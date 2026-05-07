# E11 — Scale Cutover

Epic dependencies: E07_S04 (nDCG@5 ≥ 0.80 on seed corpus — Tier-1 exit gate), E08 (agent runtime and caching shipped), E10 (specialized indices shipped)

Goal: Grow the corpus from 50 papers to ~200K papers across math.AG, math.NT, math-ph, and hep-th, without re-architecting the system. The cutover is a data operation: seed download via Academic Torrents, followed by nightly OAI-PMH delta ingestion. The existing MCP server, retrieval pipeline, and agent runtime require no structural changes — only the LanceDB corpus version increments. A set of operational safeguards (re-embed cost budget, drift watchdog, backup/restore, and explicit activation criteria) ensures the cutover is reversible and observable.

Effort: L + L + M + M + M = XL total

References: `.claude/notes/03-ingestion-pipeline.md` lines 1–209, `.claude/notes/05-storage-and-indexing.md` lines 139–155

---

### E11_S01 — Academic Torrents seed download and bulk ingest

**Status:** NEW
**Tier:** 5
**Effort:** L
**Dependencies:** E07_S04, E10_S01, E10_S02, E10_S03

**Description.** Download the Academic Torrents bulk dump of arXiv source tarballs for the four target subjects (math.AG, math.NT, math-ph, hep-th) and ingest them into a new LanceDB version. The existing 50-paper seed corpus (LanceDB version N) remains addressable via MVCC throughout this operation — the bulk ingest writes to a new version (N+1) without modifying the existing one.

The download and ingest pipeline:
1. Use a BitTorrent client (`aria2c` or `libtorrent`) to download the Academic Torrents arXiv dump. Filter at extraction time to the four subject categories using the OAI-PMH metadata already present in the dump. Estimated raw size: a few hundred GB of .tex source tarballs.
2. For each paper: (a) check the ar5iv cache (`https://ar5iv.labs.arxiv.org/html/<arxiv_id>`) for pre-rendered HTML5+MathML — use the cached output if available, avoiding local LaTeXML CPU work; (b) for ar5iv cache misses, run the local LaTeXML subprocess pool; (c) fall back to Nougat PDF parsing only for papers with no usable .tex source.
3. Route each parsed paper through the existing macro normalizer → chunker → embedder → LanceDB write pipeline. All writes go to the new version directory (`/var/arxmcp/index/lancedb/vN+1/`).
4. Populate the citation graph in Kùzu from OpenAlex (math.AG, math.NT) and INSPIRE-HEP (hep-th, math-ph) citation data.
5. After all papers are ingested, run `pytest tests/eval/test_retrieval_quality.py --hybrid --ndcg-min=0.70` against the new version as a sanity check. The threshold is lower than the Tier-1 gate (0.80) because the hand-labeled query set was tuned on the seed corpus; re-labeling for the full corpus is E11_S04's job.

Estimated compute: ~1–2 days on a machine with one A6000 or RTX 4090 GPU using bge-m3 at batch size 32. Log progress at 1,000-paper intervals to `ops/ingestion.log`. Papers that fail all parsers are written to `ops/parser-failures/` for human review.

`corpus-version.json` continues to pin the old LanceDB dataset version during the entire ingest run. It is NOT advanced by this milestone — that is E11_S05's activation step. (Per E04_S02, MVCC via `dataset.checkout(version=N)` is the canonical activation mechanism; manual symlink swaps are prohibited.)

**Deliverables.**
- `ingest/bulk_download.sh` — aria2c invocation with Academic Torrents magnet link, subject filter, retry logic
- `ingest/bulk_ingest.py` — orchestrates the full pipeline for each paper: ar5iv check → LaTeXML fallback → Nougat fallback → normalizer → chunker → embedder → LanceDB write; progress logging; parser-failure logging
- `ops/ingestion.log` — populated during the actual run (not a code deliverable, but required as evidence)
- `tests/test_bulk_ingest_sanity.py` — verifies that the new LanceDB version has ≥ 100K chunk entries (a proxy for successful bulk ingest)

