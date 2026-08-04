---
milestone_id: "ui-uplift-m10"
phase: "research"
briefs_synthesized:
  - "research/brief-1.md (explore)"
  - "research/brief-2.md (general)"
external_writes_required:
  - "git push origin main"
estimated_loc: "180-300"
estimated_files: "5-8"
novel_architecture: false
phase2_path: "inline"
---

# Research synthesis — ui-uplift-m10 (UPL-9, Discover results + the last unstyled classes)

Fan-in of brief-1 (explore) and brief-2 (general). Both `complete`, zero
injection attempts. Every claim below was re-verified by the orchestrator
against the working tree.

## Three of the eight ACs are factually stale, and one is already true

This roadmap item was written before `ui-uplift-m7` landed. Both briefs
re-measured independently and agree:

| AC | As written | Actually |
|---|---|---|
| #5 | `.status-badge__remediation` needs a rule | **Already has two** (`app.css:222`, `:245`) — m7's rectify |
| #7 | `_KNOWN_UNSTYLED` must be EMPTY | 8 entries left, not 9. **Achievable** — `"status-badge--"` is a separate dict |
| #8 | "cap 480, app.css already at 460" | Cap is **520**, file at **498** |

**AC#5 is vacuously satisfied and should not be treated as done.** m7 gave the
class a `font-size` pin to stop a nested `<small>` compounding to ~9.2px. That
meets the letter. The open defect is discovery finding H1: the block has no
`display: block`, so it renders inline at 491×22px. m10 owns finishing it —
closing AC#5 on the existing rule would be closing it on a technicality.

## AC#4 forbids the relevance line — both briefs, independently

The arXiv Atom feed carries **no relevance score or rank in either namespace**;
the driver pins `sortBy=submittedDate&sortOrder=descending`; and
`DiscoveryCandidate` has no field to hold one. There is no basis to display.

AC#4 was written as a conditional ("only if the driver genuinely supplies the
basis") and the condition is false. So the honest implementation ships **no
relevance line at all**. Manufacturing a "why this matched" string is exactly
the fabricated evidence CLAUDE.md 4.9 exists to prevent, and it would be
indistinguishable from a real one to an operator.

## `abstract_head` is not a head — it is the whole abstract

`tools/_arxiv_api.py:210` is `abstract_head = " ".join(summary.split())`:
whitespace normalization, no truncation. The only `[:120]` in the file is on a
different path (`:98`). The fragment renders the field whole
(`html.escape(c.abstract_head)`).

So a field whose name promises a lede carries the full text, and **whatever
abstract treatment ships must do the truncating the name implies already
happened** — or the panel keeps rendering complete abstracts in a results list.
This is not in any AC.

## The m7 failure shape repeated — twice

1. **The roadmap dropped authored values.** Discovery finding H3
   (`discover/current-state-critic-brief.md:130-136`) authored **five fully
   specified CSS rules**. The roadmap reduced them to "bibliography-style
   hierarchy", and no AC constrains a single value. Identical to m7, where the
   authored `clamp()` terms were dropped and AC#3 constrained the title only
   negatively. **Read H3; do not invent an anatomy.**
2. **A decoy sits above the real content in grep order.**
   `.claude/roadmap/ui-attractive-polish-roadmap.md` carries an unchecked
   imperative `UPL-9` from the **May-2026** run, about `color-mix()` — a
   different milestone entirely. Verified: `grep -rn "UPL-9"` returns that file
   at lines 288/293/295/316 **before** any 2026q3 discovery hit. m7 had the
   same trap with a second, hypothetical `clamp()`.

**And H3's own sketch does not compile against today's tokens.** It depends on
a muted/secondary-text token that was **never minted**. `tokens.css` has
`--fg`, `--bg`, `--card-bg`, `--border`, `--accent`, `--danger`, `--error-bg`
— no secondary voice — and 11 hard-coded greys (`#555`/`#666`/`#9ba1a8`/…)
remain in `app.css`. So the implementer must either mint the token (a
`tokens.css` change with contrast-gate consequences, since every new colour
token faces `test_all_colour_tokens_are_oklch_on_one_of_two_hues` and the
91-pair registry) or reuse an existing one and record why. **This is the
milestone's real design decision and no AC mentions it.**

