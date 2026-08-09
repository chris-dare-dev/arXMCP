"""Desktop-bundle build driver (desktop-distribution-m7).

Builds the PyInstaller ``onedir`` sidecar from the committed spec and proves
its hygiene: provisions a uv-locked build venv (PyInstaller hash-pinned via
``requirements-build.txt``, deliberately OUTSIDE ``pyproject.toml``/``uv.lock``
per the MinerU precedent), installs the freshly built wheel, sanitizes the
``direct_url.json`` build-path leak BEFORE freezing, builds with explicit
``--workpath``/``--distpath`` under ``var/desktop-package/`` (the ``build/``
default collides with unrelated setuptools output), then scans every regular
file — including nested zips and the executables' embedded PYZ archives, where
compressed ``.pyc`` bytes hide from a raw grep — for build-machine path
strings. ``verify`` additionally runs TWO independent builds and diffs their
per-file manifests against the CLOSED exception set below.

Deliberately not shipped in the wheel: lives outside the packaged trees.
Subprocess side effects only: ``uv`` invocations plus writes under
``var/desktop-package/`` (gitignored). Network only on first provisioning.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

PYINSTALLER_DIR = Path(__file__).resolve().parent
REPO_ROOT = PYINSTALLER_DIR.parents[2]
SPEC_PATH = PYINSTALLER_DIR / "arxmcp_desktop.spec"
BUILD_REQUIREMENTS = PYINSTALLER_DIR / "requirements-build.txt"
EMBEDDED_SCAN_HELPER = PYINSTALLER_DIR / "scan_embedded.py"
DEFAULT_ROOT = REPO_ROOT / "var" / "desktop-package"
BUNDLE_NAME = "arxmcp-desktop-child"
CHILD_EXE = "arxmcp-desktop-child"
PROBE_EXE = "arxmcp-desktop-probe"
#: Non-``ARXMCP_``-prefixed on purpose: the server FATALs on unknown
#: ``ARXMCP_*`` vars in an operator shell (DESKTOP_SUPERVISOR_BIN precedent).
BUILD_VENV_ENV_VAR = "DESKTOP_BUILD_VENV"

#: AC1's CLOSED exception set: bundle-relative paths allowed to differ between
#: two builds of the same commit. Measured EMPTY (2026-08-09, PyInstaller
#: 6.21.0, py3.12.13, macOS arm64) — but only because the spec sorts the two
#: measured ordering drifts (base_library.zip members; PYZ TOC), both
#: name-keyed archives whose write order follows module-graph enumeration.
#: Any future entry needs its own "why unavoidable" line here AND a bump of
#: the pinned count mirrored in tests/test_desktop_package.py.
NONDETERMINISTIC_EXCEPTIONS: frozenset[str] = frozenset()
EXPECTED_EXCEPTION_COUNT = 0

if len(NONDETERMINISTIC_EXCEPTIONS) != EXPECTED_EXCEPTION_COUNT:
    raise RuntimeError(
        "NONDETERMINISTIC_EXCEPTIONS size drifted from EXPECTED_EXCEPTION_COUNT; "
        "bump both here and in tests/test_desktop_package.py"
    )

#: Passed through to the build subprocesses when set. None perturbs
#: determinism the way PYTHONPATH would, and dropping them silently breaks
#: provisioning on a proxied or custom-CA box.
_PASSTHROUGH_ENV = (
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "https_proxy",
    "http_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
)


class BuildError(RuntimeError):
    """A packaging step failed; message is operator-facing."""


def _log(msg: str) -> None:
    print(f"[desktop-package] {msg}", flush=True)


def _run(
    cmd: list[str],
    *,
    env: dict[str, str],
    cwd: Path | None = None,
    timeout: int = 1800,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise BuildError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"  stdout: {proc.stdout[-4000:]}\n"
            f"  stderr: {proc.stderr[-4000:]}"
        )
    return proc


def _tool_env(*, config_dir: Path | None = None) -> dict[str, str]:
    """Minimal env for uv/PyInstaller: no PYTHONPATH so nothing resolves from
    the checkout, fixed hash seed + SOURCE_DATE_EPOCH for reproducible pycs.

    ``config_dir`` sets ``PYINSTALLER_CONFIG_DIR`` (PyInstaller's
    ``compat.CONF_DIR``). Without it every build shares the user-level bincache
    under ``$HOME``, so a second "independent" build REPLAYS the first build's
    processed, ad-hoc-signed Mach-O binaries instead of reproducing them — the
    file class most likely to carry nondeterminism.
    """
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(Path.home()),
        "TMPDIR": tempfile.gettempdir(),
        "LANG": "en_US.UTF-8",
        "PYTHONHASHSEED": "0",
        "SOURCE_DATE_EPOCH": "315532800",
    }
    for name in _PASSTHROUGH_ENV:
        value = os.environ.get(name)
        if value:
            env[name] = value
    if config_dir is not None:
        env["PYINSTALLER_CONFIG_DIR"] = str(config_dir)
    return env


def _uv() -> str:
    uv = shutil.which("uv")
    if uv is None:
        raise BuildError("uv is required on PATH to provision the build venv")
    return uv


def build_venv_dir(root: Path) -> Path:
    override = os.environ.get(BUILD_VENV_ENV_VAR)
    return Path(override).resolve() if override else root / "build-venv"


def _venv_python(venv: Path) -> Path:
    exe = venv / ("Scripts" if os.name == "nt" else "bin") / "python"
    if os.name == "nt":
        exe = exe.with_suffix(".exe")
    return exe


def _site_packages(venv: Path) -> Path:
    candidates = sorted(venv.glob("lib/python3.*/site-packages"))
    if not candidates:
        raise BuildError(f"no site-packages under {venv}")
    return candidates[-1]


def build_wheel(root: Path, env: dict[str, str]) -> Path:
    """``uv build --wheel``; preserves a pre-existing repo-root ``build/``
    scratch tree (wheel_install_check precedent)."""
    out_dir = root / "wheels"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.whl"):
        old.unlink()
    scratch = REPO_ROOT / "build"
    scratch_preexisted = scratch.exists()
    _run(
        [_uv(), "build", "--wheel", "--out-dir", str(out_dir), str(REPO_ROOT)],
        env=env,
        cwd=REPO_ROOT,
    )
    if not scratch_preexisted and scratch.exists():
        shutil.rmtree(scratch, ignore_errors=True)
    wheels = sorted(out_dir.glob("*.whl"))
    if not wheels:
        raise BuildError(f"wheel build produced nothing in {out_dir}")
    return wheels[-1]


def provision(root: Path) -> tuple[Path, Path]:
    """Create/refresh the build venv; returns ``(venv_python, site_packages)``.

    Layering: uv.lock runtime deps (no dev, no project) -> the freshly built
    arxmcp wheel (``--no-deps``, regenerating the ``direct_url.json`` leak the
    sanitizer must observe) -> hash-pinned PyInstaller stack on top.
    """
    env = _tool_env()
    venv = build_venv_dir(root)
    uv = _uv()
    sync_env = dict(env, UV_PROJECT_ENVIRONMENT=str(venv))
    _log(f"syncing locked runtime deps into {venv}")
    _run(
        [
            uv,
            "sync",
            "--locked",
            "--no-dev",
            "--no-install-project",
            "--python",
            "3.12",
        ],
        env=sync_env,
        cwd=REPO_ROOT,
    )
    wheel = build_wheel(root, env)
    python = _venv_python(venv)
    _log(f"installing {wheel.name} + pinned PyInstaller stack")
    _run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            "--force-reinstall",
            str(wheel),
        ],
        env=env,
        cwd=REPO_ROOT,
    )
    _run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(python),
            "--require-hashes",
            "-r",
            str(BUILD_REQUIREMENTS),
        ],
        env=env,
        cwd=REPO_ROOT,
    )
    return python, _site_packages(venv)


def sanitize_direct_url(site_packages: Path) -> dict[str, object]:
    """Delete ``arxmcp-*.dist-info/direct_url.json`` (the measured build-path
    leak) so the frozen bundle cannot inherit it; reports the pre-state."""
    matches = sorted(site_packages.glob("arxmcp-*.dist-info/direct_url.json"))
    report: dict[str, object] = {
        "found": bool(matches),
        "leak_observed": False,
        "removed": [],
    }
    for path in matches:
        raw = path.read_text(encoding="utf-8")
        if "file://" in raw:
            report["leak_observed"] = True
        path.unlink()
        report["removed"].append(str(path.relative_to(site_packages)))
    return report


def config_dir_for(workpath: Path) -> Path:
    """Per-build PyInstaller ``CONF_DIR`` (bincache). Lives under the workpath,
    which ``build_bundle`` rmtrees, so every build starts with a COLD cache."""
    return workpath / "pyi-conf"


def build_bundle(python: Path, workpath: Path, distpath: Path) -> Path:
    """One PyInstaller invocation into fresh, explicit work/dist paths, with a
    per-build config dir so no binary is copied out of another build's cache."""
    for path in (workpath, distpath / BUNDLE_NAME):
        if path.exists():
            shutil.rmtree(path)
    workpath.mkdir(parents=True, exist_ok=True)
    distpath.mkdir(parents=True, exist_ok=True)
    config_dir = config_dir_for(workpath)
    config_dir.mkdir(parents=True, exist_ok=True)
    _log(f"pyinstaller -> {distpath} (config dir {config_dir})")
    _run(
        [
            str(python),
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--workpath",
            str(workpath),
            "--distpath",
            str(distpath),
            str(SPEC_PATH),
        ],
        env=_tool_env(config_dir=config_dir),
        cwd=workpath,
        timeout=1800,
    )
    bundle = distpath / BUNDLE_NAME
    if not (bundle / CHILD_EXE).is_file() or not (bundle / PROBE_EXE).is_file():
        raise BuildError(f"bundle at {bundle} is missing its executables")
    return bundle


