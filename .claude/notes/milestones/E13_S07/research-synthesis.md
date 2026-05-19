# Research Synthesis — E13_S07

**Generated:** 2026-05-19 (orchestrator merge of brief-1 and brief-2)
**Mode:** standard (2× milestone-researcher, Haiku 4.5)

---

## Current state of the world (load-bearing)

**HTTP client stack:** the codebase uses **`urllib.request`** for every HTTP fetch.
There are ZERO uses of `httpx.Client` or `httpx.AsyncClient`. The brief's
prescription "all HTTP clients in `ingest/sources/` must instantiate a single
shared `httpx.Client`" is drift from the actual implementation.

**`ingest/sources/` directory does not exist.** Real fetch sites are scattered:

| Module | Existing size cap | Status |
|---|---|---|
| `tools/arxiv_fetch.py` | `MAX_RESPONSE_BYTES = 200 * 1024 * 1024` | ✅ Content-Length pre-check + read-cap |
| `ingest/graph_ingest.py` | `OPENALEX_MAX_RESPONSE_BYTES = 5 * 1024 * 1024` | ✅ read-cap (no header pre-check) |
| `ingest/inspire_ingest.py` | `INSPIRE_MAX_RESPONSE_BYTES = 8 * 1024 * 1024` | ✅ read-cap (no header pre-check) |
| `ingest/intra_paper_refs.py` | `MAX_HTML_BYTES = 50 * 1024 * 1024` | ✅ uses local-file size check (offline path) |
| `ingest/ar5iv_fetch.py:154` | **NONE** | ❌ `body_bytes = response.read()` — unbounded |
| `ingest/oai_delta.py:329` | **NONE** | ❌ `body = response.read()` — unbounded |
| `tools/curate_seed.py` | per-call read (TBD) | check during implementation |
| `tools/daily_metrics_report.py` | metrics fetch (TBD) | check during implementation |

**No `verify=False` anywhere in the codebase.** Grep over `ingest/` + `tools/`
returned zero matches. `urllib.request.urlopen` is safe-by-default per RFC 9110
§ 8.6 (uses `urllib.request.ssl.create_default_context()` which has
`check_hostname=True, verify_mode=ssl.CERT_REQUIRED`). No `ARXMCP_*` env var
exists today that can disable TLS.

**Existing redirect-host pinning (good):**

- `ingest/ar5iv_fetch.py:160-173` validates `response.url.startswith(AR5IV_BASE_URL + "/")`
- `ingest/oai_delta.py:332` validates `response_url.startswith(endpoint)`

So redirects to attacker-controlled hosts already raise. The remaining gap is
**body-size enforcement** on ar5iv + oai_delta.

---

## Threat 7 verbatim (from `.claude/notes/08-security-observability-ops.md`)

> ### Threat 7: Source ingestion (arxiv.org, ar5iv)
>
> We fetch from arxiv.org and ar5iv.labs.arxiv.org. If either is compromised, we ingest poisoned content.
>
> **Mitigations:**
> - Verify TLS certs (default for the HTTP client; do not disable).
> - Pin known fingerprint of arxiv.org's certificate authority chain (rotated periodically).
> - Content-length sanity checks (a single paper > 100 MB source is suspicious).
> - Sandbox the parser (Threat 3 mitigation covers downstream impact).

---

## Brief/repo conflicts — resolved by orchestrator

Same systematic drift as E13_S01–S06. Resolutions:

| # | Brief says | Repo policy | Resolution |
|---|---|---|---|
| 1 | `docs/security/threat-7-audit.md` | CLAUDE.md §1: `docs/` is operator-only (`install.md` only) | Use `.claude/docs/security-threat-7-audit.md` (E13 precedent) |
| 2 | `CI lint rule: grep -r "verify=False" ingest/ fails the build` | CLAUDE.md §4.1: no CI | Two-pronged replacement: (a) a pytest test that walks `ingest/` and `tools/` for the pattern (runs in `make test`), (b) optional `Makefile verify-no-verify-false` target for an explicit pre-push check |
| 3 | "all HTTP clients in `ingest/sources/` must instantiate a single shared `httpx.Client`" | Codebase uses `urllib.request`; no `httpx` clients exist; no `ingest/sources/` directory | **Do NOT refactor to httpx.** urllib is safe-by-default for TLS; refactoring is large-scope work with zero security benefit. Document that urllib.request is the canonical client; add the size cap in-place at each existing fetch site |
| 4 | "E11_S02 already enforces the 100 MB content-length cap" | **FALSE** per both researchers. E11_S02 did NOT ship a general 100 MB cap. Per-service caps exist (5 MB / 8 MB / 50 MB) but the umbrella 100 MB cap on ar5iv + oai_delta is missing | E13_S07 implements the cap from scratch on the two unbounded paths (ar5iv_fetch + oai_delta). Per-service caps remain as tighter minimums |

