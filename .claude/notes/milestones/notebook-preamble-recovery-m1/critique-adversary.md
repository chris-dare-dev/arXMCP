# Critique — notebook-preamble-recovery-m1

**Critic:** adversary
**Generated:** 2026-05-28T01:30:00Z
**Commit range:** `aec46ce7..be1a3ffb`
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES because the load-bearing fetch path is correct end-to-end (Threat-1/-7 surfaces inherited cleanly, paper_id validated upstream, AC5 hash sensitivity intact), but one HIGH finding compromises the back-fill's "never raises on per-paper failure" docstring contract.
- Findings: 0 CRITICAL, 1 HIGH, 4 MEDIUM, 3 LOW.
- Highest-risk file:line is `tools/recover_preambles.py:128-152` — `_fetch_raw_tex_with_503_backoff` catches ONLY `urllib.error.HTTPError`. A tarball-bomb `RuntimeError`, `tarfile.TarError`, or `gzip.BadGzipFile` from `fetch_eprint` will abort the back-fill mid-run, contradicting both `run()`'s docstring (`recover_preambles.py:183-186`) and AC4-style resilience.
- Cross-pattern: AC2 + AC3 + AC6 have NO integration test exercising the real `extract_preamble` → `preamble.json` chain; every back-fill test patches `extract_preamble` to a lambda.
- Cross-pattern: the autouse fixture `_default_notebook_fetch_env` (test file line 35-49) is invisible to future test authors — a `pytestmark` rather than autouse, or an explicit per-test `@pytest.mark.usefixtures(...)`, would surface the no-op default.
- Cross-pattern: the `RuntimeError`-as-"SECURITY EVENT" label in `_notebook_common.py:218-225` over-claims — `_extract_eprint_response` also raises `RuntimeError` for the 100 MB Content-Length cap, which would be mis-logged as a path-traversal event.
- AC3 + AC6 are operator-deferred (defensible per the embedder-truncation-m1 precedent), but the cross-referenced tracker (`embedder-truncation-m1/operator-followup.md`) does NOT enumerate them as explicit checklist items — only mentions running the back-fill.
- 11 new tests + 1 autouse fixture, all green; ruff clean. The real fetch path is correct; the back-fill's exception-envelope tightness is the one place a real operator run will trip.

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

