"""Read-only curriculum browsing over GraphDB (SPARQL SELECT only).

Decoupled from the QA chain / langchain: talks to the same Ontotext GraphDB
repository directly via SPARQLWrapper and returns plain JSON-serializable dicts.
"""
import re
import unicodedata

from SPARQLWrapper import SPARQLWrapper, JSON

from backend.app.config import GRAPHDB_URL, GRAPHDB_REPOSITORY
from backend.app.services.figures import figure_url_for_value, local_name
from backend.app.services.content_pages import content_images_for

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
    wrapper.setTimeout(30)
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


def _lesson_header(lesson_id: str) -> dict:
    rows = _run_select(f"""
        SELECT ?label ?title ?num ?start ?end WHERE {{
          ex:{lesson_id} a ex:Lesson .
          OPTIONAL {{ ex:{lesson_id} rdfs:label ?label }}
          OPTIONAL {{ ex:{lesson_id} ex:hasTitle ?title }}
          OPTIONAL {{ ex:{lesson_id} ex:lessonNumber ?num }}
          OPTIONAL {{ ex:{lesson_id} ex:hasStartPage ?start }}
          OPTIONAL {{ ex:{lesson_id} ex:hasEndPage ?end }}
        }} LIMIT 1
    """)
    if not rows:
        raise NotFoundError(f"Lesson not found: {lesson_id}")
    r = rows[0]
    return {
        "id": lesson_id,
        "label": r.get("label", ""),
        "title": r.get("title", ""),
        "lessonNumber": _int(r.get("num")),
        "startPage": _int(r.get("start")),
        "endPage": _int(r.get("end")),
    }


def _objectives(lesson_id: str) -> list[str]:
    rows = _run_select(f"""
        SELECT ?text WHERE {{
          ?n a ex:NoteBox ; ex:belongsToLesson ex:{lesson_id} ; ex:hasRawText ?text .
        }}
    """)
    return [r["text"] for r in rows if r.get("text")]


def _summary(lesson_id: str) -> str | None:
    rows = _run_select(f"""
        SELECT ?text WHERE {{
          ?s a ex:SummaryBox ; ex:belongsToLesson ex:{lesson_id} ; ex:hasSummaryText ?text .
        }} LIMIT 1
    """)
    return rows[0]["text"] if rows else None


def _sections(lesson_id: str) -> list[dict]:
    section_rows = _run_select(f"""
        SELECT ?s ?title ?label ?order WHERE {{
          ?s a ex:Section ; ex:belongsToLesson ex:{lesson_id} .
          OPTIONAL {{ ?s ex:hasTitle ?title }}
          OPTIONAL {{ ?s rdfs:label ?label }}
          OPTIONAL {{ ?s ex:sectionOrder ?order }}
        }} ORDER BY ?order
    """)
    para_rows = _run_select(f"""
        SELECT ?p ?text ?order ?section WHERE {{
          ?p a ex:Paragraph ; ex:belongsToLesson ex:{lesson_id} ; ex:hasRawText ?text .
          OPTIONAL {{ ?p ex:paragraphOrder ?order }}
          OPTIONAL {{ ?p ex:belongsToSection ?section }}
        }} ORDER BY ?order
    """)

    paras_by_section: dict = {}
    for r in para_rows:
        sec = local_name(r["section"]) if r.get("section") else None
        paras_by_section.setdefault(sec, []).append(
            {"order": _int(r.get("order")), "text": r["text"]}
        )

    sections = []
    seen = set()
    for r in section_rows:
        sid = local_name(r["s"])
        seen.add(sid)
        sections.append(
            {
                "order": _int(r.get("order")),
                "title": r.get("title") or r.get("label", ""),
                "paragraphs": paras_by_section.get(sid, []),
            }
        )

    leftover = []
    for sec, paras in paras_by_section.items():
        if sec is None or sec not in seen:
            leftover.extend(paras)
    if leftover:
        sections.append({"order": None, "title": "(Khác)", "paragraphs": leftover})

    return sections


