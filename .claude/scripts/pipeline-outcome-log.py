#!/usr/bin/env python3
"""pipeline-outcome-log.py — append-only, best-effort pipeline outcome capture.

Writes ONE labelled JSONL record per pipeline run to
`<repo-root>/.claude/notes/pipeline-outcomes/outcomes.jsonl`. That file is the
dataset a future cross-run calibration step (or claude-otel) would read. It is
advisory only: a capture failure here must NEVER abort the host pipeline's
terminal transition, so `emit` swallows its own errors and still exits 0.

Usage:
  pipeline-outcome-log.py emit --pipeline <fam> --id <ID>
      [--state <path>] [--outcome <phase>] [--field k=v]... [--log <path>]
  pipeline-outcome-log.py summary [--pipeline <fam>] [--last N] [--json]
      [--log <path>]

`emit` reads the milestone `state.json` (when `--state` is given) to fill the
outcome columns, then applies `--outcome` (if given), then any `--field k=v`
overrides last. For the roadmap family there is no `state.json`; the caller
passes the columns it knows via `--field` (e.g. `--field
source_state_path=plans/<slug>/roadmap.yaml --field outcome=complete`).

`--outcome` is the DECLARED terminal outcome and should be passed by every
terminal emit site. Without it the outcome column is a snapshot of
`state.phase` at call time — which races the caller's own state write: an
emit that lands between the rectification-data write and the phase flip
records `outcome=rectify-running` forever, and no second emit follows
(observed on options-signal-engine g7-3-a-m1 / g5-1-a-m1, review
2026-07-16). The `phase` column still records the state-read phase verbatim,
so a declared-outcome row whose phase lags is visible, not laundered; the
emit prints a non-fatal stderr note when they diverge.

token_cost is intentionally left null. The fleet's OTel home (claude-otel) is
the future place to backfill per-run token cost; this script builds no metric
push of any kind.

Repo root (default log location) resolves, in order:
  1. $REPO_ROOT   2. `git rev-parse --show-toplevel`   3. walk up to a .git/
A synced copy of this script lives at `<root>/.claude/scripts/<file>`, so the
final fallback is parents[2] of this file. `$PIPELINE_OUTCOME_LOG` overrides
the log path entirely.

Stdlib only. No PyYAML (state.json is JSON). fcntl is used opportunistically
for the append lock and is ImportError-guarded so the script runs on native
Windows, where the milestone .lock already serializes runs.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

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

try:
    import fcntl  # POSIX-only advisory lock; absent on native Windows.
except ImportError:  # pragma: no cover -- Windows path
    fcntl = None  # type: ignore[assignment]

SCHEMA_VERSION = 1

# Stable column set. Discovery columns (candidate_count / challenge_finding_
# counts) have no downstream producer in this fleet, but are kept null for
# schema stability so a later discovery pipeline can populate them without a
# migration.
_NULL_DISCOVERY = {"candidate_count": None, "challenge_finding_counts": None}


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def find_repo_root() -> Path:
    """Resolve the repo root: $REPO_ROOT -> git rev-parse -> walk up to .git/."""
    env = os.environ.get("REPO_ROOT")
    if env:
        p = Path(env)
        if p.is_dir():
            return p.resolve()
    here = Path(__file__).resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(here.parent),
        )
        top = out.stdout.strip()
        if top:
            return Path(top)
    except Exception:
        pass
    for parent in [here.parent, *here.parents]:
        if (parent / ".git").exists():
            return parent
    # Synced script location: <root>/.claude/scripts/<file> -> parents[2].
    return here.parents[2]


def resolve_log_path(root: Path, override: str | None = None) -> Path:
    if override:
        return Path(override)
    env = os.environ.get("PIPELINE_OUTCOME_LOG")
    if env:
        return Path(env)
    return root / ".claude" / "notes" / "pipeline-outcomes" / "outcomes.jsonl"


def _load_state(state_path: str | None) -> dict:
    if not state_path:
        return {}
    p = Path(state_path)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_field(raw: str) -> tuple[str, object]:
    if "=" not in raw:
        raise ValueError(f"--field must be key=value, got {raw!r}")
    key, val = raw.split("=", 1)
    key = key.strip()
    try:
        return key, json.loads(val)
    except json.JSONDecodeError:
        return key, val  # plain string


def build_record(
    pipeline: str,
    item_id: str,
    state_path: str | None,
    fields: list[str] | None,
    outcome: str | None = None,
) -> dict:
    """Assemble one outcome record. state.json fills columns; the declared
    ``outcome`` (if any) overrides the state-read phase; --field overrides last."""
    state = _load_state(state_path)
    fixed = state.get("fixed_findings") or []
    record: dict = {
        "schema_version": SCHEMA_VERSION,
        "run_id": uuid.uuid4().hex,
        "emitted_at": _now(),
        "pipeline": pipeline,
        "id": item_id,
        "source_state_path": state_path,
        "created_at": state.get("created_at"),
        "updated_at": state.get("updated_at"),
        # `phase` is ALWAYS the state-read snapshot — never overwritten by the
        # declared outcome, so a lagging state write stays visible in the row.
        "phase": state.get("phase"),
        # Default: the state phase IS the outcome. Terminal emit sites pass
        # --outcome to declare it explicitly (ordering-proof — see docstring);
        # roadmap callers historically pass it via --field, which still wins.
        "outcome": outcome if outcome is not None else state.get("phase"),
        "critique_finding_counts": state.get("critique_finding_counts"),
        "fixed_findings": list(fixed),
        # rectification_count == len(fixed_findings) is the LOCKED definition.
        "rectification_count": len(fixed),
        "rectification_commit": state.get("rectification_commit"),
        # token_cost stays null; claude-otel is the future home (build nothing).
        "token_cost": state.get("token_cost"),
        **_NULL_DISCOVERY,
    }
    for raw in fields or []:
        key, val = _parse_field(raw)
        record[key] = val
    return record


def append_record(log_path: Path, record: dict) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    # Append-only: a single write() to an O_APPEND handle is the atomicity
    # story (POSIX guarantees it under PIPE_BUF). fcntl adds an advisory lock
    # where available; on Windows the milestone .lock already serializes runs.
    with open(log_path, "a", encoding="utf-8") as f:
        if fcntl is not None:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(line + "\n")
            f.flush()
        finally:
            if fcntl is not None:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def read_records(log_path: Path) -> list[dict]:
    if not log_path.is_file():
        return []
    out = []
    for line in log_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def do_emit(args: argparse.Namespace) -> int:
    """Best-effort emit. Any failure is reported and swallowed (exit 0) so a
    capture problem can never abort the host pipeline's terminal transition."""
    try:
        root = find_repo_root()
        log_path = resolve_log_path(root, args.log)
        record = build_record(args.pipeline, args.id, args.state, args.field, outcome=args.outcome)
        append_record(log_path, record)
        print(f"outcome logged: {args.pipeline} {args.id} run={record['run_id']} -> {log_path}")
        if record.get("phase") is not None and record.get("outcome") != record.get("phase"):
            # Visibility, not a failure: the declared outcome outran the
            # caller's state write (or the emit ran early). The row records
            # both columns, so the lag is auditable.
            print(
                f"note: state phase={record.get('phase')!r} != recorded outcome="
                f"{record.get('outcome')!r} (state write lagging or emit ran early)",
                file=sys.stderr,
            )
    except Exception as e:  # noqa: BLE001 -- best-effort by contract
        print(f"warning: outcome capture failed (non-fatal): {e}", file=sys.stderr)
    return 0