### F1 — back-fill loop aborts on non-HTTPError fetch exceptions

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tools/recover_preambles.py:128-152`
- **What:** `_fetch_raw_tex_with_503_backoff` wraps `fetch_eprint` in `try / except urllib.error.HTTPError`. `fetch_eprint` (`tools/arxiv_fetch.py:234-297`) can also raise `RuntimeError` from `_safe_extract` (path-traversal, line 343), `RuntimeError` from the 100 MB Content-Length cap (lines 275, 281), `tarfile.TarError` (caught internally by `_extract_eprint_response`, but `tarfile.ExtractError` from `extractall` line 346 escapes), `OSError` (disk), `urllib.error.URLError` (DNS / connection-reset, NOT an HTTPError subclass), and `socket.timeout`. None of these are caught here. They propagate up through `run()`'s for-loop (`recover_preambles.py:200-233`) which only catches `PER_PAPER_FAILURE_EXCEPTIONS` around `extract_preamble` (line 230) — NOT around the fetch. A single tarball-bomb on paper 7 of 137 aborts the entire back-fill, leaving 130 papers un-recovered.
- **Why it matters:** Contradicts `run()`'s explicit docstring contract (`recover_preambles.py:183-186`): "never raises on per-paper failures (404, 503, etc.) — those are logged and aggregated." Also contradicts the `_notebook_common.py::fetch_raw_tex_if_missing` exception envelope (`_notebook_common.py:179-189`) which DOES catch the full set. The back-fill path is asymmetrically less robust than the per-paper notebook path it was supposed to mirror. The synthesis explicitly called out this exception envelope ("FM-1 through FM-7"); the back-fill loop dropped the envelope when it bypassed the helper.
- **Proposed fix:** Wrap `fetch_eprint(...)` at `recover_preambles.py:129` in the same exception envelope the helper uses: `except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError, OSError, tarfile.TarError, gzip.BadGzipFile)`. Map RuntimeError to `"security_event"` outcome (vs `"other_error"`) so the summary surfaces it distinctly. Add diff sketch:
  ```python
  except urllib.error.HTTPError as exc:
      ...  # existing
  except RuntimeError as exc:
      logger.error("[%s] SECURITY EVENT or oversize: %s", paper_id, exc)
      return "security_event"
  except (urllib.error.URLError, OSError, tarfile.TarError, gzip.BadGzipFile) as exc:
      logger.warning("[%s] fetch failed: %s", paper_id, exc)
      return "other_error"
  ```
- **Regression guard:** New test `test_recover_preambles_continues_past_tarball_bomb` — three candidate papers, `fetch_eprint` raises `RuntimeError("refusing to extract path outside dest")` on the second, asserts (a) `run()` does not raise, (b) all three are attempted, (c) summary.other_fetch_errors (or new `security_events`) contains the second paper, (d) the first and third are still processed.

### F2 — `RuntimeError` always logged as "SECURITY EVENT" even for 100 MB-cap rejections

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/_notebook_common.py:218-225`
- **What:** The helper catches `RuntimeError` and logs `[%s] raw_tex: SECURITY EVENT during tarball extraction: %s`. But `fetch_eprint` raises `RuntimeError` from THREE distinct sites in `tools/arxiv_fetch.py`: (a) `_safe_extract` line 343 (path traversal — real security event), (b) `_extract_eprint_response` line 275 (`Content-Length > MAX_RESPONSE_BYTES` — DoS-bound, also a security event but different kind), (c) `_extract_eprint_response` line 281 (`cap exceeded mid-read` — same DoS surface). All three are mis-categorized as "SECURITY EVENT during tarball extraction" even when the offender is an oversized HTTP response that never got to the extraction stage.
- **Why it matters:** Mis-labeled security telemetry hampers operator investigation per `.claude/notes/08-security-observability-ops.md` Threat 7 (resource-exhaustion). The operator sees "SECURITY EVENT during tarball extraction" for paper X and chases a tarball-bomb root cause that doesn't exist. False signal in ops logs.
- **Proposed fix:** Match on the RuntimeError message prefix or split into two branches. Simplest: inspect `str(exc)` and split:
  ```python
  except RuntimeError as exc:
      msg = str(exc)
      if "outside dest" in msg:
          logger.error("[%s] raw_tex: SECURITY EVENT (path traversal): %s", paper_id, exc)
      elif "too large" in msg or "cap exceeded" in msg:
          logger.warning("[%s] raw_tex: oversized response rejected: %s", paper_id, exc)
      else:
          logger.error("[%s] raw_tex: unexpected RuntimeError: %s", paper_id, exc)
      return False
  ```
- **Regression guard:** Two-test pair — one that simulates `RuntimeError("refusing to extract path outside dest: ...")` → asserts ERROR log with "SECURITY EVENT"; one that simulates `RuntimeError("response too large for ...: Content-Length ...")` → asserts WARNING log without "SECURITY EVENT". Both assert helper returns False.

