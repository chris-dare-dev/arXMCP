# E11_S02 — Implementation Summary

**One-line summary.** Nightly OAI-PMH delta loop:
`ingest/oai_delta.py` harvester (HTTPS endpoint, resumption-token
walk, day-windowed `from`/`until`, four per-set ListRecords),
reuses E11_S01's `ingest_one_paper` per-paper pipeline against
the staging LanceDB, 90-min budget alert via sentinel flag,
shell wrapper with `flock` reentrancy guard, systemd unit pair
+ cron-fallback documentation. All six brief ACs verified at
code-ship.

**Commit range.** `76f7373..HEAD`.

---

## Scope reminder

The synthesis narrowed/corrected the brief along three axes
(see [research-synthesis.md](research-synthesis.md) D1–D15):

1. **"Fresh LanceDB directory" language is wrong** (same MVCC
   misconception as E11_S01). The delta loop writes to
   `var/arxmcp/index/lancedb-staging/` via
   `ingest_one_paper(lancedb_staging_path=...)`. The active
   `corpus-version.json` is NOT advanced; activation is E11_S05.
2. **HTTPS endpoint** `https://oaipmh.arxiv.org/oai` (arXiv
   migrated from the legacy HTTP `export.arxiv.org/oai2` in
   March 2025; Researcher 2 verified live).
3. **No filesystem touch file.** The brief's
   `/var/arxmcp/ops/new-version-ready` absolute path was wrong
   for macOS and Docker; the touch file itself was redundant
   (the server reads `corpus-version.json` at startup and does
   not poll). The runbook documents manual restart per
   `.claude/notes/06-mcp-server-design.md:346-354`.

Plus: four per-set ListRecords calls (not `set=math` umbrella),
`metadataPrefix=arXivRaw`, `<header status="deleted">` →
withdraw-and-skip (don't delete chunks; out of scope per the
brief).

---

## Acceptance criteria — status

- [x] **AC1** — simulated delta run against mocked OAI-PMH writes
      to staging LanceDB. **Verified** by
      [TestRunDelta::test_end_to_end_with_mock_records](tests/test_oai_delta.py)
      — mocks `ingest_one_paper` to return `chunks_written=5`,
      asserts `summary.records_ingested == 2`,
      `summary.records_failed == 0`.
- [x] **AC2** — resumption-token state persisted to
      `oai-pmh-state.json` after each page. **Verified** by
      [TestHarvestSet::test_state_persisted_after_each_page](tests/test_oai_delta.py)
      — walks 2 pages, asserts state file's `last_resumption_token`
      is cleared after the final page; in-flight token is
      observable between pages.
- [x] **AC3** — mock 500-paper run completes within 90-min budget
      (sleep=0). **Verified** by
      [TestRunDelta::test_500_paper_mock_run_stays_in_budget](tests/test_oai_delta.py)
      — runs a 500-paper synthetic response with `sleep_between_pages
      = lambda _t: None`; asserts `summary.budget_breached is False`
      and `elapsed_seconds < DEFAULT_BUDGET_SECONDS`.
- [x] **AC4** — 3-second politeness delay verifiable in logs / via
      mock timer. **Verified** by
      [TestPolitenessContract::test_sleep_invoked_between_pages](tests/test_oai_delta.py)
      — sleep callback captured; 2-page harvest invokes sleep
      exactly once (between pages, not after the final).
      `POLITENESS_SLEEP_SECONDS == 3.0` is asserted directly.
- [x] **AC5** — `pytest tests/test_oai_delta.py` passes. **Verified**:
      29 passed, 0 failed.
- [x] **AC6** — `docs/ops/delta-loop.md` states the 90-minute
      latency budget explicitly. **Verified** by
      [TestRunbookContent::test_runbook_states_90_minute_budget](tests/test_oai_delta.py).

---

## Files added / changed

### New

