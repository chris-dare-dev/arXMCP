#!/usr/bin/env bash
# load-image.sh — build the arxmcp-server image and make it visible to k3s
# (Rancher Desktop), WITHOUT an external registry. (k3s-rancher-deploy-m1)
#
# k3s pulls images from its OWN containerd, namespace "k8s.io" — an image in a
# plain Docker daemon is NOT visible to it. This script handles both Rancher
# Desktop runtime modes:
#   * containerd (nerdctl) mode — builds straight into the k8s.io namespace.
#   * dockerd (moby) mode      — builds with docker, then imports the saved
#                                tarball into k3s' containerd via `ctr`.
#
# Run it from the repo root (or anywhere — it resolves the root from its own
# path). The deployment uses `imagePullPolicy: Never`, so the image MUST be
# present in k8s.io before `kubectl apply`.
#
# Usage:   infra/k8s/scripts/load-image.sh
# Env:     ARXMCP_K8S_IMAGE   image ref (default: arxmcp-server:dev)
set -euo pipefail

IMAGE="${ARXMCP_K8S_IMAGE:-arxmcp-server:dev}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DOCKERFILE="$REPO_ROOT/docker/Dockerfile.server"
K3S_SOCK="/run/k3s/containerd/containerd.sock"

case "$IMAGE" in
  *:latest) echo "ERROR: refusing :latest tag (CLAUDE.md §4.7). Pin a tag." >&2; exit 2 ;;
  *:*) : ;;
  *) echo "ERROR: image '$IMAGE' has no tag; expected name:tag." >&2; exit 2 ;;
esac

if [ ! -f "$DOCKERFILE" ]; then
  echo "ERROR: Dockerfile not found at $DOCKERFILE" >&2; exit 1
fi

echo ">> arXMCP image loader — image=$IMAGE  repo=$REPO_ROOT"

if command -v nerdctl >/dev/null 2>&1; then
  # Containerd mode (Rancher Desktop default). Build directly into the k8s.io
  # namespace so kubelet sees it immediately — no separate import step.
  echo ">> nerdctl found → building into containerd namespace k8s.io"
  nerdctl --namespace k8s.io build -t "$IMAGE" -f "$DOCKERFILE" "$REPO_ROOT"
  echo ">> verifying image is present in k8s.io:"
  # `image inspect` is an exact existence check — robust across nerdctl output
  # formats (a `grep` over the table can false-negative if the repo column is
  # registry-prefixed or padded differently).
  nerdctl --namespace k8s.io image inspect "$IMAGE" >/dev/null 2>&1 || {
    echo "ERROR: build reported success but $IMAGE not in k8s.io ns." >&2; exit 1; }
elif command -v docker >/dev/null 2>&1; then
  # dockerd (moby) mode. Build with docker, then import the tarball into k3s'
  # containerd k8s.io namespace via `ctr` (needs the k3s socket; usually root).
  echo ">> docker found (moby mode) → building, then importing into k3s containerd"
  docker build -t "$IMAGE" -f "$DOCKERFILE" "$REPO_ROOT"
  TARBALL="$(mktemp -t arxmcp-image.XXXXXX.tar)"
  trap 'rm -f "$TARBALL"' EXIT
  docker save "$IMAGE" -o "$TARBALL"
  if command -v ctr >/dev/null 2>&1 && [ -S "$K3S_SOCK" ]; then
    echo ">> importing via ctr into k8s.io (may require sudo for the k3s socket)"
    ctr --address "$K3S_SOCK" --namespace k8s.io images import "$TARBALL"
  else
    # Airgap fallback: drop the tarball where k3s auto-imports it on (re)start.
    AIRGAP_DIR="/var/lib/rancher/k3s/agent/images"
    echo ">> ctr/k3s socket unavailable → airgap-dir fallback: $AIRGAP_DIR"
    # IS2: this LAST-RESORT branch (no nerdctl, no ctr/socket) needs root to
    # write the root-owned k3s airgap dir — there is no non-sudo alternative.
    # You are authorizing a write under /var/lib/rancher; review before approving.
    # F4: remove any PRIOR arxmcp-server*.tar first — k3s auto-imports EVERY tar
    # in this dir on each (re)start, so a stale tarball would silently shadow this
    # build under the reused arxmcp-server:dev tag ("I rebuilt but it runs old code").
    echo "   (needs root; k3s auto-imports ALL tarballs here on its next start)"
    sudo mkdir -p "$AIRGAP_DIR"
    sudo rm -f "$AIRGAP_DIR"/arxmcp-server*.tar
    sudo cp "$TARBALL" "$AIRGAP_DIR/arxmcp-server.tar"
    echo "   placed tarball; restart k3s (or Rancher Desktop) to import it."
  fi
else
  echo "ERROR: neither 'nerdctl' nor 'docker' on PATH. Run this inside the" >&2
  echo "       Rancher Desktop shell (containerd mode gives you nerdctl)." >&2
  exit 1
fi

echo ">> done. Next: kubectl apply -f infra/k8s/  (see docs/ops/k3s-rancher-desktop.md)"
