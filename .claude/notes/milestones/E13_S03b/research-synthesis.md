# Research Synthesis — E13_S03b

**Milestone:** E13_S03b — Wire the production LaTeXML sandbox layers (Threat 3)
**Mode:** standard (2× researcher, parallel)
**Synthesized:** 2026-05-23 (orchestrator, main session)
**Briefs merged:** research-brief-1.md, research-brief-2.md

## One-line scope

Wire `sandbox-exec` (macOS) and `bubblewrap` / `bwrap` (Linux) into
`tools/arxiv_fetch.py::parse_with_latexml` (and the secondary
`ops/drift_check.py::render_fixture` site) by prepending the wrapper
argv to the existing `cmd` list. Degrade gracefully to
subprocess+timeout-only when neither is available. The sandbox profile
(`infra/latexml/sandbox.sb`) and Docker compose
(`infra/latexml/docker-compose.latexml.yml`) already exist (E13_S03)
and are correctly hardened — this milestone is **wiring work**, not
profile-authoring work. Closes GitHub issue #3 / gap G3.

## Agreed facts (both briefs concur)

1. **Existing infrastructure is COMPLETE.** `infra/latexml/sandbox.sb`
   and `infra/latexml/docker-compose.latexml.yml` were shipped by
   E13_S03 as Phase-1 artifacts. They're correctly hardened (the
   sandbox profile passed adversary review with explicit credential-
   directory denies; the docker-compose has all 5 hardening flags) and
   statically tested. **Only the WIRING is missing.**

2. **Single invocation site.** `tools/arxiv_fetch.py::parse_with_latexml`
   (lines ~322–394) uses `subprocess.Popen(cmd, ..., start_new_session=True)`
   with `cmd = ["latexmlc", str(main_tex.name), f"--dest={out_html}", "--format=html5"]`.
   No `command_wrapper` injection point exists — requires prepending
   wrapper argv directly to `cmd`. Secondary site:
   `ops/drift_check.py::render_fixture` (lines ~115–169) uses
   `subprocess.run(...)` WITHOUT `start_new_session=True`.

3. **macOS approach — `sandbox-exec`.** Prepend
   `["/usr/bin/sandbox-exec", "-f", str(profile), "-D", f"SOURCE_DIR=...", "-D", f"OUTPUT_DIR=...", "-D", f"HOME=...", "-D", f"TMPDIR_SUBDIR=..."]`
   to the `cmd` list. `sandbox-exec` is built-in (no install). Status:
   DEPRECATED per `man sandbox-exec` but still functional on Darwin
   25.x; document the deprecation.

4. **Linux approach — `bubblewrap` (`bwrap`).** Both briefs strongly
   recommend bwrap over raw seccomp+landlock/ctypes/sandlock.
   Reasons: (a) ships as a distro package
   (`apt install bubblewrap`); (b) no Python C extension required;
   (c) combines filesystem namespace + network isolation in one tool;
   (d) used by Flatpak (well-audited); (e) NOT setuid root (unlike
   Firejail which has past CVEs). Argv form:
   ```python
   ["bwrap", "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib",
    "--ro-bind", "/lib64", "/lib64", "--ro-bind", str(source_dir), str(source_dir),
    "--bind", str(output_dir), str(output_dir),
    "--tmpfs", "/tmp", "--unshare-net", "--unshare-pid",
    "--die-with-parent", "--new-session", "--",
    "latexmlc", ...]
   ```

5. **Docker approach — NO code changes.**
   `infra/latexml/docker-compose.latexml.yml` already encodes
   `read_only`, `security_opt: no-new-privileges`, `cap_drop: ALL`,
   `network_mode: none`, `user: "65534:65534"`. The audit doc marks
   this as "complete via static documentation"; "wired to actual
   invocation" awaits E14 main-compose merge.

6. **Graceful degradation contract.** When neither sandbox-exec
   (macOS) nor bwrap (Linux) is available, prepend nothing and
   return the original `cmd`. Log the degraded state so an operator
   sees it. The subprocess+timeout primitives (start_new_session +
   killpg + 5-minute timeout) remain on the main code path
   unchanged.

7. **Windows handling.** All three sandbox layers (sandbox-exec,
   seccomp, landlock) are POSIX-only. Windows takes the degraded
   path unconditionally. All sandbox-layer unit tests for
   wrapper-presence wiring use `@pytest.mark.skipif(sys.platform == "win32", ...)`.

