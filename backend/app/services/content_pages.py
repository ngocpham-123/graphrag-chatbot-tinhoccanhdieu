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
    files = mapping.get(lesson_id) if isinstance(mapping, dict) else None
    if not isinstance(files, list):
        return []
    abs_dir = os.path.abspath(img_dir)
    return [
        f"/content_figure/{f}"
        for f in files
        if isinstance(f, str) and os.path.isfile(os.path.join(abs_dir, f))
    ]
