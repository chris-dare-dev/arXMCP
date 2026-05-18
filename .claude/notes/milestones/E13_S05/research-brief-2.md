# Research Brief — E13_S05

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-18T14:35:00Z

---

## In-codebase context

### Design constitution — Threat 5 (verbatim, `08-security-observability-ops.md` lines 65–76)

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

### MCP spec 2025-06-18 (verbatim, Streamable HTTP Security Warning)

> 1. Servers **MUST** validate the `Origin` header on all incoming connections to
>    prevent DNS rebinding attacks
> 2. When running locally, servers **SHOULD** bind only to localhost (127.0.0.1)
>    rather than all network interfaces (0.0.0.0)
> 3. Servers **SHOULD** implement proper authentication for all connections
>
> Without these protections, attackers could use DNS rebinding to interact with
> local MCP servers from remote websites.

### Current codebase state (what is already shipped)

Reading `server/middleware.py` reveals significant prior art:

- `OriginValidationMiddleware` is FULLY IMPLEMENTED (E06_S05). It rejects any
  `Origin` that is not in `LOOPBACK_ORIGIN_HOSTS = {"127.0.0.1", "localhost", "::1"}`.
  No-Origin requests pass through (stdio shim path).
- `HostValidationMiddleware` is FULLY IMPLEMENTED (E06_S05 F3 fix). It rejects any
  `Host` header not in `LOOPBACK_HOST_HEADER_HOSTS = {"127.0.0.1", "localhost", "::1",
  "testserver"}` with a 421 Misdirected Request. IPv6 bracket-stripping is handled.
- `server/config.py::reject_non_loopback` FULLY IMPLEMENTED. `ARXMCP_BIND_HOST=0.0.0.0`
  raises `ValueError` at config parse time — the server refuses to start.
- Existing tests in `tests/test_security.py` cover: evil Origin → 403, no-Origin →
  pass, evil Host → 421, IPv6 loopback, `0.0.0.0` startup rejection.

**CRITICAL DRIFT: The milestone brief describes three hardening additions ("beyond E07_S01")
as if they are new. In reality, all three are already implemented:**

1. **`ARXMCP_ALLOWED_ORIGINS` env var** — NOT present. `LOOPBACK_ORIGIN_HOSTS` is a
   hardcoded `frozenset` in `middleware.py`, not env-configurable.
2. **`Sec-Fetch-Site` rejection** — NOT present anywhere in `server/`. No handler,
   middleware, or test for `Sec-Fetch-Site` exists.
3. **`Host` header validation** — ALREADY SHIPPED as `HostValidationMiddleware`.

**The milestone's Host-header AC** (`Host: attacker.localhost` → 403) is ALREADY
covered by `HostValidationMiddleware` — `attacker.localhost` is not in
`LOOPBACK_HOST_HEADER_HOSTS`. However, the test file `tests/security/test_origin_binding.py`
does NOT YET EXIST. The existing tests live in `tests/test_security.py`.

**`ARXMCP_UNSAFE_NETWORK_BIND` does not exist.** `server/config.py` has no such field.
The `reject_non_loopback` validator unconditionally rejects non-loopback bind hosts — no
escape hatch. The brief's AC (`ARXMCP_BIND_HOST=0.0.0.0` + `ARXMCP_UNSAFE_NETWORK_BIND=1`
→ accepted with WARN) requires a NEW config field.

**Doc destination drift.** The brief specifies `docs/security/threat-5-audit.md` and
`docs/security/binding.md`. CLAUDE.md §1 bans non-user-facing docs from `docs/`. All
prior E13 audit docs landed at `.claude/docs/security-threat-N-audit.md`.

**E13_S09 overlap.** The `ARXMCP_UNSAFE_NETWORK_BIND` + 0.0.0.0 AC is ALSO specified
in E13_S09 (`tests/security/test_bind_regression.py`). The roadmap explicitly notes
E13_S09 "complements E13_S05" and links `docs/security/binding.md` as shared. The
implementer must not duplicate the binding regression tests — E13_S05 delivers the doc
artifact and possibly a stub test; E13_S09 owns the full binding regression suite.

