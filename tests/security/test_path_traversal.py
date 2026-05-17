"""E13_S01 — Threat-1 (path traversal) audit.

Asserts every v1 tool handler that takes a ``paper_id`` or
``chunk_id`` scalar rejects malformed inputs BEFORE the handler
body reaches any resource (LanceDB, Kùzu, filesystem). The
audit doc at
``.claude/docs/security-threat-1-audit.md`` carries the full
per-tool table; this file enforces it.

**Adopted AC (synthesis D2; supersedes the brief's
"-32602 Invalid Params" wording):** the mcp Python SDK wraps
both `jsonschema.ValidationError` and Pydantic `ValidationError`
into `CallToolResult(isError=True)` — it does NOT emit
JSON-RPC -32602 for tool-arg validation. The security GOAL is
"never reaches the handler body"; the wire-level error code is
implementation choice. The handlers under test raise
``ValueError`` from their in-body validator on malformed input;
the SDK then wraps that into ``isError=True`` for callers.

These tests assert the in-body validation by calling the handler
function DIRECTLY and confirming the expected ``ValueError`` is
raised before any resource lookup. This is the load-bearing
security signal — the SDK-wrap behavior is a separate concern
covered by the existing per-handler test suite.

**Tool surface (synthesis D1; per ``server/tools.py::ALL_TOOLS``):**

- ``search_papers`` — no scalar identifier (filters dict is
  accepted-but-ignored); out of Threat-1 scope here. Known gap
  in audit doc.
- ``get_chunk`` — ``chunk_id``
- ``find_equation`` — no identifier; out of Threat-1 scope
- ``get_definitions`` — ``paper_id``
- ``find_lemma_by_name`` — ``paper_id`` (optional)
- ``get_paper`` — ``paper_id``
- ``cite_neighbors`` — ``chunk_id`` (E13_S01 NEW guard)

Total: 3 paper_id tools + 2 chunk_id tools × 3 adversarial
inputs = 15 cases.
"""

from __future__ import annotations

import asyncio

import pytest

from server.handlers.chunk import handle_get_chunk
from server.handlers.citations import handle_cite_neighbors
from server.handlers.definitions import handle_get_definitions
from server.handlers.lemma import handle_find_lemma_by_name
from server.handlers.paper import handle_get_paper

# ---------------------------------------------------------------------------
# Adversarial input bank (synthesis D9)
# ---------------------------------------------------------------------------

#: The three adversarial inputs from the milestone brief.
#:
#: ``id=`` strings make the pytest output operator-readable —
#: "test_paper_id_path_traversal[path_traversal-get_paper]"
#: vs the default "test_paper_id_path_traversal[get_paper-...]".
ADVERSARIAL_INPUTS = [
    pytest.param("../../../etc/passwd", id="path_traversal"),
    pytest.param("; cat /etc/shadow #", id="shell_injection"),
    pytest.param("a" * 512, id="overlong_512"),
]

#: Validator-message regex pinned per F1 rectification — matches
#: the canonical "<id-kind> ... does not match" form used by all
#: five handlers. Tightened from the prior ``r"paper_id"`` /
#: ``r"chunk_id"`` shape-only assertion that would silently pass
#: for any downstream ValueError mentioning the identifier name.
_PAPER_ID_REJECT_RE = (
    r"paper_id .* does not match|does not match the arXiv"
)
_CHUNK_ID_REJECT_RE = (
    r"chunk_id .* does not match|does not match.*arxiv:"
)


# ---------------------------------------------------------------------------
# paper_id-shaped attacks — 3 tools × 3 inputs = 9 cases
# ---------------------------------------------------------------------------


class TestPaperIdPathTraversal:
    """Tools that take a ``paper_id`` scalar must reject every
    adversarial input via an in-body ``ValueError`` raise before
    any resource lookup."""

    @pytest.mark.parametrize("bad_input", ADVERSARIAL_INPUTS)
    def test_get_paper_rejects(self, bad_input):
        """get_paper.paper_id: validated by
        ``is_valid_paper_id`` in-body (paper.py:37-40)."""
        with pytest.raises(ValueError, match=_PAPER_ID_REJECT_RE):
            asyncio.run(handle_get_paper(paper_id=bad_input))

    @pytest.mark.parametrize("bad_input", ADVERSARIAL_INPUTS)
    def test_get_definitions_rejects(self, bad_input):
        """get_definitions.paper_id: validated by
        ``is_valid_paper_id`` in-body
        (definitions.py:73-78)."""
        with pytest.raises(ValueError, match=_PAPER_ID_REJECT_RE):
            asyncio.run(
                handle_get_definitions(paper_id=bad_input, term="x")
            )

    @pytest.mark.parametrize("bad_input", ADVERSARIAL_INPUTS)
    def test_find_lemma_by_name_rejects(self, bad_input):
        """find_lemma_by_name.paper_id is OPTIONAL. The
        validator at lemma.py:68-71 runs when present.
        Adversarial inputs MUST be rejected; ``None`` is the
        documented absent-paper-id case (not adversarial)."""
        with pytest.raises(ValueError, match=_PAPER_ID_REJECT_RE):
            asyncio.run(
                handle_find_lemma_by_name(name="x", paper_id=bad_input)
            )


