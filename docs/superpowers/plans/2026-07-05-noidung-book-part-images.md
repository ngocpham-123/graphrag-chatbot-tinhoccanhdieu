# "Nội dung" Book Part-Images Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render each lesson's real book content in the Library "Nội dung" tab as ordered per-part image crops taken from hoc10.vn page scans, falling back to the existing GraphDB paragraph text when a lesson has no crops.

**Architecture:** An offline generator downloads each grade book's page scans and crops each page `object`'s `touch_vector` region into a per-part image, mapping the parts (via their encoded names + GraphDB lesson data) to a `{lesson_id: [filenames]}` JSON. At runtime a small service serves those crops (`/content_figure` static mount) and `lesson_detail` exposes `contentImages`; the frontend renders them or falls back to text. Pure parsing/geometry logic lives in a testable `content_parsing` module; the crawl script and crops are generated artifacts.

**Tech Stack:** Python 3.11, FastAPI, Pillow + requests (generation only; already in venv), SPARQLWrapper (via curriculum_service), vanilla JS, pytest.

## Global Constraints

- Python 3.11; FastAPI under `backend/app/`; absolute imports rooted at `backend.app.*`.
- Reuse `curriculum_service` helpers (`_run_select`, `local_name`, `_nfc`, `lesson_detail`) — do not duplicate SPARQL/normalization logic.
- Runtime adds NO new dependency (serves static images + reads JSON). `Pillow`/`requests` are used only by the offline generator (already present in the venv; not added to `backend/requirements.txt`).
- Source books: grade 10 `book_id=164` slug `tin-hoc-10`; grade 11 `386` slug `tin-hoc-11-tin-hoc-ung-dung`; grade 12 `737` slug `tin-hoc-12-tin-hoc-ung-dung`; `app_id=68`.
- API: `https://api.hoc10.vn/api/get-detail-page?book_id=<id>&page=0&book_name=<slug>&limit=0&status=&app_id=68`. Image base: `https://hoc10.monkeyuni.net/` + `background`. Send headers `User-Agent: Mozilla/5.0 Chrome/120` and `Referer: https://www.hoc10.vn/`.
- Object `name` formats (per grade, verified): g10 `Tin10.<CODE>.L<n>.P<p>.<PART>`; g11 `SGK.TIN11THUD.<CODE>.L<n>.P<p>.<PART>`; g12 `Tin12.THUD.P<p>.<LETTER><n>.<PART>`. `touch_vector` is a JSON string array of `{x,y}` in page-natural pixels.
- Generated artifacts are gitignored: crops in `asset/content_figure/`; mapping `backend/data/content_pages.json` (the `backend/data` dir is already gitignored).
- Frontend: vanilla JS, no build; HTML-escape all URLs before DOM insertion; bump `library.js` cache version when changed.
- Tests are integration tests against live GraphDB (skip when down via the conftest fixture); pure-helper tests need neither GraphDB nor network. Run from project root with `.venv/Scripts/python.exe -m pytest`.

---

### Task 1: `content_parsing` — pure name/geometry/filename helpers

**Files:**
- Create: `backend/app/services/content_parsing.py`
- Test: `backend/tests/test_content_parsing.py`

**Interfaces:**
- Produces:
  - `parse_object_name(name: str) -> dict | None` → `{grade:int, topic_code:str, lesson_num:int, page_num:int, part:str}` for a recognized g10/g11/g12 name, else `None`.
  - `touch_vector_bbox(tv: str, width: int, height: int, pad: int = 6) -> tuple[int,int,int,int] | None` → `(left, top, right, bottom)` clamped to the image, or `None` if unparseable/zero-area.
  - `crop_filename(name: str) -> str` → ASCII-normalized filename, non-alphanumerics → `_`, `.jpg` suffix.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_content_parsing.py`:

```python
from backend.app.services import content_parsing as cp


def test_parse_g10_name():
    assert cp.parse_object_name("Tin10.CA.L1.P5.KT1") == {
        "grade": 10, "topic_code": "CA", "lesson_num": 1, "page_num": 5, "part": "KT1"
    }


