# Research Synthesis — k3s-rancher-deploy-m1

**Merged by:** orchestrator (main session)
**Inputs:** research-brief-1.md (in-codebase first), research-brief-2.md (external + failure modes)
**Convergence:** HIGH — both briefs independently recommend the same architecture.

---

## 1. Decision summary (what the implementer builds)

Additive Kubernetes manifests under `infra/k8s/` that run the **same** `arxmcp-server`
image (built by `docker/Dockerfile.server`) on a local single-node **k3s** cluster
(Rancher Desktop, WSL2, Windows). Compose path untouched. Live `kubectl apply` is GATED
and out of scope for the implement phase — manifests are authored + statically validated only.

| Decision | Resolution | Source |
|---|---|---|
| Workload kind | **Deployment + RWO PVC**, `replicas: 1` (NOT StatefulSet — no stable identity needed) | both briefs agree |
| Exposure | **NodePort `30733`** (NOT Traefik Ingress — see §3) | both briefs agree |
| Shim impact | Operator updates `~/.claude.json` `--server` → `http://127.0.0.1:30733` | both briefs |
| Image into k3s | Build with `nerdctl build -n k8s.io` (containerd) OR airgap-dir tarball; `imagePullPolicy: Never`, tag `arxmcp-server:dev` (never `:latest`) | both briefs |
| Storage | k3s default `local-path` StorageClass, RWO, 20Gi; data lives **inside the WSL2 VM** (not on NTFS) | both briefs |
| Static test | `tests/test_k8s_manifests.py` — PyYAML `yaml.safe_load` + assertions, mirroring `tests/test_compose_server.py`. **PyYAML 6.0.3 confirmed available** (`pyproject.toml:112` `pyyaml>=6.0`). No `kubectl`/`kubeconform` binary required (optional skipped check). | both briefs |
| Runbook | `docs/ops/k3s-rancher-desktop.md`, linked from `docs/ops/README.md` (CLAUDE.md §1 doc placement) | both briefs |

### Manifest file set (`infra/k8s/`)
- `namespace.yaml` — `arxmcp` namespace
- `configmap.yaml` — env (see §2)
- `pvc.yaml` — RWO `local-path`, 20Gi
- `deployment.yaml` — single replica + full securityContext + 3 probes + resources + volumes
- `service.yaml` — `type: NodePort`, `nodePort: 30733`, targetPort 7733
- `networkpolicy.yaml` — default-deny ingress + allow (see §3 on enforcement caveat)
- `scripts/load-image.sh` (+ `.ps1` companion) — runtime-mode-detecting image load

---

## 2. ConfigMap env — EXACT set (load-bearing)

Quoting `infra/docker-compose.yml` verbatim — these three are mandatory and the
**0.0.0.0 + UNSAFE pair is non-negotiable** (omitting the unsafe flag crashes startup):

```yaml
ARXMCP_BIND_HOST: "0.0.0.0"          # in-cluster bind is correct; host-loopback is the k3s/RD layer
ARXMCP_UNSAFE_NETWORK_BIND: "1"      # required or reject_non_loopback_bind aborts (FM-F)
ARXMCP_BOOTSTRAP_MODE: "1"           # boot with empty default corpus
```

