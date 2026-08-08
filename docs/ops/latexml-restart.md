# LaTeXML worker restart

A LaTeXML subprocess hung (subprocess timeout fired) or LaTeXML
output drift was detected. This runbook covers the in-process
restart of stuck workers and is separate from the version-drift
remediation runbook
([`latexml-drift-runbook.md`](latexml-drift-runbook.md)), which
handles the case where LaTeXML's output bytes changed under your
feet.

> Indexed from [`docs/ops/README.md`](README.md) #7.
> Related: `failure-modes.md` #5 — LaTeXML hang; E02 chunker
> ingestion pipeline; Threat 3 (`08-security-observability-ops.md`).

---

## Symptoms

- The ingest pipeline (one of `bulk-ingest`, `delta-loop`, or
  `notebook_ingest`) stalled on a single paper.
- `journalctl -u arxmcp-ingest` shows `subprocess.TimeoutExpired:
  Command '['latexmlc', ...]' timed out after 300 seconds`.
- An orphan `latexmlc` perl process is consuming CPU long after
  the parent ingest process should have killed it.

## Detection

- `var/arxmcp/ops/parser-failures/seed.log` (or `bulk.jsonl`)
  shows status `fail` with message starting `latexml TimeoutExpired`.
- `ps aux | grep latexmlc` lists processes with PPID = 1 (i.e.,
  reparented to init — the supervising ingest process died but the
  child was orphaned).
- `arxmcp_disk_free_bytes` may also be falling if a hung LaTeXML
  is writing temp files into `/tmp` and never cleaning up.

## Steps

1. **Reap any orphan `latexmlc` processes** (these are the
   reparented-to-init children whose supervisor died first; without
   reaping them, restarting the ingest pipeline will trip on
   `EADDRINUSE` for some intermediate temp file).

   ```bash
   # Find orphan latexmlc (PPID=1) processes.
   ps -eo pid,ppid,cmd | awk '$2 == 1 && /latexmlc/ {print $1}'

   # If any pids listed:
   kill -TERM <pid>
   # Give 5s, then force:
   sleep 5
   kill -KILL <pid>  # only if still listed
   ```

2. **Clean up `/tmp/latexml*` temp files** left behind by killed
   subprocesses. The ingest pipeline does NOT own these (LaTeXML
   creates them in `/tmp` directly).

   ```bash
   # Anything from the killed worker:
   find /tmp -maxdepth 1 -name 'latexml*' -mtime +0 -delete 2>/dev/null
   ```

3. **Identify the offending paper.** The hang is almost always
   reproducible on the same paper (a specific `.tex` file that
   triggers a LaTeXML pathological case — typically deep babel
   nesting or recursive macro expansion).

   ```bash
   # Last paper attempted before the timeout:
   tail -5 var/arxmcp/ops/parser-failures/seed.log
   # Or, for the bulk-ingest path:
   tail -5 var/arxmcp/ops/parser-failures/bulk.jsonl
   ```

4. **Quarantine the offending paper.** Add the paper_id to the
   parser-failures quarantine list so the ingest pipeline skips it
   on the next run:

   ```bash
   echo "<paper_id>" >> var/arxmcp/ops/parser-failures/quarantine.txt
   ```

   File a tracker entry in
   `.claude/notes/deferred-work-tracker.md` noting the failure
   mode (e.g., "babel-25.x csname-pattern") so the LaTeXML upstream
   fix can be tracked. Cross-reference
   `.claude/notes/milestones/E01_S01-S03/parser-compat-research.md`
   for the historical pattern.

5. **Resume the ingest pipeline.** The pipeline is idempotent per
   the F1 fix in E01_S01-S03 rect (the `already_parsed()` gate
   skips successfully-parsed papers); re-running picks up where
   the hang left off:

   ```bash
   # For the seed-corpus path:
   uv run python tools/fetch_seed.py

   # For the bulk-ingest path:
   make ingest
   ```

## Verification

```bash
# No orphan latexmlc processes:
ps -eo pid,ppid,cmd | awk '$2 == 1 && /latexmlc/'   # → empty

# Ingest log shows the quarantined paper is being skipped:
tail -5 var/arxmcp/ops/parser-failures/seed.log
# Look for: <paper_id>  skipped  0.0  quarantined

# Subsequent papers are parsing normally:
tail -20 var/arxmcp/ops/parser-failures/seed.log | grep -c "ok"
```

If the same paper hangs again on a fresh attempt (the quarantine
file got ignored), check the read path in
`tools/notebook_ingest.py` / `ingest/bulk_ingest.py` — the
quarantine-check is the first thing the per-paper loop should do
after reading the ID. Pre-existing bug in the pipeline if not.

If LaTeXML output *changed* on previously-working papers (rather
than hanging), that's a DIFFERENT failure mode — see
[`latexml-drift-runbook.md`](latexml-drift-runbook.md).
