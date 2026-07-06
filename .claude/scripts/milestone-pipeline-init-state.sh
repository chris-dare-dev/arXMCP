#!/usr/bin/env bash
# milestone-pipeline-init-state.sh — idempotent milestone state init + lock.
#
# Usage:
#   milestone-pipeline-init-state.sh <ID> [--brief "..."] [--single|--deep]
#       [--oss-scout] [--allow-large-diff] [--resume] [--repo-root PATH]
#   milestone-pipeline-init-state.sh <ID> --release-lock
#
# Behavior:
#   - Brief resolution: --brief wins (source recorded as 'inline'); otherwise
#     delegates to milestone-pipeline-resolve-brief.py, which scans
#     plans/*/roadmap.yaml and falls back to legacy '### <ID> —' prose
#     headings. state.brief_source records the resolver's 'source:' line.
#   - Idempotent: if state.json already exists, prints 'RESUMING phase=<X>'
#     and exits 0 without modifying state (the orchestrator's resume signal).
#   - Lock: .claude/notes/milestones/.lock holds '<pid>:<id>:<created-at>'.
#     One milestone runs at a time; a live lock for a DIFFERENT id refuses,
#     a dead lock instructs '--release-lock'. Never rm the lock by hand.
#
# Exit codes: 0 success / resume; 1 actionable failure (lock, ambiguous id,
# resolver error); 2 usage error.

set -euo pipefail

usage() {
  cat <<EOF >&2
usage: milestone-pipeline-init-state.sh <ID> [--brief "..."] [--single|--deep]
           [--oss-scout] [--allow-large-diff] [--resume] [--repo-root PATH]
       milestone-pipeline-init-state.sh <ID> --release-lock

  <ID>   milestone (<slug>-mN), spike (<slug>-spike-N), or ad-hoc
         (adhoc-YYYYMMDD-<sha7>, produced by the /milestone-pipeline --brief form)
EOF
  exit 2
}

[[ $# -ge 1 ]] || usage
case "$1" in -h|--help) usage ;; esac

MILESTONE_ID="$1"; shift
BRIEF=""
RESEARCH_MODE="standard"
OSS_SCOUT_REQUESTED="false"
ALLOW_LARGE_DIFF="false"
RELEASE_LOCK="false"
REPO_ROOT_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --brief) BRIEF="${2:-}"; shift 2 ;;
    --single) RESEARCH_MODE="single"; shift ;;
    --deep) RESEARCH_MODE="deep"; shift ;;
    --oss-scout) OSS_SCOUT_REQUESTED="true"; shift ;;
    --allow-large-diff) ALLOW_LARGE_DIFF="true"; shift ;;
    --release-lock) RELEASE_LOCK="true"; shift ;;
    --repo-root) REPO_ROOT_OVERRIDE="${2:-}"; shift 2 ;;
    --resume)
      # --resume is a no-op at init time; resume routing is driven by the
      # RESUMING line this script prints when state already exists. Accepted
      # so the orchestrator can pass its full argv through.
      shift ;;
    *) echo "error: unknown arg: $1" >&2; usage ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Repo-root detection: --repo-root > git rev-parse > walk up from script dir.
detect_repo_root() {
  if [[ -n "$REPO_ROOT_OVERRIDE" ]]; then
    if [[ ! -d "$REPO_ROOT_OVERRIDE" ]]; then
      echo "error: --repo-root '$REPO_ROOT_OVERRIDE' is not a directory" >&2
      exit 2
    fi
    cd "$REPO_ROOT_OVERRIDE" && pwd; return
  fi
  if root="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)"; then
    echo "$root"; return
  fi
  here="$SCRIPT_DIR"
  while [[ "$here" != "/" ]]; do
    if [[ -d "$here/.git" ]]; then echo "$here"; return; fi
    here="$(dirname "$here")"
  done
  echo "error: could not locate repo root" >&2; exit 1
}

