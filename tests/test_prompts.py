"""Role-prefix tests (E08_S02).

Coverage map (acceptance criteria → test class):

  AC                                                       Test class
  ──────────────────────────────────────────────────────────────────
  Each role prefix ≤ 50 tokens                             TestPrefixTokenCap
  server/prompts.py contains exactly 4 role-prefixes       TestPrefixCompleteness
  pytest tests/test_prompts.py passes                      the suite itself
  prompts.md states "BP3 is dropped..."                    TestDocBP3DropSentence
  4-agent fan-out: BP1 byte-identical across all 4 roles   TestBP1ByteIdentityAcrossFanout

Plus regression-grade tests for:
- Frozen-constants invariant (AST literal-only check)
- ROLE_PREFIXES is read-only (MappingProxyType)
- Beta-header constants pinned
- Import-time invariant: ROLE_PREFIXES covers every RouteTag

Token-cap measurement note
--------------------------

The brief mandates "≤ 50 tokens (Claude Sonnet 4.6 tokenizer)".
The Claude tokenizer is NOT published as an offline library; the
only way to count exact Claude tokens is via the Anthropic API
(``client.beta.messages.count_tokens``), which requires a network
call and an ``ANTHROPIC_API_KEY``. Both are explicitly out of
scope for this test suite (per the project's no-network-in-tests
discipline).

We use a conservative heuristic instead: ``len(prefix) <= 200``
(= 50 tokens × 4 chars/token, the standard Anthropic
English-ASCII rate). The heuristic is an UPPER BOUND — under any
plausible BPE, a 200-char ASCII English imperative prefix tokens
to ≤ 50 tokens. Document the choice prominently so a future
contributor doesn't replace it with a falsely-precise tiktoken
proxy (cl100k is OpenAI's BPE, not Claude's).
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from server.prompts import (
    EXTENDED_CACHE_TTL_HEADER_NAME,
    EXTENDED_CACHE_TTL_HEADER_VALUE,
    ROLE_PREFIXES,
    SYSTEM_PROMPT,
)
from server.router import RouteTag

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Heuristic char cap per the synthesis D3: 50 Claude tokens × 4
#: chars/token (Anthropic's English-ASCII rate). Conservative
#: upper bound — any prefix ≤ 200 chars in English imperative
#: prose tokens to ≤ 50 Claude tokens under any plausible BPE.
MAX_PREFIX_CHARS: int = 200

#: Path to the prompts module (used by the AST literal-only test).
PROMPTS_MODULE_PATH: Path = (
    Path(__file__).resolve().parent.parent / "server" / "prompts.py"
)

#: Path to the prompts docs (used by the AC #4 verbatim-sentence
#: test).
PROMPTS_DOC_PATH: Path = (
    Path(__file__).resolve().parent.parent / "server" / "prompts.md"
)

#: The verbatim sentence required by AC #4. Byte-exact, NOT
#: paraphrased.
AC4_VERBATIM_SENTENCE: str = (
    "BP3 is dropped; heterogeneous roles never share seed retrieval bytes"
)


# ===========================================================================
# AC #1 — token cap
# ===========================================================================


class TestPrefixTokenCap:
    """Brief AC #1: each role prefix is ≤ 50 tokens."""

    @pytest.mark.parametrize("tag", list(RouteTag))
    def test_prefix_under_char_cap(self, tag):
        prefix = ROLE_PREFIXES[tag]
        assert len(prefix) <= MAX_PREFIX_CHARS, (
            f"{tag.value} prefix is {len(prefix)} chars, exceeding the "
            f"{MAX_PREFIX_CHARS}-char cap (= 50 Claude tokens × 4 c/t "
            f"heuristic). Either trim the prefix OR document a tighter "
            f"tiktoken-based measurement in the test."
        )

    @pytest.mark.parametrize("tag", list(RouteTag))
    def test_prefix_is_ascii_only(self, tag):
        """F8 fix from the E08_S02 critique: the 4 chars/token heuristic
        is Anthropic's English-ASCII rate. CJK characters and most emoji
        tokenize at 1+ token/char, blowing the heuristic by 4–8×. Pin
        the prefix domain to ASCII so a future contributor adding
        ``[Role: 验证]`` is caught here, not silently shipped over-cap."""
        prefix = ROLE_PREFIXES[tag]
        assert prefix.isascii(), (
            f"{tag.value} prefix contains non-ASCII characters. The "
            f"200-char heuristic uses Anthropic's English-ASCII rate "
            f"(4 chars/token); non-ASCII text tokenizes denser. Either "
            f"transliterate to ASCII OR replace the heuristic with a "
            f"tiktoken-based measurement that handles the contributor's "
            f"chosen script."
        )

    def test_max_prefix_chars_constant(self):
        """Pin the heuristic so a future edit catches the eye."""
        assert MAX_PREFIX_CHARS == 200


