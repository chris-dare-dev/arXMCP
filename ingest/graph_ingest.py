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
    build_user_agent,
    parse_retry_after,
    validate_paper_id,
)
from tools.fetch_seed import read_seed_list

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

#: Cap on the OpenAlex JSON response body. A real Work record is
#: ~10 KB; 5 MiB is generous for the 99th-percentile response and
#: tight enough to fail fast on a misbehaving / hostile server. Threat
#: 7 (``08-security-observability-ops.md``) requires a meaningful cap;
#: we do NOT inherit ``tools.arxiv_fetch.MAX_RESPONSE_BYTES`` (200 MB)
#: because that constant is calibrated for arXiv source tarballs and
#: would let a malformed CDN response allocate 20,000× more memory
#: than the OpenAlex shape ever needs (F2 from the E09_S01 critique).
OPENALEX_MAX_RESPONSE_BYTES = 5 * 1024 * 1024


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
                body = resp.read(OPENALEX_MAX_RESPONSE_BYTES + 1)
                if len(body) > OPENALEX_MAX_RESPONSE_BYTES:
                    raise RuntimeError(
                        f"OpenAlex response too large for {arxiv_id}: "
                        f">{OPENALEX_MAX_RESPONSE_BYTES} bytes"
                    )
                # E13_S07b — Threat 7 redirect-host pin. urllib follows
                # 30x redirects automatically; ``resp.url`` carries the
                # post-redirect URL. A redirect off api.openalex.org
                # means the body originates from an untrusted host —
                # refuse it rather than ingest poisoned citation data.
                # The trailing "/" closes the prefix-collision hole:
                # ``https://api.openalex.org.evil.com/`` would pass a
                # bare ``startswith`` but is correctly rejected here
                # (the legit URL always has "/" after the host).
                # Mirrors ar5iv_fetch.py / oai_delta.py.
                response_url = resp.url
                if not response_url.startswith(OPENALEX_BASE + "/"):
                    raise RuntimeError(
                        f"OpenAlex response redirected off {OPENALEX_BASE}: "
                        f"got {response_url!r}; refusing as untrusted "
                        f"(Threat 7)"
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
    skeleton = {"resolved": {}, "edges_done": [], "fetch_failures": []}
    if not path.exists():
        return skeleton
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("checkpoint %s unreadable; starting fresh", path)
        return skeleton
    payload.setdefault("resolved", {})
    payload.setdefault("edges_done", [])
    payload.setdefault("fetch_failures", [])
    return payload


def save_checkpoint(path: Path, state: dict[str, Any]) -> None:
    """Atomic checkpoint write (tmp + ``os.replace``).

    A crash mid-write leaves the previous checkpoint intact; the
    rename is atomic on POSIX (and on macOS, ``os.replace`` performs
    the durable swap that ``Path.write_text`` cannot guarantee).

    The temp sibling lives in the same directory as the destination
    (``path.with_suffix(path.suffix + ".tmp")``), so ``os.replace`` is
    intra-filesystem by construction — the cross-device rename failure
    mode is structurally avoided regardless of where the operator
    points ``--checkpoint`` (F7 from the E09_S01 critique).
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
    """Idempotent ``MERGE`` upsert of one ``papers`` node.

    .. note::

        Forward-compat hazard for E09_S02 (INSPIRE-HEP enrichment, F4
        from the E09_S01 critique): the ``ON MATCH SET`` clauses below
        unconditionally overwrite ``title``, ``authors``, etc. with the
        OpenAlex values on every re-MERGE. When E09_S02 lands and adds
        ``doi`` / ``journal_ref`` / ``inspire_id`` columns, an OpenAlex
        re-ingest will not touch those new columns (Cypher's ``SET``
        only writes named properties), but if INSPIRE-HEP populated a
        canonical journal title in ``title``, this re-MERGE would
        clobber it with the OpenAlex preprint title. E09_S02 must
        introduce a per-field source-rank predicate (or split the
        ``_merge_paper`` writers per-source) before adding any
        cross-source enrichment that writes the same columns.
    """
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
        # F3 fix from the E09_S01 critique: track transient-network failures
        # explicitly so a re-run drains them and the CLI returns nonzero
        # while papers remain unresolved. Previously a silent ``continue``
        # left the operator no signal.
        fetch_failures: dict[str, str] = {
            entry["arxiv_id"]: entry.get("error", "")
            for entry in state.get("fetch_failures", [])
            if isinstance(entry, dict) and "arxiv_id" in entry
        }

        # PASS 1: resolution. For each seed paper not yet resolved, fetch
        # OpenAlex, project into _ResolvedWork, and MERGE the papers node.
        # On resume, papers in ``fetch_failures`` are retried (and removed
        # from the failures list on success); previously-resolved papers
        # are re-MERGEd as a no-op for defense-in-depth.
        last_request_at: float | None = None
        new_in_pass = 0
        for arxiv_id in seed_ids:
            if arxiv_id in resolved:
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
                # F3 fix: record the failure so a re-run retries and the
                # CLI surfaces a nonzero exit code while papers remain
                # unresolved. The old "log + continue" path silently lost
                # the failure signal because ``resolved`` had no entry.
                logger.error("openalex fetch failed for %s: %s", arxiv_id, exc)
                fetch_failures[arxiv_id] = str(exc)
                continue
            # Success path — drop any prior failure for this paper.
            fetch_failures.pop(arxiv_id, None)
            rw = _resolved_from_work(work)
            _merge_paper(conn, arxiv_id, rw)
            resolved[arxiv_id] = rw
            new_in_pass += 1
            if new_in_pass % batch_size == 0:
                state["resolved"] = _serialize_resolved(resolved)
                state["edges_done"] = sorted(edges_done)
                state["fetch_failures"] = _serialize_failures(fetch_failures)
                save_checkpoint(checkpoint_path, state)

        # Build oa_work_id → arxiv_id reverse mapping for in-corpus filter.
        # F8 fix: detect duplicate ``oa_work_id`` collisions before they
        # silently last-wins through the dict-comprehension. OpenAlex Work
        # IDs are supposed to be unique per work; a collision usually
        # indicates a withdrawn/replaced version mapping to the same Work
        # and is worth surfacing rather than dropping silently.
        rev_map: dict[str, str] = {}
        oa_id_collisions: dict[str, list[str]] = {}
        for aid, rw in resolved.items():
            if not rw.oa_work_id:
                continue
            existing = rev_map.get(rw.oa_work_id)
            if existing is not None:
                oa_id_collisions.setdefault(rw.oa_work_id, [existing]).append(aid)
            else:
                rev_map[rw.oa_work_id] = aid
        if oa_id_collisions:
            for oa_id, aids in oa_id_collisions.items():
                logger.warning(
                    "oa_work_id collision: %s maps to multiple arxiv ids %s; "
                    "first-wins resolution kept %s",
                    oa_id,
                    sorted(aids),
                    rev_map[oa_id],
                )

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
                state["fetch_failures"] = _serialize_failures(fetch_failures)
                save_checkpoint(checkpoint_path, state)

        # Final checkpoint flush.
        state["resolved"] = _serialize_resolved(resolved)
        state["edges_done"] = sorted(edges_done)
        state["fetch_failures"] = _serialize_failures(fetch_failures)
        save_checkpoint(checkpoint_path, state)
        return state
    finally:
        del db


def _serialize_failures(failures: dict[str, str]) -> list[dict[str, str]]:
    """Serialize ``{arxiv_id: error}`` to a stable on-disk list shape."""
    return [
        {"arxiv_id": aid, "error": err} for aid, err in sorted(failures.items())
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _normalize_source(value: str) -> str:
    """Argparse ``type=`` for ``--source`` that accepts case-insensitive
    aliases.

    F1 fix from the E09_S01 critique: the milestone brief and roadmap
    use ``--source openAlex`` (camelCase), but the original argparse
    declaration was ``choices=["openalex"]`` (lowercase only). An
    operator copy-pasting the brief got an ``invalid choice`` error.
    Accept both casings, canonicalize internally to ``"openalex"``
    so downstream dispatch logic doesn't have to care.

    E09_S02 added a separate ``ingest.inspire_ingest`` module for
    INSPIRE-HEP enrichment (per the split-writer F4 closure). This
    CLI explicitly does NOT dispatch to INSPIRE — pointing operators
    at the right module is more useful than silently no-op'ing on
    ``--source inspire``.
    """
    folded = value.strip().lower()
    if folded == "inspire":
        raise argparse.ArgumentTypeError(
            "INSPIRE-HEP enrichment uses a separate CLI; run "
            "`python -m ingest.inspire_ingest` instead. The "
            "`graph_ingest` CLI dispatches to OpenAlex only."
        )
    if folded != "openalex":
        # argparse converts ValueError into a friendly usage error.
        raise argparse.ArgumentTypeError(
            f"unsupported source: {value!r}. The graph_ingest CLI "
            "supports 'openalex' / 'openAlex' only."
        )
    return "openalex"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=_normalize_source,
        default="openalex",
        help=(
            "citation-edge source. Accepts either casing the brief uses "
            "('openAlex' / 'openalex'); both canonicalize to 'openalex'. "
            "INSPIRE-HEP lands in E09_S02."
        ),
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

    # F5 fix: reuse ``tools.fetch_seed.read_seed_list`` rather than
    # carrying a local copy. The two parsers were behaviorally identical
    # and would have drifted if either added BOM handling, # suffix
    # comments, or paper-id validation.
    seed_ids = read_seed_list(args.seed_file)
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

    failures = state.get("fetch_failures", [])
    logger.info(
        "done: %d papers resolved, %d papers had edges processed, "
        "%d transient fetch failures still pending",
        len(state.get("resolved", {})),
        len(state.get("edges_done", [])),
        len(failures),
    )
    if failures:
        # F3 fix: a transient-network-error path was previously logged and
        # silently swallowed. Surface it as a non-zero exit so the
        # operator notices and re-runs (the resume path will retry).
        sys.stderr.write(
            f"WARNING: {len(failures)} paper(s) hit transient network "
            "errors during the OpenAlex resolution pass and were not "
            "added to the graph. Re-run this command to retry; the "
            f"checkpoint at {args.checkpoint} preserves progress.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
