# Rectification Summary — onboarding-uplift-m4

**Rect commit:** 636e5f7
**Base commit:** 071d4b1
**Date:** 2026-05-31T00:00:00Z
**Branch:** main (cherry-picked from worktree-agent-a0ec232fef4c7fe49)

## Findings closed

### F1 CRITICAL — refresh_metrics crash in bootstrap mode
- `server/health.py`: wrapped `CORPUS_VERSION_GAUGE.set(resources.corpus_info.version)` and `CORPUS_CHUNK_COUNT_MARKER.set(resources.corpus_info.chunk_count)` in a `if resources.corpus_info is not None:` guard. Prometheus leaves the gauges absent in bootstrap mode (correct behavior).
- `server/main.py`: added `if not getattr(resources, "bootstrap_mode_active", False):` guard around `refresh_metrics_from_singleton_state(resources)` in the lifespan. Belt-and-suspenders guard — the internal fix in health.py is the primary fix.
- New test: `TestLifespanBootstrapMode::test_refresh_metrics_skips_corpus_info_when_none`.

### F2 HIGH — /readyz returns 503 in bootstrap mode (synthesis D1 not implemented)
- `server/health.py` `readyz`: added bootstrap branch before the `not warm` 503 check — returns 200 with `{"status": "bootstrap", "bootstrap_mode_active": True, "warm": {...}}`.
- `server/health.py` `compute_health_status`: added bootstrap branch returning `status="warn"`, `http_code=200`, `summary="bootstrap | awaiting first ingest"`.
- New tests: `TestReadyzBootstrapMode::test_readyz_returns_bootstrap_status_in_bootstrap_mode`, `TestStatusBootstrapMode::test_status_returns_warn_in_bootstrap_mode`.

### F3 HIGH — Bootstrap envelope isError=true dead at MCP wire
- `server/tools.py`: changed `_build_bootstrap_envelope` to return `mcp.types.CallToolResult(content=[TextContent(...)], structuredContent=structured, isError=True)` instead of a plain dict. Added `TYPE_CHECKING` import for `CallToolResult`.
- Updated `TestBuildBootstrapEnvelope` to assert `isinstance(result, CallToolResult)` + `result.isError is True` + `result.structuredContent` shape.
- New test: `test_build_bootstrap_envelope_wire_isError_is_true`.

### F4 HIGH — on_success_callback has zero test coverage
- New test class `TestOnSuccessCallback` (4 tests, ~120 LOC):
  1. `test_callback_fires_on_exit_code_zero` — callback invoked exactly once on exit 0.
  2. `test_callback_not_fired_on_nonzero_exit` — callback NOT invoked on exit 1.
  3. `test_callback_exception_logged_not_propagated` — exception logged at ERROR, task completes normally.
  4. `test_main_closure_passes_through_to_late_bind` — closure in main.py calls `resources.late_bind(config)`.
- No production code change.

### F5 HIGH — late_bind silently fails on enable_rerank=True + bootstrap path
- `server/resources.py` `late_bind`: added lazy reranker load before `RerankPhase` construction:
  ```python
  if config.enable_rerank and self.reranker_model is None:
      self.reranker_model = await _load_reranker_or_raise()
  ```
- New test: `TestLateBindWithRerank::test_late_bind_with_enable_rerank_loads_reranker_lazily`.

### F6 MEDIUM — `_corpus_ready_event` is dead code (no awaiter)
- `server/resources.py`: deleted `_corpus_ready_event: asyncio.Event` dataclass field and the `self._corpus_ready_event.set()` call in `late_bind`. Updated comment to note the removal.
- Updated `research-synthesis.md` §3 D2 with implementation deferral paragraph.
- Updated test assertions (removed `assert stub._corpus_ready_event.is_set()` and similar).

### F7 MEDIUM — late_bind partial-mutation leaks set_cache global on rerank failure
- `server/resources.py`: moved `set_cache(retrieval_cache)` to AFTER `RerankPhase(...)` construction (previously before). "Build everything, then publish atomically."
- New test: `TestLateBindCacheNotLeaked::test_late_bind_failure_does_not_leak_cache_global`.

### F8 MEDIUM — Bootstrap hint text hardcodes 127.0.0.1:7733
- `server/tools.py`: added `ui_url: str = "http://127.0.0.1:7733/ui/"` kwarg to `_build_bootstrap_envelope`. Updated `_wrap_with_observability` to pass `f"http://{_r.config.bind_host}:{_r.config.bind_port}/ui/"`.
- New test: `TestBootstrapEnvelopeBind::test_bootstrap_envelope_text_uses_configured_bind`.

### F9 MEDIUM — Synthesis D5 phase-sentinel scope-slip
- Doc-only fix: amended `research-synthesis.md` §3 D3 with a "Further deferral" paragraph explaining why even the 10-LOC `phase=downloading_model` sentinel was deferred from m4 to m5.

### IS1 MEDIUM — .PHONY comment label "FIRST-TIME?" vs help label "FIRST TIME?"
- `Makefile:6`: changed `# FIRST-TIME?` → `# FIRST TIME?` (drop hyphen to match `make help` section header).

## Deferred findings

- F10 (LOW) — explicit `bootstrap_mode_active=False` in normal startup. Orchestrator records under `deferred_findings`.
- F11 (LOW) — late_bind docstring on first-query BGE-M3 latency. Orchestrator records under `deferred_findings`.
- IS2 (LOW) — Makefile help epoch tag stale. Orchestrator records under `deferred_findings`.

## Test count delta

- Before: 16 tests in `tests/test_bootstrap_mode.py`
- After: 27 tests (+11 new tests for F1–F8 findings)
- Full suite: all new tests pass; no pre-existing passing tests broken.

## Files changed

- `server/health.py` — F1 corpus_info None-guard, F2 bootstrap branches in readyz + compute_health_status
- `server/main.py` — F1 bootstrap_mode guard on refresh_metrics call
- `server/resources.py` — F5 lazy reranker load, F6 delete _corpus_ready_event, F7 move set_cache after RerankPhase
- `server/tools.py` — F3 CallToolResult return type, F8 ui_url kwarg, TYPE_CHECKING import
- `tests/test_bootstrap_mode.py` — all new and updated tests
- `Makefile` — IS1 hyphen fix
- `.claude/notes/milestones/onboarding-uplift-m4/research-synthesis.md` — F6 D2 deferral, F9 D3 deferral
- `.claude/notes/milestones/onboarding-uplift-m4/critique-adversary.md` — rectification status appended
- `.claude/notes/milestones/onboarding-uplift-m4/critique-infra-safety.md` — rectification status appended
