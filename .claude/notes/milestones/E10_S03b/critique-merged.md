# Critique — E10_S03b

**Critic:** adversary
**Generated:** 2026-05-14T00:00:00Z
**Commit range:** 4b4d263..7ff2656
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict is SHIP-WITH-FIXES — the code lands the data layer the brief
  asked for and 1445 tests pass / ruff clean, but the FIND_EQUATION
  description omits a `retrieval_mode` value the handler can emit,
  which leaks an LLM-visible inconsistency through BP1.
- Finding counts: 0 CRITICAL, 1 HIGH, 4 MEDIUM, 4 LOW.
- Highest-risk file: `server/tools.py:131-148` — the BP1-cached tool
  description fails to enumerate `malformed_mathml_fallback` even
  though `server/handlers/equation.py:68` actively emits it.
- Cross-axis pattern: two `except Exception` blocks
  (`server/retrieval/equations.py:491` and
  `ingest/extract_equations.py:346`) repeat the broad-catch foot-gun
  flagged as F3 in the E10_S01 critique. Documented reasoning is
  "first write may raise", but a narrower exception type would still
  preserve the safe fallback without masking real errors.
- The hash anchors (`TOOL_SCHEMA_VERSION=5`, `EXPECTED_TOOL_SCHEMA_SHA256`,
  `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH=5`, `EXPECTED_BP1_SHA256`,
  `search_papers_result.json::version=5`) are all in lockstep — no
  cache-stability regression.
- Synthesis-D3 align-group serialization (`str(tbody)`) produces a
  MathML tree rooted at `tbody`, NOT `math` — this means
  align-group atoms TED against single-equation atoms with
  structurally-different roots. Verified empirically: a trivial
  `<math>` vs the matching `<tbody>` wrapper scores 0.79 TED.
- The "H5 fully closed" claim in the implementation summary is
  algorithmically true but is only exercised against SYNTHETIC unit
  vectors as `embedding_eq`. Real BGE-M3 over equation text is not
  validated; the brief AC5 should not claim full closure.
- Test count delta: 1311 baseline → 1445 (+134) is plausible across
  E10_S03b's 17 new tests plus other recent milestones; ruff clean.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — FIND_EQUATION description omits `malformed_mathml_fallback`

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/tools.py:131-148
- **What:** The FIND_EQUATION tool description enumerates four
  `retrieval_mode` values: `ted_fused_eq`, `ted_fused`,
  `dense_only_stmt_fallback`, `dense_only_fallback`. It does NOT
  mention `malformed_mathml_fallback`, which the handler emits at
  `server/handlers/equation.py:68` when MathML parsing fails.
  `grep -n "malformed_mathml_fallback" server/tools.py` returns
  empty.
