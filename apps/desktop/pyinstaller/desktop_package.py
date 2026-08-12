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
strings, and counts the bundle's OpenMP runtimes (m8: exactly one).
``verify`` additionally runs TWO independent builds and diffs their per-file
manifests against the CLOSED exception set below.

Deliberately not shipped in the wheel: lives outside the packaged trees.
Subprocess side effects only: ``uv`` invocations plus writes under
``var/desktop-package/`` (gitignored). Network only on first provisioning.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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

#: Per-platform OpenMP consolidation policy keyed by ``sys.platform`` family;
#: read it through :func:`libomp_policy`, which explains both branches.
#: ``canonical_dir`` is the bundle-relative directory (under ``_internal``) of
#: the runtime the bundle keeps; ``duplicate_dir`` is the directory whose copy
#: the spec drops from the collected TOC, or ``None`` where none is redundant.
LIBOMP_POLICY: dict[str, dict[str, str | None]] = {
    "darwin": {"canonical_dir": "torch/lib", "duplicate_dir": "faiss/.dylibs"},
    "linux": {"canonical_dir": "torch/lib", "duplicate_dir": None},
}

#: Matches every OpenMP runtime filename family the scan must count, so a
#: renamed, versioned (``libomp.5.dylib``, ``libiomp5.dylib``) or
#: auditwheel-mangled (``libgomp-a34b3233.so.1``) copy cannot slip past a
#: literal-name check. Over-matching is the safe direction — it can only
#: over-count copies, which fails a guard loudly.
LIBOMP_PATTERN = re.compile(
    r"\Alib(omp|iomp5|gomp)(-[0-9a-f]+)?[.0-9]*\.(dylib|so[.0-9]*)\Z"
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


def _normalize_dest(dest: str) -> str:
    """PyInstaller TOC destinations use the host separator on Windows."""
    return dest.replace("\\", "/")


def libomp_policy(platform: str | None = None) -> dict[str, str | None]:
    """The OpenMP policy for ``platform`` (default: the running one).

    macOS drops faiss-cpu's private ``faiss/.dylibs`` copy: PyInstaller rewrites
    both consumers' load commands AND both dylib IDs to ``@rpath/libomp.dylib``,
    so dyld dedupes them onto torch's copy and faiss's is never mapped —
    until its upstream install name is restored, when dyld maps a SECOND image
    and the process aborts with ``OMP: Error #15``.

    Linux has NO redundant copy: auditwheel gives each wheel's vendored libgomp
    a distinct mangled SONAME (``libgomp-<hash>.so.1``) recorded in its OWN
    consumer's DT_NEEDED, so torch's copy cannot satisfy faiss's and dropping
    either leaves an unresolvable dependency; GNU libgomp also has no
    duplicate-runtime abort. Raises on an unknown platform rather than guessing.
    """
    key = platform or sys.platform
    if key.startswith("linux"):
        key = "linux"
    policy = LIBOMP_POLICY.get(key)
    if policy is None:
        raise BuildError(
            f"no OpenMP consolidation policy for platform {key!r}; add one to "
            "LIBOMP_POLICY (with the measurement behind it) before building here"
        )
    return policy


def expects_duplicate_libomp(platform: str | None = None) -> bool:
    """Whether the spec's TOC exclusion must drop something on ``platform``."""
    return libomp_policy(platform)["duplicate_dir"] is not None


def _split_dest(dest: str) -> tuple[str, str]:
    parent, _, name = _normalize_dest(dest).rpartition("/")
    return parent, name


def is_duplicate_libomp(dest: str, platform: str | None = None) -> bool:
    """Whether a TOC destination is the redundant OpenMP copy on ``platform``.

    Directory-exact rather than a substring glob: only a :data:`LIBOMP_PATTERN`
    filename sitting DIRECTLY in the policy's ``duplicate_dir`` matches, so a
    string-match bug cannot reach the canonical copy one directory over. The
    filename is a pattern and not a literal because auditwheel mangles the
    Linux name; ``canonical_dir``/``duplicate_dir`` carry the exactness.
    """
    duplicate_dir = libomp_policy(platform)["duplicate_dir"]
    if duplicate_dir is None:
        return False
    parent, name = _split_dest(dest)
    return parent == duplicate_dir and bool(LIBOMP_PATTERN.match(name))


def is_canonical_libomp(dest: str, platform: str | None = None) -> bool:
    """Whether a TOC destination is the OpenMP runtime the bundle keeps."""
    parent, name = _split_dest(dest)
    return parent == libomp_policy(platform)["canonical_dir"] and bool(
        LIBOMP_PATTERN.match(name)
    )


def libomp_inventory(root: Path) -> dict[str, object]:
    """Every OpenMP-runtime entry in the bundle, split by kind.

    Symlinks are reported separately and never counted as copies: a symlink
    adds a name, not a mapped image. ``regular`` carries one
    ``{"path", "size", "sha256"}`` record per real file, so a second copy is
    visible with its identity rather than as a bare count.
    """
    regular: list[dict[str, object]] = []
    symlinks: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not LIBOMP_PATTERN.match(path.name):
            continue
        meta = path.lstat()
        rel = path.relative_to(root).as_posix()
        if stat.S_ISLNK(meta.st_mode):
            symlinks[rel] = os.readlink(path)
        elif stat.S_ISREG(meta.st_mode):
            regular.append(
                {
                    "path": rel,
                    "size": meta.st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    return {"regular": regular, "symlinks": symlinks}


def _require_single_libomp(
    inventory: dict[str, object], platform: str | None = None
) -> None:
    """Fail the build when the bundle's OpenMP inventory breaks the platform
    policy.

    Where a duplicate is expected (macOS): exactly one runtime file. Two copies
    abort the process the moment their install names differ; zero means the
    consolidation dropped the live copy.

    Where none is (Linux): at least one file, and no two sharing a FILENAME.
    Distinct mangled SONAMEs are separate, individually-needed libraries, but
    two files under one name is the ELF shape of the macOS hazard and must not
    pass unnoticed just because nothing is dropped here.
    """
    regular: list[dict[str, object]] = inventory["regular"]  # type: ignore[assignment]
    if expects_duplicate_libomp(platform):
        if len(regular) != 1:
            raise BuildError(
                f"bundle must carry exactly one OpenMP runtime file, found "
                f"{len(regular)}: {regular}"
            )
        return
    if not regular:
        raise BuildError("bundle carries no OpenMP runtime file at all")
    names = [Path(str(entry["path"])).name for entry in regular]
    collisions = sorted({name for name in names if names.count(name) > 1})
    if collisions:
        raise BuildError(
            f"bundle carries more than one OpenMP runtime file under the same "
            f"name {collisions}: {regular}"
        )


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
    libomp = libomp_inventory(bundle)
    report: dict[str, object] = {
        "bundle": str(bundle),
        "direct_url": direct_url,
        "libomp": libomp,
        "scan": scan,
    }
    (root / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    if scan["hits"]:
        raise BuildError(f"build-machine paths in bundle: {scan['hits']}")
    _require_single_libomp(libomp)
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
    libomp = libomp_inventory(bundle_a)
    if not keep_second:
        shutil.rmtree(dist_b, ignore_errors=True)
    report: dict[str, object] = {
        "bundle": str(bundle_a),
        "direct_url": direct_url,
        "libomp": libomp,
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


# --------------------------------------------------------------------------
# macOS application-bundle assembly (desktop-distribution-m15)
#
# Implements Decision 1 of `.claude/docs/adr-desktop-bundle-assembly.md`
# (Accepted): Tauri's bundler builds the `.app` SHELL ONLY — no `resources`,
# no `externalBin`, no `frameworks` entry for the payload — and this module
# owns pre-signing the onedir bottom-up, placing it at
# `Contents/MacOS/arxmcp-desktop-child/` (Decision 2) and re-sealing the
# outer bundle.
#
# Read Decision 3 before writing anything into this section: whether the
# resulting artifact survives Apple's notary service is OPEN and unanswerable
# here. Nothing below may be described as notarization-ready, Gatekeeper-ready
# or signable-as-is; `tests/test_desktop_notarization_claims.py` fails the
# suite on such a claim.
# --------------------------------------------------------------------------

TAURI_CONF = REPO_ROOT / "apps" / "desktop" / "crates" / "supervisor" / "tauri.conf.json"
DESKTOP_WORKSPACE = REPO_ROOT / "apps" / "desktop"
SUPERVISOR_CRATE = DESKTOP_WORKSPACE / "crates" / "supervisor"

#: Pinned like every other link in this chain. The Tauri *crates* are pinned
#: with `=` in the workspace `Cargo.toml` and matched in `Cargo.lock`; the
#: PyInstaller stack is pinned by hash. `cargo install tauri-cli` with no
#: version and no `--locked` would be the only unpinned link, which the ADR's
#: "Toolchain onboarding" section rules out. 2.11.4 is the newest published
#: CLI as of 2026-08-12; the library crates this workspace pins are 2.11.5,
#: and the two version lines are independent upstream — they are NOT expected
#: to be equal, so do not "fix" the difference.
TAURI_CLI_VERSION = "2.11.4"

#: Signing identity. Default is ad-hoc (`-`), which is what this host can
#: actually do: `security find-identity -p codesigning` offers an *Apple
#: Development* certificate only, and no Developer ID Application certificate
#: exists anywhere in this project (that is the certificate `e4` is blocked
#: on). Ad-hoc is a real signature — it seals the code and makes tampering
#: detectable locally — and it is NOT a distribution signature: it carries no
#: identity, cannot be notarized, and says nothing about Gatekeeper. Override
#: with a real identity string when one exists. Non-`ARXMCP_`-prefixed for the
#: same reason as BUILD_VENV_ENV_VAR.
CODESIGN_IDENTITY_ENV = "DESKTOP_CODESIGN_IDENTITY"
AD_HOC_IDENTITY = "-"

#: Hardened runtime is OFF by default and that is a decision, not an oversight.
#: It is a notarization *prerequisite*, so it belongs with the trial that needs
#: it (e4). Turning it on here would need entitlements this project has never
#: authored for a CPython closure that JITs and maps writable-executable pages
#: (`com.apple.security.cs.allow-jit`,
#: `...allow-unsigned-executable-memory`), and shipping untested entitlements
#: would trade a measured artifact for an unmeasured one. Opt in with
#: `DESKTOP_CODESIGN_HARDENED=1` to measure the other arm.
HARDENED_RUNTIME_ENV = "DESKTOP_CODESIGN_HARDENED"

#: Mach-O and universal-binary magics, both endiannesses. Membership is
#: decided by reading four bytes rather than by extension: the payload's
#: executables are extensionless, and a `.so` that is really a linker script
#: would be signed pointlessly rather than harmfully. Over-detection is the
#: safe direction here — `codesign` refuses a non-Mach-O loudly.
_MACHO_MAGICS = frozenset(
    {
        b"\xcf\xfa\xed\xfe",  # MH_MAGIC_64  (little-endian)
        b"\xce\xfa\xed\xfe",  # MH_MAGIC     (little-endian)
        b"\xfe\xed\xfa\xcf",  # MH_CIGAM_64  (big-endian)
        b"\xfe\xed\xfa\xce",  # MH_CIGAM
        b"\xca\xfe\xba\xbe",  # FAT_MAGIC
        b"\xbe\xba\xfe\xca",  # FAT_CIGAM
    }
)


def product_name() -> str:
    """The bundle's product name, READ from `tauri.conf.json` rather than
    duplicated, so a rename cannot desync the assembler from the bundler."""
    conf = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
    name = conf.get("productName")
    if not name:
        raise BuildError(f"{TAURI_CONF} declares no productName")
    return str(name)


def app_bundle_path(target_dir: Path | None = None) -> Path:
    """Where Tauri's bundler writes the `.app`."""
    target = target_dir or (DESKTOP_WORKSPACE / "target")
    return target / "release" / "bundle" / "macos" / f"{product_name()}.app"


def bundle_executable(app: Path) -> Path:
    """`Contents/MacOS/<CFBundleExecutable>`, READ from the built `Info.plist`.

    Not derived from `productName`: Tauri names the bundle directory
    `arXMCP.app` but leaves the executable at the cargo bin name
    (`supervisor`), and hard-coding either would desync the assembler from the
    bundler the first time one of them changes.
    """
    import plistlib

    plist = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    name = plist.get("CFBundleExecutable")
    if not name:
        raise BuildError(f"{app}/Contents/Info.plist declares no CFBundleExecutable")
    return app / "Contents" / "MacOS" / str(name)


def tauri_cli_bin(root: Path = DEFAULT_ROOT) -> Path:
    return root / "tauri-cli" / "bin" / "cargo-tauri"


def ensure_tauri_cli(root: Path = DEFAULT_ROOT) -> Path:
    """Install the pinned `tauri-cli` under the gitignored build root.

    `--root` keeps it out of `~/.cargo/bin`, so the gate cannot silently use
    whatever version a developer happened to install globally, and `--locked`
    keeps its own dependency resolution reproducible. Idempotent: a present
    binary whose `--version` matches the pin is reused.
    """
    binary = tauri_cli_bin(root)
    if binary.is_file():
        proc = subprocess.run(
            [str(binary), "--version"], capture_output=True, text=True, timeout=120
        )
        if proc.returncode == 0 and TAURI_CLI_VERSION in proc.stdout:
            return binary
    cargo = shutil.which("cargo")
    if cargo is None:
        raise BuildError("cargo is required on PATH to provision the pinned tauri-cli")
    _log(f"installing pinned tauri-cli {TAURI_CLI_VERSION} into {binary.parent.parent}")
    _run(
        [
            cargo,
            "install",
            "--locked",
            "--version",
            TAURI_CLI_VERSION,
            "--root",
            str(binary.parent.parent),
            "tauri-cli",
        ],
        env=dict(os.environ),
        cwd=REPO_ROOT,
        timeout=3600,
    )
    return binary


def codesign_identity() -> str:
    return os.environ.get(CODESIGN_IDENTITY_ENV) or AD_HOC_IDENTITY


def hardened_runtime_enabled() -> bool:
    return os.environ.get(HARDENED_RUNTIME_ENV) == "1"


def is_macho(path: Path) -> bool:
    """Whether ``path`` is a regular file whose first four bytes are a Mach-O
    or universal-binary magic."""
    if not path.is_file() or path.is_symlink():
        return False
    try:
        with path.open("rb") as stream:
            return stream.read(4) in _MACHO_MAGICS
    except OSError:
        return False


def macho_inventory(root: Path) -> list[Path]:
    """Every nested Mach-O under ``root``, DEEPEST FIRST.

    The ordering is the whole point. `codesign` seals a Mach-O over its own
    bytes, so signing a container before the code it contains invalidates the
    container's seal — which is exactly the failure `codesign --deep` is known
    for and which ADR evidence rows E4/E6 record surviving local verification
    while failing the notary. Deepest-first, ties broken by path for
    determinism, guarantees every dependency is sealed before anything that
    embeds or loads it.
    """
    found = [p for p in root.rglob("*") if is_macho(p)]
    return sorted(found, key=lambda p: (-len(p.relative_to(root).parts), p.as_posix()))


def sign_file(path: Path, identity: str, *, hardened: bool = False) -> None:
    """Sign one Mach-O with `codesign`, replacing any existing signature.

    `--timestamp=none` for ad-hoc: Apple's timestamp server refuses an
    identity-free signature, and a network round-trip per file across a
    ~0.75 GB tree would dominate the build anyway. A real identity gets a
    real timestamp.
    """
    codesign = shutil.which("codesign")
    if codesign is None:
        raise BuildError("codesign is required (Xcode command line tools)")
    cmd = [codesign, "--force", "--sign", identity]
    cmd += ["--timestamp=none"] if identity == AD_HOC_IDENTITY else ["--timestamp"]
    if hardened:
        cmd += ["--options", "runtime"]
    cmd.append(str(path))
    _run(cmd, env=dict(os.environ), timeout=300)


def codesign_verify(path: Path, *, deep: bool = False) -> str:
    """`codesign --verify --strict` output; raises via `_run` on a bad seal.

    Deliberately NOT called "validate the artifact". It answers one question —
    does this seal match these bytes on this machine — and says nothing about
    Gatekeeper assessment or the notary (ADR Decision 3's four distinct
    questions; this is (c), partially).
    """
    codesign = shutil.which("codesign")
    if codesign is None:
        raise BuildError("codesign is required (Xcode command line tools)")
    cmd = [codesign, "--verify", "--strict"]
    if deep:
        cmd.append("--deep")
    cmd += ["--verbose=2", str(path)]
    proc = _run(cmd, env=dict(os.environ), timeout=900)
    return proc.stderr + proc.stdout


def presign_payload(payload_root: Path, identity: str | None = None) -> dict[str, object]:
    """Bottom-up pre-signing of EVERY nested Mach-O in the onedir.

    This is ADR Decision 1 step 2 and the owner's acceptance record names it
    explicitly: `codesign --deep` is not a substitute and is not permitted as
    one. `--deep` is a single invocation over a container; this walks the tree
    and issues one `codesign` per file in dependency-safe order, which is both
    what the evidence base recommends and what makes the count below a real
    number rather than an assertion.
    """
    identity = identity or codesign_identity()
    hardened = hardened_runtime_enabled()
    targets = macho_inventory(payload_root)
    if not targets:
        raise BuildError(f"no Mach-O files found under {payload_root}; refusing a vacuous sign")
    _log(f"pre-signing {len(targets)} Mach-O files bottom-up (identity {identity!r})")
    for target in targets:
        sign_file(target, identity, hardened=hardened)
    # Spot-verify the two executables rather than the whole tree: a per-file
    # --verify over hundreds of dylibs costs minutes and proves the same thing
    # the placement re-verify proves. The executables are the files whose seal
    # would break first if the ordering above were wrong.
    verified = {exe: codesign_verify(payload_root / exe) for exe in (CHILD_EXE, PROBE_EXE)}
    return {
        "identity": identity,
        "ad_hoc": identity == AD_HOC_IDENTITY,
        "hardened_runtime": hardened,
        "macho_signed": len(targets),
        "deepest_first": [p.relative_to(payload_root).as_posix() for p in targets[:3]],
        "executables_verified": sorted(verified),
    }


def build_app_shell(root: Path = DEFAULT_ROOT) -> Path:
    """Run Tauri's bundler to produce the `.app` SHELL.

    Run from the supervisor crate directory, which is where `tauri.conf.json`
    lives; the repo-root `.cargo/config.toml` deployment-target pin is still
    discovered, because cargo walks up from the CWD and the crate is inside
    the repo. `tests/test_desktop_bundle.py` re-reads `minos` off the bundled
    binary rather than trusting that sentence.
    """
    cli = ensure_tauri_cli(root)
    app = app_bundle_path()
    if app.exists():
        shutil.rmtree(app)
    _log("tauri build (shell only: no resources, no externalBin, no frameworks)")
    _run(
        [str(cli), "build"],
        env=dict(os.environ),
        cwd=SUPERVISOR_CRATE,
        timeout=3600,
    )
    if not app.is_dir():
        raise BuildError(f"tauri build produced no bundle at {app}")
    return app


def place_payload(app: Path, payload_root: Path) -> Path:
    """Copy the pre-signed onedir to `Contents/MacOS/<CHILD_PAYLOAD_DIR>/`.

    `copytree(symlinks=True)` preserves the payload's INTERNAL symlinks (the
    framework-style `Python`/`Versions/Current` links PyInstaller emits) while
    creating the destination root itself as a real directory. That distinction
    is load-bearing: the supervisor's `resolve_inside()` refuses a symlinked
    payload root outright, so an assembler that materialised the root as a
    link would produce an `.app` that refuses to launch.
    """
    destination = app / "Contents" / "MacOS" / BUNDLE_NAME
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(payload_root, destination, symlinks=True)
    if destination.is_symlink():
        raise BuildError(f"placed payload root {destination} is a symlink")
    return destination


def seal_app(app: Path, identity: str | None = None) -> dict[str, object]:
    """ATTEMPT the outer re-seal after placement, and record what happened.

    Ordering is ADR Decision 1's one hard constraint: the payload is signed
    before the shell is sealed, so the shell's seal would cover the payload's
    final bytes. Sealing first and copying afterwards produces a bundle whose
    `_CodeSignature` describes a tree that no longer exists.

    **Measured 2026-08-12, macOS 26.6 / Xcode `codesign`: this step does not
    succeed at Decision 2's location, and the reason is structural.**
    `Contents/MacOS` is a code-only location, so `codesign` treats every file
    the payload puts there as a nested code object and refuses the whole
    bundle at the first non-Mach-O one:

        <app>: code object is not signed at all
        In subcomponent: .../Contents/MacOS/arxmcp-desktop-child/_internal/tools/sbom.sh

    It is not about scripts, executable bits or this payload's contents: a
    six-byte `data.txt` reproduces it, and the SAME file under
    `Contents/Resources/` seals and reports "valid on disk / satisfies its
    Designated Requirement". `test_desktop_bundle.py` runs that A/B control,
    so the claim is a re-measurement rather than a quotation.

    This function therefore RECORDS the outcome instead of raising. Raising
    would abort assembly over a step whose failure is a property of the
    accepted layout, not of the build; silently succeeding would be worse.
    Decision 2 is Accepted and is NOT relitigated here — this is the input the
    owner and `e4` need in order to decide whether it should be, and it is
    precisely the condition the ADR's rejected-alternative R3 names as the
    trigger for revisiting the `frameworks` route ("unsigned or
    improperly-sealed nested code").
    """
    identity = identity or codesign_identity()
    codesign = shutil.which("codesign")
    if codesign is None:
        raise BuildError("codesign is required (Xcode command line tools)")
    cmd = [codesign, "--force", "--sign", identity]
    cmd += ["--timestamp=none"] if identity == AD_HOC_IDENTITY else ["--timestamp"]
    if hardened_runtime_enabled():
        cmd += ["--options", "runtime"]
    cmd.append(str(app))
    proc = subprocess.run(
        cmd, env=dict(os.environ), capture_output=True, text=True, timeout=1800, check=False
    )
    record: dict[str, object] = {
        "identity": identity,
        "attempted": True,
        "sealed": proc.returncode == 0,
        "returncode": proc.returncode,
        "error": (proc.stderr or proc.stdout).strip()[-2000:] or None,
    }
    if proc.returncode == 0:
        verify = subprocess.run(
            [codesign, "--verify", "--strict", "--verbose=2", str(app)],
            env=dict(os.environ),
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
        record["verified"] = verify.returncode == 0
        record["verify_output"] = (verify.stderr or verify.stdout).strip()[-2000:]
    else:
        record["verified"] = False
    return record


def measure_macos_seal_location_control(app_executable: Path) -> dict[str, object]:
    """The A/B control behind :func:`seal_app`'s recorded failure.

    Builds two throwaway one-file `.app` trees that differ ONLY in where a
    single plain `data.txt` sits — `Contents/MacOS/payload/` versus
    `Contents/Resources/payload/` — and seals each. Nothing about arXMCP is
    involved, which is the point: it separates "this payload is unusual" from
    "this location cannot hold data", and the answer must be re-derivable on
    whatever macOS the reader has rather than quoted from a log this milestone
    happened to produce.
    """
    codesign = shutil.which("codesign")
    if codesign is None:
        raise BuildError("codesign is required (Xcode command line tools)")
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>'
        "<key>CFBundleExecutable</key><string>host</string>"
        "<key>CFBundleIdentifier</key><string>com.arxmcp.sealcontrol</string>"
        "<key>CFBundleName</key><string>SealControl</string>"
        "<key>CFBundlePackageType</key><string>APPL</string>"
        "</dict></plist>\n"
    )
    results: dict[str, object] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for arm, relative in (("macos", "Contents/MacOS"), ("resources", "Contents/Resources")):
            app = Path(tmp) / f"{arm}.app"
            (app / "Contents" / "MacOS").mkdir(parents=True)
            (app / "Contents" / "Info.plist").write_text(plist, encoding="utf-8")
            shutil.copy2(app_executable, app / "Contents" / "MacOS" / "host")
            payload = app / relative / "payload"
            payload.mkdir(parents=True, exist_ok=True)
            (payload / "data.txt").write_text("hello\n", encoding="utf-8")
            proc = subprocess.run(
                [codesign, "--force", "--sign", AD_HOC_IDENTITY, "--timestamp=none", str(app)],
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            results[arm] = {
                "sealed": proc.returncode == 0,
                "output": (proc.stderr or proc.stdout).strip()[-600:],
            }
    return results


def measure_adhoc_signature_stability(payload_root: Path) -> dict[str, object]:
    """Is an ad-hoc `codesign` byte-stable for the same input?

    ADR open item 4 asks whether the ASSEMBLED artifact gets its own
    determinism claim. m7's `verify_determinism` measures the UNSIGNED onedir;
    assembly adds exactly one byte-changing step, so the honest way to extend
    that claim is to measure whether that step is a function of its input.
    One small file, signed twice into two copies, answers it in milliseconds
    instead of re-running a ~75 s build. Reported, never assumed — and note
    it measures THIS host's `codesign`, not a guarantee about all of them.
    """
    sample = payload_root / PROBE_EXE
    identity = codesign_identity()
    digests = []
    with tempfile.TemporaryDirectory() as tmp:
        for index in range(2):
            # SAME basename, different directory. `codesign` derives the
            # signing identifier from the filename when the Mach-O carries
            # none, so signing `probe-0` and `probe-1` would differ for a
            # reason that has nothing to do with determinism — the first
            # revision of this measurement made exactly that mistake and
            # reported a false negative.
            copy_dir = Path(tmp) / str(index)
            copy_dir.mkdir()
            copy = copy_dir / sample.name
            shutil.copy2(sample, copy)
            sign_file(copy, identity, hardened=hardened_runtime_enabled())
            digests.append(hashlib.sha256(copy.read_bytes()).hexdigest())
    return {
        "sample": sample.name,
        "identity": identity,
        "digests": digests,
        "byte_stable": digests[0] == digests[1],
    }


def assemble(root: Path = DEFAULT_ROOT) -> dict[str, object]:
    """Pre-sign, build the shell, place, re-seal — and record the evidence.

    Consumes the onedir `build_once` already produced at ``root/dist``; it
    does NOT rebuild it, so `make desktop-bundle` can prove the placed child
    is byte-identical to the artifact `make desktop-package` emitted rather
    than to a fresh build that merely resembles it (roadmap AC5).
    """
    if sys.platform != "darwin":
        raise BuildError(f"`.app` assembly is macOS-only; this is {sys.platform!r}")
    payload_root = root / "dist" / BUNDLE_NAME
    if not (payload_root / CHILD_EXE).is_file():
        raise BuildError(
            f"no onedir at {payload_root}; run `make desktop-package` first "
            "(assembly deliberately does not rebuild it — AC5 compares against "
            "the artifact that gate produced)"
        )
    signing = presign_payload(payload_root)
    stability = measure_adhoc_signature_stability(payload_root)
    signed_manifest = file_manifest(payload_root)
    app = build_app_shell(root)
    placed = place_payload(app, payload_root)
    placed_manifest = file_manifest(placed)
    drift = manifest_diff(signed_manifest, placed_manifest)
    if drift:
        raise BuildError(
            f"placed payload differs from the pre-signed onedir at {len(drift)} "
            f"paths (first 10: {drift[:10]}); bundling must not substitute a "
            "stale or rebuilt child"
        )
    seal = seal_app(app)
    seal_control = measure_macos_seal_location_control(bundle_executable(app))
    # AC6: m7's build-root string scan re-run over the ASSEMBLED payload, with
    # the same embedded-PYZ depth the pre-bundle scan uses — a placement step
    # that rewrote a path into a `.pyc` would otherwise hide from a raw walk.
    scan = scan_tree(
        placed,
        default_needles(build_paths=(REPO_ROOT, root, app)),
        _venv_python(build_venv_dir(root)),
    )
    _require_scan_coverage(scan)
    libomp = libomp_inventory(placed)
    _require_single_libomp(libomp)
    if scan["hits"]:
        raise BuildError(f"build-machine paths in the ASSEMBLED payload: {scan['hits']}")
    report: dict[str, object] = {
        "app": str(app),
        "payload_placed": str(placed),
        "payload_relative": str(placed.relative_to(app)),
        "signing": signing,
        "signature_stability": stability,
        "seal": seal,
        "seal_location_control": seal_control,
        "manifest_entries": len(signed_manifest),
        "payload_identical_to_onedir": not drift,
        "scan": scan,
        "libomp": libomp,
        "tauri_cli_version": TAURI_CLI_VERSION,
    }
    (root / "assembly-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    _log(f"assembled {app} with the payload at {report['payload_relative']}")
    if not seal["sealed"]:
        # Loud, and phrased as the open question it is. Every nested Mach-O IS
        # signed (see `signing` above); what failed is the OUTER bundle seal,
        # and nothing here says anything about Gatekeeper or the notary.
        _log(
            "OUTER SEAL NOT APPLIED: codesign refuses to seal a bundle whose "
            "Contents/MacOS carries non-Mach-O files. Nested Mach-O signing "
            f"({signing['macho_signed']} files) succeeded. Location control: "
            f"MacOS sealed={seal_control['macos']['sealed']}, "  # type: ignore[index]
            f"Resources sealed={seal_control['resources']['sealed']}. "  # type: ignore[index]
            "See adr-desktop-bundle-assembly.md Decision 2 and R3."
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify", "assemble"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    if args.command == "build":
        build_once(args.root)
        return 0
    if args.command == "assemble":
        assemble(args.root)
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
    try:
        _require_single_libomp(report["libomp"])  # type: ignore[arg-type]
    except BuildError as exc:
        _log(str(exc))
        return 1
    _log("verify OK: manifests identical within the pinned exception set")
    return 0


if __name__ == "__main__":
    sys.exit(main())
