# Implementation summary — E13_S07

**Milestone:** E13_S07 — Threat-7 audit: source ingestion TLS pinning + content-length enforcement
**Implementation base SHA:** `5b0b9bd6fe420f20ce6a60ee91dad62e94e0994c`
**Path:** inline (orchestrator implemented directly in main session)

## One-line summary

Closed Threat 7 (source ingestion supply chain) by adding the missing 100 MB
content-length cap to `ingest/ar5iv_fetch.py` + `ingest/oai_delta.py` (the
two unbounded HTTP paths), tightening `tools/arxiv_fetch.py`'s pre-existing
cap from 200 → 100 MB to match the threat-model budget, adding the opt-in
`ARXMCP_PIN_ARXIV_CA` Config flag (forward-compat stub), and pinning the
TLS-cannot-be-disabled posture with a pytest gate that walks production
code for any `verify=False` / unsafe-SSLContext regression.

## Files changed

| File | Change | Why |
|---|---|---|
| `ingest/ar5iv_fetch.py` | MODIFIED | Add `AR5IV_MAX_RESPONSE_BYTES = 100 MB`, Content-Length pre-check, read-cap; two new `Ar5ivResult.reason` values (`oversized_content_length`, `oversized_body`) |
| `ingest/oai_delta.py` | MODIFIED | Add `OAI_PMH_MAX_RESPONSE_BYTES = 100 MB`, Content-Length pre-check, read-cap; raises `RuntimeError` on cap breach |
| `tools/arxiv_fetch.py` | MODIFIED | Tighten `MAX_RESPONSE_BYTES` from 200 MB → 100 MB; updated comment to cite Threat 7 budget |
| `server/config.py` | MODIFIED | Add `pin_arxiv_ca: bool = False` (opt-in CA pinning forward-compat stub) |
| `tests/security/test_source_ingest.py` | NEW | 12 tests across 4 classes: `TestTlsCannotBeDisabled`, `TestContentLengthCap`, `TestNoVerifyFalse`, `TestPinArxivCaFlag` |
| `tests/test_ar5iv_fetch.py` | MODIFIED | Extend `_FakeResponse` with `headers` attribute and `read(amt)` capped-read shape to match new production contract |
| `tests/test_oai_delta.py` | MODIFIED | Extend `_FakeUrlOpenResponse` with `headers` + `read(amt)` same as above |
| `.claude/docs/security-threat-7-audit.md` | NEW | Audit doc: compliance matrix, TLS safe-by-default + cannot-be-disabled rationale, Content-Length semantics, CA-pinning approach, deviations from brief, operator runbook |

## Acceptance criteria status

| AC | Status | Evidence |
|---|---|---|
| `pytest tests/security/test_source_ingest.py` passes all cases | ✅ | 12 tests pass |
| TLS verification cannot be disabled via any `ARXMCP_*` env var | ✅ | `TestTlsCannotBeDisabled` (3 tests): no Config field exists for TLS toggling, env-var has no effect on Config attributes, no insecure SSLContext anywhere in `ingest/` `tools/` `server/` |
| 200 MB fixture response rejected without reading > 100 MB into memory | ✅ | `TestContentLengthCap::test_ar5iv_rejects_oversized_content_length_before_read` patches `response.read` with an `AssertionError` side-effect so any invocation fails the test; `_fetch_page` equivalent for oai_delta |
| All HTTP clients in `ingest/sources/` use the shared client; grep CI check | ⚠️ **reframed** — `ingest/sources/` doesn't exist; codebase uses `urllib.request` not `httpx`. Replaced with `TestNoVerifyFalse` pytest gate that walks `ingest/`, `tools/`, `server/` for any `verify=False` regression. CLAUDE.md §4.1 forbids CI gating |
| `ARXMCP_PIN_ARXIV_CA` flag (opt-in) documented in audit doc | ✅ | Config field added (stub); `TestPinArxivCaFlag` (3 tests: default-False, env opt-in, doc references the flag verbatim) |

## Brief deviations (all resolved by orchestrator synthesis)

