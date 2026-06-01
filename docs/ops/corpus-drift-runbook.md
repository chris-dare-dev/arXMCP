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

The runbook also covers write-time `RuntimeError` from the WAP gate
in `ingest/store.py::write_chunks` (corpus-integrity-completion-e1):
the gate reads `corpus-version.json` back from disk after every
write and raises if its `chunk_count` does not match a fresh
`tbl.count_rows()`. Operators following the gate's RuntimeError
`runbook_url` land here; see [§Symptom: WAP gate
RuntimeError](#wap-gate-runtimeerror-at-ingest-time-e1).

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

### WAP gate RuntimeError at ingest time (e1)

The ingest process raised `RuntimeError` with text starting
`WAP gate: corpus-version.json marker at <path> ...`. The bulk
ingest or notebook ingest aborted at the failing paper; downstream
papers were not processed. No marker corruption was published to
the server — the gate fired BEFORE the bad marker could become
load-bearing.

The three error-arm text fragments operators may see:

- `... is malformed and cannot be parsed: ...` — the gate's
  `read_corpus_version` raised `ValueError` (FM-3: truncated atomic
  rename, partial write before `os.replace`, or a serialization
  bug).
- `... is absent after write_corpus_version_marker returned ...` —
  cold-clone case: no prior marker file existed AND the just-written
  marker write was silently swallowed by the best-effort try/except
  at `ingest/store.py:970-977`.
- `... reports chunk_count=N but tbl.count_rows()=M for
  corpus_version=K. Likely causes: ...` — the COUNT-MISMATCH arm.
  Either (1) a pre-m1-style `len(chunks)`-instead-of-`count_rows()`
  arithmetic regression, OR (2) the marker write was swallowed and
  the stale prior marker's `chunk_count` is what was read back. The
  discriminator is the immediately-preceding `could not write
  corpus-version.json marker` warning in the ingest log (see [§Quick
  triage → WAP gate failure](#wap-gate-failure-triage)).

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

### WAP gate failure triage

The gate's RuntimeError text already cites the failing path, the
diagnostic counts, and the likely-cause enumeration. Triage in ≤ 60
seconds before opening Remediation:

```bash
# 1. Confirm the gate's error text from the most recent ingest log
#    (substitute your ingest log path / process manager as appropriate).
grep -B1 'WAP gate: corpus-version.json' var/arxmcp/ops/ingest.log | tail -20

# 2. CRITICAL — look for the swallow-warning discriminator in the
#    line immediately preceding the gate's RuntimeError. Its presence
#    distinguishes a swallowed-I/O failure (transient) from an
#    arithmetic regression (durable).
grep -B1 'WAP gate:' var/arxmcp/ops/ingest.log | \
    grep 'could not write corpus-version.json marker'
```

The presence (or absence) of the swallow warning routes triage:

| Gate error arm | Swallow warning present? | Likely cause |
|---|---|---|
| malformed | yes or no | atomic-rename truncation; disk full mid-write |
| absent | usually yes (cold-clone after swallowed write) | first-ever write hit transient I/O; safe to retry |
| count-mismatch | **yes** | S5 (swallow + stale prior marker) — see Remediation |
| count-mismatch | **no** | S6 (arithmetic regression) — see Remediation |

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

### S5 — WAP gate fired on a marker write that was swallowed (stale prior marker case)

Production-common stale-marker path. A transient `IOError` /
`PermissionError` / disk-full during `write_corpus_version_marker`
was absorbed by the best-effort try/except at
`ingest/store.py:970-977`. The PRIOR marker (from an earlier
successful write) remains on disk with an older `chunk_count`. The
WAP gate immediately afterward reads back the stale marker and
compares against the fresh post-merge_insert `tbl.count_rows()` —
they diverge by exactly the per-call delta. Distinguished from S6
by the presence of `could not write corpus-version.json marker` in
the ingest log immediately preceding the RuntimeError.

### S6 — WAP gate fired on a fresh marker write (arithmetic regression)

The just-written marker reports a `chunk_count` that does not match
`tbl.count_rows()` and NO swallow warning preceded it (i.e. the
marker write itself succeeded; its content is just wrong). Most
likely cause: a refactor in `ingest/store.py` reintroduced the
pre-m1 bug shape (`chunk_count = len(chunks)` per-batch instead of
`tbl.count_rows()` cumulative) — exactly the regression class the
gate exists to catch at the write boundary. Possible secondary
cause: a `WriteStats` field change that made the cumulative count
read non-monotonic. Either way, the fix is a code fix in
`ingest/store.py`, NOT a `make reconcile`.

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

### Fix S5 — WAP gate RuntimeError with swallow warning (stale prior marker)

The marker drift is recoverable; this is the transient-I/O path.

```bash
# 1. Confirm the swallow warning is in the log and the gate's text
#    matches the count-mismatch shape.
grep -B1 'WAP gate:' var/arxmcp/ops/ingest.log | tail -10

# 2. Run `make reconcile` to rewrite the marker against the live
#    table count. Reconcile reads the LanceDB row count and atomically
#    rewrites corpus-version.json — it heals exactly this drift.
make reconcile

# 3. Re-run the failing ingest. Subsequent write_chunks calls will
#    pass the gate because the marker now matches the table.
#    (For the bulk path, use the resume mechanism — bulk_ingest's
#    per-paper sidecar idempotency lets it skip already-completed
#    papers and only retry the ones that failed.)
make ingest                                       # or scoped re-run
```

If the swallow warning recurs on the retry, the underlying I/O
problem (disk full, permission drop) is the root cause — fix that
before retrying again. Escalate per the §Escalation procedure.

### Fix S6 — WAP gate RuntimeError WITHOUT swallow warning (arithmetic regression)

The marker drift indicates a code regression — `make reconcile`
would heal the marker for THIS write, but the next ingest would
reintroduce the same wrong count. Fix the code first.

```bash
# 1. Confirm NO swallow warning preceded the gate's RuntimeError.
grep -B1 'WAP gate:' var/arxmcp/ops/ingest.log | tail -5

# 2. Read the gate's error text — it cites the claimed chunk_count
#    vs the actual tbl.count_rows(). The delta is the regression
#    signature.

# 3. Search for recent edits to ingest/store.py and the
#    `chunk_count =` assignment specifically. The pre-m1 bug shape
#    used `chunk_count = len(chunks)`; the m1 fix uses
#    `chunk_count = tbl.count_rows()`.
git -C . log -p --since='14 days ago' -- ingest/store.py | \
    grep -B2 -A2 'chunk_count'

# 4. Revert or correct the regression in code; THEN run
#    `make reconcile` to heal the now-stale marker; THEN re-run
#    `make test` to confirm tests/test_write_chunks_wap_gate.py
#    passes (those tests are the regression guard for this bug
#    class).
make reconcile
make test
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
