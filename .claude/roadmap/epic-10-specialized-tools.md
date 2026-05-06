# E10 — Specialized Tools (Tier 4)

**Epic dependencies:** E08, E09.

**Goal:** add the math-pipeline-specific tools that turn arXMCP from a generic retrieval system into something useful for the autoformalizer/tactician/fixer roles. Five tools: `get_definitions`, `find_lemma_by_name`, `find_equation`, `paper_diff`, `expand_macro`. Each tool respects the determinism contract from E07 and the cache layers from E08.

**Effort:** ~2 weeks.

**References:** `06-mcp-server-design.md` § Tool surface (each of the five tools); `04-parsing-and-chunking.md` § Equation atom record; `05-storage-and-indexing.md` § definitions, theorem_names, equations tables.

---

### E10_S01 — `get_definitions` tool implementation

**Description.** Per `06-mcp-server-design.md` § get_definitions — answers "what does `\AA` mean in this paper?" Reads from the `definitions` table populated in E03_S06 / E05. Critical for the autoformalizer and tactician sub-agents.

**Acceptance criteria.**
- [ ] Tool schema matches `06-mcp-server-design.md` exactly: `{paper_id, symbol (optional)}`.
- [ ] If `symbol` is omitted, returns the full notation table for the paper.
- [ ] If `symbol` is provided, returns matching entries (exact match on `symbol_raw` or `symbol`).
- [ ] Each entry includes `symbol`, `symbol_raw`, `expansion`, `defining_chunk_id`, `scope`.
- [ ] Result is sorted by `symbol_raw` ascending for determinism.
- [ ] Test: a paper with 8 author macros returns 8 entries.
- [ ] Test: filter by `\AA` returns only the matching entry.
- [ ] Cached at Tier 1 keyed on `(paper_id, symbol)`.

**Dependencies.** E07_S02, E05_S10, E08_S01.

**Complexity.** S.

**Labels.** `area:server`, `kind:feature`.

---

### E10_S02 — Theorem-name extraction and `theorem_names` population

**Description.** Per `05-storage-and-indexing.md` § Table: theorem_names — Mathlib-style exact-match index on canonical theorem names ("Yoneda lemma", "Riemann-Roch"). Build a heuristic extractor that scans theorem chunks for "named" theorems and populates the table with a confidence score.

**Acceptance criteria.**
- [ ] `ingest/extract/theorem_names.py::extract(chunks) -> list[TheoremNameRecord]`.
- [ ] Heuristics: theorem environment titled `\begin{theorem}[Yoneda lemma]`, or "the Yoneda lemma" appearing in close proximity to a theorem environment, or named-theorem dictionary match.
- [ ] Confidence scoring: explicit title = 1.0, dictionary match in body = 0.7, fuzzy = 0.5.
- [ ] Records written to LanceDB `theorem_names` table.
- [ ] Test: a paper with `\begin{theorem}[Riemann-Roch]` produces a record with confidence 1.0.
- [ ] Re-runnable; idempotent on existing records.

**Dependencies.** E04_S08, E05_S02.

**Complexity.** L.

**Labels.** `area:parser`, `area:storage`, `kind:feature`.

---

### E10_S03 — `find_lemma_by_name` tool with fuzzy search

**Description.** Per `06-mcp-server-design.md` § find_lemma_by_name — exact and fuzzy match on canonical theorem names. Backed by FTS5 / Tantivy trigram index on the `theorem_names` table. Critical for the tactician (mathlib-style lookups).

**Acceptance criteria.**
- [ ] Tool schema matches the note: `{name, fuzzy (default true)}`.
- [ ] Exact match path: case-insensitive equality on canonical name.
- [ ] Fuzzy match path: trigram-similarity over `name`; returns top-10 by score.
- [ ] Each result includes `name`, `paper_id`, `chunk_id`, `confidence` (from extraction) plus a search-time match-score.
- [ ] Test: query "Yoneda lemma" exact-matches at least one hit when present.
- [ ] Test: query "Yoneda lema" (typo) fuzzy-matches when fuzzy=true.
- [ ] Result canonicalized per the determinism contract.

