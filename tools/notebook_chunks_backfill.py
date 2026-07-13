"""Backfill chunks-schema-v2 columns on a notebook's LanceDB table (source-truth-m2).

Hydrates the five source-truth-m2 columns
(``source_revision_id`` / ``source_span`` / ``truncated`` / ``printed_number``
/ ``license_ref``) on the EXISTING rows of a notebook's ``chunks`` LanceDB
table, WITHOUT re-embedding a single chunk. Per paper it:

- re-runs the chunker's structural extraction on
  ``var/arxmcp/corpus/parsed/<paper_id>/index.html`` to reproduce the fresh
  ``chunk_id -> ChunkRecord`` map (``truncated`` exact, ``printed_number``
  from the m2 extractor), and
- joins ``source_revision_id`` / ``license_ref`` from the per-notebook
  documents registry (source-truth-m1, ``documents.db``) by grouping
  ``DocumentsStore.all_records()`` on ``work_id`` and matching the chunk's
  (already version-stripped) ``paper_id``,

then patches the five columns onto the in-memory row dicts and writes them back
with ONE ``merge_insert("chunk_id").when_matched_update_all()
.when_not_matched_insert_all()`` per notebook — a full-row read-modify-write
that leaves every other column (crucially ``embedding_stmt`` /
``embedding_proof``) byte-identical. This mirrors the shipped
``ingest/embed_equations.py`` write mechanism.

**0-re-embed is STRUCTURAL, not incidental.** This driver never imports
``ingest.store`` (its ``_build_arrow_table`` hard-requires an embedding per
chunk_id) nor ``ingest.embedder`` (the BGE-M3 model). It connects to LanceDB
directly and re-invokes the chunker's extraction functions — which load the
BGE-M3 *tokenizer* only (``ingest.chunker._get_tokenizer``, documented as NOT
loading model weights), never the model. No forward pass ever runs, so
"0 chunks re-embedded" holds by construction (asserted by an import-scan test
in ``tests/test_notebook_chunks_backfill.py``). The self-contained schema-v2
``add_columns`` step below deliberately re-mirrors the SQL defaults from
``ingest.store._TEXTBOOK_MIGRATION_DEFAULTS`` rather than importing them, for
the same reason ``ingest.store`` must stay out of this import graph.

**Abstention is first-class (CLAUDE.md §4.9).** A chunk whose ``chunk_id`` the
current chunker does not reproduce (or whose paper's re-chunk raised, or whose
parsed HTML is missing, or whose paper is unregistered / multi-row in the
registry) gets ``source_span=null`` (and ``printed_number=null`` when the miss
is HTML/chunk-id-shaped), counted AND listed by reason code in a per-notebook
report, never a best-guess anchor and never a silent null. ``truncated`` is the
one column with no null path: exact on a chunk-id hit, else a safe-direction
token recount (``kind="proof"`` is always False; every other kind is
``token_count >= STMT_MAX_TOKENS``).

**Idempotency.** A paper whose rows already carry a non-null
``source_revision_id`` is skipped without re-invoking the chunker; a re-run over
a fully-hydrated notebook re-chunks nothing and writes nothing.

**The ``source_span`` ``id`` field.** The JSON ``id`` (a non-authoritative
debug hint, never a resolution key — spike-3) is emitted as ``""`` because a
``ChunkRecord`` does not carry the source element's HTML ``id`` attribute;
``rev`` (registry cross-check) and ``txt`` (the authoritative
NFC-normalized-body-text hash) are populated fully. Threading the element id
through the chunker is a tracked follow-up, out of m2's 5-column scope.

**SAFETY — never run against a live corpus table without owner OK.** Build and
smoke-test only against a COPY of a notebook's ``lancedb`` dir (and its
``documents.db`` sibling). The live-corpus hydration is the go-live, run by the
orchestrator post-rectify with owner sign-off and the same post-write
verification (row count unchanged, distinct chunk_id count unchanged,
embeddings ``np.array_equal`` pre/post).

Usage:

    uv run python tools/notebook_chunks_backfill.py <slug>

Exit codes:
    0 — completed (abstentions are a success state, surfaced in the report)
    1 — slug validation failed or the notebook has no ``chunks`` table
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import lancedb
import pyarrow as pa
from bs4 import BeautifulSoup, Tag

# Chunker internals — the SAME functions ``_chunk_paper_impl`` calls, reused so
# the re-chunk reproduces byte-identical chunk_ids. ``ingest.chunker`` imports
# no embedder at module load (its tokenizer + BGE_M3_COMMIT_SHA imports are
# function-local in ``_get_tokenizer``), so this import keeps the driver's
# 0-re-embed guarantee structural.
from ingest.chunker import (
    _THEOREM_CLASS_RE,
    PER_PAPER_FAILURE_EXCEPTIONS,
    STMT_MAX_TOKENS,
    _compute_chunk_id,
    _count_tokens,
    _extract_body_fallback_chunks,
    _extract_chunks_from_container,
    _extract_section_chunks,
    _resolve_preamble_doc,
)
from ingest.chunker_types import ChunkRecord
from ingest.tokenizer import tokenize_body
from server.documents_store import (
    DOCUMENTS_DB_FILENAME,
    DocumentRecord,
    DocumentsStore,
)
from tools._notebook_common import (
    CORPUS_PARSED_DIR,
    NotebookError,
    notebook_dir,
    notebook_lancedb_path,
    validate_slug,
)
from tools.oai_license import (
    LICENSE_STATUS_ELIGIBLE,
    LICENSE_STATUS_NOT_ALLOWLISTED_OPEN,
    LICENSE_STATUS_UNKNOWN,
)

logger = logging.getLogger("notebook_chunks_backfill")

# The LanceDB chunks table name. Literalized here (rather than imported from
# ``ingest.schema``) because ``ingest.schema`` does ``from ingest.embedder
# import EMBEDDING_DIM`` at module load — importing it would pull the embedder
# module into this driver's import graph and defeat the STRUCTURAL 0-re-embed
# guarantee. The name is stable; a rename is a one-line change here.
CHUNKS_TABLE_NAME = "chunks"

# The five source-truth-m2 columns and their NULL-default SQL for the
# self-contained schema-v2 ``add_columns`` step. DELIBERATELY duplicated from
# the source-truth-m2 entries in ``ingest.store._TEXTBOOK_MIGRATION_DEFAULTS``
# (not imported — see the module docstring / CHUNKS_TABLE_NAME note). Spike-4
# proved ``cast(NULL as boolean)`` rides the same single-loop mechanism, so no
# struct / schema-based ``add_columns`` branch is needed. Adding columns is a
# fragment-level metadata op that never rewrites the embedding columns.
_V2_COLUMN_DEFAULTS: dict[str, str] = {
    "source_revision_id": "cast(NULL as string)",
    "source_span": "cast(NULL as string)",
    "truncated": "cast(NULL as boolean)",
    "printed_number": "cast(NULL as string)",
    "license_ref": "cast(NULL as string)",
}

# The advisory license vocabulary the denormalized ``license_ref`` must be one
# of (source-truth-m1 3-way split). A registry row's ``license_status`` is
# always one of these by construction; the guard only logs on a surprise.
_LICENSE_REF_VOCAB = frozenset(
    {
        LICENSE_STATUS_ELIGIBLE,
        LICENSE_STATUS_NOT_ALLOWLISTED_OPEN,
        LICENSE_STATUS_UNKNOWN,
    }
)

# F2 per-paper sanity flag (spike-2): a paper with ZERO theorem-classed blocks
# but the rendered body mentions these theorem keywords >= the threshold is
# flagged as a possible total markup-path miss (old-style pre-\newtheorem
# papers). The threshold is a spike-2 judgment call the owner may override.
_F2_KEYWORDS = ("theorem", "lemma", "proposition", "corollary", "definition")
_F2_KEYWORD_THRESHOLD = 3

# Cap on the per-notebook (chunk_id, reason) null listing so a pathological run
# cannot flood stderr. The expected null count is small (chunker_version is
# uniform across the live corpus); a cap this high still lists every miss on a
# healthy run while bounding a degenerate one.
_NULL_LIST_CAP = 500


# ---------------------------------------------------------------------------
# source_span / truncated / revision-id helpers
# ---------------------------------------------------------------------------


def _revision_id(rec: DocumentRecord) -> str:
    """``f"{work_id}@{arxiv_version}"`` or the bare ``work_id`` when unversioned.

    Byte-identical to ``tools.notebook_documents_backfill._label`` so the value
    round-trips to ``(work_id, arxiv_version)`` via ``rsplit("@", 1)`` (arXiv
    ids never contain ``@``).
    """
    if rec.arxiv_version:
        return f"{rec.work_id}@{rec.arxiv_version}"
    return rec.work_id


def _normalized_text_hash(body_text: str) -> str:
    """The authoritative ``source_span`` ``txt`` key.

    ``sha256(NFC(whitespace-collapsed body_text))`` — a PURE function of the
    stored ``body_text`` column (spike-3's paragraph-grain resolving key). The
    whitespace collapse mirrors ``_element_text``'s own ``" ".join(split())``;
    the NFC step matches the ``_compute_chunk_id`` cross-host discipline so the
    hash is stable even when the HTML parser emitted NFD bytes.
    """
    collapsed = " ".join(body_text.split())
    normalized = unicodedata.normalize("NFC", collapsed)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _source_span_json(rev16: str, body_text: str, element_id: str = "") -> str:
    """Byte-stable JSON string for the ``source_span`` column.

    ``json.dumps(sort_keys=True, separators=(",", ":"))`` for deterministic
    bytes (BP1). ``element_id`` is a non-authoritative debug hint (currently
    always ``""`` — a ChunkRecord does not expose the source element id).
    """
    return json.dumps(
        {
            "id": element_id,
            "rev": rev16,
            "txt": _normalized_text_hash(body_text),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _truncated_fallback(
    kind: str, body_text: str, *, count_tokens=_count_tokens
) -> bool:
    """Safe-direction ``truncated`` recompute for a chunk-id MISS (Column 4).

    ``kind == "proof"`` -> ``False`` unconditionally (proof windows are never
    truncated, by construction of ``_window_proof_text``). Every other kind ->
    ``token_count(body_text) >= STMT_MAX_TOKENS``. One-directional: it can only
    mis-flag a coincidentally-max-length COMPLETE statement as
    possibly-truncated (a conservative false positive), never report truncated
    content as complete — truncation always leaves ``>= max_tokens`` tokens, so
    the ``< budget`` "definitely complete" branch is airtight. ``count_tokens``
    is a test seam (loads the BGE-M3 tokenizer only).
    """
    if kind == "proof":
        return False
    return count_tokens(body_text) >= STMT_MAX_TOKENS


# ---------------------------------------------------------------------------
# Per-paper re-chunk (mirrors _chunk_paper_impl WITHOUT the JSON side effect)
# ---------------------------------------------------------------------------


@dataclass
class _RechunkResult:
    """Outcome of re-chunking one paper.

    ``status`` is ``"ok"`` (``records`` populated), ``"html_missing"`` (no
    ``parsed/<id>/index.html``), or ``"rerun_failed"`` (a
    PER_PAPER_FAILURE_EXCEPTIONS during extraction). ``f2_suspected`` is the
    spike-2 per-paper sanity flag.
    """

    status: str
    records: dict[str, ChunkRecord] = field(default_factory=dict)
    f2_suspected: bool = False


def _detect_f2(soup: BeautifulSoup) -> bool:
    """spike-2 F2 sanity flag: zero theorem-classed blocks AND the rendered
    body mentions theorem keywords >= threshold (a likely total markup miss)."""

    def _is_theorem_class(c) -> bool:
        return isinstance(c, str) and _THEOREM_CLASS_RE.match(c) is not None

    if soup.find_all(True, class_=_is_theorem_class):
        return False
    text = soup.get_text(" ")
    total = 0
    for kw in _F2_KEYWORDS:
        total += len(re.findall(rf"\b{kw}\b", text, flags=re.IGNORECASE))
    return total >= _F2_KEYWORD_THRESHOLD


def _rechunk_paper(
    paper_id: str, parsed_root: Path, *, resolve_preamble
) -> _RechunkResult:
    """Reproduce the fresh ``chunk_id -> ChunkRecord`` map for one paper.

    Mirrors ``ingest.chunker._chunk_paper_impl`` up through ``chunk_id``
    assignment (both structural passes + the section-less fallback + preamble
    resolution + BM25 tokenization + the content-addressable ``chunk_id`` +
    the keep-first dedup) but DELIBERATELY omits the per-chunk JSON write, so a
    backfill re-chunk never mutates the ``var/arxmcp/corpus/chunks`` tree.

    ``resolve_preamble`` is a test seam defaulting (in ``run``) to
    ``ingest.chunker._resolve_preamble_doc`` — the exact function the real
    chunker uses, which for an already-ingested paper short-circuits to the
    cached ``preamble.json`` (read-only) and returns ``None`` (empty preamble)
    when raw ``.tex`` is absent, so re-chunk reproduces the original chunk_ids.
    """
    parsed_html = parsed_root / paper_id / "index.html"
    if not parsed_html.is_file():
        return _RechunkResult(status="html_missing")
    try:
        html_bytes = parsed_html.read_bytes()
        soup = BeautifulSoup(html_bytes, "html.parser")
        body = soup.find("body")
        root: Tag = body if isinstance(body, Tag) else soup  # type: ignore[assignment]

        counter = [0]
        theorem_chunks = _extract_chunks_from_container(root, paper_id, counter)
        section_chunks = _extract_section_chunks(soup, paper_id, counter)
        all_chunks = theorem_chunks + section_chunks
        if not all_chunks:
            all_chunks = _extract_body_fallback_chunks(root, paper_id, counter)

        preamble_doc = resolve_preamble(paper_id)
        if preamble_doc is not None:
            for chunk in all_chunks:
                chunk.preamble_ref = preamble_doc.preamble_hash
        for chunk in all_chunks:
            chunk.body_tokens = tokenize_body(chunk.body_text)
        preamble_text = (
            preamble_doc.preamble_text if preamble_doc is not None else ""
        )

        records: dict[str, ChunkRecord] = {}
        for chunk in all_chunks:
            chunk.chunk_id = _compute_chunk_id(
                paper_id, preamble_text, chunk.body_text
            )
            # keep-first on a duplicate chunk_id, mirroring _chunk_paper_impl's
            # dedup of byte-identical content (BM25 + embeddings are identical
            # for identical content, so the drop is safe and deterministic).
            records.setdefault(chunk.chunk_id, chunk)

        return _RechunkResult(
            status="ok", records=records, f2_suspected=_detect_f2(soup)
        )
    except PER_PAPER_FAILURE_EXCEPTIONS as exc:
        # Mirror the chunker's own resilience envelope: a malformed paper is a
        # per-paper abstention, not a crash that aborts the notebook backfill.
        # Programmer bugs (AttributeError, KeyError, ...) still propagate.
        logger.warning("[%s] re-chunk failed: %s", paper_id, exc)
        return _RechunkResult(status="rerun_failed")


# ---------------------------------------------------------------------------
# Registry load + schema-v2 ensure
# ---------------------------------------------------------------------------


def _load_registry(db_path: Path) -> dict[str, list[DocumentRecord]]:
    """Group the notebook's ``documents.db`` rows by ``work_id``.

    Read-only: an absent ``documents.db`` yields an empty registry (every
    chunk then abstains as ``registry_missing``) — we do NOT create the store,
    which would write an empty DB as a side effect.
    """
    if not db_path.is_file():
        return {}

    async def _load() -> list[DocumentRecord]:
        store = await DocumentsStore.open(db_path)
        try:
            return await store.all_records()
        finally:
            await store.close()

    by_work: dict[str, list[DocumentRecord]] = defaultdict(list)
    for rec in asyncio.run(_load()):
        by_work[rec.work_id].append(rec)
    return by_work


def _ensure_v2_columns(table) -> list[str]:
    """Add any missing source-truth-m2 columns to the open chunks table.

    Idempotent — on a table already at chunks-schema v2 this is a single
    ``schema.names`` read and returns ``[]``. Each ``add_columns`` is a
    fragment-level metadata op (per the lancedb 0.30 contract) that appends the
    NULL default for existing rows without rewriting the embedding columns.
    """
    existing = set(table.schema.names)
    added: list[str] = []
    for name, sql in _V2_COLUMN_DEFAULTS.items():
        if name not in existing:
            table.add_columns({name: sql})
            added.append(name)
    if added:
        logger.info(
            "chunks schema v2 migration: added %d columns: %s",
            len(added),
            added,
        )
    return added


# ---------------------------------------------------------------------------
# Per-notebook report
# ---------------------------------------------------------------------------


@dataclass
class _NotebookReport:
    """Per-notebook abstention report (machine-parseable, loud)."""

    slug: str = ""
    total_rows: int = 0
    total_papers: int = 0
    patched_rows: int = 0
    skipped_papers: int = 0
    skipped_rows: int = 0
    columns_added: list[str] = field(default_factory=list)

    source_span_resolved: int = 0
    source_span_null: int = 0
    source_span_null_reasons: dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    source_span_null_list: list[tuple[str, str]] = field(default_factory=list)

    pn_numbered: int = 0
    pn_unnumbered_f1: int = 0
    pn_uncomputable: int = 0
    pn_not_attempted: int = 0

    truncated_true: int = 0
    truncated_false: int = 0

    rev_resolved: int = 0
    rev_null: int = 0
    rev_null_reasons: dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )

    f2_suspected_papers: list[str] = field(default_factory=list)


def _print_report(report: _NotebookReport) -> None:
    """Loud, machine-parseable summary to stdout + the null listing to stderr."""
    print(
        f"chunks-backfill slug={report.slug} "
        f"rows={report.total_rows} papers={report.total_papers} "
        f"patched={report.patched_rows} "
        f"skipped_papers={report.skipped_papers} "
        f"skipped_rows={report.skipped_rows} "
        f"columns_added={len(report.columns_added)}"
    )
    r = report.source_span_null_reasons
    print(
        "source_span: "
        f"resolved={report.source_span_resolved} "
        f"null={report.source_span_null} "
        f"no_source_revision={r['no_source_revision']} "
        f"html_missing={r['html_missing']} "
        f"chunker_rerun_failed={r['chunker_rerun_failed']} "
        f"chunk_id_not_reproduced={r['chunk_id_not_reproduced']}"
    )
    print(
        "printed_number: "
        f"numbered={report.pn_numbered} "
        f"unnumbered_f1={report.pn_unnumbered_f1} "
        f"uncomputable={report.pn_uncomputable} "
        f"not_attempted={report.pn_not_attempted}"
    )
    print(
        "truncated: "
        f"true={report.truncated_true} false={report.truncated_false} "
        f"total={report.truncated_true + report.truncated_false}"
    )
    rr = report.rev_null_reasons
    print(
        "source_revision_id: "
        f"resolved={report.rev_resolved} null={report.rev_null} "
        f"registry_missing={rr['registry_missing']} "
        f"ambiguous_multi_row={rr['ambiguous_multi_row_registry']}"
    )
    # license_ref resolution tracks source_revision_id exactly (same matched
    # registry row): print it explicitly so the report is self-describing.
    print(
        "license_ref: "
        f"resolved={report.rev_resolved} null={report.rev_null}"
    )
    print(
        "f2_suspected_papers: "
        f"count={len(report.f2_suspected_papers)} "
        f"{report.f2_suspected_papers}"
    )
    if report.source_span_null_list:
        print(
            f"\nsource_span null (chunk_id, reason) — "
            f"{len(report.source_span_null_list)} total"
            + (
                f", showing first {_NULL_LIST_CAP}"
                if len(report.source_span_null_list) > _NULL_LIST_CAP
                else ""
            )
            + ":",
            file=sys.stderr,
        )
        for cid, reason in report.source_span_null_list[:_NULL_LIST_CAP]:
            print(f"  {cid}  reason={reason}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Core patch loop
# ---------------------------------------------------------------------------


def _patch_notebook(
    lancedb_dir: Path,
    db_path: Path,
    parsed_root: Path,
    *,
    slug: str,
    resolve_preamble,
) -> _NotebookReport:
    """Hydrate the five v2 columns on the notebook's chunks table.

    Full-row read-modify-write via a single per-notebook ``merge_insert`` that
    preserves every non-patched column (embeddings included). Returns the
    abstention report.
    """
    db = lancedb.connect(str(lancedb_dir))
    tables_obj = db.list_tables()
    existing_tables = set(getattr(tables_obj, "tables", tables_obj))
    if CHUNKS_TABLE_NAME not in existing_tables:
        raise NotebookError(
            f"notebook {slug!r} has no {CHUNKS_TABLE_NAME!r} LanceDB table at "
            f"{lancedb_dir} — nothing to backfill (ingest the notebook first)"
        )
    table = db.open_table(CHUNKS_TABLE_NAME)

    report = _NotebookReport(slug=slug)
    report.columns_added = _ensure_v2_columns(table)

    registry = _load_registry(db_path)
    rows = table.to_arrow().to_pylist()
    report.total_rows = len(rows)

    by_paper: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_paper[row["paper_id"]].append(row)
    report.total_papers = len(by_paper)

    patched_rows: list[dict] = []
    for paper_id, paper_rows in by_paper.items():
        # Idempotency skip-gate: a paper whose rows already all carry a non-null
        # source_revision_id was hydrated by a prior run — skip the expensive
        # re-chunk AND exclude the rows from the batch (merge_insert only
        # touches rows in the batch, so untouched rows stay byte-identical).
        if all(row.get("source_revision_id") is not None for row in paper_rows):
            report.skipped_papers += 1
            report.skipped_rows += len(paper_rows)
            continue

        # Registry resolution — once per paper (Column 2/3).
        recs = registry.get(paper_id, [])
        if len(recs) == 1:
            rec = recs[0]
            source_revision_id: str | None = _revision_id(rec)
            license_ref: str | None = rec.license_status
            rev16 = (rec.parse_artifact_sha256 or "")[:16]
            rev_null_reason: str | None = None
            if license_ref is not None and license_ref not in _LICENSE_REF_VOCAB:
                logger.warning(
                    "[%s] registry license_status %r outside the advisory "
                    "3-way vocab; denormalizing verbatim",
                    paper_id,
                    license_ref,
                )
        elif len(recs) == 0:
            source_revision_id = license_ref = None
            rev16 = ""
            rev_null_reason = "registry_missing"
        else:
            # Defensive: the live notebooks are 1:1 today, but the registry PK
            # allows >1 revision per work. Never silently pick one — abstain.
            source_revision_id = license_ref = None
            rev16 = ""
            rev_null_reason = "ambiguous_multi_row_registry"

        rr = _rechunk_paper(paper_id, parsed_root, resolve_preamble=resolve_preamble)
        if rr.f2_suspected:
            report.f2_suspected_papers.append(paper_id)

        for row in paper_rows:
            cid = row["chunk_id"]
            kind = row["kind"]
            body_text = row["body_text"]
            hit = rr.status == "ok" and cid in rr.records

            # truncated — never null.
            if hit:
                truncated = bool(rr.records[cid].truncated)
            else:
                truncated = _truncated_fallback(kind, body_text)
            if truncated:
                report.truncated_true += 1
            else:
                report.truncated_false += 1

            # printed_number — from the fresh record on a hit, else null.
            printed_number = rr.records[cid].printed_number if hit else None

            # source_span — only when the revision resolved AND we reproduced
            # the chunk_id; otherwise a counted, reason-coded abstention.
            if source_revision_id is not None and hit:
                source_span: str | None = _source_span_json(rev16, body_text)
                report.source_span_resolved += 1
            else:
                source_span = None
                report.source_span_null += 1
                if source_revision_id is None:
                    reason = "no_source_revision"
                elif rr.status == "html_missing":
                    reason = "html_missing"
                elif rr.status == "rerun_failed":
                    reason = "chunker_rerun_failed"
                else:
                    reason = "chunk_id_not_reproduced"
                report.source_span_null_reasons[reason] += 1
                report.source_span_null_list.append((cid, reason))

            # printed_number classification for the report.
            if printed_number is not None:
                report.pn_numbered += 1
            elif kind in ("proof", "section"):
                report.pn_not_attempted += 1
            elif not hit:
                report.pn_uncomputable += 1
            else:
                report.pn_unnumbered_f1 += 1

            # source_revision_id / license_ref accounting (they resolve or
            # abstain together — same matched registry row).
            if source_revision_id is not None:
                report.rev_resolved += 1
            else:
                report.rev_null += 1
                report.rev_null_reasons[rev_null_reason] += 1

            # Patch the five columns onto the in-memory row dict; every other
            # key (embeddings included) is left exactly as read.
            row["truncated"] = truncated
            row["printed_number"] = printed_number
            row["source_span"] = source_span
            row["source_revision_id"] = source_revision_id
            row["license_ref"] = license_ref
            patched_rows.append(row)

    report.patched_rows = len(patched_rows)

    if patched_rows:
        # Build the batch against the LIVE table schema (post add_columns) so
        # the fixed-size-list embedding columns round-trip losslessly and the
        # boolean/utf8 v2 columns carry the right types. ONE merge_insert per
        # notebook, mirroring embed_equations.py.
        batch = pa.Table.from_pylist(patched_rows, schema=table.schema)
        (
            table.merge_insert("chunk_id")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute(batch)
        )

    return report


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def run(
    slug: str,
    *,
    base: Path | None = None,
    corpus_parsed_dir: Path | None = None,
    resolve_preamble=None,
) -> int:
    """Backfill chunks-schema-v2 columns for one notebook.

    ``base`` / ``corpus_parsed_dir`` / ``resolve_preamble`` are test seams
    (mirroring the ``notebook_documents_backfill.run`` convention); production
    callers pass only ``slug``. Returns the process exit code.
    """
    validate_slug(slug)
    nb_dir = notebook_dir(slug, base=base)
    lancedb_dir = notebook_lancedb_path(slug, base=base)
    db_path = nb_dir / DOCUMENTS_DB_FILENAME
    parsed_root = corpus_parsed_dir or CORPUS_PARSED_DIR
    if resolve_preamble is None:
        resolve_preamble = _resolve_preamble_doc

    report = _patch_notebook(
        lancedb_dir,
        db_path,
        parsed_root,
        slug=slug,
        resolve_preamble=resolve_preamble,
    )
    _print_report(report)
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "slug",
        help="Notebook slug (must match ^[a-z][a-z0-9-]{2,30}$).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        return run(args.slug)
    except NotebookError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = [
    "run",
    "main",
]
