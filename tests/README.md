# tests/

`pytest` test suite. Run with `make test` (which also runs `ruff check .`).

Per-component tests are colocated by name (`tests/test_<module>.py`). Integration tests against the live arXiv `/e-print/` endpoint or LaTeXML installation are skipped by default — they require `ARXMCP_CONTACT_EMAIL` to be set and network access.
