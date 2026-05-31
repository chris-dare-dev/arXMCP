# Research Synthesis — onboarding-uplift-m3

**Merged from:** research-brief-1.md (seam map + file:line evidence) +
research-brief-2.md (LanceDB MVCC + atomic-rewrite pattern + 10 FMs).
**Generated:** 2026-05-31.
**Verdict:** INLINE — ~6-8 files, ~450 LOC main + tests + tools + Make + UI.
Two material brief corrections (D1 + D2 below); two design refinements
(D3 + D4); one CLI hygiene additive (D5). Purely local. **No BP1/BP2
touch** (new endpoints at `/ui/api/`, NOT `/mcp/`).

---

## 1. The locked design

**Three new REST endpoints** in `server/routes/notebooks.py` (NOT a new
file — same router, same `get_notebooks_store` dependency, same audit
logger):

1. **`POST /ui/api/admin/repair-registry`** — walks `NOTEBOOKS_BASE`,
   finds on-disk dirs with a valid `corpus-version.json` marker that
   are NOT in `notebooks.db::notebooks`, registers each via
   `NotebooksStore.create_notebook(...)`. Per-dir error handling for
   malformed markers (FM-7 mitigation). Returns:
   ```json
   {"registered": ["slug-a"], "already_registered": ["slug-c"],
    "skipped_no_marker": ["empty-dir"], "skipped_malformed_marker": ["bad-json"]}
   ```
2. **`POST /ui/api/notebooks/<slug>/reconcile-marker`** — opens
   per-notebook LanceDB at the marker's pinned `version` (MVCC
   snapshot — FM-1 safe), recounts `chunk_count` + distinct
   `paper_id`s, rewrites the marker JSON atomically via the
   `ingest/store.py::write_corpus_version_marker` pattern verbatim.
   Returns:
   ```json
   {"before": {"chunk_count": 824, "paper_count": 1},
    "after": {"chunk_count": 5266, "paper_count": 12},
    "drift_resolved": 4442}
   ```
3. **`GET /ui/api/notebooks/<slug>/health`** — opens per-notebook
   LanceDB at the marker's pinned version, runs `count_rows()`,
   returns per-notebook drift report. Live recount per call (see §3 D1).

**Two new Make targets** following the m2 dual-mode pattern:

- `make repair-registry` — curl `POST /ui/api/admin/repair-registry`
  server-up; `python -m tools.notebook_repair_registry` server-down.
- `make reconcile [NOTEBOOK=<slug>]` — curl
  `POST /ui/api/notebooks/<slug>/reconcile-marker` server-up;
  `python -m tools.notebook_reconcile_marker [<slug>]` server-down.
  Omitting `NOTEBOOK=` reconciles the shared global marker at
  `var/arxmcp/index/lancedb/corpus-version.json`.

**Two new server-down CLI tools** (mirroring the m2 pattern):

- `tools/notebook_repair_registry.py` — direct `NotebooksStore.open`
  + walk + `create_notebook` per missing slug.
- `tools/notebook_reconcile_marker.py` — direct `open_chunks_table` +
  `tbl.count_rows()` + atomic marker rewrite.

**UI badge tooltip extension** in `server/routes/ui.py::ui_status_badge`
— add a static `<small>` block (NOT `<details>`, see §3 D2) inside the
`<span>` that renders ONLY when status is `warn` or `fail`. The block
names the failing check (`corpus:version drift`, `notebooks:count
mismatch`, etc.) AND the remediation Make command. No raw paths.

**Makefile tidy-up (m2 F8 deferred LOW)** — split the 219-char one-line
`.PHONY` declaration into per-section groups (FIRST-TIME, EVERYTHING-ELSE,
m3 tidy-up).

---

## 2. Load-bearing facts (both briefs concur)

- **LanceDB checkout is in-place mutation that pins a snapshot.** R2
  quotes `server/corpus.py`: *"`tbl.checkout(N)` is an in-place mutation
  of the table object that pins reads to version `N`. … `open_chunks_table`
  returns a fresh table handle per call."* `tests/test_mvcc.py::TestVersionPinning::test_checkout_pre_and_post_second_write`
  is the live-verified contract: `checkout(v_a).count_rows()` returns
  `v_a`'s count even after a new version is added. **A concurrent ingest
  producing v+1 CANNOT race the reconcile recount** (FM-1 mitigation by
  MVCC alone). Implementation MUST pass `version=marker_info.version`
  explicitly — NEVER `version=None`.
