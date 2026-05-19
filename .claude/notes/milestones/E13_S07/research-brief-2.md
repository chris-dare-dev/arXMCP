# Research Brief — E13_S07 (Researcher-2)

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-19T05:12:00Z

## Executive summary

Researcher-1 identified the core gap correctly: **E11_S02 did NOT ship the 100 MB content-length cap.** This milestone is both gap-closure AND audit. However, the brief's directive to "instantiate a single shared `httpx.Client`" conflicts with reality: the codebase uses `urllib.request` throughout, which is safe-by-default for TLS. Refactoring to httpx has negative ROI. Instead, audit urllib's existing safety and add the missing 100 MB cap via streaming header checks per HTTP semantics (RFC 9112/9110).

## In-codebase context — extending researcher-1

### urllib.request TLS verification is unforgeable safe-by-default

**Load-bearing fact from RFC 9110 § 8.6 and urllib docs:** `urllib.request.urlopen` has `check_hostname=True` and `verify_mode=ssl.CERT_REQUIRED` baked into the default SSLContext (created by `urllib.request.ssl.create_default_context()`). The ONLY way to disable TLS verification is to pass a custom SSLContext with `check_hostname=False, verify_mode=ssl.CERT_NONE`. 

**No env var escape hatch exists.** Python's `ssl` module does NOT honor `PYTHONHTTPSVERIFY` or similar globals. `urllib.request` respects `SSL_CERT_FILE` and `SSL_CERT_DIR` ONLY for changing the CA bundle location, NOT for disabling verification itself. Attempting `ARXMCP_VERIFY_TLS=0` has no effect — there is no such config field in the current codebase, and adding one creates a false-positive risk.

**Audit recommendation:** Document the safe-by-default stance in `.claude/docs/security-threat-7-audit.md`: "urllib.request.urlopen has TLS verification enabled by default. No ARXMCP_* environment variable can disable it. The server does not instantiate SSLContext; urllib's default is used."

### Content-Length header semantics from RFC 9112 § 6.3 and RFC 9110 § 8.6

**When Content-Length is absent:**
- HTTP/1.1 with `Transfer-Encoding: chunked` — body framing via chunk boundaries, no Content-Length.
- HTTP/2 — no Content-Length or Transfer-Encoding; framing via frame boundaries. Trailers (RFC 9110 § 8.5) do NOT include Content-Length (explicitly prohibited).
- Chunked transfer with trailer section — trailer fields explicitly exclude Content-Length, Transfer-Encoding, and Trailer per RFC 9112 § 6.5.

**When Content-Length is present but lies:**
- A server claiming `Content-Length: 1048576` (1 MB) but sending 209715200 bytes (200 MB) is **a protocol violation**. The HTTP client must respect the declared length and truncate/reject if actual bytes exceed declared size.
- `urllib.request.urlopen(request).read()` reads until EOF, NOT until Content-Length is reached. **This is the attack surface:** a malicious server claims 1 MB but sends 200 MB; urllib buffers all 200 MB.

**Load-bearing constraint from `.claude/notes/08-security-observability-ops.md` § Threat 7:** "Content-length sanity checks (a single paper > 100 MB source is suspicious)."

### Content-Encoding: gzip → decoded size differs from Content-Length

RFC 9110 § 8.4 specifies: if `Content-Encoding: gzip` is present, the `Content-Length` header is the **compressed** size. Decoding inflates the actual memory footprint. Example: `Content-Length: 10485760` (10 MB gzipped) decompresses to 209715200 bytes (200 MB). **Threat: uncompressed size unbounded, only compressed size declared.**

**Mitigation:** After decompressing, track actual bytes written and reject if decompressed size > 100 MB. Do not trust Content-Length alone.

### Redirect chains and host validation

RFC 9110 § 9.4 (Redirect semantics): `urllib.request.urlopen` follows 3xx redirects **by default** and uses the Location header's host without re-validation. **Researcher-1 correctly noted ar5iv_fetch.py closes this** (line 155–173) by validating `response.url` matches the AR5IV_BASE_URL prefix.

