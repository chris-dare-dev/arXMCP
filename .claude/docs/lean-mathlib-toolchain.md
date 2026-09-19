# Mathlib REPL toolchain — build record, measurements, sandbox decision

**Provenance:** Stage-2 slice `arx-d1` (workstreams.md §WS-D D-1; RISKS.md spike
S1, P0), executed 2026-07-04 on the authoritative Windows workstation
(Ryzen 7 7800X3D, 32 GB DDR5, RTX 5070, Windows 11 Home 26200 — finding 212).
This document is the ground-truth record for the environment
`ARXMCP_LEAN_REPL_DIR` points at, the numbers that calibrate AC-D.4's
budgets, and the Windows sandbox decision D-2/D-7 build on.

Related: `.claude/docs/lean-sandbox-design.md` (per-query timeout + stderr
discipline — unchanged by this work), `server/lean_repl.py` (spawn contract),
`.claude/notes/spikes/verification-feedback-spike-2.md` (the no-mathlib
prior-art spike at `C:/Users/cedar/lean-repl-spike/`).

---

## 1. What was built, and where

```
C:/Users/cedar/Documents/Personal Projects/Source Code/_toolchains/mathlib-repl/
├── repl/          leanprover-community/repl @ f0a88bf ("chore: bump toolchain
│                  to v4.30.0-rc2 (#155)") — copied from the validated
│                  lean-repl-spike checkout, WITH its natively-built
│                  .lake/build/bin/repl.exe (reused: trace hashes matched,
│                  `lake build repl` completed in 2 s)
└── project/       the Lake package ARXMCP_LEAN_REPL_DIR points at
    ├── lean-toolchain          leanprover/lean4:v4.30.0-rc2
    ├── lakefile.toml           requires mathlib (git tag v4.30.0-rc2)
    │                           + REPL (path ../repl)
    └── .lake/packages/         mathlib @ 5450b53e5d (= tag v4.30.0-rc2),
                                batteries, aesop, Qq, proofwidgets, Cli,
                                importGraph, LeanSearchClient, plausible
```

The environment lives deliberately **outside both repos** (multi-GB,
machine-local, not versionable). Nothing in the arXMCP tree changed except
docs and tests.

**Why a wrapper package instead of the in-tree `repl/test/Mathlib` skeleton:**
`server/lean_repl.py::LeanRepl.spawn` runs `lake exe repl` with
`cwd=ARXMCP_LEAN_REPL_DIR`. `lake exe` resolves executables from the
workspace's dependency closure and sets `LEAN_PATH` for every package in it —
so a package requiring *both* mathlib and REPL gives the spawned REPL mathlib
oleans on `LEAN_PATH` with **zero server-code changes**. The upstream skeleton
(`repl/test/Mathlib/lakefile.toml`, which pinned the matched mathlib rev this
build uses) requires mathlib only; running `lake exe repl` there would not
resolve the REPL executable, and the upstream `lake env ../../.lake/build/bin/repl`
invocation is a different spawn contract than the one `lean_repl.py` ships.

## 2. Server wiring

```
ARXMCP_ENABLE_LEAN=true
ARXMCP_LAKE_PATH=C:\Users\cedar\.elan\bin\lake.exe
ARXMCP_LEAN_REPL_DIR=C:\Users\cedar\Documents\Personal Projects\Source Code\_toolchains\mathlib-repl\project
```

`ARXMCP_LAKE_PATH` must stay the **elan shim** (`~/.elan/bin/lake.exe`), not a
toolchain-dir `lake.exe`: the shim dispatches on `project/lean-toolchain`, so
the env keeps working even when elan's default channel drifts (it already
drifted to v4.31.0 during the Stage-1 audit — finding 212 §2.3).

## 3. Measured numbers (2026-07-04, this workstation)

Setup (one-time):

