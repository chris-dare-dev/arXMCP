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

#: Required keys per pattern entry. A YAML entry missing any key
#: causes import-time ``RuntimeError``.
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


# ---------------------------------------------------------------------------
# Canonicalization
# ---------------------------------------------------------------------------


def _canonicalize(query: str) -> str:
    """Return the canonical form of ``query`` for regex matching.

    Three steps in order:

    1. Slice to :data:`MAX_QUERY_PREFIX_CHARS` (cheap; O(1)).
    2. NFC-normalize Unicode (mirrors
       :func:`server.query_encoder._canonicalize` — keeps the
       ``étale`` / ``\\'etale`` discipline aligned across the server).
    3. Whitespace-collapse via ``" ".join(s.split())`` — handles all
       Unicode whitespace AND collapses runs of tabs/newlines/spaces
       to a single space.

    We do NOT lowercase here — :data:`re.IGNORECASE` on the compiled
    patterns handles case-insensitivity (defense-in-depth: an
    editor mistake adding a mixed-case pattern in the YAML doesn't
    silently never-match).
    """
    if not isinstance(query, str):
        # Defensive: return empty so no patterns match → DEFAULT_TAG.
        return ""
    head = query[:MAX_QUERY_PREFIX_CHARS]
    head = unicodedata.normalize("NFC", head)
    return " ".join(head.split())


# ---------------------------------------------------------------------------
# Pattern loading + compilation (import-time)
# ---------------------------------------------------------------------------


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
        missing = _REQUIRED_KEYS - set(entry.keys())
        if missing:
            raise RuntimeError(
                f"router_patterns.yaml[{idx}] missing required keys "
                f"{sorted(missing)!r}; required keys are "
                f"{sorted(_REQUIRED_KEYS)!r}."
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
        try:
            pattern = re.compile(regex_str, re.IGNORECASE)
        except re.error as exc:
            raise RuntimeError(
                f"router_patterns.yaml[{idx}].regex={regex_str!r} "
                f"failed to compile: {exc}"
            ) from exc
        compiled.append((pattern, RouteTag(tag_str)))

    if not compiled:
        raise RuntimeError(
            f"router_patterns.yaml at {patterns_path} has zero "
            f"entries; the router cannot classify with no patterns."
        )

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
