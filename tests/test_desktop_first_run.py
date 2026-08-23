"""The shipped application must be able to start, and must say when it cannot.

Two criticals from the 2026-08-22 chaos run, fixed together because neither
half stands alone.

**#426 — there was no first-run state that could succeed.** The self-authored
plan points ``data_root`` at ``~/Library/Application Support/arXMCP``, which on
a machine that has never run an ingest is empty. ``Resources.startup`` then
raised :class:`CorpusNotIngestedError` and the child exited before emitting
``bound``. The remedy that error names — ``make up-wizard`` — does not exist
inside a ``.app``, so the failure was not merely likely but total.

**#425 — the failure was invisible.** Every refusal path is ``eprintln!`` plus
an exit, and under LaunchServices a double-clicked application's stderr goes
nowhere an operator will look. Measured: no dialog, no message, ``open`` exits
0, process gone in five to seven seconds, and the only trace an NDJSON file the
next launch truncates (#464).

Fixing either one alone leaves the product broken: a bootstrap that works but
cannot report its next failure, or a clear report of a failure that always
happens.

Everything here is static analysis: the runtime behaviour these fixes rely on
is already covered by ``tests/test_bootstrap_mode.py``, and this module asserts
that the desktop entrypoint and the supervisor actually reach for it. No model
is loaded and no process is spawned.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
DESKTOP_CHILD: Path = REPO_ROOT / "server" / "desktop_child.py"
SUPERVISOR_SRC: Path = REPO_ROOT / "apps" / "desktop" / "crates" / "supervisor" / "src"
LIFECYCLE_RS: str = (SUPERVISOR_SRC / "lifecycle.rs").read_text(encoding="utf-8")
MAIN_RS: str = (SUPERVISOR_SRC / "main.rs").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# #426 — a cold machine can start
# ---------------------------------------------------------------------------
def _config_call_keywords() -> dict[str, ast.expr]:
    """Find the ``Config(...)`` call in ``desktop_child.main`` via AST.

    Derived rather than grepped: a substring check for ``bootstrap_mode=True``
    would also match a comment or a docstring, and the failure this guards
    against is precisely a claim that is present in prose and absent in code.
    """
    tree = ast.parse(DESKTOP_CHILD.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Config"
        ):
            return {kw.arg: kw.value for kw in node.keywords if kw.arg}
    raise AssertionError("no Config(...) call found in server/desktop_child.py")


def test_the_desktop_child_asks_for_bootstrap_mode() -> None:
    """#426. Without this the shipped .app cannot start on a fresh machine."""
    keywords = _config_call_keywords()
    assert "bootstrap_mode" in keywords, (
        "server/desktop_child.py must build its Config with "
        "bootstrap_mode=True; without it a fresh install raises "
        "CorpusNotIngestedError and never emits `bound` (#426)"
    )
    value = keywords["bootstrap_mode"]
    assert isinstance(value, ast.Constant) and value.value is True, (
        "bootstrap_mode must be the literal True, not a computed value — a "
        "cold start is the ONLY case it changes, and guessing at it is how "
        "#426 shipped"
    )


def test_the_child_still_owns_its_data_root() -> None:
    """The launch frame stays the source of the data root."""
    keywords = _config_call_keywords()
    assert "data_dir" in keywords, "Config must still be given the frame's data_root"


def test_the_semantics_bootstrap_mode_relies_on_are_covered_elsewhere() -> None:
    """Pointer, not duplication.

    The two behaviours #426 leans on — bootstrap_mode skipping the cold-start
    refusal, and FM-7's "present marker means the hint is ignored" — are
    already asserted in ``tests/test_bootstrap_mode.py``. Re-testing them here
    would add a second place to update and no new coverage. What is NEW is that
    the DESKTOP entrypoint asks for the mode at all, which the AST guards above
    pin. This test fails if that upstream coverage is deleted or renamed, so
    the reference cannot rot silently.
    """
    upstream = (REPO_ROOT / "tests" / "test_bootstrap_mode.py").read_text(
        encoding="utf-8"
    )
    for required in (
        "test_resources_startup_raises_on_cold_start_default",
        "test_resources_startup_skips_raise_in_bootstrap_mode",
        "test_resources_startup_bootstrap_hint_ignored_when_corpus_exists",
    ):
        assert required in upstream, (
            f"tests/test_bootstrap_mode.py no longer defines {required!r}; "
            "#426's correctness argument rests on it — re-home the assertion "
            "before deleting it"
        )


# ---------------------------------------------------------------------------
# #425 — a failure reaches the operator
# ---------------------------------------------------------------------------
def test_the_failure_path_shows_a_window() -> None:
    """`lifecycle-failed` must be accompanied by something on screen."""
    assert "pub fn show_failure(" in LIFECYCLE_RS, (
        "lifecycle.rs must define show_failure (#425)"
    )
    failure_arm = LIFECYCLE_RS[LIFECYCLE_RS.index('recorder.record("lifecycle-failed"') :][
        :1200
    ]
    assert "show_failure(" in failure_arm, (
        "show_failure must be called on the lifecycle-failed arm, not merely "
        "defined — an unreferenced failure surface is #425 unfixed"
    )
    assert 'record("failure-shown"' in failure_arm, (
        "record failure-shown so a triage session can tell 'the operator was "
        "told' from 'the operator was not told'"
    )


def test_the_failure_page_is_not_shown_in_smoke_mode() -> None:
    """Smoke runs are headless gates that exit immediately after failing."""
    failure_arm = LIFECYCLE_RS[LIFECYCLE_RS.index('recorder.record("lifecycle-failed"') :][
        :1200
    ]
    assert "if !smoke" in failure_arm, (
        "the failure page belongs to the interactive path only"
    )


def test_a_non_smoke_failure_no_longer_takes_the_window_away() -> None:
    """The other half of #425, and the easiest to regress.

    Showing the reason and then exiting removes it from the screen again, which
    is indistinguishable from never having shown it. A smoke run MUST still
    self-exit — the m6 fault matrix asserts an exit code of 1 — so the guard is
    that the exit is reached under ``smoke`` and not under a bare ``code != 0``.
    """
    match = re.search(r"if smoke \{\s*handle\.exit\(code\);\s*\}", MAIN_RS)
    assert match is not None, (
        "main.rs must exit on smoke runs only; a non-smoke failure has to "
        "leave the failure page on screen (#425)"
    )
    assert "if smoke || code != 0" not in MAIN_RS, (
        "the old condition exits on a non-smoke failure, which takes the "
        "failure page off screen — that is #425"
    )


def test_the_failure_page_names_the_log_and_its_volatility() -> None:
    """#464: the log is truncated on every launch, so telling the operator where it
    is without telling them it is about to be overwritten is a trap."""
    body = LIFECYCLE_RS[LIFECYCLE_RS.index("pub fn show_failure(") :][:2500]
    assert "desktop-child.log" in LIFECYCLE_RS, "the page must name the log path"
    assert "rewritten on every launch" in body, (
        "the page must warn that the log is truncated on the next launch "
        "(#464), or it sends the operator to a file that will be gone"
    )
