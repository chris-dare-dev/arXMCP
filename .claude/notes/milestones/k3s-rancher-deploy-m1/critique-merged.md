# Critique (merged) — k3s-rancher-deploy-m1

**Critics:** adversary, infra-safety
**Commit range:** df36de82e8bb558b824938fcc9bca9ffad75f0f8..e8601c9a88f181d2db5187b08f500c6cde22147c
**Merged verdict:** SHIP-WITH-FIXES

## Executive summary (orchestrator)

- Both critics returned **SHIP-WITH-FIXES** with **0 CRITICAL, 0 HIGH**. The manifest
  set is internally consistent (labels/selectors/ports/claimName all line up), the
  security story holds at the application layer (not just the RD forward), and the
  static test is honest.
- Raw finding counts: **0 CRITICAL, 0 HIGH, 5 MEDIUM, 4 LOW** (F2 and IS1 are the
  SAME issue counted by both critics — see Cross-critic agreement).
- The one cross-critic agreement — `automountServiceAccountToken` not disabled
  (F2 / IS1) — is the top rectification item: a 1-line manifest hardening + test.
- The highest operator-impact MEDIUM is F1: `readOnlyRootFilesystem: true` runs the
  image for the first time, and only the HuggingFace cache is redirected — non-HF
  `~/.cache` writers would hard-crash under EROFS. Cheap fix via `XDG_CACHE_HOME`.
- Everything else is doc-honesty (F3, F4, F6), script robustness (F4, F7), a
  frontmatter convention (F5), and a sudo comment (IS2) — all cheap, all in files I'm
  already editing, so folded in.

## Severity calibration

| level | meaning | Phase-4 action |
|---|---|---|
| CRITICAL | data loss / security regression / broken invariant | always fix |
| HIGH | wrong behavior on common path | always fix |
| MEDIUM | subtle correctness / missing test / latent foot-gun | fix if cheap (≤30 LOC) |
| LOW | style / naming / micro-robustness | defer (fold opportunistically) |

## Cross-critic agreement

- **F2 ≡ IS1** — `automountServiceAccountToken: false` missing in `deployment.yaml`
  pod spec. Flagged independently by BOTH adversary (F2) and infra-safety (IS1).
  **Highest priority.**

## Cross-critic agreement

- **infra/k8s/scripts/load-image.sh:57-62** — flagged by adversary, infra-safety (findings: F4, IS2; severities: LOW, MEDIUM)

<!-- end:cross-critic-agreement -->

## Findings

### F1 — readOnlyRootFilesystem first-exercise: only HF cache redirected
- **Severity:** MEDIUM
- **Source:** adversary
- **File:** infra/k8s/deployment.yaml:61
- **What:** `readOnlyRootFilesystem: true` runs the image under a read-only root FS for
  the first time (Compose never set `--read-only`). Only `HF_HOME`/`TRANSFORMERS_CACHE`
  are redirected; `HOME=/home/arxmcp` is on the read-only FS, so any non-HF library that
  writes `~/.cache` / `~/.config` (fontconfig, matplotlib, torch hub) crashes with EROFS.
- **Fix:** Add `XDG_CACHE_HOME=/app/var/arxmcp/.cache` + `MPLCONFIGDIR=/tmp/mpl` to the
  ConfigMap (non-`ARXMCP_`-prefixed → safe vs `extra="forbid"`). Document the read-only
  boot-risk in runbook §8.
- **Regression guard:** assert the XDG cache redirect env is present in the test.

### F2 — default ServiceAccount token auto-mounted (≡ IS1)
- **Severity:** MEDIUM
- **Source:** adversary (also infra-safety IS1)
- **File:** infra/k8s/deployment.yaml:32
- **What:** No `automountServiceAccountToken: false`; k8s mounts an unused SA token that
  expands blast radius on a process compromise. The server makes no k8s API calls.
- **Fix:** Add `automountServiceAccountToken: false` to `spec.template.spec`.
- **Regression guard:** assert it is `False` in `test_deployment_security_context`.

### F3 — static test cannot distinguish "field present" from "pod boots"
- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_k8s_manifests.py:119
- **What:** The static test proves authoring, not runtime; a manifest that boot-crashes
  under read-only rootfs still passes green, overstating AC2/AC5 evidence.
- **Fix:** Add a `RUNTIME-UNVERIFIED` note to the test docstring + a runbook §8 row that
  the read-only-rootfs boot is operator-acceptance (gated `kubectl apply`). Folds into F1.
- **Regression guard:** F1's env assertion is the partial guard; full coverage is gated.

### F4 — load-image.sh airgap fallback: stale tarball / :dev reuse
- **Severity:** MEDIUM
- **Source:** adversary
- **File:** infra/k8s/scripts/load-image.sh:57
- **What:** Airgap fallback `sudo cp`s to a fixed `arxmcp-server.tar`; the EXIT trap only
  removes the mktemp source. k3s auto-imports every tar in the airgap dir on restart, so
  a stale tarball can silently shadow a rebuild under the same `:dev` tag.
