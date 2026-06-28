# Curriculum Library Browser — Design

**Date:** 2026-06-28
**Status:** Approved (ready for implementation planning)

## Summary

Add a second, read-only section to the app — a **Curriculum Library** — living at its
own subpath (`/library`), alongside the existing QA chatbot at `/`. It lets users
drill down **Grade → Topic → Lesson** and view all of a lesson's learning resources
(objectives, sections & paragraphs, figures, tables, knowledge concepts, summary, and
assessment items/exercises) in a tabbed lesson page.

The curriculum already lives entirely in Ontotext GraphDB (the same store the chatbot
queries). Because this feature is **read-only**, it queries GraphDB live — no Postgres,
no ETL, no second container, no system-of-record migration. The feature is fully
additive: the QA pipeline is untouched.

## Goals

- Browse the full textbook structure for grades 10, 11, 12.
- For any lesson, present its content organized into four tabs:
  **Nội dung · Hình & bảng · Khái niệm · Bài tập**.
- Render figures/diagrams as images by reusing the existing figure→asset mapping.
- Keep the stack consistent: FastAPI backend + vanilla-JS frontend, no build step.

## Non-Goals (YAGNI)

- No editing/CRUD/CMS of curriculum (read-only confirmed).
- No user data: no accounts, bookmarks, notes, or progress tracking.
- No Postgres or any new datastore/container.
- No full-text search inside the library (the chatbot already covers search/Q&A).
- No static pre-generation/caching in v1 (possible later optimization; see below).

## Data Model (as ingested; source: `D:\Downloads\CD-Sparql`)

Namespace `ex: <http://example.org/tinhoc10-cd#>`. All content nodes carry
`ex:belongsToLesson`, so a lesson page is assembled by filtering on the lesson IRI.

Hierarchy and key predicates:

- `ex:GradeLevel` — `rdfs:label`, `ex:gradeNumber` (10/11/12).
- `ex:Topic` — `rdfs:label`, `ex:hasTitle`, `ex:hasSubtitle`, `ex:topicOrder`,
  `ex:belongsToGrade`, `ex:hasLesson`, `ex:hasConcept`.
- `ex:Lesson` — `rdfs:label`, `ex:hasTitle`, `ex:lessonNumber`, `ex:belongsToTopic`,
  `ex:belongsToGrade`, `ex:hasStartPage`, `ex:hasEndPage`, `ex:hasSection`,
  `ex:hasSummary`, `ex:hasConcept`.
- `ex:Section` — `rdfs:label`/`ex:hasTitle`, `ex:sectionOrder`, `ex:belongsToLesson`.
- `ex:Paragraph` — `ex:hasRawText`, `ex:paragraphOrder`, `ex:belongsToLesson`,
  `ex:belongsToSection`.
- Image resources `ex:Figure` / `ex:Diagram` / `ex:Illustration` —
  `ex:hasCaption`, `ex:figureOrderOnPage`, `ex:globalFigureOrder`,
  `ex:belongsToLesson`, `ex:illustratesConcept`. The IRI local-name maps to an asset
  image file (no extension) via `figures.py`.
- `ex:Table` — `ex:hasCaption`, `ex:hasRawText`, `ex:globalTableOrder`,
  `ex:belongsToLesson`.
- `ex:NoteBox` (objectives) — `ex:hasRawText`, `ex:belongsToLesson`.
- `ex:SummaryBox` — `ex:hasSummaryText`, `ex:belongsToLesson` (linked via
  `ex:hasSummary`).
- `ex:KnowledgeConcept` — `rdfs:label`; optional definition via a
  `ex:TextResource`/`ex:DefinitionText` with `ex:explainsConcept` + `ex:hasDefinitionText`.
- Assessment family (all `ex:belongsToLesson`, content in `ex:hasRawText`, optional
  `rdfs:label`): `ex:ReviewQuestionItem`, `ex:Exercise`, `ex:PracticeExercise`,
  `ex:AppliedTask`, `ex:PracticeTask`, `ex:PracticalInstruction`, `ex:ProjectTask`,
  plus `ex:Activity`.

### IRI uniqueness (important)

IRIs are **unique across grades** but use an **inconsistent naming convention**:
grade 10 uses bare names (`ex:topicA`, `ex:lesson1`); grades 11–12 use prefixed names
(`ex:g11_topicA`, `ex:g11_topicA_lesson1`). Therefore the implementation **must never
parse an IRI to infer grade/topic/lesson** — navigation is done purely via the
relationship predicates above. IRI local-names are treated as opaque IDs in URLs.

## Architecture

Additive, self-contained; no change to the QA chain.

- **`backend/app/services/curriculum_service.py`** — parameterized SPARQL `SELECT`
  queries against `SPARQL_ENDPOINT` (reused from `graphdb_service.py`) using
  `SPARQLWrapper` with JSON results. Pure functions returning plain dicts/lists.
  NFC-normalizes output string values for safety. No langchain/QA-chain coupling.
  IRIs are injected into queries only after validation that the local-name matches
  `^[A-Za-z0-9_]+$` (defense against injection), bound as full IRIs.
- **`backend/app/routers/curriculum.py`** — `GET` endpoints under `/api/curriculum/*`,
  registered in `main.py` via `app.include_router(...)`.
- **`backend/app/services/figures.py`** — reused unchanged to resolve image IRIs →
  `/figures/<file>` URLs.
