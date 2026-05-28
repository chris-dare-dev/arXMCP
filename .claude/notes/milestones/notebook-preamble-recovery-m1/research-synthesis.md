# Research Synthesis — notebook-preamble-recovery-m1

**Generated:** 2026-05-28 (post-research-phase)
**Merge mode:** orchestrator (main session), two-brief standard merge
**Inputs:** `research-brief-1.md`, `research-brief-2.md`

---

## TL;DR

Implement Option A from the scan brief as scoped, with **six concrete
implementation decisions** that resolve disagreements / refine the roadmap:

1. **Scope correction:** back-fill is **137 papers** (not "~65"). Live
   measurement: `corpus/parsed/` = 137 dirs, `corpus/raw/` = 0 dirs.
2. **`fetch_raw_tex_if_missing` is fetch-only.** Both callers
   (`notebook_fetch.run()` and the new back-fill script) invoke
   `extract_preamble(paper_id)` explicitly after a successful fetch.
   Mirrors the existing `fetch_seed.py` pattern.
3. **`ARXMCP_CONTACT_EMAIL` enforcement is early but NOT import-time.**
   Hard check at the top of `notebook_fetch.run()` (and the back-fill
   script's `run()`), NOT at module load. This satisfies AC7's "fail
   loudly with a clear error message" without breaking the test suite.
4. **Helper signature:** `fetch_raw_tex_if_missing(paper_id, raw_dir,
   contact_email=None) -> bool`. **Caller owns the politeness sleep.**
   The helper sleeps zero seconds; `notebook_fetch.run()` adds
   `time.sleep(sleep_seconds)` BEFORE the call (separate from its
   existing ar5iv-side sleep).
5. **Exception envelope:** catch the full `fetch_seed.py` envelope —
   `urllib.error.HTTPError, RuntimeError, OSError, tarfile.TarError,
   gzip.BadGzipFile`. `RuntimeError` is critical because
   `_safe_extract` raises it on path-traversal (security event).
6. **503-backoff asymmetry:** the inline `notebook_fetch.py` call
   logs + returns `False` on first 503 (operator re-runs); the
   back-fill script implements exponential backoff matching
   `fetch_seed.py::fetch_with_backoff`. The asymmetry is correct
   because the notebook ingest has hundreds of papers to re-loop
   over later; the back-fill is a one-shot multi-hour batch.

---

## In-codebase context (merged, load-bearing constraints quoted verbatim)

### Scope (live measurement, 2026-05-28)

| Path | Count |
|---|---:|
| `var/arxmcp/corpus/parsed/<paper_id>/index.html` | **137** |
| `var/arxmcp/corpus/raw/<paper_id>/` | **0** |
| `var/arxmcp/corpus/preamble/<paper_id>/preamble.json` | **0** |
| `var/arxmcp/ops/parser-failures/preamble.log` lines | 6,260 |
| Unique paper IDs in preamble.log | 142 |

**Every** ar5iv-only paper today (137 of them) is missing raw `.tex`.
The roadmap's "~65" estimate was from the notebook-only scope; the
back-fill MUST default to all 137 in `corpus/parsed/`, with
`ARGS="--notebook=<slug>"` available to scope down.

### `fetch_eprint` contract (R1 + R2 agree — `tools/arxiv_fetch.py:234-297`)

```python
def fetch_eprint(
    paper_id: str,
    raw_dir: Path,                    # PARENT dir; helper appends paper_id internally
    contact_email: str | None = None,
    timeout: float = 60.0,
    ssl_context: ssl.SSLContext | None = None,
) -> FetchResult:
    ...
    raw_dir = raw_dir / paper_id      # ← line 257; helper creates the paper-specific subdir
    raw_dir.mkdir(parents=True, exist_ok=True)
```

Key contract points:
- **Pass the PARENT** (`var/arxmcp/corpus/raw/`), not the paper-specific dir.
- **Raises** `urllib.error.HTTPError` on non-2xx; 404 (withdrawn) and
  503 (rate limit) both surface as `HTTPError(e.code)`.
- **Does NOT sleep internally** — docstring is explicit: "Caller is
  responsible for the politeness sleep BEFORE invoking this — the
  function does not enforce inter-call spacing."
- **Threat 7 enforced** at lines 268-284 (100 MB content-length cap).
- **`build_user_agent()` raises `RuntimeError`** if neither
  `contact_email` arg nor `ARXMCP_CONTACT_EMAIL` env var is set —
  enforcement is LAZY (call-time, not import-time).
- **`_safe_extract` at lines 330-346** raises `RuntimeError(
  "refusing to extract path outside dest: ...")` on path-traversal
  attempts. This is the load-bearing Threat-1 mitigation for the
  tarball-bomb attack class.

### `extract_preamble` contract (`ingest/preamble.py:313+`)

1. Calls `_validate_paper_id(paper_id)`.
2. Constructs `raw_paper_dir = RAW_DIR / paper_id`.
3. Raises `FileNotFoundError` if absent (caught by `PER_PAPER_FAILURE_EXCEPTIONS`).
4. Picks root `.tex` via `_select_root_tex` + enforces symlink + path-containment guard (Threat 1).
5. Writes to `PREAMBLE_DIR / paper_id / "preamble.json"`.
6. **Idempotent** via SHA256 short-circuit in `_read_existing_preamble`.

The `PER_PAPER_FAILURE_EXCEPTIONS = (OSError, ValueError, FileNotFoundError)`
envelope does NOT include `RuntimeError`. **`extract_preamble` raises**;
the caller (chunker's `_resolve_preamble_doc` and our new helper) must catch.

### Gap: `_notebook_common.py` has no `CORPUS_RAW_DIR`

The module defines `CORPUS_PARSED_DIR`, `CORPUS_CHUNKS_DIR`,
`CORPUS_EMBEDDINGS_DIR` but NOT `CORPUS_RAW_DIR`. Add it. Tests must
also be able to monkeypatch this constant; expose via `__all__`.

### `notebook_fetch.py` today has zero preamble references

Confirmed by both researchers: no `preamble`, `fetch_eprint`,
`ARXMCP_CONTACT_EMAIL`, or `RAW_DIR` references. No duplication risk.

### Politeness contract (load-bearing — quoted verbatim)

From arXiv API TOU (`https://info.arxiv.org/help/api/tou.html`):

> "When using the legacy APIs (including OAI-PMH, RSS, and the
> arXiv API), make no more than one request every three seconds,
> and limit requests to a single connection at a time."

From `tools/arxiv_fetch.py:35`: `POLITENESS_SLEEP_SECONDS = 3.0`.

From the scan brief (canonical for this milestone):

> "The politeness sleep is per-request to `export.arxiv.org`, NOT
> shared with the ar5iv budget. Sleep budgets compose additively;
> make sure the helper doesn't double-sleep."

`notebook_fetch.run()` already sleeps 3s after each ar5iv network
fetch. The new raw-tex step adds another 3s before the
`fetch_eprint` call, bringing the per-paper cost to ~6s for papers
needing a real raw-tex fetch (idempotent skip on raw-dir-exists
keeps that to zero for re-runs).

### Design notes applicable

- **`04-parsing-and-chunking.md` Rule 2** — preamble is "the single
  biggest retrieval-quality lever after macro expansion." The scan
  brief qualifies: on the ar5iv path, MathML `alttext` already
  carries macro-expanded LaTeX, so the embedder loss is small;
  `get_definitions` is the load-bearing consumer.
- **`08-security-observability-ops.md` Threat 1** — path traversal
  on tarball extraction. Mitigated by `_safe_extract` +
  `is_relative_to` containment check; both already in place.
- **`08-security-observability-ops.md` Threat 7** — 100 MB
  content-length cap. Already enforced by `fetch_eprint`.
- **`07-multi-agent-caching.md`** — `EXPECTED_TOOL_SCHEMA_SHA256`
  and `EXPECTED_BP1_SHA256` are untouched (X-1 / X-2).

### Test surface

All new tests go to `tests/tools/test_notebook_scripts.py` (NOT
`tests/test_notebook_fetch.py` — does not exist). Existing fixtures
use `monkeypatch.setattr(notebook_fetch, "try_cache", _mock)` — same
pattern for `fetch_eprint`. Add `monkeypatch.setenv(
"ARXMCP_CONTACT_EMAIL", "test@example.com")` to any test that
exercises the raw-tex path.

---

## Failure modes (merged + de-duped from R2's enumeration)

| # | Trigger | Symptom | Mitigation |
|---|---|---|---|
| FM-1 | Tarball bomb (path-traversal symlink) | `_safe_extract` raises `RuntimeError`; would propagate past `extract_preamble` (RuntimeError not in PER_PAPER_FAILURE_EXCEPTIONS) | Helper catches `RuntimeError` explicitly, logs at ERROR level (security event, not WARNING), returns `False`. Notebook run continues. |
| FM-2 | arXiv 503 mid-back-fill | Without backoff, first 503 aborts remaining papers | Back-fill script implements `fetch_seed.py::fetch_with_backoff` (honor `Retry-After`, cap at `MAX_503_BACKOFF_SECONDS`). Inline `notebook_fetch` call returns `False` on first 503 (operator re-runs). |
| FM-3 | Withdrawn paper: ar5iv 200, `/e-print/` 404 | `HTTPError(404)` propagates | Helper catches `HTTPError(404)` → log to `preamble.log` with reason `"withdrawn_404"` → return `False`. Notebook run continues; paper's ar5iv HTML still chunked, just no preamble. **NOTE**: this asymmetry not documented in `03-ingestion-pipeline.md`; surface in implementation summary. |
| FM-4 | Malformed `.tex` | `extract_preamble` raises `OSError`/`ValueError` | Already in `PER_PAPER_FAILURE_EXCEPTIONS`; `extract_preamble` catches own exceptions + logs + raises. Helper only handles `fetch_eprint`-side failures; no double-catch. |
| FM-5 | Concurrent `make ingest-recover-preambles` runs | Two processes writing to same `raw/<paper_id>/` | `mkdir(parents=True, exist_ok=True)` is atomic; content is identical (same arXiv source); preamble.json write is via temp+rename. Risk is very low. Document "run one back-fill at a time" in `make` target help. |
| FM-6 | `ARXMCP_CONTACT_EMAIL` regression breaks tests | Import-time enforcement breaks every test that imports `notebook_fetch` | Enforce at CALL time (in `run()`, not at module load). Tests that exercise the raw-tex path explicitly `monkeypatch.setenv(...)`. |
| FM-7 | Chunk_id rotation surprise after back-fill | Operator runs `make re-embed-all` expecting fast update; sees ~2-4 hours of re_embedded≫copied | INTENDED behavior (AC5). Document in implementation summary AND the Makefile help text. Update `operator-followup.md` for embedder-truncation-m1 to cross-reference. |

---

## Resolved disagreements

| # | R1 position | R2 position | Resolution |
|---|---|---|---|
| 1 | Helper signature `(paper_id, raw_dir, sleep_seconds)` — helper sleeps | Helper signature `(paper_id, raw_dir, contact_email=None)` — caller sleeps | **R2 wins.** Helper is sleep-free; caller owns the politeness budget. Matches `fetch_eprint`'s contract exactly. |
| 2 | Add early `ARXMCP_CONTACT_EMAIL` check in `notebook_fetch.run()` | NO import-time enforcement; rely on lazy `build_user_agent()` | **HYBRID** — early check in `run()` BUT not at module load. R1's UX concern (per-paper cryptic errors) is valid; R2's test-breakage concern is real. The hybrid satisfies both. |
| 3 | Summary: `preamble_recovered=P preamble_failed=F` | Summary: `raw_tex_skipped=K2` separate counter | **R2 wins** on the rename. Final format: `fetched=N from_cache=M missing=K rate_limited=R malformed=J raw_tex_recovered=P raw_tex_missing=M2`. The "missing" bucket covers all non-OK raw-tex outcomes (404, 503, network); operators read `preamble.log` for per-paper reasons. |
| 4 | Exception envelope: `HTTPError`, `OSError`, `RuntimeError` | Fuller: + `tarfile.TarError`, `gzip.BadGzipFile` | **R2 wins.** Fuller envelope matches `fetch_seed.py`'s pattern and covers more attack surface. |
| 5 | 503: implicit retry inside helper | 503: backoff in back-fill script, log+return in inline `notebook_fetch` | **R2 wins** on the asymmetry. Reasoning: notebook ingest has many papers; first 503 → log + skip + continue → operator re-runs later. Back-fill is a one-shot batch; 503 → exponential retry → resume. |
| 6 | (silent on operator chunk_id-rotation warning) | FM-7: explicit warning required | **R2 wins.** Add the warning to implementation summary, Makefile help, AND update `operator-followup.md` for embedder-truncation-m1. |

Other agreement (no disagreement to resolve):
- Scope is 137 papers; back-fill defaults to all of `corpus/parsed/`.
- `CORPUS_RAW_DIR` constant added to `_notebook_common.py`.
- Back-fill script lives at `tools/recover_preambles.py`.
- No CHUNKER_VERSION bump.
- No MCP surface change; X-1 + X-2 untouched.
- No new external endpoint (`export.arxiv.org` already in use).
- `external_writes_required = []`.

---

## Implementation plan (orchestrator decision: INLINE)

LOC estimate: ~300-450 hand-written. Files touched: 5 (helper, notebook_fetch,
back-fill script, Makefile, tests). At the boundary of inline-vs-delegated;
choosing INLINE because the synthesis is detailed and the surface is narrow.

**Sequence (single feat commit):**

1. **`tools/_notebook_common.py`** — add `CORPUS_RAW_DIR` constant; add
   `fetch_raw_tex_if_missing(paper_id, raw_dir, contact_email=None) -> bool`
   helper. Idempotent skip when `(raw_dir / paper_id).glob("*.tex")` is
   non-empty. Catches the R2 exception envelope. Logs to `preamble.log`
   with WARNING (recoverable) or ERROR (security event) levels.

2. **`tools/notebook_fetch.py`** — import `fetch_raw_tex_if_missing` and
   `CORPUS_RAW_DIR`. At top of `run()`: assert `ARXMCP_CONTACT_EMAIL` env
   var or raise `NotebookError` with a clear message. After each
   successful `try_cache(...)`: sleep 3s, call `fetch_raw_tex_if_missing`,
   then call `extract_preamble(paper_id)` (caught for graceful skip).
   Extend summary line: `fetched=N from_cache=M missing=K rate_limited=R
   malformed=J raw_tex_recovered=P raw_tex_missing=M2`. Update docstring.

3. **`tools/recover_preambles.py`** (NEW) — back-fill script. Argparse:
   `--notebook=<slug>` (optional, scopes to one notebook's papers.txt),
   `--limit=N` (testing). Walks `corpus/parsed/*/index.html` by default
   (137 papers). For each paper missing `preamble.json`:
   `politeness_sleep` → `fetch_raw_tex_if_missing` (with the same
   503-backoff loop as `fetch_seed.py::fetch_with_backoff`) →
   `extract_preamble`. Final summary: `total=N fetched=A skipped=B
   preamble_recovered=C preamble_failed=D withdrawn=E`. Exit code 0
   if all paper-level failures are recoverable (404 withdrawn,
   security event); 1 if structural failures.

4. **`Makefile`** — `make ingest-recover-preambles` target wrapping
   `tools/recover_preambles.py`. Help text includes the chunk_id-
   rotation warning (FM-7). ARGS-spaces-footgun note matching the
   sibling targets.

5. **`tests/tools/test_notebook_scripts.py`** — extend with:
   - `test_fetch_raw_tex_if_missing_invoked_after_ar5iv_hit`
   - `test_fetch_raw_tex_if_missing_503_does_not_abort_notebook`
   - `test_fetch_raw_tex_if_missing_404_logged_as_withdrawn`
   - `test_fetch_raw_tex_if_missing_idempotent_skip_when_raw_dir_present`
   - `test_fetch_raw_tex_if_missing_tarball_bomb_returns_false_logs_error`
   - `test_notebook_fetch_run_requires_arxmcp_contact_email`
   - `test_recover_preambles_walks_corpus_parsed_default`
   - `test_recover_preambles_notebook_scope_filter`
   - `test_recover_preambles_503_backoff_retries`

6. **Documentation** — update `tools/notebook_fetch.py` docstring with
   the `ARXMCP_CONTACT_EMAIL` requirement; update
   `.claude/notes/milestones/embedder-truncation-m1/operator-followup.md`
   to cross-reference the back-fill workflow.

**Note for Phase 4 (rectify) and the operator:** the production
back-fill (`make ingest-recover-preambles`, ~7 minutes for 137 papers
at 3s/paper politeness) does NOT run in this pipeline. The AC3
"≥ 90% recovered" measurement is operator-driven. The pipeline tests
the driver with mocked `fetch_eprint`; the AC3 verification happens
on the operator's first real run.

---

## Open questions (consolidated)

All open questions from both researchers are resolved inline above
via the "Resolved disagreements" table or the in-codebase context.

One residual: **the design notes (`03-ingestion-pipeline.md`) do not
document the ar5iv-200 / `/e-print`-404 asymmetry (FM-3, withdrawn
papers).** The implementation summary should flag this as a doc gap
that a future maintainer can close.

---

## External writes the implementation will require

**None.** This milestone is purely local:

- No `git push`
- No `gh issue create` / `gh pr create`
- No infra mutations
- The new `GET https://export.arxiv.org/e-print/<paper_id>` egress
  reuses the existing `tools/arxiv_fetch.fetch_eprint` path that
  `tools/fetch_seed.py` already calls. Per project convention
  (agent-conventions.md §8), a runtime egress to a documented
  public read-only endpoint respecting politeness contracts is NOT
  a Phase-4-gateable external write.

`external_writes_required = []` in state.json.

---

## Orchestrator synthesis note

Both researchers converged on the implementation shape (Option A) and
diverged constructively on six concrete decisions. R2's failure-mode
enumeration was the stronger contribution — FM-3 (withdrawn-paper
asymmetry), FM-6 (test regression on import-time enforcement), and
FM-7 (chunk_id rotation surprise) are all real and would have surfaced
in critique otherwise.

R1's strongest contribution: empirically resolving the scope question
(137 papers in parsed, not the brief's "~65") and documenting the
exact `fetch_eprint` return contract with the "function appends
`paper_id` internally" footgun.

The synthesis adopts R2's hybrid stance on `ARXMCP_CONTACT_EMAIL`
enforcement (early but not import-time) and R2's fuller exception
envelope. The helper signature follows R2's `(paper_id, raw_dir,
contact_email=None)` form.

---

## Acceptance criteria (final, AFTER synthesis)

| AC | Original | Final (post-synthesis) |
|---|---|---|
| AC1 | Every ar5iv-pull-success → raw .tex on disk | UNCHANGED. Verified via `tests/tools/test_notebook_scripts.py::test_fetch_raw_tex_if_missing_invoked_after_ar5iv_hit`. |
| AC2 | `extract_preamble` returns PreambleDoc + writes preamble.json | UNCHANGED. Verified via the unit test that asserts both. |
| AC3 | Back-fill recovers ≥ 90% of existing papers | **REFRAMED:** scope is **137 papers, not ~65**. Operator-driven; pipeline tests the driver against synthetic fixtures. The "≥90%" measurement happens on the operator's first `make ingest-recover-preambles` run; recorded in `operator-followup.md` cross-reference. |
| AC4 | 503/network failure → notebook run does NOT abort | UNCHANGED. Verified via `test_fetch_raw_tex_if_missing_503_does_not_abort_notebook`. |
| AC5 | Post-back-fill: chunk_ids rotate; non-null `preamble_ref` | UNCHANGED. **Operator follow-up:** chunk_id rotation will trigger ~2-4 hours of additional re-embed CPU on the next `make re-embed-all`. Documented in Makefile help (FM-7) and in `operator-followup.md`. |
| AC6 | `get_definitions` returns `total > 0` on canary post-back-fill | UNCHANGED. Operator spot-check in implementation summary. |
| AC7 | `ARXMCP_CONTACT_EMAIL` required for notebook ingest | UNCHANGED, with explicit clarification: enforced at `run()` entry, NOT at import time (avoids FM-6). Verified via `test_notebook_fetch_run_requires_arxmcp_contact_email`. |
| X-1 | EXPECTED_TOOL_SCHEMA_SHA256 UNCHANGED | UNCHANGED. |
| X-2 | EXPECTED_BP1_SHA256 UNCHANGED | UNCHANGED. |
| X-3 | ruff + make test green; 2778+ tests | UNCHANGED. |
| X-4 | NO CHUNKER_VERSION bump | UNCHANGED. |
