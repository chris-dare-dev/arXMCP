#!/usr/bin/env bash
# Print current capability-scout state in a human-readable form.
# Usage: status.sh <scout-id>

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: status.sh <scout-id>" >&2
  exit 2
fi

ID="$1"
REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
STATE="$REPO_ROOT/.claude/notes/capability-scouts/$ID/state.json"

if [[ ! -f "$STATE" ]]; then
  echo "no state for $ID — run init-scout.sh first" >&2
  exit 1
fi

python3 - "$STATE" <<'PY'
import json, sys
from datetime import datetime, timezone

state_path = sys.argv[1]
state = json.load(open(state_path))

def parse(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

now = datetime.now(timezone.utc)
hist = state["phase_history"]

print(f"Scout:    {state['id']}")
cur_phase = state["phase"]
last_ts = parse(hist[-1]["at"])
mins_in_phase = int((now - last_ts).total_seconds() // 60)
print(f"Phase:    {cur_phase} (since {hist[-1]['at']}, {mins_in_phase} min ago)")

if state.get("survey_mode"):
    print(f"Mode:     {state['survey_mode']}")

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

dispatched = state.get("scouts_dispatched") or []
returned = state.get("scouts_returned") or []
if dispatched:
    pending = sorted(set(dispatched) - set(returned))
    print(f"Scouts:   dispatched={','.join(dispatched)}")
    print(f"          returned={','.join(returned) if returned else '(none yet)'}")
    if pending:
        print(f"          pending={','.join(pending)}")

if state.get("synthesis_path"):
    print(f"Synthesis: {state['synthesis_path']} ({state.get('candidate_count', 0)} candidates)")

if state.get("challenge_path"):
    print(f"Challenge: {state['challenge_path']}")
    counts = state.get("challenge_finding_counts") or {}
    if any(counts.values()):
        parts = " ".join(f"{k[0].upper()}{counts.get(k, 0)}" for k in ("critical", "high", "medium", "low"))
        print(f"           findings: {parts}")

if state.get("final_report_path"):
    print(f"Report:   {state['final_report_path']}")

NEXT = {
    "init":                  "survey-running (run Phase 1 - dispatch 5 scouts in parallel)",
    "survey-running":        "survey-complete (scouts in flight; await briefs)",
    "survey-complete":       "synthesize-running (run Phase 2 - main session merges briefs)",
    "synthesize-running":    "synthesize-complete (synthesis.md written)",
    "synthesize-complete":   "challenge-running (run Phase 3 - dispatch challenger sub-agent)",
    "challenge-running":     "challenge-complete (challenger in flight; await critique)",
    "challenge-complete":    "prioritize-running (run Phase 4 - main session ranks candidates)",
    "prioritize-running":    "complete (final-report.md written)",
    "complete":              "(terminal - pipeline done; feed final-report.md to /roadmap to materialize)",
}
print(f"Next:     {NEXT.get(cur_phase, '(unknown)')}")
PY
