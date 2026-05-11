# arXMCP Implementation Scan

Snapshot of every shipped capability for the README + CLAUDE.md rewrite. Sourced from reading the tree at `/Users/chris.dare/Personal/SourceCode/arXMCP/`. Test count: **1316 tests collected** by pytest.

---

## 1. Top-level layout

### `Makefile` targets

| Target | Description |
|---|---|
| `help` | Print target list + Python override hint + `ARXMCP_CONTACT_EMAIL` reminder. |
| `bootstrap` | Validates Python ≥3.11 + active venv, runs `pip install --require-virtualenv -e ".[dev]"`, creates the `var/arxmcp/{corpus/{raw,parsed,chunks},index/{lancedb,kuzu},cache/ar5iv,ops/parser-failures}` tree. |
| `test` | `ruff check .` then `pytest`. Re-validates Python ≥3.11. |
| `eval` | Runs the Tier-0 retrieval-quality gate: `pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.70`. |
| `up` | Starts `arxmcp-server` via `python -m server.main` (honors `ARXMCP_BIND_HOST` / `ARXMCP_BIND_PORT`). |
| `ingest` | Stub — prints redirect to `tools/curate_seed.py` + `tools/fetch_seed.py` and exits 1 (real ingest driver lands in E11). |

### `pyproject.toml`

- **`requires-python = ">=3.11"`**, build-system `setuptools>=64` + wheel.
- **Packages installed**: `server`, `ingest`, `tools`, `shim`.
- **Console script**: `arxmcp-shim = shim.arxmcp_shim:main`.
- **Pytest markers**: `requires_model` (skipped by default; opt-in via env var), `eval` (Tier-1→Tier-2 exit gate).
- **Ruff config**: line-length 100, target py311, selects `E F I B UP SIM`.

### Runtime deps (with pins)

```
beautifulsoup4>=4.12    # LaTeXML HTML5 parser
transformers>=4.40      # BGE-M3 tokenizer + model
torch>=2.0              # BGE-M3 forward pass (CPU default)
safetensors>=0.4        # Threat 6: safetensors-only loading
numpy>=1.24             # NPZ store backing
lancedb>=0.6            # Vector store
pyarrow>=14.0           # LanceDB chunks-table schema
rank-bm25>=0.2          # In-process BM25 (H4 closure)
mcp>=1.27,<2            # MCP 2025-06-18 SDK; Streamable HTTP
fastapi>=0.115          # ASGI framework
uvicorn[standard]>=0.30 # ASGI server (uvloop+httptools)
pydantic-settings>=2.4  # ARXMCP_* env loading
prometheus-client>=0.20 # /metrics exposition
pyyaml>=6.0             # router_patterns.yaml loader (safe_load)
faiss-cpu>=1.7          # Tier-2 cache (IndexFlatIP)
kuzu==0.11.3            # Embedded citation graph (pinned exact; upstream archived 2025-10-10)
```

Dev extras: `ruff>=0.5`, `pytest>=8.0`.

---

## 2. `server/` — MCP runtime

### Module purposes (each in one line)

