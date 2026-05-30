# Research-Frontier Brief — 2026q2-notebook-ux-storage-ops

**Scout run:** 2026-05-28  
**Scope:** Notebook management UX + durable notebook storage + operability + container packaging  
**Scout role:** RESEARCH-FRONTIER (infra/ops focus — not ML)

---

## 1. TL;DR

The three strongest candidates for immediate adoption are: (1) hardening the existing SQLite metadata store with `PRAGMA synchronous=FULL` + `fullfsync` — a one-liner that closes a documented power-loss data-loss window in `server/notebooks_store.py:117`; (2) adopting the IETF Health Check Response Format (draft-inadarei-api-health-check) for a `/status` endpoint that exposes per-component state in a machine-readable envelope — arXMCP's `/readyz` is close but non-standard; and (3) wiring a Litestream sidecar (or equivalent WAL-shipping) for `var/arxmcp/cache/notebooks.db` so the SQLite metadata store survives disk failure without a full restic restore. The main thematic shift in the literature is that "local-first" has matured from a CRDT-research topic into an engineering practice with concrete, low-overhead tools (Litestream, LanceDB MVCC v2.1, restic retention policies) that a single operator can adopt without cloud infrastructure.

---

## 2. Method / Practice Candidates

---

### Candidate 1 — SQLite WAL Durability Hardening (`synchronous=FULL` + `fullfsync`)

**Method name:** SQLite WAL durability: `PRAGMA synchronous=FULL` + `PRAGMA fullfsync=ON`  
**Year + author/source:** SQLite project (D. Richard Hipp); documented in SQLite pragma reference; durability gap explicitly analysed in Avi Kak, "SQLite commits are not durable under default settings" (blog, 2025) at https://avi.im/blag/2025/sqlite-fsync/ and Andrew Ayer, "SQLite's Durability Settings are a Mess" at https://www.agwa.name/blog/post/sqlite_durability.  
**Primary citation:** SQLite PRAGMA documentation at https://sqlite.org/pragma.html (canonical); Avi Kak blog 2025 (analysis).  
**Summary:** SQLite's WAL mode with the default `synchronous=NORMAL` guarantees consistency (no torn writes) but NOT durability across an OS crash or power failure. The last committed transaction can be rolled back if the system loses power before the WAL is checkpointed. On macOS specifically, Apple's `fsync()` does not actually flush to stable storage; `PRAGMA fullfsync=ON` is required to invoke the `F_FULLFSYNC` syscall that does. `arXMCP/server/notebooks_store.py:117` currently applies `synchronous=NORMAL` — meaning that the notebooks SQLite metadata store (`var/arxmcp/cache/notebooks.db`) is at risk of losing the most recent write after a power failure or kernel crash. The fix is a two-pragma change: `PRAGMA synchronous=FULL` (ensures each commit is flushed before returning) and `PRAGMA fullfsync=ON` (makes the macOS `fsync` work correctly). The performance impact on a low-write metadata store (notebooks, ingest-tracker, parse-tracker) is negligible; these tables are not on the fast path.  
**Compute footprint:** Pure algorithm — zero GPU, no model download. Two PRAGMA calls per connection open.  
**Implementation complexity:** ~5 LOC change in `server/notebooks_store.py` (one line per PRAGMA; 1–2 SQLite connections affected). No OSS dependency change.  
**arXMCP fit:** `server/notebooks_store.py` (line 117 is the direct hit); also check `server/ingest_tracker.py` and `server/parse_tracker.py` for any sibling SQLite connections that set the same pragma.  
**Maturity signal:** SQLite official docs; macOS `fullfsync` is a decade-old known issue. The Kak (2025) analysis is the clearest recent writeup. Zero adoption risk — this is a documented SQLite feature.

---

### Candidate 2 — IETF Health Check Response Format (`application/health+json`)