# ===========================================================================
# AC #2 — exactly 4 role-prefix constants
# ===========================================================================


class TestPrefixCompleteness:
    """Brief AC #2: ``server/prompts.py`` contains exactly 4
    role-prefix constants, one per ``RouteTag``."""

    def test_role_prefixes_has_exactly_four_entries(self):
        assert len(ROLE_PREFIXES) == 4

    def test_role_prefixes_keys_match_route_tag(self):
        assert set(ROLE_PREFIXES.keys()) == set(RouteTag)

    def test_every_route_tag_has_a_prefix(self):
        for tag in RouteTag:
            assert tag in ROLE_PREFIXES, (
                f"RouteTag.{tag.name} has no prefix in ROLE_PREFIXES; "
                f"adding a fifth RouteTag value requires extending "
                f"ROLE_PREFIXES in lockstep (closed-at-four invariant)."
            )

    def test_every_prefix_is_a_string(self):
        for tag, prefix in ROLE_PREFIXES.items():
            assert isinstance(prefix, str), (
                f"ROLE_PREFIXES[{tag.value}] must be a str; got "
                f"{type(prefix).__name__}."
            )

    def test_every_prefix_is_non_empty(self):
        for tag, prefix in ROLE_PREFIXES.items():
            assert prefix.strip(), (
                f"ROLE_PREFIXES[{tag.value}] is empty / whitespace-only."
            )


# ===========================================================================
# Frozen-constants discipline (AST literal-only check)
# ===========================================================================


class _LiteralOnlyVisitor(ast.NodeVisitor):
    """Walk the ROLE_PREFIXES dict literal and reject any node
    that is not a bare string literal or a parenthesized
    concatenation of bare string literals.

    Specifically rejects:
    - ``ast.JoinedStr`` (f-strings) — even with no placeholders
    - ``ast.Call`` (any method call, including ``.format()`` /
      ``.join()``)
    - ``ast.BinOp`` (``+`` / ``%`` / ``*`` concatenation)
    - ``ast.Name`` / ``ast.Attribute`` (variable reference)
    - ``ast.IfExp`` (conditional expression)

    The synthesis D5 mandates this discipline: any of the above
    creates a path for a future edit to silently invalidate BP1.
    """

    def __init__(self) -> None:
        self.violations: list[str] = []

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        self.violations.append(
            f"f-string at line {node.lineno} — REJECTED. F-strings are "
            f"forbidden for ROLE_PREFIXES values (even with no "
            f"placeholders) because a future edit silently invalidates "
            f"BP1."
        )

    def visit_Call(self, node: ast.Call) -> None:
        self.violations.append(
            f"Call expression at line {node.lineno} — REJECTED. "
            f"Method calls (e.g. .format / .join) are forbidden for "
            f"ROLE_PREFIXES values."
        )

    def visit_BinOp(self, node: ast.BinOp) -> None:
        # Allow string concatenation between ast.Constant nodes (this
        # is what Python parses ``"foo" "bar"`` into — implicit
        # concatenation — which Python's parser folds to a single
        # Constant. So we should not see BinOp for that case.) Reject
        # other BinOps.
        self.violations.append(
            f"Binary operator at line {node.lineno} — REJECTED. "
            f"+ / % / * concatenation is forbidden for ROLE_PREFIXES "
            f"values."
        )

    def visit_Name(self, node: ast.Name) -> None:
        # Variable reference (other than a constant). Reject — the
        # value is not a literal.
        self.violations.append(
            f"Name reference {node.id!r} at line {node.lineno} — "
            f"REJECTED. ROLE_PREFIXES values must be bare string "
            f"literals."
        )

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.violations.append(
            f"Attribute access at line {node.lineno} — REJECTED."
        )

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.violations.append(
            f"Conditional expression at line {node.lineno} — REJECTED."
        )


