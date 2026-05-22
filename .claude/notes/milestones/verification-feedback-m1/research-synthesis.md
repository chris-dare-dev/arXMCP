# Research Synthesis — verification-feedback-m1

**Milestone:** Wire the `cite_neighbors` MCP handler to the live `graph_queries` library.
**Merged from:** research-brief-1.md (in-codebase deep read), research-brief-2.md (external/contract-first + failure modes).
**Date:** 2026-05-22

---

## 1. Verified context (both researchers agree)

**The stub.** `server/handlers/citations.py` returns a fixed `{infrastructure_status: "deferred", neighbors: [], note: "..."}` for every call. The `_cap` helper (`cap_result_list` with `list_key="neighbors"`) is already wired and needs no change.

**The library.** `server/graph_queries.py::cite_neighbors` is shipped, tested (`tests/test_proof_chain.py`), async-safe, 500 ms performance-gated. Exact signature:
```python
async def cite_neighbors(
    chunk_id: str,
    depth: int = 2,                          # library accepts 1 or 2; ValueError otherwise
    direction: Direction = "cites",          # Direction = Literal["cites","cited_by","depends_on"]
    max_results: int = 50,
    kuzudb_path: str | Path = DEFAULT_KUZUDB_PATH,   # "var/arxmcp/index/kuzu"
    lancedb_path: str | Path | None = None,
) -> list[CitationNeighbor]
```
`CitationNeighbor` (`server/graph_types.py`) is a frozen dataclass: `chunk_id, paper_id, edge_kind, hop_distance, source, confidence`. Library result order is `(hop_distance ASC, paper_id ASC)` — deterministic.

**F2 path-validation contract** (verbatim from the library docstring): "The MCP-tool wrapper ... MUST NOT pass agent-supplied JSON arguments through to either path — derive them from `Resources` / `Config` instead." This milestone IS the F2 closure (E09_S03 critique F2, HIGH).

**Direction-enum mismatch (confirmed contradiction).** Handler declares `Literal["citers","cited","co_cited","co_citing","depends_on"]` default `"cited"`; the library implements `Literal["cites","cited_by","depends_on"]` default `"cites"`. `co_cited`/`co_citing` were never implemented. The design note `.claude/notes/06-mcp-server-design.md` carries the *stale* handler enum — the shipped, tested library is the authority.

**Infrastructure gaps (both researchers, independently).** `Config` has **no** `kuzu_path` field (only `lancedb_path`). There is **no** `cite_neighbors` cache today — the 3-tier `RetrievalCache` is `search_papers`-specific (query embedding, FAISS, reranker). There is **no** `graph_version` anywhere in `Config`, `Resources`, or the cache layer, and **no** `graph-version.json` analog to `corpus-version.json`.

**Schema hash.** `TOOL_SCHEMA_VERSION` is currently `v9`. Re-aligning the `direction` enum and updating the `CITE_NEIGHBORS` description changes the `tools/list` bytes → bump to `v10` and re-pin `EXPECTED_TOOL_SCHEMA_SHA256` via `pytest --update-tool-schema-hash` (`tests/test_server_tool_schema.py`).

---

## 2. Orchestrator synthesis note — scope resolution (load-bearing)

The milestone brief framed m1 as "purely the MCP boundary — the library needs no changes." Both researchers independently surfaced that **AC4 as literally written is not "purely the boundary"**: "add a `graph_version` component to the cache key" presupposes (a) a `cite_neighbors` cache exists and (b) a `graph_version` source exists. Neither does. Building both would add a `graph-version.json` sentinel mechanism, a one-line `ingest/graph_ingest.py` change, `Config.graph_version`, `Resources` exposure, and a new `cache.py` citation-cache surface — pushing m1 from M toward L and contradicting its stated "boundary-only" scope.

**Resolution — m1 does NOT cache `cite_neighbors` results.** The Phase-3 challenger of the capability scout explicitly offered two ways to satisfy the staleness concern (`challenge.md`, CAND-2 MINOR): "*(a) add `graph_version` to the Tier-1 key for citation queries, or **(b) exclude `cite_neighbors` results from Tier-1 caching**.*" m1 takes **option (b)**: the handler calls the live library on every invocation. Consequence: **AC4's correctness intent — "a citation-graph re-ingest invalidates stale results" — is satisfied by construction**, because there are no cached results to go stale. Every call reads the current Kùzu graph.

The `graph_version`-keyed `cite_neighbors` cache is a pure *optimization*, not a correctness requirement, and is **explicitly deferred** to a future caching/optimization milestone that will own the `graph-version.json` mechanism end-to-end. This keeps m1 genuinely M-sized and "boundary-only" as the roadmap intended. AC4 will be recorded in `implementation-summary.md` as **met-by-exclusion** with this reasoning, not left silently unchecked.

This is the one place the briefs surfaced a brief-vs-reality conflict; it is resolved here, deliberately, with the challenger's own sanctioned option.

---

## 3. Implementation plan (path: INLINE — orchestrator implements directly)

Size: ~5–6 files, no novel architecture, no specialist agent registered → INLINE per the pipeline decision tree.

