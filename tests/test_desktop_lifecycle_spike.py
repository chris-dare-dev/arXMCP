from __future__ import annotations

import importlib.util
import json
import subprocess
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
    assert harness._post_run_audit(None)["clean"] is False


def test_event_validator_rejects_reordering_and_duplicate_sequences() -> None:
    harness = _load_harness()
    records = [
        {
            "v": 1,
            "seq": index,
            "event": event,
            "host_pid": 42,
            "run_id": "test-run",
            "scenario": "normal",
        }
        for index, event in enumerate(harness.EXPECTED_TRACES["normal"], start=1)
    ]
    assert harness._validate_event_records(records, "normal", "test-run")[0]
    records[3], records[4] = records[4], records[3]
    assert not harness._validate_event_records(records, "normal", "test-run")[0]
    records[3]["seq"] = records[2]["seq"]
    assert not harness._validate_event_records(records, "normal", "test-run")[0]


def test_process_and_listener_probe_failures_are_not_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _load_harness()

    def failed_bytes(*_args, **_kwargs):
        return subprocess.CompletedProcess([], 2, b"", b"denied")

    monkeypatch.setattr(harness.subprocess, "run", failed_bytes)
    assert not harness._secret_process_scan({123})

    def failed_text(*_args, **_kwargs):
        return subprocess.CompletedProcess([], 2, "", "denied")

    monkeypatch.setattr(harness.subprocess, "run", failed_text)
    audit = harness._listener_audit(7733)
    assert audit["completed"] is False
    assert audit["rows"] == []


def test_provenance_validator_rejects_stale_or_substitute_inputs() -> None:
    harness = _load_harness()
    digest = "a" * 64
    host = {
        "schema_version": 1,
        "role": "tauri-host",
        "tauri_host": True,
        "source_sha256": digest,
        "dependencies": harness.PINNED_DEPENDENCIES,
    }
    fixture = {**host, "role": "fixture-sidecar", "tauri_host": False}
    harness._validate_provenance(host, fixture, digest)
    with pytest.raises(RuntimeError, match="source provenance mismatch"):
        harness._validate_provenance({**host, "source_sha256": "b" * 64}, fixture, digest)
    with pytest.raises(RuntimeError, match="identity mismatch"):
        harness._validate_provenance({**host, "role": "shell-script"}, fixture, digest)


def test_committed_lifecycle_evidence_is_go() -> None:
    payload = json.loads(RESULTS.read_text(encoding="utf-8"))
    assert payload["decision"] == "GO"
    assert payload["artifacts"]["host_is_tauri_binary"] is True
    harness = _load_harness()
    assert payload["artifacts"]["source_sha256"] == harness._tracked_source_digest()
    assert payload["artifacts"]["build_provenance"]["host"]["role"] == "tauri-host"
    assert (
        payload["artifacts"]["build_provenance"]["fixture"]["role"]
        == "fixture-sidecar"
    )
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
    cases = {item["scenario"]: item for item in payload["fault_matrix"]}
    startup = cases["startup-timeout"]
    assert startup["post_run_audit"]["identity_source"] == "sidecar_spawned"
    assert startup["post_run_audit"]["audit_complete"] is True
    assert "direct_sigterm" in startup["events"]
    duplicate = cases["duplicate"]
    assert duplicate["duplicate_launch"]["startup_overlap"] is True
    assert duplicate["events"].count("duplicate_activation") <= 1
    assert (
        duplicate["duplicate_arbitration"]["activations"] == 1
        or duplicate["duplicate_arbitration"]["supervisor_lock_contention"] is True
    )
    for scenario in ("crash-before-bound", "crash-after-ready"):
        result = cases[scenario]
        assert result["post_run_audit"]["metadata_present"] is True
        assert "crash_group_sigterm" in result["events"]
        assert "crash_group_clean" in result["events"]
    assert all(item["event_trace_valid"] for item in payload["fault_matrix"])
    assert all(
        item["event_trace_valid"] for item in payload["thirty_cycle_gate"]["cycles"]
    )
    assert ADR.is_file()


@pytest.mark.parametrize("case", ["wildcard-v4", "wildcard-v6", "malformed-bound"])
def test_invalid_bound_cases_record_rejection(case: str) -> None:
    payload = json.loads(RESULTS.read_text(encoding="utf-8"))
    result = next(item for item in payload["fault_matrix"] if item["scenario"] == case)
    assert "invalid_bound_rejected" in result["events"]
