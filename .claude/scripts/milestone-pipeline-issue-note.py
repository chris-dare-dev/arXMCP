#!/usr/bin/env python3
"""milestone-pipeline-issue-note.py -- compose (and optionally post) the
conventions-format progress comment for a milestone's GitHub issue.

The journal-to-issue half of the execution-state sync (DESIGN 2.3): the
orchestrator invokes this at pipeline checkpoints; the target issue comes
from the item's links.issue (populated by the roadmap materializer's
backfill). Posting is an ANNOTATE-class write (github-conventions.md):
auto-allowed, ORCHESTRATOR ONLY, on the issue in hand -- leaf agents never
run this script.

Body format (github-conventions.md, Progress comments):

    **Status:** in-progress | blocked | done | handed-off
    **Did:** <what changed, 1-3 lines>
    **Commits:** <shas, or "none yet">
    **Next:** <next concrete step>
    **Blockers:** <none | what + who or what unblocks>

--status takes the COMMENT vocabulary above, not the journal's
(journal in_progress -> comment in-progress; journal dropped has no comment
status -- a dropped item's issue closes "not planned" via the structural
path; handed-off exists only here). The script never reads or writes the
journal, roadmap.yaml, or state.json fields -- it only READS state.json to
default --commits.

Degradation (never blocks a pipeline close-out): id untracked, empty
links.issue, gh missing/unauthed, or a failed comment -> warning + exit 0
(payload printed on post-failure so nothing is lost). Exit 1 = id in more
than one roadmap. Exit 2 = usage.

Usage:
  milestone-pipeline-issue-note.py <ITEM_ID> --status done [--did "..."]
      [--commits "..."] [--next "..."] [--blockers "..."] [--post]
      [--repo-root PATH]
  milestone-pipeline-issue-note.py --self-test

Stdlib + PyYAML only. roadmap.yaml is read utf-8-sig (BOM-tolerant).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

STATUSES = ("in-progress", "blocked", "done", "handed-off")


def gh(args: list[str], input_text: str | None = None) -> subprocess.CompletedProcess | None:
    """Run gh; None when the binary is missing (caller degrades, never dies)."""
    try:
        return subprocess.run(["gh", *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", check=False,
                              input=input_text)
    except FileNotFoundError:
        return None


def find_repo_root(override: str | None) -> Path:
    if override:
        p = Path(override).resolve()
        if not p.is_dir():
            sys.exit(f"error: --repo-root {override!r} is not a directory")
        return p
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True)
        top = out.stdout.strip()
        if top:
            return Path(top)
    except Exception:
        pass
    return Path(__file__).resolve().parents[2]


def scan_roadmaps(root: Path, item_id: str) -> list[tuple[Path, dict]]:
    hits: list[tuple[Path, dict]] = []
    for roadmap in sorted(root.glob("plans/*/roadmap.yaml")):
        try:
            doc = yaml.safe_load(roadmap.read_text(encoding="utf-8-sig"))
        except Exception as e:
            print(f"warning: unparseable {roadmap}: {e}", file=sys.stderr)
            continue
        if not isinstance(doc, dict):
            continue
        for item in doc.get("items") or []:
            if isinstance(item, dict) and item.get("id") == item_id:
                hits.append((roadmap, item))
    return hits


def default_commits(root: Path, item_id: str) -> str:
    """Short shas from state.json when present; 'none yet' otherwise."""
    sp = root / ".claude" / "notes" / "milestones" / item_id / "state.json"
    if not sp.is_file():
        return "none yet"
    try:
        state = json.loads(sp.read_text(encoding="utf-8-sig"))
    except Exception:
        return "none yet"
    if not isinstance(state, dict):
        return "none yet"
    shas = [s[:7] for s in state.get("implementation_commits") or []]
    rect = state.get("rectification_commit")
    if rect:
        shas.append(f"{rect[:7]} (rect)")
    return ", ".join(shas) if shas else "none yet"


def compose(status: str, did: str, commits: str, nxt: str, blockers: str) -> str:
    return "\n".join([
        f"**Status:** {status}",
        f"**Did:** {did}",
        f"**Commits:** {commits}",
        f"**Next:** {nxt}",
        f"**Blockers:** {blockers}",
    ])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="compose/post the conventions-format progress comment")
    ap.add_argument("item_id", nargs="?", help="roadmap item id")
    ap.add_argument("--status", choices=STATUSES,
                    help="comment vocabulary, NOT journal tokens")
    ap.add_argument("--did", default="-")
    ap.add_argument("--commits", default=None,
                    help="default: short shas from state.json, else 'none yet'")
    ap.add_argument("--next", dest="nxt", default="-")
    ap.add_argument("--blockers", default="none")
    ap.add_argument("--post", action="store_true",
                    help="run gh issue comment (ANNOTATE; orchestrator only)")
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()
    if not args.item_id or not args.status:
        ap.error("item_id and --status are required")

    root = find_repo_root(args.repo_root)
    hits = scan_roadmaps(root, args.item_id)
    if len(hits) > 1:
        paths = ", ".join(str(p) for p, _ in hits)
        print(f"error: {args.item_id} found in more than one roadmap: {paths}",
              file=sys.stderr)
        return 1
    if not hits:
        print(f"warning: {args.item_id} not found in any plans/*/roadmap.yaml; "
              "no comment target -- nothing to do", file=sys.stderr)
        return 0
    _, item = hits[0]
    urls = (item.get("links") or {}).get("issue") or []
    if not urls:
        print(f"warning: {args.item_id} has no links.issue (not materialized or "
              "not backfilled); nothing to do", file=sys.stderr)
        return 0
    target = urls[0]
    if len(urls) > 1:
        print("also linked: " + ", ".join(urls[1:]))

    commits = args.commits if args.commits is not None else default_commits(root, args.item_id)
    body = compose(args.status, args.did, commits, args.nxt, args.blockers)

    print(f"target: {target}")
    if not args.post:
        print(body)
        return 0

    r = gh(["issue", "comment", target, "--body-file", "-"], input_text=body)
    if r is None:
        print("warning: gh binary not found; comment not posted. Payload:",
              file=sys.stderr)
        print(body)
        return 0
    if r.returncode != 0:
        err = (r.stderr or "").strip()[:300]
        print(f"warning: gh issue comment failed ({err}); comment not posted. "
              "Payload:", file=sys.stderr)
        print(body)
        return 0
    print(f"commented: {target}")
    return 0


# ---------------------------------------------------------------------------
# Offline self-test: fake gh + tempdir fixtures.
# ---------------------------------------------------------------------------


class _FakeGH:
    def __init__(self, rc: int = 0, stderr: str = ""):
        self.calls: list[list[str]] = []
        self.bodies: list[str] = []
        self.rc, self.stderr = rc, stderr

    def __call__(self, args, input_text=None):
        self.calls.append(list(args))
        self.bodies.append(input_text or "")
        return subprocess.CompletedProcess([], self.rc, stdout="", stderr=self.stderr)


def _self_test() -> int:
    import contextlib
    import io
    import tempfile

    failures: list[str] = []

    def check(name: str, cond: bool) -> None:
        if not cond:
            failures.append(name)

    def run(fake, extra: list[str], root: str) -> tuple[int, str]:
        global gh
        real, gh = gh, fake
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                code = main([*extra, "--repo-root", root])
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
        finally:
            gh = real
        return code, buf.getvalue()

    url = "https://github.com/o/r/issues/7"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        plan = root / "plans" / "demo"
        plan.mkdir(parents=True)
        (plan / "roadmap.yaml").write_text(
            "schema: roadmap/1\nslug: demo\nitems:\n"
            f"  - id: demo-m1\n    kind: milestone\n    links:\n      issue: [\"{url}\"]\n"
            "  - id: demo-m2\n    kind: milestone\n"
            f"  - id: demo-m3\n    kind: milestone\n    links:\n"
            f"      issue: [\"{url}\", \"https://github.com/o/r/issues/8\"]\n",
            encoding="utf-8")
        sd = root / ".claude" / "notes" / "milestones" / "demo-m1"
        sd.mkdir(parents=True)
        (sd / "state.json").write_text(json.dumps(
            {"implementation_commits": ["abcdef0123456789"],
             "rectification_commit": "1234567abcdef"}), encoding="utf-8")

        # 1. --post happy path: one comment argv, five fields in order, exit 0.
        fake = _FakeGH()
        code, out = run(fake, ["demo-m1", "--status", "done", "--did", "shipped"], root=str(root))
        check("print_no_gh_calls", fake.calls == [])  # no --post yet (case 2 first)
        check("print_payload", "**Status:** done" in out and "**Did:** shipped" in out)
        check("print_commits_from_state", "abcdef0 " in out or "abcdef0," in out
              or "abcdef0" in out)
        fake = _FakeGH()
        code, out = run(fake, ["demo-m1", "--status", "in-progress", "--post"], root=str(root))
        check("post_exit0", code == 0)
        check("post_one_call", len(fake.calls) == 1
              and fake.calls[0][:3] == ["issue", "comment", url]
              and "--body-file" in fake.calls[0])
        check("post_body_transmitted", len(fake.bodies) == 1 and all(
            f"**{k}:**" in fake.bodies[0]
            for k in ("Status", "Did", "Commits", "Next", "Blockers"))
            and "**Status:** in-progress" in fake.bodies[0])
        check("post_confirms", "commented: " + url in out)

        # 3. No links.issue -> warn + exit 0, zero calls.
        fake = _FakeGH()
        code, out = run(fake, ["demo-m2", "--status", "done", "--post"], root=str(root))
        check("nolinks_exit0", code == 0 and fake.calls == [])
        check("nolinks_warns", "no links.issue" in out)

        # 4. Untracked id -> warn exit 0; ambiguous id -> exit 1.
        fake = _FakeGH()
        code, out = run(fake, ["demo-m9", "--status", "done"], root=str(root))
        check("untracked_exit0", code == 0 and "not found" in out)
        other = root / "plans" / "other"
        other.mkdir(parents=True)
        (other / "roadmap.yaml").write_text(
            "schema: roadmap/1\nslug: other\nitems:\n  - id: demo-m1\n    kind: milestone\n",
            encoding="utf-8")
        code, out = run(_FakeGH(), ["demo-m1", "--status", "done"], root=str(root))
        check("ambiguous_exit1", code == 1 and "more than one roadmap" in out)
        (other / "roadmap.yaml").unlink()
        other.rmdir()

        # 5. gh binary missing: patch subprocess.run so the real gh() degrades.
        real_run = subprocess.run

        def raiser(cmd, **kw):
            if cmd and cmd[0] == "gh":
                raise FileNotFoundError("gh")
            return real_run(cmd, **kw)

        subprocess.run = raiser
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                code = main(["demo-m1", "--status", "done", "--post",
                             "--repo-root", str(root)])
            out = buf.getvalue()
        finally:
            subprocess.run = real_run
        check("nogh_exit0", code == 0)
        check("nogh_payload_printed", "gh binary not found" in out and "**Status:** done" in out)

        # 6. Comment fails -> warn + payload + exit 0.
        fake = _FakeGH(rc=1, stderr="HTTP 401: auth")
        code, out = run(fake, ["demo-m1", "--status", "blocked", "--post"], root=str(root))
        check("fail_exit0", code == 0)
        check("fail_payload", "comment failed" in out and "**Status:** blocked" in out)

        # 7. Multi-URL: first targeted, remainder listed.
        fake = _FakeGH()
        code, out = run(fake, ["demo-m3", "--status", "done", "--post"], root=str(root))
        check("multi_first", fake.calls and fake.calls[0][2] == url)
        check("multi_rest_listed", "also linked: https://github.com/o/r/issues/8" in out)

        # 8. Journal-vocabulary token -> argparse exit 2.
        code, out = run(_FakeGH(), ["demo-m1", "--status", "in_progress"], root=str(root))
        check("badstatus_exit2", code == 2)

    if failures:
        print("SELF-TEST FAILED: " + ", ".join(failures))
        return 1
    print("self-test OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
