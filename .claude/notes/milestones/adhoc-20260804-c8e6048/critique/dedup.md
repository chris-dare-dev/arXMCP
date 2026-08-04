# Critique (merged) — adhoc-20260804-c8e6048

**Critics:** milestone-adversary-critic, milestone-arxmcp-critic
**Commit range:** d0082f0acd18117cebf029599ed0bbb6abb97fb4..e2651e9d80bd865ecaa361cfdb254ed62fd7c750
**Diff stats:** 2 files, 187 LOC
**Critique format version:** 1.0

> **Merge note.** Each critic authored its ids from 1 within its own file, so
> they collided across files. `findings.py merge` renumbered them into one
> gapless per-severity sequence in critic dispatch order; bodies are verbatim.
> **Phase 4 dispositions attach to the MERGED ids below**, not to the ids in
> the per-critic files. Re-running merge after a critic file changes will shift
> these ids - see milestone-pipeline-critique-format.md.
>
> - `milestone-adversary-critic` (adversary.md): ids unchanged
> - `milestone-arxmcp-critic` (arxmcp.md): H1->H2, M1->M2, M2->M3, M3->M4, L1->L2, L2->L3

## Verdict

**SHIP-WITH-FIXES** — the most severe of the per-critic verdicts below.

### milestone-adversary-critic — SHIP-WITH-FIXES

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

### milestone-arxmcp-critic — SHIP-WITH-FIXES

SHIP-WITH-FIXES

Every stated acceptance criterion is met and independently reproduced against this working tree, the fix moves `complete` only in the safe direction, and the research claim that no frozen schema, no `LEAN_VERIFY.description`, no `TOOL_SCHEMA_VERSION` and neither pinned hash is touched is VERIFIED rather than taken on trust. The one substantive problem is scope: the landed regex keys on the `in` combinator, but the defect the research itself characterised is same-line co-occurrence of an unrecognised token and a declaration keyword, and a snippet quoted verbatim from mathlib4 in the milestone's own brief-2 still returns `outcome="clean"` with a declaration dropped. That residual is not recorded anywhere in the implementation synthesis, so closing #382 on this diff would advertise a class as shut while a real Lean idiom still rides through it. Nothing here is a regression and nothing blocks the commit, so this is fixes-then-ship rather than do-not-ship.

## Executive summary — milestone-adversary-critic

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

## Executive summary — milestone-arxmcp-critic

- [HIGH] `deriving instance ToExpr for ULift` — quoted verbatim from mathlib4 in `research/brief-2.md:141` — still yields `names=['harmless'], complete=True, outcome='clean'` in this tree after the fix; `alias` and `meta <mod> instance` behave identically.
- [HIGH] brief-2:155-158 states the defect "is not really about `in`… it's about same-line co-occurrence of an unrecognized token and a keyword"; the landed regex requires a literal `in`, so it closes a subfamily and the implement synthesis does not record the remainder as residual.
- [MEDIUM] The accepted false positive is real and reproduced (`-- as shown in theorem 3.2 of the paper` ⇒ `complete=False`) but has no pinning test; the control test named for that shape uses a comment with no `in` and therefore never exercises the branch the diff added.
- [MEDIUM] `_audit_from_messages`' user-facing `reason` still enumerates only "an unnamed instance or an unrecognized declaration form"; the `set_option … in theorem` cause the diff exists to surface is never named, though the private docstring was updated.
- [MEDIUM] The wire-visible consequence is untested: `TestAxiomHygieneOnTheWire` already has the fake-REPL fixtures, but the new class stops at the private helpers.
- [LOW] The abstention string the diff newly routes to omits the emphatic "this is NOT a clean verdict" wording its sibling branch carries.
- [LOW] The head SHA in the Phase-3 dispatch prompt does not resolve; `state.json` carries the correct one.
- [CLEAN] Cache byte-stability, MCP spec compliance, math fidelity, security threat model, local-first, tier sequencing and no-fork all verified clean — `server/tools.py`, `server/prompts.py` and every hash pin are outside the diff, `ruff check .` passes, and the commit is GPG-signed with the required co-author trailer.

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

**H2 — Fail-safe still misses non-in-combinator declaration sites** (HIGH)

