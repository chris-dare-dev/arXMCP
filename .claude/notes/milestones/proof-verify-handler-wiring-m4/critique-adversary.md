# Critique — proof-verify-handler-wiring-m4

**Critic:** adversary
**Generated:** 2026-05-21T22:25:00Z
**Commit range:** `8cb1e94c303c12a83e76824d8fd0179e88dd3721..2de87536780197ba93098533e4606eaaa9ea9eac`
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Single-commit, single-script feature (`tools/validate_notebook_fixtures.py`
  + 29 tests + CHANGES.md) plus two manually-written data sentinels;
  surface is small and the validator is correct on the common path.
- Finding counts: 0 CRITICAL, 1 HIGH, 4 MEDIUM, 2 LOW. The HIGH is the
  "m3 follow-up backlog" that doesn't exist — `docs/ops/notebook-modes.md`
  ships a recipe that hard-fails at daemon startup under `extra="forbid"`,
  and the only record of that bug is a single bullet in the m4 impl-summary.
- Highest-risk finding: `docs/ops/notebook-modes.md:64,73` — operators
  following the runbook hit `pydantic_settings` parse failure immediately;
  no GH issue, no OWNERS.md note, no m3 state.json entry tracks the fix.
- The two "real-notebook happy-path" tests
  (`tests/tools/test_validate_notebook_fixtures.py:117-137`) couple
  the validator to live on-disk fixtures; the test docstrings say "Hard
  pin — if curation changes ... both must move together" but neither
  the validator nor the live fixtures carry a back-pointer comment.
- BM25 sentinels diverge byte-wise from what `notebook_ingest.py` would
  write (manual files contain trailing `\n`; script writes no trailing
  newline) — harmless today because the only consumer uses `.strip()`,
  but it's a "manually patched data file with no test" footprint.
- Test surface is good (29 tests, all parametrized cases for missing keys),
  but the validator delegates `is_valid_paper_id` boundary classes
  (trailing-newline / CR / leading-whitespace) entirely to the m1-rect-F3
  upstream coverage with no defensive duplication or cross-reference.
- Cache byte-stability: clean — diff does not touch `server/tools.py`,
  `server/prompts.py`, or any handler envelope.
- Doc placement: clean — all milestone artifacts live under
  `.claude/notes/milestones/`; the single user-facing edit is to
  `CHANGES.md` (an allowed root file).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — m3 runbook recipe hard-fails; "backlog" is not tracked anywhere

- **Severity:** HIGH
- **Source:** adversary
- **File:** `docs/ops/notebook-modes.md:64`, `docs/ops/notebook-modes.md:73`;
  evidence in `server/config.py:82` (`extra="forbid"`) and
  `.claude/notes/milestones/proof-verify-handler-wiring-m4/implementation-summary.md:128-135`
- **What:** The Mode-1 launch recipe instructs operators to `export
  ARXMCP_CONTACT_EMAIL=you@example.com` and then run `uv run python -m
  server.main`. `server/config.py:79-82` declares
  `SettingsConfigDict(env_prefix="ARXMCP_", extra="forbid", ...)` and no
  `contact_email` field exists on the `Config` model, so the daemon
  raises `ValidationError` on startup. The m4 implementer hit this
  empirically during AC #5 verification, worked around it by dropping
  the env var, and recorded the finding ONLY in the m4 implementation
  summary's "Deviations" section. There is no GH issue, no OWNERS.md
  TODO, no entry in `.claude/notes/milestones/proof-verify-handler-wiring-m3/state.json`,
  and no `docs/ops/notebook-modes.md` warning callout. The "m3 follow-up
  backlog" the summary defers to is a phrase, not an artifact.
- **Why it matters:** Any operator following the shipped runbook in
  good faith will see daemon startup fail with a pydantic error and no
  documented remedy. The fix-it-now cost is ~5 lines (delete the two
  `ARXMCP_CONTACT_EMAIL=...` lines from the runbook OR declare a
  no-op `contact_email: str | None = None` field on `Config`). The
  cost of forgetting until a future operator stumbles on it is a
  silent UX regression that the m3 critic-merged file would not catch
  on re-review (because nothing in the diff or notes flags it as
  open).
