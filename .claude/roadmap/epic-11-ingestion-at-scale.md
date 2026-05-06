# E11 — Ingestion Pipeline at Scale (Tier 5a)

**Epic dependencies:** E02, E03, E04.

**Goal:** convert the hand-driven ingestion path used through E04 into a production pipeline that can run continuously: Academic Torrents seed download, OAI-PMH delta channel, `/e-print/` per-paper fetcher, parser/chunker/embedder workers, atomic version swap. Daily cron-driven cadence per `08-security-observability-ops.md` § Daily ops cadence.

**Effort:** ~2 weeks.

**References:** `03-ingestion-pipeline.md` (entire file authoritative); `08-security-observability-ops.md` § Daily ops cadence; `02-architecture-overview.md` § Component responsibilities (ingestion service is a separate process).

---

### E11_S01 — Per-paper job queue (filesystem-backed)

**Description.** A simple, durable per-paper job queue: drop arxiv IDs into `var/arxmcp/queue/incoming/` (one file per ID); a worker moves them through `processing/` → `parsed/` → `chunked/` → `embedded/` → `done/` directories. Idempotent and resumable on crash.

**Acceptance criteria.**
- [ ] `ingest/queue/fs_queue.py` exposes `enqueue(arxiv_id)` and `claim_next() -> JobHandle | None`.
- [ ] Atomic state transitions via `os.rename`.
- [ ] Job carries metadata (enqueued_at, attempt_count, last_error).
- [ ] Crash recovery: jobs stuck in `processing/` for >1 hour are returned to `incoming/` with attempt_count incremented.
- [ ] Test: 100 jobs enqueued and processed by 4 concurrent workers all reach `done/` exactly once.

**Dependencies.** none within E11.

**Complexity.** M.

**Labels.** `area:ingestion`, `kind:infra`.

---

### E11_S02 — OAI-PMH delta harvester

**Description.** Per `03-ingestion-pipeline.md` § Source 2 — nightly `/oai2` harvest with `set=math`, `set=physics:hep-th`, etc. and `from`/`until` windowing using resumption tokens. Rate-limited at 1 request per 4 seconds. Filters at the source so we never pull biology / CS.

**Acceptance criteria.**
- [ ] `ingest/sources/oai_pmh.py::harvest(from_date, until_date) -> Iterable[ArxivRecord]`.
- [ ] Honors resumption tokens; harvests until completion or until-date.
- [ ] Rate limit: ≤1 request per 4 seconds with backoff on 503 (per `03-ingestion-pipeline.md`).
- [ ] Filter sets: `math`, `physics:hep-th` (math-ph and math.AG/NT come via category filters from the math set).
- [ ] English-language filter: dropped if metadata indicates non-English (per `09-feature-priorities.md` non-goals).
- [ ] Test (recorded fixture): a fixture OAI response is parsed correctly, resumption tokens followed.
- [ ] Counter `arxmcp_ingest_oai_pmh_lag_seconds` exposes lag relative to "yesterday" per `08-security-observability-ops.md`.

**Dependencies.** none within E11.

**Complexity.** L.

**Labels.** `area:ingestion`, `kind:feature`, `risk:high`.

---

### E11_S03 — `/e-print/` per-paper fetcher with politeness rules

**Description.** Per `03-ingestion-pipeline.md` § Source 3 — fetch `https://arxiv.org/e-print/<paper_id>` at 1 request per 3 seconds per IP, with 503 backoff. Hard ceiling. Used only for the delta — bulk seed comes via Academic Torrents.

**Acceptance criteria.**
- [ ] `ingest/sources/eprint.py::fetch(arxiv_id) -> SourceTarball | FetchFailure`.
- [ ] Single global rate-limiter at 3-second per-request cadence.
- [ ] User-Agent: `arXMCP/0.1 (mailto:<configured>)`.
- [ ] Exponential backoff on 503 starting at 30 s, capping at 1 hour per `08-security-observability-ops.md` § Failure modes.
- [ ] Content-length sanity: refuse responses >100 MB per `08-security-observability-ops.md` Threat 7.
- [ ] Test: rate limiter allows exactly 20 requests in 60 seconds.
- [ ] Test: 503 response triggers backoff and pauses subsequent calls.

**Dependencies.** none within E11.

**Complexity.** M.

**Labels.** `area:ingestion`, `area:security`, `kind:feature`.

---

### E11_S04 — Academic Torrents seed downloader

**Description.** Per `03-ingestion-pipeline.md` § Source 1 — community-published torrents are the seed. Filter to math.AG + math.NT + math-ph + hep-th source. Download via libtorrent or aria2c; the script documents the torrent magnet/file IDs to use.

