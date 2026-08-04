---
milestone_id: "verification-contract-spike-1"
phase: "research"
briefs_synthesized:
  - "research/brief-1.md (explore)"
  - "research/brief-2.md (general, with live pywin32 probes)"
external_writes_required:
  - "git push origin main"
novel_architecture: true
phase2_path: "delegated"
safety_gate_required: true
---

# Research synthesis — verification-contract-spike-1

Fan-in of brief-1 (explore) and brief-2 (general). Both `complete`, both on
disk, zero injection attempts. brief-2 is unusually strong evidence: the
researcher ran **bounded live pywin32 probes on this workstation**, so several
findings below are empirical, not documentary.

## The headline: the spike's framing question is already partly answered

The brief called network denial "the sharpest question" deciding between the
two routes. Research resolved it, and the answer reshapes the spike:

- **Job Objects have NO network primitive.** `JOBOBJECT_NET_RATE_CONTROL_INFORMATION`
  is bandwidth throttling, not denial. Confirmed against the official doc.
- **But network denial IS achievable Windows-natively** — via a Windows
  Firewall per-executable outbound block (`New-NetFirewallRule -Program
  <abs path to lake.exe>`), provisionable **once** at setup rather than
  per-invocation. It requires an **elevated** session to create.
- **So network denial is a THIRD, orthogonal primitive**, not a discriminator.
  Even the container route needs its own explicit `--network none` — it is not
  automatic there either.

Net effect: the two routes are NOT "one can do network, one can't". They are
two different resource/identity-containment mechanisms, both of which need a
separately-provisioned network control. The ADR must say this, or it will
record a decision on a premise that research already falsified.

## Empirical findings (live-probed, not documentary)

1. **`JOB_OBJECT_LIMIT_ACTIVE_PROCESS=1` killed an ordinary benign child
   before it ran any code** — the working minimum was 2. A fork-bomb cap sized
   "1 process = 1 limit" produces a **false-positive containment signal**: the
   probe would report "contained" when it actually never ran. This single
   finding invalidates the most obvious naive probe design.
2. **Restricted tokens genuinely work.** A real `CreateProcessAsUser` test with
   an ACL'd file showed the control case succeeding and the restricted-own-SID
   case failing — so the R3 requirement that "the corpus and user home are
   unreachable" is satisfiable this way.
3. **This workstation's account is a local Administrator**, but UAC already
   deny-only-filters that SID in non-elevated processes. Load-bearing and easy
   to miss: a probe run elevated would measure a different security context
   than production.
4. **The research session's own process was already inside an ambient,
   externally-created Job Object**, which confounded a clean breakaway test.
   The spike must re-test breakaway from arXMCP's real launch context.
5. **pywin32 311 has no CPU-rate-control and no AppContainer support** —
   confirmed by introspection. CPU capping via Job Object is therefore not
   reachable through the installed binding.
6. **Memory-limit semantics differ by route, materially:** Job Object memory
   limit makes the *allocation call fail*; Docker `--memory` invokes the
   *kernel OOM-killer*. Harder, more final. Not an implementation detail — a
   behavioral difference the ADR must record.

## Repo-context findings

7. **Both routes start from zero proven running containment on this host.**
   The container route's only in-repo analog (`infra/latexml/docker-compose.latexml.yml`)
   self-describes as "a DOCUMENTATION ARTIFACT... NOT the main
   docker-compose.yml", names an image with no Dockerfile in the repo, and the
   sibling milestone that would have proven Docker containment here
   (`scale-ops-hardening-m10`) has **no shipped artifact** despite its target
   window having elapsed. This is a fair fight between two unknowns.
8. **The POSIX kill idiom fails UNCAUGHT on Windows.** `os.killpg` / `getpgid`
   / `SIGKILL` / `fork` are absent, and the existing `suppress` guards do not
   catch it. A probe harness that copies the in-repo idiom would *look*
   implemented while leaving runaway processes unreaped the first time a
   timeout fires — precisely the wrong failure mode in a containment test.
