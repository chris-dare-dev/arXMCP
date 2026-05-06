# 06 — MCP Server Design

## Transport: Streamable HTTP, with stdio shim

Re-stating the headline correction from
[02-architecture-overview.md](02-architecture-overview.md): **stdio is wrong** for
multi-agent serving because it spawns one process per Claude client, defeating
shared caches.

Right architecture:

- **`arxmcp-server`** — long-running Streamable HTTP MCP server, bound to
  `127.0.0.1`, port configurable (default `7733`). Runs in Docker. Owns indices,
  embedder, reranker, and all caches.
- **`arxmcp-shim`** — small stdio binary (~50 lines) registered in
  `~/.claude.json` under `mcpServers`. Each Claude sub-agent spawns the shim;
  the shim proxies JSON-RPC frames over HTTP to `arxmcp-server`. Stateless.

Concrete `~/.claude.json` entry:

```json
{
  "mcpServers": {
    "arxmcp": {
      "command": "arxmcp-shim",
      "args": ["--server", "http://127.0.0.1:7733"]
    }
  }
}
```

## Spec compliance points (MCP 2025-06-18)

The MCP spec is the source of truth: `https://modelcontextprotocol.io/specification/2025-06-18`.

Key obligations we must meet:

- **Origin pinning + localhost binding.** Both. Spec quote: "Servers MUST
  validate the `Origin` header... bind only to localhost."
- **`Mcp-Session-Id` header** is globally unique and cryptographically secure.
  Used for our per-session rate limits and observability.
- **Tool input validation** is a MUST per the spec's Tools section.
- **Tool result size has no protocol limit** — we enforce our own (256 KB hard
  cap on inline content). Use `resource_link` for the long tail.
- **No protocol-level streaming of tool results.** `notifications/progress` is
  a heartbeat, not a partial-result channel. A `tools/call` returns exactly one
  `result`.
- **Pagination is defined for listings (`tools/list` cursor)**, not for tool
  call results. We roll our own via a `next_cursor` field in `structuredContent`.

## Tool surface (v1)

All tools accept JSON arguments; all return `{content: [...], structuredContent: {...}}`
where `structuredContent` is the canonical, byte-stable, cache-friendly payload.

### `search_papers`

Hybrid search across the corpus. The workhorse tool.

```jsonschema
{
  "type": "object",
  "properties": {
    "query": {"type": "string", "description": "Natural language or LaTeX-containing query"},
    "level": {"type": "string", "enum": ["paper", "section", "theorem"], "default": "theorem"},
    "k": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
    "filters": {
      "type": "object",
      "properties": {
        "categories": {"type": "array", "items": {"type": "string"}},
        "year_min": {"type": "integer"},
        "year_max": {"type": "integer"},
        "authors": {"type": "array", "items": {"type": "string"}},
        "include_withdrawn": {"type": "boolean", "default": false}
      }
    },
    "cursor": {"type": "string", "description": "Opaque continuation token from a previous call"}
  },
  "required": ["query"]
}
```

Returns:

```json
{
  "structuredContent": {
    "results": [
      {
        "chunk_id": "arxiv:2401.01234:a1b2c3d4e5f60718",
        "paper_id": "2401.01234",
        "version": 3,
        "label": "Theorem 3.4",
        "score": 0.873,
        "snippet": "Let $X$ be a smooth projective variety...",   // ≤200 chars
        "summary": "Proves flatness of X under condition Y; depends on Lemma 2.1.",
        "section_path": ["3. Main results", "3.2 The flat case"]
      }
    ],
    "next_cursor": null,
    "corpus_version": 7,
    "embed_model": "bge-m3@2024-08"
  },
  "content": [
    {"type": "resource_link", "uri": "arxmcp://chunks/arxiv:2401.01234:a1b2c3d4e5f60718", "name": "Theorem 3.4 (full text)"}
  ]
}
```

Default response is summary + snippet inline. Full chunk body is fetched via
`resource_link`. This keeps per-result inline tokens small (~300 tokens vs
~2000). For 4 agents fanning out the same retrieval, the savings compound.

