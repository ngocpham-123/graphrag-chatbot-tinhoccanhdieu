# Image Input (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user attach an image to a chat message; a vision model reads the image, the system retrieves related graph content (the Phase 1 hybrid path), and answers in Vietnamese — "understand & answer", grounded in the textbook.

**Architecture:** The image arrives as a base64 data URL in the existing JSON chat request. A new `vision_service` sends it to `gpt-4.1-mini` (vision) with the user's text and returns a Vietnamese description. The orchestrator (from Phase 1) gains an optional `image` argument: when present, it gets the vision description, uses `question + description` as the retrieval query for the existing SPARQL + vector retrievers, and passes the description as a third labeled evidence block to the answer LLM. Frontend gets an attach-image control.

**Tech Stack:** FastAPI, Pydantic, LangChain `ChatOpenAI` (multimodal `gpt-4.1-mini`), vanilla JS frontend.

**Spec:** `docs/superpowers/specs/2026-06-14-multimodal-hybrid-rag-design.md` (Phase 2)

**Builds on Phase 1:** `docs/superpowers/plans/2026-06-14-hybrid-text-retrieval.md` — `orchestrator.answer_question(...)`, `HYBRID_ANSWER_PROMPT`, the Chroma index, and the chat endpoint wiring already exist.

**Repo realities (read first):**
- NOT a git repository — skip all commit steps.
- No test harness (no pytest). Verify with runnable scripts and the running app.
- Windows + PowerShell. Run Python as `.venv/Scripts/python.exe` from the project root with `PYTHONUTF8=1 PYTHONPATH=.`. Bash tool examples use forward slashes.
- GraphDB must be up at `http://localhost:7200` (repo `Tin-hoc-canh-dieu`); `.env` has a working `OPENAI_API_KEY`; the Chroma index is built at `backend/data/chroma`.
- `gpt-4.1-mini` accepts image input via the OpenAI chat API; LangChain passes it as a `HumanMessage` whose `content` is a list with a `text` part and an `image_url` part.

---

## File Structure

- **Modify** `backend/app/models/schemas.py` — add optional `image` to `ChatRequest`.
- **Create** `backend/app/services/vision_service.py` — `describe_image(image_data, question) -> str`. Single responsibility: image → Vietnamese description.
- **Modify** `backend/app/services/chatgpt_service.py` — add `image_context` to `HYBRID_ANSWER_PROMPT`.
- **Modify** `backend/app/services/orchestrator.py` — `answer_question(...)` gains `image` arg; runs vision, folds the description into the retrieval query and the answer context.
- **Modify** `backend/app/routers/chat.py` — pass `request.image` to the orchestrator.
- **Modify** `frontend/index.html` — attach-image button + hidden file input + preview slot.
- **Modify** `frontend/app.js` — read file → data URL, send as `image`, show it on the user message, clear after send.
- **Modify** `frontend/styles.css` — minimal styles for the attach button + preview thumbnail.

---

## Task 1: Add `image` to the request schema

**Files:**
- Modify: `backend/app/models/schemas.py`

- [ ] **Step 1: Add the field**

In `backend/app/models/schemas.py`, change the `ChatRequest` class to:

```python
class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    image: str | None = None  # base64 data URL (e.g. "data:image/png;base64,...") or raw base64
```

Leave `ChatResponse` unchanged.

- [ ] **Step 2: Verify it imports and accepts the field**

Run:
```bash
PYTHONPATH=. .venv/Scripts/python.exe -c "from backend.app.models.schemas import ChatRequest; r = ChatRequest(message='hi', image='data:image/png;base64,AAA'); print(r.image[:20], '| no-image:', ChatRequest(message='hi').image)"
```
Expected: `data:image/png;base6 | no-image: None`

---

## Task 2: Vision service

**Files:**
- Create: `backend/app/services/vision_service.py`

