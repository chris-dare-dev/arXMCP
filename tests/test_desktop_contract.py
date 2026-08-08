"""Cross-language conformance and model-free desktop sidecar lifecycle tests."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import warnings
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
    "launch-v1-windows-path.jsonl",
)
NEGATIVE_FIXTURES = (
    "duplicate-core-field.jsonl",
    "unknown-core-field.jsonl",
    "wildcard-bound.jsonl",
    "mismatched-url-bound.jsonl",
    "invalid-version-space.jsonl",
    "oversized-frame.jsonl",
)
FIXTURE_ONLY_TOKEN = "0" * 64


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _sidecar_binary() -> Path | None:
    """The built fixture sidecar, or None when nobody asked for one.

    An EXPLICIT ``ARXMCP_FIXTURE_SIDECAR`` that does not resolve to a file
    is a build failure, not an absence: returning None there let the two
    headline m6 tests skip while ``make desktop-conformance`` still exited 0
    (a wrong DESKTOP_EXE_SUFFIX, an interrupted `cargo build`, an ambient
    CARGO_TARGET_DIR). ``pytest.fail`` matches `_supervisor_binary` /
    `_fixture_binary` in tests/test_desktop_child.py."""
    configured = os.environ.get("ARXMCP_FIXTURE_SIDECAR")
    if configured:
        candidate = Path(configured).resolve()
        if not candidate.is_file():
            pytest.fail(
                f"ARXMCP_FIXTURE_SIDECAR is set to {configured!r} but that is "
                f"not a file — build it with `make desktop-conformance`; a "
                f"missing explicitly-requested binary is never a skip"
            )
        return candidate
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
        data_root=root.as_posix(),
        executable=executable,
        log_location=(root / "logs" / "fixture-sidecar.log").as_posix(),
        startup_token=token,
    )


def _exception_graph_values(error: BaseException) -> list[str]:
    values: list[str] = []
    pending: list[object] = [error]
    visited: set[int] = set()
    while pending:
        value = pending.pop()
        if value is None or id(value) in visited:
            continue
        visited.add(id(value))
        if isinstance(value, bytes):
            values.append(value.decode("latin-1"))
        elif isinstance(value, str):
            values.append(value)
        elif isinstance(value, BaseException):
            pending.extend(value.args)
            pending.extend((value.__cause__, value.__context__))
            pending.extend(
                getattr(value, attribute, None) for attribute in ("doc", "object")
            )
        elif isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple, set)):
            pending.extend(value)
    return values


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


#: Directories searched when `shutil.which` misses. `/usr/sbin` is where macOS
#: keeps `lsof`; most Linux distros use `/usr/bin/lsof` and `/bin/ps`.
_PROBE_DIRS = ("/usr/sbin", "/usr/bin", "/bin", "/sbin")


def _probe_command(argv: list[str]) -> subprocess.CompletedProcess[bytes]:
    """Run one `ps`/`lsof` evidence probe, asserting the PROBE ITSELF worked.

    Spike-3 discipline: a failed or partial probe is an evidence failure,
    never clean absence. **Exit code alone cannot establish that.** Measured
    on this box, `lsof -nP --bogus`, `lsof` on an unresolvable service, and
    `ps -p notanumber` all exit 1 with an EMPTY stdout — byte-identical to a
    clean no-match. So this raises on a missing binary, a timeout, an exit
    code outside (0, 1), and on an exit-1 that carries stderr diagnostics —
    and every caller additionally supplies its own positive control (see
    `_listener_lines` and `_pgid_members`), which is what actually
    discriminates "the probe worked and found nothing" from "the probe
    failed"."""
    binary = shutil.which(argv[0])
    if binary is None:
        for directory in _PROBE_DIRS:
            candidate = f"{directory}/{argv[0]}"
            if Path(candidate).is_file():
                binary = candidate
                break
    if binary is None or not Path(binary).is_file():
        raise RuntimeError(
            f"{argv[0]} unavailable — the audit cannot run, and no-probe is "
            f"never clean absence"
        )
    completed = subprocess.run(
        [binary, *argv[1:]], capture_output=True, timeout=10, check=False
    )
    if completed.returncode not in (0, 1):
        raise RuntimeError(f"probe failed (not a clean no-match): {completed}")
    if completed.returncode == 1 and completed.stderr.strip():
        raise RuntimeError(
            f"probe exited 1 WITH diagnostics, so it is an error rather than "
            f"a clean no-match: {completed.stderr!r}"
        )
    return completed


