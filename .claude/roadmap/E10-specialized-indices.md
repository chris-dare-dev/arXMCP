# E10 — Specialized Indices

Epic dependencies: E06 (MCP server with 7 tools shipped), E03 (macro normalizer shipped, `embedding_eq` column reserved in LanceDB schema), E02 (preamble extractor shipped)

Goal: Implement the three specialized indices that power the `get_definitions`, `find_lemma_by_name`, and `find_equation` tools, and add a LaTeXML version drift detector that guards the equation index against silent corruption when the LaTeXML container image is updated.

Effort: M + M + L + S = XL total

References: `.claude/notes/05-storage-and-indexing.md` lines 62–107, `.claude/notes/04-parsing-and-chunking.md` (equation atom design)

---

### E10_S01 — Definitions index and get_definitions tool

**Status:** NEW
**Tier:** 4
**Effort:** M
**Dependencies:** E02_S02, E06_S03

**Description.** Build the per-paper notation/definition table that backs `get_definitions(paper_id, term?)` and absorbs the former `expand_macro` tool. The index is populated during ingestion from two sources: (1) `\newcommand`, `\renewcommand`, and `\DeclareMathOperator` declarations extracted by Sonnet A's E02_S02 preamble extractor, and (2) explicit definition environments (`\begin{definition}`, `\begin{notation}`) identified by the chunker. Each entry in the `definitions` LanceDB table captures: `definition_id` (content-addressable), `paper_id`, `symbol` (canonical form, e.g., `\mathcal{A}`), `symbol_raw` (author's form, e.g., `\AA`), `expansion` (human-readable text), `defining_chunk_id`, and `scope` (`paper`, `section`, or `theorem`).

The `get_definitions` handler in `server/handlers/definitions.py` implements two modes of operation. Without the `term` argument: return the full notation table for the paper, sorted by `symbol` ascending, paginated at 100 entries per page with a `next_cursor` field. With the `term` argument: perform an exact match on `symbol` first, then `symbol_raw`, and if neither matches, fall back to case-insensitive prefix match. This absorbs the `expand_macro` tool completely — the autoformalizer can resolve any macro by calling `get_definitions(paper_id="...", term="\\AA")`.

The definitions index is populated as a streaming step after the chunker completes for each paper. It is idempotent: re-running for a paper that already has entries replaces them (keyed by `paper_id`). A paper with no preamble declarations produces zero entries (not an error). The LanceDB `definitions` table has B-tree indexes on `(paper_id, symbol)` and on `symbol_raw`, as specified in `.claude/notes/05-storage-and-indexing.md` lines 83–94.

**Deliverables.**
- `ingest/index_definitions.py` — streaming indexer: reads chunker output, extracts preamble declarations, writes to `definitions` table
- `server/handlers/definitions.py` — two-mode handler: full-table mode and term-lookup mode
- `tests/test_definitions_index.py` — ingestion test: a paper with known `\newcommand` declarations produces the correct entries; term lookup finds the right expansion

**Acceptance criteria.**
- [ ] `get_definitions(paper_id="2401.01234")` returns a paginated list of all notation entries for that paper
- [ ] `get_definitions(paper_id="2401.01234", term="\\mathcal{A}")` returns the expansion of `\mathcal{A}` from that paper's preamble
- [ ] A paper with no `\newcommand` declarations produces an empty list (not a 404 or error)
- [ ] The definitions table B-tree index on `(paper_id, symbol)` is present after ingestion
- [ ] `pytest tests/test_definitions_index.py` passes

**Out of scope.** Cross-paper symbol disambiguation. Semantic expansion of definition text. Runtime preamble parsing (index is built at ingest time, not on demand).

**Risk notes.**
- The `expand_macro` tool is absorbed here, eliminating a redundant 8th tool entry and keeping the surface at exactly 7. Autoformalizers historically needed a separate `expand_macro` call; `get_definitions(term=...)` subsumes it with a richer response.

**Labels.** `area:index`, `kind:feature`, `tier:4`

---

### E10_S02 — Theorem-name index and find_lemma_by_name tool

**Status:** NEW
**Tier:** 4
**Effort:** M
**Dependencies:** E04_S01, E06_S03

**Description.** Build the theorem-name exact-match and fuzzy-match index that backs `find_lemma_by_name(name, paper_id?)`. The core problem is deduplication: theorem names like "Lemma 3.4" appear in hundreds of papers and must not be conflated. The dedup key is the triple `(paper_id, theorem_name, section_path)`. Additionally, many theorems have canonical names ("Yoneda lemma", "Riemann-Roch theorem") that differ from their numbered labels within specific papers — the index must support lookup by canonical name across all papers.

The `theorem_names` SQLite FTS5 table (separate from LanceDB for its strong full-text indexing) has the following schema:

