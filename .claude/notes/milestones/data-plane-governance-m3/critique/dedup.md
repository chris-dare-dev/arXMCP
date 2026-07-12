# Critique — data-plane-governance-m3 — merged (adversary + arxmcp)

**Critic:** milestone-adversary-critic + milestone-arxmcp-critic (orchestrator-merged, id-remapped)
**Commit range:** 23b8628..1ff9c56
**Diff stats:** 7 files, 458 LOC (454 insertions, 4 deletions)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. Both critics independently verified every load-bearing factual claim against
source and found the policy accurate — the `lean_verify` defect (`:290-298`), the `get_definitions`
gap, the eleven R0 axes, the `rigor.py` cross-walk, the Appendix B MCP-surface census, and the
AC2 "exactly three absence claims" exhaustiveness all hold. No CRITICAL, no external-write or
one-writer violation, commits signed + trailered. One mandatory HIGH (diff size, mitigated
docs-only), two MEDIUM doc-precision fixes (an AC3 placement asymmetry; a drift-prone cross-repo
line cite), and two LOW polish items.

## Executive summary

- [HIGH] Diff is 458 LOC (> 400) — mandatory review-quality-at-risk flag; mitigated (docs-only,
  two greenfield co-dependent policy docs, no runtime/test surface; two independent opus critics
  performed full linear factual re-verification).
- [MEDIUM] AC3 asymmetry: R5's `## Gates` block does not reference the trust-language policy by
  path (only its KR3 does), whereas R3's `## Gates` "Trust gate" was updated.
- [MEDIUM] `trust-language-policy.md:80` cites the BridgelandStability comparator-stub `sorry` at
  `Spec.lean:52`, but the `sorry` is at `:57` (`:52` is the theorem type signature); cross-repo,
  drift-prone.
- [LOW] The `lean_verify` code block reformats the source `if/elif/else` (`:293-298`) as a ternary
  under a `:290-298` cite; semantics identical, "computes:" lead-in mitigates.
- [LOW] The R5 evidence-ledger census omits the template's explicit `Scope:` field that R4/R6 carry.
- [CLEAN] No external write, no one-writer touch, both commits GPG-signed + `Co-Authored-By: Claude
  Opus 4.8`, no repo-fact contradiction (§4.9 consistent with §7 / §6 / §4.7 / §4.8).

## Findings

**H1 — Diff exceeds 400 LOC (mandatory review-quality flag)** (HIGH)

**Where:** no specific file
**What:** The diff changes 458 LOC (454 insertions, 4 deletions across 7 files), over the 400-LOC threshold that auto-triggers a review-quality-at-risk finding.
**Why it matters:** Large diffs statistically hide defects; the threshold is a non-waivable tripwire so size is never silently accepted.
**Proposed fix:** No code fix — assessed honestly: the bulk is two greenfield constitutional docs (`trust-language-policy.md` 228 lines + `evidence-ledger-standard.md` 132 lines) plus a 29-line CLAUDE.md section and small brief annotations. Docs-only, no runtime/test surface, each file reviewable top-to-bottom; splitting the two co-dependent policies across commits would have harmed reviewability more than helped. Mitigation is strong; the finding is logged, not blocking.
**Regression-guard:** N/A (process flag, not a code defect); the milestone's own doc-scanning gate `tests/test_constitution_ui_claims.py` covers the CLAUDE.md delta.
**Source critic:** milestone-adversary-critic
**Source axis:** Diff size (auto-finding)

**M1 — R5's Gates section does not reference the trust-language policy by path** (MEDIUM)

