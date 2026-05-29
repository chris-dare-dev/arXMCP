# Research Brief — notebook-surface-expansion-m3

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-29T00:00:00Z

---

## In-codebase context

### Exhaustive stale-claim hunt — literal vs. omission

**BRIEF-VS-REALITY CONFLICT (flag):**
The milestone brief states "DROP the stale 'no frontend exists, by design' claim" from
`06-mcp-server-design.md` + `CLAUDE.md`. The orchestrator's pre-flight grep found NO such
literal phrase in either file. This researcher confirms that finding. The actual landscape:

**Literally-false claims (must edit — deletion + replacement):**

1. `.claude/notes/02-architecture-overview.md:150` — verbatim:
   `- Beautiful UI. The MCP tool surface is the UI.`
   This is in a "Non-goals for v1" list. A browser UI now ships. The claim is FALSE.

2. `.claude/notes/09-feature-priorities.md:151` — verbatim:
   `- **A web UI.** The MCP tool surface is the UI.`
   Same pattern, in "Things to explicitly NOT build in v1". Also FALSE.
   However, CLAUDE.md §11 marks `09-feature-priorities.md` as **SUPERSEDED** by
   `.claude/roadmap/README.md`. Recommendation: edit it anyway (see §Recommendation),
   but the supersession note means the adversary cannot legitimately cite it as the
   primary stale claim.

**Pure omissions (must add description, not delete a false claim):**

3. `CLAUDE.md` — §2 "What this project is" and §6 "Capabilities you can rely on" mention
   only the 7-tool MCP surface. The shipped browser UI (`/ui/` pages, `/ui/api/*` REST,
   the `/ui/status-badge`) is completely absent. These are omissions, not false statements.

4. `.claude/notes/06-mcp-server-design.md` — covers the 7-tool MCP surface + transport,
   spec compliance, concurrency, health/readiness. The `server/routes/ui.py` and
   `server/routes/notebooks.py` surfaces (HTML pages, htmx, REST API) are entirely absent.
   This is an omission.

5. `CLAUDE.md` §5 directory layout — `server/` subtree lists only MCP-related files.
   `server/routes/` (ui.py, notebooks.py) and `frontend/` (templates, static) are absent.

**`09-feature-priorities.md:151` — edit or leave?**
Recommendation: edit it. The supersession note in CLAUDE.md §11 says the file is superseded
by the roadmap index, not that it is wrong; the false claim will confuse any agent that reads
it. Update the bullet to read "A dedicated SPA / authenticated web UI" or similar to reflect
the loopback-only Jinja2+htmx surface actually shipped. Cost: one line edit; risk: none.

---

### `06-mcp-server-design.md` — right place and right content

The file covers: Transport, Spec compliance, Tool surface, Resource surface, Determinism
contract, Concurrency, Health/readiness, Configuration (including notebook-scoped retrieval
fork C and per-call fork A), Server lifecycle, "What this server does NOT do".

The correct insertion point is a **new section just before "What this server does NOT do"**,
titled `## Browser UI surface`. It must cover:

**HTML pages (`server/routes/ui.py`):**
- `GET /ui/` — landing page: notebook list + create-notebook form
- `GET /ui/notebooks/{slug}` — per-notebook detail: paper list, URL-paste form, drag-drop upload
- `GET /ui/notebooks/{slug}/papers/{paper_id}/preview` — ar5iv preview (per-paper HTML)
- `GET /ui/status-badge` — live htmx fragment for footer badge (notebook-ops-hardening-m4)

**REST / htmx API (`server/routes/notebooks.py`, mounted at `/ui/api`):**
- `GET /ui/api/notebooks` — list notebooks
- `POST /ui/api/notebooks` — create notebook
- `DELETE /ui/api/notebooks/{slug}` — delete notebook
- `PATCH /ui/api/notebooks/{slug}` — rename notebook (m2)
- `GET /ui/api/notebooks/{slug}/papers` — list papers
- `POST /ui/api/notebooks/{slug}/papers` — add paper by URL/ID
- `DELETE /ui/api/notebooks/{slug}/papers/{paper_id}` — remove paper
- `POST /ui/api/notebooks/{slug}/papers/upload` — upload PDF (returns HTML fragment)
- `POST /ui/api/notebooks/{slug}/ingest` — trigger ingest
- `GET /ui/api/notebooks/{slug}/ingest` — poll ingest status
- `GET /ui/api/notebooks/{slug}/parse-status` — per-notebook parse status

