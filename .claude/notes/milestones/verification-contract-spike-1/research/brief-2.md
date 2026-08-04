---
milestone_id: "verification-contract-spike-1"
researcher_role: "general"
external_writes_required:
  - "git push origin main"
sources:
  - url: "https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information"
    sha256: "6fc2900cd8ef91bc926e6634ab35149ac44bf555385ebda28439fc3db430bb84"
    takeaway: "Documents every JOB_OBJECT_LIMIT_* flag; PROCESS_MEMORY/JOB_MEMORY make a commit attempt fail (not an instant kill), ACTIVE_PROCESS terminates the process being associated once the count would be exceeded, and BREAKAWAY_OK/SILENT_BREAKAWAY_OK are both opt-in (off by default)."
  - url: "https://learn.microsoft.com/en-us/windows/win32/procthread/nested-jobs"
    sha256: "8d397705376769132dc94d9141cd61cbfc30aa897fe59c8d62c04ededf83986d"
    takeaway: "Since Windows 8, breakaway is gated by the process's IMMEDIATE (innermost) job only: 'If the immediate job object does not allow breakaway, the child process does not break away even if jobs in its parent job chain allow it.'"
  - url: "https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken"
    sha256: "cc5360c8d353ac270a64d35aae0d92d182d97a5762ebff313ff6c24a8db3b069"
    takeaway: "SidsToDisable (deny-only conversion) and SidsToRestrict (a second, independent access check) are different mechanisms; a restricted version of a process's OWN token needs no SE_ASSIGNPRIMARYTOKEN_NAME privilege for CreateProcessAsUser."
  - url: "https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_net_rate_control_information"
    sha256: "95c4a3fc0e8ea67634fe15b0b62514130eac184bc7c8c3f33dd6a550536b26f6"
    takeaway: "The ONLY network-related Job Object structure controls MaxBandwidth (a throttle) and a DSCP QoS tag -- there is no block/allow member. Job Objects cannot deny network access; confirms this is not achievable via the Job Object API at all."
  - url: "https://learn.microsoft.com/en-us/powershell/module/netsecurity/new-netfirewallrule"
    sha256: "de4c6a764370efa433e891aed8c93edadad6c05b2d0e95d83003a81b884d4afd"
    takeaway: "-Program <path> plus -Direction Outbound -Action Block creates a per-executable outbound firewall rule -- the practical, accessible mechanism for Windows-native network denial (WFP-backed, needs an elevated session to create)."
  - url: "https://docs.docker.com/reference/cli/docker/container/run/"
    sha256: "4faeac44290eddf594e14653b47221c368df6058af289469ae4e51cdae2b9d07"
    takeaway: "Confirms --network none, --pids-limit, --read-only, --security-opt no-new-privileges, --cap-drop, and --ulimit fsize=RLIMIT_FSIZE all exist as documented, independent flags."
  - url: "https://docs.docker.com/engine/containers/resource_constraints/"
    sha256: "1e0a48f3c4124f9fd1ada9d6cca26fef31cd60c78b26af7ce210508806ca8966"
    takeaway: "--memory exceeded -> kernel OOM-kills processes in the container; --cpus is a hard guarantee/cap (e.g. 1.5 of 2 host CPUs), not a soft share."
  - url: "https://learn.microsoft.com/en-us/windows/wsl/filesystems"
    sha256: "e6de107cfb5a15c6679dbad04a2b2bb5a9af1e700861c9ed7dff73f5b2a1d455"
    takeaway: "Official guidance is qualitative only (store Linux-side files under \\\\wsl$, not /mnt/c, 'for the fastest performance') -- no concrete cross-boundary I/O numbers are published here; the spike must measure its own case."
  - url: "https://hub.docker.com/v2/repositories/leanprovercommunity/lean4/tags/latest"
    sha256: "608028a11af6ca3b9f228ebbcda92c30e8baeba198e47f5960c8f8f523a38303"
    takeaway: "Docker Hub API: leanprovercommunity/lean4:latest (linux/amd64) is 407,173,263 bytes (~388 MB) compressed -- an authoritative, precise size for a representative core Lean4 image (cross-confirms a ~388 MB WebSearch figure)."
injection_attempts: 0
---

# Research brief (general) — verification-contract-spike-1

## A. External-writes enumeration

**`external_writes_required: ["git push origin main"]`** — and nothing else.

