"""Kùzu schema migration for the citation graph (E09_S01).

Idempotent migration that creates the ``papers`` node table and
``cites`` rel table at the canonical path ``var/arxmcp/index/kuzu/``
(matches ``Makefile:bootstrap`` and ``05-storage-and-indexing.md``).

The milestone brief AC#1 names the path ``var/arxmcp/index/kuzudb/``;
that wording conflicts with the bootstrap target and both relevant
design notes (``05-storage-and-indexing.md`` and
``08-security-observability-ops.md``), all of which use ``kuzu/``. The
implementation follows the design constitution and treats the brief's
AC#1 path-name as drift to be corrected in a follow-up docs PR. See
``research-synthesis.md`` § 2.1 for the resolution.

Kuzu was archived 2025-10-10; pinned to v0.11.3 (last stable, MIT) in
``pyproject.toml``. Future fork migration (Kineviz bighorn /
Vela-Engineering) is tracked separately; do not bump the pin without
re-evaluating the upstream landscape.

Schema (Tier-3 minimal — the richer 5-table form in
``05-storage-and-indexing.md`` § Kùzu citation graph is intentionally
deferred to E09_S03+):

- ``papers``: paper_id (PK), title, abstract, authors, year,
  categories, oa_work_id.
- ``cites``: FROM papers TO papers; source ("openAlex" | "inspire" |
  "intra-paper"); confidence (0..1).

Idempotency: every DDL statement uses ``CREATE … IF NOT EXISTS`` (Kùzu
0.4+). Re-running the migration is a no-op.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import kuzu

#: SQL DDL statements applied in order. Each is idempotent
#: (``IF NOT EXISTS``) so a re-run on an already-migrated database is
#: a no-op rather than an error. See ``apply_schema`` for the writer.
SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE NODE TABLE IF NOT EXISTS papers (
        paper_id STRING,
        title STRING,
        abstract STRING,
        authors STRING,
        year INT32,
        categories STRING,
        oa_work_id STRING,
        PRIMARY KEY (paper_id)
    )
    """,
    """
    CREATE REL TABLE IF NOT EXISTS cites (
        FROM papers TO papers,
        source STRING,
        confidence FLOAT
    )
    """,
)


def apply_schema(db_path: Path) -> None:
    """Apply the citation-graph schema to a Kùzu database directory.

    Creates the parent directory if missing (the Kùzu DB itself is a
    directory, not a single file). Runs every statement in
    ``SCHEMA_STATEMENTS`` in order; each uses ``IF NOT EXISTS`` so the
    function is idempotent (AC#2).

    Args:
        db_path: directory the Kùzu ``Database`` will own. The
            production default is ``var/arxmcp/index/kuzu/``; tests
            pass ``tmp_path`` per the conftest discipline.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = kuzu.Database(str(db_path))
    try:
        conn = kuzu.Connection(db)
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
    finally:
        # kuzu.Database closes implicitly when the Python object is GC'd;
        # explicitly drop the local reference so the close runs deterministically
        # (matters on Windows where the open file handle blocks parent rmtree
        # in pytest tmp_path teardown).
        del db


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kuzudb",
        type=Path,
        default=Path("var/arxmcp/index/kuzu"),
        help=(
            "directory the Kùzu database will own "
            "(default: var/arxmcp/index/kuzu — matches Makefile bootstrap)"
        ),
    )
    args = parser.parse_args()
    apply_schema(args.kuzudb)
    print(f"applied schema to {args.kuzudb}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
