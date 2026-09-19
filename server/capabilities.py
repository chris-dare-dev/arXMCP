"""Capability profiles — per-caller tool/notebook/cap policy (stage2/arx-a23, WS-A A2).

Implements the capability-configuration layer from the Stage-1 target
architecture (§6 "Capability configuration and authz model"):

- **Profiles live in ``operator_settings``** (the runtime-mutable SQLite
  KV co-resident in ``notebooks.db``) under the single JSON key
  :data:`CAPABILITY_PROFILES_KEY`. One key, one atomic write — the
  operator (or the ``/api/v1/capabilities`` CRUD surface) replaces the
  whole document; a short TTL read-through cache in this module makes
  changes effective **without a server restart** (AC-A.7).
- **Per-profile policy:** tool allowlist, per-tool per-session caps
  (superseding the hardcoded 3-search/4-chunk constants in
  :mod:`server.session`), notebook scope allowlist, enabled toggle,
  and a **SHA-256 token hash** (never the token value — AC-A.10).
- **Bearer-token → profile resolution** for
  :class:`server.middleware.CapabilityMiddleware`. Unauthenticated
  loopback callers map to the synthesized ``default`` profile, which
  preserves current behavior byte-for-byte on day one (AC-A.5): all
  tools allowed, legacy caps, no notebook scoping.
- **The inviolable constraint (adjudication D5):** nothing in this
  module — or anywhere else — filters ``tools/list`` per profile.
  Enforcement is CALL-TIME ONLY, via structured JSON-RPC denial
  envelopes in the shipped ``ARXMCP_ENABLE_LEAN`` /
  ``RETRIEVAL_CAP_REACHED`` idiom. This module deliberately does NOT
  import the tool registry from :mod:`server.tools` (grep-enforced by
  ``tests/test_capabilities.py::TestNoToolsListFiltering``); a
  profile may allowlist a tool name the server has never heard of
  (it will simply never match), and an unknown tool called under a
  wildcard profile is FastMCP's problem, exactly as today.

**No OAuth** (target-architecture §6): the MCP 2025-06-18 spec makes
authorization optional for local/stdio deployments and points them at
environment credentials. The shim's ``--token-env`` flag is the
credential channel; revisit only if the server ever leaves loopback.

**Failure discipline:** mirrors :class:`SessionCapMiddleware` — an
unreadable/malformed profile document degrades to the synthesized
``default`` profile with a WARN (the worst case is day-one behavior,
not an outage). Presenting an UNKNOWN bearer token, however, is
fail-closed (``token_unknown`` denial): an explicit credential that
matches no profile is a misconfiguration the caller must see.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from server.operator_settings import OperatorSettingsStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The single ``operator_settings`` key holding the whole capability-
#: profiles document (JSON). One key keeps writes atomic (SQLite row
#: replace) and enumeration trivial (the KV store has no key-scan API).
CAPABILITY_PROFILES_KEY: str = "capability_profiles"

#: Document schema version. Bump with a documented migration only.
CAPABILITY_DOC_VERSION: int = 1

#: Name of the profile unauthenticated loopback callers resolve to.
DEFAULT_PROFILE_NAME: str = "default"

#: Denial reasons (the ``denial_scope`` axis of the envelope). Frozen
#: vocabulary — tests and consumers switch on these strings.
DENY_TOKEN_UNKNOWN: str = "token_unknown"
DENY_PROFILE_DISABLED: str = "profile_disabled"
DENY_TOOL: str = "tool_not_allowed"
DENY_NOTEBOOK: str = "notebook_not_allowed"
DENY_NOTEBOOK_REQUIRED: str = "notebook_scope_required"

#: The wire ``error_code`` for every capability denial (one code, the
#: ``denial_scope`` field carries the specific reason — mirrors the
#: single ``RETRIEVAL_CAP_REACHED`` code with structured detail).
CAPABILITY_DENIED_CODE: str = "CAPABILITY_DENIED"

#: Default TTL for the profile read-through cache, seconds. Small
#: enough that "runtime-mutable" holds for any human operator loop
#: (AC-A.7); large enough that a tool-call burst does not hammer
#: SQLite. Overridden by ``Config.capability_cache_ttl_s`` at wiring
#: time (``server/main.py`` lifespan).
DEFAULT_CACHE_TTL_S: float = 1.0


# ---------------------------------------------------------------------------
# ContextVars — capability facts for the in-flight request
# ---------------------------------------------------------------------------

#: Profile name resolved for the in-flight ``tools/call`` request. Set
#: by :class:`server.middleware.CapabilityMiddleware`; read by the
#: audit/event emitters in :func:`server.tools._wrap_with_observability`.
current_profile_name: ContextVar[str | None] = ContextVar(
    "current_profile_name", default=None
)

#: ``filters.notebook`` value parsed from the in-flight ``tools/call``
#: arguments (None when unscoped / not applicable). Set by the same
#: middleware; consumed by the audit row + request event.
current_notebook: ContextVar[str | None] = ContextVar(
    "current_notebook", default=None
)


# ---------------------------------------------------------------------------
# Profile model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CapabilityProfile:
    """One immutable, parsed capability profile.

    ``None`` for :attr:`tool_allow` / :attr:`notebook_allow` means
    "unrestricted" — distinct from an EMPTY set, which means "deny
    everything" (a valid operator choice for a quarantined token).
    """

    name: str
    enabled: bool = True
    #: SHA-256 hex digest of the bearer token, or None for the
    #: token-less default profile. NEVER the token value (AC-A.10).
    token_sha256: str | None = None
    #: Allowed tool names; None = all tools.
    tool_allow: frozenset[str] | None = None
    #: Per-tool per-session cap overrides (tool name → max calls per
    #: MCP session). Tools absent from this mapping fall back to the
    #: legacy constants in :mod:`server.session` (3 search / 4 chunk;
    #: uncapped otherwise).
    tool_caps: dict[str, int] = field(default_factory=dict)
    #: Allowed notebook slugs for notebook-routed retrieval; None =
    #: all notebooks INCLUDING the shared corpus (unscoped calls).
    notebook_allow: frozenset[str] | None = None


def synthesized_default_profile() -> CapabilityProfile:
    """The day-one ``default`` profile: current behavior, unchanged.

    Used when the operator has not defined a ``default`` profile in
    the store (the normal case) and as the fail-open degradation when
    the profile document is unreadable.
    """
    return CapabilityProfile(name=DEFAULT_PROFILE_NAME)


# ---------------------------------------------------------------------------
# Document parsing (tolerant — malformed entries are skipped w/ WARN)
# ---------------------------------------------------------------------------


def _parse_tool_caps(raw: Any, profile_name: str) -> dict[str, int]:
    """Parse the ``caps`` member. Accepts two shapes per tool:

    - shorthand int: ``{"search_papers": 5}``
    - object: ``{"search_papers": {"per_session": 5}}``

    Non-int / negative values are skipped with a WARN.
    """
    caps: dict[str, int] = {}
    if not isinstance(raw, dict):
        return caps
    for tool, value in raw.items():
        limit: Any = value
        if isinstance(value, dict):
            limit = value.get("per_session")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            logger.warning(
                "capability profile %r: cap for tool %r is invalid (%r); "
                "ignoring this cap",
                profile_name, tool, value,
            )
            continue
        caps[str(tool)] = limit
    return caps


def _parse_allow_list(raw: Any, member: str, profile_name: str) -> frozenset[str] | None:
    """Parse ``tools`` / ``notebooks`` members: ``{"allow": [...]}`` or
    a bare list. ``None`` / absent → unrestricted."""
    if raw is None:
        return None
    values = raw
    if isinstance(raw, dict):
        values = raw.get("allow")
        if values is None:
            return None
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        logger.warning(
            "capability profile %r: %s allowlist is malformed (%r); "
            "treating as unrestricted",
            profile_name, member, raw,
        )
        return None
    return frozenset(values)


def parse_profiles_document(raw_json: str | None) -> dict[str, CapabilityProfile]:
    """Parse the stored JSON document into a name → profile map.

    Always returns a map containing ``default`` (synthesized when not
    operator-defined). Malformed documents degrade to default-only
    with a WARN (fail-open to day-one behavior); malformed individual
    profiles are skipped with a WARN so one bad entry cannot take the
    whole policy layer down.
    """
    profiles: dict[str, CapabilityProfile] = {}
    if raw_json:
        try:
            doc = json.loads(raw_json)
            entries = doc.get("profiles", {}) if isinstance(doc, dict) else {}
            if not isinstance(entries, dict):
                raise ValueError("'profiles' member is not an object")
            for name, entry in entries.items():
                if not isinstance(entry, dict):
                    logger.warning(
                        "capability profile %r is not an object; skipping", name
                    )
                    continue
                token_hash = entry.get("token_sha256")
                if token_hash is not None and not (
                    isinstance(token_hash, str) and len(token_hash) == 64
                ):
                    logger.warning(
                        "capability profile %r: token_sha256 is not a "
                        "64-char hex digest; skipping the profile "
                        "(a truncated hash would weaken token matching)",
                        name,
                    )
                    continue
                profiles[str(name)] = CapabilityProfile(
                    name=str(name),
                    enabled=bool(entry.get("enabled", True)),
                    token_sha256=token_hash.lower() if token_hash else None,
                    tool_allow=_parse_allow_list(entry.get("tools"), "tools", name),
                    tool_caps=_parse_tool_caps(entry.get("caps"), name),
                    notebook_allow=_parse_allow_list(
                        entry.get("notebooks"), "notebooks", name
                    ),
                )
        except (ValueError, TypeError) as exc:
            logger.warning(
                "capability_profiles document is malformed (%s); degrading "
                "to the synthesized default profile only", exc,
            )
            profiles = {}
    if DEFAULT_PROFILE_NAME not in profiles:
        profiles[DEFAULT_PROFILE_NAME] = synthesized_default_profile()
    return profiles


# ---------------------------------------------------------------------------
# Store binding + TTL read-through cache
# ---------------------------------------------------------------------------

_SETTINGS_STORE: OperatorSettingsStore | None = None
_CACHE_TTL_S: float = DEFAULT_CACHE_TTL_S
_cache_lock = asyncio.Lock()
_cached_profiles: dict[str, CapabilityProfile] | None = None
_cached_at: float = 0.0


def set_capability_settings_store(
    store: OperatorSettingsStore | None, *, cache_ttl_s: float | None = None
) -> None:
    """Bind the live :class:`OperatorSettingsStore` (lifespan wiring).

    ``None`` unbinds (tests / shutdown); resolution then serves the
    synthesized default profile only. Also invalidates the cache.
    """
    global _SETTINGS_STORE, _CACHE_TTL_S, _cached_profiles, _cached_at
    _SETTINGS_STORE = store
    if cache_ttl_s is not None:
        _CACHE_TTL_S = max(0.0, cache_ttl_s)
    _cached_profiles = None
    _cached_at = 0.0


def invalidate_capability_cache() -> None:
    """Drop the TTL cache so the next resolution re-reads the store.

    Called by the ``/api/v1/capabilities`` CRUD handlers after a write
    so API-driven changes are effective immediately (direct SQLite
    writes converge within the TTL)."""
    global _cached_profiles, _cached_at
    _cached_profiles = None
    _cached_at = 0.0


def reset_capabilities_for_tests() -> None:
    """Test hook — unbind the store and drop the cache."""
    set_capability_settings_store(None, cache_ttl_s=DEFAULT_CACHE_TTL_S)


async def get_profiles() -> dict[str, CapabilityProfile]:
    """Return the current profile map (read-through TTL cache).

    Store-unbound (tests without lifespan; early startup) → the
    synthesized default only. Store errors degrade the same way with
    a WARN — the capability layer must never take the server down.
    """
    global _cached_profiles, _cached_at
    now = time.monotonic()
    cached = _cached_profiles
    if cached is not None and (now - _cached_at) < _CACHE_TTL_S:
        return cached
    async with _cache_lock:
        # Double-check under the lock (another task may have refreshed).
        now = time.monotonic()
        if _cached_profiles is not None and (now - _cached_at) < _CACHE_TTL_S:
            return _cached_profiles
        store = _SETTINGS_STORE
        raw: str | None = None
        if store is not None:
            try:
                raw = await store.get(CAPABILITY_PROFILES_KEY)
            except Exception:  # noqa: BLE001 — fail open to default (see module docstring)
                logger.warning(
                    "capability_profiles read failed; degrading to the "
                    "synthesized default profile", exc_info=True,
                )
        _cached_profiles = parse_profiles_document(raw)
        _cached_at = time.monotonic()
        return _cached_profiles


# ---------------------------------------------------------------------------
# Resolution + enforcement
# ---------------------------------------------------------------------------


def hash_token(token: str) -> str:
    """SHA-256 hex digest of a bearer token — the ONLY form ever
    persisted or compared (AC-A.10)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def resolve_profile(
    bearer_token: str | None,
) -> tuple[CapabilityProfile | None, str | None]:
    """Resolve a bearer token to a profile.

    Returns ``(profile, None)`` on success or ``(None, DENY_TOKEN_UNKNOWN)``
    when an explicit token matches no enabled-or-disabled profile.
    (A DISABLED profile still MATCHES — the denial then carries
    ``profile_disabled``, which is more diagnosable than
    ``token_unknown``.)

    Token comparison is constant-time (``hmac.compare_digest``) over
    the hex digests. The token value itself is never logged (AC-A.10).
    """
    profiles = await get_profiles()
    if bearer_token is None:
        return profiles[DEFAULT_PROFILE_NAME], None
    digest = hash_token(bearer_token)
    for profile in profiles.values():
        if profile.token_sha256 is not None and hmac.compare_digest(
            profile.token_sha256, digest
        ):
            return profile, None
    logger.warning(
        "capability: bearer token (sha256=%s...) matches no profile; "
        "denying", digest[:12],
    )
    return None, DENY_TOKEN_UNKNOWN


