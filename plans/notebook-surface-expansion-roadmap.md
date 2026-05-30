# Notebook surface expansion (UI completion + agent surface) — Roadmap

**Slug:** `notebook-surface-expansion`
**Created:** 2026-05-29T15:14:27Z
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

### How Might We

How might we let an operator fully manage notebooks in the browser AND let a
Claude pipeline agent discover + move notebooks programmatically — for a
single-workstation operator and their sketcher→autoformalizer→tactician→fixer
pipeline — WITHOUT introducing an SPA/Node build chain and WITHOUT drifting the
frozen 7-tool surface or the BP1/BP2 prompt-cache hashes?

### Sharpening questions answered

1. **New frontend, or completion of the existing one?** — Completion. A
   server-rendered Jinja2+htmx notebook UI already ships (`server/routes/ui.py`
   + `frontend/templates/{base,index,notebook_detail}.html` + the REST surface
   `server/routes/notebooks.py` at `/ui/api/notebooks/*`, plus the m4
   `/ui/status-badge`). The gap is per-paper ingest status, per-notebook
   freshness, in-page rename/delete, and a constitution refresh — NOT a new SPA.
   The capability-scout flagged the "no frontend exists, by design" claim in
   `06-mcp-server-design.md` / `CLAUDE.md` as STALE.
2. **How does the agent surface (e5) avoid touching the 7-tool / BP1 surface?**
   — Via MCP **resources** (`resources/list` + `resources/read`) and the
   `initialize.instructions` field — neither lives in `server/tools.py::ALL_TOOLS`
   nor the `tools/list` wire response, so `EXPECTED_TOOL_SCHEMA_SHA256` and
   `EXPECTED_BP1_SHA256` stay byte-identical. This byte-stability is the
   load-bearing constraint (`07-multi-agent-caching.md`).
3. **Is the UI security audit in scope?** — No. The Jinja2/htmx surface was
   never security-audited (E13 scoped it out). This cycle FILES a tracked
   UI-security-audit issue; it does NOT execute the audit. Any e4 UI change
   still gets the `security-reviewer` lens during its milestone critique.
4. **Does in-page rename need a `notebooks.db` schema migration?** — Open.
   `notebooks_store.py` already persists `display_name` (created in the v1
   schema), so rename is likely an `UPDATE display_name`, not a destructive
   change. If a new column IS needed, an additive `SCHEMA_VERSION` v4→v5
   migration suffices. The implementer verifies against the live schema first.
5. **Does the harness consume MCP resources today?** — `resources/list` +
   `resources/read` are standard in MCP 2025-06-18 and usable now;
   `resources/subscribe` (live push) is the maturing bit. e5 v0 ships
   list+read + a static instructions string + tar export — none requires
   subscribe.

### Assumptions

- `[MUST]` The existing Jinja2+htmx UI + the FastAPI `/ui/api/notebooks/*` REST
  surface are the frontend foundation — this cycle COMPLETES them, never
  replaces them with an SPA / Node / npm / Vite build chain. (If wrong, the
  whole "complete the UI" framing changes.)
- `[MUST]` MCP `resources/list` + `resources/read` + the `initialize.instructions`
  field can expose notebooks to agents WITHOUT changing `ALL_TOOLS`, the
  `tools/list` bytes, or the `EXPECTED_TOOL_SCHEMA_SHA256` / `EXPECTED_BP1_SHA256`
  hashes. (If wrong, e5 cannot ship without breaking the prompt-cache contract —
  this needs a SEQUENCE-phase spike to PROVE the hashes are byte-unchanged.)
- `[SHOULD]` `notebooks.db` already carries a `display_name` column, so rename is
  an `UPDATE` (no destructive migration); a v4→v5 additive migration is the
  fallback if a new column is required.
- `[SHOULD]` The Claude Code harness consumes `resources/list`+`read` today;
  `resources/subscribe` maturity is NOT required for the e5 v0 value (list+read +
  static instructions + export).
- `[MIGHT]` A vendored-Alpine (or htmx-only) drag-drop polish is cheap enough to
  fold into e4 without any build chain; if not, it is dropped.

### Objective

Make notebooks fully manageable by a human in the browser and fully discoverable
+ portable by a pipeline agent — completing both the operator UI and the
agent-facing MCP surface — without a build chain and without disturbing the
frozen tool-schema / prompt-cache contract.

