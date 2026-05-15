# Research Brief 2 — E11_S02: OAI-PMH delta loop

**Researcher:** Agent 2 of 2
**Date:** 2026-05-15
**Axis:** Protocol mechanics · Delta-volume reality check · Operational surface

---

## 1. External sources / Protocol mechanics

### OAI-PMH 2.0 MUSTs (canonical source verified)

Fetched from https://www.openarchives.org/OAI/openarchivesprotocol.html:

**ListRecords:**
- MUST support `metadataPrefix` argument; repositories MUST be able to return
  Dublin Core (`oai_dc`). The arXiv endpoint also supports `arXiv` and
  `arXivRaw` — use `arXivRaw` (includes `<versions>`, `<categories>`,
  `<license>`, `<journal-ref>`). The brief says "arXiv-native format"; the
  correct argument is `metadataPrefix=arXivRaw`.

**resumptionToken:**
- "a repository MUST include a `resumptionToken` element as part of each
  response that includes an incomplete list"
- Token is opaque; harvesters must URL-encode it before re-use in the
  subsequent `verb=ListRecords&resumptionToken=<token>` call (no other
  parameters allowed — `from`, `until`, `set` are stripped).
- "the response containing the incomplete list that completes the list MUST
  include an empty `resumptionToken` element" — an EMPTY token is the end
  signal, not its absence.

**from/until granularity:**
- "Repositories MUST support selective harvesting with the `from` and `until`
  arguments expressed at day granularity"
- Seconds granularity is optional and advertised in the `<Identify>` response's
  `<granularity>` element.
- The arXiv `Identify` endpoint (`https://oaipmh.arxiv.org/oai?verb=Identify`)
  returns `YYYY-MM-DD` — day granularity only. Do NOT use timestamp arguments.

**set:**
- Optional selective-harvesting filter.
- Verified live set identifiers from `https://oaipmh.arxiv.org/oai?verb=ListSets`:
  - math.AG → `math:math:AG`
  - math.NT → `math:math:NT`
  - math-ph → `physics:math-ph` (NOT `math:math-ph`; NOT `math-ph` alone)
  - hep-th → `physics:hep-th`
- **The brief says `set=math` and `set=physics:hep-th`.** `set=math` returns ALL
  math categories (~30 subcategories). For targeted harvesting of the four
  subjects, use four separate `ListRecords` calls with the set identifiers above.
  `set=math` is simpler but would pull in math.CO, math.PR, etc. — not what we
  want. Recommendation: four per-set calls.

**Deleted records:**
- arXiv's `Identify` response declares `<deletedRecord>persistent</deletedRecord>`.
- Withdrawn papers appear as `<header status="deleted">` with NO metadata or
  about sections — only the identifier and datestamp.
- Per brief scope: mark `withdrawn=true` in the papers table. Do NOT re-chunk.
  The `papers` table in `.claude/notes/05-storage-and-indexing.md` includes
  `withdrawn: bool`. Existing chunks for the paper remain intact.

**503 / rate-limit behavior:**
- OAI-PMH spec: "HTTP Status Code 503 signals service unavailability. A
  `Retry-After` period is specified. Harvesters SHOULD wait this period before
  attempting another OAI-PMH request."
