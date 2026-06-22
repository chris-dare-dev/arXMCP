"""k3s-rancher-deploy-m1 — static validation of the k3s manifests.

Mirrors ``tests/test_compose_server.py``: a PyYAML pass that always runs (no
``kubectl`` / cluster dependency) asserting the load-bearing invariants of the
``infra/k8s/`` manifest set, plus an optional ``kubeconform`` schema check gated
on that binary being on PATH.

The live ``kubectl apply`` → ``/readyz`` 200 is operator-acceptance (it builds
the image + downloads BGE-M3 ~2.3 GB) and is documented in
``docs/ops/k3s-rancher-desktop.md``, NOT run here.

RUNTIME-UNVERIFIED (F3): these assertions prove the manifests are AUTHORED
correctly (fields present, well-typed) — NOT that the pod BOOTS. In particular
``readOnlyRootFilesystem: true`` is exercised for the first time here (Compose
never set ``--read-only``); whether every writable path is covered is
operator-acceptance via the gated ``kubectl apply`` → ``/readyz`` step
(runbook §5/§8), not provable statically.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
K8S_DIR = REPO_ROOT / "infra" / "k8s"

#: The pinned local image tag (imagePullPolicy: Never side-loads it into k3s).
EXPECTED_IMAGE = "arxmcp-server:dev"
#: NodePort the Service must publish (stable, so the shim URL is predictable).
EXPECTED_NODEPORT = 30733
#: Container port the server listens on (server/config.py DEFAULT_BIND_PORT).
SERVER_PORT = 7733


def _load_docs() -> list[dict]:
    """Every YAML document across infra/k8s/*.yaml (non-recursive — scripts/ is
    excluded). Each manifest file is single-document, but safe_load_all keeps
    this robust if one ever bundles multiple."""
    docs: list[dict] = []
    files = sorted(K8S_DIR.glob("*.yaml"))
    assert files, f"no manifests found in {K8S_DIR}"
    for f in files:
        for doc in yaml.safe_load_all(f.read_text(encoding="utf-8")):
            if doc is not None:
                doc["__file__"] = f.name
                docs.append(doc)
    return docs


def _by_kind(kind: str) -> dict:
    matches = [d for d in _load_docs() if d.get("kind") == kind]
    assert len(matches) == 1, f"expected exactly one {kind}, found {len(matches)}"
    return matches[0]


def _containers(deployment: dict) -> list[dict]:
    return deployment["spec"]["template"]["spec"]["containers"]


def test_k8s_dir_exists() -> None:
    assert K8S_DIR.is_dir(), f"expected k3s manifests at {K8S_DIR}"


def test_all_manifests_have_required_top_level_keys() -> None:
    for doc in _load_docs():
        where = doc.get("__file__", "?")
        assert doc.get("apiVersion"), f"{where}: missing apiVersion"
        assert doc.get("kind"), f"{where}: missing kind"
        assert doc.get("metadata", {}).get("name"), f"{where}: missing metadata.name"
        if doc["kind"] != "Namespace":
            assert (
                doc["metadata"].get("namespace") == "arxmcp"
            ), f"{where}: must be namespaced to 'arxmcp'"


def test_namespace() -> None:
    ns = _by_kind("Namespace")
    assert ns["metadata"]["name"] == "arxmcp"


def test_configmap_required_env_present() -> None:
    """FM-F: the 0.0.0.0 bind REQUIRES the unsafe flag or the pod CrashLoops.
    FM-C: HF_HOME must redirect the HuggingFace cache onto the PVC, else
    readOnlyRootFilesystem breaks the first-run model download."""
    data = _by_kind("ConfigMap")["data"]
    assert data.get("ARXMCP_BIND_HOST") == "0.0.0.0"
    assert data.get("ARXMCP_UNSAFE_NETWORK_BIND") == "1"
    assert data.get("ARXMCP_BOOTSTRAP_MODE") == "1"
    assert data.get("HF_HOME"), "HF_HOME must redirect the HF cache onto the PVC"
    assert data["HF_HOME"].startswith("/app/var/arxmcp/")
    # F1: non-HF cache writers must also be redirected off the read-only rootfs.
    assert data.get("XDG_CACHE_HOME", "").startswith("/app/var/arxmcp/"), (
        "XDG_CACHE_HOME must redirect ~/.cache off the read-only rootfs (F1)"
    )
    assert data.get("MPLCONFIGDIR"), "MPLCONFIGDIR must redirect matplotlib config (F1)"


def test_configmap_arxmcp_keys_are_real_config_fields() -> None:
    """FM-I: server/config.py uses env_prefix=ARXMCP_ + extra='forbid' — an
    unknown ARXMCP_* var crashes the pod at startup. Every ARXMCP_* ConfigMap
    key must map to a declared Config field. Skips only if the server package
    cannot be imported in this environment (keeps the manifest test hermetic)."""
    try:
        from server.config import Config
    except Exception as exc:  # pragma: no cover - import-environment dependent
        pytest.skip(f"server.config not importable here: {exc}")

    field_names = set(Config.model_fields.keys())
    data = _by_kind("ConfigMap")["data"]
    for key in data:
        if key.startswith("ARXMCP_"):
            field = key[len("ARXMCP_") :].lower()
            assert field in field_names, (
                f"ConfigMap sets {key}, but '{field}' is not a Config field — "
                f"extra='forbid' would crash the pod at startup"
            )


def test_deployment_image_is_pinned_and_never_pulled() -> None:
    for c in _containers(_by_kind("Deployment")):
        assert c["image"] == EXPECTED_IMAGE, f"image must be {EXPECTED_IMAGE}"
        assert not c["image"].endswith(":latest"), ":latest is banned (CLAUDE.md §4.7)"
        assert c["imagePullPolicy"] == "Never", "image is side-loaded; never pull"


def test_deployment_security_context() -> None:
    """Mirrors Compose's cap_drop:[ALL] + no-new-privileges + non-root UID 1000."""
    dep = _by_kind("Deployment")
    pod_sc = dep["spec"]["template"]["spec"]["securityContext"]
    assert pod_sc["runAsNonRoot"] is True
    assert pod_sc["runAsUser"] == 1000
    assert pod_sc["runAsGroup"] == 1000
    assert pod_sc["fsGroup"] == 1000, "fsGroup chowns the local-path PVC (FM-B)"
    assert pod_sc["seccompProfile"]["type"] == "RuntimeDefault"
    # F2 / IS1 (cross-critic): the unused default ServiceAccount token must not
    # be auto-mounted — standing blast radius on a process compromise.
    assert (
        dep["spec"]["template"]["spec"].get("automountServiceAccountToken") is False
    ), "automountServiceAccountToken must be False (F2/IS1)"

    for c in _containers(dep):
        csc = c["securityContext"]
        assert csc["allowPrivilegeEscalation"] is False
        assert csc["readOnlyRootFilesystem"] is True
        assert csc["capabilities"]["drop"] == ["ALL"]


def test_deployment_probes() -> None:
    """startupProbe MUST use /readyz (covers the BGE-M3 warm window); liveness
    uses /healthz (always-200 once the process responds)."""
    for c in _containers(_by_kind("Deployment")):
        assert c["startupProbe"]["httpGet"]["path"] == "/readyz"
        # >= 5-minute window for the first-run BGE-M3 download.
        budget = c["startupProbe"]["failureThreshold"] * c["startupProbe"]["periodSeconds"]
        assert budget >= 300, f"startupProbe window {budget}s < 300s; BGE-M3 may not warm"
        assert c["readinessProbe"]["httpGet"]["path"] == "/readyz"
        assert c["livenessProbe"]["httpGet"]["path"] == "/healthz"


def test_deployment_resources_bounded() -> None:
    for c in _containers(_by_kind("Deployment")):
        limits = c["resources"]["limits"]
        assert limits.get("memory"), "memory limit must be set (BGE-M3 OOM guard)"
        assert limits.get("cpu"), "cpu limit must be set"


def test_deployment_writable_paths_only_pvc_and_tmp() -> None:
    """Under readOnlyRootFilesystem, the only writable mounts are the PVC and an
    emptyDir /tmp. Confirm both exist."""
    dep = _by_kind("Deployment")
    volumes = {v["name"]: v for v in dep["spec"]["template"]["spec"]["volumes"]}
    assert "var" in volumes and "persistentVolumeClaim" in volumes["var"]
    assert "tmp" in volumes and "emptyDir" in volumes["tmp"]
    for c in _containers(dep):
        mounts = {m["name"]: m["mountPath"] for m in c["volumeMounts"]}
        assert mounts.get("var") == "/app/var/arxmcp"
        assert mounts.get("tmp") == "/tmp"


def test_service_is_loopback_safe_nodeport() -> None:
    """NodePort (not Traefik Ingress) so Rancher Desktop forwards it to
    127.0.0.1 — see research-synthesis.md §3."""
    svc = _by_kind("Service")
    assert svc["spec"]["type"] == "NodePort"
    port = svc["spec"]["ports"][0]
    assert port["nodePort"] == EXPECTED_NODEPORT
    assert port["port"] == SERVER_PORT


def test_pvc_local_path_rwo() -> None:
    pvc = _by_kind("PersistentVolumeClaim")
    assert pvc["spec"]["storageClassName"] == "local-path"
    assert pvc["spec"]["accessModes"] == ["ReadWriteOnce"]


def test_networkpolicy_restricts_ingress() -> None:
    np = _by_kind("NetworkPolicy")
    assert "Ingress" in np["spec"]["policyTypes"]
    # The single ingress rule restricts to the server port.
    ports = np["spec"]["ingress"][0]["ports"]
    assert any(p["port"] == SERVER_PORT for p in ports)


def test_no_latest_tags_anywhere() -> None:
    for doc in _load_docs():
        for c in doc.get("spec", {}).get("template", {}).get("spec", {}).get(
            "containers", []
        ):
            assert not str(c.get("image", "")).endswith(":latest"), (
                f"{doc['__file__']}: :latest image tag is banned"
            )


@pytest.mark.skipif(
    shutil.which("kubeconform") is None, reason="kubeconform not on PATH"
)
def test_kubeconform_schema_validation() -> None:
    """Optional: full schema validation when kubeconform is installed. Skipped
    by default (no binary dependency in CI / the Windows dev box)."""
    files = [str(p) for p in sorted(K8S_DIR.glob("*.yaml"))]
    result = subprocess.run(
        ["kubeconform", "-strict", "-summary", *files],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"kubeconform failed:\n{result.stdout}\n{result.stderr}"
