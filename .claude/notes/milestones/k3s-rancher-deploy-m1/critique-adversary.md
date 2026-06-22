# Critique — k3s-rancher-deploy-m1

**Critic:** adversary
**Generated:** 2026-06-21T00:00:00Z
**Commit range:** df36de82e8bb558b824938fcc9bca9ffad75f0f8..e8601c9a88f181d2db5187b08f500c6cde22147c
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the manifest set is correct and internally consistent (labels, selectors, ports, claimName all line up), the static test passes (14 passed / 1 skipped), and the security story actually holds — but two real read-only-rootfs / hardening gaps ship untested.
- Finding counts: 0 CRITICAL, 0 HIGH, 4 MEDIUM, 3 LOW.
- Highest-risk surface: `infra/k8s/deployment.yaml:61` (`readOnlyRootFilesystem: true`) — this is the FIRST place the image runs under a read-only root FS; Compose never set `--read-only`, so the only writable-path coverage is HF cache (`HF_HOME`); non-HF `~/.cache` writers (MinerU UI-parse, fontconfig, torch hub) are unverified.
- Security axis (the key axis) verified clean for the load-bearing claim: the inner `/mcp` Host+Origin defense is NOT disabled by `ARXMCP_BIND_HOST=0.0.0.0`, because `server/main.py:820` constructs `FastMCP("arxmcp", ...)` with FastMCP's DEFAULT host (127.0.0.1), so `TransportSecurityMiddleware` auto-enables; and `HostValidationMiddleware` (`allowed_port=None`, `server/main.py:719`) rejects any non-loopback `Host` across the whole app. A LAN attacker hitting `nodeIP:30733` is rejected 421 regardless of admin-install exposure.
- The `extra="forbid"` cross-check is honest: the test lowercases the `ARXMCP_*` suffix and matches `Config.model_fields`; `bind_host`/`unsafe_network_bind`/`bootstrap_mode` all map (`server/config.py:87,404,230`), and `HF_HOME`/`TRANSFORMERS_CACHE` are correctly non-`ARXMCP_`-prefixed so neither the model nor `_scan_unknown_arxmcp_env_vars` rejects them.
- Cross-axis pattern: the static test asserts manifest FIELDS are present/correct but proves nothing about RUNTIME (a pod that boot-crashes under read-only rootfs still passes every assertion) — acceptable given `kubectl apply` is gated, but the runbook should own the residual boot-risk explicitly.
- No-fork, local-first, tier-sequencing, cache-stability, math-fidelity, MCP-spec axes all clean.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — readOnlyRootFilesystem first-exercise: only HF cache redirected

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** infra/k8s/deployment.yaml:61
- **What:** `readOnlyRootFilesystem: true` is applied to the `arxmcp-server` image for the FIRST time here — the Compose path (`infra/docker-compose.yml`) never sets `--read-only`, so its rootfs is writable and has never exercised this posture. The synthesis (FM-C) identified only the HuggingFace cache as needing redirection; `HF_HOME`/`TRANSFORMERS_CACHE` → PVC covers BGE-M3 + the reranker (both load via `transformers.*.from_pretrained`, which honor `HF_HOME` — `ingest/embedder.py:332`, `server/resources.py:1412`). But the image runs as `USER arxmcp` with `HOME=/home/arxmcp` (`docker/Dockerfile.server:106,146`), which is on the read-only root FS. Any library that writes under `~/.cache` / `~/.config` OUTSIDE HuggingFace will crash with `OSError: [Errno 30] Read-only file system`.
- **Why it matters:** Two concrete vectors: (a) the UI PDF-parse path uses MinerU, which writes `~/.cache/mineru/` ONNX weights (`ingest/textbook_parser.py:66`) — an operator uploading a PDF via `/ui` under this manifest hits a read-only crash; (b) fontconfig/matplotlib (`~/.cache/fontconfig`, `~/.config/matplotlib`) if any transitively-imported plotting path fires. None of these are covered by `HF_HOME`, none is tested, and the read-only posture means the failure is a hard crash, not a degrade.
- **Proposed fix:** Add an `emptyDir` (or PVC-subdir) writable mount at `/home/arxmcp/.cache` in `deployment.yaml`, OR set `XDG_CACHE_HOME=/app/var/arxmcp/.cache` + `MPLCONFIGDIR=/tmp/mpl` in `configmap.yaml` (both non-`ARXMCP_`-prefixed, so safe vs `extra="forbid"`). Mirror the MinerU cache dir if the UI-parse path is in scope. Document the read-only-rootfs boot-risk in runbook §8 troubleshooting.
- **Regression guard:** Extend `tests/test_k8s_manifests.py` to assert a writable mount or `XDG_CACHE_HOME`/`MPLCONFIGDIR` env covers the non-HF home-cache path; the live boot-under-read-only check stays operator-acceptance (gated).