---

## Prior decisions and lessons

- **E07_S01 is real** (E07 has S01–S04). The dependency attribution is correct.
- **E07_S09 is fictional** — E07 has only S01–S04. The memory from prior E13 milestones
  is confirmed. The AC citing E07_S09 is citing a fictional milestone. E13_S05 is BOTH
  spec AND enforcement (same pattern as E13_S03, E13_S04).
- **Doc placement correction** (established in E13_S01): all security audit docs go to
  `.claude/docs/security-threat-N-audit.md`, NOT `docs/security/`.
- **No docker-compose.yml exists** in the repo (confirmed for E13_S03). The brief AC
  "Docker compose `ports:` maps `127.0.0.1:7733:7733`" cannot be verified via
  `docker inspect`. The design in `08-security-observability-ops.md` is aspirational.
  The correct deliverable is a standalone YAML artifact doc entry, not a live test.
- E13_S04 `state.json` shows the pattern for completion: feat + rect + chore commits.
- All security tests live under `tests/security/`. `test_origin_binding.py` is the
  new file to create.

---

## External sources

### MCP 2025-06-18 Spec — DNS rebinding (verbatim, Streamable HTTP Security Warning)

Quoted above in full. Key fact: the spec specifies Origin validation as MUST and
localhost binding as SHOULD. No mention of `Sec-Fetch-Site` in the spec.

### Sec-Fetch-Site header — W3C Fetch Metadata spec

Four values per W3C TR/fetch-metadata:
- `cross-site` — request from a different registrable domain
- `same-site` — same registrable domain, different origin
- `same-origin` — exact same origin (scheme + host + port)
- `none` — "navigation requests explicitly caused by a user's interaction with the
  user agent (by typing an address into the user agent directly, for example, or
  by clicking a bookmark, etc.)"

**Critical for arXMCP:** CLI tools (`curl`, `mcp-cli`, the stdio shim HTTP bridge)
do NOT send `Sec-Fetch-Site`. The W3C spec says nothing about non-browser clients.
The header is a browser-only mechanism — it is a "forbidden header name" in browsers
(cannot be forged by page scripts). Therefore:
- Requests WITHOUT `Sec-Fetch-Site` = CLI tool, stdio shim, direct HTTP client → ALLOW
- Requests WITH `Sec-Fetch-Site: none` = browser top-level navigation → ALLOW
- Requests WITH `Sec-Fetch-Site: same-origin|same-site|cross-site` = browser-mediated
  request, potentially attacker-controlled → REJECT (403)

The stdio shim never sends `Sec-Fetch-Site`. Default behavior (absent header → pass) is
correct for the stdio path.

### DNS rebinding CVEs

- **CVE-2018-5702** — Transmission BitTorrent client. DNS rebinding bypassed the
  loopback RPC daemon. Mitigation: Host header whitelist for requests that cannot be
  proven secure. Exploit: attacker DNS pointed to 127.0.0.1 after initial handshake.
- **CVE-2018-1099** — etcd 3.3.1. DNS rebinding allowed CSRF + SSRF against the etcd
  cluster API. Mitigation: Host header validation + CSRF token enforcement.
- **nip.io attack surface**: `anything.127.0.0.1.nip.io` resolves to 127.0.0.1 in a
  SINGLE lookup. This is NOT a rebinding attack — it is a static wildcard DNS service.
  The Host header would be `anything.127.0.0.1.nip.io`, which is NOT in
  `LOOPBACK_HOST_HEADER_HOSTS` and would be correctly rejected by the existing
  `HostValidationMiddleware`. This means the current implementation already defends
  against nip.io-style bypass.

### State of DNS Rebinding in 2023 (NCC Group / APNIC)

Modern browser same-site cookie improvements and reduced TTL caching have reduced but
not eliminated DNS rebinding effectiveness. Against localhost servers without proper
Host validation, rebinding attacks on iOS/Safari can succeed in under 3 seconds.

---

## Failure-mode analysis

