# Hybrid Text Retrieval (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add semantic (vector) retrieval over the graph's text literals, run alongside the existing Text-to-SPARQL retriever, and merge both into one grounded Vietnamese answer — improving conceptual/paraphrased questions without breaking structured ones.

**Architecture:** A one-time build script dumps every text literal (`hasRawText`, `hasDefinitionText`, `hasCaption`, `rdfs:label`) from GraphDB into a local Chroma index embedded with OpenAI `text-embedding-3-large`. At query time an orchestrator runs SPARQL retrieval (reusing the existing `FormattedGraphDBQAChain`) and Chroma vector retrieval concurrently, merges both result sets into a labeled context, and a Vietnamese answer LLM synthesizes the final answer. Image input is Phase 2 (out of scope here).

**Tech Stack:** FastAPI, LangChain (`OntotextGraphDBQAChain`, `langchain-chroma`), Chroma (`chromadb`), OpenAI (`text-embedding-3-large`, `gpt-4.1-mini`), SPARQLWrapper.

**Spec:** `docs/superpowers/specs/2026-06-14-multimodal-hybrid-rag-design.md`

**Repo realities (read first):**
- This project is **not a git repository** — skip all commit steps.
- There is **no test harness** (no pytest). Verification is via small runnable scripts and the running app.
- Windows + PowerShell. Run Python as `.venv/Scripts/python.exe` from the project root with `PYTHONPATH=.`. Prefix `PYTHONUTF8=1` so Vietnamese prints correctly. Bash examples below also work in the Git Bash tool.
- GraphDB must be running at `http://localhost:7200`, repository `Tin-hoc-canh-dieu`. `.env` must hold a working `OPENAI_API_KEY`.

---

## File Structure

- **Create** `backend/app/services/vector_index.py` — Chroma config, embeddings factory, `load_vector_store()`, `vector_retrieve()`. Read-only at app runtime.
- **Create** `backend/scripts/build_index.py` — one-time builder: SPARQL-dump literals → Documents → Chroma (the only writer of the index).
- **Create** `backend/app/services/orchestrator.py` — runs SPARQL + vector retrieval, merges, calls the answer LLM. Single entry point `answer_question()`.
- **Modify** `backend/app/services/chatgpt_service.py` — add `retrieve_context()` to `FormattedGraphDBQAChain` (SPARQL retrieval that returns the formatted rows instead of a final answer) and the `HYBRID_ANSWER_PROMPT`.
- **Modify** `backend/app/routers/chat.py` — startup loads the vector store; the endpoint delegates to the orchestrator.
- **Modify** `backend/requirements.txt` — add `langchain-chroma`, `chromadb`.
- **Create** `backend/eval/eval_hybrid.py` — compare SPARQL-only vs hybrid on conceptual questions.

---

## Task 1: Add dependencies

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Append the two packages**

Add these lines to `backend/requirements.txt`:

```
langchain-chroma>=0.2.0
chromadb>=0.5.0
```

- [ ] **Step 2: Install into the venv**

Run:
```bash
.venv/Scripts/python.exe -m pip install "langchain-chroma>=0.2.0" "chromadb>=0.5.0"
```
Expected: installs successfully, ending with a line like `Successfully installed chromadb-… langchain-chroma-…`.

- [ ] **Step 3: Verify imports resolve**

Run:
```bash
.venv/Scripts/python.exe -c "import chromadb, langchain_chroma; from langchain_openai import OpenAIEmbeddings; print('deps OK')"
```
Expected: `deps OK`

---

## Task 2: Vector index module (config + load + retrieve)

**Files:**
- Create: `backend/app/services/vector_index.py`

- [ ] **Step 1: Write the module**

Create `backend/app/services/vector_index.py`:

```python
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
```

- [ ] **Step 2: Verify it imports (index not built yet)**

Run:
```bash
PYTHONPATH=. .venv/Scripts/python.exe -c "from backend.app.services.vector_index import CHROMA_DIR, load_vector_store; print('module OK', CHROMA_DIR)"
```
Expected: `module OK <abs path>/backend/data/chroma`

---

## Task 3: Build the index

**Files:**
- Create: `backend/scripts/build_index.py`

- [ ] **Step 1: Write the build script**

