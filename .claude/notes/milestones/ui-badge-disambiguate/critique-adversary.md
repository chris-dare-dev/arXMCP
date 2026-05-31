# Critique — ui-badge-disambiguate

**Critic:** adversary
**Generated:** 2026-05-30T00:00:00Z
**Commit range:** `ca2c274bb2fc4e1e130f896c4df7de3b6f2efea2..2df990c53c527c844e75a73fbbcd8b43fea0b858`
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: classification logic is correct, security/cache axes clean, MCP surface untouched, full status-endpoint suite (32 tests) green; ONE user-visible text regression to fix.
- 1 HIGH, 2 MEDIUM, 1 LOW. The HIGH is a cosmetic-but-user-visible glitch on the **common warn path**: the rebuilt badge text drops the space between the new label and the first pipe ("WARN| corpus v7" instead of "WARN | corpus v7").
- Highest-risk site: `server/routes/ui.py:254-255` — `summary = label + raw_summary[pipe:]` concatenates `label` directly onto a `"| corpus v..."` substring; the original space-before-pipe lives BEFORE `pipe`, so it is sliced off.
- Cache byte-stability (Axis 1) clean: BP1/tool-schema diff is empty (`git diff -- server/tools.py server/prompts.py` → no output).
- Security (Axis 3) clean: `_html.escape(summary)` runs with default `quote=True` (verified — `"` → `&quot;`), so the `title="..."` double-quote context is safe; `label` and `css` are constants from a closed enum; no user input flows into the fragment.
- MCP spec / no-fork / local-first (Axes 4, 5, 7) all clean — purely loopback UI fragment, no new deps, no submodules, no lifted code.
- Test surface (Axis 8) has a coverage gap: AC2 enumerated three ops keys (`backup:time`, `disk:utilization`, `process:uptime`) but no test exercises a `disk:utilization`-only or `process:uptime`-only warn at either the helper or endpoint layer (only `backup:time` is staged). Also: no test asserts the rendered text actually contains `"WARN | corpus v"` (with the space) — which is why F1 ships untested.
- Pre-existing failures called out by the implementer (drift-check + `test_cite_neighbors_wired`) verified unrelated to this diff (separate handlers / fixtures).

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Badge text drops the space before the first pipe ("WARN| corpus v7")

- **Severity:** HIGH
- **Source:** adversary
- **File:** `server/routes/ui.py:253-255`
- **What:** The summary reconstruction `summary = label + raw_summary[pipe:]` finds the index of the first `|` and slices from THAT character. The space-before-pipe in `compute_health_status`'s pre-rendered summary (`"DEGRADED | corpus v7 | 3 notebooks"`) lives at index `pipe - 1`, OUTSIDE the slice — so the rebuilt string omits it. Verified live with a Python trace:

  ```
  raw_summary = 'DEGRADED | corpus v7 | 3 notebooks'
  pipe = 9, raw_summary[9:] = '| corpus v7 | 3 notebooks'
  summary = 'WARN' + '| corpus v7 | 3 notebooks' = 'WARN| corpus v7 | 3 notebooks'
  ```

  The original summary was `"DEGRADED | corpus v7 | 3 notebooks"` (with a space before every pipe); the rebuilt summary is `"WARN| corpus v7 | 3 notebooks"` (or `"DEGRADED| corpus v7 | 3 notebooks"` for the retrieval-warn path) — missing the space before the FIRST pipe.
- **Why it matters:** This is rendered into both the badge text node AND the `title` attribute on every poll (every 10s) on every operator console page. The milestone's stated motivation is "operator experience" — shipping a visibly broken format string on the very common path the milestone "improves" is the worst kind of UX regression: the more visible, the more obviously wrong it looks. It is also a behaviour-bearing pre-fix→post-fix change in a property no test asserts on (see F3).
- **Proposed fix:** `server/routes/ui.py:254-255` — either slice from `pipe - 1` to preserve the leading space, OR (preferred, more robust to a future health.py whitespace tweak) split on the first `|`:

  ```python
  # Replace compute_health_status()'s leading READY/DEGRADED token, preserving
  # the " | corpus v..." trailer verbatim.
  _, _, rest = raw_summary.partition("|")
  summary = f"{label} | {rest.lstrip()}" if rest else label
  ```

  Or, equivalently, the original style with a corrected slice:

  ```python
  pipe = raw_summary.find("|")
  summary = f"{label} {raw_summary[pipe:]}" if pipe >= 0 else label
  ```

  (Note the inserted space between `{label}` and `{raw_summary[pipe:]}`.)
