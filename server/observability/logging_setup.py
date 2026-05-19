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


def configure(log_level: str) -> None:
    """Install :class:`RedactionFilter` on the root logger and set
    the root log level from ``log_level``.

    Safe to call multiple times — the filter installation is
    idempotent (a duplicate :class:`RedactionFilter` would re-run
    deletion of already-absent keys, a no-op) and the DEBUG WARN
    fires only on the first DEBUG configure per process via the
    :data:`_debug_warning_emitted` one-shot guard.

    :param log_level: a stdlib logging level name (``"DEBUG"``,
        ``"INFO"``, ``"WARNING"``, ``"ERROR"``, ``"CRITICAL"``).
        Passed verbatim to ``logging.getLogger().setLevel`` so any
        string the stdlib accepts is also accepted here.
    """
    global _debug_warning_emitted

    root = logging.getLogger()

    # Idempotent: only add the filter if one of the same class isn't
    # already attached. Two attached filters wouldn't be incorrect
    # (the second is a no-op on an already-redacted record) but the
    # extra dispatch cost is avoidable.
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