| File | Purpose |
|---|---|
| `server/main.py` | FastAPI app factory + lifespan + Streamable HTTP mount; pure-ASGI `BodySizeCapMiddleware`; `__main__` entry that honors `ARXMCP_BIND_*`. |
| `server/config.py` | `pydantic-settings` `Config` class — rejects non-loopback bind, validates port range/concurrency/byte cap at parse time. |
| `server/resources.py` | Lifecycle container: BGE-M3 embedder, LanceDB chunks-table handle, optional reranker, semaphores, singleflights. |
| `server/corpus.py` | Read-only LanceDB `open_chunks_table()` with MVCC `dataset.checkout(version=N)` pinning. |
| `server/health.py` | `/healthz` (liveness, always 200) + `/readyz` (503 until embedder+LanceDB warm). |
| `server/metrics.py` | Prometheus cache-tier counters (`arxmcp_cache_lookups_total{tier}`, `_hits_total`, `_evictions_total`, `_bytes`). |
| `server/middleware.py` | Five ASGI middlewares: `OriginValidation`, `SecurityHeaders`, `RequestBodySizeLimit`, `HostValidation`, `SessionCap`. |
| `server/session.py` | Per-session retrieval-cap state (3 search calls, 4 chunk calls per `Mcp-Session-Id`). |
| `server/_mcp_mount.py` | Thin adapter calling `FastMCP.streamable_http_app()` and mounting at `/mcp`. |
| `server/tools.py` | 7-tool registration; frozen `ToolMeta` dataclasses; `envelope()` + `enforce_byte_cap()` helpers. |
| `server/router.py` | YAML-pattern-driven query classifier (4 `RouteTag`s); H1 closure (no LLM planner). |
| `server/router_patterns.yaml` | 18 named regex patterns mapped to `RouteTag.{LOOKUP,SYNTHESIS,VERIFICATION,AUTOFORMALIZATION}`. |
| `server/cache.py` | 3-tier retrieval cache singleton (Tier-1 exact, Tier-2 FAISS semantic, Tier-3 rerank-set). |
| `server/cache_sqlite.py` | Tier-1 SQLite persistence with TTL-priority eviction; WAL mode; corpus-version keyed. |
| `server/graph_queries.py` | `cite_neighbors(chunk_id, depth, direction, max_results, kuzudb_path)` — read-side Kùzu query API. |
| `server/graph_types.py` | `CitationNeighbor` dataclass (`chunk_id`, `paper_id`, `edge_kind`, `hop_distance`, `source`, `confidence`). |
| `server/query_encoder.py` | Singleflight wrapper for BGE-M3 query encoding with 100ms post-completion dedup window. |
| `server/prompts.py` | Role-prefix constants for the 4 agent roles (`MappingProxyType` frozen; ≤50 tokens each); BP1+BP2 cache contract. |
| `server/prompts.md` | Prompt-cache breakpoint strategy doc. |
| `server/schemas/search_papers_result.json` | JSON-schema pin for the `search_papers` result envelope. |

### Server entry point (`server/main.py`)

- **Framework**: FastAPI 0.115+ via `create_app()` factory; lifespan-based startup/shutdown (NOT deprecated `@app.on_event`).
- **MCP transport**: Streamable HTTP at `/mcp`, mounted via `FastMCP("arxmcp", json_response=True).streamable_http_app()`. Single-shot `application/json` (no SSE).
- **Bind**: 127.0.0.1 only (loopback-only validator in `Config`). Default port 7733.
- **Health**: `/healthz`, `/readyz`, `/metrics` (Prometheus default registry).
- **Eager startup**: BGE-M3 + LanceDB + (optional) reranker loaded BEFORE `/readyz` flips to 200.
- **Shutdown drain**: 30s budget via `asyncio.wait_for(resources.shutdown(), timeout=30)`.
- **Docs disabled**: `docs_url=None, redoc_url=None, openapi_url=None` (surface reduction).
- **Body-size cap**: pure-ASGI middleware enforces 256 KB on every response EXCEPT `/healthz`, `/readyz`, `/metrics`, `/mcp` (which uses `resource_link` for large payloads per MCP spec).

### MCP tools registered (`server/tools.py` + `server/handlers/*`)

Seven tools, in `ALL_TOOLS` order. Every tool carries `_meta: {"tool_schema_version": 1}` and every result includes `corpus_version`.

| Tool | Handler | Signature (key args) | Description |
|---|---|---|---|
| `search_papers` | `server/handlers/search.py::handle_search_papers` | `query: str, k: int=10, level: Literal["theorem","section","paper"]="theorem"` | Dense-only ANN over `embedding_stmt`; agg by chunk/section/paper. v1 indexes statement chunks only (proof chunks excluded until E07 dual-col RRF lands). Returns `resource_link` blocks for each row. Filter arg deferred to E07_S04. |
| `get_chunk` | `server/handlers/chunk.py::handle_get_chunk` | `chunk_id: str, include_referenced=False, include_equations=False` | Direct LanceDB lookup; >256 KB returns `body_truncated=True` + `arxmcp://chunks/<id>` resource_link. `include_*` are ignored at v1. |
| `find_equation` | `server/handlers/equation.py::handle_find_equation` | `latex_or_mathml: str, k: int=10` | Dense-only fallback (TED index deferred to E10_S03); embeds LaTeX as a query and searches `embedding_stmt`. `retrieval_mode` documents limitation. |
| `get_definitions` | `server/handlers/definitions.py::handle_get_definitions` | `paper_id: str, term: str|None=None` | Reads per-paper `preamble.json`; parses `\newcommand`/`\DeclareMathOperator`/`\def` macros into `(symbol, expansion)` pairs. |
| `find_lemma_by_name` | `server/handlers/lemma.py::handle_find_lemma_by_name` | `name: str, paper_id: str|None=None, k: int=10` | In-memory case-insensitive substring scan over chunks where `theorem_name IS NOT NULL`. FTS5 index swap lands in E10_S02. |
| `get_paper` | `server/handlers/paper.py::handle_get_paper` | `paper_id: str, version: int|None=None` | Synthesizes per-paper metadata from chunks (chunk_count, section_count, chunker_version, embedder_version). Authors/title/abstract/year/categories all NULL at v1. |
| `cite_neighbors` | `server/handlers/citations.py::handle_cite_neighbors` | `chunk_id: str, direction: Literal["citers","cited","co_cited","co_citing","depends_on"]="cited", depth: 1..3=1, limit: 1..100=30` | **v1 STUB** — returns `{neighbors: [], infrastructure_status: "deferred"}`. The real graph query lives in `server/graph_queries.py::cite_neighbors` but isn't yet wired to this tool. |

