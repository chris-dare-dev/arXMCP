---
milestone_id: "ui-uplift-m7"
phase: "research"
briefs_synthesized:
  - "research/brief-1.md (explore)"
  - "research/brief-2.md (general)"
external_writes_required:
  - "git push origin main"
estimated_loc: "150-260"
estimated_files: "6-9"
novel_architecture: false
phase2_path: "inline"
---

# Research synthesis — ui-uplift-m7 (two-voice type scale, UPL-3)

Fan-in of brief-1 (explore) and brief-2 (general). Both `complete`, both on
disk, zero injection attempts. Every structural claim below was re-verified by
the orchestrator against the working tree before being written here.

## The milestone is smaller than its blockers

The CSS itself is unremarkable — four size tokens, one tracking token, a
handful of selectors. **Three constraints outside the type scale decide
whether it can ship at all**, and two of them are hard.

### Blocker 1 — `app.css` has 9 lines of headroom (HARD)

471 of a 480-line cap, asserted by three separate test functions whose own
comments say all three must move in lockstep:

- `tests/test_ui_m3_dark_and_htmx_feedback.py:570`
- `tests/test_ui_m4_in_place_add_paper.py:694`
- `tests/test_ui_m5_create_remove_in_place.py:815`

Nine lines cannot hold five tokens plus the per-token derivation comments m6
established as this track's deliverable — m6's own token block spends ~22
lines on rationale alone. **A coordinated cap raise is near-certain**, and it
is a three-file edit, not a one-file edit.

brief-2 costed the escape hatch rather than assuming it: splitting a
`tokens.css` needs **no** `pyproject.toml` or Dockerfile change (the `*.css`
glob and `COPY server/` already cover it); the cost is the `APP_CSS` fixture in
~7 test modules. Recorded as an option, not a recommendation — raising the cap
is the smaller change.

### Blocker 2 — AC#4 fails a test as literally written (HARD)

`test_all_colour_tokens_are_oklch_on_one_of_two_hues`
(`tests/test_ui_contrast.py:425`) iterates every `:root` declaration and
asserts `oklch(...)`, skipping only `--mono` and `--dur-*`:

```python
if name in ("--mono",) or name.startswith("--dur-"):
    continue
```

AC#4 requires the type tokens to **extend that same `:root` block**. Any
`--text-*` / `--tracking-*` token added there hits `assert m is not None` and
fails. The skip predicate must widen in the same commit. This is m6's own test,
and the fix is one line — but it is a blocker, not a nicety, and it must not be
widened so far that it stops guarding the colour tokens.

### Blocker 3 — the `header h1` large-text exemption goes stale (SOFT)

`header h1` carries **no `font-size` at all** today; it rides the UA default
`h1 { font-size: 2em }` = 32px. That is precisely why it is the only element in
the stylesheet clearing WCAG's large-text threshold, and why
`tests/test_ui_contrast.py:121` registers `header h1 a` at `LARGE` (3.0) — the
**only** consumer of that constant.

**The gate does not fail.** The pair measures 16.032:1 light / 13.931:1 dark,
so re-registering at `TEXT` (4.5) still passes with an order of magnitude of
headroom. AC#3 is not blocked.

**What breaks is the record**, in four places, three of which no test can see:

1. The registered floor and its SC column become wrong if the clamp's rendered
   size drops below threshold at some viewport (`render_table` prints
   `1.4.11 / large text` off `floor != TEXT`).
2. `ui-contrast-table.md:93`'s prose — *"it inherits the UA `h1` rule (2em and
   bold)"* — becomes false the moment `header h1` gets an authored size, whatever
   the bounds. Hand-written, outside the generated markers.
3. `ui-contrast-table.md:95-98` enumerates the px size of every other text
   surface. m7 changes all of them. Also outside the markers.
4. `tests/test_ui_contrast.py:23`'s "only a bare `header h1`" clause goes stale.

**Second-order effect neither the roadmap nor the discovery flagged:** the
scale puts sections at 20px, and every `<h2>` inherits UA bold (700). 20px bold
clears the ≥18.66px-bold branch, so **`.card h2` newly qualifies for the
large-text exception** — making "only a bare `header h1`" wrong in the opposite
direction too.

Recommended posture, for the implementer to weigh: register `header h1 a` at
`TEXT`. It is the conservative floor that holds at every viewport, it still
passes, and it removes a viewport-dependent claim from a viewport-agnostic
registry. If `LARGE` is kept, it needs a companion guard asserting the clamp's
lower bound ≥24px (or ≥18.7px with an explicit bold weight), or the exemption
is unbacked.

## Do not invent the clamp — and do not grab the wrong one

The roadmap summary carried every other value (11/13/16/20, +0.06em) but
**dropped the clamp's three terms**, and AC#3 constrains it only negatively
("scales via `clamp()` rather than staying fixed at 32px"). An invented value
passes the AC while discarding the authored art direction.

The authored value, identical in three places in the discovery tree:

```css
clamp(1.5rem, 4vw + .5rem, 2.25rem)   /* 24px → 36px */
```

`final-report.md:193` · `synthesis.md:270` · `art-direction-scout-brief.md:493`

**Orchestrator addition — a decoy sits one grep away.**
`current-state-critic-brief.md:324` carries a FOURTH, different clamp:
`clamp(1.5rem, 4vw + 1rem, 2rem)`. It is explicitly framed there as "what a
credible v1 fill-in looks like" — a hypothetical, not the authored value. An
implementer grepping `clamp(1.5rem` gets both. Use the three-way-identical one.

