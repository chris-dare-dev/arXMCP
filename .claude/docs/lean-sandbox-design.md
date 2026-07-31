# Lean REPL sandbox sub-design

**Milestone:** verification-feedback-m2 (AC3). **Status:** harness shipped; the
guards below are partly implemented, partly documented-for-m3+.

This is the security/resource sub-design for the managed Lean 4 REPL subprocess
(`server/lean_repl.py`). It is modeled on the **E13_S03 LaTeXML sandbox**
(Threat 3, `.claude/notes/08-security-observability-ops.md`): a subprocess that
runs externally-influenced input must be bounded in time, isolated on the
filesystem, denied the network, and capped in memory.

## Threat surface

The Lean REPL elaborates Lean 4 source. In the m2→m3 pipeline that source is
agent-authored (the autoformalizer / tactician produce it; `lean_verify`, m3,
submits it). Lean's elaborator is a powerful, Turing-complete metaprogramming
engine — a hostile or buggy snippet can: loop forever (runaway elaboration);
allocate unbounded memory; attempt filesystem writes; in principle attempt
network access via an FFI. The REPL process is therefore treated as an
untrusted compute sandbox, exactly as LaTeXML is.

## Guards

| Guard | Mechanism | m2 status |
|---|---|---|
| **Per-query timeout** | Every `LeanRepl.query` round-trip is wrapped in `asyncio.wait_for(timeout=DEFAULT_QUERY_TIMEOUT_S)` (30 s default). A runaway elaboration trips the timeout → `LeanReplError`; m3 will additionally kill+respawn the process on timeout. | **Implemented.** |
| **stderr isolation** | The subprocess is spawned with `stderr=DEVNULL`. Lean stderr is diagnostic, not protocol; discarding it removes the pipe-buffer deadlock (a large stderr write blocking the subprocess while the parent reads only stdout). | **Implemented.** |
| **Single-flight I/O** | One REPL process, one stdin/stdout stream — `LeanRepl` serialises round-trips with an `asyncio.Lock` so two concurrent queries cannot interleave JSON on the wire. | **Implemented.** |
| **Process reaping** | `LeanRepl.close` does `terminate()` → bounded `wait()` → `kill()` → bounded `wait()` (both reaps are `asyncio.wait_for`-capped at `_CLOSE_GRACE_S`, so `close()` cannot hang the lifespan shutdown drain even if a parent-side transport is wedged). Reaping is mandatory: an unreaped child is a zombie (POSIX) / leaked handle (Windows). Called from `Resources.shutdown` inside the lifespan teardown. | **Implemented.** |
| **Filesystem isolation** | The subprocess `cwd` is the built `leanprover-community/repl` package directory (required so `lake` resolves `LEAN_PATH`) — NOT the arXMCP repo or the corpus/index tree. A hostile snippet thus cannot write to `var/arxmcp/`. **m3+:** any Lean-emitted artifact path should be redirected to a per-call `tempfile.mkdtemp()` directory, cleaned on `close`. | **Partial** — `cwd` isolation done; temp-dir redirection is m3+. |
| **Memory cap** | A hard address-space cap. On POSIX this is `resource.setrlimit(RLIMIT_AS, ...)` via a subprocess `preexec_fn`; on Windows it requires a Job Object (`CREATE_BREAKAWAY_FROM_JOB` + `SetInformationJobObject`). | **Deferred** — documented, not implemented. The 30 s per-query timeout is the primary safeguard in m2/m3; the memory cap mirrors E13_S03, which itself defers Docker-level enforcement of the LaTeXML cap. A follow-up milestone adds `RLIMIT_AS` on POSIX. |
| **No network** | The Lean toolchain caches every dependency at `lake build` time; a steady-state `lake exe repl` opens no sockets. No explicit network namespace is applied (consistent with the LaTeXML sandbox, which relies on "the subprocess never opens sockets" rather than a namespace). In Docker, the container's network policy is the backstop. | **By construction.** |
| **System dependency, gated** | Lean is not a pip dependency; `pyproject.toml` cannot declare it. `ARXMCP_ENABLE_LEAN` defaults OFF — the subprocess is spawned only on explicit operator opt-in, and only when `ARXMCP_LAKE_PATH` + `ARXMCP_LEAN_REPL_DIR` resolve. An unresolvable toolchain under `enable_lean=true` is FATAL (`LeanUnavailableError`). | **Implemented.** |
| **Environment-snapshot growth** | Every REPL command records a new immutable `CommandSnapshot` (and every `sorry`/tactic a `ProofSnapshot`) into an append-only array; ids are array indices, never freed. The in-process tree grows unbounded and is released only by the timeout kill+respawn or an operator restart. The upstream protocol has no per-env eviction command, so bounding the tree is a pooled-worker-lifecycle concern. See "Environment-snapshot accumulation (F7)" below. | **Documented — R3 m7 owns the fix.** |

## Process lifecycle

```
Resources.startup(config)
  └─ if config.enable_lean:  LeanRepl.spawn_from_config(config)   # instant; kernel loads lazily
yield  (server serves requests; m3's lean_verify calls LeanRepl.query)
Resources.shutdown()
  └─ LeanRepl.close()  → terminate → wait(5s) → kill fallback
```