**Context:** `backend/app/config.py` defines `OPENAI_API_KEY`. This module's only job is: given an image (base64 data URL or raw base64) and the user's text, return a short Vietnamese description focused on informatics concepts and search keywords. The orchestrator (Task 4) uses that description both to drive retrieval and as evidence for the answer.

- [ ] **Step 1: Write the module**

Create `backend/app/services/vision_service.py`:

```python
import logging

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from backend.app.config import OPENAI_API_KEY

logger = logging.getLogger(__name__)

_vision_llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0, api_key=OPENAI_API_KEY)

_VISION_INSTRUCTION = (
    "Bạn là trợ lí cho sách giáo khoa Tin học. Hãy quan sát hình ảnh và mô tả NỘI DUNG "
    "của nó bằng tiếng Việt, tập trung vào các khái niệm tin học liên quan (thiết bị, "
    "sơ đồ, giao diện phần mềm, mạch điện, v.v.). Nêu rõ hình thể hiện gì và liệt kê các "
    "từ khoá quan trọng có thể dùng để tra cứu trong sách. Trả lời ngắn gọn (2-4 câu). "
    "Câu hỏi của người dùng kèm theo hình: {question}"
)


def _to_data_url(image_data: str) -> str:
    """Accept either a full data URL or raw base64; return a data URL."""
    if image_data.startswith("data:"):
        return image_data
    return f"data:image/png;base64,{image_data}"


def describe_image(image_data: str, question: str) -> str:
    """Return a short Vietnamese description of the image, or "" on failure."""
    try:
        url = _to_data_url(image_data)
        msg = HumanMessage(content=[
            {"type": "text", "text": _VISION_INSTRUCTION.format(question=question or "")},
            {"type": "image_url", "image_url": {"url": url}},
        ])
        resp = _vision_llm.invoke([msg])
        return (resp.content or "").strip()
    except Exception:
        logger.exception("Vision description failed")
        return ""
```

- [ ] **Step 2: Verify against a real textbook figure**

Run (uses an existing asset image of a CPU; makes a real OpenAI vision call):
```bash
PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe -c "
import sys, io, base64; sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from backend.app.services.vision_service import describe_image
b = base64.b64encode(open('asset/g11_topicA_fig_l1_cpu.png','rb').read()).decode()
print(describe_image('data:image/png;base64,'+b, 'đây là cái gì?'))
"
```
Expected: a short Vietnamese description that recognizably refers to a CPU / bộ xử lí / vi xử lí (a non-empty, on-topic sentence or two).

---

## Task 3: Add the image evidence block to the hybrid answer prompt

**Files:**
- Modify: `backend/app/services/chatgpt_service.py`

**Context:** `HYBRID_ANSWER_PROMPT` currently has input variables `sparql_context`, `vector_context`, `prompt`. Add a third evidence block, `image_context`, so the answer LLM can use the vision description. For text-only questions the orchestrator will pass `image_context="(không có)"`, so behavior is unchanged for Phase 1.

- [ ] **Step 1: Replace `HYBRID_ANSWER_PROMPT`**

In `backend/app/services/chatgpt_service.py`, replace the entire `HYBRID_ANSWER_PROMPT = PromptTemplate(...)` block with:

```python
# Answer prompt for the hybrid orchestrator. Receives three labeled evidence
# blocks: structured SPARQL rows, semantic passages, and (optional) a vision
# description of an attached image. Same honesty rules: use evidence even if
# partial, never contradict, say "not found" only when ALL blocks are empty.
HYBRID_ANSWER_PROMPT = PromptTemplate(
    input_variables=["sparql_context", "vector_context", "image_context", "prompt"],
    template="""\
Bạn là trợ lí AI trả lời câu hỏi về sách giáo khoa "Tin học  -10 Cánh Diều".
Dưới đây là bằng chứng truy xuất từ knowledge graph của cuốn sách, gồm: kết quả
truy vấn cấu trúc (SPARQL), các đoạn văn liên quan (tìm kiếm ngữ nghĩa), và mô tả
hình ảnh người dùng gửi kèm (nếu có). Đây là nguồn đáng tin cậy: không nghi ngờ,
không dùng kiến thức riêng để sửa lại.

Quy tắc trả lời (tiếng Việt, rõ ràng, tự nhiên):
- Nếu có một hình ảnh được mô tả, hãy dựa vào mô tả đó để hiểu người dùng đang hỏi
  về cái gì, rồi kết hợp với bằng chứng từ sách để trả lời.
- Nếu BẤT KỲ phần nào có dữ liệu, BẮT BUỘC dùng nó để trả lời; tổng hợp các phần
  thành một câu trả lời mạch lạc. Nếu chỉ liên quan một phần, hãy trình bày như
  thông tin liên quan và nói rõ là chưa có mục đúng chính xác.
- TUYỆT ĐỐI KHÔNG nói "không tìm thấy" khi vẫn còn dữ liệu, và KHÔNG tự mâu thuẫn.
- CHỈ khi TẤT CẢ các phần đều TRỐNG thì mới nói rằng bạn không tìm thấy thông tin
  về câu hỏi này trong sách.
- Không bịa thêm thông tin nằm ngoài bằng chứng.

Mô tả hình ảnh (nếu có):
{image_context}

Kết quả truy vấn (SPARQL):
{sparql_context}

Đoạn văn liên quan (ngữ nghĩa):
{vector_context}

Câu hỏi: {prompt}
Trả lời:""",
)
```

- [ ] **Step 2: Verify the prompt now has four input variables**

Run:
```bash
PYTHONPATH=. .venv/Scripts/python.exe -c "from backend.app.services.chatgpt_service import HYBRID_ANSWER_PROMPT; print(sorted(HYBRID_ANSWER_PROMPT.input_variables))"
```
Expected: `['image_context', 'prompt', 'sparql_context', 'vector_context']`

---

## Task 4: Orchestrator handles the image

**Files:**
- Modify: `backend/app/services/orchestrator.py`

**Context:** `answer_question` currently runs condense → SPARQL retrieval + vector retrieval → `HYBRID_ANSWER_PROMPT.format(sparql_context, vector_context, prompt)`. Add an optional `image` argument. When present: get a Vietnamese description via `describe_image`, use `standalone + "\n" + description` as the retrieval query (so SPARQL/vector find related content), add `"image"` to `sources`, and pass the description as `image_context`. The `HYBRID_ANSWER_PROMPT.format(...)` call must now also pass `image_context` (always — `"(không có)"` when no image).

- [ ] **Step 1: Replace `orchestrator.py` with the image-aware version**

Replace the entire contents of `backend/app/services/orchestrator.py` with:

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
from backend.app.services.vision_service import describe_image

logger = logging.getLogger(__name__)

_answer_llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0, api_key=OPENAI_API_KEY)


def answer_question(
    question: str,
    qa_chain: FormattedGraphDBQAChain,
    vector_store: Chroma,
    history_text: str = "",
    image: str | None = None,
) -> dict:
    """Hybrid answer: optional image understanding + SPARQL + vector retrieval, merged.

    Returns {"reply": str, "sparql_query": str | None, "sources": list[str]}.
    """
    standalone = condense_question(history_text, question)
    sources = []

    # Image: describe it, then fold the description into the retrieval query so
    # SPARQL and vector search find related textbook content.
    image_context = ""
    if image:
        image_context = describe_image(image, standalone)
        if image_context:
            sources.append("image")
    retrieval_query = f"{standalone}\n{image_context}".strip() if image_context else standalone

    sparql_context, sparql = "", None
    try:
        sparql_context, sparql = qa_chain.retrieve_context(retrieval_query)
    except Exception:
        logger.exception("SPARQL retrieval failed; continuing without it")

    vector_context = ""
    try:
        vector_context = vector_retrieve(vector_store, retrieval_query, k=6)
    except Exception:
        logger.exception("Vector retrieval failed; continuing without it")

    if sparql_context:
        sources.append("sparql")
    if vector_context:
        sources.append("vector")

    msg = HYBRID_ANSWER_PROMPT.format(
        image_context=image_context or "(không có)",
        sparql_context=sparql_context or "(trống)",
        vector_context=vector_context or "(trống)",
        prompt=standalone,
    )
    reply = (_answer_llm.invoke(msg).content or "").strip()
    logger.info("Hybrid answer sources=%s standalone=%r", sources, standalone)

    return {"reply": reply, "sparql_query": sparql, "sources": sources}
