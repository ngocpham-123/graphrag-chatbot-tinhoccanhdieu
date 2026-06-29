# Interactive Exercises Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let students attempt exercises and get LLM-graded, lesson-grounded feedback + a model answer, via a shared inline "exercise runner" used in both the 📚 Thư viện Bài tập tab and the QA chatbot.

**Architecture:** A new `exercise_service.py` resolves an exercise by IRI from GraphDB, grounds via `curriculum_service.lesson_detail`, and grades with `gpt-4.1-mini`. A `POST /api/exercises/grade` endpoint exposes it. A shared `frontend/exercise.js` widget (`mountExerciseRunner`) is consumed by the Library and by the chatbot, where assessment answers surface a two-button offer. The existing QA pipeline and curriculum browser are untouched except for additive wiring.

**Tech Stack:** Python 3.11, FastAPI, langchain_openai (`gpt-4.1-mini`, already used), SPARQLWrapper/rdflib (already present), vanilla JS (no build step), pytest (already a dev dep).

## Global Constraints

- Python 3.11; FastAPI under `backend/app/`; absolute imports rooted at `backend.app.*`.
- No new runtime dependency (reuse `langchain_openai`, `SPARQLWrapper`, `rdflib`); `pytest` already present.
- Reuse `curriculum_service` helpers (`_run_select`, `_validate_id`, `_int`, `local_name`, `_nfc`, `lesson_detail`, `CurriculumError`, `NotFoundError`) — do NOT duplicate SPARQL/validation/normalization logic.
- IRI local-names are opaque IDs — never parse an IRI to infer grade/topic/lesson; validate ids with `^[A-Za-z0-9_]+$` (via `_validate_id`) before interpolating into SPARQL.
- All API string values NFC-normalized (use `curriculum_service._nfc`).
- Assessment family local-names (verbatim): `ReviewQuestionItem, Exercise, PracticeExercise, AppliedTask, PracticeTask, PracticalInstruction, ProjectTask, Activity`.
- Grading model: `ChatOpenAI(model="gpt-4.1-mini", temperature=0, api_key=OPENAI_API_KEY)`. JSON output; never 500 on malformed model reply.
- Verdict values (machine): `correct | partial | incorrect`. UI labels (Vietnamese): **Chính xác / Gần đúng / Chưa chính xác**.
- Endpoint: `POST /api/exercises/grade`, body `{exerciseId, userAnswer}` → `{verdict, feedback, modelAnswer}`. 404 unknown id; 400 empty answer; 503 GraphDB/LLM failure.
- Frontend: vanilla JS, no build step; HTML-escape all API/user text before DOM insertion.
- Tests are integration tests against live GraphDB (port 7200) and live OpenAI; they SKIP when GraphDB is unreachable (conftest autouse fixture). Run from project root with `.venv/Scripts/python.exe -m pytest`.

---

### Task 1: `exercise_service` core — `get_exercise` + `extract_exercises_from_rows`

**Files:**
- Create: `backend/app/services/exercise_service.py`
- Test: `backend/tests/test_exercise_service.py`

**Interfaces:**
- Consumes: `curriculum_service` (`_run_select`, `_validate_id`, `local_name`, `_nfc`, `NotFoundError`, `CurriculumError`)
- Produces:
  - `ASSESSMENT_LOCALNAMES: tuple[str, ...]`
  - `class GradingError(Exception)`
  - `get_exercise(exercise_id: str) -> dict` → `{id, type, title, text, lessonId}`; raises `curriculum_service.NotFoundError` if the id is malformed or not an assessment item.
  - `extract_exercises_from_rows(sparql: str, rows) -> list[dict]` → `[{id, type, title, text}]`; pure (no network/LLM); `[]` unless `sparql` references an assessment class AND rows expose `item`+`text` vars.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_exercise_service.py`:

```python
import rdflib

from backend.app.services import exercise_service as es
from backend.app.services import curriculum_service as cs


def _rows(ttl: str, query: str):
    g = rdflib.Graph()
    g.parse(data=ttl, format="turtle")
    return list(g.query(query))


def test_get_exercise_known_id():
    ex = es.get_exercise("l1_ex2")
    assert ex["id"] == "l1_ex2"
    assert ex["lessonId"] == "lesson1"
    assert ex["text"]                       # the question text
    assert ex["type"] in es.ASSESSMENT_LOCALNAMES


