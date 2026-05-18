# Threat-5 audit — Origin spoofing, DNS rebinding, and localhost-binding hardening

**Threat source:** `.claude/notes/08-security-observability-ops.md` § Threat 5
(Origin spoofing on the HTTP transport).

**Milestone:** E13_S05.

**Severity:** HIGH. A localhost MCP server without proper Origin / Host
validation can be reached by malicious local web pages via DNS-rebinding
attacks — the attacker pivots from a browser tab on `attacker.com` (which the
user visits) into the localhost MCP API.

---

## Defense layers (priority order)

The MCP 2025-06-18 spec mandates Origin validation as MUST and loopback
binding as SHOULD. Beyond the spec, arXMCP layers defense-in-depth:

1. **Origin header validation** (E06_S05, EXTENDED in E13_S05).
   `OriginValidationMiddleware` rejects any `Origin` not in the loopback
   floor (`http://127.0.0.1`, `http://localhost`, `http://[::1]`) OR the
   operator-configured `ARXMCP_ALLOWED_ORIGINS` env var (EXTENDS the floor;
   does not bypass it). Empty list (default) preserves E06_S05 behavior.
   No-Origin requests pass through (the stdio shim path).

2. **Host header validation** (E06_S05). `HostValidationMiddleware` rejects
   any `Host` not in the loopback set. Defends against DNS-rebinding:
   the browser sends `Host: attacker.com` even after DNS resolves to
   127.0.0.1, so the server can distinguish "real localhost request" from
   "rebind probe."

3. **`Sec-Fetch-Site` enforcement** (NEW in E13_S05). Pure-ASGI
   `SecFetchSiteMiddleware` rejects any value except `none` or absent. The
   header is browser-only (a "forbidden header" per Fetch Metadata spec —
   cannot be set by page scripts). CLI tools and the stdio shim omit it.
   Browser top-level navigation sends `none`. Anything else means a web
   page initiated the request and should be rejected as defense-in-depth.

4. **Localhost-only bind** (E06_S05, EXTENDED in E13_S05).
   `Config.reject_non_loopback_bind` raises `ValidationError` when
   `ARXMCP_BIND_HOST` is not in the loopback set, UNLESS
   `ARXMCP_UNSAFE_NETWORK_BIND=1` is also set. The escape hatch is for
   container deployments where the host-side port mapping pins to
   127.0.0.1 (the container internal can safely bind 0.0.0.0). Emits a
   WARN log at startup when active.

5. **Docker host-port pinning** (documented; main `docker-compose.yml`
   ships in E14). Reference deployment uses `ports: "127.0.0.1:7733:7733"`
   so the container's 0.0.0.0 binding is invisible outside the host
   loopback interface.

---

## Per-mitigation status table

| Mitigation | Mechanism | Status | Source |
|---|---|---|---|
| Origin header (MCP spec MUST) | `OriginValidationMiddleware` (loopback floor) | ✅ | E06_S05 |
| Origin allow-list extension | `OriginValidationMiddleware._extra_allowed` from `ARXMCP_ALLOWED_ORIGINS` | ✅ | E13_S05 |
| Host header (DNS-rebinding defense) | `HostValidationMiddleware` | ✅ | E06_S05 F3 |
| `Sec-Fetch-Site` enforcement | `SecFetchSiteMiddleware` | ✅ | E13_S05 |
| Bind-host loopback-only | `Config.reject_non_loopback_bind` model_validator | ✅ | E06_S05 (extended by E13_S05) |
| `ARXMCP_UNSAFE_NETWORK_BIND` escape hatch | Same model_validator + startup WARN log | ✅ | E13_S05 |
| Main docker-compose loopback mapping | Documented in design note 08; main compose ships in E14 | ⏳ E14 | Document only at v1 |

---

## Middleware mount order

```
request flow:
  SecurityHeaders ->                # outermost — applies headers to all responses
    SecFetchSite ->                 # cheap byte check on browser traffic
      OriginValidation ->           # parses & validates Origin
        HostValidation ->           # Host header check
          RequestBodySizeLimit ->   # 1 MB inbound cap
            SessionCap ->           # per-tool retrieval + hourly caps
              BodySizeCap ->        # 256 KB outbound cap
                TracingContext ->   # populate OTel ContextVars
                  handler
```

