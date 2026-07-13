# Critique — source-truth-m2 — merged (adversary + arxmcp)

**Critic:** milestone-adversary-critic + milestone-arxmcp-critic (orchestrator-merged, id-remapped)
**Commit range:** 880fcfd..ac0ff62
**Diff stats:** 8 files, 1825 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. **No CRITICAL or correctness defect survived** — both critics independently verified:
embedding byte-preservation (real `np.array_equal` test + lancedb-0.30.2 repro; 0 mismatches on the
15,106-row smoke), structural 0-re-embed (import-scan enforced), byte-stable `source_span`
(`json.dumps(sort_keys,separators)`, pure fn of stored `body_text`), safe-direction `truncated`
(proofs windowed), registry abstention on every 0/1/>1 cardinality (`license_status` NOT NULL so the
null-invariant holds), `_compute_chunk_id` untouched, and the `tools/list` BP1 pin intact. The
findings are **regression-test gaps** on the go-live-critical backfill (its real preamble round-trip
and migrate-then-hydrate composition are empirically validated by the scratch smoke but not by an
automated test) plus operational sharp edges (an idempotency freeze, minor hardening). H1 is the
mandated large-diff flag (owner-approved `allow_large_diff`).

## Executive summary

- [HIGH] Mandated review flag: 1825 LOC (>400). No defect; `allow_large_diff` approved; 240 tests + the 15,106-row smoke mitigate.
- [MEDIUM] M1: the HIT path's REAL `extract_preamble`→chunk_id round-trip is untested — every backfill test stubs `preamble=None`, so a preamble-resolution divergence would pass CI and surface only as a low `resolved=` count on the go-live report.
- [MEDIUM] M2: the driver's own `add_columns`→hydrate composition (the live 21→26-col go-live path) has no automated test — every test starts at the 26-col schema; validated only by the uncommitted smoke.
- [MEDIUM] M3: the `chunker_rerun_failed` abstention reason-code branch has no covering test.
- [MEDIUM] M4 (cross-critic: adversary L3 + arxmcp M1): the idempotency skip-gate keys on `source_revision_id`, so a registry-HIT + chunk-id-MISS row is frozen at `source_span=null` on every future run with no `--reattempt`; registry-missing papers conversely re-chunk every run — the "writes nothing" claim is overstated.
- [LOW] L1 printed-number regex fuses a trailing word-letter to a digit ("Corollary3"→"y3"), unreachable in real LaTeXML. L2 `_truncated_fallback` "airtight" docstring overstates BPE-boundary monotonicity. L3 `_V2_COLUMN_DEFAULTS` duplicates the store's map with no drift guard. L4 commit subject 51 chars.

## Findings

**H1 — Diff exceeds the 400-LOC review-quality threshold** (HIGH)
**Where:** no specific file · **Anchor:** `1825 LOC across 8 files`
**What:** 1825-LOC diff (8 files), above the 400-LOC HIGH line.
**Why it matters:** Large diffs lower per-line review density.
**Proposed fix:** No code change. `allow_large_diff` owner-approved; volume dominated by two test files (690 LOC) + a self-contained 736-LOC driver; 240 tests + the 15,106-row smoke (0 embedding mismatches on live data) mitigate. Record and proceed.
**Regression-guard:** N/A.
**Source critic:** milestone-adversary-critic · **Source axis:** Review quality / diff size

**M1 — HIT path's real preamble round-trip is never tested (all tests stub preamble to None)** (MEDIUM)
**Where:** `tools/notebook_chunks_backfill.py:691` · **Anchor:** `resolve_preamble = _resolve_preamble_doc`
**What:** Every test builds the table AND runs the backfill with `resolve_preamble=lambda _pid: None`, so chunk_ids match by construction; the production `_resolve_preamble_doc`→`extract_preamble` (the SOLE HIT-path dependency for `source_span`/`printed_number`) is exercised by no test.
**Why it matters:** If backfill-time preamble resolution diverges from ingest-time, `_compute_chunk_id` differs, every chunk MISSes, and `source_span` goes uniformly null. Not silent (the report shows `resolved=0`, and the go-live SAFETY gate catches it) — but a regression in `extract_preamble` reproducibility passes the whole CI suite. The 0-embedding-mismatch smoke says nothing about the resolved-rate (embeddings are preserved on a MISS too).
**Proposed fix:** Add a test with a NON-empty preamble (real `extract_preamble` seam or a stable `preamble_text`/`preamble_hash` doc) asserting the backfill reproduces chunk_ids and resolves `source_span` for the theorem rows. Separately, make the post-rectify go-live gate assert `resolved/rows >= <scratch-smoke threshold>`, not just embeddings-preserved.
**Regression-guard:** `tests/test_notebook_chunks_backfill.py::test_hit_path_with_real_preamble_roundtrip`
**Source critic:** milestone-arxmcp-critic · **Source axis:** Axis 8 — test surface

