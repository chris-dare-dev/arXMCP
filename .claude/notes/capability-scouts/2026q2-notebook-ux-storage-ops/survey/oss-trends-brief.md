# OSS Trends Brief — Notebook UX, Storage, Operability, Container Packaging
**Scout run:** `2026q2-notebook-ux-storage-ops`
**Date:** 2026-05-28
**arXMCP version context:** E14 shipped (S01–S05), minimal Jinja2 notebook UI live (`server/routes/ui.py`, `frontend/templates/`), HTMX already vendored at `frontend/static/htmx.min.js`, notebook data local-filesystem only, no docker-compose base stack.

---

## 1. TL;DR

**Top-3 borrowable projects:** Litestream (SQLite WAL streaming to local replica — direct fit for `var/arxmcp/cache/notebooks.db` durability with zero added runtime deps), HTMX + sse-starlette (SSE-based ingest progress streaming already composable with the existing HTMX shell — no build chain, pure-ASGI), and Gatus (config-as-code health dashboard for the `/healthz`/`/readyz` surface, runnable as a one-container sidecar with a loopback port binding).

**Top theme:** arXMCP's biggest infra gap is that notebook data (the SQLite `notebooks.db` and the `var/arxmcp/notebooks/<slug>/` tree) is in-process filesystem-only with no durable snapshot, no backup trigger, and no docker-compose to gate service startup on a healthy MCP server. Every candidate below closes one slice of that gap.

**Main thematic gap:** The absence of a base `docker-compose.yml` (deferred since E06; `infra/README.md` calls it out explicitly) means the healthcheck-gated startup discipline already present in `docker/Dockerfile.server` is never surfaced to operators in a multi-service stack context. The compose gap also blocks adding storage sidecars (Litestream, Kopia) or a status dashboard (Gatus) via `depends_on: condition: service_healthy`.

---

## 2. Project candidates

### 2.1 Litestream

- **URL:** https://github.com/benbjohnson/litestream
- **License:** Apache-2.0
- **Stars / last commit:** 13.6k stars; latest release v0.5.11 dated April 8, 2026 (actively maintained)
- **What it does:** Litestream runs as a sidecar process (or as a Docker sidecar container) that continuously tails SQLite's Write-Ahead Log and streams LTX change frames to one or more replica destinations: S3-compatible object store, local directory, SFTP, or NATS JetStream. The v0.5 series (October 2025) introduced the LTX file format replacing the WAL-based generations system, enabling true point-in-time recovery via monotonically incrementing transaction IDs. Restoring to any snapshot is `litestream restore -timestamp <ISO8601>`. No server process is needed for the database itself; SQLite remains the primary store.
- **Specific capability worth borrowing:** The `litestream replicate` daemon pattern — configured via a single YAML file that maps the SQLite path to a local directory replica (`file:///var/arxmcp/backup/litestream`) — gives arXMCP hot WAL streaming without any network dependency. The local-replica mode means the backup lives at a second path on the same workstation, providing copy-on-write durability against accidental truncation or SQLite corruption. The `litestream restore` command supports a `--if-db-not-exists` flag that makes container-startup recovery idempotent: if the db exists, skip; if not (fresh volume), restore from latest replica.
- **arXMCP positioning:** Design-pattern lift. The `litestream replicate` config shape and the `--if-db-not-exists` startup idiom land in a new `infra/litestream.yml` config file + a `docker-compose.yml` sidecar service. The sidecar requires no Python changes; it consumes `var/arxmcp/cache/notebooks.db` via a shared named volume. Under the no-fork policy, nothing is vendored — Litestream runs as its own container image (`litestream/litestream`).
- **Risk flags:** Apache-2.0 permissive, study+deploy OK. Single-binary Go, no runtime Python deps. The v0.5 LTX format is NOT backward-compatible with v0.3.x WAL replicas — the CHANGELOG calls this out clearly. Since arXMCP has no existing Litestream replica, this is a non-issue for a fresh deployment. The `litestream/litestream` Docker image is multi-arch (amd64 + arm64); Apple Silicon works. No GPU dependency.

