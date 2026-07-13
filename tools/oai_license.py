"""OAI-PMH per-paper license client + advisory license-decision fn (source-truth-m1).

The load-bearing pivot the source-truth spike proved: arXiv license URIs
come from the OAI-PMH ``GetRecord`` surface, NOT the Atom client in
:mod:`tools._arxiv_api` (Atom is a confirmed schema-level 0/30 absence).
This module issues one ``GetRecord`` per version-stripped work id and
parses the OPTIONAL ``<license>`` element, together with the withdrawn
signal (``<header status="deleted">``) that rides the same fetch.

**Why a self-contained fetch (not a reuse of ``ingest.oai_delta``).**
``ingest/oai_delta.py::_fetch_page`` already solves the identical
503/``Retry-After``/backoff/redirect-pin problem and is critique-hardened
— but importing it pulls in ``ingest.bulk_ingest``, which imports the
BGE-M3 embedder and ``ingest.store`` (``ingest/bulk_ingest.py:66-68``).
The documents backfill's "0 chunks re-embedded" guarantee is STRUCTURAL:
it must never even import the embedder. So the 503/backoff/redirect-pin
logic and its constants are RE-MIRRORED here (a deliberate ~60-line
duplication) to keep this module's import graph clean: stdlib +
``defusedxml`` + ``tools.arxiv_fetch`` + ``ingest.identifiers`` only.

**Parsing** uses ``defusedxml.ElementTree`` (XXE / entity-expansion
safe — the response is untrusted external data, Threat 7), matching
:mod:`tools._arxiv_api`'s convention and deliberately NOT copying
``oai_delta.py``'s plain-``xml.etree`` choice.

**License-decision function** (:func:`decide_license_status`) is ADVISORY
ONLY. It maps a fetched URI to a 3-way ``license_status`` and does NOT
touch :mod:`server.license_policy` (that token-allowlist + its actual
serving behavior is the owner-gated m4 cutover). The 3-way split is the
source-truth-m1 OWNER DECISION: ``eligible`` (a CC-allowlisted open URI)
/ ``not-allowlisted-open`` (a real dereferenceable URI recovered but not
CC-allowlisted, e.g. arXiv's default ``nonexclusive-distrib`` — its OA
policy call is the owner's, not m1's) / ``unknown`` (no license data —
the old-style gap). These three are NEVER folded together: ``unknown``
is a genuine data gap, ``not-allowlisted-open`` is an
eligibility-pending-policy decision, and conflating them corrupts the
coverage report's >20% owner-escalation signal.
"""

from __future__ import annotations

import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

import defusedxml.ElementTree as DET

from ingest.identifiers import is_valid_arxiv_paper_id
from tools._arxiv_api import strip_id_version
from tools.arxiv_fetch import POLITENESS_SLEEP_SECONDS

logger = logging.getLogger("oai_license")

#: OAI-PMH endpoint. The CANONICAL host arXiv itself reports serving
#: from (its ``<request>`` element self-identifies as
#: ``http://oaipmh.arxiv.org/oai`` even when queried via the legacy
#: ``export.arxiv.org/oai2`` alias); arXiv migrated here in March 2025.
#: Mirrors ``ingest.oai_delta.OAI_PMH_ENDPOINT``.
OAI_PMH_ENDPOINT: str = "https://oaipmh.arxiv.org/oai"

#: Metadata format. The plain ``arXiv`` prefix carries the ``<license>``
#: element (live-verified in the source-truth-m1 research). ``arXivRaw``
#: (which ``oai_delta`` uses) also carries it but adds version history
#: this per-paper license lookup does not need.
METADATA_PREFIX: str = "arXiv"

#: Per-request timeout. A single ``GetRecord`` response is a few KB;
#: 30s is generous for slow links but short enough that a stuck
#: connection cannot poison the run.
OAI_PMH_TIMEOUT_SECONDS: float = 30.0

#: Threat 7 content-length sanity cap. A ``GetRecord`` response is a few
#: KB and never legitimately approaches this; the cap guards against a
#: lying ``Content-Length`` / hostile chunked body. Applied at the
#: header (pre-read reject) AND the actual read size.
OAI_PMH_MAX_RESPONSE_BYTES: int = 100 * 1024 * 1024

