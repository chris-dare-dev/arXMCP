# Research Synthesis — textbook-ingest-m10

**Orchestrator merge of research-brief-1 + research-brief-2.**
**Generated:** 2026-05-28

## Headline: the milestone's premise is wrong — the carve-out already shipped in m4

Both researchers, independently, flagged the SAME critical drift: the brief's
stated "un-built piece" (the 200 MB textbook upload-cap carve-out) is **already
fully implemented, tested, and documented** — it landed in `textbook-ingest-m4`
(state `complete`). My brief's grep missed it because the cap is wired in
`server/main.py` via `prefix_caps`, not in `server/middleware.py` directly, and
the middleware class is `RequestBodySizeLimitMiddleware` (not the assumed
"BodySizeCap" name).

**Verbatim evidence (both briefs agree):**

`server/main.py:523-549`:
```python
# textbook-ingest-m4: cap raised from 10 MB to 200 MB to allow
# textbook PDF uploads on notebook_kind="textbook" notebooks ...
# The 10 MB enforcement for arxiv-kind notebooks is preserved at
# the ROUTE HANDLER level ...
app.add_middleware(
    RequestBodySizeLimitMiddleware,
    prefix_caps={
        "/ui/api/notebooks": 200 * 1024 * 1024,  # 200 MB envelope; per-kind enforced in handler
    },
)
```

`server/routes/notebooks.py:540` → `_ARXIV_UPLOAD_MAX_BYTES = 10 * 1024 * 1024`.
`server/routes/notebooks.py:820-834` → handler-side per-kind 413 for arxiv >10 MB.

**The central design tension was resolved by m4 via Option (b)** (200 MB
middleware ceiling + 10 MB handler-side arxiv check), with the DoS regression
(a 200 MB body to an arxiv notebook IS buffered via `await file.read()` before
the 413 fires) EXPLICITLY documented and accepted under the loopback-only
deployment model (`server/main.py:532-545`, `config.py::reject_non_loopback`).

## What m10 actually is: doc-accuracy pass + one test-gap closure

### A. Doc-accuracy fixes to `.claude/docs/security-pdf-sandbox.md` (the 486-line threat doc)

Both briefs found the doc ALREADY documents the 200 MB carve-out + the
memory-pressure caveat (lines ~262-274), but with these accuracy gaps:

1. **JS-detection function signature is wrong** (brief-1, ~line 226). The doc's
   pre-flight snippet shows `def _pdf_has_javascript(pdf_path: Path)`. The actual
   code imports `from tools.security.pdfid import find_javascript as
   _pdf_find_javascript` (`server/routes/notebooks.py:66`) and calls it with
   `content: bytes`. The real signature is
   `def find_javascript(pdf_bytes: bytes) -> list[str]` (`tools/security/pdfid.py:102`).
2. **Stale future-tense header** (brief-1, ~line 378): "Failure modes covered by
   tests (e2 will land these)" — e2 shipped in m4/m5. Fix to past tense.
3. **Stale baseline attribution** (brief-2, ~line 62): the 1 MB→10 MB raise was
   m8; the 10 MB→200 MB textbook envelope was m4. The doc conflates them.
4. **Optional**: annotate/add an explicit "Upload cap carve-out (m4)" section
   stating (a) 200 MB middleware envelope for `/ui/api/notebooks`, (b) handler-side
   10 MB arxiv cap after `await file.read()`, (c) the accepted DoS caveat, (d) code
   anchors (`server/main.py::prefix_caps` + `notebooks.py::_ARXIV_UPLOAD_MAX_BYTES`),
   (e) cross-reference the m4 tests.
5. **Low priority** (brief-1): stale module-level comment in
   `tests/security/test_request_body_prefix_caps.py` (or wherever the prefix-cap
   tests live) saying "m8 carve-out raises it to 10 MB" — the fixture is decoupled
   from production so this is cosmetic.

### B. The one possible code deliverable (resolve OQ-1 first)

The AC asks for "malformed/missing content-length edge cases" tests. Both briefs
agree the `RequestBodySizeLimitMiddleware` ALREADY enforces this correctly:
- **Content-Length declared > cap** → 413 immediately, body never pumped
  (`server/middleware.py:897-954`).
- **No/after-header path** → eager pre-read counting `body_seen`; 413 when
  actual streamed bytes exceed cap (`middleware.py:965-1007`). So a header that
  under-declares (says 5 MB, sends 200 MB) is caught by the streamed-byte counter.
- **Malformed/negative Content-Length** → 400 (`middleware.py:900-935`).

brief-1 says these are covered by unit tests in `tests/test_body_size_cap.py` /
`tests/security/test_request_body_prefix_caps.py` but NOT in
`tests/test_pdf_preflight.py` scoped to the notebooks upload path. **OQ-1**: confirm
whether a malformed/missing-Content-Length test exists for the notebooks upload
PATH specifically; if not, add a small one (same pattern as the existing prefix-cap
middleware tests, scoped to `/ui/api/notebooks`).

### Already-covered ACs (do NOT re-implement)
- arxiv >10 MB → 413, textbook >10 MB accepted: `tests/test_pdf_preflight.py::TestUploadCapPerKind` (~lines 344-398).
- 200 MB middleware envelope present: `TestMiddlewareEnvelope` (~lines 619-664).
- notebook-kind resolution / DB-call ordering: `TestDbCallOrdering` (~lines 667+).

## Constraints (confirmed by both briefs)
- **No MCP tool-schema surface change.** The upload route is `/ui/api/notebooks/*`,
  not `/mcp`. NO `EXPECTED_TOOL_SCHEMA_SHA256` / `EXPECTED_BP1_SHA256` re-pin.
- **Pure-ASGI already satisfied** — `RequestBodySizeLimitMiddleware` is a pure-ASGI
  `__call__(scope, receive, send)` class; no `BaseHTTPMiddleware`.
- **No code changes** to `server/main.py` or `server/routes/notebooks.py` (the
  feature is built). Doc + possibly one test only.
- Design notes applying: `06-mcp-server-design.md` (middleware stack ordering),
  `08-security-observability-ops.md` (Threat 4 resource-exhaustion),
  `07-multi-agent-caching.md` (confirms no BP1 impact).

## Orchestrator synthesis note (divergence resolution)
**No material divergence.** Both briefs reached the identical conclusion
(carve-out built in m4; m10 = doc pass + possible test-gap closure) from
different entry points (brief-1 in-codebase-first, brief-2 ASGI/failure-mode-first).
This strong independent agreement raises confidence that the implementer must NOT
re-implement the carve-out. The implementation is an **honest-descope** milestone
(precedent: textbook-ingest-m8): ship the doc-accuracy pass + close the one genuine
test gap, and record that the feature was already built in m4.

## Open questions
- **OQ-1 (must resolve before deciding on the test deliverable):** Does a
  malformed/missing-Content-Length test exist for the `/ui/api/notebooks` upload
  PATH specifically (vs only the generic middleware unit test)? If yes → pure doc
  pass. If no → add one small scoped test. The implementer resolves this by reading
  `tests/test_pdf_preflight.py` + `tests/security/test_request_body_prefix_caps.py`
  + `tests/test_body_size_cap.py` (whichever exist).

## External writes the implementation will require
None — purely local (doc update + possibly one test). All commits land on `main`.
