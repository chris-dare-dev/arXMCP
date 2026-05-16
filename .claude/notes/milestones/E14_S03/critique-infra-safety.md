# E14_S03 — Infra-safety critique

**Scope:** commit range `7cf092e..3395d0e` (single commit `3395d0e — feat(infra): Phoenix retrieval-quality compose profile (E14_S03)`).
**Trigger:** infra-safety (`infra/`, `Makefile` touched).
**Critic posture:** narrow — container hygiene, compose correctness,
CI workflow safety, Makefile/build script. Not a re-litigation of
design choices outside that scope.

---

## What was done well

- **Loopback-only host binding is correctly applied to both published
  ports.** `infra/observability/phoenix-compose.yml:66-69` uses the
  full `127.0.0.1:6006:6006` and `127.0.0.1:4317:4317` form, matching
  `.claude/notes/08-security-observability-ops.md` §Tracing's
  "localhost-only by convention" requirement. The threat model (spans
  carry `mcp.session_id`) is correctly cited inline in the file
  header (`phoenix-compose.yml:19-24`) so a future agent does not
  silently relax the prefix.
- **Outbound telemetry explicitly disabled.** `PHOENIX_TELEMETRY_ENABLED:
  "false"` (`phoenix-compose.yml:62`) prevents Phoenix from beaconing
  to Arize; combined with the loopback ingest binding, the only
  outbound network call across the lifecycle is the one-time image
  pull. The inline comment names this explicitly, which is the right
  way to defend a hardening choice against accidental re-enablement.
- **Bounded retention.** `PHOENIX_DEFAULT_RETENTION_POLICY_DAYS: "14"`
  (`phoenix-compose.yml:58`) closes the unbounded-disk-growth failure
  mode that Phoenix's default `0` would create. Tied back to the
  single-workstation posture from CLAUDE.md.
- **No `version:` field.** Compose v2 deprecated the top-level
  `version:` key; the file correctly omits it (`phoenix-compose.yml`
  begins with `services:` at line 26). One less drift surface.
- **No CI workflow changes.** Confirmed via `git diff
  7cf092e..3395d0e -- .github/workflows/` (empty output) and `ls
  .github` (no such directory). The trigger filter is satisfied
  vacuously.
- **Makefile bootstrap addition is idempotent, sudo-free, and
  correctly placed.** `Makefile:37-40` adds `mkdir -p
  var/arxmcp/observability/phoenix` immediately after the other
  `var/arxmcp/...` mkdir lines, before the LaTeXML NOTE block.
  `mkdir -p` is idempotent, exits non-zero on permission errors
  (propagating to `make bootstrap` via Make's default
  exit-on-failure), and does not require root. The placement
  does not introduce a precondition that breaks an earlier line
  — each `mkdir -p` is independent.
- **Profile gating.** `profiles: ["phoenix"]` (`phoenix-compose.yml:37`)
  means `docker compose -f infra/observability/phoenix-compose.yml
  up` without the `--profile phoenix` flag is a no-op, eliminating
  the surprise-startup failure mode where a routine `compose up`
  unexpectedly launches an observability stack.
- **Healthcheck uses `wget --spider` not `curl`.** `phoenix-compose.yml:82`
  picks the portable command for the Phoenix image base, matching
  the inline justification at line 81. `start_period: 20s` correctly
  accounts for SQLite migration on first run.

---

## Findings

### IS1 — Container runs as root; no `user:` override

- **Severity:** MEDIUM
- **Where:** `infra/observability/phoenix-compose.yml:27-95` — no `user:`
  directive anywhere in the `phoenix` service block.
- **Observation:** The brief's prompt explicitly flags this as a known
  Phoenix default: `arizephoenix/phoenix:15.10` runs as UID 0 inside the
  container. The compose file does not override with a `user:` directive,
  so the SQLite trace store at `/mnt/data` (bind-mounted to
  `./var/arxmcp/observability/phoenix`) is written as root on the host.
- **Why it matters:** Two concrete consequences. (a) Files in
  `var/arxmcp/observability/phoenix/` are root-owned on the host,
  meaning a developer running `make clean` (or `rm -rf var/`) without
  sudo gets a permission error — friction the rest of the
  `var/arxmcp/` tree does not impose. (b) Bind-mounted root-write is
  the same posture that
  `.claude/notes/08-security-observability-ops.md` §"Threat 3 …
  rootless-container UID isolation" calls out as the failure mode the
  LaTeXML container intentionally avoids. Phoenix re-introduces it
  in a sibling subtree.
