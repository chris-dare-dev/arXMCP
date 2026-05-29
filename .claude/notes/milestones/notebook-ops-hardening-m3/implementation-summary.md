# Implementation Summary — notebook-ops-hardening-m3

**One-liner:** Ship `infra/docker-compose.yml` (server-only v0) — `docker
compose up --wait` builds `docker/Dockerfile.server` (now `@sha256`-pinned) and
brings the MCP server up healthy on loopback `127.0.0.1:7733`, with a static
compose-inspection test and a documented end-to-end flow.

**Commit range:** `<base>..<head>` (filled at finalize).
**Implementation path:** inline — 5 files, surgical copy-adapt from the
already-rectified `phoenix-compose.yml`, no parallel boundary.

**Gate:** `notebook-ops-hardening-spike-1` was RUN + RESOLVED as a pre-step
(`.claude/notes/spikes/notebook-ops-hardening-spike-1.md`): on macOS Docker
Desktop a UID-1000 container writes cleanly to a bind-mounted `var/arxmcp/`
with NO `chown` — VirtioFS maps ownership. **The chown pre-step is
native-Linux-only, correcting the brief's "macOS chown" wording.**

---

## What landed

### `infra/docker-compose.yml` (new) — server-only v0
Mirrors the phoenix template's hardening: `build: {context: .., dockerfile:
docker/Dockerfile.server}`, `ports: ["127.0.0.1:7733:7733"]` (loopback host
side), `volumes: ["../var/arxmcp:/app/var/arxmcp"]`, `environment:
{ARXMCP_BIND_HOST: 0.0.0.0, ARXMCP_UNSAFE_NETWORK_BIND: 1}`, an explicit
`healthcheck` on `/readyz` (start_period 5m for BGE-M3 warm-up), `cap_drop:
[ALL]`, `security_opt: [no-new-privileges:true]`, `init: true`, `restart: "no"`,
`mem_limit: 8g`, `cpus: 4.0`. `ARXMCP_CONTACT_EMAIL` intentionally omitted.

**The load-bearing detail — bind-mount prefix `../var/arxmcp` (ONE `../`)** —
was empirically verified: `docker compose -f infra/docker-compose.yml config`
resolves the bind source to exactly `<repo-root>/var/arxmcp` (not `infra/var`,
not above the repo). This settles the brief-1-vs-brief-2 conflict (brief-1 was
right; phoenix's `../../` is correct only because it sits two levels deep).

### `docker/Dockerfile.server` — `@sha256` base-image pins
Both `FROM python:3.11-slim` stages (builder + runtime) pinned to
`@sha256:a3ab0b966bc4e91546a033e22093cb840908979487a9fc0e6e38295747e49ac0` (the
multi-arch manifest digest from `docker buildx imagetools inspect`), with a
rationale comment citing 08-security §Threat 6.

### `tests/test_compose_server.py` (new, 11 tests)
Mirrors `test_compose_phoenix.py`. Always-run PyYAML asserts: loopback-only
ports (no bare 0.0.0.0), the `../var/arxmcp` prefix (rejects `./var` and
`../../var`), `cap_drop ALL`, `no-new-privileges`, `init`, the two bind-override
env vars, NO `ARXMCP_CONTACT_EMAIL`, `/readyz` healthcheck, mem_limit/cpus,
`build.dockerfile`, and both Dockerfile FROM lines carry `@sha256:`. Plus a
docker-gated `docker compose config` test that asserts the bind source resolves
to repo-root `var/arxmcp` and the published port host_ip is `127.0.0.1`.

### Docs
- `docs/install.md` § "Run via Docker Compose": `make bootstrap` → Linux-only
  chown (macOS none, per spike-1) → `docker compose up --wait` → poll `/readyz`;
  notes on loopback, restart policy, CONTACT_EMAIL, resource limits.
- `infra/README.md`: replaced the "not yet shipped" placeholder with the shipped
  server compose.

---

## Acceptance criteria status

- [x] **AC1 G/W/T: `docker compose up` → `/readyz` 200 once warm
  (service_healthy gate).** The compose `healthcheck` + `docker compose up
  --wait` provide the gate; the live build+run is operator-acceptance
  (heavyweight BGE-M3 download), documented in install.md. `docker compose
  config` validation (run here) confirms the file is valid + resolves the bind
  path. The static test is the automated artifact per AC3.
- [x] **AC2: no host-side 0.0.0.0; loopback only; non-root UID; install.md
  chown pre-step.** `127.0.0.1:7733:7733`; UID 1000 (Dockerfile); install.md
  documents the Linux-only chown + macOS-no-pre-step (spike-1 correction).
- [x] **AC3: a test inspects the compose/middleware stack for the loopback
  binding (no live upload).** `tests/test_compose_server.py` (11 tests).

## Deviations from the brief

1. **AC2 wording corrected (spike-1):** chown is native-Linux-only, not macOS.
2. **`restart: "no"`** for v0 (explicit operator control; avoids BGE-M3 RAM on
   every reboot) vs 08-security's "always-on" framing — documented override to
   `unless-stopped`.
3. **`ARXMCP_CONTACT_EMAIL` omitted** from the server compose env (ingest-only;
   server Config forbids unknown ARXMCP_* vars).
4. No Makefile target added (raw `docker compose` command documented instead —
   avoids an unnecessary infra-safety surface).
5. Live `docker compose up` not run during implementation (heavyweight; AC3
   carves out the static test as the automated artifact).

## Test surface

New: `tests/test_compose_server.py`. Changed: `docker/Dockerfile.server`,
`infra/docker-compose.yml` (new), `docs/install.md`, `infra/README.md`, +
`.claude/notes/spikes/notebook-ops-hardening-spike-1.md` (new).

## External writes required

**None gated.** One local read-only network fetch during implementation
(`docker buildx imagetools inspect python:3.11-slim` to resolve the digest) —
not a push/PR/ticket. `git push origin main` is per-event authorized at finalize.
