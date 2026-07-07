#!/usr/bin/env python3
"""sync-repos.py — copy-sync registry data tiers into consuming repos.

Usage:
  python3 sync-repos.py [--check] [--dry-run] [--repo <path> ...]

Without --repo, targets every repo listed in repos-manifest.txt (one path per
line, relative to the Source Code directory two levels above this registry,
'#' comments allowed).

Mapping (registry -> consumer):
  data/commands/*.md    -> .claude/commands/
  data/agents/*.md      -> .claude/agents/
  data/references/*.md  -> .claude/references/
  data/scripts/*        -> .claude/scripts/

Every synced file is recorded (sha256) in .claude/.registry-manifest.json in
the consumer. Rules:
  - files NOT in the manifest are repo-local overlays: never touched
  - files in the manifest whose local hash differs from the last-synced hash
    have local edits: --check reports them; sync refuses to clobber and lists
    them (fix by editing the registry copy, then re-sync)
  - files removed from the registry are deleted from the consumer on sync
--check reports drift without writing. --dry-run prints planned actions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

REGISTRY = Path(__file__).resolve().parents[2]  # .../claude-registry
TIERS = {
    "commands": ".claude/commands",
    "agents": ".claude/agents",
    "references": ".claude/references",
    "scripts": ".claude/scripts",
}
MANIFEST_NAME = ".registry-manifest.json"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def registry_files() -> dict[str, Path]:
    """rel-dest-path -> registry source path"""
    out: dict[str, Path] = {}
    for tier, dest in TIERS.items():
        src_dir = REGISTRY / "data" / tier
        if not src_dir.is_dir():
            continue
        for f in sorted(src_dir.iterdir()):
            if f.is_file():
                out[f"{dest}/{f.name}"] = f
    return out


def target_repos(cli_repos: list[str]) -> list[Path]:
    if cli_repos:
        return [Path(r).resolve() for r in cli_repos]
    manifest = REGISTRY / "data" / "scripts" / "repos-manifest.txt"
    source_code = REGISTRY.parent
    repos = []
    for line in manifest.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            repos.append((source_code / line).resolve())
    return repos


def sync_repo(repo: Path, files: dict[str, Path], check: bool, dry: bool) -> int:
    """Returns number of problems (drift under --check, refusals under sync)."""
    mpath = repo / ".claude" / MANIFEST_NAME
    old = json.loads(mpath.read_text()) if mpath.exists() else {}
    problems = 0
    new_manifest: dict[str, str] = {}
    actions: list[str] = []

    for rel, src in files.items():
        dest = repo / rel
        src_hash = sha(src)
        new_manifest[rel] = src_hash
        if dest.exists():
            local = sha(dest)
            if local == src_hash:
                continue  # up to date
            if rel in old and old[rel] != local:
                # local edits on a synced file — never clobber
                actions.append(f"  DRIFT   {rel} (locally edited since last sync)")
                problems += 1
                new_manifest[rel] = old[rel]  # keep old record until resolved
                continue
            actions.append(f"  UPDATE  {rel}")
        else:
            actions.append(f"  ADD     {rel}")
        if not check and not dry:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    # removals: previously synced, no longer in registry
    for rel in sorted(set(old) - set(files)):
        dest = repo / rel
        if dest.exists():
            actions.append(f"  REMOVE  {rel}")
            if not check and not dry:
                dest.unlink()

    if actions:
        print(f"{repo.name}:")
        print("\n".join(actions))
    else:
        print(f"{repo.name}: clean")
    if not check and not dry:
        mpath.parent.mkdir(parents=True, exist_ok=True)
        mpath.write_text(json.dumps(new_manifest, indent=2, sort_keys=True) + "\n")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--repo", action="append", default=[])
    args = ap.parse_args()

    files = registry_files()
    problems = 0
    for repo in target_repos(args.repo):
        if not repo.is_dir():
            print(f"{repo}: MISSING — skipped")
            problems += 1
            continue
        problems += sync_repo(repo, files, args.check, args.dry_run)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
