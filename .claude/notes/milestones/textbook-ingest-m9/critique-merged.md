# Critique — textbook-ingest-m9

**Critic:** adversary
**Generated:** 2026-05-28T11:10:00Z
**Commit range:** 2dcf6bb..4d59c97
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the source_kind filter + tag CAPABILITY is correct, secure, and byte-stable, but two HIGH gaps undercut the milestone's own claims — the e4 OUTCOME is untracked and the FM-1 under-fill rationale is unproven.
- 0 CRITICAL, 2 HIGH, 4 MEDIUM, 1 LOW.
- Highest-risk file:line — `tests/test_store.py:1359` (TestSourceKindPrefilter proves `.where()` filters but NOT the under-fill case that justifies pre-filter over post-filter; 2 chunks + limit(10) cannot distinguish the two).
- The synthesis (research-synthesis.md:60) explicitly directed "File as a follow-up ISSUE at e4-close"; no `gh issue` exists and e4 is being declared CLOSED — the deferred-without-tracking anti-pattern.
- Cross-axis security is clean: SQL-injection whitelist fires before interpolation on every path; the combined `(paper_id IN (...)) AND (source_kind = '...')` predicate was verified to execute correctly on a real LanceDB.
- Cache discipline is exemplary: TOOL_SCHEMA_VERSION, EXPECTED_TOOL_SCHEMA_SHA256, EXPECTED_BP1_SHA256, both result schemas, and the version-at-hash pin all moved together and were verified stable by re-running the suite.
- A doc-accuracy drift survives inside the SAME `tools/list` payload: the ToolMeta says source_kind is filterable, the `filters` parameter inputSchema still says "other keys are ignored" (search.py:351).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings

### F1 — e4 follow-up driver deferred without tracking; e4 closed regardless

