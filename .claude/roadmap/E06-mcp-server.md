# E06 — MCP Server

Epic dependencies: E04 (LanceDB chunks table shipped), E05 (retrieval eval harness shipped)

Goal: Ship a production-ready Streamable HTTP MCP server bound to `127.0.0.1:7733`, exposing exactly 7 tools over the arXiv corpus. The server must satisfy byte-stable caching constraints, enforce localhost-only security, and carry a stdio shim so Claude Code sub-agents can connect without configuration friction.

Effort: L + M + L + M + S + S = XL total

References: `.claude/notes/06-mcp-server-design.md` lines 1–366, `.claude/notes/07-multi-agent-caching.md` lines 40–60

---

### E06_S01 — FastAPI server skeleton with Streamable HTTP transport

**Status:** NEW
**Tier:** 1
**Effort:** L
**Dependencies:** E04_S03, E04_S04

**Description.** Stand up the long-running `arxmcp-server` process: a FastAPI application wired to the `mcp` Python library using the Streamable HTTP transport as defined in the MCP specification dated 2025-06-18 (`https://modelcontextprotocol.io/specification/2025-06-18`). The server binds exclusively to `127.0.0.1` on port 7733 (overridable via `ARXMCP_BIND_PORT`). On startup it reads `corpus-version.json` to obtain `corpus_version: int`, calls `dataset.checkout(version=corpus_version)` on the LanceDB chunks dataset (per E04_S02 — manual symlink swaps are explicitly prohibited), and pins that version for the entire process lifetime — running sessions are never surprised by a mid-flight corpus swap.

The server owns three expensive resources that must be initialized once and reused: (1) the embedder (bge-m3 loaded into GPU/CPU memory), (2) the reranker (BGE-reranker-v2-m3, loaded only when `ARXMCP_ENABLE_RERANK=true`), and (3) a read-only LanceDB connection. Bounded asyncio semaphores gate concurrent access: `max_concurrent_embeddings=8`, `max_concurrent_reranks=4`. A `Singleflight` asyncio class (pattern documented in `.claude/notes/07-multi-agent-caching.md` lines 197–223) wraps the embedder so that N concurrent agents asking the same query produce exactly one in-flight embedding call.

The `Mcp-Session-Id` header must be globally unique and cryptographically secure (UUID4 at minimum) — it feeds per-session rate-limit and observability instrumentation. Tool input validation is a MUST per the MCP spec's Tools section; use Pydantic models as the validation layer, not ad-hoc checks. Tool result payloads are capped at 256 KB inline; larger payloads must be returned via `resource_link`.

Shutdown drains in-flight requests with a 30-second asyncio deadline, then closes LanceDB and flushes Prometheus metrics. Health endpoints: `GET /healthz` (liveness, always 200 if process is up); `GET /readyz` (readiness, 200 only after embedder, LanceDB, and reranker are warm); `GET /metrics` (Prometheus exposition).

**Deliverables.**
- `server/main.py` — FastAPI app, lifespan context manager, MCP lib wiring, Streamable HTTP mount
- `server/config.py` — pydantic-settings Config class reading all `ARXMCP_*` env vars with defaults
- `server/resources.py` — startup initialization of embedder, reranker, LanceDB; Singleflight wrapper
- `server/health.py` — `/healthz`, `/readyz`, `/metrics` routes
- `tests/test_server_startup.py` — asserts server reaches readiness within 30s in a test fixture
- `docker/Dockerfile.server` — multi-stage build; non-root user; exposes 7733

**Acceptance criteria.**
- [ ] `pytest tests/test_server_startup.py` passes: server reaches `/readyz` 200 within 30 seconds
- [ ] `GET /healthz` returns 200 before readiness (pure liveness check)
- [ ] `GET /readyz` returns 503 until embedder + LanceDB are initialized, then 200
- [ ] `ARXMCP_BIND_HOST` env var forces binding; binding to `0.0.0.0` is rejected at config parse time
- [ ] Starting two server processes on the same port raises a clear error (not a silent hang)
- [ ] `corpus_version` integer is logged at startup and matches `corpus-version.json`

