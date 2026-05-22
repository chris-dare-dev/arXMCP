# Research Brief — verification-feedback-m2 (researcher-1)

## 1. In-Codebase Context

### server/config.py — enable_rerank as the mirror pattern

`enable_rerank` is a plain `bool` field with `default=False`:

```python
enable_rerank: bool = False
```

No field_validator is needed — pydantic's bool coercion handles
`"true"/"false"/"1"/"0"` via `pydantic-settings` automatically.
`ARXMCP_ENABLE_LEAN` mirrors this exactly: one line, no validator.

The existing path fields (`lancedb_path`, `kuzu_path`, etc.) use
`Path` typed defaults under `var/arxmcp/`. m2 needs two new `Config`
fields:

- `enable_lean: bool = False` — gates the subprocess
- `lean_repl_dir: Path | None = None` — operator-supplied path to the
  built repl package directory (where `lake exe repl` is run from)

The `extra="forbid"` + `_scan_unknown_arxmcp_env_vars` pattern in
`main.py` means both fields MUST be declared on `Config` before any
test or run that sets `ARXMCP_ENABLE_LEAN` — unknown ARXMCP_* vars
raise `ValueError` at startup.

### server/main.py — lifespan insertion point

The lifespan has a clear structure:
1. `Resources.startup(config)` — await, fatal on failure
2. Side-effecting setup (`set_resources`, notebooks store open,
   orphan recovery, `IngestTaskTracker`)
3. `async with mcp_server.session_manager.run(): yield`
4. `finally:` — ordered teardown

**The CLAUDE.md §8 gotcha on prewarm** (gotcha not explicitly in §8,
but in Resources.startup): the reranker warm-up runs as an
`await loop.run_in_executor(None, ...)` call, blocking the lifespan
until warm. m2's Lean REPL startup is different: `create_subprocess_exec`
is `await`-able directly on the event loop, no executor. The REPL process
itself must be spawned inside the lifespan `try:` block (before `yield`)
so it is alive before any request arrives — no first-call cold-start race.

Shutdown (`finally:`) must `proc.terminate()` + `await proc.wait()` (with
timeout) before `Resources.shutdown`. Zombie prevention requires awaiting
the process; orphan prevention requires not skipping the finally block.

### server/resources.py — enable_rerank conditional-startup pattern

```python
reranker_model: Any | None = None  # populated when enable_rerank=True

if config.enable_rerank:
    reranker_model = await _load_reranker_or_raise()
```

m2 mirrors this: a `lean_repl_proc: asyncio.subprocess.Process | None = None`
field on Resources, populated only when `enable_lean=True`. The
subprocess module (`server/lean_repl.py`) should own the spawn/drain
logic; Resources stores only the process reference.

On the disabled path (`enable_lean=False`): `lean_repl_proc = None`,
no subprocess spawned, the 7 existing tools are completely unaffected.

### .claude/notes/08-security-observability-ops.md — E13_S03 sandbox discipline

Threat 3 (LaTeXML on hostile source) defines the sandbox template m2's
Lean sandbox sub-design must mirror:

> **LaTeXML runs in a subprocess with a hard timeout** (5 minutes).
> Subprocess runs as a **separate UID** (Docker user namespace, or
> rootless container with an unprivileged user inside).
> **Filesystem write whitelist** (only the per-paper output directory).
> No network access from the LaTeXML subprocess.
> On macOS: `sandbox-exec` profile. On Linux: seccomp + landlock. In Docker:
> `--read-only`, `--security-opt no-new-privileges`, dedicated user.
> **Never** invoke LaTeXML inside the MCP server process itself.

