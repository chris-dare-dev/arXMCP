"""The eight frontend mediums from the 2026-08-22 chaos run.

#450 stale count · #451 form never reset · #452 dead slug pattern ·
#453 view-transition errors · #454/#455 horizontal overflow ·
#456 raw JSON on HTML routes · #457 unbounded polling.

Two of them — #451 and half of #450 — were already closed by the delegated
listener in `ui.js` (#431), which is why the assertions here are about what
*remained*: the heading count, and the six others.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FRONTEND: Path = REPO_ROOT / "server" / "frontend"
INDEX: str = (FRONTEND / "templates" / "index.html").read_text(encoding="utf-8")
DETAIL: str = (FRONTEND / "templates" / "notebook_detail.html").read_text(encoding="utf-8")
BASE: str = (FRONTEND / "templates" / "base.html").read_text(encoding="utf-8")
APP_CSS: str = (FRONTEND / "static" / "app.css").read_text(encoding="utf-8")
UI_JS: str = (FRONTEND / "static" / "ui.js").read_text(encoding="utf-8")
UI_PY: str = (REPO_ROOT / "server" / "routes" / "ui.py").read_text(encoding="utf-8")
NOTEBOOKS_PY: str = (
    REPO_ROOT / "server" / "routes" / "notebooks.py"
).read_text(encoding="utf-8")


def _status_branch(name: str) -> str:
    """The `_ingest_status_fragment` branch for one status, and no further.

    A fixed-size window is wrong here: `none` and `running` are ~20 lines
    apart, so a 1400-char slice from one runs straight into the next and the
    assertions read the wrong branch. Cut at the next branch boundary.
    """
    if name == "failed":
        # The fall-through case: no `if`, just a comment marking it.
        start = NOTEBOOKS_PY.index('# status == "failed"')
        return NOTEBOOKS_PY[start : start + 2000]
    start = NOTEBOOKS_PY.index(f'if status == "{name}":')
    rest = NOTEBOOKS_PY[start + 1 :]
    ends = [
        rest.index(marker)
        for marker in ('if status == "', '# status == "failed"')
        if marker in rest
    ]
    return rest[: min(ends)] if ends else rest


# --------------------------------------------------------------------------
# #452 — the slug pattern must COMPILE, or it silently validates nothing
# --------------------------------------------------------------------------
def test_the_slug_pattern_compiles_under_the_v_flag() -> None:
    """HTML compiles `pattern` with the `v` (unicodeSets) flag.

    A pattern that does not compile is IGNORED — the browser logs a warning
    and `checkValidity()` returns true for anything. Measured in Chrome:

        [a-z][a-z0-9-]{2,30}   -> Invalid character in character class
        [a-z][-a-z0-9]{2,30}   -> Invalid character in character class
        [a-z][a-z0-9\\-]{2,30}  -> compiles

    Both unescaped forms fail, including the one that looks safe because a
    leading hyphen is fine under `u`. Only the escape works.
    """
    match = re.search(r'pattern="([^"]+)"', INDEX)
    assert match is not None, "the slug input must keep a pattern"
    pattern = match.group(1)
    assert "\\-" in pattern, (
        f"the hyphen must be backslash-escaped; got {pattern!r} (#452)"
    )
    # Assert against the two forms MEASURED to fail rather than trying to
    # re-derive the `v` flag's rules — a first attempt at that flagged the
    # legitimate ranges `a-z` and `0-9`, which are exactly what a hyphen is
    # allowed to do.
    for broken in ("[a-z][a-z0-9-]{2,30}", "[a-z][-a-z0-9]{2,30}"):
        assert pattern != broken, (
            f"{broken!r} does not compile under the v flag, so the browser "
            "ignores it and validates nothing (#452)"
        )


def test_the_slug_pattern_still_describes_the_server_rule() -> None:
    """Client-side validation that disagrees with the server is worse than
    none — it rejects things the server would accept."""
    match = re.search(r'pattern="([^"]+)"', INDEX)
    pattern = re.sub(r"\\-", "-", match.group(1))
    compiled = re.compile(f"^(?:{pattern})$")
    assert compiled.match("bridgeland-stability")
    assert compiled.match("abc")
    assert not compiled.match("INVALID_Slug!!")
    assert not compiled.match("9leading-digit")
    assert not compiled.match("ab")


# --------------------------------------------------------------------------
# #450 — the heading count must not go stale
# --------------------------------------------------------------------------
def test_the_count_is_addressable_and_recounted() -> None:
    assert 'id="notebooks-count"' in INDEX, (
        "the count needs its own element so it can be updated without "
        "rewriting the heading (#450)"
    )
    assert "recount:#notebooks-count" in INDEX
    assert "function recount(" in UI_JS


def test_the_count_is_derived_not_incremented() -> None:
    """An increment drifts the moment anything else changes the table.

    The rendered rows ARE what the heading claims to be counting, so counting
    them cannot disagree with what the user sees.
    """
    body = UI_JS[UI_JS.index("function recount(") :][:900]
    assert "querySelectorAll" in body
    assert "notebooks-empty" in body, (
        "the empty-state placeholder is a message, not a notebook, and must "
        "be excluded from the count"
    )
    assert "++" not in body and "+ 1" not in body, (
        "count from the DOM rather than incrementing (#450)"
    )


def test_success_tokens_run_after_the_swap_not_after_the_response() -> None:
    """The bug this exposed, and the reason it is worth its own test.

    `htmx:afterRequest` fires when the response arrives, which can be BEFORE
    htmx inserts the new content — so `recount` counted a table without the
    new row and wrote a number one short. `htmx:afterSettle` fires after the
    swap and the settle delay.
    """
    assert 'addEventListener("htmx:afterSettle"' in UI_JS, (
        "success tokens must run on afterSettle so the DOM they act on is "
        "the DOM the user sees (#450)"
    )
    settle = UI_JS[UI_JS.index('addEventListener("htmx:afterSettle"') :][:400]
    assert "runSuccessTokens" in settle


def test_the_requesting_element_is_resolved_per_event() -> None:
    """`afterRequest` fires on the requesting element; `afterSwap` and
    `afterSettle` fire on the SWAP TARGET.

    Measured: afterSettle arrived with `detail.elt` = TBODY, which carries no
    `data-on-success`, so every token silently did nothing. Getting this
    wrong is invisible — no error, just no behaviour.
    """
    assert "function requestingElement(" in UI_JS
    body = UI_JS[UI_JS.index("function requestingElement(") :][:400]
    assert "requestConfig" in body, (
        "detail.requestConfig.elt is the requesting element on both events"
    )


# --------------------------------------------------------------------------
# #453 — a poll must not start a view transition
# --------------------------------------------------------------------------
def test_every_automatic_swap_opts_out_of_view_transitions() -> None:
    """globalViewTransitions is on for USER-initiated swaps.

    Anything that fires on `load` or on a timer will eventually overlap
    another transition; `startViewTransition` then rejects with
    InvalidStateError and htmx does not catch it. Measured before the fix:
    one console error every couple of seconds, forever.
    """
    for source, name in (
        (BASE, "base.html"),
        (DETAIL, "notebook_detail.html"),
        (UI_PY, "routes/ui.py"),
        (NOTEBOOKS_PY, "routes/notebooks.py"),
    ):
        for match in re.finditer(
            r'hx-trigger="(load|every)[^"]*"[^>]*?hx-swap="([^"]*)"', source, re.S
        ):
            assert "transition:false" in match.group(2), (
                f"{name}: an automatic swap "
                f"(hx-trigger={match.group(1)}…) must not start a view "
                f"transition — got hx-swap={match.group(2)!r} (#453)"
            )


def test_global_view_transitions_stays_on_for_user_swaps() -> None:
    """The fix is targeted, not a revert of UPL-13."""
    assert "globalViewTransitions" in UI_JS, (
        "user-initiated swaps keep their crossfade; only automatic ones opt "
        "out"
    )


# --------------------------------------------------------------------------
# #454 / #455 — long unbroken strings wrap instead of scrolling the page
# --------------------------------------------------------------------------
def test_long_paths_and_topics_wrap() -> None:
    assert "overflow-wrap: anywhere" in APP_CSS, (
        "a filesystem path or an unbroken topic token must wrap, not push "
        "the whole page sideways (#454/#455)"
    )
    rule = APP_CSS[APP_CSS.index("overflow-wrap: anywhere") - 200 :][:400]
    assert "dl.meta dd" in rule, "the LanceDB path (#454)"
    assert ".topic-description" in rule, "the topic token (#455)"


# --------------------------------------------------------------------------
# #456 — an HTML route must fail as HTML
# --------------------------------------------------------------------------
def test_html_routes_render_an_html_error() -> None:
    assert (FRONTEND / "templates" / "error.html").is_file()
    assert "def _html_error(" in UI_PY
    detail_route = UI_PY[UI_PY.index("async def ui_notebook_detail") :][:2400]
    assert "_html_error(" in detail_route
    assert "raise HTTPException" not in detail_route, (
        "the HTML route must RETURN a rendered page, not raise into the JSON "
        "handler (#456)"
    )


def test_the_html_error_does_not_leak_the_slug_regex() -> None:
    """The 422 body named the internal pattern — useful to an API caller,
    meaningless to someone who mistyped a URL."""
    detail_route = UI_PY[UI_PY.index("async def ui_notebook_detail") :][:2400]
    assert "[a-z]" not in detail_route, "no regex in an end-user message"
    assert "Notebook names are" in detail_route


def test_the_json_api_still_raises() -> None:
    """The sibling /ui/api/* routes must keep answering JSON."""
    assert UI_PY.count("raise HTTPException") >= 3, (
        "only the two HTML routes changed; the JSON API still raises"
    )


# --------------------------------------------------------------------------
# #457 — polling must not be unbounded at 2s
# --------------------------------------------------------------------------
def test_the_idle_ingest_state_polls_slowly() -> None:
    """`none` polled every 2s forever — ~43,000 requests/day from a window
    left open on a notebook nobody has ingested.

    Not stopped outright: a run started OUTSIDE the UI (`make ingest`,
    tools/notebook_ingest.py) is still discovered, now within a minute
    instead of never. ~1,440/day is a 97% reduction.
    """
    none_block = _status_branch("none")
    assert 'hx-trigger="every 60s"' in none_block, (
        "the idle state must not poll at 2s (#457)"
    )
    assert 'hx-trigger="every 2s"' not in none_block


def test_a_running_ingest_still_polls_fast() -> None:
    """The negative control: a run in progress genuinely wants 2s."""
    running = _status_branch("running")
    assert 'hx-trigger="every 2s"' in running


def test_terminal_states_do_not_poll_at_all() -> None:
    for state in ("success", "failed"):
        block = _status_branch(state)
        assert "hx-trigger" not in block, (
            f"the terminal {state!r} state has nothing to poll for"
        )
