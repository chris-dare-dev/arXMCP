#!/usr/bin/env bash
# Print current frontend-uplift state in a human-readable form.
# Usage: status.sh <uplift-id>

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: status.sh <uplift-id>" >&2
  exit 2
fi

ID="$1"
REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
STATE="$REPO_ROOT/.claude/notes/frontend-uplifts/$ID/state.json"

if [[ ! -f "$STATE" ]]; then
  echo "no state for $ID — run init-uplift.sh first" >&2
  exit 1
fi

python3 - "$STATE" <<'PY'
import json, os, sys
from datetime import datetime, timezone

state_path = sys.argv[1]
state = json.load(open(state_path))

def parse(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

now = datetime.now(timezone.utc)
hist = state["phase_history"]

print(f"Uplift:   {state['id']}")
cur_phase = state["phase"]
last_ts = parse(hist[-1]["at"])
mins_in_phase = int((now - last_ts).total_seconds() // 60)
print(f"Phase:    {cur_phase} (since {hist[-1]['at']}, {mins_in_phase} min ago)")

if state.get("discover_mode"):
    print(f"Mode:     {state['discover_mode']}")
pages = state.get("pages_to_walk") or []
if pages:
    print(f"Pages:    {len(pages)} (override) — {', '.join(pages[:6])}{'…' if len(pages)>6 else ''}")
else:
    print(f"Pages:    (default — 3 routes + 1 fragment; arxmcp-design-system.md §3)")

print("History:")
for i, entry in enumerate(hist):
    ts = parse(entry["at"])
    if i + 1 < len(hist):
        nxt = parse(hist[i + 1]["at"])
        delta = nxt - ts
        mins = int(delta.total_seconds() // 60)
        secs = int(delta.total_seconds() % 60)
        elapsed = f"+{mins:>2}m → {hist[i + 1]['phase']}" if mins > 0 else f"+{secs:>2}s → {hist[i + 1]['phase']}"
    else:
        elapsed = "(now)"
    print(f"  {entry['phase']:<22} {entry['at']} {elapsed}")

dispatched = state.get("agents_dispatched") or []
returned = state.get("agents_returned") or []
if dispatched:
    pending = sorted(set(dispatched) - set(returned))
    print(f"Agents:   dispatched={','.join(dispatched)}")
    print(f"          returned={','.join(returned) if returned else '(none yet)'}")
    if pending:
        print(f"          pending={','.join(pending)}")

screenshot_dir = state.get("screenshot_dir")
if screenshot_dir:
    abs_dir = os.path.join(os.path.dirname(os.path.dirname(state_path)), os.path.basename(screenshot_dir))
    # Resolve relative path against repo root
    repo_root = os.path.realpath(os.path.join(os.path.dirname(state_path), "..", "..", "..", ".."))
    full = os.path.join(repo_root, screenshot_dir)
    if os.path.isdir(full):
        png_count = len([f for f in os.listdir(full) if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))])
        print(f"Shots:    {png_count} captured under {screenshot_dir}")

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
    "init":                  "discover-running (run Phase 1 — dispatch 4 scouts in parallel; ensure-preview-up.sh first)",
    "discover-running":      "discover-complete (scouts in flight; await briefs)",
    "discover-complete":     "synthesize-running (run Phase 2 — main session merges briefs)",
    "synthesize-running":    "synthesize-complete (synthesis.md written)",
    "synthesize-complete":   "challenge-running (run Phase 3 — dispatch challenger sub-agent)",
    "challenge-running":     "challenge-complete (challenger in flight; await critique)",
    "challenge-complete":    "prioritize-running (run Phase 4 — main session ranks candidates)",
    "prioritize-running":    "complete (final-report.md written)",
    "complete":              "(terminal — pipeline done; feed final-report.md to /milestone-pipeline or /roadmap to materialize)",
}
print(f"Next:     {NEXT.get(cur_phase, '(unknown)')}")
PY
