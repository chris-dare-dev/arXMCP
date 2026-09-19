"""AC-A.18 (stage2/arx-a45) — markdown chunker selectable via the API.

Covers the whole chain that surfaces ``--chunker markdown`` in the UI/API
parse path (workstreams.md WS-A A4; acceptance-criteria.md AC-A.18):

1. ``NotebooksStore`` v5→v6 additive migration (``textbook_chunker``
   column, DEFAULT ``'html'`` backfill, idempotent re-open).
2. ``NotebookCreate.chunker`` validation — ``markdown`` accepted for
   textbook-kind, 422 on arxiv-kind, 422 on out-of-domain values —
   and persistence through ``POST /ui/api/notebooks``.
3. ``ParseTaskTracker`` markdown mode — LaTeXML render SKIPPED, MinerU
   markdown presence required, ``parsed_html_path=''`` on the complete
   row; html mode byte-identical to the historical behavior.
4. ``IngestTaskTracker`` kind-aware argv — textbook dispatch spawns
   ``tools.notebook_textbook_ingest ... --chunker <c>``; arxiv keeps
   ``tools.notebook_ingest``.
5. Route dispatch — the ingest trigger passes the stored chunker +
   junction-row paper_ids; a paperless textbook notebook 422s.
6. The AC-A.18 FIXTURE PARITY test — the server-built argv, fed through
   the real CLI argparse on a real MinerU-markdown fixture tree,
   produces chunk-for-chunk the SAME records as the operator-run CLI
   path (they are one implementation; the test pins that they stay so).

Conventions per tests/test_parse_tracker.py: no pytest-asyncio; async
bodies run via ``asyncio.run()``. Heavy work (MinerU, LaTeXML, BGE-M3)
is mocked or dry-run; no model download, no subprocess spawn.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import tools._notebook_common as _notebook_common
from ingest.textbook_parser import MinerUResult
from server.ingest_tracker import IngestTaskTracker
from server.notebooks_store import SCHEMA_VERSION, NotebooksStore
from server.parse_tracker import ParseTaskTracker, count_mineru_markdown
from server.routes import notebooks as notebooks_module
from server.routes.notebooks import router as notebooks_router

if TYPE_CHECKING:
    from collections.abc import Iterator

# ---------------------------------------------------------------------------
# Fixtures (mirroring tests/test_notebook_api.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def notebooks_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect NOTEBOOKS_BASE so create_notebook writes inside tmp_path."""
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
    return base


