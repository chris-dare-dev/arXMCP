"""Tests for the notebook CLI scripts (proof-verify-handler-wiring-m6).

Coverage matrix (mapped to the synthesis failure modes):

- test_init_*                         — AC #1, FM-3 (idempotency at dir level)
- test_validate_slug_rejects_*        — FM-2 (path-traversal regex defense)
- test_fetch_*                        — AC #2, FM-4 (rate-limit category), FM-5 (malformed)
- test_ingest_*                       — AC #3, FM-6 (missing dirs)
- test_purge_*                        — AC #4, FM-1 (cross-notebook), FM-8 (pdf-deferred)
- test_notebook_dir_containment       — FM-2 belt-and-braces

All tests use ``tmp_path`` — none touch live ``var/arxmcp/notebooks/``.
HTTP is mocked at the ``try_cache`` boundary; ``run_bulk_ingest`` is
monkeypatched (the real one needs the embedder + LanceDB and is too
heavy for a unit test).
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from ingest.ar5iv_fetch import Ar5ivResult
from tools import _notebook_common, notebook_fetch, notebook_ingest, notebook_init, notebook_purge
from tools._notebook_common import NotebookError, validate_slug

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def notebooks_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect every script's NOTEBOOKS_BASE to a tmp dir."""
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebook_init, "NOTEBOOKS_BASE", base, raising=False)
    monkeypatch.setattr(notebook_fetch, "NOTEBOOKS_BASE", base, raising=False)
    monkeypatch.setattr(notebook_ingest, "NOTEBOOKS_BASE", base, raising=False)
    monkeypatch.setattr(notebook_purge, "NOTEBOOKS_BASE", base, raising=False)
    return base


