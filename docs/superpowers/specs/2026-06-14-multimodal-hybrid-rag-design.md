# Design: Multimodal Hybrid RAG

**Date:** 2026-06-14
**Status:** Approved (design), pending implementation plan
**Builds on:** `2026-06-13-rag-accuracy-targeted-fixes-design.md` (Text-to-SPARQL is now reliable).

## Problem

The current system is pure Text-to-SPARQL. It answers structured questions well (definitions by
label, navigation, "images in bài 1"), but fails when a question cannot be turned into a label
substring match: paraphrases, synonyms, broad conceptual questions, and concepts that have no
`hasDefinitionText` node (e.g. "thông tin là gì" — the concept exists but has no definition triple).
There is also no way to ask about an **image**.

## Goals

1. **Improve conceptual / paraphrased questions** by adding semantic (vector) retrieval over the
   graph's text literals, run alongside SPARQL.
2. **Accept an image as input**: a vision model reads the image, and the system retrieves related
   graph content and answers ("understand & answer", not image-similarity lookup).
3. Keep structured SPARQL questions working exactly as they do now.
4. Keep the improvement measurable (extend the eval harness: SPARQL-only vs hybrid).

## Non-goals

- Image-to-image similarity search over `asset/` figures (not requested).
- OCR-only path (the vision "understand & answer" path subsumes simple text-in-image cases).
- GraphDB-native vectors (using a separate Chroma index instead — see Decisions).
- Replacing the existing SPARQL chain (it is reused as one retriever).

## Decisions (with rationale)

- **Vector store: local Chroma (separate), not GraphDB-native.** Retrieval quality is identical
  (same OpenAI vectors, cosine similarity); Chroma is one line to build/rebuild in LangChain, easy to
  inspect, and supports metadata filters (lesson/topic/concept) so we still get structured+semantic
  hybrid without GraphDB-side setup.
- **Routing: deterministic for images, run-both-and-merge for text.** Image attached → always the
  vision path (no classifier needed). For text, run SPARQL **and** vector retrieval and merge all
  evidence into the answer context — this avoids a router's main failure mode (misrouting a
  conceptual question to SPARQL and getting nothing). Which path contributed is logged for evaluation.
- **Embeddings: OpenAI `text-embedding-3-large`** — zero infra, handles Vietnamese acceptably, reuses
  the existing OpenAI key.
- **Vision + answer model: `gpt-4.1-mini`** — supports image input, cheap, consistent with the
  current answer model.

## Phasing

Two independently-shippable phases, each its own implementation cycle:

- **Phase 1 — Hybrid text retrieval** (conceptual questions). The core accuracy win. No image.
- **Phase 2 — Image input** (vision service + API/schema + frontend upload). Builds on Phase 1.

## Architecture

```
Request (text [+ image])
   │
   ├─ image attached?  ──► [P2] Vision service (gpt-4.1-mini vision): image + text
   │                         -> Vietnamese text query describing intent
   ▼                                     │
   └──────────────► text query ◄─────────┘
                        │
         ┌──────────────┴───────────────┐
         ▼                              ▼
   SPARQL retrieval              Vector retrieval
   (existing chain ->            (Chroma top-k over text
    structured rows)              literals + metadata)
         └──────────────┬───────────────┘
                        ▼
        Merge evidence (labeled sections + citations)
                        ▼
        Answer LLM (Vietnamese, grounded) -> answer + sources
```

## Components

Each is small, single-purpose, and independently testable.

### 1. Vector index builder — `backend/app/services/vector_index.py` + `backend/scripts/build_index.py`
- A SPARQL query extracts every text literal as a document with metadata:
  - text sources: `ex:hasRawText` (~1105), `ex:hasDefinitionText` (109), `ex:hasCaption` (453),
    `rdfs:label` (2467) → ~4,000 docs.
  - metadata per doc: `uri`, `source_property`, node `type`, and (where reachable) `lesson`, `topic`,
    `grade`, `concept` — for citations and optional filtering.
- Embed with `text-embedding-3-large`; persist a Chroma collection to `backend/data/chroma/`.
- One-time build (a few cents), re-runnable via the script. The build script is the only writer; the
  app only reads.

### 2. Vector retriever — part of `vector_index.py`
- `similarity_search(query, k)` returning passages + metadata. Optional metadata filter for the
  later "semantic within lesson X" story.

### 3. Graph retriever — reuse existing `FormattedGraphDBQAChain`
- Generate + execute SPARQL and return the formatted structured rows (the work already done in the
  targeted-fixes round). Exposed so the orchestrator can get the rows as evidence rather than a final
  answer.

### 4. Vision service — `backend/app/services/vision_service.py` *(Phase 2)*
- Input: image (base64 or uploaded bytes) + the user's text.
- Calls `gpt-4.1-mini` with the image → a Vietnamese description/standalone query capturing what the
  user wants to know about the image.
- On failure: log and fall back to text-only (no image context).

### 5. Orchestrator — `backend/app/services/orchestrator.py`
- Steps: (a) *(P2)* if image, run vision → text query; (b) run SPARQL and vector retrieval
  concurrently; (c) merge into one context with labeled sections; (d) call the Vietnamese answer LLM.
- Logs which sources returned evidence (for the thesis evaluation).

### 6. API / schema / frontend
- `backend/app/models/schemas.py`: `ChatRequest` gains an optional `image` field *(Phase 2)*.
- `backend/app/routers/chat.py`: endpoint delegates to the orchestrator; conversation history /
  condensing behaviour from the previous round is preserved (history stays out of SPARQL/vector
  query text except via condensing).
- `frontend/`: image-upload control *(Phase 2)*.

## Data flow / merging

The answer prompt receives up to three labeled blocks and synthesizes one grounded Vietnamese answer,
citing lesson/page where present:
- `Kết quả truy vấn (SPARQL)` — structured rows.
- `Đoạn văn liên quan (ngữ nghĩa)` — top-k vector passages with source.
- `Mô tả hình ảnh` *(Phase 2)* — the vision description.

The existing answer rules carry over: use evidence even if only partially related, never contradict
(no list-then-deny), and say "không tìm thấy" only when **all** sources are empty.

## Error handling

- Embedding / vision / SPARQL failure → skip that source, log a warning, continue with the others.
- Missing/empty Chroma index at startup → clear error naming the build command
  (`python backend/scripts/build_index.py`).
- All sources empty → the existing honest "not found".

## Testing

- Extend `backend/eval/` to compare **SPARQL-only vs hybrid** on a set of conceptual questions
  (primary thesis metric: answered-rate / quality on conceptual queries).
- Manual smoke tests: conceptual questions in Phase 1; one image question in Phase 2.
- No automated test harness exists in this repo; verification is via the eval script and the running
  app, consistent with prior rounds.

## Open follow-ups (out of scope)

- GraphDB-native vectors if a single-query structured+semantic join is later wanted.
- Image-similarity lookup against `asset/` figures.
- Upgrading vision/answer model to `gpt-4.1` if `mini` quality is insufficient.
