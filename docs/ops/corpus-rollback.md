# Corpus-version rollback

A `corpus_version` bump produced a regression (nDCG@5 dropped, a
known-good query returns wrong results, or a malformed chunk
landed). Revert to the previous LanceDB dataset version via
MVCC, no data restore required.

> Indexed from [`docs/ops/README.md`](README.md) #6.
> Related: E04_S02 (LanceDB MVCC via `dataset.checkout(version=N)`),
> E04_S03 (corpus-version marker file), E11_S05 (atomic cutover).
> The companion runbook [`cutover-runbook.md`](cutover-runbook.md)
> handles the FORWARD direction (staging → active); this runbook
> handles the BACKWARD direction.

---

## Symptoms

- The Tier-1 retrieval eval (`make eval`) regressed since the last
  `corpus_version` bump.
- A spot-check query that worked yesterday now returns wrong
  papers.
- The drift watchdog ([`drift-watchdog.md`](drift-watchdog.md))
  fired against the current `corpus_version`.
- A bug surfaced in the chunker / embedder / extractor and the
  affected chunks are in the latest LanceDB dataset version but
  not the previous one.

## Detection

- `arxmcp_eval_ndcg5` gauge dropped against baseline.
- `arxmcp_latexml_drift_detected` non-zero (relevant if the bump
  came with a new LaTeXML; see
  [`latexml-drift-runbook.md`](latexml-drift-runbook.md)).
- Manual spot-check from the affected query.

## Steps

The LanceDB MVCC contract (E04_S02) keeps every prior dataset
version on disk. Rollback is a marker-file flip, NOT a data
restore.

1. **Identify the target version.** List the dataset versions and
   pick the one you want to roll back to.

   ```bash
   uv run python -c '
   import lancedb
   db = lancedb.connect("var/arxmcp/index/lancedb")
   tbl = db.open_table("chunks")
   for v in tbl.list_versions():
       print(v)
   '
   ```

   The output lists `(version, timestamp, metadata)` tuples in
   ascending order. The CURRENT pinned version is in
   `var/arxmcp/corpus-version.json`.

2. **Read the current pinned version and decide the target.**

   ```bash
   cat var/arxmcp/corpus-version.json
   # Expected: {"corpus_version": <N>, "lancedb_version": <M>, ...}
   ```

   You're rolling back to `<M-1>` (or further). Pick the version
   immediately before the regression landed.

3. **Atomically swap the marker.** The `corpus_version` marker
   file is THE single source of truth for which LanceDB version
   the server pins. Edit it via temp-file + `os.replace` to keep
   the swap atomic (so a concurrent `/readyz` check never sees a
   half-written file).

   ```bash
   TARGET_LDB=<the version number from step 2>
   TARGET_CORPUS=<the corpus_version that corresponds to that LDB version>
   cat > var/arxmcp/corpus-version.json.tmp <<EOF
   {"corpus_version": ${TARGET_CORPUS}, "lancedb_version": ${TARGET_LDB}, "rolled_back_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"}
   EOF
   mv var/arxmcp/corpus-version.json.tmp var/arxmcp/corpus-version.json
   ```

4. **Restart the daemon.** The corpus version is read at lifespan
   startup; the in-process 3-tier retrieval cache invalidates on
   version change per E08_S03.

   ```bash
   sudo systemctl restart arxmcp
   ```

5. **The Kùzu citation graph is NOT rolled back.** Kùzu is a
   separate database and does NOT participate in LanceDB MVCC.
   If the bad bump corrupted the citation graph too, see the
   citation-graph rebuild procedure in
   [`bulk-ingest-runbook.md`](bulk-ingest-runbook.md). For most
   rollbacks (a bad embedder, a bad chunker), the citation graph
   is untouched and the rollback is LanceDB-only.

## Verification

```bash
# The daemon now pins to the target LanceDB dataset version. Confirm
# the corpus-version marker file matches what step 3 wrote (this is
# the single source of truth the daemon reads at lifespan startup).
cat var/arxmcp/corpus-version.json
# Expected: matches the TARGET_CORPUS / TARGET_LDB from step 3.

# Confirm the daemon came up cleanly post-restart.
curl -fsS http://127.0.0.1:7733/healthz   # → 200
curl -fsS http://127.0.0.1:7733/readyz    # → 200

# Spot-check the failing query — it should return the correct
# paper now.
make smoke   # or run a single search_papers call manually

# Eval gate against the rolled-back version
make eval --ndcg-min=0.80
```

After rollback, **file an issue in
`.claude/notes/deferred-work-tracker.md`** documenting the
regression that triggered the rollback. The forward fix (a bug in
the chunker / embedder / etc.) should be tracked there until
addressed, then the corpus can be re-ingested forward via
[`bulk-ingest-runbook.md`](bulk-ingest-runbook.md) +
[`re-embed-runbook.md`](re-embed-runbook.md).