def test_get_exercise_unknown_raises_notfound():
    import pytest
    with pytest.raises(cs.NotFoundError):
        es.get_exercise("nosuchexercise")


def test_extract_exercises_from_assessment_rows():
    ttl = """
    @prefix ex: <http://example.org/tinhoc10-cd#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    ex:l1_ex1 a ex:Exercise ; rdfs:label "Bài 1 - Bài tập 1" ; ex:hasRawText "Nêu ví dụ minh hoạ." .
    """
    q = """PREFIX ex: <http://example.org/tinhoc10-cd#>
           PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
           SELECT ?item ?kind ?title ?text WHERE {
             ?item a ?kind ; ex:hasRawText ?text . OPTIONAL { ?item rdfs:label ?title } }"""
    rows = _rows(ttl, q)
    sparql = "SELECT ?item ?kind ?text WHERE { ?item a ex:Exercise ; ex:hasRawText ?text }"
    out = es.extract_exercises_from_rows(sparql, rows)
    assert len(out) == 1
    assert out[0]["id"] == "l1_ex1"
    assert out[0]["type"] == "Exercise"
    assert "ví dụ" in out[0]["text"]


def test_extract_exercises_ignores_non_assessment_query():
    ttl = """
    @prefix ex: <http://example.org/tinhoc10-cd#> .
    ex:p1 a ex:Paragraph ; ex:hasRawText "đoạn văn" .
    """
    q = """PREFIX ex: <http://example.org/tinhoc10-cd#>
           SELECT ?item ?kind ?text WHERE { ?item a ?kind ; ex:hasRawText ?text }"""
    rows = _rows(ttl, q)
    sparql = "SELECT ?p ?text WHERE { ?p ex:mentionsConcept ?c ; ex:hasRawText ?text }"
    assert es.extract_exercises_from_rows(sparql, rows) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_exercise_service.py -v`
Expected: FAIL — `ModuleNotFoundError: backend.app.services.exercise_service`.

- [ ] **Step 3: Create the service module**

Create `backend/app/services/exercise_service.py`:

```python
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
        "title": r.get("title") or None,
        "text": r.get("text", ""),
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_exercise_service.py -v`
Expected: PASS (4 passed). If GraphDB is down the two `get_exercise` tests SKIP; start GraphDB and re-run to confirm PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/exercise_service.py backend/tests/test_exercise_service.py
git commit -m "feat: exercise_service get_exercise + assessment-row extraction"
```

---

### Task 2: `grade_exercise` — grounded LLM grading

**Files:**
- Modify: `backend/app/services/exercise_service.py`
- Test: `backend/tests/test_exercise_service.py`

**Interfaces:**
- Consumes: `get_exercise` (Task 1); `curriculum_service.lesson_detail`, `_nfc`, `CurriculumError`; `backend.app.config.OPENAI_API_KEY`
- Produces:
  - `grade_exercise(exercise_id: str, user_answer: str) -> dict` → `{verdict, feedback, modelAnswer}` (`verdict ∈ {correct, partial, incorrect}`); raises `NotFoundError` (unknown id), `GradingError` (LLM failure).
  - `_parse_grade_json(raw: str) -> dict` (helper; tolerant; never raises).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_exercise_service.py`:

```python
def test_parse_grade_json_plain():
    d = es._parse_grade_json('{"verdict":"correct","feedback":"Tốt","modelAnswer":"Đáp án"}')
    assert d == {"verdict": "correct", "feedback": "Tốt", "modelAnswer": "Đáp án"}


def test_parse_grade_json_fenced_and_bad_verdict():
    raw = '```json\n{"verdict":"perfect","feedback":"x","modelAnswer":"y"}\n```'
    d = es._parse_grade_json(raw)
    assert d["verdict"] == "partial"          # unknown verdict normalized
    assert d["feedback"] == "x"


def test_parse_grade_json_garbage_falls_back():
    d = es._parse_grade_json("not json at all")
    assert d["verdict"] == "partial"
    assert isinstance(d["feedback"], str)
    assert d["modelAnswer"] == ""


def test_grade_correct_answer_not_incorrect():
    # l1_ex2: "đầu vào và đầu ra của một bài toán xử lí thông tin"
    res = es.grade_exercise(
        "l1_ex2",
        "Đầu vào là dữ liệu, đầu ra là thông tin hữu ích.",
    )
    assert res["verdict"] in {"correct", "partial", "incorrect"}
    assert res["verdict"] != "incorrect"
    assert res["feedback"] and res["modelAnswer"]


