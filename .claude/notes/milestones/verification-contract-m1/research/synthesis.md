---
milestone_id: "verification-contract-m1"
phase: "research"
briefs_synthesized:
  - "research/brief-1.md (explore)"
  - "research/brief-2.md (general)"
external_writes_required:
  - "git push origin main"
estimated_loc: "250-350"
estimated_files: 10
novel_architecture: false
phase2_path: "delegated"
---

# Research synthesis — verification-contract-m1

Fan-in of brief-1 (explore, codebase context) and brief-2 (general, external
research + external-writes). Both returned `complete`; both files verified
present in the main tree. Zero injection attempts across both.

## What this milestone actually is

A mechanical rename (`status="ok"` → `"elaborated_no_errors"`) propagated
across a frozen wire schema, plus one new design-only ADR. **No behavior
changes.** `compilation_success` semantics, the `axiom_audit` axis, and the
epistemic/operational split are all unchanged — only the token one enum
member carries.

The risk is not difficulty, it is **partial application**. Ten sites must
land together, two of them hash re-pins that must be computed *after* the
other eight. A half-done re-pin fails loudly (the constants cross-check each
other) rather than silently — but only if the order below is respected.

## Affected files (deduped, both briefs agree)

### Ordered re-pin checklist — steps 6–7 depend on 1–5

| # | File | Change | Notes |
|---|---|---|---|
| 1 | `server/handlers/lean_verify.py` | 6 live code sites: `724`, `730`, `733`, `777`, `823`, `1447` | 724 + 823 are the two `status =` assignments (cmd + tactic_step branches); 730/733 derive `compilation_success`; 777 gates `_default_audit_for`; 1447 gates the axiom-audit round-trip. Miss one → `compilation_success` mis-derives or axiom audit stops firing. |
| 2 | `server/tools.py:410-446` | `LEAN_VERIFY.description` — 2 literal `"ok"` sites (`426`, `434`) | BP1-affecting. This is what moves `EXPECTED_BP1_SHA256`. |
| 3 | `server/tools.py:226` | `TOOL_SCHEMA_VERSION` 22 → 23 + extend the bump-history comment block (180-225) | |
| 4 | `server/schemas/lean_verify_result.json` | enum (`163`), 2 field descriptions (`65`, `162`), top-level description append (`5`), `version` 22→23, `$id` v22→v23 | |
| 5 | `server/schemas/search_papers_result.json` | `version` 22→23, `$id` v22→v23, +1 narrative sentence | Content otherwise untouched. **The `$id` bump is asserted**, not conventional — `tests/test_search_filter.py:905-917`. Precedented ~8 times. |
| 6 | `tests/test_server_tool_schema.py` | `pytest tests/test_server_tool_schema.py --update-tool-schema-hash` | Regenerates `EXPECTED_TOOL_SCHEMA_SHA256` **and** `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`. The flag **refuses** unless `TOOL_SCHEMA_VERSION` was already bumped (decorative-version guard). It rewrites, then deliberately FAILS with "commit and rerun" — re-run plain to confirm green. |
| 7 | `tests/test_prompts.py:675-677` | Hand-edit `EXPECTED_BP1_SHA256` + add a `# v23:` history line | **No update flag exists.** Run the BP1 test, read the actual hash from the failure message, paste it. |
| 8 | `tests/test_handlers_lean_verify.py:224` | `TOOL_SCHEMA_VERSION == 22` → `== 23` | The only other hand-pinned integer in the suite; everything else references the symbol dynamically. |
| 9 | `tests/test_handlers_lean_verify.py` | ~20 literal `"ok"` assertion sites | Lines per brief-1 §3. Two are `!= "ok"` (1474, 1650) — flip the comparison *target*, not the polarity. |
| 10 | `docs/api.md:141` | Rename the one token | Minimal fix only — see Decision 3. |

### New file

| # | File | Size |
|---|---|---|
| 11 | `.claude/docs/adr-verification-contract-five-operations.md` | ~150-250 lines, following `.claude/docs/adr-data-plane-boundary.md` (the only existing ADR, 175 lines) |