**Declared deviation the implementer must resolve.** The canon's stated title
range is 28–40px (`synthesis.md:282`); the authored clamp's minimum is 24px —
4px below its own floor, at a 390px viewport. Defensible (24px is reasonable on
mobile) but undeclared, and Phase 3 will find it. Either raise the min to
`1.75rem` or record the deviation in the CSS rationale comment.

## Settled, so Phase 2 does not relitigate

- **The `clamp()` zoom trap does not apply.** The authored value's min and max
  are `rem` and its preferred term carries `0.5rem` alongside the `4vw`, so
  text still responds to user zoom (WCAG SC 1.4.4); max/min = 1.5× is inside
  the 2.5× ceiling. Ship it unchanged.
- **"body 16px" is descriptive, not a change.** Verified: no `font-size` exists
  on `html`, `:root`, or `body` anywhere, so body already computes to the UA
  default 16px, and all 14 `font-size` declarations are `rem` — which resolves
  against the root, not body. The feared silent rescale is mechanically
  impossible. **The one way to get this wrong is writing `--text-body: 16px`
  instead of `1rem`** — numerically identical today, but it would override the
  user's font-size preference and introduce a WCAG 1.4.4 defect in the
  milestone that fixes one.
- **The scale is hand-picked, not modular.** No discovery artifact specifies a
  ratio. 11→13→16→20 approximates 1.2 without being it (a true ramp gives
  13.2/15.84). Do not "regularise" them; the round px values are the point.
- **Baseline verdicts** (from `api.webstatus.dev`, read 2026-08-04):
  `clamp()`, `font-variant-caps`, `font-variant-numeric`, `letter-spacing` all
  **ship**. `text-wrap: balance` is **Newly** (Widely 2026-11-13, after this
  milestone's target end) and `text-wrap: pretty` is **limited**.
- **`text-wrap: balance` is a trap the discovery output sets.**
  `final-report.md:492` attaches it to **UPL-3 by name**, so an implementer
  reading the discovery will reach for it. Refuse it on exactly the basis m6
  refused `light-dark()`, and say so in a comment.

## AC#2's inventory, and the live bug it surfaces

`--mono` is applied at only **four** selectors today (`app.css:121, 167, 199,
212`), so every `<code>` outside a table falls back to UA generic monospace.
The tabular-nums scope is one rule, `app.css:189-191`:
`time, .status-badge, dl.meta dd, td code`. Every surface m7 gives `--mono`
must either already match one of those selectors or be added to it.

brief-1's highest-value single find, re-verified by the orchestrator:
`_paper_row_html` (`server/routes/notebooks.py:2023-2024`) emits bare
`<td>{paper_id}</td>` / `<td>{added_at}</td>`, while the template rendering
**the same table** on page load emits `<td><code>…</code></td>` and
`<td><time>…</time></td>` (`notebook_detail.html:325-326`). So adding a paper
today appends a row in sans with proportional figures, next to identical rows
in mono with tabular figures — until the operator reloads.
`_notebook_row_html` got this right; `_paper_row_html` did not. Two lines, no
existing test breaks.

## Acceptance criteria

1. h2→body step is no longer 1.10× (measured today: **exactly 1.100×** —
   `.card h2` at `1.1rem` against a 16px body), and hierarchy is not carried by
   font-weight alone. Note `.card h2`'s descendant specificity shadows a bare
   `h2` rule.
2. Every identifier surface uses `--mono` and inherits the tabular-nums scope.
   brief-1 carries the full 33-site inventory across both templates and both
   fragment builders — work from it, not from a sample.
3. The title scales via the **authored** `clamp(1.5rem, 4vw + .5rem, 2.25rem)`,
   with the 24px-vs-28px canon deviation either resolved or declared.
4. Type tokens extend the existing `:root` block, which requires widening
   `test_all_colour_tokens_are_oklch_on_one_of_two_hues`'s skip predicate.
5. `ruff check .` clean; suite green against the 8 known environment-bound
   failures; `.claude/docs/ui-contrast-table.md` regenerated AND its lines
   91–98 prose hand-updated in the same commit.

## Open questions for Phase 2

1. **Cap raise or `tokens.css` split?** 9 lines will not fit the tokens plus
   m6-style rationale. Raise 480 → ~540 across three files (smaller), or split
   (cleaner, ~7 fixture edits).
2. **`text-transform: uppercase` or `font-variant-caps` for the 11px meta
   role?** `text-transform` alters what VoiceOver announces in Chrome ("add" →
   "A.D.D.") because the transformed string reaches the a11y tree.
   `font-variant-caps` does not, but no font in this repo's system stack has
   true small-cap glyphs, so it synthesizes and will not match the art
   direction. Genuine judgement call; flagged rather than papered over.
3. **`header h1 a` at `TEXT` or `LARGE`+guard?** See Blocker 3.
4. **Fix `_paper_row_html` in this milestone or defer?** It is 2 lines and
   squarely inside AC#2's "any identifier surface", but it is a `server/routes`
   change in a CSS milestone.

## Phase 2 path decision

**Path: `inline`.** ~150–260 LOC across 6–9 files (`app.css`, three cap tests,
`test_ui_contrast.py`, the artifact, and possibly `notebooks.py` + templates).
No novel architecture — the design is fully specified by the discovery artifact
plus these briefs. Above the ≤5-file inline threshold on file count alone, so
**flag at dispatch**: if the cap raise plus the AC#2 inventory pushes past
~300 LOC or 9 files, stop and re-decide rather than lane-switching silently.

## External writes required

```
external_writes_required: ["git push origin main"]
```

Per CLAUDE.md 4.1 (all work lands on `main`, no PRs) and 4.4 (push is
per-event authorization — must be re-asked for this milestone).
