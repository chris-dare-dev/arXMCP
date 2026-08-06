from pathlib import Path

import pytest

import tools.desktop_sidecar_spike as spike
from tools.desktop_sidecar_spike import (
    launch_environment,
    tree_manifest,
    tree_statistics,
    validate_frozen_paths,
    validate_launch_environment,
)


def test_launch_environment_is_offline_and_sanitized(tmp_path: Path) -> None:
    env = launch_environment(tmp_path / "root with 空白", 7811)
    validate_launch_environment(env)
    assert env["ARXMCP_BIND_HOST"] == "127.0.0.1"
    assert env["ARXMCP_DATA_DIR"].startswith(str(tmp_path))
    assert "PYTHONPATH" not in env
    assert "KMP_DUPLICATE_LIB_OK" not in env


@pytest.mark.parametrize(
    "key", ["KMP_DUPLICATE_LIB_OK", "PYTHONHOME", "PYTHONPATH", "DYLD_LIBRARY_PATH"]
)
def test_launch_environment_rejects_ambient_paths(tmp_path: Path, key: str) -> None:
    env = launch_environment(tmp_path, 7812)
    env[key] = "/host/path"
    with pytest.raises(RuntimeError, match="forbidden environment"):
        validate_launch_environment(env)


def test_tree_manifest_detects_bundle_mutation(tmp_path: Path) -> None:
    payload = tmp_path / "bundle" / "asset.css"
    payload.parent.mkdir()
    payload.write_text("one", encoding="utf-8")
    before = tree_manifest(tmp_path)
    payload.write_text("two", encoding="utf-8")
    assert tree_manifest(tmp_path) != before


def test_tree_manifest_detects_symlink_retarget(tmp_path: Path) -> None:
    first, other = tmp_path / "first.bin", tmp_path / "other.bin"
    first.write_bytes(b"a")
    other.write_bytes(b"b")
    link = tmp_path / "alias"
    try:
        link.symlink_to(first.name)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks unavailable")
    before = tree_manifest(tmp_path)
    link.unlink()
    link.symlink_to(other.name)
    assert tree_manifest(tmp_path) != before


def test_tree_statistics_do_not_follow_symlinks(tmp_path: Path) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"data")
    link = tmp_path / "payload-link"
    try:
        link.symlink_to(payload.name)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks unavailable")
    measured = tree_statistics(tmp_path)
    assert measured["regular_files"] == 1
    assert measured["symlinks"] == 1
    assert measured["logical_bytes"] == 4


def test_frozen_paths_must_stay_in_bundle(tmp_path: Path, monkeypatch) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.setattr("sys.executable", str(bundle / "arxmcp-sidecar"))
    monkeypatch.setattr("sys.path", [str(bundle / "_internal")])
    validate_frozen_paths(bundle)
    monkeypatch.setattr("sys.path", ["/opt/homebrew/lib/python3.12"])
    with pytest.raises(RuntimeError, match="escaped bundle"):
        validate_frozen_paths(bundle)


def test_probe_calls_freeze_support(monkeypatch, capsys) -> None:
    calls = []
    monkeypatch.setattr(spike.multiprocessing, "freeze_support", lambda: calls.append(True))
    monkeypatch.setattr(spike, "validate_launch_environment", lambda _env: None)
    monkeypatch.setattr(spike, "_native_model_probe", lambda: {"ok": True})
    assert spike.main(["probe"]) == 0
    assert calls == [True]
    assert '"ok": true' in capsys.readouterr().out
