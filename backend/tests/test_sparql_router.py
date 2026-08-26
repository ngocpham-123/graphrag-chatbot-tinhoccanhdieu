"""Integration tests for /api/chat/sparql against a live GraphDB.

The endpoint is exercised as a plain function rather than through TestClient:
the chat router's startup handler builds the OpenAI chain and the Chroma store,
which these tests neither need nor should pay for.
"""
import pytest
from fastapi import HTTPException

from backend.app.routers import chat

EX = "http://example.org/tinhoc10-cd#"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"

# The shape that used to fail: a CONSTRUCT mixing resource links with literal
# labels and definition texts, which is what the app's graph view is built for.
CONSTRUCT_QUERY = f"""
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ex:   <{EX}>
CONSTRUCT {{
  ?concept rdfs:label ?conceptLabel .
  ?definition ex:explainsConcept ?concept .
  ?definition ex:hasDefinitionText ?definitionText .
  ?lesson ex:hasConcept ?concept .
  ?lesson ex:belongsToGrade ?grade .
  ?grade rdfs:label ?gradeLabel .
}}
WHERE {{
  ?concept rdf:type ex:KnowledgeConcept ; rdfs:label ?conceptLabel .
  FILTER(CONTAINS(LCASE(STR(?conceptLabel)), "cpu"))
  OPTIONAL {{
    ?definition rdf:type ex:DefinitionText ; ex:explainsConcept ?concept .
    OPTIONAL {{ ?definition ex:hasDefinitionText ?definitionText . }}
  }}
  OPTIONAL {{
    ?lesson rdf:type ex:Lesson ; ex:hasConcept ?concept .
    OPTIONAL {{ ?lesson ex:belongsToGrade ?grade . ?grade rdfs:label ?gradeLabel . }}
  }}
}}
"""


@pytest.fixture(scope="module")
def construct_result():
    return chat.execute_sparql({"query": CONSTRUCT_QUERY})


def test_construct_returns_triple_rows(construct_result):
    """The regression: this query used to come back as HTTP 400 on a bytes body."""
    assert construct_result["query_form"] == "CONSTRUCT"
    assert construct_result["columns"] == ["subject", "predicate", "object"]
    assert len(construct_result["rows"]) > 0
    assert all(len(row) == 3 for row in construct_result["rows"])


def test_construct_marks_literals_apart_from_resources(construct_result):
    """The renderer needs this to tell a linked resource from Vietnamese text."""
    kinds = {k for row in construct_result["term_types"] for k in row}
    assert kinds <= {"uri", "literal", "bnode"}

    by_predicate = {
        row[1]: kind[2]
        for row, kind in zip(construct_result["rows"], construct_result["term_types"])
    }
    assert by_predicate[RDFS_LABEL] == "literal"
    assert by_predicate[f"{EX}explainsConcept"] == "uri"


def test_construct_row_order_is_stable():
    """rdflib's store iteration order is not stable; the response must be."""
    first = chat.execute_sparql({"query": CONSTRUCT_QUERY})["rows"]
    second = chat.execute_sparql({"query": CONSTRUCT_QUERY})["rows"]
    assert first == second


def test_node_meta_carries_most_specific_type(construct_result):
    """A DefinitionText is also a TextResource and a LearningResource; colouring
    by a superclass would paint every resource in the book the same shade."""
    meta = construct_result["node_meta"]
    assert meta[f"{EX}g11_conceptCPU"]["type"] == f"{EX}KnowledgeConcept"
    assert meta[f"{EX}g11_topicA_def_cpu"]["type"] == f"{EX}DefinitionText"


def test_node_meta_carries_labels_for_captions(construct_result):
    meta = construct_result["node_meta"]
    assert meta[f"{EX}g11_conceptCPU"]["label"] == "CPU"
    assert meta[f"{EX}g11_grade11"]["label"] == "Lớp 11"


def test_node_meta_keeps_english_predicate_labels(construct_result):
    """Instance labels are tagged @vi but the ontology's property labels are
    tagged @en, so a Vietnamese-only filter would drop every edge caption."""
    meta = construct_result["node_meta"]
    assert meta[f"{EX}belongsToGrade"]["label"] == "belongs to grade"
    assert meta[f"{EX}hasConcept"]["label"] == "has concept"


def test_node_meta_omits_label_for_unlabelled_predicate(construct_result):
    """ex:hasDefinitionText has no rdfs:label, so the frontend must be free to
    fall back to its local name -- as the GraphDB Workbench does."""
    meta = construct_result["node_meta"]
    assert "label" not in meta.get(f"{EX}hasDefinitionText", {})


def test_node_meta_only_covers_resources(construct_result):
    """Literals must never turn up as nodes to be styled."""
    literals = {
        row[2]
        for row, kind in zip(construct_result["rows"], construct_result["term_types"])
        if kind[2] == "literal"
    }
    assert literals, "expected the query to return some literal objects"
    assert not (literals & set(construct_result["node_meta"]))


def test_select_still_returns_its_own_columns():
    result = chat.execute_sparql(
        {"query": f"SELECT ?s ?l WHERE {{ ?s a <{EX}Lesson> ; <{RDFS_LABEL}> ?l }} LIMIT 3"}
    )
    assert result["query_form"] == "SELECT"
    assert result["columns"] == ["s", "l"]
    assert result["term_types"][0] == ["uri", "literal"]


def test_select_projecting_resources_is_enriched():
    """A SELECT that projects URIs gets the same colouring data as a CONSTRUCT."""
    result = chat.execute_sparql(
        {"query": f"SELECT ?s WHERE {{ ?s a <{EX}Lesson> }} LIMIT 3"}
    )
    subject = result["rows"][0][0]
    assert result["node_meta"][subject]["type"] == f"{EX}Lesson"
    assert result["node_meta"][subject]["label"]


def test_select_projecting_only_literals_needs_no_lookup():
    """The reported case: every column is a label, so there is nothing to type.
    It must come back cleanly rather than paying for a pointless lookup."""
    result = chat.execute_sparql(
        {"query": f"SELECT ?l WHERE {{ ?s a <{EX}Lesson> ; <{RDFS_LABEL}> ?l }} LIMIT 3"}
    )
    assert result["term_types"][0] == ["literal"]
    assert result["node_meta"] == {}


def test_select_keeps_unbound_optional_columns():
    """head.vars is authoritative: the first binding alone would miss ?missing."""
    result = chat.execute_sparql(
        {"query": f"SELECT ?s ?missing WHERE {{ ?s a <{EX}Lesson> }} LIMIT 1"}
    )
    assert result["columns"] == ["s", "missing"]
    assert result["rows"][0][1] == ""


def test_empty_query_rejected():
    with pytest.raises(HTTPException) as excinfo:
        chat.execute_sparql({"query": "   "})
    assert excinfo.value.status_code == 400


def test_malformed_query_rejected():
    with pytest.raises(HTTPException) as excinfo:
        chat.execute_sparql({"query": "CONSTRUCT WHERE { this is not sparql"})
    assert excinfo.value.status_code == 400