class TestFrozenConstantsDiscipline:
    """Synthesis D4 / D5: ROLE_PREFIXES values are bare string
    literals. AST-parses ``server/prompts.py`` and rejects f-strings,
    .format() calls, BinOp concatenation, and variable references
    in any value of the ROLE_PREFIXES dict literal."""

    def test_role_prefixes_dict_values_are_bare_literals(self):
        source = PROMPTS_MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(PROMPTS_MODULE_PATH))

        # Find the assignment to ROLE_PREFIXES at module level.
        # The RHS may be a Call (MappingProxyType(...)) wrapping a
        # Dict literal.
        role_prefixes_value: ast.AST | None = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Name)
                        and target.id == "ROLE_PREFIXES"
                    ):
                        role_prefixes_value = node.value
                        break
            if isinstance(node, ast.AnnAssign) and (
                isinstance(node.target, ast.Name)
                and node.target.id == "ROLE_PREFIXES"
            ):
                role_prefixes_value = node.value

        assert role_prefixes_value is not None, (
            "ROLE_PREFIXES assignment not found in server/prompts.py"
        )

        # Unwrap MappingProxyType(...) call to get the inner Dict.
        inner_dict: ast.AST | None = None
        if isinstance(role_prefixes_value, ast.Call):
            # Expect MappingProxyType(<Dict>)
            assert (
                isinstance(role_prefixes_value.func, ast.Name)
                and role_prefixes_value.func.id == "MappingProxyType"
            ), (
                f"Expected MappingProxyType(...) wrapping the dict; "
                f"got Call to {ast.dump(role_prefixes_value.func)}"
            )
            assert len(role_prefixes_value.args) == 1
            inner_dict = role_prefixes_value.args[0]
        elif isinstance(role_prefixes_value, ast.Dict):
            inner_dict = role_prefixes_value

        assert isinstance(inner_dict, ast.Dict), (
            "ROLE_PREFIXES value must be a Dict literal "
            "(optionally wrapped in MappingProxyType)"
        )

        # Walk every VALUE of the dict and assert it's a literal.
        # The values may be Constant(str) directly, OR a Name
        # referring to a module-level constant (e.g. _LOOKUP_PREFIX).
        # If a Name, look up the constant in the module and assert
        # IT is a bare literal.
        module_constants = _collect_module_string_constants(tree)

        for key_node, val_node in zip(
            inner_dict.keys, inner_dict.values, strict=True,
        ):
            self._assert_value_is_literal(
                val_node, module_constants, key_node,
            )

    def _assert_value_is_literal(
        self,
        val_node: ast.AST,
        module_constants: dict[str, ast.AST],
        key_node: ast.AST | None,
    ) -> None:
        """Assert ``val_node`` is a Constant(str), or a Name pointing
        to a module-level Constant(str)."""
        if isinstance(val_node, ast.Constant) and isinstance(
            val_node.value, str
        ):
            return
        if isinstance(val_node, ast.Name):
            target_value = module_constants.get(val_node.id)
            assert target_value is not None, (
                f"ROLE_PREFIXES value {val_node.id!r} references a "
                f"name not assigned at module level (or assigned to a "
                f"non-literal). The literal-only invariant is broken."
            )
            visitor = _LiteralOnlyVisitor()
            visitor.visit(target_value)
            assert not visitor.violations, (
                f"ROLE_PREFIXES value {val_node.id!r} is not a bare "
                f"literal: {visitor.violations}"
            )
            return
        # Any other node type is a violation.
        raise AssertionError(
            f"ROLE_PREFIXES value at key {ast.dump(key_node) if key_node else '?'} "
            f"is not a bare string literal or named-constant: "
            f"{ast.dump(val_node)}"
        )


