"""desktop-distribution-m5 — real desktop-child + supervisor lifecycle tests.

Two speed classes share this file:

- Fast, subprocess-free tests (the AC5 config regression and the AC6
  pure-ASGI ``/readyz`` middleware unit tests) run on every ``make test``.
- Tests marked ``requires_desktop_stack`` boot the REAL server (eager
  BGE-M3/LanceDB warm-up, minutes not milliseconds) and/or the built Tauri
  supervisor binary. They are opt-in via ``pytest -m requires_desktop_stack``
  and are run — with zero skips — by ``make desktop-conformance``. Following
  the ``requires_latexmlc`` precedent, they carry NO secondary skip guard:
  opting in with a missing prerequisite fails loudly.

The supervisor binary path env var is deliberately NOT ``ARXMCP_``-prefixed:
the AC2 test imports ``server.main`` (module-level app construction), whose
unknown-``ARXMCP_*`` scan would otherwise FATAL on the harness knob.
"""

from __future__ import annotations

import asyncio
import http.client
import io
import json
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import BinaryIO

import pytest

from server.desktop_child import (
    COMPONENT,
    ReadyzStartupTokenMiddleware,
    executable_identity,
    read_frame,
)
from server.desktop_contract import (
    FRAME_LIMIT,
    Bound,
    DesktopContractError,
    Launch,
    Shutdown,
    StartupToken,
    canonicalize_frame,
    encode_frame,
    generate_startup_token,
    parse_frame,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "apps" / "desktop" / "contract-fixtures"
SUPERVISOR_BIN_ENV = "DESKTOP_SUPERVISOR_BIN"
CHILD_ARGV = [sys.executable, "-m", "server.desktop_child"]
_HEX64 = re.compile(rb"[0-9a-f]{64}")

_MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "Mcp-Protocol-Version": "2025-06-18",
}


def _golden_launch() -> Launch:
    frame = parse_frame((FIXTURES / "launch-v1.jsonl").read_bytes())
    if not isinstance(frame, Launch):
        raise RuntimeError("launch fixture parsed as the wrong frame type")
    return frame


