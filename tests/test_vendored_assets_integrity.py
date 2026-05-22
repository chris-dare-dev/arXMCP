"""Integrity pin for vendored third-party static assets (m8 rect F6).

Pins the SHA-256 of every vendored file so a re-vendor (security
patch, version bump) MUST update both the file and the test in
lockstep. A bare tamper on the file shows in the git diff already;
a fresh re-vendor that accidentally substitutes a backdoored bundle
would still get caught by the upstream's published SRI hash, but
this test makes the verification explicit at the project level.

The recorded hashes also live in ``frontend/static/VENDORED.md`` —
both must move together on re-vendor.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FRONTEND_STATIC: Path = REPO_ROOT / "frontend" / "static"


#: SHA-256 of the vendored ``htmx.min.js`` file AS STORED ON DISK
#: (i.e. with the prepended header comment naming version + source
#: URL + 0BSD license). htmx 2.0.10, downloaded 2026-05-22 from
#: ``https://cdn.jsdelivr.net/npm/htmx.org@2.0.10/dist/htmx.min.js``.
#:
#: On re-vendor: download the upstream file, prepend the header line
#: in the exact same format, compute ``shasum -a 256
#: frontend/static/htmx.min.js``, then update BOTH this constant
#: and ``frontend/static/VENDORED.md`` in lockstep.
EXPECTED_HTMX_SHA256: str = (
    "5e6ee42df72f91d6f5ddcfd746ed157f96071a9ad68df148ead526c864d3ddc7"
)


class TestVendoredHtmxIntegrity:
    def test_htmx_file_exists(self) -> None:
        path = FRONTEND_STATIC / "htmx.min.js"
        assert path.is_file(), (
            f"vendored htmx file missing at {path} — run the "
            f"re-vendor recipe in frontend/static/VENDORED.md"
        )

    def test_htmx_sha256_matches(self) -> None:
        """Hard pin: if this fails, the vendored htmx was modified
        without updating the recorded hash. EITHER the change is
        intentional (re-vendor for a security patch / version bump
        — update EXPECTED_HTMX_SHA256 here AND VENDORED.md in the
        same commit) OR the file was tampered with (revert)."""
        path = FRONTEND_STATIC / "htmx.min.js"
        content = path.read_bytes()
        actual = hashlib.sha256(content).hexdigest()
        assert actual == EXPECTED_HTMX_SHA256, (
            f"vendored htmx SHA-256 mismatch:\n"
            f"  expected: {EXPECTED_HTMX_SHA256}\n"
            f"  actual:   {actual}\n"
            f"If this was an intentional re-vendor, update BOTH the "
            f"EXPECTED_HTMX_SHA256 constant in this file AND the "
            f"corresponding row in frontend/static/VENDORED.md."
        )

    def test_htmx_header_comment_preserved(self) -> None:
        """The vendored file MUST start with the project's version-
        naming header comment (so a hex-dump grep finds the version
        + source URL + license without parsing the minified JS)."""
        path = FRONTEND_STATIC / "htmx.min.js"
        head = path.read_bytes()[:200].decode("utf-8", errors="replace")
        assert "htmx 2.0.10" in head
        assert "cdn.jsdelivr.net" in head
        assert "0BSD" in head
