"""Hosted-model API spend tracking (E14_S12).

Cost constants + Prometheus metric registration for the optional
hosted-model paths (Voyage AI embedder via ``ARXMCP_QUERY_EMBED_PROVIDER=
voyage``; Anthropic Haiku summarizer if E08_S07 ships). Per-call cost
constants are *manual* — there is no automated pricing API. Update
them when pricing changes; the ``LAST_VERIFIED`` field at the bottom
of this docstring is the operator-visible currency marker. The
quarterly restore drill cadence (per
:doc:`.claude/notes/08-security-observability-ops.md`) doubles as the
manual pricing review cadence.

The metric family is
``arxmcp_api_spend_usd_total{provider, model, agent_role}`` (3 labels
per the milestone brief). Label cardinality is bounded:

- ``provider`` in ``{"voyage", "anthropic"}``
- ``model`` is the Anthropic model ID (imported from
  :mod:`server.orchestrator.model_selector` — the single source of
  truth per the E08_S05 critique F2 fix) plus Voyage model name
  strings (Voyage is not in the orchestrator model selector since
  it's an embedder, not an LLM call site)
- ``agent_role`` in :data:`server.observability.tracing.VALID_AGENT_ROLES`
  plus ``"unknown"`` for the no-header case

Maximum 2 × 2 × 5 = 20 label combinations — safe under Prometheus
best practices.

The ``agent_role`` label reads from the ``current_agent_role``
ContextVar (populated by ``TracingContextMiddleware`` from the
``Arxmcp-Agent-Role`` HTTP request header) — NOT from a JSON-Schema
tool argument (per
:doc:`.claude/notes/08-security-observability-ops.md` §Tracing:
"NOT a JSON-Schema property — keeps TOOL_SCHEMA_VERSION pinned at 6").

Pricing sources:

- Voyage AI ``voyage-3``: https://docs.voyageai.com/pricing
- Anthropic Haiku 4.5: https://www.anthropic.com/pricing

LAST_VERIFIED: 2026-05-22
"""

from __future__ import annotations

from prometheus_client import Counter

# Single source of truth for the Anthropic Haiku model ID (E08_S05 F2
# fix — never hardcode model IDs outside server/orchestrator/
# model_selector.py).
from server.orchestrator.model_selector import MODEL_HAIKU_4_5

# ---------------------------------------------------------------------------
# Cost constants (USD per million tokens) — UPDATE when pricing changes
# ---------------------------------------------------------------------------

#: Voyage AI embedding model name. Voyage is NOT in the orchestrator
#: model_selector (that module is for the orchestrator's LLM calls;
#: Voyage is an embedder). Hardcoded here as the single mention site
#: for the Voyage model identifier.
VOYAGE_3_MODEL: str = "voyage-3"

#: Voyage AI ``voyage-3`` embedding model — input tokens only
#: (embeddings have no output tokens). Source:
#: https://docs.voyageai.com/pricing as of 2026-05-22.
VOYAGE_3_USD_PER_M_TOKENS: float = 0.06

#: Anthropic Claude Haiku 4.5 — input tokens. Source:
#: https://www.anthropic.com/pricing as of 2026-05-22.
CLAUDE_HAIKU_4_5_INPUT_USD_PER_M: float = 1.00

#: Anthropic Claude Haiku 4.5 — output tokens. Source:
#: https://www.anthropic.com/pricing as of 2026-05-22.
CLAUDE_HAIKU_4_5_OUTPUT_USD_PER_M: float = 5.00

#: ISO-8601 date the constants above were last verified against
#: the upstream pricing pages. The quarterly restore drill cadence
#: doubles as the manual review trigger; operators should update
#: this date AND the constants together. The
#: ``tests/test_spend_constants.py::TestLastVerifiedFresh::test_last_verified_within_six_months``
#: regression guard (F3 closure from the m10 adversary critique)
#: fails CI when this date is > 180 days old, surfacing stale
#: constants automatically.
LAST_VERIFIED: str = "2026-05-22"

#: Sanity ceiling — no provider's per-million-token cost should
#: exceed this. Used by the value-sanity tests to catch a typo
#: like ``100.0`` where ``1.00`` was intended.
PRICE_PER_M_USD_CEILING: float = 100.0


# ---------------------------------------------------------------------------
# Prometheus metric registration
# ---------------------------------------------------------------------------