**Out of scope.** Tool implementations (E06_S03). Shim binary (E06_S02). Security hardening (E06_S05). Authentication (explicitly out of v1 per notes line 358).

**Risk notes.**
- Streamable HTTP transport is the MCP 2025-06-18 spec's mandated transport; stdio for the server would defeat shared-cache semantics (`.claude/notes/06-mcp-server-design.md` lines 5–17).
- `corpus_version` pinning at startup is load-bearing for all cache key correctness (`.claude/notes/07-multi-agent-caching.md` lines 113–128).

**Labels.** `area:server`, `kind:feature`, `tier:1`

---

### E06_S02 — Stdio shim binary

**Status:** NEW
**Tier:** 1
**Effort:** S
**Dependencies:** E06_S01

**Description.** Claude Code and its sub-agents expect an MCP server registered in `~/.claude.json` under `mcpServers` as a stdio command. The `arxmcp-shim` binary bridges this expectation: it is a ~50-line stateless stdio proxy that reads JSON-RPC frames from stdin and forwards them verbatim over HTTP to `arxmcp-server`, then writes the response back to stdout. It accepts a single `--server <url>` flag (default `http://127.0.0.1:7733`).

On startup the shim performs a single `GET /readyz` probe. If the probe fails within 5 seconds, the shim prints a human-readable error to stderr and exits with code 1, giving the Claude Code UI a clear signal that the server is not running. This prevents the silent "tool not found" failure mode.

The shim is a single-file Python script (or Go binary if startup latency proves too high) installable via `pip install arxmcp` or `pipx install arxmcp`. The installed entry point is `arxmcp-shim`. Document the exact `~/.claude.json` snippet in `docs/install.md` — copy-paste, no editing required.

Because the shim is stateless and carries no authentication material, it is safe to run as a long-lived process or to be respawned per-session by Claude Code's MCP harness. Each sub-agent spawns its own shim instance; all shim instances hit the same shared `arxmcp-server` and benefit from the shared retrieval cache.

**Deliverables.**
- `shim/arxmcp_shim.py` — the ~50-line proxy; `#!/usr/bin/env python3`; no dependencies beyond stdlib
- `shim/setup.cfg` (or `pyproject.toml` entry point) — installs `arxmcp-shim` on `$PATH`
- `docs/install.md` — step-by-step: `pipx install arxmcp`; paste the JSON snippet; run `arxmcp-server`
- `tests/test_shim.py` — integration test: shim forwards a `tools/list` call and returns results

**Acceptance criteria.**
- [ ] `arxmcp-shim --server http://127.0.0.1:7733` forwards `tools/list` correctly end-to-end
- [ ] Shim exits with code 1 and a readable stderr message when `/readyz` probe fails
- [ ] Shim binary is ≤60 lines excluding comments and blank lines
- [ ] `docs/install.md` contains a verbatim `~/.claude.json` snippet matching `.claude/notes/06-mcp-server-design.md` lines 19–29

**Out of scope.** TLS (localhost only). Authentication. Any stateful session logic.

**Risk notes.**
- The shim must forward JSON-RPC verbatim; any re-serialization risks breaking byte-stability of tool schemas.

**Labels.** `area:server`, `kind:feature`, `tier:1`

---

### E06_S03 — Implement all 7 tools

**Status:** NEW
**Tier:** 1
**Effort:** L
**Dependencies:** E06_S01, E07_S01, E07_S02

**Description.** Wire up exactly 7 MCP tools. The v1 tool surface is deliberately minimal and has been rationalized from an earlier 9-tool design: `list_papers` is absorbed into `search_papers(level="paper")`; `expand_macro` is absorbed into `get_definitions(paper_id, term?)`; `dependency_graph` is absorbed into `cite_neighbors(chunk_id, depth, direction="depends_on")`; `paper_diff` is deferred to Tier 4 and out of v1.

