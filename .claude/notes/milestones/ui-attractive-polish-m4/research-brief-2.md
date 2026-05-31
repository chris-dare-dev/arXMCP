# Research Brief — ui-attractive-polish-m4

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-31T15:10:00Z

---

## In-codebase context

### Design constitution notes that apply

**`07-multi-agent-caching.md`** — This milestone makes zero changes to the MCP tool surface, tool definitions, or prompt-cache breakpoints. The `EXPECTED_TOOL_SCHEMA_SHA256` in `tests/test_server_tool_schema.py` is UNCHANGED. No BP1/BP2 risk. Confirmed: all changes are confined to `server/routes/notebooks.py` (one new content-negotiation branch), `frontend/templates/notebook_detail.html` (3 attribute changes on the add-paper form), `frontend/templates/base.html` (1 LOC config flag), and `frontend/static/app.css` (~20 new lines).

**`08-security-observability-ops.md`** (threat model) — UPL-12 adds a new HTML-rendering code path for operator-controlled data. The Spike-2 pre-flight checklist is the m4-narrow threat-model gate. The full `chris-dare-dev/arXMCP#9` audit is NOT a m4 dependency (confirmed by Spike-2).

**`06-mcp-server-design.md`** — The operator console is "loopback-only, server-rendered Jinja2+htmx." UPL-12's content-negotiation branch is a server-rendered fragment, consistent with the architecture. The `SecFetchSiteMiddleware` carve-out at `("/ui",)` already covers `/ui/api/notebooks/*` — no middleware change needed.

### Codebase state — load-bearing facts

**The `add_paper` handler** (`server/routes/notebooks.py:499-551`) currently returns `dict[str, str]` on HTTP 201 — i.e. JSON only. It calls `validate_slug`, then `_arxiv_url_to_paper_id`, then `store.add_paper`. The Pydantic model is `PaperAdd(arxiv_url: str = Field(min_length=1, max_length=512))`.

**`_paper_row_html`** (`server/routes/notebooks.py:1575-1609`) is the exact pattern to reuse. It uses `html.escape()` on every interpolated value: `slug`, `paper_id`, `added_at`, and the preview URL path. It is already used by the upload handler (lines 1498 and 1568-1571). **This is the proven precedent the m4 fragment branch must match exactly.**

**The add-paper form** (`frontend/templates/notebook_detail.html:99-112`) currently has:
- `hx-post="/ui/api/notebooks/{{ notebook.slug }}/papers"` — correct, no change needed
- `hx-disabled-elt="find button"` — m3 already applied this (CONFIRMED PRESENT at line 101)
- `hx-on::htmx:after-request="if(event.detail.successful) location.reload()"` — this is the line m4 replaces
- No `hx-target`, no `hx-swap` — m4 must add `hx-target="#papers-tbody" hx-swap="beforeend"`

**`#papers-tbody`** (`notebook_detail.html:215`) already carries `aria-live="polite"` from m1 (UPL-3). Confirmed present at line 215.

**`base.html`** has ONE `<script defer>` block (lines 25-52), the `htmx:configRequest` JSON-shim. `htmx.config.globalViewTransitions = true;` must be appended INSIDE this same block. The block is inside `<head>` after `<script src="…htmx.min.js" defer>`.

**CSP:** `CONTENT_SECURITY_POLICY_UI` (server/middleware.py:170-176) = `"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"`. The `'unsafe-inline'` on `script-src` already covers the config flag line. Zero CSP change required.

**`app.css` line count:** 306 (verified). Budget cap is 330. Headroom = 24 lines. The UPL-13 CSS duration block = ~4 lines; UPL-22 `min-width` = 1 line; UPL-22 `.htmx-settling` flash = ~8-10 lines gated. Total ~15 lines → well within the 330 cap.

**CONFLICT FLAG — m4 pre-flight checklist item mismatch:** Spike-2 pre-flight checklist (`.claude/notes/ui-attractive-polish-spike-2.md:97`) says: "Pattern-match the m8 `_paper_row_html` at `server/routes/notebooks.py:1575-1604`." Line 1604 is correct as the closing `</tr>` line. **The milestone brief also cites this line range verbatim.** The implementer should use `_paper_row_html` as the direct reuse target (call it unchanged, or extract a sub-helper if the URL-paste `added_at` shape differs). Confirmed: the `add_paper` handler uses `_now_iso()` which returns an ISO-8601 string — same type as the upload handler's call at line 1570. `_paper_row_html` accepts that string directly. No shape mismatch.

---

## Prior decisions and lessons

