# Research Brief — E13_S03b

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-23T02:45:00Z

---

## In-codebase context

### Threat model — verbatim from `08-security-observability-ops.md` § Threat 3

> "LaTeX is Turing-complete. A malicious paper could ship a `.tex` source designed
> to consume infinite RAM, write arbitrary files, or shell out."
>
> **Mitigations:**
> - LaTeXML runs in a **subprocess with a hard timeout** (5 minutes).
> - Subprocess runs as a **separate UID** (Docker user namespace, or rootless container with an unprivileged user inside).
> - Filesystem write whitelist (only the per-paper output directory).
> - No network access from the LaTeXML subprocess.
> - On macOS: `sandbox-exec` profile. On Linux: seccomp + landlock. In Docker: `--read-only`, `--security-opt no-new-privileges`, dedicated user.
>
> **Never** invoke LaTeXML inside the MCP server process itself. The server has network access; the parser doesn't need it.

### What E13_S03 already shipped

Per `.claude/docs/security-threat-3-audit.md` (the existing audit doc), the phase table:

| Phase | Mitigation | Status |
|---|---|---|
| 1 | Process-group kill on timeout (`start_new_session=True` + `os.killpg`) | ✅ shipped |
| 1 | 5 hostile-fixture test corpus + containment harness | ✅ shipped |
| 1 | `infra/latexml/sandbox.sb` — macOS profile (documented but NOT wired) | ✅ shipped |
| 1 | `infra/latexml/docker-compose.latexml.yml` — static-validated YAML | ✅ shipped |
| 2 | `sandbox-exec` wired into `parse_with_latexml` on macOS | ⏳ **deferred → E13_S03b** |
| 2 | Linux seccomp+landlock filter in the ingest service | ⏳ **deferred → E13_S03b** |
| 2 | Main docker-compose with the LaTeXML service definition | ⏳ deferred → E14 |

### LaTeXML invocation sites

**Primary site — `tools/arxiv_fetch.py::parse_with_latexml` (lines 322–394):**

```python
proc = subprocess.Popen(  # noqa: S603 — fixed argv, no shell
    cmd,
    cwd=main_tex.parent,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    start_new_session=True,
)
```

No `env` parameter is passed — the subprocess inherits the full parent environment (PATH, HOME, AWS credentials, etc.). No sandbox wrapper. No seccomp. No `preexec_fn`. The `cmd` list is `["latexmlc", str(main_tex.name), f"--dest={out_html}", "--format=html5"]` — no `--shell-escape`, which is correct.

**Secondary site — `ops/drift_check.py::render_fixture` (lines 115–169):**

Uses `subprocess.run(...)` WITHOUT `start_new_session=True`. This is a drift-check tool, not production ingest, but it is also a LaTeXML invocation without process-group kill discipline. **E13_S03b should note this site exists and apply the same discipline or explicitly document why it is exempt.**

### Existing sandbox profile and docker config

`infra/latexml/sandbox.sb` is fully authored and correct post-E13_S03 rectification:
- `(version 1)` + `(deny default)` + `(deny network*)` + `(deny mach-bootstrap)` + `(deny mach-lookup)`
- Explicit `(deny file-read* ...)` for `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.config/op`, `~/.netrc`, `~/.kube`, `~/.docker` BEFORE the HOME-relative allows
- Narrow allow for enumerated Perl/CPAN roots only: `~/perl5`, `~/.cpan`, `~/.cpanm`, `~/.perlbrew`, `~/.plenv`, `~/Library/Perl`
- Write allow only on `(param "OUTPUT_DIR")` and `(param "TMPDIR_SUBDIR")`

`infra/latexml/docker-compose.latexml.yml` is also authored and fully correct:
- `network_mode: none`, `read_only: true`, `security_opt: no-new-privileges:true`, `user: "65534:65534"`, `cap_drop: ALL`, `restart: "no"`, `mem_limit: 2g`, `cpus: 1.0`, `tmpfs: /tmp:size=512M`

**The profiles are complete and tested. E13_S03b is ONLY wiring work — calling these profiles from the invocation site.**

### Existing tests — what's already covered

`tests/security/test_latexml_sandbox.py` has four test classes:

1. `TestLatexmlSandboxContainment` — 5 tests; skip if `latexmlc` not on PATH; test side-effect absence and timeout containment using the production `parse_with_latexml`. **These must continue to pass after E13_S03b.**
2. `TestSandboxProfile` — 5 static text-parsing tests on `infra/latexml/sandbox.sb`; always-on (no PATH skip). Tests: `profile_file_exists`, `denies_default`, `denies_network`, `uses_version_1`, `does_not_grant_blanket_home_read`, `denies_credential_directories`.
3. `TestDockerLatexmlConfig` — 7 static YAML-parsing tests on `infra/latexml/docker-compose.latexml.yml`; always-on.
4. `TestProcessGroupKill` — 3 tests (AST check + `test_timeout_fires_killpg_path` mock + `test_catastrophic_case_drains_pipes_and_reraises` mock); always-on.

**Mock pattern used:** `monkeypatch.setattr(af.subprocess, "Popen", _FakeProc)` + `monkeypatch.setattr(af.os, "getpgid", ...)` + `monkeypatch.setattr(af.os, "killpg", ...)`. New sandbox-wiring tests should follow this pattern for the platform-detect path.

### Docker Dockerfile.server — current posture

`docker/Dockerfile.server` already creates a non-root user:
```
RUN groupadd --gid 1000 arxmcp \
    && useradd --uid 1000 --gid arxmcp --shell /bin/bash --create-home arxmcp
...
USER arxmcp
```

What is **missing** from `Dockerfile.server` for Threat 3: the server Dockerfile is for the MCP server only, not the ingest service. There is no `Dockerfile.ingest`. The ingest LaTeXML invocation currently runs as whatever user runs `tools/arxiv_fetch.py` directly — no dedicated UID enforcement outside Docker.

**CONFLICT FLAG: The milestone brief says "Updates to `docker/Dockerfile.server` for Docker hardening." `Dockerfile.server` is the MCP server image, not the ingest image. LaTeXML is invoked only during ingest (`tools/arxiv_fetch.py`). The correct Docker hardening target, if any, is a `docker/Dockerfile.ingest` (which doesn't exist). The implementer should create `docker/Dockerfile.ingest` rather than touching `Dockerfile.server`, OR document that the Docker layer applies only when the operator runs ingest inside Docker.**

---

## Prior decisions and lessons

### From E13_S03 critique artifacts

The adversary critique (`critique-adversary.md`) rated the blanket-`$HOME` sandbox profile as **HIGH** (F1). The rectification (already in `infra/latexml/sandbox.sb`) added explicit credential-directory denies. The profile is correctly hardened. E13_S03b should not re-open F1.

`ops/drift_check.py::render_fixture` uses `subprocess.run` WITHOUT `start_new_session=True`. This is a dev-tool latexmlc invocation not covered by the E13_S03 process-group fix. E13_S03b may optionally apply the same discipline there, but its threat surface is lower (developer workstation, not ingest pipeline).

### CLAUDE.md §8 gotchas relevant here

- **Gotcha 1:** `KMP_DUPLICATE_LIB_OK=TRUE` in `tests/conftest.py` is load-bearing on macOS. `test_latexml_sandbox.py` line 66 already acknowledges this. Do not remove the conftest fixture.
- **Gotcha 8:** Use `uv run python -m pytest` not system `pytest`. Windows platform: `start_new_session=True` is a no-op on Windows (does not call `setsid()`), and `os.killpg` does not exist on Windows — the existing tests that call `parse_with_latexml` are guarded by the `latexmlc not on PATH` skip, which fires on Windows. New sandbox-wiring tests must use `@pytest.mark.skipif(sys.platform == "win32", ...)` for any POSIX-specific sandbox path.

### Memory notes (from `milestone-researcher/MEMORY.md`)

- `latexml-sandbox-is-aspirational-only` (2026-05-18): confirmed — sandbox wiring was correctly deferred to E13_S03b.
- `sandbox-exec-deprecated-but-functional` (2026-05-18): `sandbox-exec` is deprecated per `man sandbox-exec` but still functional on macOS 15+ (Darwin 25.x). The `.sb` profile syntax is Scheme-like.
- `latexmlc-timeout-flag-and-lua` (2026-05-18): pass `--timeout=300` to `latexmlc` CLI AND use Python-side `timeout=305` for defense-in-depth.

---

## External sources

### sandbox-exec (macOS)

`sandbox-exec` invocation from a Python subprocess wrapper:
```python
cmd = [
    "/usr/bin/sandbox-exec",
    "-f", str(profile_path),
    "-D", f"SOURCE_DIR={source_dir}",
    "-D", f"OUTPUT_DIR={output_dir}",
    "-D", f"HOME={Path.home()}",
    "-D", f"TMPDIR_SUBDIR={tmpdir}",
    "latexmlc", ...
]
```

The SBPL profile format uses `(version 1)`, `(deny default)`, `(allow ...)`. Rules are evaluated in order; first match wins. The profile at `infra/latexml/sandbox.sb` is complete. The call requires no external dependencies — `/usr/bin/sandbox-exec` is a built-in macOS binary.

Status: DEPRECATED per `man sandbox-exec` (macOS 13+). Still functional on macOS 15 (Darwin 25.x). No code-signing required for subprocess wrapping. The proper successor (App Sandbox via entitlements + XPC) requires code signing — unsuitable for a dev-tool subprocess. Document deprecation in the updated audit doc.

### seccomp + landlock (Linux)

**Recommendation: use `bubblewrap` (`bwrap`) as the Linux sandbox wrapper rather than raw `prctl(PR_SET_SECCOMP, ...)`.**

Rationale: bubblewrap (`bwrap`) ships as a distro package (`apt install bubblewrap` on Debian/Ubuntu), requires no Python C-extension (unlike `pyseccomp`), provides both filesystem namespacing (landlock-equivalent via bind mounts + `--ro-bind`) and network isolation (`--unshare-net`), and is maintained as a Flatpak infrastructure project with stable semantics. Its invocation is straightforward:

```python
cmd = [
    "bwrap",
    "--ro-bind", "/usr", "/usr",
    "--ro-bind", "/lib", "/lib",
    "--ro-bind", "/lib64", "/lib64",
    "--ro-bind", str(source_dir), str(source_dir),
    "--bind", str(output_dir), str(output_dir),
    "--tmpfs", "/tmp",
    "--unshare-net",
    "--unshare-pid",
    "--die-with-parent",
    "latexmlc", ...
]
```

Alternatives considered and rejected:
- **Raw `prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ...)` via ctypes**: requires authoring a BPF bytecode allowlist or using `pyseccomp` (C extension, extra dep). Fragile to maintain — syscall numbers differ by arch (x86_64 vs arm64). Does not provide filesystem isolation without also wiring landlock (Linux 5.13+, kernel version requirement).
- **`firejail`**: heavier dep, slower, more complex than `bwrap` for this use case.
- **`libseccomp` via `pyseccomp`**: adds a C extension dep, complex allowlist authoring.

`bubblewrap` requires Linux only; detect at runtime with `shutil.which("bwrap")`.

### Docker hardening flags

Current canonical flags (Docker Engine 27.x, 2026):
- `--read-only` — root filesystem read-only
- `--security-opt no-new-privileges` — blocks `setuid` privilege escalation
- `--cap-drop=ALL` — drops all Linux capabilities
- `--user=65534:65534` — `nobody:nobody` (or `1000:1000` for a named non-root user)
- `--network=none` — no network interface, no DNS

All five are already encoded in `infra/latexml/docker-compose.latexml.yml`. The open question is whether E13_S03b adds a `docker/Dockerfile.ingest` to encode the dedicated-UID layer for the ingest service image.

### Dedicated UID

`docker/Dockerfile.server` already has UID 1000 `arxmcp`. For non-container deployments, the operator runbook (`.claude/docs/security-threat-3-audit.md`) should document: run ingest as a dedicated unprivileged user (e.g. `sudo useradd -r -s /bin/false arxmcp-ingest`). This is a documentation deliverable, not a code deliverable.

---

## Recommendation

**Wire `sandbox-exec` on macOS and `bwrap` on Linux into `parse_with_latexml` in `tools/arxiv_fetch.py`. Degrade gracefully to subprocess+timeout-only when neither is available (log a WARNING). Do not add a `Dockerfile.ingest`.**

Specific approach:

1. Add a `_build_sandbox_cmd(cmd: list[str], source_dir: Path, output_dir: Path, tmpdir: Path) -> list[str]` helper in `tools/arxiv_fetch.py` that:
   - On macOS (`sys.platform == "darwin"`): prepends `sandbox-exec` args if `/usr/bin/sandbox-exec` exists and `infra/latexml/sandbox.sb` is readable.
   - On Linux (`sys.platform == "linux"`): prepends `bwrap` args if `shutil.which("bwrap")` is not None.
   - Otherwise: returns `cmd` unchanged; logs `WARNING: no sandbox layer available, running latexmlc with subprocess isolation only`.
   
2. In `parse_with_latexml`, create a `tempfile.TemporaryDirectory` for the bwrap/sandbox-exec `TMPDIR_SUBDIR` parameter, call `_build_sandbox_cmd`, then launch `subprocess.Popen` as today (retaining `start_new_session=True` and `os.killpg` on timeout).

3. New tests in `tests/security/test_latexml_sandbox.py` — a new class `TestSandboxWiring`:
   - `test_sandbox_cmd_darwin_uses_sandbox_exec`: monkeypatch `sys.platform = "darwin"` + `Path.exists` to return True for sandbox-exec and profile; assert `sandbox-exec` is first arg.
   - `test_sandbox_cmd_linux_uses_bwrap`: monkeypatch `sys.platform = "linux"` + `shutil.which("bwrap") = "/usr/bin/bwrap"`; assert `bwrap` is first arg.
   - `test_sandbox_cmd_unavailable_degrades_gracefully`: monkeypatch neither available; assert original `cmd` returned and a WARNING logged.
   - All three: POSIX-only (`@pytest.mark.skipif(sys.platform == "win32", ...)`).

4. Update `.claude/docs/security-threat-3-audit.md` Phase table rows 5–6 to "✅ E13_S03b (macOS: sandbox-exec wired; Linux: bwrap wired; Docker: compose config already present at v1)".

5. Update `.claude/docs/security-threat-model-coverage.md` Threat 3 row + G3 gap-issue row.

6. Close `chris-dare-dev/arXMCP#3` via `gh issue close 3 --comment "Closed by <commit-sha> — sandbox-exec (macOS) and bwrap (Linux) wired into parse_with_latexml"`.

**Do NOT create `Dockerfile.ingest`** — out of scope; the brief says "Refactoring the LaTeXML invocation layer into a generic sandbox-process abstraction" is out of scope, and no ingest Dockerfile exists to anchor the Docker-UID layer. Document the Docker layer as "applied when the operator runs the LaTeXML ingest in the existing `infra/latexml/docker-compose.latexml.yml` container."

---

## Open questions

1. **Profile path at runtime.** `infra/latexml/sandbox.sb` is relative to the repo root. When `tools/arxiv_fetch.py` is invoked from an arbitrary CWD, `Path("infra/latexml/sandbox.sb")` will not resolve. The implementer must decide: (a) resolve relative to `Path(__file__).parent.parent / "infra/latexml/sandbox.sb"` (repo-root-relative anchored to the tools/ dir), or (b) make it a `Config` field `latexml_sandbox_profile_path`. Recommendation: use the `__file__`-relative anchor; this is a dev tool, not a deployed service, and the config field adds overhead for minimal benefit.

2. **`bwrap` Perl module paths on Linux.** The macOS profile enumerates `~/perl5`, `~/.cpan`, etc. `bwrap`'s `--ro-bind` approach must bind-mount the Perl module roots. On a typical Debian/Ubuntu system with system LaTeXML, the Perl modules are under `/usr/share/perl5/` and `/usr/lib/x86_64-linux-gnu/` — already covered by `--ro-bind /usr /usr`. If the operator has CPAN modules under `$HOME`, the bwrap invocation needs `--ro-bind $HOME/perl5 $HOME/perl5` etc. The implementer should enumerate the same Perl roots as the `.sb` profile, translated to `--ro-bind` pairs.

3. **`ops/drift_check.py::render_fixture` — apply process-group fix?** This is a secondary LaTeXML invocation using `subprocess.run` without `start_new_session=True`. E13_S03b should either (a) apply the sandbox wrapper here too, or (b) explicitly document why it is exempt (dev-only, not invoked during ingest, guarded by `latexmlc not on PATH`). Recommendation: apply the sandbox wrapper for consistency; the code change is 3 lines.

4. **Smoke-test after wiring.** The brief's risk notes say: "the first deploy after this lands MUST be smoke-tested against the seed corpus (50 math.AG papers; `tools/seed-papers.txt`) to verify no false-positive sandbox-trips." This is an operational concern for the implementer — if macOS smoke test fails (e.g. Homebrew Perl modules not under enumerated roots), the implementer must widen the profile before committing.

5. **`--timeout` flag on `latexmlc` CLI.** Memory note `latexmlc-timeout-flag-and-lua` recommends passing `--timeout=300` to `latexmlc` AND using Python `timeout=305` for defense-in-depth. This was not done in E13_S03. E13_S03b is a natural point to add `"--timeout=300"` to the `cmd` list in `parse_with_latexml`.

---

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| `gh issue close` | `chris-dare-dev/arXMCP#3` | Close the Threat 3 deferred-sandbox tracking issue once the implementation commit lands |
| `git push` to `main` | `origin/main` | Standard milestone commit triple (feat + rect + chore); per CLAUDE.md §4.4, push is per-event authorized by the user |
