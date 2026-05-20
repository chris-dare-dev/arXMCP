"""E13_S10 — Threat-model coverage doc staleness gate.

Validates the cumulative threat-model coverage document at
``.claude/docs/security-threat-model-coverage.md``. The doc is the
authoritative v1 audit snapshot; this gate prevents the doc from
silently drifting away from the codebase as test files are renamed,
gap-issue links rot, or new threats are added without paired
documentation updates.

The gate is intentionally lightweight — it asserts structural
properties (cited test files exist, gap rows are well-formed, the
seven numbered threats are present) but does NOT verify that each
cited test file's contents actually exercise the claimed threat
(that would require AST parsing + heuristic matching and is the
implementer's code-review responsibility, not an automation
responsibility).

Pattern mirrors
``tests/security/test_log_redaction.py::TestAuditDocPresence`` from
E13_S08 — same audit-doc-presence-and-content contract, scaled to
the 7-threat surface.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Module-level constants and helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
COVERAGE_DOC = (
    REPO_ROOT / ".claude" / "docs" / "security-threat-model-coverage.md"
)
TESTS_SECURITY_DIR = REPO_ROOT / "tests" / "security"
THREAT_MODEL_DOC = (
    REPO_ROOT / ".claude" / "notes" / "08-security-observability-ops.md"
)

# The seven numbered threats from the threat-model file. If a future
# change adds Threat 8 to the file, this constant must be updated AND
# a new row must appear in the coverage doc. The mismatch fires
# loudly in ``test_threat_count_matches_threat_model``.
EXPECTED_THREAT_NUMBERS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)


def _doc_text() -> str:
    """Read the coverage doc once per test (small file; no caching
    needed). UTF-8 is the canonical encoding for everything in
    ``.claude/docs/``."""
    return COVERAGE_DOC.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC1 — Document exists and is non-empty
# ---------------------------------------------------------------------------


class TestCoverageDocExists:
    """The audit's most basic invariant — the doc is present.

    A deleted or relocated doc would silently strip the v1 security
    posture from the repo; this test fires loudly so a refactor
    cannot quietly drop the audit chain.
    """

    def test_doc_file_present(self):
        assert COVERAGE_DOC.is_file(), (
            f"Coverage doc missing at {COVERAGE_DOC}. "
            f"E13_S10 contract: the document must live at this "
            f"path so prior E13 audit docs can cross-reference it."
        )

    def test_doc_is_not_empty(self):
        body = _doc_text()
        assert len(body.strip()) > 200, (
            f"Coverage doc at {COVERAGE_DOC} is suspiciously small "
            f"({len(body)} chars); the v1 audit snapshot should be a "
            f"substantial document."
        )

    def test_doc_links_to_threat_model_source(self):
        """The doc must cite the threat-model file by name so a
        reader can navigate from the audit back to the source of
        truth."""
        body = _doc_text()
        assert "08-security-observability-ops.md" in body, (
            "Coverage doc must link to the threat-model source file"
        )


# ---------------------------------------------------------------------------
# AC2 — Every threat has at least one automated test linked
# ---------------------------------------------------------------------------


class TestCitedTestFilesExist:
    """The doc cites concrete ``tests/security/test_*.py`` paths.
    Each cited path must exist as a real file. A rename or delete
    of a cited file silently strips the audit's coverage claim;
    this test fires loudly so the doc cannot drift.
    """

    # Match any markdown link or bare reference to a file under
    # ``tests/security/`` whose name matches the standard test_*.py
    # pattern. Captures the relative path so the assertion can
    # produce useful failure messages.
    _CITED_TEST_RE = re.compile(
        r"tests/security/(test_[a-z_]+\.py)",
    )

    def test_at_least_one_test_file_cited(self):
        body = _doc_text()
        matches = self._CITED_TEST_RE.findall(body)
        assert matches, (
            f"Coverage doc cites zero test files under "
            f"tests/security/; the brief AC mandates every threat "
            f"have at least one automated test linked. Doc body "
            f"length: {len(body)} chars."
        )

    def test_every_cited_file_exists(self):
        body = _doc_text()
        cited = set(self._CITED_TEST_RE.findall(body))
        missing = sorted(
            name for name in cited
            if not (TESTS_SECURITY_DIR / name).is_file()
        )
        assert not missing, (
            f"Coverage doc cites test files that do not exist on "
            f"disk: {missing}. Either the doc is stale (file was "
            f"renamed / deleted) or the citation is a typo. Update "
            f"the doc to match the current file layout in "
            f"tests/security/."
        )

    def test_every_security_test_file_is_cited(self):
        """Inverse contract — every real ``tests/security/test_*.py``
        file SHOULD be cited by the coverage doc. A file that exists
        but isn't cited is either dead code OR a security test
        whose threat-row was omitted from the audit.

        Allow a small allow-list for genuinely doc-independent
        infrastructure tests (e.g., this file itself).
        """
        existing = {
            p.name for p in TESTS_SECURITY_DIR.glob("test_*.py")
        }
        # This test file documents the doc itself — exclude.
        existing.discard("test_threat_model_coverage.py")

        body = _doc_text()
        cited = set(self._CITED_TEST_RE.findall(body))

        orphans = sorted(existing - cited)
        assert not orphans, (
            f"The following tests/security/ files exist but are "
            f"not cited by the coverage doc: {orphans}. Either add "
            f"a coverage-doc row for the threat each test covers, "
            f"or remove the test if it is dead. Allow-list this "
            f"check ONLY for genuinely doc-independent "
            f"infrastructure tests."
        )


# ---------------------------------------------------------------------------
# AC4 + forward maintenance — the seven numbered threats are present
# ---------------------------------------------------------------------------


class TestThreatStructure:
    """The doc must contain a heading or summary row for every
    numbered threat in the threat-model file.

    If a future change adds Threat 8 to ``08-security-observability-ops.md``,
    this test fires loudly so the coverage doc cannot silently lag
    the source-of-truth.
    """

    def test_all_seven_threats_have_section_heading(self):
        body = _doc_text()
        missing = [
            n for n in EXPECTED_THREAT_NUMBERS
            if f"## Threat {n} " not in body
        ]
        assert not missing, (
            f"Coverage doc is missing per-threat sections: {missing}. "
            f"Every numbered threat from the threat-model file must "
            f"have a corresponding `## Threat N — Name` section."
        )

    def test_all_seven_threats_appear_in_summary_table(self):
        """The summary table at the top must have a row referencing
        each threat number. A reader scanning the table should see
        a complete inventory before drilling into per-threat
        sections."""
        body = _doc_text()
        # Look for the threat number at the start of a markdown
        # table row: ``| 1 |``, ``| 2 |``, etc.
        for n in EXPECTED_THREAT_NUMBERS:
            pat = re.compile(rf"^\|\s*{n}\s*\|", re.MULTILINE)
            assert pat.search(body), (
                f"Coverage doc summary table has no row for Threat {n}"
            )

    def test_threat_model_source_threat_count_matches(self):
        """Forward-maintenance contract: if Threat 8 is added to the
        threat-model file, this test fires so the coverage doc must
        be updated in the same change.
        """
        threat_model = THREAT_MODEL_DOC.read_text(encoding="utf-8")
        # Count ``### Threat N: ...`` headings in the source-of-truth.
        threat_headings = re.findall(
            r"^### Threat (\d+):", threat_model, re.MULTILINE
        )
        actual_numbers = sorted({int(n) for n in threat_headings})
        expected_numbers = sorted(EXPECTED_THREAT_NUMBERS)
        assert actual_numbers == expected_numbers, (
            f"Threat-model file at {THREAT_MODEL_DOC} now lists "
            f"{actual_numbers}, but the coverage doc + this test's "
            f"EXPECTED_THREAT_NUMBERS expects {expected_numbers}. "
            f"Either (a) add the missing threat(s) to the coverage "
            f"doc AND update EXPECTED_THREAT_NUMBERS, or (b) remove "
            f"any deprecated threat from the threat-model file."
        )


# ---------------------------------------------------------------------------
# AC3 — gap rows are well-formed
# ---------------------------------------------------------------------------


class TestGapRowsWellFormed:
    """Every row in the doc's "Gaps" column must be one of:

    1. ``(none)`` or an em-dash ``—`` — no gap identified for this threat.
    2. ``(TODO file issue: ...)`` — gap identified, GitHub issue not
       yet filed (waiting for Phase-4 authorization).
    3. ``[#NNN — title](https://github.com/.../issues/NNN)`` — issue
       filed, link populated.

    Any other shape (e.g., a bare TODO without "(TODO file issue:" prefix,
    or a markdown link to a non-GitHub URL) is a doc-quality bug.
    """

    # Pattern matches the three well-formed shapes:
    #   - "(none)"
    #   - em-dash "—" alone
    #   - "(TODO file issue" prefix
    #   - GitHub issue URL
    _WELL_FORMED_GAP_RE = re.compile(
        r"\(none\)|—|\(TODO file issue|https://github\.com/[\w\-./]+issues/\d+",
        re.IGNORECASE,
    )

    def test_every_gap_row_is_well_formed_or_placeholder(self):
        """Loose check: every Gap cell either has a well-formed
        marker or is empty. This is the staleness gate against the
        "doc says gap but never linked an issue" failure mode.
        """
        body = _doc_text()

        # Walk every Gap-bearing table row. The summary table's
        # "Gaps" column is the last pipe-delimited cell on rows
        # whose first cell is a threat number (1-7) or em-dash
        # (the addendum row).
        problem_rows: list[str] = []
        for line in body.splitlines():
            # Only consider markdown table rows that look like the
            # summary table's data rows: start with "|" and have
            # at least 5 cells (the table has 6 columns).
            stripped = line.strip()
            if not stripped.startswith("|") or stripped.count("|") < 6:
                continue
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            # Skip header / separator rows.
            if len(cells) < 6:
                continue
            first = cells[0]
            if not (first.isdigit() or first in ("—", "-", "")):
                continue
            # Skip the separator row (cells are dashes only).
            if all(set(c) <= set("-:") for c in cells if c):
                continue
            gaps_cell = cells[-1]
            if not gaps_cell:
                # Empty cell = unclear; flag.
                problem_rows.append(
                    f"row {first}: Gaps cell is empty (use `(none)` "
                    f"if no gap)"
                )
                continue
            if not self._WELL_FORMED_GAP_RE.search(gaps_cell):
                problem_rows.append(
                    f"row {first}: Gaps cell `{gaps_cell[:60]}...` "
                    f"is not well-formed (must be `(none)`, em-dash, "
                    f"`(TODO file issue: ...)`, or a github.com "
                    f"issues URL)"
                )

        assert not problem_rows, (
            "Coverage-doc Gap-cell well-formedness violations:\n  - "
            + "\n  - ".join(problem_rows)
        )


# ---------------------------------------------------------------------------
# Forward maintenance contract — surfaced to the reader
# ---------------------------------------------------------------------------


class TestForwardMaintenanceContractDocumented:
    """The doc must surface the contract that any new threat
    added to ``08-security-observability-ops.md`` requires a paired
    coverage-doc update. Without an explicit contract in the doc,
    a future contributor might add a Threat 8 to the threat model
    and not realize they need to update the audit.
    """

    def test_doc_mentions_forward_maintenance_contract(self):
        body = _doc_text()
        # Loose substring search — "forward maintenance contract"
        # or similar language must appear so a reader of the doc
        # encounters the rule.
        assert re.search(
            r"forward[- ]maintenance|future threats?|paired update",
            body,
            re.IGNORECASE,
        ), (
            "Coverage doc must include a forward-maintenance "
            "contract — language stating that any new threat added "
            "to the threat-model file requires a paired update to "
            "this audit doc before the next epic closes."
        )


# ---------------------------------------------------------------------------
# Final smoke — milestone identifier is surfaced
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "milestone_id",
    ["E13_S01", "E13_S02", "E13_S03", "E13_S04", "E13_S05",
     "E13_S06", "E13_S07", "E13_S08", "E13_S09", "E13_S10"],
)
def test_milestone_id_appears_in_doc(milestone_id: str):
    """Every E13 milestone must be referenced in the coverage doc
    (in the Mitigation epic / Audit epic columns or the body text).
    A milestone whose work isn't traceable from the audit doc is a
    coverage gap in the audit chain itself.
    """
    body = _doc_text()
    assert milestone_id in body, (
        f"Coverage doc does not mention {milestone_id}. Every E13 "
        f"milestone's contribution to the security posture must be "
        f"traceable from the audit doc — either as a Mitigation "
        f"epic, an Audit epic, or in the body text."
    )
