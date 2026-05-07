# E08 — Agent Runtime + Caching

Epic dependencies: E06 (MCP server with 7 tools shipped), E07 (hybrid retrieval at nDCG@5 ≥ 0.80)

Goal: Implement the orchestration layer that routes queries to the correct agent role, encodes roles as user-turn prefixes rather than system prompts, manages prompt-cache breakpoints, enforces hard caps on retrieval rounds and chunk materialization, and operates a 3-tier retrieval cache inside the MCP server. The result is a 4-agent fan-out pipeline that costs ~1.3–1.5× a single-agent call rather than 4×.

Effort: M + M + L + M + S = XL total

References: `.claude/notes/07-multi-agent-caching.md` lines 1–329, `.claude/notes/06-mcp-server-design.md` lines 278–295

---

### E08_S01 — Query router: Python regex classifier

**Status:** NEW
**Tier:** 2
**Effort:** M
**Dependencies:** E06_S03

**Description.** Implement `server/router.py`, a fast query classifier that reads the first 200 characters of the user query and uses Python regular expressions to assign it to one of four agent roles: Lookup, Synthesis, Verification, or Autoformalization. There is no LLM planner, no embedding similarity, and no external API call in this path — the router must be synchronous and return within 1ms.

The classification logic uses a priority-ordered list of compiled regex patterns. The patterns operate on the lowercased, whitespace-normalized first 200 characters of the query. Examples of classification signals:

- **Lookup**: patterns like `r"\bdefin(e|ition)\b"`, `r"\bwhat is\b"`, `r"\blemma \d"`, `r"\btheorem \d"`, `r"\bnotation\b"` — the agent needs a specific named object from the corpus.
- **Synthesis**: patterns like `r"\bprove\b"`, `r"\bsketch\b"`, `r"\bshow that\b"`, `r"\bderive\b"` — the agent must assemble a proof strategy across multiple retrieved chunks.
- **Verification**: patterns like `r"\bcheck\b"`, `r"\bverify\b"`, `r"\bcorrect\b"`, `r"\bvalid\b"` — the agent receives a candidate proof step and must validate it.
- **Autoformalization**: patterns like `r"\blean\b"`, `r"\bmathlib\b"`, `r"\bformalize\b"`, `r"\btranslate.*lean"` — the agent must produce Lean 4 syntax.

The router returns a `RouteTag` enum value. The `RouteTag` is consumed by the orchestrator to select the appropriate role prefix (E08_S02) and model (E08_S05). The router is not the final arbiter of agent behavior — if the regex fires incorrectly, the agent's role-prefix still constrains its behavior. Misrouting is a quality issue, not a correctness issue.

The pattern list is loaded from `server/router_patterns.yaml`, which is version-controlled and annotated with the rationale for each pattern. This makes the classifier reviewable and editable without touching Python source. A test suite covers all four tags with canonical examples and common edge cases.

**Deliverables.**
- `server/router.py` — `classify(query: str) -> RouteTag` function; `RouteTag` enum with four values
- `server/router_patterns.yaml` — annotated pattern list; ordered by priority; includes rationale comments
- `tests/test_router.py` — at minimum 5 canonical examples per RouteTag; at least 3 ambiguous cases with documented expected behavior

**Acceptance criteria.**
- [ ] `classify("What is the definition of an étale morphism?")` returns `RouteTag.LOOKUP`
- [ ] `classify("Prove that the Hodge conjecture holds for abelian varieties of CM type")` returns `RouteTag.SYNTHESIS`
- [ ] `classify("Formalize Yoneda lemma in Lean 4")` returns `RouteTag.AUTOFORMALIZATION`
- [ ] `classify(...)` returns within 1ms for any 200-character prefix (measured via `timeit`)
- [ ] `pytest tests/test_router.py` passes
- [ ] Adding a new pattern to `router_patterns.yaml` does not require modifying `router.py`

**Out of scope.** LLM-based intent classification. Embedding similarity routing. Multi-label routing (one tag per query in v1).

