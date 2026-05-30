# Final Report — capability-scout 2026q2-notebook-ux-storage-ops

**Theme:** Notebook management UX · durable/portable notebook storage · operability ("is it running") · container packaging
**Pipeline:** 5 scouts → synthesis (18 candidates) → challenger (1 BLOCKER / 2 MAJOR / 6 MINOR / 9 NONE) → this ranking
**Generated:** 2026-05-28

## 1. Executive summary

The scout confirms your instinct on all four fronts — but the highest-value moves are **cheap correctness/durability fixes, not new infrastructure**. The top of the RICE ranking is dominated by two XS fixes that close real data-loss windows: **CAND-2** (add the notebook tree + `notebooks.db` to the restic backup scope — today your *non-regenerable user-uploaded PDFs* aren't backed up) and **CAND-3** (set SQLite `synchronous=FULL` + `fullfsync`, a ~5-LOC fix that closes a documented power-loss commit-loss window on macOS). The third pick, **CAND-6**, is the direct answer to "is it running" — a `make status` + a UI status badge, riding a new **CAND-5** `/status` JSON endpoint. The **base `docker-compose.yml` (CAND-1)** is the *structural unblocker* — all 5 scouts flagged it independently and six other candidates gate on it — but the challenger correctly re-scoped it from M to **server-only S** (the `reject_non_loopback` container carve-out already ships via `ARXMCP_UNSAFE_NETWORK_BIND`, and the Dockerfile HEALTHCHECK candidate CAND-7 is **already shipped** → killed). The richer notebook frontend you asked about already exists (Jinja2+htmx) and just needs **completion** (CAND-14: per-paper status, freshness, rename/delete) — and a flagged caveat: **that UI was never security-audited** (the E13 audit literally scoped it out as "no frontend exists"), which CAND-13 converts into a tracked issue. **Confidence ceiling caveat:** this was an infra/UX scout with 15-min scout budgets; effort estimates are t-shirts (±50%), and the two XS top-picks score sky-high partly because RICE-light rewards tiny effort — treat them as "do-first cheap wins," not "the only things worth doing."

## 2. Quick-glance ranking table

| Rank | Cand | Title | Category | Size | R | I | C | E | RICE | Adj | Final | Challenger |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | CAND-2 | Extend restic backup to notebook data + `notebooks.db` | Ops/infra | XS | 3 | 3 | 0.8 | 0.25 | 28.8 | — | **28.8** | NONE |
| 2 | CAND-3 | SQLite durability `synchronous=FULL`+`fullfsync` | Ops/infra | XS | 3 | 3 | 0.8 | 0.25 | 28.8 | — | **28.8** | NONE |
| 3 | CAND-6 | `make status` + htmx UI status badge | Ops/infra | XS | 3 | 1 | 0.8 | 0.25 | 9.6 | — | **9.6** | NONE (gates on CAND-5) |
| 4 | CAND-1 | Base `docker-compose.yml` (server-only v0) | Ops/infra | S | 3 | 3 | 1.0 | 1 | 9.0 | ×0.75 | **6.75** | MAJOR |
| 5 | CAND-16 | LanceDB on-disk format version-pin | Ops/infra | XS | 3 | 1 | 0.3 | 0.25 | 3.6 | — | **3.6** | NONE |
| 5 | CAND-18 | restic retention + `check --read-data-subset` drill | Ops/infra | XS | 3 | 1 | 0.3 | 0.25 | 3.6 | — | **3.6** | NONE |
| 7 | CAND-5 | `/status` JSON endpoint (IETF health+json) | Ops/infra | S | 3 | 1 | 1.0 | 1 | 3.0 | — | **3.0** | NONE |
| 8 | CAND-11 | MCP `initialize.instructions` (v0; SYSTEM_PROMPT deferred) | Agent harness | XS | 3 | 1 | 0.3 | 0.25 | 3.6 | ×0.75 | **2.7** | MAJOR |
| 9 | CAND-14 | Notebook UI completion (status/freshness/CRUD) | Ops/infra | S | 3 | 1 | 0.8 | 1 | 2.4 | — | **2.4** | NONE |
| 10 | CAND-13 | Refresh constitution + file UI-security-audit issue | Ops/infra | XS | 1 | 1 | 0.5 | 0.25 | 2.0 | — | **2.0** | MINOR |
| 11 | CAND-8 | SSE ingest progress (v0: MCP logging only) | Agent harness | S | 3 | 0.5 | 1.0 | 1 | 1.5 | — | **1.5** | MINOR |
| 11 | CAND-9 | Per-notebook export/import (tar + manifest) | Ops/infra | S | 3 | 1 | 0.5 | 1 | 1.5 | — | **1.5** | NONE |
| 11 | CAND-10 | Notebooks as MCP resources (list/subscribe) | MCP tool surface | M | 3 | 3 | 0.5 | 3 | 1.5 | — | **1.5** | NONE |
| 14 | CAND-4 | Litestream WAL-replication sidecar | Ops/infra | S | 3 | 0.5 | 0.8 | 1 | 1.2 | — | **1.2** | MINOR (defer) |
| 15 | CAND-17 | Claude Code operability contract (`listChanged`/`_meta`) | MCP tool surface | S | 3 | 1 | 0.3 | 1 | 0.9 | — | **0.9** | MINOR |
| 16 | CAND-15 | Textbook-notebook BM25 index | Retrieval quality | XS | 1 | 0.5 | 0.3 | 0.25 | 0.6 | — | **0.6** | MINOR (defer) |
| 17 | CAND-7 | Dockerfile HEALTHCHECK | Ops/infra | — | — | — | — | — | — | KILL | **KILL** | BLOCKER (already shipped) |
| 18 | CAND-12 | Notebook-management MCP tools (read-only) | MCP tool surface | M | 1 | 0.5 | 0.3 | 3 | 0.05 | — | **0.05** | MINOR (kill, redundant w/ CAND-10) |

## 3. Top 10 in detail

### Rank 1 — CAND-2 · Extend restic backup to notebook data + `notebooks.db` (RICE 28.8, NONE)
- **Synthesis gist:** `var/arxmcp/notebooks/` (per-notebook LanceDB + parsed HTML + **user-uploaded PDFs**) and `var/arxmcp/cache/notebooks.db` are outside the E14 restic include-path; the ops note predates the notebook feature. PDFs are non-regenerable.
- **Challenger:** clean. XS, no architecture conflict, closes a real data-loss gap.
- **RICE:** R=3 (all notebook data) × I=3 (kills adversary H2) × C=0.8 (3 briefs) / E=0.25 (XS) = 28.8. **Do first.**

### Rank 2 — CAND-3 · SQLite durability `synchronous=FULL` + `fullfsync` (RICE 28.8, NONE)
- **Synthesis gist:** `server/notebooks_store.py:117` ships `synchronous=NORMAL`; under WAL + macOS's neutered `fsync`, the last committed notebook write can be lost on power-loss. `PRAGMA synchronous=FULL` + `fullfsync=ON` closes it; negligible cost on a low-write metadata store.
- **Challenger:** clean. 5-LOC; no architecture/cache interaction.
- **RICE:** R=3 × I=3 (documented data-loss window) × C=0.8 / E=0.25 = 28.8. **Do first.** (Open Q: apply to the regenerable Tier-1 cache too, or only the durable notebook store?)

### Rank 3 — CAND-6 · `make status` + htmx UI status badge (RICE 9.6, NONE; gates on CAND-5)
- **Synthesis gist:** the direct answer to "is it running?" — a `make status` that curls `/status` and prints a human line, plus a `<span hx-get="/status" hx-trigger="every 10s">` badge in `base.html` (today the footer links raw JSON).
- **Challenger:** clean; correctly gated on CAND-5.
- **RICE:** R=3 × I=1 (operator QoL/parity) × C=0.8 / E=0.25 = 9.6. **Ships with CAND-5.**

### Rank 4 — CAND-1 · Base `docker-compose.yml` (server-only v0) (RICE 6.75, MAJOR)
- **Synthesis gist:** the structural unblocker — 5/5 scouts; six candidates gate on it. Mirror the shipped `infra/observability/phoenix-compose.yml` template (loopback bind, `@sha256` pins, `cap_drop:[ALL]`).
- **Challenger (MAJOR → ×0.75):** re-scope M→**S (server-only v0)**: the `ARXMCP_UNSAFE_NETWORK_BIND=1` carve-out already ships (`server/config.py:348/513`), so no `reject_non_loopback` work needed; **bind-mount** `var/arxmcp/` (host-visible for restic) but document the **uid/gid chown** pre-step (`chown -R 1000:1000 var/arxmcp` — macOS Docker Desktop will hit this); defer the `arxmcp-ingest` service to v1 (needs a Dockerfile.ingest first).
- **RICE:** R=3 × I=3 (kills adversary H1 + unblocks the cluster) × C=1.0 / E=1 (v0 S) = 9.0 → ×0.75 = 6.75.

### Rank 5 (tie) — CAND-16 · LanceDB on-disk format version-pin (RICE 3.6, NONE)
- **Gist:** explicitly pin `data_storage_version` on LanceDB writes so a `uv`/`pip` upgrade can't silently migrate the on-disk format to a version the pinned reader can't decode — sharper once CAND-1 splits host-writer from container-reader. **Challenger:** clean, 3-LOC + pin comment. **RICE:** 3×1×0.3/0.25 = 3.6. (Open Q: what version does the pinned LanceDB write today? verify first.)

### Rank 5 (tie) — CAND-18 · restic retention + `check --read-data-subset` drill (RICE 3.6, NONE)
- **Gist:** specify `--keep-daily 7 --keep-weekly 4 --keep-monthly 12` + a `check --read-data-subset=5%` rotation so the quarterly drill validates pack DATA, not just the index. **Challenger:** clean, ~20-LOC; pairs with CAND-2. **RICE:** 3×1×0.3/0.25 = 3.6.

### Rank 7 — CAND-5 · `/status` JSON endpoint (IETF health+json) (RICE 3.0, NONE)
- **Gist:** a `GET /status` envelope (`pass|warn|fail` + per-component checks + corpus_version + notebook count + uptime) that the badge (CAND-6), `make status`, Gatus, and a Docker healthcheck all consume. Keep `/readyz` 503-on-degraded; put `warn`(2xx) only on `/status`. **Challenger:** clean, pure-ASGI, no BP1/tool-schema interaction. **RICE:** 3×1×1.0/1 = 3.0. **Pair with CAND-6.**

### Rank 8 — CAND-11 · MCP `initialize.instructions` (v0 only) (RICE 2.7, MAJOR)
- **Gist:** populate the MCP `initialize.instructions` field with a static one-paragraph corpus orientation (Claude Code's Tool Search uses it).
- **Challenger (MAJOR → ×0.75):** SPLIT the candidate — **v0 = static `instructions` only** (XS, **zero BP1 re-pin** — it's in the `initialize` response, not `tools/list`/system-prompt). **DEFER** authoring the `SYSTEM_PROMPT` placeholder (CLAUDE.md gotcha 6) to a dedicated agent-harness milestone (it's a policy decision + a BP1 re-pin, out of this infra scout's scope; document in `.claude/docs/model-policy.md`).
- **RICE:** 3×1×0.3/0.25 = 3.6 → ×0.75 = 2.7 (v0 cut).

### Rank 9 — CAND-14 · Notebook UI completion (RICE 2.4, NONE)
- **Gist:** the "manage my notebooks" UX you asked for — per-paper ingest-status column, a "Last indexed / Never indexed" freshness signal (additive `last_ingest_succeeded_at` SQLite column, v4→v5), and in-page rename (`PATCH`) / delete (`hx-delete`+`hx-confirm`). **Challenger:** clean; but see CC-4 — adds to the un-audited UI surface (pair with CAND-13). **RICE:** 3×1×0.8/1 = 2.4. Overlaps CAND-8 (shared status plumbing).

### Rank 10 — CAND-13 · Refresh constitution + file UI-security-audit issue (RICE 2.0, MINOR)
- **Gist:** retire the stale "no frontend exists, by design" claim in `06-mcp-server-design.md`; add `server/routes/`, `notebooks_store.py`, `frontend/` to CLAUDE.md §5; add the `/ui/` URL to `install.md`.
- **Challenger (MINOR):** the doc fix UNDER-scopes a real finding — the Jinja2/htmx UI was **never security-audited** (E13 scoped it out). v1 = doc refresh (XS) **AND file a GitHub issue** at `chris-dare-dev/arXMCP` for a dedicated UI security audit (XSS/CSP/template-injection/htmx), analogous to E13 for the MCP surface.
- **RICE:** 1×1×0.5/0.25 = 2.0.

*(Ranks 11–18: CAND-9 export, CAND-10 MCP resources [agent-facing, M], CAND-8 SSE [v0 MCP-logging only], CAND-4 Litestream [defer], CAND-17 operability contract [`listChanged`+`alwaysLoad` are free; `_meta` is a tool-schema re-pin], CAND-15 textbook BM25 [defer until hybrid notebook retrieval is roadmapped], CAND-7 [KILL — already shipped at `Dockerfile.server:133`], CAND-12 read-only tools [KILL — redundant with CAND-10 at zero BP1 cost]. Full entries in `synthesis.md` + `challenge.md`.)*

## 4. Recommended next steps

1. **Feed `/roadmap` a single "notebook-ops-hardening" epic** bundling the coherent cluster that answers all four of your questions:
   - *Storage durability (your Q3):* CAND-2 (restic notebooks) + CAND-3 (SQLite FULL) + CAND-16 (Lance pin) + CAND-18 (restic drill) — all XS, all clean, ~1 week total.
   - *Operability "is it running" (your Q2):* CAND-5 (`/status`) + CAND-6 (`make status` + badge) — ~S.
   - *Container packaging (your Q4):* CAND-1 (docker-compose, **server-only v0, S**) — the spine; ingest service + Litestream (CAND-4) deferred to v1.
   - *Notebook frontend (your Q1):* CAND-14 (UI completion) + CAND-13 (constitution refresh + **security-audit issue**) — ~S.
   - *Agent-facing (bonus):* CAND-10 (notebooks as MCP resources, zero-BP1) + CAND-11 v0 (`instructions`) + CAND-9 (export).
2. **Spike-lane (unvalidated assumptions — `/roadmap` should spike before committing):**
   - CAND-1's **uid/gid bind-mount friction on macOS Docker Desktop** — spike a 1-day "does `docker compose up` write `var/arxmcp/` cleanly on the operator's machine?" before sizing the compose milestone.
   - CAND-8 **SSE vs existing polling** — the challenger says the existing htmx-286 polling already works; spike whether SSE is worth a new dep before building it (ship the v0 MCP-logging half instead).
3. **Resolve two [VERIFY] items inline before roadmap decomposition** (cheap reads): (a) confirm CAND-7's HEALTHCHECK is shipped (it is — kill it); (b) confirm the LanceDB default write version for CAND-16's pin.
4. **Park for a later scout/milestone:** CAND-4 (Litestream — revisit only if CAND-2+CAND-3 prove insufficient after a cycle), CAND-15 (textbook BM25 — gate on a hybrid-notebook-retrieval roadmap entry), CAND-12 (notebook tools — only if an agent action use-case appears), the full **SYSTEM_PROMPT authoring** (its own agent-harness track), and the **UI security audit** (its own E-series milestone, tracked via CAND-13's issue).

## 5. Honest limitations

- Each scout had a ~15-minute budget; the agent-facing MCP-resources direction (CAND-10) and the UI-security gap (CC-4) are under-explored relative to their potential importance.
- Triangulation across 5 briefs is strong but not infallible — CAND-7 (already-shipped) slipped through synthesis with only a `[VERIFY]` flag; the challenger caught it. Treat 1-source candidates (C=0.3: CAND-11/15/16/17/18) as lower-confidence.
- Effort is t-shirt → person-weeks; ±50% is the realistic ceiling. The two XS top-picks (CAND-2/3) score very high partly because RICE-light rewards tiny effort — that's a real signal ("do the cheap correctness fixes first") but don't read 28.8 vs 6.75 as "10× more important than the compose stack."
- The challenger judged against *current* architecture locks (loopback-only, pure-ASGI, no-anthropic-SDK, BP1/BP2). If `CLAUDE.md` conventions evolve (e.g. a sanctioned in-container bind), CAND-1's MAJOR softens further.
- Local-first was treated as a HARD constraint, so cloud/object-store options (MinIO/Garage/SeaweedFS, WebDAV, LiteFS) were parked, not scored — revisit only if a multi-device requirement emerges.

## 6. Cross-reference index

| Cand | comparative | research-frontier | oss-trends | multi-agent | adversary |
|---|---|---|---|---|---|
| CAND-1 docker-compose | C4 | C5 | 2.8/theme-4 | C4 | H1 |
| CAND-2 restic notebooks | — | C7 | 2.7 | — | H2 |
| CAND-3 sqlite FULL | C6(adj) | C1 | 2.1(adj) | — | — |
| CAND-4 Litestream | C6 | C3 | 2.1 | — | — |
| CAND-5 /status | C2 | C2 | 2.5 | — | M2 |
| CAND-6 make status+badge | C3/C7 | C6 | — | — | M2 |
| CAND-7 HEALTHCHECK (killed) | C8 | — | 2.8 | — | — |
| CAND-8 SSE ingest | C1/C9 | C6 | 2.3/2.4 | C2 | — |
| CAND-9 export | C5 | C8/C9 | — | — | — |
| CAND-10 MCP resources | — | — | — | C1/C7 | — |
| CAND-11 instructions/SYSTEM_PROMPT | — | — | — | C5 | — |
| CAND-12 notebook tools (killed) | — | — | — | C3/C6 | — |
| CAND-13 refresh constitution | theme | — | — | — | M1/L1/L2 |
| CAND-14 UI completion | C9/C10 | — | 2.9(adj) | — | M3 |
| CAND-15 textbook BM25 | — | — | — | — | M4 |
| CAND-16 Lance pin | — | C4 | — | — | — |
| CAND-17 operability contract | — | — | — | C8 | — |
| CAND-18 restic drill | — | C7 | 2.7 | — | — |

## Handoff offer

Seven candidates rank RICE ≥ 3.0 (CAND-2, CAND-3, CAND-6, CAND-1, CAND-16, CAND-18, CAND-5) — well above the threshold. The top cluster is ready to feed the `roadmap` skill as a source brief. To materialize as a roadmap with milestones:

    /roadmap notebook-ops-hardening --brief "$(head -200 .claude/notes/capability-scouts/2026q2-notebook-ux-storage-ops/artifacts/final-report.md)"

The roadmap skill will refine → decompose → sequence → materialize from this report, and its milestones (`notebook-ops-hardening-mN`) hand off to `/milestone-pipeline` for execution.

*(capability-scout does NOT auto-invoke `/roadmap` — offer-and-wait. You pick the cut.)*
