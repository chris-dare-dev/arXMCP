# Critique — ui-uplift-m10 — milestone-frontend-ux

**Critic:** milestone-frontend-ux
**Commit range:** 216aff062f78d44d314b7b33f72d6b836192e0ee..9444a4cf0cb6b17eae8d0e7b2793032eea0e05ec
**Diff stats:** 14 files, 1974 LOC (frontend surface: `app.css` +79/−2, `tokens.css` +22/−0)
**Critique format version:** 1.0

**Review method — source-level only.** No dev server was run and no browser render was
observed: `create_app()` refuses to boot without an ingested corpus, and the Discover panel
additionally needs a live arXiv call. Every rendered claim below is derived from the CSS
cascade, the fragment builders, the Jinja template, and OKLCH→sRGB + WCAG arithmetic I
computed myself; none of it is a screenshot. Where I state a colour or a ratio, I recomputed
it rather than quoting the implementer's table.

## Verdict

**SHIP-WITH-FIXES.** The typographic work is genuinely good — four of discovery finding H3's
five authored rules ship essentially verbatim with correct token substitution, the ban list
was actively consulted rather than nodded at, and AC#4's refusal to manufacture a relevance
line is the right call argued from the data. Two things hold it back: the abstract is now
clamped with no affordance to reveal it and no cue that anything was cut, on the one surface
the console builds for operator judgment; and `--fg-muted` was minted without migrating any of
the eleven greys beside it, which in dark mode puts three distinct secondary-text values in a
single card. Neither is expensive to fix and neither is a wrong direction — they are an
unfinished one.

## Executive summary

- [HIGH] `.discover-abstract` hides 40–70% of an arXiv abstract behind `max-height` + `overflow: hidden` with no `…`, no fade, no `<details>`, and no control — the operator deciding whether to Add a paper now has strictly less information than before m10, and no signal that information is missing.
- [MEDIUM] `--fg-muted` is a **twelfth** grey, not a replacement: in dark mode the Discover card renders `.card .hint` at `#b3b9c0` (8.95:1) three lines above `.discover-meta` at `#9fa4a8` (7.04:1), and `--fg-muted` dark sits within a 1.036 luminance ratio of `.card .note`/`.card .empty` `#9ba1a8` — two values too close to be intentional.
- [MEDIUM] `.discover-list { list-style: none }` strips list role in Safari/VoiceOver with no compensating `role="list"`; the results list loses its item count for AT users on the surface where "how many candidates" is the first question.
- [MEDIUM] Candidate titles are `<p class="discover-title">` with `font-weight: 600` and no heading level — "this is a paper title" is conveyed by type treatment alone, and a screen-reader user cannot navigate the list by heading.
- [MEDIUM] BAN-9 (multiple primary CTAs per viewport, on the **must-be-removed** list) is live and unaddressed on the exact surface m10 designed: every candidate row carries a full-accent `Add` button. The implementer's ban audit checked BAN-2/3/7 and UPL-24 but not BAN-9.
- [MEDIUM] The panel discloses no ordering. The list is `sortBy=submittedDate&sortOrder=descending`, and dressing it as bibliography-style search results actively strengthens the "these are ranked by relevance" reading that AC#4 exists to avoid.
- [MEDIUM] H3's abstract/meta size step was dropped — both render at `--text-small` (13px), so the hierarchy is two steps where H3 authored three.
- [MEDIUM] The stylesheet contradicts itself on run size (`:195` "a run is up to 10 rows" vs `:222` "up to 200 candidates a run"); the route passes no `max_results`, so 200 is live, and the ladder plus the `aria-atomic="true"` announcement are both unbounded.

## Findings

**H1 — Abstract truncated with no reveal affordance and no truncation cue** (HIGH)

