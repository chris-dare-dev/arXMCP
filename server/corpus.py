"""Read-only LanceDB ``chunks`` table accessor with MVCC version pinning (E04_S02).

The MVCC handshake — verbatim from the brief AC and from
:mod:`ingest.store`'s docstring:

  No symlink swaps. LanceDB version int IS the corpus_version.
  Writers use the current dataset; readers call
  ``dataset.checkout(version=N)``.

The MCP server (E06) reads the ``corpus_version`` (an integer) from a
runtime config and passes it to :func:`open_chunks_table` to pin the
dataset view at startup. The eval harness (E05) does the same. Pinning
ensures that concurrent writers cannot affect a long-running reader's
result set, and that a reader can reproduce any query against any
historical dataset version.

**Why a separate module rather than re-exporting from ingest.store.**
``ingest.store`` is the *writer*; ``server.corpus`` is the *reader*.
LanceDB's ``checkout`` API is read-only — calling it on a table object
that's also being used to write would corrupt the writer's view. By
isolating the reader in a server-layer module we make the
read-vs-write distinction explicit at the import-graph level: nothing
in ``ingest/`` imports ``server.corpus``, and nothing in
``server.corpus`` writes to LanceDB.

**checkout mutates in place.** ``tbl.checkout(N)`` is an in-place
mutation of the table object that pins reads to version ``N``. A
shared/cached table reference passed to ``checkout`` would corrupt
other readers' views. :func:`open_chunks_table` therefore returns a
**fresh table handle per call** — callers that want to cache should
cache the *returned* handle, not the intermediate ``open_table`` result
(see the function docstring for the caching guidance).

**HNSW + checkout interaction.** When a reader pins to a version that
predates an HNSW index build, LanceDB transparently falls back to
brute-force scan for ANN queries. Results are correct; performance
degrades. The integer returned by :func:`ingest.store.write_chunks` is
the post-index version (E04_S01 docstring's "MVCC handshake" section),
so readers pinning to that integer always get an indexed view.

**Threat 1 (08-security-observability-ops.md).** This function accepts
a filesystem path. In production the path comes from a trusted config
value, not from tool input — but we ``Path(...).exists()``-check before
passing to LanceDB so the failure mode is a clear ``FileNotFoundError``
with the offending path in the message, not a confusing
LanceDB-internal error.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ingest.schema import CHUNKS_TABLE_NAME

logger = logging.getLogger(__name__)


def open_chunks_table(
    lancedb_path: str | Path,
    version: int | None = None,
) -> object:
    """Open the ``chunks`` table at LanceDB ``version``.

    Returns a fresh, version-pinned ``lancedb.table.Table`` handle.
    The handle supports the standard LanceDB read API: ``count_rows``,
    ``to_arrow``, ``search``, ``schema``, ``version``. Writes raise
    ``ValueError`` from LanceDB's own write guard ("table cannot be
    modified when a specific version is checked out") — no defensive
    wrapper is added on this side.

    Pass ``version=None`` to open the live tip (latest version). The
    server uses this on cold startup before reading the
    ``corpus-version.json`` marker file (E04_S03); after the marker
    is read, the server re-opens with the explicit integer.

    The ``lancedb_path`` is checked for existence before connecting so
    the failure mode is a clear ``FileNotFoundError`` rather than a
    confusing LanceDB-internal error. Path validation (Threat 1) is
    deferred to the MCP-tool input layer (E06) — for E04_S02 the path
    is treated as trusted-config input.

    Each call opens a fresh table handle. ``checkout`` mutates the
    table object in place, so a shared/cached table passed to
    ``checkout`` would corrupt other readers' views. Callers that
    want to cache should cache the *returned* handle, not the
    intermediate ``open_table`` result.

    Raises
    ------
    FileNotFoundError
        ``lancedb_path`` does not exist on disk.
    ValueError
        ``version`` is not a known LanceDB dataset version (the
        underlying LanceDB exception is re-raised with a clearer
        message that names the missing version).
    """
    import lancedb  # noqa: PLC0415

    path = Path(lancedb_path)
    if not path.exists():
        raise FileNotFoundError(
            f"LanceDB path does not exist: {path}. "
            f"Run ingest.store.write_chunks first."
        )

    db = lancedb.connect(str(path))
    tbl = db.open_table(CHUNKS_TABLE_NAME)

    if version is not None:
        try:
            tbl.checkout(version)
        except Exception as exc:
            # LanceDB raises a generic Exception/ValueError when the
            # version doesn't exist; re-raise with a clearer message
            # that names the requested + live versions explicitly.
            # Read tbl.version BEFORE the failed checkout if possible;
            # if checkout failed without mutating, ``tbl.version`` is
            # still the pre-checkout (live) version.
            live_version = getattr(tbl, "version", "?")
            raise ValueError(
                f"LanceDB version {version} is not accessible "
                f"(live tip is {live_version}); call open_chunks_table "
                f"with a valid version or version=None for the live tip"
            ) from exc

    logger.debug(
        "opened chunks table at %s pinned to version %s (live tip = %s)",
        path,
        version if version is not None else "latest",
        tbl.version,
    )
    return tbl


__all__ = ["open_chunks_table"]