**Dependencies.** E10_S02, E07_S02.

**Complexity.** M.

**Labels.** `area:server`, `area:retrieval`, `kind:feature`.

---

### E10_S04 — Equation tree-edit-distance similarity

**Description.** Per `06-mcp-server-design.md` § find_equation — equation similarity uses MathML tree-edit-distance plus a dense embedding fusion. Implement a tree-edit-distance scorer over MathML ASTs (Zhang-Shasha algorithm) and combine with the dense embedding (built in E05) via RRF.

**Acceptance criteria.**
- [ ] `server/retrieval/equation_ted.py::ted(mathml_a, mathml_b) -> float`.
- [ ] Implementation uses Zhang-Shasha or APTED; pinned dependency.
- [ ] Normalized score: `1.0 - (edit_distance / max_tree_size)`.
- [ ] Performance: <50 ms for 100 candidate comparisons on typical-size equations.
- [ ] Test: identical MathML returns 1.0.
- [ ] Test: structurally equivalent equations with different variable names return >0.7.
- [ ] Test: completely unrelated equations return <0.3.

**Dependencies.** E04_S03.

**Complexity.** L.

**Labels.** `area:retrieval`, `kind:feature`.

---

### E10_S05 — `find_equation` tool implementation

**Description.** Per `06-mcp-server-design.md` § find_equation — query by LaTeX, parse to MathML, fuse dense embedding similarity with tree-edit-distance. Return equation atoms with parent chunk IDs ranked by combined score.

**Acceptance criteria.**
- [ ] Tool schema matches the note: `{latex, k, filters}`.
- [ ] Implementation: parse the query LaTeX to MathML (use the same LaTeXML or a lighter pipeline like KaTeX); embed `presentation_latex + context_sentence`; fuse with TED via RRF; return top-k.
- [ ] Each result includes `equation_id`, `paper_id`, `label`, `presentation_latex`, `parent_chunk_id`, fused score.
- [ ] Test: query for an equation present verbatim in the corpus returns it as the top hit.
- [ ] Test: structurally similar equation (alpha-renamed variables) ranks in top-5.
- [ ] Result canonicalized per determinism contract.

**Dependencies.** E10_S04, E05_S03.

**Complexity.** L.

**Labels.** `area:server`, `area:retrieval`, `kind:feature`.

---

### E10_S06 — `paper_diff` tool implementation

**Description.** Per `06-mcp-server-design.md` § paper_diff — compare two versions of the same paper at the requested scope (`abstract | theorems | full`). Autoformalizers care: v1 often has the cleaner statement, v3 has the corrected proof.

**Acceptance criteria.**
- [ ] Tool schema matches the note: `{paper_id, from_version, to_version, scope (default "theorems")}`.
- [ ] For `scope="abstract"`: diff abstracts at chunk level.
- [ ] For `scope="theorems"`: align theorems by label across versions; diff each pair; report added/removed/modified theorems.
- [ ] For `scope="full"`: diff section-level chunks aligned by section path.
- [ ] Diff output is a stable structure with `{added: [...], removed: [...], modified: [{from_chunk, to_chunk, unified_diff}]}`.
- [ ] Test: a paper with v1 and v2 differing in one theorem returns exactly one modified entry.
- [ ] Test: requesting a version that doesn't exist returns a clear error.
- [ ] Result canonicalized per determinism contract.

**Dependencies.** E07_S02, E05_S10.

**Complexity.** L.

**Labels.** `area:server`, `area:retrieval`, `kind:feature`.

---

### E10_S07 — Multi-version chunk storage support

**Description.** `paper_diff` requires that we store chunks for multiple versions of the same paper. Today, ingestion may overwrite older versions. Add a `version` field to the LanceDB primary key and ensure the ingestion pipeline writes one row per `(paper_id, version, chunk_id)`.

