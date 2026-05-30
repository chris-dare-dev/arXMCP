# Notebook ops hardening (storage durability · operability · container packaging · UI completion) — Roadmap

**Slug:** `notebook-ops-hardening`
**Created:** 2026-05-28T21:04:26Z
**Status:** init

<!--
This roadmap is itself the state. Re-invoking the `roadmap` skill on
this file resumes from the first un-populated phase. Sections below
contain `{{TOKEN}}` placeholders until their phase runs.

Phases:
  1. REFINE     — How-Might-We, sharpening questions, assumptions, OKR, Won't list
  2. DECOMPOSE  — technique, epics, INVEST, specialist suggestions
  3. SEQUENCE   — MoSCoW, RICE, Now/Next/Later, spike lane, Now-lane milestones
  4. MATERIALIZE — validation results, optional GitHub bundle, next-step handoff
-->

---

## Phase 1 — Refine

<!-- populated by REFINE phase -->

### How Might We

How might we make a single local operator's notebooks **durable, portable, observable, and manageable** — and bring arXMCP's deployment story up to local-first parity — **without loosening any architecture lock** (local-first / loopback-only / pure-ASGI / no-anthropic-SDK-at-runtime / BP1 cache discipline)?

### Sharpening questions answered

1. **Is a new frontend needed, or completion of the existing one?** — Completion. A Jinja2+htmx notebook UI already ships (`server/routes/ui.py` + `frontend/templates/` + `/ui/api/notebooks/*`); the gap is per-paper ingest status, per-notebook freshness, in-page rename/delete, and a (separate) security audit — NOT a new SPA. The capability-scout flagged the "no frontend exists, by design" constitution claim as STALE.
2. **What's the biggest data-loss risk today?** — Two, both cheap to close: user-uploaded PDFs + `notebooks.db` are OUTSIDE the E14 restic backup scope (CAND-2), and `notebooks.db` ships `synchronous=NORMAL` — a documented power-loss commit-loss window on macOS (CAND-3, ~5 LOC). These were the scout's RICE #1/#2.
3. **What unblocks the storage/operability/packaging cluster?** — The base `docker-compose.yml` (CAND-1); six candidates gate on it. The challenger re-scoped it M→**server-only S** (the in-container bind carve-out already ships via `ARXMCP_UNSAFE_NETWORK_BIND`; the Dockerfile HEALTHCHECK is already present — CAND-7 killed).
4. **Cloud object storage (MinIO/S3) for notebooks?** — No. Local-first is a HARD constraint (CLAUDE.md §2/§8); MinIO/Garage/SeaweedFS/WebDAV/LiteFS are parked (AGPL and/or multi-host). Durability is restic + SQLite `synchronous=FULL` + bind-mounted volumes — self-hosted only.
5. **Does adding an agent/MCP surface for notebooks risk the BP1 cache?** — Use MCP **resources** (CAND-10, zero `tools/list`-byte / BP1 cost), NOT new MCP **tools** (CAND-12, which forces `EXPECTED_TOOL_SCHEMA_SHA256` + BP1 re-pins). The cache discipline is a forcing function toward resources for read-only corpus enumeration (cite `.claude/notes/07-multi-agent-caching.md`).

### Assumptions

- `[MUST]` The existing Jinja2+htmx UI + the FastAPI `/ui/api` are the frontend foundation — this cycle COMPLETES it, never replaces it with an SPA/Node build chain. (If wrong, the whole "complete the UI" framing changes.)
- `[MUST]` The architecture locks hold for every candidate — local-first, loopback-only (`server/config.py::reject_non_loopback`), pure-ASGI (`BaseHTTPMiddleware` banned), no `anthropic` SDK at runtime, BP1/BP2 byte-stability. Cloud storage is out. (Dealbreaker — the challenger judged every candidate against these.)
- `[MUST]` A docker-compose stack can bind-mount `var/arxmcp/` on the operator's machine — INCLUDING macOS Docker Desktop — without an unworkable uid/gid ownership problem. (The challenger flagged macOS uid/gid friction; this needs a SEQUENCE-phase spike before the compose milestone is sized.)
- `[SHOULD]` The E14 restic mechanism extends cleanly to the notebook paths + `notebooks.db` (an include-path + restore-drill change, not a re-architecture). Fallback: a standalone `make backup-notebooks` if the shared wrapper resists extension.
- `[SHOULD]` `synchronous=FULL` + `fullfsync=ON` on the low-write `notebooks.db` has negligible perf impact. Fallback: scope it to the durable notebook store only, leave the regenerable Tier-1 cache at `NORMAL`.
- `[MIGHT]` MCP `resources/subscribe` has enough harness support to ship now (vs `list`/`read` only — the multi-agent scout noted harness support lags the spec ~3–6 months).
- `[MIGHT]` SSE ingest progress is worth a new dependency over the existing (working) htmx-286 polling — the challenger judged it marginal for a single operator.