```

- [ ] **Step 2: Verify text-only still works (no regression)**

Run:
```bash
PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe -c "
import sys, io; sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from backend.app.services.graphdb_service import create_graph
from backend.app.services.chatgpt_service import create_qa_chain
from backend.app.services.vector_index import load_vector_store
from backend.app.services.orchestrator import answer_question
g=create_graph(); qa=create_qa_chain(g); vs=load_vector_store()
r=answer_question('máy tính đem lại lợi ích gì cho xã hội?', qa, vs)
print('SOURCES:', r['sources']); print('REPLY:', r['reply'][:200])
"
```
Expected: `SOURCES:` has no `image`, includes `vector` (often `sparql`); non-empty Vietnamese reply.

- [ ] **Step 3: Verify the image path end-to-end**

Run (feeds the CPU figure as the image; makes real vision + retrieval + answer calls):
```bash
PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe -c "
import sys, io, base64; sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from backend.app.services.graphdb_service import create_graph
from backend.app.services.chatgpt_service import create_qa_chain
from backend.app.services.vector_index import load_vector_store
from backend.app.services.orchestrator import answer_question
g=create_graph(); qa=create_qa_chain(g); vs=load_vector_store()
b='data:image/png;base64,'+base64.b64encode(open('asset/g11_topicA_fig_l1_cpu.png','rb').read()).decode()
r=answer_question('Thiết bị trong hình này là gì và sách nói gì về nó?', qa, vs, image=b)
print('SOURCES:', r['sources']); print('REPLY:', r['reply'])
"
```
Expected: `SOURCES:` includes `image` (and usually `vector`/`sparql`); `REPLY:` is a Vietnamese answer that identifies the device (CPU / bộ xử lí) and ties in textbook content.

---

## Task 5: Pass the image through the chat endpoint

**Files:**
- Modify: `backend/app/routers/chat.py`

**Context:** The endpoint already calls `answer_question(request.message, qa_chain, vector_store, history_text)`. Add the image argument. Nothing else changes.

- [ ] **Step 1: Pass `image=request.image`**

In `backend/app/routers/chat.py`, change the line:
```python
        result = answer_question(request.message, qa_chain, vector_store, history_text)
```
to:
```python
        result = answer_question(
            request.message, qa_chain, vector_store, history_text, image=request.image
        )
```

- [ ] **Step 2: Verify the endpoint accepts an image over HTTP**

Start the server in the BACKGROUND from the project root (use run_in_background):
```bash
PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe -m uvicorn backend.app.main:app --port 8012
```
Wait ~15-20s for startup. Then run this foreground check (builds a JSON body with a real image via Python, posts it with curl, prints the reply):
```bash
PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe -c "
import json, base64
b='data:image/png;base64,'+base64.b64encode(open('asset/g11_topicA_fig_l1_cpu.png','rb').read()).decode()
open('/tmp/img_body.json','w',encoding='utf-8').write(json.dumps({'message':'Hình này là gì?','image':b}))
print('body written')
"
curl -s -X POST http://localhost:8012/api/chat/ -H "Content-Type: application/json" --data-binary @/tmp/img_body.json | PYTHONUTF8=1 .venv/Scripts/python.exe -c "import sys,io,json; sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8'); d=json.load(sys.stdin); print('REPLY:', d.get('reply'))"
```
Expected: HTTP 200; `REPLY:` is a Vietnamese answer identifying the device from the image. Kill the background server afterward.

---

## Task 6: Frontend — attach, send, and show an image

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`

