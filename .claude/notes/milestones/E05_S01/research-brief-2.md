# E05_S01 — Research Brief 2

## 1. In-codebase context

### What's already there

**`chunk_manifest.json` writer** lives at `ingest/chunker.py:1002-1041`
(`_write_chunk_manifest`). The on-disk schema is:

```json
{
    "chunker_version": "v1.0",
    "chunks": [{"chunk_id": "arxiv:2307.00001:13d9aafc9c49463a", "kind": "stmt"}, ...],
    "paper_id": "2307.00001"
}
```

Written via the BP1 byte-stable pattern: `json.dumps(manifest, ensure_ascii=False,
sort_keys=True) + "\n"`, then atomic tmp+rename with PID+UUID suffix
(`ingest/chunker.py:1030-1041`). The manifest file's own docstring already
calls out this milestone: *"Used by E05_S01's eval harness to validate that
curated chunk_id references in the labeled query set still exist after a
re-chunk"* (`ingest/chunker.py:1018-1019`). **The manifest carries `kind`
per chunk** — a critical detail for AC-7 (≥5 stmt + ≥5 proof).

**`CHUNKER_VERSION` constant**: `ingest/chunker_types.py:28` — `CHUNKER_VERSION
= "v1.0"`. Comment block (lines 21-27): *"Single source of truth for the
chunker version string. Bump this constant in lockstep with any change to
chunking strategy"*. The validator MUST import this — never re-literalize
`"v1.0"`.

**`CHUNKS_DIR` constant**: `ingest/chunker.py:79` and `ingest/embedder.py:141`
— both define `CHUNKS_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "chunks"`
where `REPO_ROOT = Path(__file__).resolve().parent.parent`. Validator should
reuse the chunker's constant (single source of truth).

**Chunker has NOT been run on the 50-paper seed.** `find var -type d` returns
only `var/arxmcp/`, `var/arxmcp/ops/`, `var/arxmcp/ops/parser-failures/`. No
`var/arxmcp/corpus/chunks/` exists in this worktree, no `seed.log` shows the
seed has been fetched, and `var/arxmcp/` is gitignored (`.gitignore:24`,
`/var/arxmcp/`). The 10 chunker fixtures live at `tests/fixtures/chunker/`
and are committed (E02_S05).

**Test wiring pattern**: `tests/conftest.py` already exists with an autouse
fixture redirecting `STORE_STATS_PATH` into `tmp_path`. `pyproject.toml:67-69`
configures `testpaths = ["tests"]`. The `make test` target is
`ruff check . && pytest` (`Makefile:45-46`); pytest auto-discovers anything
under `tests/`. The brief says *"`make test` integration: runs
`python tools/validate_eval_fixtures.py`"* — there are two clean ways to do
this and both are fine (a `tests/eval/test_fixtures.py` wrapper that imports
the validator + `pytest.fail` on non-zero, or an explicit Makefile line);
**recommend the wrapper** because it inherits ruff's exclusions and the
existing `make test` invariant doesn't change.

### Design notes that apply

- **`02-architecture-overview.md:122-127`** (Determinism contract): *"Chunk
  IDs are content-addressable: `arxiv:<paper_id>:<sha256(canonical_chunk_bytes)[:16]>`.
  No timestamps in tool results. No random tie-breaking. JSON keys serialized
  in alphabetical order."* The fixture file itself must respect this (sorted
  keys, no `created_at` if it would invalidate BP1 — but the brief schema
  *includes* `"created_at": "2026-05-06"` so this is allowed in fixture
  metadata; it's not in the cache-keyed read path).
- **`07-multi-agent-caching.md:40-58`** — BP1 byte-stability. The fixture
  file is committed source (not cache-keyed runtime output), so the
  `created_at` field is fine.
- **`09-feature-priorities.md`** — Tier 0 exit criterion comes from E05_S02,
  not S01. S01 only ships the labeled data.
- **`05-storage-and-indexing.md`** referenced by E05 epic header for the
  nDCG@5 / Recall@10 definitions.

## 2. Prior decisions and lessons

### "User-blocked" precedent

