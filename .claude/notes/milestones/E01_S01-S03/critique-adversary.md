# Critique — E01_S01-S03

**Critic:** adversary
**Generated:** 2026-05-06T00:00:00Z
**Commit range:** 953709e..c486b26
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES: the offline scaffolding is solid, but the seed
  loop has two correctness defects that will silently degrade math
  fidelity on the very 50-paper run the milestone is supposed to prove.
- Finding counts: 0 CRITICAL, 4 HIGH, 4 MEDIUM, 3 LOW.
- Highest-risk file: `tools/fetch_seed.py:107` — bypasses
  `find_main_tex` and feeds an arbitrary `.tex` (often `appendix.tex`)
  to LaTeXML, which usually parses as a tiny doc with no `<math>` and
  is then logged as a silent-math-loss "fail" — a false negative.
- Cross-axis pattern: error handling masks the exact failure modes the
  acceptance gate is meant to surface (LaTeXML timeouts, corrupt
  tarballs, wrong-`.tex` parses) — Threat 3 timeout is set but the
  process_paper loop crashes when it fires.
- E01_S03 acceptance criterion #1 ("`tools/seed-papers.txt` lists 50
  arXiv IDs from category math.AG") is **not met** — the file ships
  with 1 ID. The implementation summary acknowledges this and defers it
  to Phase 4, but the brief asks for the IDs in the commit.
- `make test` does not pin the Python interpreter; on the dev
  machine's default `python3` (3.9.6) collection fails on
  `from datetime import UTC`, so `make test` returns non-zero out of
  the box (acceptance criterion E01_S01 partially violated).
- Politeness contract has helpers (User-Agent, Retry-After parsing,
  503 backoff, 3-s sleep) but **zero tests** of the loop-level
  contract — the 3 s spacing, the User-Agent on every request, and
  the 503 retry path are all uncovered. Brief calls these out.
- No tests cover `_safe_extract` (Threat 1) or `parse_with_latexml`
  (Threat 3) — the very security-critical surfaces the synthesis
  highlights are unverified.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — process_paper bypasses find_main_tex; picks any .tex via rglob

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tools/fetch_seed.py:107`
- **What:** `process_paper` does
  `main_tex = next(raw_paper.rglob("*.tex"), None)` and feeds whatever
  the OS yields first to LaTeXML. The carefully-built `find_main_tex`
  heuristic in `tools/arxiv_fetch.py:166-193` (prefer `<paper_id>.tex`,
  unique-`.tex`, `\documentclass`-search, then alphabetical fallback)
  is unused on the 50-paper path even though `fetch_one_paper.py:39`
  already returns `fetch.main_tex` from `fetch_eprint`.
- **Why it matters:** multi-tex submissions are common (a main file +
  `appendix.tex`/`macros.tex`/`refs.tex`). On those, `rglob` order is
  not guaranteed to be the main file; LaTeXML on `appendix.tex`
  produces a tiny HTML with no `<math>`, which the parse-success
  detector then correctly classifies as failure. The acceptance gate
  (≥45/50) tilts toward false negatives precisely on the papers the
  heuristic was written to handle. This directly undermines the
  "math fidelity over coverage" constraint.
- **Proposed fix:** call `fetch_eprint` once and use
  `fetch_outcome.main_tex` (the `FetchResult` already carries it),
  rather than re-deriving the path. Refactor `fetch_with_backoff` to
  return the `FetchResult` so `process_paper` can read `.main_tex`.
- **Regression guard:** add a unit test that builds a fake raw_dir
  with `appendix.tex` (alphabetically first) and `2307.01156.tex`
  (matching paper_id) and asserts `process_paper`'s code path picks
  the latter — i.e. mock `fetch_with_backoff` to succeed and assert
  on the path passed to a mocked `parse_with_latexml`.

### F2 — LaTeXML timeout + corrupt-tar exceptions kill the seed loop

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tools/fetch_seed.py:117-128`, `tools/fetch_seed.py:95-97`
- **What:** `process_paper` wraps `parse_with_latexml` in
  `except (RuntimeError, OSError)`, but `subprocess.run(..., timeout=)`
  raises `subprocess.TimeoutExpired`, whose MRO is
  `(TimeoutExpired, SubprocessError, Exception)` — neither
  `RuntimeError` nor `OSError`. Same gap in `fetch_with_backoff`'s
  `except (OSError, RuntimeError, ValueError)`: `tarfile.ReadError`,
  `tarfile.CompressionError`, `tarfile.HeaderError` all derive from
  `tarfile.TarError -> Exception`, not `OSError`. Verified at the
  Python REPL.
