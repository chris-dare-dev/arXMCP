"""OAI-PMH delta harvester (E11_S02).

Nightly cron-driven module that harvests the previous day's
new/updated papers from arXiv's OAI-PMH endpoint and feeds them
into the per-paper pipeline (:func:`ingest.bulk_ingest.ingest_one_paper`).

**Why this lives next to `bulk_ingest`:** the two share the
per-paper pipeline entry point. E11_S01 ships the orchestrator
(:func:`ingest_one_paper`) with five rectifier fixes baked in
(embed-status check, parsed_dir decoupling, math-signal boundary,
redirect pinning). This delta loop **reuses it unchanged** rather
than cloning the per-paper logic — every E11_S01 fix flows
through transparently.

**Staging-path discipline (inherited from E11_S01).** The delta
loop writes to ``var/arxmcp/index/lancedb-staging/`` via the
same staging-path parameter. The active ``corpus-version.json``
is NOT advanced; activation is E11_S05's atomic cutover.

**Scope at v1 (per research synthesis D-items):**

- D1-D2: This module owns OAI-PMH harvest + per-paper feed;
  ``ingest_one_paper`` owns parse + chunk + embed + write.
- D4: HTTPS endpoint ``https://oaipmh.arxiv.org/oai`` (arXiv
  migrated from ``http://export.arxiv.org/oai2`` in March 2025).
- D5: Four per-set ListRecords calls — ``math:math:AG``,
  ``math:math:NT``, ``physics:math-ph``, ``physics:hep-th``.
- D6: State file persists token AND harvest date so a cross-day
  crash detects expired tokens.
- D8: 90-minute budget breach surfaces as ERROR log + sentinel
  flag file at ``var/arxmcp/ops/delta-timeout.flag``.
- D11: NO filesystem touch file. The active marker is not
  touched; manual restart is the documented mechanism per
  ``.claude/notes/06-mcp-server-design.md:346-354``.
- D12: ``<header status="deleted">`` records are logged and
  skipped (no chunk/embed; existing chunks left alone).
- D13: ``papers``-table metadata upsert is deferred (no
  ``papers`` table populated at v1 of the project).

References:

- OAI-PMH 2.0 spec — https://www.openarchives.org/OAI/openarchivesprotocol.html
- arXiv Identify — ``https://oaipmh.arxiv.org/oai?verb=Identify``
  (day granularity; persistent deletes; ``arXivRaw`` metadata prefix)
- arXiv TOS — https://info.arxiv.org/help/api/tou.html
  ("no more than one request every three seconds")
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from ingest.ar5iv_fetch import DEFAULT_AR5IV_CACHE_DIR, DEFAULT_PARSED_DIR
from ingest.bulk_ingest import (
    DEFAULT_LANCEDB_STAGING_PATH,
    PaperOutcome,
    _log_parser_failure,
    ingest_one_paper,
)
from ingest.identifiers import is_valid_paper_id

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

#: OAI-PMH endpoint. arXiv migrated from
#: ``http://export.arxiv.org/oai2`` to ``https://oaipmh.arxiv.org/oai``
#: in March 2025. The legacy URL still works but is HTTP-only.
OAI_PMH_ENDPOINT: str = "https://oaipmh.arxiv.org/oai"

#: arXiv TOS politeness contract — applies to every request hitting
#: an ``arxiv.org`` host (OAI-PMH page fetches; per-paper
#: ``/e-print/`` calls live inside ``ingest_one_paper``).
POLITENESS_SLEEP_SECONDS: float = 3.0

#: Per-request timeout. OAI-PMH responses are XML batches that
#: can be tens of MB; 30s is generous for slow links but short
#: enough that a stuck connection doesn't poison the run.
OAI_PMH_TIMEOUT_SECONDS: float = 30.0

#: Target sets — verified live against
#: ``https://oaipmh.arxiv.org/oai?verb=ListSets`` (synthesis D5).
DEFAULT_SETS: tuple[str, ...] = (
    "math:math:AG",
    "math:math:NT",
    "physics:math-ph",
    "physics:hep-th",
)

#: Metadata format. ``arXivRaw`` includes ``<versions>``,
#: ``<categories>``, ``<license>``, ``<journal-ref>``; ``arXiv``
#: omits version history. Use ``arXivRaw`` (synthesis D5).
METADATA_PREFIX: str = "arXivRaw"

#: Default state file location. Persists ``last_harvest_date`` and
#: ``last_resumption_token`` so a mid-harvest crash can resume.
DEFAULT_STATE_PATH: Path = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "oai-pmh-state.json"
)

#: Default delta log location.
DEFAULT_DELTA_LOG_PATH: Path = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "oai-delta.log"
)

#: Default parser-failures JSONL location (separate from the
#: bulk-ingest path so each channel has its own audit trail).
DEFAULT_DELTA_PARSER_FAILURES_PATH: Path = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "parser-failures" / "delta.jsonl"
)

#: Sentinel flag file written when a run exceeds the 90-minute
#: budget (synthesis D8). Mirrors the E10_S04 drift-detector
#: pattern (``var/arxmcp/ops/drift-detected.flag``).
DEFAULT_TIMEOUT_FLAG_PATH: Path = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "delta-timeout.flag"
)

#: 90-minute budget in seconds. Synthesis §7 documents this is
#: 4-6× headroom over typical 15-20 min runs; the alert is the
#: signal, not a hard timeout.
DEFAULT_BUDGET_SECONDS: float = 90 * 60.0

#: OAI-PMH XML namespaces. ``arXivRaw`` records sit under the
#: ``http://arxiv.org/OAI/arXivRaw/`` namespace.
_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "raw": "http://arxiv.org/OAI/arXivRaw/",
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class HarvestedRecord:
    """One OAI-PMH record after parsing."""

    paper_id: str
    datestamp: str           # ISO 8601 date from the OAI header
    set_spec: str            # which `set` this record came from
    deleted: bool = False    # `<header status="deleted">`
    categories: list[str] = field(default_factory=list)


@dataclass
class DeltaSummary:
    """Aggregate of one delta-loop run."""

    sets_harvested: list[str] = field(default_factory=list)
    records_total: int = 0
    records_deleted: int = 0
    records_ingested: int = 0
    records_failed: int = 0
    pages_fetched: int = 0
    elapsed_seconds: float = 0.0
    budget_breached: bool = False


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------


def _read_state(path: Path) -> dict:
    """Load the delta state file; missing-file returns empty state."""
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"oai-pmh-state.json at {path} is malformed: {exc}. "
            f"Inspect and delete to re-bootstrap from yesterday."
        ) from exc


def _write_state(path: Path, state: dict) -> None:
    """Persist state. Atomic via temp + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _today_utc_iso() -> str:
    """``YYYY-MM-DD`` for today in UTC. OAI-PMH is day-granularity."""
    return _dt.datetime.now(_dt.UTC).date().isoformat()