**Acceptance criteria.**
- [ ] `tools/seed_torrent.sh` (bash, uses aria2c or transmission-cli) downloads the configured torrent.
- [ ] Script accepts a torrent file or magnet URI as argument; suggested torrent IDs documented in `docs/ingestion/torrents.md` (verified live before commit).
- [ ] Post-download: extracts source tarballs into `var/arxmcp/corpus/raw/` keyed by arxiv_id.
- [ ] Filter step: drops papers not in math.AG / math.NT / math-ph / hep-th (based on metadata file in the torrent).
- [ ] Documented expected size: a few hundred GB per `03-ingestion-pipeline.md`.
- [ ] Note in docs: torrents are stale by definition; OAI-PMH delta keeps it current.

**Dependencies.** E01_S01.

**Complexity.** M.

**Labels.** `area:ingestion`, `kind:infra`, `risk:high`.

---

### E11_S05 — Ingestion worker pool: parse → normalize → chunk → embed → write

**Description.** Long-running worker that pulls a job from the queue (E11_S01) and runs the full pipeline: E02 parser → E03 normalizer → E04 chunker → E05 embedder → write to a staging LanceDB version. Supports N workers in parallel.

**Acceptance criteria.**
- [ ] `ingest/worker/main.py` runs N workers (configurable, default 4) sharing the queue.
- [ ] Each worker handles one paper at a time; failures route to the parser-failure log (E02_S04, E02_S06) and advance the queue.
- [ ] Workers write to a staging LanceDB directory `var/arxmcp/index/lancedb/staging/`; only after batch completion does E11_S06 swap.
- [ ] Worker shutdown is graceful (finish current job, then exit).
- [ ] Test: 4 workers concurrently process 50 jobs without races.
- [ ] Counters `arxmcp_ingest_papers_processed_total{parser, outcome}` and `arxmcp_ingest_paper_duration_seconds` exposed.

**Dependencies.** E11_S01, E02_S04, E03_S07, E04_S09, E05_S06.

**Complexity.** L.

**Labels.** `area:ingestion`, `area:embedder`, `kind:feature`.

---

### E11_S06 — Atomic version-swap orchestrator

**Description.** When a batch completes (a daily delta or a full re-chunk), promote the staging LanceDB directory to a new versioned directory and atomic-swap the `current` symlink (using the primitive from E05_S07). Confirm the new version is queryable before swapping.

**Acceptance criteria.**
- [ ] `ingest/orchestrate/version_swap.py::promote(staging_dir) -> Version`.
- [ ] Pre-swap validation: open the staging dataset, run a smoke query, confirm row counts match expectations.
- [ ] On validation failure, alert and retain staging for inspection.
- [ ] On success, rename staging to `vNNNN`, atomic-swap `current`.
- [ ] Old versions retained per the N=7 policy from E05_S07.
- [ ] Test: a corrupted staging directory does NOT swap and is left for inspection.

**Dependencies.** E11_S05, E05_S07.

**Complexity.** M.

**Labels.** `area:ingestion`, `area:storage`, `kind:infra`.

---

### E11_S07 — Daily cron entry point

**Description.** Per `08-security-observability-ops.md` § Daily ops cadence, the daily timeline is OAI-PMH @ 00:00 UTC → fetch + parse + chunk + embed → version swap @ 04:00 UTC. Build a single `daily-delta` command that orchestrates this end-to-end.

**Acceptance criteria.**
- [ ] `ingest daily-delta` entry point runs OAI-PMH harvest, enqueues new IDs, runs workers, calls `promote`.
- [ ] On any sub-step failure, the script exits non-zero and emits a structured log with the failed step name.
- [ ] Idempotent: re-running after partial failure resumes from where it left off.
- [ ] Documented cron entry in `infra/cron/daily-delta.cron`.
- [ ] Test: dry-run mode that processes a synthetic 5-paper delta end-to-end.

**Dependencies.** E11_S02, E11_S03, E11_S05, E11_S06.

**Complexity.** M.

**Labels.** `area:ingestion`, `kind:infra`.

---

### E11_S08 — Two-service docker-compose with `ingest` profile

**Description.** Per `08-security-observability-ops.md` § Docker deployment — two services, `arxmcp-server` (always-on) and `arxmcp-ingest` (on-demand via `--profile ingest`). Each runs as non-root user, with read-only / read-write volume splits. The MCP server reads `/var/arxmcp/index` read-only; the ingestion service reads/writes corpus + index.

