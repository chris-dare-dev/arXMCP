# E11_S02 — Research Synthesis

Merged from [research-brief-1.md](research-brief-1.md) (in-codebase
mechanics + landmines A-H) and [research-brief-2.md](research-brief-2.md)
(OAI-PMH protocol mechanics + delta-volume reality + operational
surface). Sharp convergence on most decisions; one important
divergence on the OAI-PMH endpoint URL — Brief 2's "migrated to
HTTPS oaipmh.arxiv.org as of March 2025" supersedes Brief 1's HTTP
`export.arxiv.org/oai2`.

---

## 1. Headline findings (consensus)

| # | finding | resolution |
|---|---|---|
| 1 | **"Fresh LanceDB directory" language is wrong (again).** Same MVCC mistake as E11_S01's brief. LanceDB MVCC manages versions internally inside ONE dataset; no `vN+1/` subdirs, no symlinks. | Use **staging-path discipline from E11_S01.** Write to `DEFAULT_LANCEDB_STAGING_PATH` = `var/arxmcp/index/lancedb-staging/`. The active marker is NOT advanced until E11_S05. |
| 2 | **`ingest_one_paper` from E11_S01 is the correct reuse point.** Calling it inherits all five HIGH rectifier fixes (F1 embed-status check, F2 parsed_dir decoupling, F3 resume removal, F4 math-signal guard, F9 redirect pinning). | **Reuse `ingest_one_paper`.** The delta loop is an OAI-PMH-driven `paper_ids` source feeding the same per-paper pipeline. NO parallel implementation. |
| 3 | **Absolute path `/var/arxmcp/ops/new-version-ready` is wrong** (fails on macOS, fails in Docker with mounted volumes). The touch file is ALSO redundant — `corpus-version.json` IS the signal; the server reads it at startup and does not poll. | **Drop the touch file entirely.** Document manual restart in `docs/ops/delta-loop.md`. The active `corpus-version.json` is not touched by the delta loop anyway (staging discipline). |
| 4 | **systemd is Linux-only.** macOS operators need an alternative. | **Ship systemd primary + crontab fallback documented in the runbook.** Do NOT ship a launchd plist (more complex, no precedent in the repo; drift-check sets the pattern). |
| 5 | **Delta volume reality.** Brief assumes 200–500 papers/day across four subjects. Brief 2 verified live data: ~71–133 typical, ~200–250 Monday spike. The 500-paper worst case is conservative. | Latency model is **15–20 min typical, 40 min spike**. The 90-min budget is 4–6× headroom — keep it (room for ar5iv CDN degradation, future category expansion). |
| 6 | **Two distinct rate-limit contexts.** OAI-PMH page fetches (3-sec politeness, ~2 pages per run) vs per-paper `/e-print/` fallback (3-sec per paper, only on ar5iv miss). ar5iv has NO rate limit. | Apply `politeness_sleep` only before OAI-PMH page fetches and before per-paper `/e-print/` calls. `ingest_one_paper` already handles ar5iv (no sleep). |
| 7 | **`flock`-based reentrancy.** A run that overlaps the next nightly run breaks single-writer-per-dataset. | Shell wrapper acquires `flock -n var/arxmcp/ops/.delta.lock` before invoking Python. Identical for cron+systemd. |
| 8 | **Resumption-token expiry.** arXiv tokens expire daily. A crash spanning midnight invalidates the token. | State schema persists BOTH `last_resumption_token` AND `last_harvest_date`. On restart, if `last_harvest_date < today`, discard the token and re-harvest from `last_harvest_date`. |
| 9 | **`set=math` umbrella vs four per-set calls.** `set=math` pulls in math.CO, math.PR, etc. — not what the project targets. | **Four per-set ListRecords calls.** Set identifiers verified live: `math:math:AG`, `math:math:NT`, `physics:math-ph`, `physics:hep-th`. |
| 10 | **No tool-schema changes.** No new MCP tools, no tool description changes. | `TOOL_SCHEMA_VERSION` stays at 6. No hash repins. |

## 2. Divergence + resolution

### OAI-PMH endpoint URL — HTTPS vs HTTP

- Brief 1: `http://export.arxiv.org/oai2` (HTTP only; cited the
  design note `.claude/notes/03-ingestion-pipeline.md:30`).
- Brief 2: `https://oaipmh.arxiv.org/oai` (HTTPS; cited
  "as of March 2025 arXiv migrated to" the new HTTPS endpoint).

