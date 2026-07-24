# lean-verify-continuation-m1 — Research synthesis

**Goal.** Thread the two leanprover-community/repl *continuation ids* — the
environment id and the proof-state id — through the `lean_verify` MCP tool, so
the autoformalizer/tactician pipeline can (a) pay `import Mathlib` **once** and
reuse it, and (b) step a proof incrementally instead of resubmitting whole
snippets. Chosen scope (owner, 2026-07-24): **env reuse + proof stepping**.

**Lineage.** Continues `verification-feedback-m1..m4` (config → LeanRepl harness
→ lean_verify handler → progress heartbeats). Governed by the R3
`verification-contract` brief (`.claude/roadmap-briefs/R3-verification-contract.md`)
and the trust-language policy (`.claude/docs/trust-language-policy.md` §1/§2) —
this milestone must NOT introduce a fail-open path or a bare trust token.

**Base commit.** `6ade74e` (main). `TOOL_SCHEMA_VERSION = 19`
(`server/tools.py:186`). NOTE: a concurrent session landed `retrieval-unlocks-m4`
(`e1a91c6`, `6ade74e`) during this work; it touched `equation.py` /
`retrieval/equations.py` / `config.py` — NOT `tools.py`, `server/schemas/*`, or
`tests/test_server_tool_schema.py`, so the schema-version machinery is un-forked.
Re-verify version+hash live immediately before editing.

---

## 1. Protocol semantics — measured live (Mathlib-enabled REPL, 2026-07-24)

Probe: `scratchpad/protocol_probe.py`. Cold `import Mathlib` = 18.78 s; every
continuation call below = **0.00–0.05 s**.

| Q | Finding |
|---|---|
| **Env id is fresh per call** | `{"cmd":"def foo…","env":0}` → `{"env":1}`. Even a read-only `#check` advances the counter (`env:1`→`env:2`). The REPL returns a **new** env id every command; the input env is the *parent* snapshot. ⇒ the output token is always the freshly-produced env, and callers chain by passing it forward. |
| **Envs are immutable snapshots** | `foo` defined continuing env 0 (→ env 1) is visible via `#check foo` **in env 1** but `Unknown identifier 'foo'` **in env 0**. ⇒ a reused env cannot be mutated out from under another caller; reuse is a read of a frozen snapshot. This de-fangs cross-caller *mutation*, though a caller that *chooses* a poisoned parent still builds on it (see §3). |
| **Proof stepping works** | sorry → `{"sorries":[{"proofState":0,"goal":"n : ℕ\n⊢ n + 0 = n",…}]}`. Then `{"tactic":"simp","proofState":0}` → `{"proofStatus":"Completed","proofState":1,"goals":[]}`. A **distinct** response shape: no `env`; carries `proofStatus` / `proofState` (new id) / `goals` (remaining goal strings) and may carry `messages` (tactic errors). |
| **Stale/unknown id → distinct error shape** | `{"cmd":"…","env":999}` → `{"message":"Unknown environment."}`. `{"tactic":"…","proofState":999}` → `{"message":"Unknown proof state."}`. A **top-level `message` string**, with NO `messages` array and NO `sorries`. |

### 1a. The fail-OPEN hazard (primary soundness finding)

Today `_normalize_response` (`server/handlers/lean_verify.py:258-259`) does
`resp.get("messages") or []` / `resp.get("sorries") or []`. An
`{"message":"Unknown environment."}` response has **neither** ⇒ it currently
normalizes to `has_error=False, has_sorry=False` ⇒ **`status:"ok"`,
`compilation_success:true`**. A stale env/proofState id would be reported as a
clean kernel accept. This is a false-accept and MUST be closed by detecting the
top-level `message` key **before** the messages/sorries branch.

### 1b. Cross-process collision (why the protocol error is not enough)

The "Unknown environment" guard only fires *within one process*. On a per-query
timeout the handler kills + respawns the REPL (`lean_verify.py:518-531`); the new
process restarts its env counter at 0. A stale env id from the old process
(e.g. `1`) can **collide** with a live env `1` in the new process ⇒ silent
misbind, not "Unknown environment". ⇒ a **per-spawn generation token** is
required so a token minted before a respawn is rejected structurally.

---

## 2. Design

