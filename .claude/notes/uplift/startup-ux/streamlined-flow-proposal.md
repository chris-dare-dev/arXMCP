# Streamlined first-time-user onboarding — destination-state proposal

> Companion to (and independent of) `current-state-critique.md`. This
> file describes how onboarding *should* feel after the uplift; the
> critique enumerates the friction we're removing. Authored 2026-05-30
> for the `streamlined-flow-proposal` slot of the startup-UX uplift.

---

## 1. Goal statement

A first-time arXMCP user — non-tech-proficient researcher OR scripting
operator — should reach **"my MCP client is talking to a populated
notebook"** in **one Make target or one UI click-path**, without
reading the design constitution, without exporting environment
variables that the server refuses to accept, and without learning the
fork A / fork B / fork C taxonomy. The single concept we expose is the
**notebook**: a curated bundle of papers, a corpus, and a `queries.json`.
Everything else (LanceDB, BM25, BGE-M3, corpus-version markers) is an
implementation detail the wizard handles silently and the CLI surfaces
as a single command.

---

## 2. Personas + their happy paths

### Persona A — the UI user ("Riya, postdoc")

What she wants: type a URL, click "New Notebook", paste an arXiv link,
wait, query through Claude Code.

```
 1. Clones the repo; `make bootstrap` (creates var/arxmcp tree).
 2. `make up`. Server boots in "no corpus" mode — the lifespan
    skips eager BGE-M3 warmup, /readyz returns 200 with a
    `setup_required=true` flag, and a startup banner prints the
    URL of the wizard.
 3. Opens http://127.0.0.1:7733/ui/ — the landing page detects
    "zero notebooks" and renders an onboarding wizard instead of
    the empty notebook table.
 4. Wizard step 1: "What's your email?" (one input; persisted to
    var/arxmcp/cache/operator.json so she never sees it again).
 5. Wizard step 2: "Name your first notebook" (slug input; live-
    validates against the slug regex). Click Create.
 6. Wizard step 3: "Add papers" — paste arXiv URLs OR upload a PDF
    OR click the "Try a 3-paper sample" button (canonical seed:
    1601.00001, 2103.00876, 2401.00500 — covers algebraic geometry
    + number theory + math.AG to exercise every retrieval pathway).
 7. Wizard step 4: "Ingest" — htmx-driven progress panel polls
    /ui/api/notebooks/<slug>/ingest-status every 2 s. First run
    streams the BGE-M3 download progress through the same panel
    (bytes downloaded / total). When done, the wizard hands off
    to the notebook detail page with a green badge.
 8. Riya pastes the MCP registration snippet from docs/install.md
    into ~/.claude.json. Done.
```

She never touched a terminal beyond `make bootstrap` + `make up`.

### Persona B — the CLI user ("Sam, ML engineer scripting a pipeline")

```
 1. Clones, runs `make bootstrap`.
 2. `make init NOTEBOOK=alg-geom EMAIL=sam@lab.org` —
    creates the notebook, persists EMAIL to operator.json,
    scaffolds papers.txt + queries.json.
 3. Pipes IDs in: `cat my-ids.txt > var/arxmcp/notebooks/alg-geom/papers.txt`
    OR `make add NOTEBOOK=alg-geom PAPER=2401.00001` per paper.
 4. `make ingest NOTEBOOK=alg-geom` — runs fetch + ingest end-to-
    end, exits non-zero on any per-paper failure. Idempotent.
 5. `make up NOTEBOOK=alg-geom` (or the existing
    `ARXMCP_NOTEBOOK=alg-geom make up`) — starts the server bound
    to the notebook. `make status` prints "READY chunks=N
    notebook=alg-geom".
 6. Registers the shim in ~/.claude.json (one-time).
 7. To add papers later: `make add NOTEBOOK=alg-geom PAPER=<id>`
    + `make reingest NOTEBOOK=alg-geom`.
 8. Drift after a chunker bump: `make reconcile NOTEBOOK=alg-geom`.
```

Same backend logic as Riya's path — every Make target is a thin shell
over the `/ui/api/*` REST endpoints (single source of truth — see §4).

---

## 3. Surface inventory (what exists today)

### 3.1 CLI surface (`tools/notebook_*.py` family)