This spike's own acceptance criteria (`plans/verification-contract/roadmap.yaml:184-196`) produce
exactly two artifacts: an ADR recording measured pass/fail + overhead per route, and (if the spike
concludes negatively) a documented manual-operator fallback note. Both are local Markdown files
under `.claude/docs/` (matching the `adr-verification-contract-five-operations.md` precedent this
repo's own `verification-contract-m1` milestone just set). Neither criterion names a package
publish, a deploy, a GitHub issue/PR write, or any other network-mutating call. Per CLAUDE.md
§4.4, `git push origin main` is per-event user authorization and is **not implied** by a completed
spike — this is recorded as the only candidate write, not an approval to execute it. This mirrors
`verification-contract-m1`'s own sibling research brief
(`.claude/notes/milestones/verification-contract-m1/research/brief-2.md`), which reached the
identical conclusion for the milestone immediately upstream of this one.

**Side effect that is NOT a write but is worth naming explicitly (per this brief's own
instructions):** the container/WSL2 route requires **pulling a Docker image** onto the operator's
machine — a network read with local disk-usage consequences, not a repo write. There is no
evidence in this repo that a specific base image has been chosen (`infra/latexml/` and
`docker/Dockerfile.server` exist but neither packages a Lean toolchain; `infra/latexml/docker-
compose.latexml.yml` is itself referenced as "does not exist yet" territory by
`plans/scale-ops-hardening/roadmap.yaml:49`). For scale, representative published Lean4 images
found this session: `leanprovercommunity/lean4:latest` is **407,173,263 bytes (~388 MB)**
compressed, linux/amd64 (Docker Hub API, hashed above); the same organization's `mathlib`
gitpod-dev variant runs ~722 MB and a community-built minimal `semenovp/tiny-lean4-toolchain` is
~39.1 MB (WebSearch snippet level only — not independently fetched/hashed, flagged accordingly).
None of these is necessarily what m2/m5 would actually ship — R3's own roadmap separately
estimates "tens of GB" for a `mathlib@pinned-commit` build with `lake exe cache get`
(`plans/verification-contract/roadmap.yaml:29-30`) — but a **core-only** image (this spike's actual
scope; `lean-sandbox-design.md` and spike-2's own finding confirm the live REPL is core-only, no
Mathlib) is in the tens-to-hundreds-of-MB range, not gigabytes. Docker Desktop itself, if not
already installed, is also a multi-hundred-MB-to-GB installer — the orchestrator's live probe
confirmed Docker 29.1.3 is already running on this box, so this is not a fresh-install cost here,
but should be noted as a one-time setup cost for any other box running this spike.

## B. Technical research

### B1. Windows Job Objects — what they can enforce (live-verified, not just documented)

I ran a bounded, safe probe harness against this exact workstation (Windows 11 10.0.26200,
pywin32 311, Python 3.11.9) rather than relying on documentation alone — every test spawned only
short-lived, project-authored child processes (never Lean, never network I/O, never an unbounded
bomb), and every job/process handle was closed. This is the single most load-bearing section of
this brief: several findings below **contradict a naive reading of the documentation** and must
inform the spike's own test design.

**pywin32 surface, confirmed by direct introspection of the installed 311 build (`win32job`
module):** `CreateJobObject`, `SetInformationJobObject`, `QueryInformationJobObject`,
`AssignProcessToJobObject`, `TerminateJobObject`, `OpenJobObject`, `IsProcessInJob`,
`UserHandleGrantAccess` — all 8 job-management primitives are present, plus every
`JOB_OBJECT_LIMIT_*` / `JOB_OBJECT_UILIMIT_*` / `JOB_OBJECT_MSG_*` constant. `QueryInformationJobObject`
returns a genuine nested Python `dict` (not raw bytes) for `JobObjectExtendedLimitInformation` —
confirmed live: `{'BasicLimitInformation': {...'LimitFlags', 'ActiveProcessLimit', ...},
'IoInfo': {...}, 'ProcessMemoryLimit': 0, 'JobMemoryLimit': 0, ...}`.

**What the memory limits actually do (matches docs, empirically confirmed).**
`JOB_OBJECT_LIMIT_PROCESS_MEMORY` set to 64 MB, a child tries to allocate 512 MB: the allocation
call itself **fails** (Python's `bytearray()` raised `MemoryError`; the process caught it and
exited cleanly, `returncode=0`) — it is **not** an instant kill. This exactly matches the fetched
struct doc's wording: "When a process attempts to commit memory that would exceed the per-process
limit, **it fails**." **Implication for the spike's memory-bomb probe:** a PASS must be defined as
"the allocation attempt fails / the process cannot exceed the cap," not "the process gets killed"
— and the spike must separately verify how Lean's own runtime (not Python's) behaves on an
allocation failure (crash vs. graceful OOM report) with a **real** Lean elaboration, since a
synthetic Python allocator is not evidence for Lean's C++/native-heap behavior.

**A sharp, reproducible, and highly consequential `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` gotcha.**
Setting `ActiveProcessLimit=1` and assigning a single, ordinary, already-running Python child
process to the job **kills that child before it executes a single line of code** — confirmed by
adding an unconditional first-line `print("STARTED", flush=True)` to the child script, which
never appeared in its (empty) captured stdout; the parent saw `returncode=101` and a stderr string
matching the `_winapi`-level `"Unable to create process using '<full cmdline>'"` failure shape.
Raising the cap to `ActiveProcessLimit=2` let the SAME child run to completion. This means **one
ordinary console-hosted child process costs *more* than 1 against this limit in this exact
environment** — consistent with the fetched doc's own accounting rule ("the system increments the
active process count when you attempt to associate a process with a job... if the limit is
exceeded, the process is terminated and the association fails"), but the extra unit is not the
Lean subprocess itself; it is most likely a console-host helper process Windows silently attributes
to the same job (this dev environment is hosted by Git Bash / mintty, which does not hand child
Win32 console apps a native console — `CREATE_NO_WINDOW` did **not** fix it when I tested it live,
so the exact mechanism is not fully root-caused; a `venv`-launcher redirection hop is a second,
unconfirmed candidate). **This is the single highest-value operational finding in this brief:** a
naive `ActiveProcessLimit=1` cap sized for "one Lean subprocess = one process" will kill a
perfectly benign Lean invocation before it produces any output, which is a **false-positive
containment signal** indistinguishable, from the outside, from "the sandbox correctly stopped a
fork bomb" — exactly the "PASS vs. a probe that merely failed to run" ambiguity Section B6 of the
milestone brief asks about. The spike must (a) measure the real per-invocation process cost from
whatever process actually launches `lake exe repl` in arXMCP's real entrypoint (not a nested dev
shell — see the ambient-job finding below), and (b) budget headroom above the naive "1", not
assume it.

**Breakaway: the documented rule, and a live result that does not cleanly confirm it in this
environment.** The nested-jobs doc is unambiguous: "If the immediate job object does not allow
breakaway, the child process does not break away even if jobs in its parent job chain allow it" —
i.e. only the innermost job's `JOB_OBJECT_LIMIT_BREAKAWAY_OK` / `_SILENT_BREAKAWAY_OK` matters, and
both are **off unless explicitly set**, so breakaway can be denied outright simply by never setting
them. Live testing, however, surfaced a genuine, unresolved discrepancy that the spike must chase
down with better tooling than I had available (Process Explorer / ETW, not just user-mode Python):