---

## Where briefs disagreed — orchestrator decisions

The briefs agreed substantively. Minor differences:

1. **Add a `verify_tls` Config field?** Both briefs said no. Brief-1 explicitly: "adding a field (even read-only True) risks future developers treating it as configurable." Brief-2 elaborated: "no env var escape hatch exists for urllib; adding ARXMCP_VERIFY_TLS creates false-positive risk." **Decision: omit the field; document the safe-by-default stance instead.**

2. **CA-pinning flag — implement now, or document only?** Brief-1 leaned toward implementing the Config field architecture but deferring the CN frozenset values to live cert inspection. Brief-2 agreed: "Implement the Config field + documentation. Defer the actual CN validation to implementation phase." **Decision: add `pin_arxiv_ca: bool = False` to `server/config.py`. When True, log INFO that CA pinning is requested but not yet active (the implementation is a stub gated by a follow-up roadmap entry). Document explicitly in the audit doc that the flag is forward-compatible plumbing.**

3. **Cap scope — which modules get the 100 MB umbrella?** Brief-1 said ar5iv + oai_delta. Brief-2 added "graph_ingest, inspire_ingest, arxiv_fetch as well." **Decision:**
   - `ingest/ar5iv_fetch.py` + `ingest/oai_delta.py`: **MUST** get the 100 MB cap (currently unbounded).
   - `tools/arxiv_fetch.py`: already has 200 MB cap; lower it to 100 MB to match Threat 7 ("a single paper > 100 MB source is suspicious") — the existing 200 MB was a safety-net default, not a Threat-7 budget.
   - `ingest/graph_ingest.py` + `ingest/inspire_ingest.py`: per-service caps (5 MB / 8 MB) are tighter than 100 MB and service-correct; leave them.

4. **Streaming vs read-with-cap.** Brief-2 leaned toward streaming chunk accumulation. Brief-1 leaned toward `response.read(MAX + 1)` (which buffers up to the cap+1 in memory). **Decision: use the existing pattern from `tools/arxiv_fetch.py`** — Content-Length pre-check (reject before any body read if the declared size exceeds the cap) + `response.read(MAX + 1)` (cap the actual read to bounded memory). The pattern is proven, simple, and already in the codebase. Streaming-with-accumulation is overkill for a 100 MB cap (worst-case 100 MB into memory once, then immediate reject).

---

## Failure modes (union of both briefs, deduped)

1. **Content-Length absent (chunked / HTTP/2):** server sends body without a Content-Length header. **Mitigation:** still pass `MAX + 1` to `response.read()`; the cap applies to the actual bytes read, not the declared length.

2. **Content-Length lies (declared 1 MB, sends 200 MB):** `urllib.request.urlopen.read()` reads until EOF, not until declared length. **Mitigation:** `response.read(MAX + 1)` ensures only `MAX + 1` bytes are ever buffered; the lie is irrelevant.

3. **Gzip inflation:** `Content-Encoding: gzip`, declared compressed size 1 MB, decompresses to 500 MB. **Mitigation:** urllib does NOT auto-decompress unless the caller wraps with `gzip.GzipFile`. None of our current fetch sites do that — `response.read()` returns raw (gzipped) bytes. Document this; not a current vulnerability.

4. **Chunked encoding with no zero-terminator (slow-loris):** server streams chunks indefinitely. **Mitigation:** `response.read(MAX + 1)` reads at most `MAX + 1` bytes; combined with the existing per-call `timeout=` argument (typically 5-30s), the attack window is bounded.

