"""Tests for the E14_S11 Langfuse orchestrator-side tracing doc.

Coverage matrix:

- TestDocExists
    docs/observability/langfuse-orchestrator.md is present.
- TestDocStructure
    Required sections present (caller-side disclaimer, session-id
    note, snippet, gotchas).
- TestSnippetLengthBounded
    Python snippet is < 60 LOC per the brief acceptance criterion.
- TestNoServerSideAnthropic
    server/ source still contains zero ``import anthropic`` (the doc
    is a caller-side reference, not a server change).
- TestSnippetSyntaxParses
    The Python snippet parses as syntactically valid Python (without
    executing it; langfuse/anthropic are not project deps).
- TestSnippetImportsCleanlySkipIf
    Skipped when langfuse + anthropic not installed (the brief's
    "doctest the Python snippet imports cleanly" requirement, gated
    to avoid forcing the deps into pyproject.toml).
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

    def test_doc_explains_session_id_emitted_per_mcp_spec(
        self, doc_text: str,
    ) -> None:
        """F1 closure (m10 adversary critique): the previous version
        of this test was based on the WRONG synthesis claim that
        arXMCP does not emit Mcp-Session-Id. In fact, per the MCP
        2025-06-18 spec, the upstream MCP library
        (StreamableHTTPSessionManager) emits the header on the
        initialize response. The shim at shim/arxmcp_shim.py:150
        proves this — it reads the header from response.getheader.

        The corrected doc must communicate: (1) the server DOES emit
        the header on initialize, (2) subsequent requests carry it
        back, (3) the orchestrator extracts from the initialize
        response."""
        flat = " ".join(doc_text.split())
        # Positive: doc references the spec emission.
        assert "emits `Mcp-Session-Id` as a response header" in flat, (
            "Doc must state that the server emits Mcp-Session-Id on "
            "initialize per the MCP 2025-06-18 spec (F1 closure)"
        )
        # Negative: the old wrong claim must NOT appear.
        assert "does **NOT** emit" not in flat, (
            "Doc still contains the wrong 'does NOT emit' claim; F1 "
            "closure replaced this with the accurate per-MCP-spec wording"
        )

    def test_snippet_does_not_hardcode_obsolete_model_id(
        self, snippet: str,
    ) -> None:
        """F4 closure (m10 adversary critique): the original snippet
        hardcoded ``model="claude-sonnet-4-5"`` — wrong version
        (canonical is ``claude-sonnet-4-6`` per MODEL_SONNET_4_6 in
        server/orchestrator/model_selector.py:88) AND violated the
        SSoT discipline the bundle's fixup commit was created to
        enforce. The snippet must not hardcode any literal
        ``claude-...`` model ID; reference model_selector.py instead.
        """
        import re

        bad = re.findall(r"['\"]claude-[a-z0-9-]+['\"]", snippet)
        assert not bad, (
            f"Snippet hardcodes Anthropic model IDs: {bad}. The "
            f"snippet must reference the orchestrator's pinned model "
            f"by symbol (or as a caller-supplied parameter without a "
            f"default literal), not embed the version string. See "
            f"server/orchestrator/model_selector.py for the SSoT."
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
        import anthropic  # noqa: F401
        import langfuse  # noqa: F401
    except ImportError:
        return False
    return True


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
