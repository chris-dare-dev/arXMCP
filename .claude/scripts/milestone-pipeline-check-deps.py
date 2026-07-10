#!/usr/bin/env python3
"""milestone-pipeline-check-deps.py - deterministic dependency gate (roadmap/1).

Refuses to start a milestone while any of its depends_on items is not done.
This is the "scripts block, agents advise" half of the pipeline: the command
used to gate softly ("depends on <ids> which are not done - proceed anyway?
[y]"); this replaces that human prompt with a hard, script-enforced gate plus
an audited --override event.

Usage:
  python3 milestone-pipeline-check-deps.py <ID> [--repo-root PATH]
      [--check-only] [--override "reason"]

How it decides:
  1. Locate the item by ID by shelling out to milestone-pipeline-resolve-brief.py
     --json (a sibling, co-located post-sync). We reuse its fleet-wide scan and
     INHERIT its exit codes: ambiguous id -> 1, not found -> 2. No re-scan here.
  2. For each dependency, compute its EFFECTIVE status:
       roadmap.yaml item status (plan-time seed, default 'planned')
         OVERLAID BY the latest field=="status" event in
         plans/<slug>/progress/*.jsonl (the journal is authoritative for
         execution state; roadmap.yaml status is a frozen plan-time seed under
         the one-writer rule, so gating on it alone would deadlock forever).
     A dependency is satisfied iff its effective status == 'done'. A dependency
     absent from the roadmap is treated as unmet.
  3. Any unmet dependency with NO --override -> refuse with exit 3, listing the
     unmet deps. With --override "<reason>" (and not --check-only) we append one
     audited field=="gate_override" line to plans/<slug>/progress/agent.jsonl -
     never silent; the journal is the audit trail. We do NOT route the override
     through record-progress.py, which validates value in its STATUSES set and
     so cannot carry a free-text reason.

Exit codes (downstream numbering - the INVERSE of the upstream register finder,
so init-state.sh must NOT copy an exit-2=ambiguous branch):
  0  gate passes (no unmet deps, or --override applied / would apply)
  1  ambiguous id (found in more than one plans/*/roadmap.yaml)
  2  id not found in any roadmap.yaml -> NON-FATAL; caller skips the gate
     (ad-hoc ids like adhoc-YYYYMMDD-<sha7>, and legacy-prose ids, skip it)
  3  dependency-gate refusal (unmet deps, no override)

Stdlib only (no PyYAML, no fcntl): roadmap data comes from resolve-brief's JSON,
status events come from the JSONL journal. Ruff-clean; ASCII-only output.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# Sort floor for events whose 'at' is missing/unparseable - they lose every
# tie-break so a well-formed later event always wins.
_EPOCH_MIN = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


def find_repo_root(override: str | None) -> Path:
    if override:
        p = Path(override).resolve()
        if not p.is_dir():
            sys.exit(f"error: --repo-root {override!r} is not a directory")
        return p
    env = os.environ.get("REPO_ROOT")
    if env and Path(env).is_dir():
        return Path(env).resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(out.stdout.strip())
    except Exception:
        # Script lives at <root>/.claude/scripts/<this-file> once synced.
        return Path(__file__).resolve().parents[2]


def parse_at(raw: object) -> datetime.datetime | None:
    """Parse a journal 'at' into a tz-aware datetime; None if unusable."""
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        # A naive stamp is interpreted as local wall-clock time.
        dt = dt.astimezone()
    return dt


def resolve_item(py: str, script_dir: Path, item_id: str, root: Path) -> tuple[int, dict | None]:
    """Shell out to resolve-brief.py --json. Returns (exit_code, payload|None).

    exit_code is resolve-brief's own rc (1 ambiguous, 2 not-found) so we inherit
    downstream numbering; on rc 0 payload is the parsed JSON object.
    """
    resolver = script_dir / "milestone-pipeline-resolve-brief.py"
    if not resolver.is_file():
        print(f"error: sibling resolver not found: {resolver}", file=sys.stderr)
        return 2, None
    proc = subprocess.run(
        [py, str(resolver), item_id, "--repo-root", str(root), "--json"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        # Forward the resolver's own diagnostics (ambiguity list, not-found note).
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        # rc 1 (ambiguous) and 2 (not found) pass through verbatim; any other
        # resolver failure is treated as non-fatal 'skip' so a resolver bug
        # never hard-blocks the pipeline (the gate advises, it does not brick).
        return (proc.returncode if proc.returncode in (1, 2) else 2), None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        print(f"warning: could not parse resolver JSON ({e}) - skipping gate", file=sys.stderr)
        return 2, None
    return 0, payload


def latest_journal_status(progress_dir: Path, dep_ids: set[str]) -> dict[str, str]:
    """Latest field=='status' value per id across plans/<slug>/progress/*.jsonl.

    Later 'at' wins; ties break by (filename, line number) for determinism.
    field=='gate_override' audit lines are ignored - only real status events
    move the effective status.
    """
    best: dict[str, tuple] = {}
    if not progress_dir.is_dir():
        return {}
    for path in sorted(progress_dir.glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict):
                continue
            if ev.get("field") != "status" or ev.get("id") not in dep_ids:
                continue
            key = (parse_at(ev.get("at")) or _EPOCH_MIN, path.name, lineno)
            cur = best.get(ev["id"])
            if cur is None or key > cur[0]:
                best[ev["id"]] = (key, ev.get("value"))
    return {dep: val for dep, (_key, val) in best.items() if isinstance(val, str)}


def append_override(root: Path, slug: str, item_id: str, reason: str, unmet: list[str]) -> Path:
    """Append one audited gate_override event to plans/<slug>/progress/agent.jsonl."""
    journal = root / "plans" / slug / "progress" / "agent.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "id": item_id,
        "field": "gate_override",
        "value": reason,
        "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "actor": "milestone-pipeline-init",
        "note": "bypassed unmet deps: " + "; ".join(unmet),
    }
    with open(journal, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    return journal


def compute_unmet(payload: dict, root: Path) -> list[str]:
    """List of 'id (status: X)' for every dependency whose effective status != done."""
    deps = payload.get("depends_on") or []
    if not deps:
        return []
    slug = (payload.get("source") or {}).get("slug")
    dep_ids = {d.get("id") for d in deps if isinstance(d, dict) and d.get("id")}
    journal = {}
    if slug:
        journal = latest_journal_status(root / "plans" / slug / "progress", dep_ids)
    unmet = []
    for d in deps:
        if not isinstance(d, dict) or not d.get("id"):
            continue
        dep_id = d["id"]
        seed = d.get("status") or "planned"
        effective = journal.get(dep_id, seed)
        if effective != "done":
            label = f"{dep_id} (status: {effective})"
            if d.get("title") is None:
                # resolve-brief leaves title None when the dep id is not an
                # item in this roadmap - a dangling depends_on target.
                label += " [not found in roadmap]"
            unmet.append(label)
    return unmet


def main() -> int:
    ap = argparse.ArgumentParser(description="dependency gate for a milestone (roadmap/1)")
    ap.add_argument("item_id")
    ap.add_argument("--repo-root", default=None)
    ap.add_argument(
        "--check-only", action="store_true", help="dry-run: never write the audit event"
    )
    ap.add_argument("--override", default=None, help="audited reason to bypass unmet deps")
    args = ap.parse_args()

    root = find_repo_root(args.repo_root)
    script_dir = Path(__file__).resolve().parent

    rc, payload = resolve_item(sys.executable, script_dir, args.item_id, root)
    if rc != 0 or payload is None:
        # 1 = ambiguous, 2 = not found / non-fatal skip. Nothing to gate.
        return rc

    src = payload.get("source") or {}
    if src.get("kind") != "roadmap":
        # legacy-prose (or any non-roadmap source) carries no depends_on -> the
        # gate has nothing to enforce; let it through.
        return 0

    unmet = compute_unmet(payload, root)
    if not unmet:
        return 0

    if args.override is None:
        print(f"DEP-GATE: refusing to start {args.item_id} - unmet dependencies:", file=sys.stderr)
        for u in unmet:
            print(f"  - {u}", file=sys.stderr)
        print(
            "Complete the dependencies first, or bypass with an audited reason:\n"
            f'  milestone-pipeline-check-deps.py {args.item_id} --override "<reason>"',
            file=sys.stderr,
        )
        return 3

    if args.check_only:
        print(f"{args.item_id}: {len(unmet)} unmet dep(s) - WOULD PASS via --override (no write)")
        return 0

    slug = src.get("slug")
    if not slug:
        print("error: roadmap source has no slug - cannot record override audit", file=sys.stderr)
        return 2
    journal = append_override(root, slug, args.item_id, args.override, unmet)
    try:
        journal_rel = journal.relative_to(root).as_posix()
    except ValueError:
        journal_rel = journal.as_posix()
    print(f"{args.item_id}: OVERRIDE recorded ({len(unmet)} unmet dep(s)) -> {journal_rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
