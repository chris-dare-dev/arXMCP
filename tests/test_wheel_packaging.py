"""Packaging-boundary guards (issue #206, trustworthy-release-m4).

The bug class this file exists to prevent is uniquely nasty: it is
**invisible from a source checkout**. The repo root is on ``sys.path`` and
every data file is right there on disk, so the full test suite passes, the
server runs, and `make up` works — while the built wheel silently ships
none of it. Five separate holes were open simultaneously until 2026-07-31:

* ``ops/`` — the whole operability layer. An operator installing the
  documented way got no backup, no cutover, no restore drill, no drift
  watchdog, and **no error announcing their absence**.
* the operator-console assets (now ``src/arxmcp/server/frontend/``) — ``create_app()``
  raises on the missing StaticFiles dir.
* ``src/arxmcp/server/router_patterns.yaml`` — ``src/arxmcp/server/router.py`` raises outright.
* ``src/arxmcp/server/schemas/*.json`` — the declared result-row source of truth.
* ``src/arxmcp/tools/seed-papers.txt`` — ``src/arxmcp/tools/fetch_seed.py`` cannot find it.

Plus a sixth at the docs boundary: ``docs/install.md`` told every new
operator to verify their install with ``arxmcp-server --help`` while
``pyproject.toml`` had no ``[project.scripts]`` section at all.

Two layers, deliberately:

**Static guards (always run).** Cheap, no build, no network. They are
DERIVED from the on-disk tree rather than hard-coded, so the guard cannot
rot the way a hand-maintained list would: adding a new data file to a
shipped package, or a new package to ``pyproject.toml``, fails here until
the packaging declarations catch up.

**The real thing (opt-in).** ``src/arxmcp/tools/wheel_install_check.py`` builds the
wheel, installs it into a fresh venv and boots the server. It is opt-in via
the ``requires_wheel_build`` marker because it costs ~4 min and a ~2 GB
dependency resolve; ``make wheel-check`` and ``make wheel-check-full`` are
the operator-facing entry points, and docs/releasing.md makes the full run
a pre-publish gate.
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from setuptools import find_namespace_packages

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
DOCKERFILE = REPO_ROOT / "deploy" / "Dockerfile.server"

#: Filenames that are repo navigation, not distribution content. This is an
#: explicit decision rather than an oversight: ``README.md`` inside a
#: package documents the source tree for contributors and has no consumer
#: at runtime. Keeping the exclusion keyed on the FILENAME (not on a path)
#: means it can never accidentally cover a real data file.
_NOT_SHIPPED_FILENAMES = frozenset({"README.md", "CLAUDE.md"})

#: Directory names skipped when walking the shipped trees. The desktop
#: lifecycle spike is a source-only Rust/Tauri experiment, not Python wheel
#: content; its locked crate is built directly with Cargo.
_SKIP_DIRS = frozenset(
    {"__pycache__", ".pytest_cache", ".ruff_cache", "desktop_lifecycle_spike"}
)


@pytest.fixture(scope="module")
def pyproject() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _include_patterns(pyproject: dict) -> list[str]:
    return pyproject["tool"]["setuptools"]["packages"]["find"]["include"]


def _exclude_patterns(pyproject: dict) -> list[str]:
    return pyproject["tool"]["setuptools"]["packages"]["find"].get("exclude", [])


def _package_root(pyproject: dict) -> str:
    """The directory setuptools discovers packages under (``src``)."""
    return pyproject["tool"]["setuptools"]["packages"]["find"].get("where", ["."])[0]


def _shipped_trees(pyproject: dict) -> list[str]:
    """Repo-relative directories the wheel claims to ship.

    ``where = ["src"]``, ``include = ["arxmcp*"]`` -> ``["src/arxmcp"]``.
    """
    root = _package_root(pyproject)
    return sorted({f"{root}/{p.rstrip('*')}" for p in _include_patterns(pyproject)})


def _discovered(pyproject: dict) -> list[str]:
    return find_namespace_packages(
        where=str(REPO_ROOT / _package_root(pyproject)),
        include=_include_patterns(pyproject),
        exclude=_exclude_patterns(pyproject),
    )


def _iter_data_files(tree: str):
    """Yield every non-``.py`` file under ``tree`` that a wheel would need
    an explicit ``package-data`` glob to carry."""
    root = REPO_ROOT / tree
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(REPO_ROOT).parts):
            continue
        if path.suffix in (".py", ".pyc", ".pyo"):
            continue
        if path.name.startswith("."):
            continue
        yield path


# ---------------------------------------------------------------------------
# Static guards — always run
# ---------------------------------------------------------------------------


class TestPackagesDeclared:
    def test_ops_is_in_the_wheel_include_list(self, pyproject: dict) -> None:
        """issue #206's headline: the operability layer shipped nowhere."""
        assert "arxmcp.ops" in _discovered(pyproject), (
            "pyproject.toml [tool.setuptools.packages.find].include does not "
            "list 'ops*'. Backup, cutover, restore drill and the drift "
            "watchdog would ship in no artifact, with no error."
        )

    def test_console_assets_are_covered_by_the_server_tree(
        self, pyproject: dict
    ) -> None:
        """trustworthy-release-m4: without these create_app() cannot start.

        They live at ``src/arxmcp/server/frontend/`` and are therefore carried by the
        ``server*`` glob — there is deliberately NO ``frontend*`` entry.
        A top-level ``frontend`` package would claim that very generic name
        in every installing environment's site-packages, and un-claiming it
        after a PyPI publish is a one-way door.
        """
        patterns = _include_patterns(pyproject)
        assert "arxmcp.server.frontend.static" in _discovered(pyproject)
        assert "frontend*" not in patterns, (
            "pyproject.toml re-added a TOP-LEVEL 'frontend*' package. The "
            "console assets belong at src/arxmcp/server/frontend/ so the distribution "
            "does not claim the generic name 'frontend' in site-packages."
        )
        assert not (REPO_ROOT / "frontend").exists(), (
            "a top-level frontend/ directory reappeared; the console assets "
            "belong at src/arxmcp/server/frontend/"
        )

    def test_console_asset_dirs_exist_where_the_code_looks(self) -> None:
        """Pin the move against the two call sites that resolve it.

        ``src/arxmcp/server/routes/ui.py`` uses ``parents[1]`` and ``src/arxmcp/server/main.py``
        uses ``parent`` — both package-relative, which is what makes one
        expression work for a source checkout and an installed wheel. If the
        assets move again without those being updated, the server raises at
        ``create_app()``; this fails first and says so.
        """
        for sub in ("templates", "static"):
            path = REPO_ROOT / "src" / "arxmcp" / "server" / "frontend" / sub
            assert path.is_dir(), f"missing console assets dir: {path}"

    @pytest.mark.parametrize("box", ["corpus", "server", "ingest", "tools", "shim", "ops"])
    def test_every_box_is_discovered(self, pyproject: dict, box: str) -> None:
        assert f"arxmcp.{box}" in _discovered(pyproject)

    def test_every_declared_tree_exists_on_disk(self, pyproject: dict) -> None:
        missing = [t for t in _shipped_trees(pyproject) if not (REPO_ROOT / t).is_dir()]
        assert not missing, (
            f"pyproject.toml declares package tree(s) {missing} that do not "
            "exist; the wheel build fails outright with \"package directory "
            "does not exist\"."
        )

    def test_desktop_lifecycle_spike_is_not_a_wheel_package(
        self, pyproject: dict
    ) -> None:
        assert "arxmcp.tools.desktop_lifecycle_spike*" in _exclude_patterns(pyproject)
        discovered = _discovered(pyproject)
        assert discovered, "no packages discovered; the find config is stale"
        assert not any(
            package == "arxmcp.tools.desktop_lifecycle_spike"
            or package.startswith("arxmcp.tools.desktop_lifecycle_spike.")
            for package in discovered
        )