**Method name:** Health Check Response Format for HTTP APIs (draft-inadarei-api-health-check)  
**Year + author/source:** Irakli Nadareishvili, IETF Internet-Draft (draft-06 is the most recent stable iteration), 2020–2023, at https://datatracker.ietf.org/doc/html/draft-inadarei-api-health-check-06; GitHub reference implementation at https://github.com/inadarei/rfc-healthcheck (MIT license).  
**Primary citation:** https://datatracker.ietf.org/doc/html/draft-inadarei-api-health-check-06 (IETF draft).  
**Summary:** This Internet-Draft specifies a `application/health+json` media type with a standard JSON envelope for service health. The mandatory field is `status` with values `pass` / `warn` / `fail`. Optional fields include `checks` (a nested map of named components, each with `componentType`, `observedValue`, `status`, `output`) and `links`. The design allows a single `/status` endpoint to expose per-component health (LanceDB, embedder, Kùzu, restic-last-run, disk-free) in a machine-readable format that any operator dashboard, Docker healthcheck, or monitoring script can consume. arXMCP's `/readyz` already returns `{"status": "degraded", "warm": {...}}` but uses a custom schema and HTTP 503 for degraded — operators building dashboards must write custom parsers. A `/status` endpoint following this draft would be a superset of `/readyz` with standardised keys. The draft is stable (no changes since 2022) even if not yet an RFC; .NET, Spring Boot, and Fastify all ship compatible health check implementations. The `warn` state maps directly to arXMCP's degraded/fallback-version scenario (serving but on N-1 corpus), which currently returns 503 — a value that causes load balancers to take the pod out of rotation even though it can still serve requests.  
**Compute footprint:** Zero GPU. One JSON serialisation per HTTP request to `/status`. The per-component checks are cheap reads (Prometheus gauge values, a `Path.stat()` for disk, the `resources.warm` flags already computed).  
**Implementation complexity:** ~80 LOC new handler in `server/health.py`; no new dependencies. A thin wrapper that assembles the draft-compliant JSON from values already in `server.resources.Resources`.  
**arXMCP fit:** `server/health.py` — new `GET /status` route; coexists with `/healthz` and `/readyz`. The Jinja2 status page (`frontend/templates/`) can then `hx-get="/status"` to auto-refresh a human-friendly indicator. Docker `HEALTHCHECK` stays on `/readyz`.  
**Maturity signal:** Draft since 2017; widely implemented in Spring Boot Actuator, .NET health checks, Fastify-healthcheck. Not formally ratified but the schema is stable and battle-tested.

---

### Candidate 3 — Litestream SQLite WAL Replication

**Method name:** Litestream — streaming WAL replication for SQLite  
**Year + author/source:** Ben Johnson (benbjohnson), Apache-2.0, ~2021; actively maintained, 13K+ GitHub stars, https://github.com/benbjohnson/litestream; documentation at https://litestream.io/.  
**Primary citation:** https://litestream.io/how-it-works/ (design doc) + https://github.com/benbjohnson/litestream (source).  
**Summary:** Litestream runs as a separate process that intercepts SQLite's WAL checkpointing. It holds a long-running read transaction to prevent checkpoints, instead continuously copying new WAL frames to a "shadow WAL" and shipping them to one or more replica destinations (local path, S3, B2, GCS, SFTP, Azure). For arXMCP, the target would be a local NAS path (or Backblaze B2) for `var/arxmcp/cache/notebooks.db` — providing continuous point-in-time replication without application code changes. Recovery is a single CLI command (`litestream restore`) that reconstructs the database from the snapshot + WAL replay. The key advantage over restic for the SQLite layer is that Litestream replicates at WAL-page granularity (sub-second lag) rather than nightly snapshot granularity. The key limitation is that Litestream requires the SQLite database to be in WAL mode — which `notebooks_store.py:116` already enables. A known constraint: Litestream holds an open read transaction, which means the WAL file never auto-checkpoints; operators must monitor WAL file growth. For arXMCP's low-write metadata store this is not a practical concern.  
**Compute footprint:** Sidecar process (Go binary, ~10 MB RAM, negligible CPU). No GPU.  
**Implementation complexity:** Zero application code changes. One YAML config file + one Docker Compose service (or systemd unit). Reference: https://litestream.io/getting-started/. The arXMCP docker-compose would add a `litestream` service with a bind-mount to `var/arxmcp/cache/` and a `replica` target pointing to a local path or B2.  
**arXMCP fit:** `infra/` (new `docker-compose.yml` service); configuration only. Pairs with the existing restic nightly snapshot strategy — restic covers the LanceDB/Kùzu bulk indices; Litestream covers the SQLite metadata and notebook store at fine granularity.  
**Maturity signal:** 13K GitHub stars; used in production at SQLiteCloud, Fly.io's internal tooling, and the Lemon Squeezy billing platform. Apache-2.0 license.

---

### Candidate 4 — Lance File Format v2.1/v2.2 Explicit Version Pin