def test_grade_irrelevant_answer_not_correct():
    res = es.grade_exercise("l1_ex2", "Hôm nay trời mưa.")
    assert res["verdict"] != "correct"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_exercise_service.py -v -k "parse_grade or grade_"`
Expected: FAIL — `AttributeError: module ... has no attribute '_parse_grade_json'` / `grade_exercise`.

- [ ] **Step 3: Implement grading**

Add to the imports at the top of `backend/app/services/exercise_service.py`:

```python
import json
import re

from langchain_openai import ChatOpenAI

from backend.app.config import OPENAI_API_KEY
```

Then append to the module:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_exercise_service.py -v`
Expected: PASS (all). The `grade_*` tests make real OpenAI calls; they need both GraphDB and a valid `OPENAI_API_KEY`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/exercise_service.py backend/tests/test_exercise_service.py
git commit -m "feat: grade_exercise grounded LLM grading + tolerant JSON parse"
```

---

### Task 3: `/api/exercises/grade` router + `main.py` wiring

**Files:**
- Create: `backend/app/routers/exercises.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_exercises_router.py`

**Interfaces:**
- Consumes: `exercise_service` (`grade_exercise`, `GradingError`), `curriculum_service` (`NotFoundError`, `CurriculumError`)
- Produces: `router` (`APIRouter`, prefix `/api/exercises`) with `POST /grade` taking `{exerciseId, userAnswer}` → `{verdict, feedback, modelAnswer}`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_exercises_router.py`:

```python
"""Router tests mount only the exercises router (no chat startup), and mock the
grading service so they do not call OpenAI."""
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.routers import exercises
from backend.app.services import curriculum_service as cs

app = FastAPI()
app.include_router(exercises.router)
client = TestClient(app)


def test_grade_200_shape():
    fake = {"verdict": "partial", "feedback": "Cần bổ sung.", "modelAnswer": "Đáp án mẫu."}
    with patch("backend.app.routers.exercises.es.grade_exercise", return_value=fake):
        resp = client.post("/api/exercises/grade",
                           json={"exerciseId": "l1_ex2", "userAnswer": "abc"})
    assert resp.status_code == 200
    assert set(resp.json()) == {"verdict", "feedback", "modelAnswer"}


def test_grade_empty_answer_400():
    resp = client.post("/api/exercises/grade",
                       json={"exerciseId": "l1_ex2", "userAnswer": "   "})
    assert resp.status_code == 400


def test_grade_unknown_id_404():
    with patch("backend.app.routers.exercises.es.grade_exercise",
               side_effect=cs.NotFoundError("nope")):
        resp = client.post("/api/exercises/grade",
                           json={"exerciseId": "nope", "userAnswer": "abc"})
    assert resp.status_code == 404


def test_grade_graphdb_error_503():
    with patch("backend.app.routers.exercises.es.grade_exercise",
               side_effect=cs.CurriculumError("db down")):
        resp = client.post("/api/exercises/grade",
                           json={"exerciseId": "l1_ex2", "userAnswer": "abc"})
    assert resp.status_code == 503
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_exercises_router.py -v`
Expected: FAIL — `ModuleNotFoundError: backend.app.routers.exercises`.

- [ ] **Step 3: Create the router**

Create `backend/app/routers/exercises.py`:

```python
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.services import exercise_service as es
from backend.app.services import curriculum_service as cs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/exercises", tags=["exercises"])


class GradeRequest(BaseModel):
    exerciseId: str
    userAnswer: str


@router.post("/grade")
async def grade(req: GradeRequest):
    if not req.userAnswer or not req.userAnswer.strip():
        raise HTTPException(status_code=400, detail="Câu trả lời trống")
    try:
        return es.grade_exercise(req.exerciseId, req.userAnswer)
    except cs.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (cs.CurriculumError, es.GradingError) as e:
        logger.exception("Grading failed")
        raise HTTPException(status_code=503, detail=str(e))
```

- [ ] **Step 4: Register the router in `main.py`**

In `backend/app/main.py`, change:

```python
from backend.app.routers import chat, curriculum
```

to:

```python
from backend.app.routers import chat, curriculum, exercises
```

After the existing `app.include_router(curriculum.router)` line, add:

```python
app.include_router(exercises.router)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_exercises_router.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/exercises.py backend/app/main.py backend/tests/test_exercises_router.py
git commit -m "feat: POST /api/exercises/grade router"
```

---

