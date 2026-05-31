# Critique — corpus-integrity-completion-m1

**Critic:** infra-safety
**Generated:** 2026-05-31T00:00:00Z
**Commit range:** ff00f49dfe4ddb604c2f420dbfc0921225069084..c58c19e
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: one MEDIUM finding (IS1) on the missing runbook URL, all other axes clean
- 0 CRITICAL, 0 HIGH, 1 MEDIUM, 1 LOW
- Axes 1–4 (container hygiene, docker-compose, CI workflows, Makefile) are N/A for this diff
- The two new rules are structurally well-formed: appended INSIDE `groups[0].rules[]`, not as a duplicate `groups:` block
- PromQL expressions are syntactically valid; `test_promtool_check_rules` skips correctly when `promtool` absent and runs when present — skip logic is sound
- New `component: corpus` label is a new value but acceptable for a single-workstation deployment; operator action needed only if Alertmanager routing is keyed on `component`
- `for: 10m` calibration for the critical rule matches the existing `ArXMCPBackupStale` precedent; `for: 1h` for the warning rule is longer than any existing rule but is defensible for the HNSW rebuild window

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### IS1 — Runbook URL 404 until sibling m2 lands

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** infra/prometheus/alerts.yml:143 and :172
- **What:** Both new rules point `runbook_url` at `https://github.com/chris-dare-dev/arXMCP/blob/main/docs/ops/corpus-drift-runbook.md`. That file does not exist in the repo as of this commit (confirmed: `docs/ops/` contains no `corpus-drift-runbook.md`). An operator clicking the link during the window between m1 and m2 gets a GitHub 404.
- **Why it matters:** The primary value of `runbook_url` is that an on-call operator can act immediately when `ArXMCPCorpusCountRowsFailed` fires at 2 a.m. A 404 removes that recovery path at exactly the moment stress is highest. The critical-severity rule (`ArXMCPCorpusCountRowsFailed`) is the more exposed of the two. The research synthesis (FM-1) acknowledges this as accepted risk, but "accepted" should mean documented in a visible place, not just in the implementation summary.
- **Proposed fix:** Either (a) ship a stub `docs/ops/corpus-drift-runbook.md` in this commit with `# corpus-drift-runbook — placeholder until corpus-integrity-completion-m2` (< 5 LOC, self-contained), or (b) add an inline YAML comment below the `runbook_url` lines — e.g. `# NOTE: runbook ships in corpus-integrity-completion-m2; url is valid after that milestone lands` — so an operator who examines the raw YAML understands the transient state. Option (a) is preferred because it stops the 404; option (b) is acceptable if the project's doc-placement rules prohibit a stub file under `docs/ops/`.
- **Regression guard:** No new test is required for this finding. If option (a) is taken, verify `docs/ops/corpus-drift-runbook.md` exists at the repo root before Phase 4 closes.

### IS2 — `for: 1h` calibration lacks corpus-scale citation

- **Severity:** LOW
- **Source:** infra-safety
- **File:** infra/prometheus/alerts.yml:159
- **What:** The inline comment for `ArXMCPCorpusUnindexedRows` says the `for: 1h` duration "filters any transient startup + rebuild window" but does not cite a measured or estimated rebuild time for the seed corpus. The existing rules all use durations ≤ 10m; `for: 1h` is 6× the next-longest duration (`ArXMCPBackupStale` at 10m) and 60× the shortest (1m). No design note or research document was found that benchmarks the HNSW rebuild time against the seed-corpus scale.
- **Why it matters:** If a 50-paper ingest triggers a rebuild that completes in 90 seconds (plausible for a small corpus), the `for: 1h` suppression means a genuine stuck-rebuild scenario would not page the operator for 58 additional minutes. Calibration is not wrong — it is conservatively wide — but the rationale is implicit. Future corpus growth could push the rebuild time well past 1h on production scale, inverting the calibration's intent.
- **Proposed fix:** Add one comment line to the `ArXMCPCorpusUnindexedRows` block: `# for: 1h — measured worst-case for seed corpus (50 papers) is <5m; 1h ensures` / `# full production ingest (N>>50k rows) does not generate spurious alerts.` If no measurement exists, note `# conservative: measured or estimated rebuild window < Xm on seed corpus`. This is a comment-only change (0 LOC functional impact).
- **Regression guard:** N/A (LOW, comment-only).

