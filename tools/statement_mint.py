"""Prefill a candidate registry entry from a corpus chunk. Mints nothing.

Lands derived-alg-geo-lean **#169** (epic #134). Offline, read-only, on the
ingest plane — the same plane as ``tools/statement_resolve.py`` and what
``CLAUDE.md`` §4.8 rule 2 permits.

## Why this is here and not in `mfc`

Minting was specified inside the contract package, and cannot live there.
``mfc``'s declared dependency is ``jsonschema`` and nothing else; it can reach
neither LanceDB nor a loopback server. And the lookup the operator actually
needs — *fetch the chunk printed as Lemma 8.2* — did not exist anywhere. The
audit's words: "No tool accepts ``printed_number`` as an input… there is no
'fetch the chunk numbered 8.2' path." :func:`find_by_printed_number` is that
path, and it is why this file is in arXMCP.

## What it does NOT do

**It does not mint identity.** ADR-0002: a citation key contains zero
corpus-derived bytes, and it is minted by a human in the topic repo. This tool
prints a *suggested* key when it can read the registry's ``registry_id``, and
that is a suggestion — the human types the label.

**It does not write to the topic repo.** It writes a fragment to stdout. The
seam is cold (ADR-0001) and this side of it has no business editing the other
side's files.

**It does not fill in the human's judgement.** Four fields are always the
human's and the fragment carries them as ``null`` — ``kind``, ``title``,
``informal``, ``minted_by`` — joined by ``source.version`` whenever the corpus
cannot supply it, and by the key itself, always.
``null`` rather than a ``"TODO"`` string on purpose — a placeholder string
VALIDATES, so a fragment pasted and forgotten would sail through
``mfc registry validate`` carrying the word TODO into a published record.
``null`` fails, loudly, at the first gate the topic repo runs.

So this tool's output is DELIBERATELY INVALID on purpose, it says so on
stderr, and it prints the checklist of what a human still owes.

## What it fills, and from what

* ``quote`` — the chunk's ``body_text``, byte-for-byte as the corpus made it.
* ``quote_sha256`` — ``mfc.digest.quote_sha256`` over that text, which is the
  same function the resolver will compare against.
* ``quote_norm`` — ``nfc-ws-collapse/1``.
* ``quote_mode`` — ``verbatim``. ``digest_only`` costs offline verification and
  is a deliberate downgrade the schema makes you justify.
* ``source.printed_number`` — the chunk's, when the chunker extracted one.
* ``source.version`` — ``documents.arxiv_version`` when the corpus knows it,
  else ``null``.
* ``mint_resolution`` — this notebook, this chunk id, ``matched_by:
  quote_sha256`` (true by construction: the quote IS the chunk body), the
  corpus manifest hash, and the observation time.

**Do not hand-correct the ``quote``.** It is the machine-owned field and
``quote_sha256`` is computed over it. A human fix to a LaTeXML artifact there
permanently breaks exact match and silently demotes the entry to
``printed_number`` or to unresolvable. Corrections go in ``quote_as_read``,
which is displayed and never hashed.

Usage::

    # by printed number — the lookup that did not exist
    uv run python -m tools.statement_mint --notebook bridgeland-stability \\
        --paper math/0212237 --printed-number 8.2

    # by chunk id, when you already have one
    uv run python -m tools.statement_mint --notebook bridgeland-stability \\
        --chunk-id arxiv:math/0212237:a82c3230040fd724

    # find the chunk first; this LISTS, it never picks
    uv run python -m tools.statement_mint --notebook bridgeland-stability \\
        --paper math/0212237 --search "local homeomorphism"

Exit codes:
    0 — a candidate fragment was printed (it is not valid; that is the point)
    1 — no chunk selected: none matched, several did, or a precondition failed
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools._statement_common import (
    Chunk,
    StatementToolError,
    load_chunks,
    read_corpus_version,
    read_document_versions,
    require_mfc,
)

#: The fields no machine may fill. Emitted as `null`, which is invalid against
#: `registry/1.0` and therefore cannot be pasted and forgotten.
HUMAN_OWNED = (
    "kind — theorem / lemma / definition / obligation / … as the paper has it",
    "title — how a person would name this statement, <=256 chars",
    "informal — what it says, in prose, for a reader who has not opened the paper",
    "minted_by — the person accepting this entry; not a tool name",
)

#: Printed when a scan turns up more than this many candidates. A longer list
#: is not a shortlist, and paging one at a terminal is how the wrong chunk gets
#: picked.
MAX_CANDIDATES = 12


def find_by_printed_number(
    chunks: list[Chunk], paper_id: str, printed_number: str
) -> list[Chunk]:
    """*Fetch the chunk printed as 8.2.* The lookup the audit found missing.

    Returns every match rather than one, and the caller refuses on more than
    one. ``printed_number`` is not unique by construction: it is extracted per
    chunk on the ar5iv/LaTeXML path only, a paper can print "8.2" in an
    appendix as well as a body, and a re-chunk can leave two chunks carrying
    it. Picking the first would be a coin flip wearing a lookup's clothes.
    """
    wanted = printed_number.strip()
    if not wanted:
        # `(c.printed_number or "") == ""` would otherwise match every chunk
        # the chunker could not number -- which on the textbook and MinerU
        # paths is ALL of them. An empty locator selecting the whole notebook
        # is the worst possible answer to it.
        return []
    return [
        c for c in chunks
        if c.paper_id == paper_id and (c.printed_number or "").strip() == wanted
    ]


def find_by_text(
    chunks: list[Chunk], paper_id: str, needle: str, norm_text
) -> list[Chunk]:
    """Chunks whose normalized body contains the normalized ``needle``.

    A SELECTION aid for a human at a terminal, and never a resolution rung:
    the output is a list to read, and this tool will not mint from it without
    a ``--chunk-id``. Containment is used rather than a similarity score for
    the same reason the resolver does — a number here would suggest a ranking
    that nothing computed.
    """
    key = norm_text(needle)
    if not key:
        return []
    return [
        c for c in chunks
        if c.paper_id == paper_id and key in norm_text(c.body_text)
    ]


def build_entry(
    chunk: Chunk,
    *,
    scheme: str,
    work_id: str,
    source_version: str | None,
    notebook: str,
    corpus_version: int,
    corpus_manifest_content_hash: str,
    quote_sha256,
    minted_at: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """The candidate fragment. Every machine-knowable field, and no others."""
    now = datetime.now(UTC)
    unresolved = None
    resolution: dict[str, Any] | None = {
        "notebook": notebook,
        "chunk_id": chunk.chunk_id,
        # True by construction: `quote` IS this chunk's body, so the digest
        # matches. Recorded as the rung it is rather than left null, so the
        # resolver's rung 1 has a hint to try first.
        "matched_by": "quote_sha256",
        "corpus_manifest_content_hash": corpus_manifest_content_hash,
        "corpus_version": corpus_version,
        "observed_at": observed_at or now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if not corpus_manifest_content_hash:
        # An adopter with no arXMCP running still mints; the schema makes
        # `mint_resolution` nullable-with-a-reason for exactly this. A
        # resolution stamped with a manifest hash nobody computed would be
        # worse than none: the topic repo's F-02 compares that field.
        resolution = None
        unresolved = (
            "the corpus manifest hash could not be computed, so no "
            "mint-time resolution is recorded; the entry is minted on the "
            "chunk text alone"
        )
    return {
        "kind": None,
        "title": None,
        "informal": None,
        "source": {
            "scheme": scheme,
            "id": work_id,
            "version": source_version,
            "printed_number": chunk.printed_number,
            "locator": None,
        },
        "quote_mode": "verbatim",
        "quote": chunk.body_text,
        "quote_norm": "nfc-ws-collapse/1",
        "quote_sha256": quote_sha256(chunk.body_text),
        "mint_resolution": resolution,
        "mint_unresolved_reason": unresolved,
        "depends_on": [],
        "frontier": [],
        "minted_at": (minted_at or now.strftime("%Y-%m-%d")),
        "minted_by": None,
        "supersedes": None,
        "superseded_by": None,
    }


def _registry_id(registry_path: Path | None) -> str | None:
    """The topic registry's 12-hex id, so the suggested key has the right prefix."""
    if registry_path is None:
        return None
    if not registry_path.is_file():
        raise StatementToolError(f"no registry at {registry_path}")
    doc = json.loads(registry_path.read_text(encoding="utf-8"))
    value = doc.get("registry_id")
    return value if isinstance(value, str) else None


