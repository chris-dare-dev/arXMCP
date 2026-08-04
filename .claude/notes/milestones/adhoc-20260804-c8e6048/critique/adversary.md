# Critique — adhoc-20260804-c8e6048 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** d0082f0acd18117cebf029599ed0bbb6abb97fb4..e2651e9d80bd865ecaa361cfdb254ed62fd7c750
**Diff stats:** 2 files, 187 LOC
**Critique format version:** 1.0

> Dispatch metadata note (procedural, not a finding): the head sha supplied at
> dispatch, `e2651e9d80bd865ecaa361cfdb254ed62fd7c0f5`, is not an object in this
> repo — `git cat-file -t` refuses it. The real commit is
> `e2651e9d80bd865ecaa361cfdb254ed62fd7c750` (same `e2651e9` short prefix,
> last four hex digits differ). Everything below is measured against the real
> object; diff stats match the dispatch brief exactly (184+/3-).

## Verdict

SHIP-WITH-FIXES. The code change is correct for the shapes it targets and is
monotone-safe by construction — the new branch sits inside the
`not _DECL_SITE_RE.match(line)` arm and only ever increments `sites`, so
`sites == len(names)` can move True → False and never the reverse. Two things
block calling #382 closed: `CLAUDE.md` §4.10 rule 3 still documents the bug as
live, in the present tense, with a dated measurement table the diff falsifies;
and the fix keys on the `in` combinator, so a same-line doc comment
(`/-- Helper. -/ axiom evil : False` beside any ordinary theorem) still puts an
unaudited declaration inside a `clean` `axiom_audit` — live-verified in this
tree, and exactly the characterisation `research/brief-2.md:155-158` warned was
"not really about `in`".

## Executive summary

- [CRITICAL] `CLAUDE.md:475-500` asserts the #382 mechanism in the present
  tense ("increments **neither** `sites` nor `names`"), carries a four-row
  dated table whose rows 2 and 4 the diff falsifies, concludes "Only the last
  row is the hole", and cites three `file:line` anchors that all drifted with
  the +37-line insertion. No doc update in the diff.
- [HIGH] The fix closes the `… in <keyword>` subclass only.
  `_declaration_names("/-- Helper. -/ axiom evil : False\ntheorem harmless …")`
  still returns `(['harmless'], True)` — a `False` axiom rides a `clean`
  verdict. `deriving instance ToExpr for ULift` (a real mathlib line quoted at
  `research/brief-2.md:141`) is invisible for the same reason.
- [MEDIUM] `^\s*\S.*?\bin\s+…` is a substring scan, so the `.match()` anchor the
  rationale comment credits with "keeping comments safe" does not. Comments,
  docstrings and tactic lines containing `in <keyword>` now count as sites; the
  record then emits "The snippet contains a declaration this tool could not
  name" for snippets that contain no such declaration — and, on the empty-names
  path, for snippets with no declaration at all.
- [LOW] `_PREFIXED_DECL_SITE_RE` is named for a class broader than it matches.
- Clean on every other axis: no external write, no `plans/*/roadmap.yaml` or
  journal touch, production + test deltas both present, commit signed
  (`%G?` = `G`) with the mandated `Co-Authored-By: Claude Opus 5` trailer and a
  39-char conventional subject, no `LEAN_VERIFY.description` /
  `TOOL_SCHEMA_VERSION` / pinned-hash surface touched.
- Diff-size auto-finding NOT filed, and the arithmetic is stated so the
  omission is auditable: 184 insertions + 3 deletions = 187 LOC, well under the
  400-LOC cliff.
- AC#6 independently verified, not taken on trust: `ruff check .` → "All checks
  passed!"; the FULL suite re-run here fails exactly the 8 environment-bound
  tests the implementer named (6 × `tests/security/test_latexml_sandbox.py`,
  `test_arxiv_fetch.py::…::test_win32_bat_invoked_via_perl`,
  `test_tools_all.py::…::test_cite_neighbors_wired`) — same 8, no more, no
  fewer, and `tests/test_handlers_lean_verify.py` is fully green.

## Findings

**C1 — CLAUDE.md 4.10 rule 3 still documents #382 as an open hole** (CRITICAL)

