#!/usr/bin/env bash
# status.sh — human-readable dump of milestone-pipeline state.
#
# Usage: status.sh <ID> [--repo-root /path]

set -euo pipefail

[[ $# -ge 1 ]] || { echo "usage: status.sh <ID> [--repo-root /path]" >&2; exit 2; }

MILESTONE_ID="$1"; shift
REPO_ROOT_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo-root) REPO_ROOT_OVERRIDE="${2:-}"; shift 2 ;;
        *) echo "error: unknown arg: $1" >&2; exit 2 ;;
    esac
done

detect_repo_root() {
    if [[ -n "$REPO_ROOT_OVERRIDE" ]]; then
        cd "$REPO_ROOT_OVERRIDE" && pwd; return
    fi
    if [[ -n "${REPO_ROOT:-}" && -d "$REPO_ROOT/.git" ]]; then
        cd "$REPO_ROOT" && pwd; return
    fi
    if root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
        echo "$root"; return
    fi
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    while [[ "$here" != "/" ]]; do
        if [[ -d "$here/.git" ]]; then echo "$here"; return; fi
        here="$(dirname "$here")"
    done
    echo "error: could not locate repo root" >&2; exit 1
}

REPO_ROOT_RESOLVED="$(detect_repo_root)"
STATE_FILE="$REPO_ROOT_RESOLVED/.claude/notes/milestones/$MILESTONE_ID/state.json"

[[ -f "$STATE_FILE" ]] || { echo "error: no state for $MILESTONE_ID at $STATE_FILE" >&2; exit 1; }

STATE_FILE="$STATE_FILE" python3 <<'PY'
import datetime as dt
import json
import os

with open(os.environ["STATE_FILE"]) as f:
    s = json.load(f)


def parse(ts):
    if not ts:
        return None
    return dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def fmt_elapsed(start, end):
    if not start:
        return "—"
    end = end or dt.datetime.now(dt.timezone.utc)
    delta = end - start
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m{secs % 60:02d}s"
    return f"{secs // 3600}h{(secs % 3600) // 60:02d}m"


print(f"milestone:    {s['id']}")
print(f"phase:        {s['phase']}")
print(f"created:      {s['created_at']}")
print(f"updated:      {s['updated_at']}")
print()

print("phase history:")
for h in s.get("phase_history", []):
    start = parse(h.get("entered_at"))
    end = parse(h.get("left_at"))
    elapsed = fmt_elapsed(start, end)
    marker = " (current)" if h.get("phase") == s["phase"] and not end else ""
    print(f"  {h['phase']:<22} entered={h.get('entered_at')}  elapsed={elapsed}{marker}")
print()

brief = (s.get("milestone_brief") or "").splitlines()
print("brief (first 3 lines):")
for line in brief[:3]:
    print(f"  {line}")
if len(brief) > 3:
    print(f"  ... ({len(brief) - 3} more lines)")
print()

print("research:")
print(f"  mode:       {s.get('research_mode', '—')}")
print(f"  briefs:     {len(s.get('research_briefs', []))}")
synth = s.get("research_synthesis")
print(f"  synthesis:  {synth or '—'}")
print()

print("implementation:")
print(f"  path:       {s.get('implementation_path') or '—'}")
print(f"  specialist: {s.get('implementation_specialist') or '—'}")
print(f"  branch:     {s.get('implementation_branch') or '—'}")
print(f"  commits:    {len(s.get('implementation_commits', []))}")
print(f"  range:      {s.get('implementation_commit_range') or '—'}")
print()

print("critique:")
print(f"  output:     {s.get('critique_path') or '—'}")
print(f"  critics:    {', '.join(c.get('critic') for c in s.get('critics_run', [])) or '—'}")
counts = s.get("critique_finding_counts", {})
print(f"  findings:   crit={counts.get('critical', 0)} high={counts.get('high', 0)} med={counts.get('medium', 0)} low={counts.get('low', 0)}")
print()

print("rectification:")
print(f"  commit:     {s.get('rectification_commit') or '—'}")
print(f"  fixed:      {len(s.get('fixed_findings', []))}  deferred: {len(s.get('deferred_findings', []))}  invalidated: {len(s.get('invalidated_findings', []))}")
print(f"  reg tests:  {len(s.get('regression_tests_added', []))}")
print()

print("external writes:")
ext = s.get("external_writes_required", [])
print(f"  required:   {len(ext)}")
for e in ext:
    print(f"    - {e.get('type', '?')}: {e.get('target', '?')}")
print(f"  authorized: {s.get('external_writes_authorized', False)}")
print(f"  completed:  {s.get('external_writes_completed', False)}")
PY
