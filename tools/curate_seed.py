#!/usr/bin/env python3
"""Pull math.AG candidates from the arXiv API for human review.

E01_S03 prefilter step. Hits `export.arxiv.org/api/query` (metadata only,
no tarball fetch yet) and prints a TSV the user can scan to pick 50 clean
papers for `tools/seed-papers.txt`.

Heuristics this can apply (from metadata only):
- post-2015 submission
- math.AG as the primary category
- single primary subject (no cross-listing onto hep-th / cs.LG)
- abstract length not pathologically short (<200 chars suggests note/comment)

Heuristics it CANNOT apply (those need the tarball, deferred to fetch_seed):
- single .tex file vs multi-file project
- exotic .sty chain
- documentclass detection (amsart vs JHEP vs custom)

Usage:
    export ARXMCP_CONTACT_EMAIL=you@example.com
    python tools/curate_seed.py --max-results 200 > /tmp/math-ag-candidates.tsv

Then eyeball the TSV, pick 50 IDs that look like single-author / small
collaboration / amsart-style submissions, and append them to
tools/seed-papers.txt.

notebook-paper-discovery-m2: the arXiv Atom API surface (``Candidate``,
``build_query_url``, ``parse_atom_feed``, ``fetch_candidates``) moved into the
shared ``tools/_arxiv_api.py`` library so the m3 notebook-discovery driver can
reuse it. They are re-exported here so existing imports
(``from tools.curate_seed import Candidate, build_query_url, …``) keep working.
Only the CLI-specific ``filter_candidates`` heuristic and ``main()`` live here.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from tools._arxiv_api import (
    ARXIV_API_URL,
    ATOM_NS,
    Candidate,
    build_query_url,
    fetch_candidates,
    parse_atom_feed,
)
from tools.arxiv_fetch import POLITENESS_SLEEP_SECONDS

# Re-exported for backward-compatible imports (tests/test_fetch_seed.py and any
# other caller importing these names from tools.curate_seed). The canonical
# definitions live in tools/_arxiv_api.py.
__all__ = [
    "ARXIV_API_URL",
    "ATOM_NS",
    "Candidate",
    "build_query_url",
    "fetch_candidates",
    "filter_candidates",
    "parse_atom_feed",
]


def filter_candidates(
    candidates: list[Candidate],
    primary_category: str,
    min_year: int,
    min_abstract_chars: int,
) -> list[Candidate]:
    return [
        c
        for c in candidates
        if c.primary_category == primary_category
        and c.submitted_year >= min_year
        and len(c.abstract_head) >= min_abstract_chars
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", default="math.AG", help="arXiv category (default: math.AG)")
    parser.add_argument(
        "--max-results", type=int, default=200, help="API page size (max 2000 per arXiv)"
    )
    parser.add_argument(
        "--min-year", type=int, default=2015, help="filter submissions before this year"
    )
    parser.add_argument(
        "--min-abstract-chars", type=int, default=200, help="filter very short abstracts"
    )
    args = parser.parse_args()

    print(
        f"# arXMCP curate_seed: pulling {args.max_results} {args.category} "
        f"candidates submitted >= {args.min_year}",
        file=sys.stderr,
    )
    print(
        f"# politeness: paginating at <= {POLITENESS_SLEEP_SECONDS}s/page via "
        "tools._arxiv_api",
        file=sys.stderr,
    )

    try:
        # fetch_candidates owns pagination + parse + the inter-page politeness
        # sleep; for max_results <= 2000 this is a single request.
        candidates = fetch_candidates(args.category, args.max_results)
    except Exception as e:  # noqa: BLE001
        print(f"FETCH FAILED: {e}", file=sys.stderr)
        return 2

    filtered = filter_candidates(
        candidates,
        primary_category=args.category,
        min_year=args.min_year,
        min_abstract_chars=args.min_abstract_chars,
    )

    print(
        f"# {len(candidates)} returned, {len(filtered)} after"
        " primary-category/year/abstract filter",
        file=sys.stderr,
    )
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    print(f"# generated: {generated_at}", file=sys.stderr)
    print("paper_id\tyear\tn_authors\tprimary_category\tabstract_head")
    for c in filtered:
        print(c.as_tsv_row())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
