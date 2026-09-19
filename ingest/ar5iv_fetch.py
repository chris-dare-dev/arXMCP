"""Pre-rendered-HTML fetchers: arXiv-native HTML + ar5iv (E11_S01; stage2/arx-a45).

Fetches pre-rendered HTML5+MathML for a given arXiv paper id from two
sources, in ladder order (finding 04 cascade; finding 211 R-E):

1. ``arxiv.org/html/<id>`` — arXiv's first-party native HTML surface
   (:func:`try_native`). The institutionally-backed successor to
   ar5iv; both are LaTeXML output with an identical ``ltx_*`` class
   vocabulary, so the chunker consumes either unchanged.
2. ``ar5iv.labs.arxiv.org/html/<id>`` — the ar5iv cache
   (:func:`try_cache`). Covers ~70-90% of post-2007 papers; the
   native rollout is still incomplete for older papers.

:func:`try_html_sources` runs the two rungs in order; callers fall
back to local LaTeXML on a double miss (the third rung lives in the
callers — ``ingest/bulk_ingest.py`` step 2). Using the remote renders
avoids weeks of local CPU work during the bulk ingest.

Per `.claude/notes/03-ingestion-pipeline.md:87-95` ("Run our local
LaTeXML only on ar5iv cache misses. Saves weeks of CPU.") the
remote-render-first ladder is the load-bearing ingest strategy.

**LaTeXML generator-version tripwire (arx-a45 / finding 211 rec 6).**
Every hit extracts the ``Generated … by LaTeXML (version X.Y.Z)``
comment into ``Ar5ivResult.latexml_generator`` so ingest can persist
it per paper. arXiv's in-progress LaTeXML Rust port could eventually
shift ``ltx_*`` markup; the recorded generator string is the drift
signal that pairs with the native-HTML golden-fixture regression
test (``tests/test_native_html_ingest.py``).

**Status codes & retry:**

* HTTP 200 with non-empty body containing ``<math`` → success.
  Body is written both to the canonical parsed path
  ``var/arxmcp/corpus/parsed/<paper_id>/index.html`` (so the
  chunker's existing HTML walk picks it up unchanged) AND to a
  separate cache directory ``var/arxmcp/cache/ar5iv/<paper_id>.html``
  (so re-runs skip the network call).
* HTTP 200 with empty/error body — treat as miss (ar5iv error
  banner has no ``<math``).
* HTTP 404 / 503 / 429 → cache miss; caller falls back to local
  LaTeXML on the .tex source.
* Network timeout / connection error → cache miss (do NOT retry;
  ar5iv is a static CDN, a transient failure is unlikely to
  resolve quickly).

**No rate limiting.** ar5iv is a CDN-fronted static cache. The
5-second timeout is the only safety; no inter-request sleep.

**Politeness contract is separate from arxiv.org.** The 3-second
``POLITENESS_SLEEP_SECONDS`` discipline from `tools/arxiv_fetch.py`
applies to ``export.arxiv.org`` (the e-print and OAI-PMH
endpoints), not to ``ar5iv.labs.arxiv.org``. Mixing them in one
sleep budget would needlessly slow down ar5iv-hit-heavy runs.
"""

from __future__ import annotations

import logging
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ingest.identifiers import is_valid_arxiv_paper_id

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AR5IV_CACHE_DIR = REPO_ROOT / "var" / "arxmcp" / "cache" / "ar5iv"
#: arx-a45: native-HTML fetches cache separately from ar5iv ones so
#: the on-disk provenance stays legible (which render family produced
#: a given cached file matters for the generator-version tripwire).
DEFAULT_NATIVE_CACHE_DIR = REPO_ROOT / "var" / "arxmcp" / "cache" / "native-html"
DEFAULT_PARSED_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "parsed"

#: Base URL for the ar5iv cache. The labs domain serves the legacy
#: rewrite; arxiv.org/html serves the newer first-party rewrite of
#: the same LaTeXML content (its rollout is incomplete for older
#: papers, which is why ar5iv remains the second rung).
AR5IV_BASE_URL: str = "https://ar5iv.labs.arxiv.org/html"

#: Base URL for arXiv's native HTML surface (arx-a45 — first rung of
#: the fetch ladder per finding 04's native → ar5iv → local-LaTeXML
#: cascade). Like ar5iv it is CDN-fronted static content; the same
#: no-rate-limit discipline applies (see module docstring note on
#: politeness budgets — the export.arxiv.org 3-second contract is a
#: separate budget and does NOT govern this surface).
ARXIV_NATIVE_BASE_URL: str = "https://arxiv.org/html"