Create `backend/scripts/build_index.py`:

```python
"""Build the Chroma vector index from GraphDB text literals.

Run from the project root:
    PYTHONPATH=. .venv/Scripts/python.exe backend/scripts/build_index.py
Rebuilds from scratch each run (deletes the existing index directory first).
"""
import os
import io
import sys
import shutil
import logging

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
logging.basicConfig(level=logging.INFO)

from SPARQLWrapper import SPARQLWrapper, JSON
from langchain_core.documents import Document
from langchain_chroma import Chroma

from backend.app.config import GRAPHDB_URL, GRAPHDB_REPOSITORY
from backend.app.services.vector_index import (
    CHROMA_DIR,
    COLLECTION,
    get_embeddings,
)

ENDPOINT = f"{GRAPHDB_URL}/repositories/{GRAPHDB_REPOSITORY}"

# Pull every text literal we want searchable, with a lesson label for citation.
# Exclude rdfs:label on ontology (TBox) nodes — those are English class/property
# names, not content.
EXTRACT_QUERY = """
PREFIX ex:   <http://example.org/tinhoc10-cd#>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl:  <http://www.w3.org/2002/07/owl#>
SELECT ?node ?prop ?text ?lessonLabel WHERE {
  VALUES ?prop { ex:hasRawText ex:hasDefinitionText ex:hasCaption rdfs:label }
  ?node ?prop ?text .
  FILTER(isLiteral(?text))
  FILTER NOT EXISTS {
    ?node a ?t2 .
    FILTER(?t2 IN (owl:Class, owl:ObjectProperty, owl:DatatypeProperty, rdf:Property))
  }
  OPTIONAL { ?node ex:belongsToLesson ?lesson . ?lesson rdfs:label ?lessonLabel }
}
"""


def fetch_rows():
    sparql = SPARQLWrapper(ENDPOINT)
    sparql.setReturnFormat(JSON)
    sparql.setQuery(EXTRACT_QUERY)
    return sparql.query().convert()["results"]["bindings"]


def build_documents(rows):
    seen = set()
    docs = []
    for r in rows:
        node = r["node"]["value"]
        prop = r["prop"]["value"].rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        text = r["text"]["value"].strip()
        if not text:
            continue
        key = (node, prop, text)
        if key in seen:
            continue
        seen.add(key)
        meta = {"uri": node, "source_property": prop}
        if "lessonLabel" in r:
            meta["lessonLabel"] = r["lessonLabel"]["value"]
        docs.append(Document(page_content=text, metadata=meta))
    return docs


def main():
    print(f"Querying {ENDPOINT} ...")
    rows = fetch_rows()
    docs = build_documents(rows)
    print(f"Prepared {len(docs)} documents from {len(rows)} rows.")

    if os.path.isdir(CHROMA_DIR):
        shutil.rmtree(CHROMA_DIR)
    os.makedirs(CHROMA_DIR, exist_ok=True)

    print("Embedding + writing Chroma index (this calls the OpenAI API)...")
    Chroma.from_documents(
        documents=docs,
        embedding=get_embeddings(),
        collection_name=COLLECTION,
        persist_directory=CHROMA_DIR,
    )
    print(f"Done. Index at {CHROMA_DIR}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the builder**

Run:
```bash
PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe backend/scripts/build_index.py
```
Expected: prints `Prepared ~4000 documents from ... rows.` then `Done. Index at …\backend\data\chroma`. (Document count will be in the low thousands.)

- [ ] **Step 3: Verify retrieval returns sensible passages**

Run:
```bash
PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe -c "
import sys, io; sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from backend.app.services.vector_index import load_vector_store, vector_retrieve
s = load_vector_store()
print(vector_retrieve(s, 'máy tính giúp ích gì cho xã hội tri thức', k=4))
"
```
Expected: 3–4 `- (...) <Vietnamese passage>` lines whose content is topically about computers/knowledge society.

---

## Task 4: SPARQL retrieval-only method + hybrid answer prompt

**Files:**
- Modify: `backend/app/services/chatgpt_service.py`

- [ ] **Step 1: Add the imports for a no-op callback manager**

At the top of `backend/app/services/chatgpt_service.py`, below the existing imports, add:

```python
from langchain_core.callbacks import CallbackManagerForChainRun
```

- [ ] **Step 2: Add `retrieve_context` to `FormattedGraphDBQAChain`**

In `backend/app/services/chatgpt_service.py`, inside the `FormattedGraphDBQAChain` class (right after the existing `_execute_query` method), add:

```python
    def retrieve_context(self, question: str) -> tuple[str, str]:
        """Generate + execute SPARQL and return (formatted_rows, sparql_query).

        Reuses the chain's own SPARQL generation and fix-retry logic, but stops
        before answer generation so the orchestrator can merge these rows with
        vector passages. Returns ("", sparql) when the query yields no rows.
        """
        run_manager = CallbackManagerForChainRun.get_noop_manager()
        callbacks = run_manager.get_child()
        schema = self.graph.get_schema

        gen = self.sparql_generation_chain.invoke(
            {"prompt": question, "schema": schema}, callbacks=callbacks
        )
        sparql = gen[self.sparql_generation_chain.output_key]
        sparql = self._get_prepared_sparql_query(
            run_manager, callbacks, sparql, schema
        )
        context = self._execute_query(sparql)  # our override returns a clean string
        return context, sparql
