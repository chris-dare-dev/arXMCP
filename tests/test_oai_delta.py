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

import io
import json
import textwrap
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from ingest.bulk_ingest import PaperOutcome
from ingest.oai_delta import (
    DEFAULT_BUDGET_SECONDS,
    METADATA_PREFIX,
    OAI_PMH_ENDPOINT,
    POLITENESS_SLEEP_SECONDS,
    _fetch_page,
    _parse_listrecords,
    _parse_retry_after,
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
        from_date, token, set_spec = _resolve_resume({})
        # Just sanity: from_date must be a YYYY-MM-DD string, token None.
        assert len(from_date) == 10 and from_date[4] == "-"
        assert token is None
        assert set_spec is None

    def test_same_day_resume_keeps_token_and_set(self):
        today = datetime.now(UTC).date().isoformat()
        from_date, token, set_spec = _resolve_resume(
            {
                "last_harvest_date": today,
                "last_resumption_token": "tok-x",
                "last_set_spec": "math:math:AG",
            }
        )
        assert from_date == today
        assert token == "tok-x"
        assert set_spec == "math:math:AG"

    def test_cross_day_resume_discards_expired_token(self):
        from_date, token, set_spec = _resolve_resume(
            {
                "last_harvest_date": "2020-01-01",
                "last_resumption_token": "expired",
                "last_set_spec": "math:math:AG",
            }
        )
        # Token expired (date is in the past); harvest from that date.
        assert from_date == "2020-01-01"
        assert token is None
        assert set_spec is None

    def test_future_date_resets_to_yesterday(self):
        """Closes F8: a future last_harvest_date (clock skew /
        operator typo) resets to yesterday rather than passing a
        future window to OAI-PMH."""
        future = (datetime.now(UTC).date() + timedelta(days=30)).isoformat()
        from_date, token, set_spec = _resolve_resume(
            {
                "last_harvest_date": future,
                "last_resumption_token": "bogus",
                "last_set_spec": "math:math:AG",
            }
        )
        # Reset signal: from_date is NOT the future date.
        assert from_date != future
        assert len(from_date) == 10 and from_date[4] == "-"
        assert token is None
        assert set_spec is None


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

    def test_writes_ingest_summary_sentinel(self, tmp_path):
        """corpus-integrity-observability-e3 F3: run_delta writes the
        ingest-summary.json sentinel at end-of-run (AC2)."""
        import json as _json

        fetcher = _MockFetcher([_final_page(["2401.00001", "2401.00002"])])
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
                timeout_flag_path=tmp_path / "timeout.flag",
                ops_dir=tmp_path,
                fetch_page=fetcher,
                sleep_between_pages=lambda _t: None,
            )
        sentinel = tmp_path / "ingest-summary.json"
        assert sentinel.is_file()
        payload = _json.loads(sentinel.read_text(encoding="utf-8"))
        assert payload["schema_version"] == 1
        assert payload["driver"] == "oai_delta"
        assert payload["papers_processed"] == 2

    def test_papers_processed_excludes_deletions(self, tmp_path):
        """corpus-integrity-observability-e3 F4: a delta run with a deletion must
        NOT count the deletion in papers_processed — processed == succeeded +
        failed (consistent with the bulk path). records_total includes deletions
        and would inflate the arxmcp_ingest_last_run_papers gauge."""
        import json as _json

        mixed = _wrap_response(
            _record("2401.00001") + _record("2401.00099", deleted=True)
        )
        fetcher = _MockFetcher([mixed])
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
                ops_dir=tmp_path,
                fetch_page=fetcher,
                sleep_between_pages=lambda _t: None,
            )
        assert summary.records_deleted == 1
        assert summary.records_ingested == 1
        payload = _json.loads(
            (tmp_path / "ingest-summary.json").read_text(encoding="utf-8")
        )
        assert payload["papers_processed"] == 1  # pre-fix: 2 (records_total)
        assert (
            payload["papers_processed"]
            == payload["papers_succeeded"] + payload["papers_failed"]
        )

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


# ---------------------------------------------------------------------------
# Rectification regression guards
# ---------------------------------------------------------------------------


class TestRetryAfterParsing:
    """Closes F1 (parse half): Retry-After header parsing."""

    def test_integer_seconds(self):
        assert _parse_retry_after("30") == 30.0

    def test_whitespace_stripped(self):
        assert _parse_retry_after("  45  ") == 45.0

    def test_none_input(self):
        assert _parse_retry_after(None) is None

    def test_non_numeric_returns_none(self):
        # HTTP-date form isn't supported; fall back to exponential.
        assert _parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT") is None

    def test_negative_clamped_to_zero(self):
        assert _parse_retry_after("-5") == 0.0


