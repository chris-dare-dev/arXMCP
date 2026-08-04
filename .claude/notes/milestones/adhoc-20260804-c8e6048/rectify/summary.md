---
milestone_id: "adhoc-20260804-c8e6048"
phase: "rectify"
issue: "https://github.com/chris-dare-dev/arXMCP/issues/382"
rectification_commit: "af55e541c3f8e6fd345f84ee5598238f05019fd4"
critics_run:
  - milestone-adversary-critic
  - milestone-arxmcp-critic
finding_counts: { critical: 1, high: 2, medium: 4, low: 3 }
fixed: [C1, H1, H2, M1, M2, M3, M4]
deferred: [L2, L3]
invalidated: [L1]
external_writes_required:
  - "git push origin main"
---

# Rectify summary — adhoc-20260804-c8e6048 (arXMCP#382)

## Re-verification

All 7 CRITICAL/HIGH/MEDIUM anchors re-verified against live code before any
fix — 7/7 found in window. **0% invalidation at re-verify**, so no
re-critique was owed. (L1 was invalidated later, by the fix superseding it,
not by a stale anchor.)

## The headline correction

The Phase-2 implementation keyed on the `in` combinator. That closes
`set_option`, `open`, `variable`, `universe` and `attribute` — five of the
eight live shapes in the #382 class — and leaves `deriving instance`, `alias`,
`meta …` and a same-line doc comment open. `research/brief-2.md:155-158` had
already stated the correct characterisation: the defect is that **the physical
line carries a declaration keyword with something unrecognised in front of
it** — "it is not really about `in`". The implementation built to the issue's
narrower framing and the research's wider one was in front of it the whole
time.

Both critics reached this independently, from different axes, and the register
clustered their findings at `lean_verify.py:471-472`. Worth recording as the
pipeline earning its cost: a single-pass implement-and-ship would have closed
the issue while `/-- Helper. -/ axiom evil : False` still rode inside a `clean`
verdict.

## Fixed

