"""arxiv.org CA-pinning SSL context factory (E13_S07c).

Wires :attr:`arxmcp.server.config.Config.pin_arxiv_ca` into an
:class:`ssl.SSLContext` consumer for the two arxiv-rooted fetch
sites — ``src/arxmcp/ingest/ar5iv_fetch.py::try_cache`` and
``src/arxmcp/ingest/arxiv_fetch.py::fetch_eprint``. Every production caller of
those two functions passes :func:`arxiv_ssl_context_from_env`. Closes Threat 7 mitigation #2
("Pin known fingerprint of arxiv.org's certificate authority chain
(rotated periodically)").

**Scope.** arxiv.org + ar5iv.labs.arxiv.org ONLY. The pin does NOT
apply to ``api.openalex.org``, ``inspirehep.net``, or
``oaipmh.arxiv.org`` — those use the default system trust store via
their own host-specific fetch sites.

**Bundle.** The vendored bundle at ``src/arxmcp/server/ca/arxiv-ca-bundle.pem``
ships ISRG Root X1 only — the Let's Encrypt root that arxiv.org and
ar5iv.labs.arxiv.org chain to. Let's Encrypt leaf certs rotate every
60-90 days but the root rotates rarely (X1 is valid until 2035-06-04).
Pinning the root therefore survives intermediate rotations and
requires bundle refresh only when ISRG itself rotates roots.

**Fail-closed.** The bundle-path resolution + existence check fires
in :func:`arxmcp.server.config.Config.validate_arxiv_ca_bundle` at
Config-load time (BEFORE uvicorn binds). This module re-raises
``RuntimeError`` if invoked in an inconsistent state (e.g. the
bundle file was deleted between Config load and fetch time) so the
caller cannot accidentally degrade to the system trust store.

**Banned-pattern compliance.** Uses
``ssl.create_default_context(cafile=...)`` exclusively, which sets
hostname verification ON and peer-cert verification to required by
default. Does NOT trigger any of the patterns banned by the
``TestTlsCannotBeDisabled`` / ``TestNoVerifyFalse`` production-code
walks (those tests reject any code that weakens hostname checking,
disables cert verification, or constructs an unverified SSL
context — see ``tests/security/test_source_ingest.py`` for the
authoritative regex list).
"""

from __future__ import annotations

import ssl
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arxmcp.server.config import Config


#: The vendored bundle's canonical location. It sits inside the
#: ``server`` package and ships as package data, so the same path
#: resolves in a source checkout and in an installed wheel. Resolved
#: absolutely so callers in any cwd see the same path.
VENDORED_ARXIV_CA_BUNDLE: Path = (
    Path(__file__).resolve().parent / "ca" / "arxiv-ca-bundle.pem"
)


def resolve_arxiv_ca_bundle(config: Config) -> Path:
    """Resolve the CA bundle path from Config.

    Returns :attr:`Config.arxiv_ca_bundle_path` if set (operator
    override), else :data:`VENDORED_ARXIV_CA_BUNDLE`. Raises
    :class:`RuntimeError` if the resolved path is not a regular
    file — this is the runtime defense-in-depth that complements
    :meth:`Config.validate_arxiv_ca_bundle`'s startup check (the
    bundle could have been deleted between Config load and first
    fetch).
    """
    resolved = config.arxiv_ca_bundle_path or VENDORED_ARXIV_CA_BUNDLE
    if not resolved.is_file():
        # ``assert`` is banned for invariants (CLAUDE.md §4.7;
        # Python -O strips). Use explicit raise.
        raise RuntimeError(
            f"arxiv CA bundle not found at {resolved!s}. "
            f"This is the Config-validator's job to catch at startup; "
            f"if you are seeing this at fetch time, the bundle was "
            f"deleted post-Config-load. Run `make refresh-arxiv-ca` "
            f"to restore it, then restart the server."
        )
    return resolved


def build_arxiv_ssl_context(config: Config) -> ssl.SSLContext | None:
    """Build an SSLContext for arxiv-rooted fetches.

    Returns ``None`` when :attr:`Config.pin_arxiv_ca` is ``False``
    (the safe-by-default flag-off posture; callers pass
    ``context=None`` to ``urllib.request.urlopen`` which uses the
    system trust store).

    Returns a fully-configured :class:`ssl.SSLContext` when
    ``pin_arxiv_ca=True``: built via
    ``ssl.create_default_context(cafile=<bundle>)`` so
    ``check_hostname=True`` and ``verify_mode=CERT_REQUIRED`` are
    preserved at their secure defaults. The CA store is replaced
    (not augmented) — the pinned bundle is the ONLY trust anchor,
    which means a system trust-store compromise (rogue/malicious CA)
    cannot forge an arxiv.org certificate that this context accepts.

    The function is pure (no globals, no caching). Callers MAY
    cache the returned context for the process lifetime —
    :class:`ssl.SSLContext` instances are thread-safe for use across
    concurrent connections.
    """
    if not config.pin_arxiv_ca:
        return None
    bundle = resolve_arxiv_ca_bundle(config)
    return ssl.create_default_context(cafile=str(bundle))


def arxiv_ssl_context_from_env() -> ssl.SSLContext | None:
    """Build the arxiv SSLContext from the process's ``ARXMCP_*`` env.

    The entry point for fetch callers that run outside the server
    process (bulk ingest, the seed and notebook fetch tools) and so
    hold no :class:`~arxmcp.server.config.Config` of their own. Loads a fresh
    ``Config()``, which applies the same fail-closed bundle validation
    as server startup, and hands it to :func:`build_arxiv_ssl_context`:
    ``None`` when the pin is off, the pinned context when it is on.
    A missing or unparseable bundle raises rather than degrading to
    the system trust store.
    """
    from arxmcp.server.config import (
        Config,  # noqa: PLC0415 — arxmcp.server.config imports this module
    )

    return build_arxiv_ssl_context(Config())


__all__ = [
    "VENDORED_ARXIV_CA_BUNDLE",
    "arxiv_ssl_context_from_env",
    "build_arxiv_ssl_context",
    "resolve_arxiv_ca_bundle",
]
