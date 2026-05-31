# Research Brief — corpus-integrity-completion-m2

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-31T00:00:00Z

---

## In-codebase context

### Runbook structure survey

All four existing operator runbooks deviate from each other structurally. The AC
specifies `Symptom / Quick triage / Likely causes / Remediation / Escalation` — but
none of the four existing runbooks use exactly that 5-section skeleton verbatim. The
implementer must pick one style and apply it. Here is what each uses:

**`failure-modes.md`** — organized as a summary table then named per-failure-mode
anchors, each with `## Hosted-embedder outage`, `## LanceDB corruption`, etc.
Sub-sections within each mode are narrative paragraphs labeled `**What.**`,
`**Detection.**`, `**Recovery.**`. Prose style: terse operator-imperative. Code
blocks for recovery steps. Inline cross-references via relative links:
`[`docs/ops/backup-restore.md`](backup-restore.md) §"Restore drill"`. Ends with
a `## See also` list. No status header or "last updated" line.

**`backup-restore.md`** — uses a `**Use when:**` callout at the top, then a `## Scope`,
followed by `## First-time setup`, `## Scheduling`, etc. Organized around procedure
sections (numbered steps), code blocks dense. Cross-references relative links.
No `## Symptom` / `## Escalation` sections. Ends with `## See also` list.

**`drift-watchdog.md`** — uses a `**Use when:**` callout, then `## What the watchdog
does`, `## Threshold tuning`, `## Prerequisites`, `## Procedure` (Steps 1–4),
`## Scheduling`, `## E11_S05 cutover dependency`, `## State file schemas`,
`## Failure modes`, `## See also`. Dense code blocks. No `## Symptom` or
`## Escalation` header. Cross-references with relative links.

**`latexml-drift-runbook.md`** — uses a `**Use when:**` callout, then `## Recovery
procedure` (Steps 1–7 with code blocks), `## What this runbook does NOT cover`,
`## See also`. Most imperative of the four. Numbered step structure (`### Step N`).
No `## Symptom`, `## Quick triage`, `## Likely causes`, or `## Escalation` sections.

