---
milestone_id: "verification-contract-spike-1"
researcher_role: "explore"
injection_attempts: 0
---

# Research brief (explore) — verification-contract-spike-1

## Affected files / context

### 0. Framing: this is the first Windows-native sandbox attempt in the repo

Every subprocess sandbox this repo has shipped so far is POSIX-only in its
resource-cap mechanism and its kill discipline. Concretely, on this exact
Windows workstation, **zero working subprocess containment exists today**
for any of the four candidate "peer" sandboxes:

| Sandbox | Windows resource cap | Windows kill discipline |
|---|---|---|
| LaTeXML (Threat 3, E13_S03) | none — `scale-ops-hardening-m12` ("WSL2/bwrap half-step for the currently-unsandboxed Windows LaTeXML path") is still `lane: next`, unshipped | n/a |
| MinerU/PDF (`security-pdf-sandbox.md`) | RLIMIT_AS is Linux-only (`ingest/textbook_parser.py:107,152`) | `os.killpg` — POSIX-only, confirmed absent on Windows (below) |
| CDM/pdflatex (`security-cdm-sandbox.md`) | none documented for Windows at all | same `os.killpg` helper |
| Lean REPL (`server/lean_repl.py`) | RLIMIT_AS explicitly skipped on `win32` (`server/lean_repl.py:209-228`) | none — 30 s per-query wall-clock is the *only* backstop |

The container/WSL2 route's closest in-repo analog,
`infra/latexml/docker-compose.latexml.yml`, is self-described as **"a
DOCUMENTATION ARTIFACT... NOT the main docker-compose.yml"** (lines 1-13) for
a *different* subprocess, and the image it names (`arxmcp/latexml:0.8.8`) has
no Dockerfile anywhere in the repo. The sibling milestone that would be the
closest "container sandbox actually built on this Windows host" precedent,
`scale-ops-hardening-m10` ("MinerU/uploaded-PDF parsing contained in a
no-egress sandbox", `plans/scale-ops-hardening/roadmap.yaml:721-741`,
targeted `2026-07-09 -> 2026-07-17`), has **no shipped artifact** — no
`state.json`, no notes dir, no container/no-egress code found anywhere in the
tree (grepped). So both candidate routes start this spike from *zero proven
running code on this host*, not one route vs. an established baseline.

### 1. `server/lean_repl.py` — spawn / query / close, and exactly what is and isn't bounded on Windows today

- Module docstring names this spike's design doc directly:
  `server/lean_repl.py:20-21` — "`.claude/docs/lean-sandbox-design.md` — the
  sandbox sub-design (per-query timeout, filesystem isolation, stderr
  discipline)."
- **Platform-conditional `resource` import.** `server/lean_repl.py:49-52` —
  `try: import resource as _resource / except ImportError: _resource = None`
  (POSIX-only module; on win32 this is always `None`).