**Where:** `server/frontend/static/app.css:231`
**Anchor:** `.discover-abstract { margin: 0.25rem 0 0`
**What:** `max-height: 4.5em; overflow: hidden` clips the abstract to three lines with no ellipsis, no fade, no "more" control and no `<details>` disclosure, so an operator cannot read the hidden text or even tell that text was hidden.
**Why it matters:** This is the console's only surface that presents external content for an operator decision (per-candidate Add), and m10 removed reading capability from it — pre-m10 the full abstract rendered; post-m10 roughly 40–70% of an 800–1500-character abstract is unreachable in-console, and because the cut lands cleanly on a line boundary a short abstract and a truncated one are visually indistinguishable.
**Proposed fix:** Make the truncation self-declaring and reversible with zero JS. Change the fragment builder to emit `<details class="discover-abstract"><summary>` + the first sentence, with the full text as the disclosure body — native, keyboard-operable, and it collapses the visual/AT asymmetry the current clamp creates. If markup must stay frozen, the minimum acceptable stopgap is a CSS-only cue that the text continues: keep the clamp, add `position: relative` plus an `::after` gradient fade to `var(--card-bg)` over the last line box, and append a literal "… (abstract truncated)" span to the fragment — but a cue without a reveal is a worse product than a disclosure, so prefer `<details>`. Add `overflow-wrap: anywhere` in the same edit: `overflow: hidden` clips horizontally too, and arXiv abstracts carry inline-math and URL tokens that will not wrap.
**Regression-guard:** `tests/test_ui_class_css_coverage.py` (or a new `tests/test_ui_m10_discover.py`) asserting that whenever `.discover-abstract` carries a `max-height`/`line-clamp`/`overflow: hidden` declaration, the emitted fragment for a long `abstract_head` also contains a `<details>`/`<summary>` pair or a literal truncation marker — i.e. clamping without an affordance fails.
**Source critic:** milestone-frontend-ux
**Source axis:** First-time-user clarity / information density

---

**M1 — `--fg-muted` adds a twelfth grey instead of replacing any; dark mode now shows three secondary greys per card** (MEDIUM)

**Where:** `server/frontend/static/tokens.css:162`
**Anchor:** `    --fg-muted: oklch(71.512% 0.008 250)`
**What:** The token is minted and consumed by three m10 surfaces, but none of the eleven hand-typed greys was migrated, so `--fg-muted` now coexists with them on the same cards — in dark mode `.card .hint` renders `#b3b9c0` (8.95:1 on `--card-bg`) and `.discover-meta` renders `#9fa4a8` (7.04:1) inside one `<section class="card">`, while `.card .note`/`.card .empty` at `#9ba1a8` (6.79:1) is within a 1.036 luminance ratio of `--fg-muted` — a difference no reader can resolve and no author can have intended.
**Why it matters:** The milestone's stated purpose for the token is coherence, and shipping it un-migrated inverts that: the Discover card previously had one secondary voice per element role and now has two visibly different ones (8.95:1 vs 7.04:1 is a real dark-mode step), plus a near-duplicate pair, so the product reads as less systematic than before the token existed. Light mode hides this — `#555` vs `#51585f` is a 1.033 ratio — so the regression is dark-mode-only, which is exactly where this track's regressions keep landing.
**Proposed fix:** Migrate in the same track, not "someday": point `.card .hint`, `header .subtitle`, `dl.meta dt`, `.card .empty` and `.card .note` at `var(--fg-muted)` and delete the matching entries from the dark-mode remap rule at `app.css:456-458` (they become inert once the light rule uses a mode-aware token — that is the whole point of minting one). `.card .display-name` (`#444`/`#c9d1d9`) is a *primary* value, not a muted one, and should go to `var(--fg)` rather than `--fg-muted`. If a full migration is too wide for a rectify, migrate at minimum the two greys that render inside the Discover and Topic cards — `.card .hint` and `.card .empty` — since those are the ones now sitting adjacent to `--fg-muted`.
**Regression-guard:** Extend `tests/test_ui_contrast.py` or the token test with an assertion that no `color:` declaration in `app.css` outside the `.status-badge--*` pill family uses a literal hex — the pills are the documented v1 exception; everything else must go through a token.
**Source critic:** milestone-frontend-ux
**Source axis:** Design-token / design-system discipline

---

**M2 — `list-style: none` removes list semantics in Safari/VoiceOver with no `role="list"`** (MEDIUM)

