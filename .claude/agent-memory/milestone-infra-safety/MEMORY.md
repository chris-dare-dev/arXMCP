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
