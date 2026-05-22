# Research Brief — proof-verify-handler-wiring-m4

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-22T01:10:00Z

## In-codebase context

### Ground truth: both notebooks are ALREADY INGESTED

**This is the most important finding of this brief.** The implementer does NOT need to
run `notebook_fetch.py` or `notebook_ingest.py` from scratch. Both notebooks already
have fully populated LanceDB indices:

- `var/arxmcp/notebooks/bridgeland-stability/lancedb/` — 4505 chunks from **39 unique
  paper_ids** (matches the 39-line `papers.txt` exactly; all 39 papers had pre-cached
  HTML at `var/arxmcp/corpus/parsed/<id>/index.html`)
- `var/arxmcp/notebooks/shimura-varieties/lancedb/` — 3625 chunks from **12 unique
  paper_ids** (matches the 12-line `papers.txt`)

Both LanceDB tables were confirmed queryable via `lancedb.connect()` + `open_table('chunks')`.

### The `corpus-version.json` `paper_count: 1` is NOT a bug — it reflects batch size

`corpus-version.json` for bridgeland shows `"paper_count": 1, "version": 157`; shimura
shows `"paper_count": 1, "version": 49`. **This is not an error.** The field is written
by `ingest/store.py:711`: `paper_count = len({c.paper_id for c in chunks})` where
`chunks` is the batch passed to a single `write_chunks()` call. When the bulk ingest
loop calls `write_chunks` per-paper, the last batch contains one paper's chunks, and that
is what `corpus-version.json` reflects. The actual paper count must be queried from
LanceDB directly (unique `paper_id` values) — not from the marker file.

**AC #1 MUST be reworded.** The brief says "paper_count >= 80 (allowing for ar5iv-miss
fail-rate ≤ 20%)." This is wrong on two axes:

1. Bridgeland has 39 papers total (not 100). 80% of 39 = 31.2 → floor = 31. The correct
   threshold is `unique_paper_ids >= 31`.
2. `corpus-version.json`'s `paper_count` field does NOT report the cumulative total. An
   AC checking this field will never show 39.