**Security posture to document:**
- Jinja2 autoescape: `jinja2.Environment` constructed explicitly with
  `autoescape=select_autoescape(enabled_extensions=("html","htm","xml"), default_for_string=True)`.
  No `| safe` filters exist in templates.
- CSP: `CONTENT_SECURITY_POLICY_UI` (from `server/middleware.py:170-177`) applied to all
  `/ui/*` paths. Tighter `CONTENT_SECURITY_POLICY_PREVIEW` (lines 218-226) for the preview
  route. `frame-ancestors 'none'` in both. `unsafe-inline` trade-off documented.
- `SecFetchSiteMiddleware` carves out `/ui` as an `exempt_prefix` (allows `same-origin`
  XHR from `/ui/*` pages to `/ui/*` endpoints). Non-`/ui` origins still blocked.
- Origin + Host validation: `OriginValidationMiddleware` + `HostValidationMiddleware`
  (loopback-only: `{"127.0.0.1", "localhost", "::1"}`).
- **No SPA / no Node.js build chain** — server-rendered Jinja2+htmx; vendored htmx.min.js
  from `frontend/static/`; templates in `frontend/templates/`. Hard constraint: do NOT add
  a Node/npm/build-chain dependency.

---

### CLAUDE.md edit scope

Minimal, correct changes (do NOT bloat CLAUDE.md):

**§2 "What this project is"** — add one sentence after "every sub-agent shares one substrate
of grounded context through this server." Insert: "A loopback-only Jinja2+htmx browser UI at
`/ui/` enables notebook management (create/list/ingest/rename/delete/upload) without a build chain."

**§5 directory layout** — under `server/` subtree, add:
```
│   ├── routes/              browser UI + REST routes (notebooks, ui pages)
│   │   ├── ui.py            Jinja2 HTML pages: /ui/, /ui/notebooks/{slug}, /ui/status-badge
│   │   └── notebooks.py     /ui/api/ REST + htmx upload (create/list/ingest/rename/delete)
```
And add `frontend/` to the top-level tree:
```
├── frontend/
│   ├── templates/           Jinja2 HTML templates (base.html, index.html, notebook_detail.html)
│   └── static/              vendored htmx.min.js + minimal CSS
```

**§6 "Capabilities you can rely on"** — add one bullet:
`- **Browser UI** at `http://127.0.0.1:7733/ui/` — notebook management (list/create/ingest/rename/delete/upload); loopback-only; Jinja2+htmx, no SPA build chain.`

These changes are agent-internal context, so CLAUDE.md is the correct home per doc-placement
rules (§1, §4.6).

---

## Prior decisions and lessons

**Recent git log (last 15):**
- `eb8088d chore(notes): finalize notebook-surface-expansion-m2 state -> complete`
- `9b2ba61 rect(server): close 1M+1L from notebook-surface-expansion-m2 critique`
- `d073c0a feat(server): in-page notebook rename + delete (notebook-surface-expansion-m2)`
- `096be65 chore(notes): finalize notebook-surface-expansion-m1 state -> complete`
- `934ecba feat(server): notebook detail parse-status + freshness (notebook-surface-expansion-m1)`

**How E13 follow-up issues were filed:**
From `.claude/docs/security-threat-model-coverage.md` §Brief deviations:
> `gh issue create` is a Phase-4 external write per the milestone-pipeline command; the
> implementer compiles the gap list during Phase 2 (this document) and surfaces it to the
> user at the Phase-4 boundary. Each gap row below is either a literal `(none)`, a
> `(TODO file issue)` placeholder, or a `[#NNN — title](URL)` link.

Issues #1–#6 were created via `gh issue create` at `github.com/chris-dare-dev/arXMCP` (not
GitLab). The pattern: implementer writes a `(TODO file issue)` placeholder; Phase 4 fires
`gh issue create --repo chris-dare-dev/arXMCP --title "..." --body "..."`.