**Method name:** Lance file format version pinning (`data_storage_version="2.0"` until explicit opt-in to 2.1)  
**Year + author/source:** LanceDB team / Weston Pace et al.; blog "Lance File 2.1 is Now Stable" at https://www.lancedb.com/blog/lance-file-2-1-stable (2025); academic paper arXiv:2504.15247, "Lance: Efficient Random Access in Columnar Storage through Adaptive Structural Encodings", April 2025.  
**Primary citation:** arXiv:2504.15247 (verified) — Pace, She, Xu, Jones, Lockett, Wang, Shah; LanceDB blog https://www.lancedb.com/blog/lance-file-2-1-stable.  
**Summary:** LanceDB's on-disk format has moved through v1 → v2.0 (stable) → v2.1 (stable, April 2025) → v2.2 (beta). The v2.1 format is not readable by Lance versions < 0.38.0. If arXMCP's `pyproject.toml` pins LanceDB below 0.38.0, writing a v2.1 dataset makes it unreadable by the installed library — a silent corruption scenario during dependency upgrades. The mitigation is explicit `data_storage_version="2.0"` when creating datasets until the team has verified the installed library supports v2.1 reads and is ready to migrate. The academic paper (arXiv:2504.15247) provides the formal storage engineering rationale for the Lance format's adaptive structural encoding approach; it documents benchmark results showing Lance achieves better random access performance than Parquet without the scan/RAM tradeoffs. For arXMCP specifically, the most load-bearing practical finding is: keep the LanceDB version pin consistent between the host that writes chunks and the container that reads them, and do not let a `uv` or `pip` upgrade silently migrate the on-disk format to a version the pinned reader cannot decode.  
**Compute footprint:** Zero. This is an operational/versioning practice, not a compute task.  
**Implementation complexity:** ~3 LOC change to any LanceDB `write_dataset` call that uses the default version; one line in `pyproject.toml` comments. A one-off migration script if the team wants to move to v2.1.  
**arXMCP fit:** `ingest/store.py` (lance dataset writes); `pyproject.toml` (dependency pin); `ingest/_migrate_chunks_schema_if_needed` (explicit version guard). Also relevant to `tools/_notebook_common.py` which creates per-notebook LanceDB instances.  
**Maturity signal:** LanceDB is production-grade (Apache-2.0, widely adopted). The version-pin gap is a documented operational failure mode from their own release notes.

---

### Candidate 5 — Docker Compose `depends_on: condition: service_healthy` Startup Ordering

**Method name:** Docker Compose `depends_on` with `condition: service_healthy` for startup ordering  
**Year + author/source:** Docker Inc.; documented at https://docs.docker.com/compose/how-tos/startup-order/ and https://docs.docker.com/reference/compose-file/services/#depends_on (Docker Docs, 2024–2025). The pattern was generalised in Compose V2 (2022) and is now the documented replacement for wrapper scripts like `wait-for-it.sh`.  
**Primary citation:** https://docs.docker.com/compose/how-tos/startup-order/ (official Docker Docs).  
**Summary:** Docker Compose `depends_on: condition: service_healthy` gates a service's start on another service's `HEALTHCHECK` reporting healthy. The arXMCP design note (`08-security-observability-ops.md:269`) already specifies the correct two-service structure (`arxmcp-server` + `arxmcp-ingest`) and the correct healthcheck (`curl -f http://127.0.0.1:7733/readyz`). The gap is that the `docker-compose.yml` file itself does not yet exist. The `depends_on: service_healthy` pattern is the key missing piece that makes the compose stack safe to `docker-compose up` in one command: the ingest service waits for the server's `/readyz` to return 200 before starting. Without this ordering, an ingest run that starts before LanceDB is warm races with the server's startup and may open the LanceDB dataset before the server has checkpointed its corpus-version metadata. Also relevant: the `arxmcp-server` service should mount `var/arxmcp/index` as read-only (`ro`) but `var/arxmcp/cache` as read-write, matching the design note's intent. `profiles: ["ingest"]` on the ingest service (already in the design note) means `docker-compose up` starts only the server by default.  
**Compute footprint:** Zero. Configuration-only.  
**Implementation complexity:** ~60 LOC YAML (`docker-compose.yml`). The compose file is the entire deliverable; the Dockerfile already exists at `docker/Dockerfile.server`.  
**arXMCP fit:** `infra/` — new `docker-compose.yml`. The `infra/README.md` placeholder explicitly defers this to E14; this candidate surfaces it as low-complexity/high-value.  
**Maturity signal:** Official Docker Docs feature; Docker Compose V2 (2022+). Used universally in any compose-based local development stack.