#: Tools whose ``arguments.filters.notebook`` routes retrieval to a
#: per-notebook corpus (today: only ``search_papers`` — see
#: ``server/handlers/search.py`` ``_ROUTING_FILTER_KEYS``). Notebook
#: scope enforcement applies to these tools; other tools carry no
#: notebook designation at the call boundary (documented limitation:
#: ``get_chunk`` by chunk_id is not notebook-attributable pre-lookup).
NOTEBOOK_ROUTED_TOOLS: frozenset[str] = frozenset({"search_papers"})


def check_call(
    profile: CapabilityProfile,
    tool_name: str,
    notebook: str | None,
) -> str | None:
    """Return a denial reason for this call under ``profile``, or
    ``None`` when the call is allowed.

    Order: enabled toggle → tool allowlist → notebook scope. The
    notebook rule is STRICT for scoped profiles: a profile with a
    notebook allowlist may neither name another notebook (AC-A.8) nor
    fall back to the shared corpus via an unscoped retrieval call —
    an unscoped ``search_papers`` under a scoped profile is denied
    with :data:`DENY_NOTEBOOK_REQUIRED` (otherwise the scope would be
    a suggestion, not a boundary).
    """
    if not profile.enabled:
        return DENY_PROFILE_DISABLED
    if profile.tool_allow is not None and tool_name not in profile.tool_allow:
        return DENY_TOOL
    if profile.notebook_allow is not None and tool_name in NOTEBOOK_ROUTED_TOOLS:
        if notebook is None:
            return DENY_NOTEBOOK_REQUIRED
        if notebook not in profile.notebook_allow:
            return DENY_NOTEBOOK
    return None


