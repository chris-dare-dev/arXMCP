# Exploration pipeline v0 — open-problem discovery (WS-E)

**Status:** v0 (stage2/arx-e1). Interim home per Stage-1 decision D3: the
exploration layer lives in arXMCP's `.claude/` until the third-repo
extraction triggers (below) fire.

The target outcome's exploration phase — find open problems in the
3-12-month literature; gather publications + bridging graduate textbooks
into a notebook — existed in neither repo (finding 06 §2.1.4) and ran as
hand-pasted ar5iv URL lists in Obsidian (finding 03 F-8). This pipeline
replaces that with a deterministic, LLM-free engine that **proposes** and an
operator who **confirms**. Power tool, not autopilot.

## The propose→confirm contract (AC-E.1)

- A run makes **zero mutating calls**: no notebook is created, nothing is
  ingested, no store is opened for write. Discovery fetches are
  agent-side/CLI (the server never fetches — loopback invariant 2).
- The run's only write is ONE file: an envelope-wrapped
  `arxmcp.bridge/proposed-notebook-manifest` (v0.2, `contracts/`) at the
  path the operator names with `--out`.
- Nothing proceeds until the operator reviews the manifest and runs the
  ingest lane themselves (§Operator confirm).
- Every proposed paper carries `source_citation` provenance (AC-E.4 — the
  GPT-5-Erdős lesson applied to discovery: no unsourced "this is open"
  claims). The contract schema REQUIRES it since manifest v0.2.

## Running a scan

Engine: `tools/exploration/` (windowing, atom_channel, graph_channel,
sources, textbooks, manifest, propose). Driver:

```sh
uv run python -m tools.exploration.propose \
  --topic-title "Bridgeland stability follow-ups" \
  --category math.AG \
  --months 6 \
  --keywords "stability conditions" \
  --anchors 2008.12019 \
  --sources-dir var/exploration/sources \
  --dedup-papers-file var/arxmcp/notebooks/bridgeland-stability/papers.txt \
  --email you@example.com \
  --out var/exploration/proposals/bridgeland-followups.json
```

Channel notes:

- **Atom** (`tools/_arxiv_api.py`, shipped): live scan sorted by
  submittedDate, window-filtered (AC-E.2). Offline mode via
  `--atom-fixture <saved-atom.xml>` — tests use this exclusively.
- **cite_neighbors** (`server/graph_queries.py`, wired — finding 211 R-A):
  probes around `--anchors`. Degrades exactly like the MCP handler:
  `absent` when `var/arxmcp/index/kuzu/` does not exist (the current state
  of this workstation), `unavailable` when unqueryable — the run proceeds
  on the other channels either way. Graph neighbors carry no dates, so a
  graph-only candidate is proposed only when its arXiv-id YYMM month lies
  entirely inside the window.
- **Open-problem sources**: local `*.snapshot.json` files (see below).
- **Dedup** (AC-E.2): `--dedup-papers-file` accepts a `papers.txt`-style
  list; already-curated papers are excluded and recorded in
  `payload.dedup.excluded_paper_ids`.

## Open-problem source snapshots (finding 04 key finding 5)

v0 consumes snapshots, not live feeds — refresh them agent-side, record
`retrieved_at`, and commit nothing (snapshots live under
`var/exploration/sources/`, gitignored via `var/`). Format:
`tools/exploration/sources.py` module docstring. Registered sources:

| Source | Kind | Refresh procedure (agent-side/CLI) |
|---|---|---|
| `formal-conjectures` | github-lean-corpus | Clone/pull https://github.com/google-deepmind/formal-conjectures ; extract per-conjecture `{id, title, statement, tags, arxiv_ids, url}` from the Lean sources' docstrings/comments into a snapshot. Apache-2.0 (code) / CC-BY 4.0 (content). |
| `emergentmind-open-problems` | api-snapshot | Query the EmergentMind public API's Open Problems surface (https://www.emergentmind.com); save items with their arXiv ids. Solo-maintained product — treat extractions as candidates needing verification; NEVER a hard dependency (finding 04 §2.1.3). |
| `randomstrasse101` | arxiv-list | Fetch the annual open-problem lists (arXiv 2504.20539 for 2024, 2603.29571 for 2025); extract problems + citations into a snapshot. |