### Key Results

1. The notebook-detail page shows a per-paper ingest/parse-status column + a
   per-notebook "last indexed / never indexed" freshness signal, and supports
   in-page rename + delete — all via htmx, no SPA — asserted by UI-render +
   handler tests.
2. The design constitution no longer claims "no frontend exists, by design"
   (`06-mcp-server-design.md` + `CLAUDE.md` updated) and a UI-security-audit
   issue is FILED at `chris-dare-dev/arXMCP` (tracked, not executed).
3. `resources/list` returns every notebook as `arxmcp://notebooks/<slug>` and
   `resources/read` returns its metadata, with `EXPECTED_TOOL_SCHEMA_SHA256` AND
   `EXPECTED_BP1_SHA256` BYTE-UNCHANGED (the load-bearing regression assertion).
4. `GET /ui/api/notebooks/{slug}/export` streams a tar + manifest that
   round-trips (export → fresh dir → restore → notebook readable), asserted by a
   test.
5. A static MCP `initialize.instructions` string orients a connecting agent
   (present in the `initialize` response; asserted), with the BP1/BP2 hashes
   still byte-unchanged.

### Won't (explicit out-of-scope)

- A new SPA or any Node / npm / Vite / build-chain frontend.
- Cloud / object storage for notebooks (local-first contract).
- Authoring the full `SYSTEM_PROMPT` (only the static `initialize.instructions`
  field).
- Notebook MUTATION via MCP tools — resources are READ-ONLY; the 7-tool surface
  stays frozen.
- Litestream / streaming SQLite replication.
- EXECUTING the UI security audit (it is FILED as an issue this cycle, not done).
- `resources/subscribe` live-update wiring (v0 is list+read; subscribe deferred
  until harness support matures).

---

## Phase 2 — Decompose

### Technique

Vertical slicing, sliced by **surface/actor + risk boundary**. The two source
epics map to distinct audiences (operator browser UI vs pipeline-agent MCP
surface); the agent half splits again along its risk boundary — the
BP1-byte-stability-sensitive *discovery* capability (MCP resources + instructions)
vs the streaming *portability* capability (tar export). Each slice ships
independent operator- or agent-visible value.

### Epics

#### notebook-surface-expansion-e1 — Operator manages notebooks end-to-end in the browser

- **Type:** value
- **Specialist suggestion:** `security-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md`. The Jinja2/htmx UI surface was never security-audited (E13 scoped it out); rename/delete add mutation handlers that need input-validation review.
- **Outcome:** The notebook-detail page shows a per-paper ingest/parse-status column + a per-notebook "last indexed / never indexed" freshness signal and supports in-page rename + delete via htmx; `06-mcp-server-design.md` + `CLAUDE.md` no longer claim "no frontend exists, by design"; and a UI-security-audit issue is FILED (CAND-13/CAND-14). Optional vendored/htmx-only drag-drop polish if it adds no build chain.
- **Estimated size:** S
- **INVEST check:** I clean (additive templates + a PATCH route + at most a `notebooks.db` v4→v5 additive migration; reads existing parse_tracker state); N clean; V clean (the "manage my notebooks" UX the operator asked for); E clean; S clean (≤ 1 wk); T clean (status-column render + rename/delete handler tests). Cross-cut: shares the ingest-status plumbing read by e2, but no hard dependency.
- **Dependencies:** none (the m4 status badge already shipped; this is additive to the existing UI).
- **Won't conflict check:** none — UI completion + a doc refresh + a *filed* security issue; the audit itself is on the Won't list (separate future milestone).

#### notebook-surface-expansion-e2 — A pipeline agent discovers notebooks at zero BP1 cost

