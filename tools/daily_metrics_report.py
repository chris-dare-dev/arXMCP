#!/usr/bin/env python3
"""Daily ops metrics report (E14_S04).

Scrapes the running MCP server's ``/metrics`` endpoint, parses the
Prometheus exposition format, and renders a markdown report to
``var/arxmcp/ops/daily-reports/<YYYY-MM-DD>.md``. Optional email
delivery via stdlib ``smtplib`` when ``MAIL_TO``, ``MAIL_FROM``,
``SMTP_HOST`` are all set.

Usage::

    # Production cron path (run from repo root).
    uv run python -m tools.daily_metrics_report

    # Dry-run against a fixture (no network, no file write).
    uv run python -m tools.daily_metrics_report \\
        --dry-run --fixture tests/fixtures/metrics_sample.txt

    # Custom destination.
    uv run python -m tools.daily_metrics_report \\
        --out-dir /alt/path --metrics-url http://127.0.0.1:9999/metrics

Acceptance criteria (E14_S04):

- ``--dry-run`` produces valid markdown against the fixture
- Report includes all 7 tools in the latency breakdown
- Histogram quantiles use Prometheus's linear-interpolation
  algorithm (not bucket-walk — that would quantise P99 to bucket
  edges and the 5.0s ceiling makes the report useless).

The script never raises on a missing metric family (operator may
run it against a server that has not yet served any request);
empty/zero values render as ``n/a``.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import os
import pathlib
import smtplib
import sys
import urllib.error
import urllib.request
from email.message import EmailMessage

from prometheus_client.parser import text_string_to_metric_families

logger = logging.getLogger(__name__)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Canonical tool surface — must stay in sync with
#: ``server/tools.py::ALL_TOOLS``. The E14_S04 acceptance criterion
#: "Report includes all 7 tools" pins this list explicitly.
TOOLS: tuple[str, ...] = (
    "search_papers",
    "get_chunk",
    "find_equation",
    "get_definitions",
    "find_lemma_by_name",
    "get_paper",
    "cite_neighbors",
)

#: Cache tier labels. Note the label name is ``tier``, NOT
#: ``layer`` as `.claude/notes/08-security-observability-ops.md`
#: documents — the constitution note has drift; the shipped code
#: uses ``tier``. See E14_S04 synthesis D4.
CACHE_TIERS: tuple[str, ...] = ("1", "2", "3")

#: Default MCP server endpoint for the cron path. Matches
#: ``server/config.py::Config.bind_port`` default (7733).
DEFAULT_METRICS_URL: str = "http://127.0.0.1:7733/metrics"

#: Default output directory relative to repo root.
DEFAULT_OUT_DIR: pathlib.Path = REPO_ROOT / "var/arxmcp/ops/daily-reports"


# ---------------------------------------------------------------------------
# Prometheus client-side helpers
# ---------------------------------------------------------------------------


def histogram_quantile(
    q: float, buckets: list[tuple[float, float]]
) -> float:
    """Compute the ``q``-th quantile from cumulative Prometheus
    histogram bucket counts using linear interpolation within the
    matching bucket.

    Mirrors Prometheus's ``promql/quantile.go`` algorithm
    verbatim — bucket-walk alone would quantise P99 to the
    nearest bucket edge (the 5.0s ceiling on
    ``arxmcp_request_latency_seconds`` makes that useless for any
    tool spending <5s). See E14_S04 synthesis D3.

    Parameters
    ----------
    q:
        Quantile in [0, 1].
    buckets:
        Sorted list of ``(le, cumulative_count)`` tuples. The
        ``+Inf`` (``float("inf")``) bucket is REQUIRED per the
        Prometheus exposition contract.

    Returns
    -------
    Quantile estimate in the same units as the bucket boundaries.
    Returns ``nan`` when ``buckets`` is empty or contains no
    observations.
    """
    if not buckets:
        return float("nan")
    # F6 rectification (E14_S04 adversary critique): the Prometheus
    # exposition spec requires a ``le="+Inf"`` overflow bucket on
    # every histogram. Without it, the quantile algorithm has no
    # way to know the total observation count, and would silently
    # return a value drawn from the highest-finite-le bucket — a
    # foot-gun for any future caller that doesn't know the
    # constraint. Raise instead.
    if buckets[-1][0] != float("inf"):
        raise ValueError(
            f"histogram missing +Inf overflow bucket "
            f"(highest le={buckets[-1][0]}); Prometheus expositions "
            f"without le='+Inf' are malformed per the spec"
        )
    total = buckets[-1][1]
    if total == 0:
        return float("nan")
    rank = q * total
    prev_le, prev_count = 0.0, 0.0
    for le, count in buckets:
        if count >= rank:
            if le == float("inf"):
                # Cannot interpolate past +Inf; clamp at the
                # previous (highest finite) bucket edge.
                return prev_le
            if prev_count == count:
                # Empty bucket between prev_le and le; clamp.
                return prev_le
            return prev_le + (le - prev_le) * (rank - prev_count) / (
                count - prev_count
            )
        prev_le, prev_count = le, count
    return buckets[-1][0]


def _collect_histogram_buckets(
    samples: list, family_name: str, label_filter: dict[str, str]
) -> list[tuple[float, float]]:
    """Extract sorted ``(le, count)`` buckets for a single histogram
    label-set out of a parsed metric family's sample list.

    The Prometheus parser exposes histograms as one family with
    samples of three shapes: ``<name>_bucket`` (with ``le`` label),
    ``<name>_count``, ``<name>_sum``. We pull only the ``_bucket``
    rows matching ``label_filter`` (excluding ``le``).
    """
    bucket_samples = [
        s
        for s in samples
        if s.name == f"{family_name}_bucket"
        and all(s.labels.get(k) == v for k, v in label_filter.items())
    ]
    buckets: list[tuple[float, float]] = []
    for s in bucket_samples:
        le_raw = s.labels.get("le", "")
        le = float("inf") if le_raw == "+Inf" else float(le_raw)
        buckets.append((le, float(s.value)))
    buckets.sort(key=lambda x: x[0])
    return buckets


def fetch_metrics_text(
    metrics_url: str | None, fixture_path: pathlib.Path | None
) -> str:
    """Return the Prometheus exposition text. Reads ``fixture_path``
    if given (``--dry-run`` path); otherwise fetches ``metrics_url``.

    Raises:
        FileNotFoundError: when fixture path is given and missing.
        urllib.error.URLError: on network failure (caller logs +
            returns non-zero).
    """
    if fixture_path is not None:
        return fixture_path.read_text(encoding="utf-8")
    if metrics_url is None:
        raise ValueError(
            "either --metrics-url or --fixture must be provided"
        )
    with urllib.request.urlopen(metrics_url, timeout=5) as r:
        return r.read().decode("utf-8")


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _families_by_name(metrics_text: str) -> dict[str, object]:
    return {f.name: f for f in text_string_to_metric_families(metrics_text)}


def _request_counts(family) -> dict[str, dict[str, int]]:
    """Aggregate ``arxmcp_request_total{tool, status}`` into
    ``{tool: {"ok": N, "error": N}}``."""
    out: dict[str, dict[str, int]] = {t: {"ok": 0, "error": 0} for t in TOOLS}
    if family is None:
        return out
    for sample in family.samples:
        if sample.name != "arxmcp_request_total":
            continue
        tool = sample.labels.get("tool", "")
        status = sample.labels.get("status", "")
        if tool in out and status in ("ok", "error"):
            out[tool][status] = int(sample.value)
    return out


def _latency_quantiles(family) -> dict[str, dict[str, float]]:
    """Compute P50/P95/P99 per-tool from the histogram family.
    Tools with zero observations render as ``nan`` quantiles
    (the markdown rendering replaces ``nan`` with ``n/a``)."""
    out: dict[str, dict[str, float]] = {}
    if family is None:
        return {
            t: {"p50": float("nan"), "p95": float("nan"), "p99": float("nan")}
            for t in TOOLS
        }
    for tool in TOOLS:
        buckets = _collect_histogram_buckets(
            list(family.samples),
            "arxmcp_request_latency_seconds",
            {"tool": tool},
        )
        out[tool] = {
            "p50": histogram_quantile(0.50, buckets),
            "p95": histogram_quantile(0.95, buckets),
            "p99": histogram_quantile(0.99, buckets),
        }
    return out


def _cache_hit_rates(
    lookups_family, hits_family
) -> dict[str, dict[str, float | int]]:
    """Return ``{tier: {"lookups": N, "hits": N, "rate": float}}``."""
    lookups = {t: 0 for t in CACHE_TIERS}
    hits = {t: 0 for t in CACHE_TIERS}
    if lookups_family is not None:
        for s in lookups_family.samples:
            if s.name == "arxmcp_cache_lookups_total":
                t = s.labels.get("tier", "")
                if t in lookups:
                    lookups[t] = int(s.value)
    if hits_family is not None:
        for s in hits_family.samples:
            if s.name == "arxmcp_cache_hits_total":
                t = s.labels.get("tier", "")
                if t in hits:
                    hits[t] = int(s.value)
    out: dict[str, dict[str, float | int]] = {}
    for tier in CACHE_TIERS:
        l_ = lookups[tier]
        h_ = hits[tier]
        rate = (h_ / l_) if l_ > 0 else float("nan")
        out[tier] = {"lookups": l_, "hits": h_, "rate": rate}
    return out


def _embed_rerank_counts(family) -> dict[str, int]:
    """Return ``{"ok": N, "error": N}`` for an embed/rerank counter
    family (single-model assumption)."""
    out = {"ok": 0, "error": 0}
    if family is None:
        return out
    for s in family.samples:
        if s.name in (
            "arxmcp_embed_calls_total",
            "arxmcp_rerank_calls_total",
        ):
            outcome = s.labels.get("outcome", "")
            if outcome in out:
                out[outcome] += int(s.value)
    return out


def _fmt_q(v: float) -> str:
    """Render a quantile in ms with ``n/a`` for ``nan``."""
    if v != v:  # nan
        return "n/a"
    return f"{v * 1000:.1f}ms"


def _fmt_pct(v: float) -> str:
    if v != v:
        return "n/a"
    return f"{v * 100:.1f}%"


def render_report(
    metrics_text: str, now: datetime.datetime
) -> str:
    """Render the markdown report. ``now`` should be timezone-aware
    (UTC); tests inject a fixed value for determinism."""
    fams = _families_by_name(metrics_text)

    requests = _request_counts(fams.get("arxmcp_request"))
    latencies = _latency_quantiles(fams.get("arxmcp_request_latency_seconds"))
    cache = _cache_hit_rates(
        fams.get("arxmcp_cache_lookups"),
        fams.get("arxmcp_cache_hits"),
    )
    embed = _embed_rerank_counts(fams.get("arxmcp_embed_calls"))
    rerank = _embed_rerank_counts(fams.get("arxmcp_rerank_calls"))

    total_requests = sum(r["ok"] + r["error"] for r in requests.values())
    total_errors = sum(r["error"] for r in requests.values())
    error_rate = (total_errors / total_requests) if total_requests > 0 else float("nan")

    lines: list[str] = []
    lines.append(f"# arXMCP daily ops report — {now.date().isoformat()}")
    lines.append("")
    lines.append(f"_Generated {now.isoformat()} from `/metrics`._")
    lines.append("")

    # --- Requests served --------------------------------------------------
    lines.append("## Requests served")
    lines.append("")
    lines.append("| Tool | OK | Error | Total |")
    lines.append("|---|---:|---:|---:|")
    for tool in TOOLS:
        r = requests[tool]
        lines.append(
            f"| `{tool}` | {r['ok']} | {r['error']} | {r['ok'] + r['error']} |"
        )
    lines.append(
        f"| **All** | **{total_requests - total_errors}** | "
        f"**{total_errors}** | **{total_requests}** |"
    )
    lines.append("")
    lines.append(f"**Overall error rate:** {_fmt_pct(error_rate)}")
    lines.append("")

    # --- Latency ----------------------------------------------------------
    lines.append("## Latency per tool (P50 / P95 / P99)")
    lines.append("")
    lines.append("| Tool | P50 | P95 | P99 |")
    lines.append("|---|---:|---:|---:|")
    for tool in TOOLS:
        q = latencies[tool]
        lines.append(
            f"| `{tool}` | {_fmt_q(q['p50'])} | "
            f"{_fmt_q(q['p95'])} | {_fmt_q(q['p99'])} |"
        )
    lines.append("")

    # --- Cache hit rates --------------------------------------------------
    lines.append("## Cache hit rates per tier")
    lines.append("")
    lines.append("| Tier | Lookups | Hits | Hit rate |")
    lines.append("|---|---:|---:|---:|")
    for tier in CACHE_TIERS:
        c = cache[tier]
        lines.append(
            f"| tier{tier} | {c['lookups']} | {c['hits']} | "
            f"{_fmt_pct(c['rate'] if isinstance(c['rate'], float) else float(c['rate']))} |"
        )
    lines.append("")

    # --- Embed + rerank ---------------------------------------------------
    lines.append("## Embedder + reranker")
    lines.append("")
    lines.append("| Stage | OK | Error |")
    lines.append("|---|---:|---:|")
    lines.append(f"| BGE-M3 embed | {embed['ok']} | {embed['error']} |")
    lines.append(
        f"| BGE-reranker-v2-m3 rerank | {rerank['ok']} | {rerank['error']} |"
    )
    lines.append("")

    # --- Corpus integrity (corpus-integrity-observability-e2 / CAND-9) ----
    # Reconcile the corpus-version.json marker chunk_count against the live
    # table count — both startup-cached gauges shipped by m2. A persistent gap
    # is the silent ~100x divergence bug class made human-visible at daily
    # cadence. Gauges are startup-cached (stale by design; restart to refresh).
    marker_ct = _sentinel_gauge(fams, "arxmcp_corpus_chunk_count_marker")
    actual_ct = _sentinel_gauge(fams, "arxmcp_corpus_chunk_count_actual")
    corpus_ver = _sentinel_gauge(fams, "arxmcp_corpus_version")

    def _count_cell(v: float) -> str:
        # NaN (gauge absent — server down / cold corpus) or a negative value
        # (-1 = m2 FM-2 count_rows() failed at startup) → "n/a"; never render a
        # bogus "-1".
        if v != v or v < 0:
            return "n/a"
        return str(int(v))

    diverged = (
        marker_ct == marker_ct  # not NaN
        and actual_ct == actual_ct  # not NaN
        and marker_ct >= 0
        and actual_ct >= 0
        and int(marker_ct) != int(actual_ct)
    )
    lines.append("## Corpus integrity")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---:|")
    lines.append(f"| corpus_version | {_count_cell(corpus_ver)} |")
    lines.append(f"| marker chunk_count | {_count_cell(marker_ct)} |")
    lines.append(f"| actual chunk_count | {_count_cell(actual_ct)} |")
    lines.append(f"| Status | {'**[DIVERGED]**' if diverged else 'ok'} |")
    lines.append("")

    # --- Ingestion throughput (TODO — metrics not yet emitted) -----------
    lines.append("## Ingestion throughput")
    lines.append("")
    lines.append(
        "_Papers ingested + chunks written are not yet exposed via "
        "`/metrics`; the families `arxmcp_ingest_papers_processed_total` "
        "and `arxmcp_ingest_chunks_written_total` are named in note 08 "
        "but no emitter exists yet. See `var/arxmcp/ops/delta-status.json` "
        "for the most-recent delta run summary, or "
        "`docs/ops/delta-loop.md` for the operator workflow._"
    )
    lines.append("")

    # --- Parser failures (read alongside the metrics scrape) -------------
    lines.append("## Parser failures (last 24h)")
    lines.append("")
    lines.append(
        "_See the weekly review report at "
        "`var/arxmcp/ops/reports/parser-failures-<YYYY>-W<NN>.md` "
        "(generated by `tools/parser_failures_report.py`) for the "
        "human triage queue. Daily parser-failure counts can be "
        "computed from `var/arxmcp/ops/parser-failures/*.log` "
        "directly._"
    )
    lines.append("")

    # --- Sentinels --------------------------------------------------------
    drift = _sentinel_gauge(fams, "arxmcp_latexml_drift_fixtures")
    quarantine = _sentinel_gauge(fams, "arxmcp_eval_quarantine_active")
    delta_to = _sentinel_gauge(fams, "arxmcp_delta_timeout_active")
    backup_age = _backup_age_seconds(fams)
    backup_state = _backup_status_active_state(fams)
    lines.append("## Sentinels")
    lines.append("")
    lines.append("| Sentinel | Value |")
    lines.append("|---|---:|")
    lines.append(
        f"| LaTeXML drift fixtures | "
        f"{0 if drift != drift else int(drift)} |"
    )
    lines.append(
        f"| Eval quarantine active | "
        f"{'yes' if quarantine == 1.0 else 'no'} |"
    )
    lines.append(
        f"| Delta-loop timeout active | "
        f"{'yes' if delta_to == 1.0 else 'no'} |"
    )
    if backup_age != backup_age:
        age_str = "no backup recorded"
    elif backup_age < 0:
        age_str = "_clock skew_"
    else:
        h = int(backup_age // 3600)
        age_str = f"{h}h ago"
    # F3 rectification — render the backup state alongside the
    # age so a "failed" status is not masked by a recently-updated
    # finished_at timestamp.
    backup_str = (
        age_str if backup_state is None else f"{age_str} ({backup_state})"
    )
    lines.append(f"| Backup last success | {backup_str} |")
    lines.append("")

    return "\n".join(lines) + "\n"


def _sentinel_gauge(fams: dict[str, object], name: str) -> float:
    """Return the first sample value for ``name`` or ``nan``."""
    fam = fams.get(name)
    if fam is None:
        return float("nan")
    for s in fam.samples:
        if s.name == name:
            return float(s.value)
    return float("nan")


def _backup_age_seconds(fams: dict[str, object]) -> float:
    """Return ``now - arxmcp_backup_last_success_timestamp_seconds``
    in seconds. ``nan`` if the gauge is 0 or absent."""
    ts = _sentinel_gauge(fams, "arxmcp_backup_last_success_timestamp_seconds")
    if ts != ts or ts == 0.0:
        return float("nan")
    return datetime.datetime.now(datetime.UTC).timestamp() - ts


def _backup_status_active_state(fams: dict[str, object]) -> str | None:
    """Return the active ``arxmcp_backup_status{state}`` (the one
    cell with value 1.0), or ``None`` if no state is active.

    F3 rectification (E14_S04 adversary critique): the report
    previously rendered only `arxmcp_backup_last_success_timestamp_seconds`,
    so a backup that updated `finished_at` despite failing showed
    as "Xh ago" and masked the failed status. Surface the
    state cell so the operator sees ``failed`` / ``running`` /
    ``unknown`` alongside the age.
    """
    fam = fams.get("arxmcp_backup_status")
    if fam is None:
        return None
    for sample in fam.samples:
        if sample.name == "arxmcp_backup_status" and float(sample.value) == 1.0:
            return sample.labels.get("state")
    return None


# ---------------------------------------------------------------------------
# Optional email delivery
# ---------------------------------------------------------------------------


def maybe_email(subject: str, body: str) -> None:
    """Send ``body`` via SMTP when ``MAIL_TO``, ``MAIL_FROM``,
    ``SMTP_HOST`` are all set. Logs INFO either way so operators
    can see WHY their email didn't arrive (per E14_S04 synthesis
    D8).

    Optional env vars: ``SMTP_PORT`` (default 25),
    ``SMTP_STARTTLS=1`` (opt-in STARTTLS), ``SMTP_USER`` /
    ``SMTP_PASS`` (opt-in auth).
    """
    cfg = {
        k: os.environ.get(k)
        for k in ("MAIL_TO", "MAIL_FROM", "SMTP_HOST")
    }
    if not all(cfg.values()):
        missing = ",".join(k for k, v in cfg.items() if not v)
        logger.info("email disabled: missing env var(s) %s", missing)
        return

    msg = EmailMessage()
    msg["From"] = cfg["MAIL_FROM"]
    msg["To"] = cfg["MAIL_TO"]
    msg["Subject"] = subject
    msg.set_content(body)

    port = int(os.environ.get("SMTP_PORT", "25"))
    starttls = os.environ.get("SMTP_STARTTLS") == "1"
    smtp_user = os.environ.get("SMTP_USER")
    logger.info(
        "email enabled: sending to %s via %s:%d (starttls=%s)",
        cfg["MAIL_TO"], cfg["SMTP_HOST"], port, starttls,
    )
    # F2 rectification (E14_S04 adversary critique): SMTP failures
    # must NOT bubble up and turn a successful daily-report write
    # into a journalctl-failed cron job. The report on disk is the
    # durable artifact; email is opt-in notification. Log ERROR
    # and continue. ``smtplib.SMTPException`` is the umbrella for
    # the specific delivery failures (recipient refused, auth
    # refused, server-disconnect); ``OSError`` covers network-level
    # failures (DNS, connection-refused) before the SMTP handshake.
    try:
        with smtplib.SMTP(cfg["SMTP_HOST"], port, timeout=10) as s:
            if starttls:
                s.starttls()
            if smtp_user:
                s.login(smtp_user, os.environ.get("SMTP_PASS", ""))
            s.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        logger.error(
            "email delivery failed (%s); the on-disk report at "
            "var/arxmcp/ops/daily-reports/<date>.md is the durable "
            "artifact and is unaffected.",
            exc,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Daily ops metrics report (E14_S04). Scrapes /metrics, "
            "renders markdown to var/arxmcp/ops/daily-reports/"
            "<YYYY-MM-DD>.md, optionally emails."
        )
    )
    p.add_argument(
        "--metrics-url",
        default=DEFAULT_METRICS_URL,
        help=f"server /metrics endpoint (default: {DEFAULT_METRICS_URL})",
    )
    p.add_argument(
        "--fixture",
        type=pathlib.Path,
        default=None,
        help="read /metrics text from a file instead of the server; "
             "useful for --dry-run + tests",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print markdown to stdout; do not write file, do not email",
    )
    p.add_argument(
        "--out-dir",
        type=pathlib.Path,
        default=DEFAULT_OUT_DIR,
        help=f"output directory (default: {DEFAULT_OUT_DIR})",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    args = _parse_args(argv)
    try:
        metrics_text = fetch_metrics_text(
            None if args.fixture else args.metrics_url,
            args.fixture,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: fixture not found: {exc}", file=sys.stderr)
        return 2
    except urllib.error.URLError as exc:
        print(
            f"ERROR: failed to fetch {args.metrics_url}: {exc}",
            file=sys.stderr,
        )
        return 2

    now = datetime.datetime.now(datetime.UTC)
    body = render_report(metrics_text, now)

    if args.dry_run:
        sys.stdout.write(body)
        return 0

    out_path = args.out_dir / f"{now.date().isoformat()}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    logger.info("wrote daily report to %s", out_path)
    maybe_email(f"arXMCP daily ops report — {now.date()}", body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
