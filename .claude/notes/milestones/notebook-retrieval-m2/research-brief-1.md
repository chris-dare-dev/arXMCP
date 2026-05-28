# Research Brief — notebook-retrieval-m2

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-28T15:40:00Z

---

## In-codebase context

### filters type — X-1 confirmed

`server/handlers/search.py` lines 344-355:

```python
filters: Annotated[
    dict[str, Any] | None,
    Field(
        description=(
            "Optional filters. Honors 'paper_id' as a str or "
            "list[str] (up to 100 items, each validated against "
            "the arXiv paper_id format) and 'source_kind' "
            "('arxiv' or 'textbook'); these compose (AND). Other "
            "keys are ignored and surface in 'filter_warnings'."
        ),
    ),
] = None,
```

**`filters` is `dict[str, Any] | None`.** Adding `"notebook"` key is invisible to the tool schema. X-1 (`EXPECTED_TOOL_SCHEMA_SHA256` UNCHANGED) and X-2 (`EXPECTED_BP1_SHA256` UNCHANGED) are both confirmed safe.

### Tier-1 cache key — the central AC3/AC7 constraint

`server/cache_sqlite.py::canonical_key_components` (lines 144-187):

```python
def canonical_key_components(
    *,
    query: str,
    filters: dict[str, Any] | None,
    k: int,
    corpus_version: int,
    level: str | None = None,
) -> bytes:
    ...
    parts = [
        canonical.encode("utf-8"),
        filters_json.encode("utf-8"),
        str(k).encode("ascii"),
        str(corpus_version).encode("ascii"),
        level_token.encode("utf-8"),
    ]
```

Five components: `query`, `filters_json`, `k`, `corpus_version`, `level`. **NO notebook slug.** `corpus_version` is per-dataset MVCC (not globally unique) — bridgeland v369 and a fresh notebook at v369 collide by hash construction. AC3 is UNSATISFIED by the current key.

The `RetrievalCache` object is initialized ONCE at startup with a fixed `self._corpus_version = int(corpus_version)` (`server/cache.py` lines 234-243) and uses it for every `lookup_search`/`store_search` call. There is no per-call corpus_version override path.

### slug-in-key minimal injection (AC3 + AC4 byte-stability)

To preserve AC4 (no `filters.notebook` → key byte-identical to today), the notebook slug must be injected as a **sixth component** ONLY when non-None:

- `notebook_slug=None` → encode as a zero-length component: `struct.pack(">Q", 0)` (8 zero bytes appended after `level_token`). This produces a key extension that is **byte-identical to not being present** ONLY if it is truly omitted. The safe approach is: if `notebook_slug is None`, emit nothing; if non-None, append `struct.pack(">Q", len(slug_bytes)) + slug_bytes`.

**Recommendation for implementation:** add an optional `notebook_slug: str | None = None` parameter to `canonical_key_components`. When `None`, append nothing to `parts` — the resulting bytes are byte-identical to today's output for the no-notebook case (AC4 exact match). When a slug is present, append it as a sixth length-prefixed part. Same treatment for `_filter_fingerprint` in `server/cache.py` (which calls `canonical_key_components` directly at lines 154-163 — both must be updated in lockstep).

### corpus_version echo — AC6

`server/tools.py::envelope` (lines 388-396):

```python
def envelope(payload: dict[str, Any]) -> dict[str, Any]:
    r = get_resources()
    payload = {**payload, "corpus_version": r.corpus_info.version}
    return _sort_dict(payload)
```

This reads `r.corpus_info.version` — the STARTUP-PINNED shared corpus version (or the fork-C notebook's version if `ARXMCP_NOTEBOOK` was set). For fork-A per-call notebook routing, `r.corpus_info.version` is the SHARED corpus version (or fork-C's), **not** the per-call notebook's version. **AC6 cannot be satisfied by the current `envelope()` path.**

The handler must call `envelope()` with the notebook's `corpus_info.version` rather than the process-wide value. The cleanest fix: pass the notebook's `CorpusVersionInfo` to a new `envelope_with_version(payload, corpus_version: int)` variant (or extend `envelope` with an optional kwarg), so the shared-corpus path remains byte-identical (AC4).

### Resources.startup — single chunks_table (table-registry gap)

`server/resources.py` dataclass fields (lines 210-276):

```python
@dataclass
class Resources:
    config: Config
    corpus_info: CorpusVersionInfo
    chunks_table: Any  # ONE table, startup-bound
    ...
```

`startup` opens ONE `chunks_table` (lines 330-338) against `config.lancedb_path`. Fork A needs a slug→table registry. The `Resources.startup` call opens this table via `open_chunks_table_with_fallback(lancedb_path=config.lancedb_path, version=corpus_info.version)` in a thread-executor. A second notebook requires the same sequence: `read_corpus_version(notebook_lancedb_path)` + `open_chunks_table_with_fallback(notebook_path, version)`.