```sql
CREATE VIRTUAL TABLE theorem_names_fts USING fts5(
    normalized_name,    -- lowercase, punctuation-stripped, e.g. "yoneda lemma"
    display_name,       -- original form, e.g. "Yoneda Lemma"
    paper_id,
    chunk_id,
    section_path,       -- JSON array
    confidence,         -- float: how sure we are this is a named theorem
    content=''          -- external content table for size
);
CREATE TABLE theorem_names (
    dedup_key TEXT PRIMARY KEY,  -- sha256(paper_id + theorem_name + section_path_json)
    normalized_name TEXT,
    display_name TEXT,
    paper_id TEXT,
    chunk_id TEXT,
    section_path TEXT,
    confidence REAL
);
```

The `dedup_key` is a SHA-256 hash of the concatenation of `paper_id`, `theorem_name`, and `section_path` JSON. This ensures that "Lemma 3.4" in paper A and "Lemma 3.4" in paper B have different dedup keys and are stored as separate entries. A `normalized_name` field stores the lowercased, punctuation-stripped form — "Riemann-Roch" normalizes to "riemannroch" — enabling fuzzy prefix lookup via SQLite FTS5 trigram matching.

The `find_lemma_by_name` handler first attempts exact match on `normalized_name`, then FTS5 trigram fuzzy match if no exact hit. When `paper_id` is given, results are filtered to that paper. The response includes `dedup_key`, `display_name`, `paper_id`, `chunk_id`, `section_path`, and `confidence`, sorted by `confidence` descending.

**Deliverables.**
- `ingest/index_theorem_names.py` — streaming indexer: reads chunker output, extracts theorem/lemma/proposition/corollary labels, computes normalized names, writes to FTS5 table with dedup
- `server/handlers/lemma.py` — `find_lemma_by_name` handler: exact then fuzzy; `paper_id` filter
- `tests/test_theorem_names.py` — ingestion test: multiple papers each with a "Lemma 3.4" produce separate dedup entries; fuzzy search for "Yoneda" finds "Yoneda Lemma" entries

**Acceptance criteria.**
- [ ] Two papers each with a "Lemma 3.4" produce two separate entries in the theorem_names table
- [ ] `find_lemma_by_name("Yoneda lemma")` returns results across all indexed papers
- [ ] `find_lemma_by_name("Yoneda lemma", paper_id="2401.01234")` returns only results from that paper
- [ ] Fuzzy search: `find_lemma_by_name("riemanroch")` (typo) returns "Riemann-Roch" entries
- [ ] `pytest tests/test_theorem_names.py` passes

**Out of scope.** Cross-paper theorem identity resolution (determining that "Theorem 3.4" in paper A is the same mathematical result as "Corollary 2.1" in paper B — this is a v2 semantic dedup problem). Author disambiguation.

**Risk notes.**
- Closes MEDIUM: theorem-name dedup — without the `(paper_id, theorem_name, section_path)` triple as the dedup key, a query for "Lemma 3.4" returns a useless blend of hundreds of unrelated lemmas from different papers, destroying the utility of the `find_lemma_by_name` tool.

**Labels.** `area:index`, `kind:feature`, `tier:4`

---

### E10_S03 — Equation index: tree-edit distance fused with dense cosine

**Status:** NEW
**Tier:** 4
**Effort:** L
**Dependencies:** E03_S01, E04_S02, E06_S03

**Description.** Implement the equation similarity index that backs `find_equation(latex_or_mathml, k)`. The index fuses two complementary similarity signals: (1) tree-edit distance (TED) over canonical MathML computed using the Zhang-Shasha algorithm via the `zss` Python package; and (2) dense cosine similarity over the `embedding_eq` column (the column Sonnet A reserved in E03_S01, populated with equation embeddings from the `bge-m3` model run over `presentation_latex + context_sentence`).

The Zhang-Shasha TED algorithm treats the MathML parse tree as an ordered labeled tree and computes the minimum number of node insertions, deletions, and relabelings needed to transform one tree into another. This captures structural equation similarity in a way that dense embeddings miss — `\int_0^1 f(x) dx` and `\int_a^b f(t) dt` are structurally identical but densely different if the embedding model doesn't generalize well over variable names. The `zss` package provides `simple_distance(tree_a, tree_b)` over `Node` objects.

The query-time pipeline for `find_equation`:
1. Parse the input `latex_or_mathml` to canonical MathML (via the local LaTeXML subprocess pool, reusing the existing pool from `server/resources.py`).
2. Embed the input using the equation encoder (same model as index-time).
3. Retrieve top-200 candidates by dense cosine over `embedding_eq` (fast ANN pass).
4. Score each candidate by `zss.simple_distance(query_tree, candidate_tree)`.
5. Fuse the two scores using a weighted linear combination: `final_score = α * (1 - normalized_ted) + (1 - α) * cosine_score`, where `α = 0.5` is the default (configurable via `ARXMCP_EQ_TED_WEIGHT`).
6. Return top-k by `final_score`.

MathML parse trees are pre-computed at index time and stored in the `equations` table alongside `mathml` (the raw MathML string). A separate `mathml_tree_pickle` column stores the pickled `zss.Node` tree for fast deserialization at query time, avoiding a full re-parse of the MathML on every comparison.

The `find_equation` tool handler also accepts raw MathML as input (detected by the presence of an `<math>` root element) — this path skips the LaTeXML parsing step.