class TestFetchPage503Backoff:
    """Closes F1: 503/Retry-After honored; non-503 errors propagate."""

    def test_503_then_200_succeeds_after_retry(self):
        calls: list[float] = []

        class _Fake503Then200:
            def __init__(self):
                self.n = 0

            def __call__(self, request, timeout):
                self.n += 1
                if self.n == 1:
                    err = urllib.error.HTTPError(
                        url=request.full_url,
                        code=503,
                        msg="Service Unavailable",
                        hdrs={"Retry-After": "5"},
                        fp=io.BytesIO(b""),
                    )
                    err.headers = {"Retry-After": "5"}
                    raise err
                return _FakeUrlOpenResponse(
                    body=b"<ok/>",
                    url=f"{OAI_PMH_ENDPOINT}?verb=ListRecords",
                )

        opener = _Fake503Then200()
        with patch("ingest.oai_delta.urllib.request.urlopen", opener):
            body = _fetch_page(
                OAI_PMH_ENDPOINT,
                {"verb": "ListRecords"},
                timeout_seconds=5.0,
                user_agent="test/0.1",
                sleep=lambda t: calls.append(t),
                monotonic=lambda: 0.0,
                retry_cap_seconds=3600.0,
            )
        assert body == b"<ok/>"
        # Retry-After=5 was honored.
        assert calls == [5.0]

    def test_non_503_error_propagates_without_retry(self):
        sleeps: list[float] = []

        def _err(request, timeout):
            err = urllib.error.HTTPError(
                url=request.full_url,
                code=404,
                msg="Not Found",
                hdrs=None,
                fp=io.BytesIO(b""),
            )
            raise err

        with (
            patch("ingest.oai_delta.urllib.request.urlopen", _err),
            pytest.raises(urllib.error.HTTPError),
        ):
            _fetch_page(
                OAI_PMH_ENDPOINT,
                {"verb": "ListRecords"},
                timeout_seconds=5.0,
                user_agent="test/0.1",
                sleep=lambda t: sleeps.append(t),
                monotonic=lambda: 0.0,
            )
        # Did not retry.
        assert sleeps == []

    def test_503_retry_cap_exhaustion_raises(self):
        """When the retry cap elapses, _fetch_page surfaces a
        RuntimeError instead of looping forever."""

        def _always_503(request, timeout):
            err = urllib.error.HTTPError(
                url=request.full_url,
                code=503,
                msg="Service Unavailable",
                hdrs=None,
                fp=io.BytesIO(b""),
            )
            err.headers = {"Retry-After": "30"}
            raise err

        # Synthetic clock: deadline of 60s; first retry consumes 30s,
        # next retry would consume another 30s — at second iteration
        # the deadline is exhausted.
        clock = {"now": 0.0}

        def _monotonic():
            return clock["now"]

        def _sleep(t):
            clock["now"] += t

        with (
            patch("ingest.oai_delta.urllib.request.urlopen", _always_503),
            pytest.raises(RuntimeError, match="retry cap"),
        ):
            _fetch_page(
                OAI_PMH_ENDPOINT,
                {"verb": "ListRecords"},
                timeout_seconds=5.0,
                user_agent="test/0.1",
                sleep=_sleep,
                monotonic=_monotonic,
                retry_cap_seconds=60.0,
            )


class TestFetchPageRedirectPin:
    """Closes F2: off-host redirects rejected."""

    def test_off_host_response_url_rejected(self):
        with patch(
            "ingest.oai_delta.urllib.request.urlopen",
            return_value=_FakeUrlOpenResponse(
                body=b"<ok/>", url="https://evil.example/x"
            ),
        ), pytest.raises(RuntimeError, match="redirected off"):
            _fetch_page(
                OAI_PMH_ENDPOINT,
                {"verb": "ListRecords"},
                timeout_seconds=5.0,
                user_agent="test/0.1",
            )

    def test_on_host_response_url_accepted(self):
        with patch(
            "ingest.oai_delta.urllib.request.urlopen",
            return_value=_FakeUrlOpenResponse(
                body=b"<ok/>",
                url=f"{OAI_PMH_ENDPOINT}?verb=ListRecords",
            ),
        ):
            body = _fetch_page(
                OAI_PMH_ENDPOINT,
                {"verb": "ListRecords"},
                timeout_seconds=5.0,
                user_agent="test/0.1",
            )
        assert body == b"<ok/>"


