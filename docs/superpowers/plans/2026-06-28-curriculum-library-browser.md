# Curriculum Library Browser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only "Curriculum Library" section at `/library` that lets users drill down Grade → Topic → Lesson and view each lesson's content in a tabbed page, served live from GraphDB.

**Architecture:** A new, self-contained backend service (`curriculum_service.py`) issues SPARQL `SELECT` queries against the same GraphDB repository the chatbot uses (via `SPARQLWrapper`, no langchain), exposed through a `/api/curriculum/*` REST router. A vanilla-JS frontend (`library.html` + `library.js`) consumes the API with hash-based routing. The QA chatbot is untouched.

**Tech Stack:** Python 3.11, FastAPI, SPARQLWrapper 2.0 (already a dependency), vanilla JS (no build step), pytest (added as a dev/test dependency).

## Global Constraints

- Python 3.11; FastAPI app under `backend/app/`; imports are absolute, rooted at `backend.app.*`.
- No new runtime dependency: `SPARQLWrapper>=2.0.0` is already in `backend/requirements.txt`. `pytest` is added solely for tests.
- Frontend is vanilla JS/HTML/CSS served as static files (`/static/...`); **no build step, no framework**.
- All API paths under `/api/curriculum`; all endpoints are read-only `GET`.
- IRI local-names are treated as **opaque IDs** — never parse an IRI to infer grade/topic/lesson; navigate via predicates (`belongsToGrade`, `belongsToTopic`, `belongsToLesson`, `hasConcept`).
- All string values returned to clients are NFC-normalized (`unicodedata.normalize("NFC", ...)`).
- Reuse `backend/app/services/figures.py` (`figure_url_for_value`, `local_name`) for image URLs; do not duplicate that logic.
- Namespace: `ex: <http://example.org/tinhoc10-cd#>`.
- UI labels in Vietnamese: nav "Thư viện"/"Chatbot"; tabs "Nội dung", "Hình & bảng", "Khái niệm", "Bài tập".
- Tests are integration tests that hit the live local GraphDB at `GRAPHDB_URL` (port 7200) and **skip** (not fail) when it is unreachable. Run from project root with `.venv/Scripts/python.exe -m pytest`.

---

### Task 1: Test infra + `curriculum_service` scaffolding + `grades()`

**Files:**
- Modify: `backend/requirements.txt` (add `pytest`)
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/app/services/curriculum_service.py`
- Test: `backend/tests/test_curriculum_service.py`

**Interfaces:**
- Produces:
  - `SPARQL_ENDPOINT: str`
  - `class CurriculumError(Exception)` — GraphDB connection/query failure
  - `class NotFoundError(Exception)` — unknown/invalid entity id
  - `_run_select(query: str) -> list[dict]` — runs `PREFIXES + query`, returns list of `{var: nfc_value}` dicts
  - `_validate_id(local_id: str) -> str` — raises `NotFoundError` unless `^[A-Za-z0-9_]+$`
  - `_int(value, default=None) -> int | None`
  - `grades() -> list[dict]` with items `{id, label, gradeNumber}`

- [ ] **Step 1: Add pytest and install it**

Edit `backend/requirements.txt`, append a line:

```
pytest>=8.0.0
```

Then install:

Run: `.venv/Scripts/python.exe -m pip install "pytest>=8.0.0"`
Expected: ends with `Successfully installed pytest-...`

- [ ] **Step 2: Create the GraphDB-skip fixture**

Create `backend/tests/__init__.py` (empty file).

Create `backend/tests/conftest.py`:

```python
"""Shared test fixtures. Curriculum tests are integration tests that need a
live GraphDB; skip the whole session if it is unreachable."""
import pytest
from SPARQLWrapper import SPARQLWrapper, JSON

from backend.app.services.curriculum_service import SPARQL_ENDPOINT


@pytest.fixture(scope="session", autouse=True)
def require_graphdb():
    wrapper = SPARQLWrapper(SPARQL_ENDPOINT)
    wrapper.setReturnFormat(JSON)
    wrapper.setQuery("ASK { ?s ?p ?o }")
    try:
        wrapper.query().convert()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"GraphDB not reachable at {SPARQL_ENDPOINT}: {e}")
```

- [ ] **Step 3: Write the failing test**

Create `backend/tests/test_curriculum_service.py`:

```python
import backend.app.services.curriculum_service as cs


