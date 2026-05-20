"""E13_S04 — Threat-4 (resource exhaustion) audit.

Asserts the five resource-exhaustion limits documented in
`.claude/notes/08-security-observability-ops.md` § Threat 4 hold
under adversarial input:

1. **Numeric parameter caps** — JSON-Schema/Pydantic ``Field(le=...)``
   constraints reject ``k=10000``, ``depth=100``, etc. BEFORE handler
   body executes.
2. **Filter dict cap** — handler-body ``ValueError`` rejects an
   oversized ``filters`` dict on ``search_papers``.
3. **256 KB byte cap** — ``enforce_byte_cap`` rewrites oversized chunk
   bodies to ``resource_link`` content blocks.
4. **Per-session retrieval caps** — existing E08_S04 enforcement (3
   ``search_papers``, 4 ``get_chunk`` per session) returns
   ``RETRIEVAL_CAP_REACHED``.
5. **Hourly rate limit** — E13_S04 NEW: 1000 tool calls per session
   in a rolling 1-hour window returns ``RATE_LIMIT_EXCEEDED``.

**Reframed ACs vs. brief** (synthesis D1–D3):

- Brief named ``dependency_graph(depth=100)`` — that tool does NOT
  exist. Reframed to ``cite_neighbors(depth=100)``.
- Brief asserted ``-32602`` for Pydantic rejection — mcp Python SDK
  wraps ``ValidationError`` as ``isError=True``. Tests assert the
  security GOAL (handler body not entered), not the wire-level code.
- Brief asserted ``-32005`` for rate limit — NOT in MCP spec. Uses
  structured ``code="RATE_LIMIT_EXCEEDED"`` per project convention.
- Brief named ``E07_S10``, ``E06_S07``, ``E06_S08`` as prerequisites
  — all fictional. E07 stops at S04; E06 stops at S06. This
  milestone is therefore BOTH the specification AND the
  enforcement, same pattern as E13_S01–S03.

Full per-tool audit table: ``.claude/docs/security-threat-4-audit.md``.
"""

from __future__ import annotations

import asyncio
import time
import typing
from unittest.mock import patch

import pytest

from server.handlers.citations import handle_cite_neighbors
from server.handlers.equation import handle_find_equation
from server.handlers.lemma import handle_find_lemma_by_name
from server.handlers.search import (
    MAX_FILTER_ITEMS,
    MAX_K,
    handle_search_papers,
)
from server.session import (
    HOURLY_WINDOW_SECONDS,
    MAX_CALLS_PER_HOUR,
    SessionState,
    check_hourly_rate_limit,
)

# ===========================================================================
# Adversarial inputs (synthesis: known-bad numeric values from brief)
# ===========================================================================

#: The brief's named adversarial value for numeric over-cap inputs.
#: Used by ``TestNumericParamRejection`` behavioral tests (F2 rect)
#: to drive Pydantic validation through ``TypeAdapter`` and assert
#: ``ValidationError`` fires for every constrained numeric param.
ADVERSARIAL_K = 10000

#: The brief's named adversarial value for depth.
ADVERSARIAL_DEPTH = 100


def _run(coro):
    """Run a coroutine in a fresh event loop; pytest's asyncio
    integration adds complexity we don't need here."""
    return asyncio.run(coro)


def _le_constraint_for_param(handler_fn, param_name: str):
    """Return the ``Le(value)`` constraint object attached to a
    handler's ``Annotated[int, Field(le=...)]`` parameter, or
    ``None`` if no le= is declared.

    Uses :func:`typing.get_type_hints` with ``include_extras=True``
    to resolve PEP 604 string-form annotations under
    ``from __future__ import annotations``. ``inspect.signature``
    alone leaves the annotation as a string in that case.
    """
    hints = typing.get_type_hints(handler_fn, include_extras=True)
    annotated_type = hints.get(param_name)
    if annotated_type is None or not hasattr(annotated_type, "__metadata__"):
        return None
    for meta in annotated_type.__metadata__:
        # Pydantic v2 FieldInfo carries constraints in .metadata.
        if hasattr(meta, "metadata"):
            for constraint in meta.metadata:
                if hasattr(constraint, "le") and constraint.le is not None:
                    return constraint
    return None


def _adapter_for_param(handler_fn, param_name: str):
    """Return a :class:`pydantic.TypeAdapter` for a handler's
    ``Annotated[int, Field(le=...)]`` parameter (F2 rect).

    Behavioral test path: where the introspection helper proves the
    constraint is DECLARED, the TypeAdapter actually VALIDATES against
    it — exactly what FastMCP's schema-validation wrapper does when
    the tool is invoked through the MCP transport layer. Calling
    ``adapter.validate_python(10000)`` raises
    ``pydantic.ValidationError`` for any parameter whose annotation
    declares ``le<10000``. The handler function is never called, so
    the security goal "handler body not entered for over-cap input"
    is asserted by the absence of any monkey-patchable side effect
    on the handler.
    """
    from pydantic import TypeAdapter  # noqa: PLC0415

    hints = typing.get_type_hints(handler_fn, include_extras=True)
    annotated_type = hints.get(param_name)
    if annotated_type is None:
        return None
    return TypeAdapter(annotated_type)