The subprocess is spawned at lifespan startup (pre-`yield`), never lazily on
first use — that closes the first-call cold-start race (m2 AC2). The spawn is
non-blocking (`asyncio.create_subprocess_exec` returns after fork+exec); Lean's
kernel loads lazily on the first `query` (sub-second per spike-2), so the spawn
does not block the lifespan `yield` and `/healthz` stays responsive.

## Environment-snapshot accumulation (F7)

**Finding.** F7 from the `lean-verify-continuation-m1` adversary critique
([`critique-adversary.md`](../notes/milestones/lean-verify-continuation-m1/critique-adversary.md)).
With env / proof-state continuation tokens now a first-class `lean_verify`
feature (env reuse — pay `import Mathlib` once, then reuse it warm), a
long-lived REPL process accumulates immutable environment snapshots without
bound. **Not a soundness issue — a resource-exhaustion one.**

**Growth model (verified against the pinned REPL source, 2026-07-25).** The
built `leanprover-community/repl` on this workstation
(`~/lean-repl-spike/repl`, toolchain `leanprover/lean4:v4.30.0-rc2`) keeps all
state in two append-only arrays (`REPL/Main.lean` `structure State`):

```
cmdStates   : Array CommandSnapshot := #[]
proofStates : Array ProofSnapshot   := #[]
```

`recordCommandSnapshot` sets `id := cmdStates.size` then `cmdStates.push` — the
returned env id **is** the array index, and the array only ever grows. **Every**
command records a snapshot: a `def`, a failed `theorem`, even a read-only
`#check` advances the counter (measured — research-synthesis §1). Each snapshot
pins a full `Environment`; for a Mathlib-resident REPL the imported Mathlib
environment dominates (the F7 finding reports ~3.1 GB RSS for such a process;
the default core-only REPL is small). Nothing frees an individual snapshot.

**Per-env eviction is not available in the protocol.** The REPL's entire
command surface is seven inputs (`REPL/Main.lean` `inductive Input`): `cmd`,
`file`, `proofStep`, `pickleEnvironment`, `unpickleEnvironment`,
`pickleProofSnapshot`, `unpickleProofSnapshot`. There is **no** drop / free /
release / gc command, and because ids are array indices, removal would break id
stability even if one were added. `pickleEnvironment` serializes a snapshot to
disk but does **not** free the in-memory copy; `unpickle` *appends* a new one.
⇒ a bounded-live-env LRU (critique scope option (a)) is infeasible without
forking the REPL internals — **rejected**.

**Interim mitigation (what holds today).**

- The REPL is **off by default** (`ARXMCP_ENABLE_LEAN` unset); env reuse is
  **opt-in** (a caller must pass an `env` token); single-user workstation
  (CLAUDE.md §4.1) bounds the blast radius.
- The per-query-timeout **kill+respawn** (`lean_verify` handler) frees the whole
  tree — but only when a query actually times out, so it is partial relief.
- **In-product signal (lean-repl-observability-m1).** Two `/metrics` gauges make
  the growth observable: `arxmcp_lean_repl_env_snapshots` (a proxy for the
  append-only snapshot-tree size — the count of successful REPL round-trips this
  generation) and `arxmcp_lean_repl_age_seconds` (worker age). Both read 0 when
  the REPL is disabled and drop back toward 0 after a respawn. **Ops threshold:**
  on a long-lived **Mathlib-resident** REPL, a steadily climbing
  `arxmcp_lean_repl_env_snapshots` with no respawn is the F7 growth signal —
  restart the server between heavy verification sessions to reclaim the tree.
  (Direct child-process RSS is NOT surfaced this milestone — `psutil` is not a
  dependency and there is no portable Windows RSS reader; the snapshot-count
  proxy is the shipped signal. An RSS gauge can be revisited if R3 m7 needs an
  RSS-based recycle trigger.)
- **Operator restart** (`make up`) remains the reset lever until R3 m7's pooled
  workers recycle automatically.

**Forward owner: R3 m7.** The real fix — bounding the live-env tree — belongs in
the pooled-worker lifecycle layer, **not** the `lean_verify` handler. A respawn
*policy* bolted onto the handler (or a standalone timer built now) would (i)
silently invalidate the warm envs this milestone shipped, since a respawn mints
a new `generation` and expires every outstanding continuation token, and (ii) be
rebuilt at m7. Recorded as an explicit m7 requirement in the R3
verification-contract brief
([`R3-verification-contract.md`](../roadmap-briefs/R3-verification-contract.md),
KR8 + m7 + Inherited findings). Levers m7 can use: recycle a pooled worker on a
live-snapshot-count / age budget; `pickleEnvironment` the hot named env to disk
and `unpickle` it into a fresh worker across a recycle (preserving the warm
import while resetting the tree); and consume the REPL live-snapshot / worker-age
gauge **shipped** by `lean-repl-observability-m1`
([`.claude/roadmap/lean-repl-observability.md`](../../.claude/roadmap/lean-repl-observability.md)) —
that read-only telemetry landed *ahead* of this gate (it adds no
untrusted-execution surface). The env-tree *bounding* itself (recycling +
pickle-migration) stays gated behind R3's trust gate (m2–m5) — pooling/
performance work is forbidden before it.

## Out of scope for m2

The `lean_verify` MCP tool, the kill-and-respawn-on-timeout recovery loop, the
per-call temp-dir redirection, and the POSIX `RLIMIT_AS` cap are m3+ work. m2
ships the harness (`LeanRepl`: spawn / query / close) and this design; the
harness is gated, reaped, time-bounded, and stderr-safe today.
