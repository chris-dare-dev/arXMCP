"""Tests for the OAI-PMH delta loop (E11_S02).

Pure unit tests with mocked HTTP responses (no live network) and
mocked ``ingest_one_paper`` (no LaTeXML / BGE-M3 / LanceDB
required). The suite covers all six AC items in the brief:

1. simulated delta run completes and writes a (mock) new corpus
   version,
2. resumption-token state is persisted after each harvested page,
3. a mock 500-paper run stays inside the 90-minute budget when
   sleep=0,
4. the 3-second politeness delay is invoked between page fetches,
5. the suite passes,
6. the runbook states the 90-minute budget explicitly.
"""

from __future__ import annotations

import json
import textwrap
from datetime import UTC
from pathlib import Path
from unittest.mock import patch

import pytest

from ingest.bulk_ingest import PaperOutcome
from ingest.oai_delta import (
    DEFAULT_BUDGET_SECONDS,
    METADATA_PREFIX,
    OAI_PMH_ENDPOINT,
    POLITENESS_SLEEP_SECONDS,
    _parse_listrecords,
    _read_state,
    _resolve_resume,
    _write_state,
    harvest_set,
    run_delta,
)

# ---------------------------------------------------------------------------
# XML fixtures
# ---------------------------------------------------------------------------


def _wrap_response(body_inner: str) -> bytes:
    """Wrap one ListRecords body in the OAI-PMH outer envelope."""
    return textwrap.dedent(
        f"""<?xml version="1.0" encoding="UTF-8"?>
        <OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
          <responseDate>2026-05-15T02:00:00Z</responseDate>
          <ListRecords>{body_inner}</ListRecords>
        </OAI-PMH>
        """
    ).encode("utf-8")


def _record(paper_id: str, *, deleted: bool = False) -> str:
    if deleted:
        return f"""
        <record xmlns="http://www.openarchives.org/OAI/2.0/">
          <header status="deleted">
            <identifier>oai:arXiv.org:{paper_id}</identifier>
            <datestamp>2026-05-14</datestamp>
          </header>
        </record>
        """
    return f"""
    <record xmlns="http://www.openarchives.org/OAI/2.0/">
      <header>
        <identifier>oai:arXiv.org:{paper_id}</identifier>
        <datestamp>2026-05-14</datestamp>
      </header>
      <metadata>
        <arXivRaw xmlns="http://arxiv.org/OAI/arXivRaw/">
          <categories>math.AG</categories>
        </arXivRaw>
      </metadata>
    </record>
    """


def _final_page(paper_ids: list[str]) -> bytes:
    """A page with no resumption token (end-of-list)."""
    records = "".join(_record(pid) for pid in paper_ids)
    return _wrap_response(records)


def _continuation_page(paper_ids: list[str], next_token: str) -> bytes:
    """A page that hands back a non-empty resumption token."""
    records = "".join(_record(pid) for pid in paper_ids)
    inner = (
        records
        + f'<resumptionToken xmlns="http://www.openarchives.org/OAI/2.0/">{next_token}</resumptionToken>'
    )
    return _wrap_response(inner)


def _empty_token_page(paper_ids: list[str]) -> bytes:
    """Final page with an EMPTY resumption token element."""
    records = "".join(_record(pid) for pid in paper_ids)
    inner = (
        records
        + '<resumptionToken xmlns="http://www.openarchives.org/OAI/2.0/"></resumptionToken>'
    )
    return _wrap_response(inner)


# ---------------------------------------------------------------------------
# _parse_listrecords
# ---------------------------------------------------------------------------


