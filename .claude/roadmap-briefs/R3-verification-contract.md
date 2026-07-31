# R3 — verification-contract

Phase 0–1. Depends on: R0 (trust vocabulary). Blocks: R4 (certificates), R5 (attestations),
any warm-pool/caching work. This is the P0 trust milestone: the current surface can be made
to say "ok" to an `axiom`-backed proof.

## Brief (seed for /roadmap)

`lean_verify` is a useful feedback hook and an unsound trust surface. Verified at source
(2026-07-11): the handler maps "no error messages and no sorries" to `status: "ok"`
(`server/handlers/lean_verify.py:290-298`) with no comparison of the candidate against an
expected target signature, no rejection of target replacement or declaration-kind changes,
no transitive axiom enumeration (a bare `axiom h : False` passes silently and poisons
everything after it), no unsafe/metaprogramming policy, and no independent replay;
`syntax_only` is not syntax-only — terms are `#check`-wrapped (full elaboration) and
declarations run under a 5,000-heartbeat cap that reduces but does not remove kernel work
(`lean_verify.py:367-396`; mitigating: the handler already returns
`compilation_success=null` for syntax_only passes). The live environment is a core-only REPL
that cannot import Mathlib or BridgelandStability (verification spike: "No mathlib build was
required"), the flag defaults off, and on Windows the only resource control is the 30 s
wall-clock (`server/lean_repl.py` — RLIMIT path is POSIX-only; the repo's own sandbox
design doc names filesystem/memory/FFI/network as open risks). This initiative replaces the
single mode with an honest five-operation contract — `parse_source` (parser only),
`elaborate_signature` (server-supplied expected signature; unsolved metavariables rejected),
`check_declaration` (isolated environment compile), `audit_axioms` (transitive closure vs
the allowlist propext / Quot.sound / Classical.choice), `strict_replay_proof` (fresh
independent checker; exact target/signature equality; SafeVerify-pattern) — behind real OS
isolation on Windows (Job Object + restricted token, or container/WSL2 boundary: read-only
environment, per-call scratch, no network, CPU/memory/process/file-size limits, teardown on
violation), validated by an adversarial attack suite whose required false-accept rate is
zero. It adds named immutable environments (core; mathlib@commit; bridgeland-anchor@commit)
with an `arxmcp://lean-env` manifest resource and a reproducible build smoke, and — only
after the gates — content-addressed result caching keyed on (candidate hash, target hash,
ordered imports, environment digest, checker + trust-policy version, compiler options,
resource policy), with positive strict results durable and timeouts/memory failures cached
briefly or not at all. Warm pooled workers with REPL incremental state reuse come last,
inside the same boundary. Until the contract lands, trust-bearing labels are disabled:
`status: "ok"` is renamed to what it is (`elaborated_no_errors`), and the trust-language
policy ([`.claude/docs/trust-language-policy.md`](../docs/trust-language-policy.md)) governs the response schema. Existing prior art is adopted, not rebuilt: SafeVerify
for kernel-bypass patterns, AXLE's per-request environment selection as the shape of named
envs, Kimina/Poiroux pooling + state reuse (~8 s → ~0.02 s Mathlib-import round-trips) for
the performance tail.

## HMW / Objective

- **HMW:** How might we make every Lean-derived signal arXMCP serves impossible to
  misread — parse vs elaborate vs check vs axiom-audited vs strictly-replayed, in a named
  immutable environment, under real isolation — before any formal artifact ships?
- **Objective:** Ship the five-operation contract, the isolation boundary, the attack
  suite at zero false accepts, named environments with manifests, then caching and pools.

## Key results

1. The MCP surface exposes the five operations (naming/registration batched into W1;
   `lean_verify` kept as a deprecated alias returning the honest renamed statuses).
2. `elaborate_signature` and `strict_replay_proof` take a server-side target reference
   (R5 registry id or inline expected signature); candidate declarations that rename,
   re-kind, strengthen, or weaken the target are rejected with a specific error.
3. `audit_axioms` returns the exact transitive axiom set and an allowlist verdict; any
   non-allowlisted axiom, `unsafe`/`partial` declaration, or environment-mutating
   construct fails the trust verdict.
4. The adversarial suite runs in CI-equivalent local gating with **zero false accepts**:
   sorry; custom axiom (direct + via import); target replacement; kind change;
   strengthening/weakening; `unsafe`; metaprogramming/IO/filesystem attempts;
   `native_decide` under a policy that forbids it; declaration shadowing; cross-request
   leakage probes; heartbeat/memory/fork bombs (fail closed as resource errors, never as
   acceptance).
5. Untrusted Lean executes inside an OS boundary on Windows: no network, read-only
   toolchain/env, writable per-call scratch only, memory + CPU + wall + process caps,
   kill-and-teardown on violation; the corpus and user home are unreachable. The boundary
   choice (Job Object + restricted token vs container/WSL2) is spiked and recorded as an
   ADR with measured overhead.
6. Named environments exist with reproducible builds: `core@<lean-ver>`,
   `mathlib@<commit>`, `bridgeland-anchor@<commit>` (pin per R5's audit); the
   `arxmcp://lean-env` resource returns toolchain, commits, lake manifest hash, import
   universe, checker + policy versions, and environment digest; a build-smoke script
   reproduces each digest from scratch.
7. Result cache: content-addressed on the full key; hit/miss metrics on `/metrics`;
   positive strict results durable across restarts; timeout/memory outcomes TTL ≤ 1h.
8. Pooled warm workers (per named environment) with incremental state reuse; measured
   latency report (target: repeat-verification p50 < 1 s in mathlib env) — explicitly the
   last milestone, gated on 4–5. Bounds the live environment-snapshot tree (inherited F7,
   below): the REPL exposes no per-env eviction, so pooled workers are **recycled** on a
   live-snapshot-count / age budget (optionally `pickle`-migrating the hot named env across
   a recycle), consuming the REPL live-snapshot / worker-age gauge that ships standalone
   ahead of this gate (`lean-repl-observability-m1`; see Inherited findings).

## Scope — out (wont)

- No proving, no tactic search, no premise selection (compose with LeanExplore/LeanSearch
  externally; R7 adapters).
- No claim that kernel acceptance = paper fidelity (that axis belongs to R5's human
  review dimension).
- No multi-user tenancy; loopback-only stands.
- No Mathlib ingestion.

## Assumptions (tiered)

- **must** — A Windows isolation boundary with the required properties is achievable with
  acceptable overhead (Job Objects + restricted token, or Docker/WSL2 which
  scale-ops-hardening already plans for MinerU). *Validation:* a 3-day spike measures both
  routes on the attack suite's resource cases; if neither meets the bar, Lean stays
  disabled-by-default and R5 targets are checked in a manual operator workflow (documented
  fallback), not served live.
- **must** — A strict independent replay path exists for the pinned toolchain (SafeVerify
  supports version branches; fallback: fresh-environment re-elaboration with axiom audit
  in a second process). *Validation:* replay catches 100% of the suite's kernel-bypass
  cases; if SafeVerify lacks the pinned version, the fallback is measured against the same
  suite before acceptance.
- **should** — mathlib@pinned-commit builds reproducibly on this workstation (disk/RAM
  budget ~tens of GB / ≥16 GB). *Validation:* build smoke with `lake exe cache get` timed
  and recorded in the env manifest doc.
- **should** — Incremental state reuse (REPL prefix caching) composes with the isolation
  boundary without cross-request leakage. *Validation:* leakage probes run against the
  pooled configuration specifically; failure keeps pools per-request-fresh (slower,
  safe).

## Evidence (verified 2026-07-11)

- `server/handlers/lean_verify.py:290-298` (ok = no errors/no sorries), `:367-396`
  (`#check` wrapping; heartbeat cap), `:304-307` (existing honest null for syntax_only —
  the seed of the renamed statuses).
- `server/lean_repl.py` (Windows: no preexec resource caps; timeout-only; stderr to
  DEVNULL; kill+respawn on timeout — keep).
- `.claude/notes/spikes/verification-feedback-spike-2.md` (core-only REPL; "No mathlib
  build was required"; sub-second round-trips).
- `.claude/docs/lean-sandbox-design.md` (self-documented open risks: elaboration is
  Turing-complete; FS/memory/FFI/network).
- SafeVerify (github.com/GasStationManager/SafeVerify); AXLE (arXiv:2606.26442) named-env
  + strict-check shape; Poiroux REPL state reuse (~8 s → ~0.02 s) and Kimina pooling
  (arXiv:2504.21230) for the performance tail.

## Inherited findings

- **F7 — unbounded environment-snapshot growth** (from the `lean-verify-continuation-m1`
  adversary critique; deferred there, owned here). The `leanprover-community/repl` records
  every command's environment as an immutable snapshot in an **append-only array** (env id
  = array index) and exposes **no** eviction command — the surface is
  `cmd`/`file`/`proofStep`/`pickleEnvironment`/`unpickleEnvironment`/`pickleProofSnapshot`/
  `unpickleProofSnapshot` only, verified against the pinned `v4.30.0-rc2` source
  (`~/lean-repl-spike/repl/REPL/Main.lean`, census 2026-07-25). Even a `#check` grows the
  tree; only a respawn/restart frees it (~3.1 GB RSS for a Mathlib-resident process). This
  track's env-reuse continuation tokens make the growth first-class. **Owned by m7** (KR8):
  bound the live tree by recycling pooled workers on a snapshot-count / age budget
  (per-env eviction is not available; `pickleEnvironment`→`unpickle` can migrate the hot
  named env across a recycle), and consume the live-snapshot / worker-age gauge on `/metrics`.
  That observability gauge is now scoped as a **standalone, independently-schedulable
  milestone** — `lean-repl-observability-m1`
  ([`.claude/roadmap/lean-repl-observability.md`](../../.claude/roadmap/lean-repl-observability.md)) — pullable
  *ahead* of the trust gate because read-only telemetry changes no REPL lifecycle; m7
  consumes/extends it and retains only the env-tree *bounding* (recycling + pickle-migration).
  A respawn *policy* must NOT live in the `lean_verify` handler — a respawn mints a new
  REPL generation that expires every outstanding continuation token, so bolting it on would
  silently destroy the warm envs the tokens depend on; it is pooled-worker-lifecycle logic.
  Gated behind the trust gate like the rest of m6–m7. **Interim (pre-m7):** off-by-default
  + opt-in reuse + single-user + operator restart; growth model + operator mitigation in
  [`.claude/docs/lean-sandbox-design.md`](../docs/lean-sandbox-design.md)
  § "Environment-snapshot accumulation (F7)".

## Milestone sketch

1. **m1 — honest statuses + contract design** (S): rename, response-schema redesign per
   R0 policy, ADR for the five operations; W1 coordination.
2. **m2 — isolation spike + ADR** (M): Job Object vs container measured; boundary lands.
3. **m3 — five operations + target binding + axiom audit** (L).
4. **m4 — attack suite** (M): fixtures + gating; zero-false-accept report committed.
5. **m5 — named environments + manifests + build smoke** (M): incl. bridgeland-anchor
   pin from R5's audit (cross-track handshake).
6. **m6 — result cache** (S→M). **m7 — pools + state reuse + latency report + env-tree
   bounding** (M): incl. the inherited-F7 live-snapshot bound — worker recycling (the
   `/metrics` gauge ships standalone as `lean-repl-observability-m1`, ahead of the gate);
   see the F7 note under "Inherited findings".

## Gates

- **Trust gate (blocks R4/R5 shipping):** m2–m5 complete; attack suite zero false
  accepts; every response carries environment digest + checker/policy version, and the
  response schema conforms to the trust-language policy
  ([`.claude/docs/trust-language-policy.md`](../docs/trust-language-policy.md)).
- **Performance work (m6–m7) is forbidden before the trust gate** — pooling an unsound
  verifier scales the blast radius.
