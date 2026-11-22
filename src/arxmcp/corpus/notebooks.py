"""What a notebook is on disk: its slug, its directory and its dataset path.

This module is the single source of truth for slug validation and the
per-notebook path layout (Variant 1: global `corpus/`, per-notebook
`lancedb/`). Every box that opens a notebook derives its paths here, so
they share the same path constants and slug validation.

The slug regex (:data:`arxmcp.settings.NOTEBOOK_SLUG_RE`) is the FIRST-LINE defense
against path traversal (Threat 1). A path containment check at
``(notebooks_base / slug).resolve()`` is the belt-and-braces secondary
check.
"""

from __future__ import annotations

from pathlib import Path

from arxmcp.settings import NOTEBOOK_SLUG_RE, ApplicationPaths

# Repo root resolved from this file's location: src/arxmcp/corpus/notebooks.py
# → tools/ → repo root.
REPO_ROOT: Path = Path(__file__).resolve().parents[3]

_APPLICATION_PATHS = ApplicationPaths.resolve()
# Compatibility aliases; the root and fixed children come from one resolver.
NOTEBOOKS_BASE: Path = _APPLICATION_PATHS.notebooks
CORPUS_PARSED_DIR: Path = _APPLICATION_PATHS.corpus / "parsed"
CORPUS_CHUNKS_DIR: Path = _APPLICATION_PATHS.corpus / "chunks"
CORPUS_EMBEDDINGS_DIR: Path = _APPLICATION_PATHS.corpus / "embeddings"
# notebook-preamble-recovery-m1: raw `.tex` source root. Used by
# :func:`arxmcp.ingest.notebooks.fetch_raw_tex_if_missing` and the
# `src/arxmcp/tools/recover_preambles.py` back-fill script. `fetch_eprint`
# internally appends `paper_id` so this is the PARENT dir, never the
# per-paper subdir.
CORPUS_RAW_DIR: Path = _APPLICATION_PATHS.corpus / "raw"

class NotebookError(RuntimeError):
    """Raised by any notebook helper when a precondition fails.

    Prefer this over ``assert`` per CLAUDE.md §4.7 ("`assert` is BANNED
    for invariants — Python ``-O`` strips them").
    """


def validate_slug(slug: str) -> None:
    """Reject any slug that doesn't match :data:`arxmcp.settings.NOTEBOOK_SLUG_RE`.

    Raises :class:`NotebookError` (a :class:`RuntimeError` subclass).
    This is the FIRST check every script's ``main()`` performs, before
    any path construction. See FM-2 in the synthesis.
    """
    if not isinstance(slug, str):
        raise NotebookError(
            f"slug must be a string, got {type(slug).__name__}"
        )
    if not NOTEBOOK_SLUG_RE.fullmatch(slug):
        raise NotebookError(
            f"invalid notebook slug {slug!r}: must match "
            f"{NOTEBOOK_SLUG_RE.pattern!r} (lowercase letter start, then "
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

    Closes F3 (HIGH) from the m6 critique: if ``nb_base/<slug>`` IS a
    symlink (regardless of where it points), refuse to operate on it.
    Both the regex-pass-then-pre-create-symlink and the legitimate-
    symlink-to-another-notebook cases are covered. Operators creating
    notebook directories via the m6 scripts will never produce symlinks;
    a symlink at the slug name implies the directory was pre-created
    out-of-band, which is a red flag worth blocking on.

    The ``base`` argument is for tests — production callers pass the
    default. Both ``base`` and the constructed target are resolved
    BEFORE comparison so symlinks don't sneak past the containment
    check. ``base`` may be a non-existent directory (tests use
    ``tmp_path`` subdirs that don't exist yet) — we use ``resolve
    (strict=False)`` semantics so non-existence is fine.
    """
    validate_slug(slug)
    nb_base = (base or NOTEBOOKS_BASE).resolve()
    # F3: refuse symlinks BEFORE resolving (we want to detect the
    # symlink itself, not its target). Use the un-resolved path so
    # is_symlink() reports True on the link, not the target.
    unresolved_target = nb_base / slug
    if unresolved_target.is_symlink():
        raise NotebookError(
            f"notebook path {unresolved_target} is a symlink — "
            f"refusing for safety. Investigate before proceeding; if "
            f"intentional, replace with a real directory."
        )
    target = unresolved_target.resolve()
    # Containment check: target must be a child of nb_base.
    try:
        target.relative_to(nb_base)
    except ValueError as exc:  # pragma: no cover — regex makes this unreachable
        raise NotebookError(
            f"slug {slug!r} resolves outside notebooks base "
            f"({target} not under {nb_base})"
        ) from exc
    return target


def notebook_lancedb_path(slug: str, *, base: Path | None = None) -> Path:
    """Return the per-notebook LanceDB dataset path for ``slug``.

    This is ``notebook_dir(slug) / "lancedb"`` — the same path
    ``src/arxmcp/tools/notebook_ingest.py`` writes to and the MCP server reads
    when notebook-scoped retrieval is active (notebook-retrieval-m1,
    fork C). It inherits :func:`notebook_dir`'s slug validation +
    symlink rejection + containment check (Threat 1), so the returned
    path is safe to hand to ``lancedb.connect``.

    **Shared seam (stepping-stone shaping, notebook-retrieval-m1 AC8):**
    both the fork-C startup path (`src/arxmcp/settings/config.py` deriving
    ``lancedb_path`` from ``ARXMCP_NOTEBOOK``) AND the future fork-A
    per-request routing path (`filters.notebook=<slug>`) call THIS
    helper, so the C→A migration is additive — A does not re-derive
    the path or re-implement the slug-safety contract.

    The path may not exist yet (a notebook can be registered before
    it is ingested); callers that require an ingested corpus check
    for ``corpus-version.json`` / ``chunks.lance`` themselves.
    """
    return notebook_dir(slug, base=base) / "lancedb"


def read_paper_ids_from_papers_txt(papers_txt: Path) -> list[str]:
    """Read a notebook's ``papers.txt``, skipping ``#``-comments and blanks.

    Mirrors :func:`arxmcp.ingest.bulk_ingest._read_paper_ids` but without
    validating against the arXiv ID regex — that's the caller's job
    (different callers want different categorization: ``notebook_fetch.py``
    surfaces malformed lines as ``malformed=J``, while
    ``notebook_purge.py`` only needs the union to compute set
    difference).
    """
    if not papers_txt.is_file():
        raise NotebookError(
            f"papers.txt not found at {papers_txt} — run "
            f"`src/arxmcp/tools/notebook_init.py {papers_txt.parent.name}` first"
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
    "CORPUS_RAW_DIR",
    "NOTEBOOKS_BASE",
    "NotebookError",
    "REPO_ROOT",
    "notebook_dir",
    "notebook_lancedb_path",
    "read_paper_ids_from_papers_txt",
    "validate_slug",
]
