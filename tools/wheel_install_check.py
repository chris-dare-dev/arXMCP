"""Clean-environment install check for the built wheel (issue #206).

Builds the project wheel, installs it into a FRESH virtual environment,
and asserts that what an operator actually receives matches what the docs
promise. This is the gate that would have caught every one of the five
packaging holes open until 2026-07-31:

===========================  ===================================================
missing from the wheel       what the operator saw
===========================  ===================================================
``ops/``                     no backup, no cutover, no restore drill, no drift
                             watchdog — and no error announcing their absence
console assets              ``create_app()`` crash: StaticFiles directory
                             ``.../frontend/static`` does not exist
``server/router_patterns``   ``RuntimeError: router_patterns.yaml missing``
``server/schemas/*.json``    the declared result-row source of truth absent
``tools/seed-papers.txt``    ``tools/fetch_seed.py`` cannot find the seed list
``[project.scripts]``        ``arxmcp-server: command not found`` — the FIRST
                             verification step in docs/install.md
===========================  ===================================================

**Why a separate environment is load-bearing.** Every one of those bugs is
invisible from a source checkout, because the repo root is on ``sys.path``
and the files are right there on disk. They only appear once imports must
resolve from site-packages. For the same reason every subprocess below runs
with ``cwd`` set OUTSIDE the repo — if the checks ran from the repo root,
``server/`` and ``frontend/`` in the working directory would shadow the
installed copies and the check would pass while shipping nothing.

Modes
-----

``contents`` (default)
    Fresh venv, wheel installed with ``--no-deps``, no network beyond the
    wheel itself. Asserts the shipped file inventory and that
    ``arxmcp-server --version`` / ``--help`` exit 0. This works with ZERO
    third-party packages installed because ``server/cli.py`` imports
    ``server.main`` lazily — which is the property that makes ``--help`` a
    meaningful install check rather than a full app construction.

``full``
    Everything in ``contents``, plus an isolated venv that resolves the
    real dependency set (~2 GB: torch, transformers, faiss) and a real
    server boot with ``ARXMCP_BOOTSTRAP_MODE=1`` polled at ``/healthz``.
    This is the honest pre-publish gate — run it before any PyPI upload
    (see docs/releasing.md). Measured ~4 min on a warm ``uv`` cache and
    ~15 min cold, dominated by the torch download.

    The boot additionally asserts that ``server.__file__`` resolves inside
    the child venv before it starts polling. Without that guard a stray
    ``PYTHONPATH`` or an editable install in an inherited environment could
    satisfy the import from the source tree and the check would pass while
    the wheel shipped nothing.

There is deliberately no "borrow the parent environment's dependencies"
mode. It was tried and removed: ``--system-site-packages`` exposes the
BASE interpreter's site-packages, and this project's dependencies live in
a ``.venv`` whose base is a bare CPython — so the borrow silently found
nothing and the boot died on ``ModuleNotFoundError: prometheus_client``.
A mode that can pass for the wrong reason is worse than a slow one.

Usage::

    python tools/wheel_install_check.py                 # contents
    python tools/wheel_install_check.py --mode full     # + deps + boot
    make wheel-check
    make wheel-check-full

Exit code is 0 on success, 1 on the first failed assertion (each failure
prints what was expected and what the wheel actually contained).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Files an operator must find in the installed distribution, expressed as
#: paths relative to site-packages. Each entry is a bug that shipped.
REQUIRED_INSTALLED_FILES: tuple[str, ...] = (
    # ops/ — the operability layer (issue #206). The .py modules AND the
    # shell halves the docs/ops/ runbooks actually invoke.
    "ops/__init__.py",
    "ops/cutover.py",
    "ops/cutover.sh",
    "ops/restore_drill.sh",
    "ops/restore_drill_check.py",
    "ops/drift_check.py",
    "ops/watchdog_eval.py",
    "ops/checkpoint_notebooks_db.py",
    "ops/restic-env.sh.template",
    "ops/cron/arxmcp-backup.sh",
    "ops/cron/arxmcp-cron.cron",
    "ops/systemd/arxmcp-backup.service",
    "ops/systemd/arxmcp-backup.timer",
    # server/frontend/ — operator console (issue #195 / trustworthy-release-m4).
    # Absent, create_app() raises before serving a single request. Sited
    # under server/ rather than top-level so the wheel does not claim the
    # generic name ``frontend`` in the installing environment's
    # site-packages; the paths below are the assertion that the move is
    # actually reflected in the built artifact.
    "server/frontend/templates/base.html",
    "server/frontend/templates/index.html",
    "server/frontend/templates/notebook_detail.html",
    "server/frontend/static/htmx.min.js",
    "server/frontend/static/app.css",
    # Data files inside already-declared packages that no package-data glob
    # covered, so setuptools dropped them silently.
    "server/router_patterns.yaml",
    "server/schemas/search_papers_result.json",
    "server/schemas/lean_verify_result.json",
    "tools/seed-papers.txt",
)

#: Console scripts docs/install.md tells the operator to expect on $PATH.
REQUIRED_CONSOLE_SCRIPTS: tuple[str, ...] = ("arxmcp-server", "arxmcp-shim")


class CheckFailed(Exception):
    """A packaging assertion failed. Message is operator-facing."""


def _log(msg: str) -> None:
    print(f"[wheel-install-check] {msg}", flush=True)


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 900,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _have_uv() -> bool:
    return shutil.which("uv") is not None


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build_wheel(out_dir: Path) -> Path:
    """Build the project wheel into ``out_dir`` and return its path.

    Cleans up the transient ``build/`` directory setuptools drops in the
    repo root, but only if it did not already exist — a developer's own
    build tree is never removed.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    build_dir = REPO_ROOT / "build"
    build_dir_preexisted = build_dir.exists()

    if _have_uv():
        cmd = ["uv", "build", "--wheel", "--out-dir", str(out_dir), str(REPO_ROOT)]
    else:
        cmd = [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--outdir",
            str(out_dir),
            str(REPO_ROOT),
        ]

    _log(f"building wheel: {' '.join(cmd)}")
    proc = _run(cmd, cwd=REPO_ROOT)
    if proc.returncode != 0:
        raise CheckFailed(
            "wheel build failed.\n"
            f"  command: {' '.join(cmd)}\n"
            f"  stdout: {proc.stdout[-4000:]}\n"
            f"  stderr: {proc.stderr[-4000:]}"
        )

    if not build_dir_preexisted and build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)

    wheels = sorted(out_dir.glob("*.whl"))
    if not wheels:
        raise CheckFailed(f"wheel build reported success but {out_dir} holds no .whl")
    _log(f"built {wheels[-1].name}")
    return wheels[-1]


