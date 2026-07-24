# lean-verify-continuation-m1 — Implementation summary

**Status:** implement-complete; critique running. Base `6ade74e`, inline on main.

## What shipped

Threaded the leanprover-community/repl **env** and **proofState** continuation
ids through the `lean_verify` MCP tool as opaque, generation-guarded tokens,
plus a new `tactic_step` mode. Closes the two blockers from the Mathlib-env
findings (30 s timeout vs slow import; no incremental stepping) and fixes a
latent **fail-open** bug found during research.

### server/lean_repl.py
- `LeanRepl` gains a per-spawn `generation` (random `secrets.token_hex(8)`,
  auto-assigned in `__init__` so the fake-construction test needs no change) +
  a `generation` property. This is the token namespace that makes a
  post-respawn stale id un-reusable.

### server/handlers/lean_verify.py
- **Token codec** `_encode_token` / `_decode_token` (`"{generation}:{int}"`,
  `rpartition`), `_continuation_reject_message`.
- **Input**: `env: str|None`, `proof_state: str|None`, `mode` gains
  `tactic_step`. Fail-closed decode BEFORE any REPL round-trip: expired
  (generation mismatch) / malformed → `_invalid_continuation_envelope`
  (`status=invalid-input`, `compilation_success=false`), REPL never queried.
- **`_normalize_response` now dispatches THREE response shapes**, checking the
  fail-open one FIRST:
  1. `{"message": ...}` (unknown-id) → invalid-input (the primary fix — this
     shape previously normalized to `status:ok`).
  2. `tactic_step` → `_normalize_tactic_step` (goals→goals_remaining,
     proofState→proof_state_id token, Completed→ok / goals-remain→incomplete /
     tactic-error→error; **compilation_success ALWAYS null** — a tactic step is
     not a declaration kernel check).
  3. cmd → as before, PLUS surfaces the `env` token + per-sorry
     `proof_state_id` + top-level `proof_state_id` (first sorry).
- **Output** (all four+ envelope builders emit them): `env`, `proof_state_id`,
  `continuation_status` (not-applicable / resumed / expired / unknown-id /
  malformed). `status` enum gains `incomplete` + `invalid-input`.

### Schema + cascade
- `lean_verify_result.json` v19→v20: new props + enum values + 3 fields added
  to `required` (mirroring the always-emitted `proof_state` precedent).
- `TOOL_SCHEMA_VERSION` 19→20; `search_papers_result.json` version+$id bumped
  (global tracker); `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned via
  `--update-tool-schema-hash` (→ `d9b9ade2…`); `EXPECTED_BP1_SHA256` re-pinned
  by hand (→ `4676fa03…`, LEAN_VERIFY.description edited); hardcoded
  `test_handlers_lean_verify.py` version assert → 20.

### Tests (+~30)
- Codec unit tests; env-reuse (forward + token round-trip); **fail-closed**
  (expired / malformed / unknown-id — the fail-open guard); tactic_step
  (completed/incomplete/error/missing-ps/expired); mode cross-wiring; schema
  conformance for the new shapes. Real-REPL integration (core Lean, no Mathlib
  import): env reuse carries a def across calls, tactic_step closes a sorry,
  expired + unknown-id fail closed end-to-end.

## Verification so far
- lint clean; `tests/test_handlers_lean_verify.py` + the full version/hash
  cascade suites (test_server_tool_schema, test_prompts, test_search_filter,
  test_snippet_contract, test_bootstrap_mode, test_mcp_resources,
  test_mcp_instructions, test_corpus_manifest, test_tools_all, test_lean_repl)
  green.
- Real-REPL integration (ARXMCP_ENABLE_LEAN=true against the Mathlib env): 7
  passed / 1 POSIX-skip — incl. the fail-open guard end to end.
- Full `make test` + adversary critique: IN PROGRESS.

## Known design positions (for the critique to stress)
- tactic_step `status:ok` + `compilation_success:null` = "goals discharged at
  this state", NOT declaration verified — documented; re-verify in `full`.
- Env reuse inherits the parent env's axioms; until R3 `audit_axioms`, reuse
  cannot certify a base env (documented in field descriptions).
- One REPL shared across pipeline sub-agents; env immutability prevents
  mutation leakage, but a shared/leaked token lets a caller build on another's
  env. Single-user workstation (§4.1) bounds the blast.
