"""One writer per LanceDB dataset: a second writer is refused at once.

The holder in these tests is a separate Python process, the case the lock
exists for (an operator's terminal run beside a console-started one).
"""

from __future__ import annotations

import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import lancedb
import pytest

import arxmcp.corpus.store as store_mod
from arxmcp.corpus.write_lock import (
    WRITE_LOCKED_EXIT_CODE,
    DatasetWriteLockedError,
    dataset_write_lock,
)
from arxmcp.ingest import bulk_ingest
from arxmcp.ops import prune_versions as prune_mod
from tests._corpus_helpers import seed_corpus_multi_paper

REPO_ROOT = Path(__file__).resolve().parents[1]

_HOLDER = """
import sys
from arxmcp.corpus.write_lock import dataset_write_lock
with dataset_write_lock(sys.argv[1]):
    print("held", flush=True)
    sys.stdin.read()
"""


@pytest.fixture
def hold_in_other_process() -> Iterator[Callable[[Path], subprocess.Popen]]:
    procs: list[subprocess.Popen] = []

    def hold(path: Path) -> subprocess.Popen:
        proc = subprocess.Popen(
            [sys.executable, "-c", _HOLDER, str(path)],
            cwd=REPO_ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True,
        )
        procs.append(proc)
        if proc.stdout.readline().strip() != "held":
            raise RuntimeError("lock holder did not start")
        return proc

    yield hold
    for proc in procs:
        proc.stdin.close()
        proc.wait(timeout=30)


def _writers(tmp_path: Path) -> dict[str, Callable[[Path], object]]:
    from arxmcp.ingest.derived_indexes import build_derived_indexes
    from arxmcp.ingest.embed_equations import embed_pending_equations
    from arxmcp.ingest.extract_equations import extract_equations_for_paper
    from arxmcp.ingest.index_definitions import index_definitions_for_corpus
    from arxmcp.ingest.index_equations import index_equation_trees
    from arxmcp.ingest.index_theorem_names import build_theorem_names_index
    from arxmcp.ingest.oai_delta import run_delta
    from arxmcp.ingest.re_embed import run_re_embed

    def no_fetch(*_args, **_kwargs):
        raise AssertionError("a refused run must not harvest")

    return {
        "write_chunks": lambda ds: store_mod.write_chunks([], None, lancedb_path=ds),
        "delete_paper": lambda ds: store_mod.delete_paper(ds, "2307.00001"),
        "bulk_ingest": lambda ds: bulk_ingest.run_bulk_ingest(
            ["2307.00001"], lancedb_staging_path=ds,
            failures_path=tmp_path / "failures.jsonl",
            log_path=tmp_path / "ingestion.log", ops_dir=tmp_path / "ops",
        ),
        "oai_delta": lambda ds: run_delta(
            lancedb_staging_path=ds, state_path=tmp_path / "oai-state.json",
            log_path=tmp_path / "delta.log", ops_dir=tmp_path / "ops",
            timeout_flag_path=tmp_path / "timeout.flag", fetch_page=no_fetch,
        ),
        "re_embed": lambda ds: run_re_embed(
            active_lancedb_path=tmp_path / "active", staging_lancedb_path=ds,
            state_path=tmp_path / "re-embed-state.json",
            failures_path=tmp_path / "re-embed-failures.jsonl",
        ),
        "prune_versions": lambda ds: prune_mod.prune_versions(ds),
        "index_equation_trees": lambda ds: index_equation_trees(ds),
        "index_definitions": lambda ds: index_definitions_for_corpus(ds),
        "extract_equations": lambda ds: extract_equations_for_paper("2307.00001", ds),
        "embed_equations": lambda ds: embed_pending_equations(ds),
        "theorem_names": lambda ds: build_theorem_names_index(ds),
        "derived_indexes": lambda ds: build_derived_indexes(ds),
    }


_WRITER_NAMES = list(_writers(Path("unused")))


@pytest.mark.parametrize("writer", _WRITER_NAMES)
def test_every_write_entry_point_is_refused_beside_another_writer(
    tmp_path, hold_in_other_process, writer
):
    dataset = tmp_path / "lancedb"
    holder = hold_in_other_process(dataset)

    with pytest.raises(DatasetWriteLockedError) as excinfo:
        _writers(tmp_path)[writer](dataset)

    message = str(excinfo.value)
    assert "another ingest is writing the dataset" in message
    assert f"pid {holder.pid}" in message
    # Refused before any work: no table, no harvest state, no sentinel.
    assert not (dataset / "chunks.lance").exists()
    assert not (tmp_path / "oai-state.json").exists()
    assert not (tmp_path / "ops").exists()


def _bulk_cli(tmp_path: Path, dataset: Path) -> int:
    ids = tmp_path / "ids.txt"
    ids.write_text("2307.00001\n", encoding="utf-8")
    return bulk_ingest._cli(
        ["--paper-ids-file", str(ids), "--lancedb-staging-path", str(dataset)]
    )


