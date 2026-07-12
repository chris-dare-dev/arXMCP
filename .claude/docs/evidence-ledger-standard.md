# Evidence-ledger standard — dated, scoped census for novelty claims

**Status:** Accepted (data-plane-governance-m3, 2026-07-12) · owner-approved
**Companion:** [`trust-language-policy.md`](trust-language-policy.md) (the runtime / MCP-surface
half). Binding short form: CLAUDE.md §4.9.
**Scope:** every *external market-absence* novelty claim ("no system does X", "nobody ships
Y", "first to Z") asserted in an arXMCP planning or analysis document — the R0–R7 roadmap
briefs and their successors, the gap-analysis artifact, ADRs, and CLAUDE.md. It does **not**
govern internal codebase facts or positive prior-art citations (see §3).

---

## 1. The problem this closes

A categorical absence claim — "no system tags papers by technique" — is un-falsifiable as
written and rots silently: the reader cannot tell *what was checked*, *how*, or *when*, so a
claim that was true in 2026-Q1 reads as eternal, and a claim that was never really surveyed
reads identical to one that was. The gap analysis this program is built on shipped exactly
this failure in reverse (a "no hosted X" that turned out hosted; a "typecheck ⇒ verified"
that TheoremGraph's own data refutes). The fix is not to stop making absence claims — they
are load-bearing for a roadmap — but to make each one **dated, scoped, and reproducible**.

## 2. What the standard requires

An external absence claim is admissible only if it carries a **census** with all five fields:

1. **census set** — the *named* systems / sources / corpora actually checked. "The field" or
   "the literature" is not a census set; a list of names is.
2. **queries run** — the literal query strings, tool calls, or lookups performed, verbatim
   enough to re-run.
3. **census date** — the calendar date the census was run (ISO `YYYY-MM-DD`).
4. **verdict** — one of `confirmed` (absence holds over the set), `updated` (the claim was
   wrong or narrowed — record the correction), `unconfirmable` (could not check).
5. **unconfirmable fallback** — "could not verify on `<date>`" is a valid, honest result.
   Invent no system, no number, no negative. A missing census beats a fabricated one.

**Phrasing rule — scoped, never categorical:**

> ✗ BANNED: "no system tags informal papers by technique at scale."
> ✓ REQUIRED: "as of 2026-07-12, a scoped census of {MSC/AutoMSC, arXiv:2110.04040,
>   formula-concept tagging, Tricki/nLab/ProofWiki} via {…queries…} surfaced no system that
>   tags informal papers by proof technique at scale."

The scoped form is weaker on its face — and that is the point. It says exactly how much
weight it can bear, and it tells the next reader precisely what to re-run to falsify it.

## 3. In scope / out of scope

| Claim kind | Governed here? | Discipline that applies |
|---|---|---|
| External market-absence ("no system does X") | **YES** | this standard — full census |
| Internal codebase fact ("`lean_verify` returns `ok` for a bare axiom") | No | *verified-at-source* — cite `file:line`, re-verify on change |
| Positive prior-art citation ("RANGO +45%"; "TheoremGraph 68.1%") | No | freshness date if reproduced; not an absence census |
| Architectural scope-out ("no MMT stack in v1"; "no serving without axes") | No | a design choice, not a market claim |

The distinction matters: R2's "typed symbol/theory context" is a **capability it builds**, and
its "no full MMT/OMDoc stack" is a **scope-out** — neither is an external absence claim, so
R2 correctly carries no census entry. Do not manufacture censuses for design decisions.

## 4. Template

```markdown
> **Evidence-ledger census (<YYYY-MM-DD>).** Claim: "<verbatim absence claim>".
> Census set: <named systems/sources>.
> Queries run: <literal queries / tool calls>.
> Verdict: confirmed | updated | unconfirmable — <one-line result, incl. any correction>.
> Scope note: <exhaustive | scoped/non-exhaustive; what was NOT checked>.
```

## 5. Retro census (2026-07-12) — R0–R7 brief-cited absence claims

Exhaustive over the eight briefs (close-read + directory-wide keyword grep for
`no (system|one|tool|library|hosted)|nobody|not a single|first to|no.{0,20}(does|serves|ships|tracks)`).
**Exactly three** external absence claims exist across R0–R7. R0 *states* this standard
(not a claim instance); R1 and R3 are internal-codebase-fact briefs (no absence claims);
R2's novelty is a capability + a scope-out (§3 above); R7's Matlas reference is deferred
(R7 has not been through `/roadmap` and is named in no m3 acceptance criterion — tracked for
R7's own planning pass).

| # | Claim (verbatim, short) | Anchor | Census set | Date | Verdict |
|---|---|---|---|---|---|
| 1 | "no one serves Bridgeland-domain computations … as an API" | `R4-verified-computation.md:9` | Schmidt `stability_conditions` (Sage, 2023); Naylor `tilt.rs`; QuiverTools | 2026-07-11, re-affirmed 2026-07-12 | **confirmed** |
| 2 | "no system serving new, typechecked formalizations of paper statements pinned to both a corpus revision and a formal environment as a queryable API" | `R5-formal-target-registry.md:9-11` | AXLE, formal-conjectures, SorryDB, Herald, TheoremGraph, LeanArchitect, Matlas | 2026-07-11, re-affirmed 2026-07-12 | **confirmed** |
| 3 | "no system tags informal papers by technique at scale" | `R6-proof-structure-and-bundles.md:15` | MSC/AutoMSC subject classification; math-aware content classification (arXiv:2110.04040); formula-concept/POS tagging for math; human-curated technique wikis (Tricki, nLab, ProofWiki) | 2026-07-12 | **confirmed (scoped, non-exhaustive)** |

### Detail

**Claim 1 (R4:9) — hosted Bridgeland-domain computation.** Original census from gap-analysis
§2.5 (2026-07-11), already carried in R4's Evidence section (`R4:123-125`). *Queries run:*
searches for hosted stability-condition / wall-crossing / Bogomolov–Gieseker computation
services vs. offline libraries. *Verdict:* confirmed — Schmidt `stability_conditions` is a
Sage library, Naylor `tilt.rs` a crate (no API), QuiverTools a package; none is a hosted,
queryable API. The sibling `stability-mflds` is a local package, not a service. Re-affirmed
2026-07-12; no new hosted entrant found. This claim needed only the explicit *queries-run*
field to become standard-compliant.

**Claim 2 (R5:9-11) — typechecked paper-statement registry.** Census dated + scoped inline in
the claim sentence (7 systems). *Queries run:* per system — does it serve *new, typechecked
formalizations of paper statements pinned to a corpus revision + a formal environment as a
queryable API*? *Verdict:* confirmed — each of the seven serves a different shape (conjecture
banks, sorry-tracking, autoformalization, dependency graphs, statement mining), none the
pinned-and-served registry R5 scopes. **Correction recorded (per this standard's `updated`
discipline, applied to a supporting fact rather than the claim itself):** the "BridgelandStability
§8 excluded" phrasing used in R5's prose (`R5:26-27`, `:113`) and in the program handoff is a
*correct inference from stated scope*, not a sentence any BridgelandStability source asserts —
`formalization.yaml`, `README.md`, and the coverage site all state only the positive "covers
Sections 2–7" (byte-verified 2026-07-12; §8's identity as the group-action section comes from
Bridgeland 2007's own table of contents, not the repo). Recommended phrasing for R5-m1's
coverage matrix: "scope statement is §2–7; §8-absence is inferred, not asserted." R5-m1 owns
the precise wording; this entry flags it dated.

**Claim 3 (R6:15) — technique tagging at scale.** No prior census existed — full retrofit.
*Queries run (2026-07-12):* `tag mathematics papers by proof technique at scale automatic
classification 2026`; `Tricki mathematics proof techniques wiki status active or frozen`.
*Verdict:* confirmed, **scoped and non-exhaustive** — the surfaced work is *subject*
classification (Mathematics Subject Classification, AutoMSC), *content-representation* similarity
(arXiv:2110.04040), or *formula-concept* tagging, none of which tags by **proof technique**;
human-curated technique wikis (Tricki — live since Tao's 2009 launch — nLab, ProofWiki) are
small and static, with no evidence of scaled ongoing technique-tagging. *Not checked:* closed
commercial indexers and any non-English-language systems — hence non-exhaustive. This is the
honest floor the claim can now stand on; R6 (Phase 3, gated by R7's ablation) can deepen it
before it ships anything technique-tag-shaped.

## 6. Relationship to the trust-language policy

The trust-language policy governs how *runtime* outputs express trust (per-axis records,
abstention, no bare "verified"). This standard governs how *documents* express *novelty*.
They share one principle — **no categorical trust or novelty claim; always scoped, dated,
falsifiable** — and CLAUDE.md §4.9 binds both as agent constraints. Enforcement is
by-reference discipline (doc review), not tooling, per the data-plane-governance `wont` list;
a future doc-accuracy guard test could pin these censuses the way
`tests/test_constitution_ui_claims.py` pins other CLAUDE.md phrasing.
