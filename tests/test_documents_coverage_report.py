"""Tests for ``tools.documents_coverage_report`` (source-truth-m1).

Seeds per-notebook ``documents.db`` files under ``tmp_path`` and drives
the report through its test seams. Covers per-``license_status`` +
per-id-shape counts, the >20%-unknown owner escalation on
``bridgeland-stability`` (non-zero exit + loud stderr), the OWNER
DECISION C invariant that ``not-allowlisted-open`` is reported EQUALLY
prominently but NEVER folds into the escalation, and the missing-registry
loud fail state.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from server.documents_store import (
    DOCUMENTS_DB_FILENAME,
    DocumentRecord,
    DocumentsStore,
)
from tools import documents_coverage_report

BRIDGELAND = "bridgeland-stability"


def _rec(
    work_id: str,
    license_status: str,
    *,
    arxiv_version: str = "",
    status: str = "active",
) -> DocumentRecord:
    return DocumentRecord(
        work_id=work_id,
        arxiv_version=arxiv_version,
        raw_source_sha256=None,
        raw_source_status="unavailable",
        parse_artifact_sha256="b" * 64,
        chunker_version="v1.1",
        parser_used=None,
        latexml_version=None,
        fetched_at="2026-07-12T00:00:00+00:00",
        license_uri=None,
        license_status=license_status,
        status=status,
    )


def _seed(base: Path, slug: str, records: list[DocumentRecord]) -> None:
    db_path = base / slug / DOCUMENTS_DB_FILENAME

    async def _w() -> None:
        store = await DocumentsStore.open(db_path)
        try:
            await store.upsert_records(records)
        finally:
            await store.close()

    asyncio.run(_w())


def _run(base: Path):
    return documents_coverage_report.run(
        base=base, notebooks=(BRIDGELAND,), escalation_notebook=BRIDGELAND,
    )


class TestCounts:
    def test_per_status_and_id_shape_counts(self, tmp_path, capsys):
        base = tmp_path / "notebooks"
        _seed(base, BRIDGELAND, [
            _rec("2401.00001", "eligible"),
            _rec("2401.00002", "eligible"),
            _rec("math/0212237", "not-allowlisted-open"),
            _rec("alg-geom/9410026", "unknown"),
            _rec("2006.10956", "not-allowlisted-open", arxiv_version="v1"),
        ])

        exit_code = _run(base)
        out = capsys.readouterr().out

        # 1 of 5 unknown = 20.0%, NOT strictly greater than the 20% gate.
        assert exit_code == 0
        assert "total=5" in out
        assert "eligible=2" in out
        assert "not-allowlisted-open=2" in out
        assert "unknown=1" in out
        assert "new-style=3" in out
        assert "old-style=2" in out
        assert "versioned=1" in out


class TestEscalation:
    def test_within_threshold_exits_zero(self, tmp_path, capsys):
        base = tmp_path / "notebooks"
        _seed(base, BRIDGELAND, (
            [_rec(f"2401.{i:05d}", "eligible") for i in range(8)]
            + [_rec("2401.10000", "not-allowlisted-open")]
            + [_rec("2401.10001", "unknown")]
        ))

        exit_code = _run(base)
        captured = capsys.readouterr()

        assert exit_code == 0  # unknown rate 10% <= 20%
        assert "OK" in captured.out
        # not-allowlisted-open reported alongside, not hidden.
        assert "not-allowlisted-open=1" in captured.out

    def test_over_threshold_escalates_loudly(self, tmp_path, capsys):
        base = tmp_path / "notebooks"
        _seed(base, BRIDGELAND, (
            [_rec(f"2401.{i:05d}", "eligible") for i in range(6)]
            + [_rec(f"2401.9{i:04d}", "unknown") for i in range(4)]
        ))

        exit_code = _run(base)
        captured = capsys.readouterr()

        assert exit_code == 1  # unknown rate 40% > 20%
        assert "ESCALATION" in captured.err
        assert "40.0%" in captured.err

    def test_not_allowlisted_open_does_not_trigger_escalation(
        self, tmp_path, capsys,
    ):
        """OWNER DECISION C: the >20% gate is on ``unknown`` ALONE. A
        notebook that is mostly ``not-allowlisted-open`` (real licenses,
        allowlist decision pending) with a LOW unknown rate must NOT
        escalate — but its not-allowlisted-open count is still reported
        prominently."""
        base = tmp_path / "notebooks"
        _seed(base, BRIDGELAND, (
            [_rec(f"2401.{i:05d}", "not-allowlisted-open") for i in range(7)]
            + [_rec("2401.20000", "eligible"), _rec("2401.20001", "eligible")]
            + [_rec("2401.20002", "unknown")]
        ))

        exit_code = _run(base)
        captured = capsys.readouterr()

        assert exit_code == 0  # unknown only 10%, despite 70% not-allowlisted
        assert "ESCALATION" not in captured.err
        assert "not-allowlisted-open=7" in captured.out

    def test_missing_registry_is_a_loud_fail_state(self, tmp_path, capsys):
        """No documents.db for the escalation notebook: the gate cannot
        be measured -> loud stderr + non-zero exit (pre-cutover fail)."""
        base = tmp_path / "notebooks"
        # nothing seeded

        exit_code = _run(base)
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "NOT FOUND" in captured.out
        assert "cannot measure" in captured.err


class TestMultiNotebook:
    def test_both_notebooks_rendered(self, tmp_path, capsys):
        base = tmp_path / "notebooks"
        _seed(base, BRIDGELAND, [_rec("2401.00001", "eligible")])
        _seed(base, "fourier-duality", [_rec("2401.00002", "unknown")])

        exit_code = documents_coverage_report.run(base=base)
        out = capsys.readouterr().out

        assert exit_code == 0  # bridgeland 0% unknown
        assert "=== bridgeland-stability ===" in out
        assert "=== fourier-duality ===" in out