### `ARXMCP_*` env vars (declared on `Config`)

- `ARXMCP_BIND_HOST` (default `127.0.0.1`; rejects non-loopback at parse time)
- `ARXMCP_BIND_PORT` (default `7733`; range 1024..65535)
- `ARXMCP_LANCEDB_PATH` (default `var/arxmcp/index/lancedb`)
- `ARXMCP_CACHE_DB_PATH` (default `var/arxmcp/cache/retrieval.db`)
- `ARXMCP_ENABLE_RERANK` (default `False`)
- `ARXMCP_RERANK_MODEL_SHA` (default `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`)
- `ARXMCP_MAX_CONCURRENT_EMBEDDINGS` (default `8`)
- `ARXMCP_MAX_CONCURRENT_RERANKS` (default `4`)
- `ARXMCP_RESULT_BYTE_CAP` (default `262144` = 256 KB)
- `ARXMCP_LOG_LEVEL` (default `INFO`)

Unknown `ARXMCP_*` env vars are rejected at startup by `_scan_unknown_arxmcp_env_vars` (closes F4 from E06_S01 critique).

### Caching (`server/cache.py`, `server/cache_sqlite.py`)

- **Tier 1 — Exact-query memo**: SQLite-backed, max 10K rows, 1-hour TTL, WAL mode, corpus-version keyed; in-process LRU mirror (`OrderedDict.move_to_end`).
- **Tier 2 — Semantic-query memo**: FAISS `IndexFlatIP` over recent query embeddings (ring of 1000); hit ≡ cosine ≥0.97 AND exact filter match; 15-min TTL.
- **Tier 3 — Rerank-set memo**: in-process LRU keyed by `sha256(query_vec + sorted_chunk_ids + reranker_version)`; 1-hour TTL.
- **Failure mode**: every tier wraps lookup/write in `try/except Exception` — worst case is cache miss, never correctness failure.
- **Metrics**: per-tier `lookups_total`, `hits_total`, `evictions_total` counters + `bytes` gauge, exposed at `/metrics`.

### Orchestrator (`server/orchestrator/`)

- `id_canon.py::canonicalize_turn` — rewrites Anthropic-issued `tool_use_id` values to deterministic `toolu_{counter:08d}` form so a tool call in agent A doesn't blow agent B's prompt cache (BP1 invariant).
- `model_selector.py` — pure-lookup policy from `(RouteTag, TurnType)` → Anthropic model. Haiku 4.5 default for retrieval + draft turns; Sonnet 4.6 ONLY for Autoformalizer's Lean-syntax write step. Opus 4.7 strictly forbidden in `server/` source (AC #4). Verifier pass DROPPED (H10).
- `test_id_canon.py` — re-export stub satisfying the brief AC `pytest server/orchestrator/test_id_canon.py`; real tests live at `tests/test_id_canon.py`.

### Retrieval (`server/retrieval/`)

- `bm25.py` — Phase 1 BM25 from `var/arxmcp/index/bm25/v<N>/bm25.pkl` + `chunk_ids.json` sidecars (built by `ingest/bm25_indexer.py`). Pickle loader hardening (`_assert_pickle_file_safe`) refuses world-writable paths.
- `ann.py` — Phase 2 dual-ANN over `embedding_stmt` + `embedding_proof` columns. ONE BGE-M3 query vector reused against both columns. Cosine = `max(0, 1 - dist/2)`.
- `rrf.py` — Reciprocal Rank Fusion (k=60); pure-Python over `Sequence[Sequence[chunk_id]]`.
- `rerank.py` — Phase 3 BGE-reranker-v2-m3 cross-encoder. Default-off via `ARXMCP_ENABLE_RERANK`. Singleflight key + Tier-3 cache.

