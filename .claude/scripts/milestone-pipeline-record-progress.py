#!/usr/bin/env python3
"""milestone-pipeline-record-progress.py — append a status event to the journal.

Usage:
  python3 milestone-pipeline-record-progress.py <ITEM_ID> <STATUS>
      [--actor NAME] [--note "..."] [--repo-root PATH]

Locates the plans/*/roadmap.yaml that contains <ITEM_ID> (same lookup as
milestone-pipeline-resolve-brief.py), then appends ONE JSON line to
plans/<slug>/progress/agent.jsonl:

  {"id": ..., "field": "status", "value": ..., "at": <ISO-8601 local offset>,
   "actor": ..., "note": ...?}

ONE-WRITER RULE: this script NEVER edits roadmap.yaml. Execution progress is
journal appends only; the plan file belongs to the roadmap phase agents.

Legacy-prose milestones (id not present in any roadmap.yaml) get a warning and
exit 0 with NO write — there is no journal to append to.

Exit codes:
  0  event appended (or legacy-prose no-op)
  1  ambiguous — id found in more than one roadmap.yaml
  2  usage error (bad status, bad repo root)

Stdlib + PyYAML only. Append is atomic-enough: single write() on an 'a' handle.
"""
from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path

import yaml

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

STATUSES = {"planned", "ready", "in_progress", "blocked", "done", "dropped"}


def find_repo_root(override: str | None) -> Path:
    if override:
        p = Path(override).resolve()
        if not p.is_dir():
            sys.exit(f"error: --repo-root {override!r} is not a directory")
        return p
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(out.stdout.strip())
    except Exception:
        return Path(__file__).resolve().parents[2]


def scan_roadmaps(root: Path, item_id: str) -> list[Path]:
    """Return the roadmap.yaml paths containing item_id."""
    hits = []
    for path in sorted(root.glob("plans/*/roadmap.yaml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
        except Exception as e:
            print(f"warning: skipping unparseable {path}: {e}", file=sys.stderr)
            continue
        if not isinstance(doc, dict):
            continue
        for it in doc.get("items") or []:
            if isinstance(it, dict) and it.get("id") == item_id:
                hits.append(path)
                break
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description="append a status event to the progress journal")
    ap.add_argument("item_id")
    ap.add_argument("status")
    ap.add_argument("--actor", default="agent")
    ap.add_argument("--note", default=None)
    ap.add_argument("--repo-root", default=None)
    args = ap.parse_args()

    if args.status not in STATUSES:
        print(f"error: status {args.status!r} not in {sorted(STATUSES)}", file=sys.stderr)
        return 2

    root = find_repo_root(args.repo_root)
    hits = scan_roadmaps(root, args.item_id)

    if len(hits) > 1:
        print(f"error: id {args.item_id!r} found in {len(hits)} roadmap files "
              "(ids must be fleet-unique):", file=sys.stderr)
        for path in hits:
            print(f"  - {path}", file=sys.stderr)
        return 1

    if not hits:
        print(f"warning: {args.item_id!r} is not tracked in any plans/*/roadmap.yaml "
              "(legacy-prose or ad-hoc milestone) — no journal write.", file=sys.stderr)
        return 0

    journal = hits[0].parent / "progress" / "agent.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)

    event = {
        "id": args.item_id,
        "field": "status",
        "value": args.status,
        "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "actor": args.actor,
    }
    if args.note:
        event["note"] = args.note

    line = json.dumps(event, ensure_ascii=False)
    with open(journal, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    try:
        journal_rel = journal.relative_to(root).as_posix()
    except ValueError:
        journal_rel = journal.as_posix()
    print(f"recorded {args.item_id} status={args.status} -> {journal_rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
