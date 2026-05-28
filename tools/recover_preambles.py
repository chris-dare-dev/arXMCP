"""Back-fill raw `.tex` source + preamble.json for already-ingested papers.

notebook-preamble-recovery-m1 — one-shot recovery for papers that were
ingested via the ar5iv-only path before this milestone shipped. Without
the back-fill, every ar5iv-only paper has ``preamble_ref=null`` and
``get_definitions`` returns ``{definitions: [], total: 0,
index_status: "absent"}``.

Walks ``var/arxmcp/corpus/parsed/<paper_id>/index.html`` (137 papers
live as of 2026-05-28; 0 in ``corpus/raw/``). For each paper missing a
``preamble.json``:

    1. ``politeness_sleep`` to honor arXiv TOU §3 (3 s inter-request).
    2. ``fetch_eprint`` with 503 backoff (exponential up to 300 s).
    3. ``extract_preamble`` (idempotent — short-circuits via SHA256).

**Requires ARXMCP_CONTACT_EMAIL** (User-Agent for the /e-print/ request).

Usage::

    make ingest-recover-preambles
    # or, via the project's uv interpreter:
    uv run python -m tools.recover_preambles
    uv run python -m tools.recover_preambles --notebook bridgeland-stability
    uv run python -m tools.recover_preambles --limit 5   # smoke test

**Operator-warning on chunk_id rotation:** after the back-fill, the
next ``make re-embed-all`` will detect that body+preamble of every
back-filled paper now differs (because preamble is non-empty), so
``re_embed`` produces ``re_embedded ≫ copied`` for the affected
notebooks — 2-4 hours additional CPU. This is INTENDED behavior per
AC5 (LanceDB MVCC handles it cleanly). See
``.claude/notes/milestones/embedder-truncation-m1/operator-followup.md``.

Exit codes::

    0 — every paper either recovered, was already present, or failed
        with a recoverable reason (404 withdrawn, security event)
    1 — env var missing, malformed args, or any structural failure
    2 — no candidate papers discovered (corpus/parsed/ empty)
"""

from __future__ import annotations

import argparse
import http
import logging
import os
import sys
import time
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path

from ingest.identifiers import is_valid_arxiv_paper_id
from ingest.preamble import (
    PER_PAPER_FAILURE_EXCEPTIONS as PREAMBLE_FAILURES,
)
from ingest.preamble import extract_preamble
from tools._notebook_common import (
    CORPUS_PARSED_DIR,
    CORPUS_RAW_DIR,
    NOTEBOOKS_BASE,
    NotebookError,
    read_paper_ids_from_papers_txt,
    validate_slug,
)

logger = logging.getLogger("recover_preambles")

POLITENESS_SLEEP_SECONDS: float = 3.0
DEFAULT_503_BACKOFF_SECONDS: float = 60.0
MAX_503_BACKOFF_SECONDS: float = 300.0
# Path the chunker / definitions indexer reads from.
PREAMBLE_OUTPUT_DIR: Path = (
    Path(__file__).resolve().parent.parent
    / "var" / "arxmcp" / "corpus" / "preamble"
)


@dataclass
class RecoverySummary:
    total_candidates: int = 0
    already_has_preamble: int = 0
    raw_tex_fetched: int = 0
    raw_tex_already_present: int = 0
    preamble_recovered: int = 0
    preamble_failed: list[tuple[str, str]] = field(default_factory=list)
    withdrawn_404: list[str] = field(default_factory=list)
    other_fetch_errors: list[tuple[str, str]] = field(default_factory=list)


def _has_preamble_json(paper_id: str) -> bool:
    """Return True iff a ``preamble.json`` already exists for this paper."""
    return (PREAMBLE_OUTPUT_DIR / paper_id / "preamble.json").is_file()


def _has_raw_tex(paper_id: str) -> bool:
    """Return True iff at least one ``.tex`` exists under the paper's raw dir."""
    paper_raw_dir = CORPUS_RAW_DIR / paper_id
    return paper_raw_dir.is_dir() and any(paper_raw_dir.glob("*.tex"))


