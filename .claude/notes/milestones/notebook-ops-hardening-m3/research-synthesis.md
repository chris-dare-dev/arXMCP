# Research Synthesis — notebook-ops-hardening-m3

**Milestone:** `docker compose up` brings the server up healthy (server-only v0)
**Mode:** standard (2× Sonnet, parallel)
**Gate:** `notebook-ops-hardening-spike-1` — RESOLVED (see
`.claude/notes/spikes/notebook-ops-hardening-spike-1.md`)
**Sources:** research-brief-1.md (in-codebase), research-brief-2.md (compose
spec + failure modes + static-test design)

---

## TL;DR — what to build

Ship `infra/docker-compose.yml` (server-only v0) by copy-adapting the
already-rectified `infra/observability/phoenix-compose.yml` template. Pin the
two `FROM python:3.11-slim` lines in `docker/Dockerfile.server` to `@sha256`.
Add a "Run via Docker Compose" section to `docs/install.md` (macOS = no
pre-step; Linux = chown). Update `infra/README.md`. Add a static YAML-inspection
test `tests/test_compose_server.py`. No Makefile change. No MCP/BP1/tool-schema
impact. infra-safety critic WILL fire (compose + Dockerfile paths).

Recommended compose (resolved shape):
```yaml
# infra/docker-compose.yml  (server-only v0, notebook-ops-hardening-m3)
services:
  server:
    build:
      context: ..                       # repo root — Dockerfile COPYs server/ ingest/ etc.
      dockerfile: docker/Dockerfile.server
    ports:
      - "127.0.0.1:7733:7733"           # host side loopback-only
    volumes:
      - ../var/arxmcp:/app/var/arxmcp   # ONE ../ — see RESOLVED #1
    environment:
      # 0.0.0.0 INSIDE the container is fine; the loopback defense is the
      # host-side 127.0.0.1: port prefix (phoenix-compose §"0.0.0.0 is correct
      # INSIDE the container"). Both vars are REQUIRED or config parse crashes.
      ARXMCP_BIND_HOST: "0.0.0.0"
      ARXMCP_UNSAFE_NETWORK_BIND: "1"
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:7733/readyz"]
      interval: 30s
      timeout: 5s
      start_period: 5m                  # covers first-run BGE-M3 ~2.3GB download
      retries: 3
    cap_drop: ["ALL"]
    security_opt: ["no-new-privileges:true"]
    init: true
    restart: "no"                        # see RESOLVED #2
    mem_limit: 8g                        # BGE-M3 + reranker + LanceDB headroom
    cpus: 4.0
```

---

## In-codebase facts (verbatim, brief-1 + brief-2)

**`docker/Dockerfile.server`:** multi-stage, `FROM python:3.11-slim AS builder`
(line 32) + `FROM python:3.11-slim AS runtime` (line 73) — **NEITHER `@sha256`-
pinned**; both need pins (AC requires sha256 base-image pins). UID 1000/GID 1000
`arxmcp` user (lines 91-92, `USER arxmcp` line 124). `tini` PID 1
(`ENTRYPOINT ["/usr/bin/tini","--"]` line 138). `VOLUME /app/var/arxmcp` (line
122). `CMD ["python","-m","server.main"]` (line 145). Existing HEALTHCHECK
(lines 133-134): `--interval=30s --timeout=5s --start-period=5m --retries=3 CMD
curl -fsS http://127.0.0.1:7733/readyz || exit 1`.

**`server/config.py`:** `bind_host` default `127.0.0.1`; `bind_port` default
7733; `unsafe_network_bind: bool = False` (line 358) → env
`ARXMCP_UNSAFE_NETWORK_BIND`. The `reject_non_loopback_bind` validator (510-537)
raises at parse time unless `bind_host` is loopback OR
`unsafe_network_bind=True`; its own error text points at exactly the compose
pattern (`ports: "127.0.0.1:7733:7733"` + `ARXMCP_UNSAFE_NETWORK_BIND=1`).

**Project precedents:** `phoenix-compose.yml` (E14_S03, fully rectified) +
`infra/latexml/docker-compose.latexml.yml` both document the relative-bind-mount
trap and `mem_limit`/`cpus`-not-`deploy.resources`. `tests/test_compose_phoenix.py`
is the static-YAML-test pattern to mirror. `pyyaml>=6.0` is already a dep
(`yaml.safe_load`, no new dep for the test).

---

## RESOLVED divergences

### #1 — Bind-mount prefix: `../var/arxmcp` (ONE `../`) — brief-1 correct

