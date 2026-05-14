"""Equation tree-JSON indexer (E10_S03).

Walks every row in the ``equations`` LanceDB table whose ``mathml``
column is populated and whose ``mathml_tree_json`` column is NULL,
parses the MathML into a :class:`zss.Node` tree, serializes the tree
to JSON, and writes the result back to the table.

**v1 scope reminder.** The brief frames E10_S03 as "build the
equation similarity index"; in practice the corpus-level equation
atom extraction step (LaTeXML HTML → ``equations`` rows) is deferred
to a future milestone. At v1 this indexer is mainly exercised by
tests and by hand-seeded fixtures — once a future milestone lands
the extractor, this module is the second step of the chain and
needs no changes.

**Idempotent per row.** Re-running the indexer on a table that
already has ``mathml_tree_json`` populated is a no-op; the WHERE
predicate filters rows that need processing.

**Concurrency.** Like the definitions indexer in
:mod:`ingest.index_definitions`, this writer assumes a
**single-writer contract** — concurrent invocations against the same
LanceDB table can interleave delete/insert pairs in ways that
duplicate or drop rows. The production ingest driver landing in E11
must serialize the equation-tree population step.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pyarrow as pa

from ingest.schema import EQUATIONS_SCHEMA_V1, EQUATIONS_TABLE_NAME
from server.retrieval.equations import parse_mathml_to_tree, tree_to_json

logger = logging.getLogger(__name__)


def open_or_create_equations_table(lancedb_path: str | Path) -> Any:
    """Open the ``equations`` table, creating it on first use.

    Returns a LanceDB ``Table`` handle. Mirrors the resilience
    pattern used by ``ingest/index_definitions.py``: try
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
        return db.open_table(EQUATIONS_TABLE_NAME)
    except (ValueError, FileNotFoundError):
        return db.create_table(
            EQUATIONS_TABLE_NAME,
            schema=EQUATIONS_SCHEMA_V1,
        )


def index_equation_trees(lancedb_path: str | Path) -> dict[str, int]:
    """Populate ``mathml_tree_json`` on every row that has a
    ``mathml`` payload and a NULL ``mathml_tree_json``.

    Returns a counts dict ``{processed, updated, skipped, failed}``
    so the caller (ops tooling or tests) can verify what landed.

    On a parse failure the row is left untouched and the failure is
    logged at WARNING. This lets a hand-crafted bad fixture surface
    in test logs without killing the whole indexer pass.
    """
    table = open_or_create_equations_table(lancedb_path)
    arrow = table.to_arrow()
    counts = {"processed": 0, "updated": 0, "skipped": 0, "failed": 0}

    if arrow.num_rows == 0:
        return counts

    rows = arrow.to_pylist()
    new_rows: list[dict[str, Any]] = []
    for row in rows:
        counts["processed"] += 1
        mathml = row.get("mathml")
        if not mathml:
            counts["skipped"] += 1
            continue
        if row.get("mathml_tree_json"):
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


__all__ = [
    "index_equation_trees",
    "open_or_create_equations_table",
]
