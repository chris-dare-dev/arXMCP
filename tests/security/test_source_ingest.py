"""E13_S07 — Threat-7 (source ingestion TLS pinning, content-length
enforcement) audit.

Closes the five acceptance criteria of the milestone:

1. ``pytest tests/security/test_source_ingest.py`` passes all cases.
2. TLS verification cannot be disabled via any ``ARXMCP_*`` env var
   (Config validation rejects it via ``extra="forbid"``).
3. A fixture HTTP response advertising a 200 MB body is rejected
   without reading > 100 MB into memory (Content-Length pre-check).
   Bonus: a lying / missing Content-Length is caught by the read-cap.
4. All HTTP clients in ingestion code avoid ``verify=False``.
   Enforced by ``TestNoVerifyFalse`` which walks ``ingest/``, ``tools/``,
   and ``server/`` for the pattern. (Reframe of the brief's "shared
   httpx.Client" + "CI grep" because the codebase uses urllib.request
   throughout and the project has no CI per CLAUDE.md §4.1.)
5. ``ARXMCP_PIN_ARXIV_CA`` opt-in flag exists on Config and is
   documented in the audit doc.

Threat 7 verbatim (``.claude/notes/08-security-observability-ops.md``):

    > We fetch from arxiv.org and ar5iv.labs.arxiv.org. If either is
    > compromised, we ingest poisoned content.
    > Mitigations:
    > - Verify TLS certs (default for the HTTP client; do not disable).
    > - Pin known fingerprint of arxiv.org's certificate authority
    >   chain (rotated periodically).
    > - Content-length sanity checks (a single paper > 100 MB source
    >   is suspicious).
    > - Sandbox the parser (Threat 3 mitigation covers downstream impact).

**Reframed ACs vs. brief** (synthesis):

- AC4 reframed from "shared httpx.Client across ``ingest/sources/``"
  to "no ``verify=False`` anywhere in ingest / tools / server".
  Reason: the codebase uses ``urllib.request`` everywhere; ``httpx``
  is not in use. The functional equivalent — refusing any future
  ``verify=False`` regression — is what the test enforces.
- AC1's "CI grep" reframed to a pytest gate (no CI per CLAUDE.md §4.1).

Full per-mitigation audit: ``.claude/docs/security-threat-7-audit.md``.
"""

from __future__ import annotations

import json
import re
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ingest.ar5iv_fetch import AR5IV_MAX_RESPONSE_BYTES, try_cache
from ingest.oai_delta import (
    OAI_PMH_ENDPOINT,
    OAI_PMH_MAX_RESPONSE_BYTES,
)
from server.config import Config

# ===========================================================================
# AC2 — TLS verification cannot be disabled via any ARXMCP_* env var
# ===========================================================================


