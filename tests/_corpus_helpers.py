"""Shared test helpers for corpus-integrity tests.

Promoted out of `tests/test_corpus_count_reconciliation.py` per
corpus-integrity-completion-m3 rect F3: when m3 added a sibling test
file (`tests/test_server_startup_integration.py`) that imported
`_seed_corpus` and `_patch_model` from the reconciliation tests, the
cross-test import coupled to leading-underscore "module-private"
helpers in a sibling test file without any contract pin. A future
rename or signature change in the reconciliation test file would
silently break the integration test at collection time.

This module is the shared contract. Both consumer test files import
from here. The leading-underscore prefix was dropped on promotion;
signature changes here REQUIRE updating both callers in lockstep.

Consumers:
- `tests/test_corpus_count_reconciliation.py` (the original site)
- `tests/test_server_startup_integration.py` (the corpus-integrity-completion-m3 site)

Anything added here should have a docstring explaining its
load-bearing contract — these helpers are shared infrastructure, not
test-local conveniences.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ingest.chunker_types import CHUNKER_VERSION, ChunkRecord
from ingest.embedder import EMBEDDER_VERSION, EMBEDDING_DIM
from ingest.schema import EmbedRecord
from ingest.store import write_chunks


def seed_corpus(lancedb_path: Path, *, n: int = 2) -> int:
    """Ingest a tiny n-chunk / n-paper corpus via a SINGLE
    ``write_chunks`` call; return its corpus_version.

    The marker's ``chunk_count == n`` after this (m1 made the marker
    table-derived). All n chunks ship in ONE ``write_chunks`` call —
    use ``seed_corpus_multi_paper`` for the multi-call cumulative
    shape (which is what the pre-m1 ``chunk_count = len(chunks)`` bug
    actually broke).
    """
    chunks = [
        ChunkRecord(
            chunk_id=f"arxiv:2307.0000{i}:{'0' * 16}",
            paper_id=f"2307.0000{i}",
            kind="stmt",
            section_path=[],
            theorem_name=None,
            theorem_label=None,
            body_text=f"chunk body {i}",
            body_tokens=f"chunk body {i}",
            preamble_ref=None,
            chunker_version=CHUNKER_VERSION,
        )
        for i in range(1, n + 1)
    ]
    rng = np.random.default_rng(42)
    rows = []
    for _ in chunks:
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        v /= np.linalg.norm(v)
        rows.append(v)
    embeddings = EmbedRecord(
        chunk_ids_stmt=[c.chunk_id for c in chunks],
        embedding_stmt=np.stack(rows, axis=0),
        chunk_ids_proof=[],
        embedding_proof=np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
        embedder_version=EMBEDDER_VERSION,
    )
    return write_chunks(chunks, embeddings, lancedb_path=lancedb_path)


def seed_corpus_multi_paper(
    lancedb_path: Path,
    *,
    n_papers: int = 3,
    chunks_per_paper: int = 10,
) -> int:
    """Ingest a multi-paper corpus via ``n_papers`` SEPARATE
    ``write_chunks`` calls; return the final corpus_version.

    THIS is the load-bearing fixture for the pre-m1 bug class. The
    pre-m1 bug shape wrote ``chunk_count = len(chunks)`` where
    ``chunks`` was the LAST per-paper batch — so a multi-paper ingest
    where each call processes ``chunks_per_paper`` chunks would write
    a marker reporting ``chunk_count = chunks_per_paper`` even though
    the cumulative table contains ``n_papers * chunks_per_paper`` rows.

    Default 3 × 10 = 30 chunks total but the LAST call only writes 10.
    Under the bug shape: marker.chunk_count == 10; actual == 30; the
    reconciliation detects a 20-row gap (200% divergence vs the 5%
    tolerance floor) and degrades.

    Each call produces an `EmbedRecord` whose
    ``chunk_ids_stmt`` is JUST that paper's chunks — mirrors the
    production bulk-ingest per-paper cadence (one ``write_chunks``
    per paper).

    Returns the corpus_version from the FINAL ``write_chunks`` call —
    LanceDB MVCC means each call advances the version and the final
    one is the canonical one ``corpus-version.json`` reflects.
    """
    final_version = 0
    rng = np.random.default_rng(42)
    for paper_idx in range(1, n_papers + 1):
        chunks = [
            ChunkRecord(
                chunk_id=(
                    # Distinct paper-id per call; distinct chunk-id
                    # per chunk within a paper (the canonical pattern
                    # production ingest produces).
                    f"arxiv:2307.{paper_idx:05d}:{chunk_idx:016d}"
                ),
                paper_id=f"2307.{paper_idx:05d}",
                kind="stmt",
                section_path=[],
                theorem_name=None,
                theorem_label=None,
                body_text=f"paper {paper_idx} chunk {chunk_idx}",
                body_tokens=f"paper {paper_idx} chunk {chunk_idx}",
                preamble_ref=None,
                chunker_version=CHUNKER_VERSION,
            )
            for chunk_idx in range(1, chunks_per_paper + 1)
        ]
        rows = []
        for _ in chunks:
            v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
            v /= np.linalg.norm(v)
            rows.append(v)
        embeddings = EmbedRecord(
            chunk_ids_stmt=[c.chunk_id for c in chunks],
            embedding_stmt=np.stack(rows, axis=0),
            chunk_ids_proof=[],
            embedding_proof=np.zeros(
                (0, EMBEDDING_DIM), dtype=np.float32
            ),
            embedder_version=EMBEDDER_VERSION,
        )
        final_version = write_chunks(
            chunks, embeddings, lancedb_path=lancedb_path
        )
    return final_version


def patch_bge_m3_model(monkeypatch) -> None:
    """Mock the BGE-M3 load in BOTH the query_encoder module and the
    resources module.

    Load-bearing per the notebook-retrieval-m2 lesson: ``resources.py``
    binds ``_get_model`` and ``_get_tokenizer`` by name via
    ``from server.query_encoder import _get_model``, so patching only
    ``query_encoder`` is INSUFFICIENT for any test that exercises
    ``Resources.startup``. The patch must target both modules.
    """
    import server.query_encoder as qe_mod  # noqa: PLC0415
    import server.resources as res_mod  # noqa: PLC0415

    fake_model = object()
    fake_tokenizer = object()
    for mod in (qe_mod, res_mod):
        monkeypatch.setattr(mod, "_get_model", lambda: fake_model)
        monkeypatch.setattr(mod, "_get_tokenizer", lambda: fake_tokenizer)