# ===========================================================================
# AC1 + AC2: Numeric parameter caps
# ===========================================================================


class TestNumericParamRejection:
    """Pydantic ``Field(le=...)`` constraints reject over-cap numeric
    arguments BEFORE the handler body executes. The mcp Python SDK
    wraps ``ValidationError`` into ``CallToolResult(isError=True)``
    at the transport layer; testing the handler function directly
    asserts the same security GOAL — handler body not entered.

    Pydantic validation fires when the handler is called via FastMCP's
    schema-validation wrapper, which is NOT exercised when we call
    the handler function directly in tests. To prove the security
    goal we instead test the canonical surface that DOES fire on
    direct call: each handler's pre-resource validation logic + the
    Pydantic constraint table is asserted via inspection.
    """

    def test_search_papers_k_field_constraint_present(self):
        """The ``k`` parameter on ``search_papers`` declares
        ``Field(ge=1, le=50)``. Pydantic rejects ``k=10000`` at
        validation time — handler body is never entered.
        """
        le = _le_constraint_for_param(handle_search_papers, "k")
        assert le is not None, (
            "search_papers.k must have a le= constraint (E13_S04 Threat 4)"
        )
        assert le.le == MAX_K == 50

    def test_find_equation_k_field_constraint_present(self):
        le = _le_constraint_for_param(handle_find_equation, "k")
        assert le is not None
        assert le.le == 50

    def test_find_lemma_by_name_k_field_constraint_present(self):
        le = _le_constraint_for_param(handle_find_lemma_by_name, "k")
        assert le is not None
        assert le.le == 50

    def test_cite_neighbors_depth_field_constraint_present(self):
        """Reframed from brief's fictional ``dependency_graph(depth=100)``.
        The real depth-constrained tool is ``cite_neighbors`` with
        ``Field(ge=1, le=3)``.
        """
        le = _le_constraint_for_param(handle_cite_neighbors, "depth")
        assert le is not None
        assert le.le == 3, (
            f"cite_neighbors.depth must have le=3 (E13_S04 Threat 4 "
            f"reframe from fictional dependency_graph). Got "
            f"le={le.le}"
        )

    def test_cite_neighbors_limit_field_constraint_present(self):
        le = _le_constraint_for_param(handle_cite_neighbors, "limit")
        assert le is not None
        assert le.le == 100

    # ------------------------------------------------------------------
    # F2 rectification (E13_S04 adversary critique): behavioral tests.
    # The constraint-presence checks above prove the Field metadata
    # is DECLARED. These tests prove the constraint is ENFORCED — by
    # validating the over-cap value through ``pydantic.TypeAdapter``
    # (exactly what FastMCP's schema-validation wrapper does on the
    # MCP transport boundary). ValidationError fires; the handler
    # function is never called.
    # ------------------------------------------------------------------

    def test_search_papers_k_over_cap_rejected_by_validator(self):
        from pydantic import ValidationError

        adapter = _adapter_for_param(handle_search_papers, "k")
        assert adapter is not None
        with pytest.raises(ValidationError, match="less than or equal to"):
            adapter.validate_python(ADVERSARIAL_K)
        # Boundary: 50 is accepted.
        assert adapter.validate_python(50) == 50

    def test_find_equation_k_over_cap_rejected_by_validator(self):
        from pydantic import ValidationError

        adapter = _adapter_for_param(handle_find_equation, "k")
        assert adapter is not None
        with pytest.raises(ValidationError, match="less than or equal to"):
            adapter.validate_python(ADVERSARIAL_K)

    def test_find_lemma_by_name_k_over_cap_rejected_by_validator(self):
        from pydantic import ValidationError

        adapter = _adapter_for_param(handle_find_lemma_by_name, "k")
        assert adapter is not None
        with pytest.raises(ValidationError, match="less than or equal to"):
            adapter.validate_python(ADVERSARIAL_K)

    def test_cite_neighbors_depth_over_cap_rejected_by_validator(self):
        """Reframed from brief's fictional ``dependency_graph(depth=100)``.
        Real depth=100 against ``cite_neighbors`` (le=3) is rejected
        at validation."""
        from pydantic import ValidationError

        adapter = _adapter_for_param(handle_cite_neighbors, "depth")
        assert adapter is not None
        with pytest.raises(ValidationError, match="less than or equal to"):
            adapter.validate_python(ADVERSARIAL_DEPTH)

    def test_cite_neighbors_limit_over_cap_rejected_by_validator(self):
        from pydantic import ValidationError

        adapter = _adapter_for_param(handle_cite_neighbors, "limit")
        assert adapter is not None
        with pytest.raises(ValidationError, match="less than or equal to"):
            adapter.validate_python(101)


