"""Tool-schema byte-stability test (E06_S06).

A sub-agent's prompt cache (BP1 = system prompt + ``tools`` array)
gets blown the moment any byte of the ``tools/list`` response
changes — see `.claude/notes/07-multi-agent-caching.md` lines 40-49:

    Property 1: Tool definitions are byte-stable

    Pin tool JSON schemas. Sort properties alphabetically at
    serialization time. Freeze descriptions as constants in source.
    A casual edit to a tool description blows every sub-agent's
    cache.

    Implementation: a single ``tools.py`` module with frozen
    dataclasses + a unit test that asserts
    ``sha256(serialize_tools()) == EXPECTED_HASH``. Bump the hash
    deliberately when intentionally changing schema; treat as an
    API version bump.

This file IS that unit test. The hash is :data:`EXPECTED_TOOL_SCHEMA_SHA256`.
A drift means: either you intentionally changed a tool name /
description / argument schema (in which case bump
``server.tools.TOOL_SCHEMA_VERSION`` AND run ``pytest
--update-tool-schema-hash`` to refresh the constant below), or you
made an accidental edit that just nuked every sub-agent's cached
prefix (in which case revert).

**Update procedure** (single source of truth — also in the
docstring of :func:`compute_tool_schema_hash`):

    pytest tests/test_server_tool_schema.py --update-tool-schema-hash

The flag is registered by ``tests/conftest.py``. When set, the
test computes the live hash and rewrites the
:data:`EXPECTED_TOOL_SCHEMA_SHA256` literal in this file in place,
then passes trivially. CI never sets the flag.

**What goes into the hash.** The wire-equivalent JSON of the
``tools/list`` response, computed as:

    payload = {"tools": [t.model_dump(mode="json", by_alias=True,
                                       exclude_none=True)
                          for t in tools]}
    canonical = json.dumps(payload, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=True)
    sha256(canonical.encode("utf-8")).hexdigest()

- ``by_alias=True``: the per-tool ``meta`` field aliases to the
  spec-blessed ``_meta`` wire form. Without this the hash captures
  ``"meta"`` (Python attr) instead of ``"_meta"`` (wire form) and
  drifts when downstream clients touch the wire bytes.
- ``exclude_none=True``: strips nullable noise (``outputSchema``,
  ``annotations``, ``icons``, ``title`` when unset). Without this
  the hash is sensitive to MCP SDK-version bumps that flip
  default-None to default-empty-dict, which has nothing to do with
  our schema.
- ``sort_keys=True`` + ``separators=(",", ":")``: the canonical
  json form. No whitespace, alphabetically sorted keys.
- ``ensure_ascii=True``: any non-ASCII char in a future tool
  description renders as ``\\uXXXX`` rather than raw UTF-8 bytes —
  pinned across Python versions and platforms.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

from server.config import Config
from server.health import reset_metrics_for_tests
from server.main import create_app
from server.tools import ALL_TOOLS, TOOL_SCHEMA_VERSION, reset_resources_for_tests

# ---------------------------------------------------------------------------
# Pinned hash (the load-bearing constant)
# ---------------------------------------------------------------------------

#: SHA-256 of the canonical JSON of the ``tools/list`` response,
#: computed by :func:`compute_tool_schema_hash`. Update procedure:
#: ``pytest tests/test_server_tool_schema.py --update-tool-schema-hash``.
#:
#: A drift here means a contributor changed a tool name, description,
#: argument schema, or the per-tool ``_meta`` shape — all of which
#: invalidate every sub-agent's BP1 prompt cache. The drift is
#: intentional only when paired with a ``TOOL_SCHEMA_VERSION`` bump.
EXPECTED_TOOL_SCHEMA_SHA256: str = (  # UPDATE-ANCHOR — do not delete
    "4623e8988f8346da38eaa882303da7a4ef5a4c9a6c13211d867a04c50018fd41"
)


# ---------------------------------------------------------------------------
# Fixtures (mirror the pattern in tests/test_tools_all.py to avoid
# cross-import F811 on shared fixture names)
# ---------------------------------------------------------------------------


def _seed_minimal_corpus(lancedb_path: Path) -> None:
    """Seed a 1-chunk corpus so ``Resources.startup`` has a valid
    ``corpus-version.json`` marker. The actual chunk content does
    not matter — the hash is computed over schema bytes, not data."""
    import numpy as np

    from ingest.chunker_types import CHUNKER_VERSION, ChunkRecord
    from ingest.embedder import EMBEDDER_VERSION, EMBEDDING_DIM
    from ingest.schema import EmbedRecord
    from ingest.store import write_chunks

    chunks = [
        ChunkRecord(
            chunk_id=f"arxiv:2307.00001:{'0' * 16}",
            paper_id="2307.00001",
            kind="stmt",
            section_path=[],
            theorem_name=None,
            theorem_label=None,
            body_text="seed",
            body_tokens="seed",
            preamble_ref=None,
            chunker_version=CHUNKER_VERSION,
        )
    ]
    rng = np.random.default_rng(0)
    v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
    v /= np.linalg.norm(v)
    embeddings = EmbedRecord(
        chunk_ids_stmt=[c.chunk_id for c in chunks],
        embedding_stmt=np.stack([v], axis=0),
        chunk_ids_proof=[],
        embedding_proof=np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
        embedder_version=EMBEDDER_VERSION,
    )
    write_chunks(chunks, embeddings, lancedb_path=lancedb_path)


@pytest.fixture
def _mocked_bge(monkeypatch):
    """Replace BGE-M3 model + tokenizer load with no-ops."""
    import server.query_encoder as qe_mod

    monkeypatch.setattr(qe_mod, "_get_model", lambda: object())
    monkeypatch.setattr(qe_mod, "_get_tokenizer", lambda: object())
    yield


@pytest.fixture
def _live_tools(tmp_path, _mocked_bge) -> list[Any]:
    """Construct the live FastMCP server and return its registered
    tools as a list of ``mcp.types.Tool`` objects.

    Does NOT enter the TestClient lifespan — ``list_tools`` queries
    the in-memory tool registry that ``register_all`` populates at
    ``create_app`` time, so we don't need warm Resources. This makes
    the test fast (~30 ms) and decoupled from the BGE-M3 download
    path."""
    lancedb_path = tmp_path / "lancedb"
    _seed_minimal_corpus(lancedb_path)
    cfg = Config(lancedb_path=lancedb_path)
    reset_resources_for_tests()
    reset_metrics_for_tests()
    app = create_app(cfg)
    return asyncio.run(app.state.mcp_server.list_tools())


# ---------------------------------------------------------------------------
# Hash computation (pure function — testable in isolation)
# ---------------------------------------------------------------------------


def _serialize_tools(tools: list[Any]) -> str:
    """Render the wire-equivalent ``tools/list`` JSON in canonical form.

    Returns the canonical JSON string (UTF-8, no whitespace,
    alphabetically sorted keys, ``\\uXXXX`` for non-ASCII). The
    return value is deterministic across Python versions and
    platforms — see module docstring for the field-by-field
    rationale.
    """
    payload = {
        "tools": [
            t.model_dump(mode="json", by_alias=True, exclude_none=True)
            for t in tools
        ]
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def compute_tool_schema_hash(tools: list[Any]) -> str:
    """Return the SHA-256 hex digest of the canonical
    ``tools/list`` JSON.

    See :data:`EXPECTED_TOOL_SCHEMA_SHA256` for the pinned value.
    See module docstring for the update procedure.
    """
    canonical = _serialize_tools(tools)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# In-place hash rewrite (for the --update-tool-schema-hash flag)
# ---------------------------------------------------------------------------


_PINNED_HASH_PATTERN = re.compile(
    # Anchor on the UPDATE-ANCHOR sentinel comment so this pattern
    # never accidentally matches another 64-hex literal in the file.
    r'(EXPECTED_TOOL_SCHEMA_SHA256:\s*str\s*=\s*\(\s*'
    r'#\s*UPDATE-ANCHOR\s*[^\n]*\n\s*")[0-9a-f]{64}("\s*\))',
)


def _rewrite_pinned_hash(new_hash: str) -> bool:
    """Rewrite :data:`EXPECTED_TOOL_SCHEMA_SHA256` in this file to
    ``new_hash``. Returns True if the file was modified, False if
    the hash was already up to date.

    Anchors on the ``# UPDATE-ANCHOR`` sentinel so the rewrite is
    idempotent and cannot accidentally clobber another 64-hex
    literal in the file."""
    path = Path(__file__).resolve()
    text = path.read_text(encoding="utf-8")
    match = _PINNED_HASH_PATTERN.search(text)
    if match is None:
        raise RuntimeError(
            "could not find the UPDATE-ANCHOR pattern in "
            f"{path} — has the file structure drifted?"
        )
    current = text[match.start() + len(match.group(1)) : match.end() - len(match.group(2))]
    if current == new_hash:
        return False
    new_text = (
        text[: match.start()]
        + match.group(1)
        + new_hash
        + match.group(2)
        + text[match.end() :]
    )
    path.write_text(new_text, encoding="utf-8")
    return True


# ===========================================================================
# AC #1 — pytest passes with the pinned hash
# AC #2 — changing a tool description causes the test to fail (TestUpdateProcedure)
# AC #3 — --update-tool-schema-hash regenerates the pinned constant
# AC #4 — tool_schema_version: 1 appears in the tools/list response (per-tool _meta)
# ===========================================================================


class TestPinnedHash:
    """Brief AC #1: pytest passes with the pinned hash.

    The single load-bearing assertion of this milestone. A failure
    means a tool schema byte changed since the pin was last updated.
    See module docstring for the update procedure.
    """

    def test_live_tools_match_pinned_hash(self, _live_tools, request):
        """Compute the live hash; if equal to the pinned constant,
        pass. If the user passed ``--update-tool-schema-hash``,
        rewrite the constant in place and pass.

        The flag is registered in ``tests/conftest.py``."""
        live_hash = compute_tool_schema_hash(_live_tools)

        if request.config.getoption("--update-tool-schema-hash"):
            changed = _rewrite_pinned_hash(live_hash)
            if changed:
                pytest.skip(
                    f"updated EXPECTED_TOOL_SCHEMA_SHA256 to {live_hash}; "
                    f"re-run pytest WITHOUT --update-tool-schema-hash to "
                    f"verify the new hash is stable."
                )
            # No change — fall through to the normal assertion.

        assert live_hash == EXPECTED_TOOL_SCHEMA_SHA256, (
            f"\n\nTool schema bytes drifted.\n"
            f"  expected: {EXPECTED_TOOL_SCHEMA_SHA256}\n"
            f"  actual:   {live_hash}\n\n"
            f"This means a tool name, description, argument schema, or "
            f"per-tool _meta shape changed since the pin was last "
            f"updated. A drift INVALIDATES the BP1 prompt cache for "
            f"every sub-agent (see .claude/notes/07-multi-agent-"
            f"caching.md lines 40-49).\n\n"
            f"To accept the drift (intentional schema change):\n"
            f"  1. Bump server.tools.TOOL_SCHEMA_VERSION\n"
            f"  2. Run: pytest tests/test_server_tool_schema.py "
            f"--update-tool-schema-hash\n"
            f"  3. Commit the new pinned hash.\n"
        )


class TestSchemaVersionMetaSurface:
    """Brief AC #4: ``tool_schema_version: 1`` appears in the
    ``tools/list`` response.

    Per the E06_S03 design decision (research-brief-2 lines 235-245),
    ``tool_schema_version`` lives in per-tool ``_meta`` (the
    spec-blessed metadata slot) rather than as a top-level field.
    This class asserts the surface AND that it equals the module
    constant — closing the cross-check between the in-process
    constant and the wire bytes.
    """

    def test_per_tool_meta_carries_schema_version(self, _live_tools):
        """Every registered tool's wire ``_meta`` carries
        ``{"tool_schema_version": TOOL_SCHEMA_VERSION}``."""
        canonical = _serialize_tools(_live_tools)
        # The literal substring per the brief's wording. We assert
        # against the canonical JSON bytes (not the in-memory dict)
        # because the hash is computed from those bytes — drift in
        # how _meta serializes shows up here too.
        needle = f'"_meta":{{"tool_schema_version":{TOOL_SCHEMA_VERSION}}}'
        assert needle in canonical, (
            f"expected per-tool _meta substring {needle!r} in canonical "
            f"tools/list JSON; got bytes={canonical[:500]!r}..."
        )

    def test_meta_present_on_every_tool(self, _live_tools):
        """Per-tool ``_meta`` is set on every tool (defense in depth
        against a future refactor that drops the meta arg from
        register_all)."""
        for t in _live_tools:
            assert t.meta is not None, (
                f"tool {t.name!r} has no _meta; register_all must set "
                f"meta={{'tool_schema_version': TOOL_SCHEMA_VERSION}}"
            )
            assert t.meta.get("tool_schema_version") == TOOL_SCHEMA_VERSION


class TestUpdateProcedure:
    """Brief AC #2: changing a tool description causes the test to fail.

    Plus AC #3 indirectly: the rewrite helper is unit-tested in
    isolation here without recursively shelling out to pytest."""

    def test_changing_tool_description_changes_hash(
        self, _live_tools, monkeypatch
    ):
        """Replace one tool's description with a different string;
        recompute the hash; assert it differs from the pinned value.

        We monkeypatch via the registered ``Tool`` object's
        ``description`` attribute. The MCP ``Tool`` model is a
        pydantic ``BaseModel`` — we use ``model_copy(update=...)``
        to get a fresh instance with a tweaked description without
        mutating frozen state."""
        import copy

        # Build a parallel tool list with one description tweaked.
        tools = list(_live_tools)
        if not tools:
            pytest.skip("no tools registered")
        tweaked = copy.copy(tools[0])
        # Tool is a pydantic model; setattr works because it's not
        # frozen. Wrapped in model_copy for safety.
        tweaked = tweaked.model_copy(
            update={"description": "BUMP — not the real description"}
        )
        tools[0] = tweaked

        original_hash = compute_tool_schema_hash(_live_tools)
        bumped_hash = compute_tool_schema_hash(tools)
        assert bumped_hash != original_hash, (
            "tweaking a tool description did NOT change the hash — "
            "the description bytes are not flowing into the hash. "
            "Inspect _serialize_tools."
        )

    def test_rewrite_helper_idempotent_when_hash_unchanged(self, tmp_path):
        """Calling ``_rewrite_pinned_hash`` with the value CURRENTLY
        in the file returns False without modifying the file.

        We re-extract the current hash from the file (rather than
        using the imported ``EXPECTED_TOOL_SCHEMA_SHA256`` constant)
        because in a session that ran with ``--update-tool-schema-hash``
        before this test, the file has the fresh hash but the imported
        constant still points to whatever it was at module load time.
        Reading the file directly keeps the assertion meaningful in
        either order."""
        path = Path(__file__).resolve()
        original_text = path.read_text(encoding="utf-8")
        match = _PINNED_HASH_PATTERN.search(original_text)
        assert match is not None, "UPDATE-ANCHOR pattern missing"
        current_in_file = original_text[
            match.start() + len(match.group(1)) : match.end() - len(match.group(2))
        ]
        try:
            changed = _rewrite_pinned_hash(current_in_file)
            assert changed is False
            # File contents must be byte-identical.
            assert path.read_text(encoding="utf-8") == original_text
        finally:
            # Defensive: if the assertion failed mid-test, restore.
            if path.read_text(encoding="utf-8") != original_text:
                path.write_text(original_text, encoding="utf-8")

    def test_rewrite_helper_finds_anchor(self):
        """The UPDATE-ANCHOR sentinel pattern is present and
        unambiguous in this file."""
        path = Path(__file__).resolve()
        text = path.read_text(encoding="utf-8")
        matches = _PINNED_HASH_PATTERN.findall(text)
        assert len(matches) == 1, (
            f"expected exactly 1 UPDATE-ANCHOR match; found {len(matches)}"
        )

    def test_serialize_tools_is_canonical(self, _live_tools):
        """Two calls produce byte-identical output (no dict-order
        nondeterminism)."""
        a = _serialize_tools(_live_tools)
        b = _serialize_tools(_live_tools)
        assert a == b
        # Sanity: starts with {"tools":[ ...
        assert a.startswith('{"tools":['), (
            f"canonical form regressed; got prefix={a[:50]!r}"
        )
        # Sanity: ends with ]}
        assert a.endswith(']}')

    def test_tools_list_response_includes_all_seven(self, _live_tools):
        """The hash covers all 7 tools registered by the v1 brief.
        A drop to 6 (someone removed a tool) would silently lower
        the BP1 cache surface — assert the count explicitly."""
        assert len(_live_tools) == len(ALL_TOOLS) == 7
