"""Optional injection-pattern sanitizer for retrieved paper content (E13_S02).

The primary defense against indirect prompt injection from paper content is
the ``<retrieved_chunk>...</retrieved_chunk>`` delimiter wrapper applied by
:func:`server.tools.wrap_retrieved_text`. The sanitizer here is a defense-in-
depth layer — OFF by default — that scrubs four literal byte sequences known
to be tokenized as role-control tokens by current LLMs:

* ``<|system|>``
* ``[INST]``
* ``<|im_start|>``
* ``ignore previous instructions`` (case-sensitive)

The literal-byte check is intentional: these patterns are what the consuming
LLM sees AFTER LaTeXML rendering. LaTeX-encoded variants (e.g.
``\\text{<|system|>}``) are not matched here — defending against semantic /
encoded injection requires a model-aware classifier, which is out of scope
per ``.claude/notes/09-feature-priorities.md`` § "Things to explicitly NOT
build in v1".

**Activation.** Set the environment variable ``ARXMCP_SANITIZE_RETRIEVED_CONTENT=1``
to enable. Any other value (including ``true``, ``yes``, ``on``) is treated as
disabled — exact-string ``"1"`` is the documented contract. The first call with
sanitization enabled logs at WARN level once per process; subsequent calls are
silent (warn-once pattern).

**False-positive surface.** Enabling this sanitizer may corrupt chunks from
papers that legitimately discuss LLM architecture or tokenization (the math-ph
and hep-th categories most likely to include such content). The audit doc at
``.claude/docs/security-threat-2-audit.md`` documents this trade-off.

See:

* ``.claude/notes/08-security-observability-ops.md`` § Threat 2 — the
  mitigation contract.
* ``.claude/docs/security-threat-2-audit.md`` — full audit including
  per-tool wrapping status, deferred work, and false-positive surface.
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

#: Tokenizer-role markers — matched case-SENSITIVE because the
#: consuming LLM tokenizes these as exact byte sequences. A casing
#: variant like ``<|System|>`` is a different token in the model's
#: vocabulary and does not pose the same threat as the canonical
#: lowercased form below.
_TOKENIZER_PATTERNS: tuple[str, ...] = (
    "<|system|>",
    "[INST]",
    "<|im_start|>",
)

#: Natural-language injection patterns — matched case-INSENSITIVE
#: because English prose tokenizes case-equivalently in modern
#: BPE/Tiktoken vocabularies. A case-sensitive match would be
#: trivially bypassed by "Ignore Previous Instructions" or
#: "IGNORE PREVIOUS INSTRUCTIONS". F6 rectification (E13_S02
#: adversary critique): the previous single-list implementation
#: justified case-sensitive matching by "literal-byte only" — but
#: that justification only fits tokenizer markers, not NL prose.
#: The pattern types are now correctly separated.
_NL_PATTERNS: tuple[str, ...] = (
    "ignore previous instructions",
)

#: Combined list for documentation / log purposes. The actual
#: substitution uses the two lists above with different matching
#: discipline.
_INJECTION_PATTERNS: tuple[str, ...] = _TOKENIZER_PATTERNS + _NL_PATTERNS

#: Pre-compiled case-insensitive regex for the NL patterns. Compiled
#: once at module import to avoid per-call compilation cost.
_NL_PATTERN_RE: re.Pattern[str] = re.compile(
    "|".join(re.escape(p) for p in _NL_PATTERNS),
    flags=re.IGNORECASE,
)

#: Environment-variable name controlling sanitizer activation. Set to
#: exactly ``"1"`` (the string, not the integer; any other value is
#: treated as disabled). Documented in the audit doc.
_SANITIZE_ENV_VAR = "ARXMCP_SANITIZE_RETRIEVED_CONTENT"

#: Warn-once guard. The first call with sanitization enabled logs once;
#: subsequent calls in the same process are silent. Same pattern as the
#: ``_warned_resources_not_ready_for_tracing`` flag in ``server/tools.py``.
_warned: bool = False


def is_sanitization_enabled() -> bool:
    """Return True iff the ``ARXMCP_SANITIZE_RETRIEVED_CONTENT`` env var
    is set to exactly ``"1"``. Any other value — including truthy
    variants like ``"true"`` or ``"yes"`` — returns False. The
    exact-string contract is intentional; see module docstring.
    """
    return os.environ.get(_SANITIZE_ENV_VAR) == "1"


def sanitize_retrieved_text(text: str | None) -> str:
    """Strip literal injection patterns from ``text`` if sanitization is enabled.

    The four patterns stripped (when enabled) are documented in
    :data:`_INJECTION_PATTERNS`. Patterns are removed with literal
    string replacement; no regex, no normalization, no Unicode-fold.

    OFF by default. When enabled via ``ARXMCP_SANITIZE_RETRIEVED_CONTENT=1``,
    the first call logs a WARN-level message and the global ``_warned``
    flag flips so subsequent calls stay silent.

    For empty / None input, returns the empty string. The caller is
    expected to apply :func:`server.tools.wrap_retrieved_text` AFTER
    sanitization — sanitize-then-wrap is the canonical order
    (synthesis D3).

    Args:
        text: Retrieved paper-derived text. May be None or empty.

    Returns:
        The text with any matched injection patterns removed (if
        sanitization is enabled), or the original text unchanged (if
        disabled). Empty input returns ``""``.
    """
    global _warned
    if not text:
        return ""
    if not is_sanitization_enabled():
        return text
    if not _warned:
        logger.warning(
            "ARXMCP_SANITIZE_RETRIEVED_CONTENT=1 — sanitizing literal "
            "injection patterns (%s) from retrieved content. The "
            "delimiter wrapper is still the primary Threat-2 defense.",
            ", ".join(_INJECTION_PATTERNS),
        )
        _warned = True
    # Tokenizer-role markers — case-sensitive literal replace.
    for pattern in _TOKENIZER_PATTERNS:
        text = text.replace(pattern, "")
    # Natural-language patterns — case-insensitive regex replace
    # (F6 rectification). Bypassed in the previous implementation
    # by trivial case variation like "Ignore Previous Instructions".
    text = _NL_PATTERN_RE.sub("", text)
    return text


def _reset_warned_for_tests() -> None:
    """Reset the warn-once flag. For test-suite use only.

    The warn-once pattern is correct for production but bites tests
    that exercise multiple enable/disable transitions. Tests that
    need to observe the WARN log should call this between scenarios.
    """
    global _warned
    _warned = False
