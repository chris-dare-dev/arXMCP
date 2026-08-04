# Critique — ui-uplift-m7 — milestone-frontend-ux

**Critic:** milestone-frontend-ux
**Commit range:** 2c6588446351f5d947d5c1dc366a036c661f6dc0..a825898616dd8368b57c57adc4802d01cc72baa3
**Diff stats:** 23 files, 2934 LOC (2745 insertions, 189 deletions)
**Critique format version:** 1.0

**Dispatch note.** This agent's frontmatter trigger is a `.tsx`/`.jsx`/`.vue`/`.svelte`
component file. This repo has none and never will (CLAUDE.md §4.7). I was dispatched on
the secondary gate — the diff touches `server/frontend/static/` and
`server/frontend/templates/` — and reviewed accordingly. I judge the trigger definition
itself to be a defect and record it as M5.

**Review method — stated plainly.** This is a **source-level review only. I did not see
this render.** `create_app()` refuses to boot without an ingested corpus, so there is no
dev server available in this worktree, exactly as the implement synthesis already
declares at its "No browser verification" bullet. Every size claim below is derived by
reading the cascade in `server/frontend/static/app.css` + `tokens.css` against the three
templates and the five fragment builders in `server/routes/`, not by measuring pixels.
Where I assert a computed size I name the rules that produce it so the rectifier can
check my arithmetic rather than trust it.

## Verdict

SHIP-WITH-FIXES

The scale itself is well-authored — the tokens are `rem`, the micro-caps rule is scoped
correctly, the Baseline refusals held, and `tokens.css` is the most honestly-commented
file in the product. But the new `code, time` rule sets an **absolute** font-size, and on
`notebook_detail.html:9` that makes the page's own subject render at 13px inside a 20px
heading — the detail page's title is now smaller than its table body text, which inverts
the exact hierarchy AC#1 exists to create. That plus one enumerated inventory site left
in the wrong voice are cheap, surgical fixes; nothing here argues against the milestone's
direction.

## Executive summary

- [HIGH] `code, time { font-size: var(--text-small) }` is an absolute value, so the
  `<h2><code>slug</code></h2>` on the notebook detail page renders at **13px inside a
  20px heading** — the page subject is now smaller than the body text around it, and
  smaller than it was before m7.
- [HIGH] `latest_run.status` at `notebook_detail.html:71` is a state token still in the
  sans voice. brief-1's own inventory lists it as site #10; m7 fixed sites 28–31 (the
  same token in the ingest fragment) and left this one, so the identical value renders in
  two different voices ~200px apart on one page.
- [MEDIUM] The fluid title lands only on the constant site wordmark ("arXMCP notebooks",
  every page). The largest step in the scale is spent on boilerplate while the page
  subject sits at 20px — discovery's BAN-5 "no focal element" is not removed.
- [MEDIUM] `.status-badge__remediation` is a UA `<small>` nested inside the badge; m7
  shrank the badge 12px → 11px, dragging operator remediation text to roughly 9px — the
  smallest text in the product, on the recovery path.
- [MEDIUM] Prose in mono: `input[type="text"]` puts the `display_name` field in `--mono`,
  contradicting m7's own textarea reasoning ("topic text is prose, not an identifier").
- [MEDIUM] The discover-results panel gets no hierarchy at all — candidate title and
  abstract both render at 16px, typographically identical.
- [MEDIUM] This agent's trigger definition can never fire in this repo, leaving the most
  visual milestone track without a UX gate by default.
- [LOW] Two text surfaces remain off the token scale entirely (`.card .empty`, `footer >
  small`), and the SC 1.4.4 comment overstates the mid-band case.

## Findings

**H1 — Mono `<code>` shrinks the detail page's own heading to 13px** (HIGH)

