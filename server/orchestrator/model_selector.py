"""Model selection policy for the 4-agent pipeline (E08_S05).

Pure-lookup function that maps ``(RouteTag, TurnType)`` pairs to
Anthropic model IDs. The single source of truth for model selection
in the orchestrator — no model ID strings appear elsewhere in
``server/`` (per AC #4 and the verifier-pass-removal decision).

**Model policy (v1):**

- **Claude Haiku 4.5** (``"claude-haiku-4-5"``): default model for
  ALL retrieval turns and ALL draft turns across every agent role.
  Cheapest tier; appropriate for short, retrieval-heavy turns where
  the model's job is to plan tool calls and synthesize retrieved
  evidence.
- **Claude Sonnet 4.6** (``"claude-sonnet-4-6"``): used ONLY for the
  Autoformalizer's Lean-syntax write step — the single turn that
  produces the final Lean 4 output. Sonnet's higher quality is
  load-bearing for syntactic correctness; Haiku's lower-quality
  Lean output would fail the kernel check more often, costing
  more in retries than the Sonnet upgrade saves.
- **Claude Opus 4.7**: NOT used in v1. The 35% tokenizer expansion
  relative to Sonnet 4.6 makes Opus economically nonviable for the
  retrieval-heavy 4-agent pipeline. Per AC #4 the Opus API ID
  string MUST NOT appear anywhere in ``server/`` source — not
  even as a deferred constant or comment. The deferral rationale
  lives in ``docs/model-policy.md``.

**Verifier pass DROPPED.** The v1 design had a dedicated Verification
agent that re-read retrieved chunks to validate proof steps. That
pass is eliminated (closes H10 in the roadmap). The argument: the
verifier reads from the same MCP corpus as the other agents — a
misranked or irrelevant retrieved chunk fools BOTH the upstream
agent and the verifier identically. The correct mathematical
critic is the Lean kernel, which is independent of the retrieval
corpus AND formally sound. Queries the router classifies as
``RouteTag.VERIFICATION`` are routed at dispatch time to the
Autoformalizer execution path; this module makes that explicit
by returning the same model IDs for ``VERIFICATION`` and
``AUTOFORMALIZATION``.

The ``RouteTag.VERIFICATION`` value remains in the router
(``server/router.py``) and the ``ROLE_PREFIXES`` map
(``server/prompts.py``) for query classification + BP1 byte-identity;
the dispatch redirection happens here, not in the router or the
prompts.

**Rationale and per-query token-budget estimates** live in
``docs/model-policy.md``.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from server.router import RouteTag

# ---------------------------------------------------------------------------
# Model ID constants
# ---------------------------------------------------------------------------

#: Claude Haiku 4.5 — the v1 default model for retrieval and draft
#: turns. The string is the ANTHROPIC API ALIAS form
#: (``claude-haiku-4-5``). The pinned snapshot ID is
#: ``claude-haiku-4-5-20251001`` per Anthropic's models overview as
#: of 2026-05; we use the alias here to match the AC text and the
#: project's E14 metric-label convention. If a future deployment
#: needs to pin the snapshot date (for reproducibility of evals),
#: bump this constant to the dated form AND update the AC test.
MODEL_HAIKU_4_5: str = "claude-haiku-4-5"

#: Claude Sonnet 4.6 — used ONLY for the Autoformalizer's
#: ``LEAN_WRITE`` turn. Per Anthropic's "dateless format that is
#: also a pinned snapshot" convention starting with Claude 4.6,
#: this string is BOTH the alias and the pinned snapshot.
MODEL_SONNET_4_6: str = "claude-sonnet-4-6"

# NOTE: by AC #4, the Opus API ID string MUST NOT appear anywhere
# in server/ source files. Do not add a "MODEL_OPUS_*" constant
# here, even as a DEFERRED marker, until v2 of the model policy.
# The rationale for Opus's exclusion lives in docs/model-policy.md.


# ---------------------------------------------------------------------------
# TurnType enum
# ---------------------------------------------------------------------------


class TurnType(StrEnum):
    """The three turn kinds the orchestrator dispatches.

    A turn is a single Anthropic Messages API call. The orchestrator
    composes a turn from the role prefix, the system prompt, the
    accumulated message history, and the available tools, then issues
    the call and consumes the response.

    The three values:

    - ``RETRIEVAL`` — the agent is calling tools (``search_papers``,
      ``get_chunk``, ``find_equation``, etc.) to materialize evidence.
      Always Haiku.
    - ``DRAFT`` — the agent is producing intermediate prose
      (analysis, planning, context assembly). Always Haiku.
    - ``LEAN_WRITE`` — the Autoformalizer's terminal turn that
      produces the final Lean 4 output. Sonnet.

    Closed at three for v1. A fourth turn type would require
    extending the lookup table in :data:`_SELECTION_TABLE` AND
    updating the import-time invariant assertion below.
    """

    RETRIEVAL = "RETRIEVAL"
    DRAFT = "DRAFT"
    LEAN_WRITE = "LEAN_WRITE"


# ---------------------------------------------------------------------------
# Selection table — the single source of truth
# ---------------------------------------------------------------------------

#: The 12-cell selection table (4 RouteTags × 3 TurnTypes). The
#: table is TOTAL: every (RouteTag, TurnType) pair is present.
#: Adding a new RouteTag or TurnType without extending this table
#: trips the import-time invariant (closed-at-N) below.
#:
#: The table encodes the model policy:
#: - LEAN_WRITE → Sonnet for Autoformalizer AND for Verification
#:   (Verification queries route to Autoformalizer execution).
#: - All other (role × turn type) combinations → Haiku.
#:
#: Rationale: the Lean-syntax write is the single turn whose output
#: is mechanically validated by the Lean kernel. Sonnet's higher
#: quality reduces kernel-rejection retries, paying for itself.
#: Every other turn does prose / tool-orchestration work where Haiku
#: is sufficient.
_SELECTION_TABLE: Mapping[tuple[RouteTag, TurnType], str] = MappingProxyType({
    # LOOKUP role — all turns Haiku.
    (RouteTag.LOOKUP, TurnType.RETRIEVAL): MODEL_HAIKU_4_5,
    (RouteTag.LOOKUP, TurnType.DRAFT): MODEL_HAIKU_4_5,
    (RouteTag.LOOKUP, TurnType.LEAN_WRITE): MODEL_HAIKU_4_5,
    # SYNTHESIS role — all turns Haiku.
    (RouteTag.SYNTHESIS, TurnType.RETRIEVAL): MODEL_HAIKU_4_5,
    (RouteTag.SYNTHESIS, TurnType.DRAFT): MODEL_HAIKU_4_5,
    (RouteTag.SYNTHESIS, TurnType.LEAN_WRITE): MODEL_HAIKU_4_5,
    # VERIFICATION role — routed to Autoformalizer execution at
    # dispatch time. Mirrors AUTOFORMALIZATION exactly.
    (RouteTag.VERIFICATION, TurnType.RETRIEVAL): MODEL_HAIKU_4_5,
    (RouteTag.VERIFICATION, TurnType.DRAFT): MODEL_HAIKU_4_5,
    (RouteTag.VERIFICATION, TurnType.LEAN_WRITE): MODEL_SONNET_4_6,
    # AUTOFORMALIZATION role — Haiku for retrieval/draft; Sonnet
    # for the terminal Lean-write turn.
    (RouteTag.AUTOFORMALIZATION, TurnType.RETRIEVAL): MODEL_HAIKU_4_5,
    (RouteTag.AUTOFORMALIZATION, TurnType.DRAFT): MODEL_HAIKU_4_5,
    (RouteTag.AUTOFORMALIZATION, TurnType.LEAN_WRITE): MODEL_SONNET_4_6,
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def select_model(route_tag: RouteTag, turn_type: TurnType) -> str:
    """Return the Anthropic model ID for a ``(route_tag, turn_type)``
    pair.

    Pure-function lookup over :data:`_SELECTION_TABLE`. The table is
    total — every legitimate ``(RouteTag, TurnType)`` combination has
    an entry. An unknown pair raises ``ValueError`` (defensive: a
    silent fallback to Haiku would mask a future enum extension that
    forgot to update the table).

    The model IDs are the dateless / aliased forms documented in the
    module docstring. This function is the SINGLE SOURCE OF TRUTH
    for model selection in the orchestrator; no model ID strings
    appear elsewhere in ``server/``.

    Examples
    --------
    >>> select_model(RouteTag.AUTOFORMALIZATION, TurnType.LEAN_WRITE)
    'claude-sonnet-4-6'
    >>> select_model(RouteTag.SYNTHESIS, TurnType.RETRIEVAL)
    'claude-haiku-4-5'
    >>> # Verification routes to Autoformalizer execution → same models.
    >>> select_model(RouteTag.VERIFICATION, TurnType.DRAFT)
    'claude-haiku-4-5'
    """
    try:
        return _SELECTION_TABLE[(route_tag, turn_type)]
    except KeyError:
        raise ValueError(
            f"No model selected for (route_tag={route_tag!r}, "
            f"turn_type={turn_type!r}). The selection table is "
            f"closed at 4 RouteTags × 3 TurnTypes; adding a new "
            f"value to either enum requires extending "
            f"server.orchestrator.model_selector._SELECTION_TABLE "
            f"in lockstep."
        ) from None


# ---------------------------------------------------------------------------
# Import-time invariants — closed-at-(4 routes × 3 turn types)
# ---------------------------------------------------------------------------

# Mirrors the F4-fix discipline from server/prompts.py: use
# ``if … raise RuntimeError(…)`` rather than a bare ``assert`` so
# the check survives ``python -O`` (which strips assert statements).
# The invariant: the selection table covers every (RouteTag, TurnType)
# cross-product. Adding a new value to either enum without extending
# the table is caught at import.

_expected_keys = {
    (route_tag, turn_type)
    for route_tag in RouteTag
    for turn_type in TurnType
}
_actual_keys = set(_SELECTION_TABLE.keys())
if _actual_keys != _expected_keys:
    missing = _expected_keys - _actual_keys
    extra = _actual_keys - _expected_keys
    raise RuntimeError(
        f"_SELECTION_TABLE keys diverge from RouteTag × TurnType "
        f"cross-product. missing={sorted(missing)!r}, "
        f"extra={sorted(extra)!r}. Adding a new RouteTag or TurnType "
        f"value requires extending _SELECTION_TABLE in lockstep."
    )

# Belt-and-suspenders: the values must be one of the two exported
# model IDs (no surprise model strings sneaking in via a typo).
_valid_models = frozenset({MODEL_HAIKU_4_5, MODEL_SONNET_4_6})
_actual_values = set(_SELECTION_TABLE.values())
if not _actual_values.issubset(_valid_models):
    raise RuntimeError(
        f"_SELECTION_TABLE references model IDs not in the v1 "
        f"policy. extra={sorted(_actual_values - _valid_models)!r}. "
        f"Allowed: {sorted(_valid_models)!r}. Per AC #4, the Opus "
        f"API ID MUST NOT appear in server/."
    )


__all__ = [
    "MODEL_HAIKU_4_5",
    "MODEL_SONNET_4_6",
    "TurnType",
    "select_model",
]
