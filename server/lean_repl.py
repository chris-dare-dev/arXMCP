"""Managed Lean 4 REPL subprocess harness (verification-feedback-m2).

A :class:`LeanRepl` wraps `leanprover-community/repl` — driven over
stdin/stdout JSON as an ``asyncio`` subprocess — into a managed,
event-loop-friendly handle. It is the *harness* the m3 ``lean_verify``
MCP tool will sit on top of: m2 ships the harness (spawn / query /
close); **no MCP tool is added in m2** (that is intentional and
deliberate — ``lean_verify`` is m3).

Lifecycle: gated by ``ARXMCP_ENABLE_LEAN`` (default off). When enabled,
:meth:`server.resources.Resources.startup` spawns exactly one
``LeanRepl`` and :meth:`Resources.shutdown` closes it. The flag-off
path spawns nothing and leaves the 7 existing MCP tools untouched.

Design references:
- ``.claude/notes/spikes/verification-feedback-spike-2.md`` — the spike
  that installed Lean 4 + built the repl and validated this exact
  asyncio-subprocess approach (sub-second round-trips; the absolute-
  ``lake``-path requirement on Windows).
- ``.claude/docs/lean-sandbox-design.md`` — the sandbox sub-design
  (per-query timeout, filesystem isolation, stderr discipline).

Sandbox discipline implemented here: every :meth:`query` round-trip is
wrapped in ``asyncio.wait_for`` (the Lean REPL has no built-in
per-command timeout); ``stderr`` is routed to ``DEVNULL`` so a large
diagnostic write cannot fill an OS pipe buffer and deadlock the
subprocess; round-trips are serialised by an internal lock because the
single REPL process has one stdin/stdout stream.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from server.resources import ResourceStartupError

# verification-feedback-m3 — RLIMIT_AS sandbox cap. The ``resource``
# module is POSIX-only; on Windows the import fails. ``LeanRepl.spawn``
# additionally guards on ``sys.platform != "win32"`` because
# ``asyncio.create_subprocess_exec`` raises ``ValueError`` on Windows
# whenever ``preexec_fn`` is set, even with the module imported.
try:
    import resource as _resource
except ImportError:  # pragma: no cover — Windows path exercised in CI
    _resource = None

if TYPE_CHECKING:
    from server.config import Config

logger = logging.getLogger(__name__)

#: Default per-:meth:`LeanRepl.query` wall-clock timeout (seconds). The
#: Lean REPL has no built-in per-command timeout — this is the
#: implemented sandbox guard against a runaway elaboration (see
#: ``.claude/docs/lean-sandbox-design.md``). The spike measured
#: sub-second round-trips for simple snippets; 30 s is generous.
DEFAULT_QUERY_TIMEOUT_S = 30.0

#: Grace period for a clean subprocess ``terminate()`` before the
#: :meth:`LeanRepl.close` path escalates to ``kill()``.
_CLOSE_GRACE_S = 5.0


class LeanUnavailableError(ResourceStartupError):
    """Raised when ``ARXMCP_ENABLE_LEAN=true`` but the Lean toolchain
    cannot be resolved (``lake_path`` / ``lean_repl_dir`` unset or
    unusable, or the subprocess fails to spawn).

    Subclasses :class:`server.resources.ResourceStartupError`: a
    startup-time failure that must refuse to open ``/readyz``. This
    mirrors :class:`server.resources.RerankerUnavailableError` exactly —
    "trust the operator's choice; refuse to start" rather than silently
    degrading.
    """


class LeanReplError(RuntimeError):
    """Raised for a *runtime* failure of an already-spawned REPL — a
    query timeout, the subprocess having exited, or a malformed
    response. Distinct from :class:`LeanUnavailableError` (a
    startup-time failure)."""


class LeanReplTimeoutError(LeanReplError):
    """The per-:meth:`LeanRepl.query` wall-clock timeout fired —
    a runaway elaboration. The subprocess is NOT killed by the raise;
    callers (the lean_verify handler) MUST close + respawn so the
    next query does not read stale stdout from the wedged elaboration.

    A distinct subclass so handlers can ``except LeanReplTimeoutError``
    without resorting to substring-matching on the error message (m3
    critique F3).
    """


class LeanRepl:
    """A managed, single-process Lean 4 REPL subprocess.

    Construct via :meth:`spawn` or :meth:`spawn_from_config`; tear down
    via :meth:`close`. :meth:`query` performs one JSON command/response
    round-trip; concurrent ``query`` calls are serialised internally
    (the process has one stdin/stdout stream).
    """

    def __init__(
        self,
        proc: asyncio.subprocess.Process,
        lake_path: Path,
        repl_dir: Path,
    ) -> None:
        self._proc = proc
        self._lake_path = lake_path
        self._repl_dir = repl_dir
        # One REPL process, one stdin/stdout stream: serialise
        # round-trips so two concurrent queries cannot interleave their
        # JSON on the wire.
        self._io_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    async def spawn(
        cls,
        *,
        lake_path: str | Path,
        repl_dir: str | Path,
        rlimit_as_bytes: int | None = None,
    ) -> LeanRepl:
        """Spawn ``lake exe repl`` as a non-blocking asyncio subprocess.

        ``lake_path`` MUST be the absolute path to the ``lake`` binary
        (``asyncio.create_subprocess_exec`` does not PATH-search a bare
        name on Windows — spike-2 finding #1). ``repl_dir`` is the built
        ``leanprover-community/repl`` package directory and becomes the
        subprocess ``cwd`` so ``lake`` resolves ``LEAN_PATH`` for it.

        ``rlimit_as_bytes`` (verification-feedback-m3 — m2 critique F4
        carry-forward) caps the subprocess address-space via POSIX
        ``RLIMIT_AS`` in a ``preexec_fn``. ``None`` or ``0`` disables the
        cap. On Windows the cap is silently skipped — the platform has
        no ``RLIMIT_AS`` analogue and ``preexec_fn`` is rejected by
        ``asyncio.create_subprocess_exec``; the 30 s per-query timeout
        remains the only memory backstop there (deferred to a Job-Object
        follow-up; ``.claude/docs/lean-sandbox-design.md``).

        Raises :class:`LeanUnavailableError` if either path is missing
        or the subprocess cannot be started.
        """
        lake = Path(lake_path)
        rd = Path(repl_dir)
        if not lake.is_file():
            raise LeanUnavailableError(
                f"lake binary not found at {lake!s}; set ARXMCP_LAKE_PATH "
                f"to the absolute path of the lake executable."
            )
        if not rd.is_dir():
            raise LeanUnavailableError(
                f"Lean REPL package directory not found at {rd!s}; set "
                f"ARXMCP_LEAN_REPL_DIR to a built leanprover-community/repl "
                f"directory (run `lake build` in it first)."
            )

        # POSIX-only RLIMIT_AS preexec_fn (m3 — closes m2 critique F4).
        # Build the kwargs dict so the Windows path passes no
        # ``preexec_fn`` argument at all (the constructor rejects even
        # ``preexec_fn=None`` on some versions / is documented as
        # POSIX-only).
        spawn_kwargs: dict[str, Any] = {}
        if (
            rlimit_as_bytes
            and rlimit_as_bytes > 0
            and sys.platform != "win32"
            and _resource is not None
        ):
            cap = int(rlimit_as_bytes)
            rlimit_as_const = _resource.RLIMIT_AS

            def _apply_rlimit_as() -> None:  # runs in the child after fork()
                _resource.setrlimit(rlimit_as_const, (cap, cap))

            spawn_kwargs["preexec_fn"] = _apply_rlimit_as
        elif rlimit_as_bytes and sys.platform == "win32":
            logger.warning(
                "LeanRepl: RLIMIT_AS (%d bytes) requested but Windows has "
                "no equivalent; the 30 s per-query timeout is the only "
                "memory backstop. See .claude/docs/lean-sandbox-design.md.",
                rlimit_as_bytes,
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                str(lake),
                "exe",
                "repl",
                cwd=str(rd),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                # stderr -> DEVNULL: Lean stderr is diagnostic, not
                # protocol. Discarding it removes the pipe-buffer
                # deadlock trap (a large stderr write blocking the
                # subprocess while the parent only reads stdout).
                stderr=asyncio.subprocess.DEVNULL,
                **spawn_kwargs,
            )
        except (OSError, ValueError) as exc:
            raise LeanUnavailableError(
                f"failed to spawn the Lean REPL ({lake!s} exe repl, "
                f"cwd={rd!s}): {exc}"
            ) from exc
        logger.info(
            "LeanRepl: spawned `lake exe repl` (pid=%s, cwd=%s, rlimit_as=%s)",
            proc.pid,
            rd,
            (
                f"{rlimit_as_bytes} bytes (POSIX)"
                if "preexec_fn" in spawn_kwargs
                else "disabled"
            ),
        )
        return cls(proc, lake, rd)

    @classmethod
    async def spawn_from_config(cls, config: Config) -> LeanRepl:
        """Spawn from :attr:`Config.lake_path` + :attr:`Config.lean_repl_dir`.

        Raises :class:`LeanUnavailableError` if either is unset — the
        ``enable_lean=True`` contract requires both.
        """
        if config.lake_path is None or config.lean_repl_dir is None:
            raise LeanUnavailableError(
                "ARXMCP_ENABLE_LEAN=true requires both ARXMCP_LAKE_PATH "
                "and ARXMCP_LEAN_REPL_DIR to be set; got "
                f"lake_path={config.lake_path!r}, "
                f"lean_repl_dir={config.lean_repl_dir!r}. Either set both "
                "or leave ARXMCP_ENABLE_LEAN unset (default)."
            )
        return await cls.spawn(
            lake_path=config.lake_path,
            repl_dir=config.lean_repl_dir,
            rlimit_as_bytes=config.lean_rlimit_as_bytes,
        )

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """True while the REPL subprocess has not exited."""
        return self._proc.returncode is None

    async def query(
        self,
        command: dict[str, Any],
        *,
        timeout: float = DEFAULT_QUERY_TIMEOUT_S,
    ) -> dict[str, Any]:
        """Send one JSON ``command`` to the REPL, return the parsed JSON
        response.

        The round-trip is wrapped in ``asyncio.wait_for(timeout)`` — the
        sandbox per-query guard against a runaway elaboration — and
        serialised against other ``query`` calls.

        Raises :class:`LeanReplError` if the process has exited, the
        timeout fires, or the response is not valid JSON.
        """
        async with self._io_lock:
            if self._proc.returncode is not None:
                raise LeanReplError(
                    f"Lean REPL process has exited "
                    f"(returncode={self._proc.returncode}); cannot query."
                )
            try:
                return await asyncio.wait_for(
                    self._round_trip(command), timeout=timeout
                )
            except TimeoutError as exc:
                # LeanReplTimeoutError subclasses LeanReplError so existing
                # ``except LeanReplError`` handlers still catch it; the
                # subclass exists so the lean_verify handler can route the
                # timeout path WITHOUT substring-matching on the message
                # (m3 critique F3).
                raise LeanReplTimeoutError(
                    f"Lean REPL query exceeded the {timeout}s timeout."
                ) from exc

    async def _round_trip(self, command: dict[str, Any]) -> dict[str, Any]:
        """Write one command, read one JSON-block response.

        Protocol (spike-2): a JSON object then a blank line on stdin;
        the response is a JSON object terminated by a blank line on
        stdout.
        """
        stdin = self._proc.stdin
        stdout = self._proc.stdout
        if stdin is None or stdout is None:
            # Never happens — spawn() always uses PIPE — but the
            # project bans bare `assert` for invariants (CLAUDE.md §4.7).
            raise LeanReplError("Lean REPL subprocess has no stdin/stdout pipe.")

        stdin.write((json.dumps(command) + "\n\n").encode("utf-8"))
        await stdin.drain()

        lines: list[str] = []
        while True:
            raw = await stdout.readline()
            if not raw:  # EOF — the subprocess closed stdout / exited.
                raise LeanReplError(
                    "Lean REPL closed stdout before returning a response "
                    "(the subprocess likely crashed)."
                )
            text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if text == "":
                if lines:  # blank line after content == end of block.
                    break
                continue  # leading blank line — skip.
            lines.append(text)
            # Return as soon as the accumulated buffer is a complete JSON
            # object — do NOT depend on the trailing blank line alone.
            # The REPL build validated by spike-2 does emit the
            # blank-line terminator, but relying on it exclusively means
            # a repl build that omits it turns every query into a 30 s
            # `asyncio.wait_for` timeout hang (m2 critique F3). An early
            # successful parse is the robust framing signal; the
            # blank-line break below is the fallback for a buffer that
            # is not yet (or never) valid JSON.
            try:
                return json.loads("\n".join(lines))
            except json.JSONDecodeError:
                continue  # incomplete JSON — keep accumulating lines.
        # Reached only on a blank-line terminator whose preceding buffer
        # never parsed as JSON — surface the decode error, do not hang.
        try:
            return json.loads("\n".join(lines))
        except json.JSONDecodeError as exc:
            raise LeanReplError(
                f"Lean REPL returned a non-JSON response: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Terminate the REPL subprocess and reap it.

        ``terminate()`` then ``await wait()`` (bounded by
        :data:`_CLOSE_GRACE_S`); escalates to ``kill()`` if the process
        does not exit within the grace period. Reaping (``wait()``) is
        mandatory — skipping it leaves a zombie (POSIX) / leaked handle
        (Windows). Idempotent and exception-safe; safe to call from a
        lifespan ``finally`` block.
        """
        if self._proc.returncode is not None:
            return  # already exited and reaped.
        try:
            self._proc.terminate()
        except ProcessLookupError:
            return  # raced with natural exit.
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=_CLOSE_GRACE_S)
        except TimeoutError:
            logger.warning(
                "LeanRepl: process did not exit within %.0fs of terminate(); "
                "escalating to kill()",
                _CLOSE_GRACE_S,
            )
            try:
                self._proc.kill()
            except ProcessLookupError:
                return
            # Bound the post-kill() reap too (m2 critique F5). SIGKILL
            # is uninterceptable, so a wedged parent-side transport — not
            # the child — is the only way `wait()` can stall here; an
            # unbounded `await` would hang `close()` (hence the whole
            # lifespan shutdown drain) on that edge case.
            try:
                await asyncio.wait_for(
                    self._proc.wait(), timeout=_CLOSE_GRACE_S
                )
            except TimeoutError:
                logger.warning(
                    "LeanRepl: process did not exit within %.0fs of "
                    "kill(); abandoning the reap (handle may leak)",
                    _CLOSE_GRACE_S,
                )
                return
        logger.info("LeanRepl: subprocess closed (returncode=%s)", self._proc.returncode)


__all__ = [
    "DEFAULT_QUERY_TIMEOUT_S",
    "LeanRepl",
    "LeanReplError",
    "LeanReplTimeoutError",
    "LeanUnavailableError",
]
