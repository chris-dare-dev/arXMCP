# Research Brief — textbook-ingest-m10

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-28T17:30:00Z

## In-codebase context

### CRITICAL FINDING: Upload-size carve-out is already fully implemented

**The central design tension in the milestone brief is already resolved.** The 200 MB
middleware envelope + 10 MB per-kind handler check both shipped in **textbook-ingest-m4**
(state: `complete`, rectification commit `800cc0b1b913ed71bfbc1c65d77341bcffc51c88`).

Verbatim from `server/main.py:546-550`:
```python
app.add_middleware(
    RequestBodySizeLimitMiddleware,
    prefix_caps={
        "/ui/api/notebooks": 200 * 1024 * 1024,  # 200 MB envelope; per-kind enforced in handler
    },
)
```
Comment at `server/main.py:523-531`:
> "textbook-ingest-m4: cap raised from 10 MB to 200 MB to allow textbook PDF uploads on
> notebook_kind="textbook" notebooks (Bourbaki / Hartshorne / Griffiths-Harris all fit
> comfortably under 200 MB). The 10 MB enforcement for arxiv-kind notebooks is preserved
> at the ROUTE HANDLER level — the upload handler in server/routes/notebooks.py reads
> notebook_kind from the SQLite store (m3) and rejects 413 if the body exceeds 10 MB on
> an arxiv-kind notebook."

Handler check at `server/routes/notebooks.py:820-834`:
```python
# textbook-ingest-m4 D3: per-kind upload-cap enforcement.
if not is_textbook and len(content) > _ARXIV_UPLOAD_MAX_BYTES:
    raise HTTPException(
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        detail=(
            f"upload of {len(content)} bytes exceeds the "
            f"{_ARXIV_UPLOAD_MAX_BYTES}-byte cap for arxiv-kind "
            f"notebooks (textbook-kind notebooks accept up to "
            f"200 MB; raise this notebook's kind to 'textbook' "
            f"if you intend to upload PDFs)"
        ),
    )
```

`_ARXIV_UPLOAD_MAX_BYTES = 10 * 1024 * 1024  # 10 MB` at `server/routes/notebooks.py:540`.

### Memory-pressure caveat is documented in the code

`server/main.py:532-545` acknowledges the DoS regression verbatim:
> "Memory-pressure caveat (m4 rect F1). The route handler reads the full body via
> `await file.read()` BEFORE the per-kind cap fires — see `server/routes/notebooks.py`
> upload-paper flow. So a 200 MB body uploaded to an arxiv-kind notebook IS buffered
> fully in memory before the handler returns 413. This is acceptable under the
> loopback-only deployment model (CLAUDE.md 'Must run locally in Docker'; server binds
> to 127.0.0.1 per `server/config.py::reject_non_loopback`) but is a memory-pressure
> regression vs the pre-m4 10 MB middleware envelope."

### Tests already cover all the ACs

`tests/test_pdf_preflight.py`:
- `TestUploadCapPerKind` — arxiv >10 MB rejected 413, textbook >10 MB accepted,
  tests at lines 344-400.
- `TestMiddlewareEnvelope` — asserts `prefix_caps["/ui/api/notebooks"] == 200*1024*1024`
  by inspecting the live middleware stack, lines 619-664.
- `TestDbCallOrdering` — notebook_kind resolution path (get_notebook before paper_id
  validation), lines 667+.
- Missing content-length edge cases ARE covered by `RequestBodySizeLimitMiddleware`
  unit tests in `tests/test_body_size_cap.py` (malformed C-L → 400, negative C-L → 400)
  but NOT in `test_pdf_preflight.py`. The AC text says "tests the implementer should add"
  — these edge-case tests need to be added.

### Design notes that apply

- `06-mcp-server-design.md` — server architecture; middleware stack ordering
  (SecurityHeaders → … → RequestBodySizeLimitMiddleware → BodySizeCapMiddleware → handler).
- `07-multi-agent-caching.md` — no tool-schema change, no BP1 re-pin needed.
- `08-security-observability-ops.md` — Threat 4 (resource exhaustion via tool args);
  the upload cap is one of the mitigations under the broader DoS threat surface.

### Doc accuracy gaps in `.claude/docs/security-pdf-sandbox.md`

**The doc already documents the 200 MB carve-out** (lines 262-274) and the
memory-pressure caveat. However two accuracy gaps exist:

1. **Function signature mismatch** (line 226). The doc's "Pre-flight gate" code snippet
   shows `def _pdf_has_javascript(pdf_path: Path)` (takes a Path, not bytes). The
   actual implementation is `_pdf_find_javascript` (an alias for
   `tools.security.pdfid.find_javascript`), which takes `content: bytes` — imported at
   `server/routes/notebooks.py:66`. The function name and signature in the doc are wrong.

2. **Stale future-tense section header** (line 378). "Failure modes covered by tests
   (e2 will land these)" uses future tense — e2 shipped in m4/m5. Should read
   "Failure modes covered by tests (shipped in textbook-ingest-m4/m5)".

