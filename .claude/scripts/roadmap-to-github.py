#!/usr/bin/env python3
"""roadmap-to-github.py -- materialize a roadmap/1 YAML into GitHub.

Creates one GitHub Milestone for the roadmap, one issue per item (epic /
milestone / task / spike) with the item ID as the title prefix, and links
children to parents as native sub-issues. See github-conventions.md.

DRY-RUN BY DEFAULT: prints the plan and mutates nothing. Pass --apply to create.
Idempotent: each issue body carries a hidden marker
`<!-- roadmap-gh: <slug>/<id> -->`; a re-run skips items whose marker already
exists on the repo.

Hardening (github-sync-integration-m1):
- Items with `status: done` are SKIPPED by default (count always printed).
  `--backfill-done` creates them and then closes them as completed; the
  dry-run plan states each pending close, so the same --apply covers them.
  Closes are computed from the fetched issue `state` (only OPEN issues close).
- `--update` re-renders the managed body of every marker-matched item and
  edits only when the normalized rendering differs from the live body
  (\r\n tolerated); an immediately repeated run performs zero writes.
- A preflight (gh binary, auth payload, token scopes) runs in EVERY mode
  before any read or mutation; failures exit non-zero with a clear message.
- Every mutating call goes through a paced writer (PACE_S) that detects
  secondary-rate-limit rejections and retries with backoff.

Milestone/issue creation, closes, body edits, and sub-issue links are
STRUCTURAL writes and are user-gated: running with --apply IS the
authorization, and the orchestrator must obtain an explicit [y] before
invoking it (see runtime-contract.md).

Usage:
  python3 roadmap-to-github.py --repo owner/name --roadmap plans/<slug>/roadmap.yaml
  python3 roadmap-to-github.py --repo owner/name --roadmap ... --apply
  python3 roadmap-to-github.py --repo owner/name --roadmap ... --apply --project <N>
  python3 roadmap-to-github.py --repo ... --roadmap ... --backfill-done --update --apply
  python3 roadmap-to-github.py --self-test

Requires: PyYAML + the gh CLI (repo scope; project scope when --project is used).
Lane / Priority / Size are Mission Control fields; setting them is a follow-on.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
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

# Secondary content-creation limits are ~80 writes/min (0.75 s floor) and
# 500/hr across REST + GraphQL + web combined -- see DESIGN.md section 9.
PACE_S = 1.0
RETRY_BASE_S = 60.0
RETRY_MAX = 3
LIST_LIMIT = 1000

# 429 and secondary-limit phrasing only. A bare HTTP 403 (permission denied /
# SAML enforcement / "Resource not accessible") must fail fast, not burn three
# 60/120/240 s backoffs; genuine secondary-limit 403s always carry the
# "secondary rate limit" text and still match here.
RATE_RE = re.compile(r"secondary rate limit|submitted too quickly|HTTP 429", re.I)

_sleep = time.sleep  # module-level so the self-test can inject a recorder


def gh(args: list[str], check: bool = True,
       input_text: str | None = None) -> subprocess.CompletedProcess:
    # Pin utf-8: gh emits utf-8, but Windows text mode would otherwise decode
    # with cp1252 and crash on an issue body carrying a non-cp1252 byte (e.g. a
    # dash/quote in acceptance text). errors=replace keeps ASCII markers/ids intact.
    try:
        return subprocess.run(["gh", *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", check=check,
                              input=input_text)
    except FileNotFoundError:
        sys.exit("error: gh binary not found -- install GitHub CLI (https://cli.github.com) "
                 "and run `gh auth login`")


def _parse_wait(text: str) -> float | None:
    m = re.search(r"retry.?after\D*(\d+)", text, re.I)
    return float(m.group(1)) if m else None


def gh_write(args: list[str], input_text: str | None = None,
             fatal: bool = True) -> subprocess.CompletedProcess:
    """Every mutating gh call: paced, secondary-limit-aware, stderr surfaced."""
    err = ""
    for attempt in range(RETRY_MAX + 1):
        r = gh(args, check=False, input_text=input_text)
        if r.returncode == 0:
            _sleep(PACE_S)
            return r
        err = ((r.stderr or "") + (r.stdout or "")).strip()
        if RATE_RE.search(err) and attempt < RETRY_MAX:
            wait = _parse_wait(err) or RETRY_BASE_S * (2 ** attempt)
            print(f"  rate-limited; waiting {int(wait)}s (retry {attempt + 1}/{RETRY_MAX})")
            _sleep(wait)
            continue
        break
    if fatal:
        sys.exit(f"error: gh {' '.join(args[:2])} failed: {err[:300]}")
    print(f"  warning: gh {' '.join(args[:2])} failed: {err[:200]}")
    return r


def preflight(need_project: bool) -> None:
    """Verify gh binary, auth, and scopes BEFORE any read or mutation."""
    r = gh(["--version"], check=False)
    ver = (r.stdout or "").strip().splitlines()[0] if (r.stdout or "").strip() else "unknown"
    if r.returncode != 0:
        sys.exit(f"error: gh --version failed: {(r.stderr or '').strip()[:200]}")
    # --json always exits 0 unless fatal, so inspect the payload, not the code.
    r = gh(["auth", "status", "--json", "hosts"], check=False)
    try:
        hosts = json.loads(r.stdout or "{}").get("hosts") or {}
    except json.JSONDecodeError:
        hosts = {}
    active = None
    for entries in hosts.values():
        for entry in entries:
            if entry.get("active"):
                active = entry
    if active is None or active.get("state") != "success":
        detail = (r.stderr or "").strip()[:200] or "no active authenticated host"
        sys.exit(f"error: gh is not authenticated ({detail}) -- run `gh auth login`")
    scopes = [s.strip() for s in (active.get("scopes") or "").split(",") if s.strip()]
    if not scopes:
        print("  warning: token reports no classic scopes (fine-grained PAT?); proceeding")
    else:
        need = ["repo"] + (["project"] if need_project else [])
        missing = [s for s in need if s not in scopes]
        if missing:
            sys.exit(f"error: gh token missing scope(s): {', '.join(missing)} "
                     "-- run `gh auth refresh -s " + ",".join(missing) + "`")
    print(f"preflight: {ver}; account {active.get('login', '?')}; auth ok")


def marker_for(slug: str, item_id: str) -> str:
    return f"{slug}/{item_id}"


def _norm(body: str) -> str:
    # GitHub returns \r\n on web-edited bodies; trailing newlines are unstable.
    return body.replace("\r\n", "\n").rstrip("\n")


def existing_by_marker(repo: str) -> dict[str, dict]:
    """marker-key -> {number, node, state, body} for every marker-carrying issue."""
    r = gh(["issue", "list", "--repo", repo, "--state", "all",
            "--limit", str(LIST_LIMIT), "--json", "number,id,body,state"], check=False)
    if r.returncode != 0:
        sys.exit(f"error: gh issue list failed: {(r.stderr or '').strip()[:300]}")
    issues = json.loads(r.stdout or "[]")
    if len(issues) >= LIST_LIMIT:
        print(f"  warning: issue list hit the {LIST_LIMIT}-issue cap; markers beyond it are "
              "invisible and skip/update decisions may be wrong -- raise LIST_LIMIT")
    out: dict[str, dict] = {}
    for issue in issues:
        m = MARKER_RE.search(issue.get("body") or "")
        if m:
            out[m.group("key")] = {"number": issue["number"], "node": issue["id"],
                                   "state": issue.get("state", ""),
                                   "body": issue.get("body") or ""}
    return out


def ensure_milestone(repo: str, title: str) -> None:
    r = gh(["api", f"repos/{repo}/milestones", "--jq", ".[].title"], check=False)
    if title in [t for t in (r.stdout or "").splitlines() if t]:
        return
    gh_write(["api", f"repos/{repo}/milestones", "-f", f"title={title}"])
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
    lines = [ln for ln in (gh_write(args).stdout or "").strip().splitlines() if ln.strip()]
    if not lines:
        sys.exit(f"error: issue create returned no URL for {item['id']}")
    return int(lines[-1].rstrip("/").split("/")[-1])


def link_sub_issue(parent_node: str, child_node: str) -> None:
    query = ('mutation { addSubIssue(input: {issueId: "' + parent_node
             + '", subIssueId: "' + child_node + '"}) { issue { number } } }')
    gh_write(["api", "graphql", "-f", f"query={query}"], fatal=False)


def compute_updates(items: list[dict], slug: str,
                    existing: dict[str, dict]) -> list[tuple[str, int, str]]:
    """(item-id, issue-number, rendered-body) for every marker-matched item whose
    normalized managed body differs from the live one. Full number map first, so
    raw-id parent/depends refs resolve to #N deterministically."""
    num_map = {k.split("/", 1)[1]: v["number"] for k, v in existing.items()
               if k.startswith(slug + "/")}
    updates: list[tuple[str, int, str]] = []
    for item in items:
        key = marker_for(slug, item["id"])
        if key not in existing:
            continue
        rendered = build_body(item, slug, num_map)
        if _norm(rendered) != _norm(existing[key]["body"]):
            updates.append((item["id"], existing[key]["number"], rendered))
    return updates