**FM1: Stdio shim's no-Origin requests blocked by `ARXMCP_ALLOWED_ORIGINS=[]`.**
The brief says "default: empty list, meaning only no-Origin requests are accepted."
This is semantically reasonable: empty list means "no browser Origin is allowed, only
no-Origin (stdio) passes." Implementation: if `ARXMCP_ALLOWED_ORIGINS` is set to
non-empty, those specific Origins are additionally permitted alongside no-Origin.
Default empty = stdio-only, no browser access. This is the INTENDED behavior and
does not create a regression for the shim.

**FM2: `Host: localhost` vs `Host: 127.0.0.1` equivalence.**
Both are in `LOOPBACK_HOST_HEADER_HOSTS`. Edge cases: `localhost.` (trailing dot) is
NOT in the set and will be rejected — this is the correct behavior. `LOCALHOST`
(uppercase) is lowercased by `_validate_host_header` before lookup — safe. IPv6
`[::1]` is handled by bracket-stripping logic in the existing implementation.

**FM3: DNS rebinding via `Host: 7f000001.nip.io`.**
`7f000001.nip.io` resolves to 127.0.0.1 but the HOST HEADER is `7f000001.nip.io`, not
`127.0.0.1`. The `HostValidationMiddleware` compares the Host header value string —
not its DNS resolution. So `7f000001.nip.io` IS correctly rejected. True DNS rebinding
(attacker.com resolves to 127.0.0.1 at connection time) is also blocked because the
Host header sent by the browser would be `attacker.com`, not `127.0.0.1`.

**FM4: Browser sends Origin AND `Sec-Fetch-Site: cross-site`.**
The correct check order is: `Sec-Fetch-Site` check FIRST (fast reject), then Origin
check. Either check failing independently should reject. Both being present with
malicious values is doubly rejected (at the first check encountered). The middleware
stack should add `Sec-Fetch-Site` validation as a separate middleware or extend
`OriginValidationMiddleware` — prefer a new `SecFetchSiteMiddleware` positioned
outermost (before `OriginValidationMiddleware`) so the cheap string check fires first.

**FM5: `ARXMCP_BIND_HOST=0.0.0.0` + `ARXMCP_UNSAFE_NETWORK_BIND=1` escape hatch.**
This escape hatch does not exist yet. When added to `Config`, it must use a
`model_validator(mode="after")` (same pattern as `validate_otel_endpoint_loopback`)
to check BOTH fields together. The escape hatch must emit a WARN log at startup. The
escape hatch is for container deployments only — the operator must understand they are
deliberately allowing container-internal 0.0.0.0 binding.

**FM6: Tests run on CI host with port already in use.**
The bind-host refusal AC test must test `Config()` validation, NOT actually open a
socket. The existing `TestStartupRejectsBadBind` in `tests/test_security.py` uses
`subprocess.run` against `python -m server.main` with the env var. The new test in
`tests/security/test_origin_binding.py` should test the Config validation directly to
avoid port-binding in CI.

**FM7: Host header comma-separated (RFC violation).**
`Host: 127.0.0.1, attacker.com` — the current `_validate_host_header` would parse this
as a single string `"127.0.0.1, attacker.com"`, which is NOT in
`LOOPBACK_HOST_HEADER_HOSTS` and is thus correctly REJECTED. No additional handling
needed; the strict allowlist approach naturally handles this.

**FM8: `ARXMCP_ALLOWED_ORIGINS` CSV parsing.**
The env var is a comma-separated list. Parsing: `str.split(",")` + `strip()` each
entry + filter empty strings. Case sensitivity: URL schemes are lowercase per RFC; the
existing `_origin_is_allowed` uses `urlparse` which lowercases scheme + host. Store as
`frozenset` of lowercased origin strings. Trailing slash: `http://localhost:7733/` vs
`http://localhost:7733` — strip trailing slashes at parse time for consistency.

**FM9: `Sec-Fetch-Site` with empty value vs absent vs `"none"`.**
- Absent: CLI tool or shim → PASS (no header = not a browser request)
- `none`: browser top-level navigation → PASS
- `""` (empty): pathological input → REJECT (treat as "present but invalid")
- Any other value: REJECT