**Risk notes.**
- Closes H1: replacing an LLM planner with a Python regex router eliminates the latency and cost of a planning LLM call on every query, and makes routing behavior deterministic and auditable.

**Labels.** `area:runtime`, `kind:feature`, `tier:2`

---

### E08_S02 — Role-as-user-turn-prefix and BP1/BP2 breakpoint placement

**Status:** NEW
**Tier:** 2
**Effort:** M
**Dependencies:** E08_S01

**Description.** Encode each agent role as a 50-token prefix injected at the start of the FIRST user turn, not as a per-role system prompt. This design choice is load-bearing for prompt-cache efficiency: BP1 (system prompt + tool definitions) is byte-identical across all four roles (Lookup, Synthesis, Verification, Autoformalization), enabling the longest and most valuable cache prefix to be shared across the entire 4-agent fan-out. A per-role system prompt would produce four distinct BP1 prefixes and eliminate cross-role cache hits.

The role prefix is a brief, imperative instruction in the user voice. It must fit within 50 tokens (measured by the Claude tokenizer). Example prefix for Autoformalization:

```
[Role: Autoformalizer] Translate the following mathematical content to Lean 4 using Mathlib conventions. Produce only valid Lean 4 syntax. Do not paraphrase or summarize.
```

The four role-prefix templates are defined in `server/prompts.md` (human-readable reference) and `server/prompts.py` (importable string constants). The templates are frozen constants — they must not be interpolated at runtime with dynamic values, because that would invalidate BP1. Any parameter that needs to vary (e.g., the specific problem statement) goes AFTER the role prefix, not inside it.

Cache breakpoint placement:
- **BP1** (1-hour TTL): end of the system prompt + tool definitions block. Identical across all agents. Use the extended-cache-ttl beta header.
- **BP2** (1-hour TTL): end of the problem statement. Stable across the 4-agent fan-out for a single query session. Placed after the role prefix and the problem statement together.
- **No BP3**: there is no third breakpoint for "seed retrieval results." Heterogeneous roles issue heterogeneous tool calls and their retrieval results diverge immediately — a shared BP3 would be invalid and would waste a breakpoint slot. The 4-breakpoint-per-request budget is preserved for future use.

Document the full breakpoint strategy, including the rationale for dropping BP3, in `server/prompts.md`. Include a diagram showing the message structure for a typical Synthesis agent turn.

**Deliverables.**
- `server/prompts.py` — four frozen role-prefix string constants; one constant per RouteTag
- `server/prompts.md` — human-readable documentation of all role prefixes, breakpoint placement, rationale for dropping BP3, and the message structure diagram
- `tests/test_prompts.py` — asserts each role prefix is ≤ 50 tokens; asserts no runtime interpolation occurs (templates are literal strings); asserts BP1 prefix is byte-identical across all four roles

**Acceptance criteria.**
- [ ] Each role prefix is ≤ 50 tokens (Claude Sonnet 4.6 tokenizer)
- [ ] `server/prompts.py` contains exactly 4 role-prefix constants, one per `RouteTag`
- [ ] `tests/test_prompts.py` passes
- [ ] `server/prompts.md` explicitly states: "BP3 is dropped; heterogeneous roles never share seed retrieval bytes"
- [ ] A 4-agent fan-out integration test confirms BP1 is byte-identical across all roles (hash equality check)

**Out of scope.** Per-role system prompts (permanently dropped). Dynamic role-prefix interpolation. More than 4 roles in v1.

**Risk notes.**
- Closes H2: dropping BP3 eliminates the invalid assumption that heterogeneous agents can share a "seed retrieval" breakpoint, preventing wasted breakpoint slots and incorrect cache reuse.
- Closes MEDIUM: role-specific system prompts — encoding role as a user-turn prefix makes BP1 byte-identical across the fan-out, achieving the 80–95% input-token cache hit rate described in `.claude/notes/07-multi-agent-caching.md` lines 320–326.

**Labels.** `area:runtime`, `kind:design`, `tier:2`

---

