"""E13_S08 — Threat-8 (tool-result and request-input redaction in
structured logs) audit.

Closes the four acceptance criteria of the milestone:

1. ``pytest tests/security/test_log_redaction.py`` passes.
2. A log record with ``event="search_papers"`` and
   ``query="Faltings theorem"`` at INFO level has ``query`` absent
   from the serialized JSON.
3. The same record at DEBUG level includes ``query``.
4. ``body_canonical``, ``body_raw_latex``, and ``mathml`` follow the
   same pattern.

Threat verbatim (``.claude/notes/08-security-observability-ops.md``
§ Logging):

    > Sensitive fields (full query text, chunk bodies) are logged at
    > DEBUG only, never at INFO or above.

Caller-side scope (from the synthesis):

- Only top-level ``record.__dict__`` keys are redacted. Nested dict
  payloads (``extra={"context": {"query": ...}}``), ``record.args``
  tuples, and pre-composed message templates are documented caller
  contracts, not in the filter's mechanical scope.
- ``paper_id`` and ``chunk_id`` are identifiers, NOT sensitive
  content; explicitly OUT of scope per the brief.
"""

from __future__ import annotations

import io
import json
import logging
from typing import Any

import pytest

from server.observability.log_filter import REDACTED_FIELDS, RedactionFilter
from server.observability.logging_setup import (
    JsonFormatter,
    _reset_debug_warning_for_tests,
    configure,
)

# ===========================================================================
# Helpers
# ===========================================================================


def _make_isolated_logger(
    name: str,
    *,
    level: int,
    filter_instance: RedactionFilter | None = None,
) -> tuple[logging.Logger, io.StringIO]:
    """Build a logger that emits to an in-memory ``StringIO`` via
    :class:`JsonFormatter`, with optional filter installed.

    The logger is configured with ``propagate=False`` so it does NOT
    bubble up to the root logger (which the test session shares with
    pytest's own capture). Each test gets a fresh per-name logger.
    """
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.setLevel(level)
    logger = logging.getLogger(name)
    # Clear any handlers/filters from a prior test that re-used the
    # same name (defensive — the unique-name pattern below should
    # prevent this in practice).
    logger.handlers.clear()
    logger.filters.clear()
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    if filter_instance is not None:
        # The filter goes on the handler so the level check inside
        # the filter (record.levelno >= INFO) sees the same record
        # the handler will format.
        handler.addFilter(filter_instance)
    return logger, stream


def _parse_one(stream: io.StringIO) -> dict[str, Any]:
    """Parse exactly one JSON line out of ``stream``. Asserts the
    handler produced exactly one record."""
    lines = [line for line in stream.getvalue().splitlines() if line.strip()]
    assert len(lines) == 1, f"expected exactly 1 log line, got {len(lines)}: {lines!r}"
    return json.loads(lines[0])


# ===========================================================================
# AC2 — INFO record strips query from serialized JSON
# AC3 — DEBUG record keeps query
# AC4 — body_canonical / body_raw_latex / mathml follow the same pattern
# ===========================================================================