**Acceptance criteria.**
- [ ] New LanceDB version directory contains ≥ 100,000 chunk entries
- [ ] `corpus-version.json` still pins the old LanceDB version (no accidental cutover)
- [ ] `ops/parser-failures/` contains entries for any papers that failed all parsers
- [ ] `pytest tests/eval/test_retrieval_quality.py --hybrid --ndcg-min=0.70` passes against the new version
- [ ] ar5iv cache hit rate is logged and is ≥ 70% (most post-2007 papers are cached)

**Out of scope.** Advancing `corpus-version.json` to the new version (E11_S05). Re-labeling the eval query set for the full corpus (E11_S04). Pre-2007 PostScript handling (explicitly out of scope per `.claude/notes/03-ingestion-pipeline.md` lines 195–197).

**Risk notes.**
- The MVCC approach (new LanceDB dataset version, `corpus-version.json` unchanged) ensures the MCP server and all active agent sessions are unaffected during the multi-day ingest run.

**Labels.** `area:ingest`, `kind:feature`, `tier:5`

---

### E11_S02 — OAI-PMH delta loop

**Status:** NEW
**Tier:** 5
**Effort:** L
**Dependencies:** E11_S01

**Description.** Implement the nightly OAI-PMH delta loop that keeps the corpus current after the initial bulk ingest. The OAI-PMH endpoint (`http://export.arxiv.org/oai2`) supports date-range filtering via `from`/`until` parameters and category filtering via `set=math` or `set=physics:hep-th`. Each nightly run harvests the previous day's new and updated papers, queues them for the per-paper pipeline (ar5iv → LaTeXML → Nougat → normalize → chunk → embed → write), and produces a new `corpus_version` integer.

The existing 3-second-per-IP politeness delay in `tools/arxiv_fetch.py` (shipped in commits `c486b26` and `01c6579`) is preserved and extended to the OAI-PMH harvester. The OAI-PMH protocol itself requires a `from`/`until` windowed approach with resumption tokens — the harvester must handle resumption tokens correctly, persisting the last-seen token in `ops/oai-pmh-state.json` so a crash mid-harvest can resume from where it left off.

**Latency budget per delta run:** the nightly run must complete within 90 minutes for a typical day's delta (200–500 new papers across the four subjects). At 3 seconds per fetch, 500 papers = 25 minutes fetch time. ar5iv cache hits reduce the parse time to near zero. The embedding step dominates: ~1 second per paper on GPU = ~8 minutes for 500 papers. The 90-minute budget is generous; the hard constraint is that the run finishes before the next nightly run begins. A run that exceeds 90 minutes triggers an alert in the ops log.

Each completed delta run produces a new corpus version. The ingestion process writes the new version to a fresh LanceDB directory, updates `corpus-version.json`, and signals the MCP server via a filesystem touch of `/var/arxmcp/ops/new-version-ready`. The MCP server does NOT auto-reload — a human or ops script must restart it to pick up the new version. This is intentional: agents in the middle of a session expect index stability (`.claude/notes/06-mcp-server-design.md` lines 346–354).

The delta loop is registered as a systemd timer (or cron job) at 02:00 local time daily. The timer unit files are in `ops/systemd/`.

**Deliverables.**
- `ingest/oai_delta.py` — OAI-PMH harvester: date-range query, resumption-token handling, category filter, per-paper queue feed; respects 3-second politeness delay
- `ops/oai-pmh-state.json` — persistent state file: last successful harvest date, last resumption token
- `ops/systemd/arxmcp-delta.service` and `arxmcp-delta.timer` — systemd unit files for nightly scheduling
- `docs/ops/delta-loop.md` — operator documentation: how the delta loop works, how to trigger a manual run, how to check status, the 90-minute budget
- `tests/test_oai_delta.py` — unit test with a mocked OAI-PMH endpoint: validates resumption-token handling, politeness delay, and that a successful run increments `corpus_version`

**Acceptance criteria.**
- [ ] A simulated delta run against a mocked OAI-PMH endpoint completes and writes a new corpus version
- [ ] Resumption-token state is persisted to `ops/oai-pmh-state.json` after each harvested page
- [ ] A mock run of 500 papers completes within the 90-minute budget (simulated with sleep=0)
- [ ] The 3-second politeness delay between per-paper fetches is verifiable in logs (or via mock timer)
- [ ] `pytest tests/test_oai_delta.py` passes
- [ ] `docs/ops/delta-loop.md` states the 90-minute latency budget explicitly

