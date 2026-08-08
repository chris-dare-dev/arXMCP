"""Regression coverage for Config-owned installed-runtime writable paths."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server.fastmcp import FastMCP

from server.config import Config
from server.ingest_tracker import IngestTaskTracker
from server.mcp_resources import (
    CORPUS_MANIFEST_URI,
    register_resources,
    reset_notebooks_store_for_tests,
    set_notebooks_store,
)
from server.notebooks_store import NotebooksStore
from server.routes.notebooks import router as notebooks_router
from server.routes.ui import router as ui_router
from server.tools import reset_resources_for_tests, set_resources
from tools import _notebook_common, wheel_install_check

REPO_ROOT = Path(__file__).resolve().parents[1]


def _minimal_subprocess_environment() -> dict[str, str]:
    environment = {"PATH": "/usr/bin:/bin"}
    if sys.platform == "win32":
        for name in ("SYSTEMROOT", "WINDIR"):
            if value := os.environ.get(name):
                environment[name] = value
    return environment


def test_http_consumers_ignore_import_time_writable_roots(
    tmp_path: Path, monkeypatch
) -> None:
    """A Config data root wins even when legacy module globals are poisoned."""
    runtime_root = tmp_path / "runtime"
    poison = tmp_path / "poison"
    config = Config(data_dir=runtime_root)
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", poison / "notebooks")
    monkeypatch.setattr(
        _notebook_common, "CORPUS_PARSED_DIR", poison / "corpus" / "parsed"
    )

    loop = asyncio.new_event_loop()
    store = loop.run_until_complete(
        NotebooksStore.open(config.notebooks_db_path)
    )
    app = FastAPI()
    app.state.config = config
    app.state.notebooks_store = store
    app.include_router(notebooks_router, prefix="/ui/api")
    app.include_router(ui_router, prefix="/ui")
    try:
        with TestClient(app) as client:
            response = client.post(
                "/ui/api/notebooks", json={"slug": "demo-nb"}
            )
            assert response.status_code == 201, response.text
            preview = (
                config.application_paths.notebooks
                / "demo-nb"
                / "ar5iv"
                / "2604.26204.html"
            )
            preview.parent.mkdir(parents=True, exist_ok=True)
            preview.write_text("<html>configured root</html>", encoding="utf-8")
            shown = client.get(
                "/ui/notebooks/demo-nb/papers/2604.26204/preview"
            )
            assert shown.status_code == 200
            assert "configured root" in shown.text
    finally:
        loop.run_until_complete(store.close())
        loop.close()

    assert (runtime_root / "notebooks" / "demo-nb").is_dir()
    assert not poison.exists()


def test_per_notebook_retrieval_uses_configured_base(
    tmp_path: Path, monkeypatch
) -> None:
    from server import resources as resources_module
    from server.resources import Resources, Singleflight

    config = Config(data_dir=tmp_path / "runtime")
    seen_bases: list[Path | None] = []

    def fake_notebook_path(slug: str, *, base: Path | None = None) -> Path:
        seen_bases.append(base)
        return (base or tmp_path / "wrong") / slug / "lancedb"

    monkeypatch.setattr(
        _notebook_common, "notebook_lancedb_path", fake_notebook_path
    )
    monkeypatch.setattr(
        resources_module,
        "read_corpus_version",
        lambda path: SimpleNamespace(version=7),
    )
    monkeypatch.setattr(
        resources_module,
        "open_chunks_table_with_fallback",
        lambda **kwargs: (SimpleNamespace(path=kwargs["lancedb_path"]), None),
    )
    resources = Resources(
        config=config,
        corpus_info=SimpleNamespace(version=1),
        chunks_table=None,
        embed_semaphore=asyncio.Semaphore(1),
        rerank_semaphore=asyncio.Semaphore(1),
        rerank_singleflight=Singleflight(),
    )

    asyncio.run(resources.notebook_table("demo-nb"))

    assert seen_bases == [config.application_paths.notebooks]


def test_mcp_resources_use_live_config_paths(
    tmp_path: Path, monkeypatch
) -> None:
    from server import corpus_manifest

    config = Config(data_dir=tmp_path / "runtime")
    poison = tmp_path / "poison-notebooks"
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", poison)
    seen: dict[str, Path | None] = {}

    async def fake_manifest(store, *, base=None, settings_db_path=None):
        seen["base"] = base
        seen["settings_db_path"] = settings_db_path
        return {"snapshot": {"notebooks": {}}}

    monkeypatch.setattr(corpus_manifest, "build_manifest", fake_manifest)

    async def exercise() -> None:
        store = await NotebooksStore.open(config.notebooks_db_path)
        await store.create_notebook(
            slug="demo-nb",
            display_name="Demo",
            lancedb_path="redacted",
            created_at="2026-08-06T00:00:00Z",
        )
        (config.application_paths.notebooks / "demo-nb" / "lancedb").mkdir(
            parents=True
        )
        set_resources(SimpleNamespace(config=config))
        set_notebooks_store(store)
        mcp = FastMCP("arxmcp", json_response=True)
        register_resources(mcp)
        try:
            detail = await mcp.read_resource("arxmcp://notebooks/demo-nb")
            assert '"is_ingested": true' in detail[0].content
            await mcp.read_resource(CORPUS_MANIFEST_URI)
        finally:
            await store.close()
            reset_notebooks_store_for_tests()
            reset_resources_for_tests()

    asyncio.run(exercise())

    assert seen == {
        "base": config.application_paths.notebooks,
        "settings_db_path": config.application_paths.notebooks_db,
    }
    assert not poison.exists()


def test_relocated_child_environment_removes_parent_path_influence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "application-data"
    ambient = {
        "PATH": "/usr/bin:/bin",
        "SAFE_SETTING": "preserved",
        "ARXMCP_LANCEDB_PATH": "/parent/leak",
        "ARXMCP_CONTACT_EMAIL": "parent@example.invalid",
        "PYTHONPATH": "/editable/checkout",
        "PYTHONHOME": "/parent/python",
        "PYTHONHASHSEED": "parent-value",
        "DYLD_LIBRARY_PATH": "/parent/dylib",
        "LD_PRELOAD": "/parent/preload.so",
        "VIRTUAL_ENV": "/parent/venv",
        "PWD": "/parent/cwd",
        "OLDPWD": "/parent/old-cwd",
    }

    env = wheel_install_check.build_relocated_child_environment(
        root, 47123, environ=ambient
    )

    assert env["PATH"] == ambient["PATH"]
    assert env["SAFE_SETTING"] == "preserved"
    for removed in (
        "ARXMCP_LANCEDB_PATH",
        "ARXMCP_CONTACT_EMAIL",
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONHASHSEED",
        "DYLD_LIBRARY_PATH",
        "LD_PRELOAD",
        "VIRTUAL_ENV",
        "PWD",
        "OLDPWD",
    ):
        assert removed not in env

    canonical_root = root.resolve()
    assert env["ARXMCP_DATA_DIR"] == str(canonical_root)
    assert env["ARXMCP_BIND_PORT"] == "47123"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    for redirected in (
        "HOME",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
        "XDG_DATA_HOME",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "HF_HOME",
        "TRANSFORMERS_CACHE",
        "MPLCONFIGDIR",
        "TMPDIR",
        "TEMP",
        "TMP",
    ):
        path = Path(env[redirected])
        assert path.is_dir()
        assert path.is_relative_to(canonical_root)


def test_manifest_guard_rejects_an_arbitrary_cwd_write(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    data = sandbox / "data"
    cwd = sandbox / "cwd"
    data.mkdir(parents=True)
    cwd.mkdir()
    before = wheel_install_check.filesystem_metadata_manifest(sandbox)

    allowed = data / "logs" / "server.log"
    allowed.parent.mkdir()
    allowed.write_text("inside root", encoding="utf-8")
    after_allowed = wheel_install_check.filesystem_metadata_manifest(sandbox)
    wheel_install_check.assert_manifest_changes_confined(
        "test sandbox", before, after_allowed, allowed_prefix="data"
    )

    (cwd / "leak.db").write_text("outside root", encoding="utf-8")
    after_leak = wheel_install_check.filesystem_metadata_manifest(sandbox)
    with pytest.raises(wheel_install_check.CheckFailed, match="leak.db"):
        wheel_install_check.assert_manifest_changes_confined(
            "test sandbox", before, after_leak, allowed_prefix="data"
        )


def test_manifest_guard_watches_application_parent_and_file_bytes(
    tmp_path: Path,
) -> None:
    application_parent = tmp_path / "application"
    venv = application_parent / "venv"
    venv.mkdir(parents=True)
    module = venv / "module.py"
    module.write_text("AAAA", encoding="utf-8")
    before = wheel_install_check.filesystem_metadata_manifest(
        application_parent, hash_contents=True
    )

    original = module.stat()
    module.write_text("BBBB", encoding="utf-8")
    os.utime(module, ns=(original.st_atime_ns, original.st_mtime_ns))
    rewritten = wheel_install_check.filesystem_metadata_manifest(
        application_parent, hash_contents=True
    )
    assert "venv/module.py" in wheel_install_check.changed_manifest_paths(
        before, rewritten
    )

    (application_parent / "leak.db").write_text("sibling", encoding="utf-8")
    after_leak = wheel_install_check.filesystem_metadata_manifest(
        application_parent, hash_contents=True
    )
    with pytest.raises(wheel_install_check.CheckFailed, match="leak.db"):
        wheel_install_check.assert_manifest_unchanged(
            "installed application parent", before, after_leak
        )


def test_wheel_provenance_requires_canonical_containment(tmp_path: Path) -> None:
    site_packages = tmp_path / "site-packages"
    installed = site_packages / "server" / "__init__.py"
    installed.parent.mkdir(parents=True)
    installed.write_text("installed", encoding="utf-8")
    assert wheel_install_check._assert_installed_provenance(
        str(installed), str(site_packages)
    ) == installed.resolve()

    sibling = tmp_path / "site-packages-shadow" / "server" / "__init__.py"
    sibling.parent.mkdir(parents=True)
    sibling.write_text("shadow", encoding="utf-8")
    with pytest.raises(wheel_install_check.CheckFailed, match="SHADOWED"):
        wheel_install_check._assert_installed_provenance(
            str(sibling), str(site_packages)
        )

    symlink = site_packages / "linked-server.py"
    try:
        symlink.symlink_to(sibling)
    except OSError:
        pytest.skip("platform cannot create symlinks")
    with pytest.raises(wheel_install_check.CheckFailed, match="SHADOWED"):
        wheel_install_check._assert_installed_provenance(
            str(symlink), str(site_packages)
        )


def test_server_ingest_child_uses_application_paths(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "application-data"
    captured: dict[str, object] = {}

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_spawn(*args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs.get("env")
        return FakeProcess()

    monkeypatch.setattr(
        "server.ingest_tracker.asyncio.create_subprocess_exec", fake_spawn
    )

    async def exercise_tracker() -> None:
        store = await NotebooksStore.open(tmp_path / "tracker.db")
        await store.create_notebook(
            slug="demo-nb",
            display_name="Demo",
            lancedb_path="redacted",
            created_at="2026-08-06T00:00:00Z",
        )
        run_id = await store.insert_ingest_run(
            "demo-nb", "2026-08-06T00:00:00Z"
        )
        tracker = IngestTaskTracker(data_root=root)
        await tracker._run_ingest_subprocess(
            "demo-nb", run_id, store, lambda: "2026-08-06T00:01:00Z"
        )
        await store.close()

    asyncio.run(exercise_tracker())
    assert captured["args"][:3] == (
        sys.executable,
        "-m",
        "tools.notebook_ingest",
    )
    child_env = captured["env"]
    assert isinstance(child_env, dict)
    assert child_env["ARXMCP_DATA_DIR"] == str(root.resolve())

    env = wheel_install_check.build_relocated_child_environment(
        root, 47300, environ=_minimal_subprocess_environment()
    )
    env["PYTHONPATH"] = str(REPO_ROOT)
    probe = (
        "import json\n"
        "import server.application_paths as application_paths\n"
        "application_paths._source_checkout_root = lambda: None\n"
        "from tools.notebook_ingest import runtime_paths_report\n"
        "print(json.dumps(runtime_paths_report(), sort_keys=True))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["mode"] == "installed"
    for label, raw_path in report.items():
        if label != "mode":
            assert Path(raw_path).is_relative_to(root.resolve()), label


def test_installed_writer_probe_is_independent_of_cwd(tmp_path: Path) -> None:
    """Real writers stay under the configured root in installed path mode."""
    checkout_before = wheel_install_check.filesystem_metadata_manifest(
        REPO_ROOT
    )
    reports: list[dict[str, str]] = []
    probe = (
        "import server.application_paths as application_paths\n"
        "application_paths._source_checkout_root = lambda: None\n"
        + wheel_install_check._WRITER_PROBE
    )

    for ordinal in (1, 2):
        cwd = tmp_path / f"arbitrary-cwd-{ordinal}"
        root = tmp_path / f"application-data-{ordinal}"
        cwd.mkdir()
        env = wheel_install_check.build_relocated_child_environment(
            root, 47200 + ordinal, environ=_minimal_subprocess_environment()
        )
        # This always-on test imports the worktree to exercise the same code
        # cheaply.  The full-wheel gate deliberately has no PYTHONPATH and
        # separately proves imports resolve inside its isolated site-packages.
        env["PYTHONPATH"] = str(REPO_ROOT)
        cwd_before = wheel_install_check.filesystem_metadata_manifest(cwd)
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads(result.stdout.strip().splitlines()[-1])
        reports.append(report)
        assert report["mode"] == "installed"
        assert report["settings_value"] == "ok"
        canonical_root = root.resolve()
        for key, raw_path in report.items():
            if key not in {"mode", "settings_value"}:
                assert Path(raw_path).is_relative_to(canonical_root)
        assert (root / "cache" / "retrieval.db").is_file()
        assert (root / "cache" / "notebooks.db").is_file()
        assert (
            root / "index" / "lancedb" / "corpus-version.json"
        ).is_file()
        cwd_after = wheel_install_check.filesystem_metadata_manifest(cwd)
        wheel_install_check.assert_manifest_unchanged(
            f"arbitrary CWD {ordinal}", cwd_before, cwd_after
        )

    assert reports[0]["root"] != reports[1]["root"]
    checkout_after = wheel_install_check.filesystem_metadata_manifest(
        REPO_ROOT
    )
    wheel_install_check.assert_manifest_unchanged(
        "source checkout", checkout_before, checkout_after
    )
