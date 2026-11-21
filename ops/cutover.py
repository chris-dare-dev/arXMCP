"""200K cutover activation script (E11_S05).

Activates a staging LanceDB corpus version as the new active
dataset via an atomic directory swap. Closes the H9 design
finding ("scale cutover trigger explicit and measurable") that
threads back through every E11 milestone.

The activation is gated on FOUR criteria, ALL must pass:

1. **E07_S04 seed eval** — the active corpus has previously
   passed nDCG@5 ≥ 0.80 (Tier-1 exit gate). Read the
   `aggregate-<active_version>.json` produced by
   `tests/eval/test_retrieval_quality.score_and_write`.
2. **E11_S04 watchdog on staging** — the most-recent watchdog
   report at the staging corpus version reports nDCG@5 ≥ 0.80
   AND no `eval-quarantine.flag` is present.
3. **E11_S01/S03 ingest complete** — `re-embed-state.json` (if
   it exists) reports `status="complete"` or
   `"complete_with_failures"`; the staging LanceDB at the
   pinned version opens cleanly, has > 0 rows, and every ANN
   vector column that holds vectors has an index covering every
   row (:func:`verify_lancedb_integrity`).
4. **Restore drill passed** — `restore-drill-passed.flag`
   exists, written by `ops/restore_drill.sh` after a successful
   restic restore + smoke check.

Activation = atomic directory swap (NOT marker rewrite):

* `os.rename(active_path, rollback_path)` — saves the old
  active dataset for rollback (microsecond, POSIX-atomic on
  same FS).
* `os.rename(staging_path, active_path)` — promotes staging.

The staging `corpus-version.json` already carries the correct
version integer for the now-active dataset. **No marker
rewrite needed.**

**Rollback** (`--rollback` flag): inverse swap — atomic-rename
`active_path` → `lancedb-failed-cutover-<ts>/`, then
`rollback_path` → `active_path`. Two renames + restart server
under 30s.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ingest.bulk_ingest import DEFAULT_LANCEDB_STAGING_PATH
from ingest.store import (
    CORPUS_VERSION_MARKER_NAME,
    DEFAULT_LANCEDB_PATH,
)

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Default rollback snapshot path. The old active LanceDB is
#: moved here during cutover; rollback moves it back.
DEFAULT_ROLLBACK_PATH: Path = (
    REPO_ROOT / "var" / "arxmcp" / "index" / "lancedb-prev"
)

#: Default aggregate eval-report directory (E05 / E07_S04).
DEFAULT_AGGREGATE_EVAL_DIR: Path = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "eval"
)

#: Default watchdog report directory (E11_S04).
DEFAULT_WATCHDOG_REPORT_DIR: Path = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "eval-reports"
)

#: Default watchdog quarantine flag (E11_S04).
DEFAULT_QUARANTINE_FLAG_PATH: Path = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "eval-quarantine.flag"
)

#: Default re-embed state file (E11_S03).
DEFAULT_RE_EMBED_STATE_PATH: Path = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "re-embed-state.json"
)

#: Default restore-drill passed sentinel.
DEFAULT_RESTORE_DRILL_FLAG_PATH: Path = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "restore-drill-passed.flag"
)

#: Default /readyz URL.
DEFAULT_READYZ_URL: str = "http://127.0.0.1:7733/readyz"
DEFAULT_STATUS_URL: str = "http://127.0.0.1:7733/status"

#: AC4: /readyz must return 200 within 60 seconds.
DEFAULT_READYZ_TIMEOUT_SECONDS: float = 60.0

#: Minimum nDCG@5 for both seed (C1) and post-staging (C2).
NDCG5_MIN: float = 0.80


# ---------------------------------------------------------------------------
# Errors + result types
# ---------------------------------------------------------------------------


class CutoverError(RuntimeError):
    """Raised when the cutover is refused or fails."""


@dataclass(frozen=True)
class CriterionResult:
    """One activation criterion's check result."""

    name: str
    ok: bool
    reason: str


def _utc_iso() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_ts_filename() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%S")


# ---------------------------------------------------------------------------
# Criterion 3 — E11_S01/S03 ingest complete
# ---------------------------------------------------------------------------


def check_criterion_3_re_embed_state(
    state_path: Path = DEFAULT_RE_EMBED_STATE_PATH,
) -> CriterionResult:
    """Verify E11_S03 re-embed (if any) is complete.

    Absent state file is acceptable — a bulk ingest (E11_S01)
    that never went through re-embed leaves no state file. Only
    a present-but-not-complete status blocks cutover.
    """
    name = "C3: re-embed state complete"
    if not state_path.is_file():
        return CriterionResult(
            name=name,
            ok=True,
            reason=f"no {state_path.name} present (bulk-ingest path)",
        )
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return CriterionResult(
            name=name,
            ok=False,
            reason=f"malformed {state_path}: {exc}",
        )
    status = state.get("status")
    if status not in ("complete", "complete_with_failures"):
        return CriterionResult(
            name=name,
            ok=False,
            reason=(
                f"re-embed status={status!r} is not complete; "
                f"see {state_path}"
            ),
        )
    return CriterionResult(
        name=name, ok=True, reason=f"status={status!r}"
    )


# ---------------------------------------------------------------------------
# Criterion 4 — restore drill passed
# ---------------------------------------------------------------------------


#: The drill runs quarterly, with a reminder in the week before each
#: quarter mark. A pass older than one quarter plus that week no longer
#: says anything about whether today's backups restore.
RESTORE_DRILL_MAX_AGE_DAYS: int = 100


def check_criterion_4_restore_drill(
    flag_path: Path = DEFAULT_RESTORE_DRILL_FLAG_PATH,
    *,
    now=None,  # noqa: ANN001
    max_age_days: int = RESTORE_DRILL_MAX_AGE_DAYS,
) -> CriterionResult:
    """Verify a restore drill passed within the last quarter."""
    name = "C4: restore drill passed"
    if not flag_path.is_file():
        return CriterionResult(
            name=name,
            ok=False,
            reason=(
                f"missing {flag_path}; run ops/restore_drill.sh first"
            ),
        )
    try:
        payload = json.loads(flag_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return CriterionResult(
            name=name,
            ok=False,
            reason=f"malformed {flag_path}: {exc}",
        )
    smoke = payload.get("smoke_check")
    if smoke != "passed":
        return CriterionResult(
            name=name,
            ok=False,
            reason=f"smoke_check={smoke!r} (expected 'passed')",
        )
    restored_at = payload.get("restored_at")
    try:
        when = _dt.datetime.strptime(
            str(restored_at), "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=_dt.UTC)
    except ValueError:
        return CriterionResult(
            name=name,
            ok=False,
            reason=(
                f"restored_at={restored_at!r} in {flag_path} is not a UTC "
                f"timestamp; rerun ops/restore_drill.sh"
            ),
        )
    current = now if now is not None else _dt.datetime.now(_dt.UTC)
    age_days = (current - when).total_seconds() / 86400.0
    if age_days > max_age_days:
        return CriterionResult(
            name=name,
            ok=False,
            reason=(
                f"last drill passed {age_days:.0f} days ago "
                f"(restored_at={restored_at}); the limit is "
                f"{max_age_days} days. Rerun ops/restore_drill.sh"
            ),
        )
    return CriterionResult(
        name=name,
        ok=True,
        reason=(
            f"snapshot_id={payload.get('snapshot_id', '?')}, "
            f"{age_days:.0f} days ago"
        ),
    )


# ---------------------------------------------------------------------------
# Criterion 1 — seed eval aggregate ndcg5_mean >= 0.80
# ---------------------------------------------------------------------------


def check_criterion_1_seed_eval(
    *,
    active_marker_path: Path,
    aggregate_dir: Path = DEFAULT_AGGREGATE_EVAL_DIR,
    ndcg5_min: float = NDCG5_MIN,
) -> CriterionResult:
    """Verify the active (seed) corpus has previously passed
    nDCG@5 ≥ 0.80 (Tier-1 exit gate).

    Reads the active corpus-version.json to discover the seed
    version integer, then loads
    ``<aggregate_dir>/aggregate-<N>.json`` (produced by
    ``tests/eval/test_retrieval_quality.score_and_write``).
    """
    name = "C1: seed eval ndcg5_mean >= 0.80"
    if not active_marker_path.is_file():
        return CriterionResult(
            name=name,
            ok=False,
            reason=(
                f"active marker missing at {active_marker_path}; "
                f"cannot determine seed version"
            ),
        )
    try:
        marker = json.loads(
            active_marker_path.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as exc:
        return CriterionResult(
            name=name,
            ok=False,
            reason=f"malformed active marker: {exc}",
        )
    seed_version = marker.get("version")
    if not isinstance(seed_version, int):
        return CriterionResult(
            name=name,
            ok=False,
            reason="active marker missing integer 'version'",
        )
    aggregate_path = aggregate_dir / f"aggregate-{seed_version}.json"
    if not aggregate_path.is_file():
        return CriterionResult(
            name=name,
            ok=False,
            reason=(
                f"no aggregate-{seed_version}.json at {aggregate_dir}; "
                f"run `make eval` against the seed first"
            ),
        )
    try:
        agg = json.loads(aggregate_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return CriterionResult(
            name=name,
            ok=False,
            reason=f"malformed {aggregate_path}: {exc}",
        )
    ndcg = agg.get("ndcg5_mean")
    if not isinstance(ndcg, (int, float)):
        return CriterionResult(
            name=name,
            ok=False,
            reason="aggregate missing numeric ndcg5_mean",
        )
    if ndcg < ndcg5_min:
        return CriterionResult(
            name=name,
            ok=False,
            reason=(
                f"seed ndcg5_mean={ndcg:.4f} < {ndcg5_min} "
                f"(see {aggregate_path})"
            ),
        )
    return CriterionResult(
        name=name,
        ok=True,
        reason=(
            f"seed_version={seed_version} ndcg5_mean={ndcg:.4f}"
        ),
    )


# ---------------------------------------------------------------------------
# Criterion 2 — watchdog on staging passes
# ---------------------------------------------------------------------------


def _find_watchdog_report_for_version(
    report_dir: Path, target_version: int
) -> Path | None:
    """Find the most-recent watchdog report at ``target_version``."""
    if not report_dir.is_dir():
        return None
    candidates: list[tuple[float, Path]] = []
    prefix = f"corpus_v{target_version}-"
    for entry in report_dir.iterdir():
        if not entry.is_file():
            continue
        if entry.name.startswith(prefix) and entry.suffix == ".json":
            candidates.append((entry.stat().st_mtime, entry))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][1]


def check_criterion_2_watchdog(
    *,
    staging_marker_path: Path,
    report_dir: Path = DEFAULT_WATCHDOG_REPORT_DIR,
    quarantine_flag_path: Path = DEFAULT_QUARANTINE_FLAG_PATH,
    ndcg5_min: float = NDCG5_MIN,
) -> CriterionResult:
    """Verify the E11_S04 watchdog passed on the staging corpus.

    Two sub-checks:
    1. No `eval-quarantine.flag` present (the watchdog's
       refuse-to-promote signal).
    2. The most-recent watchdog report at the staging version
       reports `ndcg5_mean >= 0.80` AND `alert_triggered=False`.
    """
    name = "C2: watchdog on staging passes"
    if quarantine_flag_path.is_file():
        return CriterionResult(
            name=name,
            ok=False,
            reason=(
                f"quarantine flag present at {quarantine_flag_path}; "
                f"investigate + run `make watchdog "
                f"ARGS=--clear-quarantine` first"
            ),
        )
    if not staging_marker_path.is_file():
        return CriterionResult(
            name=name,
            ok=False,
            reason=(
                f"staging marker missing at {staging_marker_path}; "
                f"cannot determine staging version"
            ),
        )
    try:
        staging_marker = json.loads(
            staging_marker_path.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as exc:
        return CriterionResult(
            name=name,
            ok=False,
            reason=f"malformed staging marker: {exc}",
        )
    staging_version = staging_marker.get("version")
    if not isinstance(staging_version, int):
        return CriterionResult(
            name=name,
            ok=False,
            reason="staging marker missing integer 'version'",
        )
    report_path = _find_watchdog_report_for_version(
        report_dir, staging_version
    )
    if report_path is None:
        return CriterionResult(
            name=name,
            ok=False,
            reason=(
                f"no watchdog report for corpus_v{staging_version} "
                f"at {report_dir}; run `make watchdog` against staging "
                f"first"
            ),
        )
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return CriterionResult(
            name=name,
            ok=False,
            reason=f"malformed watchdog report: {exc}",
        )
    if report.get("alert_triggered"):
        return CriterionResult(
            name=name,
            ok=False,
            reason=(
                f"watchdog reported alert_triggered=true in "
                f"{report_path}"
            ),
        )
    ndcg = report.get("ndcg5_mean")
    if not isinstance(ndcg, (int, float)):
        return CriterionResult(
            name=name,
            ok=False,
            reason="watchdog report missing numeric ndcg5_mean",
        )
    if ndcg < ndcg5_min:
        return CriterionResult(
            name=name,
            ok=False,
            reason=(
                f"watchdog ndcg5_mean={ndcg:.4f} < {ndcg5_min} "
                f"(see {report_path})"
            ),
        )
    return CriterionResult(
        name=name,
        ok=True,
        reason=(
            f"staging_version={staging_version} "
            f"ndcg5_mean={ndcg:.4f}"
        ),
    )


# ---------------------------------------------------------------------------
# LanceDB integrity verification (synthesis D1 §3)
# ---------------------------------------------------------------------------

#: The vector columns the server searches by ANN — the two that
#: ``ingest.store._create_indices`` indexes. ``embedding_eq`` is reserved
#: and always NULL on ``chunks``, so it is not checked.
ANN_VECTOR_COLUMNS: tuple[str, ...] = ("embedding_stmt", "embedding_proof")


def vector_index_gaps(tbl) -> list[str]:
    """Describe each ANN vector column of ``tbl`` that no index fully covers.

    A column that holds vectors needs an index with
    ``num_unindexed_rows == 0``. A column with no vectors at all needs
    none: ``_create_indices`` cannot train an index on it and skips it,
    so an all-NULL ``embedding_proof`` is legitimate. Rows outside an
    index are still found, by a flat scan, so a gap costs speed rather
    than rows, and no other check in this gate would notice it.

    ``tbl`` must be the version-pinned handle the server will serve:
    ``list_indices()`` reports the indexes of the checked-out version.
    Returns an empty list when every column is covered. Exceptions
    propagate; the caller fails closed on them.
    """
    indices_by_column: dict[str, list[str]] = {}
    for cfg in tbl.list_indices():
        for column in cfg.columns:
            indices_by_column.setdefault(column, []).append(cfg.name)
    gaps: list[str] = []
    for column in ANN_VECTOR_COLUMNS:
        vectors = tbl.count_rows(f"{column} IS NOT NULL")
        if vectors == 0:
            continue
        names = indices_by_column.get(column, [])
        if not names:
            gaps.append(f"{column} holds {vectors} vectors but has no index")
            continue
        shortfalls: list[str] = []
        covered = False
        for index_name in names:
            stats = tbl.index_stats(index_name)
            if stats is None:
                shortfalls.append(f"{index_name} reports no stats")
            elif stats.num_unindexed_rows > 0:
                shortfalls.append(
                    f"{index_name} misses {stats.num_unindexed_rows} rows"
                )
            else:
                covered = True
        if not covered:
            gaps.extend(shortfalls)
    return gaps


def verify_lancedb_integrity(
    staging_path: Path = DEFAULT_LANCEDB_STAGING_PATH,
) -> CriterionResult:
    """Open the staging chunks table at its pinned version; assert it
    has rows and that its vector indexes cover every row.

    Replaces the brief's fictional `lancedb verify` CLI. Lazy-
    imports `ingest.corpus.open_chunks_table` so the cutover
    module is cheap to import for unit tests.

    The index check matters because ``ingest.re_embed`` writes staging
    without indexes and builds them once at the end, and C3 accepts
    ``complete_with_failures``: a staging table whose build never ran
    would otherwise be promoted, and every search would silently scan
    flat. See :func:`vector_index_gaps`.
    """
    name = "LanceDB integrity (staging)"
    if not (staging_path / CORPUS_VERSION_MARKER_NAME).is_file():
        return CriterionResult(
            name=name,
            ok=False,
            reason=(
                f"staging marker missing at {staging_path}/"
                f"{CORPUS_VERSION_MARKER_NAME}"
            ),
        )
    try:
        from ingest.corpus import (  # noqa: PLC0415
            open_chunks_table,
            read_corpus_version,
        )

        info = read_corpus_version(lancedb_path=staging_path)
        if info is None:
            return CriterionResult(
                name=name,
                ok=False,
                reason="read_corpus_version returned None on staging",
            )
        tbl = open_chunks_table(
            lancedb_path=staging_path, version=info.version
        )
        row_count = tbl.count_rows()
        gaps = vector_index_gaps(tbl) if row_count else []
    except Exception as exc:  # noqa: BLE001 — integrity probe
        return CriterionResult(
            name=name,
            ok=False,
            reason=f"LanceDB open/verify failed: {exc!r}",
        )
    if row_count == 0:
        return CriterionResult(
            name=name,
            ok=False,
            reason="staging chunks table has zero rows",
        )
    if gaps:
        return CriterionResult(
            name=name,
            ok=False,
            reason=(
                f"staging v{info.version} vector indexes do not cover "
                f"every row ({'; '.join(gaps)}); search would fall back "
                f"to a flat scan. A finished re-embed run, including a "
                f"--resume run, rebuilds them"
            ),
        )
    return CriterionResult(
        name=name,
        ok=True,
        reason=f"chunks={row_count}; vector indexes cover every row",
    )


# ---------------------------------------------------------------------------
# Directory swap + rollback
# ---------------------------------------------------------------------------


def perform_directory_swap(
    *,
    active_path: Path,
    staging_path: Path,
    rollback_path: Path,
) -> None:
    """Atomic directory swap. Two ``os.rename`` calls.

    Pre-flight: refuse if ``rollback_path`` already exists — that
    means a prior cutover failed and the operator's rollback
    lifeline is in place. Overwriting it would lose the
    pre-cutover state.

    Both renames are POSIX-atomic on the same filesystem; the
    microsecond window between them is the only ambiguity. If
    step 2 fails (e.g. permissions), step 1 is restored.
    """
    if rollback_path.exists():
        raise CutoverError(
            f"refusing to overwrite existing rollback path "
            f"{rollback_path} — a prior cutover may have failed. "
            f"Inspect, then move or remove the directory before "
            f"retrying."
        )
    if not active_path.exists():
        raise CutoverError(
            f"active path {active_path} does not exist; nothing "
            f"to swap"
        )
    if not staging_path.exists():
        raise CutoverError(
            f"staging path {staging_path} does not exist; nothing "
            f"to promote"
        )
    # Closes adversary F8: `os.rename` raises `OSError: EXDEV`
    # across filesystem boundaries. The atomic-swap contract
    # depends on same-FS renames; surface the constraint as a
    # `CutoverError` with an actionable message rather than a
    # raw OSError after the criterion checks have already run.
    active_dev = os.stat(active_path).st_dev
    staging_dev = os.stat(staging_path).st_dev
    rollback_parent_dev = os.stat(rollback_path.parent).st_dev
    if not (active_dev == staging_dev == rollback_parent_dev):
        raise CutoverError(
            f"cross-filesystem swap refused: active={active_path} "
            f"on st_dev={active_dev}, staging={staging_path} on "
            f"st_dev={staging_dev}, rollback parent="
            f"{rollback_path.parent} on st_dev={rollback_parent_dev}. "
            f"The atomic rename contract requires all three paths "
            f"on the SAME filesystem. Move staging/active to a "
            f"common mount before retrying."
        )
    os.rename(active_path, rollback_path)
    try:
        os.rename(staging_path, active_path)
    except OSError as exc:
        # Best-effort restore. The microsecond window between
        # rename calls is bounded; failure here is rare but must
        # not leave the active path missing.
        os.rename(rollback_path, active_path)
        raise CutoverError(
            f"directory swap failed at step 2 ({exc}); restored "
            f"original active path"
        ) from exc


def perform_rollback(
    *,
    active_path: Path,
    rollback_path: Path,
    failed_cutover_dir: Path | None = None,
) -> Path:
    """Inverse directory swap. Returns the failed-cutover path."""
    if not rollback_path.exists():
        raise CutoverError(
            f"rollback path {rollback_path} does not exist; "
            f"no prior cutover to roll back"
        )
    if not active_path.exists():
        raise CutoverError(
            f"active path {active_path} does not exist; "
            f"inconsistent state (cutover crashed mid-swap?)"
        )
    if failed_cutover_dir is None:
        failed_cutover_dir = active_path.parent / (
            f"lancedb-failed-cutover-{_utc_ts_filename()}"
        )
    os.rename(active_path, failed_cutover_dir)
    try:
        os.rename(rollback_path, active_path)
    except OSError as exc:
        os.rename(failed_cutover_dir, active_path)
        raise CutoverError(
            f"rollback failed at step 2 ({exc}); restored failed-"
            f"cutover state"
        ) from exc
    return failed_cutover_dir


# ---------------------------------------------------------------------------
# /readyz polling (AC4)
# ---------------------------------------------------------------------------


def poll_readyz(
    *,
    url: str = DEFAULT_READYZ_URL,
    total_timeout: float = DEFAULT_READYZ_TIMEOUT_SECONDS,
    interval: float = 5.0,
    sleep=time.sleep,
    monotonic=time.monotonic,
    urlopen=urllib.request.urlopen,
) -> bool:
    """Poll the server's /readyz endpoint until 200 or timeout.

    Returns True on 200, False on timeout.
    """
    deadline = monotonic() + total_timeout
    last_status: int | None = None
    while monotonic() < deadline:
        try:
            with urlopen(url, timeout=interval) as response:  # noqa: S310
                last_status = response.status
                if last_status == 200:
                    return True
        except urllib.error.URLError:
            pass
        sleep(interval)
    logger.warning(
        "readyz poll timed out after %.0fs (last_status=%s)",
        total_timeout, last_status,
    )
    return False


def _readyz_ok(url: str, *, timeout: float, urlopen) -> bool:  # noqa: ANN001
    try:
        with urlopen(url, timeout=timeout) as response:  # noqa: S310
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def served_corpus_version(
    *,
    url: str = DEFAULT_STATUS_URL,
    timeout: float = 5.0,
    urlopen=urllib.request.urlopen,
) -> int | None:
    """The corpus version the running server reports at ``/status``.

    ``None`` when the server does not answer or the body has no version.
    """
    try:
        with urlopen(url, timeout=timeout) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    try:
        value = body["checks"]["corpus:version"][0]["observedValue"]
    except (KeyError, IndexError, TypeError):
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def wait_for_promoted_server(
    *,
    expected_version: int,
    readyz_url: str = DEFAULT_READYZ_URL,
    status_url: str = DEFAULT_STATUS_URL,
    total_timeout: float = DEFAULT_READYZ_TIMEOUT_SECONDS,
    interval: float = 5.0,
    sleep=time.sleep,
    monotonic=time.monotonic,
    urlopen=urllib.request.urlopen,
) -> tuple[bool, int | None]:
    """Wait until the server is ready AND serving ``expected_version``.

    A ready answer alone proves nothing after a swap: a server that was
    never restarted still answers 200 while serving the old dataset,
    which is now the rollback copy. The server pins its corpus version at
    startup and reports it at ``/status``, so the check waits for that
    number to become the promoted one.

    Returns ``(ok, last_seen_version)``.
    """
    deadline = monotonic() + total_timeout
    seen: int | None = None
    while monotonic() < deadline:
        if _readyz_ok(readyz_url, timeout=interval, urlopen=urlopen):
            seen = served_corpus_version(url=status_url, urlopen=urlopen)
            if seen == expected_version:
                return True, seen
        sleep(interval)
    return False, seen


# ---------------------------------------------------------------------------
# Post-activation watchdog (AC5)
# ---------------------------------------------------------------------------


def run_post_activation_watchdog(
    *,
    corpus_version: int,
    active_path: Path = DEFAULT_LANCEDB_PATH,
    report_dir: Path = DEFAULT_WATCHDOG_REPORT_DIR,
    ndcg5_min: float = NDCG5_MIN,
    runner=subprocess.run,
    wall_clock=time.time,
) -> CriterionResult:
    """Invoke `python -m ops.watchdog_eval` against the now-
    active LanceDB. AC5: nDCG@5 ≥ 0.80 on 200K corpus.

    Closes adversary F2: the watchdog's exit code only reflects
    a RELATIVE regression check. AC5's stated job is an
    ABSOLUTE floor (`nDCG@5 ≥ 0.80`). After the watchdog
    subprocess completes, we read its newest report from
    ``report_dir`` and assert ``ndcg5_mean >= ndcg5_min``
    additionally — `exit 0 AND ndcg5_mean >= floor` is the
    pass condition.
    """
    name = "AC5: post-activation watchdog"
    # The nightly watchdog writes into the same directory. Only a report
    # for the promoted version, written during this run, is ours. The
    # one-second margin covers filesystems with coarse mtimes.
    started = wall_clock() - 1.0
    completed = runner(
        [
            sys.executable,
            "-m",
            "ops.watchdog_eval",
            "--lancedb-staging-path",
            str(active_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return CriterionResult(
            name=name,
            ok=False,
            reason=(
                f"watchdog exited {completed.returncode}; "
                f"stderr={completed.stderr.strip()[:200]}"
            ),
        )
    # Read the report this run wrote and check the absolute floor.
    if not report_dir.is_dir():
        return CriterionResult(
            name=name,
            ok=False,
            reason=(
                f"watchdog reported exit 0 but report_dir "
                f"{report_dir} is missing"
            ),
        )
    prefix = f"corpus_v{corpus_version}-"
    candidates = sorted(
        (p for p in report_dir.iterdir()
         if p.is_file() and p.name.startswith(prefix)
         and p.suffix == ".json" and p.stat().st_mtime >= started),
        key=lambda p: p.stat().st_mtime,
    )
    if not candidates:
        return CriterionResult(
            name=name,
            ok=False,
            reason=(
                f"watchdog reported exit 0 but wrote no report for "
                f"corpus_v{corpus_version} in {report_dir}"
            ),
        )
    latest = candidates[-1]
    try:
        report = json.loads(latest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return CriterionResult(
            name=name,
            ok=False,
            reason=f"watchdog report at {latest} is malformed: {exc}",
        )
    ndcg = report.get("ndcg5_mean")
    if not isinstance(ndcg, (int, float)):
        # An underpowered run has ndcg5_mean=null; treat as
        # pass-by-skip (the run wasn't a real measurement).
        if report.get("underpowered") or report.get("query_count") == 0:
            return CriterionResult(
                name=name,
                ok=True,
                reason=(
                    "watchdog reported underpowered run "
                    "(fixture too small for absolute floor check)"
                ),
            )
        return CriterionResult(
            name=name,
            ok=False,
            reason=(
                f"watchdog report at {latest} has no numeric "
                f"ndcg5_mean"
            ),
        )
    if ndcg < ndcg5_min:
        return CriterionResult(
            name=name,
            ok=False,
            reason=(
                f"post-activation ndcg5_mean={ndcg:.4f} < "
                f"{ndcg5_min} (see {latest})"
            ),
        )
    return CriterionResult(
        name=name,
        ok=True,
        reason=f"ndcg5_mean={ndcg:.4f} (see {latest})",
    )


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


def run_cutover(
    *,
    active_path: Path = DEFAULT_LANCEDB_PATH,
    staging_path: Path = DEFAULT_LANCEDB_STAGING_PATH,
    rollback_path: Path = DEFAULT_ROLLBACK_PATH,
    aggregate_dir: Path = DEFAULT_AGGREGATE_EVAL_DIR,
    watchdog_report_dir: Path = DEFAULT_WATCHDOG_REPORT_DIR,
    quarantine_flag_path: Path = DEFAULT_QUARANTINE_FLAG_PATH,
    re_embed_state_path: Path = DEFAULT_RE_EMBED_STATE_PATH,
    restore_drill_flag_path: Path = DEFAULT_RESTORE_DRILL_FLAG_PATH,
    readyz_url: str = DEFAULT_READYZ_URL,
    status_url: str = DEFAULT_STATUS_URL,
    readyz_timeout: float = DEFAULT_READYZ_TIMEOUT_SECONDS,
    dry_run: bool = False,
    skip_post_activation: bool = False,
) -> int:
    """Drive the cutover end-to-end. Returns exit code."""
    active_marker = active_path / CORPUS_VERSION_MARKER_NAME
    staging_marker = staging_path / CORPUS_VERSION_MARKER_NAME

    # Run all 4 criteria checks (cheap-first).
    results: list[CriterionResult] = []
    results.append(check_criterion_3_re_embed_state(re_embed_state_path))
    results.append(check_criterion_4_restore_drill(restore_drill_flag_path))
    results.append(
        check_criterion_1_seed_eval(
            active_marker_path=active_marker,
            aggregate_dir=aggregate_dir,
        )
    )
    results.append(
        check_criterion_2_watchdog(
            staging_marker_path=staging_marker,
            report_dir=watchdog_report_dir,
            quarantine_flag_path=quarantine_flag_path,
        )
    )
    # Plus the LanceDB integrity probe (synthesis D1 §3).
    results.append(verify_lancedb_integrity(staging_path))

    print("\n=== Activation criteria ===")
    for r in results:
        marker = "PASS" if r.ok else "FAIL"
        print(f"  [{marker}] {r.name}: {r.reason}")
    print()

    failed = [r for r in results if not r.ok]
    if failed:
        print(f"REFUSED: {len(failed)} criterion/criteria failed")
        return 1

    if dry_run:
        print("DRY RUN: all criteria pass; not performing swap")
        return 0

    # Criterion 2 has already checked that the marker holds an int.
    promoted_version = json.loads(staging_marker.read_text(encoding="utf-8"))[
        "version"
    ]

    print("Performing atomic directory swap...")
    perform_directory_swap(
        active_path=active_path,
        staging_path=staging_path,
        rollback_path=rollback_path,
    )
    print(f"Swap complete. Old active saved to {rollback_path}.")

    print(
        "Operator action required: restart the MCP server now."
    )
    print(
        f"Waiting up to {readyz_timeout:.0f}s for {readyz_url} to be "
        f"ready and {status_url} to report corpus_v{promoted_version}..."
    )
    ok, seen = wait_for_promoted_server(
        expected_version=promoted_version,
        readyz_url=readyz_url,
        status_url=status_url,
        total_timeout=readyz_timeout,
    )
    if not ok:
        if seen is None:
            print(
                f"FAILED: no ready server reported a corpus version within "
                f"{readyz_timeout:.0f}s. Inspect server logs."
            )
        else:
            print(
                f"FAILED: the server is serving corpus_v{seen}, not the "
                f"promoted corpus_v{promoted_version}. It was probably not "
                f"restarted. Restart it and rerun the post-activation "
                f"check, or run --rollback."
            )
        return 1
    print(f"Server is ready and serving corpus_v{promoted_version}")

    if skip_post_activation:
        print(
            "Skipping post-activation watchdog (--skip-post-activation)"
        )
        return 0

    print("Running post-activation watchdog...")
    post = run_post_activation_watchdog(
        corpus_version=promoted_version,
        active_path=active_path,
        report_dir=watchdog_report_dir,
    )
    marker = "PASS" if post.ok else "FAIL"
    print(f"  [{marker}] {post.name}: {post.reason}")
    return 0 if post.ok else 1


def run_rollback_cli(
    *,
    active_path: Path = DEFAULT_LANCEDB_PATH,
    rollback_path: Path = DEFAULT_ROLLBACK_PATH,
) -> int:
    """CLI entry for `--rollback`."""
    print(f"Rolling back active {active_path} from {rollback_path}...")
    failed_dir = perform_rollback(
        active_path=active_path,
        rollback_path=rollback_path,
    )
    print(f"Rollback complete. Failed cutover saved to {failed_dir}.")
    print(
        "Operator action required: restart the MCP server to pick "
        "up the rolled-back corpus."
    )
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="arXMCP 200K cutover activation (E11_S05).",
    )
    parser.add_argument(
        "--active-lancedb-path",
        default=str(DEFAULT_LANCEDB_PATH),
        type=Path,
    )
    parser.add_argument(
        "--lancedb-staging-path",
        default=str(DEFAULT_LANCEDB_STAGING_PATH),
        type=Path,
    )
    parser.add_argument(
        "--rollback-path",
        default=str(DEFAULT_ROLLBACK_PATH),
        type=Path,
    )
    parser.add_argument(
        "--readyz-url",
        default=DEFAULT_READYZ_URL,
    )
    parser.add_argument(
        "--status-url",
        default=DEFAULT_STATUS_URL,
        help="Where the server reports the corpus version it serves.",
    )
    parser.add_argument(
        "--readyz-timeout",
        default=DEFAULT_READYZ_TIMEOUT_SECONDS,
        type=float,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check all criteria; do not perform the swap.",
    )
    parser.add_argument(
        "--skip-post-activation",
        action="store_true",
        help=(
            "Skip the post-activation watchdog check (operator "
            "may prefer to run it manually)."
        ),
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help=(
            "Inverse swap. Restores the pre-cutover active "
            "dataset from var/arxmcp/index/lancedb-prev/."
        ),
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.rollback:
        return run_rollback_cli(
            active_path=args.active_lancedb_path,
            rollback_path=args.rollback_path,
        )

    return run_cutover(
        active_path=args.active_lancedb_path,
        staging_path=args.lancedb_staging_path,
        rollback_path=args.rollback_path,
        readyz_url=args.readyz_url,
        status_url=args.status_url,
        readyz_timeout=args.readyz_timeout,
        dry_run=args.dry_run,
        skip_post_activation=args.skip_post_activation,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_cli(sys.argv[1:]))


__all__ = [
    "ANN_VECTOR_COLUMNS",
    "CriterionResult",
    "CutoverError",
    "DEFAULT_AGGREGATE_EVAL_DIR",
    "DEFAULT_QUARANTINE_FLAG_PATH",
    "DEFAULT_READYZ_TIMEOUT_SECONDS",
    "DEFAULT_READYZ_URL",
    "DEFAULT_RESTORE_DRILL_FLAG_PATH",
    "DEFAULT_ROLLBACK_PATH",
    "DEFAULT_WATCHDOG_REPORT_DIR",
    "NDCG5_MIN",
    "check_criterion_1_seed_eval",
    "check_criterion_2_watchdog",
    "check_criterion_3_re_embed_state",
    "check_criterion_4_restore_drill",
    "perform_directory_swap",
    "perform_rollback",
    "poll_readyz",
    "served_corpus_version",
    "wait_for_promoted_server",
    "run_cutover",
    "run_post_activation_watchdog",
    "vector_index_gaps",
    "verify_lancedb_integrity",
]
