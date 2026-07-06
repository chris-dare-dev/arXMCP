#!/usr/bin/env python3
"""Advance capability-scout state to the next phase, or read/write a field.

Usage:
  checkpoint.py <ID> <new-phase>             # advance state
  checkpoint.py <ID> --get <field>           # read a top-level field
  checkpoint.py <ID> --set <field>=<json>    # set a top-level field (json-parsed)
  checkpoint.py <ID> --append <field>=<json> # append json value to a list field

Phase advancement is validated against the state machine:

  init -> survey-running -> survey-complete
       -> synthesize-running -> synthesize-complete
       -> challenge-running -> challenge-complete
       -> prioritize-running -> complete

Refuses backward transitions and skipped phases.  Writes atomically.

Mirrors .claude/scripts/milestone-pipeline-checkpoint.py — see that for the
canonical state-machine pattern.  ``--append`` is specific to capability-scout
(the survey phase returns up to 5 briefs, each appended one-by-one as the
orchestrator dispatches the sub-agents).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    from datetime import UTC, datetime
except ImportError:  # pragma: no cover — Python <3.11 fallback
    from datetime import datetime, timezone  # noqa: UP017

    UTC = timezone.utc  # type: ignore[assignment]  # noqa: UP017

PHASE_ORDER = [
    "init",
    "survey-running",
    "survey-complete",
    "synthesize-running",
    "synthesize-complete",
    "challenge-running",
    "challenge-complete",
    "prioritize-running",
    "complete",
]


def _state_path(sid: str) -> Path:
    # Path: .claude/scripts/capability-scout/checkpoint.py
    #       └── parents[3] = repo root
    #
    # capability-scout follows the command-based architecture (slash command +
    # agents + references + scripts), so the scripts directory lives directly
    # under .claude/scripts/.  This is the same depth as arXMCP's
    # milestone-pipeline checkpoint.py (.claude/scripts/),
    # which also resolves the repo root via parents[3].
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / ".claude" / "notes" / "capability-scouts" / sid / "state.json"


def _load(state_path: Path) -> dict:
    if not state_path.exists():
        sys.exit(f"state.json not found at {state_path} — run init-scout.sh first")
    return json.loads(state_path.read_text())


def _save_atomic(state_path: Path, state: dict) -> None:
    tmp = state_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, state_path)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def advance(sid: str, new_phase: str) -> None:
    if new_phase not in PHASE_ORDER:
        sys.exit(f"unknown phase: {new_phase}. Valid: {', '.join(PHASE_ORDER)}")
    sp = _state_path(sid)
    state = _load(sp)
    cur = state["phase"]
    cur_idx = PHASE_ORDER.index(cur)
    new_idx = PHASE_ORDER.index(new_phase)
    if new_idx <= cur_idx:
        sys.exit(f"refusing backward/same transition: {cur} -> {new_phase}")
    if new_idx - cur_idx > 1:
        sys.exit(f"refusing skipped transition: {cur} -> {new_phase} (must advance one step)")
    now = _now()
    state["phase"] = new_phase
    state["updated_at"] = now
    state["phase_history"].append({"phase": new_phase, "at": now})
    _save_atomic(sp, state)
    print(f"{sid}: {cur} -> {new_phase} @ {now}")


def get_field(sid: str, field: str) -> None:
    state = _load(_state_path(sid))
    if field not in state:
        sys.exit(f"unknown field: {field}. Valid: {', '.join(state.keys())}")
    val = state[field]
    if isinstance(val, (dict, list)):
        print(json.dumps(val, indent=2))
    elif val is None:
        print("")
    else:
        print(val)


def set_field(sid: str, expr: str) -> None:
    if "=" not in expr:
        sys.exit("--set value must be field=<json>")
    field, raw = expr.split("=", 1)
    field = field.strip()
    try:
        val = json.loads(raw)
    except json.JSONDecodeError:
        val = raw  # treat as plain string
    sp = _state_path(sid)
    state = _load(sp)
    if field not in state:
        sys.exit(f"unknown field: {field}. Add it to the schema first.")
    state[field] = val
    state["updated_at"] = _now()
    _save_atomic(sp, state)
    print(f"{sid}: set {field} = {json.dumps(val)[:80]}")


def append_field(sid: str, expr: str) -> None:
    if "=" not in expr:
        sys.exit("--append value must be field=<json>")
    field, raw = expr.split("=", 1)
    field = field.strip()
    try:
        val = json.loads(raw)
    except json.JSONDecodeError:
        val = raw
    sp = _state_path(sid)
    state = _load(sp)
    if field not in state:
        sys.exit(f"unknown field: {field}. Add it to the schema first.")
    if not isinstance(state[field], list):
        sys.exit(f"field {field!r} is not a list ({type(state[field]).__name__})")
    state[field].append(val)
    state["updated_at"] = _now()
    _save_atomic(sp, state)
    print(f"{sid}: appended to {field} (new length {len(state[field])})")


def main(argv: list[str]) -> None:
    if len(argv) < 3:
        sys.exit(__doc__)
    sid, second = argv[1], argv[2]
    if second == "--get":
        if len(argv) < 4:
            sys.exit("--get requires a field name")
        get_field(sid, argv[3])
    elif second == "--set":
        if len(argv) < 4:
            sys.exit("--set requires field=value")
        set_field(sid, argv[3])
    elif second == "--append":
        if len(argv) < 4:
            sys.exit("--append requires field=value")
        append_field(sid, argv[3])
    else:
        advance(sid, second)


if __name__ == "__main__":
    main(sys.argv)
