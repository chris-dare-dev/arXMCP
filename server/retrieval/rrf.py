"""Reciprocal Rank Fusion utility (E07_S02).

Pure-Python implementation of RRF per Cormack, Clarke & Büttcher
(SIGIR 2009 — "Reciprocal Rank Fusion outperforms Condorcet and
individual Rank Learning Methods"):

    score(d) = sum over i of 1 / (k + rank_i(d))

where ``rank_i(d)`` is the 1-based position of document ``d`` in
ranked list ``L_i``, or implicitly infinity if absent (which makes
``1/(k + inf) == 0`` — that document contributes nothing from that
list). The constant ``k = 60`` is the empirical default from the
original paper and is pinned by ``.claude/notes/05-storage-and-
indexing.md:328`` ("Reciprocal Rank Fusion (k=60)"). Bumping this
constant is a deliberate retrieval-quality change, not a casual edit.

**Input shape: chunk_ids only.** The function takes
``Sequence[Sequence[str]]`` — each inner sequence is a ranked list
of chunk_ids in descending-relevance order. Source scores from BM25
or ANN are intentionally NOT consumed — RRF is rank-based by design,
which is why it composes cleanly across heterogeneous scoring
families (BM25 is an unbounded sum-of-logs, cosine is a bounded
[0,1] similarity). The caller adapts:

    bm25_ids = [cid for cid, _score in bm25_candidates]
    stmt_ids = [cid for cid, _score in ann_stmt_results]
    proof_ids = [cid for cid, _score in ann_proof_results]
    fused = reciprocal_rank_fusion([bm25_ids, stmt_ids, proof_ids])

**Output shape and ordering.** Returns ``list[tuple[str, float]]``
sorted by ``(fused_score desc, chunk_id asc)`` — the project-wide
determinism convention from ``06-mcp-server-design.md`` (mirrors the
existing `search.py:128` sort key). Stable across runs given
identical input lists; cross-agent prompt-cache hits remain viable.

**Empty-input semantics.** An empty outer ``lists`` argument returns
``[]``. Empty inner lists are tolerated and contribute nothing to
any document's fused score — this is the load-bearing edge case for
the brief AC #1 (``ANNPhase.query("...", bm25_candidates=[])`` must
still return results when the BM25 list is empty but the ANN lists
are not).
"""

from __future__ import annotations

from collections.abc import Sequence

#: The canonical RRF tuning constant from the original Cormack paper.
#: Pinned by ``.claude/notes/05-storage-and-indexing.md:328``. A bump
#: here is a deliberate retrieval-quality decision (changing it
#: re-balances the relative influence of high vs low ranks across the
#: fused lists) — coordinate with E05's eval harness before touching.
RRF_K: int = 60


def reciprocal_rank_fusion(
    lists: Sequence[Sequence[str]],
    k: int = RRF_K,
) -> list[tuple[str, float]]:
    """Fuse multiple ranked lists of chunk_ids via RRF.

    Parameters
    ----------
    lists:
        Sequence of ranked lists. Each inner sequence is a list of
        chunk_ids in descending-relevance order; rank-1 is index 0.
        Empty inner lists are tolerated. An empty outer ``lists``
        returns ``[]``.
    k:
        The RRF tuning constant. Defaults to :data:`RRF_K` (60).
        ``k`` MUST be > 0; a non-positive ``k`` would either divide
        by zero (k=0 with a rank-0 document, though we use 1-based
        ranks so this is unreachable in practice) or invert the
        sign meaning of the score. Validated.

    Returns
    -------
    list[tuple[str, float]]
        ``(chunk_id, fused_score)`` tuples sorted by
        ``(score desc, chunk_id asc)``. Length equals the size of
        the union of unique chunk_ids across all input lists.

    Raises
    ------
    ValueError
        If ``k <= 0``.
    """
    if k <= 0:
        # k=0 + rank-1 produces score=1 (1/(0+1)) — fine — but k=0 +
        # rank-0 (which doesn't happen with 1-based ranks) would divide
        # by zero. Negative k inverts the rank-relevance relationship.
        # Either case is a programming error, not a recoverable edge.
        raise ValueError(
            f"RRF k must be a positive integer; got {k}. The canonical "
            f"value is RRF_K=60 per Cormack 2009."
        )

    if not lists:
        return []

    # Accumulate fused scores. Use a plain dict — we'll sort once at
    # the end. Iterating in stable insertion order doesn't affect the
    # final result because the post-fusion sort is the canonical
    # determinism boundary.
    fused: dict[str, float] = {}
    for ranked_list in lists:
        # 1-based rank: enumerate(start=1).
        for rank, chunk_id in enumerate(ranked_list, start=1):
            # 1 / (k + rank). Rank-1 contributes the most weight;
            # higher ranks contribute exponentially less.
            contribution = 1.0 / (k + rank)
            fused[chunk_id] = fused.get(chunk_id, 0.0) + contribution

    # Project-wide determinism: sort (score desc, chunk_id asc). Same
    # key shape as ``server/handlers/search.py:128``.
    return sorted(fused.items(), key=lambda x: (-x[1], x[0]))


__all__ = ["RRF_K", "reciprocal_rank_fusion"]
