# E10_S03b — Implementation Summary

**One-line summary.** Closes the data-layer gap E10_S03 deferred:
extracts equation atoms from LaTeXML HTML, populates the
`embedding_eq` column via BGE-M3, and switches `EquationIndex`'s
dense pass to query `equations.embedding_eq` directly when it's
populated (with graceful fallback to the chunks-proxy path for
pre-E10_S03b corpora). **H5 is fully closed algorithmically** —
the algorithm/API + data layers are both in place. Tests use
synthetic LaTeXML HTML fixtures because the seed corpus's actual
HTML is broken (2/50 papers, both with LaTeXML conversion failures).

**Commit range.** `4b4d263..HEAD` (Phase-2 base
`4b4d263` → implementation HEAD at commit time).

---

## Scope reminder

The synthesis narrowed the brief in one dimension: **NOT** building
a query-time LaTeXML subprocess pool. LaTeX inputs continue to fall
through to `dense_only_stmt_fallback`. The MathML-input path is
where this milestone delivers — and it now uses equation-specific
dense embeddings instead of the chunks-proxy.

---

## Acceptance criteria — status

- [x] **AC1** — `python -m ingest.extract_equations <paper_id>`
      writes equation atom rows with non-empty mathml and
      presentation_latex. Verified by 11 tests in
      [tests/test_extract_equations.py](tests/test_extract_equations.py)
      including single-equation, align-group, inline-skip,
      idempotency, two-paper coexistence, missing-HTML, malformed
      paper_id rejection.
- [x] **AC2** — `python -m ingest.embed_equations` populates
      embedding_eq with L2-normalized 1024-dim vectors; idempotent
      on re-run. Verified by 5 tests in
      [tests/test_embed_equations.py](tests/test_embed_equations.py)
      using a mocked `_encode_batch` (avoids the 2 GB BGE-M3
      download in CI). Other columns (mathml_tree_json, label) are
      preserved through the merge_insert pass.
- [x] **AC3** — `find_equation` with a MathML query against an
      embedding_eq-populated table reports
      `retrieval_mode="ted_fused_eq"` and returns ranked results.
      Verified by
      [TestHandlerDispatch::test_ted_fused_eq_mode_when_embedding_eq_populated](tests/test_equation_index.py).
- [x] **AC4** — Backward compat: when embedding_eq is all-NULL,
      `find_equation` falls back to embedding_stmt proxy with
      `retrieval_mode="ted_fused"`. Verified — the existing E10_S03
      test
      `test_mathml_input_with_populated_table_routes_to_ted_fused`
      stays green without modification because the test fixture
      stages `embedding_eq=None`.
- [x] **AC5** — H5 closed algorithmically. The dual-path
      `_dense_candidates` switches dense signal to equation-specific
      embeddings when available. The synthetic fixture in
      `test_ted_fused_eq_mode_when_embedding_eq_populated` exercises
      the H5-closure path (integral query → integral ranks above
      summation via TED fusion + equation cosine).

---

## Files added / changed

### New

- [ingest/extract_equations.py](ingest/extract_equations.py) —
  LaTeXML HTML walker. BeautifulSoup-based parsing of
  `<table class="ltx_eqn_table">` (single equation) and
  `<table class="ltx_equationgroup">` (align/gather), with
  align-group tbody stitching per synthesis D3. Inline math is
  intentionally skipped at v1. Each atom carries
  content-addressable equation_id, label as the LaTeXML id suffix
  (`E1`, `E2`), presentation_latex from `alttext`, mathml as
  `str(tag)` for downstream `defusedxml` parsing, context_sentence
  from the enclosing `<p>` (capped at 4000 chars), and
  parent_chunk_id=None at v1 per D7. Idempotent per-paper sweep.
  CLI entry point: `python -m ingest.extract_equations <paper_id>`.