**Resolution:** Default to **Brief 2's HTTPS endpoint**
`https://oaipmh.arxiv.org/oai`. Rationale:
- Brief 2 was explicit about running live verification against
  the `Identify` endpoint.
- HTTPS supersedes HTTP for the same content (no TLS gap to
  document for E13).
- The legacy `http://export.arxiv.org/oai2` is documented as
  still working but HTTP-only.

The design note `.claude/notes/03-ingestion-pipeline.md:30`
references the old URL — it predates the migration. We will NOT
update the note in this milestone (a note refresh would be out
of scope) but the implementation comment in `ingest/oai_delta.py`
points at the migration as a documentation drift item.

If the live `oaipmh.arxiv.org` endpoint turns out to be flaky or
inaccessible during implementation, fall back to the legacy
HTTP endpoint with a comment. The contract is opaque to callers
either way — `metadataPrefix=arXivRaw` + `from`/`until`/`set`
work identically.

---

## 3. Load-bearing quotes

### Single-writer constraint — `ingest/store.py:44-55`

> "Callers running concurrent ingest from multiple processes against
> the same dataset must serialize writes externally (e.g. a flock on
> `<lancedb_path>/.write-lock`)."

### MVCC reality — `.claude/notes/05-storage-and-indexing.md:162-169`

> "No manual version subdirectories (v0001/, v0002/, etc.) and no
> symlinks. LanceDB MVCC manages corpus versions natively."

### Server index stability — `.claude/notes/06-mcp-server-design.md:346-354`

> "The MCP server does NOT auto-switch — it continues using its
> pinned version. Restart the server to pick up the new corpus.
> (Rationale: agents in the middle of a session expect index
> stability.)"

### OAI-PMH MUSTs — openarchives.org/OAI/openarchivesprotocol.html

> "the response containing the incomplete list that completes the
> list MUST include an empty `resumptionToken` element"

> "Repositories MUST support selective harvesting with the `from` and
> `until` arguments expressed at day granularity"

### arXiv TOS — `https://info.arxiv.org/help/api/tou.html`

> "make no more than one request every three seconds, and limit
> requests to a single connection at a time."

---

## 4. Design decisions

### D1. Module: `ingest/oai_delta.py`

A single module owning:
- HTTP fetch of OAI-PMH `ListRecords` pages (with `politeness_sleep`).
- Resumption-token parsing + persisting to state file.
- Per-paper feed into `ingest_one_paper` from `ingest.bulk_ingest`.
- Daily window selection (`yesterday` by default; resume from
  state file if `last_harvest_date == today`).
- Withdrawn-paper handling (mark in metadata; do not delete chunks).
- 90-minute budget alert (ERROR log + sentinel flag).

### D2. Reuse `ingest_one_paper` — no parallel pipeline

Per Headline #2: the delta loop calls
`ingest_one_paper(paper_id, lancedb_staging_path=DEFAULT_LANCEDB_STAGING_PATH, ...)`
directly. The OAI-PMH harvest is a pre-step that produces paper IDs;
the per-paper pipeline is unchanged.

### D3. Staging-path discipline (not "fresh directory")

Writes go to `var/arxmcp/index/lancedb-staging/`. The active
`corpus-version.json` is NOT touched. Activation is E11_S05.

### D4. OAI-PMH endpoint: HTTPS `oaipmh.arxiv.org/oai`

Per §2 divergence resolution.

### D5. Four per-set calls

`metadataPrefix=arXivRaw` + four set identifiers:
- `math:math:AG`
- `math:math:NT`
- `physics:math-ph`
- `physics:hep-th`

Each call independently paginates with resumption tokens.

### D6. State file schema — `var/arxmcp/ops/oai-pmh-state.json`

```json
{
  "last_harvest_date": "2026-05-14",
  "last_resumption_token": null,
  "last_successful_run_utc": "2026-05-15T02:14:37Z",
  "last_run_paper_count": 143,
  "last_run_duration_seconds": 847
}
```

`last_resumption_token` is set to the in-progress token mid-run
and nulled on successful completion. On restart:
- If `last_resumption_token` non-null AND `last_harvest_date == today`,
  resume from token.
- If `last_harvest_date < today`, discard the (expired) token and
  re-harvest from `last_harvest_date`.

### D7. CLI flags

`python -m ingest.oai_delta` with:
- `--from=YYYY-MM-DD` (override default "yesterday")
- `--until=YYYY-MM-DD` (override default "yesterday")
- `--lancedb-staging-path=<path>` (default `DEFAULT_LANCEDB_STAGING_PATH`)
- `--state-file=<path>` (default `var/arxmcp/ops/oai-pmh-state.json`)
- `--dry-run` (print papers that would be harvested; no writes)

