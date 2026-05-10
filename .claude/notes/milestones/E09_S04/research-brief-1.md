# E09_S04 — Research Brief 1 (cross-paper proof-chain workflow)

## 1. In-codebase context

### 1a. `server/graph_queries.py` (just-shipped E09_S03)

The async signature is firm:

```python
async def cite_neighbors(
    chunk_id: str,
    depth: int = 2,
    direction: Direction = "cites",
    max_results: int = DEFAULT_MAX_RESULTS,
    kuzudb_path: str | Path = DEFAULT_KUZUDB_PATH,
    lancedb_path: str | Path | None = None,
) -> list[CitationNeighbor]:
```

Result type (`server/graph_types.py`) — `chunk_id` is `str | None`:

> "The brief signature pinned ``chunk_id: str`` plus an AC saying
> 'Papers in the graph but not in the chunked corpus return
> ``chunk_id=None``' — those are inconsistent. This dataclass
> follows the AC: ``chunk_id`` is ``str | None`` and downstream
> callers must check before passing the value to ``get_chunk``."

The MCP-wrapper boundary contract is loud and must be repeated in `proof-chain-workflow.md`:

> "Path-traversal validation (Threat 1 from `08-security-observability-ops.md`) is **deferred to E06's tool-input boundary**. This function trusts ``kuzudb_path`` and ``lancedb_path`` as config-derived. The MCP-tool wrapper ... MUST NOT pass agent-supplied JSON arguments through to either path — derive them from ``Resources`` / ``Config`` instead."

`DEFAULT_KUZUDB_PATH = "var/arxmcp/index/kuzu"` — note the path-name drift (brief says `kuzudb/`); the doc must use the constitutional `kuzu/` path.

### 1b. `server/handlers/chunk.py` — `get_chunk` interface

The handler is `async def handle_get_chunk(chunk_id, include_referenced=False, include_equations=False)` and is **single-chunk only**, no batching:

```python
if arrow.num_rows == 0:
    return envelope({"chunk": None, "found": False, ...})
```

So "Round 2 (parallel) get_chunk × N" means N concurrent `await handle_get_chunk(cid)` coroutines via `asyncio.gather`. There is no bulk endpoint. The brief's "rounds 2+3 are merged" works only because MCP allows the agent to issue parallel `tool_use` blocks in a single assistant turn — that single turn is "one MCP round."

`is_valid_chunk_id` enforces `arxiv:<paper_id>:<16-hex>` strictly (`ingest/identifiers.py` `CHUNK_ID_PATTERN`). The brief's `arxiv:1803.01010:stmt-thm-grr` would FAIL this check at runtime.

### 1c. `server/handlers/citations.py` — STILL A STUB

`handle_cite_neighbors` is the v1 empty stub: `{neighbors: [], infrastructure_status: "deferred", ...}`. **The library `cite_neighbors()` from E09_S03 is NOT yet wired to the MCP tool.** This milestone — per its title and out-of-scope clause — is docs + tests, not a tool-handler swap. Implementer must decide: wire the handler now, or document the library-level pattern and leave the MCP-side wiring to a future milestone (recommended: document the library pattern + simulate via direct library calls in the integration test, since wiring the handler exposes the F2 contract surface that E09_S03 explicitly deferred to "E06_S04 / E09_S04").

### 1d. Eval fixture (E05_S01) — EMPTY

`tests/eval/fixtures/queries.json`:

```json
{ "schema_version": "1.0", "chunker_version": "v1.0", "created_at": "2026-05-08", "queries": [] }
```

