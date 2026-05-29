"""corpus-integrity-observability-e3 — writer tests for
:func:`ingest.ingest_summary.write_ingest_summary`.

Coverage:
- happy path: file written with v1 schema, all fields present
- missing ops_dir: directory is auto-created
- atomicity: same-directory .tmp file; no leftover .tmp after success
"""

from __future__ import annotations

import json
from pathlib import Path

from ingest.ingest_summary import write_ingest_summary


class TestWriteIngestSummary:
    """Happy-path and structural tests for the atomic writer."""

    def _write(self, ops_dir: Path, **overrides) -> dict:
        """Call write_ingest_summary with representative values + any overrides."""
        kwargs = dict(
            papers_processed=52,
            papers_succeeded=50,
            papers_failed=2,
            chunks_written_this_run=4820,
            total_rows_after_commit=10298,
            elapsed_seconds=312.4,
        )
        kwargs.update(overrides)
        write_ingest_summary(ops_dir, "bulk_ingest", **kwargs)
        return json.loads((ops_dir / "ingest-summary.json").read_text(encoding="utf-8"))

    def test_happy_path_file_written(self, tmp_path: Path):
        sentinel = tmp_path / "ingest-summary.json"
        assert not sentinel.exists()
        self._write(tmp_path)
        assert sentinel.is_file()

    def test_v1_schema_version(self, tmp_path: Path):
        payload = self._write(tmp_path)
        assert payload["schema_version"] == 1

    def test_all_required_fields_present(self, tmp_path: Path):
        payload = self._write(tmp_path)
        for field in (
            "schema_version",
            "driver",
            "finished_at",
            "elapsed_seconds",
            "papers_processed",
            "papers_succeeded",
            "papers_failed",
            "chunks_written_this_run",
            "total_rows_after_commit",
        ):
            assert field in payload, f"missing field: {field}"

    def test_field_values_match_input(self, tmp_path: Path):
        payload = self._write(tmp_path)
        assert payload["driver"] == "bulk_ingest"
        assert payload["papers_processed"] == 52
        assert payload["papers_succeeded"] == 50
        assert payload["papers_failed"] == 2
        assert payload["chunks_written_this_run"] == 4820
        assert payload["total_rows_after_commit"] == 10298
        assert abs(payload["elapsed_seconds"] - 312.4) < 0.1

    def test_finished_at_is_iso8601_utc(self, tmp_path: Path):
        payload = self._write(tmp_path)
        finished_at = payload["finished_at"]
        assert isinstance(finished_at, str)
        # Must be parseable and end with 'Z'
        assert finished_at.endswith("Z"), (
            f"finished_at should end with 'Z': {finished_at!r}"
        )
        from datetime import datetime  # noqa: PLC0415
        dt = datetime.fromisoformat(finished_at)
        assert dt.tzinfo is not None

    def test_delta_driver_name(self, tmp_path: Path):
        write_ingest_summary(
            tmp_path,
            "oai_delta",
            papers_processed=10,
            papers_succeeded=9,
            papers_failed=1,
            chunks_written_this_run=890,
            total_rows_after_commit=5000,
            elapsed_seconds=45.0,
        )
        payload = json.loads((tmp_path / "ingest-summary.json").read_text())
        assert payload["driver"] == "oai_delta"


class TestWriteIngestSummaryMissingDir:
    """The writer must create ops_dir (including parents) if absent."""

    def test_creates_ops_dir_if_missing(self, tmp_path: Path):
        ops_dir = tmp_path / "var" / "arxmcp" / "ops"
        assert not ops_dir.exists()
        write_ingest_summary(
            ops_dir,
            "bulk_ingest",
            papers_processed=1,
            papers_succeeded=1,
            papers_failed=0,
            chunks_written_this_run=10,
            total_rows_after_commit=10,
            elapsed_seconds=1.0,
        )
        assert (ops_dir / "ingest-summary.json").is_file()


class TestWriteIngestSummaryAtomicity:
    """FM-1: same-directory .tmp + rename atomicity contract."""

    def test_tmp_is_in_same_directory(self, tmp_path: Path, monkeypatch):
        """The temp file must be created in the same directory as the target
        (not /tmp or a cross-filesystem location) so os.replace is atomic
        on a single filesystem."""
        seen_tmp: list[Path] = []
        original_write_text = Path.write_text

        def _spy_write_text(self_path, *args, **kwargs):
            if self_path.suffix == ".tmp":
                seen_tmp.append(self_path)
            return original_write_text(self_path, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", _spy_write_text)
        write_ingest_summary(
            tmp_path,
            "bulk_ingest",
            papers_processed=1,
            papers_succeeded=1,
            papers_failed=0,
            chunks_written_this_run=5,
            total_rows_after_commit=5,
            elapsed_seconds=0.5,
        )
        assert len(seen_tmp) == 1, "expected exactly one .tmp write"
        assert seen_tmp[0].parent == tmp_path, (
            f"tmp file {seen_tmp[0]} is NOT in the same directory as "
            f"the target {tmp_path} — cross-fs rename may not be atomic"
        )

    def test_no_leftover_tmp_after_success(self, tmp_path: Path):
        """After a successful write there must be no .tmp file left over."""
        write_ingest_summary(
            tmp_path,
            "bulk_ingest",
            papers_processed=1,
            papers_succeeded=1,
            papers_failed=0,
            chunks_written_this_run=5,
            total_rows_after_commit=5,
            elapsed_seconds=0.5,
        )
        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == [], f"leftover tmp files: {leftovers}"
