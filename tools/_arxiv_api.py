"""Reusable arXiv Atom API client (notebook-paper-discovery-m2).

Extracted from ``tools/curate_seed.py`` so the m3 notebook-discovery driver
and the curate-seed CLI share ONE arXiv-query surface. Mirrors the
``tools/_notebook_common.py`` shared-module pattern: a leading-underscore
internal helper module, ``from __future__ import annotations``, an
``__all__`` export list, and ``if … raise`` validation (never ``assert`` —
``-O`` strips them, CLAUDE.md §4.7).

Capabilities:

- ``build_query_url`` — compose an arXiv ``search_query`` from a category +
  optional ``abs:``/``ti:`` keyword clauses, with ``start`` + ``max_results``
  pagination params. Keyword phrases are double-quoted so an operator-supplied
  ``description`` cannot inject boolean operators / field prefixes into the
  query (a phrase value matches literally).
- ``parse_atom_feed`` — parse the Atom response into ``Candidate`` rows using
  ``defusedxml`` (XXE / billion-laughs safe — the response is untrusted
  external data; Threat 7 in ``08-security-observability-ops.md``). Detects the
  arXiv "error entry" pattern (HTTP 200 + an ``/api/errors#`` id) and raises.
- ``fetch_candidates`` — fetch + paginate + parse, returning ``list[Candidate]``.
  Pagination is bounded by the requested ``max_results`` (≤2000/page per the
  arXiv API), with an injectable ``sleep`` honoured BETWEEN pages so the
  politeness contract (``tools.arxiv_fetch.POLITENESS_SLEEP_SECONDS`` = 3s) is
  preserved. For ``max_results`` ≤ 2000 this is a single request with no sleep
  — identical to the pre-m2 single-fetch behaviour.

No new pip dependency: stdlib ``urllib`` + ``defusedxml`` (already a project
dep, used by ``server/retrieval/equations.py``). No-fork: reimplemented
natively, nothing lifted from ``arxiv.py`` or other arxiv-mcp code.
"""

from __future__ import annotations

import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import defusedxml.ElementTree as DET

from tools.arxiv_fetch import (
    POLITENESS_SLEEP_SECONDS,
    build_user_agent,
)

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

#: arXiv API hard caps (info.arxiv.org/help/api/user-manual.html).
MAX_RESULTS_PER_PAGE: int = 2000
ARXIV_TOTAL_CAP: int = 30000

#: Defensive read cap for a single Atom response. Metadata feeds are tiny
#: (a 2000-entry page is well under 10 MB); this only guards against a
#: malformed / hostile response inflating the process (FM-5).
MAX_RESPONSE_BYTES: int = 50 * 1024 * 1024

#: arXiv signals a query/server error as an HTTP-200 feed whose single entry
#: has an id under this path (FM-6) rather than a 4xx/5xx status.
_ERROR_ID_MARKER: str = "/api/errors#"


@dataclass(frozen=True)
class Candidate:
    """One arXiv paper parsed from an Atom feed entry.

    ``title`` and ``submitted_date`` (notebook-paper-discovery-m3) are appended
    with defaults so the dataclass stays backward-compatible: ``as_tsv_row`` and
    the curate-seed CLI ignore them, and the only construction site is
    :func:`parse_atom_feed` (keyword args). ``submitted_year`` (int) is retained
    for ``as_tsv_row``; ``submitted_date`` is the raw ISO-8601 ``<published>``
    string the m3 discovery driver surfaces.
    """

    paper_id: str
    submitted_year: int
    n_authors: int
    primary_category: str
    abstract_head: str
    title: str = ""
    submitted_date: str = ""

    def as_tsv_row(self) -> str:
        return "\t".join(
            [
                self.paper_id,
                str(self.submitted_year),
                str(self.n_authors),
                self.primary_category,
                self.abstract_head[:120],
            ]
        )


def _keyword_clause(field: str, value: str) -> str | None:
    """Build a quoted ``field:"phrase"`` clause from operator keywords.

    The value is wrapped in double quotes so the arXiv parser treats it as a
    literal phrase — this neutralises injected boolean operators / field
    prefixes (FM-3) AND gives exact-phrase relevance. Any embedded double
    quote is stripped first so it cannot terminate the phrase early.

    Returns ``None`` when the value is empty after stripping quotes +
    whitespace, so the caller drops the clause entirely rather than emitting a
    degenerate ``field:""`` phrase (rect F1: m3 populates these from notebook
    descriptions, which may be blank after stripping).
    """
    cleaned = value.replace('"', "").strip()
    if not cleaned:
        return None
    return f'{field}:"{cleaned}"'


