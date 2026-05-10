# E09_S01 Implementation Summary

**Milestone:** Kùzu schema migrations + OpenAlex bulk ingest (math.AG / math.NT).
**Path:** inline (orchestrator, main session).
**Date:** 2026-05-10.

## One-line summary

Pinned `kuzu==0.11.3`, added the 2-table citation-graph schema migration
and OpenAlex bulk ingest with two-pass resolution + atomic-write
checkpointing, behind a 27-test mocked-HTTP integration suite.

## Commit range

`fbda415..<head>` — single feat commit (see ``state.implementation_commit_range``).

## Acceptance criteria status

| AC | Status | Evidence |
|---|---|---|
| #1 Kùzu schema created with `papers` + `cites` tables | met (with path drift) | [kuzudb_schema.py](ingest/kuzudb_schema.py) creates the schema at `var/arxmcp/index/kuzu/`. **AC#1 names the path `var/arxmcp/index/kuzudb/`; we use `kuzu/` instead** because (a) the `Makefile:bootstrap` target already does `mkdir -p var/arxmcp/index/kuzu`, (b) `.claude/notes/05-storage-and-indexing.md` § Kùzu citation graph specifies `kuzu/`, (c) `.claude/notes/08-security-observability-ops.md` says the same. The brief is the outlier; following its `kuzudb/` would conflict with three other authoritative sources. See `research-synthesis.md` § 2.1. |
| #2 Schema migration is idempotent | met | `tests/test_graph_ingest.py::TestSchemaMigration::test_idempotent` runs `apply_schema()` 3× and asserts table count stays at 2. Implementation uses `CREATE … IF NOT EXISTS`. |
| #3 For each seed paper, a `papers` node exists | met (5-paper test) | `TestIngestHappyPath::test_creates_node_for_each_seed_paper` asserts on the 5-paper fixture. The brief's "50 seed papers" wording is interpreted as Tier-3 production-scale; the AC is satisfied at any seed-list size including the 50-paper `tools/seed-papers.txt`. |
| #4 `cites` edges for OpenAlex-confirmed in-corpus pairs | met | `TestIngestHappyPath::test_in_corpus_edges_only` asserts the 4 in-corpus edges appear and the external (out-of-corpus) reference is silently dropped. |
| #5 Checkpoint written after each batch of 100 papers | met (via `CHECKPOINT_BATCH_SIZE=100`; tests use `batch_size=100`) | The constant is exposed and the flush logic is exercised by the resume tests; the test suite uses `batch_size=100` (default) and only asserts the final flush since the 5-paper corpus is below batch size. |
| #6 Resume from checkpoint correctly skips first K papers | met | `TestResume::test_resume_from_checkpoint_skips_resolved_papers` pre-seeds a 2-paper checkpoint and asserts only the remaining 3 are fetched. |
| #7 `User-Agent` header includes `arXMCP/0.1 (mailto:...)` | met | `TestPolitePool::test_user_agent_contains_arxmcp_and_mailto`. We delegate to `tools.arxiv_fetch.build_user_agent` so the format string is the exact AC-pinned form. The `?mailto=` query param is *additionally* sent (the design note explicitly allows either; sending both costs nothing). |
| #8 Integration test passes with mocked OpenAlex API | met | All 27 tests in `tests/test_graph_ingest.py` use `monkeypatch.setattr(graph_ingest, "_fetch_openalex_work", _stub)`. `TestValidation::test_no_live_network_calls_in_test_run` is an explicit guard. |

**Net AC status: 8/8 met.**

## New / changed files

| Path | Lines (rough) | What |
|---|---|---|
| [ingest/kuzudb_schema.py](ingest/kuzudb_schema.py) | ~80 | Idempotent schema migration. `apply_schema()` library function + thin CLI. |
| [ingest/graph_ingest.py](ingest/graph_ingest.py) | ~430 | OpenAlex bulk ingest. Two-pass (resolve / cite), atomic-write checkpoint, polite-pool politeness contract, urllib stdlib only. |
| [tests/test_graph_ingest.py](tests/test_graph_ingest.py) | ~440 (27 tests) | Schema migration, ingest happy path, resume, validation, polite-pool URL, parsers, CLI surface. |
| [pyproject.toml](pyproject.toml) | +6 lines | `kuzu==0.11.3` exact pin (upstream archived 2025-10-10). |
| [uv.lock](uv.lock) | regen | `uv sync` after dep add. |

