"""Server-down CLI fallback for ``make repair-registry``
(``onboarding-uplift-m3``).

Walks ``var/arxmcp/notebooks/`` and registers any on-disk dirs with a
valid ``corpus-version.json`` marker that are NOT already in
``notebooks.db::notebooks``. Mirrors the server-up
``POST /ui/api/admin/repair-registry`` REST endpoint's behavior for
operators running ``make repair-registry`` against a stopped server.

Every registration routes through
:meth:`server.notebooks_store.NotebooksStore.create_notebook` — the
canonical writer per the m2 critique F1 lesson. Direct SQLite INSERTs
into the ``notebooks`` table are BANNED.

Usage:

    uv run python -m tools.notebook_repair_registry

Exit codes:
    0 — success (any number of dirs registered, including zero)
    1 — operational failure (cannot open notebooks.db, etc.)
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any

from tools._notebook_common import (
    NOTEBOOKS_BASE,
    NotebookError,
    notebook_lancedb_path,
    validate_slug,
)

logger = logging.getLogger("notebook_repair_registry")


def _read_marker_safely(
    notebook_lance_path: Path,
) -> tuple[Any | None, str | None]:
    """Mirror of ``server/routes/notebooks.py::_read_marker_safely``.

    Returns ``(info, None)`` on success, ``(None, "no_marker")`` when
    absent, ``(None, "malformed")`` on invalid JSON. Used here so the
    server-down path produces the same response classification as the
    server-up REST endpoint.
    """
    from server.corpus import read_corpus_version  # local

    try:
        info = read_corpus_version(notebook_lance_path)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "marker read failed at %s: %s", notebook_lance_path, exc
        )
        return None, "malformed"
    if info is None:
        return None, "no_marker"
    return info, None


async def _repair(
    db_path: Path, notebooks_base: Path
) -> dict[str, list[str]]:
    """Walk + register; returns the same four-bucket shape as the REST
    endpoint's response model."""
    from server.notebooks_store import NotebooksStore  # local

    # m2 synthesis FM-1 / m3 synthesis §3 D5: ensure busy_timeout is set
    # so a concurrent server write doesn't immediately raise
    # ``sqlite3.OperationalError`` on the CLI side. ``NotebooksStore.open``
    # applies it during ``_open_sync`` via the WAL pragma block; mention
    # in the comment so future contributors don't second-guess.
    store = await NotebooksStore.open(db_path)

    registered: list[str] = []
    already_registered: list[str] = []
    skipped_no_marker: list[str] = []
    skipped_malformed: list[str] = []

    try:
        existing_slugs = {
            row["slug"] for row in await store.list_notebooks()
        }
        if not notebooks_base.is_dir():
            logger.info(
                "repair-registry: %s does not exist; nothing to walk",
                notebooks_base,
            )
            return {
                "registered": registered,
                "already_registered": already_registered,
                "skipped_no_marker": skipped_no_marker,
                "skipped_malformed_marker": skipped_malformed,
            }

        from datetime import UTC, datetime  # noqa: PLC0415

        for child in sorted(notebooks_base.iterdir()):
            if not child.is_dir() or child.is_symlink():
                continue
            slug = child.name
            try:
                validate_slug(slug)
            except NotebookError:
                logger.debug(
                    "repair-registry: skipping %s (invalid slug)", child
                )
                continue

            nb_lance = child / "lancedb"
            info, err = _read_marker_safely(nb_lance)
            if err == "no_marker":
                skipped_no_marker.append(slug)
                continue
            if err == "malformed":
                skipped_malformed.append(slug)
                continue

            if slug in existing_slugs:
                already_registered.append(slug)
                continue

            now = (
                datetime.now(UTC)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            )
            try:
                await store.create_notebook(
                    slug=slug,
                    display_name="",
                    lancedb_path=str(
                        notebook_lancedb_path(slug, base=notebooks_base)
                    ),
                    created_at=now,
                )
                registered.append(slug)
                logger.info(
                    "registered slug=%s version=%d chunks=%d papers=%d",
                    slug,
                    info.version,
                    info.chunk_count,
                    info.paper_count,
                )
            except sqlite3.IntegrityError:
                already_registered.append(slug)
        return {
            "registered": registered,
            "already_registered": already_registered,
            "skipped_no_marker": skipped_no_marker,
            "skipped_malformed_marker": skipped_malformed,
        }
    finally:
        await store.close()


def main(
    argv: list[str] | None = None,
    *,
    db_path: Path | None = None,
    notebooks_base: Path | None = None,
) -> int:
    """CLI entry point.

    Tests pass ``db_path`` + ``notebooks_base`` explicitly to scope to a
    ``tmp_path``-scoped fixture; production callers pass ``None`` and the
    defaults resolve to ``var/arxmcp/cache/notebooks.db`` +
    :data:`tools._notebook_common.NOTEBOOKS_BASE`.
    """
    del argv  # accepted for symmetry with other tools/notebook_*.py mains

    # Resolve the canonical DB path lazily (the server.operator_settings
    # import is the single source of truth; m2 critique F7 lesson).
    if db_path is None:
        from server.operator_settings import DEFAULT_DB_PATH  # local

        db_path = DEFAULT_DB_PATH
    if notebooks_base is None:
        notebooks_base = NOTEBOOKS_BASE

    try:
        result = asyncio.run(_repair(db_path, notebooks_base))
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    # One-line human-readable summary, then the JSON for scripts.
    print(
        f"repair-registry: registered={len(result['registered'])} "
        f"already_registered={len(result['already_registered'])} "
        f"skipped_no_marker={len(result['skipped_no_marker'])} "
        f"skipped_malformed_marker={len(result['skipped_malformed_marker'])}"
    )
    if any(result.values()):
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
