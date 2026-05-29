# Research Brief — notebook-surface-expansion-m1

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-29T15:50:00Z

---

## In-codebase context

### Jinja2 autoescape — confirmed ON, explicitly named

`server/routes/ui.py` lines 85–92 construct the Jinja2 environment with
autoescape stated explicitly in source:

```python
_env: jinja2.Environment = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=jinja2.select_autoescape(
        enabled_extensions=("html", "htm", "xml"),
        default_for_string=True,
    ),
)
templates: Jinja2Templates = Jinja2Templates(env=_env)
```

The inline comment (lines 78–84) explains this was a deliberate m8
"explicit > implicit" design decision: "a future template-loader change
can't silently regress it." This is the load-bearing autoescape guarantee.

**Grep confirms zero `| safe` filters and zero `{% autoescape false %}` blocks
across all three templates** (`base.html`, `index.html`, `notebook_detail.html`).
Every field rendered in the detail page — `notebook.slug`, `notebook.display_name`,
`notebook.lancedb_path`, `notebook.created_at`, `p.paper_id`, `p.added_at` — goes
through the Jinja2 autoescaper. The status column and freshness signal will inherit
this protection automatically.

### **CONFLICT: parse_status lives on `notebooks`, NOT `notebook_papers`**

**The milestone brief states:** "reusing the existing `parse_status` on the
`notebook_papers` rows (`list_papers`)"

**The actual schema (confirmed from `server/notebooks_store.py` lines 238–251 and
`list_papers` at lines 406–413):**

- `parse_status` is an ALTER TABLE column on the `notebooks` table (v3→v4 migration,
  textbook-ingest-m6). It tracks the whole-notebook parse state for textbook-kind
  notebooks.
- `notebook_papers` has only `paper_id` and `added_at`. `list_papers()` returns
  exactly `[{"paper_id": r[0], "added_at": r[1]} for r in rows]`.
- The five `parse_status` values (`skipped`, `pending`, `running`, `complete`,
  `failed`) apply to the notebook as a whole — not to individual arXiv papers.

**This means "per-paper parse status" as described in the brief does not exist in
the current schema.** The implementer must resolve this design gap before writing
code (see Open Questions).

### parse_status provenance — constrained enum, server-written only

`NotebooksStore.PARSE_STATUS_*` constants (lines 601–605) define the five legal
values. The only writer is `update_parse_status()` (line 607), called exclusively
from the route layer after subprocess completion. No user-controlled or
agent-controlled input path reaches this column. For arxiv-kind notebooks the column
is always `'skipped'` (column-level DEFAULT at migration time).

**XSS verdict:** `parse_status` is a server-controlled enum — not operator-supplied
free text. It is XSS-safe regardless of autoescape status. The same is true for
`notebook_kind` and all timestamp columns.

**`display_name` is operator-supplied free text.** It is already rendered in the
detail page (`notebook_detail.html` line 11: `{{ notebook.display_name }}`). With
autoescape ON this is safe. m2 will make `display_name` editable — the autoescape
guarantee must hold through that milestone. Flag: if any future template ever uses
`{{ notebook.display_name | safe }}` this becomes a stored-XSS vector.

### freshness timestamp — server-written, safe

`get_latest_ingest_run()` (lines 507–529) returns a dict read directly from
`notebook_ingest_runs` rows whose timestamps are written by `insert_ingest_run()`
and `update_ingest_run()` — server code, no user path. `finished_at` is an ISO
string set at task completion time. Rendering this in the template is safe.

### Current detail handler — no MCP tool surface, no BP1 impact

`ui_notebook_detail` in `server/routes/ui.py` is a `/ui/` HTML handler. It does not
touch `server/tools.py::ALL_TOOLS`, does not modify `EXPECTED_TOOL_SCHEMA_SHA256`,
and does not affect BP1/BP2 prompt-cache breakpoints. The `07-multi-agent-caching.md`
cache discipline is NOT affected by this milestone.

### N+1 query risk — already present, watch the pattern

The current handler already does 2 `os.stat()` calls per paper for `_preview_html_path`
(lines 233–240). The comment at line 228 notes: "Two filesystem stats per paper;
loopback-only deployment makes this cheap." The brief says "parse_status should come
from the already-fetched list_papers rows" — but since `parse_status` is on
`notebooks` (not `notebook_papers`), it is already fetched in the single
`store.get_notebook(slug)` call at line 217 and is available as `notebook["parse_status"]`
without any additional query. The freshness signal requires one additional
`await store.get_latest_ingest_run(slug)` call — O(1), not O(papers).

