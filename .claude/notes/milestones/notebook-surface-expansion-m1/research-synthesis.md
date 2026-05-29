# Research Synthesis — notebook-surface-expansion-m1

**Milestone:** Notebook detail page shows ingest status + per-notebook freshness
**Epic:** e1 (UI completion) of the `notebook-surface-expansion` roadmap
**Mode:** standard (2× Sonnet, parallel)
**Sources:** research-brief-1.md (in-codebase), research-brief-2.md (UI-security +
failure modes)

---

## TL;DR — what to build (CORRECTED from the brief)

Server-side render in `server/routes/ui.py::ui_notebook_detail`:
1. A **notebook-scoped parse-status badge** from the already-fetched
   `notebook["parse_status"]` (NOT a per-paper column — see RESOLVED below).
2. A **per-notebook freshness line** — "Last indexed `<ts>`" / "Never indexed" —
   from one O(1) `await store.get_latest_ingest_run(slug)` call.

Both render in the notebook-header/ingest section, OUTSIDE the `{% for p in
papers %}` loop. No `notebooks.db` schema change. No new route, no htmx poll
(v0). No MCP tool / `tools/list` / BP1 impact. No external writes.

This is INLINE-sized: `server/routes/ui.py` (handler) +
`frontend/templates/notebook_detail.html` (template) + a UI-render test. ~3
files.

---

## RESOLVED (both briefs flagged the SAME load-bearing conflict)

**The roadmap's m1 brief is WRONG on two counts; both researchers caught it:**

