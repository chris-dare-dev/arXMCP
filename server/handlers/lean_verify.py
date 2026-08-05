"""``lean_verify`` handler — kernel-backed Lean 4 verification feedback
for the autoformalizer / tactician / fixer pipeline (verification-feedback-m3).

A thin mapping layer over :class:`server.lean_repl.LeanRepl`. The
handler accepts a Lean 4 snippet + optional context imports + a
``mode`` of ``"full"`` (elaborator AND kernel) or ``"syntax_only"``
(elaborator only — wrapped in ``#check (...)``), drives one REPL
round-trip, and projects the response into the frozen schema at
``server/schemas/lean_verify_result.json`` (version 23).

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
import re
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
# Continuation-token codec (lean-verify-continuation-m1)
# ---------------------------------------------------------------------------
# The leanprover-community/repl ``env`` and ``proofState`` ids are integers
# scoped to ONE subprocess instance. We NEVER expose the raw int: the tool
# emits an opaque token ``"{generation}:{int}"`` where ``generation`` is the
# per-spawn ``LeanRepl.generation`` (colon-free hex). On input the handler
# splits the token and rejects — FAIL CLOSED — any token whose generation
# does not match the live REPL (a token minted before a timeout-triggered
# kill+respawn), so a stale id can never silently misbind onto a colliding
# env id in the new process. It also rejects a fabricated / malformed token.


def _encode_token(generation: str, n: int) -> str:
    """Wrap a raw REPL env / proofState int in a generation-scoped token."""
    return f"{generation}:{n}"


def _decode_token(token: Any, current_generation: str) -> tuple[str, int | None]:
    """Decode a continuation token against the live REPL generation.

    Returns ``(disposition, value)`` where ``disposition`` is:
    - ``"resumed"``  → ``value`` is the int to forward to the REPL;
    - ``"expired"``  → the token is from a prior REPL instance (``value`` None);
    - ``"malformed"``→ unparseable / fabricated (``value`` None).

    The int is split off the RIGHT (``rpartition``) so a generation that ever
    contained a colon would still round-trip; the current generation is
    colon-free hex, but the parser does not depend on that.
    """
    if not isinstance(token, str):
        return ("malformed", None)
    gen, sep, num = token.rpartition(":")
    if not sep or not gen:
        return ("malformed", None)
    try:
        n = int(num)
    except ValueError:
        return ("malformed", None)
    if n < 0:
        return ("malformed", None)
    if gen != current_generation:
        return ("expired", None)
    return ("resumed", n)


def _continuation_reject_message(kind: str, disposition: str) -> str:
    """Human-readable reason for a fail-closed continuation rejection."""
    if disposition == "expired":
        return (
            f"The {kind} continuation token was minted by a previous Lean REPL "
            "instance (the REPL is respawned after a per-query timeout). "
            "Continuation tokens do not survive a respawn — re-run the setup "
            "call (e.g. re-import) to obtain a fresh token before continuing."
        )
    return (
        f"The {kind} continuation token is malformed. Pass back the opaque "
        "token returned by a prior lean_verify call verbatim; do not "
        "construct one."
    )


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


def _project_messages(raw_msgs: Any) -> list[dict[str, Any]]:
    """Project REPL diagnostic rows into the schema ``messages`` shape.

    m3 critique F2: clamp severity to the schema enum (unknown values
    default to "error" — the safer side; silent downgrade to "info" would
    mask real diagnostics from a future REPL build) AND coerce ``data`` to
    ``str`` so a structured upstream payload becomes a string rather than a
    schema-violating slot. Shared by the cmd and tactic_step branches.
    """
    return [
        {
            "severity": (
                m.get("severity")
                if m.get("severity") in _ALLOWED_SEVERITIES
                else "error"
            ),
            "position": _normalize_position(m.get("pos")),
            "text": str(m.get("data", "")),
        }
        for m in (raw_msgs or [])
        if isinstance(m, dict)
    ]


def _project_sorries(
    raw_sorries: Any, repl_generation: str
) -> list[dict[str, Any]]:
    """Project REPL ``sorries`` rows into the schema ``sorry_goals`` shape,
    attaching a per-sorry ``proof_state_id`` continuation token when the REPL
    supplied a ``proofState`` id. Shared by the cmd and tactic_step branches
    (m5 critique F2 — tactic_step previously dropped the sorries frontier).
    """
    out: list[dict[str, Any]] = []
    for s in raw_sorries or []:
        if not isinstance(s, dict):
            continue
        row: dict[str, Any] = {
            "goal": str(s.get("goal", "")),
            "position": _normalize_position(s.get("pos")),
        }
        ps = s.get("proofState")
        if isinstance(ps, int):
            # Per-sorry continuation token so the tactician can target THIS
            # sorry via mode=tactic_step.
            row["proof_state_id"] = _encode_token(repl_generation, ps)
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Axiom-hygiene axis (issues #205 / #281 / #332)
# ---------------------------------------------------------------------------
# CLAUDE.md §4.9 rule 1 named this module's ``status`` as THE live violation of
# the trust-language policy: the original ``status="ok"`` (renamed to
# ``elaborated_no_errors`` at verification-contract-m1) <=> (no error-severity
# messages) AND (no sorries), so a bare ``axiom h : False`` elaborates clean
# and the surface called a proof of False clean. ``lean_verify`` is the only
# tool here that emits a *verdict* rather than evidence, so that token is
# designed to be believed.
#
# The fix is an INDEPENDENT axis, never a widened ``status``
# (``.claude/docs/trust-language-policy.md`` §6 rule 1: "New trust-bearing
# fields are namespaced and axis-specific"; §4: "no axis may be inferred from
# another"). Concretely:
#
#   - ``status`` / ``compilation_success`` keep answering EXACTLY what they
#     measure — elaboration + proof closure, and kernel acceptance. The kernel
#     really did accept ``axiom h : False``; forcing those fields to "error"
#     because of an axiom finding would be inferring the elaboration axis from
#     the axiom axis — the same conflation in the opposite direction.
#   - ``axiom_audit`` answers the fidelity question those fields never could,
#     from the transitive axiom closure Lean itself reports.
#
# Certificate-shaped per policy §6 rule 3 — an ordinal ``outcome`` PLUS the
# evidence behind it (the per-declaration axiom sets, the allowlist actually
# applied, and the method). Always emitted, and NEVER defaulted to a passing
# value (policy §6 rule 5): every path that does not measure the axis says so.

#: The transitive axioms a proof may depend on and still count as clean. These
#: three are Lean 4 / mathlib's standard classical foundation and are the
#: allowlist named by the R3 verification contract
#: (``.claude/roadmap-briefs/R3-verification-contract.md`` key result 3).
#:
#: Everything else is flagged, with no special-casing needed for the notable
#: cases: ``sorryAx`` (an unproved hole — the axiom-side cross-check on the
#: proof-closure axis), ``Lean.ofReduceBool`` / ``Lean.trustCompiler``
#: (introduced by ``native_decide``, which the Lean community treats as a
#: trust reduction), and any user-declared ``axiom``.
AXIOM_ALLOWLIST: frozenset[str] = frozenset(
    {"propext", "Quot.sound", "Classical.choice"}
)

#: Outcome precedence when combining per-declaration verdicts — a weakest-link
#: ``meet`` WITHIN this one axis (policy §4 permits ``meet`` only within an
#: axis, never across axes). ``flagged`` outranks ``unknown`` because it is
#: strictly more informative and strictly more severe; ``clean`` is only
#: reported when every declaration was measured AND every measurement passed.
_AUDIT_SEVERITY: dict[str, int] = {"clean": 0, "unknown": 1, "flagged": 2}

#: Declaration keywords whose bodies the Lean kernel checks. ``example`` is
#: deliberately absent: it introduces no name, so ``#print axioms`` cannot
#: address it (it is also caught indirectly — an ``example`` that leans on a
#: bad axiom needs that axiom declared in the same snippet, which IS named).
_DECL_KEYWORDS: tuple[str, ...] = (
    "theorem",
    "lemma",
    "def",
    "abbrev",
    "axiom",
    "opaque",
    "instance",
    "structure",
    "inductive",
    "class",
    # ``alias foo := bar`` registers a real declaration and was simply missing
    # (#382 critique). Unlike ``set_option`` / ``open``, which are commands and
    # NOT declarations, `alias` belongs in this list: naming it means the
    # aliased declaration is audited rather than merely fail-safed. The Mathlib
    # anonymous-constructor form ``alias ⟨a, b⟩ := h`` yields a name this
    # parser cannot resolve, which `#print axioms` answers as an unknown
    # identifier — scored ``unknown``, never ``clean``.
    "alias",
)

#: Modifiers that may precede a declaration keyword.
_DECL_MODIFIERS: tuple[str, ...] = (
    "private",
    "protected",
    "noncomputable",
    "unsafe",
    "partial",
    "nonrec",
    "scoped",
    "local",
)

_MODIFIER_ALT = "|".join(_DECL_MODIFIERS)
_KEYWORD_ALT = "|".join(_DECL_KEYWORDS)

#: A declaration SITE — the keyword, whether or not a name follows. Counting
#: sites separately from extracted names is what makes under-extraction
#: fail-safe: an unnamed ``instance``, or any form this regex cannot name,
#: leaves sites > names and forces the whole audit to ``unknown`` rather than
#: letting an unaudited declaration ride along inside a ``clean`` verdict.
_DECL_SITE_RE = re.compile(
    rf"^\s*(?:@\[[^\]]*\]\s*)*(?:(?:{_MODIFIER_ALT})\s+)*(?:{_KEYWORD_ALT})\b"
)

#: EVERY declaration site on a physical line, wherever it sits (#382).
#:
#: ``_DECL_SITE_RE`` anchors at the start of the line and ``.match()`` returns
#: at most once, so for counting purposes a line was worth 0 or 1 sites no
#: matter how many declarations Lean actually read off it. Two distinct holes
#: followed, both of which produced a false ``clean`` rather than an honest
#: ``unknown``, and both reproduced against real ``lean4:v4.29.0``:
#:
#:   def harmless : Nat := 1 axiom evil : False
#:     -> Lean: 'harmless' does not depend on any axioms
#:              'evil' depends on axioms: [evil]
#:     -> extractor, before this fix: (['harmless'], True) -> audit `clean`
#:
#:   namespace N theorem t : True := trivial axiom evil : False
#:     -> Lean registers BOTH `N.t` and `N.evil`; the namespace branch of
#:        :func:`_declaration_names` consumed the line and `continue`d, so
#:        neither declaration was counted at all.
#:
#: Lean 4 is whitespace-insensitive at the command level: the term parser stops
#: at a command keyword, so `:= 1 axiom` ends the `def` body and opens a new
#: command. Physical lines are OUR unit, never Lean's — so counting must scan
#: the whole line.
#:
#: This also subsumes the earlier prefixed-site probe, whose shapes (all
#: measured in this repo) are just the special case of a keyword that is not
#: the first token:
#:
#:   set_option maxHeartbeats 400000 in theorem t    -- the Mathlib idiom
#:   open Classical in theorem t
#:   variable (n : Nat) in theorem t
#:   universe u in theorem t
#:   attribute [simp] foo in theorem t
#:   deriving instance ToExpr for ULift              -- verbatim from mathlib4
#:   meta unsafe instance foo : Inhabited Nat := d
#:   /-- Helper. -/ axiom evil : False               -- see _strip_comments
#:
#: The characterisation is NOT "an ``in`` combinator" — that framing closed
#: five shapes and left three open, which is what the first attempt at #382
#: shipped. It is: **count the declaration keywords the line carries, and
#: compare against the names that could be extracted from it.**
#:
#: Deliberately does NOT teach the parser ``set_option`` / ``open`` /
#: ``deriving`` grammar: an unnameable site is counted with NO extractable
#: name, the same fail-safe the unnamed ``instance`` already uses. Fail-safe
#: over feature — over-counting only ever moves ``complete`` True -> False,
#: never the reverse, so it can never admit a declaration that went unaudited.
#:
#: The keyword must be preceded by start-of-line, whitespace, or ``]`` (the
#: attribute-bracket case ``@[simp]theorem t``), which is what keeps a
#: projection like ``simp [Set.def]`` or an identifier like ``inferInstance``
#: from counting. Comment text is removed and string-literal interiors are
#: masked by :func:`_strip_comments` before this ever runs — that masking is
#: what keeps ``def s : String := "a theorem about X"`` at one site rather than
#: two, now that the scan no longer anchors to the line start.
_DECL_KEYWORD_SCAN_RE = re.compile(
    rf"(?:^|(?<=\s)|(?<=\]))(?:{_KEYWORD_ALT})\b"
)

#: A declaration site that DOES carry an extractable name. The name charset
#: excludes the delimiters that can legally follow it (binders, type ascription,
#: universe braces) rather than enumerating Lean's very permissive identifier
#: alphabet, so unicode names (``φ``, ``α_lt``) and primed/`?`/`!` names survive.
_DECL_NAME_RE = re.compile(
    rf"^\s*(?:@\[[^\]]*\]\s*)*(?:(?:{_MODIFIER_ALT})\s+)*"
    rf"(?:{_KEYWORD_ALT})\s+(?P<name>[^\s:{{(\[⦃<]+)"
)

#: ``namespace Foo`` / ``section [Foo]`` / ``end [Foo]`` — tracked as a stack so
#: an extracted name is qualified exactly as Lean will have registered it.
#: Sections are tracked too: a bare ``end`` closing a ``section`` must NOT pop
#: an enclosing namespace and silently de-qualify every later name.
_NAMESPACE_RE = re.compile(r"^\s*namespace\s+(?P<name>\S+)")
_SECTION_RE = re.compile(r"^\s*section\b")
_END_RE = re.compile(r"^\s*end\b")

#: ``#print axioms Foo`` replies, verbatim from Lean:
#:   ``'Foo' depends on axioms: [propext, Classical.choice]``
#:   ``'Foo' does not depend on any axioms``
#: Parsed by the quoted NAME rather than by message order, so a reply set that
#: arrives reordered (or interleaved with unrelated diagnostics) still binds
#: each axiom set to the right declaration.
_PRINT_AXIOMS_RE = re.compile(
    r"^'(?P<name>[^']+)'\s+(?:depends on axioms:\s*\[(?P<axioms>[^\]]*)\]"
    r"|(?P<none>does not depend on any axioms))"
)


#: Filler substituted for each character inside a string literal. A word
#: character, so it cannot create the whitespace boundary
#: :data:`_DECL_KEYWORD_SCAN_RE` needs, and length-preserving one-for-one.
_STRING_FILLER = "x"


def _strip_comments(snippet: str) -> list[str]:
    """Return ``snippet``'s lines with Lean comment text blanked out.

    Removing comment text — rather than skipping lines that look like comments
    — is what lets :data:`_PREFIXED_DECL_SITE_RE` drop its ``in`` requirement
    without the prose false-positives an unanchored keyword scan would other-
    wise cause (``-- as used in theorem 3.2`` is not a declaration site). It
    also turns the same-line doc-comment shape ``/-- Helper. -/ axiom evil``
    into an ordinary NAMED site, so ``evil`` is genuinely audited rather than
    merely fail-safed.

    Handles what Lean 4's own lexer does at this level:

    - ``--`` to end of line
    - ``/- … -/`` block comments, INCLUDING nesting and spanning lines (Lean
      block comments nest; ``/-- doc -/`` is just a block comment to us)
    - ``"…"`` string literals with backslash escapes, so a ``--`` or ``/-``
      inside a string does not open a comment. Without this, ``def s := "/-"``
      would open a block comment that never closes and every later declaration
      in the snippet would vanish — the exact silent-drop this module exists
      to prevent. The literal's interior is replaced character-for-character
      with :data:`_STRING_FILLER` rather than copied, so prose inside a string
      cannot be read as a declaration site either (#382 round 2).

    Char literals (``'a'``) are deliberately NOT tracked: ``'`` is a legal
    identifier character in Lean (``h'``, ``ε'``), so treating it as a
    delimiter would corrupt far more lines than it protects.

    Output has the same number of lines as the input, and comment text is
    replaced rather than deleted, so every line-oriented match below keeps its
    original column semantics.
    """
    out: list[str] = []
    depth = 0  # open `/-` block-comment nesting depth, carried across lines
    for line in snippet.splitlines():
        kept: list[str] = []
        i = 0
        n = len(line)
        while i < n:
            if depth:
                if line.startswith("-/", i):
                    depth -= 1
                    i += 2
                elif line.startswith("/-", i):
                    depth += 1
                    i += 2
                else:
                    i += 1
                continue
            if line.startswith("/-", i):
                depth += 1
                i += 2
                continue
            if line.startswith("--", i):
                break  # rest of the line is a comment
            if line[i] == '"':
                # Mask the string literal's INTERIOR. Its contents must not be
                # scanned for comment openers, they must not shorten the line
                # (a declaration after it would be lost), and — since #382's
                # second round made _DECL_KEYWORD_SCAN_RE scan the whole line
                # rather than only its start — they must not contribute phantom
                # declaration sites. `def s : String := "a theorem about X"` is
                # ONE declaration; copying the literal verbatim would have made
                # it two and abstained on a snippet that is perfectly auditable.
                # A fixed filler char preserves length and carries no keyword.
                kept.append('"')
                i += 1
                while i < n:
                    if line[i] == "\\" and i + 1 < n:
                        kept.append(_STRING_FILLER * 2)
                        i += 2
                        continue
                    if line[i] == '"':
                        kept.append('"')
                        i += 1
                        break
                    kept.append(_STRING_FILLER)
                    i += 1
                continue
            kept.append(line[i])
            i += 1
        out.append("".join(kept))
    return out


def _declaration_names(snippet: str) -> tuple[list[str], bool]:
    """Extract the fully-qualified names ``snippet`` introduces.

    Returns ``(names, complete)``. ``complete`` is False when the snippet
    contains a declaration site this parser could not name (an unnamed
    ``instance``, a declaration behind an unrecognised ``… in`` combinator
    such as ``set_option … in theorem t``, an exotic form) — the caller MUST
    degrade the audit to ``unknown`` in that case, because a name we never
    asked about is a declaration we never audited.

    Namespace-aware: ``namespace N`` / ``end`` are tracked as a stack so
    ``theorem t`` inside ``namespace N`` is audited as ``N.t`` — the name Lean
    actually registered. A name that is nonetheless wrong is still fail-safe:
    ``#print axioms`` answers "unknown identifier", which this module scores as
    ``unknown``, never ``clean``.
    """
    names: list[str] = []
    sites = 0
    # Stack entries are (kind, name) — "namespace" contributes to the prefix,
    # "section" does not, but both are closed by `end`.
    scopes: list[tuple[str, str]] = []

    for line in _strip_comments(snippet):
        # #382: count EVERY declaration keyword the line carries, before any
        # branch below can `continue` past them. Two things make this the only
        # safe place for it. (a) A declaration behind an unrecognised same-line
        # prefix is a site this parser cannot name, NOT an absent one. (b) Lean
        # reads commands sequentially, not one per physical line, so
        # `def harmless : Nat := 1 axiom evil : False` is TWO declarations and
        # `namespace N theorem t : True := trivial` is a scope command with a
        # declaration riding behind it — both verified against lean4:v4.29.0.
        # Counting here is what lets the sites-vs-names fail-safe below fire
        # instead of letting a declaration ride inside a `clean` verdict.
        sites += len(_DECL_KEYWORD_SCAN_RE.findall(line))

        ns = _NAMESPACE_RE.match(line)
        if ns:
            scopes.append(("namespace", ns.group("name")))
            continue
        if _SECTION_RE.match(line):
            scopes.append(("section", ""))
            continue
        if _END_RE.match(line):
            if scopes:
                scopes.pop()
            continue
        if not _DECL_SITE_RE.match(line):
            continue
        named = _DECL_NAME_RE.match(line)
        if not named:
            continue
        prefix = ".".join(n for kind, n in scopes if kind == "namespace")
        name = named.group("name")
        names.append(f"{prefix}.{name}" if prefix else name)

    # De-duplicate, preserving order (a snippet may legitimately re-declare a
    # name in two namespaces; identical qualified names are one audit target).
    seen: set[str] = set()
    unique = [n for n in names if not (n in seen or seen.add(n))]
    return unique, sites == len(names)


def _audit_record(
    outcome: str,
    *,
    declarations: list[dict[str, Any]] | None = None,
    reason: str | None = None,
    method: str | None = None,
) -> dict[str, Any]:
    """Build the Certificate-shaped ``axiom_audit`` record.

    ``outcome`` is the ordinal level; ``declarations`` / ``disallowed`` /
    ``allowlist`` / ``method`` are the attached evidence (policy §6 rule 3 — a
    trust-bearing field carries its evidence, not a bare token).
    """
    decls = declarations or []
    disallowed = sorted(
        {
            ax
            for d in decls
            for ax in d.get("axioms", [])
            if ax not in AXIOM_ALLOWLIST
        }
    )
    return {
        "outcome": outcome,
        "declarations": decls,
        "disallowed_axioms": disallowed,
        "allowlist": sorted(AXIOM_ALLOWLIST),
        "method": method,
        "reason": reason,
    }


def _audit_not_applicable(reason: str) -> dict[str, Any]:
    """The tool did not measure this axis on this path. Distinct from
    ``unknown`` (measurement was attempted and did not resolve) and from
    ``clean`` — an unmeasured axis is NEVER a passing one (policy §6 rule 5).
    """
    return _audit_record("not-applicable", reason=reason)


def _audit_unknown(reason: str, **kw: Any) -> dict[str, Any]:
    return _audit_record("unknown", reason=reason, **kw)


def _parse_print_axioms(messages: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Map declaration name -> transitive axiom list from ``#print axioms``
    reply messages. Names Lean did not answer for are simply absent, which the
    caller scores as ``unknown`` for that declaration."""
    found: dict[str, list[str]] = {}
    for msg in messages:
        m = _PRINT_AXIOMS_RE.match(msg.get("text", "").strip())
        if not m:
            continue
        if m.group("none") is not None:
            found[m.group("name")] = []
            continue
        raw = m.group("axioms") or ""
        found[m.group("name")] = [a.strip() for a in raw.split(",") if a.strip()]
    return found


def _audit_from_messages(
    messages: list[dict[str, Any]], names: list[str], complete: bool
) -> dict[str, Any]:
    """Score a ``#print axioms`` reply set into an ``axiom_audit`` record."""
    answered = _parse_print_axioms(messages)
    declarations: list[dict[str, Any]] = []
    worst = "clean"

    for name in names:
        if name not in answered:
            # Lean did not report on this declaration — most often "unknown
            # identifier" because the qualified name we derived is wrong.
            # Fail-safe: unknown, never clean.
            declarations.append({"name": name, "axioms": [], "verdict": "unknown"})
            worst = _worse(worst, "unknown")
            continue
        axioms = answered[name]
        bad = [a for a in axioms if a not in AXIOM_ALLOWLIST]
        verdict = "flagged" if bad else "clean"
        declarations.append({"name": name, "axioms": axioms, "verdict": verdict})
        worst = _worse(worst, verdict)

    reason: str | None = None
    if not complete:
        # A declaration site we could not name is a declaration we did not
        # audit; the record must not read as a clean sweep.
        worst = _worse(worst, "unknown")
        reason = (
            "The snippet contains a declaration this tool could not name (an "
            "unnamed instance, a declaration behind an unrecognized same-line "
            "prefix such as 'set_option ... in' or 'deriving instance', or "
            "another unrecognized declaration form), so the audit does not "
            "cover every declaration it introduced."
        )
    elif worst == "unknown":
        reason = (
            "Lean did not report an axiom set for every declaration (the "
            "derived name may not match the registered one)."
        )

    return _audit_record(
        worst, declarations=declarations, reason=reason, method="#print axioms"
    )


def _worse(a: str, b: str) -> str:
    """Weakest-link combinator, WITHIN the axiom axis only (policy §4)."""
    return a if _AUDIT_SEVERITY[a] >= _AUDIT_SEVERITY[b] else b


#: The EXACT leanprover-community/repl replies for a stale/unknown env or
#: proofState id (verified live). A bare top-level ``message`` matching one of
#: these is a continuation-id rejection (invalid-input); any OTHER bare
#: ``message`` (e.g. a thrown "Lean error:\n...") is a genuine kernel/tactic
#: error, NOT a continuation problem (m5 critique F1).
_UNKNOWN_ID_PREFIXES: tuple[str, ...] = (
    "Unknown environment",
    "Unknown proof state",
)


def _normalize_response(
    resp: dict[str, Any],
    mode: str,
    *,
    repl_generation: str,
    resumed: bool = False,
) -> dict[str, Any]:
    """Project a ``LeanRepl.query`` response into the schema shape.

    Handles THREE response shapes (lean-verify-continuation-m1):

    1. ``{"message": <str>}`` — the REPL's "Unknown environment." /
       "Unknown proof state." protocol error for a stale/unknown
       continuation id. It carries NEITHER ``messages`` NOR ``sorries``,
       so the pre-m5 path (both empty ⇒ status "ok") reported it as a
       CLEAN COMPILE. Checked FIRST and failed closed — the primary
       soundness fix of this milestone.
    2. tactic_step — ``{"proofStatus", "proofState", "goals"}`` from a
       ``{"tactic": ...}`` round-trip (see ``_normalize_tactic_step``).
    3. cmd — ``{"env", "messages", "sorries"}`` from a ``{"cmd": ...}``
       round-trip (the pre-m5 shape), now also surfacing the ``env`` token
       and per-sorry ``proof_state_id`` tokens.

    ``resumed`` records whether a valid continuation token was forwarded to
    the REPL (⇒ ``continuation_status == "resumed"``); ``repl_generation``
    stamps every token this call emits.
    """
    continuation_status = "resumed" if resumed else "not-applicable"

    # Shape 1 — a bare top-level "message" (NEITHER a "messages" array NOR
    # "env" / "sorries"). Two disjoint sub-cases, BOTH fail closed:
    #   (a) the REPL's "Unknown environment." / "Unknown proof state." error
    #       for a stale/unknown continuation id -> invalid-input (the primary
    #       soundness fix: the pre-m5 path reported this as a CLEAN COMPILE);
    #   (b) any OTHER thrown message — e.g. a failed tactic "Lean error:\n..."
    #       (runProofStep catch, REPL/Main.lean) — a genuine kernel/tactic
    #       ERROR, NOT a continuation problem (the token, if any, was valid).
    #       m5 critique F1: routing (b) through the unknown-id path mislabeled
    #       every failed tactic as a bad token and lied on the continuation
    #       axis. Discriminated on the EXACT REPL strings (verified live).
    raw_message = resp.get("message")
    if isinstance(raw_message, str) and "env" not in resp:
        if raw_message.strip().startswith(_UNKNOWN_ID_PREFIXES):
            return _invalid_continuation_envelope(
                mode,
                continuation_status="unknown-id",
                message=(
                    f"Lean REPL rejected the continuation id: {raw_message} "
                    "The env / proof_state token references a state that does "
                    "not exist in the current REPL process."
                ),
            )
        return _message_error_envelope(
            mode, raw_message, continuation_status=continuation_status
        )

    # Shape 2 — tactic_step.
    if mode == "tactic_step":
        return _normalize_tactic_step(
            resp,
            continuation_status=continuation_status,
            repl_generation=repl_generation,
        )

    # Shape 3 — cmd (full / syntax_only).
    messages = _project_messages(resp.get("messages"))
    sorry_goals = _project_sorries(resp.get("sorries"), repl_generation)
    goals_remaining = [s["goal"] for s in sorry_goals if s["goal"]]

    # `status` stays a bare token here, NOT because the trust-language policy
    # exempts it — it does not. ``.claude/docs/trust-language-policy.md`` §6
    # rule 3 reads "Every trust-bearing field carries its ``Certificate``
    # (level + attached evidence), not a bare token", with no qualifier, and
    # this field's own schema description defines an ordinal precedence
    # ladder. So rule 3 DOES reach `status`.
    #
    # This is a SCOPED DEFERRAL, owned by ``verification-contract-e3``:
    # nesting `status` into a Certificate is a wire-breaking shape change,
    # and e3 owns the response-schema redesign that can carry it. m1's scope
    # was the honest token plus the design ADR. Meanwhile the evidence rule 3
    # wants attached does ship — as sibling fields (``messages``,
    # ``sorry_goals``, ``proof_state``, ``axiom_audit``) rather than as one
    # attached record.
    #
    # Do not read policy §2 as blessing the rename alone: §2 names the rename
    # AND the five-operation split together as R3's remedy. See
    # ``.claude/docs/adr-verification-contract-five-operations.md`` Decision 2.
    has_error = any(m["severity"] == "error" for m in messages)
    has_sorry = bool(sorry_goals)
    if has_error:
        status = "error"
    elif has_sorry:
        status = "sorry"
    else:
        status = "elaborated_no_errors"

    # syntax_only DID NOT run kernel verification — even a clean
    # elaboration leaves "verification success" undefined. Surface this as
    # null so the agent does not read a syntax-only pass as a full kernel
    # acceptance.
    if mode == "syntax_only" and status == "elaborated_no_errors":
        compilation_success: bool | None = None
    else:
        compilation_success = status == "elaborated_no_errors"

    env_raw = resp.get("env")
    env_token = (
        _encode_token(repl_generation, env_raw)
        if isinstance(env_raw, int)
        else None
    )
    first_ps_token = next(
        (s["proof_state_id"] for s in sorry_goals if "proof_state_id" in s),
        None,
    )

    return {
        "status": status,
        "messages": messages,
        "sorry_goals": sorry_goals,
        "goals_remaining": goals_remaining,
        "proof_state": goals_remaining[0] if goals_remaining else None,
        "proof_state_id": first_ps_token,
        "compilation_success": compilation_success,
        "lean_status": "available",
        "mode": mode,
        "env": env_token,
        "continuation_status": continuation_status,
        # Placeholder only. ``_normalize_response`` is a PURE projection of one
        # REPL response; measuring the axiom axis needs a second round-trip, so
        # the handler overwrites this via ``_attach_axiom_audit`` on the paths
        # that warrant one. The default is deliberately non-passing: if that
        # call is ever skipped or removed, the record degrades to "unmeasured",
        # never to "clean" (policy §6 rule 5).
        "axiom_audit": _default_audit_for(mode, status),
    }


def _default_audit_for(mode: str, status: str) -> dict[str, Any]:
    """The ``axiom_audit`` a cmd-shaped response carries before the handler's
    second round-trip runs (or when one is not warranted)."""
    if mode == "syntax_only":
        return _audit_not_applicable(
            "mode='syntax_only' short-circuits post-elaboration kernel work, "
            "so no declaration is kernel-checked and there is no axiom closure "
            "to audit. Re-run in mode='full' for an axiom verdict."
        )
    if status not in ("elaborated_no_errors", "sorry"):
        return _audit_not_applicable(
            f"status={status!r}: the snippet introduced no kernel-checked "
            "declaration to audit."
        )
    return _audit_unknown(
        "The axiom audit did not run for this call.",
        method="#print axioms",
    )


def _normalize_tactic_step(
    resp: dict[str, Any],
    *,
    continuation_status: str,
    repl_generation: str,
) -> dict[str, Any]:
    """Project a ``{"tactic": ...}`` step response into the schema shape.

    Response shape (measured): ``{"proofStatus": <str>, "proofState": <int>,
    "goals": [<str>, ...]}`` plus optional ``sorries`` (a sorry-introducing
    tactic) and ``messages`` (tactic diagnostics). ``goals`` empty + no
    ``sorries`` + ``proofStatus == "Completed"`` ⇒ the goals at this state
    are discharged (``status == "elaborated_no_errors"``); open goals OR a remaining sorry ⇒
    ``status == "incomplete"``; a tactic error ⇒ ``"error"``.

    m5 critique F2: a sorry-introducing tactic returns ``{"goals": [],
    "proofStatus": "Incomplete: contains sorry", "sorries": [...]}`` — the
    ``sorries`` frontier (and its resumable ``proofState`` ids) MUST be
    surfaced, else the caller sees "incomplete" with nothing to act on.

    ``compilation_success`` is ALWAYS null here: a single tactic step is not
    a full-declaration kernel check, and the trust-language policy forbids
    inferring declaration fidelity from it. Re-verify the assembled proof in
    ``mode="full"`` for a kernel verdict.
    """
    messages = _project_messages(resp.get("messages"))
    goals_remaining = [str(g) for g in (resp.get("goals") or [])]
    sorry_goals = _project_sorries(resp.get("sorries"), repl_generation)
    has_error = any(m["severity"] == "error" for m in messages)
    if has_error:
        status = "error"
    elif goals_remaining or sorry_goals:
        # Open goals OR a sorry-marked obligation remain — not closed.
        status = "incomplete"
    elif resp.get("proofStatus") == "Completed":
        status = "elaborated_no_errors"
    else:
        # No goals, no sorries, but not "Completed" — do not claim
        # "elaborated_no_errors". A conservative, fail-closed default.
        status = "incomplete"

    new_ps = resp.get("proofState")
    new_ps_token = (
        _encode_token(repl_generation, new_ps)
        if isinstance(new_ps, int)
        else None
    )
    # proof_state text: the first open goal, else the first remaining sorry.
    if goals_remaining:
        proof_state_text: str | None = goals_remaining[0]
    elif sorry_goals:
        proof_state_text = sorry_goals[0]["goal"]
    else:
        proof_state_text = None

    return {
        "status": status,
        "messages": messages,
        "sorry_goals": sorry_goals,
        "goals_remaining": goals_remaining,
        "proof_state": proof_state_text,
        "proof_state_id": new_ps_token,
        # Never a full-declaration kernel verdict — see docstring.
        "compilation_success": None,
        "lean_status": "available",
        "mode": "tactic_step",
        "env": None,
        "continuation_status": continuation_status,
        "axiom_audit": _audit_not_applicable(
            "A tactic step advances a proof state; it introduces no named "
            "declaration, so there is nothing for '#print axioms' to address. "
            "Re-verify the assembled proof in mode='full' for an axiom verdict."
        ),
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
        "proof_state_id": None,
        "compilation_success": None,
        "env": None,
        "continuation_status": "not-applicable",
        "axiom_audit": _audit_not_applicable(
            "The Lean REPL is disabled (ARXMCP_ENABLE_LEAN=false); nothing "
            "was elaborated, so no axiom closure exists to audit."
        ),
    }


def _timeout_envelope(
    mode: str, timeout_s: float, *, continuation_status: str = "not-applicable"
) -> dict[str, Any]:
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
        "proof_state_id": None,
        "compilation_success": False,
        # The respawn mints a NEW generation, so any token emitted before
        # this timeout is now expired for FUTURE calls; continuation_status
        # still records THIS call's disposition (m5 critique F4).
        "env": None,
        "continuation_status": continuation_status,
        "axiom_audit": _audit_not_applicable(
            "The elaboration exceeded the per-query wall-clock and the REPL "
            "was killed; no declaration was admitted, so no axiom closure "
            "exists to audit."
        ),
    }


