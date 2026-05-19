# Critique — E13_S06

**Critic:** infra-safety
**Generated:** 2026-05-18T21:15:00Z
**Commit range:** f5359286690225413158c631e59aee986afd542e..02278ae1a3cd0bf433f679cc835e0872ddcbde3c
**Verdict:** SHIP

## Executive summary

- Verdict: **SHIP**. All infra-safety axes clean. The `make sbom` Makefile target and `tools/sbom.sh` script are correctly implemented with proper error handling, idempotence, and no destructive operations.
- Finding counts: **0 CRITICAL, 0 HIGH, 0 MEDIUM, 0 LOW**
- Only changed infra path: `Makefile` (added `sbom` target and `.PHONY` entry)
- Container hygiene: N/A (no Dockerfile changes)
- docker-compose correctness: N/A (no docker-compose changes)
- CI workflow safety: N/A (project rule: no CI). Makefile target is correctly positioned as local-only developer tool.
- Build script discipline: all four axes clean — idempotent, no sudo, no destructive defaults, exit codes propagate, `.PHONY` updated, help text present.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

(None.)

## What was done well

- **Idempotent target design** — The `sbom` target uses a timestamp-suffixed output filename pattern (`python-$TS.cdx.json`, `server-image-$TS.cdx.json`) with `set -euo pipefail`, making re-runs safe and non-destructive (lines 47, 75 of `tools/sbom.sh`).
- **Graceful tool degradation** — The script checks for required tools (`cyclonedx-py`) and soft dependencies (`docker`, `syft`, `grype`) with clear install hints (lines 80–127). Missing `docker` or `syft` downgrades to Python-only SBOM; missing `grype` allows `--no-scan` override.
- **Proper exit-code discipline** — Exit codes propagate from external tools (`cyclonedx-py`, `docker build`, `syft`, `grype`) and are mapped to canonical codes (0=OK, 1=user error, 2=CVE found, 3=generator failure). Script uses `if ! ... then exit N; fi` pattern (lines 140–155, 173–187).
- **Path handling with spaces** — All variable expansions are properly quoted (e.g., `"$SBOM_DIR"`, `"$REPO_ROOT"`, `"$IMG_SBOM"`), allowing the script to work on paths like `/c/Users/cedar/Documents/Personal Projects/Source Code/arXMCP`.
- **`.PHONY` list updated and help text present** — The `sbom` target was correctly added to `.PHONY` (line 1 of Makefile) and documented in `make help` (line 21). Operators can discover the target via `make help`.
- **Timestamp format avoids Windows incompatibilities** — Uses `date -u +%Y%m%dT%H%M%SZ` (line 75), which produces colons only in the timezone part (`Z`), avoiding Windows filename restrictions on colons in filenames.
- **`.gitignore` correctly excludes SBOM artifacts** — Both `.cdx.json` and `.json` patterns exclude raw SBOM outputs, keeping multi-MB artifacts out of the repository while documenting the justification in a comment.

## Recommended rectification order

(No findings; no rectifications required.)

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
