# Comparative Landscape Brief — 2026q2-notebook-ux-storage-ops

**Scout ID:** 2026q2-notebook-ux-storage-ops  
**Date:** 2026-05-28  
**Scope:** Notebook management UX · Durable/portable local-first storage · Operability ("is it running") · Container packaging

---

## 1. TL;DR

The three highest-value capabilities to consider are: (1) an **async ingest-task status endpoint** modeled on Paperless-ngx's `POST /documents/ → task_id → GET /tasks/?task_id=` pattern, which would let the existing Jinja2/htmx UI show per-paper parse/embed progress without polling the full server state; (2) a **lightweight `GET /status` JSON probe** (combining liveness + model-warm state + notebook slug + corpus_version) surfaced as a small htmx-polled badge in the notebook detail page, following the LM Studio `{"running": true, "port": ...}` shape; and (3) a **base `docker-compose.yml`** with `depends_on: condition: service_healthy` wiring the `server` service's `/readyz` probe, named Docker volumes for `var/arxmcp/` data, and an optional Prometheus+Grafana profile — a gap the infra/README explicitly acknowledges as unshipped.  The main thematic gap is that arXMCP already has the three foundational pieces (htmx shell, `/readyz`, restic backup) but lacks the glue that promotes them from developer-grade to operator-grade: a unified status surface, async task feedback, and a compose stack that ties them into a self-documenting deployment.

---

## 2. Top Capability Candidates

### C1 — Async ingest-task status endpoint (202 + task_id poll)

**Capability name:** Async ingest-task status with UUID poll  
**Source system:** Paperless-ngx (`POST /api/documents/post_document/` → HTTP 200 + task UUID; `GET /api/tasks/?task_id={uuid}` → `{status, result, related_document}`)  
**Public evidence:** https://github.com/paperless-ngx/paperless-ngx/blob/main/docs/api.md — "The endpoint will immediately return HTTP 200 if the document consumption process was started successfully, with the UUID of the consumption task as the data."  
**Capability angle:** When a user uploads a PDF or pastes an arXiv URL, the current REST API (`POST /ui/api/notebooks/{slug}/papers/upload`) returns synchronously. For slow ingest (LaTeXML parse + BGE-M3 embed can take 30–90 s per paper), there is no feedback loop. A task-UUID pattern lets the htmx UI poll `GET /ui/api/tasks/{task_id}` at ~2 s intervals and show `{status: "parsing" | "embedding" | "done" | "failed", progress_pct, paper_id}` without a WebSocket or SSE connection.  
**Technical angle:** Moderate. Requires a small task table in the existing `notebooks.db` SQLite (one row per ingest job: `task_id UUID, notebook_slug, paper_id, status, created_at, done_at, error_detail`). The ingest worker (currently synchronous in the FastAPI request path) must be pushed to a background asyncio Task or a subprocess. The htmx polling pattern already exists in htmx (`hx-trigger="every 2s"`, stop on HTTP 286). Pure-ASGI compatible: no additional process manager required for asyncio.Task path.  
**Cross-reference:** `server/routes/notebooks.py` — the upload handler currently blocks; `server/notebooks_store.py` — the store could host a `tasks` table.

---

### C2 — Lightweight unified `/status` JSON probe

