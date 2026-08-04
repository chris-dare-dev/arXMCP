# Critique — verification-contract-m1 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** 3a7d626e9aa7c59d8fd06599c15a20ee771719b2..6c681b9bf88469dcb147844fa40ee6ccf5624839
**Diff stats:** 9 files, 400 LOC (+345/-55)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

The wire change itself is correct and completely pinned — I re-ran the four hash/version-guarding
suites (`test_server_tool_schema.py`, `test_prompts.py`, `test_search_filter.py`,
`test_snippet_contract.py`, plus `test_handlers_lean_verify.py` and `test_tools_all.py`) and all
pass, with every one of the six pins (TOOL_SCHEMA_VERSION, EXPECTED_TOOL_SCHEMA_SHA256,
EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH, EXPECTED_BP1_SHA256, both schemas' `version` + `$id`) moved
in lockstep and the in-test hardcoded integer caught. What is not clean is the paper trail: the
two binding trust documents the milestone cites as its authority now both assert that the wire
still carries `"ok"`, the operator API reference is stale on the same lines it edited, and the
recorded reason for not Certificate-wrapping `status` rests on a distinction the cited policy
does not draw. Nothing here is a shippable bug; all seven findings are cheap doc/rationale fixes.

## Executive summary

- [MEDIUM] The Certificate-deferral rationale (ADR + mirrored code comment) claims policy §6 rule 3 applies only to a "graded" verdict — §6 rule 3 carries no such qualifier, and the schema's own `status` description defines an explicit ordinal precedence ladder, which is exactly the "ordinal level" the policy says must carry evidence.
- [MEDIUM] `elaborated_no_errors` names policy §4 axis 5 (elaboration) but is emitted only when axis 6 (proof closure) also passes, in every mode — the new name asserts an axis the token does not purely report.
- [MEDIUM] `.claude/docs/trust-language-policy.md` §2's 2026-07-31 status block still states the rename "has **not** shipped: `status` still carries the value `"ok"`, deliberately" — the exact passage the milestone leans on for authority.
- [MEDIUM] `CLAUDE.md` §4.9 rule 1 still names `status:"ok"` as the live token; CLAUDE.md is loaded at the start of every agent session in this repo.
- [MEDIUM] `docs/api.md`'s `lean_verify` Returns block — edited by this milestone — still lists a 5-value status enum (no `incomplete`, no `invalid-input`), mis-scopes `compilation_success`'s null case, and never mentions `axiom_audit`.
- [LOW] `server/handlers/lean_verify.py:363` still says the surface "will call a proof of `False` 'ok'" in present tense, in the module the milestone just renamed.
- [LOW] The ADR records that no SafeVerify branch matches the pinned toolchain and defers the tool choice to spike-2 without bounding that choice by CLAUDE.md §4.7's no-fork policy.
- [CLEAN] Cache byte-stability, MCP spec compliance, local-first, tier sequencing, doc placement, and design-only discipline (AC4) are all verified clean at source.

## Findings

**M1 — Certificate-deferral rationale misreads the policy it cites** (MEDIUM)

**Where:** `.claude/docs/adr-verification-contract-five-operations.md:34`
**Anchor:** rule 3 requires a Certificate for a *graded
**What:** The ADR bullet and the mirrored comment at `server/handlers/lean_verify.py:717-726` defer `trust-language-policy.md` §6 rule 3 on the ground that `status` "is not graded — it is a single fact drawn from a fixed, mutually-exclusive ladder", but §6 rule 3 reads "Every trust-bearing field carries its `Certificate` (level + attached evidence), not a bare token" with no graded qualifier, and `server/schemas/lean_verify_result.json:162` defines `status` as an explicit ordinal ladder ("Precedence: 'unavailable' > 'timeout' > 'error' > 'sorry' > 'elaborated_no_errors'") — i.e. exactly the "ordinal level" §4 and Appendix A say must carry attached evidence.
**Why it matters:** The recorded justification is what `verification-contract-e3` will read when it decides whether the response schema still owes a Certificate shape; "the policy does not require it here" (false) and "we scoped it out of m1" (true) lead to different e3 outcomes, and CLAUDE.md §4.9 rule 1 is binding on that decision.
**Proposed fix:** Restate both the ADR bullet and the code comment as a *scoped deferral* rather than an exemption: `status` is not Certificate-wrapped in m1 because nesting it is a wire-breaking shape change owned by e3's response-schema redesign, and its evidence already ships as sibling fields (`messages`, `sorry_goals`, `proof_state`, `axiom_audit`) rather than as an attached record. Also drop the "Policy §2 itself names the rename below as the complete fix" clause (ADR:37, comment line 722-724) — §2 lines 74-76 name the rename *and* the five-operation split together as R3's remedy, not the rename alone.
**Regression-guard:** None needed (doc/rationale); the correction is verifiable by quoting `trust-language-policy.md:170-171` and `:74-76` back into the ADR bullet.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity / trust semantics

**M2 — `elaborated_no_errors` names one axis but is gated on two** (MEDIUM)

**Where:** `server/schemas/lean_verify_result.json:163`
**Anchor:** `      "enum": ["elaborated_no_errors", "e`
**What:** The value is emitted only when there are no error-severity messages AND no unresolved sorries (`server/handlers/lean_verify.py:727-734`), and in `tactic_step` only when `proofStatus == "Completed"` with no open goals and no sorries (`:829-837`) — so a token named after `trust-language-policy.md` §4 axis 5 (elaboration) is in fact gated on axis 6 (proof closure) in every mode.
**Why it matters:** Policy §4 forbids inferring one axis from another; under this name a consumer cannot read the elaboration axis off `status` at all, because an elaboration-clean snippet carrying a `sorry` reports `"sorry"` and an elaboration-clean tactic leaving goals reports `"incomplete"` — the rename replaced an axis-neutral token (`"ok"`) with one that claims an axis it does not purely report.
**Proposed fix:** Add one clause to the `status` description in `server/schemas/lean_verify_result.json` (no enum change, so no second re-pin window beyond the one already open): "`elaborated_no_errors` additionally requires no unresolved sorry (`full`/`syntax_only`) or all goals discharged (`tactic_step`); it is NOT a pure elaboration reading — `sorry` and `incomplete` results also elaborated without errors." Mirror the same sentence into `LEAN_VERIFY.description` if the rectifier is already re-pinning.
**Regression-guard:** `tests/test_handlers_lean_verify.py` — assert that a sorry-bearing response has zero `severity == "error"` messages while `status == "sorry"`, pinning that the elaboration axis is not readable from the token alone.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity / trust semantics

**M3 — trust-language-policy.md §2 now asserts the wire still carries "ok"** (MEDIUM)

**Where:** `.claude/docs/trust-language-policy.md:34`
**Anchor:** > planned five-operation redesign, which
**What:** The 2026-07-31 status-update block states "R3 renames `"ok"` → `elaborated_no_errors` describes R3's planned five-operation redesign, which has **not** shipped: `status` still carries the value `"ok"`, deliberately" — false as of this commit, and it is the very passage the ADR and the code comment cite as the authority for the rename.
**Why it matters:** The policy is Accepted, owner-approved, bound by CLAUDE.md §4.9, and referenced by path at the R3/R5 tool-surface gates; a reader following that reference will build against a status value the server no longer emits.
**Proposed fix:** Append a new dated status-update note (the append-don't-edit convention that the 2026-07-31 block itself established for this Accepted doc — do not edit §2 in place): "(2026-08-03, verification-contract-m1) statement (b) is now stale: the rename shipped at `TOOL_SCHEMA_VERSION` 23; `status` carries `elaborated_no_errors`. The five-operation split remains unbuilt."
**Regression-guard:** None needed (doc); a grep for `status` + `"ok"` in `.claude/docs/trust-language-policy.md` should return only text explicitly marked historical.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity / trust semantics

**M4 — CLAUDE.md §4.9 rule 1 still names the retired token** (MEDIUM)

**Where:** `CLAUDE.md:413`
**Anchor:** `status:"ok"` ⇔ no-errors ∧ no-sorry — which
**What:** The §4.9 rule-1 worked example states, in present tense, "`lean_verify`'s `status:"ok"` ⇔ no-errors ∧ no-sorry … is joined by an independent `axiom_audit` axis", which no longer describes any value the server emits.
**Why it matters:** CLAUDE.md is loaded at session start by every agent in this repo and is the single most-read description of this exact token; an agent writing a consumer will branch on `status == "ok"` and silently never match.
**Proposed fix:** One-token edit plus a parenthetical: "`status:"elaborated_no_errors"` (renamed from the original `"ok"` at verification-contract-m1, `TOOL_SCHEMA_VERSION` 23) ⇔ no-errors ∧ no-sorry …". While in §4.9, note that the sentence at `CLAUDE.md:421-425` about the `LEAN_VERIFY.description` edit being "staged in w1-schema-deltas.md for the next batched re-pin" was already resolved by the W2 window and now contradicts `.claude/docs/w1-schema-deltas.md:22`.
**Regression-guard:** None needed (doc).
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity / trust semantics

**M5 — the operator API reference for lean_verify is stale on the line edited** (MEDIUM)

**Where:** `docs/api.md:131`
**Anchor:** Returns `status` (`elaborated_no_errors` / `error`
**What:** The Returns block the milestone edited lists only five of the seven wire status values (missing `incomplete` and `invalid-input`, both live since lean-verify-continuation-m1), says `compilation_success` is "(null in `syntax_only`)" where the ToolMeta correctly says "null in syntax_only + tactic_step", omits `mode='tactic_step'` from the argument table at `:128`, and never mentions `axiom_audit`, `env`, `proof_state_id`, or `continuation_status`.
**Why it matters:** This is the only operator-facing description of the tool; it under-lists two status values a client must handle, and — most consequentially for this milestone — it hands the reader the newly honest status token while omitting the axiom axis that token explicitly defers trust to, which inverts the point of the rename. The recorded "one-token fix, not a resync" decision is defensible for the rest of `api.md` but not for the four sentences immediately adjacent to the edit.
**Proposed fix:** Resync the block: add `incomplete` / `invalid-input` to the enum list, change to "(null in `syntax_only` and `tactic_step`)", add the `tactic_step` mode row and the `env` / `proof_state` argument rows, and add one sentence — "`axiom_audit` reports the transitive axiom closure independently; `status` and `compilation_success` never speak to axiom soundness."
**Regression-guard:** None needed (doc); optionally a test asserting every member of the schema's `status` enum appears literally in `docs/api.md`'s lean_verify section.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity / trust semantics

**L1 — module comment still says the surface calls a proof of False "ok"** (LOW)

**Where:** `server/handlers/lean_verify.py:363`
**Anchor:** # the trust-language policy: ``status="ok"``
**What:** The "Axiom-hygiene axis" header comment reads, in present tense, "`status="ok"` <=> (no error-severity messages) AND (no sorries) … the surface calls a proof of `False` "ok"" — describing a token this same commit renamed 370 lines below.
**Why it matters:** The milestone deliberately fixed the sibling staleness in this file (the module docstring's "version 12" → 23), so leaving the file's own canonical explanation of the defect naming the old token is an inconsistency a future reader will trip on; it is also the block the ADR points at for the code-level reasoning.
**Proposed fix:** Retag the block as historical — "the original `status="ok"` (renamed to `elaborated_no_errors` at verification-contract-m1) <=> …" — and update the closing sentence to "the surface called a proof of `False` clean".
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity / trust semantics

**L2 — ADR defers the strict_replay_proof tool choice without a no-fork bound** (LOW)

**Where:** `.claude/docs/adr-verification-contract-five-operations.md:185`
**Anchor:** CLI wrapper vs a bespoke fresh-process re-e
**What:** Decision 5 records that SafeVerify's four published backport branches (4.9.0 / 4.14.0 / 4.15.0 / 4.20.0) do not cover the pinned `v4.30.0-rc2` toolchain and defers the concrete tool choice to `verification-contract-spike-2`, without naming CLAUDE.md §4.7's no-fork policy as a constraint on that choice.
**Why it matters:** The most obvious way to resolve "no branch matches our toolchain" is to backport SafeVerify's source into this repo — a direct OSS file lift, which the no-fork policy forbids; the ADR is the document spike-2 will read as its option set.
**Proposed fix:** Add one bullet under "Deliberately NOT decided here": "Whatever spike-2 chooses must be an unmodified upstream dependency invoked as a subprocess, or a bespoke arXMCP implementation — vendoring, forking, or backporting SafeVerify's source into this repo is out of bounds (CLAUDE.md §4.7)."
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** no-fork policy

## What was done well

- **Every pin moved together, and I verified it by running the suites, not by reading the summary.** `TOOL_SCHEMA_VERSION` 22→23 (`server/tools.py:237`), `EXPECTED_TOOL_SCHEMA_SHA256`, `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` 23 (the easy-to-miss decorative-bump guard), the hand-edited `EXPECTED_BP1_SHA256`, and both `server/schemas/*.json` `version` + `$id` v23 — `test_server_tool_schema.py`, `test_prompts.py`, `test_search_filter.py`, `test_snippet_contract.py`, `test_handlers_lean_verify.py` and `test_tools_all.py` all green on my own run.
- **The hardcoded version literal buried in a test body was found.** `tests/test_handlers_lean_verify.py:231` moved 22→23 with a bump note — this is exactly the class of pin that historically ships stale because it lives outside the two obvious anchor constants.
- **Both `!= "ok"` assertions kept their polarity while the comparison target moved** (`tests/test_handlers_lean_verify.py:1481` and `:1657`, the RLIMIT_AS cap guard) — an inverted assertion here would have silently retired the memory-cap regression test.
- **Axis independence survived the rename.** `compilation_success` is still `None` for a clean `syntax_only` pass (`lean_verify.py:740-741`) and unconditionally `None` in `tactic_step` (`:861`); `_default_audit_for` still degrades to a non-passing `unknown`/`not-applicable` rather than `clean` (`:778-795`); the `_attach_axiom_audit` gate was renamed without widening (`:1454`).
- **The description's line-split is byte-safe.** `"…/unavailable/" "invalid-input), "` concatenates with no lost separator, and the ToolMeta's slash-list stays in exact value-and-order lockstep with the schema `enum` (7 values, same order) — a drift there would have made the conformance suite pass while the wire lied.
- **No unnecessary BP1 window was opened.** `.claude/docs/w1-schema-deltas.md:22` shows nothing staged, so there was nothing to batch this rename with; a wire-enum change also cannot be staged bump-free (the handler would emit a value outside the frozen enum), so taking its own window is the correct read of the batching convention.
- **AC4 held exactly.** No code in the diff begins `parse_source`, `elaborate_signature`, `check_declaration`, `audit_axioms`, or `strict_replay_proof`; the ADR is design-only and says so at `:14`.
- **Doc placement is correct.** The ADR landed in `.claude/docs/`, and no Markdown entered `server/`, `ingest/`, `tests/`, `tools/`, `shim/`, `docker/`, or `infra/`.
- **`Status: Proposed` with an explicit "no owner round-trip ran" record** is the honest call and matches the `adr-data-plane-boundary.md` precedent — fabricating an `Accepted` would have been the easy, wrong move.
- **The ADR's Decision 5 structurally protects the tier ordering**: `strict_replay_proof` "runs in a SEPARATE, freshly-spawned isolated process rather than reusing a warm `env` token … structural, not incidental" — that sentence is what stops e6/e7's cache-and-warm-pool work from quietly eroding the trust gate the roadmap's `depends_on` edges encode.

Severity counts: C0 H0 M5 L2

## Recommended rectification order

M3, M4, M1, M5, M2, L1, L2

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>
