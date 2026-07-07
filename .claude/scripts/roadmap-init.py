#!/usr/bin/env python3
"""roadmap-init.py — scaffold or resume a roadmap/1 canonical roadmap.

Usage:
  python3 roadmap-init.py <slug> [--brief "..."] [--project <key>] [--repo-root <path>]
  python3 roadmap-init.py <slug> --status [--repo-root <path>]
  python3 roadmap-init.py <slug> --advance <phase> [--repo-root <path>]

Creates plans/<slug>/roadmap.yaml (phase: init) + plans/<slug>/progress/
(with a .gitkeep so the dir survives clones) and prints INITIALIZED, or
prints RESUMING phase=<phase> when the file already exists. --status prints
the current phase; --advance moves phase forward one step only
(init->refined->decomposed->sequenced->complete), mirroring the
milestone-pipeline checkpoint discipline.

Idempotent; never overwrites an existing roadmap.yaml.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

PHASES = ["init", "refined", "decomposed", "sequenced", "complete"]


def repo_root(override: str | None) -> Path:
    if override:
        return Path(override).resolve()
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit("ERROR: not inside a git repo and no --repo-root given")
    return Path(out.stdout.strip())


def derive_project(root: Path) -> str:
    return root.name.lower()


def scaffold(slug: str, project: str, brief: str) -> str:
    # Plain string template (not yaml.dump) so field order and comments are
    # stable for prompt-cache byte-stability and human reading.
    raw = brief or "(brief pending — pass --brief or let the refiner capture the ask)"
    # Indent EVERY brief line so a multi-line --brief stays inside the
    # `brief: |` literal block instead of breaking the YAML document.
    # Blank lines are emitted empty (no trailing spaces) for byte-stability.
    indented = "\n".join(f"  {line}" if line.strip() else "" for line in raw.splitlines())
    return f"""schema: roadmap/1
slug: {slug}
project: {project}
title: ""            # <- refine phase sets this
status: draft
phase: init          # init -> refined -> decomposed -> sequenced -> complete
brief: |
{indented}
retired: []          # tombstoned item ids; ids are write-once, never deleted
items: []
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--brief", default="")
    ap.add_argument("--project", default=None)
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--advance", choices=PHASES[1:], default=None)
    args = ap.parse_args()

    root = repo_root(args.repo_root)
    rd = root / "plans" / args.slug
    path = rd / "roadmap.yaml"

    if args.status or args.advance:
        if not path.exists():
            sys.exit(f"ERROR: {path} does not exist")
        doc = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
        cur = doc.get("phase", "init")
        if args.status:
            print(f"phase={cur}")
            return 0
        # --advance: forward one step only
        if cur not in PHASES or PHASES.index(args.advance) != PHASES.index(cur) + 1:
            sys.exit(f"ERROR: cannot advance {cur} -> {args.advance} (one step at a time)")
        # Surgical single-line replace keeps key order/comments intact.
        text = path.read_text(encoding="utf-8-sig")
        new = text.replace(f"phase: {cur}", f"phase: {args.advance}", 1)
        if new == text:
            sys.exit("ERROR: phase line not found for surgical replace — fix manually")
        path.write_text(new, encoding="utf-8")
        print(f"ADVANCED {cur} -> {args.advance}")
        return 0

    if path.exists():
        doc = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
        print(f"RESUMING phase={doc.get('phase', 'init')} path={path}")
        return 0

    progress = rd / "progress"
    progress.mkdir(parents=True, exist_ok=True)
    # .gitkeep so the (initially empty) journal dir survives clones.
    (progress / ".gitkeep").touch()
    project = args.project or derive_project(root)
    path.write_text(scaffold(args.slug, project, args.brief), encoding="utf-8")
    print(f"INITIALIZED path={path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
