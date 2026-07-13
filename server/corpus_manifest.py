"""Content-addressed corpus manifest builder (source-truth-m3).

The pure-logic, FastMCP-independent core behind the
``arxmcp://corpus-manifest`` MCP resource (registered in
:mod:`server.mcp_resources`). Every ``resources/read`` regenerates the
snapshot on-read from the already-live sources — there is NO persisted
``manifest.json``, no cron, no backfill:

- :class:`server.notebooks_store.NotebooksStore` — the notebook roster
  (every notebook appears, regardless of ``notebook_kind``).
- The per-notebook documents registry
  (:class:`server.documents_store.DocumentsStore`, m1) — per-revision
  checksums + license status + active/withdrawn/superseded status.
- The per-notebook ``corpus-version.json`` marker
  (:func:`server.corpus.read_corpus_version`) — the corpus epoch +
  chunker / embedder version stamps + counts.
- The ``operator_settings`` key-value store
  (:class:`server.operator_settings.OperatorSettingsStore`) — the
  per-notebook ``license_unknown_override_<slug>`` flag (READ ONLY;
  m3 records it, m4 gates serving on it).

**Content addressing (brief-2 §1.2 / §1.7).** ``content_hash`` is a
self-referential sha256 over the canonical JSON of ``snapshot`` ALONE —
NOT the whole payload. ``manifest_version`` / ``generated_at`` /
``content_hash`` sit deliberately OUTSIDE the hash boundary (wire /
read-time metadata: a wall-clock stamp inside the hash would drift the
"content-addressed" digest on every read of unchanged data). The
canonicalization (``sort_keys=True, separators=(",", ":"),
ensure_ascii=True``) is the SAME convention
``tests/test_server_tool_schema.py::_serialize_tools`` uses for
``EXPECTED_TOOL_SCHEMA_SHA256`` — reused verbatim, not re-invented.

**Read-only (CLAUDE.md §4.8).** The only calls this module makes are
reads: ``list_notebooks``, ``DocumentsStore.open``/``all_records``/
``close`` (guarded by a file-existence check so a read NEVER creates an
empty ``documents.db``), ``read_corpus_version`` (a pure file read), and
``OperatorSettingsStore.open``/``get``/``close`` (guarded likewise). No
``upsert_records``, no ``set_setting``/``.set``, no LanceDB / Kùzu write
anywhere in this path.

**Per-notebook failure isolation (brief-2 §1.3 / §5).** A corrupt
``documents.db`` (exists but ``sqlite3.DatabaseError`` on first query),
a symlink-tampered notebook dir, or a transient OS error degrades THAT
ONE notebook to ``registry_present: false`` + ``registry_error`` — it
never raises and fails the whole ``resources/read``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from server import operator_settings
from server.corpus import read_corpus_version
from server.documents_store import (
    DOCUMENT_STATUS_ACTIVE,
    DOCUMENT_STATUS_SUPERSEDED,
    DOCUMENT_STATUS_WITHDRAWN,
    DOCUMENTS_DB_FILENAME,
    DocumentsStore,
)
from server.operator_settings import OperatorSettingsStore
from tools._notebook_common import NotebookError, notebook_dir, notebook_lancedb_path
from tools.oai_license import (
    LICENSE_STATUS_ELIGIBLE,
    LICENSE_STATUS_NOT_ALLOWLISTED_OPEN,
    LICENSE_STATUS_UNKNOWN,
)

if TYPE_CHECKING:
    from server.corpus import CorpusVersionInfo
    from server.documents_store import DocumentRecord
    from server.notebooks_store import NotebooksStore

logger = logging.getLogger(__name__)

#: Wire-format schema version of the manifest payload. Bumping this (a
#: richer JSON shape) is a SERVER CODE change, not a corpus content
#: change — so it lives OUTSIDE the ``content_hash`` boundary (§1.2).
MANIFEST_VERSION: int = 1

#: Namespaced ``operator_settings`` key for the per-notebook
#: license-unknown override flag (brief-2 §4). The single-underscore
#: delimiter is unambiguous because ``SLUG_RE`` never permits an
#: underscore inside a slug — the key is always constructed from an
#: already-validated slug, never reverse-parsed.
OVERRIDE_KEY_PREFIX: str = "license_unknown_override_"

#: The fail-safe-disabled override block: an absent key, a malformed
#: value, or an unreadable settings store all degrade to THIS (never a
#: silent permissive default — matches ``decide_license_status``'s
#: any-doubt-falls-to-unknown posture).
_OVERRIDE_DISABLED: dict[str, Any] = {
    "license_unknown_escalation_override": False,
    "set_by": None,
    "set_at": None,
    "note": None,
}


def _utc_iso() -> str:
    """ISO-8601 UTC read-time stamp (``…Z``), matching the rest of the
    repo's timestamp convention (``operator_settings._utc_iso``)."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Content addressing (pure — unit-testable without FastMCP)
