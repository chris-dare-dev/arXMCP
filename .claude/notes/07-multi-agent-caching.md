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

Recommended pattern (in the agent's prompt assembly):

- **Breakpoint 1:** end of system prompt + tool definitions block. This is
  identical across every agent invocation in the pipeline; the longest-lived
  cacheable prefix.
- **Breakpoint 2:** end of the first stable tool result block (often the seed
  retrieval). Stable across many agent turns within a session.
- **Breakpoints 3 and 4:** reserve for the orchestrator to place at session-stable
  context (e.g. the problem statement). Don't waste them on volatile turns.

Use the **1-hour TTL** for the corpus-shaped prefix and seed retrieval results.
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
key   = nearest centroid in query-embedding space, cosine > 0.97, AND filters match exactly
value = full structuredContent payload
ttl   = 15 minutes
store = small in-process FAISS index over recent query embeddings
```

Catches "definition of étale morphism" vs "what is an étale morphism" — same
intent, different bytes. Threshold tuning matters: too loose conflates distinct
queries; 0.97 is a defensible default.

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

Wrap the embedder, the reranker (per `(query, candidate_set)` key), and the
summary generator (per `(query, candidate_set)` key) in singleflight. Skip this
and you pay the model 4× for redundant calls.

## Tool-result shape: summary + citations + resource_links

Default response shape (PaperQA2-inspired):

```json
{
  "summary": "Three results bear on étale cohomology of Enriques surfaces...",
  "citations": [
    {
      "chunk_id": "...",
      "score": 0.873,
      "snippet": "≤200-char excerpt",
      "label": "Theorem 3.4 of arXiv:2401.01234v3"
    }
  ],
  "resource_links": [
    {"uri": "arxmcp://chunks/...", "name": "Theorem 3.4 (full text)"}
  ]
}
```

The `summary` is generated by a small fast model (Claude Haiku) over the
top-k candidates and **cached** keyed on `(query, candidate_set)`. Cost:
- 4 agents × identical query → 1 summary generation, 3 cache reads.
- Without this layer: 4× full retrieval payload in 4 different agent windows,
  each summarizing independently.

The summary is canonicalized: deterministic prompt to Haiku, temperature 0,
fixed seed if available, stable JSON output schema enforced.

Agents that need the raw chunk body fetch a `resource_link`. Agents that
trust the summary use the summary. The choice is the agent's; the MCP server
gives both options.

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

## Summary cache (Haiku output)

The `search_papers` summary field comes from a small-model summarizer. Its
output is cached:

```
key   = sha256(query_canonical + sorted(candidate_chunk_ids) + summarizer_prompt_version + summarizer_model_version)
value = summary string
ttl   = 1 hour
store = sqlite
```

Critical: include the `summarizer_prompt_version` in the key. If we change the
summarizer instructions, old summaries are stale.

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
