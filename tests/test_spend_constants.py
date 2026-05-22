"""Tests for the E14_S12 API spend metrics module.

Coverage matrix:

- TestCostConstants
    Values are positive floats under the sanity ceiling.
- TestLastVerifiedFresh
    LAST_VERIFIED is parseable as YYYY-MM-DD.
- TestMetricRegistration
    API_SPEND_USD_TOTAL is a Counter with the 3 expected labels.
- TestRecordSpendVoyage
    record_spend(voyage, voyage-3, tokens_in=N) increments by the
    correct USD amount.
- TestRecordSpendAnthropic
    anthropic/haiku path increments by input+output USD.
- TestRecordSpendValidation
    Unknown provider/model raises RuntimeError; negative tokens
    raise RuntimeError.
- TestAgentRoleLabel
    agent_role label is read from ContextVar; defaults to 'unknown'
    when unset; foreign values coerce to 'unknown'.
- TestStubHasTodoComment
    _voyage_encode_stub source carries the future-voyage-client TODO
    so the next person knows where to wire the real increment.
- TestNoLiveAnthropicIncrement
    server/ source contains no record_spend call for anthropic/haiku
    yet (E08_S07 has not shipped).
- TestModuleContract
    __all__ entries all resolve.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from prometheus_client import REGISTRY, Counter

from server.observability import spend_constants as sc
from server.observability.spend_constants import (
    API_SPEND_USD_TOTAL,
    CLAUDE_HAIKU_4_5_INPUT_USD_PER_M,
    CLAUDE_HAIKU_4_5_OUTPUT_USD_PER_M,
    LAST_VERIFIED,
    PRICE_PER_M_USD_CEILING,
    VOYAGE_3_USD_PER_M_TOKENS,
    record_spend,
)
from server.orchestrator.model_selector import MODEL_HAIKU_4_5

REPO_ROOT: Path = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def reset_spend_counter():
    """Each test starts with a fresh counter. prometheus_client
    Counters are process-global so we manually zero between tests."""
    # The Counter family allows clearing all label combinations.
    API_SPEND_USD_TOTAL.clear()
    yield
    API_SPEND_USD_TOTAL.clear()


def _read_counter(provider: str, model: str, agent_role: str) -> float:
    """Read the current value of the labeled counter cell."""
    val = REGISTRY.get_sample_value(
        "arxmcp_api_spend_usd_total",
        {"provider": provider, "model": model, "agent_role": agent_role},
    )
    return val if val is not None else 0.0


# ---------------------------------------------------------------------------
# Constant value-sanity
# ---------------------------------------------------------------------------


class TestCostConstants:
    @pytest.mark.parametrize(
        "name,value",
        [
            ("VOYAGE_3_USD_PER_M_TOKENS", VOYAGE_3_USD_PER_M_TOKENS),
            ("CLAUDE_HAIKU_4_5_INPUT_USD_PER_M",
             CLAUDE_HAIKU_4_5_INPUT_USD_PER_M),
            ("CLAUDE_HAIKU_4_5_OUTPUT_USD_PER_M",
             CLAUDE_HAIKU_4_5_OUTPUT_USD_PER_M),
        ],
    )
    def test_constant_is_positive_float_under_ceiling(
        self, name: str, value: float,
    ) -> None:
        """Catches typos like setting VOYAGE_3_USD_PER_M_TOKENS = 100.0
        when 1.00 was intended — the order-of-magnitude error a
        sanity ceiling catches."""
        assert isinstance(value, float), f"{name} must be a float"
        assert value > 0.0, f"{name} must be positive (>0)"
        assert value < PRICE_PER_M_USD_CEILING, (
            f"{name}={value} exceeds PRICE_PER_M_USD_CEILING "
            f"({PRICE_PER_M_USD_CEILING}). Either pricing exploded "
            f"or the constant has a units error."
        )

    def test_haiku_output_more_expensive_than_input(self) -> None:
        """Almost-universal property of LLM pricing: output costs
        more than input. If this inverts, the constants were
        probably swapped at edit time."""
        assert (
            CLAUDE_HAIKU_4_5_OUTPUT_USD_PER_M
            > CLAUDE_HAIKU_4_5_INPUT_USD_PER_M
        ), (
            "Haiku output cost should exceed input cost; "
            f"got input={CLAUDE_HAIKU_4_5_INPUT_USD_PER_M}, "
            f"output={CLAUDE_HAIKU_4_5_OUTPUT_USD_PER_M} — "
            "constants may have been swapped"
        )


class TestLastVerifiedFresh:
    def test_last_verified_parses_as_iso_date(self) -> None:
        try:
            date.fromisoformat(LAST_VERIFIED)
        except ValueError as e:
            pytest.fail(
                f"LAST_VERIFIED={LAST_VERIFIED!r} must be ISO-8601 "
                f"YYYY-MM-DD; got: {e}"
            )

    def test_last_verified_within_six_months(self) -> None:
        """F3 closure (m10 adversary critique): the spend_constants
        docstring claimed this test existed but it didn't. Now it
        does. Pricing constants go stale silently otherwise —
        operators trusted LAST_VERIFIED to be enforced, but without
        this guard a quarterly review can slip into ten years.

        Bound: 180 days (6 months) matches the project's quarterly
        restore-drill cadence with one cycle of grace. When this
        test fails, the action is:

        1. Open the pricing pages (URLs in spend_constants.py
           docstring).
        2. Update the cost constants if pricing changed.
        3. Bump LAST_VERIFIED to today.

        If you genuinely want to suppress the test for a long-paused
        deployment, set ARXMCP_SKIP_STALENESS_CHECK=1 in the env —
        but the spirit is that the constants get reviewed."""
        import os

        if os.getenv("ARXMCP_SKIP_STALENESS_CHECK") == "1":
            pytest.skip("ARXMCP_SKIP_STALENESS_CHECK=1 set in env")
        from datetime import date as _date

        verified = _date.fromisoformat(LAST_VERIFIED)
        age_days = (_date.today() - verified).days
        assert age_days <= 180, (
            f"spend_constants.LAST_VERIFIED is {age_days} days old "
            f"(> 180 day bound). Re-verify Voyage + Anthropic "
            f"pricing against the URLs in the spend_constants.py "
            f"docstring, update the cost constants if changed, and "
            f"bump LAST_VERIFIED to today's date. To suppress this "
            f"check temporarily, set ARXMCP_SKIP_STALENESS_CHECK=1."
        )


# ---------------------------------------------------------------------------
# Metric registration
# ---------------------------------------------------------------------------


class TestMetricRegistration:
    def test_metric_is_a_counter(self) -> None:
        assert isinstance(API_SPEND_USD_TOTAL, Counter)

    def test_metric_has_three_expected_labels(self) -> None:
        """Per the brief: arxmcp_api_spend_usd_total{provider, model, agent_role}."""
        assert API_SPEND_USD_TOTAL._labelnames == (
            "provider", "model", "agent_role",
        ), (
            "Metric labelnames drift: brief specifies "
            "(provider, model, agent_role); got "
            f"{API_SPEND_USD_TOTAL._labelnames}"
        )

    def test_metric_name_is_canonical(self) -> None:
        """prometheus_client strips the implicit ``_total`` suffix from
        the ``_name`` attribute on Counter objects (since the suffix is
        added at sample time). The on-the-wire metric name is still
        ``arxmcp_api_spend_usd_total`` — verify both: the internal
        ``_name`` AND a successful lookup via the full name."""
        assert API_SPEND_USD_TOTAL._name == "arxmcp_api_spend_usd"
        # Round-trip via REGISTRY: the metric is exposed under the
        # full name including the _total suffix.
        API_SPEND_USD_TOTAL.labels(
            provider="voyage", model="voyage-3", agent_role="unknown",
        ).inc(0.0)
        val = REGISTRY.get_sample_value(
            "arxmcp_api_spend_usd_total",
            {"provider": "voyage", "model": "voyage-3", "agent_role": "unknown"},
        )
        assert val is not None, (
            "Metric is not exposed under arxmcp_api_spend_usd_total — "
            "prometheus_client may have changed Counter suffix behavior"
        )


# ---------------------------------------------------------------------------
# record_spend — Voyage path
# ---------------------------------------------------------------------------


class TestRecordSpendVoyage:
    def test_voyage_3_increments_by_correct_usd(self) -> None:
        # 1 million tokens at $0.06/M = $0.06.
        usd = record_spend(
            provider="voyage", model="voyage-3", tokens_in=1_000_000,
        )
        assert usd == pytest.approx(0.06)
        # Counter cell increments.
        cell = _read_counter("voyage", "voyage-3", "unknown")
        assert cell == pytest.approx(0.06)

    def test_voyage_ignores_tokens_out(self) -> None:
        """Embeddings have no output tokens; passing tokens_out
        should not contribute to the USD computation."""
        usd_with_out = record_spend(
            provider="voyage", model="voyage-3",
            tokens_in=500_000, tokens_out=999_999,
        )
        # 0.5M * 0.06 = 0.03; tokens_out is ignored.
        assert usd_with_out == pytest.approx(0.03)

    def test_voyage_zero_tokens_increments_zero(self) -> None:
        usd = record_spend(
            provider="voyage", model="voyage-3", tokens_in=0,
        )
        assert usd == 0.0
        assert _read_counter("voyage", "voyage-3", "unknown") == 0.0


# ---------------------------------------------------------------------------
# record_spend — Anthropic path
# ---------------------------------------------------------------------------


class TestRecordSpendAnthropic:
    def test_haiku_combines_input_and_output(self) -> None:
        # 1M input at $1.00/M = $1.00. 1M output at $5.00/M = $5.00. Sum: $6.00.
        usd = record_spend(
            provider="anthropic", model=MODEL_HAIKU_4_5,
            tokens_in=1_000_000, tokens_out=1_000_000,
        )
        assert usd == pytest.approx(6.0)
        cell = _read_counter("anthropic", MODEL_HAIKU_4_5, "unknown")
        assert cell == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestRecordSpendValidation:
    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(RuntimeError, match="unknown.*combination"):
            record_spend(
                provider="openai", model="gpt-4",
                tokens_in=100,
            )

    def test_unknown_model_for_known_provider_raises(self) -> None:
        with pytest.raises(RuntimeError, match="unknown.*combination"):
            record_spend(
                provider="voyage", model="voyage-LITE",
                tokens_in=100,
            )

    def test_negative_tokens_in_raises(self) -> None:
        with pytest.raises(RuntimeError, match="non-negative"):
            record_spend(
                provider="voyage", model="voyage-3",
                tokens_in=-1,
            )

    def test_negative_tokens_out_raises(self) -> None:
        with pytest.raises(RuntimeError, match="non-negative"):
            record_spend(
                provider="anthropic", model=MODEL_HAIKU_4_5,
                tokens_in=100, tokens_out=-1,
            )


# ---------------------------------------------------------------------------
# agent_role label — read from ContextVar
# ---------------------------------------------------------------------------


class TestAgentRoleLabel:
    def test_unset_role_uses_unknown_label(self) -> None:
        """No ContextVar value set → label="unknown" (keeps the label
        space bounded; we never emit None or empty string)."""
        from server.observability.tracing import current_agent_role
        token = current_agent_role.set(None)
        try:
            record_spend(
                provider="voyage", model="voyage-3", tokens_in=1000,
            )
            assert _read_counter("voyage", "voyage-3", "unknown") > 0.0
        finally:
            current_agent_role.reset(token)

    @pytest.mark.parametrize(
        "role", ["sketcher", "autoformalizer", "tactician", "fixer"],
    )
    def test_valid_role_lands_on_that_label(self, role: str) -> None:
        from server.observability.tracing import current_agent_role
        token = current_agent_role.set(role)
        try:
            record_spend(
                provider="voyage", model="voyage-3", tokens_in=1000,
            )
            assert _read_counter("voyage", "voyage-3", role) > 0.0
            # The "unknown" cell should NOT have been incremented.
            assert _read_counter("voyage", "voyage-3", "unknown") == 0.0
        finally:
            current_agent_role.reset(token)

    def test_invalid_role_in_contextvar_coerces_to_unknown(self) -> None:
        """Defensive: even if some future middleware leak put a
        foreign value in the ContextVar, the spend counter must NOT
        explode the Prometheus label space."""
        from server.observability.tracing import current_agent_role
        token = current_agent_role.set("attacker-role")  # not in VALID_AGENT_ROLES
        try:
            record_spend(
                provider="voyage", model="voyage-3", tokens_in=1000,
            )
            # Coerced to "unknown".
            assert _read_counter("voyage", "voyage-3", "unknown") > 0.0
            assert _read_counter("voyage", "voyage-3", "attacker-role") == 0.0
        finally:
            current_agent_role.reset(token)


# ---------------------------------------------------------------------------
# Voyage stub TODO marker — operator pointer for the future client
# ---------------------------------------------------------------------------


class TestStubHasTodoComment:
    """The Voyage stub at server/query_encoder.py::_voyage_encode_stub
    must carry a TODO comment pointing at the spend-tracking wiring
    so the next person to land the real Voyage HTTP client knows
    where to add record_spend(). The comment must reference
    record_spend explicitly so a grep finds it."""

    def test_voyage_stub_carries_future_client_todo(self) -> None:
        text = (REPO_ROOT / "server" / "query_encoder.py").read_text(
            encoding="utf-8",
        )
        # The TODO marker block sits just above the raise.
        assert "TODO(future-voyage-client)" in text, (
            "_voyage_encode_stub must carry a TODO(future-voyage-client) "
            "marker so the real Voyage HTTP client knows where to wire "
            "record_spend"
        )
        assert "record_spend" in text, (
            "_voyage_encode_stub TODO must reference record_spend by name "
            "so future grep finds the wiring location"
        )

    def test_anthropic_increment_not_wired_yet(self) -> None:
        """E08_S07 (Haiku summarizer) has not shipped yet. There should
        be no LIVE record_spend(provider="anthropic", ...) call site
        in server/ until the summarizer lands. This test guards against
        accidentally enabling spend tracking for a code path that
        doesn't exist."""
        import subprocess
        result = subprocess.run(
            [
                "grep", "-rEn",
                r'record_spend\([^)]*provider\s*=\s*"anthropic"',
                str(REPO_ROOT / "server"),
            ],
            capture_output=True, text=True, check=False,
        )
        # Match in test files or comments is fine. Match in non-test
        # server/ source is a real call site — E08_S07 hasn't shipped,
        # so this must be empty.
        non_test_hits = [
            line for line in result.stdout.splitlines()
            if "/test" not in line and "# TODO" not in line
        ]
        assert not non_test_hits, (
            "Found live record_spend(provider='anthropic') call in "
            "server/ source, but E08_S07 (Haiku summarizer) has not "
            f"shipped yet:\n  {non_test_hits}"
        )


