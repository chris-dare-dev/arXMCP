"""Lexer-aware source-block extraction for the structural tests.

Issue #495. The structural tests assert things about source text that no
runtime test can reach -- "this diagnostic uses the hex-aware scrubber", "this
middleware is not a Starlette subclass". Those assertions are legitimate, but
they were being made against slices cut two unsound ways:

* a **fixed window** (``source[source.index(sig):][:900]``), which fails
  silently in BOTH directions -- it overruns into the next item when a block
  shrinks, so an assertion passes against a neighbour's code, and it truncates
  when a block grows, so an assertion fails against code that is still
  correct. Both happened repeatedly during the chaos run.

* a **naive brace count**, which treats a ``{`` inside a string literal or a
  comment as structure. ``println!("{}", x)``, a doc-comment drawing a table
  with braces, a regex in a string -- any of them ends the slice early or
  never lets it end.

So the block boundary is found by an actual (small) lexer per language. There
is one copy here rather than one per test module: the previous three copies
of ``_rust_fn`` drifted, and a fix to one did not reach the others.

These extractors raise ``AssertionError`` rather than returning a short slice.
A structural test that cannot find its block must FAIL, not quietly assert
against the wrong text -- that is the whole failure mode #495 is about.
"""

from __future__ import annotations

import ast
import re

# ---------------------------------------------------------------------------
# Rust
# ---------------------------------------------------------------------------


def _rust_spans(source: str) -> list[tuple[int, int]]:
    """Half-open ``[start, end)`` spans of every comment, string and char.

    Everything outside these spans is structure. Handles line comments, NESTED
    block comments (legal in Rust), normal strings with escapes, raw strings
    (``r"..."``, ``r#"..."#`` at any hash count), byte strings, and char
    literals -- the last distinguished from a lifetime, which also starts with
    ``'`` and is extremely common in this codebase's signatures.
    """
    spans: list[tuple[int, int]] = []
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]
        # line comment
        if source.startswith("//", i):
            end = source.find("\n", i)
            end = n if end == -1 else end
            spans.append((i, end))
            i = end
            continue
        # block comment, nested
        if source.startswith("/*", i):
            depth = 0
            j = i
            while j < n:
                if source.startswith("/*", j):
                    depth += 1
                    j += 2
                elif source.startswith("*/", j):
                    depth -= 1
                    j += 2
                    if depth == 0:
                        break
                else:
                    j += 1
            spans.append((i, j))
            i = j
            continue
        # raw string: optional b, then r, then #*, then "
        m = re.match(r'b?r(#*)"', source[i:])
        if m:
            terminator = '"' + m.group(1)
            j = source.find(terminator, i + m.end())
            j = n if j == -1 else j + len(terminator)
            spans.append((i, j))
            i = j
            continue
        # normal or byte string
        if ch == '"' or (ch == "b" and source.startswith('b"', i)):
            j = i + (2 if ch == "b" else 1)
            while j < n:
                if source[j] == "\\":
                    j += 2
                    continue
                if source[j] == '"':
                    j += 1
                    break
                j += 1
            spans.append((i, j))
            i = j
            continue
        # char literal vs lifetime. `'\n'` and `'x'` are literals; `'a` is a
        # lifetime and must NOT be consumed, or the rest of the file shifts.
        if ch == "'":
            if source.startswith("'\\", i):
                j = source.find("'", i + 2)
                j = i + 1 if j == -1 else j + 1
                spans.append((i, j))
                i = j
                continue
            if i + 2 < n and source[i + 2] == "'":
                spans.append((i, i + 3))
                i += 3
                continue
        i += 1
    return spans


def _masked(source: str, spans: list[tuple[int, int]]) -> str:
    """``source`` with every span blanked to spaces -- indices preserved."""
    out = list(source)
    for start, end in spans:
        for pos in range(start, min(end, len(out))):
            if out[pos] != "\n":
                out[pos] = " "
    return "".join(out)


def rust_block(source: str, anchor: str) -> str:
    """The brace-balanced block that STARTS at ``anchor``.

    Braces are counted on a masked copy, so a ``{`` in a string, a char
    literal or a doc comment is not structure. The returned text is the
    ORIGINAL, comments and all -- callers that must not match prose should
    strip comments themselves via :func:`strip_rust_comments`.
    """
    start = source.find(anchor)
    if start == -1:
        raise AssertionError(f"anchor not found: {anchor!r}")
    code = _masked(source, _rust_spans(source))
    depth = 0
    seen_open = False
    for pos in range(start, len(source)):
        char = code[pos]
        if char == "{":
            depth += 1
            seen_open = True
        elif char == "}":
            depth -= 1
            if seen_open and depth == 0:
                return source[start : pos + 1]
    raise AssertionError(f"unbalanced braces after {anchor!r}")


