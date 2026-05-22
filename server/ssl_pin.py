"""arxiv.org CA-pinning SSL context factory (E13_S07c).

Wires :attr:`server.config.Config.pin_arxiv_ca` into an
:class:`ssl.SSLContext` consumer for the two arxiv-rooted fetch
sites — ``ingest/ar5iv_fetch.py::try_cache`` and
``tools/arxiv_fetch.py::fetch_eprint``. Closes Threat 7 mitigation #2
("Pin known fingerprint of arxiv.org's certificate authority chain
(rotated periodically)") from
``.claude/notes/08-security-observability-ops.md``.

**Scope.** arxiv.org + ar5iv.labs.arxiv.org ONLY. The pin does NOT
apply to ``api.openalex.org``, ``inspirehep.net``, or
``oaipmh.arxiv.org`` — those use the default system trust store via
their own host-specific fetch sites.

**Bundle.** The vendored bundle at ``infra/ca/arxiv-ca-bundle.pem``
ships ISRG Root X1 only — the Let's Encrypt root that arxiv.org and
ar5iv.labs.arxiv.org chain to. Let's Encrypt leaf certs rotate every
60-90 days but the root rotates rarely (X1 is valid until 2035-06-04).
Pinning the root therefore survives intermediate rotations and
requires bundle refresh only when ISRG itself rotates roots.

**Fail-closed.** The bundle-path resolution + existence check fires
in :func:`server.config.Config.validate_arxiv_ca_bundle` at
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
    from server.config import Config


#: The vendored bundle's canonical location. ``server/ssl_pin.py`` →
#: ``parents[1]`` is the repo root; resolve absolutely so callers in
#: any cwd see the same path.
VENDORED_ARXIV_CA_BUNDLE: Path = (
    Path(__file__).resolve().parents[1]
    / "infra"
    / "ca"
    / "arxiv-ca-bundle.pem"
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


__all__ = [
    "VENDORED_ARXIV_CA_BUNDLE",
    "build_arxiv_ssl_context",
    "resolve_arxiv_ca_bundle",
]
