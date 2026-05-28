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

import gzip
import logging
import re
import tarfile
import urllib.error
from pathlib import Path

logger = logging.getLogger("notebook_common")

# Repo root resolved from this file's location: tools/_notebook_common.py
# → tools/ → repo root.
REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# Variant 1 layout constants.
NOTEBOOKS_BASE: Path = REPO_ROOT / "var" / "arxmcp" / "notebooks"
CORPUS_PARSED_DIR: Path = REPO_ROOT / "var" / "arxmcp" / "corpus" / "parsed"
CORPUS_CHUNKS_DIR: Path = REPO_ROOT / "var" / "arxmcp" / "corpus" / "chunks"
CORPUS_EMBEDDINGS_DIR: Path = REPO_ROOT / "var" / "arxmcp" / "corpus" / "embeddings"
# notebook-preamble-recovery-m1: raw `.tex` source root. Used by the
# `fetch_raw_tex_if_missing` helper and the `tools/recover_preambles.py`
# back-fill script. `fetch_eprint` internally appends `paper_id` so this
# is the PARENT dir, never the per-paper subdir.
CORPUS_RAW_DIR: Path = REPO_ROOT / "var" / "arxmcp" / "corpus" / "raw"

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


def fetch_raw_tex_if_missing(
    paper_id: str,
    raw_dir: Path,
    *,
    contact_email: str | None = None,
) -> bool:
    """Ensure raw `.tex` source for ``paper_id`` exists under ``raw_dir``.

    notebook-preamble-recovery-m1 — Option A from the scan brief at
    ``.claude/notes/scans/preamble-without-raw-tex-2026-05-27.md``.

    ``raw_dir`` is the PARENT directory (e.g. ``var/arxmcp/corpus/raw/``);
    ``fetch_eprint`` appends ``paper_id`` internally and creates the
    paper-specific subdir.

    Idempotency gate: if ``raw_dir / paper_id`` already exists AND
    contains at least one ``.tex`` file, return ``True`` without
    network egress. Operators can re-run the back-fill freely.

    Politeness: this helper does NOT sleep — the caller owns the
    politeness budget (3-second inter-request spacing per arXiv TOU,
    same contract `fetch_eprint` documents). Always call
    ``politeness_sleep(start_time)`` BEFORE invoking this helper if
    the previous call was a network request to ``export.arxiv.org``.

    Exception envelope (matches `fetch_seed.py`):
      - ``urllib.error.HTTPError`` — 404 (withdrawn paper), 503 (rate
        limit), any other non-2xx. Caller handles 503 backoff if needed.
      - ``RuntimeError`` — path-traversal attempt during tarball
        extraction (``_safe_extract`` Threat-1 mitigation). Logged at
        ERROR level (security event), not WARNING.
      - ``OSError`` — disk full, permission denied, gzip decode error
        propagated as OSError subclass.
      - ``tarfile.TarError`` — malformed tarball.
      - ``gzip.BadGzipFile`` — corrupt gzip payload.

    Returns
    -------
    ``True`` if raw `.tex` is now on disk (either was already there,
    or was successfully fetched and extracted). ``False`` on any
    per-paper failure — the notebook run / back-fill MUST continue
    past `False` returns (AC4).
    """
    paper_raw_dir = raw_dir / paper_id
    if paper_raw_dir.is_dir() and any(paper_raw_dir.glob("*.tex")):
        # Idempotent skip: raw .tex already present from a prior run.
        logger.debug(
            "[%s] raw_tex: skip — paper_raw_dir already has .tex files",
            paper_id,
        )
        return True

    # Late import to avoid cycles: tools.arxiv_fetch imports nothing
    # from _notebook_common, but keeping the import lazy means tests
    # that don't exercise the raw-tex path don't pay the import cost.
    from tools.arxiv_fetch import fetch_eprint  # noqa: PLC0415

    try:
        fetch_eprint(paper_id, raw_dir, contact_email=contact_email)
    except urllib.error.HTTPError as exc:
        # 404 (withdrawn), 503 (rate limit), and friends. Caller may
        # implement retry/backoff above; the inline notebook path
        # logs + returns False so the operator re-runs later.
        reason = "withdrawn_404" if exc.code == 404 else f"http_{exc.code}"
        logger.warning(
            "[%s] raw_tex: %s on /e-print/ (%s); preamble will be empty",
            paper_id, reason, exc,
        )
        return False
    except RuntimeError as exc:
        # Path-traversal attempt during _safe_extract — log as ERROR
        # (security event), not WARNING. Notebook run continues but
        # the operator should investigate the tarball.
        logger.error(
            "[%s] raw_tex: SECURITY EVENT during tarball extraction: %s",
            paper_id, exc,
        )
        return False
    except (OSError, tarfile.TarError, gzip.BadGzipFile) as exc:
        # Disk failures, malformed tarballs, corrupt gzip. Recoverable
        # per-paper miss; notebook run continues.
        logger.warning(
            "[%s] raw_tex: extraction failed (%s); preamble will be empty",
            paper_id, exc,
        )
        return False

    logger.info("[%s] raw_tex: fetched + extracted", paper_id)
    return True


__all__ = [
    "CORPUS_CHUNKS_DIR",
    "CORPUS_EMBEDDINGS_DIR",
    "CORPUS_PARSED_DIR",
    "CORPUS_RAW_DIR",
    "NOTEBOOKS_BASE",
    "NotebookError",
    "REPO_ROOT",
    "SLUG_RE",
    "fetch_raw_tex_if_missing",
    "notebook_dir",
    "read_paper_ids_from_papers_txt",
    "validate_slug",
]