**Capability name:** Combined liveness + readiness + runtime-state probe  
**Source system:** LM Studio CLI (`lms server status` → `{"running": true, "port": 1234}`); Ollama (`GET /api/ps` → loaded models + `expires_at`); Jupyter Server (`GET /api/status` → server activity)  
**Public evidence:** https://lmstudio.ai/docs/cli/serve/server-status (CLI JSON shape); https://github.com/ollama/ollama/blob/main/docs/api.md (`/api/ps` endpoint); https://jupyter-server.readthedocs.io/en/latest/developers/rest-api.html (`GET /api/status`)  
**Capability angle:** arXMCP has `/healthz` (liveness) and `/readyz` (readiness) but they return no machine-readable state beyond HTTP status code. A `/status` endpoint returning `{"healthy": true, "ready": true, "embed_model_warm": true, "corpus_version": 7, "notebook": "bridgeland-stability" | null, "uptime_s": 3721}` gives the htmx notebook index page a single poll target for a live status badge (green dot + corpus_version). Also enables `make status` to curl this endpoint and print a human-friendly summary, closing the operability gap without a tray app or GUI.  
**Technical angle:** Low. The data already exists: `server/health.py` knows liveness/readiness state; `server/corpus.py` tracks `corpus_version`; `server/config.py` holds the notebook slug. Aggregating into a new `GET /status` handler is a 30-line addition. No new dependencies. Pure-ASGI.  
**Cross-reference:** `server/health.py` (closest analog — but returns only HTTP 200/503, no JSON body); `server/metrics.py` (Prometheus exposition — not human-readable JSON).

---

### C3 — htmx SSE / polling status badge in Jinja2 shell

**Capability name:** Server-rendered live status badge via htmx polling  
**Source system:** htmx docs — `hx-trigger="every 2s"` pattern; htmx SSE extension (`hx-ext="sse"`, `sse-connect="/status/stream"`)  
**Public evidence:** https://htmx.org/docs/ — polling syntax: `<div hx-get="/status" hx-trigger="every 2s"></div>`; SSE extension: https://htmx.org/extensions/sse/  
**Capability angle:** The existing Jinja2 templates (`frontend/templates/base.html`, `notebook_detail.html`) render a static page. Adding a small `<span hx-get="/status" hx-trigger="load, every 10s" hx-swap="outerHTML">` in `base.html` would show a live "server ready / warming up" badge using only the vendored `htmx.min.js` already on disk. For ingest progress (C1), the same polling pattern with HTTP 286 as stop-signal provides progress feedback. No JavaScript framework, no SPA, pure htmx + Jinja2.  
**Technical angle:** Very low on the client side. Server side requires C1 (task endpoint) and C2 (status endpoint). The existing htmx setup in `frontend/static/htmx.min.js` is already wired. The constraint is that the CSP in `server/routes/ui.py` must allow the htmx `hx-on::htmx:afterRequest` inline handler pattern — review the `CONTENT_SECURITY_POLICY_PREVIEW` constant before adding new htmx event attributes.  
**Cross-reference:** `frontend/templates/base.html` (the shell — no live status badge today); `server/routes/ui.py` (CSP configuration is load-bearing).

---

### C4 — Named Docker volumes for `var/arxmcp/` with `docker-compose.yml`

**Capability name:** Base docker-compose stack with named volumes + healthcheck-gated depends_on  
**Source system:** Open WebUI compose (`open-webui:/app/backend/data` named volume); Grafana compose (`grafana_storage:/var/lib/grafana`); Ollama production guides (`depends_on: condition: service_healthy` + `healthcheck: test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]`)  
**Public evidence:** https://docs.openwebui.com/getting-started/quick-start/ (named volume pattern); https://grafana.com/docs/grafana/latest/setup-grafana/installation/docker/ (named volume example); https://last9.io/blog/docker-compose-health-checks/ (healthcheck + depends_on condition pattern)  
**Capability angle:** The `infra/README.md` explicitly states "The base docker-compose.yml ... is not yet shipped." A compose file with services `server` (bound to `127.0.0.1:7733`) and optionally `ingest`, with named volumes `arxmcp_index:/app/var/arxmcp/index`, `arxmcp_corpus:/app/var/arxmcp/corpus`, and `arxmcp_notebooks:/app/var/arxmcp/notebooks`, plus a `healthcheck: test: ["CMD", "curl", "-f", "http://localhost:7733/readyz"]` block, gives an operator a single `docker compose up -d` command that survives container restarts with durable data.  
**Technical angle:** Low-to-moderate. The Dockerfile.server already exists. The main gaps are: (a) model weights must be either baked into the image (large layer) or volume-mounted from a host cache dir; (b) the ingest service needs its own Dockerfile or shares the server image with a different entrypoint; (c) the Phoenix observability profile (`infra/observability/phoenix-compose.yml`) already ships — the base compose can `--profile phoenix` extend it. License: Docker Compose is Apache-2.0.  
**Cross-reference:** `docker/Dockerfile.server` (image exists); `infra/observability/phoenix-compose.yml` (the only shipped compose file); `infra/README.md` (explicit gap acknowledgment).

