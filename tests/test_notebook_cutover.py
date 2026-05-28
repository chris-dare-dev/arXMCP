"""Tests for tools/notebook_cutover.py (notebook-cutover-m1).

Synthetic-fixture only — no BGE-M3, no real BM25 build. A "lancedb" dir is
modeled as a directory carrying a valid ``corpus-version.json`` marker plus a
``_sentinel.txt`` whose content lets a test verify the dir's identity survives
the rename round-trip. ``build_bm25_index`` is monkeypatched to a recorder so
the swap logic is tested in isolation from the (dense-only-unused) BM25 build.

Acceptance criteria → test:
- AC1 swap+backup       → test_cutover_swaps_and_backs_up
- AC2 rollback lossless → test_rollback_is_lossless_roundtrip
- AC3 downgrade-refuse  → test_downgrade_refused / test_force_overrides_downgrade
- AC4 missing-staging   → test_missing_staging_refused / test_staging_without_marker_refused
- AC5 all-notebooks     → test_all_notebooks_isolates_failures
- AC6 N=2 prune         → test_backup_retention_prunes_to_two
- AC7 BM25 pre-swap     → test_bm25_built_for_staging_version (+ failure variant)
- FM swap-step-2 fail   → test_swap_step2_failure_restores_active
- FM-5 slug traversal   → test_traversal_slug_rejected
- FM-6 rollback-no-bkup → test_rollback_without_backup_refused
- first-ingest          → test_first_ingest_promotes_without_backup
"""

from __future__ import annotations

import json
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


@pytest.fixture
def recorded_bm25(monkeypatch):
    """Replace build_bm25_index with a recorder; capture (path, version) and
    whether the staging dir still existed at call time (proves PRE-swap)."""
    calls: list[dict] = []

    def _fake(lancedb_path, corpus_version):
        p = Path(lancedb_path)
        calls.append({
            "path": str(p),
            "version": corpus_version,
            "staging_existed": p.name == nc.STAGING_NAME and p.is_dir(),
        })

    monkeypatch.setattr(nc, "build_bm25_index", _fake)
    return calls


# ---------------------------------------------------------------------------
# AC1 / AC6 / AC7 — happy-path cutover
# ---------------------------------------------------------------------------


def test_cutover_swaps_and_backs_up(nb_base, recorded_bm25) -> None:
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


def test_bm25_built_for_staging_version(nb_base, recorded_bm25) -> None:
    """AC7: BM25 is built for the STAGING version, reading the STAGING path,
    BEFORE the swap (the staging dir still existed at call time)."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=369)
    _write_lancedb(nb / "lancedb-staging", version=645)

    nc.perform_cutover("demo-nb", base=nb_base)

    assert len(recorded_bm25) == 1
    call = recorded_bm25[0]
    assert call["version"] == 645
    assert call["path"].endswith("lancedb-staging")
    assert call["staging_existed"] is True  # built pre-swap


def test_backup_retention_prunes_to_two(nb_base, recorded_bm25) -> None:
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


def test_first_ingest_promotes_without_backup(nb_base, recorded_bm25) -> None:
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


def test_rollback_is_lossless_roundtrip(nb_base, recorded_bm25) -> None:
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


def test_rollback_without_backup_refused(nb_base, recorded_bm25) -> None:
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


def test_downgrade_refused(nb_base, recorded_bm25) -> None:
    """AC3: staging version <= active → refuse, no mutation, no BM25 build."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=645)
    _write_lancedb(nb / "lancedb-staging", version=369)  # older!
    with pytest.raises(nc.CutoverError, match="downgrade"):
        nc.perform_cutover("demo-nb", base=nb_base)
    # Nothing moved; BM25 never built (refusal precedes the build).
    assert (nb / "lancedb" / "_sentinel.txt").read_text() == "v645"
    assert (nb / "lancedb-staging").exists()
    assert recorded_bm25 == []


def test_equal_version_refused(nb_base, recorded_bm25) -> None:
    """AC3 boundary: staging == active is also a refusal (<=)."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=369)
    _write_lancedb(nb / "lancedb-staging", version=369)
    with pytest.raises(nc.CutoverError, match="downgrade"):
        nc.perform_cutover("demo-nb", base=nb_base)


def test_force_overrides_downgrade(nb_base, recorded_bm25) -> None:
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


def test_missing_staging_refused(nb_base, recorded_bm25) -> None:
    """AC4: no staging dir → refuse, active untouched."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=369)
    with pytest.raises(nc.CutoverError, match="no lancedb-staging"):
        nc.perform_cutover("demo-nb", base=nb_base)
    assert (nb / "lancedb" / "_sentinel.txt").read_text() == "v369"


def test_staging_without_marker_refused(nb_base, recorded_bm25) -> None:
    """AC4: staging dir present but no corpus-version.json (incomplete
    re-embed) → refuse, no mutation."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=369)
    (nb / "lancedb-staging").mkdir(parents=True)  # dir but NO marker
    with pytest.raises(nc.CutoverError, match="no corpus-version.json"):
        nc.perform_cutover("demo-nb", base=nb_base)
    assert recorded_bm25 == []


# ---------------------------------------------------------------------------
# AC7 / FM — pre-swap BM25 build is the clean-refusal point
# ---------------------------------------------------------------------------


def test_bm25_failure_refuses_with_no_mutation(nb_base, monkeypatch) -> None:
    """AC7 ordering: if the BM25 build raises, the swap must NOT have happened
    (R2's pre-swap rationale — clean refusal, directories untouched)."""
    nb = nb_base / "demo-nb"
    _write_lancedb(nb / "lancedb", version=369)
    _write_lancedb(nb / "lancedb-staging", version=645)

    def _boom(lancedb_path, corpus_version):
        raise ValueError("simulated BM25 build failure")

    monkeypatch.setattr(nc, "build_bm25_index", _boom)
    with pytest.raises(ValueError, match="simulated BM25"):
        nc.perform_cutover("demo-nb", base=nb_base)
    # No directory mutation occurred.
    assert (nb / "lancedb" / "_sentinel.txt").read_text() == "v369"
    assert (nb / "lancedb-staging" / "_sentinel.txt").read_text() == "v645"
    assert [p for p in nb.iterdir() if p.name.startswith(nc.BACKUP_PREFIX)] == []


def test_swap_step2_failure_restores_active(nb_base, recorded_bm25, monkeypatch) -> None:
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


def test_traversal_slug_rejected(nb_base, recorded_bm25) -> None:
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


def test_all_notebooks_isolates_failures(nb_base, recorded_bm25, capsys) -> None:
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


def test_all_notebooks_empty_is_clean(nb_base, recorded_bm25, capsys) -> None:
    """--all-notebooks with no promotable notebooks → exit 0, clear message."""
    rc = nc.main([])
    assert rc == 0
    assert "no promotable notebooks" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# discover_promotable
# ---------------------------------------------------------------------------


def test_discover_promotable_lists_only_staged(nb_base, recorded_bm25) -> None:
    _write_lancedb(nb_base / "has-staging" / "lancedb-staging", version=2)
    _write_lancedb(nb_base / "no-staging" / "lancedb", version=2)
    assert nc.discover_promotable(nb_base) == ["has-staging"]