The cheapest checks fire first so attacker traffic is rejected with minimum
work. `SecurityHeaders` is OUTERMOST so even error responses from inner
middleware (e.g. 403, 421, 413) carry `X-Content-Type-Options` +
`X-Frame-Options`.

---

## DNS-rebinding attack mechanism + defense

**Attack:** the attacker's web page (loaded from `attacker.com`) issues a
`fetch("http://attacker.com:7733/")` request. DNS for `attacker.com`
initially resolves to attacker's IP; the TLS handshake succeeds. Then the
attacker's DNS server changes the record to point at `127.0.0.1` (or the
victim's local IP). The browser's connection pool reuses the existing
hostname so subsequent requests still go to `attacker.com:7733` — which
NOW resolves to localhost. The browser treats the requests as same-origin
with `attacker.com`, bypassing CORS.

**Defense (this milestone closes ALL layers):**

| Attack step | Defense | What rejects |
|---|---|---|
| Browser sends `Host: attacker.com` | `HostValidationMiddleware` | 421 Misdirected Request |
| Browser sends `Origin: http://attacker.com` | `OriginValidationMiddleware` | 403 |
| Browser sends `Sec-Fetch-Site: cross-site` (from attacker.com to attacker.com after rebind, but the header reflects the original initiator context) | `SecFetchSiteMiddleware` | 403 |
| (Bind to localhost) | `Config.reject_non_loopback_bind` | Server refuses to start on 0.0.0.0 |

CVE evidence (R2's external research):
- **CVE-2018-5702** — Transmission BitTorrent. Loopback RPC daemon
  compromised via DNS rebinding. Mitigation: Host header whitelist.
- **CVE-2018-1099** — etcd 3.3.1. DNS rebinding allowed CSRF+SSRF against
  the cluster API. Mitigation: Host + CSRF tokens.
- **NCC Group 2023 research**: DNS rebinding still effective against
  localhost servers without Host validation; iOS/Safari attack <3 s.

---

## `Sec-Fetch-Site` semantics

Four values per the W3C Fetch Metadata spec:

| Value | Meaning | arXMCP behavior |
|---|---|---|
| `none` | Top-level user-initiated navigation (address bar, bookmark, stdio shim) | **ALLOW** |
| `same-origin` | Browser fetch from the exact same origin | **REJECT** (no same-origin partner exists for a localhost MCP server) |
| `same-site` | Browser fetch from same registrable domain, different origin | **REJECT** |
| `cross-site` | Browser fetch from a different registrable domain | **REJECT** |
| (absent) | Non-browser client (curl, stdio shim, mcp-cli) | **ALLOW** |

The header cannot be forged by page scripts ("forbidden header name" per the
Fetch spec) — the browser sets it automatically based on the initiator
context. This makes it a high-signal, low-false-positive defense layer.

The MCP 2025-06-18 spec does NOT mandate this check; it is arXMCP-specific
defense-in-depth from the design note:

> *`Sec-Fetch-Site: none` enforced where possible.*

---

## `ARXMCP_ALLOWED_ORIGINS` semantics

```
ARXMCP_ALLOWED_ORIGINS='["http://my-tool.localhost:8080"]'
```

Parsed by pydantic-settings as a JSON list of strings. Each entry is
normalized at middleware-construction time (lowercased, trailing-slash
stripped, blank entries dropped).

**The env var EXTENDS the loopback floor; it never bypasses it.** The
`LOOPBACK_ORIGIN_HOSTS` frozenset is a security baseline checked first;
the env-var allow-list is checked second. There is no env var that can
weaken the loopback rejection — the floor is hardcoded.

**Default empty list = current E06_S05 behavior.** No new accepted Origins
beyond the hardcoded loopback set. Setting the var is OPT-IN.

Typical use case: an operator running a companion browser-based tool on
`http://my-arxmcp-dashboard.localhost:8080` who wants the dashboard to
fetch from the arXMCP server. The operator adds that specific origin to
the env var; no change in default behavior for other deployments.

---

## `ARXMCP_UNSAFE_NETWORK_BIND` escape hatch

**Default behavior** (`ARXMCP_UNSAFE_NETWORK_BIND` unset or `0`):
`ARXMCP_BIND_HOST` must be in `{"127.0.0.1", "::1", "localhost"}`. Any
other value raises `ValidationError` at config parse — the server
refuses to start.

**Escape hatch** (`ARXMCP_UNSAFE_NETWORK_BIND=1`): the validator permits
non-loopback bind values AND a WARN log is emitted at startup:

```
WARNING ARXMCP_UNSAFE_NETWORK_BIND=1 is set; server binding to '0.0.0.0'
        (non-loopback). Container deployments only — the host-side port
        mapping MUST still pin to 127.0.0.1. See
        .claude/docs/security-binding.md.
```

**Intended use:** containerized deployments where the container internally
binds `0.0.0.0` so the container's host-port mapping (set via Docker
`ports:` directive) is what exposes the port to the host loopback
interface. See `.claude/docs/security-binding.md` for the full warning +
the required `ports: "127.0.0.1:7733:7733"` host-side mapping.

