#!/usr/bin/env python3
"""Fetch ONE math.AG paper from arXiv `/e-print/` and parse with LaTeXML.

E01_S02 smoke test for the ingestion path. Verifies politeness contract,
tar-vs-gzip Content-Type dispatch, and LaTeXML HTML5+MathML emission.

Usage:
    export ARXMCP_CONTACT_EMAIL=you@example.com
    python tools/fetch_one_paper.py 2307.01156

Exit codes:
    0  parse succeeded (HTML emitted, MathML present, ≥1 KB)
    1  parse failed (any of the four success conditions unmet)
    2  network/setup failure (no email, bad paper_id, http error)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.arxiv_fetch import (
    fetch_eprint,
    parse_with_latexml,
)
from tools.fetch_seed import PER_PAPER_FAILURE_EXCEPTIONS

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "raw"
PARSED_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "parsed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paper_id", help="arXiv ID, e.g. 2307.01156")
    args = parser.parse_args()

    try:
        fetch = fetch_eprint(args.paper_id, RAW_DIR)
    except Exception as e:  # noqa: BLE001 — boundary; we want any failure surfaced
        print(f"FETCH FAILED: {e}", file=sys.stderr)
        return 2

    print(
        f"fetched {fetch.paper_id}: "
        f"http={fetch.http_status} bytes={fetch.bytes_downloaded} "
        f"archive={fetch.archive_kind} main_tex={fetch.main_tex}"
    )

    if fetch.main_tex is None:
        print(f"PARSE SKIPPED: no .tex file in {fetch.raw_dir}", file=sys.stderr)
        return 1

    try:
        parse = parse_with_latexml(fetch.main_tex, PARSED_DIR, args.paper_id)
    except PER_PAPER_FAILURE_EXCEPTIONS as e:
        print(f"PARSE FAILED for {args.paper_id}: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(f"parsed {args.paper_id}: {parse.message}")
    return 0 if parse.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