| Step | Duration | Notes |
|---|---|---|
| `lake update` | 3 min 34 s | clones mathlib + 8 deps; mathlib's post-update hook downloaded + decompressed the **8,297-file olean cache** inside this window (Azure origin) |
| `lake exe cache get` (explicit re-run) | 15 s | "No files to download" — confirms the hook already fetched; **prebuilt cache IS published for the `v4.30.0-rc2` tag** (closes finding 212 OQ2) |
| `lake build repl` | 2 s | reused the spike's natively-built `repl.exe` (same toolchain, traces matched) |
| Disk footprint | ≈ 8 GB | `_toolchains/mathlib-repl/` total; C: had 321 GB free after |

Runtime (via `server.lean_repl.LeanRepl` — the exact server spawn path):

| Operation | Cold | Warm OS cache | RSS |
|---|---|---|---|
| `lake exe repl` spawn | < 1 s | < 1 s | — |
| `import Mathlib.Algebra.Group.Defs` + theorem | 6.4 s | ≈ 1–6 s | — |
| `import Mathlib.Analysis.SpecialFunctions.Sqrt` + theorem | **> 30 s (handler TIMEOUT)** | 8.7–14 s | — |
| `import Mathlib.NumberTheory.Real.Irrational` + theorem | — | 5.6 s | — |
| **full `import Mathlib`** | **33.4 s** | **15.5–16.0 s** | **3,085 MiB peak (steady state)** |
| post-warm query in the full-Mathlib env | 0.01 s | 0.01 s | — |

Cold-vs-warm correction (2026-07-04, second session of the day): the
first `Mathlib.Analysis.SpecialFunctions.Sqrt` import of a session, with
a cold OS file cache, exceeded `DEFAULT_QUERY_TIMEOUT_S` (30 s) through
`handle_lean_verify` — the handler returned `lean_status: "timeout"` and
kill+respawned exactly as designed. The identical query re-run warm
passed in 13.8 s wall (test total). The earlier "per-module imports fit
comfortably" claim held only for a warm cache; it is corrected below and
`tests/test_lean_repl_mathlib.py` now pre-warms the olean closure via a
raw `LeanRepl.query` (explicit 240 s timeout) before its 30 s-budget
handler tests.

Consequences:

1. **The 4 GiB per-REPL budget holds** (repo default `lean_rlimit_as_bytes`);
   the 2–3-concurrent-REPL pool budget on 32 GB (finding 212 §2.4) is
   confirmed with a measured 3.1 GiB data point, closing finding 212 OQ1.