class TestPackageDataCoversEveryDataFile:
    """The regression guard, derived from the tree rather than hard-coded.

    Declaring a directory in ``packages.find`` ships only its ``.py``
    modules. Every other file needs a ``package-data`` glob, and forgetting
    one is silent — that is precisely how ``router_patterns.yaml`` (whose
    absence makes ``src/arxmcp/server/router.py`` raise) went missing unnoticed.
    """

    def test_no_data_file_is_silently_dropped(self, pyproject: dict) -> None:
        package_data: dict[str, list[str]] = pyproject["tool"]["setuptools"].get(
            "package-data", {}
        )
        unmatched: list[str] = []

        for tree in _shipped_trees(pyproject):
            for path in _iter_data_files(tree):
                if path.name in _NOT_SHIPPED_FILENAMES:
                    continue
                rel = path.relative_to(REPO_ROOT / _package_root(pyproject))
                # setuptools resolves a package-data glob against the
                # package directory, and the glob does NOT descend into
                # subdirectories — so match the BASENAME against the globs
                # declared for this file's own directory only.
                package = ".".join(rel.parent.parts)
                globs = list(package_data.get(package, ()))
                globs += list(package_data.get("*", ()))
                if not any(fnmatch.fnmatch(path.name, g) for g in globs):
                    unmatched.append(f"{rel.as_posix()}  (needs a glob under "
                                     f"[tool.setuptools.package-data].\"{package}\")")

        assert not unmatched, (
            f"{len(unmatched)} data file(s) live in a shipped package but match "
            "no [tool.setuptools.package-data] glob, so the wheel drops them "
            "SILENTLY:\n  " + "\n  ".join(unmatched)
        )

    def test_the_known_casualties_are_covered(self, pyproject: dict) -> None:
        """Named regression cases — each one shipped broken at least once.

        The derived test above would catch these, but only while the file
        still exists at that path. Naming them keeps the specific bugs
        pinned even if the tree is reorganized.
        """
        package_data = pyproject["tool"]["setuptools"]["package-data"]
        for package, filename in [
            ("arxmcp.server", "router_patterns.yaml"),
            ("arxmcp.server.schemas", "search_papers_result.json"),
            ("arxmcp.settings.ca", "arxiv-ca-bundle.pem"),
            ("arxmcp.tools", "seed-papers.txt"),
            ("arxmcp.ops", "cutover.sh"),
            ("arxmcp.ops", "restic-env.sh.template"),
            ("arxmcp.ops.cron", "arxmcp-backup.sh"),
            ("arxmcp.ops.cron", "arxmcp-cron.cron"),
            ("arxmcp.ops.systemd", "arxmcp-backup.service"),
            ("arxmcp.ops.systemd", "arxmcp-backup.timer"),
            ("arxmcp.server.frontend.templates", "base.html"),
            ("arxmcp.server.frontend.static", "htmx.min.js"),
            ("arxmcp.server.frontend.static", "app.css"),
            # ui-uplift-m7 split the :root token blocks out of app.css. The
            # existing "*.css" glob and the wholesale `COPY server/` already
            # carry it — verified, not assumed, so no pyproject or Dockerfile
            # edit was needed. Named here anyway: a stylesheet that ships
            # without its token layer renders every var() as its initial
            # value (transparent backgrounds, no fonts), and the source
            # checkout cannot see that because the file is on disk either
            # way. This is precisely the §4.5b invisible-from-source class.
            ("arxmcp.server.frontend.static", "tokens.css"),
        ]:
            globs = package_data.get(package, [])
            assert any(fnmatch.fnmatch(filename, g) for g in globs), (
                f"{package}/{filename} matches no package-data glob "
                f"{globs!r} for package {package!r}"
            )