def denial_payload(
    profile_name: str | None,
    tool_name: str,
    reason: str,
    notebook: str | None = None,
) -> dict[str, Any]:
    """Build the structured denial payload (single wire shape).

    Mirrors the ``RETRIEVAL_CAP_REACHED`` idiom (``code`` +
    human-readable ``message`` + machine fields) and the bootstrap
    envelope's ``error_code`` naming, so consumers of either idiom
    parse this envelope without new code paths.
    """
    messages = {
        DENY_TOKEN_UNKNOWN: (
            "the presented bearer token matches no capability profile; "
            "check the token env var wired via the shim's --token-env"
        ),
        DENY_PROFILE_DISABLED: (
            f"capability profile {profile_name!r} is disabled by the "
            f"operator; no tool calls are permitted under its token"
        ),
        DENY_TOOL: (
            f"tool {tool_name!r} is not in the allowlist of capability "
            f"profile {profile_name!r}"
        ),
        DENY_NOTEBOOK: (
            f"notebook {notebook!r} is not in the notebook allowlist of "
            f"capability profile {profile_name!r}"
        ),
        DENY_NOTEBOOK_REQUIRED: (
            f"capability profile {profile_name!r} is notebook-scoped; "
            f"{tool_name} calls must carry filters={{'notebook': <slug>}} "
            f"naming an allowed notebook"
        ),
    }
    payload: dict[str, Any] = {
        "code": CAPABILITY_DENIED_CODE,
        "error_code": CAPABILITY_DENIED_CODE,
        "denial_scope": reason,
        "message": messages.get(reason, f"capability denial: {reason}"),
        "tool": tool_name,
    }
    if profile_name is not None:
        payload["profile"] = profile_name
    if notebook is not None:
        payload["notebook"] = notebook
    return payload


