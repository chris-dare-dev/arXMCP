"""notebook-surface-expansion-m1 — notebook-detail parse-status + freshness.

The detail page (server/routes/ui.py::ui_notebook_detail +
frontend/templates/notebook_detail.html) now renders, server-side on page
open:

- a notebook-scoped **parse-status** badge (parse_status lives on the
  ``notebooks`` table — per-notebook, NOT per-paper; arxiv-kind notebooks are
  always ``skipped``); and
- a **"Last indexed <ts>" / "Never indexed"** freshness line from the latest
  ``notebook_ingest_runs`` row.

Seeding goes through the REST surface (notebook create) + a raw sqlite3 INSERT
for the ingest-run row (WAL mode → visible to the store's reads), which avoids
acquiring the store's asyncio.Lock on a foreign event loop. No model load.
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from server.notebooks_store import NotebooksStore
from server.routes import notebooks as notebooks_module
from server.routes.notebooks import router as notebooks_router
from server.routes.ui import router as ui_router
from tools import _notebook_common

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FRONTEND_STATIC: Path = REPO_ROOT / "server" / "frontend" / "static"


@pytest.fixture
def detail_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Path]]:
    """Minimal app (notebooks + ui routers + static) + a real NotebooksStore.

    Yields ``(client, db_path)`` so a test can raw-INSERT ingest-run rows. The
    db is WAL mode, so a separate sqlite3 connection's committed writes are
    visible to the store's reads — and we never touch the async lock from this
    loop, so the TestClient portal owns it cleanly.
    """
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
    monkeypatch.setattr(
        notebooks_module, "_now_iso", lambda: "2026-05-28T16:00:00+00:00"
    )
    db_path = tmp_path / "notebooks.db"
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        app.include_router(notebooks_router, prefix="/ui/api")
        app.include_router(ui_router, prefix="/ui")
        app.mount(
            "/ui/static",
            StaticFiles(directory=str(FRONTEND_STATIC)),
            name="ui-static",
        )
        with TestClient(app) as c:
            yield c, db_path
        loop.run_until_complete(store.close())
    finally:
        loop.close()


def _create_notebook(client: TestClient, slug: str, kind: str = "arxiv") -> None:
    r = client.post(
        "/ui/api/notebooks",
        json={"slug": slug, "display_name": slug, "notebook_kind": kind},
    )
    assert r.status_code in (200, 201), r.text


def _insert_ingest_run(
    db_path: Path, slug: str, *, status: str, finished_at: str | None
) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO notebook_ingest_runs "
            "(slug, status, started_at, finished_at) VALUES (?, ?, ?, ?)",
            (slug, status, "2026-05-28T03:20:00Z", finished_at),
        )
        conn.commit()
    finally:
        conn.close()


class TestParseStatusBadge:
    def test_arxiv_notebook_shows_skipped_badge_and_never_indexed(
        self, detail_client
    ):
        """AC1: an arxiv notebook (no papers, no ingest run) renders the
        per-notebook parse-status badge (default 'skipped' → ok) and a
        'Never indexed' freshness signal. Also covers FM-a (zero papers):
        the badge + freshness are notebook-scoped, outside the papers loop."""
        client, _ = detail_client
        _create_notebook(client, "alpha-nb")
        r = client.get("/ui/notebooks/alpha-nb")
        assert r.status_code == 200
        assert "Parse status" in r.text
        assert "status-badge--ok" in r.text
        assert "skipped" in r.text
        assert "Never indexed" in r.text

    def test_unknown_future_status_renders_literally_with_warn_fallback(
        self, detail_client
    ):
        """FM-d (forward-compat): a parse_status outside the known enum (a
        future migration value; the column is free TEXT, NOT NULL) renders
        LITERALLY (autoescaped) with the `.get(..., 'warn')` CSS fallback —
        never crashes a match/if-chain. (FM-c — NULL parse_status — is
        prevented by the column's NOT NULL constraint + DEFAULT 'skipped',
        so it cannot occur; the template `| default` is belt-and-suspenders.)"""
        client, db_path = detail_client
        _create_notebook(client, "future-nb")
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "UPDATE notebooks SET parse_status = ? WHERE slug = ?",
                ("futurestate", "future-nb"),
            )
            conn.commit()
        finally:
            conn.close()
        r = client.get("/ui/notebooks/future-nb")
        assert r.status_code == 200
        assert "futurestate" in r.text  # rendered literally, no crash
        assert "status-badge--warn" in r.text  # forward-compat css fallback


    @pytest.mark.parametrize(
        ("parse_status", "expected_css"),
        [
            ("complete", "ok"),
            ("skipped", "ok"),
            ("pending", "warn"),
            ("running", "warn"),
            ("failed", "down"),
        ],
    )
    def test_known_enum_maps_to_expected_badge_class(
        self, detail_client, parse_status, expected_css
    ):
        """m1 rect F1: each known parse_status enum value maps to its
        _PARSE_STATUS_CSS class (complete/skipped->ok, pending/running->warn,
        failed->down) and renders the value literally."""
        client, db_path = detail_client
        _create_notebook(client, "enum-nb")
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "UPDATE notebooks SET parse_status = ? WHERE slug = ?",
                (parse_status, "enum-nb"),
            )
            conn.commit()
        finally:
            conn.close()
        r = client.get("/ui/notebooks/enum-nb")
        assert r.status_code == 200
        assert f"status-badge--{expected_css}" in r.text
        assert parse_status in r.text


class TestFreshnessSignal:
    def test_last_indexed_renders_after_a_finished_run(self, detail_client):
        """AC1/AC2: with a finished ingest run, the page shows the
        finished_at timestamp + the run status, and NOT 'Never indexed'."""
        client, db_path = detail_client
        _create_notebook(client, "fresh-nb")
        _insert_ingest_run(
            db_path, "fresh-nb",
            status="success", finished_at="2026-05-28T03:30:00Z",
        )
        r = client.get("/ui/notebooks/fresh-nb")
        assert r.status_code == 200
        assert "2026-05-28T03:30:00Z" in r.text
        # ui-uplift-m7 rectify (critique H2/H6/M5): latest_run.status is a
        # state token and now renders inside <code> for the mono voice, so
        # "ingest success" is no longer a contiguous string. The intent of
        # this assertion is that the status reaches the page — assert that,
        # not one particular markup spelling of it.
        assert "ingest <code>success</code>" in r.text
        assert "Never indexed" not in r.text

    def test_failed_run_renders_finished_at_and_failed_status(
        self, detail_client
    ):
        """m1 rect F1: a FAILED ingest run still renders its finished_at + the
        'failed' status (the freshness line is not success-only)."""
        client, db_path = detail_client
        _create_notebook(client, "failed-nb")
        _insert_ingest_run(
            db_path, "failed-nb",
            status="failed", finished_at="2026-05-28T03:25:00Z",
        )
        r = client.get("/ui/notebooks/failed-nb")
        assert r.status_code == 200
        assert "2026-05-28T03:25:00Z" in r.text
        assert "ingest failed" in r.text
        assert "Never indexed" not in r.text

    def test_running_run_with_no_finished_at_falls_back_to_started(
        self, detail_client
    ):
        """A still-running ingest (finished_at NULL) shows the started_at ts
        rather than 'Never indexed' (the run exists)."""
        client, db_path = detail_client
        _create_notebook(client, "running-nb")
        _insert_ingest_run(
            db_path, "running-nb", status="running", finished_at=None
        )
        r = client.get("/ui/notebooks/running-nb")
        assert r.status_code == 200
        assert "2026-05-28T03:20:00Z" in r.text  # started_at fallback
        assert "Never indexed" not in r.text
