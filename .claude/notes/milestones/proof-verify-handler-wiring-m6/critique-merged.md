# Critique (merged) — proof-verify-handler-wiring-m6

**Critics dispatched:** adversary only (infra-safety SKIPPED — no `infra/`, `Makefile`, `Dockerfile`, or workflow paths touched; oss-scout NOT requested by user and synthesis did not flag this as an active OSS research area).

**Verdict:** **DO-NOT-SHIP** (per adversary).

**Generated:** 2026-05-21T00:00:00Z
**Commit range:** `0555ea2..b4e5dd53562bfd18861e4a582fb2e6f5f2fac828`

## Unified executive summary (orchestrator voice)

The implementation cleanly addresses the synthesis's documented failure modes for the **happy paths** (slug regex, set-difference uniqueness, delegation to `try_cache`, etc.) but the adversary uncovered three load-bearing security gaps that the synthesis named but the implementation did not fully close:

1. **F1 (CRITICAL)** — `notebook_purge.py` can `shutil.rmtree` arbitrary host directories via a malformed `papers.txt` entry. The synthesis FM-1 mitigation (set difference) is implemented but the synthesis FM-5 mitigation (validate paper_ids via `is_valid_paper_id`) was NOT applied to the purge path — only to the fetch path. This is the kind of asymmetric defense that ships and then ships again the bug.
2. **F2 (HIGH)** — The implementer's documented deviation #1 ("BM25 global path, per-notebook corpus_version makes `v<N>` implicitly per-notebook") is **wrong**. Per-notebook `corpus_version` is unique only WITHIN one notebook; across notebooks it collides. Second notebook's BM25 build silently no-ops; the script reports success; the operator sees a notebook serving the wrong index's chunk_ids.
3. **F3 (HIGH)** — Symlink at `var/arxmcp/notebooks/safe-slug -> /etc/` defeats `notebook_dir()`'s containment check because both sides resolve through the symlink. Synthesis FM-2 named this; the implementation's regex-then-relative_to defense doesn't cover it.

Three MEDIUM (F4-F6) and two LOW (F7-F8) findings round out the critique. The MEDIUMs are individually cheap; the LOWs are deferrable.

## Counts and severity calibration

| severity | count | rectification phase action |
|---|---|---|
| CRITICAL | 1 | always fix in Phase 4 |
| HIGH | 2 | always fix in Phase 4 |
| MEDIUM | 3 | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | 2 | defer (record under `deferred_findings`) |

Implementer's invalidation prediction (per `implementation-summary.md`'s "What needs Phase 3 critique attention" section): they flagged `notebook_purge.py` security, the set-difference trade-off, and the pdf-deferred WARN as worth scrutiny. The adversary independently surfaced F1 (purge security) and F2 (BM25 path) — strong corroboration. F3 (symlink) was NOT pre-emptively flagged.

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings (verbatim from adversary; severity-grouped)

### F1 — purge can rmtree outside corpus via malformed papers.txt

- **Severity:** CRITICAL
- **Source:** adversary
- **File:** `tools/notebook_purge.py:110-122` (`_purge_corpus_assets`) and `tools/notebook_purge.py:80-107` (`_compute_unique_paper_ids`)
- **What:** `_compute_unique_paper_ids` reads `papers.txt` via `read_paper_ids_from_papers_txt` which intentionally does NOT validate against `is_valid_paper_id`. The purge caller never performs that validation. `_purge_corpus_assets` then does `target = base_dir / paper_id; if target.is_dir(): shutil.rmtree(target)`. A line like `../../../home/user/important` resolves to a directory outside the corpus tree and gets deleted.
- **Proposed fix:** Validate paper_ids via `is_valid_paper_id` BEFORE the set difference. Add belt-and-braces containment in `_purge_corpus_assets` via `target.resolve().relative_to(base_dir.resolve())`.
- **Regression guard:** `test_purge_corpus_too_rejects_malformed_paper_ids` — seed `papers.txt` with `"../../tmp/victim"`, create sentinel in `tmp_path`, assert sentinel untouched.