**From MEMORY (ui-attractive-polish-m3 — htmx-request-class-on-form-not-button):** "When a `<form hx-post>` is submitted, htmx 2.0.10 applies `htmx-request` to the `<form>` element itself, NOT to the `<button type="submit">` child. CSS selector `button.htmx-request` alone will NOT dim the button on form-submission." — m3 already applied the compound selector `form.htmx-request button[type="submit"]` in `app.css:275`. The new add-paper form uses the SAME pattern as rename and ingest-now, so the in-flight dimming is automatic when m4 adds `hx-target`/`hx-swap` (the form already has `hx-disabled-elt="find button"`). **No CSS change needed for UPL-12's button disable.**

**From MEMORY (ui-attractive-polish-m3 — hx-disabled-elt-form-vs-button):** "`hx-disabled-elt` adds the HTML `disabled` attribute. `<form>` has NO standard `disabled` attribute — always apply to `<button>` or standalone elements." The add-paper form uses `hx-disabled-elt="find button"` (targets the child button, not the form). This is the correct pattern. **No change needed.**

**From MEMORY (ui-attractive-polish-m3 — details-outerHTML-swap-loses-open-state):** The `outerHTML` swap on `#status-badge` loses `open` state every 10s. m4's UPL-22 adds `min-width: 14ch` to `.status-badge` in CSS and an `.htmx-settling` flash — neither creates a `<details>` or `open` attribute issue. The flash keyframe fires on the `.htmx-settling` auto-class that htmx applies post-swap. This pattern is safe.

**From MEMORY (ui-attractive-polish-m1 — outerHTML-swap-breaks-aria-live):** "htmx `hx-swap='outerHTML'` REPLACES the element — the new element from the server must carry `aria-live` in its markup or the live region silently stops announcing after the first swap." The `#status-badge` `outerHTML` swap target (`server/routes/ui.py::ui_status_badge`) must carry `aria-live="polite" aria-atomic="true"` — this was addressed in m1. The add-paper `beforeend` swap on `#papers-tbody` does NOT replace the `<tbody>` element itself, so this hazard does not apply to UPL-12.

**git log analysis:** The last 3 commits show the m3 triple pattern: feat `58bfb41` + rect `08b9c53` + chore `b66fa1e`. m4 must follow the same triple: `feat(frontend,server): in-place add-paper + View Transitions + badge flash (ui-attractive-polish-m4)` → `rect(...)` → `chore(notes)`.

---

## External sources

### htmx 2.0.10 — `HX-Request` header

Per htmx docs (confirmed from htmx.org): "`HX-Request` always 'true' except on history restore requests if `htmx.config.historyRestoreAsHxRequest` disabled." The header value is the STRING `"true"`. FastAPI's `request.headers.get("hx-request")` returns `"true"` (lowercase header names are normalized by Starlette's Headers class). The canonical server-side check is:

```python
is_htmx = request.headers.get("hx-request") == "true"
```

Note: the function signature for `add_paper` must accept `request: Request` as a parameter to read headers. Currently it does NOT have `request: Request` in its signature (only `slug`, `body`, `store`). **The implementer must add `request: Request` to the handler signature.** FastAPI will inject it automatically — no DI change needed.

### htmx 2.0.10 — `globalViewTransitions` and `htmx:beforeTransition`

