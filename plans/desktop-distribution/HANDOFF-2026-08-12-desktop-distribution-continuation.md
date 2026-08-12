---
project: desktop-distribution
type: handoff
status: complete
authorship: agent-generated
handoff_kind: continuation
date: 2026-08-12
roadmap: plans/desktop-distribution-roadmap.md
resume_target: opus
tags:
  - project/desktop-distribution
  - type/handoff
  - authorship/agent-generated
  - handoff/continuation
aliases:
  - "desktop-distribution — continuation handoff (2026-08-12)"
---

# CONTINUATION HANDOFF — desktop-distribution (2026-08-12)

> **Audience:** a fresh session picking up `desktop-distribution`. No companion review
> handoff was written (continuation was requested alone). Roadmap:
> `plans/desktop-distribution-roadmap.md` — **legacy-prose, not `roadmap.yaml`**, so
> `milestone-pipeline-record-progress.py` and `issue-note.py` warn and no-op for every id
> in this program. That is expected, not a fault.
>
> **Program goal:** ship arXMCP as a signed, notarized macOS desktop application whose
> operator never needs a Terminal.

## 1. Current state (as of this handoff)

| Milestone | Status |
|---|---|
| m1–m7, m9 | ✅ SHIPPED (before this session) |
| m8 — native-library consolidation + real-model gate | ✅ SHIPPED (finalized this session) |
| m10 — the application launches itself | ✅ SHIPPED |
| m15 — assemble a launchable application bundle | ✅ SHIPPED |
| **m11 — choose storage, adopt or initialize** | ⬜ **← RESUME HERE** (`implement-running`, ADR awaiting owner approval) |
| m12 — model provisioning is consented, never silent | ⬜ next |
| m13 — register the MCP shim without a Terminal | ⬜ free to run any time after m10 |
| m14 — a truthful ready / degraded surface | ⬜ last |

**Execution order is NOT numeric:** `m10 → m15 → m11 → m12 → m14`, with `m13` free after
`m10`. `m15` was allocated last and executes second; the roadmap states this.

Load-bearing live facts:

- **`main` is clean and fully pushed.** Every commit of this session, including the m11 ADR
  (`0625325`) and this handoff, is on `origin/main`.
- **The pipeline lock is RELEASED.** It was held by this session's pid for
  `desktop-distribution-m11` and released at session end after confirming the pid was dead.
  `m11` remains at `implement-running` — the lock is about concurrency, not phase.
- A real `arXMCP.app` now assembles, outer-seals, and resolves its payload. It is **not**
  notarized and nothing may claim it is (ADR Decision 3; a scanner gate enforces the
  language).
- Gates all green at `0625325`, measured serially: `make test` 5202 passed / 0 failed;
  `make desktop-conformance` exit 0, 129 passed zero skips; `make desktop-bundle-check`
  exit 0, 72 passed zero skips.

## 2. RESUME HERE — m11, at the ADR approval gate

**Goal:** make the data root an operator decision with a safe default, and make an existing
root adoptable rather than silently re-initialized.

**State:** `implement-running`, `implementation_base = ea06449`, `allow_large_diff = true`
(set at init, deliberately — see §5.1). Phase 1 complete: two briefs + synthesis committed.
Phase 2 is running as a **two-step**: an ADR dispatch has landed and the implementation
dispatch has NOT been sent.

**The ADR is `.claude/docs/adr-desktop-data-root-selection.md`, Status `Proposed`, owner
approval PENDING.** Its own approval record says the implementation dispatch must not begin
until Decisions 1–3 are accepted or amended. Three decisions:

1. **Pointer at `<platform_data_root()>/data-root.json`**, reusing the Python/Rust function
   pair m10 already pinned to each other. The non-circularity criterion it states is
   sharper than the framing in the roadmap: *the pointer's location is a pure function of
   the process environment, never of the pointer's own content*. Under that criterion the
   pointer sitting inside the **default** data root is harmless; a location derived from
   the **chosen** root would not be, however far outside the default it sat.
2. **`main()`'s startup ordering is NOT restructured**; the picker is a pre-Tauri native
   dialog. `tauri-plugin-dialog` structurally cannot do it — every documented call is an
   `App`/`AppHandle` method and `data_root` resolves 49 lines before the builder exists.
   **The ADR deliberately does not name a crate.** brief-2 proposed `rfd`; the ADR ledgers
   that as **E7 — NOT ESTABLISHED** (asserted in prose, no URL, no hash) and attaches a
   verify-or-escalate obligation instead of pinning a dependency on an uncited claim.
3. **Free space is a lower bound and must be phrased as one.** On APFS the error is
   asymmetric and optimistic (purgeable space + snapshots counted as available), so it
   produces false "looks fine", never false refusals.

**To resume:** read the ADR, then either accept it (flip `Status` to `Accepted <date>`, fill
the owner approval record, commit) or amend it. Then dispatch the implementation half.
Precedent for both steps is m15's ADR (`.claude/docs/adr-desktop-bundle-assembly.md`),
including how an accepted decision was later **superseded by measurement** (Decision 2 →
2a) without relitigating it.