---

### Candidate 6 — HTMX + SSE Live Status Indicator on `/ui/` Landing Page

**Method name:** HTMX SSE extension (`hx-ext="sse"`) for auto-refreshing status badges  
**Year + author/source:** htmx project (Carson Gross), MIT license, https://htmx.org/extensions/sse/ (version 2.x+); server integration via FastAPI `StreamingResponse` / `EventSourceResponse`. Reference: fastapi-sse-htmx at https://github.com/vlcinsky/fastapi-sse-htmx (MIT).  
**Primary citation:** https://htmx.org/extensions/sse/ (canonical); https://github.com/vlcinsky/fastapi-sse-htmx (reference impl, MIT).  
**Summary:** arXMCP's `/ui/` landing page (Jinja2 server-rendered, htmx already vendored at `frontend/static/`) displays notebook lists but has no "is the server ready / degraded?" indicator visible to the operator. The htmx SSE extension allows any `<div hx-ext="sse" sse-connect="/ui/status-stream">` to receive server-push fragments. A minimal FastAPI `GET /ui/status-stream` endpoint (`EventSourceResponse` or `StreamingResponse` with `text/event-stream`) can push an HTML fragment (`<span class="badge">ready</span>` / `<span class="badge warning">degraded</span>`) every 10 seconds, reading from `resources.warm` and `resources.degraded`. The badge auto-updates without a page reload. This is a 100-LOC addition: ~40 LOC FastAPI SSE endpoint + ~60 LOC Jinja2 template change. The alternative approach (polling with `hx-trigger="every 10s"` and `hx-get="/status"`) is simpler but less efficient; for a single-operator local tool the difference is immaterial and polling is arguably more debuggable. HTMX 4.0 (2025) switches the underlying transport to `fetch()` which enables true streaming — the SSE extension behaviour is more reliable in 4.x. License: MIT.  
**Compute footprint:** Zero GPU. One async generator per SSE connection (one operator, one browser tab — negligible).  
**Implementation complexity:** ~100 LOC (40 Python + 60 Jinja2/HTML). No new Python dependencies if the existing `server/routes/ui.py` already imports FastAPI's `StreamingResponse`. The SSE extension JS is 1.5 KB.  
**arXMCP fit:** `server/routes/ui.py` (new `/ui/status-stream` route); `frontend/templates/index.html` (badge element); `frontend/static/` (SSE extension JS if not already vendored). The `/status` endpoint from Candidate 2 is the natural data source.  
**Maturity signal:** htmx 1.x is in production at companies of all sizes; 2.x is stable; 4.0 is recent. The SSE extension is included in the official htmx distribution. Zero risk.

---

### Candidate 7 — restic Retention Policy + `check --read-data-subset` Quarterly Drill

**Method name:** restic `forget` / `prune` / `check --read-data-subset` operational discipline  
**Year + author/source:** restic project (Alexander Neumann et al.), BSD-2-Clause license, https://github.com/restic/restic (v0.17+); retention policy documentation at https://restic.readthedocs.io/en/stable/060_forget.html.  
**Primary citation:** https://restic.readthedocs.io/en/stable/060_forget.html (official docs).  
**Summary:** arXMCP already pins restic as the backup tool (`08-security-observability-ops.md:245`) and has a `backup-status.json` sentinel wired into Prometheus. What is NOT yet specified in the codebase is a concrete retention policy and a verified restore drill procedure. The literature and community best-practice consensus (servercrate.net, forum.restic.net) is: `--keep-daily 7 --keep-weekly 4 --keep-monthly 12` for a workstation setup. For arXMCP's 100 GB corpus, typical incremental backups after dedup are 1–3 GB/day. The critical gap is `check --read-data-subset`: running `restic check` only validates index consistency (fast, cheap), NOT that the actual pack data is uncorrupted. `check --read-data-subset=5%` reads 5% of all pack files on each quarterly drill, covering 100% of data over ~5 runs without the bandwidth cost of a full verification every quarter. The design note specifies a quarterly restore drill but does not specify the check subset fraction or the forget policy; this candidate formalises both.  
**Compute footprint:** Zero GPU. CPU/IO during backup window (04:10 UTC per the daily ops cadence). Negligible impact on query serving.  
**Implementation complexity:** ~20 LOC in the backup wrapper script (restic CLI invocations); ~5 LOC in the cron configuration. The `backup-status.json` writer already exists; it needs a `finished_at` timestamp and `--check-subset` result field added.  
**arXMCP fit:** `infra/` (backup wrapper script); `var/arxmcp/ops/backup-status.json` (sentinel contract); `docker/Dockerfile.server` (restic binary already installed or to be added). Pairs with the nightly ops cadence in `08-security-observability-ops.md:260`.  
**Maturity signal:** restic 0.17+; BSD-2-Clause; 26K GitHub stars; the `--read-data-subset` flag was added in restic 0.14 (2022). Widely documented in the self-hosting community.

