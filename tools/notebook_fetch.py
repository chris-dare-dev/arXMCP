"""Fetch ar5iv HTML for any paper_id in a notebook missing from corpus/parsed.

Walks ``var/arxmcp/notebooks/<slug>/papers.txt``, validates each line,
and for every paper_id missing from ``var/arxmcp/corpus/parsed/<id>/index.html``
delegates to :func:`ingest.ar5iv_fetch.try_cache`. Delegation inherits
the existing security machinery: 100 MB cap, 5 s timeout, 429/503
handling, ``<math`` body-presence check. See the synthesis "Disagreement
1" resolution for why we delegate rather than re-implement HTTP.

notebook-preamble-recovery-m1: after each ar5iv hit, also pulls raw
``.tex`` source via :func:`tools._notebook_common.fetch_raw_tex_if_missing`
(which wraps :func:`tools.arxiv_fetch.fetch_eprint`). This populates
``var/arxmcp/corpus/raw/<paper_id>/`` so :func:`ingest.preamble.extract_preamble`
can run successfully on the ar5iv path — without it, every ar5iv-only
paper has ``preamble_ref=null`` and ``get_definitions`` returns empty.

**Requires ``ARXMCP_CONTACT_EMAIL``** for the User-Agent header on the
``/e-print/`` request (arXiv TOU §3 politeness contract). Enforced at
:func:`run` entry — clear NotebookError if unset. NOT enforced at
module import (that would break every test that doesn't set the env).

Honors the 3-second-per-IP politeness contract (see
``ingest/ar5iv_fetch.py`` module docstring and
``tools/arxiv_fetch.py:29``) by sleeping between non-first fetches.
The raw-tex fetch adds its OWN 3-second sleep before each call — the
ar5iv and ``export.arxiv.org`` budgets are separate per the scan brief
(``.claude/notes/scans/preamble-without-raw-tex-2026-05-27.md``).

Summary line at end:

    fetched=N from_cache=M missing=K rate_limited=R malformed=J \
      raw_tex_recovered=P raw_tex_missing=M2

The four ar5iv miss categories are distinct — operators must NOT drop
``rate_limited`` IDs from their papers.txt (re-run after backoff).
See FM-4 in the synthesis. ``raw_tex_missing`` covers all non-OK raw-
tex outcomes (404 withdrawn, 503 rate-limited, tarball errors); see
``preamble.log`` for per-paper reasons.

Usage:

    uv run python tools/notebook_fetch.py <slug>

Exit codes:
    0 — every paper_id either cached, fetched, or rate-limited
        (rate-limited is recoverable; not a hard failure)
    1 — slug validation failed OR malformed papers.txt entries
        OR irrecoverable ``missing`` (ar5iv 404, no_math, etc.)
        OR ARXMCP_CONTACT_EMAIL unset.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from ingest.ar5iv_fetch import (
    DEFAULT_AR5IV_CACHE_DIR,
    DEFAULT_PARSED_DIR,
    try_cache,
)
from ingest.identifiers import is_valid_arxiv_paper_id
from tools._notebook_common import (
    CORPUS_RAW_DIR,
    NotebookError,
    fetch_raw_tex_if_missing,
    notebook_dir,
    read_paper_ids_from_papers_txt,
    validate_slug,
)

POLITENESS_SLEEP_SECONDS: float = 3.0


def run(slug: str, *, sleep_seconds: float = POLITENESS_SLEEP_SECONDS) -> int:
    """Fetch ar5iv HTML + raw .tex for every missing paper in the notebook.

    ``sleep_seconds`` is exposed for tests (set to 0.0 to skip the
    politeness sleep). Production callers should leave it at the
    default 3.0 s.

    AC7 (notebook-preamble-recovery-m1): ARXMCP_CONTACT_EMAIL is
    required at run() entry. Fail loudly with a clear NotebookError
    rather than letting per-paper RuntimeErrors leak from
    ``build_user_agent`` deep inside the loop. The check is at
    run-time (not import-time) so tests that don't exercise the raw-
    tex path don't need to set the env var.
    """
    if not os.environ.get("ARXMCP_CONTACT_EMAIL"):
        raise NotebookError(
            "ARXMCP_CONTACT_EMAIL is required for notebook ingest. "
            "Export it in your shell before re-running: "
            "export ARXMCP_CONTACT_EMAIL=you@example.com (arXiv TOU §3 "
            "politeness-contract — used in the /e-print/ User-Agent "
            "header). See .claude/notes/scans/preamble-without-raw-tex-"
            "2026-05-27.md for context."
        )
    validate_slug(slug)
    nb_dir = notebook_dir(slug)
    papers_txt = nb_dir / "papers.txt"
    raw_lines = read_paper_ids_from_papers_txt(papers_txt)

    # Pre-validate every line. Malformed entries are surfaced as
    # ``malformed=J`` per FM-5 — not silently dropped into ``missing``.
    valid_ids: list[str] = []
    malformed: list[str] = []
    for line in raw_lines:
        if is_valid_arxiv_paper_id(line):
            valid_ids.append(line)
        else:
            malformed.append(line)

    fetched: list[str] = []
    from_cache: list[str] = []
    missing: list[tuple[str, str]] = []  # (paper_id, reason)
    rate_limited: list[str] = []  # ar5iv 429 / 503 / timeout
    # notebook-preamble-recovery-m1 — raw-tex counters
    raw_tex_recovered: list[str] = []
    raw_tex_missing: list[str] = []

    # F4 fix: dropped the bare >1024-byte size heuristic. It admitted
    # corrupt local files (manually dropped invalid HTML, half-written
    # files from a crashed pre-m6 run) as cache hits. Always call
    # try_cache; it does the correct dual-file existence + content
    # validation. The sleep is suppressed when try_cache reports a
    # local-cache hit (no network round-trip).
    for paper_id in valid_ids:
        result = try_cache(
            paper_id,
            cache_dir=DEFAULT_AR5IV_CACHE_DIR,
            parsed_dir=DEFAULT_PARSED_DIR,
        )
        if result.hit:
            # Categorize: was this a local-cache hit (no fetch) or a
            # genuine fetch? try_cache returns reason="ok_local_cache"
            # when both files were already present; "ok" means a real
            # network fetch happened. Reflect that in our summary —
            # AND skip the politeness sleep on local-cache hits.
            if result.reason == "ok_local_cache":
                from_cache.append(paper_id)
            else:
                fetched.append(paper_id)
                # Sleep AFTER the network fetch so the next iteration
                # (if any) waits the full politeness interval.
                time.sleep(sleep_seconds)
            # notebook-preamble-recovery-m1: after each ar5iv hit, also
            # pull raw .tex so extract_preamble can run on the ar5iv
            # path. Sleep BEFORE the fetch (separate politeness budget
            # for export.arxiv.org); skip the sleep if the raw dir is
            # already populated (idempotent helper short-circuits at
            # zero network egress).
            paper_raw_dir = CORPUS_RAW_DIR / paper_id
            already_present = (
                paper_raw_dir.is_dir()
                and any(paper_raw_dir.glob("*.tex"))
            )
            if not already_present:
                time.sleep(sleep_seconds)
            if fetch_raw_tex_if_missing(paper_id, CORPUS_RAW_DIR):
                raw_tex_recovered.append(paper_id)
            else:
                raw_tex_missing.append(paper_id)
            continue
        # Miss. Sleep AFTER (it counted as an attempted fetch — server
        # saw the request). The reason strings match ingest/ar5iv_fetch.py
        # exactly (verified at ingest/ar5iv_fetch.py:154, 241, 250).
        if result.reason in {"http_429", "http_503", "timeout_or_network"}:
            rate_limited.append(paper_id)
        else:
            missing.append((paper_id, result.reason))
        time.sleep(sleep_seconds)

    # Summary line — the AC-required format.
    print(
        f"fetched={len(fetched)} "
        f"from_cache={len(from_cache)} "
        f"missing={len(missing)} "
        f"rate_limited={len(rate_limited)} "
        f"malformed={len(malformed)} "
        f"raw_tex_recovered={len(raw_tex_recovered)} "
        f"raw_tex_missing={len(raw_tex_missing)}"
    )

    if malformed:
        print("\nmalformed lines in papers.txt (not arXiv IDs):", file=sys.stderr)
        for line in malformed:
            print(f"  {line!r}", file=sys.stderr)
    if rate_limited:
        print(
            "\nrate-limited IDs — DO NOT drop these from papers.txt; "
            "re-run after a backoff (≥ 60 s):",
            file=sys.stderr,
        )
        for pid in rate_limited:
            print(f"  {pid}", file=sys.stderr)
    if missing:
        print(
            "\nmissing IDs — ar5iv lacks these; drop manually OR provide "
            "local HTML at var/arxmcp/corpus/parsed/<paper_id>/index.html:",
            file=sys.stderr,
        )
        for pid, reason in missing:
            print(f"  {pid}  reason={reason}", file=sys.stderr)

    # Exit non-zero if there's anything the operator needs to act on
    # beyond a retry. Rate-limited is recoverable (exit 0); malformed
    # and missing are not.
    return 1 if (malformed or missing) else 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "slug",
        help="Notebook slug (must match ^[a-z][a-z0-9-]{2,30}$).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        return run(args.slug)
    except NotebookError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
