# Research Brief — k3s-rancher-deploy-m1

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-06-22T03:45:00Z

## In-codebase context

### Design constitution notes that apply

**`06-mcp-server-design.md`** — load-bearing:

> "**`arxmcp-server`** — long-running Streamable HTTP MCP server, bound to `127.0.0.1`, port configurable (default `7733`). Runs in Docker. Owns indices, embedder, reranker, and all caches."

> "The stdio shim is **not** in Docker — it runs on the host as a tiny binary spawned by Claude Code."

> `{"mcpServers":{"arxmcp":{"command":"arxmcp-shim","args":["--server","http://127.0.0.1:7733"]}}}`

The shim's `--server` URL is hardwired in `~/.claude.json`. If k8s exposes the service on a different port than 7733, the operator must update this URL. The doc and runbook MUST note this.

**`08-security-observability-ops.md`** — load-bearing loopback-only threat model:

> "This is a single-developer, localhost-only system. The threat model is **not** 'external attacker'..."

> Threat 5: "Even bound to localhost, a malicious local web page could try to issue fetches... DNS rebinding defense: validate the `Host` header is `127.0.0.1` or `localhost` with the configured port."

The server's `OriginValidationMiddleware` and `HostValidationMiddleware` enforce loopback-only access. In k8s, the host-side boundary defense migrates from Compose's `127.0.0.1:` port prefix to Rancher Desktop's WSL2 port-forwarding behavior — which MUST be documented as the residual delta.

### `infra/docker-compose.yml` — load-bearing lines (verbatim)

```yaml
ports:
  # Host side pinned to LOOPBACK (127.0.0.1). This is the load-bearing
  # network defense (08-security-observability-ops.md): the LAN can never
  # reach the server. Do NOT drop the 127.0.0.1: prefix — a bare
  # "7733:7733" publishes on 0.0.0.0 (all host interfaces).
  - "127.0.0.1:7733:7733"

environment:
  # 0.0.0.0 is correct INSIDE the container — Docker's bridge network
  # forwards the loopback host port-binding to the container's 0.0.0.0
  # listener. The "localhost-only" defense lives on the HOST side via the
  # ports: 127.0.0.1: prefix above... The server's config validator
  # (server/config.py::reject_non_loopback_bind) rejects a non-loopback
  # bind at parse time UNLESS ARXMCP_UNSAFE_NETWORK_BIND=1
  ARXMCP_BIND_HOST: "0.0.0.0"
  ARXMCP_UNSAFE_NETWORK_BIND: "1"
  ARXMCP_BOOTSTRAP_MODE: "1"

cap_drop: ["ALL"]
security_opt:
  - "no-new-privileges:true"
mem_limit: 8g
cpus: 4.0
```

The k8s manifests replicate ALL of these. The 0.0.0.0 + UNSAFE_NETWORK_BIND pair is required in-cluster; the host-side loopback defense is the k3s/Rancher Desktop forwarding layer.

### `docker/Dockerfile.server` — load-bearing lines (verbatim)

```dockerfile
FROM python:3.11-slim@sha256:a3ab0b966bc4e91546a033e22093cb840908979487a9fc0e6e38295747e49ac0 AS builder
FROM python:3.11-slim@sha256:a3ab0b966bc4e91546a033e22093cb840908979487a9fc0e6e38295747e49ac0 AS runtime

# Non-root user (UID 1000). Threat 3 mitigations.
RUN groupadd --gid 1000 arxmcp && useradd --uid 1000 --gid arxmcp ...

VOLUME /app/var/arxmcp
USER arxmcp
EXPOSE 7733

HEALTHCHECK --interval=30s --timeout=5s --start-period=5m --retries=3 \
    CMD curl -fsS http://127.0.0.1:7733/readyz || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "server.main"]
```

The PVC mountpoint in k8s MUST be `/app/var/arxmcp` (matching `WORKDIR /app` + `VOLUME` declaration).

### `server/config.py` — load-bearing constraints

