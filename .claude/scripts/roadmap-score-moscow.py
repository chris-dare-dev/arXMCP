#!/usr/bin/env python3
"""roadmap-score-moscow.py — MoSCoW Must-cap check for a roadmap/1 file.

Usage:
  python3 roadmap-score-moscow.py <path/to/roadmap.yaml> [--json] [--cap 60]

Reads the epics from the canonical roadmap.yaml and computes the must share
over non-wont epics (count-based, mirroring roadmap-validate.py's must-cap
check: epics without a priority still count in the denominator).

DSDM canonical rule: a Must list over 60% collapses the prioritization
signal — everything-is-must becomes nothing-is-must under deadline pressure.

Exit codes:
  0  must share within cap (or no epics yet)
  1  must share exceeds the cap — demote one or more epics to should/could
  2  input / usage error

Read-only: never writes the YAML. stdlib + PyYAML only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

DEFAULT_CAP = 60.0  # DSDM canonical
BUCKETS = ("must", "should", "could", "wont")


def main() -> int:
    ap = argparse.ArgumentParser(description="MoSCoW Must-cap check (roadmap/1)")
    ap.add_argument("path", type=Path, help="path/to/roadmap.yaml")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--cap", type=float, default=DEFAULT_CAP,
                    help=f"must-cap percentage (default {DEFAULT_CAP:.0f})")
    args = ap.parse_args()

    if not (0 < args.cap <= 100):
        sys.stderr.write(f"error: --cap must be in (0, 100], got {args.cap}\n")
        return 2
    try:
        doc = yaml.safe_load(args.path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        sys.stderr.write(f"error: cannot read/parse {args.path}: {e}\n")
        return 2
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
        sys.stderr.write("error: document is not a roadmap/1 mapping with an items list\n")
        return 2

    epics = [it for it in doc["items"]
             if isinstance(it, dict) and it.get("kind") == "epic"]
    by_bucket: dict[str, list[str]] = {b: [] for b in BUCKETS}
    unset: list[str] = []
    for e in epics:
        iid = str(e.get("id", "?"))
        pri = e.get("priority")
        if pri in BUCKETS:
            by_bucket[pri].append(iid)
        else:
            unset.append(iid)

    scoped = len(epics) - len(by_bucket["wont"])  # non-wont epics (unset count)
    musts = len(by_bucket["must"])
    must_pct = (musts / scoped * 100.0) if scoped else 0.0
    ok = must_pct <= args.cap
    if ok:
        message = f"OK: must = {musts}/{scoped} non-wont epics = {must_pct:.1f}% (cap {args.cap:.0f}%)"
        if not epics:
            message = "OK: no epics found (nothing to cap yet)"
    else:
        message = (
            f"FAIL: must = {musts}/{scoped} non-wont epics = {must_pct:.1f}% — exceeds the "
            f"{args.cap:.0f}% cap. Demote one or more must epics to should/could before "
            f"sequencing; a Must list with no slack collapses under deadline pressure (DSDM)."
        )

    if args.json:
        print(json.dumps({
            "ok": ok,
            "cap_pct": args.cap,
            "must_pct": round(must_pct, 1),
            "epics_total": len(epics),
            "epics_non_wont": scoped,
            "buckets": {b: by_bucket[b] for b in BUCKETS},
            "priority_unset": unset,
            "message": message,
        }, indent=2))
    else:
        print("MoSCoW summary (epics):")
        for b in BUCKETS:
            ids = ", ".join(by_bucket[b]) or "—"
            print(f"  {b:<6}  {len(by_bucket[b]):3d}   {ids}")
        if unset:
            print(f"  unset   {len(unset):3d}   {', '.join(unset)}  (counted as non-wont)")
        print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
