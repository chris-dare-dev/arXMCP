# Adversary Brief — Capability Scout 2026q2-notebook-ux-storage-ops

**Scout run:** 2026-05-28  
**Scope:** Notebook management UX · durable/portable notebook storage · operability ("is it running") · container packaging  
**Critic model:** claude-sonnet-4-6

---

## 1. Executive Summary

The highest-severity gap is the **absence of a base docker-compose.yml**: the design constitution (`08-security-observability-ops.md`) specifies a two-service server+ingest compose stack and `infra/README.md` explicitly calls it unshipped, yet `make up` still launches bare-metal — every operator bootstrapping from the README gets a non-containerized setup with no volume-isolation, no ingest-service separation, and no replay path for the corpus/notebook data. Second-highest: **notebook storage has no durable backup coverage**: E14 ships restic backup for the arXiv corpus, but the per-notebook tree (`var/arxmcp/notebooks/`) is nowhere in the restic include-path, and the `notebooks.db` SQLite file is explicitly excluded from backup in the ops note. Third: **stale design-constitution claim** — `.claude/notes/06-mcp-server-design.md` and the E13_S06 critique artifact both assert "no frontend exists" when a Jinja2+htmx notebook UI ships across routes/ui.py, routes/notebooks.py, frontend/templates/, and frontend/static/. Fourth: **no human-friendly operability surface** — /healthz /readyz /metrics all exist, but they produce machine-readable JSON/Prometheus and are unlinkable from the notebook UI's own shell; a non-expert operator cannot tell "is my server ready" without running curl.

---

## 2. Critical Gaps

None. The listed gaps are HIGH or MEDIUM by the calibrated rubric. The notebook storage gap comes close but the data is local-filesystem and re-buildable from arXiv + re-ingest (at cost), so it does not reach "silent data-loss with no recovery path."

---

## 3. High Gaps

### H1 — No base docker-compose.yml

**Gap name:** Base docker-compose absent  
**Severity:** HIGH

**What comparable systems/SOTA expect:** Every comparable local-first research tool with a Dockerfile ships a companion `docker-compose.yml` within the same repo. The `08-security-observability-ops.md` design constitution (§ "Docker deployment") specifies a two-service YAML (`arxmcp-server` + `arxmcp-ingest`) with named volume mounts, port binding to 127.0.0.1, non-root UID, `no-new-privileges`, and `restart: unless-stopped`. That YAML is the authoritative target shape. The `infra/observability/phoenix-compose.yml` ships for the sidecar Phoenix profile, proving the compose tooling works; the base stack does not.

**What arXMCP has today:** `docker/Dockerfile.server` (complete, multi-stage, non-root, tini). `infra/README.md:7` — "The base docker-compose.yml ... is not yet shipped — tracked as future work." CLAUDE.md §5 layout still reads `infra/ └── README.md  placeholder for docker-compose (E14)`. `make up` invokes `python -m server.main` bare-metal.

**What a credible v1 fill-in looks like:** Ship `infra/docker-compose.yml` with (a) `arxmcp-server` service built from `docker/Dockerfile.server`, port binding `127.0.0.1:7733:7733`, a named volume `arxmcp-var` mounted at `/app/var/arxmcp`, and healthcheck inheriting from the Dockerfile's existing `HEALTHCHECK`; (b) `arxmcp-ingest` service from a second lightweight Dockerfile in `docker/` sharing the same volume, profiles-gated (`docker compose --profile ingest up`). Volume declaration uses a named Docker volume (not a bind mount) so disk location is Docker-managed and `docker volume inspect` / `docker volume rm` give the operator a clean lifecycle. The Phoenix compose in `infra/observability/` already demonstrates this pattern with `extends`.

