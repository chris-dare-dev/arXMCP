#!/usr/bin/env python3
"""pipeline-reconcile.py — advisory cross-artifact drift-catcher.

Reconciles, per milestone, the roadmap/1 substrate against the state machine
and the durable critique evidence, then reports any disagreements. It NEVER
edits anything and ALWAYS exits 0 — it is a diagnostic you run when a milestone
"looks done but smells wrong", not a gate.

Artifacts compared (the roadmap/1 rewrite of the old 5-way check):
  1. plans/*/roadmap.yaml     -- the register (item ids; item.status ADVISORY).
  2. plans/<slug>/progress/*.jsonl -- the execution journal (latest status).
  3. .claude/notes/milestones/<id>/state.json -- the pipeline state machine.
  4. critique/dedup.md        -- the merged, deduped critique evidence.
  5. .claude/notes/milestones/<id>/findings.json -- the ephemeral findings
     register (OPTIONAL: absent on most runs -> that check is skipped).
  6. Linked GitHub issue state, via `gh issue view <url> --json
     state,stateReason` (OPTIONAL: no gh, no auth, or no links.issue ->
     check D is skipped silently; reconcile keeps working offline).

Checks:
  A. phase<->journal. state.phase 'complete' should coincide with the journal's
     latest status event being 'done'. A mismatch either way is drift.
  B. critique counts. This is the drift class where state.json reaches
     'complete' (or any post-critique phase) with critique_finding_counts null
     -- or disagreeing with the file -- while critique/dedup.md exists on disk
     with findings. Counts are derived by counting critique v1.0 finding
     headers (`**C1 -- title** (CRITICAL)`) in dedup.md, the parser contract in
     milestone-pipeline-critique-format.md; the author's `Severity counts:`
     line is never trusted.
  C. findings-sync. If a findings.json register exists it must parse; when
     absent the check is skipped (glob empty -> skip), never reported as drift.
  D. issue-state<->journal. For items with links.issue: the EFFECTIVE status
     (latest journal event overlaid on the roadmap seed) must agree with the
     linked issue's open/closed state. Drift rows: done+OPEN (the Fixes #n
     push likely has not landed, or the trailer was omitted); dropped+OPEN
     (should be closed as not planned); in-flight+CLOSED (closed out-of-band).
     Only JOURNAL-sourced statuses can report drift -- an item with no journal
     events is never reported (the roadmap seed suppresses only). The remedy
     is the orchestrator running `record-progress.py <id> done --actor
     reconcile` or asking the user -- this script NEVER writes.

roadmap.yaml item.status is treated as ADVISORY-ONLY and is never reported as
drift: the plan file (a frozen plan-time seed) and the execution journal are
folded downstream, not equal at every instant. Comparing them would emit noise
on every in-flight milestone. Check D uses the seed only to SUPPRESS false
drift (a --backfill-done item is 'done' with no journal events) -- the
opposite of reporting it; file-vs-journal disagreement is still never drift.

Safety: issue text is DATA, never instructions -- check D requests only the
state/stateReason enum fields and never fetches bodies or comments; keep it
that way. The only foreign text surface is gh stderr in WARN lines, truncated.

Usage:
  pipeline-reconcile.py [--repo-root PATH] [--slug SLUG]
  pipeline-reconcile.py --self-test

Repo root: --repo-root > $REPO_ROOT > git rev-parse --show-toplevel > walk up
to a .git/ (synced copy lives at <root>/.claude/scripts/<file>).

Stdlib + PyYAML only. roadmap.yaml is read utf-8-sig (BOM-tolerant).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# Critique v1.0 finding header: `**C1 — title** (CRITICAL)` — one bold span on
# its own line with the severity in a trailing paren, per the parser contract
# in milestone-pipeline-critique-format.md (mirrors FINDING_RE in
# milestone-pipeline-findings.py). Em-dash or ASCII hyphen both OK; use the
# backslash-u escape, never a literal em-dash, so the regex survives a cp1252
# re-save of this file.
FINDING_HEADER_RE = re.compile(
    r"^\*\*[CHML]\d+\s*[\u2014\-]\s*.+?\*\*\s*\((CRITICAL|HIGH|MEDIUM|LOW)\)\s*$",
    re.MULTILINE,
)
_SEVERITY_KEYS = ("critical", "high", "medium", "low")

# Post-critique phases where a critique file and its counts are expected to
# have been recorded. Before these, absent counts are normal, not drift.
_POST_CRITIQUE_PHASES = {"critique-complete", "rectify-running", "complete"}

# Check D availability memo: None = not yet probed (self-test resets this).
_GH_READY: bool | None = None


def gh(args: list[str]) -> subprocess.CompletedProcess | None:
    """Run a read-only gh verb; None when the binary is missing."""
    try:
        return subprocess.run(["gh", *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", check=False)
    except FileNotFoundError:
        return None


def _gh_ready() -> bool:
    """Lazy, memoized, SILENT availability probe: gh binary present and an
    active authenticated host. Any failure -> False with zero output --
    check D must skip silently and reconcile must keep working offline."""
    global _GH_READY
    if _GH_READY is None:
        ready = False
        r = gh(["auth", "status", "--json", "hosts"])
        if r is not None and r.returncode == 0:
            try:
                hosts = json.loads(r.stdout or "{}").get("hosts") or {}
            except json.JSONDecodeError:
                hosts = {}
            for entries in hosts.values():
                for entry in entries:
                    if entry.get("active") and entry.get("state") == "success":
                        ready = True
        _GH_READY = ready
    return _GH_READY


def _check_issue_state(slug_dir: Path, item: dict, errors: list[str]) -> list[str]:
    """Check D: linked issue open/closed state vs the effective status.

    Effective = latest journal event overlaid on the roadmap seed (the
    check-deps overlay); the seed only suppresses false drift. Reads only the
    state/stateReason enums. Run-level preconditions (no links, no gh/auth)
    skip silently; a FAILED per-item read is a WARN, never drift and never
    silent -- otherwise it is indistinguishable from checked-and-clean."""
    urls = (item.get("links") or {}).get("issue") or []
    if not urls or not _gh_ready():
        return []
    item_id = item.get("id")
    url = urls[0]
    r = gh(["issue", "view", url, "--json", "state,stateReason"])
    if r is None or r.returncode != 0:
        detail = ((r.stderr or "") if r is not None else "gh unavailable").strip()[:120]
        errors.append(f"{item_id}: check D could not read {url}: {detail}")
        return []
    try:
        data = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        errors.append(f"{item_id}: check D got unparseable JSON for {url}")
        return []
    if not isinstance(data, dict):
        errors.append(f"{item_id}: check D got non-object JSON for {url}")
        return []
    state = data.get("state", "")
    reason = (data.get("stateReason") or "").replace("_", " ").lower()
    journal = latest_journal_status(slug_dir, item_id)
    effective = journal or item.get("status") or "planned"
    terminal = effective in ("done", "dropped")
    # MERGED appears when a links.issue entry points at a PR; closed-equivalent.
    closed = state in ("CLOSED", "MERGED")
    if terminal == closed:
        return []
    if journal is None:
        # ADVISORY-ONLY: a seed-sourced status only SUPPRESSES drift. An item
        # with no journal events is never reported, whatever GitHub says.
        return []
    if effective == "done":
        return [f"journal says 'done' but {url} is OPEN "
                "(Fixes #n push likely not landed, or trailer omitted)"]
    if effective == "dropped":
        return [f"journal says 'dropped' but {url} is OPEN "
                "(should be closed as not planned)"]
    suffix = f" as {reason}" if reason else ""
    return [f"effective status is '{effective}' but {url} is CLOSED{suffix} "
            "(closed out-of-band)"]


def find_repo_root(override: str | None) -> Path:
    if override:
        p = Path(override).resolve()
        if not p.is_dir():
            sys.exit(f"error: --repo-root {override!r} is not a directory")
        return p
    env = os.environ.get("REPO_ROOT")
    if env and Path(env).is_dir():
        return Path(env).resolve()
    here = Path(__file__).resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(here.parent),
        )
        top = out.stdout.strip()
        if top:
            return Path(top)
    except Exception:
        pass
    for parent in [here.parent, *here.parents]:
        if (parent / ".git").exists():
            return parent
    return here.parents[2]


def _blank_fences(text: str) -> str:
    """Blank ``` fenced blocks (same pre-pass as milestone-pipeline-findings.py)
    so example headers quoted in a critique never count as findings."""
    out = []
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def count_severity_headers(text: str) -> dict:
    counts = dict.fromkeys(_SEVERITY_KEYS, 0)
    for m in FINDING_HEADER_RE.finditer(_blank_fences(text)):
        counts[m.group(1).lower()] += 1
    return counts


def latest_journal_status(slug_dir: Path, item_id: str) -> str | None:
    """Latest `field == status` value for item_id across progress/*.jsonl.

    Ordered by the event 'at' timestamp, tie-broken by (file name, line number)
    so a deterministic winner emerges when two events share a timestamp.
    """
    progress = slug_dir / "progress"
    if not progress.is_dir():
        return None
    best_key: tuple | None = None
    best_value: str | None = None
    for jf in sorted(progress.glob("*.jsonl")):
        try:
            lines = jf.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict):
                continue
            if ev.get("id") != item_id or ev.get("field") != "status":
                continue
            key = (str(ev.get("at", "")), jf.name, lineno)
            if best_key is None or key > best_key:
                best_key = key
                best_value = ev.get("value")
    return best_value


def _load_state(root: Path, item_id: str) -> dict | None:
    sp = root / ".claude" / "notes" / "milestones" / item_id / "state.json"
    if not sp.is_file():
        return None
    try:
        data = json.loads(sp.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _resolve_artifact(root: Path, item_id: str, rel: str) -> Path:
    """critique_path may be repo-relative or milestone-dir-relative."""
    candidate = root / rel
    if candidate.is_file():
        return candidate
    return root / ".claude" / "notes" / "milestones" / item_id / rel


def _check_item(root: Path, slug_dir: Path, item: dict, errors: list[str]) -> list[str]:
    """Return drift messages for one roadmap item (empty == clean)."""
    item_id = item["id"]
    # Check D first: it needs no state.json (backfilled and out-of-band items
    # have none) and must not be gated by the pipeline-never-ran early return.
    drifts: list[str] = list(_check_issue_state(slug_dir, item, errors))
    state = _load_state(root, item_id)
    if state is None:
        # No pipeline run for this planned item yet -- checks A-C skip.
        return drifts

    phase = state.get("phase")
    journal_status = latest_journal_status(slug_dir, item_id)

    # Check A: phase <-> journal.
    if phase == "complete" and journal_status != "done":
        drifts.append(
            f"state.phase is 'complete' but journal latest status is "
            f"{journal_status!r} (expected 'done')"
        )
    elif journal_status == "done" and phase != "complete":
        drifts.append(
            f"journal latest status is 'done' but state.phase is {phase!r} "
            "(expected 'complete')"
        )

    # Check B: critique counts vs the file (prod-sync failure class).
    critique_path = state.get("critique_path")
    counts = state.get("critique_finding_counts")
    if critique_path:
        cf = _resolve_artifact(root, item_id, critique_path)
        if not cf.is_file():
            drifts.append(f"critique_path {critique_path!r} is set but the file is missing")
        else:
            actual = count_severity_headers(cf.read_text(encoding="utf-8-sig"))
            total = sum(actual.values())
            counts_missing = counts is None or (
                isinstance(counts, dict) and sum(counts.get(k, 0) for k in _SEVERITY_KEYS) == 0
            )
            if total > 0 and counts_missing and phase in _POST_CRITIQUE_PHASES:
                # The class where state reached a post-critique phase with null
                # (or all-zero) critique_finding_counts while dedup.md carries
                # findings -- the counts were derived but never written back.
                drifts.append(
                    f"critique file has {total} finding(s) but "
                    f"critique_finding_counts is {counts!r}"
                )
            elif isinstance(counts, dict) and any(counts.values()):
                for k in _SEVERITY_KEYS:
                    if counts.get(k, 0) != actual[k]:
                        drifts.append(
                            f"critique_finding_counts.{k}={counts.get(k, 0)} but "
                            f"dedup.md has {actual[k]} ({k.upper()}) finding header(s)"
                        )
    elif phase in _POST_CRITIQUE_PHASES:
        drifts.append(f"phase is {phase!r} but critique_path is unset")

    # Check C: findings-sync (optional register; absent -> skip silently).
    register = root / ".claude" / "notes" / "milestones" / item_id / "findings.json"
    if register.is_file():
        try:
            json.loads(register.read_text(encoding="utf-8-sig"))
        except Exception as e:
            drifts.append(f"findings.json register exists but does not parse: {e}")

    return drifts


def reconcile(root: Path, slug_filter: str | None = None) -> dict:
    """Scan plans/*/roadmap.yaml and return {item_id: [drift, ...]} for drifting
    items, plus a scanned count under the '_scanned' key."""
    report: dict = {}
    errors: list[str] = []
    scanned = 0
    for roadmap in sorted(root.glob("plans/*/roadmap.yaml")):
        slug_dir = roadmap.parent
        if slug_filter and slug_dir.name != slug_filter:
            continue
        try:
            doc = yaml.safe_load(roadmap.read_text(encoding="utf-8-sig"))
        except Exception as e:
            errors.append(f"unparseable {roadmap}: {e}")
            continue
        if not isinstance(doc, dict):
            continue
        for item in doc.get("items") or []:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if not item_id:
                continue
            scanned += 1
            drifts = _check_item(root, slug_dir, item, errors)
            if drifts:
                report[item_id] = drifts
    if errors:
        report["_errors"] = errors
    report["_scanned"] = scanned
    return report


def _print_report(report: dict) -> None:
    scanned = report.get("_scanned", 0)
    errors = report.get("_errors", [])
    drifting = {k: v for k, v in report.items() if not k.startswith("_")}
    for err in errors:
        print(f"WARN  {err}")
    if not drifting:
        print(f"OK  reconciled {scanned} milestone(s); no drift detected.")
        return
    print(f"DRIFT  {len(drifting)} of {scanned} milestone(s) disagree:")
    for item_id in sorted(drifting):
        for msg in drifting[item_id]:
            print(f"  - {item_id}: {msg}")


def _self_test() -> int:
    import tempfile

    failures = []

    def check(name: str, cond: bool) -> None:
        if not cond:
            failures.append(name)

    # count_severity_headers (critique v1.0 authored-id bold headers)
    sample = (
        "**C1 — external write in diff** (CRITICAL)\n\n"
        "**H1 - missing test** (HIGH)\n"
        "**H2 — diff too large** (HIGH)\n"
        "### MEDIUM retired heading shape, not a finding\n"
        "**M1 — header missing its severity paren**\n"
        "```\n"
        "**L9 — fenced example, never counted** (LOW)\n"
        "```\n"
        "**L1 — naming nit** (LOW)\n"
    )
    c = count_severity_headers(sample)
    check("count_critical", c["critical"] == 1)
    check("count_high", c["high"] == 2)
    check("count_medium_ignores_nonfindings", c["medium"] == 0)
    check("count_low_ignores_fenced", c["low"] == 1)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".git").mkdir()

        # Plan: one slug with two items.
        plan = root / "plans" / "demo"
        (plan / "progress").mkdir(parents=True)
        (plan / "roadmap.yaml").write_text(
            "schema: roadmap/1\nslug: demo\nitems:\n"
            "  - id: demo-m1\n    status: done\n"
            "  - id: demo-m2\n    status: planned\n",
            encoding="utf-8",
        )

        def milestone_dir(mid: str) -> Path:
            d = root / ".claude" / "notes" / "milestones" / mid
            d.mkdir(parents=True, exist_ok=True)
            return d

        # demo-m1: state complete, but journal latest is NOT done -> drift A;
        # critique file has 2 findings but counts null -> drift B.
        d1 = milestone_dir("demo-m1")
        (d1 / "critique").mkdir()
        (d1 / "critique" / "dedup.md").write_text(
            "**C1 — boom** (CRITICAL)\n\n**H1 — bang** (HIGH)\n", encoding="utf-8"
        )
        (d1 / "state.json").write_text(
            json.dumps(
                {
                    "phase": "complete",
                    "critique_path": "critique/dedup.md",
                    "critique_finding_counts": None,
                }
            ),
            encoding="utf-8",
        )
        (plan / "progress" / "agent.jsonl").write_text(
            json.dumps({"id": "demo-m1", "field": "status", "value": "in_progress",
                        "at": "2026-07-09T10:00:00+00:00"})
            + "\n",
            encoding="utf-8",
        )

        # demo-m2: clean -- state complete, journal done, counts match file.
        d2 = milestone_dir("demo-m2")
        (d2 / "critique").mkdir()
        (d2 / "critique" / "dedup.md").write_text(
            "**H1 — one** (HIGH)\n", encoding="utf-8"
        )
        (d2 / "state.json").write_text(
            json.dumps(
                {
                    "phase": "complete",
                    "critique_path": "critique/dedup.md",
                    "critique_finding_counts": {"critical": 0, "high": 1, "medium": 0, "low": 0},
                }
            ),
            encoding="utf-8",
        )
        (plan / "progress" / "extra.jsonl").write_text(
            json.dumps({"id": "demo-m2", "field": "status", "value": "done",
                        "at": "2026-07-09T12:00:00+00:00"})
            + "\n",
            encoding="utf-8",
        )

        report = reconcile(root)
        check("scanned_two", report.get("_scanned") == 2)
        check("m1_flagged", "demo-m1" in report)
        check("m1_has_two_drifts", len(report.get("demo-m1", [])) == 2)
        check("m2_clean", "demo-m2" not in report)

        # latest_journal_status tie-break / selection
        check("journal_m1_inprogress", latest_journal_status(plan, "demo-m1") == "in_progress")
        check("journal_m2_done", latest_journal_status(plan, "demo-m2") == "done")

        # slug filter that matches nothing scans nothing.
        empty = reconcile(root, slug_filter="nope")
        check("slug_filter_empty", empty.get("_scanned") == 0)

    # ---- Check D scenarios (separate root; injected fake gh; memo reset) ----
    class _FakeGH:
        def __init__(self, issues: dict, auth_ok: bool = True):
            self.issues, self.auth_ok = issues, auth_ok
            self.calls: list[list[str]] = []

        def __call__(self, args):
            self.calls.append(list(args))
            if args[:2] == ["auth", "status"]:
                state = "success" if self.auth_ok else "error"
                payload = {"hosts": {"github.com": [{"active": True, "state": state}]}}
                return subprocess.CompletedProcess([], 0, stdout=json.dumps(payload),
                                                   stderr="")
            if args[:2] == ["issue", "view"]:
                url = args[2]
                if url not in self.issues:
                    return subprocess.CompletedProcess([], 1, stdout="",
                                                       stderr="HTTP 404: Not Found")
                return subprocess.CompletedProcess([], 0,
                                                   stdout=json.dumps(self.issues[url]),
                                                   stderr="")
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    def run_d(fake, root: Path) -> dict:
        global gh, _GH_READY
        real, gh, _GH_READY = gh, fake, None
        try:
            return reconcile(root)
        finally:
            gh, _GH_READY = real, None

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".git").mkdir()
        plan = root / "plans" / "ghd"
        (plan / "progress").mkdir(parents=True)
        u = {n: f"https://github.com/o/r/issues/{n}" for n in range(1, 8)}
        items = [
            "  - id: ghd-m1\n    links: {issue: ['%s']}\n" % u[1],  # done+OPEN
            "  - id: ghd-m2\n    links: {issue: ['%s']}\n" % u[2],  # dropped+OPEN
            "  - id: ghd-m3\n    links: {issue: ['%s']}\n" % u[3],  # in_progress+CLOSED
            "  - id: ghd-m4\n    links: {issue: ['%s']}\n" % u[4],  # done+CLOSED clean
            "  - id: ghd-m5\n    status: done\n    links: {issue: ['%s']}\n" % u[5],
            "  - id: ghd-m6\n",                                     # no links -> no call
            "  - id: ghd-m7\n    links: {issue: ['%s']}\n" % u[7],  # view fails -> WARN
        ]
        (plan / "roadmap.yaml").write_text(
            "schema: roadmap/1\nslug: ghd\nitems:\n" + "".join(items), encoding="utf-8")
        events = [("ghd-m1", "done"), ("ghd-m2", "dropped"),
                  ("ghd-m3", "in_progress"), ("ghd-m4", "done")]
        (plan / "progress" / "agent.jsonl").write_text(
            "".join(json.dumps({"id": i, "field": "status", "value": v,
                                "at": "2026-07-21T10:00:00+00:00"}) + "\n"
                    for i, v in events), encoding="utf-8")
        opened = {"state": "OPEN", "stateReason": ""}
        closed = {"state": "CLOSED", "stateReason": "COMPLETED"}
        fake = _FakeGH({u[1]: opened, u[2]: opened, u[3]: closed,
                        u[4]: closed, u[5]: closed})  # u[7] absent -> 404
        rep = run_d(fake, root)
        check("d_done_open_drift", "ghd-m1" in rep and "OPEN" in rep["ghd-m1"][0])
        check("d_dropped_open_drift", "ghd-m2" in rep and "not planned" in rep["ghd-m2"][0])
        check("d_inflight_closed_drift", "ghd-m3" in rep
              and "out-of-band" in rep["ghd-m3"][0])
        check("d_done_closed_clean", "ghd-m4" not in rep)
        check("d_backfilled_seed_clean", "ghd-m5" not in rep)
        # Seed-sourced done + OPEN is SUPPRESSED (ADVISORY-ONLY), not drift.
        opened_m5 = dict(fake.issues)
        opened_m5[u[5]] = {"state": "OPEN", "stateReason": "REOPENED"}
        rep2 = run_d(_FakeGH(opened_m5), root)
        check("d_seed_open_suppressed", "ghd-m5" not in rep2)
        # A merged PR URL is closed-equivalent, not a false done+OPEN drift.
        merged_m1 = dict(fake.issues)
        merged_m1[u[1]] = {"state": "MERGED", "stateReason": ""}
        rep3 = run_d(_FakeGH(merged_m1), root)
        check("d_merged_closed_equiv", "ghd-m1" not in rep3)
        check("d_view_failure_warn_not_drift", "ghd-m7" not in rep
              and any("ghd-m7" in e for e in rep.get("_errors", [])))
        views = [c for c in fake.calls if c[:2] == ["issue", "view"]]
        check("d_no_links_no_call", len(views) == 6)  # m6 skipped; m1-m5 + m7

        # No gh binary: silent full skip, zero drift, zero errors.
        rep = run_d(lambda args: None, root)
        check("d_nogh_silent", not [k for k in rep if not k.startswith("_")]
              and "_errors" not in rep)
        # Unauthenticated: same silent skip, and no issue views attempted.
        fake = _FakeGH({}, auth_ok=False)
        rep = run_d(fake, root)
        check("d_noauth_silent", not [k for k in rep if not k.startswith("_")]
              and not [c for c in fake.calls if c[:2] == ["issue", "view"]])

    if failures:
        print("SELF-TEST FAILED: " + ", ".join(failures))
        return 1
    print("self-test OK")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="advisory pipeline drift-catcher (always exits 0)")
    ap.add_argument("--repo-root", default=None)
    ap.add_argument("--slug", default=None, help="limit to one plans/<slug>")
    ap.add_argument("--self-test", action="store_true", help="run the built-in self-test")
    args = ap.parse_args(argv)

    if args.self_test:
        # The one place a non-zero exit is allowed: a broken build gate.
        return _self_test()

    root = find_repo_root(args.repo_root)
    report = reconcile(root, args.slug)
    _print_report(report)
    # ALWAYS advisory: never signal drift through the exit code.
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
