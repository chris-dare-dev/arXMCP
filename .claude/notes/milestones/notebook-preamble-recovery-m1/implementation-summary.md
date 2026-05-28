# Implementation Summary — notebook-preamble-recovery-m1

**Path:** inline (orchestrator main session)
**Base SHA:** `aec46ce7d1b5a93e00170d61ee58c1f966dec48e`
**Generated:** 2026-05-28

---

## One-line

Add raw `.tex` fetch to the ar5iv ingest path so `extract_preamble` runs on every paper; add `make ingest-recover-preambles` back-fill target + driver script for the 137 already-ingested ar5iv-only papers; enforce `ARXMCP_CONTACT_EMAIL` at notebook-ingest entry.

## Commit range

`aec46ce7..<HEAD>` (filled after the feat commit lands).

## Acceptance criteria status

- **[AC1] ✅** Every successful `try_cache` hit in `tools/notebook_fetch.py` is followed by a call to `fetch_raw_tex_if_missing(paper_id, CORPUS_RAW_DIR)`. Regression test: `tests/tools/test_notebook_scripts.py::test_fetch_raw_tex_if_missing_invoked_after_ar5iv_hit` records the per-paper invocation list and asserts it matches the ar5iv-hit set.
- **[AC2] ✅** `tools/recover_preambles.py::run()` calls `extract_preamble(paper_id)` after a successful raw-tex fetch. The function is idempotent (SHA256 short-circuit). Regression test: `test_recover_preambles_skips_paper_with_existing_preamble` asserts no fetch happens when `preamble.json` already exists.
- **[AC3] DEFERRED to operator** — pipeline tests the driver against synthetic fixtures; the "≥ 90% recovered" measurement happens on the operator's first `make ingest-recover-preambles` run against the 137 live papers. Cross-referenced in the `embedder-truncation-m1/operator-followup.md` doc (now updated to recommend the recover-then-re-embed sequence).
- **[AC4] ✅** A `False` return from `fetch_raw_tex_if_missing` does NOT abort the notebook loop. Regression test: `test_fetch_raw_tex_if_missing_failure_does_not_abort_notebook` mocks selective failure on the middle paper of three and asserts all three are still attempted + the summary line shows the right counts.
- **[AC5] ✅ by design** — `_compute_chunk_id` is preamble-sensitive (`sha256(preamble_text + body_text)[:16]`). Back-filled papers will rotate chunk_ids on the next `make re-embed-all`. INTENDED. Documented in `tools/recover_preambles.py` module docstring AND the Makefile target help comment AND the cross-reference in `operator-followup.md` (2-4 hour CPU warning).
- **[AC6] DEFERRED to operator** — the `get_definitions` canary spot-check requires a real re-embed + a populated definitions index, both of which are operator-driven post-milestone. Recorded in `operator-followup.md`.
- **[AC7] ✅** `ARXMCP_CONTACT_EMAIL` is required at `notebook_fetch.run()` entry AND `recover_preambles.run()` entry. Hard NotebookError with a clear message + remediation. Enforcement is at run-time, NOT import-time (so tests that don't exercise the raw-tex path don't need to set the env var). Regression tests: `test_notebook_fetch_run_requires_arxmcp_contact_email` + `test_recover_preambles_requires_arxmcp_contact_email`.
- **[X-1] ✅** `EXPECTED_TOOL_SCHEMA_SHA256` UNCHANGED — no `server/tools.py::ALL_TOOLS` edit. Verified by green `tests/test_server_tool_schema.py`.
- **[X-2] ✅** `EXPECTED_BP1_SHA256` UNCHANGED — no `server/prompts.py` edit. Verified by green `tests/test_prompts.py`.
- **[X-3] ✅** `ruff check .` clean. `make test`: **2895 passed, 26 skipped, 1 xfailed, 6 pre-existing failures** (same 6 verified at the milestone base SHA; latexmlc + Kùzu + parser-fidelity-fixture-dirs). Net +117 vs the embedder-truncation-m1 baseline (2778); 10 mine, the rest from parallel textbook-ingest-m3 work merging in.
- **[X-4] ✅** NO `CHUNKER_VERSION` bump — chunker is unchanged.

