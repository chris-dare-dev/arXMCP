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
#: intentional only when paired with a ``TOOL_SCHEMA_VERSION`` bump
#: (cross-checked by :data:`EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`
#: below — F2 fix from the E06_S06 critique).
EXPECTED_TOOL_SCHEMA_SHA256: str = (  # UPDATE-ANCHOR — do not delete
    "4623e8988f8346da38eaa882303da7a4ef5a4c9a6c13211d867a04c50018fd41"
)

#: The :data:`server.tools.TOOL_SCHEMA_VERSION` value that produced
#: :data:`EXPECTED_TOOL_SCHEMA_SHA256`. F2 fix from the E06_S06
#: critique: hash drift MUST imply a version bump. The
#: ``--update-tool-schema-hash`` flag refuses to proceed if the
#: hash has drifted but ``TOOL_SCHEMA_VERSION`` still equals this
#: pinned value — forcing the contributor to bump the version FIRST.
#:
#: Decorative-version risk closed: if a contributor bumps a tool
#: description without bumping ``TOOL_SCHEMA_VERSION``, the flag
#: refuses, and they cannot ship the new hash without also editing
#: ``server/tools.py``'s ``TOOL_SCHEMA_VERSION`` constant.
EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH: int = 1  # VERSION-ANCHOR — do not delete


# ---------------------------------------------------------------------------
# Fixtures (mirror the pattern in tests/test_tools_all.py to avoid
# cross-import F811 on shared fixture names)
# ---------------------------------------------------------------------------


@pytest.fixture
def _mocked_bge(monkeypatch):
    """Replace BGE-M3 model + tokenizer load with no-ops."""
    import server.query_encoder as qe_mod

    monkeypatch.setattr(qe_mod, "_get_model", lambda: object())
    monkeypatch.setattr(qe_mod, "_get_tokenizer", lambda: object())
    yield


def _build_app_and_list_tools(tmp_path: Path) -> list[Any]:
    """Construct ``create_app(cfg)`` and return its registered tools.

    F5 fix from the E06_S06 critique: NO corpus seed. ``list_tools``
    queries the in-memory tool registry populated by ``register_all``
    at ``create_app`` time; ``Resources.startup`` is never invoked
    because we don't enter the TestClient lifespan. So we don't need
    a corpus marker, numpy, or any ingest imports.

    Pointing ``lancedb_path`` at a non-existent directory is fine
    for the same reason — LanceDB is never opened."""
    cfg = Config(lancedb_path=tmp_path / "no_lancedb_needed")
    reset_resources_for_tests()
    reset_metrics_for_tests()
    app = create_app(cfg)
    return asyncio.run(app.state.mcp_server.list_tools())