## Axis walk

### Axis 1 — Container hygiene

N/A. The diff touches only `infra/prometheus/alerts.yml`. The alerts.yml is consumed by an operator-deployed Prometheus stack, not by the arXMCP Docker container. The project's `infra/docker-compose.yml` does not include a Prometheus service; the file header comment (lines 1–16) explicitly documents this: "Mount this file into the operator's Prometheus deployment (out of scope here — Phoenix is the OTel sidecar, not a Prometheus scraper; the operator runs Prometheus + Grafana separately, landing in E14_S09)." Container hygiene for the arXMCP server image is unchanged; `docker/Dockerfile.server` is unmodified.

### Axis 2 — docker-compose correctness

N/A. The diff does not touch any `docker-compose*.yml` file. The existing `infra/docker-compose.yml` and `infra/observability/phoenix-compose.yml` are unmodified. No port binding, volume mount, or restart-policy concerns introduced.

### Axis 3 — CI workflow safety

N/A. The diff does not touch `.github/workflows/`. No workflows exist in this repo yet.

### Axis 4 — Makefile / build script discipline

N/A. The diff does not touch the Makefile.

### Axis 5 — YAML structural correctness

CLEAN. The two new rules are appended INSIDE the existing `groups[0].rules[]` array at `infra/prometheus/alerts.yml:127` and `:157`. Verified by parsing: there is exactly one top-level `groups:` key; `spec["groups"]` is a list of length 1 with name `arxmcp`; the group now contains 7 rules (was 5). There is no duplicate `groups:` key that would trigger PyYAML's last-key-wins silent overwrite behavior. The diff's `+` lines show the new blocks as indented YAML list items under `rules:`, not as a new `groups:` block.

### Axis 6 — Operator-deployable PromQL correctness

CLEAN. Both expressions are syntactically valid PromQL:
- `arxmcp_corpus_chunk_count_actual == -1` — scalar equality comparison on a gauge metric with an integer literal; valid PromQL.
- `arxmcp_corpus_unindexed_rows > 0` — scalar threshold comparison; valid PromQL.

The `test_promtool_check_rules` test (tests/test_alerts_yaml.py:133) uses `@pytest.mark.skipif(shutil.which("promtool") is None, reason=...)`. This pattern is correct and consistent with the existing E14_S04 `crontab -T` defer pattern: the test skips when `promtool` is absent and runs the canonical validator when present (PATH lookup is evaluated at collection time, not at import time, which is the correct behavior for a `skipif` condition). The skip does NOT false-pass — a missing `promtool` produces an explicit skip marker, not a passing assertion. All six PyYAML-backed tests pass (confirmed: `6 passed, 1 skipped` in the current test run); the 1 skipped is `test_promtool_check_rules`.

### Axis 7 — Runbook URL trustworthiness

FINDING IS1 (MEDIUM). `docs/ops/corpus-drift-runbook.md` does not exist in the repo. Both new rules' `runbook_url` values resolve to a GitHub 404 until sibling milestone m2 ships the file. The inline comments in alerts.yml explain the metric semantics but do not inform an operator that the runbook URL is temporarily dead. The test docstring (tests/test_alerts_yaml.py:57–59) does disclose "sibling m2 will create" with "references the path optimistically per the roadmap's accepted-risk note" — but this is test-internal prose, not operator-visible. See IS1 for the proposed fix.

### Axis 8 — Severity-tier and label conventions

MOSTLY CLEAN, one callout. The `component: corpus` label is new. Existing values in the file are: `storage`, `server`, `backup`, `eval`, `latexml`. An operator running Alertmanager with routing rules keyed on `component` will see both new corpus rules fall through to the default route. For a single-workstation deployment (the declared project profile), this is acceptable: the default route will still deliver the alert, just without any component-specific routing enrichment. The two existing labels (`severity: critical` / `severity: warning`) are canonical per `test_alert_rule_shape`'s allowlist. No finding is raised; operator-action-needed note: if Alertmanager routing is in use, add a `corpus` route matcher.