def test_grades_returns_10_11_12():
    result = cs.grades()
    numbers = sorted(g["gradeNumber"] for g in result)
    assert numbers == [10, 11, 12]
    for g in result:
        assert g["id"]                      # non-empty opaque id
        assert isinstance(g["label"], str)
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_curriculum_service.py -v`
Expected: FAIL — `ModuleNotFoundError`/`AttributeError` (module or `grades` not defined).

- [ ] **Step 5: Create the service module with scaffolding + `grades()`**

Create `backend/app/services/curriculum_service.py`:

```python
"""Read-only curriculum browsing over GraphDB (SPARQL SELECT only).

Decoupled from the QA chain / langchain: talks to the same Ontotext GraphDB
repository directly via SPARQLWrapper and returns plain JSON-serializable dicts.
"""
import re
import unicodedata

from SPARQLWrapper import SPARQLWrapper, JSON

from backend.app.config import GRAPHDB_URL, GRAPHDB_REPOSITORY
from backend.app.services.figures import figure_url_for_value, local_name

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
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_curriculum_service.py -v`
Expected: PASS (or SKIP if GraphDB is down — start GraphDB and re-run to confirm PASS).

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt backend/tests/__init__.py backend/tests/conftest.py backend/app/services/curriculum_service.py backend/tests/test_curriculum_service.py
git commit -m "feat: curriculum_service grades() + integration test infra"
```

---

### Task 2: `topics_for_grade()` and `lessons_for_topic()`

**Files:**
- Modify: `backend/app/services/curriculum_service.py`
- Test: `backend/tests/test_curriculum_service.py`

**Interfaces:**
- Consumes: `_run_select`, `_validate_id`, `_int`, `local_name` (Task 1)
- Produces:
  - `topics_for_grade(grade_id: str) -> list[dict]` items `{id, label, title, subtitle, topicOrder, lessonCount}`
  - `lessons_for_topic(topic_id: str) -> list[dict]` items `{id, label, title, lessonNumber, startPage, endPage}`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_curriculum_service.py`:

```python
def test_topics_for_grade10_includes_topicA_with_6_lessons():
    topics = cs.topics_for_grade("grade10")
    by_id = {t["id"]: t for t in topics}
    assert "topicA" in by_id
    assert by_id["topicA"]["lessonCount"] == 6
    assert by_id["topicA"]["title"]            # has a title


def test_topics_for_grade_invalid_id_raises_notfound():
    import pytest
    with pytest.raises(cs.NotFoundError):
        cs.topics_for_grade("bad-id")          # hyphen is invalid


def test_lessons_for_topicA_has_lesson1():
    lessons = cs.lessons_for_topic("topicA")
    by_id = {l["id"]: l for l in lessons}
    assert "lesson1" in by_id
    assert by_id["lesson1"]["lessonNumber"] == 1
    assert len(lessons) == 6
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_curriculum_service.py -v -k "topics or lessons_for"`
Expected: FAIL — `AttributeError: module ... has no attribute 'topics_for_grade'`.

- [ ] **Step 3: Implement both functions**

Append to `backend/app/services/curriculum_service.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_curriculum_service.py -v -k "topics or lessons_for"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/curriculum_service.py backend/tests/test_curriculum_service.py
git commit -m "feat: curriculum_service topics_for_grade + lessons_for_topic"
```

---

### Task 3: `lesson_detail()` core — header, objectives, summary, sections + paragraphs

**Files:**
- Modify: `backend/app/services/curriculum_service.py`
- Test: `backend/tests/test_curriculum_service.py`

**Interfaces:**
- Consumes: `_run_select`, `_validate_id`, `_int`, `local_name`, `NotFoundError` (Task 1)
- Produces:
  - `_lesson_header(lesson_id) -> dict` `{id, label, title, lessonNumber, startPage, endPage}`; raises `NotFoundError` if not a Lesson
  - `_objectives(lesson_id) -> list[str]`
  - `_summary(lesson_id) -> str | None`
  - `_sections(lesson_id) -> list[dict]` items `{order, title, paragraphs:[{order, text}]}`
  - `lesson_detail(lesson_id: str) -> dict` — for now returns header + `objectives`, `summary`, `sections`, and **empty** `figures`, `tables`, `concepts`, `assessments` (filled in Tasks 4–5)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_curriculum_service.py`:

```python
def test_lesson_detail_core_lesson1():
    d = cs.lesson_detail("lesson1")
    assert d["id"] == "lesson1"
    assert d["lessonNumber"] == 1
    assert d["title"]
    # objectives + summary come from NoteBox / SummaryBox
    assert d["objectives"] and isinstance(d["objectives"][0], str)
    assert d["summary"]
    # lesson 1 has exactly 6 sections, each with a title
    assert len(d["sections"]) == 6
    assert all(s["title"] for s in d["sections"])
    # section 1 has at least one paragraph
    first = sorted(d["sections"], key=lambda s: (s["order"] is None, s["order"]))[0]
    assert first["paragraphs"]
    assert first["paragraphs"][0]["text"]
    # keys filled by later tasks exist as lists/None already
    for key in ("figures", "tables", "concepts", "assessments"):
        assert key in d


def test_lesson_detail_unknown_raises_notfound():
    import pytest
    with pytest.raises(cs.NotFoundError):
        cs.lesson_detail("nosuchlesson")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_curriculum_service.py -v -k "lesson_detail"`
Expected: FAIL — `AttributeError: ... 'lesson_detail'`.

- [ ] **Step 3: Implement the header/objectives/summary/sections helpers + `lesson_detail`**

Append to `backend/app/services/curriculum_service.py`:

```python
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


def _summary(lesson_id: str):
    rows = _run_select(f"""
        SELECT ?text WHERE {{
          ?s ex:belongsToLesson ex:{lesson_id} ; ex:hasSummaryText ?text .
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


def lesson_detail(lesson_id: str) -> dict:
    _validate_id(lesson_id)
    detail = _lesson_header(lesson_id)
    detail["objectives"] = _objectives(lesson_id)
    detail["summary"] = _summary(lesson_id)
    detail["sections"] = _sections(lesson_id)
    detail["figures"] = []
    detail["tables"] = []
    detail["concepts"] = []
    detail["assessments"] = []
    return detail
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_curriculum_service.py -v -k "lesson_detail"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/curriculum_service.py backend/tests/test_curriculum_service.py
git commit -m "feat: curriculum_service lesson_detail core (sections/objectives/summary)"
```

---

### Task 4: `lesson_detail()` figures + tables (Hình & bảng tab)

**Files:**
- Modify: `backend/app/services/curriculum_service.py`
- Test: `backend/tests/test_curriculum_service.py`

**Interfaces:**
- Consumes: `_run_select`, `local_name`, `figure_url_for_value`, `_int` (Task 1)
- Produces:
  - `_figures(lesson_id) -> list[dict]` items `{id, caption, type, imageUrl, concept}` (`imageUrl` is `None` or `/figures/<file>`)
  - `_tables(lesson_id) -> list[dict]` items `{id, caption, text}`
  - `lesson_detail` now populates `figures` and `tables`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_curriculum_service.py`:

```python
def test_lesson_detail_figures_lesson1():
    d = cs.lesson_detail("lesson1")
    assert d["figures"]                                  # lesson 1 has figures/diagrams
    f = d["figures"][0]
    assert set(f) == {"id", "caption", "type", "imageUrl", "concept"}
    assert f["imageUrl"] is None or f["imageUrl"].startswith("/figures/")
    # the data/info/knowledge pyramid diagram belongs to lesson 1
    assert any("Tháp" in (x["caption"] or "") for x in d["figures"])


def test_lesson_detail_tables_lesson2():
    d = cs.lesson_detail("lesson2")
    captions = [t["caption"] for t in d["tables"]]
    assert any("đơn vị lưu trữ" in (c or "").lower() for c in captions)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_curriculum_service.py -v -k "figures or tables"`
Expected: FAIL — `figures`/`tables` are empty lists, assertions fail.

- [ ] **Step 3: Implement `_figures` and `_tables`, wire into `lesson_detail`**

Append these two functions to `backend/app/services/curriculum_service.py`:

```python
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
```

In `lesson_detail`, replace the two lines:

```python
    detail["figures"] = []
    detail["tables"] = []
```

with:

```python
    detail["figures"] = _figures(lesson_id)
    detail["tables"] = _tables(lesson_id)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_curriculum_service.py -v -k "figures or tables"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/curriculum_service.py backend/tests/test_curriculum_service.py
git commit -m "feat: curriculum_service lesson figures + tables"
```

---

### Task 5: `lesson_detail()` concepts + assessments (Khái niệm + Bài tập tabs)

**Files:**
- Modify: `backend/app/services/curriculum_service.py`
- Test: `backend/tests/test_curriculum_service.py`

**Interfaces:**
- Consumes: `_run_select`, `local_name` (Task 1)
- Produces:
  - `_ASSESSMENT_TYPES: tuple[str, ...]`
  - `_concepts(lesson_id) -> list[dict]` items `{id, label, definition}` (`definition` is `str | None`)
  - `_assessments(lesson_id) -> list[dict]` items `{id, type, title, text}` (`title` is `str | None`)
  - `lesson_detail` now populates `concepts` and `assessments`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_curriculum_service.py`:

```python
def test_lesson_detail_concepts_lesson1():
    d = cs.lesson_detail("lesson1")
    labels = [c["label"] for c in d["concepts"]]
    assert "Thông tin" in labels
    assert "Dữ liệu" in labels
    for c in d["concepts"]:
        assert set(c) == {"id", "label", "definition"}


def test_lesson_detail_assessments_lesson1():
    d = cs.lesson_detail("lesson1")
    assert d["assessments"]                       # lesson 1 has exercises/activities
    item = d["assessments"][0]
    assert set(item) == {"id", "type", "title", "text"}
    assert any(a["text"] for a in d["assessments"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_curriculum_service.py -v -k "concepts or assessments"`
Expected: FAIL — `concepts`/`assessments` are empty.

- [ ] **Step 3: Implement `_concepts` and `_assessments`, wire into `lesson_detail`**

Append to `backend/app/services/curriculum_service.py`:

```python
_ASSESSMENT_TYPES = (
    "ReviewQuestionItem", "Exercise", "PracticeExercise", "AppliedTask",
    "PracticeTask", "PracticalInstruction", "ProjectTask", "Activity",
)


def _concepts(lesson_id: str) -> list[dict]:
    rows = _run_select(f"""
        SELECT ?c ?label ?definition WHERE {{
          ex:{lesson_id} ex:hasConcept ?c .
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
```

In `lesson_detail`, replace:

```python
    detail["concepts"] = []
    detail["assessments"] = []
```

with:

```python
    detail["concepts"] = _concepts(lesson_id)
    detail["assessments"] = _assessments(lesson_id)
```

