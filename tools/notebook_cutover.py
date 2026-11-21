"""Per-notebook staging→active cutover + rollback (notebook-cutover-m1).

``tools/re_embed_all.py`` re-embeds each notebook's active ``lancedb`` into a
sibling ``lancedb-staging`` but never promotes it — the shared-corpus
``make cutover`` (E11_S05) only swaps ``var/arxmcp/index/lancedb``. This tool
is the notebook-scoped equivalent: an atomic directory swap with rollback,
adapted from ``ops/cutover.py::perform_directory_swap``.

**Measure-then-promote workflow.** Cutover is a SEPARATE step (not auto-after
re-embed) precisely so the operator can compare the OLD active against the NEW
staging (e.g. nDCG@5 deltas) before committing — auto-promotion would destroy
that comparison. Run the measurement first, then::

    make notebook-cutover ARGS="--notebook=bridgeland-stability"   # one notebook
    make notebook-cutover                                          # all promotable
    make notebook-cutover ARGS="--rollback --notebook=bridgeland-stability"

**Live-serving impact (notebook-retrieval-m1/m2).** As of fork C
(``ARXMCP_NOTEBOOK``) and fork A (``filters.notebook``), the MCP server reads
the notebook's active ``lancedb`` directly. So this cutover DOES change what is
served. **Stop the server before a cutover and start it after.** A reader
holding an open table across the swap does not keep serving the old data:
measured on Linux with lancedb 0.30.2, its cached
row count and version go stale while ``to_arrow()`` and vector search raise
``Object ... not found``, because the old dataset's files moved with it.
Windows was not measured.

**The ``PYTHON`` 3.9 trap.** ``make``'s ``PYTHON ?= python3`` resolves to 3.9 on
this workstation (the project needs ≥3.11). If ``make notebook-cutover`` hits a
syntax/typing error, run the module directly under uv::

    uv run python -m tools.notebook_cutover --notebook=<slug>

Atomic-swap contract (per notebook): ``lancedb → lancedb-prev-<UTC-ts>`` then
``lancedb-staging → lancedb`` — two ``os.rename`` calls (POSIX-atomic within a
filesystem). The most recent ``N=2`` ``lancedb-prev-*`` backups are retained;
older ones are pruned (prune failure is non-fatal — the swap already committed).

The dataset carries its derived indexes (BM25, theorem names) under
``derived/``, so the two renames move them with the chunks and a rollback
restores the ones built for the restored version.

**Version-keyed caches are invalidated after every swap.** A LanceDB version
integer counts commits within ONE dataset, and a staging table built from
scratch starts counting again, so the version a swap makes active can equal
one an earlier dataset of this notebook was served at. The fork-C Tier-1
retrieval cache (``<notebook>/cache/retrieval.db``, keys salted with the
version) lives outside the dataset and is keyed only by that integer; left in
place it would serve result lists naming chunk ids the new table does not
hold. It is a rebuildable cache, so after the swap commits
:func:`_invalidate_version_keyed_caches` deletes it, along with every
``index/bm25/v<N>`` dir still outside the dataset. A shared
(fork-A) server's Tier-1 cache can hold rows for this notebook too; it is not
in the notebook dir, so the operator deletes it while the server is stopped.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from ingest.corpus import read_corpus_version
from ingest.notebooks import (
    NOTEBOOKS_BASE,
    NotebookError,
    notebook_dir,
    validate_slug,
)

logger = logging.getLogger(__name__)

#: Prefix for timestamped pre-cutover backup directories.
BACKUP_PREFIX = "lancedb-prev-"
#: How many ``lancedb-prev-*`` backups to retain per notebook (AC6).
BACKUP_RETENTION = 2
#: Subdirectory names within a notebook dir.
ACTIVE_NAME = "lancedb"
STAGING_NAME = "lancedb-staging"


class CutoverError(RuntimeError):
    """A cutover/rollback refused or failed. Carries an actionable message;
    the CLI maps it to a non-zero exit per the affected notebook (AC5)."""


def _utc_ts_filename() -> str:
    """UTC timestamp safe for a directory name; microsecond resolution so
    two cutovers in the same second cannot collide on the backup name."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")


