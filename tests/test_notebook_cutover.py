"""Tests for tools/notebook_cutover.py (notebook-cutover-m1).

Synthetic-fixture only — no BGE-M3, no BM25 build. A "lancedb" dir is modeled as
a directory carrying a valid ``corpus-version.json`` marker plus a
``_sentinel.txt`` whose content lets a test verify the dir's identity survives
the rename round-trip. (The cutover does NOT build BM25 — see F1 rectification.)

Acceptance criteria → test:
- AC1 swap+backup       → test_cutover_swaps_and_backs_up
- AC2 rollback lossless → test_rollback_is_lossless_roundtrip
- AC3 downgrade-refuse  → test_downgrade_refused / test_force_overrides_downgrade
- AC4 missing-staging   → test_missing_staging_refused / test_staging_without_marker_refused
- AC5 all-notebooks     → test_all_notebooks_isolates_failures
- AC6 N=2 prune         → test_backup_retention_prunes_to_two
- AC7 (F1) no BM25 build→ test_cutover_builds_no_global_bm25
- FM swap-step-2 fail   → test_swap_step2_failure_restores_active
- FM-5 slug traversal   → test_traversal_slug_rejected
- FM-6 rollback-no-bkup → test_rollback_without_backup_refused
- first-ingest          → test_first_ingest_promotes_without_backup
- F2 prune non-fatal    → test_prune_failure_does_not_fail_promotion
- F3 corrupt-marker     → test_corrupt_active_marker_promotes_as_recovery
- F5 single-level back  → test_rollback_is_single_level
- F6 backup collision   → test_backup_name_collision_refused
- F8 discover skips bare→ test_discover_skips_staging_without_marker
- version-keyed caches  → test_cutover_drops_caches_keyed_by_the_promoted_version /
                          test_rollback_drops_caches_keyed_by_the_restored_version /
                          test_a_refused_cutover_keeps_the_caches /
                          test_cache_delete_failure_is_reported_after_the_swap
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import tools.notebook_cutover as nc
from tools._notebook_common import NotebookError


def _write_lancedb(d: Path, version: int, chunk_count: int = 10) -> None:
    """Create a synthetic lancedb dir: a valid corpus-version.json marker +
    an identity sentinel."""
    d.mkdir(parents=True, exist_ok=True)
    (d / "corpus-version.json").write_text(
        json.dumps({
            "version": version,
            "chunker_version": "1.1",
            "embedder_version": "bge-m3",
            "created_at": "2026-05-28T00:00:00Z",
            "paper_count": 1,
            "chunk_count": chunk_count,
        }),
        encoding="utf-8",
    )
    (d / "_sentinel.txt").write_text(f"v{version}", encoding="utf-8")


@pytest.fixture
def nb_base(tmp_path: Path, monkeypatch) -> Path:
    """A notebooks-base dir; redirect the module-level NOTEBOOKS_BASE so
    main()/discover_promotable resolve here."""
    import tools._notebook_common as _nc_common

    base = tmp_path / "notebooks"
    base.mkdir()
    # discover_promotable() reads nc.NOTEBOOKS_BASE; notebook_dir(slug,
    # base=None) — the path main() takes — reads _notebook_common.NOTEBOOKS_BASE.
    # Patch BOTH so the main()-level (all-notebooks) tests resolve to tmp.
    monkeypatch.setattr(nc, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(_nc_common, "NOTEBOOKS_BASE", base)
    return base


# ---------------------------------------------------------------------------
# AC1 / AC6 — happy-path cutover
# ---------------------------------------------------------------------------


def test_cutover_swaps_and_backs_up(nb_base) -> None:
    """AC1: lancedb holds former staging; a lancedb-prev-* backup of the
    former active exists; lancedb-staging is gone."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=369)
    _write_lancedb(nb / "lancedb-staging", version=645)

    res = nc.perform_cutover("demo-nb", base=nb_base)

    assert res["promoted_version"] == 645
    assert (nb / "lancedb" / "_sentinel.txt").read_text() == "v645"
    assert not (nb / "lancedb-staging").exists()
    backups = [p for p in nb.iterdir() if p.name.startswith(nc.BACKUP_PREFIX)]
    assert len(backups) == 1
    assert (backups[0] / "_sentinel.txt").read_text() == "v369"


