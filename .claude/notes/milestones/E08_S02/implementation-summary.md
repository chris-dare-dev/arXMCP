# E08_S02 — Implementation summary

## What shipped

Three new files implementing the role-as-user-turn-prefix design
and BP1/BP2 cache breakpoint contract:

| Path | LOC | Purpose |
|---|---|---|
| `server/prompts.py` | 167 | Frozen importable constants (4 role prefixes, SYSTEM_PROMPT placeholder, beta-header constants), `MappingProxyType`-wrapped, with import-time closed-at-four assertion. |
| `server/prompts.md` | 191 | Human-readable companion: full breakpoint contract, the verbatim AC #4 sentence, ASCII message-structure diagram, cross-references. |
| `tests/test_prompts.py` | 437 | 24 tests across 8 classes: token cap, completeness, AST literal-only, runtime immutability, AC #4 verbatim grep, BP1 byte-identity across the 4-agent fan-out, beta-header constants, closed-at-four. |

All 24 new tests pass. Full pytest suite (1033 tests collected) green.
`ruff check .` clean.

## How acceptance criteria are met

| AC | Where it's enforced |
|---|---|
| Each role prefix ≤ 50 tokens | `tests/test_prompts.py::TestPrefixTokenCap` — parametrized over `RouteTag`, asserts `len(prefix) <= 200` (50 × 4 chars/token heuristic, conservative for English ASCII per Anthropic docs) AND `prefix.isascii()` (post-rectification F8 fix narrows the heuristic's domain to ASCII). Measured chars: LOOKUP=156, SYNTHESIS=157, VERIFICATION=196 (98% of cap), AUTOFORMALIZATION=170. VERIFICATION is the tightest; future edits adding any clause overshoot. |
| Exactly 4 role-prefix constants in `server/prompts.py`, one per `RouteTag` | `ROLE_PREFIXES: Mapping[RouteTag, str]` dict literal in `server/prompts.py`; import-time `assert set(ROLE_PREFIXES.keys()) == set(RouteTag)`; tests in `TestPrefixCompleteness` cover dict size, key set, and per-tag presence. |
| `tests/test_prompts.py` passes | `24 passed in 0.15s`. |
| `server/prompts.md` contains the verbatim AC #4 sentence | `tests/test_prompts.py::TestDocBP3DropSentence::test_prompts_md_contains_ac4_sentence_verbatim` — byte-exact substring check for `"BP3 is dropped; heterogeneous roles never share seed retrieval bytes"`. The sentence appears twice in `prompts.md` (TL;DR bullet + "Why BP3 was dropped" header bullet) so a future doc rewrite that drops one still surfaces it from the other. |
| 4-agent fan-out hash equality for BP1 | `tests/test_prompts.py::TestBP1ByteIdentityAcrossFanout` — builds 4 fake `messages.create(...)` request dicts (one per `RouteTag`), extracts the `{system, tools}` BP1 region, canonical-JSONs and SHA-256s each, asserts all 4 hashes equal. Two additional tests assert the BP2 region (role prefix + problem) DIVERGES across roles (sanity: encoding the role somewhere is non-trivial), and that the 4 prefixes themselves all hash distinctly (sanity: prefixes are not silently identical). |

## Design choices made (with rationale anchored to research synthesis)

- **`ROLE_PREFIXES` dict in `MappingProxyType`** (D1 in `research-synthesis.md`) — tighter API surface than 4 bare constants; immutable at runtime as a defense alongside the AST literal-only check.
- **Token-cap heuristic `len(prefix) <= 200`** (D3) — NO new deps. Project actively rejects `import anthropic` (asserted in `tests/test_snippet_contract.py:340-351`). `tiktoken` would be a polite lie about Claude tokens. The 4 chars/token figure comes from Anthropic's own English-ASCII docs.
- **Role prefix + problem statement in the SAME `{"type": "text"}` content block** separated by `"\n\n"` (D9) — fewer content blocks means fewer surface points for a future edit to break BP2.
- **Placeholder `SYSTEM_PROMPT`** (D7) — E08_S04 owns the v1 system-prompt body. The BP1 byte-identity test only needs a stable byte surface to hash; content is irrelevant for this milestone.
- **NO `EXPECTED_BP1_SHA256` pin** — the hash is dependent on the placeholder. Pinning now means E08_S04 must update the constant when the real prompt lands. Test stays a structural assertion (4 hashes equal each other) rather than a pin.
- **Synthetic stub tools list in BP1 test** (deviation from D8) — importing `server.tools.register_all` pulls in lancedb + FastMCP transitively, which slows the unit test and crosses module boundaries. The test's contract is "system + tools are byte-identical across roles", not "the byte content matches production". Synthetic stubs satisfy the contract and keep the test pure-stdlib.

## Critique closure

- **H2: BP3 seed cache not stable → DROPPED, BP1+BP2 only** — closed. `server/prompts.md` documents the rationale: heterogeneous roles issue heterogeneous tool calls, so the seed retrieval bytes diverge immediately after the user turn. Spending a `cache_control` slot on a fictional shared BP3 would either be invalid OR force every agent through one role's retrieval (defeating the heterogeneous-fan-out point).
- **MEDIUM: Sub-agent role-specific system prompts → no cross-role caching** — closed. Encoding role in the FIRST user turn keeps the system + tools block byte-identical across the fan-out, achieving the 80–95% input-token cache hit rate described in `.claude/notes/07-multi-agent-caching.md:320-326`. The test suite proves the byte-identity at hash level.

## External writes performed

None. Pure-internal:
- `server/prompts.py` (new)
- `server/prompts.md` (new)
- `tests/test_prompts.py` (new)
- `.claude/notes/milestones/E08_S02/*` (research artifacts + state)

No git push. No PR. No third-party API call. No new runtime dependency.

## Integration seam for E08_S04 (next milestone)

The orchestrator imports `ROLE_PREFIXES` and composes the
messages-API request body as documented in `server/prompts.py`'s
module docstring AND in `server/prompts.md`'s "Message structure for
a Synthesis turn" diagram. The contract is:

```python
from server.prompts import (
    ROLE_PREFIXES, SYSTEM_PROMPT,
    EXTENDED_CACHE_TTL_HEADER_NAME, EXTENDED_CACHE_TTL_HEADER_VALUE,
)
messages = [{"role": "user", "content": [{
    "type": "text",
    "text": ROLE_PREFIXES[tag] + "\n\n" + problem_statement,
    "cache_control": {"type": "ephemeral", "ttl": "1h"},
}]}]
# system + tools also get cache_control on their LAST element (BP1).
```

The 4-breakpoint per-request budget retains 2 unused slots (BP3 +
BP4) for future use.

## Files for the critic to focus on

- `server/prompts.py:107-130` — the four prefix string literals; correctness of intent + token budget
- `server/prompts.py:137-159` — the `MappingProxyType` wrapping + closed-at-four assert
- `tests/test_prompts.py::TestFrozenConstantsDiscipline` — the AST literal-only check; verify it actually catches f-strings / `.format` / `+`-concat / `Name`-pointing-to-non-literal
- `tests/test_prompts.py::TestBP1ByteIdentityAcrossFanout` — verify the test's `_build_fanout_request` mirrors a realistic Anthropic messages.create kwargs shape and that the BP1 region is correctly defined
- `server/prompts.md` — verify the AC #4 sentence is byte-exact, the BP3 rationale is sound, and the diagram is accurate
