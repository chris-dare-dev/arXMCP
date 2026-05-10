# E06_S01 Research Brief 1 — FastAPI + Streamable HTTP server skeleton

## 1. In-codebase context

### Design constitution (load-bearing constraints)

**Transport** is non-negotiable. `06-mcp-server-design.md:3-17` plus
`02-architecture-overview.md:8` state: "stdio is wrong for multi-agent serving
because it spawns one process per Claude client, defeating shared caches" — so
the server **must** be a long-running Streamable HTTP process at
`127.0.0.1:7733`, with a separate `arxmcp-shim` (E06_S02) bridging stdio.

**Lifecycle is locked** by `06-mcp-server-design.md:339-353`:

> "load embedder into memory; load reranker only when `ARXMCP_ENABLE_RERANK=true`;
> read `corpus-version.json` to obtain `corpus_version: int`; open LanceDB via
> `dataset.checkout(version=corpus_version)` and pin that read-only view for the
> process lifetime; open Kùzu read-only; warm caches; pass readiness check.
> **No symlink resolution.**"

And: "the MCP server does NOT auto-switch — it continues using its pinned
version. Restart the server to pick up the new corpus." Shutdown is a
30-second drain.

**Concurrency** (`06-mcp-server-design.md:296-304`): semaphores
`max_concurrent_embeddings = 8`, `max_concurrent_reranks = 4`; LanceDB is
lock-free for readers; **Singleflight** "on the embedder" is "Python
`asyncio.Lock` keyed by query hash, with a `dict` of `Future`s." The reference
implementation is `07-multi-agent-caching.md:209-230`.

**Spec compliance** (`06-mcp-server-design.md:38-43`):

> "Origin pinning + localhost binding. Both. Spec quote: 'Servers MUST validate
> the `Origin` header... bind only to localhost.'"
> "`Mcp-Session-Id` header is globally unique and cryptographically secure."
> "Tool input validation is a MUST per the spec's Tools section."
> "Tool result size has no protocol limit — we enforce our own (256 KB hard cap
> on inline content). Use `resource_link` for the long tail."

The full env-var list is at `06-mcp-server-design.md:317-331` (10 vars; this
milestone wires them all).

### Existing source under `server/`

- `server/__init__.py` — empty.
- `server/README.md` — placeholder pointing at the design notes.
- `server/corpus.py` (E04_S02 + E04_S03) — exports
  `open_chunks_table(lancedb_path=None, version=int|None) -> lancedb.table.Table`
  and `read_corpus_version(lancedb_path=None) -> CorpusVersionInfo | None`.
  Cold-start contract: "Returns `None` when the marker file is **absent** … The
  MCP server (E06) handles this by falling back to
  `open_chunks_table(path, version=None)` (live tip)." That cold-start fallback
  is **already specified** in the corpus module's docstring — see open
  question (d).
- `server/query_encoder.py` (E03_S03) — `async def encode_query(query) ->
  np.ndarray`, an unbounded singleflight registry `_inflight: dict[str,
  asyncio.Future[np.ndarray]]`, lazy `_get_executor()` returning a single-worker
  `ThreadPoolExecutor(max_workers=1, thread_name_prefix="bge-m3-encode")`, plus
  `shutdown_executor(*, wait, cancel_futures)` documented as: "the server
  lifecycle can call this from a SIGTERM handler so `docker stop` honours its
  grace period."

The brief's "Singleflight wrapper" deliverable in `server/resources.py` **must
not** rebuild this. See open question (a).

### `pyproject.toml` deps

Currently present: `beautifulsoup4`, `transformers`, `torch`, `safetensors`,
`numpy`, `lancedb`, `pyarrow`, `rank-bm25`. **Missing and required for this
milestone:**

- `mcp>=1.27` — official Python lib; pinned to a specific minor for byte-stability
  guarantees on the `Mcp-Session-Id` and `tools/list` shapes.
- `fastapi>=0.115`
- `uvicorn[standard]>=0.30` — server runner; `[standard]` pulls
  `uvloop`/`httptools` for the C-accelerated event loop.
- `pydantic-settings>=2.4` — env-var loading (the bare `pydantic` is already
  a transitive of `fastapi` and `mcp`).
- `prometheus-client>=0.20` — `/metrics` exposition.
- `httpx` is already pulled by `mcp`/`fastapi` transitively.

Add as a new `[project.optional-dependencies] server = [...]` group, OR put
into the base list. The Tier-1 scope means the server is a first-class
artifact, so I recommend the base list (matches the existing pattern that
`lancedb` lives in base, not optional, even though only ingest needs it
today).

### Existing test fixtures