- **Recommended fix:** Add `user: "${UID:-1000}:${GID:-1000}"` to the
  service block. Phoenix 15.x's published Dockerfile does not enforce
  a fixed UID at the filesystem layer for `/mnt/data` (the dir is
  created at runtime by the entrypoint), so a non-root invocation
  works. If Phoenix's entrypoint legitimately needs root for setup,
  document the exception with an inline comment and a runbook
  reference — the silent-default state is the issue.
- **If left as-is:** Document the root-write footprint in
  `.claude/docs/observability-phoenix.md` and add a `chown` step to
  the runbook's teardown section. The finding stays MEDIUM either
  way; today neither mitigation is present.

### IS2 — No resource limits (CPU, memory, pids)

- **Severity:** MEDIUM
- **Where:** `infra/observability/phoenix-compose.yml:27-95` — no
  `deploy.resources.limits` or `mem_limit` / `cpus` / `pids_limit`.
- **Observation:** The service has no upper bound on memory, CPU, or
  process count. Phoenix's SQLite span store grows in-memory during
  ingest bursts; a misbehaving exporter (E14_S02 bug, runaway test
  loop) could starve the developer's workstation.
- **Why it matters:** On a single-workstation local-first deploy, an
  unbounded sidecar competes with the actual work (`python -m
  server.main`, `pytest`). The 14-day retention bounds disk, not
  memory or CPU.
- **Recommended fix:** Add a `mem_limit: 2g` and `cpus: 2.0` (or
  Compose v2's `deploy.resources.limits` equivalent in non-Swarm
  mode — `mem_limit` is the portable form). Values are conservative
  starting points; tune per the runbook's load expectations.

### IS3 — Image tag is minor-pinned, not patch-pinned or digest-pinned

- **Severity:** MEDIUM
- **Where:** `infra/observability/phoenix-compose.yml:31` — `image:
  arizephoenix/phoenix:15.10`.
- **Observation:** The `15.10` tag is mutable: a future `15.10.1` or
  `15.10.2` push to Docker Hub will be silently pulled by the next
  `docker compose pull` / `up`. The brief's prompt explicitly raises
  this question.
- **Why it matters:** Mutable-tag pinning is the supply-chain failure
  mode that distinguishes "the build that passed CI yesterday" from
  "what runs on the developer's box today." For an opt-in dev sidecar
  with no `mcp.session_id` leakage in normal operation, this is
  MEDIUM, not HIGH — but it is still a reproducibility gap.
- **Recommended fix:** Pin to a content-addressable digest:
  `image: arizephoenix/phoenix:15.10@sha256:<digest>`. Document the
  bump procedure in `.claude/docs/observability-phoenix.md`
  §"Upgrading Phoenix" (the file is already referenced from
  `phoenix-compose.yml:30`; add the digest-update step there). If
  digest pinning is judged too high-friction for a dev-only sidecar,
  at minimum patch-pin (`:15.10.0`) so the Docker Hub side of the
  pin is immutable.

### IS4 — Read-only root filesystem is not enabled

- **Severity:** MEDIUM
- **Where:** `infra/observability/phoenix-compose.yml:27-95` — no
  `read_only: true` and no companion `tmpfs:` for the writable paths.
- **Observation:** Phoenix writes its SQLite store to
  `PHOENIX_WORKING_DIR=/mnt/data` (bind-mounted), but the rest of
  the container filesystem is also writable by default. With
  `read_only: true` and a small `tmpfs:` for `/tmp` and any other
  scratch path Phoenix uses, a compromised Phoenix process cannot
  modify its own binaries or write to arbitrary container paths.
- **Why it matters:** Defense-in-depth. The threat model
  (`.claude/notes/08-security-observability-ops.md` Threat 6 —
  supply-chain) treats the model-weight pipeline as compromisable;
  the same logic applies to Docker Hub images. A read-only rootfs
  reduces the blast radius of an image compromise.
- **Recommended fix:** Add `read_only: true` and `tmpfs: ["/tmp"]`
  to the service block. Validate locally that Phoenix's startup
  does not write outside `/mnt/data` and `/tmp`; if it does, expand
  the `tmpfs:` list rather than dropping `read_only`.

### IS5 — No `cap_drop` / `security_opt` hardening

- **Severity:** MEDIUM
- **Where:** `infra/observability/phoenix-compose.yml:27-95` — no
  `cap_drop:`, no `security_opt:` (`no-new-privileges`).
