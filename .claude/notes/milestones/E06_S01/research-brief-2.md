# E06_S01 Research Brief 2 — FastAPI server skeleton

## 1. In-codebase context

### `server/` directory inventory

```
server/
├── README.md          (1 line: "Empty until E01_S08." — stale; E01_S08 is SUPERSEDED_BY E06_S01)
├── __init__.py        (0 bytes — empty package marker)
├── corpus.py          (E04_S02 + E04_S03; readers: open_chunks_table, read_corpus_version)
└── query_encoder.py   (E03_S03; singleflight wrapper around BGE-M3 encode)
```

Public APIs already in place:

- **`server.corpus.open_chunks_table(lancedb_path: str|Path|None=None, version:int|None=None) -> lancedb.table.Table`** — sync. "Each call opens a fresh table handle." Raises `FileNotFoundError` if path missing, `ValueError` if version unknown. The docstring spells out the recommended E06 pattern verbatim: "call this function ONCE per pinned version at startup, cache the returned handle, and route queries to the cached handle. Re-pinning to a new version requires opening a new handle (do not call ``checkout`` on a cached one)."
- **`server.corpus.read_corpus_version(lancedb_path=None) -> CorpusVersionInfo | None`** — sync. Returns `None` when marker is absent (cold start), raises `ValueError` for malformed file. `CorpusVersionInfo` is a dataclass with `version: int, chunker_version, embedder_version, created_at, paper_count, chunk_count`. Critically: "the ``version`` integer is also the **cache namespace key** for all server-side caches per the cache contract."
- **`server.query_encoder.encode_query(query_text: str) -> np.ndarray`** — async. Singleflight + 100 ms post-completion eviction. Module-level `_inflight: dict[str, asyncio.Future[np.ndarray]]`. Module also exports `get_singleflight_dedup_count()`, `shutdown_executor(*, wait=True, cancel_futures=False)`, `_reset_for_tests()`, and the constants `BGE_M3_COMMIT_SHA`, `EMBEDDING_DIM`, `MAX_TOKENS`, `DEDUP_WINDOW_S`. Uses a single-worker `ThreadPoolExecutor` to off-load the GIL-releasing BGE-M3 forward pass.

### `pyproject.toml` — current vs needed

Current dependencies: `beautifulsoup4`, `transformers`, `torch`, `safetensors`, `numpy`, `lancedb`, `pyarrow`, `rank-bm25`. Dev: `ruff`, `pytest`. **Missing for E06_S01**: `fastapi`, `uvicorn[standard]`, `pydantic-settings>=2.0`, `prometheus-client`, `mcp` (the MCP Python SDK), and `httpx` (test-side ASGI client). I would also add `pytest-asyncio` since the readiness test is inherently async.

### Other files of interest

- **`docker/`** — does not exist. This milestone creates it and ships `docker/Dockerfile.server`. The `docker-compose.yml` snippet in `08-security-observability-ops.md` (lines 244–288) is the integration target but is out of scope for this milestone.
- **`Makefile`** — `make up` is currently a stub: `@echo "make up — not yet implemented (lands in E01_S08)"; @exit 1`. E01_S08 is `SUPERSEDED_BY E06_S01`. This milestone should update the `make up` target to actually launch `arxmcp-server`.
- **`tests/conftest.py`** — already has two `autouse` fixtures (`_patched_store_stats_path`, `_patched_bm25_stats_path`) that redirect ops paths into `tmp_path`. New server-startup tests will inherit them — good. The conftest also registers the `--ndcg-min` pytest option pattern; if the new test wants gating env flags, follow that pattern (e.g., a `--integration` flag, or use `pytest.mark.skipif(os.getenv("ARXMCP_RUN_INTEGRATION") != "1")` to mirror the embedder test discipline).
- **`ingest.store.DEFAULT_LANCEDB_PATH`** — `REPO_ROOT / "var" / "arxmcp" / "index" / "lancedb"`. Both reader and writer share this; `ARXMCP_LANCEDB_PATH` defaults to it.

### Load-bearing constraints (verbatim)

From `06-mcp-server-design.md` lines 38–43, the spec MUSTs we inherit at server-skeleton time: "Origin pinning + localhost binding... `Mcp-Session-Id` header is globally unique and cryptographically secure... Tool input validation is a MUST per the spec's Tools section... Tool result size has no protocol limit — we enforce our own (256 KB hard cap on inline content)."

From `06-mcp-server-design.md` lines 296–304: "**Bounded semaphores** in front of expensive resources: Embedder: `max_concurrent_embeddings = 8`. Reranker: `max_concurrent_reranks = 4`... **Singleflight pattern** on the embedder: when N concurrent agents ask the same query, only one in-flight `embed(query)` call happens."

From `06-mcp-server-design.md` lines 339–353 (the Server lifecycle update): "The `current` symlink is no longer used. Version is pinned by reading the integer from `corpus-version.json` and calling `dataset.checkout(version=N)`."