def file_manifest(root: Path) -> dict[str, str]:
    """Per-entry ``mode:size:sha256`` (symlinks hash their target), keyed by
    bundle-relative posix path. mtimes are deliberately excluded."""
    manifest: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        meta = path.lstat()
        rel = path.relative_to(root).as_posix()
        if stat.S_ISLNK(meta.st_mode):
            digest = hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest()
        elif stat.S_ISREG(meta.st_mode):
            h = hashlib.sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    h.update(chunk)
            digest = h.hexdigest()
        else:
            digest = "dir"
        manifest[rel] = f"{meta.st_mode:o}:{meta.st_size}:{digest}"
    return manifest


def manifest_diff(a: dict[str, str], b: dict[str, str]) -> list[str]:
    """Relative paths present in only one manifest or differing in value."""
    return sorted(
        path for path in set(a) | set(b) if a.get(path) != b.get(path)
    )


def default_needles(*, build_paths: tuple[Path, ...] = ()) -> dict[str, bytes]:
    """Host-specific strings whose presence in the bundle is a build leak.

    Both the raw and the ``realpath`` form of the temp root and ``$HOME`` are
    emitted when they differ: on macOS ``TMPDIR`` is ``/var/folders/...`` while
    its realpath is ``/private/var/folders/...``, and the toolchain embeds
    whichever form it was handed — searching only one silently matches nothing.

    ``build_paths`` (repo root, workpath, distpath) covers the build directory
    itself, which is scanned only incidentally when the checkout happens to sit
    under ``$HOME``. A path already covered by a broader needle is dropped:
    anything containing it contains the prefix too.
    """
    home = str(Path.home())
    tmp = tempfile.gettempdir()
    needles = {
        "home": home.encode(),
        "user": Path.home().name.encode(),
        "tmp": tmp.encode(),
    }
    if os.path.realpath(home) != home:
        needles["home_real"] = os.path.realpath(home).encode()
    if os.path.realpath(tmp) != tmp:
        needles["tmp_real"] = os.path.realpath(tmp).encode()
    covered = list(needles.values())
    for index, path in enumerate(build_paths):
        for candidate in {str(path), os.path.realpath(path)}:
            raw = candidate.encode()
            if any(prefix in raw for prefix in covered):
                continue
            needles[f"build_path_{index}_{len(needles)}"] = raw
            covered.append(raw)
    return needles


