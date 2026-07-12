"""ar5iv cache fetcher (E11_S01).

Fetches pre-rendered HTML5+MathML from ``ar5iv.labs.arxiv.org`` for
a given arXiv paper id. The ar5iv service has already run LaTeXML
for ~70-90% of post-2007 papers; using its cache avoids weeks of
local CPU work during the bulk ingest.

Per `.claude/notes/03-ingestion-pipeline.md:87-95` ("Run our local
LaTeXML only on ar5iv cache misses. Saves weeks of CPU.") the
ar5iv-first ladder is the load-bearing ingest strategy.

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
DEFAULT_PARSED_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "parsed"

#: Base URL for the ar5iv cache. The labs domain is the canonical
#: one; arxiv.org/html serves a newer rewrite of the same content
#: but its rollout is incomplete as of 2026-05.
AR5IV_BASE_URL: str = "https://ar5iv.labs.arxiv.org/html"

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
_AR5IV_ERROR_BANNER = "could not be processed"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Ar5ivResult:
    """One ar5iv fetch outcome."""

    paper_id: str
    hit: bool
    cache_path: Path | None       # populated on hit; None on miss
    parsed_path: Path | None      # populated on hit; None on miss
    reason: str                   # "ok" / "404" / "timeout" / "no_math" / etc.


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
    if not is_valid_arxiv_paper_id(paper_id):
        raise ValueError(
            f"paper_id {paper_id!r} does not match the arXiv id "
            f"format (new-style YYMM.NNNNN or old-style "
            f"subject/NNNNNNN)"
        )

    cache_path = cache_dir / f"{paper_id}.html"
    parsed_paper_dir = parsed_dir / paper_id
    parsed_path = parsed_paper_dir / "index.html"

    if cache_path.is_file() and parsed_path.is_file():
        logger.debug("ar5iv: cache hit on disk for %s", paper_id)
        return Ar5ivResult(
            paper_id=paper_id,
            hit=True,
            cache_path=cache_path,
            parsed_path=parsed_path,
            reason="ok_local_cache",
        )

    url = f"{AR5IV_BASE_URL}/{paper_id}"
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
                        "ar5iv: Content-Length %d > cap %d for %s; "
                        "treating as miss (Threat 7)",
                        declared_int,
                        AR5IV_MAX_RESPONSE_BYTES,
                        paper_id,
                    )
                    return Ar5ivResult(
                        paper_id=paper_id,
                        hit=False,
                        cache_path=None,
                        parsed_path=None,
                        reason="oversized_content_length",
                    )
            # E13_S07: read at most cap+1 bytes; treat any
            # over-cap actual read as a lie / missing-header attack
            # and refuse. This bounds memory to ~100 MB worst case
            # even when the header is missing or wrong.
            body_bytes = response.read(AR5IV_MAX_RESPONSE_BYTES + 1)
            if len(body_bytes) > AR5IV_MAX_RESPONSE_BYTES:
                logger.warning(
                    "ar5iv: response body for %s exceeded cap %d "
                    "(Content-Length=%r); treating as miss (Threat 7)",
                    paper_id,
                    AR5IV_MAX_RESPONSE_BYTES,
                    declared,
                )
                return Ar5ivResult(
                    paper_id=paper_id,
                    hit=False,
                    cache_path=None,
                    parsed_path=None,
                    reason="oversized_body",
                )
            # Closes F9: ``urllib.request.urlopen`` silently follows
            # 3xx redirects to any host. ar5iv is a static CDN that
            # doesn't redirect, so a redirect off-domain is either a
            # CDN misconfiguration or an active attack. Reject the
            # response to keep egress pinned to ar5iv.labs.arxiv.org.
            response_url = response.url
        if not response_url.startswith(AR5IV_BASE_URL + "/"):
            logger.warning(
                "ar5iv: response redirected off %s for %s -> %s; "
                "treating as miss",
                AR5IV_BASE_URL, paper_id, response_url,
            )
            return Ar5ivResult(
                paper_id=paper_id,
                hit=False,
                cache_path=None,
                parsed_path=None,
                reason="unexpected_redirect",
            )
    except urllib.error.HTTPError as exc:
        logger.info(
            "ar5iv: HTTP %d for %s (miss; falling back)",
            exc.code, paper_id,
        )
        return Ar5ivResult(
            paper_id=paper_id,
            hit=False,
            cache_path=None,
            parsed_path=None,
            reason=f"http_{exc.code}",
        )
    except (TimeoutError, urllib.error.URLError) as exc:
        logger.info("ar5iv: network error for %s: %s", paper_id, exc)
        return Ar5ivResult(
            paper_id=paper_id,
            hit=False,
            cache_path=None,
            parsed_path=None,
            reason="timeout_or_network",
        )

    if status != 200:
        return Ar5ivResult(
            paper_id=paper_id,
            hit=False,
            cache_path=None,
            parsed_path=None,
            reason=f"http_{status}",
        )

    body = body_bytes.decode("utf-8", errors="replace")
    if not _MATH_SIGNAL_RE.search(body) or _AR5IV_ERROR_BANNER in body:
        # ar5iv error banner is a 200 with no MathML, or a 200 that
        # also contains the explicit "could not be processed" string.
        # Treat either as miss.
        logger.info(
            "ar5iv: 200 for %s with no usable math signal — miss",
            paper_id,
        )
        return Ar5ivResult(
            paper_id=paper_id,
            hit=False,
            cache_path=None,
            parsed_path=None,
            reason="no_math_in_body",
        )

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

    # ingest-robustness-m1 (AC4): a render can pass the <math> gate yet carry
    # NO ltx_section/theorem/proof structure (LaTeXML sectioning failure on old
    # formats, e.g. hep-th/0002037). The chunker's section-less fallback now
    # recovers most of these, but flag it so an operator can route a residual
    # math-only render to the PDF/MinerU path. Fresh-fetch path only (the
    # local-cache early-return above never reads the body), so this is a
    # secondary observability signal, not a per-run guarantee.
    if not any(sig in body for sig in ("ltx_section", "ltx_theorem", "ltx_proof")):
        logger.warning(
            "ar5iv: %s rendered with math but no ltx_section/theorem/proof "
            "structure — may be unchunkable; the PDF/MinerU path "
            "(tools/notebook_pdf_parse.py) may be needed",
            paper_id,
        )

    logger.info("ar5iv: cache hit for %s (%d bytes)", paper_id, len(body))
    return Ar5ivResult(
        paper_id=paper_id,
        hit=True,
        cache_path=cache_path,
        parsed_path=parsed_path,
        reason="ok",
    )


__all__ = [
    "AR5IV_BASE_URL",
    "AR5IV_TIMEOUT_SECONDS",
    "Ar5ivResult",
    "DEFAULT_AR5IV_CACHE_DIR",
    "DEFAULT_PARSED_DIR",
    "try_cache",
]