`tests/conftest.py` already auto-patches `STORE_STATS_PATH` and
`BM25_STATS_PATH` into `tmp_path`. The new `tests/test_server_startup.py`
fixture should follow that pattern: monkeypatch
`server.config.Config.lancedb_path` and `corpus_version_marker_path` into a
seeded `tmp_path`. The env-gated integration pattern at
`tests/test_embedder.py:22-24` (`ARXMCP_RUN_REAL_BGE_M3=1`) is the precedent
for any test that touches the real BGE-M3 weights — see open question (e).

## 2. Prior decisions and lessons

### Recent commits relevant to this milestone

- `9424d17 feat(server): singleflight wrapper for query encoding (E03_S03)` —
  the Singleflight already exists.
- `6f183be feat(ingest): idempotent re-embed with sidecar manifest (E03_S02)`
- `490c850 rect(E03_S01): … ` — embedder hardened, including the Threat-6
  `BGE_M3_COMMIT_SHA` single-source-of-truth contract.
- E04_S02 (`server/corpus.py:open_chunks_table`) and E04_S03
  (`read_corpus_version`) shipped the exact APIs this milestone calls.

### Threat 4 origin-pinning / 0.0.0.0 rejection

`08-security-observability-ops.md:69-76`:

> "`Origin` header validation (MCP spec MUST). Allow only configured origins;
> default to no `Origin` (the stdio shim doesn't send one) plus
> `http://127.0.0.1:7733`."
> "DNS rebinding defense: validate the `Host` header is `127.0.0.1` or
> `localhost` with the configured port."

The brief's AC says "binding to `0.0.0.0` is rejected at config parse time."
**However**, line 261 of the same notes file shows the docker-compose example
setting `ARXMCP_BIND_HOST=0.0.0.0` inside the container (with the host-side
port-publish at `127.0.0.1:7733`). The intent is "inside the container, bind
to all interfaces so the docker port-map works; outside, only loopback is
exposed." The milestone brief's wording overrides this for v1 — reject
non-loopback values **at the config layer**, no exception. If that breaks
docker-compose later, E06_S05 (security hardening) will revisit. **Do not
weaken the AC to accommodate the example compose file.** Flag the contradiction
to the implementer so they don't try to special-case it.

### "Manual symlink swaps prohibited"

Comes from E04_S02. `02-architecture-overview.md:139`: "Never mutate in place.
No manual symlink swaps." Operationally this means: never read or write
`var/arxmcp/index/lancedb/current/` (no such symlink exists); call
`dataset.checkout(version=N)` exclusively. The corpus module's docstring spells
this out: "checkout mutates in place. `tbl.checkout(N)` is an in-place mutation
of the table object that pins reads to version `N`. A shared/cached table
reference passed to `checkout` would corrupt other readers' views."
`open_chunks_table` returns a fresh handle; the server should call it **once**
per startup and cache the returned handle (do not call `.checkout()` on the
cached handle).

### Singleflight lessons from E03_S03 critique-adversary

- F1: cancellation must use `asyncio.shield` so that cancelling one waiter
  doesn't kill the in-flight future for others. The new `resources.py` must
  not re-implement this.
- F4: the executor must be lazy + drainable from a SIGTERM handler. The
  `shutdown_executor` hook already exists; the server lifespan must call it
  during the 30-second drain.
- F8: the `SINGLEFLIGHT_DEDUP_COUNT` integer is the wireable hook for the
  `arxmcp_embed_singleflight_dedup_total` Prometheus counter — see
  `07-multi-agent-caching.md:309` for the metric name. The new `health.py`
  `/metrics` endpoint should expose a Prometheus `Counter` whose `.inc()` is
  driven from the existing `get_singleflight_dedup_count()` getter (snapshot
  delta at scrape time), or simply rebuild it as a real `Counter` and have
  `query_encoder` increment both.

## 3. External sources

### MCP 2025-06-18 spec — Streamable HTTP

Verified directly against the spec page. Key obligations beyond what the
notes already capture:

- "The server **MUST** provide a single HTTP endpoint path (hereafter
  referred to as the **MCP endpoint**) that supports both POST and GET
  methods." Conventional path is `/mcp`.
- POST body is "a single JSON-RPC *request*, *notification*, or *response*."
  For requests the server returns either `Content-Type: application/json`
  (single response) or `Content-Type: text/event-stream` (SSE stream).
  Notifications/responses get `202 Accepted` with empty body.
- GET on the endpoint may open an SSE stream for server→client
  notifications, or return `405 Method Not Allowed`.
- DELETE on the endpoint with `Mcp-Session-Id` terminates the session;
  returning `405` is permitted if the server doesn't support client-driven
  termination.
