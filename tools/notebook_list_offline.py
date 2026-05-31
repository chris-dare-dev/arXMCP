"""Offline notebook lister (``onboarding-uplift-m2``).

Backs ``make notebook-list``'s server-down path. Opens
``var/arxmcp/cache/notebooks.db`` directly via raw :mod:`sqlite3`
(NOT via :class:`server.notebooks_store.NotebooksStore` — see m2
critique F2 / HIGH below) and prints one ``  <slug> (<display_name>)``
line per registered notebook, matching the server-up REST path's
output format.

The server-up path lives inline in the Makefile recipe (a one-liner
``curl /ui/api/notebooks | python -c …``); only the server-down path
needs Python's async / context-manager machinery, which doesn't fit
cleanly in a ``-c`` one-liner.

**m2 critique F2 rectification (HIGH fix).** The prior implementation
called :meth:`NotebooksStore.open` which runs the FULL v0→v4 migration
sequence on the operator's only copy of ``notebooks.db`` — including
the destructive ``DROP TABLE IF EXISTS notebooks`` in the v0→v1 block
at ``server/notebooks_store.py:154-156``. A "list" command silently
mutating the schema was the surprise; combined with m2 critique F1's
cold-DB scenario, listing AFTER ``make init`` would have destroyed the
just-registered row. The rectified path opens a raw read-only
``sqlite3.Connection`` (``mode=ro`` via URI), runs a single SELECT
over the two columns we display, and treats a missing ``notebooks``
table as "no notebooks yet" rather than running migrations. The file
is NEVER written to.

Usage:

    uv run python -m tools.notebook_list_offline

Exit 0 always (a missing DB / empty notebooks table is informational,
not an error).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# m2 critique F7 rectification (LOW): single source of truth for the
# canonical ``notebooks.db`` path. Imported from
# :mod:`server.operator_settings` rather than redeclared here.
from server.operator_settings import DEFAULT_DB_PATH


def _list_notebooks_read_only(db_path: Path) -> list[tuple[str, str]]:
    """Return ``[(slug, display_name), ...]`` from ``db_path`` without
    ever writing to the file.

    Uses SQLite's ``mode=ro`` URI parameter so any accidental write
    attempt raises ``sqlite3.OperationalError`` immediately. A missing
    ``notebooks`` table is treated as "no notebooks yet" — the table
    may legitimately not exist on a fresh file that's only been
    touched by :class:`server.operator_settings.OperatorSettingsStore`
    (which creates ``operator_settings`` but not ``notebooks``).
    """
    # ``mode=ro`` is a SQLite URI parameter — disables ALL writes
    # including PRAGMA-driven internal bookkeeping. Belt-and-braces
    # against future contributors accidentally adding a write here.
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        try:
            cur = conn.execute(
                "SELECT slug, display_name FROM notebooks "
                "ORDER BY created_at DESC, slug ASC"
            )
            return [(slug, display) for slug, display in cur.fetchall()]
        except sqlite3.OperationalError:
            # Table doesn't exist — treat as "no notebooks yet". The
            # operator's mental model: a fresh file that no
            # ``make init`` has touched contains no notebooks.
            return []
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    db_path = DEFAULT_DB_PATH
    if argv and len(argv) > 0:
        db_path = Path(argv[0])

    if not db_path.exists():
        print(
            "server down — notebooks.db does not exist yet; "
            "run `make init NOTEBOOK=<slug>` first"
        )
        return 0

    rows = _list_notebooks_read_only(db_path)
    print(f"{len(rows)} notebook(s) — via notebooks.db (server down):")
    for slug, display in rows:
        # Fall back to slug if display_name is empty (matches the
        # server-up REST path's formatting).
        print(f"  {slug} ({display or slug})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
