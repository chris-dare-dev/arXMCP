#!/usr/bin/env python3
"""roadmap-project-fields.py -- set Projects v2 Lane/Priority/Size from roadmap/1.

For issues already on a project (materialized by roadmap-to-github.py), set the
Lane / Priority / Size single-select fields from each roadmap item's lane /
priority / size. Project items are matched to roadmap items by the item ID
carried as the issue TITLE prefix (`<id>: ...`). See github-conventions.md.

DRY-RUN BY DEFAULT; --apply performs the writes (structural, user-gated), paced
to stay under GitHub secondary rate limits, idempotent + re-runnable. Status is
intentionally NOT set here -- it is live workflow state, not a roadmap attribute.

Usage:
  python3 roadmap-project-fields.py --owner OWNER --project N --roadmap a.yaml [--roadmap b.yaml ...]
  python3 roadmap-project-fields.py --owner OWNER --project N --roadmap a.yaml --apply

Requires: PyYAML + the gh CLI (project scope).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LANE_MAP = {"now": "Now", "next": "Next", "later": "Later"}
PRIORITY_MAP = {"must": "Must", "should": "Should", "could": "Could"}
SIZE_MAP = {"xs": "XS", "s": "S", "m": "M", "l": "L", "xl": "XL"}
FIELD_SPECS = [
    ("Lane", "lane", LANE_MAP),
    ("Priority", "priority", PRIORITY_MAP),
    ("Size", "size", SIZE_MAP),
]
PACE_S = 0.4


def gh(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=check)


def project_node_id(owner: str, number: int) -> str:
    r = gh(["project", "view", str(number), "--owner", owner, "--format", "json"])
    return json.loads(r.stdout)["id"]


def field_options(owner: str, number: int) -> dict:
    r = gh(["project", "field-list", str(number), "--owner", owner,
            "--format", "json", "--limit", "50"])
    out: dict = {}
    for f in json.loads(r.stdout).get("fields", []):
        if f.get("options"):
            out[f["name"]] = {"id": f["id"],
                              "opts": {o["name"]: o["id"] for o in f["options"]}}
    return out


def items_by_roadmap_id(owner: str, number: int) -> dict:
    r = gh(["project", "item-list", str(number), "--owner", owner,
            "--format", "json", "--limit", "2000"])
    out: dict = {}
    for it in json.loads(r.stdout).get("items", []):
        title = (it.get("content") or {}).get("title", "")
        if ": " in title:
            out[title.split(": ", 1)[0].strip()] = it["id"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True)
    ap.add_argument("--project", type=int, required=True)
    ap.add_argument("--roadmap", action="append", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    pid = project_node_id(args.owner, args.project)
    fields = field_options(args.owner, args.project)
    items = items_by_roadmap_id(args.owner, args.project)
    print(f"project #{args.project}: {len(items)} board items; fields: {list(fields)}")

    plan = []  # (item_id, field_id, option_id, label)
    missing = 0
    for path in args.roadmap:
        rm = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig"))
        for it in rm.get("items", []):
            item_id = items.get(it.get("id"))
            if not item_id:
                missing += 1
                continue
            for fname, key, vmap in FIELD_SPECS:
                opt = vmap.get(str(it.get(key, "")).lower())
                if opt and fname in fields and opt in fields[fname]["opts"]:
                    plan.append((item_id, fields[fname]["id"],
                                 fields[fname]["opts"][opt], f"{it['id']} {fname}={opt}"))

    print(f"field-writes planned: {len(plan)}  (roadmap items not on the board: {missing})")
    if not args.apply:
        for entry in plan[:15]:
            print(f"  would set {entry[3]}")
        if len(plan) > 15:
            print(f"  ... +{len(plan) - 15} more")
        print("\n(dry-run -- pass --apply to write; paced for rate limits)")
        return 0

    failed = 0
    for i, (item_id, field_id, option_id, _) in enumerate(plan, 1):
        r = gh(["project", "item-edit", "--project-id", pid, "--id", item_id,
                "--field-id", field_id, "--single-select-option-id", option_id], check=False)
        if r.returncode != 0:
            failed += 1
        if i % 50 == 0:
            print(f"  {i}/{len(plan)} (failed so far: {failed})")
        time.sleep(PACE_S)
    print(f"done: {len(plan) - failed} set, {failed} failed (re-run to fill any gaps).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