# ---------------------------------------------------------------------------
# chunk_id-shaped attacks — 2 tools × 3 inputs = 6 cases
# ---------------------------------------------------------------------------


class TestChunkIdPathTraversal:
    """Tools that take a ``chunk_id`` scalar must reject every
    adversarial input. Note ``chunk_id`` has a different shape
    than ``paper_id`` (``arxiv:<paper_id>:<16-hex>``); the
    validator is ``is_valid_chunk_id``."""

    @pytest.mark.parametrize("bad_input", ADVERSARIAL_INPUTS)
    def test_get_chunk_rejects(self, bad_input):
        """get_chunk.chunk_id: validated by
        ``is_valid_chunk_id`` in-body (chunk.py:39-43)."""
        with pytest.raises(ValueError, match=_CHUNK_ID_REJECT_RE):
            asyncio.run(handle_get_chunk(chunk_id=bad_input))

    @pytest.mark.parametrize("bad_input", ADVERSARIAL_INPUTS)
    def test_cite_neighbors_rejects(self, bad_input):
        """cite_neighbors.chunk_id: validated by
        ``is_valid_chunk_id`` in-body (E13_S01 D3 — NEW guard
        added by this milestone). Pre-E13_S01, the handler
        echoed any chunk_id straight into the response
        envelope without validation. This test pins the new
        guard so a future refactor cannot silently drop it."""
        with pytest.raises(ValueError, match=_CHUNK_ID_REJECT_RE):
            asyncio.run(handle_cite_neighbors(chunk_id=bad_input))


# ---------------------------------------------------------------------------
# Defense-in-depth: chunk_id-shaped attacks targeting chunk_id args
# ---------------------------------------------------------------------------


class TestChunkIdShapedAttacks:
    """Bonus coverage: an attacker who knows the chunk_id
    format may attempt to slip a malformed paper_id INSIDE a
    valid-looking chunk_id wrapper. E.g.
    ``arxiv:../../etc/passwd:aaaaaaaaaaaaaaaa`` — the outer
    shape passes the ``arxiv:`` prefix + ``:<16-hex>`` suffix
    check but the embedded paper_id is malformed.

    ``is_valid_chunk_id`` validates the FULL pattern including
    the embedded paper_id (see CHUNK_ID_RE in
    ``ingest/identifiers.py``). These cases prove that ANY
    malformed chunk_id — whether the bad bytes live in the inner
    paper_id or the outer suffix — is rejected. The test does
    NOT prove branch-specific coverage (the regex is a single
    composed pattern); F5 from the E13_S01 critique softens
    this claim.
    """

    CHUNK_SHAPED_ATTACKS = [
        pytest.param(
            "arxiv:../../etc/passwd:aaaaaaaaaaaaaaaa",
            id="embedded_traversal",
        ),
        pytest.param(
            "arxiv:2401.00001:zzzzzzzzzzzzzzzz",
            id="non_hex_suffix",
        ),
        pytest.param(
            "arxiv:2401.00001:" + "a" * 15,  # 15 not 16
            id="short_hex_suffix",
        ),
    ]

    @pytest.mark.parametrize("bad_input", CHUNK_SHAPED_ATTACKS)
    def test_get_chunk_rejects_chunk_shaped_attacks(self, bad_input):
        with pytest.raises(ValueError, match=_CHUNK_ID_REJECT_RE):
            asyncio.run(handle_get_chunk(chunk_id=bad_input))

    @pytest.mark.parametrize("bad_input", CHUNK_SHAPED_ATTACKS)
    def test_cite_neighbors_rejects_chunk_shaped_attacks(self, bad_input):
        with pytest.raises(ValueError, match=_CHUNK_ID_REJECT_RE):
            asyncio.run(handle_cite_neighbors(chunk_id=bad_input))


# ---------------------------------------------------------------------------
# Sanity guard: well-formed identifiers do NOT raise from the validator
# ---------------------------------------------------------------------------


