"""Bounded, deterministic desktop/server launch contract.

The launch capability is accepted only from the private control stream.  It is
intentionally absent from :class:`Bound`, URLs, exception messages, and object
representations so later desktop adapters can persist only token-free state.
"""

from __future__ import annotations

import hmac
import json
import math
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeAlias

FRAME_LIMIT = 4_096
SUPPORTED_MAJOR = 1
MIN_GRACE_MS = 35_000
STARTUP_TOKEN_HEADER = "X-ArXMCP-Startup-Token"
HEALTH_PATH = "/healthz"
READINESS_PATH = "/readyz"
MCP_PATH = "/mcp"
UI_PATH = "/ui/"

_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_MAX_JSON_DEPTH = 32
_MAX_EXTENSION_KEYS = 32
_TOKEN_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_COMPONENT_PATTERN = re.compile(r"[a-z0-9-]{1,64}\Z")
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_EXTENSION_KEY_PATTERN = re.compile(
    r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?\Z"
)


class DesktopContractError(ValueError):
    """A control frame violates the versioned desktop contract."""


class UnsupportedMajorError(DesktopContractError):
    """A control frame names an incompatible contract major."""


class DuplicateKeyError(DesktopContractError):
    """A JSON object repeats a key."""


@dataclass(frozen=True, slots=True, repr=False)
class StartupToken:
    """A 256-bit capability whose representation is always redacted."""

    _value: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self._value, str)
            or _TOKEN_PATTERN.fullmatch(self._value) is None
        ):
            raise DesktopContractError("invalid startup token")

    @classmethod
    def parse(cls, value: object) -> StartupToken:
        if not isinstance(value, str) or _TOKEN_PATTERN.fullmatch(value) is None:
            raise DesktopContractError("invalid startup token")
        return cls(value)

    def expose(self) -> str:
        """Return the capability only for private-channel transport or comparison."""
        return self._value

    def __repr__(self) -> str:
        return "StartupToken([REDACTED])"


def generate_startup_token() -> StartupToken:
    """Return a capability backed by 32 bytes from the OS CSPRNG."""
    return StartupToken.parse(secrets.token_hex(32))


def tokens_equal(left: StartupToken, right: StartupToken) -> bool:
    """Compare two capabilities without value-dependent early return."""
    return hmac.compare_digest(left.expose(), right.expose())


@dataclass(frozen=True, slots=True)
class ContractVersion:
    major: int
    minor: int


@dataclass(frozen=True, slots=True)
class ExecutableIdentity:
    component: str
    sha256: str
    version: str


@dataclass(frozen=True, slots=True)
class Endpoint:
    host: str
    port: int


@dataclass(frozen=True, slots=True)
class ProbePaths:
    health: str
    mcp: str
    readiness: str
    ui: str


@dataclass(frozen=True, slots=True)
class ShutdownSemantics:
    force_after_ms: int
    grace_ms: int
    parent_lifetime: str
    reap: str


Extensions: TypeAlias = dict[str, Any]


@dataclass(frozen=True, slots=True)
class Launch:
    contract: ContractVersion
    data_root: Path
    endpoint_request: Endpoint
    executable: ExecutableIdentity
    extensions: Extensions
    kind: Literal["launch"]
    log_location: Path
    probe_paths: ProbePaths
    shutdown: ShutdownSemantics
    startup_token: StartupToken = field(repr=False)


@dataclass(frozen=True, slots=True)
class Bound:
    contract: ContractVersion
    data_root: Path
    endpoint: Endpoint
    executable: ExecutableIdentity
    extensions: Extensions
    health_url: str
    kind: Literal["bound"]
    log_location: Path
    mcp_url: str
    readiness_url: str
    shutdown: ShutdownSemantics
    ui_url: str


@dataclass(frozen=True, slots=True)
class Shutdown:
    contract: ContractVersion
    extensions: Extensions
    kind: Literal["shutdown"]
    startup_token: StartupToken = field(repr=False)


Frame: TypeAlias = Launch | Bound | Shutdown


