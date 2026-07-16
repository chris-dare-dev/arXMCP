#!/usr/bin/env python3
"""roadmap-to-github.py -- materialize a roadmap/1 YAML into GitHub.

Creates one GitHub Milestone for the roadmap, one issue per item (epic /
milestone / task / spike) with the item ID as the title prefix, and links
children to parents as native sub-issues. See github-conventions.md.

DRY-RUN BY DEFAULT: prints the plan and mutates nothing. Pass --apply to create.
Idempotent: each issue body carries a hidden marker
`<!-- roadmap-gh: <slug>/<id> -->`; a re-run skips items whose marker already
exists on the repo.

Milestone/issue creation and sub-issue links are STRUCTURAL writes and are
user-gated: running with --apply IS the authorization, and the orchestrator
must obtain an explicit [y] before invoking it (see runtime-contract.md).

Usage:
  python3 roadmap-to-github.py --repo owner/name --roadmap plans/<slug>/roadmap.yaml
  python3 roadmap-to-github.py --repo owner/name --roadmap ... --apply
  python3 roadmap-to-github.py --repo owner/name --roadmap ... --apply --project <N>

Requires: PyYAML + the gh CLI (repo scope; project scope when --project is used).
Lane / Priority / Size are Mission Control fields; setting them is a follow-on.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MARKER_RE = re.compile(r"<!-- roadmap-gh: (?P<key>\S+) -->")
LABELS_BY_KIND = {
    "epic": ["epic"],
    "milestone": ["type:task"],
    "task": ["type:task"],
    "spike": ["type:spike"],
}
CREATE_ORDER = {"epic": 0, "milestone": 1, "task": 2, "spike": 2}


def gh(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=check)


def marker_for(slug: str, item_id: str) -> str:
    return f"{slug}/{item_id}"


def existing_by_marker(repo: str) -> dict[str, dict]:
    """marker-key -> {number, node} for every issue already carrying a marker."""
    r = gh(["issue", "list", "--repo", repo, "--state", "all",
            "--limit", "1000", "--json", "number,id,body"])
    out: dict[str, dict] = {}
    for issue in json.loads(r.stdout or "[]"):
        m = MARKER_RE.search(issue.get("body") or "")
        if m:
            out[m.group("key")] = {"number": issue["number"], "node": issue["id"]}
    return out


def ensure_milestone(repo: str, title: str) -> None:
    r = gh(["api", f"repos/{repo}/milestones", "--jq", ".[].title"], check=False)
    if title in [t for t in (r.stdout or "").splitlines() if t]:
        return
    gh(["api", f"repos/{repo}/milestones", "-f", f"title={title}"])
    print(f"  created milestone: {title}")


def build_body(item: dict, slug: str, number_by_id: dict[str, int]) -> str:
    lines: list[str] = []
    if item.get("summary"):
        lines += [item["summary"], ""]
    acc = item.get("acceptance") or []
    if acc:
        lines.append("**Acceptance**")
        lines += [f"- {a}" for a in acc]
        lines.append("")
    parent = item.get("parent")
    if parent:
        ref = f"#{number_by_id[parent]}" if parent in number_by_id else parent
        lines.append(f"Parent: {ref}")
    dep = item.get("depends_on") or []
    if dep:
        refs = ", ".join(f"#{number_by_id[d]}" if d in number_by_id else d for d in dep)
        lines.append(f"Depends on: {refs}")
    if item.get("tags"):
        lines.append("Tags: " + ", ".join(item["tags"]))
    meta = " ".join(f"{k}={item[k]}" for k in ("priority", "size", "lane") if item.get(k))
    if meta:
        lines.append(f"_{meta} (Lane/Priority/Size live as Project fields)_")
    lines += ["", f"<!-- roadmap-gh: {marker_for(slug, item['id'])} -->"]
    return "\n".join(lines)


def create_issue(repo: str, item: dict, slug: str, milestone: str,
                 number_by_id: dict[str, int]) -> int:
    title = f"{item['id']}: {item.get('title', '')}".strip().rstrip(":").strip()
    args = ["issue", "create", "--repo", repo, "--title", title,
            "--body", build_body(item, slug, number_by_id), "--milestone", milestone]
    for label in LABELS_BY_KIND.get(item["kind"], []):
        args += ["--label", label]
    url = (gh(args).stdout or "").strip().splitlines()[-1]
    return int(url.rstrip("/").split("/")[-1])


def link_sub_issue(parent_node: str, child_node: str) -> None:
    query = ('mutation { addSubIssue(input: {issueId: "' + parent_node
             + '", subIssueId: "' + child_node + '"}) { issue { number } } }')
    gh(["api", "graphql", "-f", f"query={query}"], check=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--roadmap", required=True, help="path to roadmap.yaml")
    ap.add_argument("--apply", action="store_true", help="create (default: dry-run)")
    ap.add_argument("--project", type=int, help="project number to add items to")
    args = ap.parse_args()

    rm = yaml.safe_load(Path(args.roadmap).read_text(encoding="utf-8-sig"))
    slug = rm["slug"]
    milestone = rm.get("title") or slug
    items = [i for i in rm.get("items", []) if i.get("id") and i.get("kind")]

    existing = existing_by_marker(args.repo)
    todo = [i for i in items if marker_for(slug, i["id"]) not in existing]

    print(f"roadmap: {slug}  ->  {args.repo}")
    print(f"milestone: {milestone}")
    print(f"items: {len(items)}  on-github: {len(items) - len(todo)}  to-create: {len(todo)}")
    for i in todo:
        print(f"  + [{i['kind']}] {i['id']}: {i.get('title', '')}")
    if not args.apply:
        print("\n(dry-run -- pass --apply to create; each --apply is a user-gated write)")
        return 0

    ensure_milestone(args.repo, milestone)
    number_by_id = {k.split("/", 1)[1]: v["number"] for k, v in existing.items()
                    if k.startswith(slug + "/")}
    for item in sorted(todo, key=lambda i: CREATE_ORDER.get(i["kind"], 3)):
        num = create_issue(args.repo, item, slug, milestone, number_by_id)
        number_by_id[item["id"]] = num
        print(f"  created #{num}  {item['id']}")

    fresh = existing_by_marker(args.repo)
    node_by_id = {k.split("/", 1)[1]: v["node"] for k, v in fresh.items()
                  if k.startswith(slug + "/")}
    for item in items:
        parent = item.get("parent")
        if parent and parent in node_by_id and item["id"] in node_by_id:
            link_sub_issue(node_by_id[parent], node_by_id[item["id"]])
            print(f"  linked {item['id']} -> {parent}")

    if args.project:
        owner = args.repo.split("/", 1)[0]
        for item in items:
            num = number_by_id.get(item["id"])
            if num:
                gh(["project", "item-add", str(args.project), "--owner", owner,
                    "--url", f"https://github.com/{args.repo}/issues/{num}"], check=False)
        print(f"  added items to project #{args.project} (fields not set -- follow-on)")

    print("\ndone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
