# Research Brief — proof-verify-handler-wiring-m4

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-21T21:00:00Z

---

## In-codebase context

### Current state of the two notebook trees (ground-truthed 2026-05-21)

**Both notebooks already have LanceDB indices fully populated by the m5 spike.**
The m5 spike (`poc.py`) ran against `var/arxmcp/notebooks/bridgeland-stability/lancedb`
and `var/arxmcp/notebooks/shimura-varieties/lancedb` directly (confirmed at
`.claude/notes/spikes/wiring-rerank-lift-100paper/poc.py:23,28`). The ingest
was performed paper-by-paper before the spike ran.

Verified state as of 2026-05-21:

| Notebook | LanceDB data files | Versions | corpus-version.json exists? | BM25 (global v<N>) | ops/ dir |
|---|---|---|---|---|---|
| bridgeland-stability | **39** | 157 | yes (`version=157`, `paper_count=1`*) | `v157/` exists (no sentinel) | **absent** |
| shimura-varieties | **12** | 49 | yes (`version=49`, `paper_count=1`*) | `v49/` exists (no sentinel) | **absent** |

*`paper_count=1` is a known artifact: `write_corpus_version_marker` at
`ingest/store.py:711` computes `len({c.paper_id for c in chunks})` over the
BATCH being written, not the cumulative corpus. Per-paper ingest sets batch
size to 1 → `paper_count=1` in the final marker. The actual paper count is
correctly reflected in data-file count (39 Lance files = 39 papers for
bridgeland; 12 = 12 for shimura). The corpus is correct; the marker field is
misleading for per-paper ingest runs.

**BM25 status — critical detail:** `var/arxmcp/index/bm25/v157/` and
`var/arxmcp/index/bm25/v49/` both contain `bm25.pkl` + `chunk_ids.json` but
**no `.notebook_slug` sentinel**. These were built before `notebook_ingest.py`
existed (the sentinel was added as a rectification fix). `notebook_ingest.py`
only errors if the sentinel EXISTS AND differs from the current slug; a
missing sentinel is treated as unclaimed → the build will proceed. First run
of `notebook_ingest.py` will write the sentinel post-build.

**ops/ directories are absent.** Both notebook dirs lack `ops/`. The
`notebook_ingest.py` code creates them via `ops_dir.mkdir(parents=True,
exist_ok=True)` on every run (line 91) — no manual mkdir needed.

**papers.txt actual line counts (non-comment, non-blank):**
- bridgeland-stability: **39 paper IDs** (46 total lines; 7 comment/blank)
- shimura-varieties: **12 paper IDs** (16 total lines; 4 comment/blank)

### AC arithmetic discrepancy — FLAGGED

**The brief's `paper_count >= 80` AC does not match notebook sizes.**

- bridgeland-stability has 39 papers. Allowing 20% ar5iv-miss: floor(39 × 0.80)
  = **31 papers minimum** (32 with ceiling). Recommendation: `paper_count >= 31`.
- shimura-varieties has 12 HTML-ingestible papers (2 PDFs in `pdf-deferred/`
  are excluded from ingest). Allowing 20% ar5iv-miss: floor(12 × 0.80) = **9
  papers minimum** (10 with ceiling). Recommendation: `paper_count >= 9`.

However — **the `paper_count` field in `corpus-version.json` records the
per-batch count (=1 for per-paper ingest), not the cumulative corpus count.**
The implementer CANNOT use `corpus-version.json::paper_count` to verify the
AC. The correct verification metric is:
- count of Lance data files in `chunks.lance/data/` (one per paper), OR
- a Python query: `len(set(lancedb.open_table("chunks").to_pandas().paper_id))`

**The AC must be reframed to count distinct paper_ids in the table, not read
`corpus-version.json::paper_count`.**

### Load-bearing constraint from design constitution

From `.claude/notes/07-multi-agent-caching.md` (load-bearing for daemon AC):

> "Tool definitions are byte-stable. Pin tool JSON schemas. Sort properties
> alphabetically at serialization time. Freeze descriptions as constants in
> source. A casual edit to a tool description blows every sub-agent's cache.
> ... bump the hash deliberately when intentionally changing schema; treat as
> an API version bump."

This milestone adds no new MCP tools → no re-pinning of
`EXPECTED_TOOL_SCHEMA_SHA256` required.

