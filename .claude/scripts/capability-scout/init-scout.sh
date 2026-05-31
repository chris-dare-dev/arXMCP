#!/usr/bin/env bash
# Initialize capability-scout state directory and state.json.
#
# Usage: init-scout.sh <scout-id> [--brief "verbatim user brief"]
#
# Idempotent: if state.json exists, prints current phase and exits 0
# without modifying anything.  The orchestrator uses that as the resume
# signal, mirroring milestone-pipeline's init-state.sh shape.
#
# <scout-id> is a free-form slug — typical convention is a date stamp + topic,
# e.g. "2026q2-retrieval-gap-scan" or "lean-verification-survey-v1".

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: init-scout.sh <scout-id> [--brief \"...\"]" >&2
  exit 2
fi

ID="$1"
shift

BRIEF=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --brief)
      BRIEF="${2:-}"
      shift 2
      ;;
    *)
      echo "unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
DIR="$REPO_ROOT/.claude/notes/capability-scouts/$ID"
STATE="$DIR/state.json"

if [[ -f "$STATE" ]]; then
  PHASE=$(python3 -c "import json; print(json.load(open('$STATE'))['phase'])")
  echo "state already exists at $STATE (phase=$PHASE) — resuming"
  exit 0
fi

mkdir -p "$DIR/survey" "$DIR/artifacts"

NOW=$(python3 -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))")

python3 - "$STATE" "$ID" "$NOW" "$BRIEF" <<'PY'
import json, os, sys
state_path, sid, now, brief = sys.argv[1:5]
state = {
    "id": sid,
    "kind": "capability-scout",
    "created_at": now,
    "updated_at": now,
    "phase": "init",
    "phase_history": [{"phase": "init", "at": now}],
    "scout_brief": brief,
    # Phase 1
    "survey_mode": None,            # "standard" (4 scouts + adversary) | "lean" (2 scouts + adversary) | "deep" (4 scouts + adversary + Opus override)
    "survey_briefs": [],            # list of brief paths once scouts return
    "scouts_dispatched": [],        # subset of:
                                    #   comparative | research-frontier | oss-trends | multi-agent | adversary
    "scouts_returned": [],
    # Phase 2
    "synthesis_path": None,
    "candidate_count": 0,
    # Phase 3
    "challenge_path": None,
    "challenge_finding_counts": {"critical": 0, "high": 0, "medium": 0, "low": 0},
    # Phase 4
    "final_report_path": None,
    "ranked_candidates": [],        # populated by the orchestrator in Phase 4
}
tmp = state_path + ".tmp"
with open(tmp, "w") as f:
    json.dump(state, f, indent=2)
os.replace(tmp, state_path)
PY

echo "initialized $STATE"
echo "  brief: $(if [[ -n "$BRIEF" ]]; then echo "set ($(echo "$BRIEF" | wc -c | tr -d ' ') chars)"; else echo "(empty — pass --brief to populate)"; fi)"
echo "  phase: init"