`E05-eval-harness.md:45` says verbatim: *"the user owns curation. The
milestone is blocked on a human reviewing chunker output for 50 papers and
writing 20 query-relevance pairs. The milestone ships when the JSON is
committed and validated — the implementer cannot automate the curation
itself (that would make the eval circular)."* Searching prior milestones,
**no precedent for user-blocked deliverables exists yet** — every E01–E04
milestone shipped fully-implemented code. The closest analog is E02_S05's
*"50-paper integration deferred to user verification"*
(`E02_S04/implementation-summary.md`), where the implementer landed unit-
testable infrastructure on hand-crafted fixtures and called the live-corpus
sweep out as out-of-scope. That's the pattern to imitate: **ship validator
+ docs + Makefile wiring + one stub fixture, mark curation as the user's
gate**.

### Validator structuring lessons

- `tools/` already has runnable scripts with the same shape we need:
  `tools/curate_seed.py`, `tools/fetch_seed.py`, `tools/fetch_one_paper.py`.
  Pattern: `#!/usr/bin/env python3`, top-of-file docstring with usage
  example, `argparse` entry point, exit codes (0=ok, 1=fail). `fetch_seed.py`
  computes `REPO_ROOT = Path(__file__).resolve().parent.parent` and derives
  paths — the validator should mirror this exactly.
- The atomic-write pattern in `_write_chunk_manifest` (PID+UUID tmp,
  `os.replace`, `try/finally` cleanup, `contextlib.suppress(OSError)`) is
  the canonical "write committed JSON" recipe. Validator only reads, but
  if the maintainer ever generates a stub fixture programmatically, copy
  that pattern.
- `ingest/embedder.py:692-738` already implements
  "scan all paper-id directories under `CHUNKS_DIR` for `chunk_manifest.json`
  and load referenced chunk_ids" with proper error classes
  (`_ManifestCorruptError`, `_ChunkFileMissingError`). The validator should
  **not duplicate** this scan; either import the embedder helpers or
  factor a small `iter_manifest_chunk_ids()` into `ingest/chunker.py`.
  Recommend: write the validator's own scan loop (the embedder helpers
  raise typed exceptions tightly coupled to the embedder skip-protocol;
  re-using them creates an unwanted dep), but copy the dedup-on-duplicate
  invariant.

### Always-breaks watch-list

- **Stale `chunk_id`s on chunker version bumps** (E05 epic risk note,
  line 67-68): *"If `chunk_id`s are not reproducible, the fixture becomes
  stale on every chunker run."* The validator's job is exactly this:
  flag staleness loudly when it happens.
- **Stray `"v1.0"` literals** — E02_S04 closure tracks `"v1.0"` literal
  count in `chunker.py = 0`, `chunker_types.py = 1`. Validator MUST
  `from ingest.chunker_types import CHUNKER_VERSION` and compare to
  fixture header — never type `"v1.0"` into validator source.
- **Test pollution into `var/`** — F8 from E04_S01 forced the conftest
  autouse `_patched_store_stats_path`. Anything the validator writes (a
  log? a stats file?) must respect the same pattern; recommend the
  validator be **read-only** (no side-effect writes).
- **TOKENIZER_VERSION ≠ CHUNKER_VERSION** (E02_S04 summary, decision 6).
  Don't conflate. Fixture's `chunker_version` field tracks
  `CHUNKER_VERSION` only.

## 3. External sources

- **TREC qrels format** (`https://trec.nist.gov/data/qrels_eng/`): the
  industry standard for graded-relevance test collections is a TSV
  `qid 0 docid relevance` (columns: query-id, iteration, document-id,
  relevance grade). The brief's JSON form is a strict superset and is
  ergonomically better for hand-editing in a small fixture; **don't
  switch to TSV**. But borrow the convention: relevance grades 0–3 with
  3 = highly relevant matches NIST norms exactly (TREC-DL-2019 used
  0/1/2/3 for irrelevant/related/highly-relevant/perfectly-relevant).
- **nDCG@5 graded-relevance norms**: graded scoring requires per-query
  judgments where ≥1 grade-3 exists (denominator avoids div-by-zero on
  ideal DCG). The brief AC-2 enforces this exactly. Prior art:
  MS MARCO passage-ranking task has avg ~1.1 relevant passages per query;
  20 queries × ≥1 grade-3 + a sprinkle of grade-1/2 is enough to make
  nDCG@5 discriminative on a 50-paper corpus.