**Where:** `server/frontend/static/app.css:195`
**Anchor:** `code, time { font-family: var(--mono); f`
**What:** The new rule sets an absolute `font-size: var(--text-small)` (13px), and because `notebook_detail.html:9` is `<h2><code>{{ notebook.slug }}</code></h2>`, the `<code>` child overrides the inherited 20px `.card h2` size and renders the notebook identity — the page's entire subject — at 13px, smaller than the 13px table text it sits above and smaller than the ~15px it rendered at before m7 (when it fell through to UA generic monospace at ~0.85em of a 17.6px heading).
**Why it matters:** The milestone's headline claim is that "size carries the hierarchy"; on the console's primary working page the size signal now points the wrong way, so the operator's first eye-stop is the boilerplate wordmark rather than which notebook they are looking at.
**Proposed fix:** Make the identifier step relative rather than absolute so it composes with whatever context it lands in, or add one contextual override. Cheapest correct patch is a single extra rule after `:195`: `.card h2 code { font-size: inherit; }` — the heading keeps `--text-section`, the mono *face* still marks it as an identifier, and every other `<code>` in the product is unaffected. The more general alternative is `code, time { font-size: 0.8125em }` (em, not rem), which self-scales in every context but re-opens the "monospace renders smaller" quirk the m7 comment at `:188-191` was closing — prefer the scoped override.
**Regression-guard:** Extend `tests/test_ui_m7_type_scale.py::TestAC2IdentifierSurfaces` with a test asserting that no rule gives a `<code>` inside a heading a smaller computed size than its heading — concretely, assert an `h2 code`-scoped rule exists whose `font-size` is `inherit`/`1em`, and pair it with a negative assertion that `.card h2` still carries `var(--text-section)` so the two cannot silently diverge.
**Source critic:** milestone-frontend-ux
**Source axis:** Visual hierarchy

**H2 — State token `latest_run.status` left in the sans voice** (HIGH)

**Where:** `server/frontend/templates/notebook_detail.html:71`
**Anchor:** `<span class="hint">(ingest {{ latest_run`
**What:** AC#2 requires `--mono` on every id, path, slug, timestamp, corpus version and state token; this renders the ingest run's state token as bare prose inside `<span class="hint">`, so it stays sans at 13px while m7 wrapped the identical values (`running` / `success` / `failed`) in `<code>` in `_ingest_status_fragment` further down the same page.
**Why it matters:** brief-1 §2 enumerates this as inventory site #10 with "`--mono` today: NO", so it is a known-and-skipped site rather than an oversight the inventory missed — and the result is one value class rendering in two voices on one screen, which is precisely the inconsistency the two-voice split exists to end.
**Proposed fix:** Wrap the interpolation in `<code>`, matching the fragment builder: `<span class="hint">(ingest <code>{{ latest_run.status }}</code>)</span>`. The surrounding "(ingest …)" prose stays sans, which is the same split `_ingest_status_fragment` already implements. One line; no CSS change, since `code` already carries `--mono` and tabular-nums.
**Regression-guard:** Add a test asserting the template and `_ingest_status_fragment` agree on the wrapper for the run-state token — the same "fragment and template must agree" invariant `test_paper_row_fragment_agrees_with_the_template_it_appends_to` already encodes for D4, applied to the status token.
**Source critic:** milestone-frontend-ux
**Source axis:** Design-token / design-system discipline

**M1 — The fluid title is spent on the constant site wordmark** (MEDIUM)