class TestRedactionFilter:
    """The :class:`RedactionFilter` strips every key in
    :data:`REDACTED_FIELDS` from records emitted at INFO+ level and
    leaves them intact at DEBUG.
    """

    @pytest.mark.parametrize("field", sorted(REDACTED_FIELDS))
    def test_info_record_strips_sensitive_field(self, field: str):
        """AC2 + AC4 parametrized — for every member of
        ``REDACTED_FIELDS``, an INFO record carrying that field as
        an ``extra=`` kwarg must NOT have the field in its serialized
        JSON.
        """
        sensitive_value = f"<sensitive payload for {field}>"
        logger, stream = _make_isolated_logger(
            f"test.e13_s08.info.{field}",
            level=logging.INFO,
            filter_instance=RedactionFilter(),
        )
        logger.info(
            "search_papers",
            extra={"event": "search_papers", field: sensitive_value},
        )
        payload = _parse_one(stream)
        assert field not in payload, (
            f"INFO record leaked the redacted field {field!r}: "
            f"payload keys={sorted(payload.keys())}"
        )
        # Sanity: the non-sensitive fields are still present so we
        # know the formatter ran and we're not just looking at empty
        # output.
        assert payload.get("event") == "search_papers"
        assert payload.get("level") == "INFO"

    @pytest.mark.parametrize("field", sorted(REDACTED_FIELDS))
    def test_debug_record_keeps_sensitive_field(self, field: str):
        """AC3 + AC4 parametrized — at DEBUG level, the filter is a
        no-op; every redacted field is preserved verbatim. This is
        the developer's explicit opt-in to full disclosure via
        ``ARXMCP_LOG_LEVEL=DEBUG``.
        """
        sensitive_value = f"<sensitive payload for {field}>"
        logger, stream = _make_isolated_logger(
            f"test.e13_s08.debug.{field}",
            level=logging.DEBUG,
            filter_instance=RedactionFilter(),
        )
        logger.debug(
            "search_papers",
            extra={"event": "search_papers", field: sensitive_value},
        )
        payload = _parse_one(stream)
        assert payload.get(field) == sensitive_value, (
            f"DEBUG record dropped the {field!r} field: "
            f"payload={payload!r}"
        )

    def test_faltings_theorem_brief_example_info(self):
        """Brief AC2 verbatim: a log record with
        ``event="search_papers"`` and ``query="Faltings theorem"`` at
        INFO has ``query`` absent. Captures the exact example so a
        reader of the test file can match it against the milestone
        brief.
        """
        logger, stream = _make_isolated_logger(
            "test.e13_s08.faltings.info",
            level=logging.INFO,
            filter_instance=RedactionFilter(),
        )
        logger.info(
            "search_papers",
            extra={"event": "search_papers", "query": "Faltings theorem"},
        )
        payload = _parse_one(stream)
        assert "query" not in payload
        assert payload["event"] == "search_papers"

    def test_faltings_theorem_brief_example_debug(self):
        """Brief AC3 verbatim: same record at DEBUG includes
        ``query``."""
        logger, stream = _make_isolated_logger(
            "test.e13_s08.faltings.debug",
            level=logging.DEBUG,
            filter_instance=RedactionFilter(),
        )
        logger.debug(
            "search_papers",
            extra={"event": "search_papers", "query": "Faltings theorem"},
        )
        payload = _parse_one(stream)
        assert payload["query"] == "Faltings theorem"

    def test_non_redacted_fields_preserved_at_info(self):
        """The brief explicitly excludes ``paper_id`` and ``chunk_id``
        from redaction (they are identifiers, not content). Confirm
        non-sensitive fields pass through unmodified at INFO.
        """
        logger, stream = _make_isolated_logger(
            "test.e13_s08.identifiers",
            level=logging.INFO,
            filter_instance=RedactionFilter(),
        )
        logger.info(
            "search_papers",
            extra={
                "event": "search_papers",
                "paper_id": "2412.00001",
                "chunk_id": "2412.00001/stmt-12abc",
                "k": 10,
            },
        )
        payload = _parse_one(stream)
        assert payload["paper_id"] == "2412.00001"
        assert payload["chunk_id"] == "2412.00001/stmt-12abc"
        assert payload["k"] == 10


# ===========================================================================
# REDACTED_FIELDS contract
# ===========================================================================


class TestRedactedFieldsContract:
    """Pins the literal contents of :data:`REDACTED_FIELDS` so any
    change to the set is visible in PR review. Adding or removing a
    field is a deliberate security policy decision — this test makes
    that decision explicit rather than letting it pass silently.
    """

    def test_redacted_fields_is_frozenset(self):
        assert isinstance(REDACTED_FIELDS, frozenset)

    def test_redacted_fields_literal_membership(self):
        # If you intend to add a field, update both the constant in
        # ``server/observability/log_filter.py`` AND this assertion
        # in the same commit. The audit doc lists the rationale for
        # each member.
        assert frozenset({
            "query",
            "body_canonical",
            "body_raw_latex",
            "mathml",
        }) == REDACTED_FIELDS


# ===========================================================================
# configure() — root logger installation, DEBUG-warn-once
# ===========================================================================


