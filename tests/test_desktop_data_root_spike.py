"""Disposable proof for the desktop application-data-root contract."""

from __future__ import annotations

import os
import sys
import tempfile
import warnings
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest

Mode = Literal["source", "installed", "container"]
Child = Literal[
    "corpus", "lancedb", "kuzu", "bm25", "sqlite", "notebooks",
    "cache", "ops", "logs", "backups", "tmp",
]
_CHILDREN: dict[Child, str] = {
    "corpus": "corpus", "lancedb": "index/lancedb", "kuzu": "index/kuzu",
    "bm25": "index/bm25", "sqlite": "index/sqlite", "notebooks": "notebooks",
    "cache": "cache", "ops": "ops", "logs": "logs", "backups": "backups",
    "tmp": "tmp",
}
_ALIASES = {
    "ARXMCP_LANCEDB_PATH", "ARXMCP_KUZU_PATH", "ARXMCP_CACHE_DB_PATH",
    "ARXMCP_BM25_INDEX_ROOT", "ARXMCP_THEOREM_NAMES_DB_PATH",
    "ARXMCP_NOTEBOOKS_DB_PATH", "ARXMCP_OPS_DIR",
}
_INVENTORY_REQUIRED_OWNER_ANCHORS = (
    "server/main.py:lifespan",
    "server/metrics_refresh.py:run_metrics_refresh_loop",
    "server/health.py:refresh_disk_free_metric",
    "tools/ingest_sentinel.py:write_pause/clear_pause",
    "tools/_notebook_common.py:ensure_raw_tex",
    "tools/arxiv_fetch.py:fetch_eprint",
    "ingest/bulk_download.sh",
    "tools/quarterly_drill_reminder.sh",
    "tools/sbom.sh",
    "ops/cron/arxmcp-backup.sh",
)


def _canonical(path: Path, label: str) -> Path:
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"{label} cannot be resolved: {path}") from exc


def _inside(root: Path, candidate: Path, label: str) -> Path:
    resolved = _canonical(candidate, label)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes ARXMCP_DATA_DIR: {resolved}") from exc
    return resolved


@dataclass(frozen=True, slots=True)
class ContainerMount:
    """A prospective container mount used only by this proof."""

    target: Path
    writable: bool