**Correct AC wording:** "When the ingest completes, `SELECT COUNT(DISTINCT paper_id)
FROM chunks` returns >= 31 for bridgeland-stability and >= 10 for shimura-varieties."
(80% of 12 = 9.6 → floor = 10.)

Since both LanceDB indices are already correct (39 and 12 papers respectively), the
implementer's verification task is to confirm these counts via the LanceDB query, then
document them.

### BM25 index status — partial gap

BM25 directories `var/arxmcp/index/bm25/v157/` (bridgeland) and
`var/arxmcp/index/bm25/v49/` (shimura) BOTH exist with `bm25.pkl` + `chunk_ids.json`.
NEITHER has a `.notebook_slug` sentinel file. The m6 rectification commit (`c6229fa`)
added sentinel logic to `notebook_ingest.py` — but these indices were built BEFORE that
fix landed (they were built during the pre-m6 bootstrap). The sentinel gap creates a
latent BM25 collision risk if the operator re-runs `notebook_ingest.py` for either
notebook: the sentinel check will find no sentinel → write it → succeed. But the risk is
real if a THIRD notebook is ingested that happens to land on v157 or v49.

**Recommendation for implementer:** After verifying the existing BM25 indices are
correct, manually write the sentinel files:

```bash
echo "bridgeland-stability" > var/arxmcp/index/bm25/v157/.notebook_slug
echo "shimura-varieties" > var/arxmcp/index/bm25/v49/.notebook_slug
```

### AC #3 path deviation (from m6 implementation summary)

The brief says BM25 at `var/arxmcp/notebooks/<slug>/index/bm25/v<N>/`. The actual path
is the global `var/arxmcp/index/bm25/v<N>/`. From `m6/implementation-summary.md`:
"BM25 output path: the synthesis 'Disagreement 2' resolves in favor of the global BM25
path... Modifying `build_bm25_index` to accept an override is out of m6's scope."
**AC #3 must be verified against `var/arxmcp/index/bm25/v157/` and `v49/`, not a
per-notebook subdirectory.**

### AC #4 — `validate_eval_fixtures.py` has NO per-notebook scope support

The brief says "Both notebook fixtures pass `tools/validate_eval_fixtures.py` (extended
to accept the per-notebook scope field)." The script at HEAD accepts only `--fixture` and
`--chunks-dir` arguments. It validates against a fixed `tests/eval/fixtures/queries.json`
(20 global queries, `TARGET_QUERY_COUNT = 20`). It has zero awareness of `notebook_slug`
or per-notebook queries.json. Both notebook `queries.json` files already exist and have a
`notebook_slug` field — but `validate_eval_fixtures.py` cannot validate them.

The implementer must decide: extend the script OR write a separate lightweight notebook-
fixture validator. **Recommendation: write a separate `tools/validate_notebook_fixtures.py`
(~50 LOC)** that checks schema_version, notebook_slug match, queries array non-empty, and
`expected_relevant_papers` references valid paper_ids from the notebook's `papers.txt`.
This avoids coupling the global eval fixture to the per-notebook fixture schema.

### m6 scripts wire correctly for re-runs

`tools/notebook_ingest.py` correctly uses `run_bulk_ingest(paper_ids, lancedb_staging_path=lancedb_path)` — NOT `ARXMCP_LANCEDB_PATH`. This was the m6 "Disagreement 4" correction; both researchers independently caught the brief error, confirming the implementation is correct. The implementer must invoke:

```bash
uv run python tools/notebook_ingest.py bridgeland-stability
uv run python tools/notebook_ingest.py shimura-varieties
```

NOT `make ingest` (which runs `ingest.bulk_ingest` against the GLOBAL staging path and
has no slug parameter) and NOT `ARXMCP_LANCEDB_PATH=... make ingest` (the env var is the
SERVER's path override, not a bulk_ingest override).

### `ARXMCP_LANCEDB_PATH` wiring for AC #5

`server/config.py::Config` uses `env_prefix="ARXMCP_"` with field `lancedb_path: Path`.
Therefore `ARXMCP_LANCEDB_PATH=var/arxmcp/notebooks/bridgeland-stability/lancedb` will
override `config.lancedb_path` at server startup. This is the correct approach for AC #5.

## Prior decisions and lessons

From `m6/implementation-summary.md`: "The per-notebook corpus_version is unique
per notebook (LanceDB MVCC, each notebook starts at version 1), so v<N> dirs are
effectively per-notebook by version-integer separation." This claim was WRONG — the
adversary caught it as F2 (HIGH). The BM25 sentinel fix (`notebook_ingest.py:128-156`)
corrects it. The pre-existing BM25 indices lack sentinels because they predate the fix.

From the m6 critique (`critique-adversary.md`): F1 (CRITICAL path traversal in purge),
F2 (HIGH BM25 collision), F3 (HIGH symlink), F4 (HIGH local-cache bypass), F5 (MEDIUM
manifest parsing), F6 (MEDIUM EOF handling), F7 (LOW stale BM25 warning) — all closed in
`c6229fa`. The sentinel file approach for F2 is the only relevant one for m4.

From MEMORY.md (E13 series): doc placement rule — new Markdown goes under `.claude/`,
not `docs/`. This milestone doesn't ship new Markdown docs unless writing a validation
runbook; if it does, the correct path is `.claude/docs/notebook-ingest-verification.md`.

`KMP_DUPLICATE_LIB_OK=TRUE` in `tests/conftest.py` must not be removed. This milestone
runs no new tests, so no risk here.

## External sources

**ar5iv coverage spot-check (WebFetch verified):**

- `0712.1083` (bridgeland): ar5iv renders successfully → "Polynomial Bridgeland stability
  conditions and the large volume limit" with complete math content.
- `2604.26204` (not in papers.txt but tested): renders successfully → "Stability and
  Fourier-Mukai transforms on an elliptic surface."
- `2310.16184` (shimura): renders successfully → "Shimura varieties" lecture notes with
  full math.

**ALL 39 bridgeland papers and ALL 12 shimura papers already have local HTML** at
`var/arxmcp/corpus/parsed/<id>/index.html` (verified via bash loop). The `notebook_fetch.py`
call would be a no-op (`from_cache=39 fetched=0 missing=0` for bridgeland). Running it
is harmless but unnecessary since the data is pre-populated.

**MCP spec (version 2025-06-18) — tools/list smoke test recipe:**

From `https://modelcontextprotocol.io/specification/2025-06-18/basic/transports`:
The Streamable HTTP transport requires a two-step init. The client MUST:
1. POST an `InitializeRequest` to `/mcp` with `Accept: application/json, text/event-stream`
2. POST an `InitializedNotification` with the returned `Mcp-Session-Id`
3. Then POST the `tools/list` request.

