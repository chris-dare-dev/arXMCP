### k3s-rancher-deploy-m1 — Kubernetes (k3s via Rancher Desktop) deployment path for arXMCP on Windows

#### Goal

Add a **parallel, additive** Kubernetes deployment path that runs the existing
`arxmcp-server` container on a local single-node **k3s** cluster provided by
**Rancher Desktop on Windows (WSL2 backend)**. Today the only containerized path
is the server-only Docker Compose stack (`infra/docker-compose.yml` +
`docker/Dockerfile.server`, landed in commit `df36de8`). No Kubernetes manifests
exist. This milestone translates that Compose service to k8s manifests under
`infra/k8s/`, adds a build/load script to get the locally-built image into k3s'
containerd (no external registry), and writes operator docs. The existing Compose
path MUST stay working and untouched — this is purely additive.

#### Operator environment (verified this session)

- Windows 11; Docker Desktop 29.1.3 + Compose v2.40.3 already installed; WSL2 with
  a Debian distro. Rancher Desktop is **not yet installed** — operator will install
  it (with k3s enabled) as a prerequisite. Live `kubectl apply` is therefore OUT OF
  SCOPE for the implement phase and is gated as an external write (runs after
  Rancher Desktop is up).
- No `make` on Windows. The project check command for this milestone is
  `ruff check . && uv run python -m pytest` (uv 0.11.15 present). Do NOT use the
  macOS-hardcoded `/Users/chris.dare/...uv` path from the command body.
- ~60 tests fail on Windows for platform reasons (symlinks, killpg, colons-in-
  filenames) — these are pre-existing, NOT regressions. The milestone's OWN new
  tests must pass.
- GPG signing is broken on this workstation (no secret key in keyring). Pipeline
  commits land **unsigned after explicit user OK** — surface this at commit time.
  Never `--no-verify`.

#### Exposure decision (operator-chosen — load-bearing)

The operator explicitly chose **Traefik Ingress / NodePort** over
`kubectl port-forward`, accepting a broader-than-Compose exposure for an always-on
service. The implementation MUST therefore minimize the residual exposure:

- Rancher Desktop forwards published/Traefik ports to the Windows host — **verify
  and document** that this binds to `127.0.0.1` by default (and how to keep it
  loopback, not LAN). The stdio shim connects to `http://127.0.0.1:7733`, so the
  host-boundary endpoint must land on loopback.
- Add a `NetworkPolicy` constraining ingress to the pod to the Traefik / ingress
  path only (default-deny otherwise).
- Document the **residual exposure delta vs Compose's strict `127.0.0.1:` host
  bind**, in the threat-model terms of `08-security-observability-ops.md`.

#### Acceptance criteria

1. `infra/k8s/` holds manifests: Namespace, ConfigMap (the `ARXMCP_*` env), a
   workload (Deployment + dedicated PVC — single replica; justify if StatefulSet is
   chosen instead), Service (ClusterIP), Traefik Ingress (or NodePort per the
   exposure decision), and a default-deny + Traefik-allow NetworkPolicy.
2. Pod `securityContext` mirrors the Compose hardening: `runAsNonRoot: true`,
   `runAsUser/runAsGroup: 1000`, `allowPrivilegeEscalation: false`,
   `capabilities.drop: [ALL]`, `seccompProfile: RuntimeDefault`,
   `readOnlyRootFilesystem: true` with the writable PVC mounted at
   `/app/var/arxmcp` and `fsGroup: 1000` so the non-root user can write it.
3. Probes map the Dockerfile/compose healthcheck semantics: a `startupProbe` that
   covers the first-run BGE-M3 download (~2.3 GB / up to ~5 min) gating liveness,
   `readinessProbe` on `/readyz`, `livenessProbe` on `/healthz`.
4. `resources.requests/limits` map `mem_limit: 8g` / `cpus: 4.0`. Document the
   Rancher Desktop WSL2 VM RAM requirement (allocate ≥ ~10 GB or the pod OOMKills
   under BGE-M3 + reranker + LanceDB).
5. PVC uses the k3s default `local-path` StorageClass for `var/arxmcp`. ConfigMap
   sets `ARXMCP_BOOTSTRAP_MODE=1` + `ARXMCP_BIND_HOST=0.0.0.0` +
   `ARXMCP_UNSAFE_NETWORK_BIND=1` (the in-cluster 0.0.0.0 bind requires the unsafe
   flag — `server/config.py::reject_non_loopback_bind` — exactly as Compose does),
   so the server boots with an empty default corpus and serves per-notebook corpora.