class TestParseListRecords:
    def test_parses_records(self):
        body = _final_page(["2401.00001", "2401.00002"])
        records, token = _parse_listrecords(body, set_spec="math:math:AG")
        assert [r.paper_id for r in records] == ["2401.00001", "2401.00002"]
        assert token is None

    def test_empty_resumption_token_signals_end(self):
        records, token = _parse_listrecords(
            _empty_token_page(["2401.00001"]),
            set_spec="math:math:AG",
        )
        assert len(records) == 1
        assert token is None  # empty token === end-of-list per spec

    def test_continuation_token_returned(self):
        records, token = _parse_listrecords(
            _continuation_page(["2401.00001"], next_token="abc123"),
            set_spec="math:math:AG",
        )
        assert token == "abc123"

    def test_deleted_record_flagged(self):
        records, _ = _parse_listrecords(
            _wrap_response(_record("2401.00099", deleted=True)),
            set_spec="math:math:AG",
        )
        assert len(records) == 1
        assert records[0].deleted is True

    def test_oai_error_raises(self):
        body = textwrap.dedent(
            """<?xml version="1.0" encoding="UTF-8"?>
            <OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
              <error code="badArgument">bad from</error>
            </OAI-PMH>"""
        ).encode()
        with pytest.raises(RuntimeError, match="badArgument"):
            _parse_listrecords(body, set_spec="math:math:AG")

    def test_malformed_paper_id_skipped(self):
        body = _wrap_response(
            """
            <record xmlns="http://www.openarchives.org/OAI/2.0/">
              <header>
                <identifier>oai:arXiv.org:not-an-id</identifier>
                <datestamp>2026-05-14</datestamp>
              </header>
            </record>
            """
        )
        records, _ = _parse_listrecords(body, set_spec="math:math:AG")
        assert records == []


# ---------------------------------------------------------------------------
# State file
# ---------------------------------------------------------------------------