3. **`test_request_body_prefix_caps.py` header comment is stale**. The doc comment at
   line 8 says "the m8 carve-out raises it to 10 MB only for paths under
   `/ui/api/notebooks`" — this was true at m8, but m4 raised it to 200 MB. The test
   fixtures themselves are internally consistent (they create their own 10 MB fixture)
   but the module-level comment is misleading. Low priority — the fixture is decoupled
   from production.

### Pure-ASGI constraint confirmation

`BaseHTTPMiddleware` is project-banned per E06_S01 F1 (see `agent-conventions.md §4`
and `CLAUDE.md §4.7`). The existing implementation uses `RequestBodySizeLimitMiddleware`
as a pure-ASGI class with `__call__(scope, receive, send)` — no `BaseHTTPMiddleware`.
This constraint is already satisfied.

## Prior decisions and lessons

- `textbook-ingest-m4` (complete) shipped the 200 MB envelope + per-kind handler check.
  All 8 findings from the adversary critique were fixed (F1 through F8 in
  `.claude/notes/milestones/textbook-ingest-m4/state.json`).
- The "two-tier" design (middleware ceiling = 200 MB, handler-level check = 10 MB for
  arxiv) was the resolution to the design tension the brief poses. Option (b) from the
  brief was chosen with the memory-pressure caveat explicitly documented and accepted.
- `notebook_kind` was added in m3 (`server/notebooks_store.py`) — `get_notebook(slug)`
  returns a dict including `"notebook_kind"`. The upload handler fetches the notebook
  BEFORE validating `paper_id` format because the validation rule depends on kind.
  This is the DB call ordering locked by `TestDbCallOrdering`.
- Memory ENTRY from 2026-05-22 confirms the m10 scope: "m9-scope-invariant-test-blocks-
  m10-frontend-changes — tests/test_m9_scope_invariants.py greps frontend/ for
  `iframe|preview` and fails if found. m10 adds both tokens." This is a DIFFERENT m10
  (the preview route milestone, already shipped). The textbook-ingest-m10 milestone is
  separate and is the current focus.

**No git log conflicts** — the most recent commits confirm m4 shipped the upload cap
and tests. No commits since m4 have touched `server/main.py::prefix_caps` or
`server/routes/notebooks.py::_ARXIV_UPLOAD_MAX_BYTES`.

## External sources

The MCP spec is not in scope — this milestone adds no tool-surface change. Confirmed:
no `EXPECTED_TOOL_SCHEMA_SHA256` re-pin needed (the `search_papers`/`get_chunk` etc.
tool definitions are unaffected).

ASGI spec for content-length / body streaming: the `RequestBodySizeLimitMiddleware`
(middleware.py lines 886-1020) already handles the ASGI `http.request` `more_body`
chunking correctly — it drains the receive queue before forwarding to the inner app,
so the content-length precheck fires before any body buffering when a `Content-Length`
header is present. The eager-pre-read path buffers up to `max_bytes` before rejection.
This is the mechanism that makes Option (b) acceptable under the loopback-only model.

No vendor docs are needed — the implementation is complete and the external references
are all already in the codebase.

## Recommendation

**The upload-size carve-out is already implemented.** m10 is a doc-accuracy pass only.

Concrete implementation:

1. **Fix `security-pdf-sandbox.md` §"Pre-flight gate" code snippet** (line 226).
   Replace `def _pdf_has_javascript(pdf_path: Path)` with accurate description:
   the route imports `from tools.security.pdfid import find_javascript as _pdf_find_javascript`
   and calls `_pdf_find_javascript(content)` where `content` is `bytes`.
   The function signature: `def find_javascript(pdf_bytes: bytes) -> list[str]`
   (from `tools/security/pdfid.py:102`).

2. **Update the stale future-tense section header** (line 378).
   "e2 will land these" → "shipped in textbook-ingest-m4/m5".

3. **Add missing content-length edge-case tests** to `tests/test_pdf_preflight.py`.
   The AC requires: "malformed/missing content-length edge cases the existing middleware
   already guards." These are: (a) malformed C-L header → 400, (b) missing C-L header
   with chunked body still subject to cap. These are unit-testable via
   `RequestBodySizeLimitMiddleware` directly (same pattern as
   `tests/security/test_request_body_prefix_caps.py`) but scoped to the notebooks
   upload path.

4. **No code changes needed** to `server/main.py` or `server/routes/notebooks.py`.
   No `EXPECTED_TOOL_SCHEMA_SHA256` re-pin. No `EXPECTED_BP1_SHA256` re-pin.

This is a LOW-complexity milestone: doc pass + 2-3 new tests.

## Open questions

No open questions — implementation can proceed on the above recommendation.

The central design tension (middleware envelope vs per-kind cap) was already resolved by
textbook-ingest-m4. The chosen approach is documented with its accepted trade-off (the
memory-pressure caveat). The implementer should NOT re-litigate the design; only update
the doc and add the missing tests.

## External writes the implementation will require

None — this milestone is purely local.
