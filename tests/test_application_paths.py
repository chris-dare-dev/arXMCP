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


def test_installed_notebook_uses_derived_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "installed data"
    notebook = root / "notebooks" / "demo-nb"
    marker = notebook / "lancedb" / "corpus-version.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(paths_module, "_source_checkout_root", lambda: None)
    monkeypatch.setenv("ARXMCP_DATA_DIR", str(root))
    monkeypatch.setenv("ARXMCP_NOTEBOOK", "demo-nb")
    monkeypatch.delenv("ARXMCP_CACHE_DB_PATH", raising=False)

    config = Config()
    assert config.lancedb_path == notebook / "lancedb"
    assert config.cache_db_path == notebook / "cache/retrieval.db"
    assert config.bm25_index_root == notebook / "index/bm25"
    assert config.application_paths.lancedb == config.lancedb_path
    assert config.application_paths.retrieval_cache_db == config.cache_db_path
    assert config.application_paths.bm25 == config.bm25_index_root

    monkeypatch.setenv("ARXMCP_LANCEDB_PATH", str(root / "other-lancedb"))
    with pytest.raises(ValueError, match="either|both"):
        Config()


def test_source_config_propagates_explicit_root_and_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    startup = tmp_path / "startup"
    root = tmp_path / "chosen root"
    source.mkdir()
    startup.mkdir()
    monkeypatch.setattr(paths_module, "_source_checkout_root", lambda: source)
    monkeypatch.setattr(paths_module, "_STARTUP_CWD", startup)
    monkeypatch.setenv("ARXMCP_DATA_DIR", str(root))
    monkeypatch.delenv("ARXMCP_CACHE_DB_PATH", raising=False)

    config = Config()
    field_pairs = (
        ("lancedb_path", "lancedb"),
        ("kuzu_path", "kuzu"),
        ("cache_db_path", "retrieval_cache_db"),
        ("bm25_index_root", "bm25"),
        ("theorem_names_db_path", "theorem_names_db"),
        ("notebooks_db_path", "notebooks_db"),
        ("ops_dir", "ops"),
    )
    assert config.data_dir == root.resolve()
    for config_field, paths_field in field_pairs:
        value = getattr(config, config_field)
        assert value == getattr(config.application_paths, paths_field)
        value.relative_to(root.resolve())

    monkeypatch.chdir(tmp_path)
    assert config.lancedb_path == root.resolve() / "index/lancedb"

    monkeypatch.setenv("ARXMCP_LANCEDB_PATH", "trusted corpus")
    external = Config()
    assert external.lancedb_path == (startup / "trusted corpus").resolve()
    assert external.application_paths.lancedb == external.lancedb_path
    assert external.application_paths.legacy_external_aliases == (
        "ARXMCP_LANCEDB_PATH",
    )


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
