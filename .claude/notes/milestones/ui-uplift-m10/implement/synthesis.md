---
milestone_id: "ui-uplift-m10"
phase: "implement"
status: "complete"
implementation_base: "216aff062f78d44d314b7b33f72d6b836192e0ee"
commits:
  - "0edc12a feat(server): style Discover results (ui-uplift-m10)"
  - "263bdba chore(notes): implementer lessons from ui-uplift-m10"
  - "chore(notes): record ui-uplift-m10 implement synthesis"
branch: "worktree-agent-a4fd5bfa636591d65"
external_writes_required:
  - "git push origin main"
injection_attempts: 0
---

# Implement synthesis — ui-uplift-m10 (UPL-9)

## Built

**AC#1 — title / meta / abstract distinguished, candidates separated.** Built
from discovery H3's five authored rules
(`discover/current-state-critic-brief.md:130-136`), carried onto the m7 scale
rather than pasted — H3's raw `0.8rem` / `0.875rem` predate `--text-small` and
would re-open the untokenised sizes m7 closed.
`server/frontend/static/app.css:213-232`:

- `.discover-list` — `list-style: none; margin: 0; padding: 0`. No `ul`/`ol`/`li`
  rule existed anywhere in the file before this, so the list had been rendering
  at the UA default (disc bullets, 40px indent).
- `.discover-candidate` — `padding: 0.75rem 0` + a `1px solid var(--border)`
  hairline, plus `:last-child { border-bottom: none }` so the ladder does not
  leave a stray rule against the card padding.
- `.discover-title` — `font-weight: 600` and **no** `font-size`. It inherits
  body 16px; the hierarchy is carried on weight, which is what reference lists
  do (brief-2 §3) and what H3 authored.
- `.discover-meta` — mono, `--text-small`, `--fg-muted`.
- `.discover-abstract` — sans, `--text-small`, `--fg` (inherited), truncated.