#: Cumulative API spend in USD across all hosted-model paths.
#: Incremented by :func:`record_spend` from the call site that
#: completes a hosted-model API call. Counter monotonicity is
#: satisfied because API spend is always positive.
#:
#: Labels (3, all bounded):
#:
#: - ``provider`` — one of ``"voyage"``, ``"anthropic"``.
#: - ``model`` — concrete model name (the Voyage embedder ID from
#:   :data:`VOYAGE_3_MODEL`, or the Anthropic Haiku ID imported
#:   from :data:`server.orchestrator.model_selector.MODEL_HAIKU_4_5`).
#: - ``agent_role`` — one of
#:   :data:`server.observability.tracing.VALID_AGENT_ROLES`
#:   (``"sketcher" | "autoformalizer" | "tactician" | "fixer"``)
#:   or ``"unknown"`` when the ``Arxmcp-Agent-Role`` header was
#:   absent.
#:
#: The daily metrics report (E14_S04) surfaces top spend categories
#: by ``sum by (provider, model) (arxmcp_api_spend_usd_total)``.
API_SPEND_USD_TOTAL: Counter = Counter(
    "arxmcp_api_spend_usd_total",
    "Cumulative API spend in USD across hosted-model paths. "
    "Labels: provider (voyage/anthropic), model (specific name), "
    "agent_role (the calling agent's role from "
    "Arxmcp-Agent-Role header, or 'unknown'). Increment lives at "
    "the call site that completes the hosted-model API call.",
    labelnames=["provider", "model", "agent_role"],
)


# ---------------------------------------------------------------------------
# Recording helper
# ---------------------------------------------------------------------------


def _resolve_agent_role() -> str:
    """Return the validated agent_role label value.

    Reads :data:`server.observability.tracing.current_agent_role`
    ContextVar (populated by ``TracingContextMiddleware`` from the
    ``Arxmcp-Agent-Role`` request header). Returns ``"unknown"``
    when the header was absent — keeps the label space bounded
    rather than producing a None-stringified value.

    The middleware already validates against
    :data:`server.observability.tracing.VALID_AGENT_ROLES`; if a
    foreign value somehow lands in the ContextVar (defensive
    against future middleware changes), we coerce to ``"unknown"``
    here too — protects the label cardinality contract regardless
    of upstream validation drift.
    """
    # Local import avoids a circular import at module load time
    # (tracing.py uses prometheus_client too).
    from server.observability.tracing import (
        VALID_AGENT_ROLES,
        current_agent_role,
    )

    role = current_agent_role.get()
    if role is None or role not in VALID_AGENT_ROLES:
        return "unknown"
    return role


def record_spend(
    *,
    provider: str,
    model: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> float:
    """Compute USD spend for a completed hosted-model call and increment
    the ``arxmcp_api_spend_usd_total`` counter.

    Call this from the SUCCESS branch of the hosted-model call site
    (per :doc:`.claude/notes/milestones/E14_Tier5plus/research-synthesis.md`
    §D2 — counting attempted-but-failed calls as spend systematically
    over-reports). The function returns the computed USD amount so
    callers can also log it.

    Parameters
    ----------
    provider : str
        ``"voyage"`` or ``"anthropic"``. Other values are rejected
        with ``RuntimeError`` to keep the label space bounded.
    model : str
        Concrete model identifier — pass :data:`VOYAGE_3_MODEL` for
        Voyage, or the Anthropic model ID from
        :data:`server.orchestrator.model_selector.MODEL_HAIKU_4_5`.
        Used both for the metric label and to pick the cost constants.
    tokens_in : int, default 0
        Input-token count for the call.
    tokens_out : int, default 0
        Output-token count for the call. Unused for embedding models
        (no output tokens).

    Returns
    -------
    float
        USD amount that was added to the counter (sum of input +
        output cost). Always non-negative.

    Raises
    ------
    RuntimeError
        On unknown ``provider`` / ``model`` combination, or on negative
        token counts. (``assert`` is project-banned per CLAUDE.md §4.7.)
    """
    if tokens_in < 0 or tokens_out < 0:
        raise RuntimeError(
            f"record_spend: token counts must be non-negative; got "
            f"tokens_in={tokens_in}, tokens_out={tokens_out}"
        )

    usd_amount: float = 0.0
    if provider == "voyage" and model == VOYAGE_3_MODEL:
        # Embeddings have no output tokens; tokens_out is ignored.
        usd_amount = tokens_in / 1_000_000 * VOYAGE_3_USD_PER_M_TOKENS
    elif provider == "anthropic" and model == MODEL_HAIKU_4_5:
        usd_amount = (
            tokens_in / 1_000_000 * CLAUDE_HAIKU_4_5_INPUT_USD_PER_M
            + tokens_out / 1_000_000 * CLAUDE_HAIKU_4_5_OUTPUT_USD_PER_M
        )
    else:
        raise RuntimeError(
            f"record_spend: unknown (provider, model) combination "
            f"({provider!r}, {model!r}). Add cost constants for new "
            f"models in server/observability/spend_constants.py first."
        )

    agent_role = _resolve_agent_role()
    API_SPEND_USD_TOTAL.labels(
        provider=provider, model=model, agent_role=agent_role,
    ).inc(usd_amount)
    return usd_amount


__all__ = [
    "API_SPEND_USD_TOTAL",
    "CLAUDE_HAIKU_4_5_INPUT_USD_PER_M",
    "CLAUDE_HAIKU_4_5_OUTPUT_USD_PER_M",
    "LAST_VERIFIED",
    "PRICE_PER_M_USD_CEILING",
    "VOYAGE_3_MODEL",
    "VOYAGE_3_USD_PER_M_TOKENS",
    "record_spend",
]