**M2 — Driver's add_columns→hydrate composition has no regression guard** (MEDIUM)
**Where:** `tools/notebook_chunks_backfill.py:532` · **Anchor:** `report.columns_added = _ensure_v2_columns`
**What:** Every backfill test builds via `write_chunks`/`CHUNKS_SCHEMA_V1` (already 26 cols), so `_ensure_v2_columns` always returns `[]`; the migrate-then-hydrate path (add 5 cols to a pre-v2 table, then hydrate in the same run) — the go-live scenario — is never exercised by a test.
**Why it matters:** If a future lancedb version left `table.schema`/`to_arrow()` stale after `add_columns`, `from_pylist(schema=table.schema)` would drop the 5 patched keys and `merge_insert` would silently no-op them — and since `_patch_notebook` increments `resolved` from in-memory decisions (not a post-write read-back), the report would print `resolved=N` while the columns persisted NULL. Verified correct on lancedb 0.30.2 + the smoke ran this exact path on the real pre-v2 table; this guards future regression.
**Proposed fix:** Add a test creating a genuine pre-v2 table (`pa.schema(list(CHUNKS_SCHEMA_V1)[:-5])`), write rows + synthetic embeddings, run `backfill.run(...)`, assert (a) `columns_added==5`, (b) the 5 columns hydrated non-null on a HIT paper via a table read-back, (c) embeddings `np.array_equal` pre/post.
**Regression-guard:** `tests/test_notebook_chunks_backfill.py::TestMigrateThenHydrate::test_pre_v2_table_migrated_and_hydrated_in_one_run`
**Source critic:** milestone-adversary-critic · **Source axis:** Acceptance coverage (AC1∩AC2 composition)

**M3 — `chunker_rerun_failed` abstention branch is uncovered** (MEDIUM)
**Where:** `tools/notebook_chunks_backfill.py:615` · **Anchor:** `elif rr.status == "rerun_failed":`
**What:** Of the four abstention reason codes, `chunker_rerun_failed` is the only one no test triggers (no test forces `_rechunk_paper` to raise a `PER_PAPER_FAILURE_EXCEPTIONS`).
**Why it matters:** A malformed parsed HTML on the live run hits this untested branch; AC3 is "un-anchorable → counted + reason-coded," and one reason code is unverified.
**Proposed fix:** Add a test patching `_rechunk_paper` (or feeding HTML that raises) to return `status="rerun_failed"`, asserting `chunker_rerun_failed=N` in the report, `source_span=null`, `truncated` still via fallback.
**Regression-guard:** `tests/test_notebook_chunks_backfill.py::test_rerun_failed_abstains`
**Source critic:** milestone-arxmcp-critic · **Source axis:** Axis 8 — test surface

**M4 — Idempotency skip-gate freezes source_span abstentions after revision resolves** (MEDIUM)
**Where:** `tools/notebook_chunks_backfill.py:549` · **Anchor:** `if all(row.get("source_revision_id") is not None ...`
**What:** The skip-gate keys on `source_revision_id`, set whenever the registry resolves — independent of whether `source_span`/`printed_number` resolved. So (a) a registry-HIT + chunk-id-MISS row is skipped forever at `source_span=null` with no `--reattempt`; (b) conversely, a `registry_missing` paper re-chunks + re-writes on every run (embeddings preserved). The docstring frames idempotency purely as "re-run writes nothing."
**Why it matters:** Near-zero live impact (m1 smoke showed `source_revision_id` 100%, chunk-id MISS ≈ near-zero), embeddings preserved either way — not a correctness bug, but the guarantee is weaker than documented and post-chunker-upgrade re-hydration has no path.
**Proposed fix:** Tighten the skip-gate to "all 5 columns resolved OR the abstention is provably terminal (unregistered/ambiguous)" rather than `source_revision_id` alone; tighten the docstring to match; optionally a `--reattempt-spans` flag (fast-follow). Minimal change (<30 LOC).
**Regression-guard:** `tests/test_notebook_chunks_backfill.py::test_span_null_rerun_reattempts_when_ids_reproduce` (+ a registry-missing re-run case).
**Source critic:** milestone-arxmcp-critic + milestone-adversary-critic · **Source axis:** Axis 8 / Idempotency

**L1 — printed-number regex fuses a trailing word-letter to a digit** (LOW)
**Where:** `ingest/chunker.py:123` · **Anchor:** `_PRINTED_NUMBER_RE = re.compile(r"([A-Za`
**What:** With no space between word and number the optional `[A-Za-z]?` captures the word's last letter ("Corollary3"→"y3"). Unreachable in real LaTeXML (always a space in the tag), but the extractor is new.
**Why it matters:** A malformed `printed_number` would be persisted verbatim; harmless today (LaTeXML always renders a space) but the new extractor deserves the one-anchor guard.
**Proposed fix:** Require a separator before the optional appendix letter (e.g. `(?:^|[\s(])` prefix) or post-filter a leading letter preceded by another letter. Add `test_no_space_before_number_declines`.
**Regression-guard:** `tests/test_chunker.py::TestPrintedNumberExtraction::test_no_space_before_number_declines`
**Source critic:** milestone-adversary-critic · **Source axis:** printed_number extraction