class TestConsoleScripts:
    """issue #206: docs promised a binary that pyproject never declared."""

    def test_arxmcp_server_is_declared(self, pyproject: dict) -> None:
        scripts = pyproject["project"]["scripts"]
        assert "arxmcp-server" in scripts, (
            "docs/install.md tells a new operator to verify their install "
            "with `arxmcp-server --help`, but [project.scripts] does not "
            "declare it — the first documented verification step fails."
        )

    def test_arxmcp_shim_still_declared(self, pyproject: dict) -> None:
        # Claude Code's ~/.claude.json registers this name verbatim.
        assert pyproject["project"]["scripts"]["arxmcp-shim"] == "arxmcp.shim.arxmcp_shim:main"

    @pytest.mark.parametrize("script", ["arxmcp-server", "arxmcp-shim"])
    def test_entry_point_target_is_importable_and_callable(
        self, pyproject: dict, script: str
    ) -> None:
        target = pyproject["project"]["scripts"][script]
        module_name, _, attr = target.partition(":")
        import importlib

        module = importlib.import_module(module_name)
        assert callable(getattr(module, attr)), f"{target} is not callable"

    def test_arxmcp_server_entry_point_does_not_build_the_app_on_import(
        self, pyproject: dict
    ) -> None:
        """``arxmcp-server --help`` must not construct the FastAPI app.

        ``src/arxmcp/server/main.py`` builds ``app`` at module scope, so pointing the
        console script at it would make ``--help`` open LanceDB handles and
        mount StaticFiles — and exit non-zero on any config error before
        argparse ran. This asserts the indirection through ``arxmcp.server.cli``
        is real: importing it must not drag in ``arxmcp.server.main``.
        """
        target = pyproject["project"]["scripts"]["arxmcp-server"]
        module_name = target.partition(":")[0]

        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import {module_name}, sys; "
                f"print('arxmcp.server.main' in sys.modules)",
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "False", (
            f"importing {module_name} eagerly imported arxmcp.server.main, which "
            "builds the whole FastAPI app. Keep the import inside main()."
        )

    def test_help_and_version_run_without_a_configured_environment(self) -> None:
        """The docs' verification step must work before anything is set up.

        Run with a cwd outside the repo and no ARXMCP_* variables, because
        that is the state a new operator's shell is in.
        """
        env = {k: v for k, v in os.environ.items() if not k.startswith("ARXMCP_")}
        for flag in ("--help", "--version"):
            proc = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import sys; from arxmcp.server.cli import main; "
                    f"sys.argv=['arxmcp-server','{flag}']; "
                    "sys.exit(main())",
                ],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
                env={**env, "PYTHONPATH": str(REPO_ROOT)},
                timeout=120,
            )
            # argparse exits 0 for both --help and --version.
            assert proc.returncode == 0, (
                f"`arxmcp-server {flag}` exited {proc.returncode}:\n"
                f"{proc.stdout}\n{proc.stderr}"
            )
            assert proc.stdout.strip(), f"`arxmcp-server {flag}` printed nothing"


