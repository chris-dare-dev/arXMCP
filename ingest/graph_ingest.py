"""OpenAlex bulk citation ingest into the Kùzu graph (E09_S01).

Iterates over ``tools/seed-papers.txt``, resolves each arXiv ID to an
OpenAlex Work, fetches the work's ``referenced_works`` list, and writes
``papers`` nodes plus ``cites`` edges to the Kùzu graph.

Two-pass shape (per ``research-synthesis.md`` § 3):

1. **Resolution.** For each seed arXiv ID, GET the OpenAlex Work and
   record ``(arxiv_id → oa_work_id, references)`` in memory and on
   disk. Always create the ``papers`` node — when the paper is not in
   OpenAlex, the node is written with ``oa_work_id = NULL`` and an
   empty references list (AC#3 + risk-note "Papers not found in
   OpenAlex are still added as `papers` nodes").
2. **Citation.** For each resolved paper, walk its ``referenced_works``
   list and emit a ``cites`` edge ONLY when the cited OA work ID maps
   back to an arXiv ID in the corpus reverse mapping. Cross-corpus
   references are silently dropped (AC#4 — only in-corpus pairs).

The ``referenced_works`` list is a list of OpenAlex Work URL strings
(e.g. ``"https://openalex.org/W272048707"``); the URL prefix is
stripped to get the bare ``W…`` ID before the reverse-mapping lookup
(see ``_strip_oa_url``).

Politeness contract (mirrors ``tools/arxiv_fetch.py`` for arXiv):

- ``User-Agent`` header: ``arXMCP/0.1 (mailto:<email>)``. Reuses
  ``tools.arxiv_fetch.build_user_agent`` so the contact email is
  sourced from ``ARXMCP_CONTACT_EMAIL`` once.
- ``?mailto=<email>`` query string on every URL. OpenAlex docs prefer
  this form; the User-Agent header alone satisfies AC#7. Sending both
  costs nothing and matches the design note's "header or query
  parameter" phrasing.
- Inter-request sleep: ``OPENALEX_POLITE_SLEEP_SECONDS = 0.1`` (10
  rps polite-pool cap; the brief's stated rate).
- 429 / 503 backoff: ``Retry-After`` honored via
  ``tools.arxiv_fetch.parse_retry_after``; default 30 s, capped at
  300 s, exponential between retries.

Checkpointing: the entire resolved-state dict is rewritten to
``var/arxmcp/ops/graph-ingest-checkpoint.json`` after each batch of
``CHECKPOINT_BATCH_SIZE = 100`` papers. The write is atomic
(tmp + ``os.replace``) so a crash mid-write cannot corrupt the file
(AC#5/#6).

Idempotency: DDL via ``CREATE … IF NOT EXISTS`` (handled by
``ingest.kuzudb_schema.apply_schema``). Inserts and edges via Cypher
``MERGE`` upserts. Re-running the script after an interruption skips
papers that are already in the checkpoint's ``resolved`` set without
re-fetching from OpenAlex (AC#6); the Kùzu graph itself is the
ultimate source-of-truth — if a paper is in the graph but missing
from the checkpoint, the resolution pass will issue a ``MERGE`` that
is functionally a no-op.

Out of scope for this milestone:

- The ``--category math.AG math.NT`` discovery path (raises
  ``NotImplementedError``). The brief's stated OpenAlex Concept IDs
  ``C66938386`` and ``C15736585`` were verified live as wrong /
  deprecated (``C66938386`` resolves to "Structural engineering";
  ``C15736585`` returns 404). The correct concept IDs are
  ``C68363185`` (algebraic geometry) and ``C169654258`` (number
  theory), but Concepts themselves are deprecated in favor of
  ``primary_topic`` / ``topics`` filters. Tier-3 category-bulk
  discovery will land in a future milestone using Topics.
- INSPIRE-HEP enrichment (E09_S02).
- ``cite_neighbors`` query API (E09_S03).
- Intra-paper ``\\ref{}`` chain tracing (E09_S03).

CLI::

    python -m ingest.graph_ingest \\
        --source openalex \\
        --seed-file tools/seed-papers.txt \\
        --checkpoint var/arxmcp/ops/graph-ingest-checkpoint.json \\
        --kuzudb var/arxmcp/index/kuzu/

Live HTTP calls hit ``api.openalex.org`` and require
``ARXMCP_CONTACT_EMAIL`` in the environment. Tests must mock
``_fetch_openalex_work`` via ``monkeypatch.setattr``; never let live
calls leak into CI.
"""