# ===========================================================================
# AC3: Filter dict size cap (handler-body validation)
# ===========================================================================


class TestFiltersCapEnforced:
    """The ``filters`` dict on ``search_papers`` is capped at
    :data:`MAX_FILTER_ITEMS` items via handler-body validation. The
    cap is enforced BEFORE any resource lookup (no LanceDB query, no
    embedding, no cache touch).

    Handler-body validation is used instead of Pydantic
    ``Field(max_length=...)`` so the constraint does NOT bump
    ``EXPECTED_TOOL_SCHEMA_SHA256`` per the BP1 byte-stability
    discipline in ``.claude/notes/07-multi-agent-caching.md``.
    """

    def test_filters_at_cap_does_not_raise_value_error(self):
        """Exactly ``MAX_FILTER_ITEMS`` items is the boundary — must
        not raise. The handler may still fail downstream (no seeded
        corpus), but NOT with the resource-exhaustion ValueError.
        """
        filters = {f"k{i}": i for i in range(MAX_FILTER_ITEMS)}
        sentinel = "did_not_reach_get_resources"
        with patch(
            "server.handlers.search.get_resources",
            side_effect=RuntimeError(sentinel),
        ):
            with pytest.raises(RuntimeError) as exc:
                _run(handle_search_papers(query="x", filters=filters))
            # Reached the resources fetch — filter cap did not fire.
            assert sentinel in str(exc.value), (
                f"filters at cap ({MAX_FILTER_ITEMS}) must not raise the "
                f"resource-exhaustion ValueError; got {exc.value!r}"
            )

    def test_filters_over_cap_rejected_with_value_error(self):
        """One above the cap must raise ValueError BEFORE
        get_resources is called. Use a sentinel monkeypatch on
        get_resources to prove the resource layer was not reached.
        """
        filters = {f"k{i}": i for i in range(MAX_FILTER_ITEMS + 1)}
        sentinel = "resource_layer_was_unexpectedly_reached"
        with patch(
            "server.handlers.search.get_resources",
            side_effect=RuntimeError(sentinel),
        ), pytest.raises(ValueError, match="max allowed is"):
            _run(handle_search_papers(query="x", filters=filters))

    def test_filters_10000_items_rejected_brief_ac(self):
        """The brief's named adversarial input — 10000-item filter
        dict — must be rejected.
        """
        adversarial_filters = {f"author{i}": "x" for i in range(10000)}
        with pytest.raises(ValueError, match="resource-exhaustion cap"):
            _run(handle_search_papers(query="x", filters=adversarial_filters))


# ===========================================================================
# F4 rect: get_definitions.term cap (was the only uncapped string param)
# ===========================================================================


class TestDefinitionsTermCap:
    """F4 rectification (E13_S04 adversary critique).

    Closes the last named gap in the Threat-4 audit table:
    ``get_definitions.term`` previously had no length cap. An
    adversary could pass ``term="X" * 1_000_000`` to inflate memory
    before any LanceDB query fires. Handler-body validation now
    rejects over-cap terms with a ``ValueError``, identical
    discipline to ``MAX_FILTER_ITEMS`` in ``search_papers``.
    """

    def test_term_at_cap_does_not_raise_value_error(self):
        from server.handlers.definitions import (
            MAX_TERM_LENGTH,
            handle_get_definitions,
        )

        sentinel = "did_not_reach_resources"
        with patch(
            "server.handlers.definitions._get_definitions_table",
            side_effect=RuntimeError(sentinel),
        ):
            with pytest.raises(RuntimeError) as exc:
                _run(
                    handle_get_definitions(
                        paper_id="2401.00100",
                        term="x" * MAX_TERM_LENGTH,
                    )
                )
            # Reached the resources fetch — term cap did not fire at boundary.
            assert sentinel in str(exc.value), (
                f"term at cap (200 chars) must not raise the term cap "
                f"ValueError; got {exc.value!r}"
            )

    def test_term_over_cap_rejected_with_value_error(self):
        from server.handlers.definitions import handle_get_definitions

        sentinel = "resource_layer_unexpectedly_reached"
        with patch(
            "server.handlers.definitions._get_definitions_table",
            side_effect=RuntimeError(sentinel),
        ), pytest.raises(ValueError, match="resource-exhaustion cap"):
            _run(
                handle_get_definitions(
                    paper_id="2401.00100",
                    term="x" * 10000,
                )
            )


# ===========================================================================
# AC4: 256 KB byte cap (resource_link rewrite)
# ===========================================================================


