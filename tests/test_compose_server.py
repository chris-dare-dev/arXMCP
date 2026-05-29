"""notebook-ops-hardening-m3 — server docker-compose smoke tests.

The AC explicitly scopes the automated test to static inspection ("a test
inspects the compose/middleware stack to assert the prefix loopback binding —
no live 201 MB upload needed"). The live ``docker compose up`` → ``/readyz``
200 is operator-acceptance (it builds the image + downloads BGE-M3 ~2.3 GB)
and is documented in ``docs/install.md``, NOT run here.

Mirrors ``tests/test_compose_phoenix.py``: a PyYAML pass that always runs (no
Docker dependency) + an optional ``docker compose config`` validation gated on
``docker`` being on PATH (that one also pins the load-bearing bind-mount-path
resolution — RESOLVED #1 in the research synthesis).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = REPO_ROOT / "infra" / "docker-compose.yml"
DOCKERFILE_PATH = REPO_ROOT / "docker" / "Dockerfile.server"


def _service(spec: dict) -> dict:
    services = spec.get("services", {})
    assert "server" in services, "compose must define a 'server' service"
    return services["server"]


def _env_map(svc: dict) -> dict[str, str]:
    env = svc.get("environment", {})
    if isinstance(env, list):
        return dict(item.split("=", 1) for item in env)
    return {k: str(v) for k, v in env.items()}


def test_compose_path_exists() -> None:
    assert COMPOSE_PATH.is_file(), (
        f"expected server compose file at {COMPOSE_PATH}; "
        f"notebook-ops-hardening-m3 is incomplete if this is missing"
    )


def test_loopback_only_port_bindings() -> None:
    """AC2/AC3 + 08-security threat model: every host port mapping must start
    with 127.0.0.1: so the LAN can never reach the server. A bare 0.0.0.0 (or
    a missing host-IP prefix) is rejected."""
    svc = _service(yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8")))
    ports = svc.get("ports", [])
    assert ports, "server service must declare at least one port"
    for entry in ports:
        assert isinstance(entry, str), (
            f"port entry must be a string for loopback discipline; got {entry!r}"
        )
        assert entry.startswith("127.0.0.1:"), (
            f"port {entry!r} does not bind to 127.0.0.1 (host side); would "
            f"expose the MCP server to the LAN"
        )
        assert "0.0.0.0" not in entry, f"host-side 0.0.0.0 in port {entry!r}"


def test_bind_mount_uses_single_dotdot_prefix() -> None:
    """RESOLVED #1 / F1-class trap: Compose resolves relative bind paths
    against the compose FILE's parent (infra/), so the repo-root var/arxmcp is
    reached with ONE '../'. A bare './var' lands at infra/var; '../../var'
    lands ABOVE the repo. Pin the exact source string."""
    svc = _service(yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8")))
    volumes = svc.get("volumes", [])
    assert volumes, "server service must bind-mount var/arxmcp"
    sources = []
    for v in volumes:
        if isinstance(v, str):
            sources.append(v.split(":", 1)[0])
        elif isinstance(v, dict):
            sources.append(v.get("source"))
    assert "../var/arxmcp" in sources, (
        f"server must bind-mount '../var/arxmcp' (ONE '../' — resolves to "
        f"repo-root var/arxmcp); got {sources!r}"
    )
    assert "./var/arxmcp" not in sources, "bare './var/arxmcp' lands in infra/"
    assert "../../var/arxmcp" not in sources, (
        "'../../var/arxmcp' resolves ABOVE the repo root — the F1 trap"
    )


def test_capability_hardening() -> None:
    svc = _service(yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8")))
    assert "ALL" in (svc.get("cap_drop") or []), "cap_drop must contain ALL"
    sec = svc.get("security_opt") or []
    assert any("no-new-privileges" in s for s in sec), (
        "security_opt must include no-new-privileges:true"
    )
    assert svc.get("init") is True, "init: true required (tini zombie reaping)"


def test_in_container_bind_override_env() -> None:
    """The in-container 0.0.0.0 bind requires BOTH ARXMCP_BIND_HOST=0.0.0.0
    AND ARXMCP_UNSAFE_NETWORK_BIND set, or server config parse crashes."""
    env = _env_map(_service(
        yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    ))
    assert env.get("ARXMCP_BIND_HOST") == "0.0.0.0", (
        "ARXMCP_BIND_HOST must be 0.0.0.0 inside the container"
    )
    assert env.get("ARXMCP_UNSAFE_NETWORK_BIND") in ("1", "true", "True"), (
        "ARXMCP_UNSAFE_NETWORK_BIND must be set or config parse rejects the "
        "0.0.0.0 bind"
    )


def test_contact_email_not_in_server_env() -> None:
    """ARXMCP_CONTACT_EMAIL is an ingest-tool concern, not a server Config
    field; the server Config forbids unknown ARXMCP_* vars. It must NOT be in
    the server-only v0 compose env."""
    env = _env_map(_service(
        yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    ))
    assert "ARXMCP_CONTACT_EMAIL" not in env, (
        "ARXMCP_CONTACT_EMAIL must not be set on the server service "
        "(ingest-only; risks a config-parse ValidationError)"
    )


def test_healthcheck_targets_readyz() -> None:
    svc = _service(yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8")))
    hc = svc.get("healthcheck", {})
    test = hc.get("test", [])
    joined = " ".join(test) if isinstance(test, list) else str(test)
    assert "/readyz" in joined, "healthcheck must probe /readyz"


def test_resource_limits_set() -> None:
    svc = _service(yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8")))
    assert "mem_limit" in svc, "mem_limit required (bound BGE-M3 footprint)"
    assert "cpus" in svc, "cpus required"


def test_builds_from_project_dockerfile() -> None:
    svc = _service(yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8")))
    build = svc.get("build", {})
    assert isinstance(build, dict), "build must be a context/dockerfile mapping"
    assert build.get("dockerfile") == "docker/Dockerfile.server", (
        f"build.dockerfile must be docker/Dockerfile.server; got {build!r}"
    )


def test_dockerfile_base_images_are_sha256_pinned() -> None:
    """AC: @sha256 base-image pins. Both FROM python:3.11-slim stages must
    carry an @sha256: digest (supply-chain hygiene, 08-security §Threat 6)."""
    text = DOCKERFILE_PATH.read_text(encoding="utf-8")
    from_lines = [
        ln for ln in text.splitlines() if ln.startswith("FROM python:")
    ]
    assert len(from_lines) >= 2, (
        f"expected >=2 FROM python: stages; got {from_lines!r}"
    )
    for ln in from_lines:
        assert "@sha256:" in ln, (
            f"FROM line is not digest-pinned: {ln!r}"
        )


@pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="docker not on PATH; skipping Compose Spec validation",
)
def test_compose_config_resolves_bind_to_repo_root() -> None:
    """Run `docker compose config` and assert the bind-mount source resolves
    to the repo-root var/arxmcp (the empirical RESOLVED #1 guard) and the
    published port is host-IP 127.0.0.1. Validates full Compose Spec
    semantics that yaml.safe_load alone cannot (path resolution, port shape)."""
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_PATH), "config"],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, (
        f"docker compose config failed: stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
    resolved = yaml.safe_load(result.stdout)
    svc = resolved["services"]["server"]

    volumes = svc.get("volumes", [])
    assert len(volumes) == 1, f"expected 1 volume, got {volumes!r}"
    src = volumes[0].get("source") if isinstance(volumes[0], dict) else None
    assert src is not None, f"could not extract volume source from {volumes[0]!r}"
    assert src == str(REPO_ROOT / "var" / "arxmcp"), (
        f"bind-mount source did not resolve to repo-root var/arxmcp; "
        f"got {src!r} (RESOLVED #1 regression — wrong '../' depth)"
    )
    assert "/infra/var/" not in src, (
        f"bind-mount resolved INSIDE infra/ — relative-path bug. Got {src!r}"
    )

    # Host-side port must be loopback.
    ports = svc.get("ports", [])
    assert ports, "no ports after config resolution"
    for p in ports:
        host_ip = p.get("host_ip") if isinstance(p, dict) else None
        assert host_ip == "127.0.0.1", (
            f"published port host_ip must be 127.0.0.1; got {p!r}"
        )
