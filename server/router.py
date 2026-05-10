"""Query router (E08_S01).

Fast synchronous classifier that assigns a user query to one of four
agent roles (``RouteTag``). NO LLM planner, NO embedding similarity,
NO external API call — the router runs in <1 ms on a 200-character
query via pre-compiled regex matching against a YAML pattern list.

**H1 closure** (per ``.claude/roadmap/README.md:68`` —
*"Sonnet planner unjustified → Python regex router | E08_S01"*):
this module is the SOLE closer of the H1 finding. The risk-note
rationale: zero LLM calls on the routing path, deterministic, and
auditable (the pattern list is version-controlled YAML with a
rationale per entry).

**The four roles** (per
``.claude/notes/07-multi-agent-caching.md:66-67``):

- ``RouteTag.LOOKUP`` — agent retrieves a specific named object
  from the corpus (definitions, theorem statements, notation).
- ``RouteTag.SYNTHESIS`` — agent assembles a proof strategy
  across multiple retrieved chunks.
- ``RouteTag.VERIFICATION`` — agent receives a candidate proof
  step and validates it.
- ``RouteTag.AUTOFORMALIZATION`` — agent produces Lean 4 syntax.

The set is closed at four for v1; multi-label routing is
explicitly out of scope per the brief.

**The router is NOT the final arbiter of agent behavior.** If the
regex fires incorrectly, the agent's role-prefix (E08_S02) still
constrains its behavior. Misrouting is a quality issue, not a
correctness issue — which is why ``classify`` returns
``RouteTag.LOOKUP`` (the cheapest role) on no-match rather than
raising.

**Pattern source-of-truth**: ``server/router_patterns.yaml``.
Editing the YAML does NOT require modifying this module
(brief AC #6). The module loads + compiles the patterns once at
import time; failures (missing file, malformed YAML, unknown
``tag``, bad regex) propagate as ``RuntimeError`` at import so
the operator sees the problem at startup, not at first query.

**Latency contract**: ``classify(query)`` returns within 1 ms for
any 200-character query (brief AC #4). Verified by ``timeit``
in ``tests/test_router.py``.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maximum prefix length the router inspects. The brief says "the
#: first 200 characters of the user query" — anything past 200 chars
#: is irrelevant for classification. Slicing first keeps the
#: normalization step O(1) regardless of query size.
MAX_QUERY_PREFIX_CHARS: int = 200

#: Path to the YAML pattern file. Relative to this module so the
#: file moves with the source. ``Path(__file__).parent`` resolves
#: to ``server/`` regardless of CWD.
PATTERNS_PATH: Path = Path(__file__).parent / "router_patterns.yaml"

#: Required keys per pattern entry. A YAML entry with EXACTLY
#: this set of keys passes; any missing OR extra key raises at
#: import (F8 fix from the E08_S01 critique).
_REQUIRED_KEYS: frozenset[str] = frozenset({"tag", "regex", "rationale"})




# ---------------------------------------------------------------------------
# RouteTag enum (closed at four)
# ---------------------------------------------------------------------------


class RouteTag(StrEnum):
    """The four agent roles. The set is CLOSED at four for v1; adding
    a fifth value requires coordination with E08_S02 (role prefixes)
    and E08_S05 (model selection), which both assert "exactly 4".

    ``StrEnum`` (Python 3.11+) is the modern stdlib choice — clean
    repr, JSON-serializable without a custom encoder, and downstream
    consumers can do ``tag.name.lower()`` cleanly.
    """

    LOOKUP = "LOOKUP"
    SYNTHESIS = "SYNTHESIS"
    VERIFICATION = "VERIFICATION"
    AUTOFORMALIZATION = "AUTOFORMALIZATION"


#: Default tag returned by :func:`classify` when no pattern matches.
#: Routes the query to the cheapest agent role (Haiku for retrieval
#: per ``E08-agent-runtime.md:192``). Per ``01-mission-and-context.md``,
#: Sketcher/Tactician retrieval is the most general-purpose path —
#: a no-match query is "I don't know what this is", which most
#: resembles "look something up". Document the choice prominently.
DEFAULT_TAG: RouteTag = RouteTag.LOOKUP


#: Per-tag priority rank (higher = higher priority). F4 fix from
#: the E08_S01 critique: encode the synthesis D4 priority order
#: (AUTOFORMALIZATION > VERIFICATION > LOOKUP > SYNTHESIS) so the
#: loader can assert YAML insertion order is monotonically
#: non-increasing under this key — appending an AUTOFORMALIZATION
#: pattern at the bottom of the file silently demoting it would
#: raise at import.
_TAG_PRIORITY_RANK: dict[RouteTag, int] = {
    RouteTag.AUTOFORMALIZATION: 4,
    RouteTag.VERIFICATION: 3,
    RouteTag.LOOKUP: 2,
    RouteTag.SYNTHESIS: 1,
}


# ---------------------------------------------------------------------------
# Canonicalization
# ---------------------------------------------------------------------------


def _canonicalize(query: Any) -> str:
    """Return the canonical form of ``query`` for regex matching.

    Three steps in order:

    1. (F2 fix) If ``query`` is ``bytes`` / ``bytearray``,
       decode as UTF-8 with ``errors="replace"`` first. Wire-borne
       MCP requests can carry undecoded bytes through some
       integration points; silently returning ``DEFAULT_TAG`` for
       a real input shape would mask the upstream bug. A
       round-trippable decode preserves the user's intent.
    2. Slice to :data:`MAX_QUERY_PREFIX_CHARS` (cheap; O(1)).
    3. NFC-normalize Unicode (mirrors
       :func:`server.query_encoder._canonicalize` — keeps the
       ``étale`` / ``\\'etale`` discipline aligned across the server).
    4. Whitespace-collapse via ``" ".join(s.split())`` — handles all
       Unicode whitespace AND collapses runs of tabs/newlines/spaces
       to a single space.

    We do NOT lowercase here — :data:`re.IGNORECASE` on the compiled
    patterns handles case-insensitivity (defense-in-depth: an
    editor mistake adding a mixed-case pattern in the YAML doesn't
    silently never-match).
    """
    # F2 fix: bytes / bytearray → decode UTF-8 with errors=replace.
    # The U+FFFD replacement char doesn't match any router pattern;
    # invalid UTF-8 input degrades gracefully to DEFAULT_TAG via
    # the no-match path rather than raising.
    if isinstance(query, (bytes, bytearray)):
        query = bytes(query).decode("utf-8", errors="replace")
    if not isinstance(query, str):
        # Defensive: return empty so no patterns match → DEFAULT_TAG.
        return ""
    head = query[:MAX_QUERY_PREFIX_CHARS]
    head = unicodedata.normalize("NFC", head)
    return " ".join(head.split())


# ---------------------------------------------------------------------------
# Pattern loading + compilation (import-time)
# ---------------------------------------------------------------------------


#: Static-analysis regex matching the canonical "nested quantifier"
#: ReDoS shape: a quantified group whose body itself contains a
#: quantifier — e.g. ``(a*)*``, ``(a+)+``, ``(.*)+``, ``(.+)*``.
#: These exhibit catastrophic backtracking: ``(a*)*b`` on
#: ``'a' * 28`` takes ~18 s on commodity Python.
#:
#: We use a static check rather than a timing probe because:
#:   - A timing probe must run the regex; ``re`` does not release
#:     the GIL during catastrophic backtracking, so a thread-based
#:     probe leaks runaway threads on rejection — the worker keeps
#:     burning CPU after the probe times out.
#:   - The static check is fast, deterministic, and covers the
#:     canonical ReDoS shape that 99% of accidental edits would
#:     produce. (Sophisticated ReDoS via overlapping alternation —
#:     e.g. ``(a|a)*`` — is not caught here; that's a deliberate
#:     trade-off documented in the code comment.)
_REDOS_NESTED_QUANTIFIER_RE = re.compile(
    # Match a parenthesized group whose body contains a + * or ?
    # quantifier, immediately followed by another + * or ? quantifier
    # outside the group. Allows arbitrary chars inside the group
    # except nested unbalanced parens, since this is a heuristic
    # not a parser.
    r"\([^()]*[+*?][^()]*\)[+*?]"
)


def _assert_pattern_redos_safe(
    pattern: re.Pattern[str],  # noqa: ARG001 — kept for callsite symmetry
    pattern_idx: int,
    pattern_src: str,
) -> None:
    """Reject patterns whose REGEX SOURCE contains the canonical
    nested-quantifier ReDoS shape.

    F1 fix from the E08_S01 critique. Static-analysis check (NOT a
    timing probe) — see :data:`_REDOS_NESTED_QUANTIFIER_RE` for
    why a timing probe is unsafe (leaks runaway daemon threads on
    catastrophic patterns since ``re`` doesn't release the GIL).

    Catches: ``(a*)*``, ``(a+)+``, ``(.*)+``, ``(a?)*``, etc.
    Misses: overlapping-alternation ReDoS (``(a|a)*``) and other
    sophisticated shapes — those are rare in YAML edits and would
    need a true regex parser to detect, which is overkill for a
    classifier of <30 patterns.
    """
    if _REDOS_NESTED_QUANTIFIER_RE.search(pattern_src):
        raise RuntimeError(
            f"router_patterns.yaml[{pattern_idx}].regex={pattern_src!r} "
            f"failed the ReDoS static check: the regex source "
            f"contains the nested-quantifier shape ``(...X)Y`` where X "
            f"and Y are both ``+ * ?`` quantifiers. This shape causes "
            f"catastrophic backtracking — e.g. ``(a*)*b`` on "
            f"``'a' * 28`` takes ~18 s on commodity Python. "
            f"Rewrite the pattern WITHOUT nested quantifiers (use "
            f"alternation or pre-anchor with ``\\b`` / ``\\A``)."
        )


def _load_and_compile(
    patterns_path: Path = PATTERNS_PATH,
) -> tuple[tuple[re.Pattern[str], RouteTag], ...]:
    """Read the YAML pattern file, validate, compile, and return an
    immutable tuple of ``(compiled_pattern, tag)`` pairs in YAML
    declaration order.

    Validation (any failure → ``RuntimeError`` at import):

    1. File must exist + be readable.
    2. Top-level YAML value must be a list.
    3. Every entry must be a dict with EXACTLY the keys in
       :data:`_REQUIRED_KEYS`.
    4. Every ``tag`` must be a valid :class:`RouteTag` value.
    5. Every ``regex`` must compile cleanly with
       ``re.IGNORECASE``.

    Loaded with :func:`yaml.safe_load` only — never ``yaml.load``
    (CVE-2017-18342: the latter deserializes arbitrary Python
    objects → RCE on a malicious YAML).
    """
    try:
        text = patterns_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"router_patterns.yaml missing at {patterns_path}; "
            f"the router cannot classify without its pattern list."
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            f"router_patterns.yaml unreadable at {patterns_path}: {exc}"
        ) from exc

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RuntimeError(
            f"router_patterns.yaml at {patterns_path} is malformed YAML: "
            f"{exc}"
        ) from exc

    if not isinstance(raw, list):
        raise RuntimeError(
            f"router_patterns.yaml at {patterns_path} must be a YAML "
            f"list at the top level; got {type(raw).__name__!s}."
        )

    compiled: list[tuple[re.Pattern[str], RouteTag]] = []
    valid_tag_values = {t.value for t in RouteTag}
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise RuntimeError(
                f"router_patterns.yaml[{idx}] must be a mapping; "
                f"got {type(entry).__name__!s}."
            )
        # F8 fix from the E08_S01 critique: reject EXTRA keys, not
        # only missing ones. A future maintainer adding an
        # "ignored" field (e.g. ``priority: 99``) gets a clear
        # signal that the field has no semantics here.
        missing = _REQUIRED_KEYS - set(entry.keys())
        extra = set(entry.keys()) - _REQUIRED_KEYS
        if missing or extra:
            raise RuntimeError(
                f"router_patterns.yaml[{idx}] keys must be exactly "
                f"{sorted(_REQUIRED_KEYS)!r}; got "
                f"missing={sorted(missing)!r}, extra={sorted(extra)!r}."
            )
        tag_str = entry["tag"]
        if tag_str not in valid_tag_values:
            raise RuntimeError(
                f"router_patterns.yaml[{idx}].tag={tag_str!r} is not a "
                f"valid RouteTag value; expected one of "
                f"{sorted(valid_tag_values)!r}."
            )
        regex_str = entry["regex"]
        if not isinstance(regex_str, str):
            raise RuntimeError(
                f"router_patterns.yaml[{idx}].regex must be a string; "
                f"got {type(regex_str).__name__!s}."
            )
        # F7 fix: validate rationale is a non-empty string. The
        # "annotated rationale" premise breaks down silently if a
        # null / int / empty value passes the import check.
        rationale = entry["rationale"]
        if not isinstance(rationale, str) or not rationale.strip():
            raise RuntimeError(
                f"router_patterns.yaml[{idx}].rationale must be a "
                f"non-empty string; got {rationale!r}. The audit-trail "
                f"premise (per the E08_S01 brief) requires every "
                f"pattern to carry a human-readable explanation."
            )
        try:
            pattern = re.compile(regex_str, re.IGNORECASE)
        except re.error as exc:
            raise RuntimeError(
                f"router_patterns.yaml[{idx}].regex={regex_str!r} "
                f"failed to compile: {exc}"
            ) from exc
        # F1 fix: ReDoS probe. Reject patterns that take longer than
        # _REDOS_PROBE_DEADLINE_S on a 200-char worst-case input.
        _assert_pattern_redos_safe(pattern, idx, regex_str)
        compiled.append((pattern, RouteTag(tag_str)))

    if not compiled:
        raise RuntimeError(
            f"router_patterns.yaml at {patterns_path} has zero "
            f"entries; the router cannot classify with no patterns."
        )

    # F4 fix from the E08_S01 critique: assert the YAML order is
    # monotonically non-increasing under priority rank. A future
    # edit that appends e.g. an AUTOFORMALIZATION pattern at the
    # bottom of the file silently demotes it; this check fails
    # loudly at import.
    prev_rank = _TAG_PRIORITY_RANK[compiled[0][1]]
    prev_tag = compiled[0][1]
    for idx, (_pattern, tag) in enumerate(compiled):
        rank = _TAG_PRIORITY_RANK[tag]
        if rank > prev_rank:
            raise RuntimeError(
                f"router_patterns.yaml block-order violation at entry "
                f"[{idx}] tag={tag.value!r} (priority={rank}) appears "
                f"AFTER tag={prev_tag.value!r} (priority={prev_rank}). "
                f"YAML insertion order MUST be monotonically "
                f"non-increasing under tag priority "
                f"(AUTOFORMALIZATION > VERIFICATION > LOOKUP > "
                f"SYNTHESIS) — see synthesis D4 + the YAML header."
            )
        prev_rank = rank
        prev_tag = tag

    logger.info(
        "router: compiled %d patterns from %s", len(compiled), patterns_path,
    )
    return tuple(compiled)


# Module-level constant — compiled ONCE at import. The 1ms latency
# budget demands this; per-call compilation would blow it.
_COMPILED_PATTERNS: tuple[tuple[re.Pattern[str], RouteTag], ...] = (
    _load_and_compile()
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify(query: Any) -> RouteTag:
    """Classify ``query`` to one of the four :class:`RouteTag` roles.

    Performs in <1 ms (brief AC #4) — pre-compiled patterns,
    O(1) prefix slice, single linear scan over the pattern list,
    first-match wins.

    Defensive: ``None``, non-``str``, empty, and whitespace-only
    inputs all return :data:`DEFAULT_TAG` (= ``RouteTag.LOOKUP``)
    rather than raising. Per the brief: "Misrouting is a quality
    issue, not a correctness issue."

    Parameters
    ----------
    query:
        The user query string. May be any type; non-strings are
        treated as empty.

    Returns
    -------
    RouteTag
        The first-matching tag in YAML priority order, or
        :data:`DEFAULT_TAG` if no pattern matches.
    """
    canonical = _canonicalize(query)
    if not canonical:
        return DEFAULT_TAG
    for pattern, tag in _COMPILED_PATTERNS:
        if pattern.search(canonical):
            return tag
    return DEFAULT_TAG


__all__ = [
    "DEFAULT_TAG",
    "MAX_QUERY_PREFIX_CHARS",
    "PATTERNS_PATH",
    "RouteTag",
    "classify",
]
