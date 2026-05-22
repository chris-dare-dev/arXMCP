"""Tests for the m9 ingest trigger + status polling endpoints.

Coverage matrix:

- TestIngestTrigger          — AC #1 happy path; row created + tracker spawned
- TestPerNotebookCollision   — AC #3 (409 on second concurrent POST)
- TestPathRedaction          — AC #2 + FM-4 (absolute path stripped to var/arxmcp/)
- TestStderrHtmlEscape       — FM-3 (<retrieved_chunk> escape at storage)
- TestLatestEndpoint         — polling endpoint: running/success/failed/none
- TestHttp286OnTerminal      — HTTP 286 polling-stop signal (htmx canonical)
- TestSchemaMigration        — additive v1→v2 preserves notebooks rows (FM data-loss)
- TestOrphanRecovery         — FM-5: orphaned `running` rows marked failed at startup
- TestIngestTrackerUnit      — direct unit tests of IngestTaskTracker

The subprocess invocation is monkey-patched in most tests so the
tests don't actually spawn `tools/notebook_ingest.py` (which
would re-load BGE-M3). The path-redaction + html-escape pipeline
is exercised against synthetic stderr bytes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.ingest_tracker import (
    STDERR_TAIL_MAX_BYTES,
    IngestTaskTracker,
    prepare_stderr_tail,
    redact_paths,
)
from server.notebooks_store import NotebooksStore
from server.routes import notebooks as notebooks_module
from server.routes.notebooks import router as notebooks_router
from tools import _notebook_common


@pytest.fixture
def notebooks_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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
    """Minimal FastAPI app with notebooks_store + ingest_tracker."""
    db_path = tmp_path / "notebooks.db"
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        app.state.ingest_tracker = IngestTaskTracker()
        app.include_router(notebooks_router, prefix="/ui/api")
        monkeypatch.setattr(
            notebooks_module, "_now_iso",
            lambda: "2026-05-22T17:00:00+00:00",
        )
        with TestClient(app) as c:
            yield c
        loop.run_until_complete(store.close())
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# AC #1 — Ingest trigger happy path
# ---------------------------------------------------------------------------


class TestIngestTrigger:
    def test_trigger_returns_202_with_html_fragment(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Stub the subprocess spawn so the test doesn't actually run BGE-M3.
        async def _fake_spawn(*args, **kwargs):
            class _FakeProc:
                returncode = 0
                async def communicate(self):
                    return b"", b""
            return _FakeProc()
        monkeypatch.setattr(
            "server.ingest_tracker.asyncio.create_subprocess_exec",
            _fake_spawn,
        )
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.post("/ui/api/notebooks/demo-nb/ingest")
        assert r.status_code == 202, r.text
        assert "text/html" in r.headers["content-type"]
        body = r.text
        assert 'id="ingest-status"' in body
        assert 'data-status="running"' in body
        assert "Run #" in body

    def test_trigger_inserts_row_before_returning(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """FM-7: the DB row must exist before the response returns,
        otherwise the first poll fires before the row commits and
        sees `none` instead of `running`."""
        # Stub subprocess to hang forever so the row stays `running`.
        async def _fake_spawn(*args, **kwargs):
            class _FakeProc:
                returncode = 0
                async def communicate(self):
                    await asyncio.sleep(1000)
                    return b"", b""
            return _FakeProc()
        monkeypatch.setattr(
            "server.ingest_tracker.asyncio.create_subprocess_exec",
            _fake_spawn,
        )
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.post("/ui/api/notebooks/demo-nb/ingest")
        assert r.status_code == 202
        # IMMEDIATELY poll — the row MUST exist.
        r2 = client.get("/ui/api/notebooks/demo-nb/ingest/latest")
        assert r2.status_code == 200  # running, not 286
        assert 'data-status="running"' in r2.text

    def test_trigger_404_on_missing_notebook(
        self, client: TestClient,
    ) -> None:
        r = client.post("/ui/api/notebooks/nope/ingest")
        assert r.status_code == 404

    def test_trigger_422_on_malformed_slug(self, client: TestClient) -> None:
        r = client.post("/ui/api/notebooks/UPPER/ingest")
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# AC #3 — 409 on per-notebook collision
# ---------------------------------------------------------------------------


class TestPerNotebookCollision:
    def test_second_concurrent_post_returns_409(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Subprocess hangs so the first ingest stays in flight.
        async def _fake_spawn(*args, **kwargs):
            class _FakeProc:
                returncode = 0
                async def communicate(self):
                    await asyncio.sleep(1000)
                    return b"", b""
            return _FakeProc()
        monkeypatch.setattr(
            "server.ingest_tracker.asyncio.create_subprocess_exec",
            _fake_spawn,
        )
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r1 = client.post("/ui/api/notebooks/demo-nb/ingest")
        assert r1.status_code == 202
        r2 = client.post("/ui/api/notebooks/demo-nb/ingest")
        assert r2.status_code == 409
        assert "already in flight" in r2.text


# ---------------------------------------------------------------------------
# AC #2 — Path redaction (FM-4)
# ---------------------------------------------------------------------------


class TestPathRedaction:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (
                b"/Users/chris.dare/Personal/SourceCode/arXMCP/var/arxmcp/foo",
                b"var/arxmcp/foo",
            ),
            (
                b"/home/dev/repo/var/arxmcp/notebooks/foo/ops/log",
                b"var/arxmcp/notebooks/foo/ops/log",
            ),
            (
                b"prefix /Users/chris.dare/x/var/arxmcp/y suffix",
                b"prefix var/arxmcp/y suffix",
            ),
            (
                b"already relative: var/arxmcp/foo",
                b"already relative: var/arxmcp/foo",
            ),
            (
                b"no var prefix at all",
                b"no var prefix at all",
            ),
            # m9 rect F4: macOS usernames can contain spaces (the
            # default "First Last" full-name account). Without the
            # space in the redaction regex character class, the
            # absolute path would leak past var/arxmcp/.
            (
                b"/Users/Joe Smith/Personal/SourceCode/arXMCP/var/arxmcp/foo",
                b"var/arxmcp/foo",
            ),
            (
                b"/Users/Mary Anne Jones/repo/var/arxmcp/notebooks/x",
                b"var/arxmcp/notebooks/x",
            ),
        ],
    )
    def test_redact_paths(self, raw: bytes, expected: bytes) -> None:
        assert redact_paths(raw) == expected

    def test_prepare_stderr_tail_pipeline(self) -> None:
        """End-to-end: truncate → redact → decode → html-escape."""
        long = b"x" * 2000 + b"/Users/chris.dare/x/var/arxmcp/y <evil>"
        out = prepare_stderr_tail(long)
        # Truncated to STDERR_TAIL_MAX_BYTES (1024) — the trailing
        # var/arxmcp/y <evil> must survive (it's the tail).
        assert "var/arxmcp/y" in out
        assert "/Users/" not in out
        # HTML-escaped (Threat 2 — FM-3).
        assert "&lt;evil&gt;" in out
        assert "<evil>" not in out
        assert len(out) <= STDERR_TAIL_MAX_BYTES + 256  # html escape may expand


# ---------------------------------------------------------------------------
# FM-3 — Stderr HTML escape (Threat 2 prompt-injection defense)
# ---------------------------------------------------------------------------


class TestStderrHtmlEscape:
    def test_retrieved_chunk_literal_in_stderr_is_escaped(self) -> None:
        """If a parser-failure log contains <retrieved_chunk> literal,
        the text must be escaped before storage to defend against
        delimiter-spoofing (Threat 2 / m9 FM-3)."""
        stderr = b"parser failed: <retrieved_chunk>malicious</retrieved_chunk>"
        out = prepare_stderr_tail(stderr)
        assert "&lt;retrieved_chunk&gt;" in out
        assert "<retrieved_chunk>" not in out


# ---------------------------------------------------------------------------
# Polling endpoint behavior
# ---------------------------------------------------------------------------


class TestLatestEndpoint:
    def test_latest_returns_none_when_no_runs(
        self, client: TestClient,
    ) -> None:
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        r = client.get("/ui/api/notebooks/demo-nb/ingest/latest")
        assert r.status_code == 200
        body = r.text
        assert 'data-status="none"' in body
        # No runs yet — polling should continue (hx-trigger present).
        assert 'hx-trigger="every 2s"' in body

    def test_latest_404_on_missing_notebook(
        self, client: TestClient,
    ) -> None:
        r = client.get("/ui/api/notebooks/nope/ingest/latest")
        assert r.status_code == 404


class TestHttp286OnTerminal:
    """m9 synthesis D2: HTTP 286 is the htmx-canonical polling-stop
    signal. The latest endpoint MUST return 286 on `success` /
    `failed`, 200 on `running` / `none`."""

    def test_286_on_success(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Subprocess succeeds immediately.
        async def _fake_spawn(*args, **kwargs):
            class _FakeProc:
                returncode = 0
                async def communicate(self):
                    return b"", b""
            return _FakeProc()
        monkeypatch.setattr(
            "server.ingest_tracker.asyncio.create_subprocess_exec",
            _fake_spawn,
        )
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        client.post("/ui/api/notebooks/demo-nb/ingest")
        # Wait for the background task to finish + write the row.
        # (TestClient's lifespan owns the event loop; the task
        # completes on the next request boundary.)
        for _ in range(20):
            r = client.get("/ui/api/notebooks/demo-nb/ingest/latest")
            if r.status_code == 286:
                break
        assert r.status_code == 286, (
            f"expected 286 on terminal success; got {r.status_code}: {r.text}"
        )
        assert 'data-status="success"' in r.text
        # Terminal-state fragment MUST NOT carry hx-trigger.
        assert "hx-trigger" not in r.text

    def test_286_on_failure(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def _fake_spawn(*args, **kwargs):
            class _FakeProc:
                returncode = 1
                async def communicate(self):
                    return b"", b"FATAL: simulated /Users/test/x/var/arxmcp/oops"
            return _FakeProc()
        monkeypatch.setattr(
            "server.ingest_tracker.asyncio.create_subprocess_exec",
            _fake_spawn,
        )
        client.post("/ui/api/notebooks", json={"slug": "demo-nb"})
        client.post("/ui/api/notebooks/demo-nb/ingest")
        for _ in range(20):
            r = client.get("/ui/api/notebooks/demo-nb/ingest/latest")
            if r.status_code == 286:
                break
        assert r.status_code == 286, r.text
        body = r.text
        assert 'data-status="failed"' in body
        # FM-4: absolute path stripped down to var/arxmcp/.
        assert "var/arxmcp/oops" in body
        assert "/Users/" not in body
        # Terminal-state fragment MUST NOT carry hx-trigger.
        assert "hx-trigger" not in body


# ---------------------------------------------------------------------------
# Schema migration — additive (no data loss on v1→v2)
# ---------------------------------------------------------------------------


class TestSchemaMigration:
    def test_v1_to_v2_preserves_notebooks_rows(
        self, tmp_path: Path,
    ) -> None:
        """Critical: the v1→v2 migration must NOT drop existing
        notebooks rows. The original Tier1Store-style DROP-AND-
        RECREATE pattern was data-loss on bump; m9 ships an
        additive migration."""
        db_path = tmp_path / "notebooks.db"

        async def _run() -> dict:
            # First open: creates at v1 (we manually set version).
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            conn.execute("PRAGMA user_version = 0")
            conn.close()

            store = await NotebooksStore.open(db_path)
            await store.create_notebook(
                slug="preserve-me",
                display_name="Survive the migration",
                lancedb_path="/tmp/x",
                created_at="2026-05-22T00:00:00+00:00",
            )
            await store.add_paper(
                slug="preserve-me",
                paper_id="2604.26204",
                added_at="2026-05-22T00:00:01+00:00",
            )
            await store.close()

            # Re-open — migration to v2 should run (additive).
            store2 = await NotebooksStore.open(db_path)
            notebooks = await store2.list_notebooks()
            papers = await store2.list_papers("preserve-me")
            await store2.close()
            return {"notebooks": notebooks, "papers": papers}

        result = asyncio.run(_run())
        assert len(result["notebooks"]) == 1
        assert result["notebooks"][0]["slug"] == "preserve-me"
        assert len(result["papers"]) == 1, (
            "v1->v2 migration must be additive — notebook_papers row "
            "must survive the SCHEMA_VERSION bump"
        )

    def test_ingest_runs_table_created(self, tmp_path: Path) -> None:
        """The v1→v2 migration must create the notebook_ingest_runs
        table — otherwise the m9 insert_ingest_run will fail."""
        db_path = tmp_path / "notebooks.db"

        async def _run() -> bool:
            store = await NotebooksStore.open(db_path)
            await store.create_notebook(
                slug="demo-nb", display_name="",
                lancedb_path="/tmp/x",
                created_at="2026-05-22T00:00:00+00:00",
            )
            run_id = await store.insert_ingest_run(
                "demo-nb", "2026-05-22T17:00:00+00:00",
            )
            assert run_id >= 1
            row = await store.get_latest_ingest_run("demo-nb")
            await store.close()
            return row is not None and row["status"] == "running"

        assert asyncio.run(_run()) is True


# ---------------------------------------------------------------------------
# FM-5 — Orphan recovery at startup
# ---------------------------------------------------------------------------


class TestOrphanRecovery:
    def test_mark_orphaned_runs_failed(self, tmp_path: Path) -> None:
        db_path = tmp_path / "notebooks.db"

        async def _run() -> dict:
            store = await NotebooksStore.open(db_path)
            await store.create_notebook(
                slug="demo-nb", display_name="",
                lancedb_path="/tmp/x",
                created_at="2026-05-22T00:00:00+00:00",
            )
            # Old `running` row (started before the cutoff).
            await store.insert_ingest_run(
                "demo-nb", "2026-05-21T00:00:00+00:00",  # day ago
            )
            # Fresh `running` row (started after the cutoff — must NOT be touched).
            await store.create_notebook(
                slug="other-nb", display_name="",
                lancedb_path="/tmp/y",
                created_at="2026-05-22T00:00:00+00:00",
            )
            await store.insert_ingest_run(
                "other-nb", "2026-05-22T17:55:00+00:00",  # 5 min ago
            )

            n_recovered = await store.mark_orphaned_runs_failed(
                cutoff_iso="2026-05-22T17:00:00+00:00",
                message="server restarted mid-ingest",
            )
            old_row = await store.get_latest_ingest_run("demo-nb")
            fresh_row = await store.get_latest_ingest_run("other-nb")
            await store.close()
            return {
                "n_recovered": n_recovered,
                "old_row": old_row, "fresh_row": fresh_row,
            }

        out = asyncio.run(_run())
        assert out["n_recovered"] == 1
        assert out["old_row"]["status"] == "failed"
        assert out["old_row"]["exit_code"] == -1
        assert "restarted" in out["old_row"]["stderr_tail"]
        # The fresh row must NOT have been touched.
        assert out["fresh_row"]["status"] == "running"


# ---------------------------------------------------------------------------
# Direct unit tests of the tracker
# ---------------------------------------------------------------------------


class TestIngestTrackerUnit:
    def test_is_running_false_on_empty(self) -> None:
        tracker = IngestTaskTracker()
        assert tracker.is_running("any-slug") is False

    def test_is_running_true_after_start(self, tmp_path: Path) -> None:
        async def _run() -> bool:
            db_path = tmp_path / "notebooks.db"
            store = await NotebooksStore.open(db_path)
            tracker = IngestTaskTracker()
            await store.create_notebook(
                slug="demo-nb", display_name="",
                lancedb_path="/tmp/x",
                created_at="2026-05-22T00:00:00+00:00",
            )
            run_id = await store.insert_ingest_run(
                "demo-nb", "2026-05-22T17:00:00+00:00",
            )
            # Spawn — but stub create_subprocess_exec to hang.
            import server.ingest_tracker as it_mod

            async def _fake_spawn(*args, **kwargs):
                class _FakeProc:
                    returncode = 0
                    async def communicate(self):
                        await asyncio.sleep(1000)
                        return b"", b""
                return _FakeProc()
            it_mod.asyncio.create_subprocess_exec = _fake_spawn  # type: ignore[attr-defined]

            task = tracker.start_ingest(
                slug="demo-nb", run_id=run_id, store=store,
                now_iso_provider=lambda: "2026-05-22T17:00:00+00:00",
            )
            await asyncio.sleep(0)  # let the task start
            is_running = tracker.is_running("demo-nb")
            task.cancel()
            import contextlib as _ctx
            with _ctx.suppress(asyncio.CancelledError, BaseException):
                await task
            await store.close()
            return is_running

        assert asyncio.run(_run()) is True

    def test_shutdown_cancels_running_tasks(self, tmp_path: Path) -> None:
        async def _run() -> bool:
            db_path = tmp_path / "notebooks.db"
            store = await NotebooksStore.open(db_path)
            tracker = IngestTaskTracker()
            await store.create_notebook(
                slug="demo-nb", display_name="",
                lancedb_path="/tmp/x",
                created_at="2026-05-22T00:00:00+00:00",
            )
            run_id = await store.insert_ingest_run(
                "demo-nb", "2026-05-22T17:00:00+00:00",
            )
            import server.ingest_tracker as it_mod

            async def _fake_spawn(*args, **kwargs):
                class _FakeProc:
                    returncode = 0
                    async def communicate(self):
                        await asyncio.sleep(1000)
                        return b"", b""
                    def terminate(self):
                        pass
                    def kill(self):
                        pass
                    async def wait(self):
                        return 0
                return _FakeProc()
            it_mod.asyncio.create_subprocess_exec = _fake_spawn  # type: ignore[attr-defined]

            tracker.start_ingest(
                slug="demo-nb", run_id=run_id, store=store,
                now_iso_provider=lambda: "2026-05-22T17:00:00+00:00",
            )
            await asyncio.sleep(0)
            await tracker.shutdown(timeout_seconds=1.0)
            cancelled = not tracker.is_running("demo-nb")
            await store.close()
            return cancelled

        assert asyncio.run(_run()) is True


# ---------------------------------------------------------------------------
# m9 rect F1 — CancelledError writes terminal-state row + terminates proc
# ---------------------------------------------------------------------------


class TestCancelPathWritesFailedRow:
    """m9 rect F1: ``CancelledError`` is ``BaseException`` (not
    ``Exception``) in Python 3.8+. The cancel-path must EXPLICITLY
    catch it, terminate the subprocess, and write a terminal-state
    DB row — otherwise daemon shutdown pins the row to ``running``
    forever (well, until the FM-5 orphan-recovery 5 minutes later).

    These tests pin the F1 invariants:
      1. cancel triggers proc.terminate()
      2. cancel writes a `failed` row with exit_code=-2 + the
         "cancelled at daemon shutdown" message
      3. cancel re-raises CancelledError so the shutdown
         gathering sees the cancellation
    """

    def test_cancel_writes_failed_row_with_exit_code_minus_2(
        self, tmp_path: Path,
    ) -> None:
        terminate_calls = {"n": 0}

        async def _run() -> dict:
            db_path = tmp_path / "notebooks.db"
            store = await NotebooksStore.open(db_path)
            tracker = IngestTaskTracker()
            await store.create_notebook(
                slug="demo-nb", display_name="",
                lancedb_path="/tmp/x",
                created_at="2026-05-22T00:00:00+00:00",
            )
            run_id = await store.insert_ingest_run(
                "demo-nb", "2026-05-22T17:00:00+00:00",
            )
            import server.ingest_tracker as it_mod

            async def _fake_spawn(*args, **kwargs):
                class _FakeProc:
                    returncode = 0
                    async def communicate(self):
                        # Block until cancelled.
                        await asyncio.sleep(1000)
                        return b"", b""
                    def terminate(self):
                        terminate_calls["n"] += 1
                    def kill(self):
                        pass
                    async def wait(self):
                        # Simulate subprocess responding to SIGTERM
                        # quickly so the F1 wait_for doesn't timeout.
                        return 0
                return _FakeProc()
            it_mod.asyncio.create_subprocess_exec = _fake_spawn  # type: ignore[attr-defined]

            tracker.start_ingest(
                slug="demo-nb", run_id=run_id, store=store,
                now_iso_provider=lambda: "2026-05-22T17:30:00+00:00",
            )
            # Let the task reach `await proc.communicate()`.
            await asyncio.sleep(0)
            await tracker.shutdown(timeout_seconds=1.0)
            row = await store.get_latest_ingest_run("demo-nb")
            await store.close()
            return {
                "row": row,
                "terminate_calls": terminate_calls["n"],
            }

        out = asyncio.run(_run())
        assert out["row"] is not None
        assert out["row"]["status"] == "failed", (
            "F1 regression: CancelledError must write a failed row "
            "(was running). Without F1, the row stayed `running` "
            "forever after cancel."
        )
        assert out["row"]["exit_code"] == -2, (
            "exit_code=-2 distinguishes cancel from spawn-fail (-1)"
        )
        assert "cancelled" in (out["row"]["stderr_tail"] or "").lower()
        assert out["terminate_calls"] >= 1, (
            "F1 regression: cancel-path must call proc.terminate() "
            "to send SIGTERM to the subprocess"
        )


# ---------------------------------------------------------------------------
# m9 rect F3 — mark_orphaned_runs_failed escapes the message
# ---------------------------------------------------------------------------


class TestOrphanRecoveryEscapesMessage:
    """m9 rect F3: the ``message`` argument to
    ``mark_orphaned_runs_failed`` is stored on ``stderr_tail`` which
    interpolates raw into a ``<pre>`` element. The store must HTML-
    escape the message at storage time so the storage layer is the
    single source of truth for "stderr_tail is safe HTML"."""

    def test_message_with_html_metacharacters_escaped(
        self, tmp_path: Path,
    ) -> None:
        async def _run() -> str | None:
            db_path = tmp_path / "notebooks.db"
            store = await NotebooksStore.open(db_path)
            await store.create_notebook(
                slug="demo-nb", display_name="",
                lancedb_path="/tmp/x",
                created_at="2026-05-22T00:00:00+00:00",
            )
            await store.insert_ingest_run(
                "demo-nb", "2026-05-21T00:00:00+00:00",  # before cutoff
            )
            await store.mark_orphaned_runs_failed(
                cutoff_iso="2026-05-22T00:00:00+00:00",
                message="<script>alert(1)</script>",
            )
            row = await store.get_latest_ingest_run("demo-nb")
            await store.close()
            return row["stderr_tail"] if row else None

        tail = asyncio.run(_run())
        assert tail is not None
        # The raw script tag MUST NOT appear in storage.
        assert "<script>" not in tail
        # The escaped form MUST appear (proves the value reached
        # storage, just safely).
        assert "&lt;script&gt;" in tail