**NOT intended for** standalone non-container deployments. A bare-metal
arXMCP server on a network-reachable host with 0.0.0.0 bind is the exact
threat the original rejection guards against.

---

## What this milestone does NOT cover

- **Authentication** — explicitly out of v1 scope (single-user
  localhost deployment).
- **mTLS** — Tier-6+ hardening.
- **Reverse-proxy Host header rewriting** — if arXMCP is deployed behind
  nginx / traefik, the Host header may be rewritten by the proxy.
  Documented in `.claude/docs/security-binding.md`; the validation may
  need a `trusted_proxies` bypass in proxy deployments (deferred until
  a proxy deployment ships).
- **The full bind regression test suite** — E13_S09 owns
  `tests/security/test_bind_regression.py` as a comprehensive suite.
  E13_S05 ships the audit / hardening / new env var; E13_S09 layers on
  the dedicated regression coverage.

---

## Audit completion checklist

- [x] **AC1** — `Sec-Fetch-Site` ≠ `none` and not absent → 403.
  `SecFetchSiteMiddleware` + `TestSecFetchSiteRejection` (7 tests).
- [x] **AC2** — Public IP in `Host` → 421. Existing
  `HostValidationMiddleware`; regression-guarded by
  `TestHostValidationRegressionForThreat5::test_public_ip_in_host_rejected`.
- [x] **AC3** — `Host: attacker.localhost` → 421. Existing
  `HostValidationMiddleware`; regression-guarded.
- [x] **AC4** — `ARXMCP_BIND_HOST=0.0.0.0` without
  `ARXMCP_UNSAFE_NETWORK_BIND=1` → `ValidationError` (server refuses
  to start). Verified by `TestUnsafeNetworkBindEscapeHatch`.
- [~] **AC5** — Reframed: main `docker-compose.yml` does not exist
  (E14 owns it). Design note `08-security-observability-ops.md`
  documents the `127.0.0.1:7733:7733` binding pattern; verified by
  `TestDesignNoteDocumentsLoopbackBinding`.
- [x] **AC6** — `pytest tests/security/test_origin_binding.py` passes
  all 23 cases.

---

## References

- `.claude/notes/08-security-observability-ops.md` § Threat 5 — primary source
- `.claude/docs/security-binding.md` — `ARXMCP_UNSAFE_NETWORK_BIND` warning
- E13_S01 audit: `.claude/docs/security-threat-1-audit.md`
- E13_S02 audit: `.claude/docs/security-threat-2-audit.md`
- E13_S03 audit: `.claude/docs/security-threat-3-audit.md`
- E13_S04 audit: `.claude/docs/security-threat-4-audit.md`
- E07 prerequisites — `E07_S01` real (BM25), `E07_S09` fictional (E07 stops at S04)
- MCP 2025-06-18 spec — Streamable HTTP Security Warning
- W3C Fetch Metadata Request Headers — `Sec-Fetch-Site` semantics
- CVE-2018-5702 (Transmission), CVE-2018-1099 (etcd) — DNS rebinding precedent
