---
milestone_id: "ui-uplift-m10"
phase: "rectify"
rectification_commit: "68e622d"
critics_run:
  - milestone-adversary-critic
  - milestone-arxmcp-critic
  - milestone-frontend-ux
finding_counts: { critical: 0, high: 3, medium: 17, low: 5 }
fixed: [H1, H2, H3, M1, M2, M3, M4, M5, M6, M7, M8, M9, M11, M12, M13, M14, M15, M16, M17]
deferred: [M10, L1, L2, L3, L4, L5]
invalidated: []
external_writes_required:
  - "git push origin main"
---

# Rectify summary — ui-uplift-m10 (UPL-9)

All 20 HIGH/MEDIUM anchors re-verified before any fix. **0% invalidation.**

## Two HIGH clusters, and the second is the one that mattered

**H2/H3/M2 — the clipped abstract.** All three critics filed this as their
only HIGH, independently. The abstract was clamped with `max-height` and no
ellipsis, fade, control or link: 40–85% of the text unreachable on the
console's *only* operator-judgment surface, and a short abstract rendered
identically to a truncated one. Now a native `<details>` — the clamp moved to
`> summary`, `[open]` releases it, and the full text was already in the DOM.

Worth recording that the clamp arithmetic was *correct*: 4.5em against unitless
`line-height: 1.5` is exactly three line boxes, so the cut landed on a boundary
rather than through glyphs. The defect was never the maths. It was that a
milestone whose whole subject is operator judgment hid the evidence.

**H1/M7 — the guard that guarded nothing.** ui-uplift-e2's finish line is that
emptying `_KNOWN_UNSTYLED` makes BAN-R2 bind *unconditionally*. Nothing
defended it: both self-cleaning tests comprehend over the dict, so on `{}` they
iterate nothing and pass vacuously. In a repo with no PRs and no CI
(CLAUDE.md 4.1), the epic's finish line survived exactly one line-edit.

And `_css_defines_class` is a bare `\.token` match, so `.foo { }` satisfies it.
The `display: block` that fixes discovery H1 was unguarded — and **ui-uplift-m7's
bare `font-size` gesture, which this milestone's own research criticised as
meeting AC#5's letter and not its intent, would pass identically today.** The
predicate could not tell a rule from a gesture, which is exactly how the gesture
shipped.

Both now assert the property directly, with a real declaration pinned per styled
class.

## The ban-list item that shipped

**M14 — BAN-9, "multiple primary CTAs per viewport", is on the must-be-removed
list.** Every candidate row carries an `Add` button with no class, so it takes
the base `button` rule: full accent fill, white text. A results panel renders
one per row. The implementer's ban audit was real — no chip, no icon, no card
grid, no killed UPL-24 strip — but it was scoped to the things the discovery
named for *this* surface and never checked the per-row CTA, because
`challenge.md`'s 0 score rested on UPL-1 collapsing *forms*.

`.button-quiet` keeps the action equally reachable and equally sized. Only the
fill is dropped.

## The absence that needed a disclosure

**M8/M15.** AC#4 correctly refused a relevance line: the arXiv Atom feed carries
no score or rank in either namespace and the driver pins `sortBy=submittedDate`.
Shipping nothing was right. But *silence plus bibliography styling* still let an
operator infer a ranking — a styled ladder reads as search results. The hint now
says **"newest first — arXiv does not rank by relevance"**, which is the honest
disclosure the absent line could not make. Guarded both ways: the disclosure must
be present, and no emitted markup may imply a ranking basis.

## Corrections to claims that were false

- **M3/M9/M11** — the token comment said the AAA target meant "nothing gets
  lighter" and implied the greys had been migrated. Measured on `--card-bg`, the
  greys span **4.886:1 to 11.467:1**, and `#444` (9.47), `#555` (7.25), `#b3b9c0`
  (8.95) and `#c9d1d9` (11.47) all get *lighter* at 7.00. And none of the eleven
  was migrated: `--fg-muted` is currently a **twelfth** value. In dark mode it
  sits within a 1.036 luminance ratio of `.card .note`'s `#9ba1a8`, so three
  near-identical muted greys can render in one card. Recorded as debt rather
  than as a claim it was paid — migrating shipped surfaces has its own contrast
  rows and belongs to a milestone that owns it.
- **M4** — the cap failure messages attributed the 600 raise to m6. **I verified
  the cap COMMENTS preserved history in Phase 2 and did not check the assertion
  messages** — I looked at exactly the spot where I'd made that mistake in m7's
  rectify and stopped there.
- **M17** — the stylesheet justified omitting a chip with "a run is up to 10
  rows" while, twenty lines later, describing "up to 200 candidates a run". The
  route relied on the driver's `max_results=200` default; at ~150px per styled
  candidate that is a ~30,000px ladder announced whole by an `aria-atomic` live
  region, and m10's own styling made the row taller. Now an explicit 25.

## Forward risk, recorded not fixed

**M6.** `ui-uplift-m8` is lane `next` with both dependencies shipped, and its
acceptance criteria re-role `--card-bg` off panel ground. m10 pinned a new
token's derivation, its only two canvas rows, and a written refusal to register
a `--bg` pair to exactly that ground. Post-m8 the consumers move to `--bg`,
where the token measures 6.80 / 7.69 — **no AA failure, so nothing fails
loudly** and the registry omission would read as deliberate. m8 must re-solve
and register. Its "three dark-mode rules depend on `--card-bg`" count is now
four.

## The cap was not raised again

app.css finished at **596 of its 600 cap**. My first pass overflowed it at 610
and the reflex was to raise it — the fourth raise in four milestones. The
adversary had explicitly asked whether the discipline is still real or "a
formality that moves whenever it binds", and answering that with another raise
would have settled it the wrong way. Trimmed the rationale instead.

## Two bugs in my own guards, caught before commit

- The declaration-pinning test matched only the *first* rule block per class,
  which for `.status-badge__remediation` is the comma-grouped tabular-nums rule
  — so it failed against correct CSS. Fixed to search all blocks.
- The no-relevance guard scanned source including comments, so it flagged the
  phrase "read as relevance-ranked" in the rationale explaining *why* there is
  no relevance line. Scoped to emitted markup.

Both were my tests being wrong about correct code — the failure mode worth
naming, because a test that fails on correct code trains people to weaken tests.

## Deferred

- **M10** — five roadmap `links.code` anchors invalidated again. One-writer rule
  reserves `roadmap.yaml` for the roadmap agents; re-anchor after this milestone
  completes, so the spans are computed against the final file.
- **5 LOW** — out of the agreed scope.

## Check gate results

- `ruff check .`: **PASS**
- `pytest`: **PASS relative to baseline** — exactly the 8 pre-existing
  environment-bound failures, zero new.
- Findings register gate: **OK — no open findings.**

**Baseline correction, mine.** I told six dispatch briefs that
`test_cite_neighbors_wired` is "network-flaky, transiently passes on a warm
HuggingFace cache". It is not: it fails deterministically on
`assert 'unavailable' == 'absent'` because `var/arxmcp/index/kuzu` is an empty
bootstrapped directory. The failure *count* was right throughout, so no gate
decision was affected, but the attribution I repeated all session was wrong and
one implementer's observation I explained away with the wrong cause.

## Not verified in a browser

`create_app()` will not boot without an ingested corpus, so every check here is
source-level — including the `<details>` affordance, whose whole purpose is a
rendered interaction. The defect it fixes was found by reasoning about the
cascade, not by looking at the page.

## external_writes_required

- `git push origin main` — NOT performed. Awaiting per-event authorization
  (CLAUDE.md 4.4).