def rust_fn(source: str, signature: str) -> str:
    """The whole body of a Rust fn. Alias of :func:`rust_block`, kept for
    readability at call sites that really are passing a fn signature."""
    return rust_block(source, signature)


_RUST_FN_START = re.compile(
    r"^[ \t]*(?:pub(?:\([^)]*\))?[ \t]+)?(?:const[ \t]+)?(?:async[ \t]+)?"
    r"(?:unsafe[ \t]+)?(?:extern[ \t]+\"[^\"]*\"[ \t]+)?fn[ \t]+\w+",
    re.M,
)


def rust_enclosing_fn(source: str, needle: str) -> str:
    """The fn that CONTAINS ``needle``.

    For assertions anchored on something inside a function -- a `record(...)`
    call, a specific literal -- where the old shape was to slice a fixed
    number of characters backwards and forwards around it and hope the
    function fit. The window was the bug; the anchor was fine.
    """
    at = source.find(needle)
    if at == -1:
        raise AssertionError(f"anchor not found: {needle!r}")
    starts = [m.start() for m in _RUST_FN_START.finditer(source) if m.start() <= at]
    if not starts:
        raise AssertionError(f"no enclosing fn for {needle!r}")
    for start in reversed(starts):
        block = rust_block(source, source[start : source.index("\n", start)])
        if start + len(block) > at:
            return block
    raise AssertionError(f"no enclosing fn contains {needle!r}")


def strip_rust_comments(source: str) -> str:
    """``source`` with comments removed and string literals KEPT.

    The predecessor used two regexes: ``/\\*.*?\\*/`` (which also gutted any
    string containing ``/*``, and stopped at the first ``*/`` inside a nested
    comment) and ``^\\s*//.*$`` (which left every TRAILING ``//`` comment in
    place -- so a negative scan still matched prose on a code line).
    """
    spans = _rust_spans(source)
    comments = [
        (s, e)
        for s, e in spans
        if source.startswith("//", s) or source.startswith("/*", s)
    ]
    out = source
    for start, end in reversed(comments):
        out = out[:start] + out[end:]
    return out


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------


def python_block(source: str, header: str) -> str:
    """One ``def``/``class`` block, resolved with ``ast``.

    Python has a real parser in the stdlib, so this does not guess at all. An
    earlier indentation-based attempt got the same class of bug it was written
    to remove: a multi-line signature puts the closing ``)`` back at the
    *def's own* indent, which reads as "the block ended" one line in.

    ``header`` is the call-site-readable form (``"async def list_notebooks("``,
    ``"class RequestLineSizeLimitMiddleware:"``); only the NAME is used.
    Decorators are included -- a structural test asserting about a route
    usually cares about its decorator. A name defined more than once raises
    rather than picking one, because "which one did the assertion run
    against" is exactly the question these tests must not leave open.
    """
    m = re.match(r"\s*(?:async\s+def|def|class)\s+(\w+)", header)
    if not m:
        raise AssertionError(f"not a def/class header: {header!r}")
    name = m.group(1)
    tree = ast.parse(source)
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name == name
    ]
    if not found:
        raise AssertionError(f"no def/class named {name!r}")
    if len(found) > 1:
        raise AssertionError(f"{name!r} is defined {len(found)} times -- ambiguous")
    node = found[0]
    first = min([node.lineno] + [d.lineno for d in node.decorator_list])
    lines = source.split("\n")
    return "\n".join(lines[first - 1 : node.end_lineno])


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------


def css_block(source: str, selector: str) -> str:
    """One brace-balanced CSS rule, ignoring ``/* */`` and quoted strings."""
    at = source.find(selector)
    if at == -1:
        raise AssertionError(f"selector not found: {selector!r}")
    code = list(source)
    i = 0
    n = len(source)
    while i < n:
        if source.startswith("/*", i):
            j = source.find("*/", i + 2)
            j = n if j == -1 else j + 2
            for pos in range(i, j):
                if code[pos] != "\n":
                    code[pos] = " "
            i = j
            continue
        if source[i] in "\"'":
            quote = source[i]
            j = i + 1
            while j < n and source[j] != quote:
                j += 2 if source[j] == "\\" else 1
            j = min(j + 1, n)
            for pos in range(i, j):
                if code[pos] != "\n":
                    code[pos] = " "
            i = j
            continue
        i += 1
    masked = "".join(code)
    depth = 0
    seen_open = False
    for pos in range(at, n):
        if masked[pos] == "{":
            depth += 1
            seen_open = True
        elif masked[pos] == "}":
            depth -= 1
            if seen_open and depth == 0:
                return source[at : pos + 1]
    raise AssertionError(f"unbalanced braces after {selector!r}")