2. **Imports through `lean_verify` are cache-sensitive**: a full
   `import Mathlib` times out even warm-adjacent (33 s cold, 15–16 s warm
   vs the 30 s budget), and larger per-module towers (the Analysis chain)
   time out on a COLD OS file cache while fitting warm (5–14 s). D-2/D-7
   must pre-warm (Kimina-style pickled envs, or an import-closure touch at
   server startup — the test fixture's approach) and/or raise the
   first-query timeout before agents send heavy imports.
3. **Fresh-env imports accumulate RSS in one process**: three module-import
   commands (each a fresh REPL env) grew a second REPL process to 5.7 GiB.
   Long-lived REPLs need a respawn cadence (or env reuse via the REPL's `env`
   ids) — a D-7 pooling design input.
4. Post-warm queries are effectively free (10 ms) — pre-warmed workers are
   the right shape for best-of-n throughput, exactly as finding 05 R7
   anticipated.

## 4. Windows sandbox decision (D-1 record)

**Context.** POSIX `RLIMIT_AS` is a silent no-op on win32
(`server/lean_repl.py:196-202` logs a warning and runs the REPL uncapped);
this workstation is the authoritative runtime (finding 212 §2.9). Three lanes
were verified available in Stage 1 (finding 212 §2.2): WSL2 Debian
(15 GB VM cap + working RLIMIT_AS, but **no elan/lean toolchain in-distro
today**), Docker Desktop 29.1.3 (WSL2 backend), and a native Job Objects
patch (already sketched as deferred work in `lean_repl.py` +
`lean-sandbox-design.md`).

**Decision for D-1: run the REPL natively on Windows, uncapped, with the
existing 30 s per-query timeout + kill/respawn as the only backstop.**

**Grounding:**

- The measured worst-case RSS (3.1 GiB full-Mathlib steady state, 5.7 GiB
  after pathological env accumulation) is far from box-threatening on 32 GB,
  and the handler's timeout → kill+respawn path bounds runaway duration.
- Every prior-art artifact on this box is native-Windows (`repl.exe` built
  natively; the spike validated the asyncio-subprocess protocol natively).
  WSL2 would require installing elan in-distro, duplicating the ~3 GB
  toolchain + the 8 GB environment, and re-validating the spawn contract
  through a `wsl.exe` indirection `lean_repl.py` does not support today —
  disproportionate for a spike whose job is to make `lean_verify` mathlib-
  capable.
- Docker adds the same duplication plus image/volume plumbing, for isolation
  D-1 does not yet need (loopback-only server, operator-submitted snippets).

**Follow-up (owned by D-2/WS-A, per RISKS MA-11):** the native lane still has
NO hard memory cap. The committed follow-up is the **Job Objects patch** to
`lean_repl.py` (`JOBOBJECT_EXTENDED_LIMIT_INFORMATION.ProcessMemoryLimit`),
which caps the subprocess without changing the spawn topology. WSL2 remains
the fallback hard-cap lane if the Job Objects patch stalls; the AC-D.4
acceptance test (memory-hungry snippet killed without taking down the server)
is the gate either way. Revisit trigger: any move to agent-submitted untrusted
snippets at scale, or a measured REPL RSS approaching the 4 GiB budget.

## 5. Rebuild-from-nothing runbook

```powershell
# Prereqs: elan (any recent), git. ~10 GB disk. ~5 min on 100 Mbit.
cd "C:/Users/cedar/Documents/Personal Projects/Source Code/_toolchains"
git clone https://github.com/leanprover-community/repl mathlib-repl/repl
git -C mathlib-repl/repl checkout f0a88bf   # toolchain v4.30.0-rc2 pin
# create mathlib-repl/project/{lakefile.toml,lean-toolchain} per §1
cd mathlib-repl/project
# On Windows, inject long-path tolerance for lake's git clones:
$env:GIT_CONFIG_COUNT=1; $env:GIT_CONFIG_KEY_0='core.longpaths'; $env:GIT_CONFIG_VALUE_0='true'
& "$env:USERPROFILE\.elan\bin\lake.exe" update       # ~4 min (cache rides the post-update hook)
& "$env:USERPROFILE\.elan\bin\lake.exe" exe cache get  # idempotent verify, ~15 s
& "$env:USERPROFILE\.elan\bin\lake.exe" build repl     # seconds-to-minutes
```

Smoke test (exercises the exact server spawn contract):

```powershell
# from the arXMCP repo root, venv python:
$env:ARXMCP_LAKE_PATH="$env:USERPROFILE\.elan\bin\lake.exe"
$env:ARXMCP_LEAN_REPL_DIR='C:\Users\cedar\Documents\Personal Projects\Source Code\_toolchains\mathlib-repl\project'
python -m pytest tests/test_lean_repl_mathlib.py -m requires_lean_repl -v
```

## 6. Pin/upgrade policy

The rc2 matched pair (`lean4 v4.30.0-rc2` + `mathlib v4.30.0-rc2` + repl
`f0a88bf`) was chosen because it was the known-good in-tree pin (finding 212
§2.3) — and it worked first try, cache included. Per RISKS MA-10, the
rc2-vs-stable decision was explicitly deferred INTO this spike: recommendation
is to **stay on the rc2 pair for D-2/D-4 development** (verdict replayability
beats freshness; D-2 will pin toolchain+rev+transcript hash into every result)
and revisit as a deliberate matched-pair bump once the KAT suite (D-4) exists
to regression-gate an upgrade. Upgrading = edit `project/lean-toolchain`,
`lakefile.toml` rev, and the repl checkout to a matching tag, then rerun §5;
never move one pin without the others.
