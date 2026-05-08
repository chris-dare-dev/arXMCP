# Critique — E05_S01

**Critic:** adversary
**Generated:** 2026-05-08T00:00:00Z
**Commit range:** 5a14fa5..1f18f8c
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES — the validator's behavior matrix is solid
  and 27 tests pass green, but several documentation/runtime drift
  bugs and missing AC plumbing need cleanup before E05_S02 lands on
  this fixture.
- Finding counts: 0 CRITICAL, 3 HIGH, 8 MEDIUM, 4 LOW.
- The brief's AC text "this script runs as part of `make test`" is
  satisfied via the pytest wrapper, but the actual `make test` target
  never invokes the validator's CLI binary; downstream readers may
  expect a separate CLI gate. See F1.
- The fixture's `chunker_version` field literalizes `"v1.0"` — the
  validator imports `CHUNKER_VERSION` from `ingest.chunker_types`
  but the **fixture file itself** silently drifts on the next bump.
  See F2.
- The runbook (`docs/eval-curation.md:148-150`) tells curators that
  the validator rejects unknown top-level keys — but it does not.
  See F3.
- Highest-risk file: `tools/validate_eval_fixtures.py` (carries the
  policy surface; every drift bug lives here).
- Cross-axis: every drift bug discovered is a **single-source-of-
  truth** failure (literal vs. import; doc claim vs. code; error
  message vs. brief schema).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — `make test` does not invoke the validator CLI; brief AC drift

- **Severity:** HIGH
- **Source:** adversary
- **File:** `Makefile:43-49`
- **What:** The brief says `validate_eval_fixtures.py` "runs as part
  of `make test`" — implying the executable script is invoked. The
  Makefile `test` target only runs `ruff check` + `pytest`. Pytest
  reaches `validate()` via `tests/eval/test_fixtures.py` but does NOT
  exercise `_main()` (argparse, exit codes, stderr `FAIL:` prefix,
  CLI default-path resolution). A regression that breaks only the CLI
  surface (e.g. argparse arg name change, sys.exit logic, stderr
  formatting) ships green.
- **Why it matters:** AC drift. Curators who run `python
  tools/validate_eval_fixtures.py` per `docs/eval-curation.md:157`
  are exercising an untested code path. The pytest wrapper is not a
  drop-in replacement for the CLI per the brief's wording.
- **Proposed fix:** Either (a) extend the Makefile `test` target with
  `$(PYTHON) tools/validate_eval_fixtures.py` after pytest; or (b)
  add a pytest test that calls `subprocess.run([sys.executable,
  "tools/validate_eval_fixtures.py"])` and asserts exit code 0 and
  the `OK:` stdout line. Option (b) is preferred — keeps `make test`
  short and locks the CLI surface in unit tests.
- **Regression guard:** `tests/eval/test_fixtures.py::TestCli::
  test_cli_seed_mode_exits_zero` invoking the script as subprocess.

### F2 — Fixture `chunker_version` field literalized "v1.0"; will silently drift on next bump

- **Severity:** HIGH
- **Source:** adversary
- **File:** `tests/eval/fixtures/queries.json:3`
- **What:** The committed seed fixture has `"chunker_version":
  "v1.0"` literal. The validator imports `CHUNKER_VERSION` from
  `ingest.chunker_types` (currently `"v1.0"`) and asserts the
  fixture's value matches. When the chunker constant bumps to
  `"v1.1"`, the validator fires AC-4. Good. **But** the test
  `TestSingleSourceOfTruth::test_chunker_version_locked` only checks
  `data["chunker_version"] == CHUNKER_VERSION` — it passes if both
  are `"v1.0"`. There is no test that verifies the fixture file is
  *kept in lockstep* with the chunker constant; the curator could
  freeze "v1.0" and the AC-4 error is the safety net, but a
  regression-style "fixture should always carry the running version"
  invariant would catch the drift before commit. Furthermore, the
  validator's docstring (lines 46-51) explicitly forbids literalizing
  `"v1.0"` in the validator source — but the fixture file (which the
  validator reads) is exempt from this discipline.
