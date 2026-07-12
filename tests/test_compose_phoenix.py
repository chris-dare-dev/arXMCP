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
def test_compose_file_parses_with_profile() -> None:
    """Run ``docker compose --profile phoenix config`` and parse
    the result to assert:

    - The Phoenix service materializes when the profile is active.
    - The bind-mount ``source:`` resolves to the repo-root
      ``var/arxmcp/observability/phoenix`` (F1 regression guard —
      Compose v2 resolves relative paths against the compose-
      file's directory, so a bare ``./var/...`` would have landed
      under ``infra/observability/var/...``).
    - The pinned image references an ``arizephoenix/phoenix:``
      tag AND carries an ``@sha256:`` digest (F7/IS3 supply-chain
      pin).

    The prior version of this test omitted ``--profile phoenix``,
    so ``compose config`` returned a services-empty graph and
    trivially validated. F2 rectification from the E14_S03
    adversary critique.
    """
    result = subprocess.run(
        [
            "docker", "compose",
            "-f", str(COMPOSE_PATH),
            "--profile", "phoenix",
            "config",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, (
        f"docker compose config failed: stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )

    resolved = yaml.safe_load(result.stdout)
    services = resolved.get("services", {})
    assert "phoenix" in services, (
        "compose --profile phoenix did NOT materialize the "
        "phoenix service; check the profiles: directive"
    )

    phoenix = services["phoenix"]

    # F7/IS3 — image must carry an @sha256: digest pin.
    image = phoenix.get("image", "")
    assert image.startswith("arizephoenix/phoenix:"), (
        f"unexpected image prefix: {image!r}"
    )
    assert "@sha256:" in image, (
        f"image must be digest-pinned for supply-chain hygiene; "
        f"got {image!r}"
    )

    # F1 — bind-mount source must resolve to repo-root var/arxmcp,
    # NOT to infra/observability/var/arxmcp.
    volumes = phoenix.get("volumes", [])
    assert len(volumes) == 1, f"expected 1 volume, got {volumes!r}"
    src = volumes[0].get("source") if isinstance(volumes[0], dict) else None
    assert src is not None, f"could not extract volume source from {volumes[0]!r}"
    # Normalize separators: the resolved bind-mount source is backslash-
    # joined on Windows, which would break the forward-slash checks below
    # (and would silently defeat the negative "/infra/.../var/" guard).
    src = src.replace("\\", "/")
    assert src.endswith("/var/arxmcp/observability/phoenix"), (
        f"bind-mount source did not resolve to repo-root "
        f"var/arxmcp/...; got {src!r}. F1 regression."
    )
    assert "/infra/observability/var/" not in src, (
        f"bind-mount source resolved INSIDE infra/ — "
        f"compose-file-relative resolution bug. Got {src!r}"
    )


def test_restart_policy_is_no() -> None:
    """F3 rectification — Phoenix MUST NOT silently relaunch on
    host reboot. The compose file's restart policy must be ``no``
    (or ``on-failure``); ``unless-stopped`` re-opens a Phoenix UI
    bearing accumulated mcp.session_id-bearing spans after every
    reboot, which on a multi-user workstation is a session-id
    leak surface that the operator does not expect."""
    spec = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    restart = spec["services"]["phoenix"].get("restart", "always")
    assert restart in ("no", "on-failure"), (
        f"Phoenix restart policy must be 'no' or 'on-failure' "
        f"(opt-in dev-tool posture); got {restart!r}. See F3 in "
        f"the E14_S03 adversary critique."
    )


def test_resource_limits_set() -> None:
    """F8/IS2 — Phoenix must declare ``mem_limit`` and ``cpus``
    so a runaway sidecar can't starve the MCP server's BGE-M3
    worker."""
    spec = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    svc = spec["services"]["phoenix"]
    assert "mem_limit" in svc, "mem_limit must be declared"
    assert "cpus" in svc, "cpus must be declared"


def test_capability_hardening() -> None:
    """IS5 — Phoenix must drop default Linux capabilities and
    block privilege escalation."""
    spec = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    svc = spec["services"]["phoenix"]
    cap_drop = svc.get("cap_drop", [])
    assert "ALL" in cap_drop, (
        f"cap_drop must include ALL; got {cap_drop!r}"
    )
    security_opt = svc.get("security_opt", [])
    assert any(
        "no-new-privileges" in s for s in security_opt
    ), f"security_opt must include no-new-privileges; got {security_opt!r}"


def test_init_for_pid1_reaping() -> None:
    """IS8 — ``init: true`` injects tini as PID 1 so signal
    handling on ``docker compose down`` matches the project's
    docker/Dockerfile.server precedent."""
    spec = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    assert spec["services"]["phoenix"].get("init") is True, (
        "init: true must be set on the phoenix service"
    )