### Task 4: Chatbot extraction wiring (backend)

**Files:**
- Modify: `backend/app/services/chatgpt_service.py` (assessment few-shot SELECT + `retrieve_context`)
- Modify: `backend/app/services/orchestrator.py`
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/routers/chat.py`
- Test: `backend/tests/test_chat_exercises.py`

**Interfaces:**
- Consumes: `exercise_service.extract_exercises_from_rows` (Task 1)
- Produces: `FormattedGraphDBQAChain.retrieve_context` now returns a 4-tuple `(context, sparql, figure_urls, exercises)`; `answer_question(...)` result dict gains `"exercises"`; `ChatResponse` gains `exercises: list | None`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_chat_exercises.py`:

```python
from backend.app.models.schemas import ChatResponse
from backend.app.services import chatgpt_service as cgs


def test_chatresponse_has_exercises_field():
    r = ChatResponse(
        reply="x", conversation_id="c1",
        exercises=[{"id": "l1_ex1", "type": "Exercise", "title": None, "text": "q"}],
    )
    assert r.exercises[0]["id"] == "l1_ex1"


def test_assessment_fewshot_selects_item_iri():
    # The assessment example must project ?item so the chat layer can extract ids.
    prompt = cgs.SPARQL_GENERATION_PROMPT
    assert "?item" in prompt
    # the assessment SELECT line must include ?item alongside ?text
    assert "SELECT ?item" in prompt or "?item ?kind" in prompt
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_chat_exercises.py -v`
Expected: FAIL — `ChatResponse` has no `exercises` field; the assessment SELECT does not yet project `?item`.

- [ ] **Step 3: Add `exercises` to `ChatResponse`**

In `backend/app/models/schemas.py`, change the `ChatResponse` class to:

```python
class ChatResponse(BaseModel):
    reply: str
    conversation_id: str
    sparql_query: str | None = None
    figure_paths: list[str] | None = None
    exercises: list[dict] | None = None
```

- [ ] **Step 4: Project `?item` in the assessment few-shot**

In `backend/app/services/chatgpt_service.py`, find the assessment example query that currently begins:

```
SELECT ?kind ?title ?text WHERE {{
```

Change that line to project the item IRI:

```
SELECT ?item ?kind ?title ?text WHERE {{
```

(The `?item` variable is already bound in that example's WHERE clause via
`?item ex:belongsToLesson ?lesson ; a ?kind ; ex:hasRawText ?text .` — only the
SELECT projection needs `?item` added.)

- [ ] **Step 5: Extend `retrieve_context` to return exercises**

In `backend/app/services/chatgpt_service.py`, add this import near the top with the
other `backend.app.services` imports:

```python
from backend.app.services.exercise_service import extract_exercises_from_rows
```

Then change the `retrieve_context` method's signature and final lines. Replace:

```python
    def retrieve_context(self, question: str) -> tuple[str, str, list[str]]:
```

with:

```python
    def retrieve_context(self, question: str) -> tuple[str, str, list[str], list[dict]]:
```

And replace the method's final three lines:

```python
        rows = list(self.graph.query(sparql))
        context = _format_query_results(rows)
        figure_urls = figure_urls_from_rows(rows)
        return context, sparql, figure_urls
```

with:

```python
        rows = list(self.graph.query(sparql))
        context = _format_query_results(rows)
        figure_urls = figure_urls_from_rows(rows)
        exercises = extract_exercises_from_rows(sparql, rows)
        return context, sparql, figure_urls, exercises
```

- [ ] **Step 6: Update the orchestrator to pass exercises through**

In `backend/app/services/orchestrator.py`, replace:

```python
    sparql_context, sparql, figure_paths = "", None, []
    try:
        sparql_context, sparql, figure_paths = qa_chain.retrieve_context(retrieval_query)
    except Exception:
        logger.exception("SPARQL retrieval failed; continuing without it")
```

with:

```python
    sparql_context, sparql, figure_paths, exercises = "", None, [], []
    try:
        sparql_context, sparql, figure_paths, exercises = qa_chain.retrieve_context(
            retrieval_query
        )
    except Exception:
        logger.exception("SPARQL retrieval failed; continuing without it")
```

And in the same file, replace the return statement:

```python
    return {
        "reply": reply,
        "sparql_query": sparql,
        "sources": sources,
        "figure_paths": figure_paths,
    }
```

with:

```python
    return {
        "reply": reply,
        "sparql_query": sparql,
        "sources": sources,
        "figure_paths": figure_paths,
        "exercises": exercises,
    }
```

