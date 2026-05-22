# Implementation Summary — verification-feedback-m2

**Summary.** A managed Lean 4 REPL subprocess harness (`server/lean_repl.py`)
is added, gated by a new `ARXMCP_ENABLE_LEAN` env var (default off). When
enabled, exactly one `LeanRepl` is spawned inside the async lifespan resource
init and reaped on shutdown; when off, nothing is spawned and the 7 existing
MCP tools are untouched. This is the *harness only* — the `lean_verify` MCP
tool is m3.

**Commit range:** `d9af59db4c3019194b77df42c7b328ae93ea8f0e..c9df7f1` (feat
commit `c9df7f1`, GPG-signed, 11 files, 1463 insertions).

**Implementation path:** INLINE (orchestrator, main session). The brief
suggested a `security-reviewer` specialist; the work is a single new module +
a Config triple + a Resources hook + tests + a sandbox doc — no novel
architecture warranting a registered specialist agent. Sandbox discipline is
applied inline and audited in Phase 3.

## Acceptance criteria status

| AC | Status | Notes |
|---|---|---|
| AC1 — `ARXMCP_ENABLE_LEAN` in `server/config.py`, default `false` | ✅ met | Added `enable_lean: bool = False`, plus `lean_repl_dir: Path \| None = None` and `lake_path: Path \| None = None` (the toolchain paths the gate needs). |
| AC2 — REPL managed inside the async `lifespan`; no blocking startup; no cold-start race | ✅ met (see D1) | Spawned in `Resources.startup` step 6e (the lifespan's resource-init coroutine) and closed in `Resources.shutdown`. `asyncio.create_subprocess_exec` returns after fork+exec — non-blocking; Lean's kernel loads lazily on first `query`, so the lifespan `yield` is not blocked. Spawn is pre-`yield`, never lazy → no first-call cold-start race. |
| AC3 — one-page Lean-sandbox sub-design under `.claude/docs/` | ✅ met | `.claude/docs/lean-sandbox-design.md`: per-query timeout, stderr isolation, single-flight I/O, process reaping, filesystem isolation, memory cap (deferred-with-rationale), no-network, gated-system-dependency. Modeled on the E13_S03 LaTeXML sandbox. |
| AC4 — `enable_lean=false` → no subprocess, 7 tools unchanged | ✅ met | `Resources.startup` step 6e is `if config.enable_lean:` — guarded. The flag-off path imports nothing from `server.lean_repl` and spawns no process. Pinned by `TestConfigGate` in `tests/test_lean_repl.py`. |
| AC5 — `requires_lean_repl` marker; Lean tests skip cleanly when the binary is absent | ✅ met | Marker registered in `pyproject.toml`. `tests/test_lean_repl.py` Tier 2 carries `@pytest.mark.requires_lean_repl` + a `skipif` on `ARXMCP_LAKE_PATH`/`ARXMCP_LEAN_REPL_DIR` — the 5 real-toolchain tests skip cleanly with no Lean installed. |
| AC6 — `make test` green, `ruff check .` clean | ✅ met (caveat) | `make` is unavailable on this Windows workstation → project-check fallback `ruff check . && uv run python -m pytest`. `ruff check .` clean repo-wide. Full suite: m2 base commit `d9af59d` is itself a merge of `origin/main` carrying **52 pre-existing failures** (Windows-platform + a merge-introduced preview/upload-route set); m2 introduces **zero new failures** — verified by a `git stash` full-suite run at the base commit. `test_lean_repl.py` is 11/11 with a real Lean 4 toolchain (spike-2 install); 5/11 of those skip cleanly without it (AC5). |

## New / changed test paths

- `tests/test_lean_repl.py` — **new.** Tier 1 always-run: `TestConfigGate`
  (the three Config fields + defaults), `TestFailLoudContract`
  (`LeanUnavailableError` ⊂ `ResourceStartupError`; raises on unset paths /
  missing `lake` binary / missing repl dir). Tier 2 `@requires_lean_repl`:
  ok / error / `sorry` JSON round-trips, `close()` reaping, query-after-close.

## Files changed

- `server/config.py` — added `enable_lean`, `lean_repl_dir`, `lake_path`
  (after `rerank_model_sha`).
- `server/lean_repl.py` — **new.** `LeanRepl` (`spawn` / `spawn_from_config`
  / `query` / `close` / `is_running`); `LeanUnavailableError`
  (⊂ `ResourceStartupError`), `LeanReplError` (⊂ `RuntimeError`).
- `server/resources.py` — added `lean_repl: Any | None = None` dataclass
  field; `Resources.startup` step 6e conditional spawn; `Resources.shutdown`
  close.
- `pyproject.toml` — added the `requires_lean_repl` pytest marker.
- `.claude/docs/lean-sandbox-design.md` — **new.** AC3 sandbox sub-design.
- `.claude/notes/spikes/verification-feedback-spike-2.md` — **new.** The
  prerequisite spike (Lean 4 install + real-REPL validation; the
  absolute-`lake`-path-on-Windows finding) committed alongside the harness.
- `.claude/notes/milestones/verification-feedback-m2/` — research briefs +
  synthesis + state.json.

## Deviations from the synthesis design

- **D1 — REPL lifecycle lives in `server/resources.py`, not literally in
  `server/main.py`.** The brief's AC2 says "managed inside the async
  `lifespan` in `server/main.py`". In this codebase the lifespan delegates
  all resource init/teardown to `Resources.startup` / `Resources.shutdown`;
  `main.py`'s `lifespan` does nothing but call those. Putting the spawn in
  `Resources` follows the established pattern for every other managed
  resource (the BGE-M3 model, the reranker, LanceDB, Kùzu). AC2's intent —
  async, lifespan-scoped, non-blocking, no cold-start race — is fully met.
- **D2 — three Config fields, not one.** The brief names only
  `ARXMCP_ENABLE_LEAN`. A bare boolean cannot resolve a toolchain, so
  `lean_repl_dir` + `lake_path` were added alongside it (mirroring how
  `enable_rerank` is paired with `rerank_model` / `rerank_model_sha`).
- **D3 — no `conftest.py` autouse hook for the Lean skip.** A per-test
  `skipif` keyed on the two env vars was used instead — the exact pattern
  `requires_model` / `ARXMCP_RUN_REAL_BGE_RERANKER` already uses. Keeps the
  skip logic local to the one test file that needs it.
- **D4 — memory cap (`RLIMIT_AS`) documented, not implemented.** The
  sandbox doc defers the hard address-space cap to a follow-up milestone
  (POSIX `setrlimit` via `preexec_fn`; Windows needs a Job Object). The
  30 s per-query timeout is the implemented primary guard. This mirrors
  E13_S03, which itself defers Docker-level enforcement of the LaTeXML cap.

## External writes required

**None.** Purely local: one new source module + a new test file + three
Config fields + a Resources hook + two `.claude/` docs + a pyproject marker.
No push, no PR, no ticket, no infra mutation, no external API call.
`external_writes_required = []`.
