"""Bulk ingest orchestrator (E11_S01).

Drives the per-paper ingest pipeline at corpus scale. Reads a
newline-separated paper-id list, processes each through the
fallback ladder (ar5iv → LaTeXML → skip-and-log), and writes
chunks + embeddings into a **staging** LanceDB dataset. The active
``corpus-version.json`` (under ``var/arxmcp/index/lancedb/``) is
left untouched; E11_S05 advances it via an atomic directory swap.

**Why a staging path:** ``ingest.store.write_chunks`` writes a
``corpus-version.json`` marker as a post-write step. Writing into
the active dataset would advance the marker per-paper and break
the brief's AC2 ("``corpus-version.json`` still pins OLD
version"). The staging path keeps every per-paper write isolated
inside ``var/arxmcp/index/lancedb-staging/``. The server's
``Resources.startup`` reads from ``config.lancedb_path`` (the
active path), so it cannot accidentally pick up half-ingested
data.

**What staging does not isolate:** the per-paper intermediate trees
(``corpus/parsed``, ``corpus/chunks``, ``corpus/embeddings``,
``corpus/preamble``) are shared by every dataset's runs, on purpose.
They are a per-paper cache, not a dataset's record. The parsed and raw
trees are downloads, the same whichever dataset reads them. The chunk and
embedding trees are what this code makes of those downloads: the same
paper and code give the same files, each set is replaced through a
temporary file and ``os.replace`` (two runs writing one paper concurrently
each leave a whole set), and nothing reuses a set without checking it.
The embedder re-encodes any paper whose sidecar records another chunker,
embedder or input-policy version or other chunks, and the rows a run
writes come from the embed step of that same run, never from the tree
alone. An aborted run that leaves another code version's sets behind
therefore costs a re-embed, not a wrong row. A tree per dataset would
re-embed every paper once per notebook and per staging run. The ops
files are per target where it matters: callers pass ``ops_dir``,
``log_path`` and ``failures_path``, and a notebook's run keeps them in
the notebook's ``ops/``.

**Scope at v1 (per research synthesis D1):** This module ships
the SCAFFOLDING — orchestrator + CLI. The actual ingest of the
200K-paper corpus is a 1-2 day GPU run that requires a Bittorrent
download, live ar5iv/arxiv/OpenAlex/INSPIRE-HEP access, and
operator presence. The unit/smoke tests pin the orchestrator's
call sequence against ONE paper; the ``requires_full_corpus``-
marked sanity test gates on the operator's actual run.

**Fallback ladder (synthesis D2):**

1. ``ar5iv_fetch.try_cache(paper_id)`` — fastest path, ~70-90% of
   post-2007 papers are cached.
2. **LaTeXML on the local .tex source** — only if the operator
   has extracted the Academic Torrents bulk dump into
   ``var/arxmcp/corpus/raw/<paper_id>/``. v1 invokes the existing
   ``ingest.preamble.extract_preamble`` + ``ingest.chunker.chunk_paper``
   chain which internally calls LaTeXML via the chunker's HTML
   walk (raw .tex still has to be parsed to HTML; the chunker
   expects parsed HTML at ``var/arxmcp/corpus/parsed/<paper_id>/index.html``).
3. **Skip-and-log** — any paper with neither an ar5iv hit nor a
   parseable local .tex gets a row in
   ``ops/parser-failures/bulk.jsonl``. Nougat PDF fallback is
   deferred (synthesis D2).

**One writer per dataset:** a run holds the target dataset's write
lock (:mod:`ingest.write_lock`) from its chunker-version check to its
index build, and the loop is sequential at the write boundary. A second
writer of the same dataset is refused at once, and the CLI exits with
:data:`ingest.write_lock.WRITE_LOCKED_EXIT_CODE`.

**Chunker-version guard:** a run refuses, before
its first write, a target whose arXiv rows another
``CHUNKER_VERSION`` wrote (:func:`ingest.store.refuse_stale_chunker_rows`).
Re-chunking such rows in place would leave every row whose id changed
beside its replacement. The supported path is the re-embed driver into
a fresh staging table, then a cutover.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from ingest.application_paths import ApplicationPaths
from ingest.ar5iv_fetch import (
    DEFAULT_AR5IV_CACHE_DIR,
    DEFAULT_PARSED_DIR,
    Ar5ivResult,
    try_cache,
)
from ingest.chunker import STRUCTURE_SIGNAL_CLASSES, chunk_paper
from ingest.derived_indexes import build_derived_indexes
from ingest.embedder import embed_paper
from ingest.extract_equations import extract_equations_for_paper
from ingest.identifiers import is_valid_arxiv_paper_id
from ingest.index_equations import index_equation_trees
from ingest.store import (
    DEFAULT_LANCEDB_PATH,
    STALE_CHUNKER_EXIT_CODE,
    StaleChunkerRowsError,
    WapGateError,
    load_embed_record,
    refresh_indices,
    refuse_stale_chunker_rows,
    write_chunks,
)
from ingest.write_lock import dataset_write_lock, exits_when_write_locked

logger = logging.getLogger(__name__)

_APPLICATION_PATHS = ApplicationPaths.resolve()

#: Default staging LanceDB path (synthesis D5). The active dataset
#: sits at ``DEFAULT_LANCEDB_PATH`` (``var/arxmcp/index/lancedb``);
#: bulk ingest writes here so the active ``corpus-version.json``
#: is untouched. E11_S05's cutover swaps this with the active path.
DEFAULT_LANCEDB_STAGING_PATH = _APPLICATION_PATHS.index / "lancedb-staging"

#: Default location of the parser-failures log. Append-only JSONL.
DEFAULT_PARSER_FAILURES_PATH = (
    _APPLICATION_PATHS.ops / "parser-failures" / "bulk.jsonl"
)

#: Default location of the ingestion log. Append-only text records.
DEFAULT_INGESTION_LOG_PATH = _APPLICATION_PATHS.ops / "ingestion.log"

#: Default ops directory for sentinel files (ingest-summary.json etc.).
DEFAULT_OPS_DIR = _APPLICATION_PATHS.ops

#: Progress checkpoint interval — emit a summary line every Nth paper.
DEFAULT_PROGRESS_INTERVAL = 1000


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class PaperOutcome:
    """One paper's full-pipeline outcome."""

    paper_id: str
    parsers_tried: list[str] = field(default_factory=list)
    parser_used: str | None = None   # "ar5iv" / "latexml" / None (failure)
    chunks_written: int = 0
    elapsed_seconds: float = 0.0
    failure_reason: str | None = None
    #: Whether re-running the paper later may succeed without any other
    #: change (for example ar5iv answered 429 or 503). Only meaningful
    #: when ``failure_reason`` is set.
    retriable: bool = False