### Middleware stack (`server/middleware.py`, mount order in `server/main.py`)

Request flow (outermost → innermost): `SecurityHeaders` → `OriginValidation` → `HostValidation` → `RequestBodySizeLimit` → `SessionCap` → `BodySizeCap` → handler.

- `OriginValidationMiddleware` — MCP 2025-06-18 spec MUST; 403 on non-loopback `Origin`.
- `SecurityHeadersMiddleware` — adds `X-Content-Type-Options: nosniff` + `X-Frame-Options: DENY`.
- `RequestBodySizeLimitMiddleware` — 1 MB cap on incoming request bodies (uvicorn has no built-in knob).
- `HostValidationMiddleware` — Threat 5 / DNS rebinding defense; extends FastMCP's `/mcp`-only check across the FastAPI app.
- `SessionCapMiddleware` — per-`Mcp-Session-Id` retrieval caps (3 search_papers + 4 get_chunk).

### Routes

- `server/routes/debug.py` — `/debug/cache-stats` for operational introspection (not exempt from the 256 KB cap).

### Router (`server/router.py` + `server/router_patterns.yaml`)

Synchronous regex-based classifier; <1 ms on a 200-char query. 18 named patterns map to four `RouteTag`s: `LOOKUP`, `SYNTHESIS`, `VERIFICATION`, `AUTOFORMALIZATION`. First-match-wins priority: Autoformalization > Verification > Lookup > Synthesis. Default tag on no-match: `LOOKUP` (cheapest role). Closes H1 (no Sonnet planner).

---

## 3. `ingest/` — corpus pipeline

| Module | Purpose |
|---|---|
| `ingest/chunker.py` | Theorem-aware structural chunker for LaTeXML HTML5 parse trees. Statement chunks ≤512 BGE-M3 tokens; proof chunks ≤448 tokens with 64-token overlap windows. Per-paper failure → TSV log under `var/arxmcp/ops/parser-failures/`. |
| `ingest/chunker_types.py` | `ChunkRecord` dataclass. |
| `ingest/preamble.py` | Per-paper preamble macro extractor — reads root .tex, matches `\newcommand` / `\DeclareMathOperator` / `\def` / `\let`, writes `var/arxmcp/corpus/preamble/<paper_id>/preamble.json`. Idempotent via SHA-256 of source. |
| `ingest/preamble_types.py` | `PreambleDoc` dataclass. |
| `ingest/tokenizer.py` | Math-aware regex pre-tokenizer producing `body_tokens` for BM25. NFC-normalized; strips `$...$` math; emits `command_arg` tokens (e.g. `\mathbb{Z}` → `mathbb_Z`). |
| `ingest/embedder.py` | Dual-column BGE-M3 embedder. `kind=="proof"` → `embedding_proof`; everything else → `embedding_stmt`. Writes NPZ to `var/arxmcp/corpus/embeddings/<paper_id>/embeddings.npz`. Pinned `BGE_M3_COMMIT_SHA`, `trust_remote_code=False`, safetensors-only (Threat 6). |
| `ingest/schema.py` | Single source of truth for LanceDB `chunks` v1 schema (`CHUNKS_SCHEMA_V1`); fixed PyArrow column order for byte-stability. |
| `ingest/store.py` | LanceDB `chunks` table writer. Idempotent `merge_insert(on="chunk_id")` upsert. Builds HNSW indices on `embedding_stmt`/`embedding_proof` + scalar index on `paper_id` after every write. |
| `ingest/identifiers.py` | Single source of truth for `paper_id` + `chunk_id` regexes (F11 close); imported by chunker, server handlers, eval validator. |
| `ingest/bm25_indexer.py` | Builds per-corpus-version BM25 index from pinned LanceDB version → pickled to `var/arxmcp/index/bm25/v<N>/bm25.pkl` + `chunk_ids.json`. |
| `ingest/kuzudb_schema.py` | Idempotent Kùzu schema migration at `var/arxmcp/index/kuzu/`. Two tables: `papers` (paper_id PK, title, abstract, authors, year, categories, oa_work_id) and `cites` rel (source `openAlex`/`inspire`/`intra-paper`, confidence). |
| `ingest/graph_ingest.py` | **E09_S01** — OpenAlex bulk citation ingest. Two-pass: resolve arxiv_id → oa_work_id; then walk `referenced_works` and emit in-corpus `cites` edges. UA `arXMCP/0.1 (mailto:$ARXMCP_CONTACT_EMAIL)`. |
| `ingest/inspire_ingest.py` | **E09_S02** — INSPIRE-HEP per-paper enrichment. Sets `doi`/`journal_ref`/`inspire_id` on `papers` nodes; emits `cites` edges with `source="inspire"`. Filters to hep-th/math-ph by parsing `metadata.arxiv_eprints[*].categories` post-fetch. |
| `ingest/intra_paper_refs.py` | **E09_S03** — intra-paper `\ref{}` static analysis. Scans LaTeXML HTML for `<a class="ltx_ref" href="#<label>">` and emits `cites` edges with `source="intra-paper"`, `confidence=1.0`. |