---

### C5 — Notebook portable export (tar archive with manifest)

**Capability name:** Per-notebook archive export (tar + manifest)  
**Source system:** Obsidian vault portability (plain-file vault folder, copy-and-go); Jupyter Server content API checkpoint (`GET /api/contents/{path}` + `POST /api/contents/{path}/checkpoints`); Paperless-ngx export directory (`./export` bind mount)  
**Public evidence:** https://obsidian.md/help/data-storage (vault = portable directory); https://jupyter-server.readthedocs.io/en/latest/developers/rest-api.html (`/api/contents/{path}/checkpoints`); Paperless-ngx docker-compose `./export` bind mount pattern  
**Capability angle:** arXMCP notebook storage is `var/arxmcp/notebooks/<slug>/` containing LanceDB, parsed HTML, PDFs, and the shared `notebooks.db` metadata entry. There is no export/import mechanic. A `GET /ui/api/notebooks/{slug}/export` that streams a tar archive (`manifest.json` + `lancedb/` + `papers/*.html` + `pdfs/*.pdf` + `bm25.pkl`) would let an operator migrate or back up a notebook independently of the full corpus. On re-import, a `POST /ui/api/notebooks/import` re-registers the manifest entry in `notebooks.db` and validates the slug.  
**Technical angle:** Moderate. Streaming tar from FastAPI is straightforward (`tarfile` + `StreamingResponse`). The LanceDB directory must be closed cleanly before archiving (read-only handle is safe). The BM25 pickle and parsed HTML are plain files. The main risk is partial-write during a live ingest (C1 task must be complete before export is allowed). No new dependencies; pure-ASGI.  
**Cross-reference:** `server/routes/notebooks.py` — `DELETE /notebooks/{slug}` is metadata-only (on-disk wipe is `tools/notebook_purge.py`); no export route exists today. `tools/_notebook_common.py` — `notebook_dir()` gives the source path.

---

### C6 — Litestream local-file replication of `notebooks.db`

**Capability name:** SQLite WAL replication to a local file path  
**Source system:** Litestream (`type: file` replica — `path: /backup/notebooks.db`; also SFTP replica for NAS target)  
**Public evidence:** https://litestream.io/reference/config/ — "If no `type` field is specified and a `url` is not used then `file` is assumed" with `path:` config; SFTP variant also documented.  
**Capability angle:** `var/arxmcp/cache/notebooks.db` is the single SQLite file tracking all notebook metadata, paper junctions, and (with C1) task state. It is currently backed only by the E14-shipped restic nightly snapshot. Litestream replicates at WAL-segment granularity (sub-second lag) to a second local path (e.g. a NAS mount or a different disk), providing a finer-grained restore point than nightly restic without cloud dependency. Runs as a sidecar process alongside the server.  
**Technical angle:** Low operational complexity once installed. Litestream is a single Go binary (MIT license, Ben Johnson). The `file` replica type needs no cloud account. The constraint is that the application must use WAL mode (SQLite `PRAGMA journal_mode=WAL`) — arXMCP should verify this is set on `notebooks.db`. Docker: the sidecar pattern mounts the same volume as the server container. Note: `resource.setrlimit` on macOS irrelevance is not in scope here — Litestream has no such dependency.  
**Cross-reference:** `server/cache_sqlite.py` (the Tier-1 cache SQLite — same pattern would apply); `var/arxmcp/cache/notebooks.db` (the target); E14_S05 restic nightly (complementary, not competing — restic handles full-corpus snapshots, Litestream handles continuous notebook metadata replication).

