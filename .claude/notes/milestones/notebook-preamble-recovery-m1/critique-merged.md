# Critique — notebook-preamble-recovery-m1 (merged)

**Critics:** adversary, infra-safety
**Generated:** 2026-05-28 (post-Phase 3 merge)
**Commit range:** `aec46ce7d1b5a93e00170d61ee58c1f966dec48e..be1a3ffb12c78a4e9585cd692043775de19b41ea`
**Merged verdict:** SHIP-WITH-FIXES

## Executive summary (orchestrator voice)

- SHIP-WITH-FIXES. The fetch path itself is correct — paper_id is validated upstream of any path construction (Threat-1 surface clean), Threat-7 100 MB cap inherits cleanly, AC5 chunk_id sensitivity is preserved, X-1/X-2 BP1 SHAs unchanged. One HIGH defect compromises the back-fill's resilience contract.
- Finding counts: **0 CRITICAL, 1 HIGH, 5 MEDIUM, 4 LOW (10 total)**.
- Adversary: 8 findings (F1 HIGH; F2/F3/F4/F5 MEDIUM; F6/F7/F8 LOW). Infra-safety: 2 findings (IS1 MEDIUM; IS2 LOW). Cross-critic agreement: none — orthogonal coverage.
- **F1 (HIGH)** is the headline defect: `_fetch_raw_tex_with_503_backoff` only catches `urllib.error.HTTPError`. A tarball-bomb `RuntimeError`, `URLError` (DNS), `OSError` (disk), or `tarfile.TarError` aborts the entire 137-paper back-fill mid-loop. Contradicts the function's own docstring contract.
- F2, F4, F5, F7, IS1 are tractable in single-line / single-block fixes; cluster naturally with F1's rectification.
- F6, F8, IS2 are LOW (deferred per protocol).
- F3 (no integration test for real `extract_preamble`) is MEDIUM; the fix is one ~30-LOC test that anchors AC2 against future refactors.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement

None — adversary covered code surface; infra-safety covered Makefile. Orthogonal as expected.

## Findings (preserved IDs, by severity)

### F1 — back-fill loop aborts on non-HTTPError fetch exceptions (HIGH)
- **Source:** adversary
- **File:** `tools/recover_preambles.py:128-152`
- **What:** Only `urllib.error.HTTPError` is caught. RuntimeError / URLError / OSError / tarfile.TarError / gzip.BadGzipFile from `fetch_eprint` propagate up through `run()` and abort the loop. Contradicts the docstring contract `never raises on per-paper failures`.
- **Fix:** widen the envelope to match `_notebook_common.py::fetch_raw_tex_if_missing`. Map RuntimeError to a new `"security_event"` outcome (vs `"other_error"`) so the summary surfaces it distinctly.
- **Regression guard:** new test `test_recover_preambles_continues_past_tarball_bomb`.

### F2 — `RuntimeError` always logged as "SECURITY EVENT" (MEDIUM)
- **Source:** adversary
- **File:** `tools/_notebook_common.py:218-225`
- **What:** Helper catches RuntimeError unconditionally and logs as "SECURITY EVENT". `fetch_eprint` raises RuntimeError from THREE sites: path-traversal (security event) AND 100 MB Content-Length cap (DoS reject). Both get mis-categorized.
- **Fix:** branch on message prefix (`"outside dest"` → ERROR + SECURITY EVENT; `"too large"` / `"cap exceeded"` → WARNING + oversized).

### F3 — no integration test exercising real `extract_preamble` (MEDIUM)
- **Source:** adversary
- **File:** `tests/tools/test_notebook_scripts.py`
- **What:** Every back-fill test mocks `extract_preamble` to a lambda. The AC2 promise "raw_tex_fetched → preamble.json written" has no in-repo regression guard.
- **Fix:** add `test_recover_preambles_real_extract_preamble_end_to_end` that writes a synthetic `.tex` with a real macro, monkeypatches `ingest.preamble.RAW_DIR` + `PREAMBLE_DIR` to tmp_path, calls the back-fill, asserts the macro appears in the recovered `preamble.json`.

### F4 — autouse fixture default mask is invisible to future test authors (MEDIUM)
- **Source:** adversary
- **File:** `tests/tools/test_notebook_scripts.py:35-49`
- **What:** `_default_notebook_fetch_env` autouse silently no-ops `fetch_raw_tex_if_missing` for every test in the file. A future integration test would silently get the mock.
- **Fix:** rename to `_autouse_safety_net_mock_raw_tex_fetch` + add a prominent docblock comment that grep will find.

### F5 — operator-followup.md cross-reference doesn't enumerate AC3 + AC6 (MEDIUM)
- **Source:** adversary
- **File:** `.claude/notes/milestones/embedder-truncation-m1/operator-followup.md:54-87`
- **What:** AC3 (≥90% recovery) and AC6 (`get_definitions` canary) are operator-deferred but the tracker doesn't enumerate them as checklist items. Same failure mode as F7 of embedder-truncation-m1.
- **Fix:** add explicit "AC3 — recovery rate ≥ 90%" and "AC6 — `get_definitions` canary" sections with operator checklists.

