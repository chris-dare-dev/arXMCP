#!/usr/bin/env bash
# Bulk download (E11_S01) — operator stub.
#
# This is a SCAFFOLDING script. The actual ~300 GB Academic Torrents
# download is intentionally NOT automated — the operator runs it
# manually after verifying disk space, network bandwidth, and the
# current valid magnet link. See docs/ops/bulk-ingest-runbook.md.
#
# What this script does:
#   1. Verify `aria2c` is on PATH.
#   2. Print the operator workflow.
#   3. Exit 0 (no download initiated).
#
# What the operator should do AFTER running this script:
#   1. Visit https://academictorrents.com/browse.php?search=arxiv
#      and find the current arXiv source magnet link (the magnet
#      changes when new dumps are released).
#   2. `aria2c --file-allocation=none --seed-ratio=0 <magnet>`
#      (uses ~300-1500 GB depending on which torrent).
#   3. Extract per-paper .tar.gz tarballs into
#      var/arxmcp/corpus/raw/<paper_id>/.
#   4. Run `tools/arxiv_fetch.py` (or future per-paper LaTeXML
#      driver) to produce parsed HTML under
#      var/arxmcp/corpus/parsed/<paper_id>/index.html.
#   5. `make ingest ARGS="--paper-ids-file=<list>.txt"` to chunk +
#      embed + write to the staging LanceDB.

set -euo pipefail

if ! command -v aria2c >/dev/null 2>&1; then
    cat >&2 <<'EOF'
ERROR: aria2c not found on PATH.
Install:
  macOS:           brew install aria2
  Debian/Ubuntu:   apt install aria2

aria2c is the recommended BitTorrent client for the Academic
Torrents arXiv source dump (~300 GB for math.AG + math.NT +
math-ph + hep-th).
EOF
    exit 1
fi

cat <<'EOF'
OPERATOR WORKFLOW

Per docs/ops/bulk-ingest-runbook.md, the Academic Torrents
download is run manually:

  1. Find the current magnet link at
     https://academictorrents.com/browse.php?search=arxiv
  2. aria2c --file-allocation=none --seed-ratio=0 '<magnet>'
  3. Extract per-paper tarballs into var/arxmcp/corpus/raw/
  4. Parse with LaTeXML (operator's own driver) into
     var/arxmcp/corpus/parsed/<paper_id>/index.html
  5. make ingest ARGS="--paper-ids-file=<list>.txt"

This script intentionally does not automate the download. Disk
space (~300 GB), bandwidth, and the magnet-link freshness all
deserve operator review before the multi-hour transfer begins.
EOF