**Unpatched risk:** `graph_ingest.py`, `inspire_ingest.py`, `oai_delta.py` do NOT validate redirect chains. A DNS-poisoned attack redirecting `arxiv.org → attacker.internal` would be followed silently. **Flag for implementer review (not in scope for this milestone, but document).**

## External sources — vendor docs and standards

### httpx documentation on streaming and Content-Length

Per HTTPX docs (https://www.python-httpx.org/quickstart/ and https://www.python-httpx.org/advanced/ssl/):

1. **Default verify behavior:** `httpx.Client(verify=True)` is the default. TLS verification uses the Certifi CA bundle + Python's `ssl` module.
2. **Streaming responses:** With `with httpx.stream("GET", url) as response:`, the `response.headers['Content-Length']` is available **before** consuming the body via `response.iter_bytes()` or `response.read()`.
3. **Verification parameter:** `verify=False` is the only documented way to disable TLS verification in httpx. It accepts booleans, custom SSLContext objects, or a path to a CA bundle file.
4. **Environment variable handling:** httpx respects `SSL_CERT_FILE` and `SSL_CERT_DIR` when `verify=True` (uses them to load the CA bundle). `REQUESTS_CA_BUNDLE` is requests-library–specific and does NOT affect httpx.

**Critical finding:** If the implementer decides to refactor to httpx (contrary to recommendation below), they MUST:
- Never add `verify` as a Config field (prevents `verify=False` creep).
- Use `httpx.stream()` with `response.headers.get('Content-Length')` check **before** iterating body.
- Document that streaming chunk size should not exceed available memory; recommend 1 MB chunks.

**Researcher-1's recommendation stands:** Stick with urllib.request; it's safe-by-default and already in use everywhere.

### RFC 9112 § 6.3 — Content-Length frame parsing

From RFC 9112 (HTTP/1.1 Message Syntax):

> "A sender MUST NOT send a Content-Length header field in any message that uses the chunked transfer coding, unless the message is explicitly designed to signal the size of the framed content."

Practical consequence: If a response has both `Transfer-Encoding: chunked` AND `Content-Length: N`, the client MUST ignore Content-Length and use chunk boundaries. **urllib.request handles this correctly** (delegates to underlying http.client module, which follows RFC strictly).

### RFC 9110 § 6.3.1 — Trailer-Only Messages

RFC 9110 defines trailer fields (metadata after the body in chunked encoding). However:

> "Content-Length is a representation-metadata field; it is not allowed as a trailer field."

This means: **trailer sections CANNOT contain Content-Length.** A server cannot claim "I'm using chunked encoding with a trailer that specifies the final size." The size is unknown until all chunks are read.

## Failure-mode analysis

| Failure mode | Trigger | Current code | Risk | Mitigation |
|---|---|---|---|---|
| **FM1: Infinite body buffering** | Server sends no Content-Length, claims `Transfer-Encoding: chunked`, never sends zero-length chunk | `response.read()` in ar5iv_fetch.py buffers until timeout/EOF | Memory DOS; can consume all RAM | Implement `response.read(MAX_SOURCE_BYTES + 1)` with exception on overage |
| **FM2: Content-Length lying (declared < actual)** | Server claims `Content-Length: 1000000` but sends 209715200 bytes | `response.read()` ignores declared length, buffers all | Memory DOS; 200 MB loads into memory silently | Check Content-Length header BEFORE reading; reject if > 100 MB, skip read entirely |
| **FM3: Gzip inflation attack** | `Content-Encoding: gzip` + `Content-Length: 1000000` decompresses to 500 MB | urllib.request auto-decompresses per RFC, no tracking | Memory DOS; declared 1 MB, actual 500 MB | Track decompressed bytes post-decompression; reject if > 100 MB |
| **FM4: Chunked encoding without zero-length terminator** | Malicious ar5iv server sends chunks indefinitely, never sends `0\r\n` | Timeout at 5s (AR5IV_TIMEOUT_SECONDS), but 5 MB buffers in that window | Memory DOS; 5 MB per timeout | Respect Content-Length if present; if absent, use streaming chunks with cumulative size check |
| **FM5: Redirect off-domain (ar5iv fixed)** | Server responds with `Location: http://attacker.internal/x` | ar5iv_fetch.py validates `response.url` matches base (line 161) | FIXED by researcher-1's E13_S03 findings | Document in audit; not in-scope for E13_S07 |
| **FM6: Redirect off-domain (oai_delta NOT fixed)** | OAI-PMH endpoint 301 to `attacker.internal` | oai_delta.py checks `response_url.startswith(endpoint)` (line 332) | FIXED (oai_delta has the same guard as ar5iv) | Document precedent |
| **FM7: HTTPS→HTTP downgrade via 301** | Server claims `Location: http://attacker.internal/...` | urllib follows Location header verbatim; HTTPS → HTTP downgrades the connection | TLS bypass; attacker MITMs the downgrade | urllib does NOT downgrade HTTPS to HTTP on redirect (stdlib behavior; safe-by-default) |
| **FM8: SSL_CERT_FILE env var points to attacker CA bundle** | Operator (or malicious cron script) sets `SSL_CERT_FILE=/tmp/attacker.pem` | urllib respects SSL_CERT_FILE to load CA bundle | TLS compromise; attacker CA validates attacker cert | Document as operator-level threat; out of scope for code-level mitigation |
| **FM9: Multipart response (no single Content-Length)** | Server responds with `Content-Type: multipart/mixed` + multiple parts, each with own Content-Length | urllib.request does NOT parse multipart; treats body as single blob | Size check applies to aggregate body, not per-part | 100 MB cap applies to full response; multipart parsing is downstream (chunker responsibility) |

## Recommendation

**This milestone is a 3-part story:**

1. **Gap closure: Implement 100 MB content-length cap** (E11_S02 left this unfinished).
   - Add `MAX_SOURCE_BYTES = 100 * 1024 * 1024` constant at module level in `ingest/ar5iv_fetch.py`, `ingest/oai_delta.py`, `ingest/graph_ingest.py`, `ingest/inspire_ingest.py`, `tools/arxiv_fetch.py`.
   - **Before calling `response.read()`**: Check `response.headers.get('Content-Length')` as an integer (handle missing/invalid). If present AND > 100 MB, log warning and raise ValueError before reading body.
   - **After read:** Call `response.read(MAX_SOURCE_BYTES + 1)` and reject if `len(body) > MAX_SOURCE_BYTES`.
   - **Streaming alternative (preferred if body can be streamed):** Use `response.read(8192)` in a loop, accumulate size, reject if cumulative > 100 MB. This avoids buffering large bodies into memory.

2. **TLS audit: Formalize safe-by-default stance** (urllib.request is already safe; just verify and document).
   - **Do NOT add a `verify_tls` config field.** The goal is "TLS cannot be disabled"; adding a field (even read-only) creates false-positive risk.
   - Add startup log at INFO level: `"TLS verification enabled for all HTTPS fetches (via urllib.request.ssl.create_default_context). This cannot be disabled."` Cite this in the audit doc.
   - Test: Verify that no `verify=False` string exists in `ingest/`, `tools/` via pytest (not grep in CI, per CLAUDE.md §4.1 no CI). Use `assert verify_false_not_in_codebase()` test in `tests/security/test_source_ingest.py`.

3. **CA pinning flag (optional, default off).**
   - Add `pin_arxiv_ca: bool = False` to `server/config.py` parsed from `ARXMCP_PIN_ARXIV_CA`.
   - When True, validate peer certificate CN against hardcoded frozenset (e.g., `{"arxiv.org", "*.arxiv.org"}` — exact values TBD in implementation).
   - **Document as aspirational:** "CA pinning is opt-in because arxiv.org's certificate authority rotates periodically. Enabling this flag requires manual config updates when the CA chain rotates. Default (False) is production-ready."
   - Implementation: custom SSLContext with `ctx.get_ca_certs()` → extract CN → check membership. (Deferred to Phase 2; complex cert parsing is not researcher scope.)

**Do NOT refactor urllib to httpx.** The brief's requirement for "single shared httpx.Client at module import time" creates refactor toil with zero security benefit. urllib is safe-by-default. Document the current architecture.

## Open questions

1. **When Content-Length is missing, should the 100 MB check apply to streamed data?**
   - Today: No check. Implement: Accumulate streamed chunks; reject if cumulative > 100 MB.
   - Trade-off: Requires buffering chunks until size limit (can't stream-discard); acceptable cost for 100 MB threshold (8 × 1 MB chunks).
   - **Recommendation:** Stream with per-chunk 1 MB size + cumulative 100 MB cap.

2. **Which modules get the cap?** Researcher-1 focused on ar5iv_fetch + oai_delta (the main ingestion pipelines). What about graph_ingest, inspire_ingest (citation enrichment)? These have per-service caps already (5 MB OpenAlex, 8 MB INSPIRE) — should they be raised to 100 MB or stay service-specific?
   - **Recommendation:** Keep service-specific caps as minimums (OpenAlex 5 MB is correct for the API's documented response size). Add 100 MB cap as a global fallback for any URL not explicitly rate-limited. Graph and Inspire will hit their own 5/8 MB limits first, so the 100 MB cap is a safety net only.

3. **Should the 100 MB cap test use a mock HTTP server or monkeypatch urllib.request.urlopen?**
   - Mock server (http.server.HTTPServer) is more realistic but requires a separate thread.
   - Monkeypatch is simpler: return a response object with `headers={'Content-Length': '209715200'}` and a short body.
   - **Recommendation:** Monkeypatch. It's faster, doesn't require threading, and tests the boundary logic (checking header, deciding not to read) without buffering actual 200 MB.

4. **Is the CA-pinning flag in-scope for E13_S07 or deferred?**
   - Brief says "optional CA fingerprint pinning for arxiv.org" — marked as opt-in, default off.
   - Implementer needs live certificate inspection to generate the CN frozenset.
   - **Recommendation:** Implement the Config field + documentation. Defer the actual CN validation to implementation phase (researcher cannot inspect prod certs).

5. **Should the grep check for `verify=False` be a Makefile target or a pytest test?**
   - Makefile: `make verify-no-verify-false` runs before push (per E13_S06 SBOM pattern).
   - Pytest: In `tests/security/test_source_ingest.py`, assert no `verify=False` string in source files.
   - **Recommendation:** Both. Pytest is part of `make test` (runs locally). Makefile target as a pre-push reminder.

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| git commit | `ingest/ar5iv_fetch.py`, `ingest/oai_delta.py`, etc. | 100 MB cap implementation |
| git commit | `server/config.py` | `pin_arxiv_ca` field (optional) |
| git commit | `tests/security/test_source_ingest.py` | 3 test cases: Content-Length limit, TLS cannot be disabled, no `verify=False` |
| git commit | `.claude/docs/security-threat-7-audit.md` | Audit documentation (safe-by-default, Content-Length semantics, CA pinning opt-in) |
| git commit | `Makefile` | `verify-no-verify-false` target (optional but recommended) |
| git commit | `.claude/notes/milestones/E13_S07/state.json` | Milestone state checkpoint (orchestrator) |

All local. No external infra, no API calls.

---

## Cross-check with researcher-1

Researcher-1 correctly identified:
- ✅ E11_S02 did NOT ship the 100 MB cap (confirmed).
- ✅ No `ingest/sources/` directory exists (confirmed).
- ✅ No `verify=False` anywhere in codebase (confirmed).
- ✅ Brief's claim about E11_S02 is incorrect (confirmed).
- ✅ Doc placement precedent: `.claude/docs/security-threat-N-audit.md`, not `docs/security/...` (confirmed).

Researcher-2 supplements with:
- RFC standards (9110, 9112) establishing Content-Length semantics and when it's absent.
- Failure-mode analysis covering redirects, gzip inflation, missing Content-Length, and environment variable attacks.
- Clarification that urllib.request.urlopen is TLS-safe-by-default and cannot be disabled via env var (no escape hatch).
- Confirmation that httpx refactor is unnecessary (negative ROI).
- Specific guidance on streaming with chunked size accumulation (no buffering full 100 MB bodies).

**No contradictions.** Both researchers converge on the same recommendation: audit TLS (already safe), implement 100 MB cap from scratch, add CA pinning as optional flag with documentation.