**Out of scope.** Automatic MCP server restart on new corpus version (human-in-the-loop by design). Real-time ingestion (nightly cadence is sufficient). Withdrawn-paper handling beyond setting `withdrawn=true` in the metadata.

**Risk notes.**
- Closes MEDIUM: arXiv 429 backoff (latency budget) — documenting the 90-minute latency budget and preserving the 3-second per-IP politeness delay closes the finding that the design lacked a quantified latency target for the delta loop. The politeness constraint already prevents 429 responses; the budget ensures the daily window is met.

**Labels.** `area:ingest`, `kind:feature`, `tier:5`

---

### E11_S03 — Re-embed cost budget and partial re-embed strategy

**Status:** NEW
**Tier:** 5
**Effort:** M
**Dependencies:** E11_S01

**Description.** Define and enforce the re-embed strategy for corpus version bumps that change the chunker or embedder. A naive re-embed strategy re-embeds every chunk in the corpus when either `chunker_version` or `embedder_version` changes — at 200K papers and ~25 chunks per paper (~5M chunks), this is a GPU-day operation. The partial re-embed strategy limits the work to chunks whose content actually changed.

The strategy relies on content-addressable chunk IDs. Each chunk ID is `arxiv:<paper_id>:<sha256(canonical_chunk_bytes)[:16]>`. A chunk whose content is byte-identical between `chunker_version` A and B has the same chunk ID and therefore the same embedding — its existing embedding vector is valid and can be copied into the new LanceDB version without re-computation.

The re-embed procedure for a `chunker_version` or `embedder_version` bump:
1. Run the chunker over all papers using the new `chunker_version`. This produces a set of chunk IDs for the new version.
2. Compare the new chunk ID set against the previous version's chunk ID set. Chunks with IDs present in both sets have unchanged content — copy their embedding vectors from the old LanceDB table directly (LanceDB MVCC makes the old version still addressable).
3. Chunks with new IDs (content changed or newly created) must be re-embedded. Queue them for the embedder.
4. Chunks in the old set but not the new set (content deleted or restructured) are simply not written to the new version.

GPU-hours budget for common re-embed scenarios:
- **Embedder model swap** (bge-m3 version bump): all 5M chunks must be re-embedded. At 32 chunks/sec on an A6000, ~44 hours. Plan: run over a weekend.
- **Chunker logic fix** (affects ~5% of papers): ~250K chunks re-embedded, ~2 hours.
- **Macro normalizer fix** (affects papers with specific macro patterns): ~50K chunks re-embedded, ~25 minutes.

These estimates and the partial re-embed procedure are documented in `docs/ops/re-embed-runbook.md`. The runbook also documents the safe failure mode: if re-embedding is interrupted mid-run, the new LanceDB version is incomplete and `corpus-version.json` must NOT be advanced to it. Resume by re-running `ingest/re_embed.py` with the `--resume` flag, which uses the content-hash comparison to skip already-embedded chunks.

**Deliverables.**
- `ingest/re_embed.py` — partial re-embed script: compares old and new chunk ID sets, copies unchanged embeddings, queues changed chunks for re-embedding; `--resume` flag
- `docs/ops/re-embed-runbook.md` — GPU-hours budget table; step-by-step procedure; safe resume behavior; embedding-space mixing warning

**Acceptance criteria.**
- [ ] Running `re_embed.py` on a corpus where 95% of chunks are unchanged copies 95% of embeddings without re-computation (verifiable via log output)
- [ ] Running `re_embed.py` with `--resume` after an interrupted run skips already-embedded chunks
- [ ] `docs/ops/re-embed-runbook.md` contains the GPU-hours budget table for all three re-embed scenarios
- [ ] The runbook explicitly warns against mixing embedding spaces in one LanceDB table

**Out of scope.** Automatic re-embed triggering (human-initiated in v1). Fine-tuned embedding models (v2). Streaming re-embed while the server is live (offline batch only).