- [ ] **Step 7: Pass exercises through the chat router**

In `backend/app/routers/chat.py`, inside the `chat` handler, after the line
`sparql_query = result["sparql_query"]`, add:

```python
        exercises = result.get("exercises") or None
```

Then change the `return ChatResponse(...)` call to include the new field:

```python
        return ChatResponse(
            reply=reply,
            conversation_id=conversation_id,
            sparql_query=sparql_query,
            figure_paths=figure_paths if figure_paths else None,
            exercises=exercises,
        )
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_chat_exercises.py -v`
Expected: PASS (2 passed).

- [ ] **Step 9: Manual end-to-end check (controller-run; requires GraphDB + OpenAI)**

Start the app and confirm an assessment question returns exercises:

```bash
.venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8012
```

Then:

```bash
curl -s -X POST http://127.0.0.1:8012/api/chat/ -H "Content-Type: application/json" \
  -d '{"message":"cho tôi các bài tập của bài 1 chủ đề A lớp 10"}' \
  | python -c "import sys,json;d=json.load(sys.stdin);print('exercises:',len(d.get('exercises') or []));[print(' -',e['id'],e['text'][:40]) for e in (d.get('exercises') or [])]"
```

Expected: a non-empty `exercises` list with ids like `l1_ex1`/`l1_ex2`. Stop the server (Ctrl+C) when done.

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/chatgpt_service.py backend/app/services/orchestrator.py backend/app/models/schemas.py backend/app/routers/chat.py backend/tests/test_chat_exercises.py
git commit -m "feat: surface exercises from assessment answers in chat response"
```

---

### Task 5: Shared exercise-runner widget (`exercise.js`) + styles + page includes

**Files:**
- Create: `frontend/exercise.js`
- Modify: `frontend/styles.css` (append runner styles)
- Modify: `frontend/index.html` (include exercise.js, bump versions)
- Modify: `frontend/library.html` (include exercise.js, bump versions)
- Test: `backend/tests/test_exercise_widget_pages.py`

**Interfaces:**
- Produces: global `window.mountExerciseRunner(container, exercises)` where
  `exercises = [{id, title, text}]`; POSTs `{exerciseId, userAnswer}` to
  `/api/exercises/grade`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_exercise_widget_pages.py`:

```python
def test_index_includes_exercise_js():
    html = open("frontend/index.html", encoding="utf-8").read()
    assert "/static/exercise.js" in html


def test_library_includes_exercise_js():
    html = open("frontend/library.html", encoding="utf-8").read()
    assert "/static/exercise.js" in html


def test_exercise_js_exists_and_exposes_mount():
    js = open("frontend/exercise.js", encoding="utf-8").read()
    assert "mountExerciseRunner" in js
    assert "/api/exercises/grade" in js
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_exercise_widget_pages.py -v`
Expected: FAIL — `frontend/exercise.js` does not exist; pages don't include it.

- [ ] **Step 3: Create `frontend/exercise.js`**