from __future__ import annotations

import argparse
import http
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import kuzu

from ingest.kuzudb_schema import apply_schema
from tools.arxiv_fetch import (
    DEFAULT_503_BACKOFF_SECONDS,
    MAX_503_BACKOFF_SECONDS,
    MAX_RESPONSE_BYTES,
    build_user_agent,
    parse_retry_after,
    validate_paper_id,
)

logger = logging.getLogger(__name__)

#: OpenAlex API base. Identifier-resolution uses ``/works/<URL-encoded
#: external-id>`` so the arXiv URL is composable directly.
OPENALEX_BASE = "https://api.openalex.org"

#: Polite-pool inter-request sleep. Brief specifies 10 rps (= 0.1 s
#: between calls). Override via ``ingest()`` for tests.
OPENALEX_POLITE_SLEEP_SECONDS = 0.1

#: Acceptance criterion #5 — write the checkpoint after each batch of
#: this many papers processed.
CHECKPOINT_BATCH_SIZE = 100

#: Per-paper HTTP timeout. OpenAlex Works responses are ~10 KB.
OPENALEX_TIMEOUT_SECONDS = 30.0

#: Maximum HTTP-error retries for transient (5xx / 429) failures.
MAX_HTTP_RETRIES = 3


@dataclass(frozen=True)
class _ResolvedWork:
    """Per-paper output of the resolution pass."""

    oa_work_id: str | None  # bare W… id, or None if paper not in OpenAlex
    title: str
    abstract: str
    authors: str
    year: int | None
    categories: str
    referenced_works: tuple[str, ...]  # bare W… ids


# ---------------------------------------------------------------------------
# OpenAlex HTTP layer (mock target)
# ---------------------------------------------------------------------------


def _build_works_url(arxiv_id: str, contact_email: str) -> str:
    """Construct the OpenAlex Works URL for a given arXiv ID.

    OpenAlex resolves external identifiers in the path component, so
    ``/works/https%3A%2F%2Farxiv.org%2Fabs%2F<id>`` is the canonical
    form for an arXiv-ID lookup. The ``?mailto=`` query parameter
    enrols the request in the polite pool.
    """
    inner = f"https://arxiv.org/abs/{arxiv_id}"
    encoded = urllib.parse.quote(inner, safe="")
    mailto = urllib.parse.quote_plus(contact_email)
    return f"{OPENALEX_BASE}/works/{encoded}?mailto={mailto}"


