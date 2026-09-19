"""Soundness instrumentation for the ``lean_verify`` formal oracle
(stage2/arx-d2 — WS-D D-2 hardening).

``lean_verify``'s ``status: "ok"`` is derived purely from message
severities and the ``sorries`` list — which makes the shipped oracle
*soft*: a snippet declaring ``axiom cheat : <goal>`` and closing the
theorem with ``cheat`` verifies clean (RISKS MA-2; finding 05 §2.A3.1).
This module supplies the pure, subprocess-free half of the D-2 guard
set; ``server/handlers/lean_verify.py`` drives the REPL side:

1. **Snippet guard** — reject snippets that themselves declare
   ``axiom`` / ``opaque`` OR that run elaboration-time code able to
   subvert the kernel — the meta-programming entry points (``#eval`` /
   ``run_cmd`` / ``elab`` / ``macro`` / ``initialize`` / …) and the
   kernel-check-disabling options (``set_option debug.skipKernelTC`` /
   ``debug.skipProofs``) — (:func:`scan_snippet`). The scan is textual
   and deliberately fail-closed: the keyword appearing *anywhere* in
   the snippet (even in a comment or string literal) rejects it.
   Comments are NOT stripped first — a naive comment-stripper that
   disagrees with Lean's lexer about nesting would create a smuggling
   hole, and an over-rejection costs the caller only a snippet rewrite.
   The meta guard closes finding R2-AC-1 (meta kernel-check bypass): a
   snippet that adds a declaration via
   ``Environment.addDeclCore … (doCheck := false)`` bypasses the kernel
   type-check entirely, so a provably-false ``theorem`` inhabits its
   goal through the unchecked constant and ``#print axioms`` — which only
   walks the stored proof term — reports a CLEAN closure, defeating the
   whole axiom-closure audit. See :data:`_META_REJECT_KEYWORDS`.
2. **Advisory flags** — ``native_decide`` / ``unsafe`` / ``partial``
   are flagged (not rejected). ``native_decide`` additionally surfaces
   in the axiom closure as ``Lean.ofReduceBool`` / ``Lean.trustCompiler``,
   so the closure audit catches it even when the textual flag is evaded
   through a macro.
3. **Axiom-closure audit parsing** — :func:`parse_print_axioms_output`
   parses the ``#print axioms <decl>`` info message emitted by the
   REPL; :data:`ALLOWED_AXIOMS` pins the standard trust base
   ``{propext, Classical.choice, Quot.sound}``. Anything else in the
   closure (``sorryAx``, a smuggled custom axiom, ``Lean.ofReduceBool``)
   fails the audit.
4. **Provenance** — :func:`read_repl_provenance` records the
   ``lean-toolchain`` string and the pinned mathlib revision from the
   REPL project's ``lake-manifest.json``; :func:`transcript_sha256`
   produces a replayable content hash over (snippet, imports, mode,
   toolchain, mathlib rev, normalized result). The REPL's volatile
   ``env`` counter is *excluded* by construction (the hash is computed
   over the normalized payload, which never contains ``env``), so two
   runs of the same snippet against the same toolchain produce
   identical hashes (AC-D.3 replayability).
5. **Award rule** — :func:`formal_award_ok` is the pure predicate the
   proving lane uses to decide whether a ``lean_verify`` result can
   support a ``proven-formal`` verdict (finding 05 §4.3 row 1). It is
   fail-closed: any missing or unaudited element denies the award.

No LLM, no subprocess, no MCP registration — this module never touches
``tools/list`` bytes (BP1-safe by construction).

Design references:
- finding 05 §3-R2 (the D-2 spec) and §4.3 (verdict award rules)
- RISKS.md MA-2 (axiom smuggling) and MA-10 (verdict replayability)
- acceptance-criteria.md AC-D.1 / AC-D.2 / AC-D.3
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: The standard Lean 4 / mathlib trust base. A ``proven-formal`` award
#: requires the declaration's axiom closure to be a subset of this set
#: (finding 05 §3-R2; AC-D.2). ``sorryAx``, snippet-smuggled axioms,
#: and the ``native_decide`` compiler axioms are all outside it.
ALLOWED_AXIOMS: frozenset[str] = frozenset(
    {"propext", "Classical.choice", "Quot.sound"}
)

#: Snippet-declared keywords that cause outright rejection before the
#: REPL is consulted. ``axiom`` mints an arbitrary inhabitant of any
#: Prop; ``opaque`` mints an arbitrary constant with no definitional
#: content — both let a snippet manufacture its own trust base.
_REJECT_KEYWORDS: tuple[str, ...] = ("axiom", "opaque")

#: Keywords that are flagged in the result envelope but do not reject
#: the snippet. The award rule (:func:`formal_award_ok`) denies
#: ``proven-formal`` when any of these is present; the caller can still
#: use the kernel outcome as *feedback* (e.g. the tactician exploring
#: with ``native_decide`` before committing to a kernel-checked proof).
_FLAG_KEYWORDS: tuple[str, ...] = ("native_decide", "unsafe", "partial")

_KEYWORD_RES: dict[str, re.Pattern[str]] = {
    kw: re.compile(rf"\b{kw}\b") for kw in (*_REJECT_KEYWORDS, *_FLAG_KEYWORDS)
}

#: Meta-programming and kernel-subversion constructs that also cause
#: outright rejection before the REPL is consulted (finding R2-AC-1 —
#: meta kernel-check bypass). Where ``axiom``/``opaque`` let a snippet
#: mint its own trust base *declaratively*, these let it do so
#: *procedurally*: by running elaboration-time code that mutates the
#: kernel environment WITHOUT the kernel type-check
#: (``Environment.addDeclCore … (doCheck := false)`` /
#: ``Kernel.Environment.addDeclWithoutChecking``), or by disabling the
#: kernel type-check outright (``set_option debug.skipKernelTC`` /
#: ``debug.skipProofs``).
#:
#: The guard blocks the *syntactic entry points* to elaboration-time code
#: execution — parser keywords/commands, NOT the (aliasable, and
#: ``import Mathlib``-transitively-available) ``Lean.*`` API names. This
#: is what makes it a CLASS fix rather than a name blocklist: to run any
#: user code that is not subsequently kernel-checked, a snippet MUST reach
#: command/tactic elaboration through one of these forms (``#eval``,
#: ``run_cmd``/``run_elab``/``run_tac``, ``elab``/``elab_rules``,
#: ``macro``/``macro_rules``/``syntax``, ``initialize``/
#: ``builtin_initialize``). They are parser syntax, so they cannot be
#: renamed to evade the raw-text scan, and a ``macro`` that expands to one
#: still carries the token in its ``macro_rules`` body. Blocking them
#: therefore closes the class even though ``import Mathlib`` brings the
#: whole ``Lean`` meta API into scope — the API is inert without a way to
#: invoke it. A legitimate proof (a ``theorem``/``lemma``/``example``/
#: ``def`` with a term or ``by`` tactic body) needs none of them; like the
#: ``axiom``/``opaque`` guard this is fail-closed — over-rejection costs
#: only a snippet rewrite (the ``addDeclCore`` / ``addDeclWithoutChecking``
#: entries are defense-in-depth against the naive direct-call form; the
#: entry-point blocks above are the load-bearing defense).
_META_REJECT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("#eval", re.compile(r"#eval")),
    ("run_cmd", re.compile(r"\brun_cmd\b")),
    ("run_elab", re.compile(r"\brun_elab\b")),
    ("run_tac", re.compile(r"\brun_tac\b")),
    ("elab_rules", re.compile(r"\belab_rules\b")),
    ("elab", re.compile(r"\belab\b")),
    ("macro_rules", re.compile(r"\bmacro_rules\b")),
    ("macro", re.compile(r"\bmacro\b")),
    ("syntax", re.compile(r"\bsyntax\b")),
    ("builtin_initialize", re.compile(r"\bbuiltin_initialize\b")),
    ("initialize", re.compile(r"\binitialize\b")),
    ("debug.skip", re.compile(r"\bdebug\.skip")),
    ("addDeclCore", re.compile(r"\baddDeclCore\b")),
    ("addDeclWithoutChecking", re.compile(r"\baddDeclWithoutChecking\b")),
)

#: The labels the meta guard can emit into ``rejected_keywords`` — pinned
#: to the ``lean_verify_result.json`` schema enum (kept in sync by
#: ``tests/test_proving_meta_bypass.py``).
_META_REJECT_KEYWORDS: tuple[str, ...] = tuple(
    label for label, _ in _META_REJECT_PATTERNS
)

#: Lean declaration-name extractor for the axiom audit. Matches
#: ``theorem`` / ``lemma`` declarations (optionally prefixed by
#: attributes and modifiers) and captures the declared name, including
#: dotted names. Deliberately conservative: names it cannot parse
#: (unicode identifiers, ``example`` blocks, declarations inside an
#: open ``namespace``) are simply not audited — and the award rule
#: fails closed on an empty audit set.
_DECL_NAME = r"[A-Za-z_][A-Za-z0-9_'!?]*(?:\.[A-Za-z_][A-Za-z0-9_'!?]*)*"
_DECL_RE = re.compile(
    r"(?:^|\n)\s*"
    r"(?:@\[[^\]]*\]\s*)*"  # attributes, e.g. @[simp]
    r"(?:(?:private|protected|noncomputable|scoped|local)\s+)*"
    rf"(?:theorem|lemma)\s+({_DECL_NAME})"
)

#: Statement-declaration matcher for :func:`extract_proved_statement`.
#: A SUPERSET of ``_DECL_RE``: it additionally matches anonymous
#: ``example`` blocks (which carry NO name and so are deliberately
#: absent from ``_DECL_RE``, whose job is name-extraction for the axiom
#: audit). The skeptic lane's canonical witness form is an anonymous
#: ``example : ¬ P := by …`` (``skeptic.py`` module docstring, and the
#: KAT fixture's ``kat-fm-02`` witness) — extracting its *statement*
#: (not its name) is exactly what refutation statement-linkage needs
#: (findings: refutation-witness-skips-statement-linkage; math-r2 nit
#: "extract_proved_statement does not name-extract anonymous example
#: blocks"). Matching ``example`` here can only ENABLE a linkage check
#: to run over more witness forms; a botched extraction can still only
#: DENY an award, never grant one (the comparison is against a declared
#: target the untrusted author cannot make the kernel prove without
#: actually proving it).
_STMT_DECL_RE = re.compile(
    r"(?:^|\n)\s*"
    r"(?:@\[[^\]]*\]\s*)*"  # attributes, e.g. @[simp]
    r"(?:(?:private|protected|noncomputable|scoped|local)\s+)*"
    rf"(?:(?:theorem|lemma)\s+{_DECL_NAME}|example)"
)

#: ``#print axioms`` output shapes (leanprover-community/repl emits the
#: message as an info-severity ``data`` string).
_DEPENDS_RE = re.compile(r"depends on axioms:\s*\[([^\]]*)\]", re.DOTALL)
_NO_AXIOMS_RE = re.compile(r"does not depend on any axioms")

#: ``#check @<name>`` output shape (leanprover-community/repl emits the
#: info-severity ``data`` as ``<name> : <fully-elaborated-type>`` — spike
#: p1-step-1, live-probed on the D-1 mathlib REPL v4.30.0-rc2). Examples:
#: ``spike_foo : ∀ (n : Nat), n + 0 = n`` (Π-telescope reflected),
#: ``spike_bar : 1 = 1 → True`` (hypothesis binder as an arrow). The type
#: is everything after the FIRST ``" : "`` that follows the queried name;
#: because we anchor on the EXACT name we asked about (identifier-shaped,
#: never containing a space-colon-space), the split is unambiguous even
#: when the type itself contains colons.


@dataclass(frozen=True)
class SnippetScan:
    """Result of the textual pre-REPL soundness scan."""

    rejected_keywords: tuple[str, ...]
    flags: tuple[str, ...]

    @property
    def rejected(self) -> bool:
        return bool(self.rejected_keywords)


def scan_snippet(snippet: str) -> SnippetScan:
    """Scan a Lean snippet for smuggling keywords and advisory flags.

    Fail-closed textual scan (word-boundary regex over the raw snippet;
    comments/strings are NOT excluded — see the module docstring for
    why). ``rejected_keywords`` non-empty means the handler must refuse
    to elaborate the snippet at all. Two rejection families share this
    scan: the declarative trust-base minters (``axiom``/``opaque``) and
    the procedural kernel-subverters (:data:`_META_REJECT_PATTERNS` —
    the meta-programming entry points and kernel-check-disabling
    options; finding R2-AC-1).
    """
    rejected: list[str] = [
        kw for kw in _REJECT_KEYWORDS if _KEYWORD_RES[kw].search(snippet)
    ]
    seen = set(rejected)
    for label, pattern in _META_REJECT_PATTERNS:
        if label not in seen and pattern.search(snippet):
            rejected.append(label)
            seen.add(label)
    flags = tuple(
        kw for kw in _FLAG_KEYWORDS if _KEYWORD_RES[kw].search(snippet)
    )
    return SnippetScan(rejected_keywords=tuple(rejected), flags=flags)


def extract_decl_names(snippet: str) -> list[str]:
    """Extract auditable ``theorem`` / ``lemma`` names from a snippet.

    Returns names in source order, deduplicated. Names are
    identifier-shaped by construction of the regex, so interpolating
    them into a ``#print axioms <name>`` command is injection-safe.
    """
    seen: dict[str, None] = {}
    for m in _DECL_RE.finditer(snippet):
        seen.setdefault(m.group(1))
    return list(seen)


#: Bracket pairs whose interior must be skipped when scanning for the
#: top-level ``:`` (type opener) and ``:=`` (body separator) of a
#: declaration — a binder like ``(m : Nat)`` contains a ``:`` that is
#: NOT the type opener, and ``⟨a, b⟩`` / ``{x // p x}`` similarly nest.
_OPEN_TO_CLOSE: dict[str, str] = {"(": ")", "[": "]", "{": "}", "⟨": "⟩"}
_CLOSERS: frozenset[str] = frozenset(_OPEN_TO_CLOSE.values())


def _strip_lean_comments(snippet: str) -> str:
    """Remove Lean comments from a snippet for the STATEMENT-EXTRACTION
    (grant) path ONLY — a one-directional-safe scrubber.

    Handles both Lean comment forms, matching Lean's own lexer grain:

    - **Nested block comments** ``/- … -/`` — Lean block comments NEST,
      so ``/- outer /- inner -/ still outer -/`` is one comment. A
      depth counter (not a non-greedy regex) is required to strip them
      correctly; a naive ``/-.*?-/`` would stop at the first ``-/`` and
      leave the tail ``still outer -/`` in the snippet.
    - **Line comments** ``-- …`` — to end of line (the newline is kept
      so line/telescope structure is preserved for the extractor's
      line-anchored ``_STMT_DECL_RE``).

    **Why this is safe in ONE direction (and only for extraction).**
    :func:`extract_proved_statement` compares its result, fail-closed,
    against a gate-checked formalization (proof side) or an
    author-declared target the kernel must INDEPENDENTLY prove
    (refutation side). Stripping comments can only make the extractor
    return ``None`` or a shorter/real statement — i.e. it can only cause
    an award to be DENIED, never granted. It therefore closes the
    comment-injection hole (a ``/- theorem fake : <TARGET> := by sorry
    -/`` before a trivial ``theorem real : True := by trivial`` made the
    regex match the COMMENTED ``fake`` first and return ``<TARGET>``, a
    proposition the kernel never elaborated) without opening any new
    one: over-stripping is the safe direction.

    **This is the OPPOSITE safety direction from
    :func:`scan_snippet`.** The axiom/opaque snippet guard must stay
    fail-closed over the RAW snippet — a commented ``axiom`` keyword
    should still REJECT the snippet, because there an over-rejection is
    safe and a comment-stripper that disagreed with Lean's lexer about
    nesting would be a smuggling hole (module docstring §1). Here the
    grain is inverted: reading phantom comment text GRANTS linkage, so
    the phantom text must be removed. The two uses are deliberately not
    shared. This helper is for the extraction/grant path only; DO NOT
    reuse it in :func:`scan_snippet`.

    Not a full Lean lexer: it does not model string literals or
    character literals (a ``"/-"`` inside a Lean string would be treated
    as a comment opener). That is deliberately the SAFE direction for
    this use — mis-stripping inside a string can only shorten/blank the
    extracted statement and deny an award, never fabricate a match.
    """
    out: list[str] = []
    i = 0
    n = len(snippet)
    block_depth = 0
    while i < n:
        two = snippet[i : i + 2]
        if block_depth > 0:
            # Inside a (possibly nested) block comment: consume until the
            # depth returns to zero, emitting nothing.
            if two == "/-":
                block_depth += 1
                i += 2
            elif two == "-/":
                block_depth -= 1
                i += 2
            else:
                i += 1
            continue
        if two == "/-":
            block_depth += 1
            i += 2
            continue
        if two == "--":
            # Line comment: skip to (but keep) the end of line so the
            # extractor's line-anchored declaration regex still sees the
            # surrounding line structure.
            j = snippet.find("\n", i + 2)
            if j == -1:
                break
            i = j
            continue
        out.append(snippet[i])
        i += 1
    return "".join(out)


def extract_proved_statement(snippet: str) -> str | None:
    """Extract the *proposition the declaration proves* — the FIRST
    ``theorem`` / ``lemma`` / ``example`` in a snippet, reflecting its
    FULL binder telescope.

    **RETIRED from the linkage GRANT path (durable P1 soundness fix).**
    This text-scanner is NO LONGER the source of truth for any linkage
    grant. Both linkage sites — the proof-side ``proof_statement_linked``
    award and the refutation-side ``refutation_statement_linked`` kernel
    half — now consume the KERNEL-reported elaborated type (the
    ``kernel_statements`` field of the ``lean_verify`` envelope, selected
    via :func:`kernel_statement_for_snippet`), never this scan. The
    reason is the *class* of blind spot an author-text parse always has
    (unicode identifiers, string literals containing ``theorem``,
    multi-declaration snippets, ``where``-clauses, macro-generated
    decls); the kernel never sees comments, string contents, or unqueried
    trailing decls, so it cannot be tricked into reporting a phantom type.
    The function is retained only for its own unit tests and as a
    documented scanner; production grants do not call it. (``scan_snippet``
    — the axiom/opaque guard — is unaffected and stays fail-closed over
    the raw snippet: it is correct as-is.)

    Returns the text between the declaration's top-level ``:`` (the
    type ascription that opens the proposition) and its top-level
    ``:=`` (the body separator), whitespace-collapsed via
    :func:`server.proving.faithfulness.normalize_lean` grain (here
    inlined to avoid a cross-module import cycle). Binder colons
    (``(m : Nat)``) and nested brackets are skipped by a depth-aware
    scan; a ``:=`` inside a bracket (e.g. a structure-instance default)
    is likewise not mistaken for the body separator.

    **Binders are reflected, NOT dropped (round-3 class fix; finding:
    proof-side vacuous-hypothesis binder).** Lean's ``theorem foo
    (h : H₁) : G := …`` proves the *generalization* ``∀ (h : H₁), G``,
    not ``G`` — the kernel type is the whole Π-telescope. An earlier
    revision returned only the text after the top-level ``:``, dropping
    the binders, so ``theorem attack (h : False) : G := h.elim`` — which
    kernel-proves the vacuously-true ``∀ (_ : False), G`` for ANY ``G`` —
    extracted exactly ``G`` and PASSED statement linkage against a
    gate-checked ``G`` while the kernel established nothing about ``G``.
    That defeated the round-1 invariant through a different extractor
    blind spot. Any explicit binder(s) before the top-level ``:`` are
    now preserved verbatim as a leading ``∀ <binders>,`` prefix, so a
    proof carrying a hypothesis (or variable) not present in the
    gate-checked (closed) formalization compares UNEQUAL and fails the
    linkage closed. A genuinely binder-free declaration
    (``theorem d6 : ∀ m n, …`` / ``example : ¬ P``) is unchanged — its
    whole proposition already lives in the type ascription.

    **Lean comments are stripped first (round-3 class fix; finding:
    comment-injection into the statement extractor).** The regex + depth
    scan run over :func:`_strip_lean_comments`\\ (snippet), NOT the raw
    snippet. Otherwise a snippet whose kernel-elaborated content is a
    trivial ``theorem real : True := by trivial`` (so ``witness_ok`` /
    ``kernel_confirmed=True``) but which carries a block comment
    ``/- theorem fake : <TARGET> := by sorry -/`` (or a ``--`` line
    comment) made the regex match the COMMENTED ``theorem fake`` first
    and return ``<TARGET>`` — text the kernel never elaborated —
    granting proof-side ``proven-formal`` (against a gate-checked
    formalization) or refutation-side kernel-linkage (both compared the
    phantom ``<TARGET>``). Stripping is one-directional-safe: it can only
    make extraction return ``None`` or a shorter/real statement, i.e.
    DENY an award, never grant one. This is the OPPOSITE grain from
    :func:`scan_snippet`, which stays fail-closed over the RAW snippet (a
    commented banned keyword must still reject); see
    :func:`_strip_lean_comments`. Comment-free snippets extract
    byte-identically to before.

    Anonymous ``example`` blocks are matched (the skeptic lane's
    canonical witness form ``example : ¬ P := by …``) even though they
    carry no name — the caller wants the *statement*, not a name, and
    the axiom-audit name-extractor (:func:`extract_decl_names`)
    deliberately stays theorem/lemma-only. See :data:`_STMT_DECL_RE`.

    Returns ``None`` when no ``theorem``/``lemma``/``example`` is
    present, or when the declaration has no top-level ``:`` type
    ascription (e.g. a ``:=``-only definition-style form), or when the
    type is empty. Callers MUST treat ``None`` as "statement not
    extractable" and fail closed — this predicate feeds BOTH the
    proof-side statement-linkage award gate (findings #1/#2: a
    kernel-clean proof of the wrong statement must never earn
    ``proven-formal``) and the refutation-side witness-linkage gate
    (findings: refutation-witness-skips-statement-linkage — a
    kernel-clean witness of the wrong proposition must never earn a
    confident ``refuted``), where over-rejection only costs the caller
    a snippet rewrite, exactly like the D-2 snippet guard.

    Deliberately NOT a Lean parser — a whitespace/bracket scanner is
    sufficient for the comparison-only use and cannot be tricked into
    *accepting* a mismatched statement (the linkage compares the
    extracted text against a gate-checked formalization or an
    author-declared target the kernel must independently prove; a
    botched extraction can only deny an award, never grant one — and
    reflecting the binders keeps that one-directional safety: it can
    only ADD text a closed formalization lacks, never erase a binder a
    matching proof would need).
    """
    # Strip Lean comments BEFORE the regex + depth scan so a phantom
    # declaration hidden in a `/- … -/` block or a `-- …` line comment
    # cannot be matched and returned as the proved statement (finding:
    # comment-injection into the statement extractor). One-directional
    # safe — see `_strip_lean_comments`. `scan_snippet` (the axiom guard)
    # deliberately does NOT do this; the two uses have opposite safety
    # directions.
    snippet = _strip_lean_comments(snippet)
    m = _STMT_DECL_RE.search(snippet)
    if m is None:
        return None
    binder_start = m.end()  # just past the theorem/lemma name (or `example`)
    i = binder_start
    n = len(snippet)
    depth = 0
    type_start: int | None = None
    while i < n:
        ch = snippet[i]
        if ch in _OPEN_TO_CLOSE:
            depth += 1
        elif ch in _CLOSERS:
            if depth > 0:
                depth -= 1
        elif depth == 0 and ch == ":":
            # ``:=`` at depth 0 before any ``:`` type opener means a
            # definition-style body with no ascribed proposition.
            if i + 1 < n and snippet[i + 1] == "=":
                return None
            type_start = i + 1
            break
        i += 1
    if type_start is None:
        return None
    # The binder telescope: everything between the declaration name and
    # the top-level ``:``. Non-empty ⇒ the declaration proves a
    # generalization ``∀ <binders>, <type>``, which we reflect so the
    # linkage sees the WHOLE proved proposition (round-3 binder fix).
    binders = _WS_COLLAPSE_RE.sub(" ", snippet[binder_start:i]).strip()
    # Scan for the top-level ``:=`` that closes the type.
    depth = 0
    j = type_start
    type_end: int | None = None
    while j < n:
        ch = snippet[j]
        if ch in _OPEN_TO_CLOSE:
            depth += 1
        elif ch in _CLOSERS:
            if depth > 0:
                depth -= 1
        elif depth == 0 and ch == ":" and j + 1 < n and snippet[j + 1] == "=":
            type_end = j
            break
        j += 1
    type_text = snippet[type_start:type_end] if type_end is not None else snippet[type_start:]
    type_text = _WS_COLLAPSE_RE.sub(" ", type_text).strip()
    if not type_text:
        return None
    if binders:
        # Reflect the Π-telescope the kernel actually proved. The exact
        # surface syntax need not round-trip through Lean (this text is
        # never fed back to the kernel — it is compared, fail-closed,
        # against a gate-checked/declared target); what matters is that
        # a bound hypothesis absent from the closed formalization makes
        # the strings differ, denying the award.
        return f"∀ {binders}, {type_text}"
    return type_text


#: Whitespace collapser for statement extraction (comparison grain
#: mirrors ``faithfulness.normalize_lean``; kept local so this module
#: has no import dependency on the proving package).
_WS_COLLAPSE_RE = re.compile(r"\s+")


def parse_print_axioms_output(text: str) -> list[str] | None:
    """Parse the message body of a ``#print axioms <decl>`` command.

    Returns the axiom name list (``[]`` when the declaration depends on
    no axioms), or ``None`` when the text matches neither known shape —
    callers must treat ``None`` as an audit failure (fail closed).
    """
    if _NO_AXIOMS_RE.search(text):
        return []
    m = _DEPENDS_RE.search(text)
    if m is None:
        return None
    return [a.strip() for a in m.group(1).split(",") if a.strip()]


def closure_ok(axioms: set[str] | frozenset[str] | list[str]) -> bool:
    """True iff every axiom in the closure is in the standard trust base."""
    return set(axioms) <= ALLOWED_AXIOMS


def parse_check_type_output(text: str, name: str) -> str | None:
    """Parse the message body of a ``#check @<name>`` command into the
    declaration's fully-elaborated KERNEL type string.

    The REPL emits ``<name> : <type>`` on the info message for a known
    declaration (spike p1-step-1). This strips the leading ``<name> :``
    prefix — anchored on the EXACT ``name`` queried, so a colon inside
    the type cannot confuse the split — and whitespace-normalizes the
    remainder with the same grain as
    :func:`server.proving.faithfulness.normalize_lean` (inlined here to
    avoid a cross-module import cycle, exactly as
    :func:`extract_proved_statement` does).

    Returns ``None`` (fail-closed) when the text does not begin with the
    queried name followed by a top-level ``:`` — e.g. an
    ``Unknown identifier`` error (an anonymous ``example`` has no name to
    query, and a phantom decl hidden in a comment or string literal is
    invisible to the kernel, so ``#check @fake`` errors). A ``None`` here
    denies statement linkage downstream — the kernel is authoritative and
    a name it does not know yields no statement.
    """
    if not text or not isinstance(text, str) or not name:
        return None
    stripped = text.strip()
    # The prefix is the exact name we asked about followed by a colon.
    # ``re.escape(name)`` keeps unicode identifiers literal; ``\s*:\s*``
    # tolerates the REPL's ``<name> : <type>`` spacing.
    prefix = re.compile(rf"^{re.escape(name)}\s*:\s*")
    m = prefix.match(stripped)
    if m is None:
        return None
    type_text = _WS_COLLAPSE_RE.sub(" ", stripped[m.end() :]).strip()
    return type_text or None


def kernel_check_snippet(snippet: str, target: str, decl: str) -> str:
    """Build the combined command that makes THE KERNEL decide whether
    ``@decl`` (declared in ``snippet``) proves the proposition ``target``.

    The shape is the original snippet followed by an anonymous ``example``
    that ascribes ``target`` and inhabits it with ``@decl``::

        <snippet>
        example : <target> := @<decl>

    Elaborated in one env (the injected ``lean_verify`` re-elaborates the
    whole thing in a fresh env per call), the ``example`` type-checks IFF
    ``@decl``'s kernel type is DEFINITIONALLY EQUAL to ``target`` — the
    durable P1 soundness fix that replaces pretty-print string equality
    (``∃ x : ℝ, …`` and ``∃ x : ℚ, …`` delaborate to the SAME string but
    are NOT defeq, so the kernel denies the collision; conversely ``Nat``
    vs ``ℕ`` or reordered binders ARE defeq, so a natural-syntax target
    LINKS — the string-match brittleness vanishes).

    ``@decl`` uses the ``@`` (explicit-args) form so a declaration with
    implicit binders is inhabited without Lean trying to synthesise them
    against the ascribed type. ``decl`` is identifier-shaped by
    construction of :func:`extract_decl_names` (the only production
    source), so interpolation is injection-safe; ``target`` is author
    text ascribed verbatim — the D-2 snippet guard (which the injected
    handler runs) still rejects ``axiom``/``opaque`` smuggled into it, and
    a malformed ``target`` can only make the ``example`` FAIL to
    type-check (fail-closed), never fabricate a link.
    """
    return f"{snippet}\nexample : {target} := @{decl}"


def kernel_decides_linked(result: Mapping[str, Any] | None) -> bool:
    """Pure acceptance predicate for a :func:`kernel_check_snippet`
    verification result: did the kernel ACCEPT ``example : <target> :=
    @<decl>``?

    ``True`` IFF the combined command verified clean — ``status == "ok"``
    (the handler derives ``ok`` only when there is no error-severity
    message and no ``sorry`` row) AND ``compilation_success is True``
    (full kernel verification succeeded). EVERY other outcome is
    ``False`` (FAIL-CLOSED, the unchanged safety direction):

    - a ``Type mismatch`` (the ℝ-vs-ℚ collision, or any non-defeq target)
      → ``status == "error"`` → not linked;
    - ``sorry`` / ``timeout`` / ``unavailable`` (REPL disabled) / a
      guard-rejected snippet → not ``ok`` → not linked;
    - a ``None``/malformed result (verifier never ran, exception swallowed
      upstream) → not linked.

    A kernel type-check ERROR is therefore NEVER read as "linked" — the
    load-bearing invariant. This predicate is REPL-free and LLM-free
    (AC-D.13 grain): the REPL round-trip happens in the layer that owns
    the verifier; this function only reads the recorded envelope.

    **Self-sufficient soundness (Stage-3 terminating-probe hardening).** A
    ``sorryAx`` *term* proof of a false proposition
    (``example : (0:Nat) = 1 := @sorryAx ((0:Nat) = 1) false``) emits only
    a ``declaration uses 'sorry'`` WARNING — no error-severity message, no
    ``sorries`` row — so the handler derives ``status == "ok"`` and
    ``compilation_success is True`` even though the kernel established
    nothing. ``status``/``compilation_success`` alone therefore do NOT
    prove soundness. This predicate additionally consults the
    axiom-closure audit on the SAME envelope (``sorryAx`` — and any
    smuggled axiom — enters the closure, so ``axiom_closure_ok is
    False``), and denies linkage when it is ``False``. That makes the
    predicate sound on its own terms rather than relying on a caller
    (``formal_award_ok`` / ``witness_ok``) to run a second gate — closing
    the terminating-probe finding. (``sorryAx`` is not caught by the D-2
    snippet guard, which rejects only ``axiom``/``opaque``.)
    """
    if not isinstance(result, Mapping):
        return False
    if result.get("status") != "ok" or result.get("compilation_success") is not True:
        return False
    soundness = result.get("soundness")
    # noqa: SIM103 — keep the explicit deny-then-True form. This is a
    # soundness gate; the guard-clause reading ("deny when the closure
    # audit says False, else grant") is deliberately clearer than a
    # single ``return not (... is False)`` double-negative. Behavior is
    # identical either way; the reconciliation preserves the 99fadb8
    # bytes of the predicate rather than inlining it.
    if isinstance(soundness, Mapping) and soundness.get("axiom_closure_ok") is False:  # noqa: SIM103
        return False
    return True


def kernel_statement_for_snippet(
    snippet: str, kernel_statements: Mapping[str, str] | None
) -> str | None:
    """Select the KERNEL-reported proved statement for a snippet's
    principal declaration from a ``kernel_statements`` map.

    The principal declaration is the FIRST ``theorem`` / ``lemma`` name
    in the snippet (mirrors the "first declaration" semantics the retired
    :func:`extract_proved_statement` used, so callers get the same
    decl-selection contract but sourced from the KERNEL). Returns the
    kernel type recorded for that name, or ``None`` (fail-closed) when:

    - the snippet has no name-extractable ``theorem``/``lemma`` (an
      anonymous ``example`` — the named-declaration contract requires a
      linkage-bearing snippet to be a NAMED theorem/lemma so the kernel
      type is queryable; an ``example`` yields no entry and linkage fails
      closed), or
    - ``kernel_statements`` is absent/empty or carries no entry for that
      name (the kernel-type query failed or was not run — fail-closed).

    This is the authoritative replacement for the text-scanning
    :func:`extract_proved_statement` in the linkage GRANT path: the
    proved proposition comes from the elaborated kernel type, never from
    re-parsing author source (durable P1 soundness fix — the class of
    author-text parse blind spots, unicode identifiers / string literals
    containing ``theorem`` / multi-declaration snippets, cannot fabricate
    a match because the kernel never sees comments, strings, or unqueried
    trailing decls).
    """
    if not isinstance(kernel_statements, Mapping) or not kernel_statements:
        return None
    names = extract_decl_names(snippet)
    if not names:
        return None
    value = kernel_statements.get(names[0])
    return value if isinstance(value, str) and value.strip() else None


# ---------------------------------------------------------------------------
# Provenance (toolchain + mathlib rev + transcript hash)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=8)
def _read_repl_provenance_cached(
    repl_dir_str: str,
) -> tuple[str | None, str | None]:
    repl_dir = Path(repl_dir_str)
    toolchain: str | None = None
    mathlib_rev: str | None = None

    toolchain_file = repl_dir / "lean-toolchain"
    try:
        toolchain = toolchain_file.read_text(encoding="utf-8").strip() or None
    except OSError:
        logger.warning(
            "lean_soundness: could not read %s; toolchain provenance "
            "will be null",
            toolchain_file,
        )

    manifest_file = repl_dir / "lake-manifest.json"
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        for pkg in manifest.get("packages", []):
            if isinstance(pkg, dict) and pkg.get("name") == "mathlib":
                rev = pkg.get("rev")
                mathlib_rev = rev if isinstance(rev, str) and rev else None
                break
    except (OSError, json.JSONDecodeError, AttributeError):
        logger.warning(
            "lean_soundness: could not read/parse %s; mathlib provenance "
            "will be null",
            manifest_file,
        )
    return toolchain, mathlib_rev


def read_repl_provenance(
    repl_dir: Path | str | None,
) -> tuple[str | None, str | None]:
    """Read ``(lean-toolchain, mathlib rev)`` from a REPL project dir.

    Either element is ``None`` when unavailable (file missing, mathlib
    not a dependency of the REPL project, dir unset). Results are
    cached per directory — the pins change only on a deliberate
    toolchain rebuild, which restarts the server.
    """
    if repl_dir is None:
        return None, None
    return _read_repl_provenance_cached(str(repl_dir))


#: Envelope keys excluded from the transcript hash. ``provenance``
#: contains the hash itself; ``corpus_version`` is retrieval-side state
#: with no bearing on the formal result (and would break replay
#: comparisons across corpus updates).
_HASH_EXCLUDED_KEYS: frozenset[str] = frozenset({"provenance", "corpus_version"})


def transcript_sha256(
    *,
    snippet: str,
    imports: list[str],
    mode: str,
    lean_toolchain: str | None,
    mathlib_rev: str | None,
    payload: dict[str, Any],
) -> str:
    """Replayable SHA-256 over the verification transcript.

    Material = (snippet, imports, mode, toolchain, mathlib rev,
    normalized result payload). The payload never contains the REPL's
    volatile ``env`` counter (``_normalize_response`` drops it), so the
    hash is stable across runs of the same snippet on the same
    toolchain — the formal-lane analogue of the ``corpus_version``
    discipline (finding 05 §3-R2c; RISKS MA-10).
    """
    material = {
        "imports": list(imports),
        "lean_toolchain": lean_toolchain,
        "mathlib_rev": mathlib_rev,
        "mode": mode,
        "payload": {
            k: v for k, v in payload.items() if k not in _HASH_EXCLUDED_KEYS
        },
        "snippet": snippet,
    }
    blob = json.dumps(
        material, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# The proven-formal award predicate (pure; finding 05 §4.3 row 1)
# ---------------------------------------------------------------------------

#: Flags whose presence denies a ``proven-formal`` award outright.
#: ``native_decide`` / ``unsafe`` bypass or extend the kernel trust
#: base; ``partial`` marks definitions with no definitional content.
_AWARD_DENY_FLAGS: frozenset[str] = frozenset(_FLAG_KEYWORDS)


def formal_award_ok(result: dict[str, Any]) -> tuple[bool, list[str]]:
    """Decide whether a hardened ``lean_verify`` result can support a
    ``proven-formal`` verdict.

    Pure function over the result envelope — unit-testable without an
    LLM or a REPL (AC-D.13 discipline). Returns ``(ok, reasons)`` where
    ``reasons`` lists every unmet requirement (empty iff ``ok``).
    Fail-closed: absent fields are treated as unmet requirements.
    """
    reasons: list[str] = []
    if result.get("status") != "ok":
        reasons.append(f"status is {result.get('status')!r}, not 'ok'")
    if result.get("mode") != "full":
        reasons.append("mode is not 'full' (kernel verification required)")
    if result.get("compilation_success") is not True:
        reasons.append("compilation_success is not True")
    soundness = result.get("soundness")
    if not isinstance(soundness, dict):
        reasons.append("result carries no soundness block (unhardened oracle)")
        return False, reasons
    if soundness.get("guard") != "passed":
        reasons.append("snippet guard did not pass (axiom/opaque declared)")
    if soundness.get("audit_status") != "ok":
        reasons.append(
            f"axiom audit did not complete "
            f"(audit_status={soundness.get('audit_status')!r})"
        )
    if soundness.get("axiom_closure_ok") is not True:
        reasons.append(
            "axiom closure is not within {propext, Classical.choice, "
            "Quot.sound}"
        )
    if not soundness.get("audited_decls"):
        reasons.append("no declarations were audited")
    deny = _AWARD_DENY_FLAGS & set(soundness.get("flags") or ())
    if deny:
        reasons.append(f"forbidden flags present: {sorted(deny)}")
    return (not reasons, reasons)


__all__ = [
    "ALLOWED_AXIOMS",
    "SnippetScan",
    "closure_ok",
    "extract_decl_names",
    "extract_proved_statement",
    "formal_award_ok",
    "kernel_check_snippet",
    "kernel_decides_linked",
    "kernel_statement_for_snippet",
    "parse_check_type_output",
    "parse_print_axioms_output",
    "read_repl_provenance",
    "scan_snippet",
    "transcript_sha256",
]
