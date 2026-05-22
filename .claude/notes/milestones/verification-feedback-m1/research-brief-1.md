# Research Brief 1 — verification-feedback-m1
**Researcher:** researcher-1  
**Date:** 2026-05-22  
**Milestone:** Wire the `cite_neighbors` MCP handler to the live library

---

## 1. In-codebase context

### Files this milestone touches

#### `server/handlers/citations.py` (the stub)

The handler declares a **different `direction` enum** than the library:

```python
# handler (CURRENT — must change)
direction: Literal["citers", "cited", "co_cited", "co_citing", "depends_on"]
```

The handler currently returns a fixed stub:

```python
{
    "infrastructure_status": "deferred",
    "neighbors": [],
    "note": "citation graph (E09) and intra-paper theorem dependency parser not yet built..."
}
```

The `_cap` helper is already wired (calls `cap_result_list` with `list_key="neighbors"`), so the cap contract is forward-compat — no changes needed there.

#### `server/graph_queries.py` (the real library)

Exact `cite_neighbors` signature:

```python
async def cite_neighbors(
    chunk_id: str,
    depth: int = 2,
    direction: Direction = "cites",   # Direction = Literal["cites", "cited_by", "depends_on"]
    max_results: int = DEFAULT_MAX_RESULTS,  # 50
    kuzudb_path: str | Path = DEFAULT_KUZUDB_PATH,  # "var/arxmcp/index/kuzu"
    lancedb_path: str | Path | None = None,
) -> list[CitationNeighbor]:
```

F2 path-validation contract (verbatim from docstring):

> "Path-traversal validation (Threat 1 from `08-security-observability-ops.md`) is **deferred to E06's tool-input boundary**. This function trusts `kuzudb_path` and `lancedb_path` as config-derived. The MCP-tool wrapper that lands in E06_S04 / E09_S04 **MUST NOT pass agent-supplied JSON arguments through to either path** — derive them from `Resources` / `Config` instead."

The `CitationNeighbor` dataclass (from `server/graph_types.py`):

```python
@dataclass(frozen=True)
class CitationNeighbor:
    chunk_id: str | None
    paper_id: str
    edge_kind: str
    hop_distance: int
    source: str
    confidence: float
```

#### `server/tools.py`

- `get_resources()` returns the live `Resources` singleton (raises `ResourcesNotReadyError` if called before lifespan).
- `envelope(payload)` adds `corpus_version` from `get_resources().corpus_info.version` — the implementer MUST call this for envelope consistency.
- `cap_result_list(structured_content, list_key, chunk_id)` — already used in `_cap()`.
- `CITE_NEIGHBORS` ToolMeta description still says `infrastructure_status='deferred'`; **this description must be updated** alongside the handler (otherwise `EXPECTED_TOOL_SCHEMA_SHA256` must be re-pinned).

#### `server/cache.py` + `server/cache_sqlite.py`

The existing 3-tier cache is scoped to `search_papers`. There is **no existing cache for `cite_neighbors`**. The milestone requires adding a `graph_version` key component.

Current Tier-1 key derivation (verbatim from `cache_sqlite.py:canonical_key_components`):

> The key includes `corpus_version` so "an old entry keyed to one version is unreachable by a later version because the hash differs."

For `cite_neighbors` caching, the implementer needs a NEW, simpler cache lookup (not the existing `lookup_search`/`store_search` which is `search_papers`-specific). The key should incorporate `(chunk_id, depth, direction, limit, graph_version)` where `graph_version` tracks citation-graph re-ingest.

**Critical gap:** `Config` has no `kuzudb_path` field and `Resources` has no Kùzu-related field. The F2 contract requires deriving paths from `Config`/`get_resources()`. The Kùzu path is currently only in `server/graph_queries.py::DEFAULT_KUZUDB_PATH = "var/arxmcp/index/kuzu"`. The handler must either:
1. Add `kuzudb_path` to `Config` (preferred — matches `lancedb_path` precedent), OR
2. Import `DEFAULT_KUZUDB_PATH` from `graph_queries` directly (simpler but couples config to library).

For `lancedb_path`, `Config.lancedb_path` already exists and maps to `var/arxmcp/index/lancedb`.