- **Atomic JSON rewrite pattern is canonical** in `ingest/store.py:757-766`:
  ```python
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
  Tmp is co-located with target (same filesystem → POSIX-atomic
  `os.replace`). Cross-filesystem tmp trap (R2's memory entry): do NOT
  use `tempfile.NamedTemporaryFile(dir=None)` (lands in `/tmp`,
  different filesystem). **Copy this pattern verbatim into
  `reconcile-marker`.**
- **`NotebooksStore.create_notebook(slug, display_name, lancedb_path,
  created_at, notebook_kind="arxiv", parse_status=None)`** at
  `server/notebooks_store.py:330-376`. Raises `sqlite3.IntegrityError`
  on duplicate slug. The m3 `repair-registry` endpoint catches it →
  `already_registered` bucket.
- **`corpus-version.json` shape** (verbatim from
  `bridgeland-stability/lancedb/corpus-version.json`):
  ```json
  {"chunk_count": 10298, "chunker_version": "v1.1",
   "created_at": "2026-05-28T02:38:05Z",
   "embedder_version": "bge-m3@5617a9f6", "paper_count": 53,
   "version": 645}
  ```
  Reconcile preserves `version` / `chunker_version` / `embedder_version`
  / `created_at`, recomputes `chunk_count` + `paper_count`.
  `json.dumps(payload, sort_keys=True, separators=(",", ":"))` for
  byte-identical output on idempotent re-run.
- **REST surface conventions** from `server/routes/notebooks.py`:
  - Router at `server/main.py:738-740` includes
    `prefix="/ui/api"`.
  - Module-level `logger = logging.getLogger(__name__)` (line 74).
  - `get_notebooks_store(request)` dependency at lines 167-182 raises
    503 if store missing.
  - INFO audit-log pattern: `logger.info("action: slug=%s
    key=%s", slug, key)`.
- **No admin-auth gate exists.** All `/ui/api/*` routes are
  operator-trusted under loopback-only deployment
  (`server/config.py::reject_non_loopback` rejects non-loopback bind
  hosts). The new `/admin/` prefix is conventional, NOT a security
  boundary — no middleware needed (R1 §"Note on /admin/ prefix";
  R2 §"SecFetchSiteMiddleware").
- **Badge route still exists post-m1/m2** at
  `server/routes/ui.py:219-273`. Current fragment:
  ```python
  f'<span id="status-badge" class="status-badge status-badge--{css}" '
  f'aria-live="polite" aria-atomic="true" '
  f'hx-get="/ui/status-badge" hx-trigger="every 10s" '
  f'hx-swap="outerHTML" title="{safe}">{safe}</span>'
  ```
  `_classify_status_badge` at lines 178-216 already identifies which
  checks are failing — the tooltip helper reads from `report["checks"]`.
- **BP1/BP2 hashes stay UNCHANGED:**
  `EXPECTED_TOOL_SCHEMA_SHA256 = c7df4c5c…d13375`
  (`tests/test_server_tool_schema.py:95`);
  `EXPECTED_BP1_SHA256 = 483344e3…58959bc`
  (`tests/test_prompts.py:649-650`). Confirm via the existing test
  files.

---

## 3. Divergences resolved (orchestrator synthesis note)

### D1 — Per-notebook health endpoint: cached `startup_chunk_count` vs live recount

The brief's cardinal-safety check said: *"The `health` endpoint MUST
NOT cause an expensive scan on every request — use the pre-cached
`Resources.startup_chunk_count` / `startup_unindexed_rows` for the
actual values rather than re-counting per call."*

**R1 flags this as wrong** (§6, marked CRITICAL DESIGN QUESTION):
> `Resources.startup_chunk_count` is the SHARED GLOBAL corpus count
> (from `config.lancedb_path` = `var/arxmcp/index/lancedb/`), NOT
> per-notebook. There is no cached per-notebook count in `Resources`.

R2 §"FM-5" + Open Question 2 concurs.

**RESOLVED → R1 + R2 win. The brief was wrong. Live-recount per call.**

Reasoning:
1. The cached values are per-server-startup, not per-notebook. Using
   them for a per-notebook endpoint would conflate two scopes.
2. The per-notebook `GET /ui/api/notebooks/<slug>/health` is an
   operator-triggered diagnostic, NOT a hot poll (operators invoke it
   when investigating; the badge auto-poll uses the SHARED `/status`
   endpoint at 10s intervals).
3. A per-notebook startup cache is m6 scope (per-notebook freshness UI
   panel).

**Implementation:** the handler does (a) read marker via
`server.corpus.read_corpus_version(notebook_lancedb_path)`, (b) open
LanceDB at pinned `marker_info.version`, (c) `tbl.count_rows()`, (d)
return drift report. FM-5 is mitigated by documenting that the
endpoint is on-demand only (the badge auto-poll uses the cheap shared
`/status` path).

### D2 — Badge tooltip: `<details>/<summary>` vs static `<small>` block

R1 §"Recommendation" proposed `<details>/<summary>` nested in the
`<span>`. R2 §"Badge swap" + Recommendation argues against it: the
`hx-swap="outerHTML"` 10s poll DROPS the `<details>` `open` state on
every swap, snapping the tooltip closed.

**RESOLVED → R2 wins. Use a static `<small>` block.**

Reasoning:
1. The badge polls every 10s; an `outerHTML` swap replaces the entire
   `<span>` including any nested `<details>`. The `open` attribute is
   not preserved.
2. Adding JS to save/restore the `open` state across swaps is a
   no-build-chain violation (CLAUDE.md §4.7 ban on Node / SPA).
3. A static `<small>` block visible-when-degraded is simpler, has no
   open-state hazard, and is operator-readable at a glance — which is
   the whole point of the tooltip.

**Implementation:** the fragment becomes:
```python
remediation_block = ""
if css != "ok":
    # Build a "<small>" block listing failing checks + remediation.
    lines = _build_remediation_lines(report["checks"])
    remediation_block = (
        '<small class="status-badge__remediation" aria-live="polite">'
        + "<br>".join(html.escape(line) for line in lines)
        + "</small>"
    )
fragment = (
    f'<span id="status-badge" class="status-badge status-badge--{css}" '
    f'…>{safe}{remediation_block}</span>'
)
```
The `_build_remediation_lines` helper inspects `report["checks"]`,
identifies failing ones, and maps each to a one-line operator hint
naming the remediation Make command. No raw paths (FM-6 mitigation).

### D3 — Distinct `paper_id` count API in LanceDB 0.30.2

R1 §4: `tbl.to_lance().to_table(columns=["paper_id"]).to_pandas()
["paper_id"].nunique()` OR `len(set(...to_pylist()))`.
R2 §"Distinct paper_id count": `tbl.to_arrow().column("paper_id").
unique().length()` — pure PyArrow, no pandas allocation.

**RESOLVED → R2's PyArrow approach.**

Reasoning: PyArrow's `compute.unique` is column-typed and avoids the
pandas import + dataframe allocation. Both work; PyArrow is faster
and has fewer dependencies. The reconcile path runs on operator-tens
of MB datasets — perf is not the bottleneck, but the cleaner approach
is the right default.

Implementation:
```python
import pyarrow.compute as pc
arrow_tbl = tbl.to_arrow()
chunk_count = tbl.count_rows()
paper_count = pc.count_distinct(arrow_tbl["paper_id"]).as_py()
```

### D4 — `created_at` on `reconcile-marker` rewrite

R1 doesn't address. R2 §FM-10: **PRESERVE the original `created_at`
from the existing marker** so repeated `make reconcile` runs produce
**byte-identical** output (true idempotency, not just same-data
idempotency).

**RESOLVED → R2 wins. Preserve `created_at` from the read marker.**

Implementation:
```python
old = read_corpus_version(notebook_lancedb_path)  # CorpusVersionInfo
new = old.with_counts(chunk_count=new_chunk_count, paper_count=new_paper_count)
# `with_counts` is a NEW helper on CorpusVersionInfo that returns a
# copy with chunk_count + paper_count overridden; everything else
# (including created_at) preserved.
write_corpus_version_marker(notebook_lancedb_path, new)
```
Add `with_counts` to `CorpusVersionInfo` (small additive change in
`server/corpus.py`).

### D5 — `busy_timeout` on CLI SQLite paths

R2 §"SQLite WAL + busy_timeout" notes that `NotebooksStore._open_sync`
does NOT set explicit `busy_timeout`. The m2 pattern in CLI tools
already sets `PRAGMA busy_timeout=5000`. m3's CLI fallbacks (the new
`tools/notebook_repair_registry.py` + `tools/notebook_reconcile_marker.py`)
follow the same pattern — when they open a sync `sqlite3.Connection`
to `notebooks.db`, set `PRAGMA busy_timeout=5000`.