- **Severity:** HIGH
- **Source:** adversary
- **File:** .claude/notes/milestones/textbook-ingest-m9/implementation-summary.md:35 (vs research-synthesis.md:60)
- **What:** The synthesis directs "File as a follow-up ISSUE at e4-close" for the missing `tools/notebook_textbook_ingest.py` driver (embed m7 textbook chunk JSONs → write notebook LanceDB). The implementation-summary only records it as prose ("Flagged as a follow-up at e4 close") and declares "textbook-ingest-e4 is CLOSED." `gh issue list --repo chris-dare-dev/arXMCP --state all` shows NO matching issue (issues #1–#7 cover unrelated E13 threats).
- **Why it matters:** Without the driver, the e4 OUTCOME — "the Milne/Caraiani PDFs return in result rows" — is unachievable end-to-end: there is no path to get any textbook chunk into a notebook's LanceDB (verified: `tools/notebook_ingest.py:102` calls `run_bulk_ingest` over arXiv paper_ids only; `chunk_textbook` has no caller that writes to LanceDB). Closing e4 with the central outcome unreachable AND untracked is the named "deferred-without-tracking" anti-pattern; the project's own precedent is to file an issue (the synthesis assumed this).
- **Proposed fix:** Phase 4 main-thread files a GitHub issue at `chris-dare-dev/arXMCP` titled "textbook-ingest-e4 follow-up: notebook_textbook_ingest driver (embed m7 chunk JSONs → notebook LanceDB)" and records the issue number in implementation-summary.md §"Out of scope". Issue creation is a Phase-4-main-thread / per-event-authorized operation (agent-conventions.md §8) — do NOT have an agent run `gh issue create`.
- **Regression guard:** N/A (process/tracking finding). The guard is the recorded issue number in the summary; a future reader can verify the deferral is live, not lost.

### F2 — Pre-filter under-fill mitigation (FM-1) is asserted but never tested

- **Severity:** HIGH
- **Source:** adversary
- **File:** tests/test_store.py:1359 (TestSourceKindPrefilter._seed_mixed_corpus)
- **What:** FM-1 — the entire stated reason to use a LanceDB pre-filter instead of a post-retrieval filter — is that a textbook filter over a mostly-arXiv top-k drops all textbook results. `TestSourceKindPrefilter` seeds exactly 1 arxiv + 1 textbook chunk and queries with `.limit(10)`. With 2 chunks under a limit of 10, the unfiltered top-k already contains both, so `test_textbook_prefilter_returns_only_textbook` passes identically whether the filter is applied PRE-retrieval or POST-retrieval. The test proves `.where()` filters; it does NOT prove pre-filter solves under-fill.
- **Why it matters:** The load-bearing design claim (handler comment search.py:416-422, synthesis OQ-2) is unverified. A future refactor that moves the predicate to a post-retrieval candidate filter (e.g. dropping `prefilter=True`, or filtering `_arrow_to_rows` output) would pass every existing test while reintroducing the exact zero-results bug FM-1 warns about on real notebook corpora (mostly-arXiv with a few textbook chunks).
- **Proposed fix:** Add a test in `tests/test_store.py::TestSourceKindPrefilter` that seeds N (e.g. 20) arxiv chunks whose embeddings are CLOSER to the query vector than a single textbook chunk, then queries with `k`/`limit` small enough (e.g. `.limit(5)`) that the textbook chunk is NOT in the unfiltered top-k. Assert: (a) no-filter `.limit(5)` returns 0 textbook rows; (b) `.where("source_kind='textbook'", prefilter=True).limit(5)` still returns the textbook chunk. (b) only holds for a true pre-filter — a post-filter would return empty.
- **Regression guard:** The test above IS the guard — it fails iff the pre-filter degrades to a post-filter.

### F3 — `filters` parameter inputSchema description contradicts the new capability

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/handlers/search.py:351
- **What:** The widened ToolMeta description (tools.py:184-186) documents `filters={'source_kind': 'textbook'}` as supported, but the `filters` parameter's Pydantic `Field` description — which FastMCP renders into the `tools/list` `inputSchema` (verified live: the wire bytes contain `"other keys are ignored and surface in 'filter_warnings'"` and do NOT contain `source_kind`) — still reads "Honors 'paper_id'... other keys are ignored and surface in 'filter_warnings'." The two halves of the SAME `tools/list` response disagree about whether source_kind is honored.
- **Why it matters:** An LLM agent that reads the parameter schema (the precise, machine-consumed contract) concludes source_kind is ignored and may avoid emitting it or treat results as unfiltered. This is the description-vs-validator drift class (see adversary MEMORY 2026-05-27 bp1/security-doc drift) re-surfacing on the inputSchema surface. Filtering still WORKS, so this is doc-accuracy, not a behavior bug.
- **Proposed fix:** Update the `filters` Field description in `handle_search_papers` (search.py:347-352) to name source_kind as an honored key alongside paper_id. NOTE: this re-drifts BOTH EXPECTED_TOOL_SCHEMA_SHA256 and EXPECTED_BP1_SHA256 (the Field description is in the hashed inputSchema), so it MUST be a coordinated re-pin: edit description → `pytest tests/test_server_tool_schema.py --update-tool-schema-hash` → re-pin EXPECTED_BP1_SHA256. Cheap (~3 LOC + two pins) and worth doing now while the version is already moving.
- **Regression guard:** Existing `test_server_tool_schema.py::TestPinnedHash` + `test_prompts.py::TestBP1ByteIdentityAcrossFanout` re-pinned to the corrected bytes; add a one-line assertion that `"source_kind"` appears in the search_papers inputSchema filters description.

### F4 — Combined paper_id+source_kind predicate never executed against real LanceDB

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_search_filter.py:505
- **What:** `test_combined_paper_id_and_source_kind` asserts the exact predicate STRING `"(paper_id IN ('textbook:sv-book')) AND (source_kind = 'textbook')"` against the `_FakeSearchBuilder` (which records `.where` but returns rows regardless). `TestSourceKindPrefilter` (real LanceDB) only exercises single-clause `.where("source_kind = '...'")`. The combined parenthesized-AND form is never run against a real LanceDB, so a malformed combined predicate (wrong parenthesization, a LanceDB SQL-dialect quirk) would not be caught by any test. (I manually verified the current string IS valid on real LanceDB, so this is a test-gap, not a live bug.)
- **Why it matters:** The combine logic (search.py:542-556) is the new code path; its only coverage is a string equality against a fake. A future edit to the parenthesization/join would pass the string assertion if updated in lockstep, but a real-execution test is what catches a LanceDB-rejects-this-syntax regression.
- **Proposed fix:** Add a case to `tests/test_store.py::TestSourceKindPrefilter` that runs `tbl.search(qv).where("(paper_id IN ('textbook:sv-book')) AND (source_kind = 'textbook')", prefilter=True)` against the mixed corpus and asserts only the matching chunk returns, plus an empty-intersection case (paper_id of the arxiv chunk AND source_kind=textbook → 0 rows).
- **Regression guard:** The real-LanceDB combined-predicate test above.

### F5 — NULL source_kind → "arxiv" fallback in `_arrow_to_rows` is untested

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/handlers/search.py:805
- **What:** `_arrow_to_rows` emits `"source_kind": sk if sk is not None else "arxiv"`. The FM-7 fixture `_make_arrow_table` (test_search_filter.py:167) defaults source_kind to `"arxiv"` and no test ever passes `source_kind=None`, so the defensive `is not None else "arxiv"` branch has zero coverage.
- **Why it matters:** The fallback exists precisely for the case it isn't tested for (a legacy NULL row slipping past the m2 backfill). If a future edit changed the fallback (e.g. to `"unknown"`, or removed it causing the `additionalProperties:false`/`required` schema to reject the row), no test would catch it. Latent, off the common path (m2 backfills NULLs to "arxiv"), hence MEDIUM not HIGH.
- **Proposed fix:** Add `tests/test_search_filter.py` case feeding `_make_arrow_table([{... "source_kind": None}])` through `_arrow_to_rows` and asserting the row's `source_kind == "arxiv"`. ~6 LOC.
- **Regression guard:** The NULL-row test above pins the documented fallback semantics.

### F6 — BM25 source_kind is inferred from chunk_id prefix, decoupled from the authoritative column

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/retrieval/bm25.py:664 (_source_kind_from_chunk_id) + ingest/store.py:506
- **What:** The dense path filters on the authoritative `source_kind` COLUMN; the BM25 path infers source_kind from the chunk_id PREFIX (`arxiv:`/`textbook:`). These are independent: `write_chunks` (store.py:506) writes `chunk.source_kind` as its own column with no cross-check against the chunk_id prefix. A chunk written with a `textbook:`-prefixed id but `source_kind="arxiv"` (or vice versa, via a chunker bug) would be classified differently by the two paths.
- **Why it matters:** Two retrieval paths disagreeing on the same chunk's corpus origin is a latent correctness foot-gun. It is OFF the common path today: search_papers is dense-only at v1 (tool description: "the BM25 + RRF hybrid path lands in E07"), so the BM25 branch is supplementary/future. Hence MEDIUM, not HIGH — but it should be acknowledged so E07 hybrid wiring doesn't ship the divergence silently.
- **Proposed fix:** Add a write-time invariant in `ingest/store.write_chunks` (store.py:453 area) that the chunk_id prefix matches source_kind (`textbook:` ⇔ "textbook"; otherwise "arxiv"), raising `ValueError` on mismatch (mirrors the existing `_ALLOWED_SOURCE_KINDS` guard — use `if … raise`, never `assert`). This makes the prefix a guaranteed-reliable proxy so the BM25 inference and the dense column can never disagree. If deferred, record a note that E07 hybrid wiring must reconcile the two before activating.
- **Regression guard:** A `tests/test_store.py` case asserting `write_chunks` rejects a chunk whose chunk_id prefix and source_kind disagree.

### F7 — Stale docstring on bm25 SUPPORTED_FILTER_KEYS contradicts its own value

- **Severity:** LOW
- **Source:** adversary
- **File:** server/retrieval/bm25.py:114
- **What:** The docstring above `SUPPORTED_FILTER_KEYS` (bm25.py:114-116) still reads "v1 we honor only `paper_id`" while the value on line 117 is now `frozenset({"paper_id", "source_kind"})`.
- **Why it matters:** Minor doc-drift; a reader trusting the docstring would miss source_kind support. No behavior impact. (The mirror docstring in search.py:246-248 was correctly updated.)
- **Proposed fix:** Edit the bm25.py:114-116 docstring to name source_kind as honored (m9 / e4), matching the search.py mirror.
- **Regression guard:** None required (docstring-only); defer.

## What was done well

- Cache discipline is textbook-correct: TOOL_SCHEMA_VERSION 13→14, EXPECTED_TOOL_SCHEMA_SHA256, EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH (14), both result-schema JSONs, and the lean_verify global-echo all moved in one coordinated commit; re-running the suite confirms all pins are stable.
- The implementer CAUGHT and CORRECTED the synthesis's wrong claim that EXPECTED_BP1_SHA256 was unaffected (research-synthesis.md:24), re-pinned BP1 in lockstep, and documented the deviation honestly in implementation-summary.md:52-53 — exactly the right response to a bad upstream assumption.
- SQL-injection defense is sound and well-commented: the `{arxiv, textbook}` whitelist (search.py:235-240) fires BEFORE any string interpolation on every path, and the combined predicate independently validates each clause via its own builder.
- The single-clause `.where()` path is verified byte-identical to pre-m9 (test_search_filter.py:348 still asserts the unparenthesized `paper_id IN (...)` form), so existing paper_id-only behavior and any cached predicate shape do not drift.
- The result schema correctly locks the new field: `required` includes source_kind and `additionalProperties:false` (search_papers_result.json:75) keeps structuredContent a closed, well-formed contract.
- The snippet-contract doc was updated in lockstep (snippet-contract.md §m2-columns), avoiding the doc-drift class — and it precisely scopes which m2 columns do/don't surface.
- The capability-vs-demo split is honestly diagnosed: both research briefs and the summary correctly establish that no textbook→notebook-LanceDB driver exists, rather than papering over an unachievable demo (the descope reasoning is traced to the real input contract, the right adversary-verified posture).
- No banned patterns: zero `assert` in production diff, no BaseHTTPMiddleware, no anthropic import, no 0.0.0.0, no fork, ruff clean on all changed files.
- Test count is plausible and green for the feature: +247 passing in the touched files; the only 3 suite failures are pre-existing/environmental (latexmlc SIGABRT, stale Kùzu dir) in files m9 never touched.

## Recommended rectification order

1. F1 (HIGH, process) — file the follow-up issue and record the number; cheap, unblocks an honest e4 closure. Phase-4 main-thread `gh` operation, per-event authorized.
2. F2 (HIGH, test) — add the under-fill test; this is the load-bearing regression guard for the milestone's central design claim. Independent of F3/F4.
3. F3 (MEDIUM, doc-accuracy + re-pin) — fix the filters Field description; do it BEFORE any other schema-touching change so the coordinated re-pin happens once. Re-pins both hashes.
4. F4 + F5 (MEDIUM, test) — add real-LanceDB combined-predicate test and the NULL-fallback test; both small, both in already-touched test files, no interdependency.
5. F6 (MEDIUM, latent) — add the write-time prefix⇔column invariant OR record an explicit E07-hybrid reconciliation note; low blast radius.
6. F7 (LOW) — defer; fix opportunistically alongside F3 since both are description edits.

## Rectification status

All 7 findings addressed (0 invalidated). Verdict closed: 2 HIGH + 4 MEDIUM fixed, 1 LOW fixed (not deferred).

| ID | Severity | Disposition | Evidence |
|---|---|---|---|
| F1 | HIGH | FIXED (process) | Filed [chris-dare-dev/arXMCP#8](https://github.com/chris-dare-dev/arXMCP/issues/8); recorded in implementation-summary.md §"Out of scope". e4 now closes with the deferral tracked, not lost. |
| F2 | HIGH | FIXED | `tests/test_store.py::TestSourceKindPrefilter::test_underfill_prefilter_recovers_textbook` — 20 arxiv chunks hugging the query (e_0) + 1 textbook chunk orthogonal (e_1); `.limit(5)` excludes textbook from the unfiltered top-k; pre-filter recovers it. Fails iff pre-filter degrades to post-filter. |
| F3 | MEDIUM | FIXED + re-pin | `filters` Field description (search.py) + handler docstring now name `source_kind`. Required `TOOL_SCHEMA_VERSION` 14→15 (the `--update-tool-schema-hash` guard hard-refuses an in-place re-pin), cascaded to both result-schema JSONs + lean_verify cross-check. EXPECTED_TOOL_SCHEMA_SHA256 re-pinned (`b03e965d…`). **BP1 was NOT re-pinned — verified empirically it does not drift** (BP1 hashes only `{name, description}` per tool at test_prompts.py:464; the Field description lives in the inputSchema and the version in per-tool `_meta`, neither in the BP1 region). The adversary's "re-pins both hashes" was wrong on this point. Guard: `test_filters_field_description_names_source_kind`. |
| F4 | MEDIUM | FIXED | `TestSourceKindPrefilter::test_combined_paper_id_and_source_kind_real_lancedb` + `test_combined_predicate_empty_intersection` — the parenthesized-AND predicate now executes on a real LanceDB (not just string-asserted against the fake) + the AND truly intersects. |
| F5 | MEDIUM | FIXED | `tests/test_search_filter.py::test_arrow_to_rows_null_source_kind_falls_back_to_arxiv` — feeds a real NULL column value through `_arrow_to_rows`, pins the `"arxiv"` fallback. |
| F6 | MEDIUM | FIXED | Write-time invariant in `ingest/store.write_chunks` raises `ValueError` when the chunk_id prefix and source_kind column disagree (so dense-column and BM25-prefix paths can never diverge). Guards: `tests/test_store.py::TestWriteChunksPrefixInvariant` (3 cases). |
| F7 | LOW | FIXED | `server/retrieval/bm25.py` SUPPORTED_FILTER_KEYS docstring now names `source_kind` (bundled with F3 per the adversary's recommended order). |

**Test delta:** 3074 → 3082 passing (+8 rect tests). 3 pre-existing/environmental failures unchanged (latexmlc SIGABRT ×2, Kùzu cite_neighbors stale-dir ×1) — all in files m9 never touched. ruff clean.

**Adversary invalidation rate:** 0/7 (all findings were valid; F3's "re-pins both hashes" sub-claim was the only inaccuracy, corrected during rectification — the finding itself stands).
