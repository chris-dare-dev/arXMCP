"""Compare representative formal-result retrieval before notebook cutover."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from arxmcp.ingest.embedder import _encode_batch

QUERIES = (
    (
        "big quantum cohomology of IG(2,6) is generically semisimple theorem",
        "1405.3857",
        "embedding_stmt",
    ),
    (
        "locally finite destabilizing walls for weak stability conditions",
        "2411.18554",
        "embedding_stmt",
    ),
    (
        "tilt semistable object of positive rank has stable factor in Jordan Holder filtration",
        "1607.08199",
        "embedding_stmt",
    ),
    (
        "prime Fano threefold genus 12 smooth conic birational diagram",
        "1711.08504",
        "embedding_stmt",
    ),
    (
        "quasi representable DG functor iff graded homotopy functor representable",
        "math/0210114",
        "embedding_stmt",
    ),
    (
        "rigid bundle on a del Pezzo surface splits into exceptional bundles",
        "textbook:ko95",
        "embedding_stmt",
    ),
    (
        "complete semiorthogonal set of admissible subcategories "
        "generates derived category of a blowup",
        "textbook:orl93",
        "embedding_stmt",
    ),
    (
        "Cube Completion Lemma convolution of twisted cubes proves "
        "braid relation for spherical DG functors",
        "1309.5035",
        "embedding_proof",
    ),
    (
        "Hilbert scheme of twisted cubic curves quasi universal family Kuznetsov component",
        "1802.01134",
        "embedding_proof",
    ),
)

FORMAL_FILTER = (
    "kind IN ('stmt','theorem','lemma','proposition','corollary',"
    "'definition','remark','example','claim','conjecture')"
)


def compare(active: Path, staged: Path, limit: int = 20) -> dict:
    import lancedb

    active_table = lancedb.connect(str(active)).open_table("chunks")
    staged_table = lancedb.connect(str(staged)).open_table("chunks")
    vectors, _ = _encode_batch([query for query, _, _ in QUERIES])
    comparisons = []
    for (query, target, column), vector in zip(QUERIES, vectors, strict=True):
        entry = {"query": query, "target_paper": target, "column": column}
        for label, table in (("active", active_table), ("staged", staged_table)):
            search = table.search(vector, vector_column_name=column)
            if column == "embedding_stmt":
                search = search.where(FORMAL_FILTER)
            hits = (
                search.limit(limit)
                .select(["paper_id", "chunk_id", "kind", "body_text"])
                .to_arrow()
                .to_pylist()
            )
            entry[label] = {
                "target_rank": next(
                    (i for i, hit in enumerate(hits, 1) if hit["paper_id"] == target),
                    None,
                ),
                "target_hit": next(
                    (
                        {
                            "chunk_id": hit["chunk_id"],
                            "kind": hit["kind"],
                            "text": hit["body_text"][:260],
                        }
                        for hit in hits
                        if hit["paper_id"] == target
                    ),
                    None,
                ),
                "top_five": [
                    {
                        "paper_id": hit["paper_id"],
                        "kind": hit["kind"],
                        "text": hit["body_text"][:180],
                    }
                    for hit in hits[:5]
                ],
            }
        comparisons.append(entry)
    return {
        "queries": comparisons,
        "staged_target_hits": sum(x["staged"]["target_rank"] is not None for x in comparisons),
        "query_count": len(comparisons),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("active", type=Path)
    parser.add_argument("staged", type=Path)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    result = compare(args.active, args.staged, args.limit)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["staged_target_hits"] == result["query_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
