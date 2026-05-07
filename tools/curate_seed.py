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
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime

from tools.arxiv_fetch import (
    POLITENESS_SLEEP_SECONDS,
    build_user_agent,
)

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


@dataclass(frozen=True)
class Candidate:
    paper_id: str
    submitted_year: int
    n_authors: int
    primary_category: str
    abstract_head: str

    def as_tsv_row(self) -> str:
        return "\t".join(
            [
                self.paper_id,
                str(self.submitted_year),
                str(self.n_authors),
                self.primary_category,
                self.abstract_head[:120],
            ]
        )


def build_query_url(category: str, start: int, max_results: int) -> str:
    params = {
        "search_query": f"cat:{category}",
        "start": str(start),
        "max_results": str(max_results),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return f"{ARXIV_API_URL}?{urllib.parse.urlencode(params)}"


def parse_atom_feed(xml_bytes: bytes) -> list[Candidate]:
    root = ET.fromstring(xml_bytes)
    out: list[Candidate] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        id_url = (entry.findtext("atom:id", default="", namespaces=ATOM_NS) or "").strip()
        paper_id = id_url.rsplit("/", 1)[-1]
        if "v" in paper_id:
            paper_id = paper_id.split("v", 1)[0]

        published = entry.findtext("atom:published", default="", namespaces=ATOM_NS) or ""
        try:
            year = datetime.fromisoformat(published.replace("Z", "+00:00")).year
        except ValueError:
            year = 0

        authors = entry.findall("atom:author", ATOM_NS)
        primary = entry.find("arxiv:primary_category", ATOM_NS)
        primary_cat = primary.attrib.get("term", "") if primary is not None else ""

        summary = (entry.findtext("atom:summary", default="", namespaces=ATOM_NS) or "").strip()
        abstract_head = " ".join(summary.split())

        out.append(
            Candidate(
                paper_id=paper_id,
                submitted_year=year,
                n_authors=len(authors),
                primary_category=primary_cat,
                abstract_head=abstract_head,
            )
        )
    return out


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


def fetch_candidates(category: str, max_results: int, contact_email: str | None = None) -> bytes:
    url = build_query_url(category, start=0, max_results=max_results)
    req = urllib.request.Request(  # noqa: S310 — fixed export.arxiv.org host
        url, headers={"User-Agent": build_user_agent(contact_email)}
    )
    with urllib.request.urlopen(req, timeout=60.0) as resp:  # noqa: S310
        return resp.read()


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
        f"# politeness: 1 request, sleeping {POLITENESS_SLEEP_SECONDS}s before any follow-up",
        file=sys.stderr,
    )

    try:
        feed_bytes = fetch_candidates(args.category, args.max_results)
    except Exception as e:  # noqa: BLE001
        print(f"FETCH FAILED: {e}", file=sys.stderr)
        return 2
    time.sleep(POLITENESS_SLEEP_SECONDS)

    candidates = parse_atom_feed(feed_bytes)
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
