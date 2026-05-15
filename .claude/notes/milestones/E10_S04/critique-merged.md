# E10_S04 — Adversary Critique

**Scope:** commit `9be3a02` (`1a52ff5..9be3a02`) — the LaTeXML drift
detector. Read against the synthesis D1–D14 narrowing, which
intentionally drops `tikz-cd`, defers Prometheus `/metrics` exposure
to E14, and corrects the brief's `--rerender-all` runbook reference.
Findings below target only the code that DID land.

---

## Executive summary

- **Verdict: PARTIAL.** The diff logic, sentinel, counter, fixture
  story, and integration test all hold up. Three real bugs land in
  the test surface and one in the runbook; none threaten production
  correctness but the most prominent — a test whose docstring
  promises AC1 happy-path and whose body asserts the opposite — is a
  load-bearing signal of carelessness in the very test that pins
  AC1's CLI path.
- AC1 is closed only by the `requires_latexmlc`-marked integration
  test, which is skipped by default. The mock-layer "no drift" path
  is NOT exercised by any test in the suite that runs on `make test`
  — i.e. on every push, AC1 is verified by silence, not assertion.
- Docker container does not install LaTeXML; the cron job will fail
  if anyone runs it in the project's containerized deployment as
  documented in the Dockerfile. The runbook does not warn about this.
- `extract_canonical_mathml` returns `""` for HTML with no `<math>`
  elements, and `_read_expected` returns `""` when the baseline file
  is missing — both empty. Running `--update-fixtures` against a
  catastrophically broken LaTeXML (produces no MathML) would
  rebaseline every fixture to `""` and then "pass" subsequent runs.
- The runbook step 3c's "NULL out the column first" workflow is an
  inline Python snippet with neither documented LanceDB connect call
  nor a real `--force` flag in `ingest.embed_equations` — the
  operator must hand-write working Python under stress. Reasonable
  for a one-time event but flagged as documentation debt.