```javascript
// Shared interactive exercise runner. Used by the Library Bài tập tab and the
// QA chatbot. mountExerciseRunner(container, [{id, title, text}]).
(function () {
  function escHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  const VERDICT = {
    correct: ["Chính xác", "verdict-correct"],
    partial: ["Gần đúng", "verdict-partial"],
    incorrect: ["Chưa chính xác", "verdict-incorrect"],
  };

  async function gradeOne(id, answer) {
    const res = await fetch("/api/exercises/grade", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ exerciseId: id, userAnswer: answer }),
    });
    if (!res.ok) {
      let detail = "HTTP " + res.status;
      try { detail = (await res.json()).detail || detail; } catch (e) {}
      throw new Error(detail);
    }
    return res.json();
  }

  function mountExerciseRunner(container, exercises) {
    container.innerHTML = exercises
      .map(
        (ex) => `<div class="ex-runner" data-id="${escHtml(ex.id)}">
          <div class="ex-q">${ex.title ? `<strong>${escHtml(ex.title)}</strong><br>` : ""}${escHtml(ex.text)}</div>
          <textarea class="ex-input" rows="3" placeholder="Nhập câu trả lời của em..."></textarea>
          <div class="ex-actions"><button class="ex-submit">Nộp bài</button></div>
          <div class="ex-result"></div>
        </div>`
      )
      .join("");

    container.querySelectorAll(".ex-runner").forEach((el) => {
      const id = el.dataset.id;
      const input = el.querySelector(".ex-input");
      const submit = el.querySelector(".ex-submit");
      const result = el.querySelector(".ex-result");

      submit.addEventListener("click", async () => {
        const ans = input.value.trim();
        if (!ans) {
          result.innerHTML = `<div class="ex-hint">Hãy nhập câu trả lời trước khi nộp.</div>`;
          return;
        }
        submit.disabled = true;
        result.innerHTML = `<div class="ex-loading">Đang chấm…</div>`;
        try {
          const d = await gradeOne(id, ans);
          const [label, cls] = VERDICT[d.verdict] || ["Đã chấm", "verdict-partial"];
          result.innerHTML =
            `<div class="ex-verdict ${cls}">${label}</div>` +
            (d.feedback ? `<div class="ex-feedback">${escHtml(d.feedback)}</div>` : "") +
            (d.modelAnswer
              ? `<div class="ex-model"><div class="ex-model-h">Đáp án mẫu</div><div>${escHtml(d.modelAnswer)}</div></div>`
              : "") +
            `<div class="ex-actions"><button class="ex-retry">Làm lại</button></div>`;
          result.querySelector(".ex-retry").addEventListener("click", () => {
            result.innerHTML = "";
            submit.disabled = false;
            input.focus();
          });
        } catch (err) {
          result.innerHTML =
            `<div class="ex-error">Lỗi chấm bài: ${escHtml(err.message)} ` +
            `<button class="ex-retry">Thử lại</button></div>`;
          result.querySelector(".ex-retry").addEventListener("click", () => {
            result.innerHTML = "";
          });
          submit.disabled = false;
        }
      });
    });
  }

  window.mountExerciseRunner = mountExerciseRunner;
})();
```

- [ ] **Step 4: Append runner styles to `frontend/styles.css`**

```css
/* ===== Interactive exercise runner ===== */
.ex-runner { background: #f3f6fb; border: 1px solid #d8e2f0; border-radius: 10px; padding: 12px 14px; margin: 8px 0; color: #1f2a37; }
.ex-q { margin-bottom: 8px; line-height: 1.5; }
.ex-input { width: 100%; box-sizing: border-box; border: 1px solid #c3cfe0; border-radius: 8px; padding: 8px 10px; font: inherit; resize: vertical; }
.ex-actions { margin-top: 8px; }
.ex-submit, .ex-retry { background: #2e7d32; color: #fff; border: none; border-radius: 8px; padding: 7px 14px; cursor: pointer; font: inherit; }
.ex-submit:disabled { opacity: .6; cursor: default; }
.ex-retry { background: #607d8b; }
.ex-loading, .ex-hint { margin-top: 8px; color: #607d8b; }
.ex-error { margin-top: 8px; color: #c62828; }
.ex-result { margin-top: 8px; }
.ex-verdict { display: inline-block; font-weight: 700; padding: 3px 10px; border-radius: 12px; margin-bottom: 6px; }
.verdict-correct { background: #e8f5e9; color: #1b5e20; }
.verdict-partial { background: #fff8e1; color: #8d6e00; }
.verdict-incorrect { background: #ffebee; color: #b71c1c; }
.ex-feedback { line-height: 1.55; margin-bottom: 6px; }
.ex-model { background: #eef7ee; border-left: 4px solid #2e7d32; border-radius: 6px; padding: 8px 12px; }
.ex-model-h { font-weight: 700; color: #2e7d32; margin-bottom: 4px; }
/* Chat exercise offer */
.ex-offer { background: #eef3f8; border: 1px solid #d8e2f0; border-radius: 10px; padding: 10px 14px; margin: 8px 0; }
.ex-offer-q { margin-bottom: 8px; }
.ex-offer-actions { display: flex; gap: 8px; }
.ex-offer-yes { background: #2e7d32; color: #fff; border: none; border-radius: 8px; padding: 7px 14px; cursor: pointer; font: inherit; }
.ex-offer-no { background: #cfd8dc; color: #263238; border: none; border-radius: 8px; padding: 7px 14px; cursor: pointer; font: inherit; }
```

- [ ] **Step 5: Include `exercise.js` in both pages and bump cache versions**

In `frontend/library.html`, change the script include (currently `?v=7`) so
`exercise.js` loads before `library.js`:

```html
  <script src="/static/exercise.js?v=1"></script>
  <script src="/static/library.js?v=8"></script>
```

