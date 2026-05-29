"""notebook-surface-expansion-m5 — static MCP initialize.instructions hint.

Covers ``server/mcp_instructions.py::ARXMCP_INSTRUCTIONS`` and its wiring into the
FastMCP construction (``server/main.py``). The load-bearing assertion is that
setting ``instructions=`` leaves the frozen ``tools/list`` SHA-256 and BP1 hash
byte-identical (spike-1 proved this; this pins it). The instructions string itself
is hash-pinned so any edit is intentional + re-pinned.
"""

from __future__ import annotations

import asyncio
import hashlib

from mcp.server.fastmcp import FastMCP

from server.mcp_instructions import ARXMCP_INSTRUCTIONS
from server.tools import register_all
from tests.test_server_tool_schema import (
    EXPECTED_TOOL_SCHEMA_SHA256,
    compute_tool_schema_hash,
)

#: Pinned SHA-256 of ``ARXMCP_INSTRUCTIONS`` (UTF-8). Intentional-drift discipline,
#: mirroring ``EXPECTED_TOOL_SCHEMA_SHA256``: editing the instructions string is a
#: conscious act — re-pin this literal to the value the failing test prints.
EXPECTED_INSTRUCTIONS_SHA256: str = (  # UPDATE-ANCHOR — do not delete
    "d1cbd98edf8f8e3b0ffbdec861f313d985649efea0558460b3d5771c1969e6ef"
)

#: The 8 live tool names (server/tools.py::ALL_TOOLS); the instructions string
#: must name each so a connecting agent's orientation can't silently go stale.
_TOOL_NAMES: tuple[str, ...] = (
    "search_papers",
    "get_chunk",
    "find_equation",
    "get_definitions",
    "find_lemma_by_name",
    "get_paper",
    "cite_neighbors",
    "lean_verify",
)


class TestInstructionsConstant:
    def test_instructions_hash_matches_pin(self) -> None:
        """Intentional-drift guard: if ARXMCP_INSTRUCTIONS changes, re-pin
        EXPECTED_INSTRUCTIONS_SHA256 to the value printed below."""
        actual = hashlib.sha256(ARXMCP_INSTRUCTIONS.encode("utf-8")).hexdigest()
        assert actual == EXPECTED_INSTRUCTIONS_SHA256, (
            f"ARXMCP_INSTRUCTIONS drifted. Expected "
            f"{EXPECTED_INSTRUCTIONS_SHA256!r}, got {actual!r}. If the edit was "
            f"intentional, re-pin EXPECTED_INSTRUCTIONS_SHA256 to {actual!r}."
        )

    def test_all_tool_names_present(self) -> None:
        """m5 (brief-2 FM-e): the orientation must name every live tool, so a
        tool-surface change forces a conscious instructions update."""
        for name in _TOOL_NAMES:
            assert name in ARXMCP_INSTRUCTIONS, f"missing tool name: {name}"

    def test_length_bounded(self) -> None:
        """Anti-bloat (brief-2 FM-f): the hint rides every initialize handshake."""
        assert len(ARXMCP_INSTRUCTIONS) <= 800

    def test_content_safety_no_host_paths_or_secrets(self) -> None:
        """Content-safety: the unauthenticated initialize handshake is public —
        no absolute host paths, non-loopback binds, or obvious secret markers."""
        lowered = ARXMCP_INSTRUCTIONS.lower()
        assert "/users/" not in lowered
        assert "/var/" not in lowered
        assert "0.0.0.0" not in ARXMCP_INSTRUCTIONS
        assert "api_key" not in lowered
        assert "secret" not in lowered

    def test_not_the_system_prompt(self) -> None:
        """The instructions hint is distinct from server.prompts.SYSTEM_PROMPT
        (different surfaces) — confirm they are not the same object/text."""
        from server.prompts import SYSTEM_PROMPT

        assert ARXMCP_INSTRUCTIONS != SYSTEM_PROMPT


class TestInstructionsWiring:
    def test_instructions_threaded_into_fastmcp(self) -> None:
        """The constructor kwarg flows to the live server's instructions attr
        (which FastMCP places in the MCP initialize response)."""
        mcp = FastMCP(
            "arxmcp", json_response=True, instructions=ARXMCP_INSTRUCTIONS
        )
        assert mcp.instructions == ARXMCP_INSTRUCTIONS


class TestByteStability:
    def test_instructions_do_not_drift_tools_hash(self) -> None:
        """THE load-bearing guard: setting instructions= leaves the tools/list
        SHA-256 byte-identical to the pinned baseline (two-server comparison,
        mirroring spike-1). If this fails, instructions leaked into the tool
        surface — fix the leak, do NOT re-pin."""
        base = FastMCP("arxmcp", json_response=True)
        register_all(base)
        treat = FastMCP(
            "arxmcp", json_response=True, instructions=ARXMCP_INSTRUCTIONS
        )
        register_all(treat)
        base_hash = compute_tool_schema_hash(asyncio.run(base.list_tools()))
        treat_hash = compute_tool_schema_hash(asyncio.run(treat.list_tools()))
        assert base_hash == treat_hash == EXPECTED_TOOL_SCHEMA_SHA256