- **Why it matters:** The "single source of truth" invariant the
  validator enforces on its OWN source (`test_no_v1_literal_in_
  validator_source` at `tests/eval/test_fixtures.py:163-174`) does
  not extend to the fixture file. The seed fixture is a
  curator-owned config, but at ship time it must equal the running
  constant.
- **Proposed fix:** The current `test_chunker_version_locked` is
  adequate at ship time (asserts equality). Strengthen the runbook
  (`docs/eval-curation.md:122`) to make explicit that the curator
  must update `chunker_version` in the fixture to whatever
  `CHUNKER_VERSION` currently holds, not to a literal "v1.0". Or:
  add a `tools/freshen_fixture_version.py` one-liner that rewrites
  the field from the import. Cheapest fix is the runbook clarification.
- **Regression guard:** Add a test to `TestSingleSourceOfTruth` that
  asserts `'"v1.0"'` does not appear in
  `tests/eval/fixtures/queries.json` BUT the import-derived value
  does. (Or: keep the existing `test_chunker_version_locked` and
  document that it serves both purposes.)

### F3 — Runbook claims validator rejects unknown top-level keys; it does not

- **Severity:** HIGH
- **Source:** adversary
- **File:** `docs/eval-curation.md:147-150`
- **What:** The runbook says: *"The validator rejects unknown
  top-level keys at the next schema bump; per-query unknown keys
  are currently allowed but discouraged for byte-stability."* This
  is wrong. `_validate_header()` only checks for the four required
  keys (`schema_version`, `chunker_version`, `created_at`,
  `queries`). Confirmed empirically: a fixture with `"GARBAGE_KEY":
  "x", "_curation_status": "half"` passes header validation
  silently. The runbook's claim is aspirational, not contractual.
- **Why it matters:** A curator who reads the runbook and trusts
  this guarantee may add ad-hoc top-level metadata fields, expect
  the validator to reject them, and only discover the silent-pass
  behavior at audit time (when the eval set has already been used).
  This is a documentation lie, which is worse than a missing check.
- **Proposed fix:** Either (a) tighten `_validate_header()` to
  reject unknown top-level keys (4-line change: `unknown =
  data.keys() - required` then raise if `unknown` non-empty); or
  (b) edit the runbook to remove the claim. Option (a) is preferred
  — the brief schema is fixed at 4 keys and any drift should fail
  loud. The schema already names these as required; tightening to
  exclusive is small surface area.
- **Regression guard:** `tests/eval/test_fixtures.py::TestHeaderErrors
  ::test_unknown_top_level_key_raises` covering option (a), or
  remove the runbook claim and add no test (option b).

### F4 — Runbook mentions a non-existent `tools/seed-papers.txt` and unstated chunker invocation

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `docs/eval-curation.md:36-39`
- **What:** The runbook tells the curator to *"Run
  `tools/fetch_seed.py` # then the chunker — see `ingest/chunker.py`
  public API"*. The chunker is imported as `chunk_paper(paper_id)`
  but the runbook gives no concrete invocation; the curator has to
  reverse-engineer how to chunk all 50 seed papers. The runbook
  also says (line 196-197) "Coordinate with whoever owns
  `tools/seed-papers.txt`" — that file is committed at
  `tools/seed-papers.txt` (verified), but the runbook treats it as
  remote/owned by another party. Mixed signal.
- **Why it matters:** Curator friction. The brief is "blocked on a
  human curator" — friction in the runbook directly translates to
  no curation happening, and AC-1, AC-2, AC-7 never close.
- **Proposed fix:** Replace the chunker comment with a concrete
  command (e.g. `python -c "from ingest.chunker import chunk_paper;
  for pid in open('tools/seed-papers.txt'): chunk_paper(pid.strip())"`
  or a `make ingest-seed` target if that lands soon). Clarify that
  `tools/seed-papers.txt` is in-tree.
- **Regression guard:** None required (docs change).