Briefs CONFLICT: brief-1 says `../var/arxmcp`; brief-2 says `../../var/arxmcp`.
**brief-1 is right.** Compose resolves relative bind-mount paths against the
compose file's PARENT folder. `infra/docker-compose.yml` → parent `infra/` →
`../var/arxmcp` reaches `<repo-root>/var/arxmcp`. The `../../` in
phoenix-compose is correct only because phoenix lives at `infra/observability/`
(two levels deep). brief-2 mechanically copied phoenix's `../../` — that would
land at `<one-level-above-repo-root>/var/arxmcp`, OUTSIDE the repo. **This is the
F1-class trap; getting it wrong silently mounts the wrong dir → empty corpus →
/readyz never 200.** IMPLEMENTATION MUST verify with `docker compose -f
infra/docker-compose.yml config` (renders the resolved absolute path) before
committing.

### #2 — `restart: "no"` for v0 — recorded judgment call (briefs diverge)

brief-1: `restart: "no"` (mirror phoenix F3). brief-2: `restart:
"unless-stopped"` (08-security calls the server "always-on"). **Decision:
`restart: "no"` for v0**, with a one-line documented override to
`unless-stopped`. Rationale: this is an operator-run-explicitly v0; loading
BGE-M3 (~2.3GB RAM) automatically on every workstation reboot is a heavier
default than a single-operator wants; it matches the rectified phoenix template;
and the operator opts into always-on by changing one line. (The phoenix F3
*reason* — session-data re-exposure — does NOT transfer to the loopback-only
server, so this is a resource/explicit-control call, not a security one.) Noted
as a genuine judgment call the adversary/user may override; documented in
`docs/install.md`.

### #3 — Explicit `healthcheck:` block in compose — brief-1 approach

