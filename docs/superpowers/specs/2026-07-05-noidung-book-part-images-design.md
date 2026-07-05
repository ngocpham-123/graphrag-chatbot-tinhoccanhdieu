# "Nội dung" Real Book Part-Images — Design

**Date:** 2026-07-05
**Status:** Approved (ready for implementation planning)

## Summary

The Library "Nội dung" tab currently shows the summarized paragraph text ingested
in GraphDB. Replace it (where available) with the **actual scanned book content**,
rendered as an ordered sequence of **per-part image crops** taken from the hoc10.vn
digital textbook. Each lesson shows its real content parts (objectives, knowledge
subsections, activities, practice, applied tasks, questions, summary) as images.

Source: hoc10.vn's public reader API exposes, per book page, a full-page scan plus
`objects` — named clickable "parts" with a polygon (`touch_vector`) in page-pixel
coordinates. We download the page scans and **crop each part's region ourselves**
(chosen over reverse-engineering hoc10's on-click `hdr` image endpoint). The part
`name` encodes grade·topic·lesson·page·part, which we map to our GraphDB lessons.

## Goals

- In "Nội dung", show a lesson's real book content as ordered part-image crops.
- Map crops to lessons using the parts' encoded names + GraphDB lesson data.
- Keep the app self-hosted: crops are stored locally and served by the app; no
  runtime dependency on hoc10.vn.
- Graceful fallback to the existing paragraph text where no crops exist.

## Non-Goals (YAGNI)

- No reverse-engineering of hoc10's click→`hdr` image endpoint (approach B, rejected).
- No per-subsection *text* alignment; parts are shown as images in reading order,
  not matched one-to-one to GraphDB `Section`/`Subsection` nodes.
- No live proxying/hot-linking to hoc10 at request time.
- No editing/annotation of crops.
- No change to other tabs (Hình & bảng, Khái niệm, Bài tập) or the chatbot.

## Source Facts (verified via browser + API)

- Reader books: grade 10 `book_id=164`, grade 11 `386`, grade 12 `737`; `app_id=68`.
- `GET https://api.hoc10.vn/api/get-detail-page?book_id=<id>&page=0&book_name=<slug>&limit=0&status=&app_id=68`
  → `data.list_page[]`, each item: `index` (1-based scan page), `background`
  (`E_Learning/page_public/<hash>.jpg`), `objects[]`.
  - Full image URL = `https://hoc10.monkeyuni.net/<background>`.
- Each `object`: `id`, `page_id`, `name`, `touch_vector` (JSON string: array of
  `{x,y}` polygon points in the page's natural pixel space, e.g. 1512×2118),
  `type`, `status`. No image URL on the object (hence we crop).
- `name` scheme **differs per grade** (verified) — the parser must handle all three:
  - Grade 10: `Tin10.<TOPICCODE>.L<lesson#>.P<page#>.<PART>` (e.g. `Tin10.CA.L1.P5.KT1`).
  - Grade 11: `SGK.TIN11THUD.<TOPICCODE>.L<lesson#>.P<page#>.<PART>` (e.g.
    `SGK.TIN11THUD.CA.L1.P5.MT`).
  - Grade 12: `Tin12.THUD.P<page#>.<TOPICLETTER><lesson#>.<PART>` (page first; e.g.
    `Tin12.THUD.P5.A1.MT` = topic A, lesson 1).
  - `TOPICCODE` (g10/g11) is `C`+letter (`CA`, `CB`, …) plus track variants for the
    CS / ICT topics; g12 uses the bare letter+number (`A1`). The generator surveys
    the actual codes per book and maps them to GraphDB topics (logging unknowns).
  - Part codes vary by grade but are **not** needed for placement (ordering is by
    page then vertical position): g10/g11 use `MT` (Mục tiêu), `KĐ` (Khởi động),
    `KT#` (Kiến thức), `HĐ`, `LT#`, `VD`, `CH#`, `TTBH`; g12 uses `MT`, `MĐ`,
    `ND#` (Nội dung), `HD`, etc. The parser only needs (grade, topic, lesson,
    page) from the name.
- `GET .../get-book-content?book_id=<id>&app_id=68` returns the TOC (chapters →
  lessons with `index_page` and titles matching GraphDB labels). Not required for
  the chosen approach (grouping is done from object names) but available as a
  cross-check.

## Architecture

Additive; only the "Nội dung" tab's data/rendering changes.

- **`backend/scripts/build_content_images.py` (new, offline)** — crawl + crop +
  map. Produces the crop images and the mapping JSON. Reuses
  `curriculum_service` helpers to resolve GraphDB lessons. Run manually, like
  `build_index.py`.
- **`asset/content_figure/` (new, gitignored)** — the cropped part images.
- **`backend/data/content_pages.json` (new, gitignored generated file)** —
  `{ "<lesson_id>": ["g10_CA_L1_P5_MT.jpg", …ordered…] }`.
- **`backend/app/services/content_pages.py` (new)** — loads the JSON at import;
  `content_images_for(lesson_id) -> list[str]` returns ordered `/content_figure/…`
  URLs (only for files that exist on disk).
- **`main.py`** — static-mount `asset/content_figure/` at `/content_figure`
  (mirrors the existing `/figures` mount).
- **`curriculum_service.lesson_detail`** — add `contentImages: list[str]` from
  `content_pages.content_images_for(lesson_id)`.
- **Frontend `library.js`** — `renderContent(d)`: if `d.contentImages` is
  non-empty, render them as an ordered, responsive column of `<img>`; else render
  the existing sections/paragraphs. Bump `library.js` cache version.

## Generator Pipeline (`build_content_images.py`)

For each book (grade → book_id → book_name slug):
1. `GET get-detail-page` with `limit=0`; collect `list_page`.
2. For each page, download `https://hoc10.monkeyuni.net/<background>` once
   (in-memory, via `requests`/`urllib`; Pillow for image ops).
3. For each `object` with a parseable `name` and valid `touch_vector`:
   - Parse the polygon → bounding box `(minx,miny,maxx,maxy)`; add small padding
     (e.g. 6 px); clamp to image bounds.
   - Crop the page image to that box; save JPEG to `asset/content_figure/` with an
     ASCII-normalized filename derived from the object name
     (Unicode diacritics stripped, non-alphanumerics → `_`), e.g.
     `Tin10.CA.L1.P5.KĐ` → `g10_CA_L1_P5_KD.jpg`. Deterministic; re-runs overwrite.
4. Parse each object `name` with the **per-grade** format (see Source Facts) to
   `(grade, topic, lesson#, page#, part)`. Group crops by `(grade, topic, lesson#)`;
   order within a group by `page#` then by the crop's top-y. Names that don't match
   any known per-grade format are logged and skipped.
5. Resolve each group to a GraphDB `lesson_id`:
   - Topic: map `TOPICCODE` → GraphDB topic. Derive the topic letter and CS/ICT
     track from the code; match against the grade's GraphDB topics (by label,
     e.g. "Chủ đề A", plus the "Khoa học máy tính"/"ứng dụng" hint for track
     variants). Build this code→topic table from GraphDB at run time.
   - Lesson: within that topic, match `lesson#` to the lesson with that
     `ex:lessonNumber` (and same grade). Extra/unnumbered lessons ("tìm hiểu
     thêm") are matched if the name carries a resolvable code, else logged.
   - Any unmapped topic code / lesson is **logged** (not silently dropped) so it
     can be reconciled.
6. Write `backend/data/content_pages.json` = `{lesson_id: [filenames in order]}`.

The script supports a **dry-run/report mode** (counts of pages, parts, crops,
lessons mapped, and unmapped codes) before writing anything.

## Data Flow (runtime)

1. User opens a lesson → `lesson_detail(lesson_id)`.
2. `content_images_for(lesson_id)` returns ordered `/content_figure/<file>` URLs
   for files present on disk.
3. Frontend "Nội dung": non-empty → render the part-image column; empty → render
   existing paragraph text (unchanged behavior).

## Error Handling

- hoc10 fetch failure during generation → the script logs and continues; partial
  output is valid (only missing pages are skipped).
- `content_pages.json` missing/empty at runtime → `content_images_for` returns
  `[]`; every lesson falls back to text. Feature is fully optional.
- A mapped filename absent on disk → filtered out (never emit a broken `<img>`).
- Malformed `touch_vector` / zero-area box → skip that part, log it.

## Testing

- **Generator**: unit-test the pure helpers with fixture JSON (no network):
  `touch_vector` → bounding box; object-name parse → `(grade, topic, lesson,
  page, part)`; filename normalization (diacritics → ASCII). Run the real crawl
  manually in report mode.
- **`content_pages` service**: unit test — given a temp JSON + files, returns
  ordered existing URLs and `[]` for unknown lessons / missing files.
- **`lesson_detail`**: integration test — a lesson known to have crops returns a
  non-empty `contentImages`; a lesson without returns `[]` (and the tab still has
  its paragraph text).
- **Frontend**: page-serving test that `library.html` references the bumped
  `library.js`; manual browser check that a grade-10 lesson shows the real book
  part-images in order and a lesson without crops still shows text.

## Deployment / Ops

- `asset/content_figure/` and `backend/data/content_pages.json` are **gitignored**
  generated artifacts (like the Chroma index). In production they are produced by
  running `build_content_images.py` once (needs outbound access to hoc10.vn +
  GraphDB up), then the app serves them. No app rebuild for the data; the code
  changes deploy via `git pull`.
- Copyright: the crops are publisher-owned textbook scans, self-hosted under
  `asset/`. Acceptable for a private academic thesis; kept out of git.

## Future / Optional (not in v1)

- Approach B (fetch hoc10's `hdr` pre-made crops) if higher fidelity is ever needed.
- Aligning each part to a specific GraphDB `Section`/`Subsection` for interleaving
  text + image.