The 7 tools and their primary argument shapes are:
1. `search_papers(query, level?, k?, filters?, cursor?)` — hybrid BM25+ANN search; `level` ∈ {paper, section, theorem}, default theorem; collapses the former `list_papers` when `level="paper"`.
2. `get_chunk(chunk_id, include_referenced?, include_equations?)` — fetch full chunk body by ID.
3. `find_equation(latex_or_mathml, k?)` — equation similarity search (backed by E10_S03 when available; graceful fallback to dense-only before that epic lands).
4. `get_definitions(paper_id, term?)` — per-paper notation table; when `term` is given, returns the macro expansion; without `term`, returns the full table; absorbs `expand_macro`.
5. `find_lemma_by_name(name, paper_id?)` — SQLite FTS5 theorem-name lookup.
6. `get_paper(paper_id, version?)` — metadata lookup from the `papers` table.
7. `cite_neighbors(chunk_id, depth?, direction?)` — citation graph traversal; `direction` ∈ {citers, cited, co_cited, co_citing, depends_on}; `direction="depends_on"` replicates the former `dependency_graph` tool behavior.

Tool schemas are defined as frozen Python dataclasses in `server/tools.py` and serialized with alphabetically sorted JSON keys. Tool descriptions are string constants — never interpolated at request time. The `tool_schema_version` integer field is included in `tools/list` responses and must be bumped deliberately on any schema change.

All tool results include `corpus_version: int` in `structuredContent`. All results are sorted deterministically: primary key is `score_desc`, tiebreak is `chunk_id_asc`. No timestamps appear in any tool result.

**Deliverables.**
- `server/tools.py` — frozen dataclass schemas + handler dispatch table for all 7 tools
- `server/handlers/search.py` — `search_papers` handler calling E07 hybrid pipeline
- `server/handlers/chunk.py` — `get_chunk` handler
- `server/handlers/equation.py` — `find_equation` handler with graceful fallback
- `server/handlers/definitions.py` — `get_definitions` handler
- `server/handlers/lemma.py` — `find_lemma_by_name` handler
- `server/handlers/paper.py` — `get_paper` handler
- `server/handlers/citations.py` — `cite_neighbors` handler with `direction` dispatch
- `tests/test_tools_all.py` — smoke test: each tool returns a valid response against the seed corpus

**Acceptance criteria.**
- [ ] `tools/list` returns exactly 7 tools — no more, no fewer
- [ ] Each tool's JSON schema validates correctly against JSON Schema Draft-07
- [ ] `search_papers(level="paper")` returns paper-level results (not chunks)
- [ ] `get_definitions(paper_id="2401.01234")` returns a full notation table
- [ ] `get_definitions(paper_id="2401.01234", term="\\mathcal{A}")` returns the expansion for that symbol only
- [ ] `cite_neighbors(chunk_id=..., direction="depends_on")` returns intra-paper theorem dependencies
- [ ] All 7 tool smoke tests pass against the 50-paper seed corpus

**Out of scope.** `paper_diff` (Tier 4, deferred). LLM-generated summaries in tool results (E06_S04 explicitly drops these). Full equation TED index (E10_S03).

**Risk notes.**
- Closing MEDIUM: 7+ tools bloat — the rationalized surface (7 tools, 3 absorptions) prevents agent confusion from an over-wide tool palette (`.claude/notes/06-mcp-server-design.md` lines 51–244).

**Labels.** `area:server`, `kind:feature`, `tier:1`

---

### E06_S04 — Snippet contract: no summary field, no Citations API

**Status:** NEW
**Tier:** 1
**Effort:** M
**Dependencies:** E06_S03

