# Research Brief — notebook-retrieval-m1

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-28T04:00:00Z

---

## In-codebase context

### Fork 1 verdict: (A) `filters.notebook=<slug>` — NO schema re-pin required

`server/handlers/search.py:303-313` (quoted verbatim):

```python
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
```

`filters` is typed as `dict[str, Any] | None` — a free-form dict. FastMCP derives
`inputSchema` from the function signature; `dict[str, Any]` renders as
`{"type": "object"}` with no named properties, so adding `notebook` as a new key
is INVISIBLE to the schema bytes. **`EXPECTED_TOOL_SCHEMA_SHA256` does not
need re-pinning for fork (A).** The existing unknown-key warning path
(`filter_warnings`) already absorbs unrecognized keys gracefully; the handler
must intercept `notebook` before it reaches that path.

**`plans/textbook-ingest-roadmap.md:41` (load-bearing isolation mandate, quoted verbatim):**

> `[MUST]` **Per-notebook isolation is the correct blast radius**: textbook chunks
> live ONLY in `var/arxmcp/notebooks/<slug>/lancedb/`, never in the shared arXiv
> corpus. This is the load-bearing claim in challenger F3 + dive Path A — wrong means
> `search_papers` defaults pollute the arXiv-only query semantics.

This constraint locks the implementation to per-notebook LanceDB routing: notebook
chunks CANNOT be ingested into the shared corpus. Fork (A) is the only selection
mechanism that maintains this isolation without a new tool (which would re-pin BP1).

### Resources singleton — one corpus per startup

`server/resources.py:211-276`: `Resources` is a dataclass with ONE `chunks_table`,
ONE `bm25_phase`, ONE `ann_phase`, ONE `corpus_info`, ONE `cache`. Startup
(`Resources.startup`, lines 282-650) opens exactly ONE LanceDB path:
`config.lancedb_path` (= `var/arxmcp/index/lancedb`, hardcoded in `server/config.py:97`).

There is NO per-notebook Resources; there is NO notebook-path-aware branching in
`get_resources()`. The handler receives a singleton bound to the SHARED corpus.

**Consequence for fork 2:** The implementation must NOT mutate the global Resources.
The cleanest seam is a lazy-initialized per-notebook resource cache at module level
in `server/handlers/search.py` (or a new `server/notebook_resources.py`), keyed by
slug, that mirrors the notebook-specific LanceDB handle, BM25Phase, and ANNPhase
without touching the shared-corpus singleton. Cache this in a `dict[str, NotebookResources]`
protected by an `asyncio.Lock` (one open per slug). The `RetrievalCache` (Tier 1/2/3)
is shared but cache-key-isolated (see FM-1 below).

### Cache key structure — NO slug component today

`server/cache_sqlite.py:103-187` (`derive_tier1_key`, quoted verbatim):

```python
def derive_tier1_key(
    query: str,
    filters: dict[str, Any] | None,
    k: int,
    corpus_version: int,
    *,
    level: str | None = None,
) -> str:
```

Key components: `canonical_form(query)`, `filters_json`, `k`, `corpus_version`,
`level`. **There is NO notebook slug in the key today.** This is the cache
cross-contamination gap (FM-1 below).

The verified corpus versions: `bridgeland-stability` = **v369**,
`shimura-varieties` = **v49**. Both have matching BM25 dirs at
`var/arxmcp/index/bm25/v369/` and `var/arxmcp/index/bm25/v49/`.
The shared corpus has NO `corpus-version.json` (confirmed: empty).

**Critical: corpus_version collision is GUARANTEED.** Each notebook starts
versioning independently from the LanceDB library's internal counter; both
notebooks currently sit at versions that EXIST in the BM25 index. If a third
notebook were created and happened to reach `corpus_version=369`, it would
collide in Tier-1 cache with `bridgeland-stability`'s entries on ANY query
— a silent result-substitution bug. The slug must be injected into the cache key.

### BM25 version resolution

`ingest/bm25_indexer.py:108-114` (`_bm25_version_dir`): returns
`BM25_INDEX_ROOT / f"v{corpus_version}"` where
`BM25_INDEX_ROOT = REPO_ROOT / "var" / "arxmcp" / "index" / "bm25"`.

`server/resources.py:387-395`: `BM25Phase.startup(lancedb_path=config.lancedb_path,
corpus_version=corpus_info.version, ...)`. This is called ONCE at server start with
the SHARED corpus's version. For notebook queries, the implementation must call
`BM25Phase.startup(lancedb_path=notebook_lancedb_path, corpus_version=notebook_version)`
where `notebook_version` comes from the notebook's `corpus-version.json`.

