"""Structured open-problem sources + cross-referencing (WS-E v0, AC-E.4).

The exploration pipeline consults structured open-problem sources
(finding 04 key finding 5 / §2.4.4 / §2.1.3):

- **formal-conjectures** — DeepMind's curated machine-readable
  open-conjecture corpus (Lean 4, Apache-2.0/CC-BY,
  https://github.com/google-deepmind/formal-conjectures).
- **emergentmind-open-problems** — EmergentMind's arXiv Open Problems
  extraction surface (public API; solo-maintained — treat extractions
  as candidates needing verification, never a hard dependency).
- **randomstrasse101** — annual open-problem lists published on arXiv
  (2504.20539 for 2024, 2603.29571 for 2025).

v0 consumes these as LOCAL SNAPSHOT FILES (one JSON per source; shape
below), refreshed agent-side/CLI per the procedure in
``.claude/exploration/README.md`` — tests never fetch (the mission's
offline rule), and the server never fetches (loopback invariant).

Snapshot shape (``*.snapshot.json``)::

    {
      "name": "formal-conjectures",          # required, non-empty
      "kind": "github-lean-corpus",           # optional
      "url": "https://github.com/...",        # optional
      "retrieved_at": "2026-07-01T00:00:00Z", # required (provenance!)
      "entries": [                            # required (may be empty)
        {
          "id": "...",                        # required, non-empty
          "title": "...",                     # required, non-empty
          "statement": "...",                 # optional
          "tags": ["math.AG", ...],           # optional
          "arxiv_ids": ["2601.12345", ...],   # optional
          "url": "..."                        # optional
        }, ...
      ]
    }

Cross-referencing is deterministic and LLM-free (two rules, checked in
order; both can fire):

1. **Explicit id** — the entry lists a candidate's arXiv id in
   ``arxiv_ids``.
2. **Keyword overlap** — the entry's informative tokens (title +
   statement + tags) and the candidate's (title + abstract head) share
   at least :data:`KEYWORD_MATCH_THRESHOLD` tokens.

Every match yields a human-auditable provenance line naming the source
and the entry id — the GPT-5-Erdős lesson applied to discovery:
novelty/openness claims require provenance (AC-E.4).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

#: Minimum shared informative tokens for a keyword-overlap match.
KEYWORD_MATCH_THRESHOLD = 3

#: Tokens too generic to signal a topical match in research-math titles
#: and abstracts. Lowercase; compared against lowercased tokens.
_STOPWORDS = frozenset(
    {
        "about", "above", "after", "algebra", "algebraic", "also", "among", "analysis",
        "applications", "approach", "arbitrary", "associated", "between", "both", "case",
        "cases", "certain", "class", "classes", "conjecture", "consider", "construction",
        "corresponding", "define", "defined", "definition", "denote", "does", "each",
        "every", "exists", "field", "fields", "finite", "first", "following", "from",
        "function", "functions", "general", "generalized", "give", "given", "gives",
        "group", "groups", "have", "here", "into", "introduction", "known", "lemma",
        "let", "main", "mathematics", "method", "methods", "more", "moreover", "most",
        "new", "note", "notes", "number", "obtain", "obtained", "only", "open", "over",
        "paper", "particular", "problem", "problems", "proof", "properties", "property",
        "prove", "proved", "proven", "provide", "question", "questions", "recent",
        "related", "respectively", "result", "results", "several", "show", "shown",
        "showed", "some", "space", "spaces", "structure", "structures", "study", "such",
        "that", "their", "then", "theorem", "theory", "there", "these", "this", "those",
        "under", "using", "very", "well", "when", "where", "which", "whose", "with",
        "work",
    }
)

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z'-]{3,}")


@dataclass(frozen=True)
class OpenProblemEntry:
    """One open problem / conjecture from a source snapshot."""

    entry_id: str
    title: str
    statement: str = ""
    tags: tuple[str, ...] = ()
    arxiv_ids: tuple[str, ...] = ()
    url: str = ""


@dataclass(frozen=True)
class SourceSnapshot:
    """A loaded open-problem source snapshot."""

    name: str
    retrieved_at: str
    kind: str = ""
    url: str = ""
    entries: tuple[OpenProblemEntry, ...] = ()
    path: str = ""

    def as_payload(self, entries_matched: int) -> dict[str, object]:
        """The manifest ``payload.open_problem_sources[]`` item."""
        out: dict[str, object] = {
            "name": self.name,
            "retrieved_at": self.retrieved_at,
            "entries_considered": len(self.entries),
            "entries_matched": entries_matched,
        }
        if self.kind:
            out["kind"] = self.kind
        if self.url:
            out["url"] = self.url
        return out


@dataclass
class CrossRefResult:
    """Cross-referencing outcome: provenance per paper + per-source counts."""

    provenance: dict[str, list[str]] = field(default_factory=dict)
    matched_entries_per_source: dict[str, int] = field(default_factory=dict)


def informative_tokens(text: str) -> set[str]:
    """Lowercased informative tokens (length >= 4, stopwords removed)."""
    return {
        t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS
    }


def _require_str(obj: dict, key: str, ctx: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{ctx}: {key!r} must be a non-empty string")
    return value.strip()


def load_snapshot(path: Path) -> SourceSnapshot:
    """Load + validate one source snapshot file."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"source snapshot {path}: unreadable ({exc})") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"source snapshot {path}: top level must be an object")
    ctx = f"source snapshot {path}"
    name = _require_str(raw, "name", ctx)
    retrieved_at = _require_str(raw, "retrieved_at", ctx)
    entries_raw = raw.get("entries")
    if not isinstance(entries_raw, list):
        raise ValueError(f"{ctx}: 'entries' must be a list")
    entries: list[OpenProblemEntry] = []
    for i, e in enumerate(entries_raw):
        if not isinstance(e, dict):
            raise ValueError(f"{ctx}: entries[{i}] must be an object")
        ectx = f"{ctx} entries[{i}]"
        entries.append(
            OpenProblemEntry(
                entry_id=_require_str(e, "id", ectx),
                title=_require_str(e, "title", ectx),
                statement=str(e.get("statement", "") or ""),
                tags=tuple(str(t) for t in e.get("tags", []) or ()),
                arxiv_ids=tuple(str(a) for a in e.get("arxiv_ids", []) or ()),
                url=str(e.get("url", "") or ""),
            )
        )
    return SourceSnapshot(
        name=name,
        retrieved_at=retrieved_at,
        kind=str(raw.get("kind", "") or ""),
        url=str(raw.get("url", "") or ""),
        entries=tuple(entries),
        path=str(path),
    )


