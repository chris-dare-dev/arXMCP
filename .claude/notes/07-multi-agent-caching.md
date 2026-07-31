# 07 — Multi-Agent Caching

This is the most important note in the directory. Get this right and 4-agent
fan-out is nearly free; get it wrong and 4 agents cost you 4× everything. Two
distinct caching layers, both load-bearing:

1. **Anthropic prompt caching** — at the LLM call layer.
2. **Retrieval / embedding / rerank cache** — inside the MCP server, before the
   model is involved.

## Caveat on numeric claims

The numbers below are from training knowledge through Jan 2026. Verify against
`https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching` before
locking design choices into code. Behavior is stable; specific TTL/pricing
numbers may have shifted.

## Anthropic prompt caching — the rules that actually matter

- **Cache is org-scoped, not session-scoped.** Two API calls from two different
  Claude Code sub-agents with the same API key, that share a byte-identical
  prefix up to a `cache_control` breakpoint, share a cache hit.
- **Min cacheable prefix:** ~1024 tokens for Sonnet/Opus, ~2048 for Haiku.
  (Verify.)
- **Up to 4 `cache_control` breakpoints per request.** Use them deliberately.
- **TTL:** 5 minutes default; **1 hour** via beta header
  `anthropic-beta: extended-cache-ttl-2025-04-11` (verify exact name).
- **Pricing:** cache reads ~10% of base input cost; writes ~125% (5-min TTL) or
  ~200% (1-hour TTL).
- **Cache key is the hash of the exact prefix bytes** including system prompt,
  tool definitions, and prior turns up to the breakpoint. Any whitespace or
  ordering change invalidates.

## Implications for the MCP server

The MCP server is upstream of the prompt cache, but its design choices entirely
control whether cache reuse across agents is achievable. Three properties the
server must guarantee:

### Property 1: Tool definitions are byte-stable

Pin tool JSON schemas. Sort properties alphabetically at serialization time.
Freeze descriptions as constants in source. A casual edit to a tool description
blows every sub-agent's cache.

Implementation: a single `tools.py` module with frozen dataclasses + a unit test
that asserts `sha256(serialize_tools()) == EXPECTED_HASH`. Bump the hash
deliberately when intentionally changing schema; treat as an API version bump.

### Property 2: Tool result payloads are canonicalized

Every result is deterministic for `(query, filters, k, corpus_version)`. Per
[06-mcp-server-design.md](06-mcp-server-design.md):

- Sort results by `(score_desc, chunk_id_asc)`.
- Use deterministic chunk IDs (`arxiv:<paper>:<sha256(canonical_chunk_bytes)[:16]>`).
- No timestamps, no random tie-breaks.
- JSON keys serialized in alphabetical order.

Without this, two agents calling `search_papers("perverse sheaves on flag varieties", k=10)`
get byte-divergent payloads. Their downstream prompts diverge. No shared cache hit.

### Property 3: Breakpoint placement is deliberate

> **Updated 2026-05-06 (see E08_S02 in `.claude/roadmap/E08-agent-runtime.md`,
> closing critique H2).** BP3 is **dropped**. Heterogeneous agent roles (Lookup,
> Synthesis, Verification, Autoformalization) issue heterogeneous tool calls;
> their seed-retrieval results diverge immediately after the first tool call and
> can never share a byte-identical BP3 prefix. A BP3 placed after "seed retrieval"
> would be invalid for all but the first role. Slots 3–4 are reserved for future use.

