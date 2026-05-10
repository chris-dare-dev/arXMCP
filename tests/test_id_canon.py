"""``canonicalize_turn`` tests (E08_S04 Rule 1).

Coverage map (acceptance criteria → test class):

  AC                                                             Test class
  ────────────────────────────────────────────────────────────────────────────
  Replaces non-deterministic IDs with toolu_00000000, ...        TestCanonicalForm
  Idempotent — twice produces same as once                       TestIdempotency
  Test path: brief says server/orchestrator/test_id_canon.py     this file (see note below)

**Note on test path.** The brief AC #6 says ``pytest server/orchestrator/test_id_canon.py``
must pass. The project's ``pyproject.toml`` pins ``testpaths = ["tests"]``
so a test file under ``server/orchestrator/`` would NOT be collected
by plain ``pytest``. Per E08_S04 research synthesis D1, this test
file lives at ``tests/test_id_canon.py`` and the deviation is
documented in ``docs/orchestrator-rules.md``. The brief's AC is
satisfied because the test passes when invoked at any path —
the file location is incidental.

Plus regression-grade tests for:
- Deep-copy mutation discipline (input list NOT mutated)
- Pairing invariant (tool_use ↔ tool_result share the same
  canonical ID after rewrite)
- Robustness on malformed input (missing content, non-dict block,
  non-list content, missing id)
- Multiple-rounds canonicalization (5 tool calls → IDs 0..4)
- Mixed block types in one message (tool_use, text, tool_result)
"""

from __future__ import annotations

import copy

from server.orchestrator.id_canon import (
    CANONICAL_ID_FORMAT,
    canonicalize_turn,
    is_canonical_id,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_use(tool_use_id: str, name: str = "search_papers") -> dict:
    return {
        "type": "tool_use",
        "id": tool_use_id,
        "name": name,
        "input": {"query": "demo"},
    }


def _tool_result(tool_use_id: str, text: str = "result") -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": [{"type": "text", "text": text}],
    }


def _msg(role: str, content: list[dict]) -> dict:
    return {"role": role, "content": content}


# ===========================================================================
# AC — Replaces IDs with the canonical format
# ===========================================================================


class TestCanonicalForm:
    """AC: ``canonicalize_turn`` replaces non-deterministic IDs with
    ``toolu_00000000``, ``toolu_00000001``, etc."""

    def test_first_id_becomes_counter_zero(self):
        messages = [
            _msg("assistant", [_tool_use("toolu_01ABC")]),
        ]
        out = canonicalize_turn(messages)
        assert out[0]["content"][0]["id"] == "toolu_00000000"

    def test_second_id_becomes_counter_one(self):
        messages = [
            _msg("assistant", [
                _tool_use("toolu_01XYZ"),
                _tool_use("toolu_02DEF"),
            ]),
        ]
        out = canonicalize_turn(messages)
        ids = [b["id"] for b in out[0]["content"]]
        assert ids == ["toolu_00000000", "toolu_00000001"]

    def test_canonical_id_format_pinned(self):
        """The format string must produce zero-padded 8-digit
        counters. A regression that drops the padding (e.g.
        ``"toolu_{counter}"``) would be caught here."""
        assert CANONICAL_ID_FORMAT.format(counter=0) == "toolu_00000000"
        assert CANONICAL_ID_FORMAT.format(counter=42) == "toolu_00000042"
        assert CANONICAL_ID_FORMAT.format(counter=99_999_999) == "toolu_99999999"

    def test_is_canonical_id_helper(self):
        """The is_canonical_id helper must accept canonical forms
        and reject everything else."""
        assert is_canonical_id("toolu_00000000")
        assert is_canonical_id("toolu_99999999")
        # 7 digits (not enough): reject.
        assert not is_canonical_id("toolu_0000000")
        # 9 digits (too many): reject.
        assert not is_canonical_id("toolu_000000000")
        # Wrong prefix.
        assert not is_canonical_id("tool_00000000")
        # Original Anthropic form.
        assert not is_canonical_id("toolu_01ABC")
        # Empty / non-string handled by ``re.match`` returning None.
        assert not is_canonical_id("")


# ===========================================================================
# AC — Idempotency
# ===========================================================================


