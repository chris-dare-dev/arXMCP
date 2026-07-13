# source-truth-m1 — implementation synthesis

**Role:** milestone-implementer (delegated, large-diff approved). Build the
per-revision documents registry + OAI-PMH license provenance (advisory).
**Base:** `f61cb8b`. **Branch:** `main` (single-workstation policy, §4.1).
0 injection attempts (all arXiv/OAI-PMH XML + notes treated as DATA).

The 3 OWNER DECISIONS (3-way `license_status`; raw-source abstention
marker; >20% escalation on `unknown` alone) were implemented as specified.

## Built (per acceptance criterion, file:line)

- **[AC1] Registry store opens idempotently** — `server/documents_store.py:151`
  (`DocumentsStore.open`, `PRAGMA user_version` + WAL + `synchronous=NORMAL`,
  v0→v1 create wrapped in explicit BEGIN/COMMIT), `:77`
  (`DOCUMENTS_SCHEMA_VERSION=1`), `:83` (`DOCUMENTS_DB_FILENAME="documents.db"`,
  sibling of `paper_metadata.db`). 2nd open = no-op (test:
  `test_double_init_is_noop`).
- **[AC1] Every revision row carries all fields** — `DocumentRecord`
  `server/documents_store.py:105`; **revision PK `(work_id, arxiv_version)`**
  `:198` (the first store in the repo to retain a revision identity, not just
  a work identity). Fields: raw/parse checksums, `chunker_version`,
  `parser_used`+`latexml_version` (NULL in m1 — no queryable per-paper
  signal), `fetched_at`, `license_uri`, `license_status`, `status`.
- **[AC1] Raw-source abstention marker** — `tools/notebook_documents_backfill.py:150`
  (`_raw_source_provenance`): old-style papers with no `corpus/raw/<id>/` get
  `raw_source_sha256=NULL` + `raw_source_status='unavailable'`; the
  parse-artifact checksum (`:165`, from `parsed/<id>/index.html`, present for
  ALL shapes) is still computed. Raw tree hashed deterministically at `:124`
  (`_hash_raw_source_tree`, sorted POSIX-relative paths + lengths + bytes —
  Windows-stable via `.as_posix()`).