- **JSON-Schema vs lightweight runtime validation**: jsonschema is a
  ~150 KB pip dep with C extensions; the validator runs in `make test`
  on every CI invocation. **Recommend lightweight runtime validation in
  pure Python** — the schema has 6 top-level keys and 3 per-query keys;
  hand-coded `if not isinstance(...)` checks are ~30 LOC, zero deps,
  zero install-fragility. `pyproject.toml` deps list is currently 8
  packages and adding jsonschema for one ~80-line file is over-engineering.
  Mirror the validation discipline of `EmbedRecord.__post_init__`
  (`ingest/schema.py`).

## Open questions

**(a) Empty `var/arxmcp/corpus/chunks/` behavior.** **Recommend: skip
cleanly with a single warning line on stderr and exit 0**, gated on the
fixture being in its "empty seed" state (option (b)-1 below). Rationale:
on a cold-start dev box (which is the current state of this worktree —
no seed fetched), `make test` must stay green, otherwise every developer
hits `make test` failure on day one. But if the fixture is non-empty
AND the chunks dir is empty, that's a hard fail (the fixture references
chunks that demonstrably don't exist anywhere). Implement as: scan
chunks dir → if empty AND fixture has no `relevant_chunks` entries, warn
and exit 0; if empty AND fixture has entries, exit non-zero. This
preserves the AC-5 / AC-6 contract.

**(b) Seed `queries.json` shape on initial commit.** **Recommend:
ship as `{"queries": []}` with full header (`schema_version`,
`chunker_version`, `created_at`)** — the validator passes-as-no-op
(zero queries to check). NOT 20 stub queries with placeholder flags
(adds a `_curation_status: "pending"` invariant the validator must
respect, then must un-respect later — needless complexity), NOT absent
(makes "missing fixture" indistinguishable from "validator broken").
A literal empty-array seed makes the curation-blocking explicit
(developer running `make test` sees zero queries, knows curation is
pending) without inventing a stub schema. Doc the upgrade path in
`docs/eval-curation.md`: "when 20 queries are committed, AC-1 (`exactly
20`) becomes enforced; until then validator runs in seed-mode".
A clean alternative: the validator counts queries and **only enforces
AC-1/2/7 when count==20** (i.e. an empty fixture is seed-mode, partial
fills error out). Recommend this latter behavior — surfaces partial
curation as an error, prevents quietly merging 5-query fixtures.

**(c) Literal-locked `"v1.0"` vs imported `CHUNKER_VERSION`.**
**Recommend: import `CHUNKER_VERSION` from `ingest.chunker_types`** at
validation time. The brief's `chunker_version` line in the fixture is a
**committed expectation** that the maintainer typed; the validator's job
is to confirm the fixture's stated version matches the running chunker's
version. If we hardcode `"v1.0"` in the validator, a future
`CHUNKER_VERSION = "v2.0"` bump silently passes the fixture against the
old chunker. The acceptance criterion (AC-4 *"chunker_version in the
fixture header matches `"v1.0"`"*) is satisfied as long as the fixture
header *currently* says `"v1.0"` AND the imported constant *currently*
says `"v1.0"` — both true. The validator's contract is equality between
fixture header and `CHUNKER_VERSION` at runtime, not against a literal.

## External writes the implementation will require

| type | target | why |
|---|---|---|
| filesystem write | `tests/eval/fixtures/queries.json` | seed fixture (committed; queries[] empty per (b) above pending user curation) |
| filesystem write | `tools/validate_eval_fixtures.py` | new validator script (committed) |
| filesystem write | `docs/eval-curation.md` | curation runbook (committed) |
| filesystem write | `tests/eval/__init__.py` + `tests/eval/test_fixtures.py` | wires validator into `make test` via pytest auto-discovery (committed) |

No git push, no PR creation, no ticket mutation, no third-party API call,
no `var/` writes. The fixture itself becomes load-bearing only when the
user (chris.dare) hand-curates the 20 query triples — that act is out of
the implementer's scope and is the gating decision for milestone closure.
