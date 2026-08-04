---
milestone: ui-uplift-m9
phase: research
briefs: [research/brief-1.md, research/brief-2.md]
research_mode: standard
written_by: milestone-pipeline orchestrator (fan-in, not a sub-agent)
---

# Research synthesis — ui-uplift-m9

Land the BAN-R2 policy (every server-emitted CSS class has a rule) as a test
that derives its check from the on-disk tree.

## Affected files (deduped, both briefs agree)

| Path | Role |
|---|---|
| `tests/test_ui_class_css_coverage.py` | **NEW** — the derived test. Name follows the `test_ui_*` sibling convention. |
| `server/routes/notebooks.py` | READ-ONLY input. 14 of 16 emission sites. |
| `server/routes/ui.py` | READ-ONLY input. 2 sites, incl. the one dynamic family. |
| `server/frontend/static/app.css` | READ-ONLY input. The repo's only stylesheet, 398 lines. |

`server/routes/debug.py` and `__init__.py` emit no HTML (JSON only) — verified,
but the test must walk `server/routes/*.py` as a glob, not a hand-listed pair,
or AC3 fails the day a fifth route module lands.

## Acceptance criteria (traced to the roadmap item)

- **AC1** — every class literal emitted from a fragment builder in
  `server/routes/` must have a matching selector in `app.css`, or the test fails.
- **AC2** — the dynamic status-badge modifier family is allow-listed explicitly,
  not false-failed.
- **AC3** — a NEW fragment added later with no CSS rule fails the suite. The
  policy binds forward, not just retroactively.

## Key facts established

1. **16 emission sites**, all inside Python string/f-string literals in
   `notebooks.py` + `ui.py`. Exactly **one** dynamic family:
   `status-badge--{css}` at `ui.py:289`, whose value set is closed and
   verifiable — `{ok, warn, down, ops-warn}` from `_classify_status_badge`
   (`ui.py:211/213/220/228/229`). AC2's allow-list should pin those 4 members,
   NOT wildcard the `status-badge--` prefix.
2. **A live regex false-positive exists today.** `notebooks.py:1985` is a
   *docstring* containing a literal `class="hint"` as prose. A whole-file regex
   would treat it as an emission. Harmless only by coincidence (`hint` is
   styled). Both briefs independently reached the same conclusion: extract via
   `ast`, restricted to real string/f-string nodes, then apply a small regex for
   `class="..."` tokens *within* those isolated literals. This mirrors
   `tests/test_assert_ban.py`, whose own docstring warns about exactly this
   failure mode for a structurally identical problem.
3. **`app.css` has no bare `.foo { }` rules at all.** Every class-based selector
   is compound (`.card .hint`), element+class (`pre.error`), comma-grouped
   (`button, .button`), pseudo-suffixed, or nested in `@media`. A checker must
   match `.classname` as a word-bounded token anywhere in the file text. A
   top-level-rule assumption would fail *every* currently-covered class.
4. **Zero new dependencies.** `tinycss2` confirmed absent from `pyproject.toml`;
   none is needed. Stdlib `ast` + `re` only.
5. **Templates are deliberately out of scope.** `rename-form`,
   `notebook-actions`, `topic-form` are template-only classes. AC1 and the
   epic's `links.code` both name only `server/routes/`. Recorded so Phase 2 does
   not silently widen and Phase 3 does not flag it as a gap in *this* milestone.

## The blocking decision, and how Phase 2 resolves it

**Both briefs independently flagged the same thing: 9 classes emitted today have
zero CSS**, so a literal AC1 implementation fails on first run.

- `status-badge__remediation` (`ui.py:336`) — no milestone owns it
- `topic-block`, `topic-category`, `topic-description` (`notebooks.py:621-623`)
- `discover-candidate`, `-title`, `-meta`, `-abstract`, `-list` (`notebooks.py:731-748`)

**"Just add the CSS" is not available.** `app.css` is at **398 lines against a
`line_count <= 400` assertion in three sibling tests**
(`test_ui_m3_dark_and_htmx_feedback.py:484`, `test_ui_m4_in_place_add_paper.py:671`,
`test_ui_m5_create_remove_in_place.py:803`). Styling 9 classes needs ~30-60
lines. Taking that path means raising a deliberate, thrice-asserted budget as a
side effect of a test-authoring milestone — and poaching `ui-uplift-m10`, which
the roadmap scopes to exactly the `discover-*` family.

**DECISION: land the policy; defer the debt to the milestones that own it.**
Two structurally SEPARATE lists, never one generic skip-list
(brief-1 risk #5 is explicit that collapsing them is the anti-pattern this
milestone exists to kill):

- `_DYNAMIC_MODIFIER_ALLOWLIST` — AC2. Structural and permanent: a static scan
  *cannot* resolve an interpolation to a literal. Pins the 4 verified members.
- `_KNOWN_UNSTYLED` — debt deferral. Dated, and every entry names the milestone
  that owns the fix (`discover-*` → `ui-uplift-m10`;
  `status-badge__remediation` + `topic-*` → unowned, flag for roadmap).

**The deferral list must itself be self-cleaning:** the test asserts each
`_KNOWN_UNSTYLED` entry is STILL unstyled, and FAILS if one has gained a rule.
That makes it a shrinking list that cannot rot — the property that separates it
from the hand-maintained list this milestone replaces. AC3 still holds: a new
class not in either list fails.

## External writes required (verbatim from brief-2)

```
external_writes_required: ["git push origin main"]
```

No deploy, no publish, no GitHub mutation, no external API call.

## Open questions (max 5)

1. Do `status-badge__remediation` and `topic-*` need a roadmap milestone? No
   epic item currently owns them. Surface at Phase 4; do not fix here.
2. Should the template-only classes get their own later policy? Out of scope
   here by AC1's wording; worth a roadmap note.
3. Is `<= 400` on `app.css` still the right budget once m6/m7 land OKLCH tokens
   and a type scale? Not this milestone's call.

## Phase 2 sizing

Estimated **~250-350 LOC across 1-2 files** (one new test file; no production
code changes). Novel architecture: no — it follows two established derived-test
precedents. Sits at the inline/delegated boundary; **delegated** is chosen
because the main session already carries large prior context, which also leaves
Phase 4 running inline in the main session per the default.
