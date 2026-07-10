#!/usr/bin/env bash
# frontend-uplift-mjs-lint.sh — dialect-aware syntax gate for Workflow-tool .mjs scripts.
#
# Why this exists (critique P-1): the Workflow harness wraps a script body in an async
# function, so top-level `return` / `await` are LEGAL in the dialect but ILLEGAL in a bare
# module — `node --check` fails on every healthy *-workflow.mjs, which is why none of them
# has ever been syntax-checked. This lint reproduces the harness wrapping (the one dialect
# difference), then node --checks the wrapper:
#   1. `export const meta` -> `const meta`   (the only export the dialect allows)
#   2. wrap the whole body in `async function __workflow__() { ... }`
#
# FAIL-LOUD posture (milestone round-4 F11): a missing node binary FAILS the lint — it
# never silently passes.
#
# Usage: frontend-uplift-mjs-lint.sh <file.mjs> [more.mjs ...]
#        frontend-uplift-mjs-lint.sh --self-test
set -euo pipefail

command -v node >/dev/null || { echo "FAIL: node binary unavailable — mjs-lint cannot run (do not skip it)" >&2; exit 1; }

lint_one() {
  local f="$1"
  [[ -f "$f" ]] || { echo "FAIL: $f: no such file" >&2; return 1; }
  # Dialect assumption guard: the ONLY export is `export const meta`.
  local other_exports
  # Exact-match the allowed export ('export const meta = …') — a prefix like
  # 'export const metadata' must NOT be excused (round-2 L-2).
  other_exports=$(grep -nE '^export ' "$f" | grep -vE ':export const meta = ' || true)
  if [[ -n "$other_exports" ]]; then
    echo "FAIL: $f: unexpected export(s) — the Workflow dialect allows only 'export const meta':" >&2
    echo "$other_exports" >&2
    return 1
  fi
  # Use a temp DIR with a fixed-name .js inside (node infers CommonJS-script parsing from
  # .js; inside the async wrapper the dialect's top-level return/await are legal).
  # Portability: BSD mktemp accepts `-t prefix` but GNU (the node:20-bookworm CI image)
  # requires X's in the template — pass an explicit template path, valid on both.
  local tmpdir tmp
  tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/mjs-lint.XXXXXXXX")
  tmp="$tmpdir/wrapped.js"
  {
    echo "async function __workflow__() {"
    sed 's/^export const meta/const meta/' "$f"
    echo "}"
  } > "$tmp"
  if node --check "$tmp" 2>"$tmpdir/err"; then
    echo "OK   $f"
    rm -rf "$tmpdir"
    return 0
  fi
  echo "FAIL $f:" >&2
  sed "s|$tmp|$f (wrapped; line numbers offset by +1)|" "$tmpdir/err" >&2
  rm -rf "$tmpdir"
  return 1
}

self_test() {
  local here real fixture rc=0
  here="$(cd "$(dirname "$0")" && pwd)"
  real="$here/frontend-uplift-workflow.mjs"
  if ! lint_one "$real"; then
    echo "SELF-TEST FAIL: healthy $real did not pass" >&2
    rc=1
  fi
  local fdir
  fdir=$(mktemp -d "${TMPDIR:-/tmp}/mjs-lint-fixture.XXXXXXXX")
  fixture="$fdir/broken-workflow.mjs"
  printf 'export const meta = { name: "broken" }\nphase("x")\nreturn {   // unclosed brace\n' > "$fixture"
  if lint_one "$fixture" 2>/dev/null; then
    echo "SELF-TEST FAIL: broken fixture passed the lint" >&2
    rc=1
  else
    echo "ok: broken fixture refused"
  fi
  # A healthy top-level-return fixture must pass (pins the dialect wrapping itself).
  printf 'export const meta = { name: "ok" }\nconst x = await agent("hi")\nreturn { x }\n' > "$fdir/ok-workflow.mjs"
  if ! lint_one "$fdir/ok-workflow.mjs" >/dev/null; then
    echo "SELF-TEST FAIL: healthy top-level-return fixture refused" >&2
    rc=1
  else
    echo "ok: dialect fixture (top-level return/await) accepted"
  fi
  rm -rf "$fdir"
  [[ $rc -eq 0 ]] && echo "frontend-uplift-mjs-lint.sh self-test: all assertions passed"
  return $rc
}

if [[ "${1:-}" == "--self-test" ]]; then
  self_test
  exit $?
fi

[[ $# -ge 1 ]] || { echo "usage: frontend-uplift-mjs-lint.sh <file.mjs> [...] | --self-test" >&2; exit 2; }

rc=0
for f in "$@"; do
  lint_one "$f" || rc=1
done
exit $rc
