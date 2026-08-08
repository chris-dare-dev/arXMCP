---
handoff_kind: review
date: 2026-07-25
companion: HANDOFF-2026-07-25-lean-verify-continuation-continuation.md
roadmap: plans/verification-feedback-roadmap.md
reviewer_target: opus
review_status: requested
milestones_covered:
- lean-verify-continuation-m1
tags:
- handoff/review
- review/requested
aliases:
- lean-verify-continuation — review handoff (2026-07-25)
---

# HANDOFF (REVIEW) — lean-verify-continuation session, 2026-07-25

> **Audience:** a high-effort opus review session. **Goal:** independently scrutinize everything
> shipped this session — correctness, safety, whether the "done" claims are honest, the coding
> practices, and the program direction — against the diffs and live state. This is a REVIEW handoff
> (find problems); the companion continuation handoff
> ([[HANDOFF-2026-07-25-lean-verify-continuation-continuation]]) is for the next builder. Lineage
> roadmap: `plans/verification-feedback-roadmap.md`.

## 0. TL;DR — what this session did

| # | Work | Repo(s) | Key SHAs (branch) | State |
|---|---|---|---|---|
| 1 | `lean-verify-continuation-m1` — env + proofState continuation through `lean_verify` (+ a fail-open fix) | arXMCP | `755dc5e`, `37a1e02` (main) | SHIPPED + PUSHED |
| 2 | Build Mathlib into the Lean REPL package (env prerequisite) | `lean-repl-spike/repl` (NOT in the arXMCP repo) | repl `0cc6026` (detached HEAD) | LIVE, uncommitted lakefile change |
| 3 | Two out-of-scope follow-ups spawned as background chips | — | — | DISPATCHED to separate sessions |

The session started as a **read-only capability audit** ("does arXMCP support Lean/proof
formalization?"), found a real kernel-backed `lean_verify` tool that was off, un-Mathlib'd, and
had a latent fail-open; built Mathlib into its REPL; then ran a full 4-phase milestone to thread
the REPL's `env` and `proofState` continuation ids through the tool (import-once-reuse + proof
stepping) and close the fail-open. Item 1 is a **live-behavior change to the served tool surface**
(but the tool is flag-off by default). Item 2 is a **live environment change outside the repo**.
Item 3 is dormant (other sessions own it).

## 1. lean-verify-continuation-m1 — the milestone (SHIPPED)

**What & why.** `lean_verify` gains opaque `env` and `proof_state` continuation tokens and a
`mode="tactic_step"`, so the autoformalizer/tactician pipeline can pay `import Mathlib` once and
reuse the environment (~700× on warm calls, measured) and step a proof incrementally. The REPL's
`env`/`proofState` ids are process-local integers; the tool never exposes them raw — it emits
`"{generation}:{int}"` where `generation` is a per-spawn random hex (`LeanRepl.generation`,
`secrets.token_hex(8)`), and rejects (fail-closed `invalid-input`) any token whose generation ≠ the
live REPL — defeating cross-respawn misbinding (env counters restart at 0 on respawn).

**The fail-open fix (primary soundness item).** Research found the REPL's stale-id reply
`{"message":"Unknown environment."}` carries neither `messages` nor `sorries`, so the pre-change
`_normalize_response` reported it as `status:"ok"`, `compilation_success:true`. Now
`_normalize_response` dispatches three shapes, checking the bare-`message` shape FIRST and failing
it closed.

**New surface.** Input: `env`, `proof_state`, `mode="tactic_step"`. Output (all always-emitted,
schema `required`): `env`, `proof_state_id` (top-level + per-sorry), `continuation_status`
(`not-applicable`/`resumed`/`expired`/`unknown-id`/`malformed`); `status` enum gains `incomplete`
+ `invalid-input`. `tactic_step` NEVER yields `compilation_success:true` (a tactic step is not a
full-declaration kernel check — trust-policy §4.9).

**Files (feat `755dc5e`):** `server/handlers/lean_verify.py` (codec + three-shape normalizer +
input validation), `server/lean_repl.py` (`generation`), `server/tools.py`
(`TOOL_SCHEMA_VERSION 19→20` + `LEAN_VERIFY.description`), `server/schemas/lean_verify_result.json`
+ `server/schemas/search_papers_result.json` (v19→v20 + `$id`),
`tests/test_handlers_lean_verify.py` (+31 tests), `tests/test_prompts.py` +
`tests/test_server_tool_schema.py` (hash re-pins). Notes (chore `37a1e02`):
`.claude/notes/milestones/lean-verify-continuation-m1/*`.

**Adversary critique already ran** (independent subagent, 6 axes; verdict SOUND on fail-open;
7 findings, 0 invalidated). F1 (HIGH: failed-tactic mislabeled as a bad token) + F2 (MED: tactic_step
dropped the `sorries` frontier) + F3/F4/F5 (LOW) were FIXED and folded into `755dc5e`; F7 (unbounded
env growth) deferred to R3 m7. Full record:
`.claude/notes/milestones/lean-verify-continuation-m1/critique-adversary.md`.