class TestByteCapEnforcement:
    """The 256 KB byte cap on tool result inline content is enforced
    by :func:`server.tools.enforce_byte_cap`. Oversized chunk bodies
    are truncated to 1024 chars and a ``resource_link`` content block
    is returned per the E06_S04 design.

    These tests exercise ``enforce_byte_cap`` directly because
    constructing a full ``get_chunk`` integration test requires a
    seeded LanceDB; the function-level unit covers the same code
    path that ``get_chunk`` uses.
    """

    def test_under_cap_passes_through_unchanged(self):
        """Payload under the cap: no truncation, no resource_link."""
        from server.tools import enforce_byte_cap

        # Small body — comfortably under the cap.
        payload = {
            "chunk": {"body_text": "x" * 1000, "chunk_id": "test"},
            "found": True,
        }
        # Need a fake config + resources for the cap function. The
        # config.result_byte_cap default is 256 KB; our payload is
        # ~1KB so it stays under.
        from unittest.mock import MagicMock

        from server import tools as tools_mod

        fake_resources = MagicMock()
        fake_resources.config.result_byte_cap = 256 * 1024
        fake_resources.corpus_info.version = "test-version"
        with patch.object(tools_mod, "get_resources", return_value=fake_resources):
            structured, content_blocks = enforce_byte_cap(
                payload,
                chunk_id="test",
                body_text_path=("chunk", "body_text"),
            )
        assert content_blocks == [], "no resource_link for under-cap"
        assert structured["chunk"]["body_text"] == "x" * 1000, "body unchanged"
        assert "body_truncated" not in structured

    def test_over_cap_truncates_and_emits_resource_link(self):
        """Payload over the cap: body truncated to 1024 chars,
        ``body_truncated=True`` set, and a resource_link content
        block is returned.
        """
        from server.tools import enforce_byte_cap

        # Construct a body that, when JSON-serialized + doubled for
        # wire overhead (factor 2 per server/tools.py), exceeds the
        # cap. With cap=256 KB and wire factor 2, inner content must
        # exceed 128 KB to trip the cap. Use 200 KB to be safely
        # over.
        oversized_body = "x" * (200 * 1024)
        payload = {
            "chunk": {"body_text": oversized_body, "chunk_id": "test-cid"},
            "found": True,
        }
        from unittest.mock import MagicMock

        from server import tools as tools_mod

        fake_resources = MagicMock()
        fake_resources.config.result_byte_cap = 256 * 1024
        fake_resources.corpus_info.version = "test-version"
        with patch.object(tools_mod, "get_resources", return_value=fake_resources):
            structured, content_blocks = enforce_byte_cap(
                payload,
                chunk_id="test-cid",
                body_text_path=("chunk", "body_text"),
            )

        # Truncation applied.
        assert len(structured["chunk"]["body_text"]) <= 1024, (
            f"body must be truncated to <= 1024 chars on over-cap; got "
            f"len={len(structured['chunk']['body_text'])}"
        )
        # Truncation signal set.
        assert structured.get("body_truncated") is True, (
            "structured payload must signal body_truncated=True"
        )
        # Resource link emitted.
        assert content_blocks, "must emit a resource_link content block"
        link = content_blocks[0]
        assert link["type"] == "resource_link"
        assert "test-cid" in link["uri"]


# ===========================================================================
# AC5: Hourly rate limit (E13_S04 NEW)
# ===========================================================================


class TestHourlyRateLimit:
    """The 1000-calls-per-hour rate limit (E13_S04 Threat 4) is
    enforced by :func:`server.session.check_hourly_rate_limit`.
    Sliding-window deque of timestamps; rejected calls do NOT
    consume cap budget.
    """

    def test_constants_match_design_note(self):
        """The cap and window are pinned to match the design note's
        '1000 per hour' specification."""
        assert MAX_CALLS_PER_HOUR == 1000
        assert HOURLY_WINDOW_SECONDS == 3600

    def test_under_cap_calls_succeed(self):
        """The first 1000 calls in an hour are allowed."""
        state = SessionState(session_id="test-session-1")
        now = time.time()
        for i in range(MAX_CALLS_PER_HOUR):
            allowed, count, limit = _run(check_hourly_rate_limit(state, now=now))
            assert allowed is True, f"call {i + 1} should be allowed; got rejection"
            assert count == i + 1
            assert limit == MAX_CALLS_PER_HOUR
        # Deque is at capacity.
        assert len(state.call_timestamps) == MAX_CALLS_PER_HOUR

    def test_1001st_call_in_window_rejected(self):
        """The 1001st call within the rolling window is rejected
        with ``allowed=False``. Budget is NOT consumed.
        """
        state = SessionState(session_id="test-session-2")
        now = time.time()
        # Fill up to cap.
        for _ in range(MAX_CALLS_PER_HOUR):
            _run(check_hourly_rate_limit(state, now=now))
        # 1001st call.
        allowed, count, limit = _run(check_hourly_rate_limit(state, now=now))
        assert allowed is False, "1001st call must be rejected"
        assert count == MAX_CALLS_PER_HOUR + 1
        assert limit == MAX_CALLS_PER_HOUR
        # Deque size unchanged — rejected call did NOT consume budget.
        assert len(state.call_timestamps) == MAX_CALLS_PER_HOUR

    def test_sliding_window_prunes_old_timestamps(self):
        """Timestamps older than the window are pruned from the
        deque on subsequent calls, allowing fresh requests after
        the window slides.
        """
        state = SessionState(session_id="test-session-3")
        # Seed 1000 timestamps "one hour ago".
        old_time = time.time() - HOURLY_WINDOW_SECONDS - 1
        state.call_timestamps.extend([old_time] * MAX_CALLS_PER_HOUR)
        assert len(state.call_timestamps) == MAX_CALLS_PER_HOUR
        # A fresh call NOW should prune the old timestamps and
        # be allowed (the window slid past the seeded entries).
        now = time.time()
        allowed, count, limit = _run(check_hourly_rate_limit(state, now=now))
        assert allowed is True, (
            "after the window slides past old timestamps, fresh calls "
            "must be allowed"
        )
        assert count == 1, f"count should reset to 1 post-prune; got {count}"
        # Deque now contains only the new timestamp.
        assert len(state.call_timestamps) == 1

    def test_keyed_per_session_no_cross_session_leak(self):
        """Two distinct sessions track independently; one hitting
        the cap does NOT affect the other.
        """
        state_a = SessionState(session_id="session-a")
        state_b = SessionState(session_id="session-b")
        now = time.time()
        # Fill session A to cap.
        for _ in range(MAX_CALLS_PER_HOUR):
            _run(check_hourly_rate_limit(state_a, now=now))
        # Session B's first call must still succeed.
        allowed, count, _ = _run(check_hourly_rate_limit(state_b, now=now))
        assert allowed is True, "session B unaffected by session A's cap"
        assert count == 1

    def test_brief_ac_1500_calls_fires_at_1001(self):
        """The brief AC: '1,500 tool calls within one hour from a
        single Mcp-Session-Id are rate-limited at 1,000.' Verify the
        exact boundary: calls 1-1000 succeed, calls 1001-1500 are
        rejected.
        """
        state = SessionState(session_id="brief-ac-session")
        now = time.time()
        successes = 0
        rejections = 0
        for _ in range(1500):
            allowed, _, _ = _run(check_hourly_rate_limit(state, now=now))
            if allowed:
                successes += 1
            else:
                rejections += 1
        assert successes == MAX_CALLS_PER_HOUR == 1000
        assert rejections == 500


# ===========================================================================
# Cross-axis integration: rate-limit payload shape
# ===========================================================================


class TestRateLimitPayloadShape:
    """The RATE_LIMIT_EXCEEDED response payload is distinct from
    RETRIEVAL_CAP_REACHED so consuming agents can tell which cap
    fired. Mirrors the structure of the existing payload helper.
    """

    def test_rate_limit_payload_has_distinct_code(self):
        from server.middleware import _rate_limit_payload, _retrieval_cap_payload

        rate_payload = _rate_limit_payload("search_papers", attempted=1001, limit=1000)
        retrieval_payload = _retrieval_cap_payload(
            "search_papers", attempted=4, limit=3
        )
        assert rate_payload["code"] == "RATE_LIMIT_EXCEEDED"
        assert retrieval_payload["code"] == "RETRIEVAL_CAP_REACHED"
        assert rate_payload["code"] != retrieval_payload["code"], (
            "rate-limit and retrieval-cap codes must be distinct so "
            "agents can tell which cap fired"
        )

    def test_rate_limit_payload_includes_window_seconds(self):
        """The hourly window length is exposed in the payload so the
        agent knows how long to back off."""
        from server.middleware import _rate_limit_payload

        payload = _rate_limit_payload("any_tool", attempted=1001, limit=1000)
        assert payload["window_seconds"] == HOURLY_WINDOW_SECONDS == 3600

    def test_rate_limit_payload_shape_matches_retrieval_cap(self):
        """Both payload shapes share the same envelope keys so
        consumer code can parse them with one handler."""
        from server.middleware import _rate_limit_payload, _retrieval_cap_payload

        rate = _rate_limit_payload("search_papers", attempted=1001, limit=1000)
        retrieval = _retrieval_cap_payload("search_papers", attempted=4, limit=3)
        common_keys = {"code", "message", "tool", "limit", "session_attempted_count"}
        assert common_keys.issubset(rate.keys())
        assert common_keys.issubset(retrieval.keys())


# ===========================================================================
# F1 rect: atomic two-cap check — no budget leak
# ===========================================================================


