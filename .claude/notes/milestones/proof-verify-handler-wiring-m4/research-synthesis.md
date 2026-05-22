# Research Synthesis — proof-verify-handler-wiring-m4

**Orchestrator merge of:** `research-brief-1.md`, `research-brief-2.md`
**Generated:** 2026-05-22T02:30:00Z
**Mode:** standard (2× Sonnet in parallel)

## TL;DR for the implementer

**Most of the work is already done.** Both notebooks have populated
per-notebook LanceDB indices (39 papers bridgeland, 12 papers shimura)
from the m5 spike run; both have BM25 indices at the global
`var/arxmcp/index/bm25/v<N>/`. The implementer's job is:

1. **Verify the indices** via a LanceDB `COUNT(DISTINCT paper_id)`
   query (NOT `corpus-version.json::paper_count`, which is per-batch
   and = 1).
2. **Write the missing BM25 sentinels** (`v157/.notebook_slug` and
   `v49/.notebook_slug`) to close the latent collision risk that
   m6's F2 closure designed for.
3. **Write `tools/validate_notebook_fixtures.py`** (≤ 100 LOC) — a
   NEW validator for the notebook `queries.json` schema, separate
   from the existing `tools/validate_eval_fixtures.py` (which has
   a closed-schema guard incompatible with the notebook format).
4. **Verify daemon launch + `tools/list` works** against each
   per-notebook LanceDB via the docs/ops/notebook-modes.md
   `tools/list` recipe.
5. **Optionally re-run `notebook_ingest.py` once per notebook** to
   write sentinels via the script (alternative to manual step 2).
   The LanceDB ingest itself is idempotent on already-populated
   tables — no risk of corruption.
6. **Add a small CHANGES.md note + tests for the new validator.**

No code that already exists needs to change. Estimated 2-3 hours of
work, mostly verification + the new validator. Pure-local; no
external writes beyond optional ar5iv HTTP probes that resolve to
cache hits.

## Resolved disagreements

### Disagreement 1 — How to close the BM25 sentinel gap

**R-1:** Run `notebook_ingest.py` once per notebook to let it write
the sentinels (the script's existing logic handles unclaimed v-dirs
by writing the sentinel on first claim).

**R-2:** Manually `echo "bridgeland-stability" > .../v157/.notebook_slug`
and same for shimura/v49.

**Synthesis: do BOTH but in this order.** Prefer R-1's approach
(run the script) because it exercises the m6 ingest path end-to-end
as the AC requires, AND writes the sentinel as a side effect. If
the script's sentinel-write path fails for any reason, fall back to
R-2's manual write as recovery. The script run is idempotent on
already-populated LanceDB tables (LanceDB MVCC handles concurrent
re-writes with no data loss; the `corpus-version.json::version`
will advance to v158/v50 reflecting the no-op re-write batch).

### Disagreement 2 — `tools/list` MCP smoke-test recipe

**R-1:** Simple stateless `POST /mcp/` with `tools/list` directly,
no initialize handshake (matches the existing m3 `docs/ops/notebook-modes.md`
recipe verbatim).

**R-2:** Full MCP 2025-06-18 spec lifecycle: `initialize` →
`notifications/initialized` → `tools/list`, with `Mcp-Session-Id`
header threading.

**Synthesis: R-1 wins for the runbook test, R-2's recipe goes into
a follow-up issue.** The simpler stateless recipe works against the
current arXMCP server (verified empirically by m3 — the runbook
ships this recipe and the m3 adversary critique reviewed it without
flagging non-compliance). The spec MUST clause exists but the
FastMCP/Streamable HTTP server allows stateless tool calls in
practice. The implementer uses the simpler recipe in the
verification check; if a future MCP-spec-tightening milestone wants
to enforce the full handshake, R-2's recipe is recorded here for
reuse.

### Disagreement 3 — `validate_eval_fixtures.py` extend vs new tool

**R-1:** Write a separate `tools/validate_notebook_fixtures.py`.
**R-2:** Write a separate `tools/validate_notebook_fixtures.py`.

**Synthesis: agreement — separate tool.** Both researchers
independently reached the same conclusion. The existing validator
has `_validate_query_structure` and an F3 closed-schema guard that
explicitly rejects extra top-level keys; coupling it to the
notebook schema (which has `notebook_slug`, `notebook_display_name`,
`curated_by`, `difficulty_classes`, etc.) would require widening
the guard and adding a `--mode notebook` flag whose surface is
larger than just writing a small dedicated validator.

