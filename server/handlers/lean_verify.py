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
import math
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context
from pydantic import Field

from server.lean_repl import (
    DEFAULT_QUERY_TIMEOUT_S,
    LeanRepl,
    LeanReplError,
    LeanReplTimeoutError,
    LeanUnavailableError,
)
from server.lean_soundness import (
    SnippetScan,
    closure_ok,
    extract_decl_names,
    parse_check_type_output,
    parse_print_axioms_output,
    read_repl_provenance,
    scan_snippet,
    transcript_sha256,
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


def _heartbeat_progress(elapsed: float) -> float:
    """Map ``elapsed`` seconds to a strictly-monotonic ``progress`` value
    in ``[0, 1)`` for ``Context.report_progress``.

    The MCP 2025-06-18 spec MUST: *"The ``progress`` value MUST increase
    with each notification, even if the total is unknown."* A naive
    ``min(elapsed / total, 0.95)`` cap (the m4 first-pass implementation)
    plateaus at ``0.95`` once ``elapsed >= 0.95 * total`` — a MUST
    violation by construction the moment any future milestone raises
    ``DEFAULT_QUERY_TIMEOUT_S`` (m4 critique F1). An asymptotic taper
    ``1 - exp(-elapsed / total)`` is strictly monotonic for all positive
    ``elapsed`` AND strictly less than 1, so a slow REPL never appears
    complete before ``query`` returns. We pin ``total`` to
    ``DEFAULT_QUERY_TIMEOUT_S`` (the only source of truth for the REPL
    wall-clock budget — m4 critique F2) so a future timeout bump scales
    the taper accordingly without further code change.
    """
    return 1.0 - math.exp(-elapsed / DEFAULT_QUERY_TIMEOUT_S)


def _has_progress_token(ctx: Context) -> bool:
    """Return ``True`` iff the calling agent's ``tools/call`` request
    included ``_meta.progressToken``.

    Without a token, ``Context.report_progress`` is a documented silent
    no-op (FastMCP ``server.py``: ``if progress_token is None: return``)
    — spawning the heartbeat task is pure overhead AND would spam the
    INFO log with "heartbeat fired" lines that document emissions that
    never happened (m4 critique F3). This guard lets us skip the
    heartbeat entirely on the dominant prod path where the client did
    not opt in to progress.

    Any AttributeError / ValueError on the introspection chain is
    treated as "no token" — defensive against test shims that don't
    model the full ``request_context.meta.progressToken`` chain.
    """
    try:
        return ctx.request_context.meta.progressToken is not None
    except (AttributeError, ValueError):
        return False


async def _emit_progress_heartbeats(ctx: Context) -> None:
    """Emit ``notifications/progress`` every ``_HEARTBEAT_INTERVAL_S``
    seconds until cancelled.

    Runs as a separate :class:`asyncio.Task` while ``handle_lean_verify``
    awaits ``lean_repl.query``. The Lean call remains on the main
    coroutine (per the m4 synthesis §3 D1 resolution — R1's
    single-heartbeat-task pattern over R2's two-task ``asyncio.wait``
    pattern: the existing m3 ``try/except LeanReplTimeoutError`` /
    ``try/except LeanReplError`` blocks are preserved verbatim).

    **FM-1 (no client progressToken).** The caller skips spawning this
    task entirely when ``_has_progress_token(ctx)`` is False (m4
    critique F3). Defense-in-depth is the FastMCP no-op behaviour inside
    ``report_progress`` itself.

    **FM-2 (client disconnect mid-emission).** Transport errors during
    ``ctx.report_progress`` are caught, logged at WARN, and not
    propagated to the handler — a closed SSE channel MUST NOT kill the
    REPL query or leak through to the caller. ``CancelledError`` is a
    ``BaseException`` subclass on Python 3.8+, so the bare ``Exception``
    catch correctly does NOT swallow cancellation; this is what lets the
    ``finally``-cancel discipline in ``handle_lean_verify`` work (m4
    critique "What was done well").

    **FM-3 (post-completion emission).** The caller cancels this task in
    a ``finally`` block; the loop body's ``await asyncio.sleep`` and
    ``await ctx.report_progress`` both yield ``CancelledError`` cleanly.
    No emissions occur after ``handle_lean_verify`` returns.

    **FM-4 (monotonic progress).** A single local ``elapsed`` counter
    feeds ``_heartbeat_progress`` (an asymptotic taper); the emitted
    ``progress`` is STRICTLY increasing by construction — the m4
    critique F1 plateau-at-0.95 bug is fixed (the asymptote ``1 -
    exp(-elapsed / total)`` is strictly monotonic on ``[0, ∞)``).

    **FM-9 (PII).** The message string is duration-only — never
    ``snippet``, ``cmd``, or REPL response text. The structured INFO log
    fires ONLY on actual emission success (m4 critique F3 — silent
    swallow + unconditional INFO was misleading).
    """
    elapsed: float = 0.0
    while True:
        await asyncio.sleep(_HEARTBEAT_INTERVAL_S)
        elapsed += _HEARTBEAT_INTERVAL_S
        pct = _heartbeat_progress(elapsed)
        message = f"Lean elaboration running — {elapsed:.0f}s elapsed"
        emitted = False
        try:
            await ctx.report_progress(
                pct, total=DEFAULT_QUERY_TIMEOUT_S, message=message
            )
            emitted = True
        except Exception:
            # FM-2 — never propagate transport errors to the handler.
            # A disconnected client is the SDK / session-layer's problem;
            # the REPL query must still run to completion. WARN so ops
            # sees the SSE-close signal (m4 critique F3 — silent swallow
            # + INFO "heartbeat fired" was misleading).
            logger.warning(
                "lean_verify: progress emission failed "
                "(client disconnect?)",
                exc_info=True,
            )
        # Structured ops log (m4 synthesis §4) — only on actual
        # emission success, so the INFO line documents a real
        # notification, not a no-op (m4 critique F3). Never includes
        # snippet (m4 FM-9 + 08-security-observability-ops §Logging:
        # sensitive fields at DEBUG only).
        if emitted:
            logger.info(
                "lean_verify: progress heartbeat",
                extra={"elapsed_s": elapsed},
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
# D-2 soundness hardening (stage2/arx-d2; finding 05 §3-R2; RISKS MA-2)
# ---------------------------------------------------------------------------


def _soundness_block(
    scan: SnippetScan,
    *,
    audit_status: str,
    audit_detail: str | None = None,
    audited_decls: list[str] | None = None,
    axioms_by_decl: dict[str, list[str]] | None = None,
    guard: str = "passed",
) -> dict[str, Any]:
    """Build the ``soundness`` sub-envelope carried by every result.

    ``axiom_closure_ok`` semantics are fail-closed: ``True`` only when
    the audit ran to completion AND the closure is within the standard
    trust base; ``False`` when the audit failed or the snippet was
    rejected; ``None`` when the audit was legitimately not applicable
    (syntax_only, non-ok status, REPL disabled/timeout).
    """
    if axioms_by_decl is not None:
        closure: list[str] | None = sorted(
            {a for axs in axioms_by_decl.values() for a in axs}
        )
    else:
        closure = None
    if audit_status == "ok" and closure is not None:
        ok: bool | None = closure_ok(closure)
    elif audit_status in ("failed", "rejected"):
        ok = False
    else:
        ok = None
    return {
        "guard": guard,
        "rejected_keywords": list(scan.rejected_keywords),
        "flags": list(scan.flags),
        "audit_status": audit_status,
        "audit_detail": audit_detail,
        "audited_decls": list(audited_decls or []),
        "axioms_by_decl": axioms_by_decl,
        "axiom_closure": closure,
        "axiom_closure_ok": ok,
    }


async def _kill_and_respawn(resources: Any, lean_repl: Any) -> None:
    """Close a wedged REPL and respawn from config (FM-2 / m3 F3).

    Shared by the main-query timeout path and the axiom-audit timeout
    path — a timed-out audit query wedges the REPL stdout exactly like
    a timed-out verification query does.
    """
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


async def _audit_axioms(
    lean_repl: Any,
    env_id: Any,
    decl_names: list[str],
) -> tuple[str, str | None, dict[str, list[str]] | None]:
    """Run ``#print axioms <decl>`` for every audited declaration.

    Executes in the environment produced by the verification command
    (``env_id``), so the audited declarations are exactly the ones the
    kernel just accepted. Returns ``(audit_status, detail,
    axioms_by_decl)``; any unparseable or errored response fails the
    whole audit (fail closed — an award must never rest on a partial
    audit). ``LeanReplError`` / ``LeanReplTimeoutError`` propagate to
    the caller, which owns the respawn discipline.
    """
    if not isinstance(env_id, int):
        return (
            "failed",
            "verification response carried no env id to audit against",
            None,
        )
    axioms_by_decl: dict[str, list[str]] = {}
    for name in decl_names:
        resp = await lean_repl.query(
            {"cmd": f"#print axioms {name}", "env": env_id}
        )
        msgs = [m for m in (resp.get("messages") or []) if isinstance(m, dict)]
        err = next(
            (m for m in msgs if m.get("severity") == "error"), None
        )
        if err is not None:
            return (
                "failed",
                f"#print axioms {name} errored: "
                f"{str(err.get('data', ''))[:200]}",
                None,
            )
        parsed: list[str] | None = None
        for m in msgs:
            parsed = parse_print_axioms_output(str(m.get("data", "")))
            if parsed is not None:
                break
        if parsed is None:
            return (
                "failed",
                f"#print axioms {name} returned no parseable axiom list",
                None,
            )
        axioms_by_decl[name] = parsed
    return "ok", None, axioms_by_decl


async def _audit_statements(
    lean_repl: Any,
    env_id: Any,
    decl_names: list[str],
) -> dict[str, str]:
    """Run ``#check @<decl>`` for every audited declaration and parse the
    fully-elaborated KERNEL type (durable P1 soundness fix — the proved
    proposition comes from the kernel, never from re-parsing author
    source).

    Executes in the environment produced by the verification command
    (``env_id``), so the reported types are exactly what the kernel
    accepted — a phantom declaration hidden in a comment or a string
    literal is invisible to the kernel and ``#check @<that name>`` errors,
    so it never enters the map (spike p1-step-1). Returns ``{name:
    kernel_type_str}`` for the names that parsed; fail-closed — a name
    whose ``#check`` errors or whose output does not parse is simply
    OMITTED (a linkage that cannot find its declaration's kernel type
    fails closed downstream). NEVER raises for a per-name miss; only a
    hard ``LeanReplError`` / ``LeanReplTimeoutError`` (process wedged)
    propagates to the caller, which owns the respawn discipline —
    identical to :func:`_audit_axioms`.

    Independent of the axiom audit's pass/fail: the statement map is
    additive evidence for the verdict-linkage choke-point and does not
    gate the ``proven-formal`` axiom-closure award.
    """
    if not isinstance(env_id, int):
        return {}
    statements: dict[str, str] = {}
    for name in decl_names:
        resp = await lean_repl.query({"cmd": f"#check @{name}", "env": env_id})
        msgs = [m for m in (resp.get("messages") or []) if isinstance(m, dict)]
        # An error-severity message (e.g. "Unknown identifier") means the
        # kernel does not know this name in this env — omit it (fail-
        # closed). This is the load-bearing property: comment/string-
        # literal phantoms and anonymous examples produce no entry.
        if any(m.get("severity") == "error" for m in msgs):
            continue
        parsed: str | None = None
        for m in msgs:
            parsed = parse_check_type_output(str(m.get("data", "")), name)
            if parsed is not None:
                break
        if parsed is not None:
            statements[name] = parsed
    return statements


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

    # D-2 soundness instrumentation (stage2/arx-d2). The scan and the
    # provenance pins are computed up front so EVERY exit path —
    # rejected, disabled, timeout, error, success — carries the same
    # soundness + provenance blocks (the result schema requires them).
    scan = scan_snippet(snippet)
    lean_toolchain, mathlib_rev = read_repl_provenance(
        resources.config.lean_repl_dir
    )

    def _finish(
        payload: dict[str, Any],
        soundness: dict[str, Any],
        kernel_statements: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Attach soundness + provenance + kernel_statements, hash the
        transcript, envelope.

        ``kernel_statements`` (durable P1 soundness fix) maps each audited
        declaration name to its fully-elaborated KERNEL type; present on
        EVERY exit path (defaults to ``{}`` for rejected/disabled/timeout/
        error/syntax-only/non-ok results — the schema requires the field).
        It is the authoritative source the verdict-linkage choke-point
        consumes for statement linkage, replacing the retired
        author-source text scan.
        """
        payload = {**payload, "soundness": soundness}
        payload["kernel_statements"] = dict(kernel_statements or {})
        payload["provenance"] = {
            "lean_toolchain": lean_toolchain,
            "mathlib_rev": mathlib_rev,
            # Hashed BEFORE the byte-cap trim below: the hash covers the
            # full transcript, and both runs of an identical snippet trim
            # identically, so replay comparisons stay stable (AC-D.3).
            "transcript_sha256": transcript_sha256(
                snippet=snippet,
                imports=imports_list,
                mode=mode,
                lean_toolchain=lean_toolchain,
                mathlib_rev=mathlib_rev,
                payload=payload,
            ),
        }
        capped, _blocks = cap_result_list(
            envelope(payload), list_key="messages"
        )
        return capped

    # Snippet guard — reject snippet-declared axiom/opaque BEFORE any
    # REPL round-trip (finding 05 §3-R2a; AC-D.1). Deterministic and
    # REPL-independent, so it also fires when the REPL is disabled.
    if scan.rejected:
        kw = ", ".join(scan.rejected_keywords)
        logger.warning(
            "lean_verify: soundness guard rejected snippet "
            "(declares: %s)",
            kw,
        )
        rejected_payload = {
            "status": "error",
            "lean_status": "disabled" if lean_repl is None else "available",
            "mode": mode,
            "messages": [
                {
                    "severity": "error",
                    "position": {"line": 0, "column": 0},
                    "text": (
                        f"soundness guard: snippet contains '{kw}' — "
                        "rejected before elaboration. A snippet-declared "
                        "axiom/opaque lets a proof manufacture its own "
                        "trust base (WS-D D-2 hardening; RISKS MA-2); a "
                        "meta-programming entry point (#eval/run_cmd/elab/"
                        "macro/initialize/...) or a kernel-check-disabling "
                        "set_option (debug.skip*) lets it subvert the kernel "
                        "outright — e.g. add a declaration via "
                        "Environment.addDeclCore (doCheck := false) so a "
                        "provably-false theorem passes with a clean "
                        "#print axioms closure (finding R2-AC-1)."
                    ),
                }
            ],
            "sorry_goals": [],
            "goals_remaining": [],
            "proof_state": None,
            "compilation_success": False,
        }
        return _finish(
            rejected_payload,
            _soundness_block(
                scan,
                guard="rejected",
                audit_status="rejected",
                audit_detail=f"snippet declares: {kw}",
            ),
        )

    # FM-7 (graceful unavailable) — ARXMCP_ENABLE_LEAN=false leaves the
    # tool registered (BP1 stability) but Resources.lean_repl is None.
    if lean_repl is None:
        return _finish(
            _disabled_envelope(mode),
            _soundness_block(
                scan,
                audit_status="skipped",
                audit_detail="lean REPL disabled (ARXMCP_ENABLE_LEAN=false)",
            ),
        )

    cmd = _build_command(snippet, imports_list, mode)

    # verification-feedback-m4 — spawn a heartbeat task ONLY when a
    # FastMCP-injected ``ctx`` is present AND the client opted in to
    # progress via ``_meta.progressToken`` (m4 critique F3 —
    # spawn-without-token spammed INFO logs with "heartbeat fired" lines
    # that documented no-op emissions). Direct-call test sites pass
    # ``ctx=None`` and skip emission entirely. The Lean call remains on
    # the main coroutine path (m4 synthesis §3 D1 — preserves the m3
    # ``try/except LeanReplTimeoutError`` / ``try/except LeanReplError``
    # structure verbatim). The ``try/finally`` below guarantees the
    # heartbeat task is cancelled on EVERY exit path — success (FM-3),
    # timeout (FM-7), and other ``LeanReplError`` variants (FM-7).
    heartbeat_task: asyncio.Task[None] | None = None
    if ctx is not None and _has_progress_token(ctx):
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
        logger.warning(
            "lean_verify: REPL timed out — closing and respawning (%s)", exc
        )
        await _kill_and_respawn(resources, lean_repl)
        return _finish(
            _timeout_envelope(mode, DEFAULT_QUERY_TIMEOUT_S),
            _soundness_block(
                scan,
                audit_status="skipped",
                audit_detail="verification query timed out",
            ),
        )
    except LeanReplError as exc:
        # Any other LeanReplError (process exited, non-JSON response,
        # etc.) — surface as an error envelope, do NOT raise (the agent
        # gets a usable response with the error message).
        logger.warning("lean_verify: REPL error: %s", exc)
        return _finish(
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
            },
            _soundness_block(
                scan,
                audit_status="skipped",
                audit_detail="REPL error during verification",
            ),
        )

    payload = _normalize_response(resp, mode)

    # D-2 post-verification axiom-closure audit (finding 05 §3-R2a;
    # AC-D.1/AC-D.2). Runs ONLY on a kernel-accepted full-mode result —
    # anything else has no award to protect. Fail-closed throughout:
    # a failed/partial audit yields axiom_closure_ok=False and the
    # award predicate (server.lean_soundness.formal_award_ok) denies.
    audit_status = "skipped"
    audit_detail: str | None = None
    audited: list[str] = []
    axioms_by_decl: dict[str, list[str]] | None = None
    # Durable P1 soundness fix — the KERNEL-reported proved statement per
    # audited declaration (name -> fully-elaborated type). Populated on the
    # same kernel-accepted full-mode-with-decls path as the axiom audit,
    # but INDEPENDENT of the axiom-audit verdict (it is additive linkage
    # evidence, not part of the axiom-closure award). Empty on every other
    # path (fail-closed).
    kernel_statements: dict[str, str] = {}
    if mode != "full":
        audit_detail = "syntax_only mode ran no kernel verification"
    elif payload["status"] != "ok":
        audit_detail = f"verification status is {payload['status']!r}"
    else:
        decls = extract_decl_names(snippet)
        if not decls:
            audit_detail = (
                "no auditable theorem/lemma declarations found in snippet"
            )
        else:
            try:
                audit_status, audit_detail, axioms_by_decl = (
                    await _audit_axioms(lean_repl, resp.get("env"), decls)
                )
                if audit_status == "ok":
                    audited = decls
                # KERNEL-type query per declaration — the authoritative
                # proved-statement source for verdict linkage (replaces the
                # retired author-source text scan). Runs regardless of the
                # axiom-audit outcome above; a per-name miss (comment/string
                # phantom, unqueryable name) is simply omitted (fail-closed).
                kernel_statements = await _audit_statements(
                    lean_repl, resp.get("env"), decls
                )
            except LeanReplTimeoutError as exc:
                logger.warning(
                    "lean_verify: axiom/statement audit timed out — closing "
                    "and respawning (%s)",
                    exc,
                )
                await _kill_and_respawn(resources, lean_repl)
                audit_status = "failed"
                audit_detail = "axiom audit query timed out; REPL respawned"
                # A wedged REPL invalidates any partial statement map — the
                # respawn cleared the env, so fail closed on linkage too.
                kernel_statements = {}
            except LeanReplError as exc:
                logger.warning(
                    "lean_verify: axiom/statement audit REPL error: %s", exc
                )
                audit_status = "failed"
                audit_detail = f"axiom audit REPL error: {exc}"
                kernel_statements = {}

    # Multi-result cap surface — long elaborations can emit hundreds of
    # diagnostic rows; cap_result_list (inside _finish) trims the
    # trailing entries from the messages array if the envelope exceeds
    # Config.result_byte_cap.
    return _finish(
        payload,
        _soundness_block(
            scan,
            audit_status=audit_status,
            audit_detail=audit_detail,
            audited_decls=audited,
            axioms_by_decl=axioms_by_decl,
        ),
        kernel_statements=kernel_statements,
    )