def load_snapshots(directory: Path) -> list[SourceSnapshot]:
    """Load every ``*.snapshot.json`` under ``directory`` (sorted by name)."""
    if not directory.is_dir():
        raise ValueError(f"sources dir not found: {directory}")
    snapshots = [load_snapshot(p) for p in sorted(directory.glob("*.snapshot.json"))]
    if not snapshots:
        raise ValueError(
            f"sources dir {directory} contains no *.snapshot.json files — "
            "refresh snapshots per .claude/exploration/README.md or omit --sources-dir"
        )
    return snapshots


def _strip_version(paper_id: str) -> str:
    return paper_id.split("v", 1)[0] if "v" in paper_id else paper_id


def cross_reference(
    snapshots: list[SourceSnapshot],
    papers: list[tuple[str, str]],
) -> CrossRefResult:
    """Match open-problem entries against candidate papers.

    ``papers`` is ``[(paper_id, searchable_text), ...]`` where
    ``searchable_text`` is title + abstract head. Returns provenance
    lines keyed by paper_id plus per-source matched-entry counts.
    Deterministic: sources and entries are processed in order, token
    sets are sorted before rendering.
    """
    result = CrossRefResult()
    paper_tokens = {pid: informative_tokens(text) for pid, text in papers}

    for snap in snapshots:
        matched_entry_ids: set[str] = set()
        for entry in snap.entries:
            entry_ids = {_strip_version(a) for a in entry.arxiv_ids}
            entry_tok = informative_tokens(
                " ".join((entry.title, entry.statement, " ".join(entry.tags)))
            )
            for pid, _text in papers:
                lines = result.provenance.setdefault(pid, [])
                if _strip_version(pid) in entry_ids:
                    matched_entry_ids.add(entry.entry_id)
                    lines.append(
                        f"{snap.name} entry {entry.entry_id}: explicitly cites arXiv:{pid}"
                    )
                overlap = entry_tok & paper_tokens[pid]
                if len(overlap) >= KEYWORD_MATCH_THRESHOLD:
                    matched_entry_ids.add(entry.entry_id)
                    shown = ", ".join(sorted(overlap)[:5])
                    lines.append(
                        f"{snap.name} entry {entry.entry_id}: keyword overlap {{{shown}}}"
                    )
        result.matched_entries_per_source[snap.name] = len(matched_entry_ids)

    # Drop papers that gathered no lines (setdefault side effect).
    result.provenance = {k: v for k, v in result.provenance.items() if v}
    return result


__all__ = [
    "KEYWORD_MATCH_THRESHOLD",
    "CrossRefResult",
    "OpenProblemEntry",
    "SourceSnapshot",
    "cross_reference",
    "informative_tokens",
    "load_snapshot",
    "load_snapshots",
]