def _describe(chunk: Chunk) -> str:
    body = " ".join(chunk.body_text.split())
    head = body[:110] + ("…" if len(body) > 110 else "")
    printed = chunk.printed_number or "-"
    return f"  {chunk.chunk_id}  printed={printed}  {head}"


def _select(
    chunks: list[Chunk],
    *,
    paper_id: str | None,
    chunk_id: str | None,
    printed_number: str | None,
    search: str | None,
    norm_text,
) -> Chunk:
    """Resolve the operator's locator to exactly one chunk, or refuse.

    Ambiguity is never broken here. Every path that can return several prints
    them and exits 1, because the whole value of a mint is that a human looked
    at the statement they are binding a key to.
    """
    if chunk_id:
        for chunk in chunks:
            if chunk.chunk_id == chunk_id:
                return chunk
        raise StatementToolError(
            f"no chunk {chunk_id!r} in this notebook. chunk_ids rotate on any "
            f"parse change and merge_insert has no delete arm, so an id from "
            f"an older run can be gone without anything having failed."
        )

    if paper_id is None:
        raise StatementToolError("--paper is required unless --chunk-id is given")
    in_paper = [c for c in chunks if c.paper_id == paper_id]
    if not in_paper:
        raise StatementToolError(
            f"paper_id {paper_id!r} has no chunks in this notebook — nothing "
            f"to mint from. Ingest it first, or check the id shape (the "
            f"corpus stores the BARE id: `math/0212237`, not `arxiv:…`)."
        )

    if printed_number:
        matches = find_by_printed_number(chunks, paper_id, printed_number)
        if not matches:
            with_numbers = sum(1 for c in in_paper if c.printed_number)
            raise StatementToolError(
                f"no chunk of {paper_id!r} is printed {printed_number!r}. "
                f"{with_numbers} of {len(in_paper)} chunks carry a "
                f"printed_number at all — it is extracted only on the "
                f"ar5iv/LaTeXML path, and the textbook and MinerU paths never "
                f"populate it. Try --search."
            )
    elif search:
        matches = find_by_text(chunks, paper_id, search, norm_text)
        if not matches:
            raise StatementToolError(
                f"no chunk of {paper_id!r} contains that text. The comparison "
                f"is whitespace- and NFC-insensitive, so this is a real "
                f"absence rather than a formatting mismatch."
            )
    else:
        raise StatementToolError(
            "give one of --chunk-id, --printed-number or --search"
        )

    if len(matches) == 1:
        return matches[0]
    print(
        f"{len(matches)} chunks match; this tool will not pick one. "
        f"Re-run with --chunk-id:",
        file=sys.stderr,
    )
    for chunk in matches[:MAX_CANDIDATES]:
        print(_describe(chunk), file=sys.stderr)
    if len(matches) > MAX_CANDIDATES:
        print(f"  … and {len(matches) - MAX_CANDIDATES} more; narrow the search.",
              file=sys.stderr)
    raise StatementToolError("ambiguous locator")