8. **`start_new_session=True` + `killpg` discipline must stay on
   the main code path.** The existing
   `TestProcessGroupKill::test_parse_with_latexml_uses_process_group_kill`
   AST guard walks `parse_with_latexml` for these tokens — if the
   refactor moves them into platform-conditional branches, the AST
   guard can pass with a false-positive (tokens present but only
   on a never-taken branch). Only the `cmd` construction is
   platform-conditional; the Popen + timeout handling stay
   platform-independent.

9. **`--timeout=300` flag on latexmlc.** Add to `cmd` for
   defense-in-depth (LaTeXML's own timeout in addition to the
   Python-side `timeout=305`). Memory-note pattern from E13_S03
   research; researcher-1 recommends, researcher-2 doesn't object.

10. **No tool-schema impact.** `parse_with_latexml` is an
    ingest-layer helper, not an MCP tool.
    `EXPECTED_TOOL_SCHEMA_SHA256` unchanged. BP1 cache discipline
    preserved.

11. **No-fork policy compliance.** bubblewrap and sandbox-exec are
    system binaries (Apache-2.0 / system-supplied) — invoked via
    subprocess. No code copied from external repos.

## Divergences resolved by orchestrator

### D1 — Brief said "Updates to `docker/Dockerfile.server`"; researcher-1 flagged this as WRONG.

`Dockerfile.server` is the MCP server image — does NOT run LaTeXML.
LaTeXML is invoked only during ingest (`tools/arxiv_fetch.py`).
**Orchestrator resolution: drop the `Dockerfile.server` deliverable
from the brief.** The Docker layer is already covered by the
existing `infra/latexml/docker-compose.latexml.yml`. The audit doc
should document this honestly: "Docker layer: static config
shipped; wired-to-invocation is an E14 deliverable when the main
compose lands."

### D2 — bwrap argv: trade-off `--die-with-parent` vs `--new-session` vs both.

- **Researcher-1** suggests `--die-with-parent --unshare-net --unshare-pid`.
- **Researcher-2** suggests `--unshare-net --unshare-pid --new-session`.

**Orchestrator resolution: include both `--die-with-parent` AND `--new-session`.**
They address different concerns: `--die-with-parent` kills the
sandboxed process if the parent dies (cleanup); `--new-session`
puts the bwrap process in its own session (aligns with the
existing `start_new_session=True` discipline so the
process-group-kill path works correctly through the bwrap wrapper).
Both are cheap (no extra dependencies), both improve robustness.

### D3 — Profile path resolution at runtime.

- **Researcher-1** recommends
  `Path(__file__).resolve().parent.parent / "infra/latexml/sandbox.sb"`
  (repo-root-relative anchored via `tools/`).
- **Researcher-2** doesn't address explicitly.

**Orchestrator resolution: researcher-1's `__file__`-anchored
approach.** No new Config field — keeps the wiring local to
`tools/arxiv_fetch.py` and respects the milestone's wiring-only
scope. If a future deployment needs operator override, that's a
separate Config-field milestone.

### D4 — `TMPDIR_SUBDIR` creation strategy.

- **Researcher-2's open question.** The sandbox-exec profile
  references `(param "TMPDIR_SUBDIR")`; the caller must `mkdir`
  this path before invocation.

**Orchestrator resolution: use `tempfile.TemporaryDirectory()`
context manager around the sandbox invocation.** Auto-cleanup;
no stale tmp dirs; pytest-friendly. The `TMPDIR_SUBDIR` parameter
gets the resulting `Path`.

### D5 — Logging cadence for sandbox-unavailable degradation.

- **Researcher-2's open question** — DEBUG vs WARNING; per-call vs
  per-process.

**Orchestrator resolution: log INFO once per process at module
import** (so operators see a single line at startup confirming
which sandbox layer is in use, OR explicitly saying none is
available). Per-call: DEBUG only (avoids per-paper spam during
bulk ingest). The one-time INFO uses a module-level
`_sandbox_layer` global resolved at import.

### D6 — Apply sandbox to `ops/drift_check.py::render_fixture`?

- **Researcher-1** recommends YES — 3-line consistency change.
- **Researcher-2** silent.

**Orchestrator resolution: YES, apply.** Consistency closes the
"why is this site exempt?" foot-gun. The render_fixture path also
runs latexmlc on potentially-untrusted .tex fixtures — same
threat class, same mitigation should apply.

## Implementation plan (INLINE — orchestrator, main session)

Size estimate: ~250-300 LOC including tests. Inline; well under the
delegated-path threshold.