### F3 — AC2/AC3/AC6 integration uncovered: no test exercises real `extract_preamble`

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/tools/test_notebook_scripts.py:899-996`
- **What:** Every back-fill test that touches `extract_preamble` monkeypatches it to `lambda pid: None` (lines 937, 989, 1047). No test in the milestone exercises the real `ingest.preamble.extract_preamble` against a synthetic `.tex` source written into a real `corpus/raw/<paper_id>/` tree. Consequence: the end-to-end claim "raw_tex_fetched → preamble.json written" (AC2) has no in-repo regression guard for the integration boundary between `_fetch_raw_tex_with_503_backoff` and `extract_preamble`. AC3 ("≥ 90% recovered") and AC6 (`get_definitions total > 0`) are explicitly operator-deferred — defensible — but their pre-condition (AC2's mechanical write of preamble.json) has no test in this milestone either.
- **Why it matters:** A future refactor that changes `extract_preamble`'s path conventions, `RAW_DIR` constant, or the `_select_root_tex` heuristic will be caught by `tests/test_preamble.py` (existing) but NOT by this milestone's recovery driver tests. The recovery driver could silently stop producing preambles even though all its OWN tests pass. The implementation summary's AC2 claim cites `test_recover_preambles_skips_paper_with_existing_preamble` — but that test only verifies the negative case (skips when preamble exists), not the positive integration case.
- **Proposed fix:** Add one integration test `test_recover_preambles_writes_real_preamble_json_end_to_end` that (a) creates `corpus/parsed/<pid>/index.html`, (b) monkeypatches `fetch_eprint` to write a real synthetic `.tex` containing `\newcommand{\foo}{bar}` into `raw_dir/<pid>/main.tex`, (c) monkeypatches `recover_preambles.PREAMBLE_OUTPUT_DIR` AND `ingest.preamble.PREAMBLE_DIR` AND `ingest.preamble.RAW_DIR` to a tmp_path tree, (d) calls `recover_preambles.run()`, (e) asserts `(preamble_dir/pid/"preamble.json").is_file()` AND that the JSON contains the macro. ~30 LOC. Re-uses an existing tex fixture from `tests/fixtures/` if available.
- **Regression guard:** This finding's proposed fix IS the regression guard.

### F4 — autouse fixture default mask is invisible to future test authors

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/tools/test_notebook_scripts.py:35-49`
- **What:** The `_default_notebook_fetch_env` fixture is declared `autouse=True` at module scope. Every existing AND every future test in this file silently gets `ARXMCP_CONTACT_EMAIL=test@example.com` AND a no-op `notebook_fetch.fetch_raw_tex_if_missing`. A test added six months from now that intends to exercise the real raw-tex network path will silently pass without ever hitting `fetch_eprint`. The fixture docstring (lines 36-43) documents the contract for current readers but doesn't surface to a `git grep notebook_fetch.fetch_raw_tex_if_missing` consumer who has no reason to inspect conftest-style decorators when reading a specific test.
- **Why it matters:** This is the same anti-pattern documented in `.claude/notes/milestones/textbook-ingest-m1/` rect F1 — silently-applied defaults break the next milestone's test by appearing to validate a path that's mocked out. Test-only, but the consequence is bug-masking in future milestones, not in this one.
- **Proposed fix:** Two acceptable options: (a) demote autouse to opt-in via `@pytest.mark.usefixtures("_default_notebook_fetch_env")` on existing tests + module-scope `pytestmark = pytest.mark.usefixtures("_default_notebook_fetch_env")` so it stays universal but is grep-discoverable; (b) split the fixture into TWO — `_set_contact_email` (autouse) and `_mock_raw_tex_fetch` (NOT autouse; explicitly requested by tests that want it). Option (b) is cleaner: most existing tests don't actually care about raw-tex mocking (they monkeypatch `try_cache` to return a hit or miss without going to network anyway), so they don't need the mock.
- **Regression guard:** N/A — this is a test-architecture finding. The "regression" is a future test author confusion; the fix is to remove the foot-gun.

### F5 — operator-followup.md cross-reference does not enumerate AC3 + AC6 as tracked items

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `.claude/notes/milestones/embedder-truncation-m1/operator-followup.md:54-87`
- **What:** The implementation summary asserts (lines 21, 24) that AC3 (≥90% recovery) and AC6 (`get_definitions total > 0` canary) are "cross-referenced in the `embedder-truncation-m1/operator-followup.md` doc." The actual cross-reference section ("Cross-reference: notebook-preamble-recovery-m1", lines 54-87) recommends running `make ingest-recover-preambles` and then `make re-embed-all`, but it does NOT enumerate AC3's 90% threshold or AC6's `total > 0` canary as explicit operator deliverables. There's no checklist line "verify ≥ 90% of 137 papers recovered" and no "spot-check get_definitions for paper X returns total > 0."
- **Why it matters:** "Deferred to operator with no enumerated check" is the exact failure mode documented in `embedder-truncation-m1/critique-merged.md` F7 ("B-3 deferral lacks a tracking artifact"). This milestone reuses the same tracker but defers TWO more ACs into it without updating the tracker to list them. Without explicit enumeration the operator runs the back-fill, sees `preamble_recovered=130` in the summary, and never thinks to compute `130/137 ≈ 95% ≥ 90%` or run the `get_definitions` canary. The deferral becomes effectively a silent drop.
- **Proposed fix:** Add a new section "## 3. AC3 — recovery rate ≥ 90%" and "## 4. AC6 — `get_definitions` canary" to `embedder-truncation-m1/operator-followup.md` with the exact threshold + the exact canary paper_id + the exact MCP call to make. ~15 LOC. Better long-term: create `notebook-preamble-recovery-m1/operator-followup.md` as a sibling tracker rather than continuing to bolt onto the embedder-truncation tracker (which mixes concerns).
- **Regression guard:** N/A — doc-level finding; the test is the operator's read of the tracker.

### F6 — `_fetch_raw_tex_with_503_backoff` MAX cap never actually reached at intended wait

