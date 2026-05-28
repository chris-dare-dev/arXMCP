# Research Brief — textbook-ingest-m10

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-28T17:20:00Z

---

## In-codebase context

### **CRITICAL DRIFT FLAG: The milestone brief's stated "un-built piece" is already built.**

The brief states: "The one un-built piece of the hardening outcome is the upload-size carve-out." This is **incorrect** — the 200 MB / 10 MB per-kind split was fully implemented in textbook-ingest-m4 and survives through m9. The codebase evidence:

**`server/main.py` lines 523–549 (verbatim):**
```python
# textbook-ingest-m4: cap raised from 10 MB to 200 MB to allow
# textbook PDF uploads on notebook_kind="textbook" notebooks
# (Bourbaki / Hartshorne / Griffiths-Harris all fit comfortably
# under 200 MB). The 10 MB enforcement for arxiv-kind notebooks
# is preserved at the ROUTE HANDLER level — the upload handler
# in server/routes/notebooks.py reads notebook_kind from the
# SQLite store (m3) and rejects 413 if the body exceeds 10 MB on
# an arxiv-kind notebook.
app.add_middleware(
    RequestBodySizeLimitMiddleware,
    prefix_caps={
        "/ui/api/notebooks": 200 * 1024 * 1024,  # 200 MB envelope; per-kind enforced in handler
    },
)
```

**`server/routes/notebooks.py` lines 535–834:** `_ARXIV_UPLOAD_MAX_BYTES = 10 * 1024 * 1024` and the handler-level check `if not is_textbook and len(content) > _ARXIV_UPLOAD_MAX_BYTES: raise HTTPException(413, ...)`.

**`tests/test_pdf_preflight.py`** class `TestUploadCapPerKind` (lines 344–398): Tests cover arxiv-at-cap accepted, arxiv-over-cap rejected 413, textbook-over-arxiv-cap accepted. Class `TestMiddlewareEnvelope` (lines 619–664): Asserts the middleware prefix_caps value equals 200 MB.

**Consequently, m10's ONLY remaining deliverable is the doc accuracy pass on `.claude/docs/security-pdf-sandbox.md`.** All code, tests, and middleware changes described in the brief's acceptance criteria are already shipped.

### ASGI body-handling: how `RequestBodySizeLimitMiddleware` works

The middleware is at `server/middleware.py::RequestBodySizeLimitMiddleware` (line 806). Its `__call__` is pure-ASGI (no `BaseHTTPMiddleware`). Two enforcement paths:

**Path 1 — Content-Length header declared (lines 897–954):** Reads `scope["headers"]` for `content-length`. If declared > `max_bytes`, sends 413 JSON error **immediately**, before any `receive()` call pumps body bytes. The ASGI `receive()` channel is never touched in this path.

**Path 2 — No Content-Length or after header check passes (lines 965–1007):** Eager pre-read. The middleware drains the `receive()` channel in a loop, counting `body_seen += len(chunk)`. If `body_seen > max_bytes`, sends 413. The `more_body` flag (ASGI body streaming signal) controls loop exit: the loop continues while `event.get("more_body", False)` is True, exits on the last chunk. **This means for chunked/no-Content-Length uploads, the middleware buffers all body bytes before deciding.** For an arxiv notebook sending a 200 MB body with no Content-Length header, the full 200 MB is buffered before rejection.

**Content-Length cap vs. actual streaming bytes:** The middleware enforces BOTH:
- Content-Length precheck (header lies trigger no buffering, but a lie in the OTHER direction — declares 5 MB, sends 200 MB — is caught by the streaming byte counter). So a content-length lie that under-declares is caught by the streaming cap when the actual bytes exceed the cap.
- Malformed Content-Length (non-integer, negative) returns 400 (not 413), guarded at lines 900–935.