def assert_wheel_contents(wheel: Path) -> None:
    """Inspect the zip directly — cheapest possible signal, and it runs
    before any venv exists so a broken wheel fails fast."""
    names = set(zipfile.ZipFile(wheel).namelist())
    missing = [p for p in REQUIRED_INSTALLED_FILES if p not in names]
    if missing:
        raise CheckFailed(
            f"{wheel.name} is missing {len(missing)} required file(s):\n"
            + "\n".join(f"  - {p}" for p in missing)
            + "\n\nAdd the tree to [tool.setuptools.packages.find].include and a "
            "matching glob to [tool.setuptools.package-data] in pyproject.toml. "
            "Declaring the package alone ships only its .py modules."
        )
    _log(
        f"wheel contents OK ({len(names)} entries, "
        f"{len(REQUIRED_INSTALLED_FILES)} required present)"
    )


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


def _venv_bin(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def _venv_python(venv: Path) -> Path:
    return _venv_bin(venv) / ("python.exe" if os.name == "nt" else "python")


def _script_path(venv: Path, name: str) -> Path:
    return _venv_bin(venv) / (f"{name}.exe" if os.name == "nt" else name)


def create_venv(venv: Path, *, system_site_packages: bool) -> None:
    if _have_uv():
        cmd = ["uv", "venv", str(venv)]
        if system_site_packages:
            cmd.append("--system-site-packages")
    else:
        cmd = [sys.executable, "-m", "venv"]
        if system_site_packages:
            cmd.append("--system-site-packages")
        cmd.append(str(venv))

    _log(f"creating venv (system_site_packages={system_site_packages})")
    proc = _run(cmd)
    if proc.returncode != 0:
        raise CheckFailed(f"venv creation failed:\n{proc.stdout}\n{proc.stderr}")


def install_wheel(venv: Path, wheel: Path, *, with_deps: bool) -> None:
    py = _venv_python(venv)
    if _have_uv():
        cmd = ["uv", "pip", "install", "--python", str(py)]
    else:
        cmd = [str(py), "-m", "pip", "install"]
    if not with_deps:
        cmd.append("--no-deps")
    cmd.append(str(wheel))

    _log(f"installing wheel (with_deps={with_deps})")
    proc = _run(cmd, timeout=3600)
    if proc.returncode != 0:
        raise CheckFailed(f"wheel install failed:\n{proc.stdout[-4000:]}\n{proc.stderr[-4000:]}")


# ---------------------------------------------------------------------------
# Assertions against the INSTALLED environment
# ---------------------------------------------------------------------------

#: Probe run inside the target venv. Emits JSON on stdout so the parent
#: reads structured facts rather than parsing prose.
_PROBE = r"""
import json, sys, sysconfig
from pathlib import Path

site = Path(sysconfig.get_paths()["purelib"])
required = json.loads(sys.argv[1])
present, missing = [], []
for rel in required:
    (present if (site / rel).is_file() else missing).append(rel)

print(json.dumps({
    "site_packages": str(site),
    "present": present,
    "missing": missing,
    "prefix": sys.prefix,
}))
"""


def assert_installed_files(venv: Path) -> str:
    """Assert the required files exist under the venv's site-packages.

    Deliberately checks the INSTALLED location rather than re-reading the
    wheel: a file can be in the zip and still not land (data_files vs
    package_data, RECORD mismatches, path normalization on Windows).
    """
    py = _venv_python(venv)
    proc = _run(
        [str(py), "-c", _PROBE, json.dumps(list(REQUIRED_INSTALLED_FILES))],
        cwd=Path(tempfile.gettempdir()),
    )
    if proc.returncode != 0:
        raise CheckFailed(f"probe failed inside venv:\n{proc.stdout}\n{proc.stderr}")

    data = json.loads(proc.stdout.strip().splitlines()[-1])
    if data["missing"]:
        raise CheckFailed(
            f"installed into {data['site_packages']} but "
            f"{len(data['missing'])} required file(s) absent:\n"
            + "\n".join(f"  - {p}" for p in data["missing"])
        )
    _log(f"installed files OK ({len(data['present'])} present under {data['site_packages']})")
    return data["site_packages"]


def assert_console_scripts(venv: Path) -> None:
    """Assert each documented binary exists AND runs.

    ``--version`` is the real assertion: it proves the entry-point target
    imports and its ``main`` is callable. It runs with zero third-party
    dependencies installed only because ``server/cli.py`` defers the
    ``server.main`` import into the function body.
    """
    for name in REQUIRED_CONSOLE_SCRIPTS:
        path = _script_path(venv, name)
        if not path.exists():
            raise CheckFailed(
                f"console script {name!r} not installed at {path}.\n"
                "docs/install.md tells the operator this binary is on $PATH after "
                "install; declare it in [project.scripts] in pyproject.toml."
            )

    # arxmcp-server is the one docs/install.md:175 names as the FIRST
    # verification step a new operator runs.
    exe = _script_path(venv, "arxmcp-server")
    for flag in ("--version", "--help"):
        proc = _run([str(exe), flag], cwd=Path(tempfile.gettempdir()), timeout=120)
        if proc.returncode != 0:
            raise CheckFailed(
                f"`arxmcp-server {flag}` exited {proc.returncode} in a clean env:\n"
                f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
            )
    _log("console scripts OK (arxmcp-server --version / --help exit 0)")


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def assert_boots(venv: Path, site_packages: str) -> None:
    """Boot the installed server and poll ``/healthz``.

    Runs from a temp cwd so the repo's own ``server/`` and ``frontend/``
    cannot shadow the installed copies, and asserts up front that
    ``server`` really resolves inside this venv — otherwise a parent
    editable install would make the whole check vacuous.
    """
    py = _venv_python(venv)
    tmp_cwd = Path(tempfile.mkdtemp(prefix="arxmcp-boot-cwd-"))
    data_dir = Path(tempfile.mkdtemp(prefix="arxmcp-boot-data-"))

    try:
        shadow = _run(
            [str(py), "-c", "import server, sys; print(server.__file__)"],
            cwd=tmp_cwd,
        )
        if shadow.returncode != 0:
            raise CheckFailed(
                f"cannot import `server` from the installed wheel:\n"
                f"{shadow.stdout}\n{shadow.stderr}"
            )
        resolved = shadow.stdout.strip()
        if not resolved.lower().startswith(site_packages.lower()):
            raise CheckFailed(
                "SHADOWED: `import server` resolved to\n"
                f"  {resolved}\n"
                f"but this venv's site-packages is\n  {site_packages}\n"
                "The boot check would be testing the source tree, not the wheel. "
                "Re-run with --mode full for a fully isolated environment."
            )

        port = _free_port()
        env = dict(os.environ)
        env.pop("ARXMCP_CONTACT_EMAIL", None)  # server rejects this ingest-only var
        env.update(
            {
                "ARXMCP_BOOTSTRAP_MODE": "1",
                "ARXMCP_BIND_HOST": "127.0.0.1",
                "ARXMCP_BIND_PORT": str(port),
                "ARXMCP_DATA_DIR": str(data_dir),
                "ARXMCP_LOG_LEVEL": "INFO",
                "PYTHONUNBUFFERED": "1",
            }
        )

        exe = _script_path(venv, "arxmcp-server")
        # Stream the child's stdout+stderr to a file rather than a pipe.
        # A pipe can only be drained by read(), which blocks until EOF, so
        # on a HANG (as opposed to a crash) the diagnostic output would be
        # stuck in the OS buffer and unreadable — exactly the case where it
        # is most needed. A file is readable at any moment.
        log_path = tmp_cwd / "server-boot.log"
        _log(f"booting {exe.name} on 127.0.0.1:{port} with ARXMCP_BOOTSTRAP_MODE=1")
        _log(f"  child log: {log_path}")
        log_handle = log_path.open("w", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(
            [str(exe)],
            cwd=str(tmp_cwd),
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )

        def _tail() -> str:
            try:
                return log_path.read_text(encoding="utf-8", errors="replace")[-6000:]
            except OSError:
                return "(child log unreadable)"

        url = f"http://127.0.0.1:{port}/healthz"
        # 300s matches the 5-minute HEALTHCHECK start-period in
        # docker/Dockerfile.server, which exists for the same reason: a
        # first boot may pay a cold model/import cost this check must not
        # mistake for a hang.
        deadline = time.monotonic() + 300
        last_err: str = "never attempted"
        try:
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise CheckFailed(
                        f"server exited with code {proc.returncode} before serving "
                        f"/healthz:\n{_tail()}"
                    )
                try:
                    with urllib.request.urlopen(url, timeout=5) as resp:
                        if resp.status == 200:
                            _log(f"/healthz returned 200 — clean-env boot OK (port {port})")
                            return
                        last_err = f"HTTP {resp.status}"
                except (urllib.error.URLError, OSError, TimeoutError) as exc:
                    last_err = str(exc)
                time.sleep(1.0)

            raise CheckFailed(
                f"/healthz never returned 200 within 300s (last error: {last_err})\n"
                f"child output:\n{_tail()}"
            )
        finally:
            log_handle.close()
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=30)
    finally:
        shutil.rmtree(tmp_cwd, ignore_errors=True)
        shutil.rmtree(data_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run_check(mode: str, keep: bool = False) -> None:
    workdir = Path(tempfile.mkdtemp(prefix="arxmcp-wheel-check-"))
    _log(f"workdir {workdir} (mode={mode})")
    try:
        wheel = build_wheel(workdir / "dist")
        assert_wheel_contents(wheel)

        venv = workdir / "venv"
        create_venv(venv, system_site_packages=False)
        install_wheel(venv, wheel, with_deps=(mode == "full"))

        site_packages = assert_installed_files(venv)
        assert_console_scripts(venv)

        if mode == "full":
            assert_boots(venv, site_packages)
        else:
            _log("skipping boot (mode=contents); use --mode full for the boot check")

        _log("ALL CHECKS PASSED")
    finally:
        if keep:
            _log(f"keeping {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wheel_install_check",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=("contents", "full"),
        default="contents",
        help=(
            "contents: fresh venv, --no-deps, file inventory + --version/--help "
            "(fast, no network). full: isolated venv resolving the real "
            "dependency set (~2 GB) plus a real ARXMCP_BOOTSTRAP_MODE=1 boot "
            "polled at /healthz — the pre-publish gate."
        ),
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep the temporary workdir for inspection instead of deleting it",
    )
    args = parser.parse_args(argv)

    try:
        run_check(args.mode, keep=args.keep)
    except CheckFailed as exc:
        print(f"\nFAILED: {exc}\n", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
