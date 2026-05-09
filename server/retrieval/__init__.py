"""Server-side retrieval phases (E07).

Phase 1: :class:`server.retrieval.bm25.BM25Phase` — BM25 over the
``body_tokens`` column. Cheap and broad; returns top-200 candidates.
Lands in E07_S01.

Phase 2: dual-ANN with Reciprocal Rank Fusion. Lands in E07_S02.

Phase 3: BGE-reranker with env-flag gate. Lands in E07_S03.

End-to-end eval: E07_S04 promotes the Tier-1 → Tier-2 nDCG@5 gate
to ≥ 0.80 with the full hybrid + reranker pipeline active.
"""

from __future__ import annotations

from server.retrieval.ann import ANNPhase
from server.retrieval.bm25 import (
    BM25IndexUnavailableError,
    BM25Phase,
)
from server.retrieval.rrf import RRF_K, reciprocal_rank_fusion

__all__ = [
    "RRF_K",
    "ANNPhase",
    "BM25IndexUnavailableError",
    "BM25Phase",
    "reciprocal_rank_fusion",
]