- [ ] **Step 4: Run the full service test suite to verify all pass**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_curriculum_service.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/curriculum_service.py backend/tests/test_curriculum_service.py
git commit -m "feat: curriculum_service lesson concepts + assessments"
```

---

### Task 6: REST router + `main.py` wiring

**Files:**
- Create: `backend/app/routers/curriculum.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_curriculum_router.py`

**Interfaces:**
- Consumes: `curriculum_service` (`grades`, `topics_for_grade`, `lessons_for_topic`, `lesson_detail`, `CurriculumError`, `NotFoundError`)
- Produces: `router` (`APIRouter`, prefix `/api/curriculum`) with:
  - `GET /api/curriculum/grades`
  - `GET /api/curriculum/grades/{grade_id}/topics`
  - `GET /api/curriculum/topics/{topic_id}/lessons`
  - `GET /api/curriculum/lessons/{lesson_id}`

- [ ] **Step 1: Write the failing router tests**

Create `backend/tests/test_curriculum_router.py`:

```python
"""Router tests use a minimal app that mounts ONLY the curriculum router,
so the heavy chat-startup (OpenAI + Chroma) is not triggered."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.routers import curriculum

app = FastAPI()
app.include_router(curriculum.router)
client = TestClient(app)


def test_get_grades_200():
    resp = client.get("/api/curriculum/grades")
    assert resp.status_code == 200
    nums = sorted(g["gradeNumber"] for g in resp.json())
    assert nums == [10, 11, 12]


def test_get_topics_200():
    resp = client.get("/api/curriculum/grades/grade10/topics")
    assert resp.status_code == 200
    assert any(t["id"] == "topicA" for t in resp.json())


def test_get_lessons_200():
    resp = client.get("/api/curriculum/topics/topicA/lessons")
    assert resp.status_code == 200
    assert any(l["id"] == "lesson1" for l in resp.json())


def test_get_lesson_detail_200():
    resp = client.get("/api/curriculum/lessons/lesson1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "lesson1"
    assert len(body["sections"]) == 6


def test_get_lesson_detail_unknown_404():
    resp = client.get("/api/curriculum/lessons/nosuchlesson")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_curriculum_router.py -v`
Expected: FAIL — `ModuleNotFoundError: backend.app.routers.curriculum`.

- [ ] **Step 3: Create the router**

Create `backend/app/routers/curriculum.py`:

```python
import logging

from fastapi import APIRouter, HTTPException

from backend.app.services import curriculum_service as cs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/curriculum", tags=["curriculum"])


@router.get("/grades")
async def get_grades():
    try:
        return cs.grades()
    except cs.CurriculumError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/grades/{grade_id}/topics")
async def get_topics(grade_id: str):
    try:
        return cs.topics_for_grade(grade_id)
    except cs.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except cs.CurriculumError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/topics/{topic_id}/lessons")
async def get_lessons(topic_id: str):
    try:
        return cs.lessons_for_topic(topic_id)
    except cs.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except cs.CurriculumError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/lessons/{lesson_id}")
async def get_lesson(lesson_id: str):
    try:
        return cs.lesson_detail(lesson_id)
    except cs.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except cs.CurriculumError as e:
        raise HTTPException(status_code=503, detail=str(e))
```

- [ ] **Step 4: Register the router and add the `/library` route in `main.py`**

In `backend/app/main.py`, change the import line:

```python
from backend.app.routers import chat
```

to:

```python
from backend.app.routers import chat, curriculum
```

After the existing `app.include_router(chat.router)` line, add:

```python
app.include_router(curriculum.router)
```

After the existing `serve_frontend` route, add a new route:

```python
@app.get("/library")
async def serve_library():
    return FileResponse("frontend/library.html")
```

- [ ] **Step 5: Run the router tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_curriculum_router.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/curriculum.py backend/app/main.py backend/tests/test_curriculum_router.py
git commit -m "feat: /api/curriculum router + /library route"
```

---

### Task 7: Frontend — drill-down + tabbed lesson page

**Files:**
- Create: `frontend/library.html`
- Create: `frontend/library.js`
- Modify: `frontend/styles.css` (append library styles)
- Modify: `frontend/index.html` (add a nav link to the library)
- Test: `backend/tests/test_library_page.py` (serves the page) + manual browser verification

**Interfaces:**
- Consumes: `GET /api/curriculum/grades`, `/grades/{id}/topics`, `/topics/{id}/lessons`, `/lessons/{id}` (Task 6)
- Produces: a working `/library` UI with hash routes `#/`, `#/grade/<id>`, `#/topic/<id>`, `#/lesson/<id>`

- [ ] **Step 1: Write the failing page-serving test**

Create `backend/tests/test_library_page.py`:

```python
"""Verify the /library route serves the library HTML shell.
Uses a minimal app with just the route, avoiding chat startup."""
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.testclient import TestClient


def _make_app():
    app = FastAPI()

    @app.get("/library")
    async def serve_library():
        return FileResponse("frontend/library.html")

    return app


def test_library_file_exists():
    assert os.path.isfile("frontend/library.html")


def test_library_route_serves_html():
    client = TestClient(_make_app())
    resp = client.get("/library")
    assert resp.status_code == 200
    assert "Thư viện" in resp.text
    assert "/static/library.js" in resp.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_library_page.py -v`
Expected: FAIL — `frontend/library.html` does not exist.

- [ ] **Step 3: Create `frontend/library.html`**

```html
<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Thư viện học liệu – Tin Học Cánh Diều</title>
  <link rel="stylesheet" href="/static/styles.css?v=6" />
</head>
<body>
  <div class="lib-app">
    <header class="lib-header">
      <h1 class="lib-title">📚 Thư viện học liệu</h1>
      <nav class="lib-nav">
        <a href="/">💬 Chatbot</a>
        <a href="/library" class="active">📚 Thư viện</a>
      </nav>
    </header>

    <nav id="breadcrumb" class="breadcrumb" aria-label="breadcrumb"></nav>

    <main id="view" class="lib-view">
      <div class="lib-loading">Đang tải…</div>
    </main>
  </div>

  <script src="/static/library.js?v=6"></script>
</body>
</html>
```

- [ ] **Step 4: Create `frontend/library.js`**

```javascript
// Read-only curriculum library. Hash routes:
//   #/                       -> grade list
//   #/grade/<gradeId>        -> topics in grade
//   #/topic/<topicId>        -> lessons in topic
//   #/lesson/<lessonId>      -> lesson detail (tabbed)
const view = document.getElementById("view");
const breadcrumb = document.getElementById("breadcrumb");

const esc = (s) =>
  String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

async function api(path) {
  const res = await fetch(path);
  if (res.status === 404) throw { kind: "notfound" };
  if (!res.ok) throw { kind: "error", status: res.status };
  return res.json();
}

function setLoading() {
  view.innerHTML = `<div class="lib-loading">Đang tải…</div>`;
}
function setError(msg) {
  view.innerHTML = `<div class="lib-error">${esc(msg)}</div>`;
}
function setBreadcrumb(parts) {
  breadcrumb.innerHTML = parts
    .map((p, i) =>
      p.href
        ? `<a href="${p.href}">${esc(p.label)}</a>`
        : `<span>${esc(p.label)}</span>`
    )
    .join('<span class="sep">›</span>');
}

// ---- Views ----
async function showGrades() {
  setBreadcrumb([{ label: "Thư viện" }]);
  setLoading();
  try {
    const grades = await api("/api/curriculum/grades");
    view.innerHTML = `<div class="card-grid">${grades
      .map(
        (g) => `<a class="card grade-card" href="#/grade/${encodeURIComponent(g.id)}">
            <div class="card-title">${esc(g.label || "Lớp " + g.gradeNumber)}</div>
          </a>`
      )
      .join("")}</div>`;
  } catch (e) {
    setError("Không tải được danh sách lớp. Vui lòng thử lại.");
  }
}

async function showTopics(gradeId) {
  setBreadcrumb([{ label: "Thư viện", href: "#/" }, { label: gradeId }]);
  setLoading();
  try {
    const topics = await api(`/api/curriculum/grades/${encodeURIComponent(gradeId)}/topics`);
    if (!topics.length) return setError("Lớp này chưa có chủ đề nào.");
    setBreadcrumb([
      { label: "Thư viện", href: "#/" },
      { label: topics[0] ? "Lớp " : gradeId },
    ]);
    view.innerHTML = `<div class="card-grid">${topics
      .map(
        (t) => `<a class="card topic-card" href="#/topic/${encodeURIComponent(t.id)}">
            <div class="card-title">${esc(t.label || t.title)}</div>
            ${t.subtitle ? `<div class="card-sub">${esc(t.subtitle)}</div>` : ""}
            <div class="card-meta">${t.lessonCount} bài</div>
          </a>`
      )
      .join("")}</div>`;
  } catch (e) {
    setError(e.kind === "notfound" ? "Không tìm thấy lớp." : "Không tải được chủ đề.");
  }
}

async function showLessons(topicId) {
  setBreadcrumb([{ label: "Thư viện", href: "#/" }, { label: topicId }]);
  setLoading();
  try {
    const lessons = await api(`/api/curriculum/topics/${encodeURIComponent(topicId)}/lessons`);
    if (!lessons.length) return setError("Chủ đề này chưa có bài học nào.");
    view.innerHTML = `<div class="lesson-list">${lessons
      .map(
        (l) => `<a class="lesson-row" href="#/lesson/${encodeURIComponent(l.id)}">
            <span class="lesson-name">${esc(l.label || l.title)}</span>
            ${l.startPage ? `<span class="lesson-pages">tr. ${l.startPage}–${l.endPage}</span>` : ""}
          </a>`
      )
      .join("")}</div>`;
  } catch (e) {
    setError(e.kind === "notfound" ? "Không tìm thấy chủ đề." : "Không tải được bài học.");
  }
}

function renderTabs(d) {
  const tabs = [
    { key: "noidung", label: "Nội dung" },
    { key: "hinhbang", label: "Hình & bảng" },
    { key: "khainiem", label: "Khái niệm" },
    { key: "baitap", label: "Bài tập" },
  ];
  const panels = {
    noidung: renderContent(d),
    hinhbang: renderFiguresTables(d),
    khainiem: renderConcepts(d),
    baitap: renderAssessments(d),
  };
  view.innerHTML = `
    <article class="lesson">
      <h2 class="lesson-heading">${esc(d.label || d.title)}</h2>
      ${
        d.objectives && d.objectives.length
          ? `<section class="objectives"><h3>Mục tiêu</h3>${d.objectives
              .map((o) => `<p>${esc(o)}</p>`)
              .join("")}</section>`
          : ""
      }
      <div class="tabbar" role="tablist">
        ${tabs
          .map(
            (t, i) =>
              `<button class="tab${i === 0 ? " active" : ""}" data-tab="${t.key}">${t.label}</button>`
          )
          .join("")}
      </div>
      ${tabs
        .map(
          (t, i) =>
            `<section class="tabpanel${i === 0 ? " active" : ""}" data-panel="${t.key}">${panels[t.key]}</section>`
        )
        .join("")}
    </article>`;

  view.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.dataset.tab;
      view.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
      view.querySelectorAll(".tabpanel").forEach((p) =>
        p.classList.toggle("active", p.dataset.panel === key)
      );
    });
  });
}

function renderContent(d) {
  const empty = `<p class="empty">Không có nội dung.</p>`;
  if (!d.sections || !d.sections.length) return empty;
  return d.sections
    .map(
      (s) => `<div class="section">
        <h3 class="section-title">${esc(s.title)}</h3>
        ${(s.paragraphs || []).map((p) => `<p>${esc(p.text)}</p>`).join("")}
      </div>`
    )
    .join("");
}

function renderFiguresTables(d) {
  const figs = (d.figures || [])
    .map(
      (f) => `<figure class="fig">
        ${
          f.imageUrl
            ? `<a href="${f.imageUrl}" target="_blank" rel="noopener"><img src="${f.imageUrl}" alt="${esc(f.caption)}" loading="lazy"/></a>`
            : `<div class="fig-noimg">🖼️</div>`
        }
        <figcaption>${esc(f.caption)}</figcaption>
      </figure>`
    )
    .join("");
  const tables = (d.tables || [])
    .map(
      (t) => `<div class="tbl">
        <div class="tbl-caption">${esc(t.caption)}</div>
        <p class="tbl-text">${esc(t.text)}</p>
      </div>`
    )
    .join("");
  if (!figs && !tables) return `<p class="empty">Không có hình ảnh hoặc bảng.</p>`;
  return `${figs ? `<div class="fig-grid">${figs}</div>` : ""}${tables}`;
}

function renderConcepts(d) {
  if (!d.concepts || !d.concepts.length) return `<p class="empty">Không có khái niệm.</p>`;
  return `<div class="concept-chips">${d.concepts
    .map(
      (c) =>
        `<span class="chip"${c.definition ? ` title="${esc(c.definition)}"` : ""}>${esc(c.label)}</span>`
    )
    .join("")}</div>`;
}

function renderAssessments(d) {
  if (!d.assessments || !d.assessments.length) return `<p class="empty">Không có bài tập.</p>`;
  return d.assessments
    .map(
      (a) => `<div class="assessment">
        <div class="assessment-type">${esc(a.title || a.type)}</div>
        <p>${esc(a.text)}</p>
      </div>`
    )
    .join("");
}

async function showLesson(lessonId) {
  setBreadcrumb([{ label: "Thư viện", href: "#/" }, { label: "Bài học" }]);
  setLoading();
  try {
    const d = await api(`/api/curriculum/lessons/${encodeURIComponent(lessonId)}`);
    setBreadcrumb([{ label: "Thư viện", href: "#/" }, { label: d.label || d.title }]);
    renderTabs(d);
  } catch (e) {
    setError(e.kind === "notfound" ? "Không tìm thấy bài học." : "Không tải được bài học.");
  }
}

// ---- Router ----
function route() {
  const hash = location.hash.replace(/^#/, "") || "/";
  const m = hash.match(/^\/(grade|topic|lesson)\/(.+)$/);
  if (!m) return showGrades();
  const id = decodeURIComponent(m[2]);
  if (m[1] === "grade") return showTopics(id);
  if (m[1] === "topic") return showLessons(id);
  if (m[1] === "lesson") return showLesson(id);
  return showGrades();
}

window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", route);
```

- [ ] **Step 5: Append library styles to `frontend/styles.css`**

Append:

```css
/* ===== Curriculum Library ===== */
.lib-app { max-width: 1000px; margin: 0 auto; padding: 16px; }
.lib-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.lib-title { font-size: 1.4rem; margin: 0; }
.lib-nav a { margin-left: 12px; text-decoration: none; color: #2e7d32; font-weight: 600; }
.lib-nav a.active { text-decoration: underline; }
.breadcrumb { margin: 12px 0; font-size: 0.95rem; color: #555; }
.breadcrumb a { color: #2e7d32; text-decoration: none; }
.breadcrumb .sep { margin: 0 8px; color: #aaa; }
.lib-loading, .lib-error, .empty { padding: 24px; color: #666; text-align: center; }
.lib-error { color: #c62828; }
.card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; }
.card { display: block; padding: 18px; border-radius: 12px; background: #e8f5e9; color: #1b5e20;
  text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,.08); transition: transform .08s, box-shadow .08s; }
.card:hover { transform: translateY(-2px); box-shadow: 0 4px 10px rgba(0,0,0,.12); }
.card-title { font-weight: 700; font-size: 1.05rem; }
.card-sub { margin-top: 6px; font-size: .9rem; color: #33691e; }
.card-meta { margin-top: 10px; font-size: .8rem; color: #558b2f; }
.lesson-list { display: flex; flex-direction: column; gap: 8px; }
.lesson-row { display: flex; justify-content: space-between; align-items: center; gap: 12px;
  padding: 14px 16px; border-radius: 10px; background: #f1f8e9; color: #1b5e20; text-decoration: none; }
.lesson-row:hover { background: #dcedc8; }
.lesson-pages { font-size: .8rem; color: #777; white-space: nowrap; }
.lesson-heading { margin: 8px 0 4px; }
.objectives { background: #fffde7; border-left: 4px solid #fbc02d; padding: 10px 14px; border-radius: 6px; margin: 10px 0; }
.objectives h3 { margin: 0 0 6px; font-size: 1rem; }
.tabbar { display: flex; gap: 4px; border-bottom: 2px solid #e0e0e0; margin: 16px 0 0; flex-wrap: wrap; }
.tab { border: none; background: none; padding: 10px 16px; cursor: pointer; font-size: .95rem;
  color: #555; border-bottom: 3px solid transparent; }
.tab.active { color: #2e7d32; border-bottom-color: #2e7d32; font-weight: 700; }
.tabpanel { display: none; padding: 16px 0; }
.tabpanel.active { display: block; }
.section { margin-bottom: 18px; }
.section-title { font-size: 1.05rem; color: #2e7d32; margin: 0 0 6px; }
.fig-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 14px; margin-bottom: 16px; }
.fig { margin: 0; }
.fig img { width: 100%; height: auto; border-radius: 8px; border: 1px solid #eee; }
.fig-noimg { font-size: 2rem; text-align: center; padding: 24px; background: #f5f5f5; border-radius: 8px; }
.fig figcaption { font-size: .85rem; color: #555; margin-top: 4px; }
.tbl { background: #f9fbe7; border-radius: 8px; padding: 12px 14px; margin-bottom: 12px; }
.tbl-caption { font-weight: 600; margin-bottom: 4px; }
.concept-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { background: #e1f5fe; color: #01579b; padding: 6px 12px; border-radius: 16px; font-size: .9rem; cursor: default; }
.assessment { background: #fce4ec; border-radius: 8px; padding: 12px 14px; margin-bottom: 10px; }
.assessment-type { font-weight: 600; color: #ad1457; margin-bottom: 4px; }
```

- [ ] **Step 6: Add a library link in the chat page header**

In `frontend/index.html`, locate the `<header class="chat-header">` block (around line 39) and add a navigation link to the library inside it. Add this element just inside the header (adjust to sit alongside the existing title):

```html
    <a href="/library" class="header-lib-link" title="Thư viện học liệu">📚 Thư viện</a>
```

Then append this style to `frontend/styles.css`:

```css
.header-lib-link { margin-left: auto; text-decoration: none; color: #2e7d32; font-weight: 600; }
```

- [ ] **Step 7: Run the page-serving test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_library_page.py -v`
Expected: PASS.

- [ ] **Step 8: Manual browser verification**

Start the app (ensure GraphDB is running on 7200):

Run: `.venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000`

In a browser, open `http://127.0.0.1:8000/library` and verify:
1. Three grade cards (Lớp 10/11/12) appear.
2. Click Lớp 10 → topic cards show titles, subtitles, and "N bài".
3. Click Chủ đề A → lesson list appears; click Bài 1.
4. Lesson page shows the four tabs (Nội dung / Hình & bảng / Khái niệm / Bài tập); switching tabs works; Nội dung shows sections + paragraphs; Hình & bảng shows images (where assets exist) + the storage-units table on Bài 2; Khái niệm shows chips incl. "Thông tin"/"Dữ liệu"; Bài tập shows exercises with text.
5. Breadcrumb updates and the browser back button navigates between views.
6. From the chatbot page (`/`), the "📚 Thư viện" header link opens the library; from the library, the "💬 Chatbot" link returns.

Stop the server (Ctrl+C) when done.

- [ ] **Step 9: Commit**

```bash
git add frontend/library.html frontend/library.js frontend/styles.css frontend/index.html backend/tests/test_library_page.py
git commit -m "feat: curriculum library frontend (drill-down + tabbed lesson)"
```

---

## Self-Review Notes

- **Spec coverage:** grades/topics/lessons/lesson-detail endpoints (Tasks 1–2, 6); all four tabs' data (Tasks 3–5); figure image mapping via `figures.py` (Task 4); drill-down + tabbed UI + hash routing + nav toggle (Task 7); 404/503 error handling (Task 6 router, Task 7 UI states); read-only/no-Postgres/no-new-dep (Global Constraints); IRI-opaque navigation (Global Constraints, all queries). Testing section satisfied by Tasks 1–7 tests.
- **No placeholders:** every code step contains complete code; every run step has an exact command and expected result.
- **Type consistency:** `lesson_detail` keys (`objectives`, `summary`, `sections`, `figures`, `tables`, `concepts`, `assessments`) are defined in Task 3 and only populated (not renamed) in Tasks 4–5; the frontend (Task 7) reads exactly those keys and the documented item shapes.
- **Deployment:** code-only + static files; deploy via `git pull` (uvicorn `--reload`); `pytest` is a test-only dependency and need not be installed in the prod image.
