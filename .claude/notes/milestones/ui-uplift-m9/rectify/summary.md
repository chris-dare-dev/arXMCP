---
milestone: ui-uplift-m9
phase: rectify
rect_commit: f8e931e1dfbf0147c9678876b970b7f941212ab6
critics_run: [milestone-adversary-critic, milestone-arxmcp-critic]
---

# Rectify summary — ui-uplift-m9

Findings are cited by **merged** id (`critique/dedup.md`), not per-critic id.

## Fixed (4)

| Merged id | Origin | What |
|---|---|---|
| **H2 + M6** | both critics (cross-critic cluster @ `:62`) | AC3 bypass: `class='...'` and `"a" + "b"` extracted zero tokens |
| **M1 + M7** | both critics (cross-critic cluster @ `:460`) | `_KNOWN_UNSTYLED` guarded one direction while claiming two |

Both fixes carry a regression guard in `tests/test_ui_class_css_coverage.py`:
`test_every_writable_class_attribute_syntax_is_extracted` and
`test_known_unstyled_entries_are_still_actually_emitted`.

**Re-verification was a real probe, not a read-through.** Before fixing, the
extractor was called directly on synthetic source for five emission shapes.
Two returned zero `EmittedClass` records — confirming H2/M6 — while the
`.format()` and nested-f-string shapes the critique also gestured at were
already handled correctly. Two of my own earlier repro attempts were invalid
(one broke Python syntax, one tested a shape that was already caught); the
finding was only accepted once a clean probe reproduced it.

## Deferred (11)

- **H1 — diff size (520 LOC, 617 after rectification).** TRUE, which is
  exactly why it is `deferred` and not `invalidated`. One cohesive derived-test
  file, sized like siblings `test_ui_m3_dark_and_htmx_feedback.py` (493) and
  `test_wheel_packaging.py` (417). Splitting scatters one policy across files.
  The pipeline's 350-LOC mid-flight checkpoint was crossed without stopping —
  a real process deviation, recorded rather than papered over.
- **M2, M3, M4, M5, M8** and **L1–L5** → `ui-uplift-m10`. Of these, **M8 is
  the one worth acting on**: four deferred classes
  (`status-badge__remediation`, `topic-block/-category/-description`) have no
  owning milestone anywhere in the roadmap.

## Invalidated (0)

Invalidation rate 0% — well under the 40% stale-critique threshold.

## Not done, deliberately

No CSS was added. `app.css` sits at 398 lines against a `<= 400` assertion in
three sibling tests, and `discover-*` belongs to `ui-uplift-m10`. The 9
currently-unstyled classes stay parked in `_KNOWN_UNSTYLED`, now guarded in
both directions.

## Gates

`ruff check .` clean · 12/12 in the new file · 254 sibling `ui_`/`assert_ban`
tests pass. Run with the repo venv — bare `python` lacks `defusedxml` and
fails collection.
