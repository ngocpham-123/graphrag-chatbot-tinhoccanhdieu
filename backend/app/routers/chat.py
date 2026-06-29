import os
import re
import uuid
import logging

from fastapi import APIRouter, HTTPException
from SPARQLWrapper import SPARQLWrapper, JSON

from backend.app.models.schemas import ChatRequest, ChatResponse
from backend.app.services.graphdb_service import create_graph
from backend.app.services.chatgpt_service import create_qa_chain
from backend.app.services.vector_index import load_vector_store
from backend.app.services.orchestrator import answer_question
from backend.app.config import FIGURES_DIR, GRAPHDB_URL, GRAPHDB_REPOSITORY

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

# In-memory conversation store
conversations: dict[str, list[dict]] = {}

# Initialized on startup
graph = None
qa_chain = None
vector_store = None

# Regex to find image file paths in the reply text
IMAGE_PATH_RE = re.compile(
    r'[A-Za-z]:[\\/][^\s"\'<>|*?]+\.(?:png|jpe?g|gif|svg|webp)'
    r'|'
    r'[\w./\\-]+\.(?:png|jpe?g|gif|svg|webp)',
    re.IGNORECASE,
)


def resolve_figure_url(raw_path: str) -> str | None:
    """
    Convert a raw file path from the GraphDB/LLM reply into a serveable
    /figures/<filename> URL. Returns None if the file does not exist.
    """
    # Normalise slashes
    normalised = raw_path.replace("\\", "/")
    filename = os.path.basename(normalised)

    # 1. Check relative to FIGURES_DIR (using absolute path)
    figures_abs = os.path.abspath(FIGURES_DIR)
    local_path = os.path.join(figures_abs, filename)
    if os.path.isfile(local_path):
        return f"/figures/{filename}"

    # 2. Check the raw path as-is (the reply may contain a full absolute path)
    if os.path.isfile(normalised):
        return f"/figures/{filename}"

    logger.warning("Figure file not found: %s (tried %s and %s)", filename, local_path, normalised)
    return None


def extract_figure_paths_from_reply(reply: str) -> list[str]:
    """Scan the LLM reply text for image paths and resolve them to URLs."""
    matches = IMAGE_PATH_RE.findall(reply)
    urls = []
    seen = set()
    for match in matches:
        url = resolve_figure_url(match)
        if url and url not in seen:
            urls.append(url)
            seen.add(url)
    return urls


@router.on_event("startup")
async def startup():
    global graph, qa_chain, vector_store
    try:
        graph = create_graph()
        qa_chain = create_qa_chain(graph)
        vector_store = load_vector_store()
        logger.info("GraphDB QA chain + vector store initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize QA chain / vector store: %s", e)
        raise


@router.get("/schema")
async def get_schema():
    """Return the ontology schema (for debugging)."""
    if graph is None:
        raise HTTPException(status_code=503, detail="Graph not initialized")
    return {"schema": graph.get_schema}


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest):
    if qa_chain is None or vector_store is None:
        raise HTTPException(status_code=503, detail="Services not initialized")

    try:
        conversation_id = request.conversation_id or str(uuid.uuid4())
        history = conversations.get(conversation_id, [])

        # History is used only to resolve follow-ups; the orchestrator condenses
        # it into a standalone question before any retrieval.
        history_text = ""
        for msg in history[-6:]:
            history_text += f"{msg['role'].capitalize()}: {msg['content']}\n"

        result = answer_question(
            request.message, qa_chain, vector_store, history_text, image=request.image
        )
        reply = result["reply"] or "Xin lỗi, tôi chưa tạo được câu trả lời."
        sparql_query = result["sparql_query"]
        exercises = result.get("exercises") or None
        print(f"[DEBUG] sources={result['sources']} sparql={sparql_query}")

        # Figures: those returned by the SPARQL results (reliable) first, then
        # any paths mentioned in the reply text, de-duplicated, order-preserving.
        figure_paths = list(result.get("figure_paths") or [])
        for p in extract_figure_paths_from_reply(reply):
            if p not in figure_paths:
                figure_paths.append(p)
        print(f"[DEBUG] figure_paths: {figure_paths}")

        # Update conversation history
        history.append({"role": "user", "content": request.message})
        history.append({
            "role": "assistant",
            "content": reply,
            "figure_paths": figure_paths,
        })
        conversations[conversation_id] = history

        return ChatResponse(
            reply=reply,
            conversation_id=conversation_id,
            sparql_query=sparql_query,
            figure_paths=figure_paths if figure_paths else None,
            exercises=exercises,
        )
    except Exception as e:
        logger.exception("Chat endpoint error")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sparql")
async def execute_sparql(request: dict):
    """Execute a raw SPARQL query and return results."""
    sparql_query = request.get("query", "").strip()
    if not sparql_query:
        raise HTTPException(status_code=400, detail="Empty query")

    try:
        endpoint = f"{GRAPHDB_URL}/repositories/{GRAPHDB_REPOSITORY}"
        sparql = SPARQLWrapper(endpoint)
        sparql.setReturnFormat(JSON)
        sparql.setQuery(sparql_query)

        results = sparql.query().convert()

        columns = results["results"]["bindings"][0].keys() if results["results"]["bindings"] else []
        columns = list(columns)

        rows = []
        for binding in results["results"]["bindings"]:
            row = [binding.get(col, {}).get("value", "") for col in columns]
            rows.append(row)

        return {"columns": columns, "rows": rows}
    except Exception as e:
        print(f"[DEBUG] SPARQL error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str):
    conversations.pop(conversation_id, None)
    return {"status": "deleted"}