Chosen deliberately over brief-2's hanging-indent alternative: the hairline is
literally D-1's rule ladder ("the console is one continuous record of account…
rules carry every structure; the box is deleted"), and the discovery authored
the rule version. Recorded here because the next milestone in the track
inherits it as precedent. Ban-list check: no per-row chip (BAN-7), no icon
(BAN-3 — the product's zero-icon state is an asset the discovery names), no
card grid (BAN-2), no state-history strip (UPL-24, killed).

**AC#2 — `.discover-meta` takes `--mono` and inherits tabular-nums.** Both
halves in one edit: `app.css:219` sets `font-family: var(--mono)`, and the
exact selector string `.discover-meta` is appended **in place** to the single
existing tabular-nums rule at `app.css:224-228`. Not a second declaration —
`TestRectifyTabularNumsScope::test_the_tabular_rule_is_still_a_single_declaration`
and `test_tabular_scope_is_one_rule_covering_code_and_time` both fail on two,
and `test_every_mono_surface_inherits_tabular_nums` compares exact selector
strings, so `.discover-candidate .discover-meta` in one and `.discover-meta` in
the other would have been a failure rather than a match. Honest scope note: the
`<code>` and `<time>` children already had both properties; what this adds is
the `·` separator and the `<p>` box, so it makes the rule self-describing — it
does not fix misaligned digits, which were already aligned.

**AC#3 — no fade-in keyframe.** None added; the keyframe count in `app.css` is
unchanged at three (`spin`, `badge-flash`, `row-fade-out`). The premise was
re-verified: `base.html:59` enables `htmx.config.globalViewTransitions`
(reduced-motion-gated) and `app.css` caps `::view-transition-old/new(root)` at
`var(--dur-fast)` = 200ms. Recorded in the stylesheet comment, along with the
second escape brief-1 §6 flagged: `#discover-results` must never take a
`view-transition-name`, which would leave the root group that duration
override covers. The discovery's own `synthesis.md:462` `[MOT-1 fade-in]`
assignment is the overturned side of that argument and was not resurrected.

**AC#4 — NO relevance line shipped, and this is the deliberate outcome.**
The condition AC#4 made it contingent on is false, verified three independent
ways: the arXiv Atom entry element set carries no score, rank, weight or
per-result match explanation in either the `atom:` or `arxiv:` namespace;
`tools/_arxiv_api.py:156-157` pins `sortBy=submittedDate` /
`sortOrder=descending`, so the list is reverse-chronological and even a
positional claim ("top match") would be false; and `DiscoveryCandidate`
(`tools/discover_for_notebook.py:49-52`) is exactly `paper_id`, `title`,
`abstract_head`, `submitted_date` with nowhere to hold one. A per-candidate
"why this matched" string would have to be synthesised in the fragment builder
from nothing — fabricated evidence under CLAUDE.md 4.9, and indistinguishable
from a real one to an operator. The refusal is written into the stylesheet
(this repo writes refusals down — `tokens.css:101-106`, `app.css`'s
select/textarea note) so the next milestone does not re-litigate it from the
NotebookLM pattern the inspiration scout lifted.

**AC#5 — `.status-badge__remediation` finished, not left on m7's size pin.**
`app.css:281-298`. m7's `font-size: var(--text-meta)` met AC#5's letter (a
selector exists, and the coverage test was already green on it) while discovery
H1's actual defect stayed shipped: `<small>` is inline, so the `<br>`-separated
block rendered as a live-measured 491×22px run-on line concatenated onto a
`min-width: 14ch` pill instead of a caption beneath it. Now `display: block`,
`margin-top: 0.25rem`, `line-height: 1.4`, and `color: var(--fg-muted)` to
demote it below the status token it explains — H1's authored fill-in, all four
parts.

**AC#6 — `.topic-block` / `.topic-category` / `.topic-description` each get a
real rule.** `app.css:241-243`. `.topic-category` is styled as a labelled meta
row, never a chip: its value already renders inside `<code>`, so it is an
identifier surface that takes `--mono` + tabular-nums from the element rules.
`.topic-description` stays in the **sans** voice — it is operator prose, and
`TestRectifyProseStaysSans` exists because m7 put prose in the mono voice once.
The comment records that this markup is emitted from two places
(`notebooks.py:621-623` and its byte-identical Jinja twin
`notebook_detail.html:116-118`) and must not drift.

**AC#7 — `_KNOWN_UNSTYLED` is EMPTY.** `tests/test_ui_class_css_coverage.py`.
All 8 remaining entries (3 `topic-*`, 5 `discover-*`) deleted in the same
commit as the CSS, because
`TestKnownUnstyledDebtIsSelfCleaning::test_known_unstyled_entries_are_still_actually_unstyled`
fails the moment a listed class gains a rule. `_DYNAMIC_MODIFIER_ALLOWLIST` is
a structurally different dict (an interpolation a static scan cannot resolve)
and stays. Three m9 doc-drift findings closed while in the file:

- **M3** — the module docstring and `_css_defines_class`'s docstring both
  justified the anywhere-match on the premise that `app.css` "has no bare
  `.foo { }` rules". It has many. Rewritten to the true and load-bearing reason
  (the file mixes bare, compound, element-qualified, comma-grouped and
  `@media`-nested selectors, so selector-position awareness needs real CSS
  parsing; the anywhere-match is a deliberate over-approximation).
- **M5** — the headline claims "every server-emitted CSS class". Scoped
  explicitly: this closes the `server/routes/` half only; Jinja templates are
  still unscanned and eight unstyled template classes remain untracked (m9 L5).
- **M2** — the offender message advertised `_KNOWN_UNSTYLED` as a one-line
  escape hatch. Rewritten to say the list has been empty since m10 and
  re-populating needs a dated reason and an owning milestone.

Stale prose fixed in the same pass: "9 classes … 400-line soft cap" (both
numbers wrong — it was 8, and the cap was 520).

**AC#8 — cap raised 520 → 600 in lockstep, same commit, in all three
siblings.** `test_ui_m3_dark_and_htmx_feedback.py:610-627`,
`test_ui_m4_in_place_add_paper.py:721-730`,
`test_ui_m5_create_remove_in_place.py:825-833`. **Not a blanket replace** —
each file's historical raise notes ("m6: 400 → 480", "m7: kept 480", the m7
rectify's 480 → 520 rationale) are byte-unchanged; only the policy literal and
`test_ui_m5`'s `Cap = 520` policy statement moved, and m10's own reasoning was
appended. That is the exact mistake m7's rectify made and caught. The merits,
argued in full on the m3 test and cross-referenced from m4/m5: the tokens-split
escape hatch those tests name is spent and cannot be re-taken; eight class
rules plus two recorded refusals do not fit 22 lines under any authoring style.
The file lands at **575 of 600** — a 25-line margin, deliberately more than the
2 lines m7 left itself and immediately had to rectify. The file's comment-to-
code ratio after the change is **1.27** (303 comment / 239 code / 34 blank),
above the 1.14 it carried before; no rationale was deleted to buy room, which
is the trade m7's rectify recorded as wrong.

**Owner decision D1 — `--fg-muted` minted.** `tokens.css:47-66` (light) and
`:162` (dark). Derived the way every token in that file was derived, not
eyeballed: OKLCH on brand hue **250°**, at its own mode's `--fg` chroma (0.014
light / 0.008 dark — the muted voice is the same material one lightness step
recessive, not a second family), binary-searched to a target ratio against a
named ground.