def _yesterday_utc_iso() -> str:
    """``YYYY-MM-DD`` for yesterday in UTC."""
    today = _dt.datetime.now(_dt.UTC).date()
    return (today - _dt.timedelta(days=1)).isoformat()


def _resolve_resume(state: dict) -> tuple[str, str | None]:
    """Decide the from-date + token from the persisted state.

    Returns ``(from_date, token_or_none)``. The token is honored
    only when ``last_harvest_date == today`` (synthesis D6 — arXiv
    tokens expire daily).
    """
    today = _today_utc_iso()
    last_date = state.get("last_harvest_date")
    last_token = state.get("last_resumption_token")
    if last_token and last_date == today:
        return last_date, last_token
    if last_date:
        # Resume from the date we were mid-harvest on; the token
        # itself is stale and would 4xx if reused.
        return last_date, None
    # First run: harvest yesterday's window.
    return _yesterday_utc_iso(), None


# ---------------------------------------------------------------------------
# OAI-PMH HTTP fetch
# ---------------------------------------------------------------------------


def _fetch_page(
    endpoint: str,
    params: dict[str, str],
    *,
    timeout_seconds: float,
    user_agent: str,
) -> bytes:
    """One ``ListRecords`` page fetch. Raises on non-200."""
    url = f"{endpoint}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url, headers={"User-Agent": user_agent, "Accept": "application/xml"}
    )
    with urllib.request.urlopen(  # noqa: S310 — pinned arxiv host
        request, timeout=timeout_seconds
    ) as response:
        status = response.status
        body = response.read()
        # OAI-PMH spec: 503 with Retry-After is the rate-limit
        # signal. We escalate non-200 to the caller; arXiv's
        # 3-second TOS sleep is enforced separately around the
        # fetch call.
        if status != 200:
            raise RuntimeError(
                f"OAI-PMH unexpected HTTP {status} for {url}"
            )
    return body