1. **`tools/arxiv_fetch.py`** — Add module-level constants:
   ```python
   SANDBOX_PROFILE_PATH = (
       Path(__file__).resolve().parent.parent
       / "infra" / "latexml" / "sandbox.sb"
   )
   _LATEXML_TIMEOUT_SECONDS = 300  # latexmlc CLI flag
   ```

2. **New helper `_build_sandbox_cmd`**:
   ```python
   def _build_sandbox_cmd(
       cmd: list[str], source_dir: Path, output_dir: Path,
       tmpdir_subdir: Path,
   ) -> list[str]:
       """Prepend the platform-appropriate sandbox wrapper to cmd.
       Returns cmd unchanged when no sandbox layer is available."""
       layer = _detect_sandbox_layer()
       if layer == "sandbox-exec":
           return [
               "/usr/bin/sandbox-exec",
               "-f", str(SANDBOX_PROFILE_PATH),
               "-D", f"SOURCE_DIR={source_dir}",
               "-D", f"OUTPUT_DIR={output_dir}",
               "-D", f"HOME={Path.home()}",
               "-D", f"TMPDIR_SUBDIR={tmpdir_subdir}",
               *cmd,
           ]
       elif layer == "bwrap":
           bwrap_args = [
               "bwrap",
               "--ro-bind", "/usr", "/usr",
               "--ro-bind", "/lib", "/lib",
           ]
           # /lib64 may not exist on 32-bit; bind only if present.
           if Path("/lib64").exists():
               bwrap_args.extend(["--ro-bind", "/lib64", "/lib64"])
           # /etc subset for fontconfig + kpathsea
           bwrap_args.extend(["--ro-bind", "/etc", "/etc"])
           bwrap_args.extend([
               "--ro-bind", str(source_dir), str(source_dir),
               "--bind", str(output_dir), str(output_dir),
               "--tmpfs", "/tmp",
               "--unshare-net", "--unshare-pid",
               "--die-with-parent", "--new-session",
               "--",
           ])
           return [*bwrap_args, *cmd]
       else:
           return cmd  # degraded
   ```

3. **`_detect_sandbox_layer` (module-level, cached)**:
   ```python
   def _detect_sandbox_layer() -> str | None:
       """Returns 'sandbox-exec' / 'bwrap' / None."""
       if sys.platform == "darwin":
           if Path("/usr/bin/sandbox-exec").is_file() and SANDBOX_PROFILE_PATH.is_file():
               return "sandbox-exec"
       elif sys.platform.startswith("linux"):
           if shutil.which("bwrap") is not None:
               return "bwrap"
       return None

   _SANDBOX_LAYER = _detect_sandbox_layer()
   if _SANDBOX_LAYER is None:
       logger.info(
           "LaTeXML sandbox layer: NONE — running subprocess+timeout only "
           "(Threat 3 partially mitigated; platform=%s). See "
           ".claude/docs/security-threat-3-audit.md.",
           sys.platform,
       )
   else:
       logger.info(
           "LaTeXML sandbox layer: %s (Threat 3 fully mitigated for ingest path).",
           _SANDBOX_LAYER,
       )
   ```

4. **`parse_with_latexml` modification** — minimal:
   ```python
   cmd = [
       "latexmlc",
       f"--timeout={_LATEXML_TIMEOUT_SECONDS}",  # NEW (defense-in-depth)
       str(main_tex.name),
       f"--dest={out_html}",
       "--format=html5",
   ]
   with tempfile.TemporaryDirectory(
       prefix=f"arxmcp-latexml-{paper_id}-"
   ) as tmpdir:
       cmd = _build_sandbox_cmd(
           cmd,
           source_dir=main_tex.parent,
           output_dir=out_html.parent,
           tmpdir_subdir=Path(tmpdir),
       )
       proc = subprocess.Popen(  # noqa: S603
           cmd,
           cwd=main_tex.parent,
           stdout=subprocess.PIPE,
           stderr=subprocess.PIPE,
           text=True,
           start_new_session=True,  # MUST stay on main path (AST guard)
       )
       # ... existing timeout handling (killpg on TimeoutExpired) unchanged
   ```

5. **`ops/drift_check.py::render_fixture`** — same sandbox prepend
   (also gain `start_new_session=True` for parity).

