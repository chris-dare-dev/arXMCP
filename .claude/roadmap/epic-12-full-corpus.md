# E12 — Full v1 Corpus (Tier 5b)

**Epic dependencies:** E11, E08.

**Goal:** scale the seed-corpus pipeline to the full v1 target — math.AG, math.NT, math-ph, hep-th, post-2007 with usable .tex source. Roughly 200K papers per `03-ingestion-pipeline.md` § Realistic timing; ~100 GB of LanceDB index per `05-storage-and-indexing.md` § Disk and memory budget. Daily delta runs without manual intervention. Exit criterion (`09-feature-priorities.md`): corpus contains ≥150K papers, retrieval works at full scale, daily delta lands without manual intervention.

**Effort:** 1–2 weeks (mostly run time, not engineering).

**References:** `09-feature-priorities.md` § Tier 5; `03-ingestion-pipeline.md` § Realistic timing; `05-storage-and-indexing.md` § Disk and memory budget at v1 scale.

---

### E12_S01 — Pre-flight: workstation hardware and disk validation

**Description.** Per `08-security-observability-ops.md` § Operational footprints, the recommended workstation is 32 GB RAM, 1 TB SSD, 1 GPU ≥16 GB VRAM. Validate the target machine meets minimum + recommended thresholds before kicking off the seed download.

**Acceptance criteria.**
- [ ] `tools/preflight.py` checks free RAM ≥30 GB, free disk on `/var/arxmcp` ≥600 GB, GPU presence (warn if absent).
- [ ] Reports projected disk usage from `05-storage-and-indexing.md`'s budget against actual free space.
- [ ] Reports projected wall-clock from `03-ingestion-pipeline.md` (1–2 days for ~200K with one A6000/4090).
- [ ] Exits non-zero if minimums (16 GB RAM, 500 GB SSD) not met.
- [ ] Documented as the gate before running E12_S02.

**Dependencies.** none within E12.

**Complexity.** S.

**Labels.** `area:infra`, `kind:infra`.

---

### E12_S02 — Full Academic Torrents seed download

**Description.** Run E11_S04 against the production-target torrents to fetch math.AG + math.NT + math-ph + hep-th source for the post-2007 era. Expect a few hundred GB. Provide a resume capability since the download is multi-hour.

**Acceptance criteria.**
- [ ] Seed completed: `var/arxmcp/corpus/raw/` contains ≥150K paper directories.
- [ ] All four target categories represented (verified via OAI-PMH metadata cross-check).
- [ ] No corruption: `tools/verify_seed.py` opens every tarball and confirms it's well-formed.
- [ ] Total disk usage under the projected ~200 GB raw budget.
- [ ] Seed completion timestamp committed to `var/arxmcp/ops/seed-complete.json`.

**Dependencies.** E12_S01, E11_S04.

**Complexity.** L.

**Labels.** `area:ingestion`, `kind:research`.

---

### E12_S03 — Bulk parse + chunk + embed of the full seed

**Description.** Run E11_S05 workers against the full seed. ar5iv cache will absorb most of the work; LaTeXML local handles the long tail; Nougat handles the residue. Expected wall-clock: 1–2 days on one A6000 / RTX 4090 per `03-ingestion-pipeline.md`.

**Acceptance criteria.**
- [ ] All seed papers run through the worker pool.
- [ ] ≥90% of papers reach `parse_status="ok"`; ≤5% land in `parser-failures/`.
- [ ] Chunks written to staging LanceDB version `v0001`.
- [ ] Equation atoms, definitions, theorem_names populated.
- [ ] Stats summary in `var/arxmcp/ops/full-seed-stats.json`: total chunks, equations, definitions, per-parser breakdown, mean parse duration, GPU utilisation.
- [ ] Total chunk count between 4M and 6M (consistent with `05-storage-and-indexing.md` § Disk and memory budget).

**Dependencies.** E12_S02, E11_S05.

**Complexity.** XL.

**Labels.** `area:ingestion`, `area:embedder`, `kind:research`.

---

### E12_S04 — Build all indexes on the full corpus and atomic-swap

**Description.** After E12_S03, build HNSW + Tantivy + B-tree indexes on the staging LanceDB version, validate via smoke queries, then atomic-swap to `current`. This makes the full corpus live for the MCP server.

**Acceptance criteria.**
- [ ] HNSW indexes built on `embedding_prose`, `embedding_latex`, `embedding_eq`, `abstract_embedding`.
- [ ] BM25 / Tantivy indexes built on `body_canonical`, `body_raw_latex`.
- [ ] B-tree scalar indexes built per E05_S05.
- [ ] Pre-swap smoke test: 5 known queries return non-empty top-10.
- [ ] Atomic swap via E11_S06.
- [ ] Server restart picks up the new corpus version.
- [ ] Disk size measured and recorded in `var/arxmcp/ops/full-seed-disk.json`; within ~120 GB budget.

**Dependencies.** E12_S03, E11_S06.

**Complexity.** L.

**Labels.** `area:storage`, `area:retrieval`, `kind:research`.

---

### E12_S05 — Citation graph at full scale

**Description.** Run E09 ingestion against the full corpus. OpenAlex bulk for math.AG / math.NT (large download, ~tens of GB); INSPIRE per-paper enrichment for hep-th / math-ph (weeks of background work at 15 rps).

