"""Destructively delete a notebook directory; optionally also per-paper corpus assets.

Default: ``shutil.rmtree(var/arxmcp/notebooks/<slug>/)`` with an
interactive typed-slug confirmation prompt. ``--force`` skips the
prompt. ``--purge-corpus-too`` ADDITIONALLY removes per-paper
``corpus/{parsed,chunks,embeddings}/<paper_id>/`` for paper_ids
**unique to this notebook** (set difference across sibling notebooks'
``papers.txt`` files; see FM-1 in the synthesis).

The per-paper deletion uses set difference, NOT ``os.path.commonpath``.
``os.path.commonpath`` returns a common path prefix — it is the wrong
primitive for paper-membership uniqueness.

A ``pdf-deferred/`` subdir (shimura-varieties has one — Milne notes +
Caraiani notes) is irrecoverable on delete. We emit a ``WARN:`` to
stderr listing those PDFs BEFORE the rmtree, regardless of ``--force``.
``--force`` skips the interactive confirmation; it does NOT silence
the warning. See FM-8 in the synthesis.

Usage:

    uv run python tools/notebook_purge.py <slug> [--purge-corpus-too] [--force]

Exit codes:
    0 — notebook purged (and corpus assets if --purge-corpus-too)
    1 — slug validation failed, typed-slug confirmation mismatched,
        or notebook dir doesn't exist
    2 — confirmation aborted by user (e.g. typed wrong slug, EOF)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys

from tools._notebook_common import (
    CORPUS_CHUNKS_DIR,
    CORPUS_EMBEDDINGS_DIR,
    CORPUS_PARSED_DIR,
    NOTEBOOKS_BASE,
    NotebookError,
    notebook_dir,
    read_paper_ids_from_papers_txt,
    validate_slug,
)


def _gather_pdf_deferred_warnings(nb_dir) -> list[str]:
    """Return human-readable lines naming PDFs about to be lost.

    Looks at ``<nb_dir>/pdf-deferred/manifest.json`` (if present) and
    enumerates ``<nb_dir>/pdf-deferred/*.pdf``. Returns an empty list
    if no pdf-deferred subdir exists.
    """
    pdf_dir = nb_dir / "pdf-deferred"
    if not pdf_dir.is_dir():
        return []
    lines = []
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        return []
    manifest = pdf_dir / "manifest.json"
    titles: dict[str, str] = {}
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            titles = data.get("manual_titles") or {}
        except (OSError, json.JSONDecodeError):
            titles = {}
    for pdf in pdfs:
        title = titles.get(pdf.name, "")
        size_mb = pdf.stat().st_size / 1024 / 1024
        suffix = f" — {title}" if title else ""
        lines.append(f"  {pdf.name} ({size_mb:.1f} MB){suffix}")
    return lines


def _compute_unique_paper_ids(
    slug: str, *, notebooks_base=None
) -> tuple[set[str], set[str]]:
    """Return (unique_to_this_notebook, shared_with_others).

    Reads ``papers.txt`` for THIS notebook + every sibling notebook
    under ``notebooks_base``. Computes set difference. ``notebooks_base``
    is exposed for tests.
    """
    base = notebooks_base or NOTEBOOKS_BASE
    nb_dir = base / slug
    papers_txt = nb_dir / "papers.txt"
    # If papers.txt is missing (partial state), treat as empty set so
    # we don't attempt corpus deletion on an unknown paper-id set.
    this_ids: set[str] = (
        set(read_paper_ids_from_papers_txt(papers_txt))
        if papers_txt.is_file()
        else set()
    )
    other_ids: set[str] = set()
    if base.is_dir():
        for sibling in base.iterdir():
            if not sibling.is_dir() or sibling.name == slug:
                continue
            sp = sibling / "papers.txt"
            if sp.is_file():
                other_ids |= set(read_paper_ids_from_papers_txt(sp))
    return this_ids - other_ids, this_ids & other_ids


def _purge_corpus_assets(unique_ids: set[str]) -> int:
    """Delete corpus/{parsed,chunks,embeddings}/<id>/ for each unique ID.

    Returns the count of paper-asset trees actually removed.
    """
    removed = 0
    for paper_id in sorted(unique_ids):
        for base_dir in (CORPUS_PARSED_DIR, CORPUS_CHUNKS_DIR, CORPUS_EMBEDDINGS_DIR):
            target = base_dir / paper_id
            if target.is_dir():
                shutil.rmtree(target)
                removed += 1
    return removed


def run(
    slug: str,
    *,
    purge_corpus_too: bool = False,
    force: bool = False,
    stdin=None,
) -> int:
    """Pure function — returns exit code. Tests pass synthetic stdin.

    ``stdin`` is a file-like object readline()'d for the typed-slug
    confirmation when ``--force`` is NOT set. Defaults to ``sys.stdin``.
    """
    validate_slug(slug)
    nb_dir = notebook_dir(slug)
    if not nb_dir.exists():
        raise NotebookError(
            f"notebook dir does not exist at {nb_dir} — nothing to purge"
        )

    # FM-8 WARN — ALWAYS emit, even under --force. Lists the PDFs that
    # are about to become irrecoverable.
    pdf_warn_lines = _gather_pdf_deferred_warnings(nb_dir)
    if pdf_warn_lines:
        print(
            f"WARN: {nb_dir}/pdf-deferred/ contains "
            f"{len(pdf_warn_lines)} PDF(s) not backed by corpus assets. "
            f"Deleting these requires re-downloading from original URLs.",
            file=sys.stderr,
        )
        for line in pdf_warn_lines:
            print(line, file=sys.stderr)
        print(file=sys.stderr)

    # Compute corpus uniqueness BEFORE rmtree so the slug's papers.txt
    # is still readable.
    unique_ids: set[str] = set()
    shared_ids: set[str] = set()
    if purge_corpus_too:
        unique_ids, shared_ids = _compute_unique_paper_ids(slug)
        if shared_ids:
            print(
                f"NOTE: {len(shared_ids)} paper_id(s) shared with sibling "
                f"notebooks will NOT be deleted from corpus/:",
                file=sys.stderr,
            )
            for pid in sorted(shared_ids):
                print(f"  {pid}", file=sys.stderr)

    if not force:
        extra = (
            f" AND per-paper corpus assets for {len(unique_ids)} unique IDs"
            if purge_corpus_too
            else ""
        )
        prompt = (
            f"About to DELETE {nb_dir}/{extra}.\n"
            f"Type the notebook slug ({slug!r}) to confirm: "
        )
        print(prompt, end="", flush=True)
        in_stream = stdin or sys.stdin
        try:
            typed = in_stream.readline().strip()
        except (EOFError, KeyboardInterrupt):
            print("\naborted (EOF or interrupt)", file=sys.stderr)
            return 2
        if typed != slug:
            print(
                f"\naborted: typed {typed!r}, expected {slug!r} — "
                f"no files were deleted",
                file=sys.stderr,
            )
            return 2

    shutil.rmtree(nb_dir)
    print(f"removed {nb_dir}")

    if purge_corpus_too:
        removed = _purge_corpus_assets(unique_ids)
        print(
            f"removed {removed} per-paper asset tree(s) across "
            f"corpus/{{parsed,chunks,embeddings}}/ for {len(unique_ids)} "
            f"unique paper_id(s)"
        )

    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "slug",
        help="Notebook slug to purge (must match ^[a-z][a-z0-9-]{2,30}$).",
    )
    parser.add_argument(
        "--purge-corpus-too",
        action="store_true",
        help=(
            "ALSO delete per-paper assets under corpus/{parsed,chunks,"
            "embeddings}/<paper_id>/ for paper_ids unique to this "
            "notebook (i.e. not referenced by any other notebook's "
            "papers.txt)."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Skip the interactive typed-slug confirmation. The "
            "pdf-deferred WARN is emitted regardless."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        return run(
            args.slug,
            purge_corpus_too=args.purge_corpus_too,
            force=args.force,
        )
    except NotebookError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