def _prune_cli(_tmp_path: Path, dataset: Path) -> int:
    return prune_mod._cli(["--lancedb-path", str(dataset)])


@pytest.mark.parametrize("cli", [_bulk_cli, _prune_cli], ids=["bulk", "prune"])
def test_cli_exits_with_its_own_code_when_the_dataset_is_held(
    tmp_path, hold_in_other_process, capsys, cli
):
    dataset = tmp_path / "lancedb"
    hold_in_other_process(dataset)

    assert cli(tmp_path, dataset) == WRITE_LOCKED_EXIT_CODE

    err = capsys.readouterr().err
    assert err.startswith("error: another ingest is writing the dataset")
    assert "Traceback" not in err


def test_lock_is_free_once_the_holder_exits(tmp_path, hold_in_other_process):
    dataset = tmp_path / "lancedb"
    holder = hold_in_other_process(dataset)
    holder.stdin.close()
    holder.wait(timeout=30)

    seed_corpus_multi_paper(dataset, n_papers=1, chunks_per_paper=2)

    assert lancedb.connect(str(dataset)).open_table("chunks").count_rows() == 2


def test_lock_is_released_when_the_writer_raises(tmp_path):
    dataset = tmp_path / "lancedb"
    with pytest.raises(ValueError), dataset_write_lock(dataset):
        raise ValueError("writer failed")

    probe = subprocess.run(
        [sys.executable, "-c", _HOLDER, str(dataset)],
        cwd=REPO_ROOT, input="", capture_output=True, text=True, timeout=60,
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == "held"


def test_dry_run_takes_no_lock(tmp_path, hold_in_other_process, capsys):
    dataset = tmp_path / "lancedb"
    hold_in_other_process(dataset)

    summary = bulk_ingest.run_bulk_ingest(
        ["2307.00001"], lancedb_staging_path=dataset, dry_run=True,
        ar5iv_cache_dir=tmp_path / "ar5iv", parsed_dir=tmp_path / "parsed",
    )

    assert summary.papers_skipped == 1


def test_another_dataset_is_not_blocked(tmp_path, hold_in_other_process):
    hold_in_other_process(tmp_path / "a" / "lancedb")

    seed_corpus_multi_paper(tmp_path / "b" / "lancedb", n_papers=1, chunks_per_paper=2)

    table = lancedb.connect(str(tmp_path / "b" / "lancedb")).open_table("chunks")
    assert table.count_rows() == 2


def test_renaming_the_dataset_does_not_free_its_path(tmp_path, hold_in_other_process):
    # A cutover renames dataset directories while nothing should be
    # writing; a writer that is still running keeps the path locked.
    dataset = tmp_path / "lancedb"
    dataset.mkdir()
    hold_in_other_process(dataset)
    dataset.rename(tmp_path / "lancedb-previous")
    dataset.mkdir()

    with pytest.raises(DatasetWriteLockedError):
        seed_corpus_multi_paper(dataset, n_papers=1, chunks_per_paper=2)


def test_holder_thread_reenters_and_other_threads_are_refused(tmp_path):
    dataset = tmp_path / "lancedb"
    refused: list[BaseException] = []

    def other_thread() -> None:
        try:
            with dataset_write_lock(dataset):
                pass
        except DatasetWriteLockedError as exc:
            refused.append(exc)

    with dataset_write_lock(dataset):
        # The driver holds the lock; the writes it makes take it again.
        seed_corpus_multi_paper(dataset, n_papers=2, chunks_per_paper=2)
        thread = threading.Thread(target=other_thread)
        thread.start()
        thread.join(timeout=30)

    assert len(refused) == 1
    assert lancedb.connect(str(dataset)).open_table("chunks").count_rows() == 4


def test_wap_gate_names_a_writer_that_bypassed_the_lock(tmp_path, monkeypatch):
    dataset = tmp_path / "lancedb"
    seed_corpus_multi_paper(dataset, n_papers=1, chunks_per_paper=3)
    real_marker = store_mod.write_corpus_version_marker

    def marker_then_foreign_commit(target_path, **kwargs):
        real_marker(target_path, **kwargs)
        # Another process, not taking the lock, commits in between and
        # stamps its own marker, as every writer does.
        foreign = lancedb.connect(str(target_path)).open_table("chunks")
        foreign.delete("paper_id = '2307.00001'")
        real_marker(
            target_path, **{**kwargs, "version": foreign.version,
                            "chunk_count": foreign.count_rows(), "paper_count": 0},
        )

    monkeypatch.setattr(
        store_mod, "write_corpus_version_marker", marker_then_foreign_commit
    )

    with pytest.raises(store_mod.WapGateError) as excinfo:
        seed_corpus_multi_paper(dataset, n_papers=1, chunks_per_paper=3)

    message = str(excinfo.value)
    assert "another writer committed to this dataset" in message
    assert "write lock" in message
    assert "S6" not in message
    assert "arithmetic" not in message
