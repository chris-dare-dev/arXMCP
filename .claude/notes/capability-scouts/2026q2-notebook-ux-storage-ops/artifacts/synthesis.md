# Synthesis — capability-scout 2026q2-notebook-ux-storage-ops

**Theme:** Notebook management UX · durable/portable local-first storage · operability ("is it running") · container packaging
**Briefs synthesized:** comparative, research-frontier, oss-trends, multi-agent, adversary (5/5, standard mode)
**Generated:** 2026-05-28

## 1. Executive summary

18 candidates, overwhelmingly in **Ops / infra** with a secondary cluster in **MCP tool surface / Agent harness**. The dominant theme — flagged by ALL FIVE scouts independently — is that **the base `docker-compose.yml` is the structural unblocker**: it has been deferred since E06, `infra/README.md` admits it, and every other infra improvement (storage sidecars, a status dashboard, healthcheck-gated startup) hangs off it. The second strongest signal (4 sources) is **notebook-storage durability**: notebook data + `notebooks.db` are excluded from the E14 restic scope, and `notebooks.db` ships with `synchronous=NORMAL` (a real macOS power-loss data-loss window). The third (4 sources) is a **human-friendly operability surface** — the machine endpoints (`/healthz`/`/readyz`/`/metrics`) exist but nothing operator-facing consumes them. A recurring meta-finding: the **design constitution is stale** — it still claims "no frontend exists, by design" while a Jinja2+htmx notebook UI shipped across the proof-verify/textbook-ingest streams; the E13 security audit never reviewed that UI. **Top tension:** named Docker volumes vs host bind-mounts for `var/arxmcp/` (comparative favored named volumes for lifecycle; research-frontier favored bind-mounts for host-visible restic backup) — resolved below.

## 2. Triangulation strength

- **5-brief (strongest):** CAND-1 (base docker-compose).
- **4-brief:** CAND-5 (/status surface — incl. its UI/CLI consumers), CAND-8 (SSE ingest progress).
- **3-brief:** CAND-2/3/4 (storage-durability cluster), CAND-6 (make status + UI badge), CAND-14 (notebook UI CRUD/status).
- **2-brief:** CAND-7 (Dockerfile HEALTHCHECK), CAND-9 (notebook export), CAND-10 (MCP resources), CAND-13 (refresh constitution).
- **1-brief (flag for challenger scrutiny):** CAND-11 (SYSTEM_PROMPT/instructions), CAND-12 (notebook-mgmt MCP tools), CAND-15 (textbook BM25), CAND-16 (Lance format pin), CAND-17 (Claude Code operability contract), CAND-18 (restic retention drill).

## 3. Candidate catalog

### CAND-1 — Ship the base `docker-compose.yml` (server [+ ingest] + named/bind volumes + healthcheck-gated startup)

**Category:** Ops / infra
**Size:** M
**Evidence triangulation:** 5 briefs (comparative ✓, research-frontier ✓, oss-trends ✓, multi-agent ✓, adversary ✓)

**What it is:** A base compose stack wiring the existing `docker/Dockerfile.server` as an `arxmcp-server` service (host-side `127.0.0.1:7733`), a volume for `var/arxmcp/`, a profile-gated `arxmcp-ingest` service, and `depends_on: condition: service_healthy` startup ordering. Optionally extends the shipped `infra/observability/phoenix-compose.yml` via profiles.

**Why it matters:** Gives the operator one `docker compose up` with durable data + correct BGE-M3-warm-before-ingest sequencing; it is the prerequisite for every storage-sidecar and status-dashboard candidate below. The downstream pipeline benefits indirectly (reproducible, corpus-version-pinned boot).

**Sources:** adversary H1 (highest-severity gap); comparative C4; research-frontier C5; oss-trends theme-4 + 2.8; multi-agent C4.

**Closest arXMCP analog:** `infra/observability/phoenix-compose.yml` (the only shipped compose — the template to mirror: loopback bind, `@sha256:` image pins, `cap_drop:[ALL]`, `restart`, `init`); `infra/README.md` placeholder; `08-security-observability-ops.md` already sketches the two-service YAML.

