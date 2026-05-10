# E06_S01 — Research Synthesis

**Inputs:** `research-brief-1.md`, `research-brief-2.md` (both Sonnet,
parallel). Strong convergence on every load-bearing decision.

---

## D1 — `server/resources.py` vs `server/query_encoder.py`: COEXIST

**Both briefs agree, with identical reasoning.** R1: *"`query_encoder.py`
is the load-bearing singleflight specifically for the BGE-M3
embedding-of-queries path; it has 22+ unit tests, a critique-adversary
review, and a single-source-of-truth contract with `ingest.embedder`.
Rewriting it inside `resources.py` is pure regression risk."* R2:
*"`query_encoder` is the embedder-side singleflight (one canonicalized
query → one forward pass). `resources.py` owns lifecycle (load model
once at startup, share singleton, hold the throughput semaphore).
They wrap, not replace."*

**Decision:** `server/resources.py` is a **lifecycle/state container**:
- Holds the LanceDB table handle from `open_chunks_table` (one per
  pinned version, cached for process lifetime).
- Owns the embedder + reranker model handles (loaded once at startup,
  shared singletons).
- Owns two `asyncio.Semaphore`s: `max_concurrent_embeddings=8`,
  `max_concurrent_reranks=4`.
- Wraps `query_encoder.encode_query` with a semaphore-then-encode
  helper (`embed_query` — semaphore acquired BEFORE the singleflight
  dispatch).
- Calls `query_encoder.shutdown_executor(wait=True)` on shutdown.
- Implements a generic `Singleflight` class for the **reranker**
  (the embedder one already exists in `query_encoder`).

## D2 — Two-tier concurrency model

**Both briefs agree, with R1 articulating it most clearly.** R1:
*"two-tier concurrency: the semaphore bounds **distinct-query
parallelism**, the singleflight collapses **same-query duplication**."*

The brief's parenthetical "`Singleflight` asyncio class wraps the
embedder so that N concurrent agents asking the same query produce
exactly one in-flight embedding call" is **already done** by
`query_encoder.encode_query`. The new code adds:
- The throughput semaphore (8 concurrent distinct-query embeddings).
- The startup warmup (calls `_get_model()` + `_get_tokenizer()` once
  before `yield`, satisfying the F3 race the existing module
  documents).
- The reranker-side singleflight (which does NOT yet exist).

**Decision:** Document this two-tier model in `resources.py`'s
docstring. Do NOT increase `query_encoder._executor.max_workers`
above 1 — BGE-M3 is not safe for concurrent same-instance calls.

## D3 — Eager model load at startup (gates `/readyz`)

**Both briefs agree.** R2: *"Lazy load would make the first
`tools/call` hang for ~30s while a green /readyz lied. Call
`_get_model()` and `_get_tokenizer()` from the lifespan startup
branch, BEFORE the `yield`."* R1 same.

**Decision:** Eager. The startup sequence:
1. Parse config (pydantic-settings, validators raise on bad input).
2. Read `corpus-version.json` → `corpus_version: int` (REFUSE TO
   START on absent — see D5).
3. Open LanceDB chunks table at the pinned version (cache handle).
4. Load BGE-M3 (`_get_model()` + `_get_tokenizer()` from
   `query_encoder`).
5. If `enable_rerank=True`, load BGE-reranker-v2-m3 (REFUSE TO START
   on load failure).
6. Set `Resources.warm = True`; `/readyz` flips from 503 → 200.

## D4 — `bind_host` validation: reject non-loopback at parse time

**Both briefs agree.** Pydantic field validator on `Config.bind_host`:

```python
@field_validator("bind_host")
@classmethod
def reject_non_loopback(cls, v: str) -> str:
    if v not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError(f"bind_host must be loopback, got {v!r}")
    return v
```

R1 flags a real contradiction: `08-security-observability-ops.md:261`
shows a docker-compose example setting `ARXMCP_BIND_HOST=0.0.0.0`
inside the container (with the host port-publish at `127.0.0.1:7733`).
The brief's AC overrides this for v1: **reject non-loopback at the
config layer, no exception**. If docker-compose later needs
container-internal binding, E06_S05 (security hardening) will revisit.

**Decision:** No carve-out for the docker-compose case at this
milestone. Document the contradiction in the implementation summary
so the future security milestone re-examines it.

## D5 — Cold-start corpus marker: REFUSE TO START

**Both briefs agree.** R1: *"If the marker is absent, no
`corpus_version: int` exists to log, and downstream caches (E08_S03)
cannot key correctly. A cold-start dev box without ingest is not a
v1 scenario — the dev runs ingest, then the server."*

**Decision:** `read_corpus_version()` returning `None` → log
`FATAL: corpus-version.json not found at <path>; run ingest first`
and exit 1. The "live-tip fallback" path in `server/corpus.py` exists
for E05's eval harness, NOT for the server. We are NOT updating the
`server/corpus.py` docstring (it correctly describes its own callers'
options — the server is one caller that opts out of the fallback).

