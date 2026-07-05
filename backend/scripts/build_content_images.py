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
