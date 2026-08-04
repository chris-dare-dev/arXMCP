# Critique — adhoc-20260804-c8e6048 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** d0082f0acd18117cebf029599ed0bbb6abb97fb4..e2651e9d80bd865ecaa361cfdb254ed62fd7c750
**Diff stats:** 2 files, 184 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

Every stated acceptance criterion is met and independently reproduced against this working tree, the fix moves `complete` only in the safe direction, and the research claim that no frozen schema, no `LEAN_VERIFY.description`, no `TOOL_SCHEMA_VERSION` and neither pinned hash is touched is VERIFIED rather than taken on trust. The one substantive problem is scope: the landed regex keys on the `in` combinator, but the defect the research itself characterised is same-line co-occurrence of an unrecognised token and a declaration keyword, and a snippet quoted verbatim from mathlib4 in the milestone's own brief-2 still returns `outcome="clean"` with a declaration dropped. That residual is not recorded anywhere in the implementation synthesis, so closing #382 on this diff would advertise a class as shut while a real Lean idiom still rides through it. Nothing here is a regression and nothing blocks the commit, so this is fixes-then-ship rather than do-not-ship.

## Executive summary

- [HIGH] `deriving instance ToExpr for ULift` — quoted verbatim from mathlib4 in `research/brief-2.md:141` — still yields `names=['harmless'], complete=True, outcome='clean'` in this tree after the fix; `alias` and `meta <mod> instance` behave identically.
- [HIGH] brief-2:155-158 states the defect "is not really about `in`… it's about same-line co-occurrence of an unrecognized token and a keyword"; the landed regex requires a literal `in`, so it closes a subfamily and the implement synthesis does not record the remainder as residual.
- [MEDIUM] The accepted false positive is real and reproduced (`-- as shown in theorem 3.2 of the paper` ⇒ `complete=False`) but has no pinning test; the control test named for that shape uses a comment with no `in` and therefore never exercises the branch the diff added.
- [MEDIUM] `_audit_from_messages`' user-facing `reason` still enumerates only "an unnamed instance or an unrecognized declaration form"; the `set_option … in theorem` cause the diff exists to surface is never named, though the private docstring was updated.
- [MEDIUM] The wire-visible consequence is untested: `TestAxiomHygieneOnTheWire` already has the fake-REPL fixtures, but the new class stops at the private helpers.
- [LOW] The abstention string the diff newly routes to omits the emphatic "this is NOT a clean verdict" wording its sibling branch carries.
- [LOW] The head SHA in the Phase-3 dispatch prompt does not resolve; `state.json` carries the correct one.
- [CLEAN] Cache byte-stability, MCP spec compliance, math fidelity, security threat model, local-first, tier sequencing and no-fork all verified clean — `server/tools.py`, `server/prompts.py` and every hash pin are outside the diff, `ruff check .` passes, and the commit is GPG-signed with the required co-author trailer.

## Findings

**H1 — Fail-safe still misses non-in-combinator declaration sites** (HIGH)

**Where:** `server/handlers/lean_verify.py:472`
**Anchor:** `_PREFIXED_DECL_SITE_RE = re.compile(`
**What:** The new regex requires a literal `in` combinator, so a declaration keyword preceded on the same line by any OTHER unrecognised token is still invisible — reproduced live in this tree, `_declaration_names("set_option autoImplicit true in\nderiving instance ToExpr for ULift\ntheorem harmless : True := trivial")` returns `(['harmless'], True)` and `_audit_from_messages` scores it `outcome='clean'`, with `alias sneaky := False.elim` and `meta unsafe instance foo …` behaving identically.
**Why it matters:** That is bug #382 unchanged for those shapes — an unaudited declaration riding inside a `clean` `axiom_audit` verdict, the exact invariant CLAUDE.md §4.9 rule 1 and §4.10 rule 3 name as load-bearing — and the `deriving instance` line is quoted verbatim from live mathlib4 at `research/brief-2.md:141`, so it is reachable, not hypothetical.
**Proposed fix:** Add one more anchored, nameless-site regex beside `_PREFIXED_DECL_SITE_RE` and count it in the same `sites += 1` arm — `re.compile(r"^\s*(?:deriving\s+instance|alias|meta)\b")`. Anchoring at `^\s*` preserves the comment-safety invariant brief-2:184-192 flags (a comment line starts `--` or `/-`), and requiring `deriving\s+instance` rather than bare `deriving` keeps a trailing `deriving Repr` continuation line from becoming a spurious site. If Phase 4 defers instead, the residual MUST be written into the `_PREFIXED_DECL_SITE_RE` docstring and a follow-up issue, because the current text reads as if the class is closed.
**Regression-guard:** `tests/test_handlers_lean_verify.py::TestPrefixedDeclarationSites::test_deriving_instance_is_not_silently_dropped` asserting `_declaration_names("deriving instance ToExpr for ULift\ntheorem harmless : True := trivial") == (["harmless"], False)`, plus the same for `alias`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** trust-language / evidence-ledger (CLAUDE.md 4.9)

**M1 — Accepted comment false-positive has no pinning test** (MEDIUM)

