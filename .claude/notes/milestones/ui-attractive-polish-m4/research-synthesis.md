# Research Synthesis — `ui-attractive-polish-m4`

**Generated:** 2026-05-31T15:25:00Z
**Inputs:**
- `research-brief-1.md` (in-codebase context lens — surfaced the `has_preview` param need; cited the `added_at` capture-then-pass pattern from the upload-handler precedent)
- `research-brief-2.md` (external sources + failure-mode lens — verified `HX-Request: true` semantics, FastAPI header normalization; enumerated 7 failure modes inc. `Content-Type` and ARIA-live behavior on `beforeend`)
- Upstream artifacts: `plans/ui-attractive-polish-roadmap.md` § `### ui-attractive-polish-m4` (the m4 brief incl. the Spike-2 pre-flight checklist as AC) + both spike memos at `.claude/notes/ui-attractive-polish-spike-{1,2}.md`.
- Post-m3 state: m1+m2+m3 shipped on `origin/main`; 61 a11y/polish tests must continue passing.

---

## 1. What ships (3 UPLs, one M-sized feat commit)

| UPL | Location | LOC | Risk |
|---|---|---|---|
| **UPL-12 v0** | `server/routes/notebooks.py` (add 1 branch + capture `ts`) + `notebook_detail.html` (3 attr changes on add-paper form) + extend `_paper_row_html` with `has_preview: bool = True` param | ~25 LOC | content-negotiation correctness; XSS escaping discipline (covered by Spike-2 pre-flight) |
| **UPL-13** | `base.html` (1 LOC inside existing inline `<script>` block) + optional `app.css` `::view-transition-old/new(root)` duration override (~4 LOC, gated) | ~5 LOC | none (Spike-1 confirmed native htmx integration; `if (document.startViewTransition)` guard handles Firefox) |
| **UPL-22** | `app.css` (`.status-badge { min-width: 14ch }` + `.htmx-settling` flash keyframe under `prefers-reduced-motion: no-preference`) | ~10 LOC | none (CSS-only; uses m2's `color-mix()`, m1's reduced-motion gate already in app.css) |

Total: ~40 LOC production + new test file. Complexity: **M** per the roadmap AC.

---

## 2. Concrete implementation sketches (synthesis-authoritative)

### UPL-12 v0 — add-paper content-negotiation branch

**`server/routes/notebooks.py` — `add_paper` handler:**

```python
async def add_paper(
    slug: str,
    body: PaperAdd,
    request: Request,          # NEW — for header access (FastAPI auto-injects)
    store: NotebooksStore = Depends(get_notebooks_store),
):
    # ... existing validate_slug + notebook-exists + _arxiv_url_to_paper_id chain ...
    ts = _now_iso()             # NEW — capture once for both store + fragment
    await store.add_paper(slug=slug, paper_id=paper_id, added_at=ts)

    # NEW — content-negotiation: htmx clients get a <tr> fragment, JSON clients
    # keep the existing dict body. The header check is case-insensitive (Starlette
    # normalizes); "true" is the literal htmx 2.0.10 sends.
    if request.headers.get("hx-request") == "true":
        return HTMLResponse(
            status_code=status.HTTP_201_CREATED,
            content=_paper_row_html(
                slug=slug,
                paper_id=paper_id,
                added_at=ts,
                has_preview=False,   # NEW kwarg — URL-paste writes no ar5iv HTML
            ),
        )
    return {"slug": slug, "paper_id": paper_id}
```

**`server/routes/notebooks.py` — `_paper_row_html` extension:**