---

## 4. `tests/` — test suite

**1316 tests collected** by pytest. Test files:

| File | Description |
|---|---|
| `tests/conftest.py` | Autouse fixtures: `_patched_store_paths` (test-local var/ tree), `KMP_DUPLICATE_LIB_OK` workaround for OpenMP collision (faiss-cpu + PyTorch on macOS). |
| `tests/_graph_helpers.py` | Shared LanceDB + Kùzu fixture builders for E09 milestones (used by proof_chain test). |
| `tests/test_arxiv_fetch.py` | arXiv `/e-print/` politeness + LaTeXML invocation tests. |
| `tests/test_bm25.py` | BM25 indexer (ingest side). |
| `tests/test_cache.py` | 3-tier retrieval cache. |
| `tests/test_chunker.py` | Theorem-aware chunker. |
| `tests/test_chunker_ids.py` | Chunk ID determinism. |
| `tests/test_corpus_version.py` | MVCC corpus-version pinning. |
| `tests/test_embedder.py` | BGE-M3 embedder. |
| `tests/test_embedder_idempotent.py` | Re-embed idempotency. |
| `tests/test_fetch_seed.py` | 50-paper seed-fetch script. |
| `tests/test_graph_ingest.py` | OpenAlex ingest (E09_S01). |
| `tests/test_graph_queries.py` | `cite_neighbors` graph query (E09_S03/S04). |
| `tests/test_id_canon.py` | Tool-use ID canonicalization (E08_S04). |
| `tests/test_identifiers.py` | Identifier regex single-source-of-truth. |
| `tests/test_inspire_ingest.py` | INSPIRE-HEP enrichment (E09_S02). |
| `tests/test_intra_paper_refs.py` | Intra-paper `\ref{}` ingest (E09_S03). |
| `tests/test_model_selector.py` | Orchestrator model-selection policy. |
| `tests/test_mvcc.py` | LanceDB MVCC handshake. |
| `tests/test_preamble.py` | Preamble macro extraction. |
| `tests/test_prompts.py` | Role-prefix constants + BP1+BP2 contract. |
| `tests/test_proof_chain.py` | Multi-paper proof-chain workflow (E09_S04 perf gate). |
| `tests/test_query_encoder.py` | Singleflight BGE-M3 query encoder. |
| `tests/test_rectifications.py` | Critique-remediation regression coverage. |
| `tests/test_router.py` | Query router + pattern compilation. |
| `tests/test_security.py` | Origin/Host validation, body-size cap, security headers. |
| `tests/test_server_startup.py` | Lifespan, /healthz, /readyz, env-var bind overrides. |
| `tests/test_server_tool_schema.py` | Byte-stability of the `tools/list` response (BP1). |
| `tests/test_session_caps.py` | Per-session retrieval cap enforcement (E08_S04). |
| `tests/test_shim.py` | stdio↔HTTP shim. |
| `tests/test_snippet_contract.py` | 150-char snippet contract (E06_S04). |
| `tests/test_store.py` | LanceDB writer + HNSW index creation. |
| `tests/test_tier_gates_doc.py` | TIER-GATES.md spec compliance. |
| `tests/test_tokenizer.py` | Math-aware regex pre-tokenizer. |
| `tests/test_tools_all.py` | Cross-tool integration + envelope sanity. |
| `tests/eval/test_retrieval_quality.py` | nDCG@5/Recall@10 against 20-query fixture; the Tier-0/Tier-1 gate (`--ndcg-min=0.70`). |
| `tests/eval/test_fixtures.py` | Eval-fixture validator (cold-start matrix). |
| `tests/eval/test_metrics.py` | nDCG / Recall metric implementations. |
| `tests/eval/metrics.py` | nDCG@k and Recall@k pure functions. |
| `tests/retrieval/test_bm25.py` | Phase 1 BM25 query. |
| `tests/retrieval/test_ann.py` | Phase 2 dual-ANN + RRF. |
| `tests/retrieval/test_rerank.py` | Phase 3 BGE reranker. |
| `tests/fixtures/chunker/` | Per-paper chunker golden fixtures. |
| `tests/fixtures/preamble/` | Preamble extraction golden fixtures. |
| `tests/eval/fixtures/queries.json` | The hand-curated 20-query retrieval-quality fixture. |