def _scan_bytes(data: bytes, needles: dict[str, bytes]) -> list[str]:
    return [label for label, needle in needles.items() if needle in data]


def scan_tree(
    root: Path, needles: dict[str, bytes], python: Path | None = None
) -> dict[str, object]:
    """Byte-scan EVERY regular file, plus two nested scopes a raw grep cannot
    reach: entries of any ``*.zip`` (base_library.zip) and — via the build
    venv's PyInstaller readers — the executables' embedded PYZ archives, where
    module ``.pyc`` bytes (``co_filename``) live zlib-compressed.

    The bytes-read-vs-lstat cross-check is the tripwire against an
    early-return or a glob that skips extensionless/large files.
    """
    import zipfile

    hits: dict[str, list[str]] = {}
    files_scanned = 0
    bytes_scanned = 0
    lstat_bytes = 0
    pyc_members = 0
    native_files = 0
    overlap = max(len(n) for n in needles.values()) - 1
    for path in sorted(root.rglob("*")):
        meta = path.lstat()
        if not stat.S_ISREG(meta.st_mode):
            continue
        files_scanned += 1
        lstat_bytes += meta.st_size
        rel = path.relative_to(root).as_posix()
        if path.suffix in {".so", ".dylib"}:
            native_files += 1
        found: set[str] = set()
        tail = b""
        read = 0
        with path.open("rb") as stream:
            while chunk := stream.read(4 * 1024 * 1024):
                read += len(chunk)
                found.update(_scan_bytes(tail + chunk, needles))
                tail = chunk[-overlap:] if overlap else b""
        if read != meta.st_size:
            raise BuildError(f"scanner read {read} of {meta.st_size} bytes at {rel}")
        bytes_scanned += read
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as archive:
                for member in archive.namelist():
                    data = archive.read(member)
                    if member.endswith(".pyc"):
                        pyc_members += 1
                    for label in _scan_bytes(data, needles):
                        found.add(f"zip:{member}:{label}")
        if found:
            hits[rel] = sorted(found)
    embedded: dict[str, object] = {"entries_scanned": 0, "pyc_entries": 0}
    if python is not None:
        embedded = scan_embedded_archives(root, needles, python)
        for rel, labels in embedded.get("hits", {}).items():  # type: ignore[union-attr]
            hits.setdefault(rel, []).extend(labels)
    return {
        "hits": hits,
        "files_scanned": files_scanned,
        "bytes_scanned": bytes_scanned,
        "lstat_bytes": lstat_bytes,
        "zip_pyc_members": pyc_members,
        "native_files": native_files,
        "embedded": embedded,
    }