**Sketch:** Instantiate `infra/docker-compose.yml` following the Phoenix template. Reconcile `server/config.py::reject_non_loopback` with the container pattern (host `127.0.0.1:7733:7733`, in-container bind via an `ARXMCP_IN_CONTAINER` carve-out — adversary H1 notes the exact mechanism). Decide volume strategy (see tension §4). Healthcheck reuses `/readyz` with `start_period≈90s` for BGE-M3 cold load.

**Open questions:** named volume vs bind mount (§4 tension); does the ingest service need its own image (CAND-7b / adversary L3)?

---

### CAND-5 — Add a `/status` JSON endpoint (IETF `application/health+json` superset of `/readyz`)

**Category:** Ops / infra
**Size:** S
**Evidence triangulation:** 4 briefs (comparative ✓, research-frontier ✓, oss-trends ✓ via Gatus, adversary ✓)

**What it is:** A `GET /status` returning a machine- AND human-renderable JSON envelope (`status: pass|warn|fail`, per-component `checks` for embedder/LanceDB/Kùzu/disk/last-backup, plus `corpus_version`, notebook count, uptime). Superset of `/readyz`; maps "degraded/N-1 corpus" to `warn` (2xx) rather than 503.

**Why it matters:** The single poll target that the UI badge (CAND-6), `make status` (CAND-6), Gatus (via CAND-1), and a Docker healthcheck can all consume — closes the "operator can't tell if retrieval is warm" gap with standard tooling.

**Sources:** comparative C2; research-frontier C2 (IETF draft-inadarei-api-health-check); oss-trends 2.5 (Gatus consumes it); adversary M2.

**Closest arXMCP analog:** `server/health.py` (`/healthz`/`/readyz` return HTTP status only, no rich body); `server/metrics.py` (Prometheus, not human JSON).

**Sketch:** ~80-LOC handler in `server/health.py` assembling the envelope from `server.resources.Resources` warm flags + `corpus_version` + `NotebooksStore.list_notebooks()` count + a `Path.stat()` disk check. Pure-ASGI. The `warn`-not-503 semantics change has ops implications — keep `/readyz` as-is for the k8s/Docker probe; `/status` is the richer surface.

**Open questions:** does flipping degraded→`warn`(2xx) on `/status` (while `/readyz` stays 503) confuse operators? Keep them distinct.

---

### CAND-8 — SSE-based ingest progress (htmx SSE + `sse-starlette`) [partially shipped]

**Category:** Agent harness / Ops (UI)
**Size:** S
**Evidence triangulation:** 4 briefs (comparative ✓, research-frontier ✓, oss-trends ✓, multi-agent ✓)

**What it is:** Replace/augment the current 2s-poll ingest-status loop with a server-push SSE stream so the notebook UI shows live per-paper parse/embed progress, and (multi-agent angle) optionally emit MCP `notifications/message`/`progress` for an agent-facing ingest feed.

**Why it matters:** Upload is fast but parse+embed is 30–90s/paper; the operator (and a corpus-curating agent) needs progress without a full-page reload. NOTE: arXMCP ALREADY ships htmx polling with an HTTP-286 stop-signal (adversary "done well") — so this is an *upgrade*, not net-new.

**Sources:** comparative C1 (async task endpoint) + C9 (per-paper status column); research-frontier C6 (htmx SSE); oss-trends 2.3 (htmx SSE ext) + 2.4 (`sse-starlette`); multi-agent C2 (MCP logging/progress).

**Closest arXMCP analog:** `server/ingest_tracker.py` + `server/parse_tracker.py` (DB-tracked state already exists); the htmx 286-poll in `server/routes/notebooks.py` (works today).

**Sketch:** Add `sse-starlette` (BSD-3, pure-ASGI `EventSourceResponse` — NOT BaseHTTPMiddleware) + a `GET /ui/api/notebooks/{slug}/ingest-stream` yielding `<tr>` fragments off `IngestTaskTracker` state; vendor the htmx SSE ext JS. Optional MCP `logging:{}` capability + `notifications/message` from the ingest subprocess (zero BP1 cost). Verify CSP allows the SSE attributes.

**Open questions:** is the existing polling "good enough" (challenger should weigh the value-density of SSE vs polling for a single operator)?

---

### CAND-2 — Extend restic backup to cover notebook data + `notebooks.db`

