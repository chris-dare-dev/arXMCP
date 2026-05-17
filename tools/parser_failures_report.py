#!/usr/bin/env python3
"""Weekly parser-failures review report (E14_S04).

Aggregates the per-stage failure logs under
``var/arxmcp/ops/parser-failures/`` into an ISO-week markdown
report at ``var/arxmcp/ops/reports/parser-failures-<YYYY>-W<NN>.md``.

The producer files mix two formats (both established before
E14_S04):

- **TSV** (4 columns: ``paper_id\\tstatus\\televapsed_s\\treason\\n``):
  ``chunk.log``, ``preamble.log``, ``embed.log``, ``seed.log``.
- **JSONL** (one object per line, keys include ``paper_id``,
  ``failure_reason`` or ``reason``, ``timestamp``):
  ``delta.jsonl``, ``bulk.jsonl``, ``re-embed.jsonl``.

The reporter reads both formats and groups by ``(stage, reason)``
to surface the most common failure modes for human triage. The
operator-facing workflow lives at
``docs/ops/parser-failure-review.md``.

Usage::

    uv run python -m tools.parser_failures_report  # current week
    uv run python -m tools.parser_failures_report --dry-run
    uv run python -m tools.parser_failures_report --week 2026-W19

Acceptance: ``--dry-run`` writes nothing to disk and prints
markdown to stdout. The test surface drives small fixture trees
under ``tmp_path``.

E14_S04 scope expansion (synthesis D2): the brief asserted this
script was "authored in E02_S06" but E02 stops at S05 — the
file is being authored here.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import pathlib
import sys
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass

logger = logging.getLogger(__name__)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Where ingest stages drop per-stage failure logs.
DEFAULT_PARSER_FAILURES_DIR: pathlib.Path = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "parser-failures"
)

#: Output directory for the weekly report.
DEFAULT_REPORTS_DIR: pathlib.Path = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "reports"
)

#: Map filename → stage name surfaced in the report. The list is
#: closed at the inventory found in researcher 1's brief §1.3 +
#: the live grep against ``ingest/*.py``. Adding a stage requires
#: an entry here AND updating ``docs/ops/parser-failure-review.md``.
KNOWN_TSV_LOGS: dict[str, str] = {
    "chunk.log": "chunker",
    "preamble.log": "preamble",
    "embed.log": "embedder",
    "seed.log": "seed-fetch",
}

KNOWN_JSONL_LOGS: dict[str, str] = {
    "delta.jsonl": "oai-delta",
    "bulk.jsonl": "bulk-ingest",
    "re-embed.jsonl": "re-embed",
}

#: Top-N failure reasons surfaced per-stage in the report. The
#: weekly review fixture stays readable at 10; bump in the
#: runbook if needed.
TOP_N: int = 10


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FailureRecord:
    """One row in the rolled-up failure table.

    ``timestamp`` is the parsed UTC datetime when available; for
    TSV rows without a timestamp column, it's ``None`` and the
    week-filter falls back to the file's mtime.
    """

    stage: str
    paper_id: str
    reason: str
    timestamp: datetime.datetime | None


def _parse_tsv(
    path: pathlib.Path, stage: str
) -> Iterator[FailureRecord]:
    """Yield failure records from a TSV log file.

    The TSV shape is ``<paper_id>\\t<status>\\televapsed_s\\t<reason>``;
    rows with ``status != "fail"`` are skipped (the TSV is
    append-only across the whole run, not just failures).
    """
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 4:
                    continue
                paper_id, status, _elapsed, reason = parts[:4]
                if status.strip() != "fail":
                    continue
                yield FailureRecord(
                    stage=stage,
                    paper_id=paper_id,
                    reason=reason,
                    timestamp=None,
                )
    except OSError:
        logger.warning("could not read TSV log %s; skipping", path)


def _parse_jsonl(
    path: pathlib.Path, stage: str
) -> Iterator[FailureRecord]:
    """Yield failure records from a JSONL log file. Accepts both
    the bulk-ingest schema (``failure_reason``, ``timestamp``)
    and any future stage that surfaces ``reason``.
    """
    try:
        with path.open(encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(
                        "%s:%d malformed JSON; skipping", path, line_no
                    )
                    continue
                if not isinstance(rec, dict):
                    continue
                paper_id = rec.get("paper_id", "")
                reason = (
                    rec.get("failure_reason")
                    or rec.get("reason")
                    or "<unspecified>"
                )
                ts_raw = rec.get("timestamp") or rec.get("ts")
                ts: datetime.datetime | None = None
                if isinstance(ts_raw, str):
                    try:
                        ts = datetime.datetime.fromisoformat(
                            ts_raw.replace("Z", "+00:00")
                        )
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=datetime.UTC)
                    except ValueError:
                        ts = None
                yield FailureRecord(
                    stage=stage, paper_id=paper_id, reason=str(reason),
                    timestamp=ts,
                )
    except OSError:
        logger.warning("could not read JSONL log %s; skipping", path)


def collect_records(
    parser_dir: pathlib.Path,
) -> list[FailureRecord]:
    """Walk ``parser_dir`` and return every failure record from
    every known stage."""
    out: list[FailureRecord] = []
    if not parser_dir.is_dir():
        logger.info("no parser-failures dir at %s; nothing to report", parser_dir)
        return out
    for fname, stage in KNOWN_TSV_LOGS.items():
        p = parser_dir / fname
        if p.is_file():
            out.extend(_parse_tsv(p, stage))
    for fname, stage in KNOWN_JSONL_LOGS.items():
        p = parser_dir / fname
        if p.is_file():
            out.extend(_parse_jsonl(p, stage))
    return out


# ---------------------------------------------------------------------------
# Week filtering
# ---------------------------------------------------------------------------


def parse_week(s: str) -> tuple[int, int]:
    """Parse a ``YYYY-Www`` string (e.g. ``"2026-W19"``) into a
    ``(year, week)`` tuple. Raises ``argparse.ArgumentTypeError``
    on malformed input."""
    try:
        year_s, week_s = s.split("-W")
        return int(year_s), int(week_s)
    except (ValueError, IndexError) as exc:
        raise argparse.ArgumentTypeError(
            f"invalid --week {s!r}; expected YYYY-Www (e.g. 2026-W19)"
        ) from exc


def filter_by_week(
    records: list[FailureRecord],
    iso_year: int,
    iso_week: int,
    log_paths_for_mtime: dict[str, pathlib.Path] | None = None,
) -> list[FailureRecord]:
    """Return only records whose ISO week == ``(iso_year, iso_week)``.

    Records with an explicit ``timestamp`` are filtered directly.
    Records without (TSV legacy rows) fall back to the file's
    mtime via ``log_paths_for_mtime`` — when absent, those rows
    are NOT filtered out (conservative: surface them rather than
    silently drop).
    """
    out: list[FailureRecord] = []
    mtime_year_week: dict[str, tuple[int, int]] = {}
    if log_paths_for_mtime:
        for stage, path in log_paths_for_mtime.items():
            try:
                mt = datetime.datetime.fromtimestamp(
                    path.stat().st_mtime, tz=datetime.UTC
                )
                y, w, _ = mt.isocalendar()
                mtime_year_week[stage] = (y, w)
            except OSError:
                continue

    for r in records:
        if r.timestamp is not None:
            y, w, _ = r.timestamp.isocalendar()
            if (y, w) == (iso_year, iso_week):
                out.append(r)
            continue
        # TSV fallback: include if the source file's mtime is the
        # target week (best-effort), OR pass through when we have
        # no mtime info (conservative).
        mt = mtime_year_week.get(r.stage)
        if mt is None or mt == (iso_year, iso_week):
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def render_report(
    records: list[FailureRecord],
    iso_year: int,
    iso_week: int,
    generated_at: datetime.datetime,
) -> str:
    """Render the markdown report."""
    by_stage: dict[str, list[FailureRecord]] = defaultdict(list)
    for r in records:
        by_stage[r.stage].append(r)

    lines: list[str] = []
    lines.append(
        f"# Parser-failures weekly review — {iso_year}-W{iso_week:02d}"
    )
    lines.append("")
    lines.append(
        f"_Generated {generated_at.isoformat()} from "
        f"`var/arxmcp/ops/parser-failures/*`._"
    )
    lines.append("")

    # --- Totals ----------------------------------------------------------
    total = len(records)
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total failures: **{total}**")
    if total == 0:
        lines.append("")
        lines.append("_No failures in this window. The corpus is healthy._")
        lines.append("")
        return "\n".join(lines) + "\n"

    distinct_papers = len({r.paper_id for r in records})
    lines.append(f"- Distinct papers affected: **{distinct_papers}**")
    lines.append("")
    lines.append("| Stage | Failures |")
    lines.append("|---|---:|")
    for stage in sorted(by_stage):
        lines.append(f"| {stage} | {len(by_stage[stage])} |")
    lines.append("")

    # --- Per-stage top-N reasons ----------------------------------------
    for stage in sorted(by_stage):
        rs = by_stage[stage]
        lines.append(f"## Stage: `{stage}` ({len(rs)} failures)")
        lines.append("")
        reason_counts = Counter(r.reason for r in rs)
        lines.append(f"### Top {TOP_N} reasons")
        lines.append("")
        lines.append("| Count | Reason |")
        lines.append("|---:|---|")
        for reason, n in reason_counts.most_common(TOP_N):
            # Trim long reasons so the table stays readable.
            display = reason if len(reason) <= 160 else reason[:157] + "…"
            lines.append(f"| {n} | `{display}` |")
        lines.append("")

        # Top failing papers (so the operator can spot a single
        # broken-source-tarball that's getting retried).
        paper_counts = Counter(r.paper_id for r in rs)
        lines.append(f"### Top {TOP_N} failing papers")
        lines.append("")
        lines.append("| Count | paper_id |")
        lines.append("|---:|---|")
        for pid, n in paper_counts.most_common(TOP_N):
            lines.append(f"| {n} | `{pid}` |")
        lines.append("")

    # --- Triage pointer --------------------------------------------------
    lines.append("## Triage")
    lines.append("")
    lines.append(
        "See `docs/ops/parser-failure-review.md` for the human "
        "triage workflow + the must-act thresholds (>5% of week's "
        "papers fail → pause delta cron; >10 same-reason failures "
        "→ upstream investigation)."
    )
    lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Weekly parser-failures review report (E14_S04). Reads "
            "var/arxmcp/ops/parser-failures/, writes markdown to "
            "var/arxmcp/ops/reports/parser-failures-<YYYY>-W<NN>.md."
        )
    )
    p.add_argument(
        "--parser-dir",
        type=pathlib.Path,
        default=DEFAULT_PARSER_FAILURES_DIR,
        help=(
            f"parser-failures input dir "
            f"(default: {DEFAULT_PARSER_FAILURES_DIR})"
        ),
    )
    p.add_argument(
        "--out-dir",
        type=pathlib.Path,
        default=DEFAULT_REPORTS_DIR,
        help=f"output dir (default: {DEFAULT_REPORTS_DIR})",
    )
    p.add_argument(
        "--week",
        type=parse_week,
        default=None,
        help=(
            "ISO week to report on (e.g. 2026-W19). "
            "Default: the week containing yesterday UTC (so "
            "Sunday's cron covers the just-completed week)."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print markdown to stdout; do not write file",
    )
    return p.parse_args(argv)


def _default_week() -> tuple[int, int]:
    """Return the ISO week that "yesterday UTC" belongs to. The
    Sunday-06:00 cron runs at the start of the new week, so
    yesterday belongs to the just-completed week — exactly what
    we want to report on."""
    yesterday = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)
    y, w, _ = yesterday.isocalendar()
    return y, w


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    args = _parse_args(argv)
    iso_year, iso_week = args.week if args.week else _default_week()

    records = collect_records(args.parser_dir)
    log_paths_for_mtime = {
        stage: args.parser_dir / fname
        for fname, stage in KNOWN_TSV_LOGS.items()
        if (args.parser_dir / fname).is_file()
    }
    filtered = filter_by_week(
        records, iso_year, iso_week, log_paths_for_mtime
    )

    now = datetime.datetime.now(datetime.UTC)
    body = render_report(filtered, iso_year, iso_week, now)

    if args.dry_run:
        sys.stdout.write(body)
        return 0

    out_path = args.out_dir / f"parser-failures-{iso_year}-W{iso_week:02d}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    logger.info("wrote weekly parser-failures report to %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
