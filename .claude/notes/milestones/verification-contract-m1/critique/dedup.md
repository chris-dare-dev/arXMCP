# Critique (merged) — verification-contract-m1

**Critics:** milestone-adversary-critic, milestone-arxmcp-critic
**Commit range:** 3a7d626e9aa7c59d8fd06599c15a20ee771719b2..6c681b9bf88469dcb147844fa40ee6ccf5624839
**Diff stats:** 9 files, 400 LOC
**Critique format version:** 1.0

> Merge note: both critics authored ids from 1 within their own file. milestone-arxmcp-critic's findings were renumbered to continue the adversary's sequence (M1-M5 -> M4-M8, L1-L2 -> L3-L4) because the parser requires bare <letter><serial> ids and cannot namespace by critic. Content is otherwise verbatim.

## Verdict

SHIP-WITH-FIXES (both critics independently). The code half of the rename is complete and behaviour-preserving; every finding is doc drift, rationale precision, or naming. No finding alleges a functional defect in the shipped diff.

## Executive summary — milestone-adversary-critic

- [CRITICAL] `.claude/docs/trust-language-policy.md:34` — the policy's own dated
  amendment (b) asserts the rename has **not** shipped and that carrying `"ok"` is
  deliberate. The diff makes that statement false; the file's own append-an-amendment
  precedent (lines 23–32) is the ready-made fix.
- [CRITICAL] `CLAUDE.md:412` — §4.9 rule 1's worked example still names
  `lean_verify`'s `status:"ok"` as the live token. CLAUDE.md is re-read at every
  session start; this is the exact staleness class §3 of that file already carries
  two correction blocks for.
- [MEDIUM] `docs/api.md:131` — the line the diff edited still lists only 5 of the 7
  enum members (`incomplete` and `invalid-input` missing). Completing the enum on a
  line already being touched is not the "resync" the recorded decision scoped out.
- [MEDIUM] `.claude/docs/adr-verification-contract-five-operations.md:125` — the
  ADR's citation `lean_verify.py:1077-1148` is the **pre-diff** range; the same
  commit shifted `_attach_axiom_audit` to 1087–1158. Stale at birth.
- [MEDIUM] `server/handlers/lean_verify.py:363` — the Axiom-hygiene banner comment
  still states `status="ok"` in the present tense as the module's live semantics —
  the very sentence this milestone exists to correct. The module docstring was
  fixed in passing; this one was missed.
- [LOW] Commit body frames a wire-visible enum rename as "no behaviour change";
  no CHANGES.md / migration note for an out-of-tree MCP consumer that string-matches
  `status == "ok"`.
- [LOW] `tests/test_handlers_lean_verify.py:290` — `test_clean_compile_status_ok`
  keeps the old token in its name.
- **No diff-size auto-finding:** 345 + 55 = 400 LOC, which does not *exceed* 400;
  the reviewable code delta is ~93 lines, the rest a design document.

## Executive summary — milestone-arxmcp-critic

- [MEDIUM] The Certificate-deferral rationale (ADR + mirrored code comment) claims policy §6 rule 3 applies only to a "graded" verdict — §6 rule 3 carries no such qualifier, and the schema's own `status` description defines an explicit ordinal precedence ladder, which is exactly the "ordinal level" the policy says must carry evidence.
- [MEDIUM] `elaborated_no_errors` names policy §4 axis 5 (elaboration) but is emitted only when axis 6 (proof closure) also passes, in every mode — the new name asserts an axis the token does not purely report.
- [MEDIUM] `.claude/docs/trust-language-policy.md` §2's 2026-07-31 status block still states the rename "has **not** shipped: `status` still carries the value `"ok"`, deliberately" — the exact passage the milestone leans on for authority.
- [MEDIUM] `CLAUDE.md` §4.9 rule 1 still names `status:"ok"` as the live token; CLAUDE.md is loaded at the start of every agent session in this repo.
- [MEDIUM] `docs/api.md`'s `lean_verify` Returns block — edited by this milestone — still lists a 5-value status enum (no `incomplete`, no `invalid-input`), mis-scopes `compilation_success`'s null case, and never mentions `axiom_audit`.
- [LOW] `server/handlers/lean_verify.py:363` still says the surface "will call a proof of `False` 'ok'" in present tense, in the module the milestone just renamed.
- [LOW] The ADR records that no SafeVerify branch matches the pinned toolchain and defers the tool choice to spike-2 without bounding that choice by CLAUDE.md §4.7's no-fork policy.
- [CLEAN] Cache byte-stability, MCP spec compliance, local-first, tier sequencing, doc placement, and design-only discipline (AC4) are all verified clean at source.

