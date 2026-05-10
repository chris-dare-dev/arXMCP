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

#: Schema version. Bump whenever ``SCHEMA_STATEMENTS`` mutates so
#: callers (and downstream cache layers, e.g. ``cite_neighbors`` in
#: E09_S03) can detect drift on an existing database. F6 from the
#: E09_S01 critique cites ``07-multi-agent-caching.md``: any schema
#: mutation MUST bump a version constant so cached responses derived
#: from the schema don't go stale silently.
#:
#: Version history:
#:   1 — E09_S01 — initial papers + cites + _schema_meta.
#:   2 — E09_S02 — adds nullable ``doi`` / ``journal_ref`` /
#:                 ``inspire_id`` columns to ``papers`` for INSPIRE-HEP
#:                 enrichment.
KUZU_SCHEMA_VERSION = 2

#: Nullable columns that ``apply_schema`` adds to ``papers`` via
#: ``ALTER TABLE`` when not already present. Used by the v2 migration
#: introspect-and-ADD loop in ``apply_schema``.
PAPERS_V2_COLUMNS: tuple[tuple[str, str], ...] = (
    ("doi", "STRING"),
    ("journal_ref", "STRING"),
    ("inspire_id", "STRING"),
)

#: SQL DDL statements applied in order. Each is idempotent
#: (``IF NOT EXISTS``) so a re-run on an already-migrated database is
#: a no-op rather than an error. See ``apply_schema`` for the writer.
#:
#: A separate ``_schema_meta`` node table holds the version constant
#: above; a future migration that mutates ``papers`` or ``cites``
#: bumps ``KUZU_SCHEMA_VERSION`` and writes the new value via the same
#: idempotent ``MERGE``.
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
    """
    CREATE NODE TABLE IF NOT EXISTS _schema_meta (
        key STRING,
        value INT32,
        PRIMARY KEY (key)
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
        # E09_S02 — apply v2 ALTER TABLE migrations idempotently.
        # Kùzu 0.11 does not support ``ADD COLUMN IF NOT EXISTS``; we
        # introspect via ``CALL TABLE_INFO`` and only add columns that
        # are not yet present. This keeps re-runs a no-op (matches the
        # spirit of the v1 ``CREATE … IF NOT EXISTS`` statements).
        existing = _introspect_columns(conn, "papers")
        for col_name, col_type in PAPERS_V2_COLUMNS:
            if col_name in existing:
                continue
            conn.execute(f"ALTER TABLE papers ADD {col_name} {col_type}")
        # Stamp the schema-version row idempotently. F6 fix from the
        # E09_S01 critique. ``MERGE`` upserts so a re-run with a bumped
        # version writes the new value; existing readers pick up the
        # change without an explicit migration step.
        conn.execute(
            "MERGE (m:_schema_meta {key: $key}) "
            "ON CREATE SET m.value = $value "
            "ON MATCH SET m.value = $value",
            {"key": "version", "value": KUZU_SCHEMA_VERSION},
        )
    finally:
        # kuzu.Database closes implicitly when the Python object is GC'd;
        # explicitly drop the local reference so the close runs deterministically
        # (matters on Windows where the open file handle blocks parent rmtree
        # in pytest tmp_path teardown).
        del db


def _introspect_columns(conn: kuzu.Connection, table_name: str) -> set[str]:
    """Return the set of column names on ``table_name``.

    Uses Kùzu's ``CALL TABLE_INFO('<table>')`` which returns rows of
    shape ``[idx, name, type, default, is_pk]``. The name column is
    index 1.
    """
    result = conn.execute(f"CALL TABLE_INFO('{table_name}') RETURN *")
    columns: set[str] = set()
    while result.has_next():
        row = result.get_next()
        columns.add(row[1])
    return columns


def read_schema_version(db_path: Path) -> int | None:
    """Return the persisted schema-version stamp, or None if absent.

    Useful for cache invalidation in downstream readers (e.g. the
    ``cite_neighbors`` MCP tool in E09_S03 will key its response cache
    on this value alongside the corpus version).
    """
    if not db_path.exists():
        return None
    db = kuzu.Database(str(db_path))
    try:
        conn = kuzu.Connection(db)
        result = conn.execute(
            "MATCH (m:_schema_meta {key: $key}) RETURN m.value",
            {"key": "version"},
        )
        if not result.has_next():
            return None
        return int(result.get_next()[0])
    finally:
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