Copy-pasteable recipe for AC #5 verification:

```bash
# Step 1 — launch daemon against bridgeland notebook
ARXMCP_LANCEDB_PATH=var/arxmcp/notebooks/bridgeland-stability/lancedb \
  ARXMCP_CONTACT_EMAIL=you@example.com \
  uv run python -m server.main &
SERVER_PID=$!
sleep 3  # wait for readyz

# Step 2 — initialize session
SESSION_RESPONSE=$(curl -s -X POST http://127.0.0.1:7733/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Origin: http://127.0.0.1:7733" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke-test","version":"1.0"}}}')
echo "$SESSION_RESPONSE"
SESSION_ID=$(echo "$SESSION_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('result',{}).get('_meta',{}).get('session_id',''))" 2>/dev/null)

# Step 3 — send InitializedNotification (required per MCP spec)
curl -s -o /dev/null -X POST http://127.0.0.1:7733/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Origin: http://127.0.0.1:7733" \
  ${SESSION_ID:+-H "Mcp-Session-Id: $SESSION_ID"} \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'

# Step 4 — tools/list
curl -s -X POST http://127.0.0.1:7733/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Origin: http://127.0.0.1:7733" \
  ${SESSION_ID:+-H "Mcp-Session-Id: $SESSION_ID"} \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

kill $SERVER_PID
```

The response to `tools/list` should contain all 7 tools (search_papers, get_chunk,
find_equation, get_definitions, find_lemma_by_name, get_paper, cite_neighbors).

## Failure mode analysis

Six plausible failure modes when running ingest end-to-end:

**FM-1: ar5iv-miss rate spike above 20% threshold on cold run.**
Trigger: a paper ID in papers.txt has no ar5iv HTML and no local .tex source.
Observable: `notebook_fetch.py` summary `missing=N` for N > 0; `notebook_ingest.py`
shows `papers_failed=N`. Detection: `ops/parser-failures.jsonl` under the notebook dir.
Mitigation: all 51 paper IDs across both notebooks have pre-cached local HTML;
`from_cache` will dominate. The 20% threshold only matters if the operator runs against a
fresh machine — in that case `notebook_fetch.py` must be run first.

**FM-2: LanceDB write-lock contention.**
Trigger: a daemon (server process) is already serving one of the notebook LanceDB paths
while `notebook_ingest.py` attempts to write to it.
Observable: `lancedb.connect()` or `dataset.append()` hangs or raises `DatabaseError`.
The MCP server opens LanceDB in READ mode; LanceDB MVCC allows concurrent readers +
one writer. However, the server does NOT hold a write lock. The primary risk is if a
second `notebook_ingest.py` is run concurrently. Detection: OS-level file lock on
`chunks.lance/`. Mitigation: single-operator workflow; run ingest then start server.

**FM-3: BM25 corpus_version collision — NEW RISK EXPOSED BY THIS RESEARCH.**
Trigger: the operator deletes and re-creates a notebook (or two notebooks land on the
same MVCC version integer). Existing BM25 dirs v157 and v49 have NO sentinel files.
Observable: `notebook_ingest.py` detects no sentinel → writes it → succeeds on first
notebook. On second notebook, if it hits v157 or v49, the sentinel check fires and raises
`NotebookError` with recovery instructions. Detection: sentinel file `bm25_v_dir/.notebook_slug`.
Mitigation: manually write sentinel files BEFORE any re-run (see recommendation below).