def _emit_issue_map(roadmap_path: str, repo: str,
                    number_by_id: dict[str, int]) -> Path:
    """Write <roadmap-parent>/github/issue-map.json — the durable id -> issue
    record for every marker-matched item of the slug, and the canonical handoff
    for the materializer's links backfill. Byte-stable (sorted keys, no
    timestamps) so re-runs are diff-clean. Apply-only; dry-run never calls this.
    The dir is derived from the roadmap path, never a literal plans/<slug>/,
    so out-of-repo roadmaps work."""
    gh_dir = Path(roadmap_path).resolve().parent / "github"
    gh_dir.mkdir(parents=True, exist_ok=True)
    payload = {iid: {"number": num,
                     "url": f"https://github.com/{repo}/issues/{num}"}
               for iid, num in number_by_id.items()}
    out = gh_dir / "issue-map.json"
    # newline="\n": default text mode would translate to CRLF on Windows,
    # breaking the byte-stability the tracked map depends on across the fleet.
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8", newline="\n")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", help="owner/name")
    ap.add_argument("--roadmap", help="path to roadmap.yaml")
    ap.add_argument("--apply", action="store_true", help="create (default: dry-run)")
    ap.add_argument("--project", type=int, help="project number to add items to")
    ap.add_argument("--backfill-done", action="store_true",
                    help="create status:done items and close them as completed")
    ap.add_argument("--update", action="store_true",
                    help="re-render managed bodies; edit issues whose body drifted")
    ap.add_argument("--self-test", action="store_true", help="run the offline self-test")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()
    if not args.repo or not args.roadmap:
        ap.error("--repo and --roadmap are required")

    rm = yaml.safe_load(Path(args.roadmap).read_text(encoding="utf-8-sig"))
    slug = rm["slug"]
    milestone = rm.get("title") or slug
    items = [i for i in rm.get("items", []) if i.get("id") and i.get("kind")]

    preflight(need_project=bool(args.project))
    existing = existing_by_marker(args.repo)

    done_ids = {i["id"] for i in items if i.get("status") == "done"}
    plan = items if args.backfill_done else [i for i in items if i["id"] not in done_ids]
    todo = [i for i in plan if marker_for(slug, i["id"]) not in existing]
    if not args.backfill_done:
        n_skip = sum(1 for i in items
                     if i["id"] in done_ids and marker_for(slug, i["id"]) not in existing)
        print(f"skipped-done: {n_skip} (use --backfill-done to create-and-close them)")

    # Closes: done items being created now, plus done items already on GitHub
    # but still OPEN. Never rely on gh's already-closed behavior.
    closes: list[str] = []
    if args.backfill_done:
        for i in items:
            if i["id"] not in done_ids:
                continue
            key = marker_for(slug, i["id"])
            if key not in existing or existing[key]["state"] == "OPEN":
                closes.append(i["id"])

    updates = compute_updates(items, slug, existing) if args.update else []

    print(f"roadmap: {slug}  ->  {args.repo}")
    print(f"milestone: {milestone}")
    print(f"items: {len(items)}  on-github: {len(plan) - len(todo)}  to-create: {len(todo)}"
          f"  to-close: {len(closes)}  to-update: {len(updates)}")
    for i in todo:
        print(f"  + [{i['kind']}] {i['id']}: {i.get('title', '')}")
    for item_id in closes:
        print(f"  + close as completed: {item_id}")
    for item_id, num, _body in updates:
        print(f"  ~ update body: {item_id} (#{num})")
    if not args.apply:
        print("\n(dry-run -- pass --apply to create; each --apply is a user-gated write)")
        return 0

    if todo:
        ensure_milestone(args.repo, milestone)
    number_by_id = {k.split("/", 1)[1]: v["number"] for k, v in existing.items()
                    if k.startswith(slug + "/")}
    for item in sorted(todo, key=lambda i: CREATE_ORDER.get(i["kind"], 3)):
        num = create_issue(args.repo, item, slug, milestone, number_by_id)
        number_by_id[item["id"]] = num
        print(f"  created #{num}  {item['id']}")
        # Incremental: a rate-limit abort mid-run must not lose minted numbers.
        _emit_issue_map(args.roadmap, args.repo, number_by_id)

    for item_id in closes:
        num = number_by_id.get(item_id)
        if num is None:
            print(f"  warning: no issue number for {item_id}; skipping close")
            continue
        gh_write(["issue", "close", str(num), "--repo", args.repo, "--reason", "completed"])
        print(f"  closed #{num}  {item_id}")

    fresh = existing_by_marker(args.repo) if (todo or closes) else existing
    if todo:
        # Link pass only when something was created -- re-linking on every run
        # would be a mutating no-op that breaks the zero-write guarantee.
        node_by_id = {k.split("/", 1)[1]: v["node"] for k, v in fresh.items()
                      if k.startswith(slug + "/")}
        for item in items:
            parent = item.get("parent")
            if parent and parent in node_by_id and item["id"] in node_by_id:
                link_sub_issue(node_by_id[parent], node_by_id[item["id"]])
                print(f"  linked {item['id']} -> {parent}")

    if args.update:
        if todo or closes:
            # Re-render only bodies that pre-existed this run. Newly-created
            # bodies are already fresh; their same-tier raw-id refs get
            # normalized by the next --update run (which lists them in its own
            # dry-run), so the writes here equal the dry-run plan exactly.
            preexisting = [i for i in items if marker_for(slug, i["id"]) in existing]
            updates = compute_updates(preexisting, slug, fresh)
        for item_id, num, body in updates:
            gh_write(["issue", "edit", str(num), "--repo", args.repo, "--body-file", "-"],
                     input_text=body)
            print(f"  updated body #{num}  {item_id}")

    if args.project:
        owner = args.repo.split("/", 1)[0]
        for item in items:
            num = number_by_id.get(item["id"])
            if num:
                gh_write(["project", "item-add", str(args.project), "--owner", owner,
                          "--url", f"https://github.com/{args.repo}/issues/{num}"],
                         fatal=False)
        print(f"  added items to project #{args.project} (fields not set -- follow-on)")

    # Final regeneration from the complete marker map: self-heals after a
    # crashed session and includes items materialized by earlier runs (and
    # retired/tombstoned markers -- the map is the truthful full record).
    final_numbers = {k.split("/", 1)[1]: v["number"] for k, v in fresh.items()
                     if k.startswith(slug + "/")}
    map_path = _emit_issue_map(args.roadmap, args.repo, final_numbers)
    print(f"issue-map: {map_path}")
    # The re-dispatch string covers only ids present in the CURRENT roadmap
    # (the materializer cannot backfill a retired item), in roadmap file order.
    pairs = " ".join(
        f"{i['id']}=https://github.com/{args.repo}/issues/{final_numbers[i['id']]}"
        for i in items if i["id"] in final_numbers)
    if pairs:
        print(f'--issues "{pairs}"')

    print("\ndone.")
    return 0


