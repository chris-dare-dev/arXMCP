"""License-coverage report over the documents registry (source-truth-m1).

Reads the per-notebook :class:`server.documents_store.DocumentsStore`
(``var/arxmcp/notebooks/<slug>/documents.db``) for both live notebooks
and emits, per notebook:

- counts by the FULL 3-way ``license_status`` value set (``eligible`` /
  ``not-allowlisted-open`` / ``unknown``) — never a binary known/unknown,
  because ``not-allowlisted-open`` (a real license, allowlist decision
  pending) and ``unknown`` (a genuine data gap) demand DIFFERENT owner
  responses;
- counts by id shape (new-style / old-style / versioned), since the
  research found old-style ids carry materially higher missing-license
  risk (arXiv never backfilled ``<license>`` for pre-2007 records).

**Owner-escalation gate (source-truth-m1 OWNER DECISION C).** The >20%
threshold is measured on ``unknown`` ALONE (the data-completeness
question — genuine gaps), NOT on ``unknown + not-allowlisted-open``. When
``bridgeland-stability``'s ``unknown`` rate exceeds
:data:`UNKNOWN_ESCALATION_THRESHOLD`, the report emits a LOUD stderr
block and exits non-zero BEFORE any serving cutover. The
``not-allowlisted-open`` count is reported EQUALLY prominently (a large
value there is the real "most papers truncate at m4" headline), but it
does NOT feed the escalation exit code — folding it into ``unknown``
would corrupt the signal.

This report is ADVISORY: it reads the registry and prints. It changes no
serving behavior and touches no ``chunks`` table or embedder.

Usage:

    uv run python tools/documents_coverage_report.py

Exit codes:
    0 — the escalation notebook's unknown rate is within budget
    1 — the escalation notebook's unknown rate exceeds the threshold, OR
        its registry is missing / empty (the gate cannot be measured —
        a loud pre-cutover fail state)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

from server.documents_store import (
    DOCUMENTS_DB_FILENAME,
    DocumentRecord,
    DocumentsStore,
)
from tools._notebook_common import notebook_dir
from tools.oai_license import (
    LICENSE_STATUS_ELIGIBLE,
    LICENSE_STATUS_NOT_ALLOWLISTED_OPEN,
    LICENSE_STATUS_UNKNOWN,
)

#: The two live notebooks m1's acceptance names (``bridgeland-stability-pdfs``
#: / ``fourier-duality-pdfs`` are separate MinerU-path notebooks, NOT
#: these).
DEFAULT_NOTEBOOKS: tuple[str, ...] = (
    "bridgeland-stability",
    "fourier-duality",
)

#: The notebook whose ``unknown`` rate gates the owner escalation.
ESCALATION_NOTEBOOK: str = "bridgeland-stability"

#: Owner-escalation threshold on the ``unknown`` rate ALONE (Decision C).
UNKNOWN_ESCALATION_THRESHOLD: float = 0.20


@dataclass
class CoverageStats:
    """Per-notebook coverage aggregate."""

    slug: str
    present: bool = True  # False when the registry DB is missing
    total: int = 0
    license_status: dict[str, int] = field(default_factory=dict)
    new_style: int = 0
    old_style: int = 0
    versioned: int = 0

    @property
    def unknown(self) -> int:
        return self.license_status.get(LICENSE_STATUS_UNKNOWN, 0)

    @property
    def not_allowlisted_open(self) -> int:
        return self.license_status.get(LICENSE_STATUS_NOT_ALLOWLISTED_OPEN, 0)

    @property
    def eligible(self) -> int:
        return self.license_status.get(LICENSE_STATUS_ELIGIBLE, 0)

    @property
    def unknown_rate(self) -> float:
        """``unknown`` fraction; 0.0 for an empty registry."""
        return self.unknown / self.total if self.total else 0.0


def _analyze(slug: str, records: list[DocumentRecord]) -> CoverageStats:
    """Fold a notebook's registry rows into a :class:`CoverageStats`."""
    stats = CoverageStats(slug=slug, present=True, total=len(records))
    for r in records:
        stats.license_status[r.license_status] = (
            stats.license_status.get(r.license_status, 0) + 1
        )
        # Id shape: versioned is cross-cutting (an explicit vN in the
        # membership line); new vs old by the work id's own shape.
        if r.arxiv_version:
            stats.versioned += 1
        if "/" in r.work_id:
            stats.old_style += 1
        else:
            stats.new_style += 1
    return stats


