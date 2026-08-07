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
import hashlib
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
from collections.abc import Mapping
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
    # ui-uplift-m7: app.css references every colour, duration and type value
    # through var(). If tokens.css is missing from the wheel the console
    # still SERVES — it renders with every custom property falling back to
    # its initial value, i.e. transparent surfaces and no scale. That is a
    # worse failure than a 500 because nothing errors.
    "server/frontend/static/tokens.css",
    # Data files inside already-declared packages that no package-data glob
    # covered, so setuptools dropped them silently.
    "server/router_patterns.yaml",
    "server/schemas/search_papers_result.json",
    "server/schemas/lean_verify_result.json",
    # desktop-distribution-m3: M4's installed server adapter imports this
    # dependency-light wire parser. A source checkout would hide its absence.
    "server/desktop_contract.py",
    "tools/seed-papers.txt",
)

#: Console scripts docs/install.md tells the operator to expect on $PATH.
REQUIRED_CONSOLE_SCRIPTS: tuple[str, ...] = ("arxmcp-server", "arxmcp-shim")

# Cargo-only developer experiments must never hitchhike into the production
# Python wheel through setuptools' implicit namespace discovery.
FORBIDDEN_WHEEL_PREFIXES: tuple[str, ...] = ("tools/desktop_lifecycle_spike/",)


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
    forbidden = sorted(
        name
        for name in names
        if any(name.startswith(prefix) for prefix in FORBIDDEN_WHEEL_PREFIXES)
    )
    if forbidden:
        raise CheckFailed(
            f"{wheel.name} contains {len(forbidden)} forbidden development file(s):\n"
            + "\n".join(f"  - {name}" for name in forbidden)
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


_CHILD_ENV_BLOCKED_PREFIXES: tuple[str, ...] = (
    "ARXMCP_",
    "DYLD_",
    "LD_",
    "PYTHON",
)
_CHILD_ENV_BLOCKED_KEYS: frozenset[str] = frozenset(
    {"OLDPWD", "PWD", "VIRTUAL_ENV"}
)


def build_relocated_child_environment(
    data_dir: Path,
    port: int,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a hermetic environment for the installed-wheel boot.

    The parent shell is developer-controlled and commonly contains an
    editable-install ``PYTHONPATH``, legacy ``ARXMCP_*`` path overrides, or
    platform cache locations.  Inheriting any of those makes a relocation
    check capable of passing while importing or writing outside its sandbox.
    Keep ordinary process settings (``PATH``, certificate locations, locale),
    remove every Python/loader/arXMCP influence, then reconstruct the complete
    writable environment beneath ``data_dir``.
    """
    source = os.environ if environ is None else environ
    env = {
        key: value
        for key, value in source.items()
        if key not in _CHILD_ENV_BLOCKED_KEYS
        and not key.startswith(_CHILD_ENV_BLOCKED_PREFIXES)
    }

    root = data_dir.resolve(strict=False)
    redirected = {
        "HOME": root / "runtime" / "home",
        "USERPROFILE": root / "runtime" / "home",
        "LOCALAPPDATA": root / "runtime" / "local-app-data",
        "APPDATA": root / "runtime" / "app-data",
        "XDG_DATA_HOME": root / "runtime" / "xdg-data",
        "XDG_CONFIG_HOME": root / "runtime" / "xdg-config",
        "XDG_CACHE_HOME": root / "cache" / "xdg",
        "HF_HOME": root / "cache" / "huggingface",
        "TRANSFORMERS_CACHE": root / "cache" / "huggingface",
        "MPLCONFIGDIR": root / "cache" / "matplotlib",
        "TMPDIR": root / "tmp",
        "TEMP": root / "tmp",
        "TMP": root / "tmp",
    }
    for path in set(redirected.values()):
        path.mkdir(parents=True, exist_ok=True)

    env.update({key: str(path) for key, path in redirected.items()})
    env.update(
        {
            "ARXMCP_BOOTSTRAP_MODE": "1",
            "ARXMCP_BIND_HOST": "127.0.0.1",
            "ARXMCP_BIND_PORT": str(port),
            "ARXMCP_DATA_DIR": str(root),
            "ARXMCP_LOG_LEVEL": "INFO",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


ManifestEntry = tuple[str, int, int, int, int, int, str, str]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def filesystem_metadata_manifest(
    root: Path, *, hash_contents: bool = False
) -> dict[str, ManifestEntry]:
    """Return a stable, recursive manifest for mutation detection.

    The always-on unit checks use metadata plus inode/change time.  The opt-in
    full-wheel gate passes ``hash_contents=True`` so an equal-size rewrite with
    a restored mtime cannot evade the pre-publish confinement proof.
    """
    if not root.exists():
        return {}
    manifest: dict[str, ManifestEntry] = {}
    for path in sorted(root.rglob("*")):
        try:
            stat = path.lstat()
        except FileNotFoundError:
            # A concurrently-removed transient is itself caught by its parent
            # directory's mtime; do not make the observer race-prone.
            continue
        if path.is_symlink():
            kind = "symlink"
            target = os.readlink(path)
        elif path.is_dir():
            kind = "dir"
            target = ""
        elif path.is_file():
            kind = "file"
            target = ""
        else:
            kind = "other"
            target = ""
        manifest[path.relative_to(root).as_posix()] = (
            kind,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
            stat.st_ino,
            stat.st_mode,
            target,
            _sha256_file(path) if hash_contents and kind == "file" else "",
        )
    return manifest


def changed_manifest_paths(
    before: Mapping[str, ManifestEntry],
    after: Mapping[str, ManifestEntry],
) -> list[str]:
    """Return sorted paths added, removed, or metadata-modified."""
    return sorted(
        path
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    )


def assert_manifest_unchanged(
    label: str,
    before: Mapping[str, ManifestEntry],
    after: Mapping[str, ManifestEntry],
) -> None:
    """Raise when a watched tree changed during installed execution."""
    changed = changed_manifest_paths(before, after)
    if changed:
        rendered = "\n".join(f"  - {path}" for path in changed[:50])
        suffix = "\n  - ..." if len(changed) > 50 else ""
        raise CheckFailed(
            f"installed runtime mutated {label} outside ARXMCP_DATA_DIR:\n"
            f"{rendered}{suffix}"
        )


def assert_manifest_changes_confined(
    label: str,
    before: Mapping[str, ManifestEntry],
    after: Mapping[str, ManifestEntry],
    *,
    allowed_prefix: str,
) -> None:
    """Raise unless every manifest delta is at or below one relative path."""
    changed = changed_manifest_paths(before, after)
    unexpected = [
        path
        for path in changed
        if path != allowed_prefix and not path.startswith(f"{allowed_prefix}/")
    ]
    if unexpected:
        rendered = "\n".join(f"  - {path}" for path in unexpected[:50])
        suffix = "\n  - ..." if len(unexpected) > 50 else ""
        raise CheckFailed(
            f"installed runtime escaped {label}'s allowed "
            f"{allowed_prefix!r} subtree:\n{rendered}{suffix}"
        )


_WRITER_PROBE = r"""
import asyncio, json

from ingest.store import write_corpus_version_marker
from server.cache import RetrievalCache
from server.config import Config
from server.operator_settings import get_setting, set_setting

async def main():
    config = Config()
    paths = config.application_paths
    paths.prepare()

    cache = await RetrievalCache.open(config.cache_db_path, corpus_version=1)
    await cache.close()
    set_setting("desktop_relocation_probe", "ok", config.notebooks_db_path)
    settings_value = get_setting(
        "desktop_relocation_probe", config.notebooks_db_path
    )
    if settings_value != "ok":
        raise RuntimeError(
            "operator settings probe did not persist desktop_relocation_probe"
        )
    write_corpus_version_marker(
        config.lancedb_path,
        version=1,
        chunker_version="relocation-probe",
        embedder_version="relocation-probe",
        paper_count=0,
        chunk_count=0,
    )

    print(json.dumps({
        "mode": paths.mode,
        "root": str(paths.root),
        "notebooks": str(paths.notebooks),
        "retrieval_cache": str(config.cache_db_path),
        "settings_db": str(config.notebooks_db_path),
        "settings_value": settings_value,
        "corpus_marker": str(config.lancedb_path / "corpus-version.json"),
        "logs": str(paths.logs),
    }, sort_keys=True))

asyncio.run(main())
"""


def _post_smoke_notebook(port: int) -> None:
    body = json.dumps(
        {"slug": "relocation-smoke", "display_name": "Relocation smoke"}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/ui/api/notebooks",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = response.read().decode("utf-8", errors="replace")
            if response.status != 201:
                raise CheckFailed(
                    "live installed notebook create returned "
                    f"HTTP {response.status}: {payload[-2000:]}"
                )
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise CheckFailed(
            "live installed notebook create returned "
            f"HTTP {exc.code}: {payload[-2000:]}"
        ) from exc


def _assert_path_inside(root: Path, raw_path: str, label: str) -> Path:
    path = Path(raw_path).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise CheckFailed(
            f"writer probe reported {label} outside ARXMCP_DATA_DIR: {path}"
        ) from exc
    return path


def _assert_installed_provenance(
    resolved_module: str, site_packages: str
) -> Path:
    """Require the imported module to be canonically inside site-packages."""
    try:
        module_path = Path(resolved_module).resolve(strict=True)
        site_path = Path(site_packages).resolve(strict=True)
        module_path.relative_to(site_path)
    except (OSError, ValueError) as exc:
        raise CheckFailed(
            "SHADOWED: `import server` resolved to\n"
            f"  {resolved_module}\n"
            f"but this venv's canonical site-packages is\n  {site_packages}\n"
            "The boot check would not be testing the installed wheel."
        ) from exc
    return module_path


def _installed_ingest_paths(py: Path, cwd: Path, env: dict[str, str]) -> dict[str, str]:
    """Ask the real installed notebook-ingest entry module for writer paths."""
    proc = _run(
        [str(py), "-m", "tools.notebook_ingest", "--print-runtime-paths"],
        cwd=cwd,
        env=env,
        timeout=120,
    )
    if proc.returncode != 0:
        raise CheckFailed(
            "installed notebook-ingest path probe failed:\n"
            f"{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}"
        )
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise CheckFailed(
            "installed notebook-ingest path probe emitted no valid JSON"
        ) from exc


def assert_boots(venv: Path, site_packages: str) -> None:
    """Boot the installed server and prove all writes stay under one root.

    Besides ``/healthz``, this exercises the live notebook HTTP writer and
    the cache/settings/corpus-marker writers.  Parent-side manifests watch
    the checkout, installed venv, arbitrary CWD, and complete boot sandbox;
    only the sandbox's ``data/`` subtree may change.
    """
    py = _venv_python(venv)
    sandbox = Path(tempfile.mkdtemp(prefix="arxmcp-boot-sandbox-"))
    tmp_cwd = sandbox / "cwd"
    data_dir = sandbox / "data"
    tmp_cwd.mkdir()
    data_dir.mkdir()

    try:
        port = _free_port()
        env = build_relocated_child_environment(data_dir, port)
        shadow = _run(
            [str(py), "-c", "import server, sys; print(server.__file__)"],
            cwd=tmp_cwd,
            env=env,
        )
        if shadow.returncode != 0:
            raise CheckFailed(
                f"cannot import `server` from the installed wheel:\n"
                f"{shadow.stdout}\n{shadow.stderr}"
            )
        resolved = shadow.stdout.strip()
        _assert_installed_provenance(resolved, site_packages)

        watched_before = {
            "source checkout": filesystem_metadata_manifest(
                REPO_ROOT, hash_contents=True
            ),
            "installed application parent": filesystem_metadata_manifest(
                venv.parent, hash_contents=True
            ),
            "arbitrary boot CWD": filesystem_metadata_manifest(
                tmp_cwd, hash_contents=True
            ),
            "boot sandbox": filesystem_metadata_manifest(
                sandbox, hash_contents=True
            ),
        }

        exe = _script_path(venv, "arxmcp-server")
        # Stream the child's stdout+stderr to a file rather than a pipe.
        # A pipe can only be drained by read(), which blocks until EOF, so
        # on a HANG (as opposed to a crash) the diagnostic output would be
        # stuck in the OS buffer and unreadable — exactly the case where it
        # is most needed. A file is readable at any moment.
        log_path = data_dir / "logs" / "server-boot.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
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
        healthy = False
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
                            healthy = True
                            break
                        last_err = f"HTTP {resp.status}"
                except (urllib.error.URLError, OSError, TimeoutError) as exc:
                    last_err = str(exc)
                time.sleep(1.0)

            if not healthy:
                raise CheckFailed(
                    f"/healthz never returned 200 within 300s "
                    f"(last error: {last_err})\nchild output:\n{_tail()}"
                )

            _post_smoke_notebook(port)
            _log("live POST /ui/api/notebooks returned 201")

            writer = _run(
                [str(py), "-c", _WRITER_PROBE],
                cwd=tmp_cwd,
                env=env,
                timeout=120,
            )
            if writer.returncode != 0:
                raise CheckFailed(
                    "installed writer probe failed:\n"
                    f"{writer.stdout[-3000:]}\n{writer.stderr[-3000:]}"
                )
            try:
                writer_data = json.loads(writer.stdout.strip().splitlines()[-1])
            except (IndexError, json.JSONDecodeError) as exc:
                raise CheckFailed(
                    "installed writer probe emitted no valid JSON:\n"
                    f"{writer.stdout[-3000:]}\n{writer.stderr[-3000:]}"
                ) from exc
            if writer_data.get("mode") != "installed":
                raise CheckFailed(
                    "writer probe did not exercise installed path mode: "
                    f"{writer_data.get('mode')!r}"
                )
            if writer_data.get("settings_value") != "ok":
                raise CheckFailed(
                    "writer probe did not read back the persisted settings value"
                )
            canonical_data = data_dir.resolve(strict=False)
            for label, raw_path in writer_data.items():
                if label in {"mode", "settings_value"}:
                    continue
                _assert_path_inside(canonical_data, raw_path, label)

            ingest_paths = _installed_ingest_paths(py, tmp_cwd, env)
            if ingest_paths.get("mode") != "installed":
                raise CheckFailed(
                    "notebook-ingest path probe did not exercise installed mode"
                )
            for label, raw_path in ingest_paths.items():
                if label == "mode":
                    continue
                _assert_path_inside(canonical_data, raw_path, label)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=30)
            log_handle.close()

        expected = (
            data_dir / "notebooks" / "relocation-smoke",
            data_dir / "cache" / "retrieval.db",
            data_dir / "cache" / "notebooks.db",
            data_dir / "index" / "lancedb" / "corpus-version.json",
            log_path,
        )
        missing = [path for path in expected if not path.exists()]
        if missing:
            raise CheckFailed(
                "installed boot did not create expected application state:\n"
                + "\n".join(f"  - {path}" for path in missing)
            )

        watched_after = {
            "source checkout": filesystem_metadata_manifest(
                REPO_ROOT, hash_contents=True
            ),
            "installed application parent": filesystem_metadata_manifest(
                venv.parent, hash_contents=True
            ),
            "arbitrary boot CWD": filesystem_metadata_manifest(
                tmp_cwd, hash_contents=True
            ),
            "boot sandbox": filesystem_metadata_manifest(
                sandbox, hash_contents=True
            ),
        }
        for label in (
            "source checkout",
            "installed application parent",
            "arbitrary boot CWD",
        ):
            assert_manifest_unchanged(
                label, watched_before[label], watched_after[label]
            )
        assert_manifest_changes_confined(
            "boot sandbox",
            watched_before["boot sandbox"],
            watched_after["boot sandbox"],
            allowed_prefix="data",
        )
        data_delta = [
            path
            for path in changed_manifest_paths(
                watched_before["boot sandbox"],
                watched_after["boot sandbox"],
            )
            if path == "data" or path.startswith("data/")
        ]
        _log(f"application-data manifest delta ({len(data_delta)} paths):")
        for path in data_delta:
            _log(f"  {path}")
        _log("notebook/cache/settings/corpus-marker/log writes confined to data root")
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


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