**Description.** The `search_papers` tool result shape is locked here. Every result object in `structuredContent.results` carries exactly one inline text field: `snippet`, a UTF-8 string of at most 150 characters taken directly from the start of `body_canonical` (no LLM rewriting, no truncation ellipsis beyond the character cap). The `summary` field documented in earlier notes drafts is DROPPED — it duplicates the snippet, requires a Haiku call that breaks BP1 byte-identical caching when the prompt version changes, and provides no value that `get_chunk` does not provide on demand.

The design does NOT depend on Anthropic's Citations API. The Citations API validates document blocks in the messages array, not MCP tool results; wiring tool results through Citations API blocks is architecturally unsound and would couple the MCP server to a client-side API feature. Agents that need provenance attribution call `get_chunk(chunk_id)` to retrieve the full body with metadata, then assemble citations themselves from the `paper_id`, `label`, and `section_path` fields already present in the result object.

The `resource_link` content block IS included in the `content` array alongside `structuredContent`, pointing to `arxmcp://chunks/<chunk_id>`, because the MCP spec permits it and some clients may follow it. But the agent runtime (E08) does NOT rely on the client following `resource_link` — it relies on the agent explicitly calling `get_chunk`. This dual-mode design is intentional: MCP-spec-compliant clients get the resource link for free; agents that ignore it still work correctly.

This milestone also freezes the canonical `structuredContent` schema for `search_papers` and writes a JSON Schema file at `server/schemas/search_papers_result.json` that is checked into source control and referenced in the E06_S06 byte-stability test.

**Deliverables.**
- `server/handlers/search.py` — updated to strip `summary`, truncate snippet at 150 chars, include `resource_link` in `content`
- `server/schemas/search_papers_result.json` — canonical JSON Schema for the result object
- `docs/snippet-contract.md` — one-page document stating: (a) snippet is 150 chars max, (b) no summary field, (c) no Citations API dependency, (d) agent calls `get_chunk` for full body
- `tests/test_snippet_contract.py` — asserts no `summary` key in any result; snippet ≤ 150 chars; `chunk_id` present

**Acceptance criteria.**
- [ ] `search_papers` result objects contain `snippet` (≤150 chars) and no `summary` field
- [ ] `snippet` is derived from `body_canonical` text, not from any LLM call
- [ ] `content` array contains a `resource_link` block for each result
- [ ] `tests/test_snippet_contract.py` passes against the seed corpus
- [ ] `docs/snippet-contract.md` explicitly states "No dependency on Anthropic Citations API"

**Out of scope.** LLM summary generation (permanently dropped). Citations API integration (permanently dropped). ColBERT-based snippet extraction (v1.5 feature).

**Risk notes.**
- Closes H6: inline snippets allow agents to triage relevance without a `get_chunk` round-trip, while the explicit `get_chunk` call pattern prevents unbounded context materialization.
- Closes MEDIUM: snippet+summary duplication — dropping `summary` eliminates a redundant field that broke BP1 cache stability whenever the summarizer prompt changed.
- Closes MEDIUM: Citations API — the design is explicitly decoupled from client-side API features that the agent runtime cannot guarantee.

**Labels.** `area:server`, `kind:design`, `tier:1`

---

### E06_S05 — Security hardening: Origin validation and localhost binding

**Status:** NEW
**Tier:** 1
**Effort:** S
**Dependencies:** E06_S01

**Description.** The MCP specification (2025-06-18) mandates that HTTP MCP servers validate the `Origin` header and bind only to localhost. This milestone implements both requirements and adds defense-in-depth measures appropriate for a local-only deployment.

Origin validation: any request carrying an `Origin` header whose host component is not `localhost` or `127.0.0.1` receives a 403 Forbidden response with a JSON error body. Requests without an `Origin` header (e.g., direct curl calls) are permitted — CLI tools and the stdio shim do not set `Origin`. The validation runs as a FastAPI middleware, applied before any route handler.