def _child_env() -> dict[str, str]:
    """Child env: ambient minus ARXMCP_* (mirrors the supervisor's scrub, and
    keeps stray harness vars away from the child's unknown-env FATAL scan),
    plus rerank so the AC1 warm map can honestly be all-true."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("ARXMCP_")}
    env["ARXMCP_ENABLE_RERANK"] = "1"
    return env


def _readline_with_timeout(stream: BinaryIO, timeout: float) -> bytes:
    results: queue.Queue[bytes | BaseException] = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            results.put(stream.readline())
        except BaseException as exc:  # pragma: no cover - process boundary
            results.put(exc)

    threading.Thread(target=read, daemon=True).start()
    try:
        result = results.get(timeout=timeout)
    except queue.Empty as exc:
        raise TimeoutError("desktop child did not announce its endpoint") from exc
    if isinstance(result, BaseException):
        raise result
    return result


def _request(
    port: int,
    path: str,
    token: str | None = None,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> tuple[int, dict[str, str], bytes]:
    merged = dict(headers or {})
    if token is not None:
        merged["X-ArXMCP-Startup-Token"] = token
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request(method, path, body=body, headers=merged)
        response = connection.getresponse()
        return (
            response.status,
            {name.lower(): value for name, value in response.getheaders()},
            response.read(),
        )
    finally:
        connection.close()


def _connect_probe(port: int) -> None:
    """Positive/negative listener probe whose own success is asserted: AC4
    first proves it CONNECTS against the live server, then expects the
    specific ConnectionRefusedError after shutdown — a silently-broken probe
    cannot satisfy both sides."""
    socket.create_connection(("127.0.0.1", port), timeout=2).close()


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _seed_root(base: Path) -> Path:
    from tests._corpus_helpers import seed_corpus

    root = base.resolve()
    (root / "logs").mkdir(parents=True, exist_ok=True)
    seed_corpus(root / "index" / "lancedb", n=2)
    return root


@pytest.fixture(scope="module")
def real_child(tmp_path_factory: pytest.TempPathFactory) -> SimpleNamespace:
    """ONE real desktop-child boot shared by AC1/AC2/AC4 (the warm-up is paid
    once per run, per the research brief's shared-fixture trim)."""
    root = _seed_root(tmp_path_factory.mktemp("desktop-child") / "runtime data 数学")
    token = generate_startup_token()
    identity = executable_identity()
    launch = replace(
        _golden_launch(),
        data_root=root.as_posix(),
        executable=identity,
        log_location=(root / "logs" / "desktop-child.log").as_posix(),
        startup_token=token,
    )
    env = _child_env()
    log_handle = (root / "logs" / "desktop-child.log").open("wb")
    process = subprocess.Popen(
        CHILD_ARGV,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log_handle,
        env=env,
        cwd=str(REPO_ROOT),
    )
    try:
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("desktop child control pipes unavailable")
        process.stdin.write(encode_frame(launch))
        process.stdin.flush()
        # Bound arrives only after the eager warm-up; the m3 lesson says do
        # not use sub-second deadlines on real-server paths.
        bound_bytes = _readline_with_timeout(process.stdout, timeout=240.0)
        bound = parse_frame(bound_bytes)
        if not isinstance(bound, Bound):
            raise RuntimeError("first control frame was not bound")
        yield SimpleNamespace(
            process=process,
            env=env,
            root=root,
            token=token,
            launch=launch,
            bound=bound,
            bound_bytes=bound_bytes,
        )
    finally:
        _stop_process(process)
        log_handle.close()


@pytest.mark.requires_desktop_stack
def test_ac1_real_child_ready_and_console(real_child: SimpleNamespace) -> None:
    """AC1: the production entry point (not the fixture sidecar) reaches
    health/readiness with an all-true warm map and serves the real console."""
    argv = [str(part) for part in real_child.process.args]
    assert argv == CHILD_ARGV
    assert all("fixture-sidecar" not in part for part in argv)
    assert "ARXMCP_FIXTURE_SIDECAR" not in real_child.env

    bound = real_child.bound
    assert bound.endpoint.host == "127.0.0.1"
    assert bound.endpoint.port != 0
    assert bound.executable.component == COMPONENT
    assert bound.data_root == real_child.root.as_posix()
    assert not hasattr(bound, "startup_token")

    port = bound.endpoint.port
    status, _, _ = _request(port, "/healthz")
    assert status == 200
    status, _, _ = _request(port, "/readyz")
    assert status == 401
    status, _, _ = _request(port, "/readyz", token="f" * 64)
    assert status == 401

    # Bound is emitted after lifespan startup, so the FIRST authorized
    # response should already be fully warm; poll only as load headroom.
    deadline = time.monotonic() + 60.0
    while True:
        status, _, body = _request(port, "/readyz", token=real_child.token.expose())
        if status == 200 or time.monotonic() >= deadline:
            break
        time.sleep(2.0)
    assert status == 200
    ready = json.loads(body)
    assert ready["status"] == "ready"
    assert ready["warm"] == {"embedder": True, "lancedb": True, "reranker": True}

    status, _, page = _request(port, "/ui/")
    assert status == 200
    assert b"arXMCP notebooks" in page


@pytest.mark.requires_desktop_stack
def test_ac2_mcp_smoke_live_schema_hash(real_child: SimpleNamespace) -> None:
    """AC2: real initialize + tools/list over the announced endpoint; the
    LIVE response bytes hash to EXPECTED_TOOL_SCHEMA_SHA256 (same function
    the schema pin test uses — a mocked response cannot satisfy this)."""
    from mcp.types import Tool

    from tests.test_server_tool_schema import (
        EXPECTED_TOOL_SCHEMA_SHA256,
        compute_tool_schema_hash,
    )

    port = real_child.bound.endpoint.port
    initialize = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "desktop-conformance", "version": "1.0"},
        },
    }
    status, headers, body = _request(
        port,
        "/mcp/",
        method="POST",
        body=json.dumps(initialize).encode(),
        headers=_MCP_HEADERS,
    )
    assert status == 200, body[:300]
    session = headers["mcp-session-id"]
    session_headers = {**_MCP_HEADERS, "Mcp-Session-Id": session}
    status, _, _ = _request(
        port,
        "/mcp/",
        method="POST",
        body=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode(),
        headers=session_headers,
    )
    assert status in (200, 202, 204)

    status, _, live_bytes = _request(
        port,
        "/mcp/",
        method="POST",
        body=json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        ).encode(),
        headers=session_headers,
    )
    assert status == 200, live_bytes[:300]
    payload = json.loads(live_bytes)
    assert "error" not in payload
    wire_tools = payload["result"]["tools"]
    assert wire_tools, "tools/list served zero tools"
    live_hash = compute_tool_schema_hash(
        [Tool.model_validate(tool) for tool in wire_tools]
    )
    assert live_hash == EXPECTED_TOOL_SCHEMA_SHA256