def run(
    *,
    notebook: str,
    paper: str | None,
    chunk_id: str | None,
    printed_number: str | None,
    search: str | None,
    label: str | None,
    registry: Path | None,
    source_version: str | None,
    notebooks_base: Path | None = None,
) -> int:
    from server.documents_store import DOCUMENTS_DB_FILENAME
    from tools._notebook_common import notebook_dir, notebook_lancedb_path
    from tools.statement_resolve import _manifest_hash

    norm_text, quote_sha256, _ = require_mfc()
    registry_id = _registry_id(registry)

    lancedb_dir = notebook_lancedb_path(notebook, base=notebooks_base)
    chunks = load_chunks(lancedb_dir)
    paper_id = paper
    chunk = _select(
        chunks, paper_id=paper_id, chunk_id=chunk_id,
        printed_number=printed_number, search=search, norm_text=norm_text,
    )
    work_id = chunk.paper_id
    scheme = "textbook" if work_id.startswith("textbook:") else "arxiv"
    if scheme == "textbook":
        work_id = work_id.removeprefix("textbook:")

    version = source_version
    if version is None and scheme == "arxiv":
        documents_db = (
            notebook_dir(notebook, base=notebooks_base) / DOCUMENTS_DB_FILENAME
        )
        version = read_document_versions(documents_db).get(chunk.paper_id) or None

    entry = build_entry(
        chunk,
        scheme=scheme,
        work_id=work_id,
        source_version=None if scheme == "textbook" else version,
        notebook=notebook,
        corpus_version=read_corpus_version(lancedb_dir),
        corpus_manifest_content_hash=_manifest_hash(notebooks_base),
        quote_sha256=quote_sha256,
    )

    key = (
        f"stmt:{registry_id}:{label}" if registry_id and label
        else "stmt:<registry_id>:<label>"
    )
    print(json.dumps({key: entry}, indent=2, ensure_ascii=False))

    owed = list(HUMAN_OWNED)
    if scheme == "arxiv" and entry["source"]["version"] is None:
        owed.append(
            "source.version — documents.arxiv_version is '' for this work, so "
            "the corpus cannot say which revision it holds. Run "
            "tools/notebook_arxiv_version_backfill.py, or pass "
            "--source-version. A bare arXiv id resolves to LATEST and silently "
            "drifts, which is why the schema requires one"
        )
    if not registry_id:
        owed.append(
            "the key — this tool minted no identity (ADR-0002). Pass "
            "--registry to have the registry_id filled in, and type the label "
            "yourself"
        )
    print(
        f"\n{len(owed)} field(s) are yours, and are null above so this fragment "
        f"FAILS `mfc registry validate` until you fill them. A placeholder "
        f"string would have passed:",
        file=sys.stderr,
    )
    for item in owed:
        print(f"  - {item}", file=sys.stderr)
    print(
        "\nDo not edit `quote`. It is byte-equal to the chunk and is what "
        "quote_sha256 hashes; a correction there breaks exact match forever. "
        "Corrections go in `quote_as_read`, which is displayed and never "
        "hashed.",
        file=sys.stderr,
    )
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--notebook", required=True, help="notebook slug")
    parser.add_argument(
        "--paper",
        help="paper_id as the corpus stores it: the BARE id (`math/0212237`) "
             "or `textbook:<slug>`",
    )
    parser.add_argument("--chunk-id", help="exact chunk id; skips the lookup")
    parser.add_argument(
        "--printed-number",
        help="the rendered theorem number ('8.2'); needs --paper",
    )
    parser.add_argument(
        "--search",
        help="substring of the statement, whitespace/NFC-insensitive; "
             "needs --paper. LISTS candidates, never picks one",
    )
    parser.add_argument(
        "--label",
        help="the local label you intend to mint ('bridgeland2007.lem-8.2'). "
             "Used only to render a suggested key",
    )
    parser.add_argument(
        "--registry", type=Path,
        help="the topic repo's registry/<slug>.json, read ONLY for its "
             "registry_id so the suggested key has the right prefix",
    )
    parser.add_argument(
        "--source-version",
        help="the arXiv version this statement is from ('v3'), when you know "
             "it and the corpus does not",
    )
    parser.add_argument("--notebooks-base", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        return run(
            notebook=args.notebook,
            paper=args.paper,
            chunk_id=args.chunk_id,
            printed_number=args.printed_number,
            search=args.search,
            label=args.label,
            registry=args.registry,
            source_version=args.source_version,
            notebooks_base=args.notebooks_base,
        )
    except StatementToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