## New / changed tests

- **New:** `tests/tools/test_notebook_scripts.py::test_fetch_raw_tex_if_missing_invoked_after_ar5iv_hit` — AC1.
- **New:** `tests/tools/test_notebook_scripts.py::test_fetch_raw_tex_if_missing_failure_does_not_abort_notebook` — AC4.
- **New:** `tests/tools/test_notebook_scripts.py::test_fetch_raw_tex_if_missing_idempotent_when_raw_dir_populated` — idempotency gate.
- **New:** `tests/tools/test_notebook_scripts.py::test_fetch_raw_tex_if_missing_404_returns_false` — FM-3 (withdrawn paper).
- **New:** `tests/tools/test_notebook_scripts.py::test_fetch_raw_tex_if_missing_tarball_bomb_logs_error_returns_false` — FM-1 (security event).
- **New:** `tests/tools/test_notebook_scripts.py::test_notebook_fetch_run_requires_arxmcp_contact_email` — AC7 (notebook side).
- **New:** `tests/tools/test_notebook_scripts.py::test_recover_preambles_skips_paper_with_existing_preamble` — back-fill idempotency.
- **New:** `tests/tools/test_notebook_scripts.py::test_recover_preambles_notebook_scope_filter` — `--notebook=<slug>` scoping.
- **New:** `tests/tools/test_notebook_scripts.py::test_recover_preambles_503_backoff_retries_then_succeeds` — FM-2.
- **New:** `tests/tools/test_notebook_scripts.py::test_recover_preambles_requires_arxmcp_contact_email` — AC7 (back-fill side).
- **New:** `tests/tools/test_notebook_scripts.py::test_recover_preambles_404_classified_as_withdrawn` — FM-3 (back-fill side).
- **New fixture (autouse):** `_default_notebook_fetch_env` sets `ARXMCP_CONTACT_EMAIL=test@example.com` + patches `notebook_fetch.fetch_raw_tex_if_missing` to a no-op. Protects existing tests from accidentally hitting `export.arxiv.org`. Tests that exercise the new path override the patch explicitly (Python's monkeypatch is stack-based; inner wins).

## Code edits

- **`tools/_notebook_common.py`** — added `CORPUS_RAW_DIR` constant; added `fetch_raw_tex_if_missing(paper_id, raw_dir, *, contact_email=None) -> bool` helper with idempotent skip + full exception envelope (HTTPError, RuntimeError, OSError, TarError, BadGzipFile) + level-appropriate logging (WARNING for recoverable, ERROR for security events); exported both via `__all__`.
- **`tools/notebook_fetch.py`** — top of `run()` hard-checks `ARXMCP_CONTACT_EMAIL` (NotebookError if unset); after each ar5iv `result.hit`, sleeps `sleep_seconds` (unless raw dir already populated) and calls `fetch_raw_tex_if_missing`; extended summary line with `raw_tex_recovered=P raw_tex_missing=M2`. Updated module docstring.
- **`tools/recover_preambles.py`** (NEW, ~290 LOC) — back-fill driver. Discovers candidates (all of `corpus/parsed/` by default, or `--notebook=<slug>`); for each paper missing `preamble.json`: politeness_sleep → `fetch_eprint` with 503 backoff (mirrors `fetch_seed.py::fetch_with_backoff` semantics with `MAX_503_BACKOFF_SECONDS = 300`) → `extract_preamble`. Per-paper outcome tracking + final summary. Exit codes: 0 (success / no-op), 1 (env-var missing OR every fetch errored), 2 (no candidates).
- **`Makefile`** — added `ingest-recover-preambles` target with help text + ARGS-spaces footgun comment + chunk_id-rotation operator warning. Appended to `.PHONY`.

## Driver + script details

The synthesis split responsibilities cleanly:
- `fetch_raw_tex_if_missing` (helper, in `_notebook_common.py`): fetch-only, sleep-free (caller owns politeness budget), returns `bool`. Swallows `HTTPError` (logs + returns False).
- `recover_preambles.py::_fetch_raw_tex_with_503_backoff` (internal): wraps `fetch_eprint` DIRECTLY with the retry loop because the helper would swallow `HTTPError(503)`. The asymmetry is intentional per the synthesis "503-backoff asymmetry" decision: notebook ingest skips on first 503 (operator re-runs), back-fill retries with exponential backoff (one-shot batch).

## Docs

- **`tools/notebook_fetch.py` docstring** — updated to document the new raw-tex step + `ARXMCP_CONTACT_EMAIL` requirement.
- **`tools/recover_preambles.py` docstring** — fully documents the back-fill workflow, idempotency, exit codes, AND the chunk_id-rotation operator warning.
- **`Makefile`** — `ingest-recover-preambles` help text + comment block warn about the chunk_id-rotation re-embed cascade.
- **`.claude/notes/milestones/embedder-truncation-m1/operator-followup.md`** — cross-referenced with the recommended back-fill-then-re-embed sequence and the option to measure B-3 nDCG@5 either pre- or post-preamble for clean confound separation.

## External writes the orchestrator must authorize

**None.** Per the synthesis: the only external request is `GET https://export.arxiv.org/e-print/<paper_id>` during operator-initiated runs — the same endpoint `tools/fetch_seed.py` already calls with the same politeness contract. Per project convention (agent-conventions.md §8), runtime egress to a documented public read-only endpoint respecting politeness contracts is NOT a Phase-4-gateable external write.

## Deviations from the brief

1. **Scope correction:** the brief said "~65 ar5iv papers in the live notebook tree"; live measurement is **137 papers** in `corpus/parsed/` with 0 in `corpus/raw/`. The back-fill defaults to all 137; `--notebook=<slug>` scopes down. The synthesis's "Scope" section documents this explicitly.

2. **AC3 / AC6 are deferred to operator** — the pipeline tests the driver against synthetic fixtures (with mocked `fetch_eprint`); the 90%-recovery and `get_definitions`-canary measurements happen on the operator's first real run. Both are flagged in the cross-referenced `operator-followup.md`.

3. **The autouse `_default_notebook_fetch_env` fixture** was added to `tests/tools/test_notebook_scripts.py` so existing tests that exercise the ar5iv-hit path (`test_fetch_happy_path`, etc.) don't break on the new raw-tex step. The fixture sets `ARXMCP_CONTACT_EMAIL` AND patches `fetch_raw_tex_if_missing` to a no-op; new tests that need to assert specific helper behavior override the patch explicitly. This is the cleanest way to keep AC7's run-time enforcement testable without breaking the test suite at large.

4. **`fetch_with_backoff` is reimplemented inline in `recover_preambles.py`** rather than imported from `fetch_seed.py`, because `fetch_seed.fetch_with_backoff` returns a `(Outcome, FetchResult | None)` tuple specific to that module. Inlining the loop in `_fetch_raw_tex_with_503_backoff` keeps `recover_preambles.py` self-contained. ~30 LOC duplication; acceptable per the synthesis.

## Risk surface for Phase 3 critique

- **AC3 / AC6 deferral:** if the adversary considers the operator-driven measurements load-bearing for the milestone, this framing may be flagged. The framing matches the embedder-truncation-m1 precedent (B-3 was similarly deferred).
- **Autouse fixture scope:** the `_default_notebook_fetch_env` fixture applies to EVERY test in `test_notebook_scripts.py`, including future tests added by other milestones. Operators / future implementers must be aware that the fixture exists and that real-world `fetch_raw_tex_if_missing` calls are mocked by default.
- **`fetch_with_backoff` duplication:** ~30 LOC of similar-but-not-identical retry logic now exists in both `fetch_seed.py` and `recover_preambles.py`. Future maintainer might want to refactor; not warranted today.
- **Makefile change:** triggers `milestone-infra-safety` critic.
- **`ARXMCP_CONTACT_EMAIL` early check** is in BOTH `notebook_fetch.run()` and `recover_preambles.run()` — DRY violation if a future entry point also needs it. Acceptable today (only two entry points); refactor into `_notebook_common` if a third lands.
