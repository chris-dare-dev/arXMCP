#!/usr/bin/env bash
# milestone-pipeline-consolidate-memory.sh — keep agent memory bounded (hot/cold).
#
# Agents append to .claude/agent-memory/<agent>/*.md (lessons.md, anti-patterns.md)
# over time. Memory is append-only by design (never truncate blindly); this
# script is the ONE sanctioned place that bounds it. It keeps a small HOT slice
# in each file (the newest entries the agent auto-loads at startup) and moves the
# overflow to a COLD archive (never deletes it) that stays retrievable by grep.
#
# For each memory file it:
#   1. de-duplicates exact-repeat non-blank lines (keeps the first occurrence),
#   2. keeps the leading header (blank / `#...` / `Format:...` lines) verbatim,
#   3. keeps the newest entries that fit BOTH budgets (MAX_BYTES and MAX_LINES),
#   4. appends the older overflow entries to archive/<file>.cold.md.
# Append-only means the newest entries are at the bottom, so the kept slice is
# the tail and the archived overflow is the head-after-header.
#
# HOT  = <agent>/<file>.md            (auto-loaded; bounded)
# COLD = <agent>/archive/<file>.cold.md  (never auto-loaded; grep on demand)
#
# Usage:
#   milestone-pipeline-consolidate-memory.sh <agent>   [--dry-run]
#   milestone-pipeline-consolidate-memory.sh --all      [--dry-run]
#   milestone-pipeline-consolidate-memory.sh --status
#
#   <agent>     consolidate one agent's memory *.md files.
#   --all       consolidate every agent directory under the memory base.
#   --status    report per-agent byte/line counts and flag over-budget files.
#   --dry-run   report what WOULD change without writing.
#
# Env:
#   MAX_BYTES          HOT byte budget per file (default 24000, ~6K tokens).
#   MAX_LINES          HOT line cap per file (default 500; the smaller bound wins).
#   AGENT_MEMORY_ROOT  override the memory base entirely.
#   REPO_ROOT          repo root (else derived via git rev-parse).
#
# The memory base is resolved inline (no workspace tier): AGENT_MEMORY_ROOT
# override -> $REPO_ROOT/.claude/agent-memory -> ./.claude/agent-memory.
#
# MEMORY.md (a curated index, not an append log) and the archive/ subdir are
# never consolidated. ASCII-only output (Windows cp1252-safe). Never commits,
# pushes, or blocks.
#
# NOTE: the upstream --extract-trajectories subcommand is intentionally NOT
# ported here. It is bound to a specific self-improvement roadmap, routes to a
# rectifier target, and needs a trajectory-extraction reference that does not
# exist downstream yet. Port it separately once those land.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAX_BYTES="${MAX_BYTES:-24000}"
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

# -- Memory base resolution (inlined; no external workspace tier) -------------
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
  if [[ -s "$1" ]]; then
    awk 'END { print NR }' "$1"
  else
    echo 0
  fi
}

count_bytes() {
  if [[ -f "$1" ]]; then
    wc -c < "$1" | tr -d '[:space:]'
  else
    echo 0
  fi
}

# Consolidate one memory file: dedup exact repeats, keep header + newest entries
# within MAX_BYTES and MAX_LINES, append the older overflow to the cold archive.
consolidate_file() {
  local file="$1"
  local base dir archive before_b before_l tmp overflow after_b after_l arch_n
  base="$(basename "$file")"
  dir="$(dirname "$file")"
  archive="$dir/archive/${base%.md}.cold.md"
  before_b="$(count_bytes "$file")"
  before_l="$(count_lines "$file")"
  tmp="$file.tmp.$$"
  overflow="$file.cold.$$"
  : > "$overflow"

  # Pass 1: dedup exact-repeat non-blank lines (keep first). Pass 2: split header,
  # keep the newest entries within both budgets, spill the rest to $overflow.
  awk '
    /^[[:space:]]*$/    { print; next }
    /^---[[:space:]]*$/ { print; next }   # never dedup YAML fences (two are identical)
    !seen[$0]++         { print }
  ' "$file" | awk -v maxb="$MAX_BYTES" -v maxl="$MAX_LINES" -v ovf="$overflow" '
    { L[NR] = $0 }
    END {
      n = NR
      h = 0
      # A leading YAML frontmatter block (--- ... ---) is header, so a vault
      # stamper that stamps frontmatter into these tracked files never gets it
      # archived out from under itself.
      if (n >= 1 && L[1] == "---") {
        for (i = 2; i <= n; i++) { if (L[i] == "---") { h = i; break } }
      }
      # Then the leading run of blank / `#...` / `Format:...` lines.
      for (i = h + 1; i <= n; i++) {
        if (L[i] ~ /^[[:space:]]*$/ || L[i] ~ /^#/ || L[i] ~ /^Format:/) h = i
        else break
      }
      b = 0; c = 0; k = n + 1
      for (i = n; i > h; i--) {
        lb = length(L[i]) + 1
        if (c + 1 > maxl || b + lb > maxb) break
        b += lb; c++; k = i
      }
      if (k == n + 1 && n > h) k = n   # always keep at least the newest entry
      for (i = 1; i <= h; i++) print L[i]
      for (i = k; i <= n; i++) print L[i]
      for (i = h + 1; i < k; i++) print L[i] >> ovf
    }
  ' > "$tmp"

  arch_n="$(count_lines "$overflow")"
  after_b="$(count_bytes "$tmp")"
  after_l="$(count_lines "$tmp")"

  if [[ "$DRY_RUN" == "true" ]]; then
    rm -f "$tmp" "$overflow"
    if [[ "$arch_n" -gt 0 || "$after_b" != "$before_b" ]]; then
      printf '  %-40s %sB/%sL -> %sB/%sL, +%s archived (dry-run)\n' \
        "$base" "$before_b" "$before_l" "$after_b" "$after_l" "$arch_n"
    else
      printf '  %-40s %sB/%sL (unchanged, dry-run)\n' "$base" "$before_b" "$before_l"
    fi
    return
  fi

  if cmp -s "$tmp" "$file" && [[ "$arch_n" -eq 0 ]]; then
    rm -f "$tmp" "$overflow"
    printf '  %-40s %sB/%sL (unchanged)\n' "$base" "$before_b" "$before_l"
    return
  fi

  if [[ "$arch_n" -gt 0 ]]; then
    mkdir -p "$dir/archive"
    # Self-ignoring cold store: `*` ignores every archive file (and itself), so the
    # COLD tier is local-only and never versioned — no per-repo .gitignore edits,
    # no commit churn from nightly consolidation. Git honors an untracked .gitignore.
    [[ -f "$dir/archive/.gitignore" ]] || printf '*\n' > "$dir/archive/.gitignore"
    cat "$overflow" >> "$archive"
  fi
  rm -f "$overflow"
  mv "$tmp" "$file"
  printf '  %-40s %sB/%sL -> %sB/%sL, +%s archived\n' \
    "$base" "$before_b" "$before_l" "$after_b" "$after_l" "$arch_n"
}

# Every consolidatable memory file in one agent dir: top-level *.md, minus the
# curated MEMORY.md index (never an append log) and the archive/ subdir.
agent_memory_files() {
  local dir="$1" f
  shopt -s nullglob
  for f in "$dir"/*.md; do
    [[ "$(basename "$f")" == "MEMORY.md" ]] && continue
    printf '%s\n' "$f"
  done
  shopt -u nullglob
}

consolidate_agent() {
  local agent="$1"
  local dir="$MEMORY_BASE/$agent"
  if [[ ! -d "$dir" ]]; then
    echo "warning: no memory directory for agent '$agent' at $dir" >&2
    return
  fi
  echo "agent: $agent (cap ${MAX_BYTES}B / ${MAX_LINES}L)"
  local found="false" f
  while IFS= read -r f; do
    [[ -n "$f" ]] || continue
    found="true"
    consolidate_file "$f"
  done < <(agent_memory_files "$dir")
  [[ "$found" == "true" ]] || echo "  (no consolidatable *.md files)"
}

# -- Status (read-only) ------------------------------------------------------
do_status() {
  if [[ ! -d "$MEMORY_BASE" ]]; then
    echo "no memory base at $MEMORY_BASE"
    return
  fi
  echo "memory base: $MEMORY_BASE (cap ${MAX_BYTES}B / ${MAX_LINES}L)"
  shopt -s nullglob
  local d agent total_b total_l files f fb fl flag
  for d in "$MEMORY_BASE"/*/; do
    agent="$(basename "$d")"
    total_b=0; total_l=0; files=0
    while IFS= read -r f; do
      [[ -n "$f" ]] || continue
      files=$((files + 1))
      fb="$(count_bytes "$f")"; fl="$(count_lines "$f")"
      total_b=$((total_b + fb)); total_l=$((total_l + fl))
    done < <(agent_memory_files "${d%/}")
    [[ "$files" -eq 0 ]] && continue
    flag=""
    { [[ "$total_b" -gt "$MAX_BYTES" ]] || [[ "$total_l" -gt "$MAX_LINES" ]]; } && flag="  OVER CAP"
    printf '  %-32s %sB / %sL across %s file(s)%s\n' \
      "$agent" "$total_b" "$total_l" "$files" "$flag"
  done
  shopt -u nullglob
}

# -- Arg parse ---------------------------------------------------------------
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
      consolidate_agent "$(basename "${d%/}")"
    done
    shopt -u nullglob
    [[ "$any" == "true" ]] || echo "no agent directories under $MEMORY_BASE"
    ;;
  agent)
    consolidate_agent "$AGENT" ;;
esac
