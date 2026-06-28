"""Read-only curriculum browsing over GraphDB (SPARQL SELECT only).

Decoupled from the QA chain / langchain: talks to the same Ontotext GraphDB
repository directly via SPARQLWrapper and returns plain JSON-serializable dicts.
"""
import re
import unicodedata

from SPARQLWrapper import SPARQLWrapper, JSON

from backend.app.config import GRAPHDB_URL, GRAPHDB_REPOSITORY
from backend.app.services.figures import local_name

SPARQL_ENDPOINT = f"{GRAPHDB_URL}/repositories/{GRAPHDB_REPOSITORY}"

PREFIXES = """\
PREFIX ex:   <http://example.org/tinhoc10-cd#>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""

_LOCALNAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


class CurriculumError(Exception):
    """GraphDB connection or query failure."""


class NotFoundError(Exception):
    """Requested curriculum entity does not exist or has an invalid id."""


def _nfc(value):
    return unicodedata.normalize("NFC", value) if isinstance(value, str) else value


def _validate_id(local_id: str) -> str:
    if not local_id or not _LOCALNAME_RE.match(local_id):
        raise NotFoundError(f"Invalid id: {local_id!r}")
    return local_id


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _run_select(query: str) -> list[dict]:
    wrapper = SPARQLWrapper(SPARQL_ENDPOINT)
    wrapper.setReturnFormat(JSON)
    wrapper.setQuery(PREFIXES + query)
    try:
        data = wrapper.query().convert()
    except Exception as e:  # network / syntax / server error
        raise CurriculumError(str(e)) from e
    return [
        {k: _nfc(v["value"]) for k, v in binding.items()}
        for binding in data["results"]["bindings"]
    ]


def grades() -> list[dict]:
    rows = _run_select("""
        SELECT ?g ?label ?num WHERE {
          ?g a ex:GradeLevel ; ex:gradeNumber ?num .
          OPTIONAL { ?g rdfs:label ?label }
        } ORDER BY ?num
    """)
    return [
        {
            "id": local_name(r["g"]),
            "label": r.get("label", ""),
            "gradeNumber": _int(r.get("num")),
        }
        for r in rows
    ]


def topics_for_grade(grade_id: str) -> list[dict]:
    _validate_id(grade_id)
    rows = _run_select(f"""
        SELECT ?t ?label ?title ?subtitle ?order
               (COUNT(DISTINCT ?lesson) AS ?lessonCount) WHERE {{
          ?t a ex:Topic ; ex:belongsToGrade ex:{grade_id} .
          OPTIONAL {{ ?t rdfs:label ?label }}
          OPTIONAL {{ ?t ex:hasTitle ?title }}
          OPTIONAL {{ ?t ex:hasSubtitle ?subtitle }}
          OPTIONAL {{ ?t ex:topicOrder ?order }}
          OPTIONAL {{ ?lesson a ex:Lesson ; ex:belongsToTopic ?t }}
        }} GROUP BY ?t ?label ?title ?subtitle ?order
          ORDER BY ?order
    """)
    return [
        {
            "id": local_name(r["t"]),
            "label": r.get("label", ""),
            "title": r.get("title", ""),
            "subtitle": r.get("subtitle", ""),
            "topicOrder": _int(r.get("order")),
            "lessonCount": _int(r.get("lessonCount"), 0),
        }
        for r in rows
    ]


def lessons_for_topic(topic_id: str) -> list[dict]:
    _validate_id(topic_id)
    rows = _run_select(f"""
        SELECT ?l ?label ?title ?num ?start ?end WHERE {{
          ?l a ex:Lesson ; ex:belongsToTopic ex:{topic_id} .
          OPTIONAL {{ ?l rdfs:label ?label }}
          OPTIONAL {{ ?l ex:hasTitle ?title }}
          OPTIONAL {{ ?l ex:lessonNumber ?num }}
          OPTIONAL {{ ?l ex:hasStartPage ?start }}
          OPTIONAL {{ ?l ex:hasEndPage ?end }}
        }} ORDER BY ?num ?label
    """)
    return [
        {
            "id": local_name(r["l"]),
            "label": r.get("label", ""),
            "title": r.get("title", ""),
            "lessonNumber": _int(r.get("num")),
            "startPage": _int(r.get("start")),
            "endPage": _int(r.get("end")),
        }
        for r in rows
    ]