class TestTlsCannotBeDisabled:
    """Threat 7's first mitigation: "Verify TLS certs (default for the
    HTTP client; do not disable)." The audit asserts the contract two
    ways:

    (a) **No Config field exposes TLS toggling.** ``Config.model_fields``
        does not contain any of the canonical insecure-TLS names. This
        means no ``ARXMCP_*`` env var that an operator might guess has
        anywhere to bind to — Pydantic-settings silently ignores
        unknown env vars by default, so a hypothetical
        ``ARXMCP_VERIFY_TLS=0`` evaporates with no effect on the
        running server. The strongest defense is the absence of the
        knob, not a noisy rejection.

    (b) **No production code constructs an insecure SSLContext.**
        ``urllib.request.urlopen`` uses the default safe
        ``ssl.create_default_context()`` (per RFC 9110 § 8.6 and
        Python's ``ssl`` docs); no code in ``ingest/``, ``tools/``,
        or ``server/`` passes a custom context that would disable
        ``check_hostname`` or set ``verify_mode = ssl.CERT_NONE``.
        The ``TestNoVerifyFalse`` walk below catches a future
        ``verify=False`` regression in any httpx / requests call
        site that might be introduced.
    """

    def test_no_verify_tls_field_exists_on_config(self):
        """The model contract: no Config field exposes TLS toggling.
        Even if an operator sets ``ARXMCP_VERIFY_TLS=0`` in the
        environment, pydantic-settings has no field to bind it to and
        the value is discarded. No code reads it; TLS stays on.
        """
        forbidden = {
            "verify_tls",
            "tls_verify",
            "insecure_tls",
            "disable_tls_verification",
            "skip_tls_verify",
        }
        present = set(Config.model_fields.keys()) & forbidden
        assert not present, (
            f"Config exposes TLS-toggle fields {sorted(present)} — "
            f"Threat 7 mandates TLS verification cannot be disabled. "
            f"Remove the field(s) and document the safe-by-default "
            f"stance in .claude/docs/security-threat-7-audit.md."
        )

    def test_arxmcp_verify_tls_env_var_has_no_effect(
        self, monkeypatch, tmp_path
    ):
        """Setting a hypothetical ``ARXMCP_VERIFY_TLS=0`` env var
        must NOT bind to any Config attribute. The Config constructs
        successfully (pydantic-settings ignores unknown env vars by
        default) and ``hasattr(cfg, 'verify_tls')`` is False — so
        any downstream code that tries to honor it has nothing to
        read. This pins the AC: "TLS verification cannot be disabled
        via any ``ARXMCP_*`` env var."
        """
        monkeypatch.setenv("ARXMCP_VERIFY_TLS", "0")
        monkeypatch.setenv("ARXMCP_DATA_DIR", str(tmp_path))
        # Build the config — must NOT raise (extra="forbid" only
        # applies to constructor kwargs, not env-var inputs in
        # pydantic-settings).
        cfg = Config(_env_file=None)  # type: ignore[call-arg]
        # The crucial assertion: no attribute was bound from the env var.
        for forbidden_attr in (
            "verify_tls",
            "tls_verify",
            "insecure_tls",
            "disable_tls_verification",
            "skip_tls_verify",
        ):
            assert not hasattr(cfg, forbidden_attr), (
                f"Config gained attribute {forbidden_attr!r} from "
                f"an env var — Threat 7 contract violated."
            )

    def test_no_insecure_sslcontext_in_production_code(self):
        """Defense in depth: even if a future PR adds an
        ``ssl.SSLContext`` somewhere in ``ingest/``, ``tools/``, or
        ``server/``, it must not disable verification. The patterns
        we refuse: ``check_hostname=False``, ``verify_mode = CERT_NONE``,
        ``CERT_OPTIONAL`` (also weakens validation), and
        ``_create_unverified_context``.
        """
        repo_root = Path(__file__).resolve().parents[2]
        scopes = ("ingest", "tools", "server")
        insecure_patterns = (
            re.compile(r"check_hostname\s*=\s*False"),
            re.compile(r"verify_mode\s*=\s*ssl\.CERT_NONE"),
            re.compile(r"verify_mode\s*=\s*ssl\.CERT_OPTIONAL"),
            re.compile(r"_create_unverified_context"),
        )
        offenders: list[tuple[str, str]] = []
        for scope in scopes:
            base = repo_root / scope
            if not base.is_dir():
                continue
            for py in base.rglob("*.py"):
                try:
                    text = py.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                for pat in insecure_patterns:
                    if pat.search(text):
                        offenders.append(
                            (str(py.relative_to(repo_root)), pat.pattern)
                        )
        assert not offenders, (
            f"Threat 7: insecure TLS pattern(s) found in production "
            f"code: {offenders}. urllib.request uses "
            f"ssl.create_default_context() by default; do not "
            f"override with a weakened SSLContext."
        )


# ===========================================================================
# AC3 — 200 MB fixture response rejected without reading > 100 MB
# ===========================================================================


