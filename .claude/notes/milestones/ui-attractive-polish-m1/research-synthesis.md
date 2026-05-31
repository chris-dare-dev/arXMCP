# Research Synthesis — `ui-attractive-polish-m1`

**Generated:** 2026-05-31T02:25:00Z
**Inputs:**
- `.claude/notes/milestones/ui-attractive-polish-m1/research-brief-1.md` (in-codebase context lens)
- `.claude/notes/milestones/ui-attractive-polish-m1/research-brief-2.md` (external sources + failure-mode lens)
- Upstream artifacts: `plans/ui-attractive-polish-roadmap.md` (the m1 section) + `.claude/notes/frontend-uplifts/2026-05-ui-polish/artifacts/final-report.md`.

---

## 1. What ships

Four foundational a11y baselines (UPL-1..4 from the 2026-05-ui-polish discovery
pipeline), bundled into one CSS + template + **server-side fragment** edit pass.

| UPL | Where | Cost |
|---|---|---|
| **UPL-1** `prefers-reduced-motion` universal gate | `frontend/static/app.css` (bottom, ~8 LOC) | XS |
| **UPL-2** `:focus-visible` outline ring on every interactive element | `frontend/static/app.css` (~10 LOC) | XS |
| **UPL-3** `aria-live` parity on 4 htmx success swap targets | `frontend/templates/{base,notebook_detail}.html` + **`server/routes/ui.py`** + **`server/routes/notebooks.py`** | XS template + S audit |
| **UPL-4** Skip-to-main-content link | `frontend/templates/base.html` + `frontend/static/app.css` (~7 LOC) | XS |

The roadmap AC scoped UPL-3 to template edits only. **Both researchers
independently flagged that the existing roadmap AC is incomplete:** htmx
`hx-swap="outerHTML"` REPLACES the live-region element entirely on every swap,
so the new element coming from the server must ALSO carry the aria-live
attributes. This expands m1's file scope from "3 frontend files" to "3 frontend
files + 2 server-route files" — but stays comfortably within S complexity.

---

## 2. The outerHTML-aria-live trap — load-bearing implementation guidance

Both researcher-1 (§ "FLAG: outerHTML swap fragments must carry aria-live
attributes" + open-question (e)) and researcher-2 (F3 failure mode + open-question
1) converged on this finding. Quoting researcher-2 verbatim because the framing is
sharp:

> **F3 — outerHTML swap replaces the live region, breaking AT attachment.**
> Trigger: `hx-swap="outerHTML"` on `#display-name-block`, `#ingest-status`,
> `#status-badge` means the ELEMENT ITSELF is replaced, not just its content.
> The new element from the server must carry `aria-live` in its markup.
> Symptom: if the server-rendered fragment does NOT include `aria-live="polite"`
> on the replacement element, the live region silently stops announcing after
> the first swap.

Concrete fixes required:

1. **`base.html:65-67`** — initial render of `#status-badge` gets
   `aria-live="polite" aria-atomic="true"`.
2. **`server/routes/ui.py` (the `get_status_badge` handler, approximately lines 261-264)**
   — the f-string fragment that the 10s poll returns must include
   `aria-live="polite" aria-atomic="true"` on the new `<span id="status-badge">`.
   Without this, VoiceOver stops announcing badge changes after the first poll.
3. **`notebook_detail.html:15`** — initial render of `#display-name-block` gets
   `aria-live="polite"`.
4. **`server/routes/notebooks.py::_display_name_fragment`** — the f-string the
   rename-success swap returns must include `aria-live="polite"` on the new
   `<p id="display-name-block">`.
5. **`notebook_detail.html:161`** — initial render of `#ingest-status` div gets
   `aria-live="polite"`.
6. **The ingest-status polling fragment generator(s) in `server/routes/notebooks.py`**
   — every fragment returned by the polling handler must include `aria-live="polite"`
   on the new `<div id="ingest-status">`. There may be multiple state-specific
   fragments (queued / running / complete / failed); each one must carry the attribute.
7. **`notebook_detail.html:180`** — `#papers-tbody` uses `hx-swap="beforeend"`,
   NOT `outerHTML`. The `<tbody>` itself is never replaced; only `aria-live="polite"`
   on the static template element is required. No server-fragment update.

The implementer's first concrete task: **read `server/routes/ui.py` and
`server/routes/notebooks.py` end-to-end, enumerate every f-string or template
fragment that ends up in an `hx-swap="outerHTML"` target, and add the matching
aria-live attribute to each**. This audit IS the milestone — the CSS additions
are mechanical once the audit is done.

---