def _fetch_openalex_work(
    arxiv_id: str, contact_email: str, *, timeout: float = OPENALEX_TIMEOUT_SECONDS
) -> dict[str, Any] | None:
    """Fetch one OpenAlex Work by its arXiv ID. Returns None on 404.

    Honors the User-Agent + ``?mailto=`` polite-pool contract. Retries
    on 429 / 503 with ``Retry-After`` honoring (default 30 s, cap 300
    s, exponential). Other HTTP errors propagate to the caller.

    THIS FUNCTION IS THE INTEGRATION-TEST MOCK TARGET. Tests use
    ``monkeypatch.setattr(graph_ingest, "_fetch_openalex_work", ...)``
    to substitute a fixture-driven stub. Never let live calls leak
    into CI.
    """
    url = _build_works_url(arxiv_id, contact_email)
    backoff = DEFAULT_503_BACKOFF_SECONDS
    attempts = 0
    while True:
        attempts += 1
        request = urllib.request.Request(  # noqa: S310 — fixed api.openalex.org host
            url, headers={"User-Agent": build_user_agent(contact_email)}
        )
        try:
            with urllib.request.urlopen(  # noqa: S310
                request, timeout=timeout
            ) as resp:
                body = resp.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise RuntimeError(
                        f"OpenAlex response too large for {arxiv_id}: "
                        f">{MAX_RESPONSE_BYTES} bytes"
                    )
                return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == http.HTTPStatus.NOT_FOUND.value:
                return None
            transient = exc.code in (
                http.HTTPStatus.TOO_MANY_REQUESTS.value,
                http.HTTPStatus.SERVICE_UNAVAILABLE.value,
            )
            if transient and attempts <= MAX_HTTP_RETRIES:
                wait = parse_retry_after(exc.headers.get("Retry-After"), backoff)
                logger.warning(
                    "openalex %s for %s; retrying in %.0fs (attempt %d/%d)",
                    exc.code,
                    arxiv_id,
                    wait,
                    attempts,
                    MAX_HTTP_RETRIES,
                )
                time.sleep(wait)
                backoff = min(backoff * 2, MAX_503_BACKOFF_SECONDS)
                continue
            raise


# ---------------------------------------------------------------------------
# OpenAlex Work parsers
# ---------------------------------------------------------------------------


def _strip_oa_url(value: str) -> str:
    """Strip the ``https://openalex.org/`` prefix to get the bare W… ID."""
    prefix = "https://openalex.org/"
    if value.startswith(prefix):
        return value[len(prefix) :]
    return value


def _reconstruct_abstract(work: dict[str, Any]) -> str:
    """Reconstruct OpenAlex's abstract from its inverted-index form.

    OpenAlex stores abstracts as ``{word: [positions, ...], ...}`` for
    storage efficiency. Reassemble by sorting positions back into the
    original word order. Returns an empty string when the index is
    absent.
    """
    inv = work.get("abstract_inverted_index")
    if not inv:
        return ""
    positions: dict[int, str] = {}
    for word, posns in inv.items():
        for p in posns:
            positions[p] = word
    return " ".join(positions[i] for i in sorted(positions))


def _format_authors(authorships: list[dict[str, Any]] | None) -> str:
    """Comma-join author display names from an OpenAlex authorships list."""
    if not authorships:
        return ""
    names: list[str] = []
    for entry in authorships:
        author = entry.get("author") or {}
        name = author.get("display_name")
        if name:
            names.append(name)
    return ", ".join(names)


def _format_categories(work: dict[str, Any]) -> str:
    """Build a comma-joined category string from OpenAlex topics.

    Combines ``primary_topic.display_name`` with the remaining
    ``topics[*].display_name`` entries (deduped, preserving order).
    OpenAlex does not natively carry arXiv categories — Topics are the
    closest equivalent. Empty when neither field is present.
    """
    seen: dict[str, None] = {}
    primary = (work.get("primary_topic") or {}).get("display_name")
    if primary:
        seen[primary] = None
    for topic in work.get("topics") or []:
        name = (topic or {}).get("display_name")
        if name and name not in seen:
            seen[name] = None
    return ", ".join(seen)


def _resolved_from_work(work: dict[str, Any] | None) -> _ResolvedWork:
    """Project an OpenAlex Work dict into the dataclass we persist.

    Returns a "blank" record (oa_work_id None, empty references) when
    ``work`` is None — the paper-not-in-OpenAlex case (AC risk-note).
    """
    if work is None:
        return _ResolvedWork(
            oa_work_id=None,
            title="",
            abstract="",
            authors="",
            year=None,
            categories="",
            referenced_works=(),
        )
    oa_work_id = _strip_oa_url(work.get("id") or "") or None
    refs = tuple(_strip_oa_url(r) for r in (work.get("referenced_works") or []) if r)
    return _ResolvedWork(
        oa_work_id=oa_work_id,
        title=work.get("title") or "",
        abstract=_reconstruct_abstract(work),
        authors=_format_authors(work.get("authorships")),
        year=work.get("publication_year"),
        categories=_format_categories(work),
        referenced_works=refs,
    )