- Light `oklch(45.706% 0.014 250)` → `#51585f`, measured **7.015:1** on
  `--card-bg`.
- Dark `oklch(71.512% 0.008 250)` → `#9fa4a8`, measured **7.037:1** on
  `--card-bg`.

Two choices are deliberate and recorded in both the token comment and the
artifact. **Ground is `--card-bg`, not `--bg`**: every consumer renders inside
`<section class="card">` or inside a status pill, and none on the page canvas.
**Target is 7.00:1 (SC 1.4.6, AAA)**, not the 4.5:1 minimum — that is the band
the greys it replaces already occupied (`#555` on the light card measures
7.25:1, so nothing gets lighter), and the AAA headroom is precisely what lets
one token also clear the three status-pill grounds without a per-pill override.
Because it is a token it needs **no** dark-mode remap line in `app.css`'s
hand-listed grey block — which is the trap brief-1 risk 2 named
(`test_dark_block_remaps_tertiary_text_greys` only checks seven *named*
selectors and would not have noticed a new one).

D1's three consequences, all handled in the same commit:

1. `test_all_colour_tokens_are_oklch_on_one_of_two_hues` — satisfied, not
   exempted. `--fg-muted` is `oklch()` on 250 in both modes; no entry was added
   to `NON_COLOUR_TOKEN_NAMES` / `_PREFIXES`.
2. **Pair registry: 91 → 99 rows**, every site `--fg-muted` actually renders in,
   both modes, at the TEXT floor. Two card-ground rows and six status-pill rows.
   The pill rows skip the `ok` pill because `_build_remediation_block` returns
   `""` when `css == "ok"`, and no `--bg` row exists because no consumer sits on
   the canvas — registering a pair that does not render is the same class of
   error as omitting one that does. Tightest new pair: dark `--warn` at
   **5.448:1** against 4.5:1. Zero failures across all 99.
3. `.claude/docs/ui-contrast-table.md` regenerated
   (`python -m tests.test_ui_contrast --update`), **and** its hand-written
   prose outside the generated markers checked and corrected: the token-family
   table gained a `--fg-muted` row plus a derivation paragraph, and the
   per-surface size enumeration now names the four new 13px surfaces and
   `.discover-title`'s deliberate absence of a size step. `"7.00:1"` added to
   the `targets` allow-list in
   `test_no_ratio_is_typed_outside_a_generated_region` (it is a design input,
   not a measurement). The module docstring's hand-typed "67 rendered pairs" —
   stale at 91 before this milestone even opened — was replaced with a pointer
   to the generated Headline rather than a fourth number to rot.

**Owner decision D2 — abstract truncated with `max-height` + `overflow`.**
`app.css:232`. `max-height: 4.5em` against body's inherited `line-height: 1.5`
is exactly three line boxes, so the cut lands on a boundary rather than through
a row of glyphs. `line-clamp` refused: unprefixed is Baseline **Limited** and
`-webkit-line-clamp` is a deprecated prefixed form — the same bar that killed
`light-dark()` (m6) and `text-wrap: balance` (m7). The comment records that
`abstract_head` (`tools/_arxiv_api.py:210`) is `" ".join(summary.split())` —
the FULL abstract despite the name, 800-1500 chars at up to 200 candidates a
run — and that the full text stays in the DOM deliberately, because it is what
a screen reader announces and what a copy-paste yields.

## Branching note

Commits landed on the **worktree branch `worktree-agent-a4fd5bfa636591d65`**,
not on `main`.