### Objective

Give a single local operator durable, portable, observable, and manageable notebooks with a one-command containerized deployment — closing the capability-scout's two HIGH gaps (no notebook backup; no compose stack) and the operability/UX gaps — while holding every arXMCP architecture lock and the BP1 cache discipline.

### Key Results

1. A backup/restore drill recovers a notebook — including its user-uploaded PDFs AND `notebooks.db` metadata — byte-for-byte, verified by a restore-drill regression test, by end of cycle.
2. `notebooks.db` commits survive a simulated power-loss: `synchronous=FULL` + `fullfsync=ON` are set and pinned by a regression test asserting the pragmas on the durable connection(s).
3. `docker compose up` brings the server to a `/readyz`-healthy state on a clean checkout with a bind-mounted `var/arxmcp/`, documented end-to-end in `docs/install.md` (incl. the macOS uid/gid pre-step).
4. An operator answers "is it running + ready?" in one action: `make status` prints a human summary AND the `/ui/` shell shows a live status badge — both fed by a new `/status` JSON endpoint; no new architecture lock loosened.
5. The notebook UI shows per-paper ingest status + per-notebook "last indexed" freshness and supports in-page rename/delete; the design constitution no longer claims "no frontend exists," and a UI-security-audit issue is filed (tracked, not executed this cycle).

### Won't (explicit out-of-scope)

- Cloud / S3 / multi-host / multi-device sync (MinIO, Garage, SeaweedFS, WebDAV, LiteFS) — violates local-first.
- A SPA (React/Vue/Svelte) or any Node build chain — htmx + Jinja2 (+ Alpine.js only for the drag-drop upload card) is the chosen stack.
- Authoring the full `SYSTEM_PROMPT` placeholder (CLAUDE.md gotcha 6) — an agent-harness policy track of its own; ONLY the static MCP `initialize.instructions` field is in scope (zero BP1 cost).
- Notebook-management MCP **tools** (read-only `list_notebooks`/`get_notebook_status`) — superseded by MCP **resources** at zero BP1 cost; action-tools deferred until a concrete agent use-case appears.
- Litestream continuous WAL replication — deferred until restic + `synchronous=FULL` prove insufficient after a cycle.
- Textbook-notebook BM25 index — deferred until hybrid notebook retrieval is roadmapped (dead code otherwise, per m12 D1).
- The UI security audit itself (XSS/CSP/template-injection/htmx) — this cycle FILES the tracked issue; the audit is its own future E-series milestone.
- A desktop tray / Electron / Tauri status indicator — the `make status` + UI badge cover the need for a headless server.

---

## Phase 2 — Decompose

<!-- populated by DECOMPOSE phase -->

### Technique

**Vertical slicing + enabler stories.** Each epic is a coherent operator- or agent-facing outcome cutting through storage / server / UI / packaging as needed, mirroring the capability-scout's candidate clusters. (Rejected by-layer slicing — it would scatter one outcome across many epics and bury the user-visible value.)

### Epics

#### notebook-ops-hardening-e1 — Notebooks survive power loss and a disk wipe

- **Type:** enabler
- **Specialist suggestion:** `security-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md` (data durability + the macOS `fullfsync` territory).
- **Outcome:** A backup/restore drill recovers a notebook (uploaded PDFs + `notebooks.db` metadata) byte-for-byte; committed notebook writes survive a simulated power loss. Closes the scout's two storage gaps (CAND-2 restic-scope, CAND-3 SQLite `synchronous=FULL`) + the hardening pair (CAND-16 Lance format pin, CAND-18 restic retention/drill).
- **Estimated size:** S (the cluster is four XS fixes; the scout's RICE #1/#2 live here).
- **INVEST check:** I clean (host-level backup + SQLite pragmas, no dep on other epics); N clean; V clean (enabler — durability surfaces as operator confidence); E clean (scout-scoped); S clean (≤1wk); T clean (restore-drill test + a pragma-assert test).
- **Dependencies:** none.
- **Won't conflict check:** none (no cloud/Litestream — those are explicitly Won't; this epic is restic + SQLite pragmas + a version pin only).