No `--resume` flag (per E11_S01 F3): resume is driven by the state
file, not a flag.

### D8. 90-minute budget alert

Three escalation layers, mirroring the E10_S04 drift detector:
- ERROR-level log: `logger.error("delta run exceeded 90-minute budget")`.
- Sentinel flag: write `var/arxmcp/ops/delta-timeout.flag`. Clear on
  next successful run.
- Counter: increment `arxmcp_ingest_oai_pmh_lag_seconds` (already
  defined in metrics schema). Production exposure is E14.

### D9. `flock` reentrancy guard

Shell wrapper at `ops/cron/arxmcp-delta.sh`:

```bash
exec flock -n "${REPO_ROOT}/var/arxmcp/ops/.delta.lock" \
  "${UV_BIN}" run python -m ingest.oai_delta "$@"
```

`flock -n` exits 1 immediately if the lock is held → systemd records
a failed unit; journalctl shows the lock contention.

### D10. Cross-platform scheduling

- **systemd (Linux primary):** `ops/systemd/arxmcp-delta.service` +
  `arxmcp-delta.timer`. Runs `ops/cron/arxmcp-delta.sh` at 02:00 daily.
- **cron (macOS fallback):** documented snippet in
  `docs/ops/delta-loop.md`:
  ```
  0 2 * * * /path/to/ops/cron/arxmcp-delta.sh
  ```
- **No launchd plist.** Not justified for this project's scale.

### D11. No filesystem touch file

Per Headline #3: drop `var/arxmcp/ops/new-version-ready`. The
active `corpus-version.json` is not updated by the delta loop
(staging discipline). When E11_S05 cuts over, restarting the
server is the established mechanism per design note 06.

### D12. Withdrawn-paper handling

OAI-PMH `<header status="deleted">` records → mark `withdrawn=true`
on the paper metadata upsert. Do NOT delete chunks (out of scope
per the brief).

### D13. `papers` table population

The OAI-PMH harvest carries rich `arXivRaw` metadata (title, authors,
abstract, categories, license, version history). The delta loop
should upsert this into a `papers` table — BUT v1 of this project
does NOT have a `papers` table populated; `get_paper` returns NULL
for these fields (CLAUDE.md §7 calls this out as a known stub).

**Decision:** v1 of E11_S02 does NOT introduce the `papers` table.
The OAI-PMH metadata is logged to the structured log
(`var/arxmcp/ops/oai-delta.log`) and persisted in the state file's
`last_run_paper_count`. Populating a `papers` table is its own
milestone (Out of scope; tracked as follow-up).

The `withdrawn` semantic still applies: the OAI-PMH harvest skips
chunking/embedding for `status="deleted"` records and logs them.
Existing chunks remain (out of scope to delete).

### D14. Test surface

- `tests/test_oai_delta.py` — pure unit tests with mocked HTTP
  responses (no live network). Tests cover:
  - resumption-token loop (page 1 → page 2 → empty token = done)
  - state-file persistence after each page
  - expired-token recovery (state from yesterday → re-harvest)
  - 90-minute budget alert (mock time, ERROR log, sentinel flag)
  - politeness sleep applied between OAI-PMH page fetches
  - withdrawn-paper handling (`status="deleted"` → skip chunk/embed)
  - `--dry-run` does not call `ingest_one_paper` or write LanceDB

No new pytest marker required. No `requires_model`, no
`requires_network`, no `requires_full_corpus`. All tests run on
the default suite.

### D15. No tool-schema changes

Per Headline #10. `TOOL_SCHEMA_VERSION` stays at 6.

---

## 5. Forced cross-file changes

| File | Change | Why |
|---|---|---|
| `ingest/oai_delta.py` (NEW) | OAI-PMH harvester + delta loop CLI | D1, D2, D4-D8, D11, D12 |
| `ops/cron/arxmcp-delta.sh` (NEW) | Shell wrapper with `flock` guard | D9 |
| `ops/systemd/arxmcp-delta.service` (NEW) | systemd unit calling the shell wrapper | D10 |
| `ops/systemd/arxmcp-delta.timer` (NEW) | systemd timer at 02:00 daily | D10 |
| `docs/ops/delta-loop.md` (NEW) | Operator runbook (90-min budget, cron+systemd, restart semantics) | D10, D11 |
| `tests/test_oai_delta.py` (NEW) | Mocked-HTTP unit tests | D14 |
| `Makefile` | Add `delta:` target with Python version guard? OPTIONAL — the cron + systemd path is the canonical invocation | (deferred unless implementer sees clean fit) |