#: 503-retry wall-clock cap (mirrors ``oai_delta``): back off with
#: exponential schedule (or ``Retry-After``) and give up after at most
#: one hour rather than spinning against a sustained arXiv outage.
DEFAULT_RETRY_CAP_SECONDS: float = 3600.0
DEFAULT_BACKOFF_INITIAL_SECONDS: float = 30.0
DEFAULT_BACKOFF_MAX_SECONDS: float = 600.0

#: OAI-PMH XML namespaces for the plain ``arXiv`` metadata format. The
#: metadata element sits under ``http://arxiv.org/OAI/arXiv/`` (distinct
#: from ``oai_delta``'s ``arXivRaw`` namespace).
_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "arxiv": "http://arxiv.org/OAI/arXiv/",
}

#: OAI-PMH identifier prefix for arXiv works. Old-style ids keep their
#: archive prefix and literal ``/`` (``oai:arXiv.org:math/0212237``).
_OAI_IDENTIFIER_PREFIX: str = "oai:arXiv.org:"

# ---------------------------------------------------------------------------
# License-decision vocabulary (source-truth-m1 OWNER DECISION — 3-way)
# ---------------------------------------------------------------------------

#: A CC-allowlisted open license URI (full-body eligible).
LICENSE_STATUS_ELIGIBLE: str = "eligible"

#: A real, dereferenceable license URI was recovered but it is NOT
#: CC-allowlisted (e.g. arXiv's default ``nonexclusive-distrib``). Its
#: open-access policy call is the owner's (D8-R04), not m1's. Kept
#: DISTINCT from ``unknown``: "we have data, the policy is pending",
#: not "we have no data".
LICENSE_STATUS_NOT_ALLOWLISTED_OPEN: str = "not-allowlisted-open"

#: No license data at all — the old-style arXiv-side gap (missing
#: ``<license>`` element) or ``idDoesNotExist``. A genuine data gap.
LICENSE_STATUS_UNKNOWN: str = "unknown"

#: Substring markers for the CC families that correspond to
#: :data:`server.license_policy.OA_ALLOWLIST`'s open tokens (``CC-BY`` /
#: ``CC-BY-SA`` / ``CC0`` / ``public-domain`` / ``GFDL``). Matched as a
#: case-insensitive substring of the URI. DELIBERATELY narrow: arXiv
#: also serves ``by-nc-sa`` / ``by-nc-nd`` (non-commercial /
#: no-derivatives), which are NOT in the OA allowlist and must fall
#: through to ``not-allowlisted-open`` — a blanket ``creativecommons.org``
#: match would wrongly promote them. This mirrors the allowlist's intent
#: WITHOUT importing or modifying ``server/license_policy.py`` (m4-owned).
_CC_ELIGIBLE_URI_MARKERS: tuple[str, ...] = (
    "creativecommons.org/licenses/by/",       # CC-BY
    "creativecommons.org/licenses/by-sa/",    # CC-BY-SA
    "creativecommons.org/publicdomain/zero/",  # CC0
    "creativecommons.org/publicdomain/mark/",  # public-domain
    "gnu.org/licenses/fdl",                    # GFDL
)


