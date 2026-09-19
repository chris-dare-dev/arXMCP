#!/usr/bin/env python3
"""Exploration pipeline v0 driver — propose an open-problem notebook manifest.

Scans a 3-12-month arXiv window (Atom channel, live or fixture),
probes the citation graph around optional anchor papers, cross-
references structured open-problem source snapshots, dedups against an
optional papers list, and writes ONE file: an envelope-wrapped
``arxmcp.bridge/proposed-notebook-manifest`` v0.2 for OPERATOR
CONFIRMATION.

PROPOSE→CONFIRM, STRICTLY (AC-E.1): this driver makes zero mutating
calls — no notebook is created, nothing is ingested, no store is
opened for write. The operator reviews the manifest and, only on
confirm, runs the ingest lane (``tools/notebook_init`` →
``tools/notebook_fetch`` → ``tools/notebook_ingest``; see
``.claude/exploration/README.md`` §"Operator confirm").

Usage (offline golden path):
    python -m tools.exploration.propose \
        --topic-title "Bridgeland stability follow-ups" \
        --category math.AG --window-from 2026-01-01 --window-to 2026-07-01 \
        --atom-fixture tests/fixtures/exploration/atom-window.xml \
        --sources-dir tests/fixtures/exploration/sources \
        --dedup-papers-file tests/fixtures/exploration/dedup-papers.txt \
        --out var/exploration/proposal.json

Live scan (agent-side/CLI fetch; the server never fetches):
    python -m tools.exploration.propose --topic-title "..." \
        --category math.NT --months 6 --email you@example.com \
        --out proposal.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from tools._arxiv_api import Candidate
from tools.exploration import atom_channel, graph_channel, manifest, sources, textbooks
from tools.exploration.windowing import (
    Window,
    paper_id_month,
    parse_window,
    window_from_months,
)

DEFAULT_KUZUDB_PATH = Path("var/arxmcp/index/kuzu")
DEFAULT_MAX_RESULTS = 200


def _strip_version(paper_id: str) -> str:
    return paper_id.split("v", 1)[0] if "v" in paper_id else paper_id


def load_dedup_ids(path: Path) -> set[str]:
    """Un-versioned paper ids from a papers.txt-style file (one id/line)."""
    if not path.is_file():
        raise ValueError(f"dedup papers file not found: {path}")
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text and not text.startswith("#"):
            ids.add(_strip_version(text))
    return ids


def assemble_papers(
    atom_candidates: list[Candidate],
    window: Window,
    *,
    category: str,
    atom_mode: str,
    dedup_ids: set[str],
    graph: graph_channel.GraphChannelResult,
    crossref: sources.CrossRefResult,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Merge channels into manifest paper entries.

    Returns ``(papers, excluded_ids)``. Rules:

    - Atom candidates (already window-filtered): dedup-excluded ids are
      dropped and recorded; the Atom hit is the ``source_citation``;
      graph + open-problem matches become ``corroborations``.
    - Graph-only neighbors: proposed only when the arXiv-id month lies
      entirely inside the window (AC-E.2 without a date signal), not
      dedup-excluded, and not already proposed via Atom.
    """
    excluded: list[str] = []
    papers: list[dict[str, Any]] = []
    proposed_ids: set[str] = set()

    for c in atom_candidates:
        pid = _strip_version(c.paper_id)
        if pid in dedup_ids:
            excluded.append(pid)
            continue
        if pid in proposed_ids:
            continue
        proposed_ids.add(pid)
        entry: dict[str, Any] = {
            "arxiv_id": pid,
            "title": c.title,
            "published": c.submitted_date,
            "source_citation": atom_channel.atom_source_citation(
                category, window, mode=atom_mode
            ),
        }
        if c.primary_category:
            entry["primary_category"] = c.primary_category
        if c.abstract_head:
            entry["abstract_head"] = c.abstract_head[:300]
        corroborations = graph.provenance_for(pid) + crossref.provenance.get(pid, [])
        if corroborations:
            entry["corroborations"] = corroborations
        papers.append(entry)

    for n in graph.neighbors:
        pid = _strip_version(n.paper_id)
        if pid in proposed_ids:
            continue
        if pid in dedup_ids:
            if pid not in excluded:
                excluded.append(pid)
            continue
        ym = paper_id_month(pid)
        if ym is None or not window.contains_month(*ym):
            continue  # cannot show recency for this neighbor (AC-E.2)
        proposed_ids.add(pid)
        lines = graph.provenance_for(pid)
        entry = {
            "arxiv_id": pid,
            "source_citation": lines[0],
        }
        extra = lines[1:] + crossref.provenance.get(pid, [])
        if extra:
            entry["corroborations"] = extra
        papers.append(entry)

    return papers, excluded


