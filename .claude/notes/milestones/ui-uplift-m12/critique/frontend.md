# Critique — ui-uplift-m12 — milestone-frontend-ux

**Critic:** milestone-frontend-ux
**Commit range:** 6f5cbbc0be184e65a9ba39d4a4199d9b1971879c..75f325595acbfbf8ecf0492be92fe2edda484175
**Diff stats:** 11 files, 1304 LOC (rendered frontend surface: 2 files, 266 LOC — `notebook_detail.html` 235, `app.css` 31)
**Critique format version:** 1.0

**Method note, stated plainly:** this is a **source-level review with no rendered
page**. `create_app()` needs an ingested corpus, so no dev server was started and
no screenshot exists. Every geometric or AT claim below is derived from the
template, `app.css`, `server/routes/ui.py`, `server/routes/notebooks.py`,
`server/notebooks_store.py` and the vendored `htmx.min.js` — read directly, not
searched, because `rg` cannot see `.claude/`. Where a claim would need a
composited frame to settle (the disclosure marker at 375px), it is marked
unverified and rated accordingly rather than asserted.

## Verdict

**SHIP-WITH-FIXES.** The reorder does what it claims: the papers table is the
second region on the page, above every mutation control, and the disclosure is a
real progressive-disclosure region rather than a hidden-functionality trap —
it is forced open in every state except a completed ingest, and the empty-state
copy names it by the label the operator actually sees. One HIGH stands in the
way: an operator who collapses the disclosure during a run loses the ingest
success/failure surface entirely, with no visible recovery, which is the exact
failure class AC#2 exists to prevent, reachable one click after page load. Three
MEDIUMs are cheap: the new `<summary>` is the only interactive element on the
page outside the authored focus-ring system, region 3 is absent from heading
navigation, and nothing near the corpus points to the machinery once the
disclosure closes over an unbounded papers table.

## Executive summary

- **[HIGH]** Collapsing the disclosure mid-ingest silently kills the run's only
  status and error surface — the poll keeps firing into a `display:none` region,
  the `aria-live` announcement is suppressed with it, and the `<summary>` cue is a
  page-load snapshot that never updates. `failed` + `stderr_tail` becomes
  unreachable without a reload the page never suggests.
- **[MEDIUM]** `<summary>` — the sole entry point to all five mutation forms —
  is not in `app.css:450`'s `:focus-visible` ring list, nor in
  `test_ui_a11y_baselines.py`'s enumeration of it. It falls back to the UA ring
  while every other control on the page carries `2px solid var(--accent)`.
- **[MEDIUM]** Region 3 has no heading and no accessible name. The summary renders
  at `--text-section` (20px, identical to every `h2`) but is a `role=button`, so
  heading-list navigation jumps from "Papers in this notebook" straight into
  "Topic & discovery" with no boundary — and the heading list changes shape
  depending on whether the disclosure is open.
- **[MEDIUM]** `store.list_papers()` is uncapped and the disclosure sits below the
  whole table. On a 50-paper notebook (the size `tools/seed-papers.txt` implies)
  the only machinery affordance is ~2400px down — further than the ~1740px scroll
  the milestone exists to remove, in the opposite direction, with no anchor,
  sticky, or in-table entry point.
- **[LOW]** `<code>` inside the summary drops to `--text-small` (13px) against the
  20px the rule deliberately authors for size parity — the m7
  element-rule-overrides-inherited-size lesson recurring at a new site.
- **[LOW]** `list-style-position: outside` is the one declaration in the new rule
  with no recorded reason, and it hangs a 20px-font marker into `body`'s 16px
  padding.
- **[GOOD]** The authored strings were recovered from `.claude/` rather than
  invented, AC#5's false "Chromium-only" premise was corrected at both sites, and
  `show:` was verified against `htmx.config.scrollBehavior: "instant"` so it adds
  no un-gated motion. This is the cleanest milestone in the track's record.

## Findings

**H1 — Collapsing the disclosure hides the ingest error path with no recovery** (HIGH)

