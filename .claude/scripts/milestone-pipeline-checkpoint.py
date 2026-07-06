#!/usr/bin/env python3
"""Advance milestone state to the next phase, or read/write a state field.

Usage:
  milestone-pipeline-checkpoint.py <ID> <new-phase>             # advance state
  milestone-pipeline-checkpoint.py <ID> --get <field>           # read a top-level field
  milestone-pipeline-checkpoint.py <ID> --set <field>=<json>    # set a top-level field
  milestone-pipeline-checkpoint.py <ID> --append <field>=<json> # append to a list field

Phase advancement is validated against the state machine:
  init -> research-running -> research-complete
       -> implement-running -> implement-complete
       -> critique-running -> critique-complete
       -> rectify-running -> complete

Refuses backward transitions and skipped phases.  Writes atomically.

Repo root: parents[2] from this file (.claude/scripts/milestone-pipeline-checkpoint.py).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Force UTF-8 stdout/stderr so any non-ASCII content does not crash on Windows
# default cp1252 codepage.  All print() statements in this module use ASCII,
# but defensive output via --get on stored JSON strings could include any UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

try:
    from datetime import UTC, datetime
except ImportError:  # pragma: no cover -- Python <3.11 fallback
    from datetime import datetime, timezone  # noqa: UP017

    UTC = timezone.utc  # type: ignore[assignment]  # noqa: UP017

PHASE_ORDER = [
    "init",
    "research-running",
    "research-complete",
    "implement-running",
    "implement-complete",
    "critique-running",
    "critique-complete",
    "rectify-running",
    "complete",
]


def _state_path(mid: str) -> Path:
    # Path: .claude/scripts/milestone-pipeline-checkpoint.py
    #       parents[2] = repo root
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / ".claude" / "notes" / "milestones" / mid / "state.json"


def _load(state_path: Path) -> dict:
    if not state_path.exists():
        sys.exit(f"state.json not found at {state_path} -- run milestone-pipeline-init-state.sh first")
    return json.loads(state_path.read_text(encoding="utf-8"))


def _save_atomic(state_path: Path, state: dict) -> None:
    tmp = state_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, state_path)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def advance(mid: str, new_phase: str) -> None:
    if new_phase not in PHASE_ORDER:
        sys.exit(f"unknown phase: {new_phase}. Valid: {', '.join(PHASE_ORDER)}")
    sp = _state_path(mid)
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
    print(f"{mid}: {cur} -> {new_phase} @ {now}")


def get_field(mid: str, field: str) -> None:
    """Print the value of <field> on stdout.

    Exit codes:
      0  field has a non-None value (printed on stdout, possibly empty string)
      2  field exists in schema but is None (i.e. never set) -- diagnostic on stderr

    The exit-code split lets bash callers distinguish "never set" from
    "explicitly empty string".  Use `if VAL=$(... --get foo); then ...` to
    branch on whether the field was populated.
    """
    state = _load(_state_path(mid))
    if field not in state:
        sys.exit(f"unknown field: {field}. Valid: {', '.join(state.keys())}")
    val = state[field]
    if val is None:
        print(f"field {field!r} is unset (None)", file=sys.stderr)
        sys.exit(2)
    if isinstance(val, (dict, list)):
        print(json.dumps(val, indent=2))
    else:
        print(val)


def set_field(mid: str, expr: str) -> None:
    if "=" not in expr:
        sys.exit("--set value must be field=<json>")
    field, raw = expr.split("=", 1)
    field = field.strip()
    try:
        val = json.loads(raw)
    except json.JSONDecodeError:
        val = raw  # treat as plain string
    sp = _state_path(mid)
    state = _load(sp)
    if field not in state:
        sys.exit(f"unknown field: {field}. Add it to the schema first.")
    state[field] = val
    state["updated_at"] = _now()
    _save_atomic(sp, state)
    print(f"{mid}: set {field} = {json.dumps(val)[:80]}")


def append_field(mid: str, expr: str) -> None:
    if "=" not in expr:
        sys.exit("--append value must be field=<json>")
    field, raw = expr.split("=", 1)
    field = field.strip()
    try:
        val = json.loads(raw)
    except json.JSONDecodeError:
        val = raw
    sp = _state_path(mid)
    state = _load(sp)
    if field not in state:
        sys.exit(f"unknown field: {field}. Add it to the schema first.")
    if not isinstance(state[field], list):
        sys.exit(f"field {field!r} is not a list ({type(state[field]).__name__})")
    state[field].append(val)
    state["updated_at"] = _now()
    _save_atomic(sp, state)
    print(f"{mid}: appended to {field} (new length {len(state[field])})")


def main(argv: list[str]) -> None:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    if len(argv) < 3:
        sys.exit(__doc__)
    mid, second = argv[1], argv[2]
    if second == "--get":
        if len(argv) < 4:
            sys.exit("--get requires a field name")
        get_field(mid, argv[3])
    elif second == "--set":
        if len(argv) < 4:
            sys.exit("--set requires field=value")
        set_field(mid, argv[3])
    elif second == "--append":
        if len(argv) < 4:
            sys.exit("--append requires field=value")
        append_field(mid, argv[3])
    else:
        advance(mid, second)


if __name__ == "__main__":
    main(sys.argv)