### E08_S03 — MCP-side 3-tier retrieval cache

**Status:** NEW
**Tier:** 2
**Effort:** L
**Dependencies:** E06_S01, E07_S03

**Description.** Implement the three-tier retrieval cache that lives inside the MCP server and is shared across all concurrently connected sub-agents. The cache is a performance layer — its failure mode is a cache miss (slower but correct), never a correctness failure.

**Tier 1 — Exact-query memo.** SQLite-backed LRU cache, maximum 10,000 entries. Cache key: `sha256(canonical_form(query) + json.dumps(filters, sort_keys=True) + str(k) + str(corpus_version))`. The `corpus_version` integer (pinned at server startup from `corpus-version.json`) is a mandatory component of the key — an old entry keyed to corpus_version=6 is unreachable after the server restarts against corpus_version=7. `canonical_form(query)` is `query.strip()` only — no lowercasing, no punctuation stripping, because `étale` and `\'etale` are distinct BM25 tokens. TTL: 1 hour. On server startup, unexpired Tier-1 entries are loaded from the SQLite file into the in-process LRU.

**Tier 2 — Semantic-query memo.** In-process FAISS flat index over the embeddings of recent queries (up to 1,000 query embeddings retained in the ring buffer). A Tier-2 hit requires cosine similarity > 0.97 AND exact filter match. Cache key: nearest centroid at ≥ 0.97 cosine + filter fingerprint. TTL: 15 minutes. Tier-2 hits are logged and 1% sampled for human review — threshold tuning requires this data. If the FAISS index is empty (cold start), Tier 2 is a no-op pass-through.

**Tier 3 — Rerank-set memo.** In-process LRU cache for reranker outputs. Cache key: `sha256(query_embedding_hash + sha256(sorted_candidate_ids_json) + reranker_version_sha)`. TTL: 1 hour. This tier fires when Phase-2 produces an identical candidate set to a recent query — the reranker output is deterministic given the same (query, candidates, model) triple, so the cached ranking is bit-identical to a fresh rerank. Expected hit rate in a multi-agent fan-out: 40–60% (`.claude/notes/07-multi-agent-caching.md` lines 150–158).

The cache lookup path for a `search_papers` call is: Tier-1 → Tier-2 → run pipeline (possibly skipping Tier-3 for rerank) → write all tiers. All three lookups are async; they run sequentially (not in parallel, because Tier-2 requires the query embedding which takes time to compute). The cache is initialized in `server/resources.py` and is a singleton for the process lifetime.

**Deliverables.**
- `server/cache.py` — `RetrievalCache` class with `lookup(query, filters, k) -> Optional[payload]` and `store(query, filters, k, payload)` methods; all three tiers implemented
- `server/cache_sqlite.py` — SQLite persistence for Tier 1; schema migration on version bump
- `server/routes/debug.py` — `GET /debug/cache-stats` endpoint returning JSON with per-tier `lookups_total`, `hits_total`, `evictions_total`, `bytes_used`
- `server/metrics.py` — Prometheus counters/gauges: `arxmcp_cache_lookups_total{tier}`, `arxmcp_cache_hits_total{tier}`, `arxmcp_cache_evictions_total{tier}`, `arxmcp_cache_bytes{tier}`
- `tests/test_cache.py` — unit tests: Tier-1 miss then hit; Tier-2 semantic hit at 0.98 cosine and miss at 0.95; Tier-3 hit after identical candidate set; corpus_version change invalidates Tier-1

**Acceptance criteria.**
- [ ] A repeated identical query hits Tier-1 and bypasses Phase 1/2/3
- [ ] A semantically similar query (cos ≥ 0.97) hits Tier-2 and bypasses Phase 1/2/3
- [ ] After server restart with corpus_version=N+1, all Tier-1 entries from corpus_version=N are unreachable
- [ ] `GET /debug/cache-stats` returns valid JSON with all required fields
- [ ] `pytest tests/test_cache.py` passes
- [ ] Prometheus metrics are emitted at `/metrics`