**Where:** `server/frontend/templates/notebook_detail.html:472`
**Anchor:** `  <div id="ingest-status"`
**What:** `#ingest-status` polls every 2s from *inside* the disclosure, so an operator who clicks the `<summary>` shut during a run keeps the poll firing into a non-rendered subtree — no visible status, no `aria-live` announcement (content of a closed `<details>` is excluded from the accessibility tree), and the `<summary>` cue at `:258` is a page-LOAD snapshot that will keep reading `running` after the run has finished or failed.
**Why it matters:** The failed-ingest branch carries `stderr_tail` — the most operationally important error in the product per the discovery's own UPL-10 framing — and one click makes it unreachable for the rest of the session, with the only recovery being a page reload the page never suggests; AC#2's forced-open predicate is evaluated at render time only, so it cannot re-open a disclosure the operator closed.
**Proposed fix:** Make the cue live instead of a snapshot, zero new JS: give the cue its own element inside the summary (`<span id="ingest-cue" hx-swap-oob="true">`) and have `_ingest_status_fragment` (`server/routes/notebooks.py:2354+`) emit an out-of-band copy on every poll branch. The `<summary>` is always rendered even when the disclosure is shut, so a collapsed operator still sees `ingest failed` / `ingest success` change under them, and the existing forced-open predicate then only has to handle first paint. Alternative, larger: hoist `#ingest-status` out of the disclosure entirely (brief-2 §5.3, recorded as the road not taken), which dissolves the failure class rather than mitigating it.
**Regression-guard:** `tests/test_ui_m12_corpus_before_machinery.py::TestDisclosureOpenState` — add a case asserting `_ingest_status_fragment` emits an OOB cue element for all four states, plus a template assertion that the summary's status text is a swap target rather than a bare Jinja interpolation.
**Source critic:** milestone-frontend-ux
**Source axis:** Error states

---

**M1 — The new `<summary>` is outside the authored `:focus-visible` ring system** (MEDIUM)

**Where:** `server/frontend/static/app.css:450`
**Anchor:** `button:focus-visible, .button:focus-visi`
**What:** The ring list is `button, .button, input, a, select, textarea, [tabindex]` — `summary` is absent, so the milestone's new control (and m10's `.discover-abstract > summary`) falls back to the UA default ring instead of `2px solid var(--accent)` at `outline-offset: 2px`.
**Why it matters:** `<summary>` is the only keyboard-reachable gate to all five mutation forms; it is the one control on the page whose focus state is unauthored, and `tests/test_ui_a11y_baselines.py::test_focus_visible_rule_covers_all_interactive_selectors` enumerates the list by hand, so the omission is invisible to the guard that exists for exactly this class of gap.
**Proposed fix:** Add `summary:focus-visible,` to the selector list at `app.css:450-455` (one token, no new rule, no cap pressure) and add `"summary:focus-visible"` to the `test_focus_visible_rule_covers_all_interactive_selectors` tuple. Check the ring against `--bg` for SC 1.4.11 3:1 — `--accent` already clears it as the button ring, so no contrast artifact regeneration is needed.
**Regression-guard:** `tests/test_ui_a11y_baselines.py::TestFocusVisible::test_focus_visible_rule_covers_all_interactive_selectors` with `summary:focus-visible` added to the enumerated list.
**Source critic:** milestone-frontend-ux
**Source axis:** Accessibility

---

**M2 — Region 3 is absent from heading navigation and has no accessible name** (MEDIUM)

**Where:** `server/frontend/templates/notebook_detail.html:258`
**Anchor:** `  <summary>Manage this notebook — ingest`
**What:** The summary is styled at `--text-section` — byte-identical to `h2` (`app.css:100`) — but is a `role=button`, so the page's third region contributes nothing to the heading list; a screen-reader user navigating by heading goes "Papers in this notebook (N)" → "Topic & discovery" with no signal that they entered a different region, and the heading list silently gains or loses five entries depending on the disclosure's open state.
**Why it matters:** The milestone's whole thesis is that the page now has three legible regions; two of them are announceable and the third is only announceable to someone who tabs rather than navigates by heading, which inverts the region hierarchy for the AT users the reorder is supposed to help most. The implementer's reason for *not* nesting an `<h2>` inside `<summary>` is correct (role=button makes children presentational) — the gap is that no alternative was put in its place.
**Proposed fix:** Do not add a heading. Name the group instead: `id="manage-summary"` on the `<summary>` and `aria-labelledby="manage-summary"` on the `<details>` — HTML-AAM maps `<details>` to `role=group`, so this gives the region an announced name on entry at zero structural cost, does not touch m8's `^<(section|div)>` record view, and reuses the same id M3's anchor needs.
**Regression-guard:** `tests/test_ui_m12_corpus_before_machinery.py::TestManageDisclosureNesting` — assert the rendered `<details>` carries `aria-labelledby` resolving to an existing `id` on its own `<summary>`.
**Source critic:** milestone-frontend-ux
**Source axis:** Accessibility

---

**M3 — Nothing near the corpus points to the machinery, over an uncapped table** (MEDIUM)