# ---------------------------------------------------------------------------


def compute_manifest_hash(snapshot: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON of ``snapshot`` alone (§1.7).

    Uses ``sort_keys=True, separators=(",", ":"), ensure_ascii=True`` —
    the exact canonicalization
    ``tests/test_server_tool_schema.py::_serialize_tools`` uses for the
    tool-schema hash. A client re-verifies by extracting
    ``payload["snapshot"]``, calling this function, and comparing with
    ``payload["content_hash"]`` — no "exclude these keys by name"
    convention to get wrong, because the excluded fields live OUTSIDE
    ``snapshot`` structurally.
    """
    canonical = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _revision_key(record: DocumentRecord) -> list[str | None]:
    """Positional digest row for one revision (brief-2 §1.6).

    Both checksums AND ``license_status`` + ``status`` feed the key: a
    license re-decision (``unknown`` -> ``eligible`` after re-hydration)
    or a status flip (``active`` -> ``withdrawn``) is exactly the
    provenance change a downstream consumer pinning to this rollup needs
    to see, not just a raw byte change.
    """
    return [
        record.work_id,
        record.arxiv_version,
        record.parse_artifact_sha256,
        record.raw_source_sha256,
        record.license_status,
        record.status,
    ]


def rollup_sha256(records: list[DocumentRecord]) -> str:
    """Flat, sorted, canonical-JSON digest over positional revision rows.

    Not a real Merkle tree (nothing consumes an inclusion proof) — a
    stable content digest for cheap drift checks and for downstream
    receipts to embed instead of inlining the whole per-revision list.
    Sorting by ``(work_id, arxiv_version)`` is load-bearing: ``sort_keys``
    only orders object keys, never array elements, so the array order
    must be pinned explicitly.
    """
    rows = sorted(records, key=lambda r: (r.work_id, r.arxiv_version))
    canonical = json.dumps(
        [_revision_key(r) for r in rows],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Per-notebook aggregation (pure folds over the registry rows)
# ---------------------------------------------------------------------------


def _corpus_fields(cv: CorpusVersionInfo | None) -> dict[str, Any]:
    """The six corpus-epoch fields — populated TOGETHER or all-null
    (brief-2 §1.3 abstention invariant). They all come from ONE
    ``read_corpus_version`` call, which returns a fully-populated
    ``CorpusVersionInfo`` or ``None`` (cold-start), never a partial mix.
    """
    if cv is None:
        return {
            "corpus_version": None,
            "chunker_version": None,
            "embedder_version": None,
            "corpus_created_at": None,
            "paper_count": None,
            "chunk_count": None,
        }
    return {
        "corpus_version": cv.version,
        "chunker_version": cv.chunker_version,
        "embedder_version": cv.embedder_version,
        "corpus_created_at": cv.created_at,
        "paper_count": cv.paper_count,
        "chunk_count": cv.chunk_count,
    }


def _license_summary(records: list[DocumentRecord]) -> dict[str, int]:
    """3-way license census + total (CLAUDE.md §4.9 / brief-2 §4.9).

    The vocabulary keys come from ``tools.oai_license``'s constants,
    never re-typed as string literals. ``unknown`` (a genuine data gap)
    is NEVER folded into ``not-allowlisted-open`` (a real license,
    allowlist decision pending) or vice versa — conflating them would
    corrupt the >20%-unknown owner-escalation signal m4 gates on.
    """
    counts: dict[str, int] = {}
    for r in records:
        counts[r.license_status] = counts.get(r.license_status, 0) + 1
    return {
        LICENSE_STATUS_ELIGIBLE: counts.get(LICENSE_STATUS_ELIGIBLE, 0),
        LICENSE_STATUS_NOT_ALLOWLISTED_OPEN: counts.get(
            LICENSE_STATUS_NOT_ALLOWLISTED_OPEN, 0
        ),
        LICENSE_STATUS_UNKNOWN: counts.get(LICENSE_STATUS_UNKNOWN, 0),
        "total": len(records),
    }


def _id_shape(records: list[DocumentRecord]) -> dict[str, int]:
    """Counts by id shape (brief-2 §1.3), mirroring the coverage
    report's fold: ``versioned`` is cross-cutting (an explicit ``vN`` in
    the membership line); new vs old by the work id's own shape (an
    old-style archive prefix carries the literal ``/``)."""
    new_style = old_style = versioned = 0
    for r in records:
        if r.arxiv_version:
            versioned += 1
        if "/" in r.work_id:
            old_style += 1
        else:
            new_style += 1
    return {
        "new_style": new_style,
        "old_style": old_style,
        "versioned": versioned,
    }


def _revision_entry(record: DocumentRecord) -> dict[str, Any]:
    """One per-revision entry (brief-2 §1.4) — explicit allowlist-by-
    projection. Only the fields AC1 (checksums) and AC2 (invalidation)
    need cross the boundary. ``license_uri`` (an externally-sourced arXiv
    OAI-PMH string) and per-row ``chunker_version`` are deliberately NOT
    repeated here — ``chunker_version`` is reported once per notebook, and
    keeping ``license_uri`` out shrinks the injection surface to exactly
    one field (``override.note``)."""
    invalidated = record.status != DOCUMENT_STATUS_ACTIVE
    return {
        "work_id": record.work_id,
        "arxiv_version": record.arxiv_version,
        "raw_source_sha256": record.raw_source_sha256,
        "raw_source_status": record.raw_source_status,
        "parse_artifact_sha256": record.parse_artifact_sha256,
        "license_status": record.license_status,
        "status": record.status,
        "invalidated": invalidated,
        "invalidation_reason": record.status if invalidated else None,
    }


def _revisions_list(records: list[DocumentRecord]) -> list[dict[str, Any]]:
    """Full per-revision list, sorted by ``(work_id, arxiv_version)``.

    ``DocumentsStore.all_records`` already returns rows in this order, but
    the sort is applied here EXPLICITLY rather than relying on incidental
    DB ordering silently continuing to hold (brief-2 §1.4) — array order
    is load-bearing for the content hash's determinism.
    """
    ordered = sorted(records, key=lambda r: (r.work_id, r.arxiv_version))
    return [_revision_entry(r) for r in ordered]


def _revisions_digest(records: list[DocumentRecord]) -> dict[str, Any]:
    """The rollup block (brief-2 §1.3 / §1.6). ``active_rollup_sha256``
    EXCLUDES invalidated (non-active) revisions; ``rollup_sha256`` retains
    them. When zero revisions are invalidated the two are byte-identical
    (the free regression invariant)."""
    active = [r for r in records if r.status == DOCUMENT_STATUS_ACTIVE]
    return {
        "count_total": len(records),
        "count_active": len(active),
        "count_withdrawn": sum(
            1 for r in records if r.status == DOCUMENT_STATUS_WITHDRAWN
        ),
        "count_superseded": sum(
            1 for r in records if r.status == DOCUMENT_STATUS_SUPERSEDED
        ),
        "rollup_sha256": rollup_sha256(records),
        "active_rollup_sha256": rollup_sha256(active),
    }


# ---------------------------------------------------------------------------
# I/O helpers (each guarded — a read NEVER writes / creates a file)
# ---------------------------------------------------------------------------


def _safe_read_corpus_version(
    slug: str, base: Path | None
) -> CorpusVersionInfo | None:
    """``read_corpus_version`` for one notebook, never raising.

    Absent marker -> ``None`` (cold-start, corpus fields all-null). A
    present-but-malformed ``corpus-version.json`` (``ValueError``), an OS
    error, or a symlink-tampered dir (``NotebookError``) also degrade to
    ``None`` with a server-side WARNING rather than failing the read —
    the corpus epoch is independent of the registry, so a bad marker must
    not take down the whole notebook block.
    """
    try:
        return read_corpus_version(notebook_lancedb_path(slug, base=base))
    except (ValueError, OSError, NotebookError) as exc:
        logger.warning(
            "corpus_manifest: notebook %r corpus-version read failed "
            "(%s); reporting corpus fields as null",
            slug,
            type(exc).__name__,
        )
        return None


async def _load_records(db_path: Path) -> list[DocumentRecord]:
    """Open the registry, read every row, close. The open is guarded by
    a file-existence check in the caller so this never CREATES an empty
    ``documents.db``."""
    store = await DocumentsStore.open(db_path)
    try:
        return await store.all_records()
    finally:
        await store.close()


async def _read_override(slug: str, settings_db_path: Path) -> dict[str, Any]:
    """Read the per-notebook override flag (brief-2 §4). READ ONLY.

    Fail-safe-disabled: an absent key, a missing store file, a
    ``json.loads`` failure, a missing / non-boolean ``enabled``, or an
    unreadable store ALL return :data:`_OVERRIDE_DISABLED` (WARNING-logged,
    never raised, never a silent permissive grant). The settings-store
    file-existence check mirrors ``operator_settings.get_setting`` so a
    read never creates a brand-new ``notebooks.db``.
    """
    if not settings_db_path.is_file():
        return dict(_OVERRIDE_DISABLED)
    key = f"{OVERRIDE_KEY_PREFIX}{slug}"
    try:
        store = await OperatorSettingsStore.open(settings_db_path)
        try:
            raw = await store.get(key)
        finally:
            await store.close()
    except (sqlite3.DatabaseError, OSError) as exc:
        logger.warning(
            "corpus_manifest: notebook %r override read failed (%s); "
            "defaulting override OFF",
            slug,
            type(exc).__name__,
        )
        return dict(_OVERRIDE_DISABLED)

    if raw is None:
        return dict(_OVERRIDE_DISABLED)
    try:
        parsed = json.loads(raw)
        enabled = parsed["enabled"]
    except (ValueError, TypeError, KeyError) as exc:
        logger.warning(
            "corpus_manifest: notebook %r override value malformed (%s); "
            "defaulting override OFF",
            slug,
            type(exc).__name__,
        )
        return dict(_OVERRIDE_DISABLED)
    if not isinstance(enabled, bool):
        logger.warning(
            "corpus_manifest: notebook %r override 'enabled' is %s, not "
            "bool; defaulting override OFF",
            slug,
            type(enabled).__name__,
        )
        return dict(_OVERRIDE_DISABLED)
    return {
        "license_unknown_escalation_override": enabled,
        "set_by": parsed.get("set_by"),
        "set_at": parsed.get("set_at"),
        "note": parsed.get("note"),
    }


async def _build_notebook_block(
    slug: str, *, base: Path | None, settings_db_path: Path
) -> dict[str, Any]:
    """Assemble one notebook's snapshot block, failure-isolated.

    Corpus fields are always populated (independently of the registry).
    The registry sub-blocks (``license_summary`` / ``id_shape`` /
    ``revisions_digest`` / ``revisions`` / ``override``) are present ONLY
    when the registry is present and readable; a missing ``documents.db``
    -> ``registry_present: false`` with no error, a corrupt one ->
    ``registry_present: false`` with ``registry_error`` (the exception
    class name — the full detail is logged server-side, NOT leaked to the
    agent, matching the resources module's path-info-leak discipline).
    """
    block: dict[str, Any] = _corpus_fields(_safe_read_corpus_version(slug, base))

    # The notebook_dir() containment/symlink guard can raise NotebookError
    # (out-of-band tamper at var/arxmcp/notebooks/<slug>). Degrade this one
    # notebook rather than failing the whole read.
    try:
        db_path = notebook_dir(slug, base=base) / DOCUMENTS_DB_FILENAME
    except NotebookError as exc:
        logger.warning(
            "corpus_manifest: notebook %r dir rejected (%s); "
            "registry_present=false",
            slug,
            type(exc).__name__,
        )
        block["registry_present"] = False
        block["registry_error"] = type(exc).__name__
        return block

    # Registry-absent invariant (brief-2 §1.3): NEVER open a missing file
    # (DocumentsStore.open would create it). The absence IS the signal.
    if not db_path.is_file():
        block["registry_present"] = False
        block["registry_error"] = None
        return block

    try:
        records = await _load_records(db_path)
    except (sqlite3.DatabaseError, OSError, ValueError) as exc:
        logger.warning(
            "corpus_manifest: notebook %r registry read failed (%s); "
            "registry_present=false",
            slug,
            type(exc).__name__,
        )
        block["registry_present"] = False
        block["registry_error"] = type(exc).__name__
        return block

    block["registry_present"] = True
    block["registry_error"] = None
    block["license_summary"] = _license_summary(records)
    block["id_shape"] = _id_shape(records)
    block["revisions_digest"] = _revisions_digest(records)
    block["revisions"] = _revisions_list(records)
    block["override"] = await _read_override(slug, settings_db_path)
    return block


async def build_manifest(
    notebooks_store: NotebooksStore,
    *,
    base: Path | None = None,
    settings_db_path: Path | None = None,
) -> dict[str, Any]:
    """Build the full ``arxmcp://corpus-manifest`` payload (on-read).

    Returns ``{manifest_version, generated_at, content_hash,
    snapshot:{notebooks:{<slug>: block}}}`` with ``content_hash`` computed
    over ``snapshot`` ALONE (the three wire/read-time fields sit outside
    the hash boundary — §1.2).

    ``base`` (notebooks root) and ``settings_db_path`` (the
    ``operator_settings`` DB) are test seams; production callers pass
    nothing and get :data:`tools._notebook_common.NOTEBOOKS_BASE` /
    :data:`server.operator_settings.DEFAULT_DB_PATH`. ``settings_db_path``
    is resolved at CALL time (attribute access) so the test-suite's
    autouse redirect of ``DEFAULT_DB_PATH`` is honored.
    """
    if settings_db_path is None:
        settings_db_path = operator_settings.DEFAULT_DB_PATH

    rows = await notebooks_store.list_notebooks()
    notebooks: dict[str, Any] = {}
    for row in rows:
        slug = row["slug"]
        notebooks[slug] = await _build_notebook_block(
            slug, base=base, settings_db_path=settings_db_path
        )

    snapshot = {"notebooks": notebooks}
    content_hash = compute_manifest_hash(snapshot)
    return {
        "manifest_version": MANIFEST_VERSION,
        "generated_at": _utc_iso(),
        "content_hash": content_hash,
        "snapshot": snapshot,
    }


__all__ = [
    "MANIFEST_VERSION",
    "OVERRIDE_KEY_PREFIX",
    "build_manifest",
    "compute_manifest_hash",
    "rollup_sha256",
]
