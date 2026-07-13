"""Backfill the per-revision documents registry for a notebook (source-truth-m1).

Reads the notebook's ``papers.txt`` (the membership source of truth —
the central ``notebook_papers`` junction table is EMPTY for every
notebook, so keying off it would register zero rows and silently
"pass"), and for every ingested revision computes + persists a
:class:`server.documents_store.DocumentRecord` into the per-notebook
:class:`server.documents_store.DocumentsStore` at
``var/arxmcp/notebooks/<slug>/documents.db``.

Per revision it records:

- ``raw_source_sha256`` + ``raw_source_status`` — a deterministic hash of
  the raw ``.tex`` source tree under ``var/arxmcp/corpus/raw/<work_id>/``,
  OR the abstention marker (``None`` + ``unavailable``) when that dir does
  not exist. Old-style papers hit the ar5iv cache and never persisted a
  local raw tree, so their raw checksum is a documented NULL, never a
  silent hole ("abstention, not silence", source-truth-m1 OWNER DECISION).
- ``parse_artifact_sha256`` — a hash of ``parsed/<work_id>/index.html``
  (present for BOTH id shapes).
- ``chunker_version`` (``ingest.chunker_types.CHUNKER_VERSION``);
  ``parser_used`` + ``latexml_version`` are NULL in m1 (no queryable
  per-paper signal on disk yet — see the store docstring).
- ``license_uri`` + a 3-way ``license_status``, hydrated via ONE OAI-PMH
  ``GetRecord`` per version-stripped work id (:mod:`tools.oai_license`),
  and ``status`` (``withdrawn`` from ``<header status="deleted">``, else
  ``active``; ``superseded`` has no signal in m1).

**0-re-embed is STRUCTURAL, not incidental.** This driver never imports
``ingest.store`` or the BGE-M3 embedder, and never opens the LanceDB
``chunks`` table — its whole job is a new SQLite store + a read-only
OAI-PMH hydration. So "0 chunks re-embedded" is satisfied by construction
(asserted in ``tests/test_notebook_documents_backfill.py``).

Politeness contract (arXiv ToU): one ``GetRecord`` per paper (OAI-PMH has
no id_list batching), a 3-second sleep BEFORE every request except the
first (``tools.arxiv_fetch.POLITENESS_SLEEP_SECONDS``), 503/``Retry-After``
backoff mirrored from ``ingest.oai_delta`` inside
:func:`tools.oai_license._fetch_record`. ``idDoesNotExist`` is a per-paper
non-fatal outcome (``license_status=unknown``); a transient fetch failure
writes NO row so a re-run retries it.

Idempotency: already-registered ``(work_id, arxiv_version)`` pairs are
skipped without network egress; a re-run over a registered notebook
performs zero requests.

Summary line (machine-parseable; the registered/total pair keeps a
zero-row run LOUD):

    registered=N skipped=M missing=K malformed=J unique=U total=T

Usage:

    uv run python tools/notebook_documents_backfill.py <slug>

Exit codes:
    0 — every paper id registered or already registered
    1 — slug/email validation failed, malformed papers.txt entries, or
        >=1 id missed (reasons on stderr; re-run after outages)
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ingest.chunker_types import CHUNKER_VERSION
from ingest.identifiers import is_valid_arxiv_paper_id
from server.documents_store import (
    DOCUMENT_STATUS_ACTIVE,
    DOCUMENT_STATUS_WITHDRAWN,
    DOCUMENTS_DB_FILENAME,
    RAW_SOURCE_STATUS_PRESENT,
    RAW_SOURCE_STATUS_UNAVAILABLE,
    DocumentRecord,
    DocumentsStore,
)
from tools import oai_license
from tools._arxiv_api import strip_id_version
from tools._notebook_common import (
    CORPUS_PARSED_DIR,
    CORPUS_RAW_DIR,
    NotebookError,
    notebook_dir,
    read_paper_ids_from_papers_txt,
    resolve_contact_email,
    validate_slug,
)
from tools.arxiv_fetch import POLITENESS_SLEEP_SECONDS, build_user_agent

logger = logging.getLogger("notebook_documents_backfill")


class _FetchFailure(Exception):
    """A GetRecord that failed transiently / fatally; ``reason`` is the
    per-id miss category (``oai_error``, ``network``…)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class _RequestState:
    """Mutable politeness state shared across all requests of a run."""

    requests_made: int = 0
    sleep: Callable[[float], None] = field(default=time.sleep)


