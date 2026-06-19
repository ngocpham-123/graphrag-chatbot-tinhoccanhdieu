import os
import logging

from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma

from backend.app.config import OPENAI_API_KEY

logger = logging.getLogger(__name__)

# Persisted Chroma index lives under backend/data/chroma. The build script
# (backend/scripts/build_index.py) is the only writer; the app only reads.
CHROMA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "chroma")
)
COLLECTION = "tinhoc_text"
EMBEDDING_MODEL = "text-embedding-3-large"


def get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model=EMBEDDING_MODEL, api_key=OPENAI_API_KEY)


def load_vector_store() -> Chroma:
    """Open the persisted Chroma collection for read-only similarity search."""
    if not os.path.isdir(CHROMA_DIR) or not os.listdir(CHROMA_DIR):
        raise RuntimeError(
            "Chroma index not found at %s. Build it first:\n"
            "  PYTHONPATH=. .venv/Scripts/python.exe backend/scripts/build_index.py"
            % CHROMA_DIR
        )
    return Chroma(
        collection_name=COLLECTION,
        persist_directory=CHROMA_DIR,
        embedding_function=get_embeddings(),
    )


def vector_retrieve(store: Chroma, query: str, k: int = 6) -> str:
    """Return top-k semantically similar passages as readable, cited lines.

    Returns "" when nothing is retrieved so the answer step's not-found branch
    fires only when every source is empty.
    """
    docs = store.similarity_search(query, k=k)
    if not docs:
        return ""
    lines = []
    for d in docs:
        cite = d.metadata.get("lessonLabel") or d.metadata.get("source_property") or ""
        prefix = f"({cite}) " if cite else ""
        lines.append(f"- {prefix}{d.page_content}")
    return "\n".join(lines)
