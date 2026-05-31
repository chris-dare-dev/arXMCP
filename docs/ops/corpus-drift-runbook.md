# Corpus-drift runbook

**Use when:** the server-side `arxmcp_corpus_chunk_count_actual`
or `arxmcp_corpus_unindexed_rows` Prometheus gauges trigger one of
the two corpus-integrity alerts shipped in
`infra/prometheus/alerts.yml`:

- `ArXMCPCorpusCountRowsFailed` (severity: critical, for: 10m) —
  fires when `arxmcp_corpus_chunk_count_actual == -1`, the
  sentinel set by `server/health.py` when
  `chunks_table.count_rows()` raised at startup.
- `ArXMCPCorpusUnindexedRows` (severity: warning, for: 1h) — fires
  when `arxmcp_corpus_unindexed_rows > 0`, indicating one or more
  rows are committed to the chunks table without a HNSW index
  rebuild.

This runbook does **not** cover above-tolerance marker drift
(gauge ≥ 0 but ≠ marker). That case fires `ArXMCPDegradedMode` with
`reason="chunk_count_diverged"` and is handled by
[`failure-modes.md`](failure-modes.md) (no `#degraded-modes` anchor
exists today — read the file's top-level H2 list to find the
relevant section; corrected per m2 rect F2).

---

## Symptom

### ArXMCPCorpusCountRowsFailed (critical)

The Prometheus gauge `arxmcp_corpus_chunk_count_actual` reports
`-1` for ≥ 10 minutes. `GET /readyz` returns
`"chunk_count": null` (the `-1` sentinel is normalized to JSON
`null`; `marker_chunk_count` still reports the corpus-version.json
value). The server is **serving stale-and-unverifiable retrieval**
— the marker is intact but the live row count cannot be confirmed.

### ArXMCPCorpusUnindexedRows (warning)

The Prometheus gauge `arxmcp_corpus_unindexed_rows` reports a
value > 0 for ≥ 1 hour. `GET /readyz` returns
`"status": "ready"` (correctness is preserved). ANN queries
silently **brute-force the unindexed rows** — retrieval is correct
but latency on `search_papers` grows linearly with the unindexed
count.

---

## Quick triage

Confirm the alert in ≤ 60 seconds before opening Remediation.

### Both alerts — first 3 commands

```bash
# 1. Confirm the gauge values from Prometheus directly.
curl -s http://127.0.0.1:7733/metrics | grep -E '^arxmcp_corpus_(chunk_count_actual|unindexed_rows) '

# 2. Confirm via the /readyz health surface.
curl -s http://127.0.0.1:7733/readyz | jq '{
    status, chunk_count, marker_chunk_count
}'

# 3. Confirm the marker file is intact (relevant for BOTH alerts —
#    a missing/malformed marker can cascade into either gauge).
cat var/arxmcp/index/lancedb/corpus-version.json
```

Expected on the happy path: `arxmcp_corpus_chunk_count_actual` ≥ 0,
`arxmcp_corpus_unindexed_rows == 0`, `chunk_count ==
marker_chunk_count`, marker JSON parses cleanly. Any deviation
narrows the cause.

### Quick checks per alert

