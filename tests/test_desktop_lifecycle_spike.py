from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPIKE = ROOT / "tools" / "desktop_lifecycle_spike"
RESULTS = (
    ROOT
    / ".claude"
    / "notes"
    / "milestones"
    / "desktop-distribution-spike-3"
    / "implement"
    / "lifecycle-results.json"
)
ADR = ROOT / ".claude" / "notes" / "spikes" / "desktop-distribution-spike-3.md"


def _load_harness():
    spec = importlib.util.spec_from_file_location("desktop_lifecycle_spike", SPIKE / "run_spike.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load lifecycle spike harness")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rust_dependencies_are_exactly_pinned() -> None:
    manifest = (SPIKE / "Cargo.toml").read_text(encoding="utf-8")
    assert 'tauri = "=2.11.5"' in manifest
    assert 'tauri-plugin-shell = "=2.3.5"' in manifest
    assert 'tauri-plugin-single-instance = "=2.4.3"' in manifest
    assert (SPIKE / "Cargo.lock").is_file()


def test_host_uses_tauri_sidecar_and_group_escalation() -> None:
    source = (SPIKE / "src" / "main.rs").read_text(encoding="utf-8")
    single_instance = source.index(".plugin(tauri_plugin_single_instance::init")
    shell = source.index(".plugin(tauri_plugin_shell::init())")
    assert single_instance < shell
    assert ".sidecar(SIDECAR_NAME)" in source
    assert 'concat!("fixture-sidecar-", env!("TAURI_ENV_TARGET_TRIPLE"))' in source
    assert ".env_clear()" in source
    assert "libc::SIGTERM" in source
    assert "libc::SIGKILL" in source


def test_harness_helpers_reject_secret_canary(tmp_path: Path) -> None:
    harness = _load_harness()
    (tmp_path / "safe.log").write_text("bounded public event\n", encoding="utf-8")
    assert harness._files_secret_clean(tmp_path, b"", b"")
    (tmp_path / "unsafe.log").write_bytes(harness.TOKEN_CANARY + b"redacted")
    assert not harness._files_secret_clean(tmp_path, b"", b"")


def test_harness_requires_complete_fault_matrix() -> None:
    harness = _load_harness()
    assert set(harness.FAULT_CASES) == {
        "normal",
        "duplicate",
        "startup-timeout",
        "malformed-bound",
        "wildcard-v4",
        "wildcard-v6",
        "never-ready",
        "crash-before-bound",
        "crash-after-ready",
        "ignore-shutdown",
        "parent-crash",
    }
    assert harness._post_run_audit(None)["clean"] is True


def test_committed_lifecycle_evidence_is_go() -> None:
    payload = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert payload["decision"] == "GO"
    assert payload["artifacts"]["host_is_tauri_binary"] is True
    assert len(payload["fault_matrix"]) == 11
    assert all(item["ok"] for item in payload["fault_matrix"])
    cycle_gate = payload["thirty_cycle_gate"]
    assert cycle_gate["completed"] == 30
    assert cycle_gate["all_passed"] is True
    assert len(cycle_gate["cycles"]) == 30
    assert payload["totals"] == {
        "orphan_process_groups": 0,
        "residual_listeners": 0,
        "secret_scan_failures": 0,
    }
    assert ADR.is_file()


@pytest.mark.parametrize("case", ["wildcard-v4", "wildcard-v6", "malformed-bound"])
def test_invalid_bound_cases_record_rejection(case: str) -> None:
    payload = json.loads(RESULTS.read_text(encoding="utf-8"))
    result = next(item for item in payload["fault_matrix"] if item["scenario"] == case)
    assert "invalid_bound_rejected" in result["events"]
