"""Prune old versions of a LanceDB ``chunks`` table, keeping what readers pin.

Every commit to the table (a paper written, an index build, a delete)
leaves a dataset version, and LanceDB keeps each version's data and index
files until something cleans them up. Nothing in the write path does, so
superseded rows and superseded HNSW indexes stay on disk indefinitely.
This is the operator-run cleanup::

    python -m arxmcp.ops.prune_versions --lancedb-path <dataset> [--keep-days N] [--dry-run]

**What it keeps.**

- The version ``corpus-version.json`` pins. Readers open that one.
- The version before it: :func:`arxmcp.corpus.reader.open_chunks_table_with_fallback`
  reopens it when the pinned version fails to open.
- Every later version, and every version younger than ``--keep-days``
  (default 7, LanceDB's own default), which covers a reader still pinned
  to an older marker. LanceDB always keeps the latest version.

It refuses a dataset with no marker, or one whose marker names a version
the dataset does not hold: then nothing says what readers pin.

**Side effects.** LanceDB 0.30 exposes cleanup only through
``Table.optimize``, which also compacts small data files and folds
unindexed rows into the indexes. Both commit versions after the pinned
one. The marker is not moved, so readers keep serving the pinned
version, and the compacted copy sits beside the pinned files until the
next write moves the marker and a later prune drops the old ones. A run
with nothing to remove does not call ``optimize``.

**When to run it.** It commits to the dataset, so it takes the dataset
write lock (:mod:`arxmcp.corpus.write_lock`) and is refused beside an ingest,
re-embed or delta harvest on the same dataset. A cutover does not take
the lock: never prune during one. A server started before the last write and
not restarted is pinned to an older version, which survives only while
it is younger than ``--keep-days``; restart servers before pruning with
a short window.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from arxmcp.corpus import exits_when_write_locked, holds_dataset_write_lock

#: Versions younger than this are kept whatever they are.
DEFAULT_KEEP_DAYS = 7.0

#: Slack on the cutoff that protects the pinned version's predecessor.
#: LanceDB computes its cutoff from its own clock, read after this module
#: reads its; the slack covers that gap. Widening it only keeps more.
_CUTOFF_SLACK = timedelta(minutes=10)

#: A cleanup age no version reaches, for an ``optimize`` that must only
#: compact.
_REMOVE_NOTHING = timedelta(days=36500)


class PruneRefused(RuntimeError):
    """The dataset gives no safe answer to what readers pin."""


@dataclass(frozen=True, slots=True)
class PrunePlan:
    """What a prune keeps and removes, as computed before it runs."""

    pinned_version: int
    oldest_kept_pin: int
    older_than: timedelta
    removable: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PruneResult:
    plan: PrunePlan
    removed: tuple[int, ...]
    remaining: tuple[int, ...]


def _open(lancedb_path: Path):
    import lancedb

    from arxmcp.corpus import CHUNKS_TABLE_NAME

    if not (lancedb_path / f"{CHUNKS_TABLE_NAME}.lance").is_dir():
        raise PruneRefused(f"no chunks table at {lancedb_path}")
    return lancedb.connect(str(lancedb_path)).open_table(CHUNKS_TABLE_NAME)


def _version_times(tbl) -> dict[int, datetime]:
    # LanceDB hands back naive local times built without the DST fold flag,
    # so a time in the repeated hour reads as its earlier occurrence. That
    # overstates the age of such a version, which only keeps more.
    return {
        int(v["version"]): v["timestamp"].astimezone(UTC)
        for v in tbl.list_versions()
    }


def plan_prune(
    lancedb_path: str | Path,
    *,
    keep_days: float = DEFAULT_KEEP_DAYS,
    now: datetime | None = None,
) -> PrunePlan:
    """Work out which versions a prune of ``lancedb_path`` would remove."""
    from arxmcp.corpus import read_corpus_version

    if keep_days < 0:
        raise ValueError(f"keep_days must be >= 0; got {keep_days}")
    path = Path(lancedb_path)
    tbl = _open(path)
    times = _version_times(tbl)
    try:
        marker = read_corpus_version(path)
    except ValueError as exc:
        raise PruneRefused(f"corpus-version.json at {path} is malformed: {exc}") from exc
    if marker is None:
        raise PruneRefused(
            f"no corpus-version.json at {path}: nothing names the version "
            "readers pin"
        )
    if marker.version not in times:
        raise PruneRefused(
            f"corpus-version.json names version {marker.version}, which "
            f"{path} does not hold; repair the marker with `make reconcile` "
            "first"
        )
    oldest_kept_pin = (
        marker.version - 1 if marker.version - 1 in times else marker.version
    )
    now = now or datetime.now(UTC)
    older_than = max(
        timedelta(days=keep_days),
        now - times[oldest_kept_pin] + _CUTOFF_SLACK,
    )
    cutoff = now - older_than
    latest = max(times)
    removable = tuple(
        sorted(v for v, t in times.items() if t < cutoff and v != latest)
    )
    return PrunePlan(
        pinned_version=marker.version,
        oldest_kept_pin=oldest_kept_pin,
        older_than=older_than,
        removable=removable,
    )


@holds_dataset_write_lock("lancedb_path")
def prune_versions(
    lancedb_path: str | Path,
    *,
    keep_days: float = DEFAULT_KEEP_DAYS,
) -> PruneResult:
    """Remove the versions :func:`plan_prune` names, and their files."""
    path = Path(lancedb_path)
    plan = plan_prune(path, keep_days=keep_days)
    tbl = _open(path)
    before = set(_version_times(tbl))
    if plan.removable:
        # ``optimize`` compacts before it cleans up and reads its clock only
        # then, so on a large table the cutoff would drift by the length of
        # the compaction. Compact first, removing nothing, then plan the
        # cutoff and clean up while the second compaction finds no work.
        # Unverified files (a write still in flight) keep LanceDB's own
        # seven-day rule throughout.
        tbl.optimize(cleanup_older_than=_REMOVE_NOTHING)
        plan = plan_prune(path, keep_days=keep_days)
        tbl.optimize(cleanup_older_than=plan.older_than)
    remaining = set(_version_times(_open(path)))
    if not {plan.pinned_version, plan.oldest_kept_pin} <= remaining:
        raise RuntimeError(
            f"prune of {path} removed a pinned version: kept "
            f"{sorted(remaining)}, needed {plan.oldest_kept_pin} and "
            f"{plan.pinned_version}"
        )
    return PruneResult(
        plan=plan,
        removed=tuple(sorted(before - remaining)),
        remaining=tuple(sorted(remaining)),
    )


@exits_when_write_locked
def _cli(argv: list[str]) -> int:
    from arxmcp.corpus import DEFAULT_LANCEDB_PATH

    parser = argparse.ArgumentParser(
        prog="python -m arxmcp.ops.prune_versions",
        description=(
            "Remove old versions of a chunks table, keeping the version "
            "corpus-version.json pins and the one before it. Commits to "
            "the dataset: never run it beside another writer."
        ),
    )
    parser.add_argument(
        "--lancedb-path", type=Path, default=DEFAULT_LANCEDB_PATH,
        help=f"dataset directory (default: {DEFAULT_LANCEDB_PATH})",
    )
    parser.add_argument(
        "--keep-days", type=float, default=DEFAULT_KEEP_DAYS,
        help=f"also keep versions younger than this (default: {DEFAULT_KEEP_DAYS:g})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="print what would be removed and change nothing",
    )
    args = parser.parse_args(argv)
    try:
        if args.dry_run:
            plan = plan_prune(args.lancedb_path, keep_days=args.keep_days)
            print(
                f"pinned v{plan.pinned_version}; keeping v{plan.oldest_kept_pin} "
                f"onward; would remove {len(plan.removable)} version(s): "
                f"{list(plan.removable)}"
            )
            return 0
        result = prune_versions(args.lancedb_path, keep_days=args.keep_days)
    except PruneRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(
        f"pinned v{result.plan.pinned_version}; removed "
        f"{len(result.removed)} version(s); {len(result.remaining)} remain "
        f"(v{result.remaining[0]}..v{result.remaining[-1]})"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_cli(sys.argv[1:]))


__all__ = [
    "DEFAULT_KEEP_DAYS",
    "PrunePlan",
    "PruneRefused",
    "PruneResult",
    "plan_prune",
    "prune_versions",
]
