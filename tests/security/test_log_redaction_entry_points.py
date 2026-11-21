"""Threat-8 redaction holds on every way the server is started.

Each case runs in a fresh interpreter, because which logging handlers exist
depends on what ran before the app was built, and pytest's own handlers would
stand in for the ones under test. A record logged with a redacted field
must reach every handler without it: on the root logger, on uvicorn's own
loggers and on the server's.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SECRET = "SECRET-QUERY-TEXT"

#: Logs one record carrying ``query`` through each logger and reports, per
#: logger, whether the record still carried it after its handlers ran.
_PROBE = f"""
import json
import logging

def probe():
    seen = {{}}
    access_args = ("127.0.0.1:1", "GET", "/x", "1.1", 200)
    for name, msg, args in (
        ("", "root line", ()),
        ("uvicorn.access", '%s - "%s %s HTTP/%s" %d', access_args),
        ("uvicorn.error", "uvicorn line", ()),
        ("server.probe", "server line", ()),
    ):
        lg = logging.getLogger(name)
        record = lg.makeRecord(
            lg.name, logging.WARNING, "probe", 1, msg, args, None,
            extra={{"query": "{_SECRET}"}},
        )
        lg.handle(record)
        seen[name or "root"] = hasattr(record, "query")
    root = logging.getLogger()
    from server.observability.log_filter import RedactionFilter
    filters = [
        sum(isinstance(f, RedactionFilter) for f in h.filters)
        for lg in [root, *(
            v for v in logging.Logger.manager.loggerDict.values()
            if isinstance(v, logging.Logger)
        )]
        for h in lg.handlers
    ]
    return {{
        "query_survived": seen,
        "root_handlers": len(root.handlers),
        "root_level": logging.getLevelName(root.level),
        "json_format": [
            type(h.formatter).__name__ == "JsonFormatter" for h in root.handlers
        ],
        "filters_per_handler": filters,
    }}
"""

_UVICORN_APP_FORM = _PROBE + """
import uvicorn

config = uvicorn.Config("server.main:app")
config.load()
print("RESULT " + json.dumps(probe()))
"""

_CLI_FORM = _PROBE + """
import uvicorn

import server.cli as cli

def fake_run(app, **kwargs):
    config = uvicorn.Config(app, **kwargs)
    config.load()
    print("RESULT " + json.dumps(probe()))

uvicorn.run = fake_run
raise SystemExit(cli.main())
"""

_CONFIGURED_BEFORE_IMPORT = _PROBE + """
from server.observability.logging_setup import configure

logging.basicConfig(level="INFO")
configure("WARNING", "text")
import server.main  # noqa: F401
print("RESULT " + json.dumps(probe()))
"""


def _run(code: str) -> tuple[dict, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ARXMCP_")}
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(_REPO_ROOT), env.get("PYTHONPATH", "")) if p
    )
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        cwd=_REPO_ROOT,
        env=env,
        input="",
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, proc.stdout[-2000:] + proc.stderr[-2000:]
    return json.loads(lines[-1].removeprefix("RESULT ")), proc.stdout + proc.stderr


_ALL_REDACTED = {
    "root": False,
    "uvicorn.access": False,
    "uvicorn.error": False,
    "server.probe": False,
}


def test_uvicorn_app_form_redacts_on_every_logger() -> None:
    """``uvicorn server.main:app``: uvicorn's default logging config, then
    the import of the module-level app, and nothing else."""
    result, output = _run(_UVICORN_APP_FORM)
    assert result["query_survived"] == _ALL_REDACTED
    assert _SECRET not in output
    assert "root line" in output
    assert "server line" in output
    assert result["root_handlers"] == 1
    assert all(n == 1 for n in result["filters_per_handler"])


def test_cli_form_redacts_once_and_keeps_its_own_format() -> None:
    """The console script imports the module-level app first, then
    configures logging itself: one handler, one filter each."""
    result, output = _run(_CLI_FORM)
    assert result["query_survived"] == _ALL_REDACTED
    assert _SECRET not in output
    assert result["root_handlers"] == 1
    assert result["json_format"] == [True]
    assert all(n == 1 for n in result["filters_per_handler"])


def test_importing_the_app_keeps_an_existing_level_and_format() -> None:
    """Logging configured first: importing the app must not change the
    level or format chosen, nor add a handler or a second filter."""
    result, output = _run(_CONFIGURED_BEFORE_IMPORT)
    assert result["query_survived"] == _ALL_REDACTED
    assert _SECRET not in output
    assert result["root_level"] == "WARNING"
    assert result["json_format"] == [False]
    assert result["root_handlers"] == 1
    assert all(n == 1 for n in result["filters_per_handler"])