**CRITICAL ADDITION from brief-2 (not in the original brief's AC5):**
```yaml
HF_HOME: "/app/var/arxmcp/hf-cache"          # redirect HuggingFace cache into the PVC
TRANSFORMERS_CACHE: "/app/var/arxmcp/hf-cache"  # older-transformers compat
```
Rationale: with `readOnlyRootFilesystem: true`, the default HF cache at
`/home/arxmcp/.cache/huggingface/` is unwritable → first boot crashes
(`OSError: [Errno 30] Read-only file system`, FM-C). Putting it on the PVC also means the
~2.3 GB BGE-M3 weights survive pod restarts (an emptyDir would re-download every restart).

**`extra="forbid()` hazard (`server/config.py`):** the server's pydantic-settings model uses
`extra="forbid"` under the `ARXMCP_` env prefix — any **unknown `ARXMCP_*`** var crashes startup
(`ValidationError`, FM-I). `HF_HOME`/`TRANSFORMERS_CACHE` are NOT `ARXMCP_`-prefixed, so the
settings model ignores them — they are plain process env and safe. **Do NOT** add
`ARXMCP_CONTACT_EMAIL` (ingest-only). The static test (AC8) MUST assert every `ARXMCP_*`
ConfigMap key maps to a real field in `server/config.py`.

---

## 3. Exposure + the loopback-only threat model (the security crux)

Operator chose "Traefik Ingress / NodePort." **Both briefs independently concluded the
NodePort half is the loopback-safe choice and Traefik Ingress is NOT:**

> brief-1: "Traefik Ingress in Rancher Desktop binds to the WSL2 node's internal IP
> (172.x/192.168.x), which is LAN-accessible — a direct violation of the loopback-only
> threat model." Traefik also listens on port **80**, not 7733 — a port mismatch for the shim.

**Resolution: NodePort `30733`, forwarded by Rancher Desktop to `127.0.0.1:30733`.**
Rancher Desktop's non-admin install forwards ports to `127.0.0.1` only (brief-2: Rancher
Desktop issue #6760 — "Ports forwarded through the UI listen on 127.0.0.1, not 0.0.0.0").
The server's own `HostValidationMiddleware` + `OriginValidationMiddleware` are the inner
defense layer.

**Residual exposure delta vs Compose (must be documented in the runbook):**
- Compose enforces loopback at the Docker daemon (`127.0.0.1:7733:7733`) with no override path.
- k3s/Rancher Desktop loopback depends on **NOT** installing the Privileged Service (admin
  mode forwards NodePorts to `0.0.0.0` / all interfaces — FM-G). The runbook must instruct:
  non-admin install for loopback-only, or a Windows Firewall inbound block on 30733.

### ⚖️ Divergence resolved — NetworkPolicy enforcement on k3s
The briefs disagree on a load-bearing fact:
- **brief-1:** "k3s ships Flannel (VXLAN) + **kube-router** as the Network Policy controller.
  NetworkPolicy IS supported out of the box."
- **brief-2 (FM-H):** "k3s does NOT enforce NetworkPolicy with Flannel by default … the
  NetworkPolicy manifest may be silently unenforced."

**Orchestrator adjudication → brief-1 is correct for k3s specifically.** Upstream Kubernetes
with *plain* Flannel does not enforce NetworkPolicy (brief-2's claim is true *there*), but
**k3s embeds kube-router's network-policy controller and enforces NetworkPolicy by default** —
this is the documented k3s behavior. brief-2 conflated upstream-Flannel with k3s-Flannel.
**Action:** ship the default-deny + allow NetworkPolicy (satisfies AC1), add a YAML comment
noting enforcement is provided by k3s' embedded kube-router and should be **verified on the
specific Rancher Desktop k3s build at deploy time**, and state in the runbook that the
**host-boundary 127.0.0.1 forward is the primary defense regardless of CNI**. This keeps the
manifest honest without overclaiming.

---

## 4. Pod spec invariants (mirror the Compose hardening)

`securityContext` (pod + container) — maps `cap_drop: ALL` + `no-new-privileges` + UID 1000:
```yaml
# pod-level
runAsNonRoot: true
runAsUser: 1000
runAsGroup: 1000
fsGroup: 1000            # FM-B: makes kubelet chown the local-path PVC so UID 1000 can write
seccompProfile: { type: RuntimeDefault }
# container-level
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities: { drop: ["ALL"] }
```

Volumes:
- PVC → `/app/var/arxmcp` (matches `VOLUME /app/var/arxmcp` + `WORKDIR /app` in the Dockerfile)
- `emptyDir` → `/tmp` (tini/Python temp; required under readOnlyRootFilesystem — phoenix-compose
  `tmpfs: [/tmp]` precedent, brief-1 OQ2)
- HF cache lives on the PVC via `HF_HOME` (§2), not a separate volume

Probes (resolved divergence — see note):
```yaml
startupProbe:   { httpGet: { path: /readyz, port: 7733 }, failureThreshold: 60, periodSeconds: 10 }  # 10-min BGE-M3 window
readinessProbe: { httpGet: { path: /readyz, port: 7733 }, periodSeconds: 15 }
livenessProbe:  { httpGet: { path: /healthz, port: 7733 }, periodSeconds: 30 }
```
> **Divergence resolved:** brief-1 put `startupProbe → /healthz`; brief-2 put
> `startupProbe → /readyz`. `/healthz` returns 200 as soon as the process responds (seconds),
> so it would NOT cover the ~5-min BGE-M3 warm window. **Use `/readyz` for startupProbe** so
> "started" means "warm" and liveness can't restart the pod mid-download. `server/health.py`:
> `/healthz` = liveness (200 if process responds), `/readyz` = readiness (200 only once
> embedder + LanceDB + reranker warm, else 503).

Resources (map `mem_limit: 8g` / `cpus: 4.0`):
```yaml
requests: { memory: "2Gi", cpu: "1" }
limits:   { memory: "8Gi", cpu: "4" }
```
Runbook MUST require the WSL2 VM be given ≥12 GB via `%USERPROFILE%\.wslconfig` (`[wsl2]\nmemory=12GB`)
or BGE-M3 + reranker OOMKill (FM-D).

---

## 5. Failure modes to design against (union, deduped)

| ID | Trigger | Mitigation (baked into manifests/docs) |
|---|---|---|
| FM-A | Image not in k8s.io containerd ns | `nerdctl build -n k8s.io` / airgap dir; `imagePullPolicy: Never` |
| FM-B | local-path PVC root-owned | `fsGroup: 1000` |
| FM-C | readOnlyRootFS breaks HF cache | `HF_HOME`/`TRANSFORMERS_CACHE` on PVC + `/tmp` emptyDir |
| FM-D | WSL2 RAM too low | `limits.memory 8Gi` + `.wslconfig` ≥12GB in runbook |
| FM-E | startupProbe window too short | `/readyz` failureThreshold 60 × 10s = 10 min |
| FM-F | missing UNSAFE_NETWORK_BIND | ConfigMap sets both; test asserts both |
| FM-G | admin install → NodePort on 0.0.0.0 (LAN) | runbook: non-admin install or firewall block; documented delta |
| FM-H | NetworkPolicy enforcement | k3s kube-router enforces by default — verify on RD build; host loopback is primary defense |
| FM-I | unknown ARXMCP_* var | ConfigMap keys cross-checked vs Config fields; test asserts |
| FM-J | NodePort ≠ shim port 7733 | runbook: update `~/.claude.json` → `:30733` |

---

## 6. Open questions (deduped — for the implementer)

1. **NodePort number** → resolved to **30733**; document the shim `~/.claude.json` update.
2. **startupProbe path** → resolved to **`/readyz`** (§4).
3. **HF_HOME in ConfigMap** → resolved **yes** (§2); critical for readOnlyRootFilesystem.
4. **PyYAML for tests** → resolved **available** (6.0.3, declared `pyyaml>=6.0`); use `yaml.safe_load`.
5. **fsGroup + local-path chown on WSL2** → expected to work (kubelet runs as root in WSL2);
   verify at deploy. Not a blocker for authoring manifests.
6. **NetworkPolicy enforcement on the exact Rancher Desktop k3s build** → verify at deploy;
   primary defense is the host 127.0.0.1 forward.
7. **ARXMCP_NOTEBOOK=<slug>** → document as a runbook alternative to bootstrap mode; NOT a
   manifest default.

No open question blocks manifest authoring. All are either resolved or verify-at-deploy.

---

## 7. External writes the implementation will require (deduped union)

| Type | Target | Why | Gated? | In implement scope? |
|---|---|---|---|---|
| container image build/load | local k3s containerd (k8s.io ns) | make image visible to k3s, no registry | local | NO — after Rancher Desktop install |
| kubectl apply | local k3s cluster (Rancher Desktop) | deploy manifests | **YES** | NO — gated, post-install |
| git push | origin/main | land milestone commits | **YES** | NO — Phase 4 gate |
| edit `~/.claude.json` | operator home dir | shim `--server` → `:30733` | operator manual | NO — documented in runbook |
| edit `%USERPROFILE%\.wslconfig` | Windows host | WSL2 memory ≥12GB | operator manual | NO — documented in runbook |

The implement phase produces **local commits only** (manifests + test + runbook). Nothing in
the implement phase touches a live cluster or the network.

---

## 8. Orchestrator synthesis note (divergences resolved)

1. **startupProbe path** — `/healthz` (b1) vs `/readyz` (b2) → **chose `/readyz`** (covers the
   warm window; `/healthz` succeeds too early to protect against liveness restarts).
2. **NetworkPolicy enforcement** — "supported OOTB via kube-router" (b1) vs "Flannel ignores it"
   (b2) → **b1 correct for k3s** (embedded kube-router); ship policy + comment + verify-at-deploy
   note; host loopback is primary defense.
3. **HF_HOME** — surfaced only by b2; **adopted into the mandatory ConfigMap** (load-bearing for
   readOnlyRootFilesystem — without it the pod crashes on first boot).
4. **Exposure** — both rejected Traefik Ingress for LAN exposure; **NodePort 30733** adopted as
   the loopback-safe realization of the operator's "Traefik/NodePort" choice. The operator's
   stated preference for an always-on path is honored (NodePort is always-on; no `kubectl
   port-forward` process needed), while the LAN-exposure risk is mitigated to non-admin-install
   + documented delta.
5. **local-path data dir** — minor factual difference (`/var/lib/rancher/k3s/storage` vs
   `/opt/local-path-provisioner`); non-load-bearing, noted as "inside WSL2 VM, version-dependent."