**`server/config.py`** — add `kuzu_path: Path = Path("var/arxmcp/index/kuzu")`, mirroring the existing `lancedb_path` (no validator, same precedent). Canonical directory is `kuzu/` not `kuzudb/` (CLAUDE.md §8 gotcha #4 — "We ship `kuzu/`").

**`server/handlers/citations.py`** — replace the stub body:
- Re-align the `direction` parameter to `Literal["cites","cited_by","depends_on"]`, default `"cites"`.
- Clamp `depth` validation to `ge=1, le=2` at the Pydantic boundary (the library raises `ValueError` outside 1–2; failing fast at the input boundary is the MCP-spec input-validation MUST and gives a clean error).
- Keep the existing `is_valid_chunk_id()` validation — it must survive the rewrite.
- Call `await server.graph_queries.cite_neighbors(chunk_id, depth=depth, direction=direction, max_results=limit, kuzudb_path=str(get_resources().config.kuzu_path), lancedb_path=str(get_resources().config.lancedb_path))`. Both paths come from `Config` via `get_resources()` — never from the agent's JSON args (F2).
- Serialize each `CitationNeighbor` to a dict via `dataclasses.asdict()` (the dataclass is not JSON-serializable raw).
- Build the payload via the existing `envelope(...)` helper (adds `corpus_version`, sorts dict keys — but not list element order, so the library's `(hop_distance, paper_id)` ordering is preserved). Apply the existing `_cap(...)`.
- Remove the `infrastructure_status: "deferred"` / `note` keys entirely.

**`server/tools.py`** — update the `CITE_NEIGHBORS` `ToolMeta.description` to drop the "v1 stub" / "infrastructure_status='deferred'" / "not yet built" wording and document the live `direction` values. Bump `TOOL_SCHEMA_VERSION` `v9 → v10`.

**`tests/test_proof_chain.py`** — add a handler-level test class (e.g. `TestHandlerEndToEnd`) that calls `handle_cite_neighbors(...)` (not the library directly) through the existing `fake_resources` fixture, asserting real neighbors are returned and the 500 ms gate holds at the *handler* level. Extend `fake_resources` so its fake `Config` carries `kuzu_path`.

**`tests/test_server_tool_schema.py`** — re-pin `EXPECTED_TOOL_SCHEMA_SHA256` via `pytest --update-tool-schema-hash` after the description + version change.

**`.claude/docs/proof-chain-workflow.md`** — update the section that says the handler is a v1 stub / "call the library directly" to reflect that the handler is now wired. (Doc lives under `.claude/`, allowed.)

**`.claude/notes/06-mcp-server-design.md`** — the stale `direction` enum in this note should be corrected to the library's values, OR flagged. NOTE: `.claude/notes/` is the design constitution; per `arxmcp-integration.md` the roadmap skill treats it as read-only, but milestone-pipeline implementation may correct documented drift. **Decision:** correct the one stale enum line, since shipping a contradictory constitution note is itself a defect — but touch nothing else in that note.

---

## 4. Open questions — resolved

- **Where does `graph_version` come from?** → Moot for m1. Deferred with the caching work (§2).
- **`Config.kuzu_path` vs library `DEFAULT_KUZUDB_PATH`?** → Add `Config.kuzu_path`; F2 requires the path to be config-derived and operator-overridable, not a library constant.
- **3-tier `RetrievalCache` vs standalone cache?** → Neither — no caching in m1 (§2).
- **`depth` handler validation?** → Clamp to `ge=1, le=2` at the Pydantic boundary.
- **`limit` vs `max_results`?** → Handler `limit` is passed as the library's `max_results`.
- **Surface `graph_version` in the response envelope?** → No — there is no `graph_version` in m1. The envelope carries `corpus_version` only, as it does for every other tool.

## 5. Failure modes to guard against (from research-brief-2, still relevant under the no-cache decision)

- **FM-1 direction-enum break** — re-aligning the enum is itself the fix; the schema-hash re-pin + description update is mandatory. Any agent that passed `"cited"` will now need `"cites"` — acceptable, the tool was a non-functional stub so no working caller exists.
- **FM-3 F2 violation** — guard: paths come from `get_resources().config`, asserted in the handler test.
- **FM-4 schema-hash drift** — guard: `tests/test_server_tool_schema.py` fails loudly if the re-pin is skipped; AC6 (`make test` green) catches it.
- **FM-5 500 ms gate** — guard: the handler adds only `get_resources()` (near-zero) + `dataclasses.asdict()` over ≤ `limit` rows; the new handler test asserts the gate at the handler level.
- **FM-6 ordering / byte-stability** — guard: preserve the library's `(hop_distance, paper_id)` order; do not re-sort the `neighbors` list; `envelope()`'s `_sort_dict` sorts dict keys only.

## 6. Acceptance-criteria disposition

| AC | Plan |
|---|---|
| AC1 — handler calls the library, stub removed | Fully met. |
| AC2 — direction enum re-aligned, schema hash re-pinned | Fully met (`v9→v10`, `--update-tool-schema-hash`). |
| AC3 — paths from Config, not agent JSON (F2) | Fully met (`Config.kuzu_path` added; both paths via `get_resources().config`). |
| AC4 — cache entries include `graph_version`; re-ingest invalidates | **Met-by-exclusion** — m1 does not cache `cite_neighbors` (challenger option b); re-ingest staleness is impossible by construction. The `graph_version`-keyed cache is deferred to a future optimization milestone. Recorded in `implementation-summary.md`. |
| AC5 — handler-level test in `test_proof_chain.py` | Fully met. |
| AC6 — `make test` green, `ruff` clean | Gate. (`make` is unavailable on this workstation; the project-check fallback `ruff check . && uv run python -m pytest` is used — equivalent to `make test`.) |

## 7. External writes the implementation will require

**None.** Purely local: handler wiring + a Config field + a tool-description update + test additions + two doc corrections. No push, no PR, no ticket, no infra mutation, no external API call. `external_writes_required = []`.