def test_cutover_refuses_incomplete_reembed_sentinel(nb_base) -> None:
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=369)
    _write_lancedb(nb / "lancedb-staging", version=645)
    (nb / "lancedb-staging" / "re-embed-progress.json").write_text(
        json.dumps({"status": "in_progress", "papers_failed_count": 0}),
        encoding="utf-8",
    )
    with pytest.raises(nc.CutoverError, match="not complete"):
        nc.perform_cutover("demo-nb", base=nb_base)
    assert (nb / "lancedb" / "_sentinel.txt").read_text() == "v369"


def test_backup_retention_prunes_to_two(nb_base) -> None:
    """AC6: after repeated cutovers, at most N=2 lancedb-prev-* remain."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=1)
    # Three successive cutovers (each re-creates staging at a higher version).
    for v in (2, 3, 4):
        _write_lancedb(nb / "lancedb-staging", version=v)
        nc.perform_cutover("demo-nb", base=nb_base)
    backups = [p for p in nb.iterdir() if p.name.startswith(nc.BACKUP_PREFIX)]
    assert len(backups) == nc.BACKUP_RETENTION == 2
    # Backups hold the FORMER actives at each cutover: v1, v2, v3. The oldest
    # (v1) is pruned; the two most recent (v2, v3) are kept. The current active
    # is v4 (not a backup).
    kept_versions = sorted(
        json.loads((b / "corpus-version.json").read_text())["version"]
        for b in backups
    )
    assert kept_versions == [2, 3]
    assert json.loads(
        (nb / "lancedb" / "corpus-version.json").read_text()
    )["version"] == 4


def test_first_ingest_promotes_without_backup(nb_base) -> None:
    """First-ingest case: no active dir → promote staging, no backup."""
    nb = nb_base / "fresh-nb"
    _write_lancedb(nb / "lancedb-staging", version=5)

    res = nc.perform_cutover("fresh-nb", base=nb_base)

    assert res["first_ingest"] is True
    assert res["backup"] is None
    assert (nb / "lancedb" / "_sentinel.txt").read_text() == "v5"
    assert not (nb / "lancedb-staging").exists()
    assert [p for p in nb.iterdir() if p.name.startswith(nc.BACKUP_PREFIX)] == []


# ---------------------------------------------------------------------------
# AC2 — rollback
# ---------------------------------------------------------------------------


def test_rollback_is_lossless_roundtrip(nb_base) -> None:
    """AC2: rollback restores former active to lancedb and demotes the
    promoted content back to lancedb-staging; round-trip is lossless."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=369)
    _write_lancedb(nb / "lancedb-staging", version=645)

    nc.perform_cutover("demo-nb", base=nb_base)
    # Post-cutover: active=v645, backup=v369, no staging.
    nc.perform_rollback("demo-nb", base=nb_base)

    # Restored: active back to v369, promoted content demoted to staging.
    assert (nb / "lancedb" / "_sentinel.txt").read_text() == "v369"
    assert (nb / "lancedb-staging" / "_sentinel.txt").read_text() == "v645"


def test_derived_indexes_travel_with_their_dataset(nb_base) -> None:
    """An index built inside a dataset is promoted and rolled back with it."""
    nb = nb_base / "demo-nb"
    for name, version in (("lancedb", 369), ("lancedb-staging", 645)):
        _write_lancedb(nb / name, version=version)
        (nb / name / "derived" / "bm25" / f"v{version}").mkdir(parents=True)
        (nb / name / "derived" / "theorem_names.db").write_text(f"v{version}")
    derived = nb / "lancedb" / "derived"

    nc.perform_cutover("demo-nb", base=nb_base)
    assert (derived / "theorem_names.db").read_text() == "v645"
    assert [p.name for p in (derived / "bm25").iterdir()] == ["v645"]

    nc.perform_rollback("demo-nb", base=nb_base)
    assert (derived / "theorem_names.db").read_text() == "v369"
    assert [p.name for p in (derived / "bm25").iterdir()] == ["v369"]


