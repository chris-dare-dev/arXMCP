"""Tests for the corpus-version marker file (E04_S03).

Coverage map:
  Acceptance criterion -> test class
  ──────────────────────────────────────────────────────────────────────
  corpus-version.json written on every successful ingest run -> TestWriteOnIngest
  version field matches write_chunks return                  -> TestWriteOnIngest
  Atomic write (tmp + rename, no leak)                       -> TestAtomicWrite
  read_corpus_version → typed dataclass                      -> TestReadMarker
  Cache contract comment in server/corpus.py docstring       -> TestCacheContract
  Two ingest runs → version increments                       -> TestVersionIncrements

Plus regression tests for missing/corrupt marker handling, default
path symmetry, and BP1 byte-stability of the JSON output (alphabetical
keys, no surprise fields).
"""

from __future__ import annotations

import json

import pytest

from ingest.chunker_types import CHUNKER_VERSION
from ingest.embedder import EMBEDDER_VERSION
from ingest.store import (
    CORPUS_VERSION_MARKER_NAME,
    write_chunks,
    write_corpus_version_marker,
)
from server.corpus import CorpusVersionInfo, read_corpus_version

# Reuse the synthetic-corpus helpers from test_store.py so the
# integration test exercises the actual write_chunks → marker
# postcondition. Helpers are pure on import.
from tests.test_store import (
    _make_chunk,
    _make_corpus,
    _make_synthetic_embeddings,
)

# ===========================================================================
# TestCorpusVersionInfoDataclass — round-trip + lenient created_at
# ===========================================================================


class TestCorpusVersionInfoDataclass:
    def test_to_dict_alphabetical_keys(self):
        info = CorpusVersionInfo(
            version=3,
            chunker_version="v1.0",
            embedder_version="bge-m3@deadbeef",
            created_at="2026-05-08T14:30:00Z",
            paper_count=50,
            chunk_count=847,
        )
        d = info.to_dict()
        assert list(d.keys()) == [
            "chunk_count",
            "chunker_version",
            "created_at",
            "embedder_version",
            "paper_count",
            "version",
        ]

    def test_round_trip(self):
        info = CorpusVersionInfo(
            version=7,
            chunker_version="v1.0",
            embedder_version=EMBEDDER_VERSION,
            created_at="2026-05-08T00:00:00Z",
            paper_count=10,
            chunk_count=200,
        )
        recovered = CorpusVersionInfo.from_dict(info.to_dict())
        assert recovered == info

    def test_from_dict_lenient_on_missing_created_at(self):
        # The schema reader treats created_at as debug-only metadata;
        # a future schema reduction that drops it must not break
        # readers.
        data = {
            "version": 4,
            "chunker_version": "v1.0",
            "embedder_version": "bge-m3@abc12345",
            "paper_count": 1,
            "chunk_count": 1,
        }
        info = CorpusVersionInfo.from_dict(data)
        assert info.created_at == ""

    def test_from_dict_missing_required_field_raises_value_error(self):
        # Closes L1 from the E04_S03 critique: missing required fields
        # now raise ValueError (not KeyError) so callers catch a single
        # exception type.
        data = {
            "version": 4,
            # missing chunker_version
            "embedder_version": "bge-m3@abc12345",
            "paper_count": 1,
            "chunk_count": 1,
        }
        with pytest.raises(ValueError, match="chunker_version"):
            CorpusVersionInfo.from_dict(data)

    def test_from_dict_rejects_negative_version(self):
        # Closes H1 from the E04_S03 critique: domain validation. A
        # corrupt marker with version=-1 must raise, not silently
        # deserialize and lose the corruption signal.
        data = {
            "version": -1,
            "chunker_version": "v1.0",
            "embedder_version": "bge-m3@abc12345",
            "paper_count": 1,
            "chunk_count": 1,
        }
        with pytest.raises(ValueError, match="version must be >="):
            CorpusVersionInfo.from_dict(data)

    def test_from_dict_rejects_negative_paper_count(self):
        # Closes H1: domain validation. paper_count must be >= 0.
        data = {
            "version": 1,
            "chunker_version": "v1.0",
            "embedder_version": "bge-m3@abc12345",
            "paper_count": -5,
            "chunk_count": 1,
        }
        with pytest.raises(ValueError, match="paper_count must be >="):
            CorpusVersionInfo.from_dict(data)

    def test_from_dict_rejects_string_version(self):
        # Closes H1: type validation. A JSON parser would never
        # produce ``"3"`` from ``3``, but a hand-edited or migrated
        # file could.
        data = {
            "version": "3",
            "chunker_version": "v1.0",
            "embedder_version": "bge-m3@abc12345",
            "paper_count": 1,
            "chunk_count": 1,
        }
        with pytest.raises(ValueError, match="version must be an int"):
            CorpusVersionInfo.from_dict(data)

    def test_from_dict_rejects_none_embedder_version(self):
        # Closes H1: ``str(None) == "None"`` previously slipped
        # through the cast and produced a marker with the literal
        # string ``"None"`` as the embedder_version.
        data = {
            "version": 1,
            "chunker_version": "v1.0",
            "embedder_version": None,
            "paper_count": 1,
            "chunk_count": 1,
        }
        with pytest.raises(ValueError, match="embedder_version must"):
            CorpusVersionInfo.from_dict(data)

    def test_from_dict_rejects_int_chunker_version(self):
        # Closes H1: ``str(5) == "5"`` previously stringified an int.
        data = {
            "version": 1,
            "chunker_version": 5,
            "embedder_version": "bge-m3@abc12345",
            "paper_count": 1,
            "chunk_count": 1,
        }
        with pytest.raises(ValueError, match="chunker_version must"):
            CorpusVersionInfo.from_dict(data)

    def test_from_dict_rejects_bool_as_version(self):
        # Closes H1: ``isinstance(True, int)`` is True in Python, so
        # the bool-int distinction must be tested explicitly.
        data = {
            "version": True,  # technically a Python int, but absurd
            "chunker_version": "v1.0",
            "embedder_version": "bge-m3@abc12345",
            "paper_count": 1,
            "chunk_count": 1,
        }
        with pytest.raises(ValueError, match="version must be an int"):
            CorpusVersionInfo.from_dict(data)


