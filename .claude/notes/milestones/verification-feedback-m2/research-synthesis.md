# Research Synthesis — verification-feedback-m2

**Milestone:** Lean REPL subprocess harness + `ARXMCP_ENABLE_LEAN` gate.
**Merged from:** research-brief-1 (in-codebase), research-brief-2 (contract + failure modes). The two briefs agree on every load-bearing point; divergences (warmup probe, field count) are resolved below.
**Date:** 2026-05-22

---

## 1. Verified context (both briefs agree)

- **`enable_rerank` is the mirror pattern.** `server/config.py`: `enable_rerank: bool = False` — a plain bool, no validator (pydantic-settings coerces `true/false/1/0`). `server/resources.py`: `if config.enable_rerank: reranker_model = await _load_reranker_or_raise()` — conditional startup; `RerankerUnavailableError` if the load fails ("trust the operator's choice; refuse to start", synthesis D6).
- **Lifespan** (`server/main.py`): `await Resources.startup(config)` → side-effect setup → `async with mcp_server.session_manager.run(): yield` → ordered `finally` teardown (`IngestTaskTracker.shutdown()` is the teardown-ordering model).
- **`_scan_unknown_arxmcp_env_vars`** rejects any `ARXMCP_*` env var not declared on `Config` — every new var must be a `Config` field before any test sets it.
- **Sandbox model:** E13_S03 LaTeXML sandbox (Threat 3, `08-security-observability-ops.md`) — subprocess + hard timeout, filesystem write-whitelist, no network, platform-specific isolation.
- **Spike-2 (`.claude/notes/spikes/verification-feedback-spike-2.md`) is validated and load-bearing:** the REPL-as-asyncio-subprocess approach works; Windows needs the **absolute `lake.exe` path** (no PATH search); run mode is `lake exe repl` with `cwd` = the built repl package dir; JSON-block protocol; sub-second round-trips; Lean is a system dependency.
- **Markers:** `requires_model` / `requires_latexmlc` in `pyproject.toml` `[tool.pytest.ini_options].markers` are the template for `requires_lean_repl`.
- **m2 adds NO MCP tool** — `lean_verify` is m3. The `tools/list` hash, `EXPECTED_TOOL_SCHEMA_SHA256`, `TOOL_SCHEMA_VERSION`, and `EXPECTED_BP1_SHA256` are all **untouched** by m2.

## 2. Decisions (orchestrator synthesis)

1. **Implementation path: INLINE** (orchestrator). ~8 files, no novel architecture beyond standard asyncio subprocess management, no specialist agent registered, not parallelizable.
2. **Config fields (3):** `enable_lean: bool = False`; `lean_repl_dir: Path | None = None` (the built `leanprover-community/repl` package directory — the subprocess `cwd`); `lake_path: Path | None = None` (absolute path to `lake` / `lake.exe`). Two paths, not one — spike-2 finding #1+#2: the `cwd` dir and the `lake` exe are distinct, and `create_subprocess_exec` will not PATH-search a bare name on Windows. Both default `None`; consulted only when `enable_lean=True`.
3. **Fail-loud, not degrade.** `ARXMCP_ENABLE_LEAN=true` with `lean_repl_dir`/`lake_path` unset or unresolvable → raise `LeanUnavailableError` (a `ResourceStartupError` subclass) — the server refuses to start. This mirrors `enable_rerank`/`RerankerUnavailableError` exactly. Both briefs agree (researcher-2 FM-2, researcher-1 OQ4). Degrading-and-serving contradicts the established precedent.
4. **New module `server/lean_repl.py`** — a `LeanRepl` class owning: `spawn()` (`asyncio.create_subprocess_exec(lake_path, "exe", "repl", cwd=lean_repl_dir, stdin=PIPE, stdout=PIPE, stderr=DEVNULL)`); `query(command: dict, timeout: float) -> dict` (JSON-block round-trip wrapped in `asyncio.wait_for`); `close()` (`terminate()` → `await wait_for(wait(), 5.0)` → `kill()` fallback). `Resources` holds only a `LeanRepl | None` reference. The harness includes `query` so it is a *complete, testable* harness — m3's `lean_verify` tool wires onto `LeanRepl.query`, it does not re-implement the protocol.
5. **stderr = DEVNULL** (researcher-2 FM-6) — Lean stderr is diagnostic, not protocol; discarding it removes the pipe-buffer deadlock trap. m3 may revisit if it needs stderr.
6. **Spawn at lifespan startup, pre-`yield`, no inline probe.** `create_subprocess_exec` returns in ~ms; Lean's kernel loads lazily on the first `query` (sub-second per spike-2). "No first-call cold-start race" (AC2) = the process is spawned at startup, NOT lazily on first use — it does NOT require a warmup probe. No `/readyz` change for m2 (the AC don't mention it; keep m2 minimal).
7. **Teardown** in the lifespan `finally` block, before `NotebooksStore.close()` / `Resources.shutdown()`, mirroring `IngestTaskTracker.shutdown()` ordering: `LeanRepl.close()`.
8. **`requires_lean_repl` marker:** registered in `pyproject.toml`; a `tests/conftest.py` `pytest_collection_modifyitems` hook applies `pytest.mark.skip` to every `requires_lean_repl` item when the Lean toolchain does not resolve (no `lake` on PATH and no `ARXMCP_LAKE_PATH`/`ARXMCP_LEAN_REPL_DIR` env). CI and fresh checkouts skip cleanly.
9. **Sandbox sub-design** at `.claude/docs/lean-sandbox-design.md` (AC3) — one page modeled on E13_S03: per-`query` timeout (30 s default, the implemented guard); filesystem isolation (the subprocess `cwd` is the repl dir; a `tempfile`-based working dir for any Lean-emitted artifacts); memory cap documented as **platform-specific** — POSIX `resource.setrlimit(RLIMIT_AS)` via a `preexec_fn` *where available*, Windows JobObject deferred (consistent with E13_S03 deferring Docker enforcement); stderr=DEVNULL; no network (the toolchain caches deps at build time).
10. **`server/lean_repl.py` is NOT consumed by any m2 MCP tool** — that is intentional and called out in the module docstring (m3 wires `lean_verify`). This is a deliberate, documented "wired but not yet surfaced" state, not a stub.

