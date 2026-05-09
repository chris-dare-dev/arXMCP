# `server/`

Streamable HTTP MCP server. Long-running, owns the LanceDB index, the
embedder, the reranker, and all process-wide caches. Bound to
`127.0.0.1:7733` by default; ANY non-loopback bind is rejected at
config-parse time per the security note (Threat 4).

## Modules

| Module | Purpose |
|---|---|
| [`config.py`](config.py) | `pydantic-settings` `Config` class. Reads `ARXMCP_*` env vars; validates loopback-only bind, port range, concurrency knobs. |
| [`corpus.py`](corpus.py) | `open_chunks_table(version=N)` (E04_S02) + `read_corpus_version()` (E04_S03). Reader-side LanceDB access pinned to a corpus version. |
| [`query_encoder.py`](query_encoder.py) | Async BGE-M3 query encoder (E03_S03). Singleflight on the query hash; one-thread executor for the forward pass. |
| [`resources.py`](resources.py) | Lifecycle container (E06_S01). Loads BGE-M3 + LanceDB + (optional) reranker once at startup; owns the `embed_semaphore` (8) and `rerank_semaphore` (4). |
| [`health.py`](health.py) | `/healthz` (liveness) + `/readyz` (readiness, 503 → 200) + Prometheus metric definitions. |
| [`main.py`](main.py) | FastAPI app, lifespan context manager, body-size middleware, MCP Streamable HTTP mount at `/mcp`. |
| [`_mcp_mount.py`](_mcp_mount.py) | Thin adapter for the `mcp` library's mount API (isolated so a future SDK rename is one line). |

## Run locally

```sh
make up
# or, equivalently:
python -m uvicorn server.main:app --host 127.0.0.1 --port 7733 --lifespan on
```

The server REFUSES to start when `var/arxmcp/index/lancedb/corpus-version.json`
is absent — run the ingest pipeline first (E11 / future driver).

## Run in Docker

See [`docker/Dockerfile.server`](../docker/Dockerfile.server). Multi-stage,
non-root user (UID 1000), `tini` as PID 1 for signal forwarding, exposes
port 7733. The full `docker-compose.yml` lands in E06_S05 with the
security-hardening pass.

## Two-tier concurrency

The server bounds expensive resources at TWO composing layers:

1. **`asyncio.Semaphore(max_concurrent_embeddings=8)`** in
   [`resources.py`](resources.py) bounds DISTINCT-query parallelism —
   how many queries can be in flight against the embedder at once.
2. **`server.query_encoder.encode_query`'s singleflight** collapses
   SAME-query duplicates — N concurrent agents asking the identical
   query produce ONE forward pass.

Together: the semaphore stops thundering-herd of distinct queries
from queueing inside the single-worker BGE-M3 executor; the
singleflight prevents identical-query duplication across concurrent
sub-agents.

## Design references

- [`.claude/notes/02-architecture-overview.md`](../.claude/notes/02-architecture-overview.md)
- [`.claude/notes/06-mcp-server-design.md`](../.claude/notes/06-mcp-server-design.md) (the source of every MUST in this directory)
- [`.claude/notes/07-multi-agent-caching.md`](../.claude/notes/07-multi-agent-caching.md) (the singleflight reference implementation)
- [`.claude/notes/08-security-observability-ops.md`](../.claude/notes/08-security-observability-ops.md) (Threats 1–6, the bind-host AC)