**Where:** `server/frontend/static/app.css:209`
**Anchor:** `.discover-list { list-style: none; margi`
**What:** WebKit deliberately drops the implicit `list` role from a `<ul>` whose `list-style` is `none`, and the fragment emits `<ul class="discover-list">` with no explicit `role="list"`, so VoiceOver stops announcing "list, N items" and stops offering list navigation.
**Why it matters:** m10 introduced this — before the rule, the list had bullets and kept its semantics. On a results surface the item count and "item 3 of 12" position are the primary scanning affordance for a non-visual operator, and the only remaining count is the `.hint` sentence at the top of a region that is announced atomically.
**Proposed fix:** Emit `<ul class="discover-list" role="list">` in `_discover_results_fragment` (`server/routes/notebooks.py:748`). One attribute, no CSS change, no behaviour change for sighted users. The CSS-only alternative — `list-style-type: ""` instead of `none`, which preserves the role in WebKit — is available but less legible to the next reader; prefer the explicit role and keep the comment naming why.
**Regression-guard:** Assert in the fragment test that a rendered candidate list contains `role="list"` whenever `app.css` declares `list-style: none` on `.discover-list` — a derived pairing, like the tabular-nums scope test.
**Source critic:** milestone-frontend-ux
**Source axis:** Accessibility

---

**M3 — Candidate titles carry no heading level; "title" is conveyed by font-weight alone** (MEDIUM)

**Where:** `server/routes/notebooks.py:732`
**Anchor:** `                f'<p class="discover-tit`
**What:** Each candidate's title is a `<p>` distinguished only by `font-weight: 600` at inherited body size, so the results list has no heading structure and the title/meta/abstract hierarchy m10 built is available to sighted readers only.
**Why it matters:** Screen-reader users cannot jump between candidates by heading, which on a list that can run to 200 rows is the difference between scannable and linear; and "information conveyed by type treatment alone" is the accessibility failure mode this milestone's own thesis (a typographic hierarchy) makes most likely.
**Proposed fix:** Change the emitted element to `<h3 class="discover-title">` — the enclosing `<section class="card">` already owns an `<h2>`, so `h3` is the correct level and no other heading in the fragment competes. Add `font-size: inherit` to the existing `.discover-title` rule so the UA `h3` size does not override the deliberate no-size-step decision; `margin: 0` and `font-weight: 600` are already declared, so the rendered result is byte-identical to today.
**Regression-guard:** Assert the fragment emits a heading element (not `<p>`) for `.discover-title`, and that `app.css` pins `font-size: inherit` on it so the rendered size does not drift when the element changes.
**Source critic:** milestone-frontend-ux
**Source axis:** Accessibility

---

**M4 — BAN-9 (multiple primary CTAs per viewport) ships unaddressed on the surface m10 designed** (MEDIUM)

**Where:** `server/frontend/static/app.css:210`
**Anchor:** `.discover-candidate { padding: 0.75rem 0`
**What:** Every candidate row carries a full-accent `<button type="submit">Add</button>` inheriting the single `button { background: var(--accent); color: #fff }` rule, so a viewport showing six candidates shows six primary CTAs — BAN-9, which `final-report.md:67-68` puts on the **must be removed** list — and the milestone's ban audit enumerated BAN-2, BAN-3, BAN-7 and UPL-24 but not BAN-9.
**Why it matters:** `challenge.md:881` scores BAN-9 at 0 in the target state on the strength of "UPL-1's disclosure collapses five forms" — that projection is about the detail page's *forms* and never accounted for a per-row CTA on an unbounded list, so the score is optimistic exactly here. A ladder of accent fills also fights D-1's thesis directly: the Ledger Sheet is a continuous record carried by hairlines, and six saturated buttons are the loudest thing on it.
**Proposed fix:** Give the row action a secondary tier inside m10's own rules — no markup change, no new token: `.discover-candidate button { background: transparent; color: var(--accent); border: 1px solid var(--border); }` plus `.discover-candidate button:hover { background: color-mix(in oklab, var(--card-bg) 92%, var(--accent)); }`, reusing the `color-mix` idiom already at `app.css:132`. The `:focus-visible` ring and the `.htmx-request` loading state both still apply because they are keyed on `button`, not on the fill. Verify the new text/ground pair in `tests/test_ui_contrast.py` (accent on `--card-bg` is 6.20:1-ish in light; register both modes rather than assuming).
**Regression-guard:** Register the `.discover-candidate button` foreground/ground pair in `tests/test_ui_contrast.py::PAIRS` for both modes so the secondary tier cannot regress below SC 1.4.3.
**Source critic:** milestone-frontend-ux
**Source axis:** Experiential motion & distinctiveness (ban-list adherence)

