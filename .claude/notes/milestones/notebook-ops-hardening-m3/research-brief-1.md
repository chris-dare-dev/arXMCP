# Research Brief — notebook-ops-hardening-m3

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-29T14:15:00Z

---

## In-codebase context

### 1. `docker/Dockerfile.server` — full analysis

Base image (line 32): `FROM python:3.11-slim AS builder` — **NO `@sha256` pin**. Runtime stage (line 73): `FROM python:3.11-slim AS runtime` — also **unpinned**. The AC requires `@sha256` base-image pins; both stages need them added.

Non-root user (lines 91–92):
```
RUN groupadd --gid 1000 arxmcp \
    && useradd --uid 1000 --gid arxmcp --shell /bin/bash --create-home arxmcp
```
`USER arxmcp` (line 124). Confirmed: **UID 1000 / GID 1000**.

`tini` PID 1 (line 138): `ENTRYPOINT ["/usr/bin/tini", "--"]` — yes, tini is installed at line 84.

HEALTHCHECK (lines 133–134):
```
HEALTHCHECK --interval=30s --timeout=5s --start-period=5m --retries=3 \
    CMD curl -fsS http://127.0.0.1:7733/readyz || exit 1
```
The `start-period=5m` covers a fresh BGE-M3 download (~2.3 GB on first run). This HEALTHCHECK must be replicated verbatim in `docker-compose.yml` as the `healthcheck:` block.

CMD (line 145): `CMD ["python", "-m", "server.main"]` — honors `ARXMCP_BIND_HOST` / `ARXMCP_BIND_PORT` via Config (per comments on lines 141–145).

VOLUME declaration (line 122): `VOLUME /app/var/arxmcp` — the declared mount point. The compose bind mount must target this path.

### 2. `infra/observability/phoenix-compose.yml` — load-bearing patterns

**F1 rectification — relative bind-mount path (CRITICAL, lines 88–94):**
> "Compose v2 resolves relative bind-mount paths against the COMPOSE FILE's directory, NOT the operator's CWD. A bare `./var/arxmcp/...` here would land under `infra/observability/var/arxmcp/...` (a stray subtree inside `infra/`), not the gitignored repo-root `var/arxmcp/` that `make bootstrap` creates. The `../../` prefix walks up to the repo root."

For `infra/docker-compose.yml` (one level under repo root), the correct prefix is `../var/arxmcp` (not `../../`). Confirmed: phoenix is at `infra/observability/` (two levels deep → `../../`), but the server compose lands at `infra/` (one level deep → `../var/arxmcp`).

**127.0.0.1 host port prefix (line 75):** `"127.0.0.1:6006:6006"` — server compose must use `"127.0.0.1:7733:7733"`.

**cap_drop / security_opt (lines 135–137):**
```yaml
cap_drop: ["ALL"]
security_opt:
  - "no-new-privileges:true"
```
Both required on the server service.

**`init: true` (line 143):** ensures tini reaps zombies — include on server service.

**`restart: "no"` (line 115):** prevents silent re-launch on reboot. Required on server service (F3 pattern).

**`mem_limit` / `cpus` (lines 124–125):** `mem_limit: 2g` / `cpus: 2.0` on phoenix. The server service needs appropriate limits. BGE-M3 (~1.5 GB model + runtime overhead) needs more headroom than Phoenix. Recommendation: `mem_limit: 6g` / `cpus: 4.0` as a conservative starting point — operator-tunable.

**`@sha256` pin (line 40):** `image: arizephoenix/phoenix:15.10@sha256:34464e86c02f878d76851bd0feb4bba6faead0e842bbea207e08011fa5efcac9` — the server service uses a locally-built image (not a registry pull), so the `@sha256` constraint applies to the BASE IMAGES in `Dockerfile.server` (the two `FROM python:3.11-slim` lines), not to the built service image itself. The server service `build: context: ..` (or `build: ..`) block does not pin an image digest — it builds locally.

**`profiles:` gate (line 46):** phoenix uses `profiles: ["phoenix"]` so `docker compose up` without `--profile phoenix` is a no-op. The server service should NOT use a profile — the brief says `docker compose up` brings it up directly (no profile flag). This diverges intentionally from phoenix.

### 3. `server/config.py` — env var / validator analysis

`bind_host` (line 87): default `"127.0.0.1"`.
`bind_port` (line 88): default `DEFAULT_BIND_PORT = 7733`.

`unsafe_network_bind` (line 358): default `False`. Declared as:
```python
unsafe_network_bind: bool = False
```
Env var name (via `env_prefix="ARXMCP_"`): **`ARXMCP_UNSAFE_NETWORK_BIND`**.

