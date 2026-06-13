# Design: Targeted RAG Accuracy Fixes

**Date:** 2026-06-13
**Status:** Approved (design), pending implementation plan
**Scope:** Targeted fixes inside the existing `OntotextGraphDBQAChain` pipeline. No architecture change.

## Problem

The chatbot answers most questions with *"I cannot find the requested info."* Investigation of the
running GraphDB repository (`Tin-hoc-canh-dieu`, port 7200) and the LangChain code identified the
root causes — empty SPARQL results, not bad answer generation.

### Confirmed root causes

1. **The "schema" fed to the LLM is the entire graph.**
   `graphdb_service.py` loads the ontology with `CONSTRUCT {?s ?p ?o} WHERE {?s ?p ?o}`, which returns
   **34,049 triples** (all instance data + Vietnamese text). The real ontology (TBox) is only **361
   triples** (46 classes, 38 object properties, 24 datatype properties, with domains/ranges/labels).
   The LLM drowns in instance noise and never sees a clean schema, so it generates SPARQL against a
   guessed structure → empty results.

2. **Conversation history pollutes SPARQL generation.**
   `chat.py` prepends the full `Previous conversation: User:… Assistant:…` blob into `query`, and the
   chain turns that entire blob into SPARQL. This badly degrades query generation.

3. **No Vietnamese label-matching guidance.**
   Data labels and text are Vietnamese (`"Thông tin"`, `"Thuật toán"`); class/property names are
   English. The generic prompt leads the LLM to exact-string matches that miss on case/diacritics.

4. **No domain few-shot examples.** The chain uses LangChain's generic SPARQL prompt with zero
   examples of this ontology.

### Verified facts about the graph

- 34,049 total triples; ontology-only TBox is ~361 triples.
- Every predicate used in the data **is declared** as an `owl:ObjectProperty`/`owl:DatatypeProperty`,
  and properties carry `rdfs:domain` / `rdfs:range`. An ontology-only schema is therefore both clean
  and complete.
- `KnowledgeConcept` instances have `rdfs:label` (Vietnamese) + `hasDefinitionText`.
- `Paragraph` instances have `hasRawText` + `mentionsConcept`; figures via `illustratesConcept`.
- The installed `langchain_community` 0.4.1 `OntotextGraphDBQAChain.from_llm` accepts custom
  `sparql_generation_prompt`, `sparql_fix_prompt`, and `qa_prompt`.

## Goals

- Dramatically reduce empty/"cannot find" answers for questions the graph can answer.
- Keep the existing chain and stack (FastAPI + `OntotextGraphDBQAChain` + GPT-4.1-mini).
- Make the improvement measurable with an eval harness.

## Non-goals

- Vector/hybrid retrieval (deferred — separate future scope).
- Replacing the chain with a custom agent.
- Changing the knowledge graph itself.

## Design

### Fix 1 — Ontology-only schema (`backend/app/services/graphdb_service.py`)

Replace the all-triples CONSTRUCT with a TBox-only query that includes explicit prefixes (the
langchain endpoint does not assume `owl:`/`rdfs:`/`rdf:`):

```sparql
PREFIX owl:  <http://www.w3.org/2002/07/owl#>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
CONSTRUCT { ?s ?p ?o } WHERE {
  ?s ?p ?o . ?s a ?t .
  FILTER(?t IN (owl:Class, rdfs:Class, owl:ObjectProperty, owl:DatatypeProperty,
                rdf:Property, owl:TransitiveProperty, owl:SymmetricProperty, owl:Ontology))
}
```

This yields ~361 triples (classes, properties, domains, ranges, labels, subClassOf). The existing
`get_schema` log line will confirm the smaller, clean schema.

### Fix 2 — Keep conversation history out of SPARQL generation (`backend/app/routers/chat.py`)

- Pass **only the current question** to `qa_chain.invoke`, never the history blob.
- Preserve follow-ups with a small LLM **condense step**: if there is prior history and the new
  message looks like a follow-up, rewrite it into a standalone Vietnamese question using the last few
  turns, then feed that standalone question to the chain. History never reaches the SPARQL generator
  directly.
- Condensing uses the same `ChatOpenAI` model with a dedicated prompt; it is a separate, small call.

### Fix 3 — Domain SPARQL prompt + Vietnamese matching + few-shot (`backend/app/services/chatgpt_service.py`)

Provide a custom `sparql_generation_prompt` (input vars `prompt`, `schema`) that instructs the model:

- Class/property names are English; **all labels and text content are Vietnamese**.
- Match concepts by label robustly:
  `?c rdfs:label ?l . FILTER(CONTAINS(LCASE(STR(?l)), LCASE("<term>")))` — do not guess URIs and do
  not exact-match.
- Key navigation patterns:
  - Definition of a concept: `?c a ex:KnowledgeConcept ; rdfs:label ?l ; ex:hasDefinitionText ?def`.
  - Where a concept is discussed: `?p ex:mentionsConcept ?c ; ex:hasRawText ?text`.
  - Figures illustrating a concept: `?f ex:illustratesConcept ?c`.
- Always `SELECT` human-readable labels/text (not bare URIs) and include a `LIMIT`.
- Include 3–5 few-shot examples: real Vietnamese question → correct SPARQL for this ontology.

