#!/usr/bin/env python3
"""milestone-pipeline-findings.py - the findings register: parser, writer, gate.

A Phase-3 critique is prose; Phase 4 needs to ENFORCE "every CRITICAL/HIGH is
fixed-or-invalidated before complete" without re-reading that prose. This script
is the single authority for that. It materialises one object per finding into a
machine register and answers the completion gate from it.

Register location:
  <repo-root>/.claude/notes/milestones/<ID>/findings.json
Ephemeral, same tier as state.json (gitignore it; never commit, never move it
into a tracked path). The critique markdown under critique/ is the durable
evidence; findings.json is derived, disposable state.

Subcommands:
  merge <out.md> <in1.md> [in2.md ...]     combine per-critic critiques (renumbers)
  extract --id <ID> [<critique.md> ...]   parse critique(s) -> merge-safe write
  extract --check <critique.md> [...]      lint only; exit 1 on any malformed block
  set <ID> <ids> <fixed|deferred|invalidated> --resolution "..."   sole status writer
  gate <ID>                                exit 3 while any CRITICAL/HIGH is open
  summary <ID> [--field NAME]              derive count/id arrays for state.json
  summary --counts-for <critique.md>       C/H/M/L tally of one file (replaces grep -c)
  dedupe <critique.md>                     cross-critic agreement clustering
  --self-test                              run the embedded fixtures; exit 0 on pass

`merge` exists because critics author ids from 1 within their OWN file, so two
critics both emit C1/M1/L1 and a naive `cat` produces duplicate ids that dedupe
refuses outright. It renumbers into one gapless per-severity sequence in the
argv order (= critic dispatch order), emits exactly ONE `Severity counts:` line
and ONE `## Recommended rectification order` heading, and self-verifies its own
output through this file's parser before writing.

Exit codes:
  0  success (gate: no open CRITICAL/HIGH, or no register at all)
  1  malformed critique, or extract refusal (a registered id / critique file
     would be dropped)
  2  usage error, unknown id, or a forbidden status-machine transition
  3  gate refusal: at least one CRITICAL or HIGH finding is still open

Runtime contract: this file is COPIED by sync-repos.py into each consumer repo's
.claude/scripts/. It resolves the repo root itself (env -> git -> walk) and
locates no sibling by absolute path. Stdlib only (no PyYAML, no fcntl): fcntl is
POSIX-only and raises on import under win32, so serialisation relies on the
single-milestone .claude/notes/milestones/.lock (taken by init-state.sh) plus
atomic temp+os.replace writes in the target directory - the same discipline
checkpoint.py uses. Never introduce a flock here.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# Force UTF-8 stdout/stderr so non-ASCII finding text does not crash on Windows'
# default cp1252 codepage. All print() output in this module is ASCII, but a
# critique title echoed back could carry any UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

try:
    from datetime import UTC, datetime
except ImportError:  # pragma: no cover -- Python <3.11 fallback
    from datetime import datetime, timezone  # noqa: UP017

    UTC = timezone.utc  # type: ignore[assignment]  # noqa: UP017

CRITIQUE_FORMAT_VERSION = "1.0"

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
# Authored-id letter must agree with the severity in the header suffix.
LETTER_SEVERITY = {"C": "CRITICAL", "H": "HIGH", "M": "MEDIUM", "L": "LOW"}
# Gate-relevant severities: an open CRITICAL or HIGH blocks completion.
BLOCKING = ("CRITICAL", "HIGH")

# Forward-only status machine (v1 has NO reopen edge - a fixed/invalidated
# finding is terminal; re-litigating a disposition means a new milestone).
STATUSES = ("open", "fixed", "deferred", "invalidated")
ALLOWED_TRANSITIONS = {
    "open": {"fixed", "deferred", "invalidated"},
    "deferred": {"fixed"},
    "fixed": set(),
    "invalidated": set(),
}

# Milestone id is used to build a filesystem path. Constrain it to a traversal
# floor so a typo'd or hostile id (e.g. one containing "/" or "..") can never
# escape the .claude/notes/milestones/ tier. The live pipeline enforces the
# stricter <slug>-mN / <slug>-spike-N / adhoc-YYYYMMDD-<sha7> shape upstream in
# init-state.sh; this is a security floor, not the full grammar.
MILESTONE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# --- Critique v1.0 parser (see milestone-pipeline-critique-format.md) ---------
#
# Authored bold-header id, severity in a trailing paren:
#   **C1 -- short title** (CRITICAL)
# Accept em-dash or ASCII hyphen between id and title. Use the - escape
# (the re module honours it even in a raw string), never a literal em-dash, so
# the regex survives a cp1252 re-save of this file.
FINDING_RE = re.compile(
    r"^\*\*([CHML])(\d+)\s*[\u2014\-]\s*(.+?)\*\*\s*\((CRITICAL|HIGH|MEDIUM|LOW)\)\s*$",
    re.MULTILINE,
)
# A line that opens like an authored id but does not fully parse (missing the
# (SEVERITY) suffix, bad separator, ...). Used for near-miss detection.
# [ \t]* not \s*: \s would let ^ match an earlier blank line and swallow the
# newline, shifting the match start off the header line and breaking the
# start-position comparison against FINDING_RE below.
BAD_ID_HEADER_RE = re.compile(r"^[ \t]*\*\*[CHML]\d+\b.*$", re.MULTILINE)
# The retired synthesized-header shape; flag it so a stale critic gets caught.
OLD_HEADER_RE = re.compile(r"^[ \t]*###\s+(?:CRITICAL|HIGH|MEDIUM|LOW)\b.*$", re.MULTILINE)
# File citation: **Where:** `path:line`  (or "no specific file" for cross-cutting).
FILE_LINE_RE = re.compile(r"^\*\*Where:\*\*\s*`([^`:]+):(\d+)`", re.MULTILINE)
NO_FILE_RE = re.compile(r"^\*\*Where:\*\*\s*no specific file\b", re.MULTILINE)
ANCHOR_RE = re.compile(r"^\*\*Anchor:\*\*\s*`?(.*?)`?\s*$", re.MULTILINE)
SOURCE_CRITIC_RE = re.compile(r"^\*\*Source critic:\*\*\s*(.+?)\s*$", re.MULTILINE)
SOURCE_AXIS_RE = re.compile(r"^\*\*Source axis:\*\*\s*(.+?)\s*$", re.MULTILINE)
VERSION_RE = re.compile(r"^\*\*Critique format version:\*\*\s*(\S+)", re.MULTILINE)
# The self-declared tally line the author must keep in sync with the findings.
SEVERITY_COUNTS_RE = re.compile(
    r"^Severity counts:\s*C(\d+)\s+H(\d+)\s+M(\d+)\s+L(\d+)\s*$", re.MULTILINE
)
# Required per-finding body fields (What/Why/Proposed-fix/Regression-guard/Source).
BODY_FIELD_RES = {
    "What": re.compile(r"^\*\*What:\*\*", re.MULTILINE),
    "Why it matters": re.compile(r"^\*\*Why it matters:\*\*", re.MULTILINE),
    "Proposed fix": re.compile(r"^\*\*Proposed fix:\*\*", re.MULTILINE),
    "Regression-guard": re.compile(r"^\*\*Regression-guard:\*\*", re.MULTILINE),
    "Source critic": re.compile(r"^\*\*Source critic:\*\*", re.MULTILINE),
}


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _find_repo_root() -> Path:
    """env REPO_ROOT -> git rev-parse -> walk up to a .git dir.

    The final fallback is parents[2] of this file: a synced script lives at
    <root>/.claude/scripts/<file>, so climbing two parents lands on the repo
    root even when git is unavailable (bare checkout, tarball).
    """
    env = os.environ.get("REPO_ROOT")
    if env:
        return Path(env).resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        top = out.stdout.strip()
        if top:
            return Path(top).resolve()
    except Exception:
        pass
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".git").exists():
            return parent
    return here.parents[2]


def _check_mid(mid: str) -> str:
    if not MILESTONE_ID_RE.match(mid):
        sys.exit(f"error: refusing unsafe milestone id {mid!r} (path-traversal floor)")
    return mid


def _milestone_dir(mid: str) -> Path:
    return _find_repo_root() / ".claude" / "notes" / "milestones" / _check_mid(mid)


def _register_path(mid: str) -> Path:
    return _milestone_dir(mid) / "findings.json"


def _save_atomic(path: Path, data: dict) -> None:
    # SAME-DIR temp + os.replace: NamedTemporaryFile can land on another
    # filesystem and degrade rename to copy+unlink, defeating atomicity.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _load_register(path: Path) -> dict:
    """Load and STRICTLY validate the register.

    A hand-edited status or severity must never fail the gate OPEN, so every
    consumer loads through this validator: an out-of-vocabulary status/severity
    is a hard error, not a silent pass.
    """
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    findings = data.get("findings")
    if not isinstance(findings, dict):
        sys.exit(f"error: corrupt register {path} (missing 'findings' object)")
    for fid, f in findings.items():
        if f.get("severity") not in SEVERITIES:
            sys.exit(f"error: finding {fid} has invalid severity {f.get('severity')!r}")
        if f.get("status") not in STATUSES:
            sys.exit(f"error: finding {fid} has invalid status {f.get('status')!r}")
    return data


# --- parsing ------------------------------------------------------------------


def _blank_fences(text: str) -> str:
    """Blank fenced code blocks in place (preserving line numbers).

    Example finding headers inside a ``` fence (e.g. in critique-format.md) must
    NOT parse as real findings. Replacing fenced lines with empty strings keeps
    every real finding at its true line number for citation.
    """
    out = []
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def parse_critique(text: str, source: str) -> tuple[list[dict], list[str]]:
    """Parse one critique markdown into (findings, errors).

    Fail-loud: every structural defect appends an error string (with source +
    line) rather than silently dropping the block. `extract --check` and
    `dedupe` both surface these; an uncited finding therefore BLOCKS instead of
    vanishing.
    """
    errors: list[str] = []
    body = _blank_fences(text)

    matches = list(FINDING_RE.finditer(body))
    finding_starts = {m.start() for m in matches}

    # Near-miss detection: id-shaped or retired headers that did not fully parse.
    for m in BAD_ID_HEADER_RE.finditer(body):
        if m.start() not in finding_starts:
            ln = body.count("\n", 0, m.start()) + 1
            errors.append(
                f"{source}:{ln}: malformed authored-id header "
                f"(need `**<id> -- title** (SEVERITY)`): {m.group(0).strip()[:70]}"
            )
    for m in OLD_HEADER_RE.finditer(body):
        ln = body.count("\n", 0, m.start()) + 1
        errors.append(
            f"{source}:{ln}: retired `### <SEVERITY>` header shape - migrate to "
            f"authored ids (critique format v{CRITIQUE_FORMAT_VERSION})"
        )

    findings: list[dict] = []
    seen_ids: dict[str, str] = {}
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        block = body[start:end]
        ln = body.count("\n", 0, start) + 1
        letter, num, title, severity = m.group(1), m.group(2), m.group(3), m.group(4)
        fid = f"{letter}{num}"

        if LETTER_SEVERITY[letter] != severity:
            errors.append(
                f"{source}:{ln}: finding {fid} id-letter '{letter}' disagrees with "
                f"severity {severity} (expected {LETTER_SEVERITY[letter]})"
            )
        if fid in seen_ids:
            errors.append(f"{source}:{ln}: duplicate finding id {fid} "
                          f"(first seen at {seen_ids[fid]})")
        seen_ids[fid] = f"{source}:{ln}"

        for label, rx in BODY_FIELD_RES.items():
            if rx.search(block):
                continue
            # Regression-guard is mandated only for CRITICAL/HIGH (the critique
            # format says "MEDIUM + LOW: optional"). On MEDIUM/LOW its absence is a
            # warning, not a whole-file refusal — this aligns the parser with its
            # own spec and removes a common false rejection + re-dispatch.
            if label == "Regression-guard" and severity in ("MEDIUM", "LOW"):
                print(
                    f"warning: {source}:{ln}: {severity} finding {fid} omits "
                    f"`**{label}:**` (optional at this severity)",
                    file=sys.stderr,
                )
                continue
            errors.append(f"{source}:{ln}: finding {fid} missing required "
                          f"`**{label}:**` field")

        fl = FILE_LINE_RE.search(block)
        cite_path: str | None = None
        cite_line: int | None = None
        if fl:
            cite_path, cite_line = fl.group(1), int(fl.group(2))
        elif not NO_FILE_RE.search(block):
            errors.append(f"{source}:{ln}: finding {fid} has no parseable "
                          f"`**Where:** `file:line`` (or 'no specific file') citation")

        anchor_m = ANCHOR_RE.search(block)
        critic_m = SOURCE_CRITIC_RE.search(block)
        axis_m = SOURCE_AXIS_RE.search(block)
        findings.append(
            {
                "id": fid,
                "severity": severity,
                "title": title.strip(),
                "file": cite_path,
                "line": cite_line,
                "anchor": anchor_m.group(1).strip() if anchor_m else "",
                "source_critic": critic_m.group(1).strip() if critic_m else "",
                "source_axis": axis_m.group(1).strip() if axis_m else "",
                "source_file": source,
            }
        )

    # Self-declared tally: if present it MUST equal the parsed counts (a drifted
    # counts line means the author added/removed a finding without updating it).
    counts = _severity_counts(findings)
    sc = SEVERITY_COUNTS_RE.search(body)
    if sc:
        declared = {
            "critical": int(sc.group(1)),
            "high": int(sc.group(2)),
            "medium": int(sc.group(3)),
            "low": int(sc.group(4)),
        }
        if declared != counts:
            # Non-blocking: the register is built from the PARSED counts, not this
            # self-declared line, so a drifted tally is cosmetic. Warn instead of
            # refusing — the exact-match hard-fail forced the critic to hand-count
            # its own findings and was the top cause of a whole-critique rejection
            # plus an expensive re-dispatch of the opus adversary critic.
            print(
                f"warning: {source}: 'Severity counts:' line {declared} disagrees "
                f"with the parsed tally {counts} (using the parsed tally)",
                file=sys.stderr,
            )
    return findings, errors


