# Implementation Summary — k3s-rancher-deploy-m1

**One-line:** Additive k3s manifest set + static test + operator runbook that runs the
existing `arxmcp-server` image on local k3s (Rancher Desktop/Windows), mirroring the
Compose hardening; `kubectl apply` gated/out of scope.

**Commit range:** `df36de8..e8601c9` (single feat commit, inline path)
**Branch:** main
**Check:** `ruff check .` clean; `tests/test_k8s_manifests.py` 14 passed, 1 skipped
(kubeconform — optional binary absent). FM-I Config-field cross-check RAN (not skipped).

## Acceptance criteria status

| AC | Status | Evidence |
|---|---|---|
| 1. Manifest set (ns, cm, workload+PVC, svc, exposure, netpol) | ✅ MET | `infra/k8s/{namespace,configmap,pvc,deployment,service,networkpolicy}.yaml` |
| 2. securityContext mirrors Compose hardening | ✅ MET | `deployment.yaml` pod+container securityContext; `test_deployment_security_context` |
| 3. Probes (startup/readiness/liveness) | ✅ MET | startupProbe `/readyz` 60×10s=10min; readiness `/readyz`; liveness `/healthz` |
| 4. resources map + WSL2 RAM doc | ✅ MET | limits 8Gi/4cpu; runbook §2 `.wslconfig` ≥12GB |
| 5. PVC local-path + bootstrap/bind/unsafe env | ✅ MET | `pvc.yaml` local-path RWO; `configmap.yaml` (+ HF_HOME added — see deviations) |
| 6. Image strategy, no registry, pin, no-fork | ✅ MET | `scripts/load-image.{sh,ps1}`; `imagePullPolicy: Never`; `arxmcp-server:dev` |
| 7. Host 127.0.0.1 + NetworkPolicy + residual delta | ✅ MET | NodePort→127.0.0.1 (RD forward); `networkpolicy.yaml`; runbook §7 |
| 8. Static test of invariants | ✅ MET | `tests/test_k8s_manifests.py` (14 assertions; FM-I cross-check) |
| 9. Operator runbook in docs/ops/ + linked | ✅ MET | `docs/ops/k3s-rancher-desktop.md`; linked from `docs/ops/README.md` |
| 10. Compose untouched, additive | ✅ MET | no edits to `infra/docker-compose.yml` / `docker/Dockerfile.server` |

## New / changed files
- New: `infra/k8s/{namespace,configmap,pvc,deployment,service,networkpolicy}.yaml`,
  `infra/k8s/README.md`, `infra/k8s/scripts/load-image.{sh,ps1}`,
  `tests/test_k8s_manifests.py`, `docs/ops/k3s-rancher-desktop.md`
- Changed: `docs/ops/README.md` (runbook link)
- Test: `tests/test_k8s_manifests.py` (15 functions; 14 pass + kubeconform skip)

## Deviations from the brief (all research-backed; see research-synthesis.md)
1. **AC1 exposure — chose NodePort, did NOT add a Traefik Ingress manifest.** The brief
   listed "Traefik Ingress (or NodePort)". Both researchers found Traefik Ingress in
   Rancher Desktop binds the WSL2 node's LAN IP and listens on port 80 — a loopback-only
   violation AND a shim port mismatch. NodePort 30733 (forwarded to 127.0.0.1) is the
   loopback-safe realization of the operator's "Traefik/NodePort" choice. (synthesis §3)
2. **HF_HOME / TRANSFORMERS_CACHE added to the ConfigMap** (not in the original AC5).
   Load-bearing: under `readOnlyRootFilesystem: true` the default HF cache is unwritable
   and the first-run BGE-M3 download crashes the pod. Pinning it onto the PVC also makes
   the weights survive restarts. (synthesis §2, FM-C)
3. **NetworkPolicy enforcement caveat.** The policy is present (AC1 satisfied as a
   declaration of intent + defense-in-depth). k3s enforces NetworkPolicy via its embedded
   kube-router controller (k3s-specific); the runbook §7 flags verify-at-deploy and names
   the host-boundary 127.0.0.1 forward as the primary control. (synthesis §3 divergence)

## External writes the orchestrator must authorize
| type | target | why | blocking |
|---|---|---|---|
| container image build/load | local k3s containerd (k8s.io ns) | make image visible to k3s; post Rancher Desktop install | no (out of scope) |
| kubectl apply | local k3s cluster | deploy manifests | GATED — out of scope this phase |
| git push | origin/main | land milestone commits | GATED — Phase 4 gate |

(Operator-manual, documented in runbook, not pipeline writes: edit `~/.claude.json` shim
URL → :30733; edit `%USERPROFILE%\.wslconfig` memory ≥12GB.)