**Acceptance criteria.**
- [ ] Initial OpenAlex bulk applied to Kùzu graph.
- [ ] INSPIRE enrichment running as a background daemon at 15 rps.
- [ ] After 1 week of INSPIRE backfill, ≥80% of hep-th papers have at least one inbound or outbound `CITES` edge.
- [ ] Total Kùzu file size under ~10 GB.
- [ ] `cite_neighbors` returns ≥30 results on at least 100 query papers.
- [ ] Stats logged to `var/arxmcp/ops/full-seed-graph-stats.json`.

**Dependencies.** E12_S04, E09_S02, E09_S04.

**Complexity.** L.

**Labels.** `area:graph`, `area:ingestion`.

---

### E12_S06 — Daily-delta cron in production

**Description.** Per `08-security-observability-ops.md` § Daily ops cadence, schedule the cron pipeline. The exit criterion is "daily delta lands without manual intervention." Validate by running 7 consecutive nightly cycles and confirming each produces a new corpus version.

**Acceptance criteria.**
- [ ] Cron entry installed (host crontab or systemd timer) per `infra/cron/daily-delta.cron`.
- [ ] Cron starts at 00:00 UTC; completes by 04:30 UTC on average.
- [ ] After 7 consecutive nights, 7 new corpus versions exist (or fewer if no papers landed on a given day, but no failures).
- [ ] Per-day report logged to `var/arxmcp/ops/daily-reports/<date>.md`.
- [ ] Failed nights produce an alert via the configured channel (file + email if configured).

**Dependencies.** E11_S07, E12_S04.

**Complexity.** M.

**Labels.** `area:ingestion`, `kind:infra`, `risk:high`.

---

### E12_S07 — Full-corpus retrieval-quality eval

**Description.** Run the eval harness from E06_S09 against the full corpus. Expect retrieval quality to actually improve relative to the 50-paper baseline (more candidates = more signal for the dense embedder). Document the numbers as the v1 baseline.

**Acceptance criteria.**
- [ ] Run E06_S09's harness against the full corpus.
- [ ] Top-10 hit rate ≥85% on the harness's query set.
- [ ] Per-phrasing breakdown shows that synonym / LaTeX / English phrasings of the same intent return overlapping top-10s ≥70% of the time.
- [ ] v1 baseline numbers committed to `docs/retrieval/v1-baseline.md`.
- [ ] Comparison chart vs. E06_S09 baseline.

**Dependencies.** E12_S04.

**Complexity.** M.

**Labels.** `area:retrieval`, `kind:research`.

---

### E12_S08 — Backup runbook execution (restic to local NAS or B2)

**Description.** Per `08-security-observability-ops.md` § Backup and restore, set up nightly restic snapshots of `corpus/`, `index/lancedb/`, `index/kuzu/` to a local NAS or Backblaze B2. The constraint "no S3" was about not paying AWS for arXiv; B2 for backup is a different question and a small cost (~$3/month for 500GB).

**Acceptance criteria.**
- [ ] `infra/restic/repo-init.sh` initializes the restic repository.
- [ ] `infra/restic/nightly.sh` runs nightly via cron, takes a snapshot, prunes per retention policy (keep 7 daily, 4 weekly, 12 monthly).
- [ ] First successful snapshot completed and verified via `restic check`.
- [ ] Restic password stored in a configurable env var (`RESTIC_PASSWORD`); never in source.
- [ ] Documented in `docs/ops/backup.md`.

**Dependencies.** E12_S04.

**Complexity.** S.

**Labels.** `area:infra`, `kind:infra`.

---

### E12_S09 — Restore drill execution

**Description.** Per `08-security-observability-ops.md` § Backup and restore — "Restore drill: quarterly. Document the runbook." The Tier 5 exit criterion explicitly requires the drill to have run at least once. Execute it on a sandbox machine and document.

**Acceptance criteria.**
- [ ] Restore drill: provision a fresh `var/arxmcp/` from the most recent restic snapshot on a separate machine (or sandbox path).
- [ ] After restore, run E12_S04 smoke queries and confirm parity.
- [ ] Time-to-restore measured and documented.
- [ ] Runbook committed to `docs/ops/restore-runbook.md` with exact commands.
- [ ] Drill schedule established (next drill in 3 months).

**Dependencies.** E12_S08.

**Complexity.** M.

**Labels.** `area:infra`, `kind:research`.

---

### E12_S10 — 4-agent fan-out validation at full scale

**Description.** Re-run the cache-fanout test from E08_S12 against the full corpus. Confirms that prompt caching and retrieval caching continue to work at scale (cache hit rates should be similar to or better than at seed scale).

**Acceptance criteria.**
- [ ] Cache hit rates: Tier 1 ≥40%, Tier 3 ≥60% (same thresholds as E08_S12).
- [ ] No regression in P95 query latency vs. seed-corpus baseline.
- [ ] `/debug/cache-stats` shows healthy distribution.
- [ ] Numbers committed to `docs/cache/v1-fanout-eval.md`.

**Dependencies.** E12_S04, E08_S12.

**Complexity.** S.

**Labels.** `area:cache`, `kind:research`.

---