```python
def _paper_row_html(
    slug: str, paper_id: str, added_at: str,
    *, has_preview: bool = True,    # NEW — default True preserves upload behavior
) -> str:
    """..."""
    if has_preview:
        preview_cell = (
            f'<td><a href="/ui/notebooks/{html.escape(slug)}/papers/'
            f'{html.escape(paper_id)}/preview" target="_blank" rel="noopener">'
            f"Preview</a></td>"
        )
    else:
        # m4 (UPL-12 v0): URL-paste has no ar5iv HTML on disk; mirror the
        # m10-rect F6 "no preview" pattern used in notebook_detail.html:230-232.
        preview_cell = (
            f'<td><span class="hint" '
            f'title="upload an ar5iv HTML to enable preview">Preview</span></td>'
        )
    return (
        f'<tr data-slug="{html.escape(slug)}" '
        f'data-paper-id="{html.escape(paper_id)}">'
        f'<td>{html.escape(paper_id)}</td>'
        f'<td>{html.escape(added_at)}</td>'
        f'{preview_cell}'
        f'<td>added</td>'    # m4 — was "uploaded"; "added" applies to both paths
        f"</tr>"
    )
```

Note: changing `"uploaded"` → `"added"` is a synthesis decision (both researchers
flagged the "uploaded" cell mismatch for URL-paste; "added" is neutral and
applies to both paths). The upload-handler call site is unchanged structurally
(it just passes `has_preview=True` by default) but the operator now sees
"added" instead of "uploaded" on the upload success row. This is a 1-word UX
change documented in the deviation section of the implementation summary.

**`frontend/templates/notebook_detail.html` — add-paper form (around line 99):**

```html
<form
  hx-post="/ui/api/notebooks/{{ notebook.slug }}/papers"
  hx-disabled-elt="find button"
  hx-target="#papers-tbody"       <!-- NEW -->
  hx-swap="beforeend"             <!-- NEW -->
  hx-on::htmx:response-error="document.getElementById('paste-error').textContent = (function(t){try{return JSON.parse(t).detail||t;}catch(e){return t;}})(event.detail.xhr.responseText)"
>
```

REMOVED: `hx-on::htmx:after-request="if(event.detail.successful) location.reload()"`.
The error handler stays unchanged. The `#papers-tbody` already carries
`aria-live="polite"` from m1 UPL-3 (`notebook_detail.html:~215`); the new
`<tr>` append fires the live-region announcement automatically (per researcher-2
F7 — verified by ARIA spec).

### UPL-13 — View Transitions config flag

**`frontend/templates/base.html` — inside the existing inline `<script defer>` block:**

```js
document.addEventListener('htmx:configRequest', function (evt) {
  // ... existing JSON-shim body unchanged ...
});

// m4 — UPL-13 (Spike-1 finding): htmx 2.0.10 has native View Transitions
// integration. Flipping this flag wraps every htmx swap in
// document.startViewTransition() automatically; Firefox gracefully no-ops
// via htmx's internal `if (document.startViewTransition)` guard.
htmx.config.globalViewTransitions = true;
```

**Optional `frontend/static/app.css` duration override** (recommended per
roadmap AC):

```css
@media (prefers-reduced-motion: no-preference) {
  ::view-transition-old(root), ::view-transition-new(root) {
    animation-duration: 200ms;
  }
}
```

Default browser duration is ~250ms; explicit 200ms keeps the operator console
snappy. Gated by `prefers-reduced-motion: no-preference` (m1's discipline
ensures reduced-motion users get the universal clamp instead).

### UPL-22 — footer-badge stability + flash

**`frontend/static/app.css` — extend `.status-badge` rule + add flash keyframe:**

```css
.status-badge {
  /* ... existing rules unchanged ... */
  min-width: 14ch;     /* m4 UPL-22 — stable footer width across state changes.
                          1ch = width of "0"; 14ch fits "DEGRADED · corpus v999".
                          Font-family is var(--mono) so ch is predictable. */
}

@media (prefers-reduced-motion: no-preference) {
  /* m4 UPL-22 — flash on htmx swap-in. htmx auto-applies .htmx-settling
     to the swap target after settle; we paint a brief accent flash so
     operators see "the badge just refreshed." Uses m2's color-mix()
     adoption to derive a soft accent tint. */
  .status-badge.htmx-settling {
    animation: badge-flash 400ms ease-out;
  }
  @keyframes badge-flash {
    from { background: color-mix(in oklab, var(--accent) 30%, transparent); }
    to   { background: transparent; }
  }
}
```

