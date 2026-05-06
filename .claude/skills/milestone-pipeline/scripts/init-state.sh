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
usage: init-state.sh <ID> [--brief "text"] [--brief-from /path/to/file.md] [--repo-root /path]

  <ID>             milestone identifier (e.g. E01_S01 or citation-graph-m1)
  --brief TEXT     inline milestone brief (overrides any disk lookup)
  --brief-from P   explicit path to a markdown file with '### <ID> — Title'
                   (overrides auto-discovery; useful for archived plans
                   or non-default locations)
  --repo-root P    override repo-root detection

Auto-discovery searches BOTH .claude/roadmap/*.md and plans/*.md for a
'### <ID> — ' heading. On collision (same ID in both) the script exits
1 with both paths printed.
EOF
    exit 2
}

[[ $# -ge 1 ]] || usage
case "$1" in -h|--help) usage ;; esac

MILESTONE_ID="$1"; shift
BRIEF=""
BRIEF_FROM=""
REPO_ROOT_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --brief) BRIEF="${2:-}"; shift 2 ;;
        --brief-from) BRIEF_FROM="${2:-}"; shift 2 ;;
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

# Resolve brief. Priority: --brief (inline) > --brief-from (explicit path) >
# auto-discovery in .claude/roadmap/ AND plans/. On collision (same ID found
# in both directories) fail loudly with both paths so the user resolves the
# ambiguity at planning time, not as a debugging mystery later.
BRIEF_SOURCE=""

if [[ -z "$BRIEF" && -n "$BRIEF_FROM" ]]; then
    if [[ ! -f "$BRIEF_FROM" ]]; then
        echo "error: --brief-from path not found: $BRIEF_FROM" >&2
        exit 1
    fi
    BRIEF=$(awk -v id="$MILESTONE_ID" '
        $0 ~ "^### " id " " { printing=1; print; next }
        printing && /^### / { exit }
        printing { print }
    ' "$BRIEF_FROM")
    if [[ -z "$BRIEF" ]]; then
        echo "error: no '### $MILESTONE_ID — ' heading found in $BRIEF_FROM" >&2
        exit 1
    fi
    BRIEF_SOURCE="$BRIEF_FROM"
fi

if [[ -z "$BRIEF" ]]; then
    SEARCH_DIRS=()
    [[ -d "$REPO_ROOT_RESOLVED/.claude/roadmap" ]] && SEARCH_DIRS+=("$REPO_ROOT_RESOLVED/.claude/roadmap")
    [[ -d "$REPO_ROOT_RESOLVED/plans" ]] && SEARCH_DIRS+=("$REPO_ROOT_RESOLVED/plans")

    HITS=()
    for dir in "${SEARCH_DIRS[@]}"; do
        block=$(awk -v id="$MILESTONE_ID" '
            $0 ~ "^### " id " " { printing=1; print; next }
            printing && /^### / { exit }
            printing { print }
        ' "$dir"/*.md 2>/dev/null || true)
        if [[ -n "$block" ]]; then
            HITS+=("$dir")
            BRIEF="$block"
            BRIEF_SOURCE="$dir"
        fi
    done

    if [[ ${#HITS[@]} -gt 1 ]]; then
        echo "error: milestone ID '$MILESTONE_ID' found in multiple sources:" >&2
        for h in "${HITS[@]}"; do echo "         - $h" >&2; done
        echo "       resolve by passing --brief-from <path> explicitly, or by renaming one." >&2
        exit 1
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
BRIEF="$BRIEF" BRIEF_SOURCE="$BRIEF_SOURCE" MILESTONE_ID="$MILESTONE_ID" NOW="$NOW" STATE_FILE="$STATE_FILE" \
python3 <<'PY'
import json, os, sys
state = {
    "id": os.environ["MILESTONE_ID"],
    "created_at": os.environ["NOW"],
    "updated_at": os.environ["NOW"],
    "phase": "init",
    "phase_history": [{"phase": "init", "entered_at": os.environ["NOW"], "left_at": None}],
    "milestone_brief": os.environ.get("BRIEF", ""),
    "brief_source": os.environ.get("BRIEF_SOURCE", ""),
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
