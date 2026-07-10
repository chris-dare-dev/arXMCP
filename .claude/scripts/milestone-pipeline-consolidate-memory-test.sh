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

echo
echo "consolidate-memory tests: $PASS passed, $FAIL failed"
[[ "$FAIL" -eq 0 ]]
