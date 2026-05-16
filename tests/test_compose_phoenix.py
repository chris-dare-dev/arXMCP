"""E14_S03 — Phoenix compose-file smoke tests.

Two tests:

1. :func:`test_compose_file_parses` — runs
   ``docker compose -f infra/observability/phoenix-compose.yml
   config --quiet`` and asserts exit-0. Skipped on hosts without
   ``docker`` on PATH (the same pattern as the ``requires_model``
   marker — pulling in Docker as a test prereq is heavier than
   the marginal coverage). Validates the full Compose Spec
   semantics that ``yaml.safe_load`` alone won't catch
   (interpolation, profile syntax, port-mapping shape).

2. :func:`test_loopback_only_port_bindings` — parses the YAML
   directly with ``yaml.safe_load`` (no Docker dependency) and
   asserts every entry under ``services.phoenix.ports`` starts
   with ``127.0.0.1:``. Regression guard for the E14_S03 Risk
   note (Phoenix-bound spans carry ``mcp.session_id``;
   forwarding to the LAN would leak session IDs).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

COMPOSE_PATH = (
    Path(__file__).resolve().parents[1]
    / "infra"
    / "observability"
    / "phoenix-compose.yml"
)


def test_compose_path_exists() -> None:
    """Sanity check — without the file present the other tests
    cannot run. Asserted at module-collect time so a missing
    deliverable surfaces immediately rather than via skip-cascade."""
    assert COMPOSE_PATH.is_file(), (
        f"expected Phoenix compose file at {COMPOSE_PATH}; the "
        f"E14_S03 milestone is incomplete if this is missing"
    )


def test_loopback_only_port_bindings() -> None:
    """E14_S03 Risk-note regression guard: every host port mapping
    must start with ``127.0.0.1:``. Phoenix receives spans that
    carry ``mcp.session_id`` (per
    ``.claude/notes/08-security-observability-ops.md`` §Tracing);
    leaking those to the LAN is exactly the threat the Risk note
    flags.

    Parses the YAML directly so the test runs without Docker on
    PATH."""
    spec = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    services = spec.get("services", {})
    assert "phoenix" in services, "phoenix service missing from compose"
    ports = services["phoenix"].get("ports", [])
    assert ports, "phoenix service must declare at least one port"
    for entry in ports:
        # Compose port shape may be string ("host:cont") or dict
        # ({"published": ..., "target": ...}). The string form is
        # the one this milestone ships; assert it explicitly.
        assert isinstance(entry, str), (
            f"port entry must be a string for loopback discipline; "
            f"got {entry!r}"
        )
        assert entry.startswith("127.0.0.1:"), (
            f"port {entry!r} does not bind to 127.0.0.1; would "
            f"leak mcp.session_id-bearing spans to the LAN"
        )


def test_no_phoenix_telemetry() -> None:
    """E14_S03 D3: ``PHOENIX_TELEMETRY_ENABLED=false`` so the only
    outbound network call is the one-time Docker Hub pull. A
    regression that flips this would re-introduce a phone-home."""
    spec = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    env = spec["services"]["phoenix"].get("environment", {})
    # environment can be a list of "K=V" strings or a dict.
    if isinstance(env, list):
        env_map = dict(item.split("=", 1) for item in env)
    else:
        env_map = {k: str(v) for k, v in env.items()}
    assert env_map.get("PHOENIX_TELEMETRY_ENABLED", "").lower() == "false", (
        "PHOENIX_TELEMETRY_ENABLED must be 'false' so Phoenix "
        "does not phone home its usage stats"
    )


def test_retention_policy_bounded() -> None:
    """Bounded SQLite trace store. Default Phoenix retention is
    infinite; we cap to a finite number of days so a long-running
    dev loop doesn't fill the host disk."""
    spec = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    env = spec["services"]["phoenix"].get("environment", {})
    if isinstance(env, list):
        env_map = dict(item.split("=", 1) for item in env)
    else:
        env_map = {k: str(v) for k, v in env.items()}
    retention = env_map.get("PHOENIX_DEFAULT_RETENTION_POLICY_DAYS")
    assert retention is not None, "retention policy must be set"
    days = int(retention)
    assert 1 <= days <= 365, (
        f"retention days must be in [1, 365]; got {days} "
        f"(0=infinite is rejected per E14_S03 D3)"
    )


@pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="docker not on PATH; skipping Compose Spec validation",
)
def test_compose_file_parses() -> None:
    """Run ``docker compose config --quiet`` to validate the full
    Compose Spec semantics (profile syntax, env-var interpolation,
    healthcheck shape, port-mapping form). The YAML-only tests
    above catch the most-important invariants without requiring
    Docker; this test catches everything else when Docker is
    available."""
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_PATH), "config", "--quiet"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, (
        f"docker compose config failed: stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
