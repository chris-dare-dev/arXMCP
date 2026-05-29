"""Render a one-line human status from a /status health+json body on stdin.

notebook-ops-hardening-m4. Backs `make status`:

    curl -sf .../status | python3 tools/status_line.py
    -> "READY | corpus v7 | 3 notebooks"   (pass)
    -> "DEGRADED | corpus v7 | 3 notebooks"  (warn)
    -> "DOWN | corpus v? | ? notebooks"      (fail body)

Parsing is defensive: a missing/`warn`/`fail` body, an absent check, or a
non-numeric observedValue all degrade to ``?`` rather than raising — `make
status` must never crash on a degraded server.
"""

from __future__ import annotations

import json
import sys

_LABELS = {"pass": "READY", "warn": "DEGRADED", "fail": "DOWN"}


def _observed(checks: dict, key: str) -> object:
    """First ``observedValue`` under ``checks[key]`` (a health+json array)."""
    entries = checks.get(key) if isinstance(checks, dict) else None
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and "observedValue" in entry:
                value = entry["observedValue"]
                return "?" if value is None else value
    return "?"


def format_status_line(payload: dict) -> str:
    """Build the human status line from a parsed /status body."""
    raw_status = str(payload.get("status", "?")).lower()
    label = _LABELS.get(raw_status, raw_status.upper() or "?")
    checks = payload.get("checks", {})
    corpus = _observed(checks, "corpus:version")
    notebooks = _observed(checks, "notebooks:count")
    return f"{label} | corpus v{corpus} | {notebooks} notebooks"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        print("DOWN: /status returned an unparseable body")
        return 1
    if not isinstance(payload, dict):
        print("DOWN: /status body was not a JSON object")
        return 1
    print(format_status_line(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
