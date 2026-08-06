"""Disposable proof for the desktop application-data-root contract."""

from __future__ import annotations

import sys
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
class ApplicationPaths:
    """Immutable prototype; production code must not import this test."""

    root: Path

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
        return cls(root)

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
        }
        return {
            key: str(_inside(self.root, self.root / child, key))
            for key, child in children.items()
        }

    def prepare(self) -> None:
        marker = self.path("tmp") / ".arxmcp-write-probe"
        for path in self.all_paths:
            path.mkdir(parents=True, exist_ok=True)
        try:
            marker.write_bytes(b"probe")
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
    paths = ApplicationPaths.resolve(
        env={"ARXMCP_DATA_DIR": str(tmp_path / "root")}, **strict
    )
    inside = paths.compatibility_alias("ARXMCP_CACHE_DB_PATH", "cache/alias.db")
    assert inside.is_relative_to(paths.root)
    with pytest.raises(ValueError, match="escapes"):
        paths.compatibility_alias("ARXMCP_CACHE_DB_PATH", str(tmp_path / "outside"))


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
    with pytest.raises(ValueError, match="requires"):
        ApplicationPaths.resolve(env={}, mode="container", startup_cwd=tmp_path)
