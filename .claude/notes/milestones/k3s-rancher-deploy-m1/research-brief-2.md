# Research Brief — k3s-rancher-deploy-m1

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-06-22T03:30:00Z

## In-codebase context

### Load-bearing constraints from the design constitution

**From `08-security-observability-ops.md` — the loopback-only threat model (verbatim):**
> "This is a single-developer, localhost-only system. The threat model is **not** 'external
> attacker' — it's **'LLM-generated tool inputs and adversarial arXiv content can do
> unintended things to my workstation.'**"

**Threat 5 (verbatim):**
> "Even bound to localhost, a malicious local web page could try to issue fetches."
> Mitigations include: "DNS rebinding defense: validate the `Host` header is `127.0.0.1`
> or `localhost` with the configured port."

This threat escalates meaningfully with Traefik/NodePort: the host-side loopback binding
is provided by Rancher Desktop's port-forward layer rather than the `127.0.0.1:` ports
prefix Compose uses. Both Rancher Desktop's binding behavior and the `HostValidationMiddleware`
in `server/middleware.py` are in the threat chain.

**From `server/config.py::reject_non_loopback_bind` (verbatim):**
> "`unsafe_network_bind: bool = False` — Default False = `ARXMCP_BIND_HOST=0.0.0.0` is
> rejected at config parse time ... Container deployments should expose the port via host
> port-mapping (`ports: '127.0.0.1:7733:7733'`) rather than binding to 0.0.0.0."

The ConfigMap MUST set both `ARXMCP_BIND_HOST=0.0.0.0` and `ARXMCP_UNSAFE_NETWORK_BIND=1`
or the server crashes at startup. This is verified by the Compose file which sets both.

**From `infra/docker-compose.yml` (verbatim comment):**
> "0.0.0.0 is correct INSIDE the container — Docker's bridge network forwards the loopback
> host port-binding to the container's 0.0.0.0 listener. The 'localhost-only' defense lives
> on the HOST side via the ports: 127.0.0.1: prefix ... so BOTH vars are required here, or
> the container crashes at startup."

The k8s deployment replaces Compose's `ports: 127.0.0.1:7733:7733` with Rancher Desktop's
port-forward mechanism. The cluster-internal 0.0.0.0 binding is correct; the question is
whether Rancher Desktop enforces the loopback-only constraint at the host boundary.

**From `06-mcp-server-design.md` (verbatim):**
> "The stdio shim is **not** in Docker — it runs on the host as a tiny binary spawned by
> Claude Code. It's a thin proxy; no state, no models." The shim entry in `~/.claude.json`
> targets `http://127.0.0.1:7733`.

The shim's hardcoded `127.0.0.1:7733` target means the Traefik/NodePort path MUST land on
`127.0.0.1:7733` (or the docs must instruct the operator to change `~/.claude.json`).

**From `docker/Dockerfile.server`:**
- Base image pinned by `@sha256:a3ab0b966bc4e91546a033e22093cb840908979487a9fc0e6e38295747e49ac0` (python:3.11-slim).
- `USER arxmcp` (UID 1000, GID 1000).
- `VOLUME /app/var/arxmcp` — this is the writable mount point.
- `HEALTHCHECK --start-period=5m` — covers first-run BGE-M3 download (~2.3 GB).
- `ENTRYPOINT ["/usr/bin/tini", "--"]` + `CMD ["python", "-m", "server.main"]`.
- NO writable directories outside `/app/var/arxmcp` and an implicit `/tmp`. A
  `readOnlyRootFilesystem: true` pod WILL also need an `emptyDir` for the HuggingFace
  model cache (see Failure Mode C below).

**`ARXMCP_BOOTSTRAP_MODE` and `ARXMCP_BIND_HOST` must appear in the ConfigMap** — verbatim
from the brief AC5 and confirmed by the docker-compose.yml environment block.