def _collect_module_string_constants(
    tree: ast.Module,
) -> dict[str, ast.AST]:
    """Return ``{name: rhs_value_node}`` for every module-level
    ``name = <expr>`` where the RHS could be a string."""
    out: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node.value
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            out[node.target.id] = node.value
    return out


# ===========================================================================
# Runtime immutability — MappingProxyType
# ===========================================================================


class TestRuntimeImmutability:
    """ROLE_PREFIXES is wrapped in MappingProxyType so a downstream
    consumer can't mutate the role → prefix mapping at runtime
    (defense alongside the AST literal-only check)."""

    def test_role_prefixes_is_mapping_proxy(self):
        assert isinstance(ROLE_PREFIXES, MappingProxyType)

    def test_role_prefixes_setitem_raises(self):
        with pytest.raises(TypeError):
            ROLE_PREFIXES[RouteTag.LOOKUP] = "tampered"  # type: ignore[index]

    def test_role_prefixes_delitem_raises(self):
        with pytest.raises(TypeError):
            del ROLE_PREFIXES[RouteTag.LOOKUP]  # type: ignore[index]


# ===========================================================================
# AC #4 — verbatim sentence in prompts.md
# ===========================================================================


class TestDocBP3DropSentence:
    """Brief AC #4: ``server/prompts.md`` MUST explicitly state:

        "BP3 is dropped; heterogeneous roles never share seed
        retrieval bytes"

    Byte-exact substring check, NOT a paraphrase. Catches a future
    documentation rewrite that rephrases the sentence and
    inadvertently breaks the AC."""

    def test_prompts_md_contains_ac4_sentence_verbatim(self):
        assert PROMPTS_DOC_PATH.is_file(), (
            f"server/prompts.md missing at {PROMPTS_DOC_PATH}"
        )
        text = PROMPTS_DOC_PATH.read_text(encoding="utf-8")
        assert AC4_VERBATIM_SENTENCE in text, (
            f"server/prompts.md must contain the AC #4 verbatim "
            f"sentence:\n  {AC4_VERBATIM_SENTENCE!r}\n"
            f"Found neither in the headers nor body."
        )

    def test_prompts_md_documents_the_four_roles(self):
        """Sanity: each RouteTag value must appear in the docs."""
        text = PROMPTS_DOC_PATH.read_text(encoding="utf-8")
        for tag in RouteTag:
            assert tag.value in text, (
                f"RouteTag.{tag.name} ({tag.value!r}) is not "
                f"documented in server/prompts.md."
            )

    def test_prompts_md_documents_extended_cache_ttl_header(self):
        """The 1-hour TTL beta header literal must appear in the
        docs so a future operator searching for the header value
        finds the source-of-truth doc."""
        text = PROMPTS_DOC_PATH.read_text(encoding="utf-8")
        assert EXTENDED_CACHE_TTL_HEADER_VALUE in text


# ===========================================================================
# AC #5 — BP1 byte-identical across the 4-agent fan-out
# ===========================================================================