**Where:** `server/frontend/templates/notebook_detail.html:150`
**Anchor:** `  <h2>Papers in this notebook ({{ papers`
**What:** `server/routes/ui.py:437` calls `store.list_papers(slug)` with no limit and the template renders every row, so the `<summary>` — the only affordance for adding, discovering, uploading or ingesting once a notebook has ingested successfully — sits below the entire table; the pointer to it exists only in the `{% if not papers %}` empty state at `:159`, i.e. exactly when it is least needed.
**Why it matters:** The milestone was justified by a measured ~1740px scroll to the corpus; a 50-paper notebook (`tools/seed-papers.txt` ships 50 ids) puts the machinery ~2400px below the fold with no anchor, no sticky affordance and no in-table entry point — the scroll was inverted rather than removed, and no milestone artifact records the large-corpus case.
**Proposed fix:** One anchor, zero CSS: give the disclosure `id="manage"` (the same id M2 needs) and add `<a href="#manage">Manage this notebook</a>` to the papers `<section>` beside the `<h2>` at `:150`, so the entry point is adjacent to the corpus in every state. Note in the template that this is deliberately a link and not a duplicated control, so it cannot drift into a second primary CTA (BAN-9).
**Regression-guard:** Optional (MEDIUM) — a render assertion that the papers `<section>` contains an `href="#…"` resolving to the disclosure's `id`.
**Source critic:** milestone-frontend-ux
**Source axis:** Discoverability

---

**L1 — `<code>` in the summary drops to 13px against the authored 20px** (LOW)

**Where:** `server/frontend/static/app.css:324`
**Anchor:** `code, time { font-family: var(--mono); f`
**What:** The element-level rule sets an absolute `font-size: var(--text-small)` (13px), so the state token inside `<summary>` renders at 13px inside a label the m12 rule deliberately sets to `--text-section` (20px) "for size parity with the other regions" — the parity the comment claims holds for the label text and not for the datum the cue exists to show.
**Why it matters:** This is the m7 lesson recurring verbatim at a new site (an element rule with an absolute size silently overriding every context it nests inside); it is not obviously wrong here — a 13px mono token beside a 20px label is arguably the two-voice scale working — but it was not checked, and the same rule is why `<h2><code>{{ notebook.slug }}</code></h2>` at `:54` renders the page's primary identifier below body size.
**Proposed fix:** Decide it rather than inherit it. Either add `.manage-disclosure > summary code { font-size: inherit; }` if the cue should match the label, or record in the m12 CSS comment that the 20px/13px step is the intended two-voice pairing so the next milestone does not "fix" it. No token change either way.
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-frontend-ux
**Source axis:** Design-token / design-system discipline

---

**L2 — `list-style-position: outside` is unrecorded and hangs the marker into body padding** (LOW)

**Where:** `server/frontend/static/app.css:93`
**Anchor:** `.manage-disclosure > summary { margin-bl`
**What:** In a milestone that records a reason for every declaration and every refusal, this is the one declaration with none; it moves the disclosure marker out of the summary's content box so the label aligns with the `h2`s above, and the only space it has to hang into is `body { padding: 1rem }` (`app.css:21`) — `main` has no padding rule of its own.
**Why it matters:** At `--text-section` (20px) the UA `disclosure-closed` marker plus its gap is close to 16px, so at narrow viewports the triangle may sit at or past x=0 and clip — **unverified, and unverifiable in this review** because no page was composited; the concrete defect that IS verified is the missing rationale, which is what lets a later milestone delete or "harmonise" it without knowing it carries the label's alignment.
**Proposed fix:** Record the reason in the existing m12 comment block (one line: "`outside` so the label aligns with the sibling `h2`s; the marker hangs into `body`'s 1rem"). If a browser check shows clipping at 375px, add `padding-inline-start: 1.25rem` to the summary and drop back to the default position.
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-frontend-ux
**Source axis:** Mobile / narrow-viewport

---

**L3 — The state cue duplicates a datum already rendered in the masthead** (LOW)

**Where:** `server/frontend/templates/notebook_detail.html:123`
**Anchor:** `        <span class="hint">(ingest <code`
**What:** `latest_run.status` is now rendered twice on one page in the same `<code>` voice — once in the masthead's "Last indexed" row and again in the disclosure summary — and both are page-load reads of the same row, so they can never disagree but always repeat.
**Why it matters:** The masthead is the region this critique's axis 1 asks to justify itself, and it currently ends with a destructive Delete button and a metadata list that the disclosure summary now partially restates; repeating the same token 130 lines apart adds density without adding a fact (BAN-R3's neighbourhood), and UPL-5's posture lede — which owns this masthead — will have to resolve the duplication anyway.
**Proposed fix:** Leave both for now and record the overlap in the m12 template note so `ui-uplift-m11`/UPL-5 inherits the decision rather than rediscovering it. If one goes, the masthead's is the redundant copy: "Last indexed `<time>`" already carries the freshness fact, and the run *outcome* belongs next to the control that produces it.
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-frontend-ux
**Source axis:** Information density

---

**L4 — The "seven blocks to three regions" claim is stated unconditionally but is state-dependent** (LOW)