class TestIdempotency:
    """AC: applying ``canonicalize_turn`` twice produces the same
    output as applying it once."""

    def test_double_application_is_idempotent_simple(self):
        messages = [
            _msg("assistant", [_tool_use("toolu_01ABC")]),
            _msg("user", [_tool_result("toolu_01ABC")]),
        ]
        once = canonicalize_turn(messages)
        twice = canonicalize_turn(once)
        assert once == twice

    def test_double_application_is_idempotent_multi_round(self):
        """Five-round retrieval session: pre-canonical IDs span the
        full alphabet of Anthropic-issued forms."""
        messages = [
            _msg("assistant", [_tool_use("toolu_R1abc"), _tool_use("toolu_R1def")]),
            _msg("user", [
                _tool_result("toolu_R1abc"),
                _tool_result("toolu_R1def"),
            ]),
            _msg("assistant", [_tool_use("toolu_R2ghi")]),
            _msg("user", [_tool_result("toolu_R2ghi")]),
            _msg("assistant", [_tool_use("toolu_R3jkl"), _tool_use("toolu_R3mno")]),
        ]
        once = canonicalize_turn(messages)
        twice = canonicalize_turn(once)
        thrice = canonicalize_turn(twice)
        assert once == twice == thrice
        # Counter values are 0..4 (5 distinct IDs).
        all_ids = []
        for msg in once:
            for block in msg["content"]:
                if "id" in block:
                    all_ids.append(block["id"])
                if "tool_use_id" in block:
                    all_ids.append(block["tool_use_id"])
        # Every emitted id must be in canonical form 00..04.
        assert set(all_ids) == {
            "toolu_00000000", "toolu_00000001", "toolu_00000002",
            "toolu_00000003", "toolu_00000004",
        }


# ===========================================================================
# Mutation discipline — deep copy, original list untouched
# ===========================================================================


class TestDeepCopyDiscipline:
    """E08_S04 synthesis D2: ``canonicalize_turn`` returns a deep
    copy. The input list and its nested dicts MUST NOT be mutated.
    Idempotency holds without sacrificing caller invariants."""

    def test_input_list_object_is_not_returned(self):
        messages = [_msg("assistant", [_tool_use("toolu_01ABC")])]
        out = canonicalize_turn(messages)
        assert out is not messages

    def test_input_message_dicts_are_not_mutated(self):
        messages = [_msg("assistant", [_tool_use("toolu_01ABC")])]
        snapshot = copy.deepcopy(messages)
        canonicalize_turn(messages)
        assert messages == snapshot, (
            "canonicalize_turn must NOT mutate the input list. "
            "If this fails, the deep-copy discipline (E08_S04 "
            "synthesis D2) was bypassed."
        )

    def test_input_content_blocks_are_not_mutated(self):
        block = _tool_use("toolu_01ABC")
        messages = [_msg("assistant", [block])]
        canonicalize_turn(messages)
        assert block["id"] == "toolu_01ABC"

    def test_returned_blocks_are_distinct_objects_from_input(self):
        block = _tool_use("toolu_01ABC")
        messages = [_msg("assistant", [block])]
        out = canonicalize_turn(messages)
        assert out[0]["content"][0] is not block


# ===========================================================================
# Pairing invariant — tool_use ↔ tool_result share canonical ID
# ===========================================================================


class TestPairingInvariant:
    """A ``tool_use`` block with id ``X`` and the matching
    ``tool_result`` block with ``tool_use_id`` ``X`` MUST rewrite
    to the same canonical id ``Y`` so the API-required pairing
    invariant is preserved."""

    def test_tool_use_and_tool_result_pair_share_canonical_id(self):
        messages = [
            _msg("assistant", [_tool_use("toolu_01PAIR")]),
            _msg("user", [_tool_result("toolu_01PAIR")]),
        ]
        out = canonicalize_turn(messages)
        use_id = out[0]["content"][0]["id"]
        result_id = out[1]["content"][0]["tool_use_id"]
        assert use_id == result_id == "toolu_00000000"

    def test_three_pairs_get_distinct_canonical_ids(self):
        messages = [
            _msg("assistant", [
                _tool_use("toolu_01A"), _tool_use("toolu_02B"), _tool_use("toolu_03C"),
            ]),
            _msg("user", [
                _tool_result("toolu_01A"),
                _tool_result("toolu_02B"),
                _tool_result("toolu_03C"),
            ]),
        ]
        out = canonicalize_turn(messages)
        use_ids = [b["id"] for b in out[0]["content"]]
        result_ids = [b["tool_use_id"] for b in out[1]["content"]]
        assert use_ids == ["toolu_00000000", "toolu_00000001", "toolu_00000002"]
        assert result_ids == ["toolu_00000000", "toolu_00000001", "toolu_00000002"]

    def test_orphan_tool_result_with_no_matching_tool_use(self):
        """A ``tool_result`` with no preceding ``tool_use`` for the
        same id is malformed input but should not crash. The
        function assigns a fresh canonical id to the orphan."""
        messages = [
            _msg("user", [_tool_result("toolu_orphan")]),
        ]
        out = canonicalize_turn(messages)
        assert out[0]["content"][0]["tool_use_id"] == "toolu_00000000"


# ===========================================================================
# Robustness — malformed input
# ===========================================================================