### F5 — Validator's `_iter_chunk_manifest_paths` does not validate directory names against `_PAPER_ID_RE`

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/validate_eval_fixtures.py:164-174`
- **What:** The manifest scan globs `*/chunk_manifest.json` under
  `chunks_dir`. Directory names are not validated against
  `_PAPER_ID_RE`. A directory named `evil; rm -rf /` would be
  scanned. Confirmed empirically: the glob accepts `chunks/evil; rm
  -rf //chunk_manifest.json`. The validator does not shell-execute
  any path (read-only via `Path.read_text`), so no RCE vector. But
  the validator's chunk_id parser then admits any chunk_id from
  these manifests into the `chunk_kind_index` — meaning a malicious
  manifest at a malicious directory could declare chunk_ids for
  ANY paper_id and the validator would treat the fixture chunk_ids
  as resolved. This breaks the "stale-id safety net" promise (lines
  6-13 of the validator docstring).
- **Why it matters:** The chunker writes manifests at trusted
  paths, so this is a defense-in-depth concern. But the validator
  is the safety net for stale-IDs; if the upstream chunker is
  compromised or has a bug, the validator inherits the breakage
  silently. Cheap to add a directory-name guard.
- **Proposed fix:** Filter `manifest_paths` to those where the
  parent directory name matches `_PAPER_ID_RE`. 3-line change:
  ```
  return sorted(
      p for p in chunks_dir.glob("*/chunk_manifest.json")
      if _PAPER_ID_RE.match(p.parent.name)
  )
  ```
- **Regression guard:** `tests/eval/test_fixtures.py::TestManifest
  Errors::test_invalid_paper_id_directory_skipped` writing a
  manifest under a malformed-name directory and asserting it does
  not contribute to the kind index.

### F6 — Validator's `_load_chunk_kind_index` does not cross-validate chunk_id paper_id against directory name

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/validate_eval_fixtures.py:177-227`
- **What:** A manifest at `chunks/2307.00001/chunk_manifest.json`
  could declare a chunk with `chunk_id = "arxiv:2307.00099:..."`.
  The validator just merges all entries into `index` keyed by
  chunk_id. So a manifest under directory A could contribute
  chunk_ids for paper B, and the AC-3 lookup would resolve them.
  This is an upstream-chunker invariant violation (the chunker only
  writes its own paper_id to its own directory), but the validator
  is the safety net.
- **Why it matters:** Silent corruption surface. The validator
  promises that `chunk_id` resolves to "the chunk at that path",
  but there's no path↔chunk_id consistency check. Combined with F5
  this is a small but real attack surface.
- **Proposed fix:** Inside `_load_chunk_kind_index`, parse the
  paper_id from each chunk_id (regex group already named in
  `_CHUNK_ID_RE`) and assert it matches `manifest_path.parent.name`.
  Mismatched entries are skipped (not raised — the chunker's own
  invariant should catch this; the validator just refuses to import
  inconsistent rows).
- **Regression guard:** `tests/eval/test_fixtures.py::TestManifest
  Errors::test_chunk_id_paper_id_mismatch_skipped` writing a
  manifest where the embedded paper_id contradicts the directory.

### F7 — `created_at` field accepts arbitrary strings (e.g. "yesterday", "")

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/validate_eval_fixtures.py:288-292`
- **What:** The validator only checks `isinstance(data["created_at"],
  str)`. Empty string `""` and arbitrary text (`"yesterday"`,
  `"unknown"`) pass. The brief's example uses ISO-8601 (`"2026-05-
  06"`); the runbook (`docs/eval-curation.md:175-186`) says
  `created_at` is "intentionally a fixed string" but does not
  require ISO format. A curator who writes `"created_at": ""` gets
  a green validator and a worthless audit trail.
- **Why it matters:** The runbook calls this field the audit-trail
  signal; without format enforcement, the field can drift to
  garbage. Brief schema example is `"2026-05-06"` — implicit ISO-
  8601.
- **Proposed fix:** Reject empty strings; optionally regex-match
  ISO-8601 (`r"^\d{4}-\d{2}-\d{2}$"` for date or full datetime).
  Empty-string rejection is a one-line change; ISO regex is two.
  Keep it minimal.
- **Regression guard:** `test_empty_created_at_raises` and
  `test_non_iso_created_at_raises`.