**Category:** Ops / infra
**Size:** XS
**Evidence triangulation:** 3 briefs (adversary ✓, research-frontier ✓, oss-trends ✓)

**What it is:** Add `var/arxmcp/notebooks/` (per-notebook LanceDB + parsed HTML + **user-uploaded PDFs**) and `var/arxmcp/cache/notebooks.db` (notebook metadata) to the E14 restic include-path, and update the restore drill to verify a notebook survives a backup/restore cycle.

**Why it matters:** User-uploaded PDFs and curated paper lists are NON-regenerable; today they're outside backup scope (the ops note predates the notebook feature). Highest-value/lowest-effort durability fix.

**Sources:** adversary H2; research-frontier C7 (restic discipline); oss-trends 2.7 (restic `--files-from-verbatim` manifest).

**Closest arXMCP analog:** `infra/restic/` (E14_S05 backs up corpus + lancedb + Kùzu); `08-security-observability-ops.md` backup section (notebooks absent); `server/notebooks_store.py` docstring ("caches NOT backed up" — but conflates cache with notebook metadata).

**Sketch:** Add the two paths to the restic include-list (a `--files-from-verbatim -` manifest distinguishing user-data from regenerable caches), update the restore-drill script + ops note. ~20 LOC shell + doc.

**Open questions:** none.

---

### CAND-3 — Harden `notebooks.db` SQLite durability (`synchronous=FULL` + `fullfsync` on macOS)

**Category:** Ops / infra
**Size:** XS
**Evidence triangulation:** 3 briefs (research-frontier ✓, comparative ✓ adjacency, oss-trends ✓ adjacency)

**What it is:** Set `PRAGMA synchronous=FULL` + `PRAGMA fullfsync=ON` on the notebook/ingest/parse SQLite connections so a committed notebook write survives an OS crash / power loss (the default `NORMAL` + neutered macOS `fsync` can roll back the last commit).

**Why it matters:** Closes a documented data-loss window on the operator's primary metadata store, on a low-write path where the durability cost is negligible. Cheapest correctness win in the whole catalog.

**Sources:** research-frontier C1 (the load-bearing 5-LOC fix at `server/notebooks_store.py:117`); comparative C6 + oss-trends 2.1 note WAL mode is already on (the prerequisite).

**Closest arXMCP analog:** `server/notebooks_store.py:116-117` (sets `journal_mode=WAL` + `synchronous=NORMAL`); check `server/ingest_tracker.py`, `server/parse_tracker.py`, `server/cache_sqlite.py` for sibling connections.

**Sketch:** ~5 LOC across the SQLite connection openers; add a regression test asserting the pragmas. NOTE: macOS RLIMIT/`fullfsync` is a known arXMCP-platform quirk (CLAUDE.md gotcha 9) — this is the storage analogue.

**Open questions:** apply to the Tier-1 retrieval cache (`cache_sqlite.py`) too, or only the durable notebook store (cache is regenerable → maybe leave NORMAL)?

---

### CAND-4 — Litestream sidecar: continuous WAL replication of `notebooks.db` to a local replica

**Category:** Ops / infra
**Size:** S
**Evidence triangulation:** 3 briefs (comparative ✓, research-frontier ✓, oss-trends ✓)

**What it is:** Run Litestream (Apache-2.0, 13.6k★, v0.5.11 Apr-2026) as a compose sidecar streaming `notebooks.db` WAL frames to a second local path, giving sub-second-lag point-in-time recovery without a cloud dependency; container startup uses `restore --if-db-not-exists` for idempotent recovery.

**Why it matters:** Finer-grained recovery than nightly restic for the metadata store specifically; complements (does not replace) restic. Pure config, zero Python change.

**Sources:** comparative C6; research-frontier C3; oss-trends 2.1.

**Closest arXMCP analog:** `infra/restic/` (nightly snapshot — complementary layer); requires WAL mode (already on per CAND-3 prerequisite).

**Sketch:** New `infra/litestream.yml` + a `litestream` service in CAND-1's compose sharing the `var/arxmcp/cache/` volume, replica `type: file`. No-fork: runs as its own image. Gated on CAND-1.

**Open questions:** is this over-investment for a single workstation given CAND-2 (restic) + CAND-3 (durable commits) already cover most of the risk? (challenger: weigh against value-density).

