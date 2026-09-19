"""Audit: every Windows-conditional skip carries a documented reason.

stage2/arx-ws0 (Stage-2 WS-0, Windows-baseline triage): Windows is the
authoritative arXMCP runtime, so platform-limited tests are allowed to
skip **only** with a reason string that points a future maintainer at
the triage record — either `.claude/notes/windows-test-triage.md` or a
GitHub issue reference. An undocumented `skipif(sys.platform ==
"win32")` silently erodes the tier-1 baseline; this test makes that a
red failure instead.

Contract enforced (the acceptance-criteria.md WS-0 test-plan seed):

1. Every ``pytest.mark.skipif(...)`` whose condition mentions ``win32``
   (or a helper marker defined over such a condition) has a non-empty
   ``reason=`` that references ``windows-test-triage.md`` or an issue
   (``#<n>`` / ``issues/<n>``).
2. The triage note itself exists in the repo.

Implementation notes: source-level scan (regex over ``tests/**/*.py``),
not collection-time introspection — the audit must see files that are
skipped at import time too. The scan window for each ``skipif(`` is its
balanced-paren argument span, so multi-line reasons are covered.
"""

from __future__ import annotations

import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
TRIAGE_NOTE = REPO_ROOT / ".claude" / "notes" / "windows-test-triage.md"

#: A reason is "documented" when it names the triage note or an issue.
#: ``_TRIAGE_NOTE`` is accepted because ``tests/_platform_helpers.py``
#: interpolates the note path from that constant (its value is pinned
#: by ``test_platform_helper_markers_reference_triage_note`` below).
_DOCUMENTED_RE = re.compile(
    r"windows-test-triage\.md|_TRIAGE_NOTE|#\d+|issues/\d+", re.IGNORECASE
)

_SKIPIF_CALL_RE = re.compile(r"pytest\.mark\.skipif\s*\(")


def _balanced_span(text: str, open_paren_idx: int) -> str:
    """Return the argument text of the call whose ``(`` is at the index.

    Simple paren counter; good enough for test-source scanning (paren
    characters inside string literals can only widen the window, never
    truncate it before the true close).
    """
    depth = 0
    for i in range(open_paren_idx, len(text)):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren_idx : i + 1]
    return text[open_paren_idx:]


def _win32_skipif_sites(source: str) -> list[str]:
    """All ``pytest.mark.skipif(...)`` argument spans mentioning win32."""
    sites = []
    for m in _SKIPIF_CALL_RE.finditer(source):
        span = _balanced_span(source, m.end() - 1)
        if "win32" in span:
            sites.append(span)
    return sites


def test_triage_note_exists():
    if not TRIAGE_NOTE.is_file():
        raise AssertionError(
            f"missing {TRIAGE_NOTE} — the Windows skip markers all "
            "reference it; restore the note or re-point the reasons"
        )


def test_every_win32_skipif_reason_is_documented():
    offenders: list[str] = []
    for py_file in sorted(TESTS_DIR.rglob("*.py")):
        if py_file.name == Path(__file__).name:
            continue
        source = py_file.read_text(encoding="utf-8")
        for span in _win32_skipif_sites(source):
            if "reason" not in span or not _DOCUMENTED_RE.search(span):
                offenders.append(
                    f"{py_file.relative_to(REPO_ROOT).as_posix()}: "
                    f"{' '.join(span.split())[:160]}"
                )
    if offenders:
        raise AssertionError(
            "win32-conditioned skipif without a documented reason "
            "(must reference .claude/notes/windows-test-triage.md or "
            "an issue):\n  " + "\n  ".join(offenders)
        )


def test_platform_helper_markers_reference_triage_note():
    """The shared helper module's reasons must stay pinned to the note."""
    helper = TESTS_DIR / "_platform_helpers.py"
    source = helper.read_text(encoding="utf-8")
    if "windows-test-triage.md" not in source:
        raise AssertionError(
            "tests/_platform_helpers.py no longer references the "
            "triage note in its skip reasons"
        )
