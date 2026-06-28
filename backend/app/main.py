import logging
import os
import re

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.app.routers import chat, curriculum
from backend.app.config import FIGURES_DIR

logger = logging.getLogger(__name__)

app = FastAPI(title="GraphRAG Chatbot - Tin Hoc Canh Dieu")

app.include_router(chat.router)
app.include_router(curriculum.router)

# Serve figure images (URI local names of ex:Figure/ex:Diagram instances
# match these filenames without extension)
figures_abs = os.path.abspath(FIGURES_DIR)

IMAGE_FILE_RE = re.compile(r"\.(?:png|jpe?g|gif|svg|webp)$", re.IGNORECASE)


@app.get("/figures/manifest")
async def figures_manifest():
    """List image filenames available in FIGURES_DIR."""
    if not os.path.isdir(figures_abs):
        return {"figures": []}
    return {
        "figures": sorted(
            f for f in os.listdir(figures_abs) if IMAGE_FILE_RE.search(f)
        )
    }


if os.path.isdir(figures_abs):
    app.mount("/figures", StaticFiles(directory=figures_abs), name="figures")
    logger.info("Serving figures from %s at /figures", figures_abs)
else:
    logger.warning("Figures directory not found: %s", figures_abs)

# Serve frontend static files
app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/")
async def serve_frontend():
    return FileResponse("frontend/index.html")


@app.get("/library")
async def serve_library():
    return FileResponse("frontend/library.html")
