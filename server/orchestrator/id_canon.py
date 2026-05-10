"""Tool-use ID canonicalization for prompt-cache stability (E08_S04).

The Anthropic Messages API assigns server-side **non-deterministic**
``id`` fields to ``tool_use`` content blocks (e.g.,
``"toolu_01AbcXyz..."``) and the matching ``tool_use_id`` field on
``tool_result`` blocks that reference them. These IDs are not
reproducible across API calls — even an identical request issued
twice gets two different IDs.

For a single agent in isolation, the IDs are irrelevant; the agent
only needs them to pair its own tool_use with its own tool_result.
But in the project's 4-agent fan-out, the orchestrator composes one
agent's tool-call history into another agent's prompt context. If
agent A's first tool call has ID ``toulu_01Abc...`` and we splice
that exact byte sequence into agent B's prompt prefix, then agent B
gets a unique-to-agent-A prefix and its prompt cache misses. The
prompt cache key is the byte hash of the prefix; even a single
non-deterministic byte invalidates it.

**The fix** is to rewrite every tool-use ID to a deterministic
counter-based form before composing into the next agent's context.
The canonical format is ``"toolu_{counter:08d}"`` where ``counter``
is a per-call monotonically increasing integer reset to 0 at the
start of every :func:`canonicalize_turn` invocation. The function
returns a deep copy of the input — the original list is preserved.

**Why this is "the single most underrated optimization in agentic
pipelines"** (per ``.claude/notes/07-multi-agent-caching.md`` line
117): without canonicalization, a 4-agent fan-out with even one
shared tool call invalidates 3 of the 4 cached prefixes — so cache
hit rate drops from ~95% to ~25% on the cross-agent slot. With
canonicalization, the cross-agent prefix matches byte-for-byte and
the cache reuses correctly.

**Idempotency contract.** Applying ``canonicalize_turn`` twice
produces the same output as applying it once. This holds because
the canonical IDs (``toolu_00000000``, ``toolu_00000001``, ...) are
themselves valid inputs — the second pass sees them in the same
order, assigns them to the same counter, and rewrites them to the
same canonical form (a no-op).

**Design source**: the reference pseudocode at
``.claude/notes/07-multi-agent-caching.md`` lines 98–113 mutates the
input in place. We deviate by returning a deep copy so the caller's
original list is preserved (footgun-avoidance per the E08_S04
research synthesis D2).
"""

from __future__ import annotations

import copy
import re
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Block types whose IDs we rewrite. Per the Anthropic Messages API,
#: ``tool_use`` blocks carry an ``id`` field; ``tool_result`` blocks
#: carry a ``tool_use_id`` field that references the matching
#: ``tool_use``. Both are server-issued and non-deterministic.
ID_CARRYING_BLOCK_TYPES: frozenset[str] = frozenset({"tool_use", "tool_result"})

#: Format for the canonical ID. The 8-digit zero-padded form is large
#: enough for any realistic per-session call count (10^8) and is
#: pinned by the brief: *"replaces non-deterministic IDs with
#: ``toolu_00000000``, ``toolu_00000001``, etc."*
CANONICAL_ID_FORMAT: str = "toolu_{counter:08d}"

