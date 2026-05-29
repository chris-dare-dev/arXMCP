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

> **Updated 2026-05-06 (see E06_S03 in `.claude/roadmap/E06-mcp-server.md`).**
> The tool surface is rationalized to exactly **7 tools**. The former 9-tool
> design had redundancy: `list_papers` is absorbed into `search_papers(level="paper")`;
> `expand_macro` is absorbed into `get_definitions(paper_id, term?)`; `dependency_graph`
> is absorbed into `cite_neighbors(chunk_id, depth, direction="depends_on")`;
> `paper_diff` is deferred to Tier 4. Do not re-add standalone `list_papers`,
> `expand_macro`, `dependency_graph`, or `paper_diff` tools in v1.

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

> **Updated 2026-05-06 (see E06_S04 in `.claude/roadmap/E06-mcp-server.md`,
> closes MEDIUM: snippet+summary duplication).** The `summary` field is **dropped**.
> Each result carries only a ≤150-char inline `snippet` taken directly from
> `body_canonical` (no LLM rewriting). Agents that need the full body call
> `get_chunk(chunk_id)`. This design does NOT depend on the Anthropic Citations API
> or on Claude Code following `resource_link` — agents retrieve full text explicitly.

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
        "snippet": "Let $X$ be a smooth projective variety...",   // ≤150 chars; from body_canonical
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

