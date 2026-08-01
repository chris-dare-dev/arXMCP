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
import sys

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

    from server.config import Config
    from server.main import _scan_unknown_arxmcp_env_vars

    # Configure logging BEFORE Config() so the FATAL log lands on stderr
    # even when the failure is in Config() itself.
    logging.basicConfig(level=os.environ.get("ARXMCP_LOG_LEVEL", "INFO"))
    try:
        cfg = Config()
        _scan_unknown_arxmcp_env_vars(cfg)
    except Exception as exc:
        logger.error("FATAL during config load: %s", exc)
        sys.stderr.write(f"FATAL: {exc}\n")
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