- **Session ID rules:** "**SHOULD** be globally unique and cryptographically
  secure (e.g., a securely generated UUID, a JWT, or a cryptographic hash).
  The session ID **MUST** only contain visible ASCII characters (ranging from
  0x21 to 0x7E)." — UUID4 satisfies this, but `secrets.token_hex(32)` is the
  hardened option (E06_S05 will switch to that; ship UUID4 here per the
  brief's "UUID4 at minimum").
- "Servers that require a session ID **SHOULD** respond to requests without
  an `Mcp-Session-Id` header (other than initialization) with HTTP 400 Bad
  Request."
- `MCP-Protocol-Version: 2025-06-18` **MUST** be on every non-init request
  from the client; server returns 400 on unsupported version.
- Security warning (verbatim): "Servers **MUST** validate the `Origin`
  header on all incoming connections to prevent DNS rebinding attacks. When
  running locally, servers **SHOULD** bind only to localhost (127.0.0.1)
  rather than all network interfaces (0.0.0.0)."

### `mcp` Python lib (PyPI 1.27.1, 2026-05-08)

The lib exposes `FastMCP` with `mcp.run(transport="streamable-http")` and
also a `streamable_http_app()` (or `mcp.streamable_http_app`, depending on
minor version) that returns a Starlette/ASGI app you can mount onto FastAPI:

```python
app = FastAPI(lifespan=lifespan)
app.mount("/mcp", mcp.streamable_http_app())
```

The exact attribute name has shifted across 1.x minors. Pin
`mcp==1.27.*` and verify the mount call against the installed version's
source — see open question (b).

### FastAPI lifespan (vs deprecated startup/shutdown events)

The canonical pattern since FastAPI 0.93 is:

```python
from contextlib import asynccontextmanager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: load embedder, open LanceDB, warm reranker
    app.state.resources = await Resources.startup(config)
    try:
        yield
    finally:
        # shutdown: 30-second drain, close LanceDB, flush metrics
        await asyncio.wait_for(app.state.resources.shutdown(), timeout=30)
        shutdown_executor(wait=True)

app = FastAPI(lifespan=lifespan)
```

`@app.on_event("startup")` is deprecated and will be removed; do not use it.

### pydantic-settings

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ARXMCP_", env_file=None)
    bind_host: str = "127.0.0.1"
    bind_port: int = 7733
    lancedb_path: Path = Path("var/arxmcp/index/lancedb")
    enable_rerank: bool = False
    embed_model: str = "BAAI/bge-m3"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    max_concurrent_embeddings: int = 8
    max_concurrent_reranks: int = 4
    result_byte_cap: int = 262144
    log_level: str = "INFO"
    @field_validator("bind_host")
    @classmethod
    def reject_non_loopback(cls, v: str) -> str:
        if v not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError(f"bind_host must be loopback, got {v!r}")
        return v
```

Validators raise at instantiation time, satisfying the "rejected at config
parse time" AC.

### prometheus-client

`prometheus_client.make_asgi_app()` returns an ASGI app suitable for
`app.mount("/metrics", make_asgi_app())`. Use `Counter`, `Gauge`,
`Histogram` registered against the default `REGISTRY`.

### Docker multi-stage best practices

Two stages: `python:3.11-slim` builder (installs build deps + wheel-builds
torch/lancedb), and `python:3.11-slim` runtime (copies site-packages, runs
as `arxmcp` UID 1000). `EXPOSE 7733`. `HEALTHCHECK CMD curl -fsS
http://127.0.0.1:7733/readyz || exit 1`. Use `tini` as PID 1 (or
`uvicorn`'s `--no-server-header --no-date-header` plus `signal --propagate`)
so SIGTERM reaches the lifespan shutdown. The compose file at
`08-security-observability-ops.md:248-275` is the spec for runtime mounts;
this milestone only ships the Dockerfile, not the compose.

## Open questions

**(a) `server/resources.py` vs `server/query_encoder.py` — REPLACE or COEXIST?**
**Opinion: COEXIST.** `query_encoder.py` is the load-bearing singleflight
specifically for the BGE-M3 embedding-of-queries path; it has 22+ unit
tests, a critique-adversary review, and a single-source-of-truth contract
with `ingest.embedder` (`BGE_M3_COMMIT_SHA` import). Rewriting it inside
`resources.py` is pure regression risk. `resources.py` should be a
**lifecycle/state container**: holds the `LanceDB` table handle from
`open_chunks_table`, the embedder/reranker model handles, the two
`asyncio.Semaphore`s, and a thin generic `Singleflight` class for the
**reranker** (the brief lists embedder + reranker as the two singleflight
targets in `07-multi-agent-caching.md:232-235`; the embedder one already
exists, the reranker one does not). `resources.py` re-exports
`server.query_encoder.encode_query` and calls `shutdown_executor` from its
shutdown method.

**(b) `mcp` lib FastAPI mount API stability.** **Opinion: pin
`mcp==1.27.*`** and verify the actual attribute by importing it in
conftest. The 1.x line has renamed `sse_app` → `streamable_http_app` once
already; isolate the wiring in a `server/_mcp_mount.py` module with one
function `mount_mcp(app: FastAPI, mcp_server: FastMCP, path: str = "/mcp")`
so future renames are a one-line change. Keep tool registration in
`server/tools.py` (E06_S03 deliverable) using `@mcp.tool()` decorators —
those have been stable since 1.0.

**(c) `max_concurrent_embeddings=8` vs the existing single-worker
executor.** **Opinion: these are different knobs and BOTH apply.** There is
no `_singleflight_max_inflight` in the actual code (the brief's mention is
inaccurate — verified by grep). Today: an unbounded `_inflight` dict +
single-worker `ThreadPoolExecutor` means concurrent encode requests for the
same query coalesce to ONE forward pass, and concurrent encodes of
**different** queries serialize through the executor. The new
`asyncio.Semaphore(max_concurrent_embeddings=8)` operates **outside**
`encode_query` — at the `search_papers` handler boundary, gating how many
concurrent search requests can be in the embedding-call portion of their
work. This protects against thundering-herd of distinct queries (which
would queue inside the single-worker executor and exhaust event-loop slots).
Document this in `resources.py`'s docstring as "two-tier concurrency: the
semaphore bounds **distinct-query parallelism**, the singleflight collapses
**same-query duplication**." Do NOT increase the executor's `max_workers`
above 1 — the BGE-M3 model "is not safe for concurrent calls against the
same model instance" (`query_encoder.py:18-19`).

**(d) `corpus-version.json` absent on cold start — refuse or degrade?**
**Opinion: REFUSE TO START in v1, with a clear error message.** The
`server/corpus.py` docstring leaves the door open for "fall back to live
tip" via `open_chunks_table(version=None)`, but that contradicts the
milestone brief's load-bearing AC ("`corpus_version` integer is logged at
startup and matches `corpus-version.json`"). If the marker is absent, no
`corpus_version: int` exists to log, and downstream caches (E08_S03) cannot
key correctly. A cold-start dev box without ingest is not a v1 scenario —
the dev runs ingest, then the server. Print `FATAL: corpus-version.json not
found at <path>; run ingest first` and exit 1. The "live-tip fallback" path
in `server/corpus.py` exists for E05's eval harness, not for the server.
This contradiction with the corpus-module docstring should be flagged in
the implementation notes; we do NOT need to update the docstring — it
correctly describes its own callers' options, and the server is one
caller that opts out of the fallback.

**(e) `tests/test_server_startup.py` — real model or mocked?**
**Opinion: MOCKED by default + env-gated real test.** Match the
`tests/test_embedder.py:22-24` precedent: monkeypatch `Resources.startup`
to inject a fake embedder + a small `tmp_path` LanceDB seeded by the
fixture, run `uvicorn` in a daemon thread on an ephemeral port, poll
`/healthz` and `/readyz`, assert `503 → 200` transition within 30s (the
mocked path resolves in <2s). Add a separate
`@pytest.mark.skipif(os.environ.get("ARXMCP_RUN_REAL_BGE_M3") != "1")`
test that runs the same flow with real BGE-M3 weights (asserts the 30s
budget against the real ~5s warm-load on M2). Reusing the same fixture
shape avoids divergent paths.

**(f) `ARXMCP_ENABLE_RERANK=true` but model unavailable.**
**Opinion: REFUSE TO START.** Falling back silently to "rerank disabled
even though config said enabled" is a foot-shot for the eval harness and
will produce confusing nDCG regressions. Log
`FATAL: ARXMCP_ENABLE_RERANK=true but model load failed: <exc>`
and exit 1. The operator chose to enable it; trust the choice. (E07
ships the reranker; before E07 lands, the AC for `enable_rerank=true`
is unsatisfiable by design — that's correct behavior, not a bug.)

## External writes the implementation will require

**None.** This milestone is local-only:

- New deps in `pyproject.toml` — local edit.
- New `docker/Dockerfile.server` — local commit (the brief explicitly
  states "this milestone adds a Dockerfile — that's a new infra artifact
  but committed locally, NOT a push").
- New source files under `server/` and `tests/` — local commits.
- No PR, no ticket update, no model-weight download (mocked tests),
  no third-party API call, no infra mutation.

The implementation will eventually need to download BGE-M3 weights at
**runtime** when the operator first starts the server with
`ARXMCP_RUN_REAL_BGE_M3=1` — but that's an operator action, not a CI/test
external write, and the Threat-6 mitigations (`safetensors` + pinned SHA)
already constrain it.