class TestConfigure:
    """``configure()`` installs the filter on the root logger and
    emits a one-time WARN at DEBUG level.
    """

    @pytest.fixture(autouse=True)
    def _isolate_root(self, monkeypatch):
        """Snapshot + restore the root logger's filters and level
        across each test so configure()'s global side-effect doesn't
        pollute pytest's own logging.
        """
        root = logging.getLogger()
        saved_filters = list(root.filters)
        saved_level = root.level
        _reset_debug_warning_for_tests()
        yield
        # Restore.
        root.filters.clear()
        for f in saved_filters:
            root.addFilter(f)
        root.setLevel(saved_level)
        _reset_debug_warning_for_tests()

    def test_configure_installs_redaction_filter_on_root(self):
        configure("INFO")
        root = logging.getLogger()
        assert any(isinstance(f, RedactionFilter) for f in root.filters), (
            "configure() must install RedactionFilter on the root logger"
        )

    def test_configure_is_idempotent(self):
        """Calling configure() twice must NOT install a duplicate
        filter — the second call sees the existing one and skips."""
        configure("INFO")
        configure("INFO")
        root = logging.getLogger()
        n_filters = sum(
            1 for f in root.filters if isinstance(f, RedactionFilter)
        )
        assert n_filters == 1, (
            f"expected exactly 1 RedactionFilter on root after 2 configure() "
            f"calls; got {n_filters}"
        )

    def test_configure_redacts_child_logger_records_via_root_handler(self):
        """F1 regression (E13_S08 adversary, CRITICAL): the
        production pattern is ``logger = logging.getLogger(__name__)``
        in every server submodule, then ``logger.info(...,
        extra={"query": ...})``. The record propagates up the parent
        chain to the root's HANDLERS — but Python's filter chain
        only runs parent-logger filters on records ORIGINATING at
        the parent, NOT on propagated records.

        The fix installs :class:`RedactionFilter` on every handler
        attached to the root so the filter fires at handler-emit
        time, regardless of which child logger originated the
        record. This test exercises that path: attach a capture
        handler to root BEFORE configure(), call configure(), log
        from a child, and verify the redaction took effect.
        """
        root = logging.getLogger()
        # Install a capture handler BEFORE configure() so configure()
        # finds it and attaches the filter to it (this is what
        # production main.py does: handler from basicConfig() exists
        # before configure() runs).
        stream = io.StringIO()
        capture = logging.StreamHandler(stream)
        capture.setFormatter(JsonFormatter())
        root.addHandler(capture)
        try:
            configure("INFO")
            # Verify the filter actually landed on the handler.
            assert any(
                isinstance(f, RedactionFilter) for f in capture.filters
            ), (
                "F1: configure() must install RedactionFilter on every "
                "existing root handler, not just on the root logger"
            )
            # Now exercise the propagation path: log from a child.
            child = logging.getLogger("server.test.child_propagation")
            child.info(
                "search_papers",
                extra={
                    "event": "search_papers",
                    "query": "Faltings theorem",
                    "body_canonical": "Let X be a smooth projective variety...",
                },
            )
            payload = _parse_one(stream)
            # The redaction must have fired at the handler level.
            assert "query" not in payload, (
                f"F1: child-logger record leaked 'query' at INFO via root "
                f"handler propagation. payload keys: {sorted(payload.keys())}"
            )
            assert "body_canonical" not in payload, (
                "F1: child-logger record leaked 'body_canonical' at INFO"
            )
            # Sanity — the non-redacted fields are still present.
            assert payload["event"] == "search_papers"
            assert payload["name"] == "server.test.child_propagation"
        finally:
            root.removeHandler(capture)

    def test_configure_attaches_filter_to_handlers_added_before_configure(
        self,
    ):
        """Companion to the propagation test: confirm the handler-
        level installation is the path that fires, even when no
        child logger is involved."""
        root = logging.getLogger()
        stream = io.StringIO()
        capture = logging.StreamHandler(stream)
        capture.setFormatter(JsonFormatter())
        root.addHandler(capture)
        try:
            # Pre-condition: no filter yet.
            assert not any(
                isinstance(f, RedactionFilter) for f in capture.filters
            )
            configure("INFO")
            # Post-condition: filter attached.
            assert any(
                isinstance(f, RedactionFilter) for f in capture.filters
            )
        finally:
            root.removeHandler(capture)

    def test_configure_sets_log_level(self):
        configure("WARNING")
        assert logging.getLogger().level == logging.WARNING
        configure("DEBUG")
        assert logging.getLogger().level == logging.DEBUG

    def test_configure_warns_on_debug_level(self, caplog):
        """First DEBUG configure() emits a WARN log so the operator
        sees the deviation from the safe default."""
        with caplog.at_level(
            logging.WARNING, logger="arxmcp.security.logging"
        ):
            configure("DEBUG")
        warns = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and r.name == "arxmcp.security.logging"
        ]
        assert warns, "expected a WARN log on DEBUG-level configure()"
        msg = warns[0].getMessage()
        assert "ARXMCP_LOG_LEVEL=DEBUG" in msg
        # Mentions the redacted fields by name so a grep through the
        # ops log surfaces the exposure surface.
        for field in REDACTED_FIELDS:
            assert field in msg

    def test_configure_does_not_warn_on_info_level(self, caplog):
        with caplog.at_level(
            logging.WARNING, logger="arxmcp.security.logging"
        ):
            configure("INFO")
        warns = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and r.name == "arxmcp.security.logging"
        ]
        assert not warns, (
            f"INFO-level configure() must NOT warn; got: "
            f"{[r.getMessage() for r in warns]}"
        )

    def test_configure_debug_warn_is_one_shot(self, caplog):
        """Repeated DEBUG configure() emits the WARN only once per
        process. Matches the warn-once pattern in
        ``server.observability.sanitize``."""
        # First call: should warn.
        with caplog.at_level(
            logging.WARNING, logger="arxmcp.security.logging"
        ):
            configure("DEBUG")
            n_warns_first = sum(
                1 for r in caplog.records
                if r.levelno == logging.WARNING
                and r.name == "arxmcp.security.logging"
            )
            caplog.clear()
            # Second call at same level: should NOT warn again.
            configure("DEBUG")
            n_warns_second = sum(
                1 for r in caplog.records
                if r.levelno == logging.WARNING
                and r.name == "arxmcp.security.logging"
            )
        assert n_warns_first >= 1
        assert n_warns_second == 0, (
            "DEBUG warn must be one-shot per process; second configure() "
            "emitted a duplicate WARN"
        )


