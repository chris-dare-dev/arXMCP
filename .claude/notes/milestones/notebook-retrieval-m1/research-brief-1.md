# Research Brief — notebook-retrieval-m1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-28T00:00:00Z

---

## In-codebase context

### Fork 1 resolution (definitive — gates all other decisions)

`server/handlers/search.py:303–313` — exact handler signature:

```python
async def handle_search_papers(
    query: Annotated[
        str, Field(min_length=1, max_length=2000, description="Natural-language query")
    ],
    level: Annotated[
        Literal["paper", "section", "theorem"],
        Field(description="Aggregation level for results"),
    ] = "theorem",
    k: Annotated[int, Field(ge=1, le=MAX_K, description="Top-k cutoff")] = 10,
    filters: Annotated[
        dict[str, Any] | None,
        Field(
            description=(
                "Optional filters. Honors 'paper_id' as a str or "
                "list[str] (up to 100 items, each validated against "
                "the arXiv paper_id format); other keys are ignored "
                "and surface in 'filter_warnings'."
            ),
        ),
    ] = None,
    cursor: Annotated[
        str | None,
        Field(description="Reserved for E07_S04 pagination; ignored at v1"),
    ] = None,
) -> dict[str, Any]:
```

**VERDICT: Fork 1 (A) is viable. No `EXPECTED_TOOL_SCHEMA_SHA256` re-pin required.**

`filters` is typed as `dict[str, Any] | None` — a free-form dict, not a typed Pydantic
model. FastMCP derives `inputSchema` from the typed function signature. The `dict[str, Any]`
type produces a schema with `"type": "object"` and no `properties` constraint —
adding a `notebook` key at runtime does NOT change the schema bytes. The existing
`SUPPORTED_FILTER_KEYS` mechanism in the handler (`frozenset({"paper_id"})`) treats
unrecognized keys as ignored + surfaced in `filter_warnings`. Adding `"notebook"` to
`SUPPORTED_FILTER_KEYS` is handler-body-only.

**CRITICAL implication:** the `filters` Field `description` string does appear in the
rendered `tools/list` JSON that `EXPECTED_TOOL_SCHEMA_SHA256` covers. The current
description explicitly says `"arXiv paper_id format"` — if the implementer updates
this text to mention notebook selection, `EXPECTED_TOOL_SCHEMA_SHA256` MUST be
re-pinned. Recommendation: **do NOT change the `filters` Field description** for m1.
Add `"notebook"` to `SUPPORTED_FILTER_KEYS` only; let unrecognized keys surface as
`filter_warnings` for the zero-change path. The tool description string on `SEARCH_PAPERS`
in `server/tools.py:168–185` also appears in the hash — do NOT modify it for m1.

**If only handler body changes (no Field description changes, no tools.py description
change):** zero re-pin needed. BP1 cache is preserved.

---

### The retrieval gap (confirmed)

- `server/config.py:97`: `lancedb_path: Path = Path("var/arxmcp/index/lancedb")` — shared
  corpus only. No per-notebook path.
- `server/handlers/search.py:384`: `r = get_resources()` — uses the startup-bound singleton.
- `var/arxmcp/index/lancedb/` exists but is EMPTY: `total 0, drwxr-xr-x 2 ...  64 bytes`.
  No `chunks.lance` / `corpus-version.json` inside. **ALL retrieval returns empty today.**
- Per-notebook data: `var/arxmcp/notebooks/bridgeland-stability/lancedb/corpus-version.json`
  = `{"version": 369, "chunk_count": 222, "paper_count": 1, "embedder_version": "bge-m3@5617a9f6"}`.
  `var/arxmcp/notebooks/shimura-varieties/lancedb/corpus-version.json` = `{"version": 49, ...}`.
  Both have `chunks.lance` files. Neither is ever opened by any retrieval handler.

---

### `Resources` class and `get_resources()` binding

