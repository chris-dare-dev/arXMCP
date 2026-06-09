# Implementation Summary — windows-parse-path-fix-m1

**One-line:** Make the textbook-PDF parse path (MinerU + LaTeXML) run on
native Windows — productionize 3 working-tree fixes, add 2 scope additions,
and land regression coverage; suite drops 74 → 66 failures (−8), zero new.

**Commit range:** `702b586..<feat HEAD>` (this commit)

## What landed

### Production code (`ingest/textbook_parser.py`, `tools/arxiv_fetch.py`)

The 3 base working-tree fixes (env-whitelist split, `latexmlc_bin` via
`shutil.which`, `hasattr(os,"getpgid")` killpg guard in
`parse_with_latexml`) plus 2 orchestrator-adopted additions:

- **ADD-1** `_scrub_subprocess_env`: on `win32`, also override
  `TEMP`/`TMP` to `output_dir` (Python `tempfile` honors `TMPDIR`, but
  native libs read `TEMP`/`TMP` directly — Fix 1 whitelisted them, so the
  per-invocation scratch-isolation contract needed extending). Gated on
  win32 so the POSIX env dict stays byte-identical (no new keys).
- **ADD-2** `run_mineru_sandboxed` (MinerU timeout path,
  `textbook_parser.py`): same `os.killpg`/`os.getpgid` bug Fix 3 patched in
  `arxiv_fetch.py`. It was wrapped in
  `suppress(ProcessLookupError, OSError)` which does NOT catch the
  `AttributeError` Windows raises → a MinerU timeout crashed. Applied the
  identical `if hasattr(os,"getpgid"): killpg else: proc.kill()` guard.

### Tests

- `tests/test_textbook_parser.py` — replaced the broken `_ENV_WHITELIST`
  pin (`test_whitelist_set_unchanged`) with 4 platform-correct tests
  (`test_posix_whitelist_pinned`, `test_windows_whitelist_pinned`,
  `test_no_credential_or_egress_var_in_windows_whitelist`,
  `test_effective_whitelist_is_platform_correct`); added TEMP/TMP override
  tests (win32 + POSIX-unchanged); made `test_timeout_triggers_killpg`
  cross-platform and added the getpgid-absent `proc.kill()` sibling.
- `tests/test_arxiv_fetch.py` — new `TestParseWithLatexml` (zero prior
  coverage): cmd[0] uses the `which()` result not the bare name;
  RuntimeError when `which()` is None; killpg-present and getpgid-absent
  kill paths.
- `tests/security/test_latexml_sandbox.py` — made the two existing
  `TestProcessGroupKill` tests cross-platform (`raising=False` on the
  os.getpgid/killpg patches + sentinel `signal.SIGKILL`); they directly
  cover the `parse_with_latexml` killpg code this milestone changed.

## Acceptance criteria status

- [x] (a) regression tests — env whitelist per-platform; latexmlc cmd[0]
  uses which(); killpg fallback on no-getpgid. PLUS TEMP/TMP override and
  the ADD-2 MinerU killpg guard.
- [x] (b) security review — env-whitelist expansion confirmed: none of the
  13 Windows vars is a credential, proxy/egress route, or cloud token; a
  `test_no_credential_or_egress_var_in_windows_whitelist` guard pins this.
  See research-synthesis.md "Security review".
- [x] (c) ruff clean (`ruff check .` → All checks passed) + full suite run:
  74 → 66 failures (−8), zero new (strict subset of baseline). Remaining 66
  are all pre-existing Windows-platform failures.
- [x] (d) commit per repo conventions — feat/rect/chore triple, conventional
  subjects, co-author trailer, HEREDOC body. GPG signing unavailable on this
  workstation (no secret key) → lands UNSIGNED per known state.

## Test delta

- Baseline failures (clean `702b586`, no working-tree changes): **74**.
- After this milestone: **66**. Diff: 0 NEW, 8 FIXED.
- 8 fixed: 5× `TestLatexmlSandboxContainment::test_*` (real-latexmlc
  containment — Fix 2's `shutil.which` resolution makes latexmlc invokable
  on Windows, proving end-to-end value), 2× `TestProcessGroupKill`, 1×
  `test_timeout_triggers_killpg`.

## Out of scope (documented, NOT fixed)

- **`server/config.py` `_scan_unknown_arxmcp_env_vars` rejects
  `ARXMCP_MINERU_BIN` / `ARXMCP_MINERU_TIMEOUT_S`** — pre-existing latent
  gap (server-config vs ingest-tool vars); touches security-audited server
  config unrelated to the Windows parse path. Recommend a follow-up issue.
- **`TestUserAgent::test_builds_from_env` / `test_missing_email_raises`** —
  pre-existing, environment-dependent: `build_user_agent` consults the
  SQLite `operator_settings.contact_email` (`cedare96@gmail.com` on this
  box) before the env var; the tests don't isolate that source. Unrelated
  to this milestone; pre-existing in baseline.
- **`security-pdf-sandbox.md` Windows addendum** — doc tracks the canonical
  impl, accurate for POSIX; Windows paragraph is a future doc task.

## External writes required

NONE. Purely local. `git push` not requested.
