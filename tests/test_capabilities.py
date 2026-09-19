"""Capability-profile unit tests (stage2/arx-a23, WS-A A2).

Coverage map (acceptance criteria → test class):

  AC / contract                                          Test class
  ───────────────────────────────────────────────────────────────────
  Document parsing (tolerant, default synthesis)         TestParseProfilesDocument
  Bearer-token → profile resolution (AC-A.5/A.10)        TestResolveProfile
  Call-time policy: enabled/tool/notebook (AC-A.6/A.8)   TestCheckCall
  Runtime mutability via operator_settings (AC-A.7)      TestRuntimeMutability
  Denial envelope shape (lean-pattern structured error)  TestDenialPayload
  D5 source guard: no tools/list filtering anywhere      TestNoToolsListFiltering
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from server import capabilities as cap
from server.capabilities import (
    DEFAULT_PROFILE_NAME,
    DENY_NOTEBOOK,
    DENY_NOTEBOOK_REQUIRED,
    DENY_PROFILE_DISABLED,
    DENY_TOKEN_UNKNOWN,
    DENY_TOOL,
    CapabilityProfile,
    check_call,
    denial_payload,
    hash_token,
    parse_profiles_document,
    resolve_profile,
    set_capability_settings_store,
    synthesized_default_profile,
)


class _FakeSettingsStore:
    """Minimal async KV double for OperatorSettingsStore."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.get_calls = 0

    async def get(self, key: str) -> str | None:
        self.get_calls += 1
        return self.data.get(key)

    async def set(self, key: str, value: str) -> None:
        self.data[key] = value


def _doc(profiles: dict) -> str:
    return json.dumps({"format_version": 1, "profiles": profiles})


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestParseProfilesDocument:
    def test_none_or_empty_yields_synthesized_default_only(self) -> None:
        for raw in (None, "", "   "):
            profiles = parse_profiles_document(raw or None)
            assert set(profiles) == {DEFAULT_PROFILE_NAME}
            p = profiles[DEFAULT_PROFILE_NAME]
            assert p.enabled is True
            assert p.tool_allow is None
            assert p.tool_caps == {}
            assert p.notebook_allow is None
            assert p.token_sha256 is None

    def test_malformed_json_degrades_to_default_only(self) -> None:
        profiles = parse_profiles_document("{not json")
        assert set(profiles) == {DEFAULT_PROFILE_NAME}

    def test_full_profile_parses(self) -> None:
        digest = hash_token("s3cret")
        raw = _doc({
            "website": {
                "enabled": True,
                "token_sha256": digest,
                "tools": {"allow": ["search_papers", "get_chunk"]},
                "caps": {"search_papers": {"per_session": 5}, "get_chunk": 7},
                "notebooks": {"allow": ["bridgeland-stability"]},
            }
        })
        profiles = parse_profiles_document(raw)
        p = profiles["website"]
        assert p.token_sha256 == digest
        assert p.tool_allow == frozenset({"search_papers", "get_chunk"})
        # Both cap shapes (object + int shorthand) parse.
        assert p.tool_caps == {"search_papers": 5, "get_chunk": 7}
        assert p.notebook_allow == frozenset({"bridgeland-stability"})

    def test_bare_list_allowlists_accepted(self) -> None:
        raw = _doc({"p": {"tools": ["search_papers"], "notebooks": ["nb-a"]}})
        p = parse_profiles_document(raw)["p"]
        assert p.tool_allow == frozenset({"search_papers"})
        assert p.notebook_allow == frozenset({"nb-a"})

    def test_empty_allowlist_means_deny_everything_not_unrestricted(self) -> None:
        p = parse_profiles_document(_doc({"q": {"tools": {"allow": []}}}))["q"]
        assert p.tool_allow == frozenset()

    def test_invalid_cap_values_skipped(self) -> None:
        raw = _doc({"p": {"caps": {
            "search_papers": -1, "get_chunk": "five",
            "find_equation": True, "get_paper": 2,
        }}})
        p = parse_profiles_document(raw)["p"]
        assert p.tool_caps == {"get_paper": 2}

    def test_truncated_token_hash_skips_profile(self) -> None:
        raw = _doc({"weak": {"token_sha256": "abcd"}})
        profiles = parse_profiles_document(raw)
        assert "weak" not in profiles

    def test_operator_defined_default_overrides_synthesized(self) -> None:
        raw = _doc({DEFAULT_PROFILE_NAME: {"tools": {"allow": ["search_papers"]}}})
        p = parse_profiles_document(raw)[DEFAULT_PROFILE_NAME]
        assert p.tool_allow == frozenset({"search_papers"})

    def test_malformed_single_profile_skipped_others_survive(self) -> None:
        raw = _doc({"bad": "not-an-object", "good": {"enabled": False}})
        profiles = parse_profiles_document(raw)
        assert "bad" not in profiles
        assert profiles["good"].enabled is False


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


