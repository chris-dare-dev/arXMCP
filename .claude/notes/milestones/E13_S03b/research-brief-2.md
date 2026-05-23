# Research Brief — E13_S03b

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-23T02:45:00Z

---

## In-codebase context

### What E13_S03 actually shipped (from `.claude/docs/security-threat-3-audit.md`)

The E13_S03 Phase-1 phasing table is the authoritative picture of what exists vs. what is deferred:

> | Phase | Mitigation | Where | Status |
> |---|---|---|---|
> | 1 | Python-level process-group kill on timeout | `tools/arxiv_fetch.py::parse_with_latexml` | ✅ E13_S03 |
> | 1 | 5 hostile-fixture test corpus + containment test harness | `tests/security/fixtures/latexml/`, `tests/security/test_latexml_sandbox.py` | ✅ E13_S03 |
> | 1 | macOS `sandbox-exec` profile (documentation artifact + test fixture; not wired into production code at v1) | `infra/latexml/sandbox.sb` | ✅ E13_S03 |
> | 1 | Docker isolation config (standalone YAML; static-validated by test; merge into main compose when E14 lands it) | `infra/latexml/docker-compose.latexml.yml` | ✅ E13_S03 |
> | 2 | `sandbox-exec` wired into `parse_with_latexml` on macOS production paths | TBD | ⏳ deferred — E11 |
> | 2 | Linux seccomp+landlock filter in the ingest service | TBD | ⏳ deferred — E11 |

**E13_S03b's job:** wire the Phase-2 layers into `tools/arxiv_fetch.py::parse_with_latexml`. The profile (`infra/latexml/sandbox.sb`) and Docker config (`infra/latexml/docker-compose.latexml.yml`) already exist as documentation artifacts with static tests. The gap is: **neither is connected to the actual subprocess invocation.**

### Current invocation shape (`tools/arxiv_fetch.py::parse_with_latexml`)

The argv is constructed inline — no `command_wrapper` / `prefix_args` injection point:

```python
cmd = [
    "latexmlc",
    str(main_tex.name),
    f"--dest={out_html}",
    "--format=html5",
]
proc = subprocess.Popen(
    cmd,
    cwd=main_tex.parent,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    start_new_session=True,
)
```

**This requires a refactor to prepend the sandbox wrapper args.** Platform detection at runtime (via `sys.platform` and `shutil.which`) decides which wrapper to prepend. The wrapper args must be inserted BEFORE `"latexmlc"` in the argv list. `start_new_session=True` and the `os.killpg` timeout path must be preserved unchanged.

### Design constitution constraints

From `08-security-observability-ops.md` § Threat 3:

> **Mitigations:**
> - LaTeXML runs in a **subprocess with a hard timeout** (5 minutes).
> - Subprocess runs as a **separate UID** (Docker user namespace, or rootless container with an unprivileged user inside).
> - Filesystem write whitelist (only the per-paper output directory).
> - No network access from the LaTeXML subprocess.
> - On macOS: `sandbox-exec` profile. On Linux: seccomp + landlock. In Docker: `--read-only`, `--security-opt no-new-privileges`, dedicated user.
>
> **Never** invoke LaTeXML inside the MCP server process itself.

The phrase "seccomp + landlock" is a conjunction — both are called for on Linux. The design does not say "either/or."

### Key memory items (MEMORY.md — from E13_S03 research cycle)

- **`latexml-sandbox-is-aspirational-only`**: "NO sandbox-exec/seccomp/landlock wrapper exists. The code comments explicitly say it is 'unsandboxed dev tooling.'"
- **`sandbox-exec-deprecated-but-functional`**: "macOS `sandbox-exec` is marked DEPRECATED (man page confirms). It is still functional on Darwin 25.4.0. The .sb profile syntax is Scheme-like: (version 1), (deny default), (allow ...)."
- **`latexmlc-timeout-flag-and-lua`**: "latexmlc does NOT support LuaTeX/\directlua — large_alloc via 'Lua snippet' is fictional; use deeply nested macro expansion instead. \write18 is silently ignored by latexmlc (no shell exec)."
- **`no-docker-compose-exists`**: No docker-compose.yml exists in the repo (only `infra/observability/phoenix-compose.yml`). The Docker design spec is aspirational. Docker hardening for E13_S03b must be documented as a static audit, not verified via `docker inspect`.

### Doc placement

Prior E13 milestones establish: updated audit doc goes to `.claude/docs/security-threat-3-audit.md` (update existing, not new file). Coverage doc at `.claude/docs/security-threat-model-coverage.md` needs Threat 3 row updated. Both are under `.claude/` per CLAUDE.md §1 doc-placement rule.