**Doc-placement constraint (CLAUDE.md §1 + §4.6):**
> "`infra/k8s/*.yaml` is fine (non-Markdown); operator docs go in `docs/ops/`, internal
> notes in `.claude/`. No stray Markdown in `infra/` beyond README/CLAUDE."

The milestone's operator runbook goes under `docs/ops/k8s-rancher-deploy.md` and must be
linked from `docs/ops/README.md`. No `infra/k8s/README.md` (not a navigational CLAUDE.md
or README, it would be a Markdown doc in a non-.claude/ dir). This is fine per the rule if
the file is a `README.md`, but agent-internal notes go under `.claude/`.

**No tool-schema change.** This milestone is infrastructure-only; the MCP 7-tool surface
is untouched. `EXPECTED_TOOL_SCHEMA_SHA256` must NOT be re-pinned.

## Prior decisions and lessons

Most recent relevant commit: `df36de8 feat(infra): containerize server + fix wheel packaging`.
That commit landed `infra/docker-compose.yml` and `docker/Dockerfile.server`, which are the
exact artifacts this milestone translates into k8s manifests. The commit message scope is
`infra` — the same scope applies here.

**From agent memory (2026-06-08 textbook-render-robustness-m1):**
`ARXMCP_LATEXML_TIMEOUT_S` is an ingest-tool var, NOT a server config field. The server's
`config.py` has `extra="forbid"` — any unknown `ARXMCP_*` env var in the ConfigMap that is
NOT a recognized `Config` field causes a startup `ValidationError`. The ConfigMap must only
set vars that appear as fields in `server/config.py`. `ARXMCP_CONTACT_EMAIL` is explicitly
NOT a server config field (noted in the docker-compose.yml comments). The ConfigMap for k8s
must not include it.

No prior k8s manifests exist in this repo. This is the first Kubernetes deployment path.

**Banned patterns to check for this milestone:**
- `latest` Docker image tags: BANNED. Use `imagePullPolicy: Never` + pinned local tag.
- No Markdown in `infra/k8s/` beyond README/CLAUDE.md (navigational files only).
- No `kubectl apply`, `helm install` from agent code — these are gated external writes.

**Windows test runner:** The brief explicitly says do NOT use
`/Users/chris.dare/Library/Python/3.9/bin/uv run` (macOS path). Use `uv run python -m pytest`
directly. The new tests must parse YAML in Python — use PyYAML (already in the project deps
via lancedb) or add it as a dependency, but confirm it is available first.

## External sources

### Rancher Desktop port-forward behavior (load-bearing security finding)

**Source:** Rancher Desktop GitHub issues, docs.rancherdesktop.io/ui/port-forwarding/, 
GitHub discussions (verified 2026-06-22).

Key findings — version-pinned to Rancher Desktop circa v1.9+:

1. **Port forwarding to Windows host binds `127.0.0.1` by default.** The Rancher Desktop
   privileged service, when installed (admin installation), routes NodePort/Traefik ports
   through a vtunnel to the Windows host, binding to `localhost` (127.0.0.1), NOT `0.0.0.0`.
   Issue #6760 confirms: "Ports forwarded through the UI listen on 127.0.0.1, not 0.0.0.0,
   and this is how the code is currently written." Non-admin installation relies on WSL's
   automatic port forwarding of ports bound to `127.0.0.1` or `0.0.0.0` inside WSL.

2. **LAN exposure caveat:** The Rancher Desktop Privileged Service is **required** to expose
   services on ALL network interfaces (including LAN). Without it (non-admin install), the
   port-forward is loopback-only. The operator runbook must explicitly note: install Rancher
   Desktop WITHOUT the privileged service if loopback-only is required, or with it (admin)
   understanding the firewall controls LAN exposure.

