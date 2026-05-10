"""Role-prefix constants + cache-breakpoint contract (E08_S02).

Encodes each agent role as a ≤50-token prefix injected at the
start of the FIRST user turn — NOT as a per-role system prompt.
This design choice is load-bearing for prompt-cache efficiency:

- **BP1** (system + tool definitions) is BYTE-IDENTICAL across all
  four roles. The longest, most valuable cache prefix is shared
  across the entire 4-agent fan-out.
- A per-role system prompt would produce four distinct BP1 prefixes
  and eliminate cross-role cache hits.

The full breakpoint strategy is documented in ``server/prompts.md``;
the rationale for dropping BP3 lives there too. This module provides
the importable string constants only.

**Closes H2** (per ``.claude/roadmap/README.md:69`` — "BP3 seed
cache not stable → DROPPED, BP1+BP2 only") AND the MEDIUM finding
"Sub-agent role-specific system prompts → no cross-role caching"
(README:91).

**Frozen-constants discipline.** The prefixes are bare string
literals wrapped in :data:`types.MappingProxyType`. They MUST NOT
be:
- f-strings (``f"foo {bar}"``) — even with empty placeholders, a
  future edit silently invalidates BP1.
- ``.format()`` calls.
- ``+``-concatenated with any non-literal.
- ``%``-formatted.

``tests/test_prompts.py`` AST-parses this file and rejects any of
the above. The MappingProxyType wrapper is the runtime-immutability
defense alongside the AST check.

**Integration seam (E08_S04).** The orchestrator imports
``ROLE_PREFIXES`` and composes the messages-API request body as
follows (NOT shipped here — this module is constants only):

    from server.prompts import ROLE_PREFIXES, SYSTEM_PROMPT
    messages = [
        {"role": "user", "content": [{
            "type": "text",
            "text": ROLE_PREFIXES[tag] + "\\n\\n" + problem,
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        }]},
    ]
    request = {"system": SYSTEM_PROMPT, "tools": [...], "messages": messages}

The role prefix and the problem statement live in the SAME content
block separated by ``"\\n\\n"`` — fewer content blocks means
fewer surface points for a future edit to break BP2.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from server.router import RouteTag

# ---------------------------------------------------------------------------
# Cache-control beta header
# ---------------------------------------------------------------------------

#: The Anthropic beta header value enabling 1-hour cache TTL on
#: ``cache_control`` markers. Per
#: ``.claude/notes/07-multi-agent-caching.md:27``: *"1 hour via beta
#: header anthropic-beta: extended-cache-ttl-2025-04-11 (verify
#: exact name)."*. Frozen here so the orchestrator (E08_S04) imports
#: a single source of truth.
EXTENDED_CACHE_TTL_HEADER_NAME: str = "anthropic-beta"
EXTENDED_CACHE_TTL_HEADER_VALUE: str = "extended-cache-ttl-2025-04-11"


# ---------------------------------------------------------------------------
# System prompt placeholder
# ---------------------------------------------------------------------------

#: Placeholder system-prompt body. E08_S04 will author the v1 system
#: prompt; for E08_S02 the value only needs to be a stable byte
#: surface so the BP1 byte-identity test has something to hash.
#:
#: TODO(E08_S04): replace with the real system prompt and re-run the
#: BP1 byte-identity test against the new value.
SYSTEM_PROMPT: str = (
    "<placeholder system prompt — E08_S04 will author the v1 body. "
    "This text is byte-stable but informationally a no-op for v1.>"
)


# ---------------------------------------------------------------------------
# Role-prefix constants — frozen, literal-only, ≤ 50 Claude tokens each
# ---------------------------------------------------------------------------

#: Each prefix is a bare string literal (no f-string, no .format,
#: no concatenation). The 50-token cap is enforced via a
#: 200-character heuristic: per Anthropic's docs, English ASCII
#: averages ~4 chars/token; 50 × 4 = 200 char ceiling. The
#: heuristic is conservative (legitimate non-English / code-heavy
#: prefixes might pack denser than 4 c/t — but our prefixes are
#: pure English imperative).
#:
#: Each prefix opens with ``[Role: <Name>]`` (matching the brief's
#: Autoformalization example) and ends with a hard "Do not …" line
#: that constrains the agent — the no-paraphrasing-summarizer rule
#: from Anthropic's multi-agent research-system writeup.
_LOOKUP_PREFIX = (
    "[Role: Lookup] Retrieve the named definition, theorem statement, "
    "or notation from the corpus. Quote verbatim with citations. "
    "Do not paraphrase or interpret."
)

_SYNTHESIS_PREFIX = (
    "[Role: Synthesis] Assemble a proof strategy from the retrieved "
    "chunks. Cite every chunk you use. Do not invent results that "
    "are not in the retrieved context."
)

_VERIFICATION_PREFIX = (
    "[Role: Verification] Validate the candidate proof step against "
    "the retrieved authoritative sources. Cite the chunk that "
    "confirms or refutes each step. Do not assume facts not present "
    "in retrieval."
)

_AUTOFORMALIZATION_PREFIX = (
    "[Role: Autoformalizer] Translate the following mathematical "
    "content to Lean 4 using Mathlib conventions. Produce only "
    "valid Lean 4 syntax. Do not paraphrase or summarize."
)


#: The single source of truth for role → prefix mapping. Wrapped
#: in ``MappingProxyType`` so downstream consumers cannot mutate
#: the dict at runtime (defense alongside the AST literal-only
#: check at ``tests/test_prompts.py``).
ROLE_PREFIXES: Mapping[RouteTag, str] = MappingProxyType({
    RouteTag.LOOKUP: _LOOKUP_PREFIX,
    RouteTag.SYNTHESIS: _SYNTHESIS_PREFIX,
    RouteTag.VERIFICATION: _VERIFICATION_PREFIX,
    RouteTag.AUTOFORMALIZATION: _AUTOFORMALIZATION_PREFIX,
})


# ---------------------------------------------------------------------------
# Import-time invariants
# ---------------------------------------------------------------------------

# Closed-at-four invariant: the prefix dict MUST cover every
# RouteTag value. A future fifth value (e.g. someone adds
# ``RouteTag.EQUATION_FINDER``) without updating this module breaks
# the import loudly rather than silently routing through a KeyError
# at first use.
assert set(ROLE_PREFIXES.keys()) == set(RouteTag), (
    f"ROLE_PREFIXES keys {set(ROLE_PREFIXES.keys())} do not match "
    f"RouteTag values {set(RouteTag)}. Adding a new RouteTag "
    f"requires extending ROLE_PREFIXES with the new role's "
    f"≤50-token prefix in lockstep."
)


__all__ = [
    "EXTENDED_CACHE_TTL_HEADER_NAME",
    "EXTENDED_CACHE_TTL_HEADER_VALUE",
    "ROLE_PREFIXES",
    "SYSTEM_PROMPT",
]
