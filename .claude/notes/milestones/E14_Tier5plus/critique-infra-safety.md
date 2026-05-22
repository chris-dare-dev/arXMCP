# Critique — E14_Tier5plus

**Critic:** infra-safety
**Generated:** 2026-05-22T00:00:00Z
**Commit range:** a0a00d64e344d679c7f37abc15ab9dec8d180dd8..28b06c50ea7da5dab54a4d1929201cf81ba68007
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: one MEDIUM finding (localhost:9090 foot-gun for container-based Grafana) and one LOW finding (YAML comment vs README ambiguity on the split-file workflow). No CRITICAL or HIGH issues found.
- 0 CRITICAL, 0 HIGH, 1 MEDIUM, 1 LOW across 4 infra axes (Axes 1–4 N/A; Axis 5 Grafana-specific walked in full).
- Dashboard JSON byte-stable, UID deterministic, no embedded timestamps; metric names verified against the three registered-metric source files; provisioning structure conforms to Grafana 10.x/11.x conventions.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### IS1 — `localhost:9090` in provisioning YAML fails inside a Grafana container

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** infra/observability/grafana-provisioning.yml:32
- **What:** The datasource URL is `http://localhost:9090`. When Grafana itself runs inside a Docker container (the most common case when using `docker run grafana/grafana` or a compose service), `localhost` resolves to the Grafana container's own loopback interface, not the host. Prometheus at `host:9090` is unreachable; the datasource silently shows "connection refused" and every dashboard panel returns "No data".
- **Why it matters:** The project explicitly ships no Grafana compose file (deliberate scope discipline per synthesis D6), leaving the operator to run Grafana however they choose. The dominant pattern is `docker run grafana/grafana` or a compose stack. In both cases the hardcoded `localhost:9090` fails silently at provision time. The README's Option B guidance does not mention this. A first-time operator following the provisioning path gets an empty dashboard with no obvious error message — this is a latent usability and correctness foot-gun. It does NOT affect Option A (manual UI import where the operator manually selects their datasource) or operators running Grafana as a host binary.
- **Proposed fix:** Add a comment to `grafana-provisioning.yml` immediately above the `url:` line noting the container networking constraint and the two common mitigations: (a) `url: http://host.docker.internal:9090` for Docker Desktop on macOS/Windows; (b) a Prometheus service alias if both run in the same compose stack. Keep `localhost:9090` as the default (matching the host-binary case and project's loopback-only posture). Alternatively, replace the bare `localhost` with `${PROMETHEUS_URL:-http://localhost:9090}` so operators can override without editing the file. Either approach is ≤5 LOC.
- **Regression guard:** Add an assertion to `tests/test_grafana_dashboard.py::TestProvisioningYaml` that checks either (a) the URL comment mentions `host.docker.internal` as an alternative, or (b) the URL uses an env-var substitution pattern. The test already checks the literal string `http://localhost:9090` — augment it to also assert the comment context.

### IS2 — YAML comment says "split it" but the correct operator action is "mount the same file to both paths"

- **Severity:** LOW
- **Source:** infra-safety
- **File:** infra/observability/grafana-provisioning.yml:11–15
- **What:** The inline comment at line 11 says "the combined document here is the canonical 'what to provision' reference; operators split it into the two physical files when they wire up Grafana." The word "split" implies creating two separate files each containing only their respective block (`datasources:` or `providers:`). If an operator extracts only the `providers:` block into `dashboards/arxmcp.yml`, the resulting file lacks the required top-level `apiVersion: 1` key (which appears only once, at line 27, before the `datasources:` block). The README's Option B correctly says to mount the same file to both paths, but the YAML comment contradicts this by saying "split."
- **Why it matters:** If an operator follows the YAML comment literally and extracts the `providers:` section without carrying over `apiVersion: 1`, Grafana's dashboard provisioner will reject the file. Grafana 10 logs `WARN Provisioning failed to load data source provisioning config: failed to parse dashboard provisioner` with no apiVersion. This is a documentation bug, not a runtime bug in any path that follows the README.
- **Proposed fix:** Change the YAML comment at line 11 from "split it into the two physical files" to "mount this same file at both paths" to match the README's Option B wording.
- **Regression guard:** No automated guard needed beyond the existing `TestProvisioningYaml` test which validates the combined file. Acceptable as doc-only fix.

## What was done well

- **Byte-stability enforced and tested.** The dashboard JSON serializes identically under `json.dumps(sort_keys=True, indent=2, ensure_ascii=False)` with a trailing newline. The test `TestDashboardByteStability.test_json_keys_are_sorted_at_every_level` locks this in. No embedded `created`/`updated`/`iteration` timestamps appear in the JSON body — the only mutable field is `version: 1` which is correct for a provisioned, immutable dashboard.
- **Deterministic UID enforced end-to-end.** The dashboard UID is `arxmcp-cache-latency` (hardcoded in JSON:186) and every panel's `datasource.uid` is `prometheus` (JSON:14, :52, :88, :122, :152) — matching the provisioning YAML's `uid: prometheus` at line 35. The `TestPanelInvariants.test_every_panel_datasource_uses_provisioned_uid` test guards this linkage.
- **Metric names verified against registered sources.** The `TestMetricNamesAreRegistered.test_all_panel_metric_refs_are_registered` test greps the three actual metric registration files (`server/observability/metrics.py`, `server/metrics.py`, `server/health.py`) to confirm every PromQL reference in the dashboard hits a real metric. The brief's metric-name drift (`arxmcp_tool_latency_seconds` vs the real `arxmcp_request_latency_seconds`) was caught in research and the dashboard correctly uses `arxmcp_request_latency_seconds_bucket`.
- **`schemaVersion: 39` is the right Grafana 10.x/11.x target.** Version 39 was introduced in Grafana 10.0 and is accepted through 11.x. The dashboard uses the object-form datasource reference (`{"type": "prometheus", "uid": "prometheus"}`) rather than the legacy string form — this is the correct format for Grafana 9+ and avoids the silent datasource mismatch that the string form produces.
- **No timestamps, mutable IDs, or user-generated fields in the JSON.** The `id: null` convention is correct for provisioned dashboards (Grafana assigns the numeric ID on first load; `null` prevents collisions on re-import). Fields like `createdBy`, `updatedBy`, `gnetId`, and `iteration` are absent, keeping the file diff-friendly.
- **`editable: false` + `allowUiUpdates: false` is the right posture.** A provisioned dashboard should not be editable in the UI — edits would be lost on Grafana restart when the provisioner re-loads the file. Both fields correctly lock the dashboard.
- **`apiVersion: 1` for both provisioning blocks is correct.** Grafana 10.x and 11.x both accept `apiVersion: 1` for datasource and dashboard provider configs. Using a higher or absent version would cause Grafana to reject the file.
- **Scope discipline: no docker-compose for Grafana.** The milestone correctly avoided shipping a Grafana compose service (synthesis D6). This respects the project's convention that the operator chooses their Grafana deployment topology; shipping a compose file would bake in assumptions about image pinning, port allocation, and data persistence that are out of scope for this milestone.
- **`folderUid: arxmcp` + `folder: arXMCP` pairing is internally consistent.** Both the human-readable folder name and its UID are set, which is the Grafana 10 convention. The `folderUid` takes precedence over `folder` at import time; having both is the safe pattern.
- **Dashboard PromQL uses idiomatic histogram_quantile form.** The reranker and per-tool latency panels use `histogram_quantile(0.95, sum by (label, le) (rate(<metric>_bucket[5m])))` — the correct Prometheus 2.x form. Using `sum by ... le` before `histogram_quantile` is critical to avoid label-cardinality errors when multiple label values exist.

## Recommended rectification order

1. **IS1 (MEDIUM):** Add the `host.docker.internal` comment above `url:` in `grafana-provisioning.yml:32`, and update the test assertion. This is 3–5 LOC and prevents a silent empty-dashboard failure for the dominant container-based Grafana deployment pattern.
2. **IS2 (LOW):** Fix the YAML comment at line 11 to say "mount this same file at both paths" rather than "split it." One-line doc fix; no test change needed.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