def test_rollback_without_backup_refused(nb_base) -> None:
    """FM-6: rollback with no lancedb-prev-* backup refuses, no mutation."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=369)
    with pytest.raises(nc.CutoverError, match="no .*backup to roll back"):
        nc.perform_rollback("demo-nb", base=nb_base)
    # Active untouched.
    assert (nb / "lancedb" / "_sentinel.txt").read_text() == "v369"


# ---------------------------------------------------------------------------
# AC3 — downgrade guard
# ---------------------------------------------------------------------------


def test_downgrade_refused(nb_base) -> None:
    """AC3: staging version <= active → refuse, no mutation, no BM25 build."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=645)
    _write_lancedb(nb / "lancedb-staging", version=369)  # older!
    with pytest.raises(nc.CutoverError, match="downgrade"):
        nc.perform_cutover("demo-nb", base=nb_base)
    # Nothing moved; BM25 never built (refusal precedes the build).
    assert (nb / "lancedb" / "_sentinel.txt").read_text() == "v645"
    assert (nb / "lancedb-staging").exists()


def test_equal_version_refused(nb_base) -> None:
    """AC3 boundary: staging == active is also a refusal (<=)."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=369)
    _write_lancedb(nb / "lancedb-staging", version=369)
    with pytest.raises(nc.CutoverError, match="downgrade"):
        nc.perform_cutover("demo-nb", base=nb_base)


def test_force_overrides_downgrade(nb_base) -> None:
    """AC3: --force promotes even an older staging."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=645)
    _write_lancedb(nb / "lancedb-staging", version=369)
    res = nc.perform_cutover("demo-nb", base=nb_base, force=True)
    assert res["promoted_version"] == 369
    assert (nb / "lancedb" / "_sentinel.txt").read_text() == "v369"


# ---------------------------------------------------------------------------
# AC4 — missing / incomplete staging
# ---------------------------------------------------------------------------


def test_missing_staging_refused(nb_base) -> None:
    """AC4: no staging dir → refuse, active untouched."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=369)
    with pytest.raises(nc.CutoverError, match="no lancedb-staging"):
        nc.perform_cutover("demo-nb", base=nb_base)
    assert (nb / "lancedb" / "_sentinel.txt").read_text() == "v369"


def test_staging_without_marker_refused(nb_base) -> None:
    """AC4: staging dir present but no corpus-version.json (incomplete
    re-embed) → refuse, no mutation."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=369)
    (nb / "lancedb-staging").mkdir(parents=True)  # dir but NO marker
    with pytest.raises(nc.CutoverError, match="no corpus-version.json"):
        nc.perform_cutover("demo-nb", base=nb_base)


# ---------------------------------------------------------------------------
# FM — swap-step-2 failure restores the active path
# ---------------------------------------------------------------------------