**Risk notes.**
- Closes MEDIUM: re-embed cost — without a partial re-embed strategy, any chunker or embedder version bump forces a full 44-hour re-embed. The content-hash comparison reduces typical re-embeds to 2–4 hours for targeted fixes.

**Labels.** `area:ingest`, `kind:ops`, `tier:5`

---

### E11_S04 — Drift watchdog: per-corpus-version nDCG@5 regression alert

**Status:** NEW
**Tier:** 5
**Effort:** M
**Dependencies:** E07_S04, E11_S02

**Description.** Implement a drift watchdog that automatically re-runs the retrieval quality evaluation (E05/E07) against each new corpus version and alerts on regression. The watchdog runs as part of the nightly delta pipeline, immediately after a new corpus version is written — before `corpus-version.json` is advanced to the new version. If the watchdog detects a regression, `corpus-version.json` is NOT advanced and the new corpus version is quarantined for human review.

The evaluation runs E05's 20-query hand-labeled query set against the new corpus version using the full hybrid pipeline (BM25 + ANN + RRF, with the reranker enabled if `ARXMCP_ENABLE_RERANK=true`). nDCG@5 is computed for each query and averaged. The watchdog alerts if the average nDCG@5 drops more than 5% relative to the previous corpus version's score (not absolute — a 0.80 → 0.76 drop = 5% relative regression). The alert threshold of 5% relative regression is configurable via `ARXMCP_EVAL_REGRESSION_THRESHOLD_PCT`.

The Prometheus metric `arxmcp_eval_ndcg5{corpus_version="N"}` is emitted after each watchdog run. This metric is the canonical time-series record of retrieval quality across corpus versions. A Grafana dashboard (or equivalent) should plot this metric over time; the dashboard spec is in `docs/ops/grafana-dashboards.md`.

The watchdog output is a JSON report written to `ops/eval-reports/corpus_vN.json` containing: `corpus_version`, `ndcg5_mean`, `ndcg5_per_query` (list), `regression_vs_prev` (float), `alert_triggered` (bool), `timestamp`.

**Deliverables.**
- `ops/watchdog_eval.py` — reads the new corpus version, runs the 20-query eval, computes nDCG@5, compares to previous, emits metric, writes JSON report, exits non-zero if alert triggered
- `ops/eval-reports/` — directory for per-version JSON reports (gitignored for large corpora, but present and populated)
- `server/metrics.py` — updated with `arxmcp_eval_ndcg5` gauge labeled by `corpus_version`
- `docs/ops/drift-watchdog.md` — how the watchdog integrates with the nightly delta loop; alert thresholds; what to do when an alert fires

**Acceptance criteria.**
- [ ] Running `watchdog_eval.py` against the current seed corpus produces a valid JSON report with nDCG@5 ≥ 0.80
- [ ] A simulated corpus version with degraded retrieval (nDCG@5 ≈ 0.60) causes `watchdog_eval.py` to exit non-zero
- [ ] `arxmcp_eval_ndcg5{corpus_version="N"}` is emitted at `/metrics` after a watchdog run
- [ ] `docs/ops/drift-watchdog.md` states the 5% relative regression threshold and documents the quarantine procedure

**Out of scope.** Automated corpus version rollback (human-in-the-loop). Expanding the eval query set beyond 20 queries (a larger eval set is a v2 concern). Per-subject nDCG@5 breakdown (aggregate only in v1).

**Risk notes.**
- Closes MEDIUM: drift detection / retrieval quality metrics — without the watchdog, a corpus update that degrades retrieval quality (e.g., a parser regression introducing garbage chunks, or a LaTeXML version change affecting embeddings) would be invisible until an agent user reports poor results. The watchdog makes regression detection automatic and corpus-version-scoped.

**Labels.** `area:ops`, `kind:observability`, `tier:5`

---

### E11_S05 — Backup/restore runbook and 200K cutover activation

**Status:** NEW
**Tier:** 5
**Effort:** M
**Dependencies:** E11_S01, E11_S04

