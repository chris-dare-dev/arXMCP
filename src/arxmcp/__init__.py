"""arXMCP: a local-first MCP server over a research-mathematics arXiv corpus.

The package is a handful of boxes. Each one imports only the boxes below it,
which the import-linter contract in ``pyproject.toml`` enforces:

- ``ops`` and ``tools``: backup, cutover, drift and eval; developer and
  ingest command-line utilities.
- ``server``: the MCP server, its tools and retrieval, and the operator console.
- ``ingest``: the corpus pipeline and the stores it writes.
- ``shim``: the stdio to HTTP bridge for MCP clients. It imports no other box.
"""