- **C1 (CRITICAL) — `CLAUDE.md` §4.10 rule 3 documented #382 as live.**
  Re-measured all four table rows against the post-fix tree, added two rows for
  the shapes the first pass missed, restated the mechanism ("increments `sites`
  but not `names`, so the fail-safe now fires"), and re-resolved the three
  drifted cites (`:479`/`:1123`/`:613` → `:604`/`:1258`/`:744`). Kept the "do
  not describe the empty case as the bug" paragraph and noted its `complete`
  now returns False. The bullet still exists, because what remains true is the
  honest bound: extraction is still a regex over source text, not Lean.
  *Guard:* `test_claude_md_table_matches_live_behavior` derives the table's
  claims from live code — verified to fail on injected drift and pass on
  truth, in both directions.

- **H1 (HIGH) — a same-line comment hid a declaration.**
  `/-- Helper. -/ axiom evil : False` beside an ordinary theorem returned
  `(['harmless'], True)`: a `False` axiom inside a `clean` verdict, the exact
  founding threat of #205/#281/#332. `_strip_comments` now removes comment
  text before matching, so `evil` is a normally-named site and is genuinely
  audited — strictly better than fail-safe.
  *Guards:* `test_same_line_doc_comment_declaration_is_audited`,
  `test_same_line_block_comment_declaration_is_audited`.

- **H2 (HIGH) — prefixes with no `in` were still invisible.**
  `_PREFIXED_DECL_SITE_RE` generalized to any unrecognised same-line prefix
  before a whitespace-preceded declaration keyword. `alias` joined
  `_DECL_KEYWORDS` — unlike `set_option`/`open` it IS a declaration command
  and was simply missing, so it is named rather than fail-safed.
  *Guards:* `test_deriving_instance_is_not_silently_dropped` (the mathlib4
  line quoted in brief-2), `test_meta_prefix_is_not_silently_dropped`,
  `test_alias_is_a_declaration_keyword`.

- **M1 (MEDIUM) — the scan produced false evidence.** Comments and tactic
  lines containing "in \<keyword\>" counted as sites, so a snippet with zero
  declarations emitted "The snippet's declarations could not be named" — an
  untrue claim attached to a trust-bearing field (§4.9). Gone: comment text is
  stripped before matching.
  *Guards:* `test_comment_containing_in_theorem_is_not_a_site`,
  `test_tactic_line_trailing_comment_is_not_a_site`,
  `test_multiline_block_comment_prose_is_not_a_site`,
  `test_snippet_with_no_declaration_does_not_claim_one`,
  `test_projection_ending_in_a_keyword_is_not_a_site`.

- **M2 (MEDIUM)** — the accepted false-positive had no pinning test, and the
  control named for that shape used comments with no `in`, so it passed
  identically with and without the regex. The behaviour is now fixed rather
  than merely pinned, and the pinning test exists too.

- **M3 (MEDIUM)** — the `axiom_audit.reason` string offered only "an unnamed
  instance or an unrecognized declaration form", pointing a reader at the wrong
  mechanism. It now names the same-line-prefix cause.
  *Guard:* `test_incomplete_extraction_reason_names_the_prefix_cause`.

- **M4 (MEDIUM)** — no wire-level test drove the drop through
  `handle_lean_verify`. Added; it asserts `#print axioms` is issued for the
  visible declaration only, the record's outcome is not `clean`, and
  `status` / `compilation_success` stay untouched.
  *Guard:* `test_prefixed_declaration_does_not_reach_the_wire_as_clean`.

**MEDIUM cap deviation, recorded.** The phase reference defers MEDIUMs above
~30 LOC or needing more than a single assert. M4 exceeds that. All four were
fixed at the user's explicit direction after being shown the cap.

## The comment scanner's own hazards, and why they are tested

Stripping comment text is a lexing step, not the "skip this line" heuristic the
Phase-2 synthesis rightly rejected — but it introduces its own way to lose a
declaration. Without string-literal tracking, `def s : String := "/-"` opens a
block comment that never closes and every later declaration in the snippet
vanishes: the exact silent drop this module exists to prevent. Four tests pin
it (`"/-"` in a string, `"--"` in a string, escaped quotes, and apostrophe
identifiers — `'` is deliberately not tracked because it is a legal Lean
identifier character).

## Invalidated

- **L1** — `superseded`. The constant was named for a broader class than it
  matched; the H1/H2 fix broadened the pattern to match the name.

## Deferred

- **L2** — the newly-routed abstention string omits the "this is NOT a clean
  verdict" disclaimer its sibling branch carries. One-line wording change; out
  of the agreed scope for this pass.
- **L3** — procedural: the head SHA in the Phase-3 dispatch prompts did not
  resolve (last four hex digits were transcribed from a truncated console
  line). `state.json` recorded the correct object throughout and both critics
  detected and reported the mismatch, then measured against the real commit.
  No code impact. Recorded because the failure mode — reading a value off a
  truncated display instead of the source — is worth not repeating.

## Regression tests added

`tests/test_handlers_lean_verify.py` — `TestPrefixedDeclarationSites` grew to
27 tests; `TestAxiomHygieneOnTheWire` gained 2.

## Check gate results

- `ruff check .`: **PASS**
- `pytest` (full suite): **PASS relative to baseline.** The same 8
  environment-bound failures measured at HEAD before Phase 2 (6 × macOS
  `sandbox-exec` latexml containment, 1 × `WindowsPath` on darwin, 1 ×
  HuggingFace download). Zero new. `tests/test_handlers_lean_verify.py` fully
  green.
- `git status --porcelain`: clean after the commits.
- Findings register gate: **OK — no open findings.**

## external_writes_required

- `git push origin main` — NOT performed. Awaiting per-event authorization
  (CLAUDE.md 4.4).
