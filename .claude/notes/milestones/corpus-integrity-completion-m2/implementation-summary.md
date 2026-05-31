# Implementation Summary — corpus-integrity-completion-m2

**One-line summary:** Replace the m1 placeholder `docs/ops/corpus-drift-runbook.md` with full canonical content (5-section AC structure + 7 grounded failure scenarios); add `corpus-drift-runbook.md` row to the README `## Operations` runbook table + the `docs/ops/README.md` runbook index.

**Commit range:** `5a8c7f0..HEAD` (single feat commit).

**Implementation path:** inline (orchestrator main session). ~210 LOC Markdown (runbook content) + 2 LOC table entries; well under the 500 LOC / 5 files delegation threshold.

## Acceptance criteria status

- [x] **AC-1:** `docs/ops/corpus-drift-runbook.md` exists with H2 sections `## Symptom`, `## Quick triage`, `## Likely causes`, `## Remediation`, `## Escalation`. **Met.** The 5 H2 sections are present in the literal order specified. Within each, H3 subheadings distinguish the two alerts where their triage diverges (per synthesis §1 + T1 resolution; the two alerts share one `runbook_url` so a single landing page is operator-correct).

- [x] **AC-2:** Remediation section references `make reconcile` (Makefile:560+) and `tools/notebook_reconcile_marker.py`. **Met.** The Remediation section includes a "Reference — `make reconcile`" block citing both the Makefile target (`Makefile:560-589` for routing logic) and the underlying CLI (`tools.notebook_reconcile_marker --shared` for the shared-corpus case, `tools/notebook_reconcile_marker.py` linked from §See also).

- [x] **AC-3:** `README.md` "Common tasks" section gains a line pointing to `make reconcile`. **MET with deliberate brief-vs-reality correction.** Both research briefs verified end-to-end that no `## Common tasks` section exists in `README.md` today (it has `## What it does`, `## How to use it`, `## Operations`, `## Repo layout`, `## Hard constraints`, `## License`). The AC's literal wording was a documentation error during roadmap authoring. Per synthesis §2 Mismatch A, the implementer added the entry as a NEW ROW in the existing `## Operations` runbook table (the natural home for runbook entries), AND added a corresponding row to `docs/ops/README.md` (the dedicated runbook index page that README's Operations section links to). Creating an orphan `## Common tasks` H2 would have violated CLAUDE.md §1's README scope restriction ("what the project does, how to use it, its layout, hard constraints").

- [x] **AC-4:** No new entries added to the 4 other pre-existing runbooks. **Met.** Only `docs/ops/corpus-drift-runbook.md` itself was rewritten; `docs/ops/README.md` gained one table row (the runbook index, not a runbook itself); `README.md` gained one table row. The 4 named runbooks (`failure-modes.md`, `backup-restore.md`, `drift-watchdog.md`, `latexml-drift-runbook.md`) are untouched.

## Decisions made beyond / around the literal AC

The synthesis flagged THREE brief-vs-reality mismatches; the implementation honors all three:

### Mismatch A — "Common tasks" → Operations table (R1 + R2 cross-verified)

The AC's literal "README 'Common tasks' section gains one line" is a documentation error — no such section exists. Added the runbook entry as a new row in the existing `## Operations` table per synthesis §2. Also extended `docs/ops/README.md` (the dedicated runbook index) — every other runbook listed in README is also listed there; not extending it would have left an asymmetry. This is the minimum-coherent reading of the AC's intent.

### Mismatch B — `make ingest` is NOT a stub (CLAUDE.md §7 is stale per R2)

The runbook's S2 Remediation references `make ingest` (and `make ingest ARGS=...`) as a real working command. CLAUDE.md §7 lists `make ingest` as a stub, but R2 verified that `ingest/bulk_ingest.py` ships as the real E11_S01 orchestrator and the Makefile target wraps it (`$(PYTHON) -m ingest.bulk_ingest $(ARGS)`). Updating CLAUDE.md §7 itself is out of scope for m2 (the Won't list deferred broader docs sweeps); the runbook content is correct as written and a future docs-sweep milestone should clean up the §7 stale entry.

### IS2 closure from m1 critique (folded into Likely causes per synthesis §4 D6)

