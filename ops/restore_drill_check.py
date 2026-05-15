"""Restore-drill smoke check (E11_S05).

Verifies that a restic-restored corpus is structurally intact:

- The LanceDB chunks table opens and has > 0 rows.
- The Kùzu citation graph opens (best-effort — Kùzu directory
  is optional in some test paths).

Lightweight by design — does NOT start the full MCP server.
The watchdog (E11_S04) is the retrieval-quality check; this
drill is a "is the data even readable?" check, run once before
the 200K cutover.

On success, writes the pass sentinel JSON to ``--flag-path``
that ``ops/cutover.py``'s Criterion 4 reads.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _utc_iso() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def smoke_check_lancedb(restore_path: Path) -> int:
    """Open the restored LanceDB and return chunk row count.

    Raises ``RuntimeError`` if the directory is missing, the
    chunks table can't be opened, or the row count is 0.
    """
    lancedb_path = restore_path / "var" / "arxmcp" / "index" / "lancedb"
    if not lancedb_path.is_dir():
        raise RuntimeError(
            f"restored LanceDB missing at {lancedb_path}"
        )
    from server.corpus import (  # noqa: PLC0415
        open_chunks_table,
        read_corpus_version,
    )

    info = read_corpus_version(lancedb_path=lancedb_path)
    if info is None:
        raise RuntimeError(
            f"restored LanceDB has no corpus-version.json at "
            f"{lancedb_path}"
        )
    tbl = open_chunks_table(
        lancedb_path=lancedb_path, version=info.version
    )
    row_count = tbl.count_rows()
    if row_count == 0:
        raise RuntimeError(
            f"restored LanceDB chunks table at {lancedb_path} "
            f"has zero rows"
        )
    logger.info(
        "restore_drill: LanceDB ok (%d rows at v%d)",
        row_count, info.version,
    )
    return row_count


def smoke_check_kuzu(restore_path: Path) -> int | None:
    """Open the restored Kùzu graph and return paper count.

    Returns ``None`` if the Kùzu directory is absent (acceptable
    — some restore paths may exclude the citation graph). Raises
    ``RuntimeError`` if the directory exists but is unreadable.
    """
    kuzu_path = restore_path / "var" / "arxmcp" / "index" / "kuzu"
    if not kuzu_path.is_dir():
        logger.info(
            "restore_drill: Kùzu directory absent at %s — skipping",
            kuzu_path,
        )
        return None
    try:
        import kuzu  # noqa: PLC0415
    except ImportError:
        logger.warning("restore_drill: kuzu module not importable")
        return None
    try:
        db = kuzu.Database(str(kuzu_path))
        conn = kuzu.Connection(db)
        # Restored DB may be empty; we only require it to open.
        result = conn.execute("MATCH (p:Paper) RETURN count(p) AS c")
        paper_count = 0
        while result.has_next():
            row = result.get_next()
            paper_count = int(row[0])
    except Exception as exc:  # noqa: BLE001 — integrity probe
        raise RuntimeError(
            f"restored Kùzu DB at {kuzu_path} is unreadable: {exc}"
        ) from exc
    logger.info(
        "restore_drill: Kùzu ok (%d papers)", paper_count
    )
    return paper_count


def write_pass_sentinel(
    *,
    flag_path: Path,
    snapshot_id: str,
    restore_path: Path,
    lancedb_row_count: int,
    kuzu_paper_count: int | None,
) -> None:
    """Atomically write the restore-drill-passed.flag."""
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kuzu_paper_count": kuzu_paper_count,
        "lancedb_row_count": lancedb_row_count,
        "restore_path": str(restore_path),
        "restored_at": _utc_iso(),
        "smoke_check": "passed",
        "snapshot_id": snapshot_id,
    }
    tmp = flag_path.with_suffix(flag_path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(flag_path)


def run_check(
    *,
    restore_path: Path,
    snapshot_id: str,
    flag_path: Path,
) -> int:
    """End-to-end drill. Returns process exit code."""
    try:
        rows = smoke_check_lancedb(restore_path)
        papers = smoke_check_kuzu(restore_path)
    except RuntimeError as exc:
        logger.error("restore_drill: %s", exc)
        return 1
    write_pass_sentinel(
        flag_path=flag_path,
        snapshot_id=snapshot_id,
        restore_path=restore_path,
        lancedb_row_count=rows,
        kuzu_paper_count=papers,
    )
    print(
        f"restore drill PASSED: lancedb_rows={rows} "
        f"kuzu_papers={papers if papers is not None else '-'}"
    )
    return 0


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="arXMCP restore-drill smoke check (E11_S05).",
    )
    parser.add_argument(
        "--restore-path",
        required=True,
        type=Path,
        help="Root path under which restic restored the snapshot.",
    )
    parser.add_argument(
        "--snapshot-id",
        required=True,
        help="restic snapshot short_id (for the sentinel JSON).",
    )
    parser.add_argument(
        "--flag-path",
        required=True,
        type=Path,
        help="Where to write the restore-drill-passed.flag.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return run_check(
        restore_path=args.restore_path,
        snapshot_id=args.snapshot_id,
        flag_path=args.flag_path,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_cli(sys.argv[1:]))


__all__ = [
    "run_check",
    "smoke_check_kuzu",
    "smoke_check_lancedb",
    "write_pass_sentinel",
]