async def _load_stats(slug: str, *, base: Path | None) -> CoverageStats:
    """Load one notebook's registry into a :class:`CoverageStats`.

    Does NOT create the DB: a missing ``documents.db`` returns
    ``present=False`` (the server never scatters empty registries next to
    un-backfilled notebooks — same non-critical-enrichment contract as
    ``paper_metadata.db``).
    """
    db_path = notebook_dir(slug, base=base) / DOCUMENTS_DB_FILENAME
    if not db_path.is_file():
        return CoverageStats(slug=slug, present=False)
    store = await DocumentsStore.open(db_path)
    try:
        records = await store.all_records()
    finally:
        await store.close()
    return _analyze(slug, records)


def _format_block(stats: CoverageStats) -> str:
    """Render one notebook's coverage block."""
    if not stats.present:
        return (
            f"=== {stats.slug} ===\n"
            f"  registry NOT FOUND (documents.db missing — not yet "
            f"backfilled)"
        )
    return (
        f"=== {stats.slug} ===\n"
        f"  total={stats.total}\n"
        f"  license_status: "
        f"eligible={stats.eligible} "
        f"not-allowlisted-open={stats.not_allowlisted_open} "
        f"unknown={stats.unknown} "
        f"(unknown_rate={stats.unknown_rate * 100:.1f}%)\n"
        f"  id_shape: "
        f"new-style={stats.new_style} "
        f"old-style={stats.old_style} "
        f"versioned={stats.versioned}"
    )


def run(
    *,
    base: Path | None = None,
    notebooks: tuple[str, ...] = DEFAULT_NOTEBOOKS,
    escalation_notebook: str = ESCALATION_NOTEBOOK,
    threshold: float = UNKNOWN_ESCALATION_THRESHOLD,
) -> int:
    """Emit the coverage report; return the process exit code.

    ``base`` / ``notebooks`` / ``escalation_notebook`` / ``threshold``
    are test seams; production callers pass nothing.
    """
    all_stats = [
        asyncio.run(_load_stats(slug, base=base)) for slug in notebooks
    ]
    for stats in all_stats:
        print(_format_block(stats))

    by_slug = {s.slug: s for s in all_stats}
    gate = by_slug.get(escalation_notebook)

    # Escalation is on `unknown` ALONE (Decision C). `not-allowlisted-open`
    # is reported equally prominently but never feeds the exit code.
    escalated = False
    if gate is None or not gate.present or gate.total == 0:
        print(
            f"\nESCALATION: cannot measure the >{threshold * 100:.0f}% "
            f"unknown-rate gate for {escalation_notebook!r} — its registry "
            f"is missing or empty. Run the documents backfill before any "
            f"serving cutover.",
            file=sys.stderr,
        )
        escalated = True
    elif gate.unknown_rate > threshold:
        print(
            f"\nESCALATION: {escalation_notebook!r} unknown-license rate "
            f"{gate.unknown_rate * 100:.1f}% exceeds the "
            f"{threshold * 100:.0f}% threshold "
            f"({gate.unknown} of {gate.total} revisions have NO license "
            f"data). This is a genuine data-gap signal — resolve before "
            f"any m4 serving cutover.\n"
            f"  (reported alongside, NOT folded in: "
            f"not-allowlisted-open={gate.not_allowlisted_open} — real "
            f"licenses whose OA-allowlist decision is the owner's.)",
            file=sys.stderr,
        )
        escalated = True
    else:
        print(
            f"\nOK: {escalation_notebook!r} unknown-license rate "
            f"{gate.unknown_rate * 100:.1f}% is within the "
            f"{threshold * 100:.0f}% threshold "
            f"(not-allowlisted-open={gate.not_allowlisted_open} reported "
            f"separately — the owner's allowlist call, not a data gap)."
        )
    return 1 if escalated else 0


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    ).parse_args(argv)
    return run()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