### F8 — `_main()` ignores `result.warnings` when result.mode == "complete" but logs them in seed mode only

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/validate_eval_fixtures.py:580-582`
- **What:** The CLI prints `INFO:` lines for every warning — but
  `result.warnings` is only populated in seed mode (lines 500-509);
  complete mode always returns `warnings=[]` per line 543. So the
  warnings loop is dead code on the complete-mode path. Conversely,
  the validator never produces a non-fatal warning in complete mode
  (e.g. "fixture has 5 stmt-kind queries — meets AC-7 threshold but
  no headroom"). A reasonable diagnostic surface is missing.
- **Why it matters:** Latent dead-code branch. Either the warnings
  field is doing something useful (in which case the complete-mode
  path should populate it where helpful — e.g. "you have only the
  bare minimum for AC-7; consider adding more queries") or it's
  not, in which case the loop should be deleted.
- **Proposed fix:** Either populate complete-mode warnings (e.g.
  emit a warning when stmt-kind queries == 5, the AC-7 minimum,
  hinting at fragility) OR document the warnings field as
  seed-mode-only and inline the seed-mode warning print. The
  former is more useful for curators iterating.
- **Regression guard:** `test_complete_mode_emits_low_quota_warning`
  if option 1; otherwise none.

### F9 — Validator declares `logger = logging.getLogger(__name__)` but never uses it

- **Severity:** LOW
- **Source:** adversary
- **File:** `tools/validate_eval_fixtures.py:70`
- **What:** Logger is created at module load (line 70) but no
  `logger.*` call exists anywhere in the file. `logging.basicConfig
  (level=logging.INFO, format="%(message)s")` is configured in
  `_main()` for unrelated reasons (or as dead code, since no logger
  is ever used). Confirmed: `grep -c "logger\." → 0`.
- **Why it matters:** Dead code. Misleading reader cue (suggests
  the validator emits structured logs when it does not).
- **Proposed fix:** Delete the `logger` line and the
  `logging.basicConfig` call in `_main()`.
- **Regression guard:** None (style fix).

### F10 — `test_no_v1_literal_in_validator_source` is too coarse; will break legitimate docstring example

- **Severity:** LOW
- **Source:** adversary
- **File:** `tests/eval/test_fixtures.py:163-174`
- **What:** The test does a substring scan for `'"v1.0"'` in the
  entire validator source. If a future docstring example includes
  the literal version (e.g. *"the fixture's chunker_version field
  is `"v1.0"` at first ship time"*) the test fires. AST-based
  scanning (only string assignments / dict values, not docstring
  bodies) would be more precise. Current state: green because no
  docstring uses the literal — but it's a foot-gun for future
  documentation.
- **Why it matters:** Test is brittle to documentation changes; a
  good test should fail only on real drift.
- **Proposed fix:** Replace with an AST walk that checks
  module-level constant assignments and function bodies for the
  literal — but skips `ast.Expr` nodes wrapping `ast.Constant`
  strings (i.e. docstrings). 15 LOC change. Or accept the
  coarseness as acceptable for a tiny module and document the
  rule.
- **Regression guard:** None — the existing test is the regression
  guard for the *current* invariant; a future doc-change-driven
  failure is a desirable signal that the test needs an upgrade.

### F11 — Partial-fixture branch (1-19 queries) blocks legitimate WIP curation workflow

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/validate_eval_fixtures.py:517-525`
- **What:** Per synthesis D3, a fixture with 1-19 queries is
  always rejected. The justification (line 92-95 of impl-summary)
  is "catches accidental half-merges of in-progress curation
  work." But the curator's actual workflow is iterative: write 5
  queries, run `make test` to validate the schema, then write 5
  more. Currently `make test` fails at step 1 with "expected 0 or
  20" — forcing the curator to choose between (a) keeping `queries
  = []` and editing offline (loses pytest validation of structural
  errors), or (b) running into the partial-fixture wall every
  iteration.
- **Why it matters:** Workflow friction during the user-blocked
  curation pass. The implementer's comment on line 92-95 *"catches
  the I'll commit my first 5 queries failure mode"* conflates
  *commit* with *validate locally*; the validator runs at every
  `make test`, not just at commit time.
- **Proposed fix:** Add a `--allow-partial` CLI flag (or env var
  `ARXMCP_FIXTURE_ALLOW_PARTIAL=1`) that downgrades 1-19 to a
  warning ("WIP curation: 5/20 queries"). Alternatively, only
  enforce all-or-nothing in CI via a separate `--strict` flag, and
  default the local invocation to permissive. Cheap: ~10 LOC.
- **Regression guard:** `test_allow_partial_flag_emits_warning`.

### F12 — `_validate_query_set_invariants` short-circuits on first error; multiplies edit cycles

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/validate_eval_fixtures.py:400-438`
- **What:** Every error path raises immediately. A curator with
  three problems (one missing grade-3, one stale chunk_id, one
  duplicate query_id) gets one error per `make test` run, fixes
  it, runs again, gets the next, etc. Three edit cycles instead of
  one.