**Where:** `tests/test_handlers_lean_verify.py:2438`
**Anchor:** `    def test_comment_mentioning_a_keyword_is_no`
**What:** The synthesis records "a comment of the exact shape `-- … in theorem …` would be counted as a site" as an accepted cost — confirmed live, `_declaration_names("-- as shown in theorem 3.2 of the paper\ntheorem harmless : True := trivial")` returns `(['harmless'], False)` — yet the only comment control asserts the opposite-shaped input (`-- prove this theorem using induction`, which contains no `in`) and so never touches the branch the diff added.
**Why it matters:** An accepted cost with no test is indistinguishable from an unnoticed bug six months later, and the test's name plus the docstring at `:465-466` together read as "comments are safe", which is only true for comments without a standalone `in`.
**Proposed fix:** Add a test that asserts the false positive as INTENDED behaviour and says so in its docstring, e.g. `test_comment_with_in_and_keyword_is_an_accepted_false_positive` asserting `(["harmless"], False)` for the line above. Pinning it in the safe direction also stops a future "cleanup" from silently relaxing the regex toward a false clean.
**Regression-guard:** `tests/test_handlers_lean_verify.py::TestPrefixedDeclarationSites::test_comment_with_in_and_keyword_is_an_accepted_false_positive`
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**M2 — axiom_audit reason string never names the new failure cause** (MEDIUM)

**Where:** `server/handlers/lean_verify.py:652`
**Anchor:** `            "The snippet contains a declara`
**What:** The `complete=False` reason still enumerates only "an unnamed instance or an unrecognized declaration form" — the `set_option … in theorem` / `open … in theorem` cause that the diff exists to route here is never named, even though `_declaration_names`' own docstring at `:511-512` was updated to name it.
**Why it matters:** This string is the attached evidence for the trust axis under CLAUDE.md §4.9 rule 1 and the evidence-ledger standard; the calling agent gets a degraded verdict with no actionable statement of what it could not name, so it cannot re-submit the snippet in a form that audits.
**Proposed fix:** Extend the tuple in the reason to name the combinator case, e.g. "an unnamed instance, a declaration behind an unrecognised `… in` combinator such as `set_option … in theorem t`, or an exotic form". Three-line string edit; no schema, no wire-shape change.
**Regression-guard:** Optional — extend `test_the_whole_chain_refuses_to_report_clean` to assert the reason mentions `set_option` or `in`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** trust-language / evidence-ledger (CLAUDE.md 4.9)

**M3 — No wire-level regression test for the prefixed-site drop** (MEDIUM)

**Where:** `tests/test_handlers_lean_verify.py:2342`
**Anchor:** `class TestPrefixedDeclarationSites:`
**What:** All 12 new tests exercise the private helpers `_declaration_names` and `_audit_from_messages`; nothing drives the reported bug through `_attach_axiom_audit` / `handle_lean_verify` to assert that `result["axiom_audit"]["outcome"]` is not `clean`, even though `TestAxiomHygieneOnTheWire` at `:2577` already owns the fake-REPL fixtures that make it a ~15-line addition.
**Why it matters:** The bug's consumer-visible symptom is a wire payload reading `clean`; a refactor of `_attach_axiom_audit`'s plumbing could reintroduce the symptom with every helper test still green.
**Proposed fix:** Add one test to `TestAxiomHygieneOnTheWire` that submits `set_option maxHeartbeats 400000 in theorem sneaky : False := sorry` plus `theorem harmless : True := trivial`, stubs the REPL to answer clean for `harmless`, and asserts `result["axiom_audit"]["outcome"] == "unknown"`.
**Regression-guard:** `tests/test_handlers_lean_verify.py::TestAxiomHygieneOnTheWire::test_prefixed_declaration_blocks_a_clean_verdict`
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

**L1 — Abstention reason drops the not-a-clean-verdict disclaimer** (LOW)

**Where:** `server/handlers/lean_verify.py:1165`
**Anchor:** `            else "The snippet's declarations`
**What:** The diff makes the `not complete` arm of this ternary materially more reachable — any snippet whose only declaration is `set_option … in theorem X` now lands here instead of the `complete` arm — and that arm's string omits the emphatic "this is NOT a clean verdict" wording its sibling at `:1163` carries.
**Why it matters:** `outcome` already carries the ordinal level correctly, so this is presentation only, but the sibling's disclaimer exists because agents conflate "no answer" with "passed", and the diff shifts traffic onto the weaker string.
**Proposed fix:** Append the same clause: "…the axiom closure could not be resolved — this is NOT a clean verdict."
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** trust-language / evidence-ledger (CLAUDE.md 4.9)

**L2 — Dispatch prompt COMMIT_RANGE head SHA does not resolve** (LOW)

**Where:** no specific file
**What:** The Phase-3 dispatch prompt gave the head as `e2651e9d80bd865ecaa361cfdb254ed62fd7c8f5`, which `git rev-parse --verify` rejects with "Needed a single revision"; the real commit is `…fd7c750`, which `state.json` records correctly.
**Why it matters:** Phase 4's re-verify gate re-resolves the range to re-locate each finding's cited line; a head SHA that does not parse fails the gate for reasons unrelated to any finding, and would be misread as a stale-citation rate.
**Proposed fix:** Take the range from `state.json.implementation_commit_range` rather than re-typing it into critic prompts.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** test surface

## What was done well

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

Severity counts: C0 H1 M3 L2

## Recommended rectification order

H1, M2, M1, M3, L1, L2

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