- arXiv Terms of Use (verified at https://info.arxiv.org/help/api/tou.html):
  "make no more than one request every three seconds, and limit requests to
  a single connection at a time." This matches the existing `POLITENESS_SLEEP_SECONDS = 3.0`
  contract in `tools/arxiv_fetch.py`. The sleep applies to each `ListRecords`
  page fetch (not per-paper; OAI-PMH pages are batch metadata, not source tarballs).

**Resumption token expiry:**
- arXiv's March 2025 update: "expires daily." A crash that resumes the SAME
  calendar day can retry with the saved token. A crash spanning midnight cannot
  — the token is expired. Recovery: if the persisted token's `harvest_date` is
  prior to today, discard it and re-harvest from that date. The state file MUST
  persist BOTH `last_token` AND `harvest_date` to detect staleness.

**New OAI-PMH base URL:**
- As of March 2025, arXiv migrated to `https://oaipmh.arxiv.org/oai` (HTTPS).
  The legacy endpoint `http://export.arxiv.org/oai2` still works but is HTTP.
  The new endpoint supports HTTPS. **Use `https://oaipmh.arxiv.org/oai`** —
  this resolves Brief 1's Landmine D (HTTP) and aligns with arXiv's current
  infrastructure. Add a comment in `ingest/oai_delta.py` pointing to the
  migration note for the E13 audit.

---

## 2. Per-day delta volume reality check

**Brief assumption:** 200–500 papers per day across all four subjects. **This is
WRONG by a factor of 3–5.**

Live data from `https://arxiv.org/list/<category>/recent` (May 11–15, 2026):

| Category | Typical daily submissions |
|---|---|
| math.AG | 13–28 |
| math.NT | 10–30 |
| math-ph | 18–25 |
| hep-th | 30–50 |
| **Total** | **~71–133** |

Monday spike: hep-th showed 49 on May 15 (a Friday); Tuesdays after a long
weekend can spike to ~2× the normal rate. A realistic Monday spike estimate
for all four categories combined is ~200–250, not 500.

**The 500-paper worst-case from the brief is conservative for the aggregate
daily delta. The realistic typical-day load is 100–150 papers.**

This materially affects the latency budget:
- At 3s per ar5iv miss (≤30% of 150 = 45 papers needing `/e-print/`): 45 × 3s
  = 2.25 minutes fetch time.
- Embedding on CPU (~3s/paper): 150 × 3s = 7.5 minutes.
- **Total realistic runtime: ~15–20 minutes.** The 90-minute budget is not
  merely "generous" — it is 4–6× headroom. The hard constraint is the next
  nightly run, not the budget.

**Revised latency model:** typical day (150 papers) ~20 min; Monday spike (300
papers) ~40 min. The 90-minute alert threshold is a 4–6× safety net for
ar5iv CDN degradation or future category expansion — not a tight constraint.

---

## 3. Operational surface

### systemd vs cron vs launchd

**Be opinionated:** Ship BOTH, with a clear primary/fallback:

1. **Primary (Linux/Docker):** `ops/systemd/arxmcp-delta.service` +
   `arxmcp-delta.timer`. The service calls `ops/cron/arxmcp-delta.sh`
   (identical to how the drift-check shell wrapper calls `python -m ops.drift_check`).
   This mirrors the existing ops pattern exactly.

2. **Fallback (macOS workstations):** A crontab entry documented in
   `docs/ops/delta-loop.md`:
   ```
   0 2 * * * /path/to/uv run python -m ingest.oai_delta >> /var/log/arxmcp-delta.log 2>&1
   ```
   **Do NOT ship a launchd plist.** It is more complex, harder to debug, and
   the drift-check precedent (crontab entry in the .sh comments, not a plist)
   is the established pattern here.

**Shell wrapper:** Ship `ops/cron/arxmcp-delta.sh` mirroring the existing
`ops/cron/latexml-drift-check.sh` pattern (SCRIPT_DIR → REPO_ROOT → `exec uv run python -m ingest.oai_delta`). The systemd service unit calls this wrapper.

### Log discipline

The drift detector uses three operator-signal layers: stderr ERROR log,
non-zero exit code, and sentinel file `var/arxmcp/ops/drift-detected.flag`.
Apply the same pattern to the delta loop:

- Normal run: INFO-level structured log per paper (paper_id, outcome, elapsed_s)
- 90-minute breach: `logger.error("delta run exceeded 90-minute budget")` +
  write sentinel `var/arxmcp/ops/delta-timeout.flag`. Clear the flag on next
  successful run.
- Prometheus counter: `arxmcp_ingest_oai_pmh_lag_seconds` is already defined
  in the metrics schema (confirmed in peer brief). Increment it at run end.
  The production `/metrics` exposure is E14; the v1 signal is the stderr log
  and the flag file.

**Do NOT** write to a separate log file from the shell script — redirect stdout/
stderr to systemd's journal (`StandardOutput=journal`) or the crontab redirect.
Separate log files are harder to rotate and `journalctl` is the correct
operator interface on Linux.

### Failure mode escalation

| Condition | Action |
|---|---|
| Run > 90 min | ERROR log + write `var/arxmcp/ops/delta-timeout.flag` |
| arXiv 503 response | Honor `Retry-After`, exponential backoff (max 1 hour per `.claude/notes/08-security-observability-ops.md:199`) |
| Resume token expired | Discard token, re-harvest from `harvest_date` in state file |
| `ingest_one_paper` raises | Log paper_id + exception, write to `ops/parser-failures/delta.jsonl`, continue |

### Reentrancy guard

**Use `flock`.** The shell wrapper acquires an exclusive lock on
`var/arxmcp/ops/.delta.lock` before invoking Python:

```bash
exec flock -n "${REPO_ROOT}/var/arxmcp/ops/.delta.lock" \
  "${UV_BIN}" run python -m ingest.oai_delta "$@"
```

`flock -n` (non-blocking) exits immediately with code 1 if the lock is held.
The systemd timer records this as a failed unit, which is the correct operator
signal (journalctl shows the lock contention). Do NOT use systemd
`LockPersonality=yes` (that is a security namespace feature, not a reentrancy
guard). Do NOT use `RefuseManualStart=no` (that is the default and has nothing
to do with reentrancy). The `flock` approach works identically for crontab
invocations on macOS.

The `var/arxmcp/ops/` directory must exist before the first run. Add it to
`make bootstrap`.

---

## 4. Implementation shape

### Fallback ladder

E11_S01 ships: ar5iv → LaTeXML → skip-and-log (Nougat deferred). E11_S02
MUST inherit the same fallback ladder by calling `ingest_one_paper` from
`ingest.bulk_ingest`. Do not implement a parallel fallback ladder. The brief's
"ar5iv → LaTeXML → Nougat → normalize → chunk → embed → write" is aspirational
— Nougat remains deferred. The E11_S01 docstring at lines 40-42 is the
authoritative ladder.

### Reuse `ingest_one_paper`

Call `ingest_one_paper(paper_id, lancedb_staging_path=DEFAULT_LANCEDB_STAGING_PATH, ...)`
directly. This buys E11_S01 rectifier fixes (F1 embed-status check, F4
math-signal guard, F9 redirect pinning) for free. The OAI-PMH harvest is a
pre-step that produces paper IDs + metadata; `ingest_one_paper` handles the
per-paper source fetch.

### Corpus-version advancement semantic for deltas

The brief says the delta run "writes the new version to a fresh LanceDB
directory." **This is wrong.** The staging discipline from E11_S01 applies:
write to `DEFAULT_LANCEDB_STAGING_PATH` (`var/arxmcp/index/lancedb-staging/`).
The active `corpus-version.json` at `var/arxmcp/index/lancedb/` is NOT updated
until E11_S05 activation. The delta loop does NOT advance the active marker —
it only advances the staging dataset's internal LanceDB version integer.

The brief's "produces a new `corpus_version` integer" is accurate for the
STAGING dataset. The integer is what `write_chunks` returns. Log it.

### MCP server index stability (verbatim from design note)

`.claude/notes/06-mcp-server-design.md` lines 346–354:

> "The MCP server does NOT auto-switch — it continues using its pinned version.
> Restart the server to pick up the new corpus. (Rationale: agents in the
> middle of a session expect index stability.)"

The `new-version-ready` touch file mentioned in the brief is redundant (the
server does not poll it) and the absolute path `/var/arxmcp/ops/new-version-ready`
is wrong for macOS (no `/var/arxmcp/` root). Drop the touch file. The operator
runbook documents manual restart after confirming the new staging version.

The risk during a delta run: if `corpus-version.json` in the ACTIVE dataset
(`var/arxmcp/index/lancedb/`) were updated during a query, BP1/BP2 cache
discipline would break. Under the staging discipline this cannot happen —
the active `corpus-version.json` is never written during a delta run. The
concern is only relevant in E11_S05 (cutover), not E11_S02.

### `ops/oai-pmh-state.json` schema

```json
{
  "last_harvest_date": "2026-05-14",
  "last_resumption_token": null,
  "last_successful_run_utc": "2026-05-15T02:14:37Z",
  "last_run_paper_count": 143,
  "last_run_duration_seconds": 847
}
```

`last_resumption_token` is set to the in-progress token during a run and
nulled on successful completion. On restart, if `last_resumption_token` is
non-null AND `last_harvest_date` matches today, the run resumes from the
saved token. If `last_harvest_date` is prior to today, the token is expired —
discard and re-harvest from `last_harvest_date`.

---

## Open questions

None that must be resolved before writing code.

The following are scoped decisions the implementer should document:
1. **Four per-set calls vs single `set=math` call:** use four calls
   (`math:math:AG`, `math:math:NT`, `physics:math-ph`, `physics:hep-th`).
   The `set=math` umbrella pulls unwanted categories.
2. **Withdrawn paper `papers` table upsert:** confirm that `write_chunks`
   does NOT upsert to the `papers` table (it only writes chunks). The delta
   loop needs a separate `write_paper_metadata` step using OAI-PMH
   `arXivRaw` metadata. Mark withdrawn papers with `withdrawn=true` in
   the metadata upsert; do not delete chunks.
3. **First-run initialization:** if `oai-pmh-state.json` does not exist,
   default to harvesting yesterday's date. No full backfill.

---

## External writes the implementation will require

None. All operations are local reads/writes:

| Type | Target | Why |
|---|---|---|
| HTTP GET (read-only) | `https://oaipmh.arxiv.org/oai` | OAI-PMH metadata harvest; no side effects on arXiv |
| HTTP GET (read-only) | `https://ar5iv.labs.arxiv.org/html/<paper_id>` | Per-paper source fetch; no side effects |
| HTTP GET (read-only) | `https://export.arxiv.org/e-print/<paper_id>` | LaTeXML fallback only; no side effects |

No pushes, PRs, tickets, infra mutations, or write-side API calls are required.