def decide_license_status(license_uri: str | None) -> str:
    """Advisory URI -> 3-way ``license_status`` mapping.

    - ``None`` / empty (no ``<license>`` element recovered) ->
      :data:`LICENSE_STATUS_UNKNOWN`.
    - A CC-allowlisted-family URI (:data:`_CC_ELIGIBLE_URI_MARKERS`) ->
      :data:`LICENSE_STATUS_ELIGIBLE`.
    - Any OTHER real URI, including arXiv's default
      ``http://arxiv.org/licenses/nonexclusive-distrib/1.0/`` ->
      :data:`LICENSE_STATUS_NOT_ALLOWLISTED_OPEN` (a real license,
      allowlist decision pending — the owner's, per D8-R04).

    A pure predicate — no invariant to guard, so no ``assert`` (banned,
    CLAUDE.md 4.7) and no ``raise``. Advisory only: it never mutates
    serving behavior.
    """
    if not license_uri:
        return LICENSE_STATUS_UNKNOWN
    normalized = license_uri.strip().lower()
    if not normalized:
        return LICENSE_STATUS_UNKNOWN
    if any(marker in normalized for marker in _CC_ELIGIBLE_URI_MARKERS):
        return LICENSE_STATUS_ELIGIBLE
    return LICENSE_STATUS_NOT_ALLOWLISTED_OPEN


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OaiLicenseRecord:
    """One parsed ``GetRecord`` response for a single work id.

    ``found`` is ``False`` for an ``idDoesNotExist`` error (a per-paper,
    non-fatal outcome). ``license_uri`` is ``None`` when the ``<license>``
    element is absent (an EXPECTED first-class outcome, the old-style
    gap — not a parse error). ``deleted`` reflects
    ``<header status="deleted">`` (the withdrawn signal, surfaced from
    the SAME fetch so one round-trip hydrates both license and status).
    """

    work_id: str
    found: bool
    deleted: bool
    license_uri: str | None
    datestamp: str = ""


# ---------------------------------------------------------------------------
# URL building
# ---------------------------------------------------------------------------


def build_getrecord_url(
    work_id: str,
    *,
    endpoint: str = OAI_PMH_ENDPOINT,
    metadata_prefix: str = METADATA_PREFIX,
) -> str:
    """Build the ``GetRecord`` URL for a work id.

    Strips any trailing ``vN`` (OAI-PMH identifiers name the WORK, not a
    version snapshot; a versioned identifier is not expected to resolve),
    validates the version-stripped id with
    :func:`ingest.identifiers.is_valid_arxiv_paper_id`, and joins it to
    ``oai:arXiv.org:``. The old-style archive prefix + its literal ``/``
    are preserved. ``:`` and ``/`` are kept unescaped (``safe=":/"``,
    mirroring ``_arxiv_api.build_id_list_url``'s convention and the
    live-verified working requests).
    """
    bare_id = strip_id_version(work_id)
    if not is_valid_arxiv_paper_id(bare_id):
        raise ValueError(
            f"work_id {work_id!r} (stripped: {bare_id!r}) is not a "
            f"well-formed arXiv id; refusing to build a GetRecord URL"
        )
    params = {
        "verb": "GetRecord",
        "identifier": f"{_OAI_IDENTIFIER_PREFIX}{bare_id}",
        "metadataPrefix": metadata_prefix,
    }
    return f"{endpoint}?{urllib.parse.urlencode(params, safe=':/')}"


# ---------------------------------------------------------------------------
# HTTP fetch (re-mirrored from ingest.oai_delta._fetch_page)
# ---------------------------------------------------------------------------