## 3. Implementation plan

| File | Change |
|---|---|
| `server/config.py` | + `enable_lean: bool = False`, `lean_repl_dir: Path \| None = None`, `lake_path: Path \| None = None` |
| `server/lean_repl.py` (new) | `LeanRepl` class (spawn / query / close) + `LeanUnavailableError` + a `resolve_lean_toolchain(config)` helper |
| `server/resources.py` | + `lean_repl: LeanRepl \| None` field; conditional spawn in `startup()`; teardown in `shutdown()` |
| `server/main.py` | lifespan `finally`: tear down `lean_repl` before `Resources`/notebooks teardown (if `Resources.shutdown` doesn't already own it) |
| `pyproject.toml` | + `requires_lean_repl` marker |
| `tests/conftest.py` | + `pytest_collection_modifyitems` hook skipping `requires_lean_repl` when the toolchain is absent |
| `tests/test_lean_repl.py` (new) | flag-off (no spawn, 7 tools unaffected); `LeanUnavailableError` on `enable_lean=True`+unresolved; `@pytest.mark.requires_lean_repl` round-trip tests (ok / compile-error / sorry-goal) |
| `.claude/docs/lean-sandbox-design.md` (new) | the AC3 one-page sub-design |

## 4. Failure modes guarded (research-brief-2)

FM-1 orphan process → `close()` in lifespan `finally` with terminate+wait+kill. FM-2 silent-degrade → `LeanUnavailableError`, refuse to start. FM-3 lifespan-block → spawn only, no inline probe. FM-4 first-call race → spawn at startup not lazily. FM-5 hung command → `query` wraps reads in `asyncio.wait_for(timeout)`. FM-6 stderr deadlock → `stderr=DEVNULL`. FM-7 marker misfire → `conftest.py` collection hook + every Lean test decorated.

## 5. Acceptance-criteria disposition

| AC | Plan |
|---|---|
| AC1 `ARXMCP_ENABLE_LEAN` in config, default false | met |
| AC2 subprocess in async lifespan; no blocking startup; no cold-start race | met (spawn pre-yield, non-blocking, not lazy) |
| AC3 one-page Lean-sandbox sub-design under `.claude/docs/` | met (`lean-sandbox-design.md`) |
| AC4 flag off → no subprocess, 7 tools unchanged | met + tested |
| AC5 `requires_lean_repl` marker; Lean tests skip when binary absent | met (marker + conftest hook) |
| AC6 `make test` green, `ruff` clean | gate — `make` unavailable on this Windows box; project-check fallback `ruff check . && uv run pytest` used; 34 pre-existing Windows/env failures are the baseline (zero-new is the bar). The `requires_lean_repl` round-trip tests will RUN here (Lean toolchain was installed by spike-2). |

## 6. External writes

**None.** Purely local: config fields, a new module, resources/lifespan wiring, a pytest marker + conftest hook, a sandbox doc, tests. `external_writes_required = []`.