**Where:** `server/frontend/templates/base.html:72`
**Anchor:** `<h1><a href="/ui/">arXMCP notebooks</a><`
**What:** `--text-title` (24→36px, the scale's largest step) is applied only to `header h1`, which is the string "arXMCP notebooks" on *every* page; no page's actual subject ever receives it, so on `notebook_detail.html` a 36px boilerplate wordmark sits above a 20px `<h2>` (13px in practice — see H1) carrying the notebook identity.
**Why it matters:** The discovery listed BAN-5 "no focal element" under "must be removed" and adopted D-1, whose thesis is that the console shows the corpus first; making the brand the single largest element on every page leaves BAN-5 in place and reads as the "default stack" tell the milestone is meant to retire.
**Proposed fix:** Give `base.html` a `{% block page_title %}` inside `<header>` that defaults to the wordmark and is overridden on the detail page with the notebook slug, then move `--text-title` onto that block and drop `header h1` to `--text-section`. If restructuring the header is out of appetite for this milestone, the minimum honest alternative is to state in `tokens.css` that `--text-title` is a brand step rather than a page-title step, so the canon-deviation note is not describing a role the token does not actually play.
**Regression-guard:** Optional at MEDIUM.
**Source critic:** milestone-frontend-ux
**Source axis:** Visual hierarchy

**M2 — Badge remediation text drops to roughly 9px** (MEDIUM)

**Where:** `server/routes/ui.py:336`
**Anchor:** `f'<small class="status-badge__remediatio`
**What:** The remediation block is a `<small>` nested inside `<span class="status-badge">`; the badge carries an absolute `--text-meta` (11px) and `.status-badge__remediation` has no CSS rule of its own, so the UA's `small { font-size: smaller }` computes it to roughly 8.8–9.2px — and m7 moved the badge from `0.75rem` (12px) to `--text-meta` (11px), so this diff made it about 0.8px smaller than it was.
**Why it matters:** This block names the failing check and the `make` command to heal it — it is the text an operator reads specifically when the system is degraded, and it is now the smallest text in the product, set below the scale's own floor by a UA rule rather than by any authored decision.
**Proposed fix:** Give the class an explicit step so it stops riding the UA `smaller` keyword — `.status-badge__remediation { font-size: var(--text-small); display: block; }` puts it at 13px on the scale and stacks it under the badge label instead of inline. Note this requires deleting `status-badge__remediation` from `_KNOWN_UNSTYLED` in `tests/test_ui_class_css_coverage.py` in the same commit, which is exactly the shrink that list is designed for.
**Regression-guard:** Optional at MEDIUM.
**Source critic:** milestone-frontend-ux
**Source axis:** Accessibility

**M3 — Prose rendered in the mono voice on the display-name inputs** (MEDIUM)

**Where:** `server/frontend/static/app.css:92`
**Anchor:** `input[type="text"], input[type="url"] { f`
**What:** The selector is too coarse for the two-voice rule: it correctly puts `name="slug"` and `name="paper_id"` in `--mono`, but it also catches `name="display_name"` on `index.html:36` and `notebook_detail.html:41`, which is free prose ("Bridgeland stability conditions") typed and read in monospace.
**Why it matters:** This is the second failure direction the two-voice split is supposed to close, and m7 explicitly reasoned about it in the other case — `app.css:100` justifies excluding `textarea` because "topic text is prose, not an identifier" — so the same value class is being treated two different ways within one stylesheet.
**Proposed fix:** Scope the mono voice to the identifier inputs by name rather than by type: replace the selector with `input[name="slug"], input[name="paper_id"], input[type="url"]` and let `display_name` inherit the sans body font. The rule pre-dates m7, but AC#2 is the audit that owns it.
**Regression-guard:** Optional at MEDIUM.
**Source critic:** milestone-frontend-ux
**Source axis:** Design-token / design-system discipline

**M4 — The discover-results panel receives no hierarchy from the scale** (MEDIUM)

**Where:** `server/routes/notebooks.py:732`
**Anchor:** `f'<p class="discover-title">{html.escape`
**What:** A discovered candidate's title and its abstract are both bare `<p>` elements with no styled class, so both render at the 16px body step and are typographically indistinguishable; only `.discover-meta`'s inner `<code>`/`<time>` pick up anything from m7, via the element rules.
**Why it matters:** This is the one surface in the console that is a list of *content* rather than a list of records, so it is where a type scale should be most visible — and it is the clearest answer to "where does the page still look uniform" after this milestone.
**Proposed fix:** When `ui-uplift-m10` picks up the `discover-*` half of the BAN-R2 debt, it should consume this scale rather than author sizes: `.discover-title { font-size: var(--text-section); line-height: 1.25; }` and `.discover-abstract { font-size: var(--text-small); }`. Recorded here so m10 inherits the constraint; m7 correctly left the classes alone rather than colliding with `_KNOWN_UNSTYLED`.
**Regression-guard:** Optional at MEDIUM.
**Source critic:** milestone-frontend-ux
**Source axis:** Visual hierarchy

**M5 — This critic's trigger definition can never fire in this repo** (MEDIUM)

**Where:** `.claude/agents/milestone-frontend-ux.md:6`
**Anchor:** `  a \`.tsx\`, \`.jsx\`, \`.vue\`, or \`.svelte\` fi`
**What:** The frontmatter fires only on `.tsx` / `.jsx` / `.vue` / `.svelte` component files, and Step 0 instructs the agent to return `not-applicable` when the diff contains none — but CLAUDE.md §4.7 bars Node and any build chain, so this repo has zero such files by construction and will never have one.
**Why it matters:** Taken literally the gate is unreachable here, so every frontend milestone in the `ui-uplift` / `ui-attractive-polish` track would ship with no UX review unless an orchestrator overrides the trigger by hand, as happened for this dispatch.
**Proposed fix:** Widen the trigger to include server-rendered frontend surfaces — add `.css`, and `.html` / `.jinja` / `.j2` under a `frontend/` or `templates/` path prefix — and amend the Step 0 exit-fast check to match, so the "do not manufacture findings" guard still holds for genuinely backend diffs. Keeping the path-prefix requirement preserves the original intent of not firing on unrelated `.html` fixtures or docs.
**Regression-guard:** Optional at MEDIUM.
**Source critic:** milestone-frontend-ux
**Source axis:** Design-token / design-system discipline

**L1 — Two text surfaces remain off the token scale** (LOW)

**Where:** `server/frontend/static/app.css:71`
**Anchor:** `.card .empty { color: #666; font-style:`
**What:** `.card .empty` has no `font-size` at all, so the empty-state line renders at the 16px body step — larger than the 13px `.hint` above it and the 13px table rows it replaces; `footer > small` in `base.html:83` likewise has no authored size and rides the UA `small` keyword to ~12.8px.
**Why it matters:** The milestone's claim is that all 19 previously-untokenised `font-size` declarations now reference a token, which is true — but these two surfaces are sized by the UA rather than by a *declaration*, so they sit outside both the claim and the guard `test_no_font_size_literal_survives_in_the_rule_sheet` provides.
**Proposed fix:** Add `font-size: var(--text-small)` to `.card .empty` so an empty table reads as quieter than a full one rather than louder, and add a `footer { font-size: var(--text-small) }` rule so the footer stops depending on UA `small` scaling. Both are one-line additions inside the existing 480-line cap.
**Regression-guard:** Optional at LOW.
**Source critic:** milestone-frontend-ux
**Source axis:** Design-token / design-system discipline

**L2 — The SC 1.4.4 comment is stronger than the mid-band behaviour** (LOW)

**Where:** `server/frontend/static/tokens.css:90`
**Anchor:** `     viewport and at 36px above 700px. I`
**What:** The comment states the clamp "clears SC 1.4.4 on both counts"; that is accurate wherever the clamp is pinned to its `rem` min or max (below 400px and above 700px, which is every real operator viewport), but in the 400–700px band the preferred term governs and a 200% text-size request yields roughly 1.29× growth, not 2×.
**Why it matters:** The construction is the correct and commonly-recommended mitigation, and `test_clamp_satisfies_the_resize_text_criterion` checks exactly the right structural properties — but the unqualified prose will be trusted verbatim by the next reader, and this token block is otherwise scrupulous about stating where a claim stops.
**Proposed fix:** Qualify the sentence — note that the guarantee is carried by the `rem` bounds, which govern at every viewport outside the 400–700px fluid band, and that inside that band the `0.5rem` term supplies partial rather than full scaling. No value change; the number is right.
**Regression-guard:** Optional at LOW.
**Source critic:** milestone-frontend-ux
**Source axis:** Accessibility

## What was done well

- **The 11px micro-caps constraint holds exactly as specified.** `text-transform:
  uppercase` appears exactly once in the product, on the `th` rule, and every `<th>` in
  both templates is an authored column label ("Slug", "Display name", "Created", "Paper
  ID", "Added", "Preview"). I checked every `<th>` render site in the templates and both
  fragment builders: no identifier, slug, path, timestamp, corpus version, state token or
  operator-supplied string is uppercased anywhere. The VoiceOver initialism cost is
  recorded inline rather than discovered later, `dl.meta dt` was deliberately excluded
  with a stated reason, and `test_micro_caps_role_never_lands_on_an_identifier` enforces
  the constraint structurally rather than by convention. This is the axis I expected to
  produce a finding and it produced none.
- **The tracking ships with the size, not as decoration.** `--tracking-meta: 0.06em` is
  correctly `em` rather than `rem` — it scales with its own element, which is the whole
  point at 11px — and the comment states the actual reason positive tracking is required
  (all-caps removes the ascender/descender word-shape cues), rather than treating it as
  style.
- **The Baseline refusals held under direct temptation.** `text-wrap: balance` is
  attached to UPL-3 by name at `final-report.md:492` and is the obvious reach for a fluid
  title; it appears in the CSS only as a refusal comment citing its 2026-11-13 Widely
  date, on the same basis m6 refused `light-dark()`. `font-variant-caps` was likewise
  considered and rejected for a stated technical reason. Neither feature is declared
  anywhere.
- **Every new size token is `rem`, and the reasoning is right for the right reason.**
  `--text-body: 1rem` is byte-identical to the previous rendering, so writing `16px`
  would have passed every test — the comment explicitly names why `px` would still have
  been wrong (it would override the reader's preference in the milestone whose point is
  that type responds to the reader). Nothing sets a `font-size` on `html`/`:root`/`body`
  beyond the token.
- **The clamp is built correctly for both zoom modes.** Min and max are `rem` so text-only
  zoom and a raised default font size scale them, and the preferred term carries a
  `0.5rem` beside the `4vw` so page zoom does not cancel itself — the pure-`vw` trap that
  breaks SC 1.4.4 is avoided, and the 2.5× max/min ceiling is checked by a test.
- **The canon deviation is declared honestly and guarded.** The 24px minimum sits 4px
  below the canon's own 28px title floor; `tokens.css` states that plainly, states what
  the alternative would cost, and `test_the_canon_deviation_is_declared_not_silent` makes
  the note mandatory *while* the minimum is under 28px — so the declaration cannot be
  quietly dropped without either raising the value or failing.
- **D4 is a genuine bug fix, and the test asserts the right invariant.** `_paper_row_html`
  emitted bare `<td>` while the template rendering the same table emitted
  `<td><code>`/`<td><time>`, so htmx-appended rows rendered sans + proportional beside
  mono + tabular rows until reload. The regression test pins the *agreement* between
  fragment and template rather than either shape alone, which is the invariant that
  actually broke.
- **tabular-nums was extended in place rather than forked.** `td code` widened to bare
  `code` — a strict superset — inside the single existing declaration, with a positive
  assertion that the scope stays exactly one rule. Columns of paper IDs, timestamps, run
  ids and exit codes all align.
- **No information is conveyed by type treatment alone.** The mono voice marks
  machine-addressable values, but in every case the meaning is still carried by the word
  itself or by an adjacent label — the state badge pairs colour with a text label, and
  the ingest fragment keeps "Status:" / "Run #" / "Exit" prose beside the tokens.
- **The implement synthesis declares its own gaps rather than papering over them** — the
  scope overrun, the branching constraint, the corrected 7-vs-8 failure baseline, and
  most relevantly "No browser verification … the 11px `th` micro-caps and the 13px
  identifier step are legibility judgements that deserve one real look on a real screen."
  That last line is correct and is the single most valuable sentence in the artifact.

Severity counts: C0 H2 M5 L2

## Recommended rectification order

H1, H2, M2, M3, M1, M5, M4, L1, L2

H1 and H2 are one-line fixes that close the two places where the scale contradicts
itself; take them first. M2 and M3 are next because both are small, self-contained CSS
edits with no template restructuring. M1 is deliberately ranked after them — it is the
most valuable change on this list but the only one that touches page structure, so it may
be better placed in its own milestone alongside the D-1 header work rather than rectified
inline. M5 is a pipeline-config fix independent of the diff. M4 is a forward constraint
for `ui-uplift-m10` rather than work to do now. L1 and L2 are cheap polish.