### `SecFetchSiteMiddleware` — not a concern for this milestone

The detail page is at `/ui/notebooks/{slug}` (under `/ui/`). The ingest-run
freshness endpoint `GET /ui/api/notebooks/{slug}/ingest/latest` is also under `/ui/`.
The `parse-status` endpoint at `GET /ui/api/notebooks/{slug}/parse-status` is also
under `/ui/api/`. No `SecFetchSiteMiddleware` cross-prefix issue.

---

## Prior decisions and lessons

From git log: the most recent prior work is `notebook-ops-hardening-m4`
(operability `/status` + UI badge). The m4 htmx live-poll pattern (fragment at
`/ui/status-badge`, `hx-trigger="every 10s"`) is directly relevant as a reference
implementation if the implementer chooses to add a live-poll for ingest status.

Memory records confirm:
- `SecFetchSiteMiddleware` blocks cross-`/ui/` XHR (memory: notebook-ops-hardening-m4)
  — not relevant here since all endpoints are under `/ui/`.
- `server/health.py` line numbers shift — not relevant to this milestone.

No adjacent milestone state conflicts identified in git log. The
`corpus-integrity-observability-e3` milestone touched `server/health.py` and
`server/metrics.py`, not `server/routes/ui.py` or the notebook detail template.
Collision risk: LOW.

---

## External sources

**MCP spec:** Not relevant — this milestone touches no MCP tool surface.

**Anthropic prompt-caching docs:** Not relevant — `/ui/` HTML handlers are not
tool definitions and do not affect BP1.

**Threat model (`08-security-observability-ops.md`):** Load-bearing quote:
"This is a single-developer, localhost-only system. The threat model is **not**
'external attacker' — it's 'LLM-generated tool inputs and adversarial arXiv content
can do unintended things to my workstation.'" For the UI detail page the realistic
threat is adversarial `display_name` content or future editable fields rendered
unescaped — not a remote attacker. The autoescape guarantee covers this for the
current milestone.

---

## Recommendation

**Implement as a per-notebook freshness line + a per-notebook status badge in the
header section, NOT a per-paper status column.**

Reasoning: `parse_status` is on `notebooks`, not `notebook_papers`. The "per-paper
status" framing in the brief is schema drift. The sensible implementation reads the
already-fetched `notebook["parse_status"]` (from `store.get_notebook(slug)`, line
217) and renders it once in the notebook header section, plus one call to
`store.get_latest_ingest_run(slug)` for the freshness line. No schema change, no
new query per paper. The acceptance criteria say "each paper row shows its parse
status" — for arxiv-kind notebooks every paper has `parse_status='skipped'`
(notebook-level); for textbook-kind there is one parse result for the whole notebook.
If the implementer wants a per-paper column, the only correct source would be
a new per-paper parse-tracking table — which the brief explicitly prohibits
("NO notebooks.db schema change"). So: render `parse_status` once at notebook scope.

**Security:** The status column/line is XSS-safe. `parse_status` is a server-written
enum. `display_name` is operator text but is already autoescaped. No `| safe` filter
should be introduced. The autoescape environment at `server/routes/ui.py:85–92` is
the single protection point — do not add `| safe` anywhere in the template.

**Render-vs-poll:** Server-side render for m1 (simplest, meets the AC). The freshness
signal and notebook parse_status are stable between page loads for the common case.
The m4 htmx poll pattern (`hx-trigger="every Ns"`) could be added as a m1 stretch
or follow-up for the running/pending states. Do NOT add a live poll in m1 unless
the AC explicitly requires it.

---

## Failure-mode analysis

### FM-a: Notebook with zero papers
- **Trigger:** `store.list_papers(slug)` returns `[]`.
- **Current template behavior:** line 106 in `notebook_detail.html` has
  `{% if not papers %}<p class="empty">No papers yet.</p>{% endif %}` already.
  The `<tbody>` loop renders nothing. The freshness line and status badge are in
  the header section (notebook-scoped), not the papers loop — they render
  regardless of paper count.