## 3. CSS specifications (UPL-1, UPL-2, UPL-4) — concrete sketches

### UPL-1 (universal reduced-motion clamp)

Append at the END of `app.css`:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    animation-delay: 0.01ms !important;
    transition-delay: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

The `animation-delay` + `transition-delay` lines come from the roadmap's UPL-1
challenger MINOR finding ("the sketch should ALSO add `transition-delay` and
`animation-delay` overrides to be exhaustive"). Researcher-2 confirmed this is
the exhaustive set of timing properties per MDN.

Confirmed safe: `app.css` currently has ZERO `transition` / `animation` /
`scroll-behavior` declarations (researcher-1 verified by full-file read), so the
clamp has no immediate behavioral effect. It future-proofs every motion candidate
that lands in subsequent milestones.

### UPL-2 (`:focus-visible` outline rings)

Append after the existing button/input rules in `app.css`:

```css
button:focus-visible, .button:focus-visible,
input:focus-visible, a:focus-visible,
select:focus-visible, textarea:focus-visible,
[tabindex]:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
  border-radius: 4px;
}
button.danger:focus-visible { outline-color: var(--danger); outline-offset: 3px; }
:focus:not(:focus-visible) { outline: none; }
```

The `outline-offset: 3px` on `button.danger` (vs `2px` elsewhere) is researcher-2's
addition — pushes the destructive button's ring slightly further out so it
remains visible against the red fill. Adopt.

WCAG SC 2.4.7 satisfied via W3C Sufficient Technique C45.

### UPL-4 (skip-link)

In `base.html`, insert as the VERY FIRST child of `<body>`:

```html
<a class="skip-link" href="#main">Skip to main content</a>
```

Modify the existing `<main>` (line ~53) to add `id="main" tabindex="-1"`.

Append to `app.css`:

```css
.skip-link {
  position: absolute;
  left: -9999px;
  top: auto;
  width: 1px;
  height: 1px;
  overflow: hidden;
}
.skip-link:focus-visible {
  position: fixed;
  left: 1rem;
  top: 1rem;
  width: auto;
  height: auto;
  z-index: 9999;
  padding: 0.5rem 1rem;
  background: var(--accent);
  color: #fff;
  border-radius: 4px;
  text-decoration: none;
}
```

`position: fixed` (not `absolute`) on the focused state is researcher-2's
recommendation — ensures the link appears in the viewport regardless of scroll
position. `z-index: 9999` guarantees visibility above the header. Adopt both.

`tabindex="-1"` on `<main>` makes it programmatically focusable so the
skip-link's `href="#main"` actually moves keyboard focus (per researcher-2 — some
browsers silently fail to move focus without `tabindex="-1"`).

---

## 4. Disagreements resolved

### D1: External writes — 1 push vs 0 pushes

- **Researcher-1:** 1 row, `git push → origin/main`, "land the feat + rect + chore commit triple per CLAUDE.md §4.3."
- **Researcher-2:** "None — purely local."

**Resolution:** Researcher-1 is correct. CLAUDE.md §4.4 explicitly treats `git push`
as a per-event-authorized external write. The pipeline cannot reach `complete`
while `external_writes_required` includes an unauthorized push. Record 1 external
write.

### D2: Skip-link position — `absolute` vs `fixed` on focus

- **Researcher-1:** `position: absolute` on focus.
- **Researcher-2:** `position: fixed` on focus + `z-index: 9999`.

**Resolution:** Researcher-2 wins on concrete grounds — `fixed` ensures viewport
visibility regardless of scroll, which is the WCAG intent. Adopt `position: fixed; z-index: 9999`.

### D3: `aria-relevant` attribute — needed or not?

- **Researcher-1:** Mentioned as a v1 mitigation only if VoiceOver over-announces.
- **Researcher-2:** Implicit — only mentions `aria-live` + `aria-atomic`; `aria-relevant` is the AT default (`additions text`) and not needed explicitly.

**Resolution:** Skip `aria-relevant` for m1. Defaults work. If the manual
VoiceOver smoke-test reveals over-announcement, add `aria-relevant="text"` as a
post-implementation tweak.

### D4: `index.html` UPL-3 scope (`#notebook-list` aria-live)

Both researchers note that `#notebook-list` is NOT in the m1 AC. The synthesis
(`.claude/notes/frontend-uplifts/2026-05-ui-polish/artifacts/synthesis.md` UPL-3)
explicitly states `#notebook-list` waits for UPL-12 (in epic e4, the in-place
htmx swap conversion). **m1 covers 4 targets only: `#display-name-block`,
`#ingest-status`, `#papers-tbody`, `#status-badge`.**

---