@dataclass
class IngestSummary:
    """Aggregate of one bulk-ingest run."""

    papers_total: int = 0
    papers_succeeded: int = 0
    papers_failed: int = 0
    papers_skipped: int = 0
    ar5iv_hits: int = 0
    ar5iv_misses: int = 0
    elapsed_seconds: float = 0.0

    @property
    def ar5iv_hit_rate(self) -> float:
        """Fraction in [0, 1]. Brief's AC5 target is ≥ 0.70."""
        total = self.ar5iv_hits + self.ar5iv_misses
        return self.ar5iv_hits / total if total else 0.0


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _log_parser_failure(
    outcome: PaperOutcome, failures_path: Path
) -> None:
    """Append one JSON line to ``ops/parser-failures/bulk.jsonl``."""
    failures_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "paper_id": outcome.paper_id,
        "parsers_tried": outcome.parsers_tried,
        "failure_reason": outcome.failure_reason,
        "retriable": outcome.retriable,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with failures_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _log_progress(
    log_path: Path, summary: IngestSummary, paper_id: str
) -> None:
    """Append one progress record to ``ops/ingestion.log``."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = (
        f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\t"
        f"paper={paper_id}\t"
        f"total={summary.papers_total}\t"
        f"ok={summary.papers_succeeded}\t"
        f"fail={summary.papers_failed}\t"
        f"skip={summary.papers_skipped}\t"
        f"ar5iv_hits={summary.ar5iv_hits}\t"
        f"ar5iv_misses={summary.ar5iv_misses}\t"
        f"ar5iv_rate={summary.ar5iv_hit_rate:.3f}\n"
    )
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(record)


def _read_paper_ids(path: Path) -> list[str]:
    """Load a newline-separated list of paper ids.

    Blanks and ``#``-comment lines are skipped. Each id is
    validated against ``is_valid_paper_id`` — malformed entries
    raise so the operator catches typos before a multi-day run.
    """
    if not path.is_file():
        raise FileNotFoundError(
            f"--paper-ids-file not found: {path}. Provide a "
            f"newline-separated list of arXiv ids."
        )
    ids: list[str] = []
    for lineno, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not is_valid_arxiv_paper_id(line):
            raise ValueError(
                f"{path}:{lineno}: invalid paper_id {line!r}"
            )
        ids.append(line)
    return ids


# ---------------------------------------------------------------------------
# Per-paper pipeline (the unit of bulk-ingest work)
# ---------------------------------------------------------------------------


def _parse_via_ar5iv(
    paper_id: str,
    ar5iv_cache_dir: Path,
    parsed_dir: Path,
) -> Ar5ivResult:
    """Try ar5iv; return the result without raising."""
    from server.ssl_pin import arxiv_ssl_context_from_env  # noqa: PLC0415

    try:
        return try_cache(
            paper_id,
            cache_dir=ar5iv_cache_dir,
            parsed_dir=parsed_dir,
            ssl_context=arxiv_ssl_context_from_env(),
        )
    except ValueError:
        # Malformed paper_id was already caught upstream; defensive.
        raise
    except Exception as exc:  # noqa: BLE001 — log + return miss
        logger.warning(
            "ar5iv: unexpected error for %s: %s", paper_id, exc
        )
        return Ar5ivResult(
            paper_id=paper_id,
            hit=False,
            cache_path=None,
            parsed_path=None,
            reason="unexpected_error",
        )


def _has_local_parsed_html(paper_id: str, parsed_dir: Path) -> bool:
    """Return True if a parsed HTML file exists for the paper.

    The chunker reads ``<parsed_dir>/<paper_id>/index.html``. v1's
    LaTeXML-fallback path assumes the operator has already
    run ``ingest/arxiv_fetch.py`` (or similar) to produce this
    file. Bulk ingest does NOT itself fetch raw .tex or invoke
    LaTeXML — those are operator-side concerns.
    """
    return (parsed_dir / paper_id / "index.html").is_file()


def _diagnose_empty_render(paper_id: str, parsed_dir: Path) -> str:
    """Categorize a zero-chunk render for the parser-failures report.

    ``chunk_paper`` returning ``[]`` after the AC1 section-less fallback means
    the render had no harvestable prose at all. Distinguish the "math present
    but no ltx_section/theorem/proof structure" case
    (``render_unchunkable_no_sections`` — a strong signal the PDF/MinerU path
    is needed) from a generic ``chunker_returned_empty``. Cheap substring scan
    of the on-disk HTML (no full DOM parse), same spirit as ar5iv's ``<math``
    gate; a missing/unreadable file degrades to the generic reason.
    """
    parsed_path = parsed_dir / paper_id / "index.html"
    try:
        body = parsed_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "chunker_returned_empty"
    has_math = "<math" in body
    # ingest-robustness-m1 M2/L1: the SAME signal set the ar5iv no-sections WARN
    # uses (ingest.chunker.STRUCTURE_SIGNAL_CLASSES) — a single source derived
    # from the chunker's real structural gates, so the two AC4 sites cannot
    # drift apart.
    has_structure = any(sig in body for sig in STRUCTURE_SIGNAL_CLASSES)
    if has_math and not has_structure:
        return "render_unchunkable_no_sections"
    return "chunker_returned_empty"


def ingest_one_paper(
    paper_id: str,
    *,
    lancedb_staging_path: Path = DEFAULT_LANCEDB_STAGING_PATH,
    ar5iv_cache_dir: Path = DEFAULT_AR5IV_CACHE_DIR,
    parsed_dir: Path = DEFAULT_PARSED_DIR,
    skip_ar5iv: bool = False,
    build_indices: bool = True,
) -> PaperOutcome:
    """Run the full pipeline for one paper.

    Sequence:

    1. ar5iv cache check (unless ``skip_ar5iv``).
    2. On miss: check for pre-parsed HTML on disk (LaTeXML output
       from the operator's prior `ingest/arxiv_fetch.py` run).
    3. If neither: skip-and-log; outcome has
       ``parser_used = None`` and ``failure_reason`` set.
    4. If parsed HTML exists: invoke chunker → embedder →
       ``write_chunks`` against the **staging** LanceDB path, then
       extract the paper's equations into the same dataset.

    Returns a :class:`PaperOutcome` regardless of success or
    failure. The caller (the bulk loop) decides what to do with
    failed outcomes (log to parser-failures, continue). An exception
    from any stage becomes ``failure_reason="raised:<type>: <message>"``
    so one bad paper cannot end a run; only :class:`WapGateError`
    propagates, because a marker that disagrees with the table breaks
    every later write too.

    A loop over many papers passes ``build_indices=False`` and calls
    :func:`ingest.store.refresh_indices` once after it. The equation trees
    are built once per run too (:func:`index_equation_trees`).
    """
    if not is_valid_arxiv_paper_id(paper_id):
        raise ValueError(
            f"paper_id {paper_id!r} does not match the arXiv id format"
        )

    outcome = PaperOutcome(paper_id=paper_id)
    start = time.monotonic()

    try:
        # Step 1: ar5iv.
        ar5iv_result: Ar5ivResult | None = None
        if not skip_ar5iv:
            outcome.parsers_tried.append("ar5iv")
            ar5iv_result = _parse_via_ar5iv(
                paper_id, ar5iv_cache_dir, parsed_dir
            )
            if ar5iv_result.hit:
                outcome.parser_used = "ar5iv"
            else:
                logger.debug(
                    "ar5iv miss for %s (%s)", paper_id, ar5iv_result.reason
                )
        # Step 2: local LaTeXML output (if a prior op produced it).
        if outcome.parser_used is None:
            outcome.parsers_tried.append("latexml")
            if _has_local_parsed_html(paper_id, parsed_dir):
                outcome.parser_used = "latexml"
            elif ar5iv_result is None:
                outcome.failure_reason = "no_parsed_html"
                return outcome
            else:
                # Keep the ar5iv reason so the failures log separates a
                # paper ar5iv has no render for from a rate limit or an
                # outage that a later run would get past.
                outcome.failure_reason = f"no_parsed_html:ar5iv_{ar5iv_result.reason}"
                outcome.retriable = ar5iv_result.retriable
                return outcome
        # Step 3: chunk + embed + store.
        chunks = chunk_paper(paper_id, parsed_dir=parsed_dir)
        if not chunks:
            # ingest-robustness-m1 (AC4): distinguish a structurally
            # unchunkable render (math, but no sections/theorems, and no
            # salvageable body even after the fallback) from a generic empty,
            # so operators can route these to the PDF/MinerU path.
            outcome.failure_reason = _diagnose_empty_render(paper_id, parsed_dir)
            return outcome
        # Closes F1: embed_paper catches PER_PAPER_FAILURE_EXCEPTIONS
        # and returns EmbedStats(status="fail", ...) instead of
        # raising. Without this check, load_embed_record would read
        # whatever NPZ was on disk from a previous run — silent
        # stale-vector corruption of the staging LanceDB.
        embed_stats = embed_paper(paper_id)
        if embed_stats.status != "ok":
            outcome.failure_reason = (
                f"embedder_failed:{embed_stats.error_class}"
            )
            return outcome
        embed_record = load_embed_record(paper_id)
        if embed_record is None:
            outcome.failure_reason = "embedder_produced_no_record"
            return outcome
        # The paper's whole chunk set: rows a revision re-chunked away go.
        version = write_chunks(
            chunks, embed_record, lancedb_path=lancedb_staging_path,
            build_indices=build_indices, replace_paper=True,
        )
        # From the HTML just chunked, linked to the chunks just written.
        # A paper whose equations did not land is not counted as written.
        extract_equations_for_paper(
            paper_id, lancedb_staging_path,
            html_path=parsed_dir / paper_id / "index.html",
        )
        outcome.chunks_written = len(chunks)
        logger.debug(
            "wrote %d chunks for %s at staging version %d",
            outcome.chunks_written, paper_id, version,
        )
    except WapGateError:
        raise
    except Exception as exc:  # noqa: BLE001 — per-paper isolation
        logger.exception("ingest failed for %s; recording it and continuing", paper_id)
        outcome.failure_reason = f"raised:{type(exc).__name__}: {exc}"
    finally:
        outcome.elapsed_seconds = time.monotonic() - start

    return outcome


# ---------------------------------------------------------------------------
# Bulk loop
# ---------------------------------------------------------------------------


def run_bulk_ingest(
    paper_ids: list[str],
    *,
    lancedb_staging_path: Path = DEFAULT_LANCEDB_STAGING_PATH,
    ar5iv_cache_dir: Path = DEFAULT_AR5IV_CACHE_DIR,
    parsed_dir: Path = DEFAULT_PARSED_DIR,
    failures_path: Path = DEFAULT_PARSER_FAILURES_PATH,
    log_path: Path = DEFAULT_INGESTION_LOG_PATH,
    ops_dir: Path = DEFAULT_OPS_DIR,
    progress_interval: int = DEFAULT_PROGRESS_INTERVAL,
    limit: int | None = None,
    dry_run: bool = False,
) -> IngestSummary:
    """Run the full bulk-ingest loop. Returns the aggregate summary.

    The loop is **single-process sequential** at the write
    boundary, and the run holds the dataset's write lock throughout
    (:class:`ingest.write_lock.DatasetWriteLockedError` if another
    writer has it). GPU batching happens inside ``embed_paper``. Naive
    re-runs are safe: the embedder's per-paper sidecar carries the
    versions and each chunk's reuse identity, so already-processed
    papers short-circuit at the embed step regardless (a sidecar
    that records no reuse identity re-embeds once).
    """
    if progress_interval <= 0:
        # Closes F8: a positive interval is the only sane value; 0
        # would crash on ``n % progress_interval`` below.
        raise ValueError(
            f"progress_interval must be >= 1; got {progress_interval}"
        )
    if dry_run:
        return _run_dry(
            paper_ids,
            limit=limit,
            ar5iv_cache_dir=ar5iv_cache_dir,
            parsed_dir=parsed_dir,
        )
    with dataset_write_lock(lancedb_staging_path):
        return _run_locked(
            paper_ids,
            lancedb_staging_path=lancedb_staging_path,
            ar5iv_cache_dir=ar5iv_cache_dir,
            parsed_dir=parsed_dir,
            failures_path=failures_path,
            log_path=log_path,
            ops_dir=ops_dir,
            progress_interval=progress_interval,
            limit=limit,
        )


def _run_locked(
    paper_ids: list[str],
    *,
    lancedb_staging_path: Path,
    ar5iv_cache_dir: Path,
    parsed_dir: Path,
    failures_path: Path,
    log_path: Path,
    ops_dir: Path,
    progress_interval: int,
    limit: int | None,
) -> IngestSummary:
    """The run itself, under the dataset write lock."""
    # Never re-chunk in place across a chunker version.
    refuse_stale_chunker_rows(lancedb_staging_path)

    work = paper_ids if limit is None else paper_ids[:limit]
    summary = IngestSummary(papers_total=len(work))
    started = time.monotonic()
    chunks_written = 0

    for n, paper_id in enumerate(work, start=1):
        outcome = ingest_one_paper(
            paper_id,
            lancedb_staging_path=lancedb_staging_path,
            ar5iv_cache_dir=ar5iv_cache_dir,
            parsed_dir=parsed_dir,
            build_indices=False,
        )
        chunks_written += outcome.chunks_written
        if outcome.parser_used == "ar5iv":
            summary.ar5iv_hits += 1
        elif "ar5iv" in outcome.parsers_tried:
            summary.ar5iv_misses += 1
        if outcome.chunks_written > 0:
            summary.papers_succeeded += 1
        else:
            summary.papers_failed += 1
            _log_parser_failure(outcome, failures_path)
        if n % progress_interval == 0 or n == len(work):
            _log_progress(log_path, summary, paper_id)

    # The dataset is not ready to promote until it carries its indexes.
    # Vector indexes first: they move the marker the derived ones key to.
    if summary.papers_succeeded:
        refresh_indices(lancedb_staging_path)
        build_derived_indexes(lancedb_staging_path)
        index_equation_trees(lancedb_staging_path)

    summary.elapsed_seconds = time.monotonic() - started

    # corpus-integrity-observability-e3: write the ingest-summary.json
    # sentinel for /metrics scrape-time exposure. Wrapped in try/except
    # so a sentinel-write failure does NOT abort an otherwise-successful run.
    try:
        from ingest.ingest_summary import write_ingest_summary  # noqa: PLC0415

        write_ingest_summary(
            ops_dir,
            "bulk_ingest",
            papers_processed=summary.papers_total,
            papers_succeeded=summary.papers_succeeded,
            papers_failed=summary.papers_failed,
            chunks_written_this_run=chunks_written,
            total_rows_after_commit=0,  # not available at this level; 0 is safe
            elapsed_seconds=summary.elapsed_seconds,
        )
    except Exception:
        logger.warning(
            "failed to write ingest-summary.json (run already succeeded; "
            "sentinel is best-effort)",
            exc_info=True,
        )

    return summary


def _run_dry(
    paper_ids: list[str],
    *,
    limit: int | None,
    ar5iv_cache_dir: Path,
    parsed_dir: Path,
) -> IngestSummary:
    """Dry-run: report which parser each paper WOULD use, no writes.

    Per F5: the dry-run never queries ar5iv, so ``ar5iv_hits`` /
    ``ar5iv_misses`` are intentionally left at 0 in the summary —
    treating a cold cache as "100% miss rate" would mislead the
    operator into thinking ar5iv was broken.
    """
    work = paper_ids if limit is None else paper_ids[:limit]
    summary = IngestSummary(papers_total=len(work))
    for paper_id in work:
        cache_hit = (ar5iv_cache_dir / f"{paper_id}.html").is_file() and (
            parsed_dir / paper_id / "index.html"
        ).is_file()
        if cache_hit:
            print(f"{paper_id}\tar5iv_local_cache")
        elif _has_local_parsed_html(paper_id, parsed_dir):
            print(f"{paper_id}\tlatexml")
        else:
            print(f"{paper_id}\tWOULD_FETCH_AR5IV_THEN_FALLBACK")
        summary.papers_skipped += 1  # dry-run writes nothing
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@exits_when_write_locked
def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="arXMCP bulk ingest orchestrator (E11_S01).",
    )
    parser.add_argument(
        "--paper-ids-file",
        required=True,
        type=Path,
        help="Newline-separated arXiv paper id list (required).",
    )
    parser.add_argument(
        "--lancedb-staging-path",
        default=str(DEFAULT_LANCEDB_STAGING_PATH),
        type=Path,
        help=(
            f"Staging LanceDB dataset (default: "
            f"{DEFAULT_LANCEDB_STAGING_PATH}). The active dataset at "
            f"{DEFAULT_LANCEDB_PATH} is NOT touched."
        ),
    )
    parser.add_argument(
        "--ar5iv-cache-dir",
        default=str(DEFAULT_AR5IV_CACHE_DIR),
        type=Path,
        help=f"ar5iv on-disk cache (default: {DEFAULT_AR5IV_CACHE_DIR})",
    )
    # No --parsed-dir flag: the CLI fetches into and chunks from the
    # default parsed tree. Python callers may pass ``parsed_dir``, which
    # reaches both the ar5iv write and the chunker read.
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N papers (default: all)",
    )
    # Closes F3 + IS2: --resume was advertised in the CLI and the
    # runbook but the loop body did not act on it. Naive re-runs are
    # already safe because the embedder's per-paper sidecar carries a
    # version check (``ingest/embedder.py:914-936``) — already-
    # processed papers short-circuit at the embed step without
    # rewriting the LanceDB row.
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the per-paper action plan (which parser WOULD "
            "fire) without writing to LanceDB or fetching from "
            "ar5iv. Use this to sanity-check the input list "
            "before a multi-day ingest."
        ),
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    paper_ids = _read_paper_ids(args.paper_ids_file)
    print(
        f"loaded {len(paper_ids)} paper ids from {args.paper_ids_file}"
    )

    try:
        summary = run_bulk_ingest(
            paper_ids,
            lancedb_staging_path=args.lancedb_staging_path,
            ar5iv_cache_dir=args.ar5iv_cache_dir,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    except StaleChunkerRowsError as exc:
        # A refusal, not a crash: no traceback, and its own exit code.
        print(f"error: {exc}", file=sys.stderr)
        return STALE_CHUNKER_EXIT_CODE
    # Closes F5: dry-run never actually queries ar5iv, so an
    # ar5iv_rate of 0.0 against an empty local cache would be
    # misleading. Omit the rate from the dry-run summary.
    rate_token = (
        ""
        if args.dry_run
        else f"ar5iv_rate={summary.ar5iv_hit_rate:.3f} "
    )
    print(
        f"total={summary.papers_total} "
        f"ok={summary.papers_succeeded} "
        f"fail={summary.papers_failed} "
        f"skip={summary.papers_skipped} "
        f"{rate_token}"
        f"elapsed={summary.elapsed_seconds:.1f}s"
    )
    # Non-zero exit on any failures so the operator's shell catches
    # the signal (cron mailer, systemd-timer status).
    return 0 if summary.papers_failed == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_cli(sys.argv[1:]))


__all__ = [
    "DEFAULT_INGESTION_LOG_PATH",
    "DEFAULT_LANCEDB_STAGING_PATH",
    "DEFAULT_PARSER_FAILURES_PATH",
    "DEFAULT_PROGRESS_INTERVAL",
    "IngestSummary",
    "PaperOutcome",
    "ingest_one_paper",
    "run_bulk_ingest",
]
