"""Exploration pipeline v0 — open-problem discovery engine (stage2/arx-e1).

Deterministic, LLM-free engine behind the ``.claude/exploration/`` pipeline
(WS-E, interim home per Stage-1 decision D3). Scans a 3-12-month arXiv
window through the shipped Atom discovery library (``tools/_arxiv_api.py``)
plus the ``cite_neighbors`` citation-graph library, cross-references
structured open-problem source snapshots (DeepMind formal-conjectures,
EmergentMind Open Problems, Randomstrasse101), and emits an envelope-wrapped
``arxmcp.bridge/proposed-notebook-manifest`` (v0.2) for OPERATOR
CONFIRMATION.

Strictly propose→confirm: this package makes ZERO mutating calls against
any substrate store — its only write is the manifest file the operator
names (AC-E.1). Ingestion happens only after the operator confirms, via the
existing ``tools/notebook_*`` CLIs / the ``/ui/`` console.

Modules:

- ``windowing``    — 3-12-month window parsing/validation + recency filter
- ``atom_channel`` — arXiv Atom window scan (live or fixture; AC-E.2)
- ``graph_channel``— cite_neighbors probe with present/absent/unavailable
                     degradation (mirrors ``server/handlers/citations.py``)
- ``sources``      — open-problem source snapshots + cross-referencing
                     (AC-E.4: provenance per candidate)
- ``textbooks``    — curated bridging-textbook proposals
- ``manifest``     — envelope-wrapped manifest assembly + conformance checks
- ``propose``      — the CLI driver (``python -m tools.exploration.propose``)

Pipeline home (README, third-repo extraction triggers, operator confirm
protocol): ``.claude/exploration/README.md``.
"""