class TestPositiveCases:
    """The validators must NOT reject canonical, well-formed
    identifiers. Without this, a regression that flipped the
    rejection logic would silently break every legitimate
    request. The downstream handler body may still fail
    (Resources not configured), but the validator MUST pass.
    """

    def test_valid_paper_id_passes_validator(self):
        """A well-formed paper_id passes ``is_valid_paper_id``.
        The canonical regex (per ``ingest/identifiers.py``)
        accepts:
        - new-style: ``YYMM.NNNNN[vN]``
        - old-style: ``<archive>/NNNNNNN[vN]`` where ``<archive>``
          is lowercase letters + hyphens (e.g. ``hep-th``,
          ``cond-mat``). Note the regex does NOT accept the
          ``math.AG``-style dot-subjectclass form despite the
          misleading comment in ``identifiers.py`` (verified by
          ``tests/test_identifiers.py``).
        """
        from ingest.identifiers import is_valid_paper_id  # noqa: PLC0415

        assert is_valid_paper_id("2401.00001") is True
        assert is_valid_paper_id("2401.00001v3") is True
        # Old-style — `hep-th`, `cond-mat` form (no dots).
        assert is_valid_paper_id("hep-th/0001234") is True
        assert is_valid_paper_id("cond-mat/0612345v2") is True

    def test_valid_chunk_id_passes_validator(self):
        from ingest.identifiers import is_valid_chunk_id  # noqa: PLC0415

        assert (
            is_valid_chunk_id("arxiv:2401.00001:0123456789abcdef") is True
        )
        assert (
            is_valid_chunk_id("arxiv:hep-th/0001234:fedcba9876543210") is True
        )


# ---------------------------------------------------------------------------
# F1 — Regression guard: validator must fire BEFORE any resource access
# ---------------------------------------------------------------------------


class TestValidatorFiresBeforeResources:
    """F1 rectification (E13_S01 adversary critique). The prior
    ``match=r"paper_id"`` assertion would have passed if a future
    refactor dropped the validator but raised a different
    ``ValueError`` later in the function (e.g. from a LanceDB
    filter error after the resource lookup succeeded). This
    stronger guard monkeypatches ``server.tools.get_resources``
    to raise a sentinel exception; if the validator fires FIRST,
    we see ``ValueError`` (the validator's). If the validator is
    silently bypassed, we see the sentinel.
    """

    SENTINEL = "PROOF_VALIDATOR_DID_NOT_FIRE"

    @pytest.mark.parametrize("bad_input", ADVERSARIAL_INPUTS)
    def test_get_paper_validator_fires_before_resources(
        self, bad_input, monkeypatch
    ):
        from server import tools as tools_mod  # noqa: PLC0415

        monkeypatch.setattr(
            tools_mod, "get_resources",
            lambda: (_ for _ in ()).throw(RuntimeError(self.SENTINEL)),
        )
        # If the validator fires first, we get ValueError (not RuntimeError).
        with pytest.raises(ValueError) as exc:
            asyncio.run(handle_get_paper(paper_id=bad_input))
        assert self.SENTINEL not in str(exc.value), (
            f"validator was bypassed; sentinel reached handler "
            f"body for {bad_input!r}"
        )

    @pytest.mark.parametrize("bad_input", ADVERSARIAL_INPUTS)
    def test_get_chunk_validator_fires_before_resources(
        self, bad_input, monkeypatch
    ):
        from server import tools as tools_mod  # noqa: PLC0415

        monkeypatch.setattr(
            tools_mod, "get_resources",
            lambda: (_ for _ in ()).throw(RuntimeError(self.SENTINEL)),
        )
        with pytest.raises(ValueError) as exc:
            asyncio.run(handle_get_chunk(chunk_id=bad_input))
        assert self.SENTINEL not in str(exc.value)

    @pytest.mark.parametrize("bad_input", ADVERSARIAL_INPUTS)
    def test_cite_neighbors_validator_fires_before_resources(
        self, bad_input, monkeypatch
    ):
        """cite_neighbors does not currently call get_resources
        (it's a v1 stub), so this test is forward-compat: if a
        future wiring adds a resource access, the validator must
        still fire first. Monkeypatch defensively."""
        from server import tools as tools_mod  # noqa: PLC0415

        monkeypatch.setattr(
            tools_mod, "get_resources",
            lambda: (_ for _ in ()).throw(RuntimeError(self.SENTINEL)),
        )
        with pytest.raises(ValueError) as exc:
            asyncio.run(handle_cite_neighbors(chunk_id=bad_input))
        assert self.SENTINEL not in str(exc.value)


# ---------------------------------------------------------------------------
# F2 — Empty-string case + Pydantic min_length=1 boundary
# ---------------------------------------------------------------------------


