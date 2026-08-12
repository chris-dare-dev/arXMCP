"""CLAUDE.md §4.5's marker inventory is derived from `pyproject.toml`.

desktop-distribution-m5 critique C2: §4.5 is the checklist an agent follows
when adding an opt-in marker — it is where the `_OPT_IN_MARKERS` +
`pyproject.toml` pairing rule that issue #206 produced is written down. It
claimed "Nine test markers exist" while ten were registered, and its
enumeration silently omitted the newest one. A false count plus a short list is
exactly how the next agent concludes a gate has no opt-in surface.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"

#: §4.5 spells its count as an English word, so the assertion has to too.
_NUMBER_WORDS = (
    "Zero",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
    "Twenty",
)


def _registered_markers() -> dict[str, str]:
    """``{name: full registration string}`` from ``[tool.pytest.ini_options]``."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    entries = data["tool"]["pytest"]["ini_options"]["markers"]
    return {entry.split(":", 1)[0].strip(): entry for entry in entries}


def _section_4_5() -> str:
    body = CLAUDE_MD.read_text(encoding="utf-8")
    start = body.index("### 4.5 Test + lint discipline")
    return body[start : body.index("### 4.5b", start)]


def test_claude_md_marker_count_matches_pyproject() -> None:
    match = re.search(r"\*\*(\w+) test markers exist\*\*", _section_4_5())
    assert match is not None, "CLAUDE.md §4.5 must state how many markers exist"
    expected = _NUMBER_WORDS[len(_registered_markers())]
    assert match.group(1) == expected, (
        f"CLAUDE.md §4.5 says {match.group(1)!r} markers; pyproject.toml "
        f"registers {len(_registered_markers())} ({expected})"
    )


def test_every_registered_marker_is_enumerated_in_claude_md() -> None:
    section = _section_4_5()
    missing = [name for name in _registered_markers() if f"`{name}`" not in section]
    assert not missing, (
        f"markers registered in pyproject.toml but absent from CLAUDE.md "
        f"§4.5: {missing}"
    )


def test_opt_in_markers_are_all_registered() -> None:
    """Issue #206's pairing rule: registering a marker in only one of the two
    places is what made every marked test run on every ``make test``."""
    from tests.conftest import _OPT_IN_MARKERS

    unregistered = sorted(_OPT_IN_MARKERS - set(_registered_markers()))
    assert not unregistered, (
        f"tests/conftest.py deselects {unregistered}, which pyproject.toml "
        f"does not register — `--strict-markers` would reject them"
    )


def test_desktop_stack_marker_declares_its_reranker_prerequisite() -> None:
    """m5 critique M11: ``make desktop-conformance`` force-enables rerank, so
    the mandatory gate hard-requires a third (~2.3 GB, fail-closed) model that
    the marker text used to name only as "BGE-M3/LanceDB warm-up"."""
    registration = _registered_markers()["requires_desktop_stack"]
    assert "reranker" in registration.lower()


def test_every_desktop_gate_env_var_is_registered_in_conftest() -> None:
    """Every ``DESKTOP_*_GATE`` variable the Makefile sets must appear in
    ``tests/conftest.py``'s ``_DESKTOP_GATE_ENV``.

    This is the third occurrence of one defect. m6's H3 found the zero-skip
    guard unarmed; it was fixed. m15 added ``desktop-bundle-check`` with the
    Makefile's ``-m "<token> or not <token>"`` expression wired and the
    conftest tuple NOT updated, and all three m15 critics found it
    independently (C1/H2/H3).

    The reason it keeps recurring is that the two halves look independent: the
    ``-m`` expression is a tautology for ANY token, so a gate appears to work
    — its tests run, the session exits 0 — while the half that turns a skip
    into a failure was never connected. Nothing in the Makefile references the
    conftest tuple, so no reader of either file learns the other exists.

    Derived rather than enumerated, so a fourth gate cannot be added without
    either registering it or failing here."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    conftest = (REPO_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    declared = set(re.findall(r"\bDESKTOP_[A-Z_]*GATE\b", makefile))
    assert declared, "no DESKTOP_*_GATE variables found in the Makefile"
    registered = re.search(
        r"_DESKTOP_GATE_ENV:\s*tuple\[str, \.\.\.\]\s*=\s*\((.*?)\)",
        conftest,
        re.DOTALL,
    )
    assert registered is not None, "_DESKTOP_GATE_ENV is no longer a plain tuple"
    body = registered.group(1)
    missing = sorted(name for name in declared if f'"{name}"' not in body)
    assert not missing, (
        f"{missing} set by the Makefile but absent from conftest's "
        f"_DESKTOP_GATE_ENV, so a skip in that gate's session is silent. "
        f"This is m6 H3 / m15 C1 recurring."
    )
