"""Tests for the bulk-ingest orchestrator (E11_S01).

Pure orchestrator logic — paper-id file parsing, CLI flag
handling, parser-failures JSONL writing, progress logging,
dry-run output. Mocks `ingest_one_paper` (and its embedder /
chunker / LanceDB-writer dependencies) so the suite runs
without LaTeXML / BGE-M3 / LanceDB.

The sanity test ("≥100K chunks in staging LanceDB") lives at
`tests/test_bulk_ingest_sanity.py` and is marked
`requires_full_corpus`; it skips by default and runs only after
the operator has executed the full ingest. The single-paper
end-to-end smoke test is deferred to that operator workflow.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from arxmcp.ingest.bulk_ingest import (
    PaperOutcome,
    _log_parser_failure,
    _log_progress,
    _read_paper_ids,
    ingest_one_paper,
    run_bulk_ingest,
)


@pytest.fixture(autouse=True)
def derived_builds(monkeypatch) -> list:
    """Record index builds: the outcomes here are mocks with no dataset."""
    calls: list = []
    monkeypatch.setattr(
        "arxmcp.ingest.bulk_ingest.build_derived_indexes", lambda path: calls.append(path)
    )
    return calls


@pytest.fixture(autouse=True)
def _default_staging_in_tmp(tmp_path, monkeypatch):
    """``run_bulk_ingest`` inspects its write target before
    the first write. Most tests here omit ``lancedb_staging_path``, whose
    default is the real ``var/`` staging dataset; point the default into
    ``tmp_path`` so no test reads it."""
    import arxmcp.ingest.bulk_ingest as bulk

    defaults = dict(bulk.run_bulk_ingest.__kwdefaults__)
    defaults["lancedb_staging_path"] = tmp_path / "default-lancedb-staging"
    monkeypatch.setattr(bulk.run_bulk_ingest, "__kwdefaults__", defaults)

# ---------------------------------------------------------------------------
# _read_paper_ids
# ---------------------------------------------------------------------------


class TestReadPaperIds:
    def test_reads_one_per_line(self, tmp_path):
        path = tmp_path / "ids.txt"
        path.write_text("2401.00001\n2401.00002\n", encoding="utf-8")
        assert _read_paper_ids(path) == ["2401.00001", "2401.00002"]

    def test_skips_blanks_and_comments(self, tmp_path):
        path = tmp_path / "ids.txt"
        path.write_text(
            "# heading\n2401.00001\n\n# more\n2401.00002\n",
            encoding="utf-8",
        )
        assert _read_paper_ids(path) == ["2401.00001", "2401.00002"]

    def test_raises_on_malformed_id(self, tmp_path):
        path = tmp_path / "ids.txt"
        path.write_text("2401.00001\nnot-an-id\n", encoding="utf-8")
        with pytest.raises(ValueError, match="invalid paper_id"):
            _read_paper_ids(path)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="paper-ids-file"):
            _read_paper_ids(tmp_path / "missing.txt")


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------


class TestLogParserFailure:
    def test_writes_jsonl_line(self, tmp_path):
        path = tmp_path / "ops" / "parser-failures" / "bulk.jsonl"
        outcome = PaperOutcome(
            paper_id="2401.00001",
            parsers_tried=["ar5iv", "latexml"],
            failure_reason="no_parsed_html",
        )
        _log_parser_failure(outcome, path)
        rec = json.loads(path.read_text().strip())
        assert rec["paper_id"] == "2401.00001"
        assert rec["parsers_tried"] == ["ar5iv", "latexml"]
        assert rec["failure_reason"] == "no_parsed_html"
        assert "timestamp" in rec

    def test_appends_multiple_records(self, tmp_path):
        path = tmp_path / "bulk.jsonl"
        for i in range(3):
            _log_parser_failure(
                PaperOutcome(
                    paper_id=f"2401.0000{i}",
                    parsers_tried=["ar5iv"],
                    failure_reason="x",
                ),
                path,
            )
        lines = path.read_text().splitlines()
        assert len(lines) == 3


class TestLogProgress:
    def test_writes_progress_line(self, tmp_path):
        from arxmcp.ingest.bulk_ingest import IngestSummary

        path = tmp_path / "ingestion.log"
        summary = IngestSummary(
            papers_total=10,
            papers_succeeded=8,
            papers_failed=2,
            ar5iv_hits=7,
            ar5iv_misses=1,
        )
        _log_progress(path, summary, paper_id="2401.00010")
        text = path.read_text()
        assert "paper=2401.00010" in text
        assert "ok=8" in text
        assert "fail=2" in text
        assert "ar5iv_hits=7" in text


# ---------------------------------------------------------------------------
# run_bulk_ingest with mocked ingest_one_paper
# ---------------------------------------------------------------------------


def _ok_outcome(paper_id: str, parser: str = "ar5iv") -> PaperOutcome:
    return PaperOutcome(
        paper_id=paper_id,
        parsers_tried=[parser],
        parser_used=parser,
        chunks_written=10,
        elapsed_seconds=0.1,
    )


def _fail_outcome(paper_id: str) -> PaperOutcome:
    return PaperOutcome(
        paper_id=paper_id,
        parsers_tried=["ar5iv", "latexml"],
        parser_used=None,
        chunks_written=0,
        elapsed_seconds=0.1,
        failure_reason="no_parsed_html",
    )


class TestRunBulkIngest:
    def test_all_papers_succeed(self, tmp_path):
        failures = tmp_path / "bulk.jsonl"
        log = tmp_path / "ingestion.log"
        paper_ids = ["2401.00001", "2401.00002", "2401.00003"]

        with patch(
            "arxmcp.ingest.bulk_ingest.ingest_one_paper",
            side_effect=[_ok_outcome(p) for p in paper_ids],
        ):
            summary = run_bulk_ingest(
                paper_ids,
                failures_path=failures,
                log_path=log,
                progress_interval=1,
            )

        assert summary.papers_total == 3
        assert summary.papers_succeeded == 3
        assert summary.papers_failed == 0
        assert summary.ar5iv_hits == 3
        assert summary.ar5iv_misses == 0
        assert summary.ar5iv_hit_rate == 1.0
        assert not failures.exists()  # no failures, no JSONL line

    def test_builds_the_indexes_into_the_dataset_it_wrote(
        self, tmp_path, derived_builds
    ):
        staging = tmp_path / "staging"
        with patch(
            "arxmcp.ingest.bulk_ingest.ingest_one_paper",
            side_effect=[_fail_outcome("2401.00001"), _ok_outcome("2401.00002")],
        ):
            run_bulk_ingest(
                ["2401.00001", "2401.00002"], lancedb_staging_path=staging,
                failures_path=tmp_path / "f.jsonl", log_path=tmp_path / "log",
                ops_dir=tmp_path,
            )
        assert derived_builds == [staging]

    def test_builds_nothing_when_no_paper_landed(self, tmp_path, derived_builds):
        with patch(
            "arxmcp.ingest.bulk_ingest.ingest_one_paper",
            side_effect=[_fail_outcome("2401.00001")],
        ):
            run_bulk_ingest(
                ["2401.00001"], lancedb_staging_path=tmp_path / "staging",
                failures_path=tmp_path / "f.jsonl", log_path=tmp_path / "log",
                ops_dir=tmp_path,
            )
        assert derived_builds == []

    def test_writes_ingest_summary_sentinel(self, tmp_path):
        """corpus-integrity-observability-e3 F3: run_bulk_ingest writes the
        ingest-summary.json sentinel at end-of-run (AC2). The driver WIRING was
        untested behind a best-effort try/except — a broken call would be
        silently swallowed."""
        import json as _json

        paper_ids = ["2401.00001", "2401.00002"]
        with patch(
            "arxmcp.ingest.bulk_ingest.ingest_one_paper",
            side_effect=[_ok_outcome(p) for p in paper_ids],
        ):
            run_bulk_ingest(
                paper_ids,
                failures_path=tmp_path / "bulk.jsonl",
                log_path=tmp_path / "ingestion.log",
                ops_dir=tmp_path,
                progress_interval=10,
            )
        sentinel = tmp_path / "ingest-summary.json"
        assert sentinel.is_file()
        payload = _json.loads(sentinel.read_text(encoding="utf-8"))
        assert payload["schema_version"] == 1
        assert payload["driver"] == "bulk_ingest"
        assert payload["papers_processed"] == 2
        assert payload["papers_succeeded"] == 2
        assert payload["papers_failed"] == 0

    def test_dry_run_does_not_write_ingest_summary(self, tmp_path):
        """The dry-run path returns before the sentinel write — a no-op run
        leaves no observability artifact."""
        run_bulk_ingest(
            ["2401.00001"],
            failures_path=tmp_path / "bulk.jsonl",
            log_path=tmp_path / "ingestion.log",
            ops_dir=tmp_path,
            progress_interval=10,
            dry_run=True,
        )
        assert not (tmp_path / "ingest-summary.json").is_file()

    def test_mixed_success_and_failure(self, tmp_path):
        failures = tmp_path / "bulk.jsonl"
        log = tmp_path / "ingestion.log"
        outcomes = [
            _ok_outcome("2401.00001"),
            _fail_outcome("2401.00002"),
            _ok_outcome("2401.00003"),
        ]
        with patch(
            "arxmcp.ingest.bulk_ingest.ingest_one_paper",
            side_effect=outcomes,
        ):
            summary = run_bulk_ingest(
                ["2401.00001", "2401.00002", "2401.00003"],
                failures_path=failures,
                log_path=log,
                progress_interval=10,
            )
        assert summary.papers_total == 3
        assert summary.papers_succeeded == 2
        assert summary.papers_failed == 1
        # Only the failed paper writes to the JSONL.
        lines = failures.read_text().splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["paper_id"] == "2401.00002"

    def test_limit_caps_papers_processed(self, tmp_path):
        failures = tmp_path / "bulk.jsonl"
        log = tmp_path / "ingestion.log"
        paper_ids = ["2401.00001", "2401.00002", "2401.00003"]
        call_count = 0

        def _mock(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return _ok_outcome(args[0])

        with patch("arxmcp.ingest.bulk_ingest.ingest_one_paper", side_effect=_mock):
            summary = run_bulk_ingest(
                paper_ids,
                failures_path=failures,
                log_path=log,
                limit=2,
            )
        assert summary.papers_total == 2
        assert call_count == 2

    def test_ar5iv_hit_rate_tracks_correctly(self, tmp_path):
        failures = tmp_path / "bulk.jsonl"
        log = tmp_path / "ingestion.log"
        # Mix: 2 ar5iv hits + 1 latexml fallback. ar5iv hit rate = 2/3.
        outcomes = [
            _ok_outcome("2401.00001", parser="ar5iv"),
            PaperOutcome(
                paper_id="2401.00002",
                parsers_tried=["ar5iv", "latexml"],
                parser_used="latexml",
                chunks_written=5,
                elapsed_seconds=0.1,
            ),
            _ok_outcome("2401.00003", parser="ar5iv"),
        ]
        with patch(
            "arxmcp.ingest.bulk_ingest.ingest_one_paper",
            side_effect=outcomes,
        ):
            summary = run_bulk_ingest(
                ["2401.00001", "2401.00002", "2401.00003"],
                failures_path=failures,
                log_path=log,
                progress_interval=10,
            )
        assert summary.ar5iv_hits == 2
        assert summary.ar5iv_misses == 1
        assert summary.ar5iv_hit_rate == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# dry-run
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_does_not_call_ingest_one_paper(self, tmp_path, capsys):
        failures = tmp_path / "bulk.jsonl"
        log = tmp_path / "ingestion.log"
        # Stage one paper as having an ar5iv local cache.
        parsed_dir = tmp_path / "parsed"
        (parsed_dir / "2401.00001").mkdir(parents=True)
        (parsed_dir / "2401.00001" / "index.html").write_text("<html/>")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "2401.00001.html").write_text("<html/>")

        with patch(
            "arxmcp.ingest.bulk_ingest.ingest_one_paper",
            side_effect=AssertionError("dry-run must not call this"),
        ):
            summary = run_bulk_ingest(
                ["2401.00001", "2401.00002"],
                ar5iv_cache_dir=cache_dir,
                parsed_dir=parsed_dir,
                failures_path=failures,
                log_path=log,
                dry_run=True,
            )
        out, _err = capsys.readouterr()
        assert "ar5iv_local_cache" in out
        assert summary.papers_skipped == 2


# ---------------------------------------------------------------------------
# ingest_one_paper — skip-and-log path (no ar5iv hit, no parsed HTML)
# ---------------------------------------------------------------------------


class TestIngestOnePaperFailurePath:
    def test_returns_no_parsed_html_when_both_paths_miss(self, tmp_path):
        """Per synthesis D2: bulk_ingest does NOT fetch raw .tex or
        invoke LaTeXML itself. If ar5iv misses AND no local
        parsed HTML exists, the outcome is skip-and-log.
        """
        cache_dir = tmp_path / "cache"
        parsed_dir = tmp_path / "parsed"
        # ar5iv stubbed to return a miss.
        with patch(
            "arxmcp.ingest.bulk_ingest.try_cache",
            return_value=__import__(
                "arxmcp.ingest.ar5iv_fetch", fromlist=["Ar5ivResult"]
            ).Ar5ivResult(
                paper_id="2401.00001",
                hit=False,
                cache_path=None,
                parsed_path=None,
                reason="http_404",
            ),
        ):
            outcome = ingest_one_paper(
                "2401.00001",
                lancedb_staging_path=tmp_path / "lancedb-staging",
                ar5iv_cache_dir=cache_dir,
                parsed_dir=parsed_dir,
            )
        assert outcome.parser_used is None
        assert outcome.failure_reason == "no_parsed_html:ar5iv_http_404"
        assert outcome.retriable is False
        assert "ar5iv" in outcome.parsers_tried
        assert "latexml" in outcome.parsers_tried

    def test_skipping_ar5iv_records_the_plain_reason(self, tmp_path):
        outcome = ingest_one_paper(
            "2401.00001",
            lancedb_staging_path=tmp_path / "lancedb-staging",
            ar5iv_cache_dir=tmp_path / "cache",
            parsed_dir=tmp_path / "parsed",
            skip_ar5iv=True,
        )
        assert outcome.failure_reason == "no_parsed_html"
        assert outcome.retriable is False

    def test_a_rate_limited_miss_is_logged_as_retriable(self, tmp_path):
        from arxmcp.ingest.ar5iv_fetch import Ar5ivResult

        rate_limited = Ar5ivResult(
            paper_id="2401.00001", hit=False, cache_path=None,
            parsed_path=None, reason="http_429", retriable=True,
        )
        failures = tmp_path / "failures.jsonl"
        with patch("arxmcp.ingest.bulk_ingest.try_cache", return_value=rate_limited):
            summary = run_bulk_ingest(
                ["2401.00001"],
                lancedb_staging_path=tmp_path / "staging",
                ar5iv_cache_dir=tmp_path / "cache",
                parsed_dir=tmp_path / "parsed",
                failures_path=failures,
                log_path=tmp_path / "ingestion.log",
                ops_dir=tmp_path / "ops",
            )
        assert summary.papers_failed == 1
        row = json.loads(failures.read_text())
        assert row["failure_reason"] == "no_parsed_html:ar5iv_http_429"
        assert row["retriable"] is True


# ---------------------------------------------------------------------------
# Active corpus-version.json is NOT touched
# ---------------------------------------------------------------------------


class TestActiveCorpusVersionUntouched:
    """AC2 close: bulk ingest writes to a staging path, so the active
    `corpus-version.json` (under DEFAULT_LANCEDB_PATH) is byte-
    identical before and after the run.
    """

    def test_dry_run_doesnt_touch_active_marker(self, tmp_path):
        from arxmcp.ingest.store import DEFAULT_LANCEDB_PATH

        active_marker = DEFAULT_LANCEDB_PATH / "corpus-version.json"
        before = active_marker.read_bytes() if active_marker.is_file() else None
        # Dry-run with no parsed/cache hits — exits cleanly.
        failures = tmp_path / "bulk.jsonl"
        log = tmp_path / "ingestion.log"
        run_bulk_ingest(
            ["2401.00001"],
            ar5iv_cache_dir=tmp_path / "cache",
            parsed_dir=tmp_path / "parsed",
            failures_path=failures,
            log_path=log,
            dry_run=True,
        )
        after = active_marker.read_bytes() if active_marker.is_file() else None
        assert after == before


class TestParsedDirReachesTheChunker:
    """A caller's ``parsed_dir`` is where ar5iv writes the HTML and where
    the chunker reads it, so a non-default tree still chunks."""

    def test_ar5iv_html_in_a_custom_parsed_dir_is_chunked(self, tmp_path):
        from pathlib import Path

        from arxmcp.ingest.embedder import EmbedStats

        paper_id = "2307.00001"
        fixture = (
            Path(__file__).parent / "fixtures" / "chunker" / paper_id / "index.html"
        )

        class _Response:
            status = 200
            headers: dict[str, str] = {}
            url = f"https://ar5iv.labs.arxiv.org/html/{paper_id}"

            def read(self, _amt=None):
                return fixture.read_bytes()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        parsed_dir = tmp_path / "custom" / "parsed"
        chunks_dir = tmp_path / "chunks"
        with (
            patch("arxmcp.ingest.ar5iv_fetch.urllib.request.urlopen", return_value=_Response()),
            patch("arxmcp.ingest.chunker.PARSED_DIR", tmp_path / "default-parsed"),
            patch("arxmcp.ingest.chunker.CHUNKS_DIR", chunks_dir),
            patch("arxmcp.ingest.chunker._resolve_preamble_doc", return_value=None),
            patch(
                "arxmcp.ingest.bulk_ingest.embed_paper",
                return_value=EmbedStats(
                    paper_id=paper_id, chunks_processed=0, chunks_skipped=0,
                    truncated_count=0, elapsed_s=0.0, status="fail",
                    error="stop after chunking", error_class="stopped",
                ),
            ),
        ):
            outcome = ingest_one_paper(
                paper_id,
                lancedb_staging_path=tmp_path / "lancedb-staging",
                ar5iv_cache_dir=tmp_path / "cache",
                parsed_dir=parsed_dir,
            )

        assert outcome.parser_used == "ar5iv"
        assert (parsed_dir / paper_id / "index.html").is_file()
        assert outcome.failure_reason == "embedder_failed:stopped"
        assert (chunks_dir / paper_id / "chunk_manifest.json").is_file()


# ---------------------------------------------------------------------------
# Rectification regression guards
# ---------------------------------------------------------------------------


class TestEmbedderFailureSurfaces:
    """Closes F1: `embed_paper` failures must surface as a paper
    outcome with `failure_reason` starting with `embedder_failed`,
    NOT a silent stale-embed reuse via `load_embed_record`."""

    def test_embedder_fail_yields_failure_reason(self, tmp_path):
        from arxmcp.ingest.embedder import EmbedStats

        parsed_dir = tmp_path / "parsed"
        (parsed_dir / "2401.00001").mkdir(parents=True)
        (parsed_dir / "2401.00001" / "index.html").write_text("<html/>")

        with (
            patch(
                "arxmcp.ingest.bulk_ingest.try_cache",
                return_value=__import__(
                    "arxmcp.ingest.ar5iv_fetch", fromlist=["Ar5ivResult"]
                ).Ar5ivResult(
                    paper_id="2401.00001",
                    hit=True,
                    cache_path=parsed_dir / "2401.00001" / "index.html",
                    parsed_path=parsed_dir / "2401.00001" / "index.html",
                    reason="ok_local_cache",
                ),
            ),
            patch(
                "arxmcp.ingest.bulk_ingest.chunk_paper",
                return_value=[object()],
            ),
            patch(
                "arxmcp.ingest.bulk_ingest.embed_paper",
                return_value=EmbedStats(
                    paper_id="2401.00001",
                    chunks_processed=0,
                    chunks_skipped=0,
                    truncated_count=0,
                    elapsed_s=0.0,
                    status="fail",
                    error="forced failure",
                    error_class="model_init_failed",
                ),
            ),
            patch("arxmcp.ingest.bulk_ingest.write_chunks") as write_mock,
        ):
            from arxmcp.ingest.bulk_ingest import ingest_one_paper

            outcome = ingest_one_paper(
                "2401.00001",
                lancedb_staging_path=tmp_path / "lancedb-staging",
                parsed_dir=parsed_dir,
            )
        assert outcome.failure_reason is not None
        assert outcome.failure_reason.startswith("embedder_failed:")
        # And crucially: write_chunks was never called with stale data.
        write_mock.assert_not_called()


class TestPerPaperIsolation:
    """A paper whose pipeline raises is recorded as failed and the run
    goes on; only a WAP-gate failure, which is table-wide, stops it."""

    def _run(self, tmp_path, write_side_effect):
        from contextlib import ExitStack

        from arxmcp.ingest.ar5iv_fetch import Ar5ivResult
        from arxmcp.ingest.embedder import EmbedStats

        ids = ["2401.00001", "2401.00002", "2401.00003"]
        parsed_dir = tmp_path / "parsed"
        for pid in ids:
            (parsed_dir / pid).mkdir(parents=True)
            (parsed_dir / pid / "index.html").write_text("<html/>")

        def _hit(paper_id, *a, **kw):
            html = parsed_dir / paper_id / "index.html"
            return Ar5ivResult(
                paper_id=paper_id, hit=True, cache_path=html,
                parsed_path=html, reason="ok_local_cache",
            )

        with ExitStack() as stack:
            for target, kwargs in [
                ("try_cache", {"side_effect": _hit}),
                ("chunk_paper", {"return_value": [object()]}),
                ("embed_paper", {"side_effect": lambda pid: EmbedStats(
                    paper_id=pid, chunks_processed=1, chunks_skipped=0,
                    truncated_count=0, elapsed_s=0.0,
                )}),
                ("load_embed_record", {"return_value": object()}),
                ("write_chunks", {"side_effect": write_side_effect}),
                ("extract_equations_for_paper", {"return_value": 0}),
            ]:
                stack.enter_context(patch(f"arxmcp.ingest.bulk_ingest.{target}", **kwargs))
            return run_bulk_ingest(
                ids,
                lancedb_staging_path=tmp_path / "staging",
                parsed_dir=parsed_dir,
                failures_path=tmp_path / "failures.jsonl",
                log_path=tmp_path / "ingestion.log",
                ops_dir=tmp_path / "ops",
            )

    def test_a_raising_paper_is_recorded_and_the_run_continues(self, tmp_path):
        def _write(chunks, record, *, lancedb_path, **_kw):
            if _write.calls == 1:
                _write.calls += 1
                raise ValueError("chunk/vector misalignment")
            _write.calls += 1
            return 7

        _write.calls = 0
        summary = self._run(tmp_path, _write)
        assert summary.papers_succeeded == 2
        assert summary.papers_failed == 1
        failures = (tmp_path / "failures.jsonl").read_text().splitlines()
        assert len(failures) == 1
        row = json.loads(failures[0])
        assert row["paper_id"] == "2401.00002"
        assert row["failure_reason"] == (
            "raised:ValueError: chunk/vector misalignment"
        )

    def test_a_wap_gate_failure_stops_the_run(self, tmp_path):
        from arxmcp.ingest.store import WapGateError

        with pytest.raises(WapGateError):
            self._run(tmp_path, WapGateError("marker disagrees with table"))


class TestOneIndexBuildPerRun:
    """A bulk run writes each paper unindexed and indexes the table once."""

    def test_indexes_once_and_pins_the_indexed_version(self, tmp_path):
        from contextlib import ExitStack

        import lancedb
        import numpy as np

        import arxmcp.ingest.store as store_mod
        from arxmcp.ingest.ar5iv_fetch import Ar5ivResult
        from arxmcp.ingest.chunk import CHUNKER_VERSION, EMBEDDING_DIM
        from arxmcp.ingest.embedder import EmbedStats
        from arxmcp.ingest.schema import EmbedRecord

        ids = ["2401.00001", "2401.00002", "2401.00003"]
        parsed_dir = tmp_path / "parsed"
        for pid in ids:
            (parsed_dir / pid).mkdir(parents=True)
            (parsed_dir / pid / "index.html").write_text("<html/>")

        def _hit(paper_id, *a, **kw):
            html = parsed_dir / paper_id / "index.html"
            return Ar5ivResult(
                paper_id=paper_id, hit=True, cache_path=html,
                parsed_path=html, reason="ok_local_cache",
            )

        def _chunks(pid, **_kwargs):
            return [_row_chunk(pid, f"{i:016x}", CHUNKER_VERSION, f"{pid} {i}")
                    for i in range(2)]

        def _record(pid):
            chunks = _chunks(pid)
            rng = np.random.default_rng(int(pid[-1]))
            v = rng.standard_normal((len(chunks), EMBEDDING_DIM)).astype(np.float32)
            v /= np.linalg.norm(v, axis=1, keepdims=True)
            return EmbedRecord(
                chunk_ids_stmt=[c.chunk_id for c in chunks], embedding_stmt=v,
                embedder_version="bge-m3@00000000",
            )

        staging = tmp_path / "staging"
        with ExitStack() as stack:
            for target, kwargs in [
                ("try_cache", {"side_effect": _hit}),
                ("chunk_paper", {"side_effect": _chunks}),
                ("embed_paper", {"side_effect": lambda pid: EmbedStats(
                    paper_id=pid, chunks_processed=2, chunks_skipped=0,
                    truncated_count=0, elapsed_s=0.0,
                )}),
                ("load_embed_record", {"side_effect": _record}),
                ("build_derived_indexes", {}),
            ]:
                stack.enter_context(patch(f"arxmcp.ingest.bulk_ingest.{target}", **kwargs))
            summary = run_bulk_ingest(
                ids,
                lancedb_staging_path=staging,
                parsed_dir=parsed_dir,
                failures_path=tmp_path / "failures.jsonl",
                log_path=tmp_path / "ingestion.log",
                ops_dir=tmp_path / "ops",
            )

        assert summary.papers_succeeded == 3
        writes = [
            json.loads(line)
            for line in store_mod.STORE_STATS_PATH.read_text().splitlines()
        ]
        built = [w for w in writes if w["indices_created"]]
        assert len(writes) == 4  # three papers, then the index build
        assert built == [writes[-1]]
        tbl = lancedb.connect(str(staging)).open_table("chunks")
        # Every chunk is a statement, so there is no proof column to index.
        assert {i.columns[0] for i in tbl.list_indices()} == {
            "embedding_stmt", "paper_id",
        }
        marker = json.loads((staging / "corpus-version.json").read_text())
        assert marker["version"] == tbl.version
        assert (marker["chunk_count"], marker["paper_count"]) == (6, 3)


class TestResumeFlagRemoved:
    """Closes F3 + IS2: the no-op `--resume` flag is gone from the
    CLI and the `run_bulk_ingest` signature."""

    def test_resume_absent_from_cli(self):
        from arxmcp.ingest.bulk_ingest import _cli

        with pytest.raises(SystemExit):
            _cli(["--paper-ids-file=/nonexistent", "--resume"])

    def test_resume_absent_from_run_bulk_ingest_signature(self):
        import inspect

        sig = inspect.signature(run_bulk_ingest)
        assert "resume" not in sig.parameters


class TestParsedDirFlagRemoved:
    """Closes F2: the half-honored `--parsed-dir` CLI flag is gone
    (it was honored by try_cache but ignored by the chunker)."""

    def test_parsed_dir_absent_from_cli(self):
        from arxmcp.ingest.bulk_ingest import _cli

        with pytest.raises(SystemExit):
            _cli([
                "--paper-ids-file=/nonexistent",
                "--parsed-dir=/tmp/elsewhere",
            ])


class TestDryRunDoesNotReportMisleadingAr5ivRate:
    """Closes F5: dry-run never hits ar5iv, so ar5iv_misses must be
    0 in the summary and the printout must omit the rate."""

    def test_dry_run_does_not_increment_ar5iv_misses(self, tmp_path):
        failures = tmp_path / "bulk.jsonl"
        log = tmp_path / "ingestion.log"
        summary = run_bulk_ingest(
            ["2401.00001", "2401.00002"],
            ar5iv_cache_dir=tmp_path / "empty-cache",
            parsed_dir=tmp_path / "empty-parsed",
            failures_path=failures,
            log_path=log,
            dry_run=True,
        )
        assert summary.ar5iv_hits == 0
        assert summary.ar5iv_misses == 0
        assert summary.papers_skipped == 2

    def test_cli_dry_run_summary_omits_ar5iv_rate(
        self, tmp_path, capsys
    ):
        from arxmcp.ingest.bulk_ingest import _cli

        ids = tmp_path / "ids.txt"
        ids.write_text("2401.00001\n")
        rc = _cli([
            "--paper-ids-file", str(ids),
            "--ar5iv-cache-dir", str(tmp_path / "cache"),
            "--dry-run",
        ])
        out = capsys.readouterr().out
        assert "ar5iv_rate=" not in out
        assert rc == 0


class TestProgressIntervalValidation:
    """Closes F8: `progress_interval <= 0` must raise rather than
    crash mid-loop with `ZeroDivisionError`."""

    def test_zero_progress_interval_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="progress_interval"):
            run_bulk_ingest(
                ["2401.00001"],
                failures_path=tmp_path / "bulk.jsonl",
                log_path=tmp_path / "ingestion.log",
                progress_interval=0,
            )

    def test_negative_progress_interval_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="progress_interval"):
            run_bulk_ingest(
                ["2401.00001"],
                failures_path=tmp_path / "bulk.jsonl",
                log_path=tmp_path / "ingestion.log",
                progress_interval=-5,
            )


class TestDiagnoseEmptyRender:
    """ingest-robustness-m1 (AC4): categorize a zero-chunk render.

    ``_diagnose_empty_render`` distinguishes a structurally-unchunkable
    render (math present, no ltx_section/theorem/proof) from a generic empty,
    so operators can route the former to the PDF/MinerU path.
    """

    @staticmethod
    def _write(parsed_dir, paper_id: str, html: str):
        from pathlib import Path

        paper_dir = Path(parsed_dir) / paper_id
        paper_dir.mkdir(parents=True)
        (paper_dir / "index.html").write_text(html, encoding="utf-8")

    def test_math_but_no_sections_is_unchunkable(self, tmp_path):
        from arxmcp.ingest.bulk_ingest import _diagnose_empty_render

        parsed_dir = tmp_path / "parsed"
        self._write(
            parsed_dir,
            "hep-th/0002037",
            '<article class="ltx_document"><div class="ltx_para"><p class="ltx_p">'
            'prose <math alttext="x"><mi>x</mi></math></p></div></article>',
        )
        assert (
            _diagnose_empty_render("hep-th/0002037", parsed_dir)
            == "render_unchunkable_no_sections"
        )

    def test_structured_render_is_generic_empty(self, tmp_path):
        from arxmcp.ingest.bulk_ingest import _diagnose_empty_render

        parsed_dir = tmp_path / "parsed"
        self._write(
            parsed_dir,
            "2307.00001",
            '<article class="ltx_document"><section class="ltx_section">'
            '<math alttext="x"><mi>x</mi></math></section></article>',
        )
        assert (
            _diagnose_empty_render("2307.00001", parsed_dir)
            == "chunker_returned_empty"
        )

    def test_missing_file_degrades_to_generic(self, tmp_path):
        from arxmcp.ingest.bulk_ingest import _diagnose_empty_render

        assert (
            _diagnose_empty_render("2307.00002", tmp_path / "parsed")
            == "chunker_returned_empty"
        )

    def test_chapter_render_is_structured(self, tmp_path):
        # M2/L1: ltx_chapter is a structural signal (in the shared
        # STRUCTURE_SIGNAL_CLASSES), so a chapter-only render is NOT mislabeled
        # render_unchunkable_no_sections.
        from arxmcp.ingest.bulk_ingest import _diagnose_empty_render

        parsed_dir = tmp_path / "parsed"
        self._write(
            parsed_dir,
            "2307.00003",
            '<article class="ltx_document"><div class="ltx_chapter">'
            '<math alttext="x"><mi>x</mi></math></div></article>',
        )
        assert (
            _diagnose_empty_render("2307.00003", parsed_dir)
            == "chunker_returned_empty"
        )

    def test_ac4_signal_set_is_single_source(self):
        # M2/L1: both AC4 sites use arxmcp.ingest.chunker.STRUCTURE_SIGNAL_CLASSES so
        # the ar5iv no-sections WARN and the bulk diagnostic cannot drift apart.
        import arxmcp.ingest.ar5iv_fetch as a
        import arxmcp.ingest.bulk_ingest as b
        import arxmcp.ingest.chunker as c

        assert a.STRUCTURE_SIGNAL_CLASSES is c.STRUCTURE_SIGNAL_CLASSES
        assert b.STRUCTURE_SIGNAL_CLASSES is c.STRUCTURE_SIGNAL_CLASSES


# ---------------------------------------------------------------------------
# Never re-chunk in place across a chunker version
# ---------------------------------------------------------------------------


def _row_chunk(paper_id: str, suffix: str, version: str, body: str = "body"):
    from arxmcp.ingest.chunk import ChunkRecord

    return ChunkRecord(
        chunk_id=f"arxiv:{paper_id}:{suffix}",
        paper_id=paper_id,
        kind="stmt",
        section_path=[],
        theorem_name=None,
        theorem_label=None,
        body_text=body,
        body_tokens="body",
        chunker_version=version,
    )


def _write(path, chunks):
    import numpy as np

    from arxmcp.ingest.chunk import EMBEDDING_DIM
    from arxmcp.ingest.schema import EmbedRecord
    from arxmcp.ingest.store import write_chunks

    rng = np.random.default_rng(0)
    vectors = rng.standard_normal((len(chunks), EMBEDDING_DIM)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    write_chunks(
        chunks,
        EmbedRecord(
            chunk_ids_stmt=[c.chunk_id for c in chunks],
            embedding_stmt=vectors,
            chunk_ids_proof=[],
            embedding_proof=np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
            embedder_version="bge-m3@00000000",
        ),
        lancedb_path=path,
        build_indices=False,
    )


def _count(path) -> int:
    import lancedb

    return lancedb.connect(str(path)).open_table("chunks").count_rows()


def _minimal_table(path, rows: list[tuple[str, str | None]]):
    """A chunks table holding only the two columns the guard reads."""
    import lancedb
    import pyarrow as pa

    lancedb.connect(str(path)).create_table(
        "chunks",
        data=pa.table(
            {
                "chunk_id": [cid for cid, _ in rows],
                "chunker_version": pa.array([v for _, v in rows], pa.utf8()),
            }
        ),
    )


def _never_ingest(*_args, **_kwargs):
    raise AssertionError("ingest_one_paper must not run against a refused target")


class TestChunkerVersionGuard:
    """Once v1.3 is the chunker version, an
    in-place re-ingest of a v1.2 table (``make ingest``, notebook ingest, the
    ``/ui/`` console) would ``merge_insert`` new-id rows beside the old ones,
    because ``write_chunks`` has no delete arm."""

    def test_cli_reports_a_refusal_with_its_own_exit_code(
        self, tmp_path, monkeypatch, capsys
    ):
        # A refusal is not a crash: one "error:" line, no traceback, and
        # exit 3 rather than the failure exit 1.
        import arxmcp.ingest.bulk_ingest as bulk
        from arxmcp.ingest.store import STALE_CHUNKER_EXIT_CODE, StaleChunkerRowsError

        ids = tmp_path / "ids.txt"
        ids.write_text("2401.00001\n", encoding="utf-8")

        def _refuse(*_a, **_k):
            raise StaleChunkerRowsError("rotate it first (make re-embed)")

        monkeypatch.setattr(bulk, "run_bulk_ingest", _refuse)
        code = bulk._cli([
            "--paper-ids-file", str(ids),
            "--lancedb-staging-path", str(tmp_path / "lancedb"),
        ])

        assert code == STALE_CHUNKER_EXIT_CODE == 3
        err = capsys.readouterr().err
        assert "error: rotate it first" in err
        assert "Traceback" not in err

    def test_the_hazard_is_real(self, tmp_path):
        # Why the guard exists: the same body under a rotated id doubles.
        path = tmp_path / "lancedb"
        _write(path, [_row_chunk("2401.00001", "a" * 16, "v1.2", "same body")])
        _write(path, [_row_chunk("2401.00001", "b" * 16, "v1.3", "same body")])
        assert _count(path) == 2

    def test_refuses_a_target_holding_another_versions_arxiv_rows(self, tmp_path):
        from arxmcp.ingest.store import StaleChunkerRowsError

        path = tmp_path / "lancedb"
        _write(path, [_row_chunk("2401.00001", "a" * 16, "v1.2")])
        with (
            patch("arxmcp.ingest.bulk_ingest.ingest_one_paper", _never_ingest),
            pytest.raises(StaleChunkerRowsError, match="make notebook-cutover") as exc,
        ):
            run_bulk_ingest(
                ["2401.00001"],
                lancedb_staging_path=path,
                failures_path=tmp_path / "f.jsonl",
                log_path=tmp_path / "l.log",
                ops_dir=tmp_path,
            )
        assert "v1.2" in str(exc.value)
        assert _count(path) == 1

    def test_reads_the_rows_not_the_marker(self, tmp_path):
        # A textbook ingest restamps corpus-version.json with this code's
        # chunker version without touching an arXiv row.
        from arxmcp.ingest.chunk import CHUNKER_VERSION
        from arxmcp.ingest.store import (
            StaleChunkerRowsError,
            refuse_stale_chunker_rows,
            write_corpus_version_marker,
        )

        path = tmp_path / "lancedb"
        _write(path, [_row_chunk("2401.00001", "a" * 16, "v1.2")])
        write_corpus_version_marker(path, 9, CHUNKER_VERSION, "bge-m3@x", 1, 1)
        with pytest.raises(StaleChunkerRowsError):
            refuse_stale_chunker_rows(path)

    @pytest.mark.parametrize("state", ["missing", "empty", "current"])
    def test_allows_a_fresh_empty_or_current_target(self, tmp_path, state):
        from arxmcp.ingest.chunk import CHUNKER_VERSION, CHUNKS_SCHEMA_V1

        path = tmp_path / "lancedb"
        if state == "empty":
            import lancedb

            lancedb.connect(str(path)).create_table("chunks", schema=CHUNKS_SCHEMA_V1)
        elif state == "current":
            _write(path, [_row_chunk("2401.00001", "a" * 16, CHUNKER_VERSION)])
        with patch(
            "arxmcp.ingest.bulk_ingest.ingest_one_paper",
            side_effect=lambda pid, **kw: _ok_outcome(pid),
        ):
            summary = run_bulk_ingest(
                ["2401.00001"],
                lancedb_staging_path=path,
                failures_path=tmp_path / "f.jsonl",
                log_path=tmp_path / "l.log",
                ops_dir=tmp_path,
            )
        assert summary.papers_succeeded == 1

    def test_textbook_rows_are_not_checked(self, tmp_path):
        from arxmcp.ingest.chunk import CHUNKER_VERSION
        from arxmcp.ingest.store import refuse_stale_chunker_rows

        path = tmp_path / "lancedb"
        _minimal_table(
            path,
            [("textbook:ko95:" + "c" * 16, "tv0.1"),
             ("arxiv:2401.00001:" + "d" * 16, CHUNKER_VERSION)],
        )
        refuse_stale_chunker_rows(path)  # no raise

    def test_a_null_chunker_version_counts_as_stale(self, tmp_path):
        from arxmcp.ingest.store import StaleChunkerRowsError, refuse_stale_chunker_rows

        path = tmp_path / "lancedb"
        _minimal_table(path, [("arxiv:2401.00001:" + "e" * 16, None)])
        with pytest.raises(StaleChunkerRowsError, match="None"):
            refuse_stale_chunker_rows(path)

    def test_dry_run_is_not_refused(self, tmp_path):
        path = tmp_path / "lancedb"
        _write(path, [_row_chunk("2401.00001", "a" * 16, "v1.2")])
        summary = run_bulk_ingest(
            ["2401.00001"],
            lancedb_staging_path=path,
            ar5iv_cache_dir=tmp_path / "cache",
            parsed_dir=tmp_path / "parsed",
            failures_path=tmp_path / "f.jsonl",
            log_path=tmp_path / "l.log",
            dry_run=True,
        )
        assert summary.papers_skipped == 1