- **Regression guard:** Add to `tests/test_status_endpoint.py::TestStatusBadge`:

  ```python
  assert "WARN | corpus v" in r.text     # ops-only-warn path
  assert "DEGRADED | corpus v" in r.text # retrieval-warn path
  ```

  These assertions would fail on the current code and pass on the fix. The existing `test_badge_retrieval_warn_renders_degraded_label` already constructs a fixture with `version=7` and `_FakeStore(2)`, so a single new line per test suffices.

### F2 — `disk:utilization` warn-only and `process:uptime` warn-only paths are not regression-guarded

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_status_endpoint.py:393-465` (new `TestClassifyStatusBadge` class) + `tests/test_status_endpoint.py:346-363` (endpoint-level ops-warn test)
- **What:** AC2 in the milestone brief enumerates THREE ops-side keys: `backup:time`, `disk:utilization`, `process:uptime`. The endpoint test only stages a `backup:time` warn (by omitting `backup-status.json`). At the unit-helper layer, `test_warn_with_ops_only_keys_renders_ops_warn` (line 442) and `test_warn_with_malformed_entry_is_ignored` (line 454) put `backup:time` in `warn`; neither test sets `disk:utilization` OR `process:uptime` to `warn`. The retrieval-side parametrized loop (`test_warn_with_each_retrieval_key_renders_degraded`, line 421-429) is comprehensive; the ops-side has no symmetric loop. Concrete consequence: a future regression that special-cases `backup:time` differently from `disk:utilization` (or accidentally moves one into `_RETRIEVAL_CHECK_KEYS`) would be caught for the retrieval keys but not for the ops keys.
- **Why it matters:** The implementer's own `_RETRIEVAL_CHECK_KEYS` docstring (`server/routes/ui.py:158-168`) names the ops-side keys explicitly; the AC mirrored that list. A check-key membership change is exactly the kind of edit a future "add `parser:failures` to retrieval" milestone would attempt, and the asymmetric coverage means an accidental move (e.g. typo `disk:utilisation`) wouldn't trip a unit test. Cheap to close.
- **Proposed fix:** Add a parametrized ops-side loop mirroring the retrieval-side one. ~10 LOC:

  ```python
  def test_warn_with_each_ops_key_renders_ops_warn(self):
      """AC2 symmetric coverage: each ops-side key, in isolation, must
      produce WARN + ops-warn (no DEGRADED leakage)."""
      for key in ("backup:time", "disk:utilization", "process:uptime"):
          report = {"status": "warn", "checks": {key: [{"status": "warn"}]}}
          assert self._classify(report) == ("WARN", "ops-warn"), key
  ```

- **Regression guard:** the new test itself.

### F3 — No test asserts the badge's rendered TEXT format (only label-token presence)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_status_endpoint.py:314-385` (all three new endpoint tests)
- **What:** Every new endpoint-level test asserts either `"DEGRADED" in r.text` / `"WARN" in r.text` / `"DEGRADED" not in r.text`, plus class-modifier substrings. NONE assert on the full rendered phrase (`"DEGRADED | corpus v7 | 3 notebooks"` or the ops-only equivalent). This is why F1 — a visible space-before-pipe regression on a `version=7`/`_FakeStore(2)` fixture that does render those values — ships green.
- **Why it matters:** The milestone's stated goal is to improve operator clarity at-a-glance; the badge TEXT is the primary signal an operator reads. A test that pins only the label-prefix substring catches "did we pick the right label" but not "did we render a sensible string". Subsumed by F1's regression guard, but worth calling out separately because the underlying gap is "the test asserts the right label, not the right output".
- **Proposed fix:** When fixing F1, add the full-phrase assertions named in F1's regression guard. No new test files needed.
- **Regression guard:** see F1's regression guard.

### F4 — `_RETRIEVAL_CHECK_KEYS` and `compute_health_status` check-key set are coupled by manual convention, not by code