class ChildControlState:
    """Validate the child-facing launch then shutdown sequence."""

    __slots__ = ("_phase",)

    def __init__(self) -> None:
        self._phase = "awaiting-launch"

    @property
    def phase(self) -> str:
        return self._phase

    def accept(self, frame: Frame) -> None:
        if self._phase == "awaiting-launch" and isinstance(frame, Launch):
            self._phase = "running"
            return
        if self._phase == "running" and isinstance(frame, Shutdown):
            self._phase = "stopped"
            return
        raise DesktopContractError("invalid control-frame sequence")


def parse_frame(frame: bytes) -> Frame:
    """Parse and validate one LF-terminated, duplicate-free NDJSON frame."""
    payload = _frame_payload(frame)
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DesktopContractError("control frame is not valid UTF-8") from exc
    try:
        value = json.loads(
            decoded,
            object_pairs_hook=_unique_object,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except DuplicateKeyError:
        raise
    except (json.JSONDecodeError, DesktopContractError, ValueError) as exc:
        raise DesktopContractError("control frame is not valid canonical JSON") from exc

    _validate_json_value(value)
    top = _require_object(value, "top-level JSON must be an object")
    _preflight_major(top)
    kind = top.get("kind")
    if kind == "launch":
        return _parse_launch(top)
    if kind == "bound":
        return _parse_bound(top)
    if kind == "shutdown":
        return _parse_shutdown(top)
    raise DesktopContractError("unsupported frame kind")


def encode_frame(frame: Frame) -> bytes:
    """Emit the shared canonical JSON subset with exactly one trailing LF."""
    value = _frame_to_dict(frame)
    try:
        candidate = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError) as exc:
        raise DesktopContractError("frame cannot be serialized") from exc
    validated = parse_frame(candidate)
    value = _frame_to_dict(validated)
    _validate_json_value(value)
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError) as exc:
        raise DesktopContractError("frame cannot be serialized") from exc
    if len(payload) > FRAME_LIMIT:
        raise DesktopContractError("control frame exceeds 4096 bytes")
    return payload


def canonicalize_frame(frame: bytes) -> bytes:
    """Validate then re-emit one frame in byte-stable form."""
    return encode_frame(parse_frame(frame))


def _parse_launch(value: dict[str, Any]) -> Launch:
    _expect_keys(
        value,
        {
            "contract",
            "data_root",
            "endpoint_request",
            "executable",
            "extensions",
            "kind",
            "log_location",
            "probe_paths",
            "shutdown",
            "startup_token",
        },
        "launch",
    )
    frame = Launch(
        contract=_parse_version(value["contract"]),
        data_root=_parse_path(value["data_root"], "data root"),
        endpoint_request=_parse_endpoint(value["endpoint_request"], "endpoint request"),
        executable=_parse_identity(value["executable"]),
        extensions=_parse_extensions(value["extensions"]),
        kind="launch",
        log_location=_parse_path(value["log_location"], "log location"),
        probe_paths=_parse_probe_paths(value["probe_paths"]),
        shutdown=_parse_shutdown_semantics(value["shutdown"]),
        startup_token=StartupToken.parse(value["startup_token"]),
    )
    if frame.endpoint_request != Endpoint("127.0.0.1", 0):
        raise DesktopContractError("launch endpoint must be 127.0.0.1:0")
    _validate_paths(frame.data_root, frame.log_location)
    return frame


