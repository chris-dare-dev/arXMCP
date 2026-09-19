"""Sandboxed SymPy/CAS subprocess runner for the D-5 skeptic lane
(stage2/arx-d3 — WS-D; AC-D.10/AC-D.11).

Runs one counterexample-search check — Python source defining
``find_counterexample(**params)`` — inside an **isolated child
process** and returns a structured result envelope. The security
posture mirrors the repo's other subprocess sandboxes
(``server/lean_repl.py``, ``ingest/textbook_parser.py``):

- **Gated, default OFF.** ``ARXMCP_ENABLE_SKEPTIC_CAS`` (declared as
  :attr:`server.config.Config.enable_skeptic_cas`, mirroring the
  ``enable_lean`` precedent). With the flag off :func:`run_cas_check`
  **refuses**: it returns a ``status: "disabled"`` envelope and spawns
  nothing.
- **Subprocess isolation.** ``sys.executable -I`` (isolated mode: no
  user site-packages, ``PYTHON*`` env vars ignored, no cwd/script dir
  on ``sys.path``), a fresh temporary working directory, the spec
  passed over stdin (never argv), stderr captured not inherited.
- **Hard wall-clock timeout.** ``Popen.communicate(timeout=...)``;
  on expiry the child is ``kill()``-ed and reaped, and the envelope
  reports ``status: "timeout"``. As with the Lean REPL on Windows,
  the wall timeout is the primary backstop; a POSIX ``RLIMIT_AS``
  cap is applied on Linux only (the Darwin ``setrlimit`` bug —
  CLAUDE.md §8 #9 — and the Windows ``preexec_fn`` rejection both
  make the cap Linux-gated, matching ``ingest/textbook_parser.py``).
  Grandchildren spawned by check code are NOT reaped on kill — the
  accepted MinerU-class gap (CLAUDE.md §8 #10); check code is
  pipeline-authored, not arbitrary third-party input.
- **Structured, replayable envelope (AC-D.11).** Every envelope
  records the executed ``code``, the structured ``params``
  (seeds/ranges) and the ``timeout_s``, so any CAS result replays
  from the artifact alone.

This is a library, not an MCP tool: nothing here touches the
``tools/list`` surface (BP1-safe). If a future milestone exposes CAS
over MCP, the schema re-pin is a deliberate batched event (AC-D.11).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

#: The gate (default OFF). Declared on :class:`server.config.Config` as
#: ``enable_skeptic_cas`` so the server's unknown-``ARXMCP_*`` scan
#: accepts it; read directly from the environment here so the lane also
#: works in orchestrator/pipeline contexts with no server Config.
CAS_ENABLE_ENV_VAR = "ARXMCP_ENABLE_SKEPTIC_CAS"

#: Truthy spellings accepted for the env var (subset of pydantic's).
_TRUTHY = frozenset({"1", "true", "yes", "on"})

#: Default per-check wall-clock budget. CAS counterexample scans are
#: cheap by construction (bounded ranges); anything slower belongs in
#: a dedicated numerics lane with its own budget.
DEFAULT_CAS_TIMEOUT_S = 10.0

#: Hard ceiling on the per-check timeout a spec may request.
MAX_CAS_TIMEOUT_S = 120.0

#: Bound on the check source size (mirrors lean_verify's 16 KiB
#: snippet discipline, scaled for Python verbosity).
MAX_CODE_LEN = 64 * 1024

#: Kept tail length for child stdout/stderr in the envelope.
_TAIL_CHARS = 2000

#: POSIX (Linux-only) address-space cap for the child. Same 4 GiB
#: default as ``Config.lean_rlimit_as_bytes``.
DEFAULT_RLIMIT_AS_BYTES = 4 * 1024 * 1024 * 1024

#: Marker line prefix the child harness prints before its JSON result.
#: Check code may print freely to stdout without corrupting parsing —
#: the parent reads the LAST marker line.
_RESULT_MARKER = "__ARXMCP_CAS_RESULT__"

#: The child program (executed via ``python -I -c``). Reads the
#: ``{"code": ..., "params": ...}`` spec from stdin, executes the code,
#: calls ``find_counterexample(**params)`` and prints one marker-tagged
#: JSON line. Any exception — including a non-JSON-serializable witness
#: — becomes a structured ``error`` field, never a bare traceback exit.
_CHILD_HARNESS = """\
import json, sys
result = {"harness": "arxmcp-cas-v1", "child_python": sys.version.split()[0]}
try:
    spec = json.load(sys.stdin)
    ns = {}
    exec(compile(spec["code"], "<arxmcp-cas-check>", "exec"), ns)
    fn = ns.get("find_counterexample")
    if not callable(fn):
        raise RuntimeError("check code must define find_counterexample(**params)")
    witness = fn(**(spec.get("params") or {}))
    try:
        json.dumps(witness)
    except (TypeError, ValueError):
        raise RuntimeError(
            "find_counterexample returned a non-JSON-serializable witness: "
            + repr(witness)[:500]
        ) from None
    result["found"] = witness is not None
    result["witness"] = witness
