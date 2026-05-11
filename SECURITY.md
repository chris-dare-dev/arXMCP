# Security Policy

## Scope

arXMCP is a local-first MCP server intended to run on a single workstation,
loopback-bound, behind no public network surface. The threat model assumes
the operator's machine is the trust boundary; the server itself ships no
authentication layer because every request originates from that same
machine.

The full threat model (seven named threats, mitigations, and ongoing-test
coverage) is documented in
[`.claude/notes/08-security-observability-ops.md`](.claude/notes/08-security-observability-ops.md).
That note is the authoritative source; this file is the public-facing
contact + reporting policy.

## Reporting a vulnerability

This is a single-user research project. There is no public bug-bounty or
disclosure program. If you find a security issue and want it addressed:

1. Contact the owner directly — see [`OWNERS.md`](OWNERS.md).
2. Include enough detail to reproduce: affected component, the input or
   sequence of calls that exercises the issue, and the observed vs.
   expected behavior.
3. Please do NOT open a public GitHub issue for unfixed vulnerabilities
   until the owner has had a chance to assess and patch.

The owner will respond best-effort; there is no SLA.

## Supported versions

Only the `main` branch is supported. arXMCP is currently `0.1.0` pre-release;
there are no point releases. Security patches land on `main` directly.

## Security-relevant invariants

The implementation enforces these at config-parse time, request-handling
time, or via the test suite. Removing any of them in a PR is a
regression — please do not.

| Invariant | Enforced by |
|---|---|
| **Loopback-only bind.** `127.0.0.1` / `::1`. Refuses `0.0.0.0`. | `server/config.py::reject_non_loopback` |
| **Origin pinning.** MCP 2025-06-18 spec MUST. 403 on non-loopback `Origin`. | `server/middleware.py::OriginValidationMiddleware` |
| **Host pinning.** Threat 5 / DNS-rebinding defense. | `server/middleware.py::HostValidationMiddleware` |
| **Request body cap.** 1 MB; uvicorn has no native knob. | `server/middleware.py::RequestBodySizeLimitMiddleware` |
| **Response body cap.** 256 KB inline; `resource_link` fallback for larger payloads. | `server/main.py::BodySizeCapMiddleware`, `server/tools.py::enforce_byte_cap` |
| **Per-session retrieval caps.** 3 `search_papers` + 4 `get_chunk` per `Mcp-Session-Id`. | `server/middleware.py::SessionCapMiddleware`, `server/session.py` |
| **`paper_id` / `chunk_id` regex validation** before any I/O on every tool input. | `ingest/identifiers.py` + per-handler validation |
| **safetensors-only model loading.** Pickle `.bin` weights refused. | `ingest/embedder.py` (Threat 6) |
| **TLS verification on** for every outbound HTTP call. | Default `urllib.request.urlopen`; no opt-out anywhere. |
| **Response size cap** on external fetches (OpenAlex, INSPIRE, arXiv). | Per-source constants (`OPENALEX_MAX_RESPONSE_BYTES`, `INSPIRE_MAX_RESPONSE_BYTES`, `MAX_RESPONSE_BYTES`). |
| **Loopback-only shim egress.** `arxmcp-shim` refuses to proxy to non-loopback hosts. | `shim/arxmcp_shim.py` |
| **Security headers.** `X-Content-Type-Options: nosniff` + `X-Frame-Options: DENY` on every response. | `server/middleware.py::SecurityHeadersMiddleware` |
| **Single source of truth for identifier regexes.** Drift would expose path traversal. | `ingest/identifiers.py` + `tests/test_identifiers.py` |

The full threat-by-threat audit (Threat 1: path traversal; Threat 2:
prompt injection; Threat 3: LaTeXML sandbox; Threat 4: resource
exhaustion; Threat 5: Origin/DNS-rebinding; Threat 6: supply chain;
Threat 7: source-ingestion TLS / content-length) lives in
[`.claude/notes/08-security-observability-ops.md`](.claude/notes/08-security-observability-ops.md).

## Test coverage

Security-relevant invariants are pinned by tests under `tests/`, especially:

- `tests/test_security.py` — Origin/Host validation, body-size cap,
  security headers
- `tests/test_server_startup.py` — loopback-bind enforcement
- `tests/test_session_caps.py` — per-session retrieval caps
- `tests/test_identifiers.py` — `paper_id` / `chunk_id` regex
- `tests/test_shim.py` — shim loopback-only egress

A future milestone (E13 — Security Hardening) will add a structured audit
across all seven tool handlers.
