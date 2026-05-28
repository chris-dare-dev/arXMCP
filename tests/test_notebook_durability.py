"""Durability + on-disk-format-pin regression tests (notebook-ops-hardening-m2).

Two independent hardening changes are covered here:

1. **SQLite crash durability** — ``server/notebooks_store.py`` opens its
   single, long-lived ``notebooks.db`` connection with
   ``PRAGMA synchronous=FULL`` + ``PRAGMA fullfsync=ON``. ``notebooks.db``
   holds user-authored, NON-regenerable state, so a committed write must
   survive an OS crash / power loss. The regenerable Tier-1 cache
   (``cache_sqlite.py``) and theorem-names store stay ``NORMAL`` on
   purpose — that scope decision is locked by ``TestDurabilityScope``.

2. **LanceDB on-disk format pin** — every ``db.create_table(...)`` call
   passes ``storage_options=LANCE_STORAGE_OPTIONS`` so a ``uv``/``pip``
   upgrade can't silently migrate the format under a pinned reader.

The ``fullfsync`` pragma is CONNECTION-scoped (it does NOT persist to a
fresh connection to the same file), so the pragma assertions read back
from the store's OWN connection (``store._conn``) — see
``test_fullfsync_does_not_persist_to_fresh_connection`` for why a
separate-connection read (the pattern used for the database-scoped
``user_version`` pragma in ``test_notebook_api.py``) would be wrong here.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from ingest.chunker_types import CHUNKER_VERSION, ChunkRecord
from ingest.embedder import EMBEDDER_VERSION, EMBEDDING_DIM
from ingest.schema import CHUNKS_TABLE_NAME, LANCE_STORAGE_OPTIONS, EmbedRecord
from server.notebooks_store import NotebooksStore

# SQLite PRAGMA synchronous integer codes: OFF=0, NORMAL=1, FULL=2, EXTRA=3.
_SYNC_FULL = 2


# ===========================================================================
# Part 1 — SQLite crash durability
# ===========================================================================


def _pragmas_after_committed_write(
    db_path: Path, *, fresh_conn: bool = False
) -> dict[str, object]:
    """Open a store, do one committed write, read durability pragmas.

    Everything (open, write, pragma read, close) runs on ONE event loop so
    the store's asyncio.Lock is never touched from a foreign loop. Returns
    the pragma values read from the store's own connection. When
    ``fresh_conn`` is True, ALSO reads them from a brand-new sqlite3
    connection to the same file (to demonstrate connection-scoping).
    """
    async def _run() -> dict[str, object]:
        store = await NotebooksStore.open(db_path)
        try:
            # A real committed write through the public API (autocommit:
            # isolation_level=None means this commits immediately).
            await store.create_notebook(
                slug="durability-probe",
                display_name="Durability Probe",
                lancedb_path=str(db_path.parent / "lancedb"),
                created_at="2026-05-28T00:00:00+00:00",
            )
            result: dict[str, object] = {
                "synchronous": store._conn.execute(
                    "PRAGMA synchronous"
                ).fetchone()[0],
                "fullfsync": store._conn.execute(
                    "PRAGMA fullfsync"
                ).fetchone()[0],
                "journal_mode": store._conn.execute(
                    "PRAGMA journal_mode"
                ).fetchone()[0],
            }
            if fresh_conn:
                fresh = sqlite3.connect(str(db_path))
                try:
                    result["fresh_fullfsync"] = fresh.execute(
                        "PRAGMA fullfsync"
                    ).fetchone()[0]
                    result["fresh_synchronous"] = fresh.execute(
                        "PRAGMA synchronous"
                    ).fetchone()[0]
                finally:
                    fresh.close()
            return result
        finally:
            await store.close()

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


class TestNotebookStoreDurabilityPragmas:
    def test_synchronous_full_and_fullfsync_on_after_committed_write(
        self, tmp_path: Path
    ) -> None:
        """G/W/T: after a committed write, synchronous==2 and fullfsync==1.

        Both pragmas are read from the store's OWN connection. fullfsync is
        connection-scoped and would read back 0 from a fresh connection.
        """
        p = _pragmas_after_committed_write(tmp_path / "notebooks.db")
        assert p["synchronous"] == _SYNC_FULL, (
            f"expected synchronous=FULL (2), got {p['synchronous']}"
        )
        assert p["fullfsync"] == 1, f"expected fullfsync=ON (1), got {p['fullfsync']}"

    def test_journal_mode_stays_wal(self, tmp_path: Path) -> None:
        """The durability bump must NOT disturb WAL mode (FK cascade +
        concurrency depend on it)."""
        p = _pragmas_after_committed_write(tmp_path / "notebooks.db")
        assert str(p["journal_mode"]).lower() == "wal"

    def test_fullfsync_does_not_persist_to_fresh_connection(
        self, tmp_path: Path
    ) -> None:
        """Documents WHY the assertions above read from store._conn.

        fullfsync is connection-scoped: a brand-new sqlite3 connection to
        the SAME file reads it back as 0. A future maintainer must NOT
        "simplify" the pragma test into a separate-connection read (the
        pattern that works for the database-scoped user_version pragma).
        """
        p = _pragmas_after_committed_write(
            tmp_path / "notebooks.db", fresh_conn=True
        )
        assert p["fresh_fullfsync"] == 0, (
            "fullfsync unexpectedly persisted to a fresh connection — the "
            "test design assumption (and the per-open pragma set) is wrong"
        )
        # synchronous IS database-scoped — it does persist.
        assert p["fresh_synchronous"] == _SYNC_FULL


class TestDurabilityScope:
    """Lock the scope boundary: only notebooks.db gets FULL durability.

    The Tier-1 retrieval cache and theorem-names store are REGENERABLE
    from the corpus, so they stay NORMAL (losing the last few writes on a
    crash is a cache miss, not a correctness failure). This test pins that
    decision so a future "make everything FULL" sweep is caught.
    """

    def test_cache_sqlite_stays_normal(self) -> None:
        src = Path("server/cache_sqlite.py").read_text(encoding="utf-8")
        assert "PRAGMA synchronous=NORMAL" in src, (
            "cache_sqlite.py should stay NORMAL (regenerable cache)"
        )
        assert "PRAGMA synchronous=FULL" not in src

    def test_notebooks_store_uses_full_and_fullfsync(self) -> None:
        src = Path("server/notebooks_store.py").read_text(encoding="utf-8")
        assert "PRAGMA synchronous=FULL" in src
        assert "PRAGMA fullfsync=ON" in src
        assert "PRAGMA synchronous=NORMAL" not in src


# ===========================================================================
# Part 2 — LanceDB on-disk format pin
# ===========================================================================


def _make_minimal_corpus(n: int = 2) -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []
    for i in range(n):
        chunks.append(
            ChunkRecord(
                chunk_id=f"arxiv:2307.0010{i}:{i:016x}",
                paper_id=f"2307.0010{i}",
                kind="stmt",
                section_path=[],
                theorem_name=None,
                theorem_label=None,
                body_text=f"Body text {i}.",
                body_tokens=f"body text {i}",
                preamble_ref=None,
                chunker_version=CHUNKER_VERSION,
            )
        )
    return chunks


def _make_embeddings(chunks: list[ChunkRecord], seed: int = 0) -> EmbedRecord:
    rng = np.random.default_rng(seed)
    ids = [c.chunk_id for c in chunks]
    rows = rng.standard_normal((len(chunks), EMBEDDING_DIM)).astype(np.float32)
    rows /= np.linalg.norm(rows, axis=1, keepdims=True)
    return EmbedRecord(
        chunk_ids_stmt=ids,
        embedding_stmt=rows,
        chunk_ids_proof=[],
        embedding_proof=np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
        embedder_version=EMBEDDER_VERSION,
    )


class TestLanceFormatPin:
    def test_constant_value_is_stable(self) -> None:
        """The pinned value must be exactly the modern storage_options key.

        Guards against a maintainer reverting to the bare
        ``data_storage_version`` kwarg (silently dropped in lancedb 0.30.2)
        or changing "stable" to a brittle numeric alias.
        """
        assert LANCE_STORAGE_OPTIONS == {
            "new_table_data_storage_version": "stable"
        }

    def test_storage_options_key_reaches_engine_not_silently_dropped(
        self, tmp_path: Path
    ) -> None:
        """The ONLY guard against a future lancedb silent-drop regression.

        The whole milestone exists because the bare ``data_storage_version``
        kwarg is *accepted by the Python binding but never forwarded to the
        Rust layer* in lancedb 0.30.2 — it "looks correct and does nothing".
        We switched to ``storage_options={"new_table_data_storage_version":
        ...}`` precisely because that form DOES reach the engine.

        Proof by discriminator: a GARBAGE version string is validated only
        in the Rust/Lance layer. So:
          - via ``storage_options`` it must RAISE (the value was forwarded
            and rejected) — if a future release ever begins silently
            dropping this key too, the raise disappears and THIS test fails,
            catching the regression that no pass-through spy could.
          - via the bare ``data_storage_version`` kwarg it must NOT raise
            (the value is dropped before reaching the engine) — locking in
            *why* we don't use that form.
        """
        import warnings

        import lancedb
        import pyarrow as pa

        schema = pa.schema([pa.field("chunk_id", pa.string())])
        garbage = "totally-invalid-storage-version-xyz-999"

        # storage_options path: garbage reaches the engine -> RuntimeError.
        db1 = lancedb.connect(str(tmp_path / "via_options"))
        with pytest.raises(RuntimeError, match="storage version"):
            db1.create_table(
                "t",
                schema=schema,
                storage_options={"new_table_data_storage_version": garbage},
            )

        # bare-kwarg path: garbage is silently dropped -> no raise. If this
        # ever starts raising, lancedb changed the binding and the bare form
        # might have become viable (re-evaluate LANCE_STORAGE_OPTIONS).
        db2 = lancedb.connect(str(tmp_path / "via_bare"))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # silence the DeprecationWarning
            tbl = db2.create_table(
                "t", schema=schema, data_storage_version=garbage
            )
        tbl.add([{"chunk_id": "a"}])
        assert tbl.count_rows() == 1

    def test_write_chunks_passes_storage_options_to_create_table(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Runtime proof: write_chunks reaches create_table WITH the pin.

        Spies on the connection's create_table by wrapping lancedb.connect,
        so the test verifies the option is actually passed at runtime (not
        merely present in source).
        """
        import lancedb

        captured: dict[str, object] = {}
        real_connect = lancedb.connect

        def spy_connect(uri, *args, **kwargs):  # type: ignore[no-untyped-def]
            db = real_connect(uri, *args, **kwargs)
            real_create = db.create_table

            def spy_create(*c_args, **c_kwargs):  # type: ignore[no-untyped-def]
                captured["storage_options"] = c_kwargs.get("storage_options")
                return real_create(*c_args, **c_kwargs)

            db.create_table = spy_create  # type: ignore[method-assign]
            return db

        monkeypatch.setattr(lancedb, "connect", spy_connect)

        chunks = _make_minimal_corpus(2)
        embeddings = _make_embeddings(chunks)
        from ingest.store import write_chunks

        write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")

        assert captured.get("storage_options") == LANCE_STORAGE_OPTIONS, (
            "write_chunks did not pass the storage-version pin to create_table"
        )

    def test_pinned_table_is_readable(self, tmp_path: Path) -> None:
        """The pin must not break writes: a pinned table reads back."""
        chunks = _make_minimal_corpus(2)
        embeddings = _make_embeddings(chunks)
        from ingest.store import write_chunks

        write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")
        import lancedb

        db = lancedb.connect(str(tmp_path / "lancedb"))
        tbl = db.open_table(CHUNKS_TABLE_NAME)
        assert tbl.count_rows() == 2

    @pytest.mark.parametrize(
        "src_path",
        [
            "ingest/store.py",
            "ingest/index_equations.py",
            "ingest/index_definitions.py",
        ],
    )
    def test_all_create_table_sites_pin_storage_options(
        self, src_path: str
    ) -> None:
        """Source guard: every create_table site passes the pin, and none
        uses the silently-dropped bare ``data_storage_version`` kwarg."""
        src = Path(src_path).read_text(encoding="utf-8")
        assert "create_table" in src
        assert "storage_options=LANCE_STORAGE_OPTIONS" in src, (
            f"{src_path}: create_table site missing the storage-version pin"
        )
        # The bare kwarg is silently dropped in lancedb 0.30.2 — must not
        # be used (it looks correct but does nothing).
        assert "data_storage_version=" not in src, (
            f"{src_path}: uses the silently-dropped data_storage_version "
            f"kwarg; use storage_options=LANCE_STORAGE_OPTIONS instead"
        )