3. **Traefik default ports:** k3s bundles Traefik as the default ingress controller. Traefik
   listens on ports 80 (HTTP) and 443 (HTTPS) by default. These are forwarded to the Windows
   host. Using Traefik Ingress exposes the server at `http://127.0.0.1/` (port 80) NOT at
   port 7733. The stdio shim targets `http://127.0.0.1:7733` — **this is a port mismatch**.
   The operator must either: (a) configure a NodePort service on port 7733 (or any high port
   ≥30000 per k8s NodePort range, then document the shim URL change), or (b) configure
   Traefik with a path prefix at port 80 (requires shim URL change to `http://127.0.0.1`).

   **RECOMMENDATION:** Use a NodePort Service on a stable high port (e.g. 30733) alongside
   Traefik Ingress, and instruct the operator to update `~/.claude.json` to
   `http://127.0.0.1:30733`. This avoids Traefik path-routing complexity and keeps the
   port predictable. Document the delta from the Compose default.

### Image-into-k3s without a registry

**Sources:** docs.rancherdesktop.io/tutorials/working-with-images (verified 2026-06-22),
docs.k3s.io/add-ons/import-images (verified 2026-06-22).

**Containerd (nerdctl) mode — preferred:**
```
nerdctl build -n k8s.io -t arxmcp-server:dev .
```
This builds directly into the `k8s.io` namespace used by k3s. No separate import step.
Alternatively for post-build import:
```
docker save arxmcp-server:dev | nerdctl -n k8s.io load
```
Or using k3s's bundled `ctr`:
```
docker save arxmcp-server:dev | ctr -a /run/k3s/containerd/containerd.sock -n=k8s.io images import -
```

**Dockerd (moby) mode:** Rancher Desktop's k3s and dockerd share the same containerd
socket in moby mode, so `docker build` images ARE visible to k3s without re-import.
Set `imagePullPolicy: Never`.

**K3s airgap directory method** (works regardless of runtime):
Place `docker save arxmcp-server:dev > arxmcp-server.tar` into
`/var/lib/rancher/k3s/agent/images/` and restart k3s. This is the simplest and most
reliable method for a pre-loaded image.

**`imagePullPolicy: Never` is mandatory** — prevents k8s from trying to pull from Docker Hub.

### Kubernetes API versions (verified against k8s 1.29+)
- `Deployment`: `apps/v1`
- `Service`: `v1`
- `Ingress`: `networking.k8s.io/v1`
- `NetworkPolicy`: `networking.k8s.io/v1`
- `PersistentVolumeClaim`: `v1`
- `ConfigMap`: `v1`
- `Namespace`: `v1`
- `seccompProfile.type: RuntimeDefault` requires k8s 1.19+