---

### CAND-6 — Operator status surface: `make status` CLI + htmx status badge in the UI shell

**Category:** Ops / infra
**Size:** XS–S
**Evidence triangulation:** 3 briefs (comparative ✓, research-frontier ✓, adversary ✓)

**What it is:** A `make status` target that curls `/status` (CAND-5) and prints a human line (`READY | embedder warm | corpus v7 | 3 notebooks`), plus a small htmx-polled (`hx-trigger="every 10s"`) status badge in `frontend/templates/base.html`.

**Why it matters:** Directly answers the operator's "is the server running + ready?" question for both bare-metal (`make up`) and browser users, with no GUI/tray app.

**Sources:** comparative C3 (badge) + C7 (`make status`); research-frontier C6 (htmx SSE/poll badge); adversary M2.

**Closest arXMCP analog:** `Makefile` (no `status` target); `frontend/templates/base.html:59` (raw `/healthz`/`/readyz` JSON links — not operator-friendly).

**Sketch:** Depends on CAND-5. `make status` = one shell+python one-liner. Badge = a `<span hx-get="/status" hx-trigger="load, every 10s">` rendering prose. Poll is simpler than SSE here.

**Open questions:** none (gated on CAND-5).

---

### CAND-14 — Notebook UI completion: per-paper ingest-status column + freshness indicator + htmx CRUD (rename/delete-with-confirm)

**Category:** Ops / infra (UI)
**Size:** S
**Evidence triangulation:** 3 briefs (comparative ✓, adversary ✓, research-frontier ✓ adjacency)

**What it is:** Round out the notebook-management UI: a per-paper status column (`pending|parsing|embedding|ready|failed`), a "Last indexed: …/Never indexed" freshness signal per notebook, and in-page rename/delete actions via `hx-delete`/`hx-confirm` (+ a new `PATCH` rename endpoint).

**Why it matters:** Today a notebook with papers-added-but-never-ingested looks identical to a fully-indexed one; and the only delete path is the raw API. This is the "manage my notebooks" UX the user asked for.

**Sources:** comparative C9 (status column) + C10 (htmx CRUD); adversary M3 (freshness indicator).

**Closest arXMCP analog:** `frontend/templates/notebook_detail.html` + `index.html`; `server/routes/notebooks.py` (`DELETE` exists, no rename, no status column); `server/notebooks_store.py` (no `last_ingest_succeeded_at`).

**Sketch:** Additive SQLite migration (`last_ingest_succeeded_at`, v4→v5, backfill NULL) written by the ingest done-callback; surface in the detail template; `PATCH /ui/api/notebooks/{slug}` (display_name only, slug is structural); `hx-delete`+`hx-confirm` row removal. Overlaps CAND-8 (status column is the SSE/poll render target).

**Open questions:** sequence after CAND-8 (shared status plumbing)?

---

### CAND-9 — Per-notebook export/import (tar + `manifest.json`) for portability

**Category:** Ops / infra
**Size:** S
**Evidence triangulation:** 2 briefs (comparative ✓, research-frontier ✓)

**What it is:** `GET /ui/api/notebooks/{slug}/export` streams a tar (`manifest.json` + lancedb + parsed HTML + pdfs + bm25.pkl); `POST /ui/api/notebooks/import` re-registers it. Satisfies the local-first "longevity" ideal (Kleppmann) + the PaperQA2 manifest-CSV portability pattern.

**Why it matters:** The user explicitly wants "a better way to store/move notebooks." Today there's no migrate/share/standalone-backup path for a single notebook independent of the full corpus.

**Sources:** comparative C5; research-frontier C8 (PaperQA2 `DocDetails`/manifest) + C9 (local-first longevity).

**Closest arXMCP analog:** `server/routes/notebooks.py` (`DELETE` is metadata-only; on-disk wipe is `tools/notebook_purge.py`); no export route.

**Sketch:** `tarfile` + `StreamingResponse`; must block export during a live ingest (gate on `IngestTaskTracker`); close the LanceDB read handle cleanly. Pure-ASGI.

**Open questions:** include the (large) LanceDB index in the tar, or just the manifest + source PDFs and re-ingest on import (smaller, slower)?