@pytest.mark.requires_desktop_stack
def test_ac3_zero_delay_race_single_spawn(tmp_path: Path) -> None:
    """AC3: two supervisors released from a shared barrier with no delay —
    exactly one spawn event across both processes; the loser exits 0."""
    supervisor = os.environ.get(SUPERVISOR_BIN_ENV)
    if not supervisor or not Path(supervisor).is_file():
        pytest.fail(
            f"{SUPERVISOR_BIN_ENV} must point at the built supervisor binary "
            f"(run via `make desktop-conformance`)"
        )
    root = _seed_root(tmp_path / "race root 数学")
    identity = executable_identity()
    plan = {
        "child_argv": CHILD_ARGV,
        "component": identity.component,
        "data_root": root.as_posix(),
        "identity_file": str(REPO_ROOT / "server" / "desktop_child.py"),
        "smoke": True,
        "version": identity.version,
    }
    plan_path = root / "launch-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    barrier = root / "launch-barrier"
    env = {k: v for k, v in os.environ.items() if not k.startswith("ARXMCP_")}
    env["ARXMCP_DESKTOP_LAUNCH_PLAN"] = str(plan_path)
    env["ARXMCP_DESKTOP_LAUNCH_BARRIER"] = str(barrier)

    def spawn() -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            [supervisor],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=str(REPO_ROOT),
        )

    first = spawn()
    second = spawn()
    try:
        # Both supervisors are now holding at the barrier; releasing it is
        # the zero-delay simultaneous start (Spike-3 technique).
        barrier.write_text("go\n", encoding="utf-8")
        first_code = first.wait(timeout=300)
        second_code = second.wait(timeout=300)
    finally:
        _stop_process(first)
        _stop_process(second)

    errors = (
        first.stderr.read() if first.stderr else b"",
        second.stderr.read() if second.stderr else b"",
    )
    assert first_code == 0 and second_code == 0, errors

    events = [
        json.loads(line)
        for line in (root / "logs" / "supervisor-events.ndjson")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    def by_name(name: str) -> list[dict]:
        return [event for event in events if event["event"] == name]

    assert len(by_name("child-spawn")) == 1, events
    assert len(by_name("lock-contended")) == 1, events
    assert len(by_name("supervisor-started")) == 1, events
    assert by_name("mcp-smoke-ok"), events
    assert by_name("window-ready"), events
    assert [event["fields"]["child_exit"] for event in by_name("shutdown-clean")] == [0]

    # The winner's capability is unknown to this test, so scan structurally:
    # any 64-hex string in a supervisor/child-written artifact must be the
    # known identity digest — a leaked 256-bit token cannot satisfy that.
    allowed = {identity.sha256.encode("ascii")}
    for artifact in root.rglob("*"):
        if not artifact.is_file() or "index" in artifact.relative_to(root).parts:
            continue
        for match in set(_HEX64.findall(artifact.read_bytes())):
            assert match in allowed, (artifact, match[:12])


@pytest.mark.requires_desktop_stack
def test_ac4_normal_shutdown_leaves_nothing(real_child: SimpleNamespace) -> None:
    """AC4 (m5 slice — normal path only): bounded cleanup leaves no child
    process and no residual listener; probes assert their own success.
    Runs LAST among the shared-fixture tests because it stops the child."""
    process = real_child.process
    port = real_child.bound.endpoint.port
    launch = real_child.launch
    _connect_probe(port)  # probe self-check: must SUCCEED against the live server

    invalid = Shutdown(
        contract=launch.contract,
        extensions={},
        kind="shutdown",
        startup_token=StartupToken.parse("f" * 64),
    )
    process.stdin.write(encode_frame(invalid))
    process.stdin.flush()
    time.sleep(0.2)
    assert process.poll() is None, "invalid shutdown must not stop the server"

    process.stdin.write(
        encode_frame(
            Shutdown(
                contract=launch.contract,
                extensions={},
                kind="shutdown",
                startup_token=real_child.token,
            )
        )
    )
    process.stdin.flush()
    assert process.wait(timeout=45) == 0

    with pytest.raises(ConnectionRefusedError):
        _connect_probe(port)

    remainder = process.stdout.read()
    assert remainder == b"", "child stdout is control-only: one bound frame, ever"

    secret = real_child.token.expose().encode()
    assert secret not in real_child.bound_bytes + remainder
    assert all(secret not in str(part).encode() for part in process.args)
    assert all(real_child.token.expose() not in value for value in real_child.env.values())
    assert all(
        real_child.token.expose() not in url
        for url in (
            real_child.bound.health_url,
            real_child.bound.readiness_url,
            real_child.bound.mcp_url,
            real_child.bound.ui_url,
        )
    )
    for artifact in real_child.root.rglob("*"):
        if artifact.is_file():
            assert secret not in artifact.read_bytes(), artifact


def test_ac5_port_zero_still_rejected_by_config() -> None:
    """AC5: `Config.validate_port_range` still rejects 0/privileged/overflow —
    the desktop ephemeral bind lives entirely outside Config."""
    import pydantic

    from server.config import Config

    for port in (0, 80, 65536):
        with pytest.raises(pydantic.ValidationError):
            Config(bind_port=port)


def _code_identifiers(path: Path) -> set[str]:
    """All identifiers the module's CODE references (docstrings excluded, so
    prose mentioning a banned name cannot mask — or fake — a violation)."""
    import ast

    identifiers: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            identifiers.add(node.arg)
        elif isinstance(
            node, ast.alias | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
        ):
            identifiers.add(node.name)
        elif isinstance(node, ast.arg):
            identifiers.add(node.arg)
    return identifiers


def test_ac5_desktop_child_never_touches_config_bind_port() -> None:
    identifiers = _code_identifiers(REPO_ROOT / "server" / "desktop_child.py")
    assert "bind_port" not in identifiers, (
        "desktop child must pre-bind outside Config, never via bind_port"
    )
    config_source = (REPO_ROOT / "server" / "config.py").read_text(encoding="utf-8")
    assert "if not 1024 <= v <= 65535:" in config_source, (
        "validate_port_range guard changed — AC5 forbids widening it"
    )


class _RecordingApp:
    """Inner ASGI app standing in for create_app's result."""

    def __init__(self) -> None:
        self.paths: list[str] = []

    async def __call__(self, scope: dict, receive, send) -> None:
        self.paths.append(scope.get("path", scope["type"]))
        if scope["type"] != "http":
            return
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"inner", "more_body": False})