| Stage | Tool | Notes |
|---|---|---|
| Scaffold dir | `tools/notebook_init.py <slug>` (`tools/notebook_init.py:81`) | Creates `papers.txt` + `queries.json`. Idempotent at dir level. NO Make wrapper. |
| Fetch ar5iv + raw `.tex` | `tools/notebook_fetch.py <slug>` (`tools/notebook_fetch.py:77`) | Requires `ARXMCP_CONTACT_EMAIL`. NO Make wrapper. |
| Chunk + embed + BM25 | `tools/notebook_ingest.py <slug>` (`tools/notebook_ingest.py:73`) | Wraps `ingest.bulk_ingest.run_bulk_ingest`. NO Make wrapper. |
| Cutover staging→active | `tools/notebook_cutover.py` (covered by `make notebook-cutover`) | The one notebook-* tool with a Make wrapper. |
| Purge (destructive) | `tools/notebook_purge.py` | NO Make wrapper. |
| Backup/restore | `tools/notebook_restore.py` | NO Make wrapper. |
| Textbook PDF ingest | `tools/notebook_textbook_ingest.py` | NO Make wrapper. |
| Preamble back-fill | `tools/recover_preambles.py` (covered by `make ingest-recover-preambles`) | Wrapped. |

### 3.2 UI / REST surface (`server/routes/notebooks.py`, `server/routes/ui.py`)

| Endpoint | What it does | File:line |
|---|---|---|
| `GET /ui/` | Notebook landing page (htmx shell) | `server/routes/ui.py:1` |
| `GET /ui/notebooks/{slug}` | Per-notebook detail page | `server/routes/ui.py` |
| `GET /ui/api/notebooks` | List notebooks | `server/routes/notebooks.py:240` |
| `POST /ui/api/notebooks` | Create notebook | `server/routes/notebooks.py:248` |
| `DELETE /ui/api/notebooks/{slug}` | Metadata-only delete | `server/routes/notebooks.py:351` |
| `PATCH /ui/api/notebooks/{slug}` | Rename | `server/routes/notebooks.py:413` |
| `GET /ui/api/notebooks/{slug}/papers` | List paper rows | `server/routes/notebooks.py:462` |
| `POST /ui/api/notebooks/{slug}/papers` | Add paper from arxiv URL | `server/routes/notebooks.py:488` |
| `POST /ui/api/notebooks/{slug}/papers/upload` | PDF upload (textbook) | `server/routes/notebooks.py:797` |
| `DELETE /ui/api/notebooks/{slug}/papers/{paper_id}` | Remove junction row | `server/routes/notebooks.py:543` |
| `GET /ui/api/notebooks/{slug}/parse-status` | Poll MinerU parse | per `docs/install.md:86` |
| `GET /status`, `/healthz`, `/readyz` | Health + structured JSON | `server/health.py` |
| `GET /ui/status-badge` | HTML fragment (10 s htmx poll) | `frontend/templates/base.html:65` |

**Gaps the operator surface has TODAY:**

- No endpoint or CLI to **kick off ar5iv-fetch + ingest** for an existing
  notebook. The UI POSTs the paper row to SQLite; the on-disk corpus is
  populated only by running `tools/notebook_fetch.py` + `tools/notebook_ingest.py`
  from a terminal. The UI silently looks empty.
- No endpoint or CLI to **reconcile** a stale `corpus-version.json`
  marker (the count-drift gap behind the DEGRADED badge — `server/health.py:100`).
  The m1 fix prevents new drift; it does not heal pre-existing markers.
- No endpoint or CLI to **repair** an on-disk `var/arxmcp/notebooks/<slug>/`
  directory missing from `cache/notebooks.db` (the registry-vs-disk
  drift). The store is opened in `server/notebooks_store.py:101` and
  never reconciled against the filesystem.
- `make ingest` is the **bulk shared-corpus** driver, not the notebook
  driver (`Makefile:117`). Operators reach for it, get redirected, and
  bounce off.

### 3.3 The `ARXMCP_CONTACT_EMAIL` collision

