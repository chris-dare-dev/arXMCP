"""E14_S05 — Prometheus alert-rules file smoke tests.

The PyYAML-only tests run everywhere and pin the alert names +
expressions against the failure-mode runbook. The ``promtool
check rules`` test skips when ``promtool`` is not on PATH (same
defer pattern as ``crontab -T`` in E14_S04 — installing the full
Prometheus binary as a CI prereq is heavier than the marginal
coverage).
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest
import yaml

ALERTS_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "infra"
    / "prometheus"
    / "alerts.yml"
)


def test_alerts_file_exists():
    assert ALERTS_PATH.is_file(), (
        f"expected Prometheus alerts file at {ALERTS_PATH}; "
        f"the E14_S05 milestone is incomplete if this is missing"
    )


def test_yaml_parses_top_level_groups():
    spec = yaml.safe_load(ALERTS_PATH.read_text(encoding="utf-8"))
    assert "groups" in spec, "Prometheus alert files must have a top-level groups: key"
    assert isinstance(spec["groups"], list)
    assert spec["groups"], "at least one group required"


def test_arxmcp_group_present():
    spec = yaml.safe_load(ALERTS_PATH.read_text(encoding="utf-8"))
    groups = {g["name"] for g in spec["groups"]}
    assert "arxmcp" in groups, (
        f"expected 'arxmcp' rule group; got {sorted(groups)}"
    )


def test_required_alerts_present():
    """E14_S05 D7 — these alerts must exist (the failure-mode
    runbook references them by name).
    """
    spec = yaml.safe_load(ALERTS_PATH.read_text(encoding="utf-8"))
    alerts: set[str] = set()
    for group in spec["groups"]:
        for rule in group.get("rules", []):
            if "alert" in rule:
                alerts.add(rule["alert"])

    required = {
        "ArXMCPDiskFull",
        "ArXMCPDegradedMode",
        "ArXMCPBackupStale",
    }
    missing = required - alerts
    assert not missing, (
        f"alert rules missing required entries: {sorted(missing)}; "
        f"got {sorted(alerts)}"
    )


def test_alert_rule_shape():
    """Every alert rule must have: alert, expr, for, labels,
    annotations. promtool would catch malformed shapes; we
    duplicate the check so the test always runs."""
    spec = yaml.safe_load(ALERTS_PATH.read_text(encoding="utf-8"))
    required_keys = {"alert", "expr", "for", "labels", "annotations"}
    for group in spec["groups"]:
        for rule in group.get("rules", []):
            if "alert" not in rule:
                continue  # recording rules are allowed
            missing = required_keys - rule.keys()
            assert not missing, (
                f"alert {rule.get('alert', '?')} missing keys: "
                f"{sorted(missing)}"
            )
            labels = rule["labels"]
            assert "severity" in labels, (
                f"alert {rule['alert']} missing severity label"
            )
            assert labels["severity"] in (
                "critical", "warning", "info", "page",
            ), (
                f"alert {rule['alert']} has non-canonical severity "
                f"{labels['severity']!r}"
            )


def test_disk_full_threshold_matches_implementation():
    """The Prometheus expression ``arxmcp_disk_free_bytes < 10737418240``
    must match the implementation's
    ``server.health.DISK_PAUSE_THRESHOLD_BYTES``. Drift here
    creates an operator surprise: the alert fires but ingest
    isn't paused, or vice versa."""
    from server.health import DISK_PAUSE_THRESHOLD_BYTES  # noqa: PLC0415

    spec = yaml.safe_load(ALERTS_PATH.read_text(encoding="utf-8"))
    for group in spec["groups"]:
        for rule in group.get("rules", []):
            if rule.get("alert") == "ArXMCPDiskFull":
                assert str(DISK_PAUSE_THRESHOLD_BYTES) in rule["expr"], (
                    f"ArXMCPDiskFull expr does not reference the "
                    f"DISK_PAUSE_THRESHOLD_BYTES constant value "
                    f"({DISK_PAUSE_THRESHOLD_BYTES}); the alert and "
                    f"the sentinel-write logic must agree."
                )
                return
    pytest.fail("ArXMCPDiskFull alert not found")


@pytest.mark.skipif(
    shutil.which("promtool") is None,
    reason="promtool not on PATH (install via `brew install prometheus` on macOS)",
)
def test_promtool_check_rules():
    """When promtool is available, run the canonical Prometheus
    rules validator. Catches expr/template/duration errors the
    PyYAML tests cannot."""
    result = subprocess.run(
        ["promtool", "check", "rules", str(ALERTS_PATH)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, (
        f"promtool check rules failed: stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