def _politeness_sleep_since(start_monotonic: float) -> None:
    """Block so the next request is ≥ ``POLITENESS_SLEEP_SECONDS``
    after ``start_monotonic``. Mirrors
    :func:`tools.arxiv_fetch.politeness_sleep`."""
    elapsed = time.monotonic() - start_monotonic
    if elapsed < POLITENESS_SLEEP_SECONDS:
        time.sleep(POLITENESS_SLEEP_SECONDS - elapsed)


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------


def _parse_listrecords(
    body: bytes, *, set_spec: str
) -> tuple[list[HarvestedRecord], str | None]:
    """Parse one ``ListRecords`` response.

    Returns ``(records, resumption_token)``. Per OAI-PMH spec, an
    EMPTY ``<resumptionToken/>`` element signals end-of-list — we
    return ``None`` in that case. Absent token element also means
    end-of-list (last page fit in one response).
    """
    root = ET.fromstring(body)
    # Surface OAI-PMH error responses cleanly.
    error_el = root.find("oai:error", _NS)
    if error_el is not None:
        code = error_el.get("code", "unknown")
        msg = (error_el.text or "").strip()
        raise RuntimeError(f"OAI-PMH error code={code}: {msg}")

    records: list[HarvestedRecord] = []
    list_records = root.find("oai:ListRecords", _NS)
    if list_records is None:
        return [], None

    for rec_el in list_records.findall("oai:record", _NS):
        header = rec_el.find("oai:header", _NS)
        if header is None:
            continue
        ident = header.find("oai:identifier", _NS)
        datestamp = header.find("oai:datestamp", _NS)
        ident_text = ident.text if ident is not None else None
        datestamp_text = datestamp.text if datestamp is not None else ""
        if not ident_text:
            continue
        # arXiv identifier is `oai:arXiv.org:<paper_id>`. Strip the
        # prefix; keep the canonical arxiv id.
        prefix = "oai:arXiv.org:"
        paper_id = (
            ident_text[len(prefix):]
            if ident_text.startswith(prefix)
            else ident_text
        )
        if not is_valid_paper_id(paper_id):
            logger.warning(
                "oai_delta: skipping unexpected identifier %r",
                ident_text,
            )
            continue
        deleted = header.get("status") == "deleted"
        categories: list[str] = []
        if not deleted:
            metadata = rec_el.find("oai:metadata", _NS)
            if metadata is not None:
                raw = metadata.find("raw:arXivRaw", _NS)
                if raw is not None:
                    cats = raw.find("raw:categories", _NS)
                    if cats is not None and cats.text:
                        categories = cats.text.split()
        records.append(
            HarvestedRecord(
                paper_id=paper_id,
                datestamp=datestamp_text,
                set_spec=set_spec,
                deleted=deleted,
                categories=categories,
            )
        )

    token_el = list_records.find("oai:resumptionToken", _NS)
    if token_el is None:
        return records, None
    # Empty token text signals end-of-list per spec.
    token_text = (token_el.text or "").strip()
    return records, (token_text or None)