# ---------------------------------------------------------------------------
# Offline self-test: injects a fake gh; asserts on exact mutating argv.
# ---------------------------------------------------------------------------

_AUTH_OK = {"hosts": {"github.com": [{"active": True, "state": "success",
                                      "login": "tester", "scopes": "project, repo"}]}}


class _FakeGH:
    """Scripted gh: routes argv to a tiny in-memory issue store."""

    def __init__(self, issues: list[dict] | None = None, auth: dict | None = None,
                 fail_first: dict | None = None):
        self.issues = list(issues or [])
        self.auth = auth if auth is not None else _AUTH_OK
        self.fail_first = dict(fail_first or {})  # verb -> stderr for first call
        self.writes: list[list[str]] = []
        self.next_num = 100

    def _ok(self, stdout: str = "") -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")

    def __call__(self, args, check=True, input_text=None):
        verb = " ".join(args[:2])
        if verb in self.fail_first:
            stderr = self.fail_first.pop(verb)
            return subprocess.CompletedProcess([], 1, stdout="", stderr=stderr)
        if args[0] == "--version":
            return self._ok("gh version 2.92.0 (2026-04-28)\n")
        if verb == "auth status":
            return self._ok(json.dumps(self.auth))
        if verb == "issue list":
            return self._ok(json.dumps(self.issues))
        if args[0] == "api" and args[1].endswith("/milestones") and "-f" not in args:
            return self._ok("")
        self.writes.append(list(args))
        if verb == "issue create":
            num = self.next_num = self.next_num + 1
            body = args[args.index("--body") + 1]
            self.issues.append({"number": num, "id": f"node{num}", "state": "OPEN",
                                "body": body})
            return self._ok(f"https://github.com/o/r/issues/{num}\n")
        if verb == "issue close":
            for issue in self.issues:
                if issue["number"] == int(args[2]):
                    issue["state"] = "CLOSED"
            return self._ok()
        if verb == "issue edit":
            for issue in self.issues:
                if issue["number"] == int(args[2]):
                    issue["body"] = input_text or ""
            return self._ok()
        return self._ok()


