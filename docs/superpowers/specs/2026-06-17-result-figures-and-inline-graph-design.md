# Design: SPARQL Result Figures + Inline Graph

**Date:** 2026-06-17
**Status:** Approved (design), pending implementation plan
**Builds on:** the hybrid orchestrator (`orchestrator.answer_question`), `FormattedGraphDBQAChain.retrieve_context`, the existing figure serving (`/figures/...`, `/figures/manifest`), and the existing graph visualization (`renderGraph` + overlay in `frontend/app.js`).

## Problem

Two result-display gaps in the chat UI:

1. **Figures returned by a query are never shown.** `ChatResponse.figure_paths` is filled only by regex-scanning the *answer text* for `.png` paths, which essentially never matches (answers are prose). The SPARQL results that actually contain figures are formatted to text and the figure identifiers discarded.
2. **The SPARQL badge shows the query text but not its graph.** The app can already visualize a query (`/api/chat/sparql` + `renderGraph`), but only via the SPARQL-editor's Execute button into a full-screen overlay — not from the per-answer badge.

## Key data fact (verified)

A figure node (e.g. `…#g11_topicA_fig_l1_cpu`) has **no property holding an image filename**. Its only link to an image is the node's **own name**: the local part of the URI (`g11_topicA_fig_l1_cpu`) equals the asset file `asset/g11_topicA_fig_l1_cpu.png` (minus extension). So image resolution is **name → asset file**, exactly as the existing graph view already does client-side (`localName` + `/figures/manifest`).

## Goals

1. When a query's results contain figure identifiers that map to real `asset/` images, show those images in the chat answer.
2. Let the user expand an **inline minimal graph** of the executed SPARQL directly from the badge, collapsed by default.

## Non-goals

- A dedicated image-filename property on figures (none exists; not adding one).
- Replacing the full-screen graph overlay (it stays for the SPARQL editor).
- Any schema change (`ChatResponse.figure_paths` already exists).

## Decisions

- **Figure detection = name match against `asset/`** (mirror the existing frontend `figureUrlForValue`), done backend-side over the raw SPARQL bindings. Show figures whenever results contain figure names that map to image files (not gated on the user saying "image").
- **Inline graph, not overlay,** for the badge. Collapsed by default; renders lazily on first expand; toggles thereafter without re-fetching.
- **DRY the renderer:** refactor `renderGraph` into `renderGraphInto(container, columns, rows)` shared by the inline mini-graph and the existing overlay.

## Architecture / components

### Feature 1 — figures from results (backend)

**New `backend/app/services/figures.py`** (single responsibility: name → image URL):
- Loads the set of image filenames in `FIGURES_DIR` once (basename + basename-without-extension index).
- `local_name(value: str) -> str` — part after the last `#` or `/`, else the value itself.
- `figure_url_for_value(value: str) -> str | None` — returns `/figures/<filename>` if `local_name(value)` matches an asset image (by stem), else `None`.
- `figure_urls_from_rows(rows) -> list[str]` — iterate rdflib result rows, test every bound value, collect unique `/figures/...` URLs in order.

**`backend/app/services/chatgpt_service.py`:**
- `FormattedGraphDBQAChain.retrieve_context(question)` now returns `(context: str, sparql: str, figure_urls: list[str])`. It materializes the query rows once, formats the text context (as today) **and** extracts figure URLs via `figures.figure_urls_from_rows`.
- Figure few-shot examples updated to `SELECT` the figure node (e.g. `?fig`) in addition to `?caption`, so a figure name reaches the results for image resolution. (Caption remains for the text answer.)

**`backend/app/services/orchestrator.py`:**
- `answer_question(...)` captures `figure_urls` from `retrieve_context` and returns them under a new key `figure_paths` in its result dict (alongside `reply`, `sparql_query`, `sources`).

**`backend/app/routers/chat.py`:**
- Merge `result["figure_paths"]` (from SPARQL results) with the existing `extract_figure_paths_from_reply(reply)` output, de-duplicated, preserving order, and pass to `ChatResponse.figure_paths`.

**Frontend:** no change — `appendMessage` already renders `figure_paths` as an image gallery.

### Feature 2 — inline graph in the badge (frontend only)

**`frontend/app.js`:**
- Refactor: extract the body of `renderGraph(columns, rows)` (node/edge building + `vis.Network` creation) into `renderGraphInto(container, columns, rows)`. The existing overlay path calls `renderGraphInto(graphContainer, ...)`; behavior unchanged.
- `appendSparqlBadge(query)` gains a second control next to the existing Show/Hide: **"Show graph" / "Hide graph"**. The badge contains a hidden inline graph container (`.sparql-graph`, ~300px tall).
  - First "Show graph" click: POST `query` to `/api/chat/sparql`, then `renderGraphInto(thatContainer, columns, rows)`; reveal the container. A small "Loading…/error" line covers fetch failures.
  - Subsequent clicks toggle the container's visibility only (no re-fetch; track a `rendered` flag).

**`frontend/styles.css`:** styles for `.sparql-graph` (fixed small height, border, hidden state) and the graph toggle button, matching the existing badge styling.

## Data flow

```
answer_question
  ├─ retrieve_context -> (sparql_context, sparql, figure_urls)   # figure_urls from result names
  └─ returns {reply, sparql_query, sources, figure_paths=figure_urls}
        │
   chat.py merges figure_paths + reply-text scan (dedup) -> ChatResponse.figure_paths
        │
   frontend: appendMessage renders the image gallery (existing)
             appendSparqlBadge renders query text + lazy inline mini-graph (new)
```

## Error handling

- `figures.py`: missing `FIGURES_DIR` → empty manifest → no figure URLs (no crash). Non-string/None values skipped.
- Inline graph fetch failure → show a short error line inside the badge; do not break the message.
- A query that returns no figure names → `figure_paths` empty → gallery simply not rendered (unchanged behavior).

## Testing

- Backend: a script issues a known figure query (e.g. figures in Bài 1, Topic A, Lớp 11) through `answer_question` and asserts `figure_paths` contains `/figures/g11_topicA_fig_l1_*.png` URLs that exist on disk; and a non-figure question yields empty `figure_paths`.
- `figures.figure_url_for_value` unit checks: a figure URI, a bare name, and a non-figure value.
- Frontend: manual — ask a figure question, confirm thumbnails appear in the answer; click "Show graph" on the badge, confirm an inline graph renders and toggles. (`node --check frontend/app.js` for syntax.)

## Follow-ups (out of scope)

- Caching `/api/chat/sparql` results client-side across badges.
- Pagination/cap for very large figure result sets (current queries `LIMIT` already bound this).
