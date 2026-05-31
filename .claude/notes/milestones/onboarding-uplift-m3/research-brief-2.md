# Research Brief — onboarding-uplift-m3

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-31T00:00:00Z

## In-codebase context

### LanceDB MVCC — checkout-at-version contract (verified in tests)

`server/corpus.py` docstring (verbatim, load-bearing):

> "checkout mutates in place. `tbl.checkout(N)` is an in-place mutation of the table
> object that pins reads to version `N`. A shared/cached table reference passed to
> `checkout` would corrupt other readers' views. `open_chunks_table` therefore returns
> a **fresh table handle per call** — closes F1 from the E04_S02 critique by relying
> on `lancedb.connect` returning a fresh `Connection` per invocation."

And from `server/corpus.py` on write-safety:

> "Writes raise `ValueError` from LanceDB's own write guard ('table cannot be modified
> when a specific version is checked out') — no defensive wrapper is added on this side."

`tests/test_mvcc.py::TestVersionPinning::test_checkout_pre_and_post_second_write` demonstrates
(live, not mocked) that after writing version `v_b`, `checkout(v_a).count_rows()` still
returns the `v_a` count. The MVCC snapshot is stable. A concurrent `add()` producing `v_b+1`
while the reconcile endpoint holds `v_a` cannot affect `count_rows()` at `v_a`.

**For the per-notebook LanceDB** in `reconcile-marker`: the same contract applies. Open a
fresh handle with `open_chunks_table(notebook_lancedb_path, version=marker_version)`, call
`count_rows()`, then call `count_distinct(paper_id)`. This is safe even if a concurrent ingest
is producing new versions against the same dataset directory.

**Caveat on distinct paper_id count**: LanceDB does not expose a native `count_distinct` SQL
aggregation at the Python level in `lancedb==0.30.x`. Use
`tbl.to_arrow().column("paper_id").unique().length()` or a PyArrow `value_counts` — both read
the snapshot at the pinned version. Confirmed via `ingest/store.py` which uses similar PyArrow
aggregations (see `write_chunks` at line 890+).

### Atomic JSON rewrite — existing pattern confirmed

`ingest/store.py::write_corpus_version_marker` (line 757–766, verbatim):

```python
# Atomic write — copy of preamble._write_preamble_json's pattern.
tmp = out_path.with_suffix(
    f"{out_path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
)
try:
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, out_path)
finally:
    with contextlib.suppress(OSError):
        tmp.unlink(missing_ok=True)
```

The tmp file is **co-located with the target** (same `lancedb_path/` directory) so
`os.replace` is POSIX-atomic on the same filesystem. The reconcile-marker endpoint
MUST copy this pattern verbatim — it rewrites the same file type.

**Important**: the existing `write_corpus_version_marker` uses `json.dumps(doc, sort_keys=True)`.
The reconcile rewrite must also use `sort_keys=True, separators=(",", ":")` to produce
byte-identical output for identical content (idempotency requirement from AC2 + FM-10).

### Badge swap — existing `hx-swap="outerHTML"` contract

`server/routes/ui.py::ui_status_badge` returns a `<span>` fragment with `hx-swap="outerHTML"`.
The existing template `frontend/templates/base.html` has the badge as a `<span>` with `id="status-badge"`.
The badge polls every 10s (`hx-trigger="every 10s"`). Extending to `<details>` requires the
**outer element to remain `<span id="status-badge">`** to maintain the swap target; the `<details>`
element must be INSIDE the span, not the outerHTML root itself.

**hx-preserve hazard**: `hx-preserve` on a `<details>` element would prevent the badge from
updating state (the whole span is frozen), which defeats the purpose. Instead, the `<details>`
`open` attribute should persist across swaps naturally IF htmx preserves it — but `outerHTML`
replaces the element entirely, so the `open` state is LOST on each 10s poll. This means:

- If the user opens the tooltip `<details>`, it snaps closed every 10s.
- **Mitigation**: Use JavaScript to save/restore `open` state around each swap using
  `htmx:beforeSwap` / `htmx:afterSwap` events, OR use a CSS-only `<details>`-less tooltip
  (e.g. `title` attribute already used today + a `<small>` explanation block that's always
  visible when degraded). The `<details>` approach requires a JS workaround; a static
  sub-span visible only when `status != "ok"` is simpler and avoids the open-state problem.

### Badge tooltip — path-leak guard

