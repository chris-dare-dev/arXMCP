# Security Policy

## Scope & threat model

arXMCP is a local-first MCP server intended to run on a single workstation,
loopback-bound, behind no public network surface. The threat model assumes
the operator's machine is the trust boundary: every request originates from
that same machine, so the server ships **no authentication layer** by design.

| | |
|---|---|
| **In scope** | Anything that breaks the loopback-only / single-user assumptions from *within* that boundary: path traversal via tool inputs, prompt-injection through retrieved content, sandbox escapes in the LaTeXML / MinerU / Lean subprocesses, resource exhaustion, supply-chain (model weights, deps), TLS/content-length issues on outbound fetches, and DNS-rebinding / Origin-spoofing against the loopback bind. |
| **Out of scope** | Threats that require already owning the host (you are the trust boundary), LAN/remote exposure you deliberately created by overriding the loopback bind, and TLS/auth for a server that is loopback-only by design. |

The full threat model — seven named threats, mitigations, and ongoing test
coverage — is in
[`.claude/notes/08-security-observability-ops.md`](.claude/notes/08-security-observability-ops.md).
That note is authoritative; this file is the public contact + reporting
policy.

## Reporting a vulnerability

This is a single-maintainer research project. There is no bug-bounty program.
To report a security issue:

1. **Email the owner directly** — see [OWNERS.md](OWNERS.md). Use a subject
   line starting with `arXMCP security:`.
2. **Include enough to reproduce:** affected component, the input or sequence
   of calls that triggers it, and observed vs. expected behavior.
3. **Do not open a public GitHub issue** for an unfixed vulnerability until
   the owner has assessed and patched it.

### What to expect

There is no SLA, but the maintainer aims to:

- **Acknowledge** your report within ~7 days.
- **Triage** and confirm/deny within ~30 days.
- **Coordinate disclosure** — agree a timeline with you, credit you (unless
  you prefer otherwise), and note the fix in [CHANGES.md](CHANGES.md).

### Safe harbor

Good-faith research that respects this policy — staying within the loopback
boundary, not accessing data that isn't yours, and not degrading the service
for others — is welcome and will not be pursued as a violation.

## Supported versions

arXMCP is in the `0.x` pre-release line. Only the latest `main` is supported;
security patches land on `main` directly.

| Version | Supported |
|---|---|
| `main` (latest) | ✅ |
| Tagged `0.x` releases | Best-effort; upgrade to latest `main` |
| Pre-`0.1.0` | ❌ |

## Known unaudited surface

- **Operator console (`/ui/`)** — the loopback-only browser console has not
  been through the structured security audit (tracked at
  `chris-dare-dev/arXMCP#9`). Keep it loopback-only.

## Security-relevant invariants

Enforced at config-parse time, request-handling time, or via the test suite.
**Removing any of these is a regression** — please don't.

| Invariant | Enforced by |
|---|---|
| **Loopback-only bind** (`127.0.0.1` / `::1`; refuses `0.0.0.0`). | `server/config.py::reject_non_loopback` |
| **Origin pinning** — MCP 2025-06-18 MUST; 403 on non-loopback `Origin`. | `server/middleware.py::OriginValidationMiddleware` |
| **Host pinning** — DNS-rebinding defense (Threat 5). | `server/middleware.py::HostValidationMiddleware` |
| **Request body cap** — 1 MB (uvicorn has no native knob). | `server/middleware.py::RequestBodySizeLimitMiddleware` |
| **Response body cap** — 256 KB inline; `resource_link` for larger payloads. | `server/main.py::BodySizeCapMiddleware`, `server/tools.py::enforce_byte_cap` |
| **Per-session retrieval caps** — 3 `search_papers` + 4 `get_chunk` per `Mcp-Session-Id`. | `server/middleware.py::SessionCapMiddleware`, `server/session.py` |
| **`paper_id` / `chunk_id` regex validation** before any I/O on every tool input. | `ingest/identifiers.py` + per-handler validation |
| **safetensors-only model loading** — pickle `.bin` weights refused (Threat 6). | `ingest/embedder.py` |
| **TLS verification on** for every outbound HTTP call (no opt-out). | `urllib.request.urlopen` defaults |
| **Response size cap** on external fetches (OpenAlex / INSPIRE / arXiv). | per-source `*_MAX_RESPONSE_BYTES` constants |
| **Loopback-only shim egress** — refuses non-loopback hosts. | `shim/arxmcp_shim.py` |
| **Security headers** — `X-Content-Type-Options: nosniff` + `X-Frame-Options: DENY`. | `server/middleware.py::SecurityHeadersMiddleware` |
| **Single source of truth for identifier regexes** (drift would expose path traversal). | `ingest/identifiers.py` + `tests/test_identifiers.py` |

The threat-by-threat audit (Threat 1 path traversal; 2 prompt injection;
3 LaTeXML/subprocess sandbox; 4 resource exhaustion; 5 Origin/DNS-rebinding;
6 supply chain; 7 source-ingestion TLS / content-length) lives in
[`08-security-observability-ops.md`](.claude/notes/08-security-observability-ops.md).

## Test coverage

Invariants are pinned by tests under `tests/`, especially:

- `tests/test_security.py` — Origin/Host validation, body-size cap, headers
- `tests/test_server_startup.py` — loopback-bind enforcement
- `tests/test_session_caps.py` — per-session retrieval caps
- `tests/test_identifiers.py` — `paper_id` / `chunk_id` regex
- `tests/test_shim.py` — shim loopback-only egress
- `tests/security/` — Sec-Fetch-Site carve-out, request-body prefix caps

The structured security hardening pass (**E13**) has shipped — 10 milestones
covering Threats 1–7 plus logging redaction and a bind regression. Six
follow-up issues are tracked at `chris-dare-dev/arXMCP#1`–`#6`. `make sbom`
generates CycloneDX SBOMs and runs a grype scan over the pinned deps and the
built image.
