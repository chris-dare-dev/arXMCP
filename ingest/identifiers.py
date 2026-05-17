"""Single source of truth for arxmcp identifier regexes (F11 close).

The chunk_id and paper_id formats are referenced by:

- ``ingest/chunker.py`` (the writer; closes Threat 1 path-traversal
  per ``08-security-observability-ops.md``).
- ``tools/validate_eval_fixtures.py`` (the eval-fixture validator;
  ensures curated chunk_ids match the chunker's output).
- ``server/handlers/*.py`` (every tool handler that accepts a
  paper_id or chunk_id from agent input).

Closes F11 from the E06_S03 critique. Three call sites had drifted
toward independent definitions; this module collapses them to one.
A single drift here is caught by ``tests/test_identifiers.py``.

The regexes themselves match the format documented in
``.claude/notes/02-architecture-overview.md``:

- ``paper_id``: arXiv "new style" ``YYMM.NNNNN[v<int>]`` OR
  "old style" ``subject/NNNNNNN[v<int>]``.
- ``chunk_id``: ``arxiv:<paper_id>:<16-hex>``.
"""

from __future__ import annotations

import re

#: arXiv paper_id format. New-style + old-style. The ``vN`` version
#: suffix is OPTIONAL (most chunks reference the version-less form).
#:
#: The two alternatives are EACH anchored independently — this
#: matches the historical pattern that ``ingest.chunker._PAPER_ID_RE``
#: and ``tools.validate_eval_fixtures._PAPER_ID_RE`` both use, so
#: the byte-equality lock test below passes without rewriting the
#: existing call sites.
_PAPER_ID_FULL_PATTERN = (
    r"^\d{4}\.\d{4,5}(v\d+)?$"  # new style: 2401.00001 or 2401.00001v3
    r"|"
    r"^[a-z][a-z\-]*/\d{7}(v\d+)?$"  # old style: hep-th/0001234 (letters + hyphens; no dots)
)

#: Inner pattern (no anchors) for embedding in the chunk_id regex.
PAPER_ID_PATTERN = (
    r"\d{4}\.\d{4,5}(v\d+)?|[a-z][a-z\-]*/\d{7}(v\d+)?"
)

PAPER_ID_RE = re.compile(_PAPER_ID_FULL_PATTERN)

#: chunk_id is ``arxiv:<paper_id>:<16-hex>``. The 16-hex suffix is
#: the ``sha256(preamble_text + NFC(body_text))[:16]`` per
#: ``ingest.chunker._compute_chunk_id``.
CHUNK_ID_PATTERN = rf"arxiv:({PAPER_ID_PATTERN}):[0-9a-f]{{16}}"

CHUNK_ID_RE = re.compile(rf"^{CHUNK_ID_PATTERN}$")


def is_valid_paper_id(value: str) -> bool:
    """Return True if ``value`` is a well-formed arXiv paper_id.

    Reject behavior is symmetric for both new-style and old-style.
    Empty strings, paths with traversal sequences (``..``), and
    arbitrary text all return False.
    """
    return isinstance(value, str) and PAPER_ID_RE.match(value) is not None


def is_valid_chunk_id(value: str) -> bool:
    """Return True if ``value`` is a well-formed chunk_id."""
    return isinstance(value, str) and CHUNK_ID_RE.match(value) is not None


def paper_id_from_chunk_id(chunk_id: str) -> str:
    """Extract the paper_id segment from a chunk_id.

    The ``chunk_id`` format is ``arxiv:<paper_id>:<16-hex>``. This
    function delegates to the same ``CHUNK_ID_RE`` used by
    ``is_valid_chunk_id`` so any drift surfaces as a parsing failure
    here AND validation failure there — single source of truth.

    Added for E09_S03 (the ``cite_neighbors`` graph query takes a
    ``chunk_id`` and needs to derive the ``paper_id`` for the Kùzu
    lookup; previously every caller would have inlined the regex).

    Raises ``ValueError`` for malformed input — keeps the call sites
    one-liner and surfaces invalid input at the boundary rather than
    deep in a graph query.
    """
    if not isinstance(chunk_id, str):
        raise ValueError(
            f"chunk_id must be a string, got {type(chunk_id).__name__}"
        )
    match = CHUNK_ID_RE.match(chunk_id)
    if not match:
        raise ValueError(
            f"chunk_id {chunk_id!r} is not well-formed; expected "
            "arxiv:<paper_id>:<16-hex>"
        )
    return match.group(1)


__all__ = [
    "CHUNK_ID_PATTERN",
    "CHUNK_ID_RE",
    "PAPER_ID_PATTERN",
    "PAPER_ID_RE",
    "is_valid_chunk_id",
    "is_valid_paper_id",
    "paper_id_from_chunk_id",
]
