# arXMCP on k3s (Rancher Desktop) — manifest set

Local single-node Kubernetes deployment of the `arxmcp-server` container,
parallel to the Docker Compose stack in [`../docker-compose.yml`](../docker-compose.yml).
It runs the **same** image built by [`../../docker/Dockerfile.server`](../../docker/Dockerfile.server)
— no separate build. Target runtime: **k3s via Rancher Desktop on Windows (WSL2)**.

> Full setup, the Docker Desktop ↔ Rancher Desktop coexistence caveat, the WSL2
> RAM requirement, and the security delta vs Compose live in the operator
> runbook: [`docs/ops/k3s-rancher-desktop.md`](../../docs/ops/k3s-rancher-desktop.md).

## Files

| File | Purpose |
|---|---|
| `namespace.yaml` | `arxmcp` namespace |
| `configmap.yaml` | server env (`ARXMCP_*` + `HF_HOME`) |
| `pvc.yaml` | `local-path` RWO volume for `/app/var/arxmcp` |
| `deployment.yaml` | single-replica server; full securityContext + 3 probes |
| `service.yaml` | NodePort `30733` (loopback-safe; see runbook) |
| `networkpolicy.yaml` | default-deny ingress except TCP/7733 |
| `scripts/load-image.sh` / `.ps1` | side-load the image into k3s' containerd |

## Apply order

```sh
# 1. Build + side-load the image into k3s (NOT a registry pull):
infra/k8s/scripts/load-image.sh          # or load-image.ps1 from PowerShell

# 2. Apply (the directory applies cleanly; namespace is created first):
kubectl apply -f infra/k8s/

# 3. Wait for warm (first run downloads BGE-M3 ~2.3 GB — up to ~10 min):
kubectl -n arxmcp rollout status deploy/arxmcp-server --timeout=12m
```

`kubectl apply` is a **gated** operation — run it yourself after Rancher Desktop
is installed; it is intentionally not automated.

## Key constraints baked into these manifests

- **`imagePullPolicy: Never`** + pinned tag `arxmcp-server:dev` (never `:latest`).
- **`ARXMCP_BIND_HOST=0.0.0.0` + `ARXMCP_UNSAFE_NETWORK_BIND=1`** — both required,
  or `server/config.py::reject_non_loopback_bind` crashes the pod.
- **Loopback at the host boundary** comes from Rancher Desktop forwarding the
  NodePort to `127.0.0.1` (non-admin install) — NOT from the manifests. This is
  the residual delta vs Compose's `127.0.0.1:` daemon-level bind.
- The static contract is verified by `tests/test_k8s_manifests.py`.
