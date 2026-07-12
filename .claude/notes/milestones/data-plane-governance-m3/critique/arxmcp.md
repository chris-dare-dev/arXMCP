# Critique — data-plane-governance-m3 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** 23b8628..1ff9c56
**Diff stats:** 7 files, 458 LOC (+454 / -4)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

A docs-only trust-language + evidence-ledger milestone that is unusually accurate: I
independently re-verified every load-bearing factual claim it makes about the arXMCP surface
(the `lean_verify` status logic, the eleven-axis set against R0, the `rigor.py` cross-walk, the
Appendix B census, the four-outcome abstention model, and the evidence-ledger's own
exhaustiveness claim) and all of them hold at source. Exactly one inaccuracy survived
verification: an illustrative worked example cites the BridgelandStability comparator-stub
`sorry` at `Spec.lean:52`, but line 52 is the theorem's type signature — the `sorry` is at
line 57. That single MEDIUM is non-blocking doc-polish, cheap to fix, and squarely in the
spirit of the milestone (precise, re-verifiable citations); nothing here blocks shipping.

## Executive summary

- [MEDIUM] `trust-language-policy.md:80` cites the BridgelandStability comparator-stub `sorry`
  as `Spec.lean:52`, but the `sorry` token is at `Spec.lean:57`; line 52 is the middle of the
  theorem's existential type. The declaration does span line 52, so it is off-by-5, not wildly
  wrong — but a reader jumping to :52 sees no sorry. (Axis 2)
- [CLEAN] Axis 2 (math/domain fidelity, primary): `lean_verify.py:290-298` logic is quoted
  faithfully; `rigor.py` enum/`Certificate`/`meet` all match at the cited `:15-21`/`:24-31`/
  `:47-57`; the R5 "§2–7 coverage / §8-is-inferred" correction is byte-accurate against
  `formalization.yaml:9`.
- [CLEAN] Axis 4 (MCP surface compliance): Appendix B census is accurate — exactly two frozen
  `server/schemas/*.json` files, 8 registered tools, `find_lemma` 5 retrieval_modes, `find_equation`
  5 (incl. the index-set `ted_fused_eq`), and the `metadata_status`/`graph_status`/`index_status`
  value sets all match handler source.
- [CLEAN] Axis 1 (cache byte-stability): zero `server/` bytes touched; the policy explicitly
  ships no schema change and defers enforcement (§7). No `tools.py`/`prompts.py` dependency.
- [CLEAN] Axis 6 (tier sequencing): every future-track capability (R2 `effective_hypotheses`,
  R3 `elaborate_signature`/`audit_axioms`, R4 receipts, R5 review) is attributed as forthcoming,
  never claimed present; enforcement is deferred to R3/R5 throughout.
- [CLEAN] Axis 8 (doc placement / overclaim): both docs correctly under `.claude/docs/` per
  CLAUDE.md §1/§4.6; §7 honestly states enforcement is by-reference discipline with no tests —
  matching the zero test/code deltas in the diff. CLAUDE.md §4.9 is internally consistent with
  §4.7/§4.8 and §7.
- [CLEAN] Axes 5 & 7 (local-first / no-fork): docs introduce no dependency or lifted-code claim;
  the `rigor.py` reuse is explicitly "shape, not values", ideas-not-code.
- [STRENGTH] The evidence-ledger's "exactly three external absence claims across R0–R7"
  exhaustiveness claim reproduces exactly under an independent re-run of its own grep, with each
  non-claim line correctly categorized.

## Axis coverage (8 arXMCP axes)

- **Axis 1 — cache byte-stability:** clean. Diff touches no `server/` file; §7 asserts "ships
  no server code / adds no enforcement tooling", consistent with the tree.
- **Axis 2 — math/domain fidelity (primary):** one MEDIUM (M1, `Spec.lean:52`); everything else
  verified accurate at source (see Findings + What-was-done-well).
- **Axis 3 — cache/prompt discipline (n/a docs):** no `SYSTEM_PROMPT`/BP1/BP2/tool-schema claim
  made; clean.
- **Axis 4 — MCP surface compliance:** clean; Appendix B census independently re-verified.
- **Axis 5 — local-first:** clean; no forbidden dependency claim.
- **Axis 6 — tier sequencing:** clean; no un-shipped capability claimed present.
- **Axis 7 — no-fork:** clean; `rigor.py` consumed as pattern-only, explicitly not lifted.
- **Axis 8 — test surface / doc placement:** clean; correct `.claude/docs/` placement, honest
  "no tooling this track" enforcement posture, no phantom-test claims.

## Findings

**M1 — Comparator-stub `sorry` cited at wrong line (`Spec.lean:52` vs `:57`)** (MEDIUM)