The brief says "uses a known entry theorem chunk_id from the eval fixture (E05_S01)." That fixture has zero queries today. There is no curated entry-theorem chunk_id to reuse. The implementation must either build a synthetic test-fixture corpus (matching `tests/test_graph_queries.py`'s 5-paper pattern) or block on E05_S01 fixture curation. Recommend the synthetic-fixture path.

### 1e. Seed corpus (`tools/seed-papers.txt`) — does NOT contain `1803.01010`

The 50 IDs are `2604.*` and `2605.*` (math.AG, post-2026 submissions). `grep` confirms zero match for `1803.01010`. The brief's example paper ID is FAKE for this corpus.

`docs/eval-curation.md` does plan Riemann-Roch and Grothendieck-Riemann-Roch as eval-query themes ("Theorems (~7 queries): Riemann-Roch, Grothendieck-Riemann-Roch, Serre duality...") — but those are intended as *queries*, not *target papers*. The seed has no specific GRR paper.

### 1f. `tests/conftest.py` autouse fixtures

`KMP_DUPLICATE_LIB_OK=TRUE` is set at module load (E08_S03 OMP workaround). Four autouse fixtures redirect on-disk paths into `tmp_path`: `_patched_store_stats_path`, `_patched_bm25_stats_path`, `_patched_bm25_index_root`, `_patched_cache_db_path`. These auto-fire for every test and prevent checkout pollution. The new `test_proof_chain.py` will inherit them; the test must NOT write to `var/arxmcp/index/kuzu/` itself — it should build a synthetic Kùzu DB in `tmp_path` exactly like `tests/test_graph_queries.py::kuzu_db`.

### 1g. Performance-target precedent

`tests/test_tokenizer.py` and `tests/test_server_startup.py:211` use `time.perf_counter()` / `time.monotonic()` deltas around the call site, asserting `elapsed < threshold`. There is NO `--bench` marker, no `pytest.mark.eval`-style gating for performance targets — the project pattern is inline `time.perf_counter()` with a single assertion. Use that. `pytest --durations` reports timings but does not assert.

### 1h. Round-budget context (`.claude/notes/07-multi-agent-caching.md`)

The 3-round cap is a **project invariant**, not an MCP-spec rule. The note discusses prompt caching, BP1/BP2 placement, and `canonicalize_turn`, but the literal "3 rounds per sub-agent" budget appears only in the E08/E09 epic prose:

> "The math-proof pipeline's orchestrator allocates 3 MCP rounds per sub-agent invocation: 1 round for initial retrieval (`search_papers`), 1 round for proof-chain expansion (`cite_neighbors`), and 1 round for specific chunk retrieval (`get_chunk` bulk)."

The doc must cite E09 epic + 07-multi-agent-caching for context, NOT cite the MCP 2025-06-18 spec — the spec contains no round budget.

## 2. Prior decisions and lessons

### 2a. F-finding inheritance from E09_S03

- **F2 (path-traversal contract):** `kuzudb_path` / `lancedb_path` trusted at the library boundary; the MCP-tool wrapper must derive them from `Resources` / `Config`. This milestone DOES touch the boundary if the implementer wires `handle_cite_neighbors` to `cite_neighbors()`. Recommended in the doc: an explicit "Security note: the `cite_neighbors` tool handler MUST construct `kuzudb_path` / `lancedb_path` from `get_resources()`, not from agent JSON" — mirrors `get_chunk`'s pattern.
- **F7 (`limit(1_000_000)` foot-gun):** Open and untouched; this milestone does not exercise `_list_paper_ids_from_lancedb` (which is the affected call site). Flag as out of scope but note it remains a Tier-3-scaling risk that intersects with the 500ms latency target — at full Tier-3 corpus, the unbounded fetch dominates the latency budget.
- **F10 (deferred LOW; empty-rels defensive default `("", 0.0)`):** Untouched. The new test should not assert against an empty-rels result row; the synthetic graph always has populated rels.

### 2b. Worked-example chunk_id format issue

The brief uses `arxiv:1803.01010:stmt-thm-grr` (theorem-label suffix). The actual `CHUNK_ID_PATTERN` is `arxiv:<paper_id>:[0-9a-f]{16}` — sha256-prefix only, no semantic suffix. `chunker.py:646` builds them as `f"arxiv:{paper_id}:idx{stmt_idx}"` initially then re-hashes per `_compute_chunk_id`. The brief's example IDs WILL NOT validate via `is_valid_chunk_id` and `paper_id_from_chunk_id` will raise `ValueError`. **Recommend: rewrite the worked example to use the real `:<16-hex>` format with synthetic-but-realistic hex values (e.g. `arxiv:2605.03890:0123456789abcdef`), and add a short callout in the doc:** "Chunk IDs in this document use synthetic 16-hex suffixes for readability; the production format is `arxiv:<paper_id>:<sha256(preamble + NFC(body))[:16]>`."

### 2c. The brief's seed-paper mismatch

Paper `1803.01010` is not in the 50-paper seed (which is all `2604.*`/`2605.*`). The doc/example must either (a) pick a real seed paper to use as the entry theorem, or (b) explicitly mark the worked example as "illustrative; the seed corpus is math.AG 2026-vintage and does not contain a Grothendieck-Riemann-Roch source paper. Substitute the entry chunk_id from your local ingest." Recommend (b) for the doc and a synthetic-fixture path for the test.

## 3. External sources

- **MCP 2025-06-18 spec round budget:** does not exist. The 3-round cap is project-internal (E08/E09 epic prose + `07-multi-agent-caching.md` orchestrator design). Doc must not over-claim spec backing.
- **`pytest --durations` / time-bound assertion best practice:** the project already pairs `time.perf_counter()` with inline `assert elapsed < N` (see `test_tokenizer.py:224`, `test_server_startup.py:211`). No need for a `--bench` marker; the inline pattern is the house style. Skip on cold-start (no Kùzu DB) via `pytest.skip` exactly as `test_retrieval_quality.py` does.

## 4. Open questions

1. **Seed corpus does not contain `1803.01010`.** Use a synthetic 5-paper Kùzu fixture mirroring `tests/test_graph_queries.py::kuzu_db`. The "≤500ms on 50-paper corpus" assertion either (a) becomes a smaller "≤500ms on synthetic 5-paper graph" assertion, OR (b) is gated on the real corpus + `pytest.skip` cold-start. Recommend (a) primary + (b) optional under an env gate (`ARXMCP_RUN_REAL_CORPUS_PROOF_CHAIN=1`) — synthetic gives reproducibility, env-gated real is the periodic check.
2. **`@pytest.mark.eval` vs unconditional?** Use unconditional + skip-on-missing-corpus, mirroring `test_retrieval_quality.py`. The synthetic-fixture-on-`tmp_path` test should run unconditionally in `make test`. The real-corpus 500ms assertion should `pytest.skip` if `var/arxmcp/index/kuzu/` is absent.
3. **Latency measurement:** `time.perf_counter()` start/end deltas around the `await cite_neighbors(...)` call, single assertion `assert elapsed < 0.5`. No marker, no `--bench`. House-style, matches `test_tokenizer.py:224`.
4. **Simulated parallel `get_chunk`:** use `asyncio.gather(*[handle_get_chunk(cid) for cid in chunk_ids])`. The test asserts (a) the gather-ed results all have `found=True` and non-null `body_text` for present chunks, (b) the elapsed wall-clock is bounded (sanity, not a hard target). Don't sequentialize — defeats the doc's "parallel = 1 MCP round" claim.
5. **Worked-example chunk_id format:** rewrite to `arxiv:<paper>:<16-hex>` with synthetic hex. Adding a one-paragraph callout that explains the format is cheap and prevents copy-paste failures by future readers. Do NOT preserve the brief's `:stmt-thm-grr` form — it fails `is_valid_chunk_id`.
6. **Right entry theorem for the test:** if synthetic fixture, use `CHUNK_A = "arxiv:2401.50001:0123456789abcdef"` (mirrors `tests/test_graph_queries.py`). If real corpus, query LanceDB at test time for the first `kind="stmt"` chunk in the seed and use that as the entry — encodes a "first-stmt-in-corpus" convention for reproducibility.
7. **Synthetic vs real corpus for the test:** synthetic primary. The other E09 tests (`test_graph_queries.py`, `test_intra_paper_refs.py`) all use synthetic Kùzu graphs in `tmp_path`. The 50-paper assertion is aspirational; close it with the synthetic test + an env-gated real-corpus check. Per F2, the synthetic test exercises the library API directly (no MCP-wrapper boundary involvement).
8. **Bulk `get_chunk`:** the handler is single-chunk-only; "parallel" means N concurrent coroutines, not a batched API. The doc must explicitly say "the agent issues N independent `tool_use` blocks in one assistant turn; the MCP server processes them concurrently. Single-chunk handler, no batching endpoint."
9. **`search_papers(paper_id=<paper_id>)` for `chunk_id=None` neighbors:** **`search_papers` does NOT accept `paper_id` as a filter at v1** — `filters` is "Reserved for E07_S04; ignored at v1 with filter_warnings" (`server/handlers/search.py:88`). The brief's escape hatch — "the agent must use `search_papers(paper_id=<paper_id>)` instead" — is not implementable today. The doc must (a) flag this gap, (b) propose `find_lemma_by_name` or another tool as the fallback, OR (c) state explicitly: "filter-by-paper_id is deferred to E07_S04; until then, papers with `chunk_id=None` are dead-ends in the proof-chain workflow and the agent must skip them."

## 5. External writes the implementation will require

| File | Status | Notes |
|---|---|---|
| `docs/proof-chain-workflow.md` | NEW | The 2-round pattern + worked example with corrected `:<16-hex>` chunk_ids; explicit MCP-wrapper security note (F2); explicit `search_papers(paper_id=…)`-not-yet-supported gap; cite E09 epic + `07-multi-agent-caching.md` (NOT MCP spec). |
| `tests/test_proof_chain.py` | NEW | Synthetic 5-paper Kùzu + LanceDB fixture (mirror `test_graph_queries.py::kuzu_db` + `_build_lancedb`); `asyncio.gather`-based round-2 simulation; `time.perf_counter()` elapsed assertion ≤500ms; optional env-gated real-corpus path. |
| `server/graph_queries.py` | OPTIONAL | No code change required by the milestone; only verify the 500ms target. If F7's `_list_paper_ids_from_lancedb` is found in the hot path of `cite_neighbors(depth=2)` at scale, file a follow-up but do not fix here (out of scope). |
| `server/handlers/citations.py` | OPTIONAL / DO-NOT-WIRE | Recommend NOT swapping the stub to call `cite_neighbors()` in this milestone — that creates the F2 boundary surface and is properly an E06_S04-flavored milestone. The integration test calls the library directly. |
