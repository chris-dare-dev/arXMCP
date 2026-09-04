"""Tests for ``tools.notebook_documents_backfill`` (source-truth-m1).

Mirrors ``tests/test_notebook_metadata_backfill.py``: happy path,
politeness (3s spacing, email enforced at run entry), idempotent re-run
(zero network egress), membership-from-``papers.txt``, the abstention
marker for old-style raw sources, the 3-way ``license_status`` mapping,
``idDoesNotExist`` as a non-fatal registration, transient-failure ->
per-id miss (row NOT written so a re-run retries), and — the STRUCTURAL
0-re-embed guarantee — that the driver imports no embedder / store /
LanceDB and touches no corpus artifacts. All offline: the OAI-PMH fetch
is a canned-XML seam and notebooks live under ``tmp_path``.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sqlite3
import textwrap
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path

import pytest

from server.documents_store import (
    DOCUMENTS_DB_FILENAME,
    RAW_SOURCE_STATUS_PRESENT,
    RAW_SOURCE_STATUS_UNAVAILABLE,
    DocumentsStore,
)
from tools import notebook_documents_backfill
from tools._notebook_common import NotebookError
from tools.arxiv_fetch import POLITENESS_SLEEP_SECONDS

SLUG = "bridgeland-stability"
NONEXCLUSIVE = "http://arxiv.org/licenses/nonexclusive-distrib/1.0/"
CC_BY = "http://creativecommons.org/licenses/by/4.0/"


# ---------------------------------------------------------------------------
# Canned OAI-PMH GetRecord XML + a URL-driven fetch seam
# ---------------------------------------------------------------------------


def _getrecord(paper_id, *, license_uri=NONEXCLUSIVE, deleted=False) -> bytes:
    if deleted:
        inner = f"""
          <record>
            <header status="deleted">
              <identifier>oai:arXiv.org:{paper_id}</identifier>
              <datestamp>2021-01-01</datestamp>
            </header>
          </record>
        """
    else:
        license_el = (
            f"<license>{license_uri}</license>" if license_uri is not None else ""
        )
        inner = f"""
          <record>
            <header>
              <identifier>oai:arXiv.org:{paper_id}</identifier>
              <datestamp>2020-06-22</datestamp>
            </header>
            <metadata>
              <arXiv xmlns="http://arxiv.org/OAI/arXiv/">
                <id>{paper_id}</id>
                {license_el}
              </arXiv>
            </metadata>
          </record>
        """
    return textwrap.dedent(
        f"""<?xml version="1.0" encoding="UTF-8"?>
        <OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
          <responseDate>2026-07-12T00:00:00Z</responseDate>
          <GetRecord>{inner}</GetRecord>
        </OAI-PMH>
        """
    ).encode("utf-8")


def _id_does_not_exist() -> bytes:
    return textwrap.dedent(
        """<?xml version="1.0" encoding="UTF-8"?>
        <OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
          <responseDate>2026-07-12T00:00:00Z</responseDate>
          <error code="idDoesNotExist">no such id</error>
        </OAI-PMH>
        """
    ).encode("utf-8")


def _id_from_url(url: str) -> str:
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    ident = qs["identifier"][0]
    return ident.split("oai:arXiv.org:", 1)[1]


def _fetch_for(outcomes: dict):
    """Build a fetch seam mapping a work id -> a canned outcome.

    Outcome tuples: ``("license", uri)`` / ``("nolicense",)`` /
    ``("deleted",)`` / ``("idnotfound",)`` / ``("fail",)`` (transient).
    """
    calls: list[str] = []

    def _fetch(url, *, timeout_seconds, user_agent):
        pid = _id_from_url(url)
        calls.append(pid)
        outcome = outcomes[pid]
        kind = outcome[0]
        if kind == "license":
            return _getrecord(pid, license_uri=outcome[1])
        if kind == "nolicense":
            return _getrecord(pid, license_uri=None)
        if kind == "deleted":
            return _getrecord(pid, deleted=True)
        if kind == "idnotfound":
            return _id_does_not_exist()
        if kind == "fail":
            raise RuntimeError("simulated transient OAI-PMH failure")
        raise AssertionError(f"unknown outcome {kind!r}")

    _fetch.calls = calls  # type: ignore[attr-defined]
    return _fetch


# ---------------------------------------------------------------------------
# Filesystem fixtures
# ---------------------------------------------------------------------------


def _make_notebook(tmp_path: Path, papers_txt: str) -> Path:
    base = tmp_path / "notebooks"
    nb_dir = base / SLUG
    nb_dir.mkdir(parents=True)
    (nb_dir / "papers.txt").write_text(papers_txt, encoding="utf-8")
    return base


def _make_corpus(
    tmp_path: Path,
    *,
    new_ids: list[str] = (),
    old_ids: list[str] = (),
) -> tuple[Path, Path]:
    """Create raw + parsed corpus dirs. new_ids get a raw tree + parsed
    index.html; old_ids get ONLY parsed index.html (raw abstention)."""
    raw_root = tmp_path / "corpus" / "raw"
    parsed_root = tmp_path / "corpus" / "parsed"
    for pid in new_ids:
        (raw_root / pid).mkdir(parents=True)
        (raw_root / pid / f"{pid}.tex").write_text(
            "\\documentclass{article}", encoding="utf-8",
        )
        (parsed_root / pid).mkdir(parents=True)
        (parsed_root / pid / "index.html").write_text(
            "<html>new</html>", encoding="utf-8",
        )
    for pid in old_ids:
        (parsed_root / pid).mkdir(parents=True)  # pid has '/', nests
        (parsed_root / pid / "index.html").write_text(
            "<html>old</html>", encoding="utf-8",
        )
    return raw_root, parsed_root


def _patch_email(monkeypatch, value="ops@example.com"):
    monkeypatch.setattr(
        notebook_documents_backfill, "resolve_contact_email", lambda _arg: value,
    )


def _store_get(base: Path, work_id: str, version: str = ""):
    db_path = base / SLUG / DOCUMENTS_DB_FILENAME

    async def _get():
        store = await DocumentsStore.open(db_path)
        try:
            return await store.get(work_id, version)
        finally:
            await store.close()

    return asyncio.run(_get())


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_registers_all_with_provenance_and_loud_summary(
        self, tmp_path, monkeypatch, capsys,
    ):
        base = _make_notebook(
            tmp_path,
            "0708.2247\n"
            "math/0212237\n"
            "# hep-th/0403166 excluded from the denominator\n"
            "2006.10956v1\n",
        )
        raw_root, parsed_root = _make_corpus(
            tmp_path,
            new_ids=["0708.2247", "2006.10956"],
            old_ids=["math/0212237"],
        )
        fetch = _fetch_for({
            "0708.2247": ("license", NONEXCLUSIVE),
            "math/0212237": ("nolicense",),
            "2006.10956": ("license", CC_BY),
        })
        _patch_email(monkeypatch)

        exit_code = notebook_documents_backfill.run(
            SLUG, base=base, corpus_raw_dir=raw_root,
            corpus_parsed_dir=parsed_root, sleep=lambda _s: None, fetch=fetch,
        )

        assert exit_code == 0
        tokens = capsys.readouterr().out.split()
        assert "registered=3" in tokens
        assert "skipped=0" in tokens
        assert "missing=0" in tokens
        assert "malformed=0" in tokens
        assert "unique=3" in tokens
        assert "total=3" in tokens  # commented line excluded
        assert "eligible=1" in tokens
        assert "not-allowlisted-open=1" in tokens
        assert "unknown=1" in tokens
        assert "present=2" in tokens
        assert "unavailable=1" in tokens

        # New-style row: raw present + parse present + not-allowlisted-open.
        r_new = _store_get(base, "0708.2247")
        assert r_new is not None
        assert r_new.raw_source_status == RAW_SOURCE_STATUS_PRESENT
        assert r_new.raw_source_sha256 and len(r_new.raw_source_sha256) == 64
        assert r_new.parse_artifact_sha256 and len(r_new.parse_artifact_sha256) == 64
        assert r_new.license_status == "not-allowlisted-open"
        assert r_new.chunker_version == "v1.1"
        assert r_new.parser_used is None
        assert r_new.latexml_version is None
        assert r_new.status == "active"

        # Old-style row: abstention marker + parse still computed.
        r_old = _store_get(base, "math/0212237")
        assert r_old is not None
        assert r_old.raw_source_sha256 is None
        assert r_old.raw_source_status == RAW_SOURCE_STATUS_UNAVAILABLE
        assert r_old.parse_artifact_sha256 is not None
        assert r_old.license_status == "unknown"
        # bare-number id is NOT a key (prefix preserved).
        assert _store_get(base, "0212237") is None

        # Versioned membership row: keyed by (work_id, 'v1').
        r_ver = _store_get(base, "2006.10956", "v1")
        assert r_ver is not None
        assert r_ver.license_status == "eligible"
        assert _store_get(base, "2006.10956", "") is None


# ---------------------------------------------------------------------------
# Politeness
# ---------------------------------------------------------------------------


class TestPoliteness:
    def test_three_second_spacing_between_requests(self, tmp_path, monkeypatch):
        base = _make_notebook(tmp_path, "2307.00001\n2307.00002\n2307.00003\n")
        raw_root, parsed_root = _make_corpus(
            tmp_path, new_ids=["2307.00001", "2307.00002", "2307.00003"],
        )
        fetch = _fetch_for({
            "2307.00001": ("license", NONEXCLUSIVE),
            "2307.00002": ("license", NONEXCLUSIVE),
            "2307.00003": ("license", NONEXCLUSIVE),
        })
        _patch_email(monkeypatch)
        sleeps: list[float] = []

        exit_code = notebook_documents_backfill.run(
            SLUG, base=base, corpus_raw_dir=raw_root,
            corpus_parsed_dir=parsed_root, sleep=sleeps.append, fetch=fetch,
        )

        assert exit_code == 0
        # One GetRecord per paper (no id_list batching) -> a politeness
        # sleep BEFORE every request except the first.
        assert sleeps == [POLITENESS_SLEEP_SECONDS, POLITENESS_SLEEP_SECONDS]

    def test_email_enforced_at_run_entry_before_any_fetch(
        self, tmp_path, monkeypatch,
    ):
        base = _make_notebook(tmp_path, "2307.00001\n")
        fetch = _fetch_for({"2307.00001": ("license", NONEXCLUSIVE)})

        def _no_email(_arg):
            raise NotebookError("no contact email available")

        monkeypatch.setattr(
            notebook_documents_backfill, "resolve_contact_email", _no_email,
        )
        with pytest.raises(NotebookError, match="contact email"):
            notebook_documents_backfill.run(
                SLUG, base=base, sleep=lambda _s: None, fetch=fetch,
            )
        assert fetch.calls == []


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_rerun_is_noop_with_zero_network_egress(
        self, tmp_path, monkeypatch, capsys,
    ):
        base = _make_notebook(tmp_path, "0708.2247\nmath/0212237\n")
        raw_root, parsed_root = _make_corpus(
            tmp_path, new_ids=["0708.2247"], old_ids=["math/0212237"],
        )
        fetch = _fetch_for({
            "0708.2247": ("license", NONEXCLUSIVE),
            "math/0212237": ("nolicense",),
        })
        _patch_email(monkeypatch)

        first = notebook_documents_backfill.run(
            SLUG, base=base, corpus_raw_dir=raw_root,
            corpus_parsed_dir=parsed_root, sleep=lambda _s: None, fetch=fetch,
        )
        assert first == 0
        assert len(fetch.calls) == 2
        capsys.readouterr()

        second = notebook_documents_backfill.run(
            SLUG, base=base, corpus_raw_dir=raw_root,
            corpus_parsed_dir=parsed_root, sleep=lambda _s: None, fetch=fetch,
        )
        assert second == 0
        assert len(fetch.calls) == 2  # NO new request on the re-run
        tokens = capsys.readouterr().out.split()
        assert "registered=0" in tokens
        assert "skipped=2" in tokens
        assert "missing=0" in tokens


    def test_a_rerun_after_the_version_backfill_is_still_a_noop(
        self, tmp_path, monkeypatch, capsys,
    ):
        """derived-alg-geo-lean #1086. The gate keyed on
        ``(work_id, arxiv_version)``, and ``arxiv_version`` is exactly the
        field ``notebook_arxiv_version_backfill`` fills in.

        So once a version landed, ``papers.txt``'s ``('0708.2247', '')`` no
        longer matched the registry's ``('0708.2247', 'v2')``, the gate said
        "not registered", and a re-run added a SECOND row for the same work at
        the empty version — plus an OAI-PMH request to do it. Measured on the
        two live notebooks the day #171's backfill first ran: 68 of 68 would
        have been re-registered.
        """
        base = _make_notebook(tmp_path, "0708.2247\nmath/0212237\n")
        raw_root, parsed_root = _make_corpus(
            tmp_path, new_ids=["0708.2247"], old_ids=["math/0212237"],
        )
        fetch = _fetch_for({
            "0708.2247": ("license", NONEXCLUSIVE),
            "math/0212237": ("nolicense",),
        })
        _patch_email(monkeypatch)
        assert notebook_documents_backfill.run(
            SLUG, base=base, corpus_raw_dir=raw_root,
            corpus_parsed_dir=parsed_root, sleep=lambda _s: None, fetch=fetch,
        ) == 0
        capsys.readouterr()

        # What #171's backfill does: re-key each row to a concrete version.
        db_path = base / SLUG / DOCUMENTS_DB_FILENAME
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE documents SET arxiv_version = 'v2' "
                "WHERE work_id = '0708.2247'"
            )
            conn.commit()
        finally:
            conn.close()

        assert notebook_documents_backfill.run(
            SLUG, base=base, corpus_raw_dir=raw_root,
            corpus_parsed_dir=parsed_root, sleep=lambda _s: None, fetch=fetch,
        ) == 0
        tokens = capsys.readouterr().out.split()
        assert "registered=0" in tokens, "a versioned row must still count as registered"
        assert "skipped=2" in tokens
        assert len(fetch.calls) == 2, "a re-run must make no new request"

        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT work_id, arxiv_version FROM documents ORDER BY work_id"
            ).fetchall()
        finally:
            conn.close()
        assert rows == [("0708.2247", "v2"), ("math/0212237", "")], (
            "the filled version must survive; no unversioned twin beside it"
        )

    def test_an_explicit_seed_version_still_keys_on_the_pair(
        self, tmp_path, monkeypatch, capsys,
    ):
        """A seed line naming ``0708.2247v2`` asks for that revision.

        (The seed syntax is arXiv's own versioned id, ``<id>vN``. The ``@vN``
        spelling in this driver's own docstrings is a DISPLAY label -- 
        ``is_valid_arxiv_paper_id`` rejects it as malformed.)

        Registering ``v2`` beside an existing ``v1`` is the point of a
        per-revision registry, so the work-level gate must NOT swallow it —
        otherwise #1086's fix would trade one silent behaviour for another.
        """
        base = _make_notebook(tmp_path, "0708.2247v2\n")
        raw_root, parsed_root = _make_corpus(tmp_path, new_ids=["0708.2247"])
        fetch = _fetch_for({"0708.2247": ("license", NONEXCLUSIVE)})
        _patch_email(monkeypatch)

        db_path = base / SLUG / DOCUMENTS_DB_FILENAME
        db_path.parent.mkdir(parents=True, exist_ok=True)
        notebook_documents_backfill.run(
            SLUG, base=base, corpus_raw_dir=raw_root,
            corpus_parsed_dir=parsed_root, sleep=lambda _s: None, fetch=fetch,
        )
        capsys.readouterr()

        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO documents "
                "(work_id, arxiv_version, raw_source_status, chunker_version, "
                " fetched_at, license_status, status) "
                "VALUES ('0708.2247', 'v1', 'present', 'v1', "
                " '2026-01-01T00:00:00+00:00', 'unknown', 'active')"
            )
            conn.commit()
            before = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        finally:
            conn.close()
        assert before == 2

        notebook_documents_backfill.run(
            SLUG, base=base, corpus_raw_dir=raw_root,
            corpus_parsed_dir=parsed_root, sleep=lambda _s: None, fetch=fetch,
        )
        assert "skipped=1" in capsys.readouterr().out.split()


# ---------------------------------------------------------------------------
# fetched_at is evidence, not a clock reading (#1086)
# ---------------------------------------------------------------------------


class TestFetchedAt:
    def test_fetched_at_is_the_parse_artifacts_mtime_not_now(
        self, tmp_path, monkeypatch,
    ):
        """It is read as *when this notebook fetched this work*.

        ``tools/notebook_arxiv_version_backfill.py`` windows arXiv's revision
        history by this field. Stamped with ``now()``, that question silently
        becomes "which revision is arXiv serving today", and writing today's
        latest onto bytes fetched months ago is the fabrication that tool
        exists to prevent. Observed on 2026-09-04: every row read 2026-09-04
        while the artifacts it described were written 2026-05-21.
        """
        base = _make_notebook(tmp_path, "0708.2247\n")
        raw_root, parsed_root = _make_corpus(tmp_path, new_ids=["0708.2247"])
        index = parsed_root / "0708.2247" / "index.html"
        parsed_when = datetime(2026, 5, 21, 15, 45, tzinfo=UTC)
        os.utime(index, (parsed_when.timestamp(), parsed_when.timestamp()))

        _patch_email(monkeypatch)
        notebook_documents_backfill.run(
            SLUG, base=base, corpus_raw_dir=raw_root,
            corpus_parsed_dir=parsed_root, sleep=lambda _s: None,
            fetch=_fetch_for({"0708.2247": ("license", NONEXCLUSIVE)}),
        )

        record = _store_get(base, "0708.2247")
        assert datetime.fromisoformat(record.fetched_at) == parsed_when

    def test_the_version_backfill_windows_on_it_and_gets_the_old_answer(
        self, tmp_path, monkeypatch,
    ):
        """The end-to-end point of #1086, on the two tools together.

        A paper parsed in May and revised in July: the version this corpus
        holds is the May one. With `now()` in `fetched_at` the window lands
        after the revision and records the July one — a version pin confirmed
        by bytes of a different revision, which is precisely #171's failure
        one layer down.
        """
        from tools.notebook_arxiv_version_backfill import Revision, parse_fetched_at, version_at

        base = _make_notebook(tmp_path, "0708.2247\n")
        raw_root, parsed_root = _make_corpus(tmp_path, new_ids=["0708.2247"])
        index = parsed_root / "0708.2247" / "index.html"
        parsed_when = datetime(2026, 5, 21, 15, 45, tzinfo=UTC)
        os.utime(index, (parsed_when.timestamp(), parsed_when.timestamp()))

        _patch_email(monkeypatch)
        notebook_documents_backfill.run(
            SLUG, base=base, corpus_raw_dir=raw_root,
            corpus_parsed_dir=parsed_root, sleep=lambda _s: None,
            fetch=_fetch_for({"0708.2247": ("license", NONEXCLUSIVE)}),
        )

        history = [
            Revision("v1", datetime(2020, 1, 1, tzinfo=UTC)),
            Revision("v2", datetime(2026, 7, 1, tzinfo=UTC)),   # after the parse
        ]
        record = _store_get(base, "0708.2247")
        assert version_at(history, parse_fetched_at(record.fetched_at)).version == "v1"
        #: And what the old behaviour would have produced, for contrast.
        assert version_at(history, datetime.now(UTC)).version == "v2"


    def test_repair_rewrites_only_fetched_at_and_needs_no_network(
        self, tmp_path, monkeypatch, capsys,
    ):
        """The other half of #1086: reaching rows already written.

        The fix corrects what a FUTURE registration records and touches none
        of the existing rows -- it cannot, because they are correctly skipped
        as registered. So a repair path exists, and it moves exactly one
        column: a repair that re-derived checksums could quietly ADOPT a
        corpus that changed underneath it, which is a different operation
        wearing this one's name.
        """
        base = _make_notebook(tmp_path, "0708.2247\n")
        raw_root, parsed_root = _make_corpus(tmp_path, new_ids=["0708.2247"])
        _patch_email(monkeypatch)
        fetch = _fetch_for({"0708.2247": ("license", NONEXCLUSIVE)})
        notebook_documents_backfill.run(
            SLUG, base=base, corpus_raw_dir=raw_root,
            corpus_parsed_dir=parsed_root, sleep=lambda _s: None, fetch=fetch,
        )
        before = _store_get(base, "0708.2247")

        # Move the artifact back in time, as a May ingest registered in
        # September looks.
        index = parsed_root / "0708.2247" / "index.html"
        when = datetime(2026, 5, 21, 15, 45, tzinfo=UTC)
        os.utime(index, (when.timestamp(), when.timestamp()))
        capsys.readouterr()

        # A dry run reports and writes nothing.
        notebook_documents_backfill.run(
            SLUG, base=base, corpus_parsed_dir=parsed_root,
            repair_fetched_at=True, dry_run=True,
        )
        assert "repaired=1" in capsys.readouterr().out
        assert _store_get(base, "0708.2247").fetched_at == before.fetched_at

        notebook_documents_backfill.run(
            SLUG, base=base, corpus_parsed_dir=parsed_root,
            repair_fetched_at=True,
        )
        after = _store_get(base, "0708.2247")
        assert datetime.fromisoformat(after.fetched_at) == when
        #: Every other column round-trips untouched.
        for f in ("work_id", "arxiv_version", "raw_source_sha256",
                  "raw_source_status", "parse_artifact_sha256",
                  "chunker_version", "license_uri", "license_status", "status"):
            assert getattr(after, f) == getattr(before, f), f
        #: And no request was made -- the artifact's mtime is the whole input.
        assert len(fetch.calls) == 1

    def test_repair_is_idempotent(self, tmp_path, monkeypatch, capsys):
        base = _make_notebook(tmp_path, "0708.2247\n")
        raw_root, parsed_root = _make_corpus(tmp_path, new_ids=["0708.2247"])
        _patch_email(monkeypatch)
        notebook_documents_backfill.run(
            SLUG, base=base, corpus_raw_dir=raw_root,
            corpus_parsed_dir=parsed_root, sleep=lambda _s: None,
            fetch=_fetch_for({"0708.2247": ("license", NONEXCLUSIVE)}),
        )
        notebook_documents_backfill.run(
            SLUG, base=base, corpus_parsed_dir=parsed_root, repair_fetched_at=True)
        capsys.readouterr()
        notebook_documents_backfill.run(
            SLUG, base=base, corpus_parsed_dir=parsed_root, repair_fetched_at=True)
        assert "repaired=0" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The 3-way license_status + status mapping
# ---------------------------------------------------------------------------


class TestStatusMapping:
    def test_three_way_license_status_and_withdrawn(
        self, tmp_path, monkeypatch,
    ):
        base = _make_notebook(
            tmp_path,
            "2401.00001\n2401.00002\n2401.00003\n2401.00004\n",
        )
        raw_root, parsed_root = _make_corpus(
            tmp_path,
            new_ids=["2401.00001", "2401.00002", "2401.00003", "2401.00004"],
        )
        fetch = _fetch_for({
            "2401.00001": ("license", CC_BY),        # eligible
            "2401.00002": ("license", NONEXCLUSIVE),  # not-allowlisted-open
            "2401.00003": ("nolicense",),             # unknown
            "2401.00004": ("deleted",),               # withdrawn
        })
        _patch_email(monkeypatch)

        exit_code = notebook_documents_backfill.run(
            SLUG, base=base, corpus_raw_dir=raw_root,
            corpus_parsed_dir=parsed_root, sleep=lambda _s: None, fetch=fetch,
        )
        assert exit_code == 0

        assert _store_get(base, "2401.00001").license_status == "eligible"
        assert _store_get(base, "2401.00002").license_status == "not-allowlisted-open"
        assert _store_get(base, "2401.00003").license_status == "unknown"
        r4 = _store_get(base, "2401.00004")
        assert r4.status == "withdrawn"
        assert r4.license_status == "unknown"
        assert r4.license_uri is None


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


class TestFailureModes:
    def test_id_does_not_exist_registers_unknown_nonfatal(
        self, tmp_path, monkeypatch, capsys,
    ):
        """``idDoesNotExist`` is a TERMINAL answer (arXiv genuinely lacks
        the id), NOT a transient miss: the row IS written with
        license_status=unknown and the run exits 0."""
        base = _make_notebook(tmp_path, "2401.99999\n")
        raw_root, parsed_root = _make_corpus(tmp_path, new_ids=["2401.99999"])
        fetch = _fetch_for({"2401.99999": ("idnotfound",)})
        _patch_email(monkeypatch)

        exit_code = notebook_documents_backfill.run(
            SLUG, base=base, corpus_raw_dir=raw_root,
            corpus_parsed_dir=parsed_root, sleep=lambda _s: None, fetch=fetch,
        )
        assert exit_code == 0
        assert "registered=1" in capsys.readouterr().out.split()
        rec = _store_get(base, "2401.99999")
        assert rec is not None
        assert rec.license_status == "unknown"
        assert rec.status == "active"

    def test_transient_failure_is_per_id_miss_and_rerun_retries(
        self, tmp_path, monkeypatch, capsys,
    ):
        """A transient fetch failure writes NO row (so a re-run retries),
        is a per-id miss, and fails the run loudly (exit 1)."""
        base = _make_notebook(tmp_path, "2401.00001\n2401.00002\n")
        raw_root, parsed_root = _make_corpus(
            tmp_path, new_ids=["2401.00001", "2401.00002"],
        )
        fetch = _fetch_for({
            "2401.00001": ("license", NONEXCLUSIVE),
            "2401.00002": ("fail",),
        })
        _patch_email(monkeypatch)

        exit_code = notebook_documents_backfill.run(
            SLUG, base=base, corpus_raw_dir=raw_root,
            corpus_parsed_dir=parsed_root, sleep=lambda _s: None, fetch=fetch,
        )
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "registered=1" in captured.out.split()
        assert "missing=1" in captured.out.split()
        assert "2401.00002" in captured.err
        assert "reason=oai_error" in captured.err
        # No row for the failed id -> a re-run will retry it.
        assert _store_get(base, "2401.00002") is None
        assert _store_get(base, "2401.00001") is not None

        # Re-run with the transient failure cleared: the missed id is
        # retried (only it — the registered one is skipped).
        fetch2 = _fetch_for({
            "2401.00001": ("license", NONEXCLUSIVE),
            "2401.00002": ("license", CC_BY),
        })
        capsys.readouterr()
        exit_code2 = notebook_documents_backfill.run(
            SLUG, base=base, corpus_raw_dir=raw_root,
            corpus_parsed_dir=parsed_root, sleep=lambda _s: None, fetch=fetch2,
        )
        assert exit_code2 == 0
        assert fetch2.calls == ["2401.00002"]  # only the previously-missed id
        assert _store_get(base, "2401.00002").license_status == "eligible"

    def test_malformed_lines_counted_never_fetched(
        self, tmp_path, monkeypatch, capsys,
    ):
        base = _make_notebook(tmp_path, "not-an-arxiv-id!\n2307.00001\n")
        raw_root, parsed_root = _make_corpus(tmp_path, new_ids=["2307.00001"])
        fetch = _fetch_for({"2307.00001": ("license", NONEXCLUSIVE)})
        _patch_email(monkeypatch)

        exit_code = notebook_documents_backfill.run(
            SLUG, base=base, corpus_raw_dir=raw_root,
            corpus_parsed_dir=parsed_root, sleep=lambda _s: None, fetch=fetch,
        )
        assert exit_code == 1
        captured = capsys.readouterr()
        tokens = captured.out.split()
        assert "malformed=1" in tokens
        assert "registered=1" in tokens
        assert "not-an-arxiv-id!" in captured.err
        assert fetch.calls == ["2307.00001"]  # malformed id never fetched

    def test_missing_papers_txt_raises_notebook_error(self, tmp_path, monkeypatch):
        base = tmp_path / "notebooks"
        (base / SLUG).mkdir(parents=True)  # notebook dir, no papers.txt
        _patch_email(monkeypatch)
        with pytest.raises(NotebookError, match="papers.txt"):
            notebook_documents_backfill.run(
                SLUG, base=base, sleep=lambda _s: None,
                fetch=_fetch_for({}),
            )


# ---------------------------------------------------------------------------
# The STRUCTURAL 0-re-embed guarantee
# ---------------------------------------------------------------------------


class TestZeroReEmbed:
    def test_driver_imports_no_embedder_store_or_lancedb(self):
        """0-re-embed is STRUCTURAL: the driver must never even import
        the embedder / LanceDB writer, so it cannot re-embed a chunk.

        Scans IMPORT LINES only (not prose) so the module docstring —
        which names ``ingest.store`` precisely to say it is NOT
        imported — doesn't false-positive."""
        source = inspect.getsource(notebook_documents_backfill)
        import_block = "\n".join(
            line for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        )
        assert "ingest.store" not in import_block
        assert "ingest.embedder" not in import_block
        assert "lancedb" not in import_block
        assert "embed_paper" not in import_block

    def test_run_touches_no_corpus_or_lancedb_artifacts(
        self, tmp_path, monkeypatch,
    ):
        """A backfill run leaves any pre-existing LanceDB artifacts
        byte-identical and writes ONLY its own registry DB — the
        row-count/corpus-version-unchanged acceptance, expressed via a
        sentinel since the driver never opens LanceDB at all."""
        base = _make_notebook(tmp_path, "0708.2247\n")
        raw_root, parsed_root = _make_corpus(tmp_path, new_ids=["0708.2247"])
        # A stand-in for the notebook's LanceDB dataset + corpus marker.
        nb_dir = base / SLUG
        lancedb_dir = nb_dir / "lancedb"
        lancedb_dir.mkdir()
        marker = lancedb_dir / "chunks.marker"
        marker.write_bytes(b"corpus_version=CV-DO-NOT-TOUCH")
        marker_before = marker.read_bytes()
        version_file = nb_dir / "corpus-version.json"
        version_file.write_text('{"corpus_version":"CV1"}', encoding="utf-8")
        version_before = version_file.read_text(encoding="utf-8")

        fetch = _fetch_for({"0708.2247": ("license", NONEXCLUSIVE)})
        _patch_email(monkeypatch)
        exit_code = notebook_documents_backfill.run(
            SLUG, base=base, corpus_raw_dir=raw_root,
            corpus_parsed_dir=parsed_root, sleep=lambda _s: None, fetch=fetch,
        )

        assert exit_code == 0
        # The LanceDB marker + corpus-version are untouched.
        assert marker.read_bytes() == marker_before
        assert version_file.read_text(encoding="utf-8") == version_before
        assert list(lancedb_dir.iterdir()) == [marker]  # no new lancedb files
        # The registry DB WAS written.
        assert (nb_dir / DOCUMENTS_DB_FILENAME).is_file()


