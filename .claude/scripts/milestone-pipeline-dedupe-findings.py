#!/usr/bin/env python3
"""Dedupe critique findings within a single critique markdown file.

Use case: Phase 3 of /milestone-pipeline fans out 2+ critics in parallel
(adversary + any repo-local overlay critics + oss-scout).  The orchestrator
concatenates their outputs into one file (critique/dedup.md).  Multiple
critics often flag the same file:line with different framing.  This script:

  1. Parses findings from the canonical critique format
     (.claude/references/milestone-pipeline-critique-format.md):
     `### <SEVERITY> -- <title>` header + `**Where:** \`<file>:<line>\`` body.
  2. Groups findings within a 5-line window of the same file.
  3. For each duplicate cluster, emits a "Cross-critic agreement" callout
     naming the findings that flagged it (these are the strongest signals).
  4. Rewrites the file in place, preserving the canonical section order.

Usage: milestone-pipeline-dedupe-findings.py <critique.md>

Idempotent: if the file already shows "Cross-critic agreement" callouts,
exits with no change.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

# Force UTF-8 stdout/stderr so non-ASCII finding text does not crash on
# Windows's default cp1252 codepage.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# Canonical finding header from milestone-pipeline-critique-format.md:
#   ### CRITICAL -- <short title>
#   ### HIGH -- <short title>
#   ### MEDIUM -- <short title>
#   ### LOW -- <short title>
# Accept both ASCII hyphen and em-dash separators.  Use the Unicode escape
# — instead of a literal em-dash so the regex stays correct even if
# this file is re-saved as cp1252 (which would clobber the literal em-dash
# into a multi-byte sequence and silently break the match).
FINDING_RE = re.compile(
    r"^###\s+(CRITICAL|HIGH|MEDIUM|LOW)\s*[—\-]\s*(.+?)\s*$",
    re.MULTILINE,
)
# Per-finding "Where:" line carries the file:line citation:
#   **Where:** `path/to/file.py:123` (or "no specific file" for cross-cutting)
FILE_LINE_RE = re.compile(r"^\*\*Where:\*\*\s*`([^`:]+):(\d+)`", re.MULTILINE)


def parse_findings(text: str) -> list[dict]:
    """Return a list of {id, title, severity, file, line, body, start, end} dicts.

    Finding ids are synthesized as `<sev-initial><serial>` per severity
    (C1, C2, H1, H2, M1, ..., L1, L2, ...) since the canonical
    critique-format headers do not carry an explicit id.
    """
    findings = []
    matches = list(FINDING_RE.finditer(text))
    counters = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for i, m in enumerate(matches):
        block_start = m.start()
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[block_start:block_end]
        fl = FILE_LINE_RE.search(block)
        if not fl:
            continue
        severity = m.group(1)
        title = m.group(2).strip()
        counters[severity] += 1
        fid = f"{severity[0]}{counters[severity]}"
        findings.append(
            {
                "id": fid,
                "title": title,
                "severity": severity,
                "file": fl.group(1),
                "line": int(fl.group(2)),
                "body": block,
                "start": block_start,
                "end": block_end,
            }
        )
    return findings


def cluster(findings: list[dict], window: int = 5) -> list[list[dict]]:
    """Group findings within `window` lines of each other, in the same file."""
    by_file: dict[str, list[dict]] = defaultdict(list)
    for f in findings:
        by_file[f["file"]].append(f)
    clusters: list[list[dict]] = []
    for file_findings in by_file.values():
        file_findings.sort(key=lambda f: f["line"])
        cur_cluster: list[dict] = []
        for f in file_findings:
            if cur_cluster and f["line"] - cur_cluster[-1]["line"] <= window:
                cur_cluster.append(f)
            else:
                if len(cur_cluster) > 1:
                    clusters.append(cur_cluster)
                cur_cluster = [f]
        if len(cur_cluster) > 1:
            clusters.append(cur_cluster)
    return clusters


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    path = Path(argv[1])
    if not path.exists():
        print(f"file not found: {path}", file=sys.stderr)
        return 1
    text = path.read_text(encoding="utf-8")
    if "Cross-critic agreement" in text:
        print(f"{path}: already deduped (skipping)")
        return 0

    findings = parse_findings(text)
    clusters = cluster(findings)
    if not clusters:
        print(f"{path}: {len(findings)} findings; no duplicates")
        return 0

    callouts = ["", "## Cross-critic agreement", ""]
    callouts.append(
        "The following findings cluster within 5 lines of each other in the same file. "
        "Multiple critics flagged the same area -- these are the strongest signals to fix first.\n"
    )
    for cl in clusters:
        ids = ", ".join(f["id"] for f in cl)
        sev = max(cl, key=lambda f: "CHML".index(f["severity"][0]))["severity"]
        loc = f"{cl[0]['file']}:{cl[0]['line']}-{cl[-1]['line']}"
        titles = "; ".join(f["title"] for f in cl)
        callouts.append(f"- **{ids}** at `{loc}` ({sev}): {titles}")

    # Insert before "## Recommended rectification order" (canonical section)
    marker = "## Recommended rectification order"
    if marker in text:
        rewritten = text.replace(marker, "\n".join(callouts) + "\n\n" + marker, 1)
    else:
        # No rectification section yet -- append at end
        rewritten = text.rstrip() + "\n\n" + "\n".join(callouts) + "\n"
    path.write_text(rewritten, encoding="utf-8")
    print(f"{path}: deduped -- {len(clusters)} cluster(s) covering {sum(len(c) for c in clusters)} findings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
