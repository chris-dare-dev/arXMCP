"""Tests for ``tools.notebook_metadata_backfill`` (paper-metadata-m1).

t-backfill-driver acceptance: politeness contract (3 s spacing,
resolved contact email on every request, run-entry enforcement),
idempotent re-run (zero network egress), loud hydrated/total summary
line, per-id miss reasons, clamped 429/503 backoff, and poisoned-batch
per-id fallback. All offline: the HTTP layer is mocked via
``monkeypatch.setattr(_arxiv_api, "_fetch_url", …)`` (the repo's
standard pattern) and notebooks live under ``tmp_path``.
"""

from __future__ import annotations

import asyncio
import email.message
import inspect
import urllib.error
import urllib.parse
from pathlib import Path

import pytest

from server.paper_metadata_store import (
    PAPER_METADATA_DB_FILENAME,
    PaperMetadataStore,
)
from tools import _arxiv_api, notebook_metadata_backfill
from tools._notebook_common import NotebookError
from tools.arxiv_fetch import DEFAULT_503_BACKOFF_SECONDS, POLITENESS_SLEEP_SECONDS

SLUG = "bridgeland-stability"

_ERROR_FEED = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<feed xmlns="http://www.w3.org/2005/Atom"'
    b' xmlns:arxiv="http://arxiv.org/schemas/atom">'
    b"<entry>"
    b"<id>http://arxiv.org/api/errors#incorrect_id_list</id>"
    b"<summary>malformed id_list</summary>"
    b"</entry></feed>"
)


def _entry(paper_id_versioned: str, title: str = "A real title") -> str:
    return (
        f"<entry>"
        f"<id>http://arxiv.org/abs/{paper_id_versioned}</id>"
        f"<title>{title}</title>"
        f"<published>2007-08-16T00:00:00Z</published>"
        f"<summary>An abstract about stability conditions.</summary>"
        f"<author><name>A. Author</name></author>"
        f'<category term="math.AG"/>'
        f'<arxiv:primary_category term="math.AG"/>'
        f"</entry>"
    )


def _feed_for_ids(ids_versioned: list[str]) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom"'
        ' xmlns:arxiv="http://arxiv.org/schemas/atom">'
        f"{''.join(_entry(i) for i in ids_versioned)}</feed>"
    ).encode()


def _requested_ids(url: str) -> list[str]:
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return qs["id_list"][0].split(",")


def _make_notebook(tmp_path: Path, papers_txt: str) -> Path:
    """Create ``<base>/<SLUG>/papers.txt``; return the notebooks base."""
    base = tmp_path / "notebooks"
    nb_dir = base / SLUG
    nb_dir.mkdir(parents=True)
    (nb_dir / "papers.txt").write_text(papers_txt, encoding="utf-8")
    return base


def _patch_email(monkeypatch: pytest.MonkeyPatch, value: str = "ops@example.com"):
    monkeypatch.setattr(
        notebook_metadata_backfill,
        "resolve_contact_email",
        lambda _arg: value,
    )


def _store_get(base: Path, paper_id: str):
    db_path = base / SLUG / PAPER_METADATA_DB_FILENAME

    async def _get():
        store = await PaperMetadataStore.open(db_path)
        try:
            return await store.get(paper_id)
        finally:
            await store.close()

    return asyncio.run(_get())


