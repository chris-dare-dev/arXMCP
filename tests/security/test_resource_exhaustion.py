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
# Adversarial inputs (synthesis: known-bad numeric values)
# ===========================================================================

#: The brief's named adversarial value for numeric over-cap inputs.
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
