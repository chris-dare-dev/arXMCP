"""PDF JavaScript / auto-action detection (textbook-ingest-m4).

Detects PDF dictionary key names that indicate embedded JavaScript,
auto-open actions, or other content-execution vectors. Algorithm
borrowed (NOT copied) from Didier Stevens' public-domain ``pdfid``
tool — see ``.claude/notes/capability-scouts/pdf-ingest-2026/`` CAND-2
for the vendoring discipline and ``tools/security/README.md`` for the
no-fork policy rationale.

**This is defense-in-depth, NOT a complete PDF malware scanner.** The
detection is a byte-level string-grep over the PDF token stream:

- It WILL detect ``/JS`` / ``/JavaScript`` / ``/OpenAction`` / etc.
  written in plain-text PDF object syntax.
- It will NOT detect tokens hidden inside ``FlateDecode`` (or other
  filter) compressed object streams. A determined adversary can hide
  ``/JS`` in a compressed stream and the byte-grep will miss it.
- It will NOT detect tokens written via PDF name-tree hex escapes
  (e.g. ``/4A53`` is hex-encoded ``/JS``).

Backstops for evasion cases (m4 rect F5 — corrected attribution):

- **Compressed-stream JS evasion:** the actual protection is that
  PyMuPDF (the parser MinerU uses internally) does NOT evaluate
  embedded JavaScript — see `.claude/docs/security-pdf-sandbox.md`
  threat surface table row 1. m5's RLIMIT_AS / wall-timeout
  sandbox bounds the resource consumption of MinerU's parsing
  pass; it does NOT block JS execution (which never happens
  because PyMuPDF doesn't run it).
- **Hex-encoded name tokens (``/#4A#53`` = ``/JS``):** the same
  two protections apply — PyMuPDF's non-evaluation of decoded
  hex-escaped JavaScript names, plus m5's sandbox bounding parse-
  time damage if PyMuPDF mis-handles the encoding.

This module's role is **defense-in-depth at the upload boundary**:
catch the common plaintext-token cases before MinerU is invoked,
so operator-supplied PDFs with obvious malicious markers are
rejected fast. PyMuPDF's parser-level non-evaluation is the layer-2
backstop for evasions; the m5 subprocess sandbox is the layer-3
damage-bound for any future parser swap that introduces a
JS-evaluating component.

Usage:
    >>> from tools.security.pdfid import find_javascript
    >>> find_javascript(b"%PDF-1.4\\n/Catalog << /JS (alert(1)) >>")
    ['/JS']

Token list (DANGEROUS_PDF_NAMES):
    /JS             — JavaScript action body
    /JavaScript     — JavaScript named action
    /OpenAction     — action triggered when the document opens
    /AA             — Additional Actions (per-page / per-event)
    /Launch         — file or executable launch action
    /SubmitForm     — form-submit action (data exfil vector)
    /ImportData     — form-data import action

The 7-token list matches the publicly-documented Didier Stevens
detection set. Cite the algorithm; do not copy the source.
"""

from __future__ import annotations

import re

#: Canonical set of PDF dictionary keys that indicate active content.
#: Exported as a frozenset for the route-handler's documentation
#: hyperlink and for the unit tests in tests/test_pdfid.py.
DANGEROUS_PDF_NAMES: frozenset[str] = frozenset(
    {
        "/JS",
        "/JavaScript",
        "/OpenAction",
        "/AA",
        "/Launch",
        "/SubmitForm",
        "/ImportData",
    }
)

#: Compiled regex matching any of the dangerous names as raw PDF
#: tokens. A PDF name token is preceded by ``/`` and followed by a
#: delimiter byte (whitespace, ``<``, ``>``, ``[``, ``(``, ``/``) or
#: end-of-stream. The lookahead prevents false-positives on longer
#: keys (e.g. ``/JavaScripty`` should NOT match ``/JavaScript``).
#:
#: Order matters: longer alternatives MUST come BEFORE shorter ones
#: so ``re.findall`` prefers the longer match (e.g. ``/JavaScript``
#: must be tried before ``/JS``). Python's ``re`` engine is leftmost-
#: first within an alternation, NOT longest-match — so the sort here
#: is by descending length, NOT alphabetical.
_DANGEROUS_PATTERN = re.compile(
    rb"/(?:" + b"|".join(
        sorted(
            (name[1:].encode("ascii") for name in DANGEROUS_PDF_NAMES),
            key=len,
            reverse=True,
        )
    ) + rb")(?=[\s<>/\[\(]|\Z)"
)


def find_javascript(pdf_bytes: bytes) -> list[str]:
    """Return the list of dangerous PDF name tokens found in ``pdf_bytes``.

    Returns an EMPTY list if no dangerous tokens are present — the
    caller can treat the result as a truthiness check (``if
    find_javascript(content): reject(...)``).

    The returned tokens are ASCII-decoded for readability in error
    messages (``["/JS", "/OpenAction"]``). PDF tokens are always
    ASCII per ISO 32000.

    Parameters
    ----------
    pdf_bytes:
        Raw PDF byte stream. The caller should pass the full upload
        body, NOT a truncated prefix — dangerous tokens may appear
        anywhere in the document, not just the header.

    Notes
    -----
    Token order in the returned list is occurrence order in the byte
    stream (leftmost-first per ``re.finditer``). Duplicates are
    preserved — if a PDF has two ``/JS`` entries, both appear in the
    result. The caller decides whether to surface unique-token sets
    or full occurrence counts.
    """
    if not isinstance(pdf_bytes, (bytes, bytearray)):
        raise TypeError(
            f"pdf_bytes must be bytes-like, got {type(pdf_bytes).__name__}"
        )
    return [
        match.group(0).decode("ascii")
        for match in _DANGEROUS_PATTERN.finditer(pdf_bytes)
    ]


__all__ = [
    "DANGEROUS_PDF_NAMES",
    "find_javascript",
]