@pytest.fixture
def client(
    tmp_path: Path, notebooks_base: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """Minimal FastAPI app + real NotebooksStore on tmp_path."""
    db_path = tmp_path / "notebooks.db"
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        app.include_router(notebooks_router, prefix="/ui/api")
        monkeypatch.setattr(
            notebooks_module, "_now_iso",
            lambda: "2026-07-04T03:00:00+00:00",
        )
        with TestClient(app) as c:
            c.app_store = store  # type: ignore[attr-defined]
            c.app_loop = loop  # type: ignore[attr-defined]
            yield c
        loop.run_until_complete(store.close())
    finally:
        loop.close()


def _make_store_mock() -> MagicMock:
    store = MagicMock()
    store.PARSE_STATUS_SKIPPED = "skipped"
    store.PARSE_STATUS_PENDING = "pending"
    store.PARSE_STATUS_RUNNING = "running"
    store.PARSE_STATUS_COMPLETE = "complete"
    store.PARSE_STATUS_FAILED = "failed"
    store.update_parse_status = AsyncMock(return_value=True)
    return store


def _make_mineru_result(tmp_path: Path) -> MinerUResult:
    return MinerUResult(
        output_dir=tmp_path / "mineru",
        markdown_path=tmp_path / "mineru" / "x" / "auto" / "x.md",
        content_list_path=tmp_path / "mineru" / "x" / "auto" / "x_cl.json",
        stdout="", stderr="", wall_clock_s=5.0,
    )


def _seed_mineru_markdown(output_dir: Path, text: str = "# H\n\nbody.") -> Path:
    """Create a MinerU-shaped ``<stem>/auto/<stem>.md`` under output_dir."""
    auto = output_dir / "book" / "auto"
    auto.mkdir(parents=True, exist_ok=True)
    md = auto / "book.md"
    md.write_text(text, encoding="utf-8")
    return md


# ---------------------------------------------------------------------------
# 1. Store migration v5 → v6
# ---------------------------------------------------------------------------


class TestV5ToV6Migration:
    def test_schema_version_is_6(self) -> None:
        assert SCHEMA_VERSION == 6

    def test_v5_to_v6_backfills_html(self, tmp_path: Path) -> None:
        """A pre-arx-a45 (v5) row backfills textbook_chunker='html' and
        the DB lands at user_version 6."""
        db_path = tmp_path / "notebooks.db"

        async def _seed_v5_and_query_v6() -> tuple[dict, int]:
            conn = sqlite3.connect(str(db_path))
            try:
                # Full v5 notebooks shape (all 10 columns present).
                conn.execute(
                    "CREATE TABLE notebooks ("
                    "  slug               TEXT PRIMARY KEY,"
                    "  display_name       TEXT NOT NULL DEFAULT '',"
                    "  lancedb_path       TEXT NOT NULL,"
                    "  created_at         TEXT NOT NULL,"
                    "  notebook_kind      TEXT NOT NULL DEFAULT 'arxiv',"
                    "  parse_status       TEXT NOT NULL DEFAULT 'skipped',"
                    "  parse_error        TEXT NOT NULL DEFAULT '',"
                    "  parsed_html_path   TEXT NOT NULL DEFAULT '',"
                    "  discovery_category TEXT NOT NULL DEFAULT '',"
                    "  description        TEXT NOT NULL DEFAULT ''"
                    ")"
                )
                conn.execute(
                    "CREATE TABLE notebook_papers ("
                    "  slug      TEXT NOT NULL,"
                    "  paper_id  TEXT NOT NULL,"
                    "  added_at  TEXT NOT NULL,"
                    "  PRIMARY KEY (slug, paper_id)"
                    ")"
                )
                conn.execute(
                    "INSERT INTO notebooks "
                    "(slug, display_name, lancedb_path, created_at, "
                    " notebook_kind, parse_status) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        "legacy-v5-textbook",
                        "Legacy v5",
                        "/tmp/legacy/lancedb",
                        "2026-06-01T00:00:00+00:00",
                        "textbook",
                        "complete",
                    ),
                )
                conn.execute("PRAGMA user_version = 5")
                conn.commit()
            finally:
                conn.close()

            store = await NotebooksStore.open(db_path)
            try:
                row = await store.get_notebook("legacy-v5-textbook")
            finally:
                await store.close()

            conn = sqlite3.connect(str(db_path))
            try:
                version = int(
                    conn.execute("PRAGMA user_version").fetchone()[0]
                )
            finally:
                conn.close()
            return row, version

        row, version = asyncio.run(_seed_v5_and_query_v6())
        assert version == 6
        assert row is not None
        assert row["textbook_chunker"] == "html", (
            "legacy rows must backfill textbook_chunker='html' via the "
            "v5→v6 ALTER TABLE DEFAULT"
        )
        # Pre-existing fields survive the migration untouched.
        assert row["notebook_kind"] == "textbook"
        assert row["parse_status"] == "complete"

    def test_v6_reopen_is_idempotent(self, tmp_path: Path) -> None:
        """Re-opening a v6 DB does not re-run the v5→v6 ALTER (which
        would raise 'duplicate column name')."""
        db_path = tmp_path / "notebooks.db"

        async def _open_twice() -> int:
            store = await NotebooksStore.open(db_path)
            await store.create_notebook(
                slug="tb", display_name="", lancedb_path="/x",
                created_at="2026-07-04T00:00:00+00:00",
                notebook_kind="textbook", parse_status="pending",
                textbook_chunker="markdown",
            )
            await store.close()
            store = await NotebooksStore.open(db_path)
            row = await store.get_notebook("tb")
            await store.close()
            if row is None:
                raise AssertionError("row lost across reopen")
            return 0 if row["textbook_chunker"] == "markdown" else 1

        assert asyncio.run(_open_twice()) == 0

    def test_create_default_is_html(self, tmp_path: Path) -> None:
        """create_notebook without the param stores 'html' (both INSERT
        branches: parse_status None and explicit)."""
        db_path = tmp_path / "notebooks.db"

        async def _create() -> tuple[str, str]:
            store = await NotebooksStore.open(db_path)
            await store.create_notebook(
                slug="a", display_name="", lancedb_path="/x",
                created_at="2026-07-04T00:00:00+00:00",
            )
            await store.create_notebook(
                slug="b", display_name="", lancedb_path="/x",
                created_at="2026-07-04T00:00:00+00:00",
                notebook_kind="textbook", parse_status="pending",
            )
            ra = await store.get_notebook("a")
            rb = await store.get_notebook("b")
            await store.close()
            return ra["textbook_chunker"], rb["textbook_chunker"]

        assert asyncio.run(_create()) == ("html", "html")