**Where:** `.claude/docs/trust-language-policy.md:80`
**Anchor:** `| 6 | **proof closure** | Are there no`
**What:** The axis-6 worked example cites "BridgelandStability's one comparator-stub `sorry`
(`Spec.lean:52`)", but in `bstab/BridgelandStability/Spec.lean` line 52 is the first line of the
theorem's existential conclusion type (`∃ (E : Type u) …`); the actual `sorry` proof term is on
line 57. (There are two `sorry` string matches in the file: line 44 is a docstring mention, line
57 is the sole real proof-sorry — so the "one comparator-stub sorry" count is correct; only the
line number is off.)
**Why it matters:** A milestone whose entire thesis is precise, re-verifiable trust citations
("internal codebase facts are cited at `file:line` and re-verified on change" — CLAUDE.md §4.9)
should not ship a citation that does not resolve to the thing it names; a reader jumping to :52
sees a type signature, not the gap. The citation is also cross-repo into a Lean repo not under
arXMCP change control, so the line number is drift-prone independent of this error.
**Proposed fix:** Change `Spec.lean:52` to `Spec.lean:57`, or (drift-proof, preferred) cite the
declaration by name — `Spec.lean::NumericalStabilityCondition.existsComplexManifoldOnConnectedComponent`
— since cross-repo line numbers are not pinned by anything in this diff.
**Regression-guard:** Optional (MEDIUM). If a future doc-accuracy guard test is added (§6 of the
evidence-ledger foreshadows one), assert the cited line in `Spec.lean` contains the token `sorry`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** Axis 2 — math/domain fidelity

## What was done well

- **`lean_verify` status logic quoted faithfully.** §2's rendering is a semantically exact
  condensation of the real `if/elif/else` at `server/handlers/lean_verify.py:290-298`; the
  derived claim `status:"ok" ⇔ no-error ∧ no-sorry` and the `compilation_success=None` for a
  clean `syntax_only` pass both match source (lines 304-305). The `#check`-wrap /
  `maxHeartbeats 5000` detail matches `_build_command` at `:367-396`.
- **`rigor.py` cross-walk is byte-accurate.** `Rigor(IntEnum) PROVEN=3…UNKNOWN=0` at `:15-21`,
  the frozen `Certificate(rigor, hypotheses, citations, note)` at `:24-31`, and `meet` (min-rigor
  + order-preserving union) at `:47-57` all match `stability-mflds/bridgeland_stability/rigor.py`
  exactly — including the honest "single-axis, not the spine" framing and the `Rigor` has-one-
  `UNKNOWN`-not-four-refusals divergence.
- **Appendix B census is accurate against handler source.** Exactly two frozen
  `server/schemas/*.json` (`lean_verify_result.json`, `search_papers_result.json`); 8 `ToolMeta`
  entries in `server/tools.py`; `find_lemma` has precisely 5 retrieval_modes (`fts5_exact`,
  `fts5_trigram`, `fuzzy_jaccard`, `in_memory_scan_fallback`, `empty_after_normalization`) with
  `confidence` hardcoded `1.0` in the fallback (`lemma.py:228`); `find_equation` has 5 incl. the
  index-set `ted_fused_eq` (`equations.py:476`).
- **The `get_definitions` not-in-corpus-vs-empty collapse (§5d) is correctly diagnosed.**
  `definitions.py:89` validates only paper_id *format*, not corpus existence; a well-formed
  unknown paper falls through to the full-table branch returning `index_status:"ok", total:0`,
  identical to a real paper with zero definitions. Verified across the cited `:68-179` span.
- **`metadata_status` / `graph_status` value sets match source.** `get_paper`'s
  `hydrated`/`synthesized_from_chunks` (`paper.py`) and `cite_neighbors`'
  `absent`/`unavailable`/`present` (`citations.py:108,134,141`) are quoted correctly, including
  the "corrupt/half-ingested Kùzu DB" meaning of `unavailable`.
- **Evidence-ledger exhaustiveness reproduces independently.** Re-running the ledger's own grep
  pattern over `.claude/roadmap-briefs/*.md` surfaces exactly the same candidate lines; the
  "exactly three" claim holds because each non-claim is correctly categorized — R5:78 "nothing
  serves without its axes" is pre-named as an architectural scope-out in the ledger's §3 table,
  and R6:15's "Tricki froze" and "Rethlas/Archon's thesis" clauses are correctly excluded as a
  historical fact and a positive prior-art citation respectively.
- **The R5 BridgelandStability correction is itself byte-accurate.** `formalization.yaml:9`
  states only the positive "Sections 2-7"; the ledger's `updated`-discipline correction that
  "§8-excluded" is an *inference* (not asserted by any source) is exactly right, and R5:26-27
  does phrase §8 as "out of scope upstream". This is the correction discipline eating its own
  dogfood, correctly.
- **Enforcement posture is honestly scoped.** §7 and CLAUDE.md §4.9 both state plainly there is
  no CI linter / schema validator this track and enforcement is by-reference discipline deferred
  to R3/R5 — matching the diff's zero test and zero code deltas. No phantom enforcement is
  claimed.
- **Tier sequencing is disciplined.** Every capability drawn from an un-shipped track (R2/R3/R4/
  R5) is attributed to that future track, never presented as existing on today's surface; the
  four abstention outcomes and three-lane (epistemic / operational / partial) split map onto real
  existing signals (`get_chunk.found`, `lean_status="disabled"`, `*_fallback` modes).
- **Doc placement and cross-refs are correct.** Both files land under `.claude/docs/` per CLAUDE.md
  §1/§4.6; CLAUDE.md §4.9 is consistent with §4.7 (SDK ban), §4.8 (data-plane boundary), and §7
  (get_paper stub wording); the R3/R4/R5/R6 brief edits swap the placeholder "R0 policy" reference
  for a real path and add well-formed census blocks.

Severity counts: C0 H0 M1 L0

## Recommended rectification order

M1

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>