def _figures(lesson_id: str) -> list[dict]:
    rows = _run_select(f"""
        SELECT ?f ?caption ?type ?concept ?gorder ?porder WHERE {{
          VALUES ?type {{ ex:Figure ex:Diagram ex:Illustration }}
          ?f a ?type ; ex:belongsToLesson ex:{lesson_id} .
          OPTIONAL {{ ?f ex:hasCaption ?caption }}
          OPTIONAL {{ ?f ex:globalFigureOrder ?gorder }}
          OPTIONAL {{ ?f ex:figureOrderOnPage ?porder }}
          OPTIONAL {{ ?f ex:illustratesConcept ?c . ?c rdfs:label ?concept }}
        }} ORDER BY ?gorder ?porder
    """)
    figures = []
    seen = set()
    for r in rows:
        fid = local_name(r["f"])
        if fid in seen:
            continue
        seen.add(fid)
        figures.append(
            {
                "id": fid,
                "caption": r.get("caption", ""),
                "type": local_name(r.get("type", "")),
                "imageUrl": figure_url_for_value(r["f"]),
                "concept": r.get("concept", ""),
            }
        )
    return figures


def _tables(lesson_id: str) -> list[dict]:
    rows = _run_select(f"""
        SELECT ?t ?caption ?text ?order WHERE {{
          ?t a ex:Table ; ex:belongsToLesson ex:{lesson_id} .
          OPTIONAL {{ ?t ex:hasCaption ?caption }}
          OPTIONAL {{ ?t ex:hasRawText ?text }}
          OPTIONAL {{ ?t ex:globalTableOrder ?order }}
        }} ORDER BY ?order
    """)
    return [
        {
            "id": local_name(r["t"]),
            "caption": r.get("caption", ""),
            "text": r.get("text", ""),
        }
        for r in rows
    ]


_ASSESSMENT_TYPES = (
    "ReviewQuestionItem", "Exercise", "PracticeExercise", "AppliedTask",
    "PracticeTask", "PracticalInstruction", "ProjectTask", "Activity",
)


def _concepts(lesson_id: str) -> list[dict]:
    # Direct concepts of the lesson, PLUS a fallback: concepts of the lesson's
    # topic that are not linked to ANY lesson of that topic (e.g. grade-12/11
    # topics whose concepts were only attached at the topic level). Those
    # "unplaced" concepts would otherwise never appear on any lesson.
    rows = _run_select(f"""
        SELECT ?c ?label ?definition WHERE {{
          {{
            ex:{lesson_id} ex:hasConcept ?c .
          }} UNION {{
            ex:{lesson_id} ex:belongsToTopic ?t .
            ?t ex:hasConcept ?c .
            FILTER NOT EXISTS {{ ?al ex:belongsToTopic ?t ; ex:hasConcept ?c }}
          }}
          OPTIONAL {{ ?c rdfs:label ?label }}
          OPTIONAL {{ ?d ex:explainsConcept ?c ; ex:hasDefinitionText ?definition }}
        }} ORDER BY ?label
    """)
    concepts = []
    seen = set()
    for r in rows:
        cid = local_name(r["c"])
        if cid in seen:
            continue
        seen.add(cid)
        concepts.append(
            {
                "id": cid,
                "label": r.get("label", ""),
                "definition": r.get("definition") or None,
            }
        )
    return concepts


def _assessments(lesson_id: str) -> list[dict]:
    values = " ".join(f"ex:{t}" for t in _ASSESSMENT_TYPES)
    rows = _run_select(f"""
        SELECT ?item ?type ?title ?text WHERE {{
          VALUES ?type {{ {values} }}
          ?item a ?type ; ex:belongsToLesson ex:{lesson_id} ; ex:hasRawText ?text .
          OPTIONAL {{ ?item rdfs:label ?title }}
        }}
    """)
    items = []
    seen = set()
    for r in rows:
        iid = local_name(r["item"])
        if iid in seen:
            continue
        seen.add(iid)
        items.append(
            {
                "id": iid,
                "type": local_name(r.get("type", "")),
                "title": r.get("title") or None,
                "text": r.get("text", ""),
            }
        )
    return items


def lesson_detail(lesson_id: str) -> dict:
    _validate_id(lesson_id)
    detail = _lesson_header(lesson_id)
    detail["objectives"] = _objectives(lesson_id)
    detail["summary"] = _summary(lesson_id)
    detail["sections"] = _sections(lesson_id)
    detail["figures"] = _figures(lesson_id)
    detail["tables"] = _tables(lesson_id)
    detail["concepts"] = _concepts(lesson_id)
    detail["assessments"] = _assessments(lesson_id)
    detail["contentImages"] = content_images_for(lesson_id)
    return detail
