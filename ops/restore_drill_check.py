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


def _locate_lancedb_root(restore_path: Path) -> Path | None:
    """Find the restored LanceDB root by searching for
    ``corpus-version.json`` under ``restore_path``.

    Closes adversary F1: restic preserves absolute source
    paths under ``--target``. A backup of
    ``/opt/arxmcp/var/arxmcp/index/lancedb`` restored to
    ``/tmp/arxmcp-restore-drill/`` lands at
    ``/tmp/arxmcp-restore-drill/opt/arxmcp/var/arxmcp/index/lancedb``.
    Hardcoding ``restore_path / "var" / "arxmcp" / ...`` misses
    this entirely. Searching for the marker is path-prefix-
    agnostic.
    """
    marker = "corpus-version.json"
    # Prefer the shallowest match (closest to restore_path) in
    # case there are multiple corpora under the snapshot.
    candidates = sorted(
        restore_path.rglob(marker),
        key=lambda p: len(p.parts),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.parent
    return None


def _locate_kuzu_root(restore_path: Path) -> Path | None:
    """Find the restored Kùzu graph by searching for the
    canonical ``var/arxmcp/index/kuzu`` segment under
    ``restore_path``. Returns ``None`` if no Kùzu directory
    was captured.

    Closes adversary F1 (Kùzu half).
    """
    # Kùzu doesn't have a single canonical marker file, so we
    # look for the directory name. Filter to directories whose
    # immediate parent is the expected ``index/`` so we don't
    # match arbitrary "kuzu" directories the operator may have
    # added under the snapshot.
    for entry in restore_path.rglob("kuzu"):
        if entry.is_dir() and entry.parent.name == "index":
            return entry
    return None


def smoke_check_lancedb(restore_path: Path) -> int:
    """Open the restored LanceDB and return chunk row count.

    Raises ``RuntimeError`` if the LanceDB is missing, the
    chunks table can't be opened, or the row count is 0.
    """
    lancedb_path = _locate_lancedb_root(restore_path)
    if lancedb_path is None:
        raise RuntimeError(
            f"restored LanceDB missing under {restore_path} "
            f"(no corpus-version.json found via rglob)"
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
        "restore_drill: LanceDB ok (%d rows at v%d) at %s",
        row_count, info.version, lancedb_path,
    )
    return row_count


def smoke_check_kuzu(restore_path: Path) -> int | None:
    """Open the restored Kùzu graph and return paper count.

    Returns ``None`` if the Kùzu directory is absent (acceptable
    — some restore paths may exclude the citation graph). Raises
    ``RuntimeError`` if the directory exists but is unreadable.

    Closes adversary F1 (Kùzu half): finds the Kùzu directory
    via rglob rather than hardcoding the path prefix.
    """
    kuzu_path = _locate_kuzu_root(restore_path)
    if kuzu_path is None:
        logger.info(
            "restore_drill: Kùzu directory absent under %s — skipping",
            restore_path,
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


def _locate_notebooks_db(restore_path: Path) -> Path | None:
    """Find the restored ``notebooks.db`` via rglob.

    notebook-ops-hardening-m1. Same path-prefix-agnostic discovery as
    ``_locate_lancedb_root`` (closes adversary F1 from E11_S05): restic
    preserves absolute source paths under ``--target``, so a backup of
    ``/opt/arxmcp/var/arxmcp/cache/notebooks.db`` restored to
    ``/tmp/...`` lands at ``/tmp/.../opt/arxmcp/var/arxmcp/cache/notebooks.db``.
    Hardcoding the prefix would miss it. Prefer the shallowest match.
    """
    candidates = sorted(
        restore_path.rglob("notebooks.db"),
        key=lambda p: len(p.parts),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _under_notebooks_subtree(p: Path) -> bool:
    """True iff ``p`` lives under a canonical ``.../arxmcp/notebooks/``
    segment.

    notebook-ops-hardening-m1 F3: anchor to the ``arxmcp`` + ``notebooks``
    ordered pair rather than matching ANY path component literally equal to
    ``notebooks`` (which would over-count a corpus PDF that happens to sit
    under some unrelated ``notebooks`` directory). Mirrors the
    ``_locate_kuzu_root`` discipline (parent.name == "index").
    """
    parts = p.parts
    return any(
        parts[i] == "notebooks" and parts[i - 1] == "arxmcp"
        for i in range(1, len(parts))
    )


def smoke_check_notebooks(restore_path: Path) -> tuple[bool, int]:
    """Verify restored notebook metadata + uploaded PDFs.

    notebook-ops-hardening-m1. Returns
    ``(notebooks_db_found, notebook_pdf_count)``.

    ``notebooks.db`` absence is ACCEPTABLE (a pre-m1 snapshot taken before
    notebooks entered backup scope, or a fresh install with no notebooks)
    and returns ``(False, <pdf count>)`` — it does NOT fail the drill. A
    ``notebooks.db`` that EXISTS but fails ``PRAGMA integrity_check`` raises
    ``RuntimeError`` (a corrupt restore is a real backup failure).
    """
    import sqlite3  # noqa: PLC0415

    db_path = _locate_notebooks_db(restore_path)
    # Count uploaded PDFs under a restored ``.../arxmcp/notebooks/`` subtree
    # (covers both ``pdf-deferred/`` and ``pdfs/`` layouts).
    pdf_count = sum(
        1
        for p in restore_path.rglob("*.pdf")
        if p.is_file() and _under_notebooks_subtree(p)
    )
    if db_path is None:
        logger.info(
            "restore_drill: notebooks.db absent under %s — skipping "
            "(notebook pdfs=%d)",
            restore_path, pdf_count,
        )
        return (False, pdf_count)
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        # A garbage/truncated file raises "file is not a database" rather
        # than returning a non-ok row. Treat any sqlite error as a failed
        # integrity check so run_check (which catches RuntimeError) reports
        # it as a drill failure rather than crashing.
        raise RuntimeError(
            f"restored notebooks.db at {db_path} failed "
            f"PRAGMA integrity_check (sqlite error): {exc}"
        ) from exc
    if row is None or row[0] != "ok":
        raise RuntimeError(
            f"restored notebooks.db at {db_path} failed "
            f"PRAGMA integrity_check: {row}"
        )
    logger.info(
        "restore_drill: notebooks.db ok at %s (notebook pdfs=%d)",
        db_path, pdf_count,
    )
    return (True, pdf_count)


def write_pass_sentinel(
    *,
    flag_path: Path,
    snapshot_id: str,
    restore_path: Path,
    lancedb_row_count: int,
    kuzu_paper_count: int | None,
    notebooks_db_found: bool = False,
    notebook_pdf_count: int = 0,
) -> None:
    """Atomically write the restore-drill-passed.flag."""
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kuzu_paper_count": kuzu_paper_count,
        "lancedb_row_count": lancedb_row_count,
        "notebook_pdf_count": notebook_pdf_count,
        "notebooks_db_found": notebooks_db_found,
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
        nb_found, nb_pdfs = smoke_check_notebooks(restore_path)
    except RuntimeError as exc:
        logger.error("restore_drill: %s", exc)
        return 1
    write_pass_sentinel(
        flag_path=flag_path,
        snapshot_id=snapshot_id,
        restore_path=restore_path,
        lancedb_row_count=rows,
        kuzu_paper_count=papers,
        notebooks_db_found=nb_found,
        notebook_pdf_count=nb_pdfs,
    )
    print(
        f"restore drill PASSED: lancedb_rows={rows} "
        f"kuzu_papers={papers if papers is not None else '-'} "
        f"notebooks_db={'yes' if nb_found else 'no'} "
        f"notebook_pdfs={nb_pdfs}"
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
    "smoke_check_notebooks",
    "write_pass_sentinel",
]
