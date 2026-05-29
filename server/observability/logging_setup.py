"""E13_S08 — root logger configuration with Threat-8 redaction.

Provides :func:`configure` — the single entry point for the server's
logging setup. Called from :mod:`server.main` after :class:`Config`
loads, this function:

1. Installs :class:`server.observability.log_filter.RedactionFilter`
   on the root logger so every ``logging.getLogger(__name__)`` in the
   process inherits the redaction without per-module wiring.
2. Sets the root logger level from ``cfg.log_level`` (which honors
   ``ARXMCP_LOG_LEVEL``, defaulting to ``"INFO"``).
3. Emits a one-time WARN log when the level is ``DEBUG``, mirroring
   the warn-once pattern in :mod:`server.observability.sanitize`. The
   WARN makes the security trade-off visible in the operational log
   so an operator can spot the misconfiguration in retrospect even if
   they forgot they set the env var.

Also exports :class:`JsonFormatter` as importable infrastructure for
tests (and for any future production-side adoption of JSON log
output). The formatter is NOT installed by default — the redaction
works regardless of the output format, and changing the default
stdout shape is out of scope for an audit milestone.

**Naming note (deviation from brief).** The brief calls for this file
to be named ``server/observability/logging.py``. We use
``logging_setup.py`` instead to keep the module's name distinct from
the stdlib :mod:`logging` package — Python 3 absolute imports already
make ``import logging`` resolve to the stdlib from anywhere in this
package, but a same-named module is still a reader-confusion hazard.
The rename is documented in
``.claude/docs/security-observability-logging.md`` and the
``implementation-summary.md`` for E13_S08.
"""

from __future__ import annotations

import json
import logging

from server.observability.log_filter import REDACTED_FIELDS, RedactionFilter

logger = logging.getLogger("arxmcp.security.logging")

#: One-shot guard for the DEBUG-level WARN log. Re-calling
#: ``configure`` (e.g. from tests that monkeypatch the config) emits
#: the WARN only on the first DEBUG-level configure, matching the
#: warn-once pattern in :mod:`server.observability.sanitize`.
_debug_warning_emitted = False

#: LogRecord attributes that :class:`JsonFormatter` excludes from
#: its output. These are bookkeeping fields the stdlib populates on
#: every record; emitting them inflates JSON without informing the
#: operator. We intentionally KEEP ``levelname``, ``name``, ``message``,
#: ``asctime`` etc. — those are the threat-model "required fields on
#: every log line" listed in ``.claude/notes/08-security-observability-ops.md``
#: § Logging.
_FORMATTER_INTERNAL_ATTRS: frozenset[str] = frozenset({
    "args",
    "msg",
    "exc_info",
    "exc_text",
    "stack_info",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "pathname",
    "filename",
    "module",
    "funcName",
    "lineno",
    "created",
})


class JsonFormatter(logging.Formatter):
    """Emit each log record as one line of JSON.

    Reads ``record.__dict__`` and ``json.dumps``-es a deterministic
    subset. The output is keyed alphabetically (``sort_keys=True``) so
    log diffs across runs are stable and human-grep-able.

    The formatter runs AFTER :class:`RedactionFilter`, so any
    sensitive attribute the filter stripped is already gone from
    ``record.__dict__`` by the time :meth:`format` reads it. The
    formatter therefore does NOT re-implement the redaction — it
    relies on the filter being installed on the root logger via
    :func:`configure`.

    Non-JSON-serializable objects (e.g. an exception value passed as
    a kwarg) are coerced via ``default=str`` so the formatter never
    raises during an emit. The cost is a less-precise serialization
    for exotic types; the trade-off is essential because a formatter
    that raises would drop the log line entirely.
    """

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        # Compute ``message`` the standard way — stdlib formats
        # ``record.msg % record.args`` lazily, and JSON consumers
        # expect the formatted text in a ``message`` key.
        record.message = record.getMessage()
        payload = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _FORMATTER_INTERNAL_ATTRS
        }
        # ``levelname`` is the operator-facing level string; rename
        # to the threat-model's required field name ``level``. We
        # keep both because some downstream tooling expects the
        # stdlib name.
        if "levelname" in payload:
            payload["level"] = payload["levelname"]
        return json.dumps(payload, default=str, sort_keys=True)