@pytest.fixture
def corpus_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Redirect CORPUS_{PARSED,CHUNKS,EMBEDDINGS}_DIR to tmp subdirs."""
    parsed = tmp_path / "corpus" / "parsed"
    chunks = tmp_path / "corpus" / "chunks"
    emb = tmp_path / "corpus" / "embeddings"
    for d in (parsed, chunks, emb):
        d.mkdir(parents=True)
    monkeypatch.setattr(_notebook_common, "CORPUS_PARSED_DIR", parsed)
    monkeypatch.setattr(_notebook_common, "CORPUS_CHUNKS_DIR", chunks)
    monkeypatch.setattr(_notebook_common, "CORPUS_EMBEDDINGS_DIR", emb)
    monkeypatch.setattr(notebook_purge, "CORPUS_PARSED_DIR", parsed)
    monkeypatch.setattr(notebook_purge, "CORPUS_CHUNKS_DIR", chunks)
    monkeypatch.setattr(notebook_purge, "CORPUS_EMBEDDINGS_DIR", emb)
    return {"parsed": parsed, "chunks": chunks, "embeddings": emb}


def _seed_notebook(
    notebooks_base: Path,
    slug: str,
    paper_ids: list[str],
    *,
    with_queries: bool = True,
    with_lancedb: bool = False,
) -> Path:
    """Build a synthetic notebook directory."""
    nb = notebooks_base / slug
    nb.mkdir()
    pt = nb / "papers.txt"
    pt.write_text(
        "# test notebook\n" + "\n".join(paper_ids) + "\n",
        encoding="utf-8",
    )
    if with_queries:
        (nb / "queries.json").write_text(
            json.dumps({"schema_version": "1.0", "notebook_slug": slug, "queries": []}),
            encoding="utf-8",
        )
    if with_lancedb:
        (nb / "lancedb").mkdir()
    return nb


# ---------------------------------------------------------------------------
# Slug validation / path containment (FM-2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "../corpus",       # path traversal
        "/etc/passwd",     # absolute path
        "Bridgeland",      # uppercase
        "aa",              # too short
        "a" * 35,          # too long
        "1numeric-start",  # starts with digit
        "-hyphen-start",   # starts with hyphen
        "trailing/slash",  # slash
        "shell;injection", # shell meta
        "spaces here",     # whitespace
        "",                # empty
    ],
)
def test_validate_slug_rejects_bad(bad: str) -> None:
    with pytest.raises(NotebookError):
        validate_slug(bad)


@pytest.mark.parametrize(
    "good",
    ["bridgeland-stability", "shimura-varieties", "abc", "a1b2c3", "a" * 31],
)
def test_validate_slug_accepts_good(good: str) -> None:
    validate_slug(good)  # no raise


def test_validate_slug_rejects_non_string() -> None:
    with pytest.raises(NotebookError):
        validate_slug(123)  # type: ignore[arg-type]


def test_notebook_dir_containment(tmp_path: Path) -> None:
    """The notebook_dir() containment check resolves symlinks safely."""
    base = tmp_path / "nb_base"
    base.mkdir()
    target = _notebook_common.notebook_dir("valid-slug", base=base)
    assert str(target).startswith(str(base.resolve()))


# ---------------------------------------------------------------------------
# notebook_init.py (AC #1, FM-3)
# ---------------------------------------------------------------------------


def test_init_happy_path(notebooks_base: Path) -> None:
    rc = notebook_init.run("my-notebook")
    assert rc == 0
    nb = notebooks_base / "my-notebook"
    assert (nb / "papers.txt").is_file()
    assert (nb / "queries.json").is_file()
    # queries.json is valid JSON with the expected schema
    data = json.loads((nb / "queries.json").read_text())
    assert data["schema_version"] == "1.0"
    assert data["notebook_slug"] == "my-notebook"


def test_init_idempotent_directory_level(
    notebooks_base: Path, capsys: pytest.CaptureFixture
) -> None:
    """FM-3: re-running on existing dir is no-op EVEN if files were
    manually deleted. Partial-state recovery requires manual nuke."""
    notebook_init.run("my-notebook")
    # Delete queries.json to create partial state
    (notebooks_base / "my-notebook" / "queries.json").unlink()
    rc = notebook_init.run("my-notebook")
    assert rc == 0
    out = capsys.readouterr().out
    assert "skipping" in out
    # queries.json STAYS missing — partial state not recovered
    assert not (notebooks_base / "my-notebook" / "queries.json").exists()


def test_init_rejects_bad_slug(notebooks_base: Path) -> None:
    with pytest.raises(NotebookError):
        notebook_init.run("../escape")


def test_init_main_returns_1_on_bad_slug(
    notebooks_base: Path, capsys: pytest.CaptureFixture
) -> None:
    rc = notebook_init.main(["../escape"])
    assert rc == 1
    assert "error:" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# notebook_fetch.py (AC #2, FM-4 rate-limit, FM-5 malformed)
# ---------------------------------------------------------------------------


def test_fetch_happy_path(
    notebooks_base: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """All papers cached locally → fetched=0, from_cache=N, no network."""
    parsed = tmp_path / "parsed"
    parsed.mkdir()
    monkeypatch.setattr(notebook_fetch, "DEFAULT_PARSED_DIR", parsed)
    # Seed local cache for both papers
    for pid in ("2303.07061", "0705.3794"):
        d = parsed / pid
        d.mkdir()
        # Body must be > 1024 bytes per the cache-hit test
        (d / "index.html").write_text("<html><math>...</math></html>" * 100)
    _seed_notebook(notebooks_base, "demo", ["2303.07061", "0705.3794"])

    # try_cache should NEVER be called (cache hit short-circuits it)
    def _fail(*args, **kwargs):
        pytest.fail("try_cache should not be called when cache hits")
    monkeypatch.setattr(notebook_fetch, "try_cache", _fail)

    rc = notebook_fetch.run("demo", sleep_seconds=0.0)
    out = capsys.readouterr().out
    assert "fetched=0" in out
    assert "from_cache=2" in out
    assert "missing=0" in out
    assert "rate_limited=0" in out
    assert "malformed=0" in out
    assert rc == 0


def test_fetch_distinguishes_rate_limit_from_miss(
    notebooks_base: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """FM-4: 429/503/timeout become rate_limited= NOT missing=."""
    parsed = tmp_path / "parsed"
    parsed.mkdir()
    monkeypatch.setattr(notebook_fetch, "DEFAULT_PARSED_DIR", parsed)
    _seed_notebook(notebooks_base, "demo", ["2303.07061", "0705.3794", "1106.3430"])

    # Mock try_cache: first returns 429, second returns 404, third returns hit
    def _mock(paper_id, *, cache_dir, parsed_dir):
        if paper_id == "2303.07061":
            return Ar5ivResult(
                paper_id=paper_id, hit=False, cache_path=None,
                parsed_path=None, reason="http_429",
            )
        if paper_id == "0705.3794":
            return Ar5ivResult(
                paper_id=paper_id, hit=False, cache_path=None,
                parsed_path=None, reason="http_404",
            )
        return Ar5ivResult(
            paper_id=paper_id, hit=True, cache_path=Path("/x"),
            parsed_path=Path("/y"), reason="ok",
        )
    monkeypatch.setattr(notebook_fetch, "try_cache", _mock)

    rc = notebook_fetch.run("demo", sleep_seconds=0.0)
    captured = capsys.readouterr()
    assert "fetched=1" in captured.out
    assert "rate_limited=1" in captured.out
    assert "missing=1" in captured.out
    # rate-limited section in stderr explicitly names 2303.07061
    assert "2303.07061" in captured.err
    assert "DO NOT drop" in captured.err
    assert rc == 1  # because of the missing/404


def test_fetch_rejects_malformed_papers_txt_lines(
    notebooks_base: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """FM-5: malformed lines surfaced as malformed=J, NOT missing=K."""
    parsed = tmp_path / "parsed"
    parsed.mkdir()
    monkeypatch.setattr(notebook_fetch, "DEFAULT_PARSED_DIR", parsed)
    _seed_notebook(
        notebooks_base,
        "demo",
        ["https://arxiv.org/abs/2303.07061", "not-an-id", "0705.3794"],
    )
    # try_cache for the one valid ID
    monkeypatch.setattr(
        notebook_fetch,
        "try_cache",
        lambda paper_id, **kw: Ar5ivResult(
            paper_id=paper_id, hit=True, cache_path=Path("/x"),
            parsed_path=Path("/y"), reason="ok"
        ),
    )
    rc = notebook_fetch.run("demo", sleep_seconds=0.0)
    captured = capsys.readouterr()
    assert "malformed=2" in captured.out
    assert "fetched=1" in captured.out
    assert "missing=0" in captured.out
    assert rc == 1  # malformed makes exit non-zero


# ---------------------------------------------------------------------------
# notebook_ingest.py (AC #3, FM-6)
# ---------------------------------------------------------------------------


def test_ingest_creates_missing_dirs(
    notebooks_base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FM-6: notebook_ingest.py mkdirs the lancedb + ops dirs."""
    nb = _seed_notebook(notebooks_base, "demo", ["2303.07061"], with_lancedb=False)
    assert not (nb / "lancedb").exists()
    assert not (nb / "ops").exists()

    # Mock run_bulk_ingest to do nothing (returns a fake summary)
    class _FakeSummary:
        papers_total = 1
        papers_succeeded = 1
        papers_failed = 0
        @property
        def ar5iv_hit_rate(self): return 1.0
    def _fake_ingest(paper_ids, **kw):
        # Verify lancedb_staging_path was set to per-notebook path
        assert kw["lancedb_staging_path"] == nb / "lancedb"
        # Write a synthetic corpus-version.json so _read_corpus_version succeeds
        marker = nb / "lancedb" / "corpus-version.json"
        marker.write_text(json.dumps({"version": 5}))
        return _FakeSummary()
    monkeypatch.setattr(notebook_ingest, "run_bulk_ingest", _fake_ingest)
    monkeypatch.setattr(notebook_ingest, "build_bm25_index", lambda *a, **kw: None)

    rc = notebook_ingest.run("demo")
    assert rc == 0
    assert (nb / "lancedb").is_dir()
    assert (nb / "ops").is_dir()