def _list_backups(nb: Path) -> list[Path]:
    """All ``lancedb-prev-*`` dirs in a notebook, oldest first (the
    timestamp name sorts chronologically)."""
    return sorted(
        (p for p in nb.iterdir() if p.is_dir() and p.name.startswith(BACKUP_PREFIX)),
        key=lambda p: p.name,
    )


def _assert_same_filesystem(*paths: Path) -> None:
    """Refuse a cross-filesystem swap (``os.rename`` raises ``EXDEV`` across
    mounts; the atomic contract requires one filesystem). For a path that does
    not exist yet (the backup target) we stat its parent. Mirrors
    ``ops/cutover.py`` adversary-F8 guard."""
    devs = {
        os.stat(p if p.exists() else p.parent).st_dev for p in paths
    }
    if len(devs) > 1:
        raise CutoverError(
            f"cross-filesystem swap refused: paths span st_dev={sorted(devs)}. "
            f"The atomic rename contract requires active, staging, and the "
            f"backup parent on the SAME filesystem. Move them to a common "
            f"mount before retrying."
        )


def discover_promotable(base: Path | None = None) -> list[str]:
    """Slugs of every notebook with a promotable ``lancedb-staging`` dir.

    Used by the ``--all-notebooks`` default. Sorted for deterministic order.

    F8: require a ``corpus-version.json`` marker inside ``lancedb-staging`` —
    a half-initialized staging dir (dir present, no marker) is NOT promotable
    and would otherwise be discovered, then refused at ``perform_cutover``,
    turning an ``--all-notebooks`` run non-zero. Skipping it here keeps the
    sweep clean.
    """
    base = base if base is not None else NOTEBOOKS_BASE
    if not base.is_dir():
        return []
    out: list[str] = []
    for child in sorted(base.iterdir()):
        staging = child / STAGING_NAME
        if (
            child.is_dir()
            and staging.is_dir()
            and (staging / "corpus-version.json").is_file()
        ):
            out.append(child.name)
    return out


def _prune_backups(nb: Path, retention: int = BACKUP_RETENTION) -> list[str]:
    """Keep the most-recent ``retention`` backups; rmtree the rest (AC6).
    Returns the names pruned. Raises ``OSError`` on rmtree failure — the
    caller (:func:`perform_cutover`) catches it post-swap and treats it as
    non-fatal (FM-3): a prune failure must NOT fail an already-committed
    promotion."""
    backups = _list_backups(nb)
    pruned: list[str] = []
    while len(backups) > retention:
        victim = backups.pop(0)  # oldest first
        shutil.rmtree(victim)
        pruned.append(victim.name)
    return pruned


#: Files of a SQLite database in WAL mode (``server/cache_sqlite.py``).
_SQLITE_SUFFIXES = ("", "-wal", "-shm", "-journal")


def _invalidate_version_keyed_caches(nb: Path) -> list[str]:
    """Delete the notebook's caches keyed by a bare version integer.

    Runs after a swap has committed. Deletes ``cache/retrieval.db`` (and its
    WAL siblings) whole, because every row in it belongs to this notebook and
    a key salted with a reused version integer is indistinguishable from a
    live one. Deletes every ``index/bm25/v<N>`` entry too, not only the one
    for the version just made active: none was built from the newly active
    dataset (a cutover never builds BM25), and any of them can alias a version
    that dataset reaches on later writes. A symlinked ``v<N>`` entry is
    unlinked, never followed; a symlinked ``index/bm25`` root is refused,
    because clearing it would delete outside the notebook.

    Returns the removed paths relative to ``nb``, with ``/`` separators on
    every platform. Raises ``OSError`` on a delete failure or a symlinked
    root; the caller reports it, since a swap that left a stale cache needs
    an operator.
    """
    removed: list[str] = []
    cache_db = nb / "cache" / "retrieval.db"
    for suffix in _SQLITE_SUFFIXES:
        path = cache_db.with_name(cache_db.name + suffix)
        if path.is_file():
            path.unlink()
            removed.append(path.relative_to(nb).as_posix())
    bm25_root = nb / "index" / "bm25"
    if bm25_root.is_symlink():
        raise OSError(f"{bm25_root} is a symlink; not following it")
    if bm25_root.is_dir():
        for entry in sorted(bm25_root.iterdir()):
            name = entry.name
            if not (name.startswith("v") and name[1:].isdigit()):
                continue
            if entry.is_symlink() or not entry.is_dir():
                entry.unlink()
            else:
                shutil.rmtree(entry)
            removed.append(entry.relative_to(nb).as_posix())
    return removed


