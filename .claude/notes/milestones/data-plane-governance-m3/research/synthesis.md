# Phase 1 synthesis — data-plane-governance-m3

**Mode:** standard (2 researchers: explore→brief-1, general→brief-2). Both returned
`status: complete`; both files present + frontmatter-valid. **0 injection attempts.**

> **Environment deviation (recorded):** the bespoke `milestone-researcher` subagent type is
> not registered in this session (only 6 built-ins are; arXMCP's `.claude/agents/` sit one
> dir below the session root) and the session root is not itself a git repo, so
> `isolation: worktree` was unavailable. Researchers ran as `general-purpose` on **sonnet**
> (the researcher's declared model) with the full researcher contract injected, `cd`-ing into
> REPO_ROOT. Researchers make no tracked writes, so losing worktree read-snapshotting is
> immaterial to correctness. The same substitution will apply to critics/rectifier.

## Affected files (deduped, with action)

| File | Action | Substance |
|---|---|---|
| `.claude/docs/trust-language-policy.md` | **CREATE** | Verified-enum ban; the 11-axis trust record; 4 abstention outcomes + gap resolutions; rigor.py cross-walk appendix. Core deliverable (~300–400 LOC). |
| `.claude/docs/evidence-ledger-standard.md` | **CREATE** | Dated-scoped-census standard + template; the 3-claim retro census table (~150–220 LOC). |
| `CLAUDE.md` | **MODIFY** | Additive new `### 4.9` immediately after §4.8 (line 287, before `## 5.` at 288). ~35 lines. |
| `.claude/roadmap-briefs/R3-verification-contract.md` | MODIFY | Add path-reference to `trust-language-policy.md` at its tool-surface gate (KR1, the `status:"ok"`→`elaborated_no_errors` rename). |
| `.claude/roadmap-briefs/R5-formal-target-registry.md` | MODIFY | Add path-reference to the policy at its "no bare verified"/multi-axis gate; apply the BridgelandStability phrasing correction. |
| `.claude/roadmap-briefs/R4-verified-computation.md` | MODIFY | Census annotation on the R4:9 hosted-computation absence claim (already partial-dated; add "queries run"). |
| `.claude/roadmap-briefs/R6-proof-structure-and-bundles.md` | MODIFY | Census annotation on the R6:15 technique-tagging absence claim (**full retrofit — no existing census**). |

**Explicitly OUT of scope:** R2 (no categorical absence claim — verified; its novelty is a
*capability it builds*, not a market census), R7 (Matlas; not roadmapped, not named in any m3
acceptance criterion), R0/R1 (R0 *states* the standard; R1 is internal-codebase-fact scope).

## Diff-size estimate + Phase 2 path decision

**Estimate:** ~600–700 LOC across **7 files** (2 new docs dominate; 4 brief edits are trivial
1–5 line annotations; CLAUDE.md ~35 lines).

**Decision: INLINE** (orchestrator authors), recorded as a deliberate deviation from the
mechanical `>5 files OR 300–800 LOC → delegated` rule. Rationale:
- **Zero novel architecture** — the rule's strongest signal. This is policy prose, no code.
- The `>5 files` trigger is inflated by **4 trivial brief annotations**; the substantive
  surface is 3 files (2 new docs + CLAUDE.md §4.9).
- The policy is a **synthesis of both research briefs + the adjudicated gap-analysis**; the
  orchestrator holds that context directly and a fresh delegate would re-derive it.
- Worktree isolation — delegation's main benefit — is unavailable in this environment anyway.
- Matches the **m1 governance-docs precedent** (m1's ADR + CLAUDE.md §4.8 went inline).
- Inline-implement → **delegated rectify** (pipeline trigger 3): independent re-verification.

**Accepted-scope acknowledgment:** m3's ~7-file / ~600-LOC surface is *planned*, not creep.
When the mid-flight scope guard (LOC≥350 OR files≥6) trips, treat it as **expected** and
continue — the guard exists to catch *unplanned* bloat. Commit in coherent units (see below).
Hard 800-LOC ABORT stays live; if the docs balloon past it, stop and reassess.

**Commit plan (explicit pathspecs only — never `git add -A`; tree is concurrently dirty):**
1. `feat(repo): trust-language + evidence-ledger policies + CLAUDE.md 4.9` — the 3 core files
   (2 new docs + hunk-scoped CLAUDE.md §4.9).
2. `feat(notes): R3/R5 policy cross-refs + R4/R6 novelty-claim census` — the 4 brief edits.
   *(Or fold into one `feat` if cleaner; the Phase-2 commit range captures both.)*

## Acceptance criteria the implementer must meet (deduped, traced to roadmap AC1/AC2/AC3)

**Trust-language policy (AC1):**
1. State the exact banned pattern: `lean_verify` `status:"ok"` ⇔ (no error-severity msgs) ∧
   (no sorry goals) at `server/handlers/lean_verify.py:290-298`; note a bare `axiom h : False`
   passes silently (zero axiom-audit code in `server/`), and `syntax_only` still elaborates
   (`#check`-wrap for terms; `maxHeartbeats` decl-elaboration otherwise). Cite that R3's brief
   independently re-derives the same (`R3:12-16`).
2. Ban any single "verified"-style enum; name the **"status" word-overload** (≥4 unrelated
   meanings: `lean_verify.status` epistemic ladder; `index_status`/`graph_status` availability;
   `metadata_status` provenance; `REQUEST_COUNTER{status}` RPC-dispatch). Ground the ban in the
   **25-row/8-tool MCP-surface census** in brief-1 §2 — not invented.
3. Define the **11 trust axes** verbatim from R0 KR3 (`R0:44-47`): source grounding; claim
   completeness; assumption closure; formal alignment + its review; elaboration; proof closure;
   axiom audit; checker identity; assumption realization; numerical replay; review independence
   — each defined + one worked example from this repo's actual surfaces.
4. Define the **4 abstention outcomes** (unknown / ambiguous / not-in-corpus /
   unsupported-by-provider) precisely enough to classify every existing "no full answer" signal
   in brief-1 §3, and **explicitly resolve (not skip) the named gaps**: (a)
   `get_paper.metadata_status="synthesized_from_chunks"` (paper in-corpus, enrichment missing —
   fits none); (b) degenerate input (`empty_after_normalization`) and quality-degraded-but-
   answered `*_fallback` modes are not refusals — state whether in scope; (c) `get_definitions`
   cannot distinguish not-in-corpus from in-corpus-but-empty (silent collapse,
   `definitions.py:68-179`) — require this be closed.
5. **rigor.py alignment as a cross-walk appendix, NOT the spine** (both researchers concur):
   `Rigor` (PROVEN>CONJECTURAL>HEURISTIC>UNKNOWN, `stability-mflds/bridgeland_stability/rigor.py:15-21`)
   is a **single-axis** ordinal lattice; `Certificate{rigor,hypotheses,citations,note}` +
   `meet()`=weakest-link (`:24-31,:47-57`). Reuse the **Certificate shape per-axis** (level +
   attached evidence; `meet` only *within* an axis, never across). Record the divergence:
   rigor.py grades *answer strength*; the 4 abstention buckets grade *whether an answer exists*
   — complementary, not one ladder. Precedent: R4's opaque `Certificate` passthrough (`R4:31-32`).

**Evidence-ledger standard (AC2):**
6. Standard + template requiring: **census set** (named systems/sources), **queries run**,
   **census date**, verdict (confirmed/updated/unconfirmable), and an explicit
   "could not verify on `<date>`" fallback. Model on brief-2 §2's worked entries.
7. Retro census covers **exactly 3 claims** (verified exhaustive; R2 has no absence claim):
   - `R4:9` (hosted Bridgeland-domain computation API) — **partial**, dated 2026-07-11; add "queries run".
   - `R5:9-10` (typechecked paper-statement registry) — **partial**, dated+scoped inline; add "queries run".
   - `R6:15` ("no system tags informal papers by technique at scale") — **full retrofit**, no existing census.
   Use brief-2 §2's byte-level re-verified figures (TheoremGraph 68.1/98.8/76.6/42.7; typecheck≠fidelity
   22/24 vs 5/24) where a census cites external systems, dated **2026-07-12**.

**CLAUDE.md + cross-refs (AC3):**
8. Additive `### 4.9` after §4.8 (line 287), mirroring §4.8 house style: one-line binding
   statement → link both new `.claude/docs/` files → explicit scope line(s) (MCP tool surface +
   a doc-authoring rule for future novelty claims) → the binding rules (verified-enum ban;
   abstention is a first-class, tested success state; novelty claims use the evidence ledger).
9. R3 and R5 each gain a concrete **path-reference to `.claude/docs/trust-language-policy.md`**
   at their existing tool-surface-gate language (R3 KR1 `R3:54-55`; R5 `R5:43,65-66`).

## external_writes_required (verbatim from brief-2)

```yaml
external_writes_required:
  - "git push origin main"
```

Docs-only. No publish/deploy/mutating-API. Push is per-event authorized at the Phase-4
boundary (CLAUDE.md §4.4) — never assumed. Re-fetch + re-verify ancestry first (concurrent
sessions push to `main` here). **Note the pre-existing 7 unpushed commits on `main`** (origin
at `0caf834`) — m3's push question is separate from those and must be surfaced distinctly.

## Open questions (max 5)

1. **Abstention buckets vs operational/degenerate signals.** The 4 buckets are epistemic;
   `timeout`/`unavailable`/`empty_after_normalization` are service/input-validity. Policy must
   scope the 4 as epistemic-only and name a separate operational-status lane, or R3's 5-op
   redesign hits the gap immediately. → **Resolve in the policy text** (state it explicitly).
2. **`metadata_status="synthesized_from_chunks"` fifth pattern?** Fold in as a recognized
   "partial-enrichment" outcome or flag as a known pre-policy exception. → Recommend: name it a
   distinct partial-result outcome (in-corpus, enrichment-unknown), not one of the 4 refusals.
3. **BridgelandStability "§8 excluded" phrasing.** No source asserts it literally (only "covers
   §2-7"). → Apply brief-2's corrected phrasing in the R5 edit + any census line.
4. **Enforcement is doc-review only for 6/8 tools** (only `lean_verify`/`search_papers` have
   frozen schema docs). → The policy must say adoption is by-reference discipline, not a
   schema-level gate (enforcement lands with the consuming R3/R5 tracks, per the `wont` list).
5. **Concurrent CLAUDE.md dirt** near-certain by close (Obsidian stamper). → Re-check
   `git status --porcelain -- CLAUDE.md` immediately before commit; hunk-scope §4.9 if dirty.