```

- [ ] **Step 3: Add the hybrid answer prompt**

In `backend/app/services/chatgpt_service.py`, after the existing `QA_PROMPT` definition, add:

```python
# Answer prompt for the hybrid orchestrator. Receives two labeled evidence
# blocks (structured SPARQL rows + semantic passages). Same honesty rules as
# QA_PROMPT: use evidence even if partial, never contradict, say "not found"
# only when BOTH blocks are empty.
HYBRID_ANSWER_PROMPT = PromptTemplate(
    input_variables=["sparql_context", "vector_context", "prompt"],
    template="""\
Bạn là trợ lí AI trả lời câu hỏi về sách giáo khoa "Tin học 10 - Cánh Diều".
Dưới đây là bằng chứng truy xuất từ knowledge graph của cuốn sách, gồm hai phần:
kết quả truy vấn cấu trúc (SPARQL) và các đoạn văn liên quan (tìm kiếm ngữ nghĩa).
Đây là nguồn đáng tin cậy: không nghi ngờ, không dùng kiến thức riêng để sửa lại.

Quy tắc trả lời (tiếng Việt, rõ ràng, tự nhiên):
- Nếu BẤT KỲ phần nào có dữ liệu, BẮT BUỘC dùng nó để trả lời; tổng hợp cả hai
  phần thành một câu trả lời mạch lạc. Nếu chỉ liên quan một phần, hãy trình bày
  như thông tin liên quan và nói rõ là chưa có mục đúng chính xác.
- TUYỆT ĐỐI KHÔNG nói "không tìm thấy" khi vẫn còn dữ liệu, và KHÔNG tự mâu thuẫn.
- CHỈ khi CẢ HAI phần đều TRỐNG thì mới nói rằng bạn không tìm thấy thông tin về
  câu hỏi này trong sách.
- Không bịa thêm thông tin nằm ngoài bằng chứng.

Kết quả truy vấn (SPARQL):
{sparql_context}

Đoạn văn liên quan (ngữ nghĩa):
{vector_context}

Câu hỏi: {prompt}
Trả lời:""",
)
```

- [ ] **Step 4: Verify the module still imports**

Run:
```bash
PYTHONPATH=. .venv/Scripts/python.exe -c "from backend.app.services.chatgpt_service import FormattedGraphDBQAChain, HYBRID_ANSWER_PROMPT; print('retrieve_context' in dir(FormattedGraphDBQAChain))"
```
Expected: `True`

---

## Task 5: Orchestrator

**Files:**
- Create: `backend/app/services/orchestrator.py`

- [ ] **Step 1: Write the orchestrator**

Create `backend/app/services/orchestrator.py`:

```python
import logging

from langchain_openai import ChatOpenAI
from langchain_chroma import Chroma

from backend.app.config import OPENAI_API_KEY
from backend.app.services.chatgpt_service import (
    FormattedGraphDBQAChain,
    HYBRID_ANSWER_PROMPT,
    condense_question,
)
from backend.app.services.vector_index import vector_retrieve

logger = logging.getLogger(__name__)

_answer_llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0, api_key=OPENAI_API_KEY)


