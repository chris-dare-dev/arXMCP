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
  data/skills/<name>/** -> .claude/skills/<name>/**
  data/github/**        -> .github/**  (issue/PR templates; subtree)

The first four tiers are FLAT: top-level files only, subdirectories are ignored
(prefix-namespace instead, e.g. `frontend-uplift-phase-1.md`). `skills/` is the
one exception -- Claude Code discovers a skill as `.claude/skills/<name>/SKILL.md`,
so a skill is a DIRECTORY and its whole tree (SKILL.md plus any assets/) is synced.
Manifest keys are destination-relative paths, so nested entries work unchanged.

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
SKILLS_TIER = "skills"
SKILLS_DEST = ".claude/skills"
GITHUB_TIER = "github"
GITHUB_DEST = ".github"
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

    # skills/ is dir-per-skill, not flat: Claude Code discovers
    # `.claude/skills/<name>/SKILL.md`, and a skill may carry assets/ alongside.
    # Sync the whole subtree; a skill dir without SKILL.md is not a skill, skip it.
    skills_dir = REGISTRY / "data" / SKILLS_TIER
    if skills_dir.is_dir():
        for skill in sorted(skills_dir.iterdir()):
            if not skill.is_dir() or not (skill / "SKILL.md").is_file():
                continue
            for f in sorted(skill.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(skills_dir).as_posix()
                    out[f"{SKILLS_DEST}/{rel}"] = f

    # .github subtree (issue/PR templates): mirror data/github/** -> .github/**.
    # A consumer's own .github/workflows and dependabot.yml are not under
    # data/github, so they are overlays and are never touched.
    github_dir = REGISTRY / "data" / GITHUB_TIER
    if github_dir.is_dir():
        for f in sorted(github_dir.rglob("*")):
            if f.is_file():
                rel = f.relative_to(github_dir).as_posix()
                out[f"{GITHUB_DEST}/{rel}"] = f
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
    pruned: set[Path] = set()
    for rel in sorted(set(old) - set(files)):
        dest = repo / rel
        if dest.exists():
            actions.append(f"  REMOVE  {rel}")
            if not check and not dry:
                dest.unlink()
                pruned.add(dest.parent)

    # a removed skill leaves an empty <skill>/ dir that Claude Code would still
    # scan; prune empty dirs under .claude/skills (deepest first), never the tier root.
    skills_root = repo / SKILLS_DEST
    for d in sorted(pruned, key=lambda p: len(p.parts), reverse=True):
        if skills_root in d.parents and d.is_dir() and not any(d.iterdir()):
            d.rmdir()

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
