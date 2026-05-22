# Cross-paper proof chain workflow (2-round agent pattern)

**Audience:** sub-agent prompt authors building math-proof pipelines
(autoformalizer, tactician, lemma-suggester roles).
**Milestone:** [E09_S04](../roadmap/E09-citation-graph.md).
**Closes:** H7 (cross-paper proof chains) — final closure when
combined with E09_S03's `cite_neighbors` implementation.

This document describes the recommended 2-round MCP interaction
pattern for agents that need to assemble cross-paper proof-chain
context from the arXMCP citation graph. The pattern fits within the
3-round budget defined for the multi-agent math-proof pipeline (see
`.claude/notes/07-multi-agent-caching.md`).

---

## The pattern

```
Round 1: cite_neighbors(chunk_id=<entry_theorem>, depth=2, direction="cites")
  → Returns: list[CitationNeighbor]  (up to max_results=50)

Round 2 (parallel): get_chunk(chunk_id) × N
  → Returns: chunk bodies for all N returned neighbors
  (Each get_chunk call is independent; the agent issues them as N
   parallel tool_use blocks in a single assistant turn.)

Total round count = 2. This fits the 3-round cap from E08. Round 1
(cite_neighbors) + Round 2 (bulk parallel get_chunk) = 2 rounds.
```

The agent (typically an autoformalizer or tactician sub-agent) uses
the proof-chain context assembled in these 2 rounds to identify
which cited results to assume as lemmas. The context is composed
into the sub-agent's window before it attempts to formalize or prove
the target theorem.

**Why 2 rounds:** the math-proof pipeline's orchestrator allocates
**3 MCP rounds per sub-agent invocation** — see
`.claude/notes/07-multi-agent-caching.md` and the E08/E09 epic prose.
The breakdown is:

| Round | Tool | Purpose |
|---|---|---|
| 1 | `search_papers` | initial retrieval (caller-side, before this workflow) |
| 2 | `cite_neighbors` | proof-chain expansion (this workflow's round 1) |
| 3 | `get_chunk` (bulk parallel) | specific chunk retrieval (this workflow's round 2) |

Rounds 2 + 3 in the full orchestration flow correspond to **this
workflow's two rounds**. Subsequent in-session work (formalization,
proof generation) does not need new MCP calls.

---

## Worked example

The chunk IDs below use **synthetic 16-hex suffixes** for
readability. The production format is
`arxiv:<paper_id>:<sha256(preamble + NFC(body))[:16]>` —
see [`ingest/identifiers.py`](../../ingest/identifiers.py) and
[`docs/chunker-fixtures.md`](chunker-fixtures.md) (the E02_S05
regeneration runbook). The seed corpus is post-2026 math.AG, so
the IDs and paper hashes are illustrative; substitute real IDs
from your local ingest.

```
Query: "What results does the proof of the main theorem in
       arxiv:2605.00001 cite?"

Round 1:
  result = await cite_neighbors(
      chunk_id="arxiv:2605.00001:0123456789abcdef",
      depth=2,
      direction="cites",
  )
  # Returns up to 50 CitationNeighbor records:
  # [
  #   CitationNeighbor(
  #     chunk_id="arxiv:2605.00002:fedcba9876543210",
  #     paper_id="2605.00002",
  #     edge_kind="cites",
  #     hop_distance=1,
  #     source="openAlex",
  #     confidence=1.0,
  #   ),
  #   CitationNeighbor(
  #     chunk_id="arxiv:2605.00003:0011223344556677",
  #     paper_id="2605.00003",
  #     edge_kind="cites",
  #     hop_distance=2,
  #     source="inspire",
  #     confidence=1.0,
  #   ),
  #   ...
  # ]

Round 2 (parallel, 1 MCP round = N concurrent tool_use blocks):
  bodies = await asyncio.gather(
      *[
          get_chunk(neighbor.chunk_id)
          for neighbor in result
          if neighbor.chunk_id is not None    # see "chunk_id=None" below
      ]
  )
  # Each body: {"chunk": {"body_text": "Theorem 3.1. ...", ...}, "found": True, ...}

Total: 2 rounds. Context assembled = entry theorem + cited lemmas +
                                     their statements (and proofs).
```

The agent unfolds `bodies` into its context window using the
prompt-cache-friendly ordering established in
[07-multi-agent-caching.md](../notes/07-multi-agent-caching.md)
§ BP2 (sort by `paper_id` lexicographically so re-runs with the
same neighbor set get prefix-cache hits).

---

## The `chunk_id=None` fallback

`CitationNeighbor.chunk_id` is `str | None`. A None value means
"the paper is in the citation graph but is NOT in the chunked
corpus" — common for papers that OpenAlex / INSPIRE-HEP knows about
but `make ingest` hasn't yet parsed.

The brief's prescription was:

> "the agent must use `search_papers(paper_id=<paper_id>)` instead
> of `get_chunk` — that counts as a third round and exhausts the
> budget."

**This is currently not implementable at v1.**
[`server/handlers/search.py`](../../server/handlers/search.py) takes
a `filters: dict[str, Any] | None` argument that is **accepted but
ignored at v1** (deferred to E07_S04). The handler surfaces a
`filter_warnings` entry on the response listing each ignored filter
key.

**Until E07_S04 lands:**

- A `paper_id` filter passed via `filters={"paper_id": "<id>"}` is
  acknowledged in the response's `filter_warnings` but NOT honored
  — the server returns a generic top-k search result that is not
  paper-scoped.
- The recommended workflow is to **skip neighbors with
  `chunk_id=None` rather than chasing them through a search call**.
  The proof-chain context will be incomplete for those neighbors;
  that's the cost of the v1 fallback gap.

**Once E07_S04 lands** (filters wired), the brief's prescription
becomes implementable: each `chunk_id=None` neighbor triggers one
extra `search_papers` call, which is the third round of the
3-round budget. After E07_S04, document this here as the canonical
workflow; until then, treat `chunk_id=None` neighbors as
dead-ends.

---

## Performance target

`cite_neighbors(depth=2)` is expected to return in **≤ 500 ms** on
the 50-paper seed corpus
(`tests/test_proof_chain.py::TestProofChainPattern::test_perf_gate_500ms`
pins this with `time.monotonic()` around the await; the test uses
a synthetic 50-paper Kùzu graph with 150 deterministic edges).

This is a project guarantee for Tier-3 scale, not an MCP-spec
clause. The Tier-3-to-production scaling story (Kùzu graph at
tens of thousands of papers) is unresolved:

- The synthetic-50 case completes well under the target in practice.
- The brief flags O(D²) blowup for highly-cited papers
  (e.g. depth=2 on a Tôhoku-style hub with thousands of direct
  citations); `max_results=50` caps the result-set size but the
  underlying BFS traversal remains unbounded inside Kùzu.
- If full Tier-3 measurements exceed 500 ms, the planned mitigation
  is a pre-computed adjacency list cached at server startup,
  replacing the per-call BFS. This change preserves the
  `cite_neighbors` API.

The F7 finding from the E09_S03 critique
(`_list_paper_ids_from_lancedb`'s `limit(1_000_000)` foot-gun)
intersects with this performance story; both are Tier-4 scaling
work.

---

## Security note — MCP-tool wrapper boundary

The library function
[`cite_neighbors`](../../server/graph_queries.py) carries an explicit
warning that path-traversal validation is **deferred to the MCP-tool
wrapper boundary**:

> "This function trusts ``kuzudb_path`` and ``lancedb_path`` as
> config-derived. The MCP-tool wrapper that lands in E06_S04 /
> E09_S04 MUST NOT pass agent-supplied JSON arguments through to
> either path — derive them from ``Resources`` / ``Config``
> instead."

(See F2 from the E09_S03 critique.) The same constraint applies
to the `get_chunk` handler's LanceDB path. Both paths MUST be
derived from `Resources` / `Config` — never from agent input.

The wrapper that exposes `cite_neighbors` on `tools/list`
([`server/handlers/citations.py`](../../server/handlers/citations.py))
is **wired to the real library** as of `verification-feedback-m1` —
it calls
[`server/graph_queries.py::cite_neighbors`](../../server/graph_queries.py)
and returns real citation neighbors. The F2 path-validation contract
is honored at the handler: the Kùzu and LanceDB paths are derived
from `Config` via `get_resources()`, never from agent-supplied JSON
arguments. When the citation graph has not been ingested the handler
returns `graph_status="absent"` with an empty `neighbors` list rather
than erroring. Results are not cached — every call reads the live
graph, so a re-ingest can never serve stale neighbors.

---

## Reference

- Library: [`server/graph_queries.py::cite_neighbors`](../../server/graph_queries.py)
- Result type: [`server/graph_types.py::CitationNeighbor`](../../server/graph_types.py)
- Handler (`get_chunk`): [`server/handlers/chunk.py`](../../server/handlers/chunk.py)
- Handler (`cite_neighbors`): [`server/handlers/citations.py`](../../server/handlers/citations.py)
- Integration test: [`tests/test_proof_chain.py`](../../tests/test_proof_chain.py)
- Round-budget context: [`.claude/notes/07-multi-agent-caching.md`](../notes/07-multi-agent-caching.md)
- Chunk-id format + regeneration: [`docs/chunker-fixtures.md`](chunker-fixtures.md) (E02_S05)
- Epic: [`.claude/roadmap/E09-citation-graph.md`](../roadmap/E09-citation-graph.md)
