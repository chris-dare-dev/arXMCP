# Startup-UX uplift — decisions

> Companion to `current-state-critique.md` + `streamlined-flow-proposal.md`.
> Captures the operator's answers to the 5 open questions in §11 of the
> proposal. Authored 2026-05-30; signed off by Chris.

---

## D1 — Bootstrap mode default: **OFF**

Cold-start corpus refusal stays the default. `Resources.startup` continues
to raise `CorpusNotIngestedError` on a missing `corpus-version.json` —
that's the safe behavior for production deploys where a missing corpus
indicates a real failure (e.g. someone deleted `var/arxmcp/index/lancedb/`).

Bootstrap mode is **opt-in** via either:
- `ARXMCP_BOOTSTRAP_MODE=1 make up` (env var), or
- `make up-wizard` (new Make target — sets the env var for you)

A fresh-clone user runs `make up-wizard` once; everyone else hits the
unchanged contract. No silent flip; no production-deploy footgun.

## D2 — Ingest stays at the corpus level (NOT per-notebook)

**Decision:** drop `make ingest NOTEBOOK=<slug>` from the proposal. The
onboarding path ingests papers into the **shared global corpus**
(`var/arxmcp/index/lancedb/`); notebooks become **filter labels** over
the shared corpus, not separate LanceDB instances.

The Make API simplifies to:

| Target | What |
|---|---|
| `make init NOTEBOOK=<slug>` | Create a notebook label (registers in `notebooks.db`). No corpus side-effects. |
| `make add NOTEBOOK=<slug> PAPER=<id>` | Tag a paper as belonging to the notebook AND ingest it into the shared corpus if not already present. |
| `make ingest` | Bulk-ingest from a paper-id list (file or stdin) into the shared corpus. Notebook-agnostic. |
| `make reingest PAPER=<id>` | Re-chunk + re-embed one paper after a chunker bump. |
| `make status` | One-line summary of the shared corpus + notebook labels. |
| `make reconcile` | Heal `corpus-version.json` drift on the shared corpus. |
| `make repair-registry` | Re-register on-disk notebook dirs missing from `notebooks.db`. |

**Tension flagged + resolution:** the shipped fork-A code in
`server/handlers/search.py:424-520` (`notebook-retrieval-m2`) opens a
**per-notebook LanceDB** when `filters.notebook=<slug>` is passed. That
path remains intact — it's an opt-in **advanced mode** for operators who
genuinely want per-notebook corpus isolation (notebook-retrieval-m1's
fork-C use case). The DEFAULT onboarding pours everything into the
shared corpus and uses notebooks as `paper_id IN (...)` filters.

Implementation impact:
- `POST /ui/api/notebooks/<slug>/papers` already writes to
  `notebook_papers` (a junction table); now it ALSO ingests the paper
  into the shared corpus (or no-ops if already ingested).
- `filters.notebook=<slug>` on `search_papers` continues to work — but
  for shared-corpus notebooks, it becomes a `paper_id IN (notebook's
  papers)` filter over the shared LanceDB instead of an alternative
  LanceDB lookup.
- The per-notebook `var/arxmcp/notebooks/<slug>/lancedb/` path stays for
  the advanced mode but is no longer the documented default.

This is closer to the "Variant 1" pattern the proof-verify-handler-wiring
spike documented as the operator pattern.

## D3 — Sample papers for the wizard: 3 random references cited by shimura-varieties papers

**Decision:** at wizard build time, query the shimura-varieties notebook's
papers, extract their `\cite{}` references, resolve to arXiv IDs, and
pick 3 at random as the canonical sample seed.

Implementation note: this can be a hardcoded list (regenerated once,
checked in) OR a live query at wizard-render time. **Pick hardcoded** —
live querying the citation graph at wizard render time adds latency and
a failure mode for a first-boot user. The list gets refreshed during the
m5 implementation (one-time script: walk `var/arxmcp/corpus/parsed/`
for shimura-varieties papers, extract refs, write
`frontend/templates/_wizard_sample_papers.json`).

If the live wizard ever loses internet, the 3-paper sample button
fails gracefully ("offline; skip this step or paste your own arXiv ID").

## D4 — `operator.json` → SQLite

**Decision:** operator preferences live as a row in a new
`operator_settings` table inside `var/arxmcp/cache/notebooks.db`. Schema:

```sql
CREATE TABLE operator_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
```

Reads/writes go through a thin `server/operator_settings.py` module
(mirrors the existing `notebooks_store.py` pattern). The first key
stored is `contact_email`; the second (m5) is `wizard_dismissed_at`.

The "consistent with the existing registry" play wins. Migration
discipline mirrors the existing `notebooks_store` schema migrations.

## D5 — BGE-M3 first-run download: **real bytes-progress**

**Decision:** intercept `huggingface_hub`'s download callbacks and
expose them via `GET /ui/api/notebooks/<slug>/ingest-status`. The wizard
renders a `<progress>` element with bytes-done / bytes-total. The user
sees a real progress bar during the 2-GB first-run download, not a
"this takes 3-5 minutes" hand-wave.

Implementation: `huggingface_hub.HfApi` exposes `etag_timeout` /
progress callbacks via `tqdm`. The simplest hook is to monkeypatch
`huggingface_hub.utils.tqdm` to write to a shared state object the
ingest-status endpoint reads. Adversary will need to check this doesn't
leak between concurrent ingests (single-tenant, single-workstation
project — but the m4 critique should confirm anyway).

---

## Implications for m2-m6

The m1 fix (env-var error message + doc sweep + `/mcp/` trailing-slash
note) is **UNCHANGED** by these answers. Run it first; the answers above
don't touch its scope.

m2 simplifies significantly given D2: no `make ingest NOTEBOOK=` — just
`make ingest` (corpus-level) + `make add NOTEBOOK= PAPER=` (label +
ingest into shared corpus). The new `make` API table in §4 of the
proposal needs a rewrite.

m3 simplifies too: `reconcile-marker` operates on the shared
`var/arxmcp/index/lancedb/corpus-version.json`, not per-notebook
markers. (Per-notebook markers still exist for fork-C-advanced users,
but reconcile-marker on those is a separate flag.)

m4 picks up D1 + D5: `bootstrap_mode` is opt-in (default off), and the
ingest-status endpoint exposes the BGE-M3 download bytes-progress.

m5 picks up D3 + D4: wizard reads `operator_settings` from SQLite, uses
the hardcoded sample-paper triple.

m6 unchanged.

---

## Open follow-ups (not blocking m1)

- **Hardcoded sample-paper triple:** generate during m5 implementation
  by walking `var/arxmcp/corpus/parsed/` shimura-varieties refs. Note in
  `m5` brief.
- **`make help` reorg:** add a "FIRST TIME?" section at the top of the
  Makefile help block during m2 — surfaces `make up-wizard` +
  `make init` as the entry points.
- **Backwards-compat for the per-notebook LanceDB path:** confirm
  during m2 implementation that the shipped fork-A code at
  `server/handlers/search.py:424-520` continues to work for operators
  who set `ARXMCP_NOTEBOOK=<slug>` and ingested via the old
  per-notebook path. NO breaking change to existing ingested data.