1. **`docs/security/threat-7-audit.md` → `.claude/docs/security-threat-7-audit.md`** — CLAUDE.md §1: `docs/` is operator-only (today: only `docs/install.md`). All E13_S01–S06 audit docs landed under `.claude/docs/`; this milestone follows that precedent.
2. **"CI lint rule" → pytest gate** — CLAUDE.md §4.1: no CI gating. The `TestNoVerifyFalse` walks `ingest/` + `tools/` + `server/` for the pattern as part of `make test`.
3. **"single shared httpx.Client at module import time" + `ingest/sources/`** — no refactor. The codebase uses `urllib.request` everywhere; no `httpx` clients exist; no `ingest/sources/` directory exists. Refactoring would be large-scope work with zero security benefit. The audit instead enforces the equivalent contract (no `verify=False` regression).
4. **"E11_S02 already enforces the 100 MB cap"** — FALSE. E11_S02 did not ship this cap. This milestone CLOSES THE GAP at the two unbounded paths.
5. **`tools/arxiv_fetch.py` cap value** — tightened from 200 MB safety-net to 100 MB Threat-7 budget for parity with the two newly-capped paths.
6. **CA pinning** — only the Config field + audit doc lands today. Actual `ssl.SSLContext.load_verify_locations(...)` against a hardcoded arxiv.org CA bundle is deferred to a follow-up because live cert inspection + an operator-refresh procedure are out of researcher scope and the rotation cadence makes a fixed pin operationally toilsome at Tier-5.

## Tests

- **New test file:** `tests/security/test_source_ingest.py` (12 tests, all passing)
- **Test classes:**
  - `TestTlsCannotBeDisabled` (3 tests) — no field for TLS toggle, env var has no effect, no insecure SSLContext anywhere
  - `TestContentLengthCap` (5 tests) — ar5iv pre-check rejects 200 MB before read, ar5iv read-cap catches missing-header attack, ar5iv accepts under-cap body (happy path), oai_delta pre-check rejects 200 MB before read, oai_delta read-cap catches lying header
  - `TestNoVerifyFalse` (1 test) — walks all production code refusing `verify=False`
  - `TestPinArxivCaFlag` (3 tests) — default False, env opt-in, audit doc documents the flag
- **Existing tests adjusted:** `tests/test_ar5iv_fetch.py::_FakeResponse` and `tests/test_oai_delta.py::_FakeUrlOpenResponse` extended with `headers` attribute and capped `read(amt)` to match the new production contract. All existing happy-path tests in those files still pass.

## Project-check status

- `ruff check .` → clean
- `pytest tests/security/test_source_ingest.py` → 12 passed
- `pytest tests/test_ar5iv_fetch.py tests/test_arxiv_fetch.py tests/test_oai_delta.py` → all pass except 1 pre-existing Windows-platform failure (`test_budget_breach_emits_sentinel`, present BEFORE this milestone)
- Full `pytest` → 30 pre-existing Windows-platform failures, identical to the baseline before E13_S07 (POSIX shell scripts, `os.getpgid`, colons-in-filenames, symlink tests). **My changes add 12 new passing tests and introduce zero new failures.**

## External writes required

None. Optional follow-up (NOT a write the orchestrator performs): an
operator who wants to use the forward-compat CA-pin flag would set
`ARXMCP_PIN_ARXIV_CA=1` — the flag plumbing is in place, the active SSL
context manipulation is deferred to a future milestone.

## Anything notable for the critic

1. **The audit `TestTlsCannotBeDisabled::test_arxmcp_verify_tls_env_var_has_no_effect` was REWRITTEN at implementation time.** The original framing asserted that `ARXMCP_VERIFY_TLS=0` would raise `ValidationError` via Config's `extra="forbid"`. That turned out to be wrong: `extra="forbid"` applies to constructor kwargs, not env-var inputs. Pydantic-settings silently ignores unknown env vars by default. The corrected security guarantee — and the test — is that no Config attribute is bound from such a var, so no code path can read it to disable TLS. The audit doc was updated in lockstep.

2. **`tools/arxiv_fetch.py` cap was tightened, not just left at 200 MB.** The 200 MB value was a pre-E11 safety-net default; Threat 7 explicitly cites 100 MB as the "suspicious" threshold. This is a behavior change for callers that download exactly-between-100-and-200-MB arXiv source tarballs — those are now rejected. Justified by the threat model; documented in the audit doc.

3. **`ARXMCP_PIN_ARXIV_CA` is a forward-compat STUB.** The Config field exists and tests cover its on/off semantics, but no code actually consumes the flag yet. A future milestone must wire the SSL context. The audit doc is explicit about this and lists the closure plan.

4. **The `_FakeResponse` / `_FakeUrlOpenResponse` extensions** keep the existing happy-path tests green by defaulting `content_length=None` (header absent) and capping `read(amt)` to the body's actual length. No existing test had to be rewritten — the new attrs are additive.

5. **No new external dependencies.** No `httpx`, no `requests`, no `certifi` — stays on stdlib `urllib.request` per the synthesis.

6. **No-fork policy compliance.** Nothing copied from arxiv-mcp / huggingface OSS. The cap-with-pre-check + cap-with-read pattern follows the existing `tools/arxiv_fetch.py` precedent (E01).