- **Why it matters:** The tool description is the contract LLM
  callers consume through BP1 (the prompt-cached system region).
  Documenting four modes but emitting five means a downstream agent
  that branches on `retrieval_mode` may treat
  `malformed_mathml_fallback` as a parse error and fail, when the
  envelope is actually well-formed. The contract is canonical-by-
  description (CLAUDE.md §4.7: "Frozen tool descriptions… bytes-
  stable"); a missing enum value is a contract gap reachable on a
  common path (LLM-emitted MathML with one missing close tag).
- **Proposed fix:** Append the fifth mode to the FIND_EQUATION
  description sentence about fallbacks (e.g. between the
  `dense_only_fallback` and `retrieval_mode field always documents
  the active path` sentences add: "If MathML parsing fails outright,
  the handler degrades to retrieval_mode='malformed_mathml_fallback'
  rather than 5xx-ing the request."). Bump TOOL_SCHEMA_VERSION 5→6
  and re-pin `EXPECTED_TOOL_SCHEMA_SHA256`,
  `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`, `EXPECTED_BP1_SHA256`,
  `search_papers_result.json::version + $id`. Run `pytest
  --update-tool-schema-hash`.
- **Regression guard:** Add a test in
  `tests/test_server_tool_schema.py` (or co-located) that asserts
  every literal `retrieval_mode` value emitted by
  `server/handlers/equation.py` appears as a substring in
  `FIND_EQUATION.description`. Use a small AST or regex scrape of
  the handler source. Pin the set so future modes cannot be added
  without an accompanying description update.

### F2 — Align-group vs single-equation root produces non-comparable TED trees

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/extract_equations.py:231 (mathml = _serialize_mathml(tbody))
- **What:** `_extract_align_group_atoms` serializes the entire
  `<tbody>` element to `mathml` (synthesis D3) so the TED tree
  preserves LHS/RHS column structure. But `parse_mathml_to_tree` in
  `server/retrieval/equations.py:108` builds a tree rooted at
  whatever the XML root is. Empirically, the root label is `tbody`
  for align-group atoms and `math` for single-equation atoms. TED
  between an isolated `<math><mrow><mi>x</mi></mrow></math>` and a
  trivial-equivalent `<tbody>…<math>…</math>…</tbody>` scores 0.79.
- **Why it matters:** Two papers expressing the same equation
  differently — one in `\begin{equation}`, one as a single row of
  `\begin{align}` — will produce atoms whose `mathml_tree_json`
  trees can never reach a low normalized_ted. H5's hypothesis
  (structurally distinct but semantically similar) is precisely the
  case TED is meant to handle, but the choice of dissimilar root
  labels means it cannot. Synthesis D3 documents the serialization
  decision but does not address this comparability gap.
- **Proposed fix:** Two reasonable options. (a) Serialize each
  align-group `<tbody>` as a synthetic `<math>` wrapper around the
  stitched child `<math>` elements, so the tree root remains `math`.
  (b) Strip the `tbody` root in `_element_to_node` (or in a wrapper
  layer) so the tree treats the tbody's children as the root's
  children — i.e. drop the tbody node when serializing the tree.
  Option (a) is cleaner because it keeps `mathml` self-describing.
- **Regression guard:** Add a test in `tests/test_equation_index.py`
  that parses both a single-equation `<math>` atom and an
  align-group `<tbody>` atom carrying the same `<mi>x</mi>` content,
  and asserts `normalized_ted(t1, t2) < 0.3` (the cross-form
  comparability threshold). The current test_equation_index does
  not cover this case.

### F3 — `_embedding_eq_is_populated()` exception fallback materializes full table

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/retrieval/equations.py:491-500
- **What:** The fast-path probe (`search().where("embedding_eq IS
  NOT NULL").limit(1).to_arrow()`) is bounded. The `except
  Exception` fallback at line 491 does a full `self._equations.
  to_arrow()` and then reads `column("embedding_eq").null_count`.
  At E11/E12 corpus scale (~4M chunks → potentially ~10-50M
  equations after extraction), this materializes the entire
  equations table into Python memory on EVERY query that hits the
  exception path.
- **Why it matters:** Synthesis assumes the equations table is
  "small at v1 corpus scale" — that holds today (seed corpus has
  ~zero rows), but the contract is reachable as soon as a future
  LanceDB upgrade changes how `WHERE col IS NOT NULL` is parsed for
  vector columns. The exception path becomes a latent DoS vector
  once the corpus grows.
- **Proposed fix:** Cap the fallback with a small slice, e.g.
  `arrow = self._equations.to_arrow().slice(0, 10_000)`. If 10K
  rows are all NULL on embedding_eq, the production-corpus is
  vanishingly likely to have any non-NULL rows further out. A
  10K-row probe is bounded at ~40MB (10K × 1024 floats × 4 bytes)
  regardless of corpus scale.
- **Regression guard:** Add a test in `tests/test_equation_index.py`
  that monkeypatches `_equations.search` to raise (forcing the
  except branch) on a synthetic 20K-row table and asserts the call
  completes within a tight time + memory budget.

### F4 — `_embedding_eq_is_populated()` runs on every query, no caching

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/retrieval/equations.py:467 + server/handlers/equation.py:55
- **What:** `EquationIndex` is constructed per-request
  (`server/handlers/equation.py:55`), so the populate-check fires
  on every MathML query. Even on the fast path
  (`.where("embedding_eq IS NOT NULL").limit(1)`) this is at least
  one round-trip to LanceDB plus an Arrow-table materialization.
  Per-instance caching doesn't help because the instance is
  request-scoped.
- **Why it matters:** Repeated I/O on every `find_equation` request
  is wasted work — the result is a property of the corpus, not the
  query, and only changes when a corpus-version bump occurs. At
  high QPS this adds latency on every request that takes the
  TED-fusion path.
- **Proposed fix:** Move the populate check to `Resources` lifespan
  startup (the same place corpus_version is pinned). Cache the
  bool as `Resources.equations_has_eq_embeddings`. Pass it into
  `EquationIndex.__init__` so the per-request dispatch is a field
  read, not a LanceDB query. Invalidate via the corpus_version
  bump path that already exists.
- **Regression guard:** Add a test that asserts
  `EquationIndex._embedding_eq_is_populated` is NOT called during
  `handle_find_equation` (use a monkeypatch counter) — the value
  must come from Resources.

### F5 — Broad `except Exception` masks real LanceDB errors in extract_equations

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/extract_equations.py:344-351
- **What:** `extract_equations_for_paper` wraps `table.delete(
  safe_filter)` in a broad `except Exception` with the comment
  "first-write may raise". The same critique fired against E10_S01
  as F3 of that milestone; the rectification protocol there was to
  narrow the exception type. Here the catch absorbs all
  exceptions — including real failures like schema mismatch,
  permission denied, disk full, or LanceDB internal errors.
- **Why it matters:** A schema drift between extractor runs (e.g.
  a future EQUATIONS_SCHEMA_V2) would silently no-op the delete,
  and the subsequent `table.add(...)` would either fail or produce
  inconsistent rows. The operator gets a DEBUG-log message they
  will never see in production logs.
- **Proposed fix:** Narrow the exception type. The documented
  "first-write raises" case for LanceDB is `FileNotFoundError` or
  a specific `ValueError` from `_pkg.error_handling`. Test on the
  pinned LanceDB version which exception type is raised on
  empty-table delete and catch only that.
- **Regression guard:** Add a test in
  `tests/test_extract_equations.py` that mocks
  `table.delete` to raise a generic `RuntimeError` and asserts
  `extract_equations_for_paper` re-raises rather than silently
  proceeding.

### F6 — Fallback `find("math")` picks first math element non-deterministically

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/extract_equations.py:172-177
- **What:** `_extract_equation_atom` first looks for
  `<math display="block">`; on miss, it falls back to the first
  `<math>` child of the equation table. If a single-equation table
  has multiple `<math>` elements (rare but observed in some
  LaTeXML conversion edge cases — e.g. an embedded inline math
  inside a commented-out caption), the wrong math element wins.
- **Why it matters:** Low blast radius. The fallback path is
  triggered only when display="block" is absent — synthesis
  D1/researcher 2 verified this is rare. But the determinism
  contract from `06-mcp-server-design.md` says result selection
  should be deterministic; "first in document order" is
  deterministic but not necessarily correct.
- **Proposed fix:** If multiple `<math>` elements exist and none
  has display="block", log a WARNING with the paper_id and skip
  the table entirely rather than guessing. Or restrict the
  fallback to "exactly one math child".
- **Regression guard:** N/A — LOW.

### F7 — No HTML size cap in extract_equations_for_paper

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/extract_equations.py:335
- **What:** `extract_equations_for_paper` reads the LaTeXML HTML
  via `src.read_text(...)` and passes it straight to
  `BeautifulSoup`. No upper bound on file size. An adversarial or
  malformed LaTeXML output could be multi-GB.
- **Why it matters:** Operator-facing tool reading trusted local
  files, so the threat model is low. But a corrupted disk or a
  pathological PDF→HTML conversion could OOM the ingest process.
- **Proposed fix:** Stat the file first; refuse reads above e.g.
  100MB with a logged WARNING.
- **Regression guard:** N/A — LOW.

### F8 — "H5 fully closed" claim hinges on synthetic embeddings

- **Severity:** LOW
- **Source:** adversary
- **File:** .claude/notes/milestones/E10_S03b/implementation-summary.md:8 + state.json (AC5)
- **What:** The implementation summary states "H5 is fully closed
  algorithmically" and AC5 lists "H5 closed" as ticked. The
  closure test (`test_ted_fused_eq_mode_when_embedding_eq_populated`)
  stages synthetic unit-vector embeddings as `embedding_eq`. It
  does NOT verify that real BGE-M3 over real equation text would
  produce the ranking the hypothesis demands.
- **Why it matters:** AC5 of the brief asks for "a corpus with the
  seeded math.AG fixtures + embedding_eq populated should rank an
  integral query above a structurally-distinct summation
  candidate". The implementation summary admits the seed corpus
  HTML is broken; the closure is mechanically achievable but
  empirically unverified. This is a documentation precision issue,
  not a code defect.
- **Proposed fix:** Update the AC5 status in state.json and the
  implementation-summary's H5 section to read "H5 closure
  mechanism is in place; behavioral closure requires E11 corpus
  rebuild". Do not relitigate the closure framing.
- **Regression guard:** N/A — LOW (documentation precision).

### F9 — `test_embed_equations.py` mocks `_encode_batch` with no integration test

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/test_embed_equations.py:81-88
- **What:** The mocked `_encode_batch` returns
  `(np.zeros((n, EMBEDDING_DIM), dtype=np.float32), 0)`. If
  `ingest.embedder._encode_batch`'s signature changes (e.g. an
  extra required parameter, a renamed kwarg, a different return
  shape), the monkeypatch will continue to silently pass tests
  that no longer exercise the real path.
- **Why it matters:** Low — the embedder signature is fairly
  stable, and other tests would catch a signature break upstream.
  But the AC2 verification rests on a mocked encoder, so the test
  alone does not prove `embed_pending_equations` is wired
  correctly end-to-end.
- **Proposed fix:** Add a `requires_model`-marked integration
  test that loads the real BGE-M3 and runs `embed_pending_equations`
  on 2-3 hand-staged rows; assert `||vec|| ≈ 1.0` and that the
  output dimensions match. Skip by default; opt-in via
  `ARXMCP_RUN_REAL_BGE_M3=1`.
- **Regression guard:** N/A — LOW.

## What was done well

- Hash anchors are re-pinned in perfect lockstep: `TOOL_SCHEMA_VERSION
  = 5`, `EXPECTED_TOOL_SCHEMA_SHA256` (the 64-hex literal in
  test_server_tool_schema.py:95), `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH
  = 5` (line 109), `EXPECTED_BP1_SHA256` (test_prompts.py:614),
  `search_papers_result.json::$id = v5.json` (line 3),
  `search_papers_result.json::version = 5` (line 6). The
  byte-stability test passes, BP1 cache discipline is intact.
- The dual-path dispatch in `_dense_candidates` is clean: a single
  predicate (`_embedding_eq_is_populated`) selects between the new
  `_dense_candidates_eq` path and the legacy
  `_dense_candidates_chunks_proxy` path with no shared state. The
  `last_retrieval_mode` field is per-instance and per-request so
  no thread-safety hazard.
- Per-paper idempotency is correctly implemented via delete-then-
  insert (extractor) and `merge_insert(on="equation_id")` (embedder).
  Re-runs do not produce duplicates; test coverage in
  `test_idempotent_per_paper` and `test_idempotent_on_already_embedded`
  is concrete.
- Content addressing via `equation_id = "arxiv:<paper_id>:" +
  sha256(paper_id || \\x00 || mathml || \\x00 || (label or "")).
  hexdigest()[:16]` uses NUL-byte separators, defending against
  the boundary-collision class the synthesis flagged.
- `paper_id` validation in `extract_equations_for_paper` raises
  `ValueError` BEFORE any file-system access, and the regression
  test `test_rejects_malformed_paper_id` exercises this. Path
  traversal via `paper_id` is blocked at the gate.
- Defusive XML: `parse_mathml_to_tree` uses `defusedxml.
  ElementTree` (verified `xmlns="http://www.w3.org/1998/Math/MathML"`
  in `str(math_tag)` is handled correctly, confirmed by the
  existing `test_strips_namespace_prefix` test that survives the
  refactor).
- The `_encode_batch` reuse from `ingest.embedder` keeps the BGE-M3
  contract single-sourced (same batch size, dtype, L2-normalization
  invariant), with the embedder-side `truncated_count` surfaced in
  `counts["truncated_inputs"]`.
- The implementation-summary explicitly calls out the deviations
  from the brief (no LaTeXML pool, parent_chunk_id=NULL,
  ascii_form="", synthetic test fixtures) — the rectifier should
  not "fix" these documented out-of-scope items.

## Recommended rectification order

1. **F1** (HIGH, ≤ 10 LOC + hash repins) — append the fifth
   `retrieval_mode` value to FIND_EQUATION.description, bump
   TOOL_SCHEMA_VERSION 5→6, repin all four anchors. The fix is
   mechanical; the regression guard (handler-vs-description
   coverage test) prevents recurrence. Highest-priority because
   it leaks into BP1.
2. **F2** (MEDIUM, ≤ 30 LOC) — wrap align-group atoms in a
   synthetic `<math>` root so TED trees have comparable roots.
   Tightly scoped to `_extract_align_group_atoms` and the
   companion test.
3. **F5** (MEDIUM, ≤ 5 LOC) — narrow the `except Exception` in
   `extract_equations_for_paper` to the specific exception type
   LanceDB raises for empty-table delete. Same pattern E10_S01
   already established.
4. **F3** (MEDIUM, ≤ 5 LOC) — cap the `_embedding_eq_is_populated`
   exception fallback with `.slice(0, 10_000)` so the path is
   bounded regardless of corpus scale.
5. **F4** (MEDIUM, ≤ 30 LOC if Resources change is small) — move
   the populate-check to Resources lifespan, cache as a field.
   May spill to ≥ 30 LOC if Resources construction shape changes;
   defer if cost grows.
6. **F6, F7, F8, F9** — LOW; record as deferred unless trivially
   bundled with a co-located fix.

## Rectification status (Phase 4)

Re-verify ran for all 9 findings. None invalidated; every cited
file:line region matched the critique's "what" claim.

- **F1 (HIGH) — fixed.** Appended `malformed_mathml_fallback` to
  `FIND_EQUATION.description`. Bumped `TOOL_SCHEMA_VERSION` 5→6;
  re-pinned `EXPECTED_TOOL_SCHEMA_SHA256`,
  `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`, `EXPECTED_BP1_SHA256`,
  and `search_papers_result.json::version+$id` in lockstep.
  Regression guard
  `test_find_equation_description_lists_every_retrieval_mode`
  scrapes the handler and EquationIndex sources for every
  emitted `retrieval_mode` literal and asserts each appears in the
  description.
- **F2 (MEDIUM) — fixed.** Align-group serialization now wraps the
  stitched cell contents in a synthetic `<math display="block">`
  root with the per-cell `<math>` wrappers STRIPPED (via
  `decode_contents()`). Regression test
  `test_align_group_ted_comparable_to_single_equation` asserts
  `normalized_ted == 0.0` between a single-equation atom and an
  align-group atom carrying the same `<mi>x</mi>` content.
- **F3 (MEDIUM) — fixed.** The `_embedding_eq_is_populated`
  exception fallback now slices the equations table to the first
  `_POPULATE_CHECK_SLICE = 10_000` rows (~40MB ceiling). At
  production scale the embedder fills paper-by-paper, so partial
  population is detectable well within the first 10K rows.
- **F5 (MEDIUM) — fixed.** `extract_equations_for_paper` now
  guards the `tbl.delete` call with a row-count precondition
  (`_table_has_any_rows_for_paper`); broad `except Exception` is
  gone. Regression test `test_delete_failure_surfaces_not_swallowed`
  monkeypatches delete to raise `PermissionError` and asserts the
  extractor re-raises. Mirrors the E10_S01 / E10_S02 F3-rect.
- **F4 (MEDIUM) — deferred.** Caching the populate-check on
  `Resources` requires changes to `Resources.startup` shape +
  invalidation on corpus-version bump. Defer — the fast path is
  already bounded at one LanceDB round-trip per query, within
  latency budget at v1 + Tier-4 scale.
- **F6 (LOW) — deferred.** Multi-`<math>` fallback determinism;
  current "first in document order" is acceptable for the rare-
  and-bounded edge case.
- **F7 (LOW) — deferred.** HTML size cap; operator-trusted local
  file, bounded by filesystem state.
- **F8 (LOW) — addressed in docs.** "H5 fully closed" framing
  softened to "H5 closed algorithmically; behavioral closure
  requires E11 corpus rebuild" (no code change).
- **F9 (LOW) — deferred.** `requires_model` integration test for
  the embedder against real BGE-M3 belongs with E11's
  ingest-quality eval pass.

**Invalidation rate:** 0 / 9 findings invalidated (0%). Adversary
critic was well-calibrated.

**Test count delta after rectify:** 1449 passing (+4 regression
guards from post-implement 1445). 4 skipped, 0 failed, ruff clean.

| Finding | Severity | Status |
|---|---|---|
| F1 — description missing `malformed_mathml_fallback` | HIGH | fixed (regression test + hash repin) |
| F2 — align-group TED root mismatch | MEDIUM | fixed (regression test) |
| F3 — unbounded fallback materialization | MEDIUM | fixed (10K-row cap) |
| F4 — no caching of populate check | MEDIUM | deferred (latency budget OK) |
| F5 — broad except in extractor | MEDIUM | fixed (regression test) |
| F6 — multi-math fallback non-determinism | LOW | deferred |
| F7 — no HTML size cap | LOW | deferred (operator-trusted) |
| F8 — "H5 fully closed" framing | LOW | addressed (docs softened) |
| F9 — mock-only embedder test | LOW | deferred (E11 corpus eval) |
