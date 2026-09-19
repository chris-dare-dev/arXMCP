"""Ingest/parse stage-event tests (stage2/arx-a23, WS-A A3 — gap R4,
AC-A.15).

The events are ADDITIVE: nothing here touches the tri-state run rows
or the 2 s htmx poll (the existing ingest/parse suites are the
regression gate for those consumers). Covered here:

- the run-summary parser that derives chunk/embed/index completions
  from the finished subprocess's stdout (the honest granularity for
  the opaque notebook-ingest subprocess);
- the tracker seams: ``start_ingest`` emits ``preflight``; the
  summary regexes match the REAL ``tools/notebook_ingest.py`` print
  format (pinned against drift).
"""

from __future__ import annotations

import asyncio

from server.ingest_tracker import (
    _BM25_BUILT_RE,
    _BULK_SUMMARY_RE,
    IngestTaskTracker,
    _publish_run_summary_stages,
)
from server.observability import events as ev


def _ingest_ring() -> list[dict]:
    items, _total, _seq = ev.INGEST_EVENTS.snapshot(limit=50)
    return list(reversed(items))  # chronological


class TestSummaryRegexes:
    def test_bulk_summary_matches_real_print_format(self) -> None:
        """Pinned against tools/notebook_ingest.py's actual print:
        ``bulk_ingest: total={n} ok={n} fail={n} ar5iv_rate={f:.3f}``."""
        line = b"bulk_ingest: total=126 ok=125 fail=1 ar5iv_rate=0.968\n"
        m = _BULK_SUMMARY_RE.search(line)
        assert m is not None
        assert [int(g) for g in m.groups()] == [126, 125, 1]

    def test_bm25_line_matches_real_print_format(self) -> None:
        line = b"BM25 built for corpus_version=1690 (at var/x/v1690/)\n"
        m = _BM25_BUILT_RE.search(line)
        assert m is not None and int(m.group(1)) == 1690


class TestRunSummaryStages:
    def test_successful_run_emits_chunk_embed_index(self) -> None:
        stdout = (
            b"bulk_ingest: total=3 ok=3 fail=0 ar5iv_rate=1.000\n"
            b"BM25 built for corpus_version=42 (at .../v42/)\n"
        )
        _publish_run_summary_stages("nb-a", 7, stdout, exit_code=0)
        events = _ingest_ring()
        stages = [(e["stage"], e["phase"]) for e in events]
        assert stages == [
            ("chunk", "finished"), ("embed", "finished"), ("index", "finished"),
        ]
        chunk = events[0]
        assert chunk["detail"]["papers_ok"] == 3
        assert chunk["detail"]["derived"] == "run_summary"
        assert events[2]["detail"]["corpus_version"] == 42
        assert all(e["run_id"] == 7 and e["slug"] == "nb-a" for e in events)

    def test_zero_success_run_emits_failed_stages(self) -> None:
        stdout = b"bulk_ingest: total=2 ok=0 fail=2 ar5iv_rate=0.000\n"
        _publish_run_summary_stages("nb-a", 8, stdout, exit_code=1)
        stages = [(e["stage"], e["phase"]) for e in _ingest_ring()]
        assert ("chunk", "failed") in stages
        assert ("index", "failed") in stages

    def test_no_recognizable_output_emits_nothing_for_zero_exit(self) -> None:
        _publish_run_summary_stages("nb-a", 9, b"garbage output", exit_code=0)
        assert _ingest_ring() == []


class TestTrackerSeams:
    def test_start_ingest_emits_preflight(self, monkeypatch) -> None:
        """``start_ingest`` fires the preflight stage event before the
        subprocess task spawns (the caller already validated + wrote
        the run row). The subprocess itself is stubbed out."""

        async def _noop(
            self, slug, run_id, store, now_iso_provider, **kwargs
        ) -> None:
            # **kwargs: the a45 merge added ``notebook_kind`` (AC-A.18)
            # to ``_run_ingest_subprocess``; the stub stays tolerant of
            # signature growth on the real method.
            return None

        monkeypatch.setattr(
            IngestTaskTracker, "_run_ingest_subprocess", _noop,
        )

        async def _run() -> None:
            tracker = IngestTaskTracker()
            task = tracker.start_ingest(
                slug="nb-pre", run_id=3, store=None, now_iso_provider=lambda: "t",
            )
            await task

        asyncio.run(_run())
        events = _ingest_ring()
        assert events, "preflight event expected"
        assert events[0]["kind"] == "ingest"
        assert events[0]["stage"] == "preflight"
        assert events[0]["phase"] == "finished"
        assert events[0]["slug"] == "nb-pre"
        assert events[0]["run_id"] == 3

    def test_canonical_stage_vocabulary_is_pinned(self) -> None:
        """The six-stage stepper vocabulary is the IF-2 contract."""
        assert ev.INGEST_STAGES == (
            "preflight", "mineru", "latexml", "chunk", "embed", "index",
        )
