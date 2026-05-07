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
     → ``X_a``, ``H_1``, ``H_ij``. The script content must be balanced —
     a brace-opened script must close cleanly with a matching ``}`` and
     no intervening non-alphanumeric characters. Inputs like ``H^{n+1}``
     (the ``+`` breaks the alphanumeric run) and ``H_{i,j}`` (the ``,``
     breaks balance) bypass the script branch entirely; the input falls
     through to the word branch, which emits each alphanumeric component
     as a separate token (``H``, ``n`` from ``H^{n+1}``; ``H``, ``i``,
     ``j`` from ``H_{i,j}``). Recall loss on these exotic notations is
     in scope per the milestone risk notes.
   * Unicode letter word (with optional internal hyphen — no leading or
     trailing hyphen): emits verbatim. Both ASCII and non-ASCII letters
     are matched (``étale``, ``Poincaré``, ``Hörmander``); BM25 recall
     would otherwise drop terms ubiquitous in algebraic geometry,
     analysis, and physics names.
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

# Closes F6: a tokenizer version string fed into chunk_id (E02_S04) and
# the BM25 cache key (E04_S04). Bumping ``_TOKENIZER_RE`` or the post-
# processing rules MUST bump TOKENIZER_VERSION; the byte-stability
# regression test in tests/test_tokenizer.py asserts a golden output for
# a fixed input under a fixed version, so an unintentional regex change
# fails CI before it can silently invalidate the BM25 cache.
TOKENIZER_VERSION = "v1.0"

# Single compiled alternation pattern. Alternative branches are tried
# left-to-right by ``re``; ordering is significant — the more specific
# ``\command{arg}`` branch must precede the bare ``\command`` branch so
# the latter doesn't strip the leading backslash before the former sees
# its argument.
#
# Word class: ``[^\W\d_]`` is Unicode-aware and matches "any letter
# without digits or underscore" — it admits étale, Poincaré, Möbius,
# Hörmander, Schrödinger, Hölder, fibré, and the rest of the math
# vocabulary that the original ``[A-Za-z]`` class silently truncated.
# Closes F2.
#
# Word body: ``(?:[^\W\d_]|-)*[^\W\d_]`` requires the final character
# to be a letter, disallowing trailing hyphens like ``well-``. Closes
# F11.
#
# Id branch: the script content is either a single alphanumeric (no
# braces) or fully brace-balanced ``\{[A-Za-z0-9]+\}``. The previous
# ``\{?...\}?`` form leaked unbalanced inputs like ``H_{i,j}`` as
# ``H_i`` plus a stray ``j``. Closes F5.
_TOKENIZER_RE = re.compile(
    # Branch 1: \command{arg} where arg is alphanumeric (single letters,
    # multi-letter operator names like Spec / Hom / End, digits).
    r"\\(?P<cmd_arg_name>[A-Za-z@]+)\{(?P<cmd_arg_val>[A-Za-z0-9]+)\}"
    # Branch 2: bare \command (no argument or non-simple argument).
    r"|\\(?P<cmd_bare>[A-Za-z@]+)"
    # Branch 3: identifier_subscript / identifier^superscript. Either a
    # single alphanumeric script char (no braces) or a brace-balanced
    # alphanumeric run.
    r"|(?P<id_base>[A-Za-z])(?P<id_sep>[_^])"
    r"(?:(?P<id_script_braced>\{[A-Za-z0-9]+\})|(?P<id_script_bare>[A-Za-z0-9]))"
    # Branch 4: Unicode-aware letter word with optional internal hyphens
    # (no leading/trailing hyphen).
    r"|(?P<word>[^\W\d_](?:(?:[^\W\d_]|-)*[^\W\d_])?)",
    re.UNICODE,
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
            # H_1, H_{ij} → H_1, H_ij. The sep (_, ^) is normalised to
            # underscore so subscript and superscript indexers collide
            # under BM25 (intentional — both are "subscript-shaped"
            # qualifiers from the prose perspective).
            braced = match.group("id_script_braced")
            # Strip the surrounding braces if the braced alternative matched.
            script = braced[1:-1] if braced is not None else match.group("id_script_bare")
            tokens.append(f"{match.group('id_base')}_{script}")
        elif match.group("word") is not None:
            tokens.append(match.group("word"))

    return " ".join(tokens)
