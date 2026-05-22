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
    "ingestion-pause",  # rendered as "ingestion-pause (disk-full origin)" after F7 closure
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


class TestCurlEndpointsExist:
    """F6 closure (m10 adversary critique): corpus-rollback.md
    instructed operators to ``curl http://127.0.0.1:7733/healthz/version``
    — an endpoint that does NOT exist anywhere in server/. Result:
    operators following the runbook hit 404 on the verification
    step and have no way to confirm the rollback took effect.

    The rectification replaced that line with ``cat var/arxmcp/
    corpus-version.json`` (the actual single source of truth the
    daemon reads at lifespan startup).

    Regression guard: this test extracts every
    ``curl http://127.0.0.1:7733/<path>`` reference from
    ``docs/ops/*.md`` and asserts each ``<path>`` is one of the
    actually-registered health endpoints. If a future runbook
    references a new endpoint, either the endpoint must be added
    to server/health.py OR this allowlist updated.
    """

    # Endpoints actually registered on the server (per server/health.py
    # + server/main.py). Anything outside this allowlist is treated as
    # nonexistent by this test.
    KNOWN_ENDPOINTS: frozenset[str] = frozenset({
        "/healthz",
        "/readyz",
        "/metrics",
    })

    def test_runbook_curl_endpoints_all_exist(self) -> None:
        import re

        curl_re = re.compile(
            r"curl\s+(?:-[A-Za-z]+\s+)*http://127\.0\.0\.1:7733([^\s`'\"]+)",
        )
        offenders: list[tuple[Path, int, str]] = []
        ops_dir = REPO_ROOT / "docs" / "ops"
        for md in sorted(ops_dir.glob("*.md")):
            text = md.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                for m in curl_re.finditer(line):
                    path = m.group(1).split("?", 1)[0]  # strip query
                    if path not in self.KNOWN_ENDPOINTS:
                        offenders.append((md, line_no, path))
        assert not offenders, (
            "Runbook curl references endpoint(s) not registered on "
            "the live server (per F6):\n"
            + "\n".join(
                f"  {p.relative_to(REPO_ROOT)}:{n}: {path!r}"
                for p, n, path in offenders
            )
            + f"\nKnown endpoints: {sorted(self.KNOWN_ENDPOINTS)}. "
            "Either add the endpoint to server/health.py or rewrite "
            "the runbook step to use an existing one."
        )


class TestNoHardcodedUserPaths:
    """F5 closure (m10 adversary critique): two new runbooks
    (corpus-rollback.md, latexml-restart.md) shipped with
    ``/Users/chris.dare/Library/Python/3.9/bin/uv run python ...``
    hardcoded into the operator instructions. Per CLAUDE.md gotcha
    8 the absolute uv path is useful for AGENT-internal docs but
    docs/ops/ is operator-facing — any operator not chris.dare
    cannot run the commands as-written.

    Fix: replaced with ``uv run python`` (assumes ``uv`` is on the
    operator's PATH, which is the documented install
    expectation). The latexml-drift-runbook.md inherited the same
    antipattern from a prior milestone and was backfilled in the
    same pass.

    Regression guard: this test fails on any future docs/ops/*.md
    that hardcodes a user-specific absolute path.
    """

    def test_no_user_path_hardcoded_in_ops_docs(self) -> None:
        import re

        offenders: list[tuple[Path, int, str]] = []
        ops_dir = REPO_ROOT / "docs" / "ops"
        for md in sorted(ops_dir.glob("*.md")):
            text = md.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                # Match /Users/<name>/ — macOS home-directory pattern.
                # Excludes /Users in arbitrary prose (the regex requires
                # at least one path component after the username).
                if re.search(r"/Users/[A-Za-z][\w.-]*/\S+", line):
                    offenders.append((md, line_no, line.strip()))
        assert not offenders, (
            "Hardcoded user-specific paths in docs/ops/ (per F5):\n"
            + "\n".join(
                f"  {p.relative_to(REPO_ROOT)}:{n}: {ln}"
                for p, n, ln in offenders
            )
            + "\nReplace with the bare command (e.g., `uv run python`)"
            " assuming the tool is on the operator's PATH."
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