- **Why it matters:** Threat 3 in `08-security-observability-ops.md`
  mandates a 5-minute timeout precisely so a hostile or malformed
  `.tex` cannot freeze ingestion. The timeout is set
  (`LATEXML_TIMEOUT_SECONDS = 300` at `tools/arxiv_fetch.py:30`) but
  when it fires, the unhandled exception propagates out of
  `process_paper`, escapes the `for` loop in `main()`, and the
  remaining papers are not fetched. Same blast for any malformed
  tarball mid-corpus. The 50-paper loop's "fail open, log, continue"
  invariant is broken on exactly the failure modes the timeout exists
  to handle.
- **Proposed fix:** broaden both `except` tuples to
  `(RuntimeError, OSError, subprocess.TimeoutExpired, tarfile.TarError, gzip.BadGzipFile)`,
  or catch `Exception` at this single boundary. Log the offending
  paper to `seed.log` with status `fail` and message
  `"timeout"` / `"tarball read error: …"` and `continue`.
- **Regression guard:** unit test `process_paper` with
  `parse_with_latexml` monkeypatched to raise
  `subprocess.TimeoutExpired(cmd=[...], timeout=300)`; assert the
  Outcome is `success=False, message="timeout"` and the loop does
  not raise.

### F3 — seed-papers.txt has 1 ID, not the 50 the brief requires

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tools/seed-papers.txt:1-15`
- **What:** the file contains a single arXiv ID (`2307.01156`,
  declared as the S02 smoke-test target). E01_S03 acceptance
  criterion #1 says "tools/seed-papers.txt lists 50 arXiv IDs from
  category math.AG"; that's not satisfied at HEAD.
- **Why it matters:** without 50 IDs, the entire S03 fetch loop
  cannot be exercised (the script even prints
  `WARNING: seed list has 1 IDs, expected 50`). The
  ≥45/50 parse-success gate, the 30–90 minute wall-clock figure,
  and the failure log (`seed.log`) all depend on the list being
  populated. The implementation summary frames this as a deliberate
  Phase-4 gate ("avoiding fabricated arXiv IDs"), which is a
  defensible safety stance — but it means the milestone ships
  incomplete against its own stated acceptance criterion. The
  rectifier needs to either populate the list (running
  `curate_seed.py` is a Phase-4 external write) or get explicit
  user sign-off that the 50-ID criterion is being deferred.
- **Proposed fix:** Phase 4 runs `tools/curate_seed.py
  --max-results 200`, the implementer eyeballs the candidates, picks
  50, and commits them. If the user declines, mark E01_S03
  partially-met and surface the deviation in the milestone exit
  report (do not paper over it in the commit message).
- **Regression guard:** add a startup-time check in `fetch_seed.py`
  that errors out (not just warns) when `len(paper_ids) !=
  EXPECTED_SEED_COUNT` with a `--allow-undersized` opt-out; that way
  the next time someone runs the script with a partial list it
  fails loud.

### F4 — `make test` returns non-zero on the dev machine's default Python

- **Severity:** HIGH
- **Source:** adversary
- **File:** `Makefile:26-28`, `tools/curate_seed.py:37`
- **What:** `make test` invokes plain `pytest`, which on the
  current dev machine resolves to `/usr/bin/python3` (3.9.6).
  `tools/curate_seed.py` does
  `from datetime import UTC, datetime` (3.11+) and the test
  collection therefore fails with
  `ImportError: cannot import name 'UTC' from 'datetime'`. Verified
  by running `python3 -m pytest tests/` at HEAD: collection error,
  no tests run. The implementation summary acknowledges this and
  documents the workaround as "use `python3.13`" — but the brief's
  E01_S01 criterion says `make help` must list `bootstrap`,
  `test`, `up`, `ingest`, and the test target needs to actually
  work for the bootstrap path to deliver value.
- **Why it matters:** any dev who clones the repo and runs
  `make bootstrap && make test` on a machine where `python3` < 3.11
  hits an opaque ImportError instead of green tests. The
  `pyproject.toml` `requires-python` will refuse the install but
  not until `pip install -e .[dev]`; the bootstrap target wraps
  that, so the failure mode is clearer there — except that on
  Python 3.9 the `pip install` could still succeed (deps don't
  block 3.9 install). Net effect: `make test` is brittle.
- **Proposed fix:** in the `test` target, prefix
  `python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"`
  and emit a clear "please use Python ≥3.11; try `python3.11
  -m pytest`" message. Alternatively, declare a `PYTHON ?=
  python3` Makefile variable and use `$(PYTHON) -m pytest` so a
  user can override with `make test PYTHON=python3.13`.
- **Regression guard:** the bootstrap target's `pip install -e
  ".[dev]"` should already fail on Python <3.11 due to
  `requires-python`; assert that explicitly in a smoke check
  inside `bootstrap`, not just `test`.

### F5 — Politeness contract (3-s sleep, 503 backoff) is untested

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_arxiv_fetch.py`, `tests/test_fetch_seed.py`
- **What:** the brief's politeness contract has three load-bearing
  pieces — (a) 3 s sleep between requests, (b) 503 backoff with
  Retry-After, (c) `arXMCP/0.1 (mailto:...)` UA on every request.
  The test suite covers `parse_retry_after` (a pure function) and
  `build_user_agent` (a pure function) but not the loop that uses
  them. The retry path of `fetch_with_backoff` (the actual 503
  handling) is uncovered, and the inter-request sleep at
  `tools/fetch_seed.py:174-175` is uncovered.
