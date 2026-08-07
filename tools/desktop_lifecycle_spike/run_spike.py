#!/usr/bin/env python3
"""Run the desktop lifecycle spike against built Tauri and sidecar binaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

TOKEN_CANARY = b"ARXMCP_SECRET_CANARY:"
CASE_TIMEOUT_SECONDS = 8.0
AUDIT_TIMEOUT_SECONDS = 4.0
POLL_SECONDS = 0.02
SPIKE_ROOT = Path(__file__).resolve().parent
SOURCE_FILES = (
    "Cargo.toml",
    "Cargo.lock",
    "build.rs",
    "run_spike.py",
    "tauri.conf.json",
    "src/lib.rs",
    "src/main.rs",
    "src/bin/fixture_sidecar.rs",
)
PINNED_DEPENDENCIES = {
    "tauri": "2.11.5",
    "tauri-plugin-shell": "2.3.5",
    "tauri-plugin-single-instance": "2.4.3",
}
MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
}
FAULT_CASES = (
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
)
EXPECTED_EVENTS = {
    "normal": {"ready_authenticated", "shutdown_sent", "sidecar_reaped"},
    "duplicate": {"duplicate_routed_to_primary", "sidecar_reaped"},
    "startup-timeout": {"startup_deadline_enforced", "sidecar_reaped"},
    "malformed-bound": {"invalid_bound_rejected", "sidecar_reaped"},
    "wildcard-v4": {"invalid_bound_rejected", "sidecar_reaped"},
    "wildcard-v6": {"invalid_bound_rejected", "sidecar_reaped"},
    "never-ready": {"readiness_deadline_enforced", "sidecar_reaped"},
    "crash-before-bound": {"expected_crash_before_bound"},
    "crash-after-ready": {"ready_authenticated", "expected_crash_after_ready"},
    "ignore-shutdown": {
        "shutdown_grace_expired",
        "group_sigterm",
        "group_sigkill",
        "sidecar_reaped",
    },
    "parent-crash": {"awaiting_parent_sigkill"},
}
EXPECTED_TRACES = {
    "normal": [
        "lifecycle_started",
        "sidecar_spawned",
        "bootstrap_sent",
        "bound_validated",
        "health_ok",
        "ready_authenticated",
        "shutdown_sent",
        "sidecar_reaped",
        "secret_scan_clean",
        "host_completed",
    ],
    "duplicate": [
        "lifecycle_started",
        "sidecar_spawned",
        "bootstrap_sent",
        "bound_validated",
        "health_ok",
        "ready_authenticated",
        "duplicate_routed_to_primary",
        "shutdown_sent",
        "sidecar_reaped",
        "secret_scan_clean",
        "host_completed",
    ],
    "startup-timeout": [
        "lifecycle_started",
        "sidecar_spawned",
        "bootstrap_sent",
        "startup_deadline_enforced",
        "direct_sigterm",
        "sidecar_reaped",
        "secret_scan_clean",
        "host_completed",
    ],
    "malformed-bound": [
        "lifecycle_started",
        "sidecar_spawned",
        "bootstrap_sent",
        "invalid_bound_rejected",
        "group_sigterm",
        "sidecar_reaped",
        "secret_scan_clean",
        "host_completed",
    ],
    "wildcard-v4": [
        "lifecycle_started",
        "sidecar_spawned",
        "bootstrap_sent",
        "invalid_bound_rejected",
        "group_sigterm",
        "sidecar_reaped",
        "secret_scan_clean",
        "host_completed",
    ],
    "wildcard-v6": [
        "lifecycle_started",
        "sidecar_spawned",
        "bootstrap_sent",
        "invalid_bound_rejected",
        "group_sigterm",
        "sidecar_reaped",
        "secret_scan_clean",
        "host_completed",
    ],
    "never-ready": [
        "lifecycle_started",
        "sidecar_spawned",
        "bootstrap_sent",
        "bound_validated",
        "health_ok",
        "readiness_deadline_enforced",
        "group_sigterm",
        "sidecar_reaped",
        "secret_scan_clean",
        "host_completed",
    ],
    "crash-before-bound": [
        "lifecycle_started",
        "sidecar_spawned",
        "bootstrap_sent",
        "expected_crash_before_bound",
        "crash_group_sigterm",
        "crash_group_clean",
        "secret_scan_clean",
        "host_completed",
    ],
    "crash-after-ready": [
        "lifecycle_started",
        "sidecar_spawned",
        "bootstrap_sent",
        "bound_validated",
        "health_ok",
        "ready_authenticated",
        "expected_crash_after_ready",
        "crash_group_sigterm",
        "crash_group_clean",
        "secret_scan_clean",
        "host_completed",
    ],
    "ignore-shutdown": [
        "lifecycle_started",
        "sidecar_spawned",
        "bootstrap_sent",
        "bound_validated",
        "health_ok",
        "ready_authenticated",
        "shutdown_sent",
        "shutdown_grace_expired",
        "group_sigterm",
        "group_sigkill",
        "sidecar_reaped",
        "secret_scan_clean",
        "host_completed",
    ],
    "parent-crash": [
        "lifecycle_started",
        "sidecar_spawned",
        "bootstrap_sent",
        "bound_validated",
        "health_ok",
        "ready_authenticated",
        "awaiting_parent_sigkill",
    ],
}


def _json_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    if content and not content.endswith("\n"):
        # A live reader may sample after the locked JSON write but before the
        # writer appends its newline. Ignore only that incomplete tail; any
        # malformed newline-terminated record below remains a hard failure.
        lines = lines[:-1]
    records: list[dict[str, Any]] = []
    for line in lines:
        if line.strip():
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError("event record is not an object")
            records.append(item)
    return records


def _wait_for_event(path: Path, event: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if any(item.get("event") == event for item in _json_lines(path)):
                return True
        except (OSError, json.JSONDecodeError, ValueError):
            pass
        time.sleep(POLL_SECONDS)
    return False


def _spawned_pid(records: list[dict[str, Any]]) -> int | None:
    spawned = [item for item in records if item.get("event") == "sidecar_spawned"]
    if len(spawned) != 1:
        return None
    value = spawned[0].get("fields", {}).get("pid")
    return int(value) if isinstance(value, int) and value > 0 else None


def _validate_event_records(
    records: list[dict[str, Any]], scenario: str, run_id: str
) -> tuple[bool, list[str]]:
    names = [str(item.get("event")) for item in records]
    sequences = [item.get("seq") for item in records]
    host_pids = {item.get("host_pid") for item in records}
    structurally_valid = all(
        (
            sequences == list(range(1, len(records) + 1)),
            len(host_pids) == 1,
            None not in host_pids,
            all(item.get("v") == 1 for item in records),
            all(item.get("run_id") == run_id for item in records),
            all(item.get("scenario") == scenario for item in records),
        )
    )
    compared = [name for name in names if name != "duplicate_activation"]
    duplicate_count = names.count("duplicate_activation")
    activation_valid = duplicate_count <= 1 if scenario == "duplicate" else duplicate_count == 0
    return (
        structurally_valid
        and activation_valid
        and compared == EXPECTED_TRACES[scenario],
        names,
    )


def _target_triple() -> str:
    output = subprocess.run(
        ["rustc", "-vV"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout
    for line in output.splitlines():
        if line.startswith("host: "):
            return line.removeprefix("host: ").strip()
    raise RuntimeError("rustc did not report a host target triple")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tracked_source_digest(root: Path = SPIKE_ROOT) -> str:
    digest = hashlib.sha256()
    for relative in SOURCE_FILES:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update((root / relative).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _validate_provenance(
    host: dict[str, Any], fixture: dict[str, Any], source_sha256: str
) -> None:
    for payload, role, tauri_host in (
        (host, "tauri-host", True),
        (fixture, "fixture-sidecar", False),
    ):
        if payload.get("schema_version") != 1:
            raise RuntimeError(f"{role} provenance schema mismatch")
        if payload.get("role") != role or payload.get("tauri_host") is not tauri_host:
            raise RuntimeError(f"{role} provenance identity mismatch")
        if payload.get("source_sha256") != source_sha256:
            raise RuntimeError(f"{role} source provenance mismatch")
        if payload.get("dependencies") != PINNED_DEPENDENCIES:
            raise RuntimeError(f"{role} dependency provenance mismatch")


def _binary_provenance(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [str(path), "--provenance"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0 or result.stderr.strip():
        raise RuntimeError(f"binary provenance command failed: {path.name}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"binary provenance is not JSON: {path.name}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"binary provenance is not an object: {path.name}")
    return payload


def _is_macho(path: Path) -> bool:
    with path.open("rb") as binary:
        return binary.read(4) in MACHO_MAGICS


def _raw_result_digest(root: Path, stdout: bytes, stderr: bytes) -> str:
    digest = hashlib.sha256()
    for label, content in ((b"stdout\0", stdout), (b"stderr\0", stderr)):
        digest.update(label)
        digest.update(content)
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _version(command: list[str]) -> str:
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return (result.stdout or result.stderr).strip()


def _process_rows() -> list[tuple[int, int, str]]:
    output = subprocess.run(
        ["ps", "-axo", "pid=,pgid=,comm="],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout
    rows: list[tuple[int, int, str]] = []
    for line in output.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
            rows.append((int(fields[0]), int(fields[1]), fields[2]))
    return rows


def _secret_process_scan(pids: set[int]) -> bool:
    live = sorted(pid for pid in pids if pid > 0)
    if not live:
        return True
    result = subprocess.run(
        ["ps", "eww", "-p", ",".join(str(pid) for pid in live), "-o", "pid=,command="],
        check=False,
        capture_output=True,
        timeout=5,
    )
    if result.returncode != 0:
        return False
    seen: set[int] = set()
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if fields and fields[0].isdigit():
            seen.add(int(fields[0]))
    return (
        seen == set(live)
        and TOKEN_CANARY not in result.stdout
        and TOKEN_CANARY not in result.stderr
    )


def _load_meta(root: Path) -> dict[str, Any] | None:
    path = root / "listener-meta.json"
    if not path.exists():
        return None
    try:
        item = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return item if isinstance(item, dict) else None


def _observe_live(
    root: Path,
    process: subprocess.Popen[bytes],
    timeout: float,
    allow_pre_group: bool = False,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    observation: dict[str, Any] = {
        "observed": False,
        "same_group_canary": False,
        "process_secret_scan_clean": True,
    }
    while time.monotonic() < deadline and process.poll() is None:
        meta = _load_meta(root)
        if meta:
            pids = {
                process.pid,
                int(meta.get("pid", 0)),
                int(meta.get("canary_pid", 0)),
            }
            rows = _process_rows()
            groups = {pid: pgid for pid, pgid, _ in rows if pid in pids}
            sidecar_pid = int(meta.get("pid", 0))
            canary_pid = int(meta.get("canary_pid", 0))
            observation = {
                "observed": sidecar_pid in groups and canary_pid in groups,
                "same_group_canary": groups.get(sidecar_pid) == sidecar_pid
                and groups.get(canary_pid) == sidecar_pid,
                "process_secret_scan_clean": _secret_process_scan(pids),
            }
            if observation["observed"]:
                return observation
        elif allow_pre_group:
            records = _json_lines(root / "events.ndjson")
            spawned_pid = _spawned_pid(records)
            if spawned_pid:
                pids = {process.pid, spawned_pid}
                rows = _process_rows()
                live_pids = {pid for pid, _, _ in rows if pid in pids}
                observation = {
                    "observed": live_pids == pids,
                    "same_group_canary": False,
                    "process_secret_scan_clean": _secret_process_scan(pids),
                }
                if observation["observed"]:
                    return observation
        time.sleep(POLL_SECONDS)
    return observation


def _listener_audit(port: int) -> dict[str, Any]:
    if not port:
        return {
            "rows": [],
            "completed": True,
            "returncode": None,
            "stderr_sha256": None,
        }
    result = subprocess.run(
        ["/usr/sbin/lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    no_match = result.returncode == 1 and not result.stderr.strip()
    return {
        "rows": [line for line in result.stdout.splitlines()[1:] if line.strip()],
        "completed": result.returncode == 0 or no_match,
        "returncode": result.returncode,
        "stderr_sha256": hashlib.sha256(result.stderr.encode("utf-8")).hexdigest()
        if result.stderr
        else None,
    }


def _connect_refused(port: int) -> bool:
    if not port:
        return True
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.1):
            return False
    except OSError:
        return True


def _post_run_audit(
    meta: dict[str, Any] | None, spawned_pid: int | None = None
) -> dict[str, Any]:
    if meta is None and not spawned_pid:
        return {
            "metadata_present": False,
            "identity_source": None,
            "audit_complete": False,
            "pid_absent": False,
            "executable_identity_absent": False,
            "process_group_empty": False,
            "listener_rows": [],
            "listener_audit_complete": False,
            "connect_refused": False,
            "clean": False,
        }
    pid = int(meta.get("pid", 0)) if meta else int(spawned_pid or 0)
    canary_pid = int(meta.get("canary_pid", 0)) if meta else 0
    pgid = int(meta.get("pgid", 0)) if meta else pid
    port = int(meta.get("port", 0)) if meta else 0
    identity_valid = pid > 0 and pgid > 0
    deadline = time.monotonic() + AUDIT_TIMEOUT_SECONDS
    audit: dict[str, Any] = {}
    while time.monotonic() < deadline:
        rows = _process_rows()
        by_pid = {row_pid: command for row_pid, _, command in rows}
        group_members = [row_pid for row_pid, row_pgid, _ in rows if row_pgid == pgid]
        listener = _listener_audit(port)
        listeners = listener["rows"]
        audited_pids = (pid, canary_pid) if canary_pid > 0 else (pid,)
        audit = {
            "metadata_present": meta is not None,
            "identity_source": "listener-meta" if meta else "sidecar_spawned",
            "audit_complete": identity_valid and bool(listener["completed"]),
            "pid_absent": all(item not in by_pid for item in audited_pids),
            "executable_identity_absent": not any(
                "fixture-sidecar" in by_pid.get(item, "") for item in audited_pids
            ),
            "process_group_empty": not group_members,
            "listener_rows": listeners,
            "listener_audit_complete": listener["completed"],
            "listener_returncode": listener["returncode"],
            "listener_stderr_sha256": listener["stderr_sha256"],
            "connect_refused": _connect_refused(port),
        }
        audit["clean"] = all(
            (
                audit["audit_complete"],
                audit["pid_absent"],
                audit["executable_identity_absent"],
                audit["process_group_empty"],
                not listeners,
                audit["connect_refused"],
            )
        )
        if audit["clean"]:
            return audit
        time.sleep(POLL_SECONDS)
    return audit


def _files_secret_clean(root: Path, stdout: bytes, stderr: bytes) -> bool:
    if TOKEN_CANARY in stdout or TOKEN_CANARY in stderr:
        return False
    for path in root.rglob("*"):
        if path.is_file() and TOKEN_CANARY in path.read_bytes():
            return False
    return True


def _host_env(
    root: Path, run_id: str, scenario: str, barrier: Path | None = None
) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "ARXMCP_SPIKE_DATA_DIR": str(root),
            "ARXMCP_SPIKE_RUN_ID": run_id,
            "ARXMCP_SPIKE_SCENARIO": scenario,
        }
    )
    if barrier is not None:
        env["ARXMCP_SPIKE_LAUNCH_BARRIER"] = str(barrier)
    return env


def _stop_timed_out_host(process: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
    process.kill()
    return process.communicate(timeout=3)


def _run_case(host: Path, scratch: Path, scenario: str, run_id: str) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix=f"{scenario}-", dir=scratch))
    barrier = root / "launch-barrier" if scenario == "duplicate" else None
    started = time.monotonic()
    first_launch_ns = time.monotonic_ns()
    process = subprocess.Popen(
        [str(host)],
        env=_host_env(root, run_id, scenario, barrier),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    first_pid = process.pid
    duplicate: subprocess.Popen[bytes] | None = None
    stdout = b""
    stderr = b""
    duplicate_exit: int | None = None
    launch_evidence: dict[str, Any] | None = None
    timed_out = False
    try:
        if scenario == "duplicate":
            ready_before_second = any(
                item.get("event") == "ready_authenticated"
                for item in _json_lines(root / "events.ndjson")
            )
            second_launch_ns = time.monotonic_ns()
            second = subprocess.Popen(
                [str(host)],
                env=_host_env(root, run_id, scenario, barrier),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            duplicate = second
            if barrier is None:
                raise RuntimeError("duplicate launch barrier missing")
            barrier.write_text("go\n", encoding="utf-8")
            barrier_released_ns = time.monotonic_ns()
            if not _wait_for_event(root / "events.ndjson", "sidecar_spawned", 3.0):
                raise RuntimeError("duplicate race produced no sidecar owner")
            sidecar_observed_ns = time.monotonic_ns()
            early_records = _json_lines(root / "events.ndjson")
            owner = next(
                (
                    int(item.get("host_pid"))
                    for item in early_records
                    if item.get("event") == "sidecar_spawned"
                    and isinstance(item.get("host_pid"), int)
                ),
                0,
            )
            if owner == process.pid:
                loser = second
            elif owner == second.pid:
                loser = process
                process = second
            else:
                raise RuntimeError("duplicate race owner did not match either host")
            duplicate = loser
            duplicate_stdout, duplicate_stderr = duplicate.communicate(timeout=3)
            duplicate_exit = duplicate.returncode
            stdout += duplicate_stdout
            stderr += duplicate_stderr
            launch_evidence = {
                "first_pid": first_pid,
                "second_pid": second.pid,
                "winner_pid": owner,
                "loser_pid": loser.pid,
                "launch_gap_ms": round((second_launch_ns - first_launch_ns) / 1_000_000, 3),
                "ready_before_second_launch": ready_before_second,
                "second_launched_before_sidecar_observed": second_launch_ns
                < sidecar_observed_ns,
                "barrier_released_after_both_launches": barrier_released_ns
                >= second_launch_ns,
                "startup_overlap": not ready_before_second
                and second_launch_ns < sidecar_observed_ns
                and barrier_released_ns >= second_launch_ns,
            }
        live = _observe_live(
            root, process, 2.0, allow_pre_group=scenario == "startup-timeout"
        )
        if scenario == "parent-crash":
            if not _wait_for_event(root / "events.ndjson", "awaiting_parent_sigkill", 3.0):
                raise RuntimeError("parent-crash host did not reach ready sentinel")
            os.kill(process.pid, signal.SIGKILL)
        try:
            host_stdout, host_stderr = process.communicate(timeout=CASE_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            timed_out = True
            host_stdout, host_stderr = _stop_timed_out_host(process)
        stdout += host_stdout
        stderr += host_stderr
        records = _json_lines(root / "events.ndjson")
        trace_valid, ordered_events = _validate_event_records(records, scenario, run_id)
        names = set(ordered_events)
        spawned_pid = _spawned_pid(records)
        meta = _load_meta(root)
        audit = _post_run_audit(meta, spawned_pid)
        secret_clean = live["process_secret_scan_clean"] and _files_secret_clean(
            root, stdout, stderr
        )
        expected_exit = -signal.SIGKILL if scenario == "parent-crash" else 0
        expected = EXPECTED_EVENTS[scenario]
        routed = next(
            (item for item in records if item.get("event") == "duplicate_routed_to_primary"),
            None,
        )
        routed_fields = routed.get("fields", {}) if routed else {}
        arbitration_observed = bool(
            routed
            and (
                int(routed_fields.get("activations", 0)) == 1
                or routed_fields.get("supervisor_lock_contention") is True
            )
        )
        duplicate_valid = scenario != "duplicate" or all(
            (
                duplicate_exit == 0,
                launch_evidence is not None,
                bool(launch_evidence and launch_evidence["startup_overlap"]),
                ordered_events.count("duplicate_activation") <= 1,
                arbitration_observed,
            )
        )
        case_ok = all(
            (
                not timed_out,
                process.returncode == expected_exit,
                expected.issubset(names),
                trace_valid,
                audit["clean"],
                secret_clean,
                live["same_group_canary"]
                if meta is not None
                else scenario == "startup-timeout",
                duplicate_valid,
                spawned_pid is not None,
            )
        )
        return {
            "scenario": scenario,
            "ok": case_ok,
            "host_exit": process.returncode,
            "duplicate_exit": duplicate_exit,
            "duplicate_launch": launch_evidence,
            "duplicate_arbitration": routed_fields if scenario == "duplicate" else None,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            "events": ordered_events,
            "event_trace_valid": trace_valid,
            "expected_events": sorted(expected),
            "live_observation": live,
            "post_run_audit": audit,
            "secret_scan_clean": secret_clean,
            "raw_result_sha256": _raw_result_digest(root, stdout, stderr),
            "raw_stdout_bytes": len(stdout),
            "raw_stderr_bytes": len(stderr),
        }
    except Exception as error:  # evidence must survive an individual fault-case failure
        if duplicate is not None and duplicate.poll() is None:
            duplicate.kill()
            duplicate.communicate(timeout=3)
        if process.poll() is None:
            stdout, stderr = _stop_timed_out_host(process)
        records = _json_lines(root / "events.ndjson")
        meta = _load_meta(root)
        audit = _post_run_audit(meta, _spawned_pid(records))
        return {
            "scenario": scenario,
            "ok": False,
            "host_exit": process.returncode,
            "duplicate_exit": duplicate_exit,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            "error_type": type(error).__name__,
            "post_run_audit": audit,
            "secret_scan_clean": _files_secret_clean(root, stdout, stderr),
            "raw_result_sha256": _raw_result_digest(root, stdout, stderr),
        }
    finally:
        shutil.rmtree(root)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.cycles != 30:
        raise SystemExit("the acceptance gate requires exactly 30 cycles")
    host = args.host.resolve(strict=True)
    fixture = args.fixture.resolve(strict=True)
    source_sha256 = _tracked_source_digest()
    host_provenance = _binary_provenance(host)
    fixture_provenance = _binary_provenance(fixture)
    _validate_provenance(host_provenance, fixture_provenance, source_sha256)
    if not _is_macho(host) or not _is_macho(fixture):
        raise SystemExit("lifecycle evidence requires real Mach-O host and fixture binaries")
    args.scratch.mkdir(parents=True, exist_ok=True)
    triple = _target_triple()
    sidecar = host.parent / f"fixture-sidecar-{triple}"
    if sidecar.exists():
        raise SystemExit(f"refusing to overwrite existing sidecar: {sidecar}")
    shutil.copy2(fixture, sidecar)
    sidecar.chmod(0o755)
    try:
        fault_results = [
            _run_case(host, args.scratch, scenario, f"fault-{index:02d}")
            for index, scenario in enumerate(FAULT_CASES, start=1)
        ]
        cycle_results = [
            _run_case(host, args.scratch, "normal", f"cycle-{index:02d}")
            for index in range(1, args.cycles + 1)
        ]
    finally:
        sidecar.unlink(missing_ok=True)

    all_results = [*fault_results, *cycle_results]
    orphan_count = sum(
        not bool(item.get("post_run_audit", {}).get("process_group_empty"))
        for item in all_results
    )
    listener_count = sum(
        bool(item.get("post_run_audit", {}).get("listener_rows"))
        or not bool(item.get("post_run_audit", {}).get("connect_refused"))
        for item in all_results
    )
    secret_failures = sum(not bool(item.get("secret_scan_clean")) for item in all_results)
    aggregate_digest = hashlib.sha256(
        "".join(str(item["raw_result_sha256"]) for item in all_results).encode("ascii")
    ).hexdigest()
    passed = all(bool(item.get("ok")) for item in all_results)
    passed = passed and orphan_count == 0 and listener_count == 0 and secret_failures == 0
    evidence = {
        "schema_version": 1,
        "milestone": "desktop-distribution-spike-3",
        "decision": "GO" if passed else "NO-GO",
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "rust_target": triple,
            "rustc": _version(["rustc", "-Vv"]),
            "cargo": _version(["cargo", "-V"]),
        },
        "artifacts": {
            "host_sha256": _sha256(host),
            "fixture_sha256": _sha256(fixture),
            "raw_results_sha256": aggregate_digest,
            "source_sha256": source_sha256,
            "host_is_tauri_binary": host_provenance["tauri_host"],
            "sidecar_target_triple_name": sidecar.name,
            "build_provenance": {
                "host": host_provenance,
                "fixture": fixture_provenance,
            },
        },
        "pinned_dependencies": host_provenance["dependencies"],
        "commands": {
            "fault_matrix": "run_spike.py --cycles 30",
            "listener_audit": "/usr/sbin/lsof -nP -iTCP:<port> -sTCP:LISTEN",
            "process_audit": "ps -axo pid=,pgid=,comm=",
            "secret_process_audit": "ps eww -p <pids> -o command=",
        },
        "production_contract": {
            "shutdown_grace_ms": 35_000,
            "fixture_shutdown_grace_ms": 350,
            "bind_host": "127.0.0.1",
            "token_transport": "stdin-only",
            "token_entropy_bits": 256,
        },
        "fault_matrix": fault_results,
        "thirty_cycle_gate": {
            "cycles": cycle_results,
            "completed": len(cycle_results),
            "all_passed": all(bool(item.get("ok")) for item in cycle_results),
        },
        "totals": {
            "orphan_process_groups": orphan_count,
            "residual_listeners": listener_count,
            "secret_scan_failures": secret_failures,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
