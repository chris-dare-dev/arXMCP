"""Tests for the E14_S10 ops runbook index.

Coverage matrix:

- TestIndexExists
    docs/ops/README.md is present.
- TestIndexLinkedFromRootReadme
    Root README.md links to it.
- TestAllIndexedRunbooksExist
    Every relative link inside the index resolves to a file on
    disk (link-check).
- TestEachRunbookHasSkeleton
    Each NEW runbook (server-crash, model-swap, corpus-rollback,
    latexml-restart) has the 4-part skeleton headers
    (Symptoms / Detection / Steps / Verification).
- TestRequiredScenariosCovered
    The 8 brief-mandated scenarios all appear in the index.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
INDEX_PATH: Path = REPO_ROOT / "docs" / "ops" / "README.md"
ROOT_README: Path = REPO_ROOT / "README.md"

# Runbooks created NEW by E14_S10 (must have the full 4-part skeleton).
NEW_RUNBOOKS: tuple[str, ...] = (
    "server-crash.md",
    "model-swap.md",
    "corpus-rollback.md",
    "latexml-restart.md",
)

# Brief-mandated scenarios (each must appear by name in the index).
REQUIRED_SCENARIOS: tuple[str, ...] = (
    "server-crash",
    "ingestion-pause",
    "disk-full",
    "restore from backup",
    "model swap",
    "corpus-version rollback",
    "LaTeXML worker restart",
    "drift watchdog",
)


@pytest.fixture(scope="module")
def index_text() -> str:
    return INDEX_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def root_readme_text() -> str:
    return ROOT_README.read_text(encoding="utf-8")


class TestIndexExists:
    def test_index_file_present(self) -> None:
        assert INDEX_PATH.is_file(), (
            f"Ops runbook index missing at {INDEX_PATH}"
        )


class TestIndexLinkedFromRootReadme:
    def test_root_readme_links_to_index(
        self, root_readme_text: str,
    ) -> None:
        """Root README.md must link to docs/ops/README.md so the
        index is discoverable from the project's landing page."""
        assert "docs/ops/README.md" in root_readme_text, (
            "Root README must link to docs/ops/README.md"
        )


class TestAllIndexedRunbooksExist:
    """Every relative markdown link in the index resolves to an
    existing file on disk. Link-check by filesystem stat — no HTTP
    fetches. Excludes external (http/https) links and anchor-only
    fragments (#foo) since those reference within the same file."""

    LINK_RE: re.Pattern[str] = re.compile(r"\]\(([^)]+)\)")

    def _enumerate_relative_links(self, text: str) -> list[str]:
        links = self.LINK_RE.findall(text)
        out: list[str] = []
        for link in links:
            if link.startswith(("http://", "https://", "#")):
                continue
            # Strip any anchor suffix — we only check file existence.
            file_part = link.split("#", 1)[0]
            if file_part:
                out.append(file_part)
        return out

    def test_every_relative_link_resolves(
        self, index_text: str,
    ) -> None:
        broken: list[str] = []
        for link in self._enumerate_relative_links(index_text):
            target = (INDEX_PATH.parent / link).resolve()
            if not target.exists():
                broken.append(f"  {link!r} -> {target}")
        assert not broken, (
            "Broken links in docs/ops/README.md (file not found):\n"
            + "\n".join(broken)
        )


class TestEachRunbookHasSkeleton:
    """Every NEW runbook file (created by E14_S10) has the 4-part
    skeleton headers. Existing runbooks (E11_S0x, E14_S05) are not
    required to conform — they predate this convention."""

    REQUIRED_SECTIONS: tuple[str, ...] = (
        "## Symptoms",
        "## Detection",
        "## Steps",
        "## Verification",
    )

    @pytest.mark.parametrize("runbook", NEW_RUNBOOKS)
    def test_new_runbook_has_all_skeleton_sections(
        self, runbook: str,
    ) -> None:
        path = REPO_ROOT / "docs" / "ops" / runbook
        assert path.is_file(), f"missing: {path}"
        text = path.read_text(encoding="utf-8")
        missing = [s for s in self.REQUIRED_SECTIONS if s not in text]
        assert not missing, (
            f"{runbook}: missing required skeleton section(s) {missing}"
        )


class TestRequiredScenariosCovered:
    """Every scenario in the brief's required-runbooks list appears
    in the index by name. The match is case-insensitive substring
    so phrasing variation (e.g., 'server-crash' vs 'server crash')
    doesn't break the test."""

    @pytest.mark.parametrize("scenario", REQUIRED_SCENARIOS)
    def test_scenario_mentioned_in_index(
        self, index_text: str, scenario: str,
    ) -> None:
        assert scenario.lower() in index_text.lower(), (
            f"Scenario {scenario!r} not found in docs/ops/README.md "
            f"— the brief requires all 8 scenarios listed by name"
        )