def _parse_bound(value: dict[str, Any]) -> Bound:
    _expect_keys(
        value,
        {
            "contract",
            "data_root",
            "endpoint",
            "executable",
            "extensions",
            "health_url",
            "kind",
            "log_location",
            "mcp_url",
            "readiness_url",
            "shutdown",
            "ui_url",
        },
        "bound",
    )
    frame = Bound(
        contract=_parse_version(value["contract"]),
        data_root=_parse_path(value["data_root"], "data root"),
        endpoint=_parse_endpoint(value["endpoint"], "endpoint"),
        executable=_parse_identity(value["executable"]),
        extensions=_parse_extensions(value["extensions"]),
        health_url=_require_string(value["health_url"], "health URL"),
        kind="bound",
        log_location=_parse_path(value["log_location"], "log location"),
        mcp_url=_require_string(value["mcp_url"], "MCP URL"),
        readiness_url=_require_string(value["readiness_url"], "readiness URL"),
        shutdown=_parse_shutdown_semantics(value["shutdown"]),
        ui_url=_require_string(value["ui_url"], "UI URL"),
    )
    if frame.endpoint.host != "127.0.0.1" or not 1 <= frame.endpoint.port <= 65_535:
        raise DesktopContractError("bound endpoint must use a nonzero loopback port")
    _validate_paths(frame.data_root, frame.log_location)
    authority = f"http://127.0.0.1:{frame.endpoint.port}"
    expected = (
        (frame.health_url, f"{authority}{HEALTH_PATH}"),
        (frame.readiness_url, f"{authority}{READINESS_PATH}"),
        (frame.mcp_url, f"{authority}{MCP_PATH}"),
        (frame.ui_url, f"{authority}{UI_PATH}"),
    )
    if any(actual != wanted for actual, wanted in expected):
        raise DesktopContractError("bound URL does not match announced endpoint")
    return frame


def _parse_shutdown(value: dict[str, Any]) -> Shutdown:
    _expect_keys(value, {"contract", "extensions", "kind", "startup_token"}, "shutdown")
    return Shutdown(
        contract=_parse_version(value["contract"]),
        extensions=_parse_extensions(value["extensions"]),
        kind="shutdown",
        startup_token=StartupToken.parse(value["startup_token"]),
    )


def _parse_version(value: object) -> ContractVersion:
    obj = _require_object(value, "contract version must be an object")
    _expect_keys(obj, {"major", "minor"}, "contract version")
    major = _require_integer(obj["major"], "contract major", minimum=0, maximum=65_535)
    minor = _require_integer(obj["minor"], "contract minor", minimum=0, maximum=65_535)
    if major != SUPPORTED_MAJOR:
        raise UnsupportedMajorError(f"unsupported desktop contract major {major}")
    return ContractVersion(major=major, minor=minor)


def _parse_identity(value: object) -> ExecutableIdentity:
    obj = _require_object(value, "executable identity must be an object")
    _expect_keys(obj, {"component", "sha256", "version"}, "executable identity")
    component = _require_string(obj["component"], "executable component")
    digest = _require_string(obj["sha256"], "executable digest")
    version = _require_string(obj["version"], "executable version")
    version_ok = (
        len(version) <= 64
        and all(character.isascii() and character.isprintable() for character in version)
        and "/" not in version
        and "\\" not in version
    )
    if (
        _COMPONENT_PATTERN.fullmatch(component) is None
        or _DIGEST_PATTERN.fullmatch(digest) is None
        or not version_ok
    ):
        raise DesktopContractError("invalid executable identity")
    return ExecutableIdentity(component=component, sha256=digest, version=version)


def _parse_endpoint(value: object, label: str) -> Endpoint:
    obj = _require_object(value, f"{label} must be an object")
    _expect_keys(obj, {"host", "port"}, label)
    return Endpoint(
        host=_require_string(obj["host"], f"{label} host"),
        port=_require_integer(obj["port"], f"{label} port", minimum=0, maximum=65_535),
    )


def _parse_probe_paths(value: object) -> ProbePaths:
    obj = _require_object(value, "probe paths must be an object")
    _expect_keys(obj, {"health", "mcp", "readiness", "ui"}, "probe paths")
    paths = ProbePaths(
        health=_require_string(obj["health"], "health path"),
        mcp=_require_string(obj["mcp"], "MCP path"),
        readiness=_require_string(obj["readiness"], "readiness path"),
        ui=_require_string(obj["ui"], "UI path"),
    )
    if paths != ProbePaths(HEALTH_PATH, MCP_PATH, READINESS_PATH, UI_PATH):
        raise DesktopContractError("unsupported probe paths")
    return paths