## D6 — `ARXMCP_ENABLE_RERANK=true` but model unavailable: REFUSE TO START

**Only R1 raised this; the answer is unambiguous.** R1: *"Falling
back silently to 'rerank disabled even though config said enabled'
is a foot-shot for the eval harness and will produce confusing nDCG
regressions."*

**Decision:** Trust the operator's choice. On model load failure, log
`FATAL: ARXMCP_ENABLE_RERANK=true but model load failed: <exc>` and
exit 1. Before E07 lands the actual reranker integration, this
milestone wires the load attempt — operators who set
`enable_rerank=true` today will hit this branch by design (the
reranker model isn't downloaded yet); that's the correct signal.

## D7 — Test strategy: MOCKED by default, env-gated real test

**Both briefs agree.** R1: *"monkeypatch `Resources.startup` to
inject a fake embedder + a small `tmp_path` LanceDB seeded by the
fixture, run `uvicorn` in a daemon thread on an ephemeral port,
poll `/healthz` and `/readyz`, assert `503 → 200` transition within
30s (the mocked path resolves in <2s)."*

**Decision:**
- `tests/test_server_startup.py` — fast path. Mocks the embedder via
  monkeypatch (replaces `query_encoder._get_model` /
  `_get_tokenizer` with stubs that return immediately). Seeds a
  `tmp_path` LanceDB via `ingest.store.write_chunks` against a tiny
  fixture. Starts `uvicorn` in a daemon thread on an ephemeral
  port. Polls `/healthz` (200) + `/readyz` (503 → 200 within 30s).
- A separate test class (or `@pytest.mark.skipif(os.environ.get("ARXMCP_RUN_REAL_BGE_M3") != "1")`)
  runs the same flow with the real BGE-M3 weights — mirrors the
  precedent in `tests/test_embedder.py`.
- The conftest's `_patched_*_stats_path` autouse fixtures work for
  free.

## D8 — `pytest-asyncio` dependency

**Slight disagreement.** R2 recommends adding `pytest-asyncio` for
async tests. R1 doesn't mention it. The existing project pattern
(`tests/eval/test_retrieval_quality.py`) uses `asyncio.run()` inside
sync test functions and does NOT use `pytest-asyncio`.

**Decision:** Do NOT add `pytest-asyncio`. Continue the existing
project pattern: synchronous test bodies that wrap async calls in
`asyncio.run()` (or use `httpx.Client` synchronously). The startup
test runs uvicorn in a daemon thread and polls via `httpx.Client`
(sync) — no async-test machinery needed.

## D9 — `mcp` Python lib: pin a minor, isolate the mount

**Both briefs agree.** R1: *"Pin `mcp==1.27.*` and verify the actual
attribute by importing it in conftest. Isolate the wiring in a
`server/_mcp_mount.py` module with one function `mount_mcp(app:
FastAPI, mcp_server: FastMCP, path: str = '/mcp')` so future renames
are a one-line change."*

**Decision:** Pin `mcp` to a tested minor. Wrap the mount call in a
single function so a future API change is one-line. Do NOT import
`mcp.types.*` in handler modules (E06_S03 territory) — keep the
adapter narrow. For this milestone, the mount can be a stub
(`# TODO(E06_S03): register tools here`) since the brief is
explicit that tool implementations are out of scope. The mount must
exist (so `make up` can launch the server), but the tool list can
be empty.

**Decision (defensive):** Wrap the `mcp` import in a `try/except
ImportError` at the top of `server/main.py`, with a clear `FATAL:
mcp library not installed. Run pip install -e '.[server]'` message.
Mirrors the discipline of the eval harness's deferred imports.

## D10 — Dependencies to add to `pyproject.toml`

Both briefs agree on the additions. Final list:

| dep | version | rationale |
|---|---|---|
| `mcp` | `>=1.27,<1.28` | Pinned minor for `streamable_http_app()` API stability |
| `fastapi` | `>=0.115` | Modern lifespan API |
| `uvicorn[standard]` | `>=0.30` | Includes `uvloop` + `httptools` |
| `pydantic-settings` | `>=2.4` | env-var loading with field validators |
| `prometheus-client` | `>=0.20` | `/metrics` exposition |

**Decision:** Add to the base dependency list (NOT
`[project.optional-dependencies] server = [...]`). Matches the
existing pattern where `lancedb` is a base dep even though only
ingest needs it today; the project is small enough that a single
install profile is simpler than splitting.

## D11 — `/metrics` counters at this milestone

R2 proposed a minimal set:

| metric | type | meaning |
|---|---|---|
| `arxmcp_corpus_version` | Gauge | The pinned `corpus_version` integer |
| `arxmcp_resources_warm{resource="embedder|reranker|lancedb"}` | Gauge (0/1) | Resource warm state |
| `arxmcp_process_start_time_seconds` | Gauge | UNIX timestamp set once at startup |
| `arxmcp_embed_singleflight_dedup_total` | Counter | Wired from `query_encoder.get_singleflight_dedup_count()` (R1's F8 callback) |

**Decision:** Ship these four. The reranker entry in
`resources_warm` reports 0 when `enable_rerank=False` (the resource
is disabled, not warm). Per-tool counters (`tool_calls_total`,
`tool_latency_seconds`) defer to E06_S03 when the tools land.

## D12 — Updates to `Makefile` and `server/README.md`

**Both briefs agree.** R2 specifically called out:
- `make up` is currently a stub (`@exit 1` with "lands in E01_S08").
  E01_S08 is SUPERSEDED_BY E06_S01. Wire it to actually launch the
  server.
- `server/README.md` says "Empty until E01_S08." — refresh.

**Decision:** Update both. `make up`:

```make
up:
    @$(PYTHON) -c "import sys; assert sys.version_info >= (3, $(MIN_PY_MINOR)), \
        f'arXMCP requires Python >= 3.$(MIN_PY_MINOR); got {sys.version_info[:2]}'"
    $(PYTHON) -m uvicorn server.main:app --host 127.0.0.1 --port 7733
```

`server/README.md`: brief contents listing the four new modules and
pointing at the design notes.

## D13 — 256 KB inline payload cap: middleware

**R2 only — accept the recommendation.** R2: *"MIDDLEWARE. Universal
cap, single enforcement point, harder to forget. Use FastAPI's
`Response` body length check in a `BaseHTTPMiddleware` subclass.
Per-tool cap would let a careless `get_chunk` exceed it. The
middleware should NOT short-circuit `/metrics` (Prometheus output
can grow large)."*

**Decision:** Implement as middleware in this milestone. Skip the
check on `/metrics` (Prometheus exposition can exceed 256 KB on
large registries). Skip on `/healthz` and `/readyz` too (negligible
size, no need to instrument). The cap fires only for tool-result
JSON; tools land in E06_S03 but the middleware is in place from
this milestone. Tested with a synthetic large response.

## D14 — Dockerfile: multi-stage, non-root, EXPOSE 7733

**Both briefs agree on the shape.** R1 spelled out the structure:

- Two stages: `python:3.11-slim` builder + `python:3.11-slim` runtime.
- Runtime runs as `arxmcp` UID 1000.
- `EXPOSE 7733`.
- `HEALTHCHECK CMD curl -fsS http://127.0.0.1:7733/readyz || exit 1`.
- `tini` as PID 1 OR uvicorn's signal-propagate so SIGTERM reaches
  the lifespan shutdown.

**Decision:** Adopt the shape. Use `tini` as PID 1 (clean signal
forwarding to uvicorn's worker). Do NOT include the docker-compose
file (out of scope per the brief; the compose lands in E06_S05 with
the security-hardening pass).

## D15 — Path-traversal validation deferred to tool boundary

**Both briefs agree.** `server/corpus.py`'s docstring already says
*"Path-traversal validation (Threat 1 from `08-security-observability-ops.md`)
is deferred to E06's tool-input boundary (TODO(E06))"*. For this
milestone, paths come from `ARXMCP_LANCEDB_PATH` (config-derived,
trusted). No extra validation needed at startup.

## File layout

```
server/main.py             # NEW: FastAPI app + lifespan
server/config.py           # NEW: pydantic-settings Config
server/resources.py        # NEW: lifecycle container (embedder/reranker/LanceDB/sema/SF)
server/health.py           # NEW: /healthz, /readyz, /metrics routes
server/_mcp_mount.py       # NEW: thin adapter for the mcp lib mount
server/README.md           # MODIFIED: refresh from "Empty until E01_S08"
docker/Dockerfile.server   # NEW: multi-stage; non-root; EXPOSE 7733
tests/test_server_startup.py  # NEW: mocked-resources readiness test
Makefile                   # MODIFIED: implement `make up` (was stub)
pyproject.toml             # MODIFIED: add 5 deps
```

## Open questions (residual)

**None blocking implementation.** Both researchers raised the same
six open questions and gave aligned, opinionated answers. The
synthesis above locks each.

## External writes the implementation will require

Both briefs agree: **none**.

| type | target | why |
|---|---|---|
| filesystem write | new files under `server/`, `docker/`, `tests/` | local commits |
| filesystem write | `pyproject.toml` (modified), `Makefile` (modified), `server/README.md` (modified) | local commits |

**No git push, no PR creation, no ticket, no infra mutation, no
third-party API call.** Phase 4's external-write gate has nothing
to authorize. The Dockerfile is shipped as source; it is NOT built
or pushed in this milestone (the operator runs `docker build` when
they want a runtime image).