Verified: `bridgeland-stability` notebook `corpus_version=369` → BM25 at
`var/arxmcp/index/bm25/v369/` exists. `shimura-varieties` notebook
`corpus_version=49` → BM25 at `var/arxmcp/index/bm25/v49/` exists. Both are
pre-built; `BM25Phase.startup` will find and load them without triggering
`build_bm25_index`.

### Slug path-traversal defense — reuse existing guard

`tools/_notebook_common.py:47,58-72` (`SLUG_RE`, `validate_slug`):
`SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{2,30}$")`. This is the FIRST-LINE defense
already used by `server/routes/notebooks.py`. The `filters.notebook` value MUST
pass through `validate_slug` before any filesystem operation.

### Delimiter wrapping — applies at snippet level, notebook-agnostic

`server/handlers/search.py:736-761` (`_snippet`): every snippet is wrapped in
`<retrieved_chunk>...</retrieved_chunk>` regardless of data source. The wrapping
is in the `_snippet` helper, not in a corpus-specific path — notebook results will
automatically receive the Threat-2 delimiter. No additional work needed here.

### Shared corpus confirmed empty

`var/arxmcp/index/lancedb/corpus-version.json`: NOT FOUND. The shared corpus has
no `corpus-version.json` → `read_corpus_version` returns None → `Resources.startup`
raises `CorpusNotIngestedError`. The server cannot start with the empty shared
corpus. **This means the server is currently not startable in production state.**
Notebook retrieval must either: (a) bypass the shared-corpus requirement entirely,
or (b) be gated on a notebook-selection path that doesn't require the shared corpus.

**FLAG:** **This is a load-bearing conflict with AC4 ("behavior byte-identical to today (shared corpus; no regression)"). AC4 cannot be satisfied because the shared corpus is empty and the server cannot start against it. The implementer must clarify whether AC4 is still a requirement given the empty shared corpus, OR ensure the server can start in a notebook-only mode.**

---

## Prior decisions and lessons

From `git log --oneline -20`: recent milestones are `textbook-ingest-m*` (m1–m6),
`notebook-preamble-recovery-m1`. The codebase is in active notebook-feature
development.

**From memory (confirmed against codebase):**

- The doc placement rule is strict: audit docs and internal references go under
  `.claude/docs/`, not `docs/`. This milestone's AC7 (documentation) must write to
  `.claude/notes/06-mcp-server-design.md`, not `docs/`.
- `EXPECTED_TOOL_SCHEMA_SHA256` re-pinning uses
  `uv run python -m pytest --update-tool-schema-hash`. Only needed if the tool schema
  bytes change. Fork (A) does NOT change schema bytes (verified).
- The `filters` dict item-count cap (`MAX_FILTER_ITEMS`, checked in handler body)
  already exists and is invisible to the schema. Any `notebook` slug validation
  must similarly live in handler body, not in Field constraints.
- `07-multi-agent-caching.md` states: "Cache layer crash / OOM → Fall through to
  recompute; log; alert. Caching is performance, not correctness." This means the
  cache-key fix is a correctness issue, not just a performance issue — it must be
  fixed before the cache can be used for notebook queries.

**`textbook-ingest-roadmap.md:55` (future milestone dependency, relevant):**
> `search_papers` with `filters.source_kind={arxiv|textbook}` ships with
> backward-compatible default semantics (queries against an arxiv-only notebook
> return arxiv-only).

This is a PLANNED future `filters` key, confirming the convention: notebook-scope
keys live in the `filters` dict. Fork (A) is architecturally consistent with
the textbook-ingest roadmap's planned schema.

---

## External sources

### MCP 2025-06-18 spec — `tools/list` and `listChanged`

From `https://modelcontextprotocol.io/specification/2025-06-18/server/tools`:

**On `listChanged` capability (quoted verbatim):**
> "Servers that support tools **MUST** declare the `tools` capability" including
> `"listChanged": true` to "indicate whether the server will emit notifications
> when the list of available tools changes."

**On `notifications/tools/list_changed` (quoted verbatim):**
> "When the list of available tools changes, servers that declared the `listChanged`
> capability **SHOULD** send a notification."