#: Per-request timeout. ar5iv is a CDN; <1s is typical; 5s catches
#: slow nodes without hanging the cron forever.
AR5IV_TIMEOUT_SECONDS: float = 5.0

#: E13_S07 Threat 7 — content-length sanity cap. The threat model
#: in ``.claude/notes/08-security-observability-ops.md`` § Threat 7
#: states "a single paper > 100 MB source is suspicious." The cap
#: applies BOTH to the ``Content-Length`` header (pre-read reject
#: when the server announces an oversized body) AND to the actual
#: bytes read (catches a lying header or chunked encoding without
#: a declared length). A legitimate ar5iv HTML render of even a
#: very long algebraic-geometry paper is well under 10 MB; 100 MB
#: leaves three orders of magnitude of headroom while bounding the
#: blast radius of a poisoned ar5iv response.
AR5IV_MAX_RESPONSE_BYTES: int = 100 * 1024 * 1024

#: Required signal in a 200 response body — verifies LaTeXML actually
#: produced math. An ar5iv error page (e.g. "this paper could not be
#: processed") returns 200 with no MathML; we treat that as a miss.
#:
#: Closes F4: matched with a ``\b`` word boundary so spurious
#: ``<math.foo`` CSS-class substrings don't trip the heuristic. The
#: legitimate signal is a ``<math>`` or ``<math xmlns=...>`` tag
#: opener, both of which match ``<math\b``.
_MATH_SIGNAL_RE = re.compile(r"<math\b")

#: ar5iv's "this paper could not be processed" error banner. When ar5iv
#: serves a 200 but the LaTeXML render failed, this string appears in
#: the body. Belt-and-braces guard alongside the ``<math\b`` check.
#: arXiv-native error pages return 404 (no banner needed) but the
#: ``<math\b`` signal check still guards a hypothetical 200-shaped
#: failure page on that surface too.
_AR5IV_ERROR_BANNER = "could not be processed"

#: arx-a45 — LaTeXML generator-version comment, present near the top
#: of both ar5iv and arXiv-native renders::
#:
#:     Generated on Tue Mar 12 05:45:28 2024 by LaTeXML (version 0.8.8)
#:
#: Captured loosely (any ``LaTeXML (version …)`` occurrence) so minor
#: comment-format drift doesn't blind the tripwire whose whole job is
#: noticing drift.
_LATEXML_GENERATOR_RE = re.compile(r"LaTeXML\s*\(version\s+([^)\s]+)\)")

#: How many chars of a locally-cached file to scan for the generator
#: comment. Observed offset is ~1.2 KB into the document (inside
#: ``<head>``); 64 KB gives ample slack without reading multi-MB
#: bodies on the local-cache short-circuit path.
_GENERATOR_SCAN_CHARS = 64 * 1024


def extract_latexml_generator(html_text: str) -> str | None:
    """Return the LaTeXML generator version string (e.g. ``"0.8.8"``)
    from a rendered HTML body, or ``None`` when absent.

    arx-a45 drift tripwire (finding 211 rec 6): the version is
    persisted per ingest so an arXiv-side LaTeXML upgrade (or the
    in-progress Rust port) is visible in the ingest ops log before it
    silently shifts ``ltx_*`` markup under the chunker.
    """
    match = _LATEXML_GENERATOR_RE.search(html_text)
    return match.group(1) if match else None


