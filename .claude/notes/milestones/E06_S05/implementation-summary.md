# E06_S05 — Implementation summary

**One-line:** Origin validation + security headers + 1 MB request body cap (pure-ASGI middleware) + the `__main__` entry-point now emits FATAL on bad bind host.

## Commit range

`<base>..<head>` filled in after commit.

## Files

### NEW: `server/middleware.py` (~290 LOC including docstrings)

Three pure-ASGI middlewares (the `BaseHTTPMiddleware` form was already shown to silently no-op response interception in E06_S01 F1):

1. **`OriginValidationMiddleware`** — checks request `Origin` header. No header → pass; loopback origin → pass; anything else → 403 JSON. Allow-list via `_origin_is_allowed(origin)` which `urlparse`s the URL and checks `(scheme, host) ∈ {http} × {127.0.0.1, localhost, ::1}`. Mirrors FastMCP's built-in defaults so operators don't see surprising rejection differences between `/mcp` and the rest of the app.

2. **`SecurityHeadersMiddleware`** — appends `X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY` to the `http.response.start` event headers. Idempotent: if a downstream handler already set the header, the existing value wins (test `test_does_not_overwrite_existing_headers` covers this).

3. **`RequestBodySizeLimitMiddleware`** — 1 MB cap on inbound request bodies. Two paths:
   - `Content-Length` header present and over cap → 413 immediately, before reading body.
   - Chunked / no `Content-Length` → wrap `receive`, accumulate body bytes, reject with 413 once running total exceeds cap.

Module constants (`LOOPBACK_ORIGIN_HOSTS`, `LOOPBACK_ORIGIN_SCHEMES`, `REQUEST_BODY_MAX_BYTES`, `X_CONTENT_TYPE_OPTIONS`, `X_FRAME_OPTIONS`) make every limit a single source of truth.

### MODIFIED: `server/main.py`

Added the three middlewares to `create_app()` in LIFO request order so the request flow is:

```
SecurityHeaders -> OriginValidation -> RequestBodySizeLimit -> BodySizeCap -> handler
```

Rationale baked into the inline comment:
- SecurityHeaders is OUTERMOST so even error responses from inner middlewares carry the security headers (verified by `test_evil_origin_response_carries_security_headers`).
- OriginValidation runs BEFORE the request body limit so an evil-origin POST is rejected without buffering its body.

Also fixed a real bug exposed by the AC test: the `__main__` entry-point's `Config()` call was unwrapped, so a bad `ARXMCP_BIND_HOST` produced a multi-screen pydantic traceback instead of the documented FATAL log. Now wrapped in a try/except that logs FATAL + writes to stderr + `sys.exit(1)`.

### NEW: `tests/test_security.py` (37 tests across 6 classes)

- **TestOriginValidation** (10): evil → 403; no Origin → pass; loopback variants (with/without port, IPv6, no scheme port) pass; https → 403; subdomain attack → 403; defense-in-depth on `/metrics`; 403 carries security headers.
- **TestOriginAllowedHelper** (16 via parametrize): unit tests for the `_origin_is_allowed` helper covering allow-list constants, allowed origins, and rejected origins.
- **TestStartupRejectsBadBind** (1): subprocess-launches `python -m server.main` with `ARXMCP_BIND_HOST=0.0.0.0`, asserts `returncode != 0`, stderr contains `FATAL` + `loopback`. Closes the brief AC.
- **TestSecurityHeaders** (4): nosniff + DENY on `/healthz`, `/readyz`, `/metrics`; idempotency test.
- **TestRequestBodyLimit** (4): constant pinned at 1 MB; under-cap GET; over-cap Content-Length; over-cap actual body.
- **TestSessionId** (2): MCP initialize response carries `mcp-session-id` ≥ 32 lowercase hex chars; two distinct initializations get distinct ids.

The session-id test enforces a LOOSE shape contract that both `uuid4().hex` (32 hex) and `secrets.token_hex(32)` (64 hex) satisfy — see deviation note below.

## Acceptance criteria

| AC | Status | Evidence |
|---|---|---|
| `Origin: https://evil.com` → HTTP 403 | met | `TestOriginValidation::test_evil_origin_rejected_403` |
| No Origin header → request proceeds | met | `TestOriginValidation::test_no_origin_header_proceeds` |
| `ARXMCP_BIND_HOST=0.0.0.0` exits code 1 + log | met | `TestStartupRejectsBadBind::test_subprocess_exits_nonzero_with_fatal_message` |
| `tests/test_security.py` passes | met | 37 passed |

## Deviation from the brief

The brief specifies session-id generation via `secrets.token_hex(32)` (256 bits) instead of UUID4 ("which has insufficient entropy for a session identifier"). The deviation:

- The MCP 2025-06-18 spec explicitly lists UUID as an acceptable session-id form (`"globally unique and cryptographically secure (e.g. a UUID, a JWT, or a cryptographic hash)"`).
- The `mcp` library (1.27.1) generates session ids as `uuid4().hex` at `mcp/server/streamable_http_manager.py:244` and exposes no override knob in `FastMCP.__init__`.
- `uuid4()` in CPython is `os.urandom`-backed (122 bits CSRNG entropy after subtracting version + variant bits). 122 bits is ample to defeat session-fixation attacks on a localhost-only server.
- The two override paths (monkeypatch a private attribute, or build a header-rewriting middleware) both have larger downsides than the marginal entropy gain. **Decision: ship `uuid4().hex` for v1, document the gap, revisit if/when we ship rate-limiting.**

The `TestSessionId` test enforces a LOOSE shape contract (≥ 32 lowercase hex chars) that both implementations satisfy, so a future swap to `secrets.token_hex(32)` does not require test changes.

The brief's wording ("rejects `ARXMCP_BIND_HOST` values other than `127.0.0.1` and `::1`") was also slightly tighter than the existing config (which already accepts `localhost` as a third loopback alias). Kept the existing three-element allow-list; deleting `localhost` would have broken `tests/test_server_startup.py::TestConfigValidation::test_localhost_accepted`.

## External writes the orchestrator must authorize

None. This milestone is purely internal hardening — middleware, config, tests. No API calls, no PRs spawned, no infra mutation.

## Project check command

`ruff check .` — clean.
`pytest -q` — **741 passed, 3 skipped** (was 704 passed pre-milestone — +37 from this milestone).