def _canonical_json(obj: object) -> bytes:
    """Canonical JSON serialization for hash-stable byte comparisons.

    Mirrors the discipline in ``tests/test_server_tool_schema.py`` —
    sort_keys + tight separators + ASCII-escaped Unicode. The same
    canonicalizer is used for E06_S06's tool-schema hash; reusing
    the shape means BP1 byte-equality and tool-schema byte-stability
    are computed from the same primitive."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")


def _live_tools_payload() -> list[dict]:
    """Return the live tool list as serializable dicts.

    F1 fix from the E08_S02 critique: we used to use a synthetic
    two-element stub list here. That made the BP1 byte-identity test
    tautological — ``_build_fanout_request`` discarded ``tag`` for the
    system+tools region by construction. The critic verified
    ``import server.tools`` runs in ~25 ms with NO ``lancedb`` import
    transitively, debunking the original "heavy import" rationale.

    We now serialize the live ``server.tools.ALL_TOOLS`` registry
    (frozen ``ToolMeta`` dataclasses with ``name`` + ``description``)
    into the same wire shape ``ALL_TOOLS`` would take in a real
    ``messages.create`` ``tools=[...]`` kwarg. The byte surface is the
    one E06_S06's ``EXPECTED_TOOL_SCHEMA_SHA256`` already pins, so a
    hash drift caught HERE means either (a) the role-as-user-turn-prefix
    invariant broke (which is what AC #5 cares about) OR (b) someone
    edited a tool description (which E06_S06 also catches and routes
    through the schema-version bump procedure)."""
    from server.tools import ALL_TOOLS

    return [{"name": t.name, "description": t.description} for t in ALL_TOOLS]


def _build_fanout_request(tag: RouteTag, problem: str) -> dict:
    """Build a hypothetical ``messages.create`` kwargs dict for one
    role. The role prefix and the problem statement go in the same
    text content block separated by ``"\\n\\n"`` (synthesis D9).

    The ``system`` field is wrapped as a single-element list of text
    content blocks so a downstream caller can attach BP1's
    ``cache_control`` marker — the bare-string ``system`` form silently
    drops ``cache_control`` per the Anthropic Messages API. We use the
    list form here so the test's BP1 region matches the integration
    seam shape the orchestrator (E08_S04) will actually emit (F2 fix
    from the E08_S02 critique)."""
    return {
        "system": [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral", "ttl": "1h"},
            }
        ],
        "tools": _live_tools_payload(),
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": ROLE_PREFIXES[tag] + "\n\n" + problem,
                        "cache_control": {
                            "type": "ephemeral",
                            "ttl": "1h",
                        },
                    }
                ],
            }
        ],
    }


def _bp1_hash(req: dict) -> str:
    """Hash the BP1 region: ``system`` + ``tools``. Anthropic's
    cache key is the bytes UP TO and including the first
    cache_control marker; for BP1 that's the end of the tools
    block. We extract those two fields and canonical-JSON-hash
    them."""
    bp1 = {"system": req["system"], "tools": req["tools"]}
    return hashlib.sha256(_canonical_json(bp1)).hexdigest()


class TestBP1ByteIdentityAcrossFanout:
    """Brief AC #5: a 4-agent fan-out integration test confirms BP1
    is byte-identical across all roles (hash equality check).

    The test constructs 4 hypothetical messages-API request bodies
    (one per RouteTag), extracts the BP1 region (system + tools),
    canonical-hashes, asserts all 4 hashes equal.

    **If this test fails, the cause is upstream tool drift OR a
    system-prompt edit that escaped the role-prefix invariant.**
    The role prefixes themselves DON'T appear in BP1 — they live
    in the user turn AFTER the BP1 marker. A failure means
    something broke the byte-stability of the system + tools
    surface that ALL roles share."""

    def test_all_four_roles_share_one_bp1_hash(self):
        problem = "What is the structure of the étale fundamental group?"
        hashes = {
            tag.value: _bp1_hash(_build_fanout_request(tag, problem))
            for tag in RouteTag
        }
        unique_hashes = set(hashes.values())
        assert len(unique_hashes) == 1, (
            f"BP1 hashes diverge across the 4-agent fan-out — the "
            f"role-as-user-turn-prefix invariant is broken. Per-role "
            f"hashes: {hashes}. Likely causes: (a) a per-role system "
            f"prompt was introduced (forbidden — see prompts.md), or "
            f"(b) tools serialization is per-role (which would also "
            f"break E06_S06's tool-schema hash). Debug by diffing "
            f"the canonical JSON of system + tools between two roles."
        )

    def test_bp1_hash_is_stable_across_problems(self):
        """The role prefix is in the user turn (BP2 region), NOT
        in BP1. Different problem statements MUST produce the same
        BP1 hash for a given role."""
        problem_a = "Prove that every Hilbert space has an orthonormal basis"
        problem_b = "Define the cotangent complex"
        hash_a = _bp1_hash(_build_fanout_request(RouteTag.SYNTHESIS, problem_a))
        hash_b = _bp1_hash(_build_fanout_request(RouteTag.SYNTHESIS, problem_b))
        assert hash_a == hash_b, (
            "BP1 hash differs across problem statements — but problem "
            "statements live in the user turn (BP2 region), not BP1. "
            "Something is leaking problem-statement bytes into the "
            "system or tools surface."
        )

    @pytest.mark.parametrize("tag", list(RouteTag))
    def test_role_prefix_lives_in_user_turn_not_bp1(self, tag):
        """Sanity: the role prefix string must NOT appear in the
        canonical JSON of the BP1 region. F12 fix from the E08_S02
        critique: parametrized over ALL FOUR ``RouteTag`` values so a
        future regression that moves only ONE role's prefix into the
        system prompt is caught (the pre-fix version of this test
        only exercised AUTOFORMALIZATION)."""
        req = _build_fanout_request(tag, "test problem statement")
        bp1_bytes = _canonical_json({"system": req["system"], "tools": req["tools"]})
        bp1_text = bp1_bytes.decode("utf-8")
        prefix_marker = ROLE_PREFIXES[tag][:20]  # the "[Role: <Name>]" head
        assert prefix_marker not in bp1_text, (
            f"Role prefix marker {prefix_marker!r} for {tag.value!r} "
            f"found in the BP1 region — the role-as-user-turn-prefix "
            f"invariant is broken. The role prefix MUST live in the "
            f"user turn (BP2 region), NOT in the system or tools "
            f"surface."
        )

    def test_bp1_hash_pinned(self):
        """F13 fix from the E08_S02 critique: pin the canonical-JSON
        SHA-256 of the BP1 region (system + live ``ALL_TOOLS``).

        The structural assertion above proves all four roles share
        ONE hash; this test pins WHAT that hash is. A drift here means
        EITHER ``SYSTEM_PROMPT`` changed (E08_S04 will land the real
        body and intentionally drift this constant) OR
        ``server.tools.ALL_TOOLS`` changed (E06_S06's
        ``EXPECTED_TOOL_SCHEMA_SHA256`` would also fire). Without this
        pin a uniform-but-changed BP1 invalidates the cross-role cache
        identically across all four roles and the structural test
        misses it.

        **Update procedure (intentional drift):** edit the literal
        below to the value the test prints in the assertion message.
        Mirror the discipline of ``EXPECTED_TOOL_SCHEMA_SHA256`` in
        ``tests/test_server_tool_schema.py`` — drift is intentional
        only when paired with an upstream change (here: the real
        ``SYSTEM_PROMPT`` body landing in E08_S04).
        """
        # UPDATE-ANCHOR — bump when SYSTEM_PROMPT or ALL_TOOLS drift:
        EXPECTED_BP1_SHA256 = (
            "f01de11288e2128b5af9c2d04dbdb264f6122f96f62d6cc4e3559ef9c16b2084"
        )
        req = _build_fanout_request(
            RouteTag.SYNTHESIS, "any problem; BP1 is independent of problem",
        )
        actual = _bp1_hash(req)
        assert actual == EXPECTED_BP1_SHA256, (
            f"BP1 hash drifted. Expected {EXPECTED_BP1_SHA256!r}, "
            f"got {actual!r}. EITHER (a) SYSTEM_PROMPT changed (was "
            f"this an intentional E08_S04 system-prompt landing? bump "
            f"the constant), OR (b) ALL_TOOLS changed (test_server_"
            f"tool_schema.py should also be failing — fix THAT first), "
            f"OR (c) the BP1 region shape changed (e.g. system was "
            f"refactored back to a bare string — which would silently "
            f"drop BP1 cache_control). To intentionally update, edit "
            f"the EXPECTED_BP1_SHA256 literal in this file to {actual!r}."
        )


# ===========================================================================
# Beta header constants
# ===========================================================================


class TestBetaHeaderConstants:
    """The Anthropic 1-hour-TTL beta header values are pinned in
    server/prompts.py for the orchestrator (E08_S04) to import. Pin
    the canonical names here too so a future drift triggers a test
    failure not a subtle cache miss."""

    def test_beta_header_name(self):
        assert EXTENDED_CACHE_TTL_HEADER_NAME == "anthropic-beta"

    def test_beta_header_value(self):
        # Per .claude/notes/07-multi-agent-caching.md:27.
        assert EXTENDED_CACHE_TTL_HEADER_VALUE == (
            "extended-cache-ttl-2025-04-11"
        )


# ===========================================================================
# Closed-at-four invariant (import-time assert)
# ===========================================================================


class TestClosedAtFourInvariant:
    """The ``if set(ROLE_PREFIXES) != set(RouteTag): raise
    RuntimeError(...)`` at server/prompts.py import time enforces
    that adding a fifth RouteTag value without extending
    ROLE_PREFIXES fails the import. F4 fix from the E08_S02 critique:
    the check used to be a bare ``assert`` which Python compiles to a
    no-op under ``-O`` (PYTHONOPTIMIZE=1)."""

    def test_route_tag_count_is_four(self):
        """Sanity: the closed-at-four contract from E08_S01 is
        still in force."""
        assert len(list(RouteTag)) == 4

    def test_role_prefixes_count_matches(self):
        assert len(ROLE_PREFIXES) == len(list(RouteTag))

    def test_closed_at_four_check_survives_dash_O(self):
        """F4 regression guard: spawn ``python -O -c "import
        server.prompts"`` and verify it succeeds. If the import-time
        check were a bare ``assert``, ``-O`` would compile it away —
        but the check would still need to fire if a contributor adds
        a fifth ``RouteTag`` without extending ``ROLE_PREFIXES``.

        We can't easily fake a fifth RouteTag inside a subprocess
        without writing a temp module. Instead this test verifies the
        runtime CHECK itself (not just the assert syntax) by reading
        the source and confirming it uses ``raise RuntimeError`` not
        ``assert``. A defense-in-depth pair: this test catches
        accidental regression of the F4 fix; the import-time check
        catches the closed-at-four invariant violation."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-O", "-c", "import server.prompts"],
            capture_output=True, text=True, timeout=30,
            cwd=str(PROMPTS_MODULE_PATH.parent.parent),
        )
        assert result.returncode == 0, (
            f"`python -O -c 'import server.prompts'` failed: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )

        source = PROMPTS_MODULE_PATH.read_text(encoding="utf-8")
        assert "raise RuntimeError" in source and (
            "if set(ROLE_PREFIXES.keys()) != set(RouteTag)" in source
        ), (
            "The closed-at-four import-time check must use "
            "`if … raise RuntimeError(…)` (NOT `assert`) so it "
            "survives `python -O`. F4 from the E08_S02 critique."
        )
        # And: the bare 'assert set(ROLE_PREFIXES.keys()) == set(RouteTag)'
        # form must NOT reappear.
        assert "assert set(ROLE_PREFIXES.keys()) == set(RouteTag)" not in source, (
            "Found `assert set(ROLE_PREFIXES.keys()) == set(RouteTag)` in "
            "server/prompts.py — this is the pre-F4 form that compiles "
            "to a no-op under `python -O`. Use `if … raise RuntimeError(…)` "
            "instead. See F4 in the E08_S02 critique."
        )