---

## 5. `tools/` — dev utilities

| Script | Purpose |
|---|---|
| `tools/arxiv_fetch.py` | Shared helpers: `fetch_eprint`, `parse_with_latexml`, `build_user_agent`, politeness (3s sleep, 503 backoff). Used by both `fetch_one_paper.py` and `fetch_seed.py`. |
| `tools/fetch_one_paper.py` | Single-paper smoke test of the arXiv `/e-print/` + LaTeXML pipeline (E01_S02). |
| `tools/curate_seed.py` | Pre-filter math.AG candidates from `export.arxiv.org/api/query` for human review (TSV output). |
| `tools/fetch_seed.py` | Walk `tools/seed-papers.txt`, fetch + LaTeXML-parse each paper; idempotent (skip if `parsed/<id>/index.html` exists). Exits 0 if ≥45/50 succeed. |
| `tools/validate_eval_fixtures.py` | Validates `tests/eval/fixtures/queries.json` (stale-id detection, structural invariants). Wrapped by `tests/eval/test_fixtures.py`. |
| `tools/seed-papers.txt` | 50 hand-curated math.AG arXiv IDs (post-2018, single-author/small collab, amsart-style). |

---

## 6. `shim/` — MCP stdio shim

`shim/arxmcp_shim.py` (`arxmcp-shim` console-script entry point):

- stateless stdio↔HTTP MCP proxy; one process per Claude Code sub-agent.
- Loopback-only egress: `--server` URL host must be `127.0.0.1`/`::1`/`localhost` (rejects malicious `~/.claude.json`).
- **Byte-pass-through**: never calls `json.loads` on request/response bodies — preserves byte-stability of tool schemas.
- Synthesizes JSON-RPC error envelopes for non-200 HTTP responses so Claude Code's stdio client sees well-formed errors.
- Default server URL: `http://127.0.0.1:7733`.

---

## 7. `docker/` + `infra/` — deployment

### `docker/Dockerfile.server`

- Multi-stage: `builder` (python:3.11-slim + build-essential, builds wheel) → `runtime` (python:3.11-slim, installs wheel into `/opt/venv`).
- Non-root user `arxmcp` (UID 1000); `tini` as PID 1; exposes 7733; `HEALTHCHECK` on `/readyz` (5-min start-period for first BGE-M3 download).
- `CMD ["python", "-m", "server.main"]` — honors `ARXMCP_BIND_*` env vars.
- Volume `/app/var/arxmcp` declared writable for read-only-FS deployments.

### `infra/`

Only `infra/README.md` exists — placeholder for the docker-compose layout deferred to E14.

---

## 8. `var/` — gitignored data tree

Created by `make bootstrap`:

```
var/arxmcp/
├── corpus/
│   ├── raw/       (arXiv tarball extractions)
│   ├── parsed/    (LaTeXML HTML5 output)
│   └── chunks/    (per-paper ChunkRecord JSON files)
├── index/
│   ├── lancedb/   (LanceDB chunks.lance dataset)
│   ├── kuzu/      (Kùzu citation graph; brief AC#1 calls this "kuzudb/" but design notes + Makefile use "kuzu/" — drift)
│   └── bm25/v<N>/ (per-corpus-version BM25 pickle + chunk_ids.json)
├── cache/
│   ├── ar5iv/     (HTML cache for LaTeXML)
│   └── retrieval.db  (Tier-1 SQLite cache)
└── ops/
    └── parser-failures/  (TSV failure logs)
```

---

## 9. What arXMCP can do TODAY

**Shipped capabilities** — each maps to a module that actually runs:

| Capability | Implementation |
|---|---|
| Fetch arXiv papers (single + 50-paper seed) | `tools/fetch_one_paper.py`, `tools/fetch_seed.py` |
| Pre-filter math.AG candidates by metadata | `tools/curate_seed.py` |
| LaTeXML HTML5 + MathML parse | `tools/arxiv_fetch.py::parse_with_latexml` |
| Extract per-paper preamble macros | `ingest/preamble.py` |
| Theorem-aware structural chunking with proof overflow split | `ingest/chunker.py` |
| Math-aware regex pre-tokenization for BM25 | `ingest/tokenizer.py` |
| Dual-column BGE-M3 embedding (stmt + proof; `embedding_eq` reserved) | `ingest/embedder.py` |
| Idempotent LanceDB chunk upsert with HNSW + scalar indices | `ingest/store.py` |
| BM25 per-corpus-version pickle index | `ingest/bm25_indexer.py` |
| Kùzu citation-graph schema migration | `ingest/kuzudb_schema.py` |
| OpenAlex bulk citation ingest | `ingest/graph_ingest.py` |
| INSPIRE-HEP enrichment of hep-th/math-ph papers | `ingest/inspire_ingest.py` |
| Intra-paper `\ref{}` chain ingest | `ingest/intra_paper_refs.py` |
| Run `arxmcp-server` on 127.0.0.1:7733 | `server/main.py` |
| Streamable HTTP MCP transport at `/mcp` | `server/_mcp_mount.py` + `mcp` SDK |
| stdio↔HTTP bridge for Claude Code | `shim/arxmcp_shim.py` |
| Liveness + readiness + Prometheus metrics | `server/health.py`, `server/metrics.py` |
| 256 KB inline result cap with `resource_link` fallback | `server/main.py::BodySizeCapMiddleware`, `server/tools.py::enforce_byte_cap` |
| Loopback-only bind + origin/host/body-size hardening | `server/config.py`, `server/middleware.py` |
| Per-session retrieval caps (3 search + 4 chunk) | `server/session.py`, `SessionCapMiddleware` |
| MVCC corpus-version pinning | `server/corpus.py::open_chunks_table` |
| Singleflight BGE-M3 query encoder | `server/query_encoder.py` |
| 3-tier retrieval cache with Prometheus metrics | `server/cache.py`, `server/cache_sqlite.py`, `server/metrics.py` |
| Regex query router → 4 agent roles | `server/router.py`, `server/router_patterns.yaml` |
| Tool-use ID canonicalization for prompt-cache stability | `server/orchestrator/id_canon.py` |
| Model selection policy (Haiku/Sonnet, no Opus) | `server/orchestrator/model_selector.py` |
| Role-prefix constants (BP1+BP2 cache breakpoints) | `server/prompts.py` |
| **Tools/list** with 7 frozen tool meta records | `server/tools.py::register_all` |
| **search_papers** (dense-only ANN; stmt column; level=theorem/section/paper) | `server/handlers/search.py` |
| **get_chunk** (LanceDB lookup; resource_link for >256 KB) | `server/handlers/chunk.py` |
| **find_equation** (dense fallback over `embedding_stmt`) | `server/handlers/equation.py` |
| **get_definitions** (per-paper macro table from preamble.json) | `server/handlers/definitions.py` |
| **find_lemma_by_name** (in-memory substring scan over `theorem_name`) | `server/handlers/lemma.py` |
| **get_paper** (chunks-synthesized metadata) | `server/handlers/paper.py` |
| **cite_neighbors** *(STUB)* — registered tool but returns `{neighbors: [], infrastructure_status: "deferred"}` | `server/handlers/citations.py` |
| Citation-graph read API (NOT yet exposed as a tool) | `server/graph_queries.py::cite_neighbors` |
| BM25 + dual-ANN + RRF + (optional) BGE reranker pipeline | `server/retrieval/{bm25,ann,rrf,rerank}.py` |
| Retrieval-quality eval gate (nDCG@5, Recall@10) | `tests/eval/test_retrieval_quality.py`, `tests/eval/metrics.py` |
| Eval-fixture validator + cold-start matrix | `tools/validate_eval_fixtures.py` |
| Docker image with multi-stage build, non-root user, tini | `docker/Dockerfile.server` |

**The retrieval pipeline modules exist (`server/retrieval/{bm25,ann,rrf,rerank}.py`) but the `search_papers` handler at v1 ships dense-only**: the BM25+RRF+reranker fusion is wired in code paths but `handle_search_papers` currently goes straight to `embedding_stmt` ANN. End-to-end hybrid wire-up is part of E07's later milestones.

