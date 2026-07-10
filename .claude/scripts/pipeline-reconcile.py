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

Checks:
  A. phase<->journal. state.phase 'complete' should coincide with the journal's
     latest status event being 'done'. A mismatch either way is drift.
  B. critique counts. This is the drift class where state.json reaches
     'complete' (or any post-critique phase) with critique_finding_counts null
     -- or disagreeing with the file -- while critique/dedup.md exists on disk
     with findings. Counts are derived by counting `### <SEVERITY>` headers in
     dedup.md (the parser contract in milestone-pipeline-critique-format.md);
     there is no separate summary line to trust.
  C. findings-sync. If a findings.json register exists it must parse; when
     absent the check is skipped (glob empty -> skip), never reported as drift.

roadmap.yaml item.status is treated as ADVISORY-ONLY and is never reported as
drift: the plan file (a frozen plan-time seed) and the execution journal are
folded downstream, not equal at every instant. Comparing them would emit noise
on every in-flight milestone.

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

# `### CRITICAL — ...` / `### HIGH - ...` at heading level 3, per the parser
# contract in milestone-pipeline-critique-format.md. Em-dash or hyphen both OK.
SEVERITY_HEADER_RE = re.compile(r"^###\s+(CRITICAL|HIGH|MEDIUM|LOW)\b", re.MULTILINE)
_SEVERITY_KEYS = ("critical", "high", "medium", "low")

# Post-critique phases where a critique file and its counts are expected to
# have been recorded. Before these, absent counts are normal, not drift.
_POST_CRITIQUE_PHASES = {"critique-complete", "rectify-running", "complete"}


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


def count_severity_headers(text: str) -> dict:
    counts = dict.fromkeys(_SEVERITY_KEYS, 0)
    for m in SEVERITY_HEADER_RE.finditer(text):
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


def _check_item(root: Path, slug_dir: Path, item_id: str) -> list[str]:
    """Return drift messages for one milestone id (empty == clean)."""
    drifts: list[str] = []
    state = _load_state(root, item_id)
    if state is None:
        # No pipeline run for this planned item yet -- nothing to reconcile.
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
                            f"dedup.md has {actual[k]} '### {k.upper()}' header(s)"
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
    scanned = 0
    for roadmap in sorted(root.glob("plans/*/roadmap.yaml")):
        slug_dir = roadmap.parent
        if slug_filter and slug_dir.name != slug_filter:
            continue
        try:
            doc = yaml.safe_load(roadmap.read_text(encoding="utf-8-sig"))
        except Exception as e:
            report.setdefault("_errors", []).append(f"unparseable {roadmap}: {e}")
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
            drifts = _check_item(root, slug_dir, item_id)
            if drifts:
                report[item_id] = drifts
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

    # count_severity_headers
    sample = (
        "### CRITICAL — external write in diff\n\n"
        "### HIGH - missing test\n"
        "### HIGH — diff too large\n"
        "#### MEDIUM not a finding heading\n"
        "### LOW — naming nit\n"
    )
    c = count_severity_headers(sample)
    check("count_critical", c["critical"] == 1)
    check("count_high", c["high"] == 2)
    check("count_medium_ignores_h4", c["medium"] == 0)
    check("count_low", c["low"] == 1)

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
            "### CRITICAL — boom\n\n### HIGH — bang\n", encoding="utf-8"
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
        (d2 / "critique" / "dedup.md").write_text("### HIGH — one\n", encoding="utf-8")
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
