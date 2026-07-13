"""Tests for ``tools.oai_license`` (source-truth-m1).

Mirrors the ``tests/test_oai_delta.py`` / ``tests/test_arxiv_api*.py``
style: canned OAI-PMH XML fed to the parser, and the HTTP layer mocked
(``urllib.request.urlopen`` patched) so no live network is touched.
Covers GetRecord parse (license present -> URI, absent -> None),
``<header status="deleted">`` -> withdrawn, ``idDoesNotExist`` ->
found=False (non-fatal), the ``defusedxml`` choice, the 503/Retry-After
backoff, redirect-pinning, and the advisory 3-way decision function
(including the ``nonexclusive-distrib`` case).
"""

from __future__ import annotations

import email.message
import inspect
import textwrap
import urllib.error
from unittest.mock import patch

import pytest

import tools.oai_license as oai_license
from tools.oai_license import (
    LICENSE_STATUS_ELIGIBLE,
    LICENSE_STATUS_NOT_ALLOWLISTED_OPEN,
    LICENSE_STATUS_UNKNOWN,
    OAI_PMH_ENDPOINT,
    OaiLicenseRecord,
    build_getrecord_url,
    decide_license_status,
    fetch_license,
    parse_getrecord,
)

NONEXCLUSIVE = "http://arxiv.org/licenses/nonexclusive-distrib/1.0/"
CC_BY = "http://creativecommons.org/licenses/by/4.0/"


# ---------------------------------------------------------------------------
# XML fixtures
# ---------------------------------------------------------------------------


def _getrecord(
    paper_id: str,
    *,
    license_uri: str | None = NONEXCLUSIVE,
    deleted: bool = False,
) -> bytes:
    if deleted:
        record_inner = f"""
          <record>
            <header status="deleted">
              <identifier>oai:arXiv.org:{paper_id}</identifier>
              <datestamp>2021-01-01</datestamp>
            </header>
          </record>
        """
    else:
        license_el = (
            f"<license>{license_uri}</license>" if license_uri is not None else ""
        )
        record_inner = f"""
          <record>
            <header>
              <identifier>oai:arXiv.org:{paper_id}</identifier>
              <datestamp>2020-06-22</datestamp>
            </header>
            <metadata>
              <arXiv xmlns="http://arxiv.org/OAI/arXiv/">
                <id>{paper_id}</id>
                <title>A paper title</title>
                <abstract>An abstract.</abstract>
                {license_el}
              </arXiv>
            </metadata>
          </record>
        """
    return textwrap.dedent(
        f"""<?xml version="1.0" encoding="UTF-8"?>
        <OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
          <responseDate>2026-07-12T00:00:00Z</responseDate>
          <request verb="GetRecord" identifier="oai:arXiv.org:{paper_id}"
                   metadataPrefix="arXiv">https://oaipmh.arxiv.org/oai</request>
          <GetRecord>{record_inner}</GetRecord>
        </OAI-PMH>
        """
    ).encode("utf-8")