`extra="forbid"` on the pydantic-settings model: **any unknown `ARXMCP_*` env var causes a startup `ValidationError`**. The ConfigMap must only set known config fields. The carve-out for ingest-only vars like `ARXMCP_CONTACT_EMAIL` is handled by a separate allow-list in `server/main.py` (`_KNOWN_INGEST_ENV_VARS`); do not add unknown vars to ConfigMap.

`reject_non_loopback_bind` validator:

> "Container deployments should expose the port via host port-mapping (`ports: \"127.0.0.1:7733:7733\"`) rather than binding to 0.0.0.0. If the container truly must bind 0.0.0.0 INTERNALLY... set `ARXMCP_UNSAFE_NETWORK_BIND=1`"

`LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})` — these are the only permitted bind hosts without the unsafe flag.

### `server/health.py` — probe semantics (verbatim from docstring)

> `GET /healthz` — **liveness**. Returns 200 as long as the process responds. Does NOT depend on resource warm state.
> `GET /readyz` — **readiness**. Returns 200 only after the embedder, LanceDB handle, and (if enabled) reranker are warm. Returns 503 with a JSON body listing which resource is not yet warm.

k8s probe mapping: `startupProbe` → `/healthz` (covers BGE-M3 download window); `readinessProbe` → `/readyz`; `livenessProbe` → `/healthz`.

### `server/main.py` — eager startup

> "**Why eager startup is load-bearing**. `/readyz` returns 503 until the embedder + LanceDB are warm. Lazy load would make the first `tools/call` hang for ~5–30s while a green `/readyz` lied."

The `startupProbe` needs a large `failureThreshold * periodSeconds` budget: BGE-M3 first-run download is ~2.3 GB (up to 5 min). Use `failureThreshold: 60, periodSeconds: 10` = 10-minute budget.

### `docs/install.md` — Windows section

Documents native Windows server run path and the `ARXMCP_BOOTSTRAP_MODE=1` bootstrap for empty corpus. The k8s runbook lands in `docs/ops/k3s-rancher-desktop.md` per doc placement rules (CLAUDE.md §1: operator-facing runbooks → `docs/ops/`).

### `tests/test_compose_server.py` — static-validation pattern

The existing compose test uses PyYAML parse + structural assertions (no Docker required). The new k8s test mirrors this: parse every `infra/k8s/*.yaml` with PyYAML, assert invariants. No `kubectl` dependency for the static test. Pattern: `_service()` helper + named assertion functions.

## Prior decisions and lessons

Recent git log confirms the Compose stack landed in `df36de8` (feat(infra): containerize server + fix wheel packaging). All IS-prefixed findings from `notebook-ops-hardening-m3` are closed: base-image SHA pin, non-root UID 1000, 127.0.0.1 bind, mem/cpu caps, no-new-privileges, cap_drop ALL. The `tests/test_compose_server.py` is the regression test pattern to mirror.

The `infra/observability/phoenix-compose.yml` used `@sha256` image pins — the same discipline applies to any base images referenced in k8s manifests (none needed here since we reuse the same `arxmcp-server` image).

**CLAUDE.md §4.7** — `latest` Docker image tags are banned: `imagePullPolicy: Never` requires a pinned local tag (e.g. `arxmcp-server:dev`). Never use `:latest`.

**GPG signing broken on this workstation** (from MEMORY.md / state.json): commits land unsigned after explicit user OK. Surface at commit time; never `--no-verify`.

**No `make` on Windows**: the check command is `ruff check . && uv run python -m pytest`. The static k8s test must use only stdlib + PyYAML (already a project dep) so it passes on Windows without any external binaries.

## External sources

**Rancher Desktop port forwarding** (docs.rancherdesktop.io/ui/port-forwarding): "port mappings are configured to the localhost and unprivileged ports > 1024" for non-admin access. The Privileged Service (admin install) is required to expose on interfaces other than 127.0.0.1. Without it, services are only reachable at `127.0.0.1`. This is the loopback preservation mechanism for this milestone.