def _parse_shutdown_semantics(value: object) -> ShutdownSemantics:
    obj = _require_object(value, "shutdown semantics must be an object")
    _expect_keys(
        obj,
        {"force_after_ms", "grace_ms", "parent_lifetime", "reap"},
        "shutdown semantics",
    )
    semantics = ShutdownSemantics(
        force_after_ms=_require_integer(
            obj["force_after_ms"], "force deadline", minimum=1, maximum=MIN_GRACE_MS
        ),
        grace_ms=_require_integer(
            obj["grace_ms"], "grace deadline", minimum=MIN_GRACE_MS
        ),
        parent_lifetime=_require_string(obj["parent_lifetime"], "parent lifetime"),
        reap=_require_string(obj["reap"], "reap semantics"),
    )
    if (
        semantics.parent_lifetime != "stdin-eof"
        or semantics.reap != "graceful-force-reap"
    ):
        raise DesktopContractError("invalid shutdown semantics")
    return semantics


def _parse_extensions(value: object) -> Extensions:
    extensions = _require_object(value, "extensions must be an object")
    if len(extensions) > _MAX_EXTENSION_KEYS:
        raise DesktopContractError("too many extension keys")
    for key, nested in extensions.items():
        if _EXTENSION_KEY_PATTERN.fullmatch(key) is None or "." not in key:
            raise DesktopContractError("invalid extension namespace")
        _validate_extension_value(nested)
    return extensions


def _validate_extension_value(value: object, depth: int = 0) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise DesktopContractError("extension nesting is too deep")
    if isinstance(value, dict):
        for key, nested in value.items():
            if _EXTENSION_KEY_PATTERN.fullmatch(key) is None:
                raise DesktopContractError("invalid extension key")
            _validate_extension_value(nested, depth + 1)
    elif isinstance(value, list):
        for nested in value:
            _validate_extension_value(nested, depth + 1)


def _validate_paths(root: Path, log_location: Path) -> None:
    try:
        relative = log_location.relative_to(root)
    except ValueError as exc:
        raise DesktopContractError("log location escapes data root") from exc
    if len(relative.parts) < 2 or relative.parts[0] != "logs":
        raise DesktopContractError("log location must name a file beneath data_root/logs")


def _parse_path(value: object, label: str) -> Path:
    text = _require_string(value, label)
    path = Path(text)
    if not path.is_absolute() or path.resolve(strict=False) != path:
        raise DesktopContractError(f"{label} must be canonical and absolute")
    return path


def _frame_to_dict(frame: Frame) -> dict[str, Any]:
    contract = {"major": frame.contract.major, "minor": frame.contract.minor}
    if isinstance(frame, Launch):
        if frame.kind != "launch":
            raise DesktopContractError("launch kind mismatch")
        return {
            "contract": contract,
            "data_root": str(frame.data_root),
            "endpoint_request": _endpoint_dict(frame.endpoint_request),
            "executable": _identity_dict(frame.executable),
            "extensions": frame.extensions,
            "kind": "launch",
            "log_location": str(frame.log_location),
            "probe_paths": {
                "health": frame.probe_paths.health,
                "mcp": frame.probe_paths.mcp,
                "readiness": frame.probe_paths.readiness,
                "ui": frame.probe_paths.ui,
            },
            "shutdown": _shutdown_dict(frame.shutdown),
            "startup_token": frame.startup_token.expose(),
        }
    if isinstance(frame, Bound):
        if frame.kind != "bound":
            raise DesktopContractError("bound kind mismatch")
        return {
            "contract": contract,
            "data_root": str(frame.data_root),
            "endpoint": _endpoint_dict(frame.endpoint),
            "executable": _identity_dict(frame.executable),
            "extensions": frame.extensions,
            "health_url": frame.health_url,
            "kind": "bound",
            "log_location": str(frame.log_location),
            "mcp_url": frame.mcp_url,
            "readiness_url": frame.readiness_url,
            "shutdown": _shutdown_dict(frame.shutdown),
            "ui_url": frame.ui_url,
        }
    if isinstance(frame, Shutdown):
        if frame.kind != "shutdown":
            raise DesktopContractError("shutdown kind mismatch")
        return {
            "contract": contract,
            "extensions": frame.extensions,
            "kind": "shutdown",
            "startup_token": frame.startup_token.expose(),
        }
    raise TypeError("unsupported desktop contract frame")


