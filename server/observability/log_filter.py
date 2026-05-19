"""E13_S08 — Threat-8 logging redaction.

Sensitive fields — full query text, chunk bodies, raw LaTeX, MathML —
must not appear in log records at INFO level or above. They are
permitted at DEBUG level only, where the developer has explicitly
opted in via ``ARXMCP_LOG_LEVEL=DEBUG``.

The :class:`RedactionFilter` is a stdlib ``logging.Filter`` subclass
that mutates ``record.__dict__`` in place, deleting each entry in
:data:`REDACTED_FIELDS`. It runs BEFORE handlers / formatters in the
Python logging architecture (logger → filters → handlers →
formatters), so every downstream consumer — including any future
JSON formatter, OTel log exporter, or stdout text formatter — sees
the already-redacted record. There is no race window where an
un-redacted record can escape.

The filter is installed in
:func:`server.observability.logging_setup.configure` on the root
logger so that every logger created via ``logging.getLogger(__name__)``
inherits the same redaction without per-module wiring.

**Threat verbatim** (``.claude/notes/08-security-observability-ops.md``
§ Logging):

    > Structured JSON logs to stdout (12-factor). One line per event.
    > Required fields on every log line: timestamp (ISO 8601 UTC),
    > level (DEBUG / INFO / WARN / ERROR), logger, mcp.session_id
    > (when applicable), request_id (when applicable), event (short
    > event name), msg (human-readable).
    >
    > Sensitive fields (full query text, chunk bodies) are logged at
    > DEBUG only, never at INFO or above.

**Scope (per brief):** only top-level ``record.__dict__`` keys are
redacted. Out of scope: nested dict payloads
(``extra={"context": {"query": ...}}``), ``record.args`` tuple values,
and pre-composed message templates (``logger.info(f"q={q}")``). The
audit doc spells out the caller-side contract that prevents these
leaks.
"""

from __future__ import annotations

import logging

#: The frozen allowlist of attribute names that ``RedactionFilter``
#: strips from ``record.__dict__`` when the record's level is INFO or
#: above. Modifying this set requires a deliberate code change and a
#: paired test update — there is intentionally no env-var override.
#:
#: Any new sensitive field added to a log call site MUST be added
#: here in the same commit. The contract is enforced by
#: ``tests/security/test_log_redaction.py::TestRedactedFieldsContract``.
REDACTED_FIELDS: frozenset[str] = frozenset({
    "query",
    "body_canonical",
    "body_raw_latex",
    "mathml",
})


class RedactionFilter(logging.Filter):
    """Redact sensitive fields from log records emitted at INFO+ level.

    At ``DEBUG`` level (and lower), records pass through unchanged —
    the developer has explicitly opted into full disclosure via
    ``ARXMCP_LOG_LEVEL=DEBUG``. At ``INFO`` and above, every key in
    :data:`REDACTED_FIELDS` is removed from ``record.__dict__`` if
    present. The filter ALWAYS returns ``True`` (records are never
    dropped — they are only redacted).

    The mutation is intentionally destructive: the LogRecord is the
    only object passed to downstream handlers, so removing the
    attribute makes it invisible to JSON serializers, text formatters,
    and OTel exporters alike. No copy is kept.

    The filter is process-safe under stdlib ``logging``'s threading
    model: each ``Handler.emit`` call holds the handler's lock, and
    the filter chain runs synchronously before any handler reads the
    record's attributes. Two handlers sharing one record both see the
    same (redacted) attribute snapshot.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        """Mutate ``record.__dict__`` in place and keep the record.

        :param record: the candidate log record. Standard LogRecord
            attributes are populated by ``Logger.makeRecord``; any
            ``extra={...}`` keys passed at the call site are also
            attached as direct attributes on ``record.__dict__``.

        :returns: ``True`` — records are never dropped by this filter.
            (The redaction is the entire effect; rejecting the record
            would also hide the ``event`` / ``msg`` fields the operator
            relies on for incident response.)
        """
        if record.levelno >= logging.INFO:
            d = record.__dict__
            for key in REDACTED_FIELDS:
                # ``pop`` is the safe form — present-or-absent is
                # tolerated. Most records will have none of these
                # keys, and the worst case (all four present) is a
                # bounded handful of attribute deletes per record.
                d.pop(key, None)
        return True


__all__ = ["REDACTED_FIELDS", "RedactionFilter"]
