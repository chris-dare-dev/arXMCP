"""Shared probe for filesystem symlink-creation capability.

Symlink-confinement tests must actually create a symlink *fixture* to
exercise the confinement logic they assert on. On Windows, ``os.symlink``
raises ``OSError: [WinError 1314] A required privilege is not held`` unless
the process runs elevated or the machine has Developer Mode enabled. POSIX
hosts (the CLAUDE.md test authority) create symlinks unconditionally.

``requires_symlink`` therefore skips a test ONLY where the OS genuinely
cannot create the fixture — it never regresses macOS/Linux coverage, where
``can_symlink()`` is always ``True``. Enabling Windows Developer Mode (or
running the suite elevated) lets these tests run for real on Windows too.
"""

from __future__ import annotations

import os
import tempfile
from functools import lru_cache

import pytest


@lru_cache(maxsize=1)
def can_symlink() -> bool:
    """Return ``True`` iff this process can create a filesystem symlink.

    Probes by creating a real symlink in a throwaway temp dir and caches the
    verdict, so the syscall runs at most once per session. Returns ``True``
    on every POSIX host; returns ``False`` on Windows lacking the
    ``SeCreateSymbolicLink`` privilege (no Developer Mode, not elevated).
    """
    with tempfile.TemporaryDirectory() as probe_dir:
        target = os.path.join(probe_dir, "probe-target")
        link = os.path.join(probe_dir, "probe-link")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("x")
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            return False
        return True


requires_symlink = pytest.mark.skipif(
    not can_symlink(),
    reason=(
        "symlink creation unavailable (WinError 1314): enable Windows "
        "Developer Mode or run elevated to grant SeCreateSymbolicLink. "
        "POSIX hosts always run this test."
    ),
)