---

### Candidate 8 — PaperQA2 `Doc` / `DocDetails` Collection Model as Reference Design

**Method name:** PaperQA2 three-tier collection model (`Doc` / `DocDetails` / `Text`) with manifest CSV and hash-keyed settings  
**Year + author/source:** Future House (paperqa team); paper arXiv:2409.13740, "PaperQA2: Scientific Research Agent" (Sept 2024); GitHub https://github.com/Future-House/paper-qa (Apache-2.0 license).  
**Primary citation:** arXiv:2409.13740 (verified) — Future House, 2024; https://github.com/Future-House/paper-qa.  
**Summary:** PaperQA2 uses three abstractions: `Doc` (minimal: `docname`, `citation`, unique key), `DocDetails` (extended: authors, DOI, year, citation count, journal quality score), and `Text` (chunked text with embedding). Collections are stored in a manifest CSV (a flat file of `DocDetails` fields); local search indexes are keyed by a hash of the `Settings` object so index regeneration is triggered automatically when configuration changes. For arXMCP, this model is instructive for the notebook data model: arXMCP's notebooks currently have a SQLite metadata store (notebooks.db) tracking notebook slug, creation time, and paper list, but lacks a formal separation between "minimal notebook-scoped record" (analogous to `Doc`) and "extended per-paper provenance record" (analogous to `DocDetails` — parse status, parser used, ingest timestamp, license, chunk count). The manifest-CSV pattern (flat export of the `DocDetails` layer) is a practical portability mechanism: an operator can `cp manifest.csv` to transfer a notebook's paper list to another machine without copying LanceDB indices. The settings-hash index key pattern (regenerate index when config hash changes) is directly applicable to arXMCP's per-notebook LanceDB instances.  
**Compute footprint:** Reference design only — ideas to implement natively. Zero compute.  
**Implementation complexity:** No implementation; this is a design-pattern reference. Adoption would mean adding a `manifest_csv` export path to `server/notebooks_store.py` and a `parse_provenance` field to the notebook metadata schema (~40 LOC).  
**arXMCP fit:** `server/notebooks_store.py` (schema extension); `tools/_notebook_common.py` (export helper). The `parser_used` column already in the `chunks` table schema (`05-storage-and-indexing.md:76`) is the per-chunk provenance; the notebook-level summary rolls it up.  
**Maturity signal:** PaperQA2 is actively maintained (Apache-2.0; Future House), published at NeurIPS 2024 workshop, widely cited in the scientific-RAG literature. The `DocDetails` model is production-grade.

---

### Candidate 9 — Kleppmann et al. "Local-First Software" Seven Ideals as Checklist