# ---------------------------------------------------------------------------
# On-disk provenance (checksums + abstention marker)
# ---------------------------------------------------------------------------


def _hash_raw_source_tree(raw_dir: Path) -> str | None:
    """Deterministic sha256 over an entire raw-source directory tree.

    Hashes every file's POSIX-normalized relative path + byte length +
    bytes, in sorted-path order, so the digest is stable across
    platforms and re-runs. Returns ``None`` when the dir is absent or
    empty (the old-style abstention case).
    """
    if not raw_dir.is_dir():
        return None
    files = sorted(p for p in raw_dir.rglob("*") if p.is_file())
    if not files:
        return None
    h = hashlib.sha256()
    for f in files:
        rel = f.relative_to(raw_dir).as_posix()
        data = f.read_bytes()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(str(len(data)).encode("ascii"))
        h.update(b"\0")
        h.update(data)
        h.update(b"\0")
    return h.hexdigest()


def _raw_source_provenance(
    work_id: str, raw_root: Path
) -> tuple[str | None, str]:
    """``(raw_source_sha256, raw_source_status)`` for a work id.

    ``(None, 'unavailable')`` is the abstention marker for old-style
    papers whose raw source never landed on disk — NOT a defect a re-run
    should try to repair.
    """
    sha = _hash_raw_source_tree(raw_root / work_id)
    if sha is None:
        return None, RAW_SOURCE_STATUS_UNAVAILABLE
    return sha, RAW_SOURCE_STATUS_PRESENT


