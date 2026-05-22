# Research Brief 2 — verification-feedback-m1
## Researcher-2 (external-contract-first pass)

---

## 1. External / Contract Sources

### 1.1 MCP Spec obligations (`06-mcp-server-design.md`)

Load-bearing MUST clause verbatim: "Tool input validation is a MUST per the
spec's Tools section." The handler already validates `chunk_id` via
`is_valid_chunk_id()` — this must survive the stub replacement.

The note specifies the `cite_neighbors` tool schema with `direction` enum as:
`["citers", "cited", "co_cited", "co_citing", "depends_on"]` default `"cited"`.
The library (`graph_queries.py`) implements `Direction = Literal["cites",
"cited_by", "depends_on"]`. These do NOT match. The design note schema is
the stale one (it was the v1 tool surface that predates the library
implementation).

Tool descriptions are frozen: "A casual edit to a tool description blows
every sub-agent's prompt cache. Treat tool definitions as a versioned API
surface." The `CITE_NEIGHBORS` `ToolMeta.description` currently says
`infrastructure_status='deferred'` and "not yet built" — both must be
updated when the stub is replaced, which means `EXPECTED_TOOL_SCHEMA_SHA256`
must be re-pinned.

### 1.2 Cache byte-stability rules (`07-multi-agent-caching.md`)

Tier-1 key verbatim: `sha256(canonical_form(query) + filters_json + k +
corpus_version)`. The `derive_tier1_key` function in `cache_sqlite.py` has
signature `(query, filters, k, corpus_version, *, level)`. There is **no
`graph_version` parameter** anywhere in the cache key API today.