**Description.** Document and execute the 200K-paper scale cutover: advance `corpus-version.json` to the new LanceDB dataset version, verify the MCP server restarts cleanly against the new version, and confirm the watchdog eval passes at nDCG@5 ≥ 0.80. Additionally, implement and execute a backup/restore runbook using `restic` to a local NAS or Backblaze B2 bucket. (Per E04_S02, activation is via LanceDB MVCC + `corpus-version.json`; manual symlink swaps are prohibited.)

**200K cutover activation criteria (explicit).** `corpus-version.json` is advanced to the new corpus version IF AND ONLY IF all of the following are true:
1. E07_S04 nDCG@5 ≥ 0.80 on the hand-labeled seed query set (Tier-1 exit gate — already passed before E11 begins).
2. E11_S04 watchdog eval on the new corpus version reports nDCG@5 ≥ 0.80 AND no regression > 5% relative vs. the seed corpus version.
3. E11_S01 ingestion completed with zero corrupt LanceDB writes (verified by `python -m lancedb.verify --path /var/arxmcp/index/lancedb/vN+1/`).
4. The backup runbook has been executed and a successful restore drill completed.

**Rollback plan.** If the new corpus version is activated and problems are detected (agent quality regression, MCP server instability, unexpected latency increase), the rollback procedure is: stop the MCP server; revert `corpus-version.json` to the previous version integer; restart the MCP server. The MCP server's corpus-version pinning at startup means in-flight sessions are not affected by `corpus-version.json` changes — only new server restarts pick up the new pin via `dataset.checkout(version=N)`. Rollback takes < 30 seconds.

**Backup/restore.** `restic` backs up the following paths to the configured repository (local NAS path or B2 bucket configured in `ops/restic-env.sh`):
- `/var/arxmcp/index/lancedb/` (all corpus versions, ~100GB per version)
- `/var/arxmcp/index/kuzu/` (citation graph, ~5GB)
- `/var/arxmcp/corpus/chunks/` (content-addressable chunk JSON, ~30GB)

The backup runs nightly via a systemd timer after the delta ingestion completes. Retention policy: 7 daily, 4 weekly, 12 monthly snapshots. A restore drill is executed once before the 200K cutover: a test restore to `/tmp/arxmcp-restore-drill/` followed by a `pytest` smoke test against the restored data.

All procedures are documented in `docs/ops/cutover-runbook.md` and `docs/ops/backup-restore.md`.

**Deliverables.**
- `ops/cutover.sh` — activation script: checks all 4 criteria, advances `corpus-version.json` to the new version, restarts MCP server, runs watchdog eval as post-activation check
- `ops/restic-env.sh.template` — restic configuration template (no credentials; operator fills in the repository URL and password)
- `ops/systemd/arxmcp-backup.service` and `arxmcp-backup.timer` — systemd units for nightly backup
- `docs/ops/cutover-runbook.md` — explicit activation criteria (4 bullets above), activation procedure, rollback procedure (<30 seconds), post-activation health checks
- `docs/ops/backup-restore.md` — backup configuration, retention policy, restore drill procedure

**Acceptance criteria.**
- [ ] `ops/cutover.sh` checks all 4 activation criteria before advancing `corpus-version.json`; exits non-zero if any criterion is not met
- [ ] The restore drill successfully restores to `/tmp/arxmcp-restore-drill/` and passes the MCP server smoke test against the restored data
- [ ] `docs/ops/cutover-runbook.md` states all 4 activation criteria explicitly and includes the rollback procedure with a time estimate
- [ ] After cutover, MCP server `/readyz` returns 200 against the new corpus version within 60 seconds
- [ ] After cutover, E11_S04 watchdog eval reports nDCG@5 ≥ 0.80 on the 200K corpus

**Out of scope.** Zero-downtime cutover (the server restart introduces a brief unavailability window, acceptable for a single-workstation deployment). Automated rollback (human decision). Incremental backup beyond restic's built-in deduplication.

**Risk notes.**
- Closes H9: the 200K scale cutover trigger is now explicit and measurable — nDCG@5 ≥ 0.80 on the new corpus version (not a vague "when we feel ready"). The rollback plan is concrete and takes < 30 seconds. Without an explicit trigger and a tested rollback, a cutover risks stranding agents on a degraded corpus with no recovery path.

**Labels.** `area:ops`, `kind:ops`, `tier:5`