5. **`SSL_CERT_FILE` env-var override:** an attacker with shell access could set `SSL_CERT_FILE=/tmp/evil-ca.pem` to make urllib trust an attacker CA. **Mitigation:** out-of-scope for code-level fix (it's an operator-environment threat). Document in audit doc as a deployment-hardening note.

6. **Redirect off-domain:** server returns 301 to `attacker.internal`. **Mitigation:** ar5iv_fetch + oai_delta already validate `response.url.startswith(...)` after urlopen. graph_ingest + inspire_ingest do NOT — flag as a follow-up (document in audit doc, don't fix in this milestone).

7. **HTTPS → HTTP downgrade via 301:** urllib does NOT downgrade automatically (stdlib behavior); the new request is built from the Location header which an attacker can specify with `http://`. **Mitigation:** any redirect to a non-HTTPS URL would fail the existing host-prefix check in ar5iv + oai_delta. Document in audit.

8. **`verify=False` slipped in via copy-paste from a test fixture:** the audit's grep check catches the literal pattern. **Mitigation:** the pytest gate (described below) walks `ingest/` and `tools/`, refusing to pass if `verify=False` appears anywhere. Test fixtures under `tests/` are explicitly excluded from the walk to permit defensive tests.

---

## Implementation plan (concrete deliverables)

1. **`ingest/ar5iv_fetch.py`** — add `MAX_SOURCE_BYTES = 100 * 1024 * 1024` module-level constant. Before the existing `response.read()` at line 154:
   - Read `Content-Length` header; if present and `int(content_length) > MAX_SOURCE_BYTES`, raise `Ar5ivOversizedError` (a new exception or `RuntimeError` if too lightweight) AND log a warning, BEFORE consuming the body.
   - Replace `body_bytes = response.read()` with `body_bytes = response.read(MAX_SOURCE_BYTES + 1)` and raise if `len(body_bytes) > MAX_SOURCE_BYTES` (catches lying Content-Length / missing header).

2. **`ingest/oai_delta.py`** — same pattern as ar5iv_fetch:
   - Add `MAX_OAI_RESPONSE_BYTES = 100 * 1024 * 1024` module-level constant.
   - Pre-check Content-Length, reject early on overage.
   - Replace `body = response.read()` at line 329 with capped read.

3. **`tools/arxiv_fetch.py`** — lower `MAX_RESPONSE_BYTES` from `200 * 1024 * 1024` to `100 * 1024 * 1024` per Threat 7 budget. Update the docstring comment that cites the old value.

4. **`server/config.py`** — add a single new Config field for the CA-pinning forward-compatible flag:
   ```python
   pin_arxiv_ca: bool = Field(default=False, description="...")
   ```
   No env var validation needed — Pydantic handles it. The field is read but not yet acted upon (the actual CN frozenset and SSL context setup is deferred to a follow-up). On server startup, if the flag is True, log an INFO line: `"ARXMCP_PIN_ARXIV_CA=1 set but pinning is not yet active; defer to E13_S07b"` (a forward-compat stub).

5. **`tests/security/test_source_ingest.py`** — new test file mirroring the E13_S05 layout. Three test classes:
   - `TestNoVerifyFalse` — walks `ingest/**/*.py` and `tools/**/*.py`, asserts no `verify=False` regex match. Excludes `tests/` (test fixtures may exercise this defensively).
   - `TestContentLengthCap` — three test cases:
     a. `Content-Length: 209715200` (200 MB) → monkey-patched urlopen returns headers but no body; assert `Ar5ivOversizedError` (or equivalent) raised before any `.read()`.
     b. `Content-Length` missing, body is 100 MB + 1 bytes → assert capped read raises (lying / missing header attack).
     c. Body < 100 MB → assert no raise; fetch succeeds.
   - `TestTlsCannotBeDisabled` — assert no `ARXMCP_*` env var disables TLS verification. The test instantiates `Config(_env_file=None)` with a hypothetical `ARXMCP_VERIFY_TLS=0` set in os.environ and confirms the field does not exist on the Config object (pydantic `extra="forbid"` will reject it).

6. **`.claude/docs/security-threat-7-audit.md`** — audit doc with:
   - Threat 7 verbatim from threat model.
   - Compliance matrix per fetch site (ar5iv / oai_delta / arxiv_fetch / graph_ingest / inspire_ingest).
   - urllib.request safe-by-default stance + RFC 9110 § 8.6 citation.
   - Content-Length semantics (declared can lie, can be absent; cap on actual read is the load-bearing guard).
   - CA-pinning approach: `ARXMCP_PIN_ARXIV_CA` opt-in, forward-compat (stub today; full implementation deferred).
   - Known gaps: graph_ingest + inspire_ingest do NOT validate redirect hosts; logged here for follow-up. `SSL_CERT_FILE` env override is an operator threat, not a code threat.
   - Operator runbook: how to check the audit (`make test` runs the pytest gate; optional `make verify-no-verify-false` target for an explicit pre-push check).

7. **`Makefile`** — optional `verify-no-verify-false` target that runs the same grep check as a developer convenience. Documented but not required by `make test` (the pytest gate is the authoritative check).

---

## Acceptance-criteria mapping

| AC (verbatim) | Status / how met |
|---|---|
| `pytest tests/security/test_source_ingest.py` passes all 3 cases | ✓ — file created with 3+ tests; runs as part of `make test` |
| TLS verification cannot be disabled via any `ARXMCP_*` env var | ✓ — `TestTlsCannotBeDisabled` asserts pydantic `extra="forbid"` rejects any `ARXMCP_VERIFY_TLS` / `ARXMCP_*` field that would do this; the audit doc cites RFC 9110 § 8.6 |
| 200 MB fixture response rejected without reading > 100 MB into memory | ✓ — Content-Length pre-check rejects BEFORE `response.read()` is called when declared size > 100 MB; `read(MAX+1)` caps the actual buffer when Content-Length is missing/lying |
| All HTTP clients in `ingest/sources/` use the shared client; grep CI check | ✗ **reframed** — no `ingest/sources/` directory exists; no `httpx` clients exist. The functional equivalent: `TestNoVerifyFalse` walks `ingest/` + `tools/` for the `verify=False` pattern and refuses any future regression. Documented in audit doc |
| `ARXMCP_PIN_ARXIV_CA` flag (opt-in) documented in audit doc | ✓ — Config field added (stub); audit doc explains the opt-in semantics and the deferred cert-inspection step |

---

## Open questions (deferred to implementer)

1. **Exception class for size-cap violations.** Use the existing `urllib.error.HTTPError`-like pattern (raise a custom `Ar5ivOversizedError` / `OaiOversizedError`) OR a generic `RuntimeError`? The graph_ingest + inspire_ingest precedent uses generic `RuntimeError(...)`. Recommend the same for parity unless the callers need to distinguish (they don't today).

2. **Should the `verify=False` walk also cover `server/`?** The brief restricts it to `ingest/`. But a future server-side HTTP client (telemetry exporter, etc.) could also leak. Recommend walking BOTH `ingest/` and `tools/` AND `server/` to be safe; test fixtures under `tests/` remain excluded.

3. **`ARXMCP_PIN_ARXIV_CA` — stub or full implementation?** Synthesis decision: stub (Config field present, startup log on opt-in, no actual SSL context manipulation). Full implementation requires live cert inspection and a documented refresh procedure; defer to a follow-up entry.

---

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| Git commit (feat) | local main | Implementation commit |
| Git commit (rect) | local main | Rectifier commit closing critic findings |
| Git commit (chore) | local main | Finalize state.json |

**No `git push`, no PR, no infra apply, no third-party API write. Purely local.**

---

## Orchestrator synthesis note

Both briefs converged on the same diagnosis: the brief is doubly-drifted (no `ingest/sources/` exists; E11_S02 didn't ship the cap), so this milestone is **gap-closure + audit**, not just audit. The synthesis resolves four brief/repo conflicts and adds two specific reframings (CI → pytest gate; refactor-to-httpx → status quo with caps). The CA-pinning flag is added as forward-compatible plumbing rather than a full implementation because live cert inspection is out of researcher scope. The 100 MB cap from `tools/arxiv_fetch.py:MAX_RESPONSE_BYTES` is being TIGHTENED from 200 MB → 100 MB to align with Threat 7's "single paper > 100 MB source is suspicious" budget.
