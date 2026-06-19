# SPARQL Result Figures + Inline Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Show figure images in the chat answer when a query's results contain figure names that map to `asset/` images; (2) add an inline, collapsible, lazily-rendered mini-graph to the per-answer SPARQL badge.

**Architecture:** Backend resolves figures by **name → asset file** (the figure node's local name equals the image filename, minus extension) over the raw SPARQL bindings, returns them via the existing `ChatResponse.figure_paths`, and the existing frontend gallery renders them. The frontend graph renderer is refactored to target any container so the badge can show a small inline graph fed by the existing `/api/chat/sparql` endpoint.

**Tech Stack:** FastAPI, LangChain (`OntotextGraphDBQAChain`), rdflib, vanilla JS + vis-network.

**Spec:** `docs/superpowers/specs/2026-06-17-result-figures-and-inline-graph-design.md`

**Repo realities (read first):**
- NOT a git repository — skip all commit steps.
- No test harness (no pytest). Verify with runnable scripts and the running app.
- Windows + PowerShell. Run Python as `.venv/Scripts/python.exe` from the project root with `PYTHONUTF8=1 PYTHONPATH=.`. Bash tool examples use forward slashes.
- GraphDB must be up at `http://localhost:7200` (repo `Tin-hoc-canh-dieu`); `.env` has `OPENAI_API_KEY`; the Chroma index is built.
- Figures are served at `/figures/<filename>` from `FIGURES_DIR` (default `asset/`); `main.py` exposes `/figures/manifest`.
- Frontend JS/CSS are served under `/static/` (e.g. `/static/app.js`); the page is `/`.

---

## File Structure

- **Create** `backend/app/services/figures.py` — name→image-URL resolution over result values. Single responsibility.
- **Modify** `backend/app/services/chatgpt_service.py` — `retrieve_context` returns figure URLs too; figure few-shots also `SELECT ?fig`.
- **Modify** `backend/app/services/orchestrator.py` — return `figure_paths` from `answer_question`.
- **Modify** `backend/app/routers/chat.py` — merge SPARQL-derived figures with the reply-text scan into `ChatResponse.figure_paths`.
- **Modify** `frontend/app.js` — refactor `renderGraph`→`renderGraphInto`; add inline graph toggle to `appendSparqlBadge`.
- **Modify** `frontend/styles.css` — inline graph container + toggle styles.

---

## Task 1: Figure resolution helper

**Files:**
- Create: `backend/app/services/figures.py`

**Context:** A figure's image is found by matching the *local name* of a result value (the part after the last `#` or `/`, or the bare string) against image files in `FIGURES_DIR`, ignoring extension. `backend/app/config.py` defines `FIGURES_DIR` (default `"asset"`). Result rows are rdflib `ResultRow` objects (iterable of terms; `str(term)` gives the value/URI).

- [ ] **Step 1: Write the module**

Create `backend/app/services/figures.py`:

```python
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
```

- [ ] **Step 2: Verify resolution on real names**

Run:
```bash
PYTHONPATH=. .venv/Scripts/python.exe -c "
from backend.app.services.figures import figure_url_for_value, _STEM_INDEX
print('index size:', len(_STEM_INDEX))
print('uri   ->', figure_url_for_value('http://example.org/tinhoc10-cd#g11_topicA_fig_l1_cpu'))
print('bare  ->', figure_url_for_value('g11_topicA_fig_l1_cpu'))
print('file  ->', figure_url_for_value('g11_topicA_fig_l1_cpu.png'))
print('none  ->', figure_url_for_value('http://example.org/tinhoc10-cd#conceptThongTin'))
"
```
Expected: `index size:` a few hundred; first three print `/figures/g11_topicA_fig_l1_cpu.png`; last prints `None`.

---

## Task 2: `retrieve_context` returns figure URLs + figure few-shots select `?fig`

**Files:**
- Modify: `backend/app/services/chatgpt_service.py`

**Context:** `FormattedGraphDBQAChain.retrieve_context(question)` currently returns `(context, sparql)`: it generates SPARQL, calls `self._get_prepared_sparql_query(...)`, then `self._execute_query(sparql)` (which returns the formatted text and internally does `self.graph.query` + `_format_query_results`). To also return figure URLs we must see the raw rows, so `retrieve_context` will run `self.graph.query` itself, materialize rows once, and produce both the text and the figure URLs. `_format_query_results(results)` already does `rows = list(results)`, so it accepts a list fine.

- [ ] **Step 1: Import the figures helper**

Near the top of `backend/app/services/chatgpt_service.py`, with the other `backend.app...` imports, add:
```python
from backend.app.services.figures import figure_urls_from_rows
```

- [ ] **Step 2: Update `retrieve_context` to return figure URLs**

Replace the existing `retrieve_context` method body with:
```python
    def retrieve_context(self, question: str) -> tuple[str, str, list[str]]:
        """Generate + execute SPARQL; return (formatted_rows, sparql_query, figure_urls).

        Reuses the chain's SPARQL generation/fix logic, stops before answer
        generation. figure_urls are /figures/... URLs for any result value whose
        name matches an asset image. Returns ("", sparql, []) when no rows.
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
        rows = list(self.graph.query(sparql))
        context = _format_query_results(rows)
        figure_urls = figure_urls_from_rows(rows)
        return context, sparql, figure_urls
```

- [ ] **Step 3: Make the figure few-shots SELECT the figure node**

In `SPARQL_GENERATION_PROMPT`, update the two figure examples so the figure variable is returned (its name is needed to resolve the image).

Replace the IoT figure example's SELECT line:
```
SELECT ?caption ?fig WHERE {{
```
(no change needed if it already selects `?fig` — confirm it does; the IoT example already is `SELECT ?caption ?fig`).

Replace the "Cho tôi các hình ảnh trong bài 1 topic A lớp 11" example's:
```
SELECT ?caption WHERE {{
```
with:
```
SELECT ?caption ?fig WHERE {{
```
(Its body already binds `?fig a ex:Figure ; ex:belongsToLesson ?lesson .`, so `?fig` is available — we just add it to the projection.)

- [ ] **Step 4: Verify the new return shape end-to-end (figure question)**

Run:
```bash
PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe -c "
import sys, io; sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from backend.app.services.graphdb_service import create_graph
from backend.app.services.chatgpt_service import create_qa_chain
g=create_graph(); qa=create_qa_chain(g)
ctx, sparql, figs = qa.retrieve_context('cho tôi các hình ảnh trong bài 1 topic A lớp 11')
print('FIG URLS:', figs)
"
```
Expected: `FIG URLS:` a non-empty list of `/figures/g11_topicA_fig_l1_*.png` URLs (e.g. cpu, ram, mainboard, ssd).

- [ ] **Step 5: Verify a non-figure question yields no figures**

Run:
```bash
PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe -c "
import sys, io; sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from backend.app.services.graphdb_service import create_graph
from backend.app.services.chatgpt_service import create_qa_chain
g=create_graph(); qa=create_qa_chain(g)
ctx, sparql, figs = qa.retrieve_context('thông tin là gì?')
print('FIG URLS:', figs)
"
```
Expected: `FIG URLS: []`

---

## Task 3: Orchestrator returns `figure_paths`

**Files:**
- Modify: `backend/app/services/orchestrator.py`

**Context:** `answer_question` calls `qa_chain.retrieve_context(retrieval_query)` which now returns a 3-tuple. Capture the figure URLs and include them in the returned dict.

- [ ] **Step 1: Unpack the 3-tuple and return figures**

In `backend/app/services/orchestrator.py`, change the SPARQL retrieval block. Replace:
```python
    sparql_context, sparql = "", None
    try:
        sparql_context, sparql = qa_chain.retrieve_context(retrieval_query)
    except Exception:
        logger.exception("SPARQL retrieval failed; continuing without it")
```
with:
```python
    sparql_context, sparql, figure_paths = "", None, []
    try:
        sparql_context, sparql, figure_paths = qa_chain.retrieve_context(retrieval_query)
    except Exception:
        logger.exception("SPARQL retrieval failed; continuing without it")
```

And change the final return. Replace:
```python
    return {"reply": reply, "sparql_query": sparql, "sources": sources}
```
with:
```python
    return {
        "reply": reply,
        "sparql_query": sparql,
        "sources": sources,
        "figure_paths": figure_paths,
    }
```

- [ ] **Step 2: Verify the orchestrator surfaces figures**

Run:
```bash
PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe -c "
import sys, io; sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from backend.app.services.graphdb_service import create_graph
from backend.app.services.chatgpt_service import create_qa_chain
from backend.app.services.vector_index import load_vector_store
from backend.app.services.orchestrator import answer_question
g=create_graph(); qa=create_qa_chain(g); vs=load_vector_store()
r=answer_question('cho tôi các hình ảnh trong bài 1 topic A lớp 11', qa, vs)
print('FIG PATHS:', r['figure_paths'])
print('REPLY head:', r['reply'][:120])
"
```
Expected: `FIG PATHS:` a non-empty list of `/figures/...png`; reply is Vietnamese listing the figures.

---

## Task 4: Merge figures into the chat response

**Files:**
- Modify: `backend/app/routers/chat.py`

**Context:** The endpoint currently computes `figure_paths = extract_figure_paths_from_reply(reply)`. Now also include the orchestrator's `result["figure_paths"]` (the reliable, SPARQL-derived figures), de-duplicated and order-preserving, with the SPARQL figures first.

- [ ] **Step 1: Merge the two sources**

In `backend/app/routers/chat.py`, find:
```python
        # Extract figure paths from the reply text
        figure_paths = extract_figure_paths_from_reply(reply)
        print(f"[DEBUG] Extracted figure_paths: {figure_paths}")
```
and replace with:
```python
        # Figures: those returned by the SPARQL results (reliable) first, then
        # any paths mentioned in the reply text, de-duplicated, order-preserving.
        figure_paths = list(result.get("figure_paths") or [])
        for p in extract_figure_paths_from_reply(reply):
            if p not in figure_paths:
                figure_paths.append(p)
        print(f"[DEBUG] figure_paths: {figure_paths}")
```

Leave the history append and `ChatResponse(... figure_paths=figure_paths if figure_paths else None)` as-is.

- [ ] **Step 2: Verify over HTTP**

Start the server in the background:
```bash
PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe -m uvicorn backend.app.main:app --port 8021
```
Wait ~15s, then (write the body via Python to avoid shell-encoding issues):
```bash
PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe -c "import json; open('img_q.json','w',encoding='utf-8').write(json.dumps({'message':'cho tôi các hình ảnh trong bài 1 topic A lớp 11'}))"
curl -s -X POST http://localhost:8021/api/chat/ -H "Content-Type: application/json" --data-binary @img_q.json | PYTHONUTF8=1 .venv/Scripts/python.exe -c "import sys,io,json; sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8'); d=json.load(sys.stdin); print('figure_paths:', d.get('figure_paths'))"
```
Expected: `figure_paths:` a non-empty list of `/figures/...png`. Delete `img_q.json` and kill the server afterward.

---

## Task 5: Refactor `renderGraph` → `renderGraphInto`

**Files:**
- Modify: `frontend/app.js`

**Context:** `renderGraph(columns, rows)` builds nodes/edges and creates a `vis.Network` inside the module-level `graphContainer` (the overlay). We extract everything except the overlay-specific bits into `renderGraphInto(container, columns, rows)` so the inline badge graph (Task 6) can reuse it. The overlay path keeps its current behavior (show overlay, handle empty/error in the overlay).

- [ ] **Step 1: Add `renderGraphInto` and make `renderGraph` delegate**

In `frontend/app.js`, locate `async function renderGraph(columns, rows) { ... }`. Keep the overlay-specific framing in `renderGraph`, and move the graph construction into a new function. Replace the existing function with:

```javascript
// Build a vis-network graph from SPARQL results into the given container.
async function renderGraphInto(container, columns, rows) {
  await loadFigureManifest();

  const nodesMap = new Map(); // id -> { label, type, imageUrl }
  const edges = [];

  if (isTriplePattern(columns)) {
    for (const row of rows) {
      const subjectUri = row[0];
      const predicateUri = row[1];
      const objectUri = row[2];
      const predName = localName(predicateUri);

      if (!nodesMap.has(subjectUri)) {
        const subjFigureUrl = figureUrlForValue(subjectUri);
        nodesMap.set(subjectUri, {
          label: localName(subjectUri),
          type: subjFigureUrl ? "image" : "subject",
          imageUrl: subjFigureUrl,
        });
      }
      const figureUrl = figureUrlForValue(objectUri);
      if (!nodesMap.has(objectUri)) {
        nodesMap.set(objectUri, {
          label: localName(objectUri),
          type: figureUrl ? "image" : "object",
          imageUrl: figureUrl,
        });
      }
      edges.push({ from: subjectUri, to: objectUri, label: predName });
    }
  } else {
    const propertyCols = columns.slice(1);
    for (let rowIdx = 0; rowIdx < rows.length; rowIdx++) {
      const row = rows[rowIdx];
      const subjectUri = row[0];
      const subjectId = `${subjectUri}_row${rowIdx}`;
      if (!nodesMap.has(subjectId)) {
        const subjFigureUrl = figureUrlForValue(subjectUri);
        nodesMap.set(subjectId, {
          label: localName(subjectUri),
          type: subjFigureUrl ? "image" : "subject",
          imageUrl: subjFigureUrl,
        });
      }
      for (let colIdx = 0; colIdx < propertyCols.length; colIdx++) {
        const colName = propertyCols[colIdx];
        const value = row[colIdx + 1];
        if (!value) continue;
        const valueId = `${subjectId}_${colName}_${value}`;
        const valueLabel = localName(value);
        const figureUrl = figureUrlForValue(value);
        const displayLabel =
          valueLabel.length > 60 ? valueLabel.substring(0, 57) + "…" : valueLabel;
        if (!nodesMap.has(valueId)) {
          nodesMap.set(valueId, {
            label: displayLabel,
            type: figureUrl ? "image" : "property",
            imageUrl: figureUrl,
          });
        }
        edges.push({ from: subjectId, to: valueId, label: colName });
      }
    }
  }

  const nodeColors = {
    subject: { background: "#10a37f", border: "#0d8c6d" },
    object: { background: "#4a90d9", border: "#3a7bc8" },
    property: { background: "#8b5cf6", border: "#7c3aed" },
  };

  const nodeEntries = [];
  let nodeId = 0;
  const idLookup = new Map();
  for (const [uri, info] of nodesMap) {
    nodeId++;
    idLookup.set(uri, nodeId);
    const colors = nodeColors[info.type] || nodeColors.object;
    if (info.type === "image" && info.imageUrl) {
      nodeEntries.push({
        id: nodeId, label: info.label, shape: "image", image: info.imageUrl,
        size: 50, borderWidth: 3,
        color: { border: "#10a37f", background: "#1a1a1a" },
        shapeProperties: { useBorderWithImage: true, useImageSize: false },
        font: { color: "#ececec", size: 12, vadjust: 8 },
      });
    } else {
      nodeEntries.push({
        id: nodeId, label: info.label,
        color: { background: colors.background, border: colors.border },
        font: { color: "#ececec", size: info.type === "subject" ? 15 : 13 },
        shape: info.type === "subject" ? "dot" : "box",
        size: info.type === "subject" ? 22 : 12, borderWidth: 2,
      });
    }
  }

  const edgeEntries = edges.map((e) => ({
    from: idLookup.get(e.from), to: idLookup.get(e.to), label: e.label,
    arrows: "to", color: { color: "#666", highlight: "#aaa" },
    font: { color: "#a0a0a0", size: 11, strokeWidth: 0 },
  }));

  if (typeof vis === "undefined") {
    console.error("vis-network library not loaded!");
    return;
  }
  const visData = {
    nodes: new vis.DataSet(nodeEntries),
    edges: new vis.DataSet(edgeEntries),
  };
  const options = {
    physics: {
      solver: "forceAtlas2Based",
      forceAtlas2Based: { gravitationalConstant: -40, centralGravity: 0.005, springLength: 150, springConstant: 0.04 },
      stabilization: { iterations: 150 },
    },
    interaction: { hover: true, tooltipDelay: 200, zoomView: true, dragView: true },
    layout: { improvedLayout: true },
  };
  const network = new vis.Network(container, visData, options);
  network.on("stabilizationIterationsDone", () => network.fit());
}

// Overlay path: validate, show overlay, then render into the overlay container.
async function renderGraph(columns, rows) {
  graphError.classList.add("hidden");
  if (!rows || rows.length === 0) {
    graphError.textContent = "Query returned no results.";
    graphError.classList.remove("hidden");
    graphOverlay.classList.remove("hidden");
    return;
  }
  graphOverlay.classList.remove("hidden");
  setTimeout(() => renderGraphInto(graphContainer, columns, rows), 100);
}
```

- [ ] **Step 2: Syntax check**

Run (if `node` is available):
```bash
node --check frontend/app.js && echo "JS OK"
```
Expected: `JS OK`. If `node` is unavailable, say so and rely on the manual check in Task 6.

---

## Task 6: Inline graph toggle on the SPARQL badge

**Files:**
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`

**Context:** `appendSparqlBadge(query)` builds a badge with a header (`Show`/`Hide` for the query text) and a `pre.sparql-code`. Add a second toggle ("Show graph"/"Hide graph") and a hidden inline graph container. On first expand, fetch `/api/chat/sparql` for `query`, then `renderGraphInto(thatContainer, columns, rows)`; afterward just toggle visibility.

- [ ] **Step 1: Update `appendSparqlBadge` in `frontend/app.js`**

Replace the entire `appendSparqlBadge(query)` function with:

```javascript
// ── SPARQL badge ──
function appendSparqlBadge(query) {
  const row = document.createElement("div");
  row.className = "message-row";

  const badge = document.createElement("div");
  badge.className = "sparql-badge";

  const header = document.createElement("div");
  header.className = "sparql-badge-header";
  header.innerHTML =
    `<span>SPARQL Query Executed</span>` +
    `<span class="sparql-actions">` +
    `<button class="sparql-toggle">Show</button>` +
    `<button class="sparql-graph-toggle">Show graph</button>` +
    `</span>`;
  badge.appendChild(header);

  const codeBlock = document.createElement("pre");
  codeBlock.className = "sparql-code hidden";
  codeBlock.textContent = query;
  badge.appendChild(codeBlock);

  const graphBox = document.createElement("div");
  graphBox.className = "sparql-graph hidden";
  badge.appendChild(graphBox);

  header.querySelector(".sparql-toggle").addEventListener("click", (e) => {
    const isHidden = codeBlock.classList.toggle("hidden");
    e.target.textContent = isHidden ? "Show" : "Hide";
  });

  let graphRendered = false;
  header.querySelector(".sparql-graph-toggle").addEventListener("click", async (e) => {
    const btn = e.target;
    // Toggle visibility if already rendered
    if (graphRendered) {
      const isHidden = graphBox.classList.toggle("hidden");
      btn.textContent = isHidden ? "Show graph" : "Hide graph";
      return;
    }
    btn.disabled = true;
    btn.textContent = "Loading…";
    graphBox.classList.remove("hidden");
    graphBox.textContent = "";
    try {
      const res = await fetch("/api/chat/sparql", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Query failed");
      }
      const data = await res.json();
      if (!data.rows || data.rows.length === 0) {
        graphBox.textContent = "Query returned no results.";
      } else {
        await renderGraphInto(graphBox, data.columns, data.rows);
      }
      graphRendered = true;
      btn.textContent = "Hide graph";
    } catch (err) {
      graphBox.textContent = `Error: ${err.message}`;
      graphRendered = true; // keep the error visible; allow toggling
      btn.textContent = "Hide graph";
    } finally {
      btn.disabled = false;
    }
  });

  row.appendChild(badge);
  messagesContainer.appendChild(row);
}
```

- [ ] **Step 2: Add styles in `frontend/styles.css`**

Append:
```css
/* Inline graph in the SPARQL badge */
.sparql-actions { display: inline-flex; gap: 8px; }
.sparql-graph-toggle {
  background: transparent;
  border: 1px solid #555;
  color: #ececec;
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 12px;
  cursor: pointer;
}
.sparql-graph-toggle:hover { background: #333; }
.sparql-graph-toggle:disabled { opacity: 0.6; cursor: default; }
.sparql-graph {
  height: 300px;
  margin-top: 8px;
  border: 1px solid #333;
  border-radius: 8px;
  background: #0e0e0e;
  overflow: hidden;
}
.sparql-graph.hidden { display: none; }
```

- [ ] **Step 3: Syntax check + served-content check**

If `node` is available:
```bash
node --check frontend/app.js && echo "JS OK"
```
Expected: `JS OK`.

Start the server in the background:
```bash
PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe -m uvicorn backend.app.main:app --port 8022
```
Wait ~15s, then:
```bash
curl -s http://localhost:8022/static/app.js | grep -c "renderGraphInto"
curl -s http://localhost:8022/static/app.js | grep -c "sparql-graph-toggle"
```
Expected: both print `1` or more. Kill the server.

- [ ] **Step 4: Manual visual check**

Run `uvicorn backend.app.main:app --port 8000`, open `http://localhost:8000`:
- Ask "cho tôi các hình ảnh trong bài 1 topic A lớp 11" → confirm figure thumbnails appear in the answer.
- On the SPARQL badge, click **Show graph** → confirm an inline ~300px graph renders below the badge and toggles with Hide graph.

---

## Self-Review notes

- **Spec coverage:** name→asset figure resolution (Task 1), figure URLs from results + few-shot `?fig` (Task 2), orchestrator `figure_paths` (Task 3), merge into `ChatResponse` (Task 4), `renderGraphInto` refactor (Task 5), inline lazy badge graph + styles (Task 6). Frontend gallery reuse and `/api/chat/sparql` reuse are explicit; no schema change.
- **No placeholders:** every code step has full code; every run step has an exact command and expected output.
- **Type consistency:** `retrieve_context -> (str, str, list[str])` is unpacked as a 3-tuple in Task 3; `answer_question` result dict gains `figure_paths` consumed in Task 4; `renderGraphInto(container, columns, rows)` is called by both `renderGraph` (Task 5) and the badge toggle (Task 6); `figure_url_for_value` / `figure_urls_from_rows` names match between Task 1 and Task 2.