| Alert | If `arxmcp_*` gauge reads | Then go to |
|---|---|---|
| CountRowsFailed | `-1` | [Likely causes → S1 / S7](#likely-causes) |
| UnindexedRows | `> 0` and gauge has been steady | [Likely causes → S2](#likely-causes) |

---

## Likely causes

Numbered by the synthesis failure-mode table; remediation steps
under [Remediation](#remediation) reference these IDs.

### S1 — `count_rows()` raised on a cold-corrupted LanceDB

The chunks-table dataset is present but the underlying Lance fragment
metadata is corrupt or the path is unreadable. `count_rows()` raises
`lance.LanceError` or `OSError`; `server/health.py` catches it and
sets `startup_chunk_count = -1`. Persists across server restarts as
long as the dataset is still broken.

### S2 — Ingest crashed mid-write, leaving unindexed rows

`ingest/store.py::write_chunks` committed row writes but
`_create_indices` raised before completing the HNSW rebuild. The
gauge is set once at startup from `startup_unindexed_rows`; the
condition persists until the next successful ingest run completes
its synchronous `_create_indices` call.

**Rebuild-window calibration (closes m1 IS2; corrected per m2 rect
F6):** `_create_indices` runs synchronously inside `write_chunks` —
it builds the HNSW index over every freshly committed row before
`write_chunks` returns. On the 50-paper seed corpus that bulk index
build completes in well under one minute; on a full 200K-paper
corpus an end-to-end ingest + index-build can take several hours
under HNSW defaults (`M=16`, `efConstruction=200`). The `for: 1h`
window on `ArXMCPCorpusUnindexedRows` is the rough upper bound on
the index-build wall-clock at full scale; the alert fires only when
an unindexed-rows condition PERSISTS beyond a single normal-ingest
window — i.e. an actual crash mid-write, not a transient post-ingest
rebuild in flight.

### S7 — `arxmcp_corpus_chunk_count_actual` persists at `-1` across restarts

After confirming S1 is NOT the cause, the most common root is a
filesystem-mount or container-volume misconfiguration: the
`ARXMCP_LANCEDB_PATH` env var points at a path that no longer
exists or is unreadable. Server logs `Resources.startup FM-2` on
every restart. Distinguishes from S1 because the dataset itself is
fine — just unreachable from the running server.

### Out of scope for these alerts

- **S3 — Operator manually edited or deleted corpus-version.json.**
  Triggers `DegradedState('chunk_count_diverged')` →
  `ArXMCPDegradedMode`, **not** one of this runbook's alerts. Fix
  via `make reconcile`; see
  [`failure-modes.md`](failure-modes.md) (`#degraded-modes` anchor
  not present; the LanceDB-corruption + degraded-mode discussion
  spans multiple H2 sections, corrected per m2 rect F2).
- **S4 — Cold-clone deployment before first ingest.** An empty
  chunks-table returns `count_rows() = 0` (not `-1`), so
  `ArXMCPCorpusCountRowsFailed` does **not** fire. Fix via
  `make ingest`.

---

## Remediation

Per-alert procedures. Both reference the existing
`tools/notebook_reconcile_marker.py` CLI and the `make reconcile` /
`make ingest` Makefile targets.

### Fix S1 / S7 — `count_rows()` failure

`make reconcile` does **not** fix this — reconcile operates on the
marker file only, not on a broken Lance dataset.

```bash
# 1. Stop the server cleanly.
#    No `make down` target exists today (m2 rect F1); use pkill on
#    the main entrypoint, or whatever systemd/launchd unit your
#    deployment harness uses.
pkill -f 'python -m server.main'

# 2. Inspect the dataset directory. The version-N subdirectory must
#    be a valid Lance fragment tree (manifests, data, indices/).
ls -la var/arxmcp/index/lancedb/_versions/
cat var/arxmcp/index/lancedb/corpus-version.json  # confirm intact

# 3a. (S1) If the dataset shows manifest corruption, restore from
#     the latest restic snapshot.
#     See docs/ops/backup-restore.md §"Restore drill".

# 3b. (S7) If the dataset looks fine on disk but the path is
#     unreadable from the server process, verify env + permissions.
echo $ARXMCP_LANCEDB_PATH                      # is it set right?
ls -la "$ARXMCP_LANCEDB_PATH"                  # readable?
# In a container: confirm the volume mount is intact and the UID
# inside the container can read the host path.

# 4. Bring the server back up. Successful startup clears the cached
#    -1 from the gauge (which is read once at startup — see the
#    `CORPUS_CHUNK_COUNT_ACTUAL` docstring in server/health.py;
#    m2 rect F5: dropped fragile line-number references).
make up

# 5. Re-trigger the triage commands to confirm.
curl -s http://127.0.0.1:7733/readyz | jq '.chunk_count'
# Expected: integer ≥ 0; null means -1 is still set.
```

If `chunk_count` remains `null` after a restart against a known-good
dataset, escalate.

### Fix S2 — unindexed rows

`make reconcile` does **not** fix this either — reconcile rewrites
the marker, not the index.

```bash
# 1. Re-run the bulk ingest orchestrator. _create_indices runs
#    synchronously inside write_chunks; a successful run rebuilds
#    the HNSW index for every committed row.
make ingest                            # full bulk re-run
# or scope to the last batch only:
# make ingest ARGS="--paper-ids-file=<last-batch.txt>"

# 2. Restart the server so the startup_unindexed_rows gauge is
#    re-read. The gauge is cached at startup (see the
#    `CORPUS_UNINDEXED_ROWS` docstring in server/health.py);
#    without a restart the alert continues firing even after the
#    index rebuilds.
#    (m2 rect F1: no `make down` target exists; pkill the main
#    entrypoint then `make up`.)
pkill -f 'python -m server.main' && make up

# 3. Confirm the gauge cleared.
curl -s http://127.0.0.1:7733/metrics | grep arxmcp_corpus_unindexed_rows
# Expected: arxmcp_corpus_unindexed_rows 0
```

### Reference — `make reconcile` (in case S3 was the real symptom)

`make reconcile` recounts the LanceDB at the version pinned in
`corpus-version.json` and atomically rewrites the marker fields if
they drifted from the live row count. It is the right tool for
**marker drift** (gauge ≥ 0 but ≠ marker), not for the two alerts
this runbook covers.

```bash
# Shared global corpus (the case ArXMCPDegradedMode covers most
# commonly). When the server is up there is no REST endpoint for
# the shared corpus — `make reconcile` always falls back to the
# `tools.notebook_reconcile_marker --shared` CLI here. This is
# expected behavior; see Makefile:560-589 for the routing logic.
make reconcile

# Per-notebook corpus (only relevant if a notebook is the source
# of the alert; the m2 alerts fire on the shared corpus gauges):
make reconcile NOTEBOOK=my-notebook-slug
```

Expected stdout on success:

```
reconcile-marker [shared]: version=42 before=10298 chunks / 217 papers
  after=10298 chunks / 217 papers drift_resolved=0
```

Exit code `1` + stderr `ERROR: ...` means the marker was malformed
or the LanceDB recount itself raised — see [Escalation](#escalation).

---

## Escalation

If the Remediation procedure does not clear the alert within 30
minutes (or `make reconcile` exits 1 unrecoverably):

1. **Capture state for the issue tracker.** Snapshot the marker file,
   the relevant gauge readings, and the most recent server-startup
   log lines (the `journalctl` form below assumes a systemd unit
   `arxmcp-server.service`; if your deployment uses a different
   process manager, substitute its equivalent — e.g.
   `docker logs arxmcp-server --since 30m > /tmp/startup.log`):
   ```bash
   cat var/arxmcp/index/lancedb/corpus-version.json > /tmp/marker.json
   curl -s http://127.0.0.1:7733/metrics | grep ^arxmcp_corpus_ > /tmp/gauges.txt
   journalctl -u arxmcp-server.service --since '30 minutes ago' > /tmp/startup.log
   ```
   The marker file is **not** sensitive (paper counts + version
   integer + chunker/embedder hashes); it can be attached to a
   public issue per the threat model in
   [`.claude/notes/08-security-observability-ops.md`](../../.claude/notes/08-security-observability-ops.md).

   > **Before attaching `/tmp/startup.log` to a public issue (m2
   > rect F3):** if the operator raised log verbosity to DEBUG
   > during troubleshooting, the 30-minute slice may contain full
   > user-submitted MCP query strings and partial chunk bodies —
   > sensitive per
   > [`.claude/notes/08-security-observability-ops.md`](../../.claude/notes/08-security-observability-ops.md)
   > §Logging. Scan the file for `DEBUG` entries containing
   > `query=`, `chunk_body=`, or absolute home-directory paths
   > (`/Users/...`, `/home/...`). Redact or attach to a private
   > channel if found. The marker + gauges captures above carry no
   > equivalent sensitivity.
2. **Restore from backup.** If the Lance dataset is genuinely
   corrupt, follow
   [`backup-restore.md`](backup-restore.md) §"Restore drill" to
   roll back to the most recent restic snapshot.
3. **Open an issue** at
   <https://github.com/chris-dare-dev/arXMCP/issues> labeled
   `ops/corpus-integrity` with the captured state and the
   commands already attempted.

---

## See also

- [`infra/prometheus/alerts.yml`](../../infra/prometheus/alerts.yml)
  — the rule definitions for both alerts covered here.
- [`failure-modes.md`](failure-modes.md) — the broader corpus
  failure-mode index; covers `ArXMCPDegradedMode` and LanceDB
  corruption beyond the narrow scope of this runbook.
- [`backup-restore.md`](backup-restore.md) — restic snapshot +
  restore procedure referenced in S1.
- [`tools/notebook_reconcile_marker.py`](../../tools/notebook_reconcile_marker.py)
  — the CLI behind `make reconcile`.
- [`server/health.py`](../../server/health.py) lines 105-134 — the
  two gauge definitions + their docstring contracts.