def test_ingest_fails_when_papers_txt_empty(notebooks_base: Path) -> None:
    nb = notebooks_base / "demo"
    nb.mkdir()
    (nb / "papers.txt").write_text("# only comments\n", encoding="utf-8")
    with pytest.raises(NotebookError):
        notebook_ingest.run("demo")


def test_ingest_fails_when_notebook_dir_missing(notebooks_base: Path) -> None:
    with pytest.raises(NotebookError):
        notebook_ingest.run("does-not-exist")


# ---------------------------------------------------------------------------
# notebook_purge.py (AC #4, FM-1 cross-notebook, FM-8 pdf-deferred)
# ---------------------------------------------------------------------------


def test_purge_typed_slug_confirmation_correct(
    notebooks_base: Path, corpus_dirs: dict[str, Path]
) -> None:
    nb = _seed_notebook(notebooks_base, "demo", ["2303.07061"])
    assert nb.exists()
    rc = notebook_purge.run("demo", stdin=io.StringIO("demo\n"))
    assert rc == 0
    assert not nb.exists()


def test_purge_typed_slug_confirmation_wrong(
    notebooks_base: Path, corpus_dirs: dict[str, Path], capsys: pytest.CaptureFixture
) -> None:
    """FM-2/security: wrong typed slug → script aborts, dir intact."""
    nb = _seed_notebook(notebooks_base, "demo", ["2303.07061"])
    rc = notebook_purge.run("demo", stdin=io.StringIO("WRONG\n"))
    assert rc == 2
    assert nb.exists()
    assert "aborted" in capsys.readouterr().err