Localhost binding: the server config rejects `ARXMCP_BIND_HOST` values other than `127.0.0.1` and `::1` at startup — it will not silently fall back to `0.0.0.0`. Any attempt to bind to a non-loopback address is a startup error with a clear log message.

Additional hardening: (1) `X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY` headers on all responses; (2) request body size limit of 1 MB enforced by FastAPI; (3) the `Mcp-Session-Id` generated per session uses `secrets.token_hex(32)` (not UUID4, which has insufficient entropy for a session identifier); (4) `ARXMCP_LOG_LEVEL` defaults to INFO; DEBUG-level logs must never emit chunk body content.

**Deliverables.**
- `server/middleware.py` — `OriginValidationMiddleware` FastAPI middleware
- `server/config.py` — updated to reject non-loopback `ARXMCP_BIND_HOST` values
- `tests/test_security.py` — asserts 403 on non-localhost Origin; asserts startup rejects `0.0.0.0`

**Acceptance criteria.**
- [ ] `curl -H "Origin: https://evil.com" http://127.0.0.1:7733/mcp` returns HTTP 403
- [ ] `curl http://127.0.0.1:7733/mcp` (no Origin header) proceeds normally
- [ ] Starting server with `ARXMCP_BIND_HOST=0.0.0.0` exits with code 1 and a log message
- [ ] `tests/test_security.py` passes

**Out of scope.** Authentication tokens. TLS (localhost-only deployment). Rate limiting per-IP (separate ops concern).

**Risk notes.**
- `.claude/notes/06-mcp-server-design.md` lines 38–43 state both Origin pinning and localhost binding are spec obligations, not optional hardening.

**Labels.** `area:security`, `kind:hardening`, `tier:1`

---

### E06_S06 — Tool schema byte-stability test

**Status:** NEW
**Tier:** 1
**Effort:** S
**Dependencies:** E06_S03

**Description.** A casual edit to a tool description or argument schema blows every sub-agent's prompt cache (BP1 = system + tools block). This milestone makes that breakage explicit and deliberate: a pytest test computes `sha256(canonical_json(tools_list_response))` and asserts equality with a pinned hex constant checked into source control. Changing any tool schema without updating the pinned constant causes CI to fail loudly.

The canonical JSON serialization uses `json.dumps(obj, sort_keys=True, separators=(",", ":"))` — no whitespace, alphabetically sorted keys. The `tools/list` response is fetched from a live server instance started in a pytest fixture. The sha256 is computed over the UTF-8-encoded bytes of the canonical JSON string.

The pinned constant lives in `tests/test_server_tool_schema.py` as a module-level string literal with a comment explaining the update procedure: run `pytest --update-tool-schema-hash` to recompute and overwrite. The update procedure is itself tested — bumping a tool description must produce a new hash that differs from the old one.

This test enforces BP1 stability (`.claude/notes/07-multi-agent-caching.md` lines 40–49) at the CI layer. It is part of the mandatory pre-merge check.

**Deliverables.**
- `tests/test_server_tool_schema.py` — hash assertion test + `--update-tool-schema-hash` flag support
- `server/tools.py` — updated with `tool_schema_version: int = 1` field in the `tools/list` response

**Acceptance criteria.**
- [ ] `pytest tests/test_server_tool_schema.py` passes with the pinned hash
- [ ] Changing a tool description causes the test to fail
- [ ] Running `pytest --update-tool-schema-hash` regenerates the pinned constant correctly
- [ ] `tool_schema_version: 1` appears in the `tools/list` response

**Out of scope.** Automatic schema migration. Versioning of individual tools independently.

**Risk notes.**
- Tool schema byte-stability is the foundational guarantee for BP1 prompt cache reuse across the 4-agent fan-out (`.claude/notes/07-multi-agent-caching.md` lines 40–49).

**Labels.** `area:server`, `kind:test`, `tier:1`