---

## 10. What's NOT shipped yet

Per `.claude/roadmap/README.md` epic status:

- **E10 — Specialized Indices**: equation TED index (Zhang-Shasha over canonical MathML), FTS5 theorem-name index, full equation similarity (closes H5).
- **E11 — Scale Cutover**: production ingest driver, GPU embedding, 200K backfill, drift watchdog (`make ingest` is a stub that exits 1 today).
- **E12 — Full Corpus**: marked SCOPED_OUT (folded into E11).
- **E13 — Security Hardening**: future hardening pass beyond E06_S05 (which already shipped).
- **E14 — Observability & Ops**: docker-compose layout, alerting, structured-log shipping.

**Specific stubs / deferrals in the shipped surface:**

- `server/handlers/citations.py` — `cite_neighbors` is a v1 stub (returns empty `neighbors`); the real query exists in `server/graph_queries.py` but isn't wired through to the MCP tool yet.
- `search_papers` does NOT accept a `filter` arg at v1 — deferred to E07_S04.
- `get_chunk` accepts `include_referenced` + `include_equations` but ignores both (reserved for E07_S03 reranker output and E10_S03 equation atoms).
- `find_equation` is a dense fallback; the equation TED index lands in E10_S03.
- `find_lemma_by_name` is an in-memory substring scan; FTS5 swap is E10_S02.
- `get_paper` returns NULL for authors/title/abstract/year/categories — no `papers` metadata table at v1.
- `embedding_eq` column on `chunks` is reserved and always NULL.

---

## 11. Files for the README's table of contents

### Top-level
- `/Users/chris.dare/Personal/SourceCode/arXMCP/Makefile`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/pyproject.toml`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/README.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/ROADMAP.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/TIER-GATES.md`

### `server/` (most important first)
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/main.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/tools.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/config.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/resources.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/handlers/` (directory; 7 handler files)
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/retrieval/` (bm25/ann/rrf/rerank)
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/orchestrator/` (id_canon + model_selector)
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/graph_queries.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/graph_types.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/cache.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/cache_sqlite.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/middleware.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/session.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/router.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/router_patterns.yaml`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/health.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/metrics.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/prompts.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/prompts.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/query_encoder.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/corpus.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/server/schemas/search_papers_result.json`

### `ingest/`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/ingest/chunker.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/ingest/preamble.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/ingest/embedder.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/ingest/schema.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/ingest/store.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/ingest/identifiers.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/ingest/tokenizer.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/ingest/bm25_indexer.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/ingest/kuzudb_schema.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/ingest/graph_ingest.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/ingest/inspire_ingest.py`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/ingest/intra_paper_refs.py`

### Tests
- `/Users/chris.dare/Personal/SourceCode/arXMCP/tests/` (directory; 1316 collected tests, eval gate under `tests/eval/`)

### `docs/` (public-facing)
- `/Users/chris.dare/Personal/SourceCode/arXMCP/docs/install.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/docs/chunker-fixtures.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/docs/eval-curation.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/docs/model-policy.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/docs/orchestrator-rules.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/docs/proof-chain-workflow.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/docs/retrieval-quality-report.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/docs/snippet-contract.md`

### `.claude/notes/` (design constitution — link, don't paraphrase)
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/notes/01-mission-and-context.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/notes/02-architecture-overview.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/notes/03-ingestion-pipeline.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/notes/04-parsing-and-chunking.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/notes/05-storage-and-indexing.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/notes/06-mcp-server-design.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/notes/07-multi-agent-caching.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/notes/08-security-observability-ops.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/notes/09-feature-priorities.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/notes/10-references-and-prior-art.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/notes/HANDOFF.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/notes/README.md`

### `.claude/roadmap/` (epic-level plans)
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/roadmap/README.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/roadmap/E01-shipped.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/roadmap/E02-chunker.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/roadmap/E03-embedder.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/roadmap/E04-vector-store.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/roadmap/E05-eval-harness.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/roadmap/E06-mcp-server.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/roadmap/E07-hybrid-retrieval.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/roadmap/E08-agent-runtime.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/roadmap/E09-citation-graph.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/roadmap/E10-specialized-indices.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/roadmap/E11-scale-cutover.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/roadmap/E12-full-corpus.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/roadmap/E13-security.md`
- `/Users/chris.dare/Personal/SourceCode/arXMCP/.claude/roadmap/E14-observability-ops.md`