- [ingest/oai_delta.py](ingest/oai_delta.py) — the harvester
  module. `HarvestedRecord` + `DeltaSummary` dataclasses;
  `_read_state` / `_write_state` (atomic JSON via temp + rename);
  `_resolve_resume` (today-vs-cross-day token-expiry logic);
  `_parse_listrecords` (XML parser handling
  `<resumptionToken/>` empty-end signal + `oai:error` codes);
  `harvest_set` (one-set walker with token loop + per-page
  state persist); `run_delta` (top-level orchestrator over all
  four sets); `_cli`.
- [tests/test_oai_delta.py](tests/test_oai_delta.py) — 29 tests
  with mocked HTTP (`_MockFetcher`) and mocked `ingest_one_paper`.
  Covers all 6 ACs plus state-file atomicity, malformed-id skip,
  OAI-PMH error responses, sentinel-flag write/clear, dry-run.
- [ops/cron/arxmcp-delta.sh](ops/cron/arxmcp-delta.sh) — shell
  wrapper with `flock -n var/arxmcp/ops/.delta.lock` reentrancy
  guard, mirroring the E10_S04 drift-detector pattern.
- [ops/systemd/arxmcp-delta.service](ops/systemd/arxmcp-delta.service)
  — oneshot unit calling the shell wrapper.
  `ProtectSystem=strict`, `ProtectHome=true`,
  `ReadWritePaths=/opt/arxmcp/var`, `NoNewPrivileges=true`,
  `PrivateTmp=true`, `TimeoutStartSec=7200`. Operator must edit
  `/opt/arxmcp` and the `arxmcp` user/group placeholders.
- [ops/systemd/arxmcp-delta.timer](ops/systemd/arxmcp-delta.timer)
  — daily 02:00 schedule, `Persistent=true`,
  `RandomizedDelaySec=300`.
- [docs/ops/delta-loop.md](docs/ops/delta-loop.md) — operator
  runbook: prerequisites, smoke test, scheduling (systemd
  primary + cron fallback), latency budget, failure modes,
  state file schema.

### Changed

None. No edits to existing files. The bulk-ingest module's
`ingest_one_paper` is called unmodified — every E11_S01 rectifier
fix flows through transparently (F1 embed-status check, F2
parsed_dir decoupling, F3 resume removal, F4 math-signal guard,
F9 redirect pinning).

### Not touched

- `server/tools.py`, every hash-anchored test, server schemas.
  No tool surface change (synthesis D15). `TOOL_SCHEMA_VERSION`
  stays at 6.
- `pyproject.toml` — no new pytest markers; the delta-loop suite
  uses no models, no live network, no `latexmlc`.

---

## Test results

```
1536 passed, 7 skipped in 81.57s
```

- 7 skipped: 4 `requires_model` + 3 `requires_full_corpus`.
- Net delta: **+29 tests** (1507 → 1536).
- `ruff check .` is clean (1 autofix sweep cleaned
  `datetime.timezone.utc → datetime.UTC` and similar 3.11-isms).

---

## Design landmines (record-of-decision)

1. **MVCC discipline preserved.** The delta loop is a thin
   harvester + per-paper feed — all LanceDB writes go through
   `ingest_one_paper` with the staging path. No new directories,
   no version subfolders.

2. **`ingest_one_paper` reuse.** Calling the bulk-ingest
   primitive directly avoids re-implementing the
   ar5iv→LaTeXML→skip-and-log ladder. Every E11_S01 rectifier
   fix is inherited.

3. **HTTPS endpoint.** Switched to `https://oaipmh.arxiv.org/oai`
   per Brief 2's live verification of arXiv's March-2025
   migration. Old `export.arxiv.org/oai2` still works but is
   HTTP-only; HTTPS supersedes.

4. **Day-granularity from/until.** arXiv `Identify` advertises
   day granularity only. Both `from` and `until` use
   `YYYY-MM-DD` format, never timestamps.