**Where:** `server/handlers/lean_verify.py:472`
**Anchor:** `_PREFIXED_DECL_SITE_RE = re.compile(`
**What:** The new regex requires a literal `in` combinator, so a declaration keyword preceded on the same line by any OTHER unrecognised token is still invisible — reproduced live in this tree, `_declaration_names("set_option autoImplicit true in\nderiving instance ToExpr for ULift\ntheorem harmless : True := trivial")` returns `(['harmless'], True)` and `_audit_from_messages` scores it `outcome='clean'`, with `alias sneaky := False.elim` and `meta unsafe instance foo …` behaving identically.
**Why it matters:** That is bug #382 unchanged for those shapes — an unaudited declaration riding inside a `clean` `axiom_audit` verdict, the exact invariant CLAUDE.md §4.9 rule 1 and §4.10 rule 3 name as load-bearing — and the `deriving instance` line is quoted verbatim from live mathlib4 at `research/brief-2.md:141`, so it is reachable, not hypothetical.
**Proposed fix:** Add one more anchored, nameless-site regex beside `_PREFIXED_DECL_SITE_RE` and count it in the same `sites += 1` arm — `re.compile(r"^\s*(?:deriving\s+instance|alias|meta)\b")`. Anchoring at `^\s*` preserves the comment-safety invariant brief-2:184-192 flags (a comment line starts `--` or `/-`), and requiring `deriving\s+instance` rather than bare `deriving` keeps a trailing `deriving Repr` continuation line from becoming a spurious site. If Phase 4 defers instead, the residual MUST be written into the `_PREFIXED_DECL_SITE_RE` docstring and a follow-up issue, because the current text reads as if the class is closed.
**Regression-guard:** `tests/test_handlers_lean_verify.py::TestPrefixedDeclarationSites::test_deriving_instance_is_not_silently_dropped` asserting `_declaration_names("deriving instance ToExpr for ULift\ntheorem harmless : True := trivial") == (["harmless"], False)`, plus the same for `alias`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** trust-language / evidence-ledger (CLAUDE.md 4.9)

**M1 — `.*?` defeats the `.match()` anchor: comments and tactic lines now count as sites** (MEDIUM)

**Where:** `server/handlers/lean_verify.py:471`
**Anchor:** `#: repo-wide invariant that keeps comments s`
**What:** The rationale block claims the regex is "Anchored with ``.match()`` like every other regex here — the repo-wide invariant that keeps comments safe", but `^\s*\S.*?\bin\s+…` matches the token anywhere on the line, so live in this tree `-- as used in theorem 3.2`, `/-- proved in theorem 2.1 -/`, `  simp [Finset.sum_comm] -- in def form` and `  exact h -- terms in class C` all now count as declaration sites — precisely the hazard `research/brief-2.md:186-190` flagged for an unanchored check, and broader than the "rare" residual `implement/synthesis.md` discloses.
**Why it matters:** Correct snippets are downgraded from `clean` to `unknown`, and the record's evidence string then asserts something false — `_audit_from_messages` emits "The snippet contains a declaration this tool could not name" when none exists, and on the empty-names path `_declaration_names("-- refer to the bound in lemma 2\n#check Nat")` → `([], False)` makes the caller emit "The snippet's declarations could not be named" for a snippet with zero declarations, which is inaccurate evidence attached to a trust axis (§4.9 rule 1).
**Proposed fix:** Strip comment text from `line` before matching, as described in the finding anchored at `            if _PREFIXED_DECL_SITE_RE.match(l` — one shared preprocessing step fixes both. If instead the current behaviour is deliberately accepted, then correct the rationale block (the anchor claim is false as written) and pin the accepted behaviour with a test, because today nothing stops it drifting in either direction.
**Regression-guard:** `tests/test_handlers_lean_verify.py::TestPrefixedDeclarationSites::test_comment_containing_in_theorem_is_not_a_site` — assert `_declaration_names("-- as used in theorem 3.2\ntheorem t : True := trivial") == (["t"], True)`. The existing `test_comment_mentioning_a_keyword_is_not_a_site` cannot catch this: its comments contain no `in`, so it passes identically with and without the new regex.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness

**M2 — Accepted comment false-positive has no pinning test** (MEDIUM)