- **Mitigation:** existing guard is sufficient; the new status line must be
  placed outside the `{% for p in papers %}` loop.

### FM-b: `get_latest_ingest_run` returns None (never ingested)
- **Trigger:** `notebook_ingest_runs` has no row for this slug.
- **Symptom without mitigation:** `None` passed to template causes a
  `{{ latest_run.finished_at }}` → `None` display or AttributeError.
- **Mitigation:** pass `latest_run` as `None` to the template and use
  `{% if latest_run and latest_run.finished_at %}...{% else %}never indexed{% endif %}`
  in the template. The `None` check must be in the template, not assumed
  to be non-None.

### FM-c: Paper row with NULL/missing parse_status (legacy)
- **Trigger:** Pre-v4 schema row where the column has NULL (possible if
  backfill didn't fire due to a schema-version race).
- **Symptom:** `None` rendered as "None" or template crash on comparison.
- **Mitigation:** In the handler, coerce `notebook["parse_status"] or "unknown"`
  before passing to the template. In the template, display "-" for unknown.
  This is defensive; the DEFAULT `'skipped'` migration at line 241 should
  prevent this in practice for all rows created after v4.

### FM-d: parse_status value outside known enum (forward-compat)
- **Trigger:** A future migration introduces a new state value before the
  template is updated.
- **Symptom:** An `if/elif` chain that falls through to nothing, or a
  missing CSS class.
- **Mitigation:** Use a dict lookup with a fallback in the handler:
  `STATUS_LABEL = {"skipped": "skipped", "pending": "pending", ...}` and
  pass `STATUS_LABEL.get(status, status)` — render literally (autoescaped),
  not crash. Never use a bare `match` without a wildcard arm.

### FM-e: Per-paper query N+1 regression
- **Trigger:** Implementer fetches parse_status per paper via a per-row
  `store.get_notebook(paper_id)` call inside the annotation loop.
- **Symptom:** O(N) SQL queries on page render (currently O(1) for status,
  O(N) for preview stats are already accepted).
- **Mitigation:** `notebook["parse_status"]` is already available from the
  single `store.get_notebook(slug)` call at line 217. Do NOT add a per-paper
  query. Similarly, `store.get_latest_ingest_run(slug)` is one O(1) call
  added to the handler, not one per paper.

### FM-f: Autoescape regression via `| safe` in future template edit
- **Trigger:** A future implementer adds `{{ notebook.display_name | safe }}`
  to make rich HTML display_names work (m2 edit-display-name feature).
- **Symptom:** Stored XSS — an operator-controlled display_name containing
  `<script>` is rendered unescaped.
- **Mitigation:** The explicit `autoescape=select_autoescape(...)` construction
  in `server/routes/ui.py:85–92` is the guard — it protects even if a developer
  forgets. However, `| safe` bypasses it. Document this in a template comment
  near `display_name` now, so m2 cannot silently introduce it.
  Per `08-security-observability-ops.md`: the threat model includes adversarial
  content via operator-controlled fields.

---

## Open questions

**OQ-1 (BLOCKING): per-paper vs per-notebook parse_status.**

The brief says "per-paper parse/ingest STATUS column ... reusing parse_status on
notebook_papers rows." `notebook_papers` has NO `parse_status` column. The implementer
must choose one of:

(a) **Recommended:** render `parse_status` once at the notebook-header scope
    (already in `notebook` dict from `store.get_notebook`), not as a per-paper
    column. Re-label the UI as "Notebook parse status:" rather than a column header.
    This meets the spirit of the AC ("shows parse status") without a schema change.

(b) Add a per-paper parse-status column to `notebook_papers` — but this IS a schema
    change, explicitly prohibited by the brief ("NO notebooks.db schema change").

(c) Join `notebook_papers` against `notebook_ingest_runs` to infer per-paper status
    from ingest run outcomes — but no per-paper tracking exists in ingest runs either.

The implementer must confirm interpretation (a) with the milestone author before
writing the template column header. If (a) is accepted, the AC wording "each paper
row shows its parse status" must be re-read as "the page shows the notebook's parse
status near the paper list," not one cell per row.

---

## External writes the implementation will require

None — this milestone is purely local.

- No git push
- No GitHub issue or PR
- No infra mutation
- No tool-schema re-pinning (no MCP tool surface touched)