def _error(code: str, msg: str = "boom") -> bytes:
    return textwrap.dedent(
        f"""<?xml version="1.0" encoding="UTF-8"?>
        <OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
          <responseDate>2026-07-12T00:00:00Z</responseDate>
          <error code="{code}">{msg}</error>
        </OAI-PMH>
        """
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# parse_getrecord
# ---------------------------------------------------------------------------


class TestParseGetRecord:
    def test_license_present_returns_uri(self):
        rec = parse_getrecord(_getrecord("2006.10956"), work_id="2006.10956")
        assert rec.found is True
        assert rec.deleted is False
        assert rec.license_uri == NONEXCLUSIVE
        assert rec.datestamp == "2020-06-22"

    def test_license_absent_returns_none_not_error(self):
        """A missing <license> is an EXPECTED first-class outcome (the
        old-style gap), NOT a parse error."""
        rec = parse_getrecord(
            _getrecord("math/0212237", license_uri=None),
            work_id="math/0212237",
        )
        assert rec.found is True
        assert rec.deleted is False
        assert rec.license_uri is None

    def test_deleted_header_flags_withdrawn(self):
        rec = parse_getrecord(
            _getrecord("2006.10956", deleted=True), work_id="2006.10956",
        )
        assert rec.found is True
        assert rec.deleted is True
        assert rec.license_uri is None

    def test_id_does_not_exist_is_nonfatal(self):
        """``idDoesNotExist`` -> found=False, no raise (per-paper skip)."""
        rec = parse_getrecord(_error("idDoesNotExist"), work_id="2401.99999")
        assert rec.found is False
        assert rec.deleted is False
        assert rec.license_uri is None

    def test_other_error_code_raises(self):
        with pytest.raises(RuntimeError, match="cannotDisseminateFormat"):
            parse_getrecord(_error("cannotDisseminateFormat"))

    def test_non_xml_raises_runtimeerror(self):
        with pytest.raises(RuntimeError, match="non-XML"):
            parse_getrecord(b"<html>maintenance</html not xml")

    def test_missing_record_and_error_raises(self):
        body = (
            b'<?xml version="1.0"?>'
            b'<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">'
            b"<responseDate>2026-07-12T00:00:00Z</responseDate>"
            b"</OAI-PMH>"
        )
        with pytest.raises(RuntimeError, match="unexpected shape"):
            parse_getrecord(body)

    def test_parser_uses_defusedxml(self):
        """XXE-safety: the module must parse with defusedxml, not the
        stdlib ElementTree (the oai_delta inconsistency this client
        deliberately does NOT copy)."""
        source = inspect.getsource(oai_license)
        assert "import defusedxml" in source
        assert "import xml.etree.ElementTree" not in source


# ---------------------------------------------------------------------------
# build_getrecord_url
# ---------------------------------------------------------------------------


class TestBuildGetRecordURL:
    def test_new_style_url(self):
        url = build_getrecord_url("2006.10956")
        assert url == (
            "https://oaipmh.arxiv.org/oai?verb=GetRecord"
            "&identifier=oai:arXiv.org:2006.10956&metadataPrefix=arXiv"
        )

    def test_version_is_stripped(self):
        """OAI-PMH identifiers name the WORK; the vN is stripped."""
        url = build_getrecord_url("2006.10956v3")
        assert "oai:arXiv.org:2006.10956&" in url
        assert "v3" not in url

    def test_old_style_prefix_and_slash_preserved_unescaped(self):
        url = build_getrecord_url("math/0212237")
        assert "identifier=oai:arXiv.org:math/0212237&" in url
        assert "%2F" not in url  # slash kept literal
        assert "%3A" not in url  # colon kept literal

    def test_malformed_id_raises(self):
        with pytest.raises(ValueError, match="well-formed arXiv id"):
            build_getrecord_url("not-an-id!")


# ---------------------------------------------------------------------------
# decide_license_status (advisory 3-way)
# ---------------------------------------------------------------------------


class TestDecideLicenseStatus:
    def test_none_is_unknown(self):
        assert decide_license_status(None) == LICENSE_STATUS_UNKNOWN

    def test_empty_is_unknown(self):
        assert decide_license_status("") == LICENSE_STATUS_UNKNOWN
        assert decide_license_status("   ") == LICENSE_STATUS_UNKNOWN

    def test_nonexclusive_distrib_is_not_allowlisted_open(self):
        """The dominant arXiv default: a REAL license, allowlist decision
        pending — NEVER folded into unknown or eligible."""
        assert decide_license_status(NONEXCLUSIVE) == (
            LICENSE_STATUS_NOT_ALLOWLISTED_OPEN
        )

    def test_cc_by_is_eligible(self):
        assert decide_license_status(CC_BY) == LICENSE_STATUS_ELIGIBLE

    def test_cc_by_sa_is_eligible(self):
        assert decide_license_status(
            "http://creativecommons.org/licenses/by-sa/4.0/"
        ) == LICENSE_STATUS_ELIGIBLE

    def test_cc0_is_eligible(self):
        assert decide_license_status(
            "http://creativecommons.org/publicdomain/zero/1.0/"
        ) == LICENSE_STATUS_ELIGIBLE

    def test_cc_by_nc_is_not_eligible(self):
        """Non-commercial / no-derivatives CC variants are NOT in the OA
        allowlist -> not-allowlisted-open (conservative, matches the
        allowlist's intent without a blanket creativecommons.org match)."""
        assert decide_license_status(
            "http://creativecommons.org/licenses/by-nc-sa/4.0/"
        ) == LICENSE_STATUS_NOT_ALLOWLISTED_OPEN
        assert decide_license_status(
            "http://creativecommons.org/licenses/by-nc-nd/4.0/"
        ) == LICENSE_STATUS_NOT_ALLOWLISTED_OPEN

    def test_case_insensitive(self):
        assert decide_license_status(CC_BY.upper()) == LICENSE_STATUS_ELIGIBLE


# ---------------------------------------------------------------------------
# fetch_license + _fetch_record (HTTP mocked)
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, body: bytes, url: str, headers: dict | None = None):
        self._body = body
        self.url = url
        self.headers = email.message.Message()
        for k, v in (headers or {}).items():
            self.headers[k] = v

    def read(self, _n: int = -1) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class TestFetchLicense:
    def test_fetch_license_end_to_end_with_fake_fetch(self):
        """The injectable fetch seam returns bytes; fetch_license builds
        the URL, strips the version, and parses."""
        seen: dict = {}

        def _fake_fetch(url, *, timeout_seconds, user_agent):
            seen["url"] = url
            seen["ua"] = user_agent
            return _getrecord("2006.10956")

        rec = fetch_license(
            "2006.10956v1", user_agent="arXMCP-test", fetch=_fake_fetch,
        )
        assert rec.work_id == "2006.10956"  # version stripped
        assert rec.license_uri == NONEXCLUSIVE
        assert "oai:arXiv.org:2006.10956&" in seen["url"]
        assert seen["ua"] == "arXMCP-test"

    def test_fetch_license_does_not_sleep(self):
        """Politeness is the CALLER's budget: fetch_license issues exactly
        one fetch and never sleeps itself."""
        calls: list[str] = []

        def _fake_fetch(url, *, timeout_seconds, user_agent):
            calls.append(url)
            return _getrecord("math/0212237", license_uri=None)

        with patch("tools.oai_license.time.sleep") as mock_sleep:
            fetch_license(
                "math/0212237", user_agent="ua", fetch=_fake_fetch,
            )
        assert len(calls) == 1
        mock_sleep.assert_not_called()


