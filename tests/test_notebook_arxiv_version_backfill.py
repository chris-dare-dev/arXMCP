"""The version backfill, and the one thing it must never do: guess.

derived-alg-geo-lean **#171**. The column it fills is load-bearing across a
repo boundary — `statement_resolve.py` reads it to decide whether a `current`
verdict is honest — so the interesting assertions here are the ABSTENTIONS.
A backfill that filled every row would satisfy a naive "did it run" test and
would be the exact failure #171 was filed about, one layer down: a version
number that nothing establishes.

No network. The OAI-PMH fetch is injected, which is also how
`tools/oai_license.py`'s own tests do it.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools.notebook_arxiv_version_backfill import (
    METADATA_PREFIX,
    Outcome,
    Revision,
    VersionBackfillError,
    apply_version,
    backfill,
    parse_fetched_at,
    parse_versions,
    summarize,
    unversioned_rows,
    version_at,
    write_report,
)

WORK = "math/0212237"

#: Real arXivRaw shape: one `<version>` per revision, RFC 2822 dates, in the
#: `http://arxiv.org/OAI/arXivRaw/` namespace (NOT the plain `arXiv` one, which
#: carries no version history at all — that is why this format was chosen).
RAW_RECORD = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <GetRecord>
    <record>
      <header>
        <identifier>oai:arXiv.org:math/0212237</identifier>
        <datestamp>2007-05-23</datestamp>
      </header>
      <metadata>
        <arXivRaw xmlns="http://arxiv.org/OAI/arXivRaw/">
          <id>math/0212237</id>
          <version version="v1"><date>Tue, 17 Dec 2002 17:12:04 GMT</date></version>
          <version version="v2"><date>Mon, 3 Nov 2003 11:02:57 GMT</date></version>
          <version version="v3"><date>Wed, 23 May 2007 09:41:18 GMT</date></version>
          <title>Stability conditions on triangulated categories</title>
        </arXivRaw>
      </metadata>
    </record>
  </GetRecord>
</OAI-PMH>
"""

DELETED_RECORD = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <GetRecord>
    <record>
      <header status="deleted">
        <identifier>oai:arXiv.org:math/0212237</identifier>
        <datestamp>2024-01-01</datestamp>
      </header>
    </record>
  </GetRecord>
</OAI-PMH>
"""

NO_SUCH_ID = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <error code="idDoesNotExist">no such id</error>
</OAI-PMH>
"""

