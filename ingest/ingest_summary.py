"""Atomic writer for ``var/arxmcp/ops/ingest-summary.json`` (v1 schema).

Emitted by :func:`ingest.bulk_ingest.run_bulk_ingest` and
:func:`ingest.oai_delta.run_delta` after a successful run so the
MCP server's Prometheus scrape hook (:func:`server.health.refresh_sentinel_metrics`)
can expose last-run ingest metrics without polling the ingest process.

Schema v1 (all fields required):

.. code-block:: json

    {
      "schema_version": 1,
      "driver": "bulk_ingest",
      "finished_at": "2026-05-29T04:00:00Z",
      "elapsed_seconds": 312.4,
      "papers_processed": 52,
      "papers_succeeded": 50,
      "papers_failed": 2,
      "chunks_written_this_run": 4820,
      "total_rows_after_commit": 10298
    }

The write is POSIX-atomic (same-directory temp file + ``os.replace``),
mirroring :func:`ingest.oai_delta._write_state` exactly (FM-1 guard:
same-directory temp avoids cross-filesystem rename failures).
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path


def write_ingest_summary(
    ops_dir: Path,
    driver: str,
    *,
    papers_processed: int,
    papers_succeeded: int,
    papers_failed: int,
    chunks_written_this_run: int,
    total_rows_after_commit: int,
    elapsed_seconds: float,
) -> None:
    """Write ``ingest-summary.json`` atomically to ``ops_dir``.

    Uses the same-directory ``.tmp`` + ``tmp.replace(path)`` idiom
    (POSIX-atomic on a single filesystem; FM-1 from the e3 brief).

    Parameters
    ----------
    ops_dir:
        Directory that receives ``ingest-summary.json``.  Created
        (including parents) if it does not exist.
    driver:
        Human-readable driver name, e.g. ``"bulk_ingest"`` or
        ``"oai_delta"``.  Rides as a JSON field only; NOT exposed
        as a Prometheus label.
    papers_processed:
        Total papers the driver attempted (succeeded + failed).
    papers_succeeded:
        Papers that produced at least one chunk row.
    papers_failed:
        Papers that produced zero chunks (parse/embed failure).
    chunks_written_this_run:
        Sum of ``rows_inserted + rows_updated`` across all
        :class:`ingest.store.WriteStats` in this run.
    total_rows_after_commit:
        ``tbl.count_rows()`` as of the last write in this run.
    elapsed_seconds:
        Wall-clock seconds for the run.
    """
    ops_dir.mkdir(parents=True, exist_ok=True)
    path = ops_dir / "ingest-summary.json"
    finished_at = (
        datetime.datetime.now(datetime.UTC)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    payload = {
        "schema_version": 1,
        "driver": driver,
        "finished_at": finished_at,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "papers_processed": papers_processed,
        "papers_succeeded": papers_succeeded,
        "papers_failed": papers_failed,
        "chunks_written_this_run": chunks_written_this_run,
        "total_rows_after_commit": total_rows_after_commit,
    }
    # FM-1: same-directory temp ensures the rename is on the same
    # filesystem — identical to oai_delta._write_state (:216-224).
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