---

### C7 — Healthcheck-driven `make status` CLI command

**Capability name:** `make status` / `make check` operator CLI probe  
**Source system:** LM Studio CLI (`lms server status` → `{"running": true, "port": 1234}`); Ollama no-health-endpoint gap (community uses `curl /api/tags` as proxy); restic `restic check` (integrity verification)  
**Public evidence:** https://lmstudio.ai/docs/cli/serve/server-status; Ollama issue https://github.com/ollama/ollama/issues/1378 (no dedicated health endpoint — community workaround confirms the gap is real); restic docs  
**Capability angle:** A single `make status` target that curls `/status` (C2), parses the JSON, and prints a human-friendly block: `Server: READY | Embed model: warm | Corpus v7 | Notebook: bridgeland-stability | Uptime: 1h02m`. This closes the "is it running" operability gap for non-Docker users (bare-metal `make up`) without requiring a tray app, a dashboard, or browser navigation. Also useful in CI / smoke-test scripts.  
**Technical angle:** Very low. One Makefile target using `curl -sf http://127.0.0.1:7733/status | python3 -c "import sys,json; d=json.load(sys.stdin); ..."`. No new dependencies.  
**Cross-reference:** `Makefile` — existing targets `up`, `test`, `eval`; no `status` target today. `server/health.py` — `/healthz` returns 200/503 with no body.

---

### C8 — Docker healthcheck surfaced as compose `condition: service_healthy`

**Capability name:** HEALTHCHECK directive in Dockerfile + `depends_on: condition: service_healthy`  
**Source system:** Ollama production patterns (`healthcheck: test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]`); NVIDIA AI Workbench compose patterns (`test: ["CMD", "python3", "-c", "import requests; requests.get('http://localhost:8000/v1/health/ready')"]`); Docker Compose documentation  
**Public evidence:** https://last9.io/blog/docker-compose-health-checks/ (interval, timeout, retries, start_period); https://docs.nvidia.com/ai-workbench/user-guide/latest/reference/projects/compose-patterns-reference.html (AI-specific healthcheck patterns); Ollama community compose files  
**Capability angle:** The existing `docker/Dockerfile.server` has no `HEALTHCHECK` directive. Adding `HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=3 CMD curl -f http://localhost:7733/readyz || exit 1` enables: (a) `docker ps` shows health state; (b) a future compose stack can gate dependent services on `condition: service_healthy`; (c) operator-visible signal when the BGE-M3 model is still warming. The `start_period=90s` is important: BGE-M3 cold load takes 30–60 s.  
**Technical angle:** Very low. One `HEALTHCHECK` line in the Dockerfile. The `/readyz` endpoint already exists in `server/health.py`. The only constraint is that `curl` must be installed in the runtime image — the current slim image may need `curl` added to the apt install list.  
**Cross-reference:** `docker/Dockerfile.server` — no HEALTHCHECK line today; `server/health.py` — `/readyz` is the right probe target.

---

### C9 — Ingest-status panel in notebook detail page (htmx fragment append)

**Capability name:** Per-paper ingest-status column in the papers table  
**Source system:** Paperless-ngx document consumption workflow (upload → task UUID → poll → document appears in library); Open WebUI document library (upload → processing indicator in list view)  
**Public evidence:** Paperless-ngx PR #2279 (https://github.com/paperless-ngx/paperless-ngx/pull/2279) — "Return created task ID when posting document to API"; Open WebUI docs (RAG document processing status)  
**Capability angle:** The existing `notebook_detail.html` renders a papers table (paper_id, title, date added). There is no column showing whether the paper has been parsed and embedded. A `status` column (`pending | parsing | embedding | ready | failed`) polled via htmx fragment swap would let an operator see at a glance which papers are usable vs still ingesting. This is the UX completion of C1 (task endpoint) — C1 is the server-side mechanism; C9 is the rendering.  
**Technical angle:** Low, depends on C1. The htmx fragment upload endpoint already exists (`/ui/api/notebooks/{slug}/papers/upload` returns an HTML fragment). The same pattern extends to a `GET /ui/api/notebooks/{slug}/papers/{paper_id}/status` → HTML fragment showing the status badge. The `hx-swap="outerHTML"` pattern replaces a placeholder badge once the paper is ready, using `HTTP 286` to stop polling.  
**Cross-reference:** `frontend/templates/notebook_detail.html` — papers table; `server/routes/notebooks.py` — upload endpoint returns HTML fragment (m8 pattern).