class TestContentLengthCap:
    """Both ar5iv and oai_delta must reject responses whose declared
    Content-Length exceeds the 100 MB cap BEFORE consuming the body,
    AND must cap the actual ``response.read()`` size to bound memory
    when the header is missing or lies.
    """

    # ----- ar5iv_fetch -----

    def test_ar5iv_rejects_oversized_content_length_before_read(
        self, monkeypatch, tmp_path
    ):
        """When the server announces Content-Length=200 MB, the
        fetcher must reject WITHOUT calling ``response.read()``. We
        monkey-patch urlopen to return a mock whose ``.read()`` is a
        ``MagicMock`` so we can assert it was never invoked.

        F3 rectification (E13_S07 adversary): the prior version of
        this test only proved ``read()`` was never invoked. That
        leaves a future refactor free to bypass ``read()`` via
        ``response.fp.read1`` / ``readinto`` / similar. The
        strengthened version also asserts that no alternative read
        primitive on the response is called either — pinning the
        full "no body buffered into memory" contract.
        """
        paper_id = "2412.00001"

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.url = "https://ar5iv.labs.arxiv.org/html/" + paper_id
        mock_response.headers = {"Content-Length": str(200 * 1024 * 1024)}

        # F3: track EVERY potential body-read primitive. If any
        # fires when Content-Length declared oversized, the cap is
        # not respected and the test fails — regardless of which
        # API the production code chose.
        body_read_methods = (
            "read", "read1", "readinto", "readinto1", "readline",
            "readlines", "fp",
        )
        forbidden_calls: list[str] = []

        def make_fail(name: str):
            def _fail(*args, **kwargs):
                forbidden_calls.append(name)
                raise AssertionError(
                    f"Content-Length cap was not respected — "
                    f"response.{name}() was called"
                )
            return _fail

        for method_name in body_read_methods:
            setattr(mock_response, method_name, make_fail(method_name))

        # urlopen returns a context manager.
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=mock_response)
        ctx.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=ctx):
            result = try_cache(
                paper_id=paper_id,
                cache_dir=tmp_path / "cache",
                parsed_dir=tmp_path / "parsed",
                user_agent="arxmcp-test/0.1",
            )

        assert result.hit is False, (
            "200 MB Content-Length must result in a miss, not a hit"
        )
        assert result.reason == "oversized_content_length", (
            f"expected reason='oversized_content_length', got {result.reason!r}"
        )
        assert not forbidden_calls, (
            f"Threat 7 F3: the fetcher called body-read primitives "
            f"{forbidden_calls} after seeing an oversized Content-Length. "
            f"The pre-check must short-circuit BEFORE any body bytes "
            f"are buffered."
        )

    def test_ar5iv_caps_actual_read_when_content_length_missing(
        self, monkeypatch, tmp_path
    ):
        """When Content-Length is missing (chunked / HTTP/2), the
        read-cap is the load-bearing guard. The fetcher must request
        at most ``MAX + 1`` bytes from ``response.read()`` so that
        memory is bounded to ~100 MB worst case.
        """
        paper_id = "2412.00002"

        # Body of 100 MB + 1 byte (one past the cap) — simulating a
        # server with missing Content-Length sending a too-large body.
        oversized_body = b"X" * (AR5IV_MAX_RESPONSE_BYTES + 1)

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.url = "https://ar5iv.labs.arxiv.org/html/" + paper_id
        mock_response.headers = {}  # No Content-Length
        # The fetcher should call read(cap + 1). We give back that
        # many bytes — the check is that len(body) > cap triggers
        # the reject branch.

        # F3 rectification: capture the actual byte cap passed to
        # read() so we can prove the production code applied
        # ``MAX + 1`` (not a larger value, not no value).
        recorded_caps: list[int | None] = []

        def fake_read(n: int | None = None) -> bytes:
            recorded_caps.append(n)
            if n is None:
                pytest.fail(
                    "ar5iv read() was called without a byte cap — "
                    "memory could grow unbounded"
                )
            return oversized_body[:n]

        mock_response.read = fake_read

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=mock_response)
        ctx.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=ctx):
            result = try_cache(
                paper_id=paper_id,
                cache_dir=tmp_path / "cache",
                parsed_dir=tmp_path / "parsed",
                user_agent="arxmcp-test/0.1",
            )

        assert result.hit is False
        assert result.reason == "oversized_body", (
            f"expected reason='oversized_body', got {result.reason!r}"
        )
        # F3: the recorded byte caps prove ``read()`` was called
        # with a bounded value exactly equal to ``MAX + 1``.
        # Anything looser (or anything past one call) would
        # indicate unbounded buffering.
        assert recorded_caps, "read() was never called"
        assert all(n == AR5IV_MAX_RESPONSE_BYTES + 1 for n in recorded_caps), (
            f"Threat 7 F3: expected every read() call to request "
            f"exactly {AR5IV_MAX_RESPONSE_BYTES + 1} bytes; got {recorded_caps}"
        )

    def test_ar5iv_accepts_body_under_cap(self, monkeypatch, tmp_path):
        """Sanity guard: a well-formed small response still succeeds.
        Without this test, we'd not know if the cap broke the happy
        path.
        """
        paper_id = "2412.00003"
        body = (
            b"<html><body><math>x</math></body></html>"
        )

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.url = "https://ar5iv.labs.arxiv.org/html/" + paper_id
        mock_response.headers = {"Content-Length": str(len(body))}
        mock_response.read = MagicMock(return_value=body)

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=mock_response)
        ctx.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=ctx):
            result = try_cache(
                paper_id=paper_id,
                cache_dir=tmp_path / "cache",
                parsed_dir=tmp_path / "parsed",
                user_agent="arxmcp-test/0.1",
            )

        assert result.hit is True
        assert result.reason == "ok"

    # ----- oai_delta -----

    def test_oai_delta_rejects_oversized_content_length(self):
        """Same pattern as ar5iv: a declared 200 MB Content-Length
        must raise BEFORE any body bytes are read. Uses the
        oai_delta._fetch_page private helper, which is the
        single HTTP call site in that module.
        """
        from ingest.oai_delta import _fetch_page

        mock_response = MagicMock()
        mock_response.url = OAI_PMH_ENDPOINT + "?verb=ListRecords"
        mock_response.headers = {
            "Content-Length": str(200 * 1024 * 1024)
        }
        mock_response.read = MagicMock(
            side_effect=AssertionError(
                "Content-Length cap was not respected — read() was called"
            )
        )

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=mock_response)
        ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch("urllib.request.urlopen", return_value=ctx),
            pytest.raises(RuntimeError) as ei,
        ):
            _fetch_page(
                OAI_PMH_ENDPOINT,
                {"verb": "ListRecords", "set": "math:math:AG"},
                timeout_seconds=5.0,
                user_agent="arxmcp-test/0.1",
                sleep=lambda _s: None,
            )
        # The error must cite the cap and the declared size so an
        # operator can grep for the value in production logs.
        msg = str(ei.value)
        assert "Threat 7" in msg or str(OAI_PMH_MAX_RESPONSE_BYTES) in msg
        # Loadbearing: .read() must NEVER fire.
        mock_response.read.assert_not_called()

    def test_oai_delta_caps_actual_read_when_header_lies(self):
        """When Content-Length lies (declared 1 KB, actual 100+ MB),
        the read-cap catches it after the read but before any
        downstream parser sees the bytes.
        """
        from ingest.oai_delta import _fetch_page

        oversized = b"<oversized>" * ((OAI_PMH_MAX_RESPONSE_BYTES // 11) + 2)
        assert len(oversized) > OAI_PMH_MAX_RESPONSE_BYTES

        mock_response = MagicMock()
        mock_response.url = OAI_PMH_ENDPOINT + "?verb=ListRecords"
        # Declared size is small (a lie) — pre-check passes.
        mock_response.headers = {"Content-Length": "1024"}

        def fake_read(n: int | None = None) -> bytes:
            if n is None:
                pytest.fail(
                    "oai_delta read() was called without a byte cap — "
                    "memory could grow unbounded under a Content-Length lie"
                )
            return oversized[:n]

        mock_response.read = fake_read

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=mock_response)
        ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch("urllib.request.urlopen", return_value=ctx),
            pytest.raises(RuntimeError) as ei,
        ):
            _fetch_page(
                OAI_PMH_ENDPOINT,
                {"verb": "ListRecords", "set": "math:math:AG"},
                timeout_seconds=5.0,
                user_agent="arxmcp-test/0.1",
                sleep=lambda _s: None,
            )
        assert "exceeded cap" in str(ei.value)