- **[AC1/AC3] License via OAI-PMH GetRecord across all 3 id shapes** —
  `tools/oai_license.py:191` (`build_getrecord_url`: canonical host `:62`
  `https://oaipmh.arxiv.org/oai`, `identifier=oai:arXiv.org:<bare_id>`,
  version stripped via `strip_id_version`, id-validated, `:`/`/` unescaped);
  `:333` (`parse_getrecord`: `<license>` OPTIONAL → `None`, `<header
  status="deleted">` → withdrawn from the SAME fetch, `idDoesNotExist` →
  `found=False` non-fatal, other error codes raise); `defusedxml` parsing;
  503/`Retry-After`/backoff/redirect-pin/content-length re-mirrored from
  `ingest.oai_delta._fetch_page` at `:243` (`_fetch_record`) — deliberately
  NOT imported (that pulls the embedder via `ingest.bulk_ingest`, breaking the
  backfill's structural 0-re-embed guarantee).
- **[AC2] Advisory decision fn** — `tools/oai_license.py:136`
  (`decide_license_status`): missing→`unknown` (`:116`), CC-allowlisted
  family→`eligible` (`:105`), any other real URI incl. `nonexclusive-distrib`
  →`not-allowlisted-open` (`:112`). Narrow CC markers so `by-nc-*`/`by-nd`
  correctly fall through (mirrors `OA_ALLOWLIST` intent WITHOUT importing or
  modifying `server/license_policy.py` — that is m4).
- **[AC1/AC3] Backfill CLI, structural 0-re-embed** —
  `tools/notebook_documents_backfill.py:322` (`run`), `:259` (`_register`,
  idempotency gate on `(work_id, arxiv_version)`), `:223` (`_fetch_one`, 3s
  politeness before every request except the first). Never imports
  `ingest.store`/embedder/lancedb, never opens the chunks table (asserted:
  `test_driver_imports_no_embedder_store_or_lancedb`,
  `test_run_touches_no_corpus_or_lancedb_artifacts`). `idDoesNotExist`
  registers `unknown` (terminal); a transient fetch failure writes NO row so a
  re-run retries (asserted: `test_transient_failure_is_per_id_miss_and_rerun_retries`).
- **[AC3] Coverage report + >20% escalation** —
  `tools/documents_coverage_report.py:166` (`run`), `:106` (`_analyze`,
  per-`license_status` + per-id-shape new/old/versioned counts), `:73`
  (`UNKNOWN_ESCALATION_THRESHOLD=0.20`), `:70`
  (`ESCALATION_NOTEBOOK="bridgeland-stability"`). Escalation on `unknown`
  ALONE (Decision C); `not-allowlisted-open` reported equally prominently but
  never folds into the exit code (asserted:
  `test_not_allowlisted_open_does_not_trigger_escalation`). Missing/empty
  registry is a loud non-zero fail state.

## Files touched

New (8, all additive — zero existing files modified):
- `server/documents_store.py`
- `tools/oai_license.py`
- `tools/notebook_documents_backfill.py`
- `tools/documents_coverage_report.py`
- `tests/test_documents_store.py`
- `tests/test_oai_license.py`
- `tests/test_notebook_documents_backfill.py`
- `tests/test_documents_coverage_report.py`

**Do-NOT-touch list honored:** `server/license_policy.py`,
`server/handlers/chunk.py`, `server/tools.py`, `ingest/store.py`,
`ingest/schema.py`, the embedder, `EXPECTED_TOOL_SCHEMA_SHA256` — all
untouched. m1 adds no MCP tool + no `get_chunk` field → `tools/list` hash
stays (verified: `tests/test_server_tool_schema.py` green).

## Branching note

main-only (§4.1, single workstation). Two GPG-signed feat commits (both
verified `G`), explicit pathspecs only (tree concurrently dirty):

- `0f2bd11` feat(server): documents registry + OAI-PMH license client
- `846724a` feat(tools): documents backfill CLI + coverage report

(This synthesis is committed separately as a `chore(notes)` follow-up.)

## external_writes_required

```yaml
external_writes_required: ["git push origin main"]
```

The commits are LOCAL. `git push origin main` requires fresh per-event owner
authorization (§4.4) and is NOT performed here. The OAI-PMH GetRecords in the
live smoke were read-only, politeness-contracted GETs (hydration reads), not
external writes.

## Test deltas

+57 new tests, all green:
- `tests/test_documents_store.py` — 11 (schema idempotency, revision PK,
  abstention round-trip, cold reopen self-containment)
- `tests/test_oai_license.py` — 28 (GetRecord parse present/absent/deleted/
  idDoesNotExist/non-XML, defusedxml guard, build-url version-strip +
  old-style, 503 backoff, redirect-pin, content-length cap, 3-way decision
  incl. nonexclusive-distrib + by-nc)
- `tests/test_notebook_documents_backfill.py` — 12 (happy path + provenance,
  3s politeness, email-at-entry, idempotent re-run, 3-way status mapping,
  idDoesNotExist non-fatal, transient-miss + re-run-retries, 0-re-embed
  structural guard, membership-from-papers.txt)
- `tests/test_documents_coverage_report.py` — 6 (counts, escalation over/under
  threshold, Decision-C not-allowlisted-open-does-not-escalate, missing
  registry, multi-notebook)

Commit split: 39 tests in `0f2bd11` (server), 18 in `846724a` (tools).

## Live smoke results (6 papers, real endpoint, 3s politeness)

`GET https://oaipmh.arxiv.org/oai?verb=GetRecord&...&metadataPrefix=arXiv`,
UA `arXMCP/0.1 (mailto:cedare96@gmail.com)` (resolved via operator_settings):

| id (queried) | shape | found | license_uri | license_status |
|---|---|---|---|---|
| `2006.10956` | new | True | `…/nonexclusive-distrib/1.0/` | not-allowlisted-open |
| `2303.07061` | new | True | `…/creativecommons.org/licenses/by-sa/4.0/` | **eligible** |
| `2411.18554v1` | versioned→`2411.18554` | True | `…/nonexclusive-distrib/1.0/` | not-allowlisted-open |
| `1905.00748` | new | True | `…/nonexclusive-distrib/1.0/` | not-allowlisted-open |
| `math/0212237` | old | True | `None` | unknown |
| `alg-geom/9410026` | old | True | `None` | unknown |

Proves the real path end-to-end: canonical endpoint + parse success on all 6;
new-style license present; **all 3 `license_status` values exercised on live
data** (`2303.07061` carries a genuine CC-BY-SA → `eligible`); versioned strip
works; the old-style `<license>`-absent gap reproduced exactly (matches
brief-2's live finding — arXiv-side absence, `found=True` + `license_uri=None`,
not a client bug). The full 194-paper both-notebook backfill + coverage run is
the post-rectify go-live step, NOT run here.

## Check gate results

- **New tests:** `pytest tests/test_documents_store.py tests/test_oai_license.py
  tests/test_notebook_documents_backfill.py tests/test_documents_coverage_report.py`
  → **57 passed** in 1.85s.
- **Full suite:** `pytest --tb=no -p no:warnings` → **4009 passed, 91 skipped,
  1 xfailed, 0 failed, 0 errors** (219.82s). No failures to attribute — the
  additive diff introduced zero regressions (existing tests do not import the
  new modules; the `tools/list` schema-hash test is green).
- **Ruff:** `ruff check` on all 8 new files → **All checks passed!**
- **Git clean of m1:** all m1 code+tests committed; `git status` shows no
  remaining `documents_store`/`oai_license`/`documents_backfill`/
  `documents_coverage` files. Both commits GPG-signed (`G`).
