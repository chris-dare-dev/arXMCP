# Implement synthesis — desktop-distribution-m3

## Built

- **AC1 — supported desktop boundary:** `apps/desktop/README.md:9` names
  macOS 14+ Apple Silicon as the first release target of one shared workspace,
  explains why it is a target rather than a fork, and keeps Linux/Windows
  portability honest. `apps/desktop/README.md:28` gives the exact locked Rust,
  focused Python, wheel, and repository development commands and states the
  no-Node/npm boundary.
- **AC2 — versioned compatibility:**
  `apps/desktop/crates/desktop-contract/src/lib.rs:251` and
  `server/desktop_contract.py:189` independently enforce bounded,
  duplicate-free canonical NDJSON, reject unsupported majors before typed
  frame validation, reject unknown core fields, validate loopback/paths/URLs,
  and accept same-major additions only under namespaced `extensions`.
- **AC3 — secret-safe launch:**
  `apps/desktop/crates/desktop-contract/src/lib.rs:64` and
  `server/desktop_contract.py:43` wrap 32-byte OS-random capabilities in
  redacted types. The sidecar accepts no argv configuration, reads capabilities
  only from retained stdin/readiness headers, never emits them in `bound`, and
  writes only static diagnostics. `tests/test_desktop_contract.py:218` and
  `tests/test_desktop_contract.py:274` scan repr/errors, control output, argv,
  environment, URLs, stderr logs, and runtime artifacts for a live canary.
- **AC4 — fixture sidecar:**
  `apps/desktop/crates/fixture-sidecar/src/main.rs:59` validates launch before
  side effects, retains a kernel-selected `127.0.0.1:0` listener, derives the
  manifest URLs, authenticates readiness/shutdown, ignores an invalid shutdown
  capability, and exits on valid shutdown or stdin EOF. It has no Python,
  model, corpus, LanceDB, or MCP-server dependency.
- **AC5 — cross-language stable fixtures:**
  `apps/desktop/contract-fixtures/` contains canonical launch/bound/shutdown,
  compatible-minor Unicode, incompatible-major, duplicate/unknown-field,
  wildcard, URL-mismatch, and 4,097-byte rejection cases plus a pinned
  aggregate digest. Rust tests and `tests/test_desktop_contract.py:150`
  independently parse and re-emit the same positive bytes and verify the same
  digest.

## Branching note

Implementation landed directly on `main`, as required by `CLAUDE.md` section
4.1 for this single-user repository. The orchestrator-provided base remained
`d6b7d69100d2cf3d8bbe0c85f85e569bf13228fe` throughout implementation.

## Files touched

- `.gitignore` — ignore local Cargo target output for the desktop workspace.
- `apps/desktop/Cargo.toml` / `Cargo.lock` — pinned, build-chain-free Rust
  workspace and reproducible dependency graph.
- `apps/desktop/README.md` — platform, protocol, secret, fixture, and command
  boundaries.
- `apps/desktop/contract-fixtures/*` — shared positive/negative golden NDJSON
  and aggregate digest.
- `apps/desktop/crates/desktop-contract/` — Rust frame types, parser,
  canonicalizer, validators, token wrapper, state machine, and fixture tests.
- `apps/desktop/crates/fixture-sidecar/` — lightweight loopback lifecycle
  fixture and authenticated probes/control.
- `server/desktop_contract.py` — dependency-light Python mirror included in
  the production wheel for the M4 adapter.
- `tests/test_desktop_contract.py` — Python conformance, security, framing,
  digest, and live sidecar lifecycle coverage.
- `tools/wheel_install_check.py` — require the Python contract module in both
  built and installed wheel contents.
- `.claude/notes/milestones/desktop-distribution-m3/implement/scope-exceeded.md`
  — record the owner-authorized large-diff checkpoint.
- `.claude/notes/milestones/desktop-distribution-m3/implement/synthesis.md` —
  this implementation record.

## Deferred

- M4 still owns production Python-server port-zero adoption, authenticated
  `/readyz`, the real stdin control actor, Tauri lifecycle ownership, ordinary
  app-exit handling, bounded platform process termination, and MCP smoke.
- No Tauri shell, frozen runtime, signing/notarization, model, corpus, or Node
  build chain was added. The historical spike remains unchanged.
- `make wheel-check-full` is the pre-publish dependency-complete boot gate and
  was not applicable: this milestone changed neither `pyproject.toml` nor the
  dependency set. The required fast wheel build/install gate passed and now
  explicitly asserts `server/desktop_contract.py`.

## external_writes_required

- `git push origin main` — Phase 4 only; not performed here.

## Test deltas

- `apps/desktop/crates/desktop-contract/tests/contract.rs` — 8 Rust tests for
  canonical bytes, aggregate digest, version compatibility, duplicate/unknown
  fields, framing bounds, secret redaction, and sequence validation.
- `tests/test_desktop_contract.py` — 22 enabled tests covering the same shared
  fixtures plus real loopback health/readiness, invalid and valid shutdown,
  stdin-EOF cleanup, argv refusal, pre-bind launch rejection, and secret scans.

## Check gate results

- `cargo fmt --all --manifest-path apps/desktop/Cargo.toml -- --check`: **PASS**.
- `cargo test --locked --offline --manifest-path apps/desktop/Cargo.toml
  --target-dir /private/tmp/arxmcp-desktop-m3-gate`: **PASS** (8 tests).
- `cargo clippy --locked --offline --manifest-path apps/desktop/Cargo.toml
  --target-dir /private/tmp/arxmcp-desktop-m3-gate --workspace --all-targets
  --all-features -- -D warnings`: **PASS**.
- Locked fixture build plus `ARXMCP_FIXTURE_SIDECAR=... .venv/bin/python -m
  pytest tests/test_desktop_contract.py -q --tb=short`: **PASS** (22 tests).
  The managed sandbox denied the first loopback bind; the exact permitted local
  rerun passed without changing code or tests.
- `.venv/bin/python -m ruff check server/desktop_contract.py
  tests/test_desktop_contract.py tools/wheel_install_check.py`: **PASS**.
- `make wheel-check PYTHON=.venv/bin/python`: **PASS** (191 wheel entries, 24
  required files present in both wheel and clean install).
- `make test PYTHON=.venv/bin/python`: **PASS** (Ruff clean; 5,051 passed, 47
  skipped, 1 xfailed, 83 warnings in 311.91 seconds).
- MCP tool-schema and BP1/BP2 prompt files versus the implementation base:
  **UNCHANGED**; no schema/hash re-pin warranted.
- Post-commit `git status --porcelain`: clean except the explicitly permitted,
  orchestrator-owned `desktop-distribution-m3/state.json` transition file.
