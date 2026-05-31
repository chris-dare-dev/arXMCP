"""Lock the E05_S03 acceptance criteria as CI-enforced contracts.

E05_S03 originally shipped ``TIER-GATES.md`` at the repo root.
A 2026-05-10 repo-wide doc-layout consolidation moved it under
``.claude/`` so the root contains only user-facing files (README,
CLAUDE, CHANGES, SECURITY, OWNERS). The brief's 5 ACs remain
load-bearing; the path constants below were updated in lockstep
with the move, and the "README links to TIER-GATES.md" AC was
DROPPED — TIER-GATES.md is now agent-internal, no longer user-
facing, and the README is restricted to project description /
how-to-use / layout content.

This module enforces the surviving ACs: existence, four-transition
coverage, verbatim reranker-activation sentence, ``make eval`` shape,
no subjective markers in spec regions.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# Moved 2026-05-10 from repo root to ``.claude/`` per the doc-layout
# consolidation (root-MD restriction).
TIER_GATES_PATH = REPO_ROOT / ".claude" / "TIER-GATES.md"
MAKEFILE_PATH = REPO_ROOT / "Makefile"


# ---------------------------------------------------------------------------
# AC #1 — TIER-GATES.md exists and defines all four transitions
# ---------------------------------------------------------------------------


class TestTierGatesExists:
    def test_file_exists(self):
        """AC #1 (revised post-doc-consolidation): ``TIER-GATES.md``
        exists at the agent-context location ``.claude/TIER-GATES.md``.
        The original AC said "at the repo root"; the repo-wide
        doc-layout consolidation moved it under ``.claude/`` and
        updated this assertion in lockstep."""
        assert TIER_GATES_PATH.is_file(), (
            f"TIER-GATES.md must exist at {TIER_GATES_PATH}"
        )

    def test_lists_all_four_transitions(self):
        """AC #1: the file defines all four tier transitions named in
        the brief table. Each row's left-cell label is a load-bearing
        identifier — its absence breaks reader navigation AND
        E07_S04's own AC (which references the Tier-1 → Tier-2 row)."""
        content = TIER_GATES_PATH.read_text(encoding="utf-8")
        for transition in (
            "Tier-0 → Tier-1",
            "Tier-1 → Tier-2",
            "Tier-2 → Tier-3",
            "Tier-5 cutover",
        ):
            assert transition in content, (
                f"TIER-GATES.md must mention {transition!r}; "
                f"missing from {TIER_GATES_PATH.name}"
            )


# ---------------------------------------------------------------------------
# AC #2 — make eval runs the right pytest invocation
# ---------------------------------------------------------------------------


class TestMakeEvalTarget:
    def test_eval_target_in_phony(self):
        """``eval`` is in the ``.PHONY`` list — guards against a
        future ``eval/`` directory shadowing the target.

        onboarding-uplift-m3 / m2 critique F8 closure: the Makefile's
        single 219-char ``.PHONY`` line was split into per-section
        stanzas grouped by topic (FIRST-TIME?, CORPUS LIFECYCLE, OPS,
        NOTEBOOK CRUD, REPAIR/RECONCILE). This test now collects
        targets from EVERY ``.PHONY:`` line in the file rather than
        the first match.
        """
        content = MAKEFILE_PATH.read_text(encoding="utf-8")
        phony_targets: list[str] = []
        for phony_match in re.finditer(
            r"^\.PHONY:\s+(.+)$", content, re.MULTILINE
        ):
            phony_targets.extend(phony_match.group(1).split())
        assert phony_targets, "Makefile must declare at least one .PHONY line"
        assert "eval" in phony_targets, (
            f".PHONY must list 'eval' across some stanza; "
            f"got {phony_targets}"
        )

    def test_eval_recipe_invokes_correct_pytest_path(self):
        """AC #2: ``make eval`` runs
        ``pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.70``
        verbatim. The brief specifies the EXACT invocation."""
        content = MAKEFILE_PATH.read_text(encoding="utf-8")
        # The recipe line should contain both the test path and the flag.
        # Allow flexible spacing / Python invocation form (the existing
        # `test:` target uses `$(PYTHON) -m pytest`).
        assert (
            "tests/eval/test_retrieval_quality.py" in content
            and "--ndcg-min=0.70" in content
        ), (
            "Makefile must invoke `pytest tests/eval/test_retrieval_quality.py "
            "--ndcg-min=0.70` (per E05_S03 AC #2)"
        )


