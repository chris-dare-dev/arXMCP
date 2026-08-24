"""The structural tests' extractor is itself tested (#495).

A source-block extractor that silently returns the wrong slice makes every
assertion built on it meaningless while still reporting green. That is the
exact failure #495 names, so the extractor gets the adversarial cases that
broke its predecessors, as executable evidence rather than a claim.
"""

from __future__ import annotations

import pytest

from tests._source_blocks import (
    css_block,
    python_block,
    rust_block,
    rust_enclosing_fn,
    rust_fn,
    strip_rust_comments,
)


def test_a_brace_inside_a_rust_string_is_not_structure() -> None:
    src = 'fn a() {\n    println!("{}", x);\n    let s = "}";\n    mark();\n}\nfn b() {}\n'
    block = rust_fn(src, "fn a()")
    assert "mark();" in block, "the unbalanced `}` in a string ended the fn early"
    assert "fn b()" not in block


def test_a_brace_inside_a_rust_comment_is_not_structure() -> None:
    src = 'fn a() {\n    // closing } in prose\n    /* and { here */\n    mark();\n}\nfn b() {}\n'
    block = rust_fn(src, "fn a()")
    assert "mark();" in block
    assert "fn b()" not in block


def test_nested_block_comments_are_balanced() -> None:
    src = "fn a() {\n    /* outer /* inner */ still comment } */\n    mark();\n}\n"
    assert "mark();" in rust_fn(src, "fn a()")


def test_a_raw_string_is_not_scanned_for_braces() -> None:
    src = 'fn a() {\n    let r = r#"a } brace "quoted" here"#;\n    mark();\n}\nfn b() {}\n'
    block = rust_fn(src, "fn a()")
    assert "mark();" in block
    assert "fn b()" not in block


def test_a_lifetime_is_not_read_as_a_char_literal() -> None:
    """`'a` and `'x'` both start with a quote. Consuming the lifetime as a
    literal shifts every index after it and silently corrupts the slice."""
    src = "fn a<'a>(x: &'a str) {\n    let c = '}';\n    mark();\n}\nfn b() {}\n"
    block = rust_block(src, "fn a<'a>")
    assert "mark();" in block
    assert "fn b()" not in block


def test_a_missing_anchor_fails_loudly() -> None:
    with pytest.raises(AssertionError):
        rust_fn("fn a() {}\n", "fn nope(")


def test_the_enclosing_fn_is_the_one_that_contains_the_needle() -> None:
    src = "fn a() {\n    one();\n}\n\nfn b() {\n    needle();\n}\n\nfn c() {}\n"
    block = rust_enclosing_fn(src, "needle()")
    assert block.startswith("fn b()")
    assert "one();" not in block and "fn c()" not in block


def test_trailing_line_comments_are_stripped_and_strings_survive() -> None:
    src = 'let a = 1; // banned_token here\nlet s = "/* not a comment */";\n'
    out = strip_rust_comments(src)
    assert "banned_token" not in out, "a TRAILING // comment must be stripped"
    assert "/* not a comment */" in out, "a string containing /* must survive"


def test_a_multi_line_python_signature_does_not_end_the_block() -> None:
    """The closing `)` of a wrapped signature sits at the def's own indent —
    the case that broke an indentation-based first attempt."""
    src = (
        "async def f(\n"
        "    a: int,\n"
        ") -> None:\n"
        "    marker = 1\n"
        "\n"
        "def g() -> None:\n"
        "    other = 2\n"
    )
    block = python_block(src, "async def f(")
    assert "marker = 1" in block
    assert "other = 2" not in block


def test_a_python_class_stops_before_a_following_module_level_def() -> None:
    """`_class_block` cut at the next top-level `class`, so a module-level
    `def` after the class was swallowed into it."""
    src = "class A:\n    inside = 1\n\n\ndef after() -> None:\n    outside = 2\n"
    block = python_block(src, "class A:")
    assert "inside = 1" in block
    assert "outside = 2" not in block


def test_an_ambiguous_python_name_is_refused() -> None:
    src = "def f() -> None:\n    a = 1\n\nclass C:\n    def f(self) -> None:\n        b = 2\n"
    with pytest.raises(AssertionError, match="ambiguous"):
        python_block(src, "def f(")


def test_a_css_comment_brace_is_not_structure() -> None:
    src = ".a {\n  /* a } in prose */\n  color: red;\n}\n.b { color: blue; }\n"
    block = css_block(src, ".a {")
    assert "color: red" in block
    assert ".b {" not in block