- **Why it matters:** the politeness contract is the only thing
  standing between this milestone and an arXiv IP ban. Untested
  contract, untested retry, untested header-on-every-request. If
  someone later refactors the loop and accidentally drops the
  sleep, no test fires.
- **Proposed fix:** add (i) a fake-clock test for `fetch_with_backoff`
  that mocks `urlopen` to raise `HTTPError(code=503,
  headers={"Retry-After": "60"})` once, then succeed; assert
  `time.sleep` was called with 60 (and not less than the floor); (ii)
  a test that runs `main` against a 3-paper seed file with a mocked
  `process_paper` and asserts `time.sleep(POLITENESS_SLEEP_SECONDS)`
  was called exactly twice (between, not before/after); (iii) assert
  every mocked `urlopen` request carried `User-Agent` starting with
  `arXMCP/0.1 (mailto:`.
- **Regression guard:** the tests above ARE the regression guard.

### F6 — `_safe_extract` (Threat 1) and `parse_with_latexml` are untested

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/arxiv_fetch.py:250-266`, `tools/arxiv_fetch.py:269-305`
- **What:** the path-traversal guard (Threat 1 mitigation per
  `08-security-observability-ops.md`) and the LaTeXML invocation
  (Threat 3) have no tests. The protective code itself could regress
  silently — for instance someone removes `filter="data"` from
  `tar.extractall`, or replaces `.resolve()` with `.absolute()` (which
  doesn't follow `..`) and the test suite stays green.
- **Why it matters:** Threats 1 and 3 are the named threat-model
  entries the synthesis quoted. Once they're untested, the only
  signal that they still work comes from the next critic round.
- **Proposed fix:** add a test that builds a `tarfile.TarFile` in
  memory with a member named `../etc/passwd`, asserts
  `_safe_extract` raises `RuntimeError` with the expected message,
  AND that no file was created outside `dest`. Add a test that
  monkeypatches `shutil.which` to return `None` and asserts
  `parse_with_latexml` raises a clear `RuntimeError` mentioning
  `latexml`. Add a test that monkeypatches `subprocess.run` to
  return a `CompletedProcess` with `returncode=1` and assert
  `parse_with_latexml` returns a non-success `ParseResult`.
- **Regression guard:** the tests above.

### F7 — politeness_sleep helper is dead code

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/arxiv_fetch.py:308-312`
- **What:** `politeness_sleep` is exported from the module but never
  called by any caller (`tools/fetch_one_paper.py`,
  `tools/fetch_seed.py`, `tools/curate_seed.py` all sleep inline).
  Confirmed by `grep -rn politeness_sleep tools/` — only the
  definition matches.