## 5. Open questions remaining (none blocking implementation)

The implementer can start immediately. Below are items to keep in mind, not gates:

1. **Manual VoiceOver smoke-test cannot be automated.** The AC requires that
   VoiceOver announces the rename success swap and the status-badge poll. This
   is a manual gate; budget ~15 minutes for it.
2. **F2 over-announcement on the 10s status-badge poll** — accept for m1 as
   the badge is always "valid" content (the cycle re-asserts the current state);
   document as a known follow-up if it bothers Chris. The mitigation (conditional
   aria-live based on state-change sentinel) is server-side complexity not worth
   the v0 cost.
3. **Server-fragment audit scope** — researcher-1's open-question (e) item 6
   warns: "Check every ingest-status fragment generator in
   `server/routes/notebooks.py` — the aria-live attribute must appear on
   EVERY fragment, not just the initial placeholder." This is the implementer's
   first step. There may be 3-5 distinct ingest-status state fragments
   (queued / running / complete / failed / no-runs); each needs the attribute.

---

## 6. Confirmed: NOT in scope

- **No tool-schema repinning** — m1 touches zero MCP tools; `EXPECTED_TOOL_SCHEMA_SHA256` unchanged.
- **No `htmx.min.js` modification** — vendored asset stays as-is; `tests/test_vendored_assets_integrity.py` unaffected.
- **No `| safe` filter additions** — autoescape contract preserved (researcher-1 + researcher-2 both verified).
- **No new vendored assets** — pure CSS + HTML attribute additions.
- **No CSP change** — `CONTENT_SECURITY_POLICY_UI` unchanged.
- **No mobile-table-overflow work** — that's m2 (UPL-19).
- **No `tabular-nums`** — that's m2 (UPL-10).
- **No `#notebook-list` aria-live** — that's a future milestone gated on UPL-12.
- **No bug-fix work (UPL-5/6/7)** — those are parallel `/milestone-pipeline ui-rename-422-fix-bm1` etc., out of this roadmap.

---

## 7. Recommended implementation order

1. **Audit `server/routes/ui.py` + `server/routes/notebooks.py`** end-to-end. Enumerate every f-string / fragment that ends up in an `hx-swap="outerHTML"` target. Note line numbers.
2. **UPL-4 (skip-link)** — structurally isolated, can ship in a separate Edit pass; add the HTML line + the two CSS rules (`.skip-link`, `.skip-link:focus-visible`) + `id="main" tabindex="-1"` on `<main>`. Manual Tab-walk verifies.
3. **UPL-2 (`:focus-visible`)** — append the rules to `app.css`. Manual Tab-walk on each route verifies the `--accent` ring appears (and `--danger` on the destructive button).
4. **UPL-1 (`prefers-reduced-motion`)** — append the universal block at the bottom of `app.css`. No immediate behavioral test; future-proofs for the next motion candidate.
5. **UPL-3 (`aria-live`)** — add attributes to (a) the 4 template elements per the AC, AND (b) the 3+ server-side fragments per the audit in step 1. The audit drives the scope.
6. **`make test` green** — full ruff + pytest run. Expect zero regressions; the only test file that could break is `tests/test_ui_html_pages.py` if it asserted on specific attribute strings (researcher-2 verified it does not).
7. **Manual VoiceOver smoke-test** — trigger a rename, wait 10s for badge poll, confirm announcements fire. **This is the milestone's evidence gate.**
8. **Commit `feat(server,frontend): ...` with all changes.** Single logical unit.

---

## 8. External writes the implementation will require

| type | target | why | blocking? |
|---|---|---|---|
| `git push` | `origin/main` | Land the feat + rect + chore commit triple per CLAUDE.md §4.3. Per-event authorization required (CLAUDE.md §4.4). | yes (Phase 4 external-write gate) |

No GitHub issues, no infra mutation, no third-party API calls. Single push.

---

## 9. Orchestrator synthesis note

The two researcher briefs reached strong consensus on the load-bearing
implementation risk (outerHTML-swap aria-live trap, surfaced independently by
both). The disagreements (D1-D4) were small and resolved on concrete grounds.
The brief is implementer-ready: every UPL has a sketch, every server-side
audit step has a target file, every WCAG criterion has an SC number.

The single divergence with the upstream roadmap AC is the implicit assumption
that UPL-3 is "template-only" — both researchers correctly expanded the scope
to include the server-rendered fragments. The implementer should treat the
research synthesis (this file) as the authoritative scope, not the roadmap AC
alone. Update the implementation summary's "Deviations from the brief" section
to record this scope expansion explicitly.

---

*End of synthesis.*
