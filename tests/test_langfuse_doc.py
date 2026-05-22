"""Tests for the E14_S11 Langfuse orchestrator-side tracing doc.

Coverage matrix:

- TestDocExists                — docs/observability/langfuse-orchestrator.md is present
- TestDocStructure             — required sections present (caller-side disclaimer, session-id note, snippet, gotchas)
- TestSnippetLengthBounded     — Python snippet is < 60 LOC per the brief acceptance criterion
- TestNoServerSideAnthropic    — server/ source still contains zero `import anthropic` (the doc is a caller-side reference, not a server change)
- TestSnippetSyntaxParses      — the Python snippet parses as syntactically valid Python (without executing it; langfuse/anthropic are not project deps)
- TestSnippetImportsCleanlySkipIf — skipped when langfuse + anthropic not installed (the brief's "doctest the Python snippet imports cleanly" requirement, gated to avoid forcing the deps into pyproject.toml)
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
DOC_PATH: Path = (
    REPO_ROOT / "docs" / "observability" / "langfuse-orchestrator.md"
)
SERVER_DIR: Path = REPO_ROOT / "server"


def _extract_python_snippet(text: str) -> str:
    """Pull the first ```python``` fenced block from the markdown.

    There should be exactly one in this doc; if zero, raise so the
    structural test fails loudly. If more than one, take the first
    (the snippet) and ignore subsequent blocks (could be later
    examples added in revisions).
    """
    m = re.search(r"```python\n(.*?)```", text, re.DOTALL)
    if m is None:
        raise RuntimeError(
            "No ```python``` fenced code block found in the doc"
        )
    return m.group(1)


@pytest.fixture(scope="module")
def doc_text() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def snippet(doc_text: str) -> str:
    return _extract_python_snippet(doc_text)


# ---------------------------------------------------------------------------
# Existence + structure
# ---------------------------------------------------------------------------


class TestDocExists:
    def test_doc_present(self) -> None:
        assert DOC_PATH.is_file(), f"missing: {DOC_PATH}"


class TestDocStructure:
    @pytest.mark.parametrize(
        "required_phrase",
        [
            # CLAUDE.md §4.7: no anthropic SDK in server/ — the doc
            # MUST surface this caller-side disclaimer prominently.
            "runs OUTSIDE the arXMCP server process",
            # Brief: explicit pin to current Langfuse SDK major version.
            "langfuse>=4.0",
            # Brief: explicit pin to anthropic SDK major version.
            "anthropic>=0.40",
        ],
    )
    def test_required_phrase_present(
        self, doc_text: str, required_phrase: str,
    ) -> None:
        assert required_phrase in doc_text, (
            f"Doc missing required phrase: {required_phrase!r}"
        )

    def test_doc_clarifies_session_id_is_not_a_response_header(
        self, doc_text: str,
    ) -> None:
        """Synthesis A4 (load-bearing): the arXMCP server does NOT emit
        Mcp-Session-Id as a response header — it only consumes the
        client's request header. The doc must communicate this so the
        snippet doesn't try to extract the value from a response.

        Whitespace-tolerant check: collapse all whitespace runs (incl.
        line wraps) to single spaces before matching."""
        flat = " ".join(doc_text.split())
        assert (
            "does **NOT** emit `Mcp-Session-Id` as a response header"
            in flat
        ), (
            "Doc must explicitly state that arXMCP does NOT emit "
            "Mcp-Session-Id as a response header (synthesis A4)"
        )


# ---------------------------------------------------------------------------
# Snippet bounds + syntactic validity
# ---------------------------------------------------------------------------


class TestSnippetLengthBounded:
    def test_snippet_under_60_loc(self, snippet: str) -> None:
        """Brief acceptance criterion: '< 60 LOC working Python
        snippet'. Count non-blank, non-comment-only lines."""
        meaningful = [
            line for line in snippet.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        assert len(meaningful) < 60, (
            f"Snippet has {len(meaningful)} meaningful LOC; "
            f"brief acceptance is < 60"
        )


class TestSnippetSyntaxParses:
    def test_snippet_is_syntactically_valid_python(
        self, snippet: str,
    ) -> None:
        """ast.parse the snippet to verify Python syntax without
        importing langfuse / anthropic / mcp (none are project deps).
        Catches typos and pasted-from-blog mistakes."""
        try:
            ast.parse(snippet)
        except SyntaxError as e:
            pytest.fail(f"Snippet is not valid Python: {e}")


# ---------------------------------------------------------------------------
# Server-side anthropic SDK ban (CLAUDE.md §4.7)
# ---------------------------------------------------------------------------


class TestNoServerSideAnthropic:
    """The doc is a caller-side reference; adding it must NOT have
    introduced `import anthropic` (or `from anthropic`) anywhere in
    server/. This is a load-bearing constraint per CLAUDE.md §4.7
    and the project's no-LLM-at-runtime-inside-server posture.
    """

    def test_no_anthropic_import_in_server(self) -> None:
        result = subprocess.run(
            [
                "grep", "-rEn",
                r"^(from anthropic|import anthropic)",
                str(SERVER_DIR),
            ],
            capture_output=True, text=True, check=False,
        )
        # grep returncode: 0=match, 1=no match, 2=error. We want 1.
        assert result.returncode == 1, (
            f"server/ contains forbidden anthropic SDK import:\n"
            f"{result.stdout}\n"
            "Per CLAUDE.md §4.7: 'No anthropic SDK at runtime inside server/'. "
            "The S11 Langfuse doc is a caller-side reference — the "
            "anthropic dependency belongs in the orchestrator's "
            "codebase, not arXMCP."
        )


# ---------------------------------------------------------------------------
# Optional: import smoke test, skipped when deps not installed
# ---------------------------------------------------------------------------


def _has_langfuse_and_anthropic() -> bool:
    """Are both langfuse and anthropic installed in this venv?
    They're NOT pyproject deps; this is opt-in for orchestrator devs."""
    try:
        import langfuse  # noqa: F401
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


class TestSnippetImportsCleanlySkipIf:
    """The brief asks: 'doctest the Python snippet imports cleanly'.
    We achieve that with an exec-in-fake-namespace test gated on the
    optional dependencies being present. Skipped (not failed) when
    they aren't, so CI without the deps stays green."""

    @pytest.mark.skipif(
        not _has_langfuse_and_anthropic(),
        reason="langfuse+anthropic not installed (orchestrator-only deps)",
    )
    def test_snippet_imports_succeed(self, snippet: str) -> None:
        """Exec the snippet in an isolated namespace — verifies
        every import statement resolves. We do NOT call any of the
        defined functions (would require live credentials)."""
        compile(snippet, str(DOC_PATH), "exec")
        # Execute the top-level imports + function definitions; no
        # function calls (no live API hits).
        ns: dict[str, object] = {}
        exec(snippet, ns)  # noqa: S102  (controlled test snippet)