---

## External sources

### Attack surface — what can a hostile .tex file do?

#### Against pdflatex / xelatex / classical TeX engines

The classic attack surface (0day.work, "Hacking with LaTeX"):
- `\write18{cmd}` — shell execution (requires `--shell-escape`; default off in modern TeX Live)
- `\input{/etc/passwd}` — arbitrary file read (ALWAYS available, no flag needed)
- `\openin` / `\openout` / `\immediate\openout` — fine-grained file I/O without `\write18`
- `\directlua{...}` (LuaTeX only) — arbitrary Lua execution including `os.execute()`; CVE-2023-32668 allows arbitrary code execution in LuaTeX 0.27.0–1.16.2 even with shell-escape disabled via Lua's `os.execute` exposed by `\directlua`
- `\luatexshell` (LuaTeX) — direct shell invocation

Sources:
- [Hacking with LaTeX](https://0day.work/hacking-with-latex/) — practical attack primitives
- [LuaTeX Security Vulnerabilities](https://www.maxchernoff.ca/p/luatex-vulnerabilities) — CVE-2023-32668 (LuaTeX ≤1.16.1)
- [Can You Accept LaTeX Files from Strangers? Ten Years Later (arXiv:2102.00856)](https://arxiv.org/abs/2102.00856) — systematic evaluation of LaTeX services; concludes sandboxing is necessary because "command restrictions are more difficult to setup" and "blacklists are bad and one will find a bypass eventually"

#### Against LaTeXML specifically

**LaTeXML does NOT expose the classical pdflatex attack surface:**
- `\write18` — silently ignored (no `--shell-escape` support in LaTeXML; confirmed by E13_S03 audit + `write18_shellout.tex` fixture effectiveness caveat)
- `\input{}` — resolves as LOCAL file path only, not HTTP; network egress absent
- `\directlua` — LaTeXML is Perl-based, not LuaTeX; `\directlua` is silently ignored
- `\luatexshell` — not applicable

**The LaTeXML-specific attack surface is narrower but real:**
1. **Perl .ltxml plugin loading** — LaTeXML loads `.ltxml` binding files from its `@INC` path. If a malicious paper ships an adjacent `.ltxml` file (possible in a multi-file tarball extraction into a single dir), and that file is on LaTeXML's `@INC`, LaTeXML will `require` it and execute arbitrary Perl code. This is the highest-severity Perl-side vector.
2. **Resource exhaustion via macro expansion** — confirmed effective (fork_bomb, infinite_recursion fixtures). Mitigated by Python-level timeout.
3. **Filesystem writes via `\openout` / `\newwrite`** — LaTeXML does implement `\openout`; a hostile file could create/append to files in the CWD or any writable path. This is the filesystem-write whitelist vector.
4. **Future LaTeXML versions** — LaTeXML's Perl internals use `eval {}` blocks extensively. A future CVE in LaTeXML's package binding loader could re-open the code execution surface. No current CVE found (NVD query returned no LaTeXML-specific entries as of 2026-05).

**CVE status:** No CVE assigned directly to LaTeXML hostile-input scenarios as of the research date. The theoretical threat class is documented in arXiv:2102.00856 (Checkoway, Ten Years Later). The USENIX LOGIN 2010 paper cited in the audit doc ("Don't Take LaTeX Files from Strangers") is the original primary source.

### Sandbox layers — what each one blocks

#### macOS sandbox-exec
- **Kernel mechanism:** `sandbox-exec` calls `sandbox_init(3)` which installs a MACF (Mandatory Access Control Framework) hook. The kernel intercepts vnode operations, network calls, and IPC before they execute.
- **Blocks:** filesystem reads/writes outside the profile allowlist, ALL network (TCP/UDP/Unix sockets) via `(deny network*)`, IPC to other processes, mach port lookups
- **Does NOT block:** CPU/memory consumption (no cgroup equivalent on macOS), process forking WITHIN the profile (forked children inherit the sandbox profile)
- **Gap:** DEPRECATED since macOS 10.15+. Still functional on Darwin 25.4.0 but Apple provides no ABI stability guarantee. Profile syntax is Scheme-like; existing `infra/latexml/sandbox.sb` is correctly written.

#### Linux seccomp-bpf
- **Kernel mechanism:** `prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ...)` installs a BPF filter on every syscall. The filter runs in a zero-overhead kernel fast path per syscall.
- **Blocks:** specific syscalls (e.g. `execve`, `socket`, `connect`, `fork`, `clone` with namespace flags); the filter decides per-syscall: allow, deny with EPERM/ENOSYS, or kill process
- **Does NOT block:** filesystem access beyond `open(2)` at the syscall level alone — `open()` itself must be allowed for LaTeXML to read source; a pure seccomp filter cannot restrict *which* files are opened without also implementing argument inspection (expensive; `openat2` with RESOLVE flags helps but requires kernel ≥5.6)
- **Complementary to landlock:** seccomp blocks syscall classes; landlock restricts file paths.

#### Linux Landlock (kernel ≥5.13)
- **Kernel mechanism:** `landlock_create_ruleset()` + `landlock_add_rule()` + `landlock_restrict_self()` syscalls. A process creates a ruleset specifying allowed file access modes and directories. After `restrict_self()`, the process and all descendants can ONLY access the listed paths with the listed modes.
- **Blocks:** filesystem reads outside allowed paths, filesystem writes outside allowed paths, and (Landlock ABI v4+) network socket creation
- **Does NOT block:** CPU/memory consumption (still need cgroups/ulimit for that), syscalls by class (seccomp's domain)
- **Python implementation choice:** The `python-landlock` package (PyPI) provides ctypes bindings; alternatively, `ctypes` + raw syscall invocation via `ctypes.CDLL(None).syscall(...)`. No stable widely-deployed Python library exists as of 2026-05 — raw ctypes is the pragmatic choice.

#### Docker hardening flags
- **Mechanism:** `--read-only` mounts root filesystem read-only (kernel copy-on-write); `--security-opt no-new-privileges` sets `PR_SET_NO_NEW_PRIVS` (irreversible on exec); `--cap-drop ALL` removes all Linux capabilities from the container's bounding set; `network_mode: none` removes all network interfaces
- **Blocks:** capability escalation, setuid exploitation, root filesystem writes, all network egress
- **Does NOT block:** CPU/memory consumption (needs `--memory` / `--cpus`); filesystem writes to explicitly mounted volumes (intended write path)
- **Current state:** `infra/latexml/docker-compose.latexml.yml` already encodes all four flags correctly; `docker/Dockerfile.server` already uses UID 1000 non-root user but does NOT launch latexmlc (it serves the MCP server). The Docker hardening for LaTeXML is about the INGEST container, not the server container.

#### `sandlock` Python library (2026 discovery)
[`sandlock` on PyPI](https://pypi.org/project/sandlock/) / [multikernel/sandlock on GitHub](https://github.com/multikernel/sandlock) — combines Landlock + seccomp-bpf + seccomp user notification into a single Python library; requires Linux 6.7+, no root needed. Actively maintained as of 2026. This is an alternative to raw ctypes implementation.

---

## Failure-mode analysis

**FM-1 — Over-strict profile blocks legitimate LaTeXML (most likely failure mode)**
- **Trigger:** sandbox-exec on macOS blocks a Perl module path not enumerated in `infra/latexml/sandbox.sb`'s HOME allowlist (e.g., operator has perlbrew under `/usr/local/` not `~/perl5`). Or landlock on Linux blocks a read of a system Perl `.pm` file outside the allowed paths.
- **Symptom:** `latexmlc` exits non-zero on ALL papers, including the 50-paper seed corpus. `ParseResult.success == False` universally. The smoke test would catch this immediately.
- **Mitigation:** The production sandbox must be smoke-tested against `tools/seed-papers.txt` (50 papers) BEFORE commit. If any paper fails, widen the filesystem allow-list incrementally. The sandbox must degrade gracefully (fall back to subprocess+timeout-only, log `sandbox_layer_unavailable`) rather than hard-fail.

**FM-2 — sandbox-exec silently not applied (deprecation removal)**
- **Trigger:** A future macOS removes `sandbox-exec` binary entirely. `shutil.which("sandbox-exec")` returns None. If the graceful-degradation path doesn't log this prominently, the operator believes the sandbox is active when it's not.
- **Symptom:** No observable test failure (the containment tests pass via Python-level timeout; they don't verify sandbox-exec was invoked). The security regression is invisible.
- **Mitigation:** Log `WARNING: sandbox-exec not available on this platform; falling back to subprocess+timeout isolation only (Threat 3 partially mitigated)` at the START of each `parse_with_latexml` call when sandbox is not applied. Add a test that when `shutil.which("sandbox-exec")` is mocked to None, the warning IS emitted and the call still succeeds.

**FM-3 — Sandbox wrapper at wrong layer — latexmlc re-execs another binary**
- **Trigger:** `latexmlc` is typically a Perl wrapper script (not a compiled binary). On macOS Homebrew, `/opt/homebrew/bin/latexmlc` is a Perl script that invokes `perl /opt/homebrew/lib/perl5/site_perl/LaTeXML/scripts/latexmlc`. If sandbox-exec is applied to the wrapper script, the sandbox may not fully restrict the `perl` interpreter that `latexmlc` exec()s.
- **Symptom:** sandbox-exec allows the re-exec (since `process-exec` is permitted in the profile). The sandboxed process GROUP includes the perl process, but if `process-exec` were not permitted the sandbox would block the exec. Current profile allows `(allow process-exec)` — this is correct.
- **Mitigation:** Confirm the `.sb` profile correctly uses `(allow process-exec)` for the Perl re-exec. Verify that `start_new_session=True` on the wrapper script propagates the session to the perl interpreter. The current `infra/latexml/sandbox.sb` has `(allow process-exec)` — this is not a gap.

**FM-4 — Docker hardening conflicts with existing write path**
- **Trigger:** `docker/Dockerfile.server` launches the MCP server (not latexmlc). If E13_S03b tries to add Docker hardening flags to the SERVER container Dockerfile, this conflicts because the server needs `var/arxmcp/cache` writes. The latexml-specific Docker hardening belongs in `infra/latexml/docker-compose.latexml.yml` (already exists), not in `docker/Dockerfile.server`.
- **Symptom:** Server container can't write cache; `make up` crashes.
- **Mitigation:** Do NOT modify `docker/Dockerfile.server` for latexml sandboxing. The latexml Docker config is already documented in `infra/latexml/docker-compose.latexml.yml`. E13_S03b's Docker deliverable is: (a) note that the existing config is complete, (b) wire the flags when E14 merges the main compose — no new changes needed.

**FM-5 — Hostile fixture tests pass but don't exercise the sandbox**
- **Trigger:** `TestLatexmlSandboxContainment` skips when `latexmlc` is not on PATH (`skipif` marker). On a CI machine or developer box without LaTeXML, the containment tests are never run. A new sandbox layer added by E13_S03b can have bugs that only manifest when the sandbox is actually invoked.
- **Symptom:** Green CI but broken sandbox in production.
- **Mitigation:** Add a separate test class for sandbox-layer wiring that uses MOCKS (not live latexmlc) — verify that `_build_latexml_cmd()` prepends the correct wrapper args on the current platform. This test must run on Windows (where it should assert no wrapper is prepended) and macOS/Linux (where it asserts the platform-appropriate wrapper).

**FM-6 — Windows host: no sandbox layer available; tests fail or skip incorrectly**
- **Trigger:** sandbox-exec, seccomp, and landlock are all POSIX-only. On Windows (the dev host per `CLAUDE.md`), `shutil.which("sandbox-exec")` returns None, and ctypes landlock calls fail. If the implementation doesn't degrade gracefully, `parse_with_latexml` raises on Windows.
- **Symptom:** Windows CI (the local dev machine) fails `make test`.
- **Mitigation:** The sandbox-layer selection MUST be wrapped in `sys.platform == "darwin"` / `sys.platform.startswith("linux")` guards. On `win32`, skip sandbox wiring entirely — the degraded path (subprocess + timeout) is the only option. All sandbox-layer unit tests that check wiring must `pytest.mark.skipif(sys.platform == "win32", ...)`.

**FM-7 — Cross-platform argv divergence breaks `TestProcessGroupKill` AST guard**
- **Trigger:** The `TestProcessGroupKill::test_parse_with_latexml_uses_process_group_kill` test does AST-level inspection of `parse_with_latexml` for `start_new_session=True` and `killpg`. If the refactor introduces platform-conditional paths (macOS path wraps cmd, Linux path does something different), the AST check needs to be updated — it currently walks the ENTIRE function body and finds these tokens.
- **Symptom:** The AST test still passes (it finds the tokens somewhere in the function), but the killpg is in a branch that is never taken on some platforms. False-positive regression guard.
- **Mitigation:** The E13_S03b refactor must NOT move the `start_new_session=True` and `killpg` calls into a platform-specific branch. They must remain on the MAIN code path (inside `Popen` and the `TimeoutExpired` handler). Only the `cmd` construction should be platform-conditional.

---

## Recommendation

**Wire `sandbox-exec` on macOS and `landlock + seccomp` on Linux directly into `parse_with_latexml` by prepending wrapper args to the `cmd` list.** Specifically:

1. **macOS:** Prepend `["sandbox-exec", "-f", str(SANDBOX_PROFILE), "-D", f"SOURCE_DIR={cwd}", "-D", f"OUTPUT_DIR={out_dir}", "-D", f"HOME={Path.home()}", "-D", f"TMPDIR_SUBDIR=/tmp/arxmcp-latexml-{paper_id}"]` before `"latexmlc"`. Use `shutil.which("sandbox-exec")` to detect availability. Fall through to unsandboxed path if absent, with a WARNING log.

2. **Linux (host, non-Docker):** Use `bubblewrap` (`bwrap`) rather than raw seccomp+landlock ctypes, because: (a) bwrap is already available on any modern Linux with Flatpak; (b) it combines filesystem namespace + seccomp in one well-tested tool; (c) no Perl-level ctypes injection needed; (d) bwrap is NOT setuid root (unlike Firejail, which has past CVEs). The `bwrap` argv: `["bwrap", "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib", "--ro-bind", str(main_tex.parent), str(main_tex.parent), "--bind", str(out_dir), str(out_dir), "--tmpfs", "/tmp", "--unshare-net", "--unshare-pid", "--new-session", "--", "latexmlc", ...]`. Fall through to subprocess+timeout if `bwrap` not on PATH.

3. **Docker (production ingest container):** No code changes — `infra/latexml/docker-compose.latexml.yml` already encodes all required flags. Update the audit doc to mark this as "complete via static documentation + test"; mark "wired to actual invocation" as an E14 deliverable when the compose is merged.

**Justification:** sandbox-exec + bwrap gives real kernel-level isolation (filesystem namespace on Linux via bwrap user namespace, MACF restriction on macOS) without adding Python ctypes complexity for seccomp/landlock syscall interface. The existing `infra/latexml/sandbox.sb` is already validated by static tests. bwrap is the production tool used by Flatpak — it is stable and well-audited. The alternative (raw landlock + seccomp via `sandlock` / ctypes) requires Linux 6.7+ which is not guaranteed on older Ubuntu LTS.

**Banned-patterns check:** No `assert` for invariants (use `if … raise RuntimeError`), no `BaseHTTPMiddleware`, no `anthropic` SDK, no tool-schema changes (so no `EXPECTED_TOOL_SCHEMA_SHA256` re-pin needed — `parse_with_latexml` is not an MCP tool).

---

## Open questions

1. **Is `bwrap` available on the production Linux target?** The prod machine is unspecified in CLAUDE.md. `bwrap` is installed by default on most modern Ubuntu/Fedora systems (comes with `flatpak` or `bubblewrap` package). The implementation must degrade gracefully if absent — but the implementer should verify against their target Linux distro before committing.

2. **Does the macOS sandbox-exec profile need a `TMPDIR_SUBDIR` parameter to exist before invocation?** The profile at `infra/latexml/sandbox.sb` references `(param "TMPDIR_SUBDIR")` — the caller must `mkdir` this path before invoking `sandbox-exec`. The implementer must create this dir (e.g., `Path(f"/tmp/arxmcp-latexml-{paper_id}").mkdir(exist_ok=True)`) before prepending sandbox-exec args.

3. **Should graceful degradation be silent or noisy?** The milestone brief says "log + continue." The severity of the log matters: DEBUG (invisible in default ops) vs. WARNING (visible). Given this is a security layer, WARNING on first invocation + a one-time startup log is appropriate. The implementer should decide on a per-session-vs-per-invocation logging cadence.

---

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| `gh issue close` | `chris-dare-dev/arXMCP#3` | Milestone brief requires closing this issue once implementation lands |

All other deliverables are local (code changes to `tools/arxiv_fetch.py`, test additions to `tests/security/test_latexml_sandbox.py`, doc updates to `.claude/docs/security-threat-3-audit.md` and `.claude/docs/security-threat-model-coverage.md`). Phase 4 main-thread gates the `gh issue close`.

---

## Sources

- [Hacking with LaTeX | 0day.work](https://0day.work/hacking-with-latex/) — attack primitives, \write18, \input, \openin/\openout
- [Can You Accept LaTeX Files from Strangers? Ten Years Later (arXiv:2102.00856)](https://arxiv.org/abs/2102.00856) — systematic LaTeX services security evaluation
- [LuaTeX Security Vulnerabilities (maxchernoff.ca)](https://www.maxchernoff.ca/p/luatex-vulnerabilities) — CVE-2023-32668, \directlua shell execution in LuaTeX (not applicable to LaTeXML but documents the threat class)
- [multikernel/sandlock on GitHub](https://github.com/multikernel/sandlock) — Landlock+seccomp Python library for Linux 6.7+
- [containers/bubblewrap on GitHub](https://github.com/containers/bubblewrap) — bwrap, the recommended Linux sandboxing tool for subprocess isolation
- [Landlock: overview 2024-01-22 (landlock.io)](https://landlock.io/talks/2024-01-22_landlock-overview.pdf) — Landlock kernel mechanism detail
