# E06_S01 Implementation Summary

**Branch:** `claude/gallant-blackburn-b89422`
**Files changed:** 10 (8 new, 2 modified files + pyproject.toml + Makefile + server/README.md)
**Commit (planned):** see Phase 4 footer once committed.

## Files

| Path | New / Modified | Purpose |
|---|---|---|
| `server/config.py` | NEW | `pydantic-settings` Config with `bind_host` / `bind_port` / concurrency / `result_byte_cap` validators. Rejects non-loopback `bind_host` at parse. |
| `server/resources.py` | NEW | Lifecycle container: corpus marker → LanceDB handle → BGE-M3 eager load → optional reranker → semaphores → generic `Singleflight` class. `CorpusNotIngestedError` + `RerankerUnavailableError` (REFUSE TO START on either). |
| `server/health.py` | NEW | `/healthz`, `/readyz` routes + Prometheus gauges/counters + `refresh_metrics_from_singleton_state` helper. |
| `server/_mcp_mount.py` | NEW | Thin adapter for the `mcp` library's `streamable_http_app()` mount. Configures `streamable_http_path = "/"` then mounts at `/mcp`. |
| `server/main.py` | NEW | FastAPI app + `lifespan` context manager + `BodySizeCapMiddleware` + Prometheus mount + MCP mount. `create_app(config)` factory + module-level `app` for `uvicorn server.main:app`. |
| `server/README.md` | modified | Refresh from "Empty until E01_S08" → full module index + run instructions + two-tier concurrency note. |
| `tests/test_server_startup.py` | NEW | 23 tests across 7 classes locking every AC + the Singleflight class. Mocks BGE-M3 by default; env-gated real-model path mirrors `tests/test_embedder.py`. |
| `docker/Dockerfile.server` | NEW | Multi-stage (builder → runtime). Non-root UID 1000. `tini` PID 1. EXPOSE 7733. HEALTHCHECK on `/readyz`. |
| `Makefile` | modified | `make up` (was stub) → `python -m uvicorn server.main:app --host 127.0.0.1 --port 7733 --lifespan on`. `make help` row updated. |
| `pyproject.toml` | modified | Added 5 deps: `mcp>=1.27,<2`, `fastapi>=0.115`, `uvicorn[standard]>=0.30`, `pydantic-settings>=2.4`, `prometheus-client>=0.20`. |

## Decisions exercised from research-synthesis.md

| Decision | Where it landed |
|---|---|
| D1 — `server/resources.py` COEXISTs with `query_encoder.py` | `resources.py` re-uses `_get_model` / `_get_tokenizer` for eager warmup; calls `shutdown_executor` from its own shutdown |
| D2 — Two-tier concurrency: semaphore (8) + singleflight | `Resources.embed_semaphore` + `query_encoder`'s in-flight dict |
| D3 — Eager model load at startup (gates `/readyz`) | `Resources.startup` awaits `_get_model()` + `_get_tokenizer()` BEFORE returning |
| D4 — `bind_host` validator rejects non-loopback at parse | `Config.reject_non_loopback` field validator |
| D5 — Cold-start corpus marker → REFUSE TO START | `Resources.startup` raises `CorpusNotIngestedError` on `read_corpus_version() is None` |
| D6 — `enable_rerank=true` w/o model → REFUSE TO START | `_load_reranker_or_raise()` always raises pre-E07 |
| D7 — MOCKED tests by default; env-gated real path | `mocked_bge_m3` fixture monkeypatches `_get_model` / `_get_tokenizer`; real path gated via existing `tests/test_embedder.py` precedent |
| D8 — No `pytest-asyncio`; use `asyncio.run` per existing project pattern | tests use `asyncio.run()` inside sync test bodies |
| D9 — Pin `mcp==1.27.*`; isolate the mount in `_mcp_mount.py` | `pyproject.toml` pins `mcp>=1.27,<2`; `_mcp_mount.mount_mcp(app, server)` is the SOLE call site |
| D10 — All 5 deps added to base list | `pyproject.toml` updated |
| D11 — Four metrics: `arxmcp_corpus_version`, `_resources_warm`, `_process_start_time_seconds`, `_embed_singleflight_dedup_total` | `health.py` defines all four; `refresh_metrics_from_singleton_state` keeps them fresh at scrape time |
| D12 — `make up` wired; `server/README.md` refreshed | both done |
| D13 — 256 KB cap as middleware; exempt `/healthz` `/readyz` `/metrics` | `BodySizeCapMiddleware` in `main.py` |
| D14 — Dockerfile multi-stage; non-root; `tini`; HEALTHCHECK on `/readyz` | `docker/Dockerfile.server` matches |
| D15 — Path-traversal validation deferred to E06's tool boundary | no startup-time path validation added |

## Test results

- **610 passed**, 3 skipped (1 pre-existing + 1 env-gated BGE-M3 + 1 cold-start eval), ruff clean
- 23 new tests in `tests/test_server_startup.py` covering all 6 ACs + the `Singleflight` class + startup-refusal paths

## Acceptance-criteria mapping

