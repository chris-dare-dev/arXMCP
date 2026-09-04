"""Shared plumbing for the two statement CLIs on the ingest plane.

``tools/statement_resolve.py`` (derived-alg-geo-lean #170) and
``tools/statement_mint.py`` (#169) both need the same three things: the
contract package's text normalization, a read-only view of a notebook's
chunks, and a read-only view of its ``documents.db`` revision rows. This
module is where they meet, so there is exactly one answer to each.

**Everything here is READ-ONLY, and that is load-bearing rather than
tidy.** ``CLAUDE.md`` §4.8 rule 2 permits writes only through offline
ingest CLIs; these two CLIs write no corpus state at all. They read
LanceDB and SQLite and emit a file. In particular
:func:`read_document_versions` opens ``documents.db`` through a
``mode=ro`` URI rather than :class:`server.documents_store.DocumentsStore`,
because ``DocumentsStore.open`` CREATES the file when it is missing, and
"the registry is absent" is a fact these tools must be able to observe
rather than erase. Same discipline as
``tools/notebook_list_offline.py``'s m2-critique-F2 rectification.

**The normalization is imported, never reimplemented.** ``norm_text`` is
``mfc.digest.norm_text`` — NFC, then whitespace-run collapse, in that
order. A second copy of that function in this repo would be a second
answer to "is this the same statement", and the two would drift on the
first Unicode-normalization subtlety anybody hits. When they drifted, the
symptom would be a citation silently re-pointed at a different theorem,
which is the exact failure the whole contract exists to prevent. So `mfc`
is a hard requirement of both CLIs, installed via the ``contract`` extra
(ADR-0009 makes it a shared tool for exactly this reason), and a missing
install is an error with the command to fix it rather than a fallback.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable

#: Printed when `mfc` is not importable. Names the extra rather than the
#: git URL: an operator who pip-installs the URL by hand gets an unpinned
#: rev, and the pin is the point.
MFC_INSTALL_HINT = (
    "the contract package `mfc` is not installed.\n"
    "  pip install -e '.[contract]'   (from the arXMCP checkout)\n"
    "\n"
    "It is a hard requirement, not an optional nicety: these CLIs compare\n"
    "statement text against corpus text, and the normalization that makes\n"
    "that comparison meaningful must be the SAME implementation the topic\n"
    "repo minted its digests with. A local copy would drift silently, and\n"
    "the symptom of the drift is a citation re-pointed at a different\n"
    "theorem."
)

#: LanceDB column set these tools read. Deliberately narrow — the chunks
#: table carries three 1024-float embedding columns, and selecting them
#: turns an 11k-row read into a multi-hundred-MB one for no reason.
_CHUNK_COLUMNS = (
    "chunk_id",
    "paper_id",
    "kind",
    "body_text",
    "printed_number",
    "theorem_label",
    "chunker_version",
)

#: Columns that a notebook ingested before their migration simply does not
#: have. ``printed_number`` landed after the first notebooks were built and
#: is absent from ``shimura-varieties`` today, so selecting it
#: unconditionally raises ``KeyError: Field "printed_number" does not
#: exist``. Absent is read as ``None`` for every row, which is the truth.
_OPTIONAL_CHUNK_COLUMNS = frozenset({
    "printed_number", "theorem_label", "chunker_version", "kind",
})


class StatementToolError(RuntimeError):
    """A precondition the operator can fix. The CLI prints it and exits 1."""


@dataclass(frozen=True, slots=True)
class Chunk:
    """One corpus chunk, reduced to the fields identity resolution uses.

    ``chunk_id`` is a CACHE HINT and never authoritative — it rotates on any
    parse change, and ``merge_insert`` has no delete arm, so a stale id stays
    addressable and would resolve to whatever now occupies it. Every rung of
    the ladder that accepts a match recomputes ``body_text``'s digest;
    ``chunk_id`` only ever decides which chunk to look at first.
    """

    chunk_id: str
    paper_id: str
    body_text: str
    printed_number: str | None = None
    theorem_label: str | None = None
    kind: str | None = None
    chunker_version: str | None = None


def require_mfc() -> tuple[Callable[[str], str], Callable[[str], str], Path]:
    """Return ``(norm_text, quote_sha256, schema_dir)`` or raise.

    Imported at call time rather than module scope so ``--help`` works, and
    so an import error names the fix instead of a traceback ending in
    ``ModuleNotFoundError``.
    """
    try:
        from mfc.digest import norm_text, quote_sha256
    except ImportError as exc:  # pragma: no cover - exercised by hand
        raise StatementToolError(MFC_INSTALL_HINT) from exc
    import mfc

    schema_dir = Path(mfc.__file__).resolve().parent / "schema"
    return norm_text, quote_sha256, schema_dir


def validate_against(document: dict[str, Any], schema_stem: str) -> None:
    """Validate ``document`` against a shipped `mfc` schema, or raise.

    The topic repo's CI is the real gate (``mfc check-resolution``), and
    this does not replace it. It exists so a malformed artifact fails at the
    producer, where the operator is standing, rather than one commit later
    in a repo they may not own.
    """
    import json

    import jsonschema

    _, _, schema_dir = require_mfc()
    schema_path = schema_dir / f"{schema_stem}.schema.json"
    if not schema_path.is_file():  # pragma: no cover - packaging regression
        raise StatementToolError(
            f"{schema_path.name} is missing from the installed mfc package; "
            f"the wheel did not ship its schemas"
        )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        jsonschema.Draft202012Validator(schema).iter_errors(document),
        key=lambda e: list(e.path),
    )
    if errors:
        first = errors[0]
        raise StatementToolError(
            f"the document this tool just produced does not validate against "
            f"{schema_stem}: {first.json_path}: {first.message}"
        )


def load_chunks(lancedb_dir: Path, *, table_name: str = "chunks") -> list[Chunk]:
    """Read every chunk of a notebook's LanceDB table, newest version.

    Sorted by ``chunk_id`` so two runs over one corpus version produce
    byte-identical output — a resolution whose ``results[]`` order depends
    on Arrow fragment layout would show a diff on every re-run and teach the
    operator to ignore diffs.
    """
    import lancedb

    if not lancedb_dir.is_dir():
        raise StatementToolError(
            f"no LanceDB directory at {lancedb_dir} — ingest the notebook first"
        )
    db = lancedb.connect(str(lancedb_dir))
    if table_name not in db.table_names():
        raise StatementToolError(
            f"no {table_name!r} table in {lancedb_dir} — ingest the notebook first"
        )
    table = db.open_table(table_name)
    arrow = table.to_arrow()
    present = set(arrow.schema.names)
    missing = [c for c in _CHUNK_COLUMNS if c not in present]
    hard_missing = [c for c in missing if c not in _OPTIONAL_CHUNK_COLUMNS]
    if hard_missing:
        raise StatementToolError(
            f"{lancedb_dir}'s {table_name} table has no "
            f"{', '.join(hard_missing)} column(s); it predates the schema "
            f"these tools read"
        )
    selected = [c for c in _CHUNK_COLUMNS if c in present]
    rows = arrow.select(selected).to_pylist()
    return sorted(
        (
            Chunk(
                chunk_id=row["chunk_id"],
                paper_id=row["paper_id"],
                body_text=row["body_text"] or "",
                printed_number=row.get("printed_number"),
                theorem_label=row.get("theorem_label"),
                kind=row.get("kind"),
                chunker_version=row.get("chunker_version"),
            )
            for row in rows
        ),
        key=lambda c: c.chunk_id,
    )


def read_corpus_version(lancedb_dir: Path, *, table_name: str = "chunks") -> int:
    """The LanceDB MVCC integer for the chunks table.

    Recorded in the resolution, never trusted as an ordering: a
    restore-from-backup presents a LOWER version over different bytes, which
    is why ``corpus_manifest_content_hash`` is the field the freshness gate
    actually compares.
    """
    import lancedb

    db = lancedb.connect(str(lancedb_dir))
    return int(db.open_table(table_name).version)


def read_document_versions(documents_db: Path) -> dict[str, str]:
    """``{work_id: arxiv_version}`` from a notebook's ``documents.db``.

    Opened ``mode=ro`` through a URI, so a missing file raises instead of
    being created (``DocumentsStore.open`` would create it, and an empty
    registry silently backfilled with nothing is indistinguishable from one
    that was read).

    An empty string is preserved rather than dropped, because ``''`` and
    "this work is not in the registry at all" are different facts and the
    version guard treats them the same way only after saying which it saw.
    """
    if not documents_db.is_file():
        return {}
    uri = f"file:{documents_db.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        try:
            rows = conn.execute(
                "SELECT work_id, arxiv_version FROM documents"
            ).fetchall()
        except sqlite3.OperationalError:
            # No `documents` table: the notebook was never backfilled. That
            # is "no version information", not an error.
            return {}
    finally:
        conn.close()
    out: dict[str, str] = {}
    for work_id, version in rows:
        # PRIMARY KEY is (work_id, arxiv_version), so one work can carry
        # several revision rows. A concrete version beats '' — if ANY row
        # for this work names a version, the corpus knows one.
        current = out.get(work_id, "")
        out[work_id] = version or current
    return out


def corpus_paper_id(source: dict[str, Any]) -> str | None:
    """The arXMCP ``paper_id`` a registry ``source`` block addresses.

    ``None`` when the scheme has no corpus coordinate at all — ``doi`` and
    ``url`` sources are legal in the registry and simply are not things this
    corpus indexes. Returning ``None`` rather than guessing is what keeps
    such an entry at ``not_run`` with a reason instead of ``unresolvable``,
    which would read as "we looked and it is gone".

    The arXiv version is deliberately NOT appended. ``paper_id`` in the
    chunks table is the bare id (``0705.3794``, ``math/0307164``); the
    version lives in ``documents.arxiv_version``, is ``''`` everywhere
    today, and is the version guard's business rather than the lookup's.
    """
    scheme = source.get("scheme")
    ident = source.get("id")
    if not isinstance(ident, str) or not ident:
        return None
    if scheme == "arxiv":
        return ident
    if scheme == "textbook":
        return f"textbook:{ident}"
    return None


def by_paper(chunks: Iterable[Chunk]) -> dict[str, list[Chunk]]:
    """Group chunks by ``paper_id``, preserving the sorted-by-id order."""
    grouped: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        grouped.setdefault(chunk.paper_id, []).append(chunk)
    return grouped


__all__ = [
    "MFC_INSTALL_HINT",
    "Chunk",
    "StatementToolError",
    "by_paper",
    "corpus_paper_id",
    "load_chunks",
    "read_corpus_version",
    "read_document_versions",
    "require_mfc",
    "validate_against",
]
