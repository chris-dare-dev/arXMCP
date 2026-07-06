#!/usr/bin/env python3
"""milestone-pipeline-resolve-brief.py — resolve a milestone/spike brief by ID.

Usage:
  python3 milestone-pipeline-resolve-brief.py <ITEM_ID> [--repo-root PATH] [--json]

Lookup order:
  1. Canonical: scan <repo-root>/plans/*/roadmap.yaml (roadmap/1 format) for
     the item whose `id` matches. Finding the id in MORE THAN ONE file is a
     hard error (exit 1) — ids are fleet-unique by contract.
  2. Legacy fallback (repos with unmigrated prose roadmaps): search for a
     '### <ID> —' heading in plans/*.md and .claude/roadmap/*.md; extract the
     block up to the next same-or-higher heading. Collision across files is
     also exit 1.

Markdown mode (default) prints:
  source: roadmap <relpath>          (or: source: legacy-prose <relpath>)
  <blank line>
  <markdown brief: title, kind, parent epic, summary, acceptance criteria,
   depends_on with title+status, lane, target dates, roadmap slug+path>

--json prints a single JSON object with the raw item plus resolution context.

Exit codes:
  0  found (either source)
  1  ambiguous — id found in more than one file (message lists all paths)
  2  not found anywhere (or usage error)

Stdlib + PyYAML only. Never writes anything.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

# Force UTF-8 stdout/stderr so briefs with non-ASCII content do not crash on
# Windows's default cp1252 codepage.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def normalize_dates(obj):
    """Coerce datetime.date/datetime (PyYAML bare-date parsing) to ISO strings."""
    if isinstance(obj, dict):
        return {k: normalize_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalize_dates(v) for v in obj]
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    if isinstance(obj, datetime.date):
        return obj.isoformat()
    return obj


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
        # Script lives at <root>/.claude/scripts/<this-file> when synced.
        return Path(__file__).resolve().parents[2]


def scan_roadmaps(root: Path, item_id: str) -> list[tuple[Path, dict, dict]]:
    """Return [(path, doc, item)] for every roadmap.yaml containing item_id."""
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
                hits.append((path, normalize_dates(doc), normalize_dates(it)))
                break
    return hits


HEADING_RE = re.compile(r"^(#{1,6})\s")


def legacy_search(root: Path, item_id: str) -> list[tuple[Path, str]]:
    """Return [(path, block)] for '### <ID> —' headings in legacy prose files."""
    pat = re.compile(
        r"^(#{3,6})\s+" + re.escape(item_id) + r"\s+(?:—|–|--|-)(?:\s|$)"
    )
    hits = []
    for rel_glob in ("plans/*.md", ".claude/roadmap/*.md"):
        for path in sorted(root.glob(rel_glob)):
            try:
                lines = path.read_text(encoding="utf-8-sig").splitlines()
            except Exception as e:
                print(f"warning: skipping unreadable {path}: {e}", file=sys.stderr)
                continue
            for i, line in enumerate(lines):
                m = pat.match(line)
                if not m:
                    continue
                level = len(m.group(1))
                block = [line]
                for nxt in lines[i + 1:]:
                    h = HEADING_RE.match(nxt)
                    if h and len(h.group(1)) <= level:
                        break
                    block.append(nxt)
                hits.append((path, "\n".join(block).rstrip() + "\n"))
                break  # first match per file; cross-file collisions handled by caller
    return hits


def rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def dep_context(doc: dict, item: dict) -> list[dict]:
    by_id = {it.get("id"): it for it in doc.get("items") or [] if isinstance(it, dict)}
    out = []
    for dep in item.get("depends_on") or []:
        d = by_id.get(dep) or {}
        out.append({
            "id": dep,
            "title": d.get("title"),
            "status": d.get("status", "planned"),
        })
    return out


def build_brief(item_id: str, path_rel: str, doc: dict, item: dict) -> str:
    by_id = {it.get("id"): it for it in doc.get("items") or [] if isinstance(it, dict)}
    lines = [f"# Milestone brief — {item_id}", ""]
    lines.append(f"**Title:** {item.get('title', '(untitled)')}")
    lines.append(f"**Kind:** {item.get('kind', '(unspecified)')}")
    lines.append(f"**Roadmap:** {doc.get('slug', '?')} ({path_rel})")
    lines.append(f"**Status:** {item.get('status', 'planned')}")
    if item.get("lane"):
        lines.append(f"**Lane:** {item['lane']}")
    ts, te = item.get("target_start"), item.get("target_end")
    if ts or te:
        lines.append(f"**Target:** {ts or '?'} -> {te or '?'}")

    lines += ["", "## Parent epic", ""]
    parent_id = item.get("parent")
    parent = by_id.get(parent_id) if parent_id else None
    if parent:
        lines.append(f"- {parent_id} — {parent.get('title', '(untitled)')}")
        if parent.get("summary"):
            lines.append(f"  {str(parent['summary']).strip()}")
    elif parent_id:
        lines.append(f"- {parent_id} — (id not found in this roadmap)")
    else:
        lines.append("- (top-level item; no parent epic)")

    lines += ["", "## Summary", ""]
    lines.append(str(item.get("summary") or
                     "(none in roadmap — derive scope from the acceptance criteria)").strip())

    lines += ["", "## Acceptance criteria", ""]
    acceptance = item.get("acceptance") or []
    if acceptance:
        lines += [f"{i}. {a}" for i, a in enumerate(acceptance, 1)]
    else:
        lines.append("(none listed — surface this as a gap before implementing)")

    lines += ["", "## Depends on", ""]
    deps = dep_context(doc, item)
    if deps:
        for d in deps:
            title = d["title"] or "(id not found in this roadmap)"
            lines.append(f"- {d['id']} — {title} [status: {d['status']}]")
    else:
        lines.append("- (none)")

    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="resolve a milestone/spike brief by ID")
    ap.add_argument("item_id")
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    root = find_repo_root(args.repo_root)
    hits = scan_roadmaps(root, args.item_id)

    if len(hits) > 1:
        print(f"error: id {args.item_id!r} found in {len(hits)} roadmap files "
              "(ids must be fleet-unique):", file=sys.stderr)
        for path, _, _ in hits:
            print(f"  - {rel(path, root)}", file=sys.stderr)
        print("       retire/rename one of them, then retry.", file=sys.stderr)
        return 1

    if len(hits) == 1:
        path, doc, item = hits[0]
        path_rel = rel(path, root)
        if args.as_json:
            by_id = {it.get("id"): it for it in doc.get("items") or []
                     if isinstance(it, dict)}
            payload = {
                "id": args.item_id,
                "source": {"kind": "roadmap", "path": path_rel,
                           "slug": doc.get("slug")},
                "roadmap": {k: doc.get(k) for k in
                            ("slug", "project", "title", "status", "phase")},
                "item": item,
                "parent": by_id.get(item.get("parent")),
                "depends_on": dep_context(doc, item),
            }
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"source: roadmap {path_rel}")
            print()
            print(build_brief(args.item_id, path_rel, doc, item), end="")
        return 0

    # Legacy prose fallback.
    legacy = legacy_search(root, args.item_id)
    if len(legacy) > 1:
        print(f"error: heading for {args.item_id!r} found in {len(legacy)} prose files:",
              file=sys.stderr)
        for path, _ in legacy:
            print(f"  - {rel(path, root)}", file=sys.stderr)
        print("       consolidate to one file, then retry.", file=sys.stderr)
        return 1

    if len(legacy) == 1:
        path, block = legacy[0]
        path_rel = rel(path, root)
        if args.as_json:
            payload = {
                "id": args.item_id,
                "source": {"kind": "legacy-prose", "path": path_rel},
                "brief": block,
            }
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"source: legacy-prose {path_rel}")
            print()
            print(block, end="")
        return 0

    print(f"error: {args.item_id!r} not found in plans/*/roadmap.yaml, plans/*.md, "
          "or .claude/roadmap/*.md", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