---

### C10 — Jinja2/htmx notebook management actions (rename, reorder, delete with confirmation)

**Capability name:** In-page notebook CRUD with htmx confirmations  
**Source system:** Jupyter Server content API (PATCH `/api/contents/{path}` for rename; DELETE for removal); Paperless-ngx bulk operations API (`/api/documents/bulk_edit/`)  
**Public evidence:** https://jupyter-server.readthedocs.io/en/latest/developers/rest-api.html (PATCH rename, DELETE); Paperless-ngx API (bulk_edit endpoint)  
**Capability angle:** The current notebook index (`GET /ui/`) shows a list of notebooks with an "open" link. There is no rename, reorder, or soft-delete action in the UI (only the API `DELETE /ui/api/notebooks/{slug}` exists). An htmx-powered action row — `hx-delete="/ui/api/notebooks/{slug}" hx-confirm="Delete notebook metadata? (data preserved on disk)"` and a rename form — would complete the notebook management UX without a SPA. The `hx-confirm` attribute renders a browser confirm dialog, requiring no custom JavaScript.  
**Technical angle:** Very low. The REST endpoints already exist (`DELETE /ui/api/notebooks/{slug}`). Rename requires a new `PATCH /ui/api/notebooks/{slug}` endpoint that updates the `notebooks.db` display name (not the slug — slug is structural). The `hx-delete` + `hx-confirm` + `hx-target="closest tr" hx-swap="outerHTML"` pattern removes the table row on success.  
**Cross-reference:** `server/routes/notebooks.py` — `DELETE /notebooks/{slug}` exists; no rename endpoint; `frontend/templates/index.html` — notebooks list; `server/notebooks_store.py` — store methods.

---

## 3. Sources Reviewed

