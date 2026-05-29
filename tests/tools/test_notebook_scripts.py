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


# ===========================================================================
# AUTOUSE SAFETY-NET FIXTURE — read this before adding any new test below.
# ===========================================================================
#
# The fixture `_autouse_safety_net_mock_raw_tex_fetch` below applies to
# EVERY test in this module via `autouse=True`. It does two things:
#
#   1. Sets ARXMCP_CONTACT_EMAIL=test@example.com so notebook_fetch.run()'s
#      AC7 hard-check passes without each test having to set it.
#      Tests that exercise the "env var unset" branch MUST call
#      ``monkeypatch.delenv("ARXMCP_CONTACT_EMAIL", raising=False)``.
#
#   2. NO-OPS `notebook_fetch.fetch_raw_tex_if_missing` so existing
#      ar5iv-hit tests don't accidentally hit `export.arxiv.org`.
#      Tests that exercise the REAL raw-tex fetch path MUST explicitly
#      override the patch with their own ``monkeypatch.setattr(...)``
#      (Python monkeypatch is stack-based; inner patch wins).
#
# F4 rect (notebook-preamble-recovery-m1 critique): the prior name
# `_default_notebook_fetch_env` was too generic and easy to miss. The
# new name embeds both `autouse_safety_net` AND `mock_raw_tex_fetch` so
# a `grep` for either term surfaces this fixture immediately. A future
# milestone that adds a real-network integration test in this file MUST
# either rename its test to make the bypass obvious OR override the
# patch inside the test body — silently relying on the no-op is a bug.
# ===========================================================================


@pytest.fixture(autouse=True)
def _autouse_safety_net_mock_raw_tex_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """See the SAFETY-NET docblock above. Renamed in F4 rect for
    grep-discoverability."""
    monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")
    monkeypatch.setattr(
        notebook_fetch,
        "fetch_raw_tex_if_missing",
        lambda *args, **kwargs: True,
    )


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
    """All papers locally cached → from_cache=N. Post-F4 fix: try_cache
    IS called (size heuristic removed), but returns ok_local_cache to
    signal no network round-trip happened."""
    _seed_notebook(notebooks_base, "demo", ["2303.07061", "0705.3794"])

    # Post-F4: try_cache is always called. ok_local_cache reason maps
    # to from_cache; "ok" reason maps to fetched.
    def _local_cache_hit(paper_id, **kw):
        return Ar5ivResult(
            paper_id=paper_id, hit=True, cache_path=Path("/x"),
            parsed_path=Path("/y"), reason="ok_local_cache",
        )
    monkeypatch.setattr(notebook_fetch, "try_cache", _local_cache_hit)

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


# ---------------------------------------------------------------------------
# Rectification regression tests (F1, F3, F4, F5, F6, F7 from critique-merged)
# ---------------------------------------------------------------------------


