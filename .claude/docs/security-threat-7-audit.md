# Threat 7 audit — source ingestion TLS, content-length enforcement, and CA pinning

**Threat model source:** [`.claude/notes/08-security-observability-ops.md`](../notes/08-security-observability-ops.md) § Threat 7
**Milestone:** E13_S07
**Status:** SHIPPED 2026-05-19

## Threat statement (verbatim)

> ### Threat 7: Source ingestion (arxiv.org, ar5iv)
>
> We fetch from arxiv.org and ar5iv.labs.arxiv.org. If either is compromised, we ingest poisoned content.
>
> **Mitigations:**
> - Verify TLS certs (default for the HTTP client; do not disable).
> - Pin known fingerprint of arxiv.org's certificate authority chain (rotated periodically).
> - Content-length sanity checks (a single paper > 100 MB source is suspicious).
> - Sandbox the parser (Threat 3 mitigation covers downstream impact).

## What this milestone changed

E13_S07 is **gap-closure + audit**. The brief implied E11_S02 had shipped the
100 MB content-length cap; in fact only per-service caps existed
(OpenAlex 5 MB, INSPIRE 8 MB, arxiv-fetch 200 MB safety-net) and the two
unbounded fetch paths — `ingest/ar5iv_fetch.py` and `ingest/oai_delta.py` —
were silently buffering whatever the server sent. This milestone closes that
gap and audits the TLS-cannot-be-disabled posture.

## Compliance matrix

| Fetch site | TLS default-on | Content-Length pre-check | Read-cap | Redirect-host pin | Cap value |
|---|---|---|---|---|---|
| `ingest/ar5iv_fetch.py` | ✅ (urllib system trust) | ✅ NEW | ✅ NEW | ✅ existing | 100 MB |
| `ingest/oai_delta.py::_fetch_page` | ✅ | ✅ NEW | ✅ NEW | ✅ existing | 100 MB |
| `tools/arxiv_fetch.py` | ✅ | ✅ existing | ✅ existing (cap **tightened** 200 → 100 MB) | n/a (single-host TOS contract) | 100 MB |
| `ingest/graph_ingest.py` | ✅ | n/a (per-service cap is tighter) | ✅ existing | ✅ E13_S07b | 5 MB |
| `ingest/inspire_ingest.py` | ✅ | n/a (per-service cap is tighter) | ✅ existing | ✅ E13_S07b | 8 MB |
| `ingest/intra_paper_refs.py` | n/a (reads local files) | n/a | ✅ via local size check | n/a | 50 MB |

The 100 MB threshold is the Threat-7 budget cited verbatim in the threat
model ("a single paper > 100 MB source is suspicious"). The two unbounded
paths (ar5iv + oai_delta) now share the same constant and the same
two-tier enforcement: **Content-Length pre-check** (refuse before any
body is read when the server announces oversized) + **read-cap**
(`response.read(MAX + 1)`, refuse if actual bytes exceed `MAX` — catches
lying headers and chunked encoding without a declared length).

## TLS verification — safe by default, cannot be disabled

`urllib.request.urlopen` uses `urllib.request.ssl.create_default_context()`
which sets `check_hostname=True` and `verify_mode=ssl.CERT_REQUIRED`. There
is no `ARXMCP_*` env var that disables this — not because pydantic rejects
the var, but because **no Config field exists for it to bind to**. The
regression guard in `tests/security/test_source_ingest.py::TestTlsCannotBeDisabled`
pins the contract three ways:

1. `Config.model_fields` does not contain any TLS-toggle field name
   (a forbid-list of `verify_tls`, `tls_verify`, `insecure_tls`,
   `disable_tls_verification`, `skip_tls_verify`).
2. Setting `ARXMCP_VERIFY_TLS=0` in the environment is silently ignored
   by pydantic-settings — Config constructs successfully and no
   matching attribute is bound. Downstream code therefore has nothing
   to read and TLS verification remains on.
3. No production code in `ingest/`, `tools/`, or `server/` constructs
   an insecure `ssl.SSLContext` — the walk rejects
   `check_hostname=False`, `verify_mode=ssl.CERT_NONE`,
   `verify_mode=ssl.CERT_OPTIONAL`, or `_create_unverified_context`.

The strongest defense is the **absence of the knob**, not a noisy
rejection: an operator who attempts to disable TLS sees no error
message but also gets no observable change in behavior. Belt + braces
with the source-code walk catches future regressions if a developer
adds a custom SSLContext anywhere.

**Operator-level threat (out of code-level scope):** `SSL_CERT_FILE` and
`SSL_CERT_DIR` are honored by Python's `ssl` module to locate the CA
bundle. An operator (or malicious cron script) with shell access could
point these at a tampered bundle. Mitigation is a deployment-hardening
concern, not a code-level guard. The container image (`docker/Dockerfile.server`)
should treat these vars as untrusted and either unset them at entry or
document them as part of the operator's threat model.