The m1 critique's IS2 (LOW, deferred to m2) said the `for: 1h` calibration on `ArXMCPCorpusUnindexedRows` lacked a corpus-scale citation. The runbook's `## Likely causes` → S2 block now cites: "on the 50-paper seed corpus, `_create_indices` finishes in well under one minute; on a full 200K-paper corpus a complete ingest + reindex can take several hours. The `for: 1h` window on `ArXMCPCorpusUnindexedRows` is sized to filter post-full-ingest rebuild windows at full scale." Sourced from R1's reference to `latexml-drift-runbook.md` §"Timing estimates."

## Sections beyond the literal AC

- Added an explicit `**Use when:**` callout above the H2 sections (matches `latexml-drift-runbook.md` style per synthesis §7 D7).
- Added a `## See also` section at the end with links to alerts.yml, failure-modes.md, backup-restore.md, the CLI module, and `server/health.py`. Internal `.claude/notes/` paths from the m1 placeholder were removed (operator-facing only per R1's recommendation).
- The S3 + S4 "out-of-scope" callout names `ArXMCPDegradedMode` and `docs/ops/failure-modes.md#degraded-modes` explicitly so an operator with a misattributed alert doesn't waste pager-time.
- Documented the asymmetry that `make reconcile` always falls back to the CLI for the shared-corpus case (no REST endpoint for it when the server is up, per R1's "WRINKLE" finding).

## New / changed test paths

None. This milestone touches only Markdown files. The existing `tests/test_alerts_yaml.py` tests still validate the runbook_url annotation points at the now-canonical (no-longer-placeholder) `docs/ops/corpus-drift-runbook.md`. 8 passed, 1 skipped (promtool) — same count as post-m1.

## Project check status

- `ruff check .` — clean ("All checks passed!").
- `tests/test_alerts_yaml.py` — 8 passed, 1 skipped (the promtool skip is the canonical pattern per CLAUDE.md §4.5 — promtool not on PATH locally).
- Full suite (excluding opt-in markers + `tests/eval/`): the only failure is the same pre-existing `tests/test_tools_all.py::TestToolsSmoke::test_cite_neighbors_wired` local-env artifact that has been ignored throughout the corpus-integrity-completion pipeline. Unrelated to m2.

## External writes the orchestrator must authorize

**None.** All file changes are local. The eventual `git push origin main` after Phase 4 is a separate per-event authorization per CLAUDE.md §4.4 — not pre-authorized here. Synthesis §7 recorded `external_writes_required = []`.

## Deviations from the brief's design

Two **deliberate** deviations grounded in the research synthesis:

1. **README placement (AC-3) — `## Operations` table, not `## Common tasks` section.** Synthesis §2 Mismatch A. R1 + R2 cross-verified. Documented above.
2. **Per-alert H3 nesting within each AC H2 section.** Synthesis §4 D1. R2 explicitly raised the alternative (per-alert H2) and deferred to AC-literal; R1 recommended AC-literal directly. The H3 nesting preserves the AC's literal 5-section structure while making the two alerts' diverging triage paths discoverable. The "Symptom" and "Quick triage" sections use this; "Likely causes" uses numbered S1/S2/S7 subsections that map to the synthesis §5 failure-mode table; "Remediation" uses "Fix Sx —" H3 subsections.

## Adversary critic preparation

The adversary critic will fire (always-on per pipeline rules). The infra-safety critic will NOT fire — no infra/, .github/workflows/, Dockerfile, docker-compose*, or Makefile changes (the Makefile is unchanged; the runbook merely references the existing `make reconcile` target). Likely critique axes:

- Cache byte-stability: N/A (no MCP tool surface or prompt change).
- Math fidelity: N/A.
- Security: the runbook tells operators it's safe to attach `corpus-version.json` to a public issue (the file has no PII; just paper counts + chunker/embedder hashes per `.claude/notes/08-security-observability-ops.md`). The escalation section's `journalctl` command may leak hostnames in startup logs — flagged here so the adversary can confirm or push back.
- MCP spec compliance: N/A.
- Local-first: the runbook is consumed by an operator-deployed Prometheus/Alertmanager stack; no runtime cost to the server.
- Tier sequencing: m1 already shipped the alerts; m2 closes the runbook content gap; m3 (the integration test) is independent.
- No-fork: N/A.
- Test surface: no new tests required; the runbook is operator documentation. The existing `test_runbook_url_present_for_required_alerts` (added in m1 rect F1) already validates that both new alerts' `runbook_url` points at the canonical path of this file.

The deliberate AC-3 deviation (Operations table vs Common tasks section) may draw an adversary finding citing AC-literal compliance — the implementation summary above documents the synthesis-grounded reasoning so the critic can evaluate it on the merits rather than the surface.