**Where:** `tests/test_handlers_lean_verify.py:2438`
**Anchor:** `    def test_comment_mentioning_a_keyword_is_no`
**What:** The synthesis records "a comment of the exact shape `-- … in theorem …` would be counted as a site" as an accepted cost — confirmed live, `_declaration_names("-- as shown in theorem 3.2 of the paper\ntheorem harmless : True := trivial")` returns `(['harmless'], False)` — yet the only comment control asserts the opposite-shaped input (`-- prove this theorem using induction`, which contains no `in`) and so never touches the branch the diff added.
**Why it matters:** An accepted cost with no test is indistinguishable from an unnoticed bug six months later, and the test's name plus the docstring at `:465-466` together read as "comments are safe", which is only true for comments without a standalone `in`.
**Proposed fix:** Add a test that asserts the false positive as INTENDED behaviour and says so in its docstring, e.g. `test_comment_with_in_and_keyword_is_an_accepted_false_positive` asserting `(["harmless"], False)` for the line above. Pinning it in the safe direction also stops a future "cleanup" from silently relaxing the regex toward a false clean.
**Regression-guard:** `tests/test_handlers_lean_verify.py::TestPrefixedDeclarationSites::test_comment_with_in_and_keyword_is_an_accepted_false_positive`
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M3 — axiom_audit reason string never names the new failure cause** (MEDIUM)

**Where:** `server/handlers/lean_verify.py:652`
**Anchor:** `            "The snippet contains a declara`
**What:** The `complete=False` reason still enumerates only "an unnamed instance or an unrecognized declaration form" — the `set_option … in theorem` / `open … in theorem` cause that the diff exists to route here is never named, even though `_declaration_names`' own docstring at `:511-512` was updated to name it.
**Why it matters:** This string is the attached evidence for the trust axis under CLAUDE.md §4.9 rule 1 and the evidence-ledger standard; the calling agent gets a degraded verdict with no actionable statement of what it could not name, so it cannot re-submit the snippet in a form that audits.
**Proposed fix:** Extend the tuple in the reason to name the combinator case, e.g. "an unnamed instance, a declaration behind an unrecognised `… in` combinator such as `set_option … in theorem t`, or an exotic form". Three-line string edit; no schema, no wire-shape change.
**Regression-guard:** Optional — extend `test_the_whole_chain_refuses_to_report_clean` to assert the reason mentions `set_option` or `in`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** trust-language / evidence-ledger (CLAUDE.md 4.9)

**M4 — No wire-level regression test for the prefixed-site drop** (MEDIUM)

**Where:** `tests/test_handlers_lean_verify.py:2342`
**Anchor:** `class TestPrefixedDeclarationSites:`
**What:** All 12 new tests exercise the private helpers `_declaration_names` and `_audit_from_messages`; nothing drives the reported bug through `_attach_axiom_audit` / `handle_lean_verify` to assert that `result["axiom_audit"]["outcome"]` is not `clean`, even though `TestAxiomHygieneOnTheWire` at `:2577` already owns the fake-REPL fixtures that make it a ~15-line addition.
**Why it matters:** The bug's consumer-visible symptom is a wire payload reading `clean`; a refactor of `_attach_axiom_audit`'s plumbing could reintroduce the symptom with every helper test still green.
**Proposed fix:** Add one test to `TestAxiomHygieneOnTheWire` that submits `set_option maxHeartbeats 400000 in theorem sneaky : False := sorry` plus `theorem harmless : True := trivial`, stubs the REPL to answer clean for `harmless`, and asserts `result["axiom_audit"]["outcome"] == "unknown"`.
**Regression-guard:** `tests/test_handlers_lean_verify.py::TestAxiomHygieneOnTheWire::test_prefixed_declaration_blocks_a_clean_verdict`
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L1 — `_PREFIXED_DECL_SITE_RE` is named for a broader class than it matches** (LOW)

**Where:** `server/handlers/lean_verify.py:472`
**Anchor:** `_PREFIXED_DECL_SITE_RE = re.compile(`
**What:** The constant name promises "prefixed declaration sites" in general, while the pattern requires an `in` combinator; the `#:` block above it lists what it deliberately leaves alone but never lists the prefixes it does not cover at all.
**Why it matters:** A future maintainer reading the name will reasonably assume the prefix class is handled and not re-check it, which is how the residual hole above survives a second review.
**Proposed fix:** Rename to `_IN_PREFIXED_DECL_SITE_RE` (or `_IN_COMBINATOR_DECL_SITE_RE`) and add one line to the `#:` block naming the prefixes still NOT covered (same-line doc/block comment, `deriving instance`).
**Regression-guard:** Not required at this severity.
**Source critic:** milestone-adversary-critic
**Source axis:** Dead code / leftovers

**L2 — Abstention reason drops the not-a-clean-verdict disclaimer** (LOW)

