"""Shared helpers for the notebook CLI tools (proof-verify-handler-wiring-m6).

This module is the single source of truth for the notebook slug regex and
the per-notebook path layout (Variant 1: global `corpus/`, per-notebook
`lancedb/`).  Importing it from each of the four ``tools/notebook_*.py``
CLI scripts guarantees the four scripts share the same path constants
and slug validation.

The slug regex (``^[a-z][a-z0-9-]{2,30}$``) is the FIRST-LINE defense
against path traversal — see Threat 1 in
``.claude/notes/08-security-observability-ops.md`` and FM-2 in
``.claude/notes/milestones/proof-verify-handler-wiring-m6/research-synthesis.md``.
A path containment check at ``(notebooks_base / slug).resolve()`` is
the belt-and-braces secondary check.
"""

from __future__ import annotations

import re
from pathlib import Path

# Repo root resolved from this file's location: tools/_notebook_common.py
# → tools/ → repo root.
REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# Variant 1 layout constants.
NOTEBOOKS_BASE: Path = REPO_ROOT / "var" / "arxmcp" / "notebooks"
CORPUS_PARSED_DIR: Path = REPO_ROOT / "var" / "arxmcp" / "corpus" / "parsed"
CORPUS_CHUNKS_DIR: Path = REPO_ROOT / "var" / "arxmcp" / "corpus" / "chunks"
CORPUS_EMBEDDINGS_DIR: Path = REPO_ROOT / "var" / "arxmcp" / "corpus" / "embeddings"

# Slug regex — same constraint the roadmap skill applies to its own
# slugs. Lowercase ASCII + digits + hyphens, 3-31 chars, must start
# with a letter. Rejects ``..``, slashes, shell metacharacters,
# uppercase, leading hyphen.
SLUG_RE: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9-]{2,30}$")


class NotebookError(RuntimeError):
    """Raised by any notebook helper when a precondition fails.

    Prefer this over ``assert`` per CLAUDE.md §4.7 ("`assert` is BANNED
    for invariants — Python ``-O`` strips them").
    """


def validate_slug(slug: str) -> None:
    """Reject any slug that doesn't match :data:`SLUG_RE`.

    Raises :class:`NotebookError` (a :class:`RuntimeError` subclass).
    This is the FIRST check every script's ``main()`` performs, before
    any path construction. See FM-2 in the synthesis.
    """
    if not isinstance(slug, str):
        raise NotebookError(
            f"slug must be a string, got {type(slug).__name__}"
        )
    if not SLUG_RE.fullmatch(slug):
        raise NotebookError(
            f"invalid notebook slug {slug!r}: must match "
            f"{SLUG_RE.pattern!r} (lowercase letter start, then "
            f"3-30 chars of [a-z0-9-]). This rule rejects path "
            f"traversal (../, slashes), uppercase, and shell "
            f"metacharacters."
        )


def notebook_dir(slug: str, *, base: Path | None = None) -> Path:
    """Return the per-notebook dir under :data:`NOTEBOOKS_BASE`.

    Validates the slug AND verifies the resolved target stays inside
    ``base`` (defaults to :data:`NOTEBOOKS_BASE`). This is the
    belt-and-braces secondary defense from FM-2; the regex in
    :func:`validate_slug` is the primary defense.

    The ``base`` argument is for tests — production callers pass the
    default. Both ``base`` and the constructed target are resolved
    BEFORE comparison so symlinks don't sneak past the containment
    check. ``base`` may be a non-existent directory (tests use
    ``tmp_path`` subdirs that don't exist yet) — we use ``os.path.abspath``
    semantics via ``resolve(strict=False)`` so non-existence is fine.
    """
    validate_slug(slug)
    nb_base = (base or NOTEBOOKS_BASE).resolve()
    target = (nb_base / slug).resolve()
    # Containment check: target must be a child of nb_base.
    try:
        target.relative_to(nb_base)
    except ValueError as exc:  # pragma: no cover — regex makes this unreachable
        raise NotebookError(
            f"slug {slug!r} resolves outside notebooks base "
            f"({target} not under {nb_base})"
        ) from exc
    return target


def read_paper_ids_from_papers_txt(papers_txt: Path) -> list[str]:
    """Read a notebook's ``papers.txt``, skipping ``#``-comments and blanks.

    Mirrors :func:`ingest.bulk_ingest._read_paper_ids` but without
    validating against the arXiv ID regex — that's the caller's job
    (different callers want different categorization: ``notebook_fetch.py``
    surfaces malformed lines as ``malformed=J``, while
    ``notebook_purge.py`` only needs the union to compute set
    difference).
    """
    if not papers_txt.is_file():
        raise NotebookError(
            f"papers.txt not found at {papers_txt} — run "
            f"`tools/notebook_init.py {papers_txt.parent.name}` first"
        )
    out: list[str] = []
    for raw in papers_txt.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


__all__ = [
    "CORPUS_CHUNKS_DIR",
    "CORPUS_EMBEDDINGS_DIR",
    "CORPUS_PARSED_DIR",
    "NOTEBOOKS_BASE",
    "NotebookError",
    "REPO_ROOT",
    "SLUG_RE",
    "notebook_dir",
    "read_paper_ids_from_papers_txt",
    "validate_slug",
]
