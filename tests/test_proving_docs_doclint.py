"""Doc-lint: the ``.claude`` proving protocol docs must not reference
repo-relative source/artifact paths that do not exist.

Stage-3 proving finding #3 (minor) — the concrete instance of the
"protocol-docs-as-agent-lore drift" hazard: the IF-5 custody move
(``server/proving/schemas/`` -> ``contracts/``, integration fix
b83ac05) updated the code and ``server/proving/README.md`` but NOT the
agent protocol docs, so ``/prove`` Step 1 directed the agent to author
the ProofTask against ``server/proving/schemas/proof-task.v0.schema.json``
and its example — neither of which exists at HEAD. It fails closed (the
engine validates tasks) but strands an agent at the correctness-critical
authoring step of the proving pipeline.

This lint keeps the proving ``.claude`` protocol docs honest
mechanically: every backtick-quoted token that looks like a
repo-relative path into a source/artifact tree
(``server/`` ``contracts/`` ``ingest/`` ``tools/`` ``tests/``) ending in
a real file extension MUST resolve to a file on disk. The next custody
move that forgets to update these docs turns red here instead of
stranding an agent.

Deliberately narrow to avoid false positives:
- only backtick-quoted tokens (prose mentions are not path claims);
- only the five source/artifact roots (``var/`` is a gitignored runtime
  tree created per-run, not a checked-in artifact; ``.claude/`` link
  targets are relative markdown links, not source paths);
- only tokens ending in ``.py``/``.json``/``.yaml``/``.yml``/``.md``
  (directory-only mentions and ``<placeholder>`` / glob forms are not
  file claims and are skipped on purpose).

Same hazard class and same fix pattern as
``tests/test_claude_md_doclint.py`` (WS-0 AC-0.1): the claim must be
re-argued against ground truth, never inherited.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The proving-pipeline agent protocol docs under ``.claude`` (the
#: files finding #3 stranded). Add new proving protocol docs here as
#: they land so the same lint covers them.
PROTOCOL_DOCS: tuple[str, ...] = (
    ".claude/commands/prove.md",
    ".claude/proving/README.md",
)

#: Backtick-quoted token extractor.
_BACKTICK = re.compile(r"`([^`\n]+)`")

#: A repo-relative path into a checked-in source/artifact tree ending
#: in a real file extension. Anchored so a trailing slash (directory
#: mention) or a ``<placeholder>``/``*`` (illustrative form) does not
#: match — only concrete file claims are linted.
_PATHISH = re.compile(
    r"^(?:server|contracts|ingest|tools|tests)/[\w./-]+\.(?:py|json|ya?ml|md)$"
)


def _referenced_paths(doc_text: str) -> list[str]:
    seen: dict[str, None] = {}
    for m in _BACKTICK.finditer(doc_text):
        token = m.group(1).strip()
        if _PATHISH.match(token):
            seen.setdefault(token)
    return list(seen)


def test_proving_protocol_docs_reference_only_existing_paths():
    offenders: list[str] = []
    for rel in PROTOCOL_DOCS:
        doc = REPO_ROOT / rel
        if not doc.exists():
            offenders.append(f"{rel}: protocol doc itself is missing")
            continue
        text = doc.read_text(encoding="utf-8")
        for token in _referenced_paths(text):
            if not (REPO_ROOT / token).exists():
                offenders.append(f"{rel} -> `{token}` does not exist")
    if offenders:
        raise AssertionError(
            "A proving `.claude` protocol doc references a repo-relative "
            "source/artifact path that does not exist (finding #3 — the "
            "IF-5 custody-move drift). Update the doc to the real path in "
            "the same change as the move; do not weaken this lint:\n  "
            + "\n  ".join(offenders)
        )


def test_doclint_actually_finds_path_references():
    """Guard the guard: if the extractor stops matching (e.g. a regex
    edit silently narrows it to nothing), the lint above would pass
    vacuously. Pin that prove.md's ProofTask schema references — the
    exact ones finding #3 broke — are seen by the extractor."""
    text = (REPO_ROOT / ".claude/commands/prove.md").read_text(encoding="utf-8")
    referenced = _referenced_paths(text)
    assert "contracts/proof-task.v0.schema.json" in referenced, referenced
    assert "contracts/examples/proof-task.v0.example.json" in referenced, referenced
