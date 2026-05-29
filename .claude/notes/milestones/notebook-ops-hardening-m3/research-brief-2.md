# Research Brief — notebook-ops-hardening-m3

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-29T14:30:00Z

---

## In-codebase context

### Design constitution citations

**`08-security-observability-ops.md` §Docker deployment** (verbatim, load-bearing):

> ```yaml
> services:
>   arxmcp-server:
>     ports:
>       - "127.0.0.1:7733:7733"
>     environment:
>       - ARXMCP_BIND_HOST=0.0.0.0
>     security_opt:
>       - no-new-privileges
>     cap_drop:
>       - ALL
> ```
>
> "The two services share volumes but run as different processes with different lifetimes.
> The MCP server is always-on; the ingest service runs on a cron schedule... The stdio
> shim is **not** in Docker — it runs on the host as a tiny binary spawned by Claude Code."

Note: the design note shows `ARXMCP_BIND_HOST=0.0.0.0` inside the container (host-side
binding at `127.0.0.1:7733:7733`). This is correct — the loopback constraint lives on the
HOST side; in-container `0.0.0.0` is acceptable because Docker's bridge network forwards
the loopback host-port-mapping to the container's listener. The `ARXMCP_UNSAFE_NETWORK_BIND=1`
flag in `server/config.py` (line 358) unlocks non-loopback bind for this exact docker path.

**`infra/observability/phoenix-compose.yml` comment** (verbatim, the loopback rationale):

> ```yaml
> # 0.0.0.0 is correct INSIDE the container — Docker's bridge
> # network forwards the loopback host port-binding to the
> # container's 0.0.0.0 listener. The "localhost-only" defense
> # lives on the host side via the ``ports:`` 127.0.0.1: prefix.
> PHOENIX_HOST: "0.0.0.0"
> ```

This is the exact same rationale for `ARXMCP_BIND_HOST=0.0.0.0` + `ARXMCP_UNSAFE_NETWORK_BIND=1`
in the server compose. Cite phoenix-compose.yml §"0.0.0.0 is correct INSIDE" verbatim in
the new compose file's comment.

**`server/config.py`** (lines 351–358, load-bearing):

> ```python
> #: E13_S05 (Threat 5) — escape hatch for non-loopback bind.
> #: Default ``False`` = ``ARXMCP_BIND_HOST=0.0.0.0`` is rejected
> #: at config parse time (the historical behavior preserved).
> #: ``True`` = the bind-host validator permits non-loopback
> #: values AND a WARN log fires at startup.
> unsafe_network_bind: bool = False
> ```

The compose file MUST set both `ARXMCP_BIND_HOST=0.0.0.0` AND `ARXMCP_UNSAFE_NETWORK_BIND=1`.
Missing either causes the container to crash at config-parse time.

**`docker/Dockerfile.server`** (load-bearing for build context):

- Multi-stage: `python:3.11-slim AS builder` → `python:3.11-slim AS runtime`.
- Neither stage is currently `@sha256`-pinned (tag only: `python:3.11-slim`).
- UID 1000 / `arxmcp` user; `tini` as PID 1; `VOLUME /app/var/arxmcp`.
- HEALTHCHECK already present: `CMD curl -fsS http://127.0.0.1:7733/readyz || exit 1`
  with `--interval=30s --timeout=5s --start-period=5m --retries=3`.
- `CMD ["python", "-m", "server.main"]`.

**`tests/test_compose_phoenix.py`** — the reference test for the AC3 static-test
pattern. Uses `yaml.safe_load` (no Docker required) to assert port bindings, capability
hardening, restart policy, resource limits, init: true. An optional `docker compose config`
test is gated on `shutil.which("docker") is not None`. This is the exact pattern m3 should
mirror for `infra/docker-compose.yml`.

**`infra/latexml/docker-compose.latexml.yml`** comment (verbatim, IS4, load-bearing):

> ```
> # IS4 rectification — bind-mount source defaults are resolved relative
> # to the compose FILE's directory in Compose v2, not the operator's CWD.
> # The previous default `./latexml-output` would resolve to
> # `infra/latexml/latexml-output/` and pollute the repo tree
> ```

**CRITICAL:** `infra/docker-compose.yml` lives under `infra/`. The `var/arxmcp/` tree
lives at repo root. The compose bind-mount path MUST be `../../var/arxmcp` (or an absolute
path). A bare `./var/arxmcp` would resolve to `infra/var/arxmcp` — an F1-class trap
documented in both phoenix-compose.yml and the latexml compose.

**`pyproject.toml`**: `pyyaml>=6.0` is an explicit project dependency (loaded via
`yaml.safe_load` only). The AC3 YAML-parse test can import `yaml` without adding any new dep.

---

## Prior decisions and lessons

From git log (recent):
- `12edf98 chore(notes): finalize notebook-ops-hardening-m1 state -> complete`
- `7c17324 rect(server): close notebook-ops-hardening-m2 critique (1M 1L; 1L deferred)`

Adjacent milestone state confirms m1 (restic backup) and m2 (durable notebooks.db) are
complete. m3 is the first compose milestone in this epic.