**Deliverables.**
- `server/retrieval/equations.py` — `EquationIndex` class: `query(latex_or_mathml, k) -> list[tuple[str, float]]`; TED computation; fusion
- `ingest/index_equations.py` — indexer: reads `equations` table, computes `zss.Node` trees from MathML, writes `mathml_tree_pickle` column
- `server/handlers/equation.py` — updated handler: delegates to `EquationIndex`; graceful fallback to dense-only if `mathml_tree_pickle` column is absent
- `tests/test_equation_index.py` — structural similarity test: `\int_0^1 f(x) dx` and `\int_a^b g(t) dt` have lower TED than `\sum_{n=0}^\infty a_n`; fusion ranks structural match above dense-only match in a known test case

**Acceptance criteria.**
- [ ] `find_equation("\\int_0^1 f(x) dx")` returns structurally similar integrals in the top-3
- [ ] TED score between `\int_0^1 f(x) dx` and `\int_a^b g(t) dt` is lower than between either and `\sum_{n=0}^\infty a_n`
- [ ] MathML input (raw `<math>...</math>`) is accepted and parsed correctly
- [ ] Graceful fallback to dense-only when `mathml_tree_pickle` column is absent
- [ ] `pytest tests/test_equation_index.py` passes

**Out of scope.** Training a custom equation encoder (use bge-m3 over `presentation_latex + context_sentence` in v1). Equation matching across different notational conventions (v2 problem). Visual rendering of equations in tool results.

**Risk notes.**
- Closes H5: sole-dense equation similarity fails for structurally distinct but semantically similar equations (different variable names, constant bounds). TED over canonical MathML provides the structural grounding that dense similarity lacks, and the fusion produces better recall than either signal alone.

**Labels.** `area:index`, `kind:feature`, `tier:4`

---

### E10_S04 — LaTeXML version drift detector

**Status:** NEW
**Tier:** 4
**Effort:** S
**Dependencies:** E10_S03

**Description.** LaTeXML version upgrades silently change the MathML output byte-for-byte — a `\frac{a}{b}` rendered by LaTeXML 0.8.7 produces different MathML than the same expression rendered by LaTeXML 0.8.8. This breaks the equation TED index (E10_S03): the stored `mathml_tree_pickle` values are no longer bit-comparable to freshly rendered query inputs, causing silent retrieval degradation with no error signal.

Implement a cron-driven drift detector: a daily job that re-renders 5 fixture papers using the current LaTeXML container image and compares the MathML output byte-for-byte against the stored values in the `equations` table. If any MathML string differs, the detector logs an alert at ERROR level and emits a Prometheus counter `arxmcp_latexml_drift_detected_total`. The 5 fixture papers are selected to cover a range of math complexity (simple fractions, multi-line aligned environments, commutative diagrams in tikz-cd, summation notation, integral notation) and are checked in to `tests/fixtures/latexml-drift/`.

When drift is detected, the runbook is:
1. Pull the new LaTeXML container image tag and record it in `ops/latexml-version.txt`.
2. Run `python -m ingest.index_equations --rerender-all` to re-render all stored MathML and rebuild the `mathml_tree_pickle` column. This is a full table rewrite and takes approximately 30 minutes for the 50-paper seed corpus, proportionally longer for the full corpus.
3. Run `pytest tests/test_equation_index.py` to verify the rebuilt index.
4. Restart the MCP server to pick up the new index version.

The runbook is documented in `docs/ops/latexml-drift-runbook.md`. The cron job is registered in `ops/cron/latexml-drift-check.sh` and documented in `docs/ops/cron-jobs.md`.

**Deliverables.**
- `ops/cron/latexml-drift-check.sh` — daily cron script: re-renders 5 fixture papers, diffs MathML, alerts on any difference
- `tests/fixtures/latexml-drift/` — 5 fixture `.tex` files + their expected MathML outputs (pinned to current LaTeXML version)
- `docs/ops/latexml-drift-runbook.md` — step-by-step reindex runbook with timing estimates
- `server/metrics.py` — updated with `arxmcp_latexml_drift_detected_total` counter

**Acceptance criteria.**
- [ ] Running the drift-check script against the current LaTeXML image produces zero alerts (no drift)
- [ ] Manually modifying a fixture's expected MathML causes the script to exit non-zero and emit an ERROR log
- [ ] `arxmcp_latexml_drift_detected_total` increments when drift is detected (verifiable via test)
- [ ] `docs/ops/latexml-drift-runbook.md` includes timing estimates for the 50-paper seed corpus and the 200K-paper full corpus

**Out of scope.** Automatic reindex on drift detection (runbook is manual in v1 — reindexing requires human confirmation). LaTeXML version pinning in the container image (separate ops concern).

**Risk notes.**
- Closes MEDIUM: LaTeXML version drift — without this detector, a LaTeXML container update silently corrupts the equation TED index and degrades `find_equation` retrieval quality with no observable error. The 5-fixture daily re-render is cheap (~10 seconds) and provides a strong early warning.

**Labels.** `area:ops`, `kind:observability`, `tier:4`