def scan_embedded_archives(
    root: Path, needles: dict[str, bytes], python: Path
) -> dict[str, object]:
    """Run ``scan_embedded.py`` under the build venv (which has PyInstaller's
    archive readers) against both executables; returns merged hits keyed like
    ``<exe>!PYZ-00.pyz/<module>``."""
    import base64

    payload = json.dumps(
        {label: base64.b64encode(n).decode() for label, n in needles.items()}
    )
    merged: dict[str, object] = {"hits": {}, "entries_scanned": 0, "pyc_entries": 0}
    for exe in (CHILD_EXE, PROBE_EXE):
        proc = _run(
            [str(python), str(EMBEDDED_SCAN_HELPER), str(root / exe), payload],
            env=_tool_env(),
            cwd=REPO_ROOT,
        )
        report = json.loads(proc.stdout)
        for entry, labels in report["hits"].items():
            merged["hits"][f"{exe}!{entry}"] = labels  # type: ignore[index]
        merged["entries_scanned"] += report["entries_scanned"]  # type: ignore[operator]
        merged["pyc_entries"] += report["pyc_entries"]  # type: ignore[operator]
    return merged


def _require_scan_coverage(scan: dict[str, object]) -> None:
    """Fail closed on a vacuously clean scan: an archive reader that yields an
    empty TOC, or a walk that opened nothing, is indistinguishable from a clean
    result by ``hits`` alone. The tighter numeric floors stay in the gate test.
    """
    embedded = scan.get("embedded", {})
    if not scan.get("files_scanned"):
        raise BuildError("scan covered zero files; the walk found nothing to read")
    if not embedded.get("entries_scanned") or not embedded.get("pyc_entries"):  # type: ignore[union-attr]
        raise BuildError(f"embedded PYZ scan covered no .pyc entries: {embedded}")