The new script's contract (combining R-1's recommendation with
R-2's open-question #1):

- CLI: `uv run python tools/validate_notebook_fixtures.py <slug>`
- Reads: `var/arxmcp/notebooks/<slug>/queries.json` and
  `var/arxmcp/notebooks/<slug>/papers.txt`
- Validates:
  - Required top-level keys: `schema_version`, `notebook_slug`,
    `notebook_display_name`, `created_at`, `queries`
  - `notebook_slug` matches the CLI arg
  - `queries` non-empty (floor: ≥ 5 per R-2 open-question #1)
  - Each query has `id`, `text`, `expected_relevant_papers`,
    `difficulty`
  - Each `expected_relevant_papers` entry is a valid arXiv ID
    AND appears in the notebook's `papers.txt`
  - No duplicate query `id` values
- Exit: 0 on pass, non-zero with structured error on fail.
- Tests: `tests/tools/test_validate_notebook_fixtures.py` covering
  happy path + each failure class.

### Disagreement 4 — Where the verification-runbook doc lives

**R-1:** `.claude/docs/notebook-ingest-verification.md` (agent-internal).
**R-2:** Doesn't propose one (treats AC #5 as a one-shot smoke test).

**Synthesis: skip the new doc.** R-2 is right — AC #5 is a one-shot
operational check ("an operator can launch a daemon"). The recipe
already lives in `docs/ops/notebook-modes.md` (m3). The
implementer's verification artifact for AC #5 is a successful
run of that recipe (recorded in `implementation-summary.md`); no
new agent-internal doc needed. Avoid doc-bloat.

## Load-bearing facts the implementer needs

### Verified state (ground-truthed by both researchers, 2026-05-21/22)

| Notebook | Papers in `papers.txt` | Papers in LanceDB | LanceDB version | BM25 v-dir | Sentinel present? |
|---|---|---|---|---|---|
| bridgeland-stability | 39 | 39 (4505 chunks) | 157 | `var/arxmcp/index/bm25/v157/` | NO |
| shimura-varieties | 12 | 12 (3625 chunks) | 49 | `var/arxmcp/index/bm25/v49/` | NO |

### `corpus-version.json::paper_count` is NOT a cumulative count

Per `ingest/store.py:711` — `paper_count = len({c.paper_id for c in
chunks})` computed per-batch. Per-paper ingest sets batch size to 1
→ the marker always reads `paper_count: 1` regardless of cumulative
total. **Do NOT use this field to verify AC #1.** Use:

```python
import lancedb
db = lancedb.connect("var/arxmcp/notebooks/bridgeland-stability/lancedb")
tbl = db.open_table("chunks")
n = len(set(tbl.to_pandas()["paper_id"].tolist()))
print(n)  # expected: 39
```

### Corrected AC arithmetic

The brief's `paper_count >= 80` was written for a 100-paper notebook.
For the actual notebooks:

| Notebook | Total papers | 80% (allowing 20% ar5iv-miss) | AC threshold |
|---|---|---|---|
| bridgeland-stability | 39 | 31.2 | `unique_paper_ids >= 31` |
| shimura-varieties | 12 (HTML; 2 PDFs deferred) | 9.6 | `unique_paper_ids >= 10` |

Implementer should update the implementation-summary checkbox
status to reflect this corrected threshold and explicitly note the
correction in the deviations section.

### AC #3 BM25 path drift (documented at m6)

Brief says BM25 at `var/arxmcp/notebooks/<slug>/index/bm25/v<N>/`.
Actual path is the **global** `var/arxmcp/index/bm25/v<N>/` per
`m6/research-synthesis.md` Disagreement 2 resolution
(brief→implementation drift was approved at m6 because modifying
`ingest/bm25_indexer.py` to accept a per-notebook override was
out of m6 scope).

Verify AC #3 against the global path:

```bash
ls var/arxmcp/index/bm25/v157/  # bm25.pkl + chunk_ids.json + (after rect) .notebook_slug
ls var/arxmcp/index/bm25/v49/   # same shape
```

### Notebook `queries.json` schema (verbatim, both notebooks)

```json
{
  "schema_version": "1.0",
  "notebook_slug": "<slug>",
  "notebook_display_name": "<human-readable>",
  "created_at": "YYYY-MM-DD",
  "curated_by": "<author>",
  "difficulty_classes": { /* taxonomy */ },
  "queries": [
    {
      "id": "<slug>-q<N>",
      "difficulty": "easy|medium|hard",
      "text": "<query text>",
      "expected_relevant_papers": ["<arxiv_id>", ...],
      "notes": "<optional>"
    }
  ]
}
```

vs. the existing `tools/validate_eval_fixtures.py` schema:
`{schema_version, chunker_version, created_at, queries[{query_id,
query_text, relevant_chunks[{chunk_id, relevance}]}]}` — paper-level
vs chunk-level relevance is a fundamental shape difference.

### `notebook_ingest.py` invocation contract (m6 ship)

```bash
uv run python tools/notebook_ingest.py bridgeland-stability
uv run python tools/notebook_ingest.py shimura-varieties
```

NOT `make ingest` (different code path — global staging only). NOT
`ARXMCP_LANCEDB_PATH=... make ingest` (the env var is the server's
read path, not a bulk_ingest write override).

The script:
- Validates slug
- `mkdir(parents=True, exist_ok=True)` for `lancedb/` and `ops/`
- Runs `run_bulk_ingest(paper_ids, lancedb_staging_path=<nb_dir>/lancedb/, log_path=<nb_dir>/ops/ingestion.log, failures_path=<nb_dir>/ops/parser-failures.jsonl)`
- Reads `corpus-version.json::version` post-ingest
- Checks `.notebook_slug` sentinel for BM25 collision (raises with
  recovery instructions if a different notebook owns the v<N> dir)
- Calls `build_bm25_index(str(lancedb_path), corpus_version=version)`
- Writes `var/arxmcp/index/bm25/v<N>/.notebook_slug` with the slug

### `tools/list` smoke-test recipe (per Synthesis D2 — R-1 form)

```bash
# Launch daemon against bridgeland notebook (per docs/ops/notebook-modes.md Mode 1)
mkdir -p var/arxmcp/notebooks/bridgeland-stability/ops
ARXMCP_LANCEDB_PATH=var/arxmcp/notebooks/bridgeland-stability/lancedb \
ARXMCP_BIND_PORT=7733 \
ARXMCP_CONTACT_EMAIL=you@example.com \
  nohup uv run python -m server.main \
  &> var/arxmcp/notebooks/bridgeland-stability/ops/daemon.log &
echo $! > var/arxmcp/notebooks/bridgeland-stability/ops/daemon.pid
sleep 3  # wait for /readyz

# Verify
curl -s -X POST -H 'Content-Type: application/json' \
  -H 'Accept: application/json,text/event-stream' \
  http://127.0.0.1:7733/mcp/ \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | jq '.result.tools | length'
# expected: 7

# Stop
kill -TERM "$(cat var/arxmcp/notebooks/bridgeland-stability/ops/daemon.pid)"
rm -f var/arxmcp/notebooks/bridgeland-stability/ops/daemon.pid
```

Repeat with `bridgeland-stability` → `shimura-varieties` and
`7733` → `7734`.

## Failure modes the implementer must inoculate against

From R-2's catalog + R-1's BM25-sentinel detail:

1. **Reading `corpus-version.json::paper_count` and concluding ingest
   failed.** AC #1 verification must use the LanceDB query, not the
   marker field. (R-1 + R-2.)
2. **Re-running ingest while a daemon is serving the same path.**
   LanceDB MVCC permits the write but the daemon's `corpus_version`
   stays pinned at startup → stale Tier-1 cache. m3 runbook FM5
   covers the recovery (stop daemon, ingest, restart). (R-2.)
3. **Hitting a third notebook on BM25 v157 or v49.** Today's
   sentinel gap = no protection. Closing the gap (synthesis D1) is
   itself a mitigation. (R-1 + R-2.)
4. **`validate_eval_fixtures.py` invoked on a notebook queries.json
   fails immediately.** Don't do it. Use the new validator. (R-1 + R-2.)
5. **Server `/readyz` fails on per-notebook LanceDB because of
   schema drift.** Both per-notebook tables were built by the same
   `ingest/store.py` path → schemas are identical. Risk is
   theoretical. (R-2.)
6. **The `ar5iv-miss rate > 20%` AC threshold fires on a cold
   machine.** All 51 papers are pre-cached at
   `var/arxmcp/corpus/parsed/`; on a fresh machine, `notebook_fetch.py`
   must be run first. This is documented in m3's FM bracket. (R-2.)

## Acceptance-criteria mapping (with corrected thresholds)

From the milestone brief, with synthesis corrections noted:

- [ ] **AC #1** — bridgeland LanceDB exists with corpus-version.json
  AND **unique paper_id count >= 31** (corrected from `paper_count
  >= 80`). Verification via LanceDB `COUNT(DISTINCT paper_id)`.
- [ ] **AC #2** — Same for shimura, threshold `>= 10`.
- [ ] **AC #3** — BM25 indices at the **global**
  `var/arxmcp/index/bm25/v<N>/` (path corrected from per-notebook
  per m6 Disagreement 2). Each must have `.notebook_slug` sentinel
  after this milestone.
- [ ] **AC #4** — Notebook fixtures validated by NEW
  `tools/validate_notebook_fixtures.py` (separate from
  `validate_eval_fixtures.py` per synthesis D3).
- [ ] **AC #5** — Daemon launches against per-notebook LanceDB and
  `tools/list` returns 7 tools.

## Open questions (deduped union)

1. **What floor should `validate_notebook_fixtures.py` enforce on
   query count?** Bridgeland has ~10 queries, shimura has ~8. R-2
   recommends ≥ 5 to leave room for future revision.
   **Synthesis resolution: floor = 5.** Encoded as a constant
   `MIN_NOTEBOOK_QUERIES` in the new validator; can be tightened
   later if needed.

2. **Should the implementer re-run `notebook_ingest.py` to write
   sentinels, OR `echo > .../v<N>/.notebook_slug` manually?**
   Synthesis D1 resolution: run the script. Idempotent on the
   LanceDB table; exercises the m6 path end-to-end (which is
   itself a verification artifact).

3. **Does AC #5 require a persistent daemon or one-shot?** R-2:
   one-shot launch + smoke + kill is sufficient. **Synthesis
   resolution: one-shot.** Record the curl output in the
   implementation-summary.

4. **Does the new `validate_notebook_fixtures.py` need a test in
   `tests/`?** Yes — by project convention every new tool gets
   tests. Add `tests/tools/test_validate_notebook_fixtures.py`
   following the same shape as `tests/tools/test_notebook_scripts.py`
   (which m6 added).

None are blockers.

## External writes required

| Type | Target | Why |
|---|---|---|
| ar5iv HTTP probe (optional) | `ar5iv.labs.arxiv.org` | If the implementer re-runs `notebook_fetch.py`, the fetcher opens HTTP connections. ALL 51 papers are pre-cached at `var/arxmcp/corpus/parsed/`, so this resolves to `from_cache=N` with 0 live fetches. ARXMCP_CONTACT_EMAIL must be set. Skippable; not required for AC. |

**No git push, no PR, no GH issue, no infra mutation, no Slack /
external API.** Phase 4 has no blocking external-write gates;
the ar5iv probe is operator-side and harmless.

## Orchestrator synthesis note

This milestone is unusual: the operational substrate it's
nominally about (running the ingest scripts) is already done by
the time the milestone fires, because the m5 spike ran end-to-end
against the per-notebook indices. The milestone reduces to:
(a) verifying the existing indices satisfy the corrected AC,
(b) closing the BM25 sentinel gap (which is what m6 F2 designed
the sentinel for in the first place — but the pre-m6 BM25 dirs
predate the fix), and (c) shipping a new tiny validator to make
the notebook `queries.json` fixtures auditable.

Both researchers independently reached identical positions on the
4 substantive points (notebooks already ingested, AC #1 needs
rewording, AC #3 path drift, separate validator over extension).
The two genuine disagreements (D1 and D2) resolved cleanly with
explicit reasoning above.

Estimated implementation surface: ≤ 300 LOC across
`tools/validate_notebook_fixtures.py` (~80 LOC) + the test file
(~120 LOC) + the implementation-summary (~80 LOC of docs). One
sentinel file written via the script run + one CHANGES.md entry.
**Inline path** is correct (well under the 500 LOC / 5 file
threshold).