6. Image strategy: a documented build/load script that makes the locally-built image
   visible to k3s' containerd WITHOUT an external registry (e.g.
   `nerdctl --namespace k8s.io build`, or `docker build` + `docker save | ...
   import`/`ctr image import`). Use `imagePullPolicy: Never` + a pinned local tag
   (no `:latest`). Provide both containerd- and dockerd-runtime paths or detect the
   Rancher Desktop runtime mode. Respect the no-fork policy.
7. Host reaches the service at `127.0.0.1:<port>`; NetworkPolicy restricts cluster-
   internal reach; residual-exposure delta vs Compose documented.
8. Static validation in `tests/`: a pytest that parses every `infra/k8s/*.yaml` and
   asserts the load-bearing invariants — securityContext fields present, no `:latest`
   image tags, image pin present, resource limits set, the `ARXMCP_UNSAFE_NETWORK_BIND`
   + bootstrap env present, NetworkPolicy present. `kubeconform`/`kubeval` may be an
   optional skipped check if the binary is absent. New tests pass under the Windows
   check command.
9. Operator docs: a runbook (operator-facing) covering Rancher Desktop install, the
   Docker Desktop ↔ Rancher Desktop coexistence caveat (Rancher wants to own the
   docker/kubectl context), the build/load step, `kubectl apply`, verify (`/readyz`),
   the WSL2 RAM requirement, and the security delta. Respect doc placement
   (CLAUDE.md §1): operator-facing runbooks live under `docs/ops/` (linked from
   `docs/README.md` / `docs/ops/README.md`); agent-internal design notes go under
   `.claude/`. No stray Markdown in `infra/` beyond README/CLAUDE.
10. Compose path untouched and still green. Additive only.

#### Constraints to quote and respect

- **Doc placement** (CLAUDE.md §1 + §4.6): `infra/k8s/*.yaml` is fine (non-Markdown);
  operator docs go in `docs/ops/`, internal notes in `.claude/`.
- **Loopback-only threat model** — `.claude/notes/08-security-observability-ops.md`.
  The pod binds `0.0.0.0` inside the cluster (cluster-internal only) and needs
  `ARXMCP_UNSAFE_NETWORK_BIND=1`, identical to the Compose rationale in
  `infra/docker-compose.yml`. The host-side loopback defense is provided by Rancher
  Desktop's port-forward binding to `127.0.0.1` (verify) rather than Compose's
  `127.0.0.1:` ports prefix.
- **No-fork policy** (CLAUDE.md §4.7) — ideas only, no lifted manifests.
- **Local-first / single-workstation** — no cloud, no external registry, no
  multi-host dependency.
- **MCP server design** — `.claude/notes/06-mcp-server-design.md`; the stdio shim
  stays on the host (not in k8s) and targets `http://127.0.0.1:7733`.
- **Container hygiene already established** in `docker/Dockerfile.server`: base image
  pinned by `@sha256`, non-root UID 1000, tini PID 1, `EXPOSE 7733`, HEALTHCHECK on
  `/readyz`. Reuse the SAME image; do not rebuild a different one.

#### Open questions for the implementer

- Deployment + RWO PVC (single replica) vs StatefulSet — recommend Deployment+PVC
  unless stable network identity is needed; justify the pick.
- Rancher Desktop runtime mode (containerd `nerdctl` vs dockerd `moby`) changes the
  image-load command — handle both or detect.
- Whether to also template `ARXMCP_NOTEBOOK=<slug>` (serve an ingested notebook) as
  a documented alternative to bootstrap-empty mode.
- Ingress host/path: Traefik default ingress on `127.0.0.1` with a path prefix, vs a
  NodePort — pick the one that most cleanly lands on `127.0.0.1:7733`-equivalent for
  the shim, and document the shim `--server` URL change if the port differs.

#### External writes the implementation will require

- `{type: container image build/load, target: local k3s containerd, why: make the
  arxmcp-server image visible to k3s without a registry}` — local, but note it.
- `{type: kubectl apply, target: local k3s cluster (Rancher Desktop), why: deploy the
  manifests}` — GATED; runs after Rancher Desktop is installed. Out of scope for the
  implement phase (manifests are authored + statically validated only).
- `{type: git push, target: origin/main, why: land the milestone commits}` — GATED.