- **Severity:** LOW
- **Source:** adversary
- **File:** `tools/recover_preambles.py:126-147`
- **What:** With `DEFAULT_503_BACKOFF_SECONDS = 60.0` and `MAX_503_BACKOFF_SECONDS = 300.0`, the doubling sequence on the `if backoff < MAX_503_BACKOFF_SECONDS` guard yields: try → sleep 60 (backoff=120) → try → sleep 120 (backoff=240) → try → sleep 240 (backoff=300) → try → return `"max_backoff_exceeded"` WITHOUT a sleep at 300. The log line at 139-142 says `"backing off %.0fs (cap %.0fs)"` displaying 300 as the cap, but no attempt is ever made after a 300s wait. Total wall-clock 420s with 3 retries. The "cap 300s" in the log is misleading.
- **Why it matters:** Operator inspecting `recover_preambles.log` sees "backing off 240s (cap 300s)" — expects a final 300s retry — and may interpret a `max_backoff_exceeded` outcome as a permanent failure when in fact one more attempt at the cap was never made. Behavioral cap is 240s not 300s.
- **Proposed fix:** Either (a) change the guard to `if is_503 and (backoff < MAX_503_BACKOFF_SECONDS or backoff == MAX_503_BACKOFF_SECONDS)` and add an explicit one-shot retry at the cap with an outer counter, or (b) accept current behavior and adjust the log line to advertise the effective cap (the largest pre-retry sleep, currently `MAX_503_BACKOFF_SECONDS / 2 + last_doubling = 240s`). Option (b) is one-line: `"backing off %.0fs (max retry wait %.0fs)" % (wait, MAX_503_BACKOFF_SECONDS // 2)`. Or just drop the "(cap %.0fs)" parenthetical.
- **Regression guard:** Existing `test_recover_preambles_503_backoff_retries_then_succeeds` could be extended to assert the exact retry count + sleep sequence under a forced-permanent-503 mock, but a doc-only fix doesn't need a new test.

### F7 — idempotency gate misses subdir-only `.tex` layouts

- **Severity:** LOW
- **Source:** adversary
- **File:** `tools/_notebook_common.py:191-196` (and mirrored `tools/recover_preambles.py:98-101`)
- **What:** Both `fetch_raw_tex_if_missing` and `_has_raw_tex` use `paper_raw_dir.glob("*.tex")` (top-level only). arXiv tarballs occasionally extract `.tex` only into subdirs (e.g. `chapters/intro.tex`, `paper/main.tex`). `extract_preamble`'s `_select_root_tex` (`ingest/preamble.py:394-411`) handles this correctly via its top-level-then-`find_main_tex` recursive fallback. But the helper's idempotency gate does NOT — for a paper with only subdir `.tex`, the gate returns False every time, and the helper re-fetches from arXiv on every run.
- **Why it matters:** Costs an extra `/e-print/` round-trip per run for the affected papers (3s politeness sleep + 1 HTTP request each). Idempotency claim in the helper docstring (`_notebook_common.py:165-167`: "Operators can re-run the back-fill freely") is wrong for subdir-layout papers. Not catastrophic — arXiv accepts the duplicate request — but the gate exists precisely to prevent the duplicate.
- **Proposed fix:** Change `paper_raw_dir.glob("*.tex")` to `paper_raw_dir.rglob("*.tex")` in both sites. Trade-off: rglob is recursive, slightly slower for deep trees, but the per-paper tree is small (single tarball extraction). Match `_select_root_tex`'s actual search semantics.
- **Regression guard:** Two-test pair — one that creates only `paper_raw_dir/chapters/intro.tex` and asserts the helper returns True without calling fetch_eprint; one that creates only `paper_raw_dir/main.tex` (top level) and asserts the same. Distinguishes the rglob fix from accidentally breaking the top-level case.

### F8 — `tests/tools/test_notebook_scripts.py` file size + cohesion

- **Severity:** LOW
- **Source:** adversary
- **File:** `tests/tools/test_notebook_scripts.py` (full file)
- **What:** The file now exceeds 1050 lines covering three distinct script surfaces (fetch, ingest, purge, plus the new recovery scripts). Adding 11 more tests cluster all preamble-recovery concerns at the bottom without a dedicated module. Future authors looking for back-fill tests grep across a multi-purpose file.
- **Why it matters:** Style only — but the existing pattern in `tests/` does split per-source-file (e.g. `tests/test_handlers_search.py`, `tests/test_handlers_chunks.py`). Splitting into `tests/tools/test_preamble_recovery.py` (or `tests/tools/test_notebook_fetch_raw_tex.py`) would mirror the source structure.
- **Proposed fix:** Defer. Not warranted today; revisit if a `m2` lands and the file passes 1500 lines. Record in `state.json::deferred_findings`.
- **Regression guard:** N/A — style finding.