- **Why it matters:** Curator friction during the labeling pass.
  The brief calls curation "the gate"; reducing edit cycles by
  reporting all errors at once meaningfully accelerates the
  user-blocked work.
- **Proposed fix:** Accumulate errors into a list, then raise a
  single `FixtureValidationError` whose message lists all of them
  (one per line). Standard Python idiom; ~20 LOC. Preserves the
  exit-non-zero contract.
- **Regression guard:** `test_multiple_errors_reported_together`.

### F13 — `_make_chunk_id` test helper produces non-hex chunk_ids when called with non-hex suffix

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/eval/test_fixtures.py:84-87`
- **What:** `_make_chunk_id(paper_id, suffix)` does `(suffix * 16)
  [:16]` — meaning if the suffix is non-hex (e.g. `"g"`, `"foo"`),
  it produces a non-hex 16-char string that fails `_CHUNK_ID_RE`.
  The current callers all pass hex characters, but the helper has
  no input validation. A future test author calling `_make_chunk_id
  ("2307.00001", "z")` gets a malformed chunk_id and a misleading
  test failure.
- **Why it matters:** Silent foot-gun for test maintenance. The
  helper's intent is "produce a valid chunk_id for tests" but its
  implementation accepts invalid input.
- **Proposed fix:** Add `assert all(c in "0123456789abcdef" for c
  in suffix)` at the helper's top. Or rename to `_make_chunk_id_
  unchecked` and add a `_make_valid_chunk_id` that validates.
- **Regression guard:** None (test-only helper).

### F14 — No test exercises validator with the production CHUNKS_DIR default

- **Severity:** LOW
- **Source:** adversary
- **File:** `tests/eval/test_fixtures.py` (entire file)
- **What:** Every test passes `tmp_path` as the `chunks_dir`
  argument. No test exercises the default path resolution
  (`CHUNKS_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" /
  "chunks"`). On a checkout where `var/arxmcp/corpus/chunks/` does
  not exist (clean clone), the validator silently treats the
  default as empty. A regression that breaks `REPO_ROOT` resolution
  (e.g. `Path(__file__).resolve().parent.parent` becoming `parent`)
  would still pass tests.
- **Why it matters:** AC-5 is "validator exits 0 on a clean
  checkout with valid corpus." The current test suite verifies
  this through `tmp_path` corpus synthesis, not through the
  default path. Path-resolution drift would be invisible.
- **Proposed fix:** Add a test that imports `validate` and calls
  it with NO args, verifying it doesn't throw on the seed fixture
  + missing default `chunks_dir`. Or assert
  `CHUNKS_DIR.is_relative_to(REPO_ROOT)`.
- **Regression guard:** `test_default_chunks_dir_resolves_under_
  repo_root`.

### F15 — Validator's `_iter_chunk_manifest_paths` is non-deterministic if filesystem case-folds

- **Severity:** LOW
- **Source:** adversary
- **File:** `tools/validate_eval_fixtures.py:174`
- **What:** `sorted()` returns Python-default lexicographic order
  on a case-sensitive filesystem. On macOS HFS+/APFS (case-
  insensitive by default), `sorted()` still works but the
  underlying directory listing may surface paper_id directories in
  case-folded order. Edge case: paper_ids are `[a-z]*`-prefixed
  (old style) so case folding doesn't matter for the chunker's
  output. Confirmed-OK; flagging only because the docstring of
  `_iter_chunk_manifest_paths` says "deterministic error ordering"
  — this is true on case-sensitive but not strictly cross-platform
  guaranteed.
- **Why it matters:** Theoretical only. No real risk on the
  current corpus.
- **Proposed fix:** Document the assumption, or use `sorted(...,
  key=lambda p: p.as_posix().lower())` for strict cross-platform
  determinism. Latter is cheap.
- **Regression guard:** None.

## What was done well

- The behavior matrix (seed × partial × complete) × (corpus
  present × absent) is exhaustive and the implementation matches
  the docstring table. The 5 cells are explicit, named, and
  tested.
- Single-source-of-truth for `CHUNKER_VERSION` is enforced via
  import + a literal-scan test (`test_no_v1_literal_in_validator_
  source`), mirroring the E04_S04 discipline. The seed fixture
  passes by construction.
- `_PAPER_ID_RE` is duplicated rather than imported — the
  rationale (avoid pulling LaTeXML deps for a CLI tool) is sound,
  and the lockstep is locked by `test_paper_id_regex_matches_
  chunker` comparing `.pattern`. Confirmed both regexes have
  identical flags (`32` = UNICODE only).
- 27 tests across 6 classes, no skipped, sub-second execution.
  Test taxonomy mirrors the validator's structure.
- `chunks_dir` is a parameter, not a hardcoded path — every test
  uses `tmp_path` and no test pollutes the developer's `var/`.
- `bool` rejection in `_validate_query_structure` (line 358-367)
  is correct: `isinstance(True, int)` is True in Python, and the
  validator explicitly excludes bools. Catches a real foot-gun.
- The malformed-chunk-id path (`_CHUNK_ID_RE.match(cid)` →
  "malformed chunk_id" error) is correctly distinct from the
  stale-id path. D10 of the synthesis is honored.
- Manifest atomic-write discipline (chunker side, line 1023-1041)
  is correct — `os.replace` + tmp suffix + try/finally cleanup.
  The validator's TOCTOU surface is bounded.
- `docs/eval-curation.md` is comprehensive (225 LOC) and provides
  a real labeling discipline (kind quotas, grade definitions,
  failure modes). The "When the curator's quota collides with
  reality" section anticipates a real failure mode and gives two
  concrete responses.

## Recommended rectification order

1. **F2 + F3** (single-source-of-truth and runbook drift) — both
   touch the docs/runbook surface; fixing together is one diff.
2. **F1** (make test wires CLI) — small, locks AC interpretation.
3. **F5 + F6** (validator manifest scan defense-in-depth) —
   touches the same `_iter_chunk_manifest_paths` /
   `_load_chunk_kind_index` code path; fix together.
4. **F11 + F12** (curator-workflow friction) — both improve the
   user-blocked curation pass; F11 is a flag, F12 is the error
   accumulator. Independent diffs.
5. **F7** (created_at format) — small.
6. **F8 + F9** (dead-code cleanup) — single diff.
7. **F4** (runbook chunker invocation) — docs only.
8. **F10, F13, F14, F15** (LOW; defer or batch).

## Rectification status

**Phase 4 commit:** see `state.json` `rectification_commit` field.

| Finding | Severity | Status | Where fixed |
|---|---|---|---|
| F1 — `make test` does not invoke the validator CLI | HIGH | **fixed** | Two-prong: (a) added `sys.path` bootstrap at the top of `tools/validate_eval_fixtures.py` so the direct `python tools/validate_eval_fixtures.py` invocation actually works (the original would have crashed with `ModuleNotFoundError: ingest`); (b) added `TestCli::test_cli_seed_mode_exits_zero` and `test_cli_invalid_fixture_exits_one` that subprocess-invoke the script and assert exit codes + `OK:`/`FAIL:` markers. The pytest wrapper still calls `validate()` directly for the rich-error-message path. |
| F2 — Fixture `chunker_version` will silently drift on next bump | HIGH | **fixed (runbook clarification)** | `docs/eval-curation.md` now carries an "On the value of `chunker_version` at re-curation time" paragraph explicitly telling the curator to read the value from `CHUNKER_VERSION` at re-curation time, not type the literal. The existing `test_chunker_version_locked` is the ship-time enforcement; the runbook is the curator-time policy. |
| F3 — Runbook claims unknown top-level keys are rejected; they aren't | HIGH | **fixed (validator tightened)** | `_validate_header` now computes `extra = data.keys() - required` and raises if non-empty. Locked by `TestUnknownTopLevelKeys::test_unknown_top_level_key_raises`. The runbook claim is now contractual. |
| F4 — Runbook missing concrete chunker invocation | MEDIUM | **fixed** | `docs/eval-curation.md` § Prerequisites now carries a concrete two-step recipe (`python tools/fetch_seed.py` then a one-liner that calls `chunk_paper(paper_id)` for every line in `tools/seed-papers.txt`). The `seed-papers.txt` ownership confusion is also resolved (in-tree, edit deliberately). |
| F5 — `_iter_chunk_manifest_paths` doesn't filter dir names | MEDIUM | **fixed** | Manifest scan now filters by `_PAPER_ID_RE` against `p.parent.name`; rogue directories (`evil; rm -rf /`) are skipped. Locked by `test_invalid_paper_id_directory_skipped`. |
| F6 — chunk_id paper_id vs directory name not cross-checked | MEDIUM | **fixed** | `_load_chunk_kind_index` now extracts the `paper_id` group from `_CHUNK_ID_RE` and compares against `manifest_path.parent.name`; mismatched rows are silently skipped. Locked by `test_chunk_id_paper_id_mismatch_skipped`. |
| F7 — `created_at` accepts arbitrary strings | MEDIUM | **fixed** | Added `_ISO_DATE_RE` (`^\d{4}-\d{2}-\d{2}$`); `_validate_header` enforces. Empty strings and free-form text now raise. Locked by `test_empty_created_at_raises`, `test_non_iso_created_at_raises`, `test_iso_created_at_passes`. |
| F8 — Warnings loop dead in complete mode | MEDIUM | **fixed (documented convention)** | `ValidationResult` docstring now states the field is seed-mode-only at Tier-0 and is preserved for E05_S02 to populate with curation-quality advisories. The CLI's print loop is harmless. |
| F9 — Unused `logger` declaration | LOW | **fixed** | Removed the `logger = logging.getLogger(...)` line and the dead `logging.basicConfig(...)` call in `_main()`. |
| F11 — Partial-fixture branch blocks WIP curation | MEDIUM | **deferred** | The per-query structural validation already runs BEFORE the count check, so a curator iterating on 5 queries gets all per-query feedback before the partial-fixture wall fires. Adding a `--allow-partial` flag complicates the contract for marginal benefit at Tier-0; the curator can iterate in a feature branch and merge at 20. |
| F12 — Errors short-circuit on first failure | MEDIUM | **deferred** | Standard fail-fast Python idiom is the default; accumulating errors is a meaningful refactor (~20 LOC + test). Curator-friction concern is real but bounded — most edits are point-fixes after a single error. Reconsider in E05_S02 if cycles measurably hurt. |
| F13 — `_make_chunk_id` test helper accepts non-hex | MEDIUM | **fixed** | Added an `assert` that rejects non-hex suffixes with a clear message. |
| F10 — Literal-scan test is too coarse | LOW | **deferred** | Kept as-is per the critic's own recommendation. AST-based scan is a future refinement. |
| F14 — No test for default `CHUNKS_DIR` resolution | LOW | **deferred** | The default-path resolution is exercised indirectly via `test_default_fixture_validates`. AC-5 is met. |
| F15 — Theoretical filesystem case-folding | LOW | **deferred** | Tier-0 corpus uses `[a-z]*`-prefixed paper_ids; case folding is a no-op. Documented as theoretical. |

**New regression tests added in this rectification batch:**
- `TestCli::test_cli_seed_mode_exits_zero` — subprocess-invoke the CLI; exit 0 + `OK:` (F1).
- `TestCli::test_cli_invalid_fixture_exits_one` — subprocess-invoke with bad JSON; exit 1 + `FAIL:` (F1).
- `TestUnknownTopLevelKeys::test_unknown_top_level_key_raises` (F3).
- `TestManifestErrors::test_invalid_paper_id_directory_skipped` (F5).
- `TestManifestErrors::test_chunk_id_paper_id_mismatch_skipped` (F6).
- `TestCreatedAtFormat::test_empty_created_at_raises` (F7).
- `TestCreatedAtFormat::test_non_iso_created_at_raises` (F7).
- `TestCreatedAtFormat::test_iso_created_at_passes` (F7).

**Suite at rectification time:** 538 passed, 2 skipped, ruff clean.