brief-2 suggested omitting it (inherit the Dockerfile's). **Decision: include an
explicit `healthcheck:` block** mirroring the Dockerfile values. Reasons: (a)
self-documenting compose, (b) unambiguous for `docker compose up --wait`, (c)
the AC#3 static test can assert the `/readyz` healthcheck is present, (d) matches
the phoenix template (which carries an explicit healthcheck). Minor duplication
with the Dockerfile is acceptable.

### #4 — OMIT `ARXMCP_CONTACT_EMAIL` from the server compose env — brief-1

brief-1: it is NOT a `Config` field and the server `Config` uses
`extra="forbid"`, so injecting it as an `ARXMCP_*` var risks a `ValidationError`
at parse time; it is consumed only by ingest tools. brief-2: "document it as
required at runtime." **Decision: do NOT set it in the server-only v0 compose
env.** The server does not need it; ingest (deferred to v1) does. IMPLEMENTATION
verifies whether the server actually rejects an unknown `ARXMCP_*` var (check
`model_config` `extra=`) — if it tolerates it, harmless; if it rejects, omitting
is mandatory. Either way: omit. Document in `docs/install.md` that the v1 ingest
service will need it.

### #5 — `mem_limit: 8g` (brief-2) — BGE-M3 + reranker headroom

brief-1 said 6g, brief-2 said 8g. Use **8g** (conservative; reranker may also
load), operator-tunable, documented. `cpus: 4.0`.

---

## @sha256 base-image pin

Pin BOTH `FROM python:3.11-slim` lines in `docker/Dockerfile.server` to
`python:3.11-slim@sha256:<digest>`. Resolve the **multi-arch manifest digest**
(so amd64 + arm64/Apple-Silicon both resolve) via:
`docker buildx imagetools inspect python:3.11-slim` (BuildKit, standard on Docker
Desktop 28.x). Mirrors phoenix-compose's `@sha256` pin + 08-security §Threat 6
(pin by SHA; tags are mutable). This is a one-time local read-only network fetch
at implementation time — NOT a gated external write.

---

## Failure modes (brief-2, condensed)

- **FM-a (CRITICAL):** wrong relative prefix → bind mount lands outside repo →
  empty corpus → /readyz never 200. Mitigation: `../var/arxmcp` + verify with
  `docker compose config`. (= RESOLVED #1.)
- **FM-b:** `var/arxmcp/` not bootstrapped before `up` → empty corpus → /readyz
  503. Mitigation: document `make bootstrap` as a prerequisite.
- **FM-c:** `ARXMCP_UNSAFE_NETWORK_BIND` unset → container crashes at config
  parse (validator rejects 0.0.0.0). Mitigation: both env vars set + the static
  test asserts `ARXMCP_UNSAFE_NETWORK_BIND` present.
- **FM-d:** missing `127.0.0.1:` host prefix → LAN can reach the server
  (08-security threat-model violation). Mitigation: static test asserts every
  `ports` entry starts with `127.0.0.1:` and rejects bare `0.0.0.0`.
- **FM-e:** BGE-M3 first-run download slow → healthcheck flaps. Mitigation:
  `start_period: 5m` (matches the Dockerfile).
- **FM-f:** base image not sha256-pinned → supply-chain drift. Mitigation: the
  `@sha256` pins.

---

## Test plan (AC#3)

`tests/test_compose_server.py`, mirroring `tests/test_compose_phoenix.py`:
- **Always-runs (PyYAML, no Docker):** `yaml.safe_load(infra/docker-compose.yml)`
  and assert: every `ports` entry starts with `127.0.0.1:` and none is a bare
  `0.0.0.0`; bind-mount source is exactly `../var/arxmcp` (NOT `./var` and NOT
  `../../var` — pins RESOLVED #1); `cap_drop` contains `ALL`; `security_opt`
  includes `no-new-privileges:true`; `environment` sets `ARXMCP_BIND_HOST=0.0.0.0`
  AND `ARXMCP_UNSAFE_NETWORK_BIND`; `init: true`; `restart` present;
  `mem_limit`/`cpus` declared; healthcheck targets `/readyz`; `build.dockerfile`
  is `docker/Dockerfile.server`; `ARXMCP_CONTACT_EMAIL` is NOT in env.
- **Dockerfile pin test:** assert both `FROM python:3.11-slim` lines carry
  `@sha256:`.
- **Optional, gated on `shutil.which("docker")`:** `docker compose -f
  infra/docker-compose.yml config` returns 0 (syntactic validity + resolves the
  bind path). NOT gated behind a marker since it is fast + no build; just skip if
  docker absent. (This is also how the implementer verifies RESOLVED #1.)

`assert` in tests is fine (the ban is for production invariants). Live `docker
compose up --wait` → /readyz 200 (AC#1) is operator-acceptance (heavyweight image
build + BGE-M3 download), documented in `docs/install.md`; NOT an automated test
(AC#3 explicitly carves out "no live 201 MB upload needed").

---

## docs/install.md + infra/README.md

`docs/install.md` new "Run via Docker Compose" section:
1. `make bootstrap` (creates `var/arxmcp/` tree) — prerequisite.
2. **macOS Docker Desktop:** no pre-step (spike-1: VirtioFS maps ownership).
   **native Linux Docker:** `chown -R 1000:1000 var/arxmcp` first (spike-1).
3. `docker compose -f infra/docker-compose.yml up --wait` (the `service_healthy`
   gate; blocks until `/readyz` 200).
4. Poll `curl -fsS http://127.0.0.1:7733/readyz`.
5. Note: ingest service + Litestream are a v1 increment; the v1 ingest service
   will require `ARXMCP_CONTACT_EMAIL`.
6. Note: `restart: "no"` default; set `unless-stopped` for auto-restart.

`infra/README.md`: replace the "not yet shipped" placeholder with the new
compose file's purpose + invocation.

---

## Acceptance criteria → artifacts

| AC | Artifact |
|---|---|
| AC1 G/W/T: `docker compose up` → /readyz 200 once warm (service_healthy gate) | compose `healthcheck:` + `docker compose up --wait`; operator-acceptance documented; `docker compose config` lint verifies the file |
| AC2: no host-side 0.0.0.0; loopback only; non-root UID; install.md chown pre-step | `127.0.0.1:7733:7733`; UID 1000 (Dockerfile); install.md (Linux-only chown per spike-1) |
| AC3: a test inspects the compose/middleware stack for loopback binding (no live upload) | `tests/test_compose_server.py` static YAML asserts |

## Deviations from the brief (recorded)

1. **AC2 wording corrected by spike-1:** the chown pre-step is **Linux-only**,
   NOT macOS (the brief said "macOS chown pre-step"). Documented per the spike.
2. **`restart: "no"`** chosen over 08-security's "always-on"/`unless-stopped`
   framing for v0 (RESOLVED #2); operator override documented.
3. **`ARXMCP_CONTACT_EMAIL` omitted** from the server compose env (RESOLVED #4).
4. No Makefile target added (avoids an unnecessary infra-safety surface; raw
   `docker compose` command documented instead).

## Open questions

- **Live AC1 validation:** run the full `docker compose up --wait` during
  implementation? **Recommendation: NO** — it builds the image + downloads BGE-M3
  (~2.3GB, multi-minute), which is operator-acceptance, not an automated gate.
  Use the static YAML test + `docker compose config` lint as the automated
  artifacts; document the live step. (Both briefs agree.)
- RESOLVED #1 (`../` vs `../../`) MUST be empirically confirmed with `docker
  compose config` before commit — the one must-verify item.

## External writes the implementation will require

**None gated.** One local read-only network fetch: `docker buildx imagetools
inspect python:3.11-slim` (resolve the `@sha256` digest) — not a push/PR/ticket/
infra mutation. The optional `docker compose config` lint + the (operator-only,
not-run-here) `docker compose up` are local. No git push (Phase 4, per-event).

## Orchestrator synthesis note

Briefs agreed on the compose shape, the env-var split, the sha256-pin
requirement, the static-test pattern, and the spike-1 chown correction. The one
load-bearing CONFLICT — bind-mount prefix `../var/arxmcp` (brief-1) vs
`../../var/arxmcp` (brief-2) — is resolved in favor of brief-1 (mechanically
correct for a one-level-deep compose file) and flagged as a must-verify with
`docker compose config`. Three smaller divergences (restart policy, healthcheck
inline-vs-inherit, CONTACT_EMAIL) resolved with recorded rationale above.