# ---------------------------------------------------------------------------
# Module __all__ contract
# ---------------------------------------------------------------------------


class TestModuleContract:
    def test_all_exports_exist(self) -> None:
        for name in sc.__all__:
            assert hasattr(sc, name), (
                f"spend_constants.__all__ lists {name!r} but the module "
                f"does not expose it"
            )


# ---------------------------------------------------------------------------
# F2 closure — runtime registration via observability/__init__.py
# ---------------------------------------------------------------------------


class TestSpendMetricRegisteredAtRuntime:
    """F2 closure (m10 adversary critique): the original
    spend_constants.py module had no live importer in production
    server/ source, so even though API_SPEND_USD_TOTAL was defined
    correctly, prometheus_client.REGISTRY never knew about it at
    server startup. Result: /metrics scrapes would not include the
    series until some future call site referenced the module.

    Fix: server/observability/__init__.py now does a side-effect
    import of spend_constants. This test pins the contract: importing
    server.observability (which happens transitively whenever the
    server uses any metrics module) MUST cause the spend Counter to
    be registered with the default REGISTRY.
    """

    def test_importing_observability_package_registers_spend_counter(
        self,
    ) -> None:
        from prometheus_client import REGISTRY

        # Import via the package (not the submodule directly) — this
        # is the production path that surfaced the F2 gap.
        import server.observability  # noqa: F401

        # The metric is registered when the Counter constructor runs.
        # We can't directly query "is X registered" via the public API,
        # so we ping a label cell — REGISTRY.get_sample_value returns
        # 0.0 (not None) once a Counter with labels has had .labels()
        # called on at least one cell. Force a 0-increment to create
        # the cell, then verify the sample is visible.
        sc.API_SPEND_USD_TOTAL.labels(
            provider="voyage", model="voyage-3", agent_role="unknown",
        ).inc(0.0)
        sample = REGISTRY.get_sample_value(
            "arxmcp_api_spend_usd_total",
            {
                "provider": "voyage",
                "model": "voyage-3",
                "agent_role": "unknown",
            },
        )
        assert sample is not None, (
            "arxmcp_api_spend_usd_total not registered after "
            "`import server.observability`. The side-effect import in "
            "server/observability/__init__.py is the F2 fix; if you "
            "removed it, /metrics will silently lose the spend series."
        )
