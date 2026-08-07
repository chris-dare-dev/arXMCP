"""Cross-language conformance and model-free desktop sidecar lifecycle tests."""

from __future__ import annotations

import hashlib
import http.client
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import BinaryIO

import pytest

from server.desktop_contract import (
    Bound,
    ChildControlState,
    DesktopContractError,
    DuplicateKeyError,
    Endpoint,
    Launch,
    Shutdown,
    StartupToken,
    UnsupportedMajorError,
    canonicalize_frame,
    encode_frame,
    generate_startup_token,
    parse_frame,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DESKTOP_ROOT = REPO_ROOT / "apps" / "desktop"
FIXTURES = DESKTOP_ROOT / "contract-fixtures"
POSITIVE_FIXTURES = (
    "launch-v1.jsonl",
    "bound-v1.jsonl",
    "shutdown-v1.jsonl",
    "launch-v1-minor-compatible.jsonl",
)
NEGATIVE_FIXTURES = (
    "duplicate-core-field.jsonl",
    "unknown-core-field.jsonl",
    "wildcard-bound.jsonl",
    "mismatched-url-bound.jsonl",
    "oversized-frame.jsonl",
)
FIXTURE_ONLY_TOKEN = "0" * 64


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _sidecar_binary() -> Path | None:
    configured = os.environ.get("ARXMCP_FIXTURE_SIDECAR")
    if configured:
        candidate = Path(configured).resolve()
    else:
        executable = "fixture-sidecar.exe" if sys.platform == "win32" else "fixture-sidecar"
        candidate = DESKTOP_ROOT / "target" / "debug" / executable
    return candidate if candidate.is_file() else None


def _readline_with_timeout(stream: BinaryIO, timeout: float = 5.0) -> bytes:
    results: queue.Queue[bytes | BaseException] = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            results.put(stream.readline())
        except BaseException as exc:  # pragma: no cover - defensive process boundary
            results.put(exc)

    threading.Thread(target=read, daemon=True).start()
    try:
        result = results.get(timeout=timeout)
    except queue.Empty as exc:
        raise TimeoutError("fixture sidecar did not announce its endpoint") from exc
    if isinstance(result, BaseException):
        raise result
    return result


def _runtime_launch(root: Path, binary: Path, token: StartupToken) -> Launch:
    golden = parse_frame(_fixture("launch-v1.jsonl"))
    if not isinstance(golden, Launch):
        raise RuntimeError("launch fixture parsed as the wrong frame type")
    executable = replace(
        golden.executable,
        sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
    )
    return replace(
        golden,
        data_root=root,
        executable=executable,
        log_location=root / "logs" / "fixture-sidecar.log",
        startup_token=token,
    )


def _request(port: int, path: str, token: str | None = None) -> tuple[int, bytes]:
    headers = {} if token is None else {"X-ArXMCP-Startup-Token": token}
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _spawn_sidecar(
    binary: Path, launch: Launch, log_handle: BinaryIO
) -> tuple[subprocess.Popen[bytes], dict[str, str]]:
    child_env = {
        key: value
        for key, value in os.environ.items()
        if key in {"SYSTEMROOT", "WINDIR", "TMP", "TEMP"}
    }
    process = subprocess.Popen(
        [str(binary)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_handle,
        env=child_env,
    )
    if process.stdin is None or process.stdout is None:
        process.kill()
        process.wait(timeout=2)
        raise RuntimeError("fixture sidecar control pipes unavailable")
    process.stdin.write(encode_frame(launch))
    process.stdin.flush()
    return process, child_env


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def test_positive_fixtures_round_trip_byte_for_byte() -> None:
    for name in POSITIVE_FIXTURES:
        original = _fixture(name)
        assert canonicalize_frame(original) == original, name


def test_compatible_minor_preserves_namespaced_additions() -> None:
    frame = parse_frame(_fixture("launch-v1-minor-compatible.jsonl"))
    assert isinstance(frame, Launch)
    assert frame.contract.minor == 9
    assert frame.extensions["org.arxmcp.future"]["nested"] == {
        "a": ["β", 2],
        "z": 1,
    }


def test_incompatible_major_is_rejected_before_missing_fields() -> None:
    with pytest.raises(UnsupportedMajorError, match="major 2"):
        parse_frame(_fixture("incompatible-major.jsonl"))


@pytest.mark.parametrize("name", NEGATIVE_FIXTURES)
def test_negative_contract_fixtures_are_rejected(name: str) -> None:
    with pytest.raises(DesktopContractError):
        parse_frame(_fixture(name))


def test_duplicate_nested_keys_and_unknown_core_fields_are_rejected() -> None:
    duplicate = (
        b'{"contract":{"major":1,"major":1,"minor":0},"kind":"shutdown",'
        b'"extensions":{},"startup_token":"' + FIXTURE_ONLY_TOKEN.encode() + b'"}\n'
    )
    with pytest.raises(DuplicateKeyError):
        parse_frame(duplicate)

    unknown = _fixture("launch-v1.jsonl").replace(b'"extensions":{}', b'"extra":1,"extensions":{}')
    with pytest.raises(DesktopContractError, match="malformed launch"):
        parse_frame(unknown)


@pytest.mark.parametrize(
    "frame",
    [
        b"{}",
        b"{}\r\n",
        b'{"contract":{"major":1,"minor":0.0}}\n',
        b'{"contract":{"major":1,"minor":9007199254740992}}\n',
    ],
)
def test_framing_and_canonical_number_subset(frame: bytes) -> None:
    with pytest.raises(DesktopContractError):
        parse_frame(frame)


def test_wildcards_zero_ports_url_mismatch_and_path_escape_are_rejected() -> None:
    bound_data = _fixture("bound-v1.jsonl")
    for invalid in (
        bound_data.replace(b'"host":"127.0.0.1"', b'"host":"::"', 1),
        bound_data.replace(b'"port":43127', b'"port":0', 1),
        bound_data.replace(
            b'"log_location":"/opt/arXMCP fixture/\xe6\x95\xb0\xe5\xad\xa6/logs/desktop.log"',
            b'"log_location":"/opt/outside.log"',
        ),
    ):
        with pytest.raises(DesktopContractError):
            parse_frame(invalid)


def test_capabilities_use_256_random_bits_and_never_enter_repr_or_errors() -> None:
    token = generate_startup_token()
    second = generate_startup_token()
    assert len(token.expose()) == 64
    assert token != second
    assert token.expose() not in repr(token)

    launch = parse_frame(_fixture("launch-v1.jsonl"))
    shutdown = parse_frame(_fixture("shutdown-v1.jsonl"))
    assert FIXTURE_ONLY_TOKEN not in repr(launch)
    assert FIXTURE_ONLY_TOKEN not in repr(shutdown)

    canary = "f" * 64
    malformed = _fixture("launch-v1.jsonl").replace(
        FIXTURE_ONLY_TOKEN.encode(), canary.encode()
    ).replace(b'"extensions":{}', b'"unknown":true,"extensions":{}')
    with pytest.raises(DesktopContractError) as raised:
        parse_frame(malformed)
    assert canary not in str(raised.value)
    assert canary not in repr(raised.value)


def test_child_control_state_rejects_sequence_violations() -> None:
    launch = parse_frame(_fixture("launch-v1.jsonl"))
    bound = parse_frame(_fixture("bound-v1.jsonl"))
    shutdown = parse_frame(_fixture("shutdown-v1.jsonl"))
    state = ChildControlState()
    with pytest.raises(DesktopContractError, match="sequence"):
        state.accept(bound)
    state.accept(launch)
    assert state.phase == "running"
    with pytest.raises(DesktopContractError, match="sequence"):
        state.accept(launch)
    state.accept(shutdown)
    assert state.phase == "stopped"


def test_fixture_set_has_pinned_aggregate_digest() -> None:
    digest = hashlib.sha256()
    for path in sorted(FIXTURES.glob("*.jsonl"), key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    expected = (FIXTURES / "fixtures.sha256").read_text(encoding="utf-8").strip()
    assert digest.hexdigest() == expected


def test_fixture_token_is_explicitly_nonsecret_test_data() -> None:
    launch = parse_frame(_fixture("launch-v1.jsonl"))
    shutdown = parse_frame(_fixture("shutdown-v1.jsonl"))
    assert isinstance(launch, Launch)
    assert isinstance(shutdown, Shutdown)
    assert launch.startup_token.expose() == FIXTURE_ONLY_TOKEN
    assert shutdown.startup_token.expose() == FIXTURE_ONLY_TOKEN


@pytest.mark.parametrize("stop_mode", ["authenticated-shutdown", "stdin-eof"])
def test_fixture_sidecar_is_model_free_token_safe_and_bounded(
    tmp_path: Path, stop_mode: str
) -> None:
    binary = _sidecar_binary()
    if binary is None:
        pytest.skip("build fixture-sidecar or set ARXMCP_FIXTURE_SIDECAR")

    root = (tmp_path / "runtime data 数学").resolve()
    logs = root / "logs"
    logs.mkdir(parents=True)
    log_path = logs / "fixture-sidecar.log"
    token = generate_startup_token()
    launch = _runtime_launch(root, binary, token)

    with log_path.open("wb") as log_handle:
        process, child_env = _spawn_sidecar(binary, launch, log_handle)
        try:
            if process.stdout is None or process.stdin is None:
                raise RuntimeError("fixture sidecar control pipes unavailable")
            bound_bytes = _readline_with_timeout(process.stdout)
            bound = parse_frame(bound_bytes)
            assert isinstance(bound, Bound)
            assert bound.endpoint == Endpoint("127.0.0.1", bound.endpoint.port)
            assert bound.endpoint.port != 0
            assert bound.data_root == root
            assert bound.executable.sha256 == launch.executable.sha256
            assert not hasattr(bound, "startup_token")

            status, _ = _request(bound.endpoint.port, "/healthz")
            assert status == 200
            status, _ = _request(bound.endpoint.port, "/readyz")
            assert status == 401
            status, _ = _request(bound.endpoint.port, "/readyz", "f" * 64)
            assert status == 401
            status, body = _request(
                bound.endpoint.port, "/readyz", token.expose()
            )
            assert status == 200
            assert body == b'{"status":"ready"}'

            bad_shutdown = Shutdown(
                contract=launch.contract,
                extensions={},
                kind="shutdown",
                startup_token=StartupToken.parse("f" * 64),
            )
            process.stdin.write(encode_frame(bad_shutdown))
            process.stdin.flush()
            time.sleep(0.05)
            assert process.poll() is None

            if stop_mode == "authenticated-shutdown":
                process.stdin.write(
                    encode_frame(
                        Shutdown(
                            contract=launch.contract,
                            extensions={},
                            kind="shutdown",
                            startup_token=token,
                        )
                    )
                )
                process.stdin.flush()
            else:
                process.stdin.close()
            assert process.wait(timeout=3) == 0

            secret = token.expose().encode()
            remainder = process.stdout.read()
            assert remainder == b""
            assert secret not in bound_bytes + remainder
            assert secret not in "\0".join(process.args).encode()
            assert all(token.expose() not in value for value in child_env.values())
            assert all(token.expose() not in url for url in (
                bound.health_url,
                bound.readiness_url,
                bound.mcp_url,
                bound.ui_url,
            ))
        finally:
            _stop_process(process)

    secret = token.expose().encode()
    for artifact in root.rglob("*"):
        if artifact.is_file():
            assert secret not in artifact.read_bytes(), artifact
    sidecar_manifest = (
        DESKTOP_ROOT / "crates" / "fixture-sidecar" / "Cargo.toml"
    ).read_text(encoding="utf-8")
    assert "torch" not in sidecar_manifest
    assert "transformers" not in sidecar_manifest
    assert "lancedb" not in sidecar_manifest


def test_fixture_sidecar_rejects_invalid_launch_before_binding(tmp_path: Path) -> None:
    binary = _sidecar_binary()
    if binary is None:
        pytest.skip("build fixture-sidecar or set ARXMCP_FIXTURE_SIDECAR")
    root = (tmp_path / "rejected runtime").resolve()
    (root / "logs").mkdir(parents=True)
    token = generate_startup_token()
    launch = _runtime_launch(root, binary, token)
    invalid_token = "A" + token.expose()[1:]
    invalid = encode_frame(launch).replace(
        token.expose().encode(), invalid_token.encode()
    )
    completed = subprocess.run(
        [str(binary)],
        input=invalid,
        capture_output=True,
        check=False,
        env={},
        timeout=2,
    )
    assert completed.returncode == 2
    assert completed.stdout == b""
    assert token.expose().encode() not in completed.stderr
    assert not any(path.is_file() for path in root.rglob("*"))


def test_fixture_sidecar_refuses_command_line_configuration() -> None:
    binary = _sidecar_binary()
    if binary is None:
        pytest.skip("build fixture-sidecar or set ARXMCP_FIXTURE_SIDECAR")
    completed = subprocess.run(
        [str(binary), "--port=0"],
        capture_output=True,
        check=False,
        env={},
        timeout=2,
    )
    assert completed.returncode == 2
    assert completed.stdout == b""
    assert completed.stderr == b"fixture-sidecar: fixture sidecar accepts no arguments\n"
