# Critique — verification-contract-m1 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** 3a7d626e9aa7c59d8fd06599c15a20ee771719b2..6c681b9bf88469dcb147844fa40ee6ccf5624839
**Diff stats:** 9 files, 400 LOC (+345 / −55; 252 of the insertions are the design-only ADR)
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. The code half of this milestone is genuinely clean: every one of
the ten `"ok"` comparison sites moved, `compilation_success` / `axiom_audit` /
`continuation_status` keep their exact prior derivations, the schema `enum` and
the handler's emitted vocabulary stay in lockstep, and the two `!= "ok"` negative
assertions were flipped with polarity preserved. What is not done is the doc half:
the rename falsifies a present-tense factual claim in **two binding constitution
documents** — `trust-language-policy.md` §2 amendment (b) literally states that
`status` "still carries the value `"ok"`, deliberately", and CLAUDE.md §4.9 rule 1
names `status:"ok"` as the live token — and neither was amended. Everything else
found is MEDIUM-or-below doc/comment drift.

## Executive summary

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

## What was done well

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

Severity counts: C2 H0 M3 L2

## Recommended rectification order

C1, C2, M1, M2, M3, L1, L2

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
