# Research Brief — E13_S03

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-18T01:30:00Z

## In-codebase context

### Load-bearing constraint from `08-security-observability-ops.md` § Threat 3 (verbatim):

> LaTeX is Turing-complete. A malicious paper could ship a `.tex` source designed
> to consume infinite RAM, write arbitrary files, or shell out.
>
> **Mitigations:**
> - LaTeXML runs in a **subprocess with a hard timeout** (5 minutes).
> - Subprocess runs as a **separate UID** (Docker user namespace, or
>   rootless container with an unprivileged user inside).
> - Filesystem write whitelist (only the per-paper output directory).
> - No network access from the LaTeXML subprocess.
> - On macOS: `sandbox-exec` profile. On Linux: seccomp + landlock. In Docker:
>   `--read-only`, `--security-opt no-new-privileges`, dedicated user.
>
> **Never** invoke LaTeXML inside the MCP server process itself. The server has
> network access; the parser doesn't need it.

### Key codebase findings:

**Actual LaTeXML invocation site** (`tools/arxiv_fetch.py::parse_with_latexml`):
```python
cmd = ["latexmlc", str(main_tex.name), f"--dest={out_html}", "--format=html5"]
proc = subprocess.run(cmd, cwd=main_tex.parent, capture_output=True, text=True, timeout=timeout)
```
- `LATEXML_TIMEOUT_SECONDS = 300` (5 minutes, matches design note)
- `subprocess.run()` with `timeout=` raises `TimeoutExpired` then calls `proc.kill()` (SIGKILL to direct child only)
- **CRITICAL GAP:** No `start_new_session=True` or `os.setsid()` — grandchildren of `latexmlc` are NOT killed on timeout
- **NO** `sandbox-exec` wrapping in current code; the docstring explicitly says: "for now this is unsandboxed dev tooling"
- **NO** `--shell-escape` flag passed — LaTeXML is not invoked with shell escape enabled, which is the safe default

**Dependency check:** E02_S02 is **real** (state: complete, preamble extractor milestone). E06_S03 is also real (complete, 7-tool surface).

**Doc placement violation in brief:** The brief mandates `docs/security/threat-3-audit.md`. Per CLAUDE.md §1 and the established E13 precedent (E13_S01 implementation-summary §Drift item 7), the correct destination is `.claude/docs/security-threat-3-audit.md`.

**Docker infrastructure does NOT exist yet:** No `docker-compose.yml` anywhere in the repo. `infra/` contains only `observability/phoenix-compose.yml` and `prometheus/alerts.yml`. The brief's AC "Docker compose config has `--network=none`" tests non-existent infrastructure. The brief's note says "On Docker the `--network=none` flag is verified" — but E14 is where docker-compose lands. **The Docker AC is unimplementable in E13_S03.**

**`ops/parser-failures/`:** Directory exists at `var/arxmcp/ops/parser-failures/` (confirmed; contains `chunk.log` and `preamble.log`). The AC requiring papers to land here is feasible.

**`tests/security/`:** Directory exists with `__init__.py`, `test_delimiters.py`, `test_path_traversal.py`. New `test_latexml_sandbox.py` can be added here.

**`infra/latexml/`:** Does not exist. Must be created.

## Prior decisions and lessons

From E13_S01 implementation-summary and memory:
- Doc placement: `docs/security/` is wrong; `.claude/docs/security-threat-N-audit.md` is established precedent
- E07 roadmap milestones beyond S04 are fictional — but E06_S03 is real; dependency is valid
- The "tested in CI" AC reframes to `make test` participation (no CI at v1)
- E13_S01 and E13_S02 both used the pattern: 1 new test file + 1 audit doc under `.claude/docs/`

From git log: The last three commits show E13_S01 (`feat(server,tests)`) → rect → finalize pattern, then E13_S02 same. E13_S03 should follow the same three-commit triple.

**Known pattern from E13_S01/S02:** The milestone briefs consistently reference fictional dependencies (E07_S12, E07_S13) and wrong doc paths. Same pattern applies here.

## External sources

### LaTeXML attack surface

**`\write18` in LaTeXML:** LaTeXML does NOT use the TeX engine directly — it is a Perl-based reimplementation of TeX's semantic layer. `\write18` (shell escape) in standard TeX is disabled by default in TeX distributions. LaTeXML processes `\write18` commands but its `LaTeXML::Common::Config` documentation shows **no `--shell-escape` flag** — shell execution via `\write18` is not implemented in LaTeXML in the same way as pdflatex. The write18 fixture may be ineffective. **This is a fixture design risk.**