- **Frontend** — `frontend/library.html`, `frontend/library.js`, shared
  `frontend/styles.css`; served at `/library` (FileResponse) with assets under
  `/static` (already mounted).

## REST API (read-only `GET`)

Path IDs are IRI local-names (opaque).

| Endpoint | Returns |
|---|---|
| `GET /api/curriculum/grades` | `[{id, label, gradeNumber}]` sorted by `gradeNumber` |
| `GET /api/curriculum/grades/{gradeId}/topics` | `[{id, label, title, subtitle, topicOrder, lessonCount}]` sorted by `topicOrder` |
| `GET /api/curriculum/topics/{topicId}/lessons` | `[{id, label, title, lessonNumber, startPage, endPage}]` sorted by `lessonNumber` (then label for un-numbered "tìm hiểu thêm" lessons) |
| `GET /api/curriculum/lessons/{lessonId}` | full lesson-detail object (below) |

**Lesson-detail object:**

```jsonc
{
  "id": "lesson1",
  "label": "Bài 1. Dữ liệu, thông tin và xử lí thông tin",
  "title": "Dữ liệu, thông tin và xử lí thông tin",
  "lessonNumber": 1,
  "startPage": 5,
  "endPage": 9,
  "objectives": ["Học xong bài này, em sẽ: ..."],          // 0..n NoteBox hasRawText
  "summary": "Thông tin có thể biểu diễn ...",              // string | null
  "sections": [                                             // Nội dung tab, by sectionOrder
    { "order": 1, "title": "Nguồn thông tin và dữ liệu",
      "paragraphs": [ { "order": 1, "text": "..." } ] }     // by paragraphOrder
  ],
  "figures": [                                              // Hình & bảng tab
    { "id": "fig_l1_dataInfoKnowledgePyramid", "caption": "Hình 3. ...",
      "type": "Diagram", "imageUrl": "/figures/...png", "concept": "Tháp ..." }
  ],
  "tables": [
    { "id": "table_l2_storageUnits", "caption": "Bảng 1. ...", "text": "B (Byte): ..." }
  ],
  "concepts": [                                             // Khái niệm tab
    { "id": "conceptThongTin", "label": "Thông tin", "definition": null }
  ],
  "assessments": [                                          // Bài tập tab
    { "id": "l1_ex1", "type": "Exercise", "title": null, "text": "..." }
  ]
}
```

Notes:
- `imageUrl` is `null` when no asset file matches the figure IRI; the caption still
  renders.
- Paragraphs that have no `belongsToSection` (if any) are grouped under a synthetic
  "(Khác)" section at the end so no content is lost.

## SPARQL Strategy

One focused `SELECT` per list endpoint. The lesson-detail endpoint runs a small set of
`SELECT`s (one per content type, each filtered by `belongsToLesson <lessonIRI>`) and
assembles the JSON server-side. Ordering: sections by `sectionOrder`, paragraphs by
`paragraphOrder`, figures by `globalFigureOrder` then `figureOrderOnPage`, tables by
`globalTableOrder`. Labels/titles prefer `ex:hasTitle`, falling back to `rdfs:label`.
`@vi` literals preferred where language tags exist.

## Frontend Behavior

- Vanilla JS, same look/feel as the chat page; a header nav toggles
  **Chatbot** (`/`) ↔ **Thư viện** (`/library`).
- Views: grade cards → topic cards (title + subtitle + lesson count) → lesson list →
  lesson page.
- Lesson page: breadcrumb (`Lớp 10 › Chủ đề A › Bài 1`) + four tabs
  (**Nội dung · Hình & bảng · Khái niệm · Bài tập**), default tab **Nội dung**.
- Routing via URL hash, e.g. `#/grade/grade10/topic/topicA/lesson/lesson1`, so views
  are linkable and the browser back button works. No framework, no build step.
- Loading and empty states for each view; figures shown as a responsive image grid
  with captions; clicking a figure opens it full-size (simple lightbox or new tab).

## Error Handling

- Unknown ID → `404` JSON `{ "detail": "..." }`; UI shows a "Không tìm thấy" state.
- GraphDB unreachable / query error → `503`; UI shows a retry message (mirrors chat).
- Missing optional content (no summary/objectives/figures) renders gracefully: empty
  tabs show a short "Không có nội dung" note rather than breaking.

## Testing

- `curriculum_service` unit tests against the live local GraphDB (port 7200):
  - `grades()` returns exactly grade numbers {10, 11, 12}.
  - topics for grade 10 include topic A; its lessons include `lesson1`.
  - lesson-detail for grade-10 topic-A `lesson1` returns: 6 sections, the
    data/info/knowledge-pyramid diagram (with a resolved `imageUrl`), the
    storage-units table by caption, expected concepts (e.g. "Thông tin", "Dữ liệu"),
    and at least one assessment item with non-empty text.
- Router tests via FastAPI `TestClient`: `200` shapes for each endpoint and `404` for
  an unknown lesson ID.

## Deployment

Code-only change plus new static files — no new dependency (`SPARQLWrapper>=2.0.0` is
already in `backend/requirements.txt`), no index rebuild, no image rebuild, no new
container. On the Azure VM the bind-mounted source + `uvicorn --reload` picks it up
after `git pull`.

## Future / Optional (not in v1)

- Static pre-generation (Approach C): a build script dumps one JSON per lesson for
  zero runtime GraphDB load and resilience to GraphDB downtime.
- Cross-links from a lesson's concepts into the chatbot ("Hỏi về khái niệm này").
