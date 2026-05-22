# Critique — E14_Tier5plus (merged)

**Critics fired:** adversary (1) + infra-safety (1; conditional fired
because `infra/observability/*` matches the infra regex). oss-scout
did NOT fire (opt-in only, not requested).

**Verdict:** SHIP-WITH-FIXES (both critics).

## Findings summary

| ID | Sev | Source | Title | Phase-4 status |
|---|---|---|---|---|
| F1 | HIGH | adversary | Langfuse doc self-contradicts on Mcp-Session-Id emission; synthesis A4 was wrong | CLOSED — rewrote the Session-ID section to accurately describe MCP-library-emitted header (per shim/arxmcp_shim.py:150 evidence). Test asserts the wrong "does NOT emit" phrase is absent and the corrected per-spec wording is present |
| F2 | HIGH | adversary | Spend module orphaned at runtime; `arxmcp_api_spend_usd_total` never registers with REGISTRY | CLOSED — added side-effect import of `spend_constants` in `server/observability/__init__.py`. Regression test imports `server.observability` (production-path import) and asserts the metric is reachable via `REGISTRY.get_sample_value` |
| F3 | HIGH | adversary | `LAST_VERIFIED` staleness guard docstring claimed; no such test existed | CLOSED — implemented `test_last_verified_within_six_months` (180-day bound; opt-out via `ARXMCP_SKIP_STALENESS_CHECK=1`). Updated module docstring to point at the real test |
| F4 | HIGH | adversary | Langfuse snippet hardcoded `claude-sonnet-4-5` (wrong: real is 4-6; also SSoT anti-pattern) | CLOSED — removed the default literal entirely; `model` parameter is now required and the docstring directs callers to `server/orchestrator/model_selector.py`. Regression test fails on any `claude-XXX` literal in the snippet |
| F5 | MEDIUM | adversary | 2 new runbooks (+ pre-existing latexml-drift-runbook) hardcode `/Users/chris.dare/Library/Python/3.9/bin/uv` | CLOSED — replaced with `uv run python` in all 3 files. Regression test `test_no_user_path_hardcoded_in_ops_docs` walks `docs/ops/*.md` and fails on any `/Users/<name>/` match |
| F6 | MEDIUM | adversary | corpus-rollback.md references non-existent `/healthz/version` endpoint | CLOSED — replaced with `cat var/arxmcp/corpus-version.json` (the actual source-of-truth file). Regression test `test_runbook_curl_endpoints_all_exist` extracts every `curl http://127.0.0.1:7733/...` reference and asserts each path is in the registered endpoint allowlist |
| F7 | MEDIUM | adversary | Anchor link UX: "ingestion-pause recovery" → `failure-modes.md#disk-full` is mismatched | CLOSED — renamed index entry to "ingestion-pause (disk-full origin)" with cross-reference to the disk-full entry. Tests updated. Anchor-validating test extension was deferred to a future cleanup pass (the label fix solves the immediate confusion) |
| F8 | MEDIUM | adversary | README required manual YAML splitting on comment markers (error-prone) | CLOSED — replaced single combined `grafana-provisioning.yml` with two physical files: `grafana-datasource.yml` and `grafana-dashboard-provider.yml`. README "Importing the dashboard" rewritten to direct-mount each at its expected path with NO operator-side splitting. Test now asserts both files exist + carry the correct provisioning API contract |
| F9 | MEDIUM | adversary | Singleflight panel shows cumulative counter; misleading UX | CLOSED — PromQL changed to `rate(arxmcp_embed_singleflight_dedup_total[5m])`; panel title updated to "Embedder singleflight dedup rate (5m)"; description rewritten to explain why rate over cumulative |
| F10 | LOW | adversary | `_resolve_agent_role` swallows foreign-value coercion silently; no log | **DEFERRED** — defense-in-depth observability gap; not load-bearing for v1. The defensive coercion correctly protects label cardinality; logging is polish |
| F11 | LOW | adversary | Cardinality docstring drift (20 vs 24 in synthesis) | **DEFERRED** — pure doc tidy; both numbers safely under Prometheus best practices. Synthesis is a historical artifact |
| IS1 | MEDIUM | infra-safety | `localhost:9090` in provisioning YAML fails inside Grafana container | CLOSED — added inline YAML comment block documenting `host.docker.internal` (Docker Desktop) and `prometheus` (compose service alias) mitigations. README "Importing the dashboard" also covers the gotcha under "Grafana-in-container networking gotcha." Regression test asserts the YAML carries the documentation |
| IS2 | LOW | infra-safety | YAML comment said "split it" but README says "mount same file twice" — internally inconsistent | CLOSED — resolved by F8 simultaneously. The old combined `grafana-provisioning.yml` no longer exists; the new two-file split removes the entire "split or mount-twice" decision from the operator's hands |