---

**M5 — The panel discloses no ordering, and bibliography styling makes it read as relevance-ranked** (MEDIUM)

**Where:** `server/routes/notebooks.py:746`
**Anchor:** `            f'<p class="hint">{len(candi`
**What:** The results are reverse-chronological (`tools/_arxiv_api.py:156-157` pins `sortBy=submittedDate&sortOrder=descending`) but the panel copy says only "N new candidate(s) — results are not saved", and the new styling makes the list look like arXiv/Semantic Scholar search results, which readers know to be relevance-ranked by default.
**Why it matters:** AC#4 correctly refused to *state* a relevance the data cannot support; this leaves the panel free to *imply* one. An operator who reads the top rows first because "the best matches are at the top" is acting on a rank the feed never produced, and the only evidence to the contrary is a mono, muted, 13px timestamp on the second line of each entry.
**Proposed fix:** Amend the existing `.hint` string to name the ordering — e.g. `f'{len(candidates)} new candidate(s), newest first — results are not saved; click Discover to re-run.'`. Three words, one f-string, no new element, no manufactured evidence: it states the ordering the driver actually applied. Both research briefs proposed this as the honest alternative to a relevance line, and the implement synthesis declined it purely on line budget, which a rectify does not have.
**Regression-guard:** Assert the discover fragment's hint text contains an ordering disclosure whenever the driver's query pins a `sortBy`, so the copy and the query cannot drift apart.
**Source critic:** milestone-frontend-ux
**Source axis:** Microcopy

---

**M6 — H3's abstract/meta size step was dropped; the hierarchy is two steps, not three** (MEDIUM)

**Where:** `server/frontend/static/app.css:219`
**Anchor:** `.discover-meta { margin: 0.25rem 0 0 0; `
**What:** H3 authored `.discover-meta` at `0.8rem` (12.8px) and `.discover-abstract` at `0.875rem` (14px) — distinct steps — and m10 collapsed both onto `--text-small` (13px), so meta and abstract now differ only by family and colour, not size.
**Why it matters:** The milestone's single deliverable is a typographic hierarchy, and the collapse means a candidate reads as two type levels (16px title, 13px everything-else) rather than the three H3 designed; the abstract, which is the content the operator actually judges, is now the same size as the identifier line above it and smaller than the surrounding body text.
**Proposed fix:** Restore the step by removing `font-size: var(--text-small)` from `.discover-abstract` so it inherits `--text-body` (16px) — this is closer to H3's 0.875rem than 13px is, matches the "abstract in body text" that H3's SOTA paragraph describes, and the clamp arithmetic survives unchanged because `4.5em` and the unitless inherited `line-height: 1.5` both scale with the element's own font-size (4.5 × 16 = 72px = 3 × 24px). The alternative — dropping `.discover-meta` to `--text-meta` (11px) — is worse: 11px muted mono for an operator-read identifier is below where this track has been willing to go.
**Regression-guard:** Optional (MEDIUM). If added: assert `.discover-abstract`'s computed step is strictly larger than `.discover-meta`'s in the stylesheet.
**Source critic:** milestone-frontend-ux
**Source axis:** Visual hierarchy

---

**M7 — The run size is 200, not 10; the stylesheet contradicts itself and both the ladder and the live-region announcement are unbounded** (MEDIUM)