- **Why it matters:** dead helper invites future confusion ("was the
  loop supposed to call this?"). It also implies a politeness
  abstraction that the codebase doesn't actually use, which makes
  the politeness contract harder to audit at a glance.
- **Proposed fix:** either delete the function, or refactor
  `fetch_seed.py:174-175` to call it (gives the testable seam F5
  asks for). Prefer the refactor — it gives one canonical home for
  the inter-request spacing rule.
- **Regression guard:** F5's politeness loop test exercises this
  path post-refactor.

### F8 — fetch_eprint does not bound response size; Threat 7 latent

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/arxiv_fetch.py:218-220`
- **What:** `body = resp.read()` reads the entire response into
  memory with no upper bound. `08-security-observability-ops.md`
  Threat 7 explicitly calls out "Content-length sanity checks (a
  single paper > 100 MB source is suspicious)" as a documented
  mitigation. Not implemented.
- **Why it matters:** a malicious or compromised arxiv mirror could
  serve a multi-GB response and OOM the dev machine, which is the
  exact local-first threat model. The synthesis docs cite this
  threat by name.
- **Proposed fix:** read in chunks with a hard cap (e.g. 200 MB);
  raise `RuntimeError("response too large")` past the cap. Or check
  `Content-Length` header and refuse before `read()`.
- **Regression guard:** test that mocks `urlopen` to return a
  response whose `.read()` raises after N bytes / whose
  `Content-Length` exceeds the cap; assert
  `fetch_eprint` raises a clear error.

### F9 — re-running fetch_eprint mixes stale and new files in raw_dir

- **Severity:** LOW
- **Source:** adversary
- **File:** `tools/arxiv_fetch.py:209-247`
- **What:** `raw_dir.mkdir(parents=True, exist_ok=True)` and a
  subsequent `tar.extractall` / gzip write into the same per-paper
  directory without first clearing it. If the prior run extracted
  `appendix.tex` + `main.tex` and the next run downloads a single-file
  gzip variant that only ships `<paper_id>.tex`, the stale
  `appendix.tex` lingers and `find_main_tex` may pick it via the
  `\documentclass` heuristic.
- **Why it matters:** edge case in dev, but it makes the seed corpus
  non-idempotent in a way that could confuse a re-run during E02
  experiments.
- **Proposed fix:** at the top of `fetch_eprint`, after validation but
  before `mkdir`, do `if raw_dir.exists(): shutil.rmtree(raw_dir)`.
  Or move the tarball-extract into a tempdir and rename atomically.
- **Regression guard:** a fixture-based test that pre-populates
  `raw_dir` with a stub file and asserts it's gone after a
  successful fetch.

### F10 — `*.log` blanket-ignore in .gitignore is broader than needed

- **Severity:** LOW
- **Source:** adversary
- **File:** `.gitignore:27`
- **What:** the gitignore line `*.log` matches every `*.log` file
  anywhere in the repo, not just under `var/arxmcp/`. The brief
  asks for `.gitignore` to exclude `/var/arxmcp/`, which is already
  covered on the line above.
- **Why it matters:** if E14's docker-compose ever ships a sample
  `*.log` fixture, it would be silently un-trackable. Defensive
  programming says scope the rule to where logs actually live.
- **Proposed fix:** delete `*.log` (the `/var/arxmcp/` rule above
  already covers `seed.log`), or scope to `/var/arxmcp/**/*.log`.
- **Regression guard:** none; pure config.

### F11 — `urllib.error` imported but unused in arxiv_fetch.py

- **Severity:** LOW
- **Source:** adversary
- **File:** `tools/arxiv_fetch.py:19`
- **What:** `import urllib.error` is at the top of `arxiv_fetch.py`
  but the symbol is never referenced. Ruff's F401 should normally
  flag this; it currently passes (likely because `import urllib.request`
  on the next line tricks F401's parent-module heuristic). The actual
  user of `urllib.error.HTTPError` is `fetch_seed.py:80`, which has
  its own import.
- **Why it matters:** dead import; tiny cognitive cost.
- **Proposed fix:** drop the line.
- **Regression guard:** none.

## What was done well

- The four-part parse-success rule with the explicit silent-math-loss
  guard at `tools/arxiv_fetch.py:113-163` is exactly what the
  synthesis (D4) called for, and the test
  `test_silent_math_loss_caught` correctly anchors the failure mode.
- `--javascript=mathjax` is deliberately NOT passed to `latexmlc`
  (`tools/arxiv_fetch.py:291-296`, comment at :278-279) — math
  fidelity stays on static MathML, no CDN dependency.
- No PyPDF / pymupdf / pdfplumber imports anywhere; the parser-chain
  ban from `04-parsing-and-chunking.md` is honored.
- URLs are pinned to `export.arxiv.org` (synthesis D2) at module
  scope (`ARXIV_EPRINT_URL`, `ARXIV_API_URL`), so SSRF via
  `paper_id` is blocked before formatting via `validate_paper_id`.
- `_safe_extract` uses `.resolve()` + `.relative_to()` AND
  `tar.extractall(filter="data")` — defense in depth; both layers
  catch absolute-path / `..` traversals.
- `LATEXML_TIMEOUT_SECONDS = 300` matches Threat 3's stated 5-minute
  hard cap; the timeout is wired through to `subprocess.run`.
- `build_user_agent` raises if `ARXMCP_CONTACT_EMAIL` is unset
  (no anonymous traffic), with a clear actionable error message.
- The seed-list reader correctly handles blanks, leading-whitespace
  comments, and trailing whitespace — and the tests exercise all
  four edge cases.
- No tier-1 over-reach: no ar5iv lookup, no theorem+proof pairing, no
  hierarchical chunker. The repo correctly stays at LaTeXML on
  `/e-print/`.
- Commit shape matches synthesis section 8: three logical commits,
  one per sub-issue, in dependency order.

## Recommended rectification order

1. **F2** (timeout/tarball exception escape) — the seed loop will
   crash on the very first malformed paper otherwise; fix this
   before any actual run.
2. **F1** (process_paper bypasses find_main_tex) — silently
   degrades the parse-success rate; tests for F1 also stress the
   `find_main_tex` heuristic the rectifier should keep.
3. **F4** (`make test` non-zero on default Python) — every other
   rectification touches tests; the test runner needs to work.
4. **F3** (50 IDs missing) — once F2/F1/F4 land, the milestone is
   ready to actually run; populating the seed list is the gate.
5. **F5** + **F6** (politeness + threat-model tests) — fix together;
   they share infra (mocked `urlopen`, monkeypatched `time.sleep`).
6. **F7** (delete or wire up `politeness_sleep`) — pair with F5's
   refactor.
7. **F8** (response size cap) — defense in depth.
8. **F9, F10, F11** — opportunistic; no need to gate the milestone
   on them.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate. -->
