#!/usr/bin/env python3
"""
score-rice.py — RICE scoring for the SEQUENCE phase.

RICE = (Reach × Impact × Confidence) / Effort
  - Reach: users / events affected per period (raw count)
  - Impact: 3 (massive) | 2 (high) | 1 (medium) | 0.5 (low) | 0.25 (minimal)
  - Confidence: percentage 0–100 (default 50 when no evidence — Intercom
    "Low" tier; treated as a forcing function to gather evidence, not a
    starting bid)
  - Effort: person-months (≥ 0.1)

Input format (stdin or file): one item per line, pipe-delimited:
    id | reach | impact | confidence | effort
e.g.
    e1 | 5000 | 2.0 | 80 | 1.5
    e2 | 1500 | 3.0 |    | 2

Confidence may be left empty; the script defaults to 50% and flags it.

Usage:
    score-rice.py [--example] [<file>]

Exit codes: 0 ok; 2 input/usage error.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

DEFAULT_CONFIDENCE = 50.0
EXAMPLE_INPUT = """\
parser-fidelity     | 5000 | 3.0 | 80 | 2.0
cache-warmup        | 4000 | 2.0 |    | 1.0
citation-graph      | 2000 | 2.0 | 50 | 3.5
ops-dashboard       |  800 | 1.0 | 90 | 1.5
"""


@dataclass
class Item:
    item_id: str
    reach: float
    impact: float
    confidence: float  # 0..100
    effort: float
    confidence_defaulted: bool

    @property
    def score(self) -> float:
        return (self.reach * self.impact * (self.confidence / 100.0)) / self.effort


def parse_line(line: str) -> Item | None:
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return None
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) != 5:
        sys.stderr.write(f"error: expected 5 pipe-delimited fields, got {len(parts)}: {raw!r}\n")
        sys.exit(2)
    item_id, reach_s, impact_s, conf_s, effort_s = parts
    try:
        reach = float(reach_s)
        impact = float(impact_s)
        effort = float(effort_s)
    except ValueError as e:
        sys.stderr.write(f"error: numeric parse failed on {raw!r}: {e}\n")
        sys.exit(2)
    if conf_s == "":
        confidence = DEFAULT_CONFIDENCE
        confidence_defaulted = True
    else:
        try:
            confidence = float(conf_s)
        except ValueError:
            sys.stderr.write(f"error: confidence must be numeric, got {conf_s!r}\n")
            sys.exit(2)
        confidence_defaulted = False
    if effort <= 0:
        sys.stderr.write(f"error: effort must be > 0 (got {effort} for {item_id})\n")
        sys.exit(2)
    if not (0 <= confidence <= 100):
        sys.stderr.write(f"error: confidence must be 0–100 (got {confidence} for {item_id})\n")
        sys.exit(2)
    return Item(item_id, reach, impact, confidence, effort, confidence_defaulted)


def render(items: list[Item]) -> str:
    items_sorted = sorted(items, key=lambda i: i.score, reverse=True)
    lines = []
    lines.append("| ID | Reach | Impact | Confidence | Effort | Score |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for it in items_sorted:
        conf = f"{it.confidence:.0f}%"
        if it.confidence_defaulted:
            conf += " *"
        lines.append(
            f"| {it.item_id} | {it.reach:.0f} | {it.impact:.2f} | {conf} | "
            f"{it.effort:.2f} | {it.score:.1f} |"
        )
    if any(i.confidence_defaulted for i in items):
        lines.append("")
        lines.append(
            "_`*` indicates Confidence defaulted to 50% — gather evidence and re-rank._"
        )
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="RICE scoring")
    p.add_argument("file", nargs="?", help="input file (default: stdin)")
    p.add_argument("--example", action="store_true",
                   help="rank a built-in sample set and exit")
    args = p.parse_args()

    if args.example:
        text = EXAMPLE_INPUT
    elif args.file:
        with open(args.file) as f:
            text = f.read()
    else:
        if sys.stdin.isatty():
            sys.stderr.write("error: no input (pipe data or pass a file or use --example)\n")
            return 2
        text = sys.stdin.read()

    items: list[Item] = []
    for line in text.splitlines():
        it = parse_line(line)
        if it:
            items.append(it)
    if not items:
        sys.stderr.write("error: no items parsed\n")
        return 2

    print(render(items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
