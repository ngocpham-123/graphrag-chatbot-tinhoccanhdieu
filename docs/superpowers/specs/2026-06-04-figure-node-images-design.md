# Figure/Diagram Node Images in Graph View — Design

**Date:** 2026-06-04
**Status:** Approved (Approach A)

## Background

The ontology schema changed: the `hasFigurePath` data property no longer exists.
Instead, instances of `ex:Figure` / `ex:Diagram` have a URI whose **local name
(without extension) exactly matches an image filename** in the assets folder.

Example: `ex:g11_topicA_fig_l1_cpu` ↔ `asset/g11_topicA_fig_l1_cpu.png`.

All 110 current assets are `.png`, but the design must not hardcode the extension.

## Goal

When a SPARQL query result (graph view) contains such an object — in any column,
subject or value — the corresponding image is rendered inside that node
(vis-network `shape: "image"`), replacing the old `figurePath`-column detection.

## Approach (A — frontend manifest)

The SPARQL endpoint returns flat strings with no `rdf:type` info, so the frontend
matches URI local names against the actual files on disk via a manifest.

### Backend

- New endpoint `GET /figures/manifest` in `backend/app/main.py` (next to the
  existing `/figures` static mount, registered **before** it) returning
  `{"figures": ["fig_qrCode.png", ...]}`.
- Implementation: list `FIGURES_DIR` for files with image extensions
  (`png|jpe?g|gif|svg|webp`). If the directory is missing, return an empty list.
- The `/api/chat/sparql` endpoint is **not** modified.

### Frontend (`frontend/app.js`)

- `loadFigureManifest()` — fetches the manifest **lazily on first graph render**,
  caches a module-level `Map<string, string>` keyed by basename-without-extension
  → full filename (e.g. `fig_qrCode` → `fig_qrCode.png`). Subsequent renders
  reuse the cache. Fetch failure: log to console, proceed with an empty map.
- New `figureUrlForValue(value)`:
  1. `localName(value)` (existing helper — strips `#`/`/` prefix),
  2. look up in the manifest map,
  3. return `/figures/<filename>` or `null`.
- Applied to **every node** in both render modes:
  - Triple mode (`s/p/o`): subjects **and** objects.
  - Tabular mode: the subject column **and** all property-value nodes.
- A matched node gets `type: "image"` + `imageUrl`, rendered with the existing
  image-node styling (`shape: "image"`, size 50, green border) — unchanged.

### Removals

- `isFigurePathCol()` and `toFigureUrl()` in `frontend/app.js` are deleted, along
  with their call sites (`renderGraph` triple + tabular branches). No other code
  references them.
- The chat-reply figure gallery (`extract_figure_paths_from_reply` in
  `chat.py`, `appendMessage` gallery in `app.js`) is **out of scope** — untouched.

## Data flow

```
first graph render → GET /figures/manifest → Map(basename → filename)
renderGraph(columns, rows)
  └─ for each node value: figureUrlForValue(value)
       └─ match → { type: "image", imageUrl: "/figures/<filename>" }
       └─ no match → plain node (dot/box) exactly as today
```

## Error handling

- Manifest fetch fails → console warning, graph renders without images.
- Local name not in manifest → normal node, no broken-image attempt.
- `renderGraph` becomes async only insofar as it awaits the cached manifest load.

## Testing

Manual verification (no test harness exists in this project):

1. Run a SPARQL query returning a Figure/Diagram URI as an object
   (e.g. triple-pattern query where `?o` is `ex:fig_qrCode`) → node shows the
   image thumbnail.
2. Run a query where the Figure URI is the **subject** → subject node shows the image.
3. Run a query with no figure URIs → all nodes render as plain dots/boxes.
4. Stop figure serving (rename `asset/` temporarily) → manifest empty, graph
   still renders, console warning only.
