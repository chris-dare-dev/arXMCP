# E08_S02 — Research Brief 1

## 1. In-codebase context

### Critical files to read first

**`.claude/notes/07-multi-agent-caching.md`** — load-bearing constants quoted verbatim:

- Lines 25–27 (`anthropic-beta` header name and TTL):
  > "**Up to 4 `cache_control` breakpoints per request.** Use them deliberately."
  > "**TTL:** 5 minutes default; **1 hour** via beta header `anthropic-beta: extended-cache-ttl-2025-04-11` (verify exact name)."
- Lines 30–32 (cache key invariant — pinned BP1 byte rules):
  > "Cache key is the hash of the exact prefix bytes including system prompt, tool definitions, and prior turns up to the breakpoint. Any whitespace or ordering change invalidates."
- Lines 65–71 (the H2 closure preamble already in the constitution):
  > "Updated 2026-05-06 (see E08_S02 ... closing critique H2). BP3 is dropped. Heterogeneous agent roles ... issue heterogeneous tool calls; their seed-retrieval results diverge immediately after the first tool call and can never share a byte-identical BP3 prefix."
- Lines 74–82 (the BP1/BP2 rule we are encoding):
  > "Breakpoint 1 (BP1, 1-hour TTL): end of system prompt + tool definitions block. Byte-identical across every agent role because roles are encoded as a ≤50-token prefix in the first *user* turn (not as per-role system prompts)."
  > "Breakpoint 2 (BP2, 1-hour TTL): end of the problem statement."
  > "BP3 / BP4: reserved for future use. Do not place at seed-retrieval results."
- Lines 84–85: "Use the **1-hour TTL** (extended-cache-ttl beta header) for BP1 and BP2."
- Lines 326–333 (the 80–95% target this milestone is closing toward):
  > "Anthropic prompt cache: 80–95% of input tokens on the second-and-subsequent agent calls in a pipeline (the corpus-shaped prefix is the long part of the prompt)."

**`.claude/roadmap/README.md:69`** — H2 row in the critique-remediation matrix:
> "| **H2** | BP3 seed cache not stable → DROPPED, BP1+BP2 only | E08_S02, E08_S03 |"

And README:91:
> "| **MEDIUM** | Sub-agent role-specific system prompts → no cross-role caching | E08_S02 |"

**`.claude/roadmap/E08-agent-runtime.md:55–97`** — full milestone brief (already mirrored into `state.json`).

**`server/router.py:90–103`** — `RouteTag` confirmed as `enum.StrEnum` with exactly:
```python
class RouteTag(StrEnum):
    LOOKUP = "LOOKUP"
    SYNTHESIS = "SYNTHESIS"
    VERIFICATION = "VERIFICATION"
    AUTOFORMALIZATION = "AUTOFORMALIZATION"
```
Import via `from server.router import RouteTag`. The `.value` strings (uppercase) are what we'll dict-key against the prefix constants — keep the spelling identical (the comment at router.py:91 calls out: "adding a fifth value requires coordination with E08_S02").

**`server/prompts.py` and `server/prompts.md`** — do **not** exist (`ls server/` confirmed). Net-new files.

**`server/tools.py`** — relevant constants for the BP1 surface:
- `TOOL_SCHEMA_VERSION: int = 1` (line 64)
- `ALL_TOOLS: tuple[ToolMeta, ...]` (line 191)
- `register_all(mcp_server: FastMCP)` (line 359), which sets `meta={"tool_schema_version": TOOL_SCHEMA_VERSION}`
The BP1 byte surface is whatever `mcp_server.list_tools()` serializes plus the system prompt. There is **no** system prompt defined yet in this repo (none of the orchestrator files exist); for the milestone's 4-agent fan-out test, the "system prompt" component must be either (a) a sentinel `SYSTEM_PROMPT = ""` constant exported from `server/prompts.py`, or (b) a placeholder TBD that E08_S04 fills in. Recommend (a): define `SYSTEM_PROMPT: str = ""` now so the BP1 hash test has a real surface to bind, and update later.

**`tests/test_server_tool_schema.py`** — the discipline to mirror. The pattern is:
1. Pin a SHA-256 hash as a load-bearing constant (`EXPECTED_TOOL_SCHEMA_SHA256`, line 94).
2. Anchor with `# UPDATE-ANCHOR` / `# VERSION-ANCHOR` regex sentinels (lines 198–216).
3. Provide `--update-tool-schema-hash` flag that rewrites the file in place; refuse the flag in CI (`_running_in_ci()` at line 308).
4. Canonical serialization: `result.model_dump(mode="json", by_alias=True, exclude_none=True)` then `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)` (lines 173–179).

