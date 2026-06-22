# Critique — k3s-rancher-deploy-m1

**Critic:** infra-safety
**Generated:** 2026-06-21T23:55:00Z
**Commit range:** df36de82e8bb558b824938fcc9bca9ffad75f0f8..e8601c9a88f181d2db5187b08f500c6cde22147c
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: one MEDIUM finding (service account token auto-mount not
  disabled) and one LOW finding (sudo in airgap fallback script); no CRITICAL or HIGH.
- 0 CRITICAL, 0 HIGH, 1 MEDIUM, 1 LOW across all four adapted axes.
- The k3s manifest set faithfully mirrors the Compose hardening: non-root UID 1000,
  `cap_drop: ALL`, `readOnlyRootFilesystem`, `allowPrivilegeEscalation: false`,
  `seccompProfile: RuntimeDefault`, resource limits, and three probes are all present.
- `imagePullPolicy: Never` and pinned tag `arxmcp-server:dev` are enforced in the
  manifest and guarded in both load scripts.
- Bind/exposure axis is clean: `ARXMCP_BIND_HOST=0.0.0.0` +
  `ARXMCP_UNSAFE_NETWORK_BIND=1` are present in the ConfigMap, the Traefik-avoidance
  rationale is documented in both the manifest and the runbook, and the LAN-exposure
  residual (Privileged Service / admin install) is called out explicitly.
- Selector and label consistency is correct across Deployment, Service, and
  NetworkPolicy — a common source of silent breakage that was handled correctly.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### IS1 — automountServiceAccountToken not disabled in Deployment

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** infra/k8s/deployment.yaml (spec.template.spec — no `automountServiceAccountToken` field present)
- **What:** The Deployment does not set `automountServiceAccountToken: false` at the
  pod spec level. By default Kubernetes mounts a service account token at
  `/var/run/secrets/kubernetes.io/serviceaccount/token` in every pod. The arXMCP
  server does not make any Kubernetes API calls; the mounted token is unused and
  expands the blast radius if the pod is ever compromised.
- **Why it matters:** Any code path that can read files within the container (including
  a hostile LaTeX fixture piped through the ingest path, per Threat 3 in
  `08-security-observability-ops.md`) can read the service account token and use it to
  enumerate or manipulate cluster resources. The single-node k3s cluster has limited
  blast radius today, but the token is a credential that should not exist if it is not
  needed.
- **Proposed fix:** Add `automountServiceAccountToken: false` to the pod spec in
  `infra/k8s/deployment.yaml`, directly under `spec.template.spec`:
  ```yaml
  spec:
    automountServiceAccountToken: false
    securityContext:
      runAsNonRoot: true
      ...
  ```
  This is a 1-line addition; no other manifest changes are required. Update
  `tests/test_k8s_manifests.py` to assert `automountServiceAccountToken is False`.
- **Regression guard:** The manifest test (`tests/test_k8s_manifests.py`) should assert
  `deployment.spec.template.spec.automountServiceAccountToken is False`. A missing
  assertion would allow a future edit to silently re-enable the mount.

---

### IS2 — sudo in airgap fallback path of load-image.sh

- **Severity:** LOW
- **Source:** infra-safety
- **File:** infra/k8s/scripts/load-image.sh:62-63
- **What:** The airgap fallback branch (`ctr` unavailable, k3s socket absent) uses
  `sudo mkdir -p "$AIRGAP_DIR"` and `sudo cp "$TARBALL" "$AIRGAP_DIR/arxmcp-server.tar"`
  where `$AIRGAP_DIR=/var/lib/rancher/k3s/agent/images`. The airgap directory is
  root-owned; writing to it without sudo is not possible on a standard system.
- **Why it matters:** The sudo calls are scoped to a non-default fallback path that only
  fires when both `nerdctl` (primary) and `ctr`+socket (secondary) are unavailable.
  The script comments acknowledge this ("writing there needs root"). The risk is low:
  the script is operator-invoked, not run in CI or as a daemon, and the `set -euo
  pipefail` header means a failure aborts immediately. Noted for completeness under the
  infra-safety scope; the Axis 4 `sudo` prohibition is specifically targeted at Makefile
  targets, not shell scripts where root-owned paths have no alternative.