---

### 2.2 Kopia

- **URL:** https://github.com/kopia/kopia
- **License:** Apache-2.0
- **Stars / last commit:** 13.3k stars; latest release v0.23.0 dated May 12, 2026 (monthly cadence)
- **What it does:** Kopia is a cross-platform backup tool with client-side AES-256-GCM encryption, content-defined chunking deduplication, and snapshot-level retention policies. It supports local repository targets (a directory on the same machine), S3, Azure, GCS, SFTP, and a self-hosted Kopia Repository Server. The CLI can snapshot arbitrary paths — `kopia snapshot create /var/arxmcp` — and restore them with `kopia snapshot restore`. The GUI (KopiaUI) runs optionally. Key differentiator from restic: Kopia has a native repository server mode suitable for multi-workstation backup convergence, but in single-workstation mode it is purely local.
- **Specific capability worth borrowing:** The `kopia policy set --compression=zstd-better-compression` + `--keep-daily=7 --keep-weekly=4` pattern applied to the entire `var/arxmcp/` tree gives arXMCP a single-command full-state backup (LanceDB, Kùzu graph, SQLite cache, notebook files) with deduplication across snapshots. arXMCP already documents `restic` backup in E14_S05; Kopia is the stronger candidate for the `var/arxmcp/` tree because its content-defined chunking deduplicates LanceDB's lance/manifest files more efficiently than restic's fixed-size chunks against large binary segment files.
- **arXMCP positioning:** Design-pattern lift. The `make backup` / `make restore` Makefile targets (currently using restic per E14_S05 documentation) are the landing zone. If the team decides not to replace restic, the Kopia incremental-snapshot shape (one `kopia snapshot create var/arxmcp`) is still worth borrowing as the model for the `make backup` command structure. Under the no-fork policy, this is a CLI tool invoked as a subprocess — never imported.
- **Risk flags:** Apache-2.0 permissive. The repository server mode introduces a network listener — irrelevant for single-workstation use, but operators should not start `kopia server start` without loopback binding. CLI-only mode has no network surface. ~80 MB binary download. No GPU dependency.

---

### 2.3 HTMX (version 2.x)

- **URL:** https://github.com/bigskysoftware/htmx
- **License:** Zero-Clause BSD (0BSD) — maximally permissive, no attribution required
- **Stars / last commit:** 48.1k stars; actively maintained (HTMX 2.0 shipped mid-2024, ongoing patch releases)
- **What it does:** HTMX extends HTML with `hx-get`, `hx-post`, `hx-swap`, `hx-trigger`, and `hx-on` attributes, allowing full server-round-trip partial-DOM updates without writing JavaScript. At 14 kB minified+gzipped, it has no build chain and no `node_modules/`. The v2.x `server-sent-events` extension adds `sse-connect` and `sse-swap` attributes for streaming server-push updates into the DOM. The `hx-boost` attribute progressively enhances `<a>` and `<form>` elements. The `hx-indicator` attribute ties spinner/progress UI to in-flight requests.
- **Specific capability worth borrowing:** The `server-sent-events` extension pattern (HTMX 2.x): `<div hx-ext="sse" sse-connect="/ui/api/notebooks/{slug}/ingest-stream" sse-swap="message" hx-swap="beforeend">` streams ingest-progress rows from a FastAPI `EventSourceResponse` endpoint into the DOM in real time without a page reload. This is directly applicable to arXMCP's notebook ingest pipeline where `server/ingest_tracker.py` already tracks per-paper ingest state — the SSE endpoint would emit one HTML `<tr>` fragment per paper as it completes. The existing `hx-on::htmx:afterRequest` full-page-reload pattern in `server/routes/ui.py` is a deliberate simplification noted in the file docstring; SSE swap would upgrade the ingest-progress UX without requiring WebSocket complexity.
- **arXMCP positioning:** The HTMX library is already vendored at `frontend/static/htmx.min.js`. This is a capability unlock within the existing stack: add the SSE extension script (a second vendored 4 kB file) + add a streaming endpoint in `server/routes/notebooks.py` + update `frontend/templates/notebook_detail.html`. Zero dependency additions, zero build chain changes, pure-ASGI compatible.
- **Risk flags:** 0BSD means no restrictions, study+deploy OK. HTMX 2.x dropped IE support; irrelevant for a local-first developer tool. The SSE extension requires the `sse-starlette` library on the server side (see candidate 2.4). No GPU dependency.