---

## 3. The Spike-2 pre-flight checklist — load-bearing AC

The m4 brief includes the Spike-2 13-item pre-flight checklist verbatim
(`plans/ui-attractive-polish-roadmap.md` lines ~520-545). The synthesis confirms
each item is satisfied by the sketches above:

**Server-fragment correctness (issue #9 open Q5):**
- ✅ Every interpolated value in `_paper_row_html` uses `html.escape()` (per the existing helper; the extension preserves this).
- ✅ Zero `| safe` filters or `Markup(...)` calls added; the fragment is a Python f-string, not a Jinja2 partial.
- ✅ Content-negotiation on `HX-Request: true`; JSON branch preserved.
- ✅ Fragment renderer interpolates only `slug` (path param, `validate_slug`-checked), `paper_id` (regex-validated via `_arxiv_url_to_paper_id`), `added_at` (server-generated `_now_iso()`). NO raw request body or header values.

**Middleware integrity (issue #9 open Q1):**
- ✅ `SecFetchSiteMiddleware` carve-out at `("/ui",)` unchanged — `server/middleware.py` has zero hunks in m4's diff.
- ✅ `OriginValidationMiddleware` + `HostValidationMiddleware` unchanged.
- ✅ `CONTENT_SECURITY_POLICY_UI` unchanged.

**Input validation invariants (issue #9 open Q3):**
- ✅ `validate_slug` called before fragment construction (same as JSON branch — validation runs BEFORE the response fork).
- ✅ `_arxiv_url_to_paper_id` rejects unparseable URLs.
- ✅ `PaperAdd` Pydantic model unchanged.

**Test surface:**
- New file `tests/test_ui_m4_fragment_xss.py` covers all 3 test items (XSS payload, content-negotiation, slug-validation gate).

---

## 4. Disagreements resolved

### D1: External writes — 1 push vs 0

- r1: 1 push to origin/main (CLAUDE.md §4.3/§4.4)
- r2: "None — this milestone is purely local"

**Resolution: r1 wins.** Same as m1/m2/m3 — `git push` is per-event-authorized per CLAUDE.md §4.4. The pipeline cannot reach `complete` while `external_writes_required` lists an unauthorized push.

### D2: `_paper_row_html` extension — `has_preview` only OR also `action_label`?

- r1: extend with `has_preview: bool = True` only
- r2: extend with `has_preview` AND optionally `action_label: str = "uploaded"`

**Resolution: extend with `has_preview` only; change "uploaded" → "added" unconditionally** (synthesis decision). Rationale: the upload card's Actions cell currently says "uploaded" — that text is correct only for that path. "Added" is neutral and applies to both upload and URL-paste with equal accuracy. Changing it for both paths is one less parameter and one less branch.

This is a **1-word UX change to the existing upload-handler row** — documented in the implementation-summary deviation section. Operationally it's a no-op (operators rarely re-read the Actions cell on the upload success row; the column gets replaced by Remove on next page-load).

### D3: Polling-driven View Transitions — opt out specific swaps?

Both researchers agree: ACCEPT default for v0. The `htmx:beforeTransition` opt-out
mechanism exists but doesn't ship in m4. Document as deferred m5 item.

---

## 5. Open questions remaining (none blocking)

1. **Manual cross-browser verification on Safari** — UPL-13's `globalViewTransitions` requires Safari 18.2+ for native support; older Safari versions fall through htmx's `if (document.startViewTransition)` guard and no-op. Chris's primary browser is Chrome on macOS — full support assumed. Manual gate.
2. **VoiceOver smoke-test on the new add-paper announcement** — the m1 `aria-live="polite"` on `#papers-tbody` should fire when the new `<tr>` is `beforeend`-appended; ARIA spec confirms but real-world AT behavior varies. Manual gate.
3. **The "uploaded" → "added" UX wording change** affects the existing upload card too (since both paths now share `_paper_row_html` with the new label). This is intentional but worth a one-line note in the implementation summary.

---

## 6. Confirmed NOT in scope

- Create-notebook and remove-notebook flows stay on `location.reload()` (m5 v1 follow-on per the roadmap).
- m1 sites (`prefers-reduced-motion`, `:focus-visible`, `aria-live`, skip-link) — untouched.
- m2 sites (`tabular-nums`, `.table-wrap`, `color-mix()` hover, favicon) — untouched.
- m3 sites (dark mode, `.htmx-request` styling, `hx-disabled-elt` attributes) — untouched.
- `_paper_row_html` Actions cell — kept text-only ("added"); no Remove button (next page-load restores the standard Remove affordance, matching the existing m8 pattern docstring).
- The `htmx:beforeTransition` opt-out for polling swaps — deferred to m5.
- The full UI security audit (`chris-dare-dev/arXMCP#9`) — stays open as a separate effort per Spike-2.
- Tool-schema repinning — m4 touches zero MCP code.
- New vendored assets — none.
- CSP change — none (UPL-13 uses existing `'unsafe-inline'`).

---

## 7. Recommended implementation order

1. **Extend `_paper_row_html` with `has_preview: bool = True`** + change "uploaded" → "added" in the Actions cell. ~6 LOC.
2. **`add_paper` handler — add `request: Request` param, capture `ts = _now_iso()`, fork on HX-Request header, return `HTMLResponse` with `_paper_row_html(..., has_preview=False)` on htmx branch.** ~12 LOC.
3. **Template — replace `hx-on::htmx:after-request` with `hx-target` + `hx-swap`.** 2 attribute changes (one removal, two additions).
4. **`base.html` — append `htmx.config.globalViewTransitions = true;` inside existing inline script block.** 1 LOC.
5. **`app.css` — `.status-badge { min-width: 14ch }` + the `.htmx-settling` flash keyframe + the View Transitions duration override.** ~15 LOC total.
6. **Tests** at `tests/test_ui_m4_in_place_add_paper.py` (new file) covering:
   - Spike-2 pre-flight: XSS payload injection through HX-Request branch; content-negotiation; slug-validation gate.
   - Template assertions: `hx-target="#papers-tbody"` + `hx-swap="beforeend"` present on add-paper form; `hx-on::htmx:after-request` REMOVED (negative regression guard).
   - `base.html` carries `htmx.config.globalViewTransitions = true`.
   - `app.css` has `.status-badge { min-width: 14ch }` AND the `.htmx-settling` flash keyframe AND the `::view-transition-*(root)` duration override.
   - `_paper_row_html` with `has_preview=False` renders the `.hint` placeholder, not the live `<a>`.
7. **`make test` green** — 61 m1+m2+m3 tests + new m4 tests all pass.

---

## 8. External writes

| type | target | why |
|---|---|---|
| `git_push` | `origin/main` | Land the pre-step `chore(plans,notes)` (roadmap m4 section + 2 spike memos) + feat + rect (if any) + chore(notes) finalize per CLAUDE.md §4.3. Per-event authorization (CLAUDE.md §4.4) at the Phase-4 external-write gate. |

No GitHub issues, no infra, no third-party API calls.

---

## 9. Orchestrator synthesis note

The two researcher briefs converged strongly — both identified the `added_at`
capture-then-pass requirement, both recommended `_paper_row_html` reuse,
both flagged the `request: Request` signature change, both verified the
Spike-2 pre-flight checklist items. The only deltas were small (D1 external
writes, D2 `_paper_row_html` extension shape) and resolved on concrete
grounds.

The synthesis's one independent decision: change `"uploaded"` → `"added"`
in `_paper_row_html` Actions cell rather than parameterize it. This
trims one parameter from the helper and accepts a 1-word UX change on
the upload-handler path that operators rarely re-read.

The Spike-1 + Spike-2 work proved its worth: m4's implementation surface
is materially simpler than the original e4 sketch (UPL-13 dropped to 1
LOC, UPL-12 v0 narrowed to one route, no audit-coordination overhead).
The implementer can proceed inline.

*End of synthesis.*