6. **Tests in `tests/security/test_latexml_sandbox.py`** —
   new class `TestSandboxWiring`:
   - `test_detect_sandbox_layer_darwin` — monkeypatch
     `sys.platform="darwin"` + `Path.is_file=lambda...`; asserts
     "sandbox-exec".
   - `test_detect_sandbox_layer_linux_with_bwrap` —
     `sys.platform="linux"`, `shutil.which=lambda n: "/usr/bin/bwrap" if n=="bwrap" else None`;
     asserts "bwrap".
   - `test_detect_sandbox_layer_unavailable` — neither
     available; asserts None.
   - `test_build_sandbox_cmd_darwin_prepends_sandbox_exec` —
     verifies argv structure: starts with `/usr/bin/sandbox-exec`,
     contains `-f profile.sb`, `-D` params, ends with original cmd.
   - `test_build_sandbox_cmd_linux_prepends_bwrap` — verifies
     argv: starts with `bwrap`, contains `--unshare-net`,
     `--unshare-pid`, ends with original cmd after `--`.
   - `test_build_sandbox_cmd_unavailable_returns_unchanged` —
     monkeypatch `_SANDBOX_LAYER=None`; assert returned cmd is
     unchanged (same list).
   - All POSIX-only:
     `@pytest.mark.skipif(sys.platform == "win32", ...)`.

7. **`.claude/docs/security-threat-3-audit.md`** — update Phase
   table rows 5–6 to `✅ E13_S03b`. Add a new section
   "Sandbox wiring (E13_S03b)" documenting platform-detect logic,
   degraded path, and what each layer blocks. Honestly document
   the Docker layer as "static config shipped (E13_S03); wiring
   awaits E14 main-compose merge."

8. **`.claude/docs/security-threat-model-coverage.md`** — Threat
   3 row + G3 triage row marked closed by E13_S03b.

9. **Verify**: pytest tests/security/test_latexml_sandbox.py
   passes (existing 4 tests + new TestSandboxWiring); ruff clean;
   full pytest no new regressions.

## Smoke-test risk note (deferred to operator)

Both briefs flag: the first deploy of this milestone MUST be
smoke-tested against the 50-paper seed corpus
(`tools/seed-papers.txt`) to verify no false-positive
sandbox-trips (e.g. a Homebrew Perl module path not enumerated in
the `.sb` profile). The implementation tests prove the WIRING is
correct; the operator validates the PROFILE against real corpus.
If false-positives surface, the fix is to widen the
`infra/latexml/sandbox.sb` profile (NOT this milestone's scope —
profile-authoring is E13_S03 work; widening is a separate
operational follow-up).

## Open questions (none-blocking)

1. **bwrap availability on production Linux.** Unspecified in
   CLAUDE.md. Modern Ubuntu/Fedora have it via `apt install
   bubblewrap`. If the target Linux distro doesn't ship it, the
   degraded path covers production with a visible startup log.
   Not blocking for E13_S03b.

2. **`--timeout=300` flag on latexmlc.** Memory note recommends
   this; researcher-1 includes; researcher-2 doesn't comment.
   Included in implementation plan as defense-in-depth. If the
   flag is rejected by the installed LaTeXML version, fall back to
   omitting it (test would catch this against live latexmlc; the
   default-case implementation assumes a recent LaTeXML).

## External writes required (deduped union)

| Type | Target | Why | Blocking |
|---|---|---|---|
| `git push` | `main @ github.com/chris-dare-dev/arXMCP` | Land the feat+rect+chore commits | YES — per-event user authorization |
| `gh issue close` | `chris-dare-dev/arXMCP#3` | Close gap-issue G3 once wiring lands | YES — Phase-4 gated |

## Orchestrator synthesis note

Strong agreement on the wiring approach (sandbox-exec + bwrap), the
implementation surface (single helper + `parse_with_latexml` + the
secondary `render_fixture` site), and the test pattern (POSIX-only
mocked sandbox-detection tests). Six divergences resolved:
(D1) drop the misnamed Dockerfile.server deliverable; (D2) include
both `--die-with-parent` AND `--new-session` in bwrap argv;
(D3) `__file__`-anchored sandbox profile path; (D4) TemporaryDirectory
for TMPDIR_SUBDIR; (D5) module-import-time INFO log + per-call DEBUG;
(D6) apply sandbox to the secondary `ops/drift_check.py` site too.

The most important non-blocking risk is **profile false-positives
in production**: the implementation lands the wiring; the operator
validates against the seed corpus. If macOS or Linux smoke-test
fails, widening the profile is a small follow-up (NOT scope creep
of E13_S03b).