E08_S02's BP1-byte-identity test should reuse `compute_tool_schema_hash` from this file (or refactor the helper into `server/_canonical.py`) so the BP1 hash and the tool-schema hash share one canonicalizer. Do **not** duplicate the serialization logic.

**`pyproject.toml`** — read in full. Confirmed: **no `anthropic` SDK dep, no `tiktoken` dep, no Claude tokenizer pin**. Adding `anthropic` would pull a network-capable client into the test path; adding `tiktoken` (~10 MB compiled wheel) is the smaller footprint.

## 2. Prior decisions and lessons

### Tokenizer choice — recommendation

**Recommend: a custom heuristic upper-bound at `len(prefix) // 3` characters**, **not** tiktoken, not anthropic SDK. Rationale:

- The Claude Sonnet 4.6 tokenizer is **not open-sourced**. There is no offline ground-truth oracle.
- `client.beta.messages.count_tokens(...)` requires `ANTHROPIC_API_KEY` and a network round-trip per test run — disqualifying for CI.
- `tiktoken` with `cl100k_base` is the OpenAI tokenizer; for English ASCII it averages within ~5–10% of Claude's BPE, but for `[Role: Autoformalizer]` with brackets and Mathlib it diverges. Using it as a "Claude proxy" is a polite lie.
- A **strict upper bound** assertion sidesteps the precision question. Empirical Anthropic guidance: ~3.5 chars/token for English; LaTeX/code closer to 2.5. A `len(prefix) <= 50 * 3` (=150 chars) hard cap is conservative — guarantees ≤50 tokens under any plausible BPE.

Document the trade-off in a docstring on the test helper. Adopt path: `assert len(prefix) <= 150, "≤50 Claude tokens upper-bound (3 chars/token heuristic)"`. If the implementer prefers tighter binding, add `tiktoken>=0.7` to `[project.optional-dependencies].dev`, use `cl100k_base`, and assert `<= 50` directly with a `WARN: approximate Claude tokens` comment. **Do not add the `anthropic` SDK.** Per `tests/test_snippet_contract.py:344`, the project actively asserts that `anthropic` is **not** importable as a side effect of handler load.

### The four prefixes — concrete proposals (≤150 chars each)

```python
LOOKUP = (
    "[Role: Lookup] Retrieve the named mathematical object below. "
    "Return the corpus chunk verbatim. Do not paraphrase or summarize."
)  # 138 chars
SYNTHESIS = (
    "[Role: Synthesis] Assemble a proof strategy across retrieved chunks. "
    "Cite chunk_id for every claim. Do not invent lemmas not in the corpus."
)  # 146 chars
VERIFICATION = (
    "[Role: Verification] Validate the candidate proof step below. "
    "Reject any unjustified inference. Cite chunk_id for each accepted step."
)  # 144 chars
AUTOFORMALIZATION = (
    "[Role: Autoformalizer] Translate the following mathematical content to "
    "Lean 4 using Mathlib conventions. Produce only valid Lean 4 syntax. "
    "Do not paraphrase or summarize."
)  # 173 chars — TRIM to fit; the brief's example is verbatim 173 chars; this exceeds the 150-char heuristic.
```

The last constant is the milestone's verbatim example (E08-agent-runtime.md:67) and overshoots a strict 3-chars/token heuristic. Two acceptable resolutions: (a) raise the per-prefix char limit to 175 (4 chars/token, closer to ASCII English reality and what Anthropic's docs use); (b) trim Autoformalizer to "Translate the content below to Lean 4 (Mathlib). Output Lean 4 syntax only. No prose." (~100 chars). **Recommend (a)**: raise the heuristic to `MAX_PREFIX_CHARS = 200` (= 50 tokens × 4 chars/token, the standard English-ASCII Anthropic figure) and keep the brief's example unchanged. Document the 4-chars/token derivation in `server/prompts.md`.

### Frozen-constant assertion (no runtime interpolation)

AST-parse `server/prompts.py`. For each `ast.Assign` whose target name is in the role-constant set, assert:
- `node.value` is `ast.Constant(value=str)`, OR `ast.Call(func=ast.Attribute(attr='join'))` with all-literal args, OR a parenthesized concatenation of `ast.Constant(value=str)` (Python represents string concatenation across line breaks as a single `Constant` after parser folding — verify with `ast.dump`).
- Reject `ast.JoinedStr` (f-strings), `ast.BinOp` with `%` (printf), and any `ast.Call` whose `.attr == "format"`.