### k3s local-path StorageClass
- Default StorageClass name: `local-path`
- Access mode: `ReadWriteOnce (RWO)` only
- Default data directory: `/opt/local-path-provisioner` inside the WSL2 VM
- This means corpus data survives pod restarts but lives inside the WSL2 VM's
  filesystem, NOT on the Windows host filesystem. The operator must back this up
  separately (separate from Compose's `../var/arxmcp` bind-mount).

### HuggingFace cache with readOnlyRootFilesystem
The HuggingFace transformers library writes model weights to `~/.cache/huggingface/`
by default (i.e. `/home/arxmcp/.cache/huggingface/` for UID 1000). With
`readOnlyRootFilesystem: true`, this directory is unwritable — the first startup will
fail attempting to create the cache. Resolution: mount an `emptyDir` volume at
`/home/arxmcp/.cache` OR set `HF_HOME` env var to `/app/var/arxmcp/hf-cache` (inside
the PVC mount). The PVC approach is better because the ~2.3 GB BGE-M3 weights survive
pod restarts; emptyDir is re-downloaded on every pod restart.

### NetworkPolicy for Traefik in k3s
Traefik in k3s runs in the `kube-system` namespace. A default-deny-ingress NetworkPolicy
for the `arxmcp` namespace plus an allow rule for traffic from `kube-system` is required.
The `kube-system` namespace does NOT have a label by default in k3s — the NetworkPolicy
must label it first, or use the podSelector approach targeting Traefik's pod labels.
The allow rule must permit traffic on port 7733 (the arXMCP server port).

**This is a non-trivial k3s NetworkPolicy interaction:** k3s uses Flannel as the default
CNI, but NetworkPolicy enforcement requires an additional network policy controller.
**k3s does NOT enforce NetworkPolicies with Flannel by default.** The operator must
either: (a) install `network-policy` addon at k3s install time, or (b) replace Flannel
with Calico/Cilium. **This is a FLAG — the NetworkPolicy manifest will be present and
correct, but may be silently unenforced on a default k3s install.**

## Failure mode analysis

**FM-A: Image not visible to k3s containerd → ImagePullBackOff**
- Trigger: `imagePullPolicy: Never` + image not in `k8s.io` namespace containerd store.
- Symptom: Pod stuck in `ImagePullBackOff`; `kubectl describe pod` shows "image not found".
- Mitigation: Use `nerdctl build -n k8s.io` (containerd mode) OR the k3s airgap dir
  (`/var/lib/rancher/k3s/agent/images/`). Document runtime detection in the build script.

**FM-B: PVC owned by root; UID-1000 process cannot write `/app/var/arxmcp` → CrashLoopBackOff**
- Trigger: `local-path` provisioner creates the PVC directory as root; `fsGroup: 1000`
  in the pod's `securityContext` is required to chown the mount on attach.
- Symptom: Server starts, attempts to write to `/app/var/arxmcp/`, raises `PermissionError`.
- Mitigation: Set `securityContext.fsGroup: 1000` at the pod level (NOT the container
  level). This causes kubelet to recursively chown the mounted volume to GID 1000 on attach.

**FM-C: `readOnlyRootFilesystem: true` breaks HuggingFace BGE-M3 cache write → CrashLoopBackOff**
- Trigger: `TRANSFORMERS_CACHE` or `HF_HOME` defaults to `~/.cache/huggingface/` which is
  on the read-only rootfs.
- Symptom: Server crashes during startup with `OSError: [Errno 30] Read-only file system`
  when trying to write model weights.
- Mitigation: Set `HF_HOME=/app/var/arxmcp/hf-cache` in the ConfigMap. This redirects the
  cache into the PVC-mounted path. Add `TRANSFORMERS_CACHE=/app/var/arxmcp/hf-cache` as well
  for older transformers versions. Also need an emptyDir for `/tmp` (tini/Python temp files).

**FM-D: WSL2 VM RAM too low → BGE-M3 + reranker OOMKilled**
- Trigger: Default Rancher Desktop WSL2 memory limit is 8 GB or half of host RAM (whichever
  is less). BGE-M3 + reranker + LanceDB + Python process needs ~8–10 GB.
- Symptom: Pod OOMKilled; `kubectl describe pod` shows `OOMKilled`.
- Mitigation: Set `resources.limits.memory: 8Gi` and document in runbook that the WSL2 VM
  must be configured with ≥12 GB RAM via `%USERPROFILE%\.wslconfig`:
  ```
  [wsl2]
  memory=12GB
  ```

**FM-E: `startupProbe` window too short for first-run BGE-M3 download → pod killed before warm**
- Trigger: Default startupProbe `failureThreshold * periodSeconds` < ~5 minutes. The
  Dockerfile HEALTHCHECK uses `start_period=5m` but k8s probes do not have this parameter;
  they use `initialDelaySeconds` + `failureThreshold * periodSeconds`.
- Symptom: Pod killed and restarted in a loop on first deployment with cold HF cache.
  With HF_HOME on the PVC (FM-C mitigation), only the FIRST deploy suffers this.
- Mitigation: `startupProbe: { httpGet: { path: /readyz }, failureThreshold: 60, periodSeconds: 10 }`
  = 10 minutes total window. Once BGE-M3 is cached in the PVC, subsequent starts take ~30s.

**FM-F: Missing `ARXMCP_UNSAFE_NETWORK_BIND=1` → `reject_non_loopback_bind` aborts startup**
- Trigger: ConfigMap omits `ARXMCP_UNSAFE_NETWORK_BIND: "1"` with `ARXMCP_BIND_HOST: "0.0.0.0"`.
- Symptom: Container exits immediately with `pydantic_settings.ValidationError` containing
  "ARXMCP_BIND_HOST must be a loopback address".
- Mitigation: ConfigMap MUST contain both vars. Tests must assert both are present.

**FM-G: Traefik/NodePort binds on LAN via Privileged Service → loopback-only threat-model regression**
- Trigger: Operator installs Rancher Desktop WITH the Privileged Service (admin install).
  In this mode, NodePort/Traefik ports are forwarded to all host interfaces (0.0.0.0).
- Symptom: `netstat -an` shows the NodePort listening on 0.0.0.0 rather than 127.0.0.1;
  LAN hosts can reach the MCP server.
- Mitigation: Document in runbook that loopback-only mode requires non-admin Rancher Desktop
  install OR adding a Windows Firewall rule blocking inbound on the NodePort from non-loopback.
  Also document that this is a **residual exposure delta vs Compose** (which enforces loopback
  at the Docker daemon level with no override path).

**FM-H: Flannel (default k3s CNI) silently ignores NetworkPolicy → zero cluster-internal isolation**
- Trigger: k3s installed with default Flannel CNI; no `--flannel-backend=none` + Calico/Cilium.
- Symptom: NetworkPolicy objects are accepted by the API server but NOT enforced. Any pod
  in the cluster can reach the arxmcp server on port 7733 despite the default-deny policy.
- Mitigation: Document prominently in the runbook and in a manifest comment. This is a
  single-node single-user cluster so the practical risk is low, but the security claim in
  AC1 ("NetworkPolicy restricts cluster-internal reach") is only true if a policy-aware CNI
  is used. Add a comment in the NetworkPolicy YAML: "# NOTE: Flannel does not enforce
  NetworkPolicy. Install network-policy addon at k3s install time for enforcement."

**FM-I: `unknown ARXMCP_*` env var in ConfigMap → `ValidationError` at startup (extra="forbid")**
- Trigger: ConfigMap sets an env var like `ARXMCP_CONTACT_EMAIL` that is NOT a `Config` field.
- Symptom: Server exits with pydantic-settings `ValidationError: Extra inputs are not
  permitted`.
- Mitigation: The ConfigMap must only set env vars that are declared fields in `server/config.py`.
  Every env var added to the ConfigMap must be cross-checked against `Config` field names.

**FM-J: NodePort port differs from shim default `7733` → shim cannot connect**
- Trigger: NodePort range is 30000–32767 by default. The stdio shim targets port 7733.
  A NodePort at e.g. 30733 means `http://127.0.0.1:7733` returns `connection refused`.
- Symptom: `arxmcp-shim` starts but every tool call fails with connection error.
- Mitigation: The operator runbook MUST instruct updating `~/.claude.json` shim args to
  `["--server", "http://127.0.0.1:30733"]` (or whichever port is chosen). Alternatively,
  use Traefik Ingress at port 80 and instruct the operator to update to `http://127.0.0.1`.

## In-codebase cross-check

**No conflicts found** between the external findings and the design constraints, EXCEPT:

**FLAG: The brief (AC7) says "Host reaches the service at `127.0.0.1:<port>`" and states the
shim's default port 7733 must be preserved or documented. The NodePort approach makes port
7733 unreachable directly — the NodePort will be 30000+. This is NOT a design constraint
violation (the brief explicitly asks the implementer to pick between Traefik path or NodePort
and document the delta) but it is a deployment UX landmine that must be called out.**

**FLAG: NetworkPolicy enforcement is NOT guaranteed on default k3s (Flannel CNI). The brief's
AC1 requires a default-deny + Traefik-allow NetworkPolicy, but k3s with Flannel silently
ignores it. The NetworkPolicy manifest should be present and correct (satisfies AC1 as a
declaration of intent) but the runbook must note that enforcement requires a CNI swap.**

The `server/config.py::extra="forbid"` creates a hidden hazard: every env var in the ConfigMap
must match a `Config` field name. The test suite (AC8) must assert that all ConfigMap env vars
(stripped of `ARXMCP_` prefix) appear as fields in the Config model.

## Recommendation

**Implement Deployment + RWO PVC (not StatefulSet).** Stable network identity is not needed;
the server is accessed via Service/Ingress, not by pod hostname. A Deployment with `replicas: 1`
is simpler, restartable, and consistent with the Compose model.

**Expose via NodePort (not pure Traefik Ingress).** Define a Service of `type: NodePort` with
`nodePort: 30733`. This puts the server at `http://127.0.0.1:30733` on the Windows host
(via Rancher Desktop's port-forward). Also include a Traefik Ingress pointing to the ClusterIP
service as a secondary access path. Document the `~/.claude.json` shim update to port 30733.
NodePort is simpler to reason about for loopback-only access than Traefik HTTP routing.

**Set `HF_HOME=/app/var/arxmcp/hf-cache`** in the ConfigMap. This is the critical missing
env var from the brief's ConfigMap list (AC5). Without it, `readOnlyRootFilesystem: true` will
crash the server on first boot.

**Use `nerdctl build -n k8s.io`** as the primary image-load method (containerd mode) with
`docker save | ctr ... import` as the moby-mode alternative. Document both in the runbook.

**For the test suite (AC8):** use Python's `yaml` module (PyYAML — confirm it is a project
dep before using it; if not, add it) to parse `infra/k8s/*.yaml` files and assert the
load-bearing invariants. Do NOT require `kubeconform` binary — make it an optional `subprocess`
call marked `pytest.skip` if the binary is absent.

## Open questions

1. **HF_HOME path is not listed in the brief's AC5 ConfigMap** — the brief lists only
   `ARXMCP_BOOTSTRAP_MODE=1`, `ARXMCP_BIND_HOST=0.0.0.0`, `ARXMCP_UNSAFE_NETWORK_BIND=1`.
   The implementer must confirm whether `HF_HOME` and `TRANSFORMERS_CACHE` should be in the
   ConfigMap (recommended) or whether an emptyDir is used instead (less resilient).

2. **PyYAML availability for tests:** confirm `pyyaml` is a project dependency before using it
   in the new test file. If not, add it to `pyproject.toml` as a test/optional dep.

3. **Traefik namespace label for NetworkPolicy:** running k3s Traefik is in `kube-system`.
   The NetworkPolicy `namespaceSelector` requires that namespace to have the label
   `kubernetes.io/metadata.name: kube-system` (this label is auto-added by k8s 1.21+).
   Confirm k3s version in Rancher Desktop satisfies this (Rancher Desktop ships k3s 1.29+
   as of 2025, so this is safe, but must be verified at install time).

4. **NodePort vs Traefik Ingress port strategy:** if the operator wants port 7733 specifically
   (to avoid the shim URL change), using `hostPort: 7733` on the pod spec is an alternative —
   but hostPort is not recommended for production and may conflict with Docker Desktop's usage
   of port 7733. The implementer should pick NodePort 30733 and document the shim update.

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| container image build/load | local k3s containerd (k8s.io namespace) | Make arxmcp-server image visible to k3s without registry; runs after Rancher Desktop install |
| kubectl apply | local k3s cluster (Rancher Desktop) | Deploy manifests; GATED — out of scope for implement phase |
| file edit | `~/.claude.json` (operator's home dir) | Update shim `--server` URL from port 7733 to NodePort (e.g. 30733) |
| git push | origin/main | Land the milestone commits; GATED |
| `.wslconfig` edit | `%USERPROFILE%\.wslconfig` (Windows host) | Set WSL2 VM memory ≥12 GB to prevent OOMKill |