**IMPORTANT FINDING**: The Traefik ingress example at docs.rancherdesktop.io/how-to-guides/traefik-ingress-example uses the node's internal IP (e.g. `192.168.x.x.sslip.io`) — NOT `127.0.0.1`. The Traefik LoadBalancer service in k3s gets an external IP that is the WSL2 node IP (a 172.x.x.x or 192.168.x.x address), which IS LAN-accessible. This is a **loopback threat model violation** if Traefik Ingress is used naively.

**Recommended mitigation**: Use **NodePort** instead of Traefik Ingress. A NodePort service exposes on the node's IP at a port in 30000-32767. With Rancher Desktop's port-forwarding UI (or automatic forwarding), the port is proxied to `127.0.0.1:<port>` on the Windows host. This gives a cleaner loopback story than Traefik Ingress. Alternatively, use Traefik Ingress but bind it to `127.0.0.1` host via a NodePort + portProxy pattern.

**K3s image import** (docs.k3s.io/add-ons/import-images): Place image tarballs in `/var/lib/rancher/k3s/agent/images/` — k3s auto-imports on startup and while running (k3s 1.29+). Command: `docker save arxmcp-server:dev | gzip > /var/lib/rancher/k3s/agent/images/arxmcp-server.tar.gz`. For containerd mode with nerdctl: `nerdctl --address=/run/k3s/containerd/containerd.sock --namespace=k8s.io load < arxmcp-server.tar`. The `k8s.io` namespace is critical — kubelet only uses images from that namespace.

**NetworkPolicy in k3s**: k3s ships with Flannel (VXLAN) + kube-router as the Network Policy controller. NetworkPolicy IS supported out of the box in k3s. Default-deny ingress + explicit Traefik-allow is achievable with standard `networking.k8s.io/v1` NetworkPolicy.

**Rancher Desktop + Docker Desktop coexistence**: Cannot run simultaneously. Rancher Desktop modifies `~/.kube/config` and `~/.docker/config.json`. The runbook MUST document: stop Docker Desktop before starting Rancher Desktop; use `docker context use rancher-desktop` / `docker context use desktop-linux` to switch. kubectl context is `rancher-desktop` while Rancher Desktop is active.

**k3s `local-path` StorageClass**: Ships by default with k3s. Provisions hostPath PVs in `/var/lib/rancher/k3s/storage/`. RWO access mode. Appropriate for single-node use.

## Recommendation

**Use a NodePort Service (port 7733 via host port-forward) rather than Traefik Ingress.**

Rationale: Traefik Ingress in Rancher Desktop binds to the WSL2 node's internal IP (172.x.x.x or 192.168.x.x), which is LAN-accessible — a direct violation of the loopback-only threat model from `08-security-observability-ops.md`. NodePort, forwarded to `127.0.0.1:7733` via the Rancher Desktop port-forwarding UI (or `kubectl port-forward` as fallback for testing), lands cleanly on loopback. The `HostValidationMiddleware` + `OriginValidationMiddleware` inside the server then provide the inner layer of defense. The NetworkPolicy default-deny + ingress-allow enforces cluster-internal isolation.

**Manifest structure:** `infra/k8s/` with the following files:
- `namespace.yaml` — `arxmcp` namespace
- `configmap.yaml` — all `ARXMCP_*` env vars (BIND_HOST=0.0.0.0, UNSAFE_NETWORK_BIND=1, BOOTSTRAP_MODE=1)
- `pvc.yaml` — RWO PVC using `local-path` StorageClass, 20Gi
- `deployment.yaml` — single replica, securityContext (runAsNonRoot, runAsUser/Group 1000, fsGroup 1000, readOnlyRootFilesystem true, capabilities.drop ALL, allowPrivilegeEscalation false, seccompProfile RuntimeDefault), startupProbe/readinessProbe/livenessProbe, resource limits 8Gi/4 CPU
- `service.yaml` — ClusterIP + separate NodePort service or a NodePort type directly
- `networkpolicy.yaml` — default-deny ingress + allow from NodePort/kube-system

**Deployment + PVC over StatefulSet**: no stable network identity is needed (single replica; the corpus is in the PVC, not in pod identity); Deployment is simpler and is the right choice.