## Rectification artifacts

- `docs/observability/langfuse-orchestrator.md`:
  - Rewrote `## Session ID handling` section to correctly describe
    MCP-library header emission + cite the shim's response-header
    extraction as evidence. **F1 closure.**
  - Removed `model: str = "claude-sonnet-4-5"` default; parameter
    is now required-no-default with docstring pointing at
    `model_selector.py`. **F4 closure.**
- `server/observability/__init__.py`:
  - Added side-effect import of `spend_constants` (with explanatory
    docstring). **F2 closure.**
- `server/observability/spend_constants.py`:
  - Updated `LAST_VERIFIED` docstring to point at the real
    regression test name. **F3 docstring closure.**
- `docs/ops/corpus-rollback.md`, `docs/ops/latexml-restart.md`,
  `docs/ops/latexml-drift-runbook.md`:
  - Replaced `/Users/chris.dare/Library/Python/3.9/bin/uv` with
    `uv run python`. **F5 closure.**
- `docs/ops/corpus-rollback.md`:
  - Replaced `curl http://127.0.0.1:7733/healthz/version` with
    `cat var/arxmcp/corpus-version.json` + `curl /healthz` and
    `curl /readyz`. **F6 closure.**
- `docs/ops/README.md`:
  - Renamed index entry #2 from "ingestion-pause recovery" to
    "ingestion-pause (disk-full origin)" with cross-reference to
    entry #3. **F7 closure.**
- `infra/observability/grafana-datasource.yml`: NEW. Datasource
  block with inline IS1 mitigation comments. **F8 + IS1 + IS2 closure.**
- `infra/observability/grafana-dashboard-provider.yml`: NEW.
  Dashboards provider block. **F8 closure.**
- `infra/observability/grafana-provisioning.yml`: DELETED. Replaced
  by the two files above. **F8 closure.**
- `infra/observability/grafana-dashboard.json`:
  - Panel 2 expr/title/description updated to use `rate(...)`
    over the cumulative counter. **F9 closure.**
  - Re-canonicalized via `json.dumps(sort_keys=True, indent=2)`
    so the byte-stability test stays green.
- `README.md`:
  - "Importing the dashboard" rewritten to direct-mount each of
    the two new YAML files (no operator-side YAML surgery) +
    explicit "Grafana-in-container networking gotcha" subsection.
    **F8 + IS1 closure.**
- `tests/test_grafana_dashboard.py`:
  - `TestProvisioningYaml` rewritten to assert BOTH new files exist
    + carry their respective provisioning blocks. **F8 + IS1
    regression guard.**
- `tests/test_langfuse_doc.py`:
  - `test_doc_explains_session_id_emitted_per_mcp_spec` (replaces
    the old wrong-claim test). **F1 regression guard.**
  - `test_snippet_does_not_hardcode_obsolete_model_id` rejects
    any `'claude-XXX'` literal in the snippet. **F4 regression guard.**
- `tests/test_runbook_index.py`:
  - `TestNoHardcodedUserPaths::test_no_user_path_hardcoded_in_ops_docs`
    walks `docs/ops/*.md`. **F5 regression guard.**
  - `TestCurlEndpointsExist::test_runbook_curl_endpoints_all_exist`
    extracts curl references and validates against the registered
    allowlist. **F6 regression guard.**
- `tests/test_spend_constants.py`:
  - `TestLastVerifiedFresh::test_last_verified_within_six_months`
    (180-day bound). **F3 closure + regression guard.**
  - `TestSpendMetricRegisteredAtRuntime::test_importing_observability_package_registers_spend_counter`
    imports `server.observability` (production path) and asserts
    the metric is reachable from REGISTRY. **F2 regression guard.**
- `tests/fixtures/metrics_sample.txt`:
  - Regenerated via `tools/regen_metrics_fixture.py` to include
    the now-registered `arxmcp_api_spend_usd_total` metric series.