And bump its stylesheet to `?v=8`:

```html
  <link rel="stylesheet" href="/static/styles.css?v=8" />
```

In `frontend/index.html`, change the stylesheet line (currently `?v=5`) to `?v=6`:

```html
  <link rel="stylesheet" href="/static/styles.css?v=6" />
```

and add the exercise.js include immediately before the existing
`<script src="/static/app.js?v=5"></script>` line, bumping app.js too:

```html
  <script src="/static/exercise.js?v=1"></script>
  <script src="/static/app.js?v=6"></script>
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_exercise_widget_pages.py -v`
Expected: PASS (3 passed).

- [ ] **Step 7: Commit**

```bash
git add frontend/exercise.js frontend/styles.css frontend/index.html frontend/library.html backend/tests/test_exercise_widget_pages.py
git commit -m "feat: shared exercise-runner widget + styles + page includes"
```

---

### Task 6: Library Bài tập integration

**Files:**
- Modify: `frontend/library.js` (`renderAssessments` + wire toggles in `renderTabs`)

**Interfaces:**
- Consumes: `window.mountExerciseRunner` (Task 5); lesson-detail `assessments` items `{id, type, title, text}`.

- [ ] **Step 1: Update `renderAssessments` to add a per-card toggle**

In `frontend/library.js`, replace the `renderAssessments` function with:

```javascript
function renderAssessments(d) {
  if (!d.assessments || !d.assessments.length) return `<p class="empty">Không có bài tập.</p>`;
  return d.assessments
    .map(
      (a) => `<div class="assessment" data-ex-id="${esc(a.id)}">
        <div class="assessment-type">${esc(a.title || a.type)}</div>
        <p>${esc(a.text)}</p>
        <button class="ex-toggle" data-ex-id="${esc(a.id)}">✍️ Làm bài</button>
        <div class="ex-mount" data-open="0"></div>
      </div>`
    )
    .join("");
}
```

- [ ] **Step 2: Wire the toggles after the lesson renders**

In `frontend/library.js`, inside `renderTabs(d)`, find where the tab-button click
listeners are attached (the block iterating `.tab` buttons). Immediately after that
block (still inside `renderTabs`, where `d` is in scope), add:

```javascript
  view.querySelectorAll(".ex-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const card = btn.closest(".assessment");
      const mount = card.querySelector(".ex-mount");
      const ex = (d.assessments || []).find((a) => a.id === btn.dataset.exId);
      if (!ex) return;
      if (mount.dataset.open === "1") {
        mount.innerHTML = "";
        mount.dataset.open = "0";
        btn.textContent = "✍️ Làm bài";
        return;
      }
      window.mountExerciseRunner(mount, [{ id: ex.id, title: ex.title, text: ex.text }]);
      mount.dataset.open = "1";
      btn.textContent = "Ẩn";
    });
  });
```

- [ ] **Step 3: Bump the library.js cache version**

In `frontend/library.html`, change `library.js?v=8` to `library.js?v=9`.

- [ ] **Step 4: Manual verification (controller-run; requires GraphDB + OpenAI)**

Start the app (`uvicorn ... --port 8012`), open `http://127.0.0.1:8012/library` →
Lớp 10 → Chủ đề A → Bài 1 → **Bài tập** tab. For an exercise, click **✍️ Làm bài**,
type an answer, click **Nộp bài**, and confirm a verdict + feedback + "Đáp án mẫu"
appear; **Làm lại** resets; clicking the toggle again hides the runner.

- [ ] **Step 5: Commit**

```bash
git add frontend/library.js frontend/library.html
git commit -m "feat: try exercises inline in the Library Bài tập tab"
```

---

### Task 7: Chatbot two-button offer + inline runner

**Files:**
- Modify: `frontend/app.js` (offer panel, submit handler, history)

**Interfaces:**
- Consumes: `window.mountExerciseRunner` (Task 5); `data.exercises` from `ChatResponse` (Task 4).

- [ ] **Step 1: Add the offer-panel helper**

In `frontend/app.js`, add this function near `appendMessage` (after it):

