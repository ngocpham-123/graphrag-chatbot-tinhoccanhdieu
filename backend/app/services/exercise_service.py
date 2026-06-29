"""LLM-graded interactive exercises over the curriculum in GraphDB.

Resolves assessment items by IRI, grounds grading in the item's lesson content
(via curriculum_service), and grades free-text answers with gpt-4.1-mini.
Reuses curriculum_service for all SPARQL/validation/normalization.
"""
import logging

from backend.app.services import curriculum_service as cs

logger = logging.getLogger(__name__)

ASSESSMENT_LOCALNAMES = (
    "ReviewQuestionItem", "Exercise", "PracticeExercise", "AppliedTask",
    "PracticeTask", "PracticalInstruction", "ProjectTask", "Activity",
)


class GradingError(Exception):
    """The grading LLM call failed."""


def get_exercise(exercise_id: str) -> dict:
    """Resolve an assessment item by IRI local-name.

    Returns {id, type, title, text, lessonId}. Raises NotFoundError if the id is
    malformed or is not an assessment item with hasRawText.
    """
    cs._validate_id(exercise_id)
    values = " ".join(f"ex:{t}" for t in ASSESSMENT_LOCALNAMES)
    rows = cs._run_select(f"""
        SELECT ?kind ?title ?text ?lesson WHERE {{
          VALUES ?kind {{ {values} }}
          ex:{exercise_id} a ?kind ; ex:hasRawText ?text .
          OPTIONAL {{ ex:{exercise_id} rdfs:label ?title }}
          OPTIONAL {{ ex:{exercise_id} ex:belongsToLesson ?lesson }}
        }} LIMIT 1
    """)
    if not rows:
        raise cs.NotFoundError(f"Exercise not found: {exercise_id}")
    r = rows[0]
    return {
        "id": exercise_id,
        "type": cs.local_name(r.get("kind", "")),
        "title": cs._nfc(r["title"]) if r.get("title") else None,
        "text": cs._nfc(r.get("text", "")),
        "lessonId": cs.local_name(r["lesson"]) if r.get("lesson") else None,
    }


def extract_exercises_from_rows(sparql: str, rows) -> list[dict]:
    """Turn assessment-query result rows into [{id, type, title, text}].

    Returns [] unless the query references an assessment class and the rows expose
    bound `item` and `text` variables. Pure: no network, no LLM.
    """
    rows = list(rows)
    if not rows:
        return []
    if not any(f"ex:{t}" in sparql for t in ASSESSMENT_LOCALNAMES):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        try:
            rd = row.asdict()
        except AttributeError:
            return []
        item = rd.get("item")
        text = rd.get("text")
        if item is None or text is None:
            continue
        kind_ln = cs.local_name(str(rd["kind"])) if rd.get("kind") is not None else ""
        if kind_ln and kind_ln not in ASSESSMENT_LOCALNAMES:
            continue
        iid = cs.local_name(str(item))
        if not iid or iid in seen:
            continue
        seen.add(iid)
        title = rd.get("title")
        out.append({
            "id": iid,
            "type": kind_ln,
            "title": cs._nfc(str(title)) if title is not None else None,
            "text": cs._nfc(str(text)),
        })
    return out