**Architecture-lock interaction:** No hard-rule conflict. The loopback binding (`127.0.0.1:7733:7733`) is required by CLAUDE.md §4.7; the compose file must NOT expose `0.0.0.0`. The design constitution's YAML snippet (08-security-observability-ops.md:288) already has `ARXMCP_BIND_HOST=0.0.0.0` inside the container with `127.0.0.1:7733:7733` as the port map — that is the standard container loopback pattern (host side is loopback; inside the container the server binds 0.0.0.0 because its loopback is the container's own network namespace). `server/config.py::reject_non_loopback` must be updated to allow 0.0.0.0 when `ARXMCP_IN_CONTAINER=1` is set, mirroring the existing E14 Phoenix profile approach.

**Why this hasn't been fixed yet:** Explicitly deferred in E14's scope; "E14_S06 DEFERRED WORK TRACKER" notes the base compose as a Tier-6+ follow-up. The Phoenix-sidecar compose shipped (E14_S03) as a standalone deliverable but the two-service base stack was left for a future milestone that hasn't been planned.

---

### H2 — Notebook storage excluded from restic backup

**Gap name:** Notebook data absent from restic backup scope  
**Severity:** HIGH

**What comparable systems/SOTA expect:** NotebookLM (Gemini) and Obsidian both treat user-created notebook data as first-class persistent state with explicit export/backup affordances. Any local-first research tool that accepts user uploads (PDFs, HTML files, curated paper lists) owes the operator a durable backup path. The arXMCP restic setup (E14_S05) is specifically the canonical backup mechanism; it already backs up `var/arxmcp/corpus/` and `var/arxmcp/index/lancedb/`.

**What arXMCP has today:** E14_S05 ships `restic` backup + restore drill covering: corpus raw+parsed, LanceDB indices, Kùzu graph. The `08-security-observability-ops.md` backup section (line 233–250) lists what to back up; `var/arxmcp/notebooks/` is not in that list. `server/notebooks_store.py`'s module docstring confirms the SQLite file lives at `var/arxmcp/cache/notebooks.db` and explicitly says caches are "NOT backed up." The distinction between "cache" (regenerable, OK to lose) and "notebook metadata" (user-entered slugs, display names, paper lists, uploaded PDFs) is not drawn anywhere in the ops note. The PDFs under `var/arxmcp/notebooks/<slug>/pdfs/` are user uploads that cannot be re-fetched automatically; losing them requires the operator to re-upload.

**What a credible v1 fill-in looks like:** Extend the restic backup runbook (`docs/ops/backup-restore.md` / E14_S05 artifact) to include two additional paths: `var/arxmcp/notebooks/` (per-notebook LanceDB, parsed HTML, ar5iv HTML, PDFs) and `var/arxmcp/cache/notebooks.db` (metadata + ingest-run log + parse-status). Add an explicit comment distinguishing notebooks (user data, non-regenerable) from retrieval caches (regenerable, excluded). If the restic include-list is in a shell script, add the two paths and update the restore drill to verify a notebook slug survives a restore cycle.

**Architecture-lock interaction:** No hard-rule conflict. Restic operates on the host filesystem and does not interact with the server process or ASGI stack. The only constraint is that `var/arxmcp/` is gitignored by design; the backup adds a restic repository as the persistence layer, not git tracking.

**Why this hasn't been fixed yet:** The ops note was written before the notebook feature existed (E14 predates the notebook-retrieval / proof-verify milestones). The backup section was never retroactively updated when the notebook tree grew. This is a deferred-update failure mode, not a deliberate scoping decision.

---

## 4. Medium Gaps

### M1 — Design constitution (06-mcp-server-design.md + E13_S06 artifact) claims "no frontend exists"

**Gap name:** Stale "no frontend" documentation claim  
**Severity:** MEDIUM

**What comparable systems/SOTA expect:** Design notes function as onboarding material for sub-agents. A claim as definitive as "no frontend exists, by design" gates every future agent's threat-model reasoning for the UI surface (XSS, CSP, htmx injection, template injection). E13_S06 explicitly scoped out "Frontend-UX: N/A (no frontend exists in arXMCP)" — meaning the security audit never reviewed the Jinja2/htmx stack that shipped via proof-verify-handler-wiring-m7 through m10.