BAD_VERB = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <error code="badArgument">metadataPrefix is missing</error>
</OAI-PMH>
"""


# --- parsing ------------------------------------------------------------------

def test_the_full_version_history_is_read_oldest_first() -> None:
    revisions = parse_versions(RAW_RECORD.encode(), work_id=WORK)
    assert [r.version for r in revisions] == ["v1", "v2", "v3"]
    assert revisions[0].posted_at < revisions[1].posted_at < revisions[2].posted_at
    #: RFC 2822 dates parse to aware datetimes, or every comparison against
    #: `fetched_at` would raise instead of deciding.
    assert all(r.posted_at.tzinfo is not None for r in revisions)


def test_a_deleted_record_has_no_revision_to_pin() -> None:
    """A withdrawn work is `documents.status`'s business, not this column's."""
    assert parse_versions(DELETED_RECORD.encode(), work_id=WORK) == []


def test_id_does_not_exist_is_an_abstention_not_a_failure() -> None:
    """Nothing to retry: arXiv answered, and the answer was "no such work"."""
    assert parse_versions(NO_SUCH_ID.encode(), work_id=WORK) == []


def test_any_other_oai_error_is_raised() -> None:
    with pytest.raises(VersionBackfillError, match="badArgument"):
        parse_versions(BAD_VERB.encode(), work_id=WORK)


def test_a_non_xml_body_is_raised_rather_than_read_as_no_versions() -> None:
    """An HTML error page parsed as "no versions" would abstain quietly on
    every row of an outage, and the run would exit 0."""
    with pytest.raises(VersionBackfillError, match="not XML"):
        parse_versions(b"<html>503 Service Unavailable", work_id=WORK)


def test_the_plain_arxiv_namespace_is_not_read_by_accident() -> None:
    """`tools/oai_license.py` requests `metadataPrefix=arXiv`, whose records
    live in a different namespace and carry no `<version>` elements. If this
    parser matched on local name alone it would silently return `[]` for a
    correctly-fetched record and for a wrongly-fetched one alike."""
    wrong_ns = RAW_RECORD.replace(
        "http://arxiv.org/OAI/arXivRaw/", "http://arxiv.org/OAI/arXiv/"
    ).replace("arXivRaw>", "arXiv>").replace("<arXivRaw ", "<arXiv ")
    assert parse_versions(wrong_ns.encode(), work_id=WORK) == []
    assert METADATA_PREFIX == "arXivRaw"


# --- the window, which is the whole idea ---------------------------------------

def _at(text: str) -> datetime:
    return parse_fetched_at(text)


def test_the_version_chosen_is_the_one_arxiv_served_at_fetch_time() -> None:
    """Not the latest. The last revision posted at or before the fetch.

    This is the difference between a fact about the past — which no later
    revision can change — and a guess about which bytes we hold.
    """
    revisions = parse_versions(RAW_RECORD.encode())
    assert version_at(revisions, _at("2003-01-01T00:00:00Z")).version == "v1"
    assert version_at(revisions, _at("2004-06-01T00:00:00Z")).version == "v2"
    assert version_at(revisions, _at("2026-05-21T00:00:00Z")).version == "v3"


def test_a_fetch_predating_every_revision_abstains() -> None:
    """Clock skew, or a `fetched_at` that does not describe this fetch.

    Either way there is no revision it could have served, and inventing v1
    would be the fabrication this tool exists to avoid.
    """
    revisions = parse_versions(RAW_RECORD.encode())
    assert version_at(revisions, _at("2001-01-01T00:00:00Z")) is None


def test_a_fetch_exactly_on_a_posting_timestamp_takes_that_version() -> None:
    """The boundary is inclusive: a revision posted at T was being served at T."""
    revisions = parse_versions(RAW_RECORD.encode())
    assert version_at(revisions, revisions[1].posted_at).version == "v2"


@pytest.mark.parametrize("stamp", ["", "not-a-date", "2026-13-45"])
def test_an_unparseable_fetched_at_is_raised(stamp: str) -> None:
    with pytest.raises(VersionBackfillError):
        parse_fetched_at(stamp)


def test_a_naive_fetched_at_is_read_as_utc() -> None:
    """`documents.fetched_at` is documented ISO-8601 UTC and some rows carry no
    `Z`. Comparing a naive datetime to an aware one raises, so this is the
    difference between a decision and a crash mid-run."""
    assert parse_fetched_at("2026-05-21T09:00:00").tzinfo is UTC


# --- the database --------------------------------------------------------------

def _documents_db(tmp_path: Path, rows: list[tuple[str, str, str]]) -> Path:
    db = tmp_path / "documents.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE documents ("
        "  work_id TEXT NOT NULL, arxiv_version TEXT NOT NULL DEFAULT '',"
        "  fetched_at TEXT NOT NULL, PRIMARY KEY (work_id, arxiv_version))"
    )
    conn.executemany("INSERT INTO documents VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return db


def test_only_unversioned_rows_are_offered_for_backfill(tmp_path: Path) -> None:
    """A row that already names a version was written by something with
    evidence; this tool has no business re-deciding it."""
    db = _documents_db(tmp_path, [
        (WORK, "", "2026-05-21T09:00:00Z"),
        ("2101.04404", "v2", "2026-05-21T09:00:00Z"),
        ("1902.08184", "", "2026-05-21T09:00:00Z"),
    ])
    assert [w for w, _ in unversioned_rows(db)] == ["1902.08184", WORK]


def test_a_missing_documents_db_is_refused_not_created(tmp_path: Path) -> None:
    """`DocumentsStore.open` would create it, and a backfill that reports
    `total=0` against a database it just made is the loudest possible way to
    be quietly wrong."""
    db = tmp_path / "documents.db"
    with pytest.raises(VersionBackfillError, match="no documents.db"):
        unversioned_rows(db)
    assert not db.exists()


def test_applying_a_version_rekeys_the_row(tmp_path: Path) -> None:
    db = _documents_db(tmp_path, [(WORK, "", "2026-05-21T09:00:00Z")])
    assert apply_version(db, WORK, "v3") is True
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT arxiv_version FROM documents").fetchall() == [("v3",)]
    conn.close()


def test_a_collision_writes_nothing_and_reports(tmp_path: Path) -> None:
    """Two rows for one revision would be two answers about the same bytes.

    `arxiv_version` is half the PRIMARY KEY, so the UPDATE trips SQLite's
    uniqueness check rather than silently producing them — this asserts the
    trip is caught and the pre-existing row survives untouched.
    """
    db = _documents_db(tmp_path, [
        (WORK, "", "2026-05-21T09:00:00Z"),
        (WORK, "v3", "2026-01-01T00:00:00Z"),
    ])
    assert apply_version(db, WORK, "v3") is False
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT arxiv_version, fetched_at FROM documents ORDER BY arxiv_version"
    ).fetchall()
    conn.close()
    assert rows == [("", "2026-05-21T09:00:00Z"), ("v3", "2026-01-01T00:00:00Z")]


# --- end to end ----------------------------------------------------------------

def _fetcher(body: bytes | Exception):
    calls: list[str] = []

    def fetch(url: str, **_kwargs) -> bytes:
        calls.append(url)
        if isinstance(body, Exception):
            raise body
        return body

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def _notebook(tmp_path: Path, rows) -> tuple[Path, str]:
    slug = "bridgeland-stability"
    nb = tmp_path / slug
    nb.mkdir(parents=True)
    _documents_db(nb, rows)
    return tmp_path, slug


def test_a_run_fills_the_version_it_can_establish(tmp_path: Path) -> None:
    base, slug = _notebook(tmp_path, [(WORK, "", "2026-05-21T09:00:00Z")])
    fetch = _fetcher(RAW_RECORD.encode())
    outcomes = backfill(slug, base=base, fetch=fetch, sleep=lambda _s: None)
    assert [(o.verdict, o.version) for o in outcomes] == [("filled", "v3")]
    assert f"metadataPrefix={METADATA_PREFIX}" in fetch.calls[0]
    conn = sqlite3.connect(base / slug / "documents.db")
    assert conn.execute("SELECT arxiv_version FROM documents").fetchone() == ("v3",)
    conn.close()


def test_a_dry_run_decides_and_writes_nothing(tmp_path: Path) -> None:
    base, slug = _notebook(tmp_path, [(WORK, "", "2026-05-21T09:00:00Z")])
    outcomes = backfill(slug, base=base, dry_run=True,
                        fetch=_fetcher(RAW_RECORD.encode()), sleep=lambda _s: None)
    assert outcomes[0].verdict == "filled" and outcomes[0].version == "v3"
    conn = sqlite3.connect(base / slug / "documents.db")
    assert conn.execute("SELECT arxiv_version FROM documents").fetchone() == ("",)
    conn.close()


def test_a_transient_fetch_failure_is_not_an_abstention(tmp_path: Path) -> None:
    """They are different facts with different remedies. An abstention says
    something about the paper and is final; a failure says something about the
    network and means re-run. Folding them together would make an outage look
    like a corpus that cannot be versioned, and the run would exit 0."""
    base, slug = _notebook(tmp_path, [(WORK, "", "2026-05-21T09:00:00Z")])
    outcomes = backfill(slug, base=base,
                        fetch=_fetcher(RuntimeError("503 budget exhausted")),
                        sleep=lambda _s: None)
    assert outcomes[0].verdict == "failed"
    assert "503" in outcomes[0].reason
    assert summarize(outcomes) == {
        "filled": 0, "abstained": 0, "collided": 0, "failed": 1, "total": 1}


def test_a_deleted_work_abstains_and_the_row_stays_empty(tmp_path: Path) -> None:
    base, slug = _notebook(tmp_path, [(WORK, "", "2026-05-21T09:00:00Z")])
    outcomes = backfill(slug, base=base, fetch=_fetcher(DELETED_RECORD.encode()),
                        sleep=lambda _s: None)
    assert outcomes[0].verdict == "abstained"
    conn = sqlite3.connect(base / slug / "documents.db")
    assert conn.execute("SELECT arxiv_version FROM documents").fetchone() == ("",)
    conn.close()


def test_politeness_is_sequenced_across_the_run(tmp_path: Path) -> None:
    """One sleep between requests, none before the first — the convention
    `notebook_documents_backfill` established, so two backfills run
    back-to-back do not double the floor."""
    base, slug = _notebook(tmp_path, [
        (WORK, "", "2026-05-21T09:00:00Z"),
        ("2101.04404", "", "2026-05-21T09:00:00Z"),
        ("1902.08184", "", "2026-05-21T09:00:00Z"),
    ])
    slept: list[float] = []
    backfill(slug, base=base, fetch=_fetcher(RAW_RECORD.encode()),
             sleep=slept.append)
    assert slept == [3.0, 3.0]


def test_the_report_records_why_each_version_was_chosen(tmp_path: Path) -> None:
    """The column says `v3`. Nothing in the schema says WHY, and a version
    nobody can audit is the same defect #171 filed, one layer down."""
    base, slug = _notebook(tmp_path, [(WORK, "", "2026-05-21T09:00:00Z")])
    outcomes = backfill(slug, base=base, fetch=_fetcher(RAW_RECORD.encode()),
                        sleep=lambda _s: None)
    report = json.loads(write_report(slug, outcomes, base=base).read_text())

    assert report["notebook"] == slug
    assert report["counts"]["filled"] == 1
    row = report["rows"][0]
    assert row["version"] == "v3"
    assert row["fetched_at"] == "2026-05-21T09:00:00Z"
    #: The whole history, not just the chosen one — the selection is only
    #: checkable against the alternatives it was selected over.
    assert [v["version"] for v in row["version_history"]] == ["v1", "v2", "v3"]
    #: And the claim itself, spelled out, so nobody reads the column as
    #: "these bytes were verified against v3".
    assert "served for the bare id" in report["method"]