### F2 — default ServiceAccount token auto-mounted into a workload that makes no k8s API calls

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** infra/k8s/deployment.yaml:32
- **What:** The pod spec sets no `automountServiceAccountToken: false` and no dedicated ServiceAccount, so k8s mounts the default SA token at `/var/run/secrets/kubernetes.io/serviceaccount/`. The `arxmcp-server` process never calls the Kubernetes API.
- **Why it matters:** An unused, mounted API credential is standing attack surface — a process-compromise (e.g. via a malicious uploaded PDF in the parse path) gains a k8s API token it otherwise would not have. This is the k8s-native analogue of the Compose `cap_drop: [ALL]` posture the brief explicitly wants mirrored; the brief's AC2 securityContext checklist predates k8s specifics and omits it, so it is a genuine gap beyond the checklist.
- **Proposed fix:** Add `automountServiceAccountToken: false` to `spec.template.spec` in `deployment.yaml` (one line). No functional impact — the workload needs no API access.
- **Regression guard:** Add `assert dep["spec"]["template"]["spec"].get("automountServiceAccountToken") is False` to `test_deployment_security_context` in `tests/test_k8s_manifests.py`.

### F3 — static test cannot distinguish "field present" from "pod actually boots"

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_k8s_manifests.py:119
- **What:** `test_deployment_security_context` and siblings assert the securityContext / probe / volume FIELDS are present and well-typed, but no assertion (and no gated marker test) proves the combination (`readOnlyRootFilesystem: true` + only PVC/`/tmp` writable + `HF_HOME` on PVC) actually yields a booting pod. A manifest that is syntactically perfect but boot-crashes under read-only rootfs (see F1) passes every test green.
- **Why it matters:** The implementation-summary AC table marks AC2/AC5 "✅ MET" with the static test as evidence, which overstates what the test proves — it proves authoring, not runtime. Combined with F1, the green test gives false confidence that the read-only posture is validated.
- **Proposed fix:** No new live test (apply is gated) — instead add a `# RUNTIME-UNVERIFIED` note in the test module docstring and a runbook §8 row stating the read-only-rootfs boot is operator-acceptance, and cross-link F1's writable-cache assertion. This keeps the static/runtime boundary honest.
- **Regression guard:** The F1 writable-cache assertion is the cheapest partial guard; full coverage is the gated `kubectl apply` → `/readyz` 200 step documented in runbook §5.

### F4 — `load-image.sh` airgap fallback leaves a stale tarball; restart side-effect unstated

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** infra/k8s/scripts/load-image.sh:57
- **What:** In moby mode when `ctr`/the k3s socket is unavailable, the script `sudo cp`s the tarball to `/var/lib/rancher/k3s/agent/images/arxmcp-server.tar` and tells the operator to restart k3s. The `trap 'rm -f "$TARBALL"' EXIT` removes only the `mktemp` source, not the copied airgap file. On a tag rebump the airgap dir accumulates stale tarballs, and k3s auto-imports EVERY tar there on each (re)start — a stale `arxmcp-server.tar` from an old build silently shadows the intended one (both import to `k8s.io`, last-write-wins on the tag is undefined across imports).
- **Why it matters:** Reproducible-build intent (the whole reason for `imagePullPolicy: Never` + a pinned tag) is undermined if an old tarball re-imports under the same `arxmcp-server:dev` tag. Operator hits "I rebuilt but the pod runs old code" with no error.
- **Proposed fix:** Name the airgap file by content (e.g. include a short digest) OR `sudo rm -f "$AIRGAP_DIR"/arxmcp-server*.tar` before the `cp`, and state in the runbook §4 that the airgap path requires a k3s restart and overwrites prior tarballs. Cheapest: overwrite-in-place is already the case for the same filename — the real fix is documenting the restart-imports-all behavior and the `:dev` tag-reuse caveat in `docs/ops/k3s-rancher-desktop.md:90`.
- **Regression guard:** N/A (shell script; no unit-test harness). Add the caveat to runbook §4 + §8.

### F5 — runbook frontmatter `type: runbook` diverges from the `docs/ops/` convention

- **Severity:** LOW
- **Source:** adversary
- **File:** docs/ops/k3s-rancher-desktop.md:3
- **What:** The new runbook sets `type: runbook` / `tags: [type/runbook]` in its frontmatter, while every sibling under `docs/ops/` (e.g. `server-crash.md`, `backup-restore.md`) uses `type: doc` / `tags: [type/doc]`.
- **Why it matters:** Inconsistent metadata breaks any tag-based index/query that assumes `type/doc` across `docs/ops/`. Purely cosmetic but trivially avoidable.
- **Proposed fix:** Change `type: runbook` → `type: doc` and `type/runbook` → `type/doc` to match the directory convention.
- **Regression guard:** None required (LOW).

### F6 — NetworkPolicy egress is fully unrestricted; comment claims "default-deny" only for ingress

- **Severity:** LOW
- **Source:** adversary
- **File:** infra/k8s/networkpolicy.yaml:30
- **What:** `policyTypes: [Ingress]` only — egress is entirely unconstrained. The header comment is honest ("Egress is intentionally UNRESTRICTED … huggingface.co … arXiv/OpenAlex/INSPIRE"), but the file name `arxmcp-server-ingress` and the README line "default-deny ingress except TCP/7733" could read as a broader lockdown than delivered.
- **Why it matters:** On a single-node single-user loopback cluster this is acceptable (and the comment says so), but a reader skimming "default-deny" may assume egress is also constrained. Intent is documented; no behavior bug.
- **Proposed fix:** None functional. Optionally add one line to runbook §7 noting egress is open by design for model/ingest fetches.
- **Regression guard:** None required (LOW).

