# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec for the desktop sidecar (desktop-distribution-m7).

Run via ``make desktop-package`` / ``apps/desktop/pyinstaller/desktop_package.py``,
NEVER bare ``pyinstaller`` from the repo root: the driver supplies the build
venv (wheel-installed arxmcp + hash-pinned PyInstaller), an explicit
``--workpath``/``--distpath`` under ``var/desktop-package/`` (the repo-root
``build/`` default collides with unrelated setuptools output), and the
determinism env (PYTHONHASHSEED / SOURCE_DATE_EPOCH).

The entry script is the WHEEL-INSTALLED ``server/desktop_child.py`` — resolved
through ``importlib`` from the build venv's site-packages, never the checkout —
so the frozen top-level IS the production module and its ``__main__`` guard
(``multiprocessing.freeze_support()`` first, AC3) is what runs. A second small
``arxmcp-desktop-probe`` EXE ships in the same COLLECT for the frozen
latex2mathml byte-parity proof (AC2); it shares the child's ``_internal`` tree,
so what it converts with is exactly what the child would resolve.
"""

import importlib.util
from pathlib import Path

import PyInstaller.building.build_main as _build_main

PLACEHOLDER_PREFIX = "/arxmcp-frozen-placeholder"

_original_create_base_library_zip = _build_main.create_base_library_zip


def _deterministic_base_library_zip(filename, modules_toc, code_cache=None):
    """AC1: base_library.zip member ORDER follows module-graph enumeration,
    which varies run-to-run (measured 2026-08-09: identical 155 members and
    bytes, order divergent from index 142). Sorting is functionally neutral —
    zipimport looks members up by name — and makes the archive byte-stable.
    Patched here because the zip is written inside Analysis(), before any
    spec-level post-processing can reach its TOC.
    """
    return _original_create_base_library_zip(filename, sorted(modules_toc), code_cache)


_build_main.create_base_library_zip = _deterministic_base_library_zip


def _sanitize_sysconfigdata(analysis, work_dir: Path) -> None:
    """Replace ``_sysconfigdata*`` with a copy whose build-machine prefix is
    rewritten (measured AC5 leak: 21 ``build_time_vars`` values carry the uv
    interpreter's ``$HOME`` path into the frozen PYZ). The values are
    build-machine paths either way — meaningless on any target host — so a
    placeholder keeps ``sysconfig`` importable with zero functional change.
    Excluding the module instead would crash any runtime
    ``sysconfig.get_config_vars()`` caller.

    Repointing the TOC src alone is NOT enough: PYZ.assemble reads the code
    object PRE-COMPILED during Analysis from ``CONF['code_cache']`` (keyed by
    ``id(analysis.pure)``), so the sanitized source must be recompiled into
    that cache; the TOC repoint remains only as the cache-miss fallback.
    """
    from PyInstaller.config import CONF

    home = str(Path.home())
    sanitized_dir = work_dir / "sanitized-sysconfigdata"
    sanitized_dir.mkdir(parents=True, exist_ok=True)
    code_cache = CONF.get("code_cache", {}).get(id(analysis.pure))
    rewritten = []
    for index, (name, src, typecode) in enumerate(analysis.pure):
        if not name.startswith("_sysconfigdata"):
            continue
        text = Path(src).read_text(encoding="utf-8").replace(home, PLACEHOLDER_PREFIX)
        if home in text or Path.home().name in text:
            raise SystemExit(f"{name} still carries build-machine strings after rewrite")
        out = sanitized_dir / f"{name}.py"
        out.write_text(text, encoding="utf-8")
        analysis.pure[index] = (name, str(out), typecode)
        if code_cache is not None and name in code_cache:
            code_cache[name] = compile(text, f"{name}.py", "exec")
        rewritten.append(name)
    if not rewritten:
        raise SystemExit(
            "no _sysconfigdata module collected; the AC5 sanitizer expected one — "
            "re-measure before removing this guard"
        )


_child_spec = importlib.util.find_spec("server.desktop_child")
if _child_spec is None or not _child_spec.origin:
    raise SystemExit("arxmcp wheel is not installed in this environment")
CHILD_ENTRY = _child_spec.origin
if "site-packages" not in CHILD_ENTRY:
    raise SystemExit(
        f"entry resolved outside site-packages ({CHILD_ENTRY}); build from the "
        "wheel-installed module, not a checkout on sys.path"
    )
HOOKS_DIR = str(Path(SPECPATH))  # noqa: F821 - SPECPATH is injected by PyInstaller
PROBE_ENTRY = str(Path(SPECPATH) / "probe_entry.py")  # noqa: F821

child_analysis = Analysis(  # noqa: F821
    [CHILD_ENTRY],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[HOOKS_DIR],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
_sanitize_sysconfigdata(child_analysis, Path(workpath))  # noqa: F821 - injected
# AC1: PYZ writes entries in TOC order, which inherits the module graph's
# run-to-run enumeration drift (measured as an intermittently byte-different
# executable). The archive is name-keyed; sorting is functionally neutral.
child_analysis.pure.sort()
child_pyz = PYZ(child_analysis.pure)  # noqa: F821
child_exe = EXE(  # noqa: F821
    child_pyz,
    child_analysis.scripts,
    [],
    exclude_binaries=True,
    name="arxmcp-desktop-child",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

probe_analysis = Analysis(  # noqa: F821
    [PROBE_ENTRY],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[HOOKS_DIR],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
probe_analysis.pure.sort()
probe_pyz = PYZ(probe_analysis.pure)  # noqa: F821
probe_exe = EXE(  # noqa: F821
    probe_pyz,
    probe_analysis.scripts,
    [],
    exclude_binaries=True,
    name="arxmcp-desktop-probe",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

COLLECT(  # noqa: F821
    child_exe,
    child_analysis.binaries,
    child_analysis.datas,
    probe_exe,
    probe_analysis.binaries,
    probe_analysis.datas,
    strip=False,
    upx=False,
    name="arxmcp-desktop-child",
)