**Where:** `server/routes/notebooks.py:748`
**Anchor:** `            f'<ul class="discover-list">`
**What:** `app.css:195` justifies omitting a per-row chip with "a run is up to 10 rows" while `app.css:222` says "up to 200 candidates a run"; the route calls `discover_for_notebook_async(store, slug, contact_email=...)` with no `max_results`, so the `= 200` default (`tools/discover_for_notebook.py:69`) is what ships, and the fragment renders every candidate with no cap, no pagination and no "showing N of M".
**Why it matters:** At ~150px per styled candidate, 200 rows is a ~30,000px unbroken ladder with the only count (`.hint`) scrolled off the top — and because `#discover-results` carries `aria-live="polite" aria-atomic="true"` (`notebook_detail.html:183`, re-emitted by the fragment), the whole thing is announced as one utterance, which with the full abstracts deliberately retained in the DOM is an unskippable wall of speech. The clamp comment presents "the full text stays in the DOM… it is what a screen reader announces" as an accessibility benefit; under `aria-atomic="true"` it is the opposite, and the sighted operator sees three lines while the AT user hears all of it.
**Proposed fix:** Two independent, cheap steps. (1) Correct the false premise: fix the `:195` comment to say 200 and re-check the BAN-7 reasoning against that number rather than against 10. (2) Bound the surface: pass an explicit `max_results` from the route (20–30 is a sane operator page) and state the truncation in the hint copy — "showing the 25 newest of N". A bounded list also bounds the atomic announcement, which is the cheapest available fix for the announcement problem short of restructuring the live region.
**Regression-guard:** Optional (MEDIUM). If added: assert the route passes an explicit `max_results` rather than relying on the driver default, so a driver-side default change cannot silently re-open a 200-row render.
**Source critic:** milestone-frontend-ux
**Source axis:** Information density

---

**L1 — `.topic-category`'s label renders at full `--fg` while its value is muted, inverting the product's label/value convention** (LOW)

**Where:** `server/frontend/static/app.css:242`
**Anchor:** `.topic-category { margin: 0; font-size: `
**What:** `.topic-category` sets no `color`, so the literal label text "Discovery category:" inherits `--fg` (16:1 light, `#d7dbe0` dark) while the operator's own topic prose in `.topic-description` directly beneath it is `--fg-muted` — and the product's other label pattern, `dl.meta dt`, is muted.
**Why it matters:** In a block m10 authored in one edit, the boilerplate label outranks the content it labels, and the same block now carries three text colours in four lines (hint, label at `--fg`, description at `--fg-muted`).
**Proposed fix:** Add `color: var(--fg-muted)` to `.topic-category` so the label matches `dl.meta dt`'s role; the `<code>` value inside it keeps its own treatment and stays the emphasised element. Register the resulting pair in `tests/test_ui_contrast.py` (it is the same token on the same card ground already measured, so this is a row, not a new solve).
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-frontend-ux
**Source axis:** Visual hierarchy

---

**L2 — The 3-line clamp silently depends on an inherited `line-height` nothing asserts** (LOW)

**Where:** `server/frontend/static/app.css:231`
**Anchor:** `.discover-abstract { margin: 0.25rem 0 0`
**What:** `max-height: 4.5em` yields exactly three line boxes only because `body { line-height: 1.5 }` (`app.css:23`) is unitless and inherits as a multiplier; the rule itself declares no `line-height`, and nothing in the suite pins the coupling.
**Why it matters:** Any future `line-height` on `.card`, `.discover-candidate` or `.discover-abstract` — or a switch to a unit-bearing value — converts the currently clean boundary cut into a partial glyph row, which is the specific failure the implementer's comment claims the design avoids. The claim is correct today; it is just undefended.
**Proposed fix:** Declare `line-height: 1.5` on `.discover-abstract` itself so the clamp's two halves live in one rule, and extend the comment to say the two numbers are coupled (4.5 = 3 × 1.5) rather than leaving the reader to reconstruct it from `body`.
**Regression-guard:** Optional (LOW).
**Source critic:** milestone-frontend-ux
**Source axis:** Design-token / design-system discipline

## What was done well

