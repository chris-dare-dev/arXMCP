# Trust-language policy — the MCP surface's trust vocabulary

**Status:** Accepted (data-plane-governance-m3, 2026-07-12) · owner-approved
**Companion:** [`evidence-ledger-standard.md`](evidence-ledger-standard.md) (the document /
novelty-claim half). Binding short form: CLAUDE.md §4.9.
**Scope:** the arXMCP MCP tool surface — every field any of the eight tools returns that
expresses trust, confidence, verification, or epistemic status. This policy governs the
**shape** of trust language; the concrete per-tool response schemas are owned by the consuming
tracks (R3 for the Lean surface, R5 for the formal-target registry). It ships **no** server
code and adds **no** enforcement tooling (§7).

---

## 1. The rule (one sentence)

**No arXMCP tool response may carry a single bare "verified"-style status that collapses
distinct trust questions into one token.** Trust is a **multi-axis record** (§4); the absence
of an answer is a **first-class, tested outcome** (§5); and **no axis may be inferred from
another** — least of all fidelity from elaboration.

## 2. The motivating defect — what "banned" means, concretely

> **Status update (2026-07-31) — the axiom half of this defect is closed.**
> The section below is preserved as written on 2026-07-12; two of its
> statements are now stale and are corrected here rather than edited in place,
> since this is an Accepted, owner-approved policy. **(a)** "There is zero
> axiom-audit code in `server/`" no longer holds: `lean_verify` runs a
> `#print axioms` round-trip over the declarations a full-mode snippet
> introduces and emits an always-present, `Certificate`-shaped `axiom_audit`
> record (axis 7 of §4), with the allowlist this policy names and with
> unmeasured paths reporting `not-applicable` / `unknown` rather than a
> passing value (§6 rule 5). Issues #205 / #281 / #332.
> **(b)** The line "R3 renames `"ok"` → `elaborated_no_errors`" describes R3's
> planned five-operation redesign, which has **not** shipped: `status` still
> carries the value `"ok"`, deliberately. Renaming it is a wire-breaking change
> that belongs to R3-m1's batched window, and the axiom fix did not need it —
> per §4, the cure for a collapsed token is an independent axis beside it, not
> a relabelled token. `status` and `compilation_success` were left reporting
> exactly what they measure; inferring them from the axiom axis would be this
> section's conflation pointing the other way.
> **What is still open here:** the second bullet below (`syntax_only` is not
> syntax-only) is unchanged and still accurate, and axes 4 (formal alignment)
> and 8 (checker identity) remain unmeasured by this tool — absent from its
> record, per §4, not defaulted to passing.

`lean_verify` today (`server/handlers/lean_verify.py:290-298`) computes:

```python
has_error = any(m["severity"] == "error" for m in messages)
has_sorry = bool(sorry_goals)

if has_error:
    status = "error"
elif has_sorry:
    status = "sorry"
else:
    status = "ok"
```

So **`status: "ok"` ⇔ (no error-severity messages) ∧ (no `sorry` goals)** — nothing else is
checked. Consequences, verified at source (2026-07-11, re-confirmed by R3's independent pass,
`R3-verification-contract.md:12-16`):

- A bare **`axiom h : False`** elaborates with no error and no sorry → `status:"ok"` (and, in
  `mode="full"`, `compilation_success=True`). There is **zero axiom-audit code in `server/`**
  (`grep -ri axiom server/` → nothing). The surface will call a proof of `False` "ok".
- **`syntax_only` is not syntax-only.** Terms are `#check`-wrapped (full elaboration);
  declarations run under a `maxHeartbeats 5000` cap (the full declaration elaborator, budgeted)
  — "reduces but does not remove kernel work". The one honest signal already present:
  `compilation_success` is forced to `null` for a clean `syntax_only` pass.

A single `"ok"` token answers *elaboration* while silently implying *proof closure*, *axiom
soundness*, *target fidelity*, and *checker identity* — four different axes it never checked.
That conflation is the banned pattern. R3 renames `"ok"` → `elaborated_no_errors` (honest to
what it measures) and splits verification into five operations, each reporting its own axis;
this policy is the general rule R3's specific rename instantiates.

## 3. The "status" overload — a single word is already broken

The word **`status`** denotes at least four unrelated things across the surface today. A ban on
"one enum" is meaningless until this is named:

| `…status` occurrence | What it actually means | Kind |
|---|---|---|
| `lean_verify.status` (`ok`/`error`/`sorry`/`timeout`/`unavailable`) | a 5-value epistemic-*and*-operational ladder, mixed | epistemic + operational (itself overloaded) |
| `get_definitions.index_status`, `cite_neighbors.graph_status` | is the index / graph *available* | operational |
| `get_paper.metadata_status` (`hydrated`/`synthesized_from_chunks`) | *provenance* of the metadata | partial-result provenance |
| `REQUEST_COUNTER{status}` (`ok`/`error`) | RPC-dispatch outcome (a `sorry` verdict still records dispatch `ok`) | transport metrics — **not a tool-payload field** |

The policy forbids adding a fifth bare `status`. New trust-bearing fields are **namespaced and
axis-specific** (§6).

## 4. The multi-axis trust record (the spine)

Trust is recorded as **independent per-axis certificates**, never a single score. The axis set
is arXMCP-native — the eleven dimensions named in R0 (`R0-data-plane-governance.md:44-47`) —
each **`Certificate`-shaped**: an ordinal level *plus* attached evidence (spans, citations,
reviewer + date, environment digest). Composition uses a `meet` (weakest-link) combinator
**only within an axis** across multiple pieces of evidence for that axis — **never across
axes** to collapse eleven dimensions into one number (that would re-create the banned enum).

