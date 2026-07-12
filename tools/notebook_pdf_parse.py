"""Shipped MinerU Stage-1 parser for a textbook-kind notebook.

ingest-robustness-m1 AC2. Runs the MinerU + LaTeXML render for a PDF already
staged under a notebook's ``pdfs/`` dir, producing ``parsed/<flat>/index.html``
— the SAME artifact the browser upload route produces via
:class:`server.parse_tracker.ParseTaskTracker`, and the input the chunk+embed
tail (``tools/notebook_textbook_ingest.py``) consumes. This replaces the
gitignored ad-hoc ``var/`` drivers (``var/phase2_textbook_driver.py``,
``var/parse_pdfs.py``) with a supported, tested CLI.

Stage split (mirrors ``server/parse_tracker.py::_run_parse``)::

    run_mineru_sandboxed(pdf_path, output_dir)          -> MinerUResult
    render_mineru_to_html(result, parsed_dir, paper_id) -> parsed_dir/<flat>/index.html

The chunk + embed + LanceDB write is a SEPARATE step
(``tools/notebook_textbook_ingest.py``), so a PDF paper's full lane is::

    make init NOTEBOOK=<slug> MINERU_BIN=<abs path>              # AC3, once
    #  ... drop <flat>.pdf into var/arxmcp/notebooks/<slug>/pdfs/ ...
    python tools/notebook_pdf_parse.py <slug> --paper-id <id>       # AC2 (this tool)
    python tools/notebook_textbook_ingest.py <slug> --paper-id <id> # chunk + embed

The mineru binary path is resolved by
``ingest.textbook_parser._resolve_mineru_binary`` (AC3): explicit arg >
``ARXMCP_MINERU_BIN`` env > persisted operator_settings > ``shutil.which`` > raise.

Usage::

    uv run python tools/notebook_pdf_parse.py <slug> --paper-id <id> [--paper-id ...] \\
        [--timeout-s N] [--force]

Exit codes:
    0 — every requested paper produced (or already had) parsed/<flat>/index.html
    1 — slug invalid, a paper_id malformed, a staged PDF missing, or a parse failed
    2 — no --paper-id given
"""

from __future__ import annotations

import argparse
import logging
import sys

from ingest.identifiers import is_valid_paper_id
from ingest.textbook_parser import run_mineru_sandboxed
from ingest.textbook_renderer import _flat_paper_id, render_mineru_to_html
from tools._notebook_common import NotebookError, notebook_dir, validate_slug

logger = logging.getLogger("notebook_pdf_parse")


def _parse_one(
    slug: str,
    paper_id: str,
    *,
    timeout_s: int | None,
    force: bool,
) -> bool:
    """Parse one staged PDF into ``parsed/<flat>/index.html``.

    Returns True on success (produced, or idempotently skipped) and False on a
    recoverable per-paper failure (missing PDF / parse error) — the caller
    aggregates failures rather than aborting the whole batch.
    """
    nb_dir = notebook_dir(slug)
    flat = _flat_paper_id(paper_id)
    parsed_dir = nb_dir / "parsed"
    index_html = parsed_dir / flat / "index.html"
    pdf_path = nb_dir / "pdfs" / f"{flat}.pdf"

    if index_html.is_file() and not force:
        logger.info(
            "[%s] already parsed at %s — skipping (pass --force to re-run)",
            paper_id, index_html,
        )
        return True

    if not pdf_path.is_file():
        logger.error(
            "[%s] no staged PDF at %s — drop the file there first "
            "(the browser upload route stores PDFs under pdfs/)",
            paper_id, pdf_path,
        )
        return False

    output_dir = parsed_dir / flat / "_mineru"
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = run_mineru_sandboxed(pdf_path, output_dir, timeout_s=timeout_s)
        render_mineru_to_html(result, parsed_dir, paper_id)
    except (RuntimeError, OSError) as exc:
        logger.error("[%s] parse failed: %s", paper_id, exc)
        return False

    if not index_html.is_file():
        logger.error(
            "[%s] parse completed but %s was not produced", paper_id, index_html,
        )
        return False
    logger.info("[%s] parsed -> %s", paper_id, index_html)
    return True


def run(
    slug: str,
    paper_ids: list[str],
    *,
    timeout_s: int | None = None,
    force: bool = False,
) -> int:
    """Pure function — parse each staged PDF. Returns an exit code."""
    validate_slug(slug)  # raises NotebookError on a malformed/unsafe slug
    nb_dir = notebook_dir(slug)
    if not nb_dir.exists():
        raise NotebookError(
            f"notebook dir does not exist at {nb_dir} — "
            f"run `tools/notebook_init.py {slug}` first"
        )
    if not paper_ids:
        raise NotebookError("no --paper-id given; nothing to parse")

    bad = [pid for pid in paper_ids if not is_valid_paper_id(pid)]
    if bad:
        raise NotebookError(
            f"invalid paper_id(s): {bad!r} (expected an arXiv id or the "
            f"textbook:<slug> form)"
        )

    failures: list[str] = []
    for pid in paper_ids:
        if not _parse_one(slug, pid, timeout_s=timeout_s, force=force):
            failures.append(pid)

    produced = len(paper_ids) - len(failures)
    print(
        f"notebook_pdf_parse: total={len(paper_ids)} "
        f"ok={produced} fail={len(failures)}"
    )
    if failures:
        print(f"  failed (missing PDF or parse error): {failures}", file=sys.stderr)
        return 1
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "slug",
        help="Notebook slug (must match ^[a-z][a-z0-9-]{2,30}$).",
    )
    parser.add_argument(
        "--paper-id",
        dest="paper_ids",
        action="append",
        default=[],
        help=(
            "Paper id whose staged PDF (pdfs/<flat>.pdf) to parse. Repeatable; "
            "accepts an arXiv id or the textbook:<slug> form."
        ),
    )
    parser.add_argument(
        "--timeout-s",
        type=int,
        default=None,
        help=(
            "Per-PDF MinerU wall-clock cap in seconds. Default: "
            "ARXMCP_MINERU_TIMEOUT_S or 1800."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-parse even if parsed/<flat>/index.html already exists.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not args.paper_ids:
        print("error: at least one --paper-id is required", file=sys.stderr)
        return 2
    try:
        return run(
            args.slug,
            args.paper_ids,
            timeout_s=args.timeout_s,
            force=args.force,
        )
    except NotebookError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