**RESOLVED → adopt. m3's CLI tools set busy_timeout=5000 explicitly.**
This is additive to the existing m2 pattern (the m2 tools already do
this; m3 inherits).

---

## 4. Failure modes → required handling (R2's enumeration, condensed)

- **FM-1 (concurrent ingest vs reconcile read):** SOLVED by MVCC
  checkout-at-version. Implementation MUST pin to
  `marker_info.version` — never `version=None`.
- **FM-2 (concurrent ingest vs reconcile rewrite):** `os.replace` is
  atomic (file is never partially-written); the residual stale-window
  race is ~seconds and self-heals on the next ingest write.
  **ACCEPTABLE per the single-operator threat model.**
- **FM-3 (stale leftover dir):** by-design. `repair-registry`
  registering an on-disk dir with a valid marker is correct; operators
  delete via `DELETE /ui/api/notebooks/<slug>`.
- **FM-4 (registry walk during mid-flight ingest):** `skipped_no_marker`
  case heals on next run; stale-count case heals via reconcile.
- **FM-5 (health endpoint hot-poll):** documented as operator-triggered
  diagnostic; cache is m6 scope. NOT a 10s auto-poll target.
- **FM-6 (badge tooltip path leak):** tooltip body uses slug + Make
  command, NO raw paths. Enforced in the tooltip-builder helper.
