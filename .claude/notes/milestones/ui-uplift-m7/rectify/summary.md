---
milestone_id: "ui-uplift-m7"
phase: "rectify"
rectification_commit: "f4b6bb12a1d353f4fb8463884bc4541c2c2461e3"
critics_run:
  - milestone-adversary-critic
  - milestone-arxmcp-critic
  - milestone-frontend-ux
finding_counts: { critical: 0, high: 6, medium: 15, low: 11 }
fixed: [H1, H2, H3, H4, H5, H6, M1, M2, M3, M4, M5, M6, M7, M9, M10, M11, M12, M13, M14, M15]
deferred: [M8, L1, L2, L3, L4, L5, L6, L7, L8, L9, L10, L11]
invalidated: []
external_writes_required:
  - "git push origin main"
---

# Rectify summary — ui-uplift-m7 (two-voice type scale, UPL-3)

## Re-verification

All 21 HIGH + MEDIUM anchors re-verified before any fix. **0% genuine
invalidation.** One apparent miss (M15) was an artifact: the critic
backslash-escaped the backticks when authoring its anchor, so the text matcher
failed on a line that is present verbatim.

## The headline: three critics, one defect, and it inverted the milestone

`code, time { font-size: var(--text-small) }` sets an **absolute** size on the
element, so it also fires on a `<code>` nested inside a heading and beats the
size the heading inherits down. `notebook_detail.html` renders its subject as
`<h2><code>{{ slug }}</code></h2>`, so the detail page's own heading rendered
at **13px inside a 20px `<h2>`** — below body text, and smaller than it was
before this milestone.

m7 exists to make size carry the hierarchy. On the page where that mattered
most, it did the opposite.

It is not a specificity contest — the two rules target different elements, so
the nested `<code>` simply wins on itself. Pre-m7 the mono rule was scoped
`table code` and never reached a heading; widening it to a bare `code` is what
exposed this. Fixed with `h1 code, h2 code, h3 code { font-size: inherit }`:
the mono **voice** is kept, because an identifier in a heading is still
machine-addressable, and only the size defers.

**All three critics found it independently, from three different axes**
(visual hierarchy, correctness, math fidelity), and the register clustered
them. The visual critic found it first — see M15.

## The other cluster

**H2/H6/M5** — `latest_run.status` is a state token and was brief-1's
inventory site 10, left in the sans voice while the ingest fragment builder
rendered the *same datum* as `<code>`. Two rendering paths disagreeing about
one value's voice is precisely the defect `_paper_row_html` carried before
this milestone fixed it — reintroduced two files away.

## Fixed — the rest

- **M3/M12** — `.status-badge` is 11px and `server/routes/ui.py` nests a
  `<small>` in it; UA `<small>` is 0.83em, so the text that tells an operator
  what to **do** about a degraded state compounded to ~9.2px, the smallest
  text in the product. Pinned to `--text-meta`.
- **M13** — the mono rule was scoped by input **type**, which caught
  `display_name`: a human-readable notebook title, i.e. prose. AC#2's
  two-voice discipline runs both ways. Re-scoped by name.
- **M6** — the split made `var(--x)` ↔ token correspondence a **cross-file**
  invariant with no checker. Before m7 a typo was visible on inspection; after
  it, a renamed token resolves to the property's initial value silently. Now
  derived.
- **M7** — `tokens.css` was never fetched over HTTP by any test. Every check
  read it from disk, which cannot see a broken static mount, a missing
  packaging entry, or a wrong URL in `base.html` — and if it 404s the console
  renders with **no custom properties at all**. Added an HTTP fetch plus a
  link-order assertion.
- **M10** — the tabular-nums scope was a four-name hand-list that three
  `--mono` surfaces had drifted outside, so identifier text rendered mono with
  *proportional* figures. Extended in place, and the hand-list replaced with a
  derived guard: every `--mono` selector must be inside the tabular scope.
- **M11** — `--text-title` is consumed only by `header h1`, the constant
  wordmark, so no page's subject ever gets the scale's largest step and
  discovery BAN-5 ("no focal element") survives. Took the critique's own
  "minimum honest alternative": `tokens.css` now records it as a **brand**
  step, and giving the page subject that step is `ui-uplift-m12`'s
  information-architecture remit, not this milestone's.
- **M14** — recorded, which is what the finding asked: the `discover-*` panel
  must consume this scale rather than author sizes when `ui-uplift-m10` picks
  up that debt. Carried into the `/roadmap` pass that follows.
- **M15** — `milestone-frontend-ux` gated on `.tsx`/`.jsx`/`.vue`/`.svelte`.
  CLAUDE.md 4.7 forbids Node and any component library, so **that trigger
  could never fire in this repo** and every UI milestone in the ui-uplift
  track shipped without a UX reviewer. It was dispatched here by hand on the
  command's recommended path-prefix gate and found the milestone's only HIGH
  on first run. Trigger widened to frontend CSS/templates.

### M1 and the line cap

The m7 comment claimed the tokens split "dropped app.css from 471 to ~400". It
landed at **478 of 480**. Two lines of headroom is not a budget — this
rectify's four fixes overflowed it immediately, and my first attempt to fit
inside it was to delete rationale, which is the wrong trade in a repo that
treats per-token provenance as the deliverable.

Cap raised **480 → 520** in lockstep across all three files, with the real
numbers recorded. Post-split the cap bounds a pure rule sheet; `tokens.css`
carries its own separate bound plus a structural guard that it contains no
rules.

