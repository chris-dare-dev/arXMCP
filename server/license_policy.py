"""License-based content-truncation policy (textbook-ingest-m11 / e5).

Non-open-access chunks may legally surface only a short excerpt of their
body text. :func:`server.handlers.chunk.handle_get_chunk` truncates a
non-OA chunk's body to :data:`LICENSE_TRUNCATION_CHARS` characters and
flags the response ``truncated_for_license=True``; open-access chunks
return their full body.

The policy is an exact-string **ALLOWLIST** with a **FAIL-CLOSED**
default: any ``license`` token NOT in :data:`OA_ALLOWLIST` — including
``None`` and the empty string — is treated as non-open-access (truncate).
This is the conservative posture for copyright compliance, per the
roadmap ``[SHOULD]`` assumption (``plans/textbook-ingest-roadmap.md``:
"License truncation policy (300 chars + ``truncated_for_license: true``
flag) is acceptable to operator for non-OA chunks").

``get_chunk`` is the ONLY MCP tool that surfaces a full chunk body — the
``search_papers`` snippet is already capped at 150 chars (< 300), and
``find_equation`` / ``get_definitions`` / ``find_lemma_by_name`` return
no ``body_text``. So enforcing the policy in ``get_chunk`` covers every
full-body leakage surface (textbook-ingest-m11 research, brief-2).
"""

from __future__ import annotations

#: Maximum number of characters of a NON-open-access chunk's body that
#: ``get_chunk`` surfaces. 300 is a short, fair-use-shaped excerpt — and
#: far below the 256 KB byte-cap, so license truncation always fires
#: BEFORE the byte-cap path (a <=300-char body never trips the cap, so no
#: ``resource_link`` to the full body is ever emitted for a non-OA chunk;
#: see the m11 FM-2 leak-path analysis). Truncation uses ``str`` slicing,
#: which is Unicode-codepoint-safe (never splits a multibyte char).
LICENSE_TRUNCATION_CHARS: int = 300

#: License tokens whose chunks may surface their FULL body. Exact-string,
#: case-sensitive. Rationale (textbook-ingest-m11 research):
#: - ``arxiv-license`` — the dominant corpus license; classifying it OA
#:   keeps the existing 100%-arXiv corpus regression-free.
#: - ``CC-BY`` / ``CC-BY-SA`` / ``CC0`` — Creative Commons; redistributable.
#: - ``public-domain`` — no rights reserved.
#: - ``GFDL`` — the Stacks Project license; redistributable (copyleft-open).
#: Everything else (``author-distributed``, ``copyrighted``, ``"no explicit
#: license"``, unknown tokens, ``""``, ``None``) is non-OA -> truncated.
OA_ALLOWLIST: frozenset[str] = frozenset(
    {
        "arxiv-license",
        "CC-BY",
        "CC-BY-SA",
        "CC0",
        "public-domain",
        "GFDL",
    }
)


def is_open_access(license_token: str | None) -> bool:
    """Return ``True`` iff ``license_token`` permits full-body surfacing.

    FAIL CLOSED: ``None`` and the empty string return ``False`` (treated
    as non-open-access). Exact-string, case-sensitive membership in
    :data:`OA_ALLOWLIST`. A pure predicate — no invariant to guard, so
    no ``assert`` (banned per CLAUDE.md 4.7) and no ``raise``.
    """
    if not license_token:  # covers both None and ""
        return False
    return license_token in OA_ALLOWLIST