REPO_ROOT_RESOLVED="$(detect_repo_root)"

# Prefer a project venv interpreter when present; fall back to python3.
PY="$REPO_ROOT_RESOLVED/.venv/Scripts/python.exe"
[[ -x "$PY" ]] || PY="$REPO_ROOT_RESOLVED/.venv/bin/python"
[[ -x "$PY" ]] || PY="python3"

NOTES_DIR="$REPO_ROOT_RESOLVED/.claude/notes/milestones"
STATE_DIR="$NOTES_DIR/$MILESTONE_ID"
STATE_FILE="$STATE_DIR/state.json"
LOCK="$NOTES_DIR/.lock"

# ── --release-lock ─────────────────────────────────────────────────────────
if [[ "$RELEASE_LOCK" == "true" ]]; then
  if [[ ! -f "$LOCK" ]]; then
    echo "no lock present at $LOCK"
    exit 0
  fi
  IFS=':' read -r LPID LID LTS < "$LOCK" || true
  if [[ "$LID" == "$MILESTONE_ID" ]] || ! kill -0 "$LPID" 2>/dev/null; then
    rm -f "$LOCK"
    echo "released lock (was ${LPID}:${LID}:${LTS})"
    exit 0
  fi
  echo "error: refusing to release — lock held by LIVE pid $LPID for '$LID'" >&2
  exit 1
fi

# ── Milestone id shape ─────────────────────────────────────────────────────
if [[ ! "$MILESTONE_ID" =~ ^[a-z0-9-]+-m[0-9]+$ ]] \
   && [[ ! "$MILESTONE_ID" =~ ^[a-z0-9-]+-spike-[0-9]+$ ]] \
   && [[ ! "$MILESTONE_ID" =~ ^adhoc-[0-9]{8}-[0-9a-f]{7}$ ]]; then
  echo "error: invalid milestone id '$MILESTONE_ID'" >&2
  echo "  expected: <slug>-mN | <slug>-spike-N | adhoc-YYYYMMDD-<sha7>" >&2
  echo "  examples: arxmcp-v2-search-m1, arxmcp-v2-search-spike-1" >&2
  exit 2
fi

# ── Lock check (one milestone at a time) ───────────────────────────────────
if [[ -f "$LOCK" ]]; then
  IFS=':' read -r LPID LID LTS < "$LOCK" || true
  if [[ "$LID" != "$MILESTONE_ID" ]]; then
    if kill -0 "$LPID" 2>/dev/null; then
      echo "error: milestone lock held by LIVE pid $LPID for '$LID' (since $LTS)." >&2
      echo "       Only one milestone runs at a time. Finish or abort it first." >&2
    else
      echo "error: stale lock (dead pid $LPID) for '$LID' (since $LTS)." >&2
      echo "       Clear it via: milestone-pipeline-init-state.sh $LID --release-lock" >&2
    fi
    exit 1
  fi
fi

# ── Idempotent resume ──────────────────────────────────────────────────────
if [[ -f "$STATE_FILE" ]]; then
  PHASE="$("$PY" -c "
import json, sys
with open(sys.argv[1], encoding='utf-8') as f:
    print(json.load(f).get('phase', '(unknown)'))
" "$STATE_FILE")"
  # Re-take the lock if it vanished (crashed session cleanup).
  if [[ ! -f "$LOCK" ]]; then
    mkdir -p "$NOTES_DIR"
    printf '%s:%s:%s\n' "$PPID" "$MILESTONE_ID" \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$LOCK"
  fi
  echo "RESUMING phase=$PHASE"
  echo "  state file: $STATE_FILE"
  exit 0
fi

# ── Brief resolution ───────────────────────────────────────────────────────
BRIEF_SOURCE=""
if [[ -n "$BRIEF" ]]; then
  BRIEF_SOURCE="inline"