except BaseException as exc:  # noqa: BLE001 - the envelope IS the error channel
    result["error"] = f"{type(exc).__name__}: {exc}"
sys.stdout.write("\\n" + "__ARXMCP_CAS_RESULT__" + " " + json.dumps(result) + "\\n")
"""


def cas_enabled(explicit: bool | None = None) -> bool:
    """Whether the CAS runner may execute (default OFF).

    ``explicit`` overrides the environment — callers holding a live
    :class:`server.config.Config` pass ``config.enable_skeptic_cas``;
    standalone pipeline callers pass ``None`` and the
    :data:`CAS_ENABLE_ENV_VAR` variable decides.
    """
    if explicit is not None:
        return bool(explicit)
    return os.environ.get(CAS_ENABLE_ENV_VAR, "").strip().lower() in _TRUTHY


@dataclass(frozen=True)
class CasCheckSpec:
    """One counterexample-search check.

    ``code`` must define ``find_counterexample(**params)`` returning a
    JSON-serializable witness (counterexample found) or ``None`` (no
    counterexample in the searched range). ``params`` carries the
    structured seeds/ranges (AC-D.11: recorded data, not embedded in
    the code, so the search space is auditable and replayable).

    ``discharges`` is the round-3 statement-linkage declaration (same
    shape as ``LeanCheckSpec.discharges``): which claim-derived
    proposition a CAS hit discharges. A CAS hit is evaluation-checked,
    not kernel-checked, so the verdict-linkage choke-point rests on the
    recorded declaration (``refutes_claim: true`` + a named
    proposition), and the ``known_truth`` / KAT escalation net backstops
    the sub-``high`` confidence. A CAS hit with no declaration is
    capped/escalated (fail-closed), never opened.
    """

    name: str
    code: str
    params: dict[str, Any] = field(default_factory=dict)
    timeout_s: float = DEFAULT_CAS_TIMEOUT_S
    description: str | None = None
    engine: str = "sympy"
    discharges: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ValueError("CasCheckSpec.name must be a non-empty string")
        if self.discharges is not None and not isinstance(self.discharges, dict):
            raise ValueError(
                f"check {self.name!r}: discharges must be an object when present"
            )
        if not self.code or not isinstance(self.code, str):
            raise ValueError(f"check {self.name!r}: code must be a non-empty string")
        if len(self.code) > MAX_CODE_LEN:
            raise ValueError(
                f"check {self.name!r}: code exceeds {MAX_CODE_LEN} bytes "
                f"(got {len(self.code)})"
            )
        if not isinstance(self.params, dict):
            raise ValueError(f"check {self.name!r}: params must be a dict")
        try:
            json.dumps(self.params)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"check {self.name!r}: params must be JSON-serializable "
                f"(seeds/ranges are recorded replay data, AC-D.11): {exc}"
            ) from exc
        if not (0 < float(self.timeout_s) <= MAX_CAS_TIMEOUT_S):
            raise ValueError(
                f"check {self.name!r}: timeout_s must be in "
                f"(0, {MAX_CAS_TIMEOUT_S}]; got {self.timeout_s}"
            )


def _envelope(spec: CasCheckSpec, **extra: Any) -> dict[str, Any]:
    """The structured result envelope. The replay floor (AC-D.11) —
    ``code`` + ``params`` + ``timeout_s`` — is present on EVERY path,
    including ``disabled``."""
    base: dict[str, Any] = {
        "engine": f"{spec.engine}-subprocess",
        "check": spec.name,
        "description": spec.description,
        "status": "error",
        "found": None,
        "witness": None,
        "detail": None,
        "code": spec.code,
        "params": dict(spec.params),
        "timeout_s": float(spec.timeout_s),
        "wall_clock_s": None,
        "exit_code": None,
        "stdout_tail": None,
        "stderr_tail": None,
        "python_executable": None,
        "child_python": None,
        "started_at": datetime.now(UTC).isoformat(),
    }
    base.update(extra)
    return base


def _tail(text: str | None) -> str | None:
    if not text:
        return None
    return text[-_TAIL_CHARS:]


def run_cas_check(
    spec: CasCheckSpec,
    *,
    enabled: bool | None = None,
    python_executable: str | None = None,
    rlimit_as_bytes: int | None = DEFAULT_RLIMIT_AS_BYTES,
) -> dict[str, Any]:
    """Execute one CAS check in the sandboxed subprocess.

    Returns the structured envelope; never raises for check-level
    failures (timeout, crash, bad output) — those are ``status``
    values. Statuses:

    - ``"disabled"`` — the gate is off; **nothing was executed**.
    - ``"ok"`` — the harness ran to completion; ``found``/``witness``
      are authoritative.
    - ``"timeout"`` — the wall clock fired; the child was killed and
      reaped (``exit_code`` records the kill).
    - ``"error"`` — the child failed (check exception, missing
      ``find_counterexample``, unserializable witness, spawn failure,
      missing result marker); ``detail`` says why.
    """
    if not cas_enabled(enabled):
        logger.info(
            "cas_runner: check %r refused — %s is not set (default OFF)",
            spec.name,
            CAS_ENABLE_ENV_VAR,
        )
        return _envelope(
            spec,
            status="disabled",
            detail=(
                f"CAS runner disabled ({CAS_ENABLE_ENV_VAR} unset/false); "
                "no subprocess was spawned"
            ),
        )

    python = python_executable or sys.executable
    cmd = [python, "-I", "-c", _CHILD_HARNESS]
    payload = json.dumps({"code": spec.code, "params": spec.params})

    popen_kwargs: dict[str, Any] = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    # Linux-only RLIMIT_AS cap — the same gating as
    # ingest/textbook_parser.py: Darwin's setrlimit is broken
    # (CLAUDE.md §8 #9) and Windows rejects preexec_fn outright.
    if rlimit_as_bytes and rlimit_as_bytes > 0 and sys.platform == "linux":
        import resource as _resource  # noqa: PLC0415 - POSIX-only module

        cap = int(rlimit_as_bytes)

        def _apply_rlimit() -> None:  # pragma: no cover - Linux-only
            _resource.setrlimit(_resource.RLIMIT_AS, (cap, cap))

        popen_kwargs["preexec_fn"] = _apply_rlimit

    tmpdir = tempfile.mkdtemp(prefix="arxmcp-cas-")
    started = time.monotonic()
    try:
        try:
            proc = subprocess.Popen(cmd, cwd=tmpdir, **popen_kwargs)  # noqa: S603
        except OSError as exc:
            return _envelope(
                spec,
                status="error",
                detail=f"failed to spawn the CAS subprocess: {exc}",
                python_executable=python,
            )
        try:
            stdout, stderr = proc.communicate(payload, timeout=spec.timeout_s)
        except subprocess.TimeoutExpired:
            # Hard timeout: kill + reap. kill() == TerminateProcess on
            # Windows; the follow-up communicate() reaps so no zombie /
            # leaked handle survives (the LeanRepl.close discipline).
            proc.kill()
            stdout, stderr = proc.communicate()
            wall = time.monotonic() - started
            logger.warning(
                "cas_runner: check %r exceeded %.1fs — child killed "
                "(pid=%s, exit_code=%s)",
                spec.name,
                spec.timeout_s,
                proc.pid,
                proc.returncode,
            )
            return _envelope(
                spec,
                status="timeout",
                detail=(
                    f"check exceeded the {spec.timeout_s:.1f}s wall-clock "
                    "timeout; the subprocess was killed"
                ),
                wall_clock_s=wall,
                exit_code=proc.returncode,
                stdout_tail=_tail(stdout),
                stderr_tail=_tail(stderr),
                python_executable=python,
            )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    wall = time.monotonic() - started
    common: dict[str, Any] = {
        "wall_clock_s": wall,
        "exit_code": proc.returncode,
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
        "python_executable": python,
    }

    # Parse the LAST marker line (check code may print freely).
    marker_payload: str | None = None
    for line in (stdout or "").splitlines():
        if line.startswith(_RESULT_MARKER):
            marker_payload = line[len(_RESULT_MARKER) :].strip()
    if marker_payload is None:
        return _envelope(
            spec,
            status="error",
            detail=(
                "child produced no result marker "
                f"(exit_code={proc.returncode}); the harness itself failed"
            ),
            **common,
        )
    try:
        child_result = json.loads(marker_payload)
    except json.JSONDecodeError as exc:
        return _envelope(
            spec,
            status="error",
            detail=f"child result marker carried invalid JSON: {exc}",
            **common,
        )

    common["child_python"] = child_result.get("child_python")
    if "error" in child_result:
        return _envelope(
            spec,
            status="error",
            detail=str(child_result["error"]),
            **common,
        )
    return _envelope(
        spec,
        status="ok",
        found=bool(child_result.get("found")),
        witness=child_result.get("witness"),
        **common,
    )


__all__ = [
    "CAS_ENABLE_ENV_VAR",
    "DEFAULT_CAS_TIMEOUT_S",
    "DEFAULT_RLIMIT_AS_BYTES",
    "MAX_CAS_TIMEOUT_S",
    "MAX_CODE_LEN",
    "CasCheckSpec",
    "cas_enabled",
    "run_cas_check",
]
