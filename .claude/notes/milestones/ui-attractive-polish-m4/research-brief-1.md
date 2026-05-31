# Research Brief — ui-attractive-polish-m4

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-31T15:10:00Z

---

## In-codebase context

### Design constitution notes that apply

**`06-mcp-server-design.md` § "Browser UI surface"** (verbatim load-bearing):

> "**Loopback-only bind** — `127.0.0.1`; non-loopback rejected at config parse. **Jinja2 autoescape** — the environment is constructed EXPLICITLY with `autoescape=select_autoescape(enabled_extensions=("html","htm","xml"), default_for_string=True)`. Zero `| safe` filters in any template (load-bearing — it is the stored-XSS guard for operator-authored fields like `display_name`). **CSP** — `CONTENT_SECURITY_POLICY_UI` on `/ui/*` pages."

> "**CSRF posture** — no token, by design: `SecFetchSiteMiddleware(exempt_prefixes=("/ui",))` admits `Sec-Fetch-Site: same-origin` on `/ui/*` and rejects cross-site."

These two paragraphs establish why the pre-flight checklist (Spike-2) is the authoritative audit gate for m4: any new fragment endpoint that does NOT follow this pattern is a stored-XSS or CSRF regression.

**`CLAUDE.md §4.7`** (load-bearing):
- "`assert` is BANNED for invariants — Python -O strips them."
- "Pure-ASGI middleware required. `BaseHTTPMiddleware` is project-banned."
- "No `anthropic` SDK at runtime."

**`07-multi-agent-caching.md`**: m4 touches no MCP tools, no prompt-cache-adjacent surfaces. The `EXPECTED_TOOL_SCHEMA_SHA256` pin is NOT affected — this milestone modifies only frontend templates, CSS, and one route handler response branch. No `ALL_TOOLS` changes.

### Add-paper handler (current state) — `server/routes/notebooks.py`

The `add_paper` handler at line 503 already implements the correct validation chain:

1. `validate_slug(slug)` — path-traversal guard (line 516)
2. `await store.get_notebook(slug) is None` → 404 (line 523)
3. `_arxiv_url_to_paper_id(body.arxiv_url)` → host-whitelist + regex (line 529)
4. `await store.add_paper(slug=slug, paper_id=paper_id, added_at=_now_iso())` (line 540–541)
5. Returns `{"slug": slug, "paper_id": paper_id}` — **only slug + paper_id, NOT added_at** (line 551)

**Critical gap for UPL-12 v0**: the existing handler captures `added_at` via `_now_iso()` INSIDE `store.add_paper()` but does NOT capture it in a local variable to pass to `_paper_row_html`. The new fragment branch must call `_now_iso()` once, store it in a local (`added_at = _now_iso()`), pass it to BOTH `store.add_paper()` AND `_paper_row_html()`. This is the add-paper handler's ONLY structural difference from the upload handler (which does the same at line 1570).

**The upload handler pattern** (lines 1567–1572) is the direct template:
```python
return HTMLResponse(
    status_code=status.HTTP_201_CREATED,
    content=_paper_row_html(
        slug=slug, paper_id=paper_id, added_at=_now_iso(),
    ),
)
```

UPL-12 v0 must fork the add-paper handler: if `request.headers.get("HX-Request") == "true"`, return `HTMLResponse` via `_paper_row_html`; else return the existing JSON dict (preserving the existing `return {"slug": slug, "paper_id": paper_id}`). The handler signature must gain a `request: Request` parameter for header access (FastAPI dependency injection; no route signature change).

### `_paper_row_html` — current shape (`server/routes/notebooks.py:1575–1609`)

Four-column `<tr>`: Paper ID | Added | Preview | Actions. The Actions cell says "uploaded" (not a Remove button) — the docstring explains this is "the m8 pattern: immediately providing Remove after upload is UX confusion; the next page-load restores the standard Remove affordance via the rendered template." **This same reasoning applies verbatim to UPL-12 v0** — the add-paper fragment should say something like "added" in the Actions column, not a Remove button. The Preview column: for URL-paste adds there is no ar5iv HTML on disk (no file uploaded), so `has_preview` is False. The existing helper hardcodes a Preview link unconditionally because upload always writes the file. **m4 must either (a) call `_paper_row_html` as-is (giving a broken preview link for URL-paste rows) or (b) add a `has_preview: bool = True` parameter and pass `False` for the URL-paste case.** Option (b) is cleaner UX. Option (a) is strictly safe (the link just 404s — no security issue) and matches the stated "reuse as-is" precedent from Spike-2. Recommendation: option (b), a one-parameter extension, since the Actions column already differs ("added" vs "uploaded").