- **FM-7 (malformed marker JSON):** per-dir try/except catches
  `JSONDecodeError` + `ValueError`; add slug to
  `skipped_malformed_marker` bucket; log WARN; DO NOT abort the walk.
- **FM-8 (reconcile against missing marker):** return 422 with
  `{"error": "no marker; run make ingest first"}`. `read_corpus_version`
  returns `None` when file absent → short-circuit.
- **FM-9 (concurrent restic backup):** WAL semantics handle it; CLI
  paths add `busy_timeout=5000` per D5.
- **FM-10 (reconcile idempotency):** SOLVED by D4 (preserve `created_at`).

---

## 5. Acceptance criteria — restated with implementation handles

- **AC1** `POST /ui/api/admin/repair-registry` finds shimura-varieties
  + bridgeland-stability (if their SQLite rows were deleted) and
  re-registers via `NotebooksStore.create_notebook`. Idempotent
  (re-run: zero new rows; `already_registered` populated). Returns
  structured response with all 4 buckets.
- **AC2** `POST /ui/api/notebooks/<slug>/reconcile-marker` against a
  drift-poisoned marker recomputes + rewrites with `os.replace`.
  Audit-logged INFO with before/after delta. Idempotent (D4).
- **AC3** `GET /ui/api/notebooks/<slug>/health` returns drift report
  with `status: "ok" | "drift" | "stale"` correctly classified.
- **AC4** `make repair-registry` + `make reconcile [NOTEBOOK=<slug>]`
  work server-up (curl) and server-down (direct Python). Idempotent.
- **AC5** `/ui/status-badge` renders the static `<small>`
  remediation block (NOT `<details>` — D2) naming check + Make
  command when degraded/warn.
- **AC6** Makefile `.PHONY` split per-section (closes m2 F8).
- **AC7** `make test` green, `ruff check .` clean.
- **AC8** `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256`
  UNCHANGED.
- **AC9** New regression tests for each endpoint + each Make target +
  the badge tooltip rendering.

---

## 6. Implementation order

1. **`server/corpus.py`** — add `CorpusVersionInfo.with_counts(chunk_count,
   paper_count)` helper. ~10 LOC.
2. **`server/routes/notebooks.py`** — add 3 new handlers
   (`repair_registry`, `reconcile_marker`, `notebook_health`), Pydantic
   response models, INFO audit logs. ~180 LOC.
3. **`server/routes/ui.py`** — extend `ui_status_badge` with the
   static `<small>` remediation block + `_build_remediation_lines`
   helper. ~40 LOC.
4. **`tools/notebook_repair_registry.py`** (NEW) — server-down CLI;
   `NotebooksStore` + walk + create_notebook. ~80 LOC.
5. **`tools/notebook_reconcile_marker.py`** (NEW) — server-down CLI;
   open lancedb at pinned version, recount, atomic rewrite. ~90 LOC.
6. **`Makefile`** — add `repair-registry` + `reconcile` recipes; split
   `.PHONY` per-section. ~60 LOC.
7. **`tests/test_admin_endpoints.py`** (NEW) — `repair_registry` tests
   (idempotent, malformed-marker handling, empty-dir skip). ~150 LOC.
8. **`tests/test_reconcile_endpoint.py`** (NEW) — drift-poisoned
   marker → recount + rewrite + idempotency (byte-identical re-run).
   ~150 LOC.
9. **`tests/test_notebook_health.py`** (NEW) — status classification
   (ok / drift / stale). ~100 LOC.
10. **`tests/test_make_targets_m3.py`** (extends or new) — dual-mode
    verification for `make repair-registry` + `make reconcile`. ~120 LOC.

---

## 7. Open questions

**None blocking.** All open questions from both briefs resolved in §3
D1-D5.

## 8. External writes required

**None.** Purely local. Both briefs concur.