| Job configuration (mine; no BREAKAWAY_OK set in any case) | `CREATE_BREAKAWAY_FROM_JOB` grandchild spawn result |
|---|---|
| Only `KILL_ON_JOB_CLOSE` (no `ActiveProcessLimit`) | **Succeeded** (`GRANDCHILD_RAN`, exit 0) — contradicts a naive reading of the doc, since my (innermost) job never granted breakaway |
| `ActiveProcessLimit=1` | Child killed before running (the gotcha above; breakaway was never reached) |
| `ActiveProcessLimit=2` | Child ran; grandchild spawn attempt failed cleanly: `WinError 1816 ERROR_NOT_ENOUGH_QUOTA` |
| `ActiveProcessLimit=3` | Child ran, reported `GRANDCHILD_SPAWN_OK`, but the **grandchild itself** then died before running any code (`returncode=101`, same signature as the `ActiveProcessLimit=1` case, one level down) |

Also confirmed: the process that hosts this entire research session is **already inside an
externally-created Job Object** (`win32job.IsProcessInJob(GetCurrentProcess(), None) == True`) —
plausibly the coding-agent harness's own Job-Object-based child-process supervision on Windows (a
correct, standard pattern for guaranteeing cleanup). This makes every job I create in this session
a **nested** job by construction, and I do not control, and cannot query, the ambient job's own
flags (it is unnamed; I hold no handle to open it independently). Given the doc's own accounting
notes above about active-process quota interacting with process creation, and that my one clean
"breakaway succeeded" result came from the ONE configuration without an active-process limit, I
cannot rule out that the ambient job (not mine) is what actually permitted the escape in that case.
**This is an open, unresolved finding, not a settled one — the spike must re-run a clean breakaway
test (a) with no `ActiveProcessLimit` confound, and (b) from arXMCP's actual production launch
context (however `make up`/the real entrypoint starts the process), not a nested Git-Bash dev
shell, before trusting "just omit BREAKAWAY_OK" as sufficient.** I could not test launching a
"clean" (non-nested) shell myself — the Bash tool available to this research role is Git-Bash-
hosted for every invocation, which is itself the source of the nesting; this is a genuine method
limitation of this research pass, not something I chose not to check.

**CPU rate control: throttle, not kill — and unsupported by this pywin32 build.**
`JOBOBJECT_CPU_RATE_CONTROL_INFORMATION`'s `JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP` "causes... no
threads associated with the job will run until the next [scheduling] interval" (WebSearch,
Microsoft Learn snippet, not independently fetched at full source depth this session — flagged
accordingly) — i.e. it **throttles**, it does not terminate. This means CPU rate control is **not**
a substitute for the wall-clock timeout `lean_repl.py` already implements for the heartbeat-bomb
case (`DEFAULT_QUERY_TIMEOUT_S = 30.0`) — an infinite-loop elaboration under a CPU cap would simply
run slower, not stop. Separately, and empirically confirmed live: this pywin32 311 build's
`SetInformationJobObject` **raises `NotImplementedError("Job information class 24 is not
supported yet")`** when given the CPU-rate-control info class with a dict payload shaped like the
other supported classes — the binding does not marshal this structure at all. If the spike wants
CPU rate control, it needs raw `ctypes` against `kernel32.dll`, not the `win32job` wrapper already
in the verified environment.

**No network primitive exists on Job Objects at all — confirmed, not inferred.** The only
network-related Job Object structure, `JOBOBJECT_NET_RATE_CONTROL_INFORMATION`, has exactly three
members: `MaxBandwidth` (a byte-rate cap), `ControlFlags`, and `DscpTag` (a QoS marking byte) — a
bandwidth throttle and traffic-class tag, **not** an allow/deny gate. There is no `JOB_OBJECT_LIMIT_*`
flag anywhere in the fetched `JOBOBJECT_BASIC_LIMIT_INFORMATION`/`JOBOBJECT_EXTENDED_LIMIT_INFORMATION`
surface for network access at all. **This settles the brief's own "sharpest question": Job Objects
cannot deny network access, full stop** — whatever the Job Object route does for the network-escape
probe, it must come from something else (see B3).

### B2. Restricted tokens

**The mechanism, confirmed against the official doc and live-tested with a real filesystem probe.**
`CreateRestrictedToken(ExistingTokenHandle, Flags, SidsToDisable, PrivilegesToDelete,
SidsToRestrict)` — pywin32 exposes it directly (confirmed callable), plus `CreateProcessAsUser`
(confirmed present in `win32process`), `TokenIntegrityLevel` / `TokenMandatoryPolicy` info classes
(confirmed present in `win32security`), and every `SECURITY_MANDATORY_*_RID` constant in
`ntsecuritycon` (LOW/MEDIUM/HIGH/SYSTEM/UNTRUSTED) needed to build a low-integrity token by hand.
**pywin32 has NO AppContainer wrapper at all** — grepped `win32api`, `win32security`,
`win32process`, `win32job`, `win32con`, `ntsecuritycon`, `win32profile` for any
`AppContainer`-named symbol; zero hits. Building an AppContainer sandbox would require raw
`ctypes` calls into `userenv.dll` (`CreateAppContainerProfile`) and
`UpdateProcThreadAttribute`/`PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES` — a materially larger
implementation lift than either the restricted-token or Job-Object primitives pywin32 already
covers cleanly. **This tips the practical answer toward "restricted token (+ optional manual
low-integrity-level drop via `SetTokenInformation`)" over AppContainer for a Windows-native route,
purely on what pywin32 already exposes** — the milestone brief's own "is
`CreateProcessAsUser` with a restricted token sufficient, or is an integrity-level drop also
needed" question is answered as: both primitives are independently available and composable
(disable SIDs AND lower the integrity level in the same restricted-token flow if wanted), but
AppContainer is a separate, unsupported-by-pywin32 code path.

