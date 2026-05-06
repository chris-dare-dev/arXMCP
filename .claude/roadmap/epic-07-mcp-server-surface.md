# E07 — MCP Server Surface (Tier 1f)

**Epic dependencies:** E06.

**Goal:** stand up the full MCP server surface from `06-mcp-server-design.md`. Streamable HTTP transport with proper spec compliance (Origin pinning, localhost binding, `Mcp-Session-Id`), the v1 tool surface (with E07 implementing all "evidence" tools — full surface lands across E07/E09/E10), the resource surface, byte-stable tool definitions, lifecycle (startup/shutdown/health), and configuration.

**Effort:** ~2 weeks.

**References:** `06-mcp-server-design.md` (entire file is authoritative); `02-architecture-overview.md` § Determinism contract; `07-multi-agent-caching.md` § Property 1: Tool definitions are byte-stable.

---

### E07_S01 — Full Streamable HTTP transport with spec MUSTs

**Description.** Replace the v0 server skeleton from E01_S08 with a fully-conforming Streamable HTTP MCP server per the MCP 2025-06-18 spec. Required: Origin header validation, localhost binding, `Mcp-Session-Id` header generation (cryptographically secure, globally unique), JSON-RPC framing.

**Acceptance criteria.**
- [ ] Server validates `Origin` header — accepts only configured allow-list (default: `http://127.0.0.1:7733` + empty Origin from the shim).
- [ ] Server validates `Host` header is `127.0.0.1` or `localhost` (DNS-rebinding defense per `08-security-observability-ops.md` Threat 5).
- [ ] Server generates `Mcp-Session-Id` per the spec (UUIDv4 or HMAC-secured token).
- [ ] Server binds to `127.0.0.1` only.
- [ ] Test: request with malicious `Origin: https://evil.example.com` returns 403.
- [ ] Test: request with no `Origin` (shim case) succeeds.
- [ ] Test: request with `Host: arxmcp.attacker.example` returns 403.

**Dependencies.** none within E07 (extends E01_S08).

**Complexity.** L.

**Labels.** `area:server`, `area:security`, `kind:feature`.

---

### E07_S02 — Byte-stable tool definitions module

**Description.** Per `07-multi-agent-caching.md` § Property 1 — tool definitions must be byte-stable across server restarts. Pin schemas, sort properties alphabetically, freeze descriptions as constants. A unit test asserts `sha256(serialize_tools()) == EXPECTED_HASH`. Bumping the hash is a deliberate API version bump.

**Acceptance criteria.**
- [ ] `server/tools/definitions.py` exposes all v1 tools as frozen dataclasses with explicit JSON-Schema.
- [ ] Serialization function uses `json.dumps(..., sort_keys=True, separators=(",", ":"))`.
- [ ] Test `tests/server/test_tool_schema_hash.py` asserts `sha256(serialize_tools()) == EXPECTED`.
- [ ] `tool_schema_version` constant tracked alongside the hash.
- [ ] PR template explicitly mentions hash bump as a versioning event.
- [ ] Documented in `docs/server/tool-stability.md`.

**Dependencies.** none within E07.

**Complexity.** S.

**Labels.** `area:server`, `area:cache`, `kind:infra`, `risk:high`.

---

### E07_S03 — Implement `search_papers` with full schema and pagination cursor

**Description.** Replace the v0 `search_papers` from E01 with the full schema from `06-mcp-server-design.md`: `query`, `level`, `k`, `filters` (categories, year_min/max, authors, include_withdrawn), `cursor`. Wires E06 retrieval + canonicalization underneath. Returns the documented response shape with `results`, `next_cursor`, `corpus_version`, `embed_model`, plus `resource_link`s.

