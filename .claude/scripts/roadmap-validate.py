#!/usr/bin/env python3
"""roadmap-validate.py — validate a roadmap/1 canonical roadmap.yaml.

Usage:
  python3 roadmap-validate.py <path/to/roadmap.yaml> [--json] [--allow CHECK ...]

Exit 0 when every check passes, 1 otherwise. --json emits a machine-readable
error list (agents self-correct from it). --allow suppresses a named check.

Checks (names are what --allow takes):
  parse            YAML parses; no duplicate keys; document is a mapping
  schema           top-level required fields + enums + slug regex
  goal             phase>=refined: objective, >=3 key_results, every MUST
                   assumption carries a non-empty validation clause
  item-ids         per-kind ID regex, slug prefix, global uniqueness
  item-fields      enums, per-kind field compat, acceptance list types
  parents          parent exists and kind-compatible (milestone->epic,
                   task->milestone|epic, spike->epic|top-level)
  deps             depends_on targets exist; dependency graph is acyclic
  dates            ISO format; target_start <= target_end; horizon sane
  lanes            phase>=sequenced: every now-lane milestone/task has >=1
                   acceptance criterion; milestones carry a lane
  must-cap         must-priority epics <= 60% of non-wont epics
  tombstones       retired ids are absent from items; no id both places

Design notes: stdlib + PyYAML only (mirrors the vault pipeline's footprint).
PyYAML coerces bare dates to datetime.date — normalized back to ISO strings
before checking so the canonical file may use either quoted or bare dates.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

import yaml

ID_RE = {
    "epic": r"e[0-9]+",
    "milestone": r"m[0-9]+",
    "spike": r"spike-[0-9]+",
    "task": r"t-[a-z0-9][a-z0-9-]*",
}
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ROADMAP_STATUS = {"draft", "active", "done", "superseded"}
PHASES = ["init", "refined", "decomposed", "sequenced", "complete"]
ITEM_STATUS = {"planned", "ready", "in_progress", "blocked", "done", "dropped"}
KINDS = {"epic", "milestone", "task", "spike"}
LANES = {"now", "next", "later"}
PRIORITIES = {"must", "should", "could", "wont"}
SIZES = {"S", "M", "L", "XL"}
PARENT_KINDS = {"milestone": {"epic"}, "task": {"milestone", "epic"}, "spike": {"epic"}}


class DupKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys (PyYAML silently last-wins)."""


def _no_dup_mapping(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.YAMLError(f"duplicate key {key!r} at line {key_node.start_mark.line + 1}")
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


DupKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dup_mapping)


def normalize_dates(obj):
    """Coerce datetime.date/datetime values (PyYAML bare-date parsing) to ISO strings."""
    if isinstance(obj, dict):
        return {k: normalize_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalize_dates(v) for v in obj]
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return (
            obj.isoformat()[:10]
            if isinstance(obj, datetime.date) and not isinstance(obj, datetime.datetime)
            else obj.isoformat()
        )
    return obj


def validate(doc: dict, errors: list) -> None:
    def err(check: str, msg: str) -> None:
        errors.append({"check": check, "msg": msg})

    # ── schema ────────────────────────────────────────────────
    for field in ("schema", "slug", "project", "title", "status", "phase", "items"):
        if field not in doc:
            err("schema", f"missing required top-level field: {field}")
    if errors:
        return  # nothing downstream is meaningful without the basics
    if doc["schema"] != "roadmap/1":
        err("schema", f'schema must be "roadmap/1", got {doc["schema"]!r}')
    slug = str(doc["slug"])
    if not SLUG_RE.match(slug):
        err("schema", f"slug {slug!r} is not kebab-case")
    if doc["status"] not in ROADMAP_STATUS:
        err("schema", f"status {doc['status']!r} not in {sorted(ROADMAP_STATUS)}")
    if doc["phase"] not in PHASES:
        err("schema", f"phase {doc['phase']!r} not in {PHASES}")
    if not isinstance(doc["items"], list):
        err("schema", "items must be a list")
        return
    phase_idx = PHASES.index(doc["phase"]) if doc["phase"] in PHASES else 0

    # ── goal ──────────────────────────────────────────────────
    if phase_idx >= PHASES.index("refined"):
        goal = doc.get("goal") or {}
        if not str(goal.get("objective", "")).strip():
            err("goal", "phase>=refined requires goal.objective")
        krs = goal.get("key_results") or []
        if len(krs) < 3:
            err("goal", f"phase>=refined requires >=3 goal.key_results (got {len(krs)})")
        for i, a in enumerate(goal.get("assumptions") or []):
            if a.get("tier") == "must" and not str(a.get("validation", "")).strip():
                err("goal", f"MUST assumption #{i + 1} has no validation clause")

    # ── items: ids, fields, parents ───────────────────────────
    ids: dict[str, dict] = {}
    for i, it in enumerate(doc["items"]):
        where = f"items[{i}]"
        if not isinstance(it, dict):
            err("item-fields", f"{where} is not a mapping")
            continue
        iid, kind = it.get("id"), it.get("kind")
        if not iid or not kind:
            err("item-ids", f"{where} missing id or kind")
            continue
        if kind not in KINDS:
            err("item-fields", f"{iid}: kind {kind!r} not in {sorted(KINDS)}")
            continue
        if not re.match(rf"^{re.escape(slug)}-{ID_RE[kind]}$", str(iid)):
            err("item-ids", f"{iid}: does not match ^{slug}-{ID_RE[kind]}$ for kind={kind}")
        if iid in ids:
            err("item-ids", f"{iid}: duplicate id")
        ids[iid] = it
        if "status" in it and it["status"] not in ITEM_STATUS:
            err("item-fields", f"{iid}: status {it['status']!r} invalid")
        if "lane" in it and it["lane"] not in LANES:
            err("item-fields", f"{iid}: lane {it['lane']!r} invalid")
        if "priority" in it and it["priority"] not in PRIORITIES:
            err("item-fields", f"{iid}: priority {it['priority']!r} invalid")
        if "size" in it and it["size"] not in SIZES:
            err("item-fields", f"{iid}: size {it['size']!r} invalid")
        if "acceptance" in it and (
            not isinstance(it["acceptance"], list)
            or not all(isinstance(a, str) and a.strip() for a in it["acceptance"])
        ):
            err("item-fields", f"{iid}: acceptance must be a list of non-empty strings")

    for iid, it in ids.items():
        parent = it.get("parent")
        if parent is not None:
            if parent not in ids:
                err("parents", f"{iid}: parent {parent!r} does not exist")
            elif it["kind"] in PARENT_KINDS and ids[parent]["kind"] not in PARENT_KINDS[it["kind"]]:
                err(
                    "parents",
                    f"{iid}: kind={it['kind']} cannot parent to kind={ids[parent]['kind']}",
                )
            elif it["kind"] == "epic":
                err("parents", f"{iid}: epics are top-level (no parent)")

    # ── deps: existence + acyclicity (Kahn) ───────────────────
    indeg = {iid: 0 for iid in ids}
    edges: dict[str, list] = {iid: [] for iid in ids}
    for iid, it in ids.items():
        for dep in it.get("depends_on") or []:
            if dep not in ids:
                err("deps", f"{iid}: depends_on target {dep!r} does not exist")
            else:
                edges[dep].append(iid)
                indeg[iid] += 1
    queue = [i for i, d in indeg.items() if d == 0]
    visited = 0
    while queue:
        n = queue.pop()
        visited += 1
        for m in edges[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
    if visited != len(ids):
        cyc = sorted(i for i, d in indeg.items() if d > 0)
        err("deps", f"dependency cycle involving: {', '.join(cyc)}")

    # ── dates ─────────────────────────────────────────────────
    def check_date(owner: str, field: str, val) -> bool:
        if val is not None and not DATE_RE.match(str(val)):
            err("dates", f"{owner}: {field} {val!r} is not YYYY-MM-DD")
            return False
        return val is not None

    hz = doc.get("horizon")
    if (
        hz
        and check_date("horizon", "start", hz.get("start"))
        and check_date("horizon", "end", hz.get("end"))
        and str(hz["start"]) > str(hz["end"])
    ):
        err("dates", "horizon.start is after horizon.end")
    for iid, it in ids.items():
        s_ok = check_date(iid, "target_start", it.get("target_start"))
        e_ok = check_date(iid, "target_end", it.get("target_end"))
        if s_ok and e_ok and str(it["target_start"]) > str(it["target_end"]):
            err("dates", f"{iid}: target_start after target_end")

    # ── lanes ─────────────────────────────────────────────────
    if phase_idx >= PHASES.index("sequenced"):
        for iid, it in ids.items():
            if it["kind"] == "milestone" and "lane" not in it:
                err("lanes", f"{iid}: phase>=sequenced requires a lane on milestones")
            if it["kind"] in ("milestone", "task") and it.get("lane") == "now" and not it.get("acceptance"):
                err("lanes", f"{iid}: now-lane {it['kind']} needs >=1 acceptance criterion")

    # ── must-cap ──────────────────────────────────────────────
    epics = [it for it in ids.values() if it["kind"] == "epic"]
    scoped = [e for e in epics if e.get("priority") != "wont"]
    musts = [e for e in scoped if e.get("priority") == "must"]
    if scoped and len(musts) / len(scoped) > 0.60:
        err(
            "must-cap",
            f"must epics {len(musts)}/{len(scoped)} exceed the 60% cap — demote something",
        )

    # ── tombstones ────────────────────────────────────────────
    for rid in doc.get("retired") or []:
        if rid in ids:
            err("tombstones", f"{rid}: listed in retired but still present in items")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--allow", action="append", default=[], metavar="CHECK")
    args = ap.parse_args()

    errors: list = []
    try:
        raw = yaml.load(args.path.read_text(encoding="utf-8-sig"), Loader=DupKeyLoader)
    except Exception as e:  # parse errors, dup keys, missing file
        errors.append({"check": "parse", "msg": str(e)})
        raw = None
    if raw is not None:
        if not isinstance(raw, dict):
            errors.append({"check": "parse", "msg": "document is not a mapping"})
        else:
            validate(normalize_dates(raw), errors)

    errors = [e for e in errors if e["check"] not in args.allow]
    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors}, indent=2))
    else:
        for e in errors:
            print(f"[{e['check']}] {e['msg']}")
        print(f"{'OK' if not errors else 'FAIL'} — {len(errors)} error(s): {args.path}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