def answer_question(
    question: str,
    qa_chain: FormattedGraphDBQAChain,
    vector_store: Chroma,
    history_text: str = "",
) -> dict:
    """Hybrid answer: SPARQL retrieval + vector retrieval, merged.

    Returns {"reply": str, "sparql_query": str | None, "sources": list[str]}.
    """
    standalone = condense_question(history_text, question)

    sparql_context, sparql = "", None
    try:
        sparql_context, sparql = qa_chain.retrieve_context(standalone)
    except Exception:
        logger.exception("SPARQL retrieval failed; continuing without it")

    vector_context = ""
    try:
        vector_context = vector_retrieve(vector_store, standalone, k=6)
    except Exception:
        logger.exception("Vector retrieval failed; continuing without it")

    sources = []
    if sparql_context:
        sources.append("sparql")
    if vector_context:
        sources.append("vector")

    msg = HYBRID_ANSWER_PROMPT.format(
        sparql_context=sparql_context or "(trống)",
        vector_context=vector_context or "(trống)",
        prompt=standalone,
    )
    reply = (_answer_llm.invoke(msg).content or "").strip()
    logger.info("Hybrid answer sources=%s standalone=%r", sources, standalone)

    return {"reply": reply, "sparql_query": sparql, "sources": sources}
```

- [ ] **Step 2: Verify end-to-end on a conceptual question**

Run:
```bash
PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe -c "
import sys, io; sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from backend.app.services.graphdb_service import create_graph
from backend.app.services.chatgpt_service import create_qa_chain
from backend.app.services.vector_index import load_vector_store
from backend.app.services.orchestrator import answer_question
g = create_graph(); qa = create_qa_chain(g); vs = load_vector_store()
r = answer_question('máy tính đem lại lợi ích gì cho xã hội?', qa, vs)
print('SOURCES:', r['sources'])
print('REPLY:', r['reply'])
"
```
Expected: `SOURCES:` includes at least `vector` (and often `sparql`); `REPLY:` is a non-empty Vietnamese answer grounded in retrieved passages (not "không tìm thấy").

---

## Task 6: Wire the orchestrator into the chat endpoint

**Files:**
- Modify: `backend/app/routers/chat.py`

- [ ] **Step 1: Add imports and a module-level vector store**

In `backend/app/routers/chat.py`, update the service imports and the init globals.

Replace:
```python
from backend.app.services.chatgpt_service import create_qa_chain, condense_question
```
with:
```python
from backend.app.services.chatgpt_service import create_qa_chain
from backend.app.services.vector_index import load_vector_store
from backend.app.services.orchestrator import answer_question
```

Replace:
```python
# Initialized on startup
graph = None
qa_chain = None
```
with:
```python
# Initialized on startup
graph = None
qa_chain = None
vector_store = None
```

- [ ] **Step 2: Load the vector store on startup**

In `backend/app/routers/chat.py`, replace the `startup` function body:

```python
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
```

- [ ] **Step 3: Delegate the chat endpoint to the orchestrator**

In `backend/app/routers/chat.py`, inside `async def chat(...)`, replace the block that builds `history_text` / `standalone_question` and calls `qa_chain.invoke` (the lines from the `# Conversation history is used ONLY ...` comment through `result = qa_chain.invoke({"query": standalone_question})` and the subsequent extraction of `reply` and `sparql_query`) with:

```python
        if qa_chain is None or vector_store is None:
            raise HTTPException(status_code=503, detail="Services not initialized")

        # History is used only to resolve follow-ups; the orchestrator condenses
        # it into a standalone question before any retrieval.
        history_text = ""
        for msg in history[-6:]:
            history_text += f"{msg['role'].capitalize()}: {msg['content']}\n"

        result = answer_question(request.message, qa_chain, vector_store, history_text)
        reply = result["reply"] or "Xin lỗi, tôi chưa tạo được câu trả lời."
        sparql_query = result["sparql_query"]
        print(f"[DEBUG] sources={result['sources']} sparql={sparql_query}")
```

Leave the rest of the function (figure extraction from `reply`, history append, `ChatResponse` return) unchanged.

- [ ] **Step 4: Start the app and verify a conceptual question over HTTP**