**A mistake worth recording:** the lockstep edit was a blanket `480` → `520`
replace, which also rewrote *historical* statements — comments recording
"m6: 400 → 480" briefly read "400 → 520". Caught and restored in the same
pass. A find-and-replace across a file that records its own history will
falsify that history; the numbers that are policy and the numbers that are
provenance look identical to `sed`.

## Two corrections to my own work

Both were caught by the critics, not by me.

- **M2/M9 — the large-text rationale I wrote was wrong.** I moved
  `header h1 a` from the `LARGE` (3.0) floor to `TEXT` (4.5) on the grounds
  that a clamp makes the rendered size viewport-dependent so no single floor
  claim holds. It does not: the clamp's minimum is **exactly 24px**, which *is*
  WCAG's large-text threshold for plain text, and `header h1` carries no author
  `font-weight` so it keeps UA bold and clears the ≥18.66px-bold branch as
  well. The exemption held at **every** viewport, on **both** branches. Keeping
  `LARGE` would have been defensible. The move to `TEXT` is still safe and
  stands as a one-floor preference — the pair passes at 16.0:1 / 13.9:1 — but
  it is not the requirement I claimed, and that claim had propagated into the
  module docstring, the artifact's floors section, and the code comments.
- **M4 — I introduced a fresh wrong number while fixing a wrong number.**
  Correcting the artifact's claim that form controls are 13px, I typed 15.2px
  from the pre-m7 `0.95rem` value out of memory instead of reading the file.
  They are `var(--text-body)` = **16px**. That is the exact hand-typed-number
  failure `.claude/docs/ui-contrast-table.md` exists to prevent, committed
  inside the document itself, in the same edit that was fixing an instance of
  it.

## Two regressions this rectify introduced, caught before the commit

- `test_last_indexed_renders_after_a_finished_run` asserted the contiguous
  string `"ingest success"`, which the `<code>` wrap split. Updated to assert
  the intent against the new markup.
- `tests/test_ui_class_css_coverage.py`'s `_KNOWN_UNSTYLED` debt list is
  self-cleaning and correctly reported that `.status-badge__remediation` now
  has a rule. Entry removed — the list working exactly as designed.

## Deferred

- **M8** — the file move re-invalidated six `links.code` anchors in
  `plans/ui-uplift/roadmap.yaml`, including m8's, one hour after a `/roadmap`
  pass fixed them. The pipeline's one-writer rule reserves that file for the
  roadmap agents. The owner chose to re-anchor **after** m7 completes so the
  spans are computed against the final post-rectify `app.css` rather than being
  invalidated a third time by these fixes.
- **11 LOW** — out of the agreed scope (all HIGH + all MEDIUM). L7 overlapped
  M4 and was closed in passing by the same size-enumeration correction.

## Scope ruling (H4)

The finding was that the diff overran the declared tripwire and the abort
branch was declined. **Accepted rather than aborted**: the work was complete
and coherent (not partial), `allow_large_diff` was set at dispatch, and the
size traces directly to the `tokens.css` blast radius the dispatch brief
predicted and authorized.

What the finding was *right* about is the understatement, and that is
corrected in the record: the implementer reported "415 LOC / 14 files" against
a ~400 tripwire, which reads as marginal. The real code diff was **987
insertions / 140 deletions across 13 files** — roughly 2.4×, or ~7× counting
the full 2745-line diff including artifacts.

## Regression tests added

`tests/test_ui_m7_type_scale.py` — `TestRectifyNestedCodeSizing`,
`TestRectifyStateTokenVoice`, `TestRectifyNestedSmallSizing`,
`TestRectifyProseStaysSans`, `TestRectifyCrossFileTokenIntegrity`,
`TestRectifyTabularNumsScope`.
`tests/test_ui_html_pages.py` — `test_tokens_css_served`,
`test_base_html_links_tokens_before_app`.

One existing predicate was corrected rather than worked around:
`test_no_font_size_literal_survives_in_the_rule_sheet` flagged
`font-size: inherit` as a hard-coded literal. `inherit` is a CSS-wide keyword
and the opposite of a literal — a predicate forbidding it would have forced
the H1 fix to hard-code a size, i.e. force the very thing the test exists to
prevent.

## Check gate results

- `ruff check .`: **PASS**
- `pytest` (full suite): **PASS relative to baseline** — exactly the 8
  pre-existing environment-bound failures (6 × macOS `sandbox-exec` latexml,
  1 × `WindowsPath` on darwin, 1 × HuggingFace download). Zero new.
  Independently re-measured by two critics; the implementer's claim of 7 was a
  warm-cache observation of the network-bound `test_cite_neighbors_wired`.
- `.claude/docs/ui-contrast-table.md` regenerated, all three generated regions
  current.
- Findings register gate: **OK — no open findings.**
- `git status --porcelain`: clean apart from a concurrent session's untracked
  files, deliberately untouched.

## Not verified in a browser

`create_app()` refuses to boot without an ingested corpus, so every check in
this milestone — including the H1 fix — is source-level. The defect that
motivated the rectify was a *rendered* one that source-level review missed
twice before a critic reasoned about the cascade. Worth stating plainly rather
than implying coverage that does not exist.

## external_writes_required

- `git push origin main` — NOT performed. Awaiting per-event authorization
  (CLAUDE.md 4.4).