### What to SCRUTINIZE
- **The fail-open discriminator.** Shape-1 routes a bare `message` to `unknown-id` only if it
  `.strip().startswith(("Unknown environment","Unknown proof state"))`; everything else routes to
  `status:"error"`. Both are fail-closed, but: (a) is the string-match robust to a Lean/REPL
  version bump that reworded those strings? If reworded, a real unknown-id would fall to `error`
  (still fail-closed, but the continuation axis lies). (b) Can any *legitimate* cmd/tactic success
  reply ever carry a top-level `message` AND satisfy the guard? I claim no (verified against
  leanprover-community/repl `REPL/JSON.lean` — CommandResponse always serializes `env`), but
  re-derive it. This is THE soundness claim; try to construct a false `ok`.
- **`tactic_step` status honesty.** `status:"ok"` + `compilation_success:null` for a `Completed`
  tactic step. Is that honest under §4.9 ("no bare verified", "no axis inferred from another"), or
  could a consumer read `ok` as "theorem verified"? Check the field descriptions carry their weight.
  Also: `getProofStatus` returns `"Completed"` only after a real `addDecl` kernel check of a
  sorry-free term — confirm no sorry-/metavariable-closed proof yields `ok`.
- **The generation guard.** `secrets.token_hex(8)` = 64-bit per spawn; the cross-process-collision
  argument depends on the OLD and NEW generation never colliding after a respawn. Is 64-bit + no
  persistence adequate? Does the timeout-respawn path (`lean_verify.py` `LeanReplTimeoutError`
  branch) actually re-mint the generation (it calls `LeanRepl.spawn_from_config` → `spawn` →
  `__init__`, which auto-assigns)? Attack `_decode_token`'s `rpartition`/`int()` leniency
  (`"g: 5"`, `"g:+5"`, huge ints) for anything exploitable.
- **The schema/hash cascade.** Confirm `TOOL_SCHEMA_VERSION=20` is echoed by BOTH
  `server/schemas/*.json` (`version` + `$id`), that `EXPECTED_TOOL_SCHEMA_SHA256` /
  `EXPECTED_BP1_SHA256` / `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` are the freshly re-pinned values,
  and that no *other* pinned hash was missed. Run the gating tests (`test_server_tool_schema`,
  `test_prompts`, `test_bootstrap_mode`, `test_mcp_resources`, `test_mcp_instructions`,
  `test_corpus_manifest`, `test_search_filter`, `test_snippet_contract`).
- **Data-plane boundary (§4.8 r2).** Env reuse holds environment state in the REPL process across
  calls. Is that acceptable ephemeral compute state (like the retrieval cache), or does it drift
  toward "per-run agent memory" the ADR forbids? One REPL is shared by pipeline sub-agents — a
  leaked env token lets agent B build on agent A's (possibly axiom-poisoned) env. Envs are immutable
  snapshots (no mutation leakage), single-user workstation bounds the blast — but judge whether that
  reasoning holds.
- **Every envelope path emits all 12 `required` fields.** Six builders (`_normalize_response`,
  `_normalize_tactic_step`, `_disabled_envelope`, `_timeout_envelope`, `_invalid_continuation_envelope`,
  `_message_error_envelope`, plus the inline `LeanReplError` dict). A missed field → `additionalProperties:false`
  Draft-7 rejection at runtime. The conformance suite covers most, not the disabled/timeout/inline
  paths — check those by eye.

## 2. Mathlib build into the REPL package (LIVE, uncommitted)

**What & why.** The `lean_verify` REPL was core-only (no Mathlib) — the tool couldn't check any
research-math statement. Added Mathlib `v4.31.0` as a `[[require]]` git+rev in
`~/lean-repl-spike/repl/lakefile.toml`, bumped the toolchain to `v4.31.0`, `lake update` (post-hook
`cache get` pulled 8542 oleans — cache hit, no source build), `lake build repl`. Verified: `import
Mathlib` + `irrational_sqrt_two` + `ring` over ℝ all typecheck through the real handler.

### What to SCRUTINIZE
- **This is outside the arXMCP repo and partly uncommitted.** `~/lean-repl-spike/repl` is in
  **detached HEAD** at `0cc6026` with an uncommitted `lakefile.toml` change (the Mathlib require).
  A stray `git checkout` there silently loses the Mathlib wiring and the tool reverts to core-only
  with no error. Judge: should this be pinned/committed on a branch? Is depending on an
  uncommitted out-of-repo build state acceptable for a "shipped" capability?
- **Cold-import cost variance.** Measured 14.5 s – **235 s** for `import Mathlib` (235 s this
  session). The tool's 30 s per-call cap means an agent call that imports Mathlib **times out** —
  the reuse pattern only works via an operator pre-warm (there is NO server-side preload yet; that's
  the proposed m2). Is "shipped" honest given the headline feature needs a manual pre-warm to be
  usable? (I labeled it so in the continuation handoff §2 — verify the labeling is honest.)
