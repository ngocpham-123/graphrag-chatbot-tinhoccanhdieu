"""Pure helpers for the hoc10 book part-image generator: object-name parsing,
touch_vector bounding boxes, and crop filenames. No network, no I/O."""
import json
import re
import unicodedata

_G10 = re.compile(r"^Tin10\.([A-Za-z]+)\.L(\d+)\.P(\d+)\.(.+)$")
_G11 = re.compile(r"^SGK\.TIN11THUD\.([A-Za-z]+)\.L(\d+)\.P(\d+)\.(.+)$")
_G12 = re.compile(r"^Tin12\.THUD\.P(\d+)\.([A-Za-z]+)(\d+)\.(.+)$")

# Vietnamese characters that don't decompose with standard NFD/NFKD
_VIETNAMESE_MAP = {
    'Đ': 'D', 'đ': 'd',
}


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
    # Map Vietnamese characters that don't decompose properly
    name = "".join(_VIETNAMESE_MAP.get(c, c) for c in name)
    # Decompose with NFD and remove combining marks, then encode to ASCII
    decomposed = unicodedata.normalize("NFD", name)
    ascii_name = "".join(
        c for c in decomposed
        if unicodedata.category(c) != "Mn"  # Remove Mark, Nonspacing
    )
    ascii_name = ascii_name.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", ascii_name).strip("_")
    return f"{slug}.jpg"