---

### CAND-10 — Expose notebooks as MCP resources (`resources/list` + `resources/subscribe`)

**Category:** MCP tool surface
**Size:** M
**Evidence triangulation:** 2 briefs (multi-agent ✓, multi-agent-via-gnosis ✓)

**What it is:** Register the MCP `resources` capability and serve `arxmcp://notebooks/<slug>` (+ `arxmcp://notebooks/<slug>/status`) so the AGENT — not just the human UI — can enumerate notebooks and subscribe to ingest-completion (`notifications/resources/updated`). **Zero BP1 cost** (resources are a separate capability from `tools/list`).

**Why it matters:** Today corpus management is human-UI-only; the sketcher/autoformalizer can't self-discover which notebooks exist or learn when a newly-added paper is retrievable. This is the agent-facing half of "notebook management."

**Sources:** multi-agent C1 (MCP resources spec) + C7 (gnosis-mcp `gnosis://docs` precedent).

**Closest arXMCP analog:** `server/tools.py` declares `arxmcp://chunks/<id>` resource_link URIs but the server does NOT register the `resources` capability or `resources/list`/`read` handlers; notebooks are absent from the MCP surface.

**Sketch:** New `server/handlers/resources.py` (list/read) + advertise `resources:{listChanged:true}` at `initialize`; back `list` with `NotebooksStore.list_notebooks()`. Verify it does NOT drift `tools/list` bytes (it shouldn't — separate request).

**Open questions:** harness support for `resources/subscribe` lags the spec ~3–6mo — ship `list`/`read` now, `subscribe` when consumers exist?

---

### CAND-13 — Refresh the stale design constitution (retire "no frontend by design"; update CLAUDE.md §5 + install.md)

**Category:** Ops / infra (docs)
**Size:** XS
**Evidence triangulation:** 2 briefs (adversary ✓, comparative ✓ theme)

**What it is:** Update `.claude/notes/06-mcp-server-design.md` to document the notebook UI (htmx shell, `/ui/api`, frontend/ layout, CSP override); add `server/routes/`, `server/notebooks_store.py`, `frontend/` to CLAUDE.md §5; add the `/ui/` URL to `docs/install.md`; flag in the E13 milestone state that the UI surface was never security-audited.

**Why it matters:** The constitution gates every future agent's threat-model + onboarding reasoning. The "no frontend exists" claim means the E13 security audit skipped the Jinja2/htmx stack entirely — a real review gap, not just a doc nit.

**Sources:** adversary M1 + L1 + L2; comparative (drift theme); the scout brief explicitly flagged it.

**Closest arXMCP analog:** `.claude/notes/06-mcp-server-design.md` (frozen at E06); `.claude/notes/milestones/E13_S06/critique-merged.md` ("no frontend exists"); CLAUDE.md §5.

**Sketch:** Doc-only edits. Pair with a note that a follow-up security pass on the UI routes (XSS/CSP/template-injection/htmx) is warranted — possibly its own candidate/milestone.

**Open questions:** does the un-audited UI warrant a dedicated security milestone (separate from this doc refresh)?

---

### CAND-7 — Add `HEALTHCHECK` to `Dockerfile.server` [VERIFY — may already exist]

**Category:** Ops / infra
**Size:** XS
**Evidence triangulation:** 2 briefs (comparative ✓, oss-trends ✓) — **but contradicted by the adversary**

**What it is:** A `HEALTHCHECK --start-period≈90s CMD curl -f /readyz` directive so `docker ps` shows health + compose can gate `service_healthy`.

**Why it matters:** Surfaces BGE-M3-warm state to Docker + the operator; prerequisite for CAND-1's `depends_on: service_healthy`.

**Sources:** comparative C8 + oss-trends 2.8 (claim it's absent). **CONTRADICTION:** CLAUDE.md §5 + the adversary describe `docker/Dockerfile.server` as already having a HEALTHCHECK on `/readyz` (and oss-trends 2.8 elsewhere says "the existing HEALTHCHECK ... with start_period 5m"). Likely already shipped.

**Closest arXMCP analog:** `docker/Dockerfile.server` — **read it to confirm** before doing anything.

**Sketch:** If present → fold into CAND-1 (verify `curl` is in the runtime image) and drop as a standalone candidate. If absent → one-line add.

**Open questions:** does the HEALTHCHECK already exist? (resolve first — cheap to check.)

---

### CAND-11 — Author the `SYSTEM_PROMPT` placeholder + set the MCP `initialize` `instructions` field

**Category:** Agent harness
**Size:** S
**Evidence triangulation:** 1 brief (multi-agent ✓) — flag for scrutiny

**What it is:** Write the long-deferred `SYSTEM_PROMPT` (CLAUDE.md gotcha 6 — still a placeholder) and populate the MCP `initialize` `instructions` field with a *static* corpus orientation (NOT a live notebook list, which would break BP1 cross-session cache hits).

**Why it matters:** Orients any freshly-connected agent; Claude Code's Tool Search uses `instructions` to decide when to surface the server's tools. Long-standing known stub.

**Sources:** multi-agent C5.

**Closest arXMCP analog:** `server/prompts.py:6` (placeholder `SYSTEM_PROMPT`); `tests/test_prompts.py::EXPECTED_BP1_SHA256` (re-pin fires when authored).

**Sketch:** Author the constant; set static `instructions` at `initialize`; re-pin `EXPECTED_BP1_SHA256` (coordinated, one-time). Keep `instructions` static/version-pinned — dynamic notebook state belongs in CAND-10 resources, not here.

**Open questions:** scope of the system prompt (this is a broader agent-harness decision than this scout's theme — likely its own track).

---

### CAND-12 — Notebook-management MCP tools (`list_notebooks`, `get_notebook_status`, corpus stats)

**Category:** MCP tool surface
**Size:** M
**Evidence triangulation:** 1 brief (multi-agent ✓) — flag for scrutiny

**What it is:** A small batch of read-only MCP tools letting the agent enumerate notebooks, query ingest status, and read corpus stats (paper/chunk counts).

**Why it matters:** Agent-driven corpus curation without human mediation. BUT — **largely subsumed by CAND-10 (resources) at zero BP1 cost**; tools force an `EXPECTED_TOOL_SCHEMA_SHA256` + BP1 re-pin (session-wide cache bust for all agents).

**Sources:** multi-agent C3 + C6 (NotebookLM pattern) + C7 (gnosis corpus stats).

**Closest arXMCP analog:** `server/tools.py::ALL_TOOLS` (7+1 tools, hash-pinned); `tests/test_server_tool_schema.py`.

**Sketch:** Prefer CAND-10 (resources) for read-only enumeration. Only add tools if an agent needs to *act* (trigger ingest) — and batch all additions into ONE schema bump. Verify outputSchema (2025-06-18) usage.

**Open questions:** is there a real agent use-case for notebook-mgmt TOOLS that resources can't serve? (challenger: likely MINOR/redundant vs CAND-10.)

---

### CAND-17 — Adopt the Claude Code operability contract (`tools:{listChanged:true}`, `_meta` result-size annotations, `alwaysLoad` doc)

**Category:** MCP tool surface / Agent harness
**Size:** S
**Evidence triangulation:** 1 brief (multi-agent ✓) — flag for scrutiny

**What it is:** Advertise `tools:{listChanged:true}` at `initialize` (zero `tools/list` byte change); add `_meta["anthropic/maxResultSizeChars"]` to large-result tools (`get_chunk`, `find_equation`); document `alwaysLoad:true` in the `.mcp.json` install example.

**Why it matters:** Prevents silent harness truncation of large `get_chunk` bodies and guarantees arXMCP tools load at session start. Mostly cheap protocol-hygiene.

**Sources:** multi-agent C8.

**Closest arXMCP analog:** `server/_mcp_mount.py` (`initialize` capabilities); `server/tools.py::ALL_TOOLS`; `docs/install.md`.

**Sketch:** `listChanged` + `alwaysLoad`-doc are free. The `_meta` additions DO change `tools/list` bytes → `EXPECTED_TOOL_SCHEMA_SHA256` re-pin (verify whether BP1 is affected — m9/m11 lesson: BP1 hashes {name,description} only, so `_meta` likely drifts tool-schema-hash but not BP1).

**Open questions:** confirm the BP1-vs-tool-schema-hash split for `_meta` changes (the m9/m11 finding).

---

### CAND-15 — Build a per-notebook BM25 index for textbook-kind notebooks

**Category:** Retrieval quality
**Size:** XS
**Evidence triangulation:** 1 brief (adversary ✓) — flag for scrutiny

**What it is:** After `write_chunks` in `tools/notebook_textbook_ingest.py`, call `build_bm25_index(...)` (as the arXiv `notebook_ingest.py` already does) so textbook notebooks get hybrid-ready BM25, not dense-only.

**Why it matters:** Parity with the arXiv path. BUT — m12 deliberately skipped it because **notebook retrieval is dense-only at v1** (notebook-retrieval-m2 AC2), so the index would be dead code until hybrid notebook retrieval ships.

**Sources:** adversary M4 (+ this is the m12 deferred decision — see m12 synthesis D1).

**Closest arXMCP analog:** `tools/notebook_textbook_ingest.py` (no BM25); `tools/notebook_ingest.py` (builds it); `ingest/bm25_indexer.py`.

**Sketch:** 3-LOC add. **Sequencing:** only valuable alongside enabling hybrid retrieval for notebooks — otherwise premature.

**Open questions:** is hybrid notebook retrieval on the roadmap? If not, this stays deferred (correctly).

---

### CAND-16 — LanceDB on-disk format version-pin discipline

**Category:** Ops / infra
**Size:** XS
**Evidence triangulation:** 1 brief (research-frontier ✓) — flag for scrutiny

**What it is:** Explicitly pin `data_storage_version` on LanceDB dataset writes so a `uv`/`pip` upgrade can't silently migrate the on-disk format to a version the pinned reader can't decode (Lance v2.1 needs lance ≥0.38.0).

**Why it matters:** Prevents a silent-corruption-on-upgrade scenario across the host-writes / container-reads boundary that CAND-1 introduces.

**Sources:** research-frontier C4 (arXiv:2504.15247 + Lance 2.1 release notes).

**Closest arXMCP analog:** `ingest/store.py` (dataset writes); `tools/_notebook_common.py` (per-notebook LanceDB); `pyproject.toml` (the pin).

**Sketch:** ~3 LOC on write calls + a `pyproject.toml` comment. Becomes more important once CAND-1 splits write-host from read-container.

**Open questions:** what version does arXMCP's pinned LanceDB write by default today? (verify before pinning.)

---

### CAND-18 — Formalize restic retention policy + `check --read-data-subset` quarterly drill

**Category:** Ops / infra
**Size:** XS
**Evidence triangulation:** 1 brief (research-frontier ✓) — flag for scrutiny

**What it is:** Specify `--keep-daily 7 --keep-weekly 4 --keep-monthly 12` and a `check --read-data-subset=5%` rotation so the quarterly restore drill actually validates pack DATA (not just index), covering 100% over ~5 runs.

**Why it matters:** `restic check` alone validates index consistency, not pack integrity; the current drill doesn't specify the subset fraction. Hardens an already-shipped mechanism.

**Sources:** research-frontier C7.

**Closest arXMCP analog:** `infra/restic/` + `var/arxmcp/ops/backup-status.json` sentinel; `08-security-observability-ops.md` quarterly drill (unspecified fraction).

**Sketch:** ~20 LOC in the backup wrapper + sentinel fields; pairs naturally with CAND-2 (which adds the notebook paths).

**Open questions:** none.

## 4. Cross-cutting tensions

1. **Named Docker volumes vs host bind-mounts for `var/arxmcp/`** — comparative C4 + multi-agent C4 favor *named volumes* (Docker-managed lifecycle, `docker volume inspect`); research-frontier C9 (and oss parking-lot) favor *host bind-mounts* (`$PWD/var/arxmcp`) so the data stays host-visible and restic can back it up at a stable path. **Resolution for CAND-1:** bind-mount `var/arxmcp/` (host-visibility + restic at a known path wins for a single-operator local-first tool; named volumes obscure the data dir from the operator's file manager and complicate the restic include-path). This directly affects CAND-2/4/9.

2. **Storage durability: how many layers?** restic (CAND-2) + SQLite `synchronous=FULL` (CAND-3) + Litestream (CAND-4) overlap. CAND-2 and CAND-3 are XS, near-zero-cost, and cover the common failure modes; CAND-4 (Litestream sidecar) adds continuous replication but is arguably over-investment for one workstation. **Surfaced for the challenger** to weigh CAND-4's value-density.

3. **Agent-facing notebook management: resources (CAND-10) vs tools (CAND-12)** — both expose notebook enumeration to the agent. Resources are zero-BP1-cost; tools force a session-wide cache bust. The BP1 discipline is a *forcing function toward resources* for read-only enumeration. **Resolution:** prefer CAND-10; CAND-12 only if the agent must *act* (trigger ingest), batched.

4. **SSE vs polling for ingest progress (CAND-8)** — arXMCP already ships htmx polling that works. SSE is "nicer" but for a single operator the difference is marginal. Tension: net-new dependency (`sse-starlette`) + CSP changes vs marginal UX gain. **Surfaced for the challenger.**

5. **`/status` degraded→`warn`(2xx) vs 503** — research-frontier C2 wants the IETF `warn` (2xx) for degraded/N-1-corpus; arXMCP's `/readyz` returns 503. Flipping `/readyz` would change probe semantics (load-balancers stop draining a degraded-but-serving pod). **Resolution:** keep `/readyz` 503-on-degraded; put `warn` semantics ONLY on the new `/status` (CAND-5).

## 5. What's already in flight / partially shipped (do NOT re-litigate)

- **htmx ingest-status polling** (HTTP-286 stop-signal) — SHIPPED (proof-verify-m9). CAND-8 is an *upgrade*, not net-new.
- **`Dockerfile.server` HEALTHCHECK** — likely SHIPPED (CLAUDE.md §5 + adversary say `/readyz` healthcheck exists); CAND-7 must verify first.
- **restic backup + atomic cutover + corpus_version MVCC + `/metrics` + OTel** — SHIPPED (E11/E14). CAND-2/18 extend scope; CAND-16 hardens versioning.
- **Per-notebook LanceDB + `filters.notebook` routing + `ARXMCP_NOTEBOOK`** — SHIPPED (notebook-retrieval m1/m2). CAND-10 adds the *agent-facing* surface over the same store.
- **WAL mode on `notebooks.db`** — SHIPPED (`notebooks_store.py:116`); CAND-3 adds the missing `synchronous=FULL`.
- **Textbook dense-only retrieval** — m12 deliberately skipped BM25 (D1); CAND-15 reverses it only if hybrid notebook retrieval is wanted.
- **SYSTEM_PROMPT placeholder** — known stub (CLAUDE.md gotcha 6); CAND-11.

## 6. Parking lot (did not survive synthesis)

- **MinIO / SeaweedFS / Garage object storage** — AGPL (MinIO/Garage) → study-only under no-fork; multi-process; over-engineered vs bind-mount + restic for one workstation. (comparative + oss parking lots.)
- **WebDAV / LiteFS / multi-device sync / CRDTs** — require network server or multi-host; violate local-first/loopback-only. Park until a multi-device requirement exists.
- **SPA frontend (React/Vue/Svelte) / FastUI / Reflex / NiceGUI** — Node build chain or second port; the htmx+Jinja2 stack + Alpine (for drag-drop only) covers the need without a build step.
- **Datastar (HTMX replacement)** — interesting signal-driven SSE, but don't displace already-vendored htmx without a concrete pain point. Future upgrade path.
- **Uptime Kuma** — config-in-SQLite, not version-controllable; Gatus (config-as-code YAML) fits the repo convention better (but Gatus itself is gated on CAND-1).
- **Tray/desktop indicator (Electron/Tauri/PyQt)** — GUI framework for a headless MCP server; `make status` + UI badge (CAND-6) cover the need.
- **MCP `sampling` / `elicitation`** — require the server to call an LLM / broker user interaction → architecture-lock conflict (no anthropic SDK at runtime).
- **Prometheus alertmanager** — over-complex for one operator; cron/email from the backup wrapper suffices. (Prometheus `/metrics` already ships.)
- **Backrest (restic WebUI)** — adds a service for UX over the existing restic CLI; nice-to-have, not now.
- **Kopia as restic replacement** — restic already in use (E14); not worth switching (CDC dedup gain is marginal here).