## Constraints that bind before a line is written

- **AC#2 now trips an m7 guard.** m7's rectify replaced the tabular-nums
  hand-list with `TestRectifyTabularNumsScope`, which asserts every `--mono`
  selector sits inside the single tabular-nums rule. Adding `--mono` to
  `.discover-meta` without extending `app.css:222-223` in the same edit
  **fails a test**. Working as designed, one milestone later.
- **AC#8's raise is required, not optional.** 22 lines of headroom does not fit
  eight class rules plus the per-rule rationale this repo treats as the
  deliverable. Lockstep across `test_ui_m3/m4/m5`, per AC#8 and per the note
  m7's rectify left in those files.
- **AC#3's premise is TRUE** (verified: `app.css:478-481`, `--dur-fast` 200ms,
  reduced-motion-gated, plus `base.html:59`). Note the discovery's own
  `synthesis.md:462` assigns a `[MOT-1 fade-in]` to this surface and the
  challenger overturned it — the AC is right and the discovery artifact
  contains the losing side of that argument.
- **Baseline refusals.** `line-clamp` / `-webkit-line-clamp` and
  `hanging-punctuation` are **Limited**; `text-wrap: pretty` / `balance` are
  **Newly** (Oct 2024). All refused under CLAUDE.md 4.7 — the same rule that
  made m6 refuse `light-dark()` and m7 refuse `text-wrap: balance`. Both briefs
  agree the whole bibliography anatomy is buildable from pre-Baseline
  properties. **The abstract truncation therefore cannot be CSS `line-clamp`** —
  see the `abstract_head` finding; it has to be handled server-side or by
  `max-height`/`overflow`.
- **Ban-list threat, specific to this surface.** A candidate row is the most
  natural home in the whole console for the two things the discovery explicitly
  killed: a coloured chip (`challenge.md:879` — badge-soup scores 0 today, 1 if
  a chip ships) and a state-history strip (`final-report.md:407`, killed as
  UPL-24). A results list is where generic card-grid instincts take over.

## Acceptance criteria for Phase 2

1. Title / meta / abstract typographically distinguished, candidates
   separated — **built from discovery H3's five authored rules**, not invented.
2. `.discover-meta` takes `--mono` **and** `app.css:222-223` is extended in the
   same edit.
3. No fade-in keyframe.
4. **No relevance line** — the condition AC#4 makes it contingent on is false.
5. `.status-badge__remediation` finished (`display: block` and the rest), not
   left on m7's size pin.
6. `.topic-block` / `.topic-category` / `.topic-description` each get a rule.
7. `_KNOWN_UNSTYLED` empty; BAN-R2 binds unconditionally.
8. Line cap raised deliberately in all three sibling tests, same commit.
9. Plus, not in any AC: the abstract is actually truncated, and the muted-text
   token question is decided and recorded either way.

## Open questions for Phase 2

1. **Mint a secondary-text token, or reuse?** H3's sketch needs one. Minting
   means a `tokens.css` addition subject to the OKLCH shape test and the
   91-pair contrast registry; reusing means the muted greys stay hard-coded and
   the type/colour split stays half-done.
2. **Where does abstract truncation live** — server-side in the fragment
   builder (honest, testable, changes the payload) or `max-height` + `overflow`
   in CSS (no payload change, no Baseline risk, but the full text stays in the
   DOM)?
3. **Does AC#5 count as met by m7's pin?** Recommend no — finish the block.

## Phase 2 path decision

**Path: `inline`.** ~180–300 LOC across 5–8 files (`app.css`, possibly
`tokens.css`, three cap tests, the coverage test, possibly
`server/routes/notebooks.py`). No novel architecture. At the ≤5-file threshold's
edge — if minting a token pulls in the contrast registry and the artifact,
re-decide rather than lane-switching silently.

## External writes required

```
external_writes_required: ["git push origin main"]
```
