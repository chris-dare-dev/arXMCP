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
| **Process reaping** | `LeanRepl.close` does `terminate()` → bounded `wait()` → `kill()` fallback. Reaping is mandatory: an unreaped child is a zombie (POSIX) / leaked handle (Windows). Called from `Resources.shutdown` inside the lifespan teardown. | **Implemented.** |
| **Filesystem isolation** | The subprocess `cwd` is the built `leanprover-community/repl` package directory (required so `lake` resolves `LEAN_PATH`) — NOT the arXMCP repo or the corpus/index tree. A hostile snippet thus cannot write to `var/arxmcp/`. **m3+:** any Lean-emitted artifact path should be redirected to a per-call `tempfile.mkdtemp()` directory, cleaned on `close`. | **Partial** — `cwd` isolation done; temp-dir redirection is m3+. |
| **Memory cap** | A hard address-space cap. On POSIX this is `resource.setrlimit(RLIMIT_AS, ...)` via a subprocess `preexec_fn`; on Windows it requires a Job Object (`CREATE_BREAKAWAY_FROM_JOB` + `SetInformationJobObject`). | **Deferred** — documented, not implemented. The 30 s per-query timeout is the primary safeguard in m2/m3; the memory cap mirrors E13_S03, which itself defers Docker-level enforcement of the LaTeXML cap. A follow-up milestone adds `RLIMIT_AS` on POSIX. |
| **No network** | The Lean toolchain caches every dependency at `lake build` time; a steady-state `lake exe repl` opens no sockets. No explicit network namespace is applied (consistent with the LaTeXML sandbox, which relies on "the subprocess never opens sockets" rather than a namespace). In Docker, the container's network policy is the backstop. | **By construction.** |
| **System dependency, gated** | Lean is not a pip dependency; `pyproject.toml` cannot declare it. `ARXMCP_ENABLE_LEAN` defaults OFF — the subprocess is spawned only on explicit operator opt-in, and only when `ARXMCP_LAKE_PATH` + `ARXMCP_LEAN_REPL_DIR` resolve. An unresolvable toolchain under `enable_lean=true` is FATAL (`LeanUnavailableError`). | **Implemented.** |

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

## Out of scope for m2

The `lean_verify` MCP tool, the kill-and-respawn-on-timeout recovery loop, the
per-call temp-dir redirection, and the POSIX `RLIMIT_AS` cap are m3+ work. m2
ships the harness (`LeanRepl`: spawn / query / close) and this design; the
harness is gated, reaped, time-bounded, and stderr-safe today.
