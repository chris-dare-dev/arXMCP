from pathlib import Path

import pytest

import server.application_paths as paths_module
from server.application_paths import (
    COMPATIBILITY_ALIAS_FIELDS,
    ApplicationPathError,
    ApplicationPaths,
)
from server.config import Config
from tests._symlink_support import requires_symlink


def test_source_and_installed_roots_ignore_later_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, cwd = tmp_path / "source", tmp_path / "cwd"
    source.mkdir()
    cwd.mkdir()
    assert ApplicationPaths.resolve(
        environ={}, mode="source", source_root=source, startup_cwd=cwd
    ).root == source / "var" / "arxmcp"
    with pytest.warns(DeprecationWarning):
        relative = ApplicationPaths.resolve(
            environ={}, mode="source", root="state", startup_cwd=cwd
        )
    monkeypatch.chdir(tmp_path)
    assert relative.root == cwd / "state"
    native = tmp_path / "missing data 数学"
    installed = ApplicationPaths.resolve(
        environ={}, mode="installed", platform_default=lambda: native
    )
    assert installed.root == native and not native.exists()


def test_strict_roots_and_aliases_are_confined(tmp_path: Path) -> None:
    root = tmp_path / "root"
    for alias, field in COMPATIBILITY_ALIAS_FIELDS:
        paths = ApplicationPaths.resolve(
            environ={}, mode="installed", root=root, aliases={alias: "custom"}
        )
        assert getattr(paths, field) == (root / "custom").resolve()
        with pytest.raises(ApplicationPathError, match="escapes"):
            ApplicationPaths.resolve(
                environ={}, mode="installed", root=root,
                aliases={alias: tmp_path / "outside"},
            )
    for bad in ("relative", root / ".." / "outside"):
        with pytest.raises(ApplicationPathError):
            ApplicationPaths.resolve(environ={}, mode="installed", root=bad)
    with pytest.raises(ApplicationPathError, match="explicit absolute"):
        ApplicationPaths.resolve(environ={}, mode="container")


def test_source_external_alias_is_explicit(tmp_path: Path) -> None:
    cwd = tmp_path / "startup"
    outside = cwd / "trusted developer corpus"
    paths = ApplicationPaths.resolve(
        environ={},
        mode="source",
        source_root=tmp_path / "source",
        startup_cwd=cwd,
        aliases={"ARXMCP_LANCEDB_PATH": "trusted developer corpus"},
    )
    assert paths.lancedb == outside.resolve()
    assert paths.legacy_external_aliases == ("ARXMCP_LANCEDB_PATH",)


def test_installed_config_uses_one_canonical_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "installed data"
    monkeypatch.setattr(paths_module, "_source_checkout_root", lambda: None)
    monkeypatch.setenv("ARXMCP_DATA_DIR", str(root))
    monkeypatch.setenv("ARXMCP_CACHE_DB_PATH", str(root / "cache/retrieval.db"))
    config = Config()
    assert config.application_paths.mode == "installed"
    assert config.data_dir == root.resolve()
    assert config.lancedb_path == root / "index/lancedb"
    assert config.kuzu_path == root / "index/kuzu"
    assert config.bm25_index_root == root / "index/bm25"
    assert config.notebooks_db_path == root / "cache/notebooks.db"


@requires_symlink
def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    target, outside, link = tmp_path / "target", tmp_path / "out", tmp_path / "link"
    target.mkdir()
    outside.mkdir()
    link.symlink_to(target, target_is_directory=True)
    assert ApplicationPaths.resolve(
        environ={}, mode="installed", root=link
    ).root == target
    (target / "cache").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ApplicationPathError, match="escapes"):
        ApplicationPaths.resolve(environ={}, mode="installed", root=link)


@requires_symlink
def test_symlink_loop_is_rejected(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.symlink_to(second, target_is_directory=True)
    second.symlink_to(first, target_is_directory=True)
    with pytest.raises(ApplicationPathError, match="cannot be resolved"):
        ApplicationPaths.resolve(environ={}, mode="installed", root=first)


def test_prepare_propagates_read_only_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = ApplicationPaths.resolve(
        environ={}, mode="installed", root=tmp_path / "data"
    )
    paths.prepare()
    def denied(**_kwargs):
        raise PermissionError("read-only")
    monkeypatch.setattr(paths_module.tempfile, "mkstemp", denied)
    with pytest.raises(PermissionError, match="read-only"):
        paths.prepare()