# ---------------------------------------------------------------------------
# 2. NotebookCreate API validation + persistence
# ---------------------------------------------------------------------------


class TestCreateNotebookChunkerField:
    def test_textbook_markdown_persisted(self, client: TestClient) -> None:
        r = client.post(
            "/ui/api/notebooks",
            json={
                "slug": "md-book",
                "notebook_kind": "textbook",
                "chunker": "markdown",
            },
        )
        assert r.status_code == 201, r.text
        store: NotebooksStore = client.app_store  # type: ignore[attr-defined]
        loop = client.app_loop  # type: ignore[attr-defined]
        row = loop.run_until_complete(store.get_notebook("md-book"))
        assert row["textbook_chunker"] == "markdown"

    def test_textbook_default_is_html(self, client: TestClient) -> None:
        r = client.post(
            "/ui/api/notebooks",
            json={"slug": "html-book", "notebook_kind": "textbook"},
        )
        assert r.status_code == 201, r.text
        store: NotebooksStore = client.app_store  # type: ignore[attr-defined]
        loop = client.app_loop  # type: ignore[attr-defined]
        row = loop.run_until_complete(store.get_notebook("html-book"))
        assert row["textbook_chunker"] == "html"

    def test_arxiv_with_markdown_chunker_422(self, client: TestClient) -> None:
        """A markdown chunker on an arxiv notebook would be a silent
        no-op — the handler rejects it loudly instead."""
        r = client.post(
            "/ui/api/notebooks",
            json={
                "slug": "bad-combo",
                "notebook_kind": "arxiv",
                "chunker": "markdown",
            },
        )
        assert r.status_code == 422
        assert "textbook-kind" in r.json()["detail"]

    def test_out_of_domain_chunker_422(self, client: TestClient) -> None:
        r = client.post(
            "/ui/api/notebooks",
            json={
                "slug": "bad-chunker",
                "notebook_kind": "textbook",
                "chunker": "freeform-garbage",
            },
        )
        assert r.status_code == 422  # Pydantic pattern rejection

    def test_list_notebooks_carries_chunker(self, client: TestClient) -> None:
        """The stored value surfaces in the list dicts (consumed by the
        /api/v1 alias + WS-B notebook cards)."""
        client.post(
            "/ui/api/notebooks",
            json={
                "slug": "md-book",
                "notebook_kind": "textbook",
                "chunker": "markdown",
            },
        )
        r = client.get("/ui/api/notebooks")
        assert r.status_code == 200
        rows = {row["slug"]: row for row in r.json()}
        assert rows["md-book"]["textbook_chunker"] == "markdown"


# ---------------------------------------------------------------------------
# 3. ParseTaskTracker markdown mode
# ---------------------------------------------------------------------------


class TestCountMinerUMarkdown:
    def test_missing_dir_is_zero(self, tmp_path: Path) -> None:
        assert count_mineru_markdown(tmp_path / "nope") == 0

    def test_counts_nested_auto_md(self, tmp_path: Path) -> None:
        out = tmp_path / "out"
        _seed_mineru_markdown(out)
        assert count_mineru_markdown(out) == 1
        # A stray .md OUTSIDE an auto/ dir does not count (mirrors the
        # markdown chunker's **/auto/*.md discovery exactly).
        (out / "notes.md").write_text("x", encoding="utf-8")
        assert count_mineru_markdown(out) == 1