**Recommended seam:** add a `Resources.notebook_table(slug: str) -> tuple[Any, CorpusVersionInfo]` async method that:
1. Validates slug via `validate_slug(slug)` (Threat-1 boundary, before any I/O).
2. Checks an internal `_notebook_table_cache: dict[str, tuple[Any, CorpusVersionInfo]]` (process-scoped LRU, bounded at e.g. 10 slugs).
3. On cache miss: calls `notebook_lancedb_path(slug)`, `read_corpus_version(path)`, `open_chunks_table_with_fallback(path, version)` in a thread-executor; stores in cache.
4. Returns `(table, corpus_info)`.

This is materially cleaner than request-scoped opens (avoids repeated cold-open cost per query; same pattern as the startup-bound shared table). Bound at 10 slugs is consistent with the repo's single-user, single-workstation scale.

**Flag:** the `_notebook_table_cache` dict needs an `asyncio.Lock` for the lazy-open path (prevents concurrent first-access races). Same `Singleflight` pattern used elsewhere in `resources.py`.

### m1 F1 reconciliation — AC7

m1's F1 fix (`server/config.py::derive_notebook_lancedb_path`, lines 486-496):

```python
if "cache_db_path" not in self.model_fields_set:
    self.cache_db_path = derived.parent / "cache" / "retrieval.db"
```

This per-notebook `cache_db_path` derivation is ONLY active under fork-C (`ARXMCP_NOTEBOOK` set at startup). For fork-A, `ARXMCP_NOTEBOOK` is unset → `cache_db_path` stays at the shared default → the `RetrievalCache` singleton opens against the shared `retrieval.db`. The slug-in-key mechanism is what isolates per-call notebook results in that shared store.

**The reconciliation is:** fork-C (env set) → per-notebook `cache_db_path` (structural isolation, m1's F1 fix). Fork-A (env unset) → shared `cache_db_path` + slug-in-key (logical isolation, m2's central refactor). The two mechanisms are COMPLEMENTARY, not competing: they govern different runtime modes. AC7 is satisfiable by documenting this clearly and ensuring fork-A's slug-in-key is the sole isolation mechanism when `ARXMCP_NOTEBOOK` is unset.

**Load-bearing constraint from `07-multi-agent-caching.md`:** "Cache key is the hash of the exact prefix bytes... Any whitespace or ordering change invalidates." The slug injection must be length-prefixed (same F1 fix pattern as the existing `canonical_key_components` implementation) to remain collision-free.

### Threat-1 at the filters boundary (AC5)

`tools._notebook_common.validate_slug` (lines 58-76):

```python
def validate_slug(slug: str) -> None:
    if not isinstance(slug, str):
        raise NotebookError(...)
    if not SLUG_RE.fullmatch(slug):
        raise NotebookError(...)
```

And `notebook_dir` adds symlink rejection + containment check (lines 79-123). The handler MUST call `validate_slug(slug)` (or `notebook_lancedb_path(slug)`) BEFORE any I/O — same contract m1 used at config-load, now at the per-call boundary.

### `SUPPORTED_FILTER_KEYS` — two copies (textbook-ingest-m9 context)

Per project memory: `SUPPORTED_FILTER_KEYS` exists in BOTH `server/retrieval/bm25.py:117` AND `server/handlers/search.py:249` (currently `frozenset({"paper_id", "source_kind"})`). m2 does NOT add `"notebook"` to `SUPPORTED_FILTER_KEYS` — `"notebook"` is consumed and stripped by the handler BEFORE it reaches the BM25/ANN path (it is NOT a LanceDB pre-filter). It should NOT appear in `filter_warnings` either (it is a recognized, consumed key). The handler must extract `notebook_slug = filters.pop("notebook", None)` (on a copy of filters) before the `SUPPORTED_FILTER_KEYS` unknown-key check.

---

## Prior decisions and lessons

### m1 complete (2026-05-28); all F1-F5 findings rectified

From `critique-merged.md` and `state.json`: m1 is `phase: complete`. The `notebook_lancedb_path` helper (AC8 stepping-stone), `derive_notebook_lancedb_path` validator, per-notebook `cache_db_path` derivation (F1), `corpus-version.json` marker check (F3), and ambiguity guard fix (F4) are all shipped. m2 builds directly on these.

### **CRITICAL MERGE-CONFLICT RISK (textbook-ingest-m9 in-flight)**

`git status` shows the following files have unstaged modifications from `textbook-ingest-m9`:

- `server/handlers/search.py` — **directly touched by m2**
- `server/tools.py` — `envelope()` is touched by AC6
- `server/retrieval/bm25.py` — `SUPPORTED_FILTER_KEYS` copy lives here

**The implementing agent MUST verify these files reflect the committed `4d59c97` state before writing m2 changes.** The `textbook-ingest-m9` state.json is also modified (phase not yet finalized). If `textbook-ingest-m9` is committed before m2 implementation begins, the implementer must rebase on that commit. If they are concurrent, the implementer must coordinate with the m9 state to avoid clobbering `SUPPORTED_FILTER_KEYS`, `_build_source_kind_predicate`, or the `source_kinds` column read in `_arrow_to_rows`.