def build_query_url(
    category: str,
    start: int = 0,
    max_results: int = 200,
    *,
    abs_keywords: str | None = None,
    ti_keywords: str | None = None,
) -> str:
    """Build an arXiv API query URL.

    ``start`` / ``max_results`` stay positional for backward compatibility
    with the pre-m2 ``build_query_url(category, start, max_results)`` callers
    and tests. ``abs_keywords`` / ``ti_keywords`` are keyword-only additions;
    when both are ``None`` the produced URL is byte-identical to the pre-m2
    output (``search_query=cat:<category>`` …), so the existing
    ``TestCurateQueryURL`` assertions hold.
    """
    if not category:
        raise ValueError("category must be a non-empty arXiv category code")

    search_query = f"cat:{category}"
    if abs_keywords:
        abs_clause = _keyword_clause("abs", abs_keywords)
        if abs_clause:
            search_query += f" AND {abs_clause}"
    if ti_keywords:
        ti_clause = _keyword_clause("ti", ti_keywords)
        if ti_clause:
            search_query += f" AND {ti_clause}"

    params = {
        "search_query": search_query,
        "start": str(start),
        "max_results": str(max_results),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return f"{ARXIV_API_URL}?{urllib.parse.urlencode(params)}"


def parse_atom_feed(xml_bytes: bytes) -> list[Candidate]:
    """Parse an arXiv Atom feed into ``Candidate`` rows.

    Uses ``defusedxml`` (XXE / entity-expansion safe). Raises
    ``RuntimeError`` if the feed is an arXiv error entry (FM-6).
    """
    root = DET.fromstring(xml_bytes)
    out: list[Candidate] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        id_url = (
            entry.findtext("atom:id", default="", namespaces=ATOM_NS) or ""
        ).strip()
        if _ERROR_ID_MARKER in id_url:
            summary = (
                entry.findtext("atom:summary", default="", namespaces=ATOM_NS)
                or "unknown arXiv API error"
            ).strip()
            raise RuntimeError(f"arXiv API returned an error entry: {summary}")

        paper_id = id_url.rsplit("/", 1)[-1]
        if "v" in paper_id:
            paper_id = paper_id.split("v", 1)[0]

        published = (
            entry.findtext("atom:published", default="", namespaces=ATOM_NS) or ""
        )
        try:
            year = datetime.fromisoformat(published.replace("Z", "+00:00")).year
        except ValueError:
            year = 0

        authors = entry.findall("atom:author", ATOM_NS)
        primary = entry.find("arxiv:primary_category", ATOM_NS)
        primary_cat = primary.attrib.get("term", "") if primary is not None else ""

        summary = (
            entry.findtext("atom:summary", default="", namespaces=ATOM_NS) or ""
        ).strip()
        abstract_head = " ".join(summary.split())

        # notebook-paper-discovery-m3: <title> (required Atom element) and the
        # raw <published> ISO-8601 string the discovery driver surfaces.
        title = " ".join(
            (entry.findtext("atom:title", default="", namespaces=ATOM_NS) or "").split()
        )

        out.append(
            Candidate(
                paper_id=paper_id,
                submitted_year=year,
                n_authors=len(authors),
                primary_category=primary_cat,
                abstract_head=abstract_head,
                title=title,
                submitted_date=published.strip(),
            )
        )
    return out


def _fetch_url(url: str, contact_email: str | None = None) -> bytes:
    """GET ``url`` from the arXiv API with the polite User-Agent.

    Private so tests monkeypatch ``_arxiv_api._fetch_url`` (the
    ``graph_ingest._fetch_openalex_work`` pattern) instead of patching
    ``urllib.request.urlopen`` globally. Reads at most ``MAX_RESPONSE_BYTES``.
    """
    req = urllib.request.Request(  # noqa: S310 — fixed export.arxiv.org host
        url, headers={"User-Agent": build_user_agent(contact_email)}
    )
    with urllib.request.urlopen(req, timeout=60.0) as resp:  # noqa: S310
        return resp.read(MAX_RESPONSE_BYTES)


def fetch_candidates(
    category: str,
    max_results: int,
    contact_email: str | None = None,
    *,
    abs_keywords: str | None = None,
    ti_keywords: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Candidate]:
    """Fetch (paginating as needed) up to ``max_results`` candidates.

    Pages in chunks of ≤``MAX_RESULTS_PER_PAGE`` until ``max_results`` rows are
    collected or the feed is exhausted. The injected ``sleep`` is called
    BETWEEN pages only (so ``max_results`` ≤ 2000 is a single request with no
    sleep — identical to the pre-m2 behaviour). Three convergence guards (FM-2):
    stop on a short/empty page, never request ``start`` ≥ ``ARXIV_TOTAL_CAP``,
    and cap the page count.
    """
    if max_results <= 0:
        raise ValueError("max_results must be a positive integer")

    page_size = min(max_results, MAX_RESULTS_PER_PAGE)
    max_pages = (max_results + page_size - 1) // page_size + 1

    collected: list[Candidate] = []
    start = 0
    pages = 0
    while len(collected) < max_results and start < ARXIV_TOTAL_CAP:
        if pages > 0:
            sleep(POLITENESS_SLEEP_SECONDS)
        url = build_query_url(
            category,
            start,
            page_size,
            abs_keywords=abs_keywords,
            ti_keywords=ti_keywords,
        )
        page = parse_atom_feed(_fetch_url(url, contact_email))
        pages += 1
        if not page:
            break
        collected.extend(page)
        start += page_size
        if len(page) < page_size or pages >= max_pages:
            # Short page => feed exhausted; page cap => convergence guard.
            break

    return collected[:max_results]


__all__ = [
    "ARXIV_API_URL",
    "ATOM_NS",
    "Candidate",
    "build_query_url",
    "fetch_candidates",
    "parse_atom_feed",
]
