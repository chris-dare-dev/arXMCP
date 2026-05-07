"""Math-aware regex pre-tokenizer for the BM25 ``body_tokens`` field (E02_S03).

No custom Tantivy LaTeX analyzer is used; see H4 remediation in `.claude/roadmap/README.md`.

Public API
----------
``tokenize_body(body_text: str) -> str``
    Walk the chunk's ``body_text`` and produce a whitespace-joined token
    stream. The output is what E04_S04 will hand to ``rank_bm25`` after
    a single ``split()`` call.

Tokenization rules
------------------
1. NFC-normalize the input (mirrors the F6 fix from E02_S02 — required for
   BP1 byte-identical caching across hosts).
2. Strip ``$...$`` math delimiters (treat ``$`` as syntax, not vocabulary).
3. Match in a single ``re.findall`` alternation pass:
   * ``\\command{arg}`` where arg is alphanumeric: emit ``command_arg`` —
     strip backslash, underscore-join. Examples: ``\\mathbb{Z}`` → ``mathbb_Z``,
     ``\\mathrm{Spec}`` → ``mathrm_Spec``.
   * Bare ``\\command`` (command is one or more letters): emit ``command``.
     Example: ``\\partial`` → ``partial``, ``\\Spec`` → ``Spec``.
   * Identifier with subscript or superscript: ``X_a``, ``H_1``, ``H_{ij}``
     → ``X_a``, ``H_1``, ``H_ij``. For non-alphanumeric script content
     (``H^{n+1}``, ``H_{i,j}``) emit only the base identifier.
   * Plain Latin word (with optional internal hyphen): emit verbatim.
4. Do NOT lowercase — math identifiers are case-significant
   (``Z`` ≠ ``z``).
5. Do NOT deduplicate — BM25 weights by term frequency.
6. Do NOT apply minimum length — single-letter math identifiers
   (``X``, ``Z``) carry meaning.

Why a regex, not a custom analyzer
----------------------------------
Earlier design notes prescribed "BM25 over ``body_raw_latex`` (LaTeX
analyzer)" implying a custom Tantivy analyzer. Tantivy ships no such
analyzer. Building one in Rust would be multi-week work for a Python
project that doesn't otherwise need Rust. The Python regex approach is
self-contained, deterministic, sub-millisecond at the 512-token-chunk
scale, and trades small recall on exotic LaTeX for shipping today. The
H4 finding from the rev-2026-05 roadmap critique forced this decision;
``05-storage-and-indexing.md`` and the milestone brief are aligned.

Determinism
-----------
* Module-level compiled pattern (one-time cost at import).
* No randomness, no set iteration order, no locale dependency.
* NFC normalization at the top of ``tokenize_body``.
* ``re.findall`` returns matches in left-to-right document order.

Performance target: ``< 1ms`` per 512-token chunk on a 2020-era laptop CPU.
"""

from __future__ import annotations

import re
import unicodedata

# Single compiled alternation pattern. Alternative branches are tried
# left-to-right by ``re``; ordering is significant — the more specific
# ``\command{arg}`` branch must precede the bare ``\command`` branch so
# the latter doesn't strip the leading backslash before the former sees
# its argument.
_TOKENIZER_RE = re.compile(
    # Branch 1: \command{arg} where arg is alphanumeric (single letters,
    # multi-letter operator names like Spec / Hom / End, digits).
    r"\\(?P<cmd_arg_name>[A-Za-z@]+)\{(?P<cmd_arg_val>[A-Za-z0-9]+)\}"
    # Branch 2: bare \command (no argument or non-simple argument).
    r"|\\(?P<cmd_bare>[A-Za-z@]+)"
    # Branch 3: identifier_subscript / identifier^superscript with simple
    # alphanumeric script content (optional braces).
    r"|(?P<id_base>[A-Za-z])(?P<id_sep>[_^])\{?(?P<id_script>[A-Za-z0-9]+)\}?"
    # Branch 4: plain Latin word (with optional internal hyphens).
    r"|(?P<word>[A-Za-z][A-Za-z\-]*)"
)


def tokenize_body(body_text: str) -> str:
    """Produce a whitespace-joined token string for BM25 indexing.

    The function is pure and deterministic: same input → same output on
    any Python version, on any host, every time. It applies NFC
    normalization, strips ``$...$`` math delimiters, runs one regex sweep
    over the result, and returns ``" ".join(tokens)``.
    """
    if not body_text:
        return ""

    # F6 / BP1: canonicalize Unicode form before tokenization.
    text = unicodedata.normalize("NFC", body_text)

    # Strip math delimiters. The ``$`` is syntax, not vocabulary; it would
    # otherwise leak into the bare-word branch via the surrounding chars.
    text = text.replace("$", " ")

    tokens: list[str] = []
    for match in _TOKENIZER_RE.finditer(text):
        if match.group("cmd_arg_name") is not None:
            # \mathbb{Z} → mathbb_Z
            tokens.append(
                f"{match.group('cmd_arg_name')}_{match.group('cmd_arg_val')}"
            )
        elif match.group("cmd_bare") is not None:
            # \partial → partial
            tokens.append(match.group("cmd_bare"))
        elif match.group("id_base") is not None:
            # H_1, H_{ij} → H_1, H_ij  (sep + script joined as underscore)
            tokens.append(
                f"{match.group('id_base')}_{match.group('id_script')}"
            )
        elif match.group("word") is not None:
            tokens.append(match.group("word"))

    return " ".join(tokens)
