#!/usr/bin/env python3
"""
dedupe-findings.py — group cross-critic findings within N lines of the same file.

Parses a critique markdown file emitted by Phase 3 and inserts (or replaces)
a "## Cross-critic agreement" section listing every file:line region where
≥ 2 critics flagged a finding.

Idempotent: re-running on an already-deduped file replaces the existing
section. If the dedupe output is byte-identical to the previous run, the
file is not rewritten.

Finding format expected (from references/critique-format.md):

    ### F<id> — <title>
    - **Severity:** CRITICAL | HIGH | MEDIUM | LOW
    - **Source:** adversary | frontend-ux | infra-safety | oss-scout
    - **File:** path/to/file.py:42
    - **What:** ...

Usage:
    dedupe-findings.py <critique.md> [--threshold N]
        --threshold N   line-window for grouping (default 5)

Exit codes:
    0  success (file possibly rewritten)
    1  parse failure / empty findings
    2  input / usage error
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

FINDING_HEADING = re.compile(r"^### ((?:F|IS|OS|UX)\d+) — (.+)$")
FILE_LINE = re.compile(r"\*\*File:\*\*\s*(\S+):(\d+)")
SEVERITY = re.compile(r"\*\*Severity:\*\*\s*(\w+)", re.IGNORECASE)
SOURCE = re.compile(r"\*\*Source:\*\*\s*([\w-]+)", re.IGNORECASE)

AGREEMENT_HEADER = "## Cross-critic agreement"
AGREEMENT_END_MARKER = "<!-- end:cross-critic-agreement -->"


def parse_findings(text: str) -> list[dict]:
    out = []
    lines = text.splitlines()
    current = None
    for line in lines:
        m = FINDING_HEADING.match(line)
        if m:
            if current:
                out.append(current)
            current = {"id": m.group(1), "title": m.group(2), "file": None,
                       "line": None, "severity": None, "source": None}
            continue
        if current is None:
            continue
        if (fm := FILE_LINE.search(line)):
            current["file"] = fm.group(1)
            current["line"] = int(fm.group(2))
        if (sm := SEVERITY.search(line)) and not current["severity"]:
            current["severity"] = sm.group(1).upper()
        if (om := SOURCE.search(line)) and not current["source"]:
            current["source"] = om.group(1).lower()
    if current:
        out.append(current)
    return out


def group_findings(findings: list[dict], threshold: int) -> list[list[dict]]:
    """Group findings on the same file whose lines fall within ±threshold of each other."""
    by_file: dict[str, list[dict]] = {}
    for f in findings:
        if f.get("file") and f.get("line") is not None:
            by_file.setdefault(f["file"], []).append(f)

    groups: list[list[dict]] = []
    for file_path, items in by_file.items():
        items.sort(key=lambda x: x["line"])
        cur: list[dict] = []
        for item in items:
            if not cur or item["line"] - cur[-1]["line"] <= threshold:
                cur.append(item)
            else:
                if len({c.get("source") for c in cur if c.get("source")}) >= 2:
                    groups.append(cur)
                cur = [item]
        if cur and len({c.get("source") for c in cur if c.get("source")}) >= 2:
            groups.append(cur)
    return groups


def render_agreement(groups: list[list[dict]]) -> str:
    if not groups:
        body = "_None — no file:line region was flagged by ≥ 2 critics._\n"
    else:
        parts = []
        for g in groups:
            file_path = g[0]["file"]
            lo = min(item["line"] for item in g)
            hi = max(item["line"] for item in g)
            sources = sorted({item.get("source") or "?" for item in g})
            ids = ", ".join(item["id"] for item in g)
            severities = sorted({item.get("severity") or "?" for item in g})
            range_str = f"{file_path}:{lo}" if lo == hi else f"{file_path}:{lo}-{hi}"
            parts.append(
                f"- **{range_str}** — flagged by {', '.join(sources)} "
                f"(findings: {ids}; severities: {', '.join(severities)})"
            )
        body = "\n".join(parts) + "\n"
    return f"{AGREEMENT_HEADER}\n\n{body}\n{AGREEMENT_END_MARKER}\n"


def splice_section(text: str, new_section: str) -> str:
    """Insert or replace the agreement section. Inserted before the first '## ' that
    isn't the agreement header itself, or appended if none found."""
    # Replace existing section if present.
    pattern = re.compile(
        re.escape(AGREEMENT_HEADER) + r".*?" + re.escape(AGREEMENT_END_MARKER) + r"\n?",
        re.DOTALL,
    )
    if pattern.search(text):
        return pattern.sub(new_section, text, count=1)
    # Otherwise, insert before "## Findings" if present, else append.
    findings_h2 = re.search(r"^## Findings.*$", text, re.MULTILINE)
    if findings_h2:
        idx = findings_h2.start()
        return text[:idx] + new_section + "\n" + text[idx:]
    return text.rstrip() + "\n\n" + new_section


def atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    # Windows refuses fsync on O_RDONLY handles; the write_text() above
    # already closed its handle so the data is in the OS buffer. NTFS
    # rename + os.replace below is durable enough for our purposes.
    if sys.platform != "win32":
        fd = os.open(str(tmp), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    os.replace(tmp, path)


def main() -> int:
    p = argparse.ArgumentParser(description="dedupe critic findings")
    p.add_argument("critique", help="path to critique markdown file")
    p.add_argument("--threshold", type=int, default=5, help="line-window (default 5)")
    args = p.parse_args()

    path = Path(args.critique).resolve()
    if not path.exists():
        sys.stderr.write(f"error: critique not found: {path}\n")
        return 2

    text = path.read_text(encoding="utf-8")
    findings = parse_findings(text)
    if not findings:
        sys.stderr.write("error: no findings parsed (expected '### F<n> — <title>' headings)\n")
        return 1

    groups = group_findings(findings, args.threshold)
    section = render_agreement(groups)
    new_text = splice_section(text, section)

    if new_text == text:
        print(f"no-op: {path.name} already up to date ({len(groups)} agreement(s))")
        return 0

    atomic_write(path, new_text)
    print(f"updated {path.name}: {len(groups)} cross-critic agreement(s) recorded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