- The runbook's bash for-loop `for paper_id in $(ls
  var/arxmcp/corpus/parsed/)` is fragile to whitespace, hidden files
  (e.g. `.DS_Store` on macOS, which the operator's session WILL
  have), and any future non-directory artifact in that path.
- Cache byte-stability axis (BP1 + tools/list hash) is CLEAN. No
  changes to `server/tools.py`, `tests/test_server_tool_schema.py`,
  `tests/test_prompts.py`, `server/schemas/`. Confirmed by
  `git diff --stat`.
- Many things are done well — see "What was done well" below for the
  10-bullet positive set.

---

## Severity calibration

| Severity | Definition |
|---|---|
| **CRITICAL** | Data loss / security boundary / broken invariant. **0 findings.** |
| **HIGH** | Wrong behavior on a common path; AC closure compromised. **2 findings.** |
| **MEDIUM** | Subtle correctness; missing test that lets a regression slip; documentation that misleads under operator pressure. **5 findings.** |
| **LOW** | Style; nit; latent fragility unlikely to trip in practice. **3 findings.** |

---

## Findings

### F1 — `test_cli_exits_zero_on_no_drift` is the wrong test under the right name

**Severity:** HIGH
**Where:** `tests/test_drift_check.py:233-276`
**What:** The test is named for AC1's happy path ("exits zero on no
drift") and its docstring promises "when no drift is detected, the
CLI exits 0, prints `ok`, and does NOT write the sentinel." The body
asserts `rc == 1` and `sentinel.is_file()`. The test acknowledges
in its own inline comment (`# With the simple static mock, every
fixture's actual is ``expected_str`` (frac's baseline)…`) that the
static mock only matches `frac` and the other four DO drift, so the
CLI exits 1. It also defines an unused `_per_fixture_actual` closure
that was abandoned mid-implementation. The test as committed is
indistinguishable from `test_cli_exits_one_on_drift` (lines 278–299)
— so the AC1 CLI happy-path is not exercised at all in the default
suite. Only the `requires_latexmlc` integration test
(`test_all_fixtures_match_baselines`) covers the all-pass scenario,
and that test is skipped by default.
**Why it matters:** A future regression where the CLI fails to clear
the sentinel or exit 0 on a clean run is undetectable by `make test`.
A reviewer scanning test names sees AC1 closed; in reality the test
is a duplicate of the AC2 drift test. The implementation-summary's
own claim that AC1 is "verified empirically" by the integration test
is correct, but per the synthesis D7 the default suite was supposed
to cover this via mocks.
**How to fix:** Use `mock.patch` with `side_effect=lambda html:
per_fixture_table[caller_name]` — or, simpler, monkey-patch
`check_fixture` itself (not its dependencies) to return non-drifted
`DriftResult` for every fixture, and assert `rc == 0`, `not
sentinel.is_file()`, and the captured stdout contains `"ok:"`. Then
rename the current "exits zero" test for what it actually tests, or
delete it (the AC2 drift test already exists).

### F2 — `extract_canonical_mathml` silently returns `""` for math-free HTML, and `_read_expected` silently returns `""` for a missing baseline file — opening a `"" == ""` silent-pass path

**Severity:** HIGH
**Where:** `ops/drift_check.py:172-188` (`extract_canonical_mathml`)
+ `ops/drift_check.py:212-223` (`_read_expected`) + `ops/drift_check.py:276-296`
(`update_fixtures`).
**What:** Three behaviors compound. (1) `extract_canonical_mathml`
returns `""` when the HTML has no `<math>` elements — by design,
documented in the docstring. (2) `_read_expected` returns `""` when
the baseline file does not exist — also by design, documented. (3)
`update_fixtures` writes whatever `extract_canonical_mathml` returns,
including `""`, into the baseline file unconditionally. If an
operator runs `python -m ops.drift_check --update-fixtures` against
a LaTeXML installation that's broken in a way that drops the math
element (e.g. a malformed `--format` flag in a future refactor,
LaTeXML upgrade that crashes mid-render but exits 0 with a stub
HTML, or a buggy macOS Homebrew formula), every baseline file will
be overwritten with `""`. Subsequent `--check` runs will report
`actual == ""` matches `expected == ""` — all 5 fixtures "pass."
**Why it matters:** This is the silent-corruption mode the drift
detector exists to prevent. The operator running
`--update-fixtures` after a "deliberate LaTeXML upgrade" (the
synthesis D8 workflow) is the exact scenario where this is most
likely. The integration test catches it ONLY if the operator runs
`pytest -m requires_latexmlc` after rebaselining and BEFORE
committing — but the runbook (step 5) does not document this gate.
**How to fix:** Add a precondition in `update_fixtures`: if the
extracted MathML is empty, raise `RuntimeError(f"refusing to write
empty baseline for {tex_path.name}: latexmlc produced no <math>
elements")`. Optionally a `--allow-empty` escape hatch for future
math-free fixtures (none exist today). Symmetrically, `check_fixture`
should distinguish "empty actual matches empty expected" (likely a
broken fixture) from "non-empty actual matches non-empty expected"
(the real pass) — or at minimum log a WARNING when both sides are
empty.

### F3 — Docker container does not install LaTeXML; cron job is unrunnable inside the documented runtime

**Severity:** MEDIUM
**Where:** `docker/Dockerfile.server` — `apt-get install` line
installs only `tini`, `curl`, `ca-certificates`. No `latexml` package.
The drift detector is implicitly host-only.
**What:** The project's documented runtime is the multi-stage
Dockerfile at `docker/Dockerfile.server`; the README quickstart
links to `docs/install.md`. The drift-check shell script
unconditionally invokes `${UV_BIN}` against a host-installed
`latexmlc`. Running `ops/cron/latexml-drift-check.sh` inside the
runtime container would fail with the friendly "latexmlc not found"
RuntimeError — but the cron-jobs.md registry says the entry is the
shell script, and the runbook step 1 (`latexmlc --VERSION`) assumes
LaTeXML is present. There is no documented "this script runs on the
host, not in the container" boundary.
**Why it matters:** Synthesis §1 finding #1 establishes that "the
operator's LaTeXML" is what produces the index. If ingest runs
inside the container (per E11 production-ingest plans) and the
container has no `latexml` package, the operator can never run the
drift check against the actual rendering substrate. The host-only
drift check would then guard a different LaTeXML version than the
one shipping into production.
**How to fix:** Either (a) add `latexml` (the Debian package) to
the Dockerfile's runtime `apt-get install` block, AND document in
the runbook + cron-jobs.md that the cron runs against the
in-container `latexmlc`, OR (b) add a `## Container note` paragraph
to `docs/ops/latexml-drift-runbook.md` and the README's Operations
section explicitly noting "this v1 drift check runs against the
HOST `latexmlc`; container alignment is E11 scope." Pick one; either
is acceptable. Don't ship neither.

### F4 — `test_cli_exits_zero_on_no_drift` leaves dead code (`_per_fixture_actual`) that confuses future readers

**Severity:** LOW
**Where:** `tests/test_drift_check.py:252-260`
**What:** A nested `_per_fixture_actual` function is defined inside
`test_cli_exits_zero_on_no_drift` and never called. Its body returns
the empty string regardless of input. The surrounding comment
documents that the closure was a draft of a per-fixture mock
strategy that was abandoned. Ruff is configured for this project
(per CLAUDE.md §4.5) and presumably reports `F841 local variable
assigned but never used` — but a nested `def` is not a variable
assignment, so it slips through.
**Why it matters:** A future agent rectifying F1 will trip over this
half-implemented closure and may waste time deciding whether it
encodes intent. Dead code in a test that is itself misnamed is a
double signal of incomplete work.
**How to fix:** Delete `_per_fixture_actual` when F1 is rectified.
If the F1 fix uses the closure approach, name it properly and
wire it via `side_effect=`.

### F5 — `extract_canonical_mathml` is byte-stable for attribute order (BS4 alphabetizes) but NOT for whitespace inside `<math>`

**Severity:** MEDIUM
**Where:** `ops/drift_check.py:186-188` —
`BeautifulSoup(html, "html.parser")` + `str(m)`.
**What:** Verified empirically: BS4's `html.parser` alphabetizes
attributes at serialization time, so `<math b="2" a="1">` and
`<math a="1" b="2">` both serialize as `<math a="1" b="2">`. That
is the synthesis D2 stability guarantee — good. HOWEVER: whitespace
inside the `<math>` body is preserved verbatim. A LaTeXML upgrade
that emits `<mi>x</mi><mo>+</mo><mi>y</mi>` vs
`<mi>x</mi>  <mo>+</mo>  <mi>y</mi>` would trigger drift for a
visually-identical AST. The synthesis acknowledged this as
acceptable noise but the docstring at lines 172–185 frames the diff
as "stable across runs of the same LaTeXML version" without warning
about cross-version whitespace sensitivity.
**Why it matters:** False-positive drift signals from cosmetic
whitespace are exactly the failure mode the synthesis flagged as
"the operator inspects the diff via `git diff`-style tooling" — but
those diffs will be unreadable when the only change is whitespace
runs. AC1's integration test runs against the SAME LaTeXML that
captured the baselines, so it does not exercise this path.
**How to fix:** Document the limitation in
`ops/drift_check.py::extract_canonical_mathml`'s docstring
("whitespace inside `<math>` is preserved verbatim; cross-LaTeXML-
version whitespace changes WILL trigger drift even when the AST is
semantically identical"). Optionally a v2 enhancement: normalize
runs of whitespace inside `<math>` to a single space before joining.
v1 should at least name the trade.

### F6 — Runbook step 3 `for paper_id in $(ls var/arxmcp/corpus/parsed/)` is shell-fragile

**Severity:** MEDIUM
**Where:** `docs/ops/latexml-drift-runbook.md:59-61`
**What:** Two real problems. (1) `ls`-piped-to-for-loop word-splits
on whitespace and glob characters; arXiv paper ids include `.` and
`/` so the loop body is technically safe today, but the operator's
checkout often contains macOS `.DS_Store` files in directories that
have been opened in Finder — running `python -m ingest.extract_equations
.DS_Store` would raise the `is_valid_paper_id` check (good) but
fill the operator's terminal with stack traces. (2) An empty parsed
directory would render the loop a no-op silently — no failure
signal.
**Why it matters:** The runbook is invoked under pressure (drift
detected at 02:30 UTC, operator triages in the morning). Operator
ergonomics matter. The "correct" idiom is `find
var/arxmcp/corpus/parsed -mindepth 1 -maxdepth 1 -type d -exec
basename {} \; | sort` or equivalent.
**How to fix:** Replace with:
```bash
find var/arxmcp/corpus/parsed -mindepth 1 -maxdepth 1 -type d \
    -printf '%f\n' | while read -r paper_id; do
    python -m ingest.extract_equations "$paper_id"
done
```
The `-printf '%f\n'` is GNU-specific; macOS operators need
`-exec basename {} \;`. The runbook should pick the form that
works on the platform Chris's deployment runs on (likely Linux for
prod, macOS for dev) — or document both.

### F7 — Runbook step 3c's "NULL out the column first" is a hand-wavy multi-line Python snippet inside a bash code block

**Severity:** MEDIUM
**Where:** `docs/ops/latexml-drift-runbook.md:70-78`
**What:** The runbook commits an inline Python snippet (wrapped in
backticks inside a bash comment) telling the operator to call
`lancedb.connect(...).open_table("equations").update(...)` to NULL
the `embedding_eq` column. There is no documented `connect(<path>)`
argument, no import statement, no error handling, no idempotency
check. The actual `ingest.embed_equations` CLI (verified at
`ingest/embed_equations.py:145+`) does NOT have a `--force` or
`--re-embed-all` flag — so the operator cannot use the official CLI
to force re-embed.
**Why it matters:** This is the SAME class of bug the runbook's D11
fix corrected for the brief's `--rerender-all` nonexistent flag.
Replacing one fictitious flag with a hand-typed Python one-liner
that the operator must extract from a bash code block, wrap in
proper Python, and execute under stress is a downgrade in operator
ergonomics, not an upgrade.
**How to fix:** Either (a) add a `--force` or `--re-embed-all` flag
to `ingest/embed_equations.py` as a proper CLI option and reference
it from the runbook (matches the synthesis spirit that ingest
modules should expose first-class workflows), OR (b) extract the
snippet into a script like `ops/scripts/null_embedding_eq.py` and
the runbook just runs it. The brief was clear that the production
ingest driver lands in E11; if (a) is out of scope, ship (b).

### F8 — `LATEXML_DRIFT_DETECTED_COUNTER` is defined but never scraped — the AC3 verification reaches into the private `._value` attribute

**Severity:** LOW
**Where:** `server/metrics.py:166-177` + `tests/test_drift_check.py:156-159`
**What:** The counter is registered with the default
`prometheus_client` registry. The server's `/metrics` endpoint does
NOT include it in any scraped path because the cron process is
distinct from the server process (synthesis D6: deferred to E14).
Tests verify the increment via `LATEXML_DRIFT_DETECTED_COUNTER.labels(
fixture="frac")._value.get()` — touching the documented-private
`_value` attribute. This is exactly the test-only escape hatch
documented at `server/metrics.py:241` ("private API but stable
across prometheus_client 0.16+"), so it's not wrong per se. But the
counter has zero production wiring at v1 — its only observer is the
test suite. Synthesis D6 owns the deferral, so this is documented
debt, not a bug.
**Why it matters:** The AC3 "counter increments when drift detected
(verifiable via test)" is technically satisfied, but the
operationally-useful signal is the sentinel file + non-zero exit
code, not the counter. If a future agent removes the counter
thinking it's dead code, no production observer will fail — only
the AC3 test will. That's defensible but worth pinning in the
metric's docstring.
**How to fix:** Add a one-line `**Production exposure deferred to
E14**` to the counter's docstring at `server/metrics.py:166-177`
and a `pytest.ini`-side note linking the AC3 test to E14 follow-up.
Acceptable as-is per synthesis D6.

### F9 — No test guards the "missing baseline file" path, but `_read_expected` returns `""` silently

**Severity:** MEDIUM
**Where:** `ops/drift_check.py:212-223` + `tests/test_drift_check.py`
(no test for missing baseline).
**What:** `_read_expected` silently returns `""` when the baseline
file is missing. The docstring claims this "lets the drift detector
flag any fixture that was added without a baseline" — true ONLY if
the actual MathML is non-empty (`actual != ""`). Combined with F2,
a missing baseline + a math-free `.tex` would silently pass. No
test exercises the missing-baseline path. Adding a new
`.tex` fixture without running `--update-fixtures` will trip the
counter on the first cron run (good!) but it's not regression-
guarded.
**Why it matters:** The "fixture added without baseline" workflow
is exactly the case where an operator forgets the `--update-fixtures`
step in a PR that adds a 6th fixture. The drift detector flagging it
is the right behavior; an absence of a test guarding it means a
future refactor that changes `_read_expected` (e.g. to raise on
missing baseline, which would be a reasonable design change) would
ship undetected.
**How to fix:** Add a `tests/test_drift_check.py` test that creates
a `.tex` fixture without an `.expected.mathml` file (in
`tmp_fixture_dir`), runs `check_fixture`, and asserts
`result.drifted is True` and `result.expected == ""`.

### F10 — `requires_latexmlc` integration class has both the marker AND a `skipif(not _have_latexmlc())` guard — defense-in-depth but adds confusion

**Severity:** LOW
**Where:** `tests/test_drift_check.py:384-395`
**What:** The class is decorated with both
`@pytest.mark.requires_latexmlc` AND
`@pytest.mark.skipif(not _have_latexmlc(), reason=...)`. The marker
means the test is skipped by default unless explicitly selected
(`pytest -m requires_latexmlc`); the `skipif` means the test is
skipped if `latexmlc` is absent. The combination: even with
`pytest -m requires_latexmlc`, the test will skip on a machine
without LaTeXML — defensible defense-in-depth. But the
implementation-summary claims the integration tests "ran the real
`latexmlc` binary locally during this session" — verified, but if
a future CI environment opts into `requires_latexmlc` without
installing LaTeXML, the test will silently skip rather than fail.
The synthesis D7 only required the marker; the skipif is over-
defensive.
**Why it matters:** Skipped tests are silent in pytest's default
output; an opt-in run that all skips is indistinguishable from a
run that all passes. CI dashboards may report "PASS" for a no-op.
**How to fix:** Pick one. Either (a) drop the `skipif` and let
`pytest -m requires_latexmlc` fail loudly when `latexmlc` is missing
(via `RuntimeError` from `_require_latexmlc()`), OR (b) keep the
`skipif` and remove the marker, treating LaTeXML as a host-detection
dependency. (a) is the more defensible choice for a project that
will run `pytest -m requires_latexmlc` in a `latexml`-equipped
CI matrix.

---

## What was done well

1. **Synthesis D2 — extracted-`<math>` diff strategy — is implemented
   exactly.** The `BeautifulSoup(html, "html.parser")` +
   `find_all("math")` + `str(m)` join pattern matches what
   `ingest/extract_equations.py` already uses for `_serialize_mathml`;
   pattern-coherence with the existing codebase is a real win.
2. **`render_fixture` stages the input into a tmpdir** to keep
   `latexmlc`'s alongside-input `.latexml.log` from polluting the
   checked-in fixture directory. The
   `test_render_fixture_does_not_leave_log_artifact` regression test
   is exactly the right shape — snapshot before/after, diff the dir
   sets, assert empty diff.
3. **`subprocess.run` uses argv-form, no `shell=True`, with
   `capture_output=True` and a `timeout=`** matching synthesis D9's
   15-second budget. The `noqa: S603` annotation correctly defangs
   the ruff warning without disabling it project-wide.
4. **`_require_latexmlc` matches the existing
   `tools/arxiv_fetch.py::_require_latexmlc` discipline** — same
   error-message pattern, same `shutil.which` lookup. Pattern
   consistency saves the operator from having to learn two install
   stories.
5. **`text=True, encoding="utf-8"` on `subprocess.run` and on every
   `read_text`/`write_text`** — defensive against locale-default-
   encoding drift on macOS/Windows. The synthesis didn't even flag
   this; the implementation got it right anyway.
6. **`DriftResult` is `@dataclass(frozen=True, slots=True)`** — both
   the immutability guard against accidental mutation in a loop
   accumulator AND the memory-efficiency of `__slots__`. Minor but
   reflects taste.
7. **`reset_drift_metrics_for_tests` walks
   `LATEXML_DRIFT_DETECTED_COUNTER._metrics.values()`** dynamically
   so newly-created label tuples are caught — better than the
   hardcoded-tier-list pattern in `reset_cache_metrics_for_tests`,
   which would need maintenance every time a new tier is added.
   Verified working empirically.
8. **CLAUDE.md doc-layout rules respected.** No `.md` files added to
   `server/`, `ingest/`, `tools/`, `shim/`, `docker/`, or `infra/`.
   `docs/ops/` is operator-facing and linked from the README, exactly
   the rule's exception. `.claude/docs/ops/cron-jobs.md` is
   agent-internal. Synthesis §2's split was honored.
9. **No changes to** `server/tools.py`,
   `tests/test_server_tool_schema.py`, `tests/test_prompts.py`,
   `server/schemas/search_papers_result.json`. BP1 cache discipline
   is intact; no hash repins. Confirmed by `git diff --stat`.
10. **The implementation summary's "Deviations from the brief" section
    is honest and complete** — three explicit deviations
    (tikz-cd, Prometheus exposure, runbook flag), each with
    rationale and a pointer to the synthesis decision that authorized
    it. A future agent reading the summary will not "fix" them
    without explicit user direction.

---

## Recommended rectification order

1. **F1** — fix the misnamed-and-wrong AC1 test FIRST. It's the
   most visible bug; the test name lies about coverage and a future
   reader will trip on it.
2. **F2** — guard `update_fixtures` against an empty actual; raise
   `RuntimeError` to prevent the silent-corruption rebase path.
   Critical for the synthesis-D8 operator workflow.
3. **F9** — add the missing-baseline regression test. Pairs naturally
   with F2's fix.
4. **F3** — make the Container note explicit OR install `latexml` in
   the Dockerfile. Pick one path; the runbook must say which.
5. **F6** — replace `ls | for-loop` with `find` in the runbook.
6. **F7** — either add `--force` to `ingest.embed_equations` or
   extract the NULL-the-column snippet into a script. Pick one.
7. **F5** — document the whitespace-sensitivity in the
   `extract_canonical_mathml` docstring.
8. **F8** — add the "deferred to E14" line to the counter docstring.
9. **F4** — delete dead `_per_fixture_actual` (mechanical; happens as
   part of F1).
10. **F10** — pick marker XOR skipif; align with the CI matrix plan.

---

## Rectification status (Phase 4)

Re-verify ran for all 10 findings. None invalidated; every cited
file:line region matched the critique's "what" claim.

- **F1 (HIGH) — fixed.** `test_cli_exits_zero_on_no_drift` rewritten
  with `patch("ops.drift_check.check_fixture", side_effect=...)`
  returning a non-drifted `DriftResult` for every fixture. Asserts
  `rc == 0`, sentinel NOT written, `"ok:"` in stdout. AC1 CLI
  happy-path now exercised in the default suite.
- **F2 (HIGH) — fixed.** `update_fixtures` raises `RuntimeError`
  when `extract_canonical_mathml` returns empty. Two regression
  tests: `test_update_fixtures_refuses_empty_actual` +
  `test_update_fixtures_allow_empty_override` (escape hatch).
- **F3 (MEDIUM) — fixed.** "Container note" added at the top of
  `docs/ops/latexml-drift-runbook.md` documenting the
  host-vs-container LaTeXML boundary. Container alignment
  deferred to E11.
- **F4 (LOW) — fixed.** Dead `_per_fixture_actual` closure deleted
  as part of F1's rewrite.
- **F5 (MEDIUM) — fixed.** `extract_canonical_mathml` docstring
  notes the whitespace-sensitivity limitation.
- **F6 (MEDIUM) — fixed.** Runbook step 3a replaced
  `for paper_id in $(ls var/arxmcp/corpus/parsed/)` with
  `find ... -mindepth 1 -maxdepth 1 -type d -exec basename {} \;`
  (portable across GNU/BSD).
- **F7 (MEDIUM) — fixed.** Added `--force` flag to
  `ingest/embed_equations.py`. Replaces the runbook's hand-typed
  LanceDB Python snippet. Runbook step 3c updated.
- **F8 (LOW) — fixed (docs).** Counter docstring at
  `server/metrics.py` notes the production-exposure deferral to
  E14 and that removing the counter would only break AC3.
- **F9 (MEDIUM) — fixed.** Regression test
  `test_check_fixture_with_missing_baseline_drifts` pins the
  contract that a fixture without a baseline file drifts cleanly.
- **F10 (LOW) — fixed.** Removed the redundant
  `@pytest.mark.skipif` on `TestIntegrationRealLatexmlc`. The
  `requires_latexmlc` marker alone gates; opt-in without LaTeXML
  installed raises loudly via `_require_latexmlc()`.

**Invalidation rate:** 0 / 10 findings invalidated (0%). Adversary
critic was well-calibrated.

**Test count delta after rectify:** 1474 passing (+3 regression
guards from post-implement 1471). 4 skipped (`requires_model`), 0
failed, ruff clean.

| Finding | Severity | Status |
|---|---|---|
| F1 — misnamed CLI test | HIGH | fixed (regression test rewritten) |
| F2 — silent empty-baseline rebase | HIGH | fixed (regression test) |
| F3 — Docker container missing LaTeXML | MEDIUM | fixed (Container note) |
| F4 — dead `_per_fixture_actual` closure | LOW | fixed (deleted) |
| F5 — whitespace sensitivity | MEDIUM | fixed (docstring) |
| F6 — fragile bash `ls \| for` | MEDIUM | fixed (find -exec) |
| F7 — hand-wavy NULL-the-column snippet | MEDIUM | fixed (`--force` flag) |
| F8 — counter exposure deferral undocumented | LOW | fixed (docstring) |
| F9 — missing-baseline path untested | MEDIUM | fixed (regression test) |
| F10 — marker+skipif silent-skip | LOW | fixed (skipif removed) |
