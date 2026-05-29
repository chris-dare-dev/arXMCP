# Critique — notebook-ops-hardening-m3

**Critic:** infra-safety
**Generated:** 2026-05-29T14:15:26Z
**Commit range:** 12edf982d0a4ae476d1138182803f2f3c111c138..55e4e8830881ab4e0929ebd063780eb64533d970
**Verdict:** SHIP

## Executive summary

- SHIP — no blocking findings; all four axes walk clean. The implementation
  matches and in places exceeds the phoenix-compose.yml rectified baseline.
- 0 CRITICAL, 0 HIGH, 0 MEDIUM, 0 LOW
- Axis 1 (container hygiene): both Dockerfile stages carry identical
  @sha256 pins; curl installed in runtime stage; HEALTHCHECK present; tini
  entrypoint; non-root UID 1000; no secrets in image layers.
- Axis 2 (compose correctness): port bound to 127.0.0.1; bind-mount source
  verified to resolve to repo-root var/arxmcp (not infra/var/arxmcp);
  restart explicit; mem_limit/cpus (not deploy.resources); cap_drop + no-new-
  privileges; init:true.
- Axis 3 (CI workflows): no .github/workflows/ files in range — N/A.
- Axis 4 (Makefile): no Makefile changes in range — N/A; make ingest stub
  confirmed preserved.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

No findings. All axes clean — see "What was done well" for the positive record.

## What was done well

- **Both Dockerfile FROM stages carry the same @sha256 pin** (`docker/Dockerfile.server:40`
  and `docker/Dockerfile.server:83`): `python:3.11-slim@sha256:a3ab0b966bc4e91546a033e22093cb840908979487a9fc0e6e38295747e49ac0`.
  The inline comment documents the multi-arch manifest-list rationale and
  the re-resolution runbook (`docker buildx imagetools inspect`). Both stages
  are pinned to the identical digest — a common miss that can silently produce
  version skew between builder and runtime.

- **curl is present in the runtime image** (`docker/Dockerfile.server:94-98`):
  `tini`, `curl`, and `ca-certificates` are all installed in the runtime apt
  layer. This is load-bearing — both the Dockerfile HEALTHCHECK and the
  compose healthcheck invoke `curl -fsS http://127.0.0.1:7733/readyz`. Without
  curl in the runtime stage, `docker compose up --wait` would time out
  indefinitely. Confirmed clean.

- **Bind-mount source resolves to repo root, not infra/** (`infra/docker-compose.yml:46`):
  `../var/arxmcp` was verified with `docker compose -f infra/docker-compose.yml config`,
  which resolves to `/Users/chris.dare/Personal/SourceCode/arXMCP/var/arxmcp`.
  The inline comment cites the Compose v2 path-resolution rule and
  distinguishes from phoenix-compose.yml's two-level `../../` (one directory
  deeper). This is the exact foot-gun logged in the project's infra-safety
  memory from E13_S03.

- **Port published to 127.0.0.1 only** (`infra/docker-compose.yml:31`):
  `"127.0.0.1:7733:7733"` with an explicit inline comment warning against
  dropping the prefix. This matches the load-bearing network defense cited
  in `08-security-observability-ops.md`.

- **In-container 0.0.0.0 bind pattern correctly documented** (`infra/docker-compose.yml:48-62`):
  `ARXMCP_BIND_HOST: "0.0.0.0"` + `ARXMCP_UNSAFE_NETWORK_BIND: "1"` is the
  correct and necessary pattern for Docker bridge networking; the comment
  explains WHY it is safe (host-side loopback pin is the real defense) and
  references `server/config.py::reject_non_loopback_bind`. The validator
  would crash the container at startup without both variables set.

- **mem_limit/cpus used correctly instead of deploy.resources** (`infra/docker-compose.yml:98-100`):
  The compose uses `mem_limit: 8g` and `cpus: 4.0` — the standalone Compose
  form that takes effect outside Swarm mode. `deploy.resources.limits` is
  Swarm-only and silently ignored by `docker compose`; the comment explicitly
  calls this out. Matches the rectified phoenix-compose.yml pattern and the
  2026-05-17 infra-safety memory entry.

- **cap_drop: ["ALL"] + no-new-privileges + init:true** (`infra/docker-compose.yml:77-84`):
  All three hardening knobs from the phoenix IS5 rectification are applied
  to this new service with accurate commentary. The `init: true` is belt-and-
  suspenders given that tini is already the Dockerfile ENTRYPOINT.

- **Dockerfile non-root user and chown scope are correct** (`docker/Dockerfile.server:101-127`):
  `useradd --uid 1000` + `USER arxmcp` before CMD; `chown -R arxmcp:arxmcp /app/var`
  scoped to the writable mount point only, leaving the source tree root-owned
  (still readable by the non-root user). The compose has no `user:` directive,
  which is correct — the image's USER directive is honored automatically by
  the container runtime.

- **No secrets baked into image layers**: no `ENV`, `ARG`, or `RUN` line in
  either Dockerfile stage sets a secret value. `ARXMCP_UNSAFE_NETWORK_BIND`
  is a capability flag, not a credential. `ARXMCP_CONTACT_EMAIL` is
  intentionally absent with a comment explaining why.

- **.dockerignore is present and comprehensive** (`/Users/chris.dare/Personal/SourceCode/arXMCP/.dockerignore`):
  Excludes `.git/`, `var/`, `tests/`, `docs/`, `infra/`, `.claude/`, and all
  Python cache artifacts. A `COPY . .` regression would not leak
  `var/arxmcp/` corpus blobs, `.git/objects`, or agent-internal notes into
  the build context.

## Recommended rectification order

No rectification required. All axes clean.

## Deferred findings

None.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