## Findings

**C1 — Policy doc still asserts the rename has not shipped** (CRITICAL)

**Where:** `.claude/docs/trust-language-policy.md:34`
**Anchor:** `> planned five-operation redesign, which`
**What:** The dated amendment block at `:33-38` states that R3's rename "has **not** shipped: `status` still carries the value `"ok"`, deliberately", and `:57` / `:60` / `:64` quote the old code and derive `status: "ok"` ⇔ no-errors ∧ no-sorry — all of which the diff falsifies, with no amendment appended.
**Why it matters:** `trust-language-policy.md` is named by CLAUDE.md §4.9 as binding constitution for every agent session, and amendment (b) does not merely go stale — it affirmatively tells the next agent that *not* renaming is the deliberate current state, which invites either a duplicate rename milestone or a revert of this one.
**Proposed fix:** Append a third dated bullet to the existing `>` amendment block (the file's own precedent for an Accepted, owner-approved doc — do not edit §2 in place): `**(c)** Amendment (b) is itself now superseded: verification-contract-m1 (2026-08-03, TOOL_SCHEMA_VERSION 22 -> 23) shipped the rename. \`status\` now carries \`"elaborated_no_errors"\` on the clean-elaboration path; the code block and derivations below are preserved as written and read \`"ok"\` for the historical token. The five-operation split remains unbuilt (verification-contract-e3).` Leave `:57`/`:60`/`:64` untouched — the amendment header already declares the section preserved-as-written.
**Regression-guard:** Add to `tests/test_trust_language_policy_doc.py` (or the nearest existing doc-guard test) an assertion that the file contains the literal `elaborated_no_errors` **and** that the substring `status` still carries the value does not appear — a derived check, so a future revert of the rename without a doc touch fails loudly.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**C2 — CLAUDE.md §4.9 rule 1 names a status token that no longer exists** (CRITICAL)

**Where:** `CLAUDE.md:412`
**Anchor:** `   **The founding case is now closed** (i`
**What:** The worked example at `:412-415` reads "`lean_verify`'s `status:"ok"` ⇔ no-errors ∧ no-sorry ... is joined by an independent `axiom_audit` axis" in the present tense; after this diff no code path emits `"ok"`, and the diff updates no doc outside `docs/api.md`.
**Why it matters:** CLAUDE.md is loaded by every agent at session start and self-describes as load-bearing; an agent that trusts `:413` will grep for `status:"ok"`, find only stale comments, and either mis-implement a consumer or re-file the already-closed defect — precisely the failure mode §3's two "Staleness correction" blocks were written about.
**Proposed fix:** One-token edit at `:413` (`status:"ok"` → `status:"elaborated_no_errors"`) plus a short parenthetical that the token was renamed at verification-contract-m1 and that the historical name was `"ok"`. While in the block, note that `:422-426`'s claim that the `LEAN_VERIFY.description` edit and `TOOL_SCHEMA_VERSION` bump are "staged in w1-schema-deltas.md for the next batched re-pin" is separately stale — `w1-schema-deltas.md:20` records both as applied in W2 — but that half is pre-existing, not this diff's debt. Do **not** sweep `adr-data-plane-boundary.md:30` or `R3-verification-contract.md:10` in the same pass: those are Accepted/append-only historical records and are out of this milestone's scope by prior agreement.
**Regression-guard:** Extend the existing CLAUDE.md doc-consistency test (or add one) to assert that any `status:"..."` token CLAUDE.md attributes to `lean_verify` is a member of `server/schemas/lean_verify_result.json`'s `status.enum`, derived from the file rather than hard-coded.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M1 — Edited api.md line still lists 5 of the 7 status enum members** (MEDIUM)

**Where:** `docs/api.md:131`
**What:** The line the diff edited advertises `elaborated_no_errors / error / sorry / timeout / unavailable`, omitting `incomplete` and `invalid-input`, both of which are in the shipped schema enum and both of which `lean_verify` emits.
**Why it matters:** `docs/api.md` is the operator-facing wire contract (the only `docs/` chapter for this tool); an integrator reading it will treat two live status values as impossible, and the milestone whose stated purpose is honest status vocabulary is the worst possible moment to leave the enum under-reported.
**Proposed fix:** Add the two missing tokens to the same line: `` `elaborated_no_errors` / `error` / `sorry` / `incomplete` / `timeout` / `unavailable` / `invalid-input` ``. I have read the recorded decision that a full `api.md` resync was scope creep and I agree with it for the `tactic_step` mode row and the missing `axiom_audit` field — but completing an enum on a line the diff already rewrites is finishing the edit, not resyncing the page, and costs one line.
**Regression-guard:** Optional; if cheap, assert in a docs test that every member of `lean_verify_result.json`'s `status.enum` appears in `docs/api.md`'s `lean_verify` section.
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M2 — New ADR cites the pre-diff line range for `_attach_axiom_audit`** (MEDIUM)

**Where:** `.claude/docs/adr-verification-contract-five-operations.md:125`
**What:** Decision 4 cites `server/handlers/lean_verify.py:1077-1148`, which is exactly where `_attach_axiom_audit` lived **before** this commit; the 10-line status comment inserted at `:717-726` in the same commit moved the function to `1087-1158`.
**Why it matters:** The ADR is authored and shipped in the same commit that invalidates its own citation, so the document is wrong from its first read — and this repo's prior critiques have repeatedly had to re-derive drifted `lean_verify.py` ranges (the `290-298` legacy is cited in three other docs today).
**Proposed fix:** Change the citation to `server/handlers/lean_verify.py:1087-1158`, or better, drop the range and cite the symbol (`server/handlers/lean_verify.py::_attach_axiom_audit`) as the ADR already does elsewhere for `_normalize_response` at `:39` — a symbol reference does not rot on insertion.
**Regression-guard:** Not required (MEDIUM).
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**M3 — Axiom-hygiene banner comment still states `status="ok"` as live semantics** (MEDIUM)

**Where:** `server/handlers/lean_verify.py:363`
**Anchor:** `# the trust-language policy: `
**What:** The section banner at `:362-367` reads, present tense, "`status="ok"` <=> (no error-severity messages) AND (no sorries) ... the surface calls a proof of False 'ok'" — the exact sentence this milestone's rename corrects — while the module docstring two hundred lines above was updated in passing (`version 12` → `23`).
**Why it matters:** This is the file's own authoritative explanation of what `status` means, it is now false, and it is the first thing a maintainer reads before touching the axiom axis; it also keeps `"ok"` alive in the file for anyone grepping to confirm the rename is complete.
**Proposed fix:** Rewrite `:363-367` in the past tense against the new token, e.g. "CLAUDE.md §4.9 rule 1 named this module's `status` as THE live violation ... `status="elaborated_no_errors"` (renamed from `"ok"` at verification-contract-m1) <=> (no error-severity messages) AND (no sorries), so a bare `axiom h : False` elaborates clean and lands there." The historical narrative at `:662` ("the pre-m5 path (both empty ⇒ status "ok")") is genuinely about a removed code path and should be left alone.
**Regression-guard:** Not required (MEDIUM).
**Source critic:** milestone-adversary-critic
**Source axis:** Dead code / leftovers

**L1 — "No behaviour change" understates a wire-visible enum rename** (LOW)

**Where:** no specific file
**What:** The commit body and several in-code comments describe the change as "no behaviour change", which is true inside the server but not for an MCP consumer: any client branching on `status == "ok"` now silently takes its non-clean branch, and there is no CHANGES.md entry or migration note anywhere an out-of-tree integrator would look. Flagging with stated uncertainty — the sibling orchestrator repo is not inspectable from here, so I cannot demonstrate a live broken consumer, and `docs/api.md` plus the `TOOL_SCHEMA_VERSION` 22→23 bump are the repo's documented breaking-change signals.
**Why it matters:** The permanent record is the thing a future bisect or release-notes pass reads; framing a contract-vocabulary change as behaviour-neutral is what lets it be under-weighted later.
**Proposed fix:** Either add a one-line entry to `CHANGES.md` under the current unreleased section ("`lean_verify` `status` value `ok` renamed to `elaborated_no_errors`; TOOL_SCHEMA_VERSION 23 — consumers matching the literal must update"), or, if CHANGES.md is genuinely epic-grain-only by convention, record the decision in the milestone's implement synthesis so it is not re-litigated.
**Regression-guard:** Not required (LOW).
**Source critic:** milestone-adversary-critic
**Source axis:** Doc drift

**L2 — Test name retains the renamed token** (LOW)

**Where:** `tests/test_handlers_lean_verify.py:290`
**What:** `test_clean_compile_status_ok` keeps `ok` in its name while its body now asserts `elaborated_no_errors`; it is the only such residue in the suite.
**Why it matters:** Cosmetic only — but it is the one place a `grep -rn '\bok\b' tests/test_handlers_lean_verify.py` still hits, which costs a future reader a lookup.
**Proposed fix:** Rename to `test_clean_compile_status_elaborated_no_errors`. Defer if the rectifier is fix-count-constrained; nothing depends on the name.
**Regression-guard:** Not required (LOW).
**Source critic:** milestone-adversary-critic
**Source axis:** Dead code / leftovers

**M4 — Certificate-deferral rationale misreads the policy it cites** (MEDIUM)

**Where:** `.claude/docs/adr-verification-contract-five-operations.md:34`
**Anchor:** rule 3 requires a Certificate for a *graded
**What:** The ADR bullet and the mirrored comment at `server/handlers/lean_verify.py:717-726` defer `trust-language-policy.md` §6 rule 3 on the ground that `status` "is not graded — it is a single fact drawn from a fixed, mutually-exclusive ladder", but §6 rule 3 reads "Every trust-bearing field carries its `Certificate` (level + attached evidence), not a bare token" with no graded qualifier, and `server/schemas/lean_verify_result.json:162` defines `status` as an explicit ordinal ladder ("Precedence: 'unavailable' > 'timeout' > 'error' > 'sorry' > 'elaborated_no_errors'") — i.e. exactly the "ordinal level" §4 and Appendix A say must carry attached evidence.
**Why it matters:** The recorded justification is what `verification-contract-e3` will read when it decides whether the response schema still owes a Certificate shape; "the policy does not require it here" (false) and "we scoped it out of m1" (true) lead to different e3 outcomes, and CLAUDE.md §4.9 rule 1 is binding on that decision.
**Proposed fix:** Restate both the ADR bullet and the code comment as a *scoped deferral* rather than an exemption: `status` is not Certificate-wrapped in m1 because nesting it is a wire-breaking shape change owned by e3's response-schema redesign, and its evidence already ships as sibling fields (`messages`, `sorry_goals`, `proof_state`, `axiom_audit`) rather than as an attached record. Also drop the "Policy §2 itself names the rename below as the complete fix" clause (ADR:37, comment line 722-724) — §2 lines 74-76 name the rename *and* the five-operation split together as R3's remedy, not the rename alone.
**Regression-guard:** None needed (doc/rationale); the correction is verifiable by quoting `trust-language-policy.md:170-171` and `:74-76` back into the ADR bullet.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity / trust semantics

**M5 — `elaborated_no_errors` names one axis but is gated on two** (MEDIUM)

**Where:** `server/schemas/lean_verify_result.json:163`
**Anchor:** `      "enum": ["elaborated_no_errors", "e`
**What:** The value is emitted only when there are no error-severity messages AND no unresolved sorries (`server/handlers/lean_verify.py:727-734`), and in `tactic_step` only when `proofStatus == "Completed"` with no open goals and no sorries (`:829-837`) — so a token named after `trust-language-policy.md` §4 axis 5 (elaboration) is in fact gated on axis 6 (proof closure) in every mode.
**Why it matters:** Policy §4 forbids inferring one axis from another; under this name a consumer cannot read the elaboration axis off `status` at all, because an elaboration-clean snippet carrying a `sorry` reports `"sorry"` and an elaboration-clean tactic leaving goals reports `"incomplete"` — the rename replaced an axis-neutral token (`"ok"`) with one that claims an axis it does not purely report.
**Proposed fix:** Add one clause to the `status` description in `server/schemas/lean_verify_result.json` (no enum change, so no second re-pin window beyond the one already open): "`elaborated_no_errors` additionally requires no unresolved sorry (`full`/`syntax_only`) or all goals discharged (`tactic_step`); it is NOT a pure elaboration reading — `sorry` and `incomplete` results also elaborated without errors." Mirror the same sentence into `LEAN_VERIFY.description` if the rectifier is already re-pinning.
**Regression-guard:** `tests/test_handlers_lean_verify.py` — assert that a sorry-bearing response has zero `severity == "error"` messages while `status == "sorry"`, pinning that the elaboration axis is not readable from the token alone.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity / trust semantics

**M6 — trust-language-policy.md §2 now asserts the wire still carries "ok"** (MEDIUM)

**Where:** `.claude/docs/trust-language-policy.md:34`
**Anchor:** > planned five-operation redesign, which
**What:** The 2026-07-31 status-update block states "R3 renames `"ok"` → `elaborated_no_errors` describes R3's planned five-operation redesign, which has **not** shipped: `status` still carries the value `"ok"`, deliberately" — false as of this commit, and it is the very passage the ADR and the code comment cite as the authority for the rename.
**Why it matters:** The policy is Accepted, owner-approved, bound by CLAUDE.md §4.9, and referenced by path at the R3/R5 tool-surface gates; a reader following that reference will build against a status value the server no longer emits.
**Proposed fix:** Append a new dated status-update note (the append-don't-edit convention that the 2026-07-31 block itself established for this Accepted doc — do not edit §2 in place): "(2026-08-03, verification-contract-m1) statement (b) is now stale: the rename shipped at `TOOL_SCHEMA_VERSION` 23; `status` carries `elaborated_no_errors`. The five-operation split remains unbuilt."
**Regression-guard:** None needed (doc); a grep for `status` + `"ok"` in `.claude/docs/trust-language-policy.md` should return only text explicitly marked historical.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity / trust semantics

**M7 — CLAUDE.md §4.9 rule 1 still names the retired token** (MEDIUM)

**Where:** `CLAUDE.md:413`
**Anchor:** `status:"ok"` ⇔ no-errors ∧ no-sorry — which
**What:** The §4.9 rule-1 worked example states, in present tense, "`lean_verify`'s `status:"ok"` ⇔ no-errors ∧ no-sorry … is joined by an independent `axiom_audit` axis", which no longer describes any value the server emits.
**Why it matters:** CLAUDE.md is loaded at session start by every agent in this repo and is the single most-read description of this exact token; an agent writing a consumer will branch on `status == "ok"` and silently never match.
**Proposed fix:** One-token edit plus a parenthetical: "`status:"elaborated_no_errors"` (renamed from the original `"ok"` at verification-contract-m1, `TOOL_SCHEMA_VERSION` 23) ⇔ no-errors ∧ no-sorry …". While in §4.9, note that the sentence at `CLAUDE.md:421-425` about the `LEAN_VERIFY.description` edit being "staged in w1-schema-deltas.md for the next batched re-pin" was already resolved by the W2 window and now contradicts `.claude/docs/w1-schema-deltas.md:22`.
**Regression-guard:** None needed (doc).
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity / trust semantics

**M8 — the operator API reference for lean_verify is stale on the line edited** (MEDIUM)

**Where:** `docs/api.md:131`
**Anchor:** Returns `status` (`elaborated_no_errors` / `error`
**What:** The Returns block the milestone edited lists only five of the seven wire status values (missing `incomplete` and `invalid-input`, both live since lean-verify-continuation-m1), says `compilation_success` is "(null in `syntax_only`)" where the ToolMeta correctly says "null in syntax_only + tactic_step", omits `mode='tactic_step'` from the argument table at `:128`, and never mentions `axiom_audit`, `env`, `proof_state_id`, or `continuation_status`.
**Why it matters:** This is the only operator-facing description of the tool; it under-lists two status values a client must handle, and — most consequentially for this milestone — it hands the reader the newly honest status token while omitting the axiom axis that token explicitly defers trust to, which inverts the point of the rename. The recorded "one-token fix, not a resync" decision is defensible for the rest of `api.md` but not for the four sentences immediately adjacent to the edit.
**Proposed fix:** Resync the block: add `incomplete` / `invalid-input` to the enum list, change to "(null in `syntax_only` and `tactic_step`)", add the `tactic_step` mode row and the `env` / `proof_state` argument rows, and add one sentence — "`axiom_audit` reports the transitive axiom closure independently; `status` and `compilation_success` never speak to axiom soundness."
**Regression-guard:** None needed (doc); optionally a test asserting every member of the schema's `status` enum appears literally in `docs/api.md`'s lean_verify section.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity / trust semantics

**L3 — module comment still says the surface calls a proof of False "ok"** (LOW)

**Where:** `server/handlers/lean_verify.py:363`
**Anchor:** # the trust-language policy: ``status="ok"``
**What:** The "Axiom-hygiene axis" header comment reads, in present tense, "`status="ok"` <=> (no error-severity messages) AND (no sorries) … the surface calls a proof of `False` "ok"" — describing a token this same commit renamed 370 lines below.
**Why it matters:** The milestone deliberately fixed the sibling staleness in this file (the module docstring's "version 12" → 23), so leaving the file's own canonical explanation of the defect naming the old token is an inconsistency a future reader will trip on; it is also the block the ADR points at for the code-level reasoning.
**Proposed fix:** Retag the block as historical — "the original `status="ok"` (renamed to `elaborated_no_errors` at verification-contract-m1) <=> …" — and update the closing sentence to "the surface called a proof of `False` clean".
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** math fidelity / trust semantics

**L4 — ADR defers the strict_replay_proof tool choice without a no-fork bound** (LOW)

**Where:** `.claude/docs/adr-verification-contract-five-operations.md:185`
**Anchor:** CLI wrapper vs a bespoke fresh-process re-e
**What:** Decision 5 records that SafeVerify's four published backport branches (4.9.0 / 4.14.0 / 4.15.0 / 4.20.0) do not cover the pinned `v4.30.0-rc2` toolchain and defers the concrete tool choice to `verification-contract-spike-2`, without naming CLAUDE.md §4.7's no-fork policy as a constraint on that choice.
**Why it matters:** The most obvious way to resolve "no branch matches our toolchain" is to backport SafeVerify's source into this repo — a direct OSS file lift, which the no-fork policy forbids; the ADR is the document spike-2 will read as its option set.
**Proposed fix:** Add one bullet under "Deliberately NOT decided here": "Whatever spike-2 chooses must be an unmodified upstream dependency invoked as a subprocess, or a bespoke arXMCP implementation — vendoring, forking, or backporting SafeVerify's source into this repo is out of bounds (CLAUDE.md §4.7)."
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** no-fork policy

## What was done well

### From milestone-adversary-critic

- **The rename is complete in code.** All ten sites moved: the status ladder
  (`lean_verify.py:734`), both `compilation_success` derivations (`:740`, `:743`),
  the `_default_audit_for` gate (`:787`), the `_normalize_tactic_step` closure
  branch (`:833`), and the `handle_lean_verify` axiom-audit gate (`:1458`). A
  repo-wide grep for a residual `"status": "ok"` returns only `/healthz` and
  backup-sentinel hits, all unrelated.
- **No behaviour actually changed, and I checked rather than assumed.**
  `compilation_success` is still `None` for a clean `syntax_only` pass and
  unconditionally `None` for `tactic_step`; `error` / `sorry` still yield `False`;
  the `mode == "full"` axiom-audit round-trip still fires on exactly
  `{clean, sorry}`. No null-vs-bool boundary moved.
- **The three axes stay independently derived.** `status`, `compilation_success`,
  and `axiom_audit` are each computed from their own evidence, and
  `TestAxiomHygieneOnTheWire` asserts the pairing that proves it —
  `status == "elaborated_no_errors"` *and* `axiom_audit.outcome == "flagged"` on
  `axiom h : False`. That is AC2 demonstrated, not merely claimed.
- **Negative assertions kept their polarity.** Both `!= "ok"` sites (the
  continuation-scope test and the RLIMIT_AS cap test) flipped target string only,
  with their explanatory comments rewritten in step — an inverted assertion here
  would have silently disarmed the memory-cap guard.
- **Schema enum and emitted vocabulary stayed in lockstep.** Every value the
  handler can produce (`error`, `sorry`, `elaborated_no_errors`, `incomplete`,
  `timeout`, `unavailable`, `invalid-input`) is in the JSON enum, so the Draft7
  conformance suite is a real coupling rather than a structural formality.
- **The frozen-schema re-pin was done in the documented order and completely.**
  `TOOL_SCHEMA_VERSION` 22→23, both `server/schemas/*.json` `version` **and** `$id`
  fields, `EXPECTED_TOOL_SCHEMA_SHA256`, `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`, and
  the hand-edited `EXPECTED_BP1_SHA256` — with a rationale comment at each pin
  explaining why this window is BP1-affecting. `w1-schema-deltas.md` was correctly
  left alone: it currently stages nothing, so no queued delta was skipped.
- **The ADR meets AC4 on its own terms and resolves rather than defers the one
  question that mattered.** Each of the five operations has inputs, isolation
  dependency, and target-binding behaviour; Decision 3/5's `check_declaration`
  vs `strict_replay_proof` split is argued from AXLE's own verbatim §4.1 limitation
  and SafeVerify's failure taxonomy, and Decision 6 closes the checker-identity axis
  explicitly instead of leaving it silently unaddressed. No operation is implemented.
- **Research provenance is honest.** Every external claim I spot-checked (the AXLE
  §4.1 quote, the 0.97s/10.1s medians, the REPL protocol's three modes, the Lean
  4.29.0 axiom-naming change) traces to a sha256-pinned source in `research/brief-2.md`
  and is reproduced accurately in the ADR.
- **Boundaries respected.** No external write (HEAD is one commit ahead of
  `origin/main`, unpushed), no `plans/*/roadmap.yaml` or journal edit, no new
  dependency, commit GPG-signed with the mandated co-author trailer and a
  34-character conventional subject.
- **`Status: Proposed` was the right call and is justified in the document itself.**
  The Owner approval record states plainly that no round-trip ran and why asserting
  `Accepted` would be a false claim — that is the trust-language policy applied to
  the ADR's own metadata, not just to the tool surface.

### From milestone-arxmcp-critic

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

Severity counts: C2 H0 M8 L4


## Cross-critic agreement

The following findings cluster within 5 lines of each other in the same file. Multiple critics flagged the same area - these are the strongest signals to fix first.

- **C1, M6** at `.claude/docs/trust-language-policy.md:34-34` (CRITICAL): Policy doc still asserts the rename has not shipped; trust-language-policy.md §2 now asserts the wire still carries "ok"
- **C2, M7** at `CLAUDE.md:412-413` (CRITICAL): CLAUDE.md §4.9 rule 1 names a status token that no longer exists; CLAUDE.md §4.9 rule 1 still names the retired token
- **M1, M8** at `docs/api.md:131-131` (MEDIUM): Edited api.md line still lists 5 of the 7 status enum members; the operator API reference for lean_verify is stale on the line edited
- **M3, L3** at `server/handlers/lean_verify.py:363-363` (MEDIUM): Axiom-hygiene banner comment still states `status="ok"` as live semantics; module comment still says the surface calls a proof of False "ok"

## Recommended rectification order

C1, C2, M4, M5, M6, M7, M8, M1, M2, M3, L1, L2, L3, L4

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: 
- Deferred: 
- Invalidated: 
- Regression tests added: 