**GATED external write:** `git push origin main` is in m11's `external_writes_required`.
The `complete` transition refuses until the ledger balances, so the push must happen and be
recorded (`--set external_writes_authorized` / `external_writes_completed`) before
finalization. Present it and get explicit per-event confirmation; CLAUDE.md §4.4 makes a
prior "yes" non-transferable.

## 3. Definition of done for m11

- ADR accepted (or amended) with the owner approval record filled.
- Implementation dispatched, fast-forwarded to `main`, `implementation_commit_range` +
  `implementation_commits` recorded.
- Phase 3: three critics (`milestone-adversary-critic` always, plus the two repo overlays),
  merged with `findings.py merge` → `dedupe` → `extract --id`.
- Phase 4: `findings.py gate` exits 0 (no open CRITICAL/HIGH), `rectify/summary.md` written,
  one `rect(...)` commit with `Reviewed-by:` trailers.
- All three gates green **measured by the orchestrator, serially** — including
  `make desktop-bundle-check`, and now also the `requires_bundled_model` prerequisites,
  because m11 inherited m15's narrowed AC3 (§4).
- External-write ledger balanced, `phase: complete`, lock released.

## 4. Remaining epics / milestones

**m11 (in flight).** Beyond the ADR: a cross-language parity row for the override read, or
m10's parity guarantee silently narrows to "only the default path is proven to agree".
Detection/adoption of an existing root. A first-run UI surface that **does not exist
anywhere in the repo today** — the supervisor crate has no window-content surface beyond
lifecycle plumbing. Re-rated **M → L** (~1,200 LOC / ~14 files).

**m11 also carries an inherited obligation.** m15's AC3 was narrowed during rectification to
what its gate measures (assemble, seal, resolve). The full
double-click-to-ready-server-and-rendered-window proof against the **real** frozen child is
now m11's, by owner decision. It brings the `requires_bundled_model` prerequisites (~4.6 GB
from the operator's external HuggingFace cache) into m11's gate. **This obligation has been
deferred once already — do not defer it a second time without saying so explicitly.**

**m12 — model provisioning.** Gate: a launch must perform ZERO requests to any model host
with no consent recorded, asserted at the socket/transport layer, not by reading a flag.
Declining must leave a usable degraded app. m8 established that no weights ship in the
bundle and the loaders call `from_pretrained(revision=<pinned SHA>)` with no
`local_files_only`, so a cold boot currently downloads ~4.6 GB silently.

**m13 — MCP shim registration.** Depends only on m10; can run any time. Registration is
currently a hand-merge into `~/.claude.json`. Must be confirm-gated, backed up, reversible,
and must preserve unrelated keys.

**m14 — ready/degraded surface.** Last, because it reports states m12 and m13 introduce.
Must keep liveness, model availability, corpus presence and shim registration as SEPARATE
axes per §4.9 — no bare "ready" token.

**e4 release gates.** Still blocked on a Developer ID certificate. `spike-4`'s runbook is
written and executable the moment one exists.

## 5. Cross-cutting follow-ups (landmines you'll trip on)

1. **`allow_large_diff` must be set at INIT, in state — not in the dispatch prompt.**
   Pre-authorizing it in the prompt and not in `state.json` produced an identical HIGH
   auto-finding in **m8 and again in m10**. m15 and m11 broke the streak by setting it at
   init. Keep doing that.
2. **A new desktop gate needs its env var registered in `tests/conftest.py::_DESKTOP_GATE_ENV`.**
   Wiring the Makefile's `-m "<token> or not <token>"` expression is NOT enough — that
   expression is a tautology for any token, so the gate *looks* wired while the half that
   turns a skip into a failure is absent. This defect has now occurred **three times**
   (m6 H3, then m15 C1 found by all three critics). A derived guard,
   `test_every_desktop_gate_env_var_is_registered_in_conftest`, now fails if a
   `DESKTOP_*_GATE` in the Makefile is unregistered.
3. **Repo-scoped agents and skills are NOT registered when the session cwd is
   `~/Personal/SourceCode`** (the parent of the repo). `milestone-researcher`,
   `milestone-implementer`, the critics, and the `handoff` skill all fail by name. This
   session worked around it by dispatching `general-purpose` agents told to read the
   definition file from disk, which worked but loses the tool allowlist and `memory:
   project` auto-injection. **Start the next session with cwd = the repo** and the registry
   resolves normally.
4. **Worktree-isolated agents cannot write to the shared checkout under `.claude/notes/`.**
   Every critic and most researchers this session wrote to their worktree-equivalent path
   and reported it; the orchestrator must copy the file in before merging/extracting. Worth
   fixing in the agent definitions rather than copying by hand every time.