### 2.1 Opaque, generation-guarded continuation tokens
- `LeanRepl` gains `self.generation` = a short random hex minted in `spawn()`
  (one per subprocess instance). Exposed as a read-only property.
- The tool never exposes the raw REPL integer. It emits an **opaque token**
  `"{generation}:{int}"`. On input it splits, checks `generation ==
  resources.lean_repl.generation`, and:
  - match → forward the int to the REPL;
  - generation mismatch → **fail closed** (`expired`); never forward.
  - unparseable → **fail closed** (`malformed`).
  This makes a stale token from a prior REPL instance impossible to misbind, and
  prevents a caller fabricating a raw int.

### 2.2 Tool surface (input)
- `env: str | None` — token from a prior call to continue a cmd-mode call
  (`mode` ∈ {full, syntax_only}). None ⇒ fresh env 0.
- `mode` gains a third value **`tactic_step`**. In that mode `snippet` is the
  **tactic** text and `proof_state: str | None` (required) is the token of the
  state to step. `env` is ignored in tactic_step.
- `proof_state: str | None` — token for tactic_step.

### 2.3 Tool surface (output) — additive, all optional/nullable
- `env: string | null` — token of the environment this call produced (cmd
  modes; null in tactic_step and on any error/timeout/disabled path).
- `proof_state_id: string | null` — token of a resumable proof state. In cmd
  mode = the first sorry's proofState (parallel to the existing `proof_state`,
  which stays the first sorry's goal **text**). In tactic_step = the state after
  the tactic.
- `sorry_goals[*].proof_state_id: string` — per-sorry token so a specific sorry
  can be targeted.
- `continuation_status: string` — namespaced axis (NOT folded into `status`, per
  trust-policy §1 "no axis inferred from another"): one of
  `not-applicable` (no token supplied) / `resumed` (token accepted + used) /
  `expired` (generation mismatch — REPL respawned) / `unknown-id` (protocol
  "Unknown environment/proof state") / `malformed` (unparseable token).
- `status` enum gains **`invalid-input`** for the expired/unknown-id/malformed
  paths (an operational status named in trust-policy §2, kept distinct from the
  epistemic `error`/`sorry`/`ok`). On those paths `compilation_success=false`.

### 2.4 Three response shapes in `_normalize_response`
1. **Top-level `message`** (checked FIRST — closes §1a) ⇒
   `status="invalid-input"`, `continuation_status="unknown-id"`,
   `compilation_success=false`, message surfaced.
2. **tactic_step** (`goals`/`proofStatus` present) ⇒ map `goals` →
   `goals_remaining`, `proofState` → `proof_state_id` token, `proofStatus`
   →status (Completed ⇒ ok; goals remain ⇒ sorry-like/`incomplete`), tactic
   `messages` errors ⇒ error.
3. **cmd** (as today) ⇒ plus `env` token + per-sorry `proof_state_id`.

### 2.5 Bounds / boundary
- Immutable envs accumulate in-process (each command mints one). Mitigations:
  env reuse is opt-in; the operator timeout/respawn resets the tree; document
  the growth. A hard live-env cap is a candidate but likely out of scope for m1
  (flag for critique).
- Data-plane boundary (§4.8 r2): reused envs are **ephemeral compute state** in
  the REPL process (like the retrieval cache), not corpus writes and not
  per-agent memory. Within-boundary — but flag for the critic to confirm.

---

## 3. Risks the critique phase must stress
- **R-1 Fail-open regression** if the `message`-shape branch is ordered after
  messages/sorries. (Primary.)
- **R-2 Cross-process misbind** if the generation guard is missing or the token
  is a bare int.
- **R-3 Poisoned-parent reuse.** A caller can pass a token whose env contains
  `axiom evil : False`. Immutability prevents *leakage* but not *deliberate
  chaining*. Until R3's `audit_axioms` exists, env reuse cannot certify the base;
  document that reuse inherits the parent's axioms.
- **R-4 Schema-version cascade** (see the blast-radius map): a missed
  `version:19→20` echo in any `server/schemas/*.json` turns the suite red (the
  documented 2026-07-14 RED-for-two-days failure mode).
- **R-5 Concurrent tenancy.** One REPL shared by pipeline sub-agents ⇒ env
  tokens are global to the process; a leaked token lets another agent build on
  it. Single-user workstation (§4.1) bounds the blast, but note it.