@pytest.fixture
def _live_tools(tmp_path, _mocked_bge) -> list[Any]:
    """Construct the live FastMCP server and return its registered
    tools as a list of ``mcp.types.Tool`` objects."""
    return _build_app_and_list_tools(tmp_path)


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

    F6 fix from the E06_S06 critique: hash the FULL ``ListToolsResult``
    envelope, not just ``{"tools": [...]}``. When E07_S04 pagination
    lands and ``nextCursor`` becomes non-None, OR a future top-level
    ``_meta`` injection happens, the hash captures it — without
    requiring a separate test or schema bump for "the envelope".
    """
    from mcp.types import ListToolsResult

    result = ListToolsResult(tools=tools)
    payload = result.model_dump(mode="json", by_alias=True, exclude_none=True)
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
    # F8 fix: anchored to start-of-line via ``re.MULTILINE`` so a
    # docstring example or onboarding doc that uses the literal
    # ``EXPECTED_TOOL_SCHEMA_SHA256`` outside an assignment cannot
    # produce a second match. The UPDATE-ANCHOR sentinel + start-of-
    # line anchor together guarantee uniqueness.
    r'^(EXPECTED_TOOL_SCHEMA_SHA256:\s*str\s*=\s*\(\s*'
    r'#\s*UPDATE-ANCHOR\s*[^\n]*\n\s*")[0-9a-f]{64}("\s*\))',
    re.MULTILINE,
)

_PINNED_VERSION_PATTERN = re.compile(
    # Mirror anchor for the EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH
    # constant. Used by ``_rewrite_pinned_version`` when
    # --update-tool-schema-hash is run with --allow-version-bump.
    r'^(EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH:\s*int\s*=\s*)\d+'
    r'(\s*#\s*VERSION-ANCHOR\s*[^\n]*)$',
    re.MULTILINE,
)


def _read_current_pin() -> tuple[str, int]:
    """Return the ``(hash, version_at_hash)`` pair currently pinned in this
    file. Reads from disk so a session that already ran
    ``--update-tool-schema-hash`` sees the fresh values, not the
    stale module-import-time ones."""
    text = Path(__file__).resolve().read_text(encoding="utf-8")
    h_match = _PINNED_HASH_PATTERN.search(text)
    v_match = _PINNED_VERSION_PATTERN.search(text)
    if h_match is None or v_match is None:
        raise RuntimeError(
            "could not find UPDATE-ANCHOR / VERSION-ANCHOR sentinels "
            f"in {Path(__file__).name}"
        )
    pinned_hash = text[
        h_match.start() + len(h_match.group(1)) : h_match.end() - len(h_match.group(2))
    ]
    # The version literal is between groups 1 and 2.
    pinned_version_str = text[
        v_match.start() + len(v_match.group(1)) : v_match.end() - len(v_match.group(2))
    ]
    return pinned_hash, int(pinned_version_str)


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
    # F8 belt+suspenders: assert exactly one match, here at the
    # rewrite site rather than only in a sibling test.
    if len(_PINNED_HASH_PATTERN.findall(text)) != 1:
        raise RuntimeError(
            "found multiple UPDATE-ANCHOR matches; refusing to rewrite. "
            "Inspect the file for duplicate sentinels."
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


def _rewrite_pinned_version(new_version: int) -> bool:
    """Rewrite :data:`EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` in this
    file. Mirrors :func:`_rewrite_pinned_hash`.

    Called by ``--update-tool-schema-hash`` after a successful hash
    rewrite, to keep the (hash, version) pair atomic."""
    path = Path(__file__).resolve()
    text = path.read_text(encoding="utf-8")
    match = _PINNED_VERSION_PATTERN.search(text)
    if match is None:
        raise RuntimeError(
            f"could not find the VERSION-ANCHOR pattern in {path}"
        )
    current = text[
        match.start() + len(match.group(1)) : match.end() - len(match.group(2))
    ]
    if int(current) == new_version:
        return False
    new_text = (
        text[: match.start()]
        + match.group(1)
        + str(new_version)
        + match.group(2)
        + text[match.end() :]
    )
    path.write_text(new_text, encoding="utf-8")
    return True


def _running_in_ci() -> bool:
    """Return True if any of the standard CI env vars are set.

    F4 fix: ``--update-tool-schema-hash`` is a developer-only flag.
    If it ever fires in CI (committed config typo, runaway pytest
    plugin), we MUST fail rather than skip — a skipped test on a
    misconfigured CI is worse than no test at all."""
    import os

    # Generic + GitHub Actions + GitLab CI + CircleCI + Travis +
    # Jenkins. Any one set means "we're in CI."
    return any(
        os.environ.get(k) == "true" or os.environ.get(k) == "1"
        for k in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "CIRCLECI", "TRAVIS")
    ) or "JENKINS_URL" in os.environ


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
        rewrite both the hash and the version-at-hash pin, then fail
        with a "commit and rerun" message.

        F4 fix: refuse to honor the flag in CI. F2 fix: require a
        ``TOOL_SCHEMA_VERSION`` bump alongside any hash drift."""
        from server.tools import TOOL_SCHEMA_VERSION as live_version

        live_hash = compute_tool_schema_hash(_live_tools)
        pinned_hash, pinned_version = _read_current_pin()

        if request.config.getoption("--update-tool-schema-hash"):
            # F4: refuse in CI.
            if _running_in_ci():
                pytest.fail(
                    "--update-tool-schema-hash must NOT be used in CI. "
                    "This flag rewrites a source file and is intended "
                    "for local developer use only. A CI run with this "
                    "flag set would mask a real schema drift behind a "
                    "skipped test."
                )

            # F2: hash drift WITHOUT a version bump is the decorative-
            # version anti-pattern. Force the contributor to bump
            # TOOL_SCHEMA_VERSION first.
            if live_hash != pinned_hash and live_version == pinned_version:
                pytest.fail(
                    "\n\nTool schema bytes have drifted but "
                    "TOOL_SCHEMA_VERSION is unchanged.\n"
                    f"  pinned hash:    {pinned_hash}\n"
                    f"  live hash:      {live_hash}\n"
                    f"  pinned version: {pinned_version}\n"
                    f"  live version:   {live_version}\n\n"
                    f"A hash drift INVALIDATES the BP1 prompt cache "
                    f"for every sub-agent (see "
                    f".claude/notes/07-multi-agent-caching.md lines "
                    f"40-49). To make the change visible to consumers, "
                    f"bump server.tools.TOOL_SCHEMA_VERSION FIRST, "
                    f"then re-run --update-tool-schema-hash.\n"
                )

            # OK to update both pins atomically.
            hash_changed = _rewrite_pinned_hash(live_hash)
            ver_changed = _rewrite_pinned_version(live_version)
            if hash_changed or ver_changed:
                pytest.fail(
                    f"updated EXPECTED_TOOL_SCHEMA_SHA256={live_hash} and "
                    f"EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH={live_version}.\n"
                    f"Commit the changes and re-run pytest WITHOUT "
                    f"--update-tool-schema-hash to verify the new pin "
                    f"is stable."
                )
            # Both already current — fall through to the normal
            # assertion (which will pass).

        # F2: enforce version pin matches in normal-mode runs too.
        assert live_version == pinned_version, (
            f"server.tools.TOOL_SCHEMA_VERSION ({live_version}) does "
            f"not match the pinned version ({pinned_version}). Either "
            f"the version was bumped without rerunning "
            f"--update-tool-schema-hash, or the pinned version was "
            f"corrupted. Run pytest --update-tool-schema-hash to "
            f"refresh both pins."
        )

        assert live_hash == pinned_hash, (
            f"\n\nTool schema bytes drifted.\n"
            f"  expected: {pinned_hash}\n"
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
            f"  3. Commit the new pinned hash + version.\n"
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


class TestCanonicalSortContract:
    """F1 fix from the E06_S06 critique (partial — see commit body).

    The critic correctly observed that ``json.dumps(sort_keys=True)``
    RECURSIVELY sorts nested dicts, so the hash captures the
    *canonical sorted form*, NOT the raw wire form FastMCP emits
    (which preserves source-code parameter order via pydantic).
    A contributor who reorders parameters in a handler signature
    changes the raw wire bytes but NOT the hash.

    **Architectural resolution.** The cache-stable contract per
    ``.claude/notes/07-multi-agent-caching.md:42`` is "Sort
    properties alphabetically AT serialization time" — a contract
    on the *orchestrator's outbound serializer*. The hash captures
    that canonical sorted form. As long as the orchestrator sorts
    before sending (E08 obligation), our hash IS the wire bytes.

    **Why we cannot enforce source-order alphabetical.** The
    natural fix would be to assert ``list(props.keys()) ==
    sorted(props.keys())`` for every tool. But Python forbids
    "non-default argument follows default argument," so e.g.
    ``find_lemma_by_name(name, paper_id=None, k=10)`` cannot be
    reordered to alphabetical (``k, name, paper_id``) without
    reworking the entire signature to keyword-only args. We
    accept this gap and document it instead.

    These tests pin the architectural invariant so a future
    contributor who breaks it (e.g. by removing ``sort_keys=True``
    in :func:`_serialize_tools`) hits a fast assertion, not a slow
    cache-invalidation incident.
    """

    def test_canonical_form_uses_sort_keys(self, _live_tools):
        """Two tool lists with permuted property orders MUST hash to
        the same value. This pins the assumption: hash represents
        the canonical sorted form, not source-code order. Removing
        ``sort_keys=True`` would break this and silently invalidate
        every sub-agent's cache on a parameter reorder."""
        # Build a permuted parallel: reverse properties on each tool's
        # inputSchema. The hash MUST be unchanged if sort_keys is
        # active in _serialize_tools.
        permuted = []
        for t in _live_tools:
            new_t = t.model_copy()
            schema = dict(new_t.inputSchema or {})
            props = schema.get("properties", {})
            if props:
                # Reverse the order of properties in the dict.
                schema["properties"] = dict(reversed(list(props.items())))
            new_t.inputSchema = schema
            permuted.append(new_t)
        # Both should hash identically because sort_keys re-sorts at
        # serialize time. If a future change drops sort_keys, this
        # test catches the regression at the form level, before the
        # hash drifts in production.
        original = compute_tool_schema_hash(_live_tools)
        permuted_hash = compute_tool_schema_hash(permuted)
        assert original == permuted_hash, (
            "Permuting property order changed the canonical hash. "
            "_serialize_tools must use sort_keys=True so the hash "
            "represents the canonical sorted wire form. Without "
            "sort_keys, source-code parameter reorders would silently "
            "invalidate every sub-agent's BP1 prompt cache."
        )


class TestUpdateProcedure:
    """Brief AC #2: changing a tool description causes the test to fail.

    Plus AC #3 indirectly: the rewrite helper is unit-tested in
    isolation here without recursively shelling out to pytest."""

    def test_changing_tool_description_changes_hash(
        self, tmp_path, _mocked_bge, monkeypatch
    ):
        """Replace one tool's source-of-truth ``ToolMeta`` with a
        different description, re-create the app (forcing
        ``register_all`` to flow the new description through FastMCP),
        and assert the hash differs.

        F7 fix from the E06_S06 critique: the original test mutated
        the post-registration ``Tool`` object via ``model_copy``,
        which bypassed the registration code path. A regression
        where ``register_all`` accidentally hardcoded a description
        or swapped ``description`` for ``name`` would not be caught.
        This version monkeypatches ``server.tools.SEARCH_PAPERS`` to
        a new ``ToolMeta`` and re-runs the registration, exercising
        the actual production path."""
        import server.tools as tools_mod

        # Baseline: live hash with the un-monkeypatched ToolMeta.
        baseline_tools = _build_app_and_list_tools(tmp_path)
        baseline_hash = compute_tool_schema_hash(baseline_tools)

        # Bump description on the source ToolMeta. ToolMeta is
        # frozen=True so we build a new instance with a different
        # description but the SAME name (so register_all's
        # name-keyed handler dict still works).
        bumped_meta = tools_mod.ToolMeta(
            name=tools_mod.SEARCH_PAPERS.name,
            description="BUMP — not the real description",
        )
        monkeypatch.setattr(tools_mod, "SEARCH_PAPERS", bumped_meta)
        # ALL_TOOLS is a tuple capturing the original SEARCH_PAPERS
        # by reference; rebuild it so register_all sees the bumped
        # meta. (The other 6 ToolMetas are unchanged.)
        bumped_all = tuple(
            bumped_meta if tm.name == bumped_meta.name else tm
            for tm in tools_mod.ALL_TOOLS
        )
        monkeypatch.setattr(tools_mod, "ALL_TOOLS", bumped_all)

        bumped_tools = _build_app_and_list_tools(tmp_path / "_bumped")
        bumped_hash = compute_tool_schema_hash(bumped_tools)
        assert bumped_hash != baseline_hash, (
            "Bumping a ToolMeta description and re-running "
            "register_all did NOT change the hash — the description "
            "is not flowing through registration. Inspect "
            "register_all in server/tools.py."
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