class TestResolveProfile:
    def test_no_token_resolves_default(self) -> None:
        profile, reason = asyncio.run(resolve_profile(None))
        assert reason is None
        assert profile is not None and profile.name == DEFAULT_PROFILE_NAME

    def test_matching_token_resolves_profile(self) -> None:
        store = _FakeSettingsStore()
        store.data[cap.CAPABILITY_PROFILES_KEY] = _doc(
            {"pipeline": {"token_sha256": hash_token("tok-123")}}
        )
        set_capability_settings_store(store, cache_ttl_s=0.0)
        profile, reason = asyncio.run(resolve_profile("tok-123"))
        assert reason is None
        assert profile is not None and profile.name == "pipeline"

    def test_unknown_token_fails_closed(self) -> None:
        store = _FakeSettingsStore()
        store.data[cap.CAPABILITY_PROFILES_KEY] = _doc(
            {"pipeline": {"token_sha256": hash_token("tok-123")}}
        )
        set_capability_settings_store(store, cache_ttl_s=0.0)
        profile, reason = asyncio.run(resolve_profile("wrong-token"))
        assert profile is None
        assert reason == DENY_TOKEN_UNKNOWN

    def test_disabled_profile_still_matches_token(self) -> None:
        """A disabled profile matches (denial then carries
        profile_disabled — more diagnosable than token_unknown)."""
        store = _FakeSettingsStore()
        store.data[cap.CAPABILITY_PROFILES_KEY] = _doc(
            {"off": {"enabled": False, "token_sha256": hash_token("t")}}
        )
        set_capability_settings_store(store, cache_ttl_s=0.0)
        profile, reason = asyncio.run(resolve_profile("t"))
        assert reason is None
        assert profile is not None and profile.enabled is False

    def test_store_error_fails_open_to_default(self) -> None:
        class _Boom:
            async def get(self, key: str) -> str | None:
                raise RuntimeError("db locked")

        set_capability_settings_store(_Boom(), cache_ttl_s=0.0)  # type: ignore[arg-type]
        profile, reason = asyncio.run(resolve_profile(None))
        assert reason is None
        assert profile is not None and profile.name == DEFAULT_PROFILE_NAME

    def test_hash_token_is_sha256_hex(self) -> None:
        assert hash_token("abc") == hashlib.sha256(b"abc").hexdigest()


# ---------------------------------------------------------------------------
# Call-time policy
# ---------------------------------------------------------------------------


class TestCheckCall:
    def test_default_profile_allows_everything(self) -> None:
        p = synthesized_default_profile()
        for tool in ("search_papers", "get_chunk", "lean_verify", "cite_neighbors"):
            assert check_call(p, tool, None) is None
        assert check_call(p, "search_papers", "any-notebook") is None

    def test_disabled_profile_denies_all(self) -> None:
        p = CapabilityProfile(name="off", enabled=False)
        assert check_call(p, "search_papers", None) == DENY_PROFILE_DISABLED

    def test_tool_allowlist_denies_unlisted_tool(self) -> None:
        p = CapabilityProfile(name="p", tool_allow=frozenset({"search_papers"}))
        assert check_call(p, "search_papers", None) is None
        assert check_call(p, "get_chunk", None) == DENY_TOOL

    def test_notebook_scope_denies_other_notebook(self) -> None:
        """AC-A.8: allow-listed to bridgeland-stability, calling with
        filters={'notebook': 'fourier-duality'} is denied."""
        p = CapabilityProfile(
            name="p", notebook_allow=frozenset({"bridgeland-stability"})
        )
        assert check_call(p, "search_papers", "fourier-duality") == DENY_NOTEBOOK
        assert check_call(p, "search_papers", "bridgeland-stability") is None

    def test_notebook_scoped_profile_denies_unscoped_search(self) -> None:
        """A scoped profile may not fall back to the shared corpus —
        the scope is a boundary, not a suggestion."""
        p = CapabilityProfile(name="p", notebook_allow=frozenset({"nb-a"}))
        assert check_call(p, "search_papers", None) == DENY_NOTEBOOK_REQUIRED

    def test_notebook_scope_ignores_non_routed_tools(self) -> None:
        p = CapabilityProfile(name="p", notebook_allow=frozenset({"nb-a"}))
        assert check_call(p, "get_chunk", None) is None


