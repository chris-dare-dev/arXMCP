# E08_S02 — Research synthesis

## Both researchers agree on these load-bearing facts

1. **`server/router.py:90-103`** — `RouteTag` is `enum.StrEnum` with values `LOOKUP`, `SYNTHESIS`, `VERIFICATION`, `AUTOFORMALIZATION`. Closed at four for v1. Import as `from server.router import RouteTag`.

2. **`server/prompts.py` and `server/prompts.md` do NOT exist** — net-new files.

3. **Anthropic SDK is NOT a dep** (`pyproject.toml` confirmed). `tests/test_snippet_contract.py:340-351` actively asserts that `import anthropic` is NOT present at handler load. The tokenizer test MUST NOT add `anthropic`.

4. **No offline Claude tokenizer exists**. Three candidate strategies:
   - Heuristic (`len(text) // 4`): conservative upper bound; zero deps.
   - `tiktoken.cl100k_base` (OpenAI BPE): tighter approximation; adds ~10 MB dev dep.
   - Anthropic API `count_tokens`: requires `ANTHROPIC_API_KEY` + network; rejected.

5. **The brief's verbatim AC #4 sentence** must appear in `prompts.md`: *"BP3 is dropped; heterogeneous roles never share seed retrieval bytes"*. Byte-exact, not paraphrased.

6. **The BP1 byte-identity test** constructs 4 fake `messages.create(...)` kwargs dicts (one per RouteTag), extracts the system + tools serialization, asserts byte-equality across all 4. NO live Anthropic API call.

7. **The integration seam to E08_S04** (orchestrator) is documented but NOT implemented in this milestone — E08_S02 ships constants + tests + docs only.

## Decisions for the implementer

| ID | Decision | Rationale |
|---|---|---|
| D1 | **`ROLE_PREFIXES: Mapping[RouteTag, str]` wrapped in `types.MappingProxyType`** for runtime immutability. Satisfies the brief's "exactly 4 role-prefix constants" via dict literal. Downstream `ROLE_PREFIXES[tag]` is O(1). | Brief 2: tighter API surface than 4 bare constants; immutable-at-runtime defense alongside the AST literal-only check. |
| D2 | **Import-time assertion** `set(ROLE_PREFIXES) == set(RouteTag)` so a future fifth `RouteTag` fails the import loudly. | Defense in depth against the closed-at-four invariant from E08_S01. |
| D3 | **Token-cap heuristic: `len(prefix) <= 200` (= 50 × 4 chars/token)**. NO new deps (no `tiktoken`, no `anthropic`). Document the heuristic + rationale prominently. | Brief 1 + project no-network discipline. Anthropic's own docs cite 4 chars/token for English. The brief's verbatim Autoformalizer example is 173 chars — fits. |
| D4 | **Four prefix texts** (each ≤ 200 chars; brief Autoformalizer verbatim): see synthesis D-Prefixes table below. | Composed from Brief 1 + 2 + brief's example. |
| D5 | **AST literal-only check** rejects `JoinedStr` (f-strings), `Call` with `.format`, `BinOp` (str concat via `+` or `%`). Walks the `ROLE_PREFIXES` dict literal, asserts every value is `Constant(value=str)`. | Both briefs converged. F-strings rejected even when they have no placeholders — a future edit to a placeholder variable silently invalidates BP1. |
| D6 | **BP1 byte-identity test**: `sha256(canonical_json({"system": ..., "tools": ...}))` where `canonical_json` uses `sort_keys=True, separators=(",", ":"), ensure_ascii=True` (mirrors `tests/test_server_tool_schema.py`'s discipline). 4 fake request bodies, one per RouteTag; assert all 4 hashes equal. | Brief 1: reuse the canonicalizer pattern from E06_S06's hash pin. Determinism contract from `.claude/notes/07-multi-agent-caching.md:58`. |
| D7 | **`SYSTEM_PROMPT` placeholder constant** in `server/prompts.py`: `SYSTEM_PROMPT: str = "<placeholder; E08_S04 will author the v1 system prompt>"`. The BP1 test asserts byte-equality across roles — the actual content doesn't matter for this milestone. | Brief 1+2: E08_S04 owns the system prompt body. |
| D8 | **Tools-list source for BP1**: import the real `server/tools.py` registration via `register_all` + `mcp_server.list_tools()`. The test then doubles as defense-in-depth for E06_S06's hash pin. | Brief 2: cheaper to verify against real surface than maintain a parallel fixture. |
| D9 | **Role prefix + problem statement in the SAME content block** separated by `\n\n` — single `{"type": "text"}` element. Fewer content blocks = fewer places for a future edit to break BP2. | Brief 2 recommendation. |
| D10 | **`prompts.md` carries the ASCII message-structure diagram** for a Synthesis turn (showing system + tools → BP1 → user(role-prefix + problem) → BP2 → divergent tool calls → no BP3). | Brief 2's diagram is concrete enough to copy. |
| D11 | **Frozen Anthropic beta header constant** `EXTENDED_CACHE_TTL_HEADER = "anthropic-beta: extended-cache-ttl-2025-04-11"` exported from `server/prompts.py` for downstream consumers (E08_S04). | Per `.claude/notes/07-multi-agent-caching.md:27`. |
| D12 | **Tool-determinism precondition documented in test docstring**: if BP1 byte-equality flakes, the cause is upstream tool drift; point at `server/tools.py` + E06_S06's hash pin to debug from. | Brief 2 — saves the next debugger time. |

### D-Prefixes: the four prefix strings

```
LOOKUP (~136 chars, ≤ 200):
  [Role: Lookup] Retrieve the named definition, theorem statement,
  or notation from the corpus. Quote verbatim with citations.
  Do not paraphrase or interpret.

SYNTHESIS (~153 chars, ≤ 200):
  [Role: Synthesis] Assemble a proof strategy from the retrieved
  chunks. Cite every chunk you use. Do not invent results that
  are not in the retrieved context.

VERIFICATION (~177 chars, ≤ 200):
  [Role: Verification] Validate the candidate proof step against
  the retrieved authoritative sources. Cite the chunk that
  confirms or refutes each step. Do not assume facts not present
  in retrieval.

AUTOFORMALIZATION (~173 chars, ≤ 200; brief verbatim):
  [Role: Autoformalizer] Translate the following mathematical
  content to Lean 4 using Mathlib conventions. Produce only
  valid Lean 4 syntax. Do not paraphrase or summarize.
```

All four open with `[Role: <Name>]` and end with a hard "Do not …" line — matches the brief's Autoformalization template + the no-paraphrasing-summarizer rule.

## Open questions

1. **Tighter token measurement (tiktoken)?** — out of scope for this milestone. If the heuristic proves too conservative in practice, a follow-up can add `tiktoken>=0.7` as a dev dep + a `requires_tiktoken` marker.

2. **Pin the BP1 hash with `EXPECTED_BP1_SHA256` constant?** — defer. The hash depends on the placeholder `SYSTEM_PROMPT`; pinning now means E08_S04 must update the constant when the real system prompt lands. Keep the test as a structural assertion (4 hashes equal each other) rather than a hash-pin.

## External writes the implementation will require

None. Pure-internal:
- `server/prompts.py` (new)
- `server/prompts.md` (new)
- `tests/test_prompts.py` (new)

No git push, PR creation, ticket mutation, or third-party API call. NO new runtime deps. NO Anthropic API access required for any test.