5. **Resumption-token expiry: daily.** arXiv tokens expire daily.
   State file persists BOTH `last_resumption_token` AND
   `last_harvest_date`; cross-day crash discards the token and
   re-harvests from `last_harvest_date`. Same-day crash resumes
   from the saved token.

6. **Per-set ListRecords, not `set=math` umbrella.** Four
   targeted calls — `math:math:AG`, `math:math:NT`,
   `physics:math-ph`, `physics:hep-th`. `set=math` would pull
   in math.CO, math.PR, etc.

7. **`flock` reentrancy guard.** Shell wrapper acquires
   `flock -n var/arxmcp/ops/.delta.lock`. Cross-platform
   (macOS + Linux). Overlapping run → fail-fast exit 1.

8. **systemd + cron coexist.** systemd is the primary on Linux;
   cron is documented in the runbook for macOS operators. No
   launchd plist (no precedent in the repo; cron suffices).

9. **No touch file.** The brief's
   `/var/arxmcp/ops/new-version-ready` is dropped. The active
   `corpus-version.json` is not touched by the delta loop, so
   no signal to the running server is needed. Operator restarts
   the server manually (per design note 06).

10. **`papers` table deferred.** OAI-PMH carries rich
    `arXivRaw` metadata (title, authors, abstract). v1 of the
    project has no populated `papers` table; the delta loop
    does NOT introduce one. This is a follow-up — the OAI-PMH
    metadata flows into `HarvestedRecord` but isn't persisted
    beyond the structured log. Tracked as a deferred item.

11. **Withdrawn papers — log + skip, don't delete chunks.**
    `<header status="deleted">` records are counted in
    `records_deleted` and skipped at the pipeline boundary.
    Existing chunks remain (out of scope per the brief).

---

## External writes required at code-ship

**None.** All operations are local Python writes (state file,
parser-failures JSONL, sentinel flag, delta log) and read-only
HTTP fetches to arXiv subdomains via `ingest_one_paper`.

Operator runtime writes:
- `var/arxmcp/ops/oai-pmh-state.json`
- `var/arxmcp/ops/oai-delta.log`
- `var/arxmcp/ops/parser-failures/delta.jsonl`
- `var/arxmcp/ops/delta-timeout.flag` (only on budget breach)
- `var/arxmcp/index/lancedb-staging/` rows (via `ingest_one_paper`)

All gated on operator action (enabling the timer / cron).

---

## Verification against the synthesis "Done-when" checklist

- [x] All 6 brief ACs covered by verifiable tests at code-ship.
- [x] `ingest_one_paper` called unchanged from `ingest.bulk_ingest`.
- [x] Staging-path discipline preserved — active marker untouched.
- [x] No touch file; runbook documents manual server restart.
- [x] systemd + cron both shipped; macOS operators can run.
- [x] `flock` reentrancy guard in place.
- [x] State file persists token AND harvest date.
- [x] Resumption-token expiry handled (cross-day recovery).
- [x] Four per-set ListRecords calls (not `set=math`).
- [x] `metadataPrefix=arXivRaw`.
- [x] `<header status="deleted">` triggers skip + log (no chunk/embed).
- [x] No `TOOL_SCHEMA_VERSION` bump.
- [x] `make test` green; ruff clean.

---

## Open follow-ups (NOT this milestone)

- **`papers` table population.** The OAI-PMH harvest carries
  rich metadata; v1 of arXMCP has no populated `papers` table
  (CLAUDE.md §7 already documents `get_paper` returning NULL
  for these fields). A future milestone can introduce
  `write_paper_metadata` upserting `HarvestedRecord` data into
  a new `papers` table.
- **E11_S05 cutover.** This delta loop writes to staging; the
  atomic swap into the active path is E11_S05's contract.
- **E14 Prometheus surface.** `arxmcp_ingest_oai_pmh_lag_seconds`
  is declared in the metrics schema but the cross-process
  exposure requires E14's `/metrics` work.