# ---------------------------------------------------------------------------
# Membership source
# ---------------------------------------------------------------------------


class TestMembershipSource:
    def test_driver_never_reads_the_empty_junction_table(self):
        """Silent-zero guard: membership MUST come from papers.txt, never
        the empty ``notebook_papers`` junction table."""
        source = inspect.getsource(notebook_documents_backfill)
        assert "NotebooksStore" not in source
        assert "server.notebooks_store" not in source
        assert "read_paper_ids_from_papers_txt" in source


# ---------------------------------------------------------------------------
# Missing parse artifact (adversary M1)
# ---------------------------------------------------------------------------


class TestParseArtifactAbsent:
    def test_missing_index_html_is_a_per_id_miss_not_a_silent_null(
        self, tmp_path, monkeypatch, capsys,
    ):
        """A papers.txt member with a raw tree + OAI license but NO parsed
        index.html is routed to a per-id MISS (row withheld, re-run retries),
        never a row with a silent NULL parse checksum (adversary M1)."""
        base = _make_notebook(tmp_path, "0708.2247\n2006.10956v1\n")
        # 0708.2247: full corpus. 2006.10956: a raw tree present but NO
        # parsed index.html (a parse-failure / not-yet-parsed member).
        raw_root, parsed_root = _make_corpus(tmp_path, new_ids=["0708.2247"])
        (raw_root / "2006.10956").mkdir(parents=True)
        (raw_root / "2006.10956" / "2006.10956.tex").write_text(
            "\\documentclass{article}", encoding="utf-8",
        )
        fetch = _fetch_for({
            "0708.2247": ("license", NONEXCLUSIVE),
            "2006.10956": ("license", CC_BY),
        })
        _patch_email(monkeypatch)

        notebook_documents_backfill.run(
            SLUG, base=base, corpus_raw_dir=raw_root,
            corpus_parsed_dir=parsed_root, sleep=lambda _s: None, fetch=fetch,
        )

        captured = capsys.readouterr()
        tokens = (captured.out + " " + captured.err).split()
        assert "registered=1" in tokens   # only the fully-provenanced sibling
        assert "missing=1" in tokens       # the no-parse member is withheld
        # No row for the member missing its parse artifact (not a NULL row) ...
        assert _store_get(base, "2006.10956", "v1") is None
        # ... and its provenance-complete sibling IS registered.
        assert _store_get(base, "0708.2247") is not None