**Where:** `CLAUDE.md:475`
**Anchor:** `- **The audit can miss a declaration and`
**What:** The binding §4.10 rule-3 block (`CLAUDE.md:475-500`) states in the present tense that such a line "increments **neither** `sites` nor `names`, so the `sites == len(names)` fail-safe never fires", carries a table dated 2026-08-04 whose row 2 (`set_option … in theorem sneaky` alone → `([], True)`) and row 4 (`… + theorem harmless` → `(['harmless'], True)`, "**`clean`** — `sneaky` silently dropped") the diff falsifies (they are now `([], False)` and `(['harmless'], False)` / `unknown`), concludes "Only the last row is the hole", and cites `lean_verify.py:479` / `:1123` / `:613` — line numbers the diff's +37-line insertion moved to `:506` / `:1158` / `:646`.
**Why it matters:** CLAUDE.md is loaded at session start by every agent in this repo, and this block is the constitutional statement of what the axiom axis may and may not promise a sibling formalization repo (§4.10 rule 3) — it now teaches a false mechanism, presents a closed hole as open, and points three cites at the wrong lines.
**Proposed fix:** Amend §4.10 rule 3 in place using the dated-amendment pattern `.claude/docs/trust-language-policy.md` already uses: re-measure the four table rows against the post-diff tree, restate the mechanism as "increments `sites` but not `names`, so the fail-safe now fires", replace "Only the last row is the hole" with the residual hole named by the finding anchored at `if _PREFIXED_DECL_SITE_RE.match(l`, and re-resolve `:479` / `:1123` / `:613` to `:506` / `:1158` / `:646`. Keep the "Do not describe the empty case as the bug" paragraph but note that the empty case's `complete` is now `False` and its reason string changed.
**Regression-guard:** A derived doc-pin in the spirit of `tests/test_assert_ban.py` — a test that imports `_declaration_names`, runs the four snippets CLAUDE.md's table names, and asserts the live tuples match the values written in the table, so the block cannot drift again silently.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**H1 — Only the `… in …` subclass is closed; a same-line doc comment still hides a declaration** (HIGH)

