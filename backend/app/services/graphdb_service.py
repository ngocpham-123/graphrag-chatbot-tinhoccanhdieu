import logging
import unicodedata

from langchain_community.graphs import OntotextGraphDBGraph

from backend.app.config import GRAPHDB_URL, GRAPHDB_REPOSITORY

logger = logging.getLogger(__name__)

SPARQL_ENDPOINT = f"{GRAPHDB_URL}/repositories/{GRAPHDB_REPOSITORY}"

# Ontology-only (TBox) CONSTRUCT. The previous query, CONSTRUCT {?s ?p ?o}
# WHERE {?s ?p ?o}, returned the ENTIRE graph (~34k triples of instance data +
# Vietnamese text) as the "schema", drowning the real ontology and making SPARQL
# generation unreliable. This returns only class/property declarations with their
# labels, domains, ranges and hierarchy (~361 triples), giving the LLM a clean schema.
ONTOLOGY_QUERY = """\
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
CONSTRUCT { ?s ?p ?o } WHERE {
  ?s ?p ?o . ?s a ?t .
  FILTER(?t IN (owl:Class, rdfs:Class, owl:ObjectProperty, owl:DatatypeProperty,
                rdf:Property, owl:TransitiveProperty, owl:SymmetricProperty, owl:Ontology))
}"""


def create_graph(ontology_file: str | None = None) -> OntotextGraphDBGraph:
    """
    Create an OntotextGraphDBGraph instance.

    Args:
        ontology_file: Path to a local ontology file (e.g. .ttl, .rdf).
                       If None, the schema is fetched from the repository
                       using a CONSTRUCT query.
    """
    if ontology_file:
        graph = OntotextGraphDBGraph(
            query_endpoint=SPARQL_ENDPOINT,
            local_file=ontology_file,
        )
    else:
        # Fetch the ontology schema (TBox only) from the repository
        graph = OntotextGraphDBGraph(
            query_endpoint=SPARQL_ENDPOINT,
            query_ontology=ONTOLOGY_QUERY,
        )

    _install_nfc_query_normalizer(graph)

    logger.info("Connected to GraphDB at %s", SPARQL_ENDPOINT)
    logger.info("Schema:\n%s", graph.get_schema)
    return graph


def _install_nfc_query_normalizer(graph: OntotextGraphDBGraph) -> None:
    """NFC-normalize every SPARQL query before it is executed.

    The GraphDB labels are stored in Unicode NFC (composed) form, but the LLM
    tends to emit Vietnamese text in NFD (decomposed) form. Because SPARQL's
    CONTAINS/= compare codepoints exactly, an NFD term silently matches nothing
    (e.g. "thuật toán" returns 0 rows). Normalizing the generated query to NFC
    here fixes the mismatch for all queries, regardless of the model used.
    """
    original_query = graph.query

    def nfc_query(query, *args, **kwargs):
        if isinstance(query, str):
            query = unicodedata.normalize("NFC", query)
        return original_query(query, *args, **kwargs)

    graph.query = nfc_query  # type: ignore[method-assign]