### Frontend template — `frontend/templates/notebook_detail.html`

Add-paper form at line 99–113:
```html
<form
  hx-post="/ui/api/notebooks/{{ notebook.slug }}/papers"
  hx-disabled-elt="find button"
  hx-on::htmx:after-request="if(event.detail.successful) location.reload()"
  hx-on::htmx:response-error="..."
>
```

UPL-12 v0 replaces the `location.reload()` line with `hx-target="#papers-tbody" hx-swap="beforeend"` and removes the `hx-on::htmx:after-request`. The `aria-live="polite"` on `<tbody id="papers-tbody">` is already present (line 215, added by m1 UPL-3) — no template change needed for a11y.

**`base.html` inline `<script defer>` block** (lines 25–52): the existing `htmx:configRequest` JSON-conversion shim is here. UPL-13 adds ONE line: `htmx.config.globalViewTransitions = true;` before or after the `document.addEventListener` call. No new event listeners, no CSP widening.

**`frontend/static/app.css`** (306 lines post-m3): `.status-badge` rule at lines 146–158 has no `min-width`. UPL-22 adds `min-width: 14ch` here. A new `@keyframes` + `.htmx-settling` block (~8 LOC) gated by `@media (prefers-reduced-motion: no-preference)` lands after line 306. Budget: 306 + ~20 = ~326 lines, within the ≤330 cap.

The m3 `@media (prefers-reduced-motion: reduce)` block at lines 213–222 is the universal clamp that zeroes all animations/transitions for reduced-motion users — **the UPL-22 `.htmx-settling` keyframe does NOT need its own reduce gate because the universal clamp already handles it**. The `no-preference` media query on the flash keyframe is sufficient.

---

## Prior decisions and lessons

**Recent git log (last 20 commits):** m1 (c5adff3), m2 (672ad81+4f1f664+fdd28d4), m3 (58bfb41+08b9c53+b66fa1e) all shipped on `main`. Latest is onboarding-uplift-m3 (867edb7). All 3 ui-attractive-polish milestones follow the three-commit pattern: `feat` → `rect` → `chore`.

**outerHTML-swap-breaks-aria-live lesson from m1**: the m1 research confirmed that `outerHTML` swaps require the server fragment to carry `aria-live`. The `beforeend` swap used by the upload card (and now the add-paper card) does NOT replace the `<tbody>` — it appends to it. The `aria-live="polite"` on `<tbody id="papers-tbody">` (line 215) is a STATIC attribute that persists across all `beforeend` appends. **m4 does not need to add `aria-live` to any server-rendered fragment** for the UPL-12 case — the tbody is never replaced.

**hx-disabled-elt-form-vs-button (agent memory)**: The milestone-researcher memory notes: "`hx-disabled-elt='this'` on a `<form>` is a silent no-op; always apply to `<button type='submit'>` or standalone button." The existing add-paper form uses `hx-disabled-elt="find button"` which targets the child button correctly — no change needed.

**htmx-request-class-on-form-not-button (agent memory)**: m3 added `form.htmx-request button[type="submit"]` as a selector alongside `button.htmx-request`. The new add-paper swap uses a `<form hx-post>`, so this selector chain already handles the in-flight spinner on the Add button without any change to app.css.

**No conflict with m1/m2/m3 additions**: m3's `.htmx-request` styling, m2's `color-mix()`, m1's `prefers-reduced-motion` gate — all compose cleanly with m4's additions. No selector collisions found.

**m4 state.json**: state is `research-running`, `research_briefs: []` — this is the first research artifact. No prior research to incorporate.

---

## External sources

**htmx 2.0.10 `HX-Request` header** (htmx.org reference, confirmed): `HX-Request: true` is sent on ALL htmx-initiated requests. It is a client-supplied hint — not a trust boundary — used only for response-format selection. Server input validation must run regardless of this header's presence or absence.