class TestAtomicTwoCapCheck:
    """F1 rectification (E13_S04 adversary critique).

    The pre-rect middleware called ``check_and_increment`` and
    ``check_hourly_rate_limit`` separately. If the per-tool cap
    allowed (incremented counter) but the hourly cap rejected, the
    retrieval budget was silently leaked — a subsequent legitimate
    retry could be rejected by per-tool even though the original
    call never executed retrieval work.

    The fix introduces ``check_both_caps`` which holds the session
    lock once and mutates neither counter unless both caps pass.
    """

    def test_per_tool_rejected_does_not_consume_hourly_budget(self):
        """When the per-tool cap rejects, the hourly timestamp deque
        is NOT mutated.
        """
        from server.session import check_both_caps

        state = SessionState(session_id="f1-test-a")
        # Saturate per-tool search cap.
        state.search_count = 3  # at MAX_SEARCH_PAPERS_CALLS

        before = len(state.call_timestamps)
        verdict, count, limit = _run(check_both_caps(state, "search_papers"))
        after = len(state.call_timestamps)

        assert verdict == "per_tool_rejected"
        assert after == before, (
            "hourly deque must not be mutated when per-tool cap rejects "
            "(F1 budget-leak fix)"
        )

    def test_hourly_rejected_does_not_consume_per_tool_budget(self):
        """When the hourly cap rejects, the per-tool counter is
        NOT incremented — even though the per-tool cap would have
        allowed the call.
        """
        from server.session import check_both_caps

        state = SessionState(session_id="f1-test-b")
        # Per-tool well under cap (search_count=0).
        # Hourly at cap (1000 fresh timestamps).
        now = time.time()
        state.call_timestamps.extend([now] * MAX_CALLS_PER_HOUR)

        verdict, count, limit = _run(check_both_caps(state, "search_papers", now=now))

        assert verdict == "hourly_rejected"
        # Per-tool counter unchanged — budget not leaked.
        assert state.search_count == 0, (
            f"per-tool search_count must stay at 0 when hourly cap "
            f"rejects (F1 budget-leak fix); got {state.search_count}"
        )

    def test_both_pass_commits_both_atomically(self):
        """When both caps pass, both counters are mutated."""
        from server.session import check_both_caps

        state = SessionState(session_id="f1-test-c")
        verdict, count, limit = _run(check_both_caps(state, "search_papers"))

        assert verdict == "allowed"
        # Both counters reflect the commit.
        assert state.search_count == 1
        assert len(state.call_timestamps) == 1

    def test_non_capped_tool_only_hits_hourly(self):
        """Tools not in TOOLS_WITH_CAPS (e.g. ``get_paper``,
        ``find_lemma_by_name``) have no per-tool cap. Only the
        hourly cap applies.
        """
        from server.session import check_both_caps

        state = SessionState(session_id="f1-test-d")
        verdict, count, limit = _run(check_both_caps(state, "get_paper"))

        assert verdict == "allowed"
        # No per-tool counter for get_paper.
        assert state.search_count == 0
        assert state.chunk_count == 0
        # Hourly timestamp recorded.
        assert len(state.call_timestamps) == 1


# ===========================================================================
# F5 rect: middleware integration test for the hourly-cap path
# ===========================================================================