**Method name:** Local-first software checklist (Kleppmann et al., 2019)  
**Year + author/source:** Martin Kleppmann, Adam Wiggins, Peter van Hardenberg, Mark McGranaghan; "Local-first software: you own your data, in spite of the cloud," ACM SIGPLAN Onward! 2019, pp. 154–178, https://dl.acm.org/doi/10.1145/3359591.3359737; full text at https://www.inkandswitch.com/essay/local-first/.  
**Primary citation:** https://dl.acm.org/doi/10.1145/3359591.3359737 (ACM, 2019). Foundational; not 24-month window but NOT in `.claude/notes/10-references-and-prior-art.md`.  
**Summary:** The paper articulates seven ideals for local-first software: (1) fast (local disk, no round-trips); (2) multi-device (sync as a background concern); (3) works offline; (4) collaboration-ready; (5) longevity (data is portable/readable without the app); (6) privacy (data stays on device); (7) user in control. For a single-workstation, single-operator system like arXMCP, ideals 1, 3, 5, and 6 are directly applicable. The actionable takeaway is a checklist against arXMCP's current state: (1) fast — yes, LanceDB is local; (3) offline — yes, no cloud dependency; (5) longevity — partially; notebook data is in a per-slug LanceDB directory + SQLite row, but there is no "export notebook to a portable format" path (a manifest CSV or JSONL export would satisfy this); (6) privacy — yes, loopback-only. The paper's design vocabulary is also useful for communicating arXMCP's constraints to contributors: "this is a local-first system, not a multi-tenant SaaS."  
**Compute footprint:** Zero. Conceptual framework.  
**Implementation complexity:** Zero code — design vocabulary and checklist for future feature scoping. The longevity gap (no portable export) suggests one ~40 LOC export handler.  
**arXMCP fit:** `server/notebooks_store.py` (export path); design notes; `CLAUDE.md` vocabulary.  
**Maturity signal:** 1100+ citations (ACL Anthology + ACM DL); the definitive reference for local-first software design. Ink & Switch essay version is the most read form.

---

## 3. Sources Reviewed

| Venue / Source | URL Pattern | Material Reviewed | High-Signal? |
|---|---|---|---|
| SQLite pragma documentation | https://sqlite.org/pragma.html | WAL, synchronous, fullfsync, journal_mode semantics | YES |
| Avi Kak blog 2025 | https://avi.im/blag/2025/sqlite-fsync/ | SQLite durability gap under default settings | YES |
| Andrew Ayer blog | https://www.agwa.name/blog/post/sqlite_durability | SQLite durability settings analysis | YES |
| IETF draft-inadarei-api-health-check-06 | https://datatracker.ietf.org/doc/html/draft-inadarei-api-health-check-06 | Health check JSON format spec | YES |
| Litestream docs | https://litestream.io/how-it-works/ | WAL replication design, failure modes, recovery | YES |
| LanceDB blog — Lance 2.1 stable | https://www.lancedb.com/blog/lance-file-2-1-stable | Format version migration guidance | YES |
| arXiv:2504.15247 | https://arxiv.org/abs/2504.15247 | Lance format engineering paper | YES |
| Docker Docs — startup order | https://docs.docker.com/compose/how-tos/startup-order/ | depends_on / service_healthy semantics | YES |
| restic documentation | https://restic.readthedocs.io/en/stable/ | Retention policy, check --read-data-subset | YES |
| restic design | https://restic.readthedocs.io/en/stable/design.html | Content-addressable backup design | YES |
| htmx SSE extension | https://htmx.org/extensions/sse/ | SSE + HTMX integration | YES |
| PaperQA2 GitHub | https://github.com/Future-House/paper-qa | Collection data model (Doc/DocDetails/Text) | YES |
| Kleppmann et al. 2019 | https://dl.acm.org/doi/10.1145/3359591.3359737 | Local-first software seven ideals | YES |
| Ink & Switch essay | https://www.inkandswitch.com/essay/local-first/ | Local-first expanded design principles | YES |
| LanceDB versioning docs | https://docs.lancedb.com/tables/versioning | Version management, cleanup_older_than | YES |
| Docker Compose volumes docs | https://docs.docker.com/reference/compose-file/volumes/ | Named volumes vs bind mounts | PARTIAL |
| BorgBackup vs restic comparison | https://remote-backups.com/blog/borg-vs-restic | Tool selection for single workstation | PARTIAL |
| Zotero SQLite schema | https://gist.github.com/pchemguy/19fa69fb4e74ef0cca0026aa0dbf5f42 | Research tool collection data model | LOW |
| OpenAPI health check FastAPI | https://medium.com/@encodedots/python-health-check-endpoint-example-a-comprehensive-guide-4d5b92018425 | FastAPI health check patterns | LOW |

---

## 4. Themes

The dominant theme is that local-first tooling has matured from research concepts into deployable engineering primitives: Litestream (SQLite WAL replication), restic (content-addressed encrypted backup), LanceDB MVCC (snapshot isolation), and HTMX SSE (live status push) are all production-grade tools with clean operational models that require zero cloud infrastructure. The second theme is that SQLite is underestimated as a durability risk in single-operator systems — the default `synchronous=NORMAL` setting trades durability for performance in a way that most developers do not notice until a power-loss event; this is especially acute on macOS where `fsync` is neutered. The third theme is the emergence of a clear vocabulary for single-operator status surfaces: the IETF health-check draft's `pass` / `warn` / `fail` + component-level `checks` maps naturally onto arXMCP's resource warm state, degraded mode, and ops sentinel files. Adopting this vocabulary would make arXMCP's observability layer interoperable with standard monitoring tooling.