**Where:** `.claude/roadmap-briefs/R5-formal-target-registry.md:138`
**Anchor:** `- **Exit:** every entry has zero non-all`
**What:** AC3 requires "the R3/R5 briefs' tool-surface gates reference [the policy]" (roadmap.yaml:30,96); R3's `## Gates` "Trust gate" (`R3:142`) was updated with the by-path reference, but R5's `## Gates` block (Entry `:136` / Exit `:138`) was not — R5's only by-path reference lives in Key result 3 (`R5:66`, "trust record per the trust-language policy").
**Why it matters:** A future reader auditing R5's `## Gates` section for policy conformance will not find the by-path link there; the R3/R5 symmetry the AC pairs is broken, so the criterion is met by a lenient reading (the brief references the policy) but not by a strict one (the *gate* references it).
**Proposed fix:** Add a clause to R5's Exit gate (`:138`) — e.g. "...an explicit assumption frontier conforming to the trust-language policy (`.claude/docs/trust-language-policy.md`); ..." — mirroring the placement R3 used. ~1 line.
**Regression-guard:** A doc-accuracy guard (the future census/policy-reference test the standard itself contemplates) asserting both `R3` and `R5` `## Gates` sections contain the string `docs/trust-language-policy.md`.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage (AC3)

**M2 — Comparator-stub `sorry` cited at wrong line (`Spec.lean:52` vs `:57`)** (MEDIUM)

**Where:** `.claude/docs/trust-language-policy.md:80`
**Anchor:** `| 6 | **proof closure** | Are there no`
**What:** The axis-6 worked example cites "BridgelandStability's one comparator-stub `sorry` (`Spec.lean:52`)", but in `bstab/BridgelandStability/Spec.lean` line 52 is the first line of the theorem's existential conclusion type (`∃ (E : Type u) …`); the actual `sorry` proof term is on line 57. (There are two `sorry` string matches in the file: line 44 is a docstring mention, line 57 is the sole real proof-sorry — so the "one comparator-stub sorry" count is correct; only the line number is off.)
**Why it matters:** A milestone whose entire thesis is precise, re-verifiable trust citations ("internal codebase facts are cited at `file:line` and re-verified on change" — CLAUDE.md §4.9) should not ship a citation that does not resolve to the thing it names; a reader jumping to :52 sees a type signature, not the gap. The citation is also cross-repo into a Lean repo not under arXMCP change control, so the line number is drift-prone independent of this error.
**Proposed fix:** Change `Spec.lean:52` to `Spec.lean:57`, or (drift-proof, preferred) cite the declaration by name — `Spec.lean::NumericalStabilityCondition.existsComplexManifoldOnConnectedComponent` — since cross-repo line numbers are not pinned by anything in this diff.
**Regression-guard:** Optional (MEDIUM). If a future doc-accuracy guard test is added (§6 of the evidence-ledger foreshadows one), assert the cited line in `Spec.lean` contains the token `sorry`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** Axis 2 — math/domain fidelity

**L1 — lean_verify code block reformats source if/elif/else as a ternary** (LOW)

**Where:** `.claude/docs/trust-language-policy.md:28`
**Anchor:** `status = "error" if has_error else "sorr`
**What:** §2 presents a fenced `python` block under a `server/handlers/lean_verify.py:290-298` cite, but condenses the source's four-line `if has_error: … elif has_sorry: … else:` (`:293-298`) into a single ternary; a reader may expect a fenced block beneath a `file:line` cite to be verbatim.
**Why it matters:** In a constitutional doc that grounds its ban in "the exact logic", a paraphrased-as-verbatim code block is a small fidelity gap — though the semantics are identical and the "computes:" lead-in signals paraphrase, so this is cosmetic.
**Proposed fix:** Either paste the source `if/elif/else` verbatim, or change the fence intro to make the condensation explicit (e.g. "computes, in effect:"). Defer by default.
**Regression-guard:** Optional; none warranted for a semantics-preserving paraphrase.
**Source critic:** milestone-adversary-critic
**Source axis:** Correctness (factual fidelity)

**L2 — R5 evidence-ledger census omits the template's explicit Scope field** (LOW)