#: Regex that matches an already-canonical ID. Used by the
#: idempotency check inside ``canonicalize_turn`` so the second pass
#: produces the same output as the first (the canonical IDs map to
#: themselves in the same order).
_CANONICAL_ID_RE: re.Pattern[str] = re.compile(r"^toolu_\d{8}$")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def canonicalize_turn(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rewrite every ``tool_use`` ``id`` and matching ``tool_use_id``
    to a deterministic counter-based form.

    The input is a list of Anthropic Messages-API ``messages`` dicts.
    Each message has ``role`` and ``content``; ``content`` is a list
    of content blocks. This function walks every block whose ``type``
    is in :data:`ID_CARRYING_BLOCK_TYPES`, builds a per-call
    ``{old_id: new_id}`` mapping in encounter order, and returns a
    deep copy of the input with IDs rewritten.

    .. warning::

        **The orchestrator MUST call this function over the WHOLE
        accumulated message history each time, NOT over only the
        newly-added messages.** F1 fix from the E08_S04 critique:
        the counter is per-call (resets on every invocation). This
        is consistent with the brief's "per-session monotonically
        increasing" wording IF AND ONLY IF every call sees the
        full history, so the same accumulated list produces the
        same canonical IDs deterministically.

        ❌ WRONG (introduces ID collisions across transitions)::

            # Transition 1
            ctx = canonicalize_turn([turn_a])
            # Transition 2 — caller appends turn_b RAW, then calls:
            ctx.append(turn_b)
            ctx_partial = canonicalize_turn([turn_b])  # ← only new turn
            # turn_b's tool_use_id collides with turn_a's id!

        ✅ RIGHT (passes full accumulated history each time)::

            # Transition 1
            ctx = canonicalize_turn(history + [turn_a])
            # Transition 2 — pass the FULL accumulated history:
            ctx = canonicalize_turn(ctx + [turn_b])
            # turn_a's IDs are preserved; turn_b's IDs are
            # appended to the same counter sequence.

        The idempotency property is what makes the "full history"
        pattern safe: re-canonicalizing already-canonical IDs is a
        no-op, so passing the full history each call costs only the
        deep-copy work, not extra ID renumbering.

    Parameters
    ----------
    messages : list[dict]
        The Anthropic Messages-API conversation history. NOT
        mutated; a deep copy is returned. MUST be the FULL
        accumulated history (see warning above). MUST be a ``list``
        — passing ``tuple`` or other sequence types raises
        ``TypeError`` (F10 fix from the E08_S04 critique).

    Returns
    -------
    list[dict]
        A NEW list (deep copy of ``messages``) with every
        ``tool_use.id`` and ``tool_result.tool_use_id`` rewritten
        to ``"toolu_{counter:08d}"`` form. The mapping is
        positional — the first encountered ID becomes
        ``"toolu_00000000"``, the second becomes
        ``"toolu_00000001"``, and so on.

    Raises
    ------
    TypeError
        If ``messages`` is not a ``list``. The function's contract
        is documented as ``list[dict]`` and the deep-copy preserves
        type — passing a tuple would silently return a tuple,
        violating the type contract.

    Notes
    -----
    **Idempotency.** Applying ``canonicalize_turn`` twice produces
    the same output as applying it once. The canonical form of an
    already-canonical ID is itself (the second pass sees the same
    IDs in the same order and maps them to the same counter values).

    **Mutation discipline.** The input list is NOT mutated. The
    function returns a deep copy. This deviates from the reference
    pseudocode in ``.claude/notes/07-multi-agent-caching.md`` which
    mutates in place — we trade a deep-copy cost for footgun-
    avoidance (per E08_S04 research synthesis D2).

    **Pairing invariant.** A ``tool_use`` block with id ``X`` and a
    later ``tool_result`` block with ``tool_use_id`` ``X`` are paired.
    Both rewrite to the same canonical id ``Y`` because the
    ``id_map`` is keyed by the original id string and reused for
    every subsequent reference. This preserves the API-required
    pairing invariant.

    **Block with both ``id`` and ``tool_use_id``.** F4 fix from the
    E08_S04 critique: when a block has BOTH fields (atypical /
    malformed input), each field is mapped independently — the
    ``id`` value gets one canonical id; the ``tool_use_id`` value
    gets another. The pre-fix version short-circuited via
    ``or`` and silently rewrote ``tool_use_id`` to the canonical
    of ``id``, destroying the pairing for any later reference to
    the original ``tool_use_id``.

    **Robustness.** Blocks without an id (malformed input) are left
    untouched. Blocks with a type outside
    :data:`ID_CARRYING_BLOCK_TYPES` are left untouched. Messages
    without a ``content`` field are skipped. The function never
    raises on input shape (only on the strict ``list`` type check
    above); it produces a best-effort canonicalized copy.

    Examples
    --------
    >>> messages = [
    ...     {"role": "assistant", "content": [
    ...         {"type": "tool_use", "id": "toolu_01Abc",
    ...          "name": "search_papers", "input": {}},
    ...     ]},
    ...     {"role": "user", "content": [
    ...         {"type": "tool_result", "tool_use_id": "toolu_01Abc",
    ...          "content": "..."},
    ...     ]},
    ... ]
    >>> result = canonicalize_turn(messages)
    >>> result[0]["content"][0]["id"]
    'toolu_00000000'
    >>> result[1]["content"][0]["tool_use_id"]
    'toolu_00000000'
    >>> # Idempotent — second pass is a no-op:
    >>> canonicalize_turn(result) == result
    True
    """
    # F10 fix from the E08_S04 critique: strict type check. The
    # function's contract is ``list[dict]``; a tuple input would
    # silently return a tuple via copy.deepcopy, violating the
    # documented return type.
    if not isinstance(messages, list):
        raise TypeError(
            f"canonicalize_turn requires a list[dict] input; got "
            f"{type(messages).__name__}. Wrap as ``list(messages)`` "
            f"if the caller has a different sequence type."
        )

    # Deep copy so the caller's original list is preserved.
    canonicalized = copy.deepcopy(messages)

    counter = 0
    id_map: dict[str, str] = {}

    def _canonicalize(old_id: str) -> str:
        """Look up or assign the canonical form for ``old_id``.

        Closure over ``counter`` / ``id_map`` so a single helper
        serves both ``id`` and ``tool_use_id`` rewrites without
        risking the pre-F4 bug where one field's value was used
        for the other field's mapping."""
        nonlocal counter
        if old_id not in id_map:
            id_map[old_id] = CANONICAL_ID_FORMAT.format(counter=counter)
            counter += 1
        return id_map[old_id]

    for msg in canonicalized:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") not in ID_CARRYING_BLOCK_TYPES:
                continue

            # F4 fix from the E08_S04 critique: handle ``id`` and
            # ``tool_use_id`` INDEPENDENTLY. The pre-fix code did
            # ``old_id = block.get("id") or block.get("tool_use_id")``
            # which short-circuited — when both fields are present
            # (atypical malformed input), only ``id`` was mapped
            # AND ``tool_use_id`` was silently rewritten to that
            # same canonical id, destroying the pairing for any
            # later reference to the original ``tool_use_id``.
            #
            # We now map each field separately. A block normally
            # only carries one of the two (``tool_use`` blocks
            # carry ``id``; ``tool_result`` blocks carry
            # ``tool_use_id``); the two-field case is preserved
            # losslessly by mapping each independently.
            if "id" in block and block["id"] is not None:
                block["id"] = _canonicalize(block["id"])
            if "tool_use_id" in block and block["tool_use_id"] is not None:
                block["tool_use_id"] = _canonicalize(block["tool_use_id"])

    return canonicalized


def is_canonical_id(value: str) -> bool:
    """Return True if ``value`` matches the canonical ID format
    ``"toolu_########"`` (eight digits).

    Provided as a public helper so downstream tests / orchestrators
    can assert post-canonicalization invariants without re-encoding
    the regex."""
    return bool(_CANONICAL_ID_RE.match(value))


__all__ = [
    "CANONICAL_ID_FORMAT",
    "ID_CARRYING_BLOCK_TYPES",
    "canonicalize_turn",
    "is_canonical_id",
]