**Acceptance criteria.**
- [ ] LanceDB `chunks` table primary key extended to `(chunk_id)` (already content-addressable, but must be globally unique across versions; verify via the determinism property of chunk IDs).
- [ ] `version` column populated correctly during ingestion.
- [ ] Querying for a specific version filters by `version = N`.
- [ ] Test: a paper with v1 and v2 has both versions queryable; both versions of a theorem chunk produce distinct chunk IDs.
- [ ] Default for `search_papers` is the latest version (filter `version = papers.latest_version`).

**Dependencies.** E04_S06, E05_S01.

**Complexity.** M.

**Labels.** `area:storage`.

---

### E10_S08 — `expand_macro` utility tool

**Description.** Per `06-mcp-server-design.md` § expand_macro — small utility for the autoformalizer. Given `(paper_id, macro)`, returns the canonical expansion. Backed by the notation table from E03_S06.

**Acceptance criteria.**
- [ ] Tool schema matches the note: `{paper_id, macro}`.
- [ ] Returns `{macro, canonical_form, defining_chunk_id, scope}` or an error if not defined.
- [ ] Test: `expand_macro("2401.01234", "\\AA")` returns `"\\mathcal{A}"` if defined.
- [ ] Test: unknown macro returns a structured "not defined" response (not an error).
- [ ] Cached at Tier 1.

**Dependencies.** E03_S06, E07_S02.

**Complexity.** S.

**Labels.** `area:server`, `kind:feature`.

---

### E10_S09 — Update server's tool-list and byte-stable hash

**Description.** Adding five new tools requires re-running the byte-stability hash test from E07_S02. Update the expected hash constant deliberately and document the bump.

**Acceptance criteria.**
- [ ] All five new tools registered in `server/tools/definitions.py` with frozen schemas.
- [ ] `EXPECTED_TOOL_SCHEMA_HASH` constant bumped; PR description explains the addition.
- [ ] `tool_schema_version` constant incremented.
- [ ] Documented version bump in `docs/server/tool-stability.md` changelog.

**Dependencies.** E10_S01, E10_S03, E10_S05, E10_S06, E10_S08.

**Complexity.** S.

**Labels.** `area:server`, `area:cache`, `kind:infra`.

---

### E10_S10 — Tactician-loop validation on the seed corpus

**Description.** Per the Tier 4 exit criterion in `09-feature-priorities.md` — "the tactician sub-agent uses at least 3 of these tools during a single proof attempt and produces a better proof draft than without them." Manual / semi-manual validation that the tools are useful in practice.

**Acceptance criteria.**
- [ ] Hand-run a tactician scenario: pick one paper from the seed, simulate "find a lemma that proves <statement>" using `find_lemma_by_name`, `find_equation`, and `get_definitions` together.
- [ ] Document the session in `docs/tier-4-tactician-demo.md` showing the three tool calls and the resulting proof draft.
- [ ] Run the same scenario without arXMCP tools and contrast.
- [ ] Subjective judgment: the arXMCP-augmented draft should be qualitatively better (more grounded, fewer hallucinated lemma names).

**Dependencies.** E10_S01, E10_S03, E10_S05, E10_S08.

**Complexity.** M.

**Labels.** `area:retrieval`, `kind:research`.

---

### E10_S11 — Backfill `theorem_names` and `definitions` for the seed corpus

**Description.** Run the new extractors over the 50-paper seed and populate the `theorem_names` and `definitions` tables. Confirms the tools work end-to-end on real data.

**Acceptance criteria.**
- [ ] After backfill: `theorem_names` table has ≥10 entries with confidence ≥0.7.
- [ ] `definitions` table has ≥200 entries (avg 4+ per paper).
- [ ] `find_lemma_by_name("Riemann-Roch", fuzzy=true)` and similar canonical-name queries return non-empty.
- [ ] Stats summary in `var/arxmcp/ops/seed-tier-4-stats.json`.

**Dependencies.** E10_S02, E03_S06.

**Complexity.** S.

**Labels.** `area:parser`, `kind:research`.

---