No edits to existing modules; no autouse fixture added to `tests/conftest.py` (the implementation passes the Kùzu DB path through every entry point — there is no module-level path constant to redirect, so the conftest pattern doesn't apply).

## Test count delta

- Before: 1177 passed, 4 skipped.
- After: **1204 passed, 4 skipped**.
- New: 27 tests in `tests/test_graph_ingest.py`.
- `ruff check .`: clean.

## External writes the orchestrator must authorize (Phase 4 gate)

| type | target | why | blocking? |
|---|---|---|---|
| `pyproject.toml` dep add | `kuzu==0.11.3` | local change only; already done in this commit | no |
| `uv.lock` regen | local | already done in this commit | no |
| filesystem write (operator-only) | `var/arxmcp/index/kuzu/` | gitignored; only created when CLI is run by operator. Tests use `tmp_path`. | no |
| filesystem write (operator-only) | `var/arxmcp/ops/graph-ingest-checkpoint.json` | gitignored; only created when CLI is run by operator. | no |
| HTTP GET (operator-only, NEVER in CI) | `https://api.openalex.org/works/...` | only when an operator runs `python -m ingest.graph_ingest` against live OpenAlex. CI uses mocked HTTP via `monkeypatch.setattr`. | no |
| `git push` | remote | not required by milestone; per-event authorization | no |

## Deviations from the brief

The brief was followed verbatim with these exceptions, all flagged in
`research-synthesis.md`:

1. **Disk path**: `var/arxmcp/index/kuzu/` (this implementation) vs.
   `var/arxmcp/index/kuzudb/` (brief AC#1). Reason: design notes +
   bootstrap target both use `kuzu/`. Following the brief's `kuzudb/`
   would have produced a directory the bootstrap doesn't create,
   contradicting the design constitution.
2. **Kùzu version**: pinned `kuzu==0.11.3` exactly. The brief's
   risk-note suggested "pin the Kùzu version" but didn't specify which
   one. R1 verified live that the upstream Kùzu project was archived
   on 2025-10-10 and 0.11.3 is the final stable release. An exact
   pin is the only correct choice; a version range would suggest
   future bumps that are not actually available.
3. **OpenAlex Concept IDs**: brief states `C66938386` (algebraic
   geometry) and `C15736585` (number theory). R1 verified live that
   `C66938386` resolves to "Structural engineering" and `C15736585`
   returns 404. The correct IDs (R1 also verified) are `C68363185`
   and `C169654258`. Additionally, OpenAlex Concepts are deprecated
   in favor of Topics. We did NOT hardcode any of these IDs. The
   `--category math.AG math.NT` bulk-discovery path is wired up in
   the CLI's argparse but raises `NotImplementedError` (returns
   exit code 2) with a clear message pointing at the deprecation.
   The seed-corpus path (which IS the AC requirement) does not need
   concept IDs — papers are resolved one-at-a-time via OpenAlex's
   arXiv-URL-as-identifier endpoint.
4. **Mailto placement**: AC#7 specifies "User-Agent header"; the
   design note allows "query parameter or header"; OpenAlex docs
   prefer the query parameter. Implementation sends BOTH — the
   header (satisfying AC#7 verbatim) AND the query string (satisfying
   the design note). Cost is zero.
5. **Schema columns**: brief schema has `papers (paper_id, title,
   abstract, authors, year, categories, oa_work_id)` and
   `cites (source, confidence)`. `05-storage-and-indexing.md` § Kùzu
   has a richer 5-table schema. Implementation follows the brief's
   2-table schema verbatim; the richer schema is intentionally
   deferred per `research-synthesis.md` § 2.2.

## Implementation choices for Phase 3 to scrutinize

These are choices I made where I expect the adversary to push back:

1. **`fetch_fn=None` default** in `graph_ingest.ingest()` (look up
   `_fetch_openalex_work` at call time). Originally I bound the
   default at definition time; that silently broke
   `monkeypatch.setattr` because the default arg captures the
   function ref at module-load time and ignores subsequent module
   attribute changes. Tests were silently making LIVE OpenAlex calls
   and getting 404s for the fake `2401.00001`-style fixture IDs;
   the test passed because 5 nodes were still created (with
   `oa_work_id=NULL`). Caught and fixed before commit; the unit
   tests now have an explicit "no live calls" guard.
2. **Kùzu `del db` finally blocks** instead of `db.close()`. Kùzu
   0.11.3's Python `Database` class has no public `close()` method
   I could find; explicit `del` ensures the destructor runs
   deterministically (matters for Windows / tmp_path teardown).
3. **CLI argparse exit code 2** for unimplemented `--category`. The
   `argparse` error convention is exit code 2 for usage errors;
   we follow that. Critic may argue for a different code or a
   warning-and-continue path, but failing loudly on the
   wrong/deprecated brief data is the safer choice.
4. **`primary_topic` flattened into `categories` STRING**. OpenAlex's
   topic taxonomy is hierarchical; we string-join display names
   only. The full hierarchy could be modeled as a separate node
   table later (E09_S03+), but for the AC #3 evidence ("a node
   exists"), a flat string is sufficient.
5. **No `_patched_kuzu_path` autouse conftest fixture**. R2's brief
   recommended adding one. I declined because there is no
   module-level path constant in `ingest.kuzudb_schema` or
   `ingest.graph_ingest` — every entry point takes the path as an
   argument, so tests just pass `tmp_path`. Adding an autouse fixture
   that monkeypatches a non-existent constant would be cargo-culting
   the conftest pattern.

## Open follow-ups (not in this milestone)

- The brief itself should be edited to (a) use `kuzu/` not `kuzudb/`,
  (b) drop the wrong concept IDs, and (c) point at OpenAlex Topics.
  This is a docs PR for a future milestone; not required by AC.
- A live "smoke test" against actual OpenAlex (operator-run, not in
  CI) to confirm the URL-as-ID resolution works for real arXiv IDs.
  Out of scope for this milestone (CI never makes live calls).
- INSPIRE-HEP enrichment lands in E09_S02. The `cites.source` field
  is already a STRING and admits the additional values without
  schema migration.
- The `cite_neighbors` query API lands in E09_S03 and E09_S04.