Key learned patterns from phoenix-compose (E14_S03 adversary critique findings, already
rectified in phoenix-compose.yml and reflected in test_compose_phoenix.py):
- **F1**: relative bind-mount under compose-file dir trap — must use `../../var/arxmcp`.
- **F7/IS3**: image tag alone is mutable; must add `@sha256:` digest pin.
- **F3**: `restart: unless-stopped` re-opens session data after reboot — use `restart: "no"` for a dev-tool compose.
- **F8/IS2**: must set `mem_limit` + `cpus` (NOT `deploy.resources` which is Swarm-only).
- **IS5**: `cap_drop: ["ALL"]` + `security_opt: no-new-privileges:true`.
- **IS8**: `init: true` for tini-reaping even when the Dockerfile already installs tini as
  ENTRYPOINT (belt-and-suspenders).

All of these apply directly to the server compose.

**SPIKE-1 RESOLVED finding** (verbatim):

> macOS Docker Desktop: NO `chown` pre-step is needed. The `chown -R 1000:1000
> var/arxmcp` pre-step is a NATIVE-LINUX-Docker concern, not macOS.

`docs/install.md` must document: macOS = no pre-step; native Linux = `chown -R 1000:1000
var/arxmcp` before first `docker compose up`.

**The state.json `milestone_brief` text** references "macOS `chown -R 1000:1000 var/arxmcp`
pre-step (per spike-1)" — **this wording in the AC is wrong per the spike resolution.** The
brief's AC2 checkbox says "documents the macOS `chown` pre-step" but spike-1 corrects this
to Linux-only. **Flag:** the implementer must satisfy the spirit of AC2 (document uid/gid
handling) using the corrected Linux-only guidance from spike-1, NOT the incorrect "macOS
chown" literal wording in the brief.

---

## External sources

### Compose Specification v2 (Docker Compose v2.39.2-desktop.1 confirmed on workstation)

**Healthcheck semantics** (from `docs.docker.com/reference/compose-file/services/`):
- Keys: `test`, `interval`, `timeout`, `retries`, `start_period` (durations as strings).
- `disable: true` or `test: ["NONE"]` to suppress inherited healthcheck.
- The Dockerfile's `HEALTHCHECK` already sets interval=30s, timeout=5s, start_period=5m,
  retries=3. The compose `healthcheck:` block OVERRIDES the Dockerfile's HEALTHCHECK when
  present; omitting it inherits the Dockerfile's HEALTHCHECK unchanged.

**`docker compose up --wait`** (from `docker compose up --help` on this workstation):
```
--wait    Wait for services to be running|healthy. Implies detached mode.
--wait-timeout int    Maximum duration in seconds to wait for the project to be
                      running|healthy
```
For a SINGLE-SERVICE compose (server only, no `depends_on`), `--wait` blocks until the
service's healthcheck passes OR the `--wait-timeout` expires. This is the correct mechanism
for AC1's "compose `service_healthy` gate honored" — there is no `depends_on` target in a
single-service compose; `--wait` IS the gate. Recommendation: AC1 should be tested via
`docker compose up --wait` (live integration) or via the static YAML-inspection test (AC3).
Do NOT add a self-referential `depends_on`.

**Relative bind-mount resolution** (verbatim from spec):
> "Relative paths are resolved from the Compose file's parent folder."

This confirms: `infra/docker-compose.yml` resolves `../../var/arxmcp` to `<repo-root>/var/arxmcp`.

**Port binding semantics** (verbatim):
> "If you do not specify a host IP...Docker binds to all interfaces (0.0.0.0)."

So `"127.0.0.1:7733:7733"` in the `ports:` list restricts the published port to loopback only.

**`mem_limit` / `cpus` vs `deploy.resources`**:
`mem_limit` and `cpus` are top-level service properties honored in standalone Compose v2.
`deploy.resources.limits` is Swarm-only and SILENTLY IGNORED in standalone Compose. This
is confirmed verbatim in `infra/latexml/docker-compose.latexml.yml` IS1 rectification comment
(directly above) and the phoenix-compose F8/IS2 rectification.

**`build:` context + dockerfile syntax**:
```yaml
build:
  context: ..
  dockerfile: docker/Dockerfile.server
```
Context must be the repo root (one level above `infra/`), since the Dockerfile COPYs
`server/`, `ingest/`, `tools/`, and `pyproject.toml` from the root.

### SHA256 base-image pinning discipline

From `infra/observability/phoenix-compose.yml` (the project precedent):
```yaml
image: arizephoenix/phoenix:15.10@sha256:34464e86c02f878d76851bd0feb4bba6faead0e842bbea207e08011fa5efcac9
```