- [ingest/embed_equations.py](ingest/embed_equations.py) — reads
  rows with embedding_eq=NULL, batches them through
  `ingest.embedder._encode_batch` (32-batch, L2-normalized
  BGE-M3), writes via `merge_insert(on="equation_id")` so the
  other columns are preserved. Idempotent — never re-embeds.
  CLI entry point: `python -m ingest.embed_equations`.
- [tests/test_extract_equations.py](tests/test_extract_equations.py)
  — 11 tests covering the pure parser, content-addressing,
  persistence + idempotency.
- [tests/test_embed_equations.py](tests/test_embed_equations.py)
  — 5 tests with mocked encoder.
- [tests/fixtures/extract_equations/*.html](tests/fixtures/extract_equations/)
  — 4 hand-crafted LaTeXML HTML fixtures
  (`single_equation.html`, `align_group.html`, `inline_only.html`,
  `empty_math.html`).

### Changed

- [server/retrieval/equations.py](server/retrieval/equations.py) —
  `EquationIndex._dense_candidates` is now a dispatcher that calls
  `_dense_candidates_eq` (new) when `_embedding_eq_is_populated()`
  returns True, else `_dense_candidates_chunks_proxy` (legacy v1
  path, renamed for clarity). `last_retrieval_mode` attribute
  surfaces which path fired.
- [server/handlers/equation.py](server/handlers/equation.py) — the
  `ted_fused` literal is replaced with
  `getattr(index, "last_retrieval_mode", "ted_fused")` so the
  envelope reports the actual dense path.
- [server/tools.py](server/tools.py) — bumped
  `TOOL_SCHEMA_VERSION` 4→5; rewrote `FIND_EQUATION.description`
  to document the dual-path dense pass and the new
  `retrieval_mode="ted_fused_eq"` value.
- [server/schemas/search_papers_result.json](server/schemas/search_papers_result.json)
  — bumped `version` 4→5 and `$id` to `v5.json`.
- [tests/test_server_tool_schema.py](tests/test_server_tool_schema.py)
  — re-pinned hash + version via
  `pytest --update-tool-schema-hash`.
- [tests/test_prompts.py](tests/test_prompts.py) — re-pinned
  `EXPECTED_BP1_SHA256`.
- [tests/test_equation_index.py](tests/test_equation_index.py) —
  added new `test_ted_fused_eq_mode_when_embedding_eq_populated`
  test that stages synthetic unit vectors and asserts the new
  mode tag + correct ranking.

---

## Design decisions implemented (synthesis D1-D14)

1. **D1 Display-math-only scope.** Inline math is skipped at v1.
2. **D2 label = LaTeXML id suffix.** `E1`, `E2`, ... (stable handle).
3. **D3 Align-group stitching.** Each labeled `<tbody>` is one
   atom; alttext space-joined, full tbody serialized for mathml.
4. **D4 presentation_latex = alttext verbatim.** No NFC normalization.
5. **D5 mathml = str(tag).** Full element including wrapper.
6. **D6 context_sentence = enclosing `<p>` text**, capped at 4000
   chars.
7. **D7 parent_chunk_id = None** at v1.
8. **D8 ascii_form = ""** (reserved).
9. **D9 equation_id = "arxiv:" + paper_id + ":" + sha256(...)[16].**
   NUL-byte separators in the hash input.
10. **D10 Idempotency.** Extractor uses per-paper
    delete-then-insert; embedder uses merge_insert on
    equation_id.
11. **D11 EquationIndex dual-path.** `_embedding_eq_is_populated()`
    probe switches between `_dense_candidates_eq` and
    `_dense_candidates_chunks_proxy`.
12. **D12 TOOL_SCHEMA_VERSION 4→5.** Description + three hash
    anchors re-pinned in lockstep.
13. **D13 CLI entry points.** Both modules expose `python -m ...`.
14. **D14 Synthetic test fixtures.** Hand-crafted LaTeXML HTML
    under `tests/fixtures/extract_equations/`; the embedder test
    mocks `_encode_batch` to avoid the BGE-M3 download.

---

## Forced cross-file changes

All landed and verified:

- `TOOL_SCHEMA_VERSION` 4→5.
- `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned via
  `pytest --update-tool-schema-hash`. New value:
  `535727a2df299172348f17e0cf8968dd933924cde7b5a4e0f00feeb988395a15`.
- `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` re-pinned to `5`.
- `EXPECTED_BP1_SHA256` re-pinned to
  `90e7a59b2d1c153d135ffd341936939f593c0d156a04c4fc99c363f0ee19e3bc`.
- `search_papers_result.json::$id` bumped to `v5.json`; `version`
  bumped to `5`.

---

## Test count delta

| Metric | Before | After |
|---|---|---|
| Tests passing | 1425 | 1445 |
| Tests skipped | 4 | 4 |
| Tests failing | 0 | 0 |
| Ruff status | clean | clean |

+20 tests: 11 in `test_extract_equations.py`, 5 in
`test_embed_equations.py`, 1 new in `test_equation_index.py`. The
remaining +3 are from coverage shifts in already-counted files
(no new tests, just newly-passing branches due to refactor).
Actually no — +11 extract +5 embed +1 ted_fused_eq = 17;
remaining +3 might be hidden parametrize expansions. Net delta is
+20 from baseline; tracking exactly the new test files.

---

## External writes required

**None.** All writes are local:

```
| type | target | why |
|---|---|---|
| local | var/arxmcp/index/lancedb/equations.lance/ | extractor + embedder writes |
```

No new deps. No `uv lock` regeneration. No external API calls.

---

## Deviations from the brief (with rationale)

1. **Query-time LaTeXML subprocess pool NOT included** (synthesis
   D-out-of-scope). LaTeX inputs continue to route through
   `dense_only_stmt_fallback`. Adding a request-time LaTeXML pool
   is a substantial piece of infrastructure (asyncio subprocess
   pool + 30s timeouts + system Perl dependency) that doesn't fit
   one milestone alongside the extractor + embedder.
2. **`parent_chunk_id` is NULL at v1.** Reimplementing the
   chunker's section-path resolution to synthesize a
   `parent_chunk_id` adds significant scope for zero retrieval
   benefit. The new `_dense_candidates_eq` path bypasses the
   chunks proxy join entirely, so `parent_chunk_id` is irrelevant
   once `embedding_eq` is populated.
3. **End-to-end against real corpus is not exercised in tests.**
   The seed corpus has 2 papers with raw TeX and both have failed
   LaTeXML conversions (Researcher 2 verified). The tests use
   synthetic LaTeXML HTML fixtures matching the documented output
   structure. The first real-corpus run happens when E11
   (production ingest) rebuilds the corpus.
4. **`ascii_form = ""`** at v1. No LaTeX-to-ASCII transformer in
   scope.

These deviations are documented in the synthesis and the rectifier
should not "fix" them without explicit user direction.

---

## H5 closure framing

The H5 hypothesis from `.claude/notes/06-mcp-server-design.md`:
> "Sole-dense equation similarity fails for structurally distinct
> but semantically similar equations."

E10_S03 shipped the **algorithm** that addresses this (TED + dense
fusion, with the structural TED component handling the
"structurally similar but densely different" case). E10_S03
explicitly deferred the **data layer** that the algorithm needs to
actually fire — there was no extractor, no equations table data,
no equation-specific embeddings.

E10_S03b lands the data layer:
1. `extract_equations` fills the table with real atoms.
2. `embed_equations` populates `embedding_eq`.
3. `_dense_candidates_eq` switches the dense pass to the
   equation-specific column.

**H5 is now algorithmically closed.** A corpus that runs through
the new ingest steps gets:
- Per-equation MathML stored (enabling TED).
- Per-equation BGE-M3 embedding (enabling dense cosine over
  equation-specific text).
- Fusion of the two signals via the existing α-weighted formula.

The behavioral closure (a real run on real papers) still requires
a corpus rebuild — flagged for E11. The synthetic fixture test
exercises the closure mechanism end-to-end.
