"""Backfill ``documents.arxiv_version``, which is ``''`` for every row.

Lands derived-alg-geo-lean **#171** (epic #134), ranked critical there.

``documents.arxiv_version`` is ``''`` for every row in both live notebooks.
The column exists and is half the PRIMARY KEY, so the corpus can *hold* a
version; nothing has ever *put one there*. The seed line is the column's only
writer (``tools/notebook_documents_backfill.py`` reads ``<id>@vN`` off
``papers.txt``) and none of the 79 seed lines carries an ``@vN``.

Three things break, and they are the reason this is not cosmetic:

1. ``notebook_fetch`` pulls ar5iv for the **bare id** — arXiv latest. After a
   re-ingest, ``statement_resolve.py`` would match a quote against whatever is
   latest and write ``current`` for an entry declaring ``version: v2``. That
   record then asserts a v2 pin confirmed by bytes of unknown version. (The
   resolver refuses to today: it emits ``not_applicable``. That guard is what
   this tool exists to let it stop needing.)
2. ``corpus_manifest_content_hash`` hashes ``(work_id, arxiv_version, …)``. With
   the version empty it cannot distinguish revisions either, so the
   ``mint_resolution`` stamp is not the guard it looks like.
3. Nothing downstream can honestly say ``current`` about a versioned entry.

## Where the version comes from, and why not from the obvious place

**Not from the arXiv API.** ``tools/_arxiv_api.py`` already parses an Atom feed
whose ``<id>`` is ``http://arxiv.org/abs/math/0212237v3``, and
``extract_paper_id_from_abs_url`` deliberately throws the ``v3`` away. Taking
it instead would record *the version that is latest right now*, which is a
different fact from *the version this corpus holds* the moment an author posts
a revision. Writing today's latest into a row fetched in May would be a
fabrication of exactly the kind this contract exists to prevent.

**From the OAI-PMH ``arXivRaw`` record, windowed by ``fetched_at``.** That
format carries the full version history — one ``<version version="vN">`` per
revision, each with its posting date (``ingest/oai_delta.py:116`` already
picked it for the same reason: the plain ``arXiv`` prefix omits the history).
``documents.fetched_at`` says when we pulled the paper. The version this
notebook holds is the last one posted at or before that moment, and that is a
fact about the past which no later revision can change.

**What the filled column then means, stated exactly.** Not "these bytes are
vN". It means: *when this notebook fetched this work, vN was the revision arXiv
served for the bare id.* The remaining gap is a stale ar5iv render — ar5iv
could in principle have served an older rendering than arXiv's then-current
source — and that gap is not closable from here, because nothing in the fetched
HTML names a version (checked: every arxiv.org link in a stored ``index.html``
is to the bare id). Every version that is written is written into a report
alongside the full history and the ``fetched_at`` that selected it, so the
inference is auditable rather than asserted.

**Abstention is the default.** Anything this tool cannot establish stays ``''``
and is counted. A row that still reads ``''`` after a run is exactly a row
whose version could not be established, which is what makes the resolver's
guard stay correct after this lands.

Politeness contract (arXiv ToU), inherited unchanged from
:mod:`tools.oai_license`: one ``GetRecord`` per work, a 3-second sleep before
every request except the first, and 503/``Retry-After`` backoff.

Usage::

    uv run python tools/notebook_arxiv_version_backfill.py <slug> [--dry-run]

Summary line (machine-parseable; the filled/total pair keeps a zero-row run
LOUD rather than quietly green)::

    filled=N abstained=M collided=C failed=K total=T

Exit codes:
    0 — every row was either filled or abstained on with a recorded reason
    1 — slug/email validation failed, no documents.db, or >=1 transient fetch
        failure (re-run after the outage; filled rows are already committed)
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from server.documents_store import DOCUMENTS_DB_FILENAME
from tools import oai_license
from tools._notebook_common import (
    NotebookError,
    notebook_dir,
    resolve_contact_email,
    validate_slug,
)
from tools.arxiv_fetch import POLITENESS_SLEEP_SECONDS, build_user_agent

#: ``arXivRaw`` is the only arXiv OAI-PMH format that carries version history.
#: The plain ``arXiv`` prefix (which ``tools/oai_license.py`` uses, correctly,
#: for the ``<license>`` element) omits it. Same choice ``ingest/oai_delta.py``
#: made at its synthesis D5.
METADATA_PREFIX: str = "arXivRaw"

#: ``arXivRaw`` records sit in their own namespace, distinct from the plain
#: ``arXiv`` format's.
_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "raw": "http://arxiv.org/OAI/arXivRaw/",
}

#: Written under ``var/arxmcp/notebooks/<slug>/ops/``. The provenance of every
#: filled version lives here rather than in a new ``documents`` column: a
#: column would change ``corpus_manifest_content_hash``'s inputs and therefore
#: every downstream freshness comparison, to carry a field only an auditor
#: reads.
REPORT_DIR_NAME = "ops"


class VersionBackfillError(RuntimeError):
    """A precondition the operator can fix. The CLI prints it and exits 1."""


@dataclass(frozen=True)
class Revision:
    """One ``<version version="vN"><date>…</date></version>`` element."""

    version: str
    posted_at: datetime


@dataclass
class Outcome:
    """What happened to one ``documents`` row."""

    work_id: str
    fetched_at: str
    verdict: str          # filled | abstained | collided | failed
    version: str | None = None
    reason: str | None = None
    history: list[dict[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_versions(body: bytes, *, work_id: str = "") -> list[Revision]:
    """Every revision in an ``arXivRaw`` ``GetRecord`` response, oldest first.

    Raises :class:`VersionBackfillError` on a fatal OAI-PMH error code or a
    deleted record; returns ``[]`` when the record carries no ``<version>``
    elements at all, which is a legal-but-useless response rather than a
    failure to retry.
    """
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise VersionBackfillError(
            f"{work_id or 'record'}: OAI-PMH response is not XML: {exc}"
        ) from exc

    error = root.find("oai:error", _NS)
    if error is not None:
        code = (error.get("code") or "").strip()
        if code == "idDoesNotExist":
            return []
        raise VersionBackfillError(
            f"{work_id or 'record'}: OAI-PMH error {code!r}: "
            f"{(error.text or '').strip()}"
        )

    record = root.find("oai:GetRecord/oai:record", _NS)
    if record is None:
        raise VersionBackfillError(
            f"{work_id or 'record'}: response carries no GetRecord/record"
        )
    header = record.find("oai:header", _NS)
    if header is not None and (header.get("status") or "") == "deleted":
        # A withdrawn work has no revision to pin. `documents.status` is where
        # that fact belongs, and the documents backfill already records it.
        return []

    revisions: list[Revision] = []
    for el in record.findall("oai:metadata/raw:arXivRaw/raw:version", _NS):
        label = (el.get("version") or "").strip()
        date_el = el.find("raw:date", _NS)
        raw_date = (date_el.text or "").strip() if date_el is not None else ""
        if not label or not raw_date:
            continue
        try:
            posted = parsedate_to_datetime(raw_date)
        except (TypeError, ValueError):
            continue
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=UTC)
        revisions.append(Revision(version=label, posted_at=posted))
    revisions.sort(key=lambda r: r.posted_at)
    return revisions


def parse_fetched_at(value: str) -> datetime:
    """Parse ``documents.fetched_at`` (ISO-8601 UTC) into an aware datetime."""
    text = (value or "").strip()
    if not text:
        raise VersionBackfillError("fetched_at is empty")
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise VersionBackfillError(
            f"fetched_at {value!r} is not ISO-8601"
        ) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def version_at(revisions: list[Revision], fetched_at: datetime) -> Revision | None:
    """The revision arXiv served for the bare id at ``fetched_at``.

    The LAST revision posted at or before that moment. ``None`` when every
    revision post-dates the fetch, which means either a clock skew or a
    ``fetched_at`` that does not describe this fetch — either way, not
    something to guess through.
    """
    eligible = [r for r in revisions if r.posted_at <= fetched_at]
    return eligible[-1] if eligible else None


# ---------------------------------------------------------------------------
# The DB, read-only until the moment it is not
# ---------------------------------------------------------------------------


def unversioned_rows(db_path: Path) -> list[tuple[str, str]]:
    """``[(work_id, fetched_at), …]`` for every row with no version.

    Opened ``mode=ro``. ``DocumentsStore.open`` would CREATE a missing file,
    and "this notebook was never backfilled" must stay observable.
    """
    if not db_path.is_file():
        raise VersionBackfillError(
            f"no documents.db at {db_path} — run "
            f"tools/notebook_documents_backfill.py first"
        )
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        return conn.execute(
            "SELECT work_id, fetched_at FROM documents "
            "WHERE arxiv_version = '' ORDER BY work_id"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        raise VersionBackfillError(f"{db_path}: {exc}") from exc
    finally:
        conn.close()


def apply_version(db_path: Path, work_id: str, version: str) -> bool:
    """Re-key one row from ``(work_id, '')`` to ``(work_id, version)``.

    ``False`` — a collision, nothing written — when ``(work_id, version)``
    already exists. Two rows for one revision would be two answers about the
    same bytes, and the one already there was written by a run with evidence
    this one does not have. Reported, never merged.

    ``arxiv_version`` is half the PRIMARY KEY, so this is an UPDATE of a key
    column: SQLite permits it and enforces uniqueness, which is what makes the
    collision surface as a caught ``IntegrityError`` rather than a silent
    overwrite.
    """
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "UPDATE documents SET arxiv_version = ? "
                "WHERE work_id = ? AND arxiv_version = ''",
                (version, work_id),
            )
        except sqlite3.IntegrityError:
            conn.execute("ROLLBACK")
            return False
        conn.execute("COMMIT")
        return True
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def backfill(
    slug: str,
    *,
    base: Path | None = None,
    dry_run: bool = False,
    user_agent: str = "",
    fetch=None,
    sleep=time.sleep,
) -> list[Outcome]:
    """Fill every establishable version for one notebook. Returns per-row outcomes.

    ``fetch`` is the test seam, matching ``oai_license.fetch_license``'s
    convention: production callers pass nothing and get the real HTTP path with
    its politeness contract.
    """
    validate_slug(slug)
    db_path = notebook_dir(slug, base=base) / DOCUMENTS_DB_FILENAME
    rows = unversioned_rows(db_path)
    if fetch is None:
        fetch = oai_license._fetch_record

    outcomes: list[Outcome] = []
    for index, (work_id, fetched_at) in enumerate(rows):
        # Politeness is sequenced across the run, not per call — the same
        # convention `notebook_documents_backfill` follows.
        if index:
            sleep(POLITENESS_SLEEP_SECONDS)
        outcomes.append(
            _one(work_id, fetched_at, db_path,
                 dry_run=dry_run, user_agent=user_agent, fetch=fetch)
        )
    return outcomes


def _one(
    work_id: str,
    fetched_at: str,
    db_path: Path,
    *,
    dry_run: bool,
    user_agent: str,
    fetch,
) -> Outcome:
    try:
        when = parse_fetched_at(fetched_at)
    except VersionBackfillError as exc:
        return Outcome(work_id, fetched_at, "abstained", reason=str(exc))

    url = oai_license.build_getrecord_url(work_id, metadata_prefix=METADATA_PREFIX)
    try:
        body = fetch(url, user_agent=user_agent)
        revisions = parse_versions(body, work_id=work_id)
    except VersionBackfillError as exc:
        return Outcome(work_id, fetched_at, "abstained", reason=str(exc))
    except Exception as exc:  # noqa: BLE001 - a transient fetch failure
        # NOT an abstention: an abstention is a fact about the paper, and this
        # is a fact about the network. Counted separately so a re-run after an
        # outage is obviously the right move.
        return Outcome(work_id, fetched_at, "failed",
                       reason=f"{type(exc).__name__}: {exc}")

    history = [
        {"version": r.version, "posted_at": r.posted_at.isoformat()}
        for r in revisions
    ]
    if not revisions:
        return Outcome(work_id, fetched_at, "abstained", history=history,
                       reason="the arXivRaw record carries no version history "
                              "(deleted, or not an arXiv work)")

    chosen = version_at(revisions, when)
    if chosen is None:
        return Outcome(
            work_id, fetched_at, "abstained", history=history,
            reason=(
                f"every revision post-dates fetched_at ({fetched_at}); the "
                f"earliest is {revisions[0].version} at "
                f"{revisions[0].posted_at.isoformat()}. Either the clock was "
                f"wrong or fetched_at does not describe this fetch, and "
                f"neither is safe to guess through."
            ),
        )

    if dry_run:
        return Outcome(work_id, fetched_at, "filled", version=chosen.version,
                       history=history, reason="dry run; nothing written")
    if not apply_version(db_path, work_id, chosen.version):
        return Outcome(
            work_id, fetched_at, "collided", version=chosen.version,
            history=history,
            reason=(
                f"a row for ({work_id}, {chosen.version}) already exists; "
                f"leaving the unversioned row alone rather than merging two "
                f"answers about the same revision"
            ),
        )
    return Outcome(work_id, fetched_at, "filled", version=chosen.version,
                   history=history)


def write_report(slug: str, outcomes: list[Outcome], *, base: Path | None) -> Path:
    """Persist the evidence behind every filled version.

    The column records ``v3``; this records WHY ``v3`` — the full posting
    history and the ``fetched_at`` that selected from it — so the inference is
    auditable by someone who was not standing here.
    """
    ops = notebook_dir(slug, base=base) / REPORT_DIR_NAME
    ops.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = ops / f"arxiv-version-backfill-{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "notebook": slug,
                "generated_at": datetime.now(UTC).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"),
                "method": (
                    "OAI-PMH arXivRaw version history, windowed by "
                    "documents.fetched_at. A filled version means: when this "
                    "notebook fetched this work, that was the revision arXiv "
                    "served for the bare id. It does not mean the stored "
                    "bytes were verified against that revision."
                ),
                "counts": summarize(outcomes),
                "rows": [
                    {
                        "work_id": o.work_id,
                        "fetched_at": o.fetched_at,
                        "verdict": o.verdict,
                        "version": o.version,
                        "reason": o.reason,
                        "version_history": o.history,
                    }
                    for o in outcomes
                ],
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    return path


def summarize(outcomes: list[Outcome]) -> dict[str, int]:
    counts = {"filled": 0, "abstained": 0, "collided": 0, "failed": 0}
    for outcome in outcomes:
        counts[outcome.verdict] += 1
    counts["total"] = len(outcomes)
    return counts


def run(
    slug: str,
    *,
    base: Path | None = None,
    dry_run: bool = False,
    contact_email: str | None = None,
) -> int:
    user_agent = build_user_agent(resolve_contact_email(contact_email))
    outcomes = backfill(slug, base=base, dry_run=dry_run, user_agent=user_agent)
    counts = summarize(outcomes)

    for outcome in outcomes:
        if outcome.verdict != "filled":
            print(f"  {outcome.verdict}: {outcome.work_id} — {outcome.reason}",
                  file=sys.stderr)

    if not dry_run and outcomes:
        print(f"report: {write_report(slug, outcomes, base=base)}")
    print(
        "filled={filled} abstained={abstained} collided={collided} "
        "failed={failed} total={total}".format(**counts)
    )
    if not outcomes:
        print(
            "  every row already carries a version; nothing to backfill.",
            file=sys.stderr,
        )
    return 1 if counts["failed"] else 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("slug", help="notebook slug")
    parser.add_argument(
        "--dry-run", action="store_true",
        help=(
            "fetch and decide, write nothing. Still hits the network — the "
            "decision IS the network call, so a dry run that skipped it would "
            "report nothing about what a real run would do."
        ),
    )
    parser.add_argument(
        "--notebooks-base", type=Path, default=None,
        help="notebooks base dir (default: var/arxmcp/notebooks/)",
    )
    parser.add_argument(
        "--contact-email", default=None,
        help="arXiv politeness contact (default: ARXMCP_CONTACT_EMAIL)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        return run(
            args.slug,
            base=args.notebooks_base,
            dry_run=args.dry_run,
            contact_email=args.contact_email,
        )
    except (VersionBackfillError, NotebookError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