- **Observation:** Container starts with Docker's default Linux
  capability set (NET_BIND_SERVICE, CHOWN, DAC_OVERRIDE, etc.).
  Phoenix listens on user-space ports (6006, 4317), reads/writes
  its bind-mount, and renders HTTP — none of which require any
  default capability beyond what `cap_drop: [ALL]` followed by
  selective `cap_add` would provide.
- **Why it matters:** Combined with IS1 (root in container) and IS4
  (writable rootfs), the capability set forms the third leg of the
  "minimum-privilege container" tripod. Each leg alone is MEDIUM;
  combining all three is what the threat model implicitly assumes
  when it labels Phoenix "localhost-only by convention."
- **Recommended fix:** Add `cap_drop: ["ALL"]` and `security_opt:
  ["no-new-privileges:true"]`. If Phoenix's entrypoint fails (e.g.
  needs `CHOWN` to set ownership on `/mnt/data` at first run), add
  the minimum required capability back with `cap_add:` and document
  it inline.

### IS6 — Bind-mount path is relative; resolution depends on invocation cwd

- **Severity:** LOW
- **Where:** `infra/observability/phoenix-compose.yml:76` —
  `- ./var/arxmcp/observability/phoenix:/mnt/data`.
- **Observation:** Compose resolves relative volume paths against the
  compose file's directory by default (`COMPOSE_PROJECT_DIR`
  override notwithstanding). With this file at
  `infra/observability/phoenix-compose.yml`, the relative path
  `./var/arxmcp/...` resolves to
  `infra/observability/var/arxmcp/observability/phoenix` — not the
  repo-root `var/arxmcp/observability/phoenix` that `make
  bootstrap` creates.
- **Why it matters:** Operators running the documented invocation
  (`docker compose -f infra/observability/phoenix-compose.yml
  --profile phoenix up -d`) from the repo root will get a
  different bind-mount target than the bootstrap-created directory.
  The repo-root case happens to work because Compose v2 (since 1.28)
  defaults `--project-directory` to the location of the **first**
  `-f` file's directory, so the relative path resolves to
  `infra/observability/var/arxmcp/observability/phoenix` — a
  silently-created empty directory inside `infra/`, not the
  bootstrap-created one. The bootstrap step (`Makefile:40`) becomes
  a no-op for this purpose.
- **Recommended fix:** Either (a) pass `--project-directory .` in
  the documented invocation and in `.claude/docs/observability-phoenix.md`,
  (b) use an absolute path via interpolation (`${PWD}/var/...` —
  fragile, requires invocation from repo root anyway), or
  (c) move the compose file to the repo root or use a named
  volume. Option (a) is the smallest fix. The compose `config`
  smoke test in `tests/test_compose_phoenix.py` should also be
  audited — if it runs `docker compose -f
  infra/observability/phoenix-compose.yml config` without
  `--project-directory`, it validates the wrong path resolution.
- **Severity rationale:** LOW because the failure mode is "spans
  don't persist across container restart in the place the operator
  expected," not data loss or security exposure. The container
  itself works.

### IS7 — Healthcheck does not validate OTLP/gRPC ingest port

- **Severity:** LOW
- **Where:** `infra/observability/phoenix-compose.yml:82` — `test:
  ["CMD", "wget", "--spider", "-q",
  "http://127.0.0.1:6006/healthz"]`.
- **Observation:** The healthcheck probes only the HTTP UI port
  (6006). The OTLP/gRPC ingest on 4317 is the load-bearing surface
  for the milestone's actual job (receiving spans from the MCP
  server). A failure that leaves the UI up but the gRPC listener
  down would not trip the healthcheck — false-positive "healthy"
  state.
- **Why it matters:** The milestone's AC is "Phoenix UI shows
  spans from a test `search_papers` call." If 4317 is not
  accepting connections, no spans arrive, but `docker compose ps`
  reports `healthy`. The operator would need to discover the
  failure through the absence of UI data, not the healthcheck.
- **Recommended fix:** Either (a) add a second healthcheck path
  that probes 4317 (e.g. via `nc -z 127.0.0.1 4317` if `nc` is in
  the image, or a small `wget` against any OTLP/HTTP endpoint
  Phoenix exposes on its HTTP port), or (b) accept the limitation
  and document it in `.claude/docs/observability-phoenix.md`
  troubleshooting: "if the UI is up but no spans appear, check
  `docker exec phoenix ss -ltn` for the 4317 listener."