def test_purge_corpus_too_rejects_malformed_paper_ids(
    notebooks_base: Path,
    corpus_dirs: dict[str, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """F1 regression (CRITICAL): malformed paper_ids in papers.txt must
    NOT drive shutil.rmtree outside the corpus tree.

    Seeds a notebook with a path-traversal payload in papers.txt + a
    sentinel directory the payload WOULD target if exploit succeeded.
    Asserts sentinel is untouched and purge completes cleanly.
    """
    # Sentinel — what an exploit would delete via ../../sentinel
    sentinel_root = tmp_path / "sentinel-victim"
    sentinel_root.mkdir()
    sentinel_file = sentinel_root / "do-not-delete"
    sentinel_file.write_text("important")

    # papers.txt contains a path-traversal payload pointing at sentinel.
    # The path is relative to CORPUS_PARSED_DIR (corpus_dirs["parsed"]
    # which is tmp_path/corpus/parsed). Need ../../sentinel-victim to
    # escape to tmp_path/sentinel-victim.
    payload = "../../sentinel-victim"
    nb = notebooks_base / "demo"
    nb.mkdir()
    (nb / "papers.txt").write_text(
        f"# malicious\n{payload}\n2303.07061\n", encoding="utf-8"
    )
    (nb / "queries.json").write_text("{}", encoding="utf-8")

    rc = notebook_purge.run("demo", purge_corpus_too=True, force=True)
    assert rc == 0
    # Sentinel must survive untouched
    assert sentinel_file.exists()
    assert sentinel_file.read_text() == "important"
    assert sentinel_root.exists()


def test_notebook_dir_rejects_symlink(tmp_path: Path) -> None:
    """F3 regression (HIGH): if nb_base/<slug> is a symlink, refuse."""
    base = tmp_path / "nb_base"
    base.mkdir()
    real_target = tmp_path / "real-target"
    real_target.mkdir()
    symlink = base / "evil-slug"
    symlink.symlink_to(real_target)
    with pytest.raises(NotebookError, match="symlink"):
        _notebook_common.notebook_dir("evil-slug", base=base)


def test_fetch_does_not_short_circuit_corrupt_parsed_file(
    notebooks_base: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """F4 regression (MEDIUM): post-fix, try_cache is ALWAYS called.
    A pre-existing corrupt parsed file (>1024 bytes but no <math) no
    longer counts as a cache hit. Result depends on what try_cache
    actually returns for the underlying validation."""
    parsed = tmp_path / "parsed"
    parsed.mkdir()
    monkeypatch.setattr(notebook_fetch, "DEFAULT_PARSED_DIR", parsed)
    # Seed a corrupt 2 KB file (no <math)
    pid = "2303.07061"
    (parsed / pid).mkdir()
    (parsed / pid / "index.html").write_text("<html></html>" * 200)  # > 1024 bytes, no math
    _seed_notebook(notebooks_base, "demo", [pid])

    # Mock try_cache to return the no-math miss the production code
    # would surface for this corrupt file. The key assertion: try_cache
    # IS called (pre-fix it was bypassed by the size heuristic).
    called = {"n": 0}
    def _mock(paper_id, **kw):
        called["n"] += 1
        return Ar5ivResult(
            paper_id=paper_id, hit=False, cache_path=None,
            parsed_path=None, reason="no_math_in_body",
        )
    monkeypatch.setattr(notebook_fetch, "try_cache", _mock)

    notebook_fetch.run("demo", sleep_seconds=0.0)
    out = capsys.readouterr().out
    assert called["n"] == 1
    assert "missing=1" in out
    assert "from_cache=0" in out  # NOT counted as cache hit


def test_purge_warns_about_pdf_deferred_with_non_dict_manifest(
    notebooks_base: Path,
    corpus_dirs: dict[str, Path],
    capsys: pytest.CaptureFixture,
) -> None:
    """F5 regression (MEDIUM): corrupt manifest.json (non-dict top-level)
    must not abort the purge with a traceback. WARN listed without
    titles; purge proceeds cleanly."""
    nb = _seed_notebook(notebooks_base, "demo", ["2303.07061"])
    pdf_dir = nb / "pdf-deferred"
    pdf_dir.mkdir()
    (pdf_dir / "note.pdf").write_bytes(b"%PDF-1.4 fake " * 200)
    # Non-dict top-level — would crash without F5 fix
    (pdf_dir / "manifest.json").write_text("[1, 2, 3]")

    rc = notebook_purge.run("demo", force=True)
    err = capsys.readouterr().err
    assert rc == 0  # NOT a traceback
    assert "note.pdf" in err
    assert "WARN:" in err


def test_purge_aborts_cleanly_on_eof(
    notebooks_base: Path,
    corpus_dirs: dict[str, Path],
    capsys: pytest.CaptureFixture,
) -> None:
    """F6 regression (MEDIUM): empty stdin (file.readline returns "") is
    handled as EOF abort with a clear message, not as 'typed empty'."""
    nb = _seed_notebook(notebooks_base, "demo", ["2303.07061"])
    rc = notebook_purge.run("demo", stdin=io.StringIO(""))
    assert rc == 2
    err = capsys.readouterr().err
    # New message says "EOF or empty input"; old behavior printed
    # confusing "typed '', expected 'demo'"
    assert "EOF" in err
    assert "typed ''" not in err
    assert nb.exists()  # NOT purged


def test_ingest_builds_bm25_under_per_notebook_root(
    notebooks_base: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """notebook-bm25-isolation-m1 regression: build_bm25_index is called
    with index_root=<nb_dir>/index/bm25, NOT the global BM25_INDEX_ROOT.
    Two notebooks at the same version N get separate roots with no collision."""
    nb = _seed_notebook(notebooks_base, "myslug", ["2303.07061"])

    class _FakeSummary:
        papers_total = 1
        papers_succeeded = 1
        papers_failed = 0
        @property
        def ar5iv_hit_rate(self): return 1.0

    def _fake_ingest(paper_ids, **kw):
        marker = nb / "lancedb" / "corpus-version.json"
        marker.write_text(json.dumps({"version": 5}))
        return _FakeSummary()

    monkeypatch.setattr(notebook_ingest, "run_bulk_ingest", _fake_ingest)

    captured_calls: list[dict] = []

    def _capture_build(*args, **kwargs):
        captured_calls.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(notebook_ingest, "build_bm25_index", _capture_build)

    rc = notebook_ingest.run("myslug")
    assert rc == 0
    assert len(captured_calls) == 1
    # index_root must be the per-notebook path, not the global root
    call = captured_calls[0]
    index_root = call["kwargs"].get("index_root")
    assert index_root is not None, "index_root must be passed explicitly"
    assert "myslug" in str(index_root), (
        f"index_root should be under the notebook dir; got {index_root}"
    )
    assert "index/bm25" in str(index_root), (
        f"index_root should be <nb_dir>/index/bm25; got {index_root}"
    )
    # Confirm no .notebook_slug sentinel is written (FM-7: sentinel removed)
    assert not (index_root / "v5" / ".notebook_slug").exists()


def test_ingest_per_notebook_bm25_root_no_collision(
    notebooks_base: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """notebook-bm25-isolation-m1: two notebooks at version 1 get
    different index_root values — no collision by construction."""
    nb_a = _seed_notebook(notebooks_base, "alpha", ["2303.07061"])
    nb_b = _seed_notebook(notebooks_base, "beta", ["2303.07062"])

    class _FakeSummary:
        papers_total = 1
        papers_succeeded = 1
        papers_failed = 0
        @property
        def ar5iv_hit_rate(self): return 1.0

    def _fake_ingest_alpha(paper_ids, lancedb_staging_path, **kw):
        marker = nb_a / "lancedb" / "corpus-version.json"
        marker.write_text(json.dumps({"version": 1}))
        return _FakeSummary()

    def _fake_ingest_beta(paper_ids, lancedb_staging_path, **kw):
        marker = nb_b / "lancedb" / "corpus-version.json"
        marker.write_text(json.dumps({"version": 1}))
        return _FakeSummary()

    roots_seen: list[str] = []

    def _capture_root(*args, **kwargs):
        roots_seen.append(str(kwargs.get("index_root", "")))

    monkeypatch.setattr(notebook_ingest, "build_bm25_index", _capture_root)
    monkeypatch.setattr(notebook_ingest, "run_bulk_ingest", _fake_ingest_alpha)
    notebook_ingest.run("alpha")

    monkeypatch.setattr(notebook_ingest, "run_bulk_ingest", _fake_ingest_beta)
    notebook_ingest.run("beta")

    assert len(roots_seen) == 2
    assert roots_seen[0] != roots_seen[1], (
        f"Two notebooks at version 1 produced the SAME index_root: "
        f"{roots_seen[0]!r} — collision not prevented!"
    )
    assert "alpha" in roots_seen[0]
    assert "beta" in roots_seen[1]


def test_ingest_warns_about_stale_bm25_versions(
    notebooks_base: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """notebook-bm25-isolation-m1: when multiple v<N>/ dirs exist under
    the per-notebook BM25 root after build, print a WARN message."""
    nb = _seed_notebook(notebooks_base, "demo", ["2303.07061"])

    class _FakeSummary:
        papers_total = 1
        papers_succeeded = 1
        papers_failed = 0
        @property
        def ar5iv_hit_rate(self): return 1.0

    def _fake_ingest(paper_ids, **kw):
        marker = nb / "lancedb" / "corpus-version.json"
        marker.write_text(json.dumps({"version": 7}))
        return _FakeSummary()

    monkeypatch.setattr(notebook_ingest, "run_bulk_ingest", _fake_ingest)

    # Pre-seed stale version dirs under the per-notebook BM25 root so the
    # warning fires. We must capture the index_root to know where to seed.
    actual_root_holder: list = []

    def _fake_build(*args, **kwargs):
        actual_root_holder.append(kwargs.get("index_root"))
        # Mimic the indexer: create the v7 dir so glob finds it
        root = kwargs.get("index_root")
        if root is not None:
            (root / "v7").mkdir(parents=True, exist_ok=True)

    # First: a dry run just to find the notebook's index_root
    monkeypatch.setattr(notebook_ingest, "build_bm25_index", _fake_build)
    notebook_ingest.run("demo")
    nb_bm25_root = actual_root_holder[0]
    assert nb_bm25_root is not None

    # Pre-seed older version dirs to trigger the multi-dir warning
    (nb_bm25_root / "v1").mkdir(parents=True, exist_ok=True)
    (nb_bm25_root / "v2").mkdir(parents=True, exist_ok=True)

    # Second run: now 3 version dirs → triggers warning
    actual_root_holder.clear()
    monkeypatch.setattr(notebook_ingest, "build_bm25_index", _fake_build)
    rc = notebook_ingest.run("demo")
    assert rc == 0
    err = capsys.readouterr().err
    assert "WARN" in err
    assert "BM25 version directories exist" in err


# ---------------------------------------------------------------------------
# notebook-preamble-recovery-m1 — raw .tex fetch + preamble back-fill
# ---------------------------------------------------------------------------


def test_fetch_raw_tex_if_missing_invoked_after_ar5iv_hit(
    notebooks_base: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """AC1: after every ar5iv hit, fetch_raw_tex_if_missing fires."""
    _seed_notebook(notebooks_base, "demo", ["2303.07061", "0705.3794"])

    def _local_cache_hit(paper_id, **kw):
        return Ar5ivResult(
            paper_id=paper_id, hit=True, cache_path=Path("/x"),
            parsed_path=Path("/y"), reason="ok_local_cache",
        )
    monkeypatch.setattr(notebook_fetch, "try_cache", _local_cache_hit)

    invocations: list[str] = []

    def _record_call(paper_id, raw_dir, **kw):
        invocations.append(paper_id)
        return True

    monkeypatch.setattr(notebook_fetch, "fetch_raw_tex_if_missing", _record_call)

    rc = notebook_fetch.run("demo", sleep_seconds=0.0)
    out = capsys.readouterr().out
    assert invocations == ["2303.07061", "0705.3794"]
    assert "raw_tex_recovered=2" in out
    assert "raw_tex_missing=0" in out
    assert rc == 0


def test_fetch_raw_tex_if_missing_failure_does_not_abort_notebook(
    notebooks_base: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """AC4: a False return from fetch_raw_tex_if_missing (503/404/network)
    must NOT abort the notebook run; subsequent papers still process.
    """
    _seed_notebook(notebooks_base, "demo", ["2303.07061", "0705.3794", "1106.3430"])

    def _local_cache_hit(paper_id, **kw):
        return Ar5ivResult(
            paper_id=paper_id, hit=True, cache_path=Path("/x"),
            parsed_path=Path("/y"), reason="ok_local_cache",
        )
    monkeypatch.setattr(notebook_fetch, "try_cache", _local_cache_hit)

    # First paper succeeds, second fails (simulating 503), third succeeds.
    calls: list[str] = []

    def _selective_fail(paper_id, raw_dir, **kw):
        calls.append(paper_id)
        return paper_id != "0705.3794"

    monkeypatch.setattr(notebook_fetch, "fetch_raw_tex_if_missing", _selective_fail)

    rc = notebook_fetch.run("demo", sleep_seconds=0.0)
    out = capsys.readouterr().out
    # All three were attempted (AC4).
    assert calls == ["2303.07061", "0705.3794", "1106.3430"]
    assert "raw_tex_recovered=2" in out
    assert "raw_tex_missing=1" in out
    # The notebook run continues — ar5iv part still all OK.
    assert "from_cache=3" in out
    assert rc == 0


def test_fetch_raw_tex_if_missing_idempotent_when_raw_dir_populated(
    notebooks_base: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Idempotency: when raw_dir/<paper_id>/*.tex exists, helper returns
    True WITHOUT calling fetch_eprint."""
    raw_dir = tmp_path / "raw"
    (raw_dir / "2303.07061").mkdir(parents=True)
    (raw_dir / "2303.07061" / "main.tex").write_text(r"\documentclass{article}")

    fetch_eprint_calls: list[str] = []

    def _record_eprint(paper_id, raw, **kw):
        fetch_eprint_calls.append(paper_id)
        raise RuntimeError("must not be called")

    monkeypatch.setattr("tools.arxiv_fetch.fetch_eprint", _record_eprint)
    # Use the REAL helper, not the autouse no-op:
    from tools._notebook_common import fetch_raw_tex_if_missing as real_helper
    rc = real_helper("2303.07061", raw_dir)
    assert rc is True
    assert fetch_eprint_calls == []


def test_fetch_raw_tex_if_missing_404_returns_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """FM-3: HTTPError(404) on /e-print/ logged as withdrawn_404; returns False."""
    import urllib.error

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    def _withdrawn(paper_id, raw, **kw):
        raise urllib.error.HTTPError(
            url="https://export.arxiv.org/e-print/0000.00001",
            code=404, msg="Not Found", hdrs={}, fp=None,
        )

    monkeypatch.setattr("tools.arxiv_fetch.fetch_eprint", _withdrawn)

    from tools._notebook_common import fetch_raw_tex_if_missing as real_helper
    with caplog.at_level("WARNING", logger="notebook_common"):
        rc = real_helper("0000.00001", raw_dir)
    assert rc is False
    assert any("withdrawn_404" in r.message for r in caplog.records)


def test_fetch_raw_tex_if_missing_tarball_bomb_logs_error_returns_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """FM-1: RuntimeError from _safe_extract (path-traversal symlink)
    is logged at ERROR level (security event) and returns False so the
    notebook run continues."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    def _bomb(paper_id, raw, **kw):
        raise RuntimeError(
            "refusing to extract path outside dest: ../../etc/passwd"
        )

    monkeypatch.setattr("tools.arxiv_fetch.fetch_eprint", _bomb)

    from tools._notebook_common import fetch_raw_tex_if_missing as real_helper
    with caplog.at_level("ERROR", logger="notebook_common"):
        rc = real_helper("0000.00001", raw_dir)
    assert rc is False
    assert any(
        "SECURITY EVENT" in r.message and r.levelname == "ERROR"
        for r in caplog.records
    )


def test_notebook_fetch_run_requires_arxmcp_contact_email(
    notebooks_base: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC7: notebook_fetch.run() fails fast with a clear NotebookError
    when ARXMCP_CONTACT_EMAIL is unset. Enforcement at run-time, NOT
    import-time (so tests that don't exercise the raw-tex path don't
    have to set the env var)."""
    _seed_notebook(notebooks_base, "demo", ["2303.07061"])
    monkeypatch.delenv("ARXMCP_CONTACT_EMAIL", raising=False)
    with pytest.raises(NotebookError, match="ARXMCP_CONTACT_EMAIL"):
        notebook_fetch.run("demo", sleep_seconds=0.0)


# ---------------------------------------------------------------------------
# tools/recover_preambles.py — back-fill script
# ---------------------------------------------------------------------------


def test_recover_preambles_skips_paper_with_existing_preamble(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The back-fill must short-circuit on papers whose preamble.json
    already exists — no fetch_eprint call, no extract_preamble call."""
    from tools import recover_preambles

    parsed_dir = tmp_path / "parsed"
    preamble_dir = tmp_path / "preamble"
    (parsed_dir / "2303.07061").mkdir(parents=True)
    (parsed_dir / "2303.07061" / "index.html").write_text("<html></html>")
    (preamble_dir / "2303.07061").mkdir(parents=True)
    (preamble_dir / "2303.07061" / "preamble.json").write_text(
        '{"paper_id": "2303.07061"}'
    )
    monkeypatch.setattr(recover_preambles, "CORPUS_PARSED_DIR", parsed_dir)
    monkeypatch.setattr(recover_preambles, "PREAMBLE_OUTPUT_DIR", preamble_dir)

    def _must_not_fetch(*args, **kw):
        raise RuntimeError("fetch must not be called")

    monkeypatch.setattr(
        "tools.arxiv_fetch.fetch_eprint", _must_not_fetch,
    )

    summary = recover_preambles.run(sleep_seconds=0.0)
    assert summary.total_candidates == 1
    assert summary.already_has_preamble == 1
    assert summary.preamble_recovered == 0


def test_recover_preambles_notebook_scope_filter(
    notebooks_base: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--notebook=<slug> scopes the back-fill to papers in that
    notebook's papers.txt, NOT every paper under corpus/parsed/."""
    from tools import recover_preambles

    # Three papers in parsed/ but only one in the notebook's papers.txt
    parsed_dir = tmp_path / "parsed"
    for pid in ("2303.07061", "0705.3794", "1106.3430"):
        (parsed_dir / pid).mkdir(parents=True)
        (parsed_dir / pid / "index.html").write_text("<html></html>")
    preamble_dir = tmp_path / "preamble"
    preamble_dir.mkdir()
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    _seed_notebook(notebooks_base, "demo", ["2303.07061"])
    monkeypatch.setattr(recover_preambles, "CORPUS_PARSED_DIR", parsed_dir)
    monkeypatch.setattr(recover_preambles, "PREAMBLE_OUTPUT_DIR", preamble_dir)
    monkeypatch.setattr(recover_preambles, "CORPUS_RAW_DIR", raw_dir)
    monkeypatch.setattr(
        recover_preambles, "NOTEBOOKS_BASE", notebooks_base, raising=False,
    )

    seen: list[str] = []

    def _fake_fetch_eprint(paper_id, raw, **kw):
        seen.append(paper_id)
        (raw / paper_id).mkdir(parents=True, exist_ok=True)
        (raw / paper_id / "main.tex").write_text(r"\documentclass{article}")

    monkeypatch.setattr(
        "tools.arxiv_fetch.fetch_eprint", _fake_fetch_eprint,
    )
    monkeypatch.setattr(
        recover_preambles, "extract_preamble", lambda pid: None,
    )

    summary = recover_preambles.run(
        notebook_slug="demo", sleep_seconds=0.0,
    )
    # Only the notebook's paper was attempted (not all three in parsed/).
    assert summary.total_candidates == 1
    assert seen == ["2303.07061"]


def test_recover_preambles_503_backoff_retries_then_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FM-2 (back-fill side): fetch_eprint raises HTTPError(503) on the
    first call, then succeeds. The back-fill must NOT give up; it must
    sleep + retry up to MAX_503_BACKOFF_SECONDS."""
    import urllib.error

    from tools import recover_preambles

    parsed_dir = tmp_path / "parsed"
    (parsed_dir / "2303.07061").mkdir(parents=True)
    (parsed_dir / "2303.07061" / "index.html").write_text("<html></html>")
    preamble_dir = tmp_path / "preamble"
    preamble_dir.mkdir()
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    monkeypatch.setattr(recover_preambles, "CORPUS_PARSED_DIR", parsed_dir)
    monkeypatch.setattr(recover_preambles, "PREAMBLE_OUTPUT_DIR", preamble_dir)
    monkeypatch.setattr(recover_preambles, "CORPUS_RAW_DIR", raw_dir)
    # Skip the real sleep so the test doesn't take 60 s.
    monkeypatch.setattr(recover_preambles.time, "sleep", lambda s: None)

    call_count = {"n": 0}

    def _flaky_fetch(paper_id, raw, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise urllib.error.HTTPError(
                url="https://export.arxiv.org/e-print/2303.07061",
                code=503, msg="Service Unavailable",
                hdrs={"Retry-After": "1"}, fp=None,
            )
        (raw / paper_id).mkdir(parents=True, exist_ok=True)
        (raw / paper_id / "main.tex").write_text(r"\documentclass{article}")

    monkeypatch.setattr(
        "tools.arxiv_fetch.fetch_eprint", _flaky_fetch,
    )
    monkeypatch.setattr(
        recover_preambles, "extract_preamble", lambda pid: None,
    )

    summary = recover_preambles.run(sleep_seconds=0.0)
    assert call_count["n"] == 2  # retried exactly once
    assert summary.raw_tex_fetched == 1
    assert summary.preamble_recovered == 1


def test_recover_preambles_requires_arxmcp_contact_email(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC7: recover_preambles.run() also enforces ARXMCP_CONTACT_EMAIL."""
    from tools import recover_preambles

    monkeypatch.delenv("ARXMCP_CONTACT_EMAIL", raising=False)
    with pytest.raises(NotebookError, match="ARXMCP_CONTACT_EMAIL"):
        recover_preambles.run(sleep_seconds=0.0)


def test_recover_preambles_continues_past_tarball_bomb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F1 rect: a RuntimeError("refusing to extract path outside dest")
    from fetch_eprint on paper 2-of-3 must NOT abort the back-fill loop.
    Papers 1 and 3 must still process; the bombed paper goes into the
    new ``security_events`` bucket (NOT ``other_fetch_errors``).
    """
    import urllib.error  # noqa: F401  (kept for parity with sibling tests)

    from tools import recover_preambles

    parsed_dir = tmp_path / "parsed"
    for pid in ("0001.00001", "0002.00002", "0003.00003"):
        (parsed_dir / pid).mkdir(parents=True)
        (parsed_dir / pid / "index.html").write_text("<html></html>")
    preamble_dir = tmp_path / "preamble"
    preamble_dir.mkdir()
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    monkeypatch.setattr(recover_preambles, "CORPUS_PARSED_DIR", parsed_dir)
    monkeypatch.setattr(recover_preambles, "PREAMBLE_OUTPUT_DIR", preamble_dir)
    monkeypatch.setattr(recover_preambles, "CORPUS_RAW_DIR", raw_dir)
    monkeypatch.setattr(recover_preambles.time, "sleep", lambda s: None)

    seen: list[str] = []

    def _selective_bomb(paper_id, raw, **kw):
        seen.append(paper_id)
        if paper_id == "0002.00002":
            raise RuntimeError(
                "refusing to extract path outside dest: ../etc/passwd"
            )
        (raw / paper_id).mkdir(parents=True, exist_ok=True)
        (raw / paper_id / "main.tex").write_text(r"\documentclass{article}")

    monkeypatch.setattr(
        "tools.arxiv_fetch.fetch_eprint", _selective_bomb,
    )
    monkeypatch.setattr(
        recover_preambles, "extract_preamble", lambda pid: None,
    )

    summary = recover_preambles.run(sleep_seconds=0.0)
    # F1 contract: all three were attempted; back-fill did not abort.
    assert seen == ["0001.00001", "0002.00002", "0003.00003"]
    # Bombed paper landed in security_events, NOT other_fetch_errors.
    assert summary.security_events == ["0002.00002"]
    assert summary.other_fetch_errors == []
    # The other two completed.
    assert summary.preamble_recovered == 2


def test_recover_preambles_continues_past_url_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F1 rect: a urllib.error.URLError (DNS / connection-reset, NOT a
    HTTPError subclass) on one paper must NOT abort the loop. The paper
    lands in ``other_fetch_errors``."""
    import urllib.error

    from tools import recover_preambles

    parsed_dir = tmp_path / "parsed"
    for pid in ("0001.00001", "0002.00002"):
        (parsed_dir / pid).mkdir(parents=True)
        (parsed_dir / pid / "index.html").write_text("<html></html>")
    preamble_dir = tmp_path / "preamble"
    preamble_dir.mkdir()
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    monkeypatch.setattr(recover_preambles, "CORPUS_PARSED_DIR", parsed_dir)
    monkeypatch.setattr(recover_preambles, "PREAMBLE_OUTPUT_DIR", preamble_dir)
    monkeypatch.setattr(recover_preambles, "CORPUS_RAW_DIR", raw_dir)
    monkeypatch.setattr(recover_preambles.time, "sleep", lambda s: None)

    def _flaky_dns(paper_id, raw, **kw):
        if paper_id == "0001.00001":
            raise urllib.error.URLError("DNS resolution failed")
        (raw / paper_id).mkdir(parents=True, exist_ok=True)
        (raw / paper_id / "main.tex").write_text(r"\documentclass{article}")

    monkeypatch.setattr(
        "tools.arxiv_fetch.fetch_eprint", _flaky_dns,
    )
    monkeypatch.setattr(
        recover_preambles, "extract_preamble", lambda pid: None,
    )

    summary = recover_preambles.run(sleep_seconds=0.0)
    assert summary.preamble_recovered == 1
    assert len(summary.other_fetch_errors) == 1
    assert summary.other_fetch_errors[0][0] == "0001.00001"


def test_fetch_raw_tex_helper_oversize_runtime_error_not_security_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """F2 rect: a RuntimeError("response too large for ...: Content-Length")
    from the 100 MB cap must log at WARNING (oversize) and NOT
    at ERROR with "SECURITY EVENT". Operator review distinguishes
    DoS-mitigation rejects from path-traversal attempts."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    def _oversize(paper_id, raw, **kw):
        raise RuntimeError(
            "response too large for 0001.00001: Content-Length 999999999 > cap 104857600"
        )

    monkeypatch.setattr("tools.arxiv_fetch.fetch_eprint", _oversize)

    from tools._notebook_common import fetch_raw_tex_if_missing as real_helper
    with caplog.at_level("WARNING", logger="notebook_common"):
        rc = real_helper("0001.00001", raw_dir)
    assert rc is False
    # The oversize path uses WARNING + "oversized", NOT
    # ERROR + "SECURITY EVENT".
    relevant = [r for r in caplog.records if "0001.00001" in r.message]
    assert any(
        r.levelname == "WARNING" and "oversized" in r.message
        for r in relevant
    )
    assert not any(
        "SECURITY EVENT" in r.message for r in relevant
    )


def test_fetch_raw_tex_helper_idempotent_with_subdir_tex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F7 rect: idempotency gate uses rglob, so a paper with .tex only
    in subdirs (e.g. ``chapters/intro.tex``) is correctly recognized as
    already-present and the helper returns True without calling
    fetch_eprint."""
    raw_dir = tmp_path / "raw"
    paper_dir = raw_dir / "0001.00001"
    (paper_dir / "chapters").mkdir(parents=True)
    (paper_dir / "chapters" / "intro.tex").write_text(r"\documentclass{book}")
    # NOTE: no top-level main.tex; only subdir tex.

    def _must_not_fetch(*args, **kw):
        raise RuntimeError("F7 regression: fetch_eprint should not be called")

    monkeypatch.setattr("tools.arxiv_fetch.fetch_eprint", _must_not_fetch)

    from tools._notebook_common import fetch_raw_tex_if_missing as real_helper
    rc = real_helper("0001.00001", raw_dir)
    assert rc is True


def test_recover_preambles_real_extract_preamble_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F3 rect: integration test that exercises the REAL
    ingest.preamble.extract_preamble against a synthetic .tex file
    written by a mocked fetch_eprint. Anchors AC2's mechanical
    promise that "raw_tex_fetched → preamble.json written" — without
    this, a future refactor of extract_preamble could silently stop
    producing preambles while this milestone's tests all still pass.
    """
    from ingest import preamble as ingest_preamble
    from tools import recover_preambles

    parsed_dir = tmp_path / "parsed"
    (parsed_dir / "0001.00001").mkdir(parents=True)
    (parsed_dir / "0001.00001" / "index.html").write_text("<html></html>")
    preamble_dir = tmp_path / "preamble"
    preamble_dir.mkdir()
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()

    monkeypatch.setattr(recover_preambles, "CORPUS_PARSED_DIR", parsed_dir)
    monkeypatch.setattr(recover_preambles, "PREAMBLE_OUTPUT_DIR", preamble_dir)
    monkeypatch.setattr(recover_preambles, "CORPUS_RAW_DIR", raw_dir)
    # CRUCIAL: extract_preamble reads from ingest.preamble.RAW_DIR
    # and writes to ingest.preamble.PREAMBLE_DIR — patch those so the
    # real implementation runs against tmp_path.
    monkeypatch.setattr(ingest_preamble, "RAW_DIR", raw_dir)
    monkeypatch.setattr(ingest_preamble, "PREAMBLE_DIR", preamble_dir)
    monkeypatch.setattr(recover_preambles.time, "sleep", lambda s: None)

    # Mock fetch_eprint to write a real synthetic .tex containing a
    # macro that extract_preamble must recover.
    def _write_real_tex(paper_id, raw, **kw):
        (raw / paper_id).mkdir(parents=True, exist_ok=True)
        (raw / paper_id / "main.tex").write_text(
            "\\documentclass{article}\n"
            "\\newcommand{\\foo}{bar}\n"
            "\\begin{document}\n"
            "Hello world.\n"
            "\\end{document}\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        "tools.arxiv_fetch.fetch_eprint", _write_real_tex,
    )

    summary = recover_preambles.run(sleep_seconds=0.0)
    # AC2: preamble.json materialized for the candidate paper.
    assert summary.preamble_recovered == 1
    pj = preamble_dir / "0001.00001" / "preamble.json"
    assert pj.is_file(), (
        "AC2 regression: extract_preamble did not write preamble.json "
        "via the back-fill driver's integration path."
    )
    import json as _json  # noqa: PLC0415
    data = _json.loads(pj.read_text())
    # The macro must appear in the recovered preamble_text.
    assert "\\newcommand" in data.get("preamble_text", "")
    assert "\\foo" in data.get("preamble_text", "")


def test_recover_preambles_404_classified_as_withdrawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FM-3: HTTPError(404) on /e-print/ is recorded as withdrawn_404,
    NOT as a fetch error. The paper is skipped; extract_preamble is
    NOT called."""
    import urllib.error

    from tools import recover_preambles

    parsed_dir = tmp_path / "parsed"
    (parsed_dir / "2303.07061").mkdir(parents=True)
    (parsed_dir / "2303.07061" / "index.html").write_text("<html></html>")
    preamble_dir = tmp_path / "preamble"
    preamble_dir.mkdir()
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    monkeypatch.setattr(recover_preambles, "CORPUS_PARSED_DIR", parsed_dir)
    monkeypatch.setattr(recover_preambles, "PREAMBLE_OUTPUT_DIR", preamble_dir)
    monkeypatch.setattr(recover_preambles, "CORPUS_RAW_DIR", raw_dir)
    monkeypatch.setattr(recover_preambles.time, "sleep", lambda s: None)

    def _withdrawn(paper_id, raw, **kw):
        raise urllib.error.HTTPError(
            url="https://export.arxiv.org/e-print/2303.07061",
            code=404, msg="Not Found", hdrs={}, fp=None,
        )

    monkeypatch.setattr(
        "tools.arxiv_fetch.fetch_eprint", _withdrawn,
    )
    extract_calls: list[str] = []

    def _record_extract(pid):
        extract_calls.append(pid)
    monkeypatch.setattr(
        recover_preambles, "extract_preamble", _record_extract,
    )

    summary = recover_preambles.run(sleep_seconds=0.0)
    assert summary.withdrawn_404 == ["2303.07061"]
    assert summary.preamble_recovered == 0
    # extract_preamble must NOT be called on a withdrawn paper
    assert extract_calls == []