**Out of scope.** Distributed cache (single-workstation deployment only). Redis. Cache warming on startup beyond loading SQLite entries.

**Risk notes.**
- Closes MEDIUM: corpus_version cache invalidation strategy — the `corpus_version` integer in the Tier-1 key ensures stale entries from a previous corpus are unreachable by construction, with no explicit invalidation step required.

**Labels.** `area:runtime`, `kind:feature`, `tier:2`

---

### E08_S04 — Tool-use ID canonicalization and hard retrieval caps

**Status:** NEW
**Tier:** 2
**Effort:** M
**Dependencies:** E08_S02

**Description.** Document and enforce two orchestrator-level rules that are critical for prompt-cache correctness and token-budget safety.

**Rule 1: Tool-use ID canonicalization.** The Anthropic API assigns server-side non-deterministic `id` fields to `tool_use` and `tool_result` content blocks (e.g., `toolu_01AbcXyz...`). These IDs are non-deterministic across API calls. When the orchestrator composes one agent's tool-call history into the prompt context for the next agent, the non-deterministic IDs cause the prompt prefix to diverge between agents, killing cross-agent cache reuse. The mitigation is mandatory: every `tool_use_id` echoed back in `tool_result` blocks must be replaced with a deterministic canonical ID before the turn is composed into another agent's context.

The canonical ID format is `toolu_{counter:08d}` where `counter` is a per-session monotonically increasing integer, reset to 0 at session start. The canonicalization function is `server/orchestrator/id_canon.py::canonicalize_turn(messages: list[dict]) -> list[dict]`. It is applied by the orchestrator immediately after receiving a tool-result block and before appending it to the shared context. The function is idempotent — applying it twice produces the same result.

**Rule 2: Hard retrieval caps.** The server enforces a per-session hard cap: maximum 3 retrieval rounds (calls to `search_papers`) and maximum 4 chunks materialized (calls to `get_chunk`). These caps prevent runaway retrieval loops and bound the token budget. The session state is tracked in a `SessionState` object keyed by `Mcp-Session-Id`. When a cap is reached, the tool returns a structured error with code `RETRIEVAL_CAP_REACHED` and a human-readable message directing the agent to proceed with the chunks already retrieved. The caps are enforced server-side — the client cannot override them.

Both rules are documented in `docs/orchestrator-rules.md`, which is the canonical reference for orchestrator implementors. The document includes the `canonicalize_turn` function in its docstring-level documentation and a worked example showing how IDs evolve across a 3-round retrieval session for a 4-agent fan-out.

**Deliverables.**
- `server/orchestrator/id_canon.py` — `canonicalize_turn(messages) -> list` function with tests
- `server/session.py` — `SessionState` dataclass tracking retrieval-round count and chunk-materialization count per `Mcp-Session-Id`
- `server/middleware.py` — updated to initialize and enforce `SessionState` per session; return `RETRIEVAL_CAP_REACHED` error when caps are exceeded
- `docs/orchestrator-rules.md` — canonical reference: ID canonicalization rule + worked example; hard-cap rule; rationale for each

**Acceptance criteria.**
- [ ] `canonicalize_turn` replaces non-deterministic IDs with `toolu_00000000`, `toolu_00000001`, etc.
- [ ] Applying `canonicalize_turn` twice produces the same output as applying it once
- [ ] A session that calls `search_papers` four times receives `RETRIEVAL_CAP_REACHED` on the fourth call
- [ ] A session that calls `get_chunk` five times receives `RETRIEVAL_CAP_REACHED` on the fifth call
- [ ] `docs/orchestrator-rules.md` contains the `canonicalize_turn` pseudocode and a worked 4-agent example
- [ ] `pytest server/orchestrator/test_id_canon.py` passes

**Out of scope.** Per-agent (sub-session) caps. Dynamic cap adjustment based on query complexity. Client-side cap enforcement.