This is the right test (cleaner than runtime introspection because module-load might silently materialize an interpolated value into a `str`).

### BP1 byte-identity test — concrete construction

"BP1 prefix" = `system + tools-list-canonical-json` up to (but not including) the first user message. Construct four hypothetical Anthropic-Messages-API request bodies, one per `RouteTag`:

```python
def build_request(role: RouteTag, problem: str) -> dict:
    return {
        "system": SYSTEM_PROMPT,                       # constant; "" for v1
        "tools": list_tools_canonical(),               # reuse compute_tool_schema_hash helper
        "messages": [{
            "role": "user",
            "content": [{"type": "text",
                         "text": ROLE_PREFIX[role] + "\n\n" + problem}],
        }],
    }
```

The BP1 hash is `sha256(canonical_json({"system": ..., "tools": ...}).encode())`. Assert all four roles produce the **same** hash for the same `(SYSTEM_PROMPT, tools)`. Pin the value as `EXPECTED_BP1_SHA256` with the same UPDATE-ANCHOR sentinel pattern from `tests/test_server_tool_schema.py:198`.

### Message-structure diagram in `prompts.md`

```
system: <SYSTEM_PROMPT>           ─┐
tools:  [<7 frozen ToolMetas>]     │  BP1 region
                                   │  cache_control: {"type": "ephemeral", "ttl": "1h"}
─────────── BP1 ─────────────────  ─┘  (anthropic-beta: extended-cache-ttl-2025-04-11)

messages:
  - role: user
    content:
      - type: text
        text: |
          [Role: Synthesis] Assemble a proof strategy across retrieved chunks. ...

          <problem-statement-here>
        cache_control: {"type": "ephemeral", "ttl": "1h"}
─────────── BP2 ─────────────────
  - role: assistant       ← model output begins; tool_use blocks may follow
  - role: user            ← tool_result blocks; NO BP3 here (heterogeneous)
```

### Where the prefix is INJECTED

E08_S02 owns **only** the constants + the static byte-identity test. The runtime injection lives in the orchestrator (E08_S04 — `server/orchestrator/id_canon.py` and surrounding files in E08-agent-runtime.md:159–164). **Do not write orchestrator code in this milestone.** The test mocks the request body inline.

## 3. External sources

- **Anthropic prompt caching docs** — https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching. Verify the exact `cache_control` shape (`{"type": "ephemeral"}` vs `{"type": "ephemeral", "ttl": "1h"}`) and the beta header literal (`extended-cache-ttl-2025-04-11` per `07-multi-agent-caching.md:27`; "verify" disclaimer is in the source). The 4-breakpoint-per-request budget is documented here.
- **Anthropic count_tokens** — https://docs.anthropic.com/en/api/messages-count-tokens. Network-bound; not used (see tokenizer recommendation).
- **Claude Sonnet 4.6 release notes** — model card at https://docs.anthropic.com/en/docs/about-claude/models. No public tokenizer change has been announced; same BPE family as 4.5/4.7.
- **H2 critique remediation** — `.claude/roadmap/README.md:69`. Already mapped; no external fetch needed.

## Open questions

1. **`SYSTEM_PROMPT` content for v1.** No system prompt exists yet. Recommend defining `SYSTEM_PROMPT: str = ""` in `server/prompts.py` so the BP1 hash test binds to a stable surface; the prompt body is owned by E08_S04. Confirm with reviewer that empty-string is acceptable and the BP1 hash will be re-pinned when E08_S04 lands.
2. **Char-budget heuristic: 3 vs 4 chars/token.** Recommend **4 chars/token (200-char cap)** to keep the brief's verbatim Autoformalizer example. Confirm with reviewer or trim the example.
3. **Whether to add `tiktoken` as a dev dep.** Recommend **no** — heuristic upper bound is sufficient; tiktoken-as-Claude-proxy is misleading. Confirm.

## External writes the implementation will require

**Zero.** This milestone is constants + static tests. No PR creation, no infra changes, no third-party API calls (the tokenizer recommendation is offline-only). If the implementer overrides the tokenizer recommendation in favor of the Anthropic `count_tokens` API, that introduces a network call **and** an `ANTHROPIC_API_KEY` requirement in CI — flag, escalate, do not proceed unilaterally.
