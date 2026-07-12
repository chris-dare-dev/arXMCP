# Implement synthesis — data-plane-governance-m3

**Path:** inline (orchestrator). **Base:** `23b8628`. **Range:** `23b8628..1ff9c56`
(2 commits). **Owner-approved** 2026-07-12 via the m3 checkpoint (3 decisions).

## Built (per roadmap acceptance criterion)

**AC1 — trust-language policy** → `.claude/docs/trust-language-policy.md` (228 lines):
- §1 the one-sentence rule; §2 the banned pattern grounded in the exact
  `lean_verify` `status:"ok"` logic (`server/handlers/lean_verify.py:290-298`), the
  bare-`axiom h : False` pass, and `syntax_only`-still-elaborates.
- §3 the "status" word-overload census (≥4 meanings); §4 the 11-axis Certificate-shaped
  trust record (from R0:44-47), each axis + a worked example on this surface.
- §5 abstention as first-class: 5a the 4 epistemic outcomes, 5b a **separate** operational
  lane, 5c a **separate** partial-result marker, 5d the `get_definitions` gap to close —
  per the owner's "epistemic-only + lanes" decision.
- Appendix A rigor.py **cross-walk** (single-axis; shape reused per-axis, not spine) — per the
  owner's "cross-walk appendix" decision, with the divergence recorded and the R4 opaque-
  passthrough precedent cited. Appendix B the condensed MCP-surface trust-vocab census.

**AC2 — evidence-ledger standard** → `.claude/docs/evidence-ledger-standard.md` (132 lines):
- The 5-field census requirement + scoped-not-categorical phrasing rule + in/out-of-scope table
  + template; the retro census over the **3** brief-cited absence claims (R4:9, R5:9-11, R6:15
  — verified exhaustive; R2 carries none, R7 deferred). R6's was a full retrofit (live census
  run 2026-07-12); R4/R5 needed only the queries-run field.

**AC3 — CLAUDE.md + cross-refs**:
- CLAUDE.md **§4.9** (additive, +29 lines, single hunk after §4.8) — 3 binding rules, links both
  docs, two scope lines. `9ed2ec5`.
- R3 (`:38-39` + Trust gate) and R5 (KR3) now reference `.claude/docs/trust-language-policy.md`
  by path. `1ff9c56`.

## Branching note

main-only repo (CLAUDE.md §4.1). Commits landed directly on `main`:
`9ed2ec5` (feat repo: policies + §4.9), `1ff9c56` (feat notes: briefs). Both GPG-signed, both
carry the `Co-Authored-By: Claude Opus 4.8` trailer (the actual authoring model, per the
m1-rectified §4.3 wording). Explicit pathspecs only — no `git add -A`.

## Files touched

- `.claude/docs/trust-language-policy.md` — CREATE (constitutional trust vocabulary)
- `.claude/docs/evidence-ledger-standard.md` — CREATE (dated-scoped-census standard)
- `CLAUDE.md` — §4.9 additive amendment
- `.claude/roadmap-briefs/R3-verification-contract.md` — policy path-ref (brief + Trust gate)
- `.claude/roadmap-briefs/R5-formal-target-registry.md` — policy path-ref (KR3) + census + §8 correction
- `.claude/roadmap-briefs/R4-verified-computation.md` — evidence-ledger census
- `.claude/roadmap-briefs/R6-proof-structure-and-bundles.md` — evidence-ledger census

## Deferred (in scope of the track, not of m3)

- Machine enforcement (schema validators / CI linters) — deferred to the consuming R3/R5
  tracks per the data-plane-governance `wont` list; adoption is by-reference discipline.
- R7's Matlas absence claim — R7 not roadmapped, named in no m3 acceptance criterion.
- R5's precise §8 wording in its own prose — R5-m1 owns the coverage matrix; m3 annotated the
  correction dated rather than rewriting R5's planning text.

## external_writes_required

- `git push origin main`

## Test deltas

- None. Docs-only diff; no production code changed, so no test file added/changed (the
  "rect must touch a test" rule applies only when production code changes — it does not here).

## Check gate results

- `tests/test_constitution_ui_claims.py` (the CLAUDE.md scanner): **PASS** (29/29).
- `tests/test_langfuse_doc.py` (SDK-ban doc guard), `tests/test_runbook_index.py`: **PASS**.
- No test pins `trust-language` / `evidence-ledger` / §4.9 / the brief paths (verified by grep);
  security-test CLAUDE.md references are incidental comments (§1/§4.1/§8).
- Full suite NOT run: docs-only diff changes no runtime surface; the doc-scanning tests are the
  complete set of gates touching this diff. (Per the workstation baseline, a full run would only
  surface the ~55 accepted platform failures — noise for a docs change.)
- **git status:** clean of m3 — all 7 target files committed. Remaining tree dirt is (a) my own
  `plans/data-plane-governance/progress/agent.jsonl` in_progress append (finalized at Phase 4),
  and (b) **concurrent-session** activity that appeared mid-Phase-2 (`server/routes/ui.py`
  modified, `tests/_symlink_support.py` new) — NOT m3's, excluded by explicit pathspecs.
