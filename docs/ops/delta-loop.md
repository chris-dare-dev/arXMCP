---
project: arxmcp
type: doc
tags:
- project/arxmcp
- type/doc
- authorship/agent-generated
authorship: agent-generated
---

# OAI-PMH delta-loop runbook (E11_S02)

**Use when:** the bulk-ingest cutover (E11_S05) has landed and the
operator needs nightly refresh of the four target arXiv subjects.
This runbook covers the operator workflow for the **OAI-PMH delta
harvester** that keeps the staging LanceDB current after the
initial 200K-paper backfill.

> **Cutover relationship.** This loop writes to the **staging**
> LanceDB at `var/arxmcp/index/lancedb-staging/`. The active
> `corpus-version.json` is NOT advanced by the delta loop. E11_S05's
> atomic cutover is the only mechanism that promotes staging →
> active. Until that runbook fires, the active server sees no
> changes.

> **No automatic server reload.** When a delta run completes, the
> MCP server continues serving its pinned `corpus_version`. A human
> or ops script must restart the server to pick up new content.
> Rationale (per `.claude/notes/06-mcp-server-design.md:346-354`):
> agents in the middle of a session expect index stability. **There
> is no touch file or filesystem signal at v1.**

---

## What the loop does

Once per night (02:00 local, via systemd timer or cron), the
delta loop:

1. Reads `var/arxmcp/ops/oai-pmh-state.json` to determine the
   harvest window. Default first run: yesterday. Resumes from the
   persisted token if the prior run crashed today; discards the
   token (it's expired) and re-harvests from the last harvest
   date if it crashed on a previous day.
2. Issues four OAI-PMH `ListRecords` calls — one per target set —
   against `https://oaipmh.arxiv.org/oai` with
   `metadataPrefix=arXivRaw`:
   - `math:math:AG`
   - `math:math:NT`
   - `physics:math-ph`
   - `physics:hep-th`
   Each call walks resumption tokens until the empty-token
   end-of-list signal. The state file is persisted after every
   page so a crash mid-harvest can resume.
3. Feeds every non-deleted paper id into
   `ingest.bulk_ingest.ingest_one_paper`, which runs the same
   ar5iv → LaTeXML → skip-and-log ladder as the bulk ingest.
   Writes go to the **staging** LanceDB
   (`var/arxmcp/index/lancedb-staging/`).
4. Logs `<header status="deleted">` records as withdrawn. **Does
   NOT delete the underlying chunks** (out of scope per the
   milestone brief).
5. Persists a successful-run summary back to the state file:
   `last_harvest_date`, `last_run_paper_count`,
   `last_run_duration_seconds`, etc.
6. Emits a non-zero exit code if any per-paper pipeline failed
   OR the run exceeded the 90-minute budget.

---

## Prerequisites

* **Python ≥3.11** with the project venv (`make bootstrap`).
* **`uv` on PATH** (the shell wrapper resolves it via
  `command -v uv`; override with `ARXMCP_UV=<absolute path>` if
  needed).
* **`flock`** binary — standard on Linux + macOS (`util-linux` on
  Linux, `brew install flock` on macOS).
* **Optional: `latexmlc`** for the LaTeXML fallback on ar5iv misses
  (same dependency as the bulk ingest).
* **The staging LanceDB MUST exist** — the delta loop writes into
  `var/arxmcp/index/lancedb-staging/` which is created by E11_S01's
  bulk ingest. Running the delta loop against a non-existent
  staging dataset will fail at the first paper.

> **Single-writer constraint** (per [ingest/store.py:44-55](../../ingest/store.py)).
> The `flock -n` reentrancy guard in `ops/cron/arxmcp-delta.sh`
> serializes concurrent runs **on the same host only**. Do NOT
> run the delta loop from two hosts targeting the same staging
> LanceDB (e.g. NFS-mounted `var/`): LanceDB's single-writer
> invariant is not NFS-safe and concurrent writes can corrupt the
> staging dataset.

---

## Smoke test before enabling the timer

```bash
# Dry-run prints the planned action per harvested record; no writes.
./ops/cron/arxmcp-delta.sh \
    --from=2026-05-13 --until=2026-05-13 \
    --state-file=var/arxmcp/ops/oai-pmh-state.smoke.json \
    --dry-run

# Smoke run against a single day; persists to a smoke state file.
./ops/cron/arxmcp-delta.sh \
    --from=2026-05-13 --until=2026-05-13 \
    --state-file=var/arxmcp/ops/oai-pmh-state.smoke.json
```

Inspect:
* `var/arxmcp/ops/oai-delta.log` — INFO records per paper.
* `var/arxmcp/ops/parser-failures/delta.jsonl` — per-paper
  failure rows (if any).
* `var/arxmcp/ops/oai-pmh-state.smoke.json` — final state.
* `var/arxmcp/index/lancedb-staging/` — staging dataset should
  have new chunks if any papers were actually ingested.

---

## Scheduling

### Linux (systemd, primary)

```bash
# Install the unit files (operator-substituted paths in the
# .service file MUST be edited first — replace /opt/arxmcp and
# the arxmcp user/group with your actual paths).
sudo cp ops/systemd/arxmcp-delta.service /etc/systemd/system/
sudo cp ops/systemd/arxmcp-delta.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now arxmcp-delta.timer

# Inspect:
systemctl list-timers arxmcp-delta.timer
journalctl -u arxmcp-delta.service -n 200
```

### macOS / Linux fallback (cron)

```bash
# Edit crontab (`crontab -e`) and add:
0 2 * * * /absolute/path/to/arxmcp/ops/cron/arxmcp-delta.sh
```

The shell wrapper acquires `flock -n var/arxmcp/ops/.delta.lock`
before invoking Python, so an overlapping run is rejected
immediately (exit 1) rather than racing on the staging LanceDB.

**Do not run on launchd.** The cron path is sufficient on macOS
and matches the precedent set by the E10_S04 drift detector.

---

## Latency budget

**90 minutes per run.** Typical daily delta is ~71–133 papers
across the four subjects (verified live as of 2026-05); the run
completes in ~15–20 minutes. The 90-minute budget is 4–6× headroom
for ar5iv CDN degradation, Monday spikes (~200–250 papers), or
future category expansion.

A run that exceeds 90 minutes triggers three signals:

1. **ERROR log** to stderr / journal:
   `oai_delta: run exceeded 5400s budget (elapsed=...); wrote sentinel to ...`
2. **Sentinel file** at `var/arxmcp/ops/delta-timeout.flag` —
   contains the JSON record `{elapsed_seconds, budget_seconds, ts}`.
3. **Non-zero exit code** — cron mailer / systemd `OnFailure=`
   pick this up.

The sentinel is cleared automatically on the next successful
in-budget run.

---

## Failure modes

### OAI-PMH endpoint 503

arXiv's TOS says "make no more than one request every three
seconds." The loop honors `POLITENESS_SLEEP_SECONDS = 3.0`
between page fetches; sustained 503s are unusual. If they
appear: pause the timer (`systemctl stop arxmcp-delta.timer`)
for an hour and resume.

### Resume token expired

arXiv resumption tokens expire daily. The state file persists
both `last_resumption_token` AND `last_harvest_date`. On restart:
- If `last_harvest_date == today`, the token is fresh — resume.
- If `last_harvest_date < today`, the token is stale — discard,
  re-harvest from `last_harvest_date` to yesterday.

This recovery is automatic; no operator action required.

### `ingest_one_paper` raises

The pipeline is documented in `docs/ops/bulk-ingest-runbook.md` —
the same failure modes apply (no parsed HTML, embedder failure,
chunker empty). Failed papers append to
`var/arxmcp/ops/parser-failures/delta.jsonl`. The loop continues.

### Disk full

The staging LanceDB and the embeddings sidecars grow linearly.
The daily delta footprint is small (~100 papers × ~30 chunks ×
~3 KB per embed = a few MB), but a long-running E11_S05 prep
window can accumulate. Free disk; re-run the failed window
manually.

---

## State file schema

`var/arxmcp/ops/oai-pmh-state.json`:

```json
{
  "last_harvest_date": "2026-05-14",
  "last_resumption_token": null,
  "last_successful_run_utc": "2026-05-15T02:14:37Z",
  "last_run_paper_count": 143,
  "last_run_duration_seconds": 847
}
```

`last_resumption_token` is non-null only mid-run; a successful
completion nulls it.

---

## See also

* [ingest/oai_delta.py](../../ingest/oai_delta.py) — the harvester module.
* [ingest/bulk_ingest.py](../../ingest/bulk_ingest.py) — the
  per-paper pipeline (`ingest_one_paper`) shared with the bulk
  ingest.
* [ops/cron/arxmcp-delta.sh](../../ops/cron/arxmcp-delta.sh) — the shell wrapper.
* [ops/systemd/arxmcp-delta.service](../../ops/systemd/arxmcp-delta.service) — systemd unit.
* [docs/ops/bulk-ingest-runbook.md](bulk-ingest-runbook.md) — the
  initial bulk-corpus ingest (E11_S01).
* [.claude/notes/03-ingestion-pipeline.md](../../.claude/notes/03-ingestion-pipeline.md) — design constitution for the ingest pipeline.
* [.claude/notes/06-mcp-server-design.md](../../.claude/notes/06-mcp-server-design.md) — server index-stability rule (lines 346-354).
* [.claude/notes/milestones/E11_S02/research-synthesis.md](../../.claude/notes/milestones/E11_S02/research-synthesis.md) — design rationale + D1-D15.