**htmx 2.0.10 View Transitions** (htmx.org/docs/#view-transitions, confirmed):
- `htmx.config.globalViewTransitions = true` — global opt-in; every htmx swap gets `document.startViewTransition()`.
- `hx-swap="<style> transition:true"` — per-element opt-in.
- `htmx:beforeTransition` event — `preventDefault()` opts out a single swap instance.
- htmx's internal guard: `if (document.startViewTransition)` — Firefox and older browsers no-op cleanly.

Both confirmed by direct inspection of `frontend/static/htmx.min.js` (Spike-1 §A, lines 1–4 of evidence).

**View Transitions browser support**: Chrome 111+ (2023), Safari 18.2+ (macOS 15). Chris's primary browser is Chrome on macOS — full support. Firefox no-ops gracefully.

**MDN `::view-transition-old(root)` / `::view-transition-new(root)`**: pseudo-elements are created by the browser during a `startViewTransition()` call. `animation-duration` can be overridden via CSS. The `@media (prefers-reduced-motion: no-preference)` gate around the override is the correct pattern (consistent with m1's UPL-1 discipline already in app.css lines 213–222 — the universal clamp handles reduced-motion; the override block only fires when motion is acceptable).

**MDN CSS `ch` unit**: `1ch` = width of the `0` character in the element's font (monospace for `.status-badge` per app.css line 151 `font-family: var(--mono)`). In a monospace font all glyphs are equal-width so `14ch` gives 14 characters of stable width. Baseline since IE9; well-supported on all target browsers.

**No MCP spec pull needed**: m4 modifies no MCP tool surface. `EXPECTED_TOOL_SCHEMA_SHA256` is unaffected.

---

## Recommendation

**Implement UPL-12 v0, UPL-13, and UPL-22 as specified, with one deliberate extension to `_paper_row_html`:**

Add a `has_preview: bool = True` parameter (default True preserves upload-handler behavior) and pass `False` from the new add-paper fragment branch, rendering a `<span class="hint">` no-preview cell instead of a broken preview link. This is a 4-LOC change to the helper plus one argument at the call site, within the "reuse `_paper_row_html`" mandate of Spike-2 — it extends rather than replaces.

For UPL-12's content-negotiation branch: add `request: Request` to `add_paper`'s signature, capture `added_at = _now_iso()` once before `store.add_paper()`, then fork on `request.headers.get("HX-Request") == "true"` AFTER all validation passes and the store insert succeeds. The fork is purely at response construction — validation and the store insert are unconditional.

For UPL-22's `.htmx-settling` flash: use `color-mix(in oklab, var(--accent) 30%, transparent)` as the flash color (per original synthesis reference in the roadmap). Target `#status-badge` specifically with `#status-badge.htmx-settling` or the general `.status-badge.htmx-settling` selector. Recommended: use `.status-badge.htmx-settling` so any future status-badge variant also gets the flash without another CSS rule.

**Polling-driven View Transitions** (open concern from Spike-1): accept the default for v0. The `htmx:beforeTransition` opt-out mechanism exists but adds implementation surface for marginal UX gain. The ingest-status poll (every 2s) and badge poll (every 10s) crossfading are visually benign for a loopback-only operator console. If the visual quality is unacceptable on review, use `hx-swap="outerHTML transition:false"` on the specific poll triggers as a targeted follow-up.

---

## Open questions

**(a) Does the existing handler expose `added_at` for the fragment?**

NO. The current `add_paper` handler calls `_now_iso()` inside `store.add_paper()` without capturing the value locally (line 540–541: `await store.add_paper(slug=slug, paper_id=paper_id, added_at=_now_iso())`). The return at line 551 is `{"slug": slug, "paper_id": paper_id}` — no `added_at` field. The fix: `added_at = _now_iso()` before the call, then `added_at=added_at` at both the store call and the fragment builder. This is a required change, not an assumption.

**(b) `_paper_row_html` scope — should it be extended or reused as-is?**

Recommendation: extend with `has_preview: bool = True`. See Recommendation section. The add-paper URL-paste flow writes NO file to disk, so the existing hardcoded preview link in `_paper_row_html` would generate a 404 for every URL-paste row until the operator manually uploads. This is a UX defect, not a security issue, but it's correctable with minimal scope expansion that the Spike-2 "reuse precedent" still satisfies.

**(c) Polling-driven View Transitions — opt-out specific swaps?**

For v0: NO. Accept the default behavior. The `htmx:beforeTransition` opt-out is available as a targeted follow-up if operators find the polling crossfades distracting. This is explicitly noted in Spike-1's "Risks the spike did NOT cover" section and is acknowledged as a v0 acceptable tradeoff.

**No further open questions** — implementation can proceed on the above recommendation once (a) and (b) are resolved as specified.

---

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| `git push` | `origin/main` | Land the `feat` + `rect` + `chore` commit triple per CLAUDE.md §4.3 three-commit pattern. Requires per-event user authorization per §4.4. |