# ===========================================================================
# TestWriteMarker — atomic write produces the expected file
# ===========================================================================


class TestWriteMarker:
    def test_writes_alphabetical_json_keys(self, tmp_path):
        write_corpus_version_marker(
            tmp_path,
            version=1,
            chunker_version="v1.0",
            embedder_version="bge-m3@aaaa1111",
            paper_count=5,
            chunk_count=10,
        )
        marker = tmp_path / CORPUS_VERSION_MARKER_NAME
        assert marker.exists()
        text = marker.read_text(encoding="utf-8")
        # Must end with a newline and parse cleanly.
        assert text.endswith("\n")
        data = json.loads(text)
        assert data["version"] == 1
        assert data["chunker_version"] == "v1.0"
        assert data["embedder_version"] == "bge-m3@aaaa1111"
        assert data["paper_count"] == 5
        assert data["chunk_count"] == 10
        assert "created_at" in data
        # Alphabetical key order at serialization time (BP1).
        # Re-load preserves order in Python 3.7+ dicts.
        parsed_keys = list(data.keys())
        assert parsed_keys == sorted(parsed_keys)

    def test_default_path(self, tmp_path, monkeypatch):
        # Pointing DEFAULT_LANCEDB_PATH at tmp_path tests the
        # ``lancedb_path=None`` branch.
        import ingest.store as store_mod

        monkeypatch.setattr(store_mod, "DEFAULT_LANCEDB_PATH", tmp_path)
        write_corpus_version_marker(
            None,
            version=2,
            chunker_version="v1.0",
            embedder_version="bge-m3@bbbb2222",
            paper_count=1,
            chunk_count=1,
        )
        assert (tmp_path / CORPUS_VERSION_MARKER_NAME).exists()

    def test_overwrite_in_place(self, tmp_path):
        # Second write replaces the first — the marker is the LATEST
        # ingest's view, not a log.
        write_corpus_version_marker(
            tmp_path,
            version=1,
            chunker_version="v1.0",
            embedder_version="bge-m3@first",
            paper_count=1,
            chunk_count=1,
        )
        write_corpus_version_marker(
            tmp_path,
            version=5,
            chunker_version="v1.0",
            embedder_version="bge-m3@secnd",
            paper_count=2,
            chunk_count=2,
        )
        marker = tmp_path / CORPUS_VERSION_MARKER_NAME
        data = json.loads(marker.read_text(encoding="utf-8"))
        assert data["version"] == 5
        assert data["embedder_version"] == "bge-m3@secnd"


# ===========================================================================
# TestAtomicWrite — tmp + rename pattern (no leaks)
# ===========================================================================