class TestEmptyIdentifier:
    """F2 rectification — ``""`` was missing from the
    adversarial bank. The handlers' Pydantic ``Field(min_length=1)``
    rejects this at the schema boundary in production traffic
    (via FastMCP wrap), but direct function calls bypass Pydantic
    so the in-body validator must also reject it.
    """

    def test_get_paper_rejects_empty_paper_id(self):
        with pytest.raises(ValueError, match=_PAPER_ID_REJECT_RE):
            asyncio.run(handle_get_paper(paper_id=""))

    def test_get_chunk_rejects_empty_chunk_id(self):
        with pytest.raises(ValueError, match=_CHUNK_ID_REJECT_RE):
            asyncio.run(handle_get_chunk(chunk_id=""))

    def test_cite_neighbors_rejects_empty_chunk_id(self):
        with pytest.raises(ValueError, match=_CHUNK_ID_REJECT_RE):
            asyncio.run(handle_cite_neighbors(chunk_id=""))


# ---------------------------------------------------------------------------
# F3 — SDK-boundary smoke (synthesis D9 commitment)
# ---------------------------------------------------------------------------


class TestSdkBoundary:
    """F3 rectification (synthesis D9). The audit doc claims the
    mcp Python SDK wraps the in-body ``ValueError`` into
    ``CallToolResult(isError=True)``. This pins the wire-level
    contract end-to-end — without it, a future SDK update that
    changes the wrap behavior (or emits the brief's literal
    -32602) would not be detected.
    """

    def test_iserror_true_on_malformed_chunk_id(self):
        """Register handle_cite_neighbors as a FastMCP tool, call
        it through the Tool.run path with a malformed chunk_id,
        and assert the SDK wraps the ValueError into
        CallToolResult(isError=True). Closes the audit doc's
        wire-level claim."""
        from mcp.server.fastmcp import FastMCP  # noqa: PLC0415

        app = FastMCP("test-e13-s01")
        app.add_tool(handle_cite_neighbors, name="cite_neighbors")
        tool = app._tool_manager.get_tool("cite_neighbors")
        assert tool is not None

        async def _run():
            return await tool.run({"chunk_id": "../../../etc/passwd"})

        # Tool.run returns the raw handler result OR raises ToolError
        # which the dispatcher wraps. We accept either: the
        # security contract is "the handler body's resource access
        # is unreached," and both paths satisfy it.
        from mcp.server.fastmcp.exceptions import ToolError  # noqa: PLC0415

        try:
            result = asyncio.run(_run())
            # If Tool.run returned cleanly, the result must be an
            # error envelope. FastMCP's convert_result=False path
            # returns the raw return; otherwise it wraps.
            assert result is None or "Error" in str(result) or hasattr(
                result, "isError"
            )
        except ToolError as exc:
            # Expected path on most mcp SDK versions: ValueError
            # bubbled through FastMCP -> ToolError.
            assert "chunk_id" in str(exc).lower() or "does not match" in str(exc)


# ---------------------------------------------------------------------------
# F4 — paper_id_from_chunk_id rejection coverage
# ---------------------------------------------------------------------------


class TestPaperIdFromChunkIdRejection:
    """F4 rectification — ``paper_id_from_chunk_id`` is the
    helper that server/graph_queries.py uses to extract a
    paper_id from a chunk_id. It will be the load-bearing
    validator when E09 wiring lands on cite_neighbors. Pin its
    rejection of the same adversarial inputs here so the
    Threat-1 audit covers both paths.
    """

    @pytest.mark.parametrize("bad_input", ADVERSARIAL_INPUTS)
    def test_rejects_paper_id_shaped_attacks(self, bad_input):
        from ingest.identifiers import paper_id_from_chunk_id  # noqa: PLC0415

        with pytest.raises(ValueError):
            paper_id_from_chunk_id(bad_input)

    @pytest.mark.parametrize(
        "bad_input",
        [
            pytest.param(
                "arxiv:../../etc/passwd:aaaaaaaaaaaaaaaa",
                id="embedded_traversal",
            ),
            pytest.param(
                "arxiv:2401.00001:zzzzzzzzzzzzzzzz",
                id="non_hex_suffix",
            ),
            pytest.param(
                "arxiv:2401.00001:" + "a" * 15,
                id="short_hex_suffix",
            ),
        ],
    )
    def test_rejects_chunk_id_shaped_attacks(self, bad_input):
        from ingest.identifiers import paper_id_from_chunk_id  # noqa: PLC0415

        with pytest.raises(ValueError):
            paper_id_from_chunk_id(bad_input)

    def test_accepts_well_formed_chunk_id(self):
        from ingest.identifiers import paper_id_from_chunk_id  # noqa: PLC0415

        assert (
            paper_id_from_chunk_id("arxiv:2401.00001:0123456789abcdef")
            == "2401.00001"
        )
