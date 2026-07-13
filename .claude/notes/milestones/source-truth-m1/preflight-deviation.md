# Phase 0 preflight — source-truth-m1

**Init HEAD:** `463b870` · **Lock:** taken (after clearing a stale lock — see below) · 2026-07-12

## Stale-lock recovery (recorded)

At init the shared `.lock` was held by `122476:adhoc-20260712-698fead` — but **pid 122476 was
dead** (`tasklist` → "No tasks running") and that session was stuck at `implement-complete`
(it died mid-pipeline). Per the milestone-pipeline protocol, a stale lock (dead holder) is
cleared via `init-state.sh <held-id> --release-lock` (never `rm`). Cleared, then took the lock
for source-truth-m1. The dead session's own commits are already on `main`; its `state.json`
is untouched.

## Dirty-tree deviation

Phase 0 wants a clean tree; the tree is dirty (22 modified / 18 untracked) — the documented
recurring pattern (Obsidian frontmatter stamper on `docs/*` + `plans/*.md`, concurrent-session
scratch). **Crucially, m1's code surfaces are CLEAN:** `git status --porcelain -- server/
ingest/ tools/ tests/` is empty, so m1's implementation cannot entangle with the pre-existing
dirt. Commit discipline: explicit pathspecs only (concurrent sessions are actively committing —
HEAD moved to `463b870` from another session's kuzu work).

## Scope note — spike-1 reshapes m1's license source

`source-truth-spike-1` (done, 2026-07-12) **falsified** the roadmap's e1/m1 premise that license
URIs come from `tools/_arxiv_api.py`'s Atom client: the Atom API returns **0/30** licenses (a
schema-level absence), while **arXiv OAI-PMH does** carry `<license>`. m1 must therefore hydrate
license from **OAI-PMH** (a new/added client), not the Atom client — a deviation from the
roadmap's literal text, driven by the spike (which is exactly what the spike existed to
determine). The >20% fail-closed owner-escalation is on record (spike-1 note); m1 keeps the
decision function **advisory-only** (serving unchanged) per the roadmap, so the escalation does
not block m1 — it blocks the m4 cutover.

## m1 scope boundaries (what it is / isn't)

- **IS:** documents registry (per-notebook SQLite, extending `server/paper_metadata_store.py`) +
  raw-source/parse-artifact checksums + parser/chunker version stamps + OAI-PMH license
  hydration + advisory per-revision license decision fn + backfill CLI for both notebooks +
  coverage report. Tests for each. Zero chunks re-embedded (paper-metadata-m1 precedent).
- **ISN'T:** the chunks-schema v2 columns (m2), the `get_chunk` field surfacing (m5, rides W1),
  the fail-closed serving cutover (m4). So m1 does **not** touch the `tools/list` schema hash.
