# E05_S01 Implementation Summary

**Branch:** `claude/gallant-blackburn-b89422`
**Files changed:** 6 (5 new, 1 docstring tweak)
**Commit (planned):** see Phase 4 footer once committed.

## Files

| Path | New / Modified | Purpose |
|---|---|---|
| `tools/validate_eval_fixtures.py` | NEW | Pure-Python validator + CLI for `queries.json`. Imports `CHUNKER_VERSION`; mirrors `_PAPER_ID_RE` from chunker. Behavior matrix (seed / partial / complete) × (corpus present / absent). |
| `tests/eval/__init__.py` | NEW | Empty package marker. |
| `tests/eval/fixtures/__init__.py` | NEW | Empty package marker. |
| `tests/eval/fixtures/queries.json` | NEW | Stub fixture: header + `queries: []`. The 20 hand-labeled triples are user-blocked per the brief's curation invariant. |
| `tests/eval/test_fixtures.py` | NEW | 27 tests in 6 classes. Locks the validator's behavior matrix and single-source-of-truth invariants. |
| `docs/eval-curation.md` | NEW | Curation runbook for the user (chris.dare). Documents the labeling discipline, kind quotas, AC mapping, and re-curation triggers. |

## Decisions exercised from research-synthesis.md

| Decision | Where it landed |
|---|---|
| D1 — implementer ships tooling; user owns 20-query curation | stub `queries.json` + `docs/eval-curation.md` |
| D2 — empty `queries: []` array on first commit | `tests/eval/fixtures/queries.json` |
| D3 — behavior matrix (seed × partial × complete) × (corpus × no-corpus) | `tools/validate_eval_fixtures.py:validate` + `TestSeedMode` / `TestPartialFixture` / `TestCompleteFixtureBranch` |
| D4 — import `CHUNKER_VERSION`, never literalize `"v1.0"` | `tools/validate_eval_fixtures.py:60` + `TestSingleSourceOfTruth.test_no_v1_literal_in_validator_source` |
| D5 — `created_at` accepted in fixture; validator never reads it | docstring + `_validate_header` |
| D6 — pytest wrapper, not raw Makefile call | `tests/eval/test_fixtures.py` (auto-discovered by `make test`) |
| D7 — pure Python validation, no `jsonschema` dep | `_validate_header` / `_validate_query_structure` |
| D8 — kind quotas via manifest `chunk_id → kind` index | `_load_chunk_kind_index` + `_validate_query_set_invariants` |
| D9 — file layout (5 new files + 1 stub) | matches |
| D10 — malformed `chunk_id` reported as MALFORMED, not STALE | `_validate_query_structure` + `test_malformed_chunk_id_raises` |
| D11 — duplicate query_id / chunk_id within query are errors | `_validate_query_structure` + `_validate_query_set_invariants` |
| D12 — 27 test cases lock behavior | `tests/eval/test_fixtures.py` (6 classes) |

## Test results

- 530 passed, 2 skipped (1 pre-existing + 1 env-gated BGE-M3 integration)
- 27 new tests in `tests/eval/test_fixtures.py`
- ruff clean

## Acceptance-criteria mapping

The brief has 7 ACs. **3 of 7 are user-blocked** (the curation pass);
the implementer satisfies the remaining 4 + the validator-side
guarantee on AC-3.

| AC | Status | Where verified |
|---|---|---|
| AC-1: `queries.json` contains exactly 20 entries | **user-blocked** (curator populates) | validator enforces in complete-mode (`test_partial_fixture_raises` / `test_19_queries_raises`) |
| AC-2: each query has ≥ 1 grade-3 chunk | **user-blocked** | validator enforces (`test_no_grade_3_raises`) |
| AC-3: every chunk_id exists in chunker output | **implementer** (validator) | `test_stale_chunk_id_raises` |
| AC-4: `chunker_version` matches running constant | **implementer** | `test_wrong_chunker_version_raises` + the stub fixture's `chunker_version: "v1.0"` matches `CHUNKER_VERSION` at ship time |
| AC-5: validator exits 0 on a clean checkout with valid corpus | **implementer** | `test_full_valid_fixture_passes` (synthetic corpus in `tmp_path`) |
| AC-6: validator exits non-zero on stale chunk_id | **implementer** | `test_stale_chunk_id_raises` |
| AC-7: ≥ 5 stmt-kind queries AND ≥ 5 proof-kind queries | **user-blocked** | validator enforces (`test_too_few_stmt_kind_raises`) |

## User handoff

The 20-query curation pass is **the** gate to closing AC-1, AC-2,
AC-7. `docs/eval-curation.md` is the runbook. The curator commits
their own pass with:

```
data(eval): hand-labeled 20-query fixture (E05_S01)
```

The implementer cannot author this commit — that would make the eval
circular (per the brief).

## Notable design choices for the critic

- **`_PAPER_ID_RE` is duplicated, not imported.** The chunker module
  pulls heavy LaTeXML-shaped imports (`_PAREN_NAME_RE`, theorem-env
  detection) the validator does not need; importing it would slow
  every `make test` invocation. The duplication is locked by
  `test_paper_id_regex_matches_chunker` which compares `.pattern`
  strings — any drift fires loudly.
- **The literal `"v1.0"` scan** lives in
  `test_no_v1_literal_in_validator_source`, mirroring the E04_S04
  single-source-of-truth pattern. The validator's docstring uses
  `CHUNKER_VERSION` (the import) when discussing the version, never
  the literal string.
- **`created_at` field is fixed**, not `datetime.now()`. The runbook
  documents the convention. The validator does not read the field at
  runtime — it's documentation only.
- **The seed `queries.json` ships with `queries: []`**, not absent
  and not 20 placeholder stubs. An empty array is the explicit
  "curation pending" mode; an absent file is "validator broken" or
  "fixture deleted" (validator raises). 20 placeholders would invent
  a `_curation_status` invariant the validator must respect-then-
  un-respect.
- **The 1-19 partial-fixture branch is always an error**, regardless
  of corpus presence. This catches the "I'll commit my first 5
  queries and finish later" failure mode by surfacing it as a CI
  failure.
- **`chunks_dir` is a parameter**, not hardcoded to the production
  path. Every test runs against `tmp_path`-synthesized manifests; no
  test pollutes the developer's `var/` tree.
- **Manifest scan is a fresh implementation**, not a re-use of
  `ingest.embedder._iter_paper_chunks`. The embedder helpers raise
  typed exceptions tightly coupled to the embedder's skip-protocol;
  re-using them creates an unwanted dep. The validator's scan is
  ~30 LOC and read-only.

## Out-of-scope (deferred per brief)

- The 20 hand-labeled query triples themselves (user-blocked).
- Running the retrieval evaluation (E05_S02).
- Queries for math.NT / hep-th / math-ph (Tier 1+).
- LLM-generated query fixtures (the brief explicitly bans these:
  *"automated query generation [...] would make the eval circular"*).

## External writes

**None.** All deliverables are local commits. The next external
write happens when the user commits their curated fixture (outside
the pipeline).
