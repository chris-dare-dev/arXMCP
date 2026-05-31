# Implementation summary — notebook-paper-discovery-m4

**One-line:** Added the loopback `POST /ui/api/notebooks/{slug}/discover` route + a
notebook-detail-page htmx "Discover" panel that runs the m3 driver and lists candidates
with per-row "Add" buttons (reusing the existing add-paper route) — the propose→confirm
operator surface for topic-driven discovery.

**Commit range:** `<BASE>..<HEAD>` (filled at commit; implementation_base in state.json).
**Implementation path:** INLINE — 5 files (route+fragment, template, form-count test, new route tests, design note).

---

## Acceptance criteria status

- [x] **Operator clicks "Discover" → panel shows deduplicated candidates with title + abstract, server-rendered.** `discover_papers` (async) calls `discover_for_notebook_async(store, slug, contact_email=…)` and renders `_discover_results_fragment` (an html.escape'd f-string, swapped into `#discover-results`). Regression: `tests/test_discover_route.py::TestDiscoverHappyPath::test_renders_candidates` (+ `test_dedups_existing_paper`, `test_empty_result_renders_friendly_state`). (The AC's "≥10" is a corpus-size detail; the test asserts candidates render + dedup with a mocked feed.)
- [x] **Operator clicks "Add" → paper recorded in `notebook_papers` (and embeddable via Ingest).** Each candidate row is a mini-form posting to the EXISTING `POST /ui/api/notebooks/{slug}/papers` with `arxiv_url=https://arxiv.org/abs/{paper_id}`, `hx-target="#papers-tbody"`, `hx-swap="beforeend"` — reuses the validated add-paper handler (records the junction; returns the `<tr>`). LanceDB embedding is the existing separate "Ingest now" step (see Deviation). Regression: `test_renders_candidates` asserts the mini-form target + URL.
- [x] **No new MCP tool; `EXPECTED_TOOL_SCHEMA_SHA256` + BP1 byte-unchanged.** The diff touches only `server/routes/notebooks.py` (a UI route, not `server/tools.py::ALL_TOOLS`), templates, tests, and a note. The schema-hash test stays green.
- [x] **Loopback-only, server-rendered Jinja2+htmx, no Node/SPA; ephemeral-queue behavior documented in the panel AND the discovery-model note.** The panel + fragment are server-rendered; the route inherits `SecFetchSite` + `OriginValidation` on `/ui/*`; the panel says "results are not saved; click Discover to re-run"; `.claude/notes/notebook-discovery-model.md §3a` documents the ephemeral queue + Add-reuses-add-paper.
- [x] **`make test` green.** ruff clean; full-suite diff vs baseline = zero real regressions (pre-existing Windows-platform failures + the known flaky rate-limit test only).

## Security (security-reviewer specialist concern)
- **XSS (primary risk, FM-A):** candidate `title`/`abstract_head`/`paper_id` come from the arXiv API (untrusted) and are `html.escape`'d in the f-string fragment — never `| safe`. Regression: `TestDiscoverSecurity::test_escapes_hostile_title` (a title that decodes to `<script>alert(1)</script>` renders as `&lt;script&gt;…`, confirming the parse→re-escape round-trip).
- **Clean error handling (FM-B/FM-C):** unconfigured notebook (`ValueError`) → 422; arXiv unreachable/error (`RuntimeError`/`OSError`) → 502; bad slug → 422 (`validate_slug` first); unknown slug → 404. Never a 500. Regressions: `TestDiscoverErrors` (4 tests). `_safe_contact_email` degrades to `None` on any settings-store failure (never breaks the request).
- **Egress/blocking:** the route reaches arXiv only via the m2/m3 driver (export.arxiv.org, TLS, `MAX_RESPONSE_BYTES` cap). The synchronous fetch briefly blocks the event loop — accepted + documented for the single-operator loopback console.

## Files changed
| File | Change |
|---|---|
| `server/routes/notebooks.py` | `_safe_contact_email`, `_discover_results_fragment`, `POST .../discover` route; imports `discover_for_notebook_async` + `get_contact_email` |
| `frontend/templates/notebook_detail.html` | Discover card (button → `#discover-results`, error `<pre>`, ephemeral label) |
| `tests/test_discover_route.py` | NEW — 8 tests (render/dedup/empty/XSS/422/404/bad-slug/502) |
| `tests/test_ui_m3_dark_and_htmx_feedback.py` | form-count 6 → 7 (the new Discover form; uses `find button`) |
| `.claude/notes/notebook-discovery-model.md` | §3a documents the shipped panel + Add-wiring + ephemeral queue |

## New / changed tests
`tests/test_discover_route.py` (8). Form-count assertion updated (6→7). Existing suite unchanged otherwise.

## Deviations from the brief
- **"Add → ingested into LanceDB":** the existing console NEVER auto-ingests on add (URL-paste only records the junction; embedding is the separate "Ingest now" subprocess). m4's "Add" reuses that add-paper route (records `notebook_papers`); LanceDB embedding remains the operator's existing "Ingest now" action. This is the established two-step propose→confirm pattern; auto-ingest-on-Add would be a heavier divergence and is out of v1 scope. Documented in `notebook-discovery-model.md §3a`.

## External writes required
**None.** New route + fragment + template + tests + a note line. The arXiv call is the m2/m3-owned egress. `state.external_writes_required = []`.