def test_purge_force_skips_confirmation(
    notebooks_base: Path, corpus_dirs: dict[str, Path]
) -> None:
    nb = _seed_notebook(notebooks_base, "demo", ["2303.07061"])
    rc = notebook_purge.run("demo", force=True)
    assert rc == 0
    assert not nb.exists()


def test_purge_corpus_too_set_difference(
    notebooks_base: Path, corpus_dirs: dict[str, Path]
) -> None:
    """FM-1: paper_id shared with sibling notebook is NOT deleted from corpus."""
    # demo has [shared, unique]; sibling has [shared, sibling-only]
    _seed_notebook(notebooks_base, "demo", ["2303.07061", "0705.3794"])
    _seed_notebook(notebooks_base, "sibling", ["2303.07061", "1106.3430"])
    # Seed corpus assets for all 3 papers
    for pid in ("2303.07061", "0705.3794", "1106.3430"):
        (corpus_dirs["parsed"] / pid).mkdir()
        (corpus_dirs["parsed"] / pid / "index.html").write_text("...")

    rc = notebook_purge.run("demo", purge_corpus_too=True, force=True)
    assert rc == 0
    # Notebook dir gone
    assert not (notebooks_base / "demo").exists()
    # Corpus assets: 0705.3794 was unique → deleted. 2303.07061 was shared → preserved.
    assert not (corpus_dirs["parsed"] / "0705.3794").exists()
    assert (corpus_dirs["parsed"] / "2303.07061").exists()
    # Sibling untouched
    assert (notebooks_base / "sibling").exists()
    assert (corpus_dirs["parsed"] / "1106.3430").exists()


def test_purge_warns_about_pdf_deferred(
    notebooks_base: Path,
    corpus_dirs: dict[str, Path],
    capsys: pytest.CaptureFixture,
) -> None:
    """FM-8: pdf-deferred WARN emitted to stderr, even with --force."""
    nb = _seed_notebook(notebooks_base, "demo", ["2303.07061"])
    pdf_dir = nb / "pdf-deferred"
    pdf_dir.mkdir()
    pdf = pdf_dir / "my-notes.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake-content " * 1000)
    (pdf_dir / "manifest.json").write_text(
        json.dumps({"manual_titles": {"my-notes.pdf": "My Notes"}})
    )

    rc = notebook_purge.run("demo", force=True)
    err = capsys.readouterr().err
    assert rc == 0
    assert "WARN:" in err
    assert "my-notes.pdf" in err
    assert "My Notes" in err


def test_purge_rejects_missing_notebook(notebooks_base: Path) -> None:
    with pytest.raises(NotebookError):
        notebook_purge.run("does-not-exist", force=True)


def test_purge_rejects_bad_slug(notebooks_base: Path) -> None:
    with pytest.raises(NotebookError):
        notebook_purge.run("../corpus", force=True)