**Where:** `.claude/roadmap-briefs/R5-formal-target-registry.md:150`
**Anchor:** `> formalizations as a queryable API? **D`
**What:** The evidence-ledger `§4` template mandates a `Scope note:` field, and the R4 (`Scope: exhaustive…`) and R6 (`Not checked:…`) censuses both carry one, but the R5 census carries none — scope is only implicit in the verdict tail ("none is the pinned registry this track scopes").
**Why it matters:** Minor internal inconsistency against the standard's own template on the very milestone that introduces it; it is still admissible under the `§2` five-field bar (set/queries/date/verdict are present), so this is polish, not a compliance failure.
**Proposed fix:** Append a `**Scope:** scoped over the seven named systems; closed commercial/non-English registries not checked.` line to the R5 census block. Defer by default.
**Regression-guard:** Optional; a future census-linter could assert each census block contains a `Scope`/`Not checked` field.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift (template consistency)

## What was done well

- **The `lean_verify` defect is characterized accurately** (both critics): `:290-298` maps (no error) ∧ (no sorry) → `status:"ok"`; a bare `axiom h : False` passes (no axiom-audit code in `server/`); `syntax_only`→`compilation_success=null` (`:304-307`) and the `#check`-wrap / `maxHeartbeats 5000` detail (`:367-396`) match source.
- **The `rigor.py` cross-walk is byte-accurate** (arxmcp verified): `Rigor(IntEnum)` `:15-21`, frozen `Certificate` `:24-31`, `meet` `:47-57` all match; the honest "single-axis, not the spine" framing and the one-`UNKNOWN`-vs-four-refusals divergence satisfy the "divergences recorded" mandate and the owner's cross-walk decision.
- **Appendix B census is accurate against handler source** (arxmcp): exactly two frozen `server/schemas/*.json`, 8 `ToolMeta` entries, `find_lemma` 5 retrieval_modes with fallback `confidence=1.0`, `find_equation` 5 incl. `ted_fused_eq`; `metadata_status`/`graph_status`/`index_status` value sets all match.
- **The `get_definitions` §5d gap is precisely diagnosed** (both): `definitions.py:89` validates `paper_id` *format* not corpus *existence*, so an unknown paper and a real-but-empty paper collapse to `{definitions: [], total: 0, index_status: "ok"}` across `:68-179`.
- **AC2 exhaustiveness holds under independent verification** (both): a broader grep than the doc's own pattern over all eight briefs surfaced no uncensused external absence claim beyond the three (R4:9, R5:9-11, R6:15); `R5:78` and R6's Tricki/Rethlas clauses are correctly classified as scope-out / historical-fact / positive-prior-art per §3.
- **The BridgelandStability §8 correction shows correct epistemic humility** (both): records "§8 excluded" as an *inference* from stated §2-7 scope, "not a sentence any source asserts" — byte-accurate against `formalization.yaml:9`; the correction discipline eating its own dogfood.
- **The "enforcement deferred" justification is not fabricated** (both): corroborated verbatim by `plans/data-plane-governance/roadmap.yaml:53` (`wont`: no CI linters/schema validators; enforcement lands with the consuming tracks) and matched by the diff's zero code/test deltas.
- **Every internal cross-reference resolves** (adversary): `R0:44-47` (eleven axes matching §4's table), `R3:12-16`, `R4:31-32`, `R4:123-125`, `R5:26-27`/`:113` all verify.
- **Tier sequencing is disciplined** (arxmcp): every capability from an un-shipped track (R2/R3/R4/R5) is attributed as forthcoming, never claimed present; the epistemic/operational/partial split maps onto real existing signals.
- **No boundary/one-writer violations; commit hygiene clean** (adversary): no push/publish/deploy, no `plans/*/roadmap.yaml` status/checkbox/journal touch; both commits GPG-signed with the correct trailer and conventional subjects within length; §4.9 contradicts no repo fact.

Severity counts: C0 H1 M2 L2

## Recommended rectification order

M1, M2, L1, L2, H1