**`SidsToDisable` vs. `SidsToRestrict` are two different, independent mechanisms — confirmed by a
live test that would otherwise be easy to get wrong.** The fetched doc states plainly: "the system
performs two access checks: one using the token's enabled SIDs, and another using the [restricting
SIDs]. Access is granted only if both... allow." Live-tested: disabling the well-known "Everyone"
SID via `SidsToDisable` (which the doc confirms "turns on `SE_GROUP_USE_FOR_DENY_ONLY` and turns
off `SE_GROUP_ENABLED`") produced a token where `IsTokenRestricted()` returns **False** — because
that API specifically reflects the presence of a non-empty `SidsToRestrict` list, a *different*
parameter than the one that actually changes ACL evaluation. **A future implementer checking
`IsTokenRestricted()` to confirm a `SidsToDisable`-only token is "working" will get a false
negative** — the correct verification is the actual access outcome (or `GetTokenInformation(...,
TokenGroups)` showing the `0x10` deny-only attribute bit on the disabled SID), not `IsTokenRestricted`.

**Direct, live-verified YES to the R3 brief's stated requirement.** I ran a bounded test: created a
throwaway file with an explicit ACL granting Read to my own user SID only (`icacls /inheritance:r`
+ `/grant:r <domain>\cedar:(R)`), then launched `cmd.exe /c type <file>` via `CreateProcessAsUser`
twice — once with a restricted token that disabled only the unrelated "Everyone" SID (**control**:
succeeded, file content read back correctly), and once with a restricted token that disabled the
caller's **own** user SID (**test**: failed, `exit_code=1`, no output produced at all — the child
could not even create its redirected-output file in the scratch directory, meaning the restriction
was not narrowly scoped to just the one target file). **This directly confirms: disabling the
caller's own identity SID and launching via `CreateProcessAsUser` DOES make identity-ACL'd
locations (a target file, and the working directory itself) unreachable to the child, without
needing elevated privileges** (per the doc: "If a process calls `CreateProcessAsUser` using a
restricted version of its own token, the calling process does not need... `SE_ASSIGNPRIMARYTOKEN_NAME`").

**A live-verified caveat that materially affects correctness on THIS class of deployment.** The
operator account on this workstation (`cedar`) **is** a member of `BUILTIN\Administrators`
(confirmed: the SID is present in the token), but in a normal, non-elevated process (which this
research session is — `IsUserAnAdmin()` returned `False`) that group SID is **already**
`SE_GROUP_USE_FOR_DENY_ONLY` (`0x10`) purely from standard UAC token filtering, before any
restriction of my own is applied. **Practical implication:** for an arXMCP server launched normally
(not "Run as Administrator", not a `LocalSystem` service), disabling only the operator's own user
SID is likely sufficient in practice, because UAC has already neutralized the Administrators-group
grant. **But this is not guaranteed for every launch mode** — if arXMCP is ever run elevated or as
a service under a different identity, `BUILTIN\Administrators` (or `NT AUTHORITY\SYSTEM`) could be
**fully enabled** in the starting token, and any directory ACL that separately grants that group
(common — many Windows directories carry an independent "Administrators: Full Control" ACE) would
still be reachable unless that SID is *also* explicitly added to `SidsToDisable`. **The spike must
enumerate every SID in the actual launch-time token (`GetTokenInformation(..., TokenGroups)`), not
assume "disable the user SID" alone is complete**, and should re-run this exact filesystem probe
from arXMCP's real launch context.

**Defense-in-depth note the doc surfaces that is easy to miss:** "Applications that use restricted
tokens should run the restricted application on desktops other than the default desktop... to
prevent an attack... using `SendMessage` or `PostMessage`" (shatter-attack-class concern) — worth
recording in the ADR as a known residual even if not implemented this milestone.

### B3. Network denial on Windows without a container

Confirmed in B1: Job Objects have **no** network-access primitive. The practical Windows-native
mechanism is the firewall (Windows Filtering Platform-backed): `New-NetFirewallRule -Program
"<absolute path to lake.exe / lean.exe>" -Direction Outbound -Action Block` creates a per-executable
outbound block, confirmed via the fetched cmdlet reference (`-Program`: "Specifies the path and
file name of the program for which the rule allows traffic," used in the doc's own worked example
scoping a rule to one `.exe`). **Not verified in this session, but standard, widely-documented
Windows behavior:** creating/modifying firewall rules requires an elevated (Administrator)
PowerShell session — this is an operational cost the Job Object route does not otherwise carry
(neither Job Objects nor `CreateRestrictedToken` need elevation for a process narrowing its own
rights). **Open question for the spike, not resolved here:** whether the firewall rule can be
provisioned **once**, at install/setup time, scoped permanently to the fixed `lake`/`lean`
executable path (cheap, static, arguably better than the container route's own per-run
`--network none` since it never needs re-asserting) — versus needing per-invocation management,
which would be slower and more fragile than Docker's one-flag primitive. This is the deciding
factor the milestone brief calls out as "the sharpest question" — my conclusion: **network denial
is achievable on Windows without a container**, via a firewall rule that is provisioned once and
left in place, not via anything Job-Object- or restricted-token-native; the ADR should record this
as a *third*, orthogonal primitive layered on top of whichever isolation route wins, since even the
container route needs its own explicit `--network none` (it is not automatic either).

### B4. The container/WSL2 route

All of `--network none`, `--pids-limit`, `--read-only`, `--security-opt no-new-privileges`,
`--cap-drop`, and `--ulimit fsize` (=`RLIMIT_FSIZE`, the file-size cap) are confirmed as documented,
independent `docker run` flags (fetched + hashed). `--memory` is enforced by the kernel OOM-killer
("the kernel kills processes in a container" on exceedance — a harder, more final failure mode
than the Windows Job-Object memory limit's "the allocation call fails" behavior from B1, worth
naming as a real behavioral difference between the two routes, not just an implementation detail).
`--cpus` is a hard guaranteed cap (e.g. `--cpus="1.5"` on a 2-CPU host), not a soft share. The
fetched resource-constraints page did **not** cover `--tmpfs` (named in the milestone brief for the
writable-scratch requirement) — a gap in this specific fetch, not a claim that the flag doesn't
exist; it is a standard, long-documented `docker run` flag and should be trivial to confirm in the
spike's own smoke test.

**Startup overhead — what is and isn't grounded here.** Docker's own blog states the `dockerd`
daemon itself can be running from a cold WSL2 boot in **~2 seconds**, and under 10 seconds versus
"almost a minute" in the pre-WSL2 backend (WebSearch snippet, Docker's own blog — not independently
fetched/hashed this session). **This is a one-time, per-session cost (the daemon booting), not a
per-verification-call cost** — it must not be conflated with the number the spike actually needs:
per-invocation `docker run --rm <lean-image> <command>` wall-clock, both cold (image not yet
pulled/cached) and warm (image cached locally, or a long-lived container reused across calls). No
authoritative published number exists for a Lean-toolchain-sized image specifically; **the spike
must measure this directly** — this is exactly what AC1 requires and is not a shortcut-able step.
For grounding the image-pull side of "cold": a representative core Lean4 image
(`leanprovercommunity/lean4:latest`) is a precisely-confirmed **407,173,263 bytes (~388 MB)**
compressed (Docker Hub API, hashed above) — a one-time-per-machine pull cost, separate from
per-invocation container startup.

**WSL2 filesystem cross-boundary performance — qualitative guidance only, no numbers found at
source depth.** The official WSL docs recommend against working across the Windows/Linux boundary
"unless you have a specific reason," and specifically: store Linux-side project files under the
Linux filesystem root (accessible from Windows via `\\wsl$`), not under `/mnt/c/...` — "your
performance speed will improve if you store them directly on the `\\wsl$` drive" (exact wording,
hashed). **No concrete numbers (e.g. "3x slower") are given in this specific page** — community
benchmarks exist but were not independently verified this session and are not cited as fact here.
**Direct relevance to Lean specifically:** `server/lean_repl.py`'s `spawn()` sets the subprocess
`cwd` to the built `leanprover-community/repl` package directory so `lake` resolves `LEAN_PATH`
there — if the container route places this toolchain/`LEAN_PATH` tree on the Windows side and
bind-mounts it into the Linux container across `/mnt/c/...`, the WSL2 cross-boundary penalty
applies to **every file Lean's elaborator touches during import resolution**, which could dominate
elaboration time for anything beyond the trivial core-only snippets spike-2 measured. **The spike
should place the Lean toolchain natively inside the container's own (Linux-side) filesystem — baked
into the image or a named Docker volume, never a bind-mount of a Windows-side path** — and measure
the difference directly rather than trust the qualitative guidance alone.