The AC requires `@sha256` base-image pins in the compose file. This applies to the build
stanza: the `FROM python:3.11-slim` in `docker/Dockerfile.server` should be pinned to
`python:3.11-slim@sha256:<digest>`. Resolve with:
```bash
docker buildx imagetools inspect python:3.11-slim --format '{{json .Manifest}}'
# or
docker manifest inspect python:3.11-slim | jq '.[0].Digest'
```
**Note:** `docker buildx imagetools inspect` requires BuildKit (standard with Docker Desktop
28.x). The implementer must run this command to obtain the current multi-arch manifest digest
for `python:3.11-slim`. This is a one-time network fetch; the resolved digest is then hardcoded
in the Dockerfile. Per `08-security-observability-ops.md` §Threat 6:
> "Pin model commit SHAs in configuration... not just names."
The same discipline extends to Docker base images: tags are mutable; digest is content-addressable.

### MCP spec relevance

This milestone touches NO MCP tool surface, NO `server/tools.py::ALL_TOOLS`, NO BP1/BP2
breakpoints, and NO `EXPECTED_TOOL_SCHEMA_SHA256`. Confirmed: the deliverables are
`infra/docker-compose.yml`, `docs/install.md` additions, and a test. Tool-schema re-pinning
is NOT required.

---

## Recommendation

**Ship `infra/docker-compose.yml` modeled exactly on `phoenix-compose.yml`**, applying all
already-rectified patterns from the E14_S03 critique. The implementation is a structured
copy-and-adapt exercise, not novel engineering. Key differences from phoenix-compose:

1. `build: {context: .., dockerfile: docker/Dockerfile.server}` instead of a pre-built image.
2. `ports: ["127.0.0.1:7733:7733"]`.
3. `volumes: ["../../var/arxmcp:/app/var/arxmcp"]` — bind-mounts the ENTIRE `var/arxmcp` at
   the container-side path `/app/var/arxmcp` (matching the Dockerfile's `WORKDIR /app` +
   `VOLUME /app/var/arxmcp`).
4. `environment: {ARXMCP_BIND_HOST: "0.0.0.0", ARXMCP_UNSAFE_NETWORK_BIND: "1"}` (both required).
5. `restart: "unless-stopped"` (server is always-on, unlike Phoenix dev tool). See open question
   below on this divergence from phoenix-compose's `restart: "no"`.
6. Omit `healthcheck:` block — inherit the Dockerfile's HEALTHCHECK unchanged (already correctly
   tuned for BGE-M3 warm-up with `start_period=5m`).
7. `mem_limit: 8g`, `cpus: 4.0` (BGE-M3 needs more headroom than Phoenix).
8. No `profiles:` — this is the always-on default service.
9. For the `@sha256` base-image pin: pin in `docker/Dockerfile.server` FROM lines.

**AC3 static test** — mirror `tests/test_compose_phoenix.py` exactly as `tests/test_compose_server.py`:
- `yaml.safe_load` (always runs, no Docker required).
- Assert: all `ports` start with `127.0.0.1:`, `cap_drop` contains `ALL`,
  `security_opt` includes `no-new-privileges`, `environment` includes `ARXMCP_UNSAFE_NETWORK_BIND`
  and `ARXMCP_BIND_HOST`, bind-mount source is `../../var/arxmcp` (not a bare `./var/...`),
  `mem_limit` and `cpus` declared, `init: true`.
- Optional `docker compose config` lint gated on `shutil.which("docker") is not None`.

**`docs/install.md`** — add a "Docker compose" section with:
- macOS: no pre-step needed (VirtioFS transparently maps ownership).
- Linux: `chown -R 1000:1000 var/arxmcp` before first `docker compose up`.
- `docker compose up --wait` as the canonical invocation for AC1 validation.
- Note that `ARXMCP_CONTACT_EMAIL` is required at runtime.

---

## Open questions

**OQ-1 (resolve before writing compose):** `restart` policy for the server service.
Phoenix uses `restart: "no"` (opt-in dev tool, F3 rectification). The server is described in
`08-security-observability-ops.md` as "always-on" (`restart: unless-stopped`). These differ.
**Recommendation:** use `restart: "unless-stopped"` for the server — it IS the always-on
service, unlike Phoenix which is an opt-in observability sidecar. Document the divergence.

**OQ-2 (implementer action, not a blocker):** The `@sha256` digest for `python:3.11-slim`
must be resolved at implementation time via `docker buildx imagetools inspect python:3.11-slim`.
The digest will be hardcoded in `docker/Dockerfile.server`. This requires a one-time `docker pull`
network fetch (not a push, not a ticket — it is a local read-only operation).

**OQ-3 (scoping clarification):** The `VOLUME /app/var/arxmcp` declaration in the Dockerfile
creates an anonymous volume on `docker run` without `-v`. The compose bind-mount overrides this
correctly. No action needed, but the implementer should confirm the bind-mount takes precedence
by verifying `docker compose config` resolves the volume to the host path.

---

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| one-time network fetch (read-only) | `docker.io/python:3.11-slim` manifest | Resolve `@sha256` digest for base-image pin in `docker/Dockerfile.server`; single `docker buildx imagetools inspect` call; no push |

None beyond this. The milestone is purely local: new files in `infra/`, edits to
`docs/install.md`, a new test file. No git push, no PR, no ticket, no infra mutation.