def test_swap_step2_failure_restores_active(nb_base, monkeypatch) -> None:
    """FM-1: if step-2 rename fails, step-1 is restored — active is never
    left missing."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=369)
    _write_lancedb(nb / "lancedb-staging", version=645)

    real_rename = nc.os.rename
    state = {"n": 0}

    def _flaky_rename(src, dst):
        state["n"] += 1
        if state["n"] == 2:  # the staging->active promotion
            raise OSError("simulated step-2 failure")
        return real_rename(src, dst)

    monkeypatch.setattr(nc.os, "rename", _flaky_rename)
    with pytest.raises(nc.CutoverError, match="step 2"):
        nc.perform_cutover("demo-nb", base=nb_base)
    # Active restored from the backup; staging still present.
    assert (nb / "lancedb" / "_sentinel.txt").read_text() == "v369"
    assert (nb / "lancedb-staging").exists()


# ---------------------------------------------------------------------------
# FM-5 — Threat-1 slug traversal
# ---------------------------------------------------------------------------


def test_traversal_slug_rejected(nb_base) -> None:
    """FM-5: a path-traversal / malformed slug is rejected by validate_slug
    before any path use, in BOTH cutover and rollback."""
    for bad in ("../etc", "a/b", "ABC", "x"):
        with pytest.raises(NotebookError):
            nc.perform_cutover(bad, base=nb_base)
        with pytest.raises(NotebookError):
            nc.perform_rollback(bad, base=nb_base)


# ---------------------------------------------------------------------------
# AC5 — --all-notebooks failure isolation (via main())
# ---------------------------------------------------------------------------


def test_all_notebooks_isolates_failures(nb_base, capsys) -> None:
    """AC5: --all-notebooks (default) cuts over every promotable notebook;
    one bad notebook does not abort the others, and the run exits non-zero."""
    # good-nb: healthy staging (v645 > active v369) → promotes.
    good = nb_base / "good-nb"
    _write_lancedb(good / "lancedb", version=369)
    _write_lancedb(good / "lancedb-staging", version=645)
    # bad-nb: staging is a DOWNGRADE (v1 < active v369) → fails, isolated.
    bad = nb_base / "bad-nb"
    _write_lancedb(bad / "lancedb", version=369)
    _write_lancedb(bad / "lancedb-staging", version=1)

    rc = nc.main([])  # no --notebook → all-notebooks default

    assert rc == 1  # non-zero because bad-nb failed
    # good-nb still promoted despite bad-nb's failure (isolation).
    assert (good / "lancedb" / "_sentinel.txt").read_text() == "v645"
    assert (bad / "lancedb" / "_sentinel.txt").read_text() == "v369"  # untouched
    out = capsys.readouterr()
    assert "OK   good-nb" in out.out
    assert "FAIL bad-nb" in out.err


def test_all_notebooks_empty_is_clean(nb_base, capsys) -> None:
    """--all-notebooks with no promotable notebooks → exit 0, clear message."""
    rc = nc.main([])
    assert rc == 0
    assert "no promotable notebooks" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# discover_promotable
# ---------------------------------------------------------------------------


def test_discover_promotable_lists_only_staged(nb_base) -> None:
    _write_lancedb(nb_base / "has-staging" / "lancedb-staging", version=2)
    _write_lancedb(nb_base / "no-staging" / "lancedb", version=2)
    assert nc.discover_promotable(nb_base) == ["has-staging"]


def test_discover_skips_staging_without_marker(nb_base) -> None:
    """F8: a half-initialized lancedb-staging (dir present, no
    corpus-version.json) is NOT promotable — skipped, not surfaced as a
    failure on --all-notebooks."""
    _write_lancedb(nb_base / "good-nb" / "lancedb-staging", version=2)
    (nb_base / "half-nb" / "lancedb-staging").mkdir(parents=True)  # no marker
    assert nc.discover_promotable(nb_base) == ["good-nb"]


# ---------------------------------------------------------------------------
# Rectification regression guards (F2, F3, F5, F6)
# ---------------------------------------------------------------------------


def test_prune_failure_does_not_fail_promotion(nb_base, monkeypatch) -> None:
    """F2 (FM-3): a prune OSError after a COMMITTED swap is non-fatal — the
    promotion succeeds and main() exits 0, not a crash."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=1)
    # Two prior cutovers so a third triggers a prune (backups exceed N=2).
    for v in (2, 3):
        _write_lancedb(nb / "lancedb-staging", version=v)
        nc.perform_cutover("demo-nb", base=nb_base)
    _write_lancedb(nb / "lancedb-staging", version=4)

    def _boom(path):
        raise OSError("simulated disk-full during prune")

    monkeypatch.setattr(nc.shutil, "rmtree", _boom)
    # The swap commits; the prune failure is swallowed (non-fatal).
    res = nc.perform_cutover("demo-nb", base=nb_base)
    assert res["promoted_version"] == 4
    assert (nb / "lancedb" / "_sentinel.txt").read_text() == "v4"
    assert res["pruned_backups"] == []  # prune failed → none recorded


def test_corrupt_active_marker_promotes_as_recovery(nb_base) -> None:
    """F3: a corrupt/missing active corpus-version.json → active_version=-1,
    so any healthy staging (>=1) promotes without --force (recovery path)."""
    nb = nb_base / "demo-nb"
    (nb / "lancedb").mkdir(parents=True)
    (nb / "lancedb" / "_sentinel.txt").write_text("corrupt", encoding="utf-8")
    # NO corpus-version.json in active → read_corpus_version returns None → -1.
    _write_lancedb(nb / "lancedb-staging", version=1)
    res = nc.perform_cutover("demo-nb", base=nb_base)  # no --force needed
    assert res["promoted_version"] == 1
    assert res["previous_version"] == -1
    assert (nb / "lancedb" / "_sentinel.txt").read_text() == "v1"


