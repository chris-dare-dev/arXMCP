#!/usr/bin/env python3
"""roadmap-score-rice.py — RICE computation for a roadmap/1 file (COMPUTE-ONLY).

Usage:
  python3 roadmap-score-rice.py <path/to/roadmap.yaml> [--json]

Reads each epic's rice.{r,i,c,e} raw factors (the sequencer agent fills
these), computes score = r*i*c/e and a descending 1-based rank (ties share
a rank), and PRINTS the results.

DESIGN NOTE — why this script never writes the YAML: PyYAML round-trips
(yaml.safe_load -> yaml.dump) lose comments and key order, which violates
the registry's byte-stability rule for agent-owned plan files. The one
sanctioned writer is the sequencer agent: it takes this script's --json
output and edits the `score:` / `rank:` values into each epic's `rice:`
block itself, then re-runs roadmap-validate.py.

Factor conventions (agent-chosen; the script is scale-agnostic but the
pipeline documents these): r = reach per period, i = impact
(0.25/0.5/1/2/3), c = confidence 0-1 (default 0.5 when there is no
evidence — surface every default), e = effort > 0 in person-weeks.

Epics with a missing/incomplete rice block or a non-positive e are listed
under "skipped" and excluded from ranking.

Exit codes: 0 computed (even with skips); 2 input/usage error.
Read-only. stdlib + PyYAML only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

FACTORS = ("r", "i", "c", "e")


def main() -> int:
    ap = argparse.ArgumentParser(description="RICE computation (roadmap/1, compute-only)")
    ap.add_argument("path", type=Path, help="path/to/roadmap.yaml")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        doc = yaml.safe_load(args.path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        sys.stderr.write(f"error: cannot read/parse {args.path}: {e}\n")
        return 2
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
        sys.stderr.write("error: document is not a roadmap/1 mapping with an items list\n")
        return 2

    scored: list[dict] = []
    skipped: list[dict] = []
    for it in doc["items"]:
        if not isinstance(it, dict) or it.get("kind") != "epic":
            continue
        iid = str(it.get("id", "?"))
        rice = it.get("rice")
        if not isinstance(rice, dict):
            skipped.append({"id": iid, "reason": "no rice block"})
            continue
        missing = [f for f in FACTORS if not isinstance(rice.get(f), (int, float))]
        if missing:
            skipped.append({"id": iid, "reason": f"missing/non-numeric factors: {', '.join(missing)}"})
            continue
        r, i, c, e = (float(rice[f]) for f in FACTORS)
        if e <= 0:
            skipped.append({"id": iid, "reason": "e must be > 0"})
            continue
        scored.append({
            "id": iid, "r": r, "i": i, "c": c, "e": e,
            "score": round(r * i * c / e, 2),
        })

    scored.sort(key=lambda x: (-x["score"], x["id"]))
    rank, prev = 0, None
    for pos, row in enumerate(scored, start=1):
        if row["score"] != prev:
            rank, prev = pos, row["score"]
        row["rank"] = rank

    if args.json:
        print(json.dumps({"ok": True, "epics": scored, "skipped": skipped}, indent=2))
    else:
        if scored:
            print(f"{'rank':>4}  {'id':<32} {'r':>7} {'i':>5} {'c':>5} {'e':>6} {'score':>8}")
            for row in scored:
                print(f"{row['rank']:>4}  {row['id']:<32} {row['r']:>7g} {row['i']:>5g}"
                      f" {row['c']:>5g} {row['e']:>6g} {row['score']:>8g}")
        else:
            print("no epics with complete rice factors")
        for s in skipped:
            print(f"skipped: {s['id']} — {s['reason']}")
        print("compute-only: write score/rank back into each epic's rice block via Edit, "
              "then re-run roadmap-validate.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