## Final test count

`make test`: **2581 passed** (+7 from m10's 2491 -? wait let me
re-baseline: m10 closed at 2491; E14_Tier5plus impl added +83 to
2574; rect added +7 to 2581). 10 skipped (unchanged). 1 xfailed
(unchanged). Ruff clean.

Net delta from m10 baseline: **+90 tests** for the whole bundle.

## Deferred findings

- **F10 (LOW)** — `_resolve_agent_role` defensive coercion logs
  nothing. Defense-in-depth observability gap, not load-bearing.
  Defer to a future polish pass.
- **F11 (LOW)** — Cardinality docstring drift (20 vs 24 in
  research-synthesis.md). Both numbers safely under Prometheus
  best practices; synthesis is a historical artifact.
- **F7 anchor-validating test extension** — the label-only fix
  resolves the immediate confusion; the durable fix (parse target
  markdown's headers + slugify per CommonMark + verify anchor
  resolution) is a future enhancement. Tracked in
  `.claude/notes/deferred-work-tracker.md` if surfaced again.

## Re-verify gate notes

All 4 HIGH findings re-verified empirically before fixing:

- **F1** (HIGH): confirmed `shim/arxmcp_shim.py:150` is literally
  `sid = resp.getheader("mcp-session-id") or sid` — the server
  DOES emit the header (via the upstream MCP library). Synthesis
  A4 was wrong about server-side emission.
- **F2** (HIGH): confirmed via `grep -rln "spend_constants" server/
  ingest/` that only `server/query_encoder.py` (TODO comment only)
  and the spend module itself reference it. Nothing live-imports
  → metric never registers with default REGISTRY.
- **F3** (HIGH): confirmed via `grep "within_six_months"
  tests/test_spend_constants.py` returns zero matches. Docstring
  promised a test that didn't exist.
- **F4** (HIGH): confirmed at `docs/observability/langfuse-orchestrator.md:60`
  the literal `model: str = "claude-sonnet-4-5"` was present.

Zero findings invalidated. Adversary invalidation rate: **0 / 4
(0%)** for HIGH+CRITICAL; infra-safety invalidation rate: **0/0**.
Both critics well under the 40% threshold.

## Cross-critic agreement

- **IS2 + F8** converged on the same root cause: the original
  combined `grafana-provisioning.yml` with operator-side splitting
  was structurally fragile. Both critics independently caught
  facets of it (IS2: the "split" comment contradicts README's
  "mount same file twice"; F8: the splitting is error-prone with
  no machine-readable markers). The F8 closure (ship two physical
  files) closes both simultaneously.

## Rectification status (filled by Phase 4)

- F1 — fixed in `c10c2e3` (regression: tests/test_langfuse_doc.py::TestDocStructure::test_doc_explains_session_id_emitted_per_mcp_spec)
- F2 — fixed in `c10c2e3` (regression: tests/test_spend_constants.py::TestSpendMetricRegisteredAtRuntime::test_importing_observability_package_registers_spend_counter)
- F3 — fixed in `c10c2e3` (regression: tests/test_spend_constants.py::TestLastVerifiedFresh::test_last_verified_within_six_months)
- F4 — fixed in `c10c2e3` (regression: tests/test_langfuse_doc.py::TestDocStructure::test_snippet_does_not_hardcode_obsolete_model_id)
- F5 — fixed in `c10c2e3` (regression: tests/test_runbook_index.py::TestNoHardcodedUserPaths)
- F6 — fixed in `c10c2e3` (regression: tests/test_runbook_index.py::TestCurlEndpointsExist)
- F7 — fixed in `c10c2e3` (label fix; anchor-validating test extension deferred)
- F8 — fixed in `c10c2e3` (split into 2 YAML files; regression: tests/test_grafana_dashboard.py::TestProvisioningYaml updated)
- F9 — fixed in `c10c2e3` (panel rewritten; byte-stability test re-locked via canonicalization)
- F10 — deferred (LOW; defense-in-depth observability gap)
- F11 — deferred (LOW; doc drift only)
- IS1 — fixed in `c10c2e3` (YAML inline mitigation comment + README "Grafana-in-container networking gotcha")
- IS2 — fixed in `c10c2e3` (resolved simultaneously by F8 — combined YAML no longer exists)
