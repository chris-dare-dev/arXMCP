# Research Synthesis — corpus-integrity-completion-m1

**Synthesizer:** main orchestrator session (NOT a sub-agent)
**Generated:** 2026-05-31
**Briefs merged:** `research-brief-1.md` (in-codebase focus), `research-brief-2.md` (external + failure-modes focus)
**Verdict:** Auto-advance to Phase 2 / inline implementation. Briefs are fully aligned; no contested decisions.

---

## 1. Implementation contract (load-bearing)

Both researchers converge on the same shape. Append exactly two rules to `infra/prometheus/alerts.yml`, inside the existing `groups[0].rules[]` array (NOT a second `groups:` block — see FM-4). Each rule mirrors the byte-stable pattern of the 5 existing rules.

### Rule 1 — `ArXMCPCorpusCountRowsFailed`

```yaml
- alert: ArXMCPCorpusCountRowsFailed
  expr: arxmcp_corpus_chunk_count_actual == -1
  for: 10m
  labels:
    severity: critical
    component: corpus
  annotations:
    summary: "<summary text>"
    description: |
      <multiline description>
    runbook_url: "https://github.com/chris-dare-dev/arXMCP/blob/main/docs/ops/corpus-drift-runbook.md"
```

### Rule 2 — `ArXMCPCorpusUnindexedRows`

```yaml
- alert: ArXMCPCorpusUnindexedRows
  expr: arxmcp_corpus_unindexed_rows > 0
  for: 1h
  labels:
    severity: warning
    component: corpus
  annotations:
    summary: "<summary text>"
    description: |
      <multiline description>
    runbook_url: "https://github.com/chris-dare-dev/arXMCP/blob/main/docs/ops/corpus-drift-runbook.md"
```

### Test extension

Extend `tests/test_alerts_yaml.py::test_required_alerts_present` to include `ArXMCPCorpusCountRowsFailed` and `ArXMCPCorpusUnindexedRows` in the required set. Both researchers recommend this as the right regression guard pattern even though it's not in the literal AC. The current set per R2 §"Existing test coverage":

> "`tests/test_alerts_yaml.py:50-70` (`test_required_alerts_present`) asserts only `{ArXMCPDiskFull, ArXMCPDegradedMode, ArXMCPBackupStale}` exist. The two new names are NOT in that set. The implementer must decide whether to add them to the required set — adding them is the right call for regression protection, but is outside the strict AC. Recommend: extend the set."

---

## 2. Quoted load-bearing constraints

### From `server/health.py:113-114` (the `-1` sentinel contract, per R1)

> "``-1`` means count_rows() failed at startup (Resources.startup FM-2). Equals the marker gauge on the happy path."

### From R2 §"FM-2" — empty table ≠ -1 (important false-positive check)

> "An empty table returns 0, NOT -1. The `-1` sentinel is set ONLY when `count_rows()` raises an exception (`server/health.py:574: CORPUS_CHUNK_COUNT_ACTUAL.set(resources.startup_chunk_count)` where `startup_chunk_count` defaults to -1 on exception). This means the false-positive risk is LOW: `actual == -1` specifically means the API failed, not 'no data.'"

Implication: the alert rule is correctly calibrated for the AC's intent. Fresh-clone boot before first ingest does NOT trigger the alert (`count_rows()` on empty table returns 0; gauge = 0; rule fires only on -1).

### From scout final report §3 Rank 1 (the challenger's MINOR resolution, per R1)

> "Challenger v0 scope adjustment: Ship rule (b) (`actual == -1 for 10m` — count_rows() failure sentinel; NOT covered by `ArXMCPDegradedMode`) and rule (c) (`unindexed_rows > 0 for 1h` — NOT covered). Fold a `corpus-drift-runbook.md` into this scope; absorb CAND-24's killed runbook idea here."

### From the parent roadmap AC (resolved decision)

> "No new rule is added for above-tolerance drift in this milestone — the existing `ArXMCPDegradedMode` covers it; that decision is documented in the implementation summary per challenger §3 CAND-1."

---

## 3. Decisions resolved (no open questions)

Both briefs answered every potential open question by direct code-read:

1. **`runbook_url` vs `runbook` annotation key.** Resolved: `runbook_url` (every existing arXMCP rule uses it).
2. **`requires_promtool` test marker needed?** Resolved: NO. The existing `tests/test_alerts_yaml.py::test_promtool_check_rules` already uses `pytest.mark.skipif(shutil.which("promtool") is None, ...)`. No new marker pattern needed.
3. **Extra labels (team, severity-tier) needed?** Resolved: NO. Existing 5 rules carry exactly `severity` + `component`. Both new rules should match.
4. **`component:` value for the new rules.** Resolved: `corpus` (distinguishes from `storage` which is the `ArXMCPDiskFull` rule's `component:` value; `corpus` is new but not test-restricted).
5. **`docs/ops/corpus-drift-runbook.md` missing for m1 runbook_url.** Resolved: accepted risk per roadmap. Sibling m2 will ship the runbook. R2 FM-1 documents this as "accepted, documented risk."

---

## 4. Failure modes (consolidated from R2)

| FM | Trigger | Symptom | Mitigation |
|---|---|---|---|
| FM-1 | Operator clicks `runbook_url` before m2 ships | GitHub 404 | Accepted per roadmap; URL pattern still informs the operator; m2 lands shortly after m1 |
| FM-2 | Fresh-clone server boot before first ingest | NOT a trigger — empty table = `count_rows()` returns 0, gauge = 0; rule fires only on `-1` | No mitigation needed |
| FM-3 | Active ingest crash leaves unindexed rows | Alert fires only after `for: 1h` suppression | `for: 1h` is calibrated to filter normal-ingest windows; abnormal-ingest windows >1h fire correctly |
| FM-4 | Implementer adds duplicate `groups:` block | `test_arxmcp_group_present` fails; `promtool check rules` flags | Append INSIDE existing `groups[0].rules[]`; do NOT add second `groups:` key |
| FM-5 | New rules missing `component:` label | `test_alert_rule_shape` passes (only checks `severity`) but pattern-inconsistent | Add `component: corpus` per R1 + R2 recommendation |
| FM-6 | Future change removes new rule names silently | No test fails | Extend `test_required_alerts_present` to include both new names |
| FM-7 | `arxmcp_corpus_unindexed_rows == -1` (index API broken) | Rule does NOT fire (`-1 > 0` is false) | Accepted per m3 docstring; `ArXMCPDegradedMode` covers broader startup failures |

The two MUST-mitigate FMs (FM-4 and FM-6) are addressed by the implementation contract above. FM-5 is the silent-but-important one — `component: corpus` is NOT in the literal AC; both researchers strongly recommend it; the implementation must include it.

---

## 5. Test surface

- **No new tests required** for the YAML rules themselves — `tests/test_alerts_yaml.py` already validates: YAML syntax, group presence, rule shape (`alert`/`expr`/`for`/`labels`/`annotations` all present), severity in `{critical, warning, info, page}`, runbook_url annotation present, and (when promtool is on PATH) `promtool check rules` exits 0.
- **Test extension required** in `tests/test_alerts_yaml.py::test_required_alerts_present` — add `"ArXMCPCorpusCountRowsFailed"` and `"ArXMCPCorpusUnindexedRows"` to the required set. ~2 line change. Forward regression protection (prevents silent removal of either new rule).
- **No new test marker.** The existing `skipif(shutil.which("promtool") is None, ...)` is the canonical pattern.

---

## 6. External writes the implementation will require

Both briefs agree: **NONE for implementation.** The only file changes are `infra/prometheus/alerts.yml` (the two new rule blocks) and `tests/test_alerts_yaml.py` (the required-set extension). All local.

R1 mentions `git push origin main` as a Phase 4 event, which is correct — but that's the post-rectification user-authorized push, not an implementation write. Per pipeline convention, `external_writes_required` for this milestone is **`[]`** (empty list).

---

## 7. Open questions (none blocking)

None.

R1's only non-blocking note: introducing `component: corpus` as a new value (existing values are `storage`, `server`, `backup`, `eval`, `latexml`) may affect Grafana dashboards or Alertmanager routing rules if an operator has them configured. For arXMCP's single-workstation target this is informational, not blocking. Document the new value in the implementation summary.

---

## 8. Orchestrator synthesis note

The two briefs are remarkably aligned — both arrived at the same implementation shape via independent paths (R1 via in-codebase pattern-matching, R2 via external-spec verification + failure-mode enumeration). The agreement is the strongest possible signal for auto-advance. The synthesis adds no new constraints beyond what either brief contributed; it deduplicates and prioritizes:

- **Highest-confidence decisions (both briefs agree):** annotation key (`runbook_url`), label structure (`severity` + `component`), insertion site (`groups[0].rules[]`), test extension target (`test_required_alerts_present`).
- **Single-brief contributions worth preserving:** R2's FM-2 empty-table check (rules out a false-positive concern that would otherwise need verification), R1's quote of `server/health.py:113-114` (the -1 sentinel contract).
- **No disagreements.** External-write count differs in semantics (R1 says "git push Phase 4 only" = 1, R2 says "none" = 0) but both mean "no writes during implementation"; the state field is set to `[]`.

Implementation path: **inline** (orchestrator main session). Estimated effort: ~30 LOC YAML in alerts.yml + 2 LOC test extension. Well under the 500 LOC / 5 files threshold for delegation. No specialist match. No novel architecture.