### Explicit do-not-touch

- **`REQUEST_COUNTER{status="ok"}`** (`server/tools.py:989,1013,1030,1035-1037`) is a
  **decoy**. It labels RPC-dispatch outcome, not lean_verify's trust axis, and is named as a
  separate legitimate overload in `trust-language-policy.md` §3 and §6 rule 4. Renaming
  lean_verify's enum has zero coupling to it. Both briefs independently flag this.
- **`server/observability/tracing.py:163-166`** and **`spend_constants.py:31-34`** say
  "keeps TOOL_SCHEMA_VERSION pinned at 6" — dead historical narrative explaining a
  point-in-time decision, not live pins. Do not "correct" them.
- **`adr-data-plane-boundary.md:30`** and **`R3-verification-contract.md:10-11,17`** cite the
  stale `lean_verify.py:290-298` range. Repo convention (per `trust-language-policy.md`'s own
  correction pattern) is append-don't-edit on Accepted docs; neither is in this milestone's
  ACs. Leave them.

## Acceptance criteria (traced to the roadmap item)

1. **AC1** — `status="elaborated_no_errors"` at all 6 code sites; no field reads bare
   `"verified"` (already true; this is a regression guard).
2. **AC2** — no single field collapses elaboration / kernel-check / axiom-audit / replay.
   **Already structurally satisfied**: `status`, `compilation_success`, `axiom_audit`,
   `continuation_status` are four independent fields, and none is inferred from another.
   See Decision 1.
3. **AC3** — both hashes re-pinned, both `server/schemas/*.json` `version` fields bumped.
   Steps 3–7 above.
4. **AC4** — the five-operation ADR defines, per operation, its inputs, isolation
   dependency, and target-binding behavior, implementing none of them.

## Decisions taken at synthesis (resolved, not deferred)

**Decision 1 — `status` stays a bare-but-honest token; no Certificate wrapping.**
brief-1 flagged genuine ambiguity in AC2's "redesign" language against
`trust-language-policy.md` §6 rule 3 (every trust-bearing field carries a Certificate).
Resolving to **rename only**, because the policy's own §2 names this exact fix in
rename form — "R3 renames `"ok"` → `elaborated_no_errors`" — and §2's 2026-07-31 status
block defers precisely that rename to "R3-m1's batched window", i.e. this milestone. AC2's
own text asks that no *single field collapse* multiple questions, which the existing
four-field shape already satisfies. Certificate-wrapping `status` would be a re-architecture
AC3's BP1-re-pin scope does not anticipate. **The implementer must record this reasoning in
the diff** (a comment or the ADR), not apply it silently — a critic re-reading §6 rule 3 in
isolation will otherwise flag it.

**Decision 2 — the ADR ships as `Status: Proposed`, not `Accepted`.**
The one house precedent (`adr-data-plane-boundary.md`) carries an "Owner approval record"
documenting a real interactive approval on 2026-07-12. No such round-trip is scheduled in
this milestone. Writing `Accepted` would assert an approval that did not happen; the
trust gate this ADR designs has not run. Ship `Proposed` with the approval-record section
present and explicitly pending. This also matches the ADR being design-only per AC4.

**Decision 3 — `docs/api.md` gets the one-token fix, not a resync.**
That line is independently stale (missing `incomplete`, `invalid-input`, `env`,
`continuation_status`, `proof_state_id`, `axiom_audit` — all landed in earlier milestones).
A full resync is scope creep; leaving `ok` there while the wire says `elaborated_no_errors`
manufactures fresh drift. Rename the token, leave the rest.

**Decision 4 — fix the handler's stale module docstring in passing.**
`server/handlers/lean_verify.py:9` claims schema "version 12"; live is 22 → 23. One line, in
a file already open for step 1. Not an AC; no reason to leave a known lie.

## Findings that change the ADR's content