# ===========================================================================
# JsonFormatter — sanity tests
# ===========================================================================


class TestJsonFormatter:
    """The formatter is the test-time path for verifying
    redaction. Pin its contract so a future refactor doesn't break
    the redaction tests above.
    """

    def test_emits_valid_json(self):
        logger, stream = _make_isolated_logger(
            "test.e13_s08.formatter.json", level=logging.INFO
        )
        logger.info("event_name", extra={"event": "event_name", "k": 1})
        payload = _parse_one(stream)
        assert payload["event"] == "event_name"
        assert payload["k"] == 1

    def test_renames_levelname_to_level(self):
        """Threat model § Logging requires a ``level`` field; stdlib
        uses ``levelname``. The formatter promotes it.
        """
        logger, stream = _make_isolated_logger(
            "test.e13_s08.formatter.level", level=logging.WARNING
        )
        logger.warning("uhoh", extra={"event": "uhoh"})
        payload = _parse_one(stream)
        assert payload["level"] == "WARNING"

    def test_emit_does_not_raise_on_non_json_value(self):
        """``default=str`` keeps the formatter robust to exotic
        attribute types so a stray ``extra={"obj": SomeObject(...)}``
        doesn't drop the log line."""
        class NotJsonable:
            def __repr__(self) -> str:
                return "<NotJsonable>"

        logger, stream = _make_isolated_logger(
            "test.e13_s08.formatter.exotic", level=logging.INFO
        )
        logger.info("evt", extra={"event": "evt", "obj": NotJsonable()})
        payload = _parse_one(stream)
        assert payload["obj"] == "<NotJsonable>"


# ===========================================================================
# Audit-doc presence
# ===========================================================================


class TestAuditDocPresence:
    """The audit doc lives at
    ``.claude/docs/security-observability-logging.md`` matching the
    E13_S01–S07 precedent. The brief asks for
    ``docs/observability/log-redaction.md`` but that path is rejected
    by CLAUDE.md §1.
    """

    def test_audit_doc_exists(self):
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[2]
        audit = (
            repo_root / ".claude" / "docs"
            / "security-observability-logging.md"
        )
        assert audit.is_file(), f"audit doc missing at {audit}"
        body = audit.read_text(encoding="utf-8")
        # Must surface the four redacted fields by name so a reader
        # can grep them.
        for field in REDACTED_FIELDS:
            assert field in body
        assert "ARXMCP_LOG_LEVEL" in body
        assert "Threat" in body