# ---------------------------------------------------------------------------
# Checkpoint I/O
# ---------------------------------------------------------------------------


def _serialize_resolved(resolved: dict[str, _ResolvedWork]) -> dict[str, Any]:
    return {
        arxiv_id: {
            "oa_work_id": rw.oa_work_id,
            "title": rw.title,
            "abstract": rw.abstract,
            "authors": rw.authors,
            "year": rw.year,
            "categories": rw.categories,
            "referenced_works": list(rw.referenced_works),
        }
        for arxiv_id, rw in resolved.items()
    }


def _deserialize_resolved(payload: dict[str, Any]) -> dict[str, _ResolvedWork]:
    out: dict[str, _ResolvedWork] = {}
    for arxiv_id, raw in payload.items():
        out[arxiv_id] = _ResolvedWork(
            oa_work_id=raw.get("oa_work_id"),
            title=raw.get("title") or "",
            abstract=raw.get("abstract") or "",
            authors=raw.get("authors") or "",
            year=raw.get("year"),
            categories=raw.get("categories") or "",
            referenced_works=tuple(raw.get("referenced_works") or ()),
        )
    return out


def load_checkpoint(path: Path) -> dict[str, Any]:
    """Load checkpoint or return a fresh skeleton if absent / unreadable."""
    if not path.exists():
        return {"resolved": {}, "edges_done": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("checkpoint %s unreadable; starting fresh", path)
        return {"resolved": {}, "edges_done": []}
    payload.setdefault("resolved", {})
    payload.setdefault("edges_done", [])
    return payload


def save_checkpoint(path: Path, state: dict[str, Any]) -> None:
    """Atomic checkpoint write (tmp + ``os.replace``).

    A crash mid-write leaves the previous checkpoint intact; the
    rename is atomic on POSIX (and on macOS, ``os.replace`` performs
    the durable swap that ``Path.write_text`` cannot guarantee).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(state, indent=2, sort_keys=True) + "\n"
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Kùzu writers
# ---------------------------------------------------------------------------


def _merge_paper(conn: kuzu.Connection, arxiv_id: str, rw: _ResolvedWork) -> None:
    """Idempotent ``MERGE`` upsert of one ``papers`` node."""
    conn.execute(
        """
        MERGE (p:papers {paper_id: $paper_id})
        ON CREATE SET
            p.title = $title,
            p.abstract = $abstract,
            p.authors = $authors,
            p.year = $year,
            p.categories = $categories,
            p.oa_work_id = $oa_work_id
        ON MATCH SET
            p.title = $title,
            p.abstract = $abstract,
            p.authors = $authors,
            p.year = $year,
            p.categories = $categories,
            p.oa_work_id = $oa_work_id
        """,
        {
            "paper_id": arxiv_id,
            "title": rw.title,
            "abstract": rw.abstract,
            "authors": rw.authors,
            "year": rw.year,
            "categories": rw.categories,
            "oa_work_id": rw.oa_work_id,
        },
    )


def _merge_cite(
    conn: kuzu.Connection,
    src_paper_id: str,
    dst_paper_id: str,
    source: str,
    confidence: float,
) -> None:
    """Idempotent ``MERGE`` upsert of one ``cites`` edge.

    Both endpoints must already exist as ``papers`` nodes. The
    ``MATCH`` clause looks them up; if either is missing the statement
    is a no-op (the ``MERGE`` never fires) — so the resolution pass
    must run before the citation pass.
    """
    conn.execute(
        """
        MATCH (a:papers {paper_id: $src}), (b:papers {paper_id: $dst})
        MERGE (a)-[r:cites {source: $source}]->(b)
        ON CREATE SET r.confidence = $confidence
        ON MATCH SET r.confidence = $confidence
        """,
        {
            "src": src_paper_id,
            "dst": dst_paper_id,
            "source": source,
            "confidence": confidence,
        },
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def ingest(
    seed_ids: list[str],
    db_path: Path,
    checkpoint_path: Path,
    contact_email: str,
    *,
    fetch_fn: Callable[[str, str], dict[str, Any] | None] | None = None,
    sleep_seconds: float = OPENALEX_POLITE_SLEEP_SECONDS,
    batch_size: int = CHECKPOINT_BATCH_SIZE,
) -> dict[str, Any]:
    """Run the two-pass ingest. Returns the final checkpoint state.

    Args:
        seed_ids: ordered list of arXiv IDs (already validated upstream;
            this function asserts each via ``validate_paper_id`` for
            defense-in-depth — Threat 1, ``08-security-observability-ops.md``).
        db_path: Kùzu database directory. Created if missing.
        checkpoint_path: JSON file persisted after every batch.
        contact_email: passed through ``build_user_agent`` and into the
            ``?mailto=`` query parameter on every OpenAlex request.
        fetch_fn: HTTP fetcher override (None = use this module's
            ``_fetch_openalex_work``, looked up at call time so
            ``monkeypatch.setattr`` on the module attribute takes effect).
            A bound default would be resolved at function-definition
            time and would prevent test monkeypatches from working —
            the explicit None sentinel pattern is required for that.
        sleep_seconds: inter-request sleep. Tests pass 0 to skip.
        batch_size: checkpoint flush cadence (AC#5).

    Returns:
        The final checkpoint state dict. Useful for tests; the CLI
        ignores it.
    """
    if fetch_fn is None:
        fetch_fn = _fetch_openalex_work
    for arxiv_id in seed_ids:
        validate_paper_id(arxiv_id)

    apply_schema(db_path)
    db = kuzu.Database(str(db_path))
    try:
        conn = kuzu.Connection(db)
        state = load_checkpoint(checkpoint_path)
        resolved = _deserialize_resolved(state.get("resolved", {}))
        edges_done: set[str] = set(state.get("edges_done", []))

        # PASS 1: resolution. For each seed paper not yet resolved, fetch
        # OpenAlex, project into _ResolvedWork, and MERGE the papers node.
        last_request_at: float | None = None
        new_in_pass = 0
        for arxiv_id in seed_ids:
            if arxiv_id in resolved:
                # Defense-in-depth: re-MERGE the node anyway in case the
                # checkpoint and graph have drifted (e.g. checkpoint was
                # restored from backup but Kùzu was wiped). The MERGE is a
                # functional no-op when both already match.
                _merge_paper(conn, arxiv_id, resolved[arxiv_id])
                continue
            if last_request_at is not None and sleep_seconds > 0:
                elapsed = time.monotonic() - last_request_at
                if elapsed < sleep_seconds:
                    time.sleep(sleep_seconds - elapsed)
            last_request_at = time.monotonic()
            try:
                work = fetch_fn(arxiv_id, contact_email)
            except urllib.error.URLError as exc:
                logger.error("openalex fetch failed for %s: %s", arxiv_id, exc)
                continue
            rw = _resolved_from_work(work)
            _merge_paper(conn, arxiv_id, rw)
            resolved[arxiv_id] = rw
            new_in_pass += 1
            if new_in_pass % batch_size == 0:
                state["resolved"] = _serialize_resolved(resolved)
                state["edges_done"] = sorted(edges_done)
                save_checkpoint(checkpoint_path, state)

        # Build oa_work_id → arxiv_id reverse mapping for in-corpus filter.
        rev_map: dict[str, str] = {
            rw.oa_work_id: aid for aid, rw in resolved.items() if rw.oa_work_id
        }

        # PASS 2: citation. Walk references and emit cites edges only when
        # the cited OA work id is in the corpus reverse map.
        new_edges_pass = 0
        for arxiv_id, rw in resolved.items():
            if arxiv_id in edges_done:
                continue
            for ref_oa_id in rw.referenced_works:
                cited_arxiv = rev_map.get(ref_oa_id)
                if cited_arxiv is None:
                    continue
                _merge_cite(
                    conn,
                    src_paper_id=arxiv_id,
                    dst_paper_id=cited_arxiv,
                    source="openAlex",
                    confidence=1.0,
                )
            edges_done.add(arxiv_id)
            new_edges_pass += 1
            if new_edges_pass % batch_size == 0:
                state["resolved"] = _serialize_resolved(resolved)
                state["edges_done"] = sorted(edges_done)
                save_checkpoint(checkpoint_path, state)

        # Final checkpoint flush.
        state["resolved"] = _serialize_resolved(resolved)
        state["edges_done"] = sorted(edges_done)
        save_checkpoint(checkpoint_path, state)
        return state
    finally:
        del db


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _read_seed_ids(path: Path) -> list[str]:
    """Read paper IDs from a seed file (lines starting with ``#`` are
    comments; blank lines are skipped). Mirrors
    ``tools.fetch_seed.read_seed_list`` to avoid pulling that module in
    via a transitive dep on the ingest path."""
    ids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        ids.append(stripped)
    return ids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        choices=["openalex"],
        default="openalex",
        help="citation-edge source. Only 'openalex' is supported in E09_S01.",
    )
    parser.add_argument(
        "--seed-file",
        type=Path,
        default=Path("tools/seed-papers.txt"),
        help="path to the arXiv-ID seed list (default: tools/seed-papers.txt)",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("var/arxmcp/ops/graph-ingest-checkpoint.json"),
        help="atomic-write checkpoint path (rewritten after each batch)",
    )
    parser.add_argument(
        "--kuzudb",
        type=Path,
        default=Path("var/arxmcp/index/kuzu"),
        help=(
            "Kùzu DB directory (default: var/arxmcp/index/kuzu — matches "
            "Makefile bootstrap and 05-storage-and-indexing.md)"
        ),
    )
    parser.add_argument(
        "--category",
        nargs="+",
        default=None,
        help=(
            "[NOT IMPLEMENTED] Tier-3 category-bulk discovery via OpenAlex "
            "Topics. The brief's stated Concept IDs were verified live as "
            "wrong/deprecated; a future milestone will implement the "
            "Topics-based path. Use --seed-file for the Tier-3-testable "
            "seed-corpus path that is required by the milestone AC."
        ),
    )
    args = parser.parse_args(argv)

    if args.category:
        sys.stderr.write(
            "ERROR: --category bulk discovery is not implemented in E09_S01.\n"
            "       The brief's stated OpenAlex Concept IDs (C66938386, "
            "C15736585) were\n"
            "       verified live as wrong / deprecated; a future "
            "milestone will land\n"
            "       Topics-based discovery. Use --seed-file for the "
            "in-scope seed path.\n"
        )
        return 2

    contact_email = os.environ.get("ARXMCP_CONTACT_EMAIL")
    if not contact_email:
        sys.stderr.write(
            "ERROR: ARXMCP_CONTACT_EMAIL is required for OpenAlex polite-pool "
            "compliance.\n"
            "       Export it in your shell before running this script.\n"
        )
        return 2

    seed_ids = _read_seed_ids(args.seed_file)
    if not seed_ids:
        sys.stderr.write(f"ERROR: seed file {args.seed_file} contains no IDs\n")
        return 2

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info(
        "ingesting %d seed paper(s) into %s (checkpoint: %s)",
        len(seed_ids),
        args.kuzudb,
        args.checkpoint,
    )

    try:
        state = ingest(
            seed_ids=seed_ids,
            db_path=args.kuzudb,
            checkpoint_path=args.checkpoint,
            contact_email=contact_email,
        )
    except KeyboardInterrupt:
        logger.warning("interrupted by user; checkpoint preserved.")
        return 130

    logger.info(
        "done: %d papers resolved, %d papers had edges processed",
        len(state.get("resolved", {})),
        len(state.get("edges_done", [])),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
