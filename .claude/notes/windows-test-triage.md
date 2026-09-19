# Windows test-baseline triage (stage2/arx-ws0)

**Date:** 2026-07-04
**Host:** Windows 11 (Ryzen 7800X3D), Python 3.11.9, the authoritative arXMCP
runtime per Stage-1 finding 212 (workstation capability inventory).
**Mandate:** Stage-2 workstream WS-0 item (c) — triage the known Windows test
failures into cheap fixes or *documented* skip markers so `pytest` on this
host is green (passing or skipped-with-reason), per
`stage-1-discovery/synthesis/acceptance-criteria.md` AC-0.3 and finding 01
§3-P7(ii). The pre-triage count in `CLAUDE.md` §3 was "29 known
Windows-platform failures"; the live pre-triage run on this branch surfaced
**34 red tests**, resolved below (14 preview + 20 others — the 29 was itself
a stale snapshot from the 2026-05-20 doc era).

Every Windows-conditional skip in `tests/` must reference this note (or a
GitHub issue) in its `reason=` string. `tests/test_windows_skip_markers.py`
enforces that contract mechanically.

The shared markers live in `tests/_platform_helpers.py`
(`requires_symlinks`, `requires_lax_filenames`, `requires_working_latexmlc`),
mirroring the `tests/_graph_helpers.py` shared-module pattern.

---

## §1 — FIXED: real Windows bugs surfaced by the suite (no skips)

These were product/test bugs on the now-tier-1 platform, not platform
impossibilities. Fixed in code on this branch:

| Fix | Where | What was wrong |
|---|---|---|
| Preview path containment | `server/routes/ui.py` | `str(resolved).startswith(str(prefix) + "/")` never matches backslash-separated `str(Path)` on Windows → every `/ui/` preview 404'd (14 test failures). Replaced with `Path.is_relative_to`. Security semantics unchanged. |
| Kùzu handle close | `ingest/kuzudb_schema.py::close_kuzu` (+ callers in `graph_ingest.py`, `inspire_ingest.py`, `tests/_graph_helpers.py`) | `del db` with a live `kuzu.Connection` keeps the exclusive file lock; same-process reopen (resume flows, v1→v2 migration, pytest `tmp_path` teardown) fails with "Could not set lock on file". Close conn **then** db, explicitly. |
| Embedder rename contention | `ingest/embedder.py::_replace_with_retry` | Windows `os.replace` → `MoveFileEx(MOVEFILE_REPLACE_EXISTING)` raises `PermissionError` (WinError 5) while a sibling idempotent writer is mid-replace; POSIX `rename(2)` never does. Bounded retry (100 × 10 ms) converges to last-writer-wins. Fixes `test_embedder_idempotent.py::TestMultiProcessConcurrency` (and the threaded variant's flake). |
| `redact_html_path` separator leak | `server/parse_tracker.py` | Fallback branch stored `str(path)` (backslashes on Windows) while the anchor branch emits `/`-joined parts; stored values are now separator-stable `as_posix()`. |
| Test-side portability | many `tests/*` | `read_text()` without `encoding=` (cp1252 chokes on UTF-8 multi-byte); `str(Path)` compared against `/`-separated needles (→ `as_posix()`/normalize); `\n` translation breaking byte-level hash contracts (→ `newline="\n"`); a Windows-illegal `evil; rm -rf /` fixture dirname; `:`-bearing fixture filenames unfaithful to the real colon-free producer format (`ops/watchdog_eval._utc_ts_filename`); ~15.6 ms `time.monotonic` granularity making a zero-budget breach test measure 0.0 elapsed (→ deterministic monkeypatched clock). |

## §2 — SKIP `requires_symlinks`: fixture needs `os.symlink` (9 tests)

On Windows, `os.symlink` requires `SeCreateSymbolicLinkPrivilege`
(Administrator or Developer Mode) and otherwise raises `OSError`
[WinError 1314]. This environment does not hold the privilege — probed
live at test-session start by `tests/_platform_helpers.SYMLINKS_AVAILABLE`,
so the skips self-heal if Developer Mode is ever enabled.

These are symlink-*confinement* security tests: the property under test
targets an attacker who CAN create symlinks. Where the runner itself
cannot, the fixture is unconstructible — the skip is honest, not a
coverage waiver. The confinement code paths remain covered on the
macOS/Linux runs.

- `tests/test_mcp_resources.py::TestDetailRead::test_is_ingested_false_and_warns_on_symlink_dir`
- `tests/test_notebook_export.py::TestPreflightSafety::test_symlink_under_slug_dir_is_skipped_and_warned`
- `tests/test_notebook_export.py::TestPreflightAdditional::test_slug_level_symlink_returns_422`
- `tests/test_preamble.py::TestF1SymlinkConfinement::test_symlink_to_outside_raises`
- `tests/test_re_embed_all.py::TestDiscovery::test_skips_symlinked_notebook_dir`
- `tests/test_server_startup.py::TestNotebookLancedbPathHelper::test_helper_rejects_symlinked_notebook`
- `tests/test_textbook_chunker.py::TestResilience::test_symlink_notebook_dir_refused`
- `tests/test_textbook_renderer.py::TestRenderMineruToHtmlSurface::test_symlink_in_images_not_dereferenced`
- `tests/tools/test_notebook_scripts.py::test_notebook_dir_rejects_symlink`

## §3 — SKIP `requires_lax_filenames`: Win32-illegal fixture filenames (1 test)

Win32/NTFS rejects control characters (and trailing spaces/dots, reserved
names) in filenames at the API level; the code under test defends against
such names arriving on a volume written by another OS. The fixture cannot
be constructed on Windows.

- `tests/test_notebook_export.py::TestPreflightAdditional::test_filename_with_control_char_is_skipped`

## §4 — SKIP `requires_working_latexmlc`: broken Strawberry-Perl latexmlc shim (2 tests)

`latexmlc` IS on PATH on this host, but the Strawberry Perl wrapper is
broken: every invocation dies inside Perl with `Can't find
C:\Strawberry\perl\site\bin\latexmlc.BAT on PATH` (exit 29) before LaTeXML
starts. Presence-on-PATH is therefore not a sufficient gate on win32; the
marker probes one real `latexmlc --VERSION` run. POSIX behavior is
unchanged (F10 no-silent-skip discipline preserved: on macOS/Linux the
class still runs whenever the binary exists and `_require_latexmlc` still
raises loudly when it does not).

- `tests/test_drift_check.py::TestIntegrationRealLatexmlc::test_all_fixtures_match_baselines`
- `tests/test_drift_check.py::TestIntegrationRealLatexmlc::test_render_fixture_does_not_leave_log_artifact`

Un-skipping on this host = repairing the Strawberry latexmlc install (or
installing LaTeXML under WSL and shimming a functional `latexmlc.bat`).

## §5 — SKIP module: POSIX ops-script tests (6 tests)

`tools/quarterly_drill_reminder.sh` is a bash + cron ops script whose
deployment target is macOS/Linux. On Windows, the `bash` on PATH is the
WSL launcher, which cannot execute a script addressed by a `C:\`-style
Windows path (exit 127) and returns UTF-16 noise through `cmd`-style
invocations. Module-level skip on win32 in
`tests/test_quarterly_drill_reminder.py` (this also skips the
executable-bit check, which is meaningless under `os.access` on Windows).

## §6 — SKIP on data absence: machine-local curated fixtures (2 tests)

`tests/tools/test_validate_notebook_fixtures.py::TestHappyPath::
test_real_{bridgeland,shimura}_notebook_validates` validate curated
`queries.json` files under the **gitignored** `var/arxmcp/notebooks/`
tree. On this workstation, `bridgeland-stability/` has no `queries.json`
and `shimura-varieties/` exists only on the macOS machine (finding 211
R-C; finding 03 F-10). The skip condition is *file absence*, not
platform — the tests re-arm automatically when the curated fixtures land
here. (Eval-fixture curation itself is owner-gated: finding 01 §4-OQ5.)

## §7 — Pre-existing platform-BRANCH skips (correct by design, kept)

These predate this triage and are not failure waivers: each tests a
platform-specific code branch that genuinely only exists on one side
(`sandbox-exec`/`bwrap`, `setrlimit`/`preexec_fn`, POSIX file modes).
The skip is the correct behavior, on either platform, forever — the
mirrored branch is covered by a sibling test or by the degraded-path
unit tests. They are listed so the `tests/test_windows_skip_markers.py`
audit can hold ONE uniform rule (every `win32`-conditioned `skipif`
references this note or an issue) without weakening it.

- `tests/security/test_latexml_sandbox.py::TestSandboxWiring` — sandbox binaries are POSIX-only; Windows takes the documented degraded path (issue #3 close rationale).
- `tests/test_handlers_lean_verify.py` (3 sites) — `RLIMIT_AS`/`preexec_fn` POSIX-branch tests + the mirrored Windows-only branch test (skipped on POSIX).
- `tests/test_operator_settings.py::TestChmodOnFirstCreate` — POSIX 0600 file-mode semantics; Windows ACLs out of scope.

---

## Post-triage expected baseline on this host

All previously-red tests are now either green (§1) or skipped with a
reason string pointing here (§2–§6). Total documented Windows-conditional
skips: 18 (9 + 1 + 2 + 6) plus 2 data-absence skips (§6). The suite-wide
counts are recorded in the Stage-2 slice report
(`_pipeline/stage-2-build/slice-reports/arx-ws0.md`) with verbatim pytest
output.