class TestAtomicWrite:
    def test_no_tmp_files_after_successful_write(self, tmp_path):
        write_corpus_version_marker(
            tmp_path,
            version=1,
            chunker_version="v1.0",
            embedder_version="bge-m3@xxxxxxxx",
            paper_count=1,
            chunk_count=1,
        )
        # No leaked .tmp files in the directory.
        leftover = list(tmp_path.glob("*.tmp"))
        assert leftover == []

    def test_tmp_filename_includes_pid_and_uuid(self, tmp_path, monkeypatch):
        # Capture the tmp path the writer uses BEFORE os.replace
        # by patching os.replace to record args.
        import os as os_mod

        captured_tmp_paths: list[str] = []
        original_replace = os_mod.replace

        def _capturing_replace(src, dst):
            captured_tmp_paths.append(str(src))
            return original_replace(src, dst)

        monkeypatch.setattr("ingest.store.os.replace", _capturing_replace)
        write_corpus_version_marker(
            tmp_path,
            version=1,
            chunker_version="v1.0",
            embedder_version="bge-m3@xxxxxxxx",
            paper_count=1,
            chunk_count=1,
        )
        assert len(captured_tmp_paths) == 1
        tmp_name = captured_tmp_paths[0]
        # Pattern: <out_path>.<pid>.<uuid8>.tmp
        assert str(os_mod.getpid()) in tmp_name
        assert tmp_name.endswith(".tmp")


# ===========================================================================
# TestReadMarker — round-trip + None on absent + raise on corrupt
# ===========================================================================