- **`spawn()`'s `rlimit_as_bytes` gate — the exact code that leaves Windows
  uncapped.** `server/lean_repl.py:208-228`:
  ```
  if (rlimit_as_bytes and rlimit_as_bytes > 0
      and sys.platform != "win32" and _resource is not None):
      ...spawn_kwargs["preexec_fn"] = _apply_rlimit_as
  elif rlimit_as_bytes and sys.platform == "win32":
      logger.warning("LeanRepl: RLIMIT_AS (%d bytes) requested but Windows has "
                      "no equivalent; the 30 s per-query timeout is the only "
                      "memory backstop. See .claude/docs/lean-sandbox-design.md.", ...)
  ```
  **Adjacent, already-known bug in this same block** (its own comment,
  `server/lean_repl.py:201-207`): the `!= "win32"` gate is "too loose" and
  **already broken on macOS** (`setrlimit` raises `ValueError` between
  `fork()` and `exec()`, per CLAUDE.md §8 #9) — tracked as
  `github.com/chris-dare-dev/arXMCP/issues/7`, still open. If this spike or
  `m2` edits this same conditional to add a Windows Job Object branch, it is
  editing the exact block with the known-open Darwin bug next to it —
  flagged as a risk below, not something to silently fix or silently
  perpetuate.
- **What IS bounded on Windows today:** per-`query()` wall-clock timeout
  (`DEFAULT_QUERY_TIMEOUT_S = 30.0`, `server/lean_repl.py:64`, enforced via
  `asyncio.wait_for` at `server/lean_repl.py:349-361`); `stderr=DEVNULL`
  (`server/lean_repl.py:242`, removes the pipe-buffer deadlock vector, not a
  security control); single-flight I/O via `self._io_lock`
  (`server/lean_repl.py:140,343`); subprocess `cwd` set to the built
  `leanprover-community/repl` package dir, not the arXMCP repo or
  `var/arxmcp/` (`server/lean_repl.py:235`); mandatory reaping on `close()`
  (`terminate()` → bounded `wait()` → `kill()` → bounded `wait()`, both
  `_CLOSE_GRACE_S=5.0`-capped, `server/lean_repl.py:430-474`); **kill+respawn
  on a query timeout is implemented** in the handler, not just documented —
  `server/handlers/lean_verify.py::_respawn_after_timeout` (line 1053),
  called from both the primary query-timeout path (line 1414) and the
  axiom-audit round-trip timeout path (line 1148).
- **What is NOT bounded on Windows today:** address-space/memory (RLIMIT_AS
  skipped outright, above); CPU; **process count — nothing prevents Lean or
  any child it spawns from spawning arbitrarily many processes; there is no
  Job Object of any kind yet**; filesystem writes beyond the `cwd` default
  (no restricted token, no read-only mount — an absolute-path write from
  inside Lean is not blocked, only relative-path resolution is narrowed by
  `cwd`); network (the design doc's "No network" guard is "by construction"
  — Lean doesn't normally open sockets — not an enforced deny, see §2).

### 2. Prior sandbox design + prior art in-repo (read in full)

**`.claude/docs/lean-sandbox-design.md`** (full file read). Guards table
(`:22-34`): Per-query timeout = **Implemented**; stderr isolation =
**Implemented**; single-flight I/O = **Implemented**; process reaping =
**Implemented**; filesystem isolation = **Partial** (cwd done; per-call
temp-dir redirection is "m3+", still unimplemented for Lean); **Memory cap =
"Deferred — documented, not implemented,"** explicitly naming the Windows
mechanism this spike must validate: `"on Windows it requires a Job Object
(CREATE_BREAKAWAY_FROM_JOB + SetInformationJobObject)"` (line 31); No network
= **"By construction"** (not enforced); System dependency gating =
**Implemented** (`ARXMCP_ENABLE_LEAN` default off). The doc's own
"Environment-snapshot accumulation (F7)" section (`:52-128`) is an
unbounded-memory-growth finding from *legitimate* env reuse (not an attack),
explicitly owned by a **different** future milestone (R3 m7) — orthogonal to
this spike, but worth knowing it exists so it isn't conflated with the
adversarial memory-bomb case this spike measures.

**`.claude/docs/security-pdf-sandbox.md`** (full file read). Three
deliberately-stacked layers (`:66-81`): pre-flight byte-level gate → subprocess
sandbox (RLIMIT_AS Linux-only, process-group kill, no inherited env,
cwd-confined tmpdir) → per-notebook blast-radius containment. **Load-bearing
transferable finding — MinerU 3.x's grandchild FastAPI server survives
`os.killpg`** (`:202-213`, `:354-363`): MinerU's internal `LocalAPIServer`
spawns with its own `start_new_session=True`, landing in a *different*
process group than the one the outer CLI's pgid reaps. This is exactly the
"process escape despite believing you killed the tree" failure class this
spike's fork-bomb/process-spawn cases must probe for on Windows — a Job
Object closes this specific class atomically (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`
terminates every process ever added to the job, however deep), whereas a
naive `TerminateProcess`-only approach reproduces the exact MinerU gap. The
doc's own **"Outstanding follow-up (out of m5 scope)"** section
(`:498-505`) already names `server/lean_repl.py`'s `!= "win32"` gate as a
likely-latent bug and explicitly defers its audit — i.e. this exact platform
question was flagged in-repo before this spike existed. Also transferable:
`_scrub_subprocess_env` (`:132-146`) — an explicit environment allowlist
(`PATH, HOME, LANG, LC_ALL` + a forced `TMPDIR` override) rather than
inheriting the parent's full env; the Windows analog is in `ingest/textbook_parser.py`
(§3 below).

**`.claude/docs/security-cdm-sandbox.md`** (full file read). Peer-tier
threat model to LaTeXML. Load-bearing detail: `--no-shell-escape` (argv) does
**not** cover `\openout` — that needs the separate `openout_any=p` kpathsea
env var (`:23`); `TMPDIR` cwd-binding alone does **not** stop `\input{/etc/passwd}`
— that needs `openin_any=p` (`:24`). General lesson for this spike: a single
plausible-sounding flag/setting is routinely insufficient; each distinct
attack vector (shell-escape vs read vs write) needs its own, separately
verified mitigation — don't assume one Job Object limit flag covers multiple
resource-case categories without checking each one.

**Kill-discipline portability — the load-bearing negative finding (live-verified
on this box's own `.venv`, not assumed):**

```
has killpg:      False   has getpgid:  False   has SIGKILL: False   has fork: False
has kill:        True
has CREATE_NEW_PROCESS_GROUP:    True
has CREATE_BREAKAWAY_FROM_JOB:   True
pywin32 (win32job/win32api/win32process/win32security/win32con): OK
  win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: True
  win32job.JobObjectExtendedLimitInformation:  True
```

All three POSIX peer sandboxes (`tools/cdm_eval.py::_run_subprocess_with_pgkill:373-378`,
`tools/arxiv_fetch.py::parse_with_latexml`, `ingest/textbook_parser.py`)
share the identical kill idiom: `os.killpg(os.getpgid(proc.pid), signal.SIGKILL)`
inside `with contextlib.suppress(ProcessLookupError, OSError):`. On Windows,
`os.killpg`/`os.getpgid`/`signal.SIGKILL` **do not exist as module
attributes** — the call would raise `AttributeError`, which is **not** a
subclass of `OSError` and therefore **not suppressed** by the existing
`contextlib.suppress(ProcessLookupError, OSError)` guard. Copying this helper
verbatim for a Windows probe would crash the exception handler itself and
leave the runaway subprocess unreaped. `os.fork` is also absent (`False`) —
a literal POSIX-style "fork bomb" cannot be authored the same way on
Windows; the analog is a rapid `CreateProcess`/`subprocess.Popen` spawn loop
(classic `.bat` `:s & start %0 & goto s` shape), not `os.fork()` in a loop.
`pywin32`'s `win32job` module is confirmed live-importable with the exact
two constants a Job Object memory/process/kill-on-close policy needs.

**pywin32 dependency status — confirmed transitive, not declared.**
`pyproject.toml` (full file read, `:105-314`) has **no** `pywin32` entry.
`uv.lock:885-902` shows it is pulled in solely as `mcp==1.27.1`'s own
Windows-conditional dependency: `{ name = "pywin32", marker = "sys_platform
== 'win32'" }`. Safe for this spike's exploratory measurement (it genuinely
resolves and imports), but a real fragility for `m2` if Job Object wins: a
future `mcp` release dropping its own `pywin32` pin would silently remove it
from arXMCP's env with no direct-dependency guard noticing. `m2` should add
it as an explicit `pywin32>=311; sys_platform == "win32"` direct dependency
rather than continue riding the transitive pull.

### 3. The macOS/Darwin RLIMIT_AS precedent — `ingest/textbook_parser.py`

`ingest/textbook_parser.py:18-19` cross-references `server/lean_repl.py::spawn`
by name as the RLIMIT_AS precedent, **and already flags it**: `"(also has
the macOS gap this driver explicitly addresses)"` — i.e. this module's own
header comment independently corroborates the §1 finding above. The
platform-gating pattern to mirror: `_RLIMIT_AS_PLATFORM: str = "linux"`
(`:107`); `if sys.platform == _RLIMIT_AS_PLATFORM: ... else: _set_mineru_rlimits
= None; logger.warning(...)` (`:152-173`) — gates on `== "linux"` (an
allowlist), not `!= "win32"` (a denylist that silently also passes Darwin).
**This is the exact fix shape `server/lean_repl.py`'s known-open issue #7
needs**, already applied correctly one file over.

Separately, a genuinely useful **Windows-specific** pattern already shipped
in this same file, directly relevant to spike-1's "writable per-call scratch
only" requirement: `ingest/textbook_parser.py:285-291` overrides `TEMP` and
`TMP` (not just `TMPDIR`) on `sys.platform == "win32"`, because native
Windows libraries read `TEMP`/`TMP`, not the POSIX-convention `TMPDIR`. Any
Windows scratch-isolation contract in this spike's harness needs the same
double env-var override, not just a `TMPDIR` copy-paste.

### 4. The five-operations ADR's isolation requirements (verbatim measurement targets) + house ADR format

`.claude/docs/adr-verification-contract-five-operations.md` (full file
read) states, for each of the five future Lean operations, its isolation
dependency on **this spike's epic (e2)** — these are the concrete properties
both routes must be measured against, not just the epic summary's five-item
list:

- **`parse_source`** (`:73-77`): depends on e2 as defense-in-depth *even
  though* it loads no environment — "custom notations/macros can pull parser
  extensions into scope."
- **`elaborate_signature`** (`:101-104`): "performs a real `{"cmd": ...}`
  elaboration round-trip against the REPL... needs the same process-isolation
  boundary as every other Lean-executing operation."
- **`check_declaration`** (`:114-117`): "a per-request, sandboxed-process
  elaboration."
- **`audit_axioms`** (`:137-139`): explicitly runs **inside the same
  isolated environment** as the preceding op — a second round-trip, **not**
  a fresh process. (Relevant to the spike: whichever route wins must support
  a warm/reused environment, not force a fresh sandbox per query.)
- **`strict_replay_proof`** (`:170-175`): the one operation that needs a
  **separate, freshly-spawned isolated process** every time, never reusing a
  warm token — "structural, not incidental."
- Decision 6 (`:209-221`): checker identity is **not** a sixth operation —
  served by a manifest resource instead, no isolation implication for this
  spike.
- **Explicit hand-off to this spike, named by id** (`:237-239`):
  *"Deliberately NOT decided here: Which Windows isolation route (Job
  Object + restricted token vs container/WSL2) —
  `verification-contract-spike-1`/m2's ADR, not this one."* Confirms this
  spike's ADR is the one and only place this decision is authoritative.
- **Owner-approval convention to replicate** (`:259-268`): this ADR ships
  `Status: Proposed` with an explicit **"Owner approval record: Pending"**
  section, stating plainly that asserting `Accepted` without an owner
  round-trip "would claim an approval that did not happen." `adr-data-plane-boundary.md:1-4`
  is the `Accepted` counter-example (header: `Status / Date / Owner /
  Roadmap item / Source brief`, same four-line block). This spike's ADR
  should default to `Proposed`/`Pending` unless an explicit owner
  confirmation actually happens, matching the five-operations precedent
  rather than the Accepted one.

### 5. Where the spike's artifacts belong

**The ADR → `.claude/docs/`** (CLAUDE.md §1/§4.6). Naming precedent is
topic-suffixed, not milestone-id-suffixed (`adr-verification-contract-five-operations.md`
for `m1`'s topic, not `adr-verification-contract-m1.md`) — because the ADR
serves **both** this spike and `m2` (the epic-level decision-of-record), a
topic name fits better: **`adr-verification-contract-windows-isolation.md`**
is the natural next name in the same family.

**Probe scripts / raw measurement output — two prior conventions exist, and
they diverge:**
- `.claude/notes/spikes/verification-feedback-spike-2.md` (the *sibling*
  Lean spike, same naming family) kept its throwaway POC **entirely outside
  the repo** (`~/lean-repl-spike/validate_repl.py`, `spike-note.md:31-34`) —
  only the prose write-up was committed, no code, no state.json (this was a
  lighter, non-pipeline spike).
- `.claude/notes/milestones/source-truth-spike-1/` and `source-truth-spike-2/`
  (also non-pipeline — flat dirs, **no** `state.json`) instead **committed**
  throwaway scripts and raw output directly: `crosscheck_script.py`,
  `extractor_script.py`, `extraction_results.json`, `raw_atom.xml`,
  `raw_oai.xml`, alongside each `spike-note.md` (verified via `git log`,
  commit `38b78cd`).

**This milestone is procedurally different from both precedents**: it has a
real `state.json` (`phase: research-running`) and on-disk
`research/critique/implement/rectify/` subdirs already created by the
orchestrator before this research dispatch — i.e. it is running through the
**full** 4-phase pipeline, which neither prior "spike" precedent did. The
directly-analogous, already-existing structure is therefore the right home:
probe scripts / measured-output tables belong under
`.claude/notes/milestones/verification-contract-spike-1/implement/` (this
milestone's own phase dir), not forced into either older convention.

**Wheel-packaging risk if placed under `tools/` instead — concrete, not
theoretical.** `tests/test_wheel_packaging.py` (full file read) derives its
check from `pyproject.toml:42`'s `[tool.setuptools.packages.find].include =
["server*", "ingest*", "tools*", "shim*", "ops*"]`. The pyproject's own
comment (`:26-29`) confirms subdirectories are swept in as **implicit
namespace packages** even with no `__init__.py` (`namespaces` defaults to
`true`) — so a new `tools/verification_contract_spike/` directory would
ship in the built wheel and the Docker image by default. `.py`-only files
would not trip `test_wheel_packaging.py`'s data-file glob check (`path.suffix
in (".py", ".pyc", ".pyo"): continue`, confirmed at that file's `_iter_data_files`),
but that is a **packaging-test pass, not a safety judgment** — shipping
spike-only, possibly-dangerous resource-bomb test code inside a production
wheel/container image is a bad outcome the test alone won't catch. `.claude/`
and `plans/` are **not** in the `include` list at all, so nothing placed
there needs a `package-data` glob and cannot ship in the wheel — reinforces
`.claude/notes/milestones/<ID>/implement/` as the safe choice. `tests/` is
also outside the shipped trees (only named via `testpaths` in
`pyproject.toml:359`), so a pytest-shaped probe under `tests/` is likewise
wheel-safe — relevant to §6 below if the orchestrator wants the probes
reusable as regression tests rather than one-off scripts.

### 6. Test-marker precedent for opt-in / environment-dependent tests

`pyproject.toml:361-371` (full markers list, all 9 read) registers markers
as **strings** in `[tool.pytest.ini_options].markers`; `tests/conftest.py:75-120`
(full function read) separately deselects them via `_OPT_IN_MARKERS: frozenset[str]`
+ a `pytest_collection_modifyitems` hook. **Both places must be updated
together** — issue #206 (CLAUDE.md §4.5) is the exact precedent for what
happens when only one is touched: `requires_latexmlc` was registered in
`pyproject.toml` alone for a long time, so nothing actually skipped it by
default, and a fresh clone with no LaTeXML hard-failed its first `make test`.
`requires_lean_repl` (`pyproject.toml:366`) is the closest existing analog —
opt-in via **both** `ARXMCP_LAKE_PATH` and `ARXMCP_LEAN_REPL_DIR` env vars,
already in `tests/conftest.py:75-86`'s frozenset. None of the 9 existing
markers gate on a **running daemon** (Docker) — they all gate on an
installed **binary** (`shutil.which`) or an **env var**. If this spike (or
`m2`) wants a `requires_docker`-shaped marker for the container/WSL2 route,
that would be a new probe *kind* (e.g. `docker info` exit code), not a
copy-paste of an existing one.

### Estimated diff size / novel architecture

This is a measurement + decision-record spike; per its own acceptance
criteria (`plans/verification-contract/roadmap.yaml:192-196`) it does **not**
land the boundary itself (that's `m2`, `roadmap.yaml:198-212`). Expected
footprint:

- `.claude/docs/adr-verification-contract-windows-isolation.md` — new, ~250–450
  lines (peer precedent: `adr-verification-contract-five-operations.md` is
  269 lines; this one additionally needs a per-route × per-resource-case
  results table).
- `.claude/notes/milestones/verification-contract-spike-1/implement/` —
  0–9 small probe scripts/harnesses (spawn-loop/process-count probe, memory
  probe, heartbeat/hang probe, filesystem-escape probe, network-escape
  probe, a Job Object harness, a throwaway Dockerfile/compose for the
  container route since none exists yet) if the orchestrator elects to
  commit them (§5) — each ~40–150 LOC, plausibly 400–900 LOC total across
  5–9 files. **Zero of this is required to ship** if probes are instead run
  ephemerally outside the repo, mirroring `verification-feedback-spike-2`'s
  convention.
- **Zero expected changes to `server/`, `ingest/`, `tests/`, `pyproject.toml`**
  under the measurement-only reading of this milestone's acceptance
  criteria — `m2` is where `server/lean_repl.py` itself changes
  (`roadmap.yaml:211`, `.claude/docs/lean-sandbox-design.md` is `m2`'s
  named target doc).

**Novel architecture:** yes, in a specific and narrow sense — this is the
**first attempt at any Windows-native process-containment mechanism** in the
codebase's history (§0); every existing sandbox precedent is POSIX-only and
none of its kill/cap mechanisms port. The container/WSL2 route is "novel
implementation of an already-well-established repo *pattern*" (3 shipped
peer sandboxes share the network-none / read-only / per-call-scratch /
resource-cap / kill-on-violation shape); the Job Object route is a wholly
new mechanism *class* for this repo (no `win32job`/Job Object code exists
anywhere today, confirmed by the grep in §2). Given the small, mostly-prose
expected diff and the genuinely exploratory/measurement nature of the work,
this reads as well-suited to an interactive/inline session rather than a
single-shot delegated implementation pass — but that call is the
orchestrator's, not this brief's.

### Safety note (explicit ask from the dispatch brief)

**No existing sandbox in this repo has ever contained a fork/memory bomb on
Windows** — the closest precedent (LaTeXML Threat 3) is POSIX-only in
practice and its own doc admits the Windows path is currently unsandboxed
(§0). This spike is not "apply a proven technique to a new platform"; it is
"prove the technique for the first time, on the user's actual daily-driver
workstation." Concrete, source-grounded blast-radius considerations:

1. **The POSIX kill helper cannot be trusted to fail safely on Windows if
   copied as-is** (§2) — it would raise an uncaught `AttributeError` instead
   of killing the runaway tree, which is *worse* than doing nothing, since
   it looks like an implemented safeguard until the exact moment it's
   needed.
2. **A Job Object test's failure mode runs directly on the host** with no
   independent outer boundary — unlike the container/WSL2 route, where
   Docker Desktop's WSL2 utility VM has its own memory ceiling (configurable
   via `.wslconfig`, not inspected during this research — worth checking
   before running the container-route memory-bomb case) that acts as a
   backstop *independent of* whatever in-container cap the spike is
   validating. Measuring the container route's resource-bomb cases before
   the Job Object route's gets a free outer safety margin the Job Object
   route structurally cannot have.
3. **Host has ~31.8 GB total physical RAM** (live `systeminfo` probe, this
   session). Any memory-bomb probe's *own* allocation loop should carry a
   hard ceiling well below that, independent of whether the mechanism under
   test catches it — the same "independent, outer watchdog" principle
   `tools/cdm_eval.py`'s 30 s `subprocess.communicate(timeout=...)` already
   applies for wall-clock (the Python-side timeout fires regardless of
   what's happening inside the child), just extended to memory.
4. **This workstation runs multiple concurrent agent sessions against the
   same `main`** (CLAUDE.md's 2026-08-01 concurrency note) — a host crash or
   hang mid-probe has blast radius beyond this one spike/session; save/commit
   other in-flight work before running any resource-bomb probe.
5. **Windows has no `os.fork()`** (live-verified, `hasattr(os, 'fork') ==
   False`) — the "fork bomb" resource case needs a Windows-shaped
   equivalent (a `CreateProcess`/`subprocess.Popen` spawn loop), not a
   literal port of a POSIX fork-bomb script; anyone designing the probe
   should not assume `os.fork()` exists.

## Acceptance criteria the implementer must meet

1. Both routes (Job Object+restricted token; container/WSL2) are measured
   against the **same** resource-case set — heartbeat/memory/fork bombs,
   filesystem escape, network escape — within the 3-day timebox, with
   pass/fail **and** overhead recorded per route in the ADR
   (`plans/verification-contract/roadmap.yaml:193`).
2. Each route's measurement is evaluated against e2's five named isolation
   properties — no network, read-only toolchain/env, writable per-call
   scratch only, CPU/memory/process/file-size caps, kill-and-teardown on
   violation — since these are what `m2` must land regardless of which
   route wins (`roadmap.yaml:69`, `:208-209`).
3. The decision is recorded as a committed ADR under `.claude/docs/`
   (CLAUDE.md §1/§4.6), not left only as prose inside the milestone's own
   notes tree — recommended filename
   `adr-verification-contract-windows-isolation.md` (§4/§5 above).
4. If neither route clears the bar in the timebox, the ADR states that
   explicitly, that `ARXMCP_ENABLE_LEAN` stays default-off, and that R5
   targets are checked via a documented manual operator fallback — and (a
   research finding, not a decision) **no such fallback procedure exists
   anywhere in the repo today** (grepped for "manual operator fallback" /
   "R5 target"; only the roadmap prose itself uses these phrases), so
   triggering this branch leaves that doc still to be authored
   (`roadmap.yaml:194`).
5. Any fork/memory/heartbeat-bomb probe actually executed against this live
   Windows workstation carries a stated, independent blast-radius bound
   (outer wall-clock/allocation ceiling that fires regardless of the
   mechanism under test) — a safety precondition the dispatching brief
   itself requires, not an optional nice-to-have (see Safety note above).
6. The ADR's `Status`/`Owner approval record` follows the two existing
   precedents' honesty convention — `Proposed`/`Pending` unless an actual
   owner round-trip happened, matching
   `adr-verification-contract-five-operations.md:259-268` rather than
   asserting `Accepted` without one.
7. If Job Object is the winning or a credible fallback route, the ADR
   records `pywin32`'s current transitive-only dependency status
   (`uv.lock:885-902`) and that `m2` will need it promoted to an explicit,
   `sys_platform`-scoped direct dependency to ship the route safely.

## Risks and open questions

1. Both routes start from **zero proven, running containment code on this
   exact host** — the container route's only in-repo analog is an admittedly
   unbuilt "documentation artifact" for a different subprocess, and the
   sibling MinerU no-egress-container milestone that would have proven the
   Docker/WSL2 path on this machine (`scale-ops-hardening-m10`) has no
   shipped artifact despite its target window having already elapsed. This
   is a fair fight between two unknowns, not a known-good vs. a novelty.
2. The shared POSIX kill idiom all three existing peer sandboxes use
   (`os.killpg`+`SIGKILL`) is confirmed non-portable and **fails uncaught,
   not silently** — a probe harness that copies it for the Windows side
   would look implemented while actually leaving runaway processes unreaped
   the first time a timeout fires.
3. `server/lean_repl.py`'s existing `preexec_fn` platform gate has a known,
   currently-open, unrelated bug on macOS (issue #7) sitting in the exact
   conditional block a Windows branch would be added next to — worth a
   deliberate decision (fix it, or explicitly leave it and say so) rather
   than an accidental side effect of this spike's or `m2`'s edit.
4. AC2's "documented manual operator fallback" for checking R5 targets does
   not exist anywhere in the repo yet — if the spike's negative branch
   triggers, authoring that fallback is undocumented extra scope not
   currently budgeted inside the stated 3-day timebox.
5. `pywin32` is only a transitive dependency today (via `mcp`'s
   `sys_platform == 'win32'` pin) — safe for this spike's own exploratory
   measurement, but not a foundation `m2` should keep building on silently;
   an unrelated future `mcp` bump could drop it with no direct-dependency
   guard noticing.
