"""One writer per LanceDB dataset, enforced with an OS file lock.

LanceDB's MVCC keeps two concurrent commits from corrupting a table, but
not from interleaving: a second writer that commits between one writer's
merge and its ``corpus-version.json`` write leaves a marker that describes
neither, and a driver's run-level checks (the chunker-version refusal, the
end-of-run index build) stop holding once another writer is in between.
So every ingest write entry point holds an exclusive lock for the dataset
while it writes. The lock is taken without waiting: a run can last days,
and a second writer queued behind it would only surprise the operator, so
it fails at once with :class:`DatasetWriteLockedError` and the CLIs exit
with :data:`WRITE_LOCKED_EXIT_CODE`.

The lock file sits beside the dataset, ``<parent>/.<name>.write-lock``,
not inside it. A cutover renames dataset directories; a lock file inside
one would move with it while a writer still held it, and a second writer
would then lock a fresh file at the same path. The file is never removed,
for the same reason.

The lock is advisory and per host: it keeps out writers that take it, on
filesystems where ``flock`` locks are shared across processes. A write
that goes around it is caught after the fact by the write-audit gate in
:func:`arxmcp.corpus.store.write_chunks`.

Holding is reentrant within a thread, so a driver holds the lock for its
whole run and the writers it calls take it again without refusing
themselves. Another thread of the same process is refused like another
process.
"""

from __future__ import annotations

import contextlib
import functools
import inspect
import os
import socket
import sys
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

#: Exit code of an ingest CLI refused because another writer holds the
#: dataset. Distinct from 1 (a failed paper), 2 (argparse's usage error)
#: and 3 (the chunker-version refusal): the remedy is to wait, not to fix.
WRITE_LOCKED_EXIT_CODE = 4

_F = TypeVar("_F", bound=Callable[..., Any])


class DatasetWriteLockedError(RuntimeError):
    """Another writer holds the dataset's write lock; this call wrote nothing."""

    def __init__(self, lancedb_path: Path, lock_path: Path, holder: str) -> None:
        self.lancedb_path = lancedb_path
        self.lock_path = lock_path
        self.holder = holder
        super().__init__(
            f"another ingest is writing the dataset at {lancedb_path} "
            f"(held by {holder or 'an unidentified writer'}; lock file "
            f"{lock_path}). A dataset takes one writer at a time and this "
            "call wrote nothing. Wait for that run to finish, or stop it, "
            "then run this again."
        )


def write_lock_path(lancedb_path: str | Path) -> Path:
    """The lock file that serializes writers of the dataset at ``lancedb_path``."""
    path = Path(lancedb_path).resolve()
    return path.parent / f".{path.name}.write-lock"


@dataclass
class _Held:
    fd: int
    owner: int
    depth: int


_GUARD = threading.Lock()
_HELD: dict[str, _Held] = {}


if sys.platform == "win32":  # pragma: no cover - exercised on Windows only
    import msvcrt

    def _try_lock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise BlockingIOError(str(exc)) from exc

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


def _read_holder(lock_path: Path) -> str:
    try:
        return lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _describe_self() -> str:
    command = " ".join(Path(a).name if i == 0 else a for i, a in enumerate(sys.argv))
    return f"pid {os.getpid()} on {socket.gethostname()}: {command}"[:500]


@contextlib.contextmanager
def dataset_write_lock(lancedb_path: str | Path) -> Iterator[Path]:
    """Hold the dataset's write lock for the ``with`` body.

    Raises :class:`DatasetWriteLockedError` at once if another process, or
    another thread of this one, holds it. Yields the lock file's path.
    """
    lock_path = write_lock_path(lancedb_path)
    key = str(lock_path)
    me = threading.get_ident()
    with _GUARD:
        held = _HELD.get(key)
        if held is not None and held.owner != me:
            raise DatasetWriteLockedError(
                Path(lancedb_path), lock_path, _read_holder(lock_path)
            )
        if held is not None:
            held.depth += 1
    if held is not None:
        try:
            yield lock_path
        finally:
            with _GUARD:
                held.depth -= 1
        return

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        _try_lock(fd)
    except BlockingIOError:
        os.close(fd)
        raise DatasetWriteLockedError(
            Path(lancedb_path), lock_path, _read_holder(lock_path)
        ) from None
    except BaseException:
        os.close(fd)
        raise
    try:
        # Name the holder for the next writer's refusal. Best-effort: the
        # lock, not this text, is what keeps writers apart.
        with contextlib.suppress(OSError):
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, (_describe_self() + "\n").encode("utf-8"))
        with _GUARD:
            _HELD[key] = _Held(fd=fd, owner=me, depth=1)
        try:
            yield lock_path
        finally:
            with _GUARD:
                _HELD.pop(key, None)
    finally:
        try:
            _unlock(fd)
        finally:
            os.close(fd)


def holds_dataset_write_lock(
    path_param: str,
    *,
    skip_if: str | None = None,
    default: Callable[[], Path] | None = None,
) -> Callable[[_F], _F]:
    """Run the decorated writer under the lock of the dataset it writes.

    ``path_param`` names the parameter holding the dataset path. When it is
    ``None``, ``default()`` supplies the path the writer itself falls back
    to. A true ``skip_if`` parameter (a dry run) takes no lock.
    """

    def decorate(fn: _F) -> _F:
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            if skip_if is not None and bound.arguments[skip_if]:
                return fn(*args, **kwargs)
            path = bound.arguments[path_param]
            if path is None and default is not None:
                path = default()
            if path is None:
                raise ValueError(f"{fn.__qualname__}: {path_param} is required")
            with dataset_write_lock(path):
                return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorate


def exits_when_write_locked(cli: Callable[..., int]) -> Callable[..., int]:
    """Turn a write-lock refusal in an ingest CLI into its own exit code.

    A refusal, not a crash: one line on stderr, no traceback, and
    :data:`WRITE_LOCKED_EXIT_CODE` so a cron mailer or a supervisor can
    tell "another run has the dataset" from a failure.
    """

    @functools.wraps(cli)
    def wrapper(*args: Any, **kwargs: Any) -> int:
        try:
            return cli(*args, **kwargs)
        except DatasetWriteLockedError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return WRITE_LOCKED_EXIT_CODE

    return wrapper


__all__ = [
    "WRITE_LOCKED_EXIT_CODE",
    "DatasetWriteLockedError",
    "dataset_write_lock",
    "exits_when_write_locked",
    "holds_dataset_write_lock",
    "write_lock_path",
]
