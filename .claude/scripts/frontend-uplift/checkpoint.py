#!/usr/bin/env python3
"""Advance frontend-uplift state to the next phase, or read/write a field.

Usage:
  checkpoint.py <ID> <new-phase>             # advance state
  checkpoint.py <ID> --get <field>           # read a top-level field
  checkpoint.py <ID> --set <field>=<json>    # set a top-level field (json-parsed)
  checkpoint.py <ID> --append <field>=<json> # append json value to a list field

Phase advancement is validated against the state machine:

  init → discover-running → discover-complete
       → synthesize-running → synthesize-complete
       → challenge-running → challenge-complete
       → prioritize-running → complete

Refuses backward transitions and skipped phases.  Writes atomically.

Mirrors capability-scout/checkpoint.py — same shape, different phase names
(discover/synthesize/challenge/prioritize) and a different state directory
(.claude/notes/frontend-uplifts/ vs capability-scouts/).
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
    "discover-running",
    "discover-complete",
    "synthesize-running",
    "synthesize-complete",
    "challenge-running",
    "challenge-complete",
    "prioritize-running",
    "complete",
]


def _state_path(uid: str) -> Path:
    # Path: .claude/scripts/frontend-uplift/checkpoint.py
    #       └── parents[3] = repo root
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / ".claude" / "notes" / "frontend-uplifts" / uid / "state.json"


def _load(state_path: Path) -> dict:
    if not state_path.exists():
        sys.exit(f"state.json not found at {state_path} — run init-uplift.sh first")
    return json.loads(state_path.read_text())


def _save_atomic(state_path: Path, state: dict) -> None:
    tmp = state_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, state_path)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def advance(uid: str, new_phase: str) -> None:
    if new_phase not in PHASE_ORDER:
        sys.exit(f"unknown phase: {new_phase}. Valid: {', '.join(PHASE_ORDER)}")
    sp = _state_path(uid)
    state = _load(sp)
    cur = state["phase"]
    cur_idx = PHASE_ORDER.index(cur)
    new_idx = PHASE_ORDER.index(new_phase)
    if new_idx <= cur_idx:
        sys.exit(f"refusing backward/same transition: {cur} → {new_phase}")
    if new_idx - cur_idx > 1:
        sys.exit(f"refusing skipped transition: {cur} → {new_phase} (must advance one step)")
    now = _now()
    state["phase"] = new_phase
    state["updated_at"] = now
    state["phase_history"].append({"phase": new_phase, "at": now})
    _save_atomic(sp, state)
    print(f"{uid}: {cur} → {new_phase} @ {now}")


def get_field(uid: str, field: str) -> None:
    state = _load(_state_path(uid))
    if field not in state:
        sys.exit(f"unknown field: {field}. Valid: {', '.join(state.keys())}")
    val = state[field]
    if isinstance(val, (dict, list)):
        print(json.dumps(val, indent=2))
    elif val is None:
        print("")
    else:
        print(val)


def set_field(uid: str, expr: str) -> None:
    if "=" not in expr:
        sys.exit("--set value must be field=<json>")
    field, raw = expr.split("=", 1)
    field = field.strip()
    try:
        val = json.loads(raw)
    except json.JSONDecodeError:
        val = raw
    sp = _state_path(uid)
    state = _load(sp)
    if field not in state:
        sys.exit(f"unknown field: {field}. Add it to the schema first.")
    state[field] = val
    state["updated_at"] = _now()
    _save_atomic(sp, state)
    print(f"{uid}: set {field} = {json.dumps(val)[:80]}")


def append_field(uid: str, expr: str) -> None:
    if "=" not in expr:
        sys.exit("--append value must be field=<json>")
    field, raw = expr.split("=", 1)
    field = field.strip()
    try:
        val = json.loads(raw)
    except json.JSONDecodeError:
        val = raw
    sp = _state_path(uid)
    state = _load(sp)
    if field not in state:
        sys.exit(f"unknown field: {field}. Add it to the schema first.")
    if not isinstance(state[field], list):
        sys.exit(f"field {field!r} is not a list ({type(state[field]).__name__})")
    state[field].append(val)
    state["updated_at"] = _now()
    _save_atomic(sp, state)
    print(f"{uid}: appended to {field} (new length {len(state[field])})")


def main(argv: list[str]) -> None:
    if len(argv) < 3:
        sys.exit(__doc__)
    uid, second = argv[1], argv[2]
    if second == "--get":
        if len(argv) < 4:
            sys.exit("--get requires a field name")
        get_field(uid, argv[3])
    elif second == "--set":
        if len(argv) < 4:
            sys.exit("--set requires field=value")
        set_field(uid, argv[3])
    elif second == "--append":
        if len(argv) < 4:
            sys.exit("--append requires field=value")
        append_field(uid, argv[3])
    else:
        advance(uid, second)


if __name__ == "__main__":
    main(sys.argv)
