---
project: arxmcp
type: doc
tags:
- project/arxmcp
- type/doc
- authorship/agent-generated
authorship: agent-generated
---

# Parser-failure review workflow

The weekly parser-failures cron
(`ops/cron/arxmcp-parser-failures-weekly.sh`, fires Sunday 06:00
UTC) writes a markdown digest to
`var/arxmcp/ops/reports/parser-failures-<YYYY>-W<NN>.md`. This
runbook covers the operator's triage workflow.

## What's in the report

The report aggregates per-stage failure logs under
`var/arxmcp/ops/parser-failures/`:

| File | Format | Stage |
|---|---|---|
| `chunk.log` | TSV `paper_id\\tstatus\\televapsed_s\\treason` | Theorem-aware chunker (E02_S01) |
| `preamble.log` | TSV (same shape) | Preamble extraction (E02_S04) |
| `embed.log` | TSV (same shape) | BGE-M3 dual-column embedder (E03_S01) |
| `seed.log` | TSV (same shape) | Seed-corpus fetcher (E01_S01) |
| `delta.jsonl` | JSONL `{paper_id, failure_reason, timestamp}` | OAI-PMH delta loop (E11_S02) |
| `bulk.jsonl` | JSONL (same shape) | Bulk-ingest driver (E11_S03) |
| `re-embed.jsonl` | JSONL (same shape) | Re-embed driver (E11_S04) |

The reporter rolls them up into:

- Totals (overall failures + distinct papers affected)
- Per-stage counts
- Top-10 failure reasons per stage
- Top-10 failing papers per stage (so a single repeatedly-broken
  source tarball is visible)

## Triage decision tree

For each row in the per-stage "top 10 reasons" tables:

1. **Read the reason string.** Most reasons are short-format
   error messages from the producer module — find their meaning
   in the producer's source (e.g. `ingest/chunker.py`,
   `ingest/oai_delta.py`, `ingest/preamble.py`).
2. **Classify the failure root cause:**

   | Root cause | Symptom | Action |
   |---|---|---|
   | Broken arXiv source tarball | "LaTeXML crash", "missing main.tex", "incomplete archive" | **Skip:** add the `paper_id` to a `tools/seed-papers.txt`-style skiplist (or a `BAD_TARBALLS` set in `ingest/oai_delta.py`). |
   | LaTeXML version drift | "tokenizer mismatch", "MathML divergence" | Run `python -m ops.drift_check` → if it confirms drift, follow [latexml-drift-runbook.md](latexml-drift-runbook.md). |
   | Chunker bug (a real one) | a class of failures only this chunker version hits — confirmed by replaying against a prior commit | **Fix:** write a fixture-based regression test in `tests/fixtures/chunker/` and patch `ingest/chunker.py`. |
   | Embedder OOM / GPU issue | "CUDA out of memory", "model load failed" | Either reduce batch size or, on a single-workstation deploy, accept the failure rate. Tracked at [bulk-ingest-runbook.md](bulk-ingest-runbook.md). |
   | Network / upstream | "fetch 503", "OAI-PMH bad response" | Retry on the next delta run; if persistent across multiple weeks, file an upstream issue (arXiv operations). |
   | Filename / encoding edge | "non-ASCII paper_id", "unicode chars in path" | Patch the producer's sanitisation — these are usually easy 1-line fixes. |

## Must-act thresholds

The report itself does not raise alerts (Grafana ships in
E14_S09). But the operator should ACT this week when any of
these fires:

| Condition | Action |
|---|---|
| **> 5% of the week's ingested papers fail** | Pause the delta cron (`sudo systemctl disable arxmcp-delta.timer`) until root cause is found. Continued failures pollute the corpus. |
| **>= 10 failures with the same exact reason string** | Upstream investigation. The reason indicates a class of papers the parser doesn't handle; fix the parser before the failures accumulate. |
| **A single `paper_id` appears in the top-10 failing-papers table for 2 consecutive weeks** | Skip-list the paper. It's almost certainly a broken upstream source archive. |
| **`embed.log` failures appear in the report and the most-recent backup is older than 24 hours** | Halt the daily report cron and inspect the GPU/CPU memory state. Embedder failures + missing backup = "data at risk." |

## Manual run

```bash
# Default: report on the just-completed ISO week.
uv run python -m tools.parser_failures_report

# Backfill: report on a specific week.
uv run python -m tools.parser_failures_report --week 2026-W19

# Dry-run (prints to stdout, no file write):
uv run python -m tools.parser_failures_report --dry-run --week 2026-W19
```

### Known limitation: TSV rows without timestamps (F7 from E14_S04)

The four TSV producers (`chunker`, `preamble`, `embedder`,
`seed-fetcher`) do NOT emit a per-row timestamp — only the
JSONL producers (`oai-delta`, `bulk-ingest`, `re-embed`) do.
For TSV rows the reporter falls back to the **source file's
mtime** to determine "which week" — meaning every TSV row in
`chunk.log` (an append-only file) is bucketed into the week
the file was last appended-to, NOT the week the row was
written.

Practical consequence: the weekly report can re-surface the
same TSV row in N consecutive weeks until the operator
rotates the log. The JSONL stages don't have this issue.

Workarounds:

- Rotate the TSV logs after acting on a row:
  ```bash
  mv var/arxmcp/ops/parser-failures/chunk.log \
     var/arxmcp/ops/parser-failures/chunk.log.$(date -u +%Y%m%d)
  ```
- File a follow-up to add timestamps to the TSV producers (the
  shape would gain a 5th column; the reporter already tolerates
  that via `parts[:4]` slicing).

A future hardening pass moves the TSV producers to a 5-column
shape with timestamps; until then the mtime-fallback is the
documented best-effort.

## Cleaning up after triage

After acting on a row (fix landed, skiplist updated, etc.), no
explicit log-clearing is needed — the producer logs are append-
only and the report filters by ISO week. Next week's report
won't re-surface a fixed issue unless it re-occurs.

If a producer log grows unbounded (a year of ingestion), rotate
it:

```bash
mv var/arxmcp/ops/parser-failures/chunk.log \
   var/arxmcp/ops/parser-failures/chunk.log.$(date -u +%Y%m%d)
gzip var/arxmcp/ops/parser-failures/chunk.log.*
```

The reporter only reads the un-suffixed `chunk.log` and friends;
rotated files are ignored.

## See also

- [daily-ops-cadence.md](daily-ops-cadence.md) — full schedule
  + alert thresholds
- [delta-loop.md](delta-loop.md) — E11_S02 OAI-PMH cron
- [latexml-drift-runbook.md](latexml-drift-runbook.md) — when
  drift is suspected
- [bulk-ingest-runbook.md](bulk-ingest-runbook.md) — for embed.log
  failures during bulk loads