**LaTeXML timeout mechanism (GitHub issue #695):** The `--timeout` flag sends ALRM signal, which fires, but the error reporting layer buries it under `perl:die`. The mechanism *technically fires* but may not surface as a clean timeout exit code. Python-side `subprocess.run(timeout=300)` uses `proc.kill()` (SIGKILL) which is more reliable than ALRM. However, the Python kill only reaches the direct child (`latexmlc`), not any grandchild Perl workers LaTeXML may fork.

**LaTeXML network/URL input:** LaTeXML resolves `\input{file}` relative to cwd (set to source directory in current invocation). Whether LaTeXML follows `\input{http://...}` URLs depends on its Perl LWP::UserAgent configuration. LaTeXML's `--includestyles` flag is OFF by default (conservative posture). No documentation confirms HTTP URL resolution is enabled by default — this fixture may silently fail to trigger a network call, producing a false-negative test.

**LuaTeX CVE-2023-32700 / CVE-2023-32668:** LuaTeX (NOT LaTeXML) had arbitrary shell command execution even without `--shell-escape`. These do NOT apply to LaTeXML directly, but demonstrate the attack class is real.

**Lua-based `large_alloc.tex` fixture:** LaTeXML does NOT run Lua — it is Perl-based. The `large_alloc.tex` fixture using "a custom Lua snippet" will NOT work as described. LaTeXML has no LuaTeX integration. **This fixture design is broken before the milestone begins.**

### macOS `sandbox-exec` status

`sandbox-exec` is deprecated (circa 2016, API marked deprecated; still functional as of macOS 15 Darwin 25.x). Multiple bypass CVEs documented in 2023-2024:
- CVE-2023-27944, CVE-2023-32414, CVE-2023-32404 (XPC service exploitation)
- CVE-2023-42977 (PerfPowerServices)
- Main bypass class: attacking XPC services reachable from within the sandbox

**Critical sandbox-exec behavior:** Forked child processes inherit the sandbox, but processes launched via `LaunchServices.framework` do NOT. For LaTeXML (a Perl process forking directly via POSIX, not LaunchServices), children DO inherit the sandbox. This is favorable for our use case.

**sandbox-exec is not a supported replacement for App Sandbox** — it is a best-effort containment tool. For single-developer localhost threat model documented in `08-security-observability-ops.md`, it is appropriate.

### Docker `--network=none` and DNS

`--network=none` is purely network namespace isolation — it does NOT prevent all escape vectors (filesystem, procfs, capabilities). Importantly: `--network=none` **does** block DNS lookups inside the container because there is no network interface and no access to Docker's embedded DNS. The `systemd-resolved` leak risk applies only to containers with some network mode; `none` is total isolation at the network namespace level.

### Hostile LaTeX corpora

No dedicated public fuzz corpus for LaTeX/LaTeXML hostile inputs found. USENIX LOGIN 2010 paper "Don't Take LaTeX Files from Strangers" (Checkoway et al.) documents the attack class. The five fixtures in the brief are reasonable coverage for a manual curated set.

## Failure-mode analysis (10 modes, grounded in `08-security-observability-ops.md`)

**FM-1: Timeout doesn't kill grandchildren.** `subprocess.run(timeout=300)` calls `proc.kill()` (SIGKILL) on the direct `latexmlc` child. If `latexmlc` forks subprocesses (Perl `fork()`, external helpers), grandchildren become zombies or orphans under `init`. On macOS, zombie Perl processes may continue consuming memory. **Mitigation:** use `os.setsid()` via `start_new_session=True` in `subprocess.Popen`, then `os.killpg(os.getpgid(proc.pid), signal.SIGKILL)` on timeout to kill the entire process group.

**FM-2: Sandbox not applied (no sandbox-exec wrapper).** The current `parse_with_latexml` runs `latexmlc` directly with no `sandbox-exec` wrapper. E13_S03 adds the sandbox profile, but the test must invoke LaTeXML via `sandbox-exec -f sandbox.sb latexmlc ...` — NOT the current bare invocation path. The test harness needs its own invocation helper, not the `tools/arxiv_fetch.py::parse_with_latexml` function.

**FM-3: `\write18` fixture doesn't trigger shell-out in LaTeXML.** LaTeXML is not pdflatex — its `\write18` implementation is a Perl stub that may silently no-op rather than execute shell commands. The test asserting "host filesystem unmodified" may pass vacuously. Fix: verify that the fixture actually attempts the shell-out by checking LaTeXML stderr for a shell-escape attempt log line, or use a different mechanism (e.g., a writable named pipe the fixture tries to write to).

**FM-4: `large_alloc.tex` doesn't work (wrong engine).** LaTeXML is Perl-based, not LuaTeX. A Lua snippet for memory allocation does nothing. **This fixture must be redesigned.** Alternative: generate a deeply nested math structure or a table with 10^6 cells to trigger memory exhaustion in LaTeXML's Perl heap.

**FM-5: `network_call.tex` silently fails (URL input may not be followed).** LaTeXML's `\input{http://...}` behavior is undocumented as a network fetch. If LaTeXML treats it as a local file path (failing with "file not found"), the test passes vacuously without actually testing network containment. Fix: use a DNS resolution attempt (e.g., write a custom LaTeXML binding that calls Perl's `LWP::UserAgent`) or accept that this fixture tests LaTeXML's file-input behavior rather than network egress.