**What arXMCP has today:** `server/routes/ui.py` (full Jinja2+htmx shell with three page routes), `server/routes/notebooks.py` (REST + htmx-fragment upload), `frontend/templates/{base,index,notebook_detail}.html`, `frontend/static/{htmx.min.js,app.css}`. The `.claude/notes/milestones/E13_S06/critique-merged.md:5` literally says "Frontend-UX: N/A (no frontend exists in arXMCP)." `.claude/notes/06-mcp-server-design.md` has no mention of the UI routes, the htmx stack, or the frontend/ directory — the note is frozen at the E06 architecture shape. CLAUDE.md §5 directory layout table (line 244) still reads `infra/ └── README.md  placeholder for docker-compose (E14)` and has no mention of `server/routes/`, `server/notebooks_store.py`, or `frontend/`.

**What a credible v1 fill-in looks like:** Update `.claude/notes/06-mcp-server-design.md` with a "Notebook management UI" section covering the htmx shell at `/ui/`, the REST API at `/ui/api/`, the frontend/ layout, and the CSP override mechanism (`CONTENT_SECURITY_POLICY_PREVIEW`). Update CLAUDE.md §5 to add `server/routes/`, `server/notebooks_store.py`, and `frontend/` to the directory layout table. Add a one-line note to the E13_S06 milestone state that the UI surface was not audited (so a future security scout knows to cover it). None of these are code changes.

**Architecture-lock interaction:** Documentation-only. No hard-rule conflict.

**Why this hasn't been fixed yet:** The notebook UI shipped incrementally across proof-verify-handler-wiring-m7 through m10 as a feature stream separate from the main E01–E14 epic numbering. The design-constitution update protocol (which governs numbered notes) was not triggered for these milestones.

---

### M2 — No human-friendly "is it running / ready" surface in the UI or CLI

**Gap name:** Machine-only operability — no operator status surface  
**Severity:** MEDIUM

**What comparable systems/SOTA expect:** Local-first research tools like Ollama expose a `/` or `/status` HTML page that a non-expert can load in a browser to confirm the service is up and which models are loaded. Tools like Zotero, Obsidian, and calibre-web all show server health in an in-app status panel. The MCP ecosystem expects a human-accessible sanity check beyond `curl /readyz`.

**What arXMCP has today:** `/healthz` returns `{"status": "ok"}` JSON (always 200). `/readyz` returns `{"status": "ready"|"not_ready"|"degraded", "warm": {...}}` JSON (200 or 503). `/debug/cache-stats` returns cache counters JSON. `/metrics` returns Prometheus text. The `base.html` footer (`frontend/templates/base.html:59`) has two hyperlinks: `<a href="/healthz">/healthz</a>` and `<a href="/readyz">/readyz</a>` — both open a raw JSON page, which is not operator-friendly. There is no `make status` target in the Makefile. The install.md does not mention the notebook UI URL (`http://127.0.0.1:7733/ui/`) at all — an operator who follows install.md would not know the browser UI exists.

**What a credible v1 fill-in looks like:** Two changes. First, add a `make status` Makefile target that curls `/readyz`, `/debug/cache-stats`, and prints a human-readable summary (`arxmcp-server: ready (embedder warm, lancedb warm) | corpus_version=7 | notebooks: 3`). This is a ~10-line shell one-liner. Second, replace the `/healthz` + `/readyz` links in `base.html` footer with a single `/ui/status` mini-page (or an htmx-injected status badge in the header) that renders the readyz JSON as prose ("Server: ready — 3 notebooks, corpus v7"). This closes the "operator visits the UI and has no idea if retrieval is warm" UX gap.

**Architecture-lock interaction:** Pure-ASGI constraint is met if the `/ui/status` page is a standard FastAPI route returning an HTML response. The Makefile target is shell; no Python changes needed. The `SecFetchSiteMiddleware` carve-out for `/ui` already covers this.