**`graph_version` source:** `KUZU_SCHEMA_VERSION = 2` in `ingest/kuzudb_schema.py` tracks schema changes, but NOT re-ingest events. A citation-graph re-ingest writes new data without bumping the schema version. The milestone requires a runtime `graph_version` that invalidates cache after re-ingest — this requires reading a version marker from the Kùzu DB itself (the `_schema_meta` table's `version` key), or maintaining a separate sentinel file analogous to `corpus-version.json`.

#### `server/config.py`

`Config.lancedb_path = Path("var/arxmcp/index/lancedb")` exists. `kuzudb_path` does NOT exist — **must be added**:

```python
kuzudb_path: Path = Path("var/arxmcp/index/kuzu")
```

#### `tests/test_proof_chain.py`

Tests currently exercise `cite_neighbors` library directly (not via handler). AC#5 of the milestone requires adding tests that call `handle_cite_neighbors` and verify real neighbors come back. The `fake_resources` fixture pattern is already established (lines 168-205).

#### `.claude/docs/proof-chain-workflow.md`

Verbatim constraint:

> "The wrapper that exposes `cite_neighbors` on `tools/list` (`server/handlers/citations.py`) is a **v1 stub** today... The real library (`server/graph_queries.py`) is exercised directly in the test for this milestone; handler-wiring is deferred to a future milestone (likely E06_S04) where the path-validation contract can be formalized at the boundary."

This doc section must be updated to reflect that the stub is now wired.

#### `.claude/docs/snippet-contract.md`

No direct impact — `cite_neighbors` does not return snippets. No changes needed.

---

## 2. Prior decisions and lessons

### E09_S03 critique — F2 (HIGH severity, verbatim)

> "**F2 — `cite_neighbors` accepts an unvalidated `kuzudb_path`**. Severity: HIGH. The MCP-tool wrapper (E06_S04) must NOT expose `kuzudb_path` to agent JSON args — derive it from `Resources` instead."

This milestone IS the F2 closure. The handler must NEVER surface `kuzudb_path` or `lancedb_path` as agent-controllable parameters.

### CLAUDE.md §7 (Known stubs)

> "`cite_neighbors` MCP tool is registered but the handler in `server/handlers/citations.py` is a v1 stub. The library (`server/graph_queries.py`) is real; the boundary-contract wiring is deferred to a future milestone (the F2 path-validation contract from the E09_S03 critique needs to formalize at the tool-input boundary first)."

### CLAUDE.md §8 gotcha #4

> "`var/arxmcp/index/kuzu/` vs `var/arxmcp/index/kuzudb/`. Three epic briefs use `kuzudb/`; the design notes + Makefile bootstrap use `kuzu/`. **We ship `kuzu/`.**"

The milestone brief mentions `kuzudb_path` per the AC3 spec, but the canonical path is `var/arxmcp/index/kuzu`.

### `TOOL_SCHEMA_VERSION` bump

Currently `v9`. Any change to the handler's input schema (direction enum re-alignment removes 4 values, adds 2) WILL change the `tools/list` response bytes, requiring:
1. `TOOL_SCHEMA_VERSION` bump to v10.
2. `EXPECTED_TOOL_SCHEMA_SHA256` re-pin via `pytest --update-tool-schema-hash`.
3. The `CITE_NEIGHBORS` description in `server/tools.py` must be updated (removes the "v1 stub" / "infrastructure_status='deferred'" language).

### Recent git log pattern

The last 20 commits show the `proof-verify-handler-wiring-m*` series. This milestone follows the same `feat(server) → rect → chore(notes)` commit triple.

---

## 3. External sources

This milestone is a pure handler-wiring change. No MCP spec consultation is required — the handler output shape (returning `structuredContent` via `envelope()`) is already established by all other handlers. No external sources needed.

---

## Open questions

1. **`graph_version` source**: `Config`/`Resources` have no `graph_version` field. The Kùzu `_schema_meta` table has `KUZU_SCHEMA_VERSION=2` (schema changes only). Where does the `graph_version` key component come from?  
   **Implementer must decide**: read `_schema_meta.version` from the live Kùzu DB at handler call time (adds a Kùzu open on every cache key derivation), OR add a `var/arxmcp/index/kuzu/graph-version.json` sentinel written by `graph_ingest.py` on every run (mirrors `corpus-version.json` pattern), OR add `kuzudb_path` + a lazy `graph_version` field to `Config`/`Resources`. The sentinel-file approach is the lightest lift and mirrors the existing `corpus-version.json` precedent; but it requires a one-line change to `graph_ingest.py` to write the sentinel. **This is the primary design decision before writing code.**

2. **`kuzudb_path` in `Config`**: Must add `kuzudb_path: Path = Path("var/arxmcp/index/kuzu")` to `Config` to satisfy the F2 contract (paths derived from config, never agent-supplied). No validator needed (mirrors `lancedb_path`'s pattern of no validator).

3. **Handler `depth` parameter**: The library accepts `depth=1|2` (raises ValueError for others). The stub accepts `ge=1, le=3`. Must align to `le=2` or propagate the ValueError — the latter is cleaner.

4. **Handler `limit` vs library `max_results`**: Handler uses `limit: int` (≤100), library uses `max_results: int` (default 50). The handler should pass `limit` as `max_results` to the library.

5. **`test_proof_chain.py` handler tests**: AC#5 requires the test to call `handle_cite_neighbors`, not just the library. The `fake_resources` fixture needs a Kùzu path. The current fixture does not set `config.kuzudb_path` — if that field is added to `Config`, the fixture needs to pass it.

6. **`CITE_NEIGHBORS` ToolMeta description**: Currently says `infrastructure_status='deferred'`. Must be updated to reflect live wiring — this changes `tools/list` bytes and triggers the hash re-pin.

---

## External writes the implementation will require

None. This is a purely local implementation — no pushes, PRs, tickets, infra mutations, or API calls are required.

| type | target | why |
|---|---|---|
| (none) | — | purely local handler wiring + test additions |