**The per-kind (arxiv vs textbook) cap is enforced handler-side, not middleware-side.** The middleware prefix_caps for `/ui/api/notebooks` is 200 MB unconditionally. The route handler reads `notebook_kind` from SQLite after `await file.read()` and rejects 413 for arxiv notebooks over 10 MB. This means a 200 MB body to an arxiv notebook IS buffered before rejection — the DoS regression the brief describes as the central design tension.

**This DoS regression is documented and accepted** per `server/main.py` lines 533–545: "acceptable under the loopback-only deployment model (CLAUDE.md 'Must run locally in Docker'; server binds to 127.0.0.1 per `server/config.py::reject_non_loopback`)."

### MCP spec relevance

**The MCP 2025-06-18 spec is NOT in scope for this milestone.** The upload route is `/ui/api/notebooks/*/papers/upload`, not `/mcp`. It is a FastAPI REST route under the `notebooks_router` mounted at `/ui/api` (`server/main.py` line 552). The MCP transport surface (`/mcp`) is unaffected. No tool schema changes. No `EXPECTED_TOOL_SCHEMA_SHA256` re-pin required.

### Doc accuracy: what `.claude/docs/security-pdf-sandbox.md` currently says

The doc (486 lines) already references the 200 MB envelope in 4 places (lines 62, 262, 268, 383) and documents the memory-pressure caveat (lines 266–274). The doc uses language like "m6 ar5iv upload route" for the 10 MB baseline in one place (line 62) — this is slightly inaccurate (m8 raised it from 1 MB to 10 MB; m4 raised the textbook envelope to 200 MB).

The doc has one outstanding section: **"Outstanding follow-up (out of m5 scope)"** (lines 479–486) which mentions a Lean REPL audit. The `server/lean_repl.py` RLIMIT_AS guard issue (`sys.platform != "win32"` instead of `sys.platform == "linux"`) is NOT closed — it is still a latent bug per `chris-dare-dev/arXMCP`. This is out of m10 scope per the brief.

---

## Prior decisions and lessons

- **textbook-ingest-m4 (complete):** Shipped the 200 MB middleware envelope + 10 MB handler-level enforcement. Rect F1 acknowledged the DoS regression (200 MB buffered before arxiv-kind rejection). The accepted gap is explicitly loopback-only deployment.
- **textbook-ingest-m5 (complete):** Shipped MinerU subprocess sandbox. `security-pdf-sandbox.md` was finalized with the e2 implementer's contract per m5.
- **MEMORY item `m10 — ar5iv-html-storage-TWO-paths-search-order`:** Preview route path lookup uses `flat_paper_id = paper_id.replace("/", "_")`. Relevant only if m10 touches preview — it doesn't (preview is m10 of the notebook-retrieval series, not textbook-ingest).
- **MEMORY item `m10 — m9-scope-invariant-test-blocks-m10-frontend-changes`:** `tests/test_m9_scope_invariants.py` was noted as potentially blocking m10 frontend changes. **Confirmed non-existent** in the current repo (`ls` returned NOT FOUND). Not a concern.
- **Git log:** m4 commit is at SHA in log history, complete state confirmed. m9 is `complete`. No adjacent m10 state prior to this pipeline run.
- **Banned patterns:** No code changes required for m10, so `assert`-for-invariants and `BaseHTTPMiddleware` risks are not live for this milestone. The doc pass cannot introduce banned patterns.

---

## External sources

The MCP 2025-06-18 specification is **not in scope** for this milestone — the upload route is a standalone REST endpoint, not part of the `/mcp` transport surface. No vendor docs needed.

The Anthropic prompt-caching docs are not in scope — no tool schema changes, no BP1/BP2 impact.