```javascript
// ── Exercise offer (shown when an answer surfaced exercises) ──
function appendExerciseOffer(exercises) {
  if (!exercises || !exercises.length) return;
  const row = document.createElement("div");
  row.className = "message-row";

  const panel = document.createElement("div");
  panel.className = "ex-offer";
  panel.innerHTML =
    `<div class="ex-offer-q">Bạn có muốn thử làm các bài tập này không?</div>` +
    `<div class="ex-offer-actions">` +
    `<button class="ex-offer-yes">▶ Làm thử</button>` +
    `<button class="ex-offer-no">Bỏ qua</button>` +
    `</div><div class="ex-offer-mount"></div>`;

  panel.querySelector(".ex-offer-yes").addEventListener("click", () => {
    panel.querySelector(".ex-offer-actions").style.display = "none";
    panel.querySelector(".ex-offer-q").textContent = "Bài tập:";
    const mount = panel.querySelector(".ex-offer-mount");
    window.mountExerciseRunner(
      mount,
      exercises.map((e) => ({ id: e.id, title: e.title, text: e.text }))
    );
  });
  panel.querySelector(".ex-offer-no").addEventListener("click", () => row.remove());

  row.appendChild(panel);
  messagesContainer.appendChild(row);
}
```

- [ ] **Step 2: Call the offer after the assistant reply + store it in history**

In `frontend/app.js`, in the form-submit handler, replace:

```javascript
    conv.messages.push({
      role: "assistant",
      content: data.reply,
      sparql_query: data.sparql_query,
      figure_paths: data.figure_paths,
    });
```

with:

```javascript
    conv.messages.push({
      role: "assistant",
      content: data.reply,
      sparql_query: data.sparql_query,
      figure_paths: data.figure_paths,
      exercises: data.exercises,
    });
```

And replace:

```javascript
    appendMessage("assistant", data.reply, data.figure_paths);
    renderConversationList();
```

with:

```javascript
    appendMessage("assistant", data.reply, data.figure_paths);
    appendExerciseOffer(data.exercises);
    renderConversationList();
```

- [ ] **Step 3: Re-render the offer when loading a stored conversation**

In `frontend/app.js`, in `loadConversation`, replace:

```javascript
    appendMessage(msg.role, msg.content, msg.figure_paths, msg.image);
```

with:

```javascript
    appendMessage(msg.role, msg.content, msg.figure_paths, msg.image);
    if (msg.role === "assistant" && msg.exercises) {
      appendExerciseOffer(msg.exercises);
    }
```

- [ ] **Step 4: Bump the app.js cache version**

In `frontend/index.html`, change `app.js?v=6` to `app.js?v=7`.

- [ ] **Step 5: Manual verification (controller-run; requires GraphDB + OpenAI)**

Start the app (`uvicorn ... --port 8012`), open `http://127.0.0.1:8012/`, ask
*"cho tôi các bài tập của bài 1 chủ đề A lớp 10"*. Confirm: under the answer a panel
appears with **▶ Làm thử** / **Bỏ qua**; **Làm thử** mounts the runner with those
exercises (type an answer → **Nộp bài** → verdict + feedback + Đáp án mẫu);
**Bỏ qua** removes the panel. Ask a non-exercise question (e.g. "Thông tin là gì?")
and confirm no panel appears.

- [ ] **Step 6: Commit**

```bash
git add frontend/app.js frontend/index.html
git commit -m "feat: chatbot offers inline exercise runner for assessment answers"
```

---

## Self-Review Notes

- **Spec coverage:** grading engine + grounding (Tasks 1–2); endpoint + error mapping (Task 3); chat extraction/4-tuple/`exercises` field (Task 4); shared widget (Task 5); Library Bài tập integration (Task 6); chatbot 2-button offer + inline runner (Task 7). Verdict labels, `exerciseId`-only grading, no-persistence, NFC, IRI validation, no-new-dependency all in Global Constraints. Testing section satisfied across tasks (service integration, pure extraction/JSON-parse unit tests, router TestClient with mocks, page-include tests, controller-run manual checks for the LLM/browser paths).
- **No placeholders:** every code step has complete code; every run step has an exact command and expected result.
- **Type consistency:** `retrieve_context` 4-tuple `(context, sparql, figure_urls, exercises)` is produced in Task 4 and consumed by the orchestrator in the same task; exercise dict shape `{id, type, title, text}` from `extract_exercises_from_rows` (Task 1) is what the chat layer (Task 4) and widget (Tasks 5–7) consume; grade result `{verdict, feedback, modelAnswer}` from `grade_exercise` (Task 2) matches the router (Task 3) and widget (Task 5). Verdict set `{correct, partial, incorrect}` consistent across service, prompt, and widget.
- **Deployment:** code-only + one new static file; no new dependency, no index/image rebuild; deploy via `git pull`.
