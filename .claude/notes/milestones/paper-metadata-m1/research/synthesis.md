# Research synthesis — paper-metadata-m1

Fan-in of brief-1 (explore) + brief-2 (general + spike-1 fold-in). Read both briefs for detail; this is the implementer's routing map.

## Affected files (deduped)

- `server/` — NEW metadata store module (mirror `notebooks_store.py` async-over-sync SQLite pattern; `theorem_names_store.py` is the closest structural precedent; durability NORMAL is defensible — regenerable). **Open decision A/B below.**
- `tools/_arxiv_api.py` — extend, don't mutate: NEW `id_list` URL builder (existing `build_query_url` output is byte-locked by tests) + NEW prefix-preserving metadata mapper/entry point (existing `parse_atom_feed` drops old-style archive prefixes at line 189 — `Candidate` must stay byte-stable for `curate_seed`/discovery).
- `tools/` — NEW backfill CLI (`run(slug) -> int` + argparse `main` convention; membership from `var/arxmcp/notebooks/<slug>/papers.txt` via `_notebook_common.read_paper_ids_from_papers_txt` — the `notebook_papers` junction table is EMPTY, keying off it silently hydrates zero).
- `tests/` — offline tests only (monkeypatch `_arxiv_api._fetch_url` with synthetic Atom bytes); store migration-idempotence; cold-reopen regression (chunks table absent/raises); old-style ID round-trip regression.
- MUST NOT touch: `server/tools.py`, `server/handlers/`, `server/prompts.py` (frozen 7-tool schema; `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` byte-unchanged).

## Acceptance criteria (traced to roadmap item paper-metadata-m1 + child tasks)

1. AC1: backfill vs bridgeland-stability → ≥95% of 127 uncommented papers.txt IDs (≥121) get rows with non-NULL title AND authors. (Live run is an operator action; CI proves the path offline.)
2. AC2: cold store reopen serves metadata without touching the chunks table (regression test).
3. t-store-schema: double-init no-op; additive + atomic migrations.
4. t-atom-mapper: old-style Atom entry → record with title/authors/abstract/year/categories; `math/0212237v1` → `math/0212237` (prefix intact, version stripped).
5. t-backfill-driver: politeness (3 s spacing, polite UA, run-entry email enforcement via `resolve_contact_email`), idempotent re-run, loud hydrated/total summary line.
6. Gates: `make test` green (mocked network), `ruff check .` clean, no `assert` in src, schema hashes unchanged, no Markdown outside `.claude/`.
7. t-ingest-hook is should-priority — descope to follow-up is legitimate; hook must be best-effort/non-blocking if built (arXiv outage must not break ingest).

## external_writes_required

- `git push origin main` (Phase 4 orchestrator boundary only)

## Open questions (max 5)

1. Storage placement: (A) additive v5→v6 table in central `notebooks.db` vs (B) per-notebook SQLite file. Implementer decides + records rationale (A minimizes m2 wiring; B matches per-notebook isolation precedent).
2. Not-found id_list response shape unverified (arXiv outage during research) — tolerate absent/empty/error entry; re-run recorded query at implementation start if API is up.
3. Throttle hazards: `Retry-After: 0`, plain-text 429s, `max_results` default 10 truncating id_list batches (pin with test), whole-feed error poisoning (pre-validate IDs, per-ID fallback).
4. ~6-ID failure budget is thin — per-ID failure reasons in driver log.
5. Spike-1 resolved GO (recorded in journal); numeric live coverage to be pasted into brief-2's recorded re-run URL when API recovers.