**Context:** The chat form (`#chat-form`) has a `#user-input` textarea and a `#send-btn`. The submit handler in `app.js` posts `{message, conversation_id}` and renders messages via `appendMessage(role, content, figurePaths)`. We add an attach-image control, send the chosen image as `image` (base64 data URL), show it on the user's message bubble, and clear it after sending.

- [ ] **Step 1: Add the attach control to the form (`index.html`)**

In `frontend/index.html`, replace the `<form id="chat-form" class="input-form"> ... </form>` block (lines ~54-67) with:

```html
      <form id="chat-form" class="input-form">
        <div id="image-preview" class="image-preview hidden">
          <img id="image-preview-img" alt="attachment preview" />
          <button type="button" id="image-remove-btn" title="Remove image">✕</button>
        </div>
        <input type="file" id="image-input" accept="image/*" hidden />
        <button type="button" id="attach-btn" title="Attach image">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
          </svg>
        </button>
        <textarea
          id="user-input"
          placeholder="Type a message…"
          rows="1"
          autocomplete="off"
        ></textarea>
        <button type="submit" id="send-btn" title="Send">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 2L11 13"/>
            <path d="M22 2L15 22L11 13L2 9L22 2Z"/>
          </svg>
        </button>
      </form>
```

- [ ] **Step 2: Add styles (`styles.css`)**

Append to `frontend/styles.css`:

```css
/* Image attach button + preview (Phase 2) */
#attach-btn {
  background: transparent;
  border: none;
  color: #8e8ea0;
  cursor: pointer;
  padding: 8px;
  display: flex;
  align-items: center;
}
#attach-btn:hover { color: #ececec; }

.image-preview {
  position: relative;
  display: inline-block;
  margin-right: 8px;
}
.image-preview.hidden { display: none; }
.image-preview img {
  max-height: 56px;
  max-width: 56px;
  border-radius: 8px;
  border: 1px solid #444;
  object-fit: cover;
}
#image-remove-btn {
  position: absolute;
  top: -6px;
  right: -6px;
  background: #333;
  color: #ececec;
  border: 1px solid #555;
  border-radius: 50%;
  width: 18px;
  height: 18px;
  line-height: 1;
  font-size: 11px;
  cursor: pointer;
  padding: 0;
}
.message .message-image {
  display: block;
  max-width: 220px;
  max-height: 220px;
  border-radius: 8px;
  margin-bottom: 6px;
  cursor: pointer;
}
```

- [ ] **Step 3: Wire the control and sending (`app.js`)**

In `frontend/app.js`, add these DOM refs next to the existing refs (after the `sparqlInput`/`graph*` refs near the top, e.g. after line 20):

```javascript
const imageInput = document.getElementById("image-input");
const attachBtn = document.getElementById("attach-btn");
const imagePreview = document.getElementById("image-preview");
const imagePreviewImg = document.getElementById("image-preview-img");
const imageRemoveBtn = document.getElementById("image-remove-btn");

// Holds the currently attached image as a base64 data URL (or null)
let selectedImage = null;

attachBtn.addEventListener("click", () => imageInput.click());

imageInput.addEventListener("change", () => {
  const file = imageInput.files && imageInput.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    selectedImage = reader.result; // data URL
    imagePreviewImg.src = selectedImage;
    imagePreview.classList.remove("hidden");
  };
  reader.readAsDataURL(file);
});

imageRemoveBtn.addEventListener("click", clearSelectedImage);

function clearSelectedImage() {
  selectedImage = null;
  imageInput.value = "";
  imagePreviewImg.removeAttribute("src");
  imagePreview.classList.add("hidden");
}
```

- [ ] **Step 4: Update `appendMessage` to optionally show an image (`app.js`)**