`server/resources.py:211` — `Resources` is a `@dataclass` with fields:
- `config: Config`
- `corpus_info: CorpusVersionInfo`
- `chunks_table: Any` — the LanceDB table handle, opened once at startup
- `bm25_phase: Any | None` — the `BM25Phase` singleton bound at startup
- `ann_phase: Any | None`, `rerank_phase: Any | None`, `cache: Any | None`

`server/resources.py:282–308`:

```python
@classmethod
async def startup(cls, config: Config) -> Resources:
    corpus_info = read_corpus_version(config.lancedb_path)
    ...
    chunks_table, degraded = await loop.run_in_executor(
        None,
        lambda: open_chunks_table_with_fallback(
            lancedb_path=config.lancedb_path,
            version=corpus_info.version,
        ),
    )
    ...
    bm25_phase = await BM25Phase.startup(
        lancedb_path=config.lancedb_path,
        corpus_version=corpus_info.version,
        live_chunk_ids=live_chunk_ids,
    )
```

**`Resources.startup` is a startup-bound singleton. It raises `CorpusNotIngestedError` if
`corpus-version.json` is absent from `config.lancedb_path`.** Since the shared corpus is
empty (no `corpus-version.json`), the server CANNOT start today with default config.

**This means the server is currently un-startable against the shared corpus.** The notebook
lancedb paths ARE startable (they each have `corpus-version.json`). For m1, option (C)
— `ARXMCP_NOTEBOOK=<slug>` env override of `config.lancedb_path` at server-launch — is
the simplest path and requires the least code change. Option (A) filter-based routing
requires the server to ALREADY be running (i.e. `Resources` must have been built against
SOME startable corpus), and then re-open a second corpus per-request.

**FLAG: The brief assumes the server is running against the shared corpus and routing
notebook queries via filters. But the server cannot start today against the shared corpus
(empty, no `corpus-version.json`). The filter-routing approach (A) requires a running
server, which in turn requires EITHER: (a) the shared corpus is populated, OR (b) the
server is started against one notebook's lancedb via option (C).** This is a real
architectural tension the implementer must resolve.

---

### Cache key construction

`server/cache_sqlite.py:144–187` — `canonical_key_components`:

```python
def canonical_key_components(
    *, query: str, filters: dict[str, Any] | None,
    k: int, corpus_version: int, level: str | None = None,
) -> bytes:
    canonical = canonical_query_form(query)
    filters_json = json.dumps(filters or {}, sort_keys=True, separators=(",", ":"))
    level_token = "None" if level is None else level
    parts = [
        canonical.encode("utf-8"),
        filters_json.encode("utf-8"),
        str(k).encode("ascii"),
        str(corpus_version).encode("ascii"),
        level_token.encode("utf-8"),
    ]
    ...
```

**The cache key is `(query, filters, k, corpus_version, level)`. The `corpus_version`
component is what isolates different notebooks IF they have different corpus versions.**
bridgeland-stability has `corpus_version=369`, shimura-varieties has `corpus_version=49`.
These DO NOT collide today. However, `corpus_version` is assigned independently by each
notebook's ingest run and could potentially collide for a new notebook started at a fresh
v1. The brief's concern is valid: the slug MUST be included in the cache key for
correctness, not just the corpus_version.

**For AC3 (cache isolation), the cache key must include the notebook slug.** Currently it
does not. If the implementer goes with option (C) (one server per notebook), each server
instance has its own `RetrievalCache` singleton with its own `corpus_version`, so isolation
is automatic. If option (A) is used with request-scoped Resources, the cache key needs a
`notebook_slug` component — requires modifying `derive_tier1_key` and `canonical_key_components`.
Modifying these functions also requires updating `_filter_fingerprint` (Tier-2) to be
consistent. This is a non-trivial change touching `cache_sqlite.py`, `cache.py`, and the
`lookup_search`/`store_search` call sites in `search.py`.

---

### BM25 per-notebook resolution

`ingest/bm25_indexer.py:108–114`:

```python
BM25_INDEX_ROOT = REPO_ROOT / "var" / "arxmcp" / "index" / BM25_DIR_NAME

def _bm25_version_dir(corpus_version: int) -> Path:
    return BM25_INDEX_ROOT / f"v{corpus_version}"
```

**BM25 index is GLOBAL: `var/arxmcp/index/bm25/v<N>/`. It is NOT per-notebook.**
Existing BM25 version dirs: `v5, v49, v81, v101, v157, v369`. Bridgeland-stability's
`corpus_version=369` already has `var/arxmcp/index/bm25/v369/`. Shimura has `v49`.
BM25Phase for a notebook query can reuse the existing global BM25 artifact as long as
the notebook's `corpus_version` matches the artifact version — which it does, because
notebook ingest writes chunks to per-notebook lancedb but the BM25 is built from that
same version's chunk_ids.

**The BM25 artifact for a notebook's `corpus_version` lives at the global path
`var/arxmcp/index/bm25/v<N>/`. The `BM25Phase.startup(lancedb_path, corpus_version)`
call reads BM25 from the global path regardless of `lancedb_path`. A per-notebook
`BM25Phase` instance opened with the notebook's `lancedb_path` and `corpus_version`
will correctly load `var/arxmcp/index/bm25/v369/bm25.pkl` (AC6 satisfied by construction)
as long as the artifact was built when the notebook was ingested.**

---

### Design notes applying to this milestone

- `06-mcp-server-design.md` (server architecture, 7-tool surface, startup lifecycle) — load-bearing
- `07-multi-agent-caching.md` (BP1 byte-stability, cache key discipline) — load-bearing
- `02-architecture-overview.md` (determinism contract, single Resources process) — load-bearing

Verbatim from `06-mcp-server-design.md`: _"Tool definitions themselves are byte-stable across
server restarts: pin schema, sort properties alphabetically, freeze descriptions in source. A
casual edit to a tool description blows every sub-agent's prompt cache."_

Verbatim from `07-multi-agent-caching.md`: _"Cache key includes `corpus_version`; old keys are dead
by construction."_ and _"Requires exact filter match in addition to cosine threshold."_

---

## Prior decisions and lessons

Recent git log (last 20 commits, 2026-05-28):

```
03bdcbe chore(notes): finalize textbook-ingest-m6 state -> complete
2ec59b5 rect(server): close all 7 textbook-ingest-m6 adversary findings
191ddd8 feat(server): textbook PDF end-to-end ingestion (textbook-ingest-m6)
...
be1a3ff feat(ingest): fetch raw .tex on ar5iv path; back-fill preambles (notebook-preamble-recovery-m1)
```

The notebook family (preamble-recovery-m1, textbook-ingest-m1 through m6) has been the
recent sprint. All notebook data is written to per-notebook lancedb; none of it has
ever been wired to MCP retrieval.

The `notebook-cutover-m1` research synthesis (`.claude/notes/milestones/notebook-cutover-m1/research-synthesis.md`)
established the key verified fact this milestone builds on: _"server/config.py:97: `lancedb_path`
is the SHARED corpus. server/handlers/search.py:384: the `search_papers` handler calls
`get_resources()`, which opens `config.lancedb_path`. No per-notebook path is consulted."_

Also established: the `notebooks_store.lancedb_path` SQLite column is metadata-only,
never read by any retrieval handler.

**Memory entries to preserve:**

1. The `SUPPORTED_FILTER_KEYS` in `search.py` is the single gate for recognized filter keys.
   Adding `"notebook"` there without changing the handler's typed signature or Field
   description = zero schema change.
2. BM25 index is global (`var/arxmcp/index/bm25/v<N>/`), not per-notebook. A notebook with
   `corpus_version=369` can reuse `v369/bm25.pkl` directly.
3. The shared corpus lancedb is EMPTY — the server cannot start today with default `config.lancedb_path`.

---

## External sources