#### notebook-ops-hardening-e2 — One command brings the stack up healthy

- **Type:** enabler
- **Specialist suggestion:** `security-reviewer` — container hygiene (non-root, loopback bind, no secrets). NOTE: `milestone-infra-safety` auto-fires on compose/Dockerfile/Makefile paths in milestone-pipeline.
- **Outcome:** `docker compose up` brings the server to a `/readyz`-healthy state on a clean checkout with a bind-mounted `var/arxmcp/`, documented in `install.md` incl. the macOS uid/gid pre-step (CAND-1, server-only v0). The ingest service + Litestream sidecar are explicitly deferred to a v1 increment.
- **Estimated size:** S (challenger re-scoped M→S: the `ARXMCP_UNSAFE_NETWORK_BIND` carve-out + the Dockerfile HEALTHCHECK already ship).
- **INVEST check:** I clean (the compose file is self-contained; consumes the existing Dockerfile + `/readyz`); N clean; V clean (enabler — reproducible deploy); E borderline (the macOS uid/gid bind-mount behavior is the unvalidated assumption — see the SEQUENCE spike); S clean (≤1wk for server-only); T clean (`docker compose up` → `/readyz` 200 is the test).
- **Dependencies:** none hard (the ingest-service v1 increment would depend on a `Dockerfile.ingest`, deferred).
- **Won't conflict check:** none (Litestream + ingest-service are deferred, not in v0).

#### notebook-ops-hardening-e3 — The operator can see at a glance that the server is ready

- **Type:** value
- **Specialist suggestion:** `—` (plain HTTP `/status` + Makefile + a Jinja2 badge; the milestone-pipeline adversary suffices).
- **Outcome:** `make status` prints a human "READY | embedder warm | corpus v7 | 3 notebooks" line AND the `/ui/` shell renders a live status badge — both fed by a new `/status` JSON endpoint (IETF `health+json` superset of `/readyz`). Directly answers the operator's "is it running?" (CAND-5 + CAND-6).
- **Estimated size:** S.
- **INVEST check:** I clean (independent of e1/e2; `/status` reads existing `Resources` state); N clean; V clean (operator-visible); E clean; S clean; T clean (assert `/status` JSON shape + a `make status` smoke test).
- **Dependencies:** none (works bare-metal; the badge benefits the e4 UI but doesn't require it).
- **Won't conflict check:** none.

#### notebook-ops-hardening-e4 — Notebooks are fully manageable from the browser

- **Type:** value
- **Specialist suggestion:** `security-reviewer` — the Jinja2/htmx UI surface was never security-audited (E13 scoped it out); any UI change touches an un-audited surface.
- **Outcome:** The notebook UI shows per-paper ingest status + a per-notebook "last indexed / never indexed" freshness signal and supports in-page rename/delete; the design constitution no longer claims "no frontend exists," and a UI-security-audit issue is filed (CAND-14 + CAND-13). Adds an `Alpine.js`-only drag-drop polish if cheap.
- **Estimated size:** S.
- **INVEST check:** I clean (additive `notebooks.db` migration v4→v5 + template + a `PATCH` route); N clean; V clean (the "manage my notebooks" UX the operator asked for); E clean; S clean; T clean (status-column render + rename/delete handler tests). Cross-cut: shares the ingest-status plumbing with e5/e3.
- **Dependencies:** soft on e3 (the status badge) — not hard; can ship independently.
- **Won't conflict check:** none — this is UI completion + a doc refresh + a *filed* security issue; the audit itself is Won't (separate milestone).

#### notebook-ops-hardening-e5 — The agent can discover and move notebooks without the human UI

- **Type:** value
- **Specialist suggestion:** `mcp-protocol-reviewer` + `cache-stability-reviewer` — confirm MCP resources don't drift `tools/list` bytes / BP1.
- **Outcome:** Notebooks become first-class MCP resources (`arxmcp://notebooks/<slug>`, `resources/list`/`read`) so a pipeline agent can enumerate corpora at ZERO BP1 cost (CAND-10); a static MCP `initialize.instructions` orients connecting agents (CAND-11 v0); and `GET /ui/api/notebooks/{slug}/export` streams a portable tar+manifest (CAND-9).
- **Estimated size:** M (the resources capability + handlers is the largest single piece; export + instructions are S each).
- **INVEST check:** I clean (additive MCP capability + a route; no change to the 7-tool surface); N clean; V clean (agent-facing + portability); E clean; S clean (≤3wk); T clean (resources/list returns notebooks; export round-trips; BP1 hash UNCHANGED is the load-bearing assertion).
- **Dependencies:** none hard (independent of e1–e4; export benefits from e1's durability framing but doesn't require it).
- **Won't conflict check:** none — uses MCP **resources** (not the Won't-listed notebook **tools**) and the **instructions** field (not the Won't-listed full `SYSTEM_PROMPT`).

---

## Phase 3 — Sequence

<!-- populated by SEQUENCE phase -->

### MoSCoW assignment

`score-moscow.py` → **Must = 46.2% (≤ 60% cap) — OK.**

- **Must** (≤ 60% of total effort): `e1-storage-durability`, `e2-docker-compose`, `e3-operability` (3.0pm / 6.5pm = 46.2%)
- **Should**: `e4-ui-completion` (1.0pm)
- **Could**: `e5-agent-surface` (2.5pm)
- **Won't (this cycle)**: — (the REFINE Won't list governs scope-out: cloud storage, SPA, full SYSTEM_PROMPT, notebook MCP tools, Litestream, textbook BM25, the UI security audit itself)

