"""INSPIRE-HEP per-paper enrichment of the citation graph (E09_S02).

Iterates over every ``papers`` node already in the Kùzu graph (or a
caller-provided seed list), GETs the paper's INSPIRE-HEP record, and
writes:

- ``papers`` node enrichment via ``_merge_paper_inspire``: sets the
  three INSPIRE-exclusive columns ``doi``, ``journal_ref``,
  ``inspire_id``. Does **NOT** touch ``title`` / ``abstract`` /
  ``authors`` / ``year`` / ``categories`` — those remain owned by the
  OpenAlex resolver. This split-writer ownership rule is the F4
  closure from the E09_S01 critique; both writers' source-of-truth
  surface is structural, not predicate-based.
- ``cites`` edges via the shared ``ingest.graph_ingest._merge_cite``
  with ``source="inspire"``, ``confidence=1.0``. Because the source
  string is part of the edge's MERGE key, an INSPIRE edge is a
  *distinct* relationship from an OpenAlex edge for the same
  ``(src, dst)`` pair — AC#3 ("existing source=openAlex edges are not
  duplicated or overwritten") is satisfied by construction.

INSPIRE-HEP record shape (verified live for ``arxiv/1207.7214``):

- ``metadata.control_number`` (int) → cast to STRING for ``inspire_id``.
- ``metadata.dois[0].value`` → ``doi``.
- ``metadata.publication_info[0]`` → concatenated into ``journal_ref``.
- ``metadata.arxiv_eprints[*].categories`` → used post-fetch to gate
  metadata writes on the hep-th / math-ph filter (the brief's stated
  ``categories LIKE`` filter is unsatisfiable on the current
  ``papers.categories`` column shape — it carries OpenAlex Topics,
  not arXiv categories. F9 from the E09_S01 critique. The post-fetch
  gate makes INSPIRE itself the classifier).
- ``metadata.references[*].reference.arxiv_eprint`` → bare arXiv ID
  directly usable as ``paper_id`` in the existing graph; no second
  lookup needed for the in-corpus reverse-map filter.

There is **no** inline ``citations`` field on the record. Forward
citations would require a paginated ``?q=refersto:recid:<n>`` search
and are deferred behind the ``--include-back-refs`` CLI flag (default
off). The brief's "both `references` and `citations`" framing is
half-true; ``references`` alone closes most of AC#2's surface.

Politeness contract:

- ``User-Agent`` reuses ``tools.arxiv_fetch.build_user_agent`` →
  ``arXMCP/0.1 (mailto:<ARXMCP_CONTACT_EMAIL>)``.
- INSPIRE-HEP does not document a ``mailto`` query parameter; do not
  send one. ``Accept: application/json`` per the API.
- Inter-request sleep ``INSPIRE_POLITE_SLEEP_SECONDS = 0.25`` (3.3
  rps; under the brief's ≤5/sec AC and INSPIRE's documented "15
  requests / 5-second window" sustained limit).
- 429 floor ``INSPIRE_429_FLOOR_SECONDS = 5.0`` per the docs (the
  rate-limited request still counts toward the quota; waiting < 5 s
  is wasted).

Idempotency:

- DDL: ``ingest.kuzudb_schema.apply_schema`` is idempotent (v1 ``IF
  NOT EXISTS`` + v2 introspect-and-ALTER) and bumps
  ``KUZU_SCHEMA_VERSION = 2``.
- Inserts: ``MERGE`` upserts both for nodes (only the three
  INSPIRE-exclusive columns) and edges.
- Resume: re-running with the same checkpoint skips already-resolved
  papers; failed-fetch IDs (URLError) are tracked in
  ``state["fetch_failures"]`` and drained on subsequent runs (F3
  pattern, mirroring ``graph_ingest``).

Out of scope (explicit):

- The arXiv ``categories`` column rename (F9 deferral).
- A real arXiv-category fetcher (would unblock the brief's
  ``categories LIKE '%hep-th%'`` filter).
- The OpenAlex ``_merge_paper`` writer is unchanged.

CLI::

    python -m ingest.inspire_ingest \\
        --checkpoint var/arxmcp/ops/inspire-ingest-checkpoint.json \\
        --kuzudb var/arxmcp/index/kuzu/

Operator-time HTTP traffic hits ``inspirehep.net``. Tests must
``monkeypatch.setattr(inspire_ingest, "_fetch_inspire_record", _stub)``;
CI never makes live calls.
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
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import kuzu

from ingest.graph_ingest import (
    _merge_cite,
    _serialize_failures,
    load_checkpoint,
    save_checkpoint,
)
from ingest.identifiers import is_valid_paper_id
from ingest.kuzudb_schema import apply_schema
from tools.arxiv_fetch import (
    DEFAULT_503_BACKOFF_SECONDS,
    MAX_503_BACKOFF_SECONDS,
    build_user_agent,
    parse_retry_after,
)


def _validate_paper_id_either_style(paper_id: str) -> None:
    """Validate an arXiv ID in either new-style (``YYMM.NNNNN``) or
    old-style (``subject/NNNNNNN``) form.

    F2 fix from the E09_S02 critique. ``tools.arxiv_fetch.validate_paper_id``
    rejects old-style IDs by design (the seed corpus is post-2010). But
    INSPIRE-HEP enrichment specifically targets hep-th / math-ph, where
    a substantial fraction of the literature predates 2007 and uses
    old-style IDs (e.g. ``hep-th/9711200`` — Maldacena AdS/CFT). The
    enrich() entry validator must accept both forms; the source-of-truth
    regex lives in ``ingest.identifiers`` which already covers this.
    """
    if not is_valid_paper_id(paper_id):
        raise ValueError(
            f"paper_id {paper_id!r} is not a valid arXiv ID "
            "(expected YYMM.NNNNN[N] new-style or subject/NNNNNNN old-style)."
        )

logger = logging.getLogger(__name__)

#: INSPIRE-HEP REST API base.
INSPIRE_API_BASE = "https://inspirehep.net/api"

#: Inter-request sleep. INSPIRE-HEP documents a 15-request /
#: 5-second window (= 3 rps sustained). The brief asks for ≤ 5/sec.
#: 0.25 s gives ~4 rps headroom to the AC and stays comfortably under
#: the documented limit.
INSPIRE_POLITE_SLEEP_SECONDS = 0.25

#: Floor on the post-429 wait. Per the INSPIRE docs the rate-limited
#: request still counts toward the quota, so any wait shorter than
#: 5 seconds is wasted.
INSPIRE_429_FLOOR_SECONDS = 5.0

#: Cap on the response body. Empirical: a paper with ~150 references
#: and authors stripped via ``?fields=`` is ~150 KB; a 1000-reference
#: paper might hit ~1 MB. 8 MiB is generous and far below the
#: 200 MB arXiv tarball cap (which would be wildly inappropriate
#: here — F2 from the E09_S01 critique). 200 MB is the failure mode
#: we explicitly avoid.
INSPIRE_MAX_RESPONSE_BYTES = 8 * 1024 * 1024

#: Per-paper HTTP timeout. INSPIRE responses are small with the
#: ``?fields=`` filter applied.
INSPIRE_TIMEOUT_SECONDS = 30.0

#: Maximum HTTP-error retries for transient (5xx / 429) failures.
MAX_HTTP_RETRIES = 3

#: AC#5 — atomic checkpoint write cadence (papers / batch).
CHECKPOINT_BATCH_SIZE = 100

#: Pinned response field set. Drops ``authors`` + ``abstracts`` etc.
#: which are large and not needed for the enrichment goal. Cuts
#: response body ~10× on author-heavy collaboration papers (e.g.
#: ATLAS: hundreds of authors). Reduces parse surface area too —
#: a future field rename only breaks fields we actually depend on.
INSPIRE_FIELDS_REQUEST = (
    "control_number,arxiv_eprints,dois,publication_info,"
    "collaborations,references"
)

#: arXiv categories that gate the post-fetch metadata write. The
#: brief targets hep-th and math-ph; if a paper resolves to an
#: INSPIRE record but its ``arxiv_eprints[*].categories`` does not
#: intersect this set, the metadata is NOT written and edges are
#: NOT emitted (defensive against non-physics papers that happen to
#: have INSPIRE records).
PHYSICS_CATEGORIES = frozenset({"hep-th", "math-ph"})


@dataclass(frozen=True)
class _ResolvedInspire:
    """Per-paper output of the INSPIRE resolution pass.

    Parallels ``graph_ingest._ResolvedWork`` but covers the three
    INSPIRE-exclusive columns plus the references list. Source
    ownership is structural — this dataclass never carries fields
    OpenAlex owns (``title``, ``authors``, etc.) so a multi-source
    write protocol mismatch can't introduce data drift at the
    dataclass layer.
    """

    inspire_id: str | None
    doi: str | None
    journal_ref: str | None
    references_arxiv: tuple[str, ...]
    arxiv_categories: tuple[str, ...]


# ---------------------------------------------------------------------------
# INSPIRE-HEP HTTP layer (mock target)
# ---------------------------------------------------------------------------


def _build_record_url(arxiv_id: str) -> str:
    """Construct the INSPIRE-HEP per-arxiv-id record URL.

    The ``?fields=`` filter is included to drop the large ``authors``
    and ``abstracts`` blobs we don't need (response-size discipline,
    reduces drift surface for the F2 cap and for snapshot tests).
    """
    encoded_id = urllib.parse.quote(arxiv_id, safe="")
    fields = urllib.parse.quote(INSPIRE_FIELDS_REQUEST, safe=",")
    return f"{INSPIRE_API_BASE}/arxiv/{encoded_id}?fields={fields}"


def _fetch_inspire_record(
    arxiv_id: str,
    contact_email: str,
    *,
    timeout: float = INSPIRE_TIMEOUT_SECONDS,
) -> dict[str, Any] | None:
    """Fetch one INSPIRE-HEP record by its arXiv ID. Returns None on 404.

    Honors the User-Agent contract; 429 / 503 retries with
    ``Retry-After`` honoring (5 s floor on 429 per INSPIRE docs).
    Other HTTP errors propagate. Caps the body at
    ``INSPIRE_MAX_RESPONSE_BYTES``.

    Validates ``arxiv_id`` against the new- and old-style arXiv
    regexes BEFORE issuing any network I/O — defense-in-depth for
    Threat 1 (``08-security-observability-ops.md``) so a future direct
    caller bypassing ``enrich()`` can't smuggle malicious input to
    ``urllib.parse.quote``. F5 fix from the E09_S02 critique.

    THIS FUNCTION IS THE INTEGRATION-TEST MOCK TARGET. Tests use
    ``monkeypatch.setattr(inspire_ingest, "_fetch_inspire_record",
    _stub)`` to substitute a fixture-driven stub. Never let live
    calls leak into CI.
    """
    _validate_paper_id_either_style(arxiv_id)
    url = _build_record_url(arxiv_id)
    backoff = DEFAULT_503_BACKOFF_SECONDS
    attempts = 0
    while True:
        attempts += 1
        request = urllib.request.Request(  # noqa: S310 — fixed inspirehep.net host
            url,
            headers={
                "User-Agent": build_user_agent(contact_email),
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(  # noqa: S310
                request, timeout=timeout
            ) as resp:
                body = resp.read(INSPIRE_MAX_RESPONSE_BYTES + 1)
                if len(body) > INSPIRE_MAX_RESPONSE_BYTES:
                    raise RuntimeError(
                        f"INSPIRE response too large for {arxiv_id}: "
                        f">{INSPIRE_MAX_RESPONSE_BYTES} bytes"
                    )
                # E13_S07b — Threat 7 redirect-host pin. urllib follows
                # 30x redirects automatically; ``resp.url`` carries the
                # post-redirect URL. A redirect off inspirehep.net/api
                # means the body originates from an untrusted host —
                # refuse it rather than ingest poisoned citation data.
                # The trailing "/" closes the prefix-collision hole:
                # ``https://inspirehep.net/apiEVIL`` would pass a bare
                # ``startswith`` but is correctly rejected here (the
                # legit URL always has "/" after the api base).
                # Mirrors ar5iv_fetch.py / oai_delta.py.
                #
                # FAIL-CLOSED SEMANTICS (deliberate — do not downgrade):
                # this RuntimeError is NOT a urllib.error.URLError, so
                # ``enrich()``'s per-paper ``except URLError`` handler
                # does NOT catch it. A poisoned redirect therefore
                # aborts the whole enrich run, not just one paper —
                # consistent with the over-size RuntimeError above. A
                # redirect off the pinned host is a signal the upstream
                # is compromised; continuing the run would risk
                # ingesting more poisoned data. If a skip-the-paper
                # degrade is ever wanted, raise a URLError subclass
                # instead so the per-paper handler catches it.
                response_url = resp.url
                if not response_url.startswith(INSPIRE_API_BASE + "/"):
                    raise RuntimeError(
                        f"INSPIRE response redirected off "
                        f"{INSPIRE_API_BASE}: got {response_url!r}; "
                        f"refusing as untrusted (Threat 7)"
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
                # 429 floor: per the docs, the rate-limited request still
                # counts toward the quota; any sub-5s wait is wasted.
                if exc.code == http.HTTPStatus.TOO_MANY_REQUESTS.value:
                    floor = INSPIRE_429_FLOOR_SECONDS
                else:
                    floor = backoff
                wait = parse_retry_after(exc.headers.get("Retry-After"), floor)
                logger.warning(
                    "inspire %s for %s; retrying in %.0fs (attempt %d/%d)",
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
# INSPIRE Work parsers
# ---------------------------------------------------------------------------


def _format_journal_ref(work: dict[str, Any]) -> str | None:
    """Build a one-line journal reference from ``publication_info``.

    Picks the FIRST ``publication_info`` entry (the canonical
    publication when there are multiple, e.g. preprint-and-then-journal
    history). Concatenates ``journal_title journal_volume (year)
    page_start-page_end`` only including parts that are present.
    Returns None when no publication info exists.
    """
    pub_list = (work.get("metadata") or {}).get("publication_info") or []
    if not pub_list:
        return None
    pub = pub_list[0]
    parts: list[str] = []
    if pub.get("journal_title"):
        parts.append(str(pub["journal_title"]))
    if pub.get("journal_volume"):
        parts.append(str(pub["journal_volume"]))
    if pub.get("year"):
        parts.append(f"({pub['year']})")
    page_start = pub.get("page_start")
    page_end = pub.get("page_end")
    if page_start and page_end:
        parts.append(f"{page_start}-{page_end}")
    elif page_start:
        parts.append(str(page_start))
    return " ".join(parts) if parts else None


def _extract_arxiv_categories(work: dict[str, Any]) -> tuple[str, ...]:
    """Flatten ``arxiv_eprints[*].categories`` into a unique-ordered tuple.

    Used by the post-fetch physics gate: a record is only enriched
    when at least one entry intersects ``PHYSICS_CATEGORIES``.
    Preserves source order; deduplicates.
    """
    eprints = (work.get("metadata") or {}).get("arxiv_eprints") or []
    seen: dict[str, None] = {}
    for ep in eprints:
        for cat in ep.get("categories") or []:
            if cat not in seen:
                seen[cat] = None
    return tuple(seen)


def _extract_references_arxiv(work: dict[str, Any]) -> tuple[str, ...]:
    """Pull ``arxiv_eprint`` from each reference; drop refs without one.

    Many references are pure book / conference / preprint without an
    arXiv eprint; those are silently dropped (analogous to OpenAlex's
    cross-corpus reference drop). Deduplicates while preserving
    source order.
    """
    refs = (work.get("metadata") or {}).get("references") or []
    seen: dict[str, None] = {}
    for ref in refs:
        eprint = ((ref or {}).get("reference") or {}).get("arxiv_eprint")
        if eprint and eprint not in seen:
            seen[eprint] = None
    return tuple(seen)


def _resolved_from_inspire(work: dict[str, Any] | None) -> _ResolvedInspire:
    """Project an INSPIRE Work dict into the dataclass we persist.

    Returns a "blank" record (everything None / empty) when ``work``
    is None — the paper-not-in-INSPIRE 404 case.
    """
    if work is None:
        return _ResolvedInspire(
            inspire_id=None,
            doi=None,
            journal_ref=None,
            references_arxiv=(),
            arxiv_categories=(),
        )
    metadata = work.get("metadata") or {}
    control_number = metadata.get("control_number")
    inspire_id = str(control_number) if control_number is not None else None
    dois = metadata.get("dois") or []
    doi = (dois[0].get("value") if dois else None) or None
    return _ResolvedInspire(
        inspire_id=inspire_id,
        doi=doi,
        journal_ref=_format_journal_ref(work),
        references_arxiv=_extract_references_arxiv(work),
        arxiv_categories=_extract_arxiv_categories(work),
    )


# ---------------------------------------------------------------------------
# Checkpoint serialization
# ---------------------------------------------------------------------------


def _serialize_resolved(
    resolved: dict[str, _ResolvedInspire],
) -> dict[str, Any]:
    return {
        arxiv_id: {
            "inspire_id": ri.inspire_id,
            "doi": ri.doi,
            "journal_ref": ri.journal_ref,
            "references_arxiv": list(ri.references_arxiv),
            "arxiv_categories": list(ri.arxiv_categories),
        }
        for arxiv_id, ri in resolved.items()
    }


def _deserialize_resolved(payload: dict[str, Any]) -> dict[str, _ResolvedInspire]:
    out: dict[str, _ResolvedInspire] = {}
    for arxiv_id, raw in payload.items():
        out[arxiv_id] = _ResolvedInspire(
            inspire_id=raw.get("inspire_id"),
            doi=raw.get("doi"),
            journal_ref=raw.get("journal_ref"),
            references_arxiv=tuple(raw.get("references_arxiv") or ()),
            arxiv_categories=tuple(raw.get("arxiv_categories") or ()),
        )
    return out


# ---------------------------------------------------------------------------
# Kùzu writers
# ---------------------------------------------------------------------------


def _existing_paper_ids(conn: kuzu.Connection) -> set[str]:
    """Return the set of ``paper_id`` values already in the graph.

    Used at ingest start so the citation-pass reverse map and the
    edge-emit step both filter against the in-corpus universe (AC#3
    in spirit — INSPIRE edges only land between in-corpus papers).
    """
    result = conn.execute("MATCH (p:papers) RETURN p.paper_id")
    out: set[str] = set()
    while result.has_next():
        out.add(result.get_next()[0])
    return out


def _merge_paper_inspire(
    conn: kuzu.Connection,
    paper_id: str,
    ri: _ResolvedInspire,
) -> None:
    """Idempotent ``MERGE`` upsert of one paper's INSPIRE-exclusive columns.

    F4 closure from the E09_S01 critique. This writer touches ONLY
    the three INSPIRE-owned columns (``doi``, ``journal_ref``,
    ``inspire_id``) and never the columns the OpenAlex
    ``graph_ingest._merge_paper`` writes (``title``, ``abstract``,
    ``authors``, ``year``, ``categories``, ``oa_work_id``). Source
    ownership is therefore structural — a future maintainer can grep
    for "writes ``title``" and find the OpenAlex writer; "writes
    ``journal_ref``" and find this one. No precedence-table logic
    is needed.

    The MERGE creates the node if absent. Normally the OpenAlex
    resolver has run first and the node already exists, but for
    test isolation we tolerate the no-OpenAlex case (the node is
    created with NULL on every OpenAlex-owned column).

    F1 fix from the E09_S02 critique: ``ON MATCH SET`` uses
    ``COALESCE($new, p.col)`` so a re-MERGE with a NULL field does
    NOT clobber a previously-stamped value. The brief frames INSPIRE
    enrichment as additive; a transient API regression returning a
    record without ``dois`` would otherwise destroy curated DOIs.
    The ``ON CREATE SET`` clause writes the new values directly
    (the previous value is NULL by definition on a fresh node, so
    COALESCE is unnecessary on create).
    """
    conn.execute(
        """
        MERGE (p:papers {paper_id: $paper_id})
        ON CREATE SET
            p.doi = $doi,
            p.journal_ref = $journal_ref,
            p.inspire_id = $inspire_id
        ON MATCH SET
            p.doi = COALESCE($doi, p.doi),
            p.journal_ref = COALESCE($journal_ref, p.journal_ref),
            p.inspire_id = COALESCE($inspire_id, p.inspire_id)
        """,
        {
            "paper_id": paper_id,
            "doi": ri.doi,
            "journal_ref": ri.journal_ref,
            "inspire_id": ri.inspire_id,
        },
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def enrich(
    paper_ids: Iterable[str],
    db_path: Path,
    checkpoint_path: Path,
    contact_email: str,
    *,
    fetch_fn: Callable[[str, str], dict[str, Any] | None] | None = None,
    sleep_seconds: float = INSPIRE_POLITE_SLEEP_SECONDS,
    batch_size: int = CHECKPOINT_BATCH_SIZE,
) -> dict[str, Any]:
    """Run the two-pass INSPIRE enrichment. Returns the final state.

    Args:
        paper_ids: arXiv IDs to enrich. Typically the result of
            ``_existing_paper_ids(conn)`` at the CLI layer; tests
            pass a constrained synthetic list. Each ID is validated
            via ``validate_paper_id`` before any I/O.
        db_path: Kùzu database directory. Must already have the v2
            schema applied (``apply_schema`` is idempotent and re-
            applied here as defense-in-depth).
        checkpoint_path: JSON file persisted after every batch.
        contact_email: passed through ``build_user_agent`` for the
            polite User-Agent header.
        fetch_fn: HTTP fetcher override (None = use this module's
            ``_fetch_inspire_record``, looked up at call time so
            ``monkeypatch.setattr`` on the module attribute takes
            effect — same default-arg-late-bind workaround as
            ``graph_ingest.ingest``).
        sleep_seconds: inter-request sleep; tests pass 0.
        batch_size: checkpoint flush cadence (AC#5).

    Returns:
        The final checkpoint state dict.
    """
    if fetch_fn is None:
        fetch_fn = _fetch_inspire_record

    paper_id_list = list(paper_ids)
    for arxiv_id in paper_id_list:
        _validate_paper_id_either_style(arxiv_id)

    apply_schema(db_path)
    db = kuzu.Database(str(db_path))
    try:
        conn = kuzu.Connection(db)
        state = load_checkpoint(checkpoint_path)
        resolved = _deserialize_resolved(state.get("resolved", {}))
        edges_done: set[str] = set(state.get("edges_done", []))
        fetch_failures: dict[str, str] = {
            entry["arxiv_id"]: entry.get("error", "")
            for entry in state.get("fetch_failures", [])
            if isinstance(entry, dict) and "arxiv_id" in entry
        }
        in_corpus = _existing_paper_ids(conn)

        # PASS 1: resolution. For each paper not yet resolved, fetch
        # INSPIRE, project into _ResolvedInspire, and (if the post-fetch
        # physics gate passes) MERGE the INSPIRE-exclusive columns.
        last_request_at: float | None = None
        new_in_pass = 0
        for arxiv_id in paper_id_list:
            if arxiv_id in resolved:
                continue
            if last_request_at is not None and sleep_seconds > 0:
                elapsed = time.monotonic() - last_request_at
                if elapsed < sleep_seconds:
                    time.sleep(sleep_seconds - elapsed)
            last_request_at = time.monotonic()
            try:
                work = fetch_fn(arxiv_id, contact_email)
            except urllib.error.URLError as exc:
                # F6 fix: increment ``new_in_pass`` on the failure path
                # too so a long failure run hits the checkpoint cadence
                # and a hard kill doesn't lose the in-memory failures
                # dict.
                logger.error("inspire fetch failed for %s: %s", arxiv_id, exc)
                fetch_failures[arxiv_id] = str(exc)
                new_in_pass += 1
                if new_in_pass % batch_size == 0:
                    state["resolved"] = _serialize_resolved(resolved)
                    state["edges_done"] = sorted(edges_done)
                    state["fetch_failures"] = _serialize_failures(fetch_failures)
                    save_checkpoint(checkpoint_path, state)
                continue
            fetch_failures.pop(arxiv_id, None)
            ri = _resolved_from_inspire(work)
            # F9 post-fetch gate: only enrich when INSPIRE confirms
            # the paper is hep-th or math-ph. Non-physics papers
            # (returning a record but with different categories) get
            # a blank resolved entry and are NOT written. Cached so
            # the resolver doesn't re-fetch on resume.
            if not (set(ri.arxiv_categories) & PHYSICS_CATEGORIES):
                # F3 deferred (E09_S02 critique): reclassification
                # semantics. If a paper was previously enriched (real
                # INSPIRE row in the graph) and is now classified as
                # non-physics on a re-run, this branch caches a blank
                # ``_ResolvedInspire`` and SKIPS calling
                # ``_merge_paper_inspire``. The previously-stamped
                # INSPIRE columns therefore SURVIVE in the graph.
                # That is the intended behavior — INSPIRE enrichment
                # is additive; a re-classification does not retract
                # earlier curation.
                resolved[arxiv_id] = _ResolvedInspire(
                    inspire_id=None,
                    doi=None,
                    journal_ref=None,
                    references_arxiv=(),
                    arxiv_categories=ri.arxiv_categories,
                )
            else:
                _merge_paper_inspire(conn, arxiv_id, ri)
                resolved[arxiv_id] = ri
            new_in_pass += 1
            if new_in_pass % batch_size == 0:
                state["resolved"] = _serialize_resolved(resolved)
                state["edges_done"] = sorted(edges_done)
                state["fetch_failures"] = _serialize_failures(fetch_failures)
                save_checkpoint(checkpoint_path, state)

        # F4 fix from the E09_S02 critique: refresh the in-corpus set
        # after Pass 1 because ``_merge_paper_inspire`` may have
        # created new nodes (the docstring's tolerated test-isolation
        # case). Without the refresh, those newly-created nodes are
        # silently excluded from edge emission below.
        in_corpus = _existing_paper_ids(conn)

        # F8 collision detection: warn if two arXiv IDs resolve to
        # the same INSPIRE record. Mirrors the oa_work_id collision
        # check from ``graph_ingest``.
        seen_inspire_ids: dict[str, list[str]] = {}
        for arxiv_id, ri in resolved.items():
            if not ri.inspire_id:
                continue
            seen_inspire_ids.setdefault(ri.inspire_id, []).append(arxiv_id)
        for inspire_id, aids in seen_inspire_ids.items():
            if len(aids) > 1:
                logger.warning(
                    "inspire_id collision: %s maps to multiple arxiv ids %s",
                    inspire_id,
                    sorted(aids),
                )

        # PASS 2: citation. Walk references and emit cites edges only
        # when both endpoints are in the corpus. AC#3 falls out of
        # _merge_cite's MERGE-key composition: source="inspire" is a
        # distinct edge from source="openAlex" for the same (a, b).
        new_edges_pass = 0
        for arxiv_id, ri in resolved.items():
            if arxiv_id in edges_done:
                continue
            if not ri.references_arxiv:
                edges_done.add(arxiv_id)
                continue
            if arxiv_id not in in_corpus:
                # Edge cannot be emitted: source paper not in graph.
                edges_done.add(arxiv_id)
                continue
            for ref_id in ri.references_arxiv:
                if ref_id not in in_corpus:
                    continue
                _merge_cite(
                    conn,
                    src_paper_id=arxiv_id,
                    dst_paper_id=ref_id,
                    source="inspire",
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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    # F7 fix from the E09_S02 critique: dropped the ``--source`` flag.
    # The script's identity IS INSPIRE — a flag advertising selectivity
    # the CLI does not deliver is a foot-gun. The OpenAlex ingest is a
    # separate ``python -m ingest.graph_ingest`` CLI; operators reach
    # for the right one by module path, not by flag.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed-file",
        type=Path,
        default=None,
        help=(
            "optional arXiv-ID seed list to constrain enrichment. "
            "Default: enrich every paper currently in the graph "
            "(matching the brief's 'iterates over all `papers` "
            "nodes' wording). For test scenarios or partial re-runs, "
            "pass a seed file to limit the worked set."
        ),
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("var/arxmcp/ops/inspire-ingest-checkpoint.json"),
        help="atomic-write checkpoint path (rewritten after each batch)",
    )
    parser.add_argument(
        "--kuzudb",
        type=Path,
        default=Path("var/arxmcp/index/kuzu"),
        help=(
            "Kùzu DB directory (default: var/arxmcp/index/kuzu — "
            "matches Makefile bootstrap and 05-storage-and-indexing.md)"
        ),
    )
    parser.add_argument(
        "--include-back-refs",
        action="store_true",
        help=(
            "[NOT IMPLEMENTED] Also fetch papers that cite each target "
            "via INSPIRE's `?q=refersto:recid:<n>` paginated search. "
            "The brief's 'and `citations`' framing requires this; the "
            "field is NOT inline on per-record responses. Default off "
            "because the references pass alone closes most of the "
            "enrichment-coverage goal."
        ),
    )
    args = parser.parse_args(argv)

    if args.include_back_refs:
        sys.stderr.write(
            "ERROR: --include-back-refs is not implemented in E09_S02.\n"
            "       Forward-citations require a paginated `?q=refersto:recid:`\n"
            "       search; that lands in a future milestone. Re-run "
            "without the flag.\n"
        )
        return 2

    contact_email = os.environ.get("ARXMCP_CONTACT_EMAIL")
    if not contact_email:
        sys.stderr.write(
            "ERROR: ARXMCP_CONTACT_EMAIL is required for the polite User-Agent "
            "header.\n"
            "       Export it in your shell before running this script.\n"
        )
        return 2

    # Apply the schema migration first so we can introspect the graph
    # for paper IDs even if E09_S02 is the first thing the operator
    # has ever run on this DB.
    apply_schema(args.kuzudb)

    paper_ids: list[str]
    if args.seed_file is not None:
        from tools.fetch_seed import read_seed_list

        paper_ids = read_seed_list(args.seed_file)
        if not paper_ids:
            sys.stderr.write(
                f"ERROR: seed file {args.seed_file} contains no IDs\n"
            )
            return 2
    else:
        db = kuzu.Database(str(args.kuzudb))
        try:
            conn = kuzu.Connection(db)
            paper_ids = sorted(_existing_paper_ids(conn))
        finally:
            del db
        if not paper_ids:
            sys.stderr.write(
                "ERROR: no `papers` nodes found in the graph. Run the "
                "OpenAlex ingest first (`python -m ingest.graph_ingest`).\n"
            )
            return 2

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info(
        "enriching %d paper(s) from %s (checkpoint: %s)",
        len(paper_ids),
        args.kuzudb,
        args.checkpoint,
    )

    try:
        state = enrich(
            paper_ids=paper_ids,
            db_path=args.kuzudb,
            checkpoint_path=args.checkpoint,
            contact_email=contact_email,
        )
    except KeyboardInterrupt:
        logger.warning("interrupted by user; checkpoint preserved.")
        return 130

    failures = state.get("fetch_failures", [])
    enriched = sum(
        1
        for r in state.get("resolved", {}).values()
        if r.get("inspire_id") is not None
    )
    logger.info(
        "done: %d papers fetched, %d enriched (physics-gated), %d edges "
        "processed, %d transient fetch failures still pending",
        len(state.get("resolved", {})),
        enriched,
        len(state.get("edges_done", [])),
        len(failures),
    )
    if failures:
        # F3 fix from the E09_S01 critique applied to INSPIRE: pending
        # failures must surface as a non-zero exit so the operator
        # notices and re-runs.
        sys.stderr.write(
            f"WARNING: {len(failures)} paper(s) hit transient network "
            "errors during the INSPIRE-HEP resolution pass and were not "
            "added to the graph. Re-run this command to retry; the "
            f"checkpoint at {args.checkpoint} preserves progress.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