def test_parse_g11_name():
    assert cp.parse_object_name("SGK.TIN11THUD.CA.L1.P5.MT") == {
        "grade": 11, "topic_code": "CA", "lesson_num": 1, "page_num": 5, "part": "MT"
    }


def test_parse_g12_name():
    assert cp.parse_object_name("Tin12.THUD.P5.A1.MT") == {
        "grade": 12, "topic_code": "A", "lesson_num": 1, "page_num": 5, "part": "MT"
    }


def test_parse_unknown_returns_none():
    assert cp.parse_object_name("random.thing") is None
    assert cp.parse_object_name("") is None


def test_touch_vector_bbox_basic():
    tv = '[{"x":26,"y":154},{"x":555,"y":154},{"x":555,"y":262},{"x":26,"y":262}]'
    assert cp.touch_vector_bbox(tv, 1512, 2118, pad=0) == (26, 154, 555, 262)


def test_touch_vector_bbox_pad_and_clamp():
    tv = '[{"x":0,"y":0},{"x":10,"y":10}]'
    # padded box would be (-6,-6,16,16) -> clamped to 0,0
    assert cp.touch_vector_bbox(tv, 1512, 2118, pad=6) == (0, 0, 16, 16)


def test_touch_vector_bbox_invalid():
    assert cp.touch_vector_bbox("not json", 1512, 2118) is None
    assert cp.touch_vector_bbox('[{"x":5,"y":5},{"x":5,"y":5}]', 1512, 2118, pad=0) is None


def test_crop_filename_ascii_normalizes_diacritics():
    assert cp.crop_filename("Tin10.CA.L1.P5.KĐ") == "Tin10_CA_L1_P5_KD.jpg"
    assert cp.crop_filename("Tin12.THUD.P5.A1.MĐ") == "Tin12_THUD_P5_A1_MD.jpg"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_content_parsing.py -v`
Expected: FAIL — `ModuleNotFoundError: backend.app.services.content_parsing`.

- [ ] **Step 3: Implement the module**

Create `backend/app/services/content_parsing.py`:

```python
"""Pure helpers for the hoc10 book part-image generator: object-name parsing,
touch_vector bounding boxes, and crop filenames. No network, no I/O."""
import json
import re
import unicodedata

_G10 = re.compile(r"^Tin10\.([A-Za-z]+)\.L(\d+)\.P(\d+)\.(.+)$")
_G11 = re.compile(r"^SGK\.TIN11THUD\.([A-Za-z]+)\.L(\d+)\.P(\d+)\.(.+)$")
_G12 = re.compile(r"^Tin12\.THUD\.P(\d+)\.([A-Za-z]+)(\d+)\.(.+)$")


def parse_object_name(name: str) -> dict | None:
    if not name:
        return None
    m = _G10.match(name)
    if m:
        return {"grade": 10, "topic_code": m.group(1), "lesson_num": int(m.group(2)),
                "page_num": int(m.group(3)), "part": m.group(4)}
    m = _G11.match(name)
    if m:
        return {"grade": 11, "topic_code": m.group(1), "lesson_num": int(m.group(2)),
                "page_num": int(m.group(3)), "part": m.group(4)}
    m = _G12.match(name)
    if m:
        return {"grade": 12, "topic_code": m.group(2), "lesson_num": int(m.group(3)),
                "page_num": int(m.group(1)), "part": m.group(4)}
    return None


def touch_vector_bbox(tv: str, width: int, height: int, pad: int = 6):
    try:
        pts = json.loads(tv)
        xs = [float(p["x"]) for p in pts]
        ys = [float(p["y"]) for p in pts]
    except (ValueError, TypeError, KeyError):
        return None
    if not xs or not ys:
        return None
    left = max(0, int(min(xs)) - pad)
    top = max(0, int(min(ys)) - pad)
    right = min(width, int(max(xs)) + pad)
    bottom = min(height, int(max(ys)) + pad)
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)