def do_summary(args: argparse.Namespace) -> int:
    root = find_repo_root()
    log_path = resolve_log_path(root, args.log)
    records = read_records(log_path)
    if args.pipeline:
        records = [r for r in records if r.get("pipeline") == args.pipeline]
    if args.last and args.last > 0:
        records = records[-args.last :]
    if args.json:
        print(json.dumps(records, indent=2, ensure_ascii=False))
        return 0
    if not records:
        print(f"no outcome records at {log_path}")
        return 0
    print(f"{'emitted_at':<21} {'pipeline':<10} {'id':<28} outcome")
    for r in records:
        print(
            f"{str(r.get('emitted_at', '')):<21} "
            f"{str(r.get('pipeline', '')):<10} "
            f"{str(r.get('id', '')):<28} "
            f"{r.get('outcome')}"
        )
    print(f"({len(records)} record(s) from {log_path})")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="append-only pipeline outcome capture")
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("emit", help="append one outcome record")
    e.add_argument("--pipeline", required=True, help="pipeline family, e.g. milestone / roadmap")
    e.add_argument("--id", required=True, help="milestone or roadmap id")
    e.add_argument("--state", default=None, help="path to state.json (milestone family)")
    e.add_argument(
        "--outcome",
        default=None,
        help="declared terminal outcome (e.g. complete) — wins over the state-read "
        "phase so the row cannot race the caller's own state write",
    )
    e.add_argument("--field", action="append", default=[], help="k=v column override (repeatable)")
    e.add_argument("--log", default=None, help="override log path")
    e.set_defaults(func=do_emit)

    s = sub.add_parser("summary", help="read back recorded outcomes")
    s.add_argument("--pipeline", default=None, help="filter by pipeline family")
    s.add_argument("--last", type=int, default=0, help="show only the last N records")
    s.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    s.add_argument("--log", default=None, help="override log path")
    s.set_defaults(func=do_summary)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
