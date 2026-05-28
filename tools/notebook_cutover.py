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
served — and a running server holds an open LanceDB handle on the OLD inode, so
**restart the server after a cutover** to pick up the swap.

**The ``PYTHON`` 3.9 trap.** ``make``'s ``PYTHON ?= python3`` resolves to 3.9 on
this workstation (the project needs ≥3.11). If ``make notebook-cutover`` hits a
syntax/typing error, run the module directly under uv::

    uv run python -m tools.notebook_cutover --notebook=<slug>

Atomic-swap contract (per notebook): ``lancedb → lancedb-prev-<UTC-ts>`` then
``lancedb-staging → lancedb`` — two ``os.rename`` calls (POSIX-atomic within a
filesystem). The most recent ``N=2`` ``lancedb-prev-*`` backups are retained;
older ones are pruned (prune failure is non-fatal — the swap already committed).

**BM25 is NOT built here (F1 rectification).** An earlier draft built the BM25
index for the staging version pre-swap, but the BM25 index root
(``var/arxmcp/index/bm25/v<N>/``) is GLOBAL and keyed only on the per-dataset
MVCC ``corpus_version`` — which is NOT globally unique across notebooks + the
shared corpus (collision confirmed live: shared-corpus ``v49`` and
shimura-varieties active are both v49). Building into that namespace from the
cutover participates in a fork-C-startup collision. The fork-A
(``filters.notebook``) retrieval path is dense-only (no BM25); the fork-C
(``ARXMCP_NOTEBOOK``) startup path AUTO-BUILDS the BM25 index for the active
version if missing (E04_S04 H1), so the cutover does not need to. The proper
fix — a per-notebook BM25 root coordinated with fork-C startup
(``server/resources.py``) — is the BM25 analog of m1's ``cache_db_path``
isolation and is tracked as a separate follow-up (see notebook-cutover-m1
critique F1).
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from server.corpus import read_corpus_version
from tools._notebook_common import (
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
    - staging ``corpus_version`` ≤ active version → refuse unless ``force``
      (AC3 downgrade guard). This comparison ASSUMES staging is a re-embed OF
      the same notebook's active dataset, so its MVCC version is monotonically
      greater (F3). A from-scratch rebuild (fresh LanceDB → low version) would
      legitimately need ``--force``.
    - first-ingest case (no active dir): promote staging with NO backup.

    Then perform the two-rename swap with an EXDEV guard +
    rollback-on-step-2-failure, and prune backups to ``N=2`` (prune failure is
    non-fatal — the swap already committed). BM25 is intentionally NOT built
    here — see the module docstring F1 note.
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
    staging_version = staging_info.version

    first_ingest = not active.exists()
    active_version: int | None = None
    if not first_ingest:
        active_info = read_corpus_version(active)
        # A missing/corrupt active marker is treated as version -1 so any
        # healthy staging promotes over it (it is effectively a recovery).
        active_version = active_info.version if active_info is not None else -1
        # F3: the <= comparison is meaningful only because staging is a
        # re-embed of the SAME active (monotonic MVCC version). A corrupt
        # active marker → -1, so any healthy staging (>= 1) promotes (recovery).
        if not force and staging_version <= active_version:
            raise CutoverError(
                f"notebook {slug!r}: staging corpus_version {staging_version} "
                f"<= active {active_version} — promoting would be a downgrade. "
                f"Pass --force to override."
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
    return {"slug": slug, "restored_from": latest.name}


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="notebook_cutover",
        description=(
            "Promote per-notebook lancedb-staging → lancedb (atomic swap + "
            "rollback). Measure BEFORE promoting; restart the server AFTER."
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
        help="override the downgrade guard (staging version <= active)",
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
        except (CutoverError, NotebookError) as exc:
            failures += 1
            print(f"FAIL {slug}: {exc}", file=sys.stderr)

    if not args.rollback and failures < len(slugs):
        print(
            "\nRESTART the arxmcp-server to pick up the swap — it holds an "
            "open LanceDB handle on the old inode and will keep serving the "
            "pre-cutover data until restarted."
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