# ---------------------------------------------------------------------------
# Document write helpers (used by the /api/v1 CRUD surface)
# ---------------------------------------------------------------------------


async def read_raw_document() -> dict[str, Any]:
    """Return the stored document (or an empty skeleton). RAW form —
    token hashes included, token values structurally impossible."""
    store = _SETTINGS_STORE
    raw: str | None = None
    if store is not None:
        raw = await store.get(CAPABILITY_PROFILES_KEY)
    if raw:
        try:
            doc = json.loads(raw)
            if isinstance(doc, dict) and isinstance(doc.get("profiles"), dict):
                return doc
        except ValueError:
            logger.warning("capability_profiles document unparseable; serving skeleton")
    return {"format_version": CAPABILITY_DOC_VERSION, "profiles": {}}


async def write_raw_document(doc: dict[str, Any]) -> None:
    """Persist ``doc`` (sorted keys) and invalidate the cache.

    Raises ``RuntimeError`` when no store is bound — the CRUD surface
    translates that to a 503 (server not fully started)."""
    store = _SETTINGS_STORE
    if store is None:
        raise RuntimeError("operator_settings store is not bound (startup incomplete)")
    await store.set(
        CAPABILITY_PROFILES_KEY,
        json.dumps(doc, sort_keys=True, ensure_ascii=True),
    )
    invalidate_capability_cache()


__all__ = [
    "CAPABILITY_DENIED_CODE",
    "CAPABILITY_DOC_VERSION",
    "CAPABILITY_PROFILES_KEY",
    "DEFAULT_PROFILE_NAME",
    "DENY_NOTEBOOK",
    "DENY_NOTEBOOK_REQUIRED",
    "DENY_PROFILE_DISABLED",
    "DENY_TOKEN_UNKNOWN",
    "DENY_TOOL",
    "NOTEBOOK_ROUTED_TOOLS",
    "CapabilityProfile",
    "check_call",
    "current_notebook",
    "current_profile_name",
    "denial_payload",
    "get_profiles",
    "hash_token",
    "invalidate_capability_cache",
    "parse_profiles_document",
    "read_raw_document",
    "reset_capabilities_for_tests",
    "resolve_profile",
    "set_capability_settings_store",
    "synthesized_default_profile",
    "write_raw_document",
]
