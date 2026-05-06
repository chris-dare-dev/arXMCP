#!/usr/bin/env python3
"""
score-moscow.py — MoSCoW Must-cap validator for the SEQUENCE phase.

Enforces the DSDM canonical rule: no more than 60% of total effort
should land in the "Must" bucket. Inflated Must lists collapse the
prioritization signal (everything-is-must → nothing-is-must under
deadline pressure).

Input format (stdin or file): one item per line, pipe-delimited:
    id | bucket | effort
where bucket is one of: must | should | could | wont
and effort is in person-months.

Usage:
    score-moscow.py [--example] [--cap 60] [<file>]

Exit codes:
    0  Must percentage within cap
    1  Must percentage exceeds cap (clear violation message)
    2  input / usage error
"""
from __future__ import annotations

import argparse
import sys

DEFAULT_CAP = 60.0  # DSDM canonical
VALID_BUCKETS = {"must", "should", "could", "wont"}

EXAMPLE_INPUT = """\
parser-fidelity   | must   | 2.0
cache-warmup      | must   | 1.0
mcp-spec          | must   | 1.5
citation-graph    | should | 3.5
ops-dashboard     | could  | 1.5
admin-ui          | wont   | 4.0
"""

EXAMPLE_FAIL_INPUT = """\
parser-fidelity   | must   | 2.0
cache-warmup      | must   | 1.0
mcp-spec          | must   | 1.5
citation-graph    | must   | 3.5
ops-dashboard     | must   | 1.5
admin-ui          | wont   | 4.0
"""


def parse_line(line: str) -> tuple[str, str, float] | None:
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return None
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) != 3:
        sys.stderr.write(f"error: expected 3 pipe-delimited fields, got {len(parts)}: {raw!r}\n")
        sys.exit(2)
    item_id, bucket_raw, effort_s = parts
    bucket = bucket_raw.lower()
    if bucket not in VALID_BUCKETS:
        sys.stderr.write(
            f"error: bucket must be one of {sorted(VALID_BUCKETS)}, "
            f"got {bucket_raw!r} for {item_id}\n"
        )
        sys.exit(2)
    try:
        effort = float(effort_s)
    except ValueError:
        sys.stderr.write(f"error: effort must be numeric, got {effort_s!r} for {item_id}\n")
        sys.exit(2)
    if effort < 0:
        sys.stderr.write(f"error: effort must be ≥ 0 (got {effort} for {item_id})\n")
        sys.exit(2)
    return item_id, bucket, effort


def main() -> int:
    p = argparse.ArgumentParser(description="MoSCoW Must-cap validator")
    p.add_argument("file", nargs="?")
    p.add_argument("--example", action="store_true",
                   help="run with a built-in passing example")
    p.add_argument("--example-fail", action="store_true",
                   help="run with a built-in failing example (Must over cap)")
    p.add_argument("--cap", type=float, default=DEFAULT_CAP,
                   help=f"Must-cap percentage (default {DEFAULT_CAP})")
    args = p.parse_args()

    if args.example:
        text = EXAMPLE_INPUT
    elif args.example_fail:
        text = EXAMPLE_FAIL_INPUT
    elif args.file:
        with open(args.file) as f:
            text = f.read()
    else:
        if sys.stdin.isatty():
            sys.stderr.write("error: no input (pipe data, pass a file, or use --example)\n")
            return 2
        text = sys.stdin.read()

    if not (0 < args.cap <= 100):
        sys.stderr.write(f"error: --cap must be in (0, 100], got {args.cap}\n")
        return 2

    totals: dict[str, float] = {b: 0.0 for b in VALID_BUCKETS}
    items_by_bucket: dict[str, list[str]] = {b: [] for b in VALID_BUCKETS}
    for line in text.splitlines():
        parsed = parse_line(line)
        if not parsed:
            continue
        item_id, bucket, effort = parsed
        totals[bucket] += effort
        items_by_bucket[bucket].append(item_id)

    grand_total = sum(totals.values())
    if grand_total == 0:
        sys.stderr.write("error: no items parsed (or all efforts zero)\n")
        return 2

    must_pct = (totals["must"] / grand_total) * 100.0

    print("MoSCoW summary:")
    for bucket in ("must", "should", "could", "wont"):
        pct = (totals[bucket] / grand_total) * 100.0
        ids = ", ".join(items_by_bucket[bucket]) or "—"
        print(f"  {bucket:<6}  {totals[bucket]:6.2f}pm  {pct:5.1f}%   {ids}")
    print(f"  total   {grand_total:6.2f}pm")
    print()

    if must_pct > args.cap:
        sys.stderr.write(
            f"FAIL: Must = {must_pct:.1f}% of effort — exceeds {args.cap:.0f}% cap.\n"
            f"      Demote one or more 'must' items to 'should' before sequencing.\n"
            f"      DSDM rule: a Must list with no slack collapses under deadline pressure.\n"
        )
        return 1

    print(f"OK: Must = {must_pct:.1f}% (≤ {args.cap:.0f}% cap)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