- **RLIMIT_AS on POSIX.** `lean_rlimit_as_bytes` defaults to 4 GiB; Mathlib RSS measured 3129 MB and
  `RLIMIT_AS` caps *address space* (mmap'd oleans exceed RSS). Windows skips the cap (no Job Object)
  so it works here; **Linux/macOS may OOM-kill the child at 4 GiB**. Not exercised this session.

## 3. Cross-cutting durable gotchas + decisions

1. **2-commit structure, not the fleet 3-commit triple.** feat `755dc5e` FOLDS IN the rectification
   (F1–F5) rather than a separate `rect(...)` commit, because the adversary critique ran on the
   working tree (uncommitted) — there was no pre-rectify commit to anchor a `rect` against.
   Deliberate + documented (state.json `rectification_note`). Judge it as a process deviation, not a
   missing rectification — the critique + fixes are real and tested.
2. **Concurrent sessions on `main`.** This session's commits interleaved with other sessions'
   (`retrieval-unlocks-m4` `e1a91c6`/`6ade74e` landed mid-session; `5335c58` "compact search
   content[0]" is a concurrent **unpushed** commit currently on local `main`, NOT this session's).
   origin/main = `37a1e02` (this session's tip). Don't attribute `5335c58` or `e1a91c6` to this
   review.
3. **F7 deferral is a documented decision, not a gap.** Per-env eviction is impossible in the pinned
   REPL (append-only snapshot arrays, no drop/gc command); a proactive-respawn policy is R3-m7
   pooled-worker lifecycle. Resolved as a coordination handoff to R3 m7 (edited the R3 brief +
   `lean-sandbox-design.md`, no `server/` code) — that edit was made by a SEPARATE background
   session, visible in `critique-adversary.md` §F7. Judge the *reasoning*, not as unfinished work.
4. **Full-suite-with-lean caveat.** `make test` is green in the DEFAULT config (enable-lean off).
   Running it WITH `ARXMCP_ENABLE_LEAN=true` fails ~17 startup/security/metrics tests — a
   **pre-existing** pid-less-`_FakeProc` limitation, not a regression (proven by running the same 17
   with the env unset → all pass).

## 4. Verification evidence (as of handoff)

- **`make test` (default config, clean env):** ruff clean; full `pytest` **0 failures** (skips +
  1 xfail only). Run this session on the working tree post-rectification.
- **Real-REPL integration** (`ARXMCP_ENABLE_LEAN=true` + path vars, `pytest -m requires_lean_repl`
  on `tests/test_handlers_lean_verify.py`): **passed** including the 4 new continuation tests + the
  2 F1/F2 regression tests + the fail-open guard end-to-end (1 POSIX-only RLIMIT skip on Windows).
- **Live end-to-end demo** (`scratchpad/demo_v2.py`, real handler + real Mathlib REPL): env reuse
  (resumed), the control proving the env carried a `def`, proof stepping (`simp` closes a `sorry`),
  Mathlib reuse (235 s import → 0.00 s reuse), and BOTH fail-closed paths (`expired` via generation
  mismatch, `unknown-id` via the message-shape guard). All behaved as designed.
- **NOT verified:** POSIX `RLIMIT_AS` behavior at 4 GiB with Mathlib resident (Windows-only box);
  the ~17 enable-lean-startup failures beyond confirming they pass with the env unset; long-session
  env-growth memory pressure (F7, deferred).

## 5. How to review (repro + response contract)

- **Diff access — arXMCP** (`C:\Users\cedar\Documents\Personal Projects\Source Code\arXMCP`,
  branch `main`): this session's range is `6ade74e..37a1e02` —
  `git log --oneline 6ade74e..37a1e02` (feat `755dc5e`, chore `37a1e02`). **Exclude `5335c58`** (on
  local `main` above `37a1e02`) — it is a concurrent session's unpushed work, not this session's.
  Pushed tip: `git ls-remote origin refs/heads/main` = `37a1e02`.
- **Diff access — Lean REPL** (`C:\Users\cedar\lean-repl-spike\repl`, detached HEAD `0cc6026`):
  `git diff` shows the uncommitted `lakefile.toml` Mathlib require; `git show 0cc6026` is the
  toolchain bump. Not an arXMCP-repo artifact.
- **Review axes:** (1) correctness/safety of each change — esp. the fail-open discriminator and the
  generation guard; (2) honesty of the done-claims against §4 evidence — esp. "shipped" for a
  feature whose headline needs a manual pre-warm; (3) coding practices (the 2-vs-3-commit deviation,
  test blast radius, the schema cascade); (4) program direction — is m2 (preload) the right next
  step, or should R3 proper come first?
- **Calibrate the verdict to state:** `lean_verify` is **flag-off by default** — judge item 1 on
  "safe + honest when enabled", not on "not yet enabled in prod". Item 2 (Mathlib build) is a live
  local env, judge on "reproducible + safe to depend on".
- **Response format:** per-finding — severity (CRITICAL/HIGH/MED/LOW), the claim it refutes, evidence
  (`file:line` / command output), suggested disposition. End with an overall verdict:
  **SHIP / SHIP-WITH-FIXES / NO-GO**, scoped per milestone (item 1 and item 2 separately).