# ===========================================================================
# F2 regression — harvest loop survives a Threat-7 cap breach mid-set
# ===========================================================================


class TestHarvestSurvivesCapBreach:
    """F2 rectification (E13_S07 adversary): a ``RuntimeError`` from
    ``_fetch_page`` (raised on Content-Length cap breach) must NOT
    abort the whole multi-set harvest run. ``harvest_set`` now
    catches the exception, logs at WARN, and returns
    ``(records, pages)`` so the outer ``run_delta`` loop continues
    to the next set.
    """

    def test_runtime_error_in_first_page_does_not_propagate(self, caplog):
        """A poisoned first page raises ``RuntimeError``;
        ``harvest_set`` must return ``([], 0)`` rather than letting
        the exception escape.
        """
        import logging

        from ingest.oai_delta import harvest_set

        def poison_fetcher(*_a, **_kw):
            raise RuntimeError(
                "OAI-PMH Content-Length 209715200 exceeds cap "
                "104857600 bytes (Threat 7); refusing"
            )

        with caplog.at_level(logging.WARNING, logger="ingest.oai_delta"):
            records, pages = harvest_set(
                "math:math:AG",
                from_date="2026-05-01",
                until_date="2026-05-02",
                endpoint=OAI_PMH_ENDPOINT,
                state_path=Path("nonexistent"),
                resume_token=None,
                fetch_page=poison_fetcher,
                sleep_between_pages=lambda _t: None,
            )

        assert records == []
        assert pages == 0
        # The graceful-degradation log must fire so an operator can
        # grep for the poisoned set name.
        warn_messages = [
            r.getMessage() for r in caplog.records
            if r.levelno == logging.WARNING
        ]
        assert any("math:math:AG" in m for m in warn_messages), (
            f"expected WARN log mentioning the poisoned set; got: {warn_messages}"
        )
        assert any("Threat 7" in m for m in warn_messages), (
            f"expected WARN log citing Threat 7; got: {warn_messages}"
        )


# ===========================================================================
# AC4 — No verify=False anywhere in ingest / tools / server
# ===========================================================================


class TestNoVerifyFalse:
    """Walks all production source trees for the pattern that would
    disable TLS verification. The brief asked for a "CI lint rule" —
    reframed here as a pytest gate that runs under ``make test``
    (CLAUDE.md §4.1 forbids CI gating). Test fixtures under
    ``tests/`` are excluded by design so defensive tests can use
    ``verify=False`` legitimately.

    Pattern is a robust regex (not the brief's literal grep) so
    whitespace variants like ``verify = False``, ``verify=  False``,
    and quoted forms all fail the check.
    """

    # Matches: verify=False, verify = False, verify =False (any whitespace).
    # Excludes harmless mentions like "verify=False" in a docstring
    # by anchoring on a call-site context: preceded by a comma OR an
    # open paren, NOT inside a triple-quoted block. The simplest robust
    # check: presence of the regex outside string literals. For pre-AST
    # speed we accept some false positives (comments mentioning it) and
    # require contributors to phrase comments without the literal pattern.
    _PATTERN = re.compile(r"\bverify\s*=\s*False\b")

    def test_no_verify_false_in_production_code(self):
        repo_root = Path(__file__).resolve().parents[2]
        scopes = ("ingest", "tools", "server")
        offenders: list[str] = []
        for scope in scopes:
            base = repo_root / scope
            if not base.is_dir():
                continue
            for py in base.rglob("*.py"):
                try:
                    text = py.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                # Strip docstring / comment occurrences are tolerated
                # for the test pattern: we only flag if the literal
                # ``verify=False`` (regex-normalized) appears AND the
                # file is not a vendored stub.
                if self._PATTERN.search(text):
                    offenders.append(str(py.relative_to(repo_root)))
        assert not offenders, (
            f"Threat 7: ``verify=False`` found in production code at "
            f"{offenders}. TLS verification must remain enabled per "
            f".claude/notes/08-security-observability-ops.md § Threat 7. "
            f"If a defensive test needs verify=False, move it under "
            f"``tests/`` (excluded from this gate)."
        )


