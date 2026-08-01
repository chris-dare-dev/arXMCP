"""`assert` is banned for invariants in shipped code — CLAUDE.md §4.7, issue #210.

``python -O`` strips assertions, so an ``assert`` guarding an invariant
disappears in exactly the deployment that opted into less checking. The live
case: ``server/main.py``'s response-size-cap middleware held an
``http.response.start`` event and flushed it on the first body event behind
``assert start_event is not None``. Under ``-O`` that guard vanished and
``await send(None)`` went straight to the ASGI server — a confusing failure
deep in uvicorn rather than a named one at the violation.

Two mechanisms, deliberately independent:

1. **ruff ``S101``** (``pyproject.toml``), which fails ``make test`` on any new
   ``assert`` outside ``tests/``. That is the fast feedback path.
2. **This module**, which re-derives the ban from the on-disk tree via AST.

The duplication is the point. A lint rule lives in config, and config can be
edited — dropping ``"S101"`` from the ``select`` list is a one-token change
that would silently retire the ban with every test still green. So
:class:`TestRuffEnforcesTheBan` below pins the config itself, and
:class:`TestNoAssertInShippedPackages` catches the violation even if the rule
is removed entirely.

Scope is the trees that ship in the wheel (``§4.5b``): a bare ``assert`` in a
dev-only script is a different, smaller problem than one an operator can run
under ``-O``.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The trees that ship in the wheel — kept in step with
#: ``[tool.setuptools.packages.find].include`` in ``pyproject.toml``.
#: ``frontend`` is listed there too but holds no Python.
SHIPPED_TREES: tuple[str, ...] = (
    "server",
    "ingest",
    "tools",
    "shim",
    "ops",
)


def _shipped_python_files() -> list[Path]:
    files: list[Path] = []
    for tree in SHIPPED_TREES:
        root = REPO_ROOT / tree
        if not root.is_dir():
            continue
        files.extend(
            p
            for p in root.rglob("*.py")
            if "__pycache__" not in p.parts
        )
    return sorted(files)


def _assert_lines(path: Path) -> list[int]:
    """Line numbers of every ``assert`` statement in ``path``.

    AST rather than a text scan: a regex over source would both miss
    continuation-line forms and fire on the word inside strings, comments and
    docstrings — this module's own prose being a perfect example.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:  # pragma: no cover - would fail the suite anyway
        pytest.fail(f"{path} is not parseable Python: {exc}")
    return [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Assert)]


class TestNoAssertInShippedPackages:
    """THE #210 regression guard, independent of any lint configuration."""

    def test_shipped_trees_are_actually_scanned(self):
        """Guard the guard: a typo in SHIPPED_TREES, or a tree that moves,
        would make every assertion below vacuously true."""
        files = _shipped_python_files()
        assert len(files) > 50, (
            f"expected the shipped trees to hold a substantial number of "
            f"modules; found {len(files)} — SHIPPED_TREES is probably stale"
        )
        found = {p.relative_to(REPO_ROOT).parts[0] for p in files}
        assert found == set(SHIPPED_TREES), (
            f"SHIPPED_TREES names {sorted(SHIPPED_TREES)} but only "
            f"{sorted(found)} produced files"
        )

    def test_no_bare_assert_in_shipped_code(self):
        offenders: list[str] = []
        for path in _shipped_python_files():
            for lineno in _assert_lines(path):
                rel = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{rel}:{lineno}")
        assert not offenders, (
            "`assert` is banned for invariants in shipped code (CLAUDE.md "
            "§4.7) because `python -O` strips it — the guard vanishes in "
            "exactly the deployment that opted into less checking. Use "
            "`if <negated>: raise RuntimeError(...)`. Offenders: "
            f"{offenders}"
        )

    def test_the_original_210_site_is_a_raise(self):
        """Pin the specific site the issue named, so a revert is loud.

        The line number moved (253 -> 262 -> here) when 004c814 lifted the
        startup sequence into server/cli.py, so this anchors on the code
        rather than a line.
        """
        text = (REPO_ROOT / "server" / "main.py").read_text(encoding="utf-8")
        assert "assert start_event is not None" not in text
        assert "if start_event is None:" in text
        assert "violated the response protocol" in text


class TestRuffEnforcesTheBan:
    """The fast path. Pinned so the rule cannot be quietly dropped."""

    @staticmethod
    def _lint_config() -> dict:
        with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
            return tomllib.load(fh)["tool"]["ruff"]["lint"]

    def test_s101_is_selected(self):
        select = self._lint_config()["select"]
        assert "S101" in select or "S" in select, (
            "ruff no longer selects S101, so a new `assert` in shipped code "
            "would not fail `make test`. Re-add it to "
            "[tool.ruff.lint].select in pyproject.toml (issue #210)."
        )

    def test_only_tests_are_exempt(self):
        """`assert` is pytest's assertion mechanism, so tests/ is exempt —
        but exempting any shipped tree would reopen the hole this closes."""
        ignores = self._lint_config().get("per-file-ignores", {})
        exempt = {
            pattern
            for pattern, rules in ignores.items()
            if "S101" in rules or "S" in rules
        }
        assert exempt == {"tests/**"}, (
            f"only tests/** may be exempt from S101; found {sorted(exempt)}"
        )
