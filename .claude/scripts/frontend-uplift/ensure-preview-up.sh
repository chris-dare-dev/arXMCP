#!/usr/bin/env bash
# Verify the arXMCP operator console is reachable before dispatching the
# visual scout.  Exits 0 on green, 1 on red — the slash command body invokes
# this BEFORE Phase 1 dispatch as a hook-like preflight check.
#
# Usage: ensure-preview-up.sh [host] [port]
# Defaults: host=127.0.0.1, port=7733  (the arXMCP MCP-server bind from
# server/config.py; see also CLAUDE.md §9 "Run the server: make up").
#
# arXMCP NOTE: the operator console is **server-rendered Jinja2 + vendored
# htmx** — there is NO Node / npm / SPA build chain (a CLAUDE.md §4.7 hard
# constraint, recently re-pinned across notebook-surface-expansion m3/m5).
# The same uvicorn process that serves /mcp also serves /ui/, so this
# preflight just verifies that uvicorn is up.

set -euo pipefail

HOST="${1:-127.0.0.1}"
PORT="${2:-7733}"
# Probe /ui/ (the operator-console landing page) rather than / — / on the
# arXMCP server doesn't return HTML; /ui/ is the actual visual surface the
# frontend-uplift visual scout will walk.
URL="http://${HOST}:${PORT}/ui/"

# 3-second timeout, follow redirects, fail on HTTP >= 400.  We only care about
# whether the server responds with something HTML-ish; the visual scout will
# do the deep DOM-level inspection.
if curl --silent --fail --max-time 3 --location --output /dev/null --write-out "%{http_code}" "$URL" 2>/dev/null | grep -qE '^(200|301|302|307|308)$'; then
  echo "[ok] operator console reachable at $URL"
  exit 0
fi

# Red path — emit a copy-paste recovery hint and exit non-zero.
cat <<EOF >&2
[fail] operator console NOT reachable at $URL

Before /frontend-uplift can run its visual scout, the arXMCP server must be
up.  Start it in another terminal:

    make up                  # uvicorn on 127.0.0.1:7733 (FastAPI + Jinja2 + htmx)

The /ui/ surface boots with the server — no separate frontend process exists
(arXMCP forbids a Node/npm build chain by design; see CLAUDE.md §4.7).

Then re-invoke the slash command.  This preflight check runs ONLY before
Phase 1; once the discover phase is past, you may stop the server.
EOF
exit 1
