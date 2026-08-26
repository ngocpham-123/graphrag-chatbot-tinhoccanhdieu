import os
import re
import uuid
import logging
import unicodedata

import rdflib
from fastapi import APIRouter, HTTPException
from SPARQLWrapper import SPARQLWrapper, JSON, TURTLE, CONSTRUCT, DESCRIBE

from backend.app.models.schemas import ChatRequest, ChatResponse
from backend.app.services.graphdb_service import create_graph
from backend.app.services.chatgpt_service import create_qa_chain
from backend.app.services.vector_index import load_vector_store
from backend.app.services.orchestrator import answer_question
from backend.app.services import langfuse_service as lf
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


# Sync (not async) on purpose: this handler runs blocking I/O — OpenAI calls,
# SPARQL queries, Langfuse — and a sync route runs in FastAPI's threadpool.
# As `async def` one wedged outbound call froze the event loop and the whole
# server stopped answering (nginx 504 on every route) until a restart.
@router.post("/", response_model=ChatResponse)
def chat(request: ChatRequest):
    if qa_chain is None or vector_store is None:
        raise HTTPException(status_code=503, detail="Services not initialized")

    conversation_id = request.conversation_id or str(uuid.uuid4())

    # One Langfuse trace per request: the user's message is the trace input, the
    # final reply its output, and the orchestrator's steps are nested spans.
    # conversation_id doubles as the Langfuse session id, so a multi-turn chat
    # groups into one session in the UI.
    with lf.trace(
        "chat-request",
        input=request.message,
        session_id=conversation_id,
        tags=["chat"],
        metadata={"has_image": bool(request.image)},
    ) as root:
        return _handle_chat(request, conversation_id, root)