class TestHappyPath:
    def test_hydrates_all_ids_and_prints_loud_summary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
    ) -> None:
        base = _make_notebook(
            tmp_path,
            "0708.2247\n"
            "math/0212237\n"
            "# hep-th/0403166 ar5iv-skipped — excluded from the denominator\n"
            "2303.07061\n",
        )
        calls: list[tuple[str, str | None]] = []

        def _stub(url: str, contact_email: str | None = None) -> bytes:
            calls.append((url, contact_email))
            # The API echoes VERSIONED abs URLs — the driver must
            # still key rows by the requested unversioned id.
            return _feed_for_ids(["0708.2247v1", "math/0212237v3", "2303.07061v2"])

        monkeypatch.setattr(_arxiv_api, "_fetch_url", _stub)
        _patch_email(monkeypatch)

        exit_code = notebook_metadata_backfill.run(
            SLUG, base=base, sleep=lambda _s: None,
        )

        assert exit_code == 0
        tokens = capsys.readouterr().out.split()
        assert "hydrated=3" in tokens
        assert "skipped=0" in tokens
        assert "missing=0" in tokens
        assert "malformed=0" in tokens
        assert "total=3" in tokens  # commented line excluded
        # One batched id_list request, polite UA email threaded through.
        assert len(calls) == 1
        url, contact_email = calls[0]
        assert contact_email == "ops@example.com"
        assert _requested_ids(url) == ["0708.2247", "math/0212237", "2303.07061"]
        # max_results pinned to the batch size (the default-10 footgun).
        assert "max_results=3" in url
        # Old-style id round-trips into the store with prefix intact.
        rec = _store_get(base, "math/0212237")
        assert rec is not None
        assert rec.title and rec.authors
        assert _store_get(base, "0212237") is None

    def test_versioned_and_duplicate_lines_normalize_to_one_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
    ) -> None:
        base = _make_notebook(tmp_path, "2307.01156v2\n2307.01156\n")
        monkeypatch.setattr(
            _arxiv_api, "_fetch_url",
            lambda url, contact_email=None: _feed_for_ids(["2307.01156v2"]),
        )
        _patch_email(monkeypatch)

        exit_code = notebook_metadata_backfill.run(
            SLUG, base=base, sleep=lambda _s: None,
        )

        assert exit_code == 0
        tokens = capsys.readouterr().out.split()
        assert "hydrated=1" in tokens
        assert "total=2" in tokens
        assert _store_get(base, "2307.01156") is not None