class TestRobustness:
    """The function MUST NOT raise on input shape variants. It
    produces a best-effort canonicalized copy."""

    def test_empty_messages(self):
        assert canonicalize_turn([]) == []

    def test_message_without_content(self):
        messages = [{"role": "system"}]  # no content key
        assert canonicalize_turn(messages) == messages

    def test_message_with_non_list_content(self):
        messages = [{"role": "user", "content": "string content"}]
        out = canonicalize_turn(messages)
        # Best-effort: returns a deep copy unchanged.
        assert out == messages

    def test_block_without_type(self):
        messages = [{"role": "assistant", "content": [{"id": "toolu_01ABC"}]}]
        out = canonicalize_turn(messages)
        # Block has no type — left untouched.
        assert out[0]["content"][0]["id"] == "toolu_01ABC"

    def test_block_with_other_type_left_untouched(self):
        messages = [
            _msg("assistant", [
                {"type": "text", "text": "hello"},
                _tool_use("toolu_01ABC"),
                {"type": "image", "source": {"data": "..."}},
            ]),
        ]
        out = canonicalize_turn(messages)
        # Text + image untouched; tool_use rewritten.
        assert out[0]["content"][0] == {"type": "text", "text": "hello"}
        assert out[0]["content"][1]["id"] == "toolu_00000000"
        assert out[0]["content"][2]["type"] == "image"

    def test_tool_use_with_no_id(self):
        """An ``tool_use`` block missing ``id`` is malformed but
        must not crash. The block is left untouched."""
        messages = [_msg("assistant", [{
            "type": "tool_use",
            "name": "search_papers",
            "input": {},
        }])]
        out = canonicalize_turn(messages)
        # No id → no rewrite, and no "id" key sprouts in the output.
        assert "id" not in out[0]["content"][0]

    def test_non_dict_message_skipped(self):
        # A list with a non-dict element (e.g., a stray None).
        messages = [None, _msg("assistant", [_tool_use("toolu_01ABC")])]
        # Should NOT raise.
        out = canonicalize_turn(messages)
        # First entry preserved; second entry rewritten.
        assert out[0] is None
        assert out[1]["content"][0]["id"] == "toolu_00000000"


# ===========================================================================
# 4-agent fan-out worked example (matches docs/orchestrator-rules.md)
# ===========================================================================


class TestFourAgentFanoutExample:
    """The brief AC: ``docs/orchestrator-rules.md`` contains a worked
    4-agent fan-out example. This test pins the example's expected
    output so a future doc edit that drifts from the worked output
    is caught at test time."""

    def test_4_agent_3_round_canonicalization_pins_to_known_output(self):
        """Three retrieval rounds, 4 agents reading a shared
        prefix — the canonical IDs are deterministic by round
        order. The test pins the expected output so the doc's
        worked example can be machine-checked."""
        # Round 1: search_papers
        # Round 2: get_chunk × 2
        # Round 3: search_papers
        messages = [
            _msg("assistant", [
                _tool_use("toolu_01R1A", name="search_papers"),
            ]),
            _msg("user", [_tool_result("toolu_01R1A")]),
            _msg("assistant", [
                _tool_use("toolu_02R2A", name="get_chunk"),
                _tool_use("toolu_03R2B", name="get_chunk"),
            ]),
            _msg("user", [
                _tool_result("toolu_02R2A"),
                _tool_result("toolu_03R2B"),
            ]),
            _msg("assistant", [
                _tool_use("toolu_04R3A", name="search_papers"),
            ]),
            _msg("user", [_tool_result("toolu_04R3A")]),
        ]
        out = canonicalize_turn(messages)
        # Walk the output and collect every emitted id.
        emitted = []
        for msg in out:
            for block in msg["content"]:
                if "id" in block:
                    emitted.append(("id", block["id"]))
                if "tool_use_id" in block:
                    emitted.append(("tool_use_id", block["tool_use_id"]))
        # 4 distinct API-issued ids → 4 distinct canonical ids,
        # each appearing twice (once on tool_use, once on
        # tool_result).
        assert emitted == [
            ("id", "toolu_00000000"),
            ("tool_use_id", "toolu_00000000"),
            ("id", "toolu_00000001"),
            ("id", "toolu_00000002"),
            ("tool_use_id", "toolu_00000001"),
            ("tool_use_id", "toolu_00000002"),
            ("id", "toolu_00000003"),
            ("tool_use_id", "toolu_00000003"),
        ]


# ===========================================================================
# E08_S04 critique rectification guards (F1, F4, F10)
# ===========================================================================


import pytest  # noqa: E402