def _fetch_raw_tex_with_503_backoff(paper_id: str) -> str:
    """Call fetch_raw_tex_if_missing with 503 retry loop.

    Returns one of: ``"ok"``, ``"already_present"``, ``"withdrawn_404"``,
    ``"max_backoff_exceeded"``, ``"other_error"``. The notebook
    `fetch_raw_tex_if_missing` helper swallows 503 (logs and returns
    False); for the back-fill we want explicit retry-with-backoff so a
    transient arXiv overload doesn't drop the remaining papers.
    """
    if _has_raw_tex(paper_id):
        return "already_present"

    # Late import: fetch_eprint is what raises HTTPError(503) — the
    # helper would swallow it. We bypass the helper for the retry
    # loop and re-use it only for the final success-path side effects
    # (logging at INFO + writing to extraction dir). Cleaner: call
    # fetch_eprint directly with our retry logic, then return "ok".
    from tools.arxiv_fetch import (  # noqa: PLC0415
        fetch_eprint,
        parse_retry_after,
    )

    backoff = DEFAULT_503_BACKOFF_SECONDS
    while True:
        try:
            fetch_eprint(paper_id, CORPUS_RAW_DIR)
            return "ok"
        except urllib.error.HTTPError as exc:
            is_503 = exc.code == http.HTTPStatus.SERVICE_UNAVAILABLE.value
            if exc.code == 404:
                return "withdrawn_404"
            if is_503 and backoff < MAX_503_BACKOFF_SECONDS:
                wait = parse_retry_after(
                    exc.headers.get("Retry-After"), backoff
                )
                logger.warning(
                    "[%s] 503; backing off %.0fs (cap %.0fs)",
                    paper_id, wait, MAX_503_BACKOFF_SECONDS,
                )
                time.sleep(wait)
                backoff = min(backoff * 2, MAX_503_BACKOFF_SECONDS)
                continue
            if is_503:
                return "max_backoff_exceeded"
            logger.warning(
                "[%s] http %d on /e-print/: %s",
                paper_id, exc.code, exc,
            )
            return "other_error"


def _discover_candidates(notebook_slug: str | None) -> list[str]:
    """Return the list of paper_ids to consider for back-fill.

    Default: every directory under ``corpus/parsed/`` with a valid arXiv
    paper_id-shaped name. With ``--notebook=<slug>``, restrict to papers
    in that notebook's ``papers.txt``.
    """
    if notebook_slug is not None:
        validate_slug(notebook_slug)
        papers_txt = NOTEBOOKS_BASE / notebook_slug / "papers.txt"
        all_ids = read_paper_ids_from_papers_txt(papers_txt)
    else:
        if not CORPUS_PARSED_DIR.is_dir():
            return []
        all_ids = [
            p.name for p in CORPUS_PARSED_DIR.iterdir() if p.is_dir()
        ]
    # Filter to valid arXiv IDs; quietly skip directories that aren't
    # paper-shaped (e.g. .DS_Store on macOS).
    return sorted(pid for pid in all_ids if is_valid_arxiv_paper_id(pid))