def test_the_summary_counts_every_outcome(tmp_path: Path) -> None:
    outcomes = [
        Outcome("a", "t", "filled", version="v1"),
        Outcome("b", "t", "abstained", reason="r"),
        Outcome("c", "t", "collided", version="v2", reason="r"),
        Outcome("d", "t", "failed", reason="r"),
    ]
    counts = summarize(outcomes)
    assert counts == {"filled": 1, "abstained": 1, "collided": 1,
                      "failed": 1, "total": 4}
    assert sum(v for k, v in counts.items() if k != "total") == counts["total"]


def test_revision_ordering_does_not_depend_on_document_order() -> None:
    """arXiv emits them in order today. The window is only correct if they are
    sorted, so it must not depend on that."""
    shuffled = RAW_RECORD.replace(
        '<version version="v1"><date>Tue, 17 Dec 2002 17:12:04 GMT</date></version>\n'
        '          <version version="v2"><date>Mon, 3 Nov 2003 11:02:57 GMT</date></version>',
        '<version version="v2"><date>Mon, 3 Nov 2003 11:02:57 GMT</date></version>\n'
        '          <version version="v1"><date>Tue, 17 Dec 2002 17:12:04 GMT</date></version>',
    )
    assert [r.version for r in parse_versions(shuffled.encode())] == \
        ["v1", "v2", "v3"]


def test_a_revision_with_an_unparseable_date_is_dropped_not_guessed() -> None:
    """It cannot take part in a date window, and giving it one would put it
    somewhere arbitrary in the ordering."""
    broken = RAW_RECORD.replace("Mon, 3 Nov 2003 11:02:57 GMT", "sometime in 2003")
    assert [r.version for r in parse_versions(broken.encode())] == ["v1", "v3"]


def test_revision_is_hashable_so_histories_can_be_compared() -> None:
    a = Revision("v1", datetime(2002, 12, 17, tzinfo=UTC))
    b = Revision("v1", datetime(2002, 12, 17, tzinfo=UTC))
    assert a == b and len({a, b}) == 1