### F7 — `nerdctl images | grep` verification is fragile across output formats

- **Severity:** LOW
- **Source:** adversary
- **File:** infra/k8s/scripts/load-image.sh:43
- **What:** Verification is `nerdctl --namespace k8s.io images | grep -E "(^|/)${IMAGE%%:*}\b"`. This depends on `nerdctl images` rendering the repository as a column starting at line-start or after a `/`, and on the word-boundary after `arxmcp-server`. A future nerdctl that prefixes a registry host (`docker.io/library/...`) or pads columns differently could make the grep miss a present image and exit 1 on a successful build.
- **Why it matters:** A false-negative verification aborts a correct build with a misleading "image not listed" error. Low likelihood; cosmetic robustness.
- **Proposed fix:** Prefer `nerdctl --namespace k8s.io image inspect "$IMAGE" >/dev/null 2>&1` for the existence check instead of grepping table output.
- **Regression guard:** None required (LOW).

## What was done well

- **Security axis is genuinely sound, not just asserted.** The 0.0.0.0-in-cluster + UNSAFE pair mirrors Compose exactly; the inner `/mcp` Host+Origin defense survives because `FastMCP("arxmcp", …)` (`server/main.py:820`) uses FastMCP's default loopback host independent of `ARXMCP_BIND_HOST`, and `HostValidationMiddleware` (`allowed_port=None`) rejects non-loopback `Host` app-wide — so even an admin-install 0.0.0.0 NodePort exposure is defended at the application layer (421), not just by the RD port-forward.
- **The `extra="forbid"` cross-check test is the right test and is correct.** It lowercases the `ARXMCP_*` suffix and matches `Config.model_fields`, and the chosen keys (`bind_host`, `unsafe_network_bind`, `bootstrap_mode`) all resolve; `HF_HOME`/`TRANSFORMERS_CACHE` are correctly non-prefixed so they bypass both the pydantic model and `_scan_unknown_arxmcp_env_vars`.
- **Manifest internal consistency is airtight:** pod-template labels, Deployment selector, Service selector, and NetworkPolicy podSelector all use the identical two-label set; `claimName: arxmcp-var` matches the PVC; Service `targetPort: http` resolves to the named container port 7733; NetworkPolicy allows the post-DNAT targetPort 7733 (not the NodePort) — all correct.
- **Recreate strategy is correctly chosen and justified** for an RWO `local-path` PVC (a RollingUpdate would deadlock on volume attach) — the comment at `deployment.yaml:18` names exactly the right reason.
- **startupProbe → `/readyz`** (not `/healthz`) correctly resolves the research divergence: it gates liveness on warm, giving BGE-M3 a 60×10s=600s window, and the test pins `budget >= 300`.
- **HF cache pinned onto the PVC** is the right call for both the read-only-rootfs constraint AND restart-survival of the 2.3 GB weights — the synthesis caught this (FM-C) and the implementer wired it.
- **Honest NetworkPolicy enforcement caveat:** the YAML comment + runbook §7 correctly state k3s enforces via embedded kube-router, flag verify-at-deploy, and name the host-boundary 127.0.0.1 forward as the primary control rather than overclaiming the NetworkPolicy.
- **Doc placement is correct:** manifests + scripts under `infra/k8s/`, operator runbook in `docs/ops/` linked from `docs/ops/README.md`, only navigational README.md added to `infra/k8s/` — no stray Markdown, no fork, Compose untouched.
- **No-fork / local-first respected:** image side-loaded into containerd with no registry, both containerd and dockerd runtime paths handled, `imagePullPolicy: Never` + pinned `arxmcp-server:dev` tag (never `:latest`, asserted twice in the test).
- **Scripts are defensively written:** `set -euo pipefail`, `:latest`-tag refusal with a clear exit code, Dockerfile-existence guard, repo-root resolution from `BASH_SOURCE`, and `$LASTEXITCODE` checks after every external call in the `.ps1`.

## Recommended rectification order

1. **F1** (read-only-rootfs non-HF cache) — highest operator-impact; a writable `~/.cache` mount or `XDG_CACHE_HOME`/`MPLCONFIGDIR` env is ≤10 LOC and prevents a hard boot/parse crash. Fix the manifest + add the test assertion.
2. **F2** (`automountServiceAccountToken: false`) — one-line manifest hardening + one test assertion; pairs naturally with F1 in the same `deployment.yaml` edit.
3. **F3** (static-vs-runtime honesty) — folds into F1's test assertion + a runbook §8 row; no standalone work once F1 lands.
4. **F4** (airgap stale-tarball / `:dev` reuse) — doc caveat in runbook §4 + §8; optional script overwrite-guard.
5. **F5, F6, F7** (LOW) — defer; fold F5 (frontmatter) opportunistically if touching the runbook for F3/F4.

## Rectification status
