"""Sandboxed MinerU subprocess driver (textbook-ingest-m5).

Implements the layer-2 defense from
``.claude/docs/security-pdf-sandbox.md``: a subprocess sandbox profile
for MinerU 3.x's pipeline backend, invoked via CLI form.

Layer-1 (upload-side pre-flight) is in ``server/routes/notebooks.py``
(m4); layer-3 (per-notebook LanceDB blast-radius) was validated by
spike-3 (``tests/test_textbook_notebook_isolation.py``).

The driver is **purely local**: no network egress, no MCP-surface
change. Consumed in m6 (LaTeXML re-render + upload-route wiring).

Cross-references
----------------
- ``.claude/docs/security-pdf-sandbox.md`` — prescriptive contract
- ``tools/cdm_eval.py::_run_subprocess_with_pgkill`` — closest peer
- ``server/lean_repl.py::spawn`` — RLIMIT_AS precedent (also has the
  macOS gap this driver explicitly addresses)
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sandbox constants — load-bearing per security-pdf-sandbox.md
# ---------------------------------------------------------------------------

#: Virtual-memory ceiling for the MinerU subprocess. 4 GB is ~2x the
#: nominal working set on a 500-page textbook (measured offline in B1);
#: leaves room for transformer attention spikes without admitting
#: decompression-bomb scenarios. Linux-only — see _RLIMIT_AS_PLATFORM.
_MINERU_RLIMIT_AS_BYTES: int = 4 * 1024 * 1024 * 1024  # 4 GB

#: Default wall-clock cap. 30 min covers Bourbaki-grade textbooks on
#: M2-class hardware (~1-3 pages/sec). Configurable via
#: ARXMCP_MINERU_TIMEOUT_S env var at module load (60–3600 inclusive).
_DEFAULT_TIMEOUT_S: int = 30 * 60

#: Bounds on the configurable timeout (inclusive).
_TIMEOUT_MIN_S: int = 60
_TIMEOUT_MAX_S: int = 3600

#: Tail-truncation budget for captured stdout/stderr. 8 KB is enough
#: for failure-relevant diagnostics; the full stream would be multi-MB
#: from MinerU's per-page progress logging.
_OUTPUT_TAIL_BYTES: int = 8 * 1024

#: Whitelist of environment variables passed through to the MinerU
#: subprocess. TMPDIR is explicitly OVERRIDDEN to output_dir (not
#: inherited) per research-synthesis §D4 — prevents cross-notebook
#: TMPDIR contamination. HOME stays so MinerU can find its
#: ~/.cache/mineru/ ONNX weights.
_ENV_WHITELIST: frozenset[str] = frozenset({
    "PATH", "HOME", "LANG", "LC_ALL",
})

#: Grace period when draining PIPE buffers after a process-group kill.
#: Prevents the second-communicate deadlock trap documented in
#: cdm_eval.py::_run_subprocess_with_pgkill.
_DRAIN_TIMEOUT_S: int = 5

#: Platform on which RLIMIT_AS is enforceable. Verified live test on
#: Darwin 25.4.0 / Apple M4 Max: setrlimit(RLIMIT_AS, (4GB, 4GB)) raises
#: ValueError because the macOS kernel keeps the hard limit at
#: RLIM_INFINITY and refuses lowering. See CLAUDE.md §8 landmine.
_RLIMIT_AS_PLATFORM: str = "linux"


# ---------------------------------------------------------------------------
# Module-load configuration parse
# ---------------------------------------------------------------------------


def _parse_timeout_from_env() -> int:
    """Resolve the wall-clock timeout from ``ARXMCP_MINERU_TIMEOUT_S``.

    Validates at module-load time per AC: reject non-integer or
    out-of-[_TIMEOUT_MIN_S, _TIMEOUT_MAX_S] with an explicit
    RuntimeError, NOT a silent clamp. Empty / unset uses the default.
    """
    raw = os.environ.get("ARXMCP_MINERU_TIMEOUT_S", "").strip()
    if not raw:
        return _DEFAULT_TIMEOUT_S
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"ARXMCP_MINERU_TIMEOUT_S={raw!r} is not a valid integer; "
            f"set to a value in [{_TIMEOUT_MIN_S}, {_TIMEOUT_MAX_S}] "
            f"seconds or leave unset to use the default "
            f"({_DEFAULT_TIMEOUT_S}s)."
        ) from exc
    if value < _TIMEOUT_MIN_S or value > _TIMEOUT_MAX_S:
        raise RuntimeError(
            f"ARXMCP_MINERU_TIMEOUT_S={value} is out of range "
            f"[{_TIMEOUT_MIN_S}, {_TIMEOUT_MAX_S}]. Refusing to silently "
            f"clamp; set a value in range or leave unset."
        )
    return value


#: Resolved at import time so config errors surface at server-startup,
#: not at first PDF upload.
_CONFIGURED_TIMEOUT_S: int = _parse_timeout_from_env()


# ---------------------------------------------------------------------------
# Platform-specific RLIMIT setup
# ---------------------------------------------------------------------------

if sys.platform == _RLIMIT_AS_PLATFORM:
    import resource as _resource

    def _set_mineru_rlimits() -> None:
        """preexec_fn for subprocess.Popen. Caps virtual memory.

        Linux-only. Runs in the child between fork() and exec() so
        the limit is inherited by every descendant MinerU spawns.
        """
        _resource.setrlimit(
            _resource.RLIMIT_AS,
            (_MINERU_RLIMIT_AS_BYTES, _MINERU_RLIMIT_AS_BYTES),
        )
else:
    _resource = None  # type: ignore[assignment]
    _set_mineru_rlimits = None  # type: ignore[assignment]
    logger.warning(
        "textbook_parser: RLIMIT_AS cap not enforceable on platform "
        "%r; the %ds wall timeout is the only memory backstop. "
        "Verified macOS gap — see CLAUDE.md §8.",
        sys.platform, _CONFIGURED_TIMEOUT_S,
    )


# ---------------------------------------------------------------------------
# Binary resolution
# ---------------------------------------------------------------------------


def _resolve_mineru_binary() -> str:
    """Return absolute path to the ``mineru`` CLI binary.

    Resolution order (per research-synthesis §Decision 1):
    1. ``ARXMCP_MINERU_BIN`` env var (absolute path; verified to exist).
    2. ``shutil.which("mineru")`` — typically empty unless mineru was
       pip-installed into the project venv (B1 used a separate venv).
    3. RuntimeError with a clear install message.

    Raised at call time, not module load — module imports must work
    without MinerU installed (unit tests mock the subprocess).
    """
    env_path = os.environ.get("ARXMCP_MINERU_BIN", "").strip()
    if env_path:
        if not Path(env_path).is_file():
            raise RuntimeError(
                f"ARXMCP_MINERU_BIN={env_path!r} is set but the path "
                f"does not point to a file. Set to the absolute path "
                f"of the mineru binary (e.g. ~/venvs/mineru/bin/mineru)."
            )
        return env_path
    which_path = shutil.which("mineru")
    if which_path:
        return which_path
    raise RuntimeError(
        "mineru binary not found. Install MinerU (typically into a "
        "dedicated venv: `uv venv ~/venvs/mineru && uv pip install "
        "--python ~/venvs/mineru/bin/python 'mineru[pipeline,mlx]'`) "
        "and set ARXMCP_MINERU_BIN to its absolute path, e.g. "
        "`export ARXMCP_MINERU_BIN=~/venvs/mineru/bin/mineru`."
    )


# ---------------------------------------------------------------------------
# Env scrubbing
# ---------------------------------------------------------------------------


def _scrub_subprocess_env(output_dir: Path) -> dict[str, str]:
    """Return a minimal env for the MinerU subprocess.

    Whitelist passes through PATH, HOME, LANG, LC_ALL from the parent
    process. TMPDIR is OVERRIDDEN to ``str(output_dir)`` rather than
    inherited — research-synthesis §D4 (FM-8) — preventing scratch
    files from landing in another notebook's tree.

    Strips proxies, AWS / GCP / Azure / HuggingFace credentials,
    anything that could enable network egress or credential leak.
    """
    env: dict[str, str] = {}
    for key in _ENV_WHITELIST:
        if key in os.environ:
            env[key] = os.environ[key]
    # Always override TMPDIR to the per-invocation output_dir.
    env["TMPDIR"] = str(output_dir)
    return env


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class MinerUResult:
    """Frozen result of a sandboxed MinerU invocation.

    ``markdown_path`` and ``content_list_path`` resolve to existing
    files under ``output_dir`` after the subprocess exits 0; consumers
    (m6's LaTeXML re-render) work from these paths.

    ``stdout`` and ``stderr`` are tail-truncated to the last 8 KB
    (_OUTPUT_TAIL_BYTES); the full streams are NOT retained.
    """
    output_dir: Path
    markdown_path: Path
    content_list_path: Path
    stdout: str
    stderr: str
    wall_clock_s: float


# ---------------------------------------------------------------------------
# Public driver
# ---------------------------------------------------------------------------


def _tail(s: str, n: int = _OUTPUT_TAIL_BYTES) -> str:
    """Return the last n bytes (UTF-8) of s, decoded back to str."""
    if not s:
        return s
    encoded = s.encode("utf-8", errors="replace")
    if len(encoded) <= n:
        return s
    return encoded[-n:].decode("utf-8", errors="replace")


def _locate_outputs(output_dir: Path, pdf_stem: str) -> tuple[Path, Path]:
    """Find the markdown + content_list.json that MinerU produced.

    MinerU 3.2.0 with ``-b pipeline -m auto`` produces:
        output_dir/<pdf_stem>/auto/<pdf_stem>.md
        output_dir/<pdf_stem>/auto/<pdf_stem>_content_list.json

    Per research-synthesis §D3: probe the documented path first,
    fall back to a glob, raise RuntimeError if no markdown found
    (FM-4 mitigation).

    The fallback ONLY accepts md+content_list pairs that share a
    parent directory — never pairs files from different parse
    subdirectories. Closes m5 adversary F4.
    """
    direct_md = output_dir / pdf_stem / "auto" / f"{pdf_stem}.md"
    direct_cl = (
        output_dir / pdf_stem / "auto" / f"{pdf_stem}_content_list.json"
    )
    if direct_md.is_file() and direct_cl.is_file():
        return direct_md, direct_cl

    md_candidates = sorted(output_dir.rglob("*.md"))
    if not md_candidates:
        listing = sorted(p.relative_to(output_dir) for p in output_dir.rglob("*"))
        raise RuntimeError(
            f"MinerU exited 0 but no .md file found under "
            f"{output_dir!s}. Directory contents: {listing!r}. The "
            f"MinerU output-tree convention may have changed; see "
            f"research-synthesis §D3 (FM-4)."
        )
    # Closes m5 F4: pair-match in same parent dir, do not cross-pair.
    for md in md_candidates:
        cl = md.with_name(f"{md.stem}_content_list.json")
        if cl.is_file():
            return md, cl
    raise RuntimeError(
        f"MinerU exited 0 and produced markdown candidates "
        f"({[str(p.relative_to(output_dir)) for p in md_candidates]!r}) "
        f"but no paired _content_list.json in the same parent dir for "
        f"any of them. Output tree partial — m6 cannot consume."
    )


def run_mineru_sandboxed(
    pdf_path: Path,
    output_dir: Path,
    *,
    timeout_s: int | None = None,
) -> MinerUResult:
    """Run MinerU 3.2.0 on a PDF with the textbook-ingest e2 sandbox.

    Three defense layers active inside this function:
    - RLIMIT_AS 4 GB cap via preexec_fn (Linux only — see _resource).
    - Wall timeout + process-group kill on expiry.
    - Scrubbed env (no proxies, no credentials, TMPDIR confined).

    The grandchild FastAPI server gap from MinerU 3.x is documented in
    .claude/docs/security-pdf-sandbox.md §"explicitly does NOT do" —
    loopback-only, accepted gap.

    Parameters
    ----------
    pdf_path
        PDF on disk. Caller is responsible for the layer-1 pre-flight
        gate (server/routes/notebooks.py::_run_pdf_preflight).
    output_dir
        Per-invocation tmpdir (typically under
        var/arxmcp/notebooks/<slug>/parsed/<paper_id>/). The subprocess
        cwd is set here and TMPDIR is overridden to match.
    timeout_s
        Override the module-configured timeout. Must be in
        [_TIMEOUT_MIN_S, _TIMEOUT_MAX_S]; out-of-range raises
        RuntimeError. None = use module-load value
        (_CONFIGURED_TIMEOUT_S).

    Raises
    ------
    RuntimeError
        - Binary missing (clearer message than FileNotFoundError).
        - Out-of-range timeout.
        - Subprocess exits nonzero (with stderr tail in message).
        - Output tree missing markdown or content_list (FM-4).
    subprocess.TimeoutExpired
        Wall timeout fired and process-group was killed.
    """
    if not pdf_path.is_file():
        raise RuntimeError(f"pdf_path is not a file: {pdf_path!s}")
    if not output_dir.is_dir():
        raise RuntimeError(f"output_dir is not a directory: {output_dir!s}")

    effective_timeout = _CONFIGURED_TIMEOUT_S if timeout_s is None else int(timeout_s)
    if effective_timeout < _TIMEOUT_MIN_S or effective_timeout > _TIMEOUT_MAX_S:
        raise RuntimeError(
            f"timeout_s={effective_timeout} is out of range "
            f"[{_TIMEOUT_MIN_S}, {_TIMEOUT_MAX_S}]."
        )

    mineru_bin = _resolve_mineru_binary()
    sandbox_env = _scrub_subprocess_env(output_dir)
    cmd: list[str] = [
        mineru_bin,
        "-p", str(pdf_path),
        "-o", str(output_dir),
        "-b", "pipeline",
        "-m", "auto",
    ]

    spawn_kwargs: dict[str, object] = {}
    if _set_mineru_rlimits is not None:
        spawn_kwargs["preexec_fn"] = _set_mineru_rlimits

    logger.info(
        "textbook_parser: invoking mineru pid-soon (bin=%s, pdf=%s, "
        "output_dir=%s, timeout=%ds, rlimit_as=%s)",
        mineru_bin, pdf_path.name, output_dir, effective_timeout,
        "linux-4GB" if "preexec_fn" in spawn_kwargs else "disabled",
    )

    started = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        cwd=str(output_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env=sandbox_env,
        **spawn_kwargs,  # type: ignore[arg-type]
    )
    try:
        stdout, stderr = proc.communicate(timeout=effective_timeout)
    except subprocess.TimeoutExpired:
        # Kill the process group; MinerU 3.x's grandchild FastAPI
        # service may survive (see security-pdf-sandbox.md). Drain
        # the PIPEs to avoid deadlock during cleanup. Capture the
        # drain output and surface in the WARN log — closes m5 F5
        # (timeout-path observability gap).
        with contextlib.suppress(ProcessLookupError, OSError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        drained_stderr: str = ""
        with contextlib.suppress(subprocess.TimeoutExpired):
            drained = proc.communicate(timeout=_DRAIN_TIMEOUT_S)
            drained_stderr = drained[1] or ""
        logger.warning(
            "textbook_parser: mineru exceeded %ds wall timeout for "
            "%s; killed pgid=%s; drain stderr tail: %s",
            effective_timeout, pdf_path.name, proc.pid,
            _tail(drained_stderr, 1024),
        )
        raise

    wall_clock_s = time.monotonic() - started

    if proc.returncode != 0:
        raise RuntimeError(
            f"mineru exited {proc.returncode} on {pdf_path.name}: "
            f"{_tail(stderr or '', 500)}"
        )

    markdown_path, content_list_path = _locate_outputs(
        output_dir, pdf_path.stem,
    )

    logger.info(
        "textbook_parser: mineru ok (pdf=%s, wall=%.2fs, "
        "md=%s)",
        pdf_path.name, wall_clock_s,
        markdown_path.relative_to(output_dir),
    )

    return MinerUResult(
        output_dir=output_dir,
        markdown_path=markdown_path,
        content_list_path=content_list_path,
        stdout=_tail(stdout or ""),
        stderr=_tail(stderr or ""),
        wall_clock_s=wall_clock_s,
    )