1. **`parse_status` is per-NOTEBOOK, not per-paper.** It is an `ALTER TABLE`
   column on the `notebooks` table (v3→v4 migration, textbook-ingest-m6),
   tracking the whole-notebook parse state. `notebook_papers` has ONLY
   `paper_id` + `added_at` — `list_papers()` returns
   `[{"paper_id": r[0], "added_at": r[1]} ...]` (notebooks_store.py:406-413). The
   brief said "reusing parse_status on the `notebook_papers` rows" — that column
   does not exist. **Resolution (interpretation (a), both briefs concur): render
   the notebook-level `parse_status` ONCE as a notebook-scoped badge, NOT a
   per-paper column.** Per-paper parse tracking would need a new table /
   migration, which the AC explicitly prohibits ("NO notebooks.db schema
   change"), and per-paper "indexed?" state would need per-paper LanceDB queries
   (expensive, out of scope for an S read-only milestone). `notebook["parse_status"]`
   is already in the template context via the existing `store.get_notebook(slug)`
   call — zero extra query.
   - **DEVIATION recorded:** AC1's "each paper row shows its parse status" is
     re-read as "the page shows the notebook's parse status near the paper list"
     (a notebook-scoped badge). Grounded in the schema; faithful to the AC's
     intent ("operator can see ingest/parse state on the detail page").
2. **The enum values in the roadmap are wrong.** The roadmap said
   `pending/parsing/parsed/failed/skipped`. The ACTUAL `PARSE_STATUS_*` constants
   (notebooks_store.py:601-605) are **`skipped` / `pending` / `running` /
   `complete` / `failed`** (no "parsing", no "parsed"). Use the real values.

## In-codebase facts (verbatim, brief-1 + brief-2)

- **`ui_notebook_detail` (server/routes/ui.py:195-245)** already calls
  `store.get_notebook(slug)` → `notebook` dict carries `parse_status`,
  `parse_error`, `notebook_kind`, `display_name`, etc.; and `store.list_papers(slug)`
  → rows of `{paper_id, added_at}`, annotated with `has_preview`. Context today:
  `{"notebook": dict, "papers": list[dict]}`. **Add** `latest_run` to the context.
- **`get_latest_ingest_run(slug)` (notebooks_store.py:507-529)** returns
  `{id, slug, status, started_at, finished_at, exit_code, stderr_tail}` or `None`
  (never ingested). Freshness rule: use `finished_at` when status is
  `success`/`failed`, `started_at` when `running`, "never indexed" when `None`.
- **Jinja2 autoescape is ON, explicit** (server/routes/ui.py:85-92,
  `select_autoescape(enabled_extensions=("html","htm","xml"), default_for_string=True)`),
  a deliberate m8 "explicit > implicit" decision. Grep confirms ZERO `| safe`
  filters + ZERO `{% autoescape false %}` blocks across all templates.
- **`notebook_detail.html`** papers table is 4 columns (Paper ID / Added /
  Preview / Remove) with an existing `{% if not papers %}` empty-state guard
  (lines 104-150). The status badge + freshness `<p>` go in the header/ingest
  section, OUTSIDE the papers loop.
- **Test pattern (tests/test_ui_html_pages.py:43-80):** a `client` fixture builds
  a minimal `FastAPI()` + a real `NotebooksStore` on a tmp `notebooks.db`, mounts
  `notebooks_router` (/ui/api) + `ui_router` (/ui) + static, via
  `asyncio.new_event_loop()` + `loop.run_until_complete`. Mirror it; seed an
  ingest run with `store.insert_ingest_run` + `store.update_ingest_run`.

## Security (brief-2 — the e1 `security-reviewer` lens)

- **XSS-safe.** `parse_status` is a server-written ENUM (only writer:
  `update_parse_status`, from the route layer post-subprocess; arxiv-kind is
  always `'skipped'`). Timestamps are server-written. Autoescape covers any edge.
  The status badge + freshness line are safe.
- **`display_name`** IS operator free text and is already rendered
  (`notebook_detail.html:11`) — safe ONLY because autoescape is on. m1 must NOT
  introduce `| safe` anywhere; add a comment near `display_name` so m2 (which
  makes it editable) cannot silently add `| safe` and create stored XSS.
- Threat model (08-security-observability-ops.md): localhost-only single-operator;
  the realistic threat is adversarial content in operator/agent-controlled fields
  rendered unescaped — autoescape is the guard.

## Failure modes → must-handle (brief-2)

- **Zero papers** → existing `{% if not papers %}` guard; the status badge +
  freshness are notebook-scoped (outside the loop), render regardless.
- **`get_latest_ingest_run` is None** → template `{% if latest_run and
  latest_run.finished_at %}…{% else %}Never indexed{% endif %}` (None-check in
  the template, not assumed non-None).
- **NULL/unknown `parse_status`** (legacy row) → coerce
  `notebook["parse_status"] or "unknown"` in the handler; render "-"/literal.
- **Forward-compat enum** (a future status value) → render the value literally
  (autoescaped); a CSS-class lookup uses `.get(status, "unknown")`, never a bare
  match without a wildcard.
- **N+1** → use the already-fetched `notebook` dict for parse_status + ONE O(1)
  `get_latest_ingest_run` call; do NOT add a per-paper query.
- **`| safe` regression** → don't add it; comment near `display_name`.

## Render-vs-poll

Server-side render for m1 (the AC says "on page open"; all data is in the handler
already). An htmx live-poll (the m4 `/ui/status-badge` `hx-trigger="every Ns"`
pattern) is OPTIONAL polish / a follow-up — NOT in m1.

## Acceptance criteria → artifacts (with the deviation noted)

| AC | Artifact |
|---|---|
| AC1 (G/W/T): opening the detail page shows ingest/parse status + freshness | a notebook-scoped parse-status badge (per-notebook, not per-paper — RESOLVED) + a "last indexed / never indexed" line in `ui_notebook_detail` + template |
| AC2: handler + template annotate with parse_status + latest ingest-run ts; no migration | `notebook["parse_status"]` (already fetched) + `get_latest_ingest_run`; no schema change |
| AC3: UI-render test (TestClient + seeded notebooks.db, no model load) | mirror `test_ui_html_pages.py`; assert badge + "last indexed" + a "never indexed" case |

## Deviations from the brief (recorded)

1. **Notebook-scoped status badge, NOT a per-paper column** — `parse_status` is
   per-notebook (on `notebooks`); per-paper does not exist and a schema change is
   prohibited by the AC. Both researchers independently reached this.
2. **Enum values corrected** to `skipped/pending/running/complete/failed`.

## Open questions

- Both briefs' single open question (per-paper vs per-notebook) is RESOLVED above
  (interpretation (a): notebook-scoped badge). No blockers remain — proceed inline.

## External writes the implementation will require

**None.** Purely local: `server/routes/ui.py`,
`frontend/templates/notebook_detail.html`, a new/extended UI-render test. No git
push (Phase 4, per-event), no MCP-schema re-pin, no infra.

## Orchestrator synthesis note

The two briefs CONVERGED exactly — both independently flagged the per-paper vs
per-notebook `parse_status` schema mismatch in the roadmap brief and both
recommended interpretation (a) (a notebook-scoped badge). No divergence to
resolve; the only "conflict" was brief-vs-codebase, resolved in favor of the
codebase (parse_status is per-notebook; the roadmap's per-paper + enum wording
were both wrong). Low parallel-collision risk: the concurrent
`corpus-integrity-observability-*` sessions touch `server/health.py` /
`server/metrics.py` / `ingest/`, not `server/routes/ui.py` or the template.
