# Figure/Diagram Node Images Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the matching `asset/` image inside any graph node whose URI local name equals an image filename (without extension), replacing the removed `hasFigurePath` mechanism.

**Architecture:** Backend exposes `GET /figures/manifest` (list of image filenames in `FIGURES_DIR`). Frontend lazily fetches it once, builds a `basename-without-extension → filename` map, and checks every node value in `renderGraph` against it. Old column-name-based detection (`isFigurePathCol`/`toFigureUrl`) is deleted.

**Tech Stack:** FastAPI (backend), vanilla JS + vis-network (frontend).

**Notes for the implementer:**
- This project is **not a git repository** — skip all commit steps.
- There is **no test harness** (no pytest, no JS tests). Verification is manual via the running app, per the approved spec (`docs/superpowers/specs/2026-06-04-figure-node-images-design.md`).
- Run the backend from the project root: `uvicorn backend.app.main:app --reload` (requires `.env` with GraphDB + OpenAI settings; startup fails without a reachable GraphDB).

---

### Task 1: Backend manifest endpoint

**Files:**
- Modify: `backend/app/main.py`

The `/figures/manifest` route MUST be registered **before** `app.mount("/figures", ...)`. Starlette matches in registration order; if the mount comes first, it swallows `/figures/manifest` and returns a 404 file lookup.

- [ ] **Step 1: Add the endpoint**

Replace the figures-serving block in `backend/app/main.py` (currently lines 17–23) with:

```python
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
```

Also add `import re` to the imports at the top of the file (alongside `import logging` / `import os`).

- [ ] **Step 2: Verify the endpoint**

Start the server from the project root:

```powershell
uvicorn backend.app.main:app --reload
```

Then in another terminal:

```powershell
Invoke-RestMethod http://localhost:8000/figures/manifest | Select-Object -ExpandProperty figures | Measure-Object
```

Expected: `Count : 110`. Also spot-check:

```powershell
(Invoke-RestMethod http://localhost:8000/figures/manifest).figures[0]
```

Expected: `fig_f12_string_programs.png` (sorted, so an `f...` name comes first).

Confirm static serving still works: open `http://localhost:8000/figures/fig_qrCode.png` in a browser → the image loads.

---

### Task 2: Frontend manifest loader + lookup helper

**Files:**
- Modify: `frontend/app.js` (replace `isFigurePathCol` + `toFigureUrl`, currently lines 294–308)

- [ ] **Step 1: Replace the old helpers**

Delete `isFigurePathCol()` and `toFigureUrl()` (the block from the comment `// Check if a column name refers to a figure path` through the end of `toFigureUrl`) and put this in their place:

```js
// ── Figure manifest: basename-without-extension → filename ──
let figureManifest = null;

async function loadFigureManifest() {
  if (figureManifest) return figureManifest;
  figureManifest = new Map();
  try {
    const res = await fetch("/figures/manifest");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    for (const filename of data.figures || []) {
      const base = filename.replace(/\.[^.]+$/, "");
      figureManifest.set(base, filename);
    }
  } catch (err) {
    console.warn("Could not load figure manifest:", err);
  }
  return figureManifest;
}

// If a URI's local name matches an image in the assets folder,
// return its serveable URL; otherwise null.
function figureUrlForValue(value) {
  if (!value || !figureManifest) return null;
  const filename = figureManifest.get(localName(value));
  return filename ? `/figures/${encodeURIComponent(filename)}` : null;
}
```

(`localName()` already exists directly below this block — it stays.)

- [ ] **Step 2: Syntax check**

```powershell
node --check frontend/app.js
```

Expected: no output (exit code 0).

---

### Task 3: Wire lookup into renderGraph (both modes, subjects included)

**Files:**
- Modify: `frontend/app.js` — `renderGraph()` and its call site

- [ ] **Step 1: Make renderGraph await the manifest**

Change the function signature and add the manifest load as the first statement:

```js
// Build vis-network graph from SPARQL results
async function renderGraph(columns, rows) {
  await loadFigureManifest();
  graphError.classList.add("hidden");
  ...
```

Update the call site in the SPARQL run handler (the handler is already `async`):

```js
    await renderGraph(data.columns, data.rows);
```

(Using `await` keeps errors inside the handler's existing `try/catch`.)

- [ ] **Step 2: Update the triple-pattern branch**

Replace the loop body of the `isTriplePattern` branch with:

```js
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
```

(The only changes: subject nodes also get the figure check, and `figureUrl` now comes from `figureUrlForValue(objectUri)` instead of `isFigurePathCol(predName) ? toFigureUrl(objectUri) : null`.)

- [ ] **Step 3: Update the tabular branch**

In the tabular branch:

a) Subject node creation becomes:

```js
      if (!nodesMap.has(subjectId)) {
        const subjFigureUrl = figureUrlForValue(subjectUri);
        nodesMap.set(subjectId, {
          label: localName(subjectUri),
          type: subjFigureUrl ? "image" : "subject",
          imageUrl: subjFigureUrl,
        });
      }
```

b) The value-node figure check changes from

```js
        // Check if this is a figurePath column → make it an image node
        const figureUrl = isFigurePathCol(colName) ? toFigureUrl(value) : null;
```

to

```js
        // Figure/Diagram instance → make it an image node
        const figureUrl = figureUrlForValue(value);
```

Everything else in `renderGraph` (image-node styling, colors, vis options) stays unchanged.

- [ ] **Step 4: Confirm no stale references**

```powershell
node --check frontend/app.js
```

Expected: exit 0. Then search for leftovers:

```
grep -n "isFigurePathCol\|toFigureUrl" frontend/app.js
```

Expected: no matches.

---

### Task 4: Manual end-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Start the app**

```powershell
uvicorn backend.app.main:app --reload
```

Open `http://localhost:8000`, open DevTools console.

- [ ] **Step 2: Figure as object**

In the SPARQL editor run a triple-pattern query that returns Figure instances as objects, e.g.:

```sparql
SELECT ?s ?p ?o WHERE {
  ?s ?p ?o .
  FILTER(isIRI(?o) && STRENDS(STR(?o), "fig_qrCode"))
} LIMIT 20
```

Expected: the `fig_qrCode` node renders as an image thumbnail (green border, label below); the network request `GET /figures/manifest` appears once with status 200.

- [ ] **Step 3: Figure as subject**

```sparql
SELECT ?s ?p ?o WHERE {
  ?s ?p ?o .
  FILTER(isIRI(?s) && CONTAINS(STR(?s), "fig_"))
} LIMIT 20
```

Expected: subject nodes whose local names match asset files render as images.

- [ ] **Step 4: Non-figure query unaffected**

Run any query returning no figure URIs (e.g. `SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10` on non-figure data). Expected: plain dots/boxes, no broken-image icons, no console errors.

- [ ] **Step 5: Manifest failure fallback**

Stop the server, rename `asset/` to `asset_bak/`, restart, run a query. Expected: manifest returns `{"figures": []}` with HTTP 200 (no console warning — the warning path only fires on fetch/HTTP errors); graph still renders with plain nodes and no broken images. Rename the folder back and restart.