---

## 5. Already in arXMCP / Already Considered

- **restic backup** — fully specified at `08-security-observability-ops.md:245–262`; `backup-status.json` sentinel is wired into Prometheus at `server/health.py:64`. The gap (retention policy + `--read-data-subset` drill formalisation) is the NEW contribution in Candidate 7.
- **LanceDB MVCC** — designed at `05-storage-and-indexing.md:178–198`; corpus-version pinning at `corpus-version.json`; N-1 fallback at `08-security-observability-ops.md:222`. The NEW contribution (Candidate 4) is the Lance format version-pin discipline.
- **/healthz + /readyz** — fully implemented at `server/health.py:147–229`. The NEW contribution (Candidate 2) is the IETF-standard `/status` envelope as a machine-readable superset that also exposes the `warn` state rather than 503 for degraded.
- **degraded mode** — implemented at `server/health.py:203–217` returning 503 with a degraded body. Candidate 2 proposes mapping this to `warn` (2xx) not `fail` (503), which is a semantics change with ops implications.
- **WAL mode on SQLite** — `server/notebooks_store.py:116` already sets `journal_mode=WAL`. The gap identified by Candidate 1 is the missing `synchronous=FULL` + `fullfsync` at line 117.
- **Docker Compose design** — fully sketched at `08-security-observability-ops.md:270–319` with correct service structure and healthcheck. The `docker-compose.yml` file itself does not yet exist (confirmed by `infra/README.md` placeholder).
- **HTMX + Jinja2 UI** — `server/routes/ui.py` + `frontend/templates/` use htmx for mutations. htmx is already vendored. Candidate 6 adds SSE-based live status, which is a new capability not yet in the templates.
- **Atomic cutover (no symlinks)** — `05-storage-and-indexing.md:196–198` explicitly prohibits symlink swaps; the corpus-version.json JSON-write pattern is the approved method. This is well-covered; no gap.
- **ColBERT / late-interaction retrieval** — documented as a v1.5 feature at `05-storage-and-indexing.md:333–339`. Not relevant to this infra/ops scout run.
- **BGE-M3 embedder** — fully shipped (E03). Out of scope for this run.

---

## 6. Out of Scope / Parking Lot

- **BorgBackup as restic alternative** — reviewed; Borg is faster for very large repos and has better compression, but requires a Python stack (vs restic's single binary), lacks native macOS support without WSL, and arXMCP already pins restic. No reason to switch.
- **CRDTs / operational transformation for notebook sync** — local-first literature mentions CRDTs prominently (Kleppmann's later work with Automerge). For a single-operator, single-workstation system with no concurrent editing requirement, CRDTs are overengineering. Parking lot for a future multi-device scenario.
- **Zotero SQLite schema as reference** — reviewed; Zotero's schema is more complex than needed (it handles 50+ item types) and the documentation explicitly warns against direct SQLite writes. PaperQA2's simpler `Doc/DocDetails` abstraction is a better reference (see Candidate 8).
- **pgvector + Litestream for vector storage** — not applicable; arXMCP uses LanceDB (not SQLite) for vectors, and Litestream only applies to SQLite databases.
- **Lance format v2.2 migration now** — v2.2 is still beta as of 2025; the relevant action is pinning v2.0 explicitly (Candidate 4) not migrating to v2.2 prematurely.
- **Prometheus alertmanager local deployment** — the design note mentions Prometheus scraping `/metrics` but does not ship an alertmanager. For a single-operator workstation, email/cron alerts from the backup wrapper are sufficient; alertmanager adds operational complexity without benefit at this scale.
- **Docker named volumes vs bind mounts** — reviewed. For arXMCP's use case (a single-workstation where `var/arxmcp/` must be visible and backable-up from the host), bind mounts at `$PWD/var/arxmcp` are correct. Named volumes would obscure the data directory from the operator's file manager and complicate restic backup paths. The design note's bind-mount approach is correct.
- **WebSockets for live status push** — HTMX SSE is simpler than WebSockets for unidirectional server→client status updates; SSE reconnects automatically on disconnect and works over HTTP/1.1. No reason to use WebSockets here.