class TestFetchRecordHTTP:
    def test_503_retry_after_then_success(self):
        """503 with a Retry-After is honored, then the retry succeeds.
        Politeness/rate-limit handling mirrored from oai_delta."""
        attempts = {"n": 0}
        url = f"{OAI_PMH_ENDPOINT}?verb=GetRecord"

        def _fake_urlopen(request, timeout):
            attempts["n"] += 1
            if attempts["n"] == 1:
                headers = email.message.Message()
                headers["Retry-After"] = "7"
                raise urllib.error.HTTPError(
                    url, 503, "Service Unavailable", headers, None,
                )
            return _FakeResponse(_getrecord("2006.10956"), url)

        sleeps: list[float] = []
        with patch("tools.oai_license.urllib.request.urlopen", _fake_urlopen):
            body = oai_license._fetch_record(
                url, user_agent="ua", sleep=sleeps.append,
            )
        assert attempts["n"] == 2
        assert sleeps == [7.0]  # Retry-After honored
        assert b"GetRecord" in body

    def test_503_budget_exhaustion_raises(self):
        url = f"{OAI_PMH_ENDPOINT}?verb=GetRecord"

        def _always_503(request, timeout):
            headers = email.message.Message()
            raise urllib.error.HTTPError(
                url, 503, "Service Unavailable", headers, None,
            )

        # A fake monotonic that jumps past the retry cap after one wait.
        ticks = iter([0.0, 0.0, 10_000.0, 10_000.0, 10_000.0])
        with (
            patch("tools.oai_license.urllib.request.urlopen", _always_503),
            pytest.raises(RuntimeError, match="retry cap"),
        ):
            oai_license._fetch_record(
                url,
                user_agent="ua",
                sleep=lambda _s: None,
                monotonic=lambda: next(ticks),
            )

    def test_non_503_http_error_propagates(self):
        url = f"{OAI_PMH_ENDPOINT}?verb=GetRecord"

        def _fake_urlopen(request, timeout):
            raise urllib.error.HTTPError(
                url, 400, "Bad Request", email.message.Message(), None,
            )

        with (
            patch("tools.oai_license.urllib.request.urlopen", _fake_urlopen),
            pytest.raises(urllib.error.HTTPError),
        ):
            oai_license._fetch_record(url, user_agent="ua")

    def test_redirect_off_host_is_refused(self):
        """A response resolved off the OAI-PMH endpoint is refused as
        untrusted (redirect-pinning)."""
        url = f"{OAI_PMH_ENDPOINT}?verb=GetRecord"

        def _fake_urlopen(request, timeout):
            return _FakeResponse(
                _getrecord("2006.10956"),
                url="https://evil.example.com/oai?x=1",
            )

        with (
            patch("tools.oai_license.urllib.request.urlopen", _fake_urlopen),
            pytest.raises(RuntimeError, match="redirected off"),
        ):
            oai_license._fetch_record(url, user_agent="ua")

    def test_oversized_content_length_refused(self):
        url = f"{OAI_PMH_ENDPOINT}?verb=GetRecord"
        over = oai_license.OAI_PMH_MAX_RESPONSE_BYTES + 1

        def _fake_urlopen(request, timeout):
            return _FakeResponse(
                b"x", url, headers={"Content-Length": str(over)},
            )

        with (
            patch("tools.oai_license.urllib.request.urlopen", _fake_urlopen),
            pytest.raises(RuntimeError, match="Threat 7"),
        ):
            oai_license._fetch_record(url, user_agent="ua")


def test_oai_license_record_shape():
    """Guard the result dataclass fields the backfill depends on."""
    rec = OaiLicenseRecord(
        work_id="x", found=True, deleted=False, license_uri=None,
    )
    assert rec.datestamp == ""  # defaulted
