"""``arxmcp-server`` console-script entry point (issue #206).

``docs/install.md`` has told every new operator to verify their install
with ``arxmcp-server --help`` since the doc was written, but
``pyproject.toml`` carried no ``[project.scripts]`` entry for it at all —
only ``arxmcp-shim``. The very first verification step in the documented
install path failed with "command not found". This module is the missing
half; ``pyproject.toml`` maps ``arxmcp-server`` onto :func:`main`.

**Why this lives here and not in** :mod:`server.main`. ``server/main.py``
builds the FastAPI app at module scope::

    app = _build_module_app() if __name__ != "__main__" else None

Hanging the console script off ``server.main:main`` would therefore run
:func:`server.main.create_app` — LanceDB handles, the MCP mount, the
``/ui/static`` StaticFiles mount — as an import side effect of
``arxmcp-server --help``, and would exit non-zero on any config error
before argparse ever saw the ``--help``. This module imports
:mod:`server.main` lazily, *inside* :func:`main`, so ``--help`` and
``--version`` are pure argparse and cost nothing.

**Config comes from the environment, not from flags.** The CLI surface is
deliberately minimal: bind host/port, data dir, log level and every other
knob are ``ARXMCP_*`` env vars parsed by :class:`server.config.Config`
(and an unknown ``ARXMCP_*`` var is a startup error — see
:func:`server.main._scan_unknown_arxmcp_env_vars`). Adding flags here
would create a second source of truth that the container, the systemd
unit and ``make up`` would all have to mirror.

``python -m server.main`` remains the equivalent invocation and is what
``docker/Dockerfile.server`` and ``make up`` use; it delegates here so the
two entry points cannot drift.
"""

from __future__ import annotations

import argparse
import logging
import os

logger = logging.getLogger(__name__)


_EPILOG = """\
configuration:
  arxmcp-server takes its configuration from ARXMCP_* environment
  variables, not from command-line flags. The most common ones:

    ARXMCP_BIND_HOST      loopback address to bind (default 127.0.0.1;
                          a non-loopback value is REJECTED at parse time
                          unless ARXMCP_UNSAFE_NETWORK_BIND=1)
    ARXMCP_BIND_PORT      TCP port (default 7733)
    ARXMCP_DATA_DIR       runtime state root (default var/arxmcp)
    ARXMCP_LOG_LEVEL      INFO / DEBUG / WARNING (default INFO)
    ARXMCP_LOG_FORMAT     json (default) or text
    ARXMCP_BOOTSTRAP_MODE 1 to boot with no corpus present, for a
                          first-run install where ingest has not run yet

  An unrecognized ARXMCP_* variable is a startup ERROR, not a warning --
  a typo'd knob must never look like it took effect.

health:
  /healthz  always 200 once the process is listening
  /readyz   200 once BGE-M3 and LanceDB are warm
  /status   health+json operability summary

equivalent invocation:
  python -m server.main

See docs/install.md for the full install and Claude Code registration
procedure.
"""