Each result has a ≤150-char `snippet` inline for triage. Full chunk body is
fetched via an explicit `get_chunk(chunk_id)` call. `resource_link` is included
in `content` for MCP-spec-compliant clients but the agent runtime does not
rely on clients following it. This keeps per-result inline tokens small and
avoids unbounded context materialization.

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
    "paper_id": {"type": "string", "description": "Optional: restrict search to a single paper"},
    "fuzzy": {"type": "boolean", "default": true}
  },
  "required": ["name"]
}
```

### `paper_diff` — DEFERRED to Tier 4

> **Not in v1 tool surface (see E06_S03).** `paper_diff` is deferred to Tier 4.
> Autoformalizers that need version comparison should call `get_paper(paper_id, version=N)`
> twice and diff locally. Do not implement this tool until Tier 4.

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

### `cite_neighbors` (citation graph + intra-paper dependency)

> **Updated 2026-05-06 (see E06_S03).** `dependency_graph` is absorbed here via
> `direction="depends_on"`. The standalone `dependency_graph` tool is removed.

```jsonschema
{
  "type": "object",
  "properties": {
    "chunk_id": {"type": "string", "description": "A chunk ID (theorem or paper)"},
    "direction": {
      "type": "string",
      "enum": ["citers", "cited", "co_cited", "co_citing", "depends_on"],
      "default": "cited",
      "description": "Use direction='depends_on' for intra-paper theorem dependency traversal (absorbs former dependency_graph tool)"
    },
    "depth": {"type": "integer", "minimum": 1, "maximum": 3, "default": 1},
    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30}
  },
  "required": ["chunk_id"]
}
```

`direction="depends_on"` returns the lemmas a proof chunk depends on, recursively
(same semantics as the former `dependency_graph` tool).

### `dependency_graph` — ABSORBED into `cite_neighbors`

> **Not in v1 tool surface (see E06_S03).** Use `cite_neighbors(chunk_id, direction="depends_on")`.

### `expand_macro` — ABSORBED into `get_definitions`

> **Not in v1 tool surface (see E06_S03).** Use
> `get_definitions(paper_id, term="\\AA")` to expand a macro. The `term` parameter
> narrows the full notation table to a single symbol.

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

### Notebook-scoped retrieval (notebook-retrieval-m1, fork C)

By default the server reads the shared corpus at `ARXMCP_LANCEDB_PATH`
(`var/arxmcp/index/lancedb`). To serve a **per-notebook** corpus
(ingested under `var/arxmcp/notebooks/<slug>/lancedb/` by
`tools/notebook_ingest.py`), set:

```
ARXMCP_NOTEBOOK=bridgeland-stability
```

`Config.derive_notebook_lancedb_path` then rewrites `lancedb_path` to the
notebook's dataset dir **before** `Resources.startup` reads it (via the
shared `tools._notebook_common.notebook_lancedb_path` helper, which
enforces the slug regex + symlink rejection + containment — Threat 1).
Contract:

- **One notebook per server process** (v1). To switch notebooks, relaunch
  with a different `ARXMCP_NOTEBOOK`. The eventual per-call multi-notebook
  mode (`filters.notebook=<slug>`, fork A) is a follow-up that reuses the
  same helper.
- `ARXMCP_NOTEBOOK` and an explicit `ARXMCP_LANCEDB_PATH` are **mutually
  exclusive** — setting both is rejected at config-load (ambiguous
  substrate).
- If the notebook has not been ingested (no `lancedb` dir on disk), the
  server refuses to start with a remediation message naming the ingest
  command — it does not surface a deeper `CorpusNotIngestedError`.
- Retrieval is **dense-only** (the live `search_papers` path: single ANN
  over `embedding_stmt`, proof chunks excluded) regardless of notebook
  vs shared corpus — the per-difficulty-class spike confirmed hybrid +
  rerank regress on the single-topic math corpora notebooks hold.

### Per-call notebook routing (notebook-retrieval-m2, fork A)

Fork A generalizes fork C from one-notebook-per-**process** to
many-notebooks-per-**process**: a `search_papers` call carrying
`filters={"notebook": "<slug>"}` routes that single query to the named
notebook's `lancedb`, without a relaunch. It reuses the same
`tools._notebook_common.notebook_lancedb_path` + `validate_slug` seam fork C
uses, and routes the SAME dense-only `embedding_stmt` path.

Contract:

- **`notebook` is a routing key, not a retrieval filter.** It is validated
  (`validate_slug`, Threat-1) at the handler boundary, consumed there, and is
  NOT added to `SUPPORTED_FILTER_KEYS` — so it never appears in
  `filters_applied` or `filter_warnings`. It composes with `paper_id` /
  `source_kind` (which still filter *within* the routed notebook).
- **Cache isolation is structural.** `notebook` stays inside the (canonical)
  `filters` dict, so it is already part of the Tier-1 key's `filters_json` —
  two notebooks with the same query and a colliding per-dataset
  `corpus_version` get distinct cache keys with NO change to
  `canonical_key_components`. A no-`notebook` call's key is byte-identical to
  pre-m2.
- **Per-notebook table registry.** `Resources.notebook_table(slug)` lazily
  opens + memoizes notebook chunks-tables in a bounded LRU
  (`MAX_NOTEBOOK_TABLE_SLOTS = 16`, asyncio-locked lazy-open) so repeated
  per-call queries don't pay the cold-open cost.
- **`corpus_version` echo (AC6)** is the routed notebook's pinned version, via
  `envelope(payload, override_corpus_version=…)`; the no-notebook path is
  byte-identical.
- **Precedence:** an explicit per-call `filters.notebook` WINS over the
  process-level `ARXMCP_NOTEBOOK` (fork C) default.
- **fork-C ↔ fork-A cache reconciliation:** m1's per-notebook `cache_db_path`
  derivation fires only when `ARXMCP_NOTEBOOK` is set (fork C, structural
  isolation); fork A (env unset) uses the shared `cache_db_path` + slug-in-key
  (logical isolation). Two complementary mechanisms for mutually-exclusive
  modes, not two competing ones.
- The server still boots against some corpus (fork C or an ingested shared
  corpus); per-call routing reaches any *other* ingested notebook from that
  process. No tool-schema / BP1 change (the `notebook` key lives inside the
  free-form `filters` dict).

## Server lifecycle

> **Updated 2026-05-06 (see E06_S01 in `.claude/roadmap/E06-mcp-server.md`).** The
> `current` symlink is no longer used. Version is pinned by reading the integer from
> `corpus-version.json` and calling `dataset.checkout(version=N)`. See also E04_S02.

1. **Startup:** load embedder into memory; load reranker only when
   `ARXMCP_ENABLE_RERANK=true`; read `corpus-version.json` to obtain
   `corpus_version: int`; open LanceDB via `dataset.checkout(version=corpus_version)`
   and pin that read-only view for the process lifetime; open Kùzu read-only;
   warm caches; pass readiness check. **No symlink resolution.**
2. **Hot reload of corpus:** the ingestion service writes a new `corpus-version.json`.
   The MCP server does NOT auto-switch — it continues using its pinned version.
   Restart the server to pick up the new corpus. (Rationale: agents in the middle of
   a session expect index stability.)
3. **Shutdown:** drain in-flight requests with a 30-second deadline; close
   LanceDB and Kùzu cleanly; flush metrics.

## Browser UI surface

> **Added by `notebook-surface-expansion-m3` (2026-05).** Earlier revisions of the
> constitution (and `02-architecture-overview.md` / `09-feature-priorities.md`)
> treated the MCP tool surface as the sole interface, with no operator UI. That is
> now STALE: a deliberately minimal,
> **loopback-only, server-rendered Jinja2 + htmx operator console** ships
> with the server. It is an operator convenience for notebook management — NOT a
> general-purpose research front-end, and NOT an SPA. **Hard constraint: no SPA, no
> Node/npm build chain.** htmx is vendored under `frontend/static/`; templates live
> under `frontend/templates/`. The MCP tool surface remains the primary agent
> interface; this console exists alongside it.

**HTML pages — `server/routes/ui.py` (mounted at `/ui/`):**

- `GET /ui/` — landing page: notebook list + create-notebook form.
- `GET /ui/notebooks/{slug}` — per-notebook detail: paper list, add-by-URL form,
  drag-drop upload card, parse-status + "last indexed" freshness
  (notebook-surface-expansion-m1), in-page rename + delete
  (notebook-surface-expansion-m2), and a live ingest-status poll.
- `GET /ui/notebooks/{slug}/papers/{paper_id}/preview` — direct-serve of stored
  ar5iv HTML under an aggressively tight per-response CSP
  (`CONTENT_SECURITY_POLICY_PREVIEW`) with a `<meta http-equiv="refresh">` strip
  (E10/m10 hardening).
- `GET /ui/status-badge` — live operability HTML fragment for the footer badge,
  backed by the same `compute_health_status` snapshot as `/status`
  (notebook-ops-hardening-m4).

**REST / htmx API — `server/routes/notebooks.py` (mounted at `/ui/api/`):**

- `GET /ui/api/notebooks` — list; `POST /ui/api/notebooks` — create;
  `DELETE /ui/api/notebooks/{slug}` — metadata-only delete (the on-disk
  `var/arxmcp/notebooks/<slug>/` tree is wiped only by `tools/notebook_purge.py`);
  `PATCH /ui/api/notebooks/{slug}` — rename `display_name` (m2; mass-assignment
  guarded — `display_name` is the ONLY patchable field).
- `GET/POST/DELETE /ui/api/notebooks/{slug}/papers[/{paper_id}]` — paper
  list / add-by-URL / remove; `POST .../papers/upload` — PDF + ar5iv HTML upload
  (returns an HTML fragment).
- `POST /ui/api/notebooks/{slug}/ingest` + `GET .../ingest/latest` — ingest
  trigger + status poll.

**Security posture (the audit baseline; see `08-security-observability-ops.md`):**

- **Loopback-only bind** — `127.0.0.1`; non-loopback rejected at config parse.
- **Jinja2 autoescape** — the environment is constructed EXPLICITLY with
  `autoescape=select_autoescape(enabled_extensions=("html","htm","xml"),
  default_for_string=True)`. Zero `| safe` filters in any template (load-bearing —
  it is the stored-XSS guard for operator-authored fields like `display_name`).
- **CSP** — `CONTENT_SECURITY_POLICY_UI` on `/ui/*` pages; tighter
  `CONTENT_SECURITY_POLICY_PREVIEW` on the ar5iv preview route; `frame-ancestors
  'none'` in both.
- **CSRF posture** — no token, by design: `SecFetchSiteMiddleware(exempt_prefixes=
  ("/ui",))` admits `Sec-Fetch-Site: same-origin` on `/ui/*` and rejects cross-site;
  combined with `OriginValidationMiddleware` + `HostValidationMiddleware`
  (loopback-only) this is the triple-layer same-origin defense.
- **Input validation** — `validate_slug` (path-traversal regex) at every mutation
  boundary; Pydantic `Field(max_length=...)` bounds; control-char strip on
  `display_name`; PDF upload preflight (magic-byte sniff / polyglot tail-scan /
  JavaScript-token scan / declared-page-count cap). NOTE: there is NO
  decompression-bomb guard today — that is an OPEN QUESTION for the UI security
  audit, not a current defense.

> **This UI surface has NOT yet had a dedicated security audit** — E13 (Security
> Hardening) scoped the audit to the 7-tool MCP surface only. The deferred UI audit
> is tracked at `chris-dare-dev/arXMCP#9` (CAND-13; notebook-surface-expansion-m3);
> the issue body lives at
> `.claude/notes/milestones/notebook-surface-expansion-m3/ui-security-audit-issue.md`.

## What this server does NOT do

- Embedding model fine-tuning. (Offline tooling, separate project.)
- Corpus ingestion. (Separate process.)
- Authentication. (localhost-only.)
- Reasoning over the retrieved content. (That's the agent's job; we provide
  evidence, not answers — except via the optional `summarize` tool described
  in [07-multi-agent-caching.md](07-multi-agent-caching.md).)
- LLM-side prompt assembly. (We return canonical structured content; the agent
  assembles prompts.)
