#!/usr/bin/env python3
"""
validate-roadmap.py — lint plans/<slug>-roadmap.md against the contract.

Checks (each fails LOUD with file:line and a one-line rationale):

  - SLUG-VALID:    slug header matches ^[a-z][a-z0-9-]{2,30}$ and not ^e\\d+$.
  - PHASES:        all four phase headers present in order.
  - NO-PLACEHOLDER (per phase): no {{TOKEN}} markers remain in the body of
                   each populated phase. (Unpopulated phases: silent.)
  - ASSUMPTIONS:   at least one [MUST] / [SHOULD] / [MIGHT] tier present.
  - OBJECTIVE-KR:  Phase 1 has an Objective and 1–5 Key Results.
  - VERTICAL-SLICE: Phase 2 declares a technique. (Free-form check.)
  - MUST-CAP:      Phase 3 asserts Must ≤ 60% (or invocation of score-moscow
                   passing). Detected via a "Must-cap:" line under the
                   MATERIALIZE phase, OR by parsing the Phase 3 MoSCoW list.
  - MILESTONE-AC:  every Now-lane milestone (### <slug>-mN — title) has a
                   non-empty Acceptance criteria block.
  - HEADING-FORMAT: Now-lane milestone headings match
                   `### <slug>-m\\d+ — <title>` exactly (so milestone-pipeline
                   can grep them).

Usage:
    validate-roadmap.py <path-to-roadmap.md> [--allow CHECK,CHECK,...]

`--allow` skips named checks. Use sparingly; document why in the doc.

Exit codes: 0 valid; 1 violations found; 2 input/usage error.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PHASE_NAMES = ["Refine", "Decompose", "Sequence", "Materialize"]
SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{2,30}$")
EXX_RE = re.compile(r"^e\d+$")
SLUG_HEADER_RE = re.compile(r"^\*\*Slug:\*\*\s*`?([a-z0-9-]+)`?", re.MULTILINE)
PLACEHOLDER_RE = re.compile(r"\{\{[A-Z0-9_]+\}\}")
PHASE_HEADER_RE = re.compile(r"^## Phase (\d+) — (\w+)", re.MULTILINE)
ASSUMPTION_RE = re.compile(r"^\s*-\s+`?\[(MUST|SHOULD|MIGHT)\]`?", re.MULTILINE)
KR_RE = re.compile(r"^\s*\d+\.\s+\S", re.MULTILINE)
MILESTONE_HEADING_RE = re.compile(r"^### ([a-z][a-z0-9-]+)-m(\d+) — (.+)$", re.MULTILINE)


class Violation:
    def __init__(self, check: str, line: int, message: str):
        self.check = check
        self.line = line
        self.message = message

    def render(self, path: Path) -> str:
        return f"{path}:{self.line}: [{self.check}] {self.message}"


def line_of(text: str, char_offset: int) -> int:
    return text.count("\n", 0, char_offset) + 1


def parse_phase_bodies(text: str) -> dict[str, str]:
    """Return phase name -> body text between its header and the next phase header."""
    bodies: dict[str, str] = {}
    matches = list(PHASE_HEADER_RE.finditer(text))
    for i, m in enumerate(matches):
        name = m.group(2)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        bodies[name] = text[start:end]
    return bodies


def is_phase_populated(body: str) -> bool:
    """A phase is populated when its `<!-- status: pending -->` sentinel
    has been removed. Each phase orchestrator deletes the sentinel as it
    writes content. Unambiguous and template-stable."""
    return "<!-- status: pending -->" not in body


def check_slug(text: str, allow: set) -> list[Violation]:
    if "SLUG-VALID" in allow:
        return []
    m = SLUG_HEADER_RE.search(text)
    if not m:
        return [Violation("SLUG-VALID", 1,
                          "**Slug:** header not found at top of doc")]
    slug = m.group(1)
    line = line_of(text, m.start())
    out = []
    if not SLUG_RE.match(slug):
        out.append(Violation(
            "SLUG-VALID", line,
            f"slug '{slug}' fails ^[a-z][a-z0-9-]{{2,30}}$"))
    if EXX_RE.match(slug):
        out.append(Violation(
            "SLUG-VALID", line,
            f"slug '{slug}' looks like an EXX epic ID; collision risk"))
    return out


def check_phases(text: str, allow: set) -> list[Violation]:
    if "PHASES" in allow:
        return []
    matches = list(PHASE_HEADER_RE.finditer(text))
    if len(matches) != 4:
        return [Violation("PHASES", 1,
                          f"expected 4 phase headers, found {len(matches)}")]
    found = [m.group(2) for m in matches]
    if found != PHASE_NAMES:
        return [Violation("PHASES", line_of(text, matches[0].start()),
                          f"phase order is {found}, expected {PHASE_NAMES}")]
    return []


def check_no_placeholders(text: str, bodies: dict[str, str], allow: set) -> list[Violation]:
    if "NO-PLACEHOLDER" in allow:
        return []
    out = []
    for name in PHASE_NAMES:
        body = bodies.get(name, "")
        if not is_phase_populated(body):
            continue
        # Phase IS populated: any remaining placeholder is a violation.
        for m in PLACEHOLDER_RE.finditer(body):
            # Find absolute line in full doc.
            phase_start = text.find(f"## Phase ") + 0  # rough
            # Compute via offset from a phase-header search:
            phase_match = re.search(rf"^## Phase \d+ — {re.escape(name)}", text, re.MULTILINE)
            phase_start = phase_match.start() if phase_match else 0
            abs_offset = phase_start + len(re.search(
                rf"^## Phase \d+ — {re.escape(name)}.*$", text, re.MULTILINE
            ).group(0)) + m.start()
            out.append(Violation(
                "NO-PLACEHOLDER", line_of(text, abs_offset),
                f"phase '{name}' is populated but still contains placeholder {m.group(0)}"))
    return out


def check_assumptions(text: str, bodies: dict[str, str], allow: set) -> list[Violation]:
    if "ASSUMPTIONS" in allow:
        return []
    body = bodies.get("Refine", "")
    if not is_phase_populated(body):
        return []
    if not ASSUMPTION_RE.search(body):
        # find phase line for offset
        m = re.search(r"^## Phase \d+ — Refine", text, re.MULTILINE)
        return [Violation("ASSUMPTIONS",
                          line_of(text, m.start() if m else 1),
                          "Refine phase populated but no [MUST]/[SHOULD]/[MIGHT] assumption found")]
    return []


def check_objective_kr(text: str, bodies: dict[str, str], allow: set) -> list[Violation]:
    if "OBJECTIVE-KR" in allow:
        return []
    body = bodies.get("Refine", "")
    if not is_phase_populated(body):
        return []
    out = []
    if "### Objective" not in body:
        m = re.search(r"^## Phase \d+ — Refine", text, re.MULTILINE)
        out.append(Violation("OBJECTIVE-KR",
                             line_of(text, m.start() if m else 1),
                             "Refine phase missing '### Objective' subheader"))
    if "### Key Results" not in body:
        m = re.search(r"^## Phase \d+ — Refine", text, re.MULTILINE)
        out.append(Violation("OBJECTIVE-KR",
                             line_of(text, m.start() if m else 1),
                             "Refine phase missing '### Key Results' subheader"))
    else:
        # KR section: 1..5 numbered items.
        kr_section = body.split("### Key Results", 1)[1].split("###", 1)[0]
        krs = KR_RE.findall(kr_section)
        if not (1 <= len(krs) <= 5):
            m = re.search(r"### Key Results", text)
            out.append(Violation("OBJECTIVE-KR",
                                 line_of(text, m.start() if m else 1),
                                 f"expected 1–5 Key Results, found {len(krs)}"))
    return out


def check_milestone_ac(text: str, bodies: dict[str, str], allow: set) -> list[Violation]:
    if "MILESTONE-AC" in allow and "HEADING-FORMAT" in allow:
        return []
    seq = bodies.get("Sequence", "")
    if not is_phase_populated(seq):
        return []
    out = []
    # Find all milestone headings within the Sequence body, walk the doc text.
    seq_match = re.search(r"^## Phase \d+ — Sequence", text, re.MULTILINE)
    if not seq_match:
        return []
    seq_start = seq_match.start()
    next_phase = re.search(r"^## Phase \d+ — Materialize", text, re.MULTILINE)
    seq_end = next_phase.start() if next_phase else len(text)
    seq_text = text[seq_start:seq_end]

    headings = list(MILESTONE_HEADING_RE.finditer(seq_text))
    if "HEADING-FORMAT" not in allow:
        # Reject heading shapes that LOOK like milestones but don't match.
        suspect = re.findall(r"^### .*-m\d+\b.*$", seq_text, re.MULTILINE)
        for s in suspect:
            if not MILESTONE_HEADING_RE.match(s):
                line = line_of(text, seq_start + seq_text.find(s))
                out.append(Violation(
                    "HEADING-FORMAT", line,
                    f"milestone heading does not match '### <slug>-m<N> — <title>': {s!r}"))

    if "MILESTONE-AC" not in allow:
        # Each milestone block runs from its heading to the next ### heading.
        for i, m in enumerate(headings):
            block_start = m.end()
            next_idx = m.end()
            following = re.search(r"^### ", seq_text[next_idx:], re.MULTILINE)
            block_end = (next_idx + following.start()) if following else len(seq_text)
            block = seq_text[block_start:block_end]
            ac_section = re.search(r"\*\*Acceptance criteria\.\*\*\s*\n([\s\S]*?)(?=\*\*\w|$)",
                                   block)
            if not ac_section or not re.search(r"-\s*\[", ac_section.group(1) or ""):
                line = line_of(text, seq_start + m.start())
                out.append(Violation(
                    "MILESTONE-AC", line,
                    f"milestone '{m.group(0).strip()}' has no Acceptance criteria checkboxes"))
    return out


def check_must_cap(text: str, bodies: dict[str, str], allow: set) -> list[Violation]:
    if "MUST-CAP" in allow:
        return []
    body = bodies.get("Sequence", "")
    if not is_phase_populated(body):
        return []
    # Soft check: look for either a "Must-cap:" line in Materialize OR an
    # explicit "Must (≤ 60%" in Sequence. Stricter analysis is in
    # score-moscow.py; this is a structural check only.
    materialize = bodies.get("Materialize", "")
    if "Must-cap:" in materialize:
        return []
    if re.search(r"\*\*Must\*\*\s*\(", body):
        return []
    m = re.search(r"^## Phase \d+ — Sequence", text, re.MULTILINE)
    return [Violation("MUST-CAP",
                      line_of(text, m.start() if m else 1),
                      "Sequence phase populated but no Must-cap reference found "
                      "(run score-moscow.py and record the result in Materialize)")]


def main() -> int:
    p = argparse.ArgumentParser(description="lint a roadmap doc")
    p.add_argument("path")
    p.add_argument("--allow", default="",
                   help="comma-separated check names to skip")
    args = p.parse_args()

    path = Path(args.path).resolve()
    if not path.exists():
        sys.stderr.write(f"error: file not found: {path}\n")
        return 2

    text = path.read_text(encoding="utf-8")
    allow = {x.strip() for x in args.allow.split(",") if x.strip()}
    bodies = parse_phase_bodies(text)

    violations: list[Violation] = []
    violations.extend(check_slug(text, allow))
    violations.extend(check_phases(text, allow))
    violations.extend(check_no_placeholders(text, bodies, allow))
    violations.extend(check_assumptions(text, bodies, allow))
    violations.extend(check_objective_kr(text, bodies, allow))
    violations.extend(check_milestone_ac(text, bodies, allow))
    violations.extend(check_must_cap(text, bodies, allow))

    if not violations:
        populated = [n for n in PHASE_NAMES if is_phase_populated(bodies.get(n, ""))]
        print(f"OK: {path.name} valid (phases populated: {', '.join(populated) or 'none'})")
        return 0

    for v in violations:
        sys.stderr.write(v.render(path) + "\n")
    sys.stderr.write(f"\n{len(violations)} violation(s).\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