def _sweep_transient(root: Path) -> None:
    """Remove work trees a previous failed or interrupted run stranded."""
    for stale in sorted(root.glob("work*")) + [root / "dist-verify"]:
        if stale.exists():
            _log(f"sweeping stale transient tree {stale}")
            shutil.rmtree(stale, ignore_errors=True)


def build_once(root: Path = DEFAULT_ROOT) -> dict[str, object]:
    """``make desktop-package``: provision, sanitize, build, scan; raises on
    any build-machine path hit or an unsanitized install."""
    python, site_packages = provision(root)
    direct_url = sanitize_direct_url(site_packages)
    _sweep_transient(root)
    work, dist = root / "work", root / "dist"
    try:
        bundle = build_bundle(python, work, dist)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    scan = scan_tree(
        bundle, default_needles(build_paths=(REPO_ROOT, work, dist)), python
    )
    _require_scan_coverage(scan)
    report: dict[str, object] = {
        "bundle": str(bundle),
        "direct_url": direct_url,
        "scan": scan,
    }
    (root / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    if scan["hits"]:
        raise BuildError(f"build-machine paths in bundle: {scan['hits']}")
    _log(f"bundle OK at {bundle} ({scan['files_scanned']} files scanned clean)")
    return report


def verify_determinism(
    root: Path = DEFAULT_ROOT, *, keep_second: bool = False
) -> dict[str, object]:
    """Two independent spec builds from the same tree; returns the full
    evidence report (manifest diff, scans, sanitizer pre-state). The first
    build stays at ``root/dist`` as the canonical artifact.

    Independent means COLD: each build gets its own ``PYINSTALLER_CONFIG_DIR``
    under its own workpath, so build B re-processes every native binary rather
    than copying A's bincache entries — the report records both dirs and
    whether B's was cold, because the AC1 claim is otherwise unfalsifiable.
    """
    python, site_packages = provision(root)
    direct_url = sanitize_direct_url(site_packages)
    _sweep_transient(root)
    work_a, work_b = root / "work-a", root / "work-b"
    dist_a, dist_b = root / "dist", root / "dist-verify"
    config_a, config_b = config_dir_for(work_a), config_dir_for(work_b)
    # Recorded, not assumed: AC1's "independent" claim rests on build B not
    # inheriting build A's bincache, so the evidence must show B started cold.
    config_b_cold = not config_b.exists()
    try:
        bundle_a = build_bundle(python, work_a, dist_a)
    finally:
        shutil.rmtree(work_a, ignore_errors=True)
    try:
        bundle_b = build_bundle(python, work_b, dist_b)
    finally:
        shutil.rmtree(work_b, ignore_errors=True)
    manifest_a = file_manifest(bundle_a)
    manifest_b = file_manifest(bundle_b)
    differing = manifest_diff(manifest_a, manifest_b)
    scan = scan_tree(
        bundle_a,
        default_needles(build_paths=(REPO_ROOT, work_a, dist_a, work_b, dist_b)),
        python,
    )
    _require_scan_coverage(scan)
    if not keep_second:
        shutil.rmtree(dist_b, ignore_errors=True)
    report: dict[str, object] = {
        "bundle": str(bundle_a),
        "direct_url": direct_url,
        "determinism": {
            "manifest_entries": len(manifest_a),
            "differing": differing,
            "identical": not differing,
            "exceptions_allowed": sorted(NONDETERMINISTIC_EXCEPTIONS),
            "config_dirs": [str(config_a), str(config_b)],
            "config_dirs_distinct": config_a != config_b,
            "config_dir_b_cold": config_b_cold,
        },
        "scan": scan,
    }
    (root / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    if args.command == "build":
        build_once(args.root)
        return 0
    report = verify_determinism(args.root)
    differing = set(report["determinism"]["differing"])  # type: ignore[index]
    unexpected = differing - NONDETERMINISTIC_EXCEPTIONS
    if unexpected:
        _log(f"NEW nondeterministic paths: {sorted(unexpected)}")
        return 1
    if report["scan"]["hits"]:  # type: ignore[index]
        _log(f"build-machine paths in bundle: {report['scan']['hits']}")  # type: ignore[index]
        return 1
    _log("verify OK: manifests identical within the pinned exception set")
    return 0


if __name__ == "__main__":
    sys.exit(main())