### F6 — `_fetch_raw_tex_with_503_backoff` MAX cap log misleading (LOW)
- **Source:** adversary
- **File:** `tools/recover_preambles.py:126-147`
- **What:** Log line says `cap %.0fs` displaying 300 as the cap, but effective max retry wait is 240s. Misleading; doc-only fix.
- **Deferred:** LOW.

### F7 — idempotency gate misses subdir-only `.tex` layouts (LOW → fixed because cheap)
- **Source:** adversary
- **File:** `tools/_notebook_common.py:191-196` + `tools/recover_preambles.py:98-101`
- **What:** `glob("*.tex")` (top-level only) misses tarballs with .tex only in subdirs. `_select_root_tex` handles those via recursive fallback; the gate doesn't.
- **Fix:** `glob` → `rglob` in both sites (2 LOC). Regression: `test_fetch_raw_tex_helper_idempotent_with_subdir_tex`.

### F8 — `tests/tools/test_notebook_scripts.py` file size + cohesion (LOW)
- **Source:** adversary
- **File:** `tests/tools/test_notebook_scripts.py` (1050+ lines)
- **What:** File covers four script surfaces. Style only.
- **Deferred:** LOW; revisit at 1500 lines.

### IS1 — operator WARNING on chunk_id rotation hidden from `make help` (MEDIUM)
- **Source:** infra-safety
- **File:** `Makefile:159-163`
- **What:** Warning lives in `@#` comment block, not in `@echo` help output.
- **Fix:** add a second `@echo` line under `ingest-recover-preambles` summarizing the consequence.

### IS2 — help line column alignment (LOW)
- **Source:** infra-safety
- **File:** `Makefile:18`
- **What:** Description column misaligned. Style only.
- **Deferred:** LOW.

## Recommended rectification order

1. **F1** (HIGH) — back-fill exception envelope. Highest blast radius.
2. **F2** — disambiguate RuntimeError logging (same file region as F1; do together).
3. **F3** — add real-extract-preamble integration test (anchors AC2).
4. **F4** — rename autouse fixture + add docblock comment (test-architecture hardening).
5. **F5** — add AC3 + AC6 enumeration to operator-followup.md (doc).
6. **IS1** — second `@echo` line under `ingest-recover-preambles`.
7. **F7** — `glob` → `rglob` (LOW but cheap; fold in).
8. **F6, F8, IS2** — defer per protocol.

## Rectification status

Re-verify gate: 1/1 HIGH finding (F1) re-verified at the cited file:line ± 30 lines; not invalidated.

- F1 — fixed in `tools/recover_preambles.py::_fetch_raw_tex_with_503_backoff` (envelope widened to URLError + RuntimeError + OSError + TarError + BadGzipFile; new `security_event` outcome bucket; new `RecoverySummary.security_events` list). Regression guard: `tests/tools/test_notebook_scripts.py::test_recover_preambles_continues_past_tarball_bomb` + `test_recover_preambles_continues_past_url_error`.
- F2 — fixed in `tools/_notebook_common.py::fetch_raw_tex_if_missing` (RuntimeError now message-branched: `"outside dest"` → ERROR + SECURITY EVENT; `"too large"`/`"cap exceeded"` → WARNING + oversized; otherwise ERROR + unexpected). Regression guard: `tests/tools/test_notebook_scripts.py::test_fetch_raw_tex_helper_oversize_runtime_error_not_security_event`.
- F3 — fixed by adding `tests/tools/test_notebook_scripts.py::test_recover_preambles_real_extract_preamble_end_to_end` which writes a synthetic `\newcommand` and asserts it appears in the recovered `preamble.json` via the real `ingest.preamble.extract_preamble`.
- F4 — fixed in `tests/tools/test_notebook_scripts.py` (autouse fixture renamed `_autouse_safety_net_mock_raw_tex_fetch`; added 22-line SAFETY-NET docblock above the fixture pointing future authors at the override pattern). Grep-discoverable on both `autouse_safety_net` and `mock_raw_tex_fetch`.
- F5 — fixed in `.claude/notes/milestones/embedder-truncation-m1/operator-followup.md` (added "## 3. AC3 explicit operator deliverable" + "## 4. AC6 `get_definitions` canary" sections, each with 5-6 step operator checklists).
- F7 — fixed in `tools/_notebook_common.py` + `tools/recover_preambles.py` (`glob` → `rglob` in both sites). Regression guard: `tests/tools/test_notebook_scripts.py::test_fetch_raw_tex_helper_idempotent_with_subdir_tex`.
- IS1 — fixed in `Makefile` (second `@echo` line under `ingest-recover-preambles` in the `help` target advertising the chunk_id-rotation follow-up).
- F6 — deferred (LOW; doc-only log-line fix; tracked).
- F8 — deferred (LOW; test-file cohesion; revisit at 1500+ lines).
- IS2 — deferred (LOW; help-column alignment; revisit if Makefile gets a sweep).

Invalidation rate: 0/1 HIGH = 0%; adversary critic prompt healthy.