## Content-Length semantics (RFC 9110 / RFC 9112)

- **Header may be absent.** HTTP/1.1 with `Transfer-Encoding: chunked` does
  not carry Content-Length. HTTP/2 frames carry no Content-Length. Trailer
  fields explicitly **cannot** carry Content-Length (RFC 9110 § 6.5).
  Implication: the read-cap is the load-bearing guard, not the pre-check.

- **Header may lie.** A malicious server may declare 1 KB and send 200 MB.
  Python's `urlopen.read()` reads until EOF, not until the declared length.
  Implication: `response.read(MAX + 1)` bounds the actual buffered memory
  regardless of what the header claims.

- **Compressed vs uncompressed.** `Content-Encoding: gzip` makes the declared
  size the **compressed** size. Today's fetch sites do NOT auto-decompress
  (`response.read()` returns raw gzipped bytes if the server sets that
  encoding header). A future enhancement that adds `gzip.GzipFile` wrapping
  must add a decompressed-size accumulator too.

- **Multipart / aggregate.** `Content-Type: multipart/mixed` has no single
  Content-Length covering the whole document. Today's fetch sites do not
  parse multipart; the body is treated as a single blob subject to the cap.

## CA pinning — `ARXMCP_PIN_ARXIV_CA` (opt-in, forward-compat)

The threat model lists "pin known fingerprint of arxiv.org's certificate
authority chain (rotated periodically)" as a mitigation. We add the
config-flag plumbing today but defer the actual certificate-chain
inspection because:

1. arxiv.org rotates its CA periodically, so a hard-coded pin without an
   operator-refresh procedure creates more operational toil than security
   benefit at Tier-5.
2. Live cert inspection requires production network access and a
   documented update cadence; both are out of scope for a code-only
   audit.

The plumbing today:

- `Config.pin_arxiv_ca: bool = False` (the `server/config.py` field).
- Mapped to env var `ARXMCP_PIN_ARXIV_CA`. Pydantic `BaseSettings` accepts
  the standard truthy values (`"1"`, `"true"`, `"True"`).
- When True, the value is accepted by Config but **has no current
  behavior**. The server today emits no startup INFO log on opt-in;
  the log line and the SSL-context wiring land together in the
  closure milestone (provisionally `E13_S07b` or rolled into a future
  hardening pass) that implements the actual `ssl.SSLContext`
  configuration. F1 rectification (E13_S07 adversary): the prior
  draft of this doc and the field's docstring claimed an INFO log
  was emitted today; that was aspirational, not actual.
- Default False is production-ready: the system trust store + the
  Content-Length cap already cover Threat 7's primary attack surface.

## Acceptance-criteria status

| Brief AC | Status | Where met |
|---|---|---|
| `pytest tests/security/test_source_ingest.py` passes | ✅ | new test file, 4 classes |
| TLS verification cannot be disabled via any `ARXMCP_*` env var | ✅ | `TestTlsCannotBeDisabled` (3 tests: no field exists, env var is silently ignored, no insecure SSLContext anywhere in production code) |
| 200 MB fixture response rejected without reading > 100 MB into memory | ✅ | `TestContentLengthCap::test_ar5iv_rejects_oversized_content_length_before_read` — `read()` is patched with an `AssertionError` side-effect so any invocation fails the test |
| All HTTP clients in `ingest/sources/` use the shared client; grep CI check | ⚠️ **reframed** — no `ingest/sources/` dir or `httpx` exists; replaced with `TestNoVerifyFalse` walk of `ingest/`, `tools/`, `server/` for any `verify=False` regression. Runs in `make test` (no CI per CLAUDE.md §4.1) |
| `ARXMCP_PIN_ARXIV_CA` flag (opt-in) documented in audit doc | ✅ | This doc + `TestPinArxivCaFlag` (3 tests: default-False, env opt-in, doc references the flag verbatim) |

## Deviations from the brief

The brief was generated against an assumed file layout that does not
match the repo:

1. **`docs/security/threat-7-audit.md`** → this file at
   `.claude/docs/security-threat-7-audit.md`. CLAUDE.md §1 restricts
   `docs/` to operator-facing content (today: only `docs/install.md`).
   All E13_S01–S06 audit docs landed under `.claude/docs/`; this
   milestone follows that precedent.

2. **"CI lint rule"** → pytest gate + optional Makefile target.
   CLAUDE.md §4.1: "No CI / GitHub Actions blocking merges." The
   pytest gate (`TestNoVerifyFalse`) is part of `make test` so the
   check is genuinely enforced.