---

### 2.4 sse-starlette

- **URL:** https://github.com/sysid/sse-starlette
- **License:** BSD-3-Clause
- **Stars / last commit:** 832 stars; v3.4.4 released May 12, 2026 (actively maintained, 406 commits)
- **What it does:** sse-starlette provides a production-ready `EventSourceResponse` class for Starlette and FastAPI that correctly handles async generator cleanup, client disconnects, cooperative shutdown under uvicorn signal handling, and the W3C SSE specification (`data:`, `event:`, `id:`, `retry:` fields). The library ships a `ServerSentEvent` named tuple for structured event construction. It is a pure-ASGI middleware-compatible implementation — it does NOT use `BaseHTTPMiddleware` (which is project-banned per CLAUDE.md §4.7); instead it is a `Response` subclass, compatible with pure-ASGI middleware stacks.
- **Specific capability worth borrowing:** The `EventSourceResponse` + async generator pattern: a FastAPI path operation returns `EventSourceResponse(generator())` where `generator()` is an `async def` that yields `ServerSentEvent(data=html_fragment, event="progress")` items as the ingest pipeline processes each paper. This integrates directly with `server/ingest_tracker.py` state and emits HTMX-compatible HTML fragments via SSE.
- **arXMCP positioning:** Native re-implementation is unnecessary; `sse-starlette` is a minimal library (BSD-3-Clause, permissive) that can be added to `pyproject.toml` as a dependency. The landing zone is `server/routes/notebooks.py` (new `GET /ui/api/notebooks/{slug}/ingest-stream` endpoint) + `frontend/templates/notebook_detail.html` (SSE extension attributes). The `EventSourceResponse` subclass approach is pure-ASGI — no `BaseHTTPMiddleware`.
- **Risk flags:** BSD-3-Clause permissive. Under arXMCP's no-fork policy this is a candidate for a direct `pip` dependency (it is a library, not an arxiv-mcp repo). The v3.x API changed event field names from v1.x; pin to `>=3.0`. 832 stars is below the scout's 50-star floor but the May 2026 release and 406-commit history indicate active maintenance. The author (sysid) maintains several Starlette-ecosystem packages with independent reputation.
- **Risk flags (continued):** No GPU dependency. No C deps. Pure Python.

---

### 2.5 Gatus

- **URL:** https://github.com/TwiN/gatus
- **License:** Apache-2.0
- **Stars / last commit:** 11.1k stars; v5.34.0 is current stable (active monthly release cadence)
- **What it does:** Gatus is a Go-based health monitoring daemon configured entirely via a YAML file — no database, no web-UI configuration, no persistent state beyond its SQLite-backed metric history. Each endpoint definition specifies a URL, check protocol (HTTP, TCP, ICMP, DNS), check interval, and a set of conditions (HTTP status code, response-body substring, response-time threshold, TLS expiry). The built-in status page auto-refreshes and shows a timeline of recent check results. It runs in ~40 MB RAM with 50 endpoints. The Docker image is `twinproduction/gatus`.
- **Specific capability worth borrowing:** The multi-endpoint YAML pattern that checks both `/healthz` (liveness — always 200) and `/readyz` (readiness — 200 only after BGE-M3 + LanceDB warm) and distinguishes them in the status page. arXMCP already has both endpoints; Gatus adds a "running/degraded/down" visual timeline without any server-side changes. The `conditions: ["[STATUS] == 200", "[RESPONSE_TIME] < 2000"]` format checks response time as well as status — useful for surfacing BGE-M3 warm/cold state differences. The YAML config lives in the repo at `infra/gatus.yml`, making it version-controllable alongside `infra/observability/phoenix-compose.yml`.
- **arXMCP positioning:** Design-pattern lift + new file. Add `infra/gatus.yml` (config) + a `gatus` service entry in the future base `docker-compose.yml` (or as a standalone sidecar compose like Phoenix). The pattern from `infra/observability/phoenix-compose.yml` — `profiles: ["gatus"]`, loopback port binding, `depends_on: condition: service_healthy`, `restart: "no"`, `cap_drop: ["ALL"]` — is directly reusable. No Python changes.
- **Risk flags:** Apache-2.0 permissive. The Gatus Docker image uses Docker Hub (`twinproduction/gatus`); for the project's SHA-pin discipline (phoenix-compose.yml §"content-addressable digest pin") the image reference should include a `@sha256:` digest. SQLite metric store inside the container; volume-mount if persistence across container restarts matters. No GPU dependency.