## What was done well

- Paper_id validation is in the right place: `notebook_fetch.py:110` filters via `is_valid_arxiv_paper_id` BEFORE constructing `paper_raw_dir = CORPUS_RAW_DIR / paper_id` at line 154, closing the Threat-1 path-traversal surface I flagged in the prompt. `recover_preambles._discover_candidates` (line 174) does the same. The defense-in-depth boundary held.
- `CORPUS_RAW_DIR` correctly placed as the PARENT directory; `fetch_eprint` appends `paper_id` internally (`tools/arxiv_fetch.py:257`). The synthesis "PARENT vs PER-PAPER subdir" decision was implemented correctly throughout.
- AC5 (chunk_id rotation) claim is anchored by a real test in `tests/test_chunker_ids.py::test_preamble_mutation_changes_chunk_id` (line 25). The implementation didn't have to add a new test; it correctly leveraged an existing one.
- AC7 enforcement at run-time (not import-time) is the right call — `notebook_fetch.py:90-99` + `recover_preambles.py:187-192` — keeps tests that don't exercise the raw-tex path from needing to set the env. The autouse fixture explicitly tests the absence-of-env case via `monkeypatch.delenv` (lines 854, 1002).
- Exception envelope in `_notebook_common.py::fetch_raw_tex_if_missing` (lines 179-189) is complete — `HTTPError`, `RuntimeError`, `OSError`, `tarfile.TarError`, `gzip.BadGzipFile`. The helper itself is robust, even though the back-fill bypass loses this property (F1).
- BP1/tools-list byte-stability verified: zero edits to `server/tools.py` or `server/prompts.py`. `tests/test_server_tool_schema.py` + `tests/test_prompts.py` still pin the same hashes — X-1 and X-2 hold mechanically.
- Politeness contract well-handled: ar5iv and `export.arxiv.org` budgets are explicitly separate (`notebook_fetch.py:148-152` comment + the `sleep(sleep_seconds)` before the helper at line 160). The idempotent-short-circuit skips the sleep when no network is needed.
- Local-first / Docker constraint preserved: no new dependencies in `pyproject.toml`, no cloud endpoints, no submodules. The `export.arxiv.org` endpoint is the same one `tools/fetch_seed.py` uses — established precedent.
- Operator warning for the chunk_id-rotation re-embed cascade is documented in three places (Makefile help, `recover_preambles.py` module docstring, `operator-followup.md`) and they agree on the 2-4 hour figure. No drift between the three sites.
- Withdrawn-paper asymmetry (`withdrawn_404` is a distinct outcome, not a generic error) is correctly modeled in `RecoverySummary` (`recover_preambles.py:84-91`) and the test exists (`test_recover_preambles_404_classified_as_withdrawn`). Synthesis FM-3 was honored.

## Recommended rectification order

1. **F1** — back-fill exception envelope. Highest blast radius: a single tarball-bomb on a real arXiv response would abort a one-shot operator run that's supposed to take ~7 minutes. Fix is mechanical (~10 LOC of `except` clauses + outcome string).
2. **F3** — add the one integration test exercising real `extract_preamble`. ~30 LOC, anchors AC2 against future refactors. Pairs naturally with F1 (the new test is the regression guard for both the fetch envelope AND the extract chain).
3. **F2** — disambiguate `RuntimeError` log labels. ~5 LOC + 2-test pair. Same file/region as F1, do them together.
4. **F5** — add explicit AC3 + AC6 enumeration to `operator-followup.md`. ~15 LOC of doc. Or create dedicated `notebook-preamble-recovery-m1/operator-followup.md`.
5. **F4** — autouse fixture split or grep-discoverable pattern. ~10 LOC; do alongside F3 since both touch test infrastructure.
6. **F6, F7** — defer to `deferred_findings`. Both are LOW; F7 has a one-line fix (`glob` → `rglob`) and could be folded in if rectifier is already in the file.
7. **F8** — defer permanently to `deferred_findings`. Revisit only if file grows further.

## Rectification status

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