- **Type:** value
- **Specialist suggestion:** `mcp-protocol-reviewer` + `cache-stability-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md`. The resources capability touches the MCP transport surface; byte-stability of `tools/list` + BP1/BP2 is the load-bearing constraint.
- **Outcome:** Notebooks become first-class MCP **resources** (`arxmcp://notebooks/<slug>`, `resources/list` + `resources/read`) so a sketcher→autoformalizer→tactician→fixer agent can enumerate available corpora at ZERO BP1 cost (CAND-10), and a static MCP `initialize.instructions` string orients a connecting agent (CAND-11 v0). The frozen 7-tool surface, `tools/list` wire bytes, and `EXPECTED_TOOL_SCHEMA_SHA256` / `EXPECTED_BP1_SHA256` stay byte-identical.
- **Estimated size:** M
- **INVEST check:** I clean (additive MCP capability + a static field; no change to the 7-tool surface); N clean; V clean (agent-facing discovery); E clean; S clean (≤ 3 wk; the resources capability + handlers is the larger piece, instructions is S); T clean (`resources/list` returns notebooks; `resources/read` returns metadata; BP1 + tool-schema hashes UNCHANGED is the load-bearing assertion). Borderline **I**: must prove the FastMCP resources capability does not perturb the `initialize`/`tools/list` bytes — a spike de-risks this.
- **Dependencies:** none hard (independent of e1/e3).
- **Won't conflict check:** none — uses MCP **resources** (not the Won't-listed notebook **tools**) + the **instructions** field (not the Won't-listed full `SYSTEM_PROMPT`). `resources/subscribe` is explicitly deferred (Won't).

#### notebook-surface-expansion-e3 — A notebook is portable (export → restore round-trips)

- **Type:** value
- **Specialist suggestion:** `security-reviewer` + `determinism-reviewer` — see `.claude/skills/roadmap/references/specialist-contracts.md`. Export touches a new streaming route (slug path-traversal validation; what bytes the tar includes/excludes — no secret leakage) and a manifest whose shape should be deterministic/round-trippable.
- **Outcome:** `GET /ui/api/notebooks/{slug}/export` streams a portable tar + manifest of one notebook (PDFs + parsed HTML + the `notebooks.db` rows for that slug + a manifest) for backup/move (CAND-9); the bundle round-trips (export → fresh dir → restore → notebook readable).
- **Estimated size:** S
- **INVEST check:** I clean (one streaming GET route + a manifest builder; reuses `_notebook_common` paths); N clean; V clean (portability/backup the operator + agent both benefit from); E clean; S clean (≤ 1 wk); T clean (export round-trip test; slug-traversal rejection test). Benefits from e1's durability framing but does not require it.
- **Dependencies:** none hard (independent of e1/e2).
- **Won't conflict check:** none — local tar to the response stream; no cloud/object storage (Won't), no Litestream (Won't).

---

## Phase 3 — Sequence

### MoSCoW assignment

`score-moscow.py` → **Must = 22.2% (≤ 60% cap) — OK.**

- **Must** (≤ 60% of total effort): `e1` UI completion (1.0pm / 4.5pm = 22.2%)
- **Should**: `e2` agent discovery surface (2.5pm)
- **Could**: `e3` portability export (1.0pm)
- **Won't (this cycle)**: — (the REFINE Won't list governs scope-out: SPA/Node
  chain, cloud storage, full SYSTEM_PROMPT, notebook mutation tools, Litestream,
  `resources/subscribe`, and executing the UI security audit)

Rationale: of the operator's four original capability-scout asks — frontend,
storage, is-it-running, containers — three shipped in the notebook-ops-hardening
Now-lane (m1/m2 storage, m3 containers, m4 is-it-running). The frontend
completion (e1) is the LAST directly-requested operator gap → the only Must. The
agent-facing surface (e2) + portability (e3) were scout-discovered bonuses the
pipeline functions without → Should / Could. Promoting e2 to Must would breach
the cap (78%) and invert the requested-vs-discovered value order.

### RICE ranking — Musts

| ID | Reach | Impact | Confidence | Effort | Score |
|---|---:|---:|---:|---:|---:|
| notebook-surface-expansion-e1 | 10 | 3.00 | 90% | 1.00 | 27.0 |

_No `*` — e1's confidence is evidenced (the UI ships; the parse-status +
ingest-run + display_name plumbing all exist in `notebooks_store.py`), so no
spike is needed for the e1 `[MUST]` (validated by inspection)._

### Now / Next / Later

