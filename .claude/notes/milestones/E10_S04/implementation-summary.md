# E10_S04 — Implementation Summary

**One-line summary.** Daily-cron drift detector for LaTeXML
version bumps. Renders 5 hand-crafted `.tex` fixtures through
`latexmlc`, extracts `<math>` elements via BeautifulSoup, diffs
byte-for-byte against checked-in baselines, alerts on drift via
ERROR log + sentinel file + non-zero exit + Prometheus counter
increment. Closes the E10 epic.

**Commit range.** `1a52ff5..HEAD` (Phase-2 base `1a52ff5` →
implementation HEAD at commit time).

---

## Scope reminder

The synthesis narrowed scope from the brief in three dimensions:

1. **`tikz-cd` fixture dropped.** LaTeXML renders `tikz-cd` as
   SVG with embedded MathML labels in `<foreignObject>` — high-
   noise, not a stable drift signal. Replaced with
   `\begin{pmatrix}` matrix notation.
2. **Production Prometheus exposure deferred to E14.** The
   counter is defined in `server/metrics.py` and increments
   inside the cron process; cross-process `/metrics` exposure
   needs a sentinel-file reader hook at scrape time, deferred to
   the broader observability/ops milestone.
3. **Runbook references correct ingest modules** (`extract_equations`
   + `index_equations`), NOT the brief's non-existent
   `--rerender-all` flag.

---

## Acceptance criteria — status

- [x] **AC1** — drift-check against the current LaTeXML produces
      zero alerts. **Verified empirically**: the live
      `python -m ops.drift_check` returns `ok: 5 fixture(s)
      match baseline` after the baselines were captured via
      `--update-fixtures`. The `requires_latexmlc`-marked
      integration test
      [TestIntegrationRealLatexmlc::test_all_fixtures_match_baselines](tests/test_drift_check.py)
      asserts this in pytest.
- [x] **AC2** — modifying a fixture's expected MathML causes the
      script to exit non-zero. Verified by
      [TestCLI::test_cli_exits_one_on_drift](tests/test_drift_check.py)
      which mocks the actual side to mismatch and asserts the CLI
      returns 1 + writes the sentinel.
- [x] **AC3** — `arxmcp_latexml_drift_detected_total` increments
      when drift is detected. Verified by
      [TestCheckFixtureMocked::test_drift_increments_counter](tests/test_drift_check.py)
      which reads the counter's `._value.get()` directly.
- [x] **AC4** — runbook includes timing estimates for the
      50-paper seed corpus AND the 200K-paper full corpus.
      Verified by
      [TestRunbookContent::test_runbook_documents_timing_estimates](tests/test_drift_check.py)
      (loose phrase match on both "50-paper" and "200K"); a
      companion test pins the runbook references the correct
      ingest modules.

---

## Files added / changed

### New

- [ops/drift_check.py](ops/drift_check.py) — async-free pure
  Python: `render_fixture` (subprocess + tmpdir staging),
  `extract_canonical_mathml` (BS4 `find_all("math")` + `str(tag)`
  join), `check_fixture` / `check_all_fixtures`,
  `update_fixtures`, sentinel write/clear helpers, full
  argparse-driven `_cli`.
- [ops/__init__.py](ops/__init__.py) — empty (marker for Python
  package discovery so `python -m ops.drift_check` works).
- [ops/cron/latexml-drift-check.sh](ops/cron/latexml-drift-check.sh)
  — bash entry point for the daily cron. Resolves the repo
  root from `${BASH_SOURCE[0]}`, exec's
  `uv run python -m ops.drift_check "$@"`. Operator can pass
  `--update-fixtures` through directly.