The ASGI spec (https://asgi.readthedocs.io) is relevant for confirming `more_body` semantics. The codebase implementation is already correct and tested; no external source needed beyond confirming the already-read code.

---

## Failure-mode analysis

**FM-1 — 200 MB body sent to an arxiv-kind notebook is buffered before rejection (DoS regression — the headline risk).**
- Trigger: client sends a multipart/form-data POST with a 200 MB body to `/ui/api/notebooks/arxiv-nb/papers/upload`.
- Symptom: server allocates ~200 MB heap before `len(content) > _ARXIV_UPLOAD_MAX_BYTES` fires and returns 413. On repeated requests, OOM is possible.
- Mitigation (accepted): loopback-only deployment (`reject_non_loopback` in `config.py`). Only the operator can reach the endpoint. If the operator sends a 200 MB HTML file to an arxiv notebook intentionally, the 413 is fast on the second request. For a future networked deployment, the per-kind cap must move into the middleware via a callable that reads notebook_kind from the SQLite store.
- **Status: accepted gap, documented in `server/main.py` and `.claude/docs/security-pdf-sandbox.md`.**

**FM-2 — Content-Length header lies (declares 5 MB, sends 200 MB).**
- Trigger: client sets `Content-Length: 5242880` but streams 200 MB.
- Symptom: middleware Content-Length precheck passes (5 MB < 200 MB limit). The streaming pre-read loop then accumulates bytes; `body_seen` exceeds the cap and 413 fires before buffering completes.
- Mitigation: the streaming byte counter in `RequestBodySizeLimitMiddleware` (lines 968–1003) enforces the ACTUAL byte count independent of the declared header. **Both the declared and actual byte counts are enforced.**
- **Status: fully mitigated by the existing middleware.**

**FM-3 — Slug in the path doesn't resolve to any notebook.**
- Trigger: client sends an upload to `/ui/api/notebooks/nonexistent-slug/papers/upload`.
- Symptom: the route handler calls `store.get_notebook(slug)` (post-m4 DB-call ordering, `server/routes/notebooks.py` line ~757), receives None, and raises HTTP 404 BEFORE the per-kind cap fires. The body IS read by `await file.read()` before the DB lookup because FastAPI reads multipart form bodies during dependency resolution. **However, the 200 MB middleware envelope still applies, so a 200 MB body to a nonexistent slug is still buffered.**
- Mitigation: same loopback-only acceptance as FM-1. The DB-call ordering lock is tested in `TestDbCallOrdering` (lines 672–700 of `test_pdf_preflight.py`).
- **Default cap for nonexistent slug: 200 MB** (the middleware prefix cap applies path-first; notebook kind is never resolved). This is the correct behavior — fail-safe toward permissive cap at middleware, conservative at handler.

**FM-4 — A notebook whose kind is NULL or unknown.**
- Trigger: a notebook row exists in SQLite with `notebook_kind` missing or `NULL` (should not happen post-m3, but defensive path matters).
- Symptom: route handler at `server/routes/notebooks.py` line 767: `notebook_kind = notebook.get("notebook_kind", "arxiv")`. **Default is "arxiv"** — a NULL/unknown kind is treated as arxiv, which means the 10 MB cap applies. This is the safe default (conservative on the restrictive side).
- Mitigation: the schema-level default in SQLite (`notebook_kind TEXT NOT NULL DEFAULT 'arxiv'` — confirmed in `server/notebooks_store.py` m3 migration) prevents NULL from ever reaching the handler in production.

**FM-5 — Middleware needs a notebooks-store lookup per request (I/O cost / coupling / failure if store unavailable).**
- Trigger: this is option (a) from the brief's design tension.
- Symptom: If the middleware were changed to resolve notebook_kind at the ASGI layer, every upload request would require an async SQLite lookup inside the middleware. Middleware runs before FastAPI DI; accessing `app.state.notebooks_store` is possible but creates tight coupling.
- Mitigation: **Option (a) is NOT used.** The current design uses option (b): middleware at 200 MB, handler at 10 MB. This avoids I/O in middleware entirely.
- **Status: design decision made, not a risk for m10 (pure doc pass).**

**FM-6 — Path-matching false positives for the `/ui/api/notebooks` prefix.**
- Trigger: a future route at `/ui/api/notebooks-adjacent/something` would match the prefix cap because `path.startswith("/ui/api/notebooks" + "/")` would NOT match, but `path.startswith("/ui/api/notebooks/")` would for any sub-path. The `_effective_max_bytes` method uses `path == prefix or path.startswith(prefix + "/")` which correctly avoids the substring issue. **However** `/ui/api/notebooks-v2` would NOT match (correct, due to `prefix + "/"` not `prefix` alone matching).
- Mitigation: **FM-3 parity is already implemented** per `server/middleware.py` line 876: "prefix-match form (path == p or path.startswith(p + '/')) — NOT substring." The FM-3 guard in the `_effective_max_bytes` docstring is load-bearing.
- **Status: guarded correctly in existing code. Not a concern for the doc-only pass.**

---

## Recommendation

**This milestone is a doc-accuracy pass only.** All code and test deliverables described in the brief were built in textbook-ingest-m4 (shipped, state=complete). The implementer's task is:

1. **Update `.claude/docs/security-pdf-sandbox.md`** to:
   - Replace the one inaccurate reference at line 62 ("m8 cap" → correct attribution to m8 for the 1 MB→10 MB raise and m4 for the 10 MB→200 MB textbook envelope).
   - Add a dedicated `## Upload cap carve-out (textbook-ingest-m4)` section (or annotate the existing §"Caps enforced before MinerU is invoked") explicitly stating: (a) the middleware is set to 200 MB globally for `/ui/api/notebooks`, (b) the arxiv-kind 10 MB cap is enforced handler-side after `await file.read()`, (c) the DoS regression is accepted under loopback-only deployment, and (d) the code locations (`server/main.py::prefix_caps` + `server/routes/notebooks.py::_ARXIV_UPLOAD_MAX_BYTES`).
   - Cross-reference `tests/test_pdf_preflight.py::TestUploadCapPerKind` and `TestMiddlewareEnvelope` as the test coverage.
   - Confirm that `tools/security/pdfid.py` (shipped m4) and `server/routes/notebooks.py::_run_pdf_preflight` (shipped m4) match the threat surface description in the doc.

2. **No code changes.** No middleware changes. No new tests (the coverage from m4 is complete per the ACs in the brief). No tool-schema re-pin.

**Implementation approach:** the implementer should read the entire `security-pdf-sandbox.md` (486 lines), identify every forward-looking statement (e.g. "e5 will land X", "textbook-ingest-m4 enforces" — verify each against actual code), and either confirm accurate or correct. The "e5 part 1 of 2" framing in the milestone title suggests the doc should acknowledge that the upload-cap carve-out is now built and tested, removing or updating any "future work" language around it.

---

## Open questions

**OQ-1:** The brief's acceptance criteria include: "Tests: textbook >10MB accepted, arxiv >10MB rejected 413, >200MB rejected, notebook-kind resolution path, and the malformed/missing content-length edge cases." The first three are covered by `TestUploadCapPerKind` and `TestMiddlewareEnvelope`. The malformed/missing content-length edge cases — are they covered by the existing middleware tests? `grep` of `tests/test_pdf_preflight.py` found no explicit missing-content-length or malformed-content-length test for the upload route (the middleware unit tests may cover this, but in a different test file). The implementer should confirm that `tests/test_body_size_middleware.py` or equivalent exists and covers malformed Content-Length for the notebooks upload path specifically, OR add such a test if missing.

This is the one potential code deliverable remaining: if the malformed/missing content-length test for the upload route specifically does not exist, a small test must be added. Everything else is already built.

---

## External writes the implementation will require

None — this milestone is purely local (doc update + possible test addition). All changes land on `main` directly per CLAUDE.md §4.1.

| Type | Target | Why |
|---|---|---|
| `git commit` | `main` | Feat commit: doc accuracy pass on `security-pdf-sandbox.md` (possibly + missing C-L test) |
| `git commit` | `main` | Chore commit: finalize state.json → complete |