From `CLAUDE.md §4.7`:
> "`assert` is BANNED for invariants — Python `-O` strips them. Use `if …
> raise RuntimeError(…)` instead."

---

## Prior decisions and lessons

### m6 script surface — what's actually shipped

**`tools/notebook_fetch.py`**

Entry point: `uv run python tools/notebook_fetch.py <slug>`

Reads `papers.txt` → pre-validates each line via `is_valid_paper_id` →
delegates to `ingest.ar5iv_fetch.try_cache` with a 3s politeness sleep between
non-cache-hit fetches. Writes to the **global** `var/arxmcp/corpus/parsed/`
(not per-notebook). Does NOT skip papers already in LanceDB — fetches HTML
independently.

Exit codes: 0 if no malformed/missing entries (rate-limited is exit-0);
1 if any `malformed` or unrecoverable `missing`.

Summary printed to stdout:
```
fetched=N from_cache=M missing=K rate_limited=R malformed=J
```

**`tools/notebook_ingest.py`**

Entry point: `uv run python tools/notebook_ingest.py <slug>`

Sequence:
1. `validate_slug(slug)` — slug regex as first check
2. Creates `<nb_dir>/lancedb/` and `<nb_dir>/ops/` via `mkdir(parents=True, exist_ok=True)`
3. Calls `run_bulk_ingest(paper_ids, lancedb_staging_path=<nb_dir>/lancedb/, log_path=<nb_dir>/ops/ingestion.log, failures_path=<nb_dir>/ops/parser-failures.jsonl)`
4. Reads `corpus-version.json::version` from the per-notebook lancedb dir
5. Checks `.notebook_slug` sentinel for BM25 collision
6. Calls `build_bm25_index(str(lancedb_path), corpus_version=corpus_version)`
   — writes to **global** `var/arxmcp/index/bm25/v<N>/`, NOT per-notebook
7. Writes sentinel `var/arxmcp/index/bm25/v<N>/.notebook_slug`

Exit codes: 0 if all papers succeeded; 1 if any failures or BM25 raised.

**BM25 output path drift from brief:** The brief specifies
`var/arxmcp/notebooks/<slug>/index/bm25/v<N>/`. The actual output is
`var/arxmcp/index/bm25/v<N>/`. This is documented drift from
`proof-verify-handler-wiring-m6/research-synthesis.md §Disagreement 2`:
> "R-1's approach wins ... modifying `ingest/bm25_indexer.py` to add a
> per-notebook output path is out of scope ... The implementation will write
> to `var/arxmcp/index/bm25/v<N>/`."

**`tools/_notebook_common.py`** — slug regex `^[a-z][a-z0-9-]{2,30}$`,
path layout constants, `validate_slug`, `notebook_dir` (symlink-refusing),
`read_paper_ids_from_papers_txt`.

### m5 spike corpus resolution

The m5 spike (`wiring-rerank-lift-100paper`) ran against the **per-notebook
LanceDB** (`var/arxmcp/notebooks/bridgeland-stability/lancedb` and
`var/arxmcp/notebooks/shimura-varieties/lancedb`), NOT the global
`var/arxmcp/index/lancedb-staging`. This is confirmed at `poc.py:23,28`.
The per-notebook LanceDB indices were already built before the spike ran and
are currently populated (39 papers bridgeland, 12 papers shimura). The m5
verdict was NO (rerank adds zero lift, regresses top-1 by 10pp).

### validate_eval_fixtures.py schema mismatch — CRITICAL CONFLICT

**The notebook `queries.json` files use a completely different schema than
what `validate_eval_fixtures.py` expects.** This is a full incompatibility,
not a minor gap.

Notebook `queries.json` schema (bridgeland + shimura, both identical):
```json
{
  "schema_version": "1.0",
  "notebook_slug": "bridgeland-stability",
  "notebook_display_name": "Bridgeland stability conditions",
  "created_at": "2026-05-21",
  "curated_by": "...",
  "difficulty_classes": {...},
  "queries": [
    {
      "id": "bridge-q1",
      "difficulty": "easy",
      "text": "...",
      "expected_relevant_papers": ["0705.3794", "0712.1083"],
      "notes": "..."
    }
  ]
}
```

`validate_eval_fixtures.py` expects (per `_validate_query_structure`):
- Top-level required keys: `schema_version`, `chunker_version`, `created_at`, `queries`
- Per-query required keys: `query_id`, `query_text`, `relevant_chunks`
- `relevant_chunks` must be non-empty list of `{chunk_id, relevance}` dicts
- `chunker_version` must match `ingest.chunker_types.CHUNKER_VERSION`

**The validator REJECTS extra top-level keys** (`notebook_slug`,
`notebook_display_name`, `curated_by`, `difficulty_classes`) via the
`F3` check: `"fixture: unknown top-level keys ... are not allowed. The
schema admits exactly {sorted(required)}."` Missing `chunker_version`
would also raise `FixtureValidationError` immediately.

The current notebook `queries.json` files are paper-level relevance (arXiv
IDs), not chunk-level (chunk_ids with relevance grades 0–3). Running
`validate_eval_fixtures.py` against them AS-IS will fail immediately at
header validation.