def _parse_retry_after(header_value: str | None) -> float | None:
    """Parse a ``Retry-After`` header. Returns seconds, or ``None``.

    Honors the RFC 7231 delta-seconds form; the rare HTTP-date form
    falls back to the exponential schedule. Mirrors
    ``ingest.oai_delta._parse_retry_after``.
    """
    if not header_value:
        return None
    value = header_value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _fetch_record(
    url: str,
    *,
    timeout_seconds: float = OAI_PMH_TIMEOUT_SECONDS,
    user_agent: str,
    sleep=time.sleep,
    monotonic=time.monotonic,
    retry_cap_seconds: float = DEFAULT_RETRY_CAP_SECONDS,
    backoff_initial: float = DEFAULT_BACKOFF_INITIAL_SECONDS,
    backoff_max: float = DEFAULT_BACKOFF_MAX_SECONDS,
) -> bytes:
    """GET one ``GetRecord`` URL with the arXiv politeness/backoff contract.

    Re-mirrors ``ingest.oai_delta._fetch_page`` (F1 + F2 hardened):

    * **503 -> Retry-After + exponential backoff**, capped per-wait at
      ``backoff_max`` and overall at ``retry_cap_seconds`` (default 1h).
      ``urllib`` raises ``HTTPError`` on every status >= 400, so 503 is
      caught explicitly; non-503 errors propagate immediately.
    * **Redirect pinning.** After a successful read, verify the resolved
      URL still starts with the endpoint host — ``urllib`` silently
      follows 3xx, and a poisoned redirect off ``oaipmh.arxiv.org`` must
      never be trusted as OAI-PMH XML.
    * **Content-Length + read-cap** (Threat 7) — refuse an oversized
      body at the header and at the actual read.
    """
    request = urllib.request.Request(
        url, headers={"User-Agent": user_agent, "Accept": "application/xml"}
    )
    deadline = monotonic() + retry_cap_seconds
    backoff = backoff_initial
    while True:
        try:
            with urllib.request.urlopen(  # noqa: S310 — pinned arxiv host
                request, timeout=timeout_seconds
            ) as response:
                declared = response.headers.get("Content-Length")
                if declared is not None:
                    try:
                        declared_int = int(declared)
                    except (TypeError, ValueError):
                        declared_int = -1
                    if declared_int > OAI_PMH_MAX_RESPONSE_BYTES:
                        raise RuntimeError(
                            f"OAI-PMH Content-Length {declared_int} exceeds "
                            f"cap {OAI_PMH_MAX_RESPONSE_BYTES} bytes "
                            f"(Threat 7); refusing"
                        )
                body = response.read(OAI_PMH_MAX_RESPONSE_BYTES + 1)
                if len(body) > OAI_PMH_MAX_RESPONSE_BYTES:
                    raise RuntimeError(
                        f"OAI-PMH response body exceeded cap "
                        f"{OAI_PMH_MAX_RESPONSE_BYTES} bytes "
                        f"(Content-Length={declared!r}); refusing"
                    )
                response_url = response.url
            if not response_url.startswith(OAI_PMH_ENDPOINT):
                raise RuntimeError(
                    f"OAI-PMH response redirected off {OAI_PMH_ENDPOINT}: "
                    f"got {response_url!r}; refusing as untrusted"
                )
            return body
        except urllib.error.HTTPError as exc:
            if exc.code != 503:
                raise
            retry_after = _parse_retry_after(
                exc.headers.get("Retry-After") if exc.headers else None
            )
            wait = retry_after if retry_after is not None else backoff
            # Never drop below the arXiv politeness floor: arXiv has served
            # Retry-After: 0, which would otherwise spin the 503 path with
            # zero inter-request delay until the cap (adversary H2). The
            # clamp still honors a server-requested LONGER delay.
            wait = max(wait, POLITENESS_SLEEP_SECONDS)
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    f"OAI-PMH 503 retry cap of {retry_cap_seconds:.0f}s "
                    f"exhausted for {url}"
                ) from exc
            wait = min(wait, remaining)
            logger.warning(
                "oai_license: HTTP 503 from %s; backing off %.1fs "
                "(retry-after=%s)",
                OAI_PMH_ENDPOINT, wait, retry_after,
            )
            sleep(wait)
            backoff = min(backoff * 2.0, backoff_max)


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------