### `get_chunk`

Fetch a chunk by ID. The agent calls this when it decides a snippet is worth
materializing the full body for.

```jsonschema
{
  "type": "object",
  "properties": {
    "chunk_id": {"type": "string"},
    "include_referenced": {"type": "boolean", "default": false},
    "include_equations": {"type": "boolean", "default": false}
  },
  "required": ["chunk_id"]
}
```

### `find_equation`

Equation similarity search.

```jsonschema
{
  "type": "object",
  "properties": {
    "latex": {"type": "string", "description": "LaTeX form of the target equation"},
    "k": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
    "filters": {"$ref": "#/definitions/filters"}
  },
  "required": ["latex"]
}
```

Returns equation atoms with parent chunk IDs, ranked by canonical-form
similarity (MathML → tree-edit-distance plus dense embedding).

### `get_definitions`

Per-paper notation/definition table.

```jsonschema
{
  "type": "object",
  "properties": {
    "paper_id": {"type": "string"},
    "symbol": {"type": "string", "description": "Optional filter to a specific symbol"}
  },
  "required": ["paper_id"]
}
```

Critical for the autoformalizer and tactician — answers "what does `\AA` mean
in this paper?"

### `find_lemma_by_name`

Mathlib-style exact-match lookup.

```jsonschema
{
  "type": "object",
  "properties": {
    "name": {"type": "string", "description": "e.g. 'Yoneda lemma', 'Riemann-Roch'"},
    "fuzzy": {"type": "boolean", "default": true}
  },
  "required": ["name"]
}
```

### `paper_diff`

Compare two versions of the same paper.

```jsonschema
{
  "type": "object",
  "properties": {
    "paper_id": {"type": "string"},
    "from_version": {"type": "integer"},
    "to_version": {"type": "integer"},
    "scope": {"type": "string", "enum": ["abstract", "theorems", "full"], "default": "theorems"}
  },
  "required": ["paper_id", "from_version", "to_version"]
}
```

Autoformalizers care about this: v1 often has the cleaner statement, v3 has the
corrected proof.

### `get_paper`

Metadata lookup.

```jsonschema
{
  "type": "object",
  "properties": {
    "paper_id": {"type": "string"},
    "version": {"type": "integer", "description": "Defaults to latest"}
  },
  "required": ["paper_id"]
}
```

### `cite_neighbors` (citation graph)

```jsonschema
{
  "type": "object",
  "properties": {
    "paper_id": {"type": "string"},
    "direction": {"type": "string", "enum": ["citers", "cited", "co_cited", "co_citing"], "default": "cited"},
    "depth": {"type": "integer", "minimum": 1, "maximum": 3, "default": 1},
    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30}
  },
  "required": ["paper_id"]
}
```

### `dependency_graph` (intra-paper)

```jsonschema
{
  "type": "object",
  "properties": {
    "chunk_id": {"type": "string", "description": "A theorem chunk"},
    "depth": {"type": "integer", "minimum": 1, "maximum": 5, "default": 2}
  },
  "required": ["chunk_id"]
}
```

Returns the lemmas this proof depends on, recursively.

### `expand_macro`

Utility tool for the autoformalizer.

```jsonschema
{
  "type": "object",
  "properties": {
    "paper_id": {"type": "string"},
    "macro": {"type": "string", "description": "e.g. '\\AA'"}
  },
  "required": ["paper_id", "macro"]
}
```

## Resource surface (MCP resources)

All chunks and equations are exposed as resources at deterministic URIs:

- `arxmcp://chunks/<chunk_id>` — full chunk body, MathML, raw LaTeX
- `arxmcp://equations/<equation_id>`
- `arxmcp://papers/<paper_id>` — metadata + section list
- `arxmcp://papers/<paper_id>/raw` — raw .tex tarball (gated; see security)
- `arxmcp://papers/<paper_id>/parsed` — parsed HTML5+MathML