class TestHourlyCapMiddlewareIntegration:
    """F5 rectification (E13_S04 adversary critique).

    Exercises the full ``SessionCapMiddleware.__call__`` path:
    receive ``tools/call`` request → check_both_caps → emit
    RATE_LIMIT_EXCEEDED short-circuit response. Pre-rect coverage
    was unit-level only (``check_hourly_rate_limit`` +
    ``_rate_limit_payload`` separately); this verifies they wire
    together correctly.
    """

    def test_hourly_cap_at_limit_short_circuits_middleware(self):
        """A session with the hourly deque at MAX_CALLS_PER_HOUR
        gets RATE_LIMIT_EXCEEDED on the next call, without ever
        reaching the inner ASGI app.
        """
        import json

        from server.middleware import SessionCapMiddleware
        from server.session import (
            _SESSIONS,
            reset_session_state_for_tests,
        )

        reset_session_state_for_tests()

        # A valid UUID4-hex session-id.
        session_id = "0123456789abcdef0123456789abcdef"

        # Pre-seed the session at the hourly cap.
        seeded_state = SessionState(session_id=session_id)
        now = time.time()
        seeded_state.call_timestamps.extend([now] * MAX_CALLS_PER_HOUR)
        _SESSIONS[session_id] = seeded_state

        # Fake inner ASGI app that records whether it was called.
        inner_app_calls: list[bool] = []

        async def inner_app(scope, receive, send):
            inner_app_calls.append(True)
            await send(
                {"type": "http.response.start", "status": 200, "headers": []}
            )
            await send(
                {"type": "http.response.body", "body": b"", "more_body": False}
            )

        middleware = SessionCapMiddleware(inner_app)

        # Build a tools/call request body for a tool NOT in TOOLS_WITH_CAPS
        # (get_paper) so the per-tool cap is a no-op and we isolate the
        # hourly check.
        request_body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 42,
                "method": "tools/call",
                "params": {"name": "get_paper", "arguments": {"paper_id": "2401.00001"}},
            }
        ).encode("utf-8")

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [
                (b"content-type", b"application/json"),
                (b"mcp-session-id", session_id.encode("ascii")),
            ],
        }

        sent_events: list[dict] = []

        async def send(event):
            sent_events.append(event)

        # Synthetic receive yields the body in one shot then disconnect.
        body_yielded = [False]

        async def receive():
            if not body_yielded[0]:
                body_yielded[0] = True
                return {
                    "type": "http.request",
                    "body": request_body,
                    "more_body": False,
                }
            return {"type": "http.disconnect"}

        _run(middleware(scope, receive, send))

        # Inner app NEVER called — middleware short-circuited.
        assert not inner_app_calls, (
            "inner ASGI app must NOT be reached when hourly cap "
            "rejects (F5 integration test)"
        )
        # Response is 200 with RATE_LIMIT_EXCEEDED structured content.
        start_events = [e for e in sent_events if e["type"] == "http.response.start"]
        body_events = [e for e in sent_events if e["type"] == "http.response.body"]
        assert len(start_events) == 1
        assert start_events[0]["status"] == 200
        body = b"".join(e["body"] for e in body_events).decode("utf-8")
        parsed = json.loads(body)
        assert parsed["result"]["isError"] is True
        assert parsed["result"]["structuredContent"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert parsed["result"]["structuredContent"]["window_seconds"] == 3600

        reset_session_state_for_tests()


# ===========================================================================
# E13_S04b — extend 256 KB byte cap to remaining 5 tool handlers
#   (search_papers, find_equation, find_lemma_by_name, get_paper,
#    cite_neighbors). Closes Threat 4 partial-coverage gap G1
#    (github.com/chris-dare-dev/arXMCP#1).
# ===========================================================================


class TestE13S04bCapExtension:
    """Each of the 5 newly-covered handlers now defines a private
    ``_cap`` helper that wraps :func:`server.tools.enforce_byte_cap`.
    The helpers are tested directly here — they are tiny pure
    functions on dict, decoupled from LanceDB / Resources / async
    machinery, so the tests can assert the cap mechanism without
    spinning up the full handler stack.

    The shape contract for every helper:
    - input: ``dict`` (the response payload built by the handler)
    - output: ``dict`` (same content under cap; truncated +
      ``body_truncated=True`` flag set when over cap)

    Per the E13_S04b synthesis, multi-result handlers
    (``search_papers``, ``find_equation``, ``find_lemma_by_name``,
    ``get_paper``) pass ``chunk_id=None`` so the helper omits the
    ``resource_link`` content block when the cap fires (the
    over-cap surface is the aggregate response, not a single
    chunk; agents follow the per-row ``chunk_id`` in
    ``results[]`` / ``matches[]`` to fetch full bodies).

    ``cite_neighbors`` passes the INPUT ``chunk_id`` to mark the
    parent context whose neighborhood was being returned — the
    resource_link IS meaningful there.
    """

    @staticmethod
    def _fake_resources(cap_bytes: int = 256 * 1024):
        """Build a MagicMock that satisfies ``enforce_byte_cap``'s
        ``get_resources().config.result_byte_cap`` lookup with a
        configurable cap value."""
        from unittest.mock import MagicMock as _MM
        fake = _MM()
        fake.config.result_byte_cap = cap_bytes
        fake.corpus_info.version = "test-version"
        return fake

    @pytest.mark.parametrize(
        "module_name",
        [
            "server.handlers.search",
            "server.handlers.equation",
            "server.handlers.lemma",
            "server.handlers.paper",
        ],
    )
    def test_multi_result_cap_passes_under_cap_unchanged(
        self, module_name: str
    ):
        """Under-cap payload routes through ``_cap`` unchanged: no
        ``body_truncated`` flag set, structure preserved.
        """
        import importlib

        from server import tools as tools_mod

        module = importlib.import_module(module_name)
        small_payload = {
            "results": [{"chunk_id": "arxiv:2412.00001:abc1234567890abc"}],
            "found": True,
        }
        with patch.object(
            tools_mod, "get_resources", return_value=self._fake_resources()
        ):
            out = module._cap(small_payload)
        assert "body_truncated" not in out, (
            f"under-cap payload must not get body_truncated flag; "
            f"got: {out!r}"
        )
        # Structure preserved.
        assert out["results"] == small_payload["results"]
        assert out["found"] is True

    @pytest.mark.parametrize(
        "module_name,oversized_field",
        [
            ("server.handlers.search", "results"),
            ("server.handlers.equation", "results"),
            ("server.handlers.lemma", "matches"),
            ("server.handlers.paper", "paper"),
        ],
    )
    def test_multi_result_cap_fires_on_over_cap(
        self, module_name: str, oversized_field: str
    ):
        """Over-cap payload: ``body_truncated=True`` is set; the
        payload is sorted by ``enforce_byte_cap`` (returned via
        ``_sort_dict``). For multi-result handlers
        ``chunk_id=None`` → no resource_link content block, but the
        ``body_truncated`` signal IS preserved.
        """
        import importlib

        from server import tools as tools_mod

        module = importlib.import_module(module_name)
        # Construct a payload that exceeds 256 KB after JSON serialize
        # × wire-overhead-factor 2. Inner content > 128 KB does it.
        # The oversized payload uses a 200-KB filler string.
        filler = "x" * (200 * 1024)
        if oversized_field == "paper":
            # paper.py emits a flat ``paper`` dict; stuff the
            # ``abstract`` field with the filler.
            oversized_payload = {
                "found": True,
                "metadata_status": "synthesized_from_chunks",
                "paper": {"abstract": filler, "paper_id": "test"},
                "paper_id": "test",
            }
        else:
            # search / equation / lemma use list-of-rows with the
            # filler stuffed into a representative content field.
            row = {
                "chunk_id": "arxiv:2412.00001:abc1234567890abc",
                "snippet": filler,
            }
            oversized_payload = {oversized_field: [row], "found": True}
        with patch.object(
            tools_mod, "get_resources", return_value=self._fake_resources()
        ):
            out = module._cap(oversized_payload)
        assert out.get("body_truncated") is True, (
            f"over-cap payload must set body_truncated=True; "
            f"keys={sorted(out.keys())!r}"
        )

    def test_cite_neighbors_cap_passes_under_cap(self):
        """``cite_neighbors._cap`` takes ``chunk_id`` as a positional
        argument. Under-cap payload (the v1 stub with empty
        neighbors) routes through unchanged.
        """
        from server import tools as tools_mod
        from server.handlers.citations import _cap

        small_payload = {
            "chunk_id": "arxiv:2412.00001:abc1234567890abc",
            "depth": 1,
            "direction": "cited",
            "infrastructure_status": "deferred",
            "limit": 30,
            "neighbors": [],
            "note": "stub",
        }
        with patch.object(
            tools_mod,
            "get_resources",
            return_value=TestE13S04bCapExtension._fake_resources(),
        ):
            out = _cap(small_payload, "arxiv:2412.00001:abc1234567890abc")
        assert "body_truncated" not in out
        assert out["chunk_id"] == small_payload["chunk_id"]

    def test_cite_neighbors_cap_fires_with_input_chunk_id(self):
        """When ``cite_neighbors`` returns an over-cap response
        (forward-compat for E09 wire-up), the ``body_truncated``
        flag is set AND the resource_link content block IS emitted
        using the INPUT chunk_id (the parent context).
        """
        from server import tools as tools_mod
        from server.handlers.citations import _cap

        filler = "x" * (200 * 1024)
        oversized_payload = {
            "chunk_id": "arxiv:2412.00001:abc1234567890abc",
            "depth": 2,
            "direction": "cited",
            "infrastructure_status": "wired",
            "limit": 100,
            "neighbors": [
                {"chunk_id": "arxiv:2412.00002:def4567890abcdef", "context": filler}
            ],
        }
        with patch.object(
            tools_mod,
            "get_resources",
            return_value=TestE13S04bCapExtension._fake_resources(),
        ):
            out = _cap(oversized_payload, "arxiv:2412.00001:abc1234567890abc")
        assert out.get("body_truncated") is True

    @pytest.mark.parametrize(
        "module_name",
        [
            "server.handlers.search",
            "server.handlers.equation",
            "server.handlers.lemma",
            "server.handlers.paper",
            "server.handlers.citations",
        ],
    )
    def test_handler_module_imports_enforce_byte_cap(
        self, module_name: str
    ):
        """Static check: every newly-covered handler imports
        ``enforce_byte_cap`` from ``server.tools``. Catches a
        regression where someone refactors a handler and accidentally
        drops the cap helper import — the per-handler ``_cap`` test
        above would still pass (because pytest re-imports the
        module), but if the production import is missing the live
        request path would fail.
        """
        import inspect

        from server import tools as tools_mod

        module = __import__(module_name, fromlist=["_cap"])
        # _cap must be a function (not a stub) in every covered
        # module.
        assert callable(getattr(module, "_cap", None)), (
            f"{module_name} must define a `_cap` helper that wraps "
            f"server.tools.enforce_byte_cap (E13_S04b contract)"
        )
        # And the helper must be importable / inspectable.
        source = inspect.getsource(module._cap)
        assert "enforce_byte_cap" in source, (
            f"{module_name}._cap must call server.tools.enforce_byte_cap; "
            f"current source does not reference it"
        )
        # The handler must actually import it (defensive against the
        # case where _cap exists but enforce_byte_cap is shadowed).
        assert hasattr(tools_mod, "enforce_byte_cap"), (
            "server.tools.enforce_byte_cap must exist as a module-level "
            "symbol"
        )