### F2 — BM25 path collision across notebooks silently corrupts search

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tools/notebook_ingest.py:127-137` collides with `ingest/bm25_indexer.py:104, 313`
- **What:** `build_bm25_index` writes to GLOBAL `BM25_INDEX_ROOT / v<corpus_version>/`. Notebook A's v1 build is silently skipped on notebook B's v1 build via the idempotent gate. Notebook B then serves notebook A's stale BM25 chunk_ids.
- **Proposed fix:** Write a `.slug` sentinel file in `v<N>/`; on subsequent build, if the sentinel's slug differs from the current slug, raise `NotebookError` instructing operator to either purge the prior notebook or pass an override flag.
- **Regression guard:** `test_ingest_detects_bm25_collision` — monkeypatch `BM25_INDEX_ROOT`, ingest slug A then slug B both at v1, assert second call raises.

### F3 — notebook_dir() containment check is not effective against symlink attack

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tools/_notebook_common.py:68-94` (`notebook_dir`)
- **What:** Slug regex rejects `../escape` but not the case where `var/arxmcp/notebooks/safe-slug` IS a symlink to `/etc/`. Both `nb_base` and `target` resolve through the symlink; `relative_to` passes; purge then operates on the symlink target.
- **Proposed fix:** After containment check, if `target.exists() and target.is_symlink()`, raise `NotebookError("notebook path is a symlink — refusing for safety")`.
- **Regression guard:** `test_notebook_dir_rejects_symlink` — `Path(nb_base / "safe-slug").symlink_to(other_dir)`, assert `notebook_dir("safe-slug")` raises.

### F4 — fetch's > 1024-byte cache-hit heuristic admits corrupt HTML

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/notebook_fetch.py:84-87`
- **What:** Bare size heuristic accepts any 1025+-byte file regardless of content. Manually-dropped invalid file or half-written file from a crashed pre-m6 run counts as cache hit; chunker downstream produces empty/corrupt output with no signal at the fetch step.
- **Proposed fix:** Drop the size heuristic; always call `try_cache` (it has its own hit-detection that includes the `<math` check). Optionally suppress sleep when `try_cache` reports it was a local-cache hit (no fetch happened).
- **Regression guard:** `test_fetch_does_not_short_circuit_corrupt_parsed_file` — seed parsed_path with 2 KB HTML lacking `<math>`; assert script flags as missing not from_cache.

### F5 — _gather_pdf_deferred_warnings crashes on non-dict manifest.json

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/notebook_purge.py:64-71`
- **What:** If manifest.json parses to a non-dict (e.g. `[1,2,3]`), `data.get("manual_titles")` raises `AttributeError`. The except clause catches `OSError, JSONDecodeError` but not `AttributeError`. Aborts the purge with an unhandled traceback.
- **Proposed fix:** `titles = (data if isinstance(data, dict) else {}).get("manual_titles") or {}` and validate `isinstance(titles, dict)`.
- **Regression guard:** `test_purge_warns_about_pdf_deferred_with_non_dict_manifest` — seed manifest with `"[1,2,3]"`, assert purge proceeds (rc=0) without traceback.