def _asgi_get(app, path: str, headers: list[tuple[bytes, bytes]]):
    async def drive():
        messages: list[dict] = []

        async def receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict) -> None:
            messages.append(message)

        scope = {"type": "http", "method": "GET", "path": path, "headers": headers}
        await app(scope, receive, send)
        return messages

    return asyncio.run(drive())


class TestReadyzStartupTokenMiddleware:
    """AC6: pure-ASGI capability gate, scoped to the desktop-child path only
    (a BaseHTTPMiddleware shortcut or a create_app registration would break
    the 11 existing unauthenticated /readyz callers)."""

    def _wrapped(self) -> tuple[ReadyzStartupTokenMiddleware, _RecordingApp, StartupToken]:
        token = generate_startup_token()
        inner = _RecordingApp()
        return ReadyzStartupTokenMiddleware(inner, expected_token=token), inner, token

    def test_readyz_without_token_is_401_and_never_reaches_inner(self) -> None:
        app, inner, _ = self._wrapped()
        messages = _asgi_get(app, "/readyz", [])
        assert messages[0]["status"] == 401
        assert inner.paths == []

    def test_readyz_with_wrong_or_malformed_token_is_401(self) -> None:
        app, inner, _ = self._wrapped()
        for supplied in (b"f" * 64, b"not-a-token", b"\xff\xfe"):
            messages = _asgi_get(app, "/readyz", [(b"x-arxmcp-startup-token", supplied)])
            assert messages[0]["status"] == 401
        assert inner.paths == []

    def test_readyz_with_correct_token_passes_through(self) -> None:
        app, inner, token = self._wrapped()
        messages = _asgi_get(
            app,
            "/readyz",
            [(b"x-arxmcp-startup-token", token.expose().encode("ascii"))],
        )
        assert messages[0]["status"] == 200
        assert inner.paths == ["/readyz"]

    def test_other_paths_and_non_http_scopes_are_untouched(self) -> None:
        app, inner, _ = self._wrapped()
        for path in ("/healthz", "/mcp", "/ui/"):
            messages = _asgi_get(app, path, [])
            assert messages[0]["status"] == 200
        assert inner.paths == ["/healthz", "/mcp", "/ui/"]

        async def lifespan_passthrough() -> None:
            async def receive() -> dict:
                return {"type": "lifespan.startup"}

            async def send(_message: dict) -> None:
                raise AssertionError("middleware must not answer lifespan scopes")

            await app({"type": "lifespan"}, receive, send)

        asyncio.run(lifespan_passthrough())
        assert inner.paths[-1] == "lifespan"

    def test_middleware_is_desktop_scoped_not_shared(self) -> None:
        main_source = (REPO_ROOT / "server" / "main.py").read_text(encoding="utf-8")
        assert "ReadyzStartupTokenMiddleware" not in main_source
        child_identifiers = _code_identifiers(REPO_ROOT / "server" / "desktop_child.py")
        assert "BaseHTTPMiddleware" not in child_identifiers
        assert "add_middleware" not in child_identifiers


def test_read_frame_matches_rust_reader_semantics() -> None:
    assert read_frame(io.BytesIO(b"")) is None
    assert read_frame(io.BytesIO(b'{"a":1}\n')) == b'{"a":1}\n'
    with pytest.raises(DesktopContractError, match="4096"):
        read_frame(io.BytesIO(b"x" * (FRAME_LIMIT + 1) + b"\n"))


def test_executable_identity_is_wire_valid_and_self_measured() -> None:
    import hashlib

    identity = executable_identity()
    assert identity.component == "arxmcp-server-desktop-child"
    assert identity.sha256 == hashlib.sha256(
        (REPO_ROOT / "server" / "desktop_child.py").read_bytes()
    ).hexdigest()
    launch = replace(_golden_launch(), executable=identity)
    # encode_frame round-trips only wire-valid identities.
    assert canonicalize_frame(encode_frame(launch)) == encode_frame(launch)
