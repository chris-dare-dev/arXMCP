"""Guards that the test suite cannot destroy its own toolchain.

Two defects were observed live on 2026-08-01 in
``tests/test_daily_metrics_report.py::TestRegenFixture``, which shelled
out to ``uv run python -c "…"`` to render a fixture in a fresh process.
Neither had anything to do with product code:

1. **``uv run`` prunes the test runner's own tooling.** ``uv run`` syncs
   the project environment to the project's DEFAULT dependency set before
   executing. ``pytest`` and ``ruff`` were declared ONLY in the ``dev``
   *extra*, and uv does not install extras by default — so the subprocess
   uninstalled pytest, ruff and pip from the very ``.venv`` the running
   pytest process had been launched from. The in-flight run survived on
   already-imported modules, so **the test passed** while the NEXT
   ``make test`` died with "No module named pytest".

2. **On Windows the same call hard-fails when an MCP session is live.**
   While syncing, uv replaces the project's own installed entry points,
   including ``.venv/Scripts/arxmcp-shim.exe``. Any Claude session with
   the arXMCP MCP server connected holds that exe open, Windows refuses
   the delete, and uv aborts with ``Access is denied. (os error 5)``.
   Pruning happens FIRST, so this path leaves a half-stripped venv AND a
   red test.

Both are closed here, from two directions:

* ``TestUvRunNotInvokedFromTests`` bans naming the ``uv`` binary from
  anywhere under ``tests/``. The fixed call site uses ``sys.executable``,
  which is already the correct project interpreter under pytest and needs
  no environment sync at all. This also retires the hardcoded
  ``/Users/chris.dare/Library/Python/3.9/bin/uv`` fallback the old call
  site carried — dead on every non-macOS box, and user-specific even
  there (the ``docs/ops/`` peer of this rule lives in
  ``tests/test_runbook_index.py::TestNoHardcodedUserPaths``).

* ``TestDevGroupMirrorsDevExtra`` pins the ``[dependency-groups].dev``
  block in ``pyproject.toml`` that makes ``uv run`` non-destructive
  everywhere else in the repo — roughly twenty ``uv run python -m
  tools.…`` commands are documented across tools/ docstrings and
  docs/ops/ runbooks, and every one of them used to strip the toolchain.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
TESTS_DIR = REPO_ROOT / "tests"


def _load_pyproject() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


class TestDevGroupMirrorsDevExtra:
    """``uv`` installs dependency GROUPS by default and extras never.

    ``pip install -e ".[dev]"`` (Makefile ``bootstrap``, docs/install.md)
    reads the extra; ``uv sync`` / ``uv run`` read the group. Neither
    table can reference the other, so pyproject.toml carries both and
    this test is what keeps them from drifting.
    """

    def test_dev_group_exists(self) -> None:
        groups = _load_pyproject().get("dependency-groups", {})
        assert "dev" in groups, (
            "pyproject.toml has no `[dependency-groups].dev`. Without it "
            "every `uv run` in this repo syncs the project .venv down to "
            "the default dependency set and PRUNES pytest + ruff out of "
            "it — including a `uv run` fired from inside the suite, which "
            "strips the interpreter running the tests. Re-add the block."
        )

    def test_dev_group_matches_dev_extra(self) -> None:
        cfg = _load_pyproject()
        extra = cfg["project"]["optional-dependencies"]["dev"]
        group = cfg["dependency-groups"]["dev"]
        # Only plain requirement strings are compared. PEP 735 also allows
        # `{include-group = ...}` table entries; if one is ever added here
        # this guard must be revisited rather than silently loosened.
        assert all(isinstance(x, str) for x in group), (
            "`[dependency-groups].dev` gained a non-string entry "
            f"({group!r}). This guard compares requirement strings only — "
            "update it deliberately."
        )
        assert sorted(group) == sorted(extra), (
            "`[dependency-groups].dev` and "
            "`[project.optional-dependencies].dev` have drifted:\n"
            f"  group (uv sync / uv run): {sorted(group)}\n"
            f"  extra (pip install -e '.[dev]'): {sorted(extra)}\n"
            "Both must list the full dev toolchain. A package present in "
            "only the extra is invisible to `uv run` and gets pruned from "
            "the project .venv on the next sync."
        )


class TestUvRunNotInvokedFromTests:
    """No test may shell out to the ``uv`` binary.

    A test that needs a fresh interpreter wants ``sys.executable``, not
    an environment sync. Detection is AST-based (string CONSTANTS only),
    so the prose in this file — and in the fixed call site's explanatory
    comment — does not trip it; only real code naming the binary does.
    """

    @staticmethod
    def _names_uv_binary(value: str) -> bool:
        # Bare executable name, Windows form, or any absolute/relative
        # path ending in the binary (catches the old hardcoded
        # `/Users/chris.dare/Library/Python/3.9/bin/uv` fallback).
        stem = value.replace("\\", "/").rsplit("/", 1)[-1]
        return stem in {"uv", "uv.exe"}

    def test_no_uv_binary_reference_in_tests(self) -> None:
        offenders: list[str] = []
        # This file is the detector; its own literals are the pattern
        # being banned, not an instance of it.
        self_path = Path(__file__).resolve()
        for py in sorted(TESTS_DIR.rglob("*.py")):
            if py.resolve() == self_path:
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            except SyntaxError:  # pragma: no cover - would fail collection anyway
                continue
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and self._names_uv_binary(node.value)
                ):
                    offenders.append(
                        f"  {py.relative_to(REPO_ROOT).as_posix()}:"
                        f"{node.lineno}: {node.value!r}"
                    )
        assert not offenders, (
            "Test code names the `uv` binary:\n"
            + "\n".join(offenders)
            + "\n\n`uv run` syncs the project environment before executing "
            "and uninstalls anything outside the default dependency set — "
            "run from inside the suite it prunes pytest/ruff out of the "
            "venv the tests are running in, and on Windows it additionally "
            "fails outright on the locked arxmcp-shim.exe when an MCP "
            "session is connected.\nUse `sys.executable` for a fresh "
            "interpreter (set PYTHONPATH=REPO_ROOT so the repo imports), "
            "or drive the real thing through tools/wheel_install_check.py, "
            "which builds into a throwaway venv and never touches .venv."
        )