Per htmx docs (htmx.org/docs/#view-transitions):
- `htmx.config.globalViewTransitions = true` — "Set the `htmx.config.globalViewTransitions` config variable to `true` to use transitions for all swaps."
- Per-element: "Use the `transition:true` option in the `hx-swap` attribute."
- Cancellation hook: "If an element swap is going to be transitioned due to either of the above configurations, you may catch the `htmx:beforeTransition` event and call `preventDefault()` on it to cancel the transition."

The `htmx:beforeTransition` event is the opt-out mechanism. If the operator finds every-2s ingest-status poll transitions visually distracting, the mitigation is adding a listener in `base.html` that checks `event.detail.elt.id === 'ingest-status'` and calls `preventDefault()`. **This is a future-follow-up, not a m4 blocker.** The milestone brief accepts polling-driven transitions as v0 behavior.

### View Transitions CSS pseudo-elements

Per MDN (`::view-transition-old()`): Baseline status is "Newly available since October 2025." Chrome 111+ and Safari 18.2+ (macOS 15+) support it. Firefox: as of 2026-05 Firefox has partial support under a flag only (same-document transitions NOT in stable Firefox). The `htmx.config.globalViewTransitions` flag combined with htmx's internal `if (document.startViewTransition)` guard ensures Firefox gracefully no-ops.

The CSS duration override syntax uses the `(root)` pseudo-element argument:

```css
@media (prefers-reduced-motion: no-preference) {
  ::view-transition-old(root), ::view-transition-new(root) {
    animation-duration: 200ms;
  }
}
```

This is verbatim from the milestone brief AC and is correct MDN syntax.

### WCAG 2.1 SC 2.3.3 (Animation from Interactions, Level AAA)

SC 2.3.3 applies to "motion animation triggered from interaction." A View Transitions crossfade is motion animation triggered by the user's "Add" button click — technically covered. However, SC 2.3.3 is **Level AAA**, not required for AA conformance. The `prefers-reduced-motion: no-preference` gate on `::view-transition-old/new(root)` (proposed in the brief) goes beyond AAA requirement by honoring the user's OS-level motion preference. This is the correct handling.

---

## Failure-mode analysis

**F1 — Content-Type stays `application/json` on fragment branch.** FastAPI's `@router.post` with no `response_class` defaults to `JSONResponse`. Returning a string from the fragment branch would produce `"<tr>…</tr>"` (JSON-encoded string, not HTML). The fix is to return `HTMLResponse(content=..., status_code=201)` explicitly — same pattern as the upload handler at lines 1496-1503 and 1567-1572. **The upload handler precedent already uses `HTMLResponse` correctly.** The implementer must NOT return a plain string or a dict.

**F2 — `_paper_row_html` called with wrong `added_at` shape.** The current `add_paper` handler calls `store.add_paper(slug=slug, paper_id=paper_id, added_at=_now_iso())` — `_now_iso()` returns `"YYYY-MM-DDTHH:MM:SS+00:00"`. `_paper_row_html` accepts `added_at: str` and passes it through `html.escape()` directly. No shape mismatch. **F2 is a non-issue** IF the implementation calls `_now_iso()` consistently (same pattern as upload handler at line 1570). One risk: the implementation saves `added_at` to the store, then retrieves the stored value for the fragment — creating a round-trip. Simpler and equivalent: capture `ts = _now_iso()`, pass to both `store.add_paper` and `_paper_row_html`. Mirrors upload pattern exactly.

**F3 — Header case sensitivity.** Starlette's `Headers` class (which FastAPI uses) normalizes all header names to lowercase on lookup. `request.headers.get("hx-request")` returns `"true"` regardless of whether htmx sends `HX-Request: true` or `hx-request: true`. **F3 is a non-issue** provided the check uses lowercase `"hx-request"`.

**F4 — `globalViewTransitions = true` triggers crossfade on every poll cycle.** The ingest-status fragment polls every 2s; the status-badge polls every 10s. With `globalViewTransitions = true`, each poll fires `document.startViewTransition()`. The crossfade duration is 200ms (per the CSS override) — visible but brief. The milestone brief explicitly accepts this as v0 behavior: "Spike-1 — Risks the spike did NOT cover: Polling-driven swaps... belong in the m4 implementation's research phase." The `htmx:beforeTransition` opt-out mechanism exists but is NOT required for m4. **F4 is a documented accepted risk, not a blocker.**

**F5 — View Transitions height-jitter on ingest-status state changes.** When ingest-status transitions from `running` (short text) to `success` (adds " · Finished · Run #"), the swap content height increases. The View Transition crossfade snapshot captures the old height and morphs to the new height — brief layout shift. **F5 is documented in Spike-1 as acceptable for v0.** Mitigation (if needed post-m4): use `hx-swap="outerHTML transition:false"` on the `#ingest-status` element to opt that specific element out of View Transitions.

**F6 — XSS escaping: Jinja2 autoescape vs `html.escape()` Python stdlib.** The milestone brief says "send `display_name = '<img src=x onerror=alert(1)>'` through the new HX-Request branch; assert the rendered HTML contains `&lt;img` not `<img`." The fragment is built via Python f-strings using `html.escape()` (not Jinja2 templates). `html.escape('<img src=x>')` produces `'&lt;img src=x&gt;'`. For the XSS test assertion, `&lt;img` is the correct expected substring. Both Jinja2 autoescape and Python `html.escape()` produce the same `&lt;img` output. **No distinction needed in the test assertion.**

**F7 — `aria-live="polite"` on `#papers-tbody` and `beforeend` announcement.** The `#papers-tbody` element at line 215 carries `aria-live="polite"` from m1. The `beforeend` swap appends a new `<tr>` as a child without replacing the `<tbody>` element. ARIA live region mutations fire on DOM insertion into a live region's subtree. VoiceOver should announce the new row's text content. **This is the expected m1 behavior; m4 relies on it.** No additional `aria-live` markup needed on the new `<tr>` fragment.

---

## In-codebase cross-check

**(a) 8-CSS-variable token system.** The dark-mode block in `app.css:232-264` redeclares exactly 8 vars (`--fg`, `--bg`, `--card-bg`, `--border`, `--accent`, `--danger`, `--error-bg`, `--mono`). UPL-22's flash uses `color-mix(in oklab, var(--accent) 30%, transparent)` per the roadmap — derives from `--accent` only, NO new tokens. System preserved.

**(b) CSP unchanged.** `CONTENT_SECURITY_POLICY_UI` = `"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"`. UPL-13 config flag lives inside the existing `<script defer>` block covered by `'unsafe-inline'`. UPL-22 is CSS-only. UPL-12 adds no inline JS. Zero CSP change.

**(c) No new vendored assets.** The milestone adds no new static files to `frontend/static/`. No update to `VENDORED.md` or `tests/test_vendored_assets_integrity.py` needed.

**(d) `EXPECTED_TOOL_SCHEMA_SHA256` unchanged.** No MCP tools are added, removed, or modified. The 7-tool surface (`server/tools.py::ALL_TOOLS`) is not touched. The hash test stays green without re-pinning.

**(e) Jinja2 autoescape.** `server/routes/ui.py` constructs `jinja2.Environment` with `autoescape=jinja2.select_autoescape(enabled_extensions=("html","htm","xml"), default_for_string=True)`. UPL-12's fragment is Python f-string with `html.escape()`, not a Jinja2 partial — this is intentional (matches the `_paper_row_html` pattern). Zero `| safe` filters anywhere. This is load-bearing — do NOT introduce `| safe`.

**(f) `hx-disabled-elt="find button"` is already on the add-paper form.** Confirmed at `notebook_detail.html:101`. m3 already applied this. **No attribute addition needed for the button-disable behavior** — only the `hx-on::htmx:after-request` removal and `hx-target` + `hx-swap` addition.

---

## Recommendation

**Implement UPL-12 by adding `request: Request` to `add_paper`'s signature, checking `request.headers.get("hx-request") == "true"`, and on the HTML branch returning `HTMLResponse(content=_paper_row_html(slug, paper_id, ts), status_code=201)` where `ts = _now_iso()` captured before `store.add_paper`. In the template, replace the `hx-on::htmx:after-request` line with `hx-target="#papers-tbody" hx-swap="beforeend"`. For UPL-13, append `htmx.config.globalViewTransitions = true;` as the last line before `});` inside the existing `<script defer>` block in `base.html`. For UPL-22, add `min-width: 14ch` to the `.status-badge` rule and a `.htmx-settling`-keyed flash keyframe in `app.css` under the `prefers-reduced-motion: no-preference` block.**

The reasoning: reusing `_paper_row_html` unchanged avoids introducing a second HTML-assembly code path and satisfies the Spike-2 pre-flight checklist in one move. The `Request` injection is FastAPI-standard and adds zero coupling to other handlers. The `globalViewTransitions` global opt-in is simpler than per-element and aligns with Spike-1's recommendation.

---

## Open questions

1. **`htmx:beforeTransition` opt-out for polling swaps.** The milestone brief leaves this as a follow-up consideration. The implementer should NOT add the opt-out listener in m4 (not in AC). If during manual verification the every-2s ingest-status crossfade feels disruptive, note it in the implementation summary as a deferred m5 item. No code change needed for m4.

2. **`_paper_row_html` "uploaded" Actions cell.** The existing helper at line 1607 hardcodes `'<td>uploaded</td>'` in the Actions cell (instead of a Remove button). For the add-paper-by-URL fragment, the Actions cell should probably show a Remove button (or at minimum not say "uploaded"). The brief is silent on this distinction. **Recommendation:** for m4 v0, show "added" (text only, no Remove button) — same UX as the existing "uploaded" cell; the next page-load restores the standard Remove affordance. This matches the `_paper_row_html` docstring at lines 1591-1594. The implementer may extend `_paper_row_html` with an optional `action_label` parameter defaulting to `"added"`.

No open questions that block implementation. The two items above are implementation detail choices, not blockers.

---

## External writes the implementation will require

None — this milestone is purely local. All changes are confined to:
- `server/routes/notebooks.py` (content-negotiation branch on `add_paper`)
- `frontend/templates/notebook_detail.html` (3 attribute changes on add-paper form)
- `frontend/templates/base.html` (1 LOC config flag in existing inline script)
- `frontend/static/app.css` (~15-20 new lines)
- `tests/test_ui_m4_fragment_xss.py` or sibling (new test file)

No `git push`, no GitHub issue creation, no infra mutation required.