**Where:** `server/frontend/templates/notebook_detail.html:257`
**Anchor:** `<details class="manage-disclosure"{% if `
**What:** The open predicate is "open unless `success`", so on every notebook that has never been ingested (`latest_run is None`) and on every failed or running one, the default render still presents all seven headed blocks stacked — the reduction to three visible regions is only realised after a successful ingest, and neither the template note, the implement synthesis, nor the BAN-2 recovery says so.
**Why it matters:** The `none` arm is the weak one: the stated justification is that "`none` and `running` both still poll every 2s", but a `none` poll can never transition without an action taken *inside* the disclosure, so forcing it open buys nothing that first-paint ordering does not already give — and it is the arm that costs the milestone its BAN-2 payload on exactly the first-run page the discovery cared about most. The ladder still ranks the inner blocks at `--rule-row` under one `--rule-section` region, so this is a claim-precision defect, not a layout one.
**Proposed fix:** Keep the predicate (open-on-first-run is the right call for an empty notebook) and fix the record: state in the m12 template note that the three-region *render* is the post-`success` state and that first run deliberately trades it for immediate access to the forms. If the predicate is ever narrowed to AC#2's literal wording (non-terminal or failed), the empty-state copy at `:159` becomes the only pointer and M3's anchor becomes mandatory rather than cheap.
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-frontend-ux
**Source axis:** Visual hierarchy

## What was done well

- **The authored strings were recovered, not invented.** "Manage this notebook"
  (`art-direction-scout-brief.md:428-430`) and the cue form
  (`challenge.md:107`) came out of `.claude/` — the tree `rg` cannot see — which
  breaks the m7/m8/m10 pattern of re-deriving values that were already on disk.
  The research synthesis names the tool blind spot as the root cause rather than
  blaming the implementer, and that diagnosis is correct.
- **AC#5's reason was corrected rather than repeated.** `::details-content` is
  Baseline *newly* across all engines since 2025-09-16, not Chromium-only; the
  refusal now stands on Newly-not-Widely with the m6 `light-dark()` / m7
  `text-wrap: balance` / m10 `line-clamp` precedent named at both sites, and the
  guard asserts absence over **comment-stripped** CSS so the comment explaining
  the refusal cannot satisfy the test that enforces it.
- **The `open` attribute is emitted bare, and the inversion is tested.**
  `open="false"` renders a `<details>` open; `TestDisclosureOpenState` renders all
  four states and asserts the string `open=` never appears, which is the only
  form of that test that catches the bug.
- **The ladder-reachability break was predicted, repaired in place, and guarded.**
  `main >` is a direct-child combinator, so nesting the five blocks silently
  dropped their rule, margin and padding; the fix folded `details` into the
  existing section-rung selector at zero net lines and shipped
  `TestRuleLadderReachesEveryRegion`, closing the coverage gap that made the break
  invisible to m8's token/horizontality guards.
- **`show:#papers-tbody:bottom` is the right fix and adds no motion.** Verified
  against the vendored `htmx.min.js` 2.0.10: `scrollBehavior` defaults to
  `"instant"`, so the scroll needs no `prefers-reduced-motion` gate and does not
  walk into the surface map's wholesale AP-2 block. Zero CSS, zero dependency.
- **The AC#1 narrowing is recorded three times, including in a test that asserts
  the template still says why.** "An unrecorded narrowing of an AC is
  indistinguishable from failing it" is exactly right, and rename staying with the
  record's identity is the correct call on the merits.
- **The empty-state copy is actionable in the state it targets.** It quotes the
  disclosure's visible label, and because a closed `<details>` still renders its
  `<summary>`, the instruction resolves even when the region is shut — which is
  what keeps this progressive disclosure on the legitimate side of the
  dark-pattern line.
- **The summary rule is class-scoped for a stated reason.** A bare `summary`
  selector at (0,0,1) would have out-declared `.discover-abstract > summary`'s
  unset properties and stripped m10's abstract-reveal marker; keeping the native
  `::marker` also preserves the only open/closed channel Firefox + VoiceOver
  exposes.
- **The prior rejection of `<details>` was answered at the site.**
  `onboarding-uplift-m3` D2 refused a disclosure that lived *inside* the swapped
  element; the note explains why nesting the polled element instead escapes that
  reasoning, and writes down the hard constraint it creates for m13 (no swap may
  target the `<details>` or any ancestor).
- **Nothing was added that the ban list forbids.** No new token, no new colour
  pair (contrast artifact regenerated byte-identical at 101 pairs), no icon
  (BAN-3 stays at 0), no status pill for the cue (BAN-7 stays at 0), no
  "Quick Actions"/"Controls" heading (BAN-10 stays at 0), and no `name` attribute
  that would have opted the nested `.discover-abstract` disclosures into
  exclusive-accordion grouping.

Severity counts: C0 H1 M3 L4

## Recommended rectification order

H1, M1, M2, M3, L1, L2, L4, L3
