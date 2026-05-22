# Research Brief 2 — verification-feedback-m2
## Lean REPL subprocess harness + ARXMCP_ENABLE_LEAN gate

**Researcher-2 focus:** Contract/discipline sources, failure-mode analysis, in-codebase cross-check.

---

## 1. Contract / Discipline Sources

### 1.1 Spike note (verification-feedback-spike-2.md) — verbatim requirements

The spike established six mandatory implementation requirements:

> **1. Resolve the toolchain exe path explicitly.** On Windows,
> `asyncio.create_subprocess_exec` does **not** PATH-search a bare name
> (`"lake"` → `FileNotFoundError [WinError 2]`). m2 must spawn the REPL with
> the **absolute path** to `lake.exe` (or the built `repl` exe). A new
> `Config` field (e.g. `ARXMCP_LAKE_PATH` / `ARXMCP_LEAN_REPL_*`) should hold
> it, default-resolved from `~/.elan/bin` / `PATH` at startup.

> **2. Run mode.** `lake exe repl` with **`cwd` = the repl package directory** —
> `lake` sets `LEAN_PATH` for the package.

> **3. Protocol.** Commands: a JSON object then a blank line. Responses: a JSON
> object terminated by a blank line. Reader must accumulate stdout lines
> until a blank line, then `json.loads`.

> **4. Unicode.** Proof states contain non-ASCII (the turnstile `⊢` U+22A2, …).
> Any Windows-console tooling around it must force UTF-8 stdout.

> **5. Lean is a system dependency, not a pip dep.** `pyproject.toml` cannot
> declare it. m2's `ARXMCP_ENABLE_LEAN` flag must default OFF; a
> `requires_lean_repl` pytest marker skips Lean-dependent tests when the
> toolchain/repl is absent.

> **6. Toolchain-version coupling.** The repl pins its own `lean-toolchain`
> (`v4.30.0-rc2`); a paper-corpus / autoformalizer targeting a different Lean
> version is a separate concern.

The spike also confirmed: subprocess spawn cost ≈ instant; per-command round-trips
sub-second (0.39–0.61 s for simple snippets). The non-blocking asyncio round-trip
works end-to-end.

### 1.2 Threat model (08-security-observability-ops.md) — Lean sandbox model

The existing LaTeXML sandbox (Threat 3) is the template for Lean:

> - LaTeXML runs in a **subprocess with a hard timeout** (5 minutes).
> - Filesystem write whitelist (only the per-paper output directory).
> - No network access from the LaTeXML subprocess.
> - On macOS: `sandbox-exec` profile. On Linux: seccomp + landlock. In Docker:
>   `--read-only`, `--security-opt no-new-privileges`, dedicated user.

For Lean: the timeout must be shorter (Lean elaboration is bounded; 30 s is
generous for a single snippet). The temp-dir isolation ensures a malicious Lean
snippet cannot write to the arXMCP corpus, caches, or the LanceDB index.

### 1.3 Server lifecycle (06-mcp-server-design.md) — startup contract

> **Startup:** load embedder into memory; load reranker only when
> `ARXMCP_ENABLE_RERANK=true`; ... **No symlink resolution.**

> **Shutdown:** drain in-flight requests with a 30-second deadline; close
> LanceDB and Kùzu cleanly; flush metrics.

The lifespan in `server/main.py` uses the pattern:
`await Resources.startup(config)` → `yield` → cleanup in `finally`.

### 1.4 CLAUDE.md §8 — the prewarm-as-background-task gotcha

Section 8 of CLAUDE.md does NOT contain an explicit §8 prewarm-background-task
note — the numbered gotchas cover faiss/PyTorch segfault, Kùzu archival, etc. The
background-task discipline is instead encoded in the existing code: `Resources.startup`
uses `loop.run_in_executor(None, _get_model)` for the BGE-M3 load so the
blocking model load is offloaded to the thread pool, NOT blocking the event loop.
This is the discipline m2 must replicate: any Lean subprocess spawn must be
awaited via `asyncio.create_subprocess_exec` (non-blocking), NOT via a
synchronous subprocess call in startup.

---

## 2. Failure-Mode Analysis

### FM-1: Subprocess not reaped on shutdown — orphan/zombie

**Trigger:** Server receives SIGTERM / uvicorn shuts down; lifespan `finally` block
does not call `proc.terminate()` + `proc.wait()` before returning.

**Observable symptom:** `lake.exe` / REPL process continues consuming RAM and CPU
after `arxmcp-server` exits. On Linux: zombie in process table. On Windows: orphaned
process visible in Task Manager.

**Mitigation:** The lifespan `finally` block must explicitly `proc.terminate()`
then `await asyncio.wait_for(proc.wait(), timeout=5.0)`. If wait times out,
escalate to `proc.kill()`. Mirror the `IngestTaskTracker.shutdown()` pattern
already in the lifespan (lines 382–384 of `server/main.py`).