The brief's cardinal check: "badge tooltip MUST NOT leak internal state (e.g. file paths)".
The existing badge uses `title="{safe}"` which carries the health summary string. The new
tooltip must produce only: `"drift in chunk_count for <slug>; run make reconcile NOTEBOOK=<slug> to heal"`.
No `var/arxmcp/notebooks/<slug>/lancedb/` path in the HTML output.

### NotebooksStore write-path discipline (m2 F1 lesson)

`server/notebooks_store.py::create_notebook` (line 330) takes the `asyncio.Lock` before any
write. Each method is serialized via `self._lock`. The `repair-registry` endpoint calling
`create_notebook` N times sequentially is safe — each call acquires/releases the lock
independently. No extra lock needed for the walk itself (disk-walk is read-only).

### Logging discipline (08-security-observability-ops.md)

Verbatim from `08-security-observability-ops.md`:

> "Sensitive fields (full query text, chunk bodies) are logged at DEBUG only, never at
> INFO or above."

For the repair/reconcile endpoints: the slug name and chunk count deltas are
**not sensitive fields** — they are operational facts the operator already knows. INFO
is correct for the audit trail ("reconcile: before=824, after=5266, drift=4442 for shimura-varieties").
The full marker JSON payload must NOT be logged at INFO (it's a file body, not just metadata).

### BP1/BP2 stability — confirmed safe

The new endpoints are at `/ui/api/admin/repair-registry`, `/ui/api/notebooks/<slug>/reconcile-marker`,
and `/ui/api/notebooks/<slug>/health`. These are FastAPI routes under the `ui.py` router — they
do NOT touch `server/tools.py::ALL_TOOLS`. AC8 holds: `EXPECTED_TOOL_SCHEMA_SHA256` and
`EXPECTED_BP1_SHA256` are UNCHANGED.

### SecFetchSiteMiddleware — new endpoints are exempt

The new REST endpoints are under `/ui/api/` which is already in the `exempt_prefixes` list
(the middleware exempts `/ui`). No `exempt_prefixes` change needed.

### SQLite WAL + busy_timeout

`notebooks_store.py::_open_sync` sets `WAL` mode. No explicit `busy_timeout` is set in the
store (grepped — returns empty). SQLite's default `busy_timeout=0` means concurrent writes
will raise `sqlite3.OperationalError: database is locked` immediately rather than waiting.
This is mitigated by the `asyncio.Lock` which serializes all NotebooksStore writes in-process,
but the CLI path (server-down Make targets) opens a separate SQLite connection with no lock
coordination.

**FM-9 risk is real but low**: if a CLI `repair-registry` and a running server's `create_notebook`
race, the CLI may get `database is locked`. The m2 pattern sets `busy_timeout` of 5000ms for
CLI paths — **check if `tools/_notebook_common.py` or direct SQLite CLI paths set this**. If not,
recommend adding `conn.execute("PRAGMA busy_timeout=5000")` in the server-down CLI path.

## Prior decisions and lessons

- **m2 F1 lesson (load-bearing)**: all `notebooks` table writes MUST go through
  `NotebooksStore.create_notebook`. Direct SQLite INSERTs are BANNED in m3.
- **m2 pattern — dual-mode Make targets**: server-up = curl; server-down = direct Python
  with same SQLite file. The `reconcile` and `repair-registry` Make targets must follow this.
- **cross-filesystem tmp trap** (from agent memory): `os.replace` is only POSIX-atomic when
  src and dst are on the same filesystem. The tmp file MUST be placed in the same directory
  as the target using `path.with_suffix(path.suffix + ".tmp")` (or the PID+UUID variant the
  existing code uses). DO NOT use `tempfile.NamedTemporaryFile(dir=None)` which defaults to
  `/tmp` — that is a different filesystem from `var/arxmcp/notebooks/<slug>/lancedb/`.
- **Git log**: recent commits show `ui-badge-disambiguate` closed (commit `ca2c274`). The badge
  already supports distinct DEGRADED vs WARN CSS classes. The m3 tooltip extension builds on
  that classification — it MUST preserve the existing `_classify_status_badge` logic and only
  ADD the `<details>` (or equivalent) explanation block.

## External sources

### LanceDB MVCC concurrency

The LanceDB versioning docs at `https://lancedb.github.io/lancedb/concepts/versioning/` returned
404 at the time of research. The project's own `tests/test_mvcc.py` provides the authoritative
live-verified contract: `checkout(N).count_rows()` returns N-rows even after a new version is
added. This is confirmed by the in-codebase docstring (quoted above) and the passing test suite.

The LanceDB Python API docs confirm `read_consistency_interval` controls when reads see new
versions, but a pinned `checkout(N)` is a true snapshot — it does not see writes that produce
versions > N.

**Conclusion**: `count_rows()` at pinned version N is consistent regardless of concurrent `add()`
operations producing version N+1 or later. No race guard is needed at the LanceDB level.

### FastAPI background tasks vs inline writes

FastAPI's `BackgroundTasks` runs the callback AFTER the response is sent. For `reconcile-marker`:
the response includes the `before`/`after` counts, which are only known after the recount. Therefore
the rewrite CANNOT be offloaded to `BackgroundTasks` — the write must complete inline.

The reconcile-marker endpoint does: (1) read marker JSON, (2) open LanceDB at pinned version,
(3) count rows, (4) write updated marker, (5) return response. Steps 1-4 are fast (sub-100ms for
a few-thousand-row table). Inline is correct and is the precedent in this codebase — all existing
`NotebooksStore` methods are inline async (no BackgroundTasks). The brief's cardinal check
confirms: "The `reconcile-marker` endpoint MUST NOT mutate the LanceDB itself — only rewrites the
JSON sidecar." The sidecar write is the cheapest possible IO operation.

**Rule from `08-security-observability-ops.md`**: no explicit "no inline writes" rule exists. The
project uses `asyncio.to_thread` for SQLite I/O (blocking) but JSON file writes are fast enough
to do inline in the async handler (mirroring `write_corpus_version_marker` usage from ingest).

### Atomic JSON rewrite — canonical Python pattern

The canonical pattern in this codebase (from `ingest/store.py:757–766`, confirmed above):

```python
tmp = out_path.with_suffix(f"{out_path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
try:
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, out_path)
finally:
    with contextlib.suppress(OSError):
        tmp.unlink(missing_ok=True)
```

`os.replace` is POSIX-atomic when src and dst are on the same filesystem. The `finally` block
prevents orphaned `.tmp` files on write failure. The implementer should copy this verbatim from
`ingest/store.py`, NOT use `tempfile.NamedTemporaryFile(dir=None)` which lands in `/tmp` (different
filesystem — NOT atomic per cross-filesystem-tmp-trap memory entry).

## Failure-mode enumeration

**FM-1 — Concurrent ingest rewrites LanceDB while reconcile-marker reads.**
Trigger: ingest runs `write_chunks` producing version N+1 while `reconcile-marker` opens at
pinned version N.
Symptom: if not using a version pin, `count_rows()` could return the in-flight partial count.
Mitigation: MVCC snapshot at `checkout(N)` is fully consistent — confirmed by test. The marker's
`version` field is the pin. Implementation must open `open_chunks_table(notebook_lancedb_path,
version=marker_info.version)` — NOT `version=None`.
Status: RESOLVED by design, IF implementation pins to `marker_info.version`.

**FM-2 — Concurrent ingest rewrites corpus-version.json while reconcile-marker rewrites it.**
Trigger: ingest's `write_corpus_version_marker` runs concurrently with `reconcile-marker`'s
own rewrite. Race window: ~milliseconds between `tmp.write_text()` and `os.replace()`.
Symptom: one rewrite wins; the other's count is set in the surviving file. If reconcile wins
AFTER ingest writes the new version, the marker version field may mismatch the actual LanceDB
version.
Mitigation: `os.replace` is atomic — the file is never partially written. But the CONTENT may
be wrong: `reconcile-marker` MUST preserve the `version` field from the marker it read (not
from the latest LanceDB version), so even if ingest has advanced the LanceDB to N+1, the
reconcile rewrite correctly references version N.
Residual risk: if ingest has advanced to N+1 AND written corpus-version.json with `version=N+1`,
and reconcile then overwrites it with `version=N` (stale), the marker now points at an obsolete
version. Mitigation: reconcile should read the marker, do the recount at that version, and write
back the SAME version field. It never looks at the live LanceDB tip. The ingest's next write will
overwrite the reconcile's marker with the new version. The residual stale window is ~seconds and
self-heals.
Status: ACCEPTABLE given the single-operator, single-workstation threat model.

**FM-3 — repair-registry registers a stale leftover dir for a deleted notebook.**
Trigger: operator deleted a notebook via `DELETE /ui/api/notebooks/<slug>` (metadata-only) but
did NOT run `tools/notebook_purge.py`. The on-disk dir still exists with a marker.
Symptom: `repair-registry` re-registers the slug as if it were a new notebook.
Mitigation: by design — the dir has a valid marker; registering it is correct. The operator can
delete it again via the API or purge via the tool.
Status: ACCEPTABLE — documented in the brief as by-design.

**FM-4 — repair-registry runs during an active mid-flight ingest.**
Trigger: ingest is writing chunks to a new (previously un-registered) notebook's LanceDB; at
that moment `repair-registry` walks the directory.
Symptom: the dir exists but `corpus-version.json` may not yet exist (written by `write_corpus_version_marker`
only after `write_chunks` completes). If the marker doesn't exist, `repair-registry` puts the dir
in `skipped_no_marker`. If the marker does exist (partial ingest), the chunk_count will be stale.
Mitigation: the `skipped_no_marker` case is correct — the dir will be registered on the next
`repair-registry` run after ingest completes. The stale-count case heals via `reconcile-marker`.
Status: ACCEPTABLE with no extra guard needed.

**FM-5 — GET /ui/api/notebooks/<slug>/health recounts LanceDB on every call.**
Trigger: operator script polls the health endpoint in a tight loop (N notebooks × M polls/sec).
Symptom: O(notebooks × rows) LanceDB scan on every call → CPU/IO spike; possible latency
regression for the MCP server's retrieval path (shared process).
Mitigation: the brief's cardinal check states: "The `health` endpoint MUST NOT cause an expensive
scan on every request — use the pre-cached `Resources.startup_chunk_count` / `startup_unindexed_rows`
for the actual values rather than re-counting per call." Implementation must read
`Resources.startup_chunk_count` (set at startup) for the "actual" value, not live-recount.
Status: MUST NOT recount per-call. Cache + invalidate on POST `reconcile-marker`.

**FM-6 — Badge tooltip leaks lancedb path.**
Trigger: tooltip renders `var/arxmcp/notebooks/<slug>/lancedb/` in the HTML output.
Symptom: path exposed in the DOM; observable via browser devtools (loopback-only but still noisy).
Mitigation: tooltip body must be structured: `"drift in chunk_count for <slug>; run make reconcile
NOTEBOOK=<slug> to heal"`. No raw paths. This is a cardinal check in the brief.
Status: MUST be enforced in the template/f-string building the tooltip.

**FM-7 — repair-registry finds a dir with malformed corpus-version.json.**
Trigger: partial write left a truncated/invalid JSON file in a notebook's lancedb dir.
Symptom: `json.loads()` raises `JSONDecodeError`; if uncaught, the endpoint 500s.
Mitigation: catch `json.JSONDecodeError` + `ValueError` per dir; log WARN; add the slug to a
`skipped_malformed_marker` bucket in the response. Do NOT abort the entire walk.
Status: MUST handle; `server/corpus.py::read_corpus_version` already raises `ValueError` for
malformed markers — catch it per-dir in the walk loop.

**FM-8 — reconcile-marker called for a notebook with no corpus-version.json yet.**
Trigger: notebook was scaffolded (created, papers added) but ingest was never run.
Symptom: `corpus-version.json` does not exist.
Mitigation: return 422 with `{"error": "no marker; run make ingest first"}`. DO NOT create an
empty marker file — that would produce a malformed marker that `read_corpus_version` would reject
as missing required fields, or worse, look like a valid marker with garbage counts.
Status: MUST return 422; `read_corpus_version` returns `None` when the file is absent — the
endpoint checks for `None` and short-circuits.

**FM-9 — Concurrent restic backup reads notebooks.db while repair-registry writes.**
Trigger: `ops/cron/arxmcp-backup.sh` runs `restic backup` while `repair-registry` calls
`NotebooksStore.create_notebook`.
Symptom: restic reads the WAL file; SQLite WAL mode allows concurrent readers while a writer
holds the write lock. The backup's file-level copy may be mid-transaction.
Mitigation: WAL mode (`journal_mode=WAL` confirmed in `notebooks_store.py:116`) allows readers
to proceed while a writer writes. The in-process `asyncio.Lock` serializes writes from the server
process. The `checkpoint_notebooks_db.py` script that runs `PRAGMA wal_checkpoint(TRUNCATE)` before
backup reduces this risk. Note: no explicit `busy_timeout` is set in `NotebooksStore._open_sync`;
adding `PRAGMA busy_timeout=5000` is low-cost insurance for the CLI path.
Status: LOW risk — WAL semantics handle this. CLI path should add `busy_timeout=5000`.

**FM-10 — reconcile-marker called repeatedly (idempotency).**
Trigger: operator runs `make reconcile NOTEBOOK=shimura-varieties` twice.
Symptom: if the second run produces a different JSON payload (e.g. different `created_at`
timestamp), the file is rewritten unnecessarily but idempotently (same chunk counts).
Mitigation: `write_corpus_version_marker` uses `json.dumps(sort_keys=True)` and the `created_at`
field is set to `datetime.now(UTC)` — so a re-run WILL produce a different timestamp and rewrite
the file. This is harmless (the important fields — `version`, `chunk_count`, `paper_count` — are
correct). The endpoint response will show `drift_resolved=0` on re-run, which is correct.
**Recommendation**: preserve the ORIGINAL `created_at` from the existing marker rather than
setting `datetime.now()` — this makes repeated runs produce byte-identical files (true idempotency).
Status: MUST preserve `created_at` from the read marker.

## In-codebase cross-check (lightweight)

1. **m2 critique F1 lesson consistency**: the brief explicitly states both endpoints route
   through `NotebooksStore.create_notebook`. Confirmed consistent with the m2 lesson and with the
   store's `asyncio.Lock` pattern.

2. **New endpoints are at `/ui/api/`**: confirmed — NOT under `/mcp/`. AC8 holds. Tool schema hash
   and BP1 hash are UNCHANGED. No `EXPECTED_TOOL_SCHEMA_SHA256` re-pinning needed.

3. **Badge tooltip `<details>` vs `hx-swap="outerHTML"`**: the existing badge is a `<span>` with
   `hx-swap="outerHTML"` polling every 10s. If the tooltip is a `<details>` child of the span,
   the `open` attribute is LOST on every 10s poll (htmx replaces the entire element). The
   `hx-preserve` attribute could prevent updates entirely. **Recommended mitigation**: implement
   the tooltip as a visually-hidden sub-element that becomes visible when status is degraded/warn,
   rather than a `<details>` toggle. This avoids the open-state problem while satisfying AC5.
   If `<details>` is required, document that the tooltip auto-closes every 10s (acceptable for
   an operator console).

4. **Audit-log level**: `08-security-observability-ops.md` states: "Sensitive fields (full query
   text, chunk bodies) are logged at DEBUG only, never at INFO or above." Slug names and chunk
   counts are NOT sensitive — they are operational metadata. INFO is correct for the repair/reconcile
   audit events. The full marker JSON payload (if logged) should be DEBUG.