Start the server (background) from the project root:
```bash
PYTHONPATH=. .venv/Scripts/python.exe -m uvicorn backend.app.main:app --port 8000
```
Then in a second shell:
```bash
curl -s -X POST http://localhost:8000/api/chat/ -H "Content-Type: application/json" \
  --data '{"message":"máy tính đem lại lợi ích gì cho xã hội?"}'
```
Expected: JSON with a non-empty Vietnamese `reply` (not "không tìm thấy"). Stop the server afterward.

---

## Task 7: Hybrid vs SPARQL-only evaluation script

**Files:**
- Create: `backend/eval/eval_hybrid.py`

- [ ] **Step 1: Write the comparison script**

Create `backend/eval/eval_hybrid.py`:

```python
"""Compare SPARQL-only vs hybrid retrieval on conceptual questions.

Usage (from project root):
    PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe backend/eval/eval_hybrid.py
Optionally pass a JSON file: a list of {"question": "...", "expected": "..."}.
"""
import sys
import io
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from backend.app.services.graphdb_service import create_graph
from backend.app.services.chatgpt_service import create_qa_chain
from backend.app.services.vector_index import load_vector_store
from backend.app.services.orchestrator import answer_question

DEFAULT_QUESTIONS = [
    {"question": "máy tính đem lại lợi ích gì cho xã hội?"},
    {"question": "vì sao cần bảo vệ thông tin cá nhân?"},
    {"question": "trí tuệ nhân tạo được nhắc đến như thế nào trong sách?"},
    {"question": "thông tin là gì?"},
    {"question": "internet vạn vật hoạt động ra sao?"},
]

NOT_FOUND = "không tìm thấy"


def load_questions():
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_QUESTIONS


def main():
    graph = create_graph()
    qa = create_qa_chain(graph)
    vs = load_vector_store()
    questions = load_questions()

    sparql_only_found = 0
    hybrid_found = 0
    for item in questions:
        q = item["question"]
        # SPARQL-only baseline (existing chain answer)
        try:
            base = qa.invoke({"query": q}).get("result", "")
        except Exception as e:
            base = f"(error: {e})"
        # Hybrid
        hyb = answer_question(q, qa, vs)
        base_found = NOT_FOUND not in base.lower() and base.strip() != ""
        hyb_found = NOT_FOUND not in hyb["reply"].lower() and hyb["reply"].strip() != ""
        sparql_only_found += base_found
        hybrid_found += hyb_found
        print("\n" + "=" * 70)
        print("Q:", q)
        print(f"[SPARQL-only] answered={base_found}\n{base}")
        print(f"[Hybrid] answered={hyb_found} sources={hyb['sources']}\n{hyb['reply']}")

    n = len(questions)
    print("\n" + "#" * 70)
    print(f"SPARQL-only answered: {sparql_only_found}/{n}")
    print(f"Hybrid answered:      {hybrid_found}/{n}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the evaluation**

Run:
```bash
PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe backend/eval/eval_hybrid.py
```
Expected: a per-question comparison, ending with a summary where **Hybrid answered ≥ SPARQL-only answered** (hybrid should answer at least as many conceptual questions, typically several more).

- [ ] **Step 3: (Optional) run against the user's real eval set**

When the user provides their Q/A JSON (a list of `{"question": "...", "expected": "..."}`), run:
```bash
PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe backend/eval/eval_hybrid.py path/to/eval.json
```
Expected: same format, measured over the real set.

---

## Self-Review notes

- **Spec coverage:** semantic text retrieval (Tasks 2–3), run-both-and-merge (Task 5), reuse SPARQL chain (Task 4 `retrieve_context`), Chroma local store + OpenAI embeddings (Tasks 1–3), graceful degradation (Task 5 try/except), measurable eval (Task 7). Image input / vision is explicitly Phase 2 and not covered here, per the spec's phasing.
- **No placeholders:** every code step contains complete code; every run step has an exact command and expected output.
- **Type consistency:** `load_vector_store() -> Chroma`, `vector_retrieve(store, query, k) -> str`, `retrieve_context(question) -> (str, str)`, `answer_question(question, qa_chain, vector_store, history_text) -> dict` with keys `reply`/`sparql_query`/`sources` are used consistently across Tasks 5–7.