- **Severity rationale:** LOW because Phoenix's two listeners
  share a process; a process-up-but-one-listener-down failure
  mode is rare. Worth fixing, not blocking.

### IS8 — No `init: true` / `tini` for PID 1 reaping

- **Severity:** LOW
- **Where:** `infra/observability/phoenix-compose.yml:27-95` — no
  `init: true` directive.
- **Observation:** Compose's `init: true` injects `tini` as PID 1
  to reap zombie processes and forward signals correctly to the
  Phoenix Python process. The `docker/Dockerfile.server` for the
  MCP server (per CLAUDE.md §5) explicitly uses `tini`; the
  Phoenix sidecar does not.
- **Why it matters:** Phoenix's image may already use `tini` (the
  Dockerfile.server precedent suggests the project values this);
  if it does, the directive is redundant. If it does not, signal
  handling on `docker compose down` may be delayed (Phoenix's
  Python process gets SIGTERM via the runc wrapper, which may
  take the full `stop_grace_period`).
- **Recommended fix:** Add `init: true`. The cost is one line; the
  benefit is consistent signal handling whether or not the
  upstream image bundles tini.
- **Severity rationale:** LOW — at worst a slow shutdown.

---

## What I checked and did not find a problem with

- **No secrets in environment.** The four `PHOENIX_*` env vars are
  all non-sensitive configuration (port, host, working dir, retention
  days, telemetry toggle). No `ARXMCP_*` vars are passed through; the
  MCP server points its OTel exporter at the published 4317 port from
  the outside, which is the right shape. (`phoenix-compose.yml:39-62`)
- **No port exposure beyond loopback.** Both `ports:` entries use the
  `127.0.0.1:` prefix (`phoenix-compose.yml:66, 69`). The inline
  comment at lines 19-24 names the threat (LAN scraping leaks
  session IDs) and the defense.
- **`restart: unless-stopped` is the right choice.** Not `always`
  (would defy explicit `down`), not `no` (would not survive a
  daemon restart that the operator did NOT explicitly trigger).
  Comment at `phoenix-compose.yml:89-94` explains the choice.
- **Volume mount target inside container is sensible.** `/mnt/data`
  matches `PHOENIX_WORKING_DIR`; not a standard system path that
  would clobber container state. (`phoenix-compose.yml:53, 76`)
- **Makefile change is correctly placed and self-contained.**
  Only one chunk modified, four lines added including two comment
  lines. No reordering of earlier targets, no removal of any
  existing mkdir, no `sudo`. (`Makefile:37-40`)
- **No CI workflow changes.** `.github/workflows/` does not exist in
  the repo; the diff filter is satisfied trivially.

---

## Summary

8 findings, all MEDIUM or LOW:

- **MEDIUM (5):** IS1 (root user), IS2 (no resource limits),
  IS3 (minor-pinned tag, no digest), IS4 (writable rootfs),
  IS5 (no `cap_drop` / `no-new-privileges`).
- **LOW (3):** IS6 (relative bind-mount path), IS7 (healthcheck
  doesn't cover gRPC), IS8 (no `init: true`).

**No CRITICAL or HIGH findings.** The two load-bearing defenses
(loopback-only host binding, telemetry disabled) are present and
inline-justified. The MEDIUM findings cluster around standard
container-hardening hygiene (run-as-non-root, resource limits,
capability drop, read-only rootfs, immutable image pinning) — none
of which is novel for this repo and all of which are addressable
with one or two lines of YAML each.

The IS6 (relative bind-mount path) finding is worth verifying
quickly during rectification: if the bootstrap-created directory
is not the one Phoenix actually writes to, the milestone's
persistence story is paper-only.

---

## Rectification status

Findings tracked in
[`critique-adversary.md`](critique-adversary.md)'s rectification
footer for unified bookkeeping. Summary:

- IS1 (root user): DEFERRED — requires live-container validation.
- IS2 (no resource limits): FIXED — `mem_limit: 2g` + `cpus: 2.0`.
- IS3 (mutable tag): FIXED — image digest pinned.
- IS4 (writable rootfs): DEFERRED — same live-container gap as IS1.
- IS5 (no cap_drop / no-new-privileges): FIXED.
- IS6 (relative bind-mount): FIXED — `../../var/arxmcp/...`.
- IS7 (healthcheck gRPC port): DEFERRED — documented in runbook.
- IS8 (no init: true): FIXED.
