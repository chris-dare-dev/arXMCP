---
milestone_id: "ui-uplift-m12"
phase: "research"
briefs_synthesized:
  - "research/brief-1.md (explore)"
  - "research/brief-2.md (general)"
external_writes_required:
  - "git push origin main"
estimated_loc: "250-400"
estimated_files: "8-12"
novel_architecture: false
phase2_path: "delegated"
---

# Research synthesis — ui-uplift-m12 (UPL-1, corpus before machinery)

Fan-in of brief-1 (explore) and brief-2 (general). Both `complete`, zero
injection attempts. Orchestrator re-verified every claim below except one,
which is flagged as unverified.

## The finding that explains three prior milestones

**`rg` cannot see `.claude/` at all.** Verified directly: `rg --files-with-matches
"UPL-1\b"` returns `plans/`, `tests/` and `app.css` — and **none** of the
discovery tree, which plain `grep` finds immediately. ripgrep skips hidden
directories by default, and the entire authored design for this track lives in
`.claude/notes/frontend-uplifts/`.

This is not "a decoy outranks the real content", which is how m8 characterised
it. It is worse and simpler: **an implementer using the Grep tool sees the
May-2026 roadmap and never sees the 2026q3 discovery at all.** The first `UPL-1`
hit is a `prefers-reduced-motion` comment in `app.css:432` — inside the very file
being edited.

It also explains m7, m10 and m8, where the roadmap had dropped authored values
and the implementer "invented" them: the source was invisible to the tool they
were searching with. **Any Phase-2 dispatch must name the discovery paths
explicitly rather than telling the implementer to find them.**

## AC#5's stated reason is wrong; its conclusion is right

The brief says animating `<details>` needs `interpolate-size` or
`::details-content`, "both Chromium-only". **`::details-content` is not
Chromium-only** — Baseline **newly** since 2025-09-16 (Chrome 131, Firefox 143,
Safari 18.4, WPT 1.0 across all engines). Only `interpolate-size` / `calc-size()`
are Chromium-only.

AC#5 still holds, on the axis this repo actually uses: Newly, not Widely (Widely
2028-03-16), the same basis that made m6 refuse `light-dark()`, m7 refuse
`text-wrap: balance` and m10 refuse `line-clamp`. **Restate the reason; do not
repeat it.** An AC defended by a false premise is one browser release from being
argued away.

And the discovery still contains the losing side: **seven live sites** in
`synthesis.md` and `art-direction-scout-brief.md` assign a `MOT-15`
accordion-expand that was killed only in `challenge.md` and `final-report.md`.
Same shape as m10's fade-in.

## A prior milestone already rejected this exact pattern

`server/routes/ui.py:280-286` records `onboarding-uplift-m3` synthesis §3 D2
**explicitly rejecting** `<details>`/`<summary>` because `hx-swap="outerHTML"`
replaces the element on every poll and **would snap any `<details>` closed**.

m12 proposes a disclosure on a page whose ingest fragment polls every 2s. This
is not a blocker — the poll target and the disclosure can be separated — but the
implementation MUST show why m12's arrangement escapes D2's reasoning, or it
repeats a decision the repo already made and documented.

Related, verified at htmx 2.0.10 source by brief-1: **a poll inside a closed
`<details>` keeps firing** (the guard is `bodyContains` only). AC#2's "would
otherwise poll invisibly for a whole run" is not a risk — it is the current
behaviour, and AC#2 is the mitigation.

## AC#1 and AC#4 are mutually inconsistent as written

There are **six** forms, not five. The sixth is **rename**, and it sits inside
the LEADING identity section:

- AC#1: the papers table is visible without scrolling past **any** input form.
- AC#4: every **moved** form's `hx-target` still resolves.

Rename either moves into the disclosure — pulling a control out of the identity
block that `ui-uplift-m8` deliberately made a `<section>` — or it stays, and AC#1
is false as worded. **Phase 2 must resolve this explicitly**, not pick one
silently.

## The risk nobody flagged, created by m8's own rectify

`app.css:64-65` is a **direct-child** selector:
`main > :where(section, div) + section|div`. Nesting the five mutation blocks
inside a `<details>` removes them from `main >`, so they **silently lose their
rule, margin and padding**. No test catches it — m8's guards check the ladder's
tokens and its horizontality, not its reachability.

This is a direct consequence of the H4 fix in m8's rectify, which split one
selector into two to make the section/div rank render. Worth stating plainly:
the fix that made the ladder correct is the thing that makes this milestone's
nesting dangerous.

## Corrections to the orchestrator's Phase-0 recon

1. **One `<details>` in product code, not two.** Four of the five grep hits are
   comments about D2's rejection. (Counting comment text as code — the same
   error this session has made repeatedly.)
2. **1823px is NOT stale.** Re-derived to **~1740px**. And the "+96px" figure
   quoted from m8's critique described a design that never shipped: m8's rectify
   split the ladder so `div` boundaries take the tighter rung, a −30px net.

## De-risked: AC#2 and AC#3 need no new query

`server/routes/ui.py:461` already passes `latest_run` from the same
`store.get_latest_ingest_run` that the polling endpoint calls at
`notebooks.py:2283`. The summary's state cue can source from that identical row,
which is exactly what AC#3 asks for — so the cue cannot drift from the fragment.

## Constraints that bind before a line is written

- **`app.css` is at 598 of a hard 600 cap** (three lockstep test files);
  `tokens.css` at 289/290. m12 fits in +2 lines only by folding selectors.
  **Raising the cap is step one, not cleanup** — but note m8's rectify
  deliberately HELD it rather than raise a fourth time, so this is a real
  decision with precedent against it.
- **The Jinja `open` attribute must be emitted BARE.** `open="false"` renders
  **open** — HTML boolean attributes are presence-based. This is AC#2's whole
  mechanism and the classic way to get it exactly backwards.
- **Reordering breaks `TestSectioningElementDecision.DECIDED`**, which pins the
  seven blocks' document ORDER. It must be updated as a recorded re-decision
  with reasons, not silently re-sorted — that guard was rewritten in m8's
  rectify precisely to catch order changes.
- **`notebook_detail.html:322` says "No papers yet. Add one above."** and m12
  moves that form below the table. The copy breaks in v0. `ui-uplift-m11` owns
  empty-state copy and `depends_on` m12 — so m12 either fixes this one string or
  ships a page whose only instruction is wrong.
- **Authored values the roadmap dropped** (recover, do not invent): the
  disclosure label **"Manage this notebook"**, the state-cue wording, the five
  form names, the 7-cards→3-regions target, and BAN-2.

## Unverified claim, flagged

brief-2 states m11 is scheduled to END eleven days before m12 despite depending
on it. The orchestrator could not confirm this: `target` is not an item field in
`roadmap.yaml` and the brief resolver derives it. **Treat as unconfirmed.** If
true it is a roadmap defect for `/roadmap`, not for Phase 2.

## Open questions for Phase 2

1. **Does rename move or stay?** (AC#1 vs AC#4.)
2. **Raise the app.css cap, or fold selectors?** m8 held it; m12 may not be able
   to.
3. **How does the disclosure escape D2's poll-snaps-closed reasoning?**

## Phase 2 path decision

**Path: `delegated`.** 250–400 LOC across 8–12 files — the template, `app.css`,
three cap tests, m8's order guard, the coverage test, the contrast registry, the
artifact, and possibly `ui.py`. Above the ≤5-file inline threshold.

## External writes required

```
external_writes_required: ["git push origin main"]
```
