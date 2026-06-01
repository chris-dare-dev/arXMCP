# Critique — corpus-integrity-completion-e1

**Critic:** adversary
**Generated:** 2026-05-31T23:50:00Z
**Commit range:** `688b25f6eab603b38cd1251b7200c6b103766450..fb3cdff16340fb61986bbb0b5fc365030487adca`
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Gate placement and behavior match the spike-1 binding contract exactly; all 6 new mutation/positive tests pass; m3 integration test restructured cleanly into a defence-in-depth pair with the new e1 write-side gate.
- 0 CRITICAL, 0 HIGH, 3 MEDIUM, 1 LOW. No data-loss, security, or invariant-violation risks.
- Highest-risk item: `tests/test_write_chunks_wap_gate.py:117-126` Mutation A docstring overstates "Multi-call cumulative table is 30 rows; the last marker says chunk_count=1" — gate actually fires on call 1 (table=10, marker=1), the third call never executes. The test passes, but a future maintainer reading the docstring as ground truth would mis-diagnose the firing point.
- Axis 1 (cache byte-stability): clean — no `server/tools.py::ALL_TOOLS` change; `EXPECTED_TOOL_SCHEMA_SHA256` re-pin not required.
- Axis 3 (security): clean — `target_path` in the RuntimeError text reaches only the local ingest log (no Prometheus label, no OTel span tag, no /metrics surface in `ingest/store.py`); `RedactionFilter` redacts query/body/mathml fields only, not paths, but the path is not classified as sensitive under the single-user threat model.
- Axis 6 (tier sequencing): clean — m1, m2, m3, and spike-1 all `phase: complete` per their `state.json` files.
- Axis 7 (no-fork): clean — `git diff --stat` shows zero changes to `pyproject.toml`, `uv.lock`, or `requirements*.txt`; no vendored OSS lift.
- Side-effect gap: the gate raising RuntimeError skips `_append_store_stats(stats)` (line 1062). LanceDB rows already committed; the store-stats.jsonl audit row never lands for the failing call. This is MEDIUM observability drift — not data loss, but auditors lose the row that triggered the failure.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Mutation A docstring claims gate fires on call 3 (actually fires on call 1)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_write_chunks_wap_gate.py:117-126`
- **What:** The Mutation A test docstring says "Multi-call cumulative table is 30 rows; the last marker says chunk_count=1. Gate fires the COUNT-MISMATCH arm." This describes the gate firing on the third (final) `write_chunks` call. Behaviorally, the monkeypatched `bad_marker_writer` injects `chunk_count=1` on EVERY call; the first `write_chunks` call writes 10 chunks → table=10, marker=1 → gate fires on call 1. The third call never executes. The `pytest.raises(RuntimeError, match="reports chunk_count=")` assertion is satisfied regardless of which call raises, so the test passes — but the docstring describes a different firing path than the code exercises.
- **Why it matters:** A future maintainer reading the docstring will mis-model the test surface. If they later add a "test the FINAL marker state on disk" assertion (a plausible extension to harden the regression guard), they will write it against the wrong expected state (marker=1, table=10 at the moment of failure, not marker=10 and table=30 as the docstring implies). The misdescription also masks a potential strengthening: an explicit assertion that the gate fires on the FIRST bad write, not allowing 30 stale rows + a wrong marker to ship to the audit log before catching the regression. The adversary-memory entry `regression-guard-pins-names-not-shape.md` is exactly this class of pattern.
- **Proposed fix:** Update the Mutation A docstring to describe actual gate-firing behavior — "The first `write_chunks` call writes 10 chunks → table=10 rows; the monkeypatched writer injects chunk_count=1 into the marker; the gate reads back chunk_count=1, sees fresh_count=10 → COUNT-MISMATCH arm fires before the second call executes." Optionally add a `excinfo.value` substring assertion pinning the chunk_count=1 / fresh=10 numerical state so the test guards the firing-point, not just any-MISMATCH.
- **Regression guard:** add `with pytest.raises(...) as excinfo` and assert `"chunk_count=1" in str(excinfo.value)` and `"tbl.count_rows()=10" in str(excinfo.value)` to pin the call-1 firing semantics.

### F2 — Gate raises after LanceDB commit; `_append_store_stats` skipped, audit log loses the failing row

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `ingest/store.py:1062` (the `_append_store_stats(stats)` call, skipped when the gate raises at lines 1020-1054)
- **What:** The gate at lines 1017-1054 raises `RuntimeError` BEFORE `_append_store_stats(stats)` at line 1062 executes. By the time the gate fires, the LanceDB `merge_insert` has already committed (line 857-862) and `_create_indices` has run (line 874). The store-stats.jsonl audit log NEVER receives a row for the failing call — the operator who runs `make ingest` sees a RuntimeError in the ingest log, but the `var/arxmcp/ops/store-stats.jsonl` audit trail is silent about the commit that actually happened. `WriteStats.total_rows_after_commit` was populated at line 954 inside the swallow's try-block but is never serialized.
- **Why it matters:** Reduces observability discipline on the very failure path the gate exists to surface. Operators correlating "what got written when" against the audit log will see a gap where the gate caught a divergence — the LanceDB rows ARE there, the index IS there, but no audit row records the transaction. On a multi-paper bulk run that aborts mid-batch, post-mortem reconstruction loses the row that pinned the failing paper. This is documented-but-undocumented behavior: the implementation summary §Deviations does not mention this side effect.
- **Proposed fix:** Wrap the gate in a `try ... finally: _append_store_stats(stats)` shape, OR call `_append_store_stats(stats)` immediately before each `raise RuntimeError(...)` in the three gate arms. The audit row should record `total_rows_after_commit = fresh_count` and a new `gate_failure_reason` field with values like "missing_marker" / "malformed_marker" / "count_mismatch". This keeps the LanceDB-committed/audit-recorded invariant intact across the gate. Alternative (lower-LOC): move `_append_store_stats(stats)` to AFTER the swallow's except-block closes but BEFORE the gate — the audit row lands BEFORE the gate either passes or raises.
- **Regression guard:** add a 7th test to `tests/test_write_chunks_wap_gate.py` — `test_gate_failure_still_appends_audit_row` — that drops Mutation A's gate-firing state, reads `store-stats.jsonl`, and asserts the audit row for the failed call is present with the gate's diagnostic.

### F3 — Runbook S5 vs S6 routing requires operator to grep the ingest log; not actionable from RuntimeError text alone

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `docs/ops/corpus-drift-runbook.md:137-142` (the routing table); `ingest/store.py:1043-1054` (the COUNT-MISMATCH error text)
- **What:** The gate's COUNT-MISMATCH RuntimeError text instructs operators to "check the immediately preceding log line for a 'could not write corpus-version.json marker' warning." The runbook's routing table (lines 137-142) explicitly conditions S5 vs S6 on this swallow-warning presence/absence. An operator who sees the RuntimeError text in a CI summary, a paging alert body, or a non-streaming log channel (e.g., a sentry capture that includes only the exception text) cannot route between S5 (recoverable via `make reconcile`) and S6 (code fix required) without separately grep-ing the ingest log. The gate could expose this routing decision IN ITS OWN ERROR TEXT by checking whether the swallow's "could not write" log line was emitted in this call (the same logger handler captures it; the gate could inspect a module-local `_last_swallow_emitted_in_call` flag set in the except-block).
- **Why it matters:** Operator-actionability is exactly what the spike's rect F6 promised. On a 2am page where the operator has only the exception message (e.g., from a Slack alert), routing to S5 vs S6 requires SSH-into-host + grep — adding 60+ seconds to the MTTR. A cheaper improvement: tag the gate's RuntimeError text with the routing decision when known. Today the error says "Likely causes: (1)... OR (2)..." — it could say "Likely cause: arithmetic regression (S6)" or "Likely cause: swallowed marker write (S5)" deterministically.
- **Proposed fix:** Set a module-local sentinel (or thread-local) inside the swallow's `except Exception` block at line 982-989 (e.g., `_marker_write_failed_in_call = True`). Read it in the gate's COUNT-MISMATCH arm and emit a single-line routing tag in the RuntimeError text: `Routing: S5 (swallow + stale marker)` or `Routing: S6 (arithmetic regression)`. Update the runbook's routing table to reference the routing-tag substring instead of the more general "check the preceding log line" instruction. Net LOC: ≤ 15 production + ≤ 20 test extension.
- **Regression guard:** extend `tests/test_write_chunks_wap_gate.py::test_mutation_D_stale_marker_swallow` to assert `"Routing: S5" in str(excinfo.value)`, and extend `test_mutation_A_wrong_value_marker` to assert `"Routing: S6" in str(excinfo.value)`.

### F4 — Two `assert` statements added to `test_pre_m1_bug_shape_is_caught_by_integration` — style drift from the surrounding `raise AssertionError(...)` pattern

- **Severity:** LOW
- **Source:** adversary
- **File:** `tests/test_server_startup_integration.py:290, 300`
- **What:** The restructured m3 integration test uses two bare `assert` statements (`assert marker_path.is_file(), (...)` at line 290; `assert marker_data["chunk_count"] == _CUMULATIVE_CHUNK_COUNT, (...)` at line 300). Every other invariant check in this file uses the `if ... raise AssertionError(...)` pattern (e.g., line 180, 185, 196, 317, 324, 329). The file's pre-existing style is `raise AssertionError`; the e1 restructuring introduces a style drift.
- **Why it matters:** `CLAUDE.md §4.7` bans `assert` for invariants ("Python `-O` strips them"). Pytest's normal idiom uses `assert` (which pytest rewrites), so the rule is mainly aimed at production code — these are test-file assertions, so the practical risk is low (no one runs pytest with `-O`). But the file's surrounding style is consistent and the drift is gratuitous. The two new asserts should match the surrounding pattern.
- **Proposed fix:** Rewrite the two `assert ..., (...)` lines as `if not ...: raise AssertionError(...)` to match the surrounding pattern in this file. Two-line mechanical edit.
- **Regression guard:** n/a — style fix.

## What was done well

- Gate placement is spike-1-exact: after the swallow `try/except` at lines 931-989 closes, before `_append_store_stats` at line 1062. The CRITICAL F1 from the spike-1 critique (gate inside the try → swallowed raise) is correctly avoided.
- The three error arms (malformed / absent / count-mismatch) are byte-for-byte from the spike's §3 code shape; all three tests (`test_mutation_A`, `B`, `C`, `D`) match the spike's test plan.
- Circular-import deviation (function-local `from server.corpus import read_corpus_version`) is correctly diagnosed, documented at TWO sites (the module's import block at lines 106-116 and the gate site at lines 1011-1014), and has zero runtime semantic difference vs. the spike's specification.
- m3 integration test restructuring is principled: instead of deleting the test (which would orphan the m3 read-side detection contract), the test was rebuilt to manually mutate the on-disk marker AFTER a clean ingest, validating the m3 path INDEPENDENTLY of the e1 gate. The defence-in-depth narrative is explicit in the docstring at lines 207-262.
- The FM-13 coverage (two sequential `write_chunks` calls on the same path — the `ingest/re_embed.py:528,558` shape) lands as `test_positive_path_re_embed_two_call_shape` at lines 95-113; this addresses the research-brief-2 surfaced gap proactively.
- Mutation D's design correction (pre-seed n_papers=2 → call n_papers=3 to land a genuinely-new third paper) is the right structural pattern; the docstring at lines 249-256 explains the merge_insert upsert semantics that necessitated the change.
- The runbook extension is co-located in the SAME commit as the gate code (per spike-1 §3 rect F6 — no separate-tracker drift). S5 + S6 are introduced as distinct entries; the routing table at lines 137-142 makes the swallow-warning-presence decision explicit.
- The runbook's `### WAP gate RuntimeError at ingest time (e1)` heading + `### WAP gate failure triage` heading both produce valid GitHub-style anchors that match the in-doc references at lines 30 and 80.
- The implementation summary §Deviations transparently documents the three e1-time discoveries (circular import, m3 test restructuring, Mutation D fixture pattern) with the rationale for each — neither hides the deviations nor over-claims their scope.
- Tests run in ~1.16s wall-clock; m3 tests run in ~1.29s; neither adds a `requires_*` marker, so both land in the default `make test` set.

## Recommended rectification order

1. **F2 (audit-log gap)** — highest leverage. Wrap the gate in a try/finally so `_append_store_stats` lands, regardless of gate outcome. Closes the observability gap on the exact failure path the gate exists to surface.
2. **F3 (S5/S6 routing tag in error text)** — operator-actionability improvement that materially shortens MTTR on the 2am-page case the spike's rect F6 explicitly called out.
3. **F1 (Mutation A docstring fix + optional firing-point assertion)** — strengthens the regression guard and prevents future maintainer drift.
4. **F4 (style fix on the two new asserts)** — mechanical; do last if at all.

## Rectification status

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