else
  set +e
  RB_OUT="$("$PY" "$SCRIPT_DIR/milestone-pipeline-resolve-brief.py" \
    "$MILESTONE_ID" --repo-root "$REPO_ROOT_RESOLVED")"
  RB_RC=$?
  set -e
  case "$RB_RC" in
    0)
      # First line is 'source: <kind> <path>'; brief body starts at line 3.
      BRIEF_SOURCE="$(printf '%s\n' "$RB_OUT" | head -n 1 | sed 's/^source: //')"
      BRIEF="$(printf '%s\n' "$RB_OUT" | tail -n +3)"
      ;;
    1)
      echo "error: brief resolution failed (ambiguous id) — see resolver message above" >&2
      exit 1
      ;;
    2)
      echo "warning: no brief found for $MILESTONE_ID in plans/*/roadmap.yaml or legacy prose" >&2
      echo "         continuing with empty brief — set it later via:" >&2
      echo "           milestone-pipeline-checkpoint.py $MILESTONE_ID --set 'milestone_brief=\"...\"'" >&2
      ;;
    *)
      echo "error: resolve-brief failed unexpectedly (exit $RB_RC)" >&2
      exit 1
      ;;
  esac
fi

# ── State + lock creation ──────────────────────────────────────────────────
mkdir -p "$STATE_DIR/research" "$STATE_DIR/implement" \
         "$STATE_DIR/critique" "$STATE_DIR/rectify"

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '%s:%s:%s\n' "$PPID" "$MILESTONE_ID" "$NOW" > "$LOCK"

# Write JSON via python (handles brief escaping safely; atomic tmp+rename).
BRIEF="$BRIEF" BRIEF_SOURCE="$BRIEF_SOURCE" MILESTONE_ID="$MILESTONE_ID" \
NOW="$NOW" STATE_FILE="$STATE_FILE" RESEARCH_MODE="$RESEARCH_MODE" \
OSS_SCOUT_REQUESTED="$OSS_SCOUT_REQUESTED" ALLOW_LARGE_DIFF="$ALLOW_LARGE_DIFF" \
"$PY" <<'PY'
import json, os
state = {
    "id": os.environ["MILESTONE_ID"],
    "created_at": os.environ["NOW"],
    "updated_at": os.environ["NOW"],
    "phase": "init",
    "phase_history": [{"phase": "init", "at": os.environ["NOW"]}],
    "milestone_brief": os.environ.get("BRIEF", ""),
    "brief_source": os.environ.get("BRIEF_SOURCE", ""),
    "research_mode": os.environ.get("RESEARCH_MODE", "standard"),
    "oss_scout_requested": os.environ.get("OSS_SCOUT_REQUESTED") == "true",
    "allow_large_diff": os.environ.get("ALLOW_LARGE_DIFF") == "true",
    "research_briefs": [],
    "research_synthesis": None,
    "implementation_path": None,
    "implementation_plan": None,
    "implementation_base": None,
    "implementation_commit_range": None,
    "implementation_commits": [],
    "implementation_branch": None,
    "external_writes_required": [],
    "critique_path": None,
    "critics_run": [],
    "critique_finding_counts": {"critical": 0, "high": 0, "medium": 0, "low": 0},
    "rectification_commit": None,
    "fixed_findings": [],
    "deferred_findings": [],
    "invalidated_findings": [],
    "regression_tests_added": [],
    "external_writes_authorized": [],
    "external_writes_completed": [],
}
path = os.environ["STATE_FILE"]
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2)
    f.write("\n")
os.replace(tmp, path)
PY

if [[ -n "$BRIEF" ]]; then
  BRIEF_NOTE="set ($(printf '%s' "$BRIEF" | wc -c | tr -d ' ') chars, source: ${BRIEF_SOURCE:-unknown})"
else
  BRIEF_NOTE="(empty — pass --brief or add the item to plans/*/roadmap.yaml)"
fi

echo "initialized $STATE_FILE"
echo "  brief: $BRIEF_NOTE"
echo "  phase: init"
echo "  lock:  $LOCK"
