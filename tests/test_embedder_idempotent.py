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
import shutil
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

import arxmcp.ingest.embedder as embedder_mod
from arxmcp.corpus.chunk import (
    CHUNKER_VERSION,
    EMBED_INPUT_POLICY_VERSION,
    EMBEDDING_DIM,
    reuse_identity,
)
from arxmcp.corpus.embedding import (
    EMBEDDER_VERSION,
    EMBEDDINGS_MANIFEST_NAME,
    read_embeddings_manifest,
)
from arxmcp.ingest.embedder import (
    EXPECTED_CHUNKER_VERSION,
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
            # Closes F10 from E03_S02: 1_000_000 multiplier so
            # cross-batch seed collision is practically impossible.
            seed_base = 1_000_000 * self.call_count
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

    with (
        patch("arxmcp.ingest.embedder.CHUNKS_DIR", chunks_dir),
        patch("arxmcp.ingest.embedder.EMBEDDINGS_DIR", embeddings_dir),
        patch("arxmcp.ingest.embedder.EMBED_STATS_PATH", stats_path),
        patch("arxmcp.ingest.embedder.EMBED_LOG_PATH", log_path),
        patch("arxmcp.ingest.embedder.get_embedding_tokenizer", return_value=fake_tokenizer),
        patch("arxmcp.ingest.embedder.get_embedding_model", return_value=fake_model),
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
    with (
        patch("arxmcp.ingest.embedder.CHUNKS_DIR", chunks_dir),
        patch("arxmcp.ingest.embedder.EMBEDDINGS_DIR", embeddings_dir),
        patch("arxmcp.ingest.embedder.EMBED_STATS_PATH", stats_path),
        patch("arxmcp.ingest.embedder.EMBED_LOG_PATH", log_path),
        patch("arxmcp.ingest.embedder.get_embedding_tokenizer", return_value=fake_tokenizer),
        patch("arxmcp.ingest.embedder.get_embedding_model", return_value=fake_model),
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
        with caplog.at_level("INFO", logger="arxmcp.ingest.embedder"):
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
        # Top-level keys are alphabetical and include the input policy.
        assert list(sidecar.keys()) == [
            "chunker_version",
            "embed_input_policy_version",
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
        assert sidecar["embed_input_policy_version"] == EMBED_INPUT_POLICY_VERSION
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


def _ident(kind: str, body: str) -> str:
    return reuse_identity(kind, body, embedder_version=EMBEDDER_VERSION)


def _write_sidecar(
    paper_dir: Path,
    entries: list[dict],
    *,
    chunker_version: str = EXPECTED_CHUNKER_VERSION,
    npz: bool = True,
) -> None:
    paper_dir.mkdir(parents=True)
    if npz:
        # The helper requires the NPZ to exist alongside the
        # sidecar; a stub file is enough for the helper.
        (paper_dir / "embeddings.npz").write_bytes(b"")
    (paper_dir / EMBEDDINGS_MANIFEST_NAME).write_text(
        json.dumps(
            {
                "chunker_version": chunker_version,
                "embedded_chunks": entries,
                "embedder_version": EMBEDDER_VERSION,
                "embed_input_policy_version": EMBED_INPUT_POLICY_VERSION,
                "paper_id": paper_dir.name,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


class TestPaperUpToDateHelper:
    A = "arxiv:2307.00173:" + "a" * 16
    B = "arxiv:2307.00173:" + "b" * 16
    C = "arxiv:2307.00173:" + "c" * 16

    def _entry(self, cid: str, kind: str, body: str) -> dict:
        return {"chunk_id": cid, "kind": kind, "reuse_identity": _ident(kind, body)}

    def test_returns_false_when_sidecar_missing(self, tmp_path):
        with patch("arxmcp.ingest.embedder.EMBEDDINGS_DIR", tmp_path):
            assert not embedder_mod._paper_is_up_to_date(
                "2307.00173", {self.A: _ident("stmt", "Body A")}
            )

    def test_returns_false_on_wrong_chunker_version(self, tmp_path):
        _write_sidecar(
            tmp_path / "2307.00173",
            [self._entry(self.A, "stmt", "Body A")],
            chunker_version="v0.9",
        )
        with patch("arxmcp.ingest.embedder.EMBEDDINGS_DIR", tmp_path):
            assert not embedder_mod._paper_is_up_to_date(
                "2307.00173", {self.A: _ident("stmt", "Body A")}
            )

    def test_returns_false_when_chunk_missing_from_sidecar(self, tmp_path):
        # Sidecar covers chunk A only; the paper now has {A, B}.
        _write_sidecar(tmp_path / "2307.00173", [self._entry(self.A, "stmt", "Body A")])
        with patch("arxmcp.ingest.embedder.EMBEDDINGS_DIR", tmp_path):
            assert not embedder_mod._paper_is_up_to_date(
                "2307.00173",
                {self.A: _ident("stmt", "Body A"), self.B: _ident("stmt", "Body B")},
            )

    def test_returns_true_only_when_ids_and_identities_match(self, tmp_path):
        _write_sidecar(tmp_path / "2307.00173", [self._entry(self.A, "stmt", "Body A")])
        with patch("arxmcp.ingest.embedder.EMBEDDINGS_DIR", tmp_path):
            assert embedder_mod._paper_is_up_to_date(
                "2307.00173", {self.A: _ident("stmt", "Body A")}
            )
            # Same chunk id, now on the proof route: not reusable.
            assert not embedder_mod._paper_is_up_to_date(
                "2307.00173", {self.A: _ident("proof", "Body A")}
            )
            # Same chunk id, different embedding input: not reusable.
            assert not embedder_mod._paper_is_up_to_date(
                "2307.00173", {self.A: _ident("stmt", "Body A, edited")}
            )

    def test_entry_without_reuse_identity_forces_reembed(self, tmp_path):
        # An older sidecar has bare {chunk_id, kind} entries; it is never
        # a source of reuse.
        _write_sidecar(
            tmp_path / "2307.00173", [{"chunk_id": self.A, "kind": "stmt"}]
        )
        with patch("arxmcp.ingest.embedder.EMBEDDINGS_DIR", tmp_path):
            assert not embedder_mod._paper_is_up_to_date(
                "2307.00173", {self.A: _ident("stmt", "Body A")}
            )

    def test_returns_false_when_npz_missing(self, tmp_path):
        # Closes F1 (CRITICAL) from the E03_S02 critique: a sidecar
        # claiming an embedding exists, with the actual NPZ missing,
        # MUST trigger re-embed — not silently skip the paper.
        _write_sidecar(
            tmp_path / "2307.00173",
            [self._entry(self.A, "stmt", "Body A")],
            npz=False,
        )
        with patch("arxmcp.ingest.embedder.EMBEDDINGS_DIR", tmp_path):
            assert not embedder_mod._paper_is_up_to_date(
                "2307.00173", {self.A: _ident("stmt", "Body A")}
            )

    def test_returns_false_on_malformed_sidecar_entry(self, tmp_path):
        # An entry that is a dict missing chunk_id must force
        # a re-embed.
        _write_sidecar(tmp_path / "2307.00173", [{"kind": "stmt"}])
        with patch("arxmcp.ingest.embedder.EMBEDDINGS_DIR", tmp_path):
            assert not embedder_mod._paper_is_up_to_date(
                "2307.00173", {self.A: _ident("stmt", "Body A")}
            )

    def test_entry_for_a_chunk_no_longer_current_forces_reembed(self, tmp_path):
        # A sidecar with MORE chunks than the paper now has is not up to
        # date: the extra entry's vector would otherwise stay in the NPZ.
        _write_sidecar(
            tmp_path / "2307.00173",
            [
                self._entry(self.A, "stmt", "Body A"),
                self._entry(self.B, "proof", "Body B"),
                self._entry(self.C, "stmt", "Body C"),
            ],
        )
        with patch("arxmcp.ingest.embedder.EMBEDDINGS_DIR", tmp_path):
            assert not embedder_mod._paper_is_up_to_date(
                "2307.00173",
                {self.A: _ident("stmt", "Body A"), self.B: _ident("proof", "Body B")},
            )


# ===========================================================================
# TestReuseIdentitySkip — the skip decision through embed_paper
# ===========================================================================


class TestReuseIdentitySkip:
    """Reuse by identity at the embedder: the sidecar stores each chunk's
    reuse identity, and a paper is skipped only when every current chunk's
    identity matches. A chunk id match alone never reuses a vector."""

    def _sidecar(self, tmp_path: Path, paper_id: str) -> dict:
        path = tmp_path / "embeddings" / paper_id / EMBEDDINGS_MANIFEST_NAME
        return json.loads(path.read_text(encoding="utf-8"))

    def test_sidecar_entries_carry_reuse_identity(self, tmp_path):
        paper_id = "2307.00190"
        chunks = [
            _make_chunk(paper_id, "stmt", "Body A", suffix="0" * 16),
            _make_chunk(paper_id, "proof", "Body B", suffix="1" * 16),
        ]
        _stage_chunk_dir(tmp_path, paper_id, chunks)
        _patched_embed_paper(tmp_path, paper_id)
        entries = self._sidecar(tmp_path, paper_id)["embedded_chunks"]
        assert entries == [
            {
                "chunk_id": c["chunk_id"],
                "kind": c["kind"],
                "reuse_identity": _ident(c["kind"], c["body_text"]),
            }
            for c in chunks
        ]

    def test_pre_identity_sidecar_forces_one_reembed(self, tmp_path):
        paper_id = "2307.00191"
        _stage_chunk_dir(
            tmp_path, paper_id, [_make_chunk(paper_id, "stmt", "Body A", suffix="0" * 16)]
        )
        _patched_embed_paper(tmp_path, paper_id)
        path = tmp_path / "embeddings" / paper_id / EMBEDDINGS_MANIFEST_NAME
        legacy = self._sidecar(tmp_path, paper_id)
        for entry in legacy["embedded_chunks"]:
            del entry["reuse_identity"]
        path.write_text(json.dumps(legacy, sort_keys=True), encoding="utf-8")

        stats, _, _, model = _patched_embed_paper(tmp_path, paper_id)
        assert stats.chunks_processed == 1
        assert model.call_count > 0
        assert "reuse_identity" in self._sidecar(tmp_path, paper_id)["embedded_chunks"][0]

        # The rewritten sidecar is reusable: the next run skips.
        stats, _, _, model = _patched_embed_paper(tmp_path, paper_id)
        assert stats.chunks_skipped == 1
        assert model.call_count == 0

    def test_same_chunk_id_on_other_route_is_reembedded(self, tmp_path):
        # The wrong-route case: the chunk id does not hash the kind, so a
        # re-chunk can return the same id on the proof route.
        paper_id = "2307.00192"
        _stage_chunk_dir(
            tmp_path, paper_id, [_make_chunk(paper_id, "section", "Body A", suffix="0" * 16)]
        )
        _patched_embed_paper(tmp_path, paper_id)
        shutil.rmtree(tmp_path / "chunks" / paper_id)
        _stage_chunk_dir(
            tmp_path, paper_id, [_make_chunk(paper_id, "proof", "Body A", suffix="0" * 16)]
        )

        stats, embeddings_dir, _, model = _patched_embed_paper(tmp_path, paper_id)
        assert stats.chunks_processed == 1
        assert model.call_count > 0
        npz = np.load(embeddings_dir / paper_id / "embeddings.npz", allow_pickle=True)
        assert list(npz["chunk_ids_proof"]) == [f"arxiv:{paper_id}:" + "0" * 16]
        assert list(npz["chunk_ids_stmt"]) == []

    def test_a_removed_chunk_leaves_the_npz_on_the_next_run(self, tmp_path):
        paper_id = "2307.00193"
        kept = _make_chunk(paper_id, "stmt", "Body A", suffix="0" * 16)
        removed = _make_chunk(paper_id, "proof", "Body B", suffix="1" * 16)
        _stage_chunk_dir(tmp_path, paper_id, [kept, removed])
        _patched_embed_paper(tmp_path, paper_id)
        shutil.rmtree(tmp_path / "chunks" / paper_id)
        _stage_chunk_dir(tmp_path, paper_id, [kept])

        stats, embeddings_dir, _, model = _patched_embed_paper(tmp_path, paper_id)
        assert stats.chunks_processed == 1
        assert model.call_count > 0
        npz = np.load(embeddings_dir / paper_id / "embeddings.npz", allow_pickle=True)
        assert list(npz["chunk_ids_stmt"]) == [kept["chunk_id"]]
        assert list(npz["chunk_ids_proof"]) == []
        entries = self._sidecar(tmp_path, paper_id)["embedded_chunks"]
        assert [e["chunk_id"] for e in entries] == [kept["chunk_id"]]

        # With the orphan gone the paper is up to date again.
        stats, _, _, model = _patched_embed_paper(tmp_path, paper_id)
        assert stats.chunks_skipped == 1
        assert model.call_count == 0


# ===========================================================================
# TestSidecarReadHelpers — exercise the read helper directly
# ===========================================================================


class TestSidecarReadHelpers:
    def test_read_returns_none_for_missing(self, tmp_path):
        assert read_embeddings_manifest(tmp_path / "absent.json") is None

    def test_read_returns_none_for_corrupt(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("{not valid json", encoding="utf-8")
        assert read_embeddings_manifest(path) is None

    def test_round_trip(self, tmp_path):
        path = tmp_path / "ok.json"
        _write_embeddings_manifest(
            path,
            paper_id="2307.00180",
            embedded_chunks=[
                {"chunk_id": "arxiv:2307.00180:" + "0" * 16, "kind": "stmt"}
            ],
        )
        data = read_embeddings_manifest(path)
        assert data is not None
        assert data["paper_id"] == "2307.00180"
        assert data["chunker_version"] == EXPECTED_CHUNKER_VERSION
        assert data["embedder_version"] == EMBEDDER_VERSION


# ===========================================================================
# TestMissingNpzReembed — F1 regression at the public-API level
# ===========================================================================


class TestMissingNpzReembed:
    def test_missing_npz_with_present_sidecar_forces_reembed(self, tmp_path):
        # F1 (CRITICAL): if a user manually deletes the NPZ but leaves
        # the sidecar (manual cleanup, fs corruption recovery, etc.),
        # the next embed run MUST re-encode rather than silently skip.
        paper_id = "2307.00190"
        _stage_chunk_dir(
            tmp_path,
            paper_id,
            [_make_chunk(paper_id, "stmt", "Body", suffix="0" * 16)],
        )
        # First run: produce both files.
        _patched_embed_paper(tmp_path, paper_id)
        npz_path = tmp_path / "embeddings" / paper_id / "embeddings.npz"
        sidecar_path = (
            tmp_path / "embeddings" / paper_id / EMBEDDINGS_MANIFEST_NAME
        )
        assert npz_path.exists()
        assert sidecar_path.exists()
        # Now delete just the NPZ (sidecar lingers, claiming up-to-date).
        npz_path.unlink()
        # Second run: must re-embed.
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
        # And the NPZ is back.
        assert npz_path.exists()


# ===========================================================================
# TestSidecarByteStability — F4: BP1 byte-identical sidecars across runs
# ===========================================================================


class TestSidecarByteStability:
    def test_sidecar_bytes_are_run_over_run_stable(self, tmp_path):
        # F4: a deterministic embedder must produce a byte-identical
        # sidecar on a repeat run (same inputs → same bytes). The
        # current "second run is zero writes" tests prove the skip
        # path AVOIDED writing; this proves the WRITE itself is
        # byte-stable.
        paper_id = "2307.00200"
        _stage_chunk_dir(
            tmp_path,
            paper_id,
            [
                _make_chunk(paper_id, "stmt", "Body A", suffix="a" * 16),
                _make_chunk(paper_id, "proof", "Body B", suffix="b" * 16),
                _make_chunk(paper_id, "section", "Body C", suffix="c" * 16),
            ],
        )
        _patched_embed_paper(tmp_path, paper_id)
        sidecar_path = (
            tmp_path / "embeddings" / paper_id / EMBEDDINGS_MANIFEST_NAME
        )
        first_bytes = sidecar_path.read_bytes()
        # Force a re-write by deleting the sidecar (so the skip path
        # doesn't short-circuit), then run again.
        sidecar_path.unlink()
        # Also delete the NPZ so the helper sees both as missing — but
        # actually a present NPZ would not impact the sidecar bytes.
        # Delete it for symmetry with the F1 fix invariant: NPZ alone
        # without sidecar must trigger re-embed.
        (tmp_path / "embeddings" / paper_id / "embeddings.npz").unlink()
        _patched_embed_paper(tmp_path, paper_id)
        second_bytes = sidecar_path.read_bytes()
        # BP1: byte-identical.
        assert first_bytes == second_bytes


# ===========================================================================
# TestDuplicateChunkIdRejected — F8 corruption-detection
# ===========================================================================


class TestDuplicateChunkIdRejected:
    def test_duplicate_chunk_id_in_manifest_raises_corrupt(self, tmp_path):
        # F8: a duplicate chunk_id in chunk_manifest.json is a
        # corruption signal. The embedder must surface it as a fail
        # row rather than silently dedup.
        paper_id = "2307.00210"
        # Construct a manifest with duplicate chunk_id manually
        # (helper functions deduplicate in their data structure).
        paper_dir = tmp_path / "chunks" / paper_id
        paper_dir.mkdir(parents=True)
        chunk = _make_chunk(paper_id, "stmt", "Body", suffix="0" * 16)
        (paper_dir / ("0" * 16 + ".json")).write_text(
            json.dumps(chunk, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (paper_dir / "chunk_manifest.json").write_text(
            json.dumps(
                {
                    "chunker_version": CHUNKER_VERSION,
                    "chunks": [
                        {"chunk_id": chunk["chunk_id"], "kind": "stmt"},
                        {
                            "chunk_id": chunk["chunk_id"],
                            "kind": "stmt",
                        },  # DUPLICATE
                    ],
                    "paper_id": paper_id,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        chunks_dir = tmp_path / "chunks"
        embeddings_dir = tmp_path / "embeddings"
        stats_path = tmp_path / "ops" / "embed-stats.jsonl"
        log_path = tmp_path / "ops" / "embed.log"
        with (
            patch("arxmcp.ingest.embedder.CHUNKS_DIR", chunks_dir),
            patch("arxmcp.ingest.embedder.EMBEDDINGS_DIR", embeddings_dir),
            patch("arxmcp.ingest.embedder.EMBED_STATS_PATH", stats_path),
            patch("arxmcp.ingest.embedder.EMBED_LOG_PATH", log_path),
        ):
            stats = embed_paper(paper_id)
        assert stats.status == "fail"
        assert stats.error_class == "manifest_corrupt"
        assert "duplicate" in (stats.error or "").lower()


# ===========================================================================
# TestMultiProcessConcurrency — F2: multi-process AC coverage
# ===========================================================================


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "This stress test relies on os.replace() being an atomic "
        "overwrite while a CONCURRENT process holds the destination (a "
        "POSIX rename guarantee). On Windows os.replace() raises "
        "PermissionError (WinError 5) when the target is held, so one of "
        "two racing writers to the SAME embeddings.npz fails loud. The "
        "no-corruption invariant still holds (the loser errors instead of "
        "writing garbage), but the test asserts BOTH writers exit 0, which "
        "cannot hold under Windows rename semantics."
    ),
)
class TestMultiProcessConcurrency:
    def test_concurrent_processes_do_not_corrupt(self, tmp_path):
        # F2: AC #5 says "two embedder PROCESSES run concurrently". The
        # threading-only test in TestConcurrency does not exercise
        # multi-process os.replace atomicity (the GIL serializes
        # threaded np.savez anyway). Use subprocess.Popen so both
        # writers are real OS processes — multiprocessing.Process can't
        # serialize a function defined inside a test method on Python
        # 3.13's spawn context.
        import subprocess
        import sys
        import textwrap

        out_dir = tmp_path / "embeddings" / "2307.00220"
        out_dir.mkdir(parents=True)
        npz_path = out_dir / "embeddings.npz"
        sidecar_path = out_dir / EMBEDDINGS_MANIFEST_NAME

        # The writer script runs in a fresh Python interpreter; it
        # imports from arxmcp.ingest.embedder (the project's own package on
        # the path) and races against a sibling instance for 5
        # iterations of (NPZ + sidecar) writes. ``os.replace`` is
        # POSIX-atomic; both writers should produce a clean final
        # state regardless of interleaving.
        writer_script = textwrap.dedent(
            f"""
            import sys
            from pathlib import Path
            sys.path.insert(0, {str(Path(__file__).parent.parent)!r})
            import numpy as np
            from arxmcp.ingest.embedder import (
                EMBEDDING_DIM,
                _write_embeddings_manifest,
                _write_embeddings_npz,
            )
            chunk_ids = ["arxiv:2307.00220:" + "0" * 16]
            emb = np.zeros((1, EMBEDDING_DIM), dtype=np.float32)
            for _ in range(5):
                _write_embeddings_npz(
                    Path({str(npz_path)!r}),
                    chunk_ids_stmt=chunk_ids,
                    embedding_stmt=emb,
                    chunk_ids_proof=[],
                    embedding_proof=np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
                )
                _write_embeddings_manifest(
                    Path({str(sidecar_path)!r}),
                    paper_id="2307.00220",
                    embedded_chunks=[{{"chunk_id": chunk_ids[0], "kind": "stmt"}}],
                )
            """
        )
        p1 = subprocess.Popen(
            [sys.executable, "-c", writer_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        p2 = subprocess.Popen(
            [sys.executable, "-c", writer_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        rc1 = p1.wait(timeout=60)
        rc2 = p2.wait(timeout=60)
        # Both processes finished cleanly.
        stderr1 = p1.stderr.read().decode("utf-8", errors="replace") if p1.stderr else ""
        stderr2 = p2.stderr.read().decode("utf-8", errors="replace") if p2.stderr else ""
        assert rc1 == 0, f"writer 1 failed (rc={rc1}): {stderr1}"
        assert rc2 == 0, f"writer 2 failed (rc={rc2}): {stderr2}"
        # Both files exist and parse cleanly.
        assert npz_path.exists()
        assert sidecar_path.exists()
        npz = np.load(npz_path, allow_pickle=True)
        assert npz["embedding_stmt"].shape == (1, EMBEDDING_DIM)
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        assert sidecar["paper_id"] == "2307.00220"
        # No tmp leaks from either process — ``try/finally`` cleanup
        # in both writers must run even on the os.replace race.
        leftover = list(out_dir.glob("*.tmp"))
        assert leftover == []
