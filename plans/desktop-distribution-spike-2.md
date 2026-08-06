### desktop-distribution-spike-2 — Prove one application-data root

**Question.** Can every installed-runtime write be routed below one explicit
application-data root without breaking source, wheel, Docker/Compose, or test
behavior?

**Description.** Time-box the work to inventory and prototype only. Inventory
all runtime writes, exercise one typed `ARXMCP_DATA_DIR` resolver across source,
wheel, and container fixtures, and record the compatibility and migration
decisions required before `desktop-distribution-m1` implementation begins.

**Acceptance criteria.**
- [ ] Inventory runtime writes and defaults across `server/`, `ingest/`, `tools/`, `shim/`, and `ops/`, distinguishing installed runtime from developer/ingest-only paths.
- [ ] Prototype a typed path resolver rooted at `ARXMCP_DATA_DIR` against source, wheel, and container fixtures.
- [ ] Verify containment for relative/absolute roots, symlinks, whitespace, Unicode, and read-only application locations.
- [ ] Record compatibility aliases, migration order, and the exact call sites that remain.
- [ ] Produce an ADR with GO/NO-GO and fallback.

**Dependencies.** None.

**Complexity.** S — spike, ≤ 3 days; inventory and prototype only.

**GitHub.** [#385](https://github.com/chris-dare-dev/arXMCP/issues/385),
materialized from the issue body on 2026-08-06.
