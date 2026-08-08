"""Desktop-child entry point: ``python -m server.desktop_child``.

Speaks the M3 ``launch``/``bound``/``shutdown`` control protocol over stdio
for the Tauri supervisor. The child binds ``127.0.0.1:0`` OUTSIDE
:class:`server.config.Config` (``validate_port_range`` is untouched; the
validated ``bind_port`` default is simply unused here), hands the live
socket to a hand-driven uvicorn server, and emits the single token-free
``bound`` frame only after uvicorn reports started — which is strictly
after BOTH the socket is listening AND the FastAPI lifespan's eager
BGE-M3/LanceDB warm-up completed (uvicorn ``startup()`` runs
``lifespan.startup()`` before wrapping the socket).

The startup capability is accepted only from the private stdin ``launch``
frame and compared on ``/readyz`` via constant-time
:func:`server.desktop_contract.tokens_equal`. It never becomes a ``Config``
field, an ``ARXMCP_*`` env var, an argv element, a URL component, or a log
line. Not a second config surface: every server knob still comes from the
environment per ``server/cli.py``; this module adds only the wire protocol.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import socket
import sys
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import BinaryIO

from server.desktop_contract import (
    FRAME_LIMIT,
    HEALTH_PATH,
    MCP_PATH,
    READINESS_PATH,
    UI_PATH,
    Bound,
    DesktopContractError,
    Endpoint,
    ExecutableIdentity,
    Launch,
    Shutdown,
    StartupToken,
    encode_frame,
    parse_frame,
    tokens_equal,
)
from server.middleware import _get_header, _send_json_error

logger = logging.getLogger(__name__)

#: Distinct from ``arxmcp-server``: the supervisor's launch frame names this
#: component so the fixture sidecar and the production child can never be
#: confused for one another.
COMPONENT = "arxmcp-server-desktop-child"


def read_frame(stream: BinaryIO) -> bytes | None:
    """Read one bounded LF-terminated control frame; ``None`` on EOF.

    Mirrors the Rust ``read_frame`` byte-for-byte semantics:
    ``readline(FRAME_LIMIT + 1)`` caps total bytes exactly like the Rust
    reader's ``take()``, so an oversized line surfaces as a contract error
    rather than an unbounded read.
    """
    chunk = stream.readline(FRAME_LIMIT + 1)
    if not chunk:
        return None
    if len(chunk) > FRAME_LIMIT:
        raise DesktopContractError("control frame exceeds 4096 bytes")
    return chunk


def _component_version() -> str:
    """Wire-safe installed-distribution version (no spaces/slashes)."""
    try:
        from importlib.metadata import version

        return version("arxmcp")
    except Exception:
        return "0+unknown"


def executable_identity() -> ExecutableIdentity:
    """Self-measured identity the child compares against the launch frame.

    A Python child has no single compiled artifact, so the closest analogue
    to the fixture sidecar's hash-your-own-binary rule is a digest of THIS
    module's source. Known limitation: the digest does not cover imported
    dependencies the way a compiled binary's hash would.
    """
    digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return ExecutableIdentity(
        component=COMPONENT, sha256=digest, version=_component_version()
    )


class ReadyzStartupTokenMiddleware:
    """Pure-ASGI capability gate on ``GET /readyz`` (desktop child only).

    Constructed EXCLUSIVELY by this module's boot path as a plain object
    wrapper around the ``create_app`` result — never registered inside
    ``server.main.create_app`` — so Docker, ``make up``, and every existing
    ``/readyz`` caller are structurally unreachable from it.
    ``BaseHTTPMiddleware`` is project-banned (E06_S01 F1); this follows the
    ``OriginValidationMiddleware`` pure-ASGI skeleton.
    """

    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        expected_token: StartupToken,
    ) -> None:
        self.app = app
        self._expected_token = expected_token

    async def __call__(
        self, scope: dict, receive: Callable, send: Callable
    ) -> None:
        if scope["type"] != "http" or scope.get("path") != READINESS_PATH:
            await self.app(scope, receive, send)
            return
        headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        supplied = _get_header(headers, b"x-arxmcp-startup-token")
        if supplied is None or not self._matches(supplied):
            await _send_json_error(
                send, status=401, body={"error": "unauthorized"}
            )
            return
        await self.app(scope, receive, send)

    def _matches(self, raw: bytes) -> bool:
        try:
            candidate = StartupToken.parse(raw.decode("ascii"))
        except (UnicodeDecodeError, DesktopContractError):
            return False
        return tokens_equal(candidate, self._expected_token)


def _validate_launch(launch: Launch, identity: ExecutableIdentity) -> None:
    """Reject a launch naming a different executable or an unreal data root.

    Mirrors the fixture sidecar: identity mismatch and non-canonical /
    unprepared roots fail BEFORE any socket is bound.
    """
    if (
        launch.executable.component != identity.component
        or launch.executable.version != identity.version
        or not hmac.compare_digest(launch.executable.sha256, identity.sha256)
    ):
        raise DesktopContractError("executable identity mismatch")
    root = Path(launch.data_root)
    log_parent = Path(launch.log_location).parent
    try:
        canonical_root = root.resolve(strict=True)
        canonical_log_parent = log_parent.resolve(strict=True)
    except OSError as exc:
        raise DesktopContractError("data root is not prepared") from exc
    if canonical_root != root or not canonical_log_parent.is_relative_to(
        canonical_root
    ):
        raise DesktopContractError("data root is not prepared")


def _make_bound(
    launch: Launch, port: int, identity: ExecutableIdentity
) -> Bound:
    authority = f"http://127.0.0.1:{port}"
    return Bound(
        contract=launch.contract,
        data_root=launch.data_root,
        endpoint=Endpoint(host="127.0.0.1", port=port),
        executable=identity,
        extensions={},
        health_url=f"{authority}{HEALTH_PATH}",
        kind="bound",
        log_location=launch.log_location,
        mcp_url=f"{authority}{MCP_PATH}",
        readiness_url=f"{authority}{READINESS_PATH}",
        shutdown=launch.shutdown,
        ui_url=f"{authority}{UI_PATH}",
    )


def _watch_stdin(stream: BinaryIO, server: object, launch: Launch) -> None:
    """Shutdown lease watcher (background OS thread; blocking stdin reads).

    Stdin EOF (parent-lifetime lease) or an authenticated ``shutdown`` frame
    sets ``server.should_exit`` — the same plain-bool signal uvicorn's own
    signal handler uses, polled by ``main_loop`` every 0.1s. Anything else
    (bad token, wrong contract, garbage, wrong kind) is ignored and the
    watcher keeps reading; an invalid frame must never stop the server.
    """
    while True:
        try:
            raw = read_frame(stream)
        except DesktopContractError:
            continue
        if raw is None:
            server.should_exit = True  # type: ignore[attr-defined]
            return
        try:
            frame = parse_frame(raw)
        except DesktopContractError:
            continue
        if (
            isinstance(frame, Shutdown)
            and frame.contract == launch.contract
            and tokens_equal(frame.startup_token, launch.startup_token)
        ):
            server.should_exit = True  # type: ignore[attr-defined]
            return


async def _serve(
    app: Callable[..., Awaitable[None]],
    sock: socket.socket,
    launch: Launch,
    identity: ExecutableIdentity,
    protocol_fd: int,
    control_stream: BinaryIO,
) -> int:
    """Hand-drive uvicorn so ``bound`` is emitted at the started boundary.

    ``Server.startup()`` awaits the FastAPI lifespan (the eager warm-up) and
    only then wraps the pre-bound socket in a listening asyncio server, so
    when it returns with ``started`` set, ``/readyz`` warmth and the LISTEN
    state both already hold. ``.run()``/``.serve()`` offer no hook between
    those steps, which is why this drives ``startup``/``main_loop``/
    ``shutdown`` directly. ``MIN_GRACE_MS`` is honored by construction:
    ``timeout_graceful_shutdown`` stays ``None`` (unbounded drain — a
    superset of the contract's floor) and the parse layer already rejected
    any launch with a smaller ``grace_ms``.
    """
    import uvicorn

    port = sock.getsockname()[1]
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, lifespan="on", log_config=None
    )
    server = uvicorn.Server(config)
    with server.capture_signals():
        if not config.loaded:
            config.load()
        server.lifespan = config.lifespan_class(config)
        await server.startup(sockets=[sock])
        if server.should_exit or not server.started:
            logger.error("desktop child startup failed; bound never emitted")
            return 1
        payload = memoryview(encode_frame(_make_bound(launch, port, identity)))
        while payload:
            written = os.write(protocol_fd, payload)
            payload = payload[written:]
        # The control stdout carries exactly one frame, ever; closing the fd
        # makes a second write structurally impossible.
        os.close(protocol_fd)
        threading.Thread(
            target=_watch_stdin,
            args=(control_stream, server, launch),
            daemon=True,
        ).start()
        await server.main_loop()
        await server.shutdown(sockets=[sock])
    return 0


def main() -> int:
    logging.basicConfig(level=os.environ.get("ARXMCP_LOG_LEVEL", "INFO"))
    control_stream = sys.stdin.buffer
    # Reserve the real stdout pipe for the single bound frame, then point
    # fd 1 at stderr so no library print (model loaders, tracebacks) can
    # ever corrupt the control stream.
    protocol_fd = os.dup(sys.stdout.fileno())
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())

    identity = executable_identity()
    try:
        raw = read_frame(control_stream)
        if raw is None:
            raise DesktopContractError("launch frame required on stdin")
        frame = parse_frame(raw)
        if not isinstance(frame, Launch):
            raise DesktopContractError("launch frame required on stdin")
        _validate_launch(frame, identity)
    except DesktopContractError as exc:
        # Contract errors are payload-free by design; safe to log.
        logger.error("desktop child rejected launch: %s", exc)
        return 2

    # Ephemeral loopback bind happens here, entirely outside Config.
    # listen() is deliberately absent: uvicorn's startup wraps this socket
    # via loop.create_server(sock=...), which is what starts listening —
    # after the lifespan warm-up.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        from server.config import Config
        from server.main import create_app

        try:
            cfg = Config(data_dir=Path(frame.data_root))
            app = create_app(cfg)
        except Exception as exc:
            logger.error("FATAL during desktop-child app build: %s", exc)
            return 1
        app = ReadyzStartupTokenMiddleware(
            app, expected_token=frame.startup_token
        )
        return asyncio.run(
            _serve(app, sock, frame, identity, protocol_fd, control_stream)
        )
    finally:
        sock.close()


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "COMPONENT",
    "ReadyzStartupTokenMiddleware",
    "executable_identity",
    "main",
    "read_frame",
]