def perform_cutover(
    slug: str, *, base: Path | None = None, force: bool = False
) -> dict:
    """Promote ``<slug>/lancedb-staging`` to ``<slug>/lancedb`` atomically.

    Pre-swap gates (refuse + raise, NO mutation):
    - Threat-1: ``validate_slug`` + ``notebook_dir`` (regex + symlink +
      containment) before any path use.
    - staging dir missing → refuse (AC4).
    - staging has no ``corpus-version.json`` → refuse (AC4, incomplete
      re-embed).
    - if a re-embed progress sentinel exists, it must report ``complete``
      with zero failed papers.
    - staging ``corpus_version`` ≤ active version → refuse unless ``force``
      (the downgrade guard). Version integers count commits within one
      dataset, and ``ingest.re_embed`` builds staging as a NEW dataset, so its
      version restarts and is usually LOWER than a long-lived active's: the
      guard does not detect a downgrade, it flags a comparison between two
      counters. A re-embed or id rotation into a fresh staging (the supported
      path) therefore needs ``--force``; check first that the staged
      ``re-embed-progress.json`` reports ``complete`` with
      ``papers_failed_count: 0`` and that each paper's staged row count equals
      the active one.
    - first-ingest case (no active dir): promote staging with NO backup.

    Then perform the two-rename swap with an EXDEV guard +
    rollback-on-step-2-failure, invalidate every cache keyed by a bare
    version integer (:func:`_invalidate_version_keyed_caches`), and prune backups to
    ``N=2`` (prune failure is non-fatal — the swap already committed).
    """
    validate_slug(slug)  # Threat-1 boundary, before any path construction.
    nb = notebook_dir(slug, base=base)
    active = nb / ACTIVE_NAME
    staging = nb / STAGING_NAME

    if not staging.is_dir():
        raise CutoverError(
            f"notebook {slug!r}: no {STAGING_NAME} to promote at {staging}"
        )
    staging_info = read_corpus_version(staging)
    if staging_info is None:
        raise CutoverError(
            f"notebook {slug!r}: {STAGING_NAME} has no corpus-version.json "
            f"(incomplete re-embed); refusing to promote"
        )
    progress = staging / "re-embed-progress.json"
    if progress.is_file():
        try:
            progress_data = json.loads(progress.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CutoverError(f"notebook {slug!r}: invalid re-embed progress sentinel") from exc
        if (progress_data.get("status") != "complete"
                or progress_data.get("papers_failed_count") != 0):
            raise CutoverError(
                f"notebook {slug!r}: staged re-embed is not complete without failures"
            )
    staging_version = staging_info.version

    first_ingest = not active.exists()
    active_version: int | None = None
    if not first_ingest:
        active_info = read_corpus_version(active)
        # A missing/corrupt active marker is treated as version -1 so any
        # healthy staging promotes over it (it is effectively a recovery).
        active_version = active_info.version if active_info is not None else -1
        # The two integers count commits in two DIFFERENT datasets, so
        # "<=" is a prompt to check, not proof of a downgrade (see the
        # docstring). A corrupt active marker → -1, so any healthy staging
        # (>= 1) promotes (recovery).
        if not force and staging_version <= active_version:
            raise CutoverError(
                f"notebook {slug!r}: staging corpus_version {staging_version} "
                f"<= active {active_version}. A staging table built from "
                f"scratch (a re-embed or id rotation) restarts its version "
                f"count, so this is expected there; otherwise it may be a "
                f"downgrade. Check the staged run, then pass --force to "
                f"promote it."
            )

    backup_name: str | None = None
    if first_ingest:
        # No active to back up — straight promotion.
        os.rename(staging, active)
    else:
        backup = nb / f"{BACKUP_PREFIX}{_utc_ts_filename()}"
        # F6: refuse if the backup target already exists (mirrors
        # ops/cutover.py:523) — guards the astronomically-unlikely
        # same-microsecond-timestamp collision rather than renaming the new
        # active INTO an existing backup dir.
        if backup.exists():
            raise CutoverError(
                f"notebook {slug!r}: backup target {backup.name} already "
                f"exists; refusing to overwrite. Retry (the timestamp will "
                f"differ) or inspect the directory."
            )
        _assert_same_filesystem(active, staging, backup)
        os.rename(active, backup)  # step 1
        try:
            os.rename(staging, active)  # step 2
        except OSError as exc:
            os.rename(backup, active)  # restore step 1
            raise CutoverError(
                f"notebook {slug!r}: swap failed at step 2 ({exc}); restored "
                f"the original active path"
            ) from exc
        backup_name = backup.name

    # The swap has COMMITTED. Drop the caches keyed by a bare
    # version integer; a stale one would serve another dataset's chunk ids
    # (Tier-1) or block startup (BM25). A failure here is NOT swallowed: the
    # promotion stands, but the operator must clear the named paths before
    # starting the server.
    try:
        invalidated = _invalidate_version_keyed_caches(nb)
    except OSError as exc:
        raise CutoverError(
            f"notebook {slug!r}: promoted v{staging_version}, but could not "
            f"delete its version-keyed caches ({exc}). Delete "
            f"{nb / 'cache' / 'retrieval.db'}* and every "
            f"{nb / 'index' / 'bm25'}/v<N> before starting the server."
        ) from exc

    # F2 (FM-3): the swap has COMMITTED. Pruning old backups is best-effort —
    # a disk-full / permission OSError here must NOT turn a successful
    # promotion into a non-zero exit. Swallow + WARN.
    pruned: list[str] = []
    if not first_ingest:
        try:
            pruned = _prune_backups(nb)
        except OSError as exc:
            logger.warning(
                "notebook %s: backup prune failed post-swap (non-fatal, the "
                "promotion succeeded): %s", slug, exc,
            )
    return {
        "slug": slug,
        "promoted_version": staging_version,
        "previous_version": active_version,
        "backup": backup_name,
        "pruned_backups": pruned,
        "first_ingest": first_ingest,
        "invalidated_caches": invalidated,
    }


def perform_rollback(slug: str, *, base: Path | None = None) -> dict:
    """Inverse swap (AC2): restore the most-recent ``lancedb-prev-*`` backup to
    ``lancedb`` and demote the current ``lancedb`` back to ``lancedb-staging``.
    Round-trip is lossless. Refuses if no backup exists or if a
    ``lancedb-staging`` is already present (would clobber it).

    **Single-level only (F5).** Rollback restores ONLY the most recent backup.
    Older ``lancedb-prev-*`` dirs (kept up to N=2) remain on disk as cold
    snapshots and are NOT touched — a second consecutive rollback refuses
    (``lancedb-staging`` now exists). To undo more than one cutover, promote a
    cold snapshot manually."""
    validate_slug(slug)
    nb = notebook_dir(slug, base=base)
    active = nb / ACTIVE_NAME
    staging = nb / STAGING_NAME

    backups = _list_backups(nb)
    if not backups:
        raise CutoverError(
            f"notebook {slug!r}: no {BACKUP_PREFIX}* backup to roll back to"
        )
    latest = backups[-1]  # most recent
    if not active.exists():
        raise CutoverError(
            f"notebook {slug!r}: active {ACTIVE_NAME} missing — inconsistent "
            f"state (cutover crashed mid-swap?)"
        )
    if staging.exists():
        raise CutoverError(
            f"notebook {slug!r}: {STAGING_NAME} already exists; refusing to "
            f"clobber it on rollback (promote or remove it first)"
        )
    _assert_same_filesystem(active, latest, staging)
    os.rename(active, staging)  # demote promoted content
    try:
        os.rename(latest, active)  # restore former active
    except OSError as exc:
        os.rename(staging, active)  # restore
        raise CutoverError(
            f"notebook {slug!r}: rollback failed at step 2 ({exc}); restored"
        ) from exc
    # A rollback is a swap too. While the demoted dataset
    # was active, its caches were written under ITS versions, which can equal
    # the restored dataset's after a forced cutover.
    try:
        invalidated = _invalidate_version_keyed_caches(nb)
    except OSError as exc:
        raise CutoverError(
            f"notebook {slug!r}: rolled back to {latest.name}, but could not "
            f"delete its version-keyed caches ({exc}); delete "
            f"{nb / 'cache' / 'retrieval.db'}* and every "
            f"{nb / 'index' / 'bm25'}/v<N> before starting the server."
        ) from exc
    return {
        "slug": slug,
        "restored_from": latest.name,
        "invalidated_caches": invalidated,
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="notebook_cutover",
        description=(
            "Promote per-notebook lancedb-staging → lancedb (atomic swap + "
            "rollback). Measure BEFORE promoting; stop the server BEFORE and "
            "start it AFTER."
        ),
    )
    p.add_argument(
        "--notebook", metavar="SLUG",
        help="cut over a single notebook by slug (default: all promotable)",
    )
    p.add_argument(
        "--all-notebooks", action="store_true",
        help="cut over every notebook with a staging dir (the default when "
             "--notebook is omitted)",
    )
    p.add_argument(
        "--rollback", action="store_true",
        help="inverse swap: restore the most recent lancedb-prev-* backup",
    )
    p.add_argument(
        "--force", action="store_true",
        help="promote even though staging version <= active (expected for a "
             "staging re-embedded from scratch, e.g. a chunk-id rotation)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _build_arg_parser().parse_args(argv)

    if args.notebook:
        slugs = [args.notebook]
    else:
        # --all-notebooks is the default behavior when no single slug is given.
        slugs = discover_promotable()
        if not slugs:
            print("no promotable notebooks (no */lancedb-staging found)")
            return 0

    failures = 0
    for slug in slugs:
        try:
            if args.rollback:
                res = perform_rollback(slug)
                print(
                    f"OK   {slug}: rolled back — restored {res['restored_from']}"
                )
            else:
                res = perform_cutover(slug, force=args.force)
                if res["first_ingest"]:
                    print(
                        f"OK   {slug}: first-ingest promotion → v"
                        f"{res['promoted_version']} (no backup)"
                    )
                else:
                    pr = (
                        f"; pruned {len(res['pruned_backups'])}"
                        if res["pruned_backups"] else ""
                    )
                    print(
                        f"OK   {slug}: v{res['previous_version']} → "
                        f"v{res['promoted_version']} (backup "
                        f"{res['backup']}{pr})"
                    )
            if res.get("invalidated_caches"):
                print(
                    f"     {slug}: deleted version-keyed caches: "
                    f"{', '.join(res['invalidated_caches'])}"
                )
        except (CutoverError, NotebookError) as exc:
            failures += 1
            print(f"FAIL {slug}: {exc}", file=sys.stderr)

    if failures < len(slugs):
        print(
            "\nSTART the arxmcp-server now (it should have been stopped "
            "before the swap). A server left running across it does not "
            "serve the old data: its open table's reads fail, because the "
            "old dataset's files moved."
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