- [tests/fixtures/latexml-drift/*.tex](tests/fixtures/latexml-drift/)
  — 5 hand-crafted standalone `.tex` files: `frac.tex`,
  `integral.tex`, `sum.tex`, `align.tex`, `pmatrix.tex`.
- [tests/fixtures/latexml-drift/*.expected.mathml](tests/fixtures/latexml-drift/)
  — 5 baseline files captured via `latexmlc 0.8.8` on macOS
  arm64. Regenerated via `python -m ops.drift_check --update-fixtures`.
- [tests/fixtures/latexml-drift/README.md](tests/fixtures/latexml-drift/README.md)
  — dual-role documentation (pytest fixtures + cron reference data).
- [tests/test_drift_check.py](tests/test_drift_check.py) — 22
  tests: list_fixtures, expected_path_for, MathML extraction,
  mocked drift logic (counter increment, exit codes), sentinel
  file, CLI, runbook content (AC4), missing-`latexmlc` error
  handling, integration tests marked `requires_latexmlc`.
- [docs/ops/latexml-drift-runbook.md](docs/ops/latexml-drift-runbook.md)
  — 7-step operator recovery procedure with explicit timing
  estimates (50-paper seed and 200K-paper Tier-4).
- [.claude/docs/ops/cron-jobs.md](.claude/docs/ops/cron-jobs.md)
  — internal registry of automated jobs (this one + placeholders
  for E14 future jobs).

### Changed

- [server/metrics.py](server/metrics.py) — added
  `LATEXML_DRIFT_DETECTED_COUNTER` (counter, label: `fixture`)
  and `reset_drift_metrics_for_tests()`. Exported in `__all__`.
- [README.md](README.md) — added an "Operations" section linking
  `docs/ops/`. Minimal — just the one paragraph + link, satisfying
  the doc-layout rule's "operator-facing AND linked from root
  README" exception (the rule's clause that lets us put runbooks
  in `docs/` at all).
- [pyproject.toml](pyproject.toml) — registered the
  `requires_latexmlc` pytest marker (mirrors `requires_model`).

NOT touched: `server/tools.py`, `server/handlers/`,
`server/retrieval/`, `tests/test_server_tool_schema.py`,
`tests/test_prompts.py`, `server/schemas/search_papers_result.json`.
**No `TOOL_SCHEMA_VERSION` bump** — the drift detector adds no
tool surface.

---

## Design decisions implemented (synthesis D1–D14)

1. **D1 Drift baseline = checked-in fixtures.** Equations table
   is empty in seed corpus; fixtures are the source of truth.
2. **D2 Extracted-`<math>` diff, byte-for-byte.** Researcher 2's
   empirical finding: raw HTML is NOT byte-stable (timestamp
   noise in HTML comment + visible `<div class="ltx_page_logo">`).
   BS4 extraction + `str(tag)` IS stable.
3. **D3 5 fixtures with `pmatrix` replacing `tikz-cd`.** Display
   math only.
4. **D4 Bash wrapper around Python.** All logic in Python.
5. **D5 `ops/drift_check.py`** as the entry point.
6. **D6 Counter in-process; production exposure deferred to E14.**
7. **D7 Mock-based default tests + `requires_latexmlc` integration.**
8. **D8 `--update-fixtures` CLI flag** for the operator-rebaseline
   workflow.
9. **D9 15s per-fixture timeout.** Empirically `latexmlc` runs in
   <1s on these standalone fixtures.
10. **D10 No new deps.**
11. **D11 Runbook references correct ingest modules.**
12. **D12 README "Operations" section** added, satisfying the
    doc-layout rule's exception for `docs/ops/`.
13. **D13 Cron registry under `.claude/docs/ops/`** (internal).
14. **D14 Sentinel under `var/arxmcp/ops/`.** Follows the existing
    `parser-failures` precedent.

---

## Forced cross-file changes (all landed)

- No `TOOL_SCHEMA_VERSION` bump (no tool surface change).
- No hash repins.
- New `requires_latexmlc` marker registered.
- New top-level `ops/` package (with `__init__.py`).
- New `docs/ops/` directory + first runbook + README link.
- New `.claude/docs/ops/` directory + cron registry.

---

## Test count delta

| Metric | Before | After |
|---|---|---|
| Tests passing | 1449 | 1471 |
| Tests skipped | 4 | 4 |
| Tests failing | 0 | 0 |
| Ruff status | clean | clean |

+22 new tests in `tests/test_drift_check.py`, including the
`requires_latexmlc`-marked integration tests that ran the real
`latexmlc` binary locally during this session.

---

## External writes required

**None.** All writes are local:

```
| type | target | why |
|---|---|---|
| local | ops/, ops/cron/ | new package dirs |
| local | tests/fixtures/latexml-drift/*.{tex,expected.mathml,README.md} | fixtures |
| local | docs/ops/latexml-drift-runbook.md | operator procedure |
| local | .claude/docs/ops/cron-jobs.md | internal registry |
| local | var/arxmcp/ops/drift-detected.flag | sentinel (runtime, not committed) |
```

No `pyproject.toml` dep changes. No `uv lock` regeneration. No
external API calls.

---

## Operator setup (post-merge)

To activate the daily cron:

```bash
chmod +x ops/cron/latexml-drift-check.sh
# Add to crontab:
crontab -e
# 30 2 * * *  /Users/chris.dare/Personal/SourceCode/arXMCP/ops/cron/latexml-drift-check.sh
```

Verify manually:

```bash
ops/cron/latexml-drift-check.sh
# ok: 5 fixture(s) match baseline
```

On drift detection, follow
[docs/ops/latexml-drift-runbook.md](docs/ops/latexml-drift-runbook.md).

---

## Deviations from the brief (with rationale)

1. **`tikz-cd` fixture dropped, `pmatrix` added.** LaTeXML
   produces SVG (not MathML) for `tikz-cd`; the `<math>` walk
   would pick up only label fragments inside `<foreignObject>`.
   Synthesis D3.
2. **`docs/ops/cron-jobs.md` moved to `.claude/docs/ops/cron-jobs.md`.**
   The cron registry is internal coordination; the runbook is
   the operator-facing piece. Synthesis §2 split.
3. **Production Prometheus exposure deferred to E14.** The
   counter is defined and increments inside the cron's lifetime;
   the cross-process `/metrics` reader is E14 scope. The v1
   operator signal is stderr ERROR + sentinel file + non-zero
   exit. Synthesis D6.
4. **Runbook updates the brief's "`--rerender-all`" flag** to
   reference the actual existing modules
   (`ingest.extract_equations` + `ingest.index_equations`). The
   brief's flag doesn't exist. Researcher 1 verified.
5. **No `ops/latexml-version.txt` initial commit.** This file is
   operator-managed (rewritten on every upgrade); the runbook
   instructs the operator to create it on first drift event.
   Committing an initial value would create a misleading "the
   project ships pinned to X" signal.

These deviations are documented in the synthesis and the
rectifier should not "fix" them without explicit user direction.
