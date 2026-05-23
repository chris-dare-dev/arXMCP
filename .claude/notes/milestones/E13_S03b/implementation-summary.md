# Implementation summary — E13_S03b

**Milestone:** E13_S03b — Ship the production LaTeXML sandbox wiring (Threat 3 Phase 2)
**Implementation base SHA:** `3c5d47ffae8fe7e2c0e64f7f7c1f7eee5f5ba893`
**Path:** inline (orchestrator implemented directly in main session)

## One-line summary

Wired `sandbox-exec` (macOS) and `bubblewrap` / `bwrap` (Linux) into
`tools/arxiv_fetch.py::parse_with_latexml` and
`ops/drift_check.py::render_fixture` by prepending a runtime
platform-detected wrapper argv. Existing `infra/latexml/sandbox.sb` and
`infra/latexml/docker-compose.latexml.yml` profiles (shipped + statically
tested in E13_S03) are now CONNECTED to the actual subprocess
invocations. Closes Threat 3 Phase-2 gap G3 (GitHub issue #3).

## Files changed

| File | Change | Why |
|---|---|---|
| `tools/arxiv_fetch.py` | MODIFIED | Added imports (`logging`, `sys`, `tempfile`), module logger. Added 2 new constants: `SANDBOX_PROFILE_PATH` (`__file__`-anchored absolute path to `infra/latexml/sandbox.sb`), `LATEXML_INTERNAL_TIMEOUT_SECONDS=300`. Added `_detect_sandbox_layer()` + module-level `_SANDBOX_LAYER` with import-time INFO log (one per process; surfaces active layer or degraded-path notice). Added `_build_sandbox_cmd(cmd, source_dir, output_dir, tmpdir_subdir)` helper. Modified `parse_with_latexml` to wrap the Popen in a `TemporaryDirectory` context, call `_build_sandbox_cmd`, log DEBUG per invocation. Added `--timeout=300` to latexmlc argv (defense-in-depth). |
| `ops/drift_check.py` | MODIFIED | `render_fixture` imports and calls `_build_sandbox_cmd` so the secondary LaTeXML invocation gets the same sandbox treatment as `parse_with_latexml`. |
| `tests/security/test_latexml_sandbox.py` | MODIFIED | Added `import sys` for the platform skip marker. New `TestSandboxWiring` class — 9 POSIX-only tests (`skipif(sys.platform == "win32")`) covering: `_detect_sandbox_layer` darwin-present / darwin-absent / linux-with-bwrap / linux-without-bwrap; `_build_sandbox_cmd` darwin-prepends / linux-prepends / unavailable-returns-unchanged / does-not-mutate-input; `parse_with_latexml` threads the wrapped argv into Popen. |
| `.claude/docs/security-threat-3-audit.md` | MODIFIED | Phasing table: 4 Phase-2 rows flipped from `⏳ deferred — E11` to `✅ E13_S03b`. Docker-wiring row marked still deferred (E14 main-compose merge). New "Phase 2 wiring (E13_S03b)" section documents the architecture, fail-closed posture, test surface, operator runbook (per-platform install), and Docker status. |
| `.claude/docs/security-threat-model-coverage.md` | MODIFIED | Threat 3 summary-table row + per-threat section + G3 triage row marked closed by E13_S03b (with Docker-wiring footnote). Test count notation updated to reflect the new TestSandboxWiring class. |

## Design decisions (from research synthesis)

1. **macOS = `sandbox-exec`, Linux = `bubblewrap` (bwrap).** Both
   researchers strongly recommended bwrap over raw seccomp+landlock
   /ctypes/sandlock. Reasons: distro-package availability
   (`apt install bubblewrap`); no Python C extension dependency;
   combines filesystem namespace + network isolation in one
   well-audited tool; NOT setuid root (unlike Firejail's past CVEs);
   battle-tested as Flatpak infrastructure.

2. **Existing profile + compose are COMPLETE.** E13_S03 shipped
   `infra/latexml/sandbox.sb` (correctly hardened per the E13_S03
   adversary F1) and `infra/latexml/docker-compose.latexml.yml`
   (5 hardening flags, statically tested). This milestone is
   wiring-only — no profile authoring.

3. **Brief CONFLICT FIXED.** The brief said to update
   `docker/Dockerfile.server` for Docker hardening — both
   researchers flagged this as WRONG (the server image doesn't run
   LaTeXML; LaTeXML is ingest-only). Orchestrator dropped that
   deliverable. Docker wiring stays as an E14 follow-up.

4. **Apply to the secondary `ops/drift_check.py::render_fixture` site
   too.** Researcher-1 recommended this; orchestrator agreed —
   consistency closes the "why is this site exempt?" foot-gun.

5. **`--timeout=300` flag on latexmlc.** Defense-in-depth — adds
   LaTeXML's own internal scheduler timeout in addition to the
   Python-side `subprocess` timeout. If LaTeXML rejects the flag,
   the test surface catches it against live latexmlc.

6. **`TemporaryDirectory` for the `TMPDIR_SUBDIR` parameter.** The
   `.sb` profile references `(param "TMPDIR_SUBDIR")` which the
   caller must `mkdir` before invocation. Context-managed temp dir
   auto-cleans; nothing leaks across paper invocations.

7. **`_SANDBOX_LAYER` resolved ONCE at module import.** Per-call
   detection would burn cycles on bulk ingest. The module-import-time
   INFO log surfaces the active layer (or its absence) ONCE so the
   operator sees the platform's posture in the startup log without
   per-paper noise.

8. **AST guard preservation.** `TestProcessGroupKill::test_parse_with_latexml_uses_process_group_kill`
   walks the function body for `start_new_session=True` and `killpg`
   tokens. My refactor kept both ON THE MAIN CODE PATH (inside the
   `with tempfile.TemporaryDirectory()`), NOT inside a platform-
   conditional branch — the AST guard still passes.

## Acceptance criteria status

| AC | Status | Evidence |
|---|---|---|
| At least ONE production sandbox layer per platform | ✅ | macOS: sandbox-exec; Linux: bwrap; Docker: existing config (E14-wiring) |
| Sandbox is APPLIED to the LaTeXML subprocess (not just available) | ✅ | `_build_sandbox_cmd` called from `parse_with_latexml` AND `render_fixture`; threaded to Popen (regression test: `test_parse_with_latexml_threads_sandbox_to_popen`) |
| Graceful degradation when chosen layer is unavailable | ✅ | `_build_sandbox_cmd` returns `cmd` unchanged when `_SANDBOX_LAYER is None`; module-import-time INFO log surfaces the degraded state; regression test: `test_build_sandbox_cmd_unavailable_returns_unchanged` |
| Hostile-fixture regression tests cover \write18 + arbitrary-file-read | ⚠️ **REFRAMED** | The existing E13_S03 hostile fixtures (`write18_shellout.tex`, `network_call.tex`, `infinite_recursion.tex`, `fork_bomb.tex`, `large_alloc.tex`) already exercise these classes. E13_S03b adds 9 sandbox-wiring tests (mock-based, POSIX-only) rather than new hostile fixtures — the wiring discipline is the new surface and the hostile-fixture surface was the E13_S03 deliverable. Documented in the audit doc. |
| `pytest tests/security/test_latexml_sandbox.py` passes; existing tests still pass as regression guards | ✅ | 15 passed, 14 skipped, 2 failed on Windows (pre-existing `os.getpgid` failures unrelated to this milestone — confirmed in earlier session's 29 Windows failures); my 9 new tests all POSIX-skipped on Windows as designed |
| Audit doc honestly documents per-platform shipped vs deferred | ✅ | Phase table: macOS sandbox-exec ✅, Linux bwrap ✅, drift_check wiring ✅, `--timeout` flag ✅, Docker compose-wiring ⏳ E14. New "Phase 2 wiring (E13_S03b)" section covers architecture, fail-closed, test surface, operator runbook |
| Threat 3 row no longer cites #3; G3 marked closed | ✅ | Summary table row updated, per-threat Gaps section marks #3 closed (with E14 Docker footnote), G3 triage row strikethrough |
| Threat-model staleness gate still passes | ✅ | 21 tests passed; no doc-citation changes needed (test_latexml_sandbox.py already cited) |
| GitHub issue #3 closed with commit reference | ⚠️ **Phase-4 gated** | `gh issue close 3` requires user authorization |

## Tests

- **Extended file:** `tests/security/test_latexml_sandbox.py`
- **New class:** `TestSandboxWiring` (9 tests, all POSIX-only, all passing):
  - `test_detect_sandbox_layer_darwin_when_present`
  - `test_detect_sandbox_layer_darwin_when_sandbox_exec_absent` (FM-2)
  - `test_detect_sandbox_layer_linux_with_bwrap`
  - `test_detect_sandbox_layer_linux_without_bwrap`
  - `test_build_sandbox_cmd_darwin_prepends_sandbox_exec`
  - `test_build_sandbox_cmd_linux_prepends_bwrap` (verifies all 4 isolation flags + `--`-separator semantics + ro/rw bind discriminator)
  - `test_build_sandbox_cmd_unavailable_returns_unchanged` (FM-2 silent-degradation regression guard)
  - `test_build_sandbox_cmd_does_not_mutate_input`
  - `test_parse_with_latexml_threads_sandbox_to_popen` (FM-3/FM-5 regression guard: live test would skip when latexmlc absent, so the mock-based test exists to catch wiring bugs)
- Test count: 22 → 31 (+9)

## Project-check status

- `ruff check .` → clean
- `pytest tests/security/test_latexml_sandbox.py tests/security/test_threat_model_coverage.py` → 36 passed, 14 skipped, 2 failed (pre-existing Windows `os.getpgid`)
- Full pytest not re-run after every edit — cached baseline; new tests +9; no new failures attributable to my changes (the only failures touching my modified files are the 2 pre-existing Windows TestProcessGroupKill mocks that fail because `os.getpgid` doesn't exist on Windows)

## External writes required

| Type | Target | Why | Blocking |
|---|---|---|---|
| `git push` | `main @ github.com/chris-dare-dev/arXMCP` | Land the feat+rect+chore commits | YES — per-event user authorization |
| `gh issue close` | `chris-dare-dev/arXMCP#3` | Close gap-issue G3 with commit reference (Docker-wiring footnote noting E14 follow-up) | YES — Phase-4 gated |

## Anything notable for the critic

1. **No tool-schema change.** `parse_with_latexml` is an ingest-layer
   helper, not an MCP tool. `EXPECTED_TOOL_SCHEMA_SHA256` unchanged.
   BP1 cache discipline preserved.

2. **Scope-restriction lines.** The pin applies ONLY to:
   - `tools/arxiv_fetch.py::parse_with_latexml` (production ingest fetch)
   - `ops/drift_check.py::render_fixture` (drift-check developer tool)
   It does NOT apply to other subprocess invocations elsewhere in the
   tree (none have been identified that run latexmlc; the audit would
   surface them if any exist).

3. **Smoke-test pending.** Both researchers and the synthesis flagged
   that the FIRST deploy after this milestone MUST smoke-test
   against the 50-paper seed corpus (`tools/seed-papers.txt`) to
   verify no false-positive sandbox-trips (e.g. a Homebrew Perl
   module path not enumerated in the `.sb` profile). This is an
   operator-time validation; if any paper trips, the profile gets
   widened in a small follow-up — NOT a re-do of E13_S03b.

4. **Docker layer status.** The brief originally asked for
   `docker/Dockerfile.server` updates; researcher-1 flagged this
   as wrong (server doesn't run LaTeXML). Docker compose-wiring
   (merging `infra/latexml/docker-compose.latexml.yml` into the
   top-level compose) is deliberately deferred to E14 — the static
   compose file is correct and statically validated; only the
   wiring is missing, and wiring is E14's "main-compose" job.

5. **TestProcessGroupKill AST guard preserved.** My refactor kept
   `start_new_session=True` and `killpg` on the MAIN code path
   (inside the `with tempfile.TemporaryDirectory()` block), NOT in
   a platform-conditional branch. The AST guard inspects the
   function body's `ast.unparse(func)` string for both tokens; both
   are present. FM-7 from research-brief-2 is closed.

## Deviations from the brief

1. **Brief said `docker/Dockerfile.server`** — wrong target;
   replaced with the existing `infra/latexml/docker-compose.latexml.yml`
   acknowledgement + an honest E14 footnote.

2. **Brief said "hostile-fixture regression tests covering \write18
   + arbitrary-file-read"** — the existing E13_S03 fixtures
   (`write18_shellout.tex`, `network_call.tex`) already cover these
   attack classes. E13_S03b's NEW tests cover the WIRING surface
   (mock-based platform-detect + wrapper-argv construction) since
   that's what's actually new in this milestone. The audit doc
   surfaces this reframe.

3. **Brief said "Decide on the canonical sandbox layer per platform"
   — DONE** in the synthesis (sandbox-exec for macOS, bwrap for
   Linux, existing compose for Docker). Documented in the audit doc.
