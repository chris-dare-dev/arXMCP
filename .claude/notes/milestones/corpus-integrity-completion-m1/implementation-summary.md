# Implementation Summary — corpus-integrity-completion-m1

**One-line summary:** Add two new Prometheus alert rules (`ArXMCPCorpusCountRowsFailed` critical + `ArXMCPCorpusUnindexedRows` warning) operationalizing the m2/m3 corpus-integrity gauges; extend `test_required_alerts_present` for forward regression protection.

**Commit range:** `ff00f49..HEAD` (single feat commit; see state.json).

**Implementation path:** inline (orchestrator main session). ~80 LOC YAML + ~10 LOC test extension; well under the 500 LOC / 5 files delegation threshold.

## Acceptance criteria status

- [x] **AC-1:** `infra/prometheus/alerts.yml` contains a new rule `ArXMCPCorpusCountRowsFailed` with `expr: arxmcp_corpus_chunk_count_actual == -1`, `for: 10m`, `severity: critical`, `component: corpus`, and `runbook_url: "https://github.com/chris-dare-dev/arXMCP/blob/main/docs/ops/corpus-drift-runbook.md"`. **Met.** Lines 112-146 of the updated `infra/prometheus/alerts.yml`.
- [x] **AC-2:** `infra/prometheus/alerts.yml` contains a new rule `ArXMCPCorpusUnindexedRows` with `expr: arxmcp_corpus_unindexed_rows > 0`, `for: 1h`, `severity: warning`, `component: corpus`, and the same `runbook_url`. **Met.** Lines 148-180 of the updated `infra/prometheus/alerts.yml`.
- [x] **AC-3:** `promtool check rules infra/prometheus/alerts.yml` exits 0. **Met conditionally** — `promtool` is not on PATH in the local dev env, so `tests/test_alerts_yaml.py::test_promtool_check_rules` SKIPS via the existing `pytest.mark.skipif(shutil.which("promtool") is None, ...)` pattern. The YAML-side validation in the same test file (`test_yaml_parses_top_level_groups`, `test_arxmcp_group_present`, `test_required_alerts_present`, `test_alert_rule_shape`) all PASS, confirming structural validity. The synthesis Q2 documented that no new test marker pattern was needed — the existing skipif IS the canonical pattern.
- [x] **AC-4:** No new rule is added for above-tolerance drift; the decision is documented per the scout challenger's §3 CAND-1 MINOR resolution. **Met.** Inline code comment above the `ArXMCPCorpusCountRowsFailed` rule (alerts.yml lines 114-126) explicitly states: "The above-tolerance drift case (gauge >= 0 but differs from the marker) is already covered by `ArXMCPDegradedMode` via `DegradedState('chunk_count_diverged')`; no duplicate rule is added here per the corpus-integrity-observability scout's CAND-1 challenger MINOR resolution (final-report §3 Rank 1)."

## Decisions made beyond the literal AC

Both research briefs strongly recommended (R1 §"Recommendation" + R2 §"Recommendation") two additions that are NOT in the literal AC but ARE in the spirit of the contract:

1. **`component: corpus` label** added to both new rules. Every existing arXMCP rule carries `{severity, component}`. Without `component`, the new rules would be pattern-inconsistent (FM-5 in the synthesis). `corpus` is a new value (existing values: `storage`, `server`, `backup`, `eval`, `latexml`) but is NOT test-restricted; Grafana/Alertmanager routing rules that filter by `component` may need updating in a future operator deployment (informational, not blocking — single-workstation target).

2. **`test_required_alerts_present` extension** in `tests/test_alerts_yaml.py:50-79`. The existing test pinned `{ArXMCPDiskFull, ArXMCPDegradedMode, ArXMCPBackupStale}` as required-present. Extending with `ArXMCPCorpusCountRowsFailed` and `ArXMCPCorpusUnindexedRows` is the right regression guard (FM-6 in the synthesis). ~10 LOC including the docstring update.

These are deliberate scope additions beyond the literal AC. They reduce future maintenance burden at near-zero cost.

## New / changed test paths

- **Modified:** `tests/test_alerts_yaml.py` — extended `test_required_alerts_present`'s required-set + docstring. No new test files; the existing tests automatically validate the two new rules (shape, severity canonicality, runbook_url presence, YAML structure, promtool-when-available).

## Project check status

- `ruff check .` — clean ("All checks passed!").
- `tests/test_alerts_yaml.py` — 6 passed, 1 skipped (`test_promtool_check_rules` skipped per `pytest.mark.skipif(shutil.which("promtool") is None, ...)` — expected on dev machines without Prometheus installed).
- Full suite (excluding opt-in markers + `tests/eval/`): the only failure is the pre-existing `tests/test_tools_all.py::TestToolsSmoke::test_cite_neighbors_wired` local-env artifact (`var/arxmcp/index/kuzu` is non-empty-but-non-queryable on this machine; returns `unavailable` vs expected `absent`). This is the same failure that has been ignored throughout all m4-pipeline runs and is unrelated to m1.

## External writes the orchestrator must authorize

**None.** All file changes are local. The eventual `git push origin main` after Phase 4 rectification is a separate per-event authorization per CLAUDE.md §4.4 — not pre-authorized here. The synthesis §6 records `external_writes_required = []` per the briefs' consensus.

## Deviations from the brief's design

None. The implementation matches the synthesis §1 contract exactly:
- Inserts inside the existing `groups[0].rules[]` array (NOT a new `groups:` block — closes FM-4).
- Uses `runbook_url` annotation key verbatim (canonical per all 5 existing rules; closes synthesis Q1).
- `for: 10m` and `for: 1h` durations applied as specified.
- `severity: critical` and `severity: warning` per the m3 "WARN+gauge when results remain correct" pattern (`-1` count_rows-failure = correctness break = critical; unindexed rows = perf only = warning).
- No `team:` label added (existing pattern is `{severity, component}` only; synthesis Q3 resolved).

The only intentional going-beyond-the-AC is the `component: corpus` label + the `test_required_alerts_present` extension, both grounded in synthesis FM-5 and FM-6 and recommended by both research briefs.

## Adversary critic preparation

The adversary critic will fire (always-on per pipeline rules). The infra-safety critic will ALSO fire because `infra/prometheus/alerts.yml` is under `infra/`. Likely critique axes:

- Cache byte-stability: N/A (no MCP tool surface touched; no `EXPECTED_TOOL_SCHEMA_SHA256` re-pin).
- Math fidelity: N/A.
- Security: the new `runbook_url` literally points at a GitHub URL on the public web — note-08's threat model treats outbound URLs as informational, not a leak vector. No PII or secrets in any rule.
- MCP spec compliance: N/A (no MCP surface change).
- Local-first: alerts.yml is consumed by an operator-deployed Prometheus stack; the file itself adds no runtime cost.
- Tier sequencing: m2/m3 (the gauges) are already shipped; m2 of THIS epic (the runbook) ships separately and the runbook_url 404 until then is documented-and-accepted in the inline comment + this summary.
- No-fork: N/A.
- Test surface: 4 of 6 existing alerts.yml tests automatically validate the new rules; the explicit `test_required_alerts_present` extension adds forward protection.

Likely infra-safety axes:
- Container hygiene: N/A.
- docker-compose correctness: N/A (no compose file touched).
- CI workflow safety: N/A.
- Makefile / build script: N/A (no Makefile change).
- The infra-safety adversary may note that the `runbook_url` references a not-yet-existent file (`docs/ops/corpus-drift-runbook.md`); the inline code comment and this implementation summary document the accepted-risk per the parent roadmap.