class TestReadMarker:
    def test_round_trip_via_writer_and_reader(self, tmp_path):
        write_corpus_version_marker(
            tmp_path,
            version=42,
            chunker_version="v1.0",
            embedder_version="bge-m3@cafebabe",
            paper_count=7,
            chunk_count=99,
        )
        info = read_corpus_version(tmp_path)
        assert info is not None
        assert info.version == 42
        assert info.chunker_version == "v1.0"
        assert info.embedder_version == "bge-m3@cafebabe"
        assert info.paper_count == 7
        assert info.chunk_count == 99
        assert info.created_at  # non-empty timestamp

    def test_returns_none_on_absent_marker(self, tmp_path):
        # No marker file under tmp_path → None. The cold-start path
        # for the MCP server.
        assert read_corpus_version(tmp_path) is None

    def test_returns_none_when_marker_is_a_directory(self, tmp_path):
        # Closes M5 from the E04_S03 critique: a directory at the
        # marker location (e.g. left behind by a failed atomic
        # rename, or a malicious symlink) used to fall through to
        # ``read_text`` and raise ``IsADirectoryError`` (an
        # ``OSError`` outside the documented ``ValueError`` /
        # ``None`` contract). With ``is_file()`` the function
        # cleanly returns ``None``.
        (tmp_path / CORPUS_VERSION_MARKER_NAME).mkdir()
        assert read_corpus_version(tmp_path) is None

    def test_raises_on_corrupt_json(self, tmp_path):
        marker = tmp_path / CORPUS_VERSION_MARKER_NAME
        marker.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(ValueError, match="not valid JSON"):
            read_corpus_version(tmp_path)

    def test_raises_on_missing_required_field(self, tmp_path):
        marker = tmp_path / CORPUS_VERSION_MARKER_NAME
        marker.write_text(
            json.dumps({"version": 1, "chunker_version": "v1.0"}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="malformed"):
            read_corpus_version(tmp_path)

    def test_default_path_via_monkeypatch(self, tmp_path, monkeypatch):
        # ``lancedb_path=None`` falls back to DEFAULT_LANCEDB_PATH.
        import ingest.store as store_mod
        import server.corpus as corpus_mod

        monkeypatch.setattr(store_mod, "DEFAULT_LANCEDB_PATH", tmp_path)
        monkeypatch.setattr(corpus_mod, "DEFAULT_LANCEDB_PATH", tmp_path)
        write_corpus_version_marker(
            None,
            version=3,
            chunker_version="v1.0",
            embedder_version="bge-m3@dddddddd",
            paper_count=1,
            chunk_count=1,
        )
        info = read_corpus_version(None)
        assert info is not None
        assert info.version == 3


# ===========================================================================
# TestCacheContract — server/corpus.py module docstring contains the contract
# ===========================================================================


class TestCacheContract:
    def test_corpus_module_docstring_states_cache_contract(self):
        """Brief AC: 'Cache contract comment is present in
        server/corpus.py'. Whitespace-collapsed substring match so the
        sentence can wrap across source lines without breaking the test.
        """
        import server.corpus as corpus_mod

        doc = corpus_mod.__doc__ or ""
        doc_collapsed = " ".join(doc.split())
        # The exact phrase from the milestone brief deliverables list.
        required = (
            "Downstream caches (E08_S03) must include corpus_version "
            "in their keys."
        )
        assert required in doc_collapsed, (
            "server/corpus.py module docstring must contain the cache "
            "contract sentence verbatim per E04_S03 deliverables"
        )


# ===========================================================================
# TestThreat1Deferral — M2: Threat 1 / TODO(E06) note on new public surfaces
# ===========================================================================


class TestThreat1Deferral:
    def test_writer_docstring_carries_threat1_deferral(self):
        """Closes M2: ``write_corpus_version_marker`` accepts a
        filesystem path and must carry the Threat 1 deferral marker
        the rest of the corpus reader/writer surfaces use, so a future
        maintainer reading the function in isolation sees the
        validation contract."""
        from ingest.store import write_corpus_version_marker

        doc = write_corpus_version_marker.__doc__ or ""
        doc_collapsed = " ".join(doc.split())
        assert "Threat 1" in doc_collapsed
        assert "TODO(E06)" in doc_collapsed

    def test_reader_docstring_carries_threat1_deferral(self):
        """Closes M2: same discipline for ``read_corpus_version``."""
        from server.corpus import read_corpus_version

        doc = read_corpus_version.__doc__ or ""
        doc_collapsed = " ".join(doc.split())
        assert "Threat 1" in doc_collapsed
        assert "TODO(E06)" in doc_collapsed


# ===========================================================================
# TestWriteOnIngest — write_chunks calls write_corpus_version_marker
# ===========================================================================


class TestWriteOnIngest:
    def test_marker_written_on_every_successful_ingest(self, tmp_path):
        chunks = _make_corpus(5)
        embeddings = _make_synthetic_embeddings(chunks, seed=1)
        version = write_chunks(
            chunks, embeddings, lancedb_path=tmp_path / "lancedb"
        )
        marker = tmp_path / "lancedb" / CORPUS_VERSION_MARKER_NAME
        assert marker.exists()
        info = read_corpus_version(tmp_path / "lancedb")
        assert info is not None
        # AC: version field matches write_chunks return value.
        assert info.version == version

    def test_marker_carries_correct_aggregates(self, tmp_path):
        # Closes M3 from the E04_S03 critique: derive expected values
        # from the chunks list itself rather than hardcoding the magic
        # number 3 against ``_make_corpus``'s internal ``i % 3``
        # rotation. A future ``_make_corpus`` edit (e.g., to ``i % 5``)
        # will not silently break this test.
        chunks = _make_corpus(10)
        embeddings = _make_synthetic_embeddings(chunks, seed=2)
        expected_paper_count = len({c.paper_id for c in chunks})
        expected_chunk_count = len(chunks)
        write_chunks(chunks, embeddings, lancedb_path=tmp_path / "lancedb")
        info = read_corpus_version(tmp_path / "lancedb")
        assert info is not None
        assert info.chunk_count == expected_chunk_count
        assert info.paper_count == expected_paper_count
        # chunker_version + embedder_version must reflect live constants.
        assert info.chunker_version == CHUNKER_VERSION
        assert info.embedder_version == EMBEDDER_VERSION


# ===========================================================================
# TestVersionIncrements — two successive writes
# ===========================================================================


class TestVersionIncrements:
    def test_marker_version_increments_across_runs(self, tmp_path):
        """Brief AC: 'Test: write two successive ingest runs, assert
        version increments.'"""
        # First batch: 5 chunks.
        first_batch = _make_corpus(5)
        first_emb = _make_synthetic_embeddings(first_batch, seed=10)
        v_a = write_chunks(
            first_batch, first_emb, lancedb_path=tmp_path / "lancedb"
        )
        info_a = read_corpus_version(tmp_path / "lancedb")
        assert info_a is not None
        assert info_a.version == v_a

        # Second batch: 5 more new chunks.
        new_chunks = [
            _make_chunk(
                f"2307.0050{i}", "stmt", f"new {i}", suffix=f"vi{i:014x}"
            )
            for i in range(5)
        ]
        second_batch = first_batch + new_chunks
        second_emb = _make_synthetic_embeddings(second_batch, seed=11)
        v_b = write_chunks(
            second_batch, second_emb, lancedb_path=tmp_path / "lancedb"
        )
        info_b = read_corpus_version(tmp_path / "lancedb")
        assert info_b is not None
        assert info_b.version == v_b
        # Version strictly increments.
        assert v_a < v_b
        # And the post-write marker reports the post-write count.
        assert info_b.chunk_count == 10