In `frontend/app.js`, change the `appendMessage` signature and add image rendering. Replace the function header line:
```javascript
function appendMessage(role, content, figurePaths) {
```
with:
```javascript
function appendMessage(role, content, figurePaths, imageDataUrl) {
```
and immediately AFTER the line `msgDiv.innerHTML = formatContent(content);` add:
```javascript
  // Show an attached image (user-sent) above the text
  if (imageDataUrl) {
    const img = document.createElement("img");
    img.className = "message-image";
    img.src = imageDataUrl;
    img.alt = "attached image";
    img.addEventListener("click", () => window.open(img.src, "_blank"));
    msgDiv.insertBefore(img, msgDiv.firstChild);
  }
```

- [ ] **Step 5: Send the image on submit and clear it (`app.js`)**

In the `chatForm` submit handler in `frontend/app.js`:

1. Change the guard at the top of the handler from:
```javascript
  const message = userInput.value.trim();
  if (!message) return;
```
to:
```javascript
  const message = userInput.value.trim();
  if (!message && !selectedImage) return;
  const imageToSend = selectedImage;
```

2. Change the user-message display call from:
```javascript
  appendMessage("user", message);
```
to:
```javascript
  appendMessage("user", message, null, imageToSend);
  clearSelectedImage();
```

3. Change the fetch body from:
```javascript
      body: JSON.stringify({
        message,
        conversation_id: currentConversationId,
      }),
```
to:
```javascript
      body: JSON.stringify({
        message,
        conversation_id: currentConversationId,
        image: imageToSend || null,
      }),
```

4. In the success branch, store the image on the saved user message so it survives conversation reloads. Change:
```javascript
    conv.messages.push({ role: "user", content: message });
```
to:
```javascript
    conv.messages.push({ role: "user", content: message, image: imageToSend });
```

- [ ] **Step 6: Render stored images when reloading a conversation (`app.js`)**

In `loadConversation`, change the message render call from:
```javascript
    appendMessage(msg.role, msg.content, msg.figure_paths);
```
to:
```javascript
    appendMessage(msg.role, msg.content, msg.figure_paths, msg.image);
```

- [ ] **Step 7: Verify the page serves and JS parses**

Start the server in the background:
```bash
PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe -m uvicorn backend.app.main:app --port 8013
```
Wait ~15s, then:
```bash
curl -s http://localhost:8013/ | grep -c "image-input"
curl -s -o /dev/null -w "app.js %{http_code}\n" http://localhost:8013/app.js
```
Expected: the first prints `1` or more (the file input is present in served HTML); the second prints `app.js 200`. If `node` is available, also run `node --check frontend/app.js` and expect no output (syntax OK). Kill the server.

- [ ] **Step 8: Manual visual check**

With the server running (`uvicorn backend.app.main:app --port 8000`), open `http://localhost:8000`, click the attach (paperclip) button, choose an image (e.g. `asset/g11_topicA_fig_l1_cpu.png`), confirm the thumbnail preview appears, type "Hình này là gì?", send, and confirm: the image shows on your message bubble and the assistant replies in Vietnamese identifying the device. (Manual — no automated browser test in this repo.)

---

## Self-Review notes

- **Spec coverage (Phase 2):** image arrives in request (Task 1), vision "understand" (Task 2), image description added as answer evidence (Task 3), orchestrator routes image deterministically + folds description into retrieval (Task 4), endpoint passes it through (Task 5), frontend upload + display (Task 6). Graceful degradation: `describe_image` returns "" on failure and the orchestrator proceeds text-only; `image` is optional everywhere.
- **No placeholders:** every code step shows full code; every run step has an exact command and expected output.
- **Type consistency:** `describe_image(image_data: str, question: str) -> str`; `answer_question(question, qa_chain, vector_store, history_text="", image=None) -> dict` (keys `reply`/`sparql_query`/`sources`); `HYBRID_ANSWER_PROMPT` input vars `image_context`/`sparql_context`/`vector_context`/`prompt` are passed consistently in Task 4's `.format(...)`. Frontend `appendMessage(role, content, figurePaths, imageDataUrl)` updated at all three call sites (submit, loadConversation; the typing indicator does not call it).