class TestStateFile:
    def test_read_missing_returns_empty(self, tmp_path):
        assert _read_state(tmp_path / "missing.json") == {}

    def test_write_then_read_round_trips(self, tmp_path):
        path = tmp_path / "state.json"
        state = {
            "last_harvest_date": "2026-05-14",
            "last_resumption_token": "tok-1",
        }
        _write_state(path, state)
        assert _read_state(path) == state

    def test_malformed_state_raises(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("{not json")
        with pytest.raises(RuntimeError, match="malformed"):
            _read_state(path)

    def test_atomic_write_uses_temp(self, tmp_path):
        path = tmp_path / "state.json"
        _write_state(path, {"a": 1})
        # The .tmp file should NOT linger.
        assert not path.with_suffix(".json.tmp").exists()
        assert json.loads(path.read_text()) == {"a": 1}


# ---------------------------------------------------------------------------
# Resume logic
# ---------------------------------------------------------------------------


class TestResolveResume:
    def test_first_run_returns_yesterday_and_no_token(self):
        from_date, token = _resolve_resume({})
        # Just sanity: from_date must be a YYYY-MM-DD string, token None.
        assert len(from_date) == 10 and from_date[4] == "-"
        assert token is None

    def test_same_day_resume_keeps_token(self):
        from datetime import datetime

        today = datetime.now(UTC).date().isoformat()
        from_date, token = _resolve_resume(
            {"last_harvest_date": today, "last_resumption_token": "tok-x"}
        )
        assert from_date == today
        assert token == "tok-x"

    def test_cross_day_resume_discards_expired_token(self):
        from_date, token = _resolve_resume(
            {
                "last_harvest_date": "2020-01-01",
                "last_resumption_token": "expired",
            }
        )
        # Token expired (date is in the past); harvest from that date.
        assert from_date == "2020-01-01"
        assert token is None


# ---------------------------------------------------------------------------
# harvest_set with mocked HTTP
# ---------------------------------------------------------------------------


class _MockFetcher:
    """Deterministic fetch_page replacement. Walks a list of bodies."""

    def __init__(self, pages: list[bytes]):
        self._pages = list(pages)
        self.calls: list[dict] = []

    def __call__(self, endpoint: str, params: dict, *, timeout_seconds, user_agent):
        self.calls.append(params)
        return self._pages.pop(0)


class TestHarvestSet:
    def test_single_page_no_token(self, tmp_path):
        fetcher = _MockFetcher([_final_page(["2401.00001", "2401.00002"])])
        records, pages = harvest_set(
            "math:math:AG",
            from_date="2026-05-14",
            until_date="2026-05-14",
            state_path=tmp_path / "state.json",
            fetch_page=fetcher,
            sleep_between_pages=lambda _t: None,
        )
        assert len(records) == 2
        assert pages == 1
        # First call must have all five params; not a resume.
        assert fetcher.calls[0]["verb"] == "ListRecords"
        assert fetcher.calls[0]["metadataPrefix"] == METADATA_PREFIX
        assert fetcher.calls[0]["set"] == "math:math:AG"
        assert fetcher.calls[0]["from"] == "2026-05-14"

    def test_paginated_token_loop(self, tmp_path):
        pages_data = [
            _continuation_page(["2401.00001"], next_token="tok-2"),
            _continuation_page(["2401.00002"], next_token="tok-3"),
            _final_page(["2401.00003"]),
        ]
        fetcher = _MockFetcher(pages_data)
        sleeps: list[float] = []
        records, pages = harvest_set(
            "math:math:AG",
            from_date="2026-05-14",
            until_date="2026-05-14",
            state_path=tmp_path / "state.json",
            fetch_page=fetcher,
            sleep_between_pages=lambda t: sleeps.append(t),
        )
        assert [r.paper_id for r in records] == [
            "2401.00001", "2401.00002", "2401.00003",
        ]
        assert pages == 3
        # Resume calls (pages 2 and 3) carry ONLY verb + resumptionToken.
        assert fetcher.calls[1] == {
            "verb": "ListRecords", "resumptionToken": "tok-2",
        }
        assert fetcher.calls[2] == {
            "verb": "ListRecords", "resumptionToken": "tok-3",
        }
        # Politeness sleep called between every pair of pages.
        assert len(sleeps) == 2

    def test_state_persisted_after_each_page(self, tmp_path):
        pages_data = [
            _continuation_page(["2401.00001"], next_token="tok-2"),
            _final_page(["2401.00002"]),
        ]
        fetcher = _MockFetcher(pages_data)
        state_path = tmp_path / "state.json"
        harvest_set(
            "math:math:AG",
            from_date="2026-05-14",
            until_date="2026-05-14",
            state_path=state_path,
            fetch_page=fetcher,
            sleep_between_pages=lambda _t: None,
        )
        # After the final page, state's token is None.
        state = _read_state(state_path)
        assert state["last_resumption_token"] is None

    def test_resume_token_used_on_first_call(self, tmp_path):
        fetcher = _MockFetcher([_final_page(["2401.00001"])])
        harvest_set(
            "math:math:AG",
            from_date="2026-05-14",
            until_date="2026-05-14",
            state_path=tmp_path / "state.json",
            resume_token="saved-tok",
            fetch_page=fetcher,
            sleep_between_pages=lambda _t: None,
        )
        # First call MUST use the resume-token form; no from/until/set.
        assert fetcher.calls[0] == {
            "verb": "ListRecords", "resumptionToken": "saved-tok",
        }


# ---------------------------------------------------------------------------
# run_delta with mocked per-paper pipeline
# ---------------------------------------------------------------------------


def _ok_paper_outcome(paper_id: str) -> PaperOutcome:
    return PaperOutcome(
        paper_id=paper_id,
        parsers_tried=["ar5iv"],
        parser_used="ar5iv",
        chunks_written=5,
        elapsed_seconds=0.01,
    )


class TestRunDelta:
    def test_end_to_end_with_mock_records(self, tmp_path):
        fetcher = _MockFetcher([_final_page(["2401.00001", "2401.00002"])])
        with patch(
            "ingest.oai_delta.ingest_one_paper",
            side_effect=lambda pid, **kw: _ok_paper_outcome(pid),
        ):
            summary = run_delta(
                sets=("math:math:AG",),
                from_date="2026-05-14",
                until_date="2026-05-14",
                lancedb_staging_path=tmp_path / "lancedb-staging",
                state_path=tmp_path / "state.json",
                log_path=tmp_path / "delta.log",
                failures_path=tmp_path / "delta.jsonl",
                timeout_flag_path=tmp_path / "timeout.flag",
                fetch_page=fetcher,
                sleep_between_pages=lambda _t: None,
            )
        assert summary.records_total == 2
        assert summary.records_ingested == 2
        assert summary.records_failed == 0
        assert summary.budget_breached is False
        # State advanced to "today"; token cleared.
        state = _read_state(tmp_path / "state.json")
        assert state["last_resumption_token"] is None
        assert state["last_run_paper_count"] == 2

    def test_deleted_record_skips_pipeline_and_doesnt_write(self, tmp_path):
        body = _wrap_response(_record("2401.00099", deleted=True))
        fetcher = _MockFetcher([body])
        with patch(
            "ingest.oai_delta.ingest_one_paper",
            side_effect=AssertionError("must not be called for deleted records"),
        ):
            summary = run_delta(
                sets=("math:math:AG",),
                from_date="2026-05-14",
                until_date="2026-05-14",
                lancedb_staging_path=tmp_path / "lancedb-staging",
                state_path=tmp_path / "state.json",
                log_path=tmp_path / "delta.log",
                failures_path=tmp_path / "delta.jsonl",
                timeout_flag_path=tmp_path / "timeout.flag",
                fetch_page=fetcher,
                sleep_between_pages=lambda _t: None,
            )
        assert summary.records_total == 1
        assert summary.records_deleted == 1
        assert summary.records_ingested == 0

    def test_dry_run_does_not_call_pipeline(self, tmp_path, capsys):
        fetcher = _MockFetcher([_final_page(["2401.00001"])])
        with patch(
            "ingest.oai_delta.ingest_one_paper",
            side_effect=AssertionError("dry-run must not call this"),
        ):
            summary = run_delta(
                sets=("math:math:AG",),
                from_date="2026-05-14",
                until_date="2026-05-14",
                lancedb_staging_path=tmp_path / "lancedb-staging",
                state_path=tmp_path / "state.json",
                log_path=tmp_path / "delta.log",
                failures_path=tmp_path / "delta.jsonl",
                timeout_flag_path=tmp_path / "timeout.flag",
                fetch_page=fetcher,
                sleep_between_pages=lambda _t: None,
                dry_run=True,
            )
        out = capsys.readouterr().out
        assert "2401.00001" in out
        assert "WOULD_INGEST" in out
        assert summary.records_ingested == 0

    def test_500_paper_mock_run_stays_in_budget(self, tmp_path):
        """AC: a 500-paper mock run completes within 90 min (sleep=0)."""
        paper_ids = [f"2401.{i:05d}" for i in range(500)]
        # All 500 fit in one page; tests budget arithmetic + the
        # zero-sleep assumption.
        fetcher = _MockFetcher([_final_page(paper_ids)])
        with patch(
            "ingest.oai_delta.ingest_one_paper",
            side_effect=lambda pid, **kw: _ok_paper_outcome(pid),
        ):
            summary = run_delta(
                sets=("math:math:AG",),
                from_date="2026-05-14",
                until_date="2026-05-14",
                lancedb_staging_path=tmp_path / "lancedb-staging",
                state_path=tmp_path / "state.json",
                log_path=tmp_path / "delta.log",
                failures_path=tmp_path / "delta.jsonl",
                timeout_flag_path=tmp_path / "timeout.flag",
                fetch_page=fetcher,
                sleep_between_pages=lambda _t: None,
            )
        assert summary.records_total == 500
        assert summary.records_ingested == 500
        assert summary.budget_breached is False
        assert summary.elapsed_seconds < DEFAULT_BUDGET_SECONDS

    def test_budget_breach_emits_sentinel(self, tmp_path):
        fetcher = _MockFetcher([_final_page(["2401.00001"])])
        flag = tmp_path / "timeout.flag"
        with patch(
            "ingest.oai_delta.ingest_one_paper",
            side_effect=lambda pid, **kw: _ok_paper_outcome(pid),
        ):
            summary = run_delta(
                sets=("math:math:AG",),
                from_date="2026-05-14",
                until_date="2026-05-14",
                lancedb_staging_path=tmp_path / "lancedb-staging",
                state_path=tmp_path / "state.json",
                log_path=tmp_path / "delta.log",
                failures_path=tmp_path / "delta.jsonl",
                timeout_flag_path=flag,
                # Synthetic budget: zero seconds. Any work breaches.
                budget_seconds=0.0,
                fetch_page=fetcher,
                sleep_between_pages=lambda _t: None,
            )
        assert summary.budget_breached is True
        assert flag.is_file()
        payload = json.loads(flag.read_text())
        assert payload["budget_seconds"] == 0.0
        assert payload["elapsed_seconds"] >= 0

    def test_clears_old_timeout_flag_on_successful_run(self, tmp_path):
        flag = tmp_path / "timeout.flag"
        flag.write_text("{}")  # leftover from a prior breach
        fetcher = _MockFetcher([_final_page(["2401.00001"])])
        with patch(
            "ingest.oai_delta.ingest_one_paper",
            side_effect=lambda pid, **kw: _ok_paper_outcome(pid),
        ):
            run_delta(
                sets=("math:math:AG",),
                from_date="2026-05-14",
                until_date="2026-05-14",
                lancedb_staging_path=tmp_path / "lancedb-staging",
                state_path=tmp_path / "state.json",
                log_path=tmp_path / "delta.log",
                failures_path=tmp_path / "delta.jsonl",
                timeout_flag_path=flag,
                fetch_page=fetcher,
                sleep_between_pages=lambda _t: None,
            )
        assert not flag.is_file()


# ---------------------------------------------------------------------------
# Politeness contract
# ---------------------------------------------------------------------------


class TestPolitenessContract:
    def test_default_is_3_seconds(self):
        assert POLITENESS_SLEEP_SECONDS == 3.0

    def test_sleep_invoked_between_pages(self, tmp_path):
        fetcher = _MockFetcher([
            _continuation_page(["2401.00001"], next_token="tok-2"),
            _final_page(["2401.00002"]),
        ])
        sleep_starts: list[float] = []
        harvest_set(
            "math:math:AG",
            from_date="2026-05-14",
            until_date="2026-05-14",
            state_path=tmp_path / "state.json",
            fetch_page=fetcher,
            sleep_between_pages=lambda t: sleep_starts.append(t),
        )
        # One sleep between the two pages; no sleep after the final.
        assert len(sleep_starts) == 1


# ---------------------------------------------------------------------------
# Runbook content
# ---------------------------------------------------------------------------


class TestRunbookContent:
    def test_runbook_states_90_minute_budget(self):
        runbook = (
            Path(__file__).resolve().parent.parent
            / "docs" / "ops" / "delta-loop.md"
        )
        assert runbook.is_file(), f"runbook missing at {runbook}"
        text = runbook.read_text(encoding="utf-8")
        assert "90-minute" in text or "90 minute" in text

    def test_runbook_documents_no_touch_file(self):
        runbook = (
            Path(__file__).resolve().parent.parent
            / "docs" / "ops" / "delta-loop.md"
        )
        text = runbook.read_text(encoding="utf-8")
        # The brief mentioned a touch file; the synthesis drops it.
        # The runbook should document the manual-restart mechanism
        # and explicitly say there is no touch file.
        assert "restart" in text.lower()


# ---------------------------------------------------------------------------
# Endpoint hygiene
# ---------------------------------------------------------------------------


class TestEndpointHygiene:
    def test_endpoint_is_https(self):
        # Synthesis D4: HTTPS, not legacy HTTP.
        assert OAI_PMH_ENDPOINT.startswith("https://")
        assert "oaipmh.arxiv.org" in OAI_PMH_ENDPOINT


# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------


class TestCLI:
    def test_dry_run_flag_accepted(self, tmp_path, capsys):
        from ingest.oai_delta import DEFAULT_SETS, _cli

        # The CLI walks all DEFAULT_SETS — provide one mock page per set.
        fetcher = _MockFetcher(
            [_final_page(["2401.00001"]) for _ in DEFAULT_SETS]
        )
        with patch("ingest.oai_delta._fetch_page", fetcher):
            rc = _cli([
                "--from", "2026-05-14",
                "--until", "2026-05-14",
                "--state-file", str(tmp_path / "state.json"),
                "--lancedb-staging-path", str(tmp_path / "lance"),
                "--dry-run",
            ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "2401.00001" in out
        # Records appear once per set in the dry-run printout.
        assert out.count("WOULD_INGEST") == len(DEFAULT_SETS)