def _severity_counts(findings: list[dict]) -> dict:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        counts[f["severity"].lower()] += 1
    return counts


def _parse_files(paths: list[Path]) -> tuple[list[dict], list[str]]:
    all_findings: list[dict] = []
    all_errors: list[str] = []
    for p in paths:
        if not p.exists():
            all_errors.append(f"{p}: file not found")
            continue
        text = p.read_text(encoding="utf-8-sig")
        rel = p.name
        findings, errors = parse_critique(text, rel)
        all_findings.extend(findings)
        all_errors.extend(errors)
    return all_findings, all_errors


# --- subcommands --------------------------------------------------------------


def cmd_extract(mid: str | None, files: list[str], check_only: bool) -> int:
    if check_only:
        paths = [Path(f) for f in files]
        _findings, errors = _parse_files(paths)
        if errors:
            print(f"CRITIQUE LINT FAILED ({len(errors)} problem(s)):", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            return 1
        print(f"critique lint OK ({len(_findings)} finding(s) across {len(paths)} file(s))")
        return 0

    if not mid:
        print("error: extract requires --id <ID> unless --check is given", file=sys.stderr)
        return 2
    _check_mid(mid)
    mdir = _milestone_dir(mid)
    paths = [Path(f) for f in files] or [mdir / "critique" / "dedup.md"]
    findings, errors = _parse_files(paths)
    if errors:
        print(f"REFUSING to materialise register - critique is malformed "
              f"({len(errors)} problem(s)):", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    reg_path = _register_path(mid)
    new_ids = {f["id"] for f in findings}
    new_files = sorted({f["source_file"] for f in findings})

    preserved: dict[str, dict] = {}
    if reg_path.exists():
        old = _load_register(reg_path)
        old_findings = old.get("findings", {})
        dropped = [fid for fid in old_findings if fid not in new_ids]
        if dropped:
            print("REFUSING extract - re-parse would DROP registered finding id(s): "
                  f"{', '.join(sorted(dropped))}", file=sys.stderr)
            print("  (a finding with a recorded disposition disappeared from the "
                  "critique; investigate before re-extracting)", file=sys.stderr)
            return 1
        old_cf = old.get("critique_files", [])
        dropped_cf = [c for c in old_cf if c not in new_files]
        if dropped_cf:
            print("REFUSING extract - critique file(s) previously registered are now "
                  f"absent: {', '.join(dropped_cf)}", file=sys.stderr)
            return 1
        preserved = old_findings

    registry_findings: dict[str, dict] = {}
    for f in findings:
        prev = preserved.get(f["id"])
        entry = {
            "id": f["id"],
            "severity": f["severity"],
            "title": f["title"],
            "file": f["file"],
            "line": f["line"],
            "anchor": f["anchor"],
            "source_critic": f["source_critic"],
            "source_axis": f["source_axis"],
            "source_file": f["source_file"],
            # PRESERVE disposition across re-extract; only structure is re-derived.
            "status": prev["status"] if prev else "open",
            "resolution": prev.get("resolution") if prev else None,
            "history": prev.get("history", []) if prev else [],
        }
        registry_findings[f["id"]] = entry

    data = {
        "milestone_id": mid,
        "critique_format_version": CRITIQUE_FORMAT_VERSION,
        "critique_files": new_files,
        "generated_at": _now(),
        "findings": registry_findings,
    }
    _save_atomic(reg_path, data)
    counts = _severity_counts(findings)
    print(f"{mid}: register written - {len(findings)} finding(s) "
          f"(C{counts['critical']} H{counts['high']} "
          f"M{counts['medium']} L{counts['low']}) -> {reg_path}")
    return 0


def cmd_set(mid: str, ids_arg: str, status: str, resolution: str | None) -> int:
    _check_mid(mid)
    if status not in ("fixed", "deferred", "invalidated"):
        print(f"error: status must be fixed|deferred|invalidated, got {status!r}",
              file=sys.stderr)
        return 2
    reg_path = _register_path(mid)
    if not reg_path.exists():
        print(f"error: no register at {reg_path} - run extract first", file=sys.stderr)
        return 2
    data = _load_register(reg_path)
    findings = data["findings"]
    ids = [i.strip() for i in ids_arg.split(",") if i.strip()]
    if not ids:
        print("error: no finding ids given", file=sys.stderr)
        return 2

    changed = False
    for fid in ids:
        f = findings.get(fid)
        if f is None:
            print(f"error: unknown finding id {fid} (not in register)", file=sys.stderr)
            return 2
        cur = f["status"]
        if cur == status:
            print(f"{fid}: already {status} - no-op")
            continue
        if status not in ALLOWED_TRANSITIONS[cur]:
            allowed = sorted(ALLOWED_TRANSITIONS[cur]) or "none - terminal"
            print(f"error: forbidden transition for {fid}: {cur} -> {status} "
                  f"(allowed from {cur}: {allowed})", file=sys.stderr)
            return 2
        if not resolution or not resolution.strip():
            print(f"error: --resolution is required to set {fid} -> {status}",
                  file=sys.stderr)
            return 2
        f["status"] = status
        f["resolution"] = resolution.strip()
        f.setdefault("history", []).append(
            {"status": status, "at": _now(), "resolution": resolution.strip()}
        )
        changed = True
        print(f"{fid}: {cur} -> {status}")

    if changed:
        data["generated_at"] = _now()
        _save_atomic(reg_path, data)
    return 0


def cmd_gate(mid: str) -> int:
    _check_mid(mid)
    reg_path = _register_path(mid)
    if not reg_path.exists():
        # No register: a legacy/ad-hoc run that never ran extract. No-op OK so
        # the gate never blocks a milestone that predates the register.
        print(f"{mid}: no findings register - gate is a no-op (legacy/ad-hoc)")
        return 0
    data = _load_register(reg_path)
    findings = data["findings"]
    open_blocking = [
        f for f in findings.values() if f["severity"] in BLOCKING and f["status"] == "open"
    ]
    open_minor = [
        f for f in findings.values()
        if f["severity"] not in BLOCKING and f["status"] == "open"
    ]
    if open_blocking:
        print(f"GATE REFUSED - {len(open_blocking)} open CRITICAL/HIGH finding(s) "
              "must be fixed or invalidated before complete:", file=sys.stderr)
        for f in sorted(open_blocking, key=lambda x: SEVERITY_ORDER[x["severity"]]):
            loc = f"{f['file']}:{f['line']}" if f.get("file") else "(no file)"
            print(f"  - {f['id']} [{f['severity']}] {f['title']} @ {loc}", file=sys.stderr)
        return 3
    if open_minor:
        # MEDIUM/LOW are deferrable by default: warn, do not block.
        print(f"{mid}: gate OK - {len(open_minor)} open MEDIUM/LOW finding(s) "
              "remain (deferrable; not blocking).")
    else:
        print(f"{mid}: gate OK - no open findings.")
    return 0


_FIELD_ALIASES = {
    "open": "open",
    "fixed": "fixed",
    "fixed_findings": "fixed",
    "deferred": "deferred",
    "deferred_findings": "deferred",
    "invalidated": "invalidated",
    "invalidated_findings": "invalidated",
}


def cmd_summary(mid: str | None, counts_for: str | None, field: str | None) -> int:
    if counts_for:
        # Pure parse of one markdown file -> C/H/M/L tally. Replaces the old
        # `grep -c '^### CRITICAL'` counting; no register needed.
        findings, errors = _parse_files([Path(counts_for)])
        if errors:
            print(f"error: cannot count - {counts_for} is malformed:", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            return 1
        print(json.dumps(_severity_counts(findings)))
        return 0

    if not mid:
        print("error: summary requires <ID> unless --counts-for is given", file=sys.stderr)
        return 2
    _check_mid(mid)
    reg_path = _register_path(mid)
    if not reg_path.exists():
        print(f"error: no register at {reg_path}", file=sys.stderr)
        return 2
    data = _load_register(reg_path)
    findings = list(data["findings"].values())
    buckets: dict[str, list[str]] = {"open": [], "fixed": [], "deferred": [], "invalidated": []}
    for f in findings:
        buckets[f["status"]].append(f["id"])
    for v in buckets.values():
        v.sort()

    if field:
        key = _FIELD_ALIASES.get(field)
        if not key:
            print(f"error: unknown --field {field!r} (valid: "
                  f"{', '.join(sorted(set(_FIELD_ALIASES)))})", file=sys.stderr)
            return 2
        print(json.dumps(buckets[key]))
        return 0

    per_file: dict[str, dict] = defaultdict(lambda: {"critical": 0, "high": 0,
                                                     "medium": 0, "low": 0})
    for f in findings:
        if f.get("file"):
            per_file[f["file"]][f["severity"].lower()] += 1
    out = {
        "milestone_id": data.get("milestone_id", mid),
        "finding_counts": _severity_counts(findings),
        "per_file": dict(per_file),
        "open": buckets["open"],
        "fixed": buckets["fixed"],
        "deferred": buckets["deferred"],
        "invalidated": buckets["invalidated"],
    }
    print(json.dumps(out, indent=2))
    return 0


def _cluster(findings: list[dict], window: int = 5) -> list[list[dict]]:
    by_file: dict[str, list[dict]] = defaultdict(list)
    for f in findings:
        if f.get("file") and f.get("line") is not None:
            by_file[f["file"]].append(f)
    clusters: list[list[dict]] = []
    for file_findings in by_file.values():
        file_findings.sort(key=lambda f: f["line"])
        cur: list[dict] = []
        for f in file_findings:
            if cur and f["line"] - cur[-1]["line"] <= window:
                cur.append(f)
            else:
                if len(cur) > 1:
                    clusters.append(cur)
                cur = [f]
        if len(cur) > 1:
            clusters.append(cur)
    return clusters


def cmd_dedupe(file_arg: str) -> int:
    """Cluster cross-critic agreement within a 5-line window of the same file.

    Runs through the SAME fail-loud parser: a malformed/uncited finding BLOCKS
    (exit 1) instead of being silently skipped, closing the standalone script's
    silent-`continue` hole.
    """
    path = Path(file_arg)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8-sig")
    if "Cross-critic agreement" in text:
        print(f"{path}: already deduped (skipping)")
        return 0
    findings, errors = parse_critique(text, path.name)
    if errors:
        print(f"REFUSING dedupe - {path} is malformed ({len(errors)} problem(s)):",
              file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    clusters = _cluster(findings)
    if not clusters:
        print(f"{path}: {len(findings)} finding(s); no duplicates")
        return 0

    callouts = ["", "## Cross-critic agreement", ""]
    callouts.append(
        "The following findings cluster within 5 lines of each other in the same "
        "file. Multiple critics flagged the same area - these are the strongest "
        "signals to fix first.\n"
    )
    for cl in clusters:
        ids = ", ".join(f["id"] for f in cl)
        # Label the cluster with its MOST-severe member. min() over SEVERITY_ORDER
        # (CRITICAL=0) picks CRITICAL - the standalone script used max(), which
        # picked the LEAST-severe member and mislabelled e.g. a C+L cluster LOW.
        sev = min(cl, key=lambda f: SEVERITY_ORDER[f["severity"]])["severity"]
        loc = f"{cl[0]['file']}:{cl[0]['line']}-{cl[-1]['line']}"
        titles = "; ".join(f["title"] for f in cl)
        callouts.append(f"- **{ids}** at `{loc}` ({sev}): {titles}")

    marker = "## Recommended rectification order"
    if marker in text:
        rewritten = text.replace(marker, "\n".join(callouts) + "\n\n" + marker, 1)
    else:
        rewritten = text.rstrip() + "\n\n" + "\n".join(callouts) + "\n"
    path.write_text(rewritten, encoding="utf-8")
    covered = sum(len(c) for c in clusters)
    print(f"{path}: deduped - {len(clusters)} cluster(s) covering {covered} finding(s)")
    return 0


# --- merge (multi-critic) -----------------------------------------------------
#
# Phase 3 dispatches N critics in parallel and each one authors its ids from 1
# within its own file (critique-format v1.0). Concatenating them therefore
# produces duplicate ids, two `Severity counts:` lines, and two
# `## Recommended rectification order` headings - all three of which the parser
# and `dedupe` reject. `merge` is the sanctioned combiner.

EMDASH = "—"  # never a literal: this file must survive a cp1252 re-save.

_SECTION_RE = re.compile(r"^##\s+(.*?)\s*$")
# One finding header matched per-LINE (FINDING_RE is the whole-document form) so
# the authored id can be rewritten in place, leaving title + severity untouched.
FINDING_LINE_RE = re.compile(
    r"^(\*\*)([CHML])(\d+)(\s*[—\-]\s*.+?\*\*\s*\((?:CRITICAL|HIGH|MEDIUM|LOW)\)\s*)$"
)
CRITIC_RE = re.compile(r"^\*\*Critics?:\*\*\s*(.+?)\s*$", re.MULTILINE)
COMMIT_RANGE_RE = re.compile(r"^\*\*Commit range:\*\*\s*(.+?)\s*$", re.MULTILINE)
DIFF_STATS_RE = re.compile(r"^\*\*Diff stats:\*\*\s*(.+?)\s*$", re.MULTILINE)
# Longest-first: a naive scan for "SHIP" would match inside "SHIP-WITH-FIXES".
VERDICT_TOKENS = ("DO-NOT-SHIP", "SHIP-WITH-FIXES", "SHIP")
VERDICT_RANK = {"DO-NOT-SHIP": 0, "SHIP-WITH-FIXES": 1, "SHIP": 2}
_ORDER_HEADING = "Recommended rectification order"
_PHASE4_HEADING = "Phase 4 status (filled by orchestrator at rectify time)"
# Sections merge understands. Anything else is carried verbatim rather than
# dropped - silently losing a critic's prose is worse than an untidy output.
_KNOWN_SECTIONS = {
    "Verdict",
    "Executive summary",
    "Findings",
    "What was done well",
    _ORDER_HEADING,
}
_ID_LIST_RE = re.compile(r"\b([CHML])(\d+)\b")


def _id_sort_key(fid: str) -> tuple[int, int]:
    return (SEVERITY_ORDER[LETTER_SEVERITY[fid[0]]], int(fid[1:]))


def _split_sections(text: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """Split into (preamble lines, [(heading, body lines), ...]).

    `## ` inside a fenced block is body text, not a heading - the same fence
    discipline `_blank_fences` applies to finding headers.
    """
    preamble: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    head: str | None = None
    body: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence:
            m = _SECTION_RE.match(line)
            if m:
                if head is not None:
                    sections.append((head, body))
                head, body = m.group(1), []
                continue
        (body if head is not None else preamble).append(line)
    if head is not None:
        sections.append((head, body))
    return preamble, sections


def _trim(lines: list[str]) -> list[str]:
    out = [ln for ln in lines if not SEVERITY_COUNTS_RE.match(ln)]
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


def _rewrite_ids(text: str, id_map: dict[str, str]) -> str:
    """Rewrite authored ids in finding HEADERS only (bodies stay verbatim)."""
    out: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        m = None if in_fence else FINDING_LINE_RE.match(line)
        if m:
            old = f"{m.group(2)}{m.group(3)}"
            out.append(f"{m.group(1)}{id_map.get(old, old)}{m.group(4)}")
        else:
            out.append(line)
    return "\n".join(out)


def _finding_blocks(lines: list[str]) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """Split a `## Findings` body into (prose before finding 1, [(id, block)])."""
    starts: list[tuple[int, str]] = []
    in_fence = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = FINDING_LINE_RE.match(line)
        if m:
            starts.append((i, f"{m.group(2)}{m.group(3)}"))
    if not starts:
        return _trim(lines), []
    blocks = []
    for j, (i, fid) in enumerate(starts):
        end = starts[j + 1][0] if j + 1 < len(starts) else len(lines)
        blocks.append((fid, _trim(lines[i:end])))
    return _trim(lines[: starts[0][0]]), blocks


def _mid_from_title(preamble: list[str]) -> str | None:
    for line in preamble:
        if line.startswith("# "):
            parts = re.split(r"\s[—\-]\s", line[2:].strip())
            for part in parts[1:]:
                cand = part.strip()
                if MILESTONE_ID_RE.match(cand):
                    return cand
    return None


def _mid_from_path(out: Path) -> str | None:
    parts = out.resolve().parts
    if "milestones" not in parts:
        return None
    i = len(parts) - 1 - parts[::-1].index("milestones")
    if i + 1 < len(parts) and MILESTONE_ID_RE.match(parts[i + 1]):
        return parts[i + 1]
    return None


def _rebind_problems(mid: str, merged_titles: dict[str, str]) -> list[str]:
    """Ids a re-merge would silently repoint at a DIFFERENT finding.

    Authored ids exist so a Phase-4 disposition stays attached across a
    re-extract. Merging reintroduces the renumbering hazard ACROSS critics: if a
    critic file gains or loses a finding and merge re-runs, every later id in
    that severity shifts by one. `extract` does not catch this - it refuses only
    a DROPPED id, and a shift-by-one drops nothing. So the check lives here.
    """
    reg_path = _register_path(mid)
    if not reg_path.exists():
        return []
    findings = _load_register(reg_path).get("findings", {})
    problems = []
    for fid, f in sorted(findings.items(), key=lambda kv: _id_sort_key(kv[0])):
        if f.get("status") == "open":
            continue  # nothing recorded yet - re-deriving this id is harmless.
        new_title = merged_titles.get(fid)
        old_title = (f.get("title") or "").strip()
        if new_title is None:
            problems.append(
                f"{fid} [{f['severity']}/{f['status']}] {old_title!r} is absent from "
                f"the merged critique"
            )
        elif new_title.strip() != old_title:
            problems.append(
                f"{fid} [{f['severity']}/{f['status']}] would move from {old_title!r} "
                f"to {new_title.strip()!r}"
            )
    return problems


def cmd_merge(  # noqa: C901 -- linear assemble; splitting would hide the doc shape
    out_arg: str, in_args: list[str], mid_arg: str | None, force: bool
) -> int:
    out = Path(out_arg)
    ins = [Path(p) for p in in_args]
    if not ins:
        print("error: merge needs at least one input critique", file=sys.stderr)
        return 2
    resolved_out = out.resolve()
    for p in ins:
        if not p.exists():
            print(f"error: input not found: {p}", file=sys.stderr)
            return 2
        if p.resolve() == resolved_out:
            print(f"error: refusing to merge {p} onto itself (out == in)", file=sys.stderr)
            return 2

    # 1. Parse every input through the SAME fail-loud parser dedupe/extract use,
    #    so a malformed critic file blocks here rather than three steps later.
    infos: list[dict] = []
    all_errors: list[str] = []
    for p in ins:
        text = p.read_text(encoding="utf-8-sig")
        findings, errors = parse_critique(text, p.name)
        all_errors.extend(errors)
        preamble, sections = _split_sections(text)
        critic_m = CRITIC_RE.search("\n".join(preamble))
        if critic_m:
            critic = critic_m.group(1).strip()
        else:
            names = [f["source_critic"] for f in findings if f["source_critic"]]
            critic = max(set(names), key=names.count) if names else p.stem
        infos.append(
            {
                "path": p,
                "text": text,
                "preamble": preamble,
                "sections": sections,
                "critic": critic,
                "findings": findings,
            }
        )
    if all_errors:
        print(f"REFUSING merge - input critique(s) malformed ({len(all_errors)} "
              "problem(s)):", file=sys.stderr)
        for e in all_errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    # 2. Milestone id: title -> out path -> --id. Needed for the rebind guard.
    mid = mid_arg or _mid_from_title(infos[0]["preamble"]) or _mid_from_path(out)
    if mid:
        _check_mid(mid)

    # 3. Renumber. Deterministic function of (argv order, in-file order): file 1
    #    keeps its ids when it is conformant (numbered from 1 in document order),
    #    every later file continues the sequence per severity letter.
    counters = {"C": 0, "H": 0, "M": 0, "L": 0}
    merged_titles: dict[str, str] = {}
    for inf in infos:
        id_map: dict[str, str] = {}
        for f in inf["findings"]:
            letter = f["id"][0]
            counters[letter] += 1
            new_id = f"{letter}{counters[letter]}"
            id_map[f["id"]] = new_id
            merged_titles[new_id] = f["title"]
        inf["id_map"] = id_map

    # 4. Rebind guard, BEFORE writing anything.
    if mid:
        problems = _rebind_problems(mid, merged_titles)
        if problems:
            head = "WARNING (--force)" if force else "REFUSING merge"
            stream = sys.stderr
            print(f"{head} - re-merging would repoint {len(problems)} finding id(s) "
                  "that already carry a Phase-4 disposition:", file=stream)
            for pb in problems:
                print(f"  - {pb}", file=stream)
            if not force:
                print("  (a critic file changed after `extract` ran. Re-merging shifts "
                      "every later id in that severity, and the recorded disposition "
                      "would follow the ID, not the finding. Treat this as a NEW "
                      "critique round - or pass --force if you have verified the "
                      "register is disposable.)", file=stream)
                return 1

    # 5. Single input is a verbatim pass-through: nothing to renumber, and byte
    #    equality keeps the old `cp adversary.md dedup.md` behaviour exactly.
    if len(infos) == 1:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(infos[0]["text"], encoding="utf-8")
        print(f"{out}: single critique copied verbatim "
              f"({len(infos[0]['findings'])} finding(s), ids unchanged)")
        return 0

    # 6. Assemble. Every section is read from the RENUMBERED copy so no stale id
    #    can leak into the merged file through a section merge copies verbatim.
    for inf in infos:
        inf["rewritten"] = _split_sections(_rewrite_ids(inf["text"], inf["id_map"]))[1]

    def section(inf: dict, name: str) -> list[str] | None:
        for head, body in inf["rewritten"]:
            if head == name or head.startswith(name):
                return body
        return None

    # merge rewrites finding HEADERS only (plus the rectification-order list,
    # which it rebuilds from the id map below). A critic that cross-references
    # its own ids in free prose - "as in M2" - therefore keeps the pre-merge
    # token, which now names somebody else's finding. Cheap to detect, expensive
    # to chase later: warn rather than silently mislead Phase 4.
    for inf in infos:
        moved = {o for o, n in inf["id_map"].items() if o != n}
        if not moved:
            continue
        prose: list[str] = []
        for head, body in inf["rewritten"]:
            if head.startswith(_ORDER_HEADING) or head.startswith(_PHASE4_HEADING):
                continue  # id lists merge rebuilds itself - not stale references.
            # The tally line is C/H/M/L digits too - merge regenerates it, so it
            # is never a stale cross-reference.
            prose += [
                ln for ln in body
                if not FINDING_LINE_RE.match(ln) and not SEVERITY_COUNTS_RE.match(ln)
            ]
        stale = sorted(
            {
                f"{m.group(1)}{m.group(2)}"
                for m in _ID_LIST_RE.finditer("\n".join(prose))
                if f"{m.group(1)}{m.group(2)}" in moved
            },
            key=_id_sort_key,
        )
        if stale:
            print(f"warning: {inf['path'].name} refers to {', '.join(stale)} in prose; "
                  "merge rewrites finding headers only, so those references now name "
                  "a DIFFERENT finding - check them by hand", file=sys.stderr)

    critics = [inf["critic"] for inf in infos]
    first_pre = "\n".join(infos[0]["preamble"])
    commit_range = COMMIT_RANGE_RE.search(first_pre)
    diff_stats = DIFF_STATS_RE.search(first_pre)
    for inf in infos[1:]:
        other = COMMIT_RANGE_RE.search("\n".join(inf["preamble"]))
        if commit_range and other and other.group(1) != commit_range.group(1):
            print(f"warning: {inf['path'].name} critiqued a different commit range "
                  f"({other.group(1)}) than {infos[0]['path'].name} "
                  f"({commit_range.group(1)})", file=sys.stderr)

    L: list[str] = [f"# Critique (merged) {EMDASH} {mid or 'unknown-milestone'}", ""]
    L.append(f"**Critics:** {', '.join(critics)}")
    if commit_range:
        L.append(f"**Commit range:** {commit_range.group(1)}")
    if diff_stats:
        L.append(f"**Diff stats:** {diff_stats.group(1)}")
    L += [f"**Critique format version:** {CRITIQUE_FORMAT_VERSION}", ""]
    L += [
        "> **Merge note.** Each critic authored its ids from 1 within its own file, so",
        "> they collided across files. `findings.py merge` renumbered them into one",
        "> gapless per-severity sequence in critic dispatch order; bodies are verbatim.",
        "> **Phase 4 dispositions attach to the MERGED ids below**, not to the ids in",
        "> the per-critic files. Re-running merge after a critic file changes will shift",
        "> these ids - see milestone-pipeline-critique-format.md.",
        ">",
    ]
    for inf in infos:
        moved = {o: n for o, n in inf["id_map"].items() if o != n}
        if moved:
            pairs = ", ".join(
                f"{o}->{n}" for o, n in sorted(moved.items(), key=lambda kv: _id_sort_key(kv[0]))
            )
            L.append(f"> - `{inf['critic']}` ({inf['path'].name}): {pairs}")
        else:
            L.append(f"> - `{inf['critic']}` ({inf['path'].name}): ids unchanged")
    L.append("")

    verdicts = []
    for inf in infos:
        body = section(inf, "Verdict") or []
        found = next((t for ln in body for t in VERDICT_TOKENS if t in ln), None)
        inf["verdict"] = found
        verdicts.append(found)
    known = [v for v in verdicts if v]
    merged_verdict = min(known, key=lambda v: VERDICT_RANK[v]) if known else "not stated"
    L += ["## Verdict", ""]
    L.append(f"**{merged_verdict}** {EMDASH} the most severe of the per-critic verdicts below.")
    L.append("")
    for inf in infos:
        L.append(f"### {inf['critic']} {EMDASH} {inf['verdict'] or 'not stated'}")
        L.append("")
        L += _trim(section(inf, "Verdict") or ["(no verdict section)"])
        L.append("")

    for inf in infos:
        body = section(inf, "Executive summary")
        if body is None:
            continue
        L += [f"## Executive summary {EMDASH} {inf['critic']}", ""]
        L += _trim(body)
        L.append("")

    L += ["## Findings", ""]
    blocks: list[tuple[str, list[str]]] = []
    for inf in infos:
        pre, bl = _finding_blocks(section(inf, "Findings") or [])
        blocks.extend(bl)
        if pre:
            L.append(f"> Note carried from `{inf['critic']}`'s Findings section:")
            L += [f"> {ln}" if ln.strip() else ">" for ln in pre]
            L.append("")
    for _fid, block in sorted(blocks, key=lambda b: _id_sort_key(b[0])):
        L += block
        L.append("")

    L += ["## What was done well", ""]
    for inf in infos:
        body = section(inf, "What was done well")
        L += [f"### From {inf['critic']}", ""]
        L += _trim(body) if body else ["(section absent)"]
        L.append("")

    counts = {"C": 0, "H": 0, "M": 0, "L": 0}
    for fid in merged_titles:
        counts[fid[0]] += 1
    L += [f"Severity counts: C{counts['C']} H{counts['H']} M{counts['M']} L{counts['L']}", ""]

    # Preserve each critic's own intra-severity priority, then stable-sort by
    # severity so CRITICALs lead regardless of which critic raised them. The ids
    # here are read from the ORIGINAL section and mapped: `_rewrite_ids` touches
    # finding headers only, so this list is still in pre-merge numbering.
    order: list[str] = []
    for inf in infos:
        body = next(
            (b for h, b in inf["sections"] if h.startswith(_ORDER_HEADING)), []
        )
        for m in _ID_LIST_RE.finditer("\n".join(body)):
            fid = inf["id_map"].get(f"{m.group(1)}{m.group(2)}")
            if fid and fid not in order:
                order.append(fid)
    for fid in sorted(merged_titles, key=_id_sort_key):
        if fid not in order:
            order.append(fid)
    order.sort(key=lambda fid: SEVERITY_ORDER[LETTER_SEVERITY[fid[0]]])
    L += [f"## {_ORDER_HEADING}", "", ", ".join(order) if order else "(no findings)", ""]

    L += [
        f"## {_PHASE4_HEADING}",
        "",
        "- Fixed:",
        "- Deferred:",
        "- Invalidated:",
        "- Regression tests added:",
        "",
    ]

    for inf in infos:
        for head, body in inf["rewritten"]:
            if head in _KNOWN_SECTIONS or head.startswith(_PHASE4_HEADING):
                continue
            if head.startswith("Cross-critic agreement"):
                print(f"warning: {inf['path'].name} was already deduped; dropping its "
                      "'Cross-critic agreement' section (dedupe regenerates it)",
                      file=sys.stderr)
                continue
            trimmed = _trim(body)
            if not trimmed:
                continue
            L += [f"## Carried from {inf['critic']} {EMDASH} {head}", ""]
            L += trimmed
            L.append("")

    merged_text = "\n".join(L).rstrip() + "\n"

    # 7. Self-verify: the merged file must parse clean through THIS parser, or it
    #    is not written at all. A merge that emits a file dedupe would refuse is
    #    the exact bug this subcommand exists to prevent.
    check_findings, check_errors = parse_critique(merged_text, out.name)
    if check_errors:
        print(f"REFUSING merge - the MERGED output does not parse "
              f"({len(check_errors)} problem(s)); nothing was written:", file=sys.stderr)
        for e in check_errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    expected = sum(len(inf["findings"]) for inf in infos)
    if len(check_findings) != expected:
        print(f"REFUSING merge - merged output holds {len(check_findings)} finding(s) "
              f"but the inputs held {expected}; nothing was written", file=sys.stderr)
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(merged_text, encoding="utf-8")
    print(f"{out}: merged {len(infos)} critique(s) - {len(check_findings)} finding(s) "
          f"(C{counts['C']} H{counts['H']} M{counts['M']} L{counts['L']}), "
          f"verdict {merged_verdict}")
    for inf in infos:
        moved = {o: n for o, n in inf["id_map"].items() if o != n}
        if moved:
            pairs = ", ".join(
                f"{o}->{n}" for o, n in sorted(moved.items(), key=lambda kv: _id_sort_key(kv[0]))
            )
            print(f"  renumbered {inf['critic']}: {pairs}")
    return 0


# --- self-test ----------------------------------------------------------------

VALID_CRITIQUE = """# Critique - demo-m1 - milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** aaaaaaa..bbbbbbb
**Diff stats:** 3 files, 120 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

## Findings

**C1 - External write in the diff** (CRITICAL)

**Where:** `src/deploy.py:42`
**Anchor:** `subprocess.run(["git", "push"])`
**What:** The diff pushes to a remote unconditionally.
**Why it matters:** Crosses the external-write boundary without authorization.
**Proposed fix:** Gate the push behind the Phase-4 authorization prompt.
**Regression-guard:** tests/test_deploy.py::test_no_autopush
**Source critic:** milestone-adversary-critic
**Source axis:** external-write boundary

**H1 - Acceptance criterion 2 has no test** (HIGH)

**Where:** `src/store.py:88`
**Anchor:** `def reopen(self, path):`
**What:** The no-rebuild criterion is implemented but unasserted.
**Why it matters:** A refactor can silently regress it.
**Proposed fix:** Add a reopen-is-norebuild test.
**Regression-guard:** tests/test_store.py::test_reopen
**Source critic:** milestone-adversary-critic
**Source axis:** acceptance coverage

**M1 - Docstring drift** (MEDIUM)

**Where:** `src/store.py:90`
**Anchor:** `\"\"\"Reopen the store.\"\"\"`
**What:** Docstring says rebuild; code no longer rebuilds.
**Why it matters:** Misleads maintainers.
**Proposed fix:** Update the docstring.
**Regression-guard:** optional
**Source critic:** milestone-adversary-critic
**Source axis:** doc drift

Severity counts: C1 H1 M1 L0

## Recommended rectification order

C1, H1, M1
"""


# A SECOND critic's file for the merge fixtures. Deliberately re-uses M1/L1:
# every critic numbers from 1 within its own file, so id collision across
# critics is the NORMAL case, not a critic error.
OVERLAY_CRITIQUE = """# Critique - demo-m1 - milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** aaaaaaa..bbbbbbb
**Diff stats:** 3 files, 120 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES

## Executive summary

- [MEDIUM] The overlay axis found one drift the generic critic does not cover.

## Findings

**M1 - Overlay drift** (MEDIUM)

**Where:** `src/store.py:91`
**Anchor:** `return Index(path)`
**What:** The overlay axis flags a stale comment.
**Why it matters:** Misleads the next reader of this module.
**Proposed fix:** Rewrite the comment.
**Regression-guard:** optional
**Source critic:** milestone-arxmcp-critic
**Source axis:** doc drift

**L1 - Overlay nit** (LOW)

**Where:** `src/store.py:120`
**Anchor:** `def close(self):`
**What:** Naming nit.
**Why it matters:** Minor readability cost.
**Proposed fix:** Rename.
**Regression-guard:** optional
**Source critic:** milestone-arxmcp-critic

## What was done well

- The overlay verified the cache pins moved together.

Severity counts: C0 H0 M1 L1

## Recommended rectification order

M1, L1
"""


def _self_test() -> int:  # noqa: C901 -- linear fixture walk, readability over splitting
    import tempfile

    failures = []

    def check(cond: bool, msg: str) -> None:
        if not cond:
            failures.append(msg)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        os.environ["REPO_ROOT"] = str(root)
        mid = "demo-m1"
        mdir = root / ".claude" / "notes" / "milestones" / mid / "critique"
        mdir.mkdir(parents=True)
        dedup = mdir / "dedup.md"
        dedup.write_text(VALID_CRITIQUE, encoding="utf-8")

        # 1. Happy-path parse.
        findings, errors = parse_critique(VALID_CRITIQUE, "dedup.md")
        check(not errors, f"valid critique produced errors: {errors}")
        check(len(findings) == 3, f"expected 3 findings, got {len(findings)}")

        # 2. --check on the valid file passes.
        check(cmd_extract(None, [str(dedup)], check_only=True) == 0, "check on valid failed")

        # 3. Malformed fixtures each raise >=1 error.
        malformed = {
            "old-header": VALID_CRITIQUE.replace(
                "**C1 - External write in the diff** (CRITICAL)",
                "### CRITICAL - External write in the diff",
            ),
            "no-severity-suffix": VALID_CRITIQUE.replace(
                "**C1 - External write in the diff** (CRITICAL)",
                "**C1 - External write in the diff**",
            ),
            "id-severity-mismatch": VALID_CRITIQUE.replace(
                "**H1 - Acceptance criterion 2 has no test** (HIGH)",
                "**C1 - Acceptance criterion 2 has no test** (HIGH)",
            ),
            "missing-what": VALID_CRITIQUE.replace(
                "**What:** The diff pushes to a remote unconditionally.\n", ""
            ),
            "missing-where": VALID_CRITIQUE.replace(
                "**Where:** `src/deploy.py:42`\n", ""
            ),
            "missing-regguard-critical": VALID_CRITIQUE.replace(
                "**Regression-guard:** tests/test_deploy.py::test_no_autopush\n", ""
            ),
        }
        for name, txt in malformed.items():
            _f, errs = parse_critique(txt, "x.md")
            check(bool(errs), f"malformed fixture {name!r} parsed clean (should error)")

        # 3b. Recoverable nits are NON-BLOCKING warnings, not refusals: a drifted
        #     'Severity counts:' line (register uses the parsed tally) and a
        #     MEDIUM/LOW finding omitting the CRITICAL/HIGH-only Regression-guard.
        #     Each must parse WITHOUT errors.
        recoverable = {
            "drifted-counts": VALID_CRITIQUE.replace(
                "Severity counts: C1 H1 M1 L0", "Severity counts: C0 H1 M1 L0"
            ),
            "medium-omits-regguard": VALID_CRITIQUE.replace(
                "**Regression-guard:** optional\n", ""
            ),
        }
        for name, txt in recoverable.items():
            _f, errs = parse_critique(txt, "x.md")
            check(not errs, f"recoverable nit {name!r} should warn, not error: {errs}")

        # 4. Fenced example headers must NOT parse as findings.
        fenced = "# doc\n\n```markdown\n**C1 - sample** (CRITICAL)\n```\n"
        ff, fe = parse_critique(fenced, "doc.md")
        check(not ff and not fe, f"fenced header leaked: findings={ff} errors={fe}")

        # 4b. An em-dash separator (what real critics emit) parses like a hyphen.
        em = chr(0x2014)
        em_hdr = VALID_CRITIQUE.replace(
            "**C1 - External write in the diff** (CRITICAL)",
            f"**C1 {em} External write in the diff** (CRITICAL)",
        )
        ef, ee = parse_critique(em_hdr, "em.md")
        check(not ee and len(ef) == 3, f"em-dash header failed to parse: {ee}")

        # 5. extract materialises a register with 3 findings, all open.
        check(cmd_extract(mid, [str(dedup)], check_only=False) == 0, "extract failed")
        reg = _load_register(_register_path(mid))
        check(len(reg["findings"]) == 3, "register did not hold 3 findings")
        check(all(f["status"] == "open" for f in reg["findings"].values()),
              "fresh findings not all open")

        # 6. Gate refuses (exit 3) while C1/H1 are open.
        check(cmd_gate(mid) == 3, "gate did not refuse with open CRITICAL/HIGH")

        # 7. set requires a resolution and honours the state machine.
        check(cmd_set(mid, "C1", "fixed", None) == 2, "set allowed empty resolution")
        check(cmd_set(mid, "C1", "fixed", "gated the push") == 0, "set C1 fixed failed")
        check(cmd_set(mid, "H1", "invalidated", "anchor-not-found") == 0,
              "set H1 invalidated failed")
        # invalidated is terminal -> cannot move to fixed.
        check(cmd_set(mid, "H1", "fixed", "nope") == 2, "terminal transition allowed")
        # same-status is an idempotent no-op (exit 0, no resolution needed).
        check(cmd_set(mid, "C1", "fixed", None) == 0, "same-status no-op failed")

        # 8. Gate now passes (only M1 open, which is deferrable).
        check(cmd_gate(mid) == 0, "gate did not pass after C/H resolved")

        # 9. Extract refuses to DROP a registered id.
        dedup.write_text(
            VALID_CRITIQUE.replace(
                "**M1 - Docstring drift** (MEDIUM)", "**M2 - Docstring drift** (MEDIUM)"
            ).replace("Severity counts: C1 H1 M1 L0", "Severity counts: C1 H1 M1 L0"),
            encoding="utf-8",
        )
        check(cmd_extract(mid, [str(dedup)], check_only=False) == 1,
              "extract did not refuse a dropped id (M1)")
        dedup.write_text(VALID_CRITIQUE, encoding="utf-8")  # restore

        # 10. dedupe clusters C1+H1 (deploy.py:42 vs store.py:88 differ; craft a
        #     same-file pair) and labels with the MOST-severe member.
        clus_src = (
            "# Critique - demo - c\n\n**Critique format version:** 1.0\n\n"
            "**C1 - a** (CRITICAL)\n\n**Where:** `f.py:10`\n**Anchor:** `x`\n"
            "**What:** a.\n**Why it matters:** a.\n**Proposed fix:** a.\n"
            "**Regression-guard:** t\n**Source critic:** milestone-adversary-critic\n\n"
            "**L1 - b** (LOW)\n\n**Where:** `f.py:12`\n**Anchor:** `y`\n"
            "**What:** b.\n**Why it matters:** b.\n**Proposed fix:** b.\n"
            "**Regression-guard:** t\n**Source critic:** milestone-oss-scout\n\n"
            "Severity counts: C1 H0 M0 L1\n\n## Recommended rectification order\n\nC1, L1\n"
        )
        clus_path = root / "clus.md"
        clus_path.write_text(clus_src, encoding="utf-8")
        check(cmd_dedupe(str(clus_path)) == 0, "dedupe of clustered file failed")
        out = clus_path.read_text(encoding="utf-8")
        check("Cross-critic agreement" in out, "dedupe added no agreement section")
        check("(CRITICAL)" in out.split("Cross-critic agreement", 1)[1],
              "dedupe mislabelled cluster severity (should be CRITICAL, not LOW)")

        # 11. --counts-for parses a markdown file into a tally.
        check(cmd_summary(None, str(dedup), None) == 0, "counts-for failed")

        # 12. merge: two critics that BOTH numbered from 1 produce a clean file.
        #     Naive `cat` here yields duplicate M1 and two Severity-counts lines,
        #     which is the failure this subcommand exists to prevent.
        adv = mdir / "adversary.md"
        ovl = mdir / "overlay.md"
        adv.write_text(VALID_CRITIQUE, encoding="utf-8")
        ovl.write_text(OVERLAY_CRITIQUE, encoding="utf-8")
        merged = mdir / "merged.md"
        check(cmd_merge(str(merged), [str(adv), str(ovl)], None, False) == 0, "merge failed")
        mtext = merged.read_text(encoding="utf-8")
        mf, me = parse_critique(mtext, "merged.md")
        check(not me, f"merged output does not parse: {me}")
        check(len(mf) == 5, f"merged output has {len(mf)} findings, expected 5")
        check([f["id"] for f in mf] == ["C1", "H1", "M1", "M2", "L1"],
              f"merged ids wrong: {[f['id'] for f in mf]}")
        check({f["id"]: f["title"] for f in mf}["M2"] == "Overlay drift",
              "overlay M1 was not renumbered to M2")
        check(len(SEVERITY_COUNTS_RE.findall(mtext)) == 1,
              "merged output does not carry EXACTLY ONE 'Severity counts:' line")
        check(mtext.count(f"## {_ORDER_HEADING}") == 1,
              "merged output does not carry EXACTLY ONE rectification-order heading")
        check("Severity counts: C1 H1 M2 L1" in mtext, "merged tally is not the true total")
        # The rectification order must be REMAPPED, not copied: the overlay's own
        # list says "M1, L1" and M1 there is this file's M2.
        order_line = mtext.split(f"## {_ORDER_HEADING}", 1)[1].strip().split("\n")[0]
        check(order_line == "C1, H1, M1, M2, L1",
              f"merged rectification order not remapped/severity-sorted: {order_line!r}")
        check("M1->M2" in mtext, "merge note does not record the renumbering map")

        # 12b. Deterministic: same inputs in the same order -> byte-identical file.
        again = mdir / "merged2.md"
        check(cmd_merge(str(again), [str(adv), str(ovl)], None, False) == 0, "re-merge failed")
        check(again.read_text(encoding="utf-8") == mtext, "merge is not deterministic")

        # 12c. The merged file survives the rest of the phase: dedupe then extract.
        check(cmd_dedupe(str(merged)) == 0, "dedupe refused the merged file")
        check(cmd_extract(None, [str(merged)], check_only=True) == 0,
              "extract --check refused the merged file")

        # 12d. Single input is a verbatim pass-through (old `cat` behaviour).
        solo = mdir / "solo.md"
        check(cmd_merge(str(solo), [str(adv)], None, False) == 0, "single-input merge failed")
        check(solo.read_text(encoding="utf-8") == VALID_CRITIQUE, "single merge was not verbatim")

        # 12e. Refusals: malformed input, and out == in.
        bad = mdir / "bad.md"
        bad.write_text(VALID_CRITIQUE.replace("**Where:** `src/deploy.py:42`\n", ""),
                       encoding="utf-8")
        check(cmd_merge(str(mdir / "x.md"), [str(adv), str(bad)], None, False) == 1,
              "merge accepted a malformed input")
        check(cmd_merge(str(adv), [str(adv), str(ovl)], None, False) == 2,
              "merge accepted out == in")

        # 13. Rebind guard. A critic file that CHANGES after extract shifts every
        #     later id in its severity; `extract` cannot catch it (nothing is
        #     dropped), so a recorded disposition would silently follow the id
        #     onto a different finding. merge must refuse.
        def _one(critic: str, sev: str, letter: str, items: list[tuple[str, str]]) -> str:
            out = [f"# Critique - demo-m2 - {critic}", "", f"**Critic:** {critic}",
                   "**Critique format version:** 1.0", "", "## Verdict", "",
                   "SHIP-WITH-FIXES", "", "## Findings", ""]
            for n, (title, f) in enumerate(items, 1):
                out += [f"**{letter}{n} - {title}** ({sev})", "",
                        f"**Where:** `{f}:1`", "**Anchor:** `x`", "**What:** w.",
                        "**Why it matters:** w.", "**Proposed fix:** w.",
                        "**Regression-guard:** optional", f"**Source critic:** {critic}", ""]
            out += [f"Severity counts: C0 H0 M{len(items)} L0", "",
                    f"## {_ORDER_HEADING}", "",
                    ", ".join(f"{letter}{n}" for n in range(1, len(items) + 1)), ""]
            return "\n".join(out)

        m2dir = root / ".claude" / "notes" / "milestones" / "demo-m2" / "critique"
        m2dir.mkdir(parents=True)
        ca, cb = m2dir / "adversary.md", m2dir / "overlay.md"
        ca.write_text(_one("milestone-adversary-critic", "MEDIUM", "M",
                           [("alpha", "a.py")]), encoding="utf-8")
        cb.write_text(_one("milestone-arxmcp-critic", "MEDIUM", "M",
                           [("beta", "b.py")]), encoding="utf-8")
        d2 = m2dir / "dedup.md"
        check(cmd_merge(str(d2), [str(ca), str(cb)], None, False) == 0, "demo-m2 merge failed")
        check(cmd_extract("demo-m2", [str(d2)], check_only=False) == 0, "demo-m2 extract failed")
        check(cmd_set("demo-m2", "M2", "deferred", "beta is cosmetic") == 0, "demo-m2 set failed")
        # adversary gains a finding -> overlay's "beta" slides M2 -> M3.
        ca.write_text(_one("milestone-adversary-critic", "MEDIUM", "M",
                           [("alpha", "a.py"), ("gamma", "c.py")]), encoding="utf-8")
        check(cmd_merge(str(m2dir / "d3.md"), [str(ca), str(cb)], None, False) == 1,
              "merge did NOT refuse a re-merge that repoints a disposed id")
        check(cmd_merge(str(m2dir / "d3.md"), [str(ca), str(cb)], None, True) == 0,
              "--force did not override the rebind guard")

        del os.environ["REPO_ROOT"]

    if failures:
        print(f"SELF-TEST FAILED ({len(failures)}):", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("self-test OK")
    return 0


# --- CLI ----------------------------------------------------------------------


def main(argv: list[str]) -> int:
    if "--self-test" in argv[1:]:
        return _self_test()

    parser = argparse.ArgumentParser(
        prog="milestone-pipeline-findings.py",
        description="findings register: parser, status writer, and completion gate",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_extract = sub.add_parser("extract", help="parse critique(s) -> register (or --check)")
    p_extract.add_argument("--id", dest="mid", default=None)
    p_extract.add_argument("--check", action="store_true")
    p_extract.add_argument("files", nargs="*")

    p_set = sub.add_parser("set", help="the sole sanctioned status writer")
    p_set.add_argument("mid")
    p_set.add_argument("ids", help="comma-separated finding ids, e.g. C1,H2")
    p_set.add_argument("status", choices=["fixed", "deferred", "invalidated"])
    p_set.add_argument("--resolution", default=None)

    p_gate = sub.add_parser("gate", help="exit 3 while any CRITICAL/HIGH is open")
    p_gate.add_argument("mid")

    p_sum = sub.add_parser("summary", help="derive count/id arrays for state.json")
    p_sum.add_argument("mid", nargs="?", default=None)
    p_sum.add_argument("--counts-for", dest="counts_for", default=None)
    p_sum.add_argument("--field", default=None)

    p_dd = sub.add_parser("dedupe", help="cross-critic agreement clustering")
    p_dd.add_argument("file")

    p_mg = sub.add_parser("merge", help="combine per-critic critiques (renumbers ids)")
    p_mg.add_argument("out", help="destination, normally critique/dedup.md")
    p_mg.add_argument("inputs", nargs="+",
                      help="critic files IN DISPATCH ORDER: adversary, overlays, oss")
    p_mg.add_argument("--id", dest="mid", default=None,
                      help="milestone id (else derived from the title or the out path)")
    p_mg.add_argument("--force", action="store_true",
                      help="merge even if it would repoint a disposed finding id")

    args = parser.parse_args(argv[1:])

    if args.cmd == "extract":
        return cmd_extract(args.mid, args.files, args.check)
    if args.cmd == "set":
        return cmd_set(args.mid, args.ids, args.status, args.resolution)
    if args.cmd == "gate":
        return cmd_gate(args.mid)
    if args.cmd == "summary":
        return cmd_summary(args.mid, args.counts_for, args.field)
    if args.cmd == "dedupe":
        return cmd_dedupe(args.file)
    if args.cmd == "merge":
        return cmd_merge(args.out, args.inputs, args.mid, args.force)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
