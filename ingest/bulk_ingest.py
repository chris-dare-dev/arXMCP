"""Bulk ingest orchestrator (E11_S01).

Drives the per-paper ingest pipeline at corpus scale. Reads a
newline-separated paper-id list, processes each through the
fallback ladder (native HTML → ar5iv → LaTeXML → skip-and-log),
and writes chunks + embeddings into a **staging** LanceDB dataset. The active
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

**Scope at v1 (per research synthesis D1):** This module ships
the SCAFFOLDING — orchestrator + CLI. The actual ingest of the
200K-paper corpus is a 1-2 day GPU run that requires a Bittorrent
download, live ar5iv/arxiv/OpenAlex/INSPIRE-HEP access, and
operator presence. The unit/smoke tests pin the orchestrator's
call sequence against ONE paper; the ``requires_full_corpus``-
marked sanity test gates on the operator's actual run.

**Fallback ladder (synthesis D2; arx-a45 adds the native rung per
finding 04's cascade and finding 211 R-E/E-8):**

0. ``ar5iv_fetch.try_native(paper_id)`` — arXiv's first-party
   ``arxiv.org/html`` render; same LaTeXML markup family as ar5iv,
   institutionally backed, but rollout incomplete for older papers.
1. ``ar5iv_fetch.try_cache(paper_id)`` — fastest legacy path,
   ~70-90% of post-2007 papers are cached.
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

**Single-writer constraint** (`ingest/store.py:44-55`): the loop
is sequential at the write boundary. No parallel ``write_chunks``
calls.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from ingest.ar5iv_fetch import (
    DEFAULT_AR5IV_CACHE_DIR,
    DEFAULT_NATIVE_CACHE_DIR,
    DEFAULT_PARSED_DIR,
    Ar5ivResult,
    extract_latexml_generator,
    try_cache,
    try_native,
)
from ingest.chunker import chunk_paper
from ingest.embedder import embed_paper
from ingest.identifiers import is_valid_arxiv_paper_id
from ingest.store import DEFAULT_LANCEDB_PATH, load_embed_record, write_chunks

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Default staging LanceDB path (synthesis D5). The active dataset
#: sits at ``DEFAULT_LANCEDB_PATH`` (``var/arxmcp/index/lancedb``);
#: bulk ingest writes here so the active ``corpus-version.json``
#: is untouched. E11_S05's cutover swaps this with the active path.
DEFAULT_LANCEDB_STAGING_PATH = (
    REPO_ROOT / "var" / "arxmcp" / "index" / "lancedb-staging"
)

#: Default location of the parser-failures log. Append-only JSONL.
DEFAULT_PARSER_FAILURES_PATH = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "parser-failures" / "bulk.jsonl"
)

#: Default location of the ingestion log. Append-only text records.
DEFAULT_INGESTION_LOG_PATH = (
    REPO_ROOT / "var" / "arxmcp" / "ops" / "ingestion.log"
)

#: Default ops directory for sentinel files (ingest-summary.json etc.).
DEFAULT_OPS_DIR = REPO_ROOT / "var" / "arxmcp" / "ops"

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
    # "native_html" / "ar5iv" / "latexml" / None (failure)
    parser_used: str | None = None
    chunks_written: int = 0
    elapsed_seconds: float = 0.0
    failure_reason: str | None = None
    #: arx-a45 drift tripwire — the LaTeXML generator version string
    #: extracted from the rendered HTML (any rung), or ``None`` when
    #: the comment is absent / the paper failed before parsing.
    latexml_generator: str | None = None


@dataclass
class IngestSummary:
    """Aggregate of one bulk-ingest run."""

    papers_total: int = 0
    papers_succeeded: int = 0
    papers_failed: int = 0
    papers_skipped: int = 0
    #: arx-a45 — papers served by the arxiv.org/html native rung.
    native_hits: int = 0
    ar5iv_hits: int = 0
    ar5iv_misses: int = 0
    elapsed_seconds: float = 0.0

    @property
    def ar5iv_hit_rate(self) -> float:
        """Fraction in [0, 1]. Brief's AC5 target is ≥ 0.70.

        Semantics preserved from E11_S01: counts papers whose parse
        came from the ar5iv rung against papers where ar5iv was
        tried and missed. Native-rung hits (arx-a45) are excluded
        from BOTH numerator and denominator — see
        :attr:`remote_html_hit_rate` for the whole-ladder view.
        """
        total = self.ar5iv_hits + self.ar5iv_misses
        return self.ar5iv_hits / total if total else 0.0

    @property
    def remote_html_hit_rate(self) -> float:
        """Fraction of papers served by EITHER remote render rung
        (native HTML or ar5iv) out of all papers that tried the
        remote ladder (arx-a45)."""
        remote = self.native_hits + self.ar5iv_hits
        total = remote + self.ar5iv_misses
        return remote / total if total else 0.0


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
        f"native_hits={summary.native_hits}\t"
        f"ar5iv_hits={summary.ar5iv_hits}\t"
        f"ar5iv_misses={summary.ar5iv_misses}\t"
        f"ar5iv_rate={summary.ar5iv_hit_rate:.3f}\n"
    )
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(record)


def _log_generator_version(
    generators_path: Path, outcome: PaperOutcome
) -> None:
    """Append one JSONL record of the per-ingest LaTeXML generator
    version — the arx-a45 drift tripwire (finding 211 rec 6).

    One record per successfully-parsed paper, even when the version
    could not be extracted (``generator: null`` is itself signal —
    a sudden run of nulls means the comment format moved). Write
    failures are logged and swallowed: the tripwire is
    observability, never a reason to abort an ingest run.
    """
    record = {
        "generator": outcome.latexml_generator,
        "paper_id": outcome.paper_id,
        "parser": outcome.parser_used,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        generators_path.parent.mkdir(parents=True, exist_ok=True)
        with generators_path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            )
    except OSError:
        logger.warning(
            "could not append LaTeXML generator record for %s to %s",
            outcome.paper_id, generators_path, exc_info=True,
        )


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
    try:
        return try_cache(
            paper_id,
            cache_dir=ar5iv_cache_dir,
            parsed_dir=parsed_dir,
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


def _parse_via_native(
    paper_id: str,
    native_cache_dir: Path,
    parsed_dir: Path,
) -> Ar5ivResult:
    """Try the arxiv.org/html native rung; return the result without
    raising (arx-a45 — mirrors :func:`_parse_via_ar5iv`)."""
    try:
        return try_native(
            paper_id,
            cache_dir=native_cache_dir,
            parsed_dir=parsed_dir,
        )
    except ValueError:
        # Malformed paper_id was already caught upstream; defensive.
        raise
    except Exception as exc:  # noqa: BLE001 — log + return miss
        logger.warning(
            "native_html: unexpected error for %s: %s", paper_id, exc
        )
        return Ar5ivResult(
            paper_id=paper_id,
            hit=False,
            cache_path=None,
            parsed_path=None,
            reason="unexpected_error",
            source="native_html",
        )


def _local_generator_version(paper_id: str, parsed_dir: Path) -> str | None:
    """Extract the LaTeXML generator version from an on-disk parsed
    render (the local-LaTeXML rung; arx-a45 drift tripwire).

    Bounded read (64 KB head — the generator comment sits in
    ``<head>``); any I/O failure degrades to ``None``.
    """
    parsed_html = parsed_dir / paper_id / "index.html"
    try:
        with parsed_html.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(64 * 1024)
    except OSError:
        return None
    return extract_latexml_generator(head)


def _has_local_parsed_html(paper_id: str, parsed_dir: Path) -> bool:
    """Return True if a parsed HTML file exists for the paper.

    The chunker reads from
    ``var/arxmcp/corpus/parsed/<paper_id>/index.html``. v1's
    LaTeXML-fallback path assumes the operator has already
    run ``tools/arxiv_fetch.py`` (or similar) to produce this
    file. Bulk ingest does NOT itself fetch raw .tex or invoke
    LaTeXML — those are operator-side concerns documented in
    ``docs/ops/bulk-ingest-runbook.md``.
    """
    return (parsed_dir / paper_id / "index.html").is_file()


def ingest_one_paper(
    paper_id: str,
    *,
    lancedb_staging_path: Path = DEFAULT_LANCEDB_STAGING_PATH,
    ar5iv_cache_dir: Path = DEFAULT_AR5IV_CACHE_DIR,
    native_cache_dir: Path = DEFAULT_NATIVE_CACHE_DIR,
    parsed_dir: Path = DEFAULT_PARSED_DIR,
    skip_ar5iv: bool = False,
) -> PaperOutcome:
    """Run the full pipeline for one paper.

    Sequence (arx-a45 ladder — native → ar5iv → local LaTeXML):

    0. arxiv.org/html native-render check (unless ``skip_ar5iv``,
       which skips BOTH remote rungs — the flag predates the native
       rung and means "no remote fetches"; its name is kept for API
       stability).
    1. On miss: ar5iv cache check.
    2. On miss: check for pre-parsed HTML on disk (LaTeXML output
       from the operator's prior `tools/arxiv_fetch.py` run).
    3. If none: skip-and-log; outcome has
       ``parser_used = None`` and ``failure_reason`` set.
    4. If parsed HTML exists: invoke chunker → embedder →
       ``write_chunks`` against the **staging** LanceDB path.

    A local-cache short-circuit runs before the network rungs: when
    the canonical parsed file exists alongside either rung's cache
    file, no network call is made (the per-rung fetchers implement
    this; the native rung's short-circuit fires first only if a
    native cache file exists, so pre-arx-a45 ar5iv caches keep
    short-circuiting exactly as before once the native rung's
    network miss is cached... see ``try_html_sources`` for the
    combined-short-circuit variant used by ``tools/notebook_fetch``).

    Returns a :class:`PaperOutcome` regardless of success or
    failure. The caller (the bulk loop) decides what to do with
    failed outcomes (log to parser-failures, continue).
    """
    if not is_valid_arxiv_paper_id(paper_id):
        raise ValueError(
            f"paper_id {paper_id!r} does not match the arXiv id format"
        )

    outcome = PaperOutcome(paper_id=paper_id)
    start = time.monotonic()

    try:
        # Step 0: arxiv.org/html native render (arx-a45 first rung).
        # Skip the network attempt when the paper is already served
        # locally by a prior ar5iv fetch (parsed + ar5iv cache both
        # present) — the ar5iv rung's own short-circuit will take it,
        # and a native network call for an already-ingested paper
        # would be wasted egress.
        if not skip_ar5iv:
            ar5iv_local = (
                (ar5iv_cache_dir / f"{paper_id}.html").is_file()
                and (parsed_dir / paper_id / "index.html").is_file()
            )
            if not ar5iv_local:
                outcome.parsers_tried.append("native_html")
                native_result = _parse_via_native(
                    paper_id, native_cache_dir, parsed_dir
                )
                if native_result.hit:
                    outcome.parser_used = "native_html"
                    outcome.latexml_generator = (
                        native_result.latexml_generator
                    )
                else:
                    logger.debug(
                        "native_html miss for %s (%s)",
                        paper_id, native_result.reason,
                    )
        # Step 1: ar5iv.
        if outcome.parser_used is None and not skip_ar5iv:
            outcome.parsers_tried.append("ar5iv")
            ar5iv_result = _parse_via_ar5iv(
                paper_id, ar5iv_cache_dir, parsed_dir
            )
            if ar5iv_result.hit:
                outcome.parser_used = "ar5iv"
                outcome.latexml_generator = ar5iv_result.latexml_generator
            else:
                logger.debug(
                    "ar5iv miss for %s (%s)", paper_id, ar5iv_result.reason
                )
        # Step 2: local LaTeXML output (if a prior op produced it).
        if outcome.parser_used is None:
            outcome.parsers_tried.append("latexml")
            if _has_local_parsed_html(paper_id, parsed_dir):
                outcome.parser_used = "latexml"
                outcome.latexml_generator = _local_generator_version(
                    paper_id, parsed_dir
                )
            else:
                outcome.failure_reason = "no_parsed_html"
                return outcome
        # Step 3: chunk + embed + store.
        chunks = chunk_paper(paper_id)
        if not chunks:
            outcome.failure_reason = "chunker_returned_empty"
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
        version = write_chunks(
            chunks, embed_record, lancedb_path=lancedb_staging_path
        )
        outcome.chunks_written = len(chunks)
        logger.debug(
            "wrote %d chunks for %s at staging version %d",
            outcome.chunks_written, paper_id, version,
        )
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
    native_cache_dir: Path = DEFAULT_NATIVE_CACHE_DIR,
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
    boundary (``ingest.store.write_chunks`` is single-writer-per-
    dataset). GPU batching happens inside ``embed_paper``. Naive
    re-runs are safe: the embedder's per-paper sidecar carries a
    version check, so already-processed papers short-circuit at
    the embed step regardless.
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
            native_cache_dir=native_cache_dir,
            parsed_dir=parsed_dir,
        )

    work = paper_ids if limit is None else paper_ids[:limit]
    summary = IngestSummary(papers_total=len(work))
    started = time.monotonic()
    chunks_written = 0

    # arx-a45: per-ingest LaTeXML generator-version records (drift
    # tripwire) live beside the ingestion log.
    generators_path = log_path.parent / "latexml-generators.jsonl"

    for n, paper_id in enumerate(work, start=1):
        outcome = ingest_one_paper(
            paper_id,
            lancedb_staging_path=lancedb_staging_path,
            ar5iv_cache_dir=ar5iv_cache_dir,
            native_cache_dir=native_cache_dir,
            parsed_dir=parsed_dir,
        )
        chunks_written += outcome.chunks_written
        if outcome.parser_used == "native_html":
            summary.native_hits += 1
        elif outcome.parser_used == "ar5iv":
            summary.ar5iv_hits += 1
        elif "ar5iv" in outcome.parsers_tried:
            summary.ar5iv_misses += 1
        if outcome.parser_used is not None:
            _log_generator_version(generators_path, outcome)
        if outcome.chunks_written > 0:
            summary.papers_succeeded += 1
        else:
            summary.papers_failed += 1
            _log_parser_failure(outcome, failures_path)
        if n % progress_interval == 0 or n == len(work):
            _log_progress(log_path, summary, paper_id)

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
    native_cache_dir: Path,
    parsed_dir: Path,
) -> IngestSummary:
    """Dry-run: report which parser each paper WOULD use, no writes.

    Per F5: the dry-run never queries the network, so the hit/miss
    counters are intentionally left at 0 in the summary — treating a
    cold cache as "100% miss rate" would mislead the operator into
    thinking the remote renders were broken.
    """
    work = paper_ids if limit is None else paper_ids[:limit]
    summary = IngestSummary(papers_total=len(work))
    for paper_id in work:
        parsed_present = (parsed_dir / paper_id / "index.html").is_file()
        native_cached = (native_cache_dir / f"{paper_id}.html").is_file()
        ar5iv_cached = (ar5iv_cache_dir / f"{paper_id}.html").is_file()
        if parsed_present and native_cached:
            print(f"{paper_id}\tnative_local_cache")
        elif parsed_present and ar5iv_cached:
            print(f"{paper_id}\tar5iv_local_cache")
        elif _has_local_parsed_html(paper_id, parsed_dir):
            print(f"{paper_id}\tlatexml")
        else:
            print(f"{paper_id}\tWOULD_FETCH_NATIVE_THEN_AR5IV_THEN_FALLBACK")
        summary.papers_skipped += 1  # dry-run writes nothing
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


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
    parser.add_argument(
        "--native-cache-dir",
        default=str(DEFAULT_NATIVE_CACHE_DIR),
        type=Path,
        help=(
            f"arxiv.org/html native-render on-disk cache "
            f"(default: {DEFAULT_NATIVE_CACHE_DIR})"
        ),
    )
    # Closes F2: --parsed-dir was a CLI footgun. The chunker reads
    # from a hardcoded module-level PARSED_DIR; honoring the CLI
    # override at the ar5iv-write step but ignoring it at the chunker
    # step caused silent "chunker_returned_empty" failures. The
    # parsed-dir is now fixed at ``ingest.chunker.PARSED_DIR``.
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

    summary = run_bulk_ingest(
        paper_ids,
        lancedb_staging_path=args.lancedb_staging_path,
        ar5iv_cache_dir=args.ar5iv_cache_dir,
        native_cache_dir=args.native_cache_dir,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    # Closes F5: dry-run never actually queries ar5iv, so an
    # ar5iv_rate of 0.0 against an empty local cache would be
    # misleading. Omit the rate from the dry-run summary.
    rate_token = (
        ""
        if args.dry_run
        else (
            f"native_hits={summary.native_hits} "
            f"ar5iv_rate={summary.ar5iv_hit_rate:.3f} "
            f"remote_html_rate={summary.remote_html_hit_rate:.3f} "
        )
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
# NOTE (arx-a45): ``try_native`` / ``try_cache`` are intentionally
# module attributes (not in __all__) so tests can monkeypatch the
# rungs at ``ingest.bulk_ingest.try_native`` / ``...try_cache``.