- **Now** (fully spec'd):
  - `e1` — decomposed into m1/m2/m3 below. **SHIPPED** (m1 `934ecba`, m2 `d073c0a`,
    m3 `23b61d3`; UI-security-audit issue filed at `chris-dare-dev/arXMCP#9`).
  - `e2` — agent discovery (MCP resources + `initialize.instructions`).
    **SHIPPED** (m4 `ed8b69e`, m5 `85077ca`; tool-schema/BP1 hashes byte-identical
    throughout, per `spike-1`). MoSCoW priority was **Should** (a scout-discovered
    bonus); "Now" was a scheduling lane, not a Must reclassification.
  - `e3` — notebook tar+manifest export/portability. **PROMOTED Later → Now
    (2026-05-29)** — the last remaining epic; decomposed into m6/m7 below. No spike
    needed (validated by inspection — a streaming GET + a manifest builder + a CLI
    restore; no byte-stability gate — `/ui/api/*` is disjoint from the MCP surface).
    MoSCoW priority stays **Could** (portability is a scout-discovered backup/move
    bonus); "Now" is the scheduling lane.
- **Next** (shaped, awaiting capacity): — (none).
- **Later** (outcome-only): — (none; e3 advanced to Now — all three epics scheduled).

### Spike / discovery lane

- `notebook-surface-expansion-spike-1` — Build a throwaway prototype that
  registers notebooks as MCP resources (`resources/list`/`read`) + sets a static
  `initialize.instructions`, then assert `EXPECTED_TOOL_SCHEMA_SHA256` AND
  `EXPECTED_BP1_SHA256` are BYTE-UNCHANGED vs the frozen baseline (and that
  `tools/list` is byte-identical). (≤ 3 days, validates `[MUST]`: "MCP resources
  + the instructions field expose notebooks WITHOUT drifting the tool-schema /
  BP1 hashes".) **Gates e2.** The other `[MUST]` (existing UI is the foundation)
  is validated-by-inspection — the UI demonstrably ships at `server/routes/ui.py`
  — so it needs no discovery spike.
  - **RESOLVED 2026-05-29 → GO.** A throwaway FastMCP (`mcp 1.27.x`) prototype
    proved a concrete `arxmcp://notebooks/demo` resource + a
    `arxmcp://notebooks/{slug}` template + a set `instructions=` leave the
    `tools/list` SHA-256 **byte-identical** to `EXPECTED_TOOL_SCHEMA_SHA256`, and
    `EXPECTED_BP1_SHA256` is structurally orthogonal (BP1 = the orchestrator's
    `SYSTEM_PROMPT + ALL_TOOLS`; zero coupling to the MCP `initialize` response).
    Both gates green on main. Also confirmed: FastMCP 1.27.x advertises
    `capabilities.resources.subscribe=False`, so `resources/list`+`read` is
    buildable now and `resources/subscribe` stays deferred; and the surface is
    **8 tools** (not 7 — `lean_verify`). Full evidence + e2 wiring guidance +
    residual risks: `.claude/notes/spikes/notebook-surface-expansion-spike-1.md`
    (commit `9ac322a`). **e2 unblocked → promoted to the Now lane below.**

### Milestones — Now lane

### notebook-surface-expansion-m1 — Notebook detail page shows per-paper ingest status + per-notebook freshness

**Description.** Add a per-paper parse/ingest STATUS column to the
notebook-detail page (`frontend/templates/notebook_detail.html` +
`server/routes/ui.py::ui_notebook_detail`), reusing the existing
`parse_status` on the `notebook_papers` rows (`list_papers`) and the
`GET /ui/api/notebooks/{slug}/parse-status` route, plus a per-notebook
"last indexed `<ts>` / never indexed" freshness line from
`NotebooksStore.get_latest_ingest_run`. Read-only display — NO `notebooks.db`
schema change.

**Acceptance criteria.**
- Given a notebook whose papers have mixed `parse_status`, When the operator
  opens `/ui/notebooks/{slug}`, Then each paper row shows its parse status
  (pending / parsing / parsed / failed / skipped) and the page shows a "last
  indexed `<ts>`" or "never indexed" freshness signal.
- [ ] Template + `ui_notebook_detail` annotate rows with `parse_status` + the
  latest ingest-run timestamp; no schema migration.
- [ ] A UI-render test (TestClient + a seeded `notebooks.db`, no model load)
  asserts the status column + the freshness signal render.

**Dependencies.** `e1`; none prior.

**Complexity.** S

**Specialist suggestion.** `security-reviewer` (UI surface is un-audited).

### notebook-surface-expansion-m2 — Operator renames + deletes a notebook in-page (htmx)

**Description.** Add an htmx in-page RENAME — a new `PATCH /ui/api/notebooks/{slug}`
that updates `display_name` via a new `NotebooksStore.update_display_name`
(an `UPDATE`; the `display_name` column already exists at `SCHEMA_VERSION 4`, so
NO migration) — and wire the existing `DELETE /ui/api/notebooks/{slug}` into the
UI behind a confirm. The mutation handlers get the `security-reviewer` lens
(slug validation, display-name length bound, same-origin via the existing `/ui`
SecFetchSite carve-out).

**Acceptance criteria.**
- Given a notebook, When the operator submits the in-page rename form, Then
  `PATCH /ui/api/notebooks/{slug}` updates `display_name` and the row re-renders
  with the new name (htmx swap); a malformed slug → 422 and an over-long name →
  rejected.
- Given a notebook, When the operator confirms delete in-page, Then the notebook
  is removed and the list re-renders without it.
- [ ] New PATCH route + `update_display_name` (no schema migration); handler +
  template tests (rename happy-path, 422 malformed slug, over-long-name reject,
  delete round-trip).

**Dependencies.** `e1`; soft-after `m1` (same template).

**Complexity.** M

**Specialist suggestion.** `security-reviewer` (mutation handlers on the
un-audited UI surface).

### notebook-surface-expansion-m3 — Constitution refreshed + UI-security-audit issue filed

**Description.** Update `.claude/notes/06-mcp-server-design.md` + `CLAUDE.md` to
DROP the stale "no frontend exists, by design" claim — describe the shipped
Jinja2+htmx UI (`server/routes/ui.py` + `frontend/templates/` + `/ui/api/notebooks/*`
+ the m4 `/ui/status-badge`) and its loopback / CSP / SecFetchSite posture. FILE
(do NOT execute) a UI-security-audit tracking issue at `chris-dare-dev/arXMCP`
covering `server/routes/ui.py` + `server/routes/notebooks.py` + the templates
(E13 scoped the UI audit out; CAND-13/CAND-14).

**Acceptance criteria.**
- [ ] `06-mcp-server-design.md` + `CLAUDE.md` no longer claim "no frontend
  exists"; they describe the actual UI surface. A doc-grep test asserts the
  stale phrase is gone from both.
- [ ] A UI-security-audit issue is FILED at `chris-dare-dev/arXMCP` (external
  write — Phase-4, per-event authorized) scoping the audit; the audit itself is
  NOT executed this cycle.

**Dependencies.** `e1`.

**Complexity.** S

**Specialist suggestion.** `—` (docs + a filed issue; the milestone-pipeline
adversary suffices).

### notebook-surface-expansion-m4 — Notebooks become first-class MCP resources (resources/list + read)

_(Epic `e2`, piece 1 of 2 — the spike doc's suggested "e2-m1"; numbered `m4` to
continue this roadmap's flat `mN` milestone-ID sequence that init-state.sh greps.)_

**Description.** Register notebooks as MCP **resources** on the FastMCP server
(`server/main.py` construction site, line ~654): a concrete index resource
`arxmcp://notebooks` (enumerates all slugs) + a per-notebook template
`arxmcp://notebooks/{slug}` whose `resources/read` returns notebook **METADATA
only** (slug, display_name, created_at, parse_status, paper count, lancedb_path)
sourced from `NotebooksStore` (`list_notebooks` / `get_notebook` / `list_papers`).
Register via a new `register_resources(mcp_server)` called AFTER
`register_all_tools` and BEFORE `mount_mcp` (same snapshot-at-mount constraint as
tools — spike-1 finding). `validate_slug` on the URI BEFORE any store/FS access
(a resources/read is an unauthenticated MCP call — treat slug as hostile). Wrap
operator-authored `display_name` in the read payload per the indirect-prompt-
injection discipline in `08-security-observability-ops.md` (an agent may feed it
to an LLM). NO new MCP tools; the frozen 8-tool surface is untouched.

**Acceptance criteria.**
- Given notebooks exist, When a client calls `resources/list`, Then it returns
  one `arxmcp://notebooks/{slug}` per notebook (+ the `arxmcp://notebooks` index);
  When it calls `resources/read` on a slug, Then it returns that notebook's
  metadata (NOT chunk content).
- Given a malformed / path-traversal slug in a resource URI, When `resources/read`
  is called, Then it is rejected via `validate_slug` before any store/filesystem
  access.
- [ ] **Byte-stability guard test** (mirrors spike-1's two-server comparison):
  asserts the live `tools/list` SHA-256 == `EXPECTED_TOOL_SCHEMA_SHA256` AND
  `EXPECTED_BP1_SHA256` is UNCHANGED after resources are registered — with **NO
  re-pin** of either hash. If either drifts, the wiring leaked into the tool
  registry / orchestrator prefix → STOP and fix the leak, do not re-pin.
- [ ] `resources/list` + `resources/read` tests (metadata shape; slug-traversal
  rejection; empty-notebooks case; display_name wrapped/escaped).

**Dependencies.** `e2`; `spike-1` (DONE — `9ac322a`).

**Complexity.** M

**Specialist suggestion.** `mcp-protocol-reviewer` + `cache-stability-reviewer`
(MCP transport surface; `tools/list` + BP1/BP2 byte-stability is load-bearing).

### notebook-surface-expansion-m5 — Static initialize.instructions orients a connecting agent

_(Epic `e2`, piece 2 of 2 — the spike doc's suggested "e2-m2"; numbered `m5`.)_

**Description.** Set a static `instructions=` on the FastMCP construction
(`FastMCP("arxmcp", json_response=True, instructions=ARXMCP_INSTRUCTIONS)` —
one-line change at `server/main.py:654`, the arg is native to FastMCP 1.27.x per
spike-1). The string is a reviewable module-level constant (e.g.
`server/mcp_instructions.py` or `server/prompts.py`): short, factual orientation —
the math corpus + target categories, the `arxmcp://notebooks` resources for corpus
discovery, the 8-tool retrieval surface, and the read-only discovery model. This
is the CAND-11 v0 — explicitly NOT the full `SYSTEM_PROMPT` (Won't list).

**Acceptance criteria.**
- Given a client connects, When it reads the MCP `initialize` response, Then the
  `instructions` field is the static `ARXMCP_INSTRUCTIONS` string.
- [ ] The instructions constant + the one-line wiring; a **hash-pin test** on the
  instructions string (its own `EXPECTED_INSTRUCTIONS_SHA256`, intentional-drift
  discipline — mirrors `EXPECTED_TOOL_SCHEMA_SHA256`).
- [ ] Byte-stability guard: `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256`
  UNCHANGED (no re-pin) — `instructions` is orthogonal to both (spike-1).

**Dependencies.** `e2`; soft-after `m4` (same FastMCP construction site).

**Complexity.** S

**Specialist suggestion.** `mcp-protocol-reviewer` + `cache-stability-reviewer`.

### notebook-surface-expansion-m6 — Notebook export streams a portable tar + manifest

_(Epic `e3`, piece 1 of 2 — the backup/export half.)_

**Description.** Add `GET /ui/api/notebooks/{slug}/export` (`server/routes/notebooks.py`)
streaming a portable tar of ONE notebook for backup/move (CAND-9): a
`StreamingResponse` (`media_type="application/x-tar"`,
`Content-Disposition: attachment; filename=<slug>.tar`) whose members are the
notebook's on-disk assets under `var/arxmcp/notebooks/<slug>/` (uploaded PDFs +
ar5iv parsed HTML + the per-notebook LanceDB/chunks) PLUS a top-level
`manifest.json` holding the `notebooks.db` rows for THAT slug only — the `notebooks`
row + its `notebook_papers` junction rows (sourced from `get_notebook` +
`list_papers`). `validate_slug` FIRST; `notebook_dir` containment for the asset
root; the manifest is DETERMINISTIC (sorted keys, stable member order) for
round-trippability. Local tar to the response stream only — NO cloud/object storage
(Won't list).

**Acceptance criteria.**
- Given a notebook with papers + on-disk assets, When the operator GETs
  `/ui/api/notebooks/{slug}/export`, Then the response streams a tar whose members
  include `manifest.json` (the slug's notebooks + notebook_papers rows) and the
  notebook's `var/` asset files; a malformed slug → 422; an unknown slug → 404.
- [ ] New streaming export route + a deterministic manifest builder (sorted keys,
  stable member ordering); `validate_slug` + `notebook_dir` containment; the
  manifest serializes ONLY the requested slug's rows (never other notebooks').
- [ ] Tests: tar members for a seeded notebook (manifest + assets present); manifest
  is byte-stable across two exports of the same notebook; 422 malformed slug; 404
  unknown slug; the manifest does NOT leak other notebooks' rows.

**Dependencies.** `e3`; none hard.

**Complexity.** S

**Specialist suggestion.** `security-reviewer` + `determinism-reviewer` (a new
streaming route — slug path-traversal, no-secret-leak in the tar bytes; the manifest
shape must be deterministic/round-trippable).

### notebook-surface-expansion-m7 — Notebook restore round-trips the export bundle

_(Epic `e3`, piece 2 of 2 — the move/restore half; completes the round-trip.)_

**Description.** Add `tools/notebook_restore.py <bundle.tar> [--force]` consuming an m6
export bundle into a target notebooks base: SAFELY extract the `var/` assets into
`var/arxmcp/notebooks/<slug>/` and re-INSERT the manifest's `notebooks` row +
`notebook_papers` rows into the target `notebooks.db`. **Security is load-bearing:**
tar extraction is a path-traversal / zip-slip vector — use the Python 3.12 `tarfile`
data extraction filter (`filter="data"`, PEP 706) AND validate every member name
(reject absolute paths, `..`, and symlink/hardlink members) before extraction;
`validate_slug` on the manifest slug; refuse to clobber an existing slug without
`--force`; re-insert DB rows idempotently (409-safe). Completes the export→restore
round-trip from m6.

**Acceptance criteria.**
- Given an m6 export bundle, When `tools/notebook_restore.py` runs against a FRESH
  notebooks base + `notebooks.db`, Then the notebook, its `notebook_papers` rows, and
  its on-disk assets are restored and the notebook is readable (round-trip:
  `get_notebook` + `list_papers` + a sample asset file all present).
- [ ] New `tools/notebook_restore.py`; SAFE extraction (`filter="data"` + explicit
  reject of absolute / `..` / symlink / hardlink members); `validate_slug`;
  idempotent DB re-insert; `--force` required to overwrite an existing slug.
- [ ] Tests: the end-to-end round-trip (export via the m6 route → restore into a tmp
  base → assert notebook + papers + a sample file present); a MALICIOUS-tar-member
  test (an absolute-path / `../escape` / symlink member is rejected, nothing written
  outside the notebook dir); the no-clobber-without-`--force` guard.

**Dependencies.** `e3`; soft-after `m6` (consumes the m6 bundle + manifest format).

**Complexity.** S

**Specialist suggestion.** `security-reviewer` + `determinism-reviewer` (tar
extraction is the zip-slip/path-traversal surface; the restore must be
deterministic + idempotent).

---

## Phase 4 — Materialize

### Validation

- `validate-roadmap.py`: pass
- Must-cap: 22.2% (≤ 60%) — unchanged; e2 (Should) and e3 (Could) were promoted
  into the Now scheduling lane WITHOUT MoSCoW reclassification, so the cap math is
  unaffected. All three epics are now scheduled (Later lane empty).
- All Now-lane milestones have AC: yes (m1, m2, m3, m4, m5 SHIPPED; m6, m7 newly
  spec'd — e3 promoted Later→Now).
- Slug format valid: yes (`notebook-surface-expansion`)

### GitHub tickets

Not requested (run with `--github` to bundle epic + story bodies). NOTE: m3
itself FILES a UI-security-audit `gh` issue as one of its acceptance criteria —
that is a Phase-4, per-event-authorized external write inside the
milestone-pipeline run, distinct from this skill's ticket bundle.

### Next step

Epics **e1 (UI) and e2 (agent discovery) are SHIPPED**. `spike-1` is **DONE (GO)**.
e3 (portability) is now spec'd as the last two milestones. Next executable
milestone: `notebook-surface-expansion-m6` (the streaming export route). Run:

    /milestone-pipeline notebook-surface-expansion-m6

Then `notebook-surface-expansion-m7` (the restore CLI + the export→restore
round-trip; soft-after m6). This skill will not invoke milestone-pipeline. After
m7, the roadmap is fully shipped — all three epics complete, Later lane empty.

---

<!-- end:roadmap -->