# ---------------------------------------------------------------------------
# Harvest loop
# ---------------------------------------------------------------------------


def harvest_set(
    set_spec: str,
    *,
    from_date: str,
    until_date: str,
    endpoint: str = OAI_PMH_ENDPOINT,
    timeout_seconds: float = OAI_PMH_TIMEOUT_SECONDS,
    user_agent: str = "arxmcp-oai-delta/0.1",
    state_path: Path = DEFAULT_STATE_PATH,
    resume_token: str | None = None,
    fetch_page=None,
    sleep_between_pages=None,
) -> tuple[list[HarvestedRecord], int]:
    """Walk every page of a single ``set`` between ``from_date`` and
    ``until_date``. Returns ``(records, pages_fetched)``.

    State is persisted after every page so a crash can resume from
    the last token. The token is opaque to us; per OAI-PMH spec the
    resume-call carries only ``verb=ListRecords&resumptionToken=<t>``
    (no other params allowed).
    """
    if fetch_page is None:
        fetch_page = _fetch_page
    if sleep_between_pages is None:
        sleep_between_pages = _politeness_sleep_since
    records: list[HarvestedRecord] = []
    pages = 0
    token = resume_token
    while True:
        if token:
            params = {"verb": "ListRecords", "resumptionToken": token}
        else:
            params = {
                "verb": "ListRecords",
                "metadataPrefix": METADATA_PREFIX,
                "from": from_date,
                "until": until_date,
                "set": set_spec,
            }
        page_started = time.monotonic()
        body = fetch_page(
            endpoint,
            params,
            timeout_seconds=timeout_seconds,
            user_agent=user_agent,
        )
        pages += 1
        page_records, next_token = _parse_listrecords(
            body, set_spec=set_spec
        )
        records.extend(page_records)
        # Persist in-flight token after each page. Closes the
        # synthesis D6 contract: a crash mid-harvest can resume.
        state = _read_state(state_path)
        state["last_resumption_token"] = next_token
        state["last_harvest_date"] = _today_utc_iso()
        _write_state(state_path, state)
        token = next_token
        if token is None:
            break
        sleep_between_pages(page_started)
    return records, pages


# ---------------------------------------------------------------------------
# Per-paper feed
# ---------------------------------------------------------------------------


def _feed_record_to_pipeline(
    record: HarvestedRecord,
    *,
    lancedb_staging_path: Path,
    ar5iv_cache_dir: Path,
    parsed_dir: Path,
    failures_path: Path,
) -> PaperOutcome | None:
    """Hand one harvested record off to ``ingest_one_paper``.

    Withdrawn records (``deleted=True``) are logged and skipped per
    synthesis D12 — existing chunks remain in place.
    """
    if record.deleted:
        logger.info(
            "oai_delta: paper=%s withdrawn (status=deleted); skipping chunk/embed",
            record.paper_id,
        )
        return None
    outcome = ingest_one_paper(
        record.paper_id,
        lancedb_staging_path=lancedb_staging_path,
        ar5iv_cache_dir=ar5iv_cache_dir,
        parsed_dir=parsed_dir,
    )
    if outcome.chunks_written == 0:
        _log_parser_failure(outcome, failures_path)
    return outcome


# ---------------------------------------------------------------------------
# Budget alert
# ---------------------------------------------------------------------------