**Acceptance criteria.**
- [ ] `infra/docker-compose.yml` matches the YAML in `08-security-observability-ops.md` § Docker deployment (modulo image name conventions).
- [ ] `arxmcp-server` is `read_only: true`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges]`, `user: arxmcp`.
- [ ] `arxmcp-ingest` is `profiles: [ingest]` so it doesn't auto-start; invoked via `docker-compose --profile ingest run --rm arxmcp-ingest daily-delta`.
- [ ] Volume layout: `/var/arxmcp/index` mounted RO into server, RW into ingest; `/var/arxmcp/cache` RW into server only.
- [ ] Healthcheck targets `http://127.0.0.1:7733/readyz` per E07_S07.
- [ ] Test: `docker compose up -d arxmcp-server` brings the server to ready state.

**Dependencies.** E07_S07, E11_S07.

**Complexity.** M.

**Labels.** `area:infra`, `kind:infra`.

---

### E11_S09 — TLS pinning and content-length sanity for source fetches

**Description.** Per `08-security-observability-ops.md` Threat 7 — verify TLS, refuse responses >100 MB. Wire into both E02_S01 (ar5iv fetcher) and E11_S03 (`/e-print/` fetcher).

**Acceptance criteria.**
- [ ] HTTP client default verifies TLS (no `verify=False` anywhere).
- [ ] Content-length header > 100 MB → refuse before downloading; log + counter increment.
- [ ] Streaming download with running byte count; abort if exceeds 100 MB even with no/incorrect Content-Length.
- [ ] Test: a fixture server returning a fake 200 MB response is rejected without exhausting memory.

**Dependencies.** E02_S01, E11_S03.

**Complexity.** S.

**Labels.** `area:ingestion`, `area:security`.

---

### E11_S10 — Withdrawal/replacement metadata tracking

**Description.** Papers can be withdrawn or replaced on arXiv. Per `09-feature-priorities.md` Tier 6 (which this issue partially advances since the metadata is needed for proper search filtering), track withdrawal status from OAI-PMH and surface it via `papers.withdrawn` and `papers.withdrawal_reason`. The `include_withdrawn` filter in `search_papers` already exists in the schema.

**Acceptance criteria.**
- [ ] `ingest/sources/oai_pmh.py` parses the withdrawal status (deleted records, withdrawal notes).
- [ ] `papers.withdrawn` and `papers.withdrawal_reason` populated.
- [ ] `search_papers` default filter excludes withdrawn (per the schema default).
- [ ] Test: a withdrawn paper does NOT appear in default search results, but DOES appear with `include_withdrawn=true`.
- [ ] Withdrawal events logged at INFO level.

**Dependencies.** E11_S02, E05_S09.

**Complexity.** S.

**Labels.** `area:ingestion`, `area:retrieval`.

---

### E11_S11 — Ingestion observability: per-stage metrics

**Description.** Per `08-security-observability-ops.md` § Metrics, ingestion has its own metrics endpoint pattern: papers processed by parser/outcome, paper duration, chunks written, OAI-PMH lag. Wire all of these into the worker (E11_S05) and harvester (E11_S02).

**Acceptance criteria.**
- [ ] `arxmcp_ingest_papers_processed_total{parser, outcome}` counter.
- [ ] `arxmcp_ingest_paper_duration_seconds{parser}` histogram (p50, p95, p99).
- [ ] `arxmcp_ingest_chunks_written_total` counter.
- [ ] `arxmcp_ingest_oai_pmh_lag_seconds` gauge.
- [ ] Ingestion process exposes `/metrics` on a separate port (default 7734).
- [ ] Test: after a 5-paper synthetic run, all four metrics report sensible values.

**Dependencies.** E11_S02, E11_S05.

**Complexity.** S.

**Labels.** `area:observability`, `area:ingestion`.

---

### E11_S12 — Pre-2007 / parse-failed paper marking as degraded coverage

**Description.** Per `09-feature-priorities.md` non-goals — "OCR of pre-2007 scanned papers" is excluded; mark these as degraded coverage. Per `03-ingestion-pipeline.md` § The %-with-source reality, log them clearly so users know the corpus boundary.

**Acceptance criteria.**
- [ ] Papers with submission date <2007 OR with no usable .tex source are flagged with `parse_status="failed"` (or "degraded" if Nougat produced low-confidence output).
- [ ] These papers are excluded from default `search_papers` results.
- [ ] A weekly degraded-coverage report (extends E02_S06) lists counts per category.
- [ ] Test: a fixture pre-2007 paper goes through ingestion and ends up with `parse_status="failed"`.

**Dependencies.** E02_S06, E11_S05.

**Complexity.** S.

**Labels.** `area:ingestion`, `area:observability`.

---