**Where:** `server/handlers/lean_verify.py:545`
**Anchor:** `            if _PREFIXED_DECL_SITE_RE.match(l`
**What:** `_PREFIXED_DECL_SITE_RE` keys on an `in` combinator, so every OTHER unrecognised same-line prefix still makes a declaration invisible rather than merely unnamed — live-verified in this working tree: `_declaration_names("/-- Helper. -/ axiom evil : False\ntheorem harmless : True := trivial")` returns `(['harmless'], True)`, and `_declaration_names("deriving instance DecidableEq for Foo\ntheorem harmless : True := trivial")` returns `(['harmless'], True)`.
**Why it matters:** `axiom evil : False` — the exact founding threat `axiom_audit` exists to catch (§4.9 rule 1, issues #205/#281/#332) — still rides inside a `clean` verdict behind a one-line doc comment, an idiom at least as common as `set_option … in`, so the milestone's headline claim that an unaudited declaration can no longer pass is not yet true.
**Proposed fix:** `research/brief-2.md:155-158` states the correct characterisation the fix should key on: "the defect is strictly: does the physical line containing the declaration keyword *also* contain a non-keyword, non-modifier prefix token before it… it is not really about `in`". The cheapest change that honours it without teaching the parser any prefix grammar is to strip comment text from `line` before both matches — a `--…$` tail strip plus a single-line `/- … -/` span strip. That alone turns `/-- Helper. -/ axiom evil : False` into a normally-matched, normally-NAMED site (strictly better than fail-safe: `evil` gets audited), and it simultaneously removes the false positives in the finding anchored at `#: repo-wide invariant that keeps comments s`. Note this is *stripping comment text*, not the "skip this line" path `implement/synthesis.md` rightly rejected — a `--` or `/- -/` inside a string literal truncates the line after the declaration name, so `_DECL_NAME_RE` still extracts. Then add a residual fail-safe arm for a leading token that is neither comment, attribute, modifier, nor keyword while a keyword appears later on the line (catches `deriving instance …`).
**Regression-guard:** `tests/test_handlers_lean_verify.py::TestPrefixedDeclarationSites::test_same_line_doc_comment_declaration_is_audited` — assert `_declaration_names("/-- d -/ axiom evil : False\ntheorem harmless : True := trivial")` yields `evil` among the names (or, if the fail-safe route is chosen instead, `complete is False`); plus a `deriving instance DecidableEq for Foo` case asserting `complete is False`.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage

**M1 — `.*?` defeats the `.match()` anchor: comments and tactic lines now count as sites** (MEDIUM)

**Where:** `server/handlers/lean_verify.py:471`
**Anchor:** `#: repo-wide invariant that keeps comments s`
**What:** The rationale block claims the regex is "Anchored with ``.match()`` like every other regex here — the repo-wide invariant that keeps comments safe", but `^\s*\S.*?\bin\s+…` matches the token anywhere on the line, so live in this tree `-- as used in theorem 3.2`, `/-- proved in theorem 2.1 -/`, `  simp [Finset.sum_comm] -- in def form` and `  exact h -- terms in class C` all now count as declaration sites — precisely the hazard `research/brief-2.md:186-190` flagged for an unanchored check, and broader than the "rare" residual `implement/synthesis.md` discloses.
**Why it matters:** Correct snippets are downgraded from `clean` to `unknown`, and the record's evidence string then asserts something false — `_audit_from_messages` emits "The snippet contains a declaration this tool could not name" when none exists, and on the empty-names path `_declaration_names("-- refer to the bound in lemma 2\n#check Nat")` → `([], False)` makes the caller emit "The snippet's declarations could not be named" for a snippet with zero declarations, which is inaccurate evidence attached to a trust axis (§4.9 rule 1).
**Proposed fix:** Strip comment text from `line` before matching, as described in the finding anchored at `            if _PREFIXED_DECL_SITE_RE.match(l` — one shared preprocessing step fixes both. If instead the current behaviour is deliberately accepted, then correct the rationale block (the anchor claim is false as written) and pin the accepted behaviour with a test, because today nothing stops it drifting in either direction.
**Regression-guard:** `tests/test_handlers_lean_verify.py::TestPrefixedDeclarationSites::test_comment_containing_in_theorem_is_not_a_site` — assert `_declaration_names("-- as used in theorem 3.2\ntheorem t : True := trivial") == (["t"], True)`. The existing `test_comment_mentioning_a_keyword_is_not_a_site` cannot catch this: its comments contain no `in`, so it passes identically with and without the new regex.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**L1 — `_PREFIXED_DECL_SITE_RE` is named for a broader class than it matches** (LOW)

**Where:** `server/handlers/lean_verify.py:472`
**Anchor:** `_PREFIXED_DECL_SITE_RE = re.compile(`
**What:** The constant name promises "prefixed declaration sites" in general, while the pattern requires an `in` combinator; the `#:` block above it lists what it deliberately leaves alone but never lists the prefixes it does not cover at all.
**Why it matters:** A future maintainer reading the name will reasonably assume the prefix class is handled and not re-check it, which is how the residual hole above survives a second review.
**Proposed fix:** Rename to `_IN_PREFIXED_DECL_SITE_RE` (or `_IN_COMBINATOR_DECL_SITE_RE`) and add one line to the `#:` block naming the prefixes still NOT covered (same-line doc/block comment, `deriving instance`).
**Regression-guard:** Not required at this severity.
**Source critic:** milestone-adversary-critic
**Source axis:** Dead code / leftovers

## What was done well

- **Monotone by construction.** The new branch is inside the
  `not _DECL_SITE_RE.match(line)` arm and only ever increments `sites`, so the
  `sites == len(names)` fail-safe can only move True → False. The claim in the
  commit body and the `#:` block that the change "can never admit a declaration
  that went unaudited" holds structurally, not just empirically.
- **Keyed on the combinator, not on the two prefixes the issue named.** Three
  lines close `set_option`, `open`, `variable`, `universe` and `attribute` at
  once. Enumerating the reported two would have shipped with three siblings
  still open, and the constraint "do not teach the regex `set_option`/`open`
  grammar" was honoured.
- **Reuses `_MODIFIER_ALT` / `_KEYWORD_ALT`**, so adding a future declaration
  keyword or modifier propagates to both regexes with no second edit site.
- **The controls in the new test class are genuinely adversarial**, not
  decorative: multi-line `open X in`, the Mathlib `∑ i in Finset.range n`
  binder, bare `open`/`variable`/`universe` lines, and
  `test_the_whole_chain_refuses_to_report_clean`, which drives
  `_audit_from_messages` and asserts the *record* reads `unknown` rather than
  stopping at the tuple.
- **The regression suite was verified to actually pin the bug** — 8 of the 12
  new tests fail with the pre-fix source stashed back in, 4 controls pass. That
  is the step most "regression tests" skip, and it is what makes the 12 tests
  worth their line count.
- **The AC#4 reason-string delta was disclosed under its own heading** rather
  than buried, which is what let it be evaluated as a choice; the new string
  is genuinely more accurate for the only-a-prefixed-declaration snippet.
- **Blast radius was re-verified at source and holds independently:** no
  `LEAN_VERIFY.description`, no `TOOL_SCHEMA_VERSION`, no pinned schema hash,
  and `status` / `compilation_success` untouched — so no CLAUDE.md §9 re-pin
  is owed.
- **Process hygiene is clean:** signed (`%G?` = `G`), conventional subject 39
  chars after the type prefix, mandated `Co-Authored-By: Claude Opus 5`
  trailer, `Closes #382`, no `plans/*/roadmap.yaml` or journal edit, no
  push/publish/deploy in the diff, and the required external write declared as
  a Phase-4 requirement rather than performed.
- **The gate caveat was recorded rather than papered over** — the 8
  environment-bound failures were measured at HEAD with the diff stashed
  *before* Phase 2, so this milestone's contribution is provably zero.

Severity counts: C1 H1 M1 L1

## Recommended rectification order

C1, H1, M1, L1

Note on ordering: H1 and M1 share one fix (strip comment text from the line
before matching), so rectifying H1 first makes M1 largely mechanical.