**Key structural finding:** the docs/ops/README.md documents the expected skeleton as
`Symptoms → Detection → Steps → Verification`, which differs from the AC's
`Symptom / Quick triage / Likely causes / Remediation / Escalation`. The AC sections
are reasonable and more granular. The implementer should follow the AC sections
(not the README's 4-part skeleton), because the AC is the contractual requirement.
The closest prose style to follow is `latexml-drift-runbook.md`: a leading `**Use
when:**` callout, numbered steps under `## Remediation`, code blocks for CLI invocations,
and a `## See also` at the end.

**Cross-reference pattern:** every runbook links to adjacent runbooks via relative links
(e.g. `[backup-restore.md](backup-restore.md)`). The corpus-drift runbook should link
to `backup-restore.md` (for the corruption path) and `failure-modes.md#lancedb-corruption`.

**Boilerplate:** no runbook has a "last updated" line or a status header. The
placeholder's `**Status:** PLACEHOLDER ...` header is the only instance of that
pattern anywhere in `docs/ops/` — it should be REMOVED in the canonical version.

### Placeholder content — reusable vs replace

The placeholder at `docs/ops/corpus-drift-runbook.md` contains:

1. **REUSABLE:** The alert names and descriptions under `## Alerts covered by this runbook`
   — `ArXMCPCorpusCountRowsFailed` and `ArXMCPCorpusUnindexedRows` with their
   gauge names and sentinel values. This content is accurate and belongs in
   the canonical `## Symptom` / `## Quick triage` sections.

2. **REUSABLE (as seed):** The "Immediate triage (m1 minimum)" bullets under each alert
   — these are the `## Quick triage` content. They name the correct gauge names,
   `server/health.py` paths, and the restore fallback pointer.

3. **REMOVE:** The `**Status:** PLACEHOLDER ...` header, the `## Why this is a
   placeholder` section, and the meta-commentary throughout. These are scaffolding
   artifacts that must not appear in the canonical operator-facing runbook.

4. **PARTIAL REMOVE / RESTRUCTURE:** The `## See also` section has good links but also
   links to `.claude/notes/capability-scouts/...` (an internal agent artifact, not
   operator-facing). Remove that one link in the canonical version.

### Tooling context: `tools/notebook_reconcile_marker.py`

The module docstring (verbatim): `"Server-down CLI fallback for 'make reconcile
[NOTEBOOK=<slug>]' (onboarding-uplift-m3). Opens a notebook's LanceDB at the pinned
marker version (MVCC snapshot — concurrent-ingest-safe), recounts chunk_count +
distinct paper_ids, and atomically rewrites the marker."`

Two modes:
- `uv run python -m tools.notebook_reconcile_marker <slug>` — per-notebook LanceDB
- `uv run python -m tools.notebook_reconcile_marker --shared` — global corpus at
  `var/arxmcp/index/lancedb/corpus-version.json`

Exit codes: `0` = success; `1` = missing marker, malformed marker, or LanceDB failure.

Output line format (verbatim from `_reconcile_one`):
`reconcile-marker [<label>]: version=<N> before=<X> chunks / <Y> papers after=<Z> chunks / <W> papers drift_resolved=<drift>`

### Tooling context: `make reconcile` (Makefile lines 560–591)

The target comment (verbatim): `"AC4 — recount the LanceDB at the marker's pinned version
and atomically rewrite corpus-version.json (m3 synthesis §3 D4 byte-identical idempotency:
re-runs against unchanged state are byte-identical, not just same-data). Pass
NOTEBOOK=<slug> for per-notebook; omit for the SHARED global corpus reconcile."`

Routing logic:
- Server up + no `NOTEBOOK=` → falls back to CLI (`tools.notebook_reconcile_marker --shared`)
- Server up + `NOTEBOOK=<slug>` → POSTs to `/ui/api/notebooks/<slug>/reconcile-marker`
- Server down (either) → runs `tools.notebook_reconcile_marker` CLI directly

**WRINKLE:** The `ArXMCPCorpusCountRowsFailed` alert fires on the SHARED global corpus
gauge (`arxmcp_corpus_chunk_count_actual == -1`). There is NO REST endpoint for
reconciling the shared global corpus when the server is up — `make reconcile` falls
back to the CLI tool in that case. The runbook's Remediation section must be explicit
about this asymmetry.

### `/readyz` body shape (load-bearing for the runbook)

From `server/health.py:283-295`, the ready-path JSON body is:
```json
{
  "status": "ready",
  "chunk_count": <int or null if -1>,
  "marker_chunk_count": <int from corpus-version.json>,
  "warm": {"embedder": bool, "lancedb": bool, "reranker": bool}
}
```
`chunk_count == null` indicates `startup_chunk_count == -1` (count_rows() failed).
`chunk_count != marker_chunk_count` indicates drift. This is the primary operator
diagnostic endpoint; the runbook should reference it under `## Quick triage`.

### Gauge definitions (health.py lines 105–134, verbatim)

`CORPUS_CHUNK_COUNT_ACTUAL` (`arxmcp_corpus_chunk_count_actual`): `"Live
chunks-table row count read once at startup. -1 = count unavailable. Equals
arxmcp_corpus_chunk_count_marker on the happy path; a gap indicates
corpus/marker divergence."`

`CORPUS_UNINDEXED_ROWS` (`arxmcp_corpus_unindexed_rows`): `"-1 = unavailable
(index API raised, or no ANN index). 0 = fully indexed (normal). >0 = abnormal:
ANN brute-forces those rows; re-run ingest to rebuild."`

### README "Common tasks" section

**The README does NOT have a "Common tasks" section.** The sections are:
`## What it does`, `## How to use it`, `## Operations`, `## Parser fidelity
evaluation`, `## Importing the dashboard`, `## Repo layout`, `## Hard constraints`,
`## License`. The `## Operations` section has a runbook table and the `## How to use
it` section has a code block with `make up`, `make test`, `make eval`, `make help`.

**CONFLICT WITH AC:** The milestone AC says `README.md "Common tasks" section gains
one line`. **There is no "Common tasks" section in README.md today.** This is
either (a) a misread of the README structure during roadmap authoring, or (b) an
implicit instruction to CREATE that section. See Open questions for the
recommendation.

---

## Prior decisions and lessons

**IS2 from m1 — explicitly deferred to m2.** The critique-merged.md records:
`"IS2 | LOW | deferred — for: 1h calibration comment lacks corpus-scale citation.
Comment-only nit; can be folded into m2 alongside the full runbook content (which
will likely cite the rebuild window in operator-actionable form)."` The `1h`
duration for `ArXMCPCorpusUnindexedRows` is 6× the next-longest `for:` value
in alerts.yml. The corpus-drift runbook's Likely Causes section is the natural
place to include the rebuild-window citation that justifies this. The m1 critic
was correct that this belongs here. Relevant seed-corpus data: from
`latexml-drift-runbook.md` timing table, the 50-paper seed corpus is ~5min for
equation re-extraction. Index rebuild via `_create_indices` (called synchronously
inside `write_chunks`) for 50 papers is sub-minute. The `1h` window is sized for
full-corpus (200K papers) scale where a full ingest + reindex can take ~10 hours.

**m1 three-commit triple confirmed at HEAD.** Commits `c58c19e` (feat), `951d3f3`
(rect), `5a8c7f0` (chore) are the m1 triple. The placeholder runbook file exists
at `docs/ops/corpus-drift-runbook.md` (shipped in `951d3f3`).

**KR-5 status.** The roadmap KR-5 states: `"docs/ops/corpus-drift-runbook.md exists
with Symptom / Quick triage / Likely causes / Remediation / Escalation sections;
every new alert rule from KR-2 references it; an operator hitting any new alert can
land on a runnable next step."` The placeholder satisfies the minimal "runnable next
step" clause — but NOT the structural `Symptom / Quick triage / Likely causes /
Remediation / Escalation` requirement. m2's job is closing the latter gap.

**Doc placement check.** `docs/ops/corpus-drift-runbook.md` is operator-facing
and already exists (placeholder). This is the pre-existing `docs/ops/` exception
documented in the roadmap Phase 1 Q3: `"docs/ops/ is a pre-existing exception
(4 runbook files already shipped... Extending the exception is operationally
consistent)."` No doc-placement violation.

**Banned patterns not applicable.** This milestone touches only Markdown files
(`docs/ops/corpus-drift-runbook.md`, `README.md`). No Python code, no MCP tools,
no `assert`, no middleware, no `anthropic` SDK. Tool-schema re-pinning not required.
`KMP_DUPLICATE_LIB_OK` guard not threatened. Kùzu path not touched.

---

## External sources

Prometheus alerting best practices (https://prometheus.io/docs/practices/alerting/)
has minimal guidance on runbook structure: `"Alerts should link to relevant consoles
and make it easy to figure out which component is at fault."` The page notes CamelCase
as the community convention for alert names (both new m1 rules follow this). No
specific runbook skeleton is mandated. The awesome-prometheus-alerts convention
(one runbook section per alert, or one runbook per alert group) is consistent with
the m1 approach: both `ArXMCPCorpusCountRowsFailed` and `ArXMCPCorpusUnindexedRows`
point to the SAME file, treated as two named sections within one runbook. This is the
correct pattern for closely-related corpus-integrity alerts sharing the same remediation
tool (`make reconcile`).

No MCP spec relevance (no tool surface change). No arXiv-specific concerns.

---

## Recommendation

**Replace the placeholder file with a full canonical runbook, and add a `make reconcile`
entry to the existing `## Operations` section of README.md (NOT a new "Common tasks"
section that doesn't exist).**

Specifically:

1. **Runbook file:** rewrite `docs/ops/corpus-drift-runbook.md` in full, removing the
   PLACEHOLDER header and "Why this is a placeholder" section entirely. Lead with
   a `**Use when:**` callout (matching `latexml-drift-runbook.md` style). Use the AC's
   five H2 sections: `## Symptom`, `## Quick triage`, `## Likely causes`,
   `## Remediation`, `## Escalation`. Add `## See also` at end (remove the
   `.claude/notes/capability-scouts/...` link as an internal artifact). Keep the alert
   names/descriptions as `## Symptom` content, the existing "Immediate triage" bullets
   as `## Quick triage` content (expanded), and populate the remaining three sections.
   The `## Remediation` section must document both the `make reconcile` and
   `uv run python -m tools.notebook_reconcile_marker` paths, including the asymmetry
   that the shared-corpus path always uses the CLI (no REST endpoint for it).

2. **README.md:** Add `make reconcile` to the EXISTING `## Operations` runbook table
   OR under the `## How to use it` → "Other entry points" line. Do NOT create a new
   section. The most natural placement is the runbook table (add a new row), OR as a
   new sentence appended to: `"Other entry points: make help, make test (ruff +
   pytest), make eval (retrieval-quality gate)."` The runbook table is cleaner
   because it already has the `corpus-drift-runbook.md` context pointer.

3. **IS2 closure:** in `## Likely causes`, cite the rebuild window: "For the 50-paper
   seed corpus, `_create_indices` completes in under 1 minute; for a full 200K-paper
   corpus, a complete ingest + reindex can take up to several hours. The `for: 1h`
   window on `ArXMCPCorpusUnindexedRows` filters transient post-ingest rebuild windows
   at full scale."

---

## Open questions

**(a) "Common tasks" section does not exist in README.md.** The AC says the section
"gains one line." This is MISLEADING — no such section exists. Recommendation: add
`make reconcile` to the existing `## Operations` runbook table as a new row. This
is functionally equivalent and cleaner than creating an orphan new section. The
implementer should treat the AC's "Common tasks section" as a documentation error
pointing at the `## Operations` section.

**(b) "Why this is a placeholder" and "See also" sections.** Recommendation: REMOVE
both entirely from the canonical version. The "Why this is a placeholder" section
is scaffolding that actively misleads operators post-m2. The "See also" section
should be rebuilt from scratch — remove the `.claude/notes/capability-scouts/...`
pointer (internal artifact) and include only operator-facing links.

**(c) IS2 — for: 1h rebuild-window citation.** Recommendation: YES, fold IS2 into
the `## Likely causes` section with the timing note above (50-paper seed ≈ sub-minute;
200K-paper full corpus ≈ several hours; `1h` covers transient post-full-ingest
rebuild windows). No separate follow-up needed; this is the natural m2 closure
for a deferred LOW finding. Evidence for the seed-corpus timing:
`latexml-drift-runbook.md` §"Timing estimates" table (50-paper step 3a+3b ≈ 5min,
step 3c ≈ 10s).

---

## External writes the implementation will require

The implementation produces only local file edits (`docs/ops/corpus-drift-runbook.md`
and `README.md`). Once Phase 4 authorizes it:

| Type | Target | Why |
|---|---|---|
| `git push origin main` | `main` branch | Deliver the three-commit triple after Phase 4 rect pass |

No PR creation, no ticket, no infra mutation, no third-party API call.