def _generator_from_file(path: Path) -> str | None:
    """Best-effort generator extraction from an on-disk cached render.

    Reads at most :data:`_GENERATOR_SCAN_CHARS` chars. Any I/O error
    degrades to ``None`` — the tripwire is observability, never a
    reason to fail an ingest.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(_GENERATOR_SCAN_CHARS)
    except OSError:
        return None
    return extract_latexml_generator(head)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Ar5ivResult:
    """One pre-rendered-HTML fetch outcome (ar5iv or arXiv-native).

    The class name predates the native-HTML rung (arx-a45); it is
    kept for API stability — every existing caller and test pins it.
    ``source`` disambiguates which rung produced the result.
    """

    paper_id: str
    hit: bool
    cache_path: Path | None       # populated on hit; None on miss
    parsed_path: Path | None      # populated on hit; None on miss
    reason: str                   # "ok" / "404" / "timeout" / "no_math" / etc.
    #: arx-a45 — which render family produced this result:
    #: ``"ar5iv"`` or ``"native_html"``. Defaulted so pre-existing
    #: construction sites (tests included) stay valid.
    source: str = "ar5iv"
    #: arx-a45 — LaTeXML generator version extracted from the body
    #: (``None`` on miss or when the comment is absent).
    latexml_generator: str | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def try_cache(
    paper_id: str,
    *,
    cache_dir: Path = DEFAULT_AR5IV_CACHE_DIR,
    parsed_dir: Path = DEFAULT_PARSED_DIR,
    timeout_seconds: float = AR5IV_TIMEOUT_SECONDS,
    user_agent: str = "arxmcp-ingest/0.1",
    ssl_context: ssl.SSLContext | None = None,
) -> Ar5ivResult:
    """Fetch ``paper_id`` from ar5iv; on hit, write the HTML to the
    canonical parsed path so the chunker's HTML walk picks it up.

    Returns an :class:`Ar5ivResult`. The caller distinguishes hit
    from miss via ``result.hit``. On miss, the caller invokes the
    local LaTeXML fallback.

    Re-runs are cheap: when the cache file already exists on disk
    and the parsed file already exists, no network call is made.

    Raises :class:`ValueError` for malformed ``paper_id`` —
    callers should validate at the boundary. Other errors are
    converted into a miss result (no raise) so the bulk-ingest
    loop never aborts.

    The ``ssl_context`` parameter is the E13_S07c CA-pinning
    injection point (Threat 7 mitigation #2). Pass ``None`` (the
    default) to use the system trust store; pass an
    :class:`ssl.SSLContext` built via
    :func:`server.ssl_pin.build_arxiv_ssl_context` to pin the
    bundle. Threaded into ``urllib.request.urlopen(context=...)``.
    """
    return _fetch_render(
        paper_id,
        base_url=AR5IV_BASE_URL,
        source="ar5iv",
        cache_dir=cache_dir,
        parsed_dir=parsed_dir,
        timeout_seconds=timeout_seconds,
        user_agent=user_agent,
        ssl_context=ssl_context,
    )


def try_native(
    paper_id: str,
    *,
    cache_dir: Path = DEFAULT_NATIVE_CACHE_DIR,
    parsed_dir: Path = DEFAULT_PARSED_DIR,
    timeout_seconds: float = AR5IV_TIMEOUT_SECONDS,
    user_agent: str = "arxmcp-ingest/0.1",
    ssl_context: ssl.SSLContext | None = None,
) -> Ar5ivResult:
    """Fetch ``paper_id`` from arXiv's native HTML surface
    (``arxiv.org/html/<id>``) — the first rung of the arx-a45 fetch
    ladder.

    Same contract, caps, redirect guard, and reason vocabulary as
    :func:`try_cache`; only the base URL, the on-disk cache
    directory, and ``result.source`` (``"native_html"``) differ.
    arXiv serves 404 for papers without a native render, which maps
    to the standard ``http_404`` miss. Unversioned ids redirect to
    the current versioned URL (``/html/<id>`` → ``/html/<id>v<N>``);
    that redirect stays under the pinned base URL and is accepted.
    """
    return _fetch_render(
        paper_id,
        base_url=ARXIV_NATIVE_BASE_URL,
        source="native_html",
        cache_dir=cache_dir,
        parsed_dir=parsed_dir,
        timeout_seconds=timeout_seconds,
        user_agent=user_agent,
        ssl_context=ssl_context,
    )


def try_html_sources(
    paper_id: str,
    *,
    native_cache_dir: Path = DEFAULT_NATIVE_CACHE_DIR,
    ar5iv_cache_dir: Path = DEFAULT_AR5IV_CACHE_DIR,
    parsed_dir: Path = DEFAULT_PARSED_DIR,
    timeout_seconds: float = AR5IV_TIMEOUT_SECONDS,
    user_agent: str = "arxmcp-ingest/0.1",
    ssl_context: ssl.SSLContext | None = None,
) -> Ar5ivResult:
    """Run the remote-render ladder: native HTML → ar5iv (arx-a45).

    Ladder order per finding 04's cascade (native → ar5iv → local
    LaTeXML; the third rung belongs to the caller). A local-cache
    short-circuit runs FIRST across both rungs so a paper previously
    fetched from either source never triggers a network call again:

    1. ``parsed/<id>/index.html`` present + native cache file → hit.
    2. ``parsed/<id>/index.html`` present + ar5iv cache file → hit.
    3. Network: :func:`try_native`; return on hit.
    4. Network: :func:`try_cache` (ar5iv); return its result
       (hit or miss — a miss here carries the ar5iv reason, which is
       the operationally interesting one since ar5iv has the wider
       coverage).

    Raises :class:`ValueError` for malformed ``paper_id`` (same
    boundary contract as both rungs).
    """
    if not is_valid_arxiv_paper_id(paper_id):
        raise ValueError(
            f"paper_id {paper_id!r} does not match the arXiv id "
            f"format (new-style YYMM.NNNNN or old-style "
            f"subject/NNNNNNN)"
        )

    parsed_path = parsed_dir / paper_id / "index.html"
    if parsed_path.is_file():
        for cache_dir, source in (
            (native_cache_dir, "native_html"),
            (ar5iv_cache_dir, "ar5iv"),
        ):
            cache_path = cache_dir / f"{paper_id}.html"
            if cache_path.is_file():
                logger.debug(
                    "%s: ladder cache hit on disk for %s", source, paper_id,
                )
                return Ar5ivResult(
                    paper_id=paper_id,
                    hit=True,
                    cache_path=cache_path,
                    parsed_path=parsed_path,
                    reason="ok_local_cache",
                    source=source,
                    latexml_generator=_generator_from_file(cache_path),
                )

    native_result = try_native(
        paper_id,
        cache_dir=native_cache_dir,
        parsed_dir=parsed_dir,
        timeout_seconds=timeout_seconds,
        user_agent=user_agent,
        ssl_context=ssl_context,
    )
    if native_result.hit:
        return native_result
    logger.debug(
        "native_html miss for %s (%s); falling back to ar5iv",
        paper_id, native_result.reason,
    )
    return try_cache(
        paper_id,
        cache_dir=ar5iv_cache_dir,
        parsed_dir=parsed_dir,
        timeout_seconds=timeout_seconds,
        user_agent=user_agent,
        ssl_context=ssl_context,
    )


def _fetch_render(
    paper_id: str,
    *,
    base_url: str,
    source: str,
    cache_dir: Path,
    parsed_dir: Path,
    timeout_seconds: float,
    user_agent: str,
    ssl_context: ssl.SSLContext | None,
) -> Ar5ivResult:
    """Shared fetch engine for both render families.

    Behavior is byte-for-byte the pre-arx-a45 ``try_cache`` flow —
    Content-Length pre-check, 100 MB read cap, off-base redirect
    rejection, ``<math\\b`` signal + error-banner miss detection,
    dual cache+parsed write — parameterized only on the base URL /
    cache directory / ``source`` label, plus the generator-version
    extraction added for the drift tripwire.
    """
    if not is_valid_arxiv_paper_id(paper_id):
        raise ValueError(
            f"paper_id {paper_id!r} does not match the arXiv id "
            f"format (new-style YYMM.NNNNN or old-style "
            f"subject/NNNNNNN)"
        )

    def _miss(reason: str) -> Ar5ivResult:
        return Ar5ivResult(
            paper_id=paper_id,
            hit=False,
            cache_path=None,
            parsed_path=None,
            reason=reason,
            source=source,
        )

    cache_path = cache_dir / f"{paper_id}.html"
    parsed_paper_dir = parsed_dir / paper_id
    parsed_path = parsed_paper_dir / "index.html"

    if cache_path.is_file() and parsed_path.is_file():
        logger.debug("%s: cache hit on disk for %s", source, paper_id)
        return Ar5ivResult(
            paper_id=paper_id,
            hit=True,
            cache_path=cache_path,
            parsed_path=parsed_path,
            reason="ok_local_cache",
            source=source,
            latexml_generator=_generator_from_file(cache_path),
        )

    url = f"{base_url}/{paper_id}"
    request = urllib.request.Request(
        url, headers={"User-Agent": user_agent, "Accept": "text/html"}
    )
    try:
        with urllib.request.urlopen(  # noqa: S310 — fixed https URL
            request, timeout=timeout_seconds, context=ssl_context
        ) as response:
            status = response.status
            # E13_S07 Threat 7: pre-read Content-Length sanity check.
            # When the server announces an oversized body, refuse
            # before any bytes are buffered. The header is advisory
            # (RFC 9110 § 8.6 — may be absent or wrong) so this is
            # belt + braces with the read-cap below.
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    declared_int = int(declared)
                except (TypeError, ValueError):
                    declared_int = -1
                if declared_int > AR5IV_MAX_RESPONSE_BYTES:
                    logger.warning(
                        "%s: Content-Length %d > cap %d for %s; "
                        "treating as miss (Threat 7)",
                        source,
                        declared_int,
                        AR5IV_MAX_RESPONSE_BYTES,
                        paper_id,
                    )
                    return _miss("oversized_content_length")
            # E13_S07: read at most cap+1 bytes; treat any
            # over-cap actual read as a lie / missing-header attack
            # and refuse. This bounds memory to ~100 MB worst case
            # even when the header is missing or wrong.
            body_bytes = response.read(AR5IV_MAX_RESPONSE_BYTES + 1)
            if len(body_bytes) > AR5IV_MAX_RESPONSE_BYTES:
                logger.warning(
                    "%s: response body for %s exceeded cap %d "
                    "(Content-Length=%r); treating as miss (Threat 7)",
                    source,
                    paper_id,
                    AR5IV_MAX_RESPONSE_BYTES,
                    declared,
                )
                return _miss("oversized_body")
            # Closes F9: ``urllib.request.urlopen`` silently follows
            # 3xx redirects to any host. Both surfaces are static
            # CDN-fronted content; the only benign redirect is the
            # native surface's unversioned→versioned rewrite, which
            # stays under the pinned base URL and passes the check.
            # A redirect off the base is either a CDN
            # misconfiguration or an active attack — reject it to
            # keep egress pinned to the expected host.
            response_url = response.url
        if not response_url.startswith(base_url + "/"):
            logger.warning(
                "%s: response redirected off %s for %s -> %s; "
                "treating as miss",
                source, base_url, paper_id, response_url,
            )
            return _miss("unexpected_redirect")
    except urllib.error.HTTPError as exc:
        logger.info(
            "%s: HTTP %d for %s (miss; falling back)",
            source, exc.code, paper_id,
        )
        return _miss(f"http_{exc.code}")
    except (TimeoutError, urllib.error.URLError) as exc:
        logger.info("%s: network error for %s: %s", source, paper_id, exc)
        return _miss("timeout_or_network")

    if status != 200:
        return _miss(f"http_{status}")

    body = body_bytes.decode("utf-8", errors="replace")
    if not _MATH_SIGNAL_RE.search(body) or _AR5IV_ERROR_BANNER in body:
        # ar5iv error banner is a 200 with no MathML, or a 200 that
        # also contains the explicit "could not be processed" string.
        # Treat either as miss. (The native surface 404s instead of
        # serving a banner; the ``<math\b`` check still guards it.)
        logger.info(
            "%s: 200 for %s with no usable math signal — miss",
            source, paper_id,
        )
        return _miss("no_math_in_body")

    # Hit. Write to cache AND to the canonical parsed path so the
    # chunker's existing HTML walk reads it unchanged.
    # Old-style ids (e.g. ``math/0212237``) embed a slash, so
    # ``cache_path`` lands in a ``<subject>/`` subdir of ``cache_dir``;
    # create the leaf's parent, not just the base ``cache_dir``, or the
    # write below raises FileNotFoundError on a fresh cache tree.
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    parsed_paper_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(body, encoding="utf-8")
    parsed_path.write_text(body, encoding="utf-8")

    logger.info(
        "%s: cache hit for %s (%d bytes)", source, paper_id, len(body),
    )
    return Ar5ivResult(
        paper_id=paper_id,
        hit=True,
        cache_path=cache_path,
        parsed_path=parsed_path,
        reason="ok",
        source=source,
        latexml_generator=extract_latexml_generator(body),
    )


__all__ = [
    "AR5IV_BASE_URL",
    "AR5IV_TIMEOUT_SECONDS",
    "ARXIV_NATIVE_BASE_URL",
    "Ar5ivResult",
    "DEFAULT_AR5IV_CACHE_DIR",
    "DEFAULT_NATIVE_CACHE_DIR",
    "DEFAULT_PARSED_DIR",
    "extract_latexml_generator",
    "try_cache",
    "try_html_sources",
    "try_native",
]