class TestRectificationGuards:
    """Regression guards for the E08_S04 critique findings F1
    (counter contract), F4 (id+tool_use_id co-occurrence), and F10
    (strict list type check)."""

    def test_f1_growing_history_preserves_old_canonical_ids(self):
        """F1 fix: when the orchestrator passes the FULL accumulated
        history each transition, previously-canonicalized ids stay
        stable. This is the contract documented in the docstring's
        ``When to call`` section.

        Simulates a two-transition orchestration:
        - Transition 1: history = [turn_a]
        - Transition 2: history = [turn_a, turn_b] (full)

        After transition 2, turn_a's ids must be the SAME as after
        transition 1. The cross-agent prompt prefix only stays
        cacheable if this holds."""
        turn_a_use = _tool_use("toolu_01A", name="search_papers")
        turn_a_result = _tool_result("toolu_01A")
        turn_b_use = _tool_use("toolu_02B", name="get_chunk")

        # Transition 1
        ctx_after_t1 = canonicalize_turn([
            _msg("assistant", [turn_a_use]),
            _msg("user", [turn_a_result]),
        ])
        t1_id = ctx_after_t1[0]["content"][0]["id"]
        t1_result_id = ctx_after_t1[1]["content"][0]["tool_use_id"]
        assert t1_id == "toolu_00000000"
        assert t1_result_id == "toolu_00000000"

        # Transition 2 — pass the FULL history to canonicalize_turn.
        # We simulate the orchestrator-side append by combining
        # ctx_after_t1 with the new turn_b. The full-history call
        # MUST keep turn_a's ids unchanged.
        full_history = ctx_after_t1 + [
            _msg("assistant", [turn_b_use]),
        ]
        ctx_after_t2 = canonicalize_turn(full_history)
        # turn_a's ids unchanged.
        assert ctx_after_t2[0]["content"][0]["id"] == t1_id
        assert ctx_after_t2[1]["content"][0]["tool_use_id"] == t1_result_id
        # turn_b's id appended to the same counter sequence.
        assert ctx_after_t2[2]["content"][0]["id"] == "toolu_00000001"

    def test_f1_partial_history_call_collides_documented_anti_pattern(self):
        """F1 negative-path: calling canonicalize_turn over only the
        NEW turn (without the full accumulated history) collides
        with previously-canonicalized ids — the documented
        ``❌ WRONG`` anti-pattern. This test proves the anti-pattern
        DOES collide so a future contributor doesn't think the
        contract can be relaxed."""
        # First transition canonicalized turn_a → toolu_00000000.
        # Second transition (BAD: only-new-turn) canonicalizes
        # turn_b → toolu_00000000 also. COLLISION.
        bad_partial = canonicalize_turn([
            _msg("assistant", [_tool_use("toolu_02B", name="get_chunk")]),
        ])
        assert bad_partial[0]["content"][0]["id"] == "toolu_00000000"
        # If the orchestrator concatenates this with a full-history
        # ctx that ALSO has toolu_00000000, the cross-id pairing
        # is destroyed. Hence the docstring's "MUST pass full
        # history each time" warning.

    def test_f4_block_with_both_id_and_tool_use_id_maps_each_independently(self):
        """F4 fix: when a block carries BOTH ``id`` and
        ``tool_use_id`` (atypical malformed input), each field is
        mapped independently. The pre-fix code short-circuited via
        ``or`` and silently rewrote ``tool_use_id`` to the canonical
        of ``id``, destroying the pairing for any later reference
        to the original ``tool_use_id``."""
        # Block carries id=A AND tool_use_id=B (different values).
        messages = [
            _msg("assistant", [{
                "type": "tool_use",
                "id": "toolu_FIELD_ID",
                "tool_use_id": "toolu_FIELD_TUI",
                "name": "x", "input": {},
            }]),
            # Later reference to the tool_use_id value.
            _msg("user", [_tool_result("toolu_FIELD_TUI")]),
        ]
        out = canonicalize_turn(messages)
        # Two distinct source ids → two distinct canonical ids.
        block = out[0]["content"][0]
        assert block["id"] == "toolu_00000000"
        assert block["tool_use_id"] == "toolu_00000001"
        # The later tool_result reference to FIELD_TUI maps to the
        # SAME canonical as the original tool_use_id field (preserves
        # the semantic pairing).
        assert out[1]["content"][0]["tool_use_id"] == "toolu_00000001"

    def test_f10_non_list_input_raises_type_error(self):
        """F10 fix: strict type check on the input. Passing a tuple
        previously round-tripped via copy.deepcopy and returned a
        tuple — violating the documented ``list[dict]`` return type.
        Now raises TypeError."""
        with pytest.raises(TypeError, match="list\\[dict\\] input"):
            canonicalize_turn(({"role": "assistant", "content": []},))  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            canonicalize_turn("not a list")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            canonicalize_turn(None)  # type: ignore[arg-type]