**L2 — `_truncated_fallback` "airtight" claim overstates boundary monotonicity** (LOW)
**Where:** `tools/notebook_chunks_backfill.py:241` · **Anchor:** `return count_tokens(body_text) >= STMT_MAX_TOKENS`
**What:** Re-tokenizing the boundary substring isn't guaranteed ≥ `max_tokens` (BPE merges at the cut can yield `max_tokens-1`), so the MISS-path fallback could rarely report a truncated stmt as complete. Only the advisory `truncated` column, negligible impact.
**Why it matters:** The "airtight" wording invites a future reader to over-trust the invariant; the mislabel is one-token, MISS-path-only, advisory-column-only.
**Proposed fix:** Soften the docstring ("safe-direction in the common case; a boundary re-tokenization can rarely undercount by one token"), or use `>= max_tokens - 1`. Docstring-only sufficient.
**Regression-guard:** optional.
**Source critic:** milestone-arxmcp-critic · **Source axis:** Axis 8

**L3 — Duplicated v2 default map has no drift guard** (LOW)
**Where:** `tools/notebook_chunks_backfill.py:143` · **Anchor:** `_V2_COLUMN_DEFAULTS: dict[str, str] = {`
**What:** `_V2_COLUMN_DEFAULTS` re-mirrors the 5 m2 entries of `ingest.store._TEXTBOOK_MIGRATION_DEFAULTS` (to keep the embedder out of the import graph) with nothing asserting they stay equal.
**Why it matters:** If a later milestone edits one column's cast SQL in only one map, the backfill's self-contained migration silently diverges from the store's. Low likelihood; cheap guard.
**Proposed fix:** A test importing both and asserting `backfill._V2_COLUMN_DEFAULTS == {k: _TEXTBOOK_MIGRATION_DEFAULTS[k] for k in backfill._V2_COLUMN_DEFAULTS}` (importing `ingest.store` in a TEST is fine).
**Regression-guard:** `tests/test_notebook_chunks_backfill.py::test_v2_defaults_match_store`
**Source critic:** milestone-arxmcp-critic · **Source axis:** Axis 7 — no-fork

**L4 — Commit 2572f2f subject is 1 char over the ≤50 convention** (LOW)
**Where:** no specific file · **Anchor:** `chunks schema v2 columns + printed-number extractor`
**What:** The `feat(ingest)` subject body is 51 chars, 1 over §4.3. Cosmetic; commit landed + signed.
**Why it matters:** Purely cosmetic; the commit is already landed + signed, so this is a note for future subjects, not a rebase trigger.
**Proposed fix:** No action on the landed commit (a rebase would break signatures/history for 1 char); note for future subjects.
**Regression-guard:** N/A.
**Source critic:** milestone-adversary-critic · **Source axis:** Commit hygiene

## What was done well

- **Embedding preservation is proven, not asserted** — `test_embeddings_bit_identical_pre_post` (`np.array_equal`) + an independent lancedb-0.30.2 repro; 0 mismatches on the 15,106-row smoke.
- **0-re-embed is genuinely STRUCTURAL** — the driver imports neither `ingest.store` nor `ingest.embedder` (even literalizes `CHUNKS_TABLE_NAME` to avoid the transitive `EMBEDDING_DIM` pull), enforced by an import-scan test. No forward pass can run.
- **`source_span` byte-stable + path-independent** — `json.dumps(sort_keys,separators)`, `txt` a pure fn of the stored `body_text` (NFC + whitespace-collapse), pinned by a byte-stability test.
- **Registry join abstains on every cardinality** — 0→`registry_missing`, >1→`ambiguous_multi_row_registry` (never a silent first-pick), 1→use; `license_ref` NULL exactly when `source_revision_id` NULL (invariant holds by `license_status NOT NULL`).
- **`truncated` safe-direction fallback** — proofs windowed → `False` correct-by-construction; the stmt branch can only over-flag, never under-report.
- **Re-chunk mirror faithful + read-only** — replicates `_chunk_paper_impl` pass order + `_compute_chunk_id` inputs + keep-first dedup, omits the per-chunk JSON write; reproduced 14,947/15,106 chunk_ids on real data.
- **Abstention first-class (§4.9)** — every miss counted, reason-coded, listed (capped 500) in a machine-parseable per-notebook report, with the spike-2 F2 sanity flag.
- **AC1 thoroughly tested** — migration, idempotency, nullability, type-match, existing-embedding byte-identity; the previously-dropped `truncated` now has a write→read round-trip guard.
- **Tier sequencing + surface** — no MCP tool / `get_chunk` field added (m5 owns surfacing), `EXPECTED_TOOL_SCHEMA_SHA256` untouched, consumes only m1's shipped registry.
- **Clean process hygiene** — both commits GPG-signed + `Co-Authored-By: Claude Opus 4.8`; no one-writer violation; no production `assert`-for-invariants; 240 tests pass.

Severity counts: C0 H1 M4 L4

## Recommended rectification order

M1, M2, M3, M4, L1, L3, L2, H1, L4
