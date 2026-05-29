# Implementation Summary — notebook-surface-expansion-m1

**One-liner:** The notebook-detail page now shows a notebook-scoped parse-status
badge + a "Last indexed / Never indexed" freshness line, server-rendered on page
open. (Epic e1 — UI completion.)

**Commit range:** `<base>..<head>` (filled at finalize).
**Implementation path:** inline — 3 files (handler + template + a new test).

---

## What landed

### `server/routes/ui.py`
- New `_PARSE_STATUS_CSS` map (parse_status enum → the shared
  `.status-badge--{ok,warn,down}` classes from m4), with a `.get(..., "warn")`
  forward-compat fallback for unknown future statuses.
- `ui_notebook_detail` now fetches `latest_run = await
  store.get_latest_ingest_run(slug)` (one O(1) call, NOT per paper) and passes
  `latest_run` + `parse_status_css` into the template context. `parse_status` was
  already present on the `notebook` dict from the existing `get_notebook` call.

### `frontend/templates/notebook_detail.html`
- Two rows added to the notebook-header `<dl class="meta">` (outside the papers
  loop): a **Parse status** badge (`notebook.parse_status | default('unknown', true)`)
  and a **Last indexed** line (`latest_run.finished_at or latest_run.started_at`
  + the run status, or "Never indexed" when `latest_run` is None). A comment warns
  against ever adding `| safe` (the autoescape env is the XSS guard).

### `tests/test_notebook_detail_status.py` (new, 4 tests)
Self-contained (mirrors the `test_ui_html_pages.py` fixture; seeds via the REST
create + a raw-sqlite3 ingest-run INSERT to avoid the async-lock cross-loop
issue; no model load). Covers: arxiv default `skipped` badge + "Never indexed"
(also FM-a zero-papers); a finished run → `finished_at` + "ingest success", no
"Never indexed"; a running run with NULL `finished_at` → `started_at` fallback;
FM-d a future unknown status → rendered literally + `status-badge--warn`.

---

## Acceptance criteria status

- [x] **AC1 (G/W/T)** — opening `/ui/notebooks/{slug}` shows the parse status +
  a freshness signal. **DEVIATION (see below):** rendered as a notebook-scoped
  badge, NOT a per-paper column.
- [x] **AC2** — handler + template annotate with `parse_status` (already fetched)
  + the latest ingest-run timestamp; NO schema migration.
- [x] **AC3** — a UI-render test (TestClient + seeded notebooks.db, no model
  load) asserts the badge + the freshness signal (4 tests).

## Deviations from the brief (recorded — both researchers concurred)

1. **Notebook-scoped parse-status badge, NOT a per-paper column.** The roadmap's
   m1 brief assumed `parse_status` is a per-paper column on `notebook_papers`; it
   is actually on the `notebooks` table (per-notebook, v3→v4 textbook-ingest
   migration). `list_papers` returns only `{paper_id, added_at}`. Per-paper parse
   tracking does not exist and a schema change is explicitly prohibited by AC2;
   per-paper "indexed?" state would need per-paper LanceDB queries (out of scope
   for an S read-only milestone). So AC1's "each paper row shows its parse status"
   is realized as "the page shows the notebook's parse status" — a notebook-scoped
   badge in the header meta. Faithful to the AC's intent.
2. **Enum values corrected** to `skipped/pending/running/complete/failed` (the
   roadmap said `pending/parsing/parsed/failed/skipped` — wrong).
3. **FM-c (NULL parse_status) is unreachable** — the column is NOT NULL with
   DEFAULT 'skipped'; the template `| default('unknown', true)` is belt-and-
   suspenders only. FM-d (a future unknown enum value) IS reachable and is tested.

## Test surface

New: `tests/test_notebook_detail_status.py` (4). Changed: `server/routes/ui.py`,
`frontend/templates/notebook_detail.html`.

## Security (e1 `security-reviewer` lens)

`parse_status` is a server-written enum; timestamps are server-written; Jinja2
autoescape is ON (explicit at `server/routes/ui.py`). The badge + freshness line
are XSS-safe. No `| safe` introduced (a template comment warns m2 off it).

## External writes required

**None.** Purely local. No git push (Phase 4, per-event), no MCP-schema re-pin,
no infra. (m3 — constitution refresh + the FILED UI-security-audit issue — is the
only external write in this epic's Now lane; separate milestone.)