### FM-2: ARXMCP_ENABLE_LEAN=true but no toolchain — loud vs. silent failure

**Trigger:** Operator sets `ARXMCP_ENABLE_LEAN=true` on a machine where
`ARXMCP_LAKE_PATH` is unresolvable (no `~/.elan/bin/lake.exe`, not in PATH).

**Observable symptom:** If the startup fails silently or degrades, `/readyz` returns
200 but calls to `lean_verify` (m3) will fail with opaque errors.

**The precedent is unambiguous.** `server/resources.py` line 358–360:
> `if config.enable_rerank:` → `reranker_model = await _load_reranker_or_raise()`
> Raises `RerankerUnavailableError` if load fails.

The docstring quotes synthesis D6: _"trust the operator's choice; refuse to start."_
`ARXMCP_ENABLE_LEAN=true` with an absent or unresolvable Lean toolchain must raise
`LeanUnavailableError(ResourceStartupError)` — the server must refuse to start.
The opposite (log a warning and serve with `lean_verify` disabled) contradicts
the established precedent and would produce confusing behavior.

**Mitigation:** Add `LeanUnavailableError(ResourceStartupError)`. During
`Resources.startup`, when `enable_lean=True`, resolve `lake_path` explicitly. If
the path is None or the binary is not executable, raise `LeanUnavailableError`
with a message naming the expected path. This mirrors `RerankerUnavailableError`.

### FM-3: Subprocess spawn blocks the lifespan from yielding

**Trigger:** m2 implementation calls `subprocess.Popen(...)` (synchronous) or
awaits `proc.communicate()` (awaits completion of a long-running command) inline
in the lifespan before the `yield`.

**Observable symptom:** `/healthz` never responds during startup; Docker
healthcheck times out and restarts the container in a loop. The MCP session
manager's `run()` context never opens.

**The gotcha in practice:** `asyncio.create_subprocess_exec` itself is
non-blocking — it returns immediately after fork+exec. The failure mode is NOT
spawn itself but sending a startup probe command and awaiting its response
inline. If that probe blocks (e.g. Lean takes 10 s to load its kernel on first
invocation), the entire lifespan is blocked at `yield`.

**Mitigation:** Two options, with the better one being Option B:
- Option A: Spawn the process in startup, immediately `yield`, then send a
  "hello probe" command in a background task post-yield. Lean is ready for the
  first m3 tool call when the background task completes. The m2 brief says
  "no first-call cold-start race" — so this option needs a readiness flag.
- Option B (recommended): Spawn via `asyncio.create_subprocess_exec` in startup
  (instant), send NO inline probe command. The REPL process starts in under
  1 ms; Lean's kernel loads lazily on the first command. m2 does NOT need to
  send a warmup command — the spike confirmed that first-command latency is
  0.39–0.61 s, acceptable for a researcher tool. The "no cold-start race" AC
  means no deferred first-call spawn, NOT that a warmup probe is required.

### FM-4: First-call cold-start race if startup is deferred to first use

**Trigger:** Implementation chooses lazy init — the REPL process is not spawned
at lifespan startup, only on the first `lean_verify` call (m3).

**Observable symptom:** The first tool call from any agent session races with
the Lean process spawn. If two concurrent first calls arrive simultaneously,
both may attempt to spawn the subprocess, creating two REPL processes. Only one
gets assigned to `app.state.lean_repl`; the other is leaked.

**Mitigation:** The m2 brief AC2 is explicit: _"no first-call cold-start race."_
Spawn the subprocess in the lifespan startup (pre-yield), not on first use.

### FM-5: Subprocess hangs / command never returns — deadlock

**Trigger:** A Lean snippet triggers infinite elaboration (e.g. `#check Nat.rec`
in a pathological context, or a sorry-heavy proof with deeply nested terms).
The server awaits `proc.stdout.readline()` forever.

**Observable symptom:** The `lean_verify` MCP tool call (m3) hangs indefinitely.
The asyncio event loop is blocked on the subprocess read. Other tool calls
continue to work (separate event loop tasks), but the hung task holds the REPL
handle indefinitely.

**Mitigation:** All subprocess reads must be wrapped in `asyncio.wait_for(...,
timeout=N)`. The spike note measured sub-second round trips for simple snippets;
a 30 s timeout is the Lean-sandbox cap. The sandbox sub-design must specify
this timeout explicitly (AC3 of the m2 brief).

### FM-6: stdout/stderr pipe buffers fill and deadlock

**Trigger:** Lean elaboration produces a very large error message (e.g. a type
mismatch in a deeply parameterized type produces thousands of lines of structured
data). If the server reads stdout but ignores stderr, and stderr fills its 64 KB
OS pipe buffer, the subprocess is blocked writing to stderr → the subprocess
cannot make progress → stdout is never written → the server's stdout reader
blocks → deadlock.

