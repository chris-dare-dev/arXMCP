"""Backfill arXiv paper metadata for an already-populated notebook.

paper-metadata-m1 (t-backfill-driver). Reads the notebook's
``papers.txt`` (the membership source of truth — the central
``notebook_papers`` junction table is EMPTY for every notebook, so
keying off it would hydrate zero rows and silently "pass"), fetches
title/authors/abstract/year/categories from the arXiv Atom API in
batched ``id_list`` requests, and upserts them into the per-notebook
:class:`server.paper_metadata_store.PaperMetadataStore` at
``var/arxmcp/notebooks/<slug>/paper_metadata.db``.

Politeness contract (arXiv ToU, live-verified hazards in the m1
research brief):

- ≤1 request / 3 s: a 3-second sleep BEFORE every request except the
  first (``tools.arxiv_fetch.POLITENESS_SLEEP_SECONDS``).
- Polite User-Agent with a contact email, enforced at ``run()`` entry
  via :func:`tools._notebook_common.resolve_contact_email` (never at
  import — tests that don't exercise the network need no email).
- 503 → backoff via ``parse_retry_after`` clamped to ≥30 s (arXiv has
  served ``Retry-After: 0``, which would otherwise hammer).
- 429 (plain-text ``Rate exceeded.``) → ≥60 s cool-down (15 s was
  observed to be insufficient).
- Bounded retry budget per request; exhausted retries degrade to
  per-id misses so an arXiv outage can never wedge the driver.
- One malformed id poisons a whole id_list response (HTTP-200 error
  feed): ids are pre-validated, and a poisoned batch falls back to
  per-id requests so one bad response cannot zero a batch.

Idempotency: already-hydrated rows (non-empty title AND authors) are
skipped without network egress; a re-run over a hydrated notebook
performs zero requests (t-backfill-driver acceptance).

Summary line (machine-parseable; the hydrated/total pair keeps a
zero-row run LOUD):

    hydrated=N skipped=M missing=K malformed=J total=T

Per-id failure reasons go to stderr — the ≥95% acceptance budget is
~6 ids thin, so every miss must be diagnosable.

Usage:

    uv run python tools/notebook_metadata_backfill.py <slug>

Exit codes:
    0 — every paper id hydrated or already hydrated
    1 — slug/email validation failed, malformed papers.txt entries,
        or ≥1 id missed (reasons on stderr; re-run after outages)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
import urllib.error
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ingest.identifiers import is_valid_arxiv_paper_id
from server.paper_metadata_store import (
    PAPER_METADATA_DB_FILENAME,
    PaperMetadataRecord,
    PaperMetadataStore,
)
from tools import _arxiv_api
from tools._arxiv_api import (
    PaperMetadata,
    build_id_list_url,
    parse_atom_metadata,
    strip_id_version,
)
from tools._notebook_common import (
    NotebookError,
    notebook_dir,
    read_paper_ids_from_papers_txt,
    resolve_contact_email,
    validate_slug,
)
from tools.arxiv_fetch import (
    DEFAULT_503_BACKOFF_SECONDS,
    POLITENESS_SLEEP_SECONDS,
    parse_retry_after,
)

logger = logging.getLogger("notebook_metadata_backfill")

#: ids per id_list request. 127-id notebooks resolve in ~3 requests;
#: well under the 2000/slice API cap, small enough that a poisoned
#: batch's per-id fallback stays cheap.
DEFAULT_BATCH_SIZE: int = 50

#: Attempts per request (initial + retries) before the ids degrade
#: to per-id misses. Bounds the total retry budget so a sustained
#: arXiv outage (25-min windows observed) fails loudly instead of
#: spinning.
MAX_ATTEMPTS_PER_REQUEST: int = 3

#: 429 cool-down. arXiv served plain-text 429s with no Retry-After;
#: 15 s inter-attempt spacing was live-observed to be insufficient.
RATE_LIMIT_BACKOFF_SECONDS: float = 60.0


class _FetchFailure(Exception):
    """A request that exhausted its retry budget; ``reason`` is the
    per-id miss category (``http_503``, ``http_429``, ``network``…)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class _RequestState:
    """Mutable politeness state shared across all requests of a run."""

    requests_made: int = 0
    sleep: Callable[[float], None] = field(default=time.sleep)