def _handle_chat(request: ChatRequest, conversation_id: str, root) -> ChatResponse:
    try:
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
        # logger (not print): print() raises UnicodeEncodeError and 500s the
        # request when the console codepage can't encode Vietnamese text.
        logger.info("sources=%s sparql=%s", result["sources"], sparql_query)

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

        root.update(
            output=reply,
            metadata={
                "sources": result["sources"],
                "sparql_query": sparql_query,
                "figure_paths": figure_paths,
                "exercise_count": len(exercises or []),
            },
        )
        lf.set_trace_io(output=reply)

        return ChatResponse(
            reply=reply,
            conversation_id=conversation_id,
            sparql_query=sparql_query,
            figure_paths=figure_paths if figure_paths else None,
            exercises=exercises,
        )
    except Exception as e:
        logger.exception("Chat endpoint error")
        root.update(level="ERROR", status_message=str(e))
        lf.set_trace_io(output={"error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))


# Columns a CONSTRUCT/DESCRIBE result is flattened onto. The frontend's triple
# renderer keys off exactly these names, so keep them in sync with app.js.
TRIPLE_COLUMNS = ["subject", "predicate", "object"]

# Ceiling on how many URIs get enriched in one lookup, so a sprawling CONSTRUCT
# cannot build a monster VALUES clause.
MAX_ENRICHED_URIS = 1000

# Rejects anything that would break out of a <...> term in a VALUES clause.
_SAFE_URI_RE = re.compile(r'^[^\s<>"{}|\\^`]+$')

# A node's rdf:type drives its colour in the frontend and its rdfs:label the
# caption, but an arbitrary CONSTRUCT carries neither, so both are fetched
# separately. The NOT EXISTS keeps only the *most specific* type: a
# DefinitionText is also a TextResource and a LearningResource, and colouring by
# a superclass would paint every resource in the book the same shade.
# Predicates are looked up by the same query -- that is how "belongsToGrade"
# renders as "belongs to grade" while unlabelled ones keep their local name.
_ENRICH_QUERY = """\
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?s ?t ?l ?lang WHERE {
  VALUES ?s { %s }
  OPTIONAL {
    ?s rdf:type ?t .
    FILTER(!isBlank(?t))
    FILTER NOT EXISTS {
      ?s rdf:type ?t2 .
      ?t2 rdfs:subClassOf+ ?t .
      FILTER(?t2 != ?t)
    }
  }
  OPTIONAL {
    ?s rdfs:label ?l .
    BIND(LANG(?l) AS ?lang)
  }
}
ORDER BY ?s ?t ?lang ?l"""

# Instance labels in this repository are tagged @vi while the ontology's
# property labels are tagged @en, so filtering the lookup down to Vietnamese
# would silently drop every edge caption. Prefer untagged, then Vietnamese,
# then fall back to whatever language exists.
_LABEL_LANG_PREFERENCE = ("", "vi")


def _sparql_client(query: str) -> SPARQLWrapper:
    endpoint = f"{GRAPHDB_URL}/repositories/{GRAPHDB_REPOSITORY}"
    client = SPARQLWrapper(endpoint)
    client.setTimeout(30)
    # Same NFC fix as graphdb_service applies to the generated queries: labels
    # are stored composed, hand-typed Vietnamese often arrives decomposed, and
    # SPARQL compares codepoints, so an NFD term would silently match nothing.
    client.setQuery(unicodedata.normalize("NFC", query))
    return client


def _pick_label(candidates: list[tuple[str, str]]) -> str:
    """Choose one label from (language, text) pairs, honouring the preference."""
    for preferred in _LABEL_LANG_PREFERENCE:
        for lang, text in candidates:
            if lang == preferred:
                return text
    return candidates[0][1] if candidates else ""


def _term_kind(term) -> str:
    if isinstance(term, rdflib.URIRef):
        return "uri"
    if isinstance(term, rdflib.BNode):
        return "bnode"
    return "literal"


def _select_result(client: SPARQLWrapper) -> dict:
    client.setReturnFormat(JSON)
    results = client.query().convert()

    # head.vars is the authoritative column list in SELECT order; the first
    # binding's keys miss OPTIONAL variables that happen to be unbound there.
    columns = list(results["head"]["vars"])

    rows, term_types = [], []
    for binding in results["results"]["bindings"]:
        rows.append([binding.get(col, {}).get("value", "") for col in columns])
        term_types.append([binding.get(col, {}).get("type", "") for col in columns])

    return {"columns": columns, "rows": rows, "term_types": term_types}


def _construct_result(client: SPARQLWrapper) -> dict:
    """Flatten a CONSTRUCT/DESCRIBE result graph into subject/predicate/object rows.

    Asking for JSON here (as this endpoint used to, unconditionally) makes
    GraphDB answer a CONSTRUCT with N-Triples instead, and the SELECT-shaped
    results["head"]["vars"] lookup then died on bytes -- every CONSTRUCT came
    back as HTTP 400 and the graph never rendered. SPARQLWrapper hands RDF
    payloads back unparsed, so rdflib does the parsing.
    """
    client.setReturnFormat(TURTLE)
    raw = client.query().convert()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")

    graph = rdflib.Graph()
    # Turtle is a superset of N-Triples, so this parses either serialisation.
    graph.parse(data=raw, format="turtle")

    # Sorted because rdflib's store iteration order is not stable, and an
    # identical query should produce an identical response.
    triples = sorted(graph, key=lambda t: (str(t[0]), str(t[1]), str(t[2])))

    return {
        "columns": list(TRIPLE_COLUMNS),
        "rows": [[str(s), str(p), str(o)] for s, p, o in triples],
        "term_types": [
            [_term_kind(s), _term_kind(p), _term_kind(o)] for s, p, o in triples
        ],
    }


def _uri_metadata(payload: dict) -> dict:
    """Look up the rdf:type and rdfs:label of every URI mentioned in a result.

    GraphDB Workbench can colour and caption nodes because it browses the whole
    repository; a CONSTRUCT result on its own has neither type nor (necessarily)
    label for the resources it mentions. This restores that context in one extra
    query. A failure here only costs styling, so it degrades to {} rather than
    failing the request.
    """
    uris = {
        value
        for row, kinds in zip(payload["rows"], payload["term_types"])
        for value, kind in zip(row, kinds)
        if kind == "uri" and value
    }
    safe = sorted(u for u in uris if _SAFE_URI_RE.match(u))
    if len(safe) > MAX_ENRICHED_URIS:
        logger.info("Enriching only %d of %d URIs", MAX_ENRICHED_URIS, len(safe))
        safe = safe[:MAX_ENRICHED_URIS]
    if not safe:
        return {}

    values = " ".join(f"<{u}>" for u in safe)
    try:
        result = _select_result(_sparql_client(_ENRICH_QUERY % values))
    except Exception:
        logger.exception("URI metadata lookup failed; rendering without types/labels")
        return {}

    types: dict[str, str] = {}
    labels: dict[str, list[tuple[str, str]]] = {}
    for subject, type_uri, label, lang in result["rows"]:
        # Rows are ORDER BY'd, so "first wins" is deterministic when a resource
        # still has several equally-specific types (e.g. a property that is both
        # an rdf:Property and an owl:ObjectProperty).
        if type_uri and subject not in types:
            types[subject] = type_uri
        if label:
            candidates = labels.setdefault(subject, [])
            if (lang, label) not in candidates:
                candidates.append((lang, label))

    meta: dict[str, dict[str, str]] = {}
    for subject in set(types) | set(labels):
        entry = {}
        if subject in types:
            entry["type"] = types[subject]
        chosen = _pick_label(labels.get(subject, []))
        if chosen:
            entry["label"] = chosen
        meta[subject] = entry
    return meta


@router.post("/sparql")
def execute_sparql(request: dict):
    """Execute a raw SPARQL query and return results.

    A SELECT keeps its own columns and rows; a CONSTRUCT/DESCRIBE is flattened
    onto subject/predicate/object rows. Either way the response carries
    `node_meta` -- the rdf:type and rdfs:label of every URI mentioned -- which
    is what lets the frontend draw class-coloured, label-captioned nodes the way
    GraphDB Workbench does, and `term_types`, marking each cell uri/literal/
    bnode so the renderer can tell a resource from the text of a definition.
    """
    sparql_query = request.get("query", "").strip()
    if not sparql_query:
        raise HTTPException(status_code=400, detail="Empty query")

    try:
        client = _sparql_client(sparql_query)
        query_form = client.queryType

        if query_form in (CONSTRUCT, DESCRIBE):
            payload = _construct_result(client)
        else:
            payload = _select_result(client)

        # Enriched for every query form, not just CONSTRUCT: a SELECT that
        # projects resource URIs (?lesson rather than only ?lessonLabel) then
        # gets the same class colours and captions. A SELECT that projects only
        # literals has no URI to look up, so this costs it nothing.
        payload["node_meta"] = _uri_metadata(payload)
        payload["query_form"] = query_form
        return payload
    except Exception as e:
        # logger, not print: print() raises UnicodeEncodeError on a console
        # codepage that cannot encode the Vietnamese text in a SPARQL error.
        logger.exception("SPARQL execution failed")
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str):
    conversations.pop(conversation_id, None)
    return {"status": "deleted"}
