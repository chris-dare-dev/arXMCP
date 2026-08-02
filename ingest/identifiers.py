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
  "old style" ``subject/NNNNNNN[v<int>]`` OR
  textbook ``textbook:<slug>`` (textbook-ingest-m1).
- ``chunk_id``: ``arxiv:<paper_id>:<16-hex>`` (arXiv) OR
  ``textbook:<slug>:<16-hex>`` (textbook-ingest-m1).
"""

from __future__ import annotations

import re

#: paper_id format. Three alternatives, each anchored independently:
#:
#: 1. arXiv new-style ``YYMM.NNNNN[v<int>]``.
#: 2. arXiv old-style ``subject/NNNNNNN[v<int>]``.
#: 3. ``textbook:<slug>`` where ``<slug>`` matches the notebook-slug
#:    inner regex (``[a-z][a-z0-9-]{2,30}``). The ``textbook:`` prefix
#:    is PART OF the paper_id; there is no symmetric ``arxiv:`` prefix
#:    on arXiv paper_ids because arXiv was the historical default.
#:    Slug source-of-truth is ``tools/_notebook_common.py::SLUG_RE``.
#:    Lands via textbook-ingest-m1.
#:
#: Independent anchoring matches the historical pattern shared with
#: ``ingest.chunker._PAPER_ID_RE`` and
#: ``tools.validate_eval_fixtures._PAPER_ID_RE``; the byte-equality
#: lock test continues to pass.
#:
#: F3 closure from proof-verify-handler-wiring-m1 critique: use ``\Z``
#: not ``$`` for the end-of-string anchor. Python's default ``$``
#: matches both end-of-string AND just before a trailing ``\n``, so
#: ``is_valid_paper_id("2604.26204\n")`` returned True pre-fix —
#: leakier than the project's "structurally rejects malformed input"
#: docstring claim. ``\Z`` matches only at the very end of the
#: string. All currently-ingested paper_ids are derived from arXiv
#: identifiers and contain no trailing whitespace, so this is
#: byte-stable for production data. textbook-ingest-m1 extends the
#: same ``\Z`` anchoring to the textbook alternative AND closes the
#: parallel ``$``→``\Z`` bug class on ``CHUNK_ID_RE`` below.
_PAPER_ID_FULL_PATTERN = (
    r"^\d{4}\.\d{4,5}(v\d+)?\Z"  # new style: 2401.00001 or 2401.00001v3
    r"|"
    r"^[a-z][a-z\-]*/\d{7}(v\d+)?\Z"  # old style: hep-th/0001234 (letters + hyphens; no dots)
    r"|"
    r"^textbook:[a-z][a-z0-9-]{2,30}\Z"  # textbook: shimura-varieties, lnm-1337, foo-bar
)

#: Inner pattern (no anchors) for the three paper_id forms.
PAPER_ID_PATTERN = (
    r"\d{4}\.\d{4,5}(v\d+)?"
    r"|[a-z][a-z\-]*/\d{7}(v\d+)?"
    r"|textbook:[a-z][a-z0-9-]{2,30}"
)

PAPER_ID_RE = re.compile(_PAPER_ID_FULL_PATTERN)

#: arXiv-only paper_id pattern. Used by ``is_valid_arxiv_paper_id``
#: at sites that construct filesystem paths or LanceDB SQL filters
#: against the shared arXiv corpus. textbook-ingest-m1 rect F2 (and
#: F1) added this helper after the adversary critique flagged that
#: widening ``is_valid_paper_id`` propagated to ≥15 downstream gates
#: that aren't ready for textbook source_kind yet (schema columns
#: land in m2, BP1 invalidation lands in m3). Sites that need the
#: union check (e.g. ``paper_id_from_chunk_id`` round-trip,
#: notebook-scoped writes once m2 ships) use ``is_valid_paper_id``;
#: every other site uses ``is_valid_arxiv_paper_id``. The constant
#: itself mirrors the pre-m1 ``_PAPER_ID_FULL_PATTERN`` exactly so
#: callsite behavior is byte-stable.
_ARXIV_PAPER_ID_FULL_PATTERN = (
    r"^\d{4}\.\d{4,5}(v\d+)?\Z"  # new style: 2401.00001 or 2401.00001v3
    r"|"
    r"^[a-z][a-z\-]*/\d{7}(v\d+)?\Z"  # old style: hep-th/0001234
)

ARXIV_PAPER_ID_RE = re.compile(_ARXIV_PAPER_ID_FULL_PATTERN)

#: chunk_id has two prefix shapes:
#:
#: 1. ``arxiv:<arxiv_paper_id>:<16-hex>`` — the ``arxiv:`` prefix is
#:    the source_kind discriminator; ``<arxiv_paper_id>`` carries no
#:    additional prefix.
#: 2. ``textbook:<slug>:<16-hex>`` — the ``textbook:<slug>`` form is
#:    BOTH the source_kind discriminator and the paper_id. Asymmetric
#:    vs arXiv by design: textbook chunks must be uniquely
#:    distinguishable at the identifier level (no schema lookup
#:    required) and the simplest form carries ``textbook:`` as part
#:    of the paper_id itself.
#:
#: The 16-hex suffix is the chunk content hash per
#: ``ingest.chunker._compute_chunk_id``. Positional capture groups
#: expose the branch-specific captures for ``paper_id_from_chunk_id``:
#:
#: - group(1) = arXiv inner paper_id (no ``arxiv:`` prefix), OR None
#:   when the textbook branch matched.
#: - group(2) = textbook paper_id INCLUDING its ``textbook:`` prefix,
#:   OR None when the arXiv branch matched.
#:
#: We deliberately use positional groups (not Python-named ``(?P<…>)``
#: syntax) so the same pattern string can mirror into the JSON Schema
#: at ``server/schemas/search_papers_result.json`` whose ECMA-262
#: regex flavor uses different named-group syntax. The byte-equality
#: lock between schema and canonical
#: (``test_schema_chunk_id_pattern_matches_canonical``) stays intact.
#:
#: The outer ``(?:...)`` wrapper is LOAD-BEARING — without it, the
#: schema's ``^{CHUNK_ID_PATTERN}$`` form would parse as
#: ``(^arxiv:…)|(textbook:…$)`` and silently allow arbitrary prefix
#: text before the textbook branch.
#:
#: Inner v-suffix groups are non-capturing (``(?:v\d+)?``). The
#: substring lock ``PAPER_ID_PATTERN in CHUNK_ID_PATTERN`` was
#: relaxed in textbook-ingest-m1 — per-alternative containment is
#: now verified by
#: ``test_chunk_id_pattern_contains_each_alternative``.
CHUNK_ID_PATTERN = (
    r"(?:"
    r"arxiv:(\d{4}\.\d{4,5}(?:v\d+)?|[a-z][a-z\-]*/\d{7}(?:v\d+)?):[0-9a-f]{16}"
    r"|"
    r"(textbook:[a-z][a-z0-9-]{2,30}):[0-9a-f]{16}"
    r")"
)

#: ``\Z`` (not ``$``) closes the F3 bug class on ``CHUNK_ID_RE``.
#: Pre-textbook-ingest-m1, ``is_valid_chunk_id(
#: "arxiv:2401.00001:abcdef0123456789\n")`` returned True because
#: Python's default ``$`` also matches before a trailing ``\n``.
#: The CHUNK_ID_PATTERN already wraps in ``(?:...)`` so the ``^``
#: and ``\Z`` anchors bind the whole alternation cleanly.
CHUNK_ID_RE = re.compile(rf"^{CHUNK_ID_PATTERN}\Z")


def is_valid_paper_id(value: str) -> bool:
    """Return True if ``value`` is a well-formed paper_id (UNION).

    Three accepted forms (textbook-ingest-m1):
    arXiv new-style, arXiv old-style, and ``textbook:<slug>``. Reject
    behavior is symmetric across all three. Empty strings, paths with
    traversal sequences (``..``), arbitrary text, trailing whitespace
    or newlines (``\\Z`` anchor — F3 closure), and chunk-id-shaped
    inputs (``foo:bar:baz``) all return False.

    **For sites that construct filesystem paths or SQL filters
    against the shared arXiv corpus, prefer :func:`is_valid_arxiv_paper_id`
    until the m2 schema columns + m3 BP1 invalidation land.** This
    function is the union check, used by ``paper_id_from_chunk_id``
    round-trip and (post-m2) by notebook-scoped writes.
    """
    return isinstance(value, str) and PAPER_ID_RE.match(value) is not None


def is_valid_arxiv_paper_id(value: str) -> bool:
    """Return True if ``value`` is a well-formed arXiv paper_id.

    Strict arXiv-only check — rejects the textbook form even though
    ``is_valid_paper_id`` accepts it. textbook-ingest-m1 rect F1 + F2:
    most existing callsites of ``is_valid_paper_id`` are filesystem-
    path constructors or SQL filters against the shared arXiv corpus,
    and the m2 schema columns / m3 BP1 invalidation haven't shipped
    yet. Those sites use this helper to preserve their pre-m1 reject
    contract; once m2 ships, they'll opt into the union by switching
    to ``is_valid_paper_id``.

    Pattern is byte-stable with the pre-m1 ``_PAPER_ID_FULL_PATTERN``:
    new-style ``YYMM.NNNNN[v<int>]`` or old-style
    ``subject/NNNNNNN[v<int>]``.
    """
    return isinstance(value, str) and ARXIV_PAPER_ID_RE.match(value) is not None


#: The ``source_kind`` a paper_id's *shape* implies. Mirrors the
#: chunks-table enum (``ingest.store._ALLOWED_SOURCE_KINDS``) and
#: ``server.handlers.search._VALID_SOURCE_KIND_FILTER_VALUES``.
SOURCE_KIND_ARXIV: str = "arxiv"
SOURCE_KIND_TEXTBOOK: str = "textbook"


def paper_id_source_kind(value: str) -> str | None:
    """Return the ``source_kind`` implied by ``value``'s shape, or ``None``
    when ``value`` is not a well-formed paper_id at all.

    Lets a consumer separate two questions that
    :func:`is_valid_arxiv_paper_id` collapsed into one boolean — "is this
    malformed?" and "is this a kind I serve?". Conflating them is
    ``chris-dare-dev/arXMCP#209``: three handlers gated on the arXiv-only
    validator and raised ``ValueError("does not match the arXiv id
    format")`` at a ``textbook:`` id that ``search_papers`` had emitted
    moments earlier, reporting a well-formed identifier as malformed
    input. Under §4.9 those are different outcomes — ``invalid-input``
    versus ``unsupported-by-provider`` — and must not share a token.

    Shape only. A ``textbook:`` id whose slug was never ingested still
    returns ``"textbook"``; whether any row exists is the caller's query
    to make, not this function's.
    """
    if not is_valid_paper_id(value):
        return None
    if value.startswith("textbook:"):
        return SOURCE_KIND_TEXTBOOK
    return SOURCE_KIND_ARXIV


def is_valid_chunk_id(value: str) -> bool:
    """Return True if ``value`` is a well-formed chunk_id."""
    return isinstance(value, str) and CHUNK_ID_RE.match(value) is not None


def paper_id_from_chunk_id(chunk_id: str) -> str:
    """Extract the paper_id segment from a chunk_id.

    Two chunk_id shapes are supported (textbook-ingest-m1):

    - ``arxiv:<arxiv_paper_id>:<16-hex>`` returns ``<arxiv_paper_id>``
      (no ``arxiv:`` prefix in the returned value — the prefix is the
      source_kind discriminator and is implicit for arXiv).
    - ``textbook:<slug>:<16-hex>`` returns ``textbook:<slug>`` (the
      ``textbook:`` prefix IS part of the paper_id in the textbook
      branch — see ``CHUNK_ID_PATTERN`` docstring).

    Delegates to the same ``CHUNK_ID_RE`` used by ``is_valid_chunk_id``
    so any drift surfaces as a parsing failure here AND a validation
    failure there — single source of truth.

    Added for E09_S03 (``cite_neighbors`` graph query); extended in
    textbook-ingest-m1 to handle the textbook branch.

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
            "arxiv:<paper_id>:<16-hex> or textbook:<slug>:<16-hex>"
        )
    # Exactly one capturing group matches per branch; the other is
    # None. group(1) = arXiv inner; group(2) = textbook full
    # (with prefix). See CHUNK_ID_PATTERN docstring.
    return match.group(1) or match.group(2)


__all__ = [
    "ARXIV_PAPER_ID_RE",
    "CHUNK_ID_PATTERN",
    "CHUNK_ID_RE",
    "PAPER_ID_PATTERN",
    "PAPER_ID_RE",
    "is_valid_arxiv_paper_id",
    "is_valid_chunk_id",
    "is_valid_paper_id",
    "paper_id_from_chunk_id",
]