### F6 — typed-slug confirmation: EOFError catch is dead code

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/notebook_purge.py:185-189`
- **What:** `file.readline()` returns `""` on EOF, not `EOFError`. The except clause for EOFError never fires; instead the empty string falls through to `if typed != slug` and prints `aborted: typed '', expected 'demo'` — misleading diagnostic.
- **Proposed fix:** Replace with `if not typed: print("aborted (EOF or empty input)", file=sys.stderr); return 2`.
- **Regression guard:** `test_purge_aborts_cleanly_on_eof` — pass `io.StringIO("")`, assert rc=2 and stderr says "aborted" not "typed ''".

### F7 — FM-7 (stale BM25) coverage punted to indexer tests without integration

- **Severity:** LOW
- **Source:** adversary
- **File:** `tools/notebook_ingest.py` (absence of integration)
- **What:** Synthesis FM-7 said `notebook_ingest.py` should log a warning if multiple `v<N>` directories exist for a notebook's lancedb. The implementation skipped this; the indexer's own tests don't cover it.
- **Proposed fix:** After `build_bm25_index` returns, glob `BM25_INDEX_ROOT/v*`; if `len > 1`, log a `WARN` suggesting `notebook_purge.py --purge-corpus-too` to prune.
- **Regression guard:** `test_ingest_warns_about_stale_bm25_versions` — mock BM25_INDEX_ROOT with v1, v2, v3; assert WARN appears.

### F8 — notebook_init race on parallel invocation

- **Severity:** LOW
- **Source:** adversary
- **File:** `tools/notebook_init.py:89-92`
- **What:** TOCTOU between `nb_dir.exists()` and `mkdir(exist_ok=False)`; parallel invocations of `notebook_init.py same-slug` race, the loser gets a raw `FileExistsError` traceback instead of clean `NotebookError`.
- **Proposed fix:** Wrap `mkdir` in `try/except FileExistsError`, treat as idempotent skip.
- **Regression guard:** None required (single-operator workflow); defensive UX only.

## What was done well (verbatim from adversary)

- Slug regex `^[a-z][a-z0-9-]{2,30}$` correctly applied as first action in every script's `run()` entry point.
- `run_bulk_ingest` integration uses the right kwargs; implementer correctly caught the brief's `ARXMCP_LANCEDB_PATH` error.
- Synthesis-prescribed FM coverage table is honest; implementer explicitly flagged FM-7 as not directly tested.
- 35 tests all pass; test file's docstring maps each test to AC/FM.
- All four scripts cleanly separate `run()` (pure-function, testable) from `main()` (argparse + sys.exit).
- No `assert` statements in production scripts (CLAUDE.md §4.7 compliance clean).
- Tests use `tmp_path` everywhere; no live `var/arxmcp/` writes.
- Delegating ar5iv fetches to `try_cache` is the right call — inherits 100 MB cap, 429/503 handling, etc.
- `NotebookError(RuntimeError)` subclass honors invariant-as-runtime-check discipline.
- `_compute_unique_paper_ids` correctly uses set difference (not `os.path.commonpath`).

## Recommended rectification order

1. **F1 (CRITICAL).** Highest leverage, smallest blast radius. ~15 LOC + 1 test. Closes arbitrary directory deletion.
2. **F2 (HIGH).** ~20 LOC for the slug-sentinel guard + 1 test. Updates docstring to remove the wrong "version-integer separation is sufficient" claim.
3. **F3 (HIGH).** ~5 LOC symlink check + 1 test.
4. **F4 (MEDIUM).** Remove size heuristic + 1 test.
5. **F5 + F6 (MEDIUM × 2).** Bundle: isinstance check + EOF handling. ~10 LOC total + 2 tests.
6. **F7 (LOW) + F8 (LOW).** Defer if Phase 4 is time-pressed. F7 worth doing for synthesis-promise fidelity; F8 is defensive UX only.

## Cross-critic agreement

Only one critic fired (adversary). No cross-critic agreement to flag.

## Rectification status

- F1 (CRITICAL) — **fixed**. `_compute_unique_paper_ids` now validates paper_ids via `is_valid_paper_id` BEFORE the set difference (tools/notebook_purge.py:99-126); `_purge_corpus_assets` adds belt-and-braces containment check via `target.resolve().relative_to(base_dir.resolve())` (tools/notebook_purge.py:131-167). Regression guard: `tests/tools/test_notebook_scripts.py::test_purge_corpus_too_rejects_malformed_paper_ids`.
- F2 (HIGH) — **fixed**. `notebook_ingest.py` writes a `.notebook_slug` sentinel file to `BM25_INDEX_ROOT/v<N>/` on first build; subsequent builds detect cross-notebook collision and raise `NotebookError` with explicit recovery instructions (tools/notebook_ingest.py:128-156). Regression guards: `test_ingest_detects_bm25_collision`, `test_ingest_writes_slug_sentinel_on_first_build`.
- F3 (HIGH) — **fixed**. `notebook_dir()` rejects symlinks before resolving (tools/_notebook_common.py:84-92). Regression guard: `test_notebook_dir_rejects_symlink`.
- F4 (MEDIUM) — **fixed**. Removed the >1024-byte size heuristic in `notebook_fetch.py`; `try_cache` is now always called, with its `ok_local_cache` reason value distinguishing local cache hits from network fetches (tools/notebook_fetch.py:77-108). Politeness sleep only applies after actual network round-trips. Regression guard: `test_fetch_does_not_short_circuit_corrupt_parsed_file`; existing `test_fetch_happy_path` updated to mock `ok_local_cache`.
- F5 (MEDIUM) — **fixed**. `_gather_pdf_deferred_warnings` validates `isinstance(data, dict)` and `isinstance(raw_titles, dict)` before `.get(...)` (tools/notebook_purge.py:65-78). Regression guard: `test_purge_warns_about_pdf_deferred_with_non_dict_manifest`.
- F6 (MEDIUM) — **fixed**. Empty-string check after `readline()` produces "aborted (EOF or empty input)" message; `KeyboardInterrupt` retained as a distinct catch (tools/notebook_purge.py:236-249). Regression guard: `test_purge_aborts_cleanly_on_eof`.
- F7 (LOW) — **fixed** (promoted from defer-eligible because the fix is ~10 LOC and aligns with synthesis FM-7 intent). After `build_bm25_index`, glob `BM25_INDEX_ROOT.glob("v*")`; warn if >1 directory exists (tools/notebook_ingest.py:158-167). Regression guard: `test_ingest_warns_about_stale_bm25_versions`.
- F8 (LOW) — **deferred** (TOCTOU race on parallel `notebook_init.py same-slug` invocations; defensive UX only, single-operator workflow makes impact low; recorded under `deferred_findings`).

Total fixed: 7 (1 CRITICAL + 2 HIGH + 3 MEDIUM + 1 LOW). Deferred: 1 LOW. Invalidated: 0 (all CRITICAL + HIGH still matched their cited regions at the re-verify gate).

Adversary invalidation rate: **0%** (0 of 3 CRITICAL+HIGH invalidated); critic prompt is calibrated correctly.

Project test count: 2203 passed (up from 2160 baseline; +43 m6 tests including 8 regression guards).

<!-- end rectification status -->