1. **`parse_source` cannot be a REPL round-trip.** brief-2 verified by omission across the
   full `leanprover-community/repl` README (sha256-pinned): the protocol has exactly `cmd`,
   `path`, and `tactic`, plus `pickleTo`/`unpickleEnvFrom`/`unpickleProofStateFrom`. **Every
   documented mode elaborates.** `parse_source` needs a direct `Lean.Parser` invocation — a
   distinct Lean metaprogram, not a protocol variant. The ADR must say this outright;
   implying "the REPL, but lighter" would repeat the `syntax_only` mistake the policy already
   flagged.
2. **The roadmap brief's REPL command names are paraphrase, not literal.** `file` → `path`,
   `proofStep` → `tactic`, `pickleEnvironment`/`pickleProofSnapshot` → one `pickleTo` key
   disambiguated by an `env`/`proofState` companion. The handler already uses the correct
   literals; only the prose is wrong. The ADR should use real key names.
3. **`check_declaration` and `strict_replay_proof` are different soundness guarantees, not
   fast/slow variants of one check.** AXLE's `verify_proof` (the `check_declaration` shape)
   explicitly does *not* re-verify the environment and is vulnerable to metaprogramming-
   installed unchecked declarations — AXLE says so in its own §4.1. SafeVerify/lean4checker
   do a full `Environment.replay` and catch exactly that class (median 0.97 s vs 10.1 s on
   AXLE's own 1,000-request corpus). **If the ADR frames these as redundancy, a future
   implementer will reasonably skip the slow one and silently re-open the gap.**
4. **No operation covers the "checker identity" axis.** `trust-language-policy.md` §4 names
   four Lean-relevant axes (elaboration, proof closure, axiom audit, checker identity); the
   five operations cover three. Checker identity is served by the `arxmcp://lean-env`
   manifest resource (m5), not a sixth operation — the ADR should say so explicitly rather
   than leave the axis unaddressed by anything.
5. **`Lean.trustCompiler` is stale prose on this toolchain.** Lean 4.29.0 (RFC #12216)
   replaced it with one auto-generated axiom per native computation (`._native.bv_decide.`
   in the name). The pinned toolchain is `v4.30.0-rc2`, which postdates this.
   `lean_verify_result.json:43` names `Lean.ofReduceBool`/`Lean.trustCompiler` as "notable
   members" — allowlist logic still catches the renamed axioms correctly (anything not in the
   3-axiom allowlist is flagged), so **no code fix is needed**, but the ADR should record the
   prose staleness for whoever next touches that description.
6. **SafeVerify has no branch matching the pinned toolchain.** Its backports cover Lean
   4.9.0 / 4.14.0 / 4.15.0 / 4.20.0; the repo pins `v4.30.0-rc2`. `verification-contract-spike-2`
   already exists to resolve this. The ADR must not assume SafeVerify "just works" — defer to
   the spike, which m3 depends on (not m1).

## Open questions (carried to Phase 2/3)

1. Does the ADR enumerate a sixth operation for checker identity, or explicitly assign that
   axis to the `arxmcp://lean-env` resource? (Synthesis leans: assign to the resource, say so.)
2. Should the ADR pre-commit to `Environment.replay` as `strict_replay_proof`'s mechanism, or
   leave the SafeVerify-vs-lean4checker-vs-own-replay choice to spike-2?

## External writes required

```
external_writes_required: ["git push origin main"]
```

Verbatim from brief-2. Nothing else — no publish, no deploy, no GitHub write, no
network-mutating call. Per CLAUDE.md §4.4 this is per-event user authorization and is
**not** authorized by the pipeline having run.

## Phase 2 path decision

| Metric | Value |
|---|---|
| Estimated LOC | ~250–350 |
| Estimated files | **10** (9 existing + 1 new) |
| Novel architecture | No — the re-pin choreography has shipped ~8 times |

**Path: `delegated`.** LOC alone would qualify for inline (≤300), but the file count is 10,
and the rule is `≤300 LOC AND ≤5 files` for inline. `>5 files` routes to delegated. brief-1
recommended inline on the grounds that the work is mechanical; that judgment does not
override the threshold — and the ten-file re-pin with two order-dependent hash steps is
exactly the shape that benefits from a worktree-isolated implementer running the gates
end-to-end.