def run(
    *,
    notebook_slug: str | None = None,
    limit: int | None = None,
    sleep_seconds: float = POLITENESS_SLEEP_SECONDS,
) -> RecoverySummary:
    """Run the back-fill. Returns a RecoverySummary; never raises on
    per-paper failures (404, 503, etc.) — those are logged and
    aggregated.
    """
    if not os.environ.get("ARXMCP_CONTACT_EMAIL"):
        raise NotebookError(
            "ARXMCP_CONTACT_EMAIL is required for recover_preambles "
            "(arXiv TOU §3 — used in the /e-print/ User-Agent). "
            "Export it: export ARXMCP_CONTACT_EMAIL=you@example.com"
        )

    candidates = _discover_candidates(notebook_slug)
    if not candidates:
        return RecoverySummary(total_candidates=0)
    work = candidates if limit is None else candidates[:limit]

    summary = RecoverySummary(total_candidates=len(work))
    for n, paper_id in enumerate(work, start=1):
        if _has_preamble_json(paper_id):
            summary.already_has_preamble += 1
            logger.debug(
                "[%s] already has preamble.json — skip", paper_id,
            )
            continue

        # Politeness sleep BEFORE the network call, unless we're going
        # to short-circuit on local raw-tex presence.
        if not _has_raw_tex(paper_id):
            time.sleep(sleep_seconds)

        outcome = _fetch_raw_tex_with_503_backoff(paper_id)
        if outcome == "already_present":
            summary.raw_tex_already_present += 1
        elif outcome == "ok":
            summary.raw_tex_fetched += 1
        elif outcome == "withdrawn_404":
            summary.withdrawn_404.append(paper_id)
            continue  # no .tex → can't extract preamble
        else:
            summary.other_fetch_errors.append((paper_id, outcome))
            continue

        # Now run extract_preamble. It catches its own
        # PER_PAPER_FAILURE_EXCEPTIONS (OSError, ValueError,
        # FileNotFoundError) AND raises them; we wrap.
        try:
            extract_preamble(paper_id)
        except PREAMBLE_FAILURES as exc:
            summary.preamble_failed.append((paper_id, str(exc)))
            continue
        summary.preamble_recovered += 1

        if n % 10 == 0:
            print(
                f"  [{n}/{len(work)}] preamble_recovered="
                f"{summary.preamble_recovered}",
                file=sys.stderr,
            )

    return summary


def _print_summary(summary: RecoverySummary) -> None:
    print(
        f"total={summary.total_candidates} "
        f"already_has_preamble={summary.already_has_preamble} "
        f"raw_tex_fetched={summary.raw_tex_fetched} "
        f"raw_tex_already_present={summary.raw_tex_already_present} "
        f"preamble_recovered={summary.preamble_recovered} "
        f"preamble_failed={len(summary.preamble_failed)} "
        f"withdrawn_404={len(summary.withdrawn_404)} "
        f"other_fetch_errors={len(summary.other_fetch_errors)}"
    )
    if summary.withdrawn_404:
        print("\nWithdrawn (404) papers (preamble unrecoverable):", file=sys.stderr)
        for pid in summary.withdrawn_404:
            print(f"  {pid}", file=sys.stderr)
    if summary.other_fetch_errors:
        print("\nFetch errors (re-runnable):", file=sys.stderr)
        for pid, reason in summary.other_fetch_errors:
            print(f"  {pid}  {reason}", file=sys.stderr)
    if summary.preamble_failed:
        print("\nPreamble extraction failed:", file=sys.stderr)
        for pid, reason in summary.preamble_failed:
            print(f"  {pid}  {reason}", file=sys.stderr)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Back-fill raw .tex + preamble.json for ar5iv-only papers. "
            "See .claude/notes/milestones/notebook-preamble-recovery-m1/ "
            "for context."
        ),
    )
    parser.add_argument(
        "--notebook",
        default=None,
        help=(
            "Scope the back-fill to one notebook's papers.txt. "
            "Default: all papers under var/arxmcp/corpus/parsed/."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after N candidates (for smoke-testing).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        summary = run(notebook_slug=args.notebook, limit=args.limit)
    except NotebookError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print_summary(summary)
    if summary.total_candidates == 0:
        return 2
    # Withdrawn / security-event misses are recoverable in the sense that
    # the operator can't fix them. Exit 0. Structural failures (every
    # candidate produced "other_fetch_errors") suggest a deeper outage
    # — exit 1 if NO papers were successfully recovered AND there were
    # fetch errors.
    if (
        summary.preamble_recovered == 0
        and summary.raw_tex_already_present == 0
        and summary.other_fetch_errors
    ):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = [
    "MAX_503_BACKOFF_SECONDS",
    "POLITENESS_SLEEP_SECONDS",
    "RecoverySummary",
    "run",
]