| System | URL | What was read | High-signal? |
|---|---|---|---|
| Ollama API docs | https://docs.ollama.com/api | `/api/ps`, `/api/tags`, `/api/version` endpoints; no dedicated health endpoint | Yes — confirms the pattern of using `/api/tags` as a healthcheck proxy |
| Ollama production deploy guide | https://markaicode.com/ollama-production-health-checks-monitoring-guide/ | `HEALTHCHECK` + `depends_on: condition: service_healthy` docker-compose patterns | Yes |
| LM Studio CLI docs | https://lmstudio.ai/docs/cli/serve/server-status | `lms server status` → `{"running": true, "port": ...}` JSON shape | Yes — clearest "is it running" CLI shape |
| Open WebUI README | https://github.com/open-webui/open-webui/blob/main/README.md | Knowledge base / RAG document library; docker-compose named volume pattern | Partial — compose details sparse |
| Open WebUI quick-start | https://docs.openwebui.com/getting-started/quick-start/ | `open-webui:/app/backend/data` named volume; no healthcheck in base compose | Yes |
| Paperless-ngx API | https://github.com/paperless-ngx/paperless-ngx/blob/main/docs/api.md | `POST /documents/post_document/` → task UUID; `GET /tasks/?task_id=` status poll; `/api/documents/bulk_edit/` | Yes — most directly applicable async ingest pattern |
| Paperless-ngx compose | https://github.com/paperless-ngx/paperless-ngx/blob/dev/docker/compose/docker-compose.portainer.yml | Named volumes (data, media, pgdata, redisdata); restart policy; no healthcheck in portainer variant | Partial |
| Jupyter Server REST API | https://jupyter-server.readthedocs.io/en/latest/developers/rest-api.html | `GET /api/status`, `GET /api/contents/{path}`, checkpoints, session management | Yes |
| htmx docs | https://htmx.org/docs/ | Polling (`hx-trigger="every 2s"`), swap strategies, file upload progress events | Yes |
| htmx SSE extension | https://htmx.org/extensions/sse/ | `sse-connect` + `sse:<event_name>` trigger pattern | Yes |
| Litestream config reference | https://litestream.io/reference/config/ | `file` replica type (local path), SFTP replica; WAL-based replication | Yes |
| Litestream Docker guide | https://litestream.io/guides/docker/ | Sidecar pattern; same-OS constraint; volume sharing | Yes |
| Obsidian data storage | https://obsidian.md/help/data-storage | Vault = plain directory of Markdown + `.obsidian/` config folder; portable by design | Partial (no SQLite; not directly applicable) |
| Zotero sync | https://www.zotero.org/support/sync | WebDAV file sync; local-first default; manual copy-and-go portability | Partial — WebDAV is out of scope (multi-host) |
| Grafana Docker docs | https://grafana.com/docs/grafana/latest/setup-grafana/installation/docker/ | Named volume pattern; basic compose structure | Partial |
| Backrest (restic WebUI) | https://github.com/garethgeorge/backrest/blob/main/README.md | WebUI for restic; docker-compose sidecar; local + remote repo targets | Partial — restic already in E14_S05 |
| Docker healthcheck patterns | https://last9.io/blog/docker-compose-health-checks/ | `interval`, `timeout`, `start_period`, `retries`; `condition: service_healthy` | Yes |
| NVIDIA AI Workbench compose | https://docs.nvidia.com/ai-workbench/user-guide/latest/reference/projects/compose-patterns-reference.html | AI-specific healthcheck test patterns; multi-service GPU compose | Partial |

---

## 4. Cross-References to arXMCP

- **C1 (async task status)** — no analog in `server/routes/notebooks.py`; upload handler is fully synchronous. Net-new server pattern, though task-state storage could extend the existing `notebooks.db` SQLite.
- **C2 (unified `/status` probe)** — closest analog: `server/health.py` (`/healthz`, `/readyz`). Delta: those return HTTP status only; `/status` adds a JSON body with model-warm, corpus_version, notebook slug.
- **C3 (htmx status badge)** — closest analog: `frontend/templates/base.html` (the Jinja2 shell). Delta: no live polling element today. Depends on C2.
- **C4 (base docker-compose)** — closest analog: `infra/observability/phoenix-compose.yml` (the only shipped compose). Delta: no base `server` service compose, no named volumes for `var/arxmcp/`. Explicitly acknowledged gap in `infra/README.md`.
- **C5 (notebook export tar)** — no analog; `server/routes/notebooks.py` has delete (metadata-only) but no export. Net-new route.
- **C6 (Litestream local replication)** — closest analog: `infra/restic/nightly.sh` (E14_S05, nightly snapshot). Delta: Litestream is continuous WAL-replication of `notebooks.db` specifically; restic handles full-corpus block-level snapshots. Complementary layers.
- **C7 (`make status`)** — no analog; `Makefile` has `up`, `test`, `eval`. Net-new target. Trivially implemented once C2 exists.
- **C8 (HEALTHCHECK in Dockerfile)** — `docker/Dockerfile.server` has no `HEALTHCHECK` directive today. Closest analog: `/readyz` endpoint in `server/health.py`. One-line add.
- **C9 (per-paper status column)** — closest analog: `frontend/templates/notebook_detail.html` papers table (static columns today). Delta: no `status` column, no per-paper poll. Depends on C1.
- **C10 (htmx CRUD actions)** — closest analog: `server/routes/notebooks.py` `DELETE /notebooks/{slug}` (API exists, no UI action). Delta: `index.html` has no delete button or htmx binding today.