**Observable symptom:** Server hangs on a specific input with no timeout error
(unless the overall timeout fires). The deadlock is input-dependent and hard to
reproduce.

**Mitigation:** Always drain stderr concurrently. Either:
- Open stderr with `asyncio.subprocess.DEVNULL` (discard), OR
- Drain it via a background `asyncio.Task` reading `proc.stderr` into a buffer.
The first option is simpler and correct for m2 (we only need stdout responses);
stderr from Lean is diagnostic, not protocol. Log stderr at DEBUG.

### FM-7: `requires_lean_repl` marker mis-defined or not enforced — Lean tests run on CI

**Trigger:** The marker is declared in `pyproject.toml` but tests are not
decorated with it, OR the marker is declared but `conftest.py` does not install
a skip condition for it when the Lean binary is absent.

**Observable symptom:** Lean-dependent tests run on CI (where there is no Lean
toolchain), fail with `FileNotFoundError`, and break `make test`.

**Mitigation:**
- Declare `requires_lean_repl` in `pyproject.toml` `[tool.pytest.ini_options]
  markers` (following the pattern of `requires_model`, `requires_latexmlc`).
- In `tests/conftest.py`, add a `pytest_collection_modifyitems` hook that
  inspects `config.lean_binary_path` (or just checks if the binary is
  executable) and adds `pytest.mark.skip` to every `requires_lean_repl` item
  when the toolchain is absent.
- Every test that exercises the REPL harness must be decorated with
  `@pytest.mark.requires_lean_repl`.

The existing `requires_latexmlc` marker in `pyproject.toml` line 191 is the
exact pattern to follow:
> `"requires_latexmlc: tests that invoke the real `latexmlc` binary (E10_S04 drift detector integration tests). Skipped by default; opt-in via `pytest -m requires_latexmlc`."`)

---

## 3. In-Codebase Cross-Check

### 3.1 Config pattern (server/config.py)

`Config` uses `pydantic-settings` with `env_prefix="ARXMCP_"` and
`extra="forbid"`. Adding `enable_lean: bool = False` and
`lake_path: Path | None = None` follows the pattern of `enable_rerank: bool = False`.

**Critical:** `_scan_unknown_arxmcp_env_vars` in `server/main.py` lines 255–266
walks `os.environ` and rejects any `ARXMCP_*` key not declared on `Config`.
Any new env var (`ARXMCP_ENABLE_LEAN`, `ARXMCP_LAKE_PATH`, `ARXMCP_LEAN_REPL_DIR`)
must be declared on `Config` BEFORE this scan runs, or startup fails for any
operator who sets the new var.

### 3.2 Lifespan pattern (server/main.py)

The lifespan has a proven pattern for conditional startup resources:

```python
# line 357-360 in resources.py:
reranker_model: Any | None = None
if config.enable_rerank:
    reranker_model = await _load_reranker_or_raise()
```

The Lean REPL must follow the same shape inside `Resources.startup`:
```python
lean_repl: Any | None = None
if config.enable_lean:
    lean_repl = await _spawn_lean_repl_or_raise(config)
```

The lifespan's `finally` block must be extended to tear down the REPL
process. **Order of operations:** tear down the REPL before
`NotebooksStore.close()` and before `Resources.shutdown()`, analogous to how
`IngestTaskTracker.shutdown()` is called first (lines 382–384).

### 3.3 Pytest markers (pyproject.toml lines 188–193)

The `markers` list in `[tool.pytest.ini_options]` currently has four entries.
`requires_lean_repl` must be added as a fifth. The `requires_latexmlc` entry
(line 191–192) is the literal template:

```toml
"requires_latexmlc: tests that invoke the real `latexmlc` binary (E10_S04 drift detector integration tests). Skipped by default; opt-in via `pytest -m requires_latexmlc`. Requires LaTeXML installed locally (`brew install latexml` / `apt install latexml`).",
```

The Lean equivalent:
```toml
"requires_lean_repl: tests that invoke the real Lean 4 REPL subprocess (verification-feedback-m2+). Skipped by default when the Lean toolchain is absent; opt-in via `pytest -m requires_lean_repl` with ARXMCP_ENABLE_LEAN=1 and a resolved ARXMCP_LAKE_PATH.",
```

### 3.4 Contradiction with FM-3 analysis

The existing `Resources.startup` uses `loop.run_in_executor(None, _get_model)`
to offload blocking model loads. **This is NOT needed for Lean:** `asyncio.create_subprocess_exec`
is itself a coroutine that resolves non-blockingly. The implementation must NOT
wrap the subprocess spawn in `run_in_executor` (it would add no benefit and
would obscure the async discipline). The blocking concern for Lean is reading
subprocess output, not spawning the process.