**Terminology note worth keeping precise in the ADR:** "Windows Containers" (Windows Server
Containers / Hyper-V Isolation, running Windows-based container images) is a **different**
technology from "Docker Desktop with the WSL2 backend running Linux containers" — the milestone
brief's "container/WSL2" phrasing and the existing `scale-ops-hardening` MinerU precedent
(`plans/scale-ops-hardening/roadmap.yaml:17,43-49`) both point at the latter. This brief's research
is scoped to that (Linux containers via the WSL2-backed Docker Desktop already verified running on
this box); Windows-native containers were not researched and are a different, heavier ecosystem
choice for a fundamentally Linux/macOS-first tool like the Lean toolchain (which does already run
natively on Windows per this repo's own shipped `lean_repl.py`, so this distinction matters).

### B5. Comparable prior art

**AXLE's stated isolation mechanism** — already fetched, sha256-pinned, and verbatim-quoted one day
prior (2026-08-03, same investigative window) in the sibling milestone's own research artifact
(`.claude/notes/milestones/verification-contract-m1/research/brief-2.md`, §B3; sha256
`82d1b44e8a3d8388a092a07f15941e03bf42bd53c5bdab8b1abd5bd3c52bbb51` for `arxiv.org/pdf/2606.26442`)
— cited here by reference rather than re-fetched, since the content is unchanged and same-day-fresh:
"Each request runs in its own sandboxed process. State a request mutates... does not persist into
any later request, and a crash or runaway elaboration in one request does not affect concurrent or
subsequent requests. The sandbox additionally blocks network access and prevents the candidate
from writing to the filesystem" (AXLE §3.3, verbatim). AXLE does not name its underlying OS
mechanism (Linux namespaces, a container, or something else) in the portion fetched — it is
architecturally a **process-per-request** model, not a warm pool, which is why R3 already sequences
pooling (e6) after the trust gate.

**Competitive-programming judges and CI sandboxes — Linux-first, with a documented caution.**
`isolate` (used by CMS/Codeforces-family judges) layers Linux namespaces (process/filesystem/network
view), cgroups (CPU/memory/process-count caps), and seccomp (syscall allowlisting) — but even a
seccomp-allowed syscall "still executes directly against the shared host kernel," a documented
limitation. **Judge0**, a widely-deployed open-source online judge built on this style of sandbox,
had sandbox-escape vulnerabilities disclosed in 2024 and referenced again in 2026 research
(WebSearch snippets: Infosecurity Magazine, TheHackerNews, tantosec.com — none independently
fetched/hashed this session, reported at search-confidence only). **Firecracker microVMs** (used by
AWS Lambda) are named as a stronger-isolation alternative precisely because seccomp/namespace-based
sandboxes share the host kernel. **Evidence-ledger census (dated, scoped, honestly reported):**
query `"competitive programming judge sandbox Windows Job Object vs Linux container isolation
untrusted code 2026"`, one WebSearch round, 2026-08-04 — **no result compared Windows-native Job
Object containment against Linux-container isolation for this use case at all**; every source
found is Linux-first (isolate, Judge0, Firecracker). This is reported as an absence with a named
census (query + date + verdict), not a categorical "nobody does this" claim: the search was narrow
(one query, one round) and a differently-worded or multi-round search could surface something this
pass did not. **Practical reading: the decision this spike produces will be a first-party
measurement on this exact workstation, not one backed by a comparable published precedent — budget
the full 3-day window rather than expecting a literature shortcut.**

### B6. Measurement methodology

The milestone brief names six probes (AC1): heartbeat bomb, memory bomb, fork bomb, filesystem
read-escape, filesystem write-escape, network escape. Proposed concrete shape for each, informed
directly by the ambiguities this session's own live testing ran into:

| Probe | Minimal implementation | PASS definition | How to distinguish PASS from "probe failed to run" |
|---|---|---|---|
| Heartbeat bomb | A Lean snippet with an unbounded/very-high `maxRecDepth`/tight loop (`partial def loop... loop`), or simply omit `set_option maxHeartbeats` on a divergent term | The wall-clock kill fires within a bounded margin of the configured timeout; the *supervising* process (not the sandboxed one) observes the kill and returns a distinct `timeout` status | Record the observed wall-clock delta AND confirm the underlying process is actually gone (`tasklist`/`docker ps`), not just that the parent's `wait()` returned — a wedged transport can look like "handled" without the child dying |
| Memory bomb | A term forcing a large allocation (Lean-level, not a Python proxy — B1's finding shows Python's `MemoryError` behavior does not transfer to Lean's native heap) | The allocation attempt is denied/OOM-killed **and** the *specific mechanism* is recorded (allocation-fails-cleanly vs. process-killed vs. wall-clock-timeout catching it instead) — these are different guarantees, not interchangeable | If the process merely times out instead of hitting the memory cap first, that is a DIFFERENT probe passing by accident — record which limit actually fired, not just pass/fail |
| Fork bomb | A bounded, project-authored "spawn N children" snippet with N capped at a known-small number (e.g. 5-10) run inside the harness — **never an actual unbounded `:(){ :\|:& };:`-style bomb**, per the SAFETY section below | `ActiveProcessLimit`/`--pids-limit` denies the (N+1)th process, or the whole job/container is torn down | Given B1's finding that a *single* ordinary process can already cost >1 against a naive `ActiveProcessLimit`, first establish the real baseline cost for ONE well-behaved Lean invocation in the actual launch context, THEN size the fork-bomb probe's expected trip point against that measured baseline — not against "N+1" naively |
| Filesystem read-escape | Attempt to read a fixed, known, non-scratch path outside the sandbox (e.g. a file under the corpus tree, or `%USERPROFILE%`) | `Access is denied` / `ENOENT`-from-namespace, not merely "file not present because cwd differs" | Use a target file guaranteed to exist and be non-empty on this workstation, and confirm the *reason* for failure (permission vs. path-not-visible) — B2 showed the reason matters (deny-only ACL vs. never-mounted path are different security properties) |
| Filesystem write-escape | Attempt to write outside the scratch directory (e.g. into the toolchain's own read-only tree, or the corpus directory) | Write denied; the target location is byte-for-byte unchanged afterward (hash before/after) | Same reason-for-failure discipline as above; also confirm the read-only toolchain mount/ACL survives a repeated attempt (not just the first) |
| Network escape | Attempt an outbound TCP connect to a known-reachable external host (or a local listener the harness controls, to avoid depending on live internet) | Connection attempt fails/times out at the OS level, confirmed by a listener-side "connection never arrived" check, not just a client-side error (a client error could be a DNS/proxy artifact rather than a real block) | Prefer a LOCAL listener under the harness's control as the target — B3 found the Windows-native mechanism is a firewall rule, which is provisioned per-executable-path, not per-destination, so testing against *any* reachable target should suffice, but a controlled listener removes ambiguity about whether the internet itself was reachable |

**A fair overhead metric.** Measure wall-clock and peak-memory for a **trivial, real** Lean snippet
(e.g. `#check 1 + 1` — not a bomb) run (a) fully unconfined (today's baseline — `lean_repl.py`'s
existing sub-second round-trip per spike-2), (b) inside the Job Object + restricted token route,
and (c) inside the container route, each measured **cold** (fresh process/container) and **warm**
(reused worker / long-lived container), and report the **added latency**, not an absolute number
alone — a route that adds 50ms to a 200ms baseline reads very differently from one that adds 50ms
to a 5ms baseline. Report peak RSS/working-set the same way. This directly operationalizes AC1's
"pass/fail and overhead are recorded per route."

## C. Safety

The spike runs (bounded, controlled versions of) memory bombs and fork bombs on the operator's real
workstation. This box currently has **31.1 GB total RAM / 14.0 GB available (54% load) and 16
CPUs** (read live via `GlobalMemoryStatusEx`, read-only, this session) — and per CLAUDE.md's own
2026-08-01 concurrency note, **this box regularly runs 2-3 concurrent agent sessions**, so "14 GB
available now" is not a stable floor to assume during the spike's own 3-day window.

**Per-probe blast radius if containment FAILS:**

| Probe | Blast radius on failure | Concrete mitigation |
|---|---|---|
| Heartbeat bomb | One CPU core pegged indefinitely; low risk to the rest of the system | Outer wall-clock kill (see below) is sufficient; low priority for extra caps |
| Memory bomb | Can exhaust available RAM, trigger system-wide thrashing/OOM affecting **other concurrent agent sessions and the operator's own foreground work** — the highest-blast-radius probe on a shared, multi-session box | Absolute cap **well below** system RAM regardless of route (recommend ≤2 GB per probe — under 7% of total, under 15% of the currently-available figure above, leaving headroom for concurrent sessions); never rely on the mechanism under test as the only backstop (see outer kill-switch below) |
| Fork bomb | Process-table/handle exhaustion, UI/system sluggishness system-wide if uncapped | **Never run an actual unbounded fork bomb.** Use the bounded, small-N version from B6; B1's own finding (one process can silently cost >1 against a naive cap) is itself evidence that even a "small" N needs headroom, not that N should be raised without limit |
| Filesystem read/write escape | Low direct blast radius (a failed escape is a no-op; a successful one could corrupt a real path) | Point every probe at scratch/synthetic targets ONLY — never a live corpus path or a real home-directory file with content that matters, mirroring how this research session itself only ever touched `%TEMP%\...\scratchpad\` |
| Network escape | Low blast radius (a successful escape just proves an outbound connection is possible) | Target a harness-controlled local listener (B6) so a "successful escape" never actually reaches the open internet or exfiltrates anything real |

**Recommended ordering (the milestone brief's own suggestion, reinforced by this session's live
findings, not just repeated):** **run the containerized route first.** Docker's `--memory`/
`--pids-limit`/`--network none` are mature, widely-battle-tested primitives (confirmed via official
docs, B4) with a simple, well-understood failure mode (kernel OOM-kill). The Job Object route, by
contrast, demonstrated in THIS session alone: an active-process cap that kills benign processes
before they run (B1), an unresolved breakaway discrepancy under nesting (B1), and a pywin32 binding
that silently fails to support CPU rate control (B1) — evidence, not speculation, that a
hand-rolled Job Object harness is more likely to have a footgun the spike hasn't found yet. Trust
the container route's results first; treat any Job Object result that looks "too clean" with extra
suspicion given how easy it was, in this session, to accidentally produce a false-positive
"contained" signal that was actually an accounting artifact killing the harness itself.

**Concrete host-protection measures to adopt (synthesizing the above):**
1. Absolute memory cap ≤2 GB per probe invocation, regardless of route or mechanism used to enforce it.
2. `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` (or `--pids-limit`) set with **measured headroom** above the
   real baseline process cost for one legitimate Lean invocation (B1) — not a bare "1".
3. A **hard wall-clock kill from OUTSIDE the mechanism under test** (a plain Python/PowerShell
   supervisor with its own `subprocess.communicate(timeout=...)` + process-group/job kill, exactly
   the pattern already shipped in `tools/cdm_eval.py::_run_subprocess_with_pgkill` and
   `ingest/textbook_parser.py::run_mineru_sandboxed`) for every probe — the mechanism being
   evaluated cannot be trusted as its own sole backstop while it is literally what is under test.
   30-60 s is a reasonable outer bound given `lean_repl.py`'s own existing 30 s per-query timeout.
4. **Never run probes with the arXMCP server live** — `ARXMCP_ENABLE_LEAN` already defaults off, so
   this is the natural state, but the spike should explicitly confirm no `arxmcp-shim.exe` /
   `python -m server.main` process is running before starting (mirrors CLAUDE.md §8 item 12's
   already-documented "a running shim self-locks the venv" hazard — a live server adds an
   uncontrolled second consumer of the same resource budget during exactly the tests measuring
   that budget).
5. **Stated bound for "the workstation falls over":** if a single probe invocation is ever observed
   to push system-wide available memory below ~2 GB or memory load above ~90%, or to leave more
   than the probe's own bounded process count running after its outer kill-switch should have
   fired, **stop the spike immediately**, or reduce every cap by half and use the containerized
   route exclusively — a workstation-wide slowdown affecting concurrent agent sessions is itself a
   real research-integrity problem (CLAUDE.md's own concurrency note), not just an inconvenience.

## D. Constraints

- **No-fork policy (CLAUDE.md §4.7).** Pulling a published base Docker image (e.g. a Lean4 image,
  B4) is infrastructure reuse, not the kind of code-lifting the no-fork policy targets — but if the
  spike is tempted to adapt SafeVerify or `leanprover-community/repl` source directly into this
  repo for any probe, that crosses the line; use ideas, not vendored code (the sibling m1 ADR
  already recorded this exact bound for `strict_replay_proof`'s spike-2, and it applies here too).
- **`assert` is banned repo-wide outside `tests/**` (ruff S101, `pyproject.toml:339-356`).** This
  is NOT scoped to only the trees that ship in the wheel — `ruff check .` (part of `make test`)
  covers the whole repo minus `var/` and `tests/**`. Any probe script committed as a tracked repo
  file (anywhere other than `tests/`) must not use bare `assert` for invariants. Given this
  milestone's own framing ("deliverable = measurements + a recorded decision, not production
  code"), the cleanest path is to **not commit throwaway probe scripts as tracked files at all** —
  keep them as session-local/scratch artifacts and commit only the ADR + measurement tables, unless
  the spike deliberately wants durable, re-runnable probes for m2 to reuse.
- **If durable probes ARE wanted**, land them as real `tests/` pytest cases (gets the S101
  exemption for free) behind a **new opt-in marker** — no `requires_windows_isolation`-shaped
  marker exists yet (confirmed: `pyproject.toml`'s marker list and `tests/conftest.py`'s
  `_OPT_IN_MARKERS` frozenset, lines 75-88, currently name `requires_model`, `requires_latexmlc`,
  `requires_full_corpus`, `requires_lean_repl`, `requires_pdflatex`, `requires_wheel_build`,
  `requires_mineru`, `requires_restic` — none of these fit). Per §4.5's own documented anti-pattern
  (issue #206), a new marker MUST be added to **both** `pyproject.toml`'s
  `[tool.pytest.ini_options].markers` AND `tests/conftest.py::_OPT_IN_MARKERS` or it silently runs
  on every `make test` — exactly the bug that already bit this repo once.
- **Data-plane boundary (§4.8).** This spike touches none of it directly (no server code changes,
  no agent dispatch) — flagged only so the m2 implementer confirms the eventual isolation boundary
  code lands inside `server/lean_repl.py`'s existing sandboxing surface (per the roadmap's own
  `code: ["server/lean_repl.py"]` link on `verification-contract-m2`) rather than introducing a new
  agent-adjacent execution path.
- **Wheel packaging (§4.5b).** A new top-level tracked directory only risks
  `tests/test_wheel_packaging.py` if it is ALSO added to `pyproject.toml`'s
  `[tool.setuptools.packages.find].include` — a spike's research artifacts should never be added
  there; this is a non-issue as long as probe code (if committed) stays under `tests/` or
  `.claude/notes/`.
- **Evidence-ledger discipline (`.claude/docs/evidence-ledger-standard.md`).** Modeled throughout
  this brief: every external claim above is either hashed-and-quoted (9 sources, this session), or
  explicitly flagged as search-snippet-level / not independently verified, or reported as a dated,
  scoped, honest absence (B5's census). The ADR this spike produces should carry the same
  discipline — measured numbers from THIS spike's own runs, not borrowed industry folklore.

## Acceptance criteria the implementer must meet

1. Both routes are measured against all six AC1 probes (heartbeat, memory, fork, filesystem-read-
   escape, filesystem-write-escape, network-escape) within the 3-day window, with pass/fail AND
   wall-clock/peak-memory overhead (cold and warm, per B6's fair-overhead metric) recorded per
   route per probe in a table in the ADR.
2. The ADR is committed under `.claude/docs/` (not `docs/`, not repo root), following the
   `adr-verification-contract-five-operations.md` structural precedent (Status/Date/Owner/Roadmap
   item/Source brief header block; Context; Decision N sections; Consequences; an explicit "Owner
   approval record: Pending" rather than a claimed Accepted status, matching that precedent exactly).
3. For the Job Object route, the ADR explicitly states whether `CREATE_BREAKAWAY_FROM_JOB` can be
   denied outright, resolving this session's unresolved discrepancy (B1) by re-testing from a
   **non-nested launch context matching arXMCP's real entrypoint** (not a dev shell already inside
   an ambient job) and by isolating `ActiveProcessLimit` accounting from breakaway-permission
   denial as two independently-tested conditions, not a confounded single test.
4. For the container/WSL2 route, cold (image/container not yet warm) and warm (reused container)
   per-invocation overhead are measured and reported **separately**, distinct from the one-time
   `dockerd` daemon boot cost (B4), and the Lean toolchain/`LEAN_PATH` tree is placed natively
   inside the container's own filesystem (never a bind-mount of a Windows-side path) per B4's
   WSL2-cross-boundary-risk finding.
5. Network denial is resolved as one of: a Windows Firewall per-program rule (`New-NetFirewallRule
   -Program <path> -Direction Outbound -Action Block`, B3) verified to actually block an outbound
   attempt from the Lean subprocess specifically, or "not practically achievable outside a
   container for this route" recorded with the specific test that demonstrated it — Job Objects
   themselves are already conclusively ruled out (B1/B3) and must not be re-litigated as a
   candidate mechanism.
6. If neither route meets the isolation bar within the timebox, the ADR names the documented
   manual-operator fallback for R5 targets and confirms `ARXMCP_ENABLE_LEAN` stays default-off
   (already true today) with no code proceeding to `verification-contract-m2`.
7. The safety bound from Section C is honored and recorded: the container route is measured before
   the Job Object route, every probe's own cap plus an outer, mechanism-independent wall-clock
   kill-switch are both documented, and the stated host-protection thresholds (≤2 GB per probe,
   measured-not-assumed active-process headroom, no live arXMCP server during testing) are followed.

## Risks and open questions

1. **Ambient/nested Job Object confound (highest-priority, live-verified this session).** This
   research session's own process was already inside an externally-created Job Object; Job-Object
   behavior measured from within a nested dev shell (breakaway denial, active-process accounting)
   may not match arXMCP's actual production launch context. The spike must re-verify
   `IsProcessInJob` and re-run the breakaway test from the real entrypoint before trusting any
   dev-shell-measured result.
2. **`ActiveProcessLimit` undercounts real process cost (live-verified, root cause unconfirmed).**
   One ordinary console-hosted child process cost *more* than 1 against this limit in this
   environment (2 needed to survive; `CREATE_NO_WINDOW` did not fix it). A naive cap sized "1 Lean
   subprocess = 1 process" will kill legitimate invocations, producing a false-positive containment
   signal indistinguishable from correctly-stopped hostile behavior unless the spike explicitly
   measures and records the real baseline cost first.
3. **pywin32 gaps mean two of the brief's named primitives need raw `ctypes`, not the wrapper
   already verified working.** No CPU-rate-control support (confirmed: `NotImplementedError`) and
   no AppContainer wrapper at all (confirmed: zero symbols across 7 modules grepped). If the spike
   wants either, budget the extra implementation risk; the Job-Object-limits and restricted-token
   primitives it already has confirmed working are the lower-risk subset.
4. **The container image choice is being made twice if uncoordinated.** Whatever base image this
   spike measures for the container route will also need to host whatever `strict_replay_proof`
   mechanism `verification-contract-spike-2` selects (SafeVerify vs. a bespoke fallback, per the
   sibling m1 ADR's Decision 5) — coordinate rather than let each spike pick independently.
5. **No comparable published prior art exists for this exact bake-off (dated census, B5).** The
   decision this spike produces will be a first-party measurement, not one a literature search can
   shortcut — the full 3-day window should be budgeted for actual measurement, not spent searching
   for a precedent that this session's own (narrow, one-round) search did not find.