A missing/empty snapshot dir simply skips the cross-reference channel; a
malformed snapshot fails the run with a named error (bad provenance is
worse than none).

## Operator confirm (after reviewing the manifest)

1. Read the manifest; prune papers/textbooks you don't want (it's JSON —
   edit it; `tools/exploration/manifest.py::conformance_violations` re-checks
   an edited file's window/provenance rules on the next validation).
2. Create the notebook: `/ui/` console or `uv run python -m tools.notebook_init <slug>`.
3. Fetch + ingest the confirmed papers:
   `uv run python -m tools.notebook_fetch <slug> <arxiv_id>...` then
   `uv run python -m tools.notebook_ingest <slug>` (see `tools/README.md`).
4. Textbooks go through the textbook lane
   (`tools/notebook_textbook_ingest`; PDFs need the separate MinerU venv —
   `docs/install.md`).
5. Keep the manifest file next to the run's notes — it is the provenance
   record for why this notebook exists.

## Tests

`tests/tools/test_exploration_pipeline.py` — manifest schema validation,
offline golden-path run on fixture Atom data, envelope conformance through
the C1 helpers (`tests/_bridge_helpers.py`), window/dedup/provenance rules,
graph-channel degradation, and a zero-mutation audit. One live Atom smoke +
the AC-E.3 retrospective backtest are opt-in:

```sh
ARXMCP_RUN_LIVE_DISCOVERY=1 uv run python -m pytest tests/tools/test_exploration_pipeline.py -k live
# Backtest additionally needs a curated papers list to measure recall against:
ARXMCP_RUN_LIVE_DISCOVERY=1 \
ARXMCP_BACKTEST_PAPERS_FILE=var/arxmcp/notebooks/bridgeland-stability/papers.txt \
ARXMCP_BACKTEST_CATEGORY=math.AG \
uv run python -m pytest tests/tools/test_exploration_pipeline.py -k backtest
```

## Third-repo extraction triggers (recorded verbatim; AC-E.5)

From `_pipeline/stage-1-discovery/synthesis/target-architecture.md` §4.2
("Create `math-research-orchestrator` when ANY of"):

> 1. Exploration or **proving orchestration** accumulates >~1,000 LOC of
>    non-prompt code or its own dependency set (a KAT-suite runner, campaign
>    scheduler, CAS harness beyond an MCP tool). Given workstream D's shape,
>    this is the trigger most likely to fire first — plan for it, don't
>    preempt it.
> 2. A second machine or remote execution surface enters the topology (also
>    the trigger that upgrades authz to OAuth 2.1 resource-server profile,
>    §6).
> 3. Bridge contracts gain consumers outside the two repos.
> 4. The run-ledger/campaign state outgrows per-repo `.claude/notes/`.

Portability by construction: every artifact this pipeline emits is
envelope-wrapped (`contracts/envelope.v1.schema.json`), so a future move to
`math-research-orchestrator` requires no format change (AC-E.5). LOC
accounting for trigger #1: `tools/exploration/` is non-prompt code — count
it (with WS-D's orchestration code) when reviewing the trigger:
`git ls-files tools/exploration | xargs wc -l`.

## Out of scope for v0 (deliberate)

- **Topic-selection automation** — v0 proposes problems + manifests for a
  topic the operator states; how topics are actually chosen is an open
  owner question (finding 03 §4 OQ1; orchestrator gate 6).
- **Standing crawlers/schedulers** — would immediately trip third-repo
  trigger #1's spirit and the "no standing infra" rule.
- **Semantic Scholar / OpenAlex channels** beyond what the
  notebook-paper-discovery Later lane already specifies.