@dataclass(frozen=True, slots=True)
class ApplicationPaths:
    """Immutable prototype; production code must not import this test."""

    root: Path
    aliases: tuple[tuple[str, Path], ...] = ()

    @classmethod
    def resolve(
        cls,
        *,
        env: Mapping[str, str],
        mode: Mode,
        startup_cwd: Path,
        source_root: Path | None = None,
        platform_default: Callable[[], Path] | None = None,
    ) -> ApplicationPaths:
        raw = env.get("ARXMCP_DATA_DIR", "")
        if raw:
            candidate = Path(raw)
            if ".." in candidate.parts:
                raise ValueError("ARXMCP_DATA_DIR must not contain '..'")
            if not candidate.is_absolute():
                if mode != "source":
                    raise ValueError("ARXMCP_DATA_DIR must be absolute")
                warnings.warn(
                    "relative ARXMCP_DATA_DIR is source-only and deprecated",
                    DeprecationWarning,
                    stacklevel=2,
                )
                candidate = startup_cwd / candidate
        elif mode == "source" and source_root is not None:
            candidate = source_root / "var" / "arxmcp"
        elif mode == "installed" and platform_default is not None:
            candidate = platform_default()
        else:
            raise ValueError(f"{mode} mode requires an application-data root")
        if not candidate.is_absolute():
            raise ValueError("resolved application-data root must be absolute")
        root = _canonical(candidate, "ARXMCP_DATA_DIR")
        for name, relative in _CHILDREN.items():
            _inside(root, root / relative, name)
        paths = cls(root)
        aliases = tuple(
            (name, paths.compatibility_alias(name, env[name]))
            for name in sorted(_ALIASES)
            if mode != "source" and env.get(name)
        )
        return cls(root, aliases)

    def path(self, name: Child) -> Path:
        return _inside(self.root, self.root / _CHILDREN[name], name)

    @property
    def all_paths(self) -> tuple[Path, ...]:
        return (self.root, *(self.path(name) for name in _CHILDREN))

    def compatibility_alias(self, name: str, value: str) -> Path:
        if name not in _ALIASES:
            raise ValueError(f"unknown compatibility alias: {name}")
        candidate = Path(value)
        if ".." in candidate.parts:
            raise ValueError(f"{name} must not contain '..'")
        if not candidate.is_absolute():
            candidate = self.root / candidate
        return _inside(self.root, candidate, name)

    def launcher_environment(self) -> dict[str, str]:
        children = {
            "ARXMCP_DATA_DIR": ".", "HF_HOME": "cache/huggingface",
            "TRANSFORMERS_CACHE": "cache/huggingface/transformers",
            "XDG_CACHE_HOME": "cache/xdg", "MPLCONFIGDIR": "cache/matplotlib",
            "HOME": "home", "TMPDIR": "tmp", "TEMP": "tmp", "TMP": "tmp",
            "USERPROFILE": "home", "LOCALAPPDATA": "home/AppData/Local",
            "APPDATA": "home/AppData/Roaming",
        }
        return {
            key: str(_inside(self.root, self.root / child, key))
            for key, child in children.items()
        }

    def validate_container_mounts(
        self, mounts: tuple[ContainerMount, ...]
    ) -> None:
        matching = [
            mount
            for mount in mounts
            if mount.target.is_absolute()
            and _canonical(mount.target, "container mount") == self.root
        ]
        if len(matching) != 1 or not matching[0].writable:
            raise ValueError(
                "ARXMCP_DATA_DIR requires exactly one matching writable mount"
            )

    def prepare(
        self, write_observer: Callable[[Path], None] | None = None
    ) -> None:
        for path in self.all_paths:
            if write_observer is not None:
                write_observer(path)
            path.mkdir(parents=True, exist_ok=True)
        fd, marker_name = tempfile.mkstemp(
            prefix=".arxmcp-write-probe-", dir=self.path("tmp")
        )
        marker = Path(marker_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                if write_observer is not None:
                    write_observer(marker)
                stream.write(b"probe")
        finally:
            marker.unlink(missing_ok=True)


def test_source_fixture_preserves_checkout_default(tmp_path: Path) -> None:
    repo, cwd = tmp_path / "source", tmp_path / "unrelated cwd"
    repo.mkdir()
    cwd.mkdir()
    paths = ApplicationPaths.resolve(
        env={}, mode="source", startup_cwd=cwd, source_root=repo
    )
    assert paths.root == repo / "var" / "arxmcp"
    assert not paths.root.exists()
    with pytest.warns(DeprecationWarning):
        relative = ApplicationPaths.resolve(
            env={"ARXMCP_DATA_DIR": "state"}, mode="source", startup_cwd=cwd
        )
    assert relative.root == cwd / "state"


def test_absolute_missing_space_unicode_root_is_typed(tmp_path: Path) -> None:
    root = tmp_path / "missing dáta 数学"
    paths = ApplicationPaths.resolve(
        env={"ARXMCP_DATA_DIR": str(root)}, mode="installed", startup_cwd=tmp_path
    )
    assert not root.exists()
    assert len(set(paths.all_paths)) == len(paths.all_paths)
    assert all(path == root or path.is_relative_to(root) for path in paths.all_paths)


def test_strict_roots_and_aliases_reject_escape(tmp_path: Path) -> None:
    strict = {"mode": "installed", "startup_cwd": tmp_path}
    for value in ("relative", str(tmp_path / "ok" / ".." / "bad")):
        with pytest.raises(ValueError):
            ApplicationPaths.resolve(env={"ARXMCP_DATA_DIR": value}, **strict)
    root = tmp_path / "root"
    paths = ApplicationPaths.resolve(env={
        "ARXMCP_DATA_DIR": str(root),
        "ARXMCP_CACHE_DB_PATH": "cache/alias.db",
    }, **strict)
    assert dict(paths.aliases)["ARXMCP_CACHE_DB_PATH"].is_relative_to(paths.root)
    with pytest.raises(ValueError, match="escapes"):
        ApplicationPaths.resolve(env={
            "ARXMCP_DATA_DIR": str(root),
            "ARXMCP_CACHE_DB_PATH": str(tmp_path / "outside"),
        }, **strict)


@pytest.mark.skipif(sys.platform == "win32", reason="symlink privilege varies")
def test_symlinks_are_canonicalized_or_rejected(tmp_path: Path) -> None:
    target, link, outside = tmp_path / "target", tmp_path / "link", tmp_path / "out"
    target.mkdir()
    outside.mkdir()
    link.symlink_to(target, target_is_directory=True)
    env = {"ARXMCP_DATA_DIR": str(link)}
    assert ApplicationPaths.resolve(env=env, mode="installed", startup_cwd=tmp_path).root == target
    (target / "cache").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        ApplicationPaths.resolve(env=env, mode="installed", startup_cwd=tmp_path)


@pytest.mark.skipif(sys.platform == "win32", reason="chmod is not authoritative")
def test_wheel_fixture_avoids_read_only_app(tmp_path: Path) -> None:
    package, cwd, data = tmp_path / "site-packages", tmp_path / "cwd", tmp_path / "data"
    package.mkdir()
    cwd.mkdir()
    asset = package / "server.py"
    asset.write_text("read only", encoding="utf-8")
    package.chmod(0o555)
    before = (asset.read_bytes(), tuple(package.iterdir()), tuple(cwd.iterdir()))
    try:
        paths = ApplicationPaths.resolve(
            env={"ARXMCP_DATA_DIR": str(data)}, mode="installed", startup_cwd=cwd
        )
        paths.prepare()
        assert all(path.exists() for path in paths.all_paths)
        assert before == (asset.read_bytes(), tuple(package.iterdir()), tuple(cwd.iterdir()))
    finally:
        package.chmod(0o755)


def test_wheel_fixture_observes_only_data_root_writes(tmp_path: Path) -> None:
    package, cwd, data = tmp_path / "site-packages", tmp_path / "cwd", tmp_path / "data"
    package.mkdir()
    cwd.mkdir()
    observed: list[Path] = []
    paths = ApplicationPaths.resolve(
        env={"ARXMCP_DATA_DIR": str(data)}, mode="installed", startup_cwd=cwd
    )

    def deny_application_write(path: Path) -> None:
        resolved = _canonical(path, "observed write")
        if resolved == package or resolved.is_relative_to(package):
            raise PermissionError("simulated read-only application")
        if resolved == cwd or resolved.is_relative_to(cwd):
            raise PermissionError("simulated read-only startup CWD")
        observed.append(_inside(paths.root, resolved, "observed write"))

    paths.prepare(write_observer=deny_application_write)
    assert observed
    assert all(path.is_relative_to(paths.root) for path in observed)


def test_prepare_preserves_preexisting_probe_names(tmp_path: Path) -> None:
    paths = ApplicationPaths.resolve(
        env={"ARXMCP_DATA_DIR": str(tmp_path / "data")},
        mode="installed",
        startup_cwd=tmp_path,
    )
    paths.prepare()
    fixed = paths.path("tmp") / ".arxmcp-write-probe"
    fixed.write_bytes(b"operator data")
    paths.prepare()
    assert fixed.read_bytes() == b"operator data"
    if sys.platform != "win32":
        fixed.unlink()
        outside = tmp_path / "outside"
        outside.write_bytes(b"outside data")
        fixed.symlink_to(outside)
        paths.prepare()
        assert fixed.is_symlink()
        assert outside.read_bytes() == b"outside data"


def test_windows_launcher_state_survives_mineru_scrub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ingest import textbook_parser

    paths = ApplicationPaths.resolve(
        env={"ARXMCP_DATA_DIR": str(tmp_path / "data")},
        mode="installed",
        startup_cwd=tmp_path,
    )
    redirects = paths.launcher_environment()
    windows_state = ("USERPROFILE", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP")
    for key in windows_state:
        monkeypatch.setenv(key, str(tmp_path / "host" / key))
    for key, value in redirects.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        textbook_parser,
        "_ENV_WHITELIST",
        textbook_parser._ENV_WHITELIST_POSIX
        | textbook_parser._ENV_WHITELIST_WINDOWS,
    )
    scrubbed = textbook_parser._scrub_subprocess_env(paths.path("tmp"))
    for key in (*windows_state, "HOME", "TMPDIR"):
        assert Path(scrubbed[key]).is_relative_to(paths.root)


def test_installed_default_and_container_redirects(tmp_path: Path) -> None:
    native = tmp_path / "native default"
    installed = ApplicationPaths.resolve(
        env={}, mode="installed", startup_cwd=tmp_path,
        platform_default=lambda: native,
    )
    assert installed.root == native
    mount = tmp_path / "container-mount"
    container = ApplicationPaths.resolve(
        env={"ARXMCP_DATA_DIR": str(mount)}, mode="container", startup_cwd=tmp_path
    )
    redirects = container.launcher_environment()
    assert redirects["ARXMCP_DATA_DIR"] == str(mount)
    assert all(Path(value).is_relative_to(mount) for value in redirects.values())
    container.validate_container_mounts((ContainerMount(mount, writable=True),))
    invalid_mounts = (
        (),
        (ContainerMount(mount, writable=False),),
        (ContainerMount(Path("relative-mount"), writable=True),),
        (ContainerMount(tmp_path / "other", writable=True),),
        (
            ContainerMount(mount, writable=True),
            ContainerMount(mount, writable=True),
        ),
    )
    for mounts in invalid_mounts:
        with pytest.raises(ValueError, match="exactly one matching writable"):
            container.validate_container_mounts(mounts)
    with pytest.raises(ValueError, match="requires"):
        ApplicationPaths.resolve(env={}, mode="container", startup_cwd=tmp_path)


def test_inventory_covers_known_write_owners() -> None:
    inventory = (
        Path(__file__).parents[1]
        / ".claude/notes/spikes/desktop-distribution-spike-2.md"
    ).read_text(encoding="utf-8")
    missing = [
        owner for owner in _INVENTORY_REQUIRED_OWNER_ANCHORS
        if owner not in inventory
    ]
    assert not missing, f"inventory is missing known owners: {missing}"
