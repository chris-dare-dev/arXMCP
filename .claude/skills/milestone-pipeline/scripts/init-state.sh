#!/usr/bin/env bash
# init-state.sh — idempotent initialization of milestone state.
#
# Usage:
#   init-state.sh <ID> [--brief "text"] [--repo-root /path]
#
# Behavior:
#   - If state.json already exists for this ID, prints current phase and
#     exits 0 (resume signal). Does NOT overwrite.
#   - Otherwise: creates state.json with phase=init, milestone_brief
#     resolved from --brief flag OR grepped from .claude/roadmap/.
#
# Exit codes: 0 success / resume; 1 actionable failure; 2 input error.

set -euo pipefail

usage() {
    cat <<EOF >&2
usage: init-state.sh <ID> [--brief "text"] [--repo-root /path]

  <ID>            milestone identifier (e.g. E01_S01)
  --brief TEXT    inline milestone brief (overrides roadmap lookup)
  --repo-root P   override repo-root detection
EOF
    exit 2
}

[[ $# -ge 1 ]] || usage
case "$1" in -h|--help) usage ;; esac

MILESTONE_ID="$1"; shift
BRIEF=""
REPO_ROOT_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --brief) BRIEF="${2:-}"; shift 2 ;;
        --repo-root) REPO_ROOT_OVERRIDE="${2:-}"; shift 2 ;;
        *) echo "error: unknown arg: $1" >&2; usage ;;
    esac
done

# Repo-root detection: --repo-root → $REPO_ROOT → git rev-parse → walk up.
detect_repo_root() {
    if [[ -n "$REPO_ROOT_OVERRIDE" ]]; then
        if [[ ! -d "$REPO_ROOT_OVERRIDE/.git" ]]; then
            echo "error: --repo-root '$REPO_ROOT_OVERRIDE' has no .git/" >&2
            exit 2
        fi
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
STATE_DIR="$REPO_ROOT_RESOLVED/.claude/notes/milestones/$MILESTONE_ID"
STATE_FILE="$STATE_DIR/state.json"

# Idempotent re-run: if state already exists, surface phase and exit 0.
if [[ -f "$STATE_FILE" ]]; then
    phase=$(python3 -c "
import json, sys
with open('$STATE_FILE') as f: print(json.load(f).get('phase','(unknown)'))
")
    echo "milestone $MILESTONE_ID already initialized — resume from phase '$phase'"
    echo "  state file: $STATE_FILE"
    exit 0
fi

# Resolve brief: explicit --brief wins, otherwise grep the roadmap.
if [[ -z "$BRIEF" ]]; then
    ROADMAP_DIR="$REPO_ROOT_RESOLVED/.claude/roadmap"
    if [[ -d "$ROADMAP_DIR" ]]; then
        # Block extraction: from "### <ID> —" to next "### " or EOF.
        brief_block=$(awk -v id="$MILESTONE_ID" '
            $0 ~ "^### " id " " { printing=1; print; next }
            printing && /^### / { exit }
            printing { print }
        ' "$ROADMAP_DIR"/*.md 2>/dev/null || true)
        if [[ -n "$brief_block" ]]; then
            BRIEF="$brief_block"
        fi
    fi
fi

if [[ -z "$BRIEF" ]]; then
    echo "warning: no brief found for $MILESTONE_ID in roadmap and --brief not given" >&2
    echo "         continuing with empty brief — set it later via:" >&2
    echo "           checkpoint.py $MILESTONE_ID --set 'milestone_brief=\"...\"'" >&2
fi

mkdir -p "$STATE_DIR"

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Use python to write JSON safely (handles brief escaping correctly).
BRIEF="$BRIEF" MILESTONE_ID="$MILESTONE_ID" NOW="$NOW" STATE_FILE="$STATE_FILE" \
python3 <<'PY'
import json, os, sys
state = {
    "id": os.environ["MILESTONE_ID"],
    "created_at": os.environ["NOW"],
    "updated_at": os.environ["NOW"],
    "phase": "init",
    "phase_history": [{"phase": "init", "entered_at": os.environ["NOW"], "left_at": None}],
    "milestone_brief": os.environ.get("BRIEF", ""),
    "research_mode": "standard",
    "research_briefs": [],
    "research_synthesis": None,
    "implementation_path": None,
    "implementation_specialist": None,
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
    "external_writes_authorized": False,
    "external_writes_completed": False,
}
path = os.environ["STATE_FILE"]
tmp = path + ".tmp"
with open(tmp, "w") as f:
    f.write(json.dumps(state, indent=2, sort_keys=True) + "\n")
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp, path)
PY

echo "initialized milestone $MILESTONE_ID at phase 'init'"
echo "  state file: $STATE_FILE"