| # | Axis | The question it answers | Worked example on this surface |
|---|---|---|---|
| 1 | **source grounding** | Is the served statement backed by a retrievable corpus span? | `get_chunk`'s span-backed rows inside `<retrieved_chunk>` delimiters; a claim with no resolvable span scores lowest. |
| 2 | **claim completeness** | Are all of the claim's stated hypotheses captured? | R2's `effective_hypotheses` with provenance; a flat list that drops a standing assumption scores low. |
| 3 | **assumption closure** | Is the ambient theory/category each symbol lives in represented? | The S_X-vs-S_Ku trap: a silently *retyped* symbol (no hypothesis dropped) is an open assumption-closure failure — the article's shipped error. |
| 4 | **formal alignment (+ its review)** | Does a Lean target faithfully match the informal statement, and was that match human-reviewed? | R5's mandatory faithfulness review (reviewer + date). TheoremGraph's 22/24-typecheck vs 5/24-faithful proves this axis is **not** inferable from elaboration. |
| 5 | **elaboration** | Does the Lean input elaborate without errors? | R3's `elaborate_signature`; the honest `elaborated_no_errors` that `lean_verify.status="ok"` should have always been. |
| 6 | **proof closure** | Are there no `sorry` goals / open holes? | R3's `check_declaration`; BridgelandStability's one comparator-stub `sorry` (in the sibling BridgelandStability repo, on `Spec.lean`'s `NumericalStabilityCondition.existsComplexManifoldOnConnectedComponent`; audited `sorry_count: 1` in its `formalization.yaml`) is a proof-closure gap on exactly that declaration. |
| 7 | **axiom audit** | What is the transitive axiom set, and is it within the allowlist? | R3's `audit_axioms` vs `{propext, Quot.sound, Classical.choice}`; a bare `axiom h : False` is an axiom-audit failure today's surface cannot see. |
| 8 | **checker identity** | *Which* checker, in *which* named immutable environment, at what policy version? | R3's `arxmcp://lean-env` digest + checker/policy version on every response. **No rigor.py analogue.** |
| 9 | **assumption realization** | Is a conditional-over-interface result instantiated on a real object, or is realization still debt? | R5: a theorem about any `EnriquesKuContext` instance ≠ a theorem about an Enriques surface; lifecycle `proved-conditional` vs `realized`. |
| 10 | **numerical replay** | Can a computed result be re-derived from a replay witness / independent oracle? | R4's replayable receipts + stability-mflds' E12 transcription oracle (imports nothing from the package) differential-testing a frozen corpus. |
| 11 | **review independence** | Was the review grading these axes independent of the thing reviewed? | TheoremGraph's own honesty — single GPT-5.4 judge, a same-model-family self-consistency re-run (93.2%), only 10 expert-calibration pairs = **weak**. stability-mflds' oracle = **strong**. |

An axis a given tool does not touch is simply **absent** from its record (not defaulted to a
passing value). A response asserts only the axes it actually measured.

## 5. Abstention outcomes — a first-class, tested success state

Per owner decision (2026-07-12), the abstention vocabulary is **epistemic-only**, and two
adjacent notions get **separate** lanes so nothing is conflated.

### 5a. The four epistemic abstention outcomes

Every tool must be able to return, and every consumer must handle, these as **success**
(a correct "I decline to answer"), not error:

| Outcome | Meaning | Existing signal it regularizes |
|---|---|---|
| `unknown` | epistemic status genuinely indeterminate given the corpus | (new — e.g. a claim whose resolution is undecided) |
| `ambiguous` | multiple candidate answers, none dominant; the tool declines to pick | R2 reference resolution surfacing candidates with no confident winner |
| `not-in-corpus` | the queried entity is well-formed but absent from the served corpus | `get_chunk.found=False`, `get_paper.found=False` |
| `unsupported-by-provider` | the operation/entity is outside what the provider can compute/serve | R4's Enriques abstention ("scalar rank-1 model cannot represent 2-torsion canonical class; requires G12"); `lean_status="disabled"`; a never-ingested graph |

### 5b. Separate lane — operational status (NOT abstention)

Service and input-validity facts are **not** epistemic abstention and must not share its enum:
`available | disabled | timeout | unavailable | invalid-input`. This is where `lean_verify`'s
`timeout`/`unavailable`, `cite_neighbors.graph_status="unavailable"` (a corrupt/half-ingested
Kùzu DB), and `find_lemma_by_name`'s `empty_after_normalization` (a degenerate query) belong.
Scoping abstention as epistemic-only here **pre-empts R3's five-operation redesign** hitting
the same gap when it must classify axiom-audit failures and isolation kills.

### 5c. Separate marker — partial result (NOT abstention, NOT a refusal)

A tool may **answer** while one axis sits at its lowest level. Canonical case: `get_paper`
returns the paper (chunks exist → in-corpus) with `metadata_status="synthesized_from_chunks"`
— the *result is present*; the *metadata-provenance axis* is `unknown`. This is a
`partial` / `enrichment-unknown` marker, distinct from the four refusals. Likewise a
`*_fallback` `retrieval_mode` (`dense_only_fallback`, `fuzzy_jaccard`, `in_memory_scan_fallback`)
is a **present** result via a lower-precision method — a lower per-axis level, **not**
abstention. "No answer" and "weaker answer" must never wear the same token.

### 5d. Named gap the abstention requirement must close

`get_definitions` (`server/handlers/definitions.py:68-179`) never validates that `paper_id`
exists: an unknown paper and a real paper with zero definitions collapse to the identical
`{definitions: [], total: 0, index_status: "ok"}`. Every tool **must** be able to distinguish
`not-in-corpus` from in-corpus-but-empty; `get_definitions`' silent collapse is a pre-existing
hole this requirement closes (the fix lands with the consuming track, per §7).

## 6. Field-naming rules

1. **No new bare `status`.** Trust-bearing fields are namespaced and axis-specific
   (`elaboration`, `proof_closure`, `axiom_audit`, `formal_alignment`, `checker_identity`,
   `metadata_provenance`, …).
2. **Abstention, operational-status, and partial-result are three distinct fields** — never one
   merged enum.
3. **Every trust-bearing field carries its `Certificate`** (level + attached evidence), not a
   bare token.
4. **Transport metrics stay separate.** `REQUEST_COUNTER{status}` is dispatch-level and is not a
   tool-payload trust field.
5. **No axis defaults to passing.** An unmeasured axis is absent, not "ok".

## 7. Enforcement posture (honest scope)

Adoption is **by-reference discipline** from CLAUDE.md §4.9 and doc review — **not** a
schema-level gate. Only `lean_verify` and `search_papers` have frozen `server/schemas/*.json`
files cross-checked by a byte-stability test; the other six tools' status-like fields live in
handler code + `ToolMeta` prose. Per the data-plane-governance `wont` list, this track adds no
CI linter and no schema validator — **enforcement lands with the consuming tracks** (R3's Lean
response schema, R5's registry schema), which cite this policy by path at their tool-surface
gates. Do not read this policy as claiming uniform machine enforcement exists today; it does
not.

---

## Appendix A — rigor.py cross-walk (a reference, NOT the spine)

Owner decision (2026-07-12): align to stability-mflds' `rigor.py` as a **cross-walk appendix**,
not as the base vocabulary. Both Phase-1 researchers independently found `rigor.py`
(`stability-mflds/bridgeland_stability/rigor.py`) is a **single-axis** ordinal lattice:

```python
class Rigor(IntEnum):   PROVEN=3 > CONJECTURAL=2 > HEURISTIC=1 > UNKNOWN=0   # :15-21
@dataclass(frozen=True)
class Certificate:  rigor; hypotheses: tuple; citations: tuple; note: str    # :24-31
def meet(*certs):   # rigor = min(...);  hypotheses/citations = order-preserving union  # :47-57
```

**The divergence (recorded):** `rigor.py` grades *how strong an answered verdict is*; arXMCP's
abstention buckets grade *whether an answer exists at all*. These are **complementary,
orthogonal axes, not one ladder** — `not-in-corpus` is not "less proven than" `ambiguous`.
Making `Rigor`'s four values *be* the axis set, or mapping the eleven axes onto a single shared
`Rigor` scale, would re-import the exact single-enum anti-pattern §1 bans — just from a sibling
repo instead of inventing it locally. `Rigor`'s sole abstention value is `UNKNOWN=0` (one
value) where this policy needs four distinguishable, non-comparable kinds.

**What genuinely transfers — the *shape*, not the *values*:** the `Certificate` pattern (an
ordinal level + attached hypotheses/citations/note, evidence-bearing rather than bare), applied
**independently per axis** (§4), with `meet` used **only within** an axis. The precedent for
consuming an external trust artifact is already set in R4: arXMCP passes the provider's
`Certificate` through **verbatim** — never re-derived, never re-graded
(`R4-verified-computation.md:31-32`).

| arXMCP axis | Nearest `rigor.py` concept |
|---|---|
| proof closure, axiom audit | the `PROVEN` end of `Rigor` (a discharged, hypothesis-checked verdict) |
| numerical replay | `HEURISTIC`/certificate provenance (a computed verdict with attached witness) |
| assumption closure, assumption realization | `Certificate.hypotheses` (open vs discharged hypotheses) |
| source grounding | `Certificate.citations` (loosely) |
| formal alignment, elaboration, checker identity, review independence, claim completeness | **no analogue** — retrieval/verification concepts absent from a Chern-character computation |
| the four abstention outcomes | **no analogue** — `rigor.py` has one `UNKNOWN`, not four refusal kinds |

## Appendix B — current MCP-surface trust-vocabulary census (2026-07-12)

The ban in §1 is enforceable only against a complete inventory of what exists today. Condensed
below (one row per tool); the exhaustive 25-field table is in the Phase-1 research brief
(`.claude/notes/milestones/data-plane-governance-m3/research/brief-1.md` §2).

| Tool | Trust/status-ish fields today |
|---|---|
| `search_papers` | `retrieval_mode`, `filter_warnings`, `filters_applied`, `degraded`/`degraded_reasons`, `excluded_kinds` |
| `get_chunk` | `found`, `include_*_applied` (always False), `unused_args` (`truncated_for_license` removed in license-serving-removal-m1) |
| `find_equation` | `retrieval_mode` (5 values incl. `*_fallback`), `cosine_score`/`ted_norm`/`score` |
| `get_definitions` | `index_status` (`absent`/`ok`) — **cannot signal not-in-corpus vs empty (§5d)** |
| `find_lemma_by_name` | `retrieval_mode` (5 values), per-match `confidence` (hardcoded `1.0` in fallback) |
| `get_paper` | `metadata_status` (`hydrated`/`synthesized_from_chunks`), `found` |
| `cite_neighbors` | `graph_status` (`absent`/`unavailable`/`present`), per-neighbor `confidence` |
| `lean_verify` | `status` (5-value ladder — §2), `compilation_success` (bool\|null), `lean_status`, `mode` |
| *(all tools)* | `corpus_version`; `body_truncated`; dispatch-level `REQUEST_COUNTER{status}` (not a payload field) |

---

## Owner approval

Owner-approved 2026-07-12 via the data-plane-governance-m3 checkpoint (three decisions, the
recorded approval for this policy):

1. **rigor.py role → cross-walk appendix** (Appendix A), not the spine — deviating from the
   roadmap's `should` assumption, on the cross-validated finding that `rigor.py` is single-axis.
2. **Abstention model → epistemic-only + separate lanes** — four epistemic outcomes (§5a), a
   distinct operational-status lane (§5b), and a distinct partial-result marker (§5c); the
   `get_definitions` gap (§5d) to be closed by the consuming track.
3. **Approve on these decisions** — this policy and `evidence-ledger-standard.md` land committed
   and Accepted; CLAUDE.md §4.9 binds them; R3/R5 reference this policy by path.