### Axis 9 — `for:` duration calibration

MOSTLY CLEAN, one deferred note (IS2). The existing `for:` durations in the file are: `5m` (disk-full), `1m` (degraded-mode), `10m` (backup-stale), `1m` (eval-quarantine), `1m` (latexml-drift). The new rules use `10m` (critical rule) and `1h` (warning rule). The `10m` for `ArXMCPCorpusCountRowsFailed` matches the `ArXMCPBackupStale` precedent and equals 20 scrapes at the 30s group interval — well-calibrated for a "startup hiccup suppression" intent. The `1h` for `ArXMCPCorpusUnindexedRows` is 6× the next-longest existing `for:` duration and is intended to filter normal-ingest rebuild windows. The calibration logic is sound in direction (a warning about a perf-only degradation warrants a wider suppression window than a critical failure). However, no corpus-scale measurement is cited; see IS2.

### Axis 10 — Idempotency / re-deployability

CLEAN. Prometheus alerts.yml is stateless YAML; Prometheus parses it fresh on every reload (SIGHUP or restart). There is no mutable on-disk artifact produced by loading this file. Re-loading the same alerts.yml twice is a no-op at the Prometheus level. No concern.

## What was done well

- The two new rules are correctly appended INSIDE the existing `groups[0].rules[]` array, avoiding the PyYAML last-key-wins duplicate-`groups:` trap that the research explicitly identified as FM-4.
- Both PromQL expressions are syntactically unambiguous: `== -1` and `> 0` are scalar comparisons on gauge metrics with no label selectors, which is the simplest and most portable PromQL form for single-workstation Prometheus deployments.
- The `-1` sentinel design is well-thought-out: an empty LanceDB table returns `count_rows() = 0`, so `actual == -1` fires ONLY on a genuine API failure, not on a freshly-initialized deployment. This eliminates the entire class of false-positive cold-clone alerts documented as FM-2.
- The `ArXMCPCorpusUnindexedRows` rule correctly excludes the `-1` unknown sentinel (`-1 > 0` is false), preventing double-firing with `ArXMCPDegradedMode` when the index API is broken. This is explicitly documented in the inline comment (lines 151–156).
- The inline YAML comments for both new rules are unusually thorough: they cite the milestone, the gauge's semantics, the `for:` duration rationale, AND the interaction with the existing `ArXMCPDegradedMode` rule. Future maintainers can read the alerts.yml without needing to consult the implementation summary.
- The test in `test_required_alerts_present` was extended to include both new alert names (tests/test_alerts_yaml.py:72–75), providing forward regression protection against silent removal.
- Both new rules use `severity: warning` / `severity: critical` — canonical values per the test's severity allowlist — avoiding the non-canonical value trap.
- The `for: 10m` choice for the critical rule aligns with the existing `ArXMCPBackupStale` precedent, maintaining consistent calibration for "wait N scrapes before firing a persistent-failure alert."
- The deployment topology comment in the alerts.yml header (lines 1–16) is accurate: the file is correctly scoped as operator-managed infrastructure outside arXMCP's own docker-compose, reducing the risk of an operator naively trying to include it in the arXMCP container.
- All 6 PyYAML-backed tests pass; the 1 skipped test (`test_promtool_check_rules`) skips correctly when `promtool` is absent, not silently false-passes.

## Recommended rectification order

1. **IS1 (MEDIUM):** Add a stub `docs/ops/corpus-drift-runbook.md` (< 5 LOC) or an inline YAML comment below both `runbook_url:` lines noting the file ships in corpus-integrity-completion-m2. The stub file approach is preferred as it stops the 404 immediately. This is a ≤ 5 LOC change.
2. **IS2 (LOW, deferred):** Add one comment line to the `ArXMCPCorpusUnindexedRows` block citing the measured or estimated rebuild window for the seed corpus. Defer to m2 or a follow-up chore commit.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
