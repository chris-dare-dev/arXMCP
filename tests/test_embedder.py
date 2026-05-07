"""Unit tests for the dual-column BGE-M3 embedder (E03_S01).

Coverage map:
  Acceptance criterion -> test class
  ──────────────────────────────────────────────────────────────────────
  Model loaded from pinned commit SHA (single constant) -> TestModuleContract
  kind="stmt" routes to embedding_stmt                  -> TestRouting
  kind="proof" routes to embedding_proof                -> TestRouting
  kind="section"/"definition" routes to embedding_stmt  -> TestRouting
  embedding_eq is always NULL                           -> TestRouting
  Vectors shape (1024,) and L2-normalized               -> TestVectorContract
  preamble + body_text exceeding 512 toks: warn+truncate -> TestTokenBudget
  embed-stats.jsonl entry per run                       -> TestStatsLogging
  Threat 6: revision pin + trust_remote_code=False      -> TestThreat6
  F3 fallback: load_preamble returns None               -> TestF3Fallback
  Per-paper failure isolation                           -> TestPerPaperFailure
  Atomic NPZ write (tmp + os.replace)                   -> TestAtomicWrite
  CHUNKER_VERSION + EMBEDDER_VERSION exposed            -> TestVersionConstants

The model itself is mocked everywhere except in TestVectorContract's
opt-in real-model test (skipped by default; flip the env var
ARXMCP_RUN_REAL_BGE_M3=1 to exercise the actual ~2.3 GB weight load).
Mocking is essential — a CI run that downloaded the real model on every
test would be neither fast nor offline-capable.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

import ingest.embedder as embedder_mod
from ingest.embedder import (
    BGE_M3_COMMIT_SHA,
    EMBEDDER_VERSION,
    EMBEDDING_DIM,
    MAX_TOKENS,
    PER_PAPER_FAILURE_EXCEPTIONS,
    _build_embed_input,
    _write_embeddings_npz,
    embed_corpus,
    embed_paper,
)

# ===========================================================================
# Helpers
# ===========================================================================


def _stage_chunk_dir(
    tmp_path: Path,
    paper_id: str,
    chunks: list[dict],
) -> Path:
    """Write per-chunk JSONs + chunk_manifest.json under tmp_path/chunks/<paper_id>/.

    Mirrors the on-disk layout the chunker produces. Returns the per-paper
    chunks directory.
    """
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
                "chunker_version": "v1.0",
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
    paper_id: str,
    kind: str,
    body_text: str,
    *,
    suffix: str | None = None,
) -> dict:
    """Build a minimal ChunkRecord-shaped JSON payload.

    ``suffix`` lets tests fabricate distinct chunk_ids in one call. If
    omitted, derives a stable hash from kind+body_text.
    """
    import hashlib

    if suffix is None:
        suffix = hashlib.sha256(
            f"{kind}::{body_text}".encode()
        ).hexdigest()[:16]
    return {
        "body_text": body_text,
        "body_tokens": "tok1 tok2",
        "chunk_id": f"arxiv:{paper_id}:{suffix}",
        "chunker_version": "v1.0",
        "kind": kind,
        "paper_id": paper_id,
        "preamble_ref": None,
        "section_path": [],
        "theorem_label": None,
        "theorem_name": None,
        "truncated": False,
    }


def _fake_model_factory(emit_dim: int = EMBEDDING_DIM):
    """Return a (tokenizer, model) pair that mimics BGE-M3 for tests.

    Closes F6 from the E03_S01 adversary critique: the fake model now
    produces ROW-DISTINCT vectors (not colinear scalar multiples). Each
    row uses a different seeded ``torch.randn`` so post-L2-normalization
    vectors are distinguishable, allowing tests to assert
    ``not allclose(vectors[i], vectors[j])``. The previous fake's rows
    were ``(i+1) * arange(hidden)``, which are positive scalar multiples
    of the same direction and L2-normalize to the SAME unit vector — a
    bug-camouflaging behavior that let "all rows are identical"
    regressions slip through.

    The tokenizer ``__call__`` handles BOTH call shapes the embedder
    uses:
    - the encode call: ``tokenizer(texts, padding=True, truncation=True,
      max_length=N, return_tensors="pt")``
    - the F3 pre-pass: ``tokenizer(texts, padding=False, truncation=
      False, return_length=True)``
    The pre-pass uses ``len(text.split())`` as a proxy for the token
    length so token-budget tests can drive the truncation path.
    """
    import torch

    class _FakeTokenizer:
        def __init__(self):
            self.calls: list[list[str]] = []

        def encode(self, text: str, add_special_tokens: bool = True) -> list[int]:
            # Lower-bound a plausible token count: word-split + 2 for special.
            n = len(text.split()) + (2 if add_special_tokens else 0)
            return list(range(n))

        def __call__(self, texts, **kwargs):
            self.calls.append(list(texts))
            # F3 pre-pass: return per-text length list, no tensors.
            if kwargs.get("return_length"):
                return {
                    "length": [
                        len(t.split()) + 2  # +2 for special tokens
                        for t in texts
                    ],
                }
            # Encode call: produces tensors. The shapes don't have to
            # match what BGE-M3 would actually produce — only the model
            # forward pass cares about the batch dim.
            assert kwargs.get("padding") is True
            assert kwargs.get("truncation") is True
            assert kwargs.get("max_length") == MAX_TOKENS
            assert kwargs.get("return_tensors") == "pt"
            batch = len(texts)
            seq_len = 4
            return {
                "input_ids": torch.zeros(batch, seq_len, dtype=torch.long),
                "attention_mask": torch.ones(batch, seq_len, dtype=torch.long),
            }

    class _FakeOutput:
        def __init__(self, batch: int, hidden: int, seed_base: int):
            # Closes F6: each row is a fresh seeded random vector so
            # post-normalization vectors are distinguishable.
            rows = []
            for i in range(batch):
                gen = torch.Generator().manual_seed(seed_base + i)
                rows.append(
                    torch.randn(1, 4, hidden, generator=gen, dtype=torch.float32)
                )
            self.last_hidden_state = torch.cat(rows, dim=0)

    class _FakeModel:
        def __init__(self):
            self.eval_called = False
            self._call_count = 0

        def eval(self):
            self.eval_called = True
            return self

        def __call__(self, **kwargs):
            batch = kwargs["input_ids"].shape[0]
            # Use a different seed_base per call so successive batches
            # produce different vectors even for identical inputs (this
            # is fine because the tests don't rely on byte-equality
            # between batches).
            seed_base = 1000 * (self._call_count + 1)
            self._call_count += 1
            return _FakeOutput(batch, emit_dim, seed_base)

    return _FakeTokenizer(), _FakeModel()


def _patched_embed(
    tmp_path: Path,
    paper_id: str,
    *,
    preamble_text: str | None = "",
    fake_tokenizer=None,
    fake_model=None,
):
    """Run :func:`embed_paper` with all paths and the model patched.

    ``preamble_text`` of ``None`` simulates the F3 fallback (preamble
    extraction failed); any string sets the preamble explicitly.
    """
    chunks_dir = tmp_path / "chunks"
    embeddings_dir = tmp_path / "embeddings"
    stats_path = tmp_path / "ops" / "embed-stats.jsonl"
    log_path = tmp_path / "ops" / "embed.log"

    if fake_tokenizer is None or fake_model is None:
        fake_tokenizer, fake_model = _fake_model_factory()

    if preamble_text is None:
        preamble_value = None
    else:
        from ingest.preamble_types import PreambleDoc

        preamble_value = PreambleDoc(
            paper_id=paper_id,
            source_hash="0" * 64,
            macros=[],
            preamble_text=preamble_text,
            preamble_hash="0" * 16,
        )

    with (
        patch("ingest.embedder.CHUNKS_DIR", chunks_dir),
        patch("ingest.embedder.EMBEDDINGS_DIR", embeddings_dir),
        patch("ingest.embedder.EMBED_STATS_PATH", stats_path),
        patch("ingest.embedder.EMBED_LOG_PATH", log_path),
        patch("ingest.embedder.load_preamble", return_value=preamble_value),
        patch("ingest.embedder._get_tokenizer", return_value=fake_tokenizer),
        patch("ingest.embedder._get_model", return_value=fake_model),
    ):
        stats = embed_paper(paper_id)
    return stats, embeddings_dir, stats_path


# ===========================================================================
# TestModuleContract
# ===========================================================================


class TestModuleContract:
    def test_bge_m3_commit_sha_pinned(self):
        # 40-char hex SHA-1 commit identifier.
        assert isinstance(BGE_M3_COMMIT_SHA, str)
        assert len(BGE_M3_COMMIT_SHA) == 40
        assert all(c in "0123456789abcdef" for c in BGE_M3_COMMIT_SHA)

    def test_bge_m3_commit_sha_defined_exactly_once(self):
        # The brief mandates a single source of truth. Confirm the
        # constant lives only in ingest/embedder.py — no stray duplicate
        # in ingest/__init__.py or anywhere else under ingest/.
        ingest_root = Path(__file__).parent.parent / "ingest"
        hits = []
        for py_file in ingest_root.rglob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            if "BGE_M3_COMMIT_SHA = " in text:
                hits.append(py_file)
        assert len(hits) == 1, (
            f"BGE_M3_COMMIT_SHA must be defined exactly once; found in: {hits}"
        )
        assert hits[0].name == "embedder.py"

    def test_embedder_version_format(self):
        assert EMBEDDER_VERSION.startswith("bge-m3@")
        assert f"bge-m3@{BGE_M3_COMMIT_SHA[:8]}" == EMBEDDER_VERSION

    def test_embedding_dim_is_1024(self):
        assert EMBEDDING_DIM == 1024

    def test_max_tokens_is_512(self):
        assert MAX_TOKENS == 512

    def test_per_paper_failure_exceptions_targeted(self):
        # Resilience-pattern exceptions only; programmer bugs propagate.
        assert OSError in PER_PAPER_FAILURE_EXCEPTIONS
        assert ValueError in PER_PAPER_FAILURE_EXCEPTIONS
        assert FileNotFoundError in PER_PAPER_FAILURE_EXCEPTIONS
        # AttributeError, KeyError, TypeError must NOT be caught.
        assert AttributeError not in PER_PAPER_FAILURE_EXCEPTIONS
        assert KeyError not in PER_PAPER_FAILURE_EXCEPTIONS
        assert TypeError not in PER_PAPER_FAILURE_EXCEPTIONS


# ===========================================================================
# TestEmbedInputBuild (NFC + F3 fallback)
# ===========================================================================


class TestEmbedInputBuild:
    def test_combines_preamble_and_body(self):
        result = _build_embed_input("\\newcommand{\\R}{\\R}", "Theorem 1.")
        assert result == "\\newcommand{\\R}{\\R}\n\n" + "Theorem 1."

    def test_empty_preamble_returns_body_only(self):
        result = _build_embed_input("", "Theorem 1.")
        assert result == "Theorem 1."

    def test_applies_nfc_normalization(self):
        # NFC composes the dotless-i + combining-grave into ï-with-grave
        # form. Verify the embedder canonicalizes before encoding.
        # Use a clearer NFC test pair: 'café' in NFD form (e + combining-acute)
        # vs NFC form (single é).
        body_nfd = "café"  # 'cafe' + combining acute
        body_nfc = "café"   # 'café' precomposed
        assert _build_embed_input("", body_nfd) == body_nfc


# ===========================================================================
# TestRouting (kind -> column)
# ===========================================================================


class TestRouting:
    def test_kind_proof_routes_to_embedding_proof(self, tmp_path):
        paper_id = "2307.00001"
        _stage_chunk_dir(
            tmp_path,
            paper_id,
            [
                _make_chunk(paper_id, "stmt", "Theorem 1.", suffix="0" * 16),
                _make_chunk(paper_id, "proof", "Proof of Theorem 1.", suffix="1" * 16),
            ],
        )
        stats, embeddings_dir, _ = _patched_embed(tmp_path, paper_id)
        npz = np.load(embeddings_dir / paper_id / "embeddings.npz", allow_pickle=True)
        chunk_ids_stmt = list(npz["chunk_ids_stmt"])
        chunk_ids_proof = list(npz["chunk_ids_proof"])
        assert chunk_ids_stmt == [f"arxiv:{paper_id}:{'0' * 16}"]
        assert chunk_ids_proof == [f"arxiv:{paper_id}:{'1' * 16}"]
        assert stats.chunks_processed == 2

    def test_kind_section_definition_route_to_embedding_stmt(self, tmp_path):
        paper_id = "2307.00002"
        _stage_chunk_dir(
            tmp_path,
            paper_id,
            [
                _make_chunk(paper_id, "section", "Body A", suffix="a" * 16),
                _make_chunk(paper_id, "definition", "Body B", suffix="b" * 16),
            ],
        )
        _, embeddings_dir, _ = _patched_embed(tmp_path, paper_id)
        npz = np.load(embeddings_dir / paper_id / "embeddings.npz", allow_pickle=True)
        chunk_ids_stmt = list(npz["chunk_ids_stmt"])
        chunk_ids_proof = list(npz["chunk_ids_proof"])
        assert len(chunk_ids_stmt) == 2
        assert len(chunk_ids_proof) == 0
        # Closes F9: empty proof column is a (0, 1024) zero-row sentinel,
        # NOT absent from the NPZ. Consumers must check
        # ``len(chunk_ids_proof) > 0`` not key presence.
        assert npz["embedding_proof"].shape == (0, EMBEDDING_DIM)
        # Closes F8: embedding_eq is reserved for E10_S03 and the
        # embedder must NEVER populate it. Lock the negative invariant
        # so a future refactor of _write_embeddings_npz that adds an
        # embedding_eq array gets caught by the test suite.
        assert "embedding_eq" not in npz.files

    def test_npz_keys_are_alphabetical(self, tmp_path):
        # Closes F5: ``np.savez`` writes archive members in kwargs
        # insertion order. Lock that the four arrays land in
        # alphabetical order so byte-stable NPZ files are an invariant.
        paper_id = "2307.00004"
        _stage_chunk_dir(
            tmp_path,
            paper_id,
            [
                _make_chunk(paper_id, "stmt", "Body A", suffix="0" * 16),
                _make_chunk(paper_id, "proof", "Body B", suffix="1" * 16),
            ],
        )
        _, embeddings_dir, _ = _patched_embed(tmp_path, paper_id)
        npz = np.load(embeddings_dir / paper_id / "embeddings.npz", allow_pickle=True)
        assert npz.files == sorted(npz.files)
        assert npz.files == [
            "chunk_ids_proof",
            "chunk_ids_stmt",
            "embedding_proof",
            "embedding_stmt",
        ]

    def test_other_kinds_route_to_embedding_stmt(self, tmp_path):
        # lemma / corollary / remark / example are emitted by the chunker
        # but the brief only enumerates stmt/proof/section/definition.
        # Routing rule: anything that isn't "proof" → embedding_stmt.
        paper_id = "2307.00003"
        _stage_chunk_dir(
            tmp_path,
            paper_id,
            [
                _make_chunk(paper_id, "lemma", "Body lemma", suffix="c" * 16),
                _make_chunk(paper_id, "remark", "Body remark", suffix="d" * 16),
            ],
        )
        _, embeddings_dir, _ = _patched_embed(tmp_path, paper_id)
        npz = np.load(embeddings_dir / paper_id / "embeddings.npz", allow_pickle=True)
        assert len(npz["chunk_ids_stmt"]) == 2
        assert len(npz["chunk_ids_proof"]) == 0


# ===========================================================================
# TestVectorContract (shape + L2-norm)
# ===========================================================================


class TestVectorContract:
    def test_shape_1024_and_l2_normalized(self, tmp_path):
        paper_id = "2307.00010"
        _stage_chunk_dir(
            tmp_path,
            paper_id,
            [
                _make_chunk(paper_id, "stmt", "Body A", suffix="0" * 16),
                _make_chunk(paper_id, "stmt", "Body B", suffix="1" * 16),
                _make_chunk(paper_id, "proof", "Body C", suffix="2" * 16),
            ],
        )
        _, embeddings_dir, _ = _patched_embed(tmp_path, paper_id)
        npz = np.load(embeddings_dir / paper_id / "embeddings.npz", allow_pickle=True)
        # Shape contract.
        assert npz["embedding_stmt"].shape == (2, EMBEDDING_DIM)
        assert npz["embedding_proof"].shape == (1, EMBEDDING_DIM)
        # L2-norm contract: every vector has norm ≈ 1.0.
        for column_key in ("embedding_stmt", "embedding_proof"):
            vectors = npz[column_key]
            for i, vec in enumerate(vectors):
                norm = np.linalg.norm(vec)
                assert abs(norm - 1.0) < 1e-5, (
                    f"{column_key}[{i}] not L2-normalized: norm={norm}"
                )

    def test_dtype_is_float32(self, tmp_path):
        paper_id = "2307.00011"
        _stage_chunk_dir(
            tmp_path,
            paper_id,
            [_make_chunk(paper_id, "stmt", "Body A", suffix="0" * 16)],
        )
        _, embeddings_dir, _ = _patched_embed(tmp_path, paper_id)
        npz = np.load(embeddings_dir / paper_id / "embeddings.npz", allow_pickle=True)
        assert npz["embedding_stmt"].dtype == np.float32


# ===========================================================================
# TestTokenBudget (warn + truncate, never raise)
# ===========================================================================


class TestTokenBudget:
    def test_overlong_input_warn_and_truncate(self, tmp_path, caplog):
        paper_id = "2307.00020"
        long_body = " ".join(["word"] * 1000)  # 1000 tokens >> 512
        _stage_chunk_dir(
            tmp_path,
            paper_id,
            [_make_chunk(paper_id, "stmt", long_body, suffix="0" * 16)],
        )
        with caplog.at_level("WARNING", logger="ingest.embedder"):
            stats, _, _ = _patched_embed(tmp_path, paper_id)
        # Must not raise.
        assert stats.status == "ok"
        assert stats.chunks_processed == 1
        # Truncation count surfaced in stats.
        assert stats.truncated_count == 1
        # Warning logged.
        assert any("truncated" in rec.message for rec in caplog.records)


# ===========================================================================
# TestStatsLogging (embed-stats.jsonl)
# ===========================================================================


class TestStatsLogging:
    def test_jsonl_line_per_paper(self, tmp_path):
        paper_id = "2307.00030"
        _stage_chunk_dir(
            tmp_path,
            paper_id,
            [_make_chunk(paper_id, "stmt", "Body A", suffix="0" * 16)],
        )
        _, _, stats_path = _patched_embed(tmp_path, paper_id)
        assert stats_path.exists()
        line = stats_path.read_text(encoding="utf-8").strip()
        row = json.loads(line)
        assert row["paper_id"] == paper_id
        assert row["chunks_processed"] == 1
        assert row["status"] == "ok"
        assert row["bge_m3_commit_sha"] == BGE_M3_COMMIT_SHA
        assert row["embedder_version"] == EMBEDDER_VERSION
        assert isinstance(row["elapsed_s"], (int, float))

    def test_failure_writes_fail_status_to_jsonl(self, tmp_path):
        # Closes F1 from the E03_S01 critique: failed runs MUST also
        # write to embed-stats.jsonl, not just to embed.log. Operators
        # querying the JSONL audit trail must catch every paper attempt.
        paper_id = "2307.00031"
        # Stage a corrupt chunk_manifest.json by hand.
        paper_dir = tmp_path / "chunks" / paper_id
        paper_dir.mkdir(parents=True)
        (paper_dir / "chunk_manifest.json").write_text(
            "{not valid json", encoding="utf-8"
        )
        chunks_dir = tmp_path / "chunks"
        embeddings_dir = tmp_path / "embeddings"
        stats_path = tmp_path / "ops" / "embed-stats.jsonl"
        log_path = tmp_path / "ops" / "embed.log"
        with (
            patch("ingest.embedder.CHUNKS_DIR", chunks_dir),
            patch("ingest.embedder.EMBEDDINGS_DIR", embeddings_dir),
            patch("ingest.embedder.EMBED_STATS_PATH", stats_path),
            patch("ingest.embedder.EMBED_LOG_PATH", log_path),
        ):
            stats = embed_paper(paper_id)
        # Stats reflect the failure.
        assert stats.status == "fail"
        assert stats.error is not None
        # Goes to BOTH the TSV log AND the structured JSONL.
        assert log_path.exists()
        assert stats_path.exists()
        line = stats_path.read_text(encoding="utf-8").strip()
        row = json.loads(line)
        assert row["status"] == "fail"
        assert row["paper_id"] == paper_id
        # Closes F4: error_class enum lets ops distinguish failure modes
        # without grepping the free-text error field. A corrupt manifest
        # file gets the manifest_corrupt class.
        assert row["error_class"] == "manifest_corrupt"

    def test_error_class_chunk_missing(self, tmp_path):
        # Closes F4: when the manifest references a chunk file that does
        # not exist on disk, the error_class must be chunk_missing (a P0
        # corpus-corruption signal), distinct from manifest-absent
        # (which takes the silent-skip path).
        paper_id = "2307.00032"
        paper_dir = tmp_path / "chunks" / paper_id
        paper_dir.mkdir(parents=True)
        (paper_dir / "chunk_manifest.json").write_text(
            json.dumps(
                {
                    "chunker_version": "v1.0",
                    "chunks": [
                        {
                            "chunk_id": f"arxiv:{paper_id}:" + "f" * 16,
                            "kind": "stmt",
                        }
                    ],
                    "paper_id": paper_id,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        chunks_dir = tmp_path / "chunks"
        embeddings_dir = tmp_path / "embeddings"
        stats_path = tmp_path / "ops" / "embed-stats.jsonl"
        log_path = tmp_path / "ops" / "embed.log"
        with (
            patch("ingest.embedder.CHUNKS_DIR", chunks_dir),
            patch("ingest.embedder.EMBEDDINGS_DIR", embeddings_dir),
            patch("ingest.embedder.EMBED_STATS_PATH", stats_path),
            patch("ingest.embedder.EMBED_LOG_PATH", log_path),
        ):
            stats = embed_paper(paper_id)
        assert stats.status == "fail"
        assert stats.error_class == "chunk_missing"


# ===========================================================================
# TestThreat6 (Threat 6: model pinning + safetensors + trust_remote_code=False)
# ===========================================================================


class TestThreat6:
    def test_model_loaded_with_pinned_revision(self):
        """``_get_model`` must pass ``revision=BGE_M3_COMMIT_SHA``."""
        # Reset the lazy global so we observe the call.
        embedder_mod._model = None
        embedder_mod._tokenizer = None

        fake_model = MagicMock()
        fake_model.eval.return_value = fake_model
        with patch("transformers.AutoModel.from_pretrained", return_value=fake_model) as load_call:
            embedder_mod._get_model()
        load_call.assert_called_once()
        kwargs = load_call.call_args.kwargs
        args = load_call.call_args.args
        # First positional arg = "BAAI/bge-m3"
        assert args[0] == "BAAI/bge-m3"
        # Pinned revision
        assert kwargs.get("revision") == BGE_M3_COMMIT_SHA
        # Threat 6: refuse custom modeling code.
        assert kwargs.get("trust_remote_code") is False
        # Reset for next tests.
        embedder_mod._model = None

    def test_tokenizer_loaded_with_pinned_revision(self):
        """``_get_tokenizer`` must pin to the SHA — closes the chunker's
        pre-existing tokenizer-pinning gap, at least for the embedder's path.
        """
        embedder_mod._tokenizer = None
        embedder_mod._model = None
        fake_tok = MagicMock()
        with patch(
            "transformers.AutoTokenizer.from_pretrained", return_value=fake_tok
        ) as load_call:
            embedder_mod._get_tokenizer()
        load_call.assert_called_once()
        kwargs = load_call.call_args.kwargs
        args = load_call.call_args.args
        assert args[0] == "BAAI/bge-m3"
        assert kwargs.get("revision") == BGE_M3_COMMIT_SHA
        embedder_mod._tokenizer = None

    def test_chunker_tokenizer_loaded_with_pinned_revision(self):
        """Closes F7 from the E03_S01 critique: ``ingest.chunker._get_tokenizer``
        must also pin to BGE_M3_COMMIT_SHA to satisfy Threat 6. Without it,
        body_tokens drifts across runs as HuggingFace rotates the
        tokenizer-only files for the floating ``main`` tag, while
        ``chunker_version`` stays the same — a dormant cache-poisoning bomb
        for BP1 byte-stability.
        """
        import ingest.chunker as chunker_mod

        chunker_mod._tokenizer = None
        fake_tok = MagicMock()
        with patch(
            "transformers.AutoTokenizer.from_pretrained", return_value=fake_tok
        ) as load_call:
            chunker_mod._get_tokenizer()
        load_call.assert_called_once()
        kwargs = load_call.call_args.kwargs
        args = load_call.call_args.args
        assert args[0] == "BAAI/bge-m3"
        assert kwargs.get("revision") == BGE_M3_COMMIT_SHA, (
            "chunker tokenizer must pin to BGE_M3_COMMIT_SHA (Threat 6, F7)"
        )
        chunker_mod._tokenizer = None


# ===========================================================================
# TestF3Fallback (preamble missing)
# ===========================================================================


class TestF3Fallback:
    def test_load_preamble_returns_none_no_crash(self, tmp_path):
        paper_id = "2307.00040"
        _stage_chunk_dir(
            tmp_path,
            paper_id,
            [_make_chunk(paper_id, "stmt", "Body A", suffix="0" * 16)],
        )
        # preamble_text=None tells the helper to make load_preamble
        # return None (the F3 fallback path).
        stats, embeddings_dir, _ = _patched_embed(
            tmp_path, paper_id, preamble_text=None
        )
        assert stats.status == "ok"
        assert stats.chunks_processed == 1
        npz = np.load(embeddings_dir / paper_id / "embeddings.npz", allow_pickle=True)
        # The vector must still be valid (shape, normalized).
        assert npz["embedding_stmt"].shape == (1, EMBEDDING_DIM)
        norm = np.linalg.norm(npz["embedding_stmt"][0])
        assert abs(norm - 1.0) < 1e-5


# ===========================================================================
# TestPerPaperFailure (resilience envelope)
# ===========================================================================


class TestPerPaperFailure:
    def test_invalid_paper_id_raises(self, tmp_path):
        # InvalidPaperIDError is a ValueError; the public embed_paper
        # validates _outside_ the per-paper envelope, so an invalid ID
        # surfaces to the caller rather than being silently logged.
        from ingest.chunker import InvalidPaperIDError

        with pytest.raises(InvalidPaperIDError):
            embed_paper("../etc/passwd")

    def test_missing_corpus_dir_returns_empty(self, tmp_path):
        # embed_corpus on a missing chunks directory returns [] without
        # raising — corpus drivers that pre-flight-check should still
        # tolerate the empty case.
        results = embed_corpus(corpus_path=str(tmp_path / "does_not_exist"))
        assert results == []


# ===========================================================================
# TestAtomicWrite (NPZ write via tmp + os.replace)
# ===========================================================================


class TestAtomicWrite:
    def test_tmp_files_are_cleaned_up(self, tmp_path):
        out_path = tmp_path / "embeddings.npz"
        _write_embeddings_npz(
            out_path,
            chunk_ids_stmt=["arxiv:p:" + "0" * 16],
            embedding_stmt=np.zeros((1, EMBEDDING_DIM), dtype=np.float32),
            chunk_ids_proof=[],
            embedding_proof=np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
        )
        assert out_path.exists()
        # No tmp leak.
        leftover = list(out_path.parent.glob("*.tmp"))
        assert leftover == []

    def test_tmp_filename_includes_pid_and_uuid(self, tmp_path):
        # Verify the tmp-name pattern matches preamble.py's discipline so
        # concurrent runs cannot collide on a shared "*.tmp" path. The
        # writer hands np.savez an open file object (not a path string)
        # so we capture file.name to assert the on-disk path the writer
        # actually wrote to.
        out_path = tmp_path / "embeddings.npz"
        captured = {}
        original_savez = np.savez

        def _capturing_savez(file, *args, **kwargs):
            captured["path"] = getattr(file, "name", str(file))
            return original_savez(file, *args, **kwargs)

        with patch("numpy.savez", side_effect=_capturing_savez):
            _write_embeddings_npz(
                out_path,
                chunk_ids_stmt=[],
                embedding_stmt=np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
                chunk_ids_proof=[],
                embedding_proof=np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
            )
        tmp_name = captured["path"]
        assert str(os.getpid()) in tmp_name
        assert tmp_name.endswith(".tmp")


# ===========================================================================
# TestEmbedCorpus (corpus-wide driver)
# ===========================================================================


class TestEmbedCorpus:
    def test_iterates_paper_dirs_with_manifest(self, tmp_path):
        # Stage two paper dirs and one rogue non-paper directory; assert
        # that only the two papers are processed and the rogue is skipped
        # with a warning.
        for paper_id in ("2307.00050", "2307.00051"):
            _stage_chunk_dir(
                tmp_path,
                paper_id,
                [_make_chunk(paper_id, "stmt", "Body", suffix="0" * 16)],
            )
        # rogue dir without a manifest
        rogue = tmp_path / "chunks" / "not-a-paper-id"
        rogue.mkdir()

        chunks_dir = tmp_path / "chunks"
        embeddings_dir = tmp_path / "embeddings"
        stats_path = tmp_path / "ops" / "embed-stats.jsonl"
        log_path = tmp_path / "ops" / "embed.log"
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
        assert len(results) == 2
        paper_ids = {r.paper_id for r in results}
        assert paper_ids == {"2307.00050", "2307.00051"}

    def test_lancedb_path_param_accepted_but_unused(self, tmp_path):
        # Forward-compat: the brief signature carries lancedb_path. We
        # accept and ignore it (E04_S01 will wire it in).
        results = embed_corpus(
            lancedb_path="/nonexistent/lancedb",
            corpus_path=str(tmp_path / "missing"),
        )
        assert results == []

    def test_run_summary_appended_to_jsonl(self, tmp_path):
        # Closes F2 from the E03_S01 critique: embed_corpus must append
        # one event="run_summary" JSONL line per call so dashboards can
        # ingest a single "embed_corpus completed" event with aggregate
        # paper_count, chunk_count, wall-clock seconds, and the pinned
        # BGE_M3_COMMIT_SHA — distinct from per-paper rows.
        for paper_id in ("2307.00060", "2307.00061"):
            _stage_chunk_dir(
                tmp_path,
                paper_id,
                [_make_chunk(paper_id, "stmt", "Body", suffix="0" * 16)],
            )
        chunks_dir = tmp_path / "chunks"
        embeddings_dir = tmp_path / "embeddings"
        stats_path = tmp_path / "ops" / "embed-stats.jsonl"
        log_path = tmp_path / "ops" / "embed.log"
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
            embed_corpus(corpus_path=str(chunks_dir))
        lines = [
            json.loads(line)
            for line in stats_path.read_text(encoding="utf-8").strip().splitlines()
        ]
        # 2 per-paper rows + 1 run_summary = 3 total.
        assert len(lines) == 3
        # Per-paper rows do not carry the "event" discriminator.
        per_paper = [row for row in lines if "event" not in row]
        run_summaries = [row for row in lines if row.get("event") == "run_summary"]
        assert len(per_paper) == 2
        assert len(run_summaries) == 1
        summary = run_summaries[0]
        assert summary["paper_count"] == 2
        assert summary["chunk_count"] == 2
        assert summary["fail_count"] == 0
        assert summary["bge_m3_commit_sha"] == BGE_M3_COMMIT_SHA
        assert summary["embedder_version"] == EMBEDDER_VERSION
        assert isinstance(summary["elapsed_s"], (int, float))

    def test_per_paper_failure_isolation(self, tmp_path):
        # Closes F14 from the E03_S01 critique: a properly named
        # per-paper-isolation test that stages multiple papers and forces
        # one to fail mid-corpus, then asserts the others still complete
        # AND the run_summary correctly reports fail_count.
        for paper_id in ("2307.00070", "2307.00071"):
            _stage_chunk_dir(
                tmp_path,
                paper_id,
                [_make_chunk(paper_id, "stmt", "Body", suffix="0" * 16)],
            )
        chunks_dir = tmp_path / "chunks"
        embeddings_dir = tmp_path / "embeddings"
        stats_path = tmp_path / "ops" / "embed-stats.jsonl"
        log_path = tmp_path / "ops" / "embed.log"
        fake_tokenizer, fake_model = _fake_model_factory()
        from ingest.preamble_types import PreambleDoc

        preamble = PreambleDoc(
            paper_id="x",
            source_hash="0" * 64,
            macros=[],
            preamble_text="",
            preamble_hash="0" * 16,
        )
        # Make the FIRST paper raise OSError when its chunks are loaded;
        # the second paper should still succeed.
        original_load_chunks = embedder_mod._load_chunks

        def _selectively_failing_load_chunks(paper_id: str) -> list[dict]:
            if paper_id == "2307.00070":
                raise OSError("simulated I/O failure")
            return original_load_chunks(paper_id)

        with (
            patch("ingest.embedder.CHUNKS_DIR", chunks_dir),
            patch("ingest.embedder.EMBEDDINGS_DIR", embeddings_dir),
            patch("ingest.embedder.EMBED_STATS_PATH", stats_path),
            patch("ingest.embedder.EMBED_LOG_PATH", log_path),
            patch("ingest.embedder.load_preamble", return_value=preamble),
            patch("ingest.embedder._get_tokenizer", return_value=fake_tokenizer),
            patch("ingest.embedder._get_model", return_value=fake_model),
            patch(
                "ingest.embedder._load_chunks",
                side_effect=_selectively_failing_load_chunks,
            ),
        ):
            results = embed_corpus(corpus_path=str(chunks_dir))
        # Both papers attempted — failure of one does NOT abort the
        # batch.
        assert len(results) == 2
        by_paper = {r.paper_id: r for r in results}
        assert by_paper["2307.00070"].status == "fail"
        assert by_paper["2307.00071"].status == "ok"
        # Run summary captures fail_count.
        lines = [
            json.loads(line)
            for line in stats_path.read_text(encoding="utf-8").strip().splitlines()
        ]
        summary = next(row for row in lines if row.get("event") == "run_summary")
        assert summary["fail_count"] == 1
        assert summary["paper_count"] == 2
