"""Tests for the WS-E exploration pipeline v0 (stage2/arx-e1).

Coverage matrix (mapped to acceptance-criteria.md §WS-E):

- TestWindowing                 — 3-12-month window rules (scope: "scans
                                  3-12-month windows")
- TestAtomChannel               — fixture Atom parse + AC-E.2 recency filter
- TestDedup                     — AC-E.2 dedup (versioned + unversioned ids)
- TestSources                   — snapshot validation + AC-E.4 provenance
                                  (explicit-id and keyword-overlap matches)
- TestTextbooks                 — curated bridging-textbook proposals
- TestGraphChannel              — cite_neighbors degradation
                                  (absent/unavailable/present/skipped)
- TestManifestSchema            — v0.2 contract validation (schema catches
                                  unsourced papers, unnamed sources)
- TestConformance               — the WS-E rules beyond JSON Schema
- TestGoldenPath                — AC-E.1: full offline run on fixture Atom
                                  data; envelope conformance via the C1
                                  helpers; zero-mutation audit
- TestPipelineReadme            — AC-E.5: extraction triggers recorded
- test_tool_schema_pin_lockstep — vendored BP1 pin stays in lockstep
- TestLiveSmoke                 — ONE live Atom smoke + the AC-E.3 backtest,
                                  both opt-in via env flags (never run in
                                  the default suite; the mission's "do not
                                  depend on live arXiv in tests")

All offline tests use ``tmp_path`` + ``tests/fixtures/exploration/``;
nothing touches live ``var/arxmcp/`` or the network.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import pytest

from tests._bridge_helpers import (
    load_json,
    select_schema,
    validator_for,
)
from tools.exploration import atom_channel, graph_channel, manifest, sources, textbooks
from tools.exploration.propose import load_dedup_ids
from tools.exploration.propose import main as propose_main
from tools.exploration.windowing import (
    Window,
    paper_id_month,
    parse_window,
    window_from_months,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "exploration"
ATOM_FIXTURE = FIXTURES / "atom-window.xml"
SOURCES_DIR = FIXTURES / "sources"
DEDUP_FILE = FIXTURES / "dedup-papers.txt"
PIPELINE_README = REPO_ROOT / ".claude" / "exploration" / "README.md"

MANIFEST_SCHEMA = "proposed-notebook-manifest.v0.schema.json"


def _window_2026h1() -> Window:
    return parse_window("2026-01-01", "2026-07-01")


def _golden_args(tmp_path: Path, out_name: str = "manifest.json") -> list[str]:
    return [
        "--topic-title", "Bridgeland stability follow-ups",
        "--topic-description", "stability conditions and moduli spaces",
        "--category", "math.AG",
        "--window-from", "2026-01-01",
        "--window-to", "2026-07-01",
        "--atom-fixture", str(ATOM_FIXTURE),
        "--sources-dir", str(SOURCES_DIR),
        "--dedup-papers-file", str(DEDUP_FILE),
        "--anchors", "2008.12019",
        "--kuzu-path", str(tmp_path / "no-such-graph"),
        "--out", str(tmp_path / out_name),
    ]


# ---------------------------------------------------------------------------
# Windowing
# ---------------------------------------------------------------------------


class TestWindowing:
    def test_valid_six_month_window(self) -> None:
        w = parse_window("2026-01-01", "2026-07-01")
        assert w.start.isoformat() == "2026-01-01"
        assert w.as_payload()["months"] == 6

    @pytest.mark.parametrize(
        ("frm", "to"),
        [
            ("2026-01-01", "2026-02-01"),  # 1 month — too short
            ("2026-01-01", "2026-03-31"),  # just under 3 months
            ("2025-01-01", "2026-06-01"),  # 17 months — too long
            ("2026-07-01", "2026-01-01"),  # reversed
            ("2026-13-01", "2026-07-01"),  # not a date
        ],
    )
    def test_invalid_windows_rejected(self, frm: str, to: str) -> None:
        with pytest.raises(ValueError):
            parse_window(frm, to)

    def test_window_from_months_bounds(self) -> None:
        with pytest.raises(ValueError):
            window_from_months(2)
        with pytest.raises(ValueError):
            window_from_months(13)
        w = window_from_months(3)
        assert (w.end - w.start).days >= 88

    def test_contains_accepts_rfc3339_and_bare_dates(self) -> None:
        w = _window_2026h1()
        assert w.contains("2026-02-15T09:00:00Z")
        assert w.contains("2026-01-01")
        assert not w.contains("2025-12-31T23:59:59Z")
        assert not w.contains("2026-07-02")
        assert not w.contains("")
        assert not w.contains("not-a-date")

    def test_paper_id_month(self) -> None:
        assert paper_id_month("2601.00777") == (2026, 1)
        assert paper_id_month("2605.90000v3") == (2026, 5)
        assert paper_id_month("hep-th/0001234") is None
        assert paper_id_month("textbook:huybrechts-fm") is None

    def test_contains_month_requires_entire_month(self) -> None:
        w = _window_2026h1()
        assert w.contains_month(2026, 5)
        assert not w.contains_month(2026, 7)  # window ends 2026-07-01
        assert not w.contains_month(2025, 12)


# ---------------------------------------------------------------------------
# Atom channel (fixture mode — no network)
# ---------------------------------------------------------------------------


class TestAtomChannel:
    def test_fixture_parses_six_entries(self) -> None:
        cands = atom_channel.load_fixture_candidates(ATOM_FIXTURE)
        assert [c.paper_id for c in cands] == [
            "2602.11111",
            "2603.22222",
            "2601.00777",
            "2604.33333",
            "2512.99999",
            "2507.55555",
        ]

    def test_window_filter_drops_out_of_window(self) -> None:
        cands = atom_channel.load_fixture_candidates(ATOM_FIXTURE)
        kept = atom_channel.filter_to_window(cands, _window_2026h1())
        assert [c.paper_id for c in kept] == [
            "2602.11111",
            "2603.22222",
            "2601.00777",
            "2604.33333",
        ]

    def test_missing_fixture_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="fixture not found"):
            atom_channel.load_fixture_candidates(tmp_path / "nope.xml")


# ---------------------------------------------------------------------------
# Dedup (AC-E.2)
# ---------------------------------------------------------------------------


class TestDedup:
    def test_versioned_ids_normalized(self) -> None:
        ids = load_dedup_ids(DEDUP_FILE)
        assert ids == {"2601.00777", "1301.00001"}

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="not found"):
            load_dedup_ids(tmp_path / "papers.txt")


# ---------------------------------------------------------------------------
# Open-problem sources (AC-E.4)
# ---------------------------------------------------------------------------


class TestSources:
    def test_snapshots_load(self) -> None:
        snaps = sources.load_snapshots(SOURCES_DIR)
        assert [s.name for s in snaps] == [
            "emergentmind-open-problems",
            "formal-conjectures",
            "randomstrasse101",
        ]
        assert all(s.retrieved_at for s in snaps)

    def test_snapshot_without_name_rejected(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.snapshot.json"
        bad.write_text(
            json.dumps({"retrieved_at": "2026-07-01T00:00:00Z", "entries": []}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="'name'"):
            sources.load_snapshot(bad)

    def test_snapshot_without_retrieved_at_rejected(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.snapshot.json"
        bad.write_text(
            json.dumps({"name": "x", "entries": []}), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="'retrieved_at'"):
            sources.load_snapshot(bad)

    def test_explicit_arxiv_id_match(self) -> None:
        snaps = sources.load_snapshots(SOURCES_DIR)
        result = sources.cross_reference(
            snaps, [("2604.33333", "Tilt-stability inequalities threefolds")]
        )
        lines = result.provenance["2604.33333"]
        assert any(
            "formal-conjectures entry fc-bg-threefolds: explicitly cites arXiv:2604.33333"
            in line
            for line in lines
        )

    def test_keyword_overlap_match(self) -> None:
        snaps = sources.load_snapshots(SOURCES_DIR)
        text = (
            "Bridgeland stability conditions on Kuznetsov components of cubic "
            "fourfolds We study moduli spaces of semistable objects"
        )
        result = sources.cross_reference(snaps, [("2602.11111", text)])
        lines = result.provenance.get("2602.11111", [])
        assert any(
            line.startswith("emergentmind-open-problems entry em-42: keyword overlap")
            for line in lines
        )

    def test_unrelated_paper_gets_no_provenance(self) -> None:
        snaps = sources.load_snapshots(SOURCES_DIR)
        result = sources.cross_reference(
            snaps, [("2601.55555", "Completely unrelated topology of sandwiches")]
        )
        assert "2601.55555" not in result.provenance


# ---------------------------------------------------------------------------
# Bridging textbooks
# ---------------------------------------------------------------------------


class TestTextbooks:
    def test_topic_matches_rank_first(self) -> None:
        rows = textbooks.propose_textbooks(
            ["math.AG"], "Bridgeland stability conditions and moduli spaces"
        )
        assert rows, "math.AG must yield curated textbooks"
        assert "topic match" in rows[0]["source"]
        assert all(r["source"].startswith("curated bridging-textbook table v0") for r in rows)

    def test_unknown_category_yields_empty(self) -> None:
        assert textbooks.propose_textbooks(["math.XX"], "anything") == []

    def test_cap_respected_and_deterministic(self) -> None:
        a = textbooks.propose_textbooks(["math.AG", "math.NT"], "elliptic curves", cap=2)
        b = textbooks.propose_textbooks(["math.AG", "math.NT"], "elliptic curves", cap=2)
        assert a == b
        assert len(a) == 2


# ---------------------------------------------------------------------------
# cite_neighbors channel degradation
# ---------------------------------------------------------------------------


class TestGraphChannel:
    def test_no_anchors_is_skipped(self, tmp_path: Path) -> None:
        result = graph_channel.probe_graph([], tmp_path / "kuzu")
        assert result.graph_status == graph_channel.GRAPH_SKIPPED
        assert result.neighbors == []

    def test_missing_path_is_absent(self, tmp_path: Path) -> None:
        result = graph_channel.probe_graph(["2008.12019"], tmp_path / "kuzu")
        assert result.graph_status == graph_channel.GRAPH_ABSENT
        assert result.neighbors == []

    def test_invalid_anchor_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="invalid anchor"):
            graph_channel.probe_graph(["../etc/passwd"], tmp_path / "kuzu")

    def test_unqueryable_path_is_unavailable(self, tmp_path: Path) -> None:
        junk = tmp_path / "kuzu"
        junk.mkdir()
        (junk / "not-a-graph.txt").write_text("junk", encoding="utf-8")
        result = graph_channel.probe_graph(["2008.12019"], junk)
        assert result.graph_status == graph_channel.GRAPH_UNAVAILABLE

    def test_synthetic_graph_is_present_with_provenance(self, tmp_path: Path) -> None:
        from tests._graph_helpers import build_synthetic_kuzu_graph

        db = tmp_path / "kuzu"
        paper_ids = build_synthetic_kuzu_graph(db, n_papers=6, edges_per_paper=2)
        anchor = paper_ids[0]
        result = graph_channel.probe_graph([anchor], db, depth=1)
        assert result.graph_status == graph_channel.GRAPH_PRESENT
        neighbor_ids = {n.paper_id for n in result.neighbors}
        assert neighbor_ids, "anchor must have 1-hop neighbors in the synthetic graph"
        some_neighbor = sorted(neighbor_ids)[0]
        lines = result.provenance_for(some_neighbor)
        assert lines and lines[0].startswith("cite_neighbors ")
        assert f"from anchor {anchor}" in lines[0]


# ---------------------------------------------------------------------------
# Manifest schema (v0.2 contract) — AC-E.1/AC-E.4 at the schema level
# ---------------------------------------------------------------------------


class TestManifestSchema:
    def _valid_example(self) -> dict:
        return load_json(
            REPO_ROOT / "contracts" / "examples"
            / "proposed-notebook-manifest.v0.example.json"
        )

    def test_committed_example_is_valid(self) -> None:
        validator = validator_for(MANIFEST_SCHEMA)
        errors = [e.message for e in validator.iter_errors(self._valid_example())]
        assert errors == []

    def test_paper_without_source_citation_rejected(self) -> None:
        artifact = self._valid_example()
        del artifact["payload"]["papers"][0]["source_citation"]
        assert not validator_for(MANIFEST_SCHEMA).is_valid(artifact)

    def test_paper_with_empty_source_citation_rejected(self) -> None:
        artifact = self._valid_example()
        artifact["payload"]["papers"][0]["source_citation"] = ""
        assert not validator_for(MANIFEST_SCHEMA).is_valid(artifact)

    def test_open_problem_source_without_name_rejected(self) -> None:
        artifact = self._valid_example()
        artifact["payload"]["open_problem_sources"].append({"kind": "mystery"})
        assert not validator_for(MANIFEST_SCHEMA).is_valid(artifact)

    def test_window_months_out_of_range_rejected(self) -> None:
        artifact = self._valid_example()
        artifact["payload"]["window"]["months"] = 2
        assert not validator_for(MANIFEST_SCHEMA).is_valid(artifact)

    def test_registry_serves_v02_for_major_zero(self) -> None:
        assert select_schema(manifest.ARTIFACT_TYPE, "0.2") == MANIFEST_SCHEMA
        assert manifest.ARTIFACT_VERSION == "0.2"


# ---------------------------------------------------------------------------
# WS-E conformance rules beyond the schema
# ---------------------------------------------------------------------------


class TestConformance:
    def _base_manifest(self, papers: list[dict]) -> dict:
        return manifest.build_manifest(
            topic={"title": "T", "categories": ["math.AG"]},
            window=_window_2026h1(),
            papers=papers,
            textbooks=[],
            produced_at="2026-07-04T00:00:00Z",
        )

    def test_clean_manifest_passes(self) -> None:
        m = self._base_manifest(
            [
                {
                    "arxiv_id": "2602.11111",
                    "published": "2026-02-15T09:00:00Z",
                    "source_citation": "arXiv Atom channel fixture",
                }
            ]
        )
        assert manifest.conformance_violations(m) == []

    def test_out_of_window_published_flagged(self) -> None:
        m = self._base_manifest(
            [
                {
                    "arxiv_id": "2512.99999",
                    "published": "2025-12-20T09:00:00Z",
                    "source_citation": "x",
                }
            ]
        )
        violations = manifest.conformance_violations(m)
        assert len(violations) == 1
        assert "AC-E.2" in violations[0]

    def test_missing_source_citation_flagged(self) -> None:
        m = self._base_manifest(
            [{"arxiv_id": "2602.11111", "published": "2026-02-15T09:00:00Z"}]
        )
        violations = manifest.conformance_violations(m)
        assert len(violations) == 1
        assert "AC-E.4" in violations[0]

    def test_dateless_graph_paper_needs_in_window_id_month(self) -> None:
        ok = self._base_manifest(
            [{"arxiv_id": "2605.90001", "source_citation": "cite_neighbors ..."}]
        )
        assert manifest.conformance_violations(ok) == []
        bad = self._base_manifest(
            [{"arxiv_id": "2507.00001", "source_citation": "cite_neighbors ..."}]
        )
        violations = manifest.conformance_violations(bad)
        assert len(violations) == 1 and "AC-E.2" in violations[0]

    def test_bad_window_short_circuits(self) -> None:
        m = self._base_manifest([])
        m["payload"]["window"] = {"from": "2026-01-01", "to": "2026-02-01"}
        violations = manifest.conformance_violations(m)
        assert len(violations) == 1 and violations[0].startswith("window:")


# ---------------------------------------------------------------------------
# Golden path (AC-E.1) — offline end-to-end + zero-mutation audit
# ---------------------------------------------------------------------------


def _tree_digest(root: Path) -> dict[str, str]:
    """SHA-256 of every file under ``root`` (relative path -> digest)."""
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return out


class TestGoldenPath:
    @pytest.fixture()
    def golden(self, tmp_path: Path, capsys) -> dict:
        rc = propose_main(_golden_args(tmp_path))
        captured = capsys.readouterr()
        if rc != 0:
            raise AssertionError(f"golden path failed rc={rc}: {captured.err}")
        return json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    def test_exit_zero_and_manifest_written(self, golden: dict) -> None:
        assert golden["bridge"]["artifact"] == manifest.ARTIFACT_TYPE

    def test_envelope_conformance_via_c1_helpers(self, golden: dict) -> None:
        """AC-E.1: the emitted artifact validates against the WS-C
        contracts through the C1 reference helpers."""
        validator = validator_for(MANIFEST_SCHEMA)
        errors = [e.message for e in validator.iter_errors(golden)]
        assert errors == []
        assert select_schema(
            golden["bridge"]["artifact"], golden["bridge"]["version"]
        ) == MANIFEST_SCHEMA

    def test_substrate_is_server_scoped_with_bp1_pin(self, golden: dict) -> None:
        sub = golden["bridge"]["substrate"]
        assert sub["server"] == "arxmcp"
        assert sub["corpus_version"] is None
        assert sub["notebook"] is None
        assert sub["retrieval_mode"] == "dense_only"
        assert sub["tool_schema_sha256"] == manifest.TOOL_SCHEMA_SHA256_PIN

    def test_window_and_papers(self, golden: dict) -> None:
        """AC-E.2: in-window only; dedup excluded 2601.00777."""
        papers = golden["payload"]["papers"]
        ids = [p["arxiv_id"] for p in papers]
        assert ids == ["2602.11111", "2603.22222", "2604.33333"]
        window = _window_2026h1()
        assert all(window.contains(p["published"]) for p in papers)
        assert golden["payload"]["dedup"]["excluded_paper_ids"] == ["2601.00777"]

    def test_every_paper_has_provenance(self, golden: dict) -> None:
        """AC-E.4 on the real output."""
        for p in golden["payload"]["papers"]:
            assert p["source_citation"].startswith("arXiv Atom channel cat:math.AG")

    def test_open_problem_matches_recorded(self, golden: dict) -> None:
        papers = {p["arxiv_id"]: p for p in golden["payload"]["papers"]}
        corr = papers["2604.33333"].get("corroborations", [])
        assert any("explicitly cites arXiv:2604.33333" in c for c in corr)
        corr_kw = papers["2602.11111"].get("corroborations", [])
        assert any("keyword overlap" in c for c in corr_kw)
        by_name = {
            s["name"]: s for s in golden["payload"]["open_problem_sources"]
        }
        assert by_name["formal-conjectures"]["entries_matched"] >= 1
        assert by_name["emergentmind-open-problems"]["entries_matched"] >= 1
        assert by_name["randomstrasse101"]["entries_matched"] == 0
        assert all("retrieved_at" in s for s in by_name.values())

    def test_textbooks_proposed_with_source(self, golden: dict) -> None:
        rows = golden["payload"]["textbooks"]
        assert rows
        assert all(r.get("source") for r in rows)

    def test_graph_channel_recorded_absent(self, golden: dict) -> None:
        """The citation graph is absent on this workstation (finding 211
        R-A); the run proceeds and records the degradation."""
        cn = golden["payload"]["channels"]["cite_neighbors"]
        assert cn["graph_status"] == "absent"
        assert cn["anchors"] == ["2008.12019"]

    def test_zero_mutation_audit(self, tmp_path: Path) -> None:
        """AC-E.1 'first test to pin': a run mutates NOTHING it reads —
        the only filesystem change is the named output file."""
        import shutil

        data = tmp_path / "data"
        shutil.copytree(FIXTURES, data / "exploration")
        out_dir = tmp_path / "out"
        args = [
            "--topic-title", "Zero mutation audit",
            "--category", "math.AG",
            "--window-from", "2026-01-01",
            "--window-to", "2026-07-01",
            "--atom-fixture", str(data / "exploration" / "atom-window.xml"),
            "--sources-dir", str(data / "exploration" / "sources"),
            "--dedup-papers-file", str(data / "exploration" / "dedup-papers.txt"),
            "--anchors", "2008.12019",
            "--kuzu-path", str(data / "no-graph"),
            "--out", str(out_dir / "manifest.json"),
        ]
        before = _tree_digest(data)
        rc = propose_main(args)
        after = _tree_digest(data)
        assert rc == 0
        assert before == after, "the run must not mutate any input tree"
        assert sorted(p.name for p in out_dir.iterdir()) == ["manifest.json"]

    def test_bad_window_exits_nonzero(self, tmp_path: Path, capsys) -> None:
        args = _golden_args(tmp_path)
        args[args.index("--window-to") + 1] = "2026-02-01"  # 1-month window
        rc = propose_main(args)
        captured = capsys.readouterr()
        assert rc == 1
        assert "PROPOSAL FAILED" in captured.err
        assert not (tmp_path / "manifest.json").exists()


# ---------------------------------------------------------------------------
# Pipeline README (AC-E.5)
# ---------------------------------------------------------------------------


class TestPipelineReadme:
    def test_readme_exists(self) -> None:
        assert PIPELINE_README.is_file()

    @pytest.mark.parametrize(
        "trigger_text",
        [
            ">~1,000 LOC of\n>    non-prompt code",
            "A second machine or remote execution surface enters the topology",
            "Bridge contracts gain consumers outside the two repos",
            "run-ledger/campaign state outgrows per-repo `.claude/notes/`",
        ],
    )
    def test_extraction_triggers_recorded_verbatim(self, trigger_text: str) -> None:
        text = PIPELINE_README.read_text(encoding="utf-8")
        assert trigger_text in text

    def test_readme_states_propose_confirm(self) -> None:
        text = PIPELINE_README.read_text(encoding="utf-8")
        assert "zero mutating calls" in text
        assert "propose" in text.lower() and "confirm" in text.lower()


# ---------------------------------------------------------------------------
# BP1 pin lockstep
# ---------------------------------------------------------------------------


def test_tool_schema_pin_lockstep() -> None:
    """The vendored pin in tools/exploration/manifest.py must equal
    EXPECTED_TOOL_SCHEMA_SHA256 (tests/test_server_tool_schema.py)."""
    source = (REPO_ROOT / "tests" / "test_server_tool_schema.py").read_text(
        encoding="utf-8"
    )
    m = re.search(
        r'EXPECTED_TOOL_SCHEMA_SHA256:\s*str\s*=\s*\(\s*#[^\n]*\n\s*"([a-f0-9]{64})"',
        source,
    )
    assert m is not None, "could not locate the pinned hash"
    assert m.group(1) == manifest.TOOL_SCHEMA_SHA256_PIN


# ---------------------------------------------------------------------------
# Live smoke + AC-E.3 backtest (opt-in; never run in the default suite)
# ---------------------------------------------------------------------------

_LIVE = os.environ.get("ARXMCP_RUN_LIVE_DISCOVERY") == "1"


class TestLiveSmoke:
    @pytest.mark.skipif(not _LIVE, reason="set ARXMCP_RUN_LIVE_DISCOVERY=1 to run")
    def test_live_atom_window_scan(self) -> None:
        """ONE live smoke behind an env flag: a small live Atom fetch
        parses and window-filters without error."""
        window = window_from_months(6)
        raw = atom_channel.fetch_live_candidates(
            "math.AG", 25, os.environ.get("ARXMCP_CONTACT_EMAIL")
        )
        assert raw, "live Atom scan returned nothing"
        kept = atom_channel.filter_to_window(raw, window)
        assert kept, "top-25 newest math.AG papers should fall in a 6-month window"
        assert all(c.paper_id and c.submitted_date for c in kept)

    @pytest.mark.skipif(
        not (_LIVE and os.environ.get("ARXMCP_BACKTEST_PAPERS_FILE")),
        reason=(
            "set ARXMCP_RUN_LIVE_DISCOVERY=1 and ARXMCP_BACKTEST_PAPERS_FILE "
            "(+ optionally ARXMCP_BACKTEST_CATEGORY / _WINDOW_FROM / _WINDOW_TO / "
            "_MIN_RECALL) to run the AC-E.3 retrospective backtest"
        ),
    )
    def test_retrospective_backtest_recall(self) -> None:
        """AC-E.3: the channel recalls >= min_recall of the curated papers
        whose submission month lies inside the backtest window (threshold
        tunable via env, recorded with the run output)."""
        papers_file = Path(os.environ["ARXMCP_BACKTEST_PAPERS_FILE"])
        category = os.environ.get("ARXMCP_BACKTEST_CATEGORY", "math.AG")
        frm = os.environ.get("ARXMCP_BACKTEST_WINDOW_FROM", "")
        to = os.environ.get("ARXMCP_BACKTEST_WINDOW_TO", "")
        min_recall = float(os.environ.get("ARXMCP_BACKTEST_MIN_RECALL", "0.5"))
        window = (
            parse_window(frm, to) if frm and to else window_from_months(12)
        )
        curated = load_dedup_ids(papers_file)
        in_window = {
            pid
            for pid in curated
            if (ym := paper_id_month(pid)) is not None and window.contains_month(*ym)
        }
        if not in_window:
            pytest.skip(
                f"no curated papers fall inside {window.start}..{window.end}; "
                "choose a creation-era window"
            )
        # Fetch depth must cover the window: math.AG alone runs ~400
        # papers/month, so a 12-month window needs ~5-6k results (the
        # library paginates politely). Measured 2026-07-04: 6000 covers
        # back past 2025-07 with margin.
        max_results = int(os.environ.get("ARXMCP_BACKTEST_MAX_RESULTS", "6000"))
        raw = atom_channel.fetch_live_candidates(
            category, max_results, os.environ.get("ARXMCP_CONTACT_EMAIL")
        )
        found = {c.paper_id for c in atom_channel.filter_to_window(raw, window)}
        recall = len(in_window & found) / len(in_window)
        print(
            f"AC-E.3 backtest: window {window.start}..{window.end} cat={category} "
            f"fetched={len(raw)} curated-in-window={len(in_window)} "
            f"recalled={len(in_window & found)} recall={recall:.2f} "
            f"threshold={min_recall}"
        )
        assert recall >= min_recall