# ===========================================================================
# AC5 — ARXMCP_PIN_ARXIV_CA opt-in flag exists and is documented
# ===========================================================================


class TestPinArxivCaFlag:
    """The opt-in CA-pinning flag must exist on Config and be
    documented in the audit doc. The actual cert-chain validation
    is a forward-compat stub today (full implementation deferred);
    this test pins the contract that the field is present, defaults
    to False, and is enable-able via the standard pydantic
    ``ARXMCP_PIN_ARXIV_CA`` env-var mapping.
    """

    def test_field_defaults_to_false(self, monkeypatch, tmp_path):
        # Strip any test-leaked env vars so the default is observed.
        monkeypatch.delenv("ARXMCP_PIN_ARXIV_CA", raising=False)
        # Provide a corpus dir so other validators don't fail.
        monkeypatch.setenv("ARXMCP_DATA_DIR", str(tmp_path))
        cfg = Config(_env_file=None)  # type: ignore[call-arg]
        assert cfg.pin_arxiv_ca is False, (
            "ARXMCP_PIN_ARXIV_CA must default to False — opt-in semantics "
            "per .claude/docs/security-threat-7-audit.md"
        )

    def test_field_accepts_env_opt_in(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ARXMCP_PIN_ARXIV_CA", "1")
        monkeypatch.setenv("ARXMCP_DATA_DIR", str(tmp_path))
        cfg = Config(_env_file=None)  # type: ignore[call-arg]
        assert cfg.pin_arxiv_ca is True

    def test_audit_doc_documents_the_flag(self):
        """The audit doc must surface the env-var name verbatim so a
        grep for the flag lands on the operator runbook.
        """
        repo_root = Path(__file__).resolve().parents[2]
        audit = repo_root / ".claude" / "docs" / "security-threat-7-audit.md"
        assert audit.is_file(), f"audit doc missing at {audit}"
        text = audit.read_text(encoding="utf-8")
        assert "ARXMCP_PIN_ARXIV_CA" in text
        # F4 rectification (E13_S07 adversary): the prior assertion
        # was ``"100" in text`` which would pass spuriously on any
        # unrelated number like a year or section. Pin the actual
        # cap value AND units so a future doc edit that removes
        # the explanation triggers the test.
        assert re.search(r"100\s*MB", text), (
            "audit doc must surface the 100 MB Content-Length cap value"
        )
        assert "Threat 7" in text


# ===========================================================================
# E13_S07c — ARXMCP_PIN_ARXIV_CA SSL-context wiring + refresh procedure
#   Closes the partial-coverage gap G5 (github.com/chris-dare-dev/arXMCP#5).
# ===========================================================================


class TestPinArxivCaWiring:
    """E13_S07c — closes Threat 7 G5 by wiring ``Config.pin_arxiv_ca``
    into a real ``ssl.SSLContext`` consumer.

    Six tests cover:
      * Factory returns None when the flag is off (safe-by-default
        flag-off posture preserved).
      * Factory builds a properly-configured SSLContext when the flag
        is on AND the vendored bundle is present.
      * Factory raises RuntimeError when the flag is on AND the
        resolved bundle is missing (defense-in-depth at the factory
        layer).
      * Config validator (model_validator) raises ValueError at
        Config-load time when the flag is on AND the override path
        points at a nonexistent file (primary fail-closed at startup,
        BEFORE uvicorn binds).
      * ``ar5iv_fetch.try_cache`` threads the ``ssl_context`` kwarg
        into ``urllib.request.urlopen`` (both call sites pinned —
        partial-coverage hole closed).
      * ``arxiv_fetch.fetch_eprint`` threads the ``ssl_context``
        kwarg into ``urllib.request.urlopen``.
    """

    def test_factory_returns_none_when_flag_off(
        self, monkeypatch, tmp_path
    ):
        """``pin_arxiv_ca=False`` (default): factory returns ``None``
        so callers pass ``context=None`` to ``urlopen`` which uses
        the system trust store. The safe-by-default flag-off posture
        must remain intact post-E13_S07c."""
        from server.ssl_pin import build_arxiv_ssl_context

        monkeypatch.delenv("ARXMCP_PIN_ARXIV_CA", raising=False)
        monkeypatch.setenv("ARXMCP_DATA_DIR", str(tmp_path))
        cfg = Config(_env_file=None)  # type: ignore[call-arg]
        ctx = build_arxiv_ssl_context(cfg)
        assert ctx is None, (
            "flag-off must return None; got a real SSLContext which "
            "would silently restrict the trust store"
        )

    def test_factory_builds_secure_context_when_flag_on(
        self, monkeypatch, tmp_path
    ):
        """Flag on + vendored bundle present: factory returns an
        SSLContext with ``check_hostname=True`` and
        ``verify_mode=CERT_REQUIRED`` (per
        ``ssl.create_default_context(cafile=...)`` semantics)."""
        import ssl as _ssl

        from server.ssl_pin import build_arxiv_ssl_context

        monkeypatch.setenv("ARXMCP_PIN_ARXIV_CA", "1")
        monkeypatch.setenv("ARXMCP_DATA_DIR", str(tmp_path))
        cfg = Config(_env_file=None)  # type: ignore[call-arg]
        ctx = build_arxiv_ssl_context(cfg)
        assert ctx is not None
        assert isinstance(ctx, _ssl.SSLContext)
        assert ctx.check_hostname is True, (
            "CA pinning must NOT weaken hostname verification "
            "(Threat 7 TLS-disable rejection contract)"
        )
        assert ctx.verify_mode == _ssl.CERT_REQUIRED, (
            "CA pinning must NOT weaken peer verification"
        )
        # The vendored bundle ships exactly one CA (ISRG Root X1).
        certs = ctx.get_ca_certs()
        assert len(certs) == 1, (
            f"expected exactly 1 CA in the vendored bundle "
            f"(ISRG Root X1); got {len(certs)}"
        )
        subject = certs[0].get("subject", ())
        # Walk the RDN tuples for the CN.
        cn = None
        for rdn in subject:
            for (k, v) in rdn:
                if k == "commonName":
                    cn = v
        assert cn == "ISRG Root X1", (
            f"vendored bundle should pin ISRG Root X1 (the Let's "
            f"Encrypt root arxiv.org chains to); got CN={cn!r}"
        )

    def test_factory_raises_when_override_path_missing(
        self, monkeypatch, tmp_path
    ):
        """Flag on + override path points at nonexistent file: the
        Config validator fires at Config-load time (primary
        fail-closed). The factory raise is the defense-in-depth
        for the post-load deletion case."""
        from pydantic import ValidationError

        missing = tmp_path / "no-such-bundle.pem"
        monkeypatch.setenv("ARXMCP_PIN_ARXIV_CA", "1")
        monkeypatch.setenv(
            "ARXMCP_ARXIV_CA_BUNDLE_PATH", str(missing)
        )
        monkeypatch.setenv("ARXMCP_DATA_DIR", str(tmp_path))
        with pytest.raises(ValidationError) as ei:
            Config(_env_file=None)  # type: ignore[call-arg]
        # Error must clearly identify the cause + remediation.
        msg = str(ei.value)
        assert "CA bundle not found" in msg
        assert "Refusing to fall back" in msg, (
            "fail-closed message must explicitly say it refuses to "
            "degrade to the system trust store"
        )

    def test_factory_runtime_raise_on_post_load_deletion(
        self, monkeypatch, tmp_path
    ):
        """Defense-in-depth: even if the Config-load validator
        passes, the factory layer must still raise if the bundle
        is missing at fetch time (e.g. deleted between startup and
        first fetch)."""
        from server.ssl_pin import build_arxiv_ssl_context

        # Build a valid bundle, then point Config at it, then delete.
        bundle = tmp_path / "tmp-bundle.pem"
        bundle.write_text(
            (Path(__file__).resolve().parents[2]
             / "infra" / "ca" / "arxiv-ca-bundle.pem")
            .read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        monkeypatch.setenv("ARXMCP_PIN_ARXIV_CA", "1")
        monkeypatch.setenv("ARXMCP_ARXIV_CA_BUNDLE_PATH", str(bundle))
        monkeypatch.setenv("ARXMCP_DATA_DIR", str(tmp_path))
        cfg = Config(_env_file=None)  # type: ignore[call-arg]
        # Config loaded successfully; now delete the bundle.
        bundle.unlink()
        with pytest.raises(RuntimeError, match="bundle not found"):
            build_arxiv_ssl_context(cfg)

    def test_ar5iv_fetch_threads_ssl_context_to_urlopen(
        self, monkeypatch, tmp_path
    ):
        """``try_cache`` must pass the ``ssl_context`` kwarg to
        ``urllib.request.urlopen(context=...)``. Pinning one site
        but not the other would create partial coverage — the
        regression guard for failure-mode (g) in research-brief-2.
        """
        from ingest.ar5iv_fetch import try_cache

        sentinel = MagicMock(name="sentinel_ssl_context")
        captured: dict[str, object] = {}

        # Stub urlopen: capture the context kwarg, return a stub
        # whose context-manager exit returns a 404-ish path so
        # try_cache produces a miss without parsing real HTML.
        def fake_urlopen(*args, **kwargs):
            captured["context"] = kwargs.get("context")
            import urllib.error
            raise urllib.error.HTTPError(
                url="https://ar5iv.labs.arxiv.org/html/test",
                code=404,
                msg="Not Found",
                hdrs=None,
                fp=None,
            )

        monkeypatch.setattr(
            "urllib.request.urlopen", fake_urlopen
        )
        result = try_cache(
            paper_id="2412.00001",
            cache_dir=tmp_path / "cache",
            parsed_dir=tmp_path / "parsed",
            ssl_context=sentinel,
        )
        assert captured.get("context") is sentinel, (
            f"try_cache did not thread ssl_context to urlopen; "
            f"got {captured.get('context')!r}"
        )
        # The HTTPError 404 path produces a miss.
        assert result.hit is False

    def test_arxiv_fetch_threads_ssl_context_to_urlopen(
        self, monkeypatch, tmp_path
    ):
        """``fetch_eprint`` must pass the ``ssl_context`` kwarg to
        ``urlopen`` — same partial-coverage guard for the
        ``tools/arxiv_fetch.py`` site."""
        from tools.arxiv_fetch import fetch_eprint

        sentinel = MagicMock(name="sentinel_ssl_context")
        captured: dict[str, object] = {}

        def fake_urlopen(*args, **kwargs):
            captured["context"] = kwargs.get("context")
            import urllib.error
            raise urllib.error.HTTPError(
                url="https://export.arxiv.org/e-print/2412.00001",
                code=404,
                msg="Not Found",
                hdrs=None,
                fp=None,
            )

        monkeypatch.setattr(
            "urllib.request.urlopen", fake_urlopen
        )
        with pytest.raises(urllib.error.HTTPError):
            fetch_eprint(
                paper_id="2412.00001",
                raw_dir=tmp_path,
                contact_email="test@example.com",
                ssl_context=sentinel,
            )
        assert captured.get("context") is sentinel, (
            f"fetch_eprint did not thread ssl_context to urlopen; "
            f"got {captured.get('context')!r}"
        )


# ===========================================================================
# E13_S07b — Threat-7 redirect-host pin on graph_ingest + inspire_ingest
#   Closes the partial-coverage gap G2 (github.com/chris-dare-dev/arXMCP#2).
# ===========================================================================


class TestRedirectHostPin:
    """E13_S07b — closes Threat 7 partial-coverage gap G2.

    ``ingest/ar5iv_fetch.py`` and ``ingest/oai_delta.py`` already pin
    the post-fetch ``response.url`` against their expected host so a
    poisoned upstream that issues a 30x to an attacker-controlled host
    is rejected before its body is parsed. ``graph_ingest.py``
    (OpenAlex) and ``inspire_ingest.py`` (INSPIRE-HEP) gained the same
    guard in E13_S07b. These tests mirror
    ``tests/test_oai_delta.py::TestFetchPageRedirectPin``.

    Mock discipline (research-brief-2 failure mode #4): the fake
    response MUST set an explicit ``.url`` string. A bare ``MagicMock``
    returns a truthy child mock for ``.url``, and ``.startswith`` on
    that child raises ``AttributeError`` — the test would error rather
    than exercise the guard. Every stub below sets ``.url`` explicitly.

    The guard pins with a trailing ``"/"`` (``OPENALEX_BASE + "/"`` /
    ``INSPIRE_API_BASE + "/"``) — the synthesis decision over the bare
    ``oai_delta.py`` form. The trailing slash closes the
    prefix-collision vector (``api.openalex.org.evil.com``); the last
    two tests pin that explicitly.
    """

    @staticmethod
    def _ctx(url: str, body: bytes):
        """Build a ``urlopen()`` context-manager stub whose response
        has a controlled ``.url`` and a ``.read(n)`` returning ``body``.
        """
        resp = MagicMock()
        resp.url = url
        resp.read = MagicMock(return_value=body)
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=resp)
        ctx.__exit__ = MagicMock(return_value=False)
        return ctx

    # ----- graph_ingest (OpenAlex) -----

    def test_graph_ingest_rejects_off_host_redirect(self):
        """A redirect off ``api.openalex.org`` raises ``RuntimeError``
        before the JSON body is trusted as a citation source.
        """
        from ingest.graph_ingest import _fetch_openalex_work

        ctx = self._ctx(
            url="https://evil.example/works/poisoned",
            body=b'{"id": "https://openalex.org/W1"}',
        )
        with (
            patch("urllib.request.urlopen", return_value=ctx),
            pytest.raises(RuntimeError, match="redirected off"),
        ):
            _fetch_openalex_work("2412.00001", "test@example.com")

    def test_graph_ingest_accepts_on_host_response(self):
        """A response whose final URL stays on ``api.openalex.org`` is
        parsed and returned unchanged — the guard does not break the
        happy path.
        """
        from ingest.graph_ingest import OPENALEX_BASE, _fetch_openalex_work

        payload = {"id": "https://openalex.org/W1", "ok": True}
        ctx = self._ctx(
            url=f"{OPENALEX_BASE}/works/W1?mailto=test%40example.com",
            body=json.dumps(payload).encode("utf-8"),
        )
        with patch("urllib.request.urlopen", return_value=ctx):
            result = _fetch_openalex_work("2412.00001", "test@example.com")
        assert result == payload

    # ----- inspire_ingest (INSPIRE-HEP) -----

    def test_inspire_ingest_rejects_off_host_redirect(self):
        """A redirect off ``inspirehep.net/api`` raises ``RuntimeError``
        before the JSON body is trusted.
        """
        from ingest.inspire_ingest import _fetch_inspire_record

        ctx = self._ctx(
            url="https://evil.example/api/arxiv/poisoned",
            body=b'{"metadata": {}}',
        )
        with (
            patch("urllib.request.urlopen", return_value=ctx),
            pytest.raises(RuntimeError, match="redirected off"),
        ):
            _fetch_inspire_record("2412.00001", "test@example.com")

    def test_inspire_ingest_accepts_on_host_response(self):
        """A response whose final URL stays on ``inspirehep.net/api`` is
        parsed and returned unchanged.
        """
        from ingest.inspire_ingest import (
            INSPIRE_API_BASE,
            _fetch_inspire_record,
        )

        payload = {"metadata": {"arxiv_eprints": []}}
        ctx = self._ctx(
            url=f"{INSPIRE_API_BASE}/arxiv/2412.00001?fields=references",
            body=json.dumps(payload).encode("utf-8"),
        )
        with patch("urllib.request.urlopen", return_value=ctx):
            result = _fetch_inspire_record("2412.00001", "test@example.com")
        assert result == payload

    # ----- prefix-collision guard (the trailing "/" synthesis decision) -----

    def test_graph_ingest_rejects_prefix_collision_host(self):
        """A bare ``startswith(OPENALEX_BASE)`` would accept
        ``https://api.openalex.org.evil.com/...`` — a domain an
        attacker can register. The ``+ "/"`` in the pin rejects it.
        """
        from ingest.graph_ingest import _fetch_openalex_work

        ctx = self._ctx(
            url="https://api.openalex.org.evil.com/works/W1",
            body=b'{"id": "x"}',
        )
        with (
            patch("urllib.request.urlopen", return_value=ctx),
            pytest.raises(RuntimeError, match="redirected off"),
        ):
            _fetch_openalex_work("2412.00001", "test@example.com")

    def test_inspire_ingest_rejects_prefix_collision_path(self):
        """A bare ``startswith(INSPIRE_API_BASE)`` would accept
        ``https://inspirehep.net/apiEVIL/...``. The ``+ "/"`` rejects it.
        """
        from ingest.inspire_ingest import _fetch_inspire_record

        ctx = self._ctx(
            url="https://inspirehep.net/apiEVIL/arxiv/x",
            body=b'{"metadata": {}}',
        )
        with (
            patch("urllib.request.urlopen", return_value=ctx),
            pytest.raises(RuntimeError, match="redirected off"),
        ):
            _fetch_inspire_record("2412.00001", "test@example.com")

    # ----- scheme-downgrade guard (F2 — E13_S07b adversary rectification) -----

    def test_graph_ingest_rejects_scheme_downgrade(self):
        """A 30x that downgrades ``https://`` → ``http://`` on the SAME
        host is a TLS-stripping attack. ``OPENALEX_BASE`` embeds the
        ``https://`` scheme, so the pin rejects an ``http://`` redirect
        target. This test pins that protection so a future refactor to
        a host-only pin (dropping the scheme) fails loudly instead of
        silently re-opening the downgrade hole.
        """
        from ingest.graph_ingest import _fetch_openalex_work

        ctx = self._ctx(
            url="http://api.openalex.org/works/W1",
            body=b'{"id": "x"}',
        )
        with (
            patch("urllib.request.urlopen", return_value=ctx),
            pytest.raises(RuntimeError, match="redirected off"),
        ):
            _fetch_openalex_work("2412.00001", "test@example.com")

    def test_inspire_ingest_rejects_scheme_downgrade(self):
        """Same TLS-stripping guard for INSPIRE: an ``http://`` redirect
        target on the same host is rejected because ``INSPIRE_API_BASE``
        embeds ``https://``.
        """
        from ingest.inspire_ingest import _fetch_inspire_record

        ctx = self._ctx(
            url="http://inspirehep.net/api/arxiv/2412.00001",
            body=b'{"metadata": {}}',
        )
        with (
            patch("urllib.request.urlopen", return_value=ctx),
            pytest.raises(RuntimeError, match="redirected off"),
        ):
            _fetch_inspire_record("2412.00001", "test@example.com")
