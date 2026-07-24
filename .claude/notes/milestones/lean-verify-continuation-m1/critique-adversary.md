# lean-verify-continuation-m1 — Adversary critique + rectification

Independent adversary-critic pass (general-purpose subagent, 6 axes: soundness
/ token-codec / schema-cache / data-plane-boundary / concurrency / edges). The
critic drove the **real** leanprover-community/repl and the real handler to
prove its confirmed findings. I (main thread) verified each finding against the
real REPL before accepting it.

## Verdict from the critique
**SOUND on the fail-open axis** — no path yields a false `status:"ok"` /
`compilation_success:true`. The primary soundness fix (the unknown-id guard)
is correct; tactic_step `ok` requires a real kernel-checked `Completed`; every
envelope is schema-conformant (153 gating tests + all 6 builders validated);
the generation guard defeats cross-respawn misbinding. **But not clean**: the
same guard over-fired on tactic failures (F1), and the sorry frontier was
dropped in tactic_step (F2) — the new mode was broken on its two commonest
non-success outcomes even though it never lied toward ok.

## Findings and disposition

| # | Sev | Finding | Disposition |
|---|-----|---------|-------------|
| F1 | HIGH | A failed tactic returns a bare `{"message":"Lean error:\n..."}`; Shape-1 caught ANY bare `message` and mislabeled it `invalid-input`/`unknown-id` (wrong axis; breaks the tactician loop). Verified live. | **FIXED** |
| F2 | MED | `_normalize_tactic_step` hardcoded `sorry_goals:[]`; a sorry-introducing tactic (`{"goals":[],"sorries":[...]}`) lost its frontier + resumable proofState. Verified live. | **FIXED** |
| F3 | LOW-MED | imports + env silently prepended an `import` into a continued env → confusing kernel error. | **FIXED** (reject up front) |
| F4 | LOW | timeout / generic-error envelopes hardcoded `continuation_status="not-applicable"` even when a token was resumed. | **FIXED** (thread `resumed`) |
| F5 | LOW | `env` silently ignored in tactic_step (asymmetric with proof_state rejection in full mode). | **FIXED** (reject) |
| F6 | LOW (plausible) | Shape-1 could mislabel any bare `message` regardless of token. | **Subsumed by F1** — non-unknown-id messages now route to `error`. |
| F7 | LOW (ack) | Unbounded in-process env growth; only a respawn frees the tree. | **DEFERRED** (see below) |

## Rectification (all in `server/handlers/lean_verify.py` unless noted)

- **F1/F6** — Shape-1 now discriminates on the EXACT REPL strings
  `_UNKNOWN_ID_PREFIXES = ("Unknown environment", "Unknown proof state")`
  (verified live via `scratchpad/rectify_probe.py`). A matching bare message →
  `invalid-input`/`unknown-id` (fail-closed). ANY OTHER bare message (a thrown
  `Lean error:\n...`) → new `_message_error_envelope` = `status:"error"`,
  `continuation_status` reflects the (valid) token. Both branches fail closed.
- **F2** — new shared `_project_sorries()` used by BOTH the cmd branch and
  `_normalize_tactic_step`; tactic_step now surfaces `sorry_goals` (with
  per-sorry `proof_state_id`) and reads them into the status decision
  (open goals OR sorries ⇒ `incomplete`).
- **F3** — imports + env ⇒ `invalid-input`/`malformed`, no query.
- **F4** — `_timeout_envelope` gains a `continuation_status` param; the inline
  `LeanReplError` envelope reflects `resumed`.
- **F5** — env in tactic_step ⇒ `invalid-input`/`malformed`, no query.
- Schema: `continuation_status` `malformed` description broadened to cover the
  incompatible-combination rejections (no shape change; version stays v20).

**Regression tests added** (`tests/test_handlers_lean_verify.py`): F1 (thrown
Lean-error ⇒ error, token resumed), F2 (sorry-tactic frontier surfaced), F3,
F5; plus real-REPL end-to-end for F1 (`exact (42:Nat)` on `⊢ True`) and F2
(`sorry` tactic). All green (handler suite + real REPL).

## F7 — deferred with rationale (owner decision)
Every REPL command mints a new immutable env snapshot in-process; nothing is
freed until a timeout-respawn or operator restart. Not a soundness issue and
not introduced by this milestone (it is the REPL's env model). A hard cap would
have to live in the REPL protocol layer (env eviction), not the handler, and is
a larger change. Mitigations in place: env reuse is opt-in; the respawn resets
the tree. **Follow-up candidate for R3's warm-pool/worker milestone**, where env
lifecycle is already in scope. Documented in research-synthesis §2.5 + here.

## Hash/cascade note
The rectification did NOT touch the tool inputSchema, `LEAN_VERIFY.description`,
`TOOL_SCHEMA_VERSION`, or the search schema — so `EXPECTED_TOOL_SCHEMA_SHA256`,
`EXPECTED_BP1_SHA256`, and the version cascade are UNCHANGED from the
implementation commit. Only handler logic + one result-schema description edit.
