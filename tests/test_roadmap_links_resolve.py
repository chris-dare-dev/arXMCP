"""Roadmap `links.code` anchors must resolve, and plans must not invert time.

**Why this file exists.** `ui-uplift-m12`'s critique filed two findings whose
durable fix is a lint, and both were deferred here rather than into
`.claude/scripts/roadmap-validate.py`, which is registry-synced
(`.claude/.registry-manifest.json`) and must not be edited in this repo.

- **M10** — `app.css` grew 598 → 627 → 656 across two days with every
  insertion near the top, so **twelve** `links.code` anchors in
  `plans/ui-uplift/roadmap.yaml` silently came to point at unrelated comment
  blocks. `ui-uplift-m16`'s `app.css:83-93` meant the input rules and landed
  in a marker comment; `ui-uplift-m18`'s `notebook_detail.html:43` meant the
  rename form's error handler and landed inside an m12 note. These anchors are
  what a Phase-0 dispatch hands an implementer, and *a milestone that cannot
  find its authored source is the documented root cause of m7/m8/m10 inventing
  values*.

- **L4** — `ui-uplift-m11` was scheduled `2026-09-08 → 2026-09-15` while the
  `ui-uplift-m12` it `depends_on` ran to `2026-09-26`: its window ended eleven
  days before its own dependency.

**The anchor format.** A line number in a hand-maintained document is stale by
construction — nothing regenerates it, and this epic rewrites `app.css` and
`notebook_detail.html` on nearly every milestone. `plans/ui-uplift` was
migrated to `path#<literal>` anchors, which a lint resolves by SEARCHING. Bare
`path` anchors were always stable and are unchanged.

**Scope, stated honestly.** Only `plans/ui-uplift` is held to the strict rule.
The other eleven roadmaps carry 177 line anchors and 45 anchors whose file does
not exist at all; fixing those is a separate pass and was not asked for. They
are held to a RATCHET instead, so the debt cannot grow silently while nobody is
looking at it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
PLANS: Path = REPO_ROOT / "plans"

#: The roadmap this lint was written for, held to the strict rule.
STRICT_SLUG = "ui-uplift"

#: Anchors elsewhere whose file does not exist, measured 2026-08-05. This is a
#: RATCHET, not a target: it may only go DOWN. If a legitimate change moves it,
#: the failure message says which anchors are involved so the number can be
#: re-set deliberately rather than nudged.
KNOWN_UNRESOLVED_ELSEWHERE = 46

#: Dependency-order inversions outside `plans/ui-uplift`, measured 2026-08-05.
#: Same ratchet, same reason: L4 is a ui-uplift finding, and silently
#: rescheduling three other epics' plans to make a new lint green would be a
#: worse act than leaving the debt visible and bounded.
KNOWN_INVERSIONS_ELSEWHERE = {
    "evidence-engine": 1,
    "trustworthy-release": 1,
    "verification-contract": 1,
}

_LINE_ANCHOR = re.compile(r"^(?P<path>.+?):(?P<lo>\d+)(?:-(?P<hi>\d+))?$")

#: Statuses that mean the item has shipped. A plan's dates are TARGETS; once an
#: item is done its recorded window is history and re-writing it to satisfy a
#: lint would be revisionism. The ordering rule below therefore applies only to
#: work that has not shipped, which is the only work an ordering can still
#: inform.
DONE_STATUSES = {"done", "complete", "shipped"}


def _roadmaps() -> list[Path]:
    return sorted(PLANS.glob("*/roadmap.yaml"))


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _anchors(doc: dict):
    """Yield ``(item_id, anchor)`` for every ``links.code`` entry."""
    for item in doc.get("items") or []:
        for anchor in (item.get("links") or {}).get("code") or []:
            yield item.get("id", "<no id>"), anchor


def _resolve(anchor: str) -> str | None:
    """Return None when ``anchor`` resolves, else a reason."""
    path_part, sep, literal = anchor.partition("#")
    if not sep:
        m = _LINE_ANCHOR.match(anchor)
        if m:
            path_part, literal = m.group("path"), None
        else:
            path_part, literal = anchor, None
    target = REPO_ROOT / path_part
    if not target.is_file():
        return f"file does not exist: {path_part}"
    if sep:
        if literal not in target.read_text(encoding="utf-8", errors="replace"):
            return f"literal not found in {path_part}: {literal!r}"
        return None
    m = _LINE_ANCHOR.match(anchor)
    if m:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        hi = int(m.group("hi") or m.group("lo"))
        if hi > len(lines):
            return f"{path_part} has {len(lines)} lines; anchor cites {hi}"
    return None


# ---------------------------------------------------------------------------
# M10 — anchors resolve
# ---------------------------------------------------------------------------
def test_the_strict_roadmap_exists() -> None:
    """Guard against the whole suite passing vacuously if the file moves."""
    assert (PLANS / STRICT_SLUG / "roadmap.yaml").is_file()


def test_every_ui_uplift_anchor_resolves() -> None:
    doc = _load(PLANS / STRICT_SLUG / "roadmap.yaml")
    anchors = list(_anchors(doc))
    assert anchors, "no links.code anchors found — the scan is broken"
    broken = [
        f"{iid}: {anchor}  ->  {reason}"
        for iid, anchor in anchors
        if (reason := _resolve(anchor))
    ]
    assert not broken, (
        f"{len(broken)} of {len(anchors)} links.code anchors in "
        f"plans/{STRICT_SLUG}/roadmap.yaml do not resolve:\n  "
        + "\n  ".join(broken)
        + "\n\nThese are what a Phase-0 dispatch hands an implementer. Prefer "
        "`path#<literal>` over `path:LINE` — this epic rewrites app.css and "
        "notebook_detail.html on nearly every milestone."
    )


def test_ui_uplift_uses_no_line_number_anchors() -> None:
    """The format rule, not just the resolution.

    A line anchor that happens to resolve today is not evidence of anything —
    twelve of these resolved perfectly while pointing at the wrong code,
    because a line number keeps resolving as the file grows around it. That is
    the whole failure mode, so the format itself is what gets banned here.
    """
    doc = _load(PLANS / STRICT_SLUG / "roadmap.yaml")
    line_anchors = [
        f"{iid}: {anchor}"
        for iid, anchor in _anchors(doc)
        if "#" not in anchor and _LINE_ANCHOR.match(anchor)
    ]
    assert not line_anchors, (
        f"plans/{STRICT_SLUG}/roadmap.yaml uses line-number anchors:\n  "
        + "\n  ".join(line_anchors)
        + "\n\nUse `path#<literal>` — a literal the file contains — so the "
        "anchor is resolved by searching rather than by counting. A line "
        "number in a hand-maintained document is stale by construction."
    )


def test_anchor_debt_in_other_roadmaps_does_not_grow() -> None:
    """A ratchet over the roadmaps this pass did not migrate."""
    unresolved: list[str] = []
    for path in _roadmaps():
        if path.parent.name == STRICT_SLUG:
            continue
        for iid, anchor in _anchors(_load(path)):
            if _resolve(anchor):
                unresolved.append(f"{path.parent.name}/{iid}: {anchor}")
    assert len(unresolved) == KNOWN_UNRESOLVED_ELSEWHERE, (
        f"unresolved links.code anchors outside plans/{STRICT_SLUG} is now "
        f"{len(unresolved)}, ratchet says {KNOWN_UNRESOLVED_ELSEWHERE}.\n"
        f"If you FIXED some, lower KNOWN_UNRESOLVED_ELSEWHERE in this file.\n"
        f"If this grew, a file was renamed or deleted without updating the "
        f"roadmaps that cite it.\nCurrent:\n  " + "\n  ".join(sorted(unresolved))
    )


# ---------------------------------------------------------------------------
# L4 — a plan may not invert its own dependency order
# ---------------------------------------------------------------------------
def find_inversions(doc: dict) -> list[str]:
    """Items scheduled to start before an UNSHIPPED dependency finishes.

    A dependency that has already shipped constrains nothing — its dependent
    may start whenever — so both ends are exempt once done. That is correct,
    and it is also why the data-driven tests below can go vacuous as a plan
    completes: `test_the_inversion_rule_actually_fires` pins the logic against
    synthetic input so the rule stays proven regardless of what the live
    roadmaps happen to contain.
    """
    by_id = {i["id"]: i for i in (doc.get("items") or []) if "id" in i}
    inverted = []
    for item in by_id.values():
        if str(item.get("status") or "").lower() in DONE_STATUSES:
            continue
        start = item.get("target_start")
        if start is None:
            continue
        for dep_id in item.get("depends_on") or []:
            dep = by_id.get(dep_id)
            if dep is None or str(dep.get("status") or "").lower() in DONE_STATUSES:
                continue
            end = dep.get("target_end")
            if end is not None and start < end:
                inverted.append(
                    f"{item['id']} starts {start} but {dep_id} ends {end}"
                )
    return sorted(inverted)


def test_the_inversion_rule_actually_fires() -> None:
    """The rule, proven on synthetic input.

    ui-uplift's dependency edges now all point at shipped milestones, so the
    live check below cannot currently fail for that roadmap no matter what the
    dates say. A guard whose subject has gone quiet proves nothing about the
    guard — this is what keeps L4 closed rather than merely unobservable.
    """
    def doc(**over):
        base = {"items": [
            {"id": "a", "target_start": "2026-01-01", "target_end": "2026-01-31"},
            {"id": "b", "depends_on": ["a"], "target_start": "2026-01-10",
             "target_end": "2026-01-20"},
        ]}
        base["items"][0].update(over.get("a", {}))
        base["items"][1].update(over.get("b", {}))
        return base

    # b starts inside a's window -> inversion
    assert find_inversions(doc()) == [
        "b starts 2026-01-10 but a ends 2026-01-31"
    ]
    # b starts after a ends -> clean
    assert find_inversions(doc(b={"target_start": "2026-02-01"})) == []
    # a has shipped -> it constrains nothing
    assert find_inversions(doc(a={"status": "done"})) == []
    # b has shipped -> its window is history
    assert find_inversions(doc(b={"status": "done"})) == []
    # a missing target_end -> nothing to compare
    assert find_inversions(doc(a={"target_end": None})) == []


@pytest.mark.parametrize(
    "roadmap", _roadmaps(), ids=lambda p: p.parent.name
)
def test_unshipped_items_do_not_start_before_their_dependencies_end(
    roadmap: Path,
) -> None:
    inverted = find_inversions(_load(roadmap))
    slug = roadmap.parent.name
    allowed = 0 if slug == STRICT_SLUG else KNOWN_INVERSIONS_ELSEWHERE.get(slug, 0)
    assert len(inverted) == allowed, (
        f"{slug}: {len(inverted)} dependency-order inversion(s), expected "
        f"{allowed}. A milestone is scheduled to start before the milestone it "
        f"depends_on finishes:\n  " + "\n  ".join(inverted or ["<none>"])
        + "\n\nEither move the dependent's window after its dependency's "
        "target_end, or drop the depends_on edge if it is not real. Shipped "
        "items are exempt — their windows are history, not plans. For roadmaps "
        "other than " + STRICT_SLUG + ", KNOWN_INVERSIONS_ELSEWHERE is a "
        "ratchet: lower it when you fix one, never raise it."
    )