def _polite_fetch(url: str, contact_email: str, state: _RequestState) -> bytes:
    """GET ``url`` honoring the politeness + backoff contract.

    Sleeps :data:`POLITENESS_SLEEP_SECONDS` before every request
    except the run's first, retries 503/429 with clamped backoffs,
    and raises :class:`_FetchFailure` once the attempt budget is
    exhausted (callers translate to per-id misses — never a crash).
    """
    attempts = 0
    while True:
        if state.requests_made > 0:
            state.sleep(POLITENESS_SLEEP_SECONDS)
        state.requests_made += 1
        attempts += 1
        try:
            return _arxiv_api._fetch_url(url, contact_email)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 503) or attempts >= MAX_ATTEMPTS_PER_REQUEST:
                logger.warning("giving up on %s: HTTP %s", url, exc.code)
                raise _FetchFailure(f"http_{exc.code}") from exc
            if exc.code == 503:
                # parse_retry_after clamps to >= the default, so the
                # live-observed ``Retry-After: 0`` cannot hammer.
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                backoff = parse_retry_after(retry_after, DEFAULT_503_BACKOFF_SECONDS)
            else:
                backoff = RATE_LIMIT_BACKOFF_SECONDS
            logger.info(
                "HTTP %d (attempt %d/%d); backing off %.0f s",
                exc.code, attempts, MAX_ATTEMPTS_PER_REQUEST, backoff,
            )
            state.sleep(backoff)
        except OSError as exc:
            # URLError / socket timeout / connection reset. 46 s
            # first-byte latencies were live-observed against the
            # 60 s client timeout — retry, then degrade.
            if attempts >= MAX_ATTEMPTS_PER_REQUEST:
                logger.warning("giving up on %s: %s", url, exc)
                raise _FetchFailure("network") from exc
            state.sleep(DEFAULT_503_BACKOFF_SECONDS)


def _fetch_batch_metadata(
    batch: Sequence[str],
    contact_email: str,
    state: _RequestState,
) -> tuple[list[PaperMetadata], list[tuple[str, str]]]:
    """Fetch one id_list batch; return ``(records, missing)``.

    ``records`` carry non-empty title+authors keyed by the REQUESTED
    unversioned id (prefix-preserving mapper); ``missing`` is
    ``(paper_id, reason)`` pairs. A poisoned batch (HTTP-200 error
    feed / non-XML) recurses to per-id requests so one bad response
    cannot zero the batch.
    """
    try:
        xml = _polite_fetch(build_id_list_url(batch), contact_email, state)
    except _FetchFailure as exc:
        return [], [(pid, exc.reason) for pid in batch]
    try:
        entries = parse_atom_metadata(xml)
    except RuntimeError as exc:
        if len(batch) == 1:
            logger.warning("[%s] error feed: %s", batch[0], exc)
            return [], [(batch[0], "error_feed")]
        logger.warning(
            "batch of %d poisoned (%s); falling back to per-id requests",
            len(batch), exc,
        )
        records: list[PaperMetadata] = []
        missing: list[tuple[str, str]] = []
        for pid in batch:
            r, m = _fetch_batch_metadata([pid], contact_email, state)
            records.extend(r)
            missing.extend(m)
        return records, missing

    by_id = {e.paper_id: e for e in entries}
    records = []
    missing = []
    for pid in batch:
        entry = by_id.get(pid)
        if entry is None:
            # Not-found shape is unverified (absent entry / empty
            # entry / error entry) — absent-entry lands here as a
            # per-id miss, never a crash.
            missing.append((pid, "no_entry"))
        elif entry.title and entry.authors:
            records.append(entry)
        else:
            # Row NOT written: hydrated_paper_ids() would skip an
            # empty row forever; leaving it out lets a re-run retry.
            missing.append((pid, "empty_fields"))
    return records, missing