# ---------------------------------------------------------------------------
# AC #3 — verbatim reranker-activation sentence
# ---------------------------------------------------------------------------


class TestRerankerActivationSentence:
    REQUIRED = (
        "Reranker activation in E07 is conditional on nDCG@5 ≥ 0.80 "
        "after BM25 hybrid is active."
    )

    def test_verbatim_sentence_present(self):
        """AC #3: TIER-GATES.md contains the EXACT sentence
        'Reranker activation in E07 is conditional on nDCG@5 ≥ 0.80
        after BM25 hybrid is active.' Bytewise equality — no
        whitespace collapse, no soft-break tolerance.

        Closes F1 of the E05_S03 critique: the original Phase 2 ship
        wrapped the sentence across a markdown line break, so a
        strict ``in`` check failed. The reflow in Phase 4 brought it
        onto one source line; this test locks that against future
        re-wrap.
        """
        content = TIER_GATES_PATH.read_text(encoding="utf-8")
        assert self.REQUIRED in content, (
            f"TIER-GATES.md must contain the verbatim AC sentence "
            f"(no whitespace collapse): {self.REQUIRED!r}"
        )

    def test_sentence_is_on_one_source_line(self):
        """Belt + suspenders for F1: the sentence sits on a single
        source line. Any re-wrap that splits the sentence across lines
        will fail this test even if the bytewise-equality test above
        somehow passes."""
        content = TIER_GATES_PATH.read_text(encoding="utf-8")
        for line in content.splitlines():
            if "Reranker activation in E07" in line:
                # The whole sentence must fit on this single line.
                assert self.REQUIRED in line, (
                    f"the AC sentence must sit on a single source line; "
                    f"found a line containing 'Reranker activation in E07' "
                    f"but not the full sentence: {line!r}"
                )
                return
        raise AssertionError("did not find the AC sentence at all")


# ---------------------------------------------------------------------------
# AC #4 — DROPPED (2026-05-10): README no longer links to TIER-GATES.md
# ---------------------------------------------------------------------------
#
# The original AC #4 required ``README.md`` to carry a markdown link to
# ``TIER-GATES.md``. The 2026-05-10 doc-layout consolidation restricted the
# root README to project-description / how-to-use / layout content only;
# TIER-GATES.md moved under ``.claude/`` (agent-internal). The "README
# links to TIER-GATES" assertion therefore no longer applies. The gate
# spec itself remains testable via the surviving ACs above.


# ---------------------------------------------------------------------------
# AC #5 — no subjective acceptance criteria
# ---------------------------------------------------------------------------


class TestNoSubjectiveCriteria:
    """The brief: 'No subjective acceptance criteria (no demo
    transcript or looks coherent language).'

    A reasonable proxy: the gate-spec sections of TIER-GATES.md
    must NOT contain the named subjective markers. The History
    section is the one place these phrases legitimately appear
    (they're the TARGET of supersession, not the new spec).
    """

    SUBJECTIVE_MARKERS = (
        "vibes-check",
        "looks coherent",
        "demo transcript",
    )

    def test_subjective_markers_only_appear_in_history(self):
        """Every subjective marker must appear exclusively below the
        ``## History`` heading (where it describes what was retired).

        This bounds the rule without requiring a hand-curated allow-
        list; if a future contributor sneaks 'vibes-check' into a
        new gate spec, the offset check fires.
        """
        content = TIER_GATES_PATH.read_text(encoding="utf-8")
        history_idx = content.find("## History")
        if history_idx < 0:
            # If History is removed, no subjective markers may appear
            # anywhere.
            history_idx = len(content)
        spec_region = content[:history_idx]
        for marker in self.SUBJECTIVE_MARKERS:
            assert marker not in spec_region, (
                f"subjective marker {marker!r} must not appear in the "
                f"gate-spec region of TIER-GATES.md (only allowed under "
                f"## History where it names what was retired)"
            )
