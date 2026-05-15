"""Drift watchdog: per-corpus-version nDCG@5 regression alert (E11_S04).

Runs the E05 retrieval-quality eval against a STAGING LanceDB
corpus version, compares the nDCG@5 mean against the most-recent
prior eval report, and writes a quarantine sentinel if the
regression exceeds the configured threshold. The active
``corpus-version.json`` is NEVER touched; staging itself is the
quarantine — the sentinel is the signal E11_S05's cutover script
reads before promoting staging → active.

**Statistical reality.** At 20 hand-labeled queries the
expected σ on the per-run nDCG@5 mean is ≈ 0.034 (assuming
per-query σ ≈ 0.15). A 5%-relative regression from 0.80 is 0.04
absolute = ~1.2σ — barely above noise. The brief's 5% therefore
becomes an OPERATIVE GOAL for the long term; the default
threshold ships at **10%** (~2.4σ at 20 queries, ~0.8% per-run
false-positive rate). Operator can tighten via
``ARXMCP_EVAL_REGRESSION_THRESHOLD_PCT`` once the fixture grows.

**Fixture-size policy.**

- ``len(queries) == 0``: skip the run entirely (exit 0).
- ``len(queries) < MIN_QUERIES_FOR_REGRESSION_CHECK (10)``:
  compute + write the metric for visibility, but DO NOT alert
  (``regression_vs_prev=null``, ``alert_triggered=false``,
  ``underpowered=true``).
- ``len(queries) >= 10``: full regression check.

**Cross-process /metrics exposure.** ``EVAL_NDCG5_GAUGE`` lives in
``server/metrics.py`` but is only populated in-process. The
production ``/metrics`` endpoint exposing this gauge for the
running server is **deferred to E14** — matches the
``LATEXML_DRIFT_DETECTED_COUNTER`` precedent (server/metrics.py
F8). v1 operational signal is: non-zero exit + ERROR log +
``var/arxmcp/ops/eval-quarantine.flag`` sentinel.

**Integration.** The watchdog refuses to run when the E11_S03
re-embed state file at ``var/arxmcp/ops/re-embed-state.json``
reports ``status="in_progress"``. Operator schedules the
watchdog as a separate cron entry ~30 min after the delta loop
(``ops/cron/arxmcp-delta.sh``).

See ``docs/ops/drift-watchdog.md`` for the operator workflow.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import getpass
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from ingest.bulk_ingest import DEFAULT_LANCEDB_STAGING_PATH
from server.metrics import EVAL_NDCG5_GAUGE

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Watchdog refuses to compute a regression alert with fewer than
#: this many queries — sampling noise dominates at small fixture
#: sizes. The metric is still emitted (for visibility) but no
#: alert can fire. Empty fixture (0 queries) skips the run.
MIN_QUERIES_FOR_REGRESSION_CHECK: int = 10

#: Default alert threshold (percent). Brief specifies 5%; synthesis
#: D4 ships 10% because 5% is below the noise floor at 20 queries.
#: Operator overrides via ``ARXMCP_EVAL_REGRESSION_THRESHOLD_PCT``.
DEFAULT_REGRESSION_THRESHOLD_PCT: float = 10.0

#: Standard E05 minimum (Tier-0 → Tier-1 gate; see TIER-GATES.md).
DEFAULT_NDCG_MIN: float = 0.70

#: Default fixture location.
DEFAULT_FIXTURE_PATH: Path = (
    REPO_ROOT / "tests" / "eval" / "fixtures" / "queries.json"
)

#: Default report output directory. Gitignored per the brief —
#: per-version JSON reports accumulate here.
DEFAULT_REPORT_DIR: Path = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "eval-reports"
)

#: Sentinel flag file written when an alert fires. E11_S05's
#: cutover script reads this to refuse promotion. Mirrors the
#: ``drift-detected.flag`` (E10_S04) and ``delta-timeout.flag``
#: (E11_S02) patterns.
DEFAULT_QUARANTINE_FLAG_PATH: Path = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "eval-quarantine.flag"
)

#: E11_S03 state file. Watchdog reads ``status`` and refuses to
#: run if it's mid-re-embed.
RE_EMBED_STATE_PATH: Path = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "re-embed-state.json"
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class WatchdogReport:
    """JSON-serializable per-run artifact written to
    ``var/arxmcp/ops/eval-reports/corpus_v<N>-<ts>.json``."""

    corpus_version: int
    ndcg5_mean: float | None
    recall10_mean: float | None
    ndcg5_per_query: list[dict]
    query_count: int
    fixture_query_count: int
    regression_vs_prev: float | None  # signed absolute delta (new - prev)
    regression_pct: float | None      # > 0 = decline
    alert_triggered: bool
    prior_report_path: str | None
    prior_ndcg5_mean: float | None
    threshold_pct: float
    rerank_enabled: bool
    fixture_path: str
    timestamp: str
    underpowered: bool
    embedder_version: str | None = None  # closes F2: mixing-guard data
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "alert_triggered": self.alert_triggered,
            "corpus_version": self.corpus_version,
            "embedder_version": self.embedder_version,
            "fixture_path": self.fixture_path,
            "fixture_query_count": self.fixture_query_count,
            "ndcg5_mean": self.ndcg5_mean,
            "ndcg5_per_query": self.ndcg5_per_query,
            "notes": self.notes,
            "prior_ndcg5_mean": self.prior_ndcg5_mean,
            "prior_report_path": self.prior_report_path,
            "query_count": self.query_count,
            "recall10_mean": self.recall10_mean,
            "regression_pct": self.regression_pct,
            "regression_vs_prev": self.regression_vs_prev,
            "rerank_enabled": self.rerank_enabled,
            "threshold_pct": self.threshold_pct,
            "timestamp": self.timestamp,
            "underpowered": self.underpowered,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_iso() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_ts_filename() -> str:
    """``YYYYMMDDTHHMMSS`` for embedding in report filenames."""
    return _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%S")


def _parse_threshold_pct(raw: str | float) -> float:
    """Parse and validate a threshold-percent value.

    Closes synthesis D4: reject non-numeric, ≤0, >100.
    """
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"ARXMCP_EVAL_REGRESSION_THRESHOLD_PCT must be numeric; "
            f"got {raw!r}"
        ) from exc
    if value <= 0:
        raise ValueError(
            f"threshold-pct must be > 0; got {value} (0 is "
            f"pathological — every run would alert)"
        )
    if value > 100:
        raise ValueError(
            f"threshold-pct must be <= 100; got {value} (>100 means "
            f"nDCG@5 must go negative to alert, which is impossible)"
        )
    return value


def evaluate_regression(
    prev_ndcg5: float, new_ndcg5: float, threshold_pct: float
) -> tuple[float, float, bool]:
    """One-directional regression test.

    Returns ``(regression_vs_prev, regression_pct, alert_triggered)``.

    * ``regression_vs_prev`` = ``new_ndcg5 - prev_ndcg5`` (signed
      absolute delta; negative = decline).
    * ``regression_pct`` = ``(prev - new) / prev * 100`` (positive
      when nDCG declined).
    * ``alert_triggered`` = ``regression_pct > threshold_pct``
      (one-directional — improvements never alert).
    """
    if prev_ndcg5 <= 0:
        # Pathological prior; can't compute a relative regression.
        # Returning (0, 0, False) treats this as "no regression
        # signal" rather than dividing by zero.
        return 0.0, 0.0, False
    regression_vs_prev = new_ndcg5 - prev_ndcg5
    regression_pct = (prev_ndcg5 - new_ndcg5) / prev_ndcg5 * 100.0
    alert = regression_pct > threshold_pct
    return regression_vs_prev, regression_pct, alert


# ---------------------------------------------------------------------------
# Re-embed-state gate
# ---------------------------------------------------------------------------


#: Whitelist of re-embed states that MUST suppress a watchdog run.
#: Closes adversary F10: invert the predicate from a "block on
#: anything-not-complete" blacklist to a "block on known
#: in-progress" whitelist. The risk posture matters — running
#: the watchdog against a half-finished staging dataset costs
#: one false alert; SKIPPING because an unrecognized status
#: string appeared in the state file costs an entire nightly run
#: silently. Default-to-run is safer.
_RE_EMBED_IN_PROGRESS_STATES: frozenset[str] = frozenset(
    {"in_progress", "starting", "interrupted"}
)


def _re_embed_blocks_run(state_path: Path) -> bool:
    """Return True iff the re-embed state file reports a known
    in-progress state.

    Absent file, malformed JSON, or unrecognized status → False
    (run anyway). Closes adversary F10: a future E11_S03 status
    string we don't recognize must NOT silently skip every nightly
    run.
    """
    if not state_path.is_file():
        return False
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning(
            "watchdog: re-embed-state.json at %s is malformed; "
            "running anyway.",
            state_path,
        )
        return False
    status = state.get("status")
    if not isinstance(status, str):
        return False
    return status in _RE_EMBED_IN_PROGRESS_STATES


# ---------------------------------------------------------------------------
# Fixture loading
# ---------------------------------------------------------------------------


def _load_fixture(path: Path) -> dict:
    """Read the eval fixture from disk. Raises if the file is
    malformed (a corrupt fixture is a setup error, not a
    runtime-skip)."""
    if not path.is_file():
        raise FileNotFoundError(
            f"eval fixture not found at {path}. Run the curation "
            f"workflow per .claude/docs/eval-curation.md."
        )
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Prior-report lookup
# ---------------------------------------------------------------------------


def find_prior_report(
    report_dir: Path, current_version: int
) -> tuple[Path | None, dict | None]:
    """Pick the most-recent prior report with corpus_version <
    current_version. Returns ``(path, parsed_json)``.

    Closes synthesis D7: corrupt or unreadable prior reports are
    treated as "no prior report" (a regression check against
    garbage is worse than no regression check).
    """
    if not report_dir.is_dir():
        return None, None
    candidates: list[tuple[int, Path]] = []
    for entry in report_dir.iterdir():
        if not entry.is_file() or not entry.name.startswith("corpus_v"):
            continue
        try:
            # Filename is ``corpus_v<N>-<ts>.json``; split on ``-``.
            name = entry.stem  # strips .json
            version_part = name.split("-", 1)[0]
            v = int(version_part.removeprefix("corpus_v"))
        except (ValueError, AttributeError):
            continue
        if v >= current_version:
            continue
        candidates.append((v, entry))
    if not candidates:
        return None, None
    # Highest version < current. Tie-break by mtime (most recent).
    candidates.sort(key=lambda pair: (pair[0], pair[1].stat().st_mtime))
    chosen_path = candidates[-1][1]
    try:
        data = json.loads(chosen_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        # Closes adversary F5: narrow the catch to malformed-JSON
        # only. OSError (PermissionError, ENOSPC, etc.) is a setup
        # error, not a "no prior report" signal — let it propagate
        # so the operator sees a clear stack rather than silently
        # losing the baseline.
        logger.warning(
            "watchdog: prior report at %s is malformed JSON (%s); "
            "treating as no prior report.",
            chosen_path, exc,
        )
        return None, None
    if not isinstance(data, dict) or "ndcg5_mean" not in data:
        logger.warning(
            "watchdog: prior report at %s missing ndcg5_mean field; "
            "treating as no prior report.",
            chosen_path,
        )
        return None, None
    return chosen_path, data


# ---------------------------------------------------------------------------
# Quarantine sentinel
# ---------------------------------------------------------------------------


def _write_quarantine_flag(
    flag_path: Path, *, report: WatchdogReport, report_path: Path
) -> None:
    """Write the quarantine sentinel. E11_S05's cutover script
    reads this file's presence to refuse promotion."""
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "corpus_version": report.corpus_version,
        "ndcg5_baseline": report.prior_ndcg5_mean,
        "ndcg5_current": report.ndcg5_mean,
        "regression_pct": report.regression_pct,
        "threshold_pct": report.threshold_pct,
        "flagged_at": _utc_iso(),
        "report_path": str(report_path),
    }
    tmp = flag_path.with_suffix(flag_path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(flag_path)
    logger.error(
        "watchdog: nDCG@5 regression %.1f%% > %.1f%% threshold; "
        "wrote quarantine flag to %s",
        report.regression_pct, report.threshold_pct, flag_path,
    )


def _clear_quarantine_flag(flag_path: Path) -> bool:
    """Delete the quarantine sentinel. Returns True if cleared,
    False if the flag was already absent."""
    if not flag_path.is_file():
        return False
    flag_path.unlink()
    logger.info(
        "watchdog: cleared quarantine flag at %s (by user=%s)",
        flag_path, getpass.getuser(),
    )
    return True


# ---------------------------------------------------------------------------
# Report write
# ---------------------------------------------------------------------------


def _write_report(report_dir: Path, report: WatchdogReport) -> Path:
    """Write the per-run JSON report. Atomic via tmp + rename."""
    report_dir.mkdir(parents=True, exist_ok=True)
    filename = f"corpus_v{report.corpus_version}-{_utc_ts_filename()}.json"
    out = report_dir / filename
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(out)
    return out


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------


def run_watchdog(
    *,
    corpus_version: int | None = None,
    lancedb_staging_path: Path = DEFAULT_LANCEDB_STAGING_PATH,
    report_dir: Path = DEFAULT_REPORT_DIR,
    fixture_path: Path = DEFAULT_FIXTURE_PATH,
    threshold_pct: float | None = None,
    quarantine_flag_path: Path = DEFAULT_QUARANTINE_FLAG_PATH,
    re_embed_state_path: Path = RE_EMBED_STATE_PATH,
    dry_run: bool = False,
    compute_eval=None,
) -> tuple[int, WatchdogReport | None]:
    """Drive one watchdog run. Returns ``(exit_code, report)``.

    ``compute_eval`` is the dependency-injection seam used by tests
    to substitute the live retrieval pipeline. Signature:
    ``compute_eval(*, fixture, corpus_version, lancedb_staging_path,
    rerank_enabled) -> (per_query_rows: list[dict], rerank_enabled:
    bool)``. The default (lazy import) wires the real
    ``_run_hybrid_against_corpus`` from the existing test harness.
    """
    started = time.monotonic()

    # D6 — refuse if re-embed is in progress.
    if _re_embed_blocks_run(re_embed_state_path):
        logger.info(
            "watchdog: re-embed is in progress; skipping run."
        )
        return 0, None

    # D4 — threshold resolution.
    if threshold_pct is None:
        env_raw = os.environ.get(
            "ARXMCP_EVAL_REGRESSION_THRESHOLD_PCT"
        )
        if env_raw is None:
            threshold = DEFAULT_REGRESSION_THRESHOLD_PCT
        else:
            threshold = _parse_threshold_pct(env_raw)
    else:
        threshold = _parse_threshold_pct(threshold_pct)

    # Load fixture (raises on malformed file; absent fixture is a
    # setup error, not a runtime skip).
    fixture = _load_fixture(fixture_path)
    queries = fixture.get("queries", [])
    fixture_query_count = len(queries)

    # Empty fixture → silent skip per the synthesis policy.
    if fixture_query_count == 0:
        logger.info(
            "watchdog: fixture %s has zero queries; skipping. "
            "Run the curation workflow per "
            ".claude/docs/eval-curation.md to populate.",
            fixture_path,
        )
        return 0, None

    # Resolve corpus_version from staging marker if not supplied.
    if corpus_version is None:
        corpus_version = _read_staging_version(lancedb_staging_path)

    # Run the eval. The default compute_eval lazily imports the
    # production retrieval pipeline; tests substitute a stub.
    if compute_eval is None:
        compute_eval = _default_compute_eval
    rerank_enabled = (
        os.environ.get("ARXMCP_ENABLE_RERANK", "false").lower() == "true"
    )
    per_query_rows, rerank_enabled_actual = compute_eval(
        fixture=fixture,
        corpus_version=corpus_version,
        lancedb_staging_path=lancedb_staging_path,
        rerank_enabled=rerank_enabled,
    )

    # Aggregate.
    ndcg5_mean = (
        sum(r.get("ndcg5", 0.0) for r in per_query_rows)
        / max(len(per_query_rows), 1)
        if per_query_rows
        else None
    )
    recall10_mean = (
        sum(r.get("recall10", 0.0) for r in per_query_rows)
        / max(len(per_query_rows), 1)
        if per_query_rows
        else None
    )

    # Underpowered fixture → compute metric but don't alert.
    underpowered = (
        fixture_query_count < MIN_QUERIES_FOR_REGRESSION_CHECK
    )

    prior_path, prior_data = find_prior_report(report_dir, corpus_version)
    prior_ndcg5_mean = (
        prior_data["ndcg5_mean"] if prior_data is not None else None
    )

    regression_vs_prev: float | None = None
    regression_pct: float | None = None
    alert_triggered = False
    notes: list[str] = []

    if underpowered:
        notes.append(
            f"fixture has {fixture_query_count} queries; "
            f"regression check skipped (min={MIN_QUERIES_FOR_REGRESSION_CHECK})"
        )
    elif prior_ndcg5_mean is None:
        notes.append(
            "no prior report; first run for this corpus stream — "
            "no regression baseline available"
        )
    else:
        # Closes adversary F2: refuse to compare across embedder
        # bumps. The mixing-guard returns a note string (and
        # forces alert_triggered=False) when prior + staging
        # disagree on embedder_version.
        mixing_note = _check_embedder_version_mixing(
            staging_path=lancedb_staging_path,
            prior_report=prior_data,
        )
        if mixing_note is not None:
            notes.append(mixing_note)
        elif ndcg5_mean is not None:
            regression_vs_prev, regression_pct, alert_triggered = (
                evaluate_regression(prior_ndcg5_mean, ndcg5_mean, threshold)
            )

    report = WatchdogReport(
        corpus_version=corpus_version,
        ndcg5_mean=ndcg5_mean,
        recall10_mean=recall10_mean,
        ndcg5_per_query=[
            {
                "query_id": r.get("query_id", ""),
                "ndcg5": r.get("ndcg5", 0.0),
            }
            for r in per_query_rows
        ],
        query_count=len(per_query_rows),
        fixture_query_count=fixture_query_count,
        regression_vs_prev=regression_vs_prev,
        regression_pct=regression_pct,
        alert_triggered=alert_triggered,
        prior_report_path=str(prior_path) if prior_path else None,
        prior_ndcg5_mean=prior_ndcg5_mean,
        threshold_pct=threshold,
        rerank_enabled=rerank_enabled_actual,
        fixture_path=str(fixture_path),
        timestamp=_utc_iso(),
        underpowered=underpowered,
        # Closes adversary F2: persist embedder_version so future
        # watchdog runs can detect a bump and suppress meaningless
        # cross-space comparisons.
        embedder_version=_read_staging_embedder_version(
            lancedb_staging_path
        ),
        notes=notes,
    )

    # Populate the in-process Prometheus gauge (test-only at v1).
    if ndcg5_mean is not None:
        EVAL_NDCG5_GAUGE.labels(
            corpus_version=str(corpus_version)
        ).set(ndcg5_mean)

    if dry_run:
        print(json.dumps(report.to_dict(), sort_keys=True))
        return 0, report

    # Persist the report.
    report_path = _write_report(report_dir, report)

    # Sentinel logic.
    if alert_triggered:
        _write_quarantine_flag(
            quarantine_flag_path,
            report=report,
            report_path=report_path,
        )
        return 1, report

    elapsed = time.monotonic() - started
    logger.info(
        "watchdog: nDCG@5=%.4f vs prior=%s (regression_pct=%s); "
        "report=%s; elapsed=%.2fs",
        ndcg5_mean if ndcg5_mean is not None else float("nan"),
        f"{prior_ndcg5_mean:.4f}" if prior_ndcg5_mean is not None else "none",
        f"{regression_pct:.2f}" if regression_pct is not None else "none",
        report_path, elapsed,
    )
    return 0, report


def _read_staging_version(staging_path: Path) -> int:
    """Read ``version`` from the staging corpus-version.json."""
    marker = staging_path / "corpus-version.json"
    if not marker.is_file():
        raise RuntimeError(
            f"staging corpus-version.json missing at {marker}; "
            f"watchdog has no corpus_version to evaluate. "
            f"Run the delta loop or re-embed first."
        )
    data = json.loads(marker.read_text(encoding="utf-8"))
    version = data.get("version")
    if not isinstance(version, int):
        raise RuntimeError(
            f"staging corpus-version.json at {marker} has no integer "
            f"`version` field"
        )
    return version


def _read_staging_embedder_version(staging_path: Path) -> str | None:
    """Read ``embedder_version`` from the staging marker. Returns
    None if the field is absent (older markers don't carry it).

    Closes adversary F2: the embedder-bump mixing guard.
    """
    marker = staging_path / "corpus-version.json"
    if not marker.is_file():
        return None
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    value = data.get("embedder_version")
    return value if isinstance(value, str) and value else None


def _check_embedder_version_mixing(
    *, staging_path: Path, prior_report: dict | None
) -> str | None:
    """Refuse to compare nDCG@5 across embedder-version bumps.

    Closes adversary F2: comparing scores from runs with different
    embedder models is meaningless (the vector space changed). The
    watchdog refuses to alert in this case and returns a note string
    that gets attached to the report; the run proceeds (the metric
    is still emitted for visibility) but ``alert_triggered`` is
    forced to False.

    Returns None if there's no mismatch (or no prior); else a
    human-readable note. Does NOT raise — the goal is to suppress
    false alerts, not crash the cron.
    """
    if prior_report is None:
        return None
    staging_embedder = _read_staging_embedder_version(staging_path)
    prior_embedder = prior_report.get("embedder_version")
    if staging_embedder is None or prior_embedder is None:
        # Older reports / older markers didn't carry embedder_version;
        # nothing to compare against. Don't manufacture a mismatch.
        return None
    if staging_embedder != prior_embedder:
        return (
            f"embedder_version changed from {prior_embedder!r} (prior) "
            f"to {staging_embedder!r} (staging); regression alert "
            f"suppressed — comparing across embedder spaces is "
            f"meaningless. Re-establish baseline by re-running the "
            f"watchdog after promoting via E11_S05."
        )
    return None


# ---------------------------------------------------------------------------
# Default compute_eval — wires the production retrieval pipeline
# ---------------------------------------------------------------------------


def _default_compute_eval(
    *,
    fixture: dict,
    corpus_version: int,
    lancedb_staging_path: Path,
    rerank_enabled: bool,
) -> tuple[list[dict], bool]:
    """Run the production hybrid retrieval pipeline against the
    staging LanceDB at the pinned ``corpus_version`` and return
    per-query rows + the final rerank-enabled flag.

    Closes adversary F1: previously this function raised
    ``NotImplementedError`` and the CLI crashed against any
    populated fixture. Now wired to the existing harness's
    ``_run_hybrid_against_corpus`` from
    ``tests/eval/test_retrieval_quality.py`` (which already lives
    pytest-free at function level).

    **Requires a live BGE-M3 model.** This function is only
    invoked from the CLI; tests substitute ``compute_eval`` via
    the ``run_watchdog(compute_eval=...)`` seam. Lazy-imports the
    server stack so the watchdog module remains cheap to import.
    """
    import asyncio  # noqa: PLC0415

    from server.config import Config  # noqa: PLC0415
    from server.corpus import open_chunks_table  # noqa: PLC0415
    from server.query_encoder import encode_query  # noqa: PLC0415
    from tests.eval.test_retrieval_quality import (  # noqa: PLC0415
        _run_hybrid_against_corpus,
    )

    # Build a Config with the requested rerank flag. Mirrors the
    # E07_S04 eval harness path so a watchdog run sees the same
    # retrieval-quality posture as `make eval`.
    cfg = Config(enable_rerank=rerank_enabled)

    # Open the STAGING LanceDB at the pinned version. The
    # underlying open_chunks_table accepts an explicit path +
    # version; we pass both to ensure the watchdog never reads
    # the active dataset.
    tbl = open_chunks_table(
        lancedb_path=lancedb_staging_path,
        version=corpus_version,
    )

    # The harness's _run_hybrid_against_corpus signature requires
    # an async `encode_query` callable. The server's
    # query_encoder.encode_query is already async.
    rows = _run_hybrid_against_corpus(
        fixture.get("queries", []),
        tbl,
        encode_query,
        corpus_version=corpus_version,
        rerank_enabled=cfg.enable_rerank,
    )
    # Defensive: close the asyncio event loop set up inside
    # _run_hybrid_against_corpus. The helper manages its own
    # loop via ``loop.run_until_complete``; this comment is here
    # to document the asyncio import above as load-bearing.
    del asyncio
    return rows, cfg.enable_rerank


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="arXMCP drift watchdog (E11_S04).",
    )
    parser.add_argument(
        "--corpus-version",
        type=int,
        default=None,
        help=(
            "Staging LanceDB corpus version to evaluate. "
            "Default: read from the staging corpus-version.json."
        ),
    )
    parser.add_argument(
        "--lancedb-staging-path",
        default=str(DEFAULT_LANCEDB_STAGING_PATH),
        type=Path,
        help=(
            f"Staging LanceDB path (read-only). Default: "
            f"{DEFAULT_LANCEDB_STAGING_PATH}."
        ),
    )
    parser.add_argument(
        "--report-dir",
        default=str(DEFAULT_REPORT_DIR),
        type=Path,
        help=f"Per-run JSON report directory (default: {DEFAULT_REPORT_DIR}).",
    )
    parser.add_argument(
        "--fixture-path",
        default=str(DEFAULT_FIXTURE_PATH),
        type=Path,
        help=f"Eval fixture path (default: {DEFAULT_FIXTURE_PATH}).",
    )
    parser.add_argument(
        "--threshold-pct",
        type=float,
        default=None,
        help=(
            "Relative regression alert threshold in percent. "
            "Default: ARXMCP_EVAL_REGRESSION_THRESHOLD_PCT env or "
            f"{DEFAULT_REGRESSION_THRESHOLD_PCT}. The brief targets "
            f"5%% as a long-term goal; the larger default ships "
            f"because 5%% is below the noise floor at 20 queries."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Compute the metric and print the JSON report to stdout; "
            "write no files, no quarantine flag, exit 0 regardless of "
            "alert condition."
        ),
    )
    parser.add_argument(
        "--clear-quarantine",
        action="store_true",
        help=(
            "Delete the quarantine flag and exit. Use after "
            "investigating an alert."
        ),
    )
    # Closes adversary F8: programmatic tests honor a
    # quarantine_flag_path arg; the CLI should too so an operator
    # working against a non-default tree can clear that tree's
    # flag without monkeypatching.
    parser.add_argument(
        "--quarantine-flag-path",
        default=str(DEFAULT_QUARANTINE_FLAG_PATH),
        type=Path,
        help=(
            f"Override the quarantine flag path. Default: "
            f"{DEFAULT_QUARANTINE_FLAG_PATH}."
        ),
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.clear_quarantine:
        # Closes adversary F7: replace `return 0 if cleared else 0`
        # tautology with an explicit return and comment. Absent
        # flag is also success (--clear-quarantine is idempotent).
        _clear_quarantine_flag(args.quarantine_flag_path)
        return 0

    exit_code, _report = run_watchdog(
        corpus_version=args.corpus_version,
        lancedb_staging_path=args.lancedb_staging_path,
        report_dir=args.report_dir,
        fixture_path=args.fixture_path,
        threshold_pct=args.threshold_pct,
        quarantine_flag_path=args.quarantine_flag_path,
        dry_run=args.dry_run,
    )
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_cli(sys.argv[1:]))


__all__ = [
    "DEFAULT_FIXTURE_PATH",
    "DEFAULT_QUARANTINE_FLAG_PATH",
    "DEFAULT_REGRESSION_THRESHOLD_PCT",
    "DEFAULT_REPORT_DIR",
    "MIN_QUERIES_FOR_REGRESSION_CHECK",
    "RE_EMBED_STATE_PATH",
    "WatchdogReport",
    "evaluate_regression",
    "find_prior_report",
    "run_watchdog",
]