5. **Backgrounded `make` inherits the SESSION cwd, not the last `cd`.** Three runs died on
   "No rule to make target". Use `make -C <repo> …`. Also: **piping `make` through `tail`
   masks its exit code** — the first `make test` of the session looked green while dying
   instantly on the Python 3.9 version gate. Capture the status explicitly, and read output
   by content.
6. **`make`'s `PYTHON ?= python3` resolves to a 3.9 on this box.** Always pass
   `PYTHON=.venv/bin/python` (or an absolute path).
7. **`make desktop-conformance` is concurrency-sensitive.** Three racing runs broke
   `test_thirty_cycles_distinct_pids_no_orphans_no_listeners` through port and target-dir
   contention. Serialize gate runs. Recorded as m15 finding L6 (deferred).
8. **`test_supervisor_owns_a_native_window_while_running` is GUI-session dependent.** It
   refuses to conclude "no window" without first observing one somewhere, and the
   zero-skip gate converts that skip into a session failure. A dispatch reported it as a
   standing host failure; it is not — it passes when the session has an observable window.
9. **Two declared macOS floors.** The Rust binaries declare `minos 14.0`; the
   PyInstaller-produced executables declare **11.0** (this project does not compile the
   CPython bootloader). Measured, pinned, deliberately unreconciled. The declared 14.0 floor
   rests on the Rust half plus the `faiss_cpu macosx_14_0_arm64` wheel tag — never on the
   frozen half.
10. **Never claim notarization or Gatekeeper readiness.** `tests/test_desktop_notarization_claims.py`
    scans root/`docs/`/`apps/`/`plans/`/`.claude/docs/` and the m15 milestone notes, and
    fails on the known claim shapes. Critique files are the only exclusion (quoting a
    forbidden phrase is how a bypass gets reported).

## 6. Environment / resume notes (how to reconnect)

```bash
cd /Users/chris.dare/Personal/SourceCode/arXMCP      # start here, so the agent registry loads

# The lock was released at session end. If a future session finds one held, verify the pid
# is dead FIRST, then release it through the script — never `rm` it.
cat .claude/notes/milestones/.lock
bash .claude/scripts/milestone-pipeline-init-state.sh <held-id> --release-lock

# m11 pipeline state
bash .claude/scripts/milestone-pipeline-status.sh desktop-distribution-m11
.venv/bin/python .claude/scripts/milestone-pipeline-resolve-brief.py desktop-distribution-m11

# Gates (serialize; never pipe through tail)
make -C . test PYTHON=.venv/bin/python
make -C . desktop-conformance PYTHON=.venv/bin/python
make -C . desktop-bundle-check PYTHON=.venv/bin/python     # ~0.75 GB rebuild
make -C . desktop-package-clean                            # reclaims ~2.5 GB + the .app
```

**Unpushed work:** none. Everything is on `origin/main` as of this handoff. Note that
`git push origin main` is still an entry in m11's `external_writes_required`, so the
`complete` transition will refuse until the ledger is balanced with
`--set external_writes_authorized` / `external_writes_completed` — pushing does not record
itself, and CLAUDE.md §4.4 makes each push its own confirmation.

**Worktrees:** several `.claude/worktrees/agent-*` from this session's dispatches remain on
disk with their branches. They are safe to prune once their commits are confirmed merged
(`git log --oneline main..worktree-agent-<id>` should be empty).

**Model prerequisites for m11's inherited launch proof:** both pinned revisions must already
be in the operator's external HF cache — the probe runs `HF_HUB_OFFLINE=1`, so a missing
snapshot fails rather than downloading. Never export `ARXMCP_CONTACT_EMAIL` for a server
run; the config has `extra="forbid"` and crashes on it.

## 7. Key values you'll need (copy-paste reference)

    program roadmap:      plans/desktop-distribution-roadmap.md     # prose, not roadmap.yaml
    m11 ADR:              .claude/docs/adr-desktop-data-root-selection.md    # Proposed
    m15 ADR:              .claude/docs/adr-desktop-bundle-assembly.md        # Accepted + amended
    m11 base SHA:         ea06449
    session range:        751f59d..0625325   (25 commits; 24 pushed)
    assembled artifact:   apps/desktop/target/release/bundle/macos/arXMCP.app
    payload inside app:   Contents/Resources/arxmcp-desktop-child/
    onedir (m7):          var/desktop-package/dist/arxmcp-desktop-child/
    gate env vars:        DESKTOP_SUPERVISOR_BIN, ARXMCP_FIXTURE_SIDECAR,
                          DESKTOP_PACKAGE_GATE, DESKTOP_BUNDLED_MODEL_GATE,
                          DESKTOP_BUNDLE_GATE     # all five must be in _DESKTOP_GATE_ENV
    tauri pin:            2.11.5 (workspace Cargo.toml, `=` exact)
    tauri-cli pin:        2.11.4 (version-pinned, NOT hash-pinned — stated at the constant)
    declared floors:      Rust minos 14.0 · frozen executables minos 11.0 (unreconciled)