def configure(log_level: str, log_format: str = "json") -> None:
    """Install :class:`RedactionFilter` on every root-logger handler
    (and on the root logger itself for direct-root emits), optionally
    install :class:`JsonFormatter` on those same handlers, and set the
    root log level from ``log_level``.

    F1 rectification (E13_S08 adversary): Python's logging filter
    chain does NOT run parent-logger filters on records propagated
    from child loggers — only the originating logger's filters and
    the receiving handler's filters fire. Installing
    :class:`RedactionFilter` on the root logger alone therefore
    leaves every ``logging.getLogger(__name__)`` child logger
    UN-redacted at INFO+, defeating the entire mitigation. The fix
    is to attach the filter to every handler the root logger owns,
    so that when a child logger's record propagates up and hits the
    handler, the filter runs at handler-emit time.

    The filter is also attached to the root logger itself so that
    records logged DIRECTLY from the root (rare but possible —
    ``logging.info(...)`` without a child logger) are also redacted
    by the originating-logger filter chain.

    The function is idempotent — repeated calls re-discover existing
    handlers and skip any that already have a :class:`RedactionFilter`.
    New handlers added AFTER ``configure()`` runs will NOT be
    auto-protected; callers that install additional handlers post-
    configure must either re-call ``configure()`` or install the
    filter themselves. The audit doc spells out this contract.

    Safe to call multiple times.

    :param log_level: a stdlib logging level name (``"DEBUG"``,
        ``"INFO"``, ``"WARNING"``, ``"ERROR"``, ``"CRITICAL"``).
        Passed verbatim to ``logging.getLogger().setLevel`` so any
        string the stdlib accepts is also accepted here.
    :param log_format: ``"json"`` (default, 12-factor) installs
        :class:`JsonFormatter` on every root handler so each record is
        emitted as one structured JSON line; ``"text"`` leaves the
        existing human-readable formatter in place. Either way the
        :class:`RedactionFilter` is installed first, so the format
        choice never affects redaction.
    """
    global _debug_warning_emitted

    root = logging.getLogger()

    # F1: attach the filter to every handler. This is the load-bearing
    # install — handler filters fire on propagated child-logger
    # records, which is the production pattern (24+ modules use
    # ``logging.getLogger(__name__)``).
    #
    # corpus-integrity-observability-e2: when log_format == "json", install
    # JsonFormatter on the SAME handler that just got the RedactionFilter —
    # NEVER a new handler. A second StreamHandler added post-configure would
    # bypass the filter loop and emit query/body fields un-redacted at INFO+
    # (Threat 8). Filter-then-format on one handler keeps the chain intact.
    want_json = str(log_format).strip().lower() == "json"
    for handler in root.handlers:
        if not any(isinstance(f, RedactionFilter) for f in handler.filters):
            handler.addFilter(RedactionFilter())
        if want_json:
            handler.setFormatter(JsonFormatter())

    # Defense-in-depth: also attach to the root logger so direct-root
    # emits (``logging.info(...)`` without a named child) are
    # redacted by the originating-logger chain. This redundant
    # install has zero cost on records already redacted by the
    # handler filter (subsequent ``dict.pop(key, None)`` calls are
    # no-ops).
    if not any(isinstance(f, RedactionFilter) for f in root.filters):
        root.addFilter(RedactionFilter())

    root.setLevel(log_level)

    # Emit the DEBUG warning AFTER the filter is installed so that
    # the warning itself is subject to the same logging discipline as
    # every other record. The warning carries no sensitive fields, so
    # the filter is a no-op on it.
    if not _debug_warning_emitted and str(log_level).upper() == "DEBUG":
        _debug_warning_emitted = True
        logger.warning(
            "ARXMCP_LOG_LEVEL=DEBUG: sensitive fields %s are NOT "
            "redacted from INFO+ records under this configuration. "
            "Do not run this in production. See "
            ".claude/docs/security-observability-logging.md.",
            sorted(REDACTED_FIELDS),
        )


def _reset_debug_warning_for_tests() -> None:
    """Clear the :data:`_debug_warning_emitted` one-shot guard.

    Test-only helper; production callers MUST NOT use this. Tests
    that exercise :func:`configure` repeatedly need the WARN to fire
    on each invocation to assert the contract; the production
    one-shot is the correct behavior so the operator's startup log
    does not get spammed by repeated configure calls.
    """
    global _debug_warning_emitted
    _debug_warning_emitted = False


__all__ = [
    "JsonFormatter",
    "configure",
]