Rationale: the two HIGH scout gaps (notebook backup, no compose) + the cheap operability surface are the dealbreakers for "durable + observable + deployable notebooks." UI completion (e4) enhances manageability but the existing UI already works — Should, not Must. Agent-facing/export (e5) is the lowest-RICE, harness-lag-bound bonus — Could. Promoting e4 to Must would breach the cap (62%).

### RICE ranking — Musts

| ID | Reach | Impact | Confidence | Effort | Score |
|---|---:|---:|---:|---:|---:|
| e1-storage-durability | 3 | 3.00 | 80% | 1.00 | 7.2 |
| e2-docker-compose | 3 | 2.00 | 50% * | 1.00 | 3.0 |
| e3-operability | 3 | 1.00 | 80% | 1.00 | 2.4 |

_`*` e2's confidence is defaulted to 50% — the compose's NEED is 5-brief-triangulated, but its EXECUTION hinges on the unvalidated macOS Docker-Desktop bind-mount uid/gid behavior. `notebook-ops-hardening-spike-1` (below) validates it before m3 is built._

### Now / Next / Later

- **Now** (fully spec'd): `e1-storage-durability`, `e2-docker-compose`, `e3-operability` → milestones m1–m4 below.
- **Next** (shaped, awaiting capacity): `e4-ui-completion` (per-paper ingest status + freshness + htmx rename/delete + constitution refresh + filed UI-security-audit issue).
- **Later** (outcome-only, low-confidence horizon): `e5-agent-surface` (notebooks as MCP resources + static `initialize.instructions` + tar export; gated on harness `resources/subscribe` support maturing).

### Spike / discovery lane

- `notebook-ops-hardening-spike-1` — On the operator's machine (macOS Docker Desktop), confirm `docker compose up` with a **bind-mounted** `var/arxmcp/` writes cleanly as the in-image non-root UID 1000 with no ownership failure; document the `chown -R 1000:1000 var/arxmcp` pre-step (or a fix) (≤ 1 day, validates `[MUST]`: "a docker-compose stack can bind-mount `var/arxmcp/` on macOS without an unworkable uid/gid problem"). **Gates m3.**

_The other two `[MUST]` assumptions need no discovery spike: "the existing Jinja2+htmx UI is the foundation" is validated-by-inspection (the UI demonstrably ships at `server/routes/ui.py`), and "the architecture locks hold" is a standing constraint already enforced by the test suite + the milestone-pipeline challenger (not a discovery item)._

### Milestones — Now lane

<!--
Each Now-lane milestone is its own H3 below. Heading format is
`### <slug>-mN — Title` exactly — milestone-pipeline's init-state.sh
greps for this. Do not change it.
-->

### notebook-ops-hardening-m1 — Notebook data + metadata enter the restic backup scope

**Description.** Extend the E14 restic backup include-path to cover `var/arxmcp/notebooks/` (per-notebook LanceDB + parsed HTML + **user-uploaded PDFs**) and `var/arxmcp/cache/notebooks.db` (notebook metadata), distinguishing non-regenerable user data from regenerable retrieval caches. Formalize the retention policy + a `check --read-data-subset` rotation and extend the restore drill to verify a notebook round-trips. (CAND-2 + CAND-18.)

**Acceptance criteria.**
- [ ] The restic include-list (a `--files-from-verbatim -` manifest) covers `var/arxmcp/notebooks/` and `var/arxmcp/cache/notebooks.db`; regenerable caches stay excluded with a comment.
- [ ] Retention policy specified: `--keep-daily 7 --keep-weekly 4 --keep-monthly 12`; the drill runs `check --read-data-subset=5%`.
- Given a notebook with an uploaded PDF + metadata, When a backup→wipe→restore cycle runs, Then the notebook (PDF + `notebooks.db` row) is recovered byte-for-byte — asserted by a restore-drill regression test.
- [ ] `08-security-observability-ops.md` backup section + the ops note updated to list the notebook paths.

**Dependencies.** `e1-storage-durability`; none prior.

**Complexity.** M (1–3 days).

**Specialist suggestion.** `security-reviewer` (data durability / backup correctness). `milestone-infra-safety` auto-fires if the restic wrapper lives under `infra/`/`Makefile`.

### notebook-ops-hardening-m2 — Notebook commits survive power loss; LanceDB format is pinned

**Description.** Set `PRAGMA synchronous=FULL` + `PRAGMA fullfsync=ON` on the durable `notebooks.db` connection(s) so a committed write survives an OS crash / power loss (the default `NORMAL` + macOS's neutered `fsync` can roll back the last commit). Separately, pin the LanceDB on-disk `data_storage_version` on dataset writes so a `uv`/`pip` upgrade can't silently migrate the format to a version the pinned reader can't decode. (CAND-3 + CAND-16.)

**Acceptance criteria.**
- [ ] `server/notebooks_store.py` opens its durable connection(s) with `synchronous=FULL` + `fullfsync=ON`; a regression test asserts both pragmas (the regenerable Tier-1 cache `cache_sqlite.py` may stay `NORMAL` — decision recorded).
- [ ] LanceDB dataset writes (`ingest/store.py`, `tools/_notebook_common.py`) pass an explicit `data_storage_version`; `pyproject.toml` carries a pin-rationale comment. (First VERIFY the LanceDB default write version.)
- Given the notebook store after a committed write, When the connection's pragmas are read back, Then `synchronous == 2 (FULL)` and `fullfsync == 1`.

**Dependencies.** `e1-storage-durability`; independent of m1.

**Complexity.** S (≤ 1 day).

**Specialist suggestion.** `cache-stability-reviewer` + `determinism-reviewer` (SQLite/LanceDB durability + format determinism).

### notebook-ops-hardening-m3 — `docker compose up` brings the server up healthy

**Description.** Ship `infra/docker-compose.yml` (server-only v0) mirroring the `infra/observability/phoenix-compose.yml` template: build `docker/Dockerfile.server`, bind `127.0.0.1:7733:7733`, bind-mount `var/arxmcp/`, `cap_drop:[ALL]`, `@sha256` base-image pins, reuse the existing `/readyz` HEALTHCHECK, set `ARXMCP_UNSAFE_NETWORK_BIND=1` for the in-container bind. Document the end-to-end flow + the macOS uid/gid pre-step in `docs/install.md`. The ingest service + Litestream sidecar are explicitly deferred to a v1 increment. (CAND-1; CAND-7 confirmed already-shipped, folded in as a pre-verified prerequisite.)

**Acceptance criteria.**
- Given a clean checkout with a bind-mounted `var/arxmcp/`, When `docker compose up` runs, Then `GET http://127.0.0.1:7733/readyz` returns 200 once BGE-M3 + LanceDB are warm (compose `service_healthy` gate honored).
- [ ] No `0.0.0.0` exposed host-side; loopback bind only; non-root UID; `docs/install.md` documents the macOS `chown -R 1000:1000 var/arxmcp` pre-step (per spike-1).
- [ ] A test inspects the compose/middleware stack to assert the prefix loopback binding (no live 201 MB upload needed).

**Dependencies.** `e2-docker-compose`; **gated on `notebook-ops-hardening-spike-1`**.

**Complexity.** M (1–3 days).

**Specialist suggestion.** `security-reviewer` (container hygiene). `milestone-infra-safety` auto-fires (compose/Dockerfile/Makefile paths).

### notebook-ops-hardening-m4 — "Is it running + ready?" answerable in one action

**Description.** Add a `GET /status` JSON endpoint (an IETF `application/health+json` superset of `/readyz`: `status: pass|warn|fail` + per-component `checks` for embedder/LanceDB/disk/last-backup + `corpus_version` + notebook count + uptime; degraded → `warn` 2xx, while `/readyz` keeps its 503-on-degraded probe semantics). Add a `make status` target that curls it and prints a human line, and a live htmx-polled status badge in the `/ui/` shell footer/header. (CAND-5 + CAND-6.)

**Acceptance criteria.**
- Given the server warm, When `GET /status` is called, Then it returns a `health+json` body with `status:"pass"`, `corpus_version`, notebook count, and per-component checks.
- [ ] `make status` prints a human summary (`READY | embedder warm | corpus v7 | 3 notebooks`) parsed from `/status`.
- [ ] `frontend/templates/base.html` renders a `<span hx-get="/status" hx-trigger="load, every 10s">` badge (ready/degraded/down); CSP permits it.
- [ ] `/readyz` 503-on-degraded behavior is unchanged (only `/status` adopts `warn` 2xx).

**Dependencies.** `e3-operability`; none prior (the badge is additive to the existing UI).

**Complexity.** M (1–3 days).

**Specialist suggestion.** `—` (plain HTTP + Makefile + Jinja2; the milestone-pipeline adversary suffices). NOTE: the badge touches the un-audited UI surface flagged in e4/CAND-13.

---

## Phase 4 — Materialize

<!-- populated by MATERIALIZE phase -->

### Validation

- `validate-roadmap.py`: pass
- Must-cap: 46.2% (≤ 60%) — `score-moscow.py` OK
- All Now-lane milestones have AC: yes (m1–m4 each carry G/W/T + bullet AC)
- Slug format valid: yes (`notebook-ops-hardening` matches `^[a-z][a-z0-9-]{2,30}$`, not `^e\d+$`)

### GitHub tickets

Not requested (run the skill with `--github` to bundle epic + story bodies under `plans/notebook-ops-hardening-tickets/` + a `create-tickets.sh`). Consistent with arXMCP's single-user, direct-to-`main` workflow — milestones execute via `/milestone-pipeline`, not via GitHub issues. (The one external-write follow-up this roadmap produces is the **UI-security-audit issue** filed inside `notebook-ops-hardening-m?`/e4 when e4 enters Now — that's a per-event `gh issue create` gated in milestone-pipeline Phase 4, not a roadmap ticket bundle.)

### Next step

First Now-lane milestone: `notebook-ops-hardening-m1` (extend restic backup to notebook data — the scout's RICE #1, an XS clean win). To execute it end-to-end:

    /milestone-pipeline notebook-ops-hardening-m1

Recommended Now-lane execution order (by RICE + dependency):
1. `notebook-ops-hardening-m2` — SQLite `synchronous=FULL` + Lance pin (XS, no deps; the cheapest correctness win — arguably do first).
2. `notebook-ops-hardening-m1` — restic backup scope + restore drill (no deps).
3. `notebook-ops-hardening-spike-1` — macOS bind-mount uid/gid (≤1 day) — **before** m3.
4. `notebook-ops-hardening-m3` — base docker-compose server-only v0 (gated on spike-1).
5. `notebook-ops-hardening-m4` — `/status` + `make status` + UI badge.

This skill will NOT invoke milestone-pipeline. Cache stays warmer if you start the milestone-pipeline session within ~5 minutes. (e4 UI-completion / e5 agent-surface are Next/Later — re-run `/roadmap notebook-ops-hardening` when they enter Now to spec their milestones.)

---

<!-- end:roadmap -->