AC #4 says "extended to accept the per-notebook scope field." The extension
is more substantial: the validator needs a new execution path for
**paper-level notebook fixtures** (vs the existing chunk-level eval
fixtures). The options are:
1. Write a separate `tools/validate_notebook_fixtures.py` — new tool,
   no risk to the existing validator.
2. Extend `validate_eval_fixtures.py` with a `--mode notebook` flag that
   accepts the notebook schema.

Option 1 is recommended (see Recommendation section).

---

## External sources

The m5 spike note at `.claude/notes/spikes/wiring-rerank-lift-100paper/note.md`
provides the reproducibility command and confirms per-notebook LanceDB was
used. No external vendor docs are needed for this milestone — it is a purely
local operational integration.

The `docs/ops/notebook-modes.md` daemon launch runbook (Mode 1) is the
canonical reference for the daemon smoke-test AC. The MCP Streamable HTTP
initialization handshake uses `POST /mcp/` with `method: "initialize"` before
`tools/list`. The sanity-check command from the runbook:

```bash
curl -s -X POST -H 'Content-Type: application/json' \
  -H 'Accept: application/json,text/event-stream' \
  http://127.0.0.1:7733/mcp/ \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | jq '.result.tools | length'
```

Expected: `7`. This can be run WITHOUT a prior `initialize` call against
the Streamable HTTP transport (stateless mode); the server processes it.

---

## Recommendation

**Skip re-running `notebook_ingest.py` for the ingest step — both corpora are
already fully populated.** 39 Lance data files exist in bridgeland (= 39
papers), 12 in shimura (= 12 papers). BM25 indices exist at `v157/` and `v49/`
with `bm25.pkl` + `chunk_ids.json`. Running `notebook_ingest.py` would be an
idempotent no-op for the LanceDB step but WOULD write the `.notebook_slug`
sentinels (currently absent). The implementer SHOULD run it once per notebook
to write the sentinels, which protects against future cross-notebook BM25
collisions.

**For AC #4 (`validate_eval_fixtures.py` extension):** write a new
`tools/validate_notebook_fixtures.py` that accepts the notebook schema
(`id`, `text`, `expected_relevant_papers`, `difficulty`, `notebook_slug`)
and validates: (a) all `expected_relevant_papers` are valid arXiv IDs,
(b) they appear in `papers.txt`, (c) no duplicate `id` fields, (d) required
top-level keys present. Do NOT extend the existing `validate_eval_fixtures.py`
— it has an explicitly closed-schema guard that rejects extra top-level keys,
and the notebook fixture schema is semantically different (paper-level not
chunk-level relevance).

**For AC #5 (daemon smoke-test):** document the Mode 1 launch + `tools/list`
verification from `docs/ops/notebook-modes.md` as a structured runbook check
in `.claude/docs/notebook-ingest-verification.md` (per CLAUDE.md §4.6 doc
placement rule — agent-internal docs go under `.claude/`, NOT `docs/ops/`).

---

## Open questions

1. **The `paper_count` AC cannot use `corpus-version.json::paper_count`** —
   that field is always 1 for per-paper ingest runs. The implementer must
   decide: query LanceDB directly (Python), or count Lance data files. The
   LanceDB query is more authoritative; the file count is simpler but could
   be wrong if any files are index files rather than data files. Recommendation:
   use `len(set(tbl.to_pandas()["paper_id"].tolist()))` via a small
   verification script.

2. **AC #4 scope ("extended to accept the per-notebook scope field") is
   ambiguous** — the brief implies a single tool extension, but the schema
   incompatibility is total. The implementer must choose new tool vs extension.
   This brief recommends a new tool. If the orchestrator disagrees and wants
   an extension, the `validate_eval_fixtures.py` changes are large (new top-
   level key allowlist, new query schema branch, backward compat guards).

No other open questions — implementation can proceed on the above
recommendations for ACs 1–3 and 5.

---

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| ar5iv HTTP fetches | `ar5iv.labs.arxiv.org` | `notebook_fetch.py` fetches any paper missing from `var/arxmcp/corpus/parsed/`. Since the m5 spike pre-fetched all 51 papers, most/all should be cache hits (`from_cache=N`). If any are missing (ar5iv cache was cleared), `notebook_fetch.py` will make live HTTP requests with 3s politeness sleep. ARXMCP_CONTACT_EMAIL must be set. |

No git push, PR creation, ticket, or infra mutation required. The sentinel
write to `var/arxmcp/index/bm25/v<N>/.notebook_slug` is a local file write.
All other operations are local LanceDB reads and BM25 index reads.