`reject_non_loopback_bind` validator (lines 510–537) — verbatim:
```
if self.bind_host not in LOOPBACK_HOSTS and not self.unsafe_network_bind:
    raise ValueError(
        f"ARXMCP_BIND_HOST must be a loopback address "
        ...
        f"Container deployments should expose the port via host "
        f"port-mapping (``ports: \"127.0.0.1:7733:7733\"``) rather "
        f"than binding to 0.0.0.0. If the container truly must "
        f"bind 0.0.0.0 INTERNALLY (with the host port-mapping "
        f"still pinning the host side to 127.0.0.1), set "
        f"``ARXMCP_UNSAFE_NETWORK_BIND=1`` to override; see "
        f".claude/docs/security-binding.md for the full warning."
    )
```

The compose service MUST set:
- `ARXMCP_BIND_HOST: "0.0.0.0"` (in-container binding to all interfaces so Docker routing works)
- `ARXMCP_UNSAFE_NETWORK_BIND: "1"` (escape hatch to allow the non-loopback in-container bind)
- Host port mapping: `"127.0.0.1:7733:7733"` (host side pinned to loopback)

`server/main.py` line 735–742 emits a WARN log when `unsafe_network_bind=1` — expected and documented in `.claude/docs/security-binding.md`.

`ARXMCP_CONTACT_EMAIL` is NOT a `Config` field (it uses `extra="forbid"` so injecting it as an ARXMCP_* var would raise a `ValidationError`). It is consumed only by ingest tools, not the MCP server. Do **not** set it in the compose environment block.

### 4. Makefile, `docs/install.md`, `infra/README.md`

Makefile `up` target (line 93–97) runs bare-metal `python -m server.main`. No `compose-up` target exists. The brief implies documenting `docker compose -f infra/docker-compose.yml up` in `docs/install.md` under a new "Run via Docker Compose" section. **No new Makefile target is required** — the brief does not specify one, and adding it risks touching the Makefile PHONY list which fires the infra-safety critic. If added, it would be `make compose-up` and minimal. Recommend deferring the Makefile target (document the raw `docker compose` command only).

`infra/README.md` currently says: "The base `docker-compose.yml` ... is **not yet shipped**" — m3 ships it, so `infra/README.md` must be updated to document the new compose file.

`docs/install.md` is operator-facing (linked from README) — correct placement per CLAUDE.md §1. A new section "Run via Docker Compose" should document the flow.

**`var/arxmcp/` subdirs needed before first compose up:**
`make bootstrap` creates: `corpus/raw`, `corpus/parsed`, `corpus/chunks`, `index/lancedb`, `index/kuzu`, `cache/ar5iv`, `ops/parser-failures`, `observability/phoenix`. The compose bind-mount of `../var/arxmcp` requires `make bootstrap` to have run first (the Dockerfile creates `var/arxmcp/index/lancedb`, `corpus/chunks`, `ops` at build time inside the image for the fallback-no-bind case, but bind-mounting an empty host dir replaces those). Document `make bootstrap` as a prerequisite.

### 5. Spike-1 findings (settled)

Per `.claude/notes/spikes/notebook-ops-hardening-spike-1.md`:
- macOS Docker Desktop + VirtioFS: NO `chown` pre-step needed.
- Native Linux Docker: `chown -R 1000:1000 var/arxmcp` before first `docker compose up`.

**`docs/install.md` must document the chown as Linux-only** and explicitly state macOS Docker Desktop needs nothing. The AC checkbox wording in state.json reads "documents the macOS `chown` pre-step" — **this is corrected by spike-1**: document the Linux-only concern, not macOS.

**CONFLICT (bold, load-bearing):** The milestone brief's acceptance criterion states: "docs/install.md documents the macOS `chown -R 1000:1000 var/arxmcp` pre-step (per spike-1)." **This is WRONG per spike-1's finding** — the spike proves macOS needs NO pre-step. The correct deliverable is documenting the Linux-only chown warning and a macOS "no pre-step needed" note. The implementer must follow spike-1 (the settled finding), not the brief's AC wording.

---

## Prior decisions and lessons

From git log: `notebook-ops-hardening-m1` and `m2` are both complete. The E14_S03 phoenix-compose critique (visible in `infra/observability/phoenix-compose.yml` inline comments) established the canonical template with F1 (relative path), F3 (restart policy), F7/IS3 (sha256 pin), IS2/F8 (resource limits), IS5 (cap_drop), IS8 (init). All of these must be replicated.

