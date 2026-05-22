"""m9 scope-invariant tests (AC #4).

The m9 brief is explicit: paper preview is OUT of scope (deferred
to v2 m10). The static-grep test below defends against an
accidental m10 leak into m9 — if any template or static asset
under ``frontend/`` contains the literal tokens ``iframe`` or
``preview``, the test fails.

The test is a simple grep; it runs without the server and is
independent of the FastAPI test fixture.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FRONTEND_DIR: Path = REPO_ROOT / "frontend"


def test_no_preview_or_iframe_in_frontend() -> None:
    """AC #4: grep over frontend/ for `iframe|preview` returns empty.

    The m10 milestone (v2, Later lane) will add the sandboxed
    iframe paper preview. m9 must not anticipate it — no template
    placeholders, no static-asset hooks, no commented-out routes.
    """
    if not FRONTEND_DIR.is_dir():
        # No frontend/ yet (fresh checkout?) — vacuously pass.
        return
    result = subprocess.run(
        ["grep", "-rEi", "iframe|preview", str(FRONTEND_DIR)],
        capture_output=True, text=True, check=False,
    )
    # grep exits 1 when no matches found — that's our success case.
    # exit 0 means matches found — failure for this AC.
    if result.returncode == 0:
        # grep wrote matches to stdout — surface them in the
        # failure message for an actionable error.
        matches = result.stdout.strip()
        raise AssertionError(
            "AC #4 violation: m9 must not introduce preview/iframe "
            "references to frontend/ (deferred to m10). Found:\n"
            f"{matches}"
        )
    # exit 1 (no matches) is the happy path; anything else is a
    # grep / FS error we surface for debugging.
    assert result.returncode == 1, (
        f"grep failed unexpectedly: exit={result.returncode}, "
        f"stderr={result.stderr!r}"
    )