def _to_record(meta: PaperMetadata, fetched_at: str) -> PaperMetadataRecord:
    return PaperMetadataRecord(
        paper_id=meta.paper_id,
        title=meta.title,
        authors=meta.authors,
        abstract=meta.abstract,
        year=meta.year,
        categories=meta.categories,
        primary_category=meta.primary_category,
        published=meta.published,
        fetched_at=fetched_at,
    )


async def _hydrate(
    db_path: Path,
    paper_ids: Sequence[str],
    contact_email: str,
    *,
    batch_size: int,
    sleep: Callable[[float], None],
) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """Hydrate ``paper_ids`` into the store; return
    ``(hydrated, skipped, missing)``."""
    store = await PaperMetadataStore.open(db_path)
    try:
        already = await store.hydrated_paper_ids()
        skipped = [p for p in paper_ids if p in already]
        pending = [p for p in paper_ids if p not in already]

        hydrated: list[str] = []
        missing: list[tuple[str, str]] = []
        state = _RequestState(sleep=sleep)
        for i in range(0, len(pending), batch_size):
            batch = pending[i : i + batch_size]
            records, batch_missing = _fetch_batch_metadata(
                batch, contact_email, state
            )
            if records:
                fetched_at = datetime.now(UTC).isoformat()
                await store.upsert_records(
                    [_to_record(r, fetched_at) for r in records]
                )
                hydrated.extend(r.paper_id for r in records)
            missing.extend(batch_missing)
        return hydrated, skipped, missing
    finally:
        await store.close()


def run(
    slug: str,
    *,
    base: Path | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Backfill metadata for every arXiv id in the notebook's papers.txt.

    ``base`` / ``batch_size`` / ``sleep`` are test seams (mirror the
    ``notebook_fetch.run`` convention); production callers pass only
    ``slug``. Returns the process exit code.
    """
    # Run-entry politeness enforcement: raises NotebookError with the
    # canonical `make init EMAIL=…` remediation if no source has one.
    contact_email = resolve_contact_email(None)
    validate_slug(slug)
    nb_dir = notebook_dir(slug, base=base)
    raw_lines = read_paper_ids_from_papers_txt(nb_dir / "papers.txt")

    # Pre-validate every line (malformed ids poison id_list batches);
    # normalize versioned ids so store rows are keyed unversioned.
    valid_ids: list[str] = []
    malformed: list[str] = []
    seen: set[str] = set()
    for line in raw_lines:
        if is_valid_arxiv_paper_id(line):
            pid = strip_id_version(line)
            if pid not in seen:
                seen.add(pid)
                valid_ids.append(pid)
        else:
            malformed.append(line)

    hydrated, skipped, missing = asyncio.run(
        _hydrate(
            nb_dir / PAPER_METADATA_DB_FILENAME,
            valid_ids,
            contact_email,
            batch_size=batch_size,
            sleep=sleep,
        )
    )

    # Summary line — hydrated/total keeps a zero-row run loud.
    print(
        f"hydrated={len(hydrated)} "
        f"skipped={len(skipped)} "
        f"missing={len(missing)} "
        f"malformed={len(malformed)} "
        f"total={len(raw_lines)}"
    )
    if malformed:
        print("\nmalformed lines in papers.txt (not arXiv IDs):", file=sys.stderr)
        for line in malformed:
            print(f"  {line!r}", file=sys.stderr)
    if missing:
        print(
            "\nmissing metadata — per-id reasons (http_*/network are "
            "recoverable: re-run after the arXiv outage clears):",
            file=sys.stderr,
        )
        for pid, reason in missing:
            print(f"  {pid}  reason={reason}", file=sys.stderr)

    return 1 if (malformed or missing) else 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "slug",
        help="Notebook slug (must match ^[a-z][a-z0-9-]{2,30}$).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        return run(args.slug)
    except NotebookError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
