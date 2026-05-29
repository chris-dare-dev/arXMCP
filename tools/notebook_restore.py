"""Restore an m6 export bundle into a target notebooks base + DB (m7).

Consumes a tar produced by ``GET /ui/api/notebooks/<slug>/export`` (see
:mod:`server.routes.notebooks`'s ``_build_export_manifest`` +
``_iter_safe_export_members``) and reproduces the notebook on a fresh (or
existing-with-``--force``) deployment: extracts the on-disk assets under
``<notebooks_base>/<slug>/`` AND re-inserts the manifest's ``notebooks`` row +
``notebook_papers`` junction rows into the target ``notebooks.db``.

**Security is load-bearing.** Tar extraction is a path-traversal / zip-slip
vector — the bundle is untrusted (it can come from anywhere; m6's producer-side
preflight cannot be relied upon for a hostile/tampered bundle). This module
applies TWO INDEPENDENT layers (m7 synthesis D1):

1. **Manual ``_safe_member`` pre-pass** (the PRIMARY gate): iterate
   ``tar.getmembers()`` BEFORE any extraction; REJECT THE WHOLE RESTORE on ANY
   member that is an absolute path, contains ``..``, is a symlink/hardlink, is a
   device/FIFO, or whose normalized name is neither ``manifest.json`` exactly nor
   begins with ``<slug>/`` (with post-``PurePosixPath``/``normpath`` normalization
   so trick forms like ``./<slug>/../escape`` are caught).
2. **``tarfile`` ``filter="data"``** (the BELT-AND-BRACES layer): PEP 706's
   strict filter independently rejects absolute paths, `..` escapes,
   sym/hardlinks, and special files. Available on Python 3.11.4+ (backported)
   and natively on 3.12+.

``--force`` semantics (m7 synthesis D2): permits the DB re-insert to overwrite
an existing slug row (``DELETE`` cascades to ``notebook_papers`` via FK, then
``INSERT``). ``--force`` does NOT allow extracting on top of an existing
``<notebooks_base>/<slug>/`` directory — that refusal is unconditional; the
operator must run ``tools/notebook_purge.py <slug>`` first. This separation
keeps the file-write and DB-write security surfaces independently auditable.

Usage::

    uv run python tools/notebook_restore.py <bundle.tar> \\
        [--notebooks-base <path>] [--db <path>] [--force]

Exit codes:
    0 — bundle restored (notebook + papers + assets)
    1 — safety / validation failure (bad member, bad slug, format version,
        existing dir, existing slug without --force, etc.)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

from tools._notebook_common import (
    NOTEBOOKS_BASE,
    NotebookError,
    notebook_dir,
    validate_slug,
)

logger = logging.getLogger(__name__)

#: Manifest ``format_version`` values this CLI knows how to consume. Bump when
#: the m6 producer adds a non-backward-compatible field. m7 synthesis D3.
_RESTORE_SUPPORTED_FORMATS: Final[tuple[int, ...]] = (1,)

#: WAL "database is locked" retry budget (m7 synthesis D4 step 6).
_DB_BUSY_RETRIES: Final[int] = 3
_DB_BUSY_BACKOFF_SECONDS: Final[float] = 0.2

#: Default DB path — sibling of the default notebooks base. The CLI accepts
#: ``--db`` to override (testability + multi-deployment support).
_DEFAULT_DB_PATH: Final[Path] = (
    NOTEBOOKS_BASE.parent / "cache" / "notebooks.db"
)


@dataclass(frozen=True)
class RestoreReport:
    """Structured result a caller (tests, future tooling) can introspect."""

    slug: str
    paper_count: int
    asset_count: int
    forced: bool


# ---------------------------------------------------------------------------
# Safety: the load-bearing pre-pass over every tar member.
# ---------------------------------------------------------------------------


def _safe_member(tarinfo: tarfile.TarInfo, slug: str) -> None:
    """Raise ``NotebookError`` for ANY suspicious member (the m7 D1 Layer 1
    primary gate). Called against EVERY member BEFORE extraction begins.

    Catches every class PEP 706's ``filter="data"`` would also catch — plus a
    manifest-slug-coupling check (member names MUST be either ``manifest.json``
    exactly or live under ``<slug>/``). Defense-in-depth: if a future change
    weakens one layer, the other still holds.
    """
    name = tarinfo.name
    # 1) Absolute paths (POSIX + Windows-style drive letters) — refuse.
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise NotebookError(
            f"bundle member {name!r} is an absolute path (zip-slip class)"
        )
    # 2) Pre-normalization ``..`` segment — refuse before any path math.
    posix = PurePosixPath(name)
    if any(part == ".." for part in posix.parts):
        raise NotebookError(
            f"bundle member {name!r} contains '..' segment (zip-slip class)"
        )
    # 3) Post-normalization: ``os.path.normpath`` collapses redundant components
    #    (e.g. ``foo/./bar`` → ``foo/bar``); the result must still start with
    #    ``<slug>/`` or be exactly ``manifest.json``.
    normalized = os.path.normpath(name).replace(os.sep, "/")
    if normalized.startswith("/") or normalized.startswith(".."):
        raise NotebookError(
            f"bundle member {name!r} normalizes outside the bundle root"
        )
    expected_prefix = f"{slug}/"
    if normalized != "manifest.json" and not normalized.startswith(
        expected_prefix
    ):
        raise NotebookError(
            f"bundle member {name!r} is not under the manifest slug "
            f"{slug!r} (expected {expected_prefix!r} prefix or "
            f"'manifest.json' exact)"
        )
    # 4) Special tar types: symlinks, hardlinks, devices, FIFOs — refuse.
    #    m6 NEVER produces these (REGTYPE only), so a hostile/tampered bundle
    #    is the only source.
    if tarinfo.issym() or tarinfo.islnk():
        raise NotebookError(
            f"bundle member {name!r} is a sym/hardlink (refused; "
            f"zip-slip class)"
        )
    if tarinfo.isdev() or tarinfo.isfifo():
        raise NotebookError(
            f"bundle member {name!r} is a device/FIFO (refused)"
        )


# ---------------------------------------------------------------------------
# Manifest + bundle parsing.
# ---------------------------------------------------------------------------


def _read_manifest(tar: tarfile.TarFile) -> dict:
    """Extract + parse ``manifest.json`` from the open tar.

    Raises ``NotebookError`` if missing or not valid JSON; ``ValueError`` is
    intentionally not used here so the CLI can map all bundle errors uniformly
    to exit code 1.
    """
    try:
        member = tar.getmember("manifest.json")
    except KeyError as exc:
        raise NotebookError(
            "bundle is missing required member 'manifest.json'"
        ) from exc
    extracted = tar.extractfile(member)
    if extracted is None:
        raise NotebookError("bundle 'manifest.json' is not a regular file")
    try:
        return json.loads(extracted.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NotebookError(f"bundle 'manifest.json' is not valid JSON: {exc}") from exc


def _validate_manifest(manifest: dict) -> tuple[str, dict, list[dict]]:
    """Cross-check + extract the slug, notebook row, and papers list. Raises
    ``NotebookError`` on any structural / version / slug failure. Returns
    ``(slug, notebook_dict, papers_list)``."""
    if not isinstance(manifest, dict):
        raise NotebookError("manifest.json is not a JSON object")
    version = manifest.get("format_version")
    if version not in _RESTORE_SUPPORTED_FORMATS:
        raise NotebookError(
            f"manifest format_version {version!r} not in supported "
            f"{_RESTORE_SUPPORTED_FORMATS} (this restore CLI may be older "
            f"than the bundle producer)"
        )
    slug = manifest.get("slug")
    if not isinstance(slug, str):
        raise NotebookError(f"manifest 'slug' is not a string: {slug!r}")
    validate_slug(slug)  # raises NotebookError on regex failure
    notebook = manifest.get("notebook")
    if not isinstance(notebook, dict):
        raise NotebookError("manifest 'notebook' is not a JSON object")
    nb_slug = notebook.get("slug")
    if nb_slug != slug:
        raise NotebookError(
            f"manifest top-level slug {slug!r} != notebook.slug {nb_slug!r}"
        )
    papers = manifest.get("papers", [])
    if not isinstance(papers, list):
        raise NotebookError("manifest 'papers' is not a JSON array")
    for row in papers:
        if not isinstance(row, dict) or "paper_id" not in row or "added_at" not in row:
            raise NotebookError(
                f"manifest 'papers' row malformed: {row!r}"
            )
    return slug, notebook, papers


# ---------------------------------------------------------------------------
# DB layer — direct sqlite3 (the CLI is sync; NotebooksStore is async-only).
# ---------------------------------------------------------------------------


def _open_db_with_retry(db_path: Path) -> sqlite3.Connection:
    """Open the target ``notebooks.db`` with the same PRAGMAs as the runtime
    server, retrying on ``"database is locked"`` (the WAL BUSY case if the
    server is mid-write)."""
    last_err: sqlite3.OperationalError | None = None
    for attempt in range(_DB_BUSY_RETRIES):
        try:
            conn = sqlite3.connect(
                str(db_path),
                isolation_level=None,  # manage BEGIN/COMMIT ourselves
                check_same_thread=False,
            )
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = FULL")
            return conn
        except sqlite3.OperationalError as exc:
            last_err = exc
            if "locked" in str(exc).lower() and attempt < _DB_BUSY_RETRIES - 1:
                time.sleep(_DB_BUSY_BACKOFF_SECONDS)
                continue
            raise
    # Unreachable, but appeases the type checker.
    raise NotebookError(f"could not open {db_path}: {last_err}")  # pragma: no cover


def _restore_db_rows(
    db_path: Path,
    *,
    slug: str,
    notebook: dict,
    papers: list[dict],
    target_lancedb_path: str,
    force: bool,
) -> None:
    """DELETE-if-forced + INSERT the notebook row + bulk INSERT OR IGNORE the
    paper rows in a single transaction. Raises ``NotebookError`` on an existing
    slug without ``--force`` (m7 D2)."""
    with _open_db_with_retry(db_path) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "SELECT 1 FROM notebooks WHERE slug = ?", (slug,)
            )
            exists = cur.fetchone() is not None
            if exists and not force:
                raise NotebookError(
                    f"notebook {slug!r} already exists in DB; pass --force "
                    f"to overwrite (cascades to notebook_papers)"
                )
            if exists:
                conn.execute(
                    "DELETE FROM notebooks WHERE slug = ?", (slug,)
                )
            conn.execute(
                "INSERT INTO notebooks "
                "(slug, display_name, lancedb_path, created_at, "
                " notebook_kind, parse_status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    slug,
                    notebook.get("display_name", ""),
                    target_lancedb_path,
                    notebook.get("created_at", ""),
                    notebook.get("notebook_kind", "arxiv"),
                    notebook.get("parse_status", "skipped") or "skipped",
                ),
            )
            # m7 D4 step 9: INSERT OR IGNORE so a re-run on the same target
            # is idempotent for paper rows (the notebook row is overwritten
            # under --force; the junction rows just no-op on duplicates).
            conn.executemany(
                "INSERT OR IGNORE INTO notebook_papers "
                "(slug, paper_id, added_at) VALUES (?, ?, ?)",
                [(slug, row["paper_id"], row["added_at"]) for row in papers],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------


def restore_bundle(
    bundle_path: Path,
    *,
    notebooks_base: Path,
    db_path: Path,
    force: bool = False,
) -> RestoreReport:
    """Restore one m6 bundle into ``(notebooks_base, db_path)``.

    Raises ``NotebookError`` for any safety or precondition failure. The CLI
    wraps every raise into a stderr line + exit code 1.

    Order (m7 synthesis D4): parse manifest → validate slug + format_version →
    resolve target dir → REFUSE if target dir already exists (always, even
    under --force) → pre-pass every member → DB transaction (DELETE under
    --force + INSERT + INSERT OR IGNORE papers) → ``extractall(filter="data")``
    into ``notebooks_base``.
    """
    if not bundle_path.is_file():
        raise NotebookError(f"bundle file not found: {bundle_path}")
    try:
        # Set up so the with-block can close cleanly even on early failure.
        with tarfile.open(bundle_path, mode="r") as tar:
            manifest = _read_manifest(tar)
            slug, notebook, papers = _validate_manifest(manifest)
            target_dir = notebook_dir(slug, base=notebooks_base)
            # m7 D2: the on-disk dir must NOT exist (regardless of --force).
            if target_dir.exists():
                raise NotebookError(
                    f"target notebook dir {target_dir} already exists; "
                    f"run tools/notebook_purge.py {slug} first (--force "
                    f"governs the DB row, NOT the on-disk dir)"
                )
            # m7 D1 Layer 1: pre-pass every member. ANY violation aborts the
            # whole restore — no partial extraction.
            members = tar.getmembers()
            for tarinfo in members:
                _safe_member(tarinfo, slug)
            # m7 D4 step 8: target lancedb_path is DERIVED from the target
            # base; never reuse the m6-omitted absolute path.
            target_lancedb_path = str(target_dir / "lancedb")
            # DB rows first (transactional; rolls back on any error). m6's
            # extraction is non-transactional so we want the DB to be sane
            # even if extraction fails mid-stream.
            _restore_db_rows(
                db_path,
                slug=slug,
                notebook=notebook,
                papers=papers,
                target_lancedb_path=target_lancedb_path,
                force=force,
            )
            # m7 D1 Layer 2: extract under filter="data". Members are
            # ``<slug>/<rel>`` so extraction into ``notebooks_base`` lands at
            # ``<notebooks_base>/<slug>/<rel>``. The manifest.json member also
            # lands at the root — harmless artifact of the bundle layout.
            notebooks_base.mkdir(parents=True, exist_ok=True)
            tar.extractall(path=notebooks_base, filter="data")
    except tarfile.TarError as exc:
        # Wrong format / corrupted bundle / etc.
        raise NotebookError(f"bundle is not a valid tar: {exc}") from exc

    asset_count = sum(1 for m in members if m.name != "manifest.json")
    return RestoreReport(
        slug=slug, paper_count=len(papers), asset_count=asset_count, forced=force
    )


# ---------------------------------------------------------------------------
# CLI wrapper.
# ---------------------------------------------------------------------------


def run(
    bundle_path: Path,
    *,
    notebooks_base: Path | None = None,
    db_path: Path | None = None,
    force: bool = False,
) -> int:
    """Sync wrapper called by ``main``. Returns exit code."""
    report = restore_bundle(
        bundle_path,
        notebooks_base=notebooks_base or NOTEBOOKS_BASE,
        db_path=db_path or _DEFAULT_DB_PATH,
        force=force,
    )
    print(
        f"restored {report.slug}: "
        f"{report.paper_count} paper(s), {report.asset_count} asset(s)"
        + (" (--force; DB row overwritten)" if report.forced else "")
    )
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "bundle",
        type=Path,
        help="Path to an m6 export bundle (.tar).",
    )
    parser.add_argument(
        "--notebooks-base",
        type=Path,
        default=None,
        help=(
            "Target notebooks base dir (default: var/arxmcp/notebooks/). "
            "Extraction lands at <base>/<slug>/<rel>."
        ),
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help=(
            "Target notebooks.db path (default: var/arxmcp/cache/notebooks.db)."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Allow overwriting an existing DB row (DELETE + INSERT). Does NOT "
            "allow extracting on top of an existing on-disk slug dir — run "
            "tools/notebook_purge.py <slug> first if that exists."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        return run(
            args.bundle,
            notebooks_base=args.notebooks_base,
            db_path=args.db,
            force=args.force,
        )
    except NotebookError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