def crop_filename(name: str) -> str:
    ascii_name = (
        unicodedata.normalize("NFKD", name)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    slug = re.sub(r"[^A-Za-z0-9]+", "_", ascii_name).strip("_")
    return f"{slug}.jpg"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_content_parsing.py -v`
Expected: PASS (8 passed). No GraphDB/network needed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/content_parsing.py backend/tests/test_content_parsing.py
git commit -m "feat: content_parsing helpers (object names, bbox, crop filenames)"
```

---

### Task 2: `content_pages` runtime service

**Files:**
- Modify: `backend/app/config.py`
- Create: `backend/app/services/content_pages.py`
- Test: `backend/tests/test_content_pages.py`

**Interfaces:**
- Consumes: `CONTENT_FIGURE_DIR`, `CONTENT_PAGES_JSON` (config)
- Produces: `content_images_for(lesson_id: str, map_path: str = CONTENT_PAGES_JSON, img_dir: str = CONTENT_FIGURE_DIR) -> list[str]` → ordered `/content_figure/<file>` URLs for files that exist on disk; `[]` when the map/lesson/files are absent.

- [ ] **Step 1: Add config paths**

In `backend/app/config.py`, after the `FIGURES_DIR` line, add:

```python
# Cropped book part-images ("Nội dung") + their lesson mapping (generated,
# gitignored artifacts produced by backend/scripts/build_content_images.py).
CONTENT_FIGURE_DIR = os.environ.get("CONTENT_FIGURE_DIR", "asset/content_figure")
CONTENT_PAGES_JSON = os.environ.get("CONTENT_PAGES_JSON", "backend/data/content_pages.json")
```

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/test_content_pages.py`:

```python
import json
import os

from backend.app.services import content_pages as cpsvc


def test_content_images_for_returns_existing_files(tmp_path):
    img_dir = tmp_path / "cf"
    img_dir.mkdir()
    (img_dir / "a.jpg").write_bytes(b"x")
    (img_dir / "b.jpg").write_bytes(b"x")
    # "c.jpg" intentionally NOT created on disk
    map_path = tmp_path / "content_pages.json"
    map_path.write_text(json.dumps({"lesson1": ["a.jpg", "c.jpg", "b.jpg"]}), encoding="utf-8")

    urls = cpsvc.content_images_for("lesson1", map_path=str(map_path), img_dir=str(img_dir))
    assert urls == ["/content_figure/a.jpg", "/content_figure/b.jpg"]  # c.jpg dropped, order kept


def test_content_images_for_unknown_lesson(tmp_path):
    map_path = tmp_path / "m.json"
    map_path.write_text(json.dumps({"lesson1": ["a.jpg"]}), encoding="utf-8")
    assert cpsvc.content_images_for("nope", map_path=str(map_path), img_dir=str(tmp_path)) == []


def test_content_images_for_missing_map():
    assert cpsvc.content_images_for("lesson1", map_path="does/not/exist.json", img_dir=".") == []
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_content_pages.py -v`
Expected: FAIL — `ModuleNotFoundError: backend.app.services.content_pages`.

- [ ] **Step 4: Implement the service**

Create `backend/app/services/content_pages.py`:

```python
"""Serve the generated book part-image mapping for the 'Nội dung' tab.

Reads backend/data/content_pages.json ({lesson_id: [filenames]}) and returns
/content_figure/<file> URLs for the crops that actually exist on disk.
"""
import json
import os

from backend.app.config import CONTENT_FIGURE_DIR, CONTENT_PAGES_JSON


def content_images_for(
    lesson_id: str,
    map_path: str = CONTENT_PAGES_JSON,
    img_dir: str = CONTENT_FIGURE_DIR,
) -> list[str]:
    if not lesson_id or not os.path.isfile(map_path):
        return []
    try:
        with open(map_path, encoding="utf-8") as fh:
            mapping = json.load(fh)
    except (ValueError, OSError):
        return []
    files = mapping.get(lesson_id) or []
    abs_dir = os.path.abspath(img_dir)
    return [
        f"/content_figure/{f}"
        for f in files
        if os.path.isfile(os.path.join(abs_dir, f))
    ]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_content_pages.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/app/services/content_pages.py backend/tests/test_content_pages.py
git commit -m "feat: content_pages service + config paths"
```

---

### Task 3: Wire `contentImages` into lesson_detail + `/content_figure` mount + gitignore

**Files:**
- Modify: `backend/app/services/curriculum_service.py`
- Modify: `backend/app/main.py`
- Modify: `.gitignore`
- Test: `backend/tests/test_curriculum_service.py`

**Interfaces:**
- Consumes: `content_pages.content_images_for` (Task 2)
- Produces: `lesson_detail(lesson_id)` result now includes `"contentImages": list[str]`; `/content_figure/<file>` static route.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_curriculum_service.py`:

```python
def test_lesson_detail_has_contentImages_key():
    d = cs.lesson_detail("lesson1")
    assert "contentImages" in d
    assert isinstance(d["contentImages"], list)  # empty unless crops generated
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_curriculum_service.py::test_lesson_detail_has_contentImages_key -v`
Expected: FAIL — `KeyError`/`assert 'contentImages' in d` fails.

- [ ] **Step 3: Add the import and populate the field**

In `backend/app/services/curriculum_service.py`, add near the other
`backend.app.services` imports (top of file, after `from backend.app.services.figures import ...`):

```python
from backend.app.services.content_pages import content_images_for
```

In `lesson_detail`, after the line `detail["assessments"] = _assessments(lesson_id)`, add:

```python
    detail["contentImages"] = content_images_for(lesson_id)
```

- [ ] **Step 4: Mount `/content_figure` in `main.py`**

In `backend/app/main.py`, add the import at the top with the other config import
(change `from backend.app.config import FIGURES_DIR` to include the new name):

```python
from backend.app.config import FIGURES_DIR, CONTENT_FIGURE_DIR
```

After the existing `/figures` mount block (the `if os.path.isdir(figures_abs): ... else: ...`), add:

```python
content_figure_abs = os.path.abspath(CONTENT_FIGURE_DIR)
if os.path.isdir(content_figure_abs):
    app.mount("/content_figure", StaticFiles(directory=content_figure_abs), name="content_figure")
    logger.info("Serving content figures from %s at /content_figure", content_figure_abs)
else:
    logger.warning("Content figure directory not found: %s", content_figure_abs)
```

- [ ] **Step 5: Gitignore the crop directory**

In `.gitignore`, add a line:

```
asset/content_figure/
```

(`backend/data` is already ignored, so `content_pages.json` is covered.)

- [ ] **Step 6: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_curriculum_service.py -q`
Expected: PASS (all curriculum service tests; the new one included).

- [ ] **Step 7: Verify the app imports cleanly (mount code runs at import)**

Run: `.venv/Scripts/python.exe -c "import backend.app.main"`
Expected: no error (logs a warning if `asset/content_figure/` doesn't exist yet — expected before generation).

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/curriculum_service.py backend/app/main.py .gitignore backend/tests/test_curriculum_service.py
git commit -m "feat: lesson_detail contentImages + /content_figure mount"
```

---

### Task 4: Frontend — render part-images in "Nội dung" (text fallback)

**Files:**
- Modify: `frontend/library.js`
- Modify: `frontend/styles.css`
- Modify: `frontend/library.html`
- Test: `backend/tests/test_content_frontend.py`

**Interfaces:**
- Consumes: `lesson_detail.contentImages` (Task 3)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_content_frontend.py`:

```python
def test_library_js_renders_content_images():
    js = open("frontend/library.js", encoding="utf-8").read()
    assert "contentImages" in js
    assert "content-page" in js


def test_library_html_bumped_library_js_v10():
    html = open("frontend/library.html", encoding="utf-8").read()
    assert "library.js?v=10" in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_content_frontend.py -v`
Expected: FAIL — `contentImages` not in library.js; version still `v=9`.

- [ ] **Step 3: Update `renderContent` in `frontend/library.js`**

Replace the existing `renderContent` function with:

```javascript
function renderContent(d) {
  if (d.contentImages && d.contentImages.length) {
    return `<div class="content-pages">${d.contentImages
      .map(
        (u) => `<img class="content-page" src="${esc(u)}" alt="Nội dung" loading="lazy" />`
      )
      .join("")}</div>`;
  }
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
```

- [ ] **Step 4: Append styles to `frontend/styles.css`**

```css
/* ===== Nội dung book part-images ===== */
.content-pages { display: flex; flex-direction: column; gap: 12px; }
.content-page { max-width: 100%; height: auto; border: 1px solid #e3e3e6; border-radius: 8px; background: #fff; }
```

- [ ] **Step 5: Bump the library.js cache version**

In `frontend/library.html`, change `library.js?v=9` to `library.js?v=10`.

- [ ] **Step 6: Run the test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest backend/tests/test_content_frontend.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add frontend/library.js frontend/styles.css frontend/library.html backend/tests/test_content_frontend.py
git commit -m "feat: render book part-images in Nội dung with text fallback"
```

---

### Task 5: Generator script + crawl/crop/map run

**Files:**
- Create: `backend/scripts/build_content_images.py`

**Interfaces:**
- Consumes: `content_parsing` (`parse_object_name`, `touch_vector_bbox`, `crop_filename`), `curriculum_service` (`_run_select`, `local_name`), `CONTENT_FIGURE_DIR`, `CONTENT_PAGES_JSON`
- Produces: crops in `asset/content_figure/`; mapping `backend/data/content_pages.json`.

- [ ] **Step 1: Create the generator script**

Create `backend/scripts/build_content_images.py`:

```python
"""Crawl hoc10.vn book pages, crop each page 'object' (part) region from the page
scan, map parts to GraphDB lessons, and write asset/content_figure/*.jpg plus
backend/data/content_pages.json = {lesson_id: [filenames in order]}.

Run from project root:
    .venv/Scripts/python.exe backend/scripts/build_content_images.py report
    .venv/Scripts/python.exe backend/scripts/build_content_images.py all
Needs outbound access to hoc10.vn and GraphDB up (for lesson mapping).
"""
import io
import os
import re
import sys
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.abspath("."))

import requests
from PIL import Image

from backend.app.services import curriculum_service as cs
from backend.app.services.content_parsing import (
    parse_object_name, touch_vector_bbox, crop_filename,
)
from backend.app.config import CONTENT_FIGURE_DIR, CONTENT_PAGES_JSON

BOOKS = {10: (164, "tin-hoc-10"), 11: (386, "tin-hoc-11-tin-hoc-ung-dung"),
         12: (737, "tin-hoc-12-tin-hoc-ung-dung")}
API = "https://api.hoc10.vn/api/get-detail-page"
IMG_BASE = "https://hoc10.monkeyuni.net/"
HEADERS = {"User-Agent": "Mozilla/5.0 Chrome/120", "Referer": "https://www.hoc10.vn/"}

# Manual (grade, topic_code, lesson_num) -> lesson_id overrides for codes the
# automatic matcher cannot resolve (filled after inspecting the report).
OVERRIDES: dict = {}


def fetch_pages(book_id: int, slug: str) -> list[dict]:
    r = requests.get(API, params={"book_id": book_id, "page": 0, "book_name": slug,
                                  "limit": 0, "status": "", "app_id": 68},
                     headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.json()["data"]["list_page"]


def lesson_index(grade: int) -> dict:
    """Build {(topic_letter, track, lesson_num): lesson_id} for a grade from GraphDB.
    track is 'cs', 'ict', or '' (core)."""
    rows = cs._run_select(f"""
        SELECT ?lesson ?tlabel ?num WHERE {{
          ?lesson a ex:Lesson ; ex:belongsToTopic ?t ; ex:belongsToGrade ?g .
          ?g ex:gradeNumber {grade} .
          ?t rdfs:label ?tlabel .
          OPTIONAL {{ ?lesson ex:lessonNumber ?num }}
        }}
    """)
    idx = {}
    for r in rows:
        label = r.get("tlabel", "")
        m = re.search(r"Chủ đề\s+([A-Za-z]+)", label)
        letter = (m.group(1).upper() if m else "")
        low = label.lower()
        track = "cs" if ("cs" in low or "khoa học máy tính" in low) else (
            "ict" if ("ict" in low or "ứng dụng" in low) else "")
        num = r.get("num")
        if num is None:
            continue
        idx.setdefault((letter, track, int(num)), cs.local_name(r["lesson"]))
    return idx


def topic_letter_track(topic_code: str, grade: int) -> tuple[str, str]:
    """Derive (letter, track) from a parsed object topic_code.
    g10/g11 codes look like 'CA'/'CACS'/'CEICT'; g12 codes are bare letters,
    and grade 12 is the applied (ICT) book."""
    code = topic_code.upper()
    if code.startswith("C") and len(code) > 1:
        code = code[1:]           # strip leading C for g10/g11
    letter = code[:1]
    track = "cs" if code.endswith("CS") else ("ict" if code.endswith("ICT") else "")
    if grade == 12 and track == "":
        track = "ict"
    return letter, track


def resolve_lesson(grade: int, topic_code: str, lesson_num: int, idx: dict) -> str | None:
    if (grade, topic_code, lesson_num) in OVERRIDES:
        return OVERRIDES[(grade, topic_code, lesson_num)]
    letter, track = topic_letter_track(topic_code, grade)
    return (idx.get((letter, track, lesson_num))
            or idx.get((letter, "", lesson_num)))  # fall back to core track


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "report"
    out_dir = os.path.abspath(CONTENT_FIGURE_DIR)
    if mode == "all":
        os.makedirs(out_dir, exist_ok=True)

    mapping: dict = {}          # lesson_id -> [(page, top, filename)]
    unmapped: dict = {}         # (grade, topic_code, lesson_num) -> count
    stats = {"pages": 0, "objects": 0, "crops": 0}

    for grade, (book_id, slug) in BOOKS.items():
        print(f"\n=== grade {grade} (book {book_id}) ===")
        idx = lesson_index(grade)
        pages = fetch_pages(book_id, slug)
        for p in pages:
            stats["pages"] += 1
            objs = p.get("objects") or []
            if not objs:
                continue
            img = None
            for o in objs:
                stats["objects"] += 1
                meta = parse_object_name(o.get("name", ""))
                if not meta:
                    continue
                lesson_id = resolve_lesson(meta["grade"], meta["topic_code"],
                                           meta["lesson_num"], idx)
                if not lesson_id:
                    key = (meta["grade"], meta["topic_code"], meta["lesson_num"])
                    unmapped[key] = unmapped.get(key, 0) + 1
                    continue
                if mode != "all":
                    stats["crops"] += 1
                    mapping.setdefault(lesson_id, []).append((meta["page_num"], 0, ""))
                    continue
                if img is None:
                    bg = p.get("background")
                    resp = requests.get(IMG_BASE + bg, headers=HEADERS, timeout=60)
                    resp.raise_for_status()
                    img = Image.open(io.BytesIO(resp.content)).convert("RGB")
                box = touch_vector_bbox(o["touch_vector"], img.width, img.height)
                if not box:
                    continue
                fn = crop_filename(o["name"])
                img.crop(box).save(os.path.join(out_dir, fn), "JPEG", quality=85)
                stats["crops"] += 1
                mapping.setdefault(lesson_id, []).append((meta["page_num"], box[1], fn))

    # order each lesson's crops by page then vertical position; keep filenames
    final = {}
    for lid, items in mapping.items():
        items.sort(key=lambda t: (t[0], t[1]))
        files = [t[2] for t in items if t[2]] if mode == "all" else []
        final[lid] = files

    print("\n=== stats ===", stats)
    print(f"lessons mapped: {len(mapping)}")
    print(f"unmapped groups: {len(unmapped)}")
    for k, v in sorted(unmapped.items()):
        print(f"  UNMAPPED {k}: {v} objects")

    if mode == "all":
        os.makedirs(os.path.dirname(os.path.abspath(CONTENT_PAGES_JSON)), exist_ok=True)
        with open(CONTENT_PAGES_JSON, "w", encoding="utf-8") as fh:
            json.dump(final, fh, ensure_ascii=False, indent=1)
        print(f"wrote {CONTENT_PAGES_JSON}: {len(final)} lessons, {stats['crops']} crops")
    else:
        print("\n(report only; run with 'all' to download+crop and write the mapping)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the generator in report mode (controller-run; needs GraphDB up + network)**

Run: `.venv/Scripts/python.exe backend/scripts/build_content_images.py report`
Expected: prints per-grade progress, stats (pages/objects/crops), lessons mapped, and any `UNMAPPED (grade, topic_code, lesson_num)` groups. **Inspect the UNMAPPED list.** For each genuinely-unmappable code, add an entry to the `OVERRIDES` dict in the script mapping `(grade, topic_code, lesson_num) -> "<lesson_local_name>"` (find the correct lesson_id via a GraphDB query on the topic + lesson number), then re-run report until UNMAPPED is empty or only expected extras (e.g. "tìm hiểu thêm" lessons without a lessonNumber) remain.

- [ ] **Step 3: Run the generator for real (controller-run)**

Run: `.venv/Scripts/python.exe backend/scripts/build_content_images.py all`
Expected: downloads page scans, writes crops to `asset/content_figure/`, and writes `backend/data/content_pages.json`. Prints `wrote backend/data/content_pages.json: <N> lessons, <M> crops`.

- [ ] **Step 4: Verify end-to-end (controller-run)**

Confirm a known lesson now has content images via the real code path:

Run:
```
.venv/Scripts/python.exe -c "import io,sys; sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8'); from backend.app.services import curriculum_service as cs; d=cs.lesson_detail('lesson1'); print('contentImages:', len(d['contentImages'])); print(d['contentImages'][:3])"
```
Expected: a non-empty `contentImages` list for `lesson1` with `/content_figure/...jpg` URLs. Then start the app and open Grade 10 → Chủ đề A → Bài 1 → Nội dung and confirm the real book part-images render in order (and a lesson with no crops still shows text).

- [ ] **Step 5: Commit the generator script (crops + JSON are gitignored)**

```bash
git add backend/scripts/build_content_images.py
git commit -m "feat: build_content_images generator (crawl + crop + map)"
```

---

## Self-Review Notes

- **Spec coverage:** generator crawl/crop/map (Task 5) using per-grade name parsing + touch_vector bbox + filename normalization (Task 1); runtime service (Task 2); `lesson_detail.contentImages` + `/content_figure` mount + gitignore (Task 3); frontend render-with-text-fallback + version bump (Task 4). Copyright/gitignore handled in Global Constraints + Task 3. Report-mode reconciliation of unmapped topic codes is Task 5 Step 2.
- **No placeholders:** every code step has complete code; run steps have exact commands + expected results. `OVERRIDES` starts empty by design and is filled from the report — that is a runtime reconciliation step, not a plan placeholder.
- **Type consistency:** `parse_object_name` dict keys (`grade, topic_code, lesson_num, page_num, part`) are produced in Task 1 and consumed in Task 5; `content_images_for(lesson_id, map_path, img_dir) -> list[str]` from Task 2 is called in Task 3; `contentImages` key from Task 3 is read in Task 4; `crop_filename`/`content_pages.json` filename values are the same strings the generator writes and the service resolves.
- **Deployment:** crops + JSON are generated artifacts (gitignored); runtime adds no dependency; code deploys via `git pull`; generation is a one-time controller/ops step.
