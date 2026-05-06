#!/usr/bin/env bash
# init-roadmap.sh — idempotent scaffolding for plans/<slug>-roadmap.md.
#
# Usage:
#   init-roadmap.sh <slug> [--title "..."] [--repo-root /path]
#
# Slug format: ^[a-z][a-z0-9-]{2,30}$, must NOT match ^e\d+$ (which would
# collide with EXX_SYY epic IDs in .claude/roadmap/).
#
# Behavior:
#   - If plans/<slug>-roadmap.md does NOT exist: scaffold from the template.
#   - If it EXISTS: parse current populated phases, print resume info, exit 0.
#
# Exit codes: 0 success / resume; 1 actionable failure; 2 input error.

set -euo pipefail

usage() {
    cat <<EOF >&2
usage: init-roadmap.sh <slug> [--title "..."] [--repo-root /path]

  <slug>            roadmap slug; ^[a-z][a-z0-9-]{2,30}$, not ^e\\d+$
  --title TEXT      human-readable title for the roadmap doc
  --repo-root P     override repo-root detection
EOF
    exit 2
}

[[ $# -ge 1 ]] || usage
case "$1" in -h|--help) usage ;; esac

SLUG="$1"; shift
TITLE=""
REPO_ROOT_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --title) TITLE="${2:-}"; shift 2 ;;
        --repo-root) REPO_ROOT_OVERRIDE="${2:-}"; shift 2 ;;
        *) echo "error: unknown arg: $1" >&2; usage ;;
    esac
done

# Slug validation. Two-step: shape, then collision-with-EXX-epic-IDs.
if ! [[ "$SLUG" =~ ^[a-z][a-z0-9-]{2,30}$ ]]; then
    echo "error: slug '$SLUG' does not match ^[a-z][a-z0-9-]{2,30}$" >&2
    echo "       must start with a lowercase letter, 3-31 chars, lowercase/digits/hyphens." >&2
    exit 2
fi
if [[ "$SLUG" =~ ^e[0-9]+$ ]]; then
    echo "error: slug '$SLUG' looks like an EXX epic ID; pick a descriptive slug." >&2
    exit 2
fi

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
PLANS_DIR="$REPO_ROOT_RESOLVED/plans"
ROADMAP_FILE="$PLANS_DIR/$SLUG-roadmap.md"
TEMPLATE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../references/templates/roadmap.md"

[[ -f "$TEMPLATE" ]] || { echo "error: template not found at $TEMPLATE" >&2; exit 1; }

# Idempotent re-run: file exists → diagnose state, exit 0.
if [[ -f "$ROADMAP_FILE" ]]; then
    echo "roadmap '$SLUG' already exists at $ROADMAP_FILE"
    # Detect populated phases via the explicit `<!-- status: pending -->`
    # sentinel: each phase orchestrator deletes this line when it writes
    # content. Sentinel present = phase still pending.
    populated=()
    pending=()
    for phase in "Refine" "Decompose" "Sequence" "Materialize"; do
        body=$(awk -v p="$phase" '
            $0 ~ "^## Phase [0-9]+ — " p { in_phase=1; next }
            /^## Phase / && in_phase { exit }
            in_phase { print }
        ' "$ROADMAP_FILE")
        if printf '%s\n' "$body" | grep -qE '^<!-- status: pending -->'; then
            pending+=("$phase")
        else
            populated+=("$phase")
        fi
    done
    if [[ ${#populated[@]} -gt 0 ]]; then
        echo "  populated: ${populated[*]}"
    else
        echo "  populated: (none)"
    fi
    if [[ ${#pending[@]} -gt 0 ]]; then
        echo "  next phase: ${pending[0]}"
    else
        echo "  all phases populated — run validate-roadmap.py to lint"
    fi
    exit 0
fi

# Fresh scaffold.
mkdir -p "$PLANS_DIR"
[[ -n "$TITLE" ]] || TITLE="$SLUG"
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Use python for safe substitution (handles arbitrary chars in TITLE).
TEMPLATE="$TEMPLATE" ROADMAP_FILE="$ROADMAP_FILE" SLUG="$SLUG" TITLE="$TITLE" NOW="$NOW" \
python3 <<'PY'
import os
src = open(os.environ["TEMPLATE"]).read()
out = (src
       .replace("{{TITLE}}", os.environ["TITLE"])
       .replace("{{SLUG}}", os.environ["SLUG"])
       .replace("{{CREATED}}", os.environ["NOW"]))
tmp = os.environ["ROADMAP_FILE"] + ".tmp"
with open(tmp, "w") as f:
    f.write(out)
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp, os.environ["ROADMAP_FILE"])
PY

echo "scaffolded roadmap '$SLUG' at $ROADMAP_FILE"
echo "  next phase: Refine"