def _invalid_continuation_envelope(
    mode: str, *, continuation_status: str, message: str
) -> dict[str, Any]:
    """Fail-closed envelope for a rejected continuation token.

    Used when an ``env`` / ``proof_state`` token is malformed, was minted by
    a prior REPL instance (``expired``), or is unknown to the live REPL
    (``unknown-id``). The snippet did NOT run: ``status="invalid-input"`` and
    ``compilation_success=False`` so no caller reads it as a kernel accept.
    ``lean_status`` stays ``"available"`` — the REPL itself is healthy; the
    input was rejected.
    """
    return {
        "status": "invalid-input",
        "lean_status": "available",
        "mode": mode,
        "messages": [
            {
                "severity": "error",
                "position": {"line": 0, "column": 0},
                "text": message,
            }
        ],
        "sorry_goals": [],
        "goals_remaining": [],
        "proof_state": None,
        "proof_state_id": None,
        "compilation_success": False,
        "env": None,
        "continuation_status": continuation_status,
        "axiom_audit": _audit_not_applicable(
            "The continuation token was rejected and the snippet did not run, "
            "so no axiom closure exists to audit."
        ),
    }


def _message_error_envelope(
    mode: str, message: str, *, continuation_status: str
) -> dict[str, Any]:
    """Fail-closed ERROR envelope for a bare top-level REPL ``message`` that
    is NOT an unknown-id rejection — e.g. a thrown tactic error
    ("Lean error:\\n...", the runProofStep catch). ``status="error"`` (a
    genuine kernel/tactic error), NOT ``"invalid-input"``: the continuation
    token, if any, was valid (m5 critique F1). ``continuation_status``
    reflects whether a token was resumed on this call.
    """
    return {
        "status": "error",
        "lean_status": "available",
        "mode": mode,
        "messages": [
            {
                "severity": "error",
                "position": {"line": 0, "column": 0},
                "text": message,
            }
        ],
        "sorry_goals": [],
        "goals_remaining": [],
        "proof_state": None,
        "proof_state_id": None,
        "compilation_success": False,
        "env": None,
        "continuation_status": continuation_status,
        "axiom_audit": _audit_not_applicable(
            "The Lean REPL reported an error rather than a checked "
            "environment, so no axiom closure exists to audit."
        ),
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


async def _respawn_after_timeout(resources: Any, lean_repl: Any) -> None:
    """Close a wedged REPL and respawn it from config.

    The lean-sandbox-design contract: ``LeanRepl.query``'s wall-clock timeout
    raises but does NOT terminate the subprocess, so a wedged elaboration would
    interleave its stdout into every subsequent call. Shared by the primary
    query path and the axiom-audit round-trip.

    Best-effort by design: ``close`` on an already-wedged process can
    legitimately raise, and a failed respawn degrades later calls to
    "unavailable" rather than raising here. ``CancelledError`` propagates (it
    is a ``BaseException``), so the narrow excepts below cannot swallow it.
    """
    try:
        await lean_repl.close()
    except (OSError, LeanReplError):
        logger.exception("lean_verify: REPL close after timeout failed")
    try:
        resources.lean_repl = await LeanRepl.spawn_from_config(resources.config)
    except (LeanUnavailableError, OSError):
        logger.exception(
            "lean_verify: respawn after timeout failed; "
            "subsequent calls degrade to 'unavailable'"
        )
        resources.lean_repl = None


def _invalidate_continuation_tokens(payload: dict[str, Any]) -> None:
    """Strip every continuation token from ``payload`` in place.

    Called when the REPL is respawned AFTER the primary response was projected:
    the tokens that response minted address env / proofState ids inside a
    process that no longer exists. They would be rejected as ``expired`` on
    reuse (the generation guard holds), but emitting a token that is already
    known-dead invites a pointless round-trip — and a caller that reads a
    non-null ``env`` as "resumable" would be reading a false affordance.
    """
    payload["env"] = None
    payload["proof_state_id"] = None
    for row in payload.get("sorry_goals", []):
        row.pop("proof_state_id", None)


async def _attach_axiom_audit(
    payload: dict[str, Any],
    snippet: str,
    env_raw: Any,
    *,
    resources: Any,
    lean_repl: Any,
) -> dict[str, Any]:
    """Measure the axiom-hygiene axis and attach it to ``payload``.

    Issues one extra ``{"cmd": "#print axioms <decl>", "env": <n>}`` round-trip
    against the environment the snippet just produced, so Lean itself reports
    the transitive axiom closure of every declaration the snippet introduced.

    **Never raises, never edits another axis.** Every failure mode resolves to
    ``outcome="unknown"`` with a reason — an audit that could not run is an
    unmeasured axis, and an unmeasured axis is not a passing one (policy §6
    rule 5). The primary verdict (``status`` / ``compilation_success`` /
    ``messages``) is returned unchanged on every path.
    """
    if not isinstance(env_raw, int):
        payload["axiom_audit"] = _audit_unknown(
            "The REPL returned no environment id for this call, so there is no "
            "environment in which to resolve the snippet's declarations."
        )
        return payload

    names, complete = _declaration_names(snippet)
    if not names:
        payload["axiom_audit"] = _audit_unknown(
            "No named declaration was found in the snippet, so there is "
            "nothing for '#print axioms' to address. A snippet that only "
            "elaborates a term (or declares an unnamed instance) carries no "
            "auditable axiom closure — this is NOT a clean verdict."
            if complete
            else "The snippet's declarations could not be named, so the axiom "
            "closure could not be resolved."
        )
        return payload

    command = {
        "cmd": "\n".join(f"#print axioms {name}" for name in names),
        "env": env_raw,
    }
    try:
        audit_resp = await lean_repl.query(command)
    except LeanReplTimeoutError:
        # Same stale-stdout hazard as the primary path — kill + respawn, then
        # drop the now-dead tokens the primary response minted.
        logger.warning(
            "lean_verify: axiom audit timed out — closing and respawning"
        )
        await _respawn_after_timeout(resources, lean_repl)
        _invalidate_continuation_tokens(payload)
        payload["axiom_audit"] = _audit_unknown(
            "The '#print axioms' round-trip exceeded the per-query wall-clock; "
            "the REPL was killed and respawned. The axiom closure is unknown "
            "for this snippet."
        )
        return payload
    except LeanReplError as exc:
        logger.warning("lean_verify: axiom audit REPL error: %s", exc)
        payload["axiom_audit"] = _audit_unknown(
            f"The '#print axioms' round-trip failed ({exc}); the axiom closure "
            "is unknown for this snippet."
        )
        return payload

    payload["axiom_audit"] = _audit_from_messages(
        _project_messages(audit_resp.get("messages")), names, complete
    )
    return payload


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
        Literal["full", "syntax_only", "tactic_step"],
        Field(
            description=(
                "'full' runs elaboration AND kernel verification. "
                "'syntax_only' wraps the snippet in `#check (...)' (or "
                "set_option maxHeartbeats 5000 in <decl> for theorems) "
                "to elaborate without kernel decide-instances + "
                "reducibility — cheap pre-verify for the autoformalizer. "
                "'tactic_step' advances an existing proof state: `snippet` "
                "is a single tactic and `proof_state` carries the state "
                "token to step; env / imports do not apply and "
                "compilation_success is always null."
            ),
        ),
    ] = "full",
    env: Annotated[
        str | None,
        Field(
            description=(
                "Optional opaque continuation token (a prior lean_verify "
                "`env` result) to run this full / syntax_only call on top of "
                "that environment WITHOUT re-importing — pay `import Mathlib` "
                "once, then reuse (~15-180s cold vs ~0.02s warm). Leave "
                "`imports` empty when `env` is set (the environment already "
                "carries them). A token minted before a timeout-triggered "
                "REPL respawn is rejected as invalid-input, never silently "
                "reused."
            ),
        ),
    ] = None,
    proof_state: Annotated[
        str | None,
        Field(
            description=(
                "Opaque proof-state token (a prior `proof_state_id` result) "
                "to advance with mode='tactic_step'. REQUIRED for "
                "tactic_step; must be omitted for full / syntax_only."
            ),
        ),
    ] = None,
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

    # --- Continuation-token decode (lean-verify-continuation-m1) --------
    # Decode env / proof_state tokens against the LIVE REPL generation and
    # FAIL CLOSED before any REPL round-trip. This is where a token minted
    # by a previous REPL instance (after a timeout respawn) is rejected as
    # ``expired`` rather than misbound onto a colliding id in the new
    # process. ``resumed`` feeds ``continuation_status`` on the success path.
    generation = lean_repl.generation
    resumed = False

    if mode == "tactic_step":
        # ``snippet`` is the tactic; ``proof_state`` is mandatory and ``env``
        # does not apply. m5 critique F5: reject a stray env rather than
        # silently ignore it — symmetric with the proof_state rejection in
        # the cmd branch below.
        if env is not None:
            return envelope(
                _invalid_continuation_envelope(
                    mode,
                    continuation_status="malformed",
                    message=(
                        "env is not valid with mode='tactic_step' (env "
                        "continues a full / syntax_only environment). Use "
                        "proof_state to advance a proof."
                    ),
                )
            )
        if proof_state is None:
            return envelope(
                _invalid_continuation_envelope(
                    mode,
                    continuation_status="malformed",
                    message=(
                        "mode='tactic_step' requires a proof_state "
                        "continuation token (the proof state to advance)."
                    ),
                )
            )
        disp, ps_int = _decode_token(proof_state, generation)
        if disp != "resumed":
            return envelope(
                _invalid_continuation_envelope(
                    mode,
                    continuation_status=disp,
                    message=_continuation_reject_message("proof_state", disp),
                )
            )
        resumed = True
        command: dict[str, Any] = {"tactic": snippet, "proofState": ps_int}
    else:
        # full / syntax_only. ``proof_state`` is a tactic_step-only input;
        # rejecting it here keeps the modes from silently crossing wires.
        if proof_state is not None:
            return envelope(
                _invalid_continuation_envelope(
                    mode,
                    continuation_status="malformed",
                    message=(
                        "proof_state is only valid with mode='tactic_step'; "
                        "use env to continue an environment in full / "
                        "syntax_only mode."
                    ),
                )
            )
        env_int: int | None = None
        if env is not None:
            disp, env_int = _decode_token(env, generation)
            if disp != "resumed":
                return envelope(
                    _invalid_continuation_envelope(
                        mode,
                        continuation_status=disp,
                        message=_continuation_reject_message("env", disp),
                    )
                )
            resumed = True
            # m5 critique F3: imports cannot apply to a continued env (Lean
            # rejects a mid-session `import`), and the env already carries
            # its imports. Reject the contradictory combination up front
            # rather than emitting a confusing kernel "invalid import" error.
            if imports_list:
                return envelope(
                    _invalid_continuation_envelope(
                        mode,
                        continuation_status="malformed",
                        message=(
                            "imports cannot be combined with env: the "
                            "environment already carries its imports and Lean "
                            "rejects an import mid-session. Omit imports when "
                            "continuing an env, or omit env to import into a "
                            "fresh environment."
                        ),
                    )
                )
        cmd = _build_command(snippet, imports_list, mode)
        command = (
            {"cmd": cmd} if env_int is None else {"cmd": cmd, "env": env_int}
        )

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
            resp = await lean_repl.query(command)
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
        await _respawn_after_timeout(resources, lean_repl)
        # m5 critique F4: a resumed continuation that then timed out still
        # had its token accepted THIS call — record that, don't claim
        # "not-applicable".
        resumed_status = "resumed" if resumed else "not-applicable"
        return envelope(
            _timeout_envelope(
                mode, DEFAULT_QUERY_TIMEOUT_S, continuation_status=resumed_status
            )
        )
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
                "proof_state_id": None,
                "compilation_success": False,
                "env": None,
                # m5 critique F4 — reflect whether a token was resumed.
                "continuation_status": "resumed" if resumed else "not-applicable",
                "axiom_audit": _audit_not_applicable(
                    "The Lean REPL failed before returning a checked "
                    "environment, so no axiom closure exists to audit."
                ),
            }
        )

    payload = _normalize_response(
        resp, mode, repl_generation=generation, resumed=resumed
    )

    # --- Axiom-hygiene axis (issues #205 / #281 / #332) -----------------
    # A SECOND round-trip, because the axiom closure is only knowable after
    # the declarations exist in an environment. Runs on the one path where
    # the question is meaningful: a full-mode call whose snippet was actually
    # admitted. Its outcome never edits status / compilation_success — those
    # answer other axes and stay exactly as measured (policy §4).
    if mode == "full" and payload["status"] in ("elaborated_no_errors", "sorry"):
        payload = await _attach_axiom_audit(
            payload,
            snippet,
            resp.get("env"),
            resources=resources,
            lean_repl=lean_repl,
        )
    # Multi-result cap surface — long elaborations can emit hundreds of
    # diagnostic rows; cap_result_list trims the trailing entries from
    # the messages array if the envelope exceeds Config.result_byte_cap.
    capped, _blocks = cap_result_list(envelope(payload), list_key="messages")
    return capped
