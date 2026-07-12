# Critique — data-plane-governance-m3 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** 23b8628..1ff9c56
**Diff stats:** 7 files, 458 LOC (454 insertions, 4 deletions)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. All three acceptance criteria are met and the load-bearing facts I could verify against this repo are accurate — the `lean_verify` defect (`:290-298`), the `get_definitions` gap, the eleven R0 axes, every internal brief cite, and the "enforcement deferred" justification (corroborated by the roadmap `wont` list) all check out, and the AC2 "exactly three absence claims" exhaustiveness survived an independent grep. The only substantive issue is a MEDIUM placement asymmetry: R3's `## Gates` section references the trust-language policy by path, but R5's does not (R5's by-path reference sits in Key results, not its Gates block). A mandatory HIGH is logged for diff size (458 > 400 LOC), mitigated by the docs-only, two-greenfield-docs nature; two LOWs are optional polish.

## Executive summary

- [HIGH] Diff is 458 LOC (> 400) — mandatory review-quality-at-risk flag; mitigated (docs-only, two greenfield policy docs reviewable linearly), no runtime surface.
- [MEDIUM] AC3 asymmetry: R5's `## Gates` block does not reference the trust-language policy by path (only its KR3 build-step does), whereas R3's `## Gates` "Trust gate" was updated — arguably met, but not placed symmetrically with R3.
- [LOW] The `lean_verify` code block (`trust-language-policy.md:28`) reformats the source's `if/elif/else` (`:293-298`) as a ternary under a `:290-298` cite; semantics identical, "computes:" framing mitigates.
- [LOW] The R5 evidence-ledger census omits the explicit `Scope:` field that §4's own template mandates and that the R4/R6 censuses carry; scope is only implicit in the verdict clause.
- [CLEAN] No external write in the diff; no one-writer-rule touch (`plans/*/roadmap.yaml` untouched; only briefs + docs + CLAUDE.md).
- [CLEAN] Both commits GPG-signed with the correct `Co-Authored-By: Claude Opus 4.8` trailer; conventional subjects within length.
- [CLEAN] No repo-fact contradiction: §4.9 is consistent with §7's `get_paper` `metadata_status` wording and §6's 8-tool count.
- [CAVEAT] Sibling-repo facts (`rigor.py` line ranges, `BridgelandStability` `Spec.lean:52`) are not present in this repo and are unverifiable here; they are internally consistent with R5's own Evidence section and prior adjudication.

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

- **AC2 exhaustiveness holds under independent verification.** A broader grep than the doc's stated pattern (`no (system|one|tool|library|hosted|other)|nobody|not a single|first to|no…(does|serves|ships|tracks|exists|provides|offers)`) over all eight briefs surfaced no uncensused external absence claim beyond the three claimed (R4:9, R5:9-11, R6:15); the tempting `R5:78` ("nothing serves without its axes" — R5's own serving discipline) and the compound `R6:15` line (positive Rango/TheoremGraph/DSP prior-art + the explicitly-addressed Tricki historical fact) are correctly classified as design/prior-art, out of scope per §3.
- **The `lean_verify` defect is characterized accurately.** `server/handlers/lean_verify.py:290-298` does map (no error) ∧ (no sorry) → `status:"ok"`; a bare `axiom h : False` would pass (no axiom-audit code in `server/`); and the `syntax_only`→`compilation_success=null` forcing (`:304-307`) is described correctly.
- **The `get_definitions` §5d gap is precise.** The handler validates `paper_id` *format* via `is_valid_arxiv_paper_id` (`:89`) but not corpus *existence*, so an unknown paper and a real-but-empty paper both collapse to `{definitions: [], total: 0, index_status: "ok"}` — exactly as the policy states.
- **The "enforcement deferred" justification is not a fabricated excuse.** It is corroborated verbatim by `plans/data-plane-governance/roadmap.yaml:53` (`wont`: "No enforcement tooling … no CI linters, no schema validators … enforcement lands with the consuming tracks").
- **Every internal cross-reference resolves.** `R0:44-47` (the eleven axes, matching §4's table exactly), `R3:12-16` (R3's independent pass on the same defect), `R4:31-32` (`Certificate` passthrough-verbatim), `R4:123-125` (the prior census), `R5:26-27` and `:113` (§8-out-of-scope phrasing) all verify.
- **The BridgelandStability §8 correction shows correct epistemic humility.** It records the "§8 excluded" phrasing as an *inference* from the stated §2-7 scope, "not a sentence any source asserts" — matching the prior adjudicated correction rather than over-claiming.
- **The rigor.py cross-walk honestly records divergence** (single-axis lattice vs. the eleven-axis record; one `UNKNOWN` vs. four abstention kinds) instead of forcing alignment — satisfying the roadmap's "divergences recorded" mandate and the owner's cross-walk-appendix decision.
- **No boundary or one-writer violations.** The diff contains no push/publish/deploy and touches no `plans/*/roadmap.yaml` status, checkbox, or journal line; `external_writes_required: git push` is a synthesis note, not an action in the diff.
- **Commit hygiene is clean.** Both commits are GPG-signed (good signature) with the correct `Co-Authored-By: Claude Opus 4.8` trailer; subjects are conventional and within length (50 / 45 chars).
- **No repo-fact contradiction.** §4.9's `get_paper` `metadata_status="synthesized_from_chunks"` example agrees with CLAUDE.md §7; the "eight tools" framing agrees with §6's byte-stable 8-record `tools/list`.

Severity counts: C0 H1 M1 L2

## Recommended rectification order

M1, H1, L1, L2