- **Proposed fix:** Add a comment immediately above the `sudo` calls stating that this
  path is an operator-only last resort and that the operator must review what they are
  authorizing. The current comment ("writing there needs root") is present but terse.
  Optionally gate the sudo block with a prompt:
  ```sh
  read -r -p "About to sudo-write to $AIRGAP_DIR. Proceed? [y/N] " yn
  [[ "$yn" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }
  ```
- **Regression guard:** N/A (LOW — defer).

---

## What was done well

- **Complete securityContext at both pod and container levels.** `runAsNonRoot: true`,
  `runAsUser: 1000`, `runAsGroup: 1000`, `fsGroup: 1000` at pod level;
  `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`,
  `capabilities.drop: [ALL]` at container level. This is the full hardening surface
  from the Compose stack and `08-security-observability-ops.md`, translated correctly
  to k8s idioms (deployment.yaml:35-55).
- **`seccompProfile: RuntimeDefault` present.** Explicitly set at the pod
  `securityContext` level (deployment.yaml:41-43), consistent with the Compose
  `security_opt: no-new-privileges` spirit and going beyond it.
- **`imagePullPolicy: Never` with a pinned non-`:latest` tag.** The deployment uses
  `arxmcp-server:dev` and `imagePullPolicy: Never` (deployment.yaml:45-46), preventing
  any registry pull of a potentially stale or substituted image. Both load scripts
  guard against `:latest` and untagged refs with explicit error exits
  (load-image.sh:26-30, load-image.ps1:23-25).
- **`set -euo pipefail` in the bash script and `$ErrorActionPreference = 'Stop'` in
  the PowerShell script.** Both scripts abort immediately on any command failure
  (load-image.sh:18, load-image.ps1:22). The bash script additionally verifies the
  image is actually visible in the k8s.io namespace after the nerdctl build
  (load-image.sh:47-49) — catching a silent build success with a missing image.
- **`strategy: Recreate` justified for the RWO PVC.** The comment at deployment.yaml:20
  explains that `RollingUpdate` would deadlock because the new pod cannot attach an
  already-attached `ReadWriteOnce` PVC. The correct strategy is documented and applied.
- **Label and selector consistency across all three manifest consumers.** Deployment
  `matchLabels`, Service `selector`, and NetworkPolicy `podSelector` all use the same
  `app.kubernetes.io/name: arxmcp` + `app.kubernetes.io/component: server` pair.
  A label mismatch here would silently break Service endpoints or NetworkPolicy
  enforcement with no startup error.
- **Traefik avoidance documented and reasoned.** The service.yaml header explains why
  NodePort was chosen over a Traefik Ingress (Traefik binds the WSL2 node's LAN IP and
  mismatches :7733), and the residual delta vs Compose's daemon-level loopback bind is
  documented in the runbook at docs/ops/k3s-rancher-desktop.md §7.
- **`ARXMCP_UNSAFE_NETWORK_BIND=1` present alongside `ARXMCP_BIND_HOST=0.0.0.0`.** The
  ConfigMap carries both vars (configmap.yaml:25-26) with a detailed inline comment
  tracing to `server/config.py::reject_non_loopback_bind`, matching the Compose
  precedent. The loopback contract is preserved at the host boundary via Rancher
  Desktop's NodePort forward.
- **`HF_HOME` redirected onto the PVC.** Without this, `readOnlyRootFilesystem: true`
  would cause the first-run BGE-M3 download to crash with EROFS. The ConfigMap includes
  both `HF_HOME` and `TRANSFORMERS_CACHE` (configmap.yaml:36-37) with a clear
  rationale comment.
- **`startupProbe` on `/readyz` (not `/healthz`) with a 10-minute window.** The probe
  comment at deployment.yaml:68-75 correctly explains why `/healthz` is wrong here:
  it returns 200 in seconds and would not protect the BGE-M3 warm window. The
  probe gives 60 * 10s = 10 minutes before liveness can kill a warming pod.

## Recommended rectification order

1. **IS1 (MEDIUM):** Add `automountServiceAccountToken: false` to `infra/k8s/deployment.yaml`
   pod spec, then add a corresponding assertion to `tests/test_k8s_manifests.py`. This
   is a 2-line production change and a 1-line test addition — well within the ≤30 LOC
   threshold for MEDIUM findings.
2. **IS2 (LOW):** Optionally add a confirmation prompt or expanded operator comment
   before the airgap-fallback `sudo` block in `infra/k8s/scripts/load-image.sh`.
   Defer if the airgap path is never expected to be used on this workstation.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