class TestParseTrackerMarkdownMode:
    def test_markdown_skips_render_and_completes_with_empty_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store = _make_store_mock()
        out_dir = tmp_path / "out"
        _seed_mineru_markdown(out_dir)
        mineru_result = _make_mineru_result(tmp_path)

        from ingest import textbook_parser, textbook_renderer
        monkeypatch.setattr(
            textbook_parser, "run_mineru_sandboxed",
            lambda pdf_path, output_dir: mineru_result,
        )

        def _render_must_not_run(r, p, pid):  # noqa: ARG001
            raise AssertionError(
                "render_mineru_to_html must NOT be called in markdown mode"
            )

        monkeypatch.setattr(
            textbook_renderer, "render_mineru_to_html", _render_must_not_run,
        )

        async def _run() -> None:
            tracker = ParseTaskTracker()
            task = tracker.start_parse(
                slug="md-book",
                pdf_path=tmp_path / "x.pdf",
                paper_id="textbook:md-book",
                output_dir=out_dir,
                parsed_dir=tmp_path / "parsed",
                store=store,
                chunker="markdown",
            )
            await task

        asyncio.run(_run())
        store.update_parse_status.assert_called_once()
        call = store.update_parse_status.call_args
        assert call.args[1] == "complete"
        assert call.kwargs["parsed_html_path"] == ""

    def test_markdown_with_no_mineru_output_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """MinerU 'succeeded' but produced no **/auto/*.md — the
        markdown chunker would find nothing, so the parse must FAIL
        (not complete into a permanently 0-chunk notebook)."""
        store = _make_store_mock()
        out_dir = tmp_path / "out"  # exists but empty
        out_dir.mkdir()
        mineru_result = _make_mineru_result(tmp_path)

        from ingest import textbook_parser
        monkeypatch.setattr(
            textbook_parser, "run_mineru_sandboxed",
            lambda pdf_path, output_dir: mineru_result,
        )

        async def _run() -> None:
            tracker = ParseTaskTracker()
            task = tracker.start_parse(
                slug="md-book",
                pdf_path=tmp_path / "x.pdf",
                paper_id="textbook:md-book",
                output_dir=out_dir,
                parsed_dir=tmp_path / "parsed",
                store=store,
                chunker="markdown",
            )
            await task

        asyncio.run(_run())
        call = store.update_parse_status.call_args
        assert call.args[1] == "failed"
        assert "markdown" in call.kwargs["parse_error"]

    def test_html_mode_still_renders(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Default mode regression pin: the render rung runs and the
        rendered path is stored (the historical contract)."""
        from ingest.textbook_renderer import RenderResult

        store = _make_store_mock()
        mineru_result = _make_mineru_result(tmp_path)
        render_result = RenderResult(
            output_html_path=tmp_path / "parsed" / "x" / "index.html",
            wall_clock_s=2.0,
            latex_error_annotations=0,
        )
        rendered: list[str] = []

        from ingest import textbook_parser, textbook_renderer
        monkeypatch.setattr(
            textbook_parser, "run_mineru_sandboxed",
            lambda pdf_path, output_dir: mineru_result,
        )
        monkeypatch.setattr(
            textbook_renderer, "render_mineru_to_html",
            lambda r, p, pid: (rendered.append(pid), render_result)[1],
        )

        async def _run() -> None:
            tracker = ParseTaskTracker()
            task = tracker.start_parse(
                slug="html-book",
                pdf_path=tmp_path / "x.pdf",
                paper_id="textbook:html-book",
                output_dir=tmp_path / "out",
                parsed_dir=tmp_path / "parsed",
                store=store,
                # chunker omitted — default 'html'
            )
            await task

        asyncio.run(_run())
        assert rendered == ["textbook:html-book"]
        call = store.update_parse_status.call_args
        assert call.args[1] == "complete"
        assert call.kwargs["parsed_html_path"] != ""


# ---------------------------------------------------------------------------
# 4. IngestTaskTracker kind-aware argv
# ---------------------------------------------------------------------------


class TestIngestTrackerDispatchArgs:
    def test_arxiv_default_argv(self) -> None:
        tracker = IngestTaskTracker()
        args = tracker._build_subprocess_args(
            "my-nb", notebook_kind="arxiv",
            textbook_chunker="html", textbook_paper_ids=[],
        )
        assert args == ["-m", "tools.notebook_ingest", "my-nb"]

    def test_textbook_markdown_argv(self) -> None:
        tracker = IngestTaskTracker()
        args = tracker._build_subprocess_args(
            "md-book", notebook_kind="textbook",
            textbook_chunker="markdown",
            textbook_paper_ids=["textbook:md-book"],
        )
        assert args == [
            "-m", "tools.notebook_textbook_ingest", "md-book",
            "--paper-id", "textbook:md-book",
            "--chunker", "markdown",
        ]

    def test_textbook_multi_segment_argv(self) -> None:
        """Multi-segment textbooks (partNN uploads) each get their own
        --paper-id, order preserved."""
        tracker = IngestTaskTracker()
        args = tracker._build_subprocess_args(
            "seg-book", notebook_kind="textbook",
            textbook_chunker="html",
            textbook_paper_ids=[
                "textbook:seg-book:part01", "textbook:seg-book:part02",
            ],
        )
        assert args == [
            "-m", "tools.notebook_textbook_ingest", "seg-book",
            "--paper-id", "textbook:seg-book:part01",
            "--paper-id", "textbook:seg-book:part02",
            "--chunker", "html",
        ]


# ---------------------------------------------------------------------------
# 5. Route dispatch (trigger_ingest → tracker kwargs)
# ---------------------------------------------------------------------------


class TestTriggerIngestDispatch:
    def _install_spy_tracker(self, client: TestClient) -> list[dict]:
        calls: list[dict] = []

        class _SpyTracker:
            def is_running(self, slug: str) -> bool:  # noqa: ARG002
                return False

            def start_ingest(self, **kwargs):
                calls.append(kwargs)
                task = MagicMock()
                return task

        # TestClient exposes the app via .app — attach the spy where
        # _get_ingest_tracker looks for it.
        client.app.state.ingest_tracker = _SpyTracker()  # type: ignore[union-attr]
        return calls

    def test_textbook_dispatch_carries_stored_chunker(
        self, client: TestClient,
    ) -> None:
        calls = self._install_spy_tracker(client)
        r = client.post(
            "/ui/api/notebooks",
            json={
                "slug": "md-book",
                "notebook_kind": "textbook",
                "chunker": "markdown",
            },
        )
        assert r.status_code == 201
        # Junction row so the dispatch has a paper to ingest.
        store: NotebooksStore = client.app_store  # type: ignore[attr-defined]
        loop = client.app_loop  # type: ignore[attr-defined]
        loop.run_until_complete(store.add_paper(
            slug="md-book", paper_id="textbook:md-book",
            added_at="2026-07-04T00:00:00+00:00",
        ))
        r = client.post("/ui/api/notebooks/md-book/ingest")
        assert r.status_code == 202, r.text
        assert len(calls) == 1
        kw = calls[0]
        assert kw["notebook_kind"] == "textbook"
        assert kw["textbook_chunker"] == "markdown"
        assert kw["textbook_paper_ids"] == ["textbook:md-book"]

    def test_textbook_without_papers_422(self, client: TestClient) -> None:
        calls = self._install_spy_tracker(client)
        client.post(
            "/ui/api/notebooks",
            json={"slug": "empty-book", "notebook_kind": "textbook"},
        )
        r = client.post("/ui/api/notebooks/empty-book/ingest")
        assert r.status_code == 422
        assert "no uploaded papers" in r.json()["detail"]
        assert calls == []  # fail-fast: no run row consumed, no spawn

    def test_arxiv_dispatch_unchanged(self, client: TestClient) -> None:
        """arxiv-kind notebooks keep the historical kwargs (tracker
        defaults) — regression pin for the m9 contract."""
        calls = self._install_spy_tracker(client)
        client.post("/ui/api/notebooks", json={"slug": "papers-nb"})
        r = client.post("/ui/api/notebooks/papers-nb/ingest")
        assert r.status_code == 202
        assert len(calls) == 1
        kw = calls[0]
        assert "notebook_kind" not in kw  # dispatch dict empty for arxiv
        assert "textbook_chunker" not in kw
        assert kw["slug"] == "papers-nb"

    def test_upload_parse_uses_stored_chunker(
        self, client: TestClient, notebooks_base: Path,
    ) -> None:
        """The upload route hands the stored textbook_chunker to
        ParseTaskTracker.start_parse (the AC-A.18 'UI parse path')."""
        parse_calls: list[dict] = []

        class _SpyParseTracker:
            def is_running(self, slug: str) -> bool:  # noqa: ARG002
                return False

            def start_parse(self, **kwargs):
                parse_calls.append(kwargs)
                return MagicMock()

        client.app.state.parse_tracker = _SpyParseTracker()  # type: ignore[union-attr]
        r = client.post(
            "/ui/api/notebooks",
            json={
                "slug": "md-book",
                "notebook_kind": "textbook",
                "chunker": "markdown",
            },
        )
        assert r.status_code == 201
        # Minimal valid PDF bytes: %PDF- head + EOF marker (the m4
        # preflight's five vectors are exercised elsewhere; this body
        # passes them: no JS, no XFA, no embedded files, no polyglot).
        pdf = b"%PDF-1.4\n1 0 obj\n<< >>\nendobj\n%%EOF\n"
        r = client.post(
            "/ui/api/notebooks/md-book/papers/upload",
            data={"paper_id": "textbook:md-book"},
            files={"file": ("book.pdf", pdf, "application/pdf")},
        )
        assert r.status_code == 201, r.text
        assert len(parse_calls) == 1
        assert parse_calls[0]["chunker"] == "markdown"
        assert parse_calls[0]["slug"] == "md-book"


# ---------------------------------------------------------------------------
# 6. AC-A.18 fixture parity: server argv == CLI path, chunk-for-chunk
# ---------------------------------------------------------------------------


class TestChunkerApiCliParity:
    """The server does not reimplement the textbook ingest — it spawns
    the SAME CLI. This test pins that property end-to-end on a real
    MinerU-markdown fixture: the tracker-built argv, driven through the
    CLI's own argparse in dry-run, routes to the markdown chunker and
    yields records identical to the operator-run CLI invocation.
    """

    SLUG = "parity-book"
    PID = "textbook:parity-book"
    MD = (
        "# 1 Derived categories\n\n"
        "Intro prose about $D^b(X)$ and Fourier-Mukai transforms.\n\n"
        "## 1.1 Exact triangles\n\n"
        "Lemma 1.1. Every exact triangle induces a long exact sequence.\n\n"
        "Proof. Apply $\\mathrm{Hom}(A, -)$ and rotate. $\\square$\n"
    )

    def _seed_tree(self, tmp_path: Path, monkeypatch) -> None:
        """Build notebooks/<slug>/parsed/<flat>/_mineru/book/auto/book.md
        — the exact tree the server's parse step produces."""
        import ingest.textbook_markdown_chunker as md_mod

        nb_dir = tmp_path / "notebooks" / self.SLUG
        flat = self.PID.replace(":", "_")
        auto = nb_dir / "parsed" / flat / "_mineru" / "book" / "auto"
        auto.mkdir(parents=True)
        (auto / "book.md").write_text(self.MD, encoding="utf-8")
        monkeypatch.setattr(
            md_mod, "_resolve_notebook_dir", lambda slug: nb_dir,
        )

    def test_server_argv_parses_and_routes_to_markdown_chunker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import tools.notebook_textbook_ingest as nti

        self._seed_tree(tmp_path, monkeypatch)

        # --- CLI path: what the operator runs by hand (dry-run). -----
        cli_result = nti.ingest_textbook_paper(
            self.SLUG, self.PID, chunker="markdown", dry_run=True,
        )
        if cli_result["chunks"] == 0:
            raise AssertionError("fixture produced no chunks — bad seed")

        # --- Server path: tracker argv → the CLI's own argparse. -----
        tracker = IngestTaskTracker()
        argv = tracker._build_subprocess_args(
            self.SLUG, notebook_kind="textbook",
            textbook_chunker="markdown",
            textbook_paper_ids=[self.PID],
        )
        # Strip the interpreter dispatch ('-m tools.notebook_textbook_
        # ingest') and drive main() with the remaining argv exactly as
        # the subprocess would receive it (+ --dry-run so no embed).
        assert argv[:2] == ["-m", "tools.notebook_textbook_ingest"]
        rc = nti.main([*argv[2:], "--dry-run"])
        assert rc == 0

    def test_chunk_records_identical_across_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Chunk-for-chunk identity: both paths call
        chunk_textbook_markdown(slug, pid) on the same tree, so the
        produced ChunkRecords must be equal AND deterministic."""
        from ingest.textbook_markdown_chunker import chunk_textbook_markdown

        self._seed_tree(tmp_path, monkeypatch)

        # CLI-path records.
        records_cli = chunk_textbook_markdown(self.SLUG, self.PID)

        # Server-path records: replay the exact (slug, paper_id,
        # chunker) triple the dispatched CLI resolves from the
        # tracker argv.
        import tools.notebook_textbook_ingest as nti

        seen: list[tuple[str, str]] = []
        real = nti.chunk_textbook_markdown

        def _spy(slug: str, pid: str):
            seen.append((slug, pid))
            return real(slug, pid)

        monkeypatch.setattr(nti, "chunk_textbook_markdown", _spy)
        result = nti.ingest_textbook_paper(
            self.SLUG, self.PID, chunker="markdown", dry_run=True,
        )
        assert seen == [(self.SLUG, self.PID)]
        assert result["chunks"] == len(records_cli)

        # Deterministic re-chunk: identical chunk_ids + bodies.
        records_again = chunk_textbook_markdown(self.SLUG, self.PID)
        assert [c.chunk_id for c in records_again] == [
            c.chunk_id for c in records_cli
        ]
        assert [c.body_text for c in records_again] == [
            c.body_text for c in records_cli
        ]
        # The records carry the markdown chunker's identity stamps —
        # retrieval consumers can tell which path produced them.
        assert all(c.parser_used == "mineru+markdown" for c in records_cli)
