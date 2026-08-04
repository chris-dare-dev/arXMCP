# ADR — Lean verification contract: five operations (verification-contract-m1)

**Status:** Proposed (see Owner approval record)
**Date:** 2026-08-03 · **Owner:** Chris Dare (per OWNERS.md)
**Roadmap item:** `verification-contract-m1` (plans/verification-contract/roadmap.yaml,
parent epic `verification-contract-e1`)
**Source brief:** `.claude/roadmap-briefs/R3-verification-contract.md` (P0 trust
milestone, seeded 2026-07-11)

This document defines, for each of the five operations that will eventually replace
`lean_verify`'s single-mode surface — `parse_source`, `elaborate_signature`,
`check_declaration`, `audit_axioms`, `strict_replay_proof` — its inputs, its isolation
dependency, and its target-binding behavior. **It implements none of them.** Per
`verification-contract-e1`'s scope, this milestone (m1) only renames `lean_verify`'s
`status="ok"` to `status="elaborated_no_errors"` and re-pins the affected wire-schema
hashes (see the code diff and `.claude/notes/milestones/verification-contract-m1/`); the
operations described here land in `verification-contract-e3` (blocked on `verification-
contract-e2`'s isolation boundary), per the roadmap's own `depends_on` edges.

## Context and problem statement

- `lean_verify` today is one mode with two knobs (`mode="full"` / `"syntax_only"` /
  `"tactic_step"`) that conflates four genuinely different questions: does this text parse,
  does it elaborate, does the kernel accept it, and does it match what the caller actually
  meant to prove. `.claude/docs/trust-language-policy.md` §4 names elaboration, proof
  closure, axiom audit, and checker identity as four distinct Lean-relevant trust axes;
  the roadmap's five-operation split is the mechanism chosen to make each axis independently
  queryable and independently absent-when-unmeasured, rather than folded into one status
  token (`.claude/roadmap-briefs/R3-verification-contract.md` KR1–3).
- **Note on this milestone's own rename** (recorded here per this milestone's own decision
  record, so a reader of this ADR does not need to separately reconstruct it): m1 renames
  `status="ok"` to `status="elaborated_no_errors"` but does **not** wrap `status` in a
  Certificate object (level + evidence), even though `status` is trust-bearing. Policy §6
  rule 3 requires a Certificate for a *graded* verdict; `status` is not graded — it is a
  single fact drawn from a fixed, mutually-exclusive ladder of outcomes (`error` / `sorry`
  / `incomplete` / `elaborated_no_errors`, plus the operational lane). Policy §2 itself
  names the rename below as the complete fix for this token, not a re-architecture.
  Certificate-wrapping `status` would duplicate `compilation_success` / `axiom_audit` for
  no new information. See `server/handlers/lean_verify.py`'s `_normalize_response` for the
  code-level comment carrying this same reasoning.
- Two prior-art systems were researched at source depth for this design (both fetched and
  sha256-pinned in `.claude/notes/milestones/verification-contract-m1/research/brief-2.md`):
  **AXLE** (arXiv:2606.26442) — a per-request-isolated, named-environment REPL-style
  service whose `verify_proof` trusts the loaded environment's kernel-checked provenance —
  and **SafeVerify** (github.com/GasStationManager/SafeVerify) — a batch CLI that performs
  a full `Environment.replay` before comparing compiled `.olean` files against a target.
  Their divergent designs are the direct model for why this contract needs both
  `check_declaration` (AXLE's shape) and `strict_replay_proof` (SafeVerify's shape) rather
  than one operation at two speeds — see Decision 3.
- The `leanprover-community/repl` protocol (README fetched + sha256-pinned) has exactly
  three interaction modes plus a pickling pair: `cmd` (+ optional `env`), `path` (+ optional
  `allTactics`), `tactic` (+ `proofState`), and `pickleTo`/`unpickleEnvFrom`/
  `unpickleProofStateFrom`. The roadmap brief's prose names ("file", "proofStep",
  "pickleEnvironment"/"pickleProofSnapshot") are paraphrase, not literal protocol keys —
  this document uses the real key names throughout. `lean_verify.py` already uses the
  correct literals (`cmd`, `env`, `tactic`, `proofState`), so no code is at risk from the
  brief's paraphrase; only prose citing the brief needed correcting.

## Decision 1 — `parse_source`

- **Inputs:** raw Lean 4 source text (a snippet or declaration head, not necessarily a
  complete file). No imports are resolved and no prior environment is required.
