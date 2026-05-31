"""Offline notebook lister (``onboarding-uplift-m2``).

Backs ``make notebook-list``'s server-down path. Opens
``var/arxmcp/cache/notebooks.db`` directly via
:class:`server.notebooks_store.NotebooksStore` (which auto-runs any
pending migrations) and prints one ``  <slug> (<display_name>)`` line
per registered notebook — matching the server-up REST path's output
format.

The server-up path lives inline in the Makefile recipe (a one-liner
``curl /ui/api/notebooks | python -c …``); only the server-down path
needs Python's async / context-manager machinery, which doesn't fit
cleanly in a ``-c`` one-liner.

Usage:

    uv run python -m tools.notebook_list_offline

Exit 0 always (a missing DB or empty notebooks table is informational,
not an error).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from server.notebooks_store import NotebooksStore

DEFAULT_DB_PATH: Path = Path("var/arxmcp/cache/notebooks.db")


async def _list_notebooks(db_path: Path) -> list[dict[str, str]]:
    if not db_path.exists():
        return []
    store = await NotebooksStore.open(db_path)
    try:
        return await store.list_notebooks()
    finally:
        await store.close()


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

    rows = asyncio.run(_list_notebooks(db_path))
    print(f"{len(rows)} notebook(s) — via notebooks.db (server down):")
    for r in rows:
        # ``NotebooksStore.list_notebooks`` returns ``list[dict[str, str]]``
        # — each row has the 8 v4-schema columns (slug, display_name,
        # lancedb_path, created_at, notebook_kind, parse_status,
        # parse_error, parsed_html_path). Print slug + display_name
        # (falling back to slug if display is empty).
        slug = r.get("slug", "<?>")
        display = r.get("display_name") or slug
        print(f"  {slug} ({display})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