CLAUDE.md 4.1 ("All work lands on `main` directly … Worktrees are fine … but
the final commits land on `main`") was attempted and is mechanically
unavailable from here: `git checkout main` returns
`fatal: 'main' is already used by worktree at
'/Users/chris.dare/Personal/SourceCode/arXMCP'`. This is the same refusal m7
hit and recorded, and nothing was forced.

**The orchestrator must land these commits.** Note it is a *rebase*, not a
fast-forward: `main` moved one commit past the base while this ran
(`216aff0` → `4f936d8`, `chore(notes): land m10 research + synthesis`), so the
two histories have diverged. That commit touches only
`.claude/notes/milestones/ui-uplift-m10/{research,state.json}` — zero overlap
with anything here — so the rebase is conflict-free.

`git status --porcelain` is empty in the worktree.

## Files touched

| File | Role |
|---|---|
| `server/frontend/static/app.css` | The deliverable — 8 new class rules, the `.discover-meta` tabular extension, the finished remediation block. 498 → 575 lines. |
| `server/frontend/static/tokens.css` | `--fg-muted` minted in both `:root` blocks with its derivation. 157 → 179 of a 200 bound. |
| `tests/test_ui_contrast.py` | 8 new registry rows; corrected the now-false note about the remediation having no rule of its own; retired the hand-typed pair count. |
| `tests/test_ui_class_css_coverage.py` | `_KNOWN_UNSTYLED = {}`; m9 M2/M3/M5 doc-drift closed; stale 9/400 prose fixed. |
| `tests/test_ui_m3_dark_and_htmx_feedback.py` | Cap 520 → 600 + the full merits argument. |
| `tests/test_ui_m4_in_place_add_paper.py` | Cap 520 → 600, cross-referencing m3. |
| `tests/test_ui_m5_create_remove_in_place.py` | Cap 520 → 600, cross-referencing m3. |
| `.claude/docs/ui-contrast-table.md` | Regenerated (3 marked regions) + 2 hand-written regions corrected. |
| `.claude/agent-memory/milestone-implementer/lessons.md` | 3 new lessons; m7's worktree lesson marked `[CONFIRMED]` in place. |

`server/routes/notebooks.py`, `server/routes/ui.py` and the templates are
**unchanged** — this milestone shipped no markup change.

## Deferred

- **The panel-level query disclosure.** Both briefs offered it as the honest
  alternative to a relevance line — amending the `.hint` copy to name the
  `cat:` + `abs:"…"` clause the run used, plus "newest first". It is a
  *constructive alternative offered, required by no AC*, and it would mean
  editing `_discover_results_fragment`'s copy, i.e. widening a CSS milestone
  into the fragment builder at the top of the line budget. Declined
  deliberately rather than silently; the panel currently discloses no ordering,
  which remains an honest gap rather than a false claim.
- **The template half of BAN-R2 coverage.** m9 M5/L5: `_route_files()` globs
  `server/routes/*.py` only, so eight unstyled *Jinja template* classes remain
  untracked. AC#7's "binds unconditionally" is true of the Python fragment
  builders and false of the templates; the docstring now states that boundary
  instead of implying total coverage.
- **A guard for AC#3.** Nothing in the suite forbids a fourth `@keyframes` or a
  `view-transition-name` on `#discover-results`. AC#3 is satisfied by review
  this milestone and evaporates on the next CSS change. Brief-1 risk 4 proposed
  a derived test ("no keyframe name outside the three that exist"); not added,
  because AC#8's line budget was the binding constraint and this is a new test
  surface rather than a milestone deliverable.
- **The remaining hard-coded greys.** `--fg-muted` is minted and consumed by
  the three m10 surfaces; the eleven legacy literals (`#555`/`#666`/`#6f6f6f`/
  `#444` and the hand-listed dark remaps) are **not** migrated onto it. Doing so
  would touch the dark-mode remap rule, several registry rows and the artifact
  for zero m10 acceptance criterion. Left as a clean, obvious follow-up now that
  the token exists.
- **`_DYNAMIC_MODIFIER_ALLOWLIST` findings.** m9 M4 (allow-list pinned to only
  one of two `status-badge--` producers), L1 (non-recursive route glob), L2/L4.
  Out of scope; not touched.

## external_writes_required

```yaml
external_writes_required:
  - "git push origin main"
```

Verbatim from both research briefs; the implementation introduced no new one
(CSS + tests + an internal doc; no `pyproject.toml` change, so no
`make wheel-check` gate and no `Dockerfile.server` `COPY` pairing — `*.css` is
already inside the `[tool.setuptools.package-data]` glob and `COPY server/`).
**Declared, not performed.** CLAUDE.md 4.4 makes the push per-event
authorized — a previous "yes, push" does not carry, and the orchestrator must
re-ask at the Phase-4 boundary.

## Test deltas

No test file was **added**. Five were changed; the contrast registry grew from
91 to 99 parametrized cases (each `PAIRS` row is one test id), so the collected
count rises by 8.

| File | Delta |
|---|---|
| `tests/test_ui_contrast.py` | +8 parametrized pair cases; 1 target added to an allow-list; 2 stale comments corrected |
| `tests/test_ui_class_css_coverage.py` | `_KNOWN_UNSTYLED` 8 → 0 entries (re-activates AC1 for all 8 classes); no test added or removed |
| `tests/test_ui_m3/m4/m5` | cap literal 520 → 600 in three assertions |

## Check gate results

- **`ruff check .`** — PASS, "All checks passed!". Run with the main tree's
  `.venv/bin/python` (a worktree has no `.venv`) and the worktree as cwd.
- **`pytest`** (full suite, `-q --tb=line -p no:warnings`) — **4774 passed,
  47 skipped, 1 xfailed, 7 failed**, 4829 collected. Exit 1 from the seven
  failures, all pre-existing and environment-bound on this workstation, none in
  any surface this milestone touched:
  - `tests/security/test_latexml_sandbox.py` ×6 — macOS has no `bwrap`; the
    containment tests report `latexmlc exited nonzero (rc=-6)` and
    `TestSandboxWiring` asserts `'latexmlc' in ['bwrap', '--ro-bind', …]`.
  - `tests/test_arxiv_fetch.py::TestParseWithLatexml::test_win32_bat_invoked_via_perl`
    — `NotImplementedError: cannot instantiate 'WindowsPath' on your system`.

  The dispatch named **8** environment-bound failures, the eighth being a
  network-flaky HuggingFace download. It **passed** this run, which is the
  transient-pass case the dispatch warned about — so this is a 7-failure
  observation of an 8-failure baseline, not a 7-failure baseline. **Zero NEW
  failures.**
- **Targeted UI surface** (`test_ui_contrast`, `test_ui_class_css_coverage`,
  `test_ui_m3`, `test_ui_m4`, `test_ui_m5`, `test_ui_m7_type_scale`) — **268
  passed, 0 failed**, exit 0. This is the set that would catch every guard the
  dispatch flagged: `TestRectifyTabularNumsScope`, `TestRectifyProseStaysSans`,
  `TestKnownUnstyledDebtIsSelfCleaning`, the three cap tests, the OKLCH shape
  test and the generated-region freshness test.
- **`git status --porcelain`** — clean.

## Diff size — the real numbers

The implementation commit `0edc12a` is **8 files, +334 / −132**; raw churn 466.
The two `chore(notes)` commits add only `lessons.md` (+4/−1) and this synthesis.

That 466 overstates authored work, and the split matters:

| | insertions | deletions |
|---|---|---|
| `.claude/docs/ui-contrast-table.md`, **inside** generated markers | 88 | 80 |
| Everything authored by hand | 246 | 52 |

168 of the 466 churned lines (36%) are the contrast table renumbering itself:
eight rows were inserted near the top of a 99-row generated table, so every
subsequent row's `| N |` index shifted and diffs as delete+insert.
`python -m tests.test_ui_contrast --update` wrote all of it.

**Against the dispatch's guard (~450 LOC or ~12 files):** 8 code files is
comfortably under 12. On lines, authored churn is 298 and raw churn is 466 —
i.e. the raw figure sits ~4% over a threshold prefixed with "~", entirely on
generated bytes, with the milestone complete and every gate green at the point
it crossed. Continuing to a coherent stop rather than committing a partial and
returning `aborted-scope` was the judgement call; it is flagged here rather
than rounded down, because the dispatch explicitly noted m7's implementer
understated its overrun by 2.4×.

**Why one implementation commit rather than the ≤200-LOC-per-commit
preference:** the change is atomic by construction. `_KNOWN_UNSTYLED` must be
emptied in the same commit as the CSS
(`test_known_unstyled_entries_are_still_actually_unstyled` fails the moment a
listed class gains a rule); the cap raise must land with the CSS (575 > 520);
the registry rows and the regenerated artifact must land with the token. Any
intermediate commit is a red gate.

## Not verified

No browser render. The repo has no visual-regression harness, and exercising
the Discover panel end-to-end needs a warm LanceDB/BGE server plus a live
arXiv call. Every claim above is from source or from a derived test; the
rendered outcomes cited (491×22px) are the discovery's own live measurements,
not re-measured here. Phase 3 should verify H1's *rendered* outcome rather than
the selector's existence — brief-2 risk 2 makes exactly that point about AC#5.