def test_rollback_is_single_level(nb_base) -> None:
    """F5: rollback restores ONLY the most recent backup; the older
    lancedb-prev-* remains on disk, and a second rollback refuses (staging
    now exists)."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=1)
    for v in (2, 3):
        _write_lancedb(nb / "lancedb-staging", version=v)
        nc.perform_cutover("demo-nb", base=nb_base)
    # Two backups now: v1, v2. Active is v3.
    nc.perform_rollback("demo-nb", base=nb_base)
    # Restored the most-recent backup (v2); the older (v1) backup remains.
    assert (nb / "lancedb" / "_sentinel.txt").read_text() == "v2"
    assert (nb / "lancedb-staging" / "_sentinel.txt").read_text() == "v3"
    older = [
        b for b in nb.iterdir()
        if b.name.startswith(nc.BACKUP_PREFIX)
        and json.loads((b / "corpus-version.json").read_text())["version"] == 1
    ]
    assert len(older) == 1  # the v1 cold snapshot survives
    # A second rollback refuses — staging already exists.
    with pytest.raises(nc.CutoverError, match="already exists"):
        nc.perform_rollback("demo-nb", base=nb_base)


def test_backup_name_collision_refused(nb_base, monkeypatch) -> None:
    """F6: if the backup target name already exists (pinned timestamp), the
    cutover refuses rather than renaming the new active INTO it."""
    monkeypatch.setattr(nc, "_utc_ts_filename", lambda: "FIXEDTS")
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=1)
    _write_lancedb(nb / "lancedb-staging", version=2)
    nc.perform_cutover("demo-nb", base=nb_base)  # creates lancedb-prev-FIXEDTS
    # Set up a second cutover with the SAME pinned timestamp.
    _write_lancedb(nb / "lancedb-staging", version=3)
    with pytest.raises(nc.CutoverError, match="already exists"):
        nc.perform_cutover("demo-nb", base=nb_base)
    # The committed v2 active is untouched by the refused second cutover.
    assert (nb / "lancedb" / "_sentinel.txt").read_text() == "v2"


# ---------------------------------------------------------------------------
# Version-keyed caches after a swap
# ---------------------------------------------------------------------------


def _seed_caches(nb: Path, *versions: int) -> None:
    cache = nb / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    for name in ("retrieval.db", "retrieval.db-wal", "retrieval.db-shm"):
        (cache / name).write_bytes(b"tier-1")
    for version in versions:
        d = nb / "index" / "bm25" / f"v{version}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "chunk_ids.json").write_text("[]", encoding="utf-8")


def test_cutover_drops_every_version_keyed_cache(nb_base) -> None:
    """A staging re-embedded from scratch restarts its version count, so the
    promoted integer can equal one an earlier dataset was served at, and the
    new table's later writes climb into the old dataset's higher ``v<N>``
    dirs, which ``build_bm25_index`` would skip as already built. The Tier-1
    cache (keys salted by the integer) and EVERY BM25 version dir go; a
    non-version entry stays."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=1532)
    _write_lancedb(nb / "lancedb-staging", version=700)
    _seed_caches(nb, 700, 701, 703, 1532)
    (nb / "index" / "bm25" / "notes.txt").write_text("keep", encoding="utf-8")

    res = nc.perform_cutover("demo-nb", base=nb_base, force=True)

    assert res["promoted_version"] == 700
    assert not (nb / "cache" / "retrieval.db").exists()
    assert not (nb / "cache" / "retrieval.db-wal").exists()
    assert not (nb / "cache" / "retrieval.db-shm").exists()
    for version in (700, 701, 703, 1532):
        assert not (nb / "index" / "bm25" / f"v{version}").exists()
    assert (nb / "index" / "bm25" / "notes.txt").is_file()
    assert sorted(res["invalidated_caches"]) == [
        "cache/retrieval.db", "cache/retrieval.db-shm", "cache/retrieval.db-wal",
        "index/bm25/v1532", "index/bm25/v700", "index/bm25/v701",
        "index/bm25/v703",
    ]
    # One spelling on every platform (CLAUDE.md §3 win32 portability).
    assert not any("\\" in entry for entry in res["invalidated_caches"])


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation needs privilege on win32")
def test_cutover_unlinks_a_symlinked_version_dir_without_following(nb_base, tmp_path) -> None:
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=5)
    _write_lancedb(nb / "lancedb-staging", version=9)
    outside = tmp_path / "outside-bm25"
    outside.mkdir()
    (outside / "chunk_ids.json").write_text("[]", encoding="utf-8")
    (nb / "index" / "bm25").mkdir(parents=True)
    (nb / "index" / "bm25" / "v9").symlink_to(outside, target_is_directory=True)

    res = nc.perform_cutover("demo-nb", base=nb_base)

    assert not (nb / "index" / "bm25" / "v9").exists()
    assert (outside / "chunk_ids.json").is_file()
    assert "index/bm25/v9" in res["invalidated_caches"]


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation needs privilege on win32")
def test_cutover_refuses_to_clear_a_symlinked_bm25_root(nb_base, tmp_path) -> None:
    """Clearing a symlinked root would delete outside the notebook. The swap
    has committed, so the operator is told what to clear."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=5)
    _write_lancedb(nb / "lancedb-staging", version=9)
    outside = tmp_path / "outside-root"
    (outside / "v9").mkdir(parents=True)
    (nb / "index").mkdir(parents=True)
    (nb / "index" / "bm25").symlink_to(outside, target_is_directory=True)

    with pytest.raises(nc.CutoverError, match="symlink"):
        nc.perform_cutover("demo-nb", base=nb_base)

    assert (outside / "v9").is_dir()
    assert (nb / "lancedb" / "_sentinel.txt").read_text() == "v9"


def test_cutover_with_no_caches_reports_none(nb_base) -> None:
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=10)
    _write_lancedb(nb / "lancedb-staging", version=20)
    assert nc.perform_cutover("demo-nb", base=nb_base)["invalidated_caches"] == []


def test_a_refused_cutover_keeps_the_caches(nb_base) -> None:
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=1532)
    _write_lancedb(nb / "lancedb-staging", version=700)
    _seed_caches(nb, 700)

    with pytest.raises(nc.CutoverError, match="--force"):
        nc.perform_cutover("demo-nb", base=nb_base)

    assert (nb / "cache" / "retrieval.db").exists()
    assert (nb / "index" / "bm25" / "v700").is_dir()


def test_rollback_drops_caches_keyed_by_the_restored_version(nb_base) -> None:
    """While the promoted dataset was active it wrote caches under ITS
    version; after a forced cutover that can equal the restored one."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=369)
    _write_lancedb(nb / "lancedb-staging", version=369)
    nc.perform_cutover("demo-nb", base=nb_base, force=True)
    _seed_caches(nb, 369, 372)

    res = nc.perform_rollback("demo-nb", base=nb_base)

    assert not (nb / "cache" / "retrieval.db").exists()
    assert not (nb / "index" / "bm25" / "v369").exists()
    assert not (nb / "index" / "bm25" / "v372").exists()
    assert {"index/bm25/v369", "index/bm25/v372"} <= set(res["invalidated_caches"])