def _identity_dict(identity: ExecutableIdentity) -> dict[str, Any]:
    return {
        "component": identity.component,
        "sha256": identity.sha256,
        "version": identity.version,
    }


def _endpoint_dict(endpoint: Endpoint) -> dict[str, Any]:
    return {"host": endpoint.host, "port": endpoint.port}


def _shutdown_dict(semantics: ShutdownSemantics) -> dict[str, Any]:
    return {
        "force_after_ms": semantics.force_after_ms,
        "grace_ms": semantics.grace_ms,
        "parent_lifetime": semantics.parent_lifetime,
        "reap": semantics.reap,
    }


def _frame_payload(frame: bytes) -> bytes:
    if not isinstance(frame, bytes):
        raise TypeError("control frame must be bytes")
    if len(frame) > FRAME_LIMIT:
        raise DesktopContractError("control frame exceeds 4096 bytes")
    if len(frame) < 2 or not frame.endswith(b"\n") or frame.endswith(b"\r\n"):
        raise DesktopContractError("control frame must end with one LF")
    payload = frame[:-1]
    if b"\n" in payload or payload.startswith(b"\xef\xbb\xbf"):
        raise DesktopContractError("control frame is not valid UTF-8")
    return payload


def _preflight_major(value: dict[str, Any]) -> None:
    contract = value.get("contract")
    if not isinstance(contract, dict):
        raise DesktopContractError("missing contract version")
    major = contract.get("major")
    if isinstance(major, bool) or not isinstance(major, int) or major < 0:
        raise DesktopContractError("invalid contract major")
    if major != SUPPORTED_MAJOR:
        raise UnsupportedMajorError(f"unsupported desktop contract major {major}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, nested in pairs:
        if key in value:
            raise DuplicateKeyError("control frame contains a duplicate key")
        value[key] = nested
    return value


def _reject_float(_value: str) -> float:
    raise DesktopContractError("floating-point JSON values are not supported")


def _reject_constant(_value: str) -> float:
    raise DesktopContractError("non-finite JSON values are not supported")


def _validate_json_value(value: object, depth: int = 0) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise DesktopContractError("JSON nesting is too deep")
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, int):
        if abs(value) > _MAX_SAFE_INTEGER:
            raise DesktopContractError("JSON integer exceeds the safe range")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DesktopContractError("non-finite JSON values are not supported")
        raise DesktopContractError("floating-point JSON values are not supported")
    if isinstance(value, list):
        for nested in value:
            _validate_json_value(nested, depth + 1)
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise DesktopContractError("JSON object keys must be strings")
            _validate_json_value(nested, depth + 1)
        return
    raise DesktopContractError("unsupported JSON value")


def _expect_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise DesktopContractError(f"malformed {label}")


def _require_object(value: object, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DesktopContractError(message)
    return value


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise DesktopContractError(f"invalid {label}")
    return value


def _require_integer(
    value: object,
    label: str,
    *,
    minimum: int,
    maximum: int = _MAX_SAFE_INTEGER,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise DesktopContractError(f"invalid {label}")
    return value


__all__ = [
    "Bound",
    "ChildControlState",
    "ContractVersion",
    "DesktopContractError",
    "DuplicateKeyError",
    "Endpoint",
    "ExecutableIdentity",
    "FRAME_LIMIT",
    "Frame",
    "HEALTH_PATH",
    "Launch",
    "MCP_PATH",
    "MIN_GRACE_MS",
    "ProbePaths",
    "READINESS_PATH",
    "STARTUP_TOKEN_HEADER",
    "SUPPORTED_MAJOR",
    "Shutdown",
    "ShutdownSemantics",
    "StartupToken",
    "UI_PATH",
    "UnsupportedMajorError",
    "canonicalize_frame",
    "encode_frame",
    "generate_startup_token",
    "parse_frame",
    "tokens_equal",
]
