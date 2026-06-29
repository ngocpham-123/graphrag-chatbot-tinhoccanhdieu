"""LLM-graded interactive exercises over the curriculum in GraphDB.

Resolves assessment items by IRI, grounds grading in the item's lesson content
(via curriculum_service), and grades free-text answers with gpt-4.1-mini.
Reuses curriculum_service for all SPARQL/validation/normalization.
"""
import json
import logging
import re

from langchain_openai import ChatOpenAI

from backend.app.config import OPENAI_API_KEY
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


_grade_llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0, api_key=OPENAI_API_KEY)

_ALLOWED_VERDICTS = {"correct", "partial", "incorrect"}

GRADE_PROMPT = """Bạn là giáo viên Tin học. Dựa vào NỘI DUNG BÀI HỌC, hãy chấm \
câu trả lời của học sinh cho BÀI TẬP.

NỘI DUNG BÀI HỌC:
{context}

BÀI TẬP:
{question}

CÂU TRẢ LỜI CỦA HỌC SINH:
{answer}

Hãy đánh giá và CHỈ trả về một đối tượng JSON hợp lệ, không thêm bất kỳ chữ nào \
khác, theo đúng định dạng:
{{"verdict": "correct" | "partial" | "incorrect", "feedback": "<nhận xét ngắn \
gọn bằng tiếng Việt>", "modelAnswer": "<đáp án mẫu bằng tiếng Việt, bám sát nội \
dung bài học>"}}
Trong đó: "correct" = đúng và đầy đủ; "partial" = đúng một phần hoặc còn thiếu ý; \
"incorrect" = sai hoặc không liên quan."""


def _grounding_context(detail: dict) -> str:
    parts = []
    title = detail.get("label") or detail.get("title")
    if title:
        parts.append(f"Bài học: {title}")
    if detail.get("objectives"):
        parts.append("Mục tiêu: " + " ".join(detail["objectives"]))
    for s in detail.get("sections", []):
        body = " ".join(p["text"] for p in s.get("paragraphs", []) if p.get("text"))
        if body:
            parts.append(f"{s.get('title', '')}: {body}")
    defs = [f"{c['label']}: {c['definition']}"
            for c in detail.get("concepts", []) if c.get("definition")]
    if defs:
        parts.append("Khái niệm: " + " ".join(defs))
    if detail.get("summary"):
        parts.append("Tóm tắt: " + detail["summary"])
    return "\n".join(parts)[:4000]


def _parse_grade_json(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            verdict = d.get("verdict")
            if verdict not in _ALLOWED_VERDICTS:
                verdict = "partial"
            return {
                "verdict": verdict,
                "feedback": str(d.get("feedback") or ""),
                "modelAnswer": str(d.get("modelAnswer") or ""),
            }
        except (ValueError, TypeError):
            pass
    return {
        "verdict": "partial",
        "feedback": (raw or "")[:500] or "Không phân tích được phản hồi.",
        "modelAnswer": "",
    }


def grade_exercise(exercise_id: str, user_answer: str) -> dict:
    """Grade a free-text answer to an exercise, grounded in its lesson content.

    Returns {verdict, feedback, modelAnswer}. Raises NotFoundError (unknown id),
    CurriculumError (GraphDB failure), GradingError (LLM failure).
    """
    ex = get_exercise(exercise_id)
    context = ""
    if ex.get("lessonId"):
        detail = cs.lesson_detail(ex["lessonId"])
        context = _grounding_context(detail)
    prompt = GRADE_PROMPT.format(
        context=context or "(không có)",
        question=ex["text"],
        answer=user_answer,
    )
    try:
        raw = (_grade_llm.invoke(prompt).content or "").strip()
    except Exception as e:  # noqa: BLE001 — surface as 503 upstream
        logger.exception("Grading LLM call failed")
        raise GradingError(str(e)) from e
    parsed = _parse_grade_json(raw)
    return {
        "verdict": parsed["verdict"],
        "feedback": cs._nfc(parsed["feedback"]),
        "modelAnswer": cs._nfc(parsed["modelAnswer"]),
    }
