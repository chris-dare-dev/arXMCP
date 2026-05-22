# Vendored static assets

This directory holds third-party assets vendored into the repo so the
arXMCP daemon makes ZERO internet fetches at runtime (m8 AC #5). Each
asset is committed with a recorded SHA-256 below; the integrity test
at `tests/test_vendored_assets_integrity.py` pins the hash so a future
re-vendor must update both the file AND this manifest in lockstep.

Out-of-band verification: when bumping a vendored asset, download
from the source URL, compute the SHA-256 (`shasum -a 256 <file>`),
compare against the upstream's published hash (most CDNs publish a
SRI hash next to the file URL), then update both the file and this
manifest.

## Inventory

### `htmx.min.js`

| Property | Value |
|---|---|
| Library | [htmx](https://htmx.org/) |
| Version | 2.0.10 |
| License | 0BSD |
| Source URL | `https://cdn.jsdelivr.net/npm/htmx.org@2.0.10/dist/htmx.min.js` |
| Vendored | 2026-05-22 (proof-verify-handler-wiring-m8) |
| SHA-256 (as stored) | `5e6ee42df72f91d6f5ddcfd746ed157f96071a9ad68df148ead526c864d3ddc7` |
| Pinned in test | `tests/test_vendored_assets_integrity.py::TestVendoredHtmxIntegrity` |

The recorded hash is of the file *as stored on disk* — i.e. with a
1-line header comment prepended after download (naming the version
+ source URL + license). On re-vendor: download the upstream file,
prepend the header line in the exact same format, compute
`shasum -a 256 frontend/static/htmx.min.js`, update the SHA-256
above AND the constant in the test in lockstep.

### `app.css`

Project-authored, not vendored. No hash recorded.