| AC | Status | Where verified |
|---|---|---|
| `pytest tests/test_server_startup.py` reaches `/readyz` 200 within 30s | **met** | `TestReadinessTransition::test_readyz_200_when_warm` (mocked-resources fast path) |
| `GET /healthz` returns 200 before readiness | **met** | `TestHealthEndpoints::test_healthz_returns_200` + `test_healthz_works_before_resources_attach` |
| `GET /readyz` returns 503 until embedder + LanceDB are warm, then 200 | **met** | `TestReadinessTransition::test_readyz_503_when_resources_absent` + `test_readyz_200_when_warm` |
| `ARXMCP_BIND_HOST=0.0.0.0` rejected at config parse | **met** | `TestConfigValidation::test_zero_zero_zero_zero_rejected` (+ `_public_ip_rejected`, `_loopback_*_accepted` siblings) |
| Two server processes on same port → clear error | **met** | `TestPortConflict::test_address_in_use_propagates` (5-second join is the silent-hang detector; uvicorn raises `OSError EADDRINUSE`) |
| `corpus_version` integer logged at startup, matches `corpus-version.json` | **met** | `TestStartupLogging::test_corpus_version_logged_at_startup` (caplog scan for "pinning corpus_version=") + the `arxmcp_corpus_version` Prometheus gauge in `TestRouteSurface::test_metrics_corpus_version_matches_pinned` |

## Notable design choices for the critic

- **The MCP mount is non-trivial.** `mcp.server.fastmcp.FastMCP("name").streamable_http_app()` returns a Starlette app whose internal route is at `streamable_http_path` (default `/mcp`). Mounting THAT app at `/mcp` on the parent FastAPI gives the wrong final URL (`/mcp/mcp`). My fix: set `mcp_server.settings.streamable_http_path = "/"` BEFORE calling `streamable_http_app()`, then mount at `/mcp`. Final URL is `/mcp/` (with the standard Starlette `/mcp → /mcp/` 307 redirect for missing trailing slash). Documented in `server/_mcp_mount.py`'s docstring.

- **`/mcp` end-to-end test is intentionally weakened.** The mcp library's `streamable_http_app()` carries its own session-manager lifespan; threading it into the parent FastAPI lifespan correctly + actually serving a `tools/list` request requires the tool registrations that land in E06_S03. For this skeleton milestone, `TestRouteSurface::test_mcp_endpoint_mounted` verifies the `/mcp` Mount is in `app.routes`. The full end-to-end test will land alongside the tool implementations.

- **`max_concurrent_embeddings=8` and `query_encoder`'s singleflight are different knobs.** The brief's parenthetical referenced a `_singleflight_max_inflight=4` that does NOT exist in the current code (verified via grep). The semaphore bounds DISTINCT-query parallelism; the singleflight collapses SAME-query duplication. Both layers compose. Documented in `resources.py`'s docstring.

- **Reranker model load PRE-E07: always FATAL when `enable_rerank=true`.** Per synthesis D6 (trust the operator's choice; refuse on failure), `_load_reranker_or_raise()` is a placeholder that always raises `RerankerUnavailableError` until E07 ships the actual loader. Operators who set `ARXMCP_ENABLE_RERANK=true` today by mistake hit this branch by design — that's the correct signal, not a bug.

- **`docker-compose` example contradiction documented.** `08-security-observability-ops.md:261` shows a docker-compose example setting `ARXMCP_BIND_HOST=0.0.0.0` inside the container. The brief's AC overrides this; the validator REJECTS it. If a future docker-compose deployment needs container-internal binding, E06_S05 (security hardening) will revisit. The docker-compose file is NOT shipped in this milestone.

- **Body-size cap is middleware, not per-tool.** Universal enforcement, single point. Exempts `/healthz` `/readyz` `/metrics` (Prometheus exposition can grow large; health endpoints are tiny). Streaming responses (e.g. SSE on `/mcp`) are passed through — the cap measures the buffered `body` attribute which streaming responses don't expose.

- **The Prometheus counter is monotonic via delta-from-singleton.** `query_encoder.SINGLEFLIGHT_DEDUP_COUNT` is the source of truth; the Prometheus `Counter` is incremented by the delta at scrape time. Module-level `_LAST_DEDUP_COUNT` tracks the last observed value. F8-from-E03_S03 closure.

- **`docs_url`, `redoc_url`, `openapi_url` all set to `None`.** Threat-4 surface reduction — operators wanting to see tools call `tools/list` over MCP, not the FastAPI auto-doc endpoints.

- **No `docker-compose.yml` in this milestone.** The brief explicitly defers it to E06_S05 (security hardening). The Dockerfile is shipped as source; the operator runs `docker build -f docker/Dockerfile.server -t arxmcp-server:dev .` when they want a runtime image.

## Out-of-scope (deferred per brief)

- Tool implementations (E06_S03).
- Stdio shim binary (E06_S02).
- Security hardening — Origin header validation, secrets-grade session ID, docker-compose (E06_S05).
- Authentication (explicitly out of v1 per design notes).
- BM25 hybrid retrieval and reranker integration (E07).

## External writes

**None at commit time.** Everything is local commits. The runtime
expectations:
- `docker build -f docker/Dockerfile.server -t arxmcp-server:dev .` is an operator action, not part of this milestone.
- BGE-M3 weights download on first real-model run is operator-initiated.
- No git push, no PR creation, no infra mutation, no third-party API call.
