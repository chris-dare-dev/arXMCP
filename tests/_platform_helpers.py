"""Shared platform-capability probes for Windows-conditional skips.

stage2/arx-ws0 Windows-baseline triage (2026-07-04): Windows is the
authoritative arXMCP runtime, so platform-limited tests carry
*documented* skip markers instead of failing red. Every marker here
must reference `.claude/notes/windows-test-triage.md` (or a GitHub
issue) in its reason string — `tests/test_windows_skip_markers.py`
audits that contract.

Import from tests as::

    from tests._platform_helpers import requires_symlinks

(mirrors the existing ``tests/_graph_helpers.py`` shared-module
pattern).
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
import uuid

import pytest

_TRIAGE_NOTE = ".claude/notes/windows-test-triage.md"


def _probe_symlink_capability() -> bool:
    """True when this process may create filesystem symlinks.

    On Windows, ``os.symlink`` requires SeCreateSymbolicLinkPrivilege
    (Administrator, or Developer Mode enabled) and otherwise raises
    ``OSError: [WinError 1314]``. POSIX platforms always succeed.
    Probed once at import; the result is stable for the process
    lifetime.
    """
    if sys.platform != "win32":
        return True
    probe_dir = tempfile.mkdtemp(prefix="arxmcp-symlink-probe-")
    target = os.path.join(probe_dir, "t")
    link = os.path.join(probe_dir, f"l-{uuid.uuid4().hex[:8]}")
    try:
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("probe")
        os.symlink(target, link)
    except OSError:
        return False
    finally:
        for p in (link, target):
            with contextlib.suppress(OSError):
                os.remove(p)
        with contextlib.suppress(OSError):
            os.rmdir(probe_dir)
    return True


SYMLINKS_AVAILABLE: bool = _probe_symlink_capability()

#: Marker for tests whose *fixture construction* needs os.symlink.
#: These are mostly symlink-confinement security tests: the property
#: under test targets an attacker who CAN create symlinks, so skipping
#: where the runner itself cannot is honest (the fixture is
#: unconstructible), not a coverage waiver. See the triage note §2.
requires_symlinks = pytest.mark.skipif(
    not SYMLINKS_AVAILABLE,
    reason=(
        "os.symlink needs SeCreateSymbolicLinkPrivilege on Windows "
        "(admin or Developer Mode); unavailable in this environment — "
        f"see {_TRIAGE_NOTE} §2 (win32)"
    ),
)

#: Marker for tests whose fixtures create filenames that Win32/NTFS
#: rejects outright (control characters, trailing spaces, reserved
#: chars). The code under test defends against such names arriving
#: from a volume written by another OS; the fixture simply cannot be
#: constructed on Windows. See the triage note §3.
requires_lax_filenames = pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "Win32/NTFS rejects control characters in filenames; the "
        f"fixture is unconstructible on Windows — see {_TRIAGE_NOTE} "
        "§3 (win32)"
    ),
)


def _probe_latexmlc_functional() -> bool:
    """True when ``latexmlc`` on PATH actually runs (win32 probe only).

    On this Windows workstation a Strawberry-Perl ``latexmlc`` shim is
    on PATH but is broken: invoking it fails inside Perl with "Can't
    find C:\\Strawberry\\perl\\site\\bin\\latexmlc.BAT on PATH" (exit
    29), so every render attempt errors before LaTeXML starts. Mere
    ``shutil.which`` presence is therefore not enough on win32 — probe
    an actual ``--VERSION`` invocation once per test process.

    Scoped to win32 on purpose: on POSIX the historical behavior
    (tests run whenever the binary is present; ``_require_latexmlc``
    raises loudly when absent — the F10 no-silent-skip discipline)
    is preserved unchanged.
    """
    if sys.platform != "win32":
        return True
    import shutil
    import subprocess

    exe = shutil.which("latexmlc")
    if exe is None:
        return False
    try:
        proc = subprocess.run(
            [exe, "--VERSION"],
            capture_output=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


LATEXMLC_FUNCTIONAL: bool = _probe_latexmlc_functional()

#: Marker for the real-``latexmlc`` integration tests. On win32 they
#: additionally require the binary to be *functional*, not merely
#: present (broken Strawberry-Perl shim case). See the triage note §4.
requires_working_latexmlc = pytest.mark.skipif(
    not LATEXMLC_FUNCTIONAL,
    reason=(
        "latexmlc on PATH is non-functional on this Windows host "
        "(Strawberry Perl shim exits 29: can't find latexmlc.BAT) — "
        f"see {_TRIAGE_NOTE} §4 (win32)"
    ),
)