def _self_test() -> int:
    import contextlib
    import io
    import tempfile

    global gh, _sleep
    failures: list[str] = []

    def check(name: str, cond: bool) -> None:
        if not cond:
            failures.append(name)

    def run(fake: _FakeGH, extra: list[str], roadmap_path: str) -> tuple[int, str]:
        global gh, _sleep
        real_gh, real_sleep = gh, _sleep
        slept: list[float] = []
        gh, _sleep = fake, slept.append
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                code = main(["--repo", "o/r", "--roadmap", roadmap_path, *extra])
        except SystemExit as e:
            code = 1 if isinstance(e.code, str) else (e.code or 0)
            if isinstance(e.code, str):
                buf.write(e.code + "\n")
        finally:
            gh, _sleep = real_gh, real_sleep
        fake.slept = slept  # type: ignore[attr-defined]
        return code, buf.getvalue()

    roadmap = (
        "schema: roadmap/1\nslug: demo\nproject: p\ntitle: Demo\n"
        "status: draft\nphase: sequenced\nitems:\n"
        "  - id: demo-e1\n    kind: epic\n    title: Epic one\n"
        "  - id: demo-m1\n    kind: milestone\n    parent: demo-e1\n"
        "    title: Done already\n    status: done\n"
        "  - id: demo-m2\n    kind: milestone\n    parent: demo-e1\n    title: Open work\n"
    )
    with tempfile.TemporaryDirectory() as td:
        rp = str(Path(td) / "roadmap.yaml")
        Path(rp).write_text(roadmap, encoding="utf-8")

        # 1. Default dry-run: done item skipped with count; zero writes.
        fake = _FakeGH()
        code, out = run(fake, [], rp)
        check("dryrun_exit0", code == 0)
        check("dryrun_skip_count", "skipped-done: 1" in out)
        check("dryrun_no_done_item", "demo-m1" not in out.split("skipped-done")[1])
        check("dryrun_zero_writes", fake.writes == [])
        check("dryrun_no_map", not (Path(td) / "github").exists())

        # 2. Backfill dry-run states the close; still zero writes.
        fake = _FakeGH()
        code, out = run(fake, ["--backfill-done"], rp)
        check("bf_dryrun_close_listed", "+ close as completed: demo-m1" in out)
        check("bf_dryrun_zero_writes", fake.writes == [])

        # 3. Backfill apply: create-then-close ordering; re-run is zero writes.
        fake = _FakeGH()
        code, out = run(fake, ["--backfill-done", "--apply"], rp)
        verbs = [" ".join(w[:2]) for w in fake.writes]
        check("bf_apply_created", verbs.count("issue create") == 3)
        check("bf_apply_close_after_create",
              "issue close" in verbs and verbs.index("issue close")
              > max(i for i, v in enumerate(verbs) if v == "issue create"))
        map_path = Path(td) / "github" / "issue-map.json"
        check("map_exists_after_apply", map_path.is_file())
        check("map_lf_only", b"\r\n" not in map_path.read_bytes())
        issue_map = json.loads(map_path.read_text(encoding="utf-8"))
        check("map_three_entries", sorted(issue_map) == ["demo-e1", "demo-m1", "demo-m2"])
        check("map_entry_shape", issue_map["demo-e1"] ==
              {"number": 101, "url": "https://github.com/o/r/issues/101"})
        expect_line = ('--issues "demo-e1=https://github.com/o/r/issues/101 '
                       "demo-m1=https://github.com/o/r/issues/102 "
                       'demo-m2=https://github.com/o/r/issues/103"')
        check("issues_string_exact", expect_line in out)
        map_bytes = map_path.read_text(encoding="utf-8")
        fake.writes.clear()
        code, out = run(fake, ["--backfill-done", "--apply"], rp)
        mutating = [w for w in fake.writes if w[0] != "api" or "-f" in w]
        check("bf_rerun_zero_writes", mutating == [])
        check("map_rerun_byte_identical",
              map_path.read_text(encoding="utf-8") == map_bytes)

        # 4. Update: drifted body (with \r\n) edited once; second run zero writes.
        fake = _FakeGH()
        run(fake, ["--backfill-done", "--apply"], rp)
        target = next(i for i in fake.issues if "demo/demo-m2" in i["body"])
        target["body"] = ("stale text\r\n\r\n" + target["body"].splitlines()[-1] + "\r\n")
        fake.writes.clear()
        code, out = run(fake, ["--update", "--apply"], rp)
        edits = [w for w in fake.writes if " ".join(w[:2]) == "issue edit"]
        check("update_one_edit", len(edits) == 1 and edits[0][2] == str(target["number"]))
        fake.writes.clear()
        code, out = run(fake, ["--update", "--apply"], rp)
        check("update_rerun_zero_writes",
              [w for w in fake.writes if " ".join(w[:2]) == "issue edit"] == [])

        # 5. Preflight refusals: bad auth state; missing repo scope. Zero writes.
        fake = _FakeGH(auth={"hosts": {"github.com": [
            {"active": True, "state": "error", "login": "t", "scopes": "repo"}]}})
        code, out = run(fake, [], rp)
        check("preflight_auth_fails", code != 0 and "not authenticated" in out)
        check("preflight_auth_zero_writes", fake.writes == [])
        fake = _FakeGH(auth={"hosts": {"github.com": [
            {"active": True, "state": "success", "login": "t", "scopes": "gist"}]}})
        code, out = run(fake, [], rp)
        check("preflight_scope_fails", code != 0 and "missing scope" in out)

        # 6. Secondary-limit retry: close fails once with 403 text, then succeeds.
        fake = _FakeGH(fail_first={"issue close":
                                   "HTTP 403: You have exceeded a secondary rate limit"})
        code, out = run(fake, ["--backfill-done", "--apply"], rp)
        check("ratelimit_recovered", code == 0)
        check("ratelimit_waited", any(s >= RETRY_BASE_S for s in fake.slept))

        # 7. Retired marker: in the map (truthful record), not in the string.
        seeded = list(fake.issues) + [{"number": 50, "id": "node50", "state": "CLOSED",
                                       "body": "old\n\n<!-- roadmap-gh: demo/demo-old-9 -->"}]
        fake = _FakeGH(issues=seeded)
        code, out = run(fake, ["--backfill-done", "--apply"], rp)
        issue_map = json.loads((Path(td) / "github" / "issue-map.json")
                               .read_text(encoding="utf-8"))
        check("retired_in_map", issue_map.get("demo-old-9", {}).get("number") == 50)
        check("retired_not_in_string", "demo-old-9" not in
              next((ln for ln in out.splitlines() if ln.startswith("--issues")), ""))

        # M1. A genuine permission 403 (no rate-limit phrasing) fails fast:
        # one attempt, no >= RETRY_BASE_S backoff sleep.
        real_gh, real_sleep = gh, _sleep
        m1_calls = {"n": 0}
        m1_slept: list[float] = []

        def _perm_403(args, check=True, input_text=None):
            m1_calls["n"] += 1
            return subprocess.CompletedProcess(
                [], 1, stdout="",
                stderr="HTTP 403: Resource not accessible by integration")

        gh, _sleep = _perm_403, m1_slept.append
        try:
            m1_r = gh_write(["issue", "close", "1", "--repo", "o/r"], fatal=False)
        finally:
            gh, _sleep = real_gh, real_sleep
        check("m1_perm403_single_attempt", m1_calls["n"] == 1)
        check("m1_perm403_no_backoff", all(s < RETRY_BASE_S for s in m1_slept))
        check("m1_perm403_returns_failure", m1_r.returncode == 1)

        # M4. A server Retry-After is honored (AC4), not the 60 s fallback.
        check("m4_parse_wait_value", _parse_wait("Retry-After: 5") == 5.0)
        check("m4_parse_wait_none", _parse_wait("no wait hint here") is None)
        fake = _FakeGH(fail_first={"issue close":
                                   "HTTP 429: rate limited; Retry-After: 5"})
        code, out = run(fake, ["--backfill-done", "--apply"], rp)
        check("m4_retry_after_recovered", code == 0)
        check("m4_retry_after_honored", 5.0 in fake.slept)
        check("m4_retry_after_not_fallback", all(s < RETRY_BASE_S for s in fake.slept))

        # M2. A same-tier depends_on listed before its target must not trigger an
        # apply-time body edit the dry-run never enumerated (writes == dry-run).
        m2_roadmap = (
            "schema: roadmap/1\nslug: demo\nproject: p\ntitle: Demo\n"
            "status: draft\nphase: sequenced\nitems:\n"
            "  - id: demo-e1\n    kind: epic\n    title: Epic\n"
            "  - id: demo-a\n    kind: task\n    parent: demo-e1\n"
            "    title: A\n    depends_on: [demo-b]\n"
            "  - id: demo-b\n    kind: task\n    parent: demo-e1\n    title: B\n"
        )
        m2p = str(Path(td) / "m2.yaml")
        Path(m2p).write_text(m2_roadmap, encoding="utf-8")
        fake = _FakeGH()
        code, out = run(fake, ["--backfill-done", "--update"], m2p)
        m2_line = next((ln for ln in out.splitlines() if ln.startswith("items:")), "")
        check("m2_dryrun_zero_update", "to-update: 0" in m2_line)
        fake = _FakeGH()
        code, out = run(fake, ["--backfill-done", "--update", "--apply"], m2p)
        m2_edits = [w for w in fake.writes if " ".join(w[:2]) == "issue edit"]
        check("m2_apply_matches_dryrun", len(m2_edits) == 0)

        # M3. A missing gh binary must hit the real gh() FileNotFoundError branch
        # (the fake-gh swap bypasses it), so patch subprocess.run to raise.
        real_run = subprocess.run
        m3_buf = io.StringIO()
        m3_code = 0

        def _no_binary(*a, **k):
            raise FileNotFoundError(2, "No such file or directory", "gh")

        subprocess.run = _no_binary
        try:
            with contextlib.redirect_stdout(m3_buf):
                main(["--repo", "o/r", "--roadmap", rp])
        except SystemExit as e:
            m3_code = 1 if isinstance(e.code, str) else (e.code or 0)
            if isinstance(e.code, str):
                m3_buf.write(e.code + "\n")
        finally:
            subprocess.run = real_run
        m3_out = m3_buf.getvalue()
        check("m3_missing_binary_exit", m3_code != 0)
        check("m3_missing_binary_msg", "gh binary not found" in m3_out)
        check("m3_missing_binary_zero_create", "issue create" not in m3_out)

    if failures:
        print("SELF-TEST FAILED: " + ", ".join(failures))
        return 1
    print("self-test OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