**FM10: Reverse proxy clobbers Host header.**
If nginx terminates TLS and forwards, the `Host` header may be rewritten to the
upstream service. This is a deployment concern. At v1 (single-user, no proxy), the
Host sent is always the direct client's. Document in the binding.md artifact that
Host validation may need `trusted_proxies` bypass in proxy deployments (deferred).

---

## Recommendation

**Implement `SecFetchSiteMiddleware` as a new pure-ASGI middleware class in
`server/middleware.py`, and add `ARXMCP_ALLOWED_ORIGINS` + `ARXMCP_UNSAFE_NETWORK_BIND`
fields to `server/config.py`.**

Specific implementation choices:

1. **`SecFetchSiteMiddleware`**: Mount BEFORE `OriginValidationMiddleware` (outermost
   check). Logic: if `Sec-Fetch-Site` header is absent → pass; if value is `b"none"`
   → pass; else → 403. Pure-ASGI (no `BaseHTTPMiddleware`). Log at WARN on reject.

2. **`ARXMCP_ALLOWED_ORIGINS`**: Add to `Config` as `allowed_origins: list[str] = []`.
   Parse CSV from env. Empty list means "only no-Origin requests accepted" (stdio
   path). Non-empty extends the Origin allow-list beyond the loopback defaults.
   `OriginValidationMiddleware` must be updated to read this at construction time.

3. **`ARXMCP_UNSAFE_NETWORK_BIND`**: Add to `Config` as `unsafe_network_bind: bool =
   False`. Use `model_validator(mode="after")` to allow `bind_host=0.0.0.0` ONLY when
   `unsafe_network_bind=True`. Emit `logger.warning("ARXMCP_UNSAFE_NETWORK_BIND=1 is
   set; server binding to 0.0.0.0...")` at startup.

4. **Tests** in `tests/security/test_origin_binding.py` — 6 test cases:
   - `Sec-Fetch-Site: cross-site` → 403
   - `Sec-Fetch-Site: same-site` → 403
   - `Sec-Fetch-Site: none` → passes
   - `Host: 1.2.3.4` (public IP) → 421 (already works via `HostValidationMiddleware`)
   - `Host: attacker.localhost` → 421 (already works)
   - `ARXMCP_BIND_HOST=0.0.0.0` without unsafe flag → `ValidationError` at Config()

5. **Docker compose AC**: create `.claude/docs/security-docker-compose-ports.md` with
   the annotated YAML snippet from `08-security-observability-ops.md` (no live
   infrastructure exists to test against).

6. **Tool-schema**: none of these changes touch `server/tools.py::ALL_TOOLS`. No
   `EXPECTED_TOOL_SCHEMA_SHA256` re-pin needed.

7. **Doc placement**: `.claude/docs/security-threat-5-audit.md` and
   `.claude/docs/security-binding.md` (NOT `docs/security/`).

---

## Open questions

**OQ1: `OriginValidationMiddleware` + `ARXMCP_ALLOWED_ORIGINS` interaction.**
The current middleware uses the hardcoded `LOOPBACK_ORIGIN_HOSTS` frozenset. With the
new env var, the middleware must accept loopback origins OR any origin in
`ARXMCP_ALLOWED_ORIGINS`. The implementer must decide whether `ARXMCP_ALLOWED_ORIGINS`
REPLACES or EXTENDS the loopback list. **Recommendation: EXTENDS.** The loopback allow-
list is a security floor and must never be bypassed by the env var.

**OQ2: Where does `SecFetchSiteMiddleware` read the config?**
The Config object is instantiated once at lifespan startup. Middleware constructors run
at `create_app()` time (before the Config is instantiated with real env vars in some
test scenarios). The pattern used by `HostValidationMiddleware` (takes `allowed_port:
int | None = None` as a constructor arg) is the right approach — pass a
`sec_fetch_site_enabled: bool = True` flag so tests can disable it if needed.

No open questions that block implementation — OQ1 and OQ2 have recommendations above.

---

## External writes the implementation will require

None — this milestone is purely local (tests, middleware, config, doc artifacts).
No git push, PR creation, or infra mutation is required; the implementing agent commits
to main and the orchestrator authorizes the push in Phase 4.