**Acceptance criteria.**
- [ ] Tool schema matches `06-mcp-server-design.md` § search_papers exactly (including alphabetically-sorted properties).
- [ ] Default `level=theorem`, default `k=10`, max `k=50`.
- [ ] `cursor` parameter is opaque base64-encoded JSON containing the last seen `(score, chunk_id)` plus filter hash; deterministic.
- [ ] Response includes `summary` (from E08 summary cache; v1 ships this as a stub returning the top hit's snippet, replaced by Haiku output in E08).
- [ ] Test: `search_papers({"query": "...", "k": 5, "filters": {"categories": ["math.AG"]}})` returns 5 results, all from math.AG.
- [ ] Test: pagination via `cursor` yields disjoint and complete result sets across calls.

**Dependencies.** E07_S01, E07_S02, E06_S07.

**Complexity.** L.

**Labels.** `area:server`, `area:retrieval`, `kind:feature`.

---

### E07_S04 — Implement `get_chunk` tool

**Description.** Per `06-mcp-server-design.md` § get_chunk — fetch a chunk by ID, optionally including referenced chunks and equation atoms. Used when an agent decides a snippet is worth materializing the full body for.

**Acceptance criteria.**
- [ ] Tool accepts `{chunk_id, include_referenced (default false), include_equations (default false)}`.
- [ ] Returns the full chunk body (canonical and raw LaTeX), MathML, label, section_path, plus optional referenced and equation appendices.
- [ ] If `include_referenced=true` and the chunk has 5 cross-references, the response inlines those 5 chunks' bodies (truncated to 2K tokens each).
- [ ] Test: known chunk ID returns expected fields.
- [ ] Test: invalid chunk ID returns JSON-RPC error -32602 with a clear error message.
- [ ] Result respects the 256 KB byte cap; spillover via `resource_link`.

**Dependencies.** E07_S01, E07_S02.

**Complexity.** M.

**Labels.** `area:server`, `area:retrieval`, `kind:feature`.

---

### E07_S05 — Implement `get_paper` metadata tool

**Description.** Per `06-mcp-server-design.md` § get_paper — return paper metadata (title, authors, abstract, categories, dates, version list, parse_status). Reads from the `papers` table populated in E05_S09.

**Acceptance criteria.**
- [ ] Tool accepts `{paper_id, version (optional, default latest)}`.
- [ ] Returns title, authors, abstract, categories, submitted/updated dates, withdrawn flag + reason, license, list of versions, n_chunks, n_equations, n_definitions, parse_status, parser_used.
- [ ] Withdrawn papers carry a clear `withdrawn=true` flag.
- [ ] Test: existing paper returns full metadata.
- [ ] Test: unknown paper returns JSON-RPC error.

**Dependencies.** E07_S01, E07_S02, E05_S09.

**Complexity.** S.

**Labels.** `area:server`, `kind:feature`.

---

### E07_S06 — MCP resource surface with deterministic URIs

**Description.** Per `06-mcp-server-design.md` § Resource surface — expose chunks, equations, papers, raw .tex tarballs, and parsed HTML at `arxmcp://...` URIs. `resources/list` returns paginated paper-level entries; per-chunk listing is via `search_papers`, not enumeration.

**Acceptance criteria.**
- [ ] `resources/list` returns paginated paper entries (`arxmcp://papers/<paper_id>`).
- [ ] `resources/read` for `arxmcp://chunks/<chunk_id>` returns the full chunk body.
- [ ] `resources/read` for `arxmcp://equations/<equation_id>` returns the equation atom.
- [ ] `resources/read` for `arxmcp://papers/<paper_id>/raw` returns the .tex tarball gated behind a config flag (default off; see E13 security gating).
- [ ] `resources/read` for `arxmcp://papers/<paper_id>/parsed` returns the parsed HTML5+MathML.
- [ ] Test: each resource URI scheme has a happy-path read test.

**Dependencies.** E07_S01.

**Complexity.** M.

**Labels.** `area:server`, `kind:feature`.

---

### E07_S07 — Health and readiness endpoints

**Description.** Per `06-mcp-server-design.md` § Health and readiness — implement `GET /healthz` (liveness) and `GET /readyz` (readiness, returns 200 only after embedder + reranker + LanceDB are warm). Used by Docker healthcheck and by the shim's pre-call probe.

**Acceptance criteria.**
- [ ] `/healthz` returns 200 with `{status: "ok"}` whenever the process is up.
- [ ] `/readyz` returns 200 only when: embedder loaded, reranker loaded, LanceDB connection open, current corpus version pinned.
- [ ] `/readyz` returns 503 with `{not_ready: [...components]}` body during startup.
- [ ] Docker healthcheck script in compose targets `/readyz`.
- [ ] Test: `/readyz` returns 503 before warm-up, 200 after.

**Dependencies.** E07_S01.

**Complexity.** S.

**Labels.** `area:server`, `area:observability`.

---

### E07_S08 — Server lifecycle: startup, version pinning, shutdown drain

**Description.** Per `06-mcp-server-design.md` § Server lifecycle — at startup, load embedder + reranker, open LanceDB at `current` symlink and pin the resolved version for the process lifetime, open Kùzu read-only, warm caches, pass readiness check. At shutdown, drain in-flight requests with a 30-second deadline.

**Acceptance criteria.**
- [ ] `server/lifecycle.py::startup()` performs all the steps in order.
- [ ] Resolved corpus version is held in process state and never re-read mid-session.
- [ ] SIGTERM triggers shutdown drain: stop accepting new requests, wait up to 30 s for in-flight, then close DB connections.
- [ ] Test: a request in flight at SIGTERM completes before shutdown.
- [ ] Test: a request started after SIGTERM is rejected with 503.
- [ ] Hot-reload of corpus is explicitly NOT auto: the server must be restarted to pick up a new version (note in `06-mcp-server-design.md` § Server lifecycle).

**Dependencies.** E07_S01, E07_S07.

**Complexity.** M.

**Labels.** `area:server`, `kind:infra`.

---

### E07_S09 — 12-factor configuration via environment variables

**Description.** Per `06-mcp-server-design.md` § Configuration — all configuration is environment-variable-driven. Document and implement: `ARXMCP_BIND_HOST`, `ARXMCP_BIND_PORT`, `ARXMCP_LANCEDB_PATH`, `ARXMCP_KUZU_PATH`, `ARXMCP_EMBED_MODEL`, `ARXMCP_RERANK_MODEL`, `ARXMCP_EMBED_BATCH_SIZE`, `ARXMCP_MAX_K`, `ARXMCP_RESULT_BYTE_CAP`, `ARXMCP_LOG_LEVEL`, `ARXMCP_OTEL_ENDPOINT`.

**Acceptance criteria.**
- [ ] `server/config.py` reads all variables with documented defaults.
- [ ] Missing required vars (e.g. `ARXMCP_LANCEDB_PATH`) cause server to exit 1 with a clear error at startup.
- [ ] No secrets in source; API-key vars (`ARXMCP_VOYAGE_API_KEY`, etc.) are optional and read at startup.
- [ ] Test: each variable has a "loads from env" test and a "default applies when unset" test where applicable.
- [ ] Documented in `docs/server/configuration.md` with a complete env-var table.

**Dependencies.** E07_S08.

**Complexity.** S.

**Labels.** `area:server`, `kind:infra`.

---

### E07_S10 — Per-session rate limits keyed on `Mcp-Session-Id`

**Description.** Per `08-security-observability-ops.md` Threat 4 — per-session rate limits. Default: 60 tool calls per minute per session, 1000 per hour. Configurable via env vars. Sessions are tracked by `Mcp-Session-Id` header.

**Acceptance criteria.**
- [ ] `server/rate_limit.py` enforces a token bucket per session.
- [ ] Limits configurable via `ARXMCP_RATE_LIMIT_PER_MINUTE`, `ARXMCP_RATE_LIMIT_PER_HOUR`.
- [ ] Exceeding triggers JSON-RPC error -32099 (custom: rate-limited) with a `retry_after` field.
- [ ] Test: 100 rapid-fire calls in 1 minute trigger rate-limit error after the 60th.
- [ ] Test: rate limit resets correctly after the window expires.
- [ ] Counter `arxmcp_rate_limit_hits_total{session_id_hash}` exposed for E14.

**Dependencies.** E07_S01, E07_S02.

**Complexity.** M.

**Labels.** `area:server`, `area:security`.

---

### E07_S11 — Concurrency model with bounded semaphores

**Description.** Per `06-mcp-server-design.md` § Concurrency model — async request handler with bounded semaphores: embedder=8, reranker=4, LaTeXML pool=2 (only relevant if runtime parsing is ever exposed; for v1 server is read-only against the index).

**Acceptance criteria.**
- [ ] Semaphores live as module-level singletons, bounded by config.
- [ ] Async handlers `await sem.acquire()` before invoking the bounded resource.
- [ ] Test: 50 concurrent embedding requests serialize at 8 in-flight max.
- [ ] Test: 20 concurrent rerank requests serialize at 4 in-flight max.
- [ ] Metric `arxmcp_request_inflight{tool}` exposed.

**Dependencies.** E07_S01, E06_S04, E06_S05.

**Complexity.** S.

**Labels.** `area:server`, `area:observability`.

---

### E07_S12 — Path-traversal-safe paper_id validation

**Description.** Per `08-security-observability-ops.md` Threat 1 — strict regex on every arxiv ID input. New-style: `^\d{4}\.\d{4,5}(v\d+)?$`. Old-style: `^[a-z\-]+/\d{7}(v\d+)?$`. Reject at JSON-Schema level so values never reach handlers.

**Acceptance criteria.**
- [ ] Every tool that accepts a paper_id has the regex pattern in its JSON-Schema `pattern` field.
- [ ] Test: `paper_id="../../../etc/passwd"` is rejected at schema validation.
- [ ] Test: `paper_id="2401.01234"` is accepted.
- [ ] Test: `paper_id="math.AG/0501123v2"` (old-style) is accepted.
- [ ] Validation lives in one place (`server/tools/validators.py`) and is reused across all tools.

**Dependencies.** E07_S02.

**Complexity.** S.

**Labels.** `area:server`, `area:security`.

---

### E07_S13 — Indirect-prompt-injection delimiter wrapping

**Description.** Per `08-security-observability-ops.md` Threat 2 — wrap every returned chunk body in `<retrieved_chunk>...</retrieved_chunk>` delimiters. Optional sanitization of obvious injection patterns ("ignore previous instructions", literal `<|system|>`) but the delimiter contract is the primary defense.

**Acceptance criteria.**
- [ ] All chunk-body fields in tool results are wrapped in `<retrieved_chunk id="<chunk_id>">...</retrieved_chunk>`.
- [ ] Equation atoms similarly wrapped in `<retrieved_equation id="...">`.
- [ ] Optional regex sanitization layer (`server/security/sanitize.py`) strips known patterns before wrapping; configurable on/off.
- [ ] Test: a fixture chunk containing "Ignore previous instructions" still returns successfully but inside the delimiter.
- [ ] Documented in `docs/server/prompt-injection.md` with a recommended agent-side system-prompt clause.

**Dependencies.** E07_S04.

**Complexity.** S.

**Labels.** `area:server`, `area:security`.

---

### E07_S14 — End-to-end smoke test from a Claude Code session

**Description.** Repeat the E01_S10 demo with the full E02–E07 stack in place. Verify the agent gets back well-formed `search_papers` results with `corpus_version`, deterministic chunk IDs, and resource_link URIs that resolve to real chunks. This is the gate before E08 caching work begins.

**Acceptance criteria.**
- [ ] Documented Claude Code session in `docs/tier-1f-demo.md` showing `search_papers` + `get_chunk` + `get_paper` calls.
- [ ] All returned `corpus_version` values match the pinned version.
- [ ] All `chunk_id`s resolve to real chunks via `get_chunk` and via `resource_link`.
- [ ] No JSON-RPC errors during the session.
- [ ] Repeat the same session a second time and confirm identical response bytes for identical queries (determinism contract).

**Dependencies.** E07_S03, E07_S04, E07_S05, E07_S06.

**Complexity.** S.

**Labels.** `area:server`, `kind:research`.

---