- **Fix:** `sudo rm -f "$AIRGAP_DIR"/arxmcp-server*.tar` before the cp; document the
  restart-imports-all + `:dev` tag-reuse caveat in runbook §4 / §8.
- **Regression guard:** N/A (shell); runbook caveat.

### F5 — runbook frontmatter `type: runbook` diverges from `docs/ops/` convention
- **Severity:** LOW
- **Source:** adversary
- **File:** docs/ops/k3s-rancher-desktop.md:3
- **What:** Siblings use `type: doc` / `tags: [type/doc]`; this uses `type: runbook`.
- **Fix:** Change to `type: doc` / `type/doc`. (Fold while editing the runbook.)

### F6 — NetworkPolicy egress unrestricted; "default-deny" naming could mislead
- **Severity:** LOW
- **Source:** adversary
- **File:** infra/k8s/networkpolicy.yaml:30
- **What:** `policyTypes: [Ingress]` only; egress open (correct, for model/ingest
  fetches) but the name/README could read as a broader lockdown.
- **Fix:** Add one runbook §7 line noting egress is intentionally open. (Fold.)

### F7 — `nerdctl images | grep` verification fragile
- **Severity:** LOW
- **Source:** adversary
- **File:** infra/k8s/scripts/load-image.sh:43
- **What:** grep over table output can false-negative across nerdctl output formats.
- **Fix:** Use `nerdctl --namespace k8s.io image inspect "$IMAGE" >/dev/null 2>&1`. (Fold.)

### IS1 — automountServiceAccountToken not disabled (≡ F2)
- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** infra/k8s/deployment.yaml (spec.template.spec)
- **What / Fix / Guard:** identical to F2 above; fixed once.

### IS2 — sudo in airgap fallback path of load-image.sh
- **Severity:** LOW
- **Source:** infra-safety
- **File:** infra/k8s/scripts/load-image.sh:62-63
- **What:** Airgap fallback uses `sudo` to write the root-owned k3s airgap dir (no
  alternative; comment present but terse).
- **Fix:** Expand the operator comment above the sudo block (no blocking prompt — would
  break non-interactive use). (Fold.)

## What was done well (deduped)

- Security axis is genuinely sound: the in-cluster `0.0.0.0` + `UNSAFE` pair mirrors
  Compose, and the inner `/mcp` Host+Origin defense survives (`FastMCP` uses its default
  loopback host independent of `ARXMCP_BIND_HOST`; `HostValidationMiddleware` rejects
  non-loopback `Host` app-wide → 421), so even an admin-install 0.0.0.0 NodePort is
  defended at the app layer, not just the RD forward.
- The `extra="forbid"` cross-check test is the right test and is correct; `HF_HOME`/
  `TRANSFORMERS_CACHE` are correctly non-prefixed.
- Manifest internal consistency is airtight: pod-template labels, Deployment/Service/
  NetworkPolicy selectors, `claimName`, and `targetPort: http` → 7733 all line up.
- `strategy: Recreate` correctly justified for the RWO `local-path` PVC.
- `startupProbe → /readyz` correctly resolves the research divergence (60×10s window;
  test pins budget ≥ 300).
- HF cache pinned onto the PVC (read-only-rootfs + restart-survival of the 2.3 GB weights).
- Honest NetworkPolicy enforcement caveat (kube-router; verify-at-deploy; host forward
  is primary control).
- Doc placement correct; no fork; local-first (registry-free side-load, both runtime
  paths, `imagePullPolicy: Never` + pinned tag).
- Scripts defensively written: `set -euo pipefail` / `$ErrorActionPreference='Stop'`,
  `:latest` refusal, Dockerfile-existence guard, `$LASTEXITCODE` checks.

## Recommended rectification order

1. **F2 / IS1** (cross-critic) — `automountServiceAccountToken: false` + test assertion.
2. **F1** — `XDG_CACHE_HOME` + `MPLCONFIGDIR` in ConfigMap + test assertion (same files).
3. **F3** — test docstring `RUNTIME-UNVERIFIED` note + runbook §8 row (folds into F1).
4. **F4** — airgap pre-clean + runbook caveat.
5. **F5, F6, F7, IS2** (LOW) — fold opportunistically while in the runbook/script.

## Rectification status

All findings fixed in `61426e0`; none deferred, none invalidated (0% invalidation
rate for both critics).

- F1 — fixed (configmap.yaml `XDG_CACHE_HOME`/`MPLCONFIGDIR`; guard: `test_configmap_required_env_present`)
- F2 / IS1 — fixed (deployment.yaml `automountServiceAccountToken: false`; guard: `test_deployment_security_context`)
- F3 — fixed (test docstring `RUNTIME-UNVERIFIED` note + runbook §8 row)
- F4 — fixed (load-image.sh airgap pre-clean of `arxmcp-server*.tar` + runbook §4/§8 caveat)
- F5 — fixed (runbook frontmatter `type: runbook` → `type: doc`)
- F6 — fixed (runbook §7 egress-open note)
- F7 — fixed (load-image.sh verify via `nerdctl image inspect`, not grep)
- IS2 — fixed (expanded operator comment above the airgap `sudo` block)