**Implication for fork (A):** adding `filters.notebook` as a recognized key
inside the free-form `filters` dict **does NOT change the tool's `inputSchema`
bytes** (the schema remains `{"type": "object"}` for `filters`). Therefore:
- No `notifications/tools/list_changed` notification is required or triggered.
- No client needs to re-issue `tools/list`.
- The BP1 prompt-cache prefix (which includes the `tools/list` response) is
  **unchanged** — zero cache invalidation.
- `EXPECTED_TOOL_SCHEMA_SHA256` is unchanged.

The spec has NO clause requiring re-listing when a server adds logic to handle
a previously-ignored key in a free-form dict schema. The client's cached
`inputSchema` remains valid.

**On backward compatibility of optional parameters:**
The spec does not mandate a version negotiation for tool schema changes. Adding
an optional, unrecognized-by-schema key (unknown key → `filter_warnings`) is
transparently backward compatible: old callers that omit `notebook` get current
behavior (AC4).

### Anthropic prompt-caching docs

Not fetched separately — `07-multi-agent-caching.md` is the authoritative
project-scope source and was read in full. Key constraint: BP1 is
"end of system prompt + tool definitions block, byte-identical across every
agent role." Fork (A) preserves this because the tool definitions block
(specifically `search_papers.inputSchema`) is unchanged.

---

## Recommendation

**Use fork (A): `filters.notebook=<slug>` with a lazy per-notebook resource
cache.** Reasoning:

1. `filters` is `dict[str, Any] | None` — schema bytes unchanged, no re-pin.
2. Consistent with the textbook-ingest roadmap's planned `filters.source_kind`
   convention (all notebook-scope discriminators live in `filters`).
3. Backward compatible per MCP spec: callers omitting `notebook` get shared
   corpus behavior (AC4 when the shared corpus is non-empty).
4. Avoids a new tool (BP1 re-pin) or an env-var (inflexible, one notebook per
   server).

**Implementation shape:**

1. In `handle_search_papers`, before the cache lookup, extract and validate
   `filters.get("notebook")` using `validate_slug` from `tools._notebook_common`.
   Remove `notebook` from `canonical_filters` before passing to cache (it must
   NOT appear in `filters_json` — the slug goes into a separate cache-key component).
2. Build a new `NotebookResources` namedtuple (or dataclass) holding:
   `chunks_table`, `bm25_phase`, `ann_phase`, `corpus_version`. Lazy-init a
   module-level `dict[str, NotebookResources]` + `asyncio.Lock` in
   `server/handlers/search.py` or a new `server/notebook_resources.py`.
3. Extend `derive_tier1_key` / `canonical_key_components` in `server/cache_sqlite.py`
   to accept an optional `notebook_slug: str | None` component (length-prefixed,
   same pattern as the existing parts). Pass `notebook_slug` from the handler.
   **This is a schema version bump** on Tier-1 SQLite: bump `SCHEMA_VERSION` in
   `cache_sqlite.py` so old cache entries (keyed without slug) are dropped on
   restart rather than producing collisions.
4. Return `isError=True` with a clear message (not a 500) when notebook lancedb
   is absent (AC5).
5. Do NOT open a second BGE-M3 model — the embedder is shared process-wide
   (`server/query_encoder.py` module-level singleton). Only the LanceDB table
   handle, BM25Phase, and ANNPhase are per-notebook.

---

## Open questions

1. **AC4 vs empty shared corpus:** `var/arxmcp/index/lancedb/corpus-version.json`
   does not exist — the server cannot start against the shared corpus today.
   AC4 requires "behavior byte-identical to today (shared corpus; no regression)."
   The implementer must decide: is AC4 a "no-regression from shared corpus when
   the shared corpus eventually exists" requirement, or does it mean "the server
   must work without a notebook selection even now (implying the server must be
   startable without a shared corpus)"? If the latter, the lifespan must be
   refactored to allow a notebook-only mode. This is a product decision, not
   resolvable from code alone.

2. **Tier-1 SQLite schema bump side-effect:** bumping `SCHEMA_VERSION` drops the
   existing cache table on restart, invalidating any warm Tier-1 cache across the
   upgrade. This is a one-time cold-start penalty, acceptable per the design
   constitution's "caching is performance, not correctness." The implementer should
   document this in the commit message.

No other open questions — the implementation can proceed on the above recommendation
for items other than open question 1.

---

## External writes the implementation will require

None — this milestone is purely local.

All changes are: server-side Python (`server/handlers/search.py`,
`server/cache_sqlite.py`, optionally `server/notebook_resources.py`) + tests
under `tests/`. No git push, no PR, no infra mutation, no third-party API call.
