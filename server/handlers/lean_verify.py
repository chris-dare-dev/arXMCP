"""``lean_verify`` handler — kernel-backed Lean 4 verification feedback
for the autoformalizer / tactician / fixer pipeline (verification-feedback-m3).

A thin mapping layer over :class:`server.lean_repl.LeanRepl`. The
handler accepts a Lean 4 snippet + optional context imports + a
``mode`` of ``"full"`` (elaborator AND kernel) or ``"syntax_only"``
(elaborator only — wrapped in ``#check (...)``), drives one REPL
round-trip, and projects the response into the frozen schema at
``server/schemas/lean_verify_result.json`` (version 12).

**No 150-char snippet contract.** ``lean_verify`` is a verifier, not a
retriever — its result row contains no ``snippet`` field and is not
wrapped in ``<retrieved_chunk>`` delimiters. The snippet contract +
Threat-2 indirect-prompt-injection wrapping apply ONLY to tools whose
result is paper-derived text.

**Graceful unavailable.** When ``ARXMCP_ENABLE_LEAN=false`` the tool is
still registered (BP1 cache stability — every operator's ``tools/list``
bytes are identical) but ``Resources.lean_repl is None``. The handler
returns a sentinel envelope (``status: "unavailable"``,
``lean_status: "disabled"``) rather than 5xx — mirrors the
``cite_neighbors`` ``graph_status="absent"`` precedent (m1).

**Timeout = kill + respawn.** The m2 ``LeanRepl.query`` wall-clock
timeout raises ``LeanReplError`` but does NOT terminate the subprocess.
A wedged elaboration would corrupt every subsequent call (stale
stdout interleave). This handler closes the REPL on timeout and
respawns from config (the contract named in
``.claude/docs/lean-sandbox-design.md`` row "Per-query timeout":
"m3 will additionally kill+respawn the process on timeout").

Design references:
- ``.claude/notes/milestones/verification-feedback-m3/research-synthesis.md``
- ``.claude/notes/spikes/verification-feedback-spike-2.md`` (REPL JSON
  protocol — message keys ``severity``/``pos``/``data``, sorry rows
  with ``goal``/``pos``).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context
from pydantic import Field

from server.lean_repl import (
    LeanRepl,
    LeanReplError,
    LeanReplTimeoutError,
    LeanUnavailableError,
)
from server.tools import cap_result_list, envelope, get_resources

#: Severity values the schema enum accepts. An upstream REPL that ever
#: emits another category (Lean has internal ``trace`` / ``debug``
#: categories) is clamped to ``"error"`` — the safer default, since
#: silent downgrade to ``"info"`` would mask real diagnostics. m3
#: critique F2.
_ALLOWED_SEVERITIES: frozenset[str] = frozenset({"error", "warning", "info"})

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------

#: Maximum bytes accepted in the ``snippet`` input. 16 KiB is generous
#: for a single theorem + proof; bounds the per-call payload an agent
#: can submit. Threat-3 "subprocess input cap" — bounding the Lean
#: source bounds the elaboration cost (mitigates the 30 s timeout from
#: needing to fire on a million-line snippet).
MAX_SNIPPET_LEN: int = 16 * 1024

#: Maximum length of one ``import X.Y`` line. Lean module paths above
#: this length are pathological.
MAX_IMPORT_LINE_LEN: int = 256

#: Maximum number of context imports. A 64-import payload is well above
#: realistic per-snippet usage and keeps the prepended preamble bounded.
MAX_IMPORTS: int = 64


# ---------------------------------------------------------------------------
# Progress notifications (verification-feedback-m4)
# ---------------------------------------------------------------------------

#: Heartbeat cadence for ``notifications/progress`` emitted while the
#: Lean REPL is elaborating. Chosen to satisfy the spec SHOULD on
#: rate-limiting (FM-6 from the m4 synthesis — every 2–3 s is right for
#: a 5–30 s call). At 3 s a 30 s elaboration produces ~10 emissions —
#: enough heartbeat for the calling agent UI; too few to flood the SSE
#: stream.
_HEARTBEAT_INTERVAL_S: float = 3.0

#: Nominal total for the ``total`` arg on ``ctx.report_progress``. The
#: REPL's own per-query timeout is ``DEFAULT_QUERY_TIMEOUT_S = 30`` from
#: ``server.lean_repl`` — we surface the same number here so a client
#: progress bar reflects the same wall-clock budget. The reported
#: progress is capped at ``0.95`` so a slow REPL doesn't appear to
#: complete before it actually returns.
_HEARTBEAT_TOTAL_S: float = 30.0


async def _emit_progress_heartbeats(ctx: Context) -> None:
    """Emit ``notifications/progress`` every ``_HEARTBEAT_INTERVAL_S``
    seconds until cancelled.

    Runs as a separate :class:`asyncio.Task` while ``handle_lean_verify``
    awaits ``lean_repl.query``. The Lean call remains on the main
    coroutine (per the m4 synthesis §3 D1 resolution — R1's
    single-heartbeat-task pattern over R2's two-task ``asyncio.wait``
    pattern: the existing m3 ``try/except LeanReplTimeoutError`` /
    ``try/except LeanReplError`` blocks are preserved verbatim).

    **FM-1 (no client progressToken).** ``Context.report_progress`` is a
    silent no-op when the client did not include
    ``_meta.progressToken`` in the ``tools/call`` request. This is spec
    compliant and tests must explicitly mock a non-None token to
    exercise emission.

    **FM-2 (client disconnect mid-emission).** Transport errors during
    ``ctx.report_progress`` are swallowed inside the loop — a closed SSE
    channel MUST NOT propagate to the handler, kill the REPL query, or
    leak through to the caller. The Lean call continues to completion
    regardless.

    **FM-3 (post-completion emission).** The caller cancels this task in
    a ``finally`` block; the loop body's ``await asyncio.sleep`` and
    ``await ctx.report_progress`` both yield ``CancelledError`` cleanly.
    No emissions occur after ``handle_lean_verify`` returns.

    **FM-4 (monotonic progress).** A single local ``elapsed`` counter
    inside this task is the sole emitter — the spec MUST that
    ``progress`` increases is satisfied by construction.

    **FM-9 (PII).** The message string is duration-only — never
    ``snippet``, ``cmd``, or REPL response text. Logging mirrors the
    emission at INFO with the same scrubbed payload.
    """
    elapsed: float = 0.0
    while True:
        await asyncio.sleep(_HEARTBEAT_INTERVAL_S)
        elapsed += _HEARTBEAT_INTERVAL_S
        # Cap at 0.95 so a slow REPL doesn't appear complete before
        # ``query`` actually returns. The ``total`` of 30.0 lets a
        # client progress bar pace against the timeout budget.
        pct = min(elapsed / _HEARTBEAT_TOTAL_S, 0.95)
        message = f"Lean elaboration running — {elapsed:.0f}s elapsed"
        # FM-2 — never propagate transport errors to the handler.
        # A disconnected client is the SDK / session-layer's problem;
        # the REPL query must still run to completion.
        with contextlib.suppress(Exception):
            await ctx.report_progress(pct, total=_HEARTBEAT_TOTAL_S, message=message)
        # Structured ops log (m4 synthesis §4) — never includes snippet
        # (m4 FM-9 + 08-security-observability-ops §Logging: sensitive
        # fields at DEBUG only).
        logger.info(
            "lean_verify: progress heartbeat", extra={"elapsed_s": elapsed}
        )


# ---------------------------------------------------------------------------
# REPL response normalization (FM-4 from the m3 synthesis)
# ---------------------------------------------------------------------------


def _normalize_position(pos: Any) -> dict[str, int]:
    """Map a REPL ``pos`` (``{line, column}``, possibly missing) to the
    schema-required ``{line, column}`` integer pair. A missing or
    malformed position defaults to ``{0, 0}`` — the schema requires the
    field to be present + integer-valued with ``minimum: 0``, so a
    positive default is preferable to a JSON-Schema-rejecting null.

    Negative integers are clamped to ``0`` (m3 critique F5). Lean
    shouldn't emit negatives, but a future REPL build with bad
    1-vs-0-indexing or an offset-subtracting wrapper could; the schema
    cap is the contract, not the upstream output.
    """
    if isinstance(pos, dict):
        line = pos.get("line")
        column = pos.get("column")
        return {
            "line": max(0, int(line)) if isinstance(line, int) else 0,
            "column": max(0, int(column)) if isinstance(column, int) else 0,
        }
    return {"line": 0, "column": 0}


def _normalize_response(resp: dict[str, Any], mode: str) -> dict[str, Any]:
    """Project a ``LeanRepl.query`` response into the m3 schema shape.

    REPL response keys are *optional* (a clean compile returns just
    ``{"env": <int>}`` with no ``messages`` and no ``sorries``). Every
    list-valued schema field defaults to ``[]`` — not ``null`` — so
    the strict JSON Schema (``type: "array"``) holds on every path.

    Derives ``status`` and ``compilation_success`` because the upstream
    REPL emits neither — those are this handler's contract.
    """
    raw_msgs = resp.get("messages") or []
    raw_sorries = resp.get("sorries") or []

    # m3 critique F2: clamp severity to the schema enum (unknown values
    # default to "error" — the safer side; silent downgrade to "info"
    # would mask real diagnostics from a future REPL build) AND coerce
    # text / goal to ``str`` so a non-string upstream payload (a
    # structured proof-state object — an active upstream RFC) becomes a
    # string rather than a schema-violating slot.
    messages = [
        {
            "severity": (
                m.get("severity")
                if m.get("severity") in _ALLOWED_SEVERITIES
                else "error"
            ),
            "position": _normalize_position(m.get("pos")),
            "text": str(m.get("data", "")),
        }
        for m in raw_msgs
        if isinstance(m, dict)
    ]
    sorry_goals = [
        {
            "goal": str(s.get("goal", "")),
            "position": _normalize_position(s.get("pos")),
        }
        for s in raw_sorries
        if isinstance(s, dict)
    ]
    goals_remaining = [s["goal"] for s in sorry_goals if s["goal"]]

    has_error = any(m["severity"] == "error" for m in messages)
    has_sorry = bool(sorry_goals)

    if has_error:
        status = "error"
    elif has_sorry:
        status = "sorry"
    else:
        status = "ok"

    # syntax_only DID NOT run kernel verification — even a clean
    # elaboration leaves "verification success" undefined. Surface this
    # as null so the agent does not interpret a syntax-only pass as a
    # full kernel acceptance.
    if mode == "syntax_only" and status == "ok":
        compilation_success: bool | None = None
    else:
        compilation_success = status == "ok"

    return {
        "status": status,
        "messages": messages,
        "sorry_goals": sorry_goals,
        "goals_remaining": goals_remaining,
        "proof_state": goals_remaining[0] if goals_remaining else None,
        "compilation_success": compilation_success,
        "lean_status": "available",
        "mode": mode,
    }


# ---------------------------------------------------------------------------
# Disabled / timeout sentinel envelopes
# ---------------------------------------------------------------------------


def _disabled_envelope(mode: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "lean_status": "disabled",
        "mode": mode,
        "messages": [],
        "sorry_goals": [],
        "goals_remaining": [],
        "proof_state": None,
        "compilation_success": None,
    }


def _timeout_envelope(mode: str, timeout_s: float) -> dict[str, Any]:
    return {
        "status": "timeout",
        "lean_status": "timeout",
        "mode": mode,
        "messages": [
            {
                "severity": "error",
                "position": {"line": 0, "column": 0},
                "text": (
                    f"Lean REPL exceeded the {timeout_s:.0f}s per-query "
                    "timeout; the subprocess was killed and respawned. "
                    "The snippet may contain a non-terminating elaboration."
                ),
            }
        ],
        "sorry_goals": [],
        "goals_remaining": [],
        "proof_state": None,
        "compilation_success": False,
    }


# ---------------------------------------------------------------------------
# Command construction
# ---------------------------------------------------------------------------


def _build_command(snippet: str, imports: list[str], mode: str) -> str:
    """Build the ``{"cmd": ...}`` payload string sent to the REPL.

    - ``imports`` are prepended verbatim as ``import <name>`` lines (the
      REPL exposes the same surface as a ``.lean`` file).
    - ``mode == "syntax_only"`` wraps the snippet in ``#check (...)`` so
      Lean's elaborator type-checks the term WITHOUT running the full
      kernel decide-instances pipeline. The REPL has no native
      ``syntax_only`` flag — ``#check`` is the documented mechanism.
      When the snippet is a declaration (a ``theorem`` / ``def`` line —
      ``#check`` cannot wrap those), the wrapping prepends
      ``set_option maxHeartbeats 5000 in `` to short-circuit kernel work
      while preserving the declaration's type-check surface.
    """
    import_lines = "\n".join(f"import {name}" for name in imports)
    body = snippet

    if mode == "syntax_only":
        stripped = snippet.lstrip()
        if stripped.startswith(("theorem ", "def ", "lemma ", "example ")):
            # Declarations cannot be #check-wrapped — short-circuit
            # kernel work via maxHeartbeats instead.
            body = f"set_option maxHeartbeats 5000 in {snippet}"
        else:
            # Term — wrap in #check to elaborate without kernel verification.
            body = f"#check ({snippet})"

    if import_lines:
        return f"{import_lines}\n{body}"
    return body


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


async def handle_lean_verify(
    snippet: Annotated[
        str,
        Field(
            min_length=1,
            max_length=MAX_SNIPPET_LEN,
            description=(
                "Lean 4 source to verify. May be a term, a theorem "
                "declaration, or a multi-line block. Max 16 KiB."
            ),
        ),
    ],
    imports: Annotated[
        list[str] | None,
        Field(
            max_length=MAX_IMPORTS,
            description=(
                "Optional Lean module names to `import` ahead of the "
                "snippet (e.g. ['Mathlib.Algebra.Group.Defs']). Each "
                "line is bounded; resolution failures surface as "
                "messages, not exceptions."
            ),
        ),
    ] = None,
    mode: Annotated[
        Literal["full", "syntax_only"],
        Field(
            description=(
                "'full' runs elaboration AND kernel verification. "
                "'syntax_only' wraps the snippet in `#check (...)' (or "
                "set_option maxHeartbeats 5000 in <decl> for theorems) "
                "to elaborate without kernel decide-instances + "
                "reducibility — cheap pre-verify for the autoformalizer."
            ),
        ),
    ] = "full",
    # verification-feedback-m4: FastMCP-injected MCP context for emitting
    # ``notifications/progress`` heartbeats during the 5–30 s Lean
    # elaboration. FastMCP excludes ``Context``-typed parameters from
    # ``inputSchema`` via ``find_context_parameter`` →
    # ``skip_names=[ctx]`` in ``Tool.from_function``, so this addition
    # does NOT alter ``tools/list`` bytes — ``EXPECTED_TOOL_SCHEMA_SHA256``
    # is unchanged. Default ``None`` preserves backward compatibility for
    # the direct-call test sites (``asyncio.run(handle_lean_verify(...))``
    # without ``ctx``); when ``None``, the heartbeat task is not spawned.
    ctx: Context | None = None,
) -> dict[str, Any]:
    # Normalize None -> empty list (the mutable-default-arg lint).
    imports_list: list[str] = list(imports) if imports else []

    # Defense-in-depth bounds (the Pydantic Field above is the primary
    # cap; this catches a non-FastMCP caller path). m3 critique F8:
    # enforce the LIST length too, not only the per-line length — the
    # docstring above justifies the loop with "catches a non-FastMCP
    # caller path", which would include direct calls passing a 100k-
    # element list that bypass Pydantic's max_length.
    if len(imports_list) > MAX_IMPORTS:
        raise ValueError(
            f"imports list too long (max {MAX_IMPORTS} entries; got "
            f"{len(imports_list)})"
        )
    for line in imports_list:
        if not isinstance(line, str) or len(line) > MAX_IMPORT_LINE_LEN:
            raise ValueError(
                f"import line too long or non-string (max "
                f"{MAX_IMPORT_LINE_LEN} chars): {line!r}"
            )

    resources = get_resources()
    lean_repl = resources.lean_repl

    # FM-7 (graceful unavailable) — ARXMCP_ENABLE_LEAN=false leaves the
    # tool registered (BP1 stability) but Resources.lean_repl is None.
    if lean_repl is None:
        return envelope(_disabled_envelope(mode))

    cmd = _build_command(snippet, imports_list, mode)

    # verification-feedback-m4 — spawn a heartbeat task ONLY when a
    # FastMCP-injected ``ctx`` is present. Direct-call test sites pass
    # ``ctx=None`` and skip emission entirely. The Lean call remains on
    # the main coroutine path (m4 synthesis §3 D1 — preserves the m3
    # ``try/except LeanReplTimeoutError`` / ``try/except LeanReplError``
    # structure verbatim). The ``try/finally`` below guarantees the
    # heartbeat task is cancelled on EVERY exit path — success (FM-3),
    # timeout (FM-7), and other ``LeanReplError`` variants (FM-7).
    heartbeat_task: asyncio.Task[None] | None = None
    if ctx is not None:
        heartbeat_task = asyncio.create_task(_emit_progress_heartbeats(ctx))

    try:
        try:
            resp = await lean_repl.query({"cmd": cmd})
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task
    except LeanReplTimeoutError as exc:
        # FM-2 / m3 critique F3 — kill + respawn so the next call
        # doesn't read this call's stale stdout. The lean-sandbox-design
        # contract. Distinct exception class so the discriminator is the
        # type, not a substring match on the message.
        from server.lean_repl import DEFAULT_QUERY_TIMEOUT_S

        logger.warning(
            "lean_verify: REPL timed out — closing and respawning (%s)", exc
        )
        # m3 critique F4 — narrow the bare-except. The teardown is
        # best-effort (close on an already-wedged process can legitimately
        # raise OSError / LeanReplError); CancelledError MUST propagate.
        try:
            await lean_repl.close()
        except (OSError, LeanReplError):
            logger.exception("lean_verify: REPL close after timeout failed")
        try:
            resources.lean_repl = await LeanRepl.spawn_from_config(
                resources.config
            )
        except (LeanUnavailableError, OSError):
            logger.exception(
                "lean_verify: respawn after timeout failed; "
                "subsequent calls degrade to 'unavailable'"
            )
            resources.lean_repl = None
        return envelope(_timeout_envelope(mode, DEFAULT_QUERY_TIMEOUT_S))
    except LeanReplError as exc:
        # Any other LeanReplError (process exited, non-JSON response,
        # etc.) — surface as an error envelope, do NOT raise (the agent
        # gets a usable response with the error message).
        logger.warning("lean_verify: REPL error: %s", exc)
        return envelope(
            {
                "status": "error",
                "lean_status": "available",
                "mode": mode,
                "messages": [
                    {
                        "severity": "error",
                        "position": {"line": 0, "column": 0},
                        "text": f"Lean REPL error: {exc}",
                    }
                ],
                "sorry_goals": [],
                "goals_remaining": [],
                "proof_state": None,
                "compilation_success": False,
            }
        )

    payload = _normalize_response(resp, mode)
    # Multi-result cap surface — long elaborations can emit hundreds of
    # diagnostic rows; cap_result_list trims the trailing entries from
    # the messages array if the envelope exceeds Config.result_byte_cap.
    capped, _blocks = cap_result_list(envelope(payload), list_key="messages")
    return capped
