"""Read-only LanceDB ``chunks`` table accessor with MVCC version pinning (E04_S02).

The MVCC handshake — verbatim from the brief AC and from
:mod:`ingest.store`'s docstring:

  No symlink swaps. LanceDB version int IS the corpus_version.
  Writers use the current dataset; readers call
  dataset.checkout(version=N).

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
**fresh table handle per call** — closes F1 from the E04_S02 critique
by relying on ``lancedb.connect`` returning a fresh ``Connection`` per
invocation (verified live and locked by
``tests/test_mvcc.py::TestHandleIndependence``). Callers that want to
cache should cache the *returned* handle, NOT the intermediate
``open_table`` result, AND must not subsequently call ``checkout`` on
the cached handle (that would invalidate every cached pin).

**HNSW + checkout interaction.** When a reader pins to a version that
predates an HNSW index build, LanceDB transparently falls back to
brute-force scan for ANN queries. Results are correct; performance
degrades. The integer returned by :func:`ingest.store.write_chunks` is
the post-index version (E04_S01 docstring's "MVCC handshake" section),
so readers pinning to that integer always get an indexed view.

**Caching contract (F12 from the E04_S02 critique).** This function is
the **uncached primitive**. Every call performs ``lancedb.connect`` →
``db.open_table`` → optional ``checkout`` and returns a fresh handle.
For an MCP server handling 10+ search_papers/sec, the per-call connect
overhead is real. The recommended pattern for E06 is: call this
function ONCE per pinned version at startup, cache the returned handle,
and route queries to the cached handle. Re-pinning to a new version
requires opening a new handle (do not call ``checkout`` on a cached
one).

**Threat 1 (08-security-observability-ops.md).** This function accepts
a filesystem path. In production the path comes from a trusted config
value, not from tool input — but we ``Path(...).exists()``-check before
passing to LanceDB so the failure mode is a clear ``FileNotFoundError``
with the offending path in the message, not a confusing
LanceDB-internal error. **Path-traversal validation is deferred to
E06's tool-input boundary (TODO(E06))**: that layer must validate the
path against the configured corpus root BEFORE invoking this function.
Closes F9 from the E04_S02 critique by surfacing the deferral
explicitly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ingest.schema import CHUNKS_TABLE_NAME

# Import the writer's default path so reader and writer have a
# symmetric default — closes F3 from the E04_S02 critique. Both
# modules now share a single source of truth for where the LanceDB
# dataset lives. ``ingest.store`` does NOT import from ``server.*``,
# so this dependency is one-way and does not close a cycle.
from ingest.store import DEFAULT_LANCEDB_PATH

if TYPE_CHECKING:  # pragma: no cover
    import lancedb.table

logger = logging.getLogger(__name__)


def open_chunks_table(
    lancedb_path: str | Path | None = None,
    version: int | None = None,
) -> lancedb.table.Table:
    """Open the ``chunks`` table at LanceDB ``version``.

    Returns a fresh, version-pinned ``lancedb.table.Table`` handle.
    The handle supports the standard LanceDB read API: ``count_rows``,
    ``to_arrow``, ``search``, ``schema``, ``version``. Writes raise
    ``ValueError`` from LanceDB's own write guard ("table cannot be
    modified when a specific version is checked out") — no defensive
    wrapper is added on this side.

    Pass ``lancedb_path=None`` (default) to use
    :data:`ingest.store.DEFAULT_LANCEDB_PATH` — the same default the
    writer uses (closes F3).

    Pass ``version=None`` (default) to open the live tip (latest
    version). The server uses this on cold startup before reading the
    ``corpus-version.json`` marker file (E04_S03); after the marker is
    read, the server re-opens with the explicit integer.

    The ``lancedb_path`` is checked for existence before connecting so
    the failure mode is a clear ``FileNotFoundError`` rather than a
    confusing LanceDB-internal error.

    .. warning::

       Path-traversal validation (Threat 1 from
       ``08-security-observability-ops.md``) is **deferred to E06's
       tool-input boundary**. This function trusts ``lancedb_path`` as
       config-derived. Callers that pass user-supplied paths MUST
       validate against an allowlisted corpus root first.

    Each call opens a fresh table handle. ``checkout`` mutates the
    table object in place, so a shared/cached table passed to
    ``checkout`` would corrupt other readers' views.
    ``lancedb.connect()`` returns a fresh ``Connection`` per call
    (verified by ``tests/test_mvcc.py::TestHandleIndependence``), so
    independent calls produce independent handles even when racing.

    Raises
    ------
    FileNotFoundError
        ``lancedb_path`` does not exist on disk.
    ValueError
        ``version`` is not a known LanceDB dataset version (LanceDB's
        own ``ValueError`` / ``LookupError`` / ``KeyError`` are
        re-raised as ``ValueError`` with a clearer message that names
        both the requested and live-tip versions). Other exception
        types (``OSError`` for disk-full, ``RuntimeError`` for
        LanceDB-internal panics) propagate unchanged so triage points
        at the real fault — closes F2 from the E04_S02 critique.
    """
    import lancedb  # noqa: PLC0415

    resolved_path = (
        Path(lancedb_path) if lancedb_path is not None else DEFAULT_LANCEDB_PATH
    )
    if not resolved_path.exists():
        raise FileNotFoundError(
            f"LanceDB path does not exist: {resolved_path}. "
            f"Run ingest.store.write_chunks first."
        )

    db = lancedb.connect(str(resolved_path))
    tbl = db.open_table(CHUNKS_TABLE_NAME)

    if version is not None:
        try:
            tbl.checkout(version)
        # F2: narrow to the LanceDB exception types that signal
        # "version doesn't exist." OSError (disk full / permission
        # denied) and RuntimeError (LanceDB-internal panic) propagate
        # so triage doesn't get a misleading "version not accessible"
        # message.
        except (ValueError, LookupError, KeyError) as exc:
            live_version = getattr(tbl, "version", None)
            raise ValueError(
                f"LanceDB version {version} is not accessible "
                f"(live tip is {live_version}); call open_chunks_table "
                f"with a valid version or version=None for the live tip"
            ) from exc

    logger.debug(
        "opened chunks table at %s pinned to version %s (live tip = %s)",
        resolved_path,
        version if version is not None else "latest",
        tbl.version,
    )
    return tbl


__all__ = ["open_chunks_table"]
