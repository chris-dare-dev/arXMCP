# Implementer plan — desktop-distribution-m6

- **What:** fault matrix through the REAL supervisor (`lifecycle.rs`/`main.rs`)
  against fault-injected fixture-sidecar arms selected via the namespaced
  `org.arxmcp.test-fault` `launch.extensions` key (test-only `Plan.test_fault`
  plus `Plan.test_bound_timeout_ms` / `test_shutdown_grace_ms` /
  `test_shutdown_force_after_ms` supervisor-budget overrides — the wire frame
  stays contract-valid at `MIN_GRACE_MS`); `redact::scrub` wired to a real
  persist site (`bound-frame-invalid` scrubbed frame prefix) with a shared
  `contract-fixtures/redaction-vectors.jsonl` consumed by both languages;
  30-cycle stress with 30 distinct PIDs + self-asserting `ps`/`lsof` audits;
  socket-level loopback probe (LAN connect must refuse; `lsof` NAME column
  structural check); real-server bare-stdin-EOF fault case (zero new
  `server/desktop_child.py` lines); non-claims recorded in tests + README.
- **Files:** `apps/desktop/crates/supervisor/src/{main,lifecycle,redact}.rs`,
  `apps/desktop/crates/fixture-sidecar/{Cargo.toml,src/main.rs}`,
  `apps/desktop/contract-fixtures/{redaction-vectors.jsonl,fixtures.sha256}`,
  `tests/test_desktop_contract.py`, `tests/test_desktop_child.py`,
  `apps/desktop/README.md`, `CLAUDE.md`. NOT touched: `server/*.py` named in
  the invariants (desktop_child, config, main, middleware, tools, prompts).
- **Check commands:** `cargo fmt --check`, `cargo clippy -D warnings`,
  `make desktop-conformance PYTHON=.venv/bin/python`,
  `make test PYTHON=.venv/bin/python`, plus the m5 H3 guard re-check.
- **Delivery actions expected (modeled later, not authorization):**
  `git push origin main`; `Fixes #397` rides the FINAL milestone commit
  (orchestrator-owned, not any implementation commit here).
- **Deviations from the brief:** (1) bound-timeout override is a Plan field,
  not an env var — one test-knob surface, nothing new to scrub; (2) the
  grace/force shrink CANNOT ride the wire frame (contract floor
  `MIN_GRACE_MS=35_000` rejects it) so it overrides only the supervisor's
  local `ChildControl` budgets; (3) a sixth fixture arm `never-ready` creates
  the stable post-bound window the supervisor-SIGKILL test needs (the normal
  fixture cycle fails at the MCP smoke sub-second); (4) `redact::scrub` is
  built (brief left it conditional) because the malformed-bound diagnostic is
  a real raw-capture persist site that the fault matrix then exercises
  end-to-end; (5) the Python half of the redaction vectors is a test-level
  reference (exact-match replace) — no production Python substring scrubber
  exists and inventing one would be dead code.