def _pid_is_gone(pid: int) -> bool:
    """Unambiguous liveness via `os.kill(pid, 0)` — no subprocess to misreport.

    `ps -p <pid>` exits 1 both for "no such process" and for a genuine error
    (a malformed pid, a `hidepid` mount, a denied /proc), so it cannot tell a
    broken probe from verified absence. The signal-0 probe has no such
    ambiguity: ProcessLookupError is gone, PermissionError is alive."""
    if sys.platform == "win32":  # pragma: no cover - POSIX-only audit
        raise RuntimeError(
            "signal-0 liveness probing is POSIX-only (on Windows os.kill "
            "TERMINATES the target), and no-probe is never clean absence"
        )
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def _listener_lines(port: int) -> list[str]:
    """Non-header `lsof` LISTEN rows for `port`; [] means VERIFIED absence.

    Verified by a SAME-INVOCATION positive control: this opens a throwaway
    loopback listener and asks `lsof` about both ports at once. A broken,
    denied, or misinvoked `lsof` exits 1 with empty stdout exactly as a clean
    no-match does, so the missing control row — not the exit code — is what
    proves the probe failed, and that raises instead of reading as absence.

    AC3: "a failed or partial `ps`/`lsof` probe is an evidence failure, never
    clean absence."""
    holds: list[socket.socket] = []
    try:
        while True:
            control = socket.socket()
            holds.append(control)
            control.bind(("127.0.0.1", 0))
            control.listen(1)
            control_port = control.getsockname()[1]
            # A control that landed ON the audited port would be indistinguishable
            # from a real residual listener; keep it bound and try another.
            if control_port != port:
                break
        completed = _probe_command(
            ["lsof", "-nP", f"-iTCP:{port},{control_port}", "-sTCP:LISTEN"]
        )
        rows = [
            line
            for line in completed.stdout.decode("utf-8", "replace").splitlines()
            if line and not line.startswith("COMMAND")
        ]
        # Trailing space: ":4924 " must not match a ":49248 " row.
        control_row = f":{control_port} "
        if not any(control_row in row for row in rows):
            raise RuntimeError(
                f"lsof failed its positive control — port {control_port} is "
                f"held open by this process yet was not reported "
                f"(rc={completed.returncode}, stderr={completed.stderr!r}). "
                f"An unverified probe is never clean absence."
            )
        return [row for row in rows if control_row not in row]
    finally:
        for held in holds:
            held.close()


def _pgid_members(pgid: int) -> list[int]:
    """PIDs currently in process group `pgid`; [] means VERIFIED empty.

    Reads the FULL process table rather than `ps -g <pgid>`, which exits 1
    for both "empty group" and a genuine error. The control is intrinsic:
    our own pid must appear in the listing, so a truncated, denied, or
    misparsed table raises instead of reading as an empty group."""
    completed = _probe_command(["ps", "-A", "-o", "pid=,pgid="])
    members: list[int] = []
    saw_self = False
    for line in completed.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split()
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            continue
        pid, group = int(parts[0]), int(parts[1])
        saw_self = saw_self or pid == os.getpid()
        if group == pgid:
            members.append(pid)
    if not saw_self:
        raise RuntimeError(
            f"the ps process-table probe never listed our own pid "
            f"{os.getpid()} — a partial listing is never a verified-empty "
            f"process group"
        )
    return members