MCP spec (https://modelcontextprotocol.io/specification/2025-06-18): tool `inputSchema` is
derived from the handler signature (FastMCP behavior). A `dict[str, Any]` parameter produces
a schema with `type: object` and no explicit `properties` — adding keys to the dict at
runtime is not a schema change. The spec has no requirement to declare individual filter
key names in the schema for a free-form dict parameter. No re-pin required for fork (A)
if Field descriptions are left unchanged.

---

## Recommendation

**Use Option (C) for m1: `ARXMCP_NOTEBOOK=<slug>` env var on `server/config.py`.**

Rationale: The server cannot start today against the shared corpus (it is empty). Option (A)
filter-based routing requires the server to already be running against SOME corpus first,
then re-opening a second LanceDB per request — a non-trivial Resources refactor. Option (B)
session-bound requires a new tool (BP1 re-pin) and a `SessionState` change. Option (C)
requires only: (1) adding `ARXMCP_NOTEBOOK: str | None = None` to `Config`, (2) making
`Resources.startup` use `var/arxmcp/notebooks/<slug>/lancedb/` as `lancedb_path` when
the env var is set, (3) zero tool schema changes.

For cache key isolation (AC3), option (C) automatically gives isolation: each server instance
has its own `RetrievalCache` singleton bound to its own `corpus_version`. No `derive_tier1_key`
changes needed.

For AC4 (no regression on shared corpus), the env var is absent by default: `config.lancedb_path`
stays `var/arxmcp/index/lancedb` and the behavior is byte-identical to today.

**`EXPECTED_TOOL_SCHEMA_SHA256` is unchanged.** No tool descriptions or handler signatures
change. No BP1 re-pin.

**Complexity reassessment:** with option (C), m1 is a single shippable milestone. The surface
is: `Config` (one field), `Resources.startup` (conditional lancedb_path override), tests
(synthetic notebook fixture + AC tests). Do NOT decompose.

---

## Open questions

1. **BM25 for the notebook corpus**: `BM25Phase.startup` auto-builds the BM25 if the
   artifact is missing (from `lancedb_path`). For a notebook started via option (C),
   `lancedb_path = var/arxmcp/notebooks/<slug>/lancedb/`. `build_bm25_index(lancedb_path, corpus_version)`
   reads chunks from that path and writes to `var/arxmcp/index/bm25/v<N>/` (global path).
   The implementer should verify: does `BM25Phase.startup` receive `lancedb_path` pointing
   to the notebook OR to the global index root? The global BM25 root path is hardcoded via
   `BM25_INDEX_ROOT = REPO_ROOT / "var" / "arxmcp" / "index" / bm25_dir`. This means the BM25
   artifact location is **always global** regardless of which `lancedb_path` is passed.
   Implication: if `var/arxmcp/index/bm25/v369/` already exists (it does for bridgeland),
   BM25Phase startup succeeds; if not, it auto-builds from the notebook's lancedb. **No code
   change needed for BM25 routing.** Implementer should confirm with a quick `ls var/arxmcp/index/bm25/`.

2. **`CorpusNotIngestedError` path**: `Resources.startup` raises if `corpus-version.json` is
   absent from `config.lancedb_path`. With option (C), the env var `ARXMCP_NOTEBOOK=bridgeland-stability`
   sets `lancedb_path = var/arxmcp/notebooks/bridgeland-stability/lancedb/` which HAS
   `corpus-version.json`. The implementer must ensure the path substitution happens BEFORE
   `read_corpus_version()` is called in `Resources.startup` — i.e. the `config.lancedb_path`
   field itself must be mutated/derived before startup, not patched mid-startup.

3. **AC1 test strategy**: AC1 requires a bridgeland query to return `0705.3794`. The test
   needs EITHER a live notebook corpus (requires BGE-M3 model = `requires_model` marker) OR
   a synthetic fixture. The implementer must pick: `requires_model` test (skipped by default)
   or a monkeypatched dummy-corpus fixture. Synthetic is preferred for CI.

---

## External writes the implementation will require

None — this milestone is purely local server code + tests.

| Type | Target | Why |
|---|---|---|
| (none) | — | All changes are `server/config.py` + `server/resources.py` + tests |