Recommended pattern (in the agent's prompt assembly):

- **Breakpoint 1 (BP1, 1-hour TTL):** end of system prompt + tool definitions block.
  Byte-identical across every agent role because roles are encoded as a ≤50-token
  prefix in the first *user* turn (not as per-role system prompts). This is the
  longest-lived cacheable prefix and enables cross-role cache hits on the 4-agent
  fan-out.
- **Breakpoint 2 (BP2, 1-hour TTL):** end of the problem statement. Stable across
  the 4-agent fan-out for a single query session, placed after the role prefix and
  the problem statement together.
- **BP3 / BP4:** reserved for future use. **Do not place at seed-retrieval results.**

Use the **1-hour TTL** (extended-cache-ttl beta header) for BP1 and BP2.
A 4-agent pipeline easily exceeds 5 minutes.

## The cache-killer the strawman missed: tool-use IDs

Anthropic's API assigns server-side `id` fields to `tool_use` and `tool_result`
content blocks (e.g. `toolu_01Abc...`). These IDs are **non-deterministic across
calls**. As soon as one tool call happens in agent A and a different one happens
in agent B, the prefix between them diverges and downstream cache reuse dies.

**Mitigation:** the orchestrator (the layer that composes sub-agent prompts) must
**normalize tool-use/tool-result IDs to deterministic values** before composing
the next agent turn. Strategy:

```python
def canonicalize_turn(messages):
    counter = 0
    id_map = {}
    for msg in messages:
        for block in msg.get("content", []):
            if block.get("type") in ("tool_use", "tool_result"):
                old_id = block.get("id") or block.get("tool_use_id")
                if old_id not in id_map:
                    id_map[old_id] = f"toolu_{counter:08d}"
                    counter += 1
                if "id" in block:
                    block["id"] = id_map[old_id]
                if "tool_use_id" in block:
                    block["tool_use_id"] = id_map[old_id]
    return messages
```

Apply this when materializing one agent's turn into another agent's prompt
context. **This is the single most underrated optimization in agentic pipelines.**

## Retrieval cache (separate from prompt cache)

Lives inside the MCP server. Three tiers:

### Tier 1: exact-query memo

```
key   = sha256(canonical_form(query) + filters_json + k + corpus_version)
value = full structuredContent payload
ttl   = 1 hour
store = in-process LRU (~10K entries) + sqlite for persistence across restarts
```

`canonical_form(query)` is `query.strip()` only — do **not** lowercase, do
**not** strip punctuation. `\'etale` and `étale` produce different lexical
matches.

### Tier 2: semantic memo

```
key   = nearest centroid in query-embedding space, cosine > 0.97
        AND scope matches exactly: filters + level + corpus_version + embedder identity
        AND the entry's own k >= the requested k   (ordinal, not equality)
value = full structuredContent payload
ttl   = 15 minutes
store = small in-process FAISS index over recent query embeddings
```

Catches "definition of étale morphism" vs "what is an étale morphism" — same
intent, different bytes. Threshold tuning matters: too loose conflates distinct
queries; 0.97 is a defensible default.

**The embedding covers the query TEXT axis and nothing else.** This spec
originally read "cosine > 0.97 AND filters match exactly", and the
implementation justified feeding sentinel values for `k` and
`corpus_version` on the grounds that "the query and `k` are already
disambiguated by the embedding". Half of that is true — the embedding *is*
a function of the query text. It is **not** a function of `k`, so
`search_papers(Q, k=5)` and `search_papers(Q, k=50)` shared one slot and
the wider call was served the five-row payload: silent under-retrieval on
the entry-point tool (issue #204, `sev:critical`). When adding an argument
that changes *which rows are correct*, it belongs in the scope fingerprint
(or, for a monotone argument like `k`, in an ordinal admission test) —
never on the assumption that the embedding already carries it.

`k` is ordinal rather than equality because an entry built for 50 rows can
correctly answer a request for 5 (the caller slices) while the converse
loses rows that were never retrieved. Folding `k` into the fingerprint
would be sound but would key `k=49` and `k=50` to separate slots.

Embedder identity is in the key so a ranking produced by the local
fallback during a hosted-provider outage is not re-served to a healthy
request — the handler re-stamps `degraded` from the CURRENT server state,
so without this axis the degraded ranking loses its marker on the way out.

A Tier-2 hit is by construction a *neighbour's* result set unless the
embedding matched byte-for-byte, so the response carries a `cache_match`
provenance object (`kind` + `cosine`) saying which. That is its own axis:
an approximate hit is a complete answer to an adjacent question, never an
abstention and never a `degraded` operational state
([`.claude/docs/trust-language-policy.md`](../docs/trust-language-policy.md)).

**Two-key normalization rule (critical):** the cache *lookup key* may use
aggressive normalization; the *actual query passed to BM25 / embedder* must be
unchanged. "Hodge" and "hodge" are different lexical tokens.

Log every Tier-2 hit; sample 1% for human review; tune.

### Tier 3: rerank-set memo

```
key   = sha256(query_embedding_hash + sorted_candidate_id_tuple_hash + reranker_version)
value = reranked top-k order
ttl   = 1 hour
store = in-process LRU
```

Rationale: when 4 agents ask similar (not identical) questions, their top-200
candidate sets after Phase-1 BM25 + Phase-2 ANN overlap heavily. Reranker is
the most expensive stage. Hit rates of 40–60% are realistic.

## Embedding cache

Two distinct caches; do not conflate.

### Query embedding cache

```
key   = sha256(model_name + model_version + canonical_form(query))
value = vector
ttl   = 1 hour
store = in-process LRU (~10K entries)
```

Hosted-API embedders cost $0.0001 per query embedding; cache pays for itself
after one repeat. Self-hosted embedders cost CPU/GPU time, not dollars, but
the cache is still worth it under fan-out.

### Chunk embedding cache (build-time, persistent)

```
key   = sha256(content_sha256 + embed_model_id)
value = vector
ttl   = forever (manually GC'd when model retires)
store = sqlite or LanceDB metadata table
```

**Critical: key by content hash, not chunk_id.** Chunk IDs are content-addressable
in our system, so they're equivalent — but explicitly tying the cache to content
hash + model version makes invalidation safe across schema migrations.

**Invalidation on model change:** don't invalidate. Old vectors stay valid against
the old index. Build the new index alongside, atomic-swap the symlink, GC the old
after a soak period. Mixing embedding spaces in one index is the disaster mode.

## Singleflight on the embedder

When 4 agents ask the same question in the first 200ms, you want **one in-flight
embedding call**, not four.

Pattern (Python asyncio):

```python
import asyncio

class Singleflight:
    def __init__(self):
        self._inflight: dict[str, asyncio.Future] = {}

    async def do(self, key, fn):
        if key in self._inflight:
            return await self._inflight[key]
        fut = asyncio.get_event_loop().create_future()
        self._inflight[key] = fut
        try:
            result = await fn()
            fut.set_result(result)
            return result
        except Exception as e:
            fut.set_exception(e)
            raise
        finally:
            del self._inflight[key]
```

Wrap the embedder and the reranker (per `(query, candidate_set)` key) in
singleflight. (The summary generator referenced here previously is removed — see
the tool-result shape section above.) Skip this and you pay the embedder/reranker
4× for redundant calls.

## Tool-result shape: snippet + structured fields (no summary)

> **Updated 2026-05-06 (see E06_S04 in `.claude/roadmap/E06-mcp-server.md`).** The
> `summary` field and the Haiku-generated summarizer are **permanently dropped**.
> The LLM-generated summary is not in the tool result shape. Removing it eliminates
> a source of BP1 cache invalidation (any prompt change to the summarizer changed the
> byte content of every tool result), and the summary duplicated information available
> via `get_chunk`. The singleflight wrapper on the summarizer (referenced in the
> paragraph below) is also removed.

Tool results carry only structured fields:

```json
{
  "chunk_id": "arxiv:2401.01234:a1b2c3d4e5f60718",
  "paper_id": "2401.01234",
  "version": 3,
  "score": 0.873,
  "snippet": "≤150-char excerpt from body_canonical"
}
```

Citations are the **agent's** responsibility: the orchestrator formats
`chunk_id + paper_id + version` from `get_chunk` results into its own prompt
template. The MCP server returns evidence, not assembled citations. Agents
triage on the inline `snippet`; if the snippet is relevant they call
`get_chunk(chunk_id)` for the full body.

## What "make every sub-agent retrieve, don't preload" actually means

Earlier guidance ("don't preload corpus into a 1M context") was right but
incomplete. The full picture:

1. Don't preload the corpus into the agent's context at all. Let the agent
   retrieve on demand.
2. **Make sure the orchestrator's tool-result composition is deterministic** so
   that "agent A's `search_papers` result" and "agent B's `search_papers` result"
   produce byte-identical `tool_result` blocks given the same query.
3. **Place a `cache_control` breakpoint after the tool_result block** in the
   composed prompt for the next turn. The next agent benefits from the cache
   read.
4. **Normalize tool-use IDs** (above) so prefix divergence doesn't kill the
   cache after the first tool call.

Done correctly, the second agent's call to the model gets a cache read on
~95%+ of its prefix. ~10× savings on input tokens for the fan-out turns.

## Retrieval cache tiers (summary cache removed)

> **Updated 2026-05-06 (see E08_S03 in `.claude/roadmap/E08-agent-runtime.md`).** The
> "Summary cache" section is **struck**. The summarizer is gone (see Drift 10 above).
> The three remaining caches are listed below for forward reference; their full
> implementation spec is in E08_S03.

- **Tier 1 — Exact-query (SQLite LRU, 10K entries):** key includes `corpus_version: int`
  as a mandatory component; stale entries from old corpus versions are unreachable
  by construction after a restart with a new `corpus-version.json`.
- **Tier 2 — Semantic-query (in-process FAISS, cosine > 0.97):** fires on
  near-duplicate queries ("étale morphism" vs "what is an étale morphism").
  Requires an exact scope match (filters + level + corpus_version + embedder
  identity) in addition to the cosine threshold, plus an entry at least as
  wide as the requested `k`. The embedding disambiguates the query TEXT and
  nothing else — see the Tier-2 section above and issue #204.
- **Tier 3 — Rerank-set (in-process LRU):** key is
  `sha256(sorted_candidate_id_tuple + reranker_version_sha)`. Fires when Phase-2
  produces an identical candidate set — the reranker output is deterministic given
  the same (candidates, model) triple. Expected hit rate in multi-agent fan-out:
  40–60%.

## Cache observability

Every cache layer must emit:

- `cache_lookups_total{layer}` — counter
- `cache_hits_total{layer}` — counter (hit ratio derived: hits / lookups)
- `cache_evictions_total{layer}` — counter
- `cache_bytes{layer}` — gauge

A debugging endpoint `GET /debug/cache-stats` returns a JSON snapshot. Useful
when 4 agents are concurrently retrieving and you need to know where the
budget is being spent.

## Failure modes for the cache layer

| Failure | Backstop |
|---|---|
| Cache layer crash / OOM | Fall through to recompute; log; alert. Caching is performance, not correctness. |
| Stale entry served after corpus version bump | Cache keys include `corpus_version`; old keys are dead by construction. |
| Tier-2 semantic memo conflates distinct queries | Threshold 0.97; manual review of 1% sample; tune. |
| Embedding model swap mid-flight | New model gets a new `model_version` string in cache keys; old entries unreachable. |
| Singleflight deadlock if `fn` raises | Use `try/finally` to always pop the inflight key. |

## Realistic cache-hit rates after warm-up

- Tier 1 (exact query): 30–50% within a single session.
- Tier 2 (semantic): another 10–20% on top.
- Tier 3 (rerank-set): 40–60% across multi-agent fan-out.
- Anthropic prompt cache: 80–95% of input tokens on the second-and-subsequent
  agent calls in a pipeline (the corpus-shaped prefix is the long part of the
  prompt).

Combined effect: a 4-agent pipeline costs roughly 1.3–1.5× a single-agent
call, not 4×.
