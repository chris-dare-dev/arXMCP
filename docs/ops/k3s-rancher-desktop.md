---
project: arxmcp
type: doc
tags:
- project/arxmcp
- type/doc
- authorship/agent-generated
authorship: agent-generated
---

# Deploy arXMCP on k3s via Rancher Desktop (Windows)

A local single-node Kubernetes deployment of the MCP server, parallel to the
[Docker Compose stack](../install.md#run-via-docker-compose-server-only-v0). It
runs the **same** image as Compose ([`docker/Dockerfile.server`](../../docker/Dockerfile.server))
and is **loopback-only by design**, like every other arXMCP surface.

Manifests: [`infra/k8s/`](../../infra/k8s/). This runbook is the operator-facing
setup; the manifest-level invariants are pinned by `tests/test_k8s_manifests.py`.

> **When to use this instead of Compose.** Only if you specifically want a local
> k3s/Kubernetes deployment. For most single-workstation use, the
> [Docker Compose path](../install.md#run-via-docker-compose-server-only-v0) is
> simpler and has a *tighter* loopback posture (see [§7](#7-security-delta-vs-compose)).

---

## 1. Prerequisites & the Docker Desktop coexistence caveat

- **Rancher Desktop** with Kubernetes (k3s) enabled. Install from
  <https://rancherdesktop.io>. During setup, enable Kubernetes and pick the
  **containerd** container runtime (gives you `nerdctl`, the simplest image-load
  path — `dockerd`/moby also works, see [§4](#4-build--side-load-the-image)).
- **Rancher Desktop and Docker Desktop cannot both run at once.** Both want to
  own the Docker socket and the WSL integration. Quit Docker Desktop before
  starting Rancher Desktop. Rancher Desktop rewrites `~/.kube/config` and the
  Docker CLI context; switch back and forth with:
  ```powershell
  docker context use rancher-desktop   # while Rancher Desktop is active
  docker context use desktop-linux      # to hand control back to Docker Desktop
  ```
- **`kubectl`** — bundled with Rancher Desktop. Confirm the context:
  ```powershell
  kubectl config current-context        # expect: rancher-desktop
  kubectl get nodes                     # expect: one Ready node
  ```

## 2. Size the WSL2 VM (required — OOM guard)

BGE-M3 + the reranker + LanceDB need real memory; the Deployment sets
`limits.memory: 8Gi`. The Rancher Desktop WSL2 VM defaults to ~8 GB (or half of
host RAM), which is too tight — the pod gets **OOMKilled** mid-warm. Give the VM
**≥ 12 GB** in `%USERPROFILE%\.wslconfig`:

```ini
[wsl2]
memory=12GB
processors=4
```

Then `wsl --shutdown` and restart Rancher Desktop. (You can also raise the limits
in Rancher Desktop's Preferences → Virtual Machine.)

## 3. Populate or bootstrap a corpus

The manifests ship with `ARXMCP_BOOTSTRAP_MODE=1`, so the server boots with an
**empty default corpus** (the MCP tools return `no_notebook_selected` until a
notebook is selected/ingested). This is the zero-prerequisite path — fine for a
first deploy. To serve an ingested notebook instead, add
`ARXMCP_NOTEBOOK: "<slug>"` to [`configmap.yaml`](../../infra/k8s/configmap.yaml)
and make sure that notebook's corpus is inside the PVC.

> Corpus data lives on the `local-path` PVC **inside the WSL2 VM**
> (`/var/lib/rancher/k3s/storage/...`), NOT on your Windows drive and NOT shared
> with the Compose `var/arxmcp` tree. Back it up separately.

## 4. Build & side-load the image

k3s pulls from its **own** containerd (namespace `k8s.io`); a plain Docker image
is invisible to it. The Deployment uses `imagePullPolicy: Never`, so the image
must be present in `k8s.io` **before** you apply. Use the helper:

```powershell
# Windows PowerShell (containerd mode → nerdctl.exe is on PATH):
infra\k8s\scripts\load-image.ps1
```
```sh
# or from the Rancher Desktop / WSL shell:
infra/k8s/scripts/load-image.sh
```

The script auto-detects the runtime: `nerdctl --namespace k8s.io build` (containerd)
builds straight into k3s; in `dockerd` mode it builds with docker and imports the
tarball into k3s' containerd. Verify:
```sh
nerdctl --namespace k8s.io images | grep arxmcp-server   # expect arxmcp-server:dev
```

> **Airgap-dir caveat (rebuilds).** If the loader falls back to the k3s airgap
> dir (`/var/lib/rancher/k3s/agent/images/`), k3s auto-imports **every** tarball
> there on each (re)start. The loader removes prior `arxmcp-server*.tar` before
> copying, but because the tag `arxmcp-server:dev` is reused across builds, after
> a rebuild always force the pod onto the new image with
> `kubectl -n arxmcp rollout restart deploy/arxmcp-server` — otherwise a cached
> image can shadow your rebuild ("I rebuilt but it runs old code").

## 5. Apply the manifests

```sh
kubectl apply -f infra/k8s/
kubectl -n arxmcp rollout status deploy/arxmcp-server --timeout=12m
```

First run downloads BGE-M3 (~2.3 GB) onto the PVC; the `startupProbe` allows a
10-minute warm window. Subsequent restarts are ~30 s (weights are cached on the PVC).

## 6. Point the MCP shim at the NodePort, then verify

The Service is a **NodePort `30733`**, which Rancher Desktop forwards to
`127.0.0.1:30733` on the Windows host. The stdio shim defaults to `:7733`, so
update `~/.claude.json` (`%USERPROFILE%\.claude.json` on Windows):

```json
{ "mcpServers": { "arxmcp": {
  "command": "arxmcp-shim",
  "args": ["--server", "http://127.0.0.1:30733"]
}}}
```

Verify readiness (200 once warm):
```powershell
curl.exe -fsS http://127.0.0.1:30733/readyz
```

## 7. Security delta vs Compose

arXMCP is loopback-only. **Compose** enforces that at the Docker daemon
(`127.0.0.1:7733:7733`) with no override path. **k3s here** relies on two things
instead — know them:

1. **Host boundary = Rancher Desktop's port forward.** A **non-admin** Rancher
   Desktop install forwards NodePorts to `127.0.0.1` only. Installing the
   **Privileged Service** (admin) forwards to **all interfaces (`0.0.0.0`)**,
   exposing port 30733 to the LAN. For loopback-only, use the non-admin install,
   or add a Windows Firewall inbound rule blocking 30733 from non-loopback.
   Confirm with `netstat -an | findstr 30733` (expect `127.0.0.1:30733`).
2. **NetworkPolicy.** [`networkpolicy.yaml`](../../infra/k8s/networkpolicy.yaml)
   default-denies ingress except TCP/7733. k3s enforces NetworkPolicy via its
   embedded **kube-router** controller (this is k3s-specific — plain Flannel does
   not). Verify enforcement on your build: `kubectl get pods -n kube-system`
   should list a kube-router pod. On a single-node single-user cluster this is
   defense-in-depth; the host-boundary forward above is the primary control.
   **Egress is intentionally unrestricted** — the policy constrains *ingress*
   only, because the server must reach huggingface.co (BGE-M3 download) and
   arXiv/OpenAlex/INSPIRE (ingest). "Default-deny" refers to ingress.

The pod binds `0.0.0.0` **inside** the cluster (required; `ARXMCP_UNSAFE_NETWORK_BIND=1`
acknowledges it) exactly as the Compose container does — a WARN log at startup is
expected.

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Pod `ImagePullBackOff` | image not in k8s.io containerd ns | re-run the loader ([§4](#4-build--side-load-the-image)); confirm `nerdctl -n k8s.io images` |
| Pod `CrashLoopBackOff`, `Read-only file system` on startup | HF cache on read-only rootfs | confirm `HF_HOME` is in the ConfigMap (it is by default) |
| Pod `CrashLoopBackOff`, `PermissionError` writing `/app/var/arxmcp` | PVC root-owned | confirm pod `securityContext.fsGroup: 1000` (default) |
| Pod `OOMKilled` | WSL2 VM RAM too low | raise `.wslconfig` memory ≥ 12 GB ([§2](#2-size-the-wsl2-vm-required--oom-guard)) |
| Pod restarts in a loop on first deploy | warm window too short | the `startupProbe` allows 10 min; check `kubectl -n arxmcp describe pod` events |
| Container exits, `ValidationError ... Extra inputs are not permitted` | unknown `ARXMCP_*` var in ConfigMap | every `ARXMCP_*` key must be a `server/config.py` field; remove the stray var |
| `curl 127.0.0.1:30733` refused | shim/URL or forward | confirm NodePort 30733; check Rancher Desktop port-forward; verify `kubectl get svc -n arxmcp` |
| Pod `CrashLoopBackOff`, `Read-only file system` on a **non-HF** path (e.g. `~/.cache/fontconfig`) | a library writes under `$HOME` outside the HF cache | `XDG_CACHE_HOME`/`MPLCONFIGDIR` cover the common cases (set by default); add the new path to `configmap.yaml`. The static tests prove authoring only — this read-only boot is verified at `kubectl apply` (§5), not by `pytest`. |
| Rebuilt the image but the pod runs old code | stale tarball in the k3s airgap dir, or a cached image under the reused `:dev` tag | the loader pre-cleans `arxmcp-server*.tar`; force the new image with `kubectl -n arxmcp rollout restart deploy/arxmcp-server` |

### Teardown

```sh
kubectl delete -f infra/k8s/         # removes the namespace + all objects
```
The PVC's backing data is reclaimed per the `local-path` reclaim policy; copy out
anything under `/app/var/arxmcp` first if you need to keep it.
