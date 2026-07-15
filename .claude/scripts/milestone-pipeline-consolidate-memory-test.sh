#!/usr/bin/env bash
# milestone-pipeline-consolidate-memory-test.sh — harness for the cap+dedup+status core.
#
# Run: bash milestone-pipeline-consolidate-memory-test.sh   (exit 0 == all pass)
#
# Exercises ONLY the ported subcommands (<agent> | --all | --status) plus
# --dry-run. No trajectory-extraction tests (that subcommand is not ported).
# Uses AGENT_MEMORY_ROOT to point the script at a throwaway tree, so it never
# touches a real repo's memory.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNDER_TEST="$SCRIPT_DIR/milestone-pipeline-consolidate-memory.sh"

PASS=0
FAIL=0
check() {
  # check <name> <condition-exit-status>
  if [[ "$2" -eq 0 ]]; then
    PASS=$((PASS + 1))
    echo "  ok   $1"
  else
    FAIL=$((FAIL + 1))
    echo "  FAIL $1"
  fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export AGENT_MEMORY_ROOT="$TMP"

count_lines() { awk 'END { print NR }' "$1"; }

# ── Fixture: agent "alpha" with duplicate + overflow lines ──────────────────
mkdir -p "$AGENT_MEMORY_ROOT/alpha"
cat > "$AGENT_MEMORY_ROOT/alpha/lessons.md" <<'EOF'
- dup
- dup
- dup
- l1
- l2
- l3
- l4
- l5
- l6
EOF

# ── Fixture: agent "beta" with pure duplicates, no overflow ─────────────────
mkdir -p "$AGENT_MEMORY_ROOT/beta"
cat > "$AGENT_MEMORY_ROOT/beta/lessons.md" <<'EOF'
- keep me
- keep me
- keep me
- other
EOF

# ── Test 1: cap keeps newest MAX_LINES after dedup ──────────────────────────
MAX_LINES=5 bash "$UNDER_TEST" alpha >/dev/null 2>&1
n="$(count_lines "$AGENT_MEMORY_ROOT/alpha/lessons.md")"
check "alpha capped to 5 lines (got $n)" "$([[ "$n" -eq 5 ]]; echo $?)"
check "alpha newest line (- l6) retained" \
  "$(grep -qxF -e '- l6' "$AGENT_MEMORY_ROOT/alpha/lessons.md"; echo $?)"
check "alpha oldest line (- l1) dropped by cap" \
  "$(! grep -qxF -e '- l1' "$AGENT_MEMORY_ROOT/alpha/lessons.md"; echo $?)"

# ── Test 2: dedup with a generous cap collapses exact repeats ───────────────
MAX_LINES=100 bash "$UNDER_TEST" beta >/dev/null 2>&1
dups="$(grep -cxF -e '- keep me' "$AGENT_MEMORY_ROOT/beta/lessons.md")"
n="$(count_lines "$AGENT_MEMORY_ROOT/beta/lessons.md")"
check "beta deduped '- keep me' to 1 (got $dups)" "$([[ "$dups" -eq 1 ]]; echo $?)"
check "beta total lines now 2 (got $n)" "$([[ "$n" -eq 2 ]]; echo $?)"

# ── Test 3: --dry-run does NOT modify the file ──────────────────────────────
mkdir -p "$AGENT_MEMORY_ROOT/gamma"
printf -- '- a\n- a\n- b\n' > "$AGENT_MEMORY_ROOT/gamma/lessons.md"
before="$(count_lines "$AGENT_MEMORY_ROOT/gamma/lessons.md")"
MAX_LINES=100 bash "$UNDER_TEST" gamma --dry-run >/dev/null 2>&1
after="$(count_lines "$AGENT_MEMORY_ROOT/gamma/lessons.md")"
check "gamma unchanged by --dry-run ($before==$after)" \
  "$([[ "$before" -eq "$after" ]]; echo $?)"

# ── Test 4: --status is read-only and reports agents ────────────────────────
before_g="$(count_lines "$AGENT_MEMORY_ROOT/gamma/lessons.md")"
out="$(MAX_LINES=100 bash "$UNDER_TEST" --status 2>&1)"
after_g="$(count_lines "$AGENT_MEMORY_ROOT/gamma/lessons.md")"
check "--status lists agent alpha" "$(echo "$out" | grep -q 'alpha'; echo $?)"
check "--status left gamma untouched" "$([[ "$before_g" -eq "$after_g" ]]; echo $?)"

# ── Test 5: --status OVER CAP flag fires ────────────────────────────────────
mkdir -p "$AGENT_MEMORY_ROOT/big"
seq 1 20 | sed 's/^/- lesson /' > "$AGENT_MEMORY_ROOT/big/lessons.md"
out="$(MAX_LINES=5 bash "$UNDER_TEST" --status 2>&1)"
check "--status flags 'big' OVER CAP" \
  "$(echo "$out" | grep 'big' | grep -q 'OVER CAP'; echo $?)"

# ── Test 6: --all consolidates every agent ──────────────────────────────────
MAX_LINES=5 bash "$UNDER_TEST" --all >/dev/null 2>&1
n="$(count_lines "$AGENT_MEMORY_ROOT/big/lessons.md")"
check "--all capped 'big' to 5 (got $n)" "$([[ "$n" -eq 5 ]]; echo $?)"

# ── Test 7: unknown agent warns, exits without a crash ──────────────────────
bash "$UNDER_TEST" no-such-agent >/dev/null 2>&1
check "unknown agent exits 0 (advisory)" "$?"

# ── Test 8: --extract-trajectories is refused (not ported) ──────────────────
bash "$UNDER_TEST" --extract-trajectories >/dev/null 2>&1
check "--extract-trajectories refused (exit 2)" "$([[ "$?" -eq 2 ]]; echo $?)"

# ── Test 9: MAX_BYTES caps by byte budget + archives overflow (not deletes) ──
mkdir -p "$AGENT_MEMORY_ROOT/bytecap"
pad="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"   # 40 chars
: > "$AGENT_MEMORY_ROOT/bytecap/lessons.md"
for i in 1 2 3 4 5 6; do echo "entry-$i $pad" >> "$AGENT_MEMORY_ROOT/bytecap/lessons.md"; done
MAX_BYTES=120 MAX_LINES=100 bash "$UNDER_TEST" bytecap >/dev/null 2>&1
hot_b="$(wc -c < "$AGENT_MEMORY_ROOT/bytecap/lessons.md" | tr -d '[:space:]')"
check "bytecap HOT within byte budget (got ${hot_b}B <= 120)" "$([[ "$hot_b" -le 120 ]]; echo $?)"
check "bytecap newest entry-6 retained in HOT" \
  "$(grep -q 'entry-6' "$AGENT_MEMORY_ROOT/bytecap/lessons.md"; echo $?)"
check "bytecap oldest entry-1 ARCHIVED (not deleted)" \
  "$(grep -q 'entry-1' "$AGENT_MEMORY_ROOT/bytecap/archive/lessons.cold.md"; echo $?)"
check "bytecap entry-1 removed from HOT" \
  "$(! grep -q 'entry-1' "$AGENT_MEMORY_ROOT/bytecap/lessons.md"; echo $?)"

# ── Test 10: every memory *.md is covered (anti-patterns.md, not just lessons) ─
mkdir -p "$AGENT_MEMORY_ROOT/multi"
printf -- '- a1\n- a2\n- a3\n' > "$AGENT_MEMORY_ROOT/multi/lessons.md"
printf -- '- p1\n- p2\n- p3\n' > "$AGENT_MEMORY_ROOT/multi/anti-patterns.md"
MAX_LINES=1 bash "$UNDER_TEST" multi >/dev/null 2>&1
check "multi: lessons.md capped to 1 (got $(count_lines "$AGENT_MEMORY_ROOT/multi/lessons.md"))" \
  "$([[ "$(count_lines "$AGENT_MEMORY_ROOT/multi/lessons.md")" -eq 1 ]]; echo $?)"
check "multi: anti-patterns.md ALSO capped to 1 (got $(count_lines "$AGENT_MEMORY_ROOT/multi/anti-patterns.md"))" \
  "$([[ "$(count_lines "$AGENT_MEMORY_ROOT/multi/anti-patterns.md")" -eq 1 ]]; echo $?)"
check "multi: anti-patterns cold archive created" \
  "$(test -f "$AGENT_MEMORY_ROOT/multi/archive/anti-patterns.cold.md"; echo $?)"

# ── Test 11: MEMORY.md (curated index) is never consolidated ─────────────────
mkdir -p "$AGENT_MEMORY_ROOT/idx"
seq 1 20 | sed 's/^/- x /' > "$AGENT_MEMORY_ROOT/idx/MEMORY.md"
before_i="$(count_lines "$AGENT_MEMORY_ROOT/idx/MEMORY.md")"
MAX_LINES=5 bash "$UNDER_TEST" idx >/dev/null 2>&1
after_i="$(count_lines "$AGENT_MEMORY_ROOT/idx/MEMORY.md")"
check "MEMORY.md index left untouched ($before_i==$after_i)" \
  "$([[ "$before_i" -eq "$after_i" ]]; echo $?)"

# ── Test 12: leading header (#/Format/blank) is preserved in HOT ─────────────
mkdir -p "$AGENT_MEMORY_ROOT/hdr"
{ echo "# Title"; echo ""; echo "Format: x"; echo ""; for i in 1 2 3 4 5; do echo "- e$i"; done; } \
  > "$AGENT_MEMORY_ROOT/hdr/lessons.md"
MAX_LINES=2 bash "$UNDER_TEST" hdr >/dev/null 2>&1
check "hdr: '# Title' header retained" \
  "$(grep -qxF '# Title' "$AGENT_MEMORY_ROOT/hdr/lessons.md"; echo $?)"
check "hdr: 'Format: x' header retained" \
  "$(grep -qxF 'Format: x' "$AGENT_MEMORY_ROOT/hdr/lessons.md"; echo $?)"
check "hdr: newest '- e5' retained, oldest '- e1' archived" \
  "$(grep -qxF -- '- e5' "$AGENT_MEMORY_ROOT/hdr/lessons.md" \
     && grep -qxF -- '- e1' "$AGENT_MEMORY_ROOT/hdr/archive/lessons.cold.md"; echo $?)"

# ── Test 13: leading YAML frontmatter (---...---) is preserved, not archived ──
mkdir -p "$AGENT_MEMORY_ROOT/fm"
{ echo "---"; echo "type: memory"; echo "---"; echo "# Title"; echo ""; \
  for i in 1 2 3 4 5; do echo "- e$i"; done; } > "$AGENT_MEMORY_ROOT/fm/lessons.md"
MAX_LINES=2 bash "$UNDER_TEST" fm >/dev/null 2>&1
check "fm: frontmatter 'type: memory' retained in HOT" \
  "$(grep -qxF 'type: memory' "$AGENT_MEMORY_ROOT/fm/lessons.md"; echo $?)"
check "fm: frontmatter not spilled to cold archive" \
  "$(! grep -qxF 'type: memory' "$AGENT_MEMORY_ROOT/fm/archive/lessons.cold.md" 2>/dev/null; echo $?)"
check "fm: newest '- e5' retained, oldest '- e1' archived" \
  "$(grep -qxF -- '- e5' "$AGENT_MEMORY_ROOT/fm/lessons.md" \
     && grep -qxF -- '- e1' "$AGENT_MEMORY_ROOT/fm/archive/lessons.cold.md"; echo $?)"

# ── Test 14: the cold archive is self-ignoring (archive/.gitignore = '*') ────
check "archive is self-ignoring (archive/.gitignore == '*')" \
  "$([[ -f "$AGENT_MEMORY_ROOT/bytecap/archive/.gitignore" ]] \
     && [[ "$(cat "$AGENT_MEMORY_ROOT/bytecap/archive/.gitignore")" == '*' ]]; echo $?)"

echo
echo "consolidate-memory tests: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