**Where:** `server/handlers/lean_verify.py:1165`
**Anchor:** `            else "The snippet's declarations`
**What:** The diff makes the `not complete` arm of this ternary materially more reachable — any snippet whose only declaration is `set_option … in theorem X` now lands here instead of the `complete` arm — and that arm's string omits the emphatic "this is NOT a clean verdict" wording its sibling at `:1163` carries.
**Why it matters:** `outcome` already carries the ordinal level correctly, so this is presentation only, but the sibling's disclaimer exists because agents conflate "no answer" with "passed", and the diff shifts traffic onto the weaker string.
**Proposed fix:** Append the same clause: "…the axiom closure could not be resolved — this is NOT a clean verdict."
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** trust-language / evidence-ledger (CLAUDE.md 4.9)

**L3 — Dispatch prompt COMMIT_RANGE head SHA does not resolve** (LOW)

**Where:** no specific file
**What:** The Phase-3 dispatch prompt gave the head as `e2651e9d80bd865ecaa361cfdb254ed62fd7c8f5`, which `git rev-parse --verify` rejects with "Needed a single revision"; the real commit is `…fd7c750`, which `state.json` records correctly.
**Why it matters:** Phase 4's re-verify gate re-resolves the range to re-locate each finding's cited line; a head SHA that does not parse fails the gate for reasons unrelated to any finding, and would be misread as a stale-citation rate.
**Proposed fix:** Take the range from `state.json.implementation_commit_range` rather than re-typing it into critic prompts.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

## What was done well

### From milestone-adversary-critic

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

### From milestone-arxmcp-critic

- The blast-radius claim was verifiable and is VERIFIED: the diff touches exactly two files, and `server/tools.py`, `server/prompts.py`, `LEAN_VERIFY.description`, `TOOL_SCHEMA_VERSION` and every `EXPECTED_*_SHA256` pin are all outside it — `tests/test_server_tool_schema.py` passes unchanged, so BP1 byte-stability is intact.
- The fix respects the mandated shape rather than the tempting one: it counts a site with no extractable name instead of teaching the regex `set_option` / `open` grammar, so the change can only move `complete` True to False and can never admit an unaudited declaration.
- The `^\s*`-anchored `.match()` discipline that brief-2:184-192 identified as the load-bearing comment-safety property is preserved, and the docstring says why — a future editor is told what the anchor is protecting.
- Keying on the `in` combinator rather than enumerating `set_option` / `open` closed the three siblings research found (`variable`, `universe`, `attribute [...]`) for free, and all three are pinned as tests.
- The pre-fix failure was measured, not assumed: 8 of 12 new tests fail against the stashed pre-fix module and the 4 controls pass, so this is a regression suite rather than a tautology.
- The behaviour delta the brief did not ask for — the changed abstention reason for the only-a-prefixed-declaration snippet — was surfaced under its own heading instead of buried, and the argument that it is strictly more accurate holds.
- The known false positive was disclosed with reasoning about direction (abstention, never a false clean) and an explicit refusal to add comment-stripping, which would have been the dangerous fix.
- The suite baseline was measured before any Phase-2 edit and the 8 environment-bound failures named individually, and this critic re-ran the full suite independently and got exactly that set — 6 `tests/security/test_latexml_sandbox.py`, 1 `test_win32_bat_invoked_via_perl`, 1 `test_cite_neighbors_wired` — with zero new failures; `ruff check .` reports "All checks passed!" and no `assert` appears in the `server/` half of the diff.
- The commit is GPG-signed with a good signature and carries the mandatory `Co-Authored-By` trailer naming the authoring model, per CLAUDE.md §4.3.
- Six of the eight project axes are untouched by construction and were confirmed so: no dependency, submodule or vendored-source change (no-fork), no LaTeX/MathML path (math fidelity), no identifier-validation or middleware change (security), no wire-shape change (MCP spec), no new paths or services (local-first), no dependency on a pending tier (tier sequencing).

Severity counts: C1 H2 M4 L3


## Cross-critic agreement

The following findings cluster within 5 lines of each other in the same file. Multiple critics flagged the same area - these are the strongest signals to fix first.

- **M1, H2, L1** at `server/handlers/lean_verify.py:471-472` (HIGH): `.*?` defeats the `.match()` anchor: comments and tactic lines now count as sites; Fail-safe still misses non-in-combinator declaration sites; `_PREFIXED_DECL_SITE_RE` is named for a broader class than it matches

## Recommended rectification order

C1, H1, H2, M1, M3, M2, M4, L1, L2, L3

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