**Risk notes.**
- Closes MEDIUM: tool-use ID canonicalization — this is described in `.claude/notes/07-multi-agent-caching.md` lines 79–108 as "the single most underrated optimization in agentic pipelines." Without it, the downstream prompt prefix diverges after the first tool call and cross-agent cache reuse is impossible.

**Labels.** `area:runtime`, `kind:design`, `tier:2`

---

### E08_S05 — Model selection policy and verifier pass removal

**Status:** NEW
**Tier:** 2
**Effort:** S
**Dependencies:** E08_S01, E08_S02

**Description.** Document and enforce the model selection policy for the 4-agent pipeline. This milestone is primarily a documentation and configuration milestone — it freezes decisions that are load-bearing for cost, latency, and cache behavior.

**Model policy (v1):**
- **Claude Haiku 4.5**: default model for all retrieval turns (any `search_papers`, `get_chunk`, `find_equation`, etc.) and all draft turns (Lookup, Synthesis, Verification roles).
- **Claude Sonnet 4.6**: used ONLY for the Autoformalizer role's Lean-syntax write step — the single turn that produces the final Lean 4 output. All other Autoformalizer turns (retrieval, context assembly) use Haiku 4.5.
- **Claude Opus 4.7**: NOT used in v1. Rationale: 35% tokenizer expansion relative to Sonnet 4.6 makes Opus economically nonviable for retrieval-heavy pipelines at current pricing; revisit in v2.

**Verifier pass: DROPPED.** The v1 design had a dedicated Verification agent that re-read retrieved chunks to validate proof steps. This pass is eliminated. The core argument: the verifier reads from the same MCP corpus as the other agents. If the retrieved chunks contain a misranked or irrelevant result, the verifier is reading the same misranked content and cannot catch the error. The correct verifier for mathematical proofs is the Lean kernel — it is the only critic that is (a) independent of the retrieval corpus and (b) formally sound. The Verification RouteTag remains in the router (E08_S01) for query classification purposes — queries classified as Verification go to the Autoformalizer role, which produces Lean syntax for kernel checking.

These decisions are documented in `docs/model-policy.md`. The orchestrator selects the model via `server/orchestrator/model_selector.py::select_model(route_tag, turn_type) -> str`, which maps `(RouteTag, TurnType)` pairs to model IDs. This function is the single source of truth for model selection — no model ID strings appear elsewhere in the orchestrator.

**Deliverables.**
- `server/orchestrator/model_selector.py` — `select_model(route_tag, turn_type) -> str` function; model ID constants
- `docs/model-policy.md` — model selection table; verifier-pass removal rationale; Opus 4.7 deferral rationale; token-budget estimates per query type
- `tests/test_model_selector.py` — asserts Haiku 4.5 for retrieval turns; Sonnet 4.6 only for Autoformalizer write step; Opus 4.7 not referenced anywhere

**Acceptance criteria.**
- [ ] `select_model(RouteTag.AUTOFORMALIZATION, TurnType.LEAN_WRITE)` returns `"claude-haiku-4-5"` — wait, correction: returns `"claude-sonnet-4-6"`
- [ ] `select_model(RouteTag.SYNTHESIS, TurnType.RETRIEVAL)` returns `"claude-haiku-4-5"`
- [ ] `select_model(RouteTag.VERIFICATION, TurnType.DRAFT)` returns `"claude-haiku-4-5"` (Verification → Autoformalizer path)
- [ ] The string `"claude-opus"` does not appear anywhere in `server/` source files
- [ ] `docs/model-policy.md` includes a section titled "Verifier pass: dropped and why"
- [ ] `pytest tests/test_model_selector.py` passes

**Out of scope.** Dynamic model selection based on query complexity. Opus 4.7 integration (v2). Fine-tuned models.

**Risk notes.**
- Closes H10: the verifier pass is circular — it reads from the same potentially-misranked corpus that the other agents use. Lean kernel is the correct mathematical critic and is independent of the retrieval system. Dropping the verifier pass reduces per-query cost by approximately 25% and eliminates a category of false confidence.

**Labels.** `area:runtime`, `kind:design`, `tier:2`
