# Role prefixes + cache breakpoint contract (E08_S02)

This document is the human-readable companion to
`server/prompts.py`. It pins the four role-prefix templates, the
cache breakpoint placement rule, and the rationale for dropping
BP3 (closing critique H2). The orchestrator (E08_S04) and any
future agent-runtime contributor must read this BEFORE editing the
prompt or breakpoint surface.

## TL;DR

- Each agent role gets a **≤50-token prefix** injected at the start
  of the FIRST user turn — NOT a per-role system prompt.
- This makes **BP1** (system + tool definitions) **byte-identical
  across all four roles**, enabling the longest, most valuable
  prompt-cache prefix to be shared across the entire 4-agent
  fan-out.
- BP3 is dropped; heterogeneous roles never share seed retrieval bytes.
  (See "Why BP3 was dropped" below — the brief AC #4 mandates this
  exact sentence appear here.)
- BP2 is placed at the end of the role-prefix + problem-statement
  user turn — stable across the fan-out for one query session.

## The four role prefixes

The strings live in `server/prompts.py` as
`ROLE_PREFIXES: Mapping[RouteTag, str]`. Each is a bare string
literal — no f-string interpolation, no `.format()`, no `+`
concatenation with non-literals. The AST literal-only check in
`tests/test_prompts.py` enforces the discipline.

### `RouteTag.LOOKUP`

> [Role: Lookup] Retrieve the named definition, theorem statement,
> or notation from the corpus. Quote verbatim with citations. Do
> not paraphrase or interpret.

**When this fires.** Queries like "what is the definition of
étale", "Theorem 3.4 in Hartshorne", "notation for the Picard
group". The router (E08_S01) routes via the LOOKUP regex block.
The agent's job is to retrieve a named object and return it
verbatim with chunk citations.

### `RouteTag.SYNTHESIS`

> [Role: Synthesis] Assemble a proof strategy from the retrieved
> chunks. Cite every chunk you use. Do not invent results that
> are not in the retrieved context.

**When this fires.** Queries with explicit derivation verbs:
"prove", "show that", "derive", "sketch". The agent assembles a
proof strategy across multiple retrieved chunks.

### `RouteTag.VERIFICATION`

> [Role: Verification] Validate the candidate proof step against
> the retrieved authoritative sources. Cite the chunk that confirms
> or refutes each step. Do not assume facts not present in
> retrieval.

**When this fires.** Queries with validation verbs: "verify",
"check", "validate", "is X correct". The agent receives a
candidate proof step and validates it against authoritative
sources.

### `RouteTag.AUTOFORMALIZATION`

> [Role: Autoformalizer] Translate the following mathematical
> content to Lean 4 using Mathlib conventions. Produce only valid
> Lean 4 syntax. Do not paraphrase or summarize.

**When this fires.** Queries mentioning Lean / Mathlib / formalize
/ translate-to-lean. The agent produces Lean 4 syntax suitable for
kernel checking. Lean is a hard mode-switch — the router gives
this tag the highest priority.

## Cache breakpoint placement

### BP1 — System + tool definitions (1-hour TTL)

Placed at the end of the system prompt + tool definitions block.

**Byte-identical across all four roles.** This is the load-bearing
property of the role-as-user-turn-prefix design: a per-role
system prompt would produce four distinct BP1 prefixes and
eliminate cross-role cache hits. Encoding role in the user turn
keeps system + tools constant across the fan-out.

Use the extended-cache-ttl beta header per
`.claude/notes/07-multi-agent-caching.md:27`:

```
anthropic-beta: extended-cache-ttl-2025-04-11
```

Constants exported from `server/prompts.py`:
- `EXTENDED_CACHE_TTL_HEADER_NAME = "anthropic-beta"`
- `EXTENDED_CACHE_TTL_HEADER_VALUE = "extended-cache-ttl-2025-04-11"`

### BP2 — Problem statement (1-hour TTL)

Placed at the end of the role-prefix + problem-statement user
turn. The role prefix and the problem statement live in the **same
content block** separated by `\n\n`:

```python
{"type": "text",
 "text": ROLE_PREFIXES[tag] + "\n\n" + problem_statement,
 "cache_control": {"type": "ephemeral", "ttl": "1h"}}
```

Why same content block: fewer content blocks means fewer surface
points for a future edit to break BP2. The combined block is
byte-stable for one query session across the 4-agent fan-out
(the role differs but the *cache key* is hashed up to and
including the BP2 marker, which is at the end of THIS block —
each role gets its own BP2 hash, but for an individual role's
multiple turns, BP2 stays valid).

### Why BP3 was dropped

BP3 is dropped; heterogeneous roles never share seed retrieval bytes.

The original design hypothesized a third breakpoint at "seed
retrieval results" — the assumption being that multiple agents
would issue identical first tool calls and share the response
bytes. That assumption is false:

- **Lookup** issues `get_chunk(<named_object>)` — a single chunk.
- **Synthesis** issues `search_papers(<query>, level="theorem")` —
  a top-K candidate list.
- **Verification** issues `find_lemma_by_name(<lemma_name>)` —
  a name-keyed lookup.
- **Autoformalization** issues `get_definitions(<term>)` — a
  definitions-only retrieval.

These tool calls produce divergent response bytes immediately
after the user turn. A shared BP3 over those bytes would either
be invalid (each role sees different bytes) or would force every
agent through one role's retrieval (which defeats the whole
point of having heterogeneous roles).

Anthropic's per-request cache_control budget is **4 breakpoints**.
Spending one on a fictional shared BP3 would waste the slot AND
produce incorrect cache reuse on the off-chance any two roles did
happen to issue identical first calls. Better to leave BP3 / BP4
unused in v1 and reserve them for a future use that actually
needs them.

## Message structure for a Synthesis turn

```
┌───────────────────────────────────────────────────────────────┐
│ system:                                                       │
│   <SYSTEM_PROMPT — frozen, identical across all 4 roles>      │
│ tools:                                                        │
│   [search_papers, get_chunk, ... — frozen, sorted, identical] │
│                          ◄── BP1 cache_control (ttl: "1h")    │
├───────────────────────────────────────────────────────────────┤
│ user (turn 1):                                                │
│   ROLE_PREFIXES[RouteTag.SYNTHESIS]                           │
│     "[Role: Synthesis] Assemble a proof strategy..."          │
│   <problem statement, e.g. user query verbatim>               │
│                          ◄── BP2 cache_control (ttl: "1h")    │
├───────────────────────────────────────────────────────────────┤
│ assistant: tool_use(search_papers, ...)                       │
│ user:      tool_result(...)         ◄── divergent across roles│
│ assistant: tool_use(get_chunk, ...) ◄── BP3 INTENTIONALLY     │
│ user:      tool_result(...)             OMITTED — see above   │
│ assistant: <final answer>                                     │
└───────────────────────────────────────────────────────────────┘
```

Two `cache_control` markers per request — one for BP1, one for
BP2. The 4-breakpoint budget retains 2 unused slots for future
use.

## Cross-references

- `server/prompts.py` — the importable string constants.
- `server/router.py` — `RouteTag` enum + the regex classifier
  (E08_S01).
- `tests/test_prompts.py` — token-cap, AST literal-only,
  AC-#4-sentence-grep, and BP1 byte-identity tests.
- `.claude/notes/07-multi-agent-caching.md:74-82` — the BP1/BP2
  placement rule (constitutional source).
- `.claude/roadmap/README.md:69` — H2 critique row.
- `tests/test_server_tool_schema.py` — E06_S06's `tools/list`
  byte-stability hash; load-bearing for BP1 byte-identity.
