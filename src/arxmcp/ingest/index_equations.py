"""Equation tree-JSON indexer (E10_S03).

Walks every row in the ``equations`` LanceDB table whose ``mathml``
column is populated and whose ``mathml_tree_json`` column is NULL,
parses the MathML into a :class:`zss.Node` tree, serializes the tree
to JSON, and writes the result back to the table.

**Second step of two.** Bulk ingest and the OAI delta extract each
paper's equations as they write its chunks
(:mod:`arxmcp.ingest.extract_equations`), then run this indexer once at the
end of the run, under the same dataset write lock.

**Idempotent per row.** Re-running the indexer on a table whose
trees the running normalizer wrote is a no-op.

**Concurrency.** Like the definitions indexer in
:mod:`arxmcp.ingest.index_definitions`, concurrent invocations against the same
LanceDB table could interleave delete/insert pairs in ways that
duplicate or drop rows, so :func:`index_equation_trees` runs under the
dataset write lock (:mod:`arxmcp.corpus.write_lock`) and a second writer is
refused.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pyarrow as pa

from arxmcp.corpus import (
    EQUATIONS_SCHEMA_V1,
    EQUATIONS_TABLE_NAME,
    LANCE_STORAGE_OPTIONS,
    add_missing_columns,
    exits_when_write_locked,
    holds_dataset_write_lock,
)
from arxmcp.ingest.mathml_tree import (
    MATHML_TREE_NORMALIZER_VERSION,
    parse_mathml_to_tree,
    tree_to_json,
)

logger = logging.getLogger(__name__)


def open_or_create_equations_table(lancedb_path: str | Path) -> Any:
    """Open the ``equations`` table, creating it on first use, and add
    any column :data:`EQUATIONS_SCHEMA_V1` has that it lacks.

    Returns a LanceDB ``Table`` handle. Mirrors the resilience
    pattern used by ``src/arxmcp/ingest/index_definitions.py``: try
    ``open_table`` first and fall through to ``create_table`` on the
    well-defined ValueError LanceDB raises for "table does not
    exist". This sidesteps the deprecation warning attached to
    ``table_names()`` and the paginated-wrapper return type of
    ``list_tables()`` on the pinned LanceDB version.
    """
    import lancedb

    resolved = Path(lancedb_path).resolve()
    if not resolved.exists():
        raise FileNotFoundError(
            f"lancedb_path does not exist: {resolved}; "
            f"run the chunks/embedder ingest first."
        )

    db = lancedb.connect(str(resolved))
    try:
        table = db.open_table(EQUATIONS_TABLE_NAME)
    except (ValueError, FileNotFoundError):
        # storage_options pins the on-disk Lance format (m2). See
        # arxmcp.corpus.schema.LANCE_STORAGE_OPTIONS for the rationale.
        return db.create_table(
            EQUATIONS_TABLE_NAME,
            schema=EQUATIONS_SCHEMA_V1,
            storage_options=LANCE_STORAGE_OPTIONS,
        )
    # Every caller writes the table under the dataset write lock.
    add_missing_columns(table, EQUATIONS_SCHEMA_V1, EQUATIONS_TABLE_NAME)
    return table


@holds_dataset_write_lock("lancedb_path")
def index_equation_trees(
    lancedb_path: str | Path, *, rebuild: bool = False,
) -> dict[str, int]:
    """Build ``mathml_tree_json`` for every row with a ``mathml``
    payload whose tree is missing or was written by another normalizer.

    A stored tree is only comparable to a query tree built by the same
    normalizer, so each row records the
    :data:`MATHML_TREE_NORMALIZER_VERSION` that wrote its tree in
    ``normalizer_version``, and a row whose version differs from the
    running one (an older tree, or one from before the column existed)
    is rebuilt. After a normalizer change a plain re-run brings the table
    in line. With ``rebuild=True``, every row's tree is recomputed.

    Returns a counts dict ``{processed, updated, skipped, failed}``
    so the caller (ops tooling or tests) can verify what landed. A
    dataset with no ``equations`` table has nothing to index: every
    count is 0 and no table is created.

    On a parse failure the row is left untouched and the failure is
    logged at WARNING. This lets a hand-crafted bad fixture surface
    in test logs without killing the whole indexer pass.
    """
    counts = {"processed": 0, "updated": 0, "skipped": 0, "failed": 0}
    if not (Path(lancedb_path) / f"{EQUATIONS_TABLE_NAME}.lance").is_dir():
        return counts
    table = open_or_create_equations_table(lancedb_path)
    arrow = table.to_arrow()

    if arrow.num_rows == 0:
        return counts

    logger.info(
        "indexing equation trees with normalizer v%d (%d rows)",
        MATHML_TREE_NORMALIZER_VERSION,
        arrow.num_rows,
    )
    rows = arrow.to_pylist()
    new_rows: list[dict[str, Any]] = []
    for row in rows:
        counts["processed"] += 1
        mathml = row.get("mathml")
        if not mathml:
            counts["skipped"] += 1
            continue
        current = (
            row.get("mathml_tree_json")
            and row.get("normalizer_version") == MATHML_TREE_NORMALIZER_VERSION
        )
        if current and not rebuild:
            counts["skipped"] += 1
            continue
        try:
            tree = parse_mathml_to_tree(mathml)
        except ValueError as exc:
            logger.warning(
                "skip equation_id=%s; MathML parse failed: %s",
                row.get("equation_id"), exc,
            )
            counts["failed"] += 1
            continue
        row["mathml_tree_json"] = tree_to_json(tree)
        row["normalizer_version"] = MATHML_TREE_NORMALIZER_VERSION
        new_rows.append(row)
        counts["updated"] += 1

    if not new_rows:
        return counts

    # LanceDB's merge_insert on the primary key updates the matched
    # rows in place and leaves untouched rows alone. ``equation_id``
    # is the natural primary key per the design constitution.
    #
    # F6 (E10_S03 critique) — build the update Arrow table from the
    # LIVE table schema rather than the hardcoded
    # ``EQUATIONS_SCHEMA_V1`` constant. This way a future
    # ``EQUATIONS_SCHEMA_V2`` that adds a column does not silently
    # drop the new column when the indexer re-runs against a
    # v1-on-disk table (or raise a schema-mismatch error on
    # ``merge_insert``). The hardcoded constant stays the source of
    # truth at ``open_or_create_equations_table`` (table creation
    # time) but read paths follow the table itself.
    update_table = pa.Table.from_pylist(new_rows, schema=table.schema)
    (
        table.merge_insert("equation_id")
        .when_matched_update_all()
        .when_not_matched_insert_all()
        .execute(update_table)
    )

    logger.info(
        "indexed equation trees: processed=%d updated=%d skipped=%d failed=%d",
        counts["processed"], counts["updated"],
        counts["skipped"], counts["failed"],
    )
    return counts



@exits_when_write_locked
def _cli(argv: list[str]) -> int:
    import argparse

    from arxmcp.corpus import DEFAULT_LANCEDB_PATH

    parser = argparse.ArgumentParser(
        prog="python -m arxmcp.ingest.index_equations",
        description="Build MathML trees for the equations table.",
    )
    parser.add_argument(
        "--lancedb-path", default=str(DEFAULT_LANCEDB_PATH),
        help="LanceDB dataset holding the equations table",
    )
    parser.add_argument(
        "--rebuild", action="store_true",
        help="recompute every tree, not only missing ones and ones "
        "another tree normalizer wrote",
    )
    args = parser.parse_args(argv)
    if not Path(args.lancedb_path).is_dir():
        parser.error(f"no LanceDB dataset at {args.lancedb_path}")
    counts = index_equation_trees(args.lancedb_path, rebuild=args.rebuild)
    print(" ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(_cli(sys.argv[1:]))

__all__ = [
    "index_equation_trees",
    "open_or_create_equations_table",
]
