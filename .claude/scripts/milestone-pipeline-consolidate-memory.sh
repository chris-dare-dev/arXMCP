#!/usr/bin/env bash
# milestone-pipeline-consolidate-memory.sh — keep agent lesson memory bounded.
#
# Agents append to .claude/agent-memory/<agent>/lessons*.md over time. Memory
# is append-only by design (never truncate blindly); this script is the ONE
# sanctioned place that trims it, by de-duplicating exact-repeat lines and
# capping each file to the newest MAX_LINES lines (append-only means the newest
# lessons are at the bottom, so the tail is what we keep).
#
# Usage:
#   milestone-pipeline-consolidate-memory.sh <agent>   [--dry-run]
#   milestone-pipeline-consolidate-memory.sh --all      [--dry-run]
#   milestone-pipeline-consolidate-memory.sh --status
#
#   <agent>     consolidate one agent's lessons*.md files.
#   --all       consolidate every agent directory under the memory base.
#   --status    report per-agent line counts and flag over-cap files; no writes.
#   --dry-run   report what WOULD change without writing.
#
# Env:
#   MAX_LINES          cap per file (default 500).
#   AGENT_MEMORY_ROOT  override the memory base entirely.
#   REPO_ROOT          repo root (else derived via git rev-parse).
#
# The memory base is resolved inline (no workspace tier): AGENT_MEMORY_ROOT
# override -> $REPO_ROOT/.claude/agent-memory -> ./.claude/agent-memory.
#
# ASCII-only output (Windows cp1252-safe). Never commits, pushes, or blocks.
#
# NOTE: the upstream --extract-trajectories subcommand is intentionally NOT
# ported here. It is bound to a specific self-improvement roadmap, routes to a
# rectifier target, and needs a trajectory-extraction reference that does not
# exist downstream yet. Port it separately once those land.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAX_LINES="${MAX_LINES:-500}"

usage() {
  cat <<EOF >&2
usage: milestone-pipeline-consolidate-memory.sh <agent> [--dry-run]
       milestone-pipeline-consolidate-memory.sh --all    [--dry-run]
       milestone-pipeline-consolidate-memory.sh --status
EOF
  exit 2
}

[[ $# -ge 1 ]] || usage

# ── Memory base resolution (inlined; no external workspace tier) ────────────
resolve_memory_base() {
  if [[ -n "${AGENT_MEMORY_ROOT:-}" ]]; then
    printf '%s\n' "$AGENT_MEMORY_ROOT"
    return
  fi
  local rr=""
  if [[ -n "${REPO_ROOT:-}" ]]; then
    rr="$REPO_ROOT"
  elif rr_try="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)"; then
    rr="$rr_try"
  fi
  if [[ -n "$rr" ]]; then
    printf '%s\n' "$rr/.claude/agent-memory"
    return
  fi
  # Legacy fallback: run relative to the current working directory.
  printf '%s\n' "./.claude/agent-memory"
}

MEMORY_BASE="$(resolve_memory_base)"

count_lines() {
  # Line count that does not undercount a trailing line with no newline.
  if [[ -s "$1" ]]; then
    awk 'END { print NR }' "$1"
  else
    echo 0
  fi
}

# Consolidate a single lessons file: dedup exact-repeat non-blank lines
# (keep first occurrence), then cap to the newest MAX_LINES lines.
consolidate_file() {
  local file="$1"
  local before after tmp
  before="$(count_lines "$file")"
  tmp="$file.tmp.$$"
  awk '
    /^[[:space:]]*$/ { print; next }   # always keep blank lines
    !seen[$0]++       { print }        # keep first occurrence of a non-blank line
  ' "$file" | tail -n "$MAX_LINES" > "$tmp"
  after="$(count_lines "$tmp")"

  if [[ "$DRY_RUN" == "true" ]]; then
    rm -f "$tmp"
    printf '  %-40s %s -> %s lines (dry-run)\n' "$(basename "$file")" "$before" "$after"
    return
  fi
  if [[ "$before" == "$after" ]]; then
    rm -f "$tmp"
    printf '  %-40s %s lines (unchanged)\n' "$(basename "$file")" "$before"
    return
  fi
  mv "$tmp" "$file"
  printf '  %-40s %s -> %s lines\n' "$(basename "$file")" "$before" "$after"
}

# Consolidate every lessons*.md in one agent directory.
consolidate_agent() {
  local agent="$1"
  local dir="$MEMORY_BASE/$agent"
  if [[ ! -d "$dir" ]]; then
    echo "warning: no memory directory for agent '$agent' at $dir" >&2
    return
  fi
  echo "agent: $agent (cap $MAX_LINES)"
  local found="false"
  shopt -s nullglob
  local f
  for f in "$dir"/lessons*.md; do
    found="true"
    consolidate_file "$f"
  done
  shopt -u nullglob
  [[ "$found" == "true" ]] || echo "  (no lessons*.md files)"
}

# ── Status (read-only) ──────────────────────────────────────────────────────
do_status() {
  if [[ ! -d "$MEMORY_BASE" ]]; then
    echo "no memory base at $MEMORY_BASE"
    return
  fi
  echo "memory base: $MEMORY_BASE (cap $MAX_LINES)"
  shopt -s nullglob
  local d f agent total files flag
  for d in "$MEMORY_BASE"/*/; do
    agent="$(basename "$d")"
    total=0
    files=0
    for f in "$d"lessons*.md; do
      files=$((files + 1))
      total=$((total + $(count_lines "$f")))
    done
    if [[ "$files" -eq 0 ]]; then
      continue
    fi
    flag=""
    [[ "$total" -gt "$MAX_LINES" ]] && flag="  OVER CAP"
    printf '  %-32s %s lines across %s file(s)%s\n' "$agent" "$total" "$files" "$flag"
  done
  shopt -u nullglob
}

# ── Arg parse ───────────────────────────────────────────────────────────────
MODE=""
AGENT=""
DRY_RUN="false"
for arg in "$@"; do
  case "$arg" in
    --status) MODE="status" ;;
    --all) MODE="all" ;;
    --dry-run) DRY_RUN="true" ;;
    --extract-trajectories)
      echo "error: --extract-trajectories is not ported in this build." >&2
      echo "       Only cap+dedup (<agent> | --all | --status) is available." >&2
      exit 2 ;;
    -h|--help) usage ;;
    -*) echo "error: unknown flag: $arg" >&2; usage ;;
    *) MODE="agent"; AGENT="$arg" ;;
  esac
done

[[ -n "$MODE" ]] || usage

case "$MODE" in
  status)
    do_status ;;
  all)
    if [[ ! -d "$MEMORY_BASE" ]]; then
      echo "no memory base at $MEMORY_BASE — nothing to consolidate"
      exit 0
    fi
    shopt -s nullglob
    any="false"
    for d in "$MEMORY_BASE"/*/; do
      any="true"
      consolidate_agent "$(basename "$d")"
    done
    shopt -u nullglob
    [[ "$any" == "true" ]] || echo "no agent directories under $MEMORY_BASE"
    ;;
  agent)
    consolidate_agent "$AGENT" ;;
esac