# ---------------------------------------------------------------------------
# Runtime mutability (AC-A.7's no-restart half at the module layer)
# ---------------------------------------------------------------------------


class TestRuntimeMutability:
    def test_store_write_changes_policy_without_rebind(self) -> None:
        async def _run() -> None:
            store = _FakeSettingsStore()
            set_capability_settings_store(store, cache_ttl_s=0.0)
            profiles = await cap.get_profiles()
            assert profiles[DEFAULT_PROFILE_NAME].tool_caps == {}

            store.data[cap.CAPABILITY_PROFILES_KEY] = _doc(
                {DEFAULT_PROFILE_NAME: {"caps": {"search_papers": 5}}}
            )
            # TTL=0 → next read sees the new document; no rebind, no restart.
            profiles = await cap.get_profiles()
            assert profiles[DEFAULT_PROFILE_NAME].tool_caps == {
                "search_papers": 5
            }

        asyncio.run(_run())

    def test_ttl_cache_serves_stale_until_invalidated(self) -> None:
        async def _run() -> None:
            store = _FakeSettingsStore()
            store.data[cap.CAPABILITY_PROFILES_KEY] = _doc({})
            set_capability_settings_store(store, cache_ttl_s=3600.0)
            await cap.get_profiles()
            reads_before = store.get_calls
            await cap.get_profiles()  # cached — no new store read
            assert store.get_calls == reads_before

            store.data[cap.CAPABILITY_PROFILES_KEY] = _doc(
                {"fresh": {"enabled": True}}
            )
            cap.invalidate_capability_cache()  # the CRUD-surface path
            profiles = await cap.get_profiles()
            assert "fresh" in profiles

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Denial payload
# ---------------------------------------------------------------------------


class TestDenialPayload:
    def test_payload_shape_matches_established_idiom(self) -> None:
        payload = denial_payload("website", "get_chunk", DENY_TOOL)
        # Both key spellings so RETRIEVAL_CAP_REACHED-parsers ("code")
        # and bootstrap-envelope-parsers ("error_code") both work.
        assert payload["code"] == "CAPABILITY_DENIED"
        assert payload["error_code"] == "CAPABILITY_DENIED"
        assert payload["denial_scope"] == DENY_TOOL
        assert payload["tool"] == "get_chunk"
        assert payload["profile"] == "website"
        assert "message" in payload

    def test_notebook_denial_names_notebook(self) -> None:
        payload = denial_payload("p", "search_papers", DENY_NOTEBOOK, "fourier-duality")
        assert payload["notebook"] == "fourier-duality"

    def test_token_unknown_payload_has_no_profile(self) -> None:
        payload = denial_payload(None, "search_papers", DENY_TOKEN_UNKNOWN)
        assert "profile" not in payload


# ---------------------------------------------------------------------------
# D5 guard — no per-profile tools/list filtering, grep-enforced
# ---------------------------------------------------------------------------


class TestNoToolsListFiltering:
    """AC-A.6: 'Per D5, no per-profile tools/list filtering exists
    anywhere in the codebase (grep-enforced).' The capability layer
    must gate at CALL TIME only — it must not even be able to see the
    tool registry."""

    _REPO_ROOT = Path(__file__).resolve().parents[1]

    def test_capability_layer_never_touches_the_tool_registry(self) -> None:
        for rel in ("server/capabilities.py", "server/routes/capabilities.py"):
            source = (self._REPO_ROOT / rel).read_text(encoding="utf-8")
            assert "ALL_TOOLS" not in source, (
                f"{rel} references ALL_TOOLS — the capability layer must "
                f"not be able to filter the tool surface (D5)"
            )
            assert "list_tools" not in source, rel

    def test_no_source_filters_tools_list_by_profile(self) -> None:
        """No server/ module may combine tools/list handling with
        profile lookups. The only file allowed to mention both words
        is this test and the docs-strings that BAN the pattern."""
        server_dir = self._REPO_ROOT / "server"
        offenders = []
        for path in server_dir.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            if "remove_tool" in text or "tools.pop(" in text:
                offenders.append(str(path))
        assert not offenders, (
            f"possible tools/list mutation found in {offenders} — per-profile "
            f"tool visibility is banned (D5; BP1 byte-stability)"
        )