**Why this hasn't been fixed yet:** Each notebook UI milestone focused on feature delivery (add papers, upload, ingest, preview). Operator onboarding UX is cross-cutting and wasn't scoped into any single milestone.

---

### M3 — No notebook-level corpus_version / ingest-freshness indicator in the UI

**Gap name:** No per-notebook ingest-freshness signal in browse UI  
**Severity:** MEDIUM

**What comparable systems/SOTA expect:** Every notebook-scoped retrieval system (Zotero, Semantic Scholar Recommender, Paperspace Gradient) shows when a corpus was last updated or how many documents are indexed. The arXMCP UI shows paper IDs and added timestamps but gives no indication of whether a notebook's LanceDB is populated, stale, or needs re-ingest.

**What arXMCP has today:** The notebook detail page (`frontend/templates/notebook_detail.html`) shows: slug, display_name, lancedb_path, created_at, paper list, ingest status (running/success/failed via htmx polling). It does NOT show: corpus_version of the per-notebook LanceDB, chunk count, last successful ingest timestamp, or whether the notebook's LanceDB even has any data (a notebook with papers added but never ingested looks identical to one that was ingested successfully — both show papers in the table). The REST API `GET /ui/api/notebooks/{slug}` returns the notebooks row but does not include any LanceDB-level stats. `server/notebooks_store.py` has no field for `last_ingest_succeeded_at` or `chunk_count`.

**What a credible v1 fill-in looks like:** Add a `last_ingest_succeeded_at` text column to the `notebooks` SQLite table (v4→v5 additive migration; backfill with NULL) and update the ingest-run done-callback to write it on success. Surface it in the detail page as "Last indexed: 2026-05-28T18:33" (or "Never indexed" if NULL). Optionally, at page-load time, read the per-notebook `corpus-version.json` marker (already written by `notebook_ingest.py`) to surface the corpus version integer. This gives the operator the minimum "is this notebook searchable" signal without adding a full LanceDB stat query to every page load.

**Architecture-lock interaction:** SQLite additive migration follows the established v3→v4 pattern (ALTER TABLE ADD COLUMN with DEFAULT). No ASGI or BP1/BP2 implications; this is storage and UI, not the MCP tool surface.

**Why this hasn't been fixed yet:** The ingest-status surface (trigger + polling) shipped in proof-verify-handler-wiring-m9 and covers the in-flight case. The "did this notebook ever finish indexing" summary was not part of the m9 scope; it's a cross-cutting UX concern.

---

### M4 — No notebook-scope BM25 for textbook-kind notebooks

**Gap name:** Textbook notebook search is dense-only (no BM25)  
**Severity:** MEDIUM

