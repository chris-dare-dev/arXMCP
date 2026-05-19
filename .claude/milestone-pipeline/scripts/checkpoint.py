#!/usr/bin/env python3
"""
checkpoint.py — milestone-pipeline state machine validator.

Reads / writes <repo-root>/.claude/notes/milestones/<ID>/state.json.
Enforces strict-forward-only phase transitions: refuses backward moves
and refuses skipped phases (one step at a time only).

Exit codes:
    0  success
    1  user-actionable failure (refused transition, missing state, etc.)
    2  input / usage error
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path

PHASES = [
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

# Index lookup for one-step-forward enforcement.
PHASE_INDEX = {name: i for i, name in enumerate(PHASES)}


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_repo_root(explicit: str | None) -> Path:
    """Repo-root detection: --repo-root flag → $REPO_ROOT → git rev-parse → walk up."""
    if explicit:
        p = Path(explicit).resolve()
        if not (p / ".git").exists():
            sys.stderr.write(f"error: --repo-root {p} has no .git/\n")
            sys.exit(2)
        return p
    env = os.environ.get("REPO_ROOT")
    if env:
        p = Path(env).resolve()
        if (p / ".git").exists():
            return p
    # git rev-parse from CWD
    try:
        import subprocess
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip()).resolve()
    except FileNotFoundError:
        pass
    # Walk up from script location.
    here = Path(__file__).resolve().parent
    for ancestor in [here, *here.parents]:
        if (ancestor / ".git").exists():
            return ancestor
    sys.stderr.write("error: could not locate repo root (no .git/ found)\n")
    sys.exit(1)


def state_path(repo_root: Path, milestone_id: str) -> Path:
    return repo_root / ".claude" / "notes" / "milestones" / milestone_id / "state.json"


def load_state(path: Path) -> dict:
    if not path.exists():
        sys.stderr.write(f"error: state not found: {path}\n")
        sys.stderr.write("       run init-state.sh first.\n")
        sys.exit(1)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.stderr.write(f"error: state.json is not valid JSON: {e}\n")
        sys.exit(1)


def atomic_write_json(path: Path, data: dict) -> None:
    """Atomic write: temp + fsync + rename + dirfsync. macOS uses F_FULLFSYNC."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, payload.encode("utf-8"))
        if sys.platform == "darwin":
            try:
                import fcntl
                F_FULLFSYNC = 51
                fcntl.fcntl(fd, F_FULLFSYNC)
            except OSError:
                os.fsync(fd)
        else:
            os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    # Directory fsync — survives crash so the rename sticks.
    # Windows refuses os.open() on a directory; skip the directory fsync there
    # (NTFS rename is already durable enough for our purposes).
    if sys.platform == "win32":
        return
    dfd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(dfd)
    except OSError:
        pass
    finally:
        os.close(dfd)


def transition(state: dict, target: str) -> dict:
    current = state.get("phase")
    if target not in PHASE_INDEX:
        sys.stderr.write(f"error: unknown phase '{target}'\n")
        sys.stderr.write(f"       valid: {', '.join(PHASES)}\n")
        sys.exit(2)
    if current == target:
        sys.stderr.write(f"note: already in phase '{target}', no-op\n")
        return state
    cur_i = PHASE_INDEX.get(current, -1)
    new_i = PHASE_INDEX[target]
    if new_i <= cur_i:
        sys.stderr.write(
            f"error: refused backward transition '{current}' -> '{target}'\n"
            f"       state machine is forward-only.\n"
        )
        sys.exit(1)
    if new_i != cur_i + 1:
        sys.stderr.write(
            f"error: refused skipped transition '{current}' -> '{target}'\n"
            f"       expected next phase: '{PHASES[cur_i + 1]}'\n"
        )
        sys.exit(1)
    now = _now()
    history = state.setdefault("phase_history", [])
    if history and history[-1].get("phase") == current and not history[-1].get("left_at"):
        history[-1]["left_at"] = now
    history.append({"phase": target, "entered_at": now, "left_at": None})
    state["phase"] = target
    state["updated_at"] = now
    return state


def parse_set_assignment(raw: str) -> tuple[str, object]:
    if "=" not in raw:
        sys.stderr.write(f"error: --set expects 'field=json_value', got: {raw}\n")
        sys.exit(2)
    key, _, value_raw = raw.partition("=")
    key = key.strip()
    if not key:
        sys.stderr.write("error: --set field name is empty\n")
        sys.exit(2)
    try:
        value = json.loads(value_raw)
    except json.JSONDecodeError:
        # Treat as literal string if not valid JSON.
        value = value_raw
    return key, value


def cmd_get(state: dict, field: str) -> int:
    if field not in state:
        sys.stderr.write(f"error: field '{field}' not in state\n")
        return 1
    val = state[field]
    if isinstance(val, (dict, list)):
        print(json.dumps(val, indent=2, sort_keys=True))
    else:
        print(val)
    return 0


def cmd_set(state: dict, raw: str) -> dict:
    key, value = parse_set_assignment(raw)
    state[key] = value
    state["updated_at"] = _now()
    return state


def main() -> int:
    p = argparse.ArgumentParser(
        description="milestone-pipeline state machine validator",
    )
    p.add_argument("milestone_id", help="milestone ID (e.g. E01_S01)")
    p.add_argument("phase", nargs="?", help="target phase (forward-only)")
    p.add_argument("--get", metavar="FIELD", help="print a state field and exit")
    p.add_argument("--set", metavar="FIELD=JSON", help="set a state field")
    p.add_argument("--repo-root", help="override repo root detection")
    args = p.parse_args()

    root = find_repo_root(args.repo_root)
    sp = state_path(root, args.milestone_id)
    state = load_state(sp)

    if args.get:
        return cmd_get(state, args.get)

    if args.set:
        state = cmd_set(state, args.set)
        atomic_write_json(sp, state)
        print(f"set {args.set.split('=', 1)[0]} on {args.milestone_id}")
        return 0

    if args.phase:
        state = transition(state, args.phase)
        atomic_write_json(sp, state)
        print(f"{args.milestone_id}: phase = {state['phase']}")
        return 0

    # No action: print current phase.
    print(state.get("phase", "(unknown)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
