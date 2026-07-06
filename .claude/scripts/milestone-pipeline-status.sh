#!/usr/bin/env bash
# milestone-pipeline-status.sh — print current milestone-pipeline state.
# Usage: milestone-pipeline-status.sh <milestone-id>
#
# ASCII-only output (no Unicode arrows) so the script runs cleanly on
# Windows's default cp1252 codepage.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: milestone-pipeline-status.sh <milestone-id>" >&2
  exit 2
fi

ID="$1"

# Repo root resolution.
if REPO_ROOT_TRY=$(git -C "$(dirname "$0")" rev-parse --show-toplevel 2>/dev/null); then
  REPO_ROOT="$REPO_ROOT_TRY"
else
  d="$(cd "$(dirname "$0")" && pwd)"
  while [[ "$d" != "/" && ! -d "$d/.git" ]]; do d="$(dirname "$d")"; done
  if [[ -d "$d/.git" ]]; then
    REPO_ROOT="$d"
  else
    echo "error: cannot find repo root (no .git ancestor)" >&2
    exit 1
  fi
fi

# Prefer the .venv interpreter so we never accidentally hit a stale system python3.
PY="$REPO_ROOT/.venv/Scripts/python.exe"
if [[ ! -x "$PY" ]]; then
  PY="$REPO_ROOT/.venv/bin/python"
fi
if [[ ! -x "$PY" ]]; then
  PY="python3"
fi

STATE="$REPO_ROOT/.claude/notes/milestones/$ID/state.json"

if [[ ! -f "$STATE" ]]; then
  echo "no state for $ID -- run milestone-pipeline-init-state.sh first" >&2
  exit 1
fi

"$PY" - "$STATE" <<'PY'
import json, sys
from datetime import datetime, timezone

# Force UTF-8 stdout so any non-ASCII brief content does not crash on Windows
# cp1252.  Script output itself is ASCII-only.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

state_path = sys.argv[1]
with open(state_path, encoding="utf-8") as f:
    state = json.load(f)

def parse(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

now = datetime.now(timezone.utc)
hist = state["phase_history"]

print(f"Milestone: {state['id']}")
if state.get("brief_source"):
    print(f"Brief:     {state['brief_source']}")
cur_phase = state["phase"]
last_ts = parse(hist[-1]["at"])
mins_in_phase = int((now - last_ts).total_seconds() // 60)
print(f"Phase:     {cur_phase} (since {hist[-1]['at']}, {mins_in_phase} min ago)")

print("History:")
for i, entry in enumerate(hist):
    ts = parse(entry["at"])
    if i + 1 < len(hist):
        nxt = parse(hist[i + 1]["at"])
        delta = nxt - ts
        mins = int(delta.total_seconds() // 60)
        secs = int(delta.total_seconds() % 60)
        if mins > 0:
            elapsed = f"+{mins:>2}m -> {hist[i + 1]['phase']}"
        else:
            elapsed = f"+{secs:>2}s -> {hist[i + 1]['phase']}"
    else:
        elapsed = "(now)"
    print(f"  {entry['phase']:<22} {entry['at']} {elapsed}")

if state.get("research_mode"):
    print(f"Research mode: {state['research_mode']}")

if state.get("implementation_path"):
    print(f"Implementation path: {state['implementation_path']}")
    if state.get("implementation_branch"):
        print(f"                    branch: {state['implementation_branch']}")
    if state.get("implementation_commit_range"):
        print(f"                    range:  {state['implementation_commit_range']}")

if state.get("critics_run"):
    print(f"Critics run: {', '.join(state['critics_run'])}")
counts = state.get("critique_finding_counts") or {}
if any(counts.values()):
    parts = " ".join(f"{k[0].upper()}{counts.get(k, 0)}" for k in ("critical", "high", "medium", "low"))
    print(f"Findings:    {parts}")

if state.get("rectification_commit"):
    print(f"Rectification commit: {state['rectification_commit']}")
    fixed = state.get("fixed_findings") or []
    deferred = state.get("deferred_findings") or []
    invalidated = state.get("invalidated_findings") or []
    if fixed:
        print(f"             fixed:       {', '.join(fixed)}")
    if invalidated:
        print(f"             invalidated: {', '.join(invalidated)}")
    if deferred:
        print(f"             deferred:    {', '.join(deferred)}")

NEXT = {
    "init":               "research-running (run Phase 1 of milestone-pipeline)",
    "research-running":   "research-complete (researchers in flight; await briefs)",
    "research-complete":  "implement-running (run Phase 2 of milestone-pipeline)",
    "implement-running":  "implement-complete (implementer in flight; await commit)",
    "implement-complete": "critique-running (run Phase 3 of milestone-pipeline)",
    "critique-running":   "critique-complete (critics in flight; await critique files)",
    "critique-complete":  "rectify-running (run Phase 4 of milestone-pipeline)",
    "rectify-running":    "complete (rectify in progress; await rect commit + write-back)",
    "complete":           "(terminal -- pipeline done)",
}
print(f"Next phase:  {NEXT.get(cur_phase, '(unknown)')}")
PY