## Recommendation

Implement `reconcile-marker` using the existing `write_corpus_version_marker` pattern from
`ingest/store.py` verbatim (PID+UUID tmp file co-located with target, `os.replace`, `sort_keys=True`,
`separators=(",", ":")`). Pin the LanceDB handle to `marker_info.version` (not `version=None`)
to get snapshot-consistent counts. Preserve `created_at` from the existing marker to achieve
true byte-identical idempotency on re-run.

For the badge tooltip: implement as a static `<small>` block inside the `<span>` that is rendered
only when `css` is not `"ok"` — not as a `<details>` element. This avoids the 10s auto-close
hazard and keeps the swap contract clean. The `<small>` block should carry no paths, only the
slug name + remediation Make command.

For `repair-registry`: per-directory try/except around `read_corpus_version` (catches `ValueError`
for malformed markers); accumulate `skipped_malformed_marker` list in response; use
`NotebooksStore.create_notebook` for each registration (sequential, lock-per-call is fine).

## Open questions

1. **Distinct paper_id count API**: confirm `tbl.to_arrow().column("paper_id").unique().length()` 
   works on the pinned table handle in `lancedb==0.30.2` for per-notebook tables (may differ
   from the global chunks table schema). Implementer should verify against the per-notebook schema.

2. **`GET /ui/api/notebooks/<slug>/health` — "actual_chunks" source**: the brief's cardinal
   check says "use pre-cached `Resources.startup_chunk_count`" — but `Resources` holds data for
   the GLOBAL corpus, not per-notebook. The per-notebook health endpoint either needs its own
   cached count (set at startup per notebook) or reads live from LanceDB (expensive). The
   `Resources` pattern for per-notebook counts does not currently exist. Implementer must decide:
   (a) read live at the cost of a scan (acceptable if `health` is not hot-polled), or (b) add
   a per-notebook cache dict to `Resources` populated at startup. **Recommend (a) for m3** —
   the health endpoint is not in the hot retrieval path, and per-notebook caching can be added
   in m6 (per-notebook freshness panel).

## External writes the implementation will require

None — this milestone is purely local.