`resources/list` returns paginated paper-level entries; per-chunk listing is
handled via `search_papers` (we don't enumerate 5M chunks).

## Determinism contract for tool results

(Repeating the rule from [02-architecture-overview.md](02-architecture-overview.md)
because it's load-bearing for caching.)

Every public-facing tool result must be bit-identical for the same
`(query, filters, k, corpus_version)` tuple. Concrete rules:

1. Results sorted by `(score_desc, chunk_id_asc)`. Ties broken deterministically.
2. Chunk IDs content-addressable.
3. No timestamps anywhere in tool results (use `corpus_version` instead).
4. No random tie-breaking.
5. JSON serialized with sorted keys (alphabetical).
6. `corpus_version` field included in every response so agents can verify
   reproducibility.
7. Tool definitions themselves are byte-stable across server restarts: pin schema,
   sort properties alphabetically, freeze descriptions in source.

A casual edit to a tool description blows every sub-agent's prompt cache. Treat
tool definitions as a versioned API surface; bump a `tool_schema_version` field
when changing them and document the change.

## Concurrency model

- Async request handler (FastAPI / aiohttp / similar) processes JSON-RPC
  requests concurrently.
- **Bounded semaphores** in front of expensive resources:
  - Embedder: `max_concurrent_embeddings = 8`.
  - Reranker: `max_concurrent_reranks = 4`.
  - LaTeXML subprocess pool (only for runtime parsing if we ever expose it):
    `max = 2`.
- LanceDB queries hold no global lock; multiple concurrent readers are safe.
- **Singleflight pattern** on the embedder: when N concurrent agents ask the
  same query, only one in-flight `embed(query)` call happens. Implementation:
  Python `asyncio.Lock` keyed by query hash, with a `dict` of `Future`s.

## Health and readiness

- `GET /healthz` — liveness. Returns 200 if process is up.
- `GET /readyz` — readiness. Returns 200 only after embedder, reranker, and
  LanceDB connection are warm. Used by Docker healthcheck and the stdio shim's
  pre-call probe.
- `GET /metrics` — Prometheus exposition format. See
  [08-security-observability-ops.md](08-security-observability-ops.md).

## Configuration

Configuration via environment variables (12-factor). Examples:

```
ARXMCP_BIND_HOST=127.0.0.1
ARXMCP_BIND_PORT=7733
ARXMCP_LANCEDB_PATH=/var/arxmcp/index/lancedb
ARXMCP_KUZU_PATH=/var/arxmcp/index/kuzu/citations.kuzu
ARXMCP_EMBED_MODEL=BAAI/bge-m3
ARXMCP_RERANK_MODEL=BAAI/bge-reranker-v2-m3
ARXMCP_EMBED_BATCH_SIZE=32
ARXMCP_MAX_K=50
ARXMCP_RESULT_BYTE_CAP=262144
ARXMCP_LOG_LEVEL=INFO
ARXMCP_OTEL_ENDPOINT=http://localhost:4318
```

Never commit secrets to the repo. Local-only deployment means there are no
shared secrets in v1, but `ARXMCP_*_API_KEY` env vars (e.g. for Voyage
query-time embedding) are read at startup if set.

## Server lifecycle

1. **Startup:** load embedder + reranker into memory; open LanceDB at the
   `current` symlink and pin the resolved version for the process lifetime;
   open Kùzu read-only; warm caches; pass readiness check.
2. **Hot reload of corpus:** the ingestion service signals (via filesystem or
   a unix socket) that a new corpus version is available. The MCP server
   does NOT auto-switch — it continues using its pinned version. Restart the
   server to pick up the new corpus. (Rationale: agents in the middle of a
   session expect index stability.)
3. **Shutdown:** drain in-flight requests with a 30-second deadline; close
   LanceDB and Kùzu cleanly; flush metrics.

## What this server does NOT do

- Embedding model fine-tuning. (Offline tooling, separate project.)
- Corpus ingestion. (Separate process.)
- Authentication. (localhost-only.)
- Reasoning over the retrieved content. (That's the agent's job; we provide
  evidence, not answers — except via the optional `summarize` tool described
  in [07-multi-agent-caching.md](07-multi-agent-caching.md).)
- LLM-side prompt assembly. (We return canonical structured content; the agent
  assembles prompts.)