### 3.5 Sandbox sub-design location (AC3)

The milestone requires a sandbox sub-design committed under `.claude/docs/`.
The existing LaTeXML threat entry in `08-security-observability-ops.md` (Threat 3)
is the model. The sub-design document should be at:
`.claude/docs/lean-sandbox-design.md`

---

## 4. Open Questions

1. **Warmup probe vs. lazy first command:** Should m2 send a trivial
   `{"cmd": "#check True"}` probe command immediately after spawn to force
   Lean's kernel to load? This guarantees `/readyz` semantics (the REPL is
   truly warm) but adds ~0.5 s to startup. Given the spike's sub-second
   measurements, this seems acceptable — but the brief AC does not mention
   `/readyz` changes for Lean. Should `ARXMCP_ENABLE_LEAN=true` add Lean
   REPL readiness to `/readyz`?

2. **ARXMCP_LEAN_REPL_DIR vs. ARXMCP_LAKE_PATH:** The spike identified two
   separate config needs: the path to the `lake` binary AND the path to the
   built REPL package directory (for `cwd`). Are these two Config fields, or
   one (e.g. `ARXMCP_LEAN_REPL_DIR` that we derive `lake` from via
   `~/.elan/bin`)?

3. **macOS path resolution:** The spike ran on Windows. On macOS, `elan` installs
   to `~/.elan/bin/lake`. Does default PATH resolution work via `shutil.which("lake")`
   on macOS, or does the same explicit-path requirement apply?

4. **Repl-dir ownership:** Where does the built `leanprover-community/repl` package
   live? The spike stored it at `~/lean-repl-spike/repl/`. For a shared deployment
   or Docker image, should this be vendored into the repo, or is it always an
   operator-provided path via `ARXMCP_LEAN_REPL_DIR`?

5. **Memory cap mechanism:** The Lean sandbox sub-design mentions a memory cap.
   On macOS, `resource.setrlimit(resource.RLIMIT_AS, ...)` is the POSIX mechanism.
   On Windows, `JobObject` is required. Does m2 attempt cross-platform memory
   limiting, or is this documented as a future concern (consistent with LaTeXML
   Threat 3 which mentions it but defers Docker enforcement)?

6. **`extra="forbid"` on Config:** Adding `ARXMCP_LEAN_REPL_DIR` and
   `ARXMCP_LAKE_PATH` as new Config fields makes them declared. But if an operator
   sets `ARXMCP_LAKE_PATH` on a server where `ARXMCP_ENABLE_LEAN=false`, the var
   is accepted (declared) but silently unused. Is this acceptable, or should a
   validator warn?

---

## 5. External Writes the Implementation Will Require

1. **`server/config.py`** — Add `enable_lean: bool = False`,
   `lake_path: Path | None = None`, `lean_repl_dir: Path | None = None`.

2. **`server/resources.py`** — Add `lean_repl: Any | None = None` field on
   `Resources`. Extend `Resources.startup` with the conditional
   `_spawn_lean_repl_or_raise` call. Add `LeanUnavailableError(ResourceStartupError)`.
   Extend `Resources.shutdown` to terminate and await the REPL process.

3. **`server/main.py`** — Extend the lifespan `finally` block to tear down the
   REPL process before `NotebooksStore.close()`.

4. **`pyproject.toml`** — Add `requires_lean_repl` to `[tool.pytest.ini_options]
   markers`.

5. **`tests/conftest.py`** — Add `pytest_collection_modifyitems` hook that
   skips `requires_lean_repl` tests when the Lean binary is absent. Alternatively,
   add a `lean_repl_available` autouse fixture with a skip guard.

6. **`.claude/docs/lean-sandbox-design.md`** — One-page sub-design: subprocess
   timeout (30 s), filesystem isolation to a `tempfile.mkdtemp()` working dir,
   memory cap (documented as platform-specific; POSIX `RLIMIT_AS`, Windows
   JobObject deferred), stderr drain strategy, stdin/stdout UTF-8 encoding,
   no-network constraint.

7. **`tests/test_lean_repl.py`** (or `tests/lean/`) — m2 unit tests for:
   (a) `ARXMCP_ENABLE_LEAN=false` → no subprocess spawned, all 7 tools work;
   (b) startup with absent toolchain when `enable_lean=True` → raises
   `LeanUnavailableError`;
   (c) `@pytest.mark.requires_lean_repl` — JSON protocol round-trip tests for
   the three response shapes (ok, compile-error, sorry-goal).

---

*Brief written by researcher-2. Disagreement from researcher-1 on the fail-loud
vs. degrade question (FM-2) or the warmup-probe question (Open Q1) is USEFUL —
both positions should be represented for the implementer.*
