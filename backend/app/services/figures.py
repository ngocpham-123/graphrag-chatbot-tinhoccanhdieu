import os
import logging

from backend.app.config import FIGURES_DIR

logger = logging.getLogger(__name__)

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")


def _load_stem_index() -> dict:
    """Map image basename-without-extension -> actual filename, from FIGURES_DIR."""
    index = {}
    abs_dir = os.path.abspath(FIGURES_DIR)
    if not os.path.isdir(abs_dir):
        logger.warning("Figures directory not found: %s", abs_dir)
        return index
    for fn in os.listdir(abs_dir):
        stem, ext = os.path.splitext(fn)
        if ext.lower() in _IMAGE_EXTS:
            index[stem] = fn
    return index


# Built once at import. The build script / app restart picks up new images.
_STEM_INDEX = _load_stem_index()


def local_name(value: str) -> str:
    """Local name of a URI (after last # or /), or the value itself if plain."""
    if not value:
        return ""
    if "#" in value:
        value = value.rsplit("#", 1)[-1]
    if "/" in value:
        value = value.rsplit("/", 1)[-1]
    return value


def figure_url_for_value(value) -> str | None:
    """Return /figures/<file> if value's local name matches an asset image."""
    if not isinstance(value, str) or not value:
        return None
    stem = local_name(value)
    # The value may itself be a filename with extension.
    stem = os.path.splitext(stem)[0]
    fn = _STEM_INDEX.get(stem)
    return f"/figures/{fn}" if fn else None


def figure_urls_from_rows(rows) -> list[str]:
    """Collect unique figure image URLs from rdflib result rows, in order."""
    urls = []
    seen = set()
    for row in rows:
        for term in row:
            url = figure_url_for_value(str(term) if term is not None else "")
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls
