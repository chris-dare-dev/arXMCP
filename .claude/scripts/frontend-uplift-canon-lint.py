#!/usr/bin/env python3
"""frontend-uplift-canon-lint.py — structural guard for the frontend canon files.

Frontend-pipeline critique round 1, findings C-2/C-3 (freshness) + R-8 (multi-writer token
collisions) + R-2 (asserted-vs-derived challenge counts). Three duties, one parser home:

  check [--strict] [--root DIR]   stamps present+parseable on the claim-table sections of the
                                  four canon files; token tables (MOT-N / EXP-N / REF-N)
                                  collision-free. Staleness (> 120 days) is a WARNING —
                                  CI must never go red because time passed (--strict flips
                                  warnings to failures for interactive use).
  tally <challenge.md>            declared Counts block must equal the mechanical per-axis-row
                                  tally (counting unit: candidate × axis row — phase-3.md).
                                  Verdict-rule consistency is advisory (WARN only).
  --self-test                     fixture-based regression suite (CI-wired).

Exit codes: 0 ok (warnings allowed) · 2 failure (missing/malformed stamp, token collision,
tally mismatch, parse failure) · 3 usage.
"""

import argparse
import datetime
import os
import pathlib
import re
import subprocess
import sys
import tempfile

# Windows consoles default to cp1252, but this script prints UTF-8 (check marks, section
# signs, arrows). Without this, printing the scorecard template or a diff raises
# UnicodeEncodeError partway through and truncates the output while still exiting non-zero.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

STALENESS_DAYS = 120

# file (relative to repo root) -> section-heading prefixes that MUST carry a stamp.
# THIS dict is the machine-readable census of stamped sections (registry §0 points here —
# round-2 L-3: prose and lint each said "which sections" once; the lint is authoritative).
# Trailing space in each prefix prevents "## §1 " from ever matching a future "## §10 …".
REQUIRED_STAMPS = {
    ".claude/references/frontend-uplift-source-registry.md": [
        "## §1 ", "## §2 ", "## §3 ", "## §4 ", "## §5 ", "## §6 ", "## §7 ",
    ],
    ".claude/references/frontend-uplift-motion-vocabulary.md": ["## §10 "],
    ".claude/references/frontend-uplift-experiential-motion.md": ["## §5 ", "## §6 "],
    ".claude/references/frontend-design-language.md": ["## §12 "],
}

# file -> list of (token_name, [regexes that define a token occurrence])
TOKEN_DEFS = {
    ".claude/references/frontend-uplift-motion-vocabulary.md": [
        ("MOT", [re.compile(r"^\|\s*MOT-(\d+)\s*\|")]),
    ],
    ".claude/references/frontend-uplift-experiential-motion.md": [
        ("EXP", [re.compile(r"^\|\s*EXP-(\d+)\s*\|"),
                 re.compile(r"^## §3 addendum — \[EXP-(\d+)")]),
    ],
    ".claude/references/frontend-design-language.md": [
        ("REF", [re.compile(r"^\|\s*REF-(\d+)\s*\|")]),
    ],
}

STAMP_RE = re.compile(r"^\*\*Last-verified:\*\*\s*(\d{4}-\d{2}-\d{2})")
SEVERITIES = ("BLOCKER", "MAJOR", "MINOR", "NONE")


def _strip_fences(lines):
    out, in_fence, tok = [], False, None
    for line in lines:
        s = line.lstrip()
        if s.startswith("```") or s.startswith("~~~"):
            t = s[:3]
            if not in_fence:
                in_fence, tok = True, t
            elif t == tok:
                in_fence, tok = False, None
            out.append("")
            continue
        out.append("" if in_fence else line)
    return out


def _read(path):
    with open(path, encoding="utf-8") as f:
        return _strip_fences(f.read().splitlines())


def check_stamps(root, required=REQUIRED_STAMPS, today=None):
    """Returns (failures, warnings)."""
    failures, warnings = [], []
    today = today or datetime.date.today()
    for rel, headings in required.items():
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            failures.append(f"{rel}: file missing")
            continue
        lines = _read(path)
        for prefix in headings:
            start = next((i for i, ln in enumerate(lines) if ln.startswith(prefix)), None)
            if start is None:
                failures.append(f"{rel}: required section '{prefix}' not found")
                continue
            stamp = None
            for ln in lines[start + 1:]:
                if ln.startswith("## "):
                    break
                m = STAMP_RE.match(ln)
                if m:
                    stamp = m.group(1)
                    break
            if stamp is None:
                failures.append(f"{rel} '{prefix}': missing '**Last-verified:** YYYY-MM-DD' stamp")
                continue
            try:
                d = datetime.date.fromisoformat(stamp)
            except ValueError:
                failures.append(f"{rel} '{prefix}': unparseable stamp '{stamp}'")
                continue
            age = (today - d).days
            if age > STALENESS_DAYS:
                warnings.append(
                    f"{rel} '{prefix}': stale ({age}d > {STALENESS_DAYS}d) — trigger T3: "
                    "re-verify the entries relied on and update the stamp in-run"
                )
    return failures, warnings


def check_tokens(root, defs=TOKEN_DEFS):
    failures, warnings = [], []
    for rel, groups in defs.items():
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            failures.append(f"{rel}: file missing")
            continue
        lines = _read(path)
        for name, regexes in groups:
            seen = {}
            for i, line in enumerate(lines, 1):
                for rx in regexes:
                    m = rx.match(line)
                    if m:
                        n = int(m.group(1))
                        if n in seen:
                            failures.append(
                                f"{rel}: duplicate {name}-{n} definition "
                                f"(lines {seen[n]} and {i}) — token collision breaks Phase-2 dedup"
                            )
                        else:
                            seen[n] = i
            if seen:
                mx = max(seen)
                missing = [str(n) for n in range(1, mx + 1) if n not in seen]
                if missing:
                    warnings.append(
                        f"{rel}: {name} numbering has gaps ({', '.join(missing)}) — "
                        "fine if deliberate removals; new tokens must not reuse gap numbers"
                    )
    return failures, warnings


def _repo_root():
    """Repo root: $REPO_ROOT, else `git rev-parse --show-toplevel`, else parents[2]."""
    env = os.environ.get("REPO_ROOT")
    if env:
        return env
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if out:
            return out
    except (OSError, subprocess.SubprocessError):
        pass
    return str(pathlib.Path(__file__).resolve().parents[2])


def cmd_check(root, strict):
    f1, w1 = check_stamps(root)
    f2, w2 = check_tokens(root)
    failures, warnings = f1 + f2, w1 + w2
    for w in warnings:
        print(f"WARN: {w}")
    for f in failures:
        print(f"FAIL: {f}", file=sys.stderr)
    if failures or (strict and warnings):
        return 2
    print(f"canon-lint check: OK ({len(warnings)} warning(s))")
    return 0


def parse_challenge(lines):
    """Return (declared: dict, derived: dict, redesign_no_blockers: int, verdict: str|None, errors)."""
    errors = []
    declared, verdict = {}, None
    in_counts = in_findings = in_verdict = False
    derived = {s: 0 for s in SEVERITIES}
    redesign_no_blockers = 0
    for line in lines:
        if line.startswith("## "):
            in_counts = line.startswith("## Counts")
            in_findings = line.startswith("## Per-candidate findings")
            in_verdict = line.startswith("## Verdict")
            continue
        if in_verdict and verdict is None:
            s = line.strip().strip("*")
            if s in ("SHIP", "DO-NOT-SHIP", "MIXED", "BLOCKED"):
                verdict = s
        if in_counts:
            for sev in SEVERITIES:
                # Only the two canonical count forms declare a count — a table row
                # (`| BLOCKER (critical) | 3 |`) or a plain line (`BLOCKER (critical): 3`).
                # Prose mentioning severities (e.g. an inline verdict-rule reminder) must not parse.
                m = (re.match(rf"^\|[^|]*\b{sev}\b[^|]*\|\s*\**(\d+)\**\s*\|\s*$", line)
                     or re.match(rf"^\**{sev}\b[^:|]*:\s*\**(\d+)\**\s*$", line.strip()))
                if m:
                    if sev in declared:
                        errors.append(f"duplicate '{sev}' line in Counts (stale duplicate misleads)")
                    else:
                        declared[sev] = int(m.group(1))
        if in_findings and line.lstrip().startswith("|"):
            cells = [c.strip() for c in line.split("|")]
            for idx, c in enumerate(cells):
                base = c.replace("/ PASS", "").replace("/PASS", "").strip()
                if base in SEVERITIES:
                    derived[base] += 1
                    if base == "BLOCKER":
                        # Un-redesignable = the redesign cell answers the word NO —
                        # word-boundary, so "None needed" does not count (round-2 L-4).
                        rest = " ".join(cells[idx + 1:idx + 2]).upper()
                        if re.match(r"^NO\b(?!NE)", rest):
                            redesign_no_blockers += 1
    missing = [s for s in SEVERITIES if s not in declared]
    if missing:
        errors.append(f"Counts block missing severities: {', '.join(missing)}")
    return declared, derived, redesign_no_blockers, verdict, errors


def cmd_tally(path):
    try:
        lines = _read(path)
    except OSError as exc:
        print(f"FAIL: cannot read {path}: {exc}", file=sys.stderr)
        return 2
    declared, derived, undesignable, verdict, errors = parse_challenge(lines)
    for e in errors:
        print(f"FAIL: {e}", file=sys.stderr)
    mismatches = [
        f"{sev}: declared {declared.get(sev)} != derived {derived[sev]}"
        for sev in SEVERITIES
        if sev in declared and declared[sev] != derived[sev]
    ]
    for m in mismatches:
        print(f"FAIL: {m} (counting unit: candidate × axis row — phase-3.md)", file=sys.stderr)
    if verdict and not errors and not mismatches:
        # ADVISORY implementation of the phase-3 verdict rule (the rule's ONE home stays
        # phase-3.md — this block cites/implements it, it is not a second spelling; a
        # mismatch WARNs and never fails, round-2 L-4).
        n_blocker, n_major = derived["BLOCKER"], derived["MAJOR"]
        if undesignable >= 1 or n_major >= 5:
            expect = "DO-NOT-SHIP"
        elif n_blocker == 0 and n_major <= 2:
            expect = "SHIP"
        else:
            expect = "MIXED"
        if verdict != expect:
            print(
                f"WARN: declared verdict {verdict} but the phase-3 rule computes {expect} "
                f"(BLOCKER={n_blocker}, un-redesignable={undesignable}, MAJOR={n_major}) — "
                "advisory only; state the reason in the verdict section if deliberate"
            )
    if errors or mismatches:
        return 2
    print(
        "tally OK: "
        + " ".join(f"{s}={derived[s]}" for s in SEVERITIES)
        + (f" verdict={verdict}" if verdict else "")
    )
    return 0


# ------------------------------------------------------------------ self-test
GOOD_CHALLENGE = """# Challenge — fixture

## Verdict

MIXED

## Counts

| Severity | Count |
|---|---|
| BLOCKER (critical) | 2 |
| MAJOR (high) | 3 |
| MINOR (medium) | 1 |
| NONE / PASS (low) | 3 |

## Per-candidate findings

### C1
| Axis | Finding | Severity | Re-design possible? |
|---|---|---|---|
| 1 | this text mentions a BLOCKER dependency in prose | MAJOR | YES |
| 2 | fine | NONE | n/a |
| 3 | bad on S-2 | BLOCKER | YES — retag surface |

### C2
| Axis | Finding | Severity | Re-design possible? |
|---|---|---|---|
| 1 | hard-coded ms | MAJOR | YES |
| 2 | fine | NONE | n/a |
| 3 | minor nit | MINOR | YES |
| 4 | slow | MAJOR | YES |
| 5 | fine | NONE / PASS | n/a |
| 6 | dep blocker | BLOCKER | None needed — lands with X2 |
"""


def self_test():
    failures = []

    def expect(name, got, want):
        if got != want:
            failures.append(f"{name}: got {got}, want {want}")

    with tempfile.TemporaryDirectory() as td:
        # --- stamps fixtures
        rel = ".claude/references/frontend-uplift-source-registry.md"
        p = os.path.join(td, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        req = {rel: ["## §1 ", "## §2 "]}
        with open(p, "w", encoding="utf-8") as f:
            f.write("## §1 — a\n\n**Last-verified:** 2026-07-01\n\n## §2 — b\n\n**Last-verified:** 2020-01-01\n")
        fails, warns = check_stamps(td, req, today=datetime.date(2026, 7, 9))
        expect("stamps: no failures", len(fails), 0)
        expect("stamps: stale warns", len(warns), 1)
        with open(p, "w", encoding="utf-8") as f:
            f.write("## §1 — a\n\ntext, no stamp\n\n## §2 — b\n\n**Last-verified:** not-a-date\n")
        fails, warns = check_stamps(td, req, today=datetime.date(2026, 7, 9))
        expect("stamps: missing+unparseable fail", len(fails), 2)
        # fenced stamp is inert
        with open(p, "w", encoding="utf-8") as f:
            f.write("## §1 — a\n\n```\n**Last-verified:** 2026-07-01\n```\n\n## §2 — b\n\n**Last-verified:** 2026-07-01\n")
        fails, _ = check_stamps(td, req, today=datetime.date(2026, 7, 9))
        expect("stamps: fenced stamp does not count", len(fails), 1)

        # --- token fixtures
        rel2 = ".claude/references/frontend-uplift-motion-vocabulary.md"
        p2 = os.path.join(td, rel2)
        os.makedirs(os.path.dirname(p2), exist_ok=True)
        defs = {rel2: [("MOT", [re.compile(r"^\|\s*MOT-(\d+)\s*\|")])]}
        with open(p2, "w", encoding="utf-8") as f:
            f.write("| MOT-1 | a |\n| MOT-2 | b |\n| MOT-2 | dup |\n| MOT-4 | gap |\n")
        fails, warns = check_tokens(td, defs)
        expect("tokens: duplicate fails", len(fails), 1)
        expect("tokens: gap warns", len(warns), 1)

        # --- tally fixtures
        good = os.path.join(td, "challenge-good.md")
        with open(good, "w", encoding="utf-8") as f:
            f.write(GOOD_CHALLENGE)
        expect("tally: matching counts pass", cmd_tally(good), 0)
        # A prose verdict-rule reminder inside Counts must NOT parse as a count line
        # (the 2026-06 run kept one there; false duplicate-detection would mislead).
        prosey = os.path.join(td, "challenge-prose.md")
        with open(prosey, "w", encoding="utf-8") as f:
            f.write(GOOD_CHALLENGE.replace(
                "## Per-candidate findings",
                "*(Verdict rule: 0 BLOCKER + <= 2 MAJOR = SHIP; >= 1 BLOCKER OR >= 5 MAJOR = "
                "DO-NOT-SHIP; otherwise MIXED.)*\n\n## Per-candidate findings"))
        expect("tally: prose rule line in Counts is inert", cmd_tally(prosey), 0)
        bad = os.path.join(td, "challenge-bad.md")
        with open(bad, "w", encoding="utf-8") as f:
            f.write(GOOD_CHALLENGE.replace("| MAJOR (high) | 3 |", "| MAJOR (high) | 6 |"))
        expect("tally: mismatch fails", cmd_tally(bad), 2)
        dup = os.path.join(td, "challenge-dup.md")
        with open(dup, "w", encoding="utf-8") as f:
            f.write(GOOD_CHALLENGE.replace(
                "| BLOCKER (critical) | 2 |",
                "| BLOCKER (critical) | 2 |\n| BLOCKER (critical) | 2 |"))
        expect("tally: duplicate counts line fails", cmd_tally(dup), 2)
        # "None needed" in the redesign cell must NOT count as un-redesignable (L-4):
        # GOOD_CHALLENGE carries exactly that cell on a BLOCKER row and declares MIXED —
        # a false "NO" read would advise DO-NOT-SHIP. Assert no warning path breaks exit 0
        # (already covered by the matching-counts pass above) and the parse counts 0:
        with open(good, encoding="utf-8") as f:
            _, _, undes, _, _ = parse_challenge(_strip_fences(f.read().splitlines()))
        expect("tally: 'None needed' not un-redesignable", undes, 0)

    if failures:
        for f in failures:
            print(f"SELF-TEST FAIL: {f}", file=sys.stderr)
        return 1
    print("frontend-uplift-canon-lint.py self-test: all assertions passed")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="frontend-uplift-canon-lint.py")
    parser.add_argument("--self-test", action="store_true")
    sub = parser.add_subparsers(dest="cmd")
    c = sub.add_parser("check")
    c.add_argument("--strict", action="store_true")
    c.add_argument("--root", default=None)
    t = sub.add_parser("tally")
    t.add_argument("challenge")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.cmd == "check":
        return cmd_check(args.root or _repo_root(), args.strict)
    if args.cmd == "tally":
        return cmd_tally(args.challenge)
    parser.print_usage(sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