From `tests/security/test_latexml_sandbox.py::TestDockerLatexmlConfig`: the project has an established pattern for static compose YAML inspection tests — parse YAML via text search or PyYAML, assert required flags without running Docker. The AC#3 test follows this exact pattern. The test file should live at `tests/test_docker_compose_server.py` (or similar) and use `Path(__file__).parent.parent / "infra" / "docker-compose.yml"`.

**`assert` is banned** (CLAUDE.md §4.7) — compose test must use `pytest assert` with explicit messages, which is fine (pytest rewrites assertions; the ban is on `assert` for runtime invariants in production code, not in tests).

---

## External sources

Not fetched — this milestone touches only compose/Dockerfile/config, not MCP protocol surface or prompt-caching. The `07-multi-agent-caching.md` caching note is irrelevant (no tool schema changes; no new tools).

The `@sha256` pin requirement for `python:3.11-slim` requires fetching the current digest from Docker Hub. This is a one-time `docker pull python:3.11-slim --platform linux/amd64` + `docker inspect` to retrieve the digest. Both `linux/amd64` and `linux/arm64` (Apple Silicon) digests should be noted. The implementer must run this to populate the Dockerfile pins.

---

## Recommendation

Ship `infra/docker-compose.yml` as a standalone server-only compose file with the following exact shape:

```yaml
# infra/docker-compose.yml  (server-only v0, notebook-ops-hardening-m3)
services:
  server:
    build:
      context: ..
      dockerfile: docker/Dockerfile.server
    ports:
      - "127.0.0.1:7733:7733"
    volumes:
      - ../var/arxmcp:/app/var/arxmcp
    environment:
      ARXMCP_BIND_HOST: "0.0.0.0"
      ARXMCP_UNSAFE_NETWORK_BIND: "1"
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:7733/readyz"]
      interval: 30s
      timeout: 5s
      start_period: 5m
      retries: 3
    cap_drop: ["ALL"]
    security_opt:
      - "no-new-privileges:true"
    init: true
    restart: "no"
    mem_limit: 6g
    cpus: 4.0
```

Add `@sha256` pins to BOTH `FROM python:3.11-slim` lines in `docker/Dockerfile.server` (implementer fetches the digest via `docker pull`).

Add a "Run via Docker Compose" section to `docs/install.md` covering: `make bootstrap`, Linux-only chown warning, `docker compose -f infra/docker-compose.yml up`, then poll `/readyz`.

Add a static compose-inspection test at `tests/test_docker_compose_server.py` that reads `infra/docker-compose.yml` and asserts: host port prefix is `127.0.0.1:`, `cap_drop` contains `ALL`, `ARXMCP_UNSAFE_NETWORK_BIND` is set, `restart` is `"no"`, no `0.0.0.0` in ports.

Update `infra/README.md` to document the new base compose file.

Do NOT add a `make compose-up` Makefile target — document the raw `docker compose` command in `docs/install.md` to avoid firing the infra-safety critic on Makefile changes unnecessarily.

---

## Open questions

**Q1 — Live `docker compose up` + `/readyz` 200 during implementation?** The AC#1 says "docker compose up → GET /readyz 200". This requires building the image (non-trivial; pulls ~2GB BGE-M3 on first run). The AC#3 says "a test inspects the compose/middleware stack to assert the prefix loopback binding (no live 201 MB upload needed)" — this clearly scopes AC#3 to a static test. AC#1 reads as operator-acceptance (human-verified), not a CI gate. **Recommendation: the implementer runs `docker compose up` once locally to verify functional correctness (operator-acceptance), but CI only runs the static YAML inspection test. The heavy image build is not suitable for automated pytest.** Document the manual acceptance step in `.claude/docs/` or in `docs/install.md`.

**Q2 — `@sha256` pin: single-arch or multi-arch manifest digest?** Docker Hub multi-arch manifest digests differ from per-arch image digests. Using the multi-arch manifest digest in the Dockerfile `FROM` ensures both amd64 and arm64 resolve to the same logical tag version. **Recommendation: use the multi-arch manifest digest** (obtainable via `docker buildx imagetools inspect python:3.11-slim --format '{{json .Manifest}}'`), not a per-arch digest. This is consistent with the phoenix-compose approach (which also pins a single multi-arch-compatible digest).

No additional open questions — the implementation path is clear on all structural decisions.

---

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| Network fetch (one-time) | `docker pull python:3.11-slim` (Docker Hub) | Implementer must pull the image to retrieve the `@sha256` digest for Dockerfile pinning |

No git push, no PR, no ticket, no infra mutation required. All other work is local file creation + `make test`.