3. **"single shared `httpx.Client` at module import time" + `ingest/sources/`**
   → no refactor. The codebase uses `urllib.request` throughout (which
   is safe-by-default for TLS), and no `ingest/sources/` directory
   exists. Refactoring to `httpx` is large-scope work with zero
   security benefit; the audit instead enforces the equivalent
   contract (no `verify=False` anywhere) and adds the missing 100 MB
   cap in-place at each existing fetch site.

4. **"E11_S02 already enforces the 100 MB content-length cap"** —
   FALSE. E11_S02 did not ship this cap. Per-service caps existed
   (5 MB / 8 MB / 50 MB) but the two unbounded paths
   (`ingest/ar5iv_fetch.py`, `ingest/oai_delta.py`) had no body-size
   guard. E13_S07 closes this gap.

5. **`tools/arxiv_fetch.py` cap tightening** — the existing
   `MAX_RESPONSE_BYTES = 200 * 1024 * 1024` was a safety-net default
   from E01. Threat 7 explicitly cites 100 MB as the "suspicious"
   threshold. The constant is now `100 * 1024 * 1024` to align the
   three primary fetch sites on the same Threat-7 budget.

## Operator runbook

### Run the audit gate locally

```bash
make test           # includes tests/security/test_source_ingest.py
```

### Generate a fresh verify=False scan (developer pre-push convenience)

Today's enforcement is the pytest gate. No standalone Makefile target is
added (the gate is part of `make test`, which the project considers
authoritative). If a future operator wants a faster check:

```bash
git grep -nE '\bverify\s*=\s*False\b' -- 'ingest/**.py' 'tools/**.py' 'server/**.py'
```

Empty output means clean.

### Enable opt-in CA pinning (forward-compat)

```bash
export ARXMCP_PIN_ARXIV_CA=1
make up
```

Today this is a forward-compat stub — the flag is accepted by Config
but has **no current behavior**. Setting it does not change the SSL
context and does not produce any log line. A future milestone will
both (a) wire `ssl.SSLContext.load_verify_locations(...)` against a
hardcoded arxiv.org CA bundle and (b) add the operator-facing INFO
log so the opt-in is visible at startup. The flag default stays
False until that closure lands.

### Known gaps

- ~~`ingest/graph_ingest.py` and `ingest/inspire_ingest.py` do NOT validate
  redirect hosts after fetch.~~ **CLOSED by E13_S07b** (2026-05-22, GitHub
  issue [`#2`](https://github.com/chris-dare-dev/arXMCP/issues/2)). Both
  `_fetch_openalex_work` and `_fetch_inspire_record` now capture
  `resp.url` after the body read and raise `RuntimeError` if it does not
  start with `OPENALEX_BASE + "/"` / `INSPIRE_API_BASE + "/"` — the same
  redirect-host pin used by `ar5iv_fetch.py` and `oai_delta.py`. The
  trailing `/` closes the prefix-collision vector
  (`https://api.openalex.org.evil.com/…`) that a bare `startswith` would
  miss. Regression coverage:
  `tests/security/test_source_ingest.py::TestRedirectHostPin` (6 tests:
  off-host rejection + on-host acceptance + prefix-collision rejection,
  per module).

- `ingest/oai_delta.py` and `ingest/ar5iv_fetch.py` do not currently auto-
  decompress `Content-Encoding: gzip` bodies. If a future change adds
  decompression, a decompressed-size accumulator must be added too
  (compressed size can be small while decompressed size is unbounded).
  (Still open — out of E13_S07b scope.)

## References

- [`ingest/ar5iv_fetch.py`](../../ingest/ar5iv_fetch.py) — `AR5IV_MAX_RESPONSE_BYTES` + dual-tier check
- [`ingest/oai_delta.py`](../../ingest/oai_delta.py) — `OAI_PMH_MAX_RESPONSE_BYTES` + dual-tier check
- [`tools/arxiv_fetch.py`](../../tools/arxiv_fetch.py) — `MAX_RESPONSE_BYTES` (tightened 200 → 100 MB)
- [`server/config.py`](../../server/config.py) — `pin_arxiv_ca` field (opt-in stub)
- [`ingest/graph_ingest.py`](../../ingest/graph_ingest.py) — `OPENALEX_BASE` redirect-host pin (E13_S07b)
- [`ingest/inspire_ingest.py`](../../ingest/inspire_ingest.py) — `INSPIRE_API_BASE` redirect-host pin (E13_S07b)
- [`tests/security/test_source_ingest.py`](../../tests/security/test_source_ingest.py) — full guard coverage (6 test classes; `TestRedirectHostPin` added by E13_S07b)
- RFC 9110 (HTTP semantics) — Content-Length, Transfer-Encoding, trailer fields
- RFC 9112 (HTTP/1.1 message syntax) — chunked encoding rules