**No issue-body template exists in repo.** Prior bodies are written ad-hoc. Recommend the
implementer document the issue body in the implementation summary for Phase 4 authorization.

**CAND-13/14 in `plans/`:**
`plans/corpus-integrity-observability-roadmap.md:108` uses CAND-13 for BGE-M3 upgrade
and CAND-14 for eval fixture completion. `plans/notebook-surface-expansion-roadmap.md:140`
uses CAND-13/CAND-14 to mean "UI-security-audit tracking issue + constitution refresh"
— a different meaning than corpus-integrity. CAND labels are reused across plan files;
do NOT conflate them. The brief here uses CAND-13/CAND-14 to mean: "E13 scoped the
`server/routes/ui.py` + `server/routes/notebooks.py` + templates security audit out."

**No MCP tool surface change:** this milestone touches only docs + a test + a filed issue.
Confirmed: `server/tools.py`, `EXPECTED_TOOL_SCHEMA_SHA256`, `server/prompts.py`, and
`EXPECTED_BP1_SHA256` do NOT need re-pinning.

---

## External sources

**MCP spec:** not relevant — milestone does not modify MCP tool surface or server transport.

**Anthropic prompt-caching docs:** not relevant — no tool-schema change.

**In-codebase primary sources** are sufficient and more reliable:
- `server/middleware.py` lines 141–231 — authoritative CSP constants + SecFetchSite logic
- `server/routes/ui.py` — authoritative UI route enumeration
- `server/routes/notebooks.py` — authoritative REST/htmx API enumeration
- `frontend/templates/` — Jinja2 template inventory (verified: base.html, index.html, etc.)

---

## Recommendation

**Implement as a pure docs + test + filed-issue milestone in exactly 4 file changes + 1 external write:**

1. **Edit `02-architecture-overview.md:150`** — change
   `- Beautiful UI. The MCP tool surface is the UI.`
   to
   `- A dedicated SPA / authenticated web UI. A loopback-only Jinja2+htmx operator console at /ui/ ships as part of the server (notebook management only); it is not a general-purpose research UI.`

2. **Edit `09-feature-priorities.md:151`** — same substitution pattern.

3. **Edit `06-mcp-server-design.md`** — insert a new `## Browser UI surface` section
   immediately before `## What this server does NOT do`, enumerating all routes/posture
   exactly as described in the In-codebase context section above.

4. **Edit `CLAUDE.md`** — §2 add one sentence; §5 add `frontend/` + `routes/` to layout;
   §6 add one bullet. Minimal; no bloat.

5. **Add `tests/test_constitution_ui_claims.py`** — one test class, two methods:
   - `test_stale_claim_absent`: asserts `"MCP tool surface is the UI"` does NOT appear in
     `02-architecture-overview.md` or `09-feature-priorities.md` (the two files that had
     the false claim; do NOT assert against 06 or CLAUDE.md which never had it).
   - `test_ui_surface_described_in_06`: asserts `06-mcp-server-design.md` contains both
     `/ui/` and `htmx` (confirms the addition landed).
   Precedent: `tests/test_tier_gates_doc.py` (reads `.claude/` markdown files from
   `REPO_ROOT = Path(__file__).resolve().parent.parent`; makes plain string-in-text
   assertions; no fixtures required).

6. **Phase 4 external write:** `gh issue create --repo chris-dare-dev/arXMCP` with title
   "UI security audit: server/routes/ui.py + server/routes/notebooks.py + templates
   (E13 deferred scope)" and body scoping audit to: Jinja2 autoescape coverage, `unsafe-inline`
   CSP tightening, CSRF risk on state-mutation POST endpoints (no token today), file-upload
   polyglot/zip-bomb paths not covered by the MCP-tool threat model audit.

---

## Open questions

No open questions — implementation can proceed on the above recommendation.

---

## External writes the implementation will require

| type | target | why |
|---|---|---|
| `gh issue create` | `chris-dare-dev/arXMCP` | File UI-security-audit tracking issue (E13 deferred scope; CAND-13/CAND-14); Phase-4, per-event authorized |
