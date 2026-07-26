# Research synthesis — lean-repl-observability-m1

Fan-in of `research/brief-1.md` (explore) + `research/brief-2.md` (general).
Both converge; no contradictions. Implementation is **inline** (S: ~5–6 files,
well under 300 LOC / 5-source-file thresholds; the test + doc files are not
"novel architecture").

## Affected files (deduped, edit order)

1. `server/lean_repl.py` — `import time`; in `__init__` (not `spawn()`, so the
   direct-construction test path at `tests/test_lean_repl.py:178-180` works)
   add `self._spawn_monotonic = time.monotonic()` and
   `self._env_snapshot_count = 0`, mirroring the `generation` field idiom
   (unconditional plain attrs). Add read-only properties `env_snapshot_count`
   (int) and `age_seconds` (float, computed live like `is_running`). Increment
   `self._env_snapshot_count += 1` inside `query()`'s existing
   `async with self._io_lock:` block, strictly AFTER `_round_trip` succeeds and
   BEFORE `return` — so it never counts the already-exited raise, the
   `LeanReplTimeoutError` path, or `_round_trip`'s EOF/non-JSON raises. No new
   lock (the `_io_lock` already serialises all `query()` calls).
2. `server/metrics.py` — two UNLABELED gauges `arxmcp_lean_repl_env_snapshots`
   and `arxmcp_lean_repl_age_seconds` (template: `CACHE_BYTES_GAUGE` /
   `PROCESS_START_TIME_GAUGE`); `refresh_lean_repl_metrics(lean_repl)` mirroring
   `refresh_cache_metrics` BUT with an **explicit `.set(0.0)` on the `None`
   branch** (see decision D2); `reset_lean_repl_metrics_for_tests()`;
   `if TYPE_CHECKING: from server.lean_repl import LeanRepl` (keep it off the
   load path); add all new names to `__all__`.
3. `server/health.py` — one line in `refresh_metrics_from_singleton_state`
   (~593-597, beside the `refresh_cache_metrics` call):
   `from server.metrics import refresh_lean_repl_metrics;
   refresh_lean_repl_metrics(getattr(resources, "lean_repl", None))`.
4. `tests/test_lean_repl.py` — harness tests: counter increments once per
   successful fake-proc `query()`; does NOT increment on the timeout / EOF /
   non-JSON / already-exited paths; a brand-new instance starts at 0 (the AC2
   respawn-reset, tested at harness level via two `_FakeProc` instances, not by
   racing a real timeout); `age_seconds` ≥ 0 and non-decreasing.
5. `tests/test_server_metrics.py` — new `TestLeanReplMetrics` (call
   `refresh_lean_repl_metrics(None)` ⇒ both gauges 0; with a fake/real repl ⇒
   values reflect state); **add `reset_lean_repl_metrics_for_tests()` to the
   `reset_all_metrics` fixture (125-146)** — else module-level gauge state leaks
   across tests. Optional end-to-end: metric names appear in rendered `/metrics`.
6. `.claude/docs/lean-sandbox-design.md` — AC7: replace the "no in-product
   signal today" caveat (currently ~99-105) with a pointer to the two shipped
   gauge names + a restart-threshold ops note; refresh the now-stale
   future-tense cross-ref in the "Forward owner: R3 m7" paragraph (~115-120).

**Confirmed NO-touch:** `server/config.py` (no env var), `server/resources.py`
(`lean_repl: Any | None` unchanged), `server/handlers/lean_verify.py` (no
behavior change; respawn path already mints a fresh instance),
`server/main.py` (scrape funnels through `refresh_metrics_from_singleton_state`),
`tests/test_handlers_lean_verify.py` (its `_FakeLeanRepl` duck-type never hits
`/metrics`), `server/tools.py` / `server/prompts.py` (no schema surface).

## Acceptance criteria (traced to the brief's 7)

1. `ARXMCP_ENABLE_LEAN=true` + N successful cmd-mode calls ⇒
   `arxmcp_lean_repl_env_snapshots` monotonically non-decreasing;
   `arxmcp_lean_repl_age_seconds` positive + increasing. (`.set(...)`, not `.inc`.)
2. Kill+respawn ⇒ snapshot gauge drops toward 0 (new generation), age resets.
   Falls out for free (per-instance state on a fresh `LeanRepl`).
3. `ARXMCP_ENABLE_LEAN` unset ⇒ both gauges present and read **0**, no crash /
   no missing series. Requires explicit `.set(0)` on the `None` branch (D2).
4. `EXPECTED_TOOL_SCHEMA_SHA256` (`tests/test_server_tool_schema.py`) AND
   `EXPECTED_BP1_SHA256` (**`tests/test_prompts.py`**, not server/prompts.py)
   byte-identical — structurally guaranteed: `/metrics` is a disjoint ASGI mount.
5. RSS gauge: **deferred this milestone** (D3) — the honest AC5 branch on this
   Windows host is "absent, no new hard dependency".
6. `make test` green (ruff + pytest) with the new tests above.
7. Doc § F7 updated (AC7).

## external_writes_required (verbatim from brief-2)

- `git push origin main` — land the milestone's `feat` + `rect` + `chore`
  commit triple on `main` (here: fast-forward/merge the worktree branch
  `claude/laughing-goldstine-b8ea4f` onto `main`, then push). **USER-GATED** at
  the Phase-4 boundary (CLAUDE.md §4.4 — re-ask each time). No other external
  write is in scope: no network calls, no deploys, no package publish, no
  external API mutation.

## Open questions / decisions (resolved)

- **D1 (proxy choice):** round-trip counter (not max-id). Simpler,
  protocol-agnostic, over-counts by ≤1 only in the adversarial unknown-id
  replay (safe direction for a growth gauge). Both briefs concur.
- **D2 (disabled path):** explicit `.set(0.0)` on `None`, NOT the
  `refresh_cache_metrics` no-op — gauges are module-level and persist across the
  pytest session, so a no-op would fail AC3 after any prior test set a value.
- **D3 (RSS gauge):** deferred — `psutil` absent repo-wide, no `/proc` on
  Windows, no `ctypes` precedent; revisit if R3 m7 needs an RSS recycle trigger.
- **D4 (`/status` + ops report):** brief item 4 is optional; only `/status`
  could be "cheap". Treat both as out-of-scope-unless-trivial; not a scope miss.
- **D5 (metrics module):** use `server/metrics.py` (sibling of the other
  scrape-refreshed gauges), not `server/observability/metrics.py`.
