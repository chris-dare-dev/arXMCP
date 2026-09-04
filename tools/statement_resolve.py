"""The resolution ladder — does this registry entry's quote still appear, and where?

Lands derived-alg-geo-lean **#170** (epic #134). Offline, read-only, on the
ingest plane, which is what ``CLAUDE.md`` §4.8 rule 2 permits. It writes one
file, ``resolution/1.0``, which a human commits into the TOPIC repo. It never
writes corpus state, never touches the topic repo, and is never called at
request time (ADR-0001: the seam is cold).

arXMCP answers exactly one question here and no other. Not "is this
formalization correct", not "does this declaration elaborate" — only *does
this quote still appear in the corpus, and where*.

## The ladder, which never guesses

1. ``mint_resolution.chunk_id`` — fetch that chunk, recompute the normalized
   body digest, accept **only on match**. A chunk-id rotation invalidates the
   cache; it never corrupts the answer, because the id is only ever a hint
   about where to look first.
2. Scan the paper's chunks for the same digest → ``matched_by: quote_sha256``.
3. ``matched_by: quote_containment`` — the chunk body CONTAINS the normalized
   quote. This is the rung that survives a re-chunk which merges or splits the
   statement's chunk, and it reads ``current`` because containment is an
   identity claim: the statement is in the chunk or it is not.
4. ``printed_number`` → a HINT only, and the schema forces it to ``drifted``.
   Authors renumber between versions, and the field is populated only on the
   ar5iv/LaTeXML path.
5. Otherwise ``unresolvable``, with the reason.

**``fuzzy`` is not implemented, deliberately.** The schema permits the value
and forbids it from ever reading ``current``; there is no nearest-neighbour
rung here at all, because the only thing a similarity score could add to this
file is a number that invites the reading it is not allowed to have.

## The version guard

**No result is ``current`` for a versioned entry while the corpus cannot say
which version it holds.** ``documents.arxiv_version`` is ``''`` for every row
in both live notebooks — the seed line is the column's only source and none of
the 79 seed lines carries an ``@vN``. Meanwhile ``notebook_fetch`` pulls ar5iv
for the bare id, which is arXiv **latest**. So a byte-equal match against
those bytes, written up as ``current`` for an entry declaring ``version: v3``,
asserts a v3 pin confirmed by bytes of unknown version.

Such a result is ``not_applicable`` — never a pass, never a fail, the same
value ``CLAUDE.md`` §4.10 rule 3 already binds for a foreign environment. The
guard is unconditional on #171's backfill landing and stays correct after it
does: a row that still reads ``''`` post-backfill is exactly a row whose
version could not be established. It also fires the other way — a corpus that
DOES name v4 while the entry pins v3 cannot confirm the v3 pin either, and
gets its own reason.

Usage::

    uv run python -m tools.statement_resolve \\
        --registry ../derived-alg-geo-lean/registry/bridgeland2007.json \\
        --notebook bridgeland-stability \\
        --out ../derived-alg-geo-lean/attest/resolution.json

Exit codes:
    0 — a resolution was written (whatever it says; a corpus that moved is a
        finding for the topic repo's freshness gate, not an error here)
    1 — a precondition failed: no such notebook, no registry, `mfc` absent,
        or the document this tool produced does not validate
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools._statement_common import (
    Chunk,
    StatementToolError,
    by_paper,
    corpus_paper_id,
    load_chunks,
    read_corpus_version,
    read_document_versions,
    require_mfc,
    validate_against,
)

#: Recorded in every resolution so a future reader can tell which ladder
#: produced it. Bumped when a rung's SEMANTICS change, not when this file is
#: edited — the field exists to explain a verdict, not to track commits.
RESOLVER_VERSION = "arxmcp/statement_resolve.py@1.0.0"

#: Rung labels. Internal to this module — the artifact never sees them; it
#: sees ``matched_by``, which is coarser because two of these rungs make the
#: same identity claim and differ only in how the chunk was found.
_RUNG_MINT_HINT = "mint_hint"
_RUNG_PAPER_SCAN = "paper_scan"
_RUNG_NO_HINT = "no_hint"
_RUNG_CONTAINMENT = "containment"
_RUNG_PRINTED = "printed_number"
_RUNG_NONE = "none"

#: What a `current` result says about HOW it was found. `None` for the
#: uneventful case: the mint-time hint still addressed the statement, so there
#: is nothing to explain and a sentence saying so would be noise in every row.
_CURRENT_REASON: dict[str, str | None] = {
    _RUNG_MINT_HINT: None,
    _RUNG_PAPER_SCAN: (
        "The mint-time chunk_id no longer addresses this statement; found by "
        "scanning the paper's chunks. The id rotated, the identity did not."
    ),
    _RUNG_NO_HINT: (
        "Found by scanning the paper's chunks. This entry carries no "
        "mint_resolution, so there was no cached chunk_id to try first — that "
        "is the entry's mint_unresolved_reason, not a drift signal."
    ),
    _RUNG_CONTAINMENT: (
        "The chunk boundaries moved and the quote is no longer a whole chunk, "
        "but it is still present in one. Current by containment rather than by "
        "byte-equality."
    ),
}

#: The six states a result can be in, in the order the summary prints them.
_COUNT_KEYS = (
    "current", "drifted", "unresolvable", "paper_absent",
    "not_applicable", "not_run",
)


def _utc_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _result(
    key: str,
    resolution: str,
    matched_by: str,
    *,
    chunk_id: str | None = None,
    matched_body_sha256: str | None = None,
    printed_number: str | None = None,
    resolved_source_version: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """One ``resolution/1.0`` result row.

    ``similarity`` is hard-wired to ``None`` and takes no parameter. The only
    rung that could produce a number is ``fuzzy``, which this resolver does
    not implement; leaving the argument available would be an invitation.
    """
    return {
        "key": key,
        "resolution": resolution,
        "matched_by": matched_by,
        "chunk_id": chunk_id,
        "resolved_source_version": resolved_source_version,
        "matched_body_sha256": matched_body_sha256,
        "printed_number": printed_number,
        "similarity": None,
        "reason": reason,
    }


def _body_digest(norm_text: Callable[[str], str], body: str) -> str:
    """The chunk body's digest under the registry's own normalization.

    Byte-identical construction to ``mfc.digest.quote_sha256``, and it must
    stay that way: ``quote_sha256`` on the entry side and this on the corpus
    side are the two halves of one comparison.
    """
    return hashlib.sha256(norm_text(body).encode("utf-8")).hexdigest()


def _version_verdict(
    entry_version: str | None,
    corpus_version: str,
) -> str | None:
    """``None`` if a ``current`` verdict is honest here, else the reason it is not.

    Three cases, and only the first permits ``current``:

    * the entry pins no version (``textbook:``, or an unversioned ``doi``) —
      there is nothing to confirm, so nothing to withhold;
    * the entry pins ``vN`` and the corpus names the same ``vN``;
    * anything else.

    The `arxiv` scheme always pins a version — the registry schema requires
    it, because a bare arXiv id resolves to LATEST and silently drifts.
    """
    if not entry_version:
        return None
    if not corpus_version:
        return (
            f"The quote was found in the corpus, but this entry pins "
            f"source.version {entry_version} and documents.arxiv_version is "
            f"'' for this work. notebook_fetch pulls ar5iv for the bare id — "
            f"arXiv LATEST — so calling this `current` would assert a "
            f"{entry_version} pin confirmed by bytes of unknown version. "
            f"Tracked by derived-alg-geo-lean #171."
        )
    if corpus_version != entry_version:
        return (
            f"The quote was found, but in {corpus_version} of this work while "
            f"the entry pins {entry_version}. A match against a different "
            f"revision is not evidence for the pinned one, even when the "
            f"statement is unchanged between them."
        )
    return None


def resolve(
    registry: dict[str, Any],
    chunks: Sequence[Chunk],
    *,
    notebook: str,
    registry_sha256: str,
    corpus_version: int,
    corpus_manifest_content_hash: str,
    chunker_version: str,
    document_versions: dict[str, str],
    generated_at: str | None = None,
    norm_text: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """The pure core: registry + chunks in, ``resolution/1.0`` out.

    No I/O and no clock beyond ``generated_at``, so the whole ladder is
    testable against a synthetic fixture with no LanceDB, no models and no
    network — which is what lets this repo's first CI job be cheap.
    """
    if norm_text is None:
        norm_text, _, _ = require_mfc()
    grouped = by_paper(chunks)
    results: list[dict[str, Any]] = []

    for key in sorted(registry.get("entries", {})):
        entry = registry["entries"][key]
        source = entry.get("source") or {}
        entry_version = source.get("version")
        paper_id = corpus_paper_id(source)

        if paper_id is None:
            results.append(_result(
                key, "not_run", "none",
                reason=(
                    f"source.scheme {source.get('scheme')!r} has no corpus "
                    f"coordinate; this corpus indexes arXiv ids and textbook "
                    f"slugs. Nothing was looked up, so nothing is claimed."
                ),
            ))
            continue

        quote = entry.get("quote")
        quote_hash = entry.get("quote_sha256")
        if quote is None and not quote_hash:
            results.append(_result(
                key, "not_run", "none",
                reason=(
                    f"kind=={entry.get('kind')!r} carries neither a quote nor "
                    f"a quote_sha256; there is no text to look for."
                ),
            ))
            continue

        paper_chunks = grouped.get(paper_id)
        if not paper_chunks:
            results.append(_result(
                key, "paper_absent", "none",
                reason=(
                    f"paper_id {paper_id!r} has no chunks in notebook "
                    f"{notebook!r}. The statement was not looked for, because "
                    f"the paper it is in was never ingested here."
                ),
            ))
            continue

        corpus_ver = document_versions.get(paper_id, "")
        matched, matched_by, rung = _walk_ladder(
            entry, paper_chunks, quote, quote_hash, notebook, norm_text
        )

        if matched is None:
            results.append(_result(
                key, "unresolvable", "none",
                resolved_source_version=corpus_ver or None,
                reason=(
                    f"No chunk of {paper_id!r} carries this quote by digest or "
                    f"by containment, and no printed_number matches. The "
                    f"statement is not in this corpus version under any rung "
                    f"the ladder will accept."
                ),
            ))
            continue

        digest = _body_digest(norm_text, matched.body_text)
        if matched_by == "printed_number":
            results.append(_result(
                key, "drifted", "printed_number",
                chunk_id=matched.chunk_id,
                matched_body_sha256=digest,
                printed_number=matched.printed_number,
                resolved_source_version=corpus_ver or None,
                reason=(
                    f"Matched only on printed_number {matched.printed_number!r}. "
                    f"That is a HINT, never an identity: authors renumber "
                    f"between versions. The quote itself no longer appears."
                ),
            ))
            continue

        withheld = _version_verdict(entry_version, corpus_ver)
        if withheld is not None:
            results.append(_result(
                key, "not_applicable", matched_by,
                chunk_id=matched.chunk_id,
                matched_body_sha256=digest,
                printed_number=matched.printed_number,
                resolved_source_version=None,
                reason=withheld,
            ))
            continue

        results.append(_result(
            key, "current", matched_by,
            chunk_id=matched.chunk_id,
            matched_body_sha256=digest,
            printed_number=matched.printed_number,
            resolved_source_version=corpus_ver or None,
            reason=_CURRENT_REASON[rung],
        ))

    counts = {k: sum(1 for r in results if r["resolution"] == k) for k in _COUNT_KEYS}
    return {
        "schema_version": "resolution/1.0",
        "registry_sha256": registry_sha256,
        "notebook": notebook,
        "corpus_version": corpus_version,
        "corpus_manifest_content_hash": corpus_manifest_content_hash,
        "resolver_version": RESOLVER_VERSION,
        "chunker_version": chunker_version,
        "generated_at": generated_at or _utc_iso(),
        "results": results,
        "counts": counts,
    }


def _walk_ladder(
    entry: dict[str, Any],
    paper_chunks: Sequence[Chunk],
    quote: str | None,
    quote_hash: str | None,
    notebook: str,
    norm_text: Callable[[str], str],
) -> tuple[Chunk | None, str, str]:
    """Rungs 1-4. Returns ``(chunk, matched_by, rung)``.

    ``rung`` is finer-grained than ``matched_by`` on purpose: rungs 1 and 2
    both report ``quote_sha256`` to the artifact — they are the same identity
    claim — but they are different stories about the cache, and a `current`
    result should not narrate a stale mint hint for an entry that never
    carried one.

    Split out so the ordering of the rungs is one readable list rather than a
    nest of early returns inside :func:`resolve`'s bookkeeping.
    """
    by_id = {c.chunk_id: c for c in paper_chunks}

    # Rung 1 — the mint-time hint, accepted ONLY on a recomputed match.
    mint = entry.get("mint_resolution")
    if mint and mint.get("notebook") == notebook and quote_hash:
        hinted = by_id.get(mint.get("chunk_id", ""))
        if hinted is not None and _body_digest(norm_text, hinted.body_text) == quote_hash:
            return hinted, "quote_sha256", _RUNG_MINT_HINT

    # Rung 2 — the same digest anywhere in the paper.
    if quote_hash:
        for chunk in paper_chunks:
            if _body_digest(norm_text, chunk.body_text) == quote_hash:
                return chunk, "quote_sha256", (
                    _RUNG_PAPER_SCAN if entry.get("mint_resolution")
                    else _RUNG_NO_HINT)

    # Rung 3 — containment. Needs the text, so `digest_only` entries stop at
    # rung 2 by construction; that cost is stated in the registry schema's
    # `quote_mode` comment and is not worked around here.
    if quote is not None:
        needle = norm_text(quote)
        if needle:
            for chunk in paper_chunks:
                if needle in norm_text(chunk.body_text):
                    return chunk, "quote_containment", _RUNG_CONTAINMENT

    # Rung 4 — printed_number, a hint that can only ever read `drifted`.
    printed = (entry.get("source") or {}).get("printed_number")
    if printed:
        for chunk in paper_chunks:
            if chunk.printed_number == printed:
                return chunk, "printed_number", _RUNG_PRINTED

    return None, "none", _RUNG_NONE


def _chunker_version(chunks: Sequence[Chunk]) -> str:
    """What actually produced these rows, not what this checkout would produce.

    Read off the chunks rather than imported from
    ``ingest.chunker_types.CHUNKER_VERSION``, because the constant describes
    the code on this machine today and the resolution describes bytes written
    at ingest time, possibly by an older chunker. A notebook chunked by two
    versions says so.
    """
    seen = sorted({c.chunker_version for c in chunks if c.chunker_version})
    if not seen:
        return "unknown"
    return seen[0] if len(seen) == 1 else "mixed:" + ",".join(seen)


def run(
    registry_path: Path,
    *,
    notebook: str,
    out_path: Path | None,
    notebooks_base: Path | None = None,
) -> int:
    """Load, resolve, validate, write. Returns an exit code."""
    from server.documents_store import DOCUMENTS_DB_FILENAME
    from tools._notebook_common import notebook_dir, notebook_lancedb_path

    norm_text, _, _ = require_mfc()

    if not registry_path.is_file():
        raise StatementToolError(f"no registry at {registry_path}")
    raw = registry_path.read_bytes()
    registry = json.loads(raw.decode("utf-8"))
    # Hashed over the FILE BYTES, not a re-serialization. This is the entire
    # cross-repo freshness mechanism (`mfc check-resolution` F-01): the topic
    # repo compares it against its own `sha256sum registry/<slug>.json`, so a
    # canonicalizing round-trip here would make every comparison fail.
    registry_sha256 = hashlib.sha256(raw).hexdigest()

    lancedb_dir = notebook_lancedb_path(notebook, base=notebooks_base)
    chunks = load_chunks(lancedb_dir)
    corpus_version = read_corpus_version(lancedb_dir)
    documents_db = notebook_dir(notebook, base=notebooks_base) / DOCUMENTS_DB_FILENAME
    document_versions = read_document_versions(documents_db)

    document = resolve(
        registry,
        chunks,
        notebook=notebook,
        registry_sha256=registry_sha256,
        corpus_version=corpus_version,
        corpus_manifest_content_hash=_manifest_hash(notebooks_base),
        chunker_version=_chunker_version(chunks),
        document_versions=document_versions,
        norm_text=norm_text,
    )
    validate_against(document, "resolution-1.0")

    rendered = json.dumps(document, indent=2) + "\n"
    if out_path is None:
        sys.stdout.write(rendered)
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
        print(f"wrote {out_path}")

    counts = document["counts"]
    print(
        "  " + "  ".join(f"{k}={counts[k]}" for k in _COUNT_KEYS),
        file=sys.stderr,
    )
    if counts["not_applicable"]:
        print(
            f"  note: {counts['not_applicable']} entr"
            f"{'y' if counts['not_applicable'] == 1 else 'ies'} matched in the "
            f"corpus but could not be certified against the version they pin. "
            f"That is neither a pass nor a fail; see each result's reason.",
            file=sys.stderr,
        )
    return 0


def _manifest_hash(notebooks_base: Path | None) -> str:
    """``arxmcp://corpus-manifest``'s ``content_hash``, computed offline.

    Built through a read-only stand-in for :class:`NotebooksStore` that
    supplies the one method ``build_manifest`` calls. Opening the real store
    would run the v0->v1 migration — including its unconditional ``DROP
    TABLE`` — on the operator's only copy of ``notebooks.db``, from a command
    whose whole job is to read. Same rectification
    ``tools/notebook_list_offline.py`` already carries.
    """
    import asyncio
    import sqlite3 as _sqlite3

    from server.corpus_manifest import build_manifest
    from server.operator_settings import DEFAULT_DB_PATH

    class _ReadOnlyNotebooks:
        """Exactly the surface ``build_manifest`` touches: ``list_notebooks``."""

        def __init__(self, db_path: Path) -> None:
            self._db_path = db_path

        async def list_notebooks(self) -> list[dict[str, str]]:
            if not self._db_path.is_file():
                return []
            uri = f"file:{self._db_path.as_posix()}?mode=ro"
            conn = _sqlite3.connect(uri, uri=True)
            try:
                rows = conn.execute("SELECT slug FROM notebooks ORDER BY slug").fetchall()
            except _sqlite3.OperationalError:
                return []
            finally:
                conn.close()
            return [{"slug": slug} for (slug,) in rows]

    async def _build() -> str:
        manifest = await build_manifest(
            _ReadOnlyNotebooks(DEFAULT_DB_PATH),  # type: ignore[arg-type]
            base=notebooks_base,
        )
        return manifest["content_hash"]

    try:
        return asyncio.run(_build())
    except Exception as exc:  # noqa: BLE001
        # A manifest this tool could not build must not be silently replaced
        # by a plausible-looking constant: the topic repo's F-02 compares this
        # field to decide whether the corpus moved, and a fabricated value
        # would read as "it did not".
        raise StatementToolError(
            f"could not compute the corpus manifest hash ({type(exc).__name__}: "
            f"{exc}). The resolution's freshness gate depends on it, so no "
            f"file was written."
        ) from exc


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--registry", type=Path, required=True,
        help="path to the topic repo's registry/<work-slug>.json",
    )
    parser.add_argument(
        "--notebook", required=True,
        help="notebook slug to resolve against",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help=(
            "where to write resolution/1.0 (default: stdout). The topic repo "
            "commits this at attest/resolution.json."
        ),
    )
    parser.add_argument(
        "--notebooks-base", type=Path, default=None,
        help="notebooks base dir (default: var/arxmcp/notebooks/)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        return run(
            args.registry,
            notebook=args.notebook,
            out_path=args.out,
            notebooks_base=args.notebooks_base,
        )
    except StatementToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