def parse_getrecord(body: bytes, *, work_id: str = "") -> OaiLicenseRecord:
    """Parse one ``GetRecord`` response body.

    Outcomes:

    - ``<error code="idDoesNotExist">`` -> ``found=False`` (per-paper,
      non-fatal — arXiv genuinely has no such identifier).
    - Any OTHER ``<error>`` code (``badArgument`` /
      ``cannotDisseminateFormat`` / ``badVerb`` / ``idDoesNotExist``'s
      siblings) -> ``RuntimeError`` (a client/programming error the
      backfill degrades to a per-paper miss, retry-able).
    - A ``<record>`` with ``<header status="deleted">`` -> ``deleted=True``
      (withdrawn; no ``<metadata>`` block, so ``license_uri=None``).
    - A ``<record>`` with a ``<license>`` text node -> that URI.
    - A ``<record>`` WITHOUT a ``<license>`` element -> ``license_uri=None``
      (an EXPECTED first-class outcome, NOT a parse error).

    Uses ``defusedxml`` (XXE-safe). Non-XML bytes raise ``RuntimeError``.
    """
    try:
        root = DET.fromstring(body)
    except DET.ParseError as exc:
        raise RuntimeError(
            f"OAI-PMH returned a non-XML / malformed response: {exc}"
        ) from exc

    error_el = root.find("oai:error", _NS)
    if error_el is not None:
        code = error_el.get("code", "unknown")
        if code == "idDoesNotExist":
            return OaiLicenseRecord(
                work_id=work_id, found=False, deleted=False, license_uri=None,
            )
        msg = (error_el.text or "").strip()
        raise RuntimeError(f"OAI-PMH error code={code}: {msg}")

    record = root.find("oai:GetRecord/oai:record", _NS)
    if record is None:
        raise RuntimeError(
            "OAI-PMH GetRecord response had neither an <error> nor a "
            "<record> element; unexpected shape"
        )

    header = record.find("oai:header", _NS)
    deleted = header is not None and header.get("status") == "deleted"
    datestamp_el = (
        header.find("oai:datestamp", _NS) if header is not None else None
    )
    datestamp = (
        datestamp_el.text.strip()
        if datestamp_el is not None and datestamp_el.text
        else ""
    )

    license_uri: str | None = None
    metadata = record.find("oai:metadata", _NS)
    if metadata is not None:
        arxiv_el = metadata.find("arxiv:arXiv", _NS)
        if arxiv_el is not None:
            lic = arxiv_el.find("arxiv:license", _NS)
            if lic is not None and lic.text and lic.text.strip():
                license_uri = lic.text.strip()

    return OaiLicenseRecord(
        work_id=work_id,
        found=True,
        deleted=deleted,
        license_uri=license_uri,
        datestamp=datestamp,
    )


# ---------------------------------------------------------------------------
# High-level fetch
# ---------------------------------------------------------------------------


def fetch_license(
    work_id: str,
    *,
    user_agent: str,
    endpoint: str = OAI_PMH_ENDPOINT,
    metadata_prefix: str = METADATA_PREFIX,
    timeout_seconds: float = OAI_PMH_TIMEOUT_SECONDS,
    fetch=None,
) -> OaiLicenseRecord:
    """Fetch + parse the license record for one work id.

    Does NOT sleep — the CALLER owns the 3s politeness budget
    (:data:`POLITENESS_SLEEP_SECONDS`), mirroring the
    ``notebook_metadata_backfill`` convention where politeness is
    sequenced across the whole run. ``fetch`` is a test seam (defaults to
    :func:`_fetch_record`); production callers pass only ``work_id`` +
    ``user_agent``.

    Raises ``RuntimeError`` on a transient fetch failure (503 budget
    exhausted, redirect off-host, oversized body) or a fatal OAI-PMH
    error code — the backfill catches it as a per-paper miss so a re-run
    retries. An ``idDoesNotExist`` is NOT an error here: it returns a
    ``found=False`` record.
    """
    if fetch is None:
        fetch = _fetch_record
    url = build_getrecord_url(
        work_id, endpoint=endpoint, metadata_prefix=metadata_prefix,
    )
    body = fetch(url, timeout_seconds=timeout_seconds, user_agent=user_agent)
    return parse_getrecord(body, work_id=strip_id_version(work_id))


__all__ = [
    "DEFAULT_BACKOFF_INITIAL_SECONDS",
    "DEFAULT_BACKOFF_MAX_SECONDS",
    "DEFAULT_RETRY_CAP_SECONDS",
    "LICENSE_STATUS_ELIGIBLE",
    "LICENSE_STATUS_NOT_ALLOWLISTED_OPEN",
    "LICENSE_STATUS_UNKNOWN",
    "METADATA_PREFIX",
    "OAI_PMH_ENDPOINT",
    "OAI_PMH_MAX_RESPONSE_BYTES",
    "OAI_PMH_TIMEOUT_SECONDS",
    "POLITENESS_SLEEP_SECONDS",
    "OaiLicenseRecord",
    "build_getrecord_url",
    "decide_license_status",
    "fetch_license",
    "parse_getrecord",
]