From `02-architecture-overview.md` lines 138–141: "**Never mutate in place. No manual symlink swaps**." — This is unambiguous. The server must NOT shell out to `ln -sf` against `var/arxmcp/index/lancedb/`. Pinning is purely via `tbl.checkout(version=N)` which `server.corpus.open_chunks_table` already wraps.

## 2. Prior decisions and lessons

### Singleflight reconciliation (the brief's biggest ambiguity)

E03_S03 already shipped `server/query_encoder.py` with a full singleflight + per-process registry + thread-pool executor + 100 ms eviction. Re-implementing a generic `Singleflight` class in `server/resources.py` would duplicate it. **Recommendation: COEXIST, do NOT replace.** `query_encoder.encode_query()` is the embedder-level singleflight (one canonicalized query → one BGE-M3 forward pass). The brief's `max_concurrent_embeddings=8` is an orthogonal *throughput* limit — it bounds DISTINCT queries in flight, not duplicates. So `server/resources.py` should:

1. Create the `asyncio.Semaphore(8)` for embeddings and `asyncio.Semaphore(4)` for reranks.
2. Re-export `query_encoder.encode_query` (or wrap it as `embed_query()` that takes the semaphore *first*, then calls `encode_query` *inside*).
3. Own model-load lifecycle (call `_get_model()` and `_get_tokenizer()` ONCE at startup so the F3 race in `query_encoder.py`'s docstring — "the operator MUST warm the model BEFORE concurrency starts" — is satisfied by construction).

The brief's "Singleflight asyncio class wraps the embedder so that N concurrent agents asking the same query produce exactly one in-flight embedding call" is **already done by `query_encoder.encode_query`**. The new code adds the semaphore + the warmup + the reranker-side singleflight (which does not yet exist).

### BP1 byte-stable JSON discipline

`/healthz`, `/readyz`, `/metrics` are NOT cache-keyed artifacts; they don't hit BP1. But the `mcp` library's `tools/list` response (which lands in E06_S03) IS cache-keyed. This milestone should set up the JSON-serialization plumbing (e.g., a `canonical_json(obj)` helper that uses `json.dumps(obj, sort_keys=True, separators=(",", ":"))`) so E06_S06's tool-schema hash test has the right serializer to hand. Out of scope for this milestone but should not be foreclosed.

### Path-traversal validation (Threat 1)

`server/corpus.py` already says: "Path-traversal validation (Threat 1 from `08-security-observability-ops.md`) is **deferred to E06's tool-input boundary** (TODO(E06))". For *this* milestone, the path comes from `ARXMCP_LANCEDB_PATH` (config-derived, trusted) — no extra validation needed at startup. Tool-input validation lands when the tools land (E06_S03 / E06_S05).

### Recent rectification commits

The last 5 commits all follow `rect(...)` patterns closing critique findings. Implication: this team writes adversarial reviews against every implementation; the brief's deliverables list is not the full story — expect to address Phase-3 critique findings in a follow-up `rect(E06_S01)` commit. Build defensively: every `pop()`, every `try/finally`, every `add_done_callback` should be there from the first pass.

### Stale `server/README.md`

The current `server/README.md` says "Empty until E01_S08" — and E01_S08 is SUPERSEDED. This milestone should refresh the README to point at E06_S01 and the actual delivered modules.

## 3. External sources

### MCP 2025-06-18 spec — Streamable HTTP (`https://modelcontextprotocol.io/specification/2025-06-18`)

Streamable HTTP is the spec's mandated remote transport. A single HTTP endpoint accepts both POST (JSON-RPC requests) and GET (SSE for server-initiated notifications). The server MAY return a chunked SSE stream or a single JSON response per POST. The `Mcp-Session-Id` header is set by the SERVER on initialization and ECHOED by the client on every subsequent request. The spec's security section requires the server to validate the `Origin` header (deferred to E06_S05 per the E06_S01 brief's "Out of scope") and bind to localhost. Spec quote on session IDs: they must be cryptographically secure. UUID4 has 122 bits of entropy — enough for a session identifier and matches the brief; E06_S05 later upgrades to `secrets.token_hex(32)` for defense-in-depth. **Land UUID4 here**, accept the upgrade in E06_S05.

### `mcp` Python SDK

The `mcp` PyPI package (`pip install mcp`) ships `mcp.server.fastmcp.FastMCP` and `mcp.server.streamable_http`. The canonical mount pattern in current docs: create a `FastMCP("arxmcp")`, register handlers, then `app.mount("/mcp", mcp_server.streamable_http_app())` to attach to a FastAPI parent. The library API is **still evolving** (the `1.x` line has had breaking changes between 0.x and 1.x). Recommendation: **wrap the `mcp` library in a thin adapter** (`server/mcp_adapter.py` is fine as a future module, but for E06_S01 keep all `mcp` imports inside `server/main.py` and behind a single function so the surface to swap is small). Do NOT expose `mcp.types.*` to handler modules in E06_S03; let handlers return Pydantic models that the adapter converts.

### FastAPI lifespan

The modern pattern (FastAPI ≥ 0.100) is `lifespan=` on the `FastAPI()` constructor with an `@asynccontextmanager async def lifespan(app)` generator. `@app.on_event("startup")` is deprecated — do NOT use it. The lifespan generator yields exactly once: pre-yield is startup, post-yield is shutdown. The 30-second drain belongs in the post-yield branch with `await asyncio.wait_for(drain_inflight(), timeout=30.0)`.

### `pydantic-settings`

`from pydantic_settings import BaseSettings, SettingsConfigDict`. The class-level `model_config = SettingsConfigDict(env_prefix="ARXMCP_", env_file=".env", extra="forbid")` gives the brief's `ARXMCP_*` discipline for free. Field-level validators (`@field_validator("bind_host")`) are how `0.0.0.0` is rejected at parse time — raise `ValueError` and pydantic-settings turns it into a startup `ValidationError` that exits with a non-zero status before uvicorn binds.

### `prometheus_client`

`from prometheus_client import make_asgi_app` returns an ASGI app that serves the registry. Mount with `app.mount("/metrics", make_asgi_app())`. This is FastAPI-compatible because FastAPI is ASGI under the hood. The default registry is process-wide — fine for a single-worker deployment. **Do not** use a multiprocess registry; the brief's "long-running `arxmcp-server` process" is single-process.

### Uvicorn worker model

Run uvicorn with `workers=1` and rely on asyncio for concurrency. Multi-worker would defeat shared-cache semantics (the same trap as stdio MCP). Bind via `uvicorn.run(app, host=settings.bind_host, port=settings.bind_port, lifespan="on", log_config=None)`. The "two servers on same port → clear error" AC is satisfied by uvicorn naturally — `OSError: [Errno 48] Address already in use` propagates and exits non-zero.

## Open questions (opinionated)

- **(a) `server/resources.py` vs `server/query_encoder.py`** — COEXIST. `query_encoder` is the embedder-side singleflight (one canonicalized query → one forward pass). `resources.py` owns lifecycle (load model once at startup, share singleton, hold the throughput semaphore). They wrap, not replace.
- **(b) Eager vs lazy model load** — EAGER. The /readyz AC says "returns 503 until embedder + LanceDB are initialized, then 200". Lazy load would make the first `tools/call` hang for ~30 s while a green /readyz lied. Call `_get_model()` and `_get_tokenizer()` from the lifespan startup branch, BEFORE the `yield`.
- **(c) `mcp` library FastAPI integration stability** — the library has FastAPI/Starlette mount support today (`streamable_http_app()` returns a Starlette app), but the API is not yet semver-stable. Wrap behind an adapter so the swap surface is one file. Do not import `mcp.*` in handler modules.
- **(d) tests/test_server_startup.py — real or mocked** — MOCK the model + LanceDB for the default path. Use a `monkeypatch` to set `server.resources._get_model = lambda: _FakeModel()` and a `tmp_path` LanceDB created via `ingest.store.write_chunks` against a tiny fixture. The 30-s readiness AC must be met with mocks; a real-BGE-M3 startup test should be gated behind `ARXMCP_RUN_INTEGRATION=1` mirroring `tests/test_embedder.py`.
- **(e) /metrics counters at this milestone** — bare-minimum: `arxmcp_corpus_version` (Gauge), `arxmcp_resources_warm{resource="embedder|reranker|lancedb"}` (Gauge 0/1), `arxmcp_process_start_time_seconds` (Gauge, set once at startup). Defer per-tool counters to E06_S03 when tools land. Keep the metric NAMES from `08-security-observability-ops.md` lines 102–145 as the canonical naming convention so E06_S03 doesn't collide.
- **(f) Pydantic input validation** — confirmed deferred. This milestone is "skeleton, no tools yet". The validation discipline lands in E06_S03 when the 7 tools materialize.
- **(g) 256 KB inline payload cap — middleware or per-tool** — MIDDLEWARE. Universal cap, single enforcement point, harder to forget. Use FastAPI's `Response` body length check in a `BaseHTTPMiddleware` subclass. Per-tool cap would let a careless `get_chunk` exceed it. The middleware should NOT short-circuit `/metrics` (Prometheus output can grow large).

## External writes the implementation will require

| type | target | why |
|---|---|---|
| git push | `claude/gallant-blackburn-b89422` | Push the implementation branch when phase advances past Implement. |
| git push | (none) | This milestone has no PR step at the implementation boundary; the orchestrator's pipeline gates PR creation behind a separate phase. No third-party API calls (no Hugging Face downloads at test time when mocked; the model SHA is pinned in source). |