def _version() -> str:
    """Resolve the installed distribution version.

    Falls back to ``"unknown"`` for a source checkout that was never
    ``pip install``-ed, so ``--version`` cannot be the thing that
    crashes a fresh clone.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("arxmcp")
    except PackageNotFoundError:
        return "unknown (arxmcp is not installed in this environment)"
    except Exception:  # pragma: no cover - defensive
        return "unknown"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arxmcp-server",
        description=(
            "Run the long-running arXMCP MCP server (FastAPI + Streamable "
            "HTTP). Binds 127.0.0.1:7733 by default."
        ),
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"arxmcp-server {_version()}",
    )
    return parser


#: Set once a config failure has been reported to the operator (#475).
#:
#: A config failure is fatal, so "once per process" is the whole lifetime.
_CONFIG_ERROR_EMITTED = False


def emit_config_error(exc: Exception, *, context: str) -> str:
    """Report a startup config failure to the operator EXACTLY once.

    #475 round 2. The root-cause fix — moving `from server.main import ...`
    inside the try, so a bad `ARXMCP_BIND_HOST` is caught rather than raising
    during the import — was correct and stands. What was not checked is what
    an operator actually sees, which is what the ticket asked for. Measured
    on `arxmcp-server` with `ARXMCP_BIND_HOST=0.0.0.0`: an unrelated INFO
    line, then the SAME message four times.

    Two entry points both catch it, because both are legitimately outermost
    on their own path: `server.main._build_module_app` for `uvicorn
    server.main:app`, and `cli.main` for the console script. On the console
    script BOTH run, since importing `server.main` executes `create_app()` at
    module scope — that import is exactly what the root-cause fix moved
    inside the try. Rather than have either guess whether it is outermost,
    the first one to report wins and the rest are silent.

    One line, through `logging`: a bare `sys.stderr.write` bypasses the
    `RedactionFilter` that E13_S08 installs on the root logger, and this
    message is built from config values.
    """
    global _CONFIG_ERROR_EMITTED  # noqa: PLW0603 — process-lifetime latch
    message = _format_config_error(exc)
    if not _CONFIG_ERROR_EMITTED:
        _CONFIG_ERROR_EMITTED = True
        logger.error("FATAL during %s: %s", context, message)
    return message


def _format_config_error(exc: BaseException) -> str:
    """One actionable line per bad field, without echoing the input.

    Issue #475. ``str(ValidationError)`` includes an ``input_value`` dump of
    everything pydantic was given, which for ``Config`` is every path the
    server knows about. Callers want to know WHICH field is wrong and WHY.

    Falls back to ``str(exc)`` for anything that is not a pydantic error —
    including ``_scan_unknown_arxmcp_env_vars``'s ValueError, whose message is
    already written for an operator and must pass through intact.
    """
    errors = getattr(exc, "errors", None)
    if not callable(errors):
        return str(exc)
    try:
        details = errors()
    except Exception:  # noqa: BLE001 — never let formatting mask the error
        return str(exc)
    lines = []
    for detail in details:
        location = ".".join(str(part) for part in detail.get("loc", ())) or "config"
        lines.append(f"{location}: {detail.get('msg', 'invalid value')}")
    return "; ".join(lines) if lines else str(exc)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``arxmcp-server`` console script.

    Returns a process exit code; ``0`` is only reachable after uvicorn's
    own loop returns (i.e. on a clean shutdown).

    The body below is the former ``if __name__ == "__main__":`` block of
    ``server/main.py``, moved verbatim so the console script and
    ``python -m server.main`` cannot diverge.
    """
    _build_parser().parse_args(argv)

    # IS3+IS4 fix: this path uses Config to source the bind host/port, so
    # ``ARXMCP_BIND_HOST`` / ``ARXMCP_BIND_PORT`` are honored. Use this
    # entry point rather than the bare ``uvicorn server.main:app`` form
    # for env-var-aware binding.
    #
    # E06_S05: wrap Config() + the env-var scan so a bad bind host (or any
    # other config validation failure) emits a FATAL log AND exits with
    # code 1, not a multi-screen pydantic stack. This mirrors
    # ``server.main._build_module_app``'s wrapping for the uvicorn-CLI
    # path so both entry points fail identically. Closes the brief AC:
    # "Starting server with ARXMCP_BIND_HOST=0.0.0.0 exits with code 1 and
    # a log message."
    import uvicorn

    # Configure logging BEFORE Config() so the FATAL log lands on stderr
    # even when the failure is in Config() itself.
    logging.basicConfig(level=os.environ.get("ARXMCP_LOG_LEVEL", "INFO"))
    try:
        # issue #475: `from server.main import ...` MUST be inside the try.
        # Importing server.main executes create_app() at module scope, which
        # constructs Config() — so a bad ARXMCP_BIND_HOST raised during the
        # IMPORT, before the guarded Config() below was ever reached, and the
        # pydantic traceback escaped this handler entirely. The guard looked
        # correct and covered nothing.
        from server.config import Config
        from server.main import _scan_unknown_arxmcp_env_vars

        cfg = Config()
        _scan_unknown_arxmcp_env_vars(cfg)
    except Exception as exc:
        # issue #475: pydantic's ValidationError stringifies the WHOLE input,
        # so the 0.0.0.0 rejection printed the entire Config dict — data_dir
        # and every other path included — to stderr. The field errors are the
        # actionable part; the input echo is noise that buries them and puts
        # the operator's filesystem layout in any pasted error report.
        emit_config_error(exc, context="config load")
        return 1

    # E13_S08 Threat 8 — install the RedactionFilter on the root logger AND
    # re-apply the level from Config (which may differ from the env-var
    # fallback used before Config() loaded). The filter strips
    # REDACTED_FIELDS (query, body_canonical, body_raw_latex, mathml) from
    # every log record at INFO+ level so accidental leakage of paper
    # content into the operational log is blocked at the source. See
    # ``.claude/docs/security-observability-logging.md``.
    from server.observability.logging_setup import configure as _configure_logging

    # corpus-integrity-observability-e2: cfg.log_format ("json" default,
    # 12-factor) selects the JsonFormatter, installed on the same
    # redaction-filtered handler inside configure().
    _configure_logging(cfg.log_level, cfg.log_format)
    # E13_S05 Threat 5 — emit a WARN log at startup if the operator has
    # enabled the unsafe-network-bind escape hatch. This makes the security
    # trade-off VISIBLE in the operational log so an operator can spot the
    # misconfiguration in retrospect even if they forgot they set the env
    # var.
    if cfg.unsafe_network_bind:
        logger.warning(
            "ARXMCP_UNSAFE_NETWORK_BIND=1 is set; server binding to %r "
            "(non-loopback). Container deployments only — the host-side "
            "port mapping MUST still pin to 127.0.0.1. See "
            ".claude/docs/security-binding.md.",
            cfg.bind_host,
        )
    # E13_S07c Threat 7 — INFO log when CA pinning is on so the operator
    # sees the opt-in at startup. The bundle path was already validated by
    # ``Config.validate_arxiv_ca_bundle`` (fail-closed); this log line just
    # makes the active pin visible in the operational log.
    if cfg.pin_arxiv_ca:
        from server.ssl_pin import resolve_arxiv_ca_bundle

        logger.info(
            "ARXMCP_PIN_ARXIV_CA=1 set; using pinned CA bundle at %s "
            "for arxiv.org / ar5iv.labs.arxiv.org / export.arxiv.org "
            "fetches (Threat 7 mitigation #2). Refresh via "
            "`make refresh-arxiv-ca`.",
            resolve_arxiv_ca_bundle(cfg),
        )
        # E13_S07c v1 caller-side coverage caveat: the API surface is wired
        # (try_cache + fetch_eprint accept ssl_context) but the existing
        # production callers (bulk_ingest, fetch_seed, fetch_one_paper,
        # notebook_fetch) do NOT auto-thread the context. Surface this WARN
        # so an operator who sets the flag sees the gap explicitly rather
        # than assuming bulk ingest is pinned. Full caller-side wiring is a
        # follow-up; see .claude/docs/security-threat-7-audit.md.
        logger.warning(
            "ARXMCP_PIN_ARXIV_CA=1 set, BUT existing production "
            "callers (ingest/bulk_ingest.py, tools/fetch_seed.py, "
            "tools/fetch_one_paper.py, tools/notebook_fetch.py) do "
            "NOT auto-thread the SSLContext. Bulk-ingest paths will "
            "still use the system trust store. See "
            ".claude/docs/security-threat-7-audit.md \"Caller-side "
            "coverage\" for the workaround. Tracked as follow-up."
        )
    logger.info("Starting arxmcp-server on %s:%d", cfg.bind_host, cfg.bind_port)
    uvicorn.run(
        "server.main:app",
        host=cfg.bind_host,
        port=cfg.bind_port,
        lifespan="on",
        log_config=None,
    )
    return 0


__all__ = ["main"]