def _parse_artifact_sha256(work_id: str, parsed_root: Path) -> str | None:
    """sha256 of ``parsed/<work_id>/index.html`` (present for BOTH id
    shapes), or ``None`` if somehow absent."""
    index = parsed_root / work_id / "index.html"
    if not index.is_file():
        return None
    return hashlib.sha256(index.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Per-paper registration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Membership:
    """One deduped membership entry: a work id + its (possibly empty)
    explicit version from the ``papers.txt`` line."""

    work_id: str
    arxiv_version: str


def _build_record(
    membership: _Membership,
    oai_record: oai_license.OaiLicenseRecord,
    *,
    raw_root: Path,
    parsed_root: Path,
    fetched_at: str,
) -> DocumentRecord:
    """Assemble a :class:`DocumentRecord` from the OAI-PMH result + the
    on-disk checksums."""
    raw_sha, raw_status = _raw_source_provenance(membership.work_id, raw_root)
    return DocumentRecord(
        work_id=membership.work_id,
        arxiv_version=membership.arxiv_version,
        raw_source_sha256=raw_sha,
        raw_source_status=raw_status,
        parse_artifact_sha256=_parse_artifact_sha256(
            membership.work_id, parsed_root
        ),
        chunker_version=CHUNKER_VERSION,
        parser_used=None,      # not a queryable per-paper column until m2
        latexml_version=None,  # local latexmlc version not captured in-repo
        fetched_at=fetched_at,
        license_uri=oai_record.license_uri,
        license_status=oai_license.decide_license_status(
            oai_record.license_uri
        ),
        status=(
            DOCUMENT_STATUS_WITHDRAWN
            if oai_record.deleted
            else DOCUMENT_STATUS_ACTIVE
        ),
    )


def _fetch_one(
    membership: _Membership,
    user_agent: str,
    state: _RequestState,
    fetch,
) -> oai_license.OaiLicenseRecord:
    """One polite ``GetRecord`` for a work id.

    Sleeps :data:`POLITENESS_SLEEP_SECONDS` before every request except
    the run's first, then delegates to :func:`tools.oai_license.fetch_license`.
    Raises :class:`_FetchFailure` (translated to a per-id miss) on any
    transient/fatal fetch error — never a crash that aborts the run.
    """
    if state.requests_made > 0:
        state.sleep(POLITENESS_SLEEP_SECONDS)
    state.requests_made += 1
    try:
        return oai_license.fetch_license(
            membership.work_id, user_agent=user_agent, fetch=fetch,
        )
    except RuntimeError as exc:
        # 503 budget exhausted, redirect-off-host, oversized body, or a
        # fatal OAI-PMH error code. Recoverable per-paper miss; re-run
        # retries (no row written).
        logger.warning(
            "[%s] GetRecord failed: %s", membership.work_id, exc,
        )
        raise _FetchFailure("oai_error") from exc
    except OSError as exc:
        # URLError / socket timeout / connection reset.
        logger.warning(
            "[%s] GetRecord network error: %s", membership.work_id, exc,
        )
        raise _FetchFailure("network") from exc


async def _register(
    db_path: Path,
    memberships: Sequence[_Membership],
    user_agent: str,
    *,
    raw_root: Path,
    parsed_root: Path,
    sleep: Callable[[float], None],
    fetch,
) -> tuple[list[DocumentRecord], list[_Membership], list[tuple[str, str]]]:
    """Register ``memberships`` into the store.

    Returns ``(registered_records, skipped, missing)`` where ``missing``
    is ``(work_id[@version], reason)`` pairs.
    """
    store = await DocumentsStore.open(db_path)
    try:
        already = await store.registered_keys()
        skipped = [
            m for m in memberships
            if (m.work_id, m.arxiv_version) in already
        ]
        pending = [
            m for m in memberships
            if (m.work_id, m.arxiv_version) not in already
        ]

        registered: list[DocumentRecord] = []
        missing: list[tuple[str, str]] = []
        state = _RequestState(sleep=sleep)
        for membership in pending:
            try:
                oai_record = _fetch_one(membership, user_agent, state, fetch)
            except _FetchFailure as exc:
                label = _label(membership)
                missing.append((label, exc.reason))
                continue
            record = _build_record(
                membership,
                oai_record,
                raw_root=raw_root,
                parsed_root=parsed_root,
                fetched_at=datetime.now(UTC).isoformat(),
            )
            await store.upsert_records([record])
            registered.append(record)
        return registered, skipped, missing
    finally:
        await store.close()


def _label(membership: _Membership) -> str:
    """Human-facing id label: ``work_id`` or ``work_id@vN``."""
    if membership.arxiv_version:
        return f"{membership.work_id}@{membership.arxiv_version}"
    return membership.work_id


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def run(
    slug: str,
    *,
    base: Path | None = None,
    corpus_raw_dir: Path | None = None,
    corpus_parsed_dir: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
    fetch=None,
) -> int:
    """Backfill the documents registry for every arXiv id in papers.txt.

    ``base`` / ``corpus_raw_dir`` / ``corpus_parsed_dir`` / ``sleep`` /
    ``fetch`` are test seams (mirror the ``notebook_metadata_backfill.run``
    convention); production callers pass only ``slug``. Returns the
    process exit code.
    """
    # Slug validation FIRST (per _notebook_common convention), then
    # run-entry politeness enforcement: resolve the arXiv polite-pool
    # contact email and build the User-Agent once for the whole run.
    validate_slug(slug)
    contact_email = resolve_contact_email(None)
    user_agent = build_user_agent(contact_email)

    nb_dir = notebook_dir(slug, base=base)
    raw_root = corpus_raw_dir or CORPUS_RAW_DIR
    parsed_root = corpus_parsed_dir or CORPUS_PARSED_DIR
    raw_lines = read_paper_ids_from_papers_txt(nb_dir / "papers.txt")

    # Pre-validate every line; split the explicit version off the work id
    # and dedupe by (work_id, version).
    memberships: list[_Membership] = []
    malformed: list[str] = []
    seen: set[tuple[str, str]] = set()
    for line in raw_lines:
        if is_valid_arxiv_paper_id(line):
            work_id = strip_id_version(line)
            # The removed suffix is the explicit version (``v1``…), or
            # '' for a bare work id. strip_id_version only ever removes a
            # trailing ``v\d+``, so the slice is exact.
            version = line.strip()[len(work_id):]
            key = (work_id, version)
            if key not in seen:
                seen.add(key)
                memberships.append(_Membership(work_id, version))
        else:
            malformed.append(line)

    registered, skipped, missing = asyncio.run(
        _register(
            nb_dir / DOCUMENTS_DB_FILENAME,
            memberships,
            user_agent,
            raw_root=raw_root,
            parsed_root=parsed_root,
            sleep=sleep,
            fetch=fetch,
        )
    )

    _print_summary(registered, skipped, missing, malformed, len(memberships), len(raw_lines))
    return 1 if (malformed or missing) else 0


def _print_summary(
    registered: list[DocumentRecord],
    skipped: list[_Membership],
    missing: list[tuple[str, str]],
    malformed: list[str],
    unique: int,
    total: int,
) -> None:
    """Loud, machine-parseable summary + per-id miss reasons on stderr."""
    # Primary line: registered/total keeps a zero-row run loud. `unique`
    # is the deduped (work_id, version) denominator
    # (registered + skipped + missing == unique).
    print(
        f"registered={len(registered)} "
        f"skipped={len(skipped)} "
        f"missing={len(missing)} "
        f"malformed={len(malformed)} "
        f"unique={unique} "
        f"total={total}"
    )
    # m1-specific breakdowns over what was NEWLY registered this run
    # (the coverage report reads the WHOLE registry across both
    # notebooks; this is just what this run wrote).
    lic: dict[str, int] = {
        oai_license.LICENSE_STATUS_ELIGIBLE: 0,
        oai_license.LICENSE_STATUS_NOT_ALLOWLISTED_OPEN: 0,
        oai_license.LICENSE_STATUS_UNKNOWN: 0,
    }
    active = withdrawn = raw_present = raw_unavailable = 0
    for r in registered:
        lic[r.license_status] = lic.get(r.license_status, 0) + 1
        if r.status == DOCUMENT_STATUS_WITHDRAWN:
            withdrawn += 1
        else:
            active += 1
        if r.raw_source_status == RAW_SOURCE_STATUS_PRESENT:
            raw_present += 1
        else:
            raw_unavailable += 1
    print(
        "license_status: "
        f"eligible={lic[oai_license.LICENSE_STATUS_ELIGIBLE]} "
        f"not-allowlisted-open={lic[oai_license.LICENSE_STATUS_NOT_ALLOWLISTED_OPEN]} "
        f"unknown={lic[oai_license.LICENSE_STATUS_UNKNOWN]}"
    )
    print(f"status: active={active} withdrawn={withdrawn}")
    print(
        f"raw_source: present={raw_present} unavailable={raw_unavailable}"
    )
    if malformed:
        print(
            "\nmalformed lines in papers.txt (not arXiv IDs):",
            file=sys.stderr,
        )
        for line in malformed:
            print(f"  {line!r}", file=sys.stderr)
    if missing:
        print(
            "\nmissing registrations — per-id reasons (oai_error/network "
            "are recoverable: re-run after the arXiv outage clears):",
            file=sys.stderr,
        )
        for label, reason in missing:
            print(f"  {label}  reason={reason}", file=sys.stderr)


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