def _non_loopback_ipv4s() -> list[str]:
    """Best-effort discovery of this host's non-loopback IPv4 addresses.

    Both probes can legitimately find nothing (loopback-only host); the
    CALLER must record that degradation rather than skip silently."""
    found: set[str] = set()
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        found.update(info[4][0] for info in infos)
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # TEST-NET-1: a route lookup only; no packet leaves the host.
            probe.connect(("192.0.2.1", 9))
            found.add(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass
    return sorted(ip for ip in found if not ip.startswith("127."))


def _assert_loopback_only(port: int) -> list[str]:
    """Socket-level loopback proof against a LIVE listener (not a wire field).

    Three independent checks: lsof must FIND the listener (so a dead server or
    broken probe cannot pass) and every row's local address must be
    127.0.0.1; a TCP connect on each discoverable non-loopback address must
    fail; the caller already proved 127.0.0.1 connects. Returns the LAN IPs
    probed so the caller can record a loopback-only-host degradation."""
    lines = _listener_lines(port)
    assert lines, f"lsof found no listener on live port {port} — probe/server failure"
    for line in lines:
        assert f"127.0.0.1:{port}" in line, line
        assert f"*:{port}" not in line, line
        assert "0.0.0.0" not in line, line
    lan_ips = _non_loopback_ipv4s()
    for ip in lan_ips:
        with pytest.raises(OSError):
            socket.create_connection((ip, port), timeout=2).close()
    return lan_ips


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
        "camelCase": True,
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


@pytest.mark.parametrize(
    ("malformed", "canary"),
    [
        (b'{"canary":"decoder-secret"}\xff\n', "decoder-secret"),
        (b'{"canary":"json-secret",}\n', "json-secret"),
    ],
)
def test_decoder_exceptions_do_not_retain_control_input(
    malformed: bytes, canary: str
) -> None:
    with pytest.raises(DesktopContractError) as raised:
        parse_frame(malformed)
    assert all(canary not in value for value in _exception_graph_values(raised.value))


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


def _makefile_recipe(target: str) -> str:
    """The tab-indented recipe lines of one target, excluding later targets."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    body = makefile.split(f"\n{target}:\n", 1)[1]
    lines: list[str] = []
    for line in body.splitlines():
        if not line.startswith("\t"):
            break
        lines.append(line)
    return "\n".join(lines)


def test_desktop_conformance_gate_builds_before_process_tests() -> None:
    target = _makefile_recipe("desktop-conformance")
    assert "cargo build --locked" in target
    for binary, harness_var in (
        ("--bin fixture-sidecar", "ARXMCP_FIXTURE_SIDECAR="),
        ("--bin supervisor", "DESKTOP_SUPERVISOR_BIN="),
    ):
        assert binary in target
        assert harness_var in target
        assert target.index(binary) < target.index(harness_var), (
            f"{binary} must be built before the suite that consumes it"
        )


def test_desktop_conformance_marker_token_is_a_registered_opt_in_marker() -> None:
    """m5 critique H3: `-m "<token> or not <token>"` is a tautology for ANY
    token, so pytest's own filter selects everything however the name drifts;
    the ONLY thing opting the real-stack tests in is the conftest hook's
    substring check against ``_OPT_IN_MARKERS``. When those disagree the tests
    skip and the gate still exits 0 (reproduced: `4 skipped, 9 passed`)."""
    from tests.conftest import _OPT_IN_MARKERS

    recipe = _makefile_recipe("desktop-conformance")
    expressions = re.findall(r'-m\s+"([^"]+)"', recipe)
    assert expressions, "desktop-conformance must select tests with -m"
    for expression in expressions:
        tokens = {
            token
            for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression)
            if token not in {"and", "or", "not"}
        }
        assert tokens, f"the -m expression names no marker: {expression!r}"
        assert tokens <= _OPT_IN_MARKERS, (
            f"{sorted(tokens - _OPT_IN_MARKERS)} is not in "
            f"tests.conftest._OPT_IN_MARKERS — the gate would silently skip "
            f"the real-stack tests and still exit 0"
        )


def test_every_conformance_pytest_line_arms_the_zero_skip_gate() -> None:
    """m6 critique H2/H5: the zero-skip guard keyed on DESKTOP_SUPERVISOR_BIN
    alone, so the recipe line that runs THIS file — AC3's 30-cycle stress and
    AC5's socket-level loopback proof — was unguarded. Both could skip (an
    ambient CARGO_TARGET_DIR is enough) and `make desktop-conformance` still
    exited 0, satisfying AC6 with AC3 and AC5 absent."""
    from tests.conftest import _DESKTOP_GATE_ENV

    recipe = _makefile_recipe("desktop-conformance")
    pytest_lines = [line for line in recipe.splitlines() if "-m pytest" in line]
    assert len(pytest_lines) >= 2, recipe
    for line in pytest_lines:
        assert any(f"{name}=" in line for name in _DESKTOP_GATE_ENV), (
            f"this line runs pytest without arming the zero-skip gate "
            f"({' / '.join(_DESKTOP_GATE_ENV)}): {line.strip()}"
        )


def test_explicit_but_missing_sidecar_path_fails_rather_than_skips(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """m6 critique H5: `_sidecar_binary` returned None — hence a SKIP — when
    ARXMCP_FIXTURE_SIDECAR was set but did not resolve, which is a build
    failure, not an absence of interest."""
    monkeypatch.setenv("ARXMCP_FIXTURE_SIDECAR", str(tmp_path / "not-built"))
    with pytest.raises(pytest.fail.Exception, match="never a skip"):
        _sidecar_binary()


def test_probe_exit_one_with_diagnostics_is_an_error_not_a_no_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """m6 critique H1/H4: `lsof --bogus` and `ps -p notanumber` both exit 1,
    the same code a clean no-match uses."""
    monkeypatch.setattr(shutil, "which", lambda name: sys.executable)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 1, b"", b"lsof: illegal option character: -\n"
        ),
    )
    with pytest.raises(RuntimeError, match="WITH diagnostics"):
        _probe_command(["lsof", "-nP", "--bogus"])


def test_listener_probe_failure_raises_instead_of_reading_as_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """m6 critique H1/H4 — the load-bearing half. A broken `lsof` exits 1 with
    an EMPTY stdout and an EMPTY stderr, byte-identical to a clean no-match,
    so the exit code cannot carry the evidence and the stderr heuristic above
    does not fire either. The same-invocation positive control is what
    discriminates: the probe is asked about a port this process is holding
    open, and a reply that omits it can only mean the probe failed."""
    invocations: list[list[str]] = []

    def silently_broken(argv: list[str], **kwargs: object):
        invocations.append(argv)
        return subprocess.CompletedProcess(argv, 1, b"", b"")

    monkeypatch.setattr(shutil, "which", lambda name: sys.executable)
    monkeypatch.setattr(subprocess, "run", silently_broken)
    with pytest.raises(RuntimeError, match="positive control"):
        _listener_lines(65000)
    assert invocations, "the probe was never invoked"
    assert any(arg.startswith("-iTCP:65000,") for arg in invocations[0]), (
        f"the control port must ride the SAME invocation as the audited "
        f"port: {invocations[0]}"
    )


def test_process_group_probe_requires_seeing_its_own_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """m6 critique M11: `ps -g <pgid>` exits 1 for an empty group and for a
    denied one alike, so the group probe reads the whole table and treats a
    listing that omits this very process as a failure, not an empty group."""
    monkeypatch.setattr(shutil, "which", lambda name: sys.executable)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, b"", b""),
    )
    with pytest.raises(RuntimeError, match="never listed our own pid"):
        _pgid_members(1)


@pytest.mark.skipif(
    sys.platform == "win32", reason="signal-0 liveness probing is POSIX-only"
)
def test_pid_liveness_uses_signal_zero_rather_than_a_subprocess() -> None:
    """m6 critique H4: replacing `ps -p` removes the ambiguity at the source —
    there is no subprocess left to misreport."""
    reaped = subprocess.Popen([sys.executable, "-c", "pass"])
    reaped.wait(timeout=30)
    assert _pid_is_gone(reaped.pid) is True
    assert _pid_is_gone(os.getpid()) is False


def test_contract_fixture_directory_has_no_unclaimed_files() -> None:
    """m6 critique M10: the aggregate digest is the only thing that notices a
    new fixture, and a digest bump is indistinguishable from an intentional
    one — so a frame fixture could land with zero parse coverage. Adding one
    must now be a conscious consumer decision."""
    claimed = {
        *POSITIVE_FIXTURES,
        *NEGATIVE_FIXTURES,
        "incompatible-major.jsonl",
        "redaction-vectors.jsonl",
    }
    present = {path.name for path in FIXTURES.glob("*.jsonl")}
    assert present == claimed, (
        f"unclaimed fixtures: {sorted(present - claimed)}; "
        f"missing fixtures: {sorted(claimed - present)}"
    )


def test_desktop_readme_describes_the_shipped_workspace() -> None:
    """m5 critique C1: `process_control.rs` cites this README as the platform
    authority, so a present-tense denial of a crate that exists in the tree is
    a bug — and an operator reproducing the gate from it must be told to build
    the supervisor."""
    readme = (DESKTOP_ROOT / "README.md").read_text(encoding="utf-8")
    if (DESKTOP_ROOT / "crates" / "supervisor" / "src" / "main.rs").is_file():
        for stale in (
            "does not yet contain the Tauri shell",
            "not yet contain the Tauri shell",
            "deferred to the lifecycle walking skeleton",
        ):
            assert stale not in readme, f"stale README claim: {stale!r}"
        assert "supervisor" in readme
        assert "DESKTOP_SUPERVISOR_BIN" in readme


def test_desktop_readme_never_claims_a_descendant_free_child() -> None:
    """m6 critique C1: the README asserted "neither the production child nor
    the fixture spawns descendants today, so a `setsid()`-style escape cannot
    occur" — inverted in the unsafe direction. The production child hosts
    `ingest_tracker` / `parse_tracker`, whose helpers spawn with
    `start_new_session=True` (literally `setsid()`), so a forced kill of the
    child orphans them TODAY. Derived from the tree in the style of
    `tests/test_assert_ban.py`: while a spawn site exists, the README may not
    re-assert descendant-freedom."""
    spawners = sorted(
        path
        for tree in ("server", "ingest", "tools")
        for path in (REPO_ROOT / tree).rglob("*.py")
        if re.search(
            r"create_subprocess_exec|subprocess\.(?:Popen|run)",
            path.read_text(encoding="utf-8"),
        )
    )
    if not spawners:
        pytest.skip("no subprocess spawn site in the shipped trees")
    readme = (DESKTOP_ROOT / "README.md").read_text(encoding="utf-8")
    for inverted in (
        "spawns descendants today",
        "escape cannot occur",
        "not applicable, not handled",
    ):
        assert inverted not in readme, (
            f"README re-asserts descendant-freedom ({inverted!r}) while "
            f"{len(spawners)} spawn site(s) exist, e.g. "
            f"{spawners[0].relative_to(REPO_ROOT)}"
        )
    # The truthful replacement must name the real paths, not go vague.
    for required in ("ingest_tracker", "parse_tracker", "start_new_session"):
        assert required in readme, (
            f"the process-group section must name {required!r} — a vague "
            f"limit is not an honest one"
        )


def test_desktop_lockfile_has_no_git_sources() -> None:
    """No-fork policy (CLAUDE.md §4.7): every crate in the shipped desktop
    dependency graph resolves from the crates.io registry."""
    lockfile = (DESKTOP_ROOT / "Cargo.lock").read_text(encoding="utf-8")
    assert 'source = "git' not in lockfile


def test_supervisor_grants_no_webview_capabilities() -> None:
    """m5 critique M16/M17: the window renders HTTP served by the child, so the
    Tauri ACL is the boundary between a console scripting bug and host access.
    Deny-by-default means no `capabilities/` tree and no declared capability
    set; the unused shell plugin, whose permissions that ACL could grant, is
    gone. A future grant must land with an explicit edit to this test."""
    supervisor = DESKTOP_ROOT / "crates" / "supervisor"
    capabilities = supervisor / "capabilities"
    assert not capabilities.is_dir() or not list(capabilities.iterdir())
    conf = json.loads((supervisor / "tauri.conf.json").read_text(encoding="utf-8"))
    assert "capabilities" not in conf.get("app", {}).get("security", {})

    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in (supervisor / "src").rglob("*.rs")
    )
    assert "tauri_plugin_shell" not in sources
    for manifest in (supervisor / "Cargo.toml", DESKTOP_ROOT / "Cargo.toml"):
        assert "tauri-plugin-shell" not in manifest.read_text(encoding="utf-8")


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
            assert bound.data_root == root.as_posix()
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
    assert invalid_token.encode() not in completed.stderr
    assert not any(path.is_file() for path in root.rglob("*"))


def test_fixture_sidecar_rejects_sha_mismatch_before_binding(tmp_path: Path) -> None:
    binary = _sidecar_binary()
    if binary is None:
        pytest.skip("build fixture-sidecar or set ARXMCP_FIXTURE_SIDECAR")
    root = (tmp_path / "identity mismatch").resolve()
    (root / "logs").mkdir(parents=True)
    launch = _runtime_launch(root, binary, generate_startup_token())
    replacement = "0" if launch.executable.sha256[0] != "0" else "1"
    mismatched = replace(
        launch,
        executable=replace(
            launch.executable,
            sha256=replacement + launch.executable.sha256[1:],
        ),
    )
    completed = subprocess.run(
        [str(binary)],
        input=encode_frame(mismatched),
        capture_output=True,
        check=False,
        env={},
        timeout=2,
    )
    assert completed.returncode == 2
    assert completed.stdout == b""
    assert completed.stderr == (
        b"fixture-sidecar: fixture executable identity mismatch\n"
    )
    assert not any(path.is_file() for path in root.rglob("*"))


def test_redaction_vectors_shared_fixture_parity() -> None:
    """m6 AC2: Rust/Python redaction parity rides ONE shared vector file.

    The Rust production scrubber (`supervisor/src/redact.rs`, wired into the
    `bound-frame-invalid` diagnostic) and this Python reference consume the
    same `redaction-vectors.jsonl`, so a drift in either — or a vector edit —
    must pass both languages plus the `fixtures.sha256` pin. Python has no
    production substring-scrubber (its `RedactionFilter` drops named
    structured-log fields, a different mechanism for a surface Rust does not
    have), so the Python half is this reference semantic: EXACT-match
    replacement with `[REDACTED]`, no partial and no case-insensitive
    stripping."""
    lines = (
        (FIXTURES / "redaction-vectors.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    vectors = [json.loads(line) for line in lines if line]
    # Exact, not a floor: a floor of 7 against 9 shipped vectors let two be
    # deleted silently, and `fixtures.sha256` already forces the deliberate
    # two-language edit that adding or removing one requires.
    assert len(vectors) == 9, f"redaction vector set changed: {len(vectors)}"
    for vector in vectors:
        scrubbed = vector["input"].replace(vector["secret"], "[REDACTED]")
        assert scrubbed == vector["expected"], vector
    # The two anti-over-eagerness cases must stay present: a partial secret
    # and an uppercase near-miss are NOT redacted.
    assert any(
        vector["secret"] not in vector["input"]
        and vector["secret"][:63] in vector["input"]
        for vector in vectors
    ), "partial-match vector missing"
    assert any(
        vector["input"] == vector["secret"].upper() != vector["secret"]
        for vector in vectors
    ), "uppercase near-miss vector missing"


@pytest.mark.requires_desktop_stack
def test_thirty_cycles_distinct_pids_no_orphans_no_listeners(tmp_path: Path) -> None:
    """m6 AC3: thirty FRESH fixture-sidecar processes, each fully reaped.

    Every cycle spawns a new OS process (reusing one Popen is the named cheap
    lie), proves the listener live with one HTTP round trip, stops it
    (alternating authenticated-shutdown / stdin-EOF), then audits with
    self-asserting `ps`/`lsof` probes. Evidence is aggregated so one bad
    cycle cannot hide the shape of the other 29.

    AC3's "zero orphan process GROUPS" clause is measured, not argued: while
    the child is live its pgid must still be the harness's own group (it did
    not `setsid()` away), and after teardown the group rooted at the child's
    pid must be empty (nothing survives had it escaped)."""
    binary = _sidecar_binary()
    if binary is None:
        pytest.skip("build fixture-sidecar or set ARXMCP_FIXTURE_SIDECAR")

    root = (tmp_path / "stress runtime 数学").resolve()
    logs = root / "logs"
    logs.mkdir(parents=True)
    started = time.monotonic()
    evidence: list[dict] = []
    with (logs / "fixture-sidecar.log").open("wb") as log_handle:
        for cycle in range(30):
            token = generate_startup_token()
            launch = _runtime_launch(root, binary, token)
            process, _env = _spawn_sidecar(binary, launch, log_handle)
            try:
                if process.stdout is None or process.stdin is None:
                    raise RuntimeError("fixture sidecar control pipes unavailable")
                bound = parse_frame(
                    _readline_with_timeout(process.stdout, timeout=10.0)
                )
                if not isinstance(bound, Bound):
                    raise RuntimeError(f"cycle {cycle}: first frame was not bound")
                port = bound.endpoint.port
                status, _ = _request(port, "/healthz")
                assert status == 200, f"cycle {cycle}: live-listener probe failed"
                live_pgid = os.getpgid(process.pid)
                if cycle % 2 == 0:
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
                exit_code = process.wait(timeout=5)
            finally:
                _stop_process(process)
            evidence.append(
                {
                    "cycle": cycle,
                    "pid": process.pid,
                    "port": port,
                    "exit": exit_code,
                    "pid_gone": _pid_is_gone(process.pid),
                    "listeners": _listener_lines(port),
                    # A `setsid()`-style escape shows up as a pgid that is not
                    # the harness's; an escaped group's residue shows up as
                    # surviving members of the group rooted at the child pid.
                    "escaped_group": live_pgid != os.getpgid(0),
                    "group_residue": _pgid_members(process.pid),
                }
            )
    elapsed = time.monotonic() - started

    bad = [
        entry
        for entry in evidence
        if entry["exit"] != 0
        or not entry["pid_gone"]
        or entry["listeners"]
        or entry["escaped_group"]
        or entry["group_residue"]
    ]
    assert bad == [], bad
    assert len(evidence) == 30
    pids = [entry["pid"] for entry in evidence]
    assert len(set(pids)) == 30, f"expected 30 DISTINCT PIDs: {pids}"
    # Bounded, not aggressive (m3's 200ms->2s lesson): measured baseline is
    # ~0.4s/cycle, so 120s only catches a real hang, not repository load.
    assert elapsed < 120.0, f"30 cycles took {elapsed:.1f}s"


@pytest.mark.requires_desktop_stack
def test_live_listener_is_loopback_only_at_socket_level(tmp_path: Path) -> None:
    """m6 AC5 (fixture layer): loopback proven against the LIVE socket.

    The wire-contract negative fixture (`wildcard-bound.jsonl`) proves the
    FRAME cannot announce a wildcard; this proves the KERNEL state — lsof's
    local-address column and a refused connect on every discoverable LAN
    address. On a loopback-only host the LAN half legitimately degrades to
    the structural checks; that degradation is recorded, never skipped."""
    binary = _sidecar_binary()
    if binary is None:
        pytest.skip("build fixture-sidecar or set ARXMCP_FIXTURE_SIDECAR")

    root = (tmp_path / "loopback runtime 数学").resolve()
    (root / "logs").mkdir(parents=True)
    token = generate_startup_token()
    launch = _runtime_launch(root, binary, token)
    with (root / "logs" / "fixture-sidecar.log").open("wb") as log_handle:
        process, _env = _spawn_sidecar(binary, launch, log_handle)
        try:
            if process.stdout is None or process.stdin is None:
                raise RuntimeError("fixture sidecar control pipes unavailable")
            bound = parse_frame(_readline_with_timeout(process.stdout))
            assert isinstance(bound, Bound)
            port = bound.endpoint.port
            # Positive probe self-check: loopback DOES connect.
            socket.create_connection(("127.0.0.1", port), timeout=2).close()
            lan_ips = _assert_loopback_only(port)
            if not lan_ips:
                warnings.warn(
                    "no non-loopback IPv4 discoverable; LAN connect probe "
                    "degraded to the lsof structural checks",
                    stacklevel=1,
                )
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
            assert process.wait(timeout=5) == 0
        finally:
            _stop_process(process)
    assert _listener_lines(port) == []


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