- **Severity:** LOW
- **Source:** adversary
- **File:** `server/routes/ui.py:160-168` (the docstring instructing future readers to keep this in lockstep with `server/health.py::compute_health_status`)
- **What:** The classification frozenset is hand-maintained against the set of check keys built in `server/health.py:319-455`. The cross-reference comment is the only enforcement. A future check added to `compute_health_status` but not to `_RETRIEVAL_CHECK_KEYS` defaults to ops-side `WARN` (the implementer noted this explicitly). Whether that is the right default is a judgment call: the milestone brief implicitly enumerated a closed list for ops too, so "unknown → ops/WARN" is arguably less safe than "unknown → DEGRADED" (which would loudly flag the operator that an unclassified check is warning).
- **Why it matters:** Defer-style LOW; the current set is small and changes are rare. The defensive non-dict fallback already does "schema drift → DEGRADED", so the implementer thought about the safety direction and explicitly chose ops-side for the unknown-key case to avoid noise. Acceptable as-is, but worth a note in the rectification status that future check-adders must consult both files.
- **Proposed fix:** None for this milestone. If a stronger guard is wanted later, add a unit test in `tests/test_status_endpoint.py` that introspects the set of check keys produced by `compute_health_status` on a warm fixture and asserts each is either in `_RETRIEVAL_CHECK_KEYS` or in an explicitly-named `_OPS_CHECK_KEYS` frozenset — partitioning makes the "unknown key" case throw at test time rather than silently drift.
- **Regression guard:** N/A (deferred).

## What was done well

- The classification helper is a **pure function** (`_classify_status_badge(report) -> (label, css)`) — synchronous, no I/O, no globals — which is why the new unit tests in `TestClassifyStatusBadge` can stay tight at the helper boundary instead of having to stand up a full `TestClient`. Clean abstraction.
- The schema-drift fallback at `server/routes/ui.py:204-207` is the correct safety direction: a non-dict `checks` value defaults to DEGRADED (loud), not WARN (soft). The inline comment names the failure mode being defended.
- The retrieval-side check-key parametrized loop (`test_warn_with_each_retrieval_key_renders_degraded`) iterates `_RETRIEVAL_CHECK_KEYS` directly rather than hard-coding the four key strings, so a future addition to the frozenset gets unit coverage automatically. (Same pattern wanted for the ops side — see F2.)
- The FM-1 mixed-warn regression guard (`test_badge_mixed_retrieval_and_ops_warn_prefers_degraded`) is the right test — retrieval-degradation must NOT be masked by an unrelated ops-side warn when both are non-pass.
- The CSS modifier name `--ops-warn` (not `--info` or `--notice`) keeps the warn-family ancestry visible in the class hierarchy — operators grep'ing CSS for "warn" still find it. Aligned-column formatting of the four rules is cosmetic but reads well.
- Cache discipline: `git diff` on `server/tools.py` and `server/prompts.py` is empty, confirming the BP1 / tool-schema surface is byte-stable. The implementer's claim in the summary is accurate.
- Security context discipline: `_html.escape(summary)` with default `quote=True` correctly escapes `"` so the `title="{safe}"` double-quote attribute context is safe; both the text-node and attribute use the SAME escaped string, so no second-context bug. Verified live.
- The `compute_health_status` boundary was respected — the badge replaces only its OWN label token and re-emits the rest of the upstream summary verbatim. Avoids forking the summary format string into two source files (which would be the higher-risk alternative).
- Pre-existing failures in `test_drift_check.py` and `test_cite_neighbors_wired` are correctly identified as unrelated to this diff. Verified: neither touches `server/routes/ui.py` or the badge surface.

## Recommended rectification order

1. **F1** — fix the missing space in `server/routes/ui.py:254-255` AND add the full-phrase assertions (this also closes F3). ≤ 5 LOC across the two files. Highest leverage: closes a user-visible bug AND a coverage gap with one edit.
2. **F2** — add the ops-side parametrized loop in `TestClassifyStatusBadge`. ≤ 10 LOC, no production-code change. Cheap regression guard for AC2 symmetry.
3. **F3** — folded into F1's regression guard. No separate fix.
4. **F4** — defer. Note for any future check-key addition milestone that BOTH `compute_health_status` AND `_RETRIEVAL_CHECK_KEYS` must move together.

## Rectification status

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