9. **`server/lean_repl.py`'s platform gate has a known-open macOS bug (issue
   #7) sitting in the exact conditional a Windows branch would join.** Decide
   deliberately: fix it, or leave it and say so. Do not change it by accident.
10. **`pywin32` is only a TRANSITIVE dependency** (via `mcp`'s
    `sys_platform == 'win32'` pin), not declared in `pyproject.toml`. Fine for
    an exploratory spike; not a foundation m2 should build on silently — an
    unrelated `mcp` bump could drop it with nothing noticing.
11. **MinerU precedent is directly on point** (CLAUDE.md gotcha #10): its
    grandchild FastAPI server survives `os.killpg` because it spawns with its
    own `start_new_session=True`. That is exactly the process-escape class this
    spike must probe. A Job Object closes it atomically
    (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` reaps every process ever added,
    however deep); a naive `TerminateProcess`-only approach reproduces the gap.

## Scope gaps in the milestone's own acceptance criteria

- **AC1 references "the attack suite's resource cases". The attack suite does
  not exist** — it is `verification-contract-m4` under epic `e4`, which
  `depends_on` e3. Nothing under `tests/` matches. The spike must author its
  own probes. Normal for a de-risking spike, but it is unbudgeted scope.
- **AC2's "documented manual operator fallback" does not exist anywhere in the
  repo.** If the spike's negative branch fires, authoring that fallback is
  additional undocumented scope not covered by the 3-day timebox.

## Acceptance criteria (traced to the roadmap item)

1. Both routes measured on the resource cases; pass/fail **and overhead**
   recorded per route in an ADR under `.claude/docs/`.
2. If neither route clears the bar: Lean stays disabled-by-default and the
   manual operator fallback is documented (see the gap above — that document
   does not yet exist).

## External writes required

```
external_writes_required: ["git push origin main"]
```

Verbatim from brief-2. One named non-write side effect: the container route
**pulls a Docker image** onto the user's machine (network read, local disk
cost). No Lean-toolchain image is selected in-repo; neither
`docker/Dockerfile.server` nor `infra/latexml/` packages one.

## SAFETY — this is the phase gate, not a footnote

This spike's probes include **fork bombs and memory bombs executed on the
user's live Windows workstation**. Both researchers flagged it independently.
Three facts make this more than routine:

1. Finding 1 shows hand-rolled Job Object configuration is **already
   demonstrated error-prone on this box** — the obvious process-cap setting
   silently produced a false containment signal.
2. Finding 8 shows the repo's existing kill idiom **does not work on Windows
   and fails uncaught**, so a harness built from in-repo precedent would not
   reliably reap what it starts.
3. **Three other Claude sessions are live on this workstation right now**
   (Lean architecture redesign, a fork of this session, and the task-chip
   worktree session). A containment failure that forces a hard reboot destroys
   their in-flight work, not just this pipeline's.

Recommended ordering, per brief-2: **run the container route first** — Docker's
limits are kernel-enforced and well-understood — and only then trust a
hand-rolled Job Object. Concrete host protections: absolute caps far below
system RAM, `ACTIVE_PROCESS` limit ≥2 but small, a hard wall-clock kill
*outside* the sandbox, and never run probes with the arXMCP server live.

**This needs an explicit owner decision before Phase 2 runs the destructive
probes.** It is not a call the pipeline should make silently on someone's
working machine.

## Open questions (carried to Phase 2/3)

1. Can the firewall rule be provisioned once at setup, permanently scoped to
   the fixed `lake`/`lean` path, or does it need per-invocation management?
2. Does the WSL2 `/mnt/c` cross-boundary filesystem penalty dominate Lean
   elaboration time enough to disqualify the container route on overhead?
3. Does breakaway-from-job get denied outright from arXMCP's real launch
   context (finding 4's confound must be re-tested)?
4. Fix or explicitly leave issue #7's macOS bug in the block a Windows branch
   would join?

## Phase 2 path decision

**Path: `delegated`, and `novel_architecture: true`.** This is not a mechanical
change: it builds two isolation prototypes plus a probe harness against a
platform the repo has never successfully contained anything on. Well past the
inline thresholds on every axis.

**But Phase 2 must not start until the safety gate above is answered.**