class TestDockerfileMatchesPackaging:
    """Every declared package tree must be in the image build context.

    Derived from pyproject rather than hard-coded: adding a tree there
    without a matching COPY makes the image build fail with "package
    directory does not exist", and this catches it without a Docker daemon.
    """

    def test_builder_stage_copies_every_declared_tree(self, pyproject: dict) -> None:
        text = DOCKERFILE.read_text(encoding="utf-8")
        missing = [
            tree
            for tree in _shipped_trees(pyproject)
            if not re.search(rf"^COPY {re.escape(tree)}/ ", text, re.MULTILINE)
        ]
        assert not missing, (
            f"deploy/Dockerfile.server has no `COPY {{tree}}/` line for "
            f"{missing}, but pyproject.toml declares them as packages. The "
            "wheel build inside the image fails on the first one."
        )

    def test_ops_is_copied(self) -> None:
        """issue #206 names this explicitly."""
        text = DOCKERFILE.read_text(encoding="utf-8")
        assert re.search(r"^COPY src/arxmcp/ops/ ", text, re.MULTILINE), (
            "deploy/Dockerfile.server does not COPY src/arxmcp/ops/ — the container "
            "ships without backup, cutover, restore drill or drift watchdog."
        )


def _dockerfile_stages() -> dict[str, str]:
    """Map each ``FROM ... AS <name>`` stage to its instruction text."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    stages: dict[str, str] = {}
    name = None
    for line in text.splitlines():
        match = re.match(r"^FROM\s+\S+\s+AS\s+(\S+)", line, re.IGNORECASE)
        if match:
            name = match.group(1)
            stages[name] = ""
        elif name is not None and not line.lstrip().startswith("#"):
            stages[name] += line + "\n"
    return stages


def _env_values(stage: str) -> dict[str, str]:
    """``ENV KEY=VALUE`` pairs of a stage, line continuations joined."""
    joined = stage.replace("\\\n", " ")
    values: dict[str, str] = {}
    for line in joined.splitlines():
        if line.startswith("ENV "):
            for key, value in re.findall(r'(\w+)=("[^"]*"|\S+)', line[4:]):
                values[key] = value.strip('"')
    return values


class TestImageDependencyClosure:
    """The image installs the closure pinned in ``uv.lock``, not a fresh
    resolve against the open ranges in pyproject.toml."""

    def test_builder_installs_the_exported_lock_with_hashes(self) -> None:
        builder = _dockerfile_stages()["builder"]
        assert re.search(r"uv export --locked\b", builder), (
            "the builder stage must export its requirements from uv.lock "
            "with --locked, so a stale lock fails the build"
        )
        assert re.search(r"pip install --require-hashes --no-deps\b", builder), (
            "the exported lock must be installed hash-checked and without "
            "pip resolving anything of its own"
        )
        assert re.search(r"^COPY [^\n]*\buv\.lock\b", builder, re.MULTILINE), (
            "uv.lock is not in the builder stage's build context"
        )

    def test_no_stage_installs_the_project_by_resolving_it(self) -> None:
        for name, stage in _dockerfile_stages().items():
            assert not re.search(r"pip install (?:--\S+ )*\.(?:\s|$)", stage), (
                f"stage {name!r} runs `pip install .`, which resolves the "
                "dependency closure from PyPI instead of uv.lock"
            )

    def test_uv_lock_is_not_excluded_from_the_build_context(self) -> None:
        patterns = [
            line.strip()
            for line in (REPO_ROOT / ".dockerignore").read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
        assert not any(fnmatch.fnmatch("uv.lock", p) for p in patterns)


class TestImageImportsTheWheel:
    """The runtime imports the installed wheel, so a file the wheel lacks
    fails in the image instead of being served from a source copy."""

    def test_runtime_has_no_copy_of_a_python_package_tree(
        self, pyproject: dict
    ) -> None:
        runtime = _dockerfile_stages()["runtime"]
        # src/arxmcp/ops/ is copied on its own: operators run its scripts by
        # path inside the container, and it is not on sys.path.
        shadowing = [
            tree
            for tree in _shipped_trees(pyproject)
            if re.search(rf"^COPY {re.escape(tree)}/ ", runtime, re.MULTILINE)
        ]
        assert not shadowing, (
            f"the runtime stage copies {shadowing} beside the installed "
            "wheel; with /app as the working directory those copies are "
            "what `python -m arxmcp.server.main` imports"
        )
        assert not re.search(r"^COPY [^\n]*\bpyproject\.toml\b", runtime, re.MULTILINE), (
            "a pyproject.toml next to the code makes the server treat /app "
            "as a source checkout"
        )

    def test_working_directory_is_not_on_sys_path(self) -> None:
        env = _env_values(_dockerfile_stages()["runtime"])
        assert env.get("PYTHONSAFEPATH") == "1", (
            "without PYTHONSAFEPATH=1, `python -m` puts /app ahead of "
            "site-packages and /app/ops shadows the installed ops package"
        )

    def test_data_dir_is_the_declared_volume(self) -> None:
        runtime = _dockerfile_stages()["runtime"]
        volumes = re.findall(r"^VOLUME\s+(\S+)", runtime, re.MULTILINE)
        env = _env_values(runtime)
        assert env.get("ARXMCP_DATA_DIR") in volumes, (
            "an installed wheel defaults its data root to the user's home, "
            f"so ARXMCP_DATA_DIR must name the volume {volumes}; got "
            f"{env.get('ARXMCP_DATA_DIR')!r}"
        )


# ---------------------------------------------------------------------------
# The real clean-environment check — opt-in
# ---------------------------------------------------------------------------


@pytest.mark.requires_wheel_build
class TestCleanEnvironmentInstall:
    """Build the wheel, install it into a fresh venv, assert the ops
    scripts are present and the server boots.

    Opt-in (``pytest -m requires_wheel_build``) because it costs minutes
    and, in ``full`` mode, a ~2 GB dependency resolve. The static guards
    above are what run on every ``make test``.
    """

    def _run_check(self, mode: str) -> None:
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "src" / "arxmcp" / "tools" / "wheel_install_check.py"),
             "--mode", mode],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=3600,
        )
        assert proc.returncode == 0, (
            f"src/arxmcp/tools/wheel_install_check.py --mode {mode} failed:\n"
            f"{proc.stdout[-8000:]}\n{proc.stderr[-8000:]}"
        )

    def test_wheel_installs_clean_with_ops_scripts_present(self) -> None:
        """Fresh venv, --no-deps: the shipped inventory and the console
        scripts, without paying for a dependency resolve."""
        self._run_check("contents")

    def test_wheel_boots_in_a_fully_isolated_environment(self) -> None:
        """The trustworthy-release-m4 acceptance: isolated venv, real
        dependency set, ARXMCP_BOOTSTRAP_MODE=1 boot serving /healthz."""
        if os.environ.get("ARXMCP_RUN_FULL_WHEEL_CHECK") != "1":
            pytest.skip(
                "set ARXMCP_RUN_FULL_WHEEL_CHECK=1 to run the full isolated "
                "install (~4 min warm cache, ~2 GB resolve)"
            )
        self._run_check("full")