def test_cache_delete_failure_is_reported_after_the_swap(nb_base, monkeypatch) -> None:
    """The promotion stands (the swap committed), but the operator is told
    which path to clear before starting the server."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=5)
    _write_lancedb(nb / "lancedb-staging", version=9)

    def _fail(*_a, **_k):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(nc, "_invalidate_version_keyed_caches", _fail)
    with pytest.raises(nc.CutoverError, match="retrieval.db"):
        nc.perform_cutover("demo-nb", base=nb_base)
    assert (nb / "lancedb" / "_sentinel.txt").read_text() == "v9"


def test_main_tells_the_operator_to_start_not_restart(nb_base, capsys) -> None:
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=5)
    _write_lancedb(nb / "lancedb-staging", version=9)
    _seed_caches(nb, 9)

    assert nc.main(["--notebook", "demo-nb"]) == 0

    out = capsys.readouterr().out
    assert "deleted version-keyed caches" in out
    assert "START the arxmcp-server" in out
    assert "serving the pre-cutover data" not in out


def _makefile_text() -> str:
    return (Path(__file__).resolve().parent.parent / "Makefile").read_text(
        encoding="utf-8"
    )


def test_makefile_recipe_does_not_say_the_cutover_builds_bm25() -> None:
    text = _makefile_text()
    start = text.index("\nnotebook-cutover:\n")
    block = text[start:text.index("tools.notebook_cutover", start)]
    assert "building the staging BM25" not in block
    assert "BM25 is not built here" in block
    assert 'ARGS="--notebook=<slug> --force"' in block
