"""Per-paper theorem-name indexer (E10_S02).

Walks the LanceDB chunks table, picks rows where ``theorem_name``
is non-null, builds :class:`TheoremRow` records keyed by a
content-addressable ``dedup_key``, and persists them via the
:class:`TheoremNamesStore` SQLite wrapper.

The dedup key — ``sha256(paper_id + theorem_name + section_path_json)[:16]``
— ensures that "Lemma 3.4" in paper A and "Lemma 3.4" in paper B
get distinct rows (the design constitution's dedup contract).
Re-running the indexer for a paper that already has entries
performs UPSERT (same key → row replaced; new keys → row appended)
plus a stale-row sweep via :meth:`delete_paper` so a paper that
goes from 12 to 8 theorems does not leave 4 orphan rows behind.

**v1 confidence = 1.0** for every chunker-emitted row. The chunker
only populates ``theorem_name`` when it found an explicit ``(Name)``
parenthetical in the heading — that's a high-confidence signal. A
future milestone may add lower-confidence body-text extraction.

**Concurrency.** Single-writer-per-table contract (synthesis D10).
Callers MUST serialize concurrent invocations of
:func:`index_theorem_names_for_paper` against the same SQLite
database; SQLite WAL tolerates concurrent readers but serializes
writers, and two interleaved per-paper passes can race the
delete + insert pair.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from server.theorem_names_store import (
    TheoremNamesStore,
    TheoremRow,
    dedup_key,
    serialize_section_path,
)

logger = logging.getLogger(__name__)


#: Confidence assigned to every row emitted by this indexer at v1.
#: The chunker only fills ``theorem_name`` when it found a
#: parenthetical in the heading, which is a high-confidence signal.
DEFAULT_CONFIDENCE: float = 1.0


def build_rows_from_arrow(
    chunks_arrow: Any, paper_id: str
) -> list[TheoremRow]:
    """Build the rows for one paper from a paper-filtered Arrow table.

    Caller is responsible for pre-filtering ``chunks_arrow`` to
    rows where ``paper_id`` matches (typically via LanceDB's
    ``search().where("paper_id = ?", ...).to_arrow()`` predicate
    push-down — see :func:`index_theorem_names_for_paper`). We
    defensively re-filter here so a stale or unfiltered table does
    not silently produce wrong-paper rows.

    Filters ``theorem_name IS NOT NULL`` and ``not isspace()``. The
    chunks table is the single source of truth for theorem names;
    we do NOT re-parse LaTeX here.
    """
    if not isinstance(paper_id, str) or not paper_id:
        raise ValueError(
            f"paper_id must be a non-empty string, got {paper_id!r}"
        )

    chunk_ids = chunks_arrow.column("chunk_id").to_pylist()
    paper_ids = chunks_arrow.column("paper_id").to_pylist()
    theorem_names = chunks_arrow.column("theorem_name").to_pylist()
    section_paths = chunks_arrow.column("section_path").to_pylist()

    rows: list[TheoremRow] = []
    for cid, pid, tname, spath in zip(
        chunk_ids, paper_ids, theorem_names, section_paths, strict=True
    ):
        if pid != paper_id:
            continue
        if tname is None or not isinstance(tname, str) or not tname.strip():
            continue
        sp_list = list(spath) if spath is not None else []
        sp_json = serialize_section_path(sp_list)
        rows.append(
            TheoremRow(
                dedup_key=dedup_key(paper_id, tname, sp_json),
                paper_id=paper_id,
                chunk_id=cid,
                theorem_name=tname,
                display_name=tname,
                section_path=sp_list,
                confidence=DEFAULT_CONFIDENCE,
            )
        )
    return rows


# Back-compat alias — same shape, kept for any external caller that
# imported the old name. New code should call ``build_rows_from_arrow``.
build_rows_from_chunks_for_paper = build_rows_from_arrow


async def index_theorem_names_for_paper(
    paper_id: str,
    chunks_table: Any,
    store: TheoremNamesStore,
) -> int:
    """Index every theorem-name chunk for one paper.

    Performs a per-paper sweep: delete any prior rows for
    ``paper_id``, then insert the freshly-built batch. Returns the
    number of rows written. A paper with zero theorem-name-bearing
    chunks produces zero writes (no error).

    **F2 (E10_S02 critique) close.** The previous implementation
    called ``chunks_table.to_arrow()`` (a full-table materialization)
    on EVERY invocation, then iterated all rows to filter by
    ``paper_id``. At Tier-4 (~50K chunks, ~200 papers) that's an
    N+1 read pattern. We now push the ``paper_id = '...'`` filter
    into the LanceDB scan via ``.search().where(..., prefilter=True)``
    so only the paper's chunks are materialized. The fallback to
    a full ``to_arrow()`` survives in tests that build a synthetic
    Arrow table without a LanceDB connection.
    """
    safe_filter = f"paper_id = '{paper_id}'"
    try:
        chunks_arrow = (
            chunks_table.search()
            .where(safe_filter, prefilter=True)
            .to_arrow()
        )
    except (AttributeError, TypeError):
        # Test fixtures (and any future caller) may pass a plain
        # Arrow table without the ``.search()`` method. Fall back
        # to materializing the whole table; ``build_rows_from_arrow``
        # re-applies the paper_id filter defensively.
        if hasattr(chunks_table, "to_arrow"):
            chunks_arrow = chunks_table.to_arrow()
        else:
            chunks_arrow = chunks_table
    rows = build_rows_from_arrow(chunks_arrow, paper_id)

    await store.delete_paper(paper_id)
    if not rows:
        logger.info(
            "indexed 0 theorem_names for paper_id=%s (no named theorems)",
            paper_id,
        )
        return 0
    n = await store.upsert_rows(rows)
    logger.info("indexed %d theorem_names for paper_id=%s", n, paper_id)
    return n


async def index_theorem_names_all_papers(
    chunks_table: Any,
    store: TheoremNamesStore,
) -> dict[str, int]:
    """Walk every distinct paper_id in the chunks table and index it.

    Returns a ``{paper_id: rows_written}`` map for ops logging.

    **F2 (E10_S02 critique) close.** Materialize the chunks table
    EXACTLY ONCE, group rows by paper_id in Python, and dispatch
    each group to ``build_rows_from_arrow`` + the SQLite store.
    The previous implementation called ``to_arrow()`` once per
    paper_id (N+1 reads); this version is O(1) full-table reads.
    """
    arrow = chunks_table.to_arrow()
    paper_ids = sorted(set(arrow.column("paper_id").to_pylist()))
    out: dict[str, int] = {}
    for pid in paper_ids:
        if not isinstance(pid, str):
            continue
        rows = build_rows_from_arrow(arrow, pid)
        await store.delete_paper(pid)
        if rows:
            await store.upsert_rows(rows)
        out[pid] = len(rows)
    return out


def default_db_path(lancedb_path: str | Path) -> Path:
    """Return the canonical on-disk path for the theorem-names DB.

    Sibling-of-sibling to the LanceDB dataset root:
    ``var/arxmcp/index/sqlite/theorem_names.db``. This keeps the
    project's ``var/`` tree organized — LanceDB indices live under
    ``index/lancedb/``, SQLite indices under ``index/sqlite/``.
    """
    return (
        Path(lancedb_path).resolve().parent / "sqlite" / "theorem_names.db"
    )


__all__ = [
    "DEFAULT_CONFIDENCE",
    "build_rows_from_chunks_for_paper",
    "default_db_path",
    "index_theorem_names_all_papers",
    "index_theorem_names_for_paper",
]
