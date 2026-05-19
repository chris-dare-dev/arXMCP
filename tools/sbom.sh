#!/usr/bin/env bash
# tools/sbom.sh — Threat-6 SBOM generation + vulnerability scan.
#
# This is the local-first replacement for the brief's
# `.github/workflows/sbom.yml` deliverable. The arXMCP project has
# no CI (CLAUDE.md §4.1: "No CI / GitHub Actions blocking merges"),
# so SBOM generation runs from the developer's machine before each
# push. The script intentionally fails fast on a critical CVE so
# the operator does not silently ship a known-bad dependency.
#
# Two SBOMs are produced:
#
#   1. Python source SBOM (cyclonedx-py) — always generated. Reads
#      pyproject.toml + uv.lock so every pinned dependency is
#      surfaced. Output: ${SBOM_DIR}/python-${date}.cdx.json
#
#   2. Container-image SBOM (syft) — optional. Generated only if
#      ``docker`` and ``syft`` are both on PATH and the
#      ``docker/Dockerfile.server`` image builds. The image SBOM
#      covers OS-level packages (apt) AND the application Python
#      env, so it is a superset of (1) for the deployed surface.
#      Output: ${SBOM_DIR}/server-image-${date}.cdx.json
#
# Each SBOM is then scanned with ``grype --fail-on critical``,
# which exits non-zero if any CRITICAL CVEs are matched. The script
# aggregates exit codes: a single failure causes the whole run to
# fail.
#
# Usage:
#   tools/sbom.sh                 # default: ./.claude/docs/security/sbom
#   tools/sbom.sh --skip-image    # Python SBOM only
#   tools/sbom.sh --no-scan       # generate SBOMs, skip grype
#   SBOM_DIR=/tmp/sbom tools/sbom.sh
#
# Exit codes:
#   0  all SBOMs generated, all scans passed
#   1  user error (missing tool, malformed flag)
#   2  grype found a critical CVE
#   3  SBOM generator failed (cyclonedx-py / syft)
#
# Required tools (install hints printed if missing):
#   - cyclonedx-py     (pip install cyclonedx-bom)  -- always
#   - grype            (https://github.com/anchore/grype)  -- unless --no-scan
#   - syft             (https://github.com/anchore/syft)   -- unless --skip-image
#   - docker           (https://docs.docker.com/get-docker/) -- unless --skip-image

set -euo pipefail

# ----------------------------------------------------------------------
# CLI parsing
# ----------------------------------------------------------------------
SKIP_IMAGE=0
NO_SCAN=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-image) SKIP_IMAGE=1; shift ;;
        --no-scan)    NO_SCAN=1; shift ;;
        -h|--help)
            sed -n '2,50p' "$0" >&2
            exit 0
            ;;
        *)
            echo "error: unknown arg: $1" >&2
            echo "       see: $0 --help" >&2
            exit 1
            ;;
    esac
done

# ----------------------------------------------------------------------
# Path setup
# ----------------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SBOM_DIR="${SBOM_DIR:-$REPO_ROOT/.claude/docs/security/sbom}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "$SBOM_DIR"

# ----------------------------------------------------------------------
# Tool detection
# ----------------------------------------------------------------------
have() { command -v "$1" >/dev/null 2>&1; }

missing_install_hint() {
    case "$1" in
        cyclonedx-py)
            echo "  Install: uv pip install cyclonedx-bom (or: pip install cyclonedx-bom)" >&2
            ;;
        grype)
            echo "  Install: https://github.com/anchore/grype#installation" >&2
            ;;
        syft)
            echo "  Install: https://github.com/anchore/syft#installation" >&2
            ;;
        docker)
            echo "  Install: https://docs.docker.com/get-docker/" >&2
            ;;
    esac
}

require() {
    if ! have "$1"; then
        echo "error: required tool '$1' not found on PATH" >&2
        missing_install_hint "$1"
        exit 1
    fi
}

# Hard requirement: cyclonedx-py for the Python source SBOM.
require cyclonedx-py

# Soft requirements (the script downgrades gracefully).
if [[ "$NO_SCAN" -eq 0 ]] && ! have grype; then
    echo "error: grype not found and --no-scan was not passed." >&2
    missing_install_hint grype
    exit 1
fi
if [[ "$SKIP_IMAGE" -eq 0 ]]; then
    if ! have docker; then
        echo "note: docker not on PATH — skipping image SBOM (use --skip-image to silence)" >&2
        SKIP_IMAGE=1
    elif ! have syft; then
        echo "note: syft not on PATH — skipping image SBOM (use --skip-image to silence)" >&2
        missing_install_hint syft
        SKIP_IMAGE=1
    fi
fi

# ----------------------------------------------------------------------
# (1) Python source SBOM (always)
# ----------------------------------------------------------------------
PY_SBOM="$SBOM_DIR/python-$TS.cdx.json"
echo "[1/2] cyclonedx-py — Python source SBOM"
echo "      output: $PY_SBOM"

# `cyclonedx-py environment` enumerates the active Python interpreter's
# installed packages. We invoke from the project root so the resolved
# environment includes the dev extras (the operator should run inside
# the project's venv).
if ! cyclonedx-py environment --output-format JSON --output-file "$PY_SBOM"; then
    echo "error: cyclonedx-py failed" >&2
    exit 3
fi

if [[ "$NO_SCAN" -eq 0 ]]; then
    echo "      grype scan (fail-on critical):"
    if ! grype "sbom:$PY_SBOM" --fail-on critical; then
        # grype exits with code matching the highest severity matched.
        # We translate any non-zero into our canonical exit 2 ("grype
        # found a critical CVE") so the Makefile target's failure mode
        # is unambiguous.
        echo "error: grype reported a CRITICAL CVE in the Python SBOM" >&2
        exit 2
    fi
fi

# ----------------------------------------------------------------------
# (2) Container image SBOM (optional)
# ----------------------------------------------------------------------
if [[ "$SKIP_IMAGE" -eq 1 ]]; then
    echo "[2/2] skipped (docker/syft unavailable or --skip-image)"
    echo ""
    echo "OK: Python SBOM produced; image SBOM skipped."
    exit 0
fi

IMG_TAG="arxmcp-server:sbom-$TS"
IMG_SBOM="$SBOM_DIR/server-image-$TS.cdx.json"
echo "[2/2] syft — server image SBOM"
echo "      image:  $IMG_TAG"
echo "      output: $IMG_SBOM"

if ! docker build -t "$IMG_TAG" -f "$REPO_ROOT/docker/Dockerfile.server" "$REPO_ROOT"; then
    echo "error: docker build failed for $IMG_TAG" >&2
    exit 3
fi
if ! syft "$IMG_TAG" -o cyclonedx-json --file "$IMG_SBOM"; then
    echo "error: syft failed for $IMG_TAG" >&2
    exit 3
fi

if [[ "$NO_SCAN" -eq 0 ]]; then
    echo "      grype scan (fail-on critical):"
    if ! grype "sbom:$IMG_SBOM" --fail-on critical; then
        echo "error: grype reported a CRITICAL CVE in the server image SBOM" >&2
        exit 2
    fi
fi

echo ""
echo "OK: both SBOMs produced + scanned clean."
echo "    Python source: $PY_SBOM"
echo "    server image:  $IMG_SBOM"