Per note: "Tier 1 — Exact-query memo... Cache key includes `corpus_version:
int` as a mandatory component; stale entries from old corpus versions are
unreachable by construction after a restart with a new `corpus-version.json`."

This design (restart-invalidates by corpus_version) works for the LanceDB
index because the server pins `corpus_version` at startup and does not
auto-switch. The Kùzu graph, however, has no equivalent `graph_version`
lifecycle today — `Resources.startup()` does not open Kùzu at all;
`kuzudb_path` is not in `Config`; there is no `graph-version.json` analog.
The cache note specifies the *mechanism* for invalidation (version in key)
but the *infrastructure* for a graph version does not exist yet.

### 1.3 Determinism contract (`06-mcp-server-design.md`)

Verbatim rules 1, 3, 5:
- "Results sorted by `(score_desc, chunk_id_asc)`. Ties broken deterministically."
- "No timestamps anywhere in tool results."
- "JSON serialized with sorted keys (alphabetical)."

The library orders by `(hop_distance ASC, paper_id ASC)` — this is
deterministic and different from `score_desc` ordering used by search tools.
The `envelope()` helper already applies `_sort_dict()` for sorted JSON keys.
The `neighbors` list is a ranking by hop distance; it must NOT be re-sorted
alphabetically (the `_sort_dict` helper explicitly does not sort lists).

### 1.4 Snippet contract (`.claude/docs/snippet-contract.md`)

The snippet contract governs `search_papers` result rows only. `cite_neighbors`
returns `CitationNeighbor` dataclass objects (paper_id, chunk_id, edge_kind,
hop_distance, source, confidence). There is no `snippet` field; the contract
does not apply here. However, if the implementation adds any neighbor body
text, the `wrap_retrieved_text()` helper from `server/tools.py` applies
(Threat 2 defense).

### 1.5 F2 path-validation contract (`server/graph_queries.py` docstring)

Verbatim warning from the library: "Path-traversal validation (Threat 1 from
`08-security-observability-ops.md`) is **deferred to E06's tool-input
boundary**. This function trusts `kuzudb_path` and `lancedb_path` as
config-derived. The MCP-tool wrapper ... MUST NOT pass agent-supplied JSON
arguments through to either path — derive them from `Resources` / `Config`
instead."

Current reality: `Config` has no `kuzu_path` field. `Resources` does not open
Kùzu at startup. The F2 contract says to get paths from `Config/get_resources()`,
but the infrastructure for that does not exist. The implementer must either
add a `kuzu_path` to `Config` and `Resources`, or accept `DEFAULT_KUZUDB_PATH`
from the library as the fallback, sourced from the library constant (not from
agent JSON).

---

## 2. Failure-Mode Analysis (≥5 modes)

### FM-1: Direction-enum mismatch silently breaks agents

**Trigger:** An agent passes `direction="cites"` or `direction="cited_by"`
(the library's values). The handler's current Literal type is
`["citers", "cited", "co_cited", "co_citing", "depends_on"]`. A naive
replacement that re-aligns the *handler* enum to the library enum would fix
the type but any agent prompt or test already referencing the OLD values
(`"citers"`, `"cited"`, `"co_cited"`, `"co_citing"`) would receive a
validation error.

**Observable symptom:** Pydantic raises a `ValidationError` on the tool call;
the MCP server returns an error result; agents in production that called
`direction="cited"` (the old default) silently get errors instead of results.

**Mitigation:** Change the handler enum to the library's Literal
(`"cites"`, `"cited_by"`, `"depends_on"`), update the default from `"cited"`
to `"cites"`, and update `CITE_NEIGHBORS.description` to document the new
values. Re-pin `EXPECTED_TOOL_SCHEMA_SHA256`. The old enum values `"co_cited"`
and `"co_citing"` are never in the library; they were aspirational and must
be dropped.

**Note from design note:** `06-mcp-server-design.md` lists `["citers", "cited",
"co_cited", "co_citing", "depends_on"]` — the note itself is the stale
source. The library is the authority.

### FM-2: `graph_version` absent from cache key — re-ingest serves stale neighbors

**Trigger:** The Kùzu citation graph is re-ingested (e.g. via
`python -m ingest.graph_ingest`). The 3-tier retrieval cache has no
`graph_version` component. A Tier-1 hit from before the re-ingest returns
the old neighbor list.

**Observable symptom:** After a citation-graph update, `cite_neighbors` returns
neighbors that may no longer exist or misses newly added edges, for up to 1
hour (Tier-1 TTL). No error is raised; the result is silently wrong.

**Mitigation:** Add a `graph_version` key component to the cache key. The
challenge: there is no `graph_version` source today. Options:
(a) Add a `graph-version.json` written by the ingest script at completion, read
by `Config`/`Resources` at startup — symmetric to `corpus-version.json`. This
is the cleanest approach but requires infra work.
(b) Use the Kùzu DB directory mtime as a proxy version — fragile (filesystem
timestamps are mutable). 
(c) Use a `graph_version` constant (e.g. `0`) as a placeholder and document
that a future ingest infra bump will update it — honest but defers the
correctness guarantee.

The milestone brief requires option (a) semantics. This is out-of-scope library
work that will touch `Config`, `Resources`, and potentially the ingest scripts.

### FM-3: F2 violation — `kuzudb_path` derived from `DEFAULT_KUZUDB_PATH` instead of Config

**Trigger:** The implementation calls `cite_neighbors(..., kuzudb_path=DEFAULT_KUZUDB_PATH)`
where `DEFAULT_KUZUDB_PATH = "var/arxmcp/index/kuzu"` is a module-level
constant in `graph_queries.py`. This is technically config-derived (not
agent-supplied), but it bypasses the `Config` system, making the path
non-configurable in production.

**Observable symptom:** An operator who sets `ARXMCP_KUZU_PATH=/custom/path`
(once that env var exists) sees the handler silently ignore it and query the
hardcoded path. Tests pass in `var/arxmcp/`-centric fixtures but fail in
alternate environments.

**Mitigation:** Add `ARXMCP_KUZU_PATH` to `Config`, load it in `Resources.startup`,
store it as `Resources.kuzu_path`, and pass `get_resources().kuzu_path` (and
`str(get_resources().config.lancedb_path)`) to `cite_neighbors`. The F2
contract is only satisfied when BOTH paths come from `Config`/`Resources`,
not from library module-level defaults.

### FM-4: `EXPECTED_TOOL_SCHEMA_SHA256` drift invalidates BP1 cache globally

**Trigger:** The `CITE_NEIGHBORS.description` in `server/tools.py` is updated
(stub wording removed), but the implementer forgets to run
`pytest --update-tool-schema-hash`.

**Observable symptom:** `tests/test_server_tool_schema.py` fails with a hash
mismatch. More critically, if the change ships without re-pinning and any
prior production agent has the old `tools/list` hash in its BP1 cache, every
agent call incurs a cache miss until the 1-hour TTL expires.

**Mitigation:** The test suite (AC#6: `make test green`) will catch this
immediately if `--update-tool-schema-hash` is NOT run. But the implementer
must not skip the step. From `CLAUDE.md`: "Re-pin `EXPECTED_TOOL_SCHEMA_SHA256`
in `tests/test_server_tool_schema.py` — the `tools/list` response must stay
byte-stable for BP1 prompt-cache discipline. Use `pytest --update-tool-schema-hash`
to regenerate."

### FM-5: 500ms performance gate regression from the MCP boundary overhead

**Trigger:** The handler adds caching logic, Kùzu open/close, and LanceDB
batched lookup on top of the library's existing Kùzu + LanceDB calls. The
library's 500ms gate is measured directly (`TestPerfGate` in
`test_proof_chain.py`). The new handler test (AC#5) exercises the HANDLER,
not just the library. Adding cache-key computation, `get_resources()` overhead,
and a cache write on top of the 500ms library call could breach the gate.

**Observable symptom:** `tests/test_proof_chain.py::TestPerfGate` starts
failing intermittently (or consistently on slower CI) because the handler
path is ~20-50ms heavier than the library-only path.

**Mitigation:** The 500ms gate should apply to the handler call, not the
library call. Cache writes are async and fire after the response is built;
only the lookup adds latency. If the gate is measured in the new handler test
with a cold cache, the overhead is limited to: `get_resources()` (near-zero),
cache key computation (SHA-256 of ~50 bytes, <1ms), and Tier-1 miss
(SQLite I/O, ~1-3ms). This is within budget. The risk is if someone
measures including a Tier-1 write or adds a LanceDB warmup call.

### FM-6: Non-deterministic result ordering breaks Tier-1 byte-stability

**Trigger:** The library returns `(hop_distance ASC, paper_id ASC)` order,
which IS deterministic. However, the `_cap()` helper calls `cap_result_list`,
which pops from the TAIL of `neighbors[]` when over the 256KB cap. If the
list order is different on two calls (due to Kùzu row materialization order
changes), the cap-truncation point differs and byte-identical payloads are
impossible.

**Observable symptom:** Two identical `cite_neighbors` calls produce different
`structuredContent` byte sequences when the payload is near the cap boundary.
Tier-1 cache misses every call even though the semantic result is the same.
Agents in a multi-agent fanout get divergent payloads.

**Mitigation:** The library's ordering contract is already explicit and
deterministic (`(hop_distance ASC, paper_id ASC)`). The handler must
preserve this ordering when building the response. The `neighbors` list in
the payload must be built in the same order the library returns, not
re-sorted. This is achieved by NOT applying `_sort_dict` to list elements'
ordering — which `_sort_dict` already respects (it sorts dict keys but not
lists).

---

## 3. In-Codebase Cross-Check

### 3.1 Direction enum — confirmed contradiction

- **Handler** (`citations.py` line 54): `Literal["citers", "cited", "co_cited", "co_citing", "depends_on"]`, default `"cited"`
- **Library** (`graph_queries.py` line 85): `Direction = Literal["cites", "cited_by", "depends_on"]`
- **Design note** (`06-mcp-server-design.md` line 232): `["citers", "cited", "co_cited", "co_citing", "depends_on"]`

The design note and handler agree on the old enum; the library uses a different
set. The library is the shipped, tested implementation. The handler must be
aligned to the library. The design note text is the stale artifact.

### 3.2 `corpus_version` in cache — exists, `graph_version` does not

`cache_sqlite.py::derive_tier1_key` takes `corpus_version: int` as a required
parameter. `RetrievalCache.__init__` stores `self._corpus_version`. Both are
populated from `corpus_info.version` in `Resources.startup`.

There is NO `graph_version` anywhere in `Config`, `Resources`, `RetrievalCache`,
or `cache_sqlite.py`. The F2 path-validation contract requires deriving paths
from `Resources`/`Config`, but `Resources` does not hold `kuzu_path` or
`graph_version`. This is a real gap that requires new `Config`/`Resources`
fields.

`cache.py` has no `lookup_cite_neighbors` or `store_cite_neighbors` methods.
The handler will need either: (a) a new cache surface in `cache.py` with a
`graph_version`-keyed Tier-1 implementation, or (b) a standalone cache key
function that derives from `(chunk_id, direction, depth, limit, graph_version)`
and calls `Tier1Store` directly. Option (a) is cleaner but larger; option (b)
is pragmatic for an M-complexity milestone.

### 3.3 `test_proof_chain.py` tests the library, not the handler

All existing `TestRound1CiteNeighbors`, `TestRound2BulkGetChunk`,
`TestChunkIdNoneBranch`, and `TestPerfGate` tests call
`server.graph_queries.cite_neighbors` directly. They do NOT call
`handle_cite_neighbors`. AC#5 of the milestone ("verified by
`tests/test_proof_chain.py` exercising the **handler**, not only the library")
requires new tests that call `handle_cite_neighbors(...)` end-to-end, including
the `get_resources()` path. The existing `fake_resources` fixture in
`test_proof_chain.py` already sets up `set_resources(fake)` — it can be
extended to wire `kuzu_path` and `graph_version` into the fake Resources.

### 3.4 `envelope()` sorts dict keys — compatible, but `neighbors` list shape is new

`envelope()` calls `_sort_dict()` which recursively sorts dict keys but
NOT list element ordering. The `CitationNeighbor` dataclass will need to be
serialized to dicts (it's a dataclass, not a dict). The implementation must
explicitly convert `CitationNeighbor` instances to dicts (e.g. via
`dataclasses.asdict()`) before building the payload. If passed raw dataclass
objects, `json.dumps` will fail and the metrics path will log a WARNING.

---

## 4. Open Questions (independently derived)

1. **Where does `graph_version` come from?** The Kùzu ingest scripts write
   no equivalent of `corpus-version.json`. Does the implementer add a
   `graph-version.json` file to the ingest pipeline, or use a surrogate
   (e.g. Kùzu DB directory mtime)? If the former, which ingest script writes
   it — `graph_ingest.py`, `inspire_ingest.py`, or both?

2. **Does `Config` get `kuzu_path` and `graph_version`, or does the handler
   use `DEFAULT_KUZUDB_PATH` from the library as an interim?** The F2 contract
   is satisfied only if neither path comes from agent-supplied JSON. Using the
   library's module-level constant is technically valid but not configurable.

3. **Should the cache for `cite_neighbors` use the existing 3-tier
   `RetrievalCache` (adding new `lookup_cite_neighbors`/`store_cite_neighbors`
   methods) or a standalone simpler cache keyed only on
   `(chunk_id, direction, depth, limit, graph_version)`?** The existing
   3-tier cache is designed for `search_papers` semantics (query embedding,
   FAISS Tier-2, reranker Tier-3). Citation neighbor queries are
   discrete/graph queries with no embedding; Tier-2 and Tier-3 are
   irrelevant. A new `lookup_citation`/`store_citation` pair in `cache.py`
   using only Tier-1 `Tier1Store` is probably the right boundary.

4. **How does the test for the HANDLER (AC#5) differ from the library test?**
   Does it call `handle_cite_neighbors(chunk_id=..., direction="cites", depth=2)`
   via the FastMCP dispatch path, or call the function directly? The FastMCP
   dispatch path tests the full MCP envelope; the direct function call tests
   the Python handler. The existing test infrastructure uses the direct-call
   pattern.

5. **When the stub's `infrastructure_status: "deferred"` key is removed, what
   fields replace it?** The `CitationNeighbor` dataclass has `chunk_id`,
   `paper_id`, `edge_kind`, `hop_distance`, `source`, `confidence`. The
   handler must serialize these into the `neighbors` list. Is `graph_version`
   surfaced in the response envelope (analogous to `corpus_version`)?

---

## 5. External Writes the Implementation Will Require

1. **`server/config.py`** — add `kuzu_path: str` (default
   `"var/arxmcp/index/kuzu"`, overridable via `ARXMCP_KUZU_PATH`) and
   `graph_version: int` (default `0`, overridable via `ARXMCP_GRAPH_VERSION`
   or read from a `graph-version.json`).

2. **`server/resources.py`** — expose `kuzu_path` (from `config.kuzu_path`)
   and `graph_version` (from `config.graph_version` or from a
   `graph-version.json` read at startup). The F2 contract requires these to
   be the handler's source of both paths.

3. **`server/cache.py`** (or `server/cache_sqlite.py`) — add a new
   citation-neighbor cache key function and
   `lookup_citation`/`store_citation` methods keyed on
   `(chunk_id, direction, depth, limit, graph_version)`. The existing
   `derive_tier1_key` signature does not cleanly extend to this use case
   (it takes `query, filters, k, corpus_version` — none of which map to
   graph query parameters).

4. **`server/tools.py`** — update `CITE_NEIGHBORS.description` to remove
   stub wording and document the library's actual `direction` values
   (`"cites"`, `"cited_by"`, `"depends_on"`). Bump `TOOL_SCHEMA_VERSION`.

5. **`server/handlers/citations.py`** — the primary target: replace the stub
   body with a real call to `server.graph_queries.cite_neighbors`, remove
   `infrastructure_status: "deferred"`, serialize `CitationNeighbor` objects
   to dicts via `dataclasses.asdict()`, add `graph_version` to the response
   envelope, and add Tier-1 cache lookup/store wrapping the library call.
   Re-align the `direction` Literal to the library's values.

6. **`tests/test_proof_chain.py`** — add a new test class
   (e.g. `TestHandlerEndToEnd`) that calls `handle_cite_neighbors(...)` (not
   the library directly) through the `fake_resources` fixture, verifying real
   neighbors are returned within the 500ms gate. The `fake_resources` fixture
   must be extended to include `kuzu_path` and `graph_version` attributes on
   the fake `Resources` object.

7. **`tests/test_server_tool_schema.py`** — re-pin `EXPECTED_TOOL_SCHEMA_SHA256`
   via `pytest --update-tool-schema-hash` after the description change.