### **CONFLICT: CLAUDE.md §7 says filters are "accepted but ignored at v1"**

CLAUDE.md §7 (known stubs): *"`search_papers` filters argument is accepted but ignored at v1 (deferred to E07_S04). A `filters={"paper_id": "<id>"}` argument is acknowledged in `filter_warnings` but does not actually filter results."*

**This is STALE.** The codebase shows `paper_id` and `source_kind` filters are FULLY WIRED (m1 + textbook-ingest-m9). CLAUDE.md §7 has not been updated to reflect shipped milestones. The implementing agent must NOT regress to the stale "ignored" behavior. This is documented drift in CLAUDE.md, not a conflict with the brief.

### Cache key stability — note 07 load-bearing rule

From `07-multi-agent-caching.md`: "Cache key is the hash of the exact prefix bytes including system prompt, tool definitions, and prior turns up to the breakpoint. Any whitespace or ordering change invalidates." The length-prefixed encoding already in `canonical_key_components` correctly handles this; the slug extension must follow the same pattern.

### KMP_DUPLICATE_LIB_OK guard

`tests/conftest.py::KMP_DUPLICATE_LIB_OK=TRUE` is load-bearing (CLAUDE.md §8.1). m2 adds no new model loads; this guard is not at risk.

### No `assert` for invariants (CLAUDE.md §4.7)

The table-registry lazy-open path must use `if not isinstance(slug, str): raise NotebookError(...)` not `assert`.

---

## External sources

The MCP spec (`https://modelcontextprotocol.io/specification/2025-06-18`) is not relevant to this milestone — no tool schema changes, no new protocol surface. The `filters` dict semantics are handler-internal.

Anthropic prompt-caching docs: not needed — BP1 is unchanged (no tool schema change, confirmed above).

---

## Recommendation

**Implement m2 as ONE milestone** with these four changes in this order:

1. **`server/cache_sqlite.py::canonical_key_components`** — add `notebook_slug: str | None = None` as a sixth parameter. When `None`, append nothing to `parts` (AC4 byte-identity preserved). When non-None, append `struct.pack(">Q", len(slug_bytes)) + slug_bytes`. Update `derive_tier1_key` signature to pass it through. Update `server/cache.py::_filter_fingerprint` to accept and thread the same slug.

2. **`server/resources.py::Resources`** — add `_notebook_table_cache: dict` and an `asyncio.Lock` field. Add `async def notebook_table(self, slug: str) -> tuple[Any, CorpusVersionInfo]` that validates slug, checks cache, lazy-opens via thread-executor, memoizes. Bound at 10 entries (simple LRU evict-oldest). This is the ONLY new method on `Resources`; no new field in the public dataclass surface (keep internal).

3. **`server/tools.py::envelope`** — add `def envelope_for_notebook(payload, corpus_version: int) -> dict` (or add an optional kwarg `override_corpus_version: int | None = None`) so the notebook path can echo the notebook's version without touching the shared-corpus call path.

4. **`server/handlers/search.py::handle_search_papers`** — extract `notebook_slug = None` from a shallow copy of `filters` before any SUPPORTED_FILTER_KEYS check. If present: validate via `validate_slug`, call `r.notebook_table(slug)` to get `(nb_table, nb_corpus_info)`, run the dense ANN over `nb_table`, call `envelope_for_notebook(payload, nb_corpus_info.version)`. Pass `notebook_slug` to all cache calls. If absent: today's path unchanged.

This recommendation is grounded in: (a) the `canonical_key_components` already uses length-prefix encoding (cleanest extension point), (b) `Resources` already has the `Singleflight` + executor pattern for lazy-open, (c) `envelope` is a thin wrapper — an optional kwarg is a minimal delta with zero AC4 risk.

---

## Open questions

**OQ-1 (resolve before coding): fork-C + fork-A coexistence precedence.**  
The brief says "recommend: explicit per-call `filters.notebook` wins." Confirm: if `ARXMCP_NOTEBOOK=bridgeland-stability` (fork-C, startup) AND `filters={"notebook":"shimura-varieties"}` (fork-A, per-call), which wins? The brief's recommendation is per-call wins. The implementation must document this in a comment and in the docs update (AC8) so operators understand the precedence. The implementer should follow the brief's recommendation (per-call wins) as there is no codebase constraint forcing the opposite.

**OQ-2 (resolve before coding): should `notebook_slug` thread into `cache.lookup_search` / `cache.store_search` via a new keyword arg, or via inclusion in `filters`?**  
Recommendation: new `notebook_slug: str | None = None` keyword arg on `lookup_search`, `store_search`, and `canonical_key_components`. Do NOT inject the slug into `filters` (that would change the `filters_json` encoding and affect `filters_applied` echo in the response — a correctness hazard). The slug travels as a separate axis.

No open questions beyond these two — both have recommended answers above. Implementation can proceed.

---

## External writes the implementation will require

None — this milestone is purely local. All changes are server code + tests + docs under `.claude/notes/`. No git push, no PR, no infra mutation, no third-party API call.
