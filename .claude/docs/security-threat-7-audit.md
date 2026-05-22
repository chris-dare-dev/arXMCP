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

## CA pinning — `ARXMCP_PIN_ARXIV_CA` (opt-in, E13_S07c wired)

The threat model lists "pin known fingerprint of arxiv.org's certificate
authority chain (rotated periodically)" as a mitigation. E13_S07 added the
config-flag plumbing; **E13_S07c (2026-05-22, closes GitHub issue
[`#5`](https://github.com/chris-dare-dev/arXMCP/issues/5)) wired it up**.

### Behavior when opted in (`ARXMCP_PIN_ARXIV_CA=1`)

- The two arxiv-rooted fetch sites — `ingest/ar5iv_fetch.py::try_cache`
  and `tools/arxiv_fetch.py::fetch_eprint` — use an `ssl.SSLContext`
  built from a pinned CA bundle (replacing the system trust store)
  instead of the OS default. The bundle is loaded via
  `ssl.create_default_context(cafile=<path>)`, which preserves the
  secure defaults (hostname verification ON, peer-cert verification
  REQUIRED).
- The pinned bundle ships as `infra/ca/arxiv-ca-bundle.pem` — a single
  PEM containing **ISRG Root X1**, the Let's Encrypt root that
  `arxiv.org`, `ar5iv.labs.arxiv.org`, and `export.arxiv.org` all chain
  to. Valid until **2035-06-04**.
- The pin is **scope-restricted to arxiv-rooted hosts** — it does NOT
  apply to `api.openalex.org` (graph_ingest), `inspirehep.net`
  (inspire_ingest), or `oaipmh.arxiv.org` (oai_delta). Those use the
  default system trust store; redirect-host pinning (E13_S07b) is
  their layered defense.

  > **Note on `oaipmh.arxiv.org`** — this IS an arxiv-rooted subdomain
  > (operated by Cornell alongside `arxiv.org` / `ar5iv.labs.arxiv.org`
  > / `export.arxiv.org`) and could in principle be added to the
  > pinned set. It is deliberately excluded from E13_S07c v1 because
  > (a) it's a separate Cornell-operated endpoint that may use a
  > distinct cert chain on its load balancer (verified at pin-refresh
  > time only for the three documented hosts), and (b) `oai_delta.py`'s
  > existing `response.url.startswith(endpoint)` redirect pin (E13_S07)
  > already provides equivalent assurance against cross-host
  > redirects. Pinning `oaipmh.arxiv.org` would require extending the
  > `make refresh-arxiv-ca` verifier to test that host's cert chain
  > too; tracked as future work alongside the caller-side coverage
  > below.

### Caller-side coverage (E13_S07c v1)

This milestone wires the SSLContext through the `try_cache` and
`fetch_eprint` **function signatures**, and threads it from the
relevant injection points down to `urllib.request.urlopen(context=...)`.
The four existing production callers — `ingest/bulk_ingest.py`
(at line ~211 in `_parse_via_ar5iv`), `tools/notebook_fetch.py`
(at line ~89), `tools/fetch_seed.py` (at line ~115), and
`tools/fetch_one_paper.py` (at line ~40) — DO NOT auto-thread the
context. They invoke the fetchers with the default
`ssl_context=None`, which falls back to the system trust store
**even when `ARXMCP_PIN_ARXIV_CA=1` is set**.

The rationale for leaving this partial-coverage state in v1:

- The bulk-ingest path crosses a layer boundary
  (`ingest/bulk_ingest.py` → `server.config` + `server.ssl_pin`).
  This is a design decision that warrants its own review rather than
  silent introduction in a security milestone.
- The dev-tooling callers (`tools/fetch_seed.py`,
  `tools/fetch_one_paper.py`) run in operator hands at corpus-build
  time; the threat surface is different from the server-warmed
  fetch path.
- The flag IS observable at startup (operators see the INFO log) so
  the partial state is not a silent contradiction — the audit doc
  here is the canonical truth source.

**Operator workaround for v1.** If you need the pin applied to bulk
ingest TODAY, explicitly build the context and pass it in:

```python
from server.config import Config
from server.ssl_pin import build_arxiv_ssl_context
from ingest.ar5iv_fetch import try_cache

ctx = build_arxiv_ssl_context(Config())
result = try_cache(paper_id, ssl_context=ctx, ...)
```

Closing the caller-side coverage is filed as a follow-up. The
function-signature wiring + factory + Config-load fail-closed +
refresh procedure are the load-bearing pieces shipped in v1.
- A startup INFO log fires when the pin is on, surfacing the bundle
  path so the operator can confirm the active configuration in the
  operational log.

### Why pin the ROOT, not the leaf or intermediate?

Let's Encrypt leaf certs rotate every 60–90 days. The intermediate
(R10/R11/E5/E6) also rotates on a months cadence. The root (ISRG Root
X1) is valid for ~20 years and rotates rarely (the next planned
rotation is to ISRG Root X2, which has already been issued as a
cross-signed standby). **Pinning the root survives the 60–90-day
intermediate rotations with zero operator intervention**, while still
blocking any non-Let's-Encrypt certificate (rogue CA, malicious system
trust-store update).

### Fail-closed contract (load-bearing)

Setting `ARXMCP_PIN_ARXIV_CA=1` without a valid CA bundle is a fatal
configuration error, not a silent degrade. Two layers enforce this:

1. **Config-load validator** (`Config.validate_arxiv_ca_bundle` in
   `server/config.py`) — runs at Config-load time, BEFORE uvicorn
   binds. Raises `ValueError` if the resolved bundle path does not
   point at a regular file. This is the primary fail-closed.
2. **Factory runtime check**
   (`server.ssl_pin.resolve_arxiv_ca_bundle`) — runs at
   ssl-context construction time. Raises `RuntimeError` for the
   bundle-deleted-post-load case (defense-in-depth). The error
   message names the bundle path AND the remediation
   (`make refresh-arxiv-ca` or unset the flag).

Silently falling back to the system trust store would defeat the
entire purpose of the pin (a compromised system store is precisely
what the pin defends against).

### Operator override

Operators with a custom bundle (e.g. a private CA in front of an
arxiv mirror) can set `ARXMCP_ARXIV_CA_BUNDLE_PATH=/path/to/bundle.pem`.
The override path is taken verbatim; the Config validator confirms
it exists. When unset, the vendored bundle at
`infra/ca/arxiv-ca-bundle.pem` is used.

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

### Enable opt-in CA pinning

```bash
export ARXMCP_PIN_ARXIV_CA=1
make up
```

Startup INFO log will confirm the active pin:

```
INFO server.main: ARXMCP_PIN_ARXIV_CA=1 set; using pinned CA bundle
     at <repo>/infra/ca/arxiv-ca-bundle.pem for arxiv.org /
     ar5iv.labs.arxiv.org / export.arxiv.org fetches (Threat 7
     mitigation #2). Refresh via `make refresh-arxiv-ca`.
```

If the bundle is missing/unreadable, startup fails with a clear
`ValueError` from `Config.validate_arxiv_ca_bundle` — the server does
NOT bind. Run `make refresh-arxiv-ca` to (re)create the bundle.

### Refresh the pinned CA bundle

```bash
make refresh-arxiv-ca
```

The target re-downloads ISRG Root X1 from
`https://letsencrypt.org/certs/isrgrootx1.pem`, verifies the new PEM
accepts the live cert chains of `arxiv.org`, `export.arxiv.org`, AND
`ar5iv.labs.arxiv.org` via `openssl s_client`, and only then writes
`infra/ca/arxiv-ca-bundle.pem`. The target REFUSES the overwrite if
any of the three hosts fails verification — review the failure
manually rather than committing a broken bundle.

**Cadence guidance.** ISRG Root X1 is valid until 2035-06-04. The
root rotates rarely (next planned move is to ISRG Root X2). Refresh
the bundle when:

- You see `ssl.SSLCertVerificationError` on every arxiv-rooted fetch
  (likely root rotation),
- After a fresh clone where the bundle was somehow missing
  (the file is committed and should be present),
- As part of a periodic audit (e.g. annually), to confirm the
  vendored bundle still matches what `make refresh-arxiv-ca`
  would produce.

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