NOT touched: `server/`, `ingest/bulk_ingest.py`, `ingest/store.py`,
hash-anchored tests. The bulk module's `ingest_one_paper` is called
unmodified.

---

## 6. Landmines (consolidated)

1. **MVCC: no `vN+1/` directories.** Staging-path discipline.
2. **`write_chunks` postcondition advances `corpus-version.json`** —
   staging path isolates it. `ingest_one_paper` already passes the
   staging path.
3. **Reuse `ingest_one_paper`** — do NOT clone its logic.
4. **OAI-PMH endpoint moved to HTTPS** — use `oaipmh.arxiv.org/oai`.
5. **Token expiry is daily** — state file persists both token AND
   harvest date.
6. **`set=math` is the wrong filter** — use four targeted sets.
7. **systemd is Linux-only** — ship cron fallback.
8. **No touch file** — the active marker isn't advanced by deltas.
9. **`assert` banned for invariants** — `if ... raise RuntimeError`.
10. **HEREDOC commits, GPG signed, no `--no-verify`.**
11. **arXiv TOS politeness applies to `export.arxiv.org`** (OAI-PMH
    + e-print). Not ar5iv.

---

## 7. AC coverage at code-ship

| Brief AC | Coverage |
|---|---|
| Simulated delta run writes new corpus version | Verifiable: mocked HTTP returns ListRecords; integration test asserts staging-LanceDB version advanced. |
| Resumption-token state persisted | Verifiable: test asserts `oai-pmh-state.json` contains the token after page 1, nulled after final page. |
| Mock 500-paper run within 90-min budget (sleep=0) | Verifiable: test injects 500 mock-paper-ids, asserts elapsed < 90 min wall + alert not raised. |
| 3-second politeness verifiable in logs/timer | Verifiable: test asserts `politeness_sleep` was invoked between OAI-PMH page fetches. |
| `pytest tests/test_oai_delta.py` passes | Verifiable. |
| `docs/ops/delta-loop.md` states 90-min budget | Verifiable: test or grep that the runbook contains the phrase "90-minute". |

All 6 ACs are verifiable at code-ship. No operator-gated ACs.

---

## 8. External writes required

**None.** All operations are read-only HTTP fetches and local writes:

| Type | Target | Why |
|---|---|---|
| HTTP GET | `https://oaipmh.arxiv.org/oai` | OAI-PMH metadata harvest (read-only) |
| HTTP GET | `https://ar5iv.labs.arxiv.org/html/<id>` | Per-paper source fetch (via `ingest_one_paper`) |
| HTTP GET | `https://export.arxiv.org/e-print/<id>` | LaTeXML fallback (via `ingest_one_paper`, only on ar5iv miss) |

No pushes, PRs, tickets, infra mutations, write-side API calls.

---

## 9. Suggested implementation order

1. `ingest/oai_delta.py` — OAI-PMH parser + harvester scaffolding (no real network calls).
2. `tests/test_oai_delta.py` — token-loop + state-file tests.
3. Wire `ingest_one_paper` into the per-paper feed.
4. `ops/cron/arxmcp-delta.sh` — shell wrapper with `flock`.
5. `ops/systemd/arxmcp-delta.{service,timer}` — systemd units.
6. `docs/ops/delta-loop.md` — operator runbook.
7. `make test` (full suite); ruff clean; commit.

---

## 10. Done-when checklist

- [ ] All 6 brief ACs covered by verifiable tests at code-ship.
- [ ] `ingest_one_paper` called unchanged from `ingest.bulk_ingest`.
- [ ] Staging-path discipline preserved — active marker untouched.
- [ ] No touch file; runbook documents manual server restart.
- [ ] systemd + cron both shipped; macOS operators can run.
- [ ] `flock` reentrancy guard in place.
- [ ] State file persists token AND harvest date.
- [ ] Resumption-token expiry handled (cross-day recovery).
- [ ] Four per-set ListRecords calls (not `set=math`).
- [ ] `metadataPrefix=arXivRaw`.
- [ ] `<header status="deleted">` triggers skip + log (no chunk/embed).
- [ ] No `TOOL_SCHEMA_VERSION` bump.
- [ ] `make test` green; ruff clean.

---

## 11. Open questions (carry-over)

None blocking. Three scoped decisions documented above as D-items
(D13 papers-table v1 deferral, withdrawn handling, first-run init).