- **Proposed fix:** EITHER (a) edit `docs/ops/notebook-modes.md`
  lines 62-64, 71-73, and any other recipe that mentions
  `ARXMCP_CONTACT_EMAIL` for daemon launch — remove the two
  occurrences, add a one-line note ("`ARXMCP_CONTACT_EMAIL` is an
  ingest-time var, not a daemon-launch var — `server/config.py`
  rejects unknown `ARXMCP_*` vars at startup"); OR (b) declare an
  optional `contact_email: str | None = None` field on the `Config`
  model so the env var is tolerated even if unused. Option (a) is
  more honest and ~30 LOC; option (b) widens the config surface.
  Either way, surface the SAME fix to the second deferred-bug —
  the m3 runbook's "stateless `tools/call` sanity check" recipe
  also empirically fails (summary line 136-142) and should either
  be removed or replaced with the spec-compliant handshake recipe
  the m4 smoke test actually used.
- **Regression guard:** Add a smoke test under
  `tests/test_server_main.py` (or a new `tests/test_runbook_recipes.py`)
  that invokes `Config(...)` with `ARXMCP_CONTACT_EMAIL=test@example.com`
  in the environment and asserts the result is one of (a) accepted (if
  fix is option b), or (b) explicitly raises with a message naming the
  offending var (if fix is option a — the current `pydantic_settings`
  message names "extra inputs are not permitted"). Either way, the
  test pins the runbook contract.

### F2 — Validator IOError paths are uncaught; contract violation

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/validate_notebook_fixtures.py:179`,
  `tools/validate_notebook_fixtures.py:186-192`
- **What:** The validator's module docstring promises "Exits 0 on
  pass; non-zero with a single-line error to stderr on fail" (line
  29-31). After the `is_file()` checks at lines 170-177, the script
  proceeds to `read_paper_ids_from_papers_txt(papers_path)` (which
  internally calls `papers_txt.read_text(encoding="utf-8")` at
  `tools/_notebook_common.py:131`) and `queries_path.open(encoding="utf-8")`
  at line 186. A `PermissionError`, `OSError`, or a TOCTOU race
  between `is_file()` and `read_text()` would propagate as a raw
  Python traceback rather than the documented single-line stderr
  message. Same applies to `json.JSONDecodeError` — wait, that one IS
  caught at line 189. Just the IOError class isn't.
- **Why it matters:** Minor UX defect on edge cases. Operator-facing
  CLI shouldn't dump a Python traceback when a file is unreadable;
  it should report `FAIL: papers.txt at <path> is unreadable: <errno>`.
  This is documented contract drift, not a security issue.
- **Proposed fix:** Wrap the `read_paper_ids_from_papers_txt` call
  and the `queries_path.open` block in `try: ... except OSError as e:
  raise FixtureValidationError(f"...unreadable: {e}") from e`. ~6
  LOC. The existing `FixtureValidationError` handler in `main()`
  (line 217) already gives the right exit code (1) and the right
  format (`FAIL: <message>`).
- **Regression guard:** Add a parametrized test under
  `TestTopLevelStructure` that `os.chmod`'s either file to `0o000`,
  asserts `FixtureValidationError` is raised, and restores perms in
  a finally block. Skip on Windows (which doesn't honor POSIX chmod
  modes the same way) and on macOS+root.

### F3 — "Hard pin" real-notebook tests have no cross-reference comment

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/tools/test_validate_notebook_fixtures.py:117-137`
  (the two `test_real_*_notebook_validates` methods) and
  `tools/validate_notebook_fixtures.py` (the entire file)
- **What:** The test docstring at line 119-122 says: "Hard pin — if
  curation changes the schema in a way that breaks the validator,
  both this test and the validator must move together." But neither
  the validator nor the live `var/arxmcp/notebooks/<slug>/queries.json`
  files carry a comment naming this test as a guard. If a future
  curator edits `queries.json` to add a new required field, the
  validator's `REQUIRED_TOP_KEYS` frozenset (line 57-63) won't
  surface that the test is the lockstep partner. The implementer
  summary correctly flags this concern in the impl-summary's task
  list but no in-code marker landed.
- **Why it matters:** Test-to-data coupling without a back-pointer is
  fragile in a multi-month maintenance window. A future agent
  editing `REQUIRED_TOP_KEYS` to add `curated_by` (currently
  OPTIONAL) without also re-running the real-notebook tests would
  break CI silently if either notebook's `queries.json` is missing
  the new key. Low-probability but the cost of inoculation is one
  comment.
- **Proposed fix:** Add a one-line comment above the
  `REQUIRED_TOP_KEYS` frozenset literal in
  `tools/validate_notebook_fixtures.py:57` pointing at
  `tests/tools/test_validate_notebook_fixtures.py::TestHappyPath::test_real_bridgeland_notebook_validates`
  (or shorter — just "If you edit this, also run TestHappyPath
  real-notebook tests"). Optionally add a similar marker to
  `var/arxmcp/notebooks/<slug>/queries.json` via a top-level
  `_schema_owner` field (not required but defensive).
- **Regression guard:** None required — this is a comment-only fix.
  If the marker is later promoted to a `_schema_owner` field, add a
  test that asserts both real fixtures carry it.

### F4 — BM25 sentinel files diverge byte-wise from script-written form

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `var/arxmcp/index/bm25/v157/.notebook_slug` (21 bytes,
  ends `0x0a`), `var/arxmcp/index/bm25/v49/.notebook_slug` (18
  bytes, ends `0x0a`); script equivalent at
  `tools/notebook_ingest.py:157` (`sentinel_path.write_text(slug, ...)` —
  no trailing newline)
- **What:** Hexdump of the two manually-written sentinels shows a
  trailing `\n` byte (consistent with shell `echo "bridgeland-stability"
  > ...`). The script at `tools/notebook_ingest.py:157` writes
  `slug` without a trailing newline, and the regression test at
  `tests/tools/test_notebook_scripts.py:637` asserts
  `sentinel.read_text() == "first"` (exact equality, no `.strip()`).
  The collision-check consumer at `tools/notebook_ingest.py:141`
  does use `.strip()`, so the divergence is harmless today; but a
  future operator-script or test that does byte-exact comparison
  would silently mismatch on the manually-written files. The
  implementation summary explicitly justifies the manual write as a
  time-saving deviation from synthesis D1, but does not flag the
  byte-divergence as a hazard.
- **Why it matters:** The m6 sentinel-write code path is now
  data-untested — the on-disk truth diverges from what the canonical
  writer would produce. If `tools/notebook_purge.py` (which today
  doesn't read these files) ever gains slug-based identity matching
  via `==` rather than `.strip()`, the manually-written sentinels
  would silently fail the match. Concretely a "latent foot-gun not
  on common path" — exactly MEDIUM-class.
- **Proposed fix:** Either (a) rewrite the two files via the
  canonical method — open shell, `python -c "from pathlib import
  Path; Path('var/arxmcp/index/bm25/v157/.notebook_slug').write_text('bridgeland-stability')"`
  and same for v49; OR (b) re-run `tools/notebook_ingest.py` once
  per notebook (synthesis D1's preferred path; the implementer
  noted the ~30min re-embed cost as the reason for skipping; if the
  embeddings cache is warm this should be much faster — verify
  before deciding); OR (c) change the assertion at
  `tests/tools/test_notebook_scripts.py:637` to use `.strip()` and
  document the discipline explicitly. (a) is the cheapest correct
  fix; (b) is the "exercises the ingest path" answer; (c) widens
  the contract and is least preferred.
- **Regression guard:** Add a test that scans `BM25_INDEX_ROOT/v*/`
  on a synthetic tmp_path, asserts every `.notebook_slug` file
  matches the script's contract (no trailing whitespace, single
  line, matches `SLUG_RE`). Useful as a low-cost "data hygiene"
  test for future operators. ~15 LOC under
  `tests/tools/test_notebook_scripts.py`.

### F5 — Validator delegates to `is_valid_paper_id` without one-line citation

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/validate_notebook_fixtures.py:146-150` (single
  invalid-paper-id-format check) and
  `tests/tools/test_validate_notebook_fixtures.py:298-308` (single
  `"NOT-A-PAPER-ID"` test)
- **What:** The validator's only check on `expected_relevant_papers`
  entries is `is_valid_paper_id(pid)`. The m1-rect-F3 boundary
  classes (trailing newline → `2604.26204\n`; trailing `\r`;
  leading/trailing whitespace) are correctly rejected by
  `is_valid_paper_id` (manually verified — see hexdump runs in
  research), and `tests/test_search_filter.py:504-514` covers the
  trailing-newline class. But the new validator's test suite
  doesn't exercise any of these classes against its own surface,
  and the validator file has no comment pointing at the upstream
  coverage. If a future refactor inlines a regex check or replaces
  `is_valid_paper_id` with a local helper, the boundary protection
  could silently regress.
- **Why it matters:** The validator's m1-rect-F3 inheritance is a
  load-bearing security property (per
  `.claude/notes/08-security-observability-ops.md` §Threat 1
  path-traversal) and the linkage is invisible in the code. A
  comment is cheap; a small parametrized test under the validator's
  own suite is cheaper than future debugging. Not a CRITICAL or
  HIGH because the function-level coverage IS present at the
  upstream identifier suite.
- **Proposed fix:** Add a parametrized test under
  `TestPerQueryStructure` that drives
  `validate_notebook_fixture(...)` against `expected_relevant_papers`
  entries containing trailing `\n`, leading whitespace, and a CR.
  ~15 LOC. Optionally add a one-line comment at
  `tools/validate_notebook_fixtures.py:146` pointing at
  `tests/test_search_filter.py:504` (or at
  `ingest/identifiers.py:46-47` where the F3 fix lives).
- **Regression guard:** The parametrized test IS the guard.

### F6 — Synthesis says "shimura has ~8 queries"; reality is 10

- **Severity:** LOW
- **Source:** adversary
- **File:** `.claude/notes/milestones/proof-verify-handler-wiring-m4/research-synthesis.md:103`
  (synthesis text) vs `var/arxmcp/notebooks/shimura-varieties/queries.json`
  (10 queries on disk)
- **What:** The synthesis open-question #1 says "Bridgeland has ~10
  queries, shimura has ~8". Live verification: bridgeland has 10,
  shimura has 10. The `MIN_NOTEBOOK_QUERIES = 5` floor was chosen
  with the wrong shimura number in mind, but the floor's value is
  still defensible at 5.
- **Why it matters:** Pure documentation drift. The synthesis is an
  artifact of the milestone process; correcting it after the fact is
  optional but keeps the per-milestone notes trustworthy.
- **Proposed fix:** Edit the synthesis line 103 to read "Bridgeland
  has 10 queries, shimura has 10". One-line correction.
- **Regression guard:** None — pure doc.

### F7 — `_validate_top_level` permits non-string `schema_version`

- **Severity:** LOW
- **Source:** adversary
- **File:** `tools/validate_notebook_fixtures.py:78-104`
- **What:** The top-level validator checks `notebook_slug` against
  the CLI slug (string equality) and requires `queries` to be a
  list, but doesn't type-check `schema_version`, `notebook_display_name`,
  or `created_at`. A `queries.json` with `"schema_version": 1.0` (a
  JSON number instead of a string) would pass validation despite
  the docstring at line 88-89 saying "queries[i]={qid!r}.text must
  be a non-empty string" — same level of paranoia would be expected
  at the top level. Today both real fixtures use string values so
  this is theoretical.
- **Why it matters:** Marginal — fixture authors are project insiders
  and don't write malformed JSON deliberately. But the validator's
  whole point is to be a contract guard against a curator slip, and
  this gap is one such slip.
- **Proposed fix:** Add `isinstance(data[k], str)` checks for
  `schema_version`, `notebook_display_name`, `created_at` in
  `_validate_top_level`. ~6 LOC. Optionally add format validation
  on `created_at` (ISO-8601 date — `datetime.date.fromisoformat`).
- **Regression guard:** Add one parametrized test under
  `TestTopLevelStructure` that sets each of the three fields to a
  non-string and asserts `FixtureValidationError`.

## What was done well

- **Diff is small and disciplined** — single feat commit, single new
  script + matching test file, single CHANGES.md edit. The
  ~215+335 LOC ratio (script:tests) is unusual but defensible given
  the validator's small public surface vs the large parametrized-failure
  matrix.
- **Test coverage of the failure space is genuinely thorough** —
  parametrized `each_required_top_key_missing_rejected` and
  `each_required_query_key_missing_rejected` cover every required
  key without manual enumeration; `test_exactly_min_queries_passes`
  pins the floor boundary; `TestCLI` covers all three documented
  exit codes (0/1/2) with stdout/stderr substring checks.
- **Path-traversal defense is correctly delegated.** The new
  validator imports `validate_slug` and `notebook_dir` from the
  m6-shipped `tools/_notebook_common.py` and doesn't reimplement
  the regex or the symlink-rejection logic — single source of
  truth honored.
- **The decision to write a separate validator (synthesis D3) was
  correct.** Coupling to `tools/validate_eval_fixtures.py` would
  have required widening the F3 closed-schema guard; the standalone
  script is the right call. Both researchers reached the same
  conclusion independently and the implementer executed without
  second-guessing.
- **AC thresholds were corrected, not silently accepted.** The brief's
  `paper_count >= 80` was inherited from an outdated 100-paper plan;
  the implementer documented the 80%-of-actual correction in both
  the deviations section AND the verification recipe, with explicit
  reasoning (`39 × 80% = 31` etc.). No fudge-the-AC anti-pattern.
- **CHANGES.md entry is accurate.** Test count (`2288 passed, 9
  skipped, 1 xfailed`) verified by re-running `make test` —
  matches the entry exactly. Net delta `+29` matches the new test
  file's `--collect-only` count.
- **Cache byte-stability surface untouched.** Diff does not modify
  `server/tools.py::ALL_TOOLS`, `server/prompts.py`, or any tool
  handler envelope. No risk to `EXPECTED_TOOL_SCHEMA_SHA256` or
  `EXPECTED_BP1_SHA256`.
- **Doc placement is exemplary.** All milestone artifacts under
  `.claude/notes/milestones/proof-verify-handler-wiring-m4/`; only
  `CHANGES.md` (an allowed root file) was touched at root. No
  Markdown introduced into `server/`, `ingest/`, `tools/`, or
  `tests/`.
- **`assert` ban honored.** The new code uses
  `RuntimeError`-subclass exceptions (`FixtureValidationError`,
  `NotebookError`) and never `assert` for invariants. Production
  Python `-O` would not strip any check.
- **No bare `except` blocks; no silent error swallowing.** Every
  exception path is named, raised with context (`from e`), and
  surfaces to the caller as a typed error.

## Recommended rectification order

1. **F1 (HIGH).** Fix `docs/ops/notebook-modes.md` to remove or
   declare `ARXMCP_CONTACT_EMAIL` for daemon-launch; same for the
   stateless `tools/call` recipe bug. Add the smoke test. This is
   the only finding that affects a real operator following the
   shipped runbook today.
2. **F4 (MEDIUM).** Rewrite the two BM25 sentinel files via the
   canonical no-trailing-newline form OR re-run `notebook_ingest.py`
   (verify embeddings cache first). The hygiene test is optional
   but cheap.
3. **F5 (MEDIUM).** Add the boundary-class parametrized test to the
   validator's suite and the one-line cross-reference comment.
4. **F2 (MEDIUM).** Wrap the read paths in `try/except OSError` and
   add the parametrized test.
5. **F3 (MEDIUM).** Add the one-line cross-reference comment above
   `REQUIRED_TOP_KEYS`.
6. **F7 (LOW).** Add `isinstance` checks to `_validate_top_level`
   (defer if shipping under time pressure).
7. **F6 (LOW).** Correct the synthesis text (one-line, optional).

## Rectification status

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
