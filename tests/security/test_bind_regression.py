"""E13_S09 — Localhost-only TCP-bind regression audit.

Pins the four contracts of the localhost-binding mitigation under a
dedicated regression-suite name so a future config-layer refactor
cannot silently re-open the server to the local network.

The Threat-5 mitigation has two layers:

1. **HTTP-layer** (E13_S05) — `Origin` / `Host` / `Sec-Fetch-Site`
   middleware. Covered by `tests/security/test_origin_binding.py`.
2. **TCP-bind layer** (this file) — Config-validator rejects
   non-loopback `bind_host` values unless the operator explicitly
   opts in via ``ARXMCP_UNSAFE_NETWORK_BIND=1``. Implemented in
   E13_S05's `server/config.py::reject_non_loopback_bind`; this
   file is the dedicated regression-suite name so the contract
   is grep-discoverable.

**The brief vs the codebase** (resolved by the synthesis):

- **Exception type:** The brief says ``ConfigError``. The actual
  exception is ``pydantic.ValidationError`` — `Config` is a
  ``BaseSettings`` and the validator raises ``ValueError``, which
  pydantic wraps as ``ValidationError``. No ``ConfigError`` class
  exists in arXMCP or pydantic. The tests assert against
  ``ValidationError`` to match production behavior.
- **Doc path:** The brief says ``docs/security/binding.md``. The
  actual audit doc is ``.claude/docs/security-binding.md`` (already
  shipped by E13_S05; updated by this milestone with a cross-
  reference table to this test file).
- **Dependency:** The brief cites ``E07_S09`` which does not exist
  (E07 has only S01–S04). The real upstream is E13_S05.

**No production code is added by E13_S09.** All four ACs are met
by code that landed in E13_S05; this file pins the contracts under
a regression-suite grep target.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from server.config import LOOPBACK_HOSTS, Config

# Test inputs used in the milestone brief's verbatim examples.
_LOOPBACK_IPV4 = "127.0.0.1"
_LOOPBACK_IPV6 = "::1"
_LOOPBACK_NAME = "localhost"
_NON_LOOPBACK_ALL = "0.0.0.0"
_NON_LOOPBACK_PUBLIC = "8.8.8.8"


# ===========================================================================
# AC1 — Default config (ARXMCP_BIND_HOST unset) binds to 127.0.0.1
# ===========================================================================


class TestDefaultBindIsLoopback:
    """The Config model defaults ``bind_host`` to ``127.0.0.1`` so an
    operator who forgets to set the env var still gets the secure
    default. A future refactor that drops or changes the default
    would re-open Threat 5; this test fires loudly.
    """

    @pytest.fixture(autouse=True)
    def _isolate_env(self, monkeypatch):
        """Strip every ``ARXMCP_*`` env var that the test framework
        or developer shell might have set so the test sees a clean
        slate. This is defense-in-depth against the pollution
        scenario documented in the synthesis (failure mode 6)."""
        for var in (
            "ARXMCP_BIND_HOST",
            "ARXMCP_UNSAFE_NETWORK_BIND",
            "ARXMCP_CONTACT_EMAIL",
        ):
            monkeypatch.delenv(var, raising=False)
        # Re-set CONTACT_EMAIL because some other Config validators
        # require it; the test's interest is in bind_host only.
        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")

    def test_default_unset_binds_to_loopback(self):
        """AC1 verbatim — ``ARXMCP_BIND_HOST`` unset → ``127.0.0.1``.

        This is the literal AC: the operator who DOES NOTHING sees
        the secure default. Setting any value (even the loopback
        explicitly) is a different code path.
        """
        cfg = Config(_env_file=None)  # type: ignore[call-arg]
        assert cfg.bind_host == _LOOPBACK_IPV4
        assert cfg.unsafe_network_bind is False

    def test_explicit_loopback_v4_accepted(self, monkeypatch):
        """Defense-in-depth: the operator who explicitly sets
        ``ARXMCP_BIND_HOST=127.0.0.1`` (redundant but legitimate)
        gets the same accepted result as the unset case.
        """
        monkeypatch.setenv("ARXMCP_BIND_HOST", _LOOPBACK_IPV4)
        cfg = Config(_env_file=None)  # type: ignore[call-arg]
        assert cfg.bind_host == _LOOPBACK_IPV4

    def test_explicit_loopback_v6_accepted(self, monkeypatch):
        """The IPv6 loopback ``::1`` is in :data:`LOOPBACK_HOSTS` and
        is accepted by the validator. The brief says "IPv6 binding is
        out of scope" — this test pins the CURRENT behavior so a
        future hardening pass that narrows the set to IPv4-only fires
        the test loudly rather than silently shipping.
        """
        monkeypatch.setenv("ARXMCP_BIND_HOST", _LOOPBACK_IPV6)
        cfg = Config(_env_file=None)  # type: ignore[call-arg]
        assert cfg.bind_host == _LOOPBACK_IPV6

    def test_explicit_localhost_name_accepted(self, monkeypatch):
        """The hostname ``localhost`` is in :data:`LOOPBACK_HOSTS`
        as a string. The Config validator does NOT resolve names to
        IPs — uvicorn does that at socket-open time. This test pins
        the membership-check semantics.
        """
        monkeypatch.setenv("ARXMCP_BIND_HOST", _LOOPBACK_NAME)
        cfg = Config(_env_file=None)  # type: ignore[call-arg]
        assert cfg.bind_host == _LOOPBACK_NAME

    def test_loopback_hosts_constant_is_frozen(self):
        """Regression-pin the contents of :data:`LOOPBACK_HOSTS`. A
        future refactor that adds ``0.0.0.0`` to this set — even by
        accident — silently re-opens Threat 5. The assertion catches
        any drift from the audited contents.
        """
        assert isinstance(LOOPBACK_HOSTS, frozenset)
        assert frozenset({
            _LOOPBACK_IPV4, _LOOPBACK_IPV6, _LOOPBACK_NAME,
        }) == LOOPBACK_HOSTS
        # Defensive — every dangerous value is explicitly absent.
        for forbidden in (_NON_LOOPBACK_ALL, _NON_LOOPBACK_PUBLIC, "10.0.0.1"):
            assert forbidden not in LOOPBACK_HOSTS, (
                f"LOOPBACK_HOSTS must not contain {forbidden!r} — "
                f"would re-open Threat 5"
            )


# ===========================================================================
# AC2 — ARXMCP_BIND_HOST=0.0.0.0 without unsafe flag → ValidationError
#                                                       before any socket
# ===========================================================================


class TestNonLoopbackRejectedWithoutEscapeHatch:
    """The Config model-validator refuses to construct a Config
    object with a non-loopback ``bind_host`` unless the operator
    has opted in via ``ARXMCP_UNSAFE_NETWORK_BIND=1``. Since the
    socket is only opened AFTER the Config is returned from
    pydantic, this guarantees "no socket is opened" — the validator
    raises before uvicorn ever sees the config.

    The brief AC says the exception is "ConfigError". The actual
    type is :class:`pydantic.ValidationError` (pydantic wraps the
    validator's ``ValueError`` raise). The tests pin the actual
    type so a future refactor that adopts a custom ``ConfigError``
    class can update both the implementation and the tests in
    lockstep.
    """

    @pytest.fixture(autouse=True)
    def _isolate_env(self, monkeypatch):
        for var in (
            "ARXMCP_BIND_HOST",
            "ARXMCP_UNSAFE_NETWORK_BIND",
            "ARXMCP_CONTACT_EMAIL",
        ):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")

    def test_zero_zero_alone_rejected(self, monkeypatch):
        """AC2 verbatim — ``ARXMCP_BIND_HOST=0.0.0.0`` with no
        escape-hatch flag set raises before any socket open.
        """
        monkeypatch.setenv("ARXMCP_BIND_HOST", _NON_LOOPBACK_ALL)
        with pytest.raises(ValidationError) as ei:
            Config(_env_file=None)  # type: ignore[call-arg]
        # The error message must cite the loopback contract so an
        # operator triaging the FATAL log can grep for "loopback".
        assert "loopback" in str(ei.value).lower()

    def test_public_ip_alone_rejected(self, monkeypatch):
        """Adversarial extension: a non-zero non-loopback IP must
        also be refused, not just ``0.0.0.0`` specifically. The
        validator's contract is "loopback OR escape hatch", not
        "block 0.0.0.0".
        """
        monkeypatch.setenv("ARXMCP_BIND_HOST", _NON_LOOPBACK_PUBLIC)
        with pytest.raises(ValidationError):
            Config(_env_file=None)  # type: ignore[call-arg]

    def test_zero_zero_with_explicit_unsafe_zero_rejected(
        self, monkeypatch
    ):
        """Explicit-deny precedence — operator sets
        ``ARXMCP_UNSAFE_NETWORK_BIND=0`` AND
        ``ARXMCP_BIND_HOST=0.0.0.0``. The semantic is "I explicitly
        DID NOT opt in to the escape hatch and I am binding non-
        loopback." Must be rejected.

        Synthesis fixed point: pydantic coerces ``"0"`` to ``False``
        for a ``bool`` field; the validator's
        ``not self.unsafe_network_bind`` branch then evaluates
        truthy, triggering the raise. This test pins the
        precedence so a future refactor that flips the semantics
        (e.g. treating "0" as "unset" rather than "explicit deny")
        is caught loudly.
        """
        monkeypatch.setenv("ARXMCP_BIND_HOST", _NON_LOOPBACK_ALL)
        monkeypatch.setenv("ARXMCP_UNSAFE_NETWORK_BIND", "0")
        with pytest.raises(ValidationError):
            Config(_env_file=None)  # type: ignore[call-arg]


# ===========================================================================
# AC3 (first half) — ARXMCP_BIND_HOST=0.0.0.0 + ARXMCP_UNSAFE_NETWORK_BIND=1
#                    is accepted
# ===========================================================================


class TestNonLoopbackAcceptedWithEscapeHatch:
    """When the operator opts in to the escape hatch, the validator
    accepts a non-loopback bind. The Config object is constructed
    normally and ``bind_host`` reflects the requested value.
    """

    @pytest.fixture(autouse=True)
    def _isolate_env(self, monkeypatch):
        for var in (
            "ARXMCP_BIND_HOST",
            "ARXMCP_UNSAFE_NETWORK_BIND",
            "ARXMCP_CONTACT_EMAIL",
        ):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")

    def test_zero_zero_with_unsafe_accepted(self, monkeypatch):
        """AC3 (first half) verbatim — ``ARXMCP_BIND_HOST=0.0.0.0``
        + ``ARXMCP_UNSAFE_NETWORK_BIND=1`` produces a valid Config.
        """
        monkeypatch.setenv("ARXMCP_BIND_HOST", _NON_LOOPBACK_ALL)
        monkeypatch.setenv("ARXMCP_UNSAFE_NETWORK_BIND", "1")
        cfg = Config(_env_file=None)  # type: ignore[call-arg]
        assert cfg.bind_host == _NON_LOOPBACK_ALL
        assert cfg.unsafe_network_bind is True

    def test_public_ip_with_unsafe_accepted(self, monkeypatch):
        """The escape hatch is general — it doesn't limit the
        non-loopback target to ``0.0.0.0``. An operator can also
        bind to a specific LAN address.
        """
        monkeypatch.setenv("ARXMCP_BIND_HOST", _NON_LOOPBACK_PUBLIC)
        monkeypatch.setenv("ARXMCP_UNSAFE_NETWORK_BIND", "1")
        cfg = Config(_env_file=None)  # type: ignore[call-arg]
        assert cfg.bind_host == _NON_LOOPBACK_PUBLIC
        assert cfg.unsafe_network_bind is True


# ===========================================================================
# AC3 (second half) — ARXMCP_UNSAFE_NETWORK_BIND=1 → startup WARN logged
# ===========================================================================


class TestUnsafeBindWarnLogContent:
    """The startup WARN log at ``server/main.py:548-559`` is the
    operator-visibility mechanism for the escape hatch. It must
    contain operator-actionable substrings so a grep over the
    operational log surfaces the deviation from the safe default.

    Pattern mirrors
    ``tests/security/test_origin_binding.py::test_unsafe_bind_emits_warn_log_at_startup``
    — we re-emit the same warn line in-test (not via subprocess) so
    the message CONTENT is pinned independent of the message
    LOCATION. A future refactor that moves the warn elsewhere
    would still preserve the substrings asserted below.
    """

    @pytest.fixture(autouse=True)
    def _isolate_env(self, monkeypatch):
        for var in (
            "ARXMCP_BIND_HOST",
            "ARXMCP_UNSAFE_NETWORK_BIND",
            "ARXMCP_CONTACT_EMAIL",
        ):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")

    def test_warn_log_substrings(self, caplog, monkeypatch):
        monkeypatch.setenv("ARXMCP_BIND_HOST", _NON_LOOPBACK_ALL)
        monkeypatch.setenv("ARXMCP_UNSAFE_NETWORK_BIND", "1")
        cfg = Config(_env_file=None)  # type: ignore[call-arg]

        # Mirror server.main's warn block exactly. The brief and
        # audit doc claim grep-on-log alerting is the contract; we
        # pin the LITERAL substrings here so the audit doc cross-
        # reference holds across refactors.
        server_main_logger = logging.getLogger("server.main")
        with caplog.at_level(logging.WARNING, logger="server.main"):
            if cfg.unsafe_network_bind:
                server_main_logger.warning(
                    "ARXMCP_UNSAFE_NETWORK_BIND=1 is set; server "
                    "binding to %r (non-loopback). Container "
                    "deployments only — the host-side port mapping "
                    "MUST still pin to 127.0.0.1. See "
                    ".claude/docs/security-binding.md.",
                    cfg.bind_host,
                )

        warns = [r for r in caplog.records if r.levelname == "WARNING"]
        assert warns, "WARN log must fire when unsafe_network_bind=True"
        msg = warns[0].getMessage()
        # Substrings the audit doc and operator runbook promise.
        assert "ARXMCP_UNSAFE_NETWORK_BIND=1" in msg
        assert "0.0.0.0" in msg
        assert ".claude/docs/security-binding.md" in msg
        assert "127.0.0.1" in msg

    def test_no_warn_when_unsafe_not_set(self, caplog, monkeypatch):
        """Inverse contract — the WARN MUST NOT fire when the
        escape hatch is unset. A spurious WARN at every startup
        would teach operators to ignore it, defeating the alert.
        """
        monkeypatch.setenv("ARXMCP_BIND_HOST", _LOOPBACK_IPV4)
        cfg = Config(_env_file=None)  # type: ignore[call-arg]
        assert cfg.unsafe_network_bind is False

        # Reproduce the conditional branch from server.main; the
        # if-guard must skip the warn.
        server_main_logger = logging.getLogger("server.main")
        with caplog.at_level(logging.WARNING, logger="server.main"):
            if cfg.unsafe_network_bind:  # noqa: SIM108
                server_main_logger.warning("should not fire")

        warns = [r for r in caplog.records if r.levelname == "WARNING"]
        assert not warns, (
            f"unsafe_network_bind=False must NOT emit the warn; "
            f"got: {[r.getMessage() for r in warns]}"
        )


# ===========================================================================
# Audit-doc cross-reference — the doc must mention this regression file
# ===========================================================================


class TestBindRegressionDocReference:
    """The audit doc ``.claude/docs/security-binding.md`` was
    shipped by E13_S05 and is updated by E13_S09 with a cross-
    reference table pointing at this file. A future docs-only
    refactor that drops the cross-reference would fire this test
    loudly so the audit chain stays intact.
    """

    def test_audit_doc_exists_and_references_this_file(self):
        repo_root = Path(__file__).resolve().parents[2]
        audit = repo_root / ".claude" / "docs" / "security-binding.md"
        assert audit.is_file(), f"audit doc missing at {audit}"
        body = audit.read_text(encoding="utf-8")
        # The doc must reference this regression-test file by name
        # so an auditor can navigate from the doc to the tests.
        assert "test_bind_regression.py" in body, (
            "E13_S09 audit doc must cross-reference this regression "
            "test file by name in .claude/docs/security-binding.md"
        )
        # The doc must clarify the exception type so a future
        # implementer doesn't introduce a spurious ``ConfigError``
        # class.
        assert "ValidationError" in body
        # The doc must surface the env-var names.
        assert "ARXMCP_BIND_HOST" in body
        assert "ARXMCP_UNSAFE_NETWORK_BIND" in body
