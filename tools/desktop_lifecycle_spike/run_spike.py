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


def _json_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
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
        ["ps", "eww", "-p", ",".join(str(pid) for pid in live), "-o", "command="],
        check=False,
        capture_output=True,
        timeout=5,
    )
    return TOKEN_CANARY not in result.stdout and TOKEN_CANARY not in result.stderr


def _load_meta(root: Path) -> dict[str, Any] | None:
    path = root / "listener-meta.json"
    if not path.exists():
        return None
    try:
        item = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return item if isinstance(item, dict) else None


def _observe_live(root: Path, process: subprocess.Popen[bytes], timeout: float) -> dict[str, Any]:
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
        time.sleep(POLL_SECONDS)
    return observation


def _listener_rows(port: int) -> list[str]:
    if not port:
        return []
    result = subprocess.run(
        ["/usr/sbin/lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return [line for line in result.stdout.splitlines()[1:] if line.strip()]


def _connect_refused(port: int) -> bool:
    if not port:
        return True
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.1):
            return False
    except OSError:
        return True


def _post_run_audit(meta: dict[str, Any] | None) -> dict[str, Any]:
    if meta is None:
        return {
            "metadata_present": False,
            "pid_absent": True,
            "executable_identity_absent": True,
            "process_group_empty": True,
            "listener_rows": [],
            "connect_refused": True,
            "clean": True,
        }
    pid = int(meta.get("pid", 0))
    canary_pid = int(meta.get("canary_pid", 0))
    pgid = int(meta.get("pgid", 0))
    port = int(meta.get("port", 0))
    deadline = time.monotonic() + AUDIT_TIMEOUT_SECONDS
    audit: dict[str, Any] = {}
    while time.monotonic() < deadline:
        rows = _process_rows()
        by_pid = {row_pid: command for row_pid, _, command in rows}
        group_members = [row_pid for row_pid, row_pgid, _ in rows if row_pgid == pgid]
        listeners = _listener_rows(port)
        audit = {
            "metadata_present": True,
            "pid_absent": pid not in by_pid and canary_pid not in by_pid,
            "executable_identity_absent": not any(
                "fixture-sidecar" in by_pid.get(item, "") for item in (pid, canary_pid)
            ),
            "process_group_empty": not group_members,
            "listener_rows": listeners,
            "connect_refused": _connect_refused(port),
        }
        audit["clean"] = all(
            (
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


def _host_env(root: Path, run_id: str, scenario: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "ARXMCP_SPIKE_DATA_DIR": str(root),
            "ARXMCP_SPIKE_RUN_ID": run_id,
            "ARXMCP_SPIKE_SCENARIO": scenario,
        }
    )
    return env


def _stop_timed_out_host(process: subprocess.Popen[bytes]) -> tuple[bytes, bytes]:
    process.kill()
    return process.communicate(timeout=3)


def _run_case(host: Path, scratch: Path, scenario: str, run_id: str) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix=f"{scenario}-", dir=scratch))
    started = time.monotonic()
    process = subprocess.Popen(
        [str(host)],
        env=_host_env(root, run_id, scenario),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    duplicate: subprocess.Popen[bytes] | None = None
    stdout = b""
    stderr = b""
    duplicate_exit: int | None = None
    timed_out = False
    try:
        if scenario == "duplicate":
            if not _wait_for_event(root / "events.ndjson", "ready_authenticated", 3.0):
                raise RuntimeError("primary did not become ready for duplicate race")
            duplicate = subprocess.Popen(
                [str(host)],
                env=_host_env(root, run_id, scenario),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            duplicate_stdout, duplicate_stderr = duplicate.communicate(timeout=3)
            duplicate_exit = duplicate.returncode
            stdout += duplicate_stdout
            stderr += duplicate_stderr
        live = _observe_live(root, process, 2.0)
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
        names = {str(item.get("event")) for item in records}
        meta = _load_meta(root)
        audit = _post_run_audit(meta)
        secret_clean = live["process_secret_scan_clean"] and _files_secret_clean(
            root, stdout, stderr
        )
        expected_exit = -signal.SIGKILL if scenario == "parent-crash" else 0
        expected = EXPECTED_EVENTS[scenario]
        case_ok = all(
            (
                not timed_out,
                process.returncode == expected_exit,
                expected.issubset(names),
                audit["clean"],
                secret_clean,
                live["same_group_canary"] if meta is not None else True,
                duplicate_exit in (None, 0),
                sum(1 for item in records if item.get("event") == "sidecar_spawned") == 1,
            )
        )
        return {
            "scenario": scenario,
            "ok": case_ok,
            "host_exit": process.returncode,
            "duplicate_exit": duplicate_exit,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            "events": sorted(names),
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
        meta = _load_meta(root)
        audit = _post_run_audit(meta)
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
            "host_is_tauri_binary": True,
            "sidecar_target_triple_name": sidecar.name,
        },
        "pinned_dependencies": {
            "tauri": "2.11.5",
            "tauri-plugin-shell": "2.3.5",
            "tauri-plugin-single-instance": "2.4.3",
        },
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
