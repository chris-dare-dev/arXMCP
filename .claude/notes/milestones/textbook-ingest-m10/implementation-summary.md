# Implementation Summary — textbook-ingest-m10 (e5 part 1 of 2)

**Summary:** An HONEST-DESCOPE milestone. The 200 MB textbook upload-cap carve-out the brief asked for was already built, tested, and documented in `textbook-ingest-m4` (200 MB middleware envelope in `server/main.py::prefix_caps` + handler-side 10 MB arxiv cap in `server/routes/notebooks.py`). m10 therefore ships a **doc-accuracy pass** on `.claude/docs/security-pdf-sandbox.md` plus **one test-gap closure** (malformed/negative Content-Length on the upload path). NO production code changed.

**Commit range:** `ca95ccb..HEAD` (single feat commit + this summary).

## Acceptance criteria status

| AC | Status | Evidence |
|---|---|---|
| textbook >10MB & ≤200MB accepted; arxiv >10MB → 413 | ✅ ALREADY MET (m4) | `tests/test_pdf_preflight.py::TestUploadCapPerKind` (`test_arxiv_body_over_cap_rejected_413`, `test_textbook_body_over_arxiv_cap_accepted`). Not re-implemented. |
| >200MB → 413 even for textbook | ✅ ALREADY MET (m4) | `TestMiddlewareEnvelope::test_middleware_envelope_is_200_mb` pins `prefix_caps["/ui/api/notebooks"] == 200 MB`. |
| Preserves DoS protection (no 200MB buffer for arxiv) | ✅ ALREADY MET (m4, accepted caveat) | The 200MB body IS buffered before the arxiv 413 (`await file.read()`); documented + accepted under loopback-only in `server/main.py:532-545` and the threat doc §"Caps enforced". This is the m4 rect-F1 accepted gap, NOT a regression introduced here. |
| Pure-ASGI; no assert; local-first; no anthropic SDK | ✅ | `RequestBodySizeLimitMiddleware` is pure-ASGI (already shipped). No production code changed; the new test uses `if`-free asserts in pytest context (allowed in tests). |
| No tool-schema / BP1 re-pin | ✅ | Upload route is `/ui/api/notebooks/*`, not `/mcp`. No `ALL_TOOLS`/schema touch. Confirmed by both researchers. |
| `security-pdf-sandbox.md` updated + pdfid/polyglot refs match code | ✅ | Three doc fixes (below). |
| Tests: textbook/arxiv/200MB/kind-resolution + malformed/missing C-L | ✅ | First four already covered (m4); the malformed/negative C-L on the upload PATH was the genuine gap — closed by `TestUploadPathContentLengthGuards`. |

## What changed

### Doc-accuracy pass — `.claude/docs/security-pdf-sandbox.md`
1. **JS-detection snippet corrected.** The doc showed `_pdf_has_javascript(pdf_path: Path) -> bool`; the actual code is `find_javascript(pdf_bytes: bytes) -> list[str]` (`tools/security/pdfid.py:102`), imported as `_pdf_find_javascript` and called with raw `content: bytes` in `_run_pdf_preflight` (`server/routes/notebooks.py:66,652,682`). Snippet rewritten to match the real signature + truthiness-check usage.
2. **Cap attribution untangled** (resource-exhaustion threat row). The muddled "(raised from the 10 MB m8 cap; see m6 ar5iv upload route)" is now an accurate two-tier description: 200 MB middleware envelope (m4, from the m8 1→10 MB baseline) + handler-side 10 MB arxiv cap, cross-referencing the §"Caps enforced before MinerU is invoked" section.
3. **Stale future-tense header fixed.** "## Failure modes covered by tests (e2 will land these)" → "(shipped in textbook-ingest-m4/m5)", with an accurate pointer to `tests/test_pdf_preflight.py` + the `requires_mineru` marker (shipped m5, pyproject.toml).

### Test-gap closure — `tests/test_pdf_preflight.py`
- New `TestUploadPathContentLengthGuards` (2 tests): posts a malformed (`"not-an-integer"`) and a negative (`"-100"`) Content-Length to `/ui/api/notebooks/*/papers/upload` against an app that mounts `RequestBodySizeLimitMiddleware` with the production 200 MB prefix carve-out; asserts 400 + `malformed_content_length`. Proves the carve-out path still inherits the middleware's smuggling-signal guard (the bare `client` fixture has no middleware, so its 413s come from the handler — this class adds the middleware explicitly). The same guard on `/healthz` is in `tests/test_security.py`.

## Files changed
- `.claude/docs/security-pdf-sandbox.md` (3 doc-accuracy fixes)
- `tests/test_pdf_preflight.py` (new `TestUploadPathContentLengthGuards`)

## External writes required
None — purely local.

## Deviation from the brief
The brief framed m10 as building the upload-cap carve-out. Both researchers (independently) found it was already shipped in m4. Per the synthesis, the implementer did NOT re-implement it — m10 reduced to the doc-accuracy pass + the one genuine test gap. This is the same honest-descope posture as textbook-ingest-m8.