---

## 5. Themes

**Operator-grade operability is one thin layer away.** The core plumbing (health endpoints, htmx shell, restic backup, Docker image) already exists in arXMCP; what's missing is the glue: a JSON `/status` endpoint, a `HEALTHCHECK` directive, a `make status` target, and a base `docker-compose.yml` that ties them together. Each individual gap is low-complexity but collectively they determine whether a non-developer operator can confidently run the stack.

**Async ingest feedback is the highest-UX-leverage gap.** All surveyed systems (Paperless-ngx, Open WebUI) that handle document ingestion solve the same problem: the upload is fast but the processing is slow, and users need progress feedback. arXMCP's current synchronous upload handler is the primary UX anti-pattern, and the Paperless-ngx `task_id → /tasks/` poll pattern is the cleanest local-first solution (no WebSocket, no external queue, pure SQLite + HTTP polling).

**Notebook portability is underdeveloped relative to the storage investment.** arXMCP has per-notebook LanceDB + BM25 + parsed HTML on disk, but no way to export, migrate, or share a notebook. The analogues (Obsidian vault portability, Jupyter checkpoint API, Paperless-ngx export dir) all treat portability as a first-class operator concern. A tar-bundle export with a `manifest.json` is low-complexity and high-value.

**Named Docker volumes are the right storage pattern for `var/arxmcp/`.** The Open WebUI and Grafana patterns confirm the community consensus: named volumes (not bind mounts) for AI application data, because Docker manages the lifecycle and backup is easier (`docker volume inspect` gives the host path for restic to snapshot). The current `docker run -v "$PWD/var/arxmcp:/app/var/arxmcp"` bind-mount pattern in `Dockerfile.server`'s comments is fine for development but the production compose should use named volumes with `external: false`.

---

## 6. Out of Scope / Parking Lot

- **MinIO / SeaweedFS / Garage object storage** — AGPL (MinIO community edition) or early-stage (Garage). Multi-process dependency for single-workstation deployment adds operational overhead without a clear win over named Docker volumes + restic. Parking lot: revisit if multi-device sync becomes a requirement.
- **WebDAV sync (Zotero pattern)** — requires a network-accessible server; violates local-first / loopback-only hard constraint. Rejected.
- **Logseq / Obsidian plain-file vault format** — the notebooks concept in arXMCP is structured (LanceDB + BM25 + metadata), not a plain Markdown vault. The Obsidian portability model (copy a directory) is already effectively what a tar-export (C5) would provide; no separate Obsidian-format integration is warranted.
- **Backrest (restic WebUI)** — E14_S05 already ships `infra/restic/nightly.sh`. Adding a Backrest container is a nice-to-have UX enhancement but adds a service dependency. The existing restic CLI + cron pattern is sufficient for a single operator. Parking lot.
- **LiteFS (Fly.io distributed SQLite)** — requires a Fly.io-specific coordinator process; multi-host by design. Out of scope.
- **Jupyter checkpoint versioning** — checkpoints are notebook-content snapshots, not document-corpus versioning. The analogue in arXMCP is LanceDB MVCC (`corpus_version`), which already ships. No delta.
- **Tray app / desktop indicator (LM Studio green dot)** — requires a GUI framework (Electron, Tauri, PyQt). Out of scope for a headless MCP server; the `make status` + status badge (C2, C3, C7) cover the same need without a desktop app.
- **SPA frontend (React/Vue/Svelte)** — explicitly out of scope given the Jinja2+htmx architecture choice and the pure-ASGI constraint. The htmx patterns surveyed are sufficient for the required UX without a separate JS build step or a separate container.
- **Prometheus + Grafana full dashboard** — Prometheus metrics already exist (`server/metrics.py`, `/metrics`); Grafana config ships in `infra/observability/`. No capability delta; already addressed.
- **Multi-user auth / session isolation** — localhost-only single-operator deployment; auth is intentionally out of scope per CLAUDE.md §4.7.
