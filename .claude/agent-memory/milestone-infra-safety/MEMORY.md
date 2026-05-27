## 2026-05-17 — E13_S03 — deploy-resources-swarm-only

`deploy.resources.limits` in docker-compose files is a Swarm-only construct — it is
silently ignored by standalone `docker compose` (Compose v2). The correct top-level
keys for standalone compose are `mem_limit` and `cpus`. The project's existing
`infra/observability/phoenix-compose.yml` uses the correct form (lines 124-125) and
serves as the canonical pattern reference. Flag `deploy.resources.limits` as HIGH
whenever it appears in a compose file documented as standalone (not Swarm).

## 2026-05-17 — E13_S03 — sandbox-exec-home-read-credential-surface

A macOS `sandbox-exec` profile that uses `(allow file-read* (subpath (param "HOME")))`
exposes `~/.ssh/`, `~/.aws/credentials`, `~/.gnupg/` to the sandboxed process.
Even with `(deny network*)`, a hostile LaTeX fixture can read credentials into the
LaTeXML output stream and write them to OUTPUT_DIR. Severity: MEDIUM (network-deny
prevents direct exfiltration, but the output artifact is on the host). Mitigation:
narrow HOME reads to specific Perl/CPAN sub-paths, or add explicit denies for
credential directories before the broad HOME allowance.

## 2026-05-22 — E13_S07c — makefile-mv-orphan-tempfile

In Makefile recipes that use a temp file + atomic `mv` pattern, the `mv` line itself
needs an `|| { rm -f $$tmp; exit 1; }` guard. Without it, a permissions failure on
`mv` leaves the temp file on disk (resource/info leak) and the recipe's exit code
may not clearly communicate the failure. The curl-download + openssl-verify + mv
pattern is a recurring infra idiom in arXMCP; always guard all three steps.

## 2026-05-17 — E13_S03 — compose-relative-path-resolves-to-compose-dir

In Compose v2, relative paths in bind-mount `source:` resolve relative to the
COMPOSE FILE's directory, not the operator's CWD. A default fallback like
`./latexml-output` placed in `infra/latexml/docker-compose.latexml.yml` would
write output to `infra/latexml/latexml-output/`, polluting the repo tree. Use
`../../var/arxmcp/...` to walk back to repo root, matching the phoenix-compose.yml
precedent (phoenix-compose.yml:94).

## 2026-05-22 — E14_Tier5plus — grafana-localhost-container-networking

When a Grafana provisioning YAML hardcodes `url: http://localhost:9090` for a
Prometheus datasource, the URL resolves to the Grafana container's own loopback if
Grafana runs in Docker (the dominant operator pattern). Prometheus is unreachable;
panels show "No data" silently. Fix: add a comment noting `host.docker.internal:9090`
as the macOS/Windows Docker Desktop alternative, or use an env-var default
`${PROMETHEUS_URL:-http://localhost:9090}`. Severity: MEDIUM (foot-gun, not
data-loss). Applies to any provisioning YAML shipped without an accompanying
docker-compose that co-locates Grafana + Prometheus in the same network.

## 2026-05-27 — embedder-truncation-m1 — makefile-args-spaces-warning-consistency

When a new `make` target forwards `$(ARGS)` to a Python `-m` driver, check whether
the recipe includes the standard `@# NOTE on ARGS: paths inside ARGS must not contain
spaces` warning comment. In arXMCP, every path-bearing `$(ARGS)` target (`ingest`,
`re-embed`, `watchdog`, `cutover`) carries this comment. A target that forwards
`$(ARGS)` but lacks the warning is MEDIUM even if today's driver has no path-bearing
flags — the comment is a forward-contract for future maintainers.

## 2026-05-22 — E14_Tier5plus — grafana-provisioning-combined-yaml-safe-if-mounted-not-split

A Grafana provisioning YAML that contains BOTH `datasources:` and `providers:` blocks
under a single `apiVersion: 1` can be safely mounted to BOTH provisioning subdirectories
(`datasources/` and `dashboards/`) — Grafana ignores unknown top-level keys when reading
from each subdir. However, if an operator naively "splits" the file by extracting only
the `providers:` section, the resulting dashboards file will lack `apiVersion: 1` and
Grafana will reject it. YAML comments should say "mount at both paths" not "split."