- **Isolation dependency:** depends on `verification-contract-e2`'s boundary as
  defense-in-depth, even though this operation touches no Mathlib import and loads no
  caller-supplied environment. A raw parser invocation is still Lean-adjacent code
  execution (custom notations/macros can pull parser extensions into scope), so it is not
  exempted from the isolation boundary that gates the other four operations.
- **Target-binding behavior:** none. `parse_source` answers only "is this syntactically
  well-formed Lean 4" — it has no fidelity check and cannot reject a target mismatch,
  because it never elaborates far enough to know what the candidate would resolve to.
- **Mechanism (the one architecturally distinct operation in this set):** confirmed by
  omission across the full `leanprover-community/repl` README — every documented mode
  (`cmd`, `path`, `tactic`) performs full elaboration; **none parses only**. `parse_source`
  therefore CANNOT be built as a REPL JSON round-trip at all. It needs a direct
  `Lean.Parser` invocation — a distinct Lean metaprogram of its own, not a `{"cmd": ...}`
  message to the existing REPL subprocess `lean_verify` already drives. Implying
  "the REPL, but lighter" here would repeat the exact `mode="syntax_only"` mistake the
  trust-language policy already flagged (`#check`-wrapping "reduces but does not remove
  kernel work" — `trust-language-policy.md:67-68`): there is no lighter-weight REPL mode to
  fall back to. This is also why `parse_source` is likely the last of the five operations
  to implement in `verification-contract-e3` despite being listed first in the roadmap's
  key results — every other operation reuses the REPL transport `lean_verify` already has;
  this one does not.

## Decision 2 — `elaborate_signature`

- **Inputs:** a candidate declaration signature (name, binders, expected type) plus a
  server-supplied expected signature — the target reference (an R5 registry id or an
  inline expected signature) — plus the standard optional imports / `env` continuation
  token for environment reuse (the same mechanism `lean_verify` already exposes).
- **Isolation dependency:** depends on `verification-contract-e2`. This operation performs
  a real `{"cmd": ...}` elaboration round-trip against the REPL (full elaboration, unsolved
  metavariables rejected per the roadmap's own operation description), so it needs the same
  process-isolation boundary as every other Lean-executing operation in this set.
- **Target-binding behavior:** BINDS. Per KR2, a candidate that renames, re-kinds,
  strengthens, or weakens the target signature is rejected with a specific, named error —
  this is the operation's entire reason to exist over a bare elaboration check. Binding is
  checked at the *signature* level (name, kind, type) before any proof body is considered.

## Decision 3 — `check_declaration`

- **Inputs:** a candidate declaration (signature + proof body) plus imports / `env` reuse,
  identical transport shape to `elaborate_signature`.
- **Isolation dependency:** depends on `verification-contract-e2`. Architecturally this is
  AXLE's `verify_proof` shape (§Context, above): a per-request, sandboxed-process
  elaboration that trusts the loaded environment's kernel-checked provenance rather than
  re-verifying it from scratch.
- **Target-binding behavior:** MAY bind to a target signature (reusing `elaborate_signature`'s
  binding check) but does **not** perform a full environment replay. This is a deliberate,
  named limitation, not an oversight: AXLE's own paper states, verbatim, that `verify_proof`
  "does not re-verify the environment from scratch and hence does not defend against inputs
  that use LEAN metaprogramming to install unchecked declarations directly into the
  environment and make invalid proofs appear valid" (§4.1). `check_declaration` inherits
  this exact gap by design — it trades soundness for speed (AXLE's own measurement: median
  0.97s for `verify_proof` vs 10.1s for SafeVerify's full-replay path on the same corpus).
  **This is precisely why `strict_replay_proof` exists as a separate operation, not a slower
  mode of this one** — see Decision 5.

## Decision 4 — `audit_axioms`

- **Inputs:** the fully-qualified name(s) of one or more declarations already elaborated in
  a live environment — typically chained immediately after `check_declaration` or
  `elaborate_signature` within the same `env` token, exactly as `lean_verify`'s existing
  `_attach_axiom_audit` second round-trip already does today for the shipped `axiom_audit`
  axis (`server/handlers/lean_verify.py:1077-1148` — issues #205/#281/#332).
- **Isolation dependency:** depends on `verification-contract-e2`, and runs inside the SAME
  isolated environment as the preceding operation (a second `{"cmd": "#print axioms
  <name>"}` round-trip against the already-loaded environment, not a fresh process).
- **Target-binding behavior:** none. `audit_axioms` compares the transitive axiom closure
  Lean reports (`Lean.collectAxioms`, per the official Lean docs — the exact primitive the
  shipped `axiom_audit` axis already drives) against the fixed allowlist (`propext`,
  `Quot.sound`, `Classical.choice`), never against a target signature. This is the
  transitive-closure-plus-allowlist-verdict OPERATION the roadmap names (KR3); it is
  distinct from, and will eventually supersede as the primary route to, the `axiom_audit`
  *axis* already shipped inside `lean_verify`'s single-mode response — the roadmap's own
  evidence block is explicit that shipping the axis "PARTIALLY closes" the founding defect
  and that "the five-operation split... remains unbuilt" (`plans/verification-contract/
  roadmap.yaml:42`).
- **Documentation-staleness hazard (not a code defect — recorded for whoever next touches
  this operation's schema prose):** Lean 4.29.0 (RFC #12216, confirmed in the fetched
  release notes) replaced the single `Lean.trustCompiler` axiom with one auto-generated
  axiom per native computation (names containing `._native.bv_decide.`). The repo's pinned
  toolchain, `v4.30.0-rc2`, postdates this change, so `Lean.trustCompiler` is very unlikely
  to appear literally going forward. The allowlist-based verdict logic is unaffected —
  anything outside the 3-axiom allowlist is flagged regardless of its exact name — but
  `server/schemas/lean_verify_result.json`'s `disallowed_axioms` description still names
  `Lean.ofReduceBool`/`Lean.trustCompiler` "by literal name" as notable members; that prose
  will read as stale once `native_decide` axioms start surfacing under their new names.
  Separately, `Lean.collectAxioms` (hence `#print axioms`) had a known transitivity bug
  (`leanprover/lean4#8840`, fixed by `#8842`, shipped in Lean 4.23.0) that could under-report
  axioms reachable only through another axiom; the pinned toolchain postdates the fix.

## Decision 5 — `strict_replay_proof`

- **Inputs:** the candidate's compiled artifact (or an elaboration environment ready to be
  compiled) plus the target's own compiled artifact (or an equivalent re-derivable expected
  signature) — the SafeVerify pattern: a fresh, independent checker comparing two `.olean`
  files for exact target/signature equality.
- **Isolation dependency:** depends on `verification-contract-e2`, but — unlike
  `check_declaration` — runs in a SEPARATE, freshly-spawned isolated process rather than
  reusing a warm `env` token. This is structural, not incidental: a full
  `Environment.replay` re-checks every declaration with the kernel from scratch (SafeVerify's
  own README: "the same check as what `lean4checker` performs"), which is meaningless if run
  against an environment the candidate itself may have tampered with via metaprogramming.
- **Target-binding behavior:** the STRICTEST of the five operations. Per SafeVerify's own
  named failure taxonomy (independently confirmed at source): declaration-kind mismatch
  (`theorem` → `def`), type/signature mismatch (a weakened or restated theorem), body-value
  mismatch (except where the target's own body depends on `sorry` — the intended "fill this
  stub" case), disallowed-axiom dependency, and `partial`/`unsafe` rejection. This is the
  operation that closes the gap `check_declaration` deliberately leaves open (Decision 3):
  a metaprogramming-installed unchecked declaration that fooled `check_declaration`'s
  trust-the-environment shortcut is caught here by the full replay, because replay
  re-derives every declaration's validity from the kernel rather than trusting what was
  already loaded.
- **This trade-off is the single most important design fact in this document.** If a future
  implementer reads `check_declaration` and `strict_replay_proof` as "the same check, twice,
  for redundancy" rather than as two different, deliberately non-overlapping soundness
  guarantees, they could reasonably conclude `check_declaration` alone is sufficient and skip
  building the slower operation — silently re-opening the exact metaprogramming-tampering gap
  AXLE names as its own accepted limitation and R3's brief names as a P0 concern.
- **Mechanism — decided here, per this ADR's remit to resolve open questions rather than
  leave them all to a later milestone:** `strict_replay_proof`'s mechanism CLASS is
  committed now — a full, independent `Environment.replay` from scratch, never a
  trust-the-loaded-environment shortcut. The concrete TOOL that performs it (SafeVerify's
  CLI wrapper vs a bespoke fresh-process re-elaboration-plus-axiom-audit fallback) is
  explicitly NOT decided here and is deferred to `verification-contract-spike-2`
  (`plans/verification-contract/roadmap.yaml:216-228`), because SafeVerify's four published
  backport branches (Lean 4.9.0 / 4.14.0 / 4.15.0 / 4.20.0) do not include a branch matching
  the repo's pinned reference toolchain (`v4.30.0-rc2`). This ADR does not assume SafeVerify
  "just works" against that toolchain; `verification-contract-e3`/`m3` (which depends on
  `spike-2`, not on this milestone) is where that confirmation happens.

## Decision 6 — checker identity is a resource, not a sixth operation

`.claude/docs/trust-language-policy.md` §4 names four Lean-relevant trust axes: elaboration,
proof closure, axiom audit, and checker identity (which checker, in which named, immutable
environment, at what policy version). The five operations above cleanly cover the first
three (`elaborate_signature` ≈ elaboration; `check_declaration`/`strict_replay_proof` ≈ proof
closure at two different soundness levels; `audit_axioms` ≈ axiom audit). **No sixth
operation is added for checker identity.** That axis is served by the `arxmcp://lean-env`
manifest resource (`verification-contract-e5`/m5, KR6: toolchain, commits, lake manifest
hash, import universe, checker + policy versions, and environment digest per named
environment) — a resource a caller reads alongside an operation's result, not a verdict an
operation computes per call. Recording this explicitly here closes the axis rather than
leaving it silently unaddressed by anything in this document.

## Consequences

- **Good:** every one of the four Lean-relevant trust axes from `trust-language-policy.md`
  §4 now has a named home (one of the five operations, or the `arxmcp://lean-env` resource)
  before any operation is implemented, so `verification-contract-e3` has a reviewable
  contract to build against rather than inventing shape as it goes. The
  `check_declaration`/`strict_replay_proof` split is recorded as a deliberate,
  non-collapsible soundness distinction, closing the single riskiest misreading this
  document could otherwise invite.
- **Bad / accepted costs:** `parse_source` needs a wholly separate implementation path (a
  direct `Lean.Parser` metaprogram) from the other four, which reuse the existing REPL
  transport — this is real, non-amortizable extra engineering surface for `e3`, not just
  documentation debt. `strict_replay_proof`'s concrete tool is still unresolved pending
  `spike-2`, so `e3`'s own estimate carries that uncertainty forward.
- **Deliberately NOT decided here:**
  - Which Windows isolation route (Job Object + restricted token vs container/WSL2) —
    `verification-contract-spike-1`/m2's ADR, not this one.
  - Which concrete tool implements `strict_replay_proof` (SafeVerify vs a bespoke
    fresh-process fallback) — `verification-contract-spike-2`, explicitly (Decision 5).
  - Any code implementing any of the five operations — forbidden by this milestone's own
    acceptance criterion 4; `e3` implements against this document, not the other way round.
  - The R5 formal-target-registry's own shape (how a "server-side target reference" is
    minted/stored) — referenced here only as a consumer of `elaborate_signature`'s and
    `strict_replay_proof`'s binding behavior.
- **Known ambient hazards recorded for the next session:**
  - `server/schemas/lean_verify_result.json`'s `disallowed_axioms` description names
    `Lean.ofReduceBool`/`Lean.trustCompiler` by literal name as "notable members"; on the
    pinned `v4.30.0-rc2` toolchain (which postdates Lean 4.29.0's RFC #12216 axiom-naming
    change) that literal name is unlikely to appear again — see Decision 4's documentation-
    staleness note. No code fix is needed (the allowlist logic is name-agnostic); the prose
    will need a future touch.
  - SafeVerify has no published branch matching the pinned toolchain — `spike-2` owns
    resolving this before `m3` can complete `strict_replay_proof`.
  - `Lean.collectAxioms`'s pre-4.23.0 transitivity bug (`leanprover/lean4#8840`) is fixed on
    the pinned toolchain, but any future toolchain downgrade would need this re-checked.

## Owner approval record

**Pending.** No interactive owner round-trip has run for this document as of the date
above — unlike `adr-data-plane-boundary.md`'s Accepted precedent, this milestone's brief
did not schedule one, and the trust gate this ADR designs toward has not itself run
(`verification-contract-e2`–`e5` are all unbuilt). Asserting `Status: Accepted` here would
claim an approval that did not happen. This ADR ships as `Proposed`; the five-operation
design becomes binding for `verification-contract-e3` only once the owner reviews and this
section is updated with a dated approval record, matching the convention set by
`adr-data-plane-boundary.md`.