---

### 2.6 Datastar

- **URL:** https://github.com/starfederation/datastar
- **License:** MIT
- **Stars / last commit:** 4.5k stars; v1.0.1 released April 20, 2026 (actively maintained, 1,392 commits on develop branch, 34 releases)
- **What it does:** Datastar is a hypermedia-over-SSE framework that unifies the reactivity of Alpine.js (client signals) with the server-drive of HTMX into a single 11.8 kB script. The core model is "View = Function(State)": the server streams SSE fragments that both update the DOM (`datastar-fragment` events) and mutate client-side signals (`datastar-signal` events). The `data-on:click="@post('/endpoint')"` attribute fires HTTP requests; `data-bind:title="$mySignal"` binds DOM attributes to reactive signal state. The backend emits `text/event-stream` responses with `event: datastar-fragment\ndata: selector #id\ndata: merge morphdom\ndata: fragment <div>...</div>` payloads.
- **Specific capability worth borrowing:** The `datastar-signal` SSE event type — the server can push a signal update (`$ingestProgress = 0.75`) that the client binds to a `<progress data-bind:value="$ingestProgress">` element, without the client ever polling. This is a cleaner model than HTMX SSE for numeric progress reporting because the signal is reactive: multiple DOM elements can observe the same signal simultaneously without re-streaming the entire fragment. Worth studying as an upgrade path if the HTMX SSE approach proves awkward for the ingest-progress UX.
- **arXMCP positioning:** Design-pattern lift only. arXMCP already vendors HTMX; replacing it with Datastar would require re-implementing all existing `hx-*` attributes and is premature. The signal-driven SSE pattern should be studied now and filed as a future upgrade option if the HTMX SSE approach (candidate 2.3) proves insufficiently reactive. Datastar's Python backend SSE format (which can be implemented natively in sse-starlette) is the borrowable pattern. Under the no-fork policy this is study-only.
- **Risk flags:** MIT permissive. v1.0 shipped April 2026 — the API is considered stable but the ecosystem is young. 4.5k stars is smaller than HTMX (48k), so less community support. The `data-*` attribute namespace conflicts with HTML5 `data-*` custom attributes if not scoped carefully. No GPU dependency.

---

### 2.7 Restic (context: arXMCP's current backup tool)

- **URL:** https://github.com/restic/restic
- **License:** BSD-2-Clause
- **Stars / last commit:** 33.7k stars; v0.18.1 released September 21, 2025 (actively maintained)
- **What it does:** Restic is a content-addressed, encrypted, deduplicated backup tool. It creates snapshots of arbitrary file trees into a "repository" (a directory, S3 bucket, SFTP server, etc.) using content-defined chunking. Each snapshot is incrementally computed — only changed chunks are stored. Repositories can be pruned with `restic forget --keep-daily 7`. Restic is already documented in arXMCP's E14_S05 ops cadence; `make backup` invokes it.
- **Specific capability worth borrowing:** The `restic backup --files-from-verbatim -` pattern (read file list from stdin) allows constructing a precise manifest of the files to snapshot: `var/arxmcp/cache/notebooks.db`, `var/arxmcp/notebooks/`, `var/arxmcp/index/lancedb/`, `var/arxmcp/index/kuzu/` — without snapshotting model caches or OTel trace data. The `restic check --with-cache` integrity verification run (already in the E14_S05 ops drill) adds confidence before a major ingest. The `restic stats` command gives a quick compressed-size report useful in a `make status` target.
- **arXMCP positioning:** Already in use (E14_S05). This entry surfaces new capability to borrow: the `--files-from-verbatim -` stdin manifest pattern and `restic stats` as a `make status` data point. No new dependency — restic is already in the E14 ops runbook.
- **Risk flags:** BSD-2-Clause permissive. v0.18.1 (Sep 2025) is the latest; note that the arXMCP restic backup cadence (E14_S05) uses a daily cron-triggered `make backup` — there is no automatic trigger when `notebooks.db` changes. The LanceDB segment files are binary and large; restic's CDC chunks them efficiently but the first snapshot will be slow.