**What comparable systems/SOTA expect:** Every hybrid-retrieval system (OpenAI file-search, Cohere RAG, arXMCP's own arXiv corpus) combines dense ANN with BM25. The arXMCP design constitution (E07) explicitly treats hybrid-retrieval as a Tier-1 quality gate. The textbook-ingest m12 milestone brief explicitly states: "Build a per-notebook BM25 index (as notebook_ingest.py does) or skip it (search_papers is dense-only at v1, so dense suffices for the e4 demo)?" — the shipped answer was skip it.

**What arXMCP has today:** `tools/notebook_textbook_ingest.py` (textbook-ingest-m12) embeds and writes textbook chunks to the per-notebook LanceDB but does NOT build a BM25 index. The `tools/notebook_ingest.py` (arXiv notebooks) DOES build a per-notebook BM25 index via `bm25_indexer.py`. The arXiv path gets BM25; the textbook path gets dense-only retrieval. The research-synthesis for m12 (line 36) documents this explicitly: "BM25 skip: search_papers is dense-only at v1 — skip the BM25 build for the e4 demo."

**What a credible v1 fill-in looks like:** After `write_chunks` succeeds in the textbook ingest driver, run `build_bm25_index(lancedb_path, corpus_version)` (already exists in `ingest/bm25_indexer.py`) against the per-notebook LanceDB — the same call `notebook_ingest.py` makes. This is a 3-line addition to `tools/notebook_textbook_ingest.py`. The BM25 index is already used by `server/retrieval/bm25.py` when the notebook LanceDB is selected. The only bloat is a pickle file under the per-notebook `var/arxmcp/notebooks/<slug>/` tree — acceptable.

**Architecture-lock interaction:** None. `bm25_indexer.py` is a pure-Python utility that reads from LanceDB and writes a pickle file; no server-side or ASGI changes.

**Why this hasn't been fixed yet:** Deferred explicitly in m12's design synthesis as an "acceptable v1 limitation for the e4 demo." It was the right call for a scoped milestone; it's a known gap.

---

## 5. Low Gaps

### L1 — `CLAUDE.md §5` directory layout is visibly stale (missing server/routes/, frontend/, notebooks_store.py)

**Gap name:** CLAUDE.md layout table stale  
**Severity:** LOW

**Evidence:** CLAUDE.md §5 (`infra/ └── README.md  placeholder for docker-compose (E14)`) has no mention of `server/routes/`, `server/notebooks_store.py`, `server/ingest_tracker.py`, `server/parse_tracker.py`, `frontend/`, or `tools/notebook_*.py`. A new agent reading §5 to understand the repo layout gets an incomplete picture of the notebook feature surface. The directory listing also still says "1311 pytest tests" in §4.5 when the actual count is 2100+.

**What a credible v1 fill-in looks like:** Update the §5 table to add `server/routes/` (per-feature route modules), `server/notebooks_store.py`, `frontend/` (htmx shell + static assets), and extend the `tools/` listing to include `notebook_ingest.py`, `notebook_purge.py`, `notebook_textbook_ingest.py`. Update §4.5 test count to 2100. These are documentation edits only.

**Architecture-lock interaction:** None.

**Why this hasn't been fixed yet:** CLAUDE.md §5 was written for E01–E14 and was not retroactively updated as the notebook feature stream (proof-verify-handler-wiring-m7 through textbook-ingest-m12) added new top-level modules. Incremental milestone docs don't touch the constitution.

---

### L2 — install.md does not mention the notebook UI at http://127.0.0.1:7733/ui/

**Gap name:** Notebook UI undiscoverable from install doc  
**Severity:** LOW

**Evidence:** `docs/install.md` is the authoritative operator-facing setup guide. It covers the MCP registration, ARXMCP_NOTEBOOK env var, per-call notebook selection, and the parse-status API endpoint. It does NOT mention that navigating to `http://127.0.0.1:7733/ui/` opens the notebook management browser UI. An operator following install.md from scratch would use only the CLI tools (`notebook_ingest.py`, etc.) and never discover the browser UI.

**What a credible v1 fill-in looks like:** Add a §"Notebook management UI" subsection to install.md: "Once the server is running, open `http://127.0.0.1:7733/ui/` in your browser to create and manage notebooks, add papers by URL, upload ar5iv HTML files, and trigger ingest. The UI is the recommended entry point for notebook management; the CLI tools remain available for scripting."

**Architecture-lock interaction:** None. Documentation only.

**Why this hasn't been fixed yet:** The UI shipped across multiple proof-verify milestones that updated install.md for specific features (parse-status endpoint) but not for the full browser-UI affordance.

---

### L3 — No `Dockerfile.ingest` or ingest service image

**Gap name:** Ingest service has no container image  
**Severity:** LOW

**Evidence:** `docker/Dockerfile.server` exists and is well-engineered (multi-stage, non-root, tini). No `docker/Dockerfile.ingest` exists. The design constitution's compose YAML references `arxmcp/ingest:latest` but there is no build target for it. The `make ingest` target runs bare-metal. If/when `infra/docker-compose.yml` ships (H1), the `arxmcp-ingest` service would need a Dockerfile.

**What a credible v1 fill-in looks like:** A minimal `docker/Dockerfile.ingest` inheriting from the same `python:3.11-slim` base, installing ingest deps from `pyproject.toml`, copying `ingest/` + `tools/`, and setting `ENTRYPOINT ["python", "-m", "ingest.bulk_ingest"]` (or similar). It does not need `tini` (not long-running); it does need the same non-root UID pattern for security posture parity.

**Architecture-lock interaction:** No hard-rule conflict. The ingest container does not host an ASGI app. Loopback binding is not applicable here.

**Why this hasn't been fixed yet:** The ingest service compose is blocked on the base docker-compose.yml (H1). Building the ingest Dockerfile before its compose wiring exists has no immediate payoff.

---

## 6. What arXMCP Does Well

- **Per-notebook LanceDB MVCC + corpus_version pinning.** Each notebook gets its own `dataset.checkout(version=N)` semantics; a notebook re-ingest never races with in-flight queries. The `corpus-version.json` marker per notebook mirrors the shared-corpus pattern exactly.

- **Metadata-only deletion contract with explicit purge CLI.** `DELETE /ui/api/notebooks/{slug}` wipes SQLite metadata but never touches the on-disk LanceDB/PDFs/ar5iv tree; `tools/notebook_purge.py` is the explicit destructive path. This avoids the "operator clicks delete and loses 2 GB of parsed textbook" failure mode.

- **htmx-over-htmx polling ingest status with HTTP 286 stop-signal.** The ingest-trigger → 2s-poll → HTTP-286-terminal pattern is the textbook htmx implementation. The polling stops automatically on terminal state without client-side JavaScript logic. This is cleaner than most local-first tools that require a full-page reload to see job completion.

- **PDF preflight gate (5-vector) + per-kind upload caps.** The magic-byte sniff, polyglot tail scan, JS detection, page-count heuristic, and MIME routing are a well-engineered first line of defense for user-supplied PDFs. The per-notebook-kind cap (200 MB for textbook, 10 MB for arXiv) prevents accidental over-upload while staying practical for large textbooks.

- **Pure-ASGI security posture on the UI routes.** The `SecFetchSiteMiddleware` carve-out for `/ui/` is surgically correct (same-origin fetch from the htmx shell must pass; DNS-rebinding via `/mcp` must still 403). `OriginValidation` and `HostValidation` still fire. The CSP override mechanism for the ar5iv preview route (per-response header beats SecurityHeadersMiddleware) is the right pattern for per-route policy tightening.

- **Orphan recovery at lifespan startup.** Both the ingest-run orphan sweep (m9 FM-5) and the parse-run orphan sweep (textbook-ingest-m6 FM-4) run before the new daemon accepts any requests. A hard-killed daemon leaves no "permanent 409" state for the operator.

---

## 7. Themes

The dominant pattern across the HIGH and MEDIUM gaps is **feature-stream drift vs. the design constitution**: the proof-verify-handler-wiring and textbook-ingest milestone series shipped a meaningful operator-facing product (browser UI, notebook management, PDF parse pipeline) that was never reflected back into the numbered design notes, the security audit scope, or the ops playbook. The constitution was written for E01–E14; the post-E14 feature stream operated autonomously and skipped the update step.

A secondary theme is **infrastructure completeness gap**: the base docker-compose.yml and the notebook backup coverage are both explicitly scoped-out items that were promised in the design constitution (08-security-observability-ops.md) but never delivered — the Phoenix sidecar compose shipped, but the two-service base stack and the notebook backup path did not. The longer these stay unshipped, the wider the gap between the "designed" and "actual" deployment story.

A third theme is **operability UX not keeping pace with feature growth**: the health/readyz/metrics stack is solid for machine consumers (Prometheus, k8s probes) but the browser UI gives a non-expert operator no "is this server ready to retrieve" signal. As the notebook feature grows, this gap will widen.