**Image strategy**: provide a shell script `infra/k8s/scripts/load-image.sh` (or `.ps1`) that auto-detects Rancher Desktop's runtime mode:
- containerd mode: `nerdctl --address=/run/k3s/containerd/containerd.sock --namespace=k8s.io load < arxmcp-server.tar` (run from WSL2)
- dockerd mode: `docker save arxmcp-server:dev | gzip | wsl sudo tee /var/lib/rancher/k3s/agent/images/arxmcp-server.tar.gz`
- Use `imagePullPolicy: Never` + tag `arxmcp-server:dev` (no `:latest`).

**Static test** (`tests/test_k8s_manifests.py`): parse all `infra/k8s/*.yaml` with PyYAML, assert: no `:latest` tags, `imagePullPolicy: Never`, securityContext invariants, resource limits set, ARXMCP_UNSAFE_NETWORK_BIND + BOOTSTRAP_MODE in ConfigMap, NetworkPolicy present. No kubectl dependency. Mirrors `tests/test_compose_server.py` pattern.

**Operator runbook**: `docs/ops/k3s-rancher-desktop.md`, linked from `docs/ops/README.md`. Cover: Rancher Desktop install, Docker Desktop coexistence (stop one, switch context), WSL2 RAM requirement (≥10 GB), build/load step, `kubectl apply -f infra/k8s/`, port-forward or NodePort forwarding to `127.0.0.1:7733`, verify `/readyz`, security delta vs Compose.

**FLAG — CONFLICT**: The milestone brief (AC item 1) lists "Traefik Ingress (or NodePort per the exposure decision)" as equal alternatives. Based on external research, **Traefik Ingress in Rancher Desktop exposes on the WSL2 node IP (LAN-accessible), not on 127.0.0.1**. Using Traefik Ingress without additional host-side port binding would violate the loopback-only threat model. This brief recommends NodePort + Rancher Desktop port-forward as the loopback-safe choice. If the implementer chooses Traefik Ingress, they MUST document the LAN exposure delta and add a clear security warning.

## Open questions

1. **NodePort port number**: NodePorts are in 30000-32767. The shim is hardwired to `http://127.0.0.1:7733` in `~/.claude.json`. Rancher Desktop's port-forwarding UI can map any NodePort to `127.0.0.1:7733` on the Windows host — the runbook must walk the operator through this. The implementer must decide: (a) use a NodePort of e.g. 30733 and document the port-forward mapping to 7733, or (b) use Rancher Desktop's automatic port forwarding feature and let it assign. Recommendation: NodePort 30733 + document the Rancher Desktop UI port-forward to `127.0.0.1:7733`.

2. **`readOnlyRootFilesystem: true` with tini + pip cache**: The Dockerfile runtime stage leaves `/wheels` cleaned up, but tini may need a writable `/tmp`. Confirm whether `/tmp` needs a `tmpfs` emptyDir volume (yes, per the phoenix-compose.yml precedent: `tmpfs: [/tmp]`). Add `emptyDir: {}` for `/tmp` in the Deployment volumes.

3. **fsGroup 1000 + local-path PVC**: local-path provisioner creates hostPath directories owned by root. fsGroup 1000 causes the kubelet to `chown` the mounted directory. Verify this works on Rancher Desktop's WSL2 — it should since the kubelet runs as root inside WSL2.

4. **ARXMCP_NOTEBOOK env var**: the brief mentions documenting `ARXMCP_NOTEBOOK=<slug>` as an alternative. This is a straightforward ConfigMap patch — document it in the runbook but do not make it a manifest default (bootstrap mode is the correct default).

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| Container image build | Local (docker build) | Build `arxmcp-server:dev` from `docker/Dockerfile.server` |
| Container image load | Local k3s containerd (via WSL2) | Make image visible to k3s without external registry; `nerdctl --namespace k8s.io load` or tarball drop into `/var/lib/rancher/k3s/agent/images/` |
| kubectl apply | Local k3s cluster (Rancher Desktop) | Deploy `infra/k8s/` manifests; **GATED** — Rancher Desktop not yet installed; out of scope for implement phase |
| git push | origin/main | Land the milestone commits; **GATED** — per-event authorization required |