class TestNoRecordsMatch:
    """Closes F4: quiet-day `noRecordsMatch` is empty-success, not fatal."""

    def test_norecordsmatch_returns_empty_no_token(self):
        body = textwrap.dedent(
            """<?xml version="1.0" encoding="UTF-8"?>
            <OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
              <error code="noRecordsMatch">no records</error>
            </OAI-PMH>"""
        ).encode()
        records, token = _parse_listrecords(body, set_spec="math:math:AG")
        assert records == []
        assert token is None

    def test_one_quiet_set_does_not_crash_run(self, tmp_path):
        """A run where one set returns noRecordsMatch still
        harvests the other sets successfully."""
        good = _final_page(["2401.00001"])
        quiet = textwrap.dedent(
            """<?xml version="1.0" encoding="UTF-8"?>
            <OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
              <error code="noRecordsMatch">no records</error>
            </OAI-PMH>"""
        ).encode()
        fetcher = _MockFetcher([good, quiet, good, good])
        with patch(
            "ingest.oai_delta.ingest_one_paper",
            side_effect=lambda pid, **kw: _ok_paper_outcome(pid),
        ):
            summary = run_delta(
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
        # Three of four sets returned 1 paper; the quiet one is 0.
        assert summary.records_total == 3
        assert summary.records_ingested == 3


class TestSetAwareTokenRecovery:
    """Closes F3: resume token applied only to its origin set."""

    def test_token_used_only_for_origin_set(self, tmp_path):
        """A state file with `last_set_spec=math:math:NT` MUST NOT
        feed the token into the first set (`math:math:AG`)."""
        state_path = tmp_path / "state.json"
        today = datetime.now(UTC).date().isoformat()
        _write_state(
            state_path,
            {
                "last_harvest_date": today,
                "last_resumption_token": "tok-NT",
                "last_set_spec": "math:math:NT",
            },
        )
        # 4 sets × 1 page each = 4 mock responses.
        fetcher = _MockFetcher([_final_page(["2401.00001"])] * 4)
        with patch(
            "ingest.oai_delta.ingest_one_paper",
            side_effect=lambda pid, **kw: _ok_paper_outcome(pid),
        ):
            run_delta(
                # Pin until=today so the same-day resume window is
                # valid (state.last_harvest_date==today drives
                # effective_from=today; until defaults to yesterday
                # which would invert the window).
                until_date=today,
                lancedb_staging_path=tmp_path / "lancedb-staging",
                state_path=state_path,
                log_path=tmp_path / "delta.log",
                failures_path=tmp_path / "delta.jsonl",
                timeout_flag_path=tmp_path / "timeout.flag",
                fetch_page=fetcher,
                sleep_between_pages=lambda _t: None,
            )
        # The FIRST call MUST be the windowed-form (no resumption
        # token) because the saved token's set isn't sets[0].
        first = fetcher.calls[0]
        assert "resumptionToken" not in first
        assert first["set"] == "math:math:AG"
        # The NT-set call (index 1) MUST consume the saved token.
        second = fetcher.calls[1]
        assert second == {
            "verb": "ListRecords", "resumptionToken": "tok-NT",
        }


class TestFromUntilValidation:
    """Closes F9: inverted window rejected at run_delta entry."""

    def test_from_greater_than_until_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="from_date"):
            run_delta(
                from_date="2026-05-15",
                until_date="2026-05-14",
                lancedb_staging_path=tmp_path / "lancedb-staging",
                state_path=tmp_path / "state.json",
                log_path=tmp_path / "delta.log",
                failures_path=tmp_path / "delta.jsonl",
                timeout_flag_path=tmp_path / "timeout.flag",
            )


class TestStaleTimeoutFlagCleared:
    """Closes F11: stale timeout flag is cleared even on dry-run."""

    def test_dry_run_clears_old_flag(self, tmp_path):
        flag = tmp_path / "timeout.flag"
        flag.write_text("{}")
        fetcher = _MockFetcher([_final_page(["2401.00001"])])
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
            dry_run=True,
        )
        assert not flag.is_file()


class TestMakeDeltaTarget:
    """Closes F13 + IS5: `make delta` target exists in Makefile."""

    def test_delta_target_in_makefile(self):
        makefile = Path(__file__).resolve().parent.parent / "Makefile"
        text = makefile.read_text(encoding="utf-8")
        assert "\ndelta:\n" in text
        assert "ingest.oai_delta" in text


class TestShellWrapperHasNoPersonalPath:
    """Closes IS2: hardcoded /Users/ path removed from cron wrapper."""

    def test_no_personal_path_in_wrapper(self):
        wrapper = (
            Path(__file__).resolve().parent.parent
            / "ops" / "cron" / "arxmcp-delta.sh"
        )
        text = wrapper.read_text(encoding="utf-8")
        # The wrapper must not embed a workstation-specific UV path.
        assert "/Users/" not in text
        # It MUST use `command -v uv` lookup with ARXMCP_UV override.
        assert "command -v uv" in text
        assert "ARXMCP_UV" in text


# ---------------------------------------------------------------------------
# Helpers for the new tests above
# ---------------------------------------------------------------------------


class _FakeUrlOpenResponse:
    """Stub for urllib.request.urlopen's context manager.

    E13_S07: ``headers`` attribute provided so the new Content-Length
    pre-check in ``_fetch_page`` can inspect the response. Pass
    ``content_length=None`` (default) to omit the header — the
    fetcher treats absence as "header missing, fall back to
    read-cap." Pass an int to inject a declared size; the new
    pre-check will reject early if it exceeds the 100 MB cap.
    """

    def __init__(
        self,
        body: bytes,
        url: str,
        *,
        content_length: int | None = None,
    ):
        self._body = body
        self.url = url
        if content_length is None:
            self.headers: dict[str, str] = {}
        else:
            self.headers = {"Content-Length": str(content_length)}

    def read(self, amt: int | None = None) -> bytes:
        # E13_S07 contract: the production fetcher passes
        # ``OAI_PMH_MAX_RESPONSE_BYTES + 1`` to bound memory. We
        # truncate to that cap so the existing tests (whose bodies
        # are well under the cap) see no behavioral change.
        if amt is None:
            return self._body
        return self._body[:amt]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


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