def _emit_budget_breach(
    flag_path: Path, elapsed_seconds: float, budget_seconds: float
) -> None:
    """Write the timeout sentinel + ERROR log. Mirrors the
    drift-detector pattern (synthesis D8)."""
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    flag_path.write_text(
        json.dumps(
            {
                "elapsed_seconds": round(elapsed_seconds, 1),
                "budget_seconds": budget_seconds,
                "ts": _dt.datetime.now(_dt.UTC).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    logger.error(
        "oai_delta: run exceeded %.0fs budget (elapsed=%.1fs); "
        "wrote sentinel to %s",
        budget_seconds, elapsed_seconds, flag_path,
    )


def _clear_budget_flag(flag_path: Path) -> None:
    """Remove the sentinel after a successful in-budget run."""
    if flag_path.is_file():
        flag_path.unlink()


# ---------------------------------------------------------------------------
# Top-level run
# ---------------------------------------------------------------------------


def run_delta(
    *,
    sets: tuple[str, ...] = DEFAULT_SETS,
    from_date: str | None = None,
    until_date: str | None = None,
    endpoint: str = OAI_PMH_ENDPOINT,
    lancedb_staging_path: Path = DEFAULT_LANCEDB_STAGING_PATH,
    ar5iv_cache_dir: Path = DEFAULT_AR5IV_CACHE_DIR,
    parsed_dir: Path = DEFAULT_PARSED_DIR,
    state_path: Path = DEFAULT_STATE_PATH,
    log_path: Path = DEFAULT_DELTA_LOG_PATH,
    failures_path: Path = DEFAULT_DELTA_PARSER_FAILURES_PATH,
    timeout_flag_path: Path = DEFAULT_TIMEOUT_FLAG_PATH,
    budget_seconds: float = DEFAULT_BUDGET_SECONDS,
    dry_run: bool = False,
    fetch_page=None,
    sleep_between_pages=None,
) -> DeltaSummary:
    """Run one delta harvest. Returns aggregate summary.

    The active ``corpus-version.json`` is NOT advanced — writes go
    to the staging LanceDB path. See synthesis D3 + design note
    ``.claude/notes/06-mcp-server-design.md:346-354`` for why.

    ``fetch_page`` and ``sleep_between_pages`` default to the
    module-level helpers; they are resolved at CALL time (not
    def-time) so test patches against ``ingest.oai_delta._fetch_page``
    are honored.
    """
    # Late-bind defaults so test patches of the module-level
    # helpers take effect.
    if fetch_page is None:
        fetch_page = _fetch_page
    if sleep_between_pages is None:
        sleep_between_pages = _politeness_sleep_since
    started = time.monotonic()
    state = _read_state(state_path)
    resume_date, resume_token = _resolve_resume(state)
    # Default window: harvest yesterday → today, OR the resume date
    # the state file points us at.
    effective_from = from_date or resume_date
    effective_until = until_date or _yesterday_utc_iso()

    summary = DeltaSummary()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    all_records: list[HarvestedRecord] = []
    for set_spec in sets:
        # Only the first set inherits a saved resumption token; the
        # token is per-set in arXiv's OAI-PMH and we don't try to
        # match a token to a set after a crash (the safer recovery
        # is to re-harvest the full window).
        token = resume_token if set_spec == sets[0] else None
        records, pages = harvest_set(
            set_spec,
            from_date=effective_from,
            until_date=effective_until,
            endpoint=endpoint,
            state_path=state_path,
            resume_token=token,
            fetch_page=fetch_page,
            sleep_between_pages=sleep_between_pages,
        )
        all_records.extend(records)
        summary.sets_harvested.append(set_spec)
        summary.pages_fetched += pages
        summary.records_total += len(records)
        # Discard the in-flight token between sets — each set starts
        # fresh from `from`/`until`.
        resume_token = None

    if dry_run:
        for record in all_records:
            tag = "DELETED" if record.deleted else "WOULD_INGEST"
            print(f"{record.paper_id}\t{record.set_spec}\t{tag}")
        # Don't touch the state file on dry-run.
        return summary

    for record in all_records:
        if record.deleted:
            summary.records_deleted += 1
            _feed_record_to_pipeline(
                record,
                lancedb_staging_path=lancedb_staging_path,
                ar5iv_cache_dir=ar5iv_cache_dir,
                parsed_dir=parsed_dir,
                failures_path=failures_path,
            )
            continue
        outcome = _feed_record_to_pipeline(
            record,
            lancedb_staging_path=lancedb_staging_path,
            ar5iv_cache_dir=ar5iv_cache_dir,
            parsed_dir=parsed_dir,
            failures_path=failures_path,
        )
        if outcome is None:
            continue
        if outcome.chunks_written > 0:
            summary.records_ingested += 1
        else:
            summary.records_failed += 1

    summary.elapsed_seconds = time.monotonic() - started
    summary.budget_breached = summary.elapsed_seconds > budget_seconds
    if summary.budget_breached:
        _emit_budget_breach(
            timeout_flag_path, summary.elapsed_seconds, budget_seconds
        )
    else:
        _clear_budget_flag(timeout_flag_path)

    # Successful completion: clear the in-flight token, persist the
    # successful-run summary, advance last_harvest_date to today.
    final_state = {
        "last_harvest_date": _today_utc_iso(),
        "last_resumption_token": None,
        "last_successful_run_utc": _dt.datetime.now(
            _dt.UTC
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_run_paper_count": summary.records_total,
        "last_run_duration_seconds": round(summary.elapsed_seconds, 1),
    }
    _write_state(state_path, final_state)

    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="arXMCP OAI-PMH delta loop (E11_S02).",
    )
    parser.add_argument(
        "--from",
        dest="from_date",
        default=None,
        help=(
            "Harvest window start (YYYY-MM-DD). Default: yesterday, "
            "or the state-file's last_harvest_date on resume."
        ),
    )
    parser.add_argument(
        "--until",
        dest="until_date",
        default=None,
        help="Harvest window end (YYYY-MM-DD). Default: yesterday.",
    )
    parser.add_argument(
        "--lancedb-staging-path",
        default=str(DEFAULT_LANCEDB_STAGING_PATH),
        type=Path,
        help=(
            f"Staging LanceDB dataset (default: "
            f"{DEFAULT_LANCEDB_STAGING_PATH}). The active dataset is "
            f"NOT touched."
        ),
    )
    parser.add_argument(
        "--state-file",
        default=str(DEFAULT_STATE_PATH),
        type=Path,
        help=f"State file path (default: {DEFAULT_STATE_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Harvest the OAI-PMH metadata but skip the per-paper "
            "pipeline. Prints one line per harvested record."
        ),
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    summary = run_delta(
        from_date=args.from_date,
        until_date=args.until_date,
        lancedb_staging_path=args.lancedb_staging_path,
        state_path=args.state_file,
        dry_run=args.dry_run,
    )
    rate_token = (
        ""
        if args.dry_run
        else f"failed={summary.records_failed} "
    )
    print(
        f"sets={len(summary.sets_harvested)} "
        f"pages={summary.pages_fetched} "
        f"total={summary.records_total} "
        f"ingested={summary.records_ingested} "
        f"deleted={summary.records_deleted} "
        f"{rate_token}"
        f"elapsed={summary.elapsed_seconds:.1f}s "
        f"budget_breached={summary.budget_breached}"
    )
    # Non-zero exit on budget breach OR any failures — cron mailer +
    # systemd-timer status pick up the signal.
    return (
        1
        if (summary.budget_breached or summary.records_failed > 0)
        else 0
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_cli(sys.argv[1:]))


__all__ = [
    "DEFAULT_BUDGET_SECONDS",
    "DEFAULT_DELTA_LOG_PATH",
    "DEFAULT_DELTA_PARSER_FAILURES_PATH",
    "DEFAULT_SETS",
    "DEFAULT_STATE_PATH",
    "DEFAULT_TIMEOUT_FLAG_PATH",
    "DeltaSummary",
    "HarvestedRecord",
    "METADATA_PREFIX",
    "OAI_PMH_ENDPOINT",
    "POLITENESS_SLEEP_SECONDS",
    "harvest_set",
    "run_delta",
]