- **H3's authored design is honoured, not substituted, on four of its five rules.** `.discover-list`, `.discover-candidate` (including the `0.75rem 0` padding and the `1px solid var(--border)` hairline verbatim), `.discover-title { font-weight: 600 }` and `.discover-meta`'s mono+muted treatment all ship as the discovery authored them, with H3's raw `rem` literals correctly translated onto m7's `--text-small` instead of pasted — which is the right call and is exactly the failure mode m7's own critique flagged. The one substitution is the abstract rule (H1/M6).
- **The `:last-child` refinement is a real improvement on H3.** H3's authored `.discover-candidate` would have left a stray hairline against the card's bottom padding; `.discover-candidate:last-child { border-bottom: none }` is a one-line addition that makes the ladder terminate cleanly, and it is the kind of detail that separates a ladder from a table.
- **The truncation arithmetic is correct and I verified it independently.** `4.5em` against the element's own `--text-small` and the unitless inherited `line-height: 1.5` is exactly 3 × 19.5px = 58.5px, so the cut lands on a line-box boundary with no partial glyph row. The refusal of `line-clamp` on Baseline-Limited grounds is consistent with the m6 `light-dark()` and m7 `text-wrap: balance` precedents, and consistency of that bar across milestones is worth more than the individual call.
- **AC#4's absence is argued from the data, three independent ways, and written into the stylesheet.** Refusing to manufacture a relevance basis the arXiv Atom feed does not carry is the correct decision, and recording the refusal at the point of use means the next milestone re-litigates it against evidence rather than against a NotebookLM screenshot. M5 asks for a disclosure of the *real* ordering, which strengthens this decision rather than reversing it.
- **AC#5 was finished rather than met on a technicality.** m7's `font-size` pin satisfied the letter of "a selector exists" while discovery H1's actual defect — an inline `<small>` welded to the side of a 14ch pill — stayed shipped. `display: block` + `margin-top` + `line-height: 1.4` is the caption H1 asked for, and choosing to fix the rendered outcome over the test-visible one is the right instinct.
- **The token was derived, not eyeballed.** `--fg-muted` is OKLCH on the existing brand hue at its own mode's `--fg` chroma, binary-searched against a *named* ground with the ground choice (`--card-bg`, because no consumer sits on the canvas) argued rather than assumed. My own recomputation lands at 7.015:1 light and 7.037:1 dark — the stated targets. M1 is about what was left un-migrated beside it, not about how it was made.
- **The ban list was actively consulted at authoring time.** BAN-2 (card grid), BAN-3 (icons), BAN-7 (per-row chips) and the killed UPL-24 state-history strip are each named in the stylesheet with the reason they were not taken, and I confirmed none of them crept in: there is no chip class, no icon, no grid, no history strip, and no second accent. M4 is a gap in that audit, not an absence of one.
- **The information-density change is a large net win.** Pre-m10 each candidate rendered its full 800–1500-character abstract at 16px in a UA-bulleted list; the styled row is a fraction of that height, which is what makes a multi-candidate run scannable at all. H1 asks for the hidden text to be *recoverable*, not for the clamp to be reverted.
- **`_KNOWN_UNSTYLED` was emptied in the same commit as the CSS**, and the cap raise landed in all three sibling tests with each file's historical rationale byte-preserved — the exact mistake m7's rectify had to catch, avoided deliberately this time.

Severity counts: C0 H1 M7 L2

## Recommended rectification order

H1, M2, M3, M1, M4, M5, M7, M6, L1, L2

Rationale for the ordering: H1 first because it is the only finding that removes operator
capability. M2 and M3 next because they are one-attribute and one-element markup edits in the
same fragment builder H1 already reopens — fix them in the same pass or pay the cost twice.
M1 before M4/M5 because it is the one whose blast radius grows with every milestone that
consumes the token. M5 and M7 are both one-string copy edits and can ride any commit. M6 is a
judgment call about H3 fidelity and is legitimately deferrable if the rectifier disagrees with
the reading. L1 and L2 are cheap enough to fold into whichever rule is already being edited.
