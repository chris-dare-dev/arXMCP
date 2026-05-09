# Research Brief — E06_S05 — Security hardening: Origin validation + localhost binding

## 1. In-codebase context

### Design constitution

`.claude/notes/06-mcp-server-design.md` lines 36–43 (load-bearing):

> Key obligations we must meet:
> - **Origin pinning + localhost binding.** Both. Spec quote: "Servers MUST
>   validate the `Origin` header... bind only to localhost."
> - **`Mcp-Session-Id` header** is globally unique and cryptographically secure.
>   Used for our per-session rate limits and observability.

`.claude/notes/08-security-observability-ops.md` lines 65–76 — Threat 5
("Origin spoofing on the HTTP transport") prescribes the mitigation we
implement here:

> - `Origin` header validation (MCP spec MUST). Allow only configured origins;
>   default to no `Origin` (the stdio shim doesn't send one) plus
>   `http://127.0.0.1:7733`.
> - `Sec-Fetch-Site: none` enforced where possible.
> - DNS rebinding defense: validate the `Host` header is `127.0.0.1` or
>   `localhost` with the configured port.

`08-security-observability-ops.md` lines 184–187 (logging contract — relevant
to AC #4 of the brief):

> Sensitive fields (full query text, chunk bodies) are logged at DEBUG only,
> never at INFO or above.

Note the **drift** flagged in `server/config.py` lines 19–27: the docker-compose
example at `08-security-observability-ops.md:261` sets
`ARXMCP_BIND_HOST=0.0.0.0` inside the container. That has already been
overridden in v1 — config rejects non-loopback unconditionally. This milestone
hardens the existing E06_S01 decision; it does NOT need to revisit the docker
case (the host-side `ports:` mapping pins to `127.0.0.1`).

### Existing wiring (E06_S01 already shipped)

- `server/main.py:323` — `create_app(config)` factory. Middleware mounts via
  `app.add_middleware(...)` at line 357 (the existing `BodySizeCapMiddleware`).
  **The new `OriginValidationMiddleware` mounts here, BEFORE the body-size
  middleware** so an evil-Origin POST is rejected without buffering its body.
- `server/main.py:88–224` — pure-ASGI `BodySizeCapMiddleware` is the pattern to
  copy: a class with `__init__(self, app, ...)` and
  `async def __call__(self, scope, receive, send)`. It already shows how to
  short-circuit a request with a JSON 4xx and how to handle the
  `_BYTE_CAP_EXEMPT_PREFIXES = ("/healthz", "/readyz", "/metrics", "/mcp")`
  exemption pattern. Origin validation, by contrast, is universal — no exempt
  prefixes — but the structural template is identical.
- `server/main.py:431–451` — the `__main__` entry point that loads `Config`,
  prints "Starting arxmcp-server on …", and calls `uvicorn.run(host=…)`. The
  AC "Starting server with `ARXMCP_BIND_HOST=0.0.0.0` exits with code 1 and a
  log message" already passes here because `Config()` raises `ValidationError`
  on bad host. The `_build_module_app` wrapper at lines 415–425 already
  catches and logs FATAL. **No new code needed for AC #3 — the existing
  infrastructure satisfies it.** Test it.
- `server/config.py:138–159` — the `reject_non_loopback` field validator
  already enforces the `bind_host ∈ {127.0.0.1, ::1, localhost}` rule. The
  brief's text "rejects `ARXMCP_BIND_HOST` values other than `127.0.0.1` and
  `::1`" is **stricter than what's currently in place** (which also accepts
  `"localhost"` as a third loopback value). My recommendation: KEEP
  `"localhost"` — it's a loopback alias and the test suite at
  `tests/test_server_startup.py:266–268` already covers it. Update the brief's
  language in the implementation summary, do not delete an accepted value
  that has shipped.

### MCP library's built-in protection (critical finding)

The `mcp==1.27.1` library has its own `TransportSecurityMiddleware` at
`.venv/lib/python3.13/site-packages/mcp/server/transport_security.py`:

- It returns **`421` on bad Host** and **`403` on bad Origin** (lines 120, 125).
- `FastMCP.__init__` at `mcp/server/fastmcp/server.py:177–183` **auto-enables**
  DNS-rebinding protection when `host in ("127.0.0.1", "localhost", "::1")`
  with these defaults:
  - `allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"]`
  - `allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]`
- BUT this protection runs only inside the `/mcp` Streamable HTTP sub-app —
  not on `/healthz`, `/readyz`, or `/metrics`.
- AND it permits Origin to be missing (line 70: "Origin can be absent for
  same-origin requests") — matches the brief's requirement.

**Implication:** the brief's `OriginValidationMiddleware` is needed because we
want the protection to apply across the WHOLE FastAPI app (so `/metrics`
behind a malicious origin gets a 403 too), and we want one place to define
the allow-list and JSON error body. We should NOT disable the FastMCP
built-in — defense in depth — but we should align our allow-list with theirs
to avoid surprising operators.

### Mcp-Session-Id

`mcp/server/streamable_http_manager.py:244` generates session IDs as
`uuid4().hex`. **The MCP library owns session-id generation** — `FastMCP`
exposes no constructor knob to override the generator. The brief's
"`Mcp-Session-Id` per session uses `secrets.token_hex(32)`" therefore needs
ONE of these approaches:

1. **Monkeypatch** `mcp.server.streamable_http_manager.uuid4` at app
   construction with a callable that returns a UUID-like wrapper backed by
   `secrets.token_hex(32)`. Brittle — couples our code to a private detail.
2. **Add a response middleware** that, on any response carrying an outbound
   `Mcp-Session-Id` header (the initialize response), rewrites the header
   value to `secrets.token_hex(32)` AND tracks the rewrite in a process-local
   dict so subsequent requests carrying that new ID get rewritten back to the
   library's UUID before the library handler sees them. **Complex and
   error-prone.**
3. **Recommended: skip overriding for v1, document the gap, and revisit when
   we ship rate-limiting.** The current `uuid4().hex` is 122 bits of entropy.
   The brief's preference for `secrets.token_hex(32)` (256 bits) is correct
   in the abstract, but `uuid4` is `secrets`-backed in CPython (`os.urandom`)
   and 122 bits is ample to defeat session-fixation attacks on a localhost-only
   server. The MCP spec line itself says "globally unique and cryptographically
   secure" — UUID4 satisfies both. **Recommendation: ship a `secrets`-based
   override only if we can wire it cleanly via a single FastMCP config knob in
   a future `mcp` minor; for v1 add a TODO comment and a test asserting the
   header is set and at least 32 hex chars.**

This is the single most controversial call in the brief — the implementer
should decide explicitly and document it.

### Existing test surface to extend

- `tests/test_server_startup.py:249–292` — `TestConfigValidation` already
  asserts `Config(bind_host="0.0.0.0")` raises `ValidationError` with
  "loopback" in the message. The brief's AC #3 ("Starting server with
  `ARXMCP_BIND_HOST=0.0.0.0` exits with code 1 and a log message") goes
  one level higher: assert that `_build_module_app()` (or `python -m
  server.main`) exits with code 1. This is best tested via `subprocess.run`
  against a `python -m server.main` invocation with `ARXMCP_BIND_HOST=0.0.0.0`
  — assert `returncode != 0` and stderr contains "FATAL" + "loopback".
- No `tests/test_security.py` exists yet. New file. Use
  `fastapi.testclient.TestClient` and the `warm_app` fixture pattern from
  `tests/test_server_startup.py:120–132`.

## 2. Prior decisions and lessons

- Git log on `server/`: 5 server-related commits since E06_S01 landed. No
  `LESSONS.md` files. Critique notes (`E06_S01/critique-adversary.md` etc.)
  exist but cover earlier milestones — no security-specific lessons surfaced.
- E06_S01 already chose **pure-ASGI middleware** over `BaseHTTPMiddleware`
  (see `server/main.py:113–139` — `BaseHTTPMiddleware` was a silent no-op
  because Starlette wraps responses in `_StreamingResponse`). Repeat that
  choice for the new origin / security-headers middleware.
- E06_S01 chose `pydantic-settings` field validators for config validation.
  No new env vars are needed for E06_S05 — Origin allow-list lives as a
  module constant in `server/middleware.py` so the implementer doesn't have
  to extend `Config`.
- The 1 MB body limit: uvicorn has NO `limit_request_body` knob (verified
  in `.venv/lib/python3.13/site-packages/uvicorn/config.py` — the only
  `limit_*` knob is `limit_max_requests`). FastAPI inherits this. Therefore
  the 1 MB cap **must be enforced by middleware** — read the
  `Content-Length` header in the ASGI middleware and reject early; for
  chunked requests (no `Content-Length`), accumulate `http.request` events
  and reject once the cap is breached. The pattern mirrors the existing
  `BodySizeCapMiddleware` but inverted (request-side instead of
  response-side).

## 3. External sources

### MCP 2025-06-18 spec — load-bearing MUSTs

From `https://modelcontextprotocol.io/specification/2025-06-18` (Streamable
HTTP transport):

> "Servers MUST validate the `Origin` header on all incoming connections to
> prevent DNS rebinding attacks."
>
> "When running locally, servers SHOULD bind only to localhost (127.0.0.1)
> rather than all network interfaces (0.0.0.0)."
>
> "Servers SHOULD implement proper authentication for all connections."
> (We omit auth — explicitly out of scope per `06-mcp-server-design.md:359`,
> "Authentication. (localhost-only.)")

The first quote is a MUST → AC #1 + #2. The second is a SHOULD that the
brief escalates to a MUST for our deployment → AC #3. The third is omitted
intentionally.

The spec also fixes the `Mcp-Session-Id` rules in the same Streamable HTTP
section:

> "If the server does include a session ID, it MUST be globally unique and
> cryptographically secure (e.g. a UUID, a JWT, or a cryptographic hash)."

UUID is explicitly listed as acceptable. Reinforces my recommendation in §1
to ship `uuid4` for v1.

### Starlette / FastAPI middleware

- `pyproject.toml` pins `fastapi>=0.115` and `uvicorn[standard]>=0.30`;
  Starlette is the actual middleware base (FastAPI re-exports). The
  pure-ASGI form (`async def __call__(self, scope, receive, send)`) is the
  documented stable API and is what `BodySizeCapMiddleware` already uses.
  Use it for the new middleware.
- Starlette ships `TrustedHostMiddleware` for Host validation; we don't
  need it because (a) MCP's built-in handles `/mcp`, (b) origin (not host)
  is what the spec mandates, (c) DNS-rebinding via Host is already handled
  inside MCP for the only path that matters.

### `secrets` module

From CPython 3.13 docs: `secrets.token_hex(nbytes)` returns a hex string
encoding `nbytes` random bytes. `nbytes=32` → 32 random bytes → 64 hex
chars → 256 bits of entropy. The brief's specification matches.

`uuid.uuid4()` in CPython is `secrets`-backed (`os.urandom` under the
hood); it produces 122 bits of entropy (6 bits fixed for version + variant).
122 bits of CSRNG is ample for a session identifier on a localhost-only
server; the brief's stated reason ("UUID4 has insufficient entropy") is
weak. Document the choice either way.

## Recommended implementation shape

```
server/middleware.py
├── OriginValidationMiddleware(app)       # pure ASGI, returns 403 JSON
├── SecurityHeadersMiddleware(app)         # adds X-Content-Type-Options + X-Frame-Options
└── RequestBodySizeLimitMiddleware(app, max_bytes=1*1024*1024)  # 413 on >1 MB
```

`server/main.py:create_app` mount order (outermost to innermost):

```python
app.add_middleware(SecurityHeadersMiddleware)              # always wrap
app.add_middleware(OriginValidationMiddleware)             # reject early
app.add_middleware(RequestBodySizeLimitMiddleware, max_bytes=1*1024*1024)
app.add_middleware(BodySizeCapMiddleware, byte_cap=cfg.result_byte_cap)  # existing
```

(`add_middleware` adds in LIFO request order — last-added runs first on
the request side. The order above means request flow is: `BodySizeCap` →
`RequestBodySizeLimit` → `Origin` → `SecurityHeaders` → handler.) The
implementer should verify with a probe test.

`tests/test_security.py` shape:

```python
class TestOriginValidation:        # 4-6 tests: evil origin, no origin, localhost, 127.0.0.1
class TestSecurityHeaders:         # 2 tests: nosniff + DENY on every response
class TestRequestBodyLimit:        # 2 tests: just-under, just-over
class TestStartupRejectsBadBind:   # 1 test: subprocess with ARXMCP_BIND_HOST=0.0.0.0 → exit 1
class TestSessionId:               # 1 test: header present + ≥32 hex chars (loose)
```

Use the existing `warm_app` fixture; for the subprocess test, copy the
`subprocess.run([sys.executable, "-m", "server.main"], env=...)` pattern with
a 5-second timeout — bind to a port that will be killed before serving.

## Open questions

1. **Mcp-Session-Id override approach.** Ship UUID4 (recommended), monkeypatch
   the MCP library, or build a header-rewriting middleware? My recommendation
   is UUID4 + a clarifying note in the implementation summary; the implementer
   should make the call and document it. The brief's "secrets.token_hex(32)"
   line is a SHOULD-strength preference, not a MUST.
2. **`localhost` allow-list value.** Brief says "`127.0.0.1` and `::1` only."
   Existing config + tests accept `"localhost"`. Recommend KEEPING `localhost`
   to avoid breaking `tests/test_server_startup.py:266–268`; the implementer
   should treat the brief's wording as illustrative.
3. **Origin header default allow-list.** The brief implies "`localhost` or
   `127.0.0.1` host component" without specifying scheme/port. Recommend:
   accept `http://127.0.0.1[:port]`, `http://localhost[:port]`, `http://[::1][:port]`
   (matching FastMCP's defaults at `fastmcp/server.py:181–182`); document this
   explicitly in `server/middleware.py`.

## External writes the implementation will require

None. This milestone is purely internal hardening — config validation,
middleware, and tests. No API calls, no PRs spawned, no infra mutation, no
ticket updates.