**FM-4: `validate_eval_fixtures.py` fails with wrong fixture path.**
Trigger: AC #4 requires the script to "accept per-notebook scope field." The script does
not. Running it against a notebook `queries.json` with `TARGET_QUERY_COUNT = 20` will
fail because per-notebook `queries.json` files do NOT have 20 queries (bridgeland has
~10, shimura has ~8).
Observable: `FAIL: expected 0 or 20 queries; got N` to stderr, exit code 1.
Mitigation: do NOT invoke `validate_eval_fixtures.py` against per-notebook fixtures
without extension. Write a separate validator.

**FM-5: `corpus-version.json` `paper_count` check in AC #1 returns wrong value.**
Trigger: the implementer reads `corpus-version.json` to check `paper_count` and sees
`paper_count: 1` — a false AC failure. The field reflects the last `write_chunks` batch,
not the cumulative database count.
Observable: false negative — the ingest succeeded but the AC check reports failure.
Mitigation: use `SELECT COUNT(DISTINCT paper_id) FROM chunks` query via `lancedb.connect()`.

**FM-6: Server startup fails against per-notebook LanceDB (missing schema fields).**
Trigger: `server/corpus.py` may expect columns present in the main LanceDB that are
absent from per-notebook indices (e.g. `embedding_eq` column is "reserved and always
NULL" per CLAUDE.md §7). If the per-notebook schema differs, `open_table('chunks')` may
raise.
Observable: server fails `/readyz`, logs schema mismatch. Detection: check server logs.
Mitigation: both per-notebook LanceDB tables were built by the same `ingest/store.py`
code path → schema is identical. However, the operator should check `/readyz` returns
200 before running the `tools/list` smoke test.

## Recommendation

**The implementation is largely already done.** Both notebooks have correct LanceDB
indices (39 and 12 papers) and BM25 indices (v157 and v49). The implementation path is:

1. Query both LanceDB tables for unique paper_id count to verify AC #1 (use lancedb
   directly, NOT corpus-version.json's `paper_count`).
2. Write the two BM25 sentinel files manually (`echo "bridgeland-stability" >
   var/arxmcp/index/bm25/v157/.notebook_slug` and same for shimura/v49).
3. Verify AC #3 by listing `var/arxmcp/index/bm25/v157/` and `v49/`.
4. Extend `tools/validate_eval_fixtures.py` OR write `tools/validate_notebook_fixtures.py`
   to accept per-notebook queries.json. The separate script is preferable (30 LOC,
   avoids coupling global-fixture schema to per-notebook schema).
5. Run the MCP smoke test using the curl recipe above for AC #5.
6. Correct the AC #1 wording in state.json to use unique paper_id queries.

**Do NOT re-run `notebook_fetch.py` or `notebook_ingest.py` unless the operator
intentionally wants to refresh the data.** All data is pre-populated.

## Open questions

1. **Does the new `validate_notebook_fixtures.py` need to cover `min_query_count`?**
   Recommendation: yes — enforce at least 5 queries per notebook (bridgeland has ~10,
   shimura has ~8 per the current queries.json; set floor at 5 to leave room for future
   revision).

2. **Does AC #5 require a persistent daemon or a single request?** Recommendation: a
   single foreground start, smoke test, and kill is sufficient. The brief does not require
   leaving a daemon running.

3. **The `corpus-version.json` shows `version: 157` for bridgeland but `version: 49` for
   shimura. These are global MVCC counters across ALL LanceDB writes in the repo (the
   shared staging LanceDB advanced the counter). Is this expected?** Yes — the per-notebook
   LanceDB is a separate database instance; its version counter starts at 0 and advances
   independently. The version numbers shown are the versions within each notebook's own
   LanceDB, not the global counter. No action needed.

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| HTTP GET (operator-initiated) | `ar5iv.labs.arxiv.org` | `notebook_fetch.py` fetches HTML for any paper_ids not already in local cache. ALL 51 papers are pre-cached, so this will be a no-op; but calling the script as written will still open HTTP connections to check. The fetch inherits the 100 MB cap, 5s timeout, and 3s politeness sleep from `ingest/ar5iv_fetch.py`. |

No git push, no GitHub issue creation, no infrastructure mutation. The milestone is
purely local except for the above operator-side HTTP calls (which occur only if the
local HTML cache is cold, which it is not).