**FM-6: LaTeXML exits 0 on hostile input (silent success).** LaTeXML may handle certain hostile inputs by producing degraded output rather than failing. The current `detect_parse_success` in `tools/arxiv_fetch.py` checks exit code + HTML size + MathML presence. A test that only asserts `parse_status="parse_failed"` may miss cases where LaTeXML exits 0 but the sandbox held. The test should assert BOTH that containment held (filesystem clean, timeout enforced) AND that the output is degraded — these are independent assertions.

**FM-7: Stale `/tmp/pwned.txt` from prior test run.** If a test run partially succeeds (sandbox fails, shell-out runs, `/tmp/pwned.txt` is created), a subsequent test run will see the file as pre-existing. The assertion "host filesystem outside output dir is unmodified" must record a baseline fingerprint of `/tmp/` before running the fixture, not just check for the file's existence. Implementation: `glob.glob('/tmp/*')` before and after, diff the two sets.

**FM-8: macOS-only `sandbox-exec` test runs on Linux CI.** `sandbox-exec` is macOS-only. Tests that call `sandbox-exec` must be marked `@pytest.mark.skipif(sys.platform != 'darwin', reason="sandbox-exec is macOS-only")`. The milestone has no CI (reframes to `make test`), but the skip discipline prevents failures on any Linux dev environment.

**FM-9: Docker AC is unimplementable.** No `docker-compose.yml` exists. The AC "Docker compose config has `--network=none`" cannot be verified or tested. Recommended approach: create `infra/latexml/docker-compose.latexml.yml` as a standalone file (NOT the main compose, which is E14's job) that documents the intended `--network=none` configuration. The test can parse this YAML file and assert the network mode value — no Docker daemon required.

**FM-10: `fork_bomb.tex` triggers OOM before timeout fires.** `\newcommand{\fb}{\fb\fb}` causes LaTeXML's Perl process to expand exponentially in the Gullet. Memory exhaustion may trigger the kernel OOM killer faster than the 300s timeout fires, terminating the process uncleanly. The test should tolerate both `TimeoutExpired` and `returncode == -9` (OOM kill) as valid containment outcomes — both mean "subprocess terminated without sandbox escape."

## Recommendation

**Implement E13_S03 with four concrete changes from the brief's spec:**

1. **Redesign `large_alloc.tex`** — replace the Lua snippet with a LaTeXML-compatible memory bomb (deeply nested `\begin{array}` or a recursive macro that generates 2^20 math atoms). LaTeXML's Perl heap will exhaust on this without Lua.

2. **Process group kill discipline** — wrap the `subprocess.run` call in `Popen` with `start_new_session=True` and use `os.killpg` on timeout. This is a one-function fix to `parse_with_latexml` that eliminates FM-1.

3. **Docker AC reframe** — create `infra/latexml/docker-compose.latexml.yml` with the documented `--network=none` config. The test asserts this YAML file contains `network: none`. No running Docker required. This unblocks the AC without depending on E14.

4. **Audit doc placement** — write `infra/latexml/sandbox.sb` as specified, but write the audit doc to `.claude/docs/security-threat-3-audit.md` (not `docs/security/`), consistent with E13_S01/S02 precedent.

The test harness should invoke LaTeXML via `sandbox-exec -f infra/latexml/sandbox.sb latexmlc ...` on macOS, and bare `latexmlc ...` (with process-group kill) on Linux. Platform skips handle the difference.

## Open questions

1. **Does LaTeXML's `\write18` attempt shell execution at all?** If not, `write18_shellout.tex` tests a non-attack (vacuous pass). Empirical verification needed before shipping the fixture — run the fixture through LaTeXML and inspect stderr. Recommend: add a shell-executed marker the test can detect (e.g., write to a pre-agreed canary path), but accept "LaTeXML silently ignores \write18" as a valid PASS with a WARNING comment in the test.

2. **Does `\input{http://...}` trigger a network request in LaTeXML?** Same issue as FM-5. If not, the fixture does not test network containment. Could be replaced with a direct Perl `use LWP::UserAgent; GET http://attacker.example.com` via a `.ltxml` binding, but that requires LaTeXML package authoring expertise.

These two open questions affect fixture effectiveness but not containment correctness. The sandbox profile and process-group discipline are valid regardless of whether the fixtures trigger the named attacks. The implementer should **ship the fixtures as-is** with skeptical commentary in test docstrings, rather than block on empirical pre-verification.

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| filesystem | `tests/security/test_latexml_sandbox.py` | New test file |
| filesystem | `tests/security/fixtures/latexml/` (5 `.tex` files) | Hostile fixture corpus |
| filesystem | `infra/latexml/sandbox.sb` | macOS sandbox-exec profile |
| filesystem | `infra/latexml/docker-compose.latexml.yml` | Documented Docker network config (AC workaround) |
| filesystem | `.claude/docs/security-threat-3-audit.md` | Audit doc (corrected path — NOT `docs/security/`) |
| git commit | main | `feat(tests,infra): LaTeXML sandbox hostile-input tests (E13_S03)` |
| git commit | main | `rect(...)` — adversary findings |
| git commit | main | `chore(notes): finalize E13_S03 state -> complete` |