class TestPoliteness:
    def test_three_second_spacing_between_requests(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        base = _make_notebook(tmp_path, "2307.00001\n2307.00002\n2307.00003\n")
        sleeps: list[float] = []

        def _stub(url: str, contact_email: str | None = None) -> bytes:
            ids = _requested_ids(url)
            return _feed_for_ids([f"{i}v1" for i in ids])

        monkeypatch.setattr(_arxiv_api, "_fetch_url", _stub)
        _patch_email(monkeypatch)

        exit_code = notebook_metadata_backfill.run(
            SLUG, base=base, batch_size=1, sleep=sleeps.append,
        )

        assert exit_code == 0
        # 3 requests → a politeness sleep BEFORE every request except
        # the first.
        assert sleeps == [POLITENESS_SLEEP_SECONDS, POLITENESS_SLEEP_SECONDS]

    def test_email_enforced_at_run_entry_before_any_fetch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        base = _make_notebook(tmp_path, "2307.00001\n")
        calls: list[str] = []
        monkeypatch.setattr(
            _arxiv_api, "_fetch_url",
            lambda url, contact_email=None: calls.append(url) or b"",
        )

        def _no_email(_arg):
            raise NotebookError("no contact email available")

        monkeypatch.setattr(
            notebook_metadata_backfill, "resolve_contact_email", _no_email,
        )

        with pytest.raises(NotebookError, match="contact email"):
            notebook_metadata_backfill.run(SLUG, base=base, sleep=lambda _s: None)
        assert calls == []

    def test_retry_after_zero_clamps_to_default_503_backoff(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Live-observed hazard: arXiv serves 503 + ``Retry-After: 0``,
        which un-clamped would mean immediate re-hammering."""
        base = _make_notebook(tmp_path, "2307.00001\n")
        sleeps: list[float] = []
        attempts: list[int] = []

        def _stub(url: str, contact_email: str | None = None) -> bytes:
            attempts.append(1)
            if len(attempts) == 1:
                headers = email.message.Message()
                headers["Retry-After"] = "0"
                raise urllib.error.HTTPError(
                    url, 503, "Service Unavailable", headers, None,
                )
            return _feed_for_ids(["2307.00001v1"])

        monkeypatch.setattr(_arxiv_api, "_fetch_url", _stub)
        _patch_email(monkeypatch)

        exit_code = notebook_metadata_backfill.run(
            SLUG, base=base, sleep=sleeps.append,
        )

        assert exit_code == 0
        assert len(attempts) == 2
        # The 0-second Retry-After is clamped up to the default.
        assert DEFAULT_503_BACKOFF_SECONDS in sleeps
        assert 0.0 not in sleeps

    def test_429_gets_long_cooldown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        base = _make_notebook(tmp_path, "2307.00001\n")
        sleeps: list[float] = []
        attempts: list[int] = []

        def _stub(url: str, contact_email: str | None = None) -> bytes:
            attempts.append(1)
            if len(attempts) == 1:
                raise urllib.error.HTTPError(
                    url, 429, "Rate exceeded.", email.message.Message(), None,
                )
            return _feed_for_ids(["2307.00001v1"])

        monkeypatch.setattr(_arxiv_api, "_fetch_url", _stub)
        _patch_email(monkeypatch)

        exit_code = notebook_metadata_backfill.run(
            SLUG, base=base, sleep=sleeps.append,
        )

        assert exit_code == 0
        assert notebook_metadata_backfill.RATE_LIMIT_BACKOFF_SECONDS in sleeps

    def test_retry_budget_exhaustion_degrades_to_per_id_miss(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
    ) -> None:
        base = _make_notebook(tmp_path, "2307.00001\n")
        attempts: list[int] = []

        def _stub(url: str, contact_email: str | None = None) -> bytes:
            attempts.append(1)
            raise urllib.error.HTTPError(
                url, 503, "Service Unavailable", email.message.Message(), None,
            )

        monkeypatch.setattr(_arxiv_api, "_fetch_url", _stub)
        _patch_email(monkeypatch)

        exit_code = notebook_metadata_backfill.run(
            SLUG, base=base, sleep=lambda _s: None,
        )

        assert exit_code == 1
        assert len(attempts) == notebook_metadata_backfill.MAX_ATTEMPTS_PER_REQUEST
        captured = capsys.readouterr()
        assert "missing=1" in captured.out.split()
        assert "reason=http_503" in captured.err


class TestIdempotency:
    def test_rerun_is_noop_with_zero_network_egress(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
    ) -> None:
        base = _make_notebook(tmp_path, "0708.2247\nmath/0212237\n")
        calls: list[str] = []

        def _stub(url: str, contact_email: str | None = None) -> bytes:
            calls.append(url)
            return _feed_for_ids(["0708.2247v1", "math/0212237v1"])

        monkeypatch.setattr(_arxiv_api, "_fetch_url", _stub)
        _patch_email(monkeypatch)

        first = notebook_metadata_backfill.run(SLUG, base=base, sleep=lambda _s: None)
        assert first == 0
        assert len(calls) == 1
        capsys.readouterr()

        second = notebook_metadata_backfill.run(SLUG, base=base, sleep=lambda _s: None)
        assert second == 0
        assert len(calls) == 1  # NO new request on the re-run
        tokens = capsys.readouterr().out.split()
        assert "hydrated=0" in tokens
        assert "skipped=2" in tokens
        assert "missing=0" in tokens


class TestFailureModes:
    def test_poisoned_batch_falls_back_to_per_id_requests(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
    ) -> None:
        """One bad response cannot zero the batch: the driver retries
        each id individually and only the bad one is missed."""
        base = _make_notebook(tmp_path, "2307.00001\n2307.00002\n")

        def _stub(url: str, contact_email: str | None = None) -> bytes:
            ids = _requested_ids(url)
            if len(ids) > 1:
                return _ERROR_FEED  # batch poisoned
            if ids == ["2307.00001"]:
                return _feed_for_ids(["2307.00001v1"])
            return _ERROR_FEED  # this id really is bad

        monkeypatch.setattr(_arxiv_api, "_fetch_url", _stub)
        _patch_email(monkeypatch)

        exit_code = notebook_metadata_backfill.run(
            SLUG, base=base, sleep=lambda _s: None,
        )

        assert exit_code == 1
        captured = capsys.readouterr()
        tokens = captured.out.split()
        assert "hydrated=1" in tokens
        assert "missing=1" in tokens
        assert "2307.00002" in captured.err
        assert "reason=error_feed" in captured.err
        assert _store_get(base, "2307.00001") is not None

    def test_absent_entry_is_a_loud_per_id_miss(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
    ) -> None:
        base = _make_notebook(tmp_path, "2307.00001\n2401.99999\n")
        monkeypatch.setattr(
            _arxiv_api, "_fetch_url",
            lambda url, contact_email=None: _feed_for_ids(["2307.00001v1"]),
        )
        _patch_email(monkeypatch)

        exit_code = notebook_metadata_backfill.run(
            SLUG, base=base, sleep=lambda _s: None,
        )

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "missing=1" in captured.out.split()
        assert "2401.99999" in captured.err
        assert "reason=no_entry" in captured.err

    def test_empty_fields_entry_not_written_so_rerun_retries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
    ) -> None:
        base = _make_notebook(tmp_path, "2307.00001\n")
        feed = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<feed xmlns="http://www.w3.org/2005/Atom"'
            b' xmlns:arxiv="http://arxiv.org/schemas/atom">'
            b"<entry>"
            b"<id>http://arxiv.org/abs/2307.00001v1</id>"
            b"<title></title>"
            b"<published>2023-07-01T00:00:00Z</published>"
            b"<summary>abstract</summary>"
            b"</entry></feed>"
        )
        monkeypatch.setattr(
            _arxiv_api, "_fetch_url", lambda url, contact_email=None: feed,
        )
        _patch_email(monkeypatch)

        exit_code = notebook_metadata_backfill.run(
            SLUG, base=base, sleep=lambda _s: None,
        )

        assert exit_code == 1
        assert "reason=empty_fields" in capsys.readouterr().err
        assert _store_get(base, "2307.00001") is None

    def test_malformed_lines_counted_never_fetched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
    ) -> None:
        base = _make_notebook(tmp_path, "not-an-arxiv-id!\n2307.00001\n")

        def _stub(url: str, contact_email: str | None = None) -> bytes:
            assert _requested_ids(url) == ["2307.00001"]
            return _feed_for_ids(["2307.00001v1"])

        monkeypatch.setattr(_arxiv_api, "_fetch_url", _stub)
        _patch_email(monkeypatch)

        exit_code = notebook_metadata_backfill.run(
            SLUG, base=base, sleep=lambda _s: None,
        )

        assert exit_code == 1
        captured = capsys.readouterr()
        tokens = captured.out.split()
        assert "malformed=1" in tokens
        assert "hydrated=1" in tokens
        assert "not-an-arxiv-id!" in captured.err

    def test_missing_papers_txt_raises_notebook_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        base = tmp_path / "notebooks"
        (base / SLUG).mkdir(parents=True)  # notebook dir, no papers.txt
        _patch_email(monkeypatch)
        with pytest.raises(NotebookError, match="papers.txt"):
            notebook_metadata_backfill.run(SLUG, base=base, sleep=lambda _s: None)


class TestMembershipSource:
    def test_driver_never_reads_the_empty_junction_table(self) -> None:
        """Silent-zero guard: membership MUST come from papers.txt.
        The ``notebook_papers`` junction table is empty for every
        notebook — a driver keyed off it hydrates nothing yet exits 0."""
        source = inspect.getsource(notebook_metadata_backfill)
        # No import path reaches the junction table: the driver must
        # not touch NotebooksStore / notebooks.db at all.
        assert "NotebooksStore" not in source
        assert "server.notebooks_store" not in source
        assert "read_paper_ids_from_papers_txt" in source