---

### 2.8 Docker Compose `depends_on: condition: service_healthy` pattern

- **URL:** https://docs.docker.com/compose/how-tos/startup-order/
- **License:** Docker, Inc. documentation (Apache-2.0 for the Compose spec)
- **Stars / last commit:** N/A (specification + tooling, not a repo project)
- **What it does:** Docker Compose v2 `depends_on` with `condition: service_healthy` blocks a dependent container from starting until the dependency's `healthcheck` returns healthy. Combined with `start_period`, `interval`, and `retries`, this implements a proper startup gate: `ingest` service waits for `arxmcp-server` to report `/readyz` healthy before running delta ingest. The `compose watch` command (GA in Compose v2, enhanced with `initial_sync` in September 2025) syncs host file changes into running containers without rebuilds — relevant for the Jinja2 template development loop.
- **Specific capability worth borrowing:** The `depends_on: condition: service_healthy` gate applied to the base `docker-compose.yml` service graph: the `ingest` service (when it runs as a compose service) should wait for the `arxmcp-server`'s `/readyz` to return 200 before attempting delta ingest. This prevents the common failure mode where the ingest process starts writing to LanceDB while the MCP server's BGE-M3 worker is still loading the model. The existing `HEALTHCHECK` in `docker/Dockerfile.server` (which already targets `/readyz` via curl) is directly composable with this pattern.
- **arXMCP positioning:** Design-pattern lift. The gate lands in the base `docker-compose.yml` (not yet written). The `docker/Dockerfile.server` healthcheck already covers the slow BGE-M3 load with `start_period: 5m` — the compose gate reuses that same readiness signal without any server changes. The Phoenix sidecar (`infra/observability/phoenix-compose.yml`) already demonstrates the project's compose conventions (loopback binding, SHA digest pins, `cap_drop: ["ALL"]`, `restart: "no"`) — the base stack should follow the same template.
- **Risk flags:** No abandonware risk (Compose is Docker's maintained tool). The `service_healthy` condition requires that the dependency service define a `healthcheck` — `arxmcp-server` does (via `docker/Dockerfile.server`), but any new sidecar (Litestream, Gatus) must also define healthchecks for the gate to work transitively. The `compose watch` feature requires Compose v2.22+.

---

### 2.9 Alpine.js

- **URL:** https://github.com/alpinejs/alpine
- **License:** MIT
- **Stars / last commit:** 31.6k stars; actively maintained (2,365 commits)
- **What it does:** Alpine.js is a ~15 kB "reactive markup" framework: `x-data`, `x-show`, `x-bind`, `x-on`, `x-model` attributes provide component-scoped reactive state directly in HTML templates with no build step. It is complementary to HTMX: HTMX owns server-round-trip DOM updates; Alpine owns client-only transient state (modal open/closed, dropdown visibility, inline form validation). The `x-data="{ open: false }"` + `x-show="open"` pattern implements a collapsible paper-list section without any server round-trip. The `Persist` plugin (`x-persist`) saves Alpine state to localStorage across page reloads.
- **Specific capability worth borrowing:** The `x-data` component model for the drag-drop upload card in `frontend/templates/notebook_detail.html`: an Alpine component handles the `dragover` / `drop` event, updates a local `x-data` state to show a drop-zone highlight, and then delegates the actual `fetch` POST to either vanilla JS or `hx-post`. This is a direct improvement over the current template structure where Alpine-appropriate client state (hover highlight, file name preview before upload) would otherwise require either a round-trip or inline `onclick` scripts that violate the template's Content Security Policy.
- **arXMCP positioning:** Design-pattern lift. Alpine.js would be a second vendored static asset at `frontend/static/alpine.min.js` (15 kB). No build chain, no npm. The `x-data` + `x-on:dragover.prevent` + `x-on:drop.prevent` pattern for the upload card is the specific borrowable pattern. Existing HTMX attributes continue to own server interaction; Alpine owns the drag-drop visual state. The `CONTENT_SECURITY_POLICY_PREVIEW` in `server/middleware.py` needs to add `nonce` or verify the Alpine JS inline expression model is compatible with the project's CSP `script-src` directive.
- **Risk flags:** MIT permissive. The Alpine `x-` attribute namespace is distinct from HTMX `hx-` and Datastar `data-` namespaces — no collision. The CSP interaction with Alpine's inline expression evaluator (Alpine uses `new Function()` internally) requires `script-src: 'unsafe-eval'` unless using Alpine's CSP build (`@alpinejs/csp`). The CSP build drops expression-syntax but supports standard `x-bind` attribute mode — the project should use the CSP build.

---

## 3. Sources reviewed

| Project | URL | Stars | Last commit / release | High-signal |
|---|---|---|---|---|
| Litestream | https://github.com/benbjohnson/litestream | 13.6k | v0.5.11 — Apr 2026 | Yes |
| Kopia | https://github.com/kopia/kopia | 13.3k | v0.23.0 — May 2026 | Yes |
| Restic | https://github.com/restic/restic | 33.7k | v0.18.1 — Sep 2025 | Yes (in use) |
| MinIO | https://github.com/minio/minio | ~50k | Active 2025 | No — AGPL-3.0; Docker Hub images dropped Oct 2025 |
| Garage | https://github.com/deuxfleurs-org/garage | 3.9k | Active 2025/2026 | No — AGPL-3.0; study-only under no-fork |
| SeaweedFS | https://github.com/seaweedfs/seaweedfs | ~23k | Active 2025 | No — distributed-first; overkill for single workstation |
| LiteFS | https://github.com/superfly/litefs | 4.8k | v0.5.14 — Apr 2025 | No — FUSE-based cluster replication; no single-node value |
| HTMX | https://github.com/bigskysoftware/htmx | 48.1k | Active 2026 | Yes (already vendored) |
| sse-starlette | https://github.com/sysid/sse-starlette | 832 | v3.4.4 — May 2026 | Yes |
| Alpine.js | https://github.com/alpinejs/alpine | 31.6k | Active 2026 | Yes |
| Datastar | https://github.com/starfederation/datastar | 4.5k | v1.0.1 — Apr 2026 | Yes (future) |
| Gatus | https://github.com/TwiN/gatus | 11.1k | v5.34.0 active | Yes |
| Uptime Kuma | https://github.com/louislam/uptime-kuma | ~84k | Active 2025/2026 | No — SQLite-stored config not version-controllable |
| Docker Compose docs | https://docs.docker.com/compose/ | N/A | GA 2025 | Yes (pattern) |
| mcp-doctor | https://github.com/destilabs/mcp-doctor | 14 | Recent 2025 | No — too few stars, narrow scope |
| phoenix-compose.yml (existing) | infra/observability/phoenix-compose.yml | N/A | E14_S03 shipped | Yes (template) |

---

## 4. Themes

**Theme 1 — SQLite durability via streaming sidecar, not object store.** A full S3-compatible object store (MinIO, Garage, SeaweedFS) is license-problematic (AGPL-3.0) and massively over-engineered for a single-workstation notebook database. Litestream's WAL-streaming sidecar pattern gives 95% of the durability benefit (point-in-time recovery, continuous replication to a local replica path) at near-zero operational overhead. arXMCP's `var/arxmcp/cache/notebooks.db` is exactly the workload Litestream was designed for.

**Theme 2 — HTMX + sse-starlette = ingest progress with no stack additions.** arXMCP has already committed to the HTMX + Jinja2 + FastAPI pattern. The HTMX 2.x `server-sent-events` extension + sse-starlette's `EventSourceResponse` fills the main UX gap (ingest progress visibility) without touching the existing architecture. Every other "richer UI" approach (Svelte sidecar, React SPA) violates the no-build-chain constraint or introduces a second port.

**Theme 3 — Config-as-code health surfaces are zero-cost operability.** Gatus and the Docker Compose `depends_on: condition: service_healthy` pattern both provide operator-visible health status with no changes to the MCP server source. The project's existing `/healthz` + `/readyz` discipline (CLAUDE.md §6, `server/health.py`) already provides the signals; the gap is that no UI or compose gate consumes them. A single `infra/gatus.yml` + one service in `docker-compose.yml` closes the gap.

**Theme 4 — The base docker-compose.yml is the structural blocker.** Phoenix, Gatus, Litestream, and the `depends_on: service_healthy` pattern all converge on a single missing artifact: the base `docker-compose.yml` deferred since E06 (`infra/README.md`). Each sidecar requires either a shared named volume or a `depends_on` reference to the `arxmcp-server` service — relationships that cannot be expressed in separate compose files without overrides. The phoenix-compose.yml convention (loopback binding, SHA pins, `cap_drop`, `restart: "no"`, `init: true`) is already the project's compose template; it just needs to be instantiated as the base stack.

---

## 5. Out of scope / parking lot

| Project | Rejection reason |
|---|---|
| **MinIO** | AGPL-3.0 — study-only under arXMCP's no-fork policy; additionally Docker Hub images dropped October 2025 (self-build required), adding operational friction for a local-first tool. Object-store semantics are over-engineered for a SQLite + filesystem notebook store. |
| **Garage (Deuxfleurs)** | AGPL-3.0 — study-only. Primarily designed for geo-distributed multi-node deployments; single-node `--single-node` flag is a development convenience, not the primary design target. Would require S3 SDK calls to replace simple filesystem writes in `tools/_notebook_common.py`. |
| **SeaweedFS** | Apache-2.0 but distributed-first: master + volume + filer + S3 gateway = 4 cooperating processes even in single-node mode. Overkill for a single-workstation notebook data store. |
| **LiteFS (superfly)** | FUSE-based cluster SQLite replication. Requires FUSE kernel module (not available in macOS production containers without special entitlements). Designed for multi-replica Fly.io deployments, not single-workstation backup. Litestream solves the same problem with zero kernel deps. |
| **Uptime Kuma** | 84k stars, permissive license, but its entire configuration lives in a SQLite database (not YAML/config files) — no version control of monitor definitions. Gatus's config-as-code YAML discipline is a better fit for the project's convention of version-controlling all infra config in the repo. |
| **mcp-doctor (destilabs)** | 14 stars — below the 50-star floor. The project is also TypeScript-only and checks tool schema compliance, not operational readiness; orthogonal to the health-surface gap. |
| **FastUI (Reflex / Nicegui / htpy)** | Each requires either a Node.js build chain or a Python-first UI compiler that adds a significant dep tree. arXMCP's Jinja2 templates plus HTMX are sufficient for the notebook management surface; the added complexity is not warranted for an internal-only developer tool. |
| **Datastar as HTMX replacement** | MIT, active, interesting signal-driven SSE model. Not worth displacing the already-vendored HTMX until there is a concrete UX pain point the HTMX SSE extension cannot solve. Filed as a future upgrade path (candidate 2.6 above). |
| **FastAPI + WebSocket (not SSE)** | WebSocket connections survive server restarts less gracefully than SSE reconnects and require a stateful connection manager in the server. SSE reconnects automatically on disconnect with `Last-Event-ID` — better fit for long-running ingest progress reporting. |