def run(args: argparse.Namespace) -> dict[str, Any]:
    """Assemble, check, and return the manifest (raises on any failure)."""
    if args.window_from and args.window_to:
        window = parse_window(args.window_from, args.window_to)
    elif args.months:
        window = window_from_months(args.months, end=date.today())
    else:
        raise ValueError("give either --window-from AND --window-to, or --months")

    categories = [c.strip() for c in args.category if c.strip()]
    if not categories:
        raise ValueError("at least one --category is required")
    scan_category = categories[0]

    # --- Atom channel (AC-E.2 window filter in both modes) ---------------
    if args.atom_fixture:
        raw = atom_channel.load_fixture_candidates(Path(args.atom_fixture))
        atom_mode = "fixture"
    else:
        raw = atom_channel.fetch_live_candidates(
            scan_category,
            args.max_results,
            args.email,
            abs_keywords=args.keywords or None,
        )
        atom_mode = "live"
    atom_candidates = atom_channel.filter_to_window(raw, window)

    # --- Dedup input ------------------------------------------------------
    dedup_ids: set[str] = set()
    dedup_target: str | None = None
    if args.dedup_papers_file:
        dedup_path = Path(args.dedup_papers_file)
        dedup_ids = load_dedup_ids(dedup_path)
        dedup_target = str(dedup_path)

    # --- Citation-graph channel -------------------------------------------
    anchors = [a.strip() for a in (args.anchors or "").split(",") if a.strip()]
    graph = graph_channel.probe_graph(
        anchors,
        Path(args.kuzu_path),
        depth=args.graph_depth,
    )

    # --- Open-problem sources (AC-E.4 provenance) ---------------------------
    snapshots: list[sources.SourceSnapshot] = []
    if args.sources_dir:
        snapshots = sources.load_snapshots(Path(args.sources_dir))
    searchable = [
        (_strip_version(c.paper_id), f"{c.title} {c.abstract_head}")
        for c in atom_candidates
    ]
    crossref = sources.cross_reference(snapshots, searchable)

    papers, excluded = assemble_papers(
        atom_candidates,
        window,
        category=scan_category,
        atom_mode=atom_mode,
        dedup_ids=dedup_ids,
        graph=graph,
        crossref=crossref,
    )

    # --- Bridging textbooks -------------------------------------------------
    topic_text = " ".join(
        [args.topic_title, args.topic_description or "", args.keywords or ""]
    )
    textbook_entries = textbooks.propose_textbooks(categories, topic_text)

    topic: dict[str, Any] = {"title": args.topic_title, "categories": categories}
    if args.topic_description:
        topic["description"] = args.topic_description
    if args.field_lane:
        topic["field_lane"] = args.field_lane
    if args.proposed_slug:
        topic["proposed_slug"] = args.proposed_slug

    source_payload = [
        snap.as_payload(crossref.matched_entries_per_source.get(snap.name, 0))
        for snap in snapshots
    ]
    channels: dict[str, Any] = {
        "atom": {
            "category": scan_category,
            "mode": atom_mode,
            "candidates_in_window": len(atom_candidates),
        },
        "cite_neighbors": {
            "graph_status": graph.graph_status,
            "anchors": graph.anchors,
            "neighbors_considered": len(graph.neighbors),
        },
    }
    dedup_block: dict[str, Any] = {
        "target": dedup_target,
        "excluded_paper_ids": sorted(excluded),
    }

    artifact = manifest.build_manifest(
        topic=topic,
        window=window,
        papers=papers,
        textbooks=textbook_entries,
        open_problem_sources=source_payload,
        channels=channels,
        dedup=dedup_block,
    )

    violations = manifest.conformance_violations(artifact)
    if violations:
        raise RuntimeError(
            "manifest fails WS-E conformance: " + "; ".join(violations)
        )
    if not args.skip_contract_validation:
        manifest.validate_against_contracts(artifact)
    return artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--topic-title", required=True, help="proposed notebook topic")
    parser.add_argument("--topic-description", default="", help="free-text topic notes")
    parser.add_argument("--field-lane", default="", help="field lane (e.g. math.AG)")
    parser.add_argument(
        "--proposed-slug", default="", help="suggested notebook slug (operator may rename)"
    )
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        help="arXiv category; repeatable. First = Atom scan category.",
    )
    parser.add_argument("--window-from", default="", help="window start (YYYY-MM-DD)")
    parser.add_argument("--window-to", default="", help="window end (YYYY-MM-DD)")
    parser.add_argument(
        "--months", type=int, default=0, help="window = last N months (3-12), ending today"
    )
    parser.add_argument("--keywords", default="", help="abs: phrase for the Atom query")
    parser.add_argument(
        "--max-results", type=int, default=DEFAULT_MAX_RESULTS, help="Atom fetch cap"
    )
    parser.add_argument("--email", default=None, help="arXiv polite-pool contact email")
    parser.add_argument(
        "--atom-fixture", default="", help="saved Atom XML (offline mode; tests)"
    )
    parser.add_argument(
        "--anchors", default="", help="comma-separated anchor paper_ids for cite_neighbors"
    )
    parser.add_argument(
        "--kuzu-path",
        default=str(DEFAULT_KUZUDB_PATH),
        help="Kuzu citation-graph dir (absent => channel degrades, run proceeds)",
    )
    parser.add_argument("--graph-depth", type=int, default=1, choices=(1, 2))
    parser.add_argument(
        "--sources-dir", default="", help="dir of open-problem *.snapshot.json files"
    )
    parser.add_argument(
        "--dedup-papers-file", default="", help="papers.txt-style exclusion list (AC-E.2)"
    )
    parser.add_argument("--out", default="", help="output path (default: stdout)")
    parser.add_argument(
        "--skip-contract-validation",
        action="store_true",
        help="skip JSON Schema validation (jsonschema unavailable)",
    )
    args = parser.parse_args(argv)

    try:
        artifact = run(args)
    except (ValueError, RuntimeError) as e:
        print(f"PROPOSAL FAILED: {e}", file=sys.stderr)
        return 1

    payload = artifact["payload"]
    print(
        f"# PROPOSAL ONLY — nothing ingested; operator confirmation required "
        f"(AC-E.1).\n"
        f"# {len(payload['papers'])} paper(s), {len(payload['textbooks'])} "
        f"textbook(s), window {payload['window']['from']}..{payload['window']['to']}, "
        f"graph_status={payload['channels']['cite_neighbors']['graph_status']}, "
        f"{len(payload.get('open_problem_sources', []))} open-problem source(s).\n"
        f"# To confirm: see .claude/exploration/README.md §'Operator confirm'.",
        file=sys.stderr,
    )
    if args.out:
        manifest.write_manifest(artifact, Path(args.out))
        print(f"# manifest written to {args.out}", file=sys.stderr)
    else:
        print(json.dumps(artifact, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
