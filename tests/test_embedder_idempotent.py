"""Idempotent re-embed tests for E03_S02.

Coverage map:
  Acceptance criterion -> test
  ──────────────────────────────────────────────────────────────────────
  Re-running on unchanged corpus writes 0 rows + logs "all up to date"
                                          -> test_second_run_is_zero_writes
  Mismatched chunker_version forces re-embed
                                          -> test_chunker_version_mismatch_forces_reembed
  Mismatched embedder_version forces re-embed (additive correctness)
                                          -> test_embedder_version_mismatch_forces_reembed
  New chunks added since last embed are embedded; old skipped paper-by-paper
                                          -> test_new_chunk_is_embedded_others_skipped
  EXPECTED_CHUNKER_VERSION is alias for canonical CHUNKER_VERSION
                                          -> test_expected_chunker_version_is_alias
  Concurrent writes do not corrupt        -> test_concurrent_writes_do_not_corrupt
  Sidecar absence forces re-embed (migration path)
                                          -> test_missing_sidecar_forces_reembed
  Corrupt sidecar forces re-embed         -> test_corrupt_sidecar_forces_reembed
  run_summary aggregates chunks_skipped   -> test_run_summary_includes_chunks_skipped

The actual BGE-M3 model is mocked everywhere via the same
``_fake_model_factory`` pattern as ``test_embedder.py``. The skip path
takes ZERO model calls — that's how we observe the skip happened
(test_second_run_is_zero_writes asserts the fake model's call counter
stayed flat).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import patch

import numpy as np

import ingest.embedder as embedder_mod
from ingest.chunker_types import CHUNKER_VERSION
from ingest.embedder import (
    EMBEDDER_VERSION,
    EMBEDDING_DIM,
    EMBEDDINGS_MANIFEST_NAME,
    EXPECTED_CHUNKER_VERSION,
    _read_embeddings_manifest,
    _write_embeddings_manifest,
    _write_embeddings_npz,
    embed_corpus,
    embed_paper,
)

# ===========================================================================
# Helpers (mirror tests/test_embedder.py — kept local so future test changes
# stay isolated)
# ===========================================================================


def _stage_chunk_dir(
    tmp_path: Path, paper_id: str, chunks: list[dict]
) -> Path:
    paper_dir = tmp_path / "chunks" / paper_id
    paper_dir.mkdir(parents=True)
    manifest_entries = []
    for chunk in chunks:
        chunk_id = chunk["chunk_id"]
        hash_suffix = chunk_id.rsplit(":", 1)[-1]
        (paper_dir / f"{hash_suffix}.json").write_text(
            json.dumps(chunk, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest_entries.append({"chunk_id": chunk_id, "kind": chunk["kind"]})
    (paper_dir / "chunk_manifest.json").write_text(
        json.dumps(
            {
                "chunker_version": CHUNKER_VERSION,
                "chunks": manifest_entries,
                "paper_id": paper_id,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return paper_dir


def _make_chunk(
    paper_id: str, kind: str, body_text: str, *, suffix: str | None = None
) -> dict:
    import hashlib

    if suffix is None:
        suffix = hashlib.sha256(
            f"{kind}::{body_text}".encode()
        ).hexdigest()[:16]
    return {
        "body_text": body_text,
        "body_tokens": "tok1 tok2",
        "chunk_id": f"arxiv:{paper_id}:{suffix}",
        "chunker_version": CHUNKER_VERSION,
        "kind": kind,
        "paper_id": paper_id,
        "preamble_ref": None,
        "section_path": [],
        "theorem_label": None,
        "theorem_name": None,
        "truncated": False,
    }


def _fake_model_factory(emit_dim: int = EMBEDDING_DIM):
    """Same fake-model pattern as test_embedder.py with a call counter
    on the model so we can assert "model not invoked" on skip paths.
    """
    import torch

    class _FakeTokenizer:
        def __init__(self):
            self.calls: list[list[str]] = []

        def encode(self, text: str, add_special_tokens: bool = True) -> list[int]:
            n = len(text.split()) + (2 if add_special_tokens else 0)
            return list(range(n))

        def __call__(self, texts, **kwargs):
            self.calls.append(list(texts))
            if kwargs.get("return_length"):
                return {"length": [len(t.split()) + 2 for t in texts]}
            batch = len(texts)
            return {
                "input_ids": torch.zeros(batch, 4, dtype=torch.long),
                "attention_mask": torch.ones(batch, 4, dtype=torch.long),
            }

    class _FakeOutput:
        def __init__(self, batch: int, hidden: int, seed_base: int):
            rows = [
                torch.randn(
                    1, 4, hidden,
                    generator=torch.Generator().manual_seed(seed_base + i),
                    dtype=torch.float32,
                )
                for i in range(batch)
            ]
            self.last_hidden_state = torch.cat(rows, dim=0)

    class _FakeModel:
        def __init__(self):
            self.eval_called = False
            self.call_count = 0

        def eval(self):
            self.eval_called = True
            return self

        def __call__(self, **kwargs):
            self.call_count += 1
            batch = kwargs["input_ids"].shape[0]
            seed_base = 1000 * self.call_count
            return _FakeOutput(batch, emit_dim, seed_base)

    return _FakeTokenizer(), _FakeModel()


def _patched_embed_paper(
    tmp_path: Path,
    paper_id: str,
    *,
    fake_tokenizer=None,
    fake_model=None,
):
    """Run :func:`embed_paper` with all paths patched."""
    chunks_dir = tmp_path / "chunks"
    embeddings_dir = tmp_path / "embeddings"
    stats_path = tmp_path / "ops" / "embed-stats.jsonl"
    log_path = tmp_path / "ops" / "embed.log"

    if fake_tokenizer is None or fake_model is None:
        fake_tokenizer, fake_model = _fake_model_factory()

    from ingest.preamble_types import PreambleDoc

    preamble = PreambleDoc(
        paper_id=paper_id,
        source_hash="0" * 64,
        macros=[],
        preamble_text="",
        preamble_hash="0" * 16,
    )

    with (
        patch("ingest.embedder.CHUNKS_DIR", chunks_dir),
        patch("ingest.embedder.EMBEDDINGS_DIR", embeddings_dir),
        patch("ingest.embedder.EMBED_STATS_PATH", stats_path),
        patch("ingest.embedder.EMBED_LOG_PATH", log_path),
        patch("ingest.embedder.load_preamble", return_value=preamble),
        patch("ingest.embedder._get_tokenizer", return_value=fake_tokenizer),
        patch("ingest.embedder._get_model", return_value=fake_model),
    ):
        stats = embed_paper(paper_id)
    return stats, embeddings_dir, stats_path, fake_model


def _patched_embed_corpus(
    tmp_path: Path, *, fake_tokenizer=None, fake_model=None
):
    chunks_dir = tmp_path / "chunks"
    embeddings_dir = tmp_path / "embeddings"
    stats_path = tmp_path / "ops" / "embed-stats.jsonl"
    log_path = tmp_path / "ops" / "embed.log"
    if fake_tokenizer is None or fake_model is None:
        fake_tokenizer, fake_model = _fake_model_factory()
    from ingest.preamble_types import PreambleDoc

    preamble = PreambleDoc(
        paper_id="x",
        source_hash="0" * 64,
        macros=[],
        preamble_text="",
        preamble_hash="0" * 16,
    )
    with (
        patch("ingest.embedder.CHUNKS_DIR", chunks_dir),
        patch("ingest.embedder.EMBEDDINGS_DIR", embeddings_dir),
        patch("ingest.embedder.EMBED_STATS_PATH", stats_path),
        patch("ingest.embedder.EMBED_LOG_PATH", log_path),
        patch("ingest.embedder.load_preamble", return_value=preamble),
        patch("ingest.embedder._get_tokenizer", return_value=fake_tokenizer),
        patch("ingest.embedder._get_model", return_value=fake_model),
    ):
        results = embed_corpus(corpus_path=str(chunks_dir))
    return results, embeddings_dir, stats_path, fake_model


# ===========================================================================
# TestSingleSourceOfTruth — D2 of the synthesis
# ===========================================================================


class TestSingleSourceOfTruth:
    def test_expected_chunker_version_is_alias(self):
        # D2: EXPECTED_CHUNKER_VERSION must reference CHUNKER_VERSION,
        # not redefine the literal. Using `is` (object identity) catches
        # a future regression where someone redefines it as a string
        # literal — the value would be equal but identity differs.
        assert EXPECTED_CHUNKER_VERSION is CHUNKER_VERSION

    def test_expected_chunker_version_value(self):
        # And the equality check too, in case `is` semantics change
        # for short string interning.
        assert EXPECTED_CHUNKER_VERSION == CHUNKER_VERSION


# ===========================================================================
# TestZeroWritesOnRerun — the central acceptance criterion
# ===========================================================================


class TestZeroWritesOnRerun:
    def test_second_run_is_zero_writes(self, tmp_path):
        # Acceptance: re-running on an unchanged corpus writes 0 rows
        # AND the model is never called on the second run.
        paper_id = "2307.00100"
        _stage_chunk_dir(
            tmp_path,
            paper_id,
            [
                _make_chunk(paper_id, "stmt", "Body A", suffix="0" * 16),
                _make_chunk(paper_id, "proof", "Body B", suffix="1" * 16),
            ],
        )
        # First run: encode all chunks.
        stats_1, embeddings_dir, _, fake_model_1 = _patched_embed_paper(
            tmp_path, paper_id
        )
        assert stats_1.chunks_processed == 2
        assert stats_1.chunks_skipped == 0
        assert fake_model_1.call_count > 0
        # Sidecar should have landed.
        sidecar_path = embeddings_dir / paper_id / EMBEDDINGS_MANIFEST_NAME
        assert sidecar_path.exists()
        npz_path = embeddings_dir / paper_id / "embeddings.npz"
        assert npz_path.exists()
        # Capture mtimes to assert no rewrite on second run.
        npz_mtime_before = npz_path.stat().st_mtime_ns
        sidecar_mtime_before = sidecar_path.stat().st_mtime_ns

        # Second run: SAME corpus, fresh fake_model. Skip path must take
        # zero model calls.
        fake_tokenizer_2, fake_model_2 = _fake_model_factory()
        stats_2, _, _, _ = _patched_embed_paper(
            tmp_path,
            paper_id,
            fake_tokenizer=fake_tokenizer_2,
            fake_model=fake_model_2,
        )
        assert stats_2.chunks_processed == 0
        assert stats_2.chunks_skipped == 2
        assert fake_model_2.call_count == 0, (
            "model must NOT be invoked on the skip path"
        )
        # Files unchanged: same byte content, same mtime.
        assert npz_path.stat().st_mtime_ns == npz_mtime_before
        assert sidecar_path.stat().st_mtime_ns == sidecar_mtime_before

    def test_run_summary_includes_chunks_skipped(self, tmp_path, caplog):
        # D5 + D9: when an entire corpus is up to date, the run_summary
        # JSONL line carries the aggregate chunks_skipped, AND the
        # info-level "Skipped N/N chunks — all up to date." log fires.
        for paper_id in ("2307.00110", "2307.00111"):
            _stage_chunk_dir(
                tmp_path,
                paper_id,
                [_make_chunk(paper_id, "stmt", "Body", suffix="0" * 16)],
            )
        # First corpus pass — encode everything.
        _patched_embed_corpus(tmp_path)

        # Second pass — should be all skips.
        with caplog.at_level("INFO", logger="ingest.embedder"):
            results, _, stats_path, _ = _patched_embed_corpus(tmp_path)
        # All papers report skipped, none processed.
        assert all(r.chunks_processed == 0 for r in results)
        assert all(r.chunks_skipped > 0 for r in results)
        # The corpus-level log fires once.
        assert any(
            "all up to date" in rec.message.lower() for rec in caplog.records
        )
        # And the run_summary JSONL line carries chunks_skipped.
        lines = [
            json.loads(line)
            for line in stats_path.read_text(encoding="utf-8")
            .strip()
            .splitlines()
        ]
        run_summaries = [r for r in lines if r.get("event") == "run_summary"]
        assert len(run_summaries) == 2  # one per embed_corpus call
        # The second run_summary reports all-skipped.
        assert run_summaries[-1]["chunk_count"] == 0
        assert run_summaries[-1]["chunks_skipped"] >= 2


# ===========================================================================
# TestVersionMismatchForcesReembed — the "MVCC handshake"
# ===========================================================================


class TestVersionMismatchForcesReembed:
    def test_chunker_version_mismatch_forces_reembed(self, tmp_path):
        # Acceptance: a stale chunker_version in the sidecar triggers
        # a re-embed of that paper.
        paper_id = "2307.00120"
        _stage_chunk_dir(
            tmp_path,
            paper_id,
            [_make_chunk(paper_id, "stmt", "Body", suffix="0" * 16)],
        )
        # First run: produce a fresh sidecar.
        _patched_embed_paper(tmp_path, paper_id)
        sidecar_path = (
            tmp_path / "embeddings" / paper_id / EMBEDDINGS_MANIFEST_NAME
        )
        # Tamper with the sidecar's chunker_version.
        sidecar_data = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sidecar_data["chunker_version"] = "v0.9"
        sidecar_path.write_text(
            json.dumps(sidecar_data, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        # Second run: must re-embed (model invoked) because version
        # mismatched.
        fake_tokenizer, fake_model = _fake_model_factory()
        stats, _, _, _ = _patched_embed_paper(
            tmp_path,
            paper_id,
            fake_tokenizer=fake_tokenizer,
            fake_model=fake_model,
        )
        assert stats.chunks_processed == 1
        assert stats.chunks_skipped == 0
        assert fake_model.call_count > 0
        # And the sidecar is now refreshed to the canonical version.
        new_sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        assert new_sidecar["chunker_version"] == EXPECTED_CHUNKER_VERSION

    def test_embedder_version_mismatch_forces_reembed(self, tmp_path):
        # D7 additive correctness: a stale embedder_version (model SHA
        # bump) triggers re-embed even when chunker_version matches.
        paper_id = "2307.00121"
        _stage_chunk_dir(
            tmp_path,
            paper_id,
            [_make_chunk(paper_id, "stmt", "Body", suffix="0" * 16)],
        )
        _patched_embed_paper(tmp_path, paper_id)
        sidecar_path = (
            tmp_path / "embeddings" / paper_id / EMBEDDINGS_MANIFEST_NAME
        )
        sidecar_data = json.loads(sidecar_path.read_text(encoding="utf-8"))
        sidecar_data["embedder_version"] = "bge-m3@deadbeef"
        sidecar_path.write_text(
            json.dumps(sidecar_data, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        fake_tokenizer, fake_model = _fake_model_factory()
        stats, _, _, _ = _patched_embed_paper(
            tmp_path,
            paper_id,
            fake_tokenizer=fake_tokenizer,
            fake_model=fake_model,
        )
        assert stats.chunks_processed == 1
        assert fake_model.call_count > 0


# ===========================================================================
# TestNewChunkPath — partial-paper updates
# ===========================================================================


class TestNewChunkPath:
    def test_new_chunk_is_embedded_others_skipped(self, tmp_path):
        # D8 / acceptance: when one paper gains a new chunk, the entire
        # paper is rewritten (np.savez has no partial-update). When
        # OTHER papers are unchanged, they're individually skipped.
        # Stage two papers, embed, then add a chunk to paper A only.
        paper_a = "2307.00130"
        paper_b = "2307.00131"
        _stage_chunk_dir(
            tmp_path,
            paper_a,
            [
                _make_chunk(paper_a, "stmt", "Body A1", suffix="a" * 16),
                _make_chunk(paper_a, "stmt", "Body A2", suffix="b" * 16),
            ],
        )
        _stage_chunk_dir(
            tmp_path,
            paper_b,
            [_make_chunk(paper_b, "stmt", "Body B1", suffix="c" * 16)],
        )
        # First corpus run.
        results_1, _, _, _ = _patched_embed_corpus(tmp_path)
        for r in results_1:
            assert r.chunks_processed > 0  # all encoded fresh

        # Add a new chunk to paper A only. We have to re-stage because
        # adding a chunk requires writing both the per-chunk JSON and
        # updating the manifest.
        new_chunks_a = [
            _make_chunk(paper_a, "stmt", "Body A1", suffix="a" * 16),
            _make_chunk(paper_a, "stmt", "Body A2", suffix="b" * 16),
            _make_chunk(paper_a, "stmt", "Body A3", suffix="d" * 16),
        ]
        # Wipe and re-stage paper A's chunk dir.
        import shutil

        shutil.rmtree(tmp_path / "chunks" / paper_a)
        _stage_chunk_dir(tmp_path, paper_a, new_chunks_a)

        # Second corpus run.
        results_2, embeddings_dir, _, fake_model_2 = _patched_embed_corpus(
            tmp_path
        )
        by_paper = {r.paper_id: r for r in results_2}
        # Paper A: re-embedded entirely (3 chunks).
        assert by_paper[paper_a].chunks_processed == 3
        assert by_paper[paper_a].chunks_skipped == 0
        # Paper B: skipped.
        assert by_paper[paper_b].chunks_processed == 0
        assert by_paper[paper_b].chunks_skipped == 1
        # The model was called for paper A only — verify by counting
        # embeddings written to paper A's NPZ.
        npz_a = np.load(
            embeddings_dir / paper_a / "embeddings.npz", allow_pickle=True
        )
        assert npz_a["embedding_stmt"].shape == (3, EMBEDDING_DIM)
        # Paper A's sidecar covers all three chunks.
        sidecar_a = json.loads(
            (
                embeddings_dir / paper_a / EMBEDDINGS_MANIFEST_NAME
            ).read_text(encoding="utf-8")
        )
        assert len(sidecar_a["embedded_chunks"]) == 3


# ===========================================================================
# TestSidecarMigration — the absence-of-sidecar / corruption paths
# ===========================================================================


class TestSidecarMigration:
    def test_missing_sidecar_forces_reembed(self, tmp_path):
        # Pre-E03_S02 NPZs have no sidecar. The reader treats this as
        # "unknown provenance" and re-embeds — also the migration path
        # for any partial-write scenario where the sidecar didn't land.
        paper_id = "2307.00140"
        _stage_chunk_dir(
            tmp_path,
            paper_id,
            [_make_chunk(paper_id, "stmt", "Body", suffix="0" * 16)],
        )
        _patched_embed_paper(tmp_path, paper_id)
        sidecar_path = (
            tmp_path / "embeddings" / paper_id / EMBEDDINGS_MANIFEST_NAME
        )
        sidecar_path.unlink()  # delete sidecar; NPZ remains
        fake_tokenizer, fake_model = _fake_model_factory()
        stats, _, _, _ = _patched_embed_paper(
            tmp_path,
            paper_id,
            fake_tokenizer=fake_tokenizer,
            fake_model=fake_model,
        )
        assert stats.chunks_processed == 1
        assert fake_model.call_count > 0
        assert sidecar_path.exists()  # sidecar regenerated

    def test_corrupt_sidecar_forces_reembed(self, tmp_path):
        # Self-healing discipline (mirrors preamble._read_existing_preamble).
        paper_id = "2307.00141"
        _stage_chunk_dir(
            tmp_path,
            paper_id,
            [_make_chunk(paper_id, "stmt", "Body", suffix="0" * 16)],
        )
        _patched_embed_paper(tmp_path, paper_id)
        sidecar_path = (
            tmp_path / "embeddings" / paper_id / EMBEDDINGS_MANIFEST_NAME
        )
        sidecar_path.write_text("{not valid json", encoding="utf-8")
        fake_tokenizer, fake_model = _fake_model_factory()
        stats, _, _, _ = _patched_embed_paper(
            tmp_path,
            paper_id,
            fake_tokenizer=fake_tokenizer,
            fake_model=fake_model,
        )
        assert stats.chunks_processed == 1
        assert fake_model.call_count > 0


# ===========================================================================
# TestSidecarSchema — BP1 byte-stability
# ===========================================================================


class TestSidecarSchema:
    def test_sidecar_has_alphabetical_keys_and_no_timestamps(self, tmp_path):
        # BP1: keys sorted, no timestamps. The serialized bytes must be
        # deterministic for the same input.
        paper_id = "2307.00150"
        _stage_chunk_dir(
            tmp_path,
            paper_id,
            [
                _make_chunk(paper_id, "stmt", "Body A", suffix="0" * 16),
                _make_chunk(paper_id, "proof", "Body B", suffix="1" * 16),
            ],
        )
        _patched_embed_paper(tmp_path, paper_id)
        sidecar_path = (
            tmp_path / "embeddings" / paper_id / EMBEDDINGS_MANIFEST_NAME
        )
        raw = sidecar_path.read_text(encoding="utf-8")
        sidecar = json.loads(raw)
        # Top-level keys are exactly the four expected, alphabetical.
        assert list(sidecar.keys()) == [
            "chunker_version",
            "embedded_chunks",
            "embedder_version",
            "paper_id",
        ]
        # No timestamp fields — load-bearing for BP1.
        for key in sidecar:
            assert "time" not in key.lower()
            assert "date" not in key.lower()
            assert "_at" not in key
        # Values match the canonical constants.
        assert sidecar["chunker_version"] == EXPECTED_CHUNKER_VERSION
        assert sidecar["embedder_version"] == EMBEDDER_VERSION
        assert sidecar["paper_id"] == paper_id

    def test_embedded_chunks_in_document_order(self, tmp_path):
        # D7: embedded_chunks list order matches manifest order so two
        # runs with identical inputs produce a byte-identical sidecar.
        paper_id = "2307.00151"
        chunks = [
            _make_chunk(paper_id, "stmt", "Body A", suffix="a" * 16),
            _make_chunk(paper_id, "proof", "Body B", suffix="b" * 16),
            _make_chunk(paper_id, "section", "Body C", suffix="c" * 16),
        ]
        _stage_chunk_dir(tmp_path, paper_id, chunks)
        _patched_embed_paper(tmp_path, paper_id)
        sidecar = json.loads(
            (
                tmp_path / "embeddings" / paper_id / EMBEDDINGS_MANIFEST_NAME
            ).read_text(encoding="utf-8")
        )
        sidecar_chunk_ids = [e["chunk_id"] for e in sidecar["embedded_chunks"]]
        manifest_chunk_ids = [c["chunk_id"] for c in chunks]
        assert sidecar_chunk_ids == manifest_chunk_ids


# ===========================================================================
# TestConcurrency — POSIX os.replace atomicity (D3)
# ===========================================================================


class TestConcurrency:
    def test_concurrent_writes_do_not_corrupt(self, tmp_path):
        # Two threads write to the same NPZ + sidecar pair via the
        # writers' tmp + os.replace pattern. Last writer wins; neither
        # reader ever sees a partial file. BP1 byte-stability means
        # both writers' outputs would be byte-identical on identical
        # input.
        out_dir = tmp_path / "embeddings" / "2307.00160"
        out_dir.mkdir(parents=True)
        npz_path = out_dir / "embeddings.npz"
        sidecar_path = out_dir / EMBEDDINGS_MANIFEST_NAME

        chunk_ids = ["arxiv:2307.00160:" + "0" * 16]
        emb = np.zeros((1, EMBEDDING_DIM), dtype=np.float32)

        def _writer():
            for _ in range(10):
                _write_embeddings_npz(
                    npz_path,
                    chunk_ids_stmt=chunk_ids,
                    embedding_stmt=emb,
                    chunk_ids_proof=[],
                    embedding_proof=np.zeros(
                        (0, EMBEDDING_DIM), dtype=np.float32
                    ),
                )
                _write_embeddings_manifest(
                    sidecar_path,
                    paper_id="2307.00160",
                    embedded_chunks=[
                        {"chunk_id": chunk_ids[0], "kind": "stmt"}
                    ],
                )

        t1 = threading.Thread(target=_writer)
        t2 = threading.Thread(target=_writer)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        # Both files exist and parse cleanly.
        assert npz_path.exists()
        assert sidecar_path.exists()
        npz = np.load(npz_path, allow_pickle=True)
        assert npz["embedding_stmt"].shape == (1, EMBEDDING_DIM)
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        assert sidecar["paper_id"] == "2307.00160"
        # No tmp leaks.
        leftover = list(out_dir.glob("*.tmp"))
        assert leftover == []


# ===========================================================================
# TestPaperUpToDateHelper — exercise the helper directly
# ===========================================================================


class TestPaperUpToDateHelper:
    def test_returns_false_when_sidecar_missing(self, tmp_path):
        with patch("ingest.embedder.EMBEDDINGS_DIR", tmp_path):
            assert not embedder_mod._paper_is_up_to_date(
                "2307.00170", {"arxiv:2307.00170:" + "0" * 16}
            )

    def test_returns_false_on_wrong_chunker_version(self, tmp_path):
        out_path = tmp_path / "2307.00171" / EMBEDDINGS_MANIFEST_NAME
        out_path.parent.mkdir(parents=True)
        out_path.write_text(
            json.dumps(
                {
                    "chunker_version": "v0.9",
                    "embedded_chunks": [
                        {
                            "chunk_id": "arxiv:2307.00171:" + "0" * 16,
                            "kind": "stmt",
                        }
                    ],
                    "embedder_version": EMBEDDER_VERSION,
                    "paper_id": "2307.00171",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        with patch("ingest.embedder.EMBEDDINGS_DIR", tmp_path):
            assert not embedder_mod._paper_is_up_to_date(
                "2307.00171", {"arxiv:2307.00171:" + "0" * 16}
            )

    def test_returns_false_when_chunk_missing_from_sidecar(self, tmp_path):
        # Sidecar covers chunk A only; manifest now says {A, B}. Must
        # re-embed because B is new.
        out_path = tmp_path / "2307.00172" / EMBEDDINGS_MANIFEST_NAME
        out_path.parent.mkdir(parents=True)
        out_path.write_text(
            json.dumps(
                {
                    "chunker_version": EXPECTED_CHUNKER_VERSION,
                    "embedded_chunks": [
                        {
                            "chunk_id": "arxiv:2307.00172:" + "a" * 16,
                            "kind": "stmt",
                        }
                    ],
                    "embedder_version": EMBEDDER_VERSION,
                    "paper_id": "2307.00172",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        with patch("ingest.embedder.EMBEDDINGS_DIR", tmp_path):
            assert not embedder_mod._paper_is_up_to_date(
                "2307.00172",
                {
                    "arxiv:2307.00172:" + "a" * 16,
                    "arxiv:2307.00172:" + "b" * 16,
                },
            )

    def test_returns_true_when_all_match(self, tmp_path):
        out_path = tmp_path / "2307.00173" / EMBEDDINGS_MANIFEST_NAME
        out_path.parent.mkdir(parents=True)
        out_path.write_text(
            json.dumps(
                {
                    "chunker_version": EXPECTED_CHUNKER_VERSION,
                    "embedded_chunks": [
                        {
                            "chunk_id": "arxiv:2307.00173:" + "a" * 16,
                            "kind": "stmt",
                        }
                    ],
                    "embedder_version": EMBEDDER_VERSION,
                    "paper_id": "2307.00173",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        with patch("ingest.embedder.EMBEDDINGS_DIR", tmp_path):
            assert embedder_mod._paper_is_up_to_date(
                "2307.00173", {"arxiv:2307.00173:" + "a" * 16}
            )


# ===========================================================================
# TestSidecarReadHelpers — exercise the read helper directly
# ===========================================================================


class TestSidecarReadHelpers:
    def test_read_returns_none_for_missing(self, tmp_path):
        assert _read_embeddings_manifest(tmp_path / "absent.json") is None

    def test_read_returns_none_for_corrupt(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("{not valid json", encoding="utf-8")
        assert _read_embeddings_manifest(path) is None

    def test_round_trip(self, tmp_path):
        path = tmp_path / "ok.json"
        _write_embeddings_manifest(
            path,
            paper_id="2307.00180",
            embedded_chunks=[
                {"chunk_id": "arxiv:2307.00180:" + "0" * 16, "kind": "stmt"}
            ],
        )
        data = _read_embeddings_manifest(path)
        assert data is not None
        assert data["paper_id"] == "2307.00180"
        assert data["chunker_version"] == EXPECTED_CHUNKER_VERSION
        assert data["embedder_version"] == EMBEDDER_VERSION
