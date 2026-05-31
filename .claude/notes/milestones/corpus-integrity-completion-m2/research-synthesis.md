# Research Synthesis — corpus-integrity-completion-m2

**Synthesizer:** main orchestrator session (NOT a sub-agent)
**Generated:** 2026-05-31
**Briefs merged:** `research-brief-1.md` (in-codebase structure + style), `research-brief-2.md` (failure-modes + operator UX)
**Verdict:** Auto-advance to Phase 2 / inline implementation. Briefs converged on the same implementation contract via independent paths. Two brief-vs-reality mismatches surfaced that the implementer MUST honor.

---

## 1. Implementation contract

Replace the m1 placeholder at `docs/ops/corpus-drift-runbook.md` (currently 78 LOC, scaffolding-flavored) with full canonical content. Add a one-line entry to `README.md` under the **existing `## Operations` section** (NOT a new `## Common tasks` section — see §2 below for the brief-vs-reality fix). No other files touched.

### Runbook file shape

Follow the AC's literal H2 ordering (Symptom → Quick triage → Likely causes → Remediation → Escalation). Within each section, use **H3 subheadings** to distinguish the two alerts where their triage diverges (a single 2am-pager-friendly file covering both, not one file per alert). The two alerts ship with different severities and different root-cause families, but they share the `runbook_url` annotation, and per Prometheus alerting practice (R2 §"Prometheus runbook_url") a single URL → single runbook landing page is the operator-correct pattern.

Lead each section with the most-paged scenario first. R2 confirmed via the alerting-receiver survey: `runbook_url` is rendered as a clickable link in Slack/PagerDuty/email — the operator has NOT yet diagnosed the problem when they click. The runbook is structurally a **2am-pager runbook**: brevity > completeness; commands at the top of each section; no scaffolding meta-commentary.

### README change

Add **one row** to the existing `## Operations` runbook table in `README.md`. R1 + R2 both verified end-to-end that **no `## Common tasks` section exists in `README.md` today** — the AC's literal wording is a documentation error. Use:

> `| corpus-drift-runbook.md | corpus-version.json marker drift or unindexed-rows alert | `make reconcile` (server-up + shared corpus; pass `NOTEBOOK=<slug>` for per-notebook). |`

(or whatever shape the existing operations table uses — implementer to mirror byte-for-byte). Do NOT create a new H2 section. CLAUDE.md §1 restricts README scope to "what the project does, how to use it, its layout, hard constraints"; an orphan "Common tasks" section would expand that scope unilaterally.

---

## 2. Brief-vs-reality mismatches (BOTH must be honored)

Both researchers independently surfaced two errors in the milestone brief's literal text. These are NOT open questions — both researchers verified by reading the codebase end-to-end and reached the same answer. The implementer treats these as RESOLVED:

### Mismatch A — "README's 'Common tasks' section" does not exist

R1 §"README 'Common tasks' section" (verbatim):
> "**The README does NOT have a 'Common tasks' section.** The sections are: `## What it does`, `## How to use it`, `## Operations`, `## Parser fidelity evaluation`, `## Importing the dashboard`, `## Repo layout`, `## Hard constraints`, `## License`."

R2 §"README 'Common tasks' section" (verbatim):
> "**DOES NOT EXIST.** The README has a '## Operations' section (line 65) with a runbook table, but NO '## Common tasks' section."

**Resolution:** Add `make reconcile` / corpus-drift-runbook reference as a new ROW in the existing `## Operations` table. Do NOT create an orphan `## Common tasks` H2.

### Mismatch B — `make ingest` is NOT a stub (CLAUDE.md §7 is stale)

R2 §"Design constitution files that apply" (verbatim):
> "CLAUDE.md §7 **stale entry**: 'make ingest is a stub that exits 1' — **THIS IS WRONG**. `ingest/bulk_ingest.py` EXISTS and is the real E11_S01 bulk ingest orchestrator. The Makefile `ingest:` target runs `$(PYTHON) -m ingest.bulk_ingest $(ARGS)`."

**Resolution:** The runbook's Remediation for `ArXMCPCorpusUnindexedRows` (re-run ingest to rebuild the HNSW index) references **`make ingest`** as a real working command. Do NOT add a "this is a stub" caveat. This also means a CLAUDE.md §7 stale-entry fix is implicitly out-of-scope for m2 (the roadmap Won't list deferred broader docs work) — flag for a future docs sweep.

---

## 3. Quoted load-bearing constraints

### From `tools/notebook_reconcile_marker.py` docstring (R1 + R2 cross-verified)

> "Server-down CLI fallback for 'make reconcile [NOTEBOOK=<slug>]' (onboarding-uplift-m3). Opens a notebook's LanceDB at the pinned marker version (MVCC snapshot — concurrent-ingest-safe), recounts chunk_count + distinct paper_ids, and atomically rewrites the marker."

### From `make reconcile` target (Makefile lines 560-589, R1)

> Routing logic:
> - Server up + no `NOTEBOOK=` → falls back to CLI (`tools.notebook_reconcile_marker --shared`)
> - Server up + `NOTEBOOK=<slug>` → POSTs to `/ui/api/notebooks/<slug>/reconcile-marker`
> - Server down (either) → runs `tools.notebook_reconcile_marker` CLI directly

**WRINKLE (R1):** The `ArXMCPCorpusCountRowsFailed` alert fires on the shared global corpus. There is NO REST endpoint for reconciling the shared corpus when the server is up — `make reconcile` always falls back to the CLI for the shared case. The runbook's Remediation must be explicit about this asymmetry.

### From `server/health.py:282-292` (R2 verbatim) — `/readyz` body shape

```python
return JSONResponse(
    status_code=200,
    content={
        "status": "ready",
        "chunk_count": None if startup_count < 0 else startup_count,
        "marker_chunk_count": resources.corpus_info.chunk_count,
        ...
    },
)
```

When `arxmcp_corpus_chunk_count_actual == -1`, `GET /readyz` returns `"chunk_count": null` (NOT -1). The Prometheus sentinel is only observable in `/metrics`, not the health endpoint. The runbook's Quick triage section MUST cite both surfaces so an operator can confirm the alarm from either `curl /readyz` OR `curl /metrics`.

### From `infra/prometheus/alerts.yml` inline comments (R2 verbatim)

> "The above-tolerance drift case (gauge >= 0 but differs from the marker) is already covered by `ArXMCPDegradedMode` via `DegradedState('chunk_count_diverged')`; no duplicate rule is added here."

> "The `-1` 'unknown' sentinel does NOT trip [`ArXMCPCorpusUnindexedRows`] (`-1 > 0` is false) — that case is covered by `ArXMCPDegradedMode`."

**Implication:** the corpus-drift runbook must explicitly cross-reference `docs/ops/failure-modes.md#degraded-modes` for the `ArXMCPDegradedMode`-handled cases (manually edited corpus-version.json, gauge=-1 for unindexed-rows API failure). The runbook's scope is narrow; misdirected operator action wastes pager-time.

---

## 4. Resolved decisions

Both briefs reached the same answer on every disputed point. Synthesizer records:

1. **Section structure (T1):** Follow AC literally (flat 5 H2 sections — Symptom / Quick triage / Likely causes / Remediation / Escalation). Within each section use H3 to distinguish the two alerts where their triage diverges. R2 proposed per-alert H2 nesting as an alternative but explicitly deferred to AC-literal; R1 recommended AC-literal directly. Aligned.
2. **Brevity vs completeness:** Brevity-first (R2). Pager-runbook style. Commands at the top. No scaffolding meta-commentary. Each section ≤ 15 lines preferred.
3. **README addition (Mismatch A):** Existing `## Operations` table, new row.
4. **`make ingest` reference (Mismatch B):** Real command, no stub caveat.
5. **Placeholder content reuse:** REMOVE the `**Status:** PLACEHOLDER`, the `## Why this is a placeholder` H2, the `.claude/notes/capability-scouts/...` link, all meta-commentary. REUSE the alert-name listing + the "Immediate triage" bullets as the seed for `## Symptom` and `## Quick triage`.
6. **IS2 closure (from m1 critique):** Yes, fold into `## Likely causes`. Cite the rebuild-window timing R1 surfaced: `_create_indices` is sub-minute on 50-paper seed; full 200K-paper ingest can take several hours; `for: 1h` filters post-full-ingest rebuild windows. R1 sourced this from `latexml-drift-runbook.md` §"Timing estimates."
7. **Style/format:** Follow `latexml-drift-runbook.md` (R1) — lead with `**Use when:**` callout, dense code blocks for CLI invocations, `## See also` at end with operator-facing links only (not internal `.claude/notes/` paths).

---

## 5. Failure scenarios the runbook MUST cover (R2 enumerated 7)

The implementer uses these as the content seed for `## Likely causes` and `## Remediation`. R2 grounded each in real CLI commands + observable gauge states:

| # | Scenario | Alert | Remediation tool | Critical detail |
|---|---|---|---|---|
| S1 | `count_rows()` raised at cold-corrupted LanceDB | CountRowsFailed (critical, for:10m) | restart server; `docs/ops/backup-restore.md` if persistent | `make reconcile` does NOT fix; reconcile only touches marker, not dataset |
| S2 | Ingest crashed mid-write, unindexed rows | UnindexedRows (warning, for:1h) | `make ingest ARGS=...` re-runs `_create_indices` | `make reconcile` does NOT fix; reconcile only touches marker, not index |
| S3 | Operator manually edited corpus-version.json | DegradedMode (NOT covered by m2 alerts) | `make reconcile` recounts + rewrites marker | Cross-ref `failure-modes.md#degraded-modes`; explain alert IS NOT one of m2's |
| S4 | Marker missing (cold-clone before first ingest) | NEITHER alert fires (gauge=0 not -1) | `make ingest` to create the first corpus version | Documented in alerts.yml inline comment |
| S5 | Concurrent `make ingest` + `make reconcile` race | None (safe) | No operator action needed | MVCC-pinned + idempotent; re-run reconcile post-ingest if alert re-fires |
| S6 | `make reconcile` returns exit 1 | None directly | Inspect malformed marker; restore from restic | Document both success + failure CLI output for operator pattern-matching |
| S7 | gauge=-1 persists across restarts | CountRowsFailed (after every restart 10m) | Verify `ARXMCP_LANCEDB_PATH`, check filesystem mount | Distinguishes "transient" from "config-broken" |

S3 and S4 are explicitly OUT-OF-SCOPE for the two m2 alerts but the runbook references them so the operator doesn't waste time. S5-S7 are operational nuances that prevent unnecessary escalation.

---

## 6. Open questions (none blocking)

All questions raised by both researchers were resolved by direct codebase inspection during the research phase. No outstanding ambiguity. The implementer can proceed.

R1 listed 3 nominal "open questions" but each carried a recommendation (Q1: use Operations table not Common tasks; Q2: remove placeholder scaffolding; Q3: yes, fold IS2 into Likely causes). R2 listed 2 "open questions" both of which were the same as R1's Q1/Q2 with the same recommendations. Synthesizer adopts all R1/R2 recommendations verbatim — no remaining ambiguity.

---

## 7. External writes the implementation will require

Both briefs agree: **NONE during implementation.** Modifications are local edits to:

- `docs/ops/corpus-drift-runbook.md` — full content replacement (existing file)
- `README.md` — one-row addition to the existing `## Operations` table

R1 listed `git push origin main` (Phase 4 only) for completeness; R2 listed empty. Same semantic answer — implementation-phase writes are zero. The state field is set to `[]`.

---

## 8. Orchestrator synthesis note

The two briefs reached near-identical conclusions on every decision point, with R1 stronger on runbook prose-style + cross-reference patterns and R2 stronger on failure-mode enumeration + operator-action grounding. Combined, they form a tight contract for the implementer.

Three resolved tensions are worth flagging in the implementation summary:
- **T1 — section structure** resolved AC-literal (flat 5 H2, H3 subheadings to distinguish alerts).
- **T2 — Remediation content** resolved by R2's stale-CLAUDE.md catch (use real `make ingest`).
- **T3 — README placement** resolved by both R1 + R2 confirming no `## Common tasks` section exists.

Implementation path: **inline** (orchestrator main session). Estimated effort: ~150 LOC Markdown (full canonical runbook content) + ~1 LOC README. Well under the 500 LOC / 5 files threshold for delegation. No specialist match. No novel architecture. No Python, YAML, or code change.

The 1-line README addition + the runbook content replacement together close KR-5 from the parent roadmap ("`docs/ops/corpus-drift-runbook.md` exists with `Symptom / Quick triage / Likely causes / Remediation / Escalation` sections; every new alert rule from KR-2 references it; an operator hitting any new alert can land on a runnable next step") fully — m1 satisfied the lower bar (the file exists; the runbook_url resolves); m2 satisfies the structural + content bar.