The Lean REPL sandbox sub-design (AC#3) adapts these constraints:

- **Timeout:** per-command timeout (configurable, default 30 s); the
  REPL process itself is long-lived (reused across commands), but any
  single elaboration must be killed and the process restarted on timeout.
- **Filesystem isolation:** `cwd` is the repl package directory (spike
  finding #2); additional writes must go to a `tempfile.mkdtemp()` dir
  passed as `LEAN_CACHE_DIR` or equivalent. No writes to the arXMCP repo.
- **Memory cap:** `ulimit -v` / `resource.setrlimit(RESOURCE_RLIMIT_AS)`
  inside the subprocess pre-exec hook. On Linux a seccomp profile or
  cgroup is the right mechanism; on macOS a `getrlimit/setrlimit` call in
  the `preexec_fn`. On Windows neither is available — document as known
  limitation; the 30s timeout provides the primary safeguard.
- **No network:** the Lean REPL does not need network access; the toolchain
  caches all deps at build time. No explicit network isolation is possible
  purely with asyncio subprocess, but the subprocess never opens sockets.

### Spike findings — load-bearing constraints (spike-2.md)

These constraints are verbatim requirements:

> 1. **Resolve the toolchain exe path explicitly.** On Windows,
>    `asyncio.create_subprocess_exec` does **not** PATH-search a bare name
>    (`"lake"` → `FileNotFoundError [WinError 2]`). m2 must spawn the REPL
>    with the **absolute path** to `lake.exe` (or the built `repl` exe).
>    A new `Config` field (e.g. `ARXMCP_LAKE_PATH` / `ARXMCP_LEAN_REPL_*`)
>    should hold it, default-resolved from `~/.elan/bin` / `PATH` at startup.
>
> 2. **Run mode.** `lake exe repl` with **`cwd` = the repl package directory**
>    — `lake` sets `LEAN_PATH` for the package.
>
> 5. **Lean is a system dependency, not a pip dep.** `pyproject.toml` cannot
>    declare it. m2's `ARXMCP_ENABLE_LEAN` flag must default OFF; a
>    `requires_lean_repl` pytest marker skips Lean-dependent tests when the
>    toolchain/repl is absent.

---

## 2. Prior Decisions and Lessons

### Recent git log

The last 4 commits form the verification-feedback-m1 triple + a merge:

```
d9af59d Merge branch 'main' of github.com:chris-dare-dev/arXMCP
f22a73b chore(notes): finalize verification-feedback-m1 state -> complete
3e4dcd6 rect(server): close F1-F4 from verification-feedback-m1 critique
(feat commit for m1 was earlier)
```

m2 follows the same three-commit pattern: `feat` → `rect` → `chore`.

### requires_model marker — the mirror pattern for requires_lean_repl

In `pyproject.toml` `[tool.pytest.ini_options]`:

```toml
markers = [
    "requires_model: tests that download / load a real ML model ...",
    "requires_latexmlc: tests that invoke the real `latexmlc` binary ...",
]
```

Usage in `tests/retrieval/test_rerank.py`:

```python
@pytest.mark.requires_model
@pytest.mark.skipif(
    os.environ.get("ARXMCP_RUN_REAL_BGE_RERANKER") != "1",
    reason="set ARXMCP_RUN_REAL_BGE_RERANKER=1 to exercise the real model",
)
```

`requires_lean_repl` follows the same dual-guard pattern:
1. `@pytest.mark.requires_lean_repl` (registered in `pyproject.toml`)
2. `@pytest.mark.skipif(lean_binary_absent(), ...)` where
   `lean_binary_absent()` checks `ARXMCP_LEAN_REPL_DIR` or tries
   `shutil.which("lake")` — whichever the implementer decides. The
   marker name alone does NOT skip; the `skipif` is the skip mechanism.
   The marker is for `pytest -m "not requires_lean_repl"` exclusion.

### CLAUDE.md §7 (stubs) — no conflict

None of the 7 existing tools touch Lean. m2 adds NO new MCP tool (that
is m3). The stub risk is that `lean_repl_proc` on `Resources` is wired
but never used by any tool in m2 — this is intentional per the brief.
Document it in the lean_repl.py module docstring.

### CLAUDE.md §8 gotchas — relevant to m2

- **Pure-ASGI rule / no blocking the event loop:** `asyncio.create_subprocess_exec`
  is non-blocking. `proc.stdin.write` + `proc.stdin.drain()` + `proc.stdout.readline()`
  are all `await`-able. No `loop.run_in_executor` needed for the REPL I/O path.
- **Subprocess cleanup (critical):** the `IngestTaskTracker.shutdown()` pattern
  in `main.py` (cancel in-flight tasks, then close store) is the model.
  For Lean: `proc.terminate()` then `await asyncio.wait_for(proc.wait(), 5.0)`,
  with `proc.kill()` fallback on timeout. Must happen in `finally:` before
  `Resources.shutdown()`.
- **No zombie processes:** if `proc.communicate()` or `proc.wait()` is never
  called, the process becomes a zombie. The shutdown path MUST `await proc.wait()`.
- **Windows PATH:** spike finding #1 — absolute path to `lake.exe` required
  on Windows. On macOS/Linux `shutil.which("lake")` works if elan is on PATH,
  but an explicit config field is safer and more operator-controllable.

### Conflict check

No conflict between brief and codebase. The brief's scope (no MCP tool,
subprocess harness only) is consistent with the code: `lean_verify` is m3.
The `_scan_unknown_arxmcp_env_vars` function will reject `ARXMCP_ENABLE_LEAN`
until the field is declared on `Config` — so the Config change must land in
the same commit as any test that sets that env var.

---

## 3. External Sources

The spike already validated `asyncio.create_subprocess_exec` for this
exact use case. No additional external research needed.

**asyncio subprocess lifecycle correctness (stdlib docs):**
- `asyncio.create_subprocess_exec` returns `asyncio.subprocess.Process`.
- Pipes (`stdout=PIPE`, `stdin=PIPE`) buffer; if the buffer fills and
  neither side reads, deadlock results. For the REPL (one command in →
  one response out per round-trip) this is not an issue as long as
  responses are read promptly.
- `proc.wait()` must be called after `proc.terminate()`; without it the
  process becomes a zombie (POSIX) or the handle leaks (Windows).
- `asyncio.wait_for(proc.wait(), timeout=5.0)` with `proc.kill()` in the
  `except TimeoutError` branch is the correct cleanup sequence.
- `proc.returncode` is `None` while the process is running; checking it
  after `terminate()` without `wait()` is a race.

**No MCP spec changes implied:** m2 adds no tool to the MCP surface.
The `tools/list` hash must NOT change. `EXPECTED_TOOL_SCHEMA_SHA256` in
`tests/test_server_tool_schema.py` stays as-is.

---

## Open Questions

1. **Where does the built `repl` package live?** The spike built it at
   `~/lean-repl-spike/repl/` — OUTSIDE the arXMCP repo. m2 does NOT
   build the repl; it requires the operator to pre-build it and point
   `ARXMCP_LEAN_REPL_DIR` at the directory. The implementer must decide:
   should there be a separate `ARXMCP_LAKE_PATH` for the `lake.exe`
   binary, or should `ARXMCP_LEAN_REPL_DIR` suffice (with `lake` looked
   up via `shutil.which` or from the elan shim)? Recommendation: one
   field `ARXMCP_LEAN_REPL_DIR: Path | None` pointing to the built repl
   directory; `lake.exe` is discovered via `shutil.which("lake")` from
   within the subprocess environment. Spike finding #1 says PATH-search
   fails on Windows for `create_subprocess_exec` — but if we `cwd` into
   the repl dir and use `lake` from elan's shim, elan may have put itself
   on PATH. Needs a test on Windows.

2. **What module owns the REPL subprocess?** The brief implies
   `server/lean_repl.py`. Confirm: does the `LeanRepl` class live there,
   with `Resources` holding only a reference? This is consistent with the
   `RerankPhase` pattern (`server/retrieval/rerank.py` owns the model;
   `Resources` holds a reference).

3. **How does `requires_lean_repl` skip?** Two options:
   - `skipif(shutil.which("lake") is None, ...)` — checks the binary
   - `skipif(os.environ.get("ARXMCP_LEAN_REPL_DIR") is None, ...)` —
     checks the config
   The config-var check is more explicit and matches the
   `ARXMCP_RUN_REAL_BGE_RERANKER=1` pattern. Implementer should decide
   before writing tests.

4. **`lean_repl_dir` field type.** Should it be `Path | None` (None =
   disabled/auto-discover) or always `Path` (with a sentinel default)?
   `None` is cleaner but requires a model validator to reject
   `enable_lean=True` + `lean_repl_dir=None` at config-parse time
   (analogous to how `enable_rerank=True` + missing model raises
   `RerankerUnavailableError` at startup, not at config parse).

5. **Lean REPL process restart on elaboration timeout.** The Lean REPL
   has no per-command timeout built in — a hung elaboration blocks the
   process indefinitely. m2 must either (a) kill and restart the process
   on timeout, or (b) wrap each round-trip with `asyncio.wait_for`. If
   the process is killed, the next command must spawn a fresh process.
   Does m2 implement this or defer to m3? Brief says "subprocess timeout"
   in the sandbox design — implementer must decide if m2 is the home.

---

## External Writes the Implementation Will Require

| type | target | why |
|---|---|---|
| (none) | — | m2 is purely local: Config field, Resources field, lean_repl.py module, lifespan wiring, pytest marker, sandbox doc under .claude/docs/. No push, PR, ticket, API call, or infra mutation required. |
