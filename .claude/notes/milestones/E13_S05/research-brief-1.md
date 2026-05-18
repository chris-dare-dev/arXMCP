# Research Brief — E13_S05

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-18T14:35:00Z

## In-codebase context

### Applicable design notes
- `08-security-observability-ops.md` — Threat 5 definition (primary)
- `06-mcp-server-design.md` — MCP spec compliance
- `07-multi-agent-caching.md` — tool-schema byte-stability (no tool changes here)

### Threat 5 verbatim from `08-security-observability-ops.md` lines 64–75

> ### Threat 5: Origin spoofing on the HTTP transport
>
> Even bound to localhost, a malicious local web page could try to issue
> fetches.
>
> **Mitigations:**
> - `Origin` header validation (MCP spec MUST). Allow only configured origins;
>   default to no `Origin` (the stdio shim doesn't send one) plus
>   `http://127.0.0.1:7733`.
> - `Sec-Fetch-Site: none` enforced where possible.
> - DNS rebinding defense: validate the `Host` header is `127.0.0.1` or `localhost`
>   with the configured port.

### What OriginValidationMiddleware actually checks (server/middleware.py)

`OriginValidationMiddleware` checks ONLY the `Origin` header. Zero
`Sec-Fetch-Site` handling exists anywhere in the codebase
(`grep -rn "Sec-Fetch-Site" server/` returns no output).

`LOOPBACK_ORIGIN_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})` —
any `Origin` in this set (any port, http scheme only) passes. No-Origin
requests pass. All other `Origin` values return 403.

### What HostValidationMiddleware actually checks (server/middleware.py)

`HostValidationMiddleware` (added as F3 fix from E06_S05 critique) validates
the `Host` header against `LOOPBACK_HOST_HEADER_HOSTS = frozenset({"127.0.0.1",
"localhost", "::1", "testserver"})`. It uses exact hostname matching (after
splitting off the port). Python simulation confirms:

- `Host: attacker.localhost` → rejected (False — "attacker.localhost" is NOT in
  the frozen set). The brief AC is ALREADY satisfied by existing code.
- `Host: 8.8.8.8` → rejected (False). Also already satisfied.
- `Host: localhost` → allowed.
- `Host: localhost:7733` → allowed.

Both `HostValidationMiddleware` and `OriginValidationMiddleware` are pure-ASGI
(no `BaseHTTPMiddleware`). Both are mounted in `server/main.py::create_app`.

### Middleware mount order (server/main.py lines 384–422, verbatim comment):

> request flow: SecurityHeaders -> OriginValidation
>               -> RequestBodySizeLimit -> BodySizeCap -> handler

`HostValidationMiddleware` is added with `allowed_port=None` in production
(accepts any port, so tests work). The brief AC for "public IP in Host → 403"
is already satisfied by the existing `_validate_host_header` logic.

### Bind-host guard (server/config.py, verbatim)

```python
@field_validator("bind_host")
@classmethod
def reject_non_loopback(cls, v: str) -> str:
    if v not in LOOPBACK_HOSTS:
        raise ValueError(
            f"ARXMCP_BIND_HOST must be a loopback address "
            f"({sorted(LOOPBACK_HOSTS)}); got {v!r}. ..."
        )
    return v
```

`LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})`. Setting
`ARXMCP_BIND_HOST=0.0.0.0` raises `ValidationError` at config parse, which
`_build_module_app` catches and re-raises causing exit with code 1.

**`ARXMCP_UNSAFE_NETWORK_BIND` does NOT exist.** The brief AC says "0.0.0.0
without ARXMCP_UNSAFE_NETWORK_BIND=1 → server refuses to start." The first
part is already implemented. The escape-hatch env var does not exist. The brief
is spec'ing NEW functionality for this env var. Note: adding this var would be
a NEW `Config` field, which triggers `_scan_unknown_arxmcp_env_vars` to reject
it if not declared — so the field MUST be added to `Config`.

**`ARXMCP_ALLOWED_ORIGINS` does NOT exist.** `grep -rn "ARXMCP_ALLOWED_ORIGINS"
server/` returns only a comment in the middleware docstring. The env var is
NOT a declared `Config` field. The brief spec's this as NEW functionality.
Adding it to `Config` means anyone currently running with a typo
`ARXMCP_ALLOWED_ORIGINS=...` would trigger the unknown-env-var scanner to
raise. But as a new field, it must be declared in `Config` and wired into
`OriginValidationMiddleware`.

### Docker compose landscape

No top-level `docker-compose.yml` exists. Only `infra/latexml/docker-compose.latexml.yml`
is present. The design note `08-security-observability-ops.md` §Docker deployment shows
a sample docker-compose YAML with `ports: - "127.0.0.1:7733:7733"` — but this is
ASPIRATIONAL, not a real file. The E14 epic owns docker-compose. The brief AC
"Docker compose ports: maps 127.0.0.1:7733:7733" cannot be verified against a real
file — it must be reframed.

**CONFLICT FLAG:** The brief's 6th AC ("Docker compose `ports:` maps
`127.0.0.1:7733:7733`") cannot be satisfied at E13_S05 because no main
docker-compose.yml exists. This is the same pattern confirmed in E13_S03 memory:
`no-docker-compose-exists`. The test must be reframed as: verify the design note
`08-security-observability-ops.md` §Docker deployment documents `127.0.0.1:7733:7733`
(an assertion against the doc text, not a running container), OR deferred to E14.

### Sec-Fetch-Site status

ZERO middleware checks `Sec-Fetch-Site`. The design note lists it as a
mitigation. The milestone brief says: "(1) `Sec-Fetch-Site` header rejected unless
value is `none` or the header is absent." This is a FULL implementation gap — the
feature does not exist. The implementer must add a new `SecFetchSiteMiddleware`
(pure-ASGI) to enforce this.

**Important semantic note:** Valid Sec-Fetch-Site values per the Fetch Living
Standard are: `cross-site`, `same-origin`, `same-site`, `none`. Only `none`
should be permitted (browser requests from the user's own address bar/bookmark,
no web page initiated the request). Any other value means a web page initiated
the request and should be rejected 403. The header may be absent (non-browser
clients — curl, the stdio shim — don't send it); absence must pass.

### Existing tests coverage

`tests/test_security.py` already covers:
- Origin validation (multiple cases including subdomain attack)
- Bind host rejection (0.0.0.0 subprocess test)
- Security headers
- Request body limit

`tests/security/test_origin_binding.py` does NOT yet exist (confirmed by
`ls tests/security/` — no such file). The file must be created as part of this
milestone.

## Prior decisions and lessons

### E07_S01 and E07_S09 are wrong dependency attributions

**E07 has only S01–S04** (confirmed by reading `E07-hybrid-retrieval.md`).
E07_S09 does not exist — it is a fictional milestone, consistent with the
established "E07-fictional-milestones-pattern" from prior milestone memory.

**E07_S01** is "Phase 1: BM25 over body_tokens" — NOT Origin validation.
Origin validation shipped in **E06_S05** ("Security hardening: Origin validation
and localhost binding"). The milestone brief's attribution of "E07_S01 (Origin
pin)" is incorrect. The real dependency is E06_S05.

This is the same documented drift pattern from E13_S01 and E13_S02: fictional
E07 milestone references. Do not implement any "E07_S09 dependency check."

### Doc placement drift

The brief specifies:
- `docs/security/threat-5-audit.md` → WRONG per CLAUDE.md §1 + doc-placement-correction-pattern
- `docs/security/binding.md` → WRONG same reason

Correct destinations:
- `.claude/docs/security-threat-5-audit.md`
- `.claude/docs/security-binding.md`

`docs/` is restricted to user-facing documentation linked from the root README.
Security audit documents are agent-internal. This drift is documented in every
prior E13 milestone brief.

### `ARXMCP_UNSAFE_NETWORK_BIND` — net-new env var

Adding `unsafe_network_bind: bool = False` to `Config` will:
1. Change the error message from `reject_non_loopback` when `True` (bypass the
   validator)
2. Trigger `_scan_unknown_arxmcp_env_vars` — must be declared on `Config`
3. NOT change the tool schema (no MCP tool involvement) — no SHA re-pin needed

The validator must check `unsafe_network_bind` AFTER parsing both fields. This
requires a `@model_validator(mode="after")` since `@field_validator` on
`bind_host` runs before `unsafe_network_bind` is available. The existing
`reject_non_loopback` field validator must be relaxed OR replaced by a model
validator that checks both fields.

### `ARXMCP_ALLOWED_ORIGINS` — net-new env var

Adding `allowed_origins: list[str] = []` to `Config` enables the operator to
specify a non-empty list of permitted Origin values. Default empty means the
current behavior (only no-Origin requests allowed — stdio shim — plus the
loopback LOOPBACK_ORIGIN_HOSTS set for browser-side origins). The
`OriginValidationMiddleware` must be wired to check `Config.allowed_origins` if
non-empty; if empty, fall back to the existing `LOOPBACK_ORIGIN_HOSTS` logic.

Pydantic-settings parses `list[str]` from env var as JSON: `ARXMCP_ALLOWED_ORIGINS='["http://127.0.0.1:7733"]'`.

### No tool-schema re-pin needed

E13_S05 adds no MCP tools and modifies no tool schemas. `EXPECTED_TOOL_SCHEMA_SHA256`
in `tests/test_server_tool_schema.py` is NOT affected.

### KMP_DUPLICATE_LIB_OK guard

`tests/conftest.py` sets `KMP_DUPLICATE_LIB_OK=TRUE`. New tests in
`tests/security/test_origin_binding.py` are in the `tests/security/` subdirectory
which is already covered by the conftest autouse fixture. No action needed.

### BaseHTTPMiddleware ban

Any new `SecFetchSiteMiddleware` must be pure-ASGI (same pattern as all existing
middlewares). BaseHTTPMiddleware is project-banned per E06_S01 F1.

## External sources

### MCP 2025-06-18 spec (verbatim Security Warning from Streamable HTTP section)

> When implementing Streamable HTTP transport:
> 1. Servers **MUST** validate the `Origin` header on all incoming connections
>    to prevent DNS rebinding attacks
> 2. When running locally, servers **SHOULD** bind only to localhost (127.0.0.1)
>    rather than all network interfaces (0.0.0.0)
> 3. Servers **SHOULD** implement proper authentication for all connections
>
> Without these protections, attackers could use DNS rebinding to interact with
> local MCP servers from remote websites.

The spec says NOTHING about `Sec-Fetch-Site` or `Host` header validation. Those
are defense-in-depth beyond the spec MUST.

### Sec-Fetch-Site header (Fetch Living Standard / MDN)

Valid values per the Fetch Metadata spec: `cross-site`, `same-origin`,
`same-site`, `none`. The values signal:
- `none` — user-initiated navigation (address bar, bookmark); safe for
  localhost MCP servers
- `same-site` / `same-origin` — same registrable domain or exact same origin;
  should be rejected since a localhost server has no same-site web partner
- `cross-site` — different site; clearly should be rejected

Security implication: if a browser sends `Sec-Fetch-Site: cross-site`, a web
page on attacker.com initiated the request to 127.0.0.1. Rejecting all values
except `none` (and absent) closes the fetch-initiated attack vector even before
the Origin check fires.

### DNS-rebinding attack mechanism

DNS rebinding: attacker.com resolves to attacker's IP on first connection; then
DNS TTL expires and attacker makes attacker.com resolve to 127.0.0.1. Browser
now treats attacker.com as same-origin with localhost. Host header validation
closes this: even after DNS rebind, the browser sends `Host: attacker.com` (the
original name), not `Host: localhost`. The `HostValidationMiddleware` rejects
any host not in `LOOPBACK_HOST_HEADER_HOSTS`. This defense is ALREADY SHIPPED.

## Recommendation

**Implement `SecFetchSiteMiddleware` + `ARXMCP_ALLOWED_ORIGINS` + `ARXMCP_UNSAFE_NETWORK_BIND`; reframe the Docker compose AC; do not re-implement Host validation (already shipped).**

Specifically:

1. Add `allowed_origins: list[str] = []` and `unsafe_network_bind: bool = False`
   to `server/config.py::Config`. Replace the `@field_validator("bind_host")`
   with a `@model_validator(mode="after")` that skips the loopback check when
   `unsafe_network_bind=True`. This preserves the existing rejection behavior as
   the default.

2. Add `SecFetchSiteMiddleware` (pure-ASGI) to `server/middleware.py`. Logic:
   if `Sec-Fetch-Site` header is absent → pass through; if present and value is
   `none` → pass through; if present with any other value → 403 with JSON body
   `{"error": "sec_fetch_site_forbidden"}`. Mount it in `create_app` AFTER
   `OriginValidationMiddleware` (inner to it — bad-origin request is rejected
   before Sec-Fetch-Site is checked).

3. Wire `ARXMCP_ALLOWED_ORIGINS` into `OriginValidationMiddleware`. When
   `allowed_origins` is non-empty, use it as the exhaustive allow-list instead
   of `LOOPBACK_ORIGIN_HOSTS`.

4. Write `tests/security/test_origin_binding.py` with 6 test cases covering the
   ACs. For the Docker compose test, assert that the design note
   `08-security-observability-ops.md` §Docker deployment text contains
   `127.0.0.1:7733:7733` (text assertion against the doc, not a running
   container). This satisfies the intent without requiring the nonexistent
   docker-compose.yml.

5. Write `.claude/docs/security-threat-5-audit.md` and
   `.claude/docs/security-binding.md` (NOT `docs/security/`).

6. Host validation and bind-host refusal already work — tests for those are
   already in `tests/test_security.py`. The new file adds the 6 additional cases
   for this milestone's specific ACs; there is no need to duplicate the existing
   `TestStartupRejectsBadBind` logic.

## Open questions

1. **`ARXMCP_UNSAFE_NETWORK_BIND` validator refactor**: The current
   `@field_validator("bind_host")` runs before `unsafe_network_bind` is parsed,
   so it cannot check the escape-hatch flag. The implementer must convert to
   `@model_validator(mode="after")`. Confirm there are no other tests that depend
   on `bind_host` raising `ValueError` directly (vs `ValidationError` from the
   model validator) — the exception type changes from a field-level error to a
   model-level error, which may affect test assertions in
   `tests/test_server_startup.py::TestConfigValidation`.

2. **`ARXMCP_ALLOWED_ORIGINS` with empty list semantics**: The brief says "default:
   empty list, meaning only no-Origin requests are accepted." But existing behavior
   ALSO accepts loopback `Origin` headers (http://127.0.0.1, http://localhost).
   The brief is contradictory with the existing E06_S05 behavior. Recommendation:
   keep the existing loopback behavior as the default when `allowed_origins` is
   empty (backward-compatible), document the discrepancy in the audit doc. An
   empty list means "use the built-in loopback allow-list," NOT "accept only
   no-Origin requests." If the intent is stricter, the implementer should treat
   this as a behavioral change requiring explicit acknowledgment.

No open questions that would BLOCK implementation — these are refinement
decisions the implementer can resolve per the recommendation above.

## External writes the implementation will require

None — this milestone is purely local.

All deliverables are test files, config additions, and middleware additions in
the local repo. No git push, no PR creation, no infra mutation. The push step
is a separate user-authorized event in Phase 4.