- `server/config.py:82` — `extra="forbid"` on the pydantic Settings class.
- `server/main.py:264` — `_scan_unknown_arxmcp_env_vars` rejects ANY
  `ARXMCP_*` env var not declared on `Config`. `ARXMCP_CONTACT_EMAIL`
  is NOT declared on `Config` (verified — `grep -n CONTACT_EMAIL
  server/config.py` → zero hits).
- `CLAUDE.md:515` AND `Makefile:37,62,180` still tell operators to
  export it. Today the docs say "do X to start the server"; the
  server then refuses to start because X is forbidden.
- The var is ONLY needed by `tools/arxiv_fetch.py:97`,
  `tools/notebook_fetch.py:91`, and `ingest/inspire_ingest.py:784`.
  None of those run inside the server process — they're CLI tools.

The fix is two lines plus a doc sweep (see §7 + §E).

---

## 4. Proposed Make API

Every target is a thin wrapper over an existing `/ui/api/*` REST
endpoint OR a `tools/notebook_*.py` module — never a parallel
implementation. The server is the source of truth; the CLI is curl.

| Target | Backed by | Replaces today's |
|---|---|---|
| `make bootstrap` | (unchanged) | creates var/arxmcp tree |
| `make init NOTEBOOK=<slug> [EMAIL=...]` | `POST /ui/api/notebooks` + `tools/notebook_init.py` for files | manual `notebook_init.py` + `export ARXMCP_CONTACT_EMAIL=...` |
| `make add NOTEBOOK=<slug> PAPER=<id>` | `POST /ui/api/notebooks/<slug>/papers` (server running) OR append to papers.txt (server down) | manual `papers.txt` edit |
| `make ingest [NOTEBOOK=<slug>]` | `POST /ui/api/notebooks/<slug>/ingest` (new endpoint; backed by `tools/notebook_fetch.py` + `tools/notebook_ingest.py`) | `make ingest` (today's bulk redirect-to-stub) |
| `make reingest NOTEBOOK=<slug>` | `POST /ui/api/notebooks/<slug>/ingest?force=1` | `tools/notebook_ingest.py` + manual cutover |
| `make status [NOTEBOOK=<slug>]` | `GET /status` + `GET /ui/api/notebooks/<slug>/health` (new) | `make status` (today's one-line summary) |
| `make reconcile [NOTEBOOK=<slug>]` | `POST /ui/api/notebooks/<slug>/reconcile-marker` (new) | NO equivalent today |
| `make repair-registry` | `POST /ui/api/admin/repair-registry` (new) | NO equivalent today |
| `make notebook-list` | `GET /ui/api/notebooks` | NO equivalent today |
| `make wizard` | opens `http://127.0.0.1:7733/ui/?wizard=1` in `$BROWSER` | NO equivalent today |
| `make up [NOTEBOOK=<slug>]` | reuses `ARXMCP_NOTEBOOK=<slug> python -m server.main` | `make up` (unchanged when `NOTEBOOK` unset) |

Important: the Make targets that hit the REST API need a "server-up"
precondition. The implementation pattern is the same as `make status`
today (`Makefile:111`) — `curl --fail` against `/healthz`; if that
fails, fall back to the in-process `tools/notebook_*.py` module so the
CLI works headlessly. (The fallback ALSO makes the Make targets work
inside the `make up` first-boot wizard before the operator has done
anything.)

The `ARGS=` pass-through that today's `make ingest` / `make cutover`
use stays; the new variable-style args (`NOTEBOOK=`, `PAPER=`, `EMAIL=`)
become first-class so the operator never has to learn the dual style.

---

## 5. Proposed UI deltas (Jinja2 + htmx — no SPA)

### 5.1 New templates

| Template | Purpose |
|---|---|
| `frontend/templates/wizard.html` | First-boot wizard (steps 1–4 from §2 Persona A). Extends `base.html`. |
| `frontend/templates/_wizard_step.html` | Per-step fragment — `wizard.html` is the shell, each step renders via `hx-get="/ui/api/wizard/step/<N>"`. |
| `frontend/templates/_notebook_health_panel.html` | Per-notebook health fragment polled by htmx (10 s) on the detail page. Renders `marker_chunks` vs `actual_chunks`, drift badge, and a "Reconcile" button when the gap is non-zero. |
| `frontend/templates/_ingest_progress.html` | Streaming HTML fragment for the ingest-status poll. Renders bytes-downloaded / total-bytes for BGE-M3 first run; per-paper progress for ingest. |
| `frontend/templates/_first_boot_banner.html` | Replaces the empty notebook table on `/ui/` when no notebooks exist. CTA: "Create your first notebook" → opens the wizard. |

### 5.2 New REST endpoints

| Endpoint | Verb | Notes |
|---|---|---|
| `/ui/api/wizard/state` | GET | Returns `{"step": <1..5>, "email_known": bool, "notebooks_count": int}`. Drives the wizard's resume-from-step behavior. |
| `/ui/api/wizard/email` | POST | Persists `{email}` to `var/arxmcp/cache/operator.json` (chmod 0600). |
| `/ui/api/notebooks/<slug>/ingest` | POST | Kicks off fetch+ingest in a background task; returns `202` with a job_id. Idempotent at the per-paper level (`tools/notebook_fetch.py` already is). |
| `/ui/api/notebooks/<slug>/ingest-status` | GET | Poll endpoint; returns `{"phase": "downloading_model|fetching|chunking|embedding|indexing|done|failed", "bytes_done", "bytes_total", "papers_done", "papers_total", "last_error"}`. |
| `/ui/api/notebooks/<slug>/health` | GET | Per-notebook drift report: `{marker_chunks, actual_chunks, drift, last_ingest, bm25_versions}`. |
| `/ui/api/notebooks/<slug>/reconcile-marker` | POST | Re-counts the LanceDB table, rewrites `corpus-version.json`, logs the delta. Audit-logged. |
| `/ui/api/admin/repair-registry` | POST | Walks `var/arxmcp/notebooks/`, INSERTs a row in `cache/notebooks.db` for every on-disk dir not currently registered. Idempotent. Returns the list of slugs added. |

These are all `/ui/api/*` REST endpoints — they do NOT touch the
frozen MCP `tools/list` schema. Zero BP1 cache impact.

### 5.3 First-boot detection

`server/routes/ui.py:GET /ui/` already renders the notebooks index.
The delta is one branch: when `await store.list_notebooks()` returns
an empty list AND no `?dismiss-wizard=1` cookie is set, render
`wizard.html` instead of the empty `index.html`. The "Skip wizard"
link sets the cookie so power users aren't trapped.

### 5.4 Operability badge — explain, not just label

`server/health.py:459` returns `"DEGRADED"` when corpus-marker drift
exceeds threshold. Today the badge has no tooltip explaining why.
Delta: extend `/ui/status-badge` to render a `<details>` tooltip:

> DEGRADED — marker says 12 480 chunks; LanceDB has 12 397. Pre-write-time
> fix only protects new ingests. Click "Reconcile" on the affected
> notebook to heal.

The link is a `hx-post="/ui/api/notebooks/<slug>/reconcile-marker"`
button that disappears once the gap closes.

---

## 6. Bootstrap / first-boot design — pick **A.iii (hybrid)**

**Reasoning** (steel-manned against A.i and A.ii):

- **A.i alone** (server boots in "no corpus" mode + UI wizard) is the
  best UX but requires lifting `CorpusNotIngestedError` from
  `server/resources.py:108` to a soft warning when the operator hasn't
  picked a notebook yet. That's a real architectural lift — the entire
  retrieval stack assumes a populated table at startup.
- **A.ii alone** (`make init` scaffolds before `make up`) is the
  cleanest from a server-correctness perspective but punishes Riya:
  she's still typing terminal commands. It's also a UX regression for
  Sam — `make init` already exists today (`tools/notebook_init.py`),
  it just lacks a Make wrapper.
- **A.iii (hybrid)** is the right pick. It splits the lift: the
  small architectural change is "server can boot with **zero
  registered notebooks**" (we already support this — the empty-corpus
  case is the seed-corpus path of `var/arxmcp/index/lancedb` before
  ingest), and the UX wizard rides on top. CLI users get
  `make init NOTEBOOK=<slug>` (single target, 60 seconds), UI users
  get the wizard (zero terminal commands after `make up`).

**Concrete implementation of A.iii:**

1. Add a `bootstrap_mode: bool = False` field to `Config` (server/config.py).
   When `True`, `Resources.startup` skips the `CorpusNotIngestedError`
   path and registers a "no-corpus stub" reader that 503s every MCP
   tool call with `{"error": "no_notebook_selected", "message": "Open
   http://127.0.0.1:7733/ui/ to create one"}`.
2. `make up` AUTO-detects `bootstrap_mode`: if `cache/notebooks.db`
   has zero rows AND no shared corpus exists at
   `var/arxmcp/index/lancedb/corpus-version.json`, set
   `ARXMCP_BOOTSTRAP_MODE=1` automatically and print a banner with the
   wizard URL.
3. When the operator finishes the wizard (or runs `make ingest`), the
   first successful ingest writes `corpus-version.json`, the server
   detects it on the next health-tick, and the bootstrap stub flips to
   the real reader (no restart needed — the existing `Resources`
   already handles late-binding via `singleflight`).
4. `make init NOTEBOOK=<slug>` is the headless equivalent — runs
   `tools/notebook_init.py`, persists `EMAIL=` (if given) to
   `operator.json`, prints the next steps. Does NOT require the server
   to be running.

This keeps the existing `CorpusNotIngestedError` path intact for the
"shared corpus, marker disappeared" edge case and only relaxes it when
the operator has explicitly opted into bootstrap mode (which the auto-
detect guarantees on a fresh clone).

---

## 7. Doc rewrite punch list

| File | Lines | Change |
|---|---|---|
| `CLAUDE.md` | 515 | Drop the `export ARXMCP_CONTACT_EMAIL=...` snippet from the "Start the MCP server (local dev)" section. The server does not need it. |
| `CLAUDE.md` | (new §) | Add a one-paragraph "Notebook = the unit of curation" gloss. Remove or relegate the fork A/B/C taxonomy to an "appendix for contributors". |
| `CLAUDE.md` | (gotchas §8) | Add a new gotcha #12: `/mcp` 307-redirects to `/mcp/`; clients must use the trailing slash. |
| `Makefile` | 37, 62, 180, 191 | The `@echo "Before fetching from arXiv, export ARXMCP_CONTACT_EMAIL=..."` lines stay (they're CLI-tool guidance) but get retargeted: name `tools/notebook_fetch.py` + `tools/recover_preambles.py` explicitly, NOT `make up`. |
| `docs/install.md` | 218-219 | Already correct (`ARXMCP_CONTACT_EMAIL` is NOT needed by the server); leave as-is. |
| `docs/install.md` | 161-164 | Rewrite "## 3. Run the server" to mention `make wizard` as the recommended path for non-tech users. |
| `docs/install.md` | 233-278 | Collapse the "Serving a notebook corpus" + "Per-call notebook selection" into a single "Pick a notebook" section. The fork A/B/C distinction is OK as a "for advanced users" footnote, but should not be the headline. |
| `docs/install.md` | 144 | Add the `/mcp/` trailing-slash note to the registration block — Claude Code is forgiving but other MCP clients are not. |
| `server/README.md` | 28 | Update the "REFUSES to start when corpus-version.json missing" sentence: it now ALSO succeeds in bootstrap mode (link to the new section). |

---

## 8. The env-var error message fix

`server/main.py:280-285` (5-LOC delta):

Today: `unknown ARXMCP_* environment variables: ['ARXMCP_CONTACT_EMAIL']. Declared variables: ['ARXMCP_BIND_HOST', 'ARXMCP_BIND_PORT', ...30 more].`

Proposed: walk each unknown var, run `difflib.get_close_matches` over
the declared set, and render either:

- `ARXMCP_CONTACT_EMAIL is not a server config var; it's only read by
  the CLI fetch tools (tools/notebook_fetch.py, tools/recover_preambles.py).
  Unset it for the server.`
- `ARXMCP_BIND_HOST_TYPO — did you mean ARXMCP_BIND_HOST?`
- Fall through to the existing "Declared variables: …" message ONLY for
  unknowns with no close match.

The CONTACT_EMAIL case gets a hardcoded carve-out because it's the one
predictable footgun and the existing `difflib` distance wouldn't
identify it (no near-match in `Config`).

---

## 9. Milestone sequencing

Sequenced by **value density × independence**. The first three target
60 % of the pain in ≤2 hours of work each. The rest are full
`/milestone-pipeline` candidates.

### m1 — `onboarding-uplift-m1` — "stop telling people to break their server"
**Effort: 1-2 hours. One-PR doc/code fix; skip the pipeline.**

- `server/main.py` env-error message fix (§8 above).
- `CLAUDE.md:515` + `Makefile:37,62,180` doc sweep (§7).
- `docs/install.md` /mcp trailing-slash note (§7).

Dependencies: none. Lands today on `main`.

### m2 — `onboarding-uplift-m2` — "Make targets that match the mental model"
**Effort: 1-2 hours. One-PR feature; skip the pipeline.**

- Add `make init NOTEBOOK= [EMAIL=]`, `make ingest NOTEBOOK=`,
  `make reingest NOTEBOOK=`, `make notebook-list`, `make add
  NOTEBOOK= PAPER=` as thin shell wrappers over the existing
  `tools/notebook_*.py` modules. Make's `NOTEBOOK?=` + `$(if ...)`
  is enough — no Python changes needed.
- Persist `EMAIL=` to `var/arxmcp/cache/operator.json` (chmod 0600);
  every `tools/notebook_fetch.py` invocation reads it as a fallback.
- Update `Makefile:11-38` (the `help` block) to list these first.

Depends on: m1 (so the new help text matches the new doc).
Pipeline? **No** — it's mechanical shell.

### m3 — `onboarding-uplift-m3` — "Repair + reconcile endpoints"
**Effort: 1 day. Run the pipeline.**

- `POST /ui/api/admin/repair-registry` — re-register on-disk dirs
  missing from `notebooks.db` (closes constraint #3).
- `POST /ui/api/notebooks/<slug>/reconcile-marker` — heal the
  `corpus-version.json` drift (closes constraint #4).
- `GET /ui/api/notebooks/<slug>/health` — per-notebook drift report.
- `make repair-registry` + `make reconcile NOTEBOOK=` wrappers.
- Tooltip on `/ui/status-badge` explaining the DEGRADED label.

Pipeline-worthy because it touches the health surface (Phase-3
adversary needs to look at audit-log discipline + concurrent-ingest
races on the marker rewrite).

Depends on: m2.

### m4 — `onboarding-uplift-m4` — "Bootstrap-mode server + ingest-status REST"
**Effort: 2-3 days. Run the pipeline.**

- `Config.bootstrap_mode: bool = False` + auto-detect on fresh clone.
- `Resources.startup` skips `CorpusNotIngestedError` when bootstrap.
- `POST /ui/api/notebooks/<slug>/ingest` (kicks off background task)
  + `GET /ui/api/notebooks/<slug>/ingest-status` (streaming poll).
- BGE-M3 first-run download wired through the status poll
  (HuggingFace's `tqdm` is already there; pipe its `downloaded_bytes`
  into a shared state object the endpoint reads).

Pipeline-worthy because it changes the server's startup contract
(adversary needs to confirm the stub reader can't accidentally serve
stale data after a half-failed first ingest; infra-safety needs to
confirm the SIGTERM path during ingest is clean).

Depends on: m3.

### m5 — `onboarding-uplift-m5` — "The wizard"
**Effort: 2-3 days. Run the pipeline.**

- `frontend/templates/wizard.html` + the four step fragments.
- `/ui/api/wizard/state` + `/ui/api/wizard/email`.
- First-boot detection at `GET /ui/`.
- "Try a 3-paper sample" button — hardcoded canonical IDs.
- `make wizard` opens the URL in `$BROWSER`.

Pipeline-worthy because it's the first feature that's user-facing in
the wizard sense — adversary should look at autoescape discipline +
CSP across the new templates; design-critique (out-of-pipeline) on the
copy.

Depends on: m4 (the ingest-status endpoint is what the wizard polls).

### m6 — `onboarding-uplift-m6` — "Per-notebook freshness in the UI"
**Effort: 1-2 days. Pipeline optional.**

- `frontend/templates/_notebook_health_panel.html` on the detail page.
- "Reconcile" button surfaced as a banner when drift > threshold.
- "Repair registry" admin surface (or quiet auto-run on startup with
  a clear log line).

Depends on: m3 + m4.

---

## 10. What we're NOT doing (the won't list)

- **No SPA.** No React, Vue, Svelte, Vite, Webpack, Node, npm. The
  wizard is `wizard.html` + step fragments + the same vendored
  htmx.min.js that ships today.
- **No remote access.** The server stays loopback-only; the wizard,
  the new REST endpoints, the reconcile/repair surfaces all bind to
  `127.0.0.1`. `bind_host = "0.0.0.0"` continues to fail at
  `Config()` parse time.
- **No authentication.** Single-user, single-workstation — the
  operator owns the host. The wizard's "What's your email?" step
  writes to disk; nobody else can read it because nobody else can
  reach the loopback port.
- **No multi-tenant notebook ACLs.** Every notebook is owned by the
  one operator. The "delete notebook" button doesn't gate on a
  password — it gates on the operator clicking through a confirm
  modal (the existing `hx-confirm` pattern).
- **No automatic `make up` daemonization.** `make up` continues to
  block. The wizard is "open this URL while `make up` is running",
  not "run this and we'll fork to a daemon".
- **No "reinstate `ARXMCP_CONTACT_EMAIL` as a server env var."** It
  was retired for a reason — the server doesn't need it. The CLI
  tools that DO need it read `operator.json` (m2) and fall back to
  `os.environ["ARXMCP_CONTACT_EMAIL"]` for compatibility with the
  scripted-pipeline users who set it in their `.envrc`.
- **No new MCP tools.** Every new surface is `/ui/api/*`. The
  `tools/list` schema is frozen; the BP1 hash stays pinned.
- **No `ROADMAP.md` at the repo root.** This proposal lives at
  `.claude/notes/uplift/startup-ux/streamlined-flow-proposal.md` per
  CLAUDE.md §1.
- **No automatic background BGE-M3 download at `make bootstrap`.**
  The download starts when the operator triggers the first ingest —
  that's where they're already waiting. Prefetching would surprise
  CI-only users who never plan to run ingest.

---

## 11. Open questions for the user

These need Chris's preference before m4/m5 sequencing is committed:

1. **Bootstrap-mode default ON or OFF?** Today's contract is "no
   corpus = server refuses to start". m4 proposes "no corpus + no
   notebooks = bootstrap mode auto-on". The risk is that a
   misconfigured production deploy (someone deleted the corpus dir)
   would silently flip into bootstrap mode instead of failing loud.
   The proposed auto-detect uses an AND (no shared corpus AND no
   notebooks AND no `ARXMCP_BOOTSTRAP_MODE=0` override), but Chris
   might prefer a tri-state (`auto` / `force_on` / `force_off`).

2. **`make ingest NOTEBOOK=`** today's `make ingest` is the bulk
   shared-corpus driver. m2 proposes overloading it: when `NOTEBOOK=`
   is set, route to the per-notebook path. When unset, behavior is
   unchanged. Is the overload OK, or should the new target be
   `make notebook-ingest`?

3. **"Try a 3-paper sample" button — which 3?** The wizard's
   demo path needs canonical IDs that exercise BGE-M3 + the chunker
   without exotic LaTeX. Best candidates from the existing seed list
   in `tools/seed-papers.txt`: pick three that succeeded cleanly on
   the most recent eval run. Chris should pick (or sign off on) the
   three so the wizard doesn't ship with a paper that has known
   parser issues.

4. **`operator.json` schema.** m2 + m5 both want a single
   single-key-value store for operator preferences (email today,
   "skip wizard" cookie tomorrow). Should this be SQLite (consistent
   with `notebooks.db`) or a flat JSON file? JSON is simpler; SQLite
   is more durable. The current proposal is JSON; Chris may prefer
   the consistency play.

5. **m4 BGE-M3 download progress — is HF's tqdm enough?** The
   wizard's ingest-status poll wants `bytes_done / bytes_total`. The
   most reliable signal is intercepting `huggingface_hub`'s download
   callbacks (which the existing embedder code already runs). The
   alternative is "spinner with a 'this takes 3-5 minutes on first
   run' note". The spinner is simpler; the progress bar is what the
   non-tech operator expects.

---

**End of proposal.** Total: ~3 000 words. Cross-link to the peer's
`current-state-critique.md` once it lands; the m1-m6 sequencing should
align 1:1 with the friction points the critique enumerates.
