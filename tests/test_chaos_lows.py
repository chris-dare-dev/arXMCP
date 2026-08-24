"""The chaos-run lows: diagnostics, disclosure and input bounds.

None of these change what the software can do; they change what it says and
what it accepts. Grouped by where the fix lives rather than by ticket.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
SUP: Path = REPO_ROOT / "apps" / "desktop" / "crates" / "supervisor" / "src"
MAIN_RS: str = (SUP / "main.rs").read_text(encoding="utf-8")
LIFECYCLE_RS: str = (SUP / "lifecycle.rs").read_text(encoding="utf-8")


def _rust_fn(source: str, signature: str) -> str:
    """The whole body of a top-level Rust fn, brace-balanced.

    Replaces the `source[source.index(sig):][:900]` shape that this file used
    throughout. A fixed window is wrong in both directions and fails silently
    each way: it OVERRUNS into the next function when a block shrinks (so an
    assertion passes against a neighbour's code) and TRUNCATES when a block
    grows (so an assertion fails against code that is still correct). The
    latter happened four separate times in this session's work -- most
    recently when #464's rotation block pushed `.append(true)` past character
    900 of `open_private_log`.

    rustfmt puts a top-level fn's closing brace at column 0, but braces are
    counted rather than trusted so a nested item cannot end the slice early.
    """
    start = source.index(signature)
    depth = 0
    seen_open = False
    for pos in range(start, len(source)):
        char = source[pos]
        if char == "{":
            depth += 1
            seen_open = True
        elif char == "}":
            depth -= 1
            if seen_open and depth == 0:
                return source[start : pos + 1]
    raise AssertionError(f"unbalanced braces after {signature!r}")
MAIN_PY: str = (REPO_ROOT / "server" / "main.py").read_text(encoding="utf-8")
CLI_PY: str = (REPO_ROOT / "server" / "cli.py").read_text(encoding="utf-8")
SESSION_PY: str = (REPO_ROOT / "server" / "session.py").read_text(encoding="utf-8")
CORPUS_PY: str = (REPO_ROOT / "server" / "corpus.py").read_text(encoding="utf-8")
MIDDLEWARE_PY: str = (REPO_ROOT / "server" / "middleware.py").read_text(encoding="utf-8")
def _class_block(source: str, name: str) -> str:
    """One class body, cut at the next top-level `class`.

    A fixed-size window overran into the NEXT class's docstring — which
    mentions the very thing the assertion forbids — so the guard failed on
    prose belonging to a different class. Third time this pattern has bitten
    in this run; extract the block instead of guessing a length.
    """
    start = source.index(f"class {name}:")
    rest = source[start + 1 :]
    end = rest.find("\nclass ")
    return rest if end == -1 else rest[:end]


NOTEBOOKS_PY: str = (
    REPO_ROOT / "server" / "routes" / "notebooks.py"
).read_text(encoding="utf-8")
UI_PY: str = (REPO_ROOT / "server" / "routes" / "ui.py").read_text(encoding="utf-8")
INDEX: str = (
    REPO_ROOT / "server" / "frontend" / "templates" / "index.html"
).read_text(encoding="utf-8")
DETAIL: str = (
    REPO_ROOT / "server" / "frontend" / "templates" / "notebook_detail.html"
).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# HTTP surface
# --------------------------------------------------------------------------
def test_root_redirects_to_the_console() -> None:
    """#478. The bind URL printed at startup is the one an operator types."""
    assert 'RedirectResponse(url="/ui/", status_code=307)' in MAIN_PY


def test_metrics_is_method_gated() -> None:
    """#470. prometheus_client's ASGI app does not method-gate, so /metrics
    answered 200 to TRACE and DELETE — out of step with every other route."""
    block = MAIN_PY[MAIN_PY.index("async def metrics_wrapper") :][:1200]
    assert '"GET"' in block and '"HEAD"' in block
    assert "405" in block


def test_the_request_line_is_bounded() -> None:
    """#471. The 1 MB body cap left the target and headers unbounded — the
    cap was on the one input that already had a limit."""
    assert "class RequestLineSizeLimitMiddleware:" in MIDDLEWARE_PY
    assert "RequestLineSizeLimitMiddleware" in MAIN_PY, "must be registered"
    block = _class_block(MIDDLEWARE_PY, "RequestLineSizeLimitMiddleware")
    assert "414" in block, "the specified status for an over-long target"
    assert "431" in block, "the specified status for an over-large header block"


def test_the_size_cap_is_pure_asgi() -> None:
    """BaseHTTPMiddleware is project-banned (E06_S01 F1)."""
    # Assert the STRUCTURE, not the absence of a word: the class docstring
    # explains that BaseHTTPMiddleware is banned, so a substring scan flags
    # the explanation. (Fourth time this trap has fired in this run — ui.js,
    # lifecycle.rs and corpus.py's _smoke_read all documented the construct
    # they must not use.)
    assert "class RequestLineSizeLimitMiddleware:" in MIDDLEWARE_PY, (
        "no base class — a pure-ASGI callable, not a Starlette subclass"
    )
    block = _class_block(MIDDLEWARE_PY, "RequestLineSizeLimitMiddleware")
    assert "async def __call__(self, scope" in block


def test_the_notebook_list_does_not_emit_host_paths() -> None:
    """#469. A list endpoint for a desktop UI does not need absolute paths."""
    block = NOTEBOOKS_PY[NOTEBOOKS_PY.index("async def list_notebooks(") :][:1800]
    assert 'key != "lancedb_path"' in block


def test_the_create_response_keeps_its_documented_field() -> None:
    """The projection is scoped to the LIST on purpose: create's JSON branch
    carries a documented backwards-compatibility commitment."""
    assert '"lancedb_path": lancedb_path,' in NOTEBOOKS_PY


# --------------------------------------------------------------------------
# What errors say
# --------------------------------------------------------------------------
def test_config_errors_do_not_echo_the_input() -> None:
    """#475. pydantic stringifies its whole input, so the 0.0.0.0 rejection
    printed every path the server knows about."""
    assert "def _format_config_error(" in CLI_PY
    assert "_format_config_error(exc)" in CLI_PY
    assert "_format_config_error" in MAIN_PY, (
        "both entry points must fail identically — the uvicorn-CLI path has "
        "its own handler"
    )


def test_the_config_guard_actually_covers_the_import() -> None:
    """The real defect: `from server.main import ...` executes create_app() at
    module scope, so a bad bind host raised during the IMPORT — before the
    guarded Config() was reached. The guard looked correct and covered
    nothing."""
    main_fn = CLI_PY[CLI_PY.index("def main(argv") :]
    guard = main_fn.index("try:")
    imported = main_fn.index("from server.main import _scan_unknown_arxmcp_env_vars")
    assert guard < imported, (
        "the server.main import must sit INSIDE the try (#475)"
    )


def test_the_env_scan_still_raises_for_callers() -> None:
    """Presentation belongs at the entry point; the library must keep raising
    or the failure is untestable and uncomposable."""
    assert "unknown ARXMCP_* environment variables" in MAIN_PY
    scan = MAIN_PY[MAIN_PY.index("unknown ARXMCP_* environment variables") - 600 :][
        :900
    ]
    assert "raise ValueError" in scan


def test_lancedb_errors_drop_the_vendored_build_path() -> None:
    """#476. pyo3 appends the crates.io BUILD MACHINE's path, which buries the
    actionable half and reads as an arXMCP bug in a vendored file."""
    assert "def _trim_vendored_paths(" in CORPUS_PY
    assert CORPUS_PY.count("_trim_vendored_paths(") >= 3, (
        "every operator-facing LanceDB message must be trimmed"
    )


def test_the_trimmer_passes_unrecognised_shapes_through() -> None:
    """A mangled error is worse than a noisy one."""
    from server.corpus import _trim_vendored_paths

    assert _trim_vendored_paths("plain error") == "plain error"
    assert _trim_vendored_paths(
        "real problem, /Users/runner/.cargo/registry/src/x.rs:1:2"
    ) == "real problem"


def test_the_session_docstring_no_longer_overstates_a_bypass() -> None:
    """#474. A security comment claiming an unreachable attack path sends the
    next maintainer to defend something already closed."""
    assert "omitting `Mcp-Session-Id` skips cap enforcement outright" not in (
        SESSION_PY
    )
    assert "That is not reachable" in SESSION_PY


# --------------------------------------------------------------------------
# The console
# --------------------------------------------------------------------------
def test_the_displayed_path_is_shortened_but_not_hidden() -> None:
    """#479. Shortening is not redaction: an operator needs the real path to
    run `make reconcile` or find the files."""
    assert "def _display_path(" in UI_PY
    assert "display_path" in DETAIL
    assert 'title="{{ notebook.lancedb_path }}"' in DETAIL, (
        "the full value must stay reachable"
    )


def test_the_empty_papers_table_has_no_header() -> None:
    """#480. A header row above an empty-state message reads as a glitch."""
    assert "{% if papers %}" in DETAIL
    head = DETAIL.index("<thead>")
    guard = DETAIL.rindex("{% if papers %}", 0, head)
    assert head - guard < 400, "the thead must be inside the guard"


def test_the_slug_field_explains_itself_and_matches_the_server() -> None:
    """#481. Without `title` the browser says only "Please match the requested
    format", and maxlength=64 accepted 33 characters the server always
    rejects."""
    assert 'title="Lowercase letters' in INDEX
    match = re.search(r'name="slug"[^>]*maxlength="(\d+)"', INDEX, re.S)
    assert match is not None and int(match.group(1)) == 31


# --------------------------------------------------------------------------
# Supervisor
# --------------------------------------------------------------------------
def test_the_post_bound_drain_is_bounded() -> None:
    """#486. Child stdout is control-only after `bound`; an unbounded drain
    burned CPU on entirely child-controlled input for the app's lifetime."""
    assert "DRAIN_CAP_BYTES" in LIFECYCLE_RS
    assert '"capped": capped' in LIFECYCLE_RS, (
        "a truncated drain must say so, or the byte count reads as complete"
    )


def test_the_event_prefix_is_charset_restricted() -> None:
    """#487. frame_prefix is the ONE event field carrying raw child bytes, and
    #439 is the case where relying on a single scrub call failed on it."""
    assert "fn printable_ascii(" in LIFECYCLE_RS
    assert "printable_ascii(&scrubbed)" in LIFECYCLE_RS


def test_payload_completeness_is_checked_at_plan_time() -> None:
    """#484. The v1 frame declares fixed probe paths, so the probe is a
    dependency of the plan — but deleting it changed nothing at plan time.

    **This test passed against a fix that covered a third of the issue**, and
    is kept only for what it genuinely proves: that the plan path calls the
    check at all. #484's title names three deletions — the probe, an
    `_internal` Mach-O, and `_CodeSignature` — and a name check can never
    cover the last two, nor a MODIFIED or ADDED file.

    The behavioral coverage is
    `tests/test_desktop_bundle.py::TestPayloadIntegrityAtLaunch`, which
    mutates a clone of the real assembled bundle three ways and requires the
    real supervisor to refuse before `child-spawn`. Verified to fail without
    the fix: the pre-fix binary reached `child-spawn` with
    `_internal/libpython3.12.dylib` deleted.
    """
    assert "fn check_payload_completeness(" in MAIN_RS
    assert "PROBE_EXECUTABLE_NAME" in MAIN_RS
    assert "PAYLOAD_RUNTIME_DIR" in MAIN_RS, (
        "the PyInstaller runtime directory is part of a complete payload too "
        "(#484 round 2)"
    )
    plan = _rust_fn(MAIN_RS, "fn self_authored_plan(")
    assert "check_payload_completeness(" in plan


def test_the_launch_path_consults_the_outer_seal() -> None:
    """#436 round 2 — the executable check is not the payload check.

    Structural on purpose and narrow on purpose: this asserts only that the
    call SITE exists next to the executable check, which is a placement
    property. Whether it detects anything is settled by
    `TestPayloadIntegrityAtLaunch` against the real artifact.
    """
    assert "fn verify_bundle_seal(" in LIFECYCLE_RS
    assert "payload-seal-invalid" in LIFECYCLE_RS
    assert "payload-seal-unavailable" in LIFECYCLE_RS, (
        "the onedir layout has no seal; 'not checked' must not read like "
        "'checked and clean' in the event log"
    )


def test_the_data_root_probe_refuses_an_unusable_derivation() -> None:
    """#485. It emitted a path for a $HOME that is a file and for a RELATIVE
    $HOME — output the program itself would reject."""
    assert "fn check_data_root_shape(" in MAIN_RS
    fn = _rust_fn(MAIN_RS, "fn check_data_root_shape(")
    assert "is_absolute()" in fn
    assert "is_dir()" in fn