Also provide a custom `qa_prompt` that answers **in Vietnamese**, grounded only in the query results
(keep the "say you don't know if no information" guardrail).

Few-shot examples to encode (final SPARQL validated against the live endpoint during implementation):
1. "Thông tin là gì?" → find KnowledgeConcept by label, return `hasDefinitionText`.
2. "Bài học nào nói về thuật toán?" → paragraphs `mentionsConcept` matching label → `belongsToLesson`.
3. "Có hình minh hoạ nào về …?" → `illustratesConcept` → figure caption/URI.

### Fix 4 — Eval harness (`backend/eval/run_eval.py`)

A standalone script that:
- Loads a Q/A set (path provided by the user; format detected — JSON/CSV).
- Runs each question through the chain.
- Logs per question: generated SPARQL, raw results count, final answer, and whether it was empty /
  "cannot find".
- Prints a summary: total, answered, empty, and (if expected answers are present) a simple match
  score. Used to measure before vs. after.

## Data flow (after changes)

```
User message
   │
   ├─ (if follow-up) condense with history ──▶ standalone Vietnamese question
   │
   ▼
OntotextGraphDBQAChain
   ├─ SPARQL generation  (clean ontology schema + domain prompt + few-shot)
   ├─ SPARQL fix retries
   ├─ execute against GraphDB
   └─ answer generation  (Vietnamese qa_prompt, grounded in results)
   │
   ▼
Chat response (+ SPARQL shown in UI)   ── history stored separately, used only for condensing
```

## Testing / verification

- After Fix 1: log shows ~361-triple schema, not 34k.
- After all fixes: run the eval harness; compare empty-rate and score against the pre-change baseline.
- Spot-check that few-shot example questions return non-empty, correct answers.
- Confirm multi-turn follow-ups still resolve via the condense step.

## Risks & mitigations

- **Condense step adds latency/cost.** Keep it conditional (only when history exists) and small.
- **CONTAINS matching may over-match short terms.** Acceptable for targeted scope; revisit with
  exact-then-fuzzy fallback if precision suffers.
- **Few-shot SPARQL must be valid for this endpoint.** Validate each example query live during
  implementation before embedding it.

## Additional fixes discovered during implementation

Verifying Fixes 1–3 end-to-end surfaced two more bugs that had to be fixed for the targeted work to
actually improve accuracy. Both are in `chatgpt_service.py` / `graphdb_service.py`.

### Fix 1b — Unicode NFC normalization of generated SPARQL (`graphdb_service.py`)

The GraphDB labels are stored in Unicode **NFC** (composed) form, but gpt-4.1-mini emits Vietnamese
in **NFD** (decomposed) form. SPARQL `CONTAINS`/`=` compare codepoints exactly, so an NFD term
silently matched nothing (e.g. `"thuật toán"` → 0 rows, while `"iot"` — no diacritics — worked).
Empirically verified: NFC term → 2 rows, NFD term → 0 rows on the same data.

`create_graph` now wraps `graph.query` to `unicodedata.normalize("NFC", query)` before execution, so
every generated query is normalized regardless of the model. This was *the* dominant cause of empty
results for any Vietnamese term with diacritics.

### Fix 1c — Clean result formatting + softened QA prompt (`chatgpt_service.py`)

The chain passed the raw rdflib result list to the answer step, which stringified as
`[(rdflib.term.Literal('…', lang='vi'),), …]`. The answer LLM frequently misread this noise as
"no usable data" and replied "not found" even when rows were present. `FormattedGraphDBQAChain`
overrides `_execute_query` to format rows as clean `- var: value` lines (and returns `""` only when
the result set is truly empty). The QA prompt was rewritten so the not-found branch fires **only** on
empty results; otherwise it must answer from the retrieved data even if it is only partially related.

### Fix 3b — Curriculum navigation + answer-contradiction fixes (`chatgpt_service.py`)

Two further issues surfaced from real user questions about figures in a specific lesson:

- **Vocabulary + hierarchy gap.** "các hình ảnh trong bài 1 topic A lớp 11" failed because the model
  filtered topics on `"topic a"` (label is "Chủ đề A") and used a `Page → hasFigure` path. Added to
  the SPARQL prompt: a Vietnamese vocabulary map ("topic X"→"Chủ đề X", "lớp N"→"Lớp N", "bài N"→
  "Bài N." *with the trailing period* so "Bài 1." ≠ "Bài 10."), the curriculum-hierarchy pattern
  (`Lesson belongsToGrade/belongsToTopic`, figures via `belongsToLesson`, `a ex:Figure` to exclude
  pages/sections), and a 5th few-shot example for "images in bài N / topic X / lớp Y".

- **Self-contradicting answers.** For some questions the SPARQL returned rows but the answer LLM
  listed them and *then* said "không tìm thấy". The QA prompt was rewritten: if ≥1 row exists it must
  be used — directly when it matches, or framed as "related information" when only loosely related —
  and a bare "not found" is allowed **only** when the result set is empty. No list-then-deny.

## Follow-ups (out of scope)

- Bump just the SPARQL-generation step to `gpt-4.1` if generation still struggles.
- Hybrid vector retrieval over `hasRawText`/`hasDefinitionText`/labels for semantic questions.
