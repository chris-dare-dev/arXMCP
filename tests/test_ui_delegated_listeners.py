"""The operator console's behaviour contract, after issues #431 / #432 / #433.

**What broke.** The console carried its behaviour in eleven inline ``hx-on::``
attributes. htmx compiles an ``hx-on`` body with ``new Function()``; the
console's own CSP (``CONTENT_SECURITY_POLICY_UI`` in ``server/middleware.py``)
grants ``script-src 'self' 'unsafe-inline'`` and deliberately withholds
``'unsafe-eval'``. Every handler threw ``EvalError`` at parse time, so the UI
had no working error display and no post-success cleanup anywhere (#431), a
rejected notebook create looked exactly like a success (#432), and a killed
backend left a stale-but-healthy-looking page (#433).

Note this was the SECOND independent reason those handlers never fired. #383
had already fixed a doubled ``htmx:htmx:`` prefix in the same attributes; that
fix was correct and the handlers stayed dead anyway. ``test_ui_hx_on_event_names``
holds the other half of that history.

**What replaced it.** One external ``ui.js`` — which ``script-src 'self'``
already admits, so no CSP relaxation was needed and #483 stays free to drop
``'unsafe-inline'`` later — plus a declarative contract in the templates:

* ``data-error-target="<id>"`` names where an element's failure text lands;
* ``data-on-success="<token>..."`` names what to do after a successful request.

**Why these tests are derived, not hand-listed.** The failure mode in #383 and
#431 alike was a guard that asserted a string was PRESENT without checking it
RESOLVED to anything. So every assertion below cross-checks two artifacts
against each other: attribute against ui.js implementation, target id against
the template that must contain it, listener against the event htmx actually
dispatches for that failure mode.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FRONTEND: Path = REPO_ROOT / "server" / "frontend"
STATIC: Path = FRONTEND / "static"
TEMPLATES: list[Path] = sorted((FRONTEND / "templates").glob("*.html"))

UI_JS: str = (STATIC / "ui.js").read_text(encoding="utf-8")


def _strip_js_comments(text: str) -> str:
    """Drop /* */ and // comments.

    ui.js DOCUMENTS the constructs it must never use (``new Function()``,
    ``innerHTML``) in its own header, so a raw substring scan flags the
    explanation as the offence. The guards below must read the code.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


UI_JS_CODE: str = _strip_js_comments(UI_JS)
BASE_HTML: str = (FRONTEND / "templates" / "base.html").read_text(encoding="utf-8")

#: ``data-on-success`` tokens ui.js implements, derived from its own source so
#: a token removed there fails here rather than silently becoming a no-op.
_IMPLEMENTED_TOKEN = re.compile(r'name === "([a-z-]+)"')

_ERROR_TARGET = re.compile(r'data-error-target="([^"]+)"')
_ON_SUCCESS = re.compile(r'data-on-success="([^"]+)"')


def _strip_jinja_comments(text: str) -> str:
    return re.sub(r"\{#.*?#\}", "", text, flags=re.S)


def implemented_tokens() -> set[str]:
    return set(_IMPLEMENTED_TOKEN.findall(UI_JS))


def authored_error_targets() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for path in TEMPLATES:
        text = _strip_jinja_comments(path.read_text(encoding="utf-8"))
        out.extend((path, m.group(1)) for m in _ERROR_TARGET.finditer(text))
    return out


def authored_success_tokens() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for path in TEMPLATES:
        text = _strip_jinja_comments(path.read_text(encoding="utf-8"))
        for match in _ON_SUCCESS.finditer(text):
            out.extend((path, token) for token in match.group(1).split() if token)
    return out


# ---------------------------------------------------------------------------
# The script itself
# ---------------------------------------------------------------------------
def test_ui_js_is_loaded_by_the_shell() -> None:
    """An unreferenced ui.js is the same outage in a different place."""
    assert '<script src="/ui/static/ui.js" defer></script>' in BASE_HTML, (
        "base.html must load ui.js, with defer so htmx is defined when it runs"
    )


def test_ui_js_loads_after_htmx() -> None:
    """Order matters: the DOMContentLoaded block reads ``htmx.config``."""
    assert BASE_HTML.index("htmx.min.js") < BASE_HTML.index("ui.js"), (
        "ui.js must be declared after htmx.min.js"
    )


def test_ui_js_uses_no_eval() -> None:
    """The whole point. An eval here re-creates #431 in the fix itself."""
    for forbidden in ("eval(", "new Function("):
        assert forbidden not in UI_JS_CODE, (
            f"ui.js uses {forbidden!r}, which this console's CSP forbids "
            "(script-src has no 'unsafe-eval') — the exact defect of #431"
        )


def test_the_console_ships_no_inline_script() -> None:
    """#483's precondition: nothing inline left for 'unsafe-inline' to serve.

    Asserted here rather than in a CSP test because this is the property the
    templates own. Tightening the header itself is #483's change, not this one.
    """
    for path in TEMPLATES:
        text = _strip_jinja_comments(path.read_text(encoding="utf-8"))
        for match in re.finditer(r"<script\b([^>]*)>", text):
            assert "src=" in match.group(1), (
                f"{path.name} has an inline <script>; move it to ui.js so "
                "#483 can drop 'unsafe-inline' from script-src"
            )


def test_script_src_has_no_unsafe_inline() -> None:
    """#483. The other end of the same policy #431 pulled on.

    #431 could have been "fixed" by ADDING ``'unsafe-eval'`` so htmx's
    ``hx-on::`` attributes would run. That would have loosened this header in
    the same edit that should tighten it. The delegated listener was chosen so
    both moves point the same way, and this guard is what stops a future
    convenience edit from re-adding either token.

    Hashes were never needed: ``'sha256-...'`` is for INLINE scripts, and
    ``test_the_console_ships_no_inline_script`` above proves there are none.
    """
    from server.middleware import CONTENT_SECURITY_POLICY_UI

    policy = CONTENT_SECURITY_POLICY_UI.decode()
    script_src = next(
        d.strip() for d in policy.split(";") if d.strip().startswith("script-src")
    )
    assert script_src == "script-src 'self'", (
        f"script-src must stay exactly \"script-src 'self'\"; got {script_src!r}. "
        "'unsafe-inline' re-opens #483; 'unsafe-eval' re-opens #431."
    )


# ---------------------------------------------------------------------------
# #431 / #432 — failures reach the operator
# ---------------------------------------------------------------------------
def test_response_error_is_handled() -> None:
    """A 4xx/5xx must write to the declared target. This is #432."""
    assert 'addEventListener("htmx:responseError"' in UI_JS


def test_send_error_is_handled_separately() -> None:
    """This is the whole of #433, and it is NOT the same event as above.

    htmx dispatches ``htmx:sendError`` — not ``htmx:responseError`` — when the
    connection is refused. Every handler the console had listened for the
    latter, which is why a killed backend was invisible even in the code paths
    that looked like they covered errors.
    """
    assert 'addEventListener("htmx:sendError"' in UI_JS, (
        "ui.js must listen for htmx:sendError; htmx does NOT emit "
        "htmx:responseError when the connection fails (#433)"
    )


def test_stale_errors_are_cleared_before_a_retry() -> None:
    assert 'addEventListener("htmx:beforeRequest"' in UI_JS, (
        "without this, a retry still shows the previous attempt's error text"
    )


def test_error_text_is_never_written_as_markup() -> None:
    """Response bodies are server- or network-controlled."""
    assert "innerHTML" not in UI_JS_CODE, (
        "ui.js must set textContent, not innerHTML — error bodies are untrusted"
    )


@pytest.mark.parametrize(
    ("path", "target_id"), authored_error_targets(), ids=lambda v: str(v)
)
def test_every_error_target_exists_in_its_template(path: Path, target_id: str) -> None:
    """A ``data-error-target`` naming an absent id fails silently at runtime."""
    text = _strip_jinja_comments(path.read_text(encoding="utf-8"))
    assert f'id="{target_id}"' in text, (
        f"{path.name}: data-error-target={target_id!r} but no element with "
        f'id="{target_id}" exists in that template'
    )


def test_the_console_declares_error_targets() -> None:
    """Guards the regex, and the migration itself: 7 forms surfaced errors."""
    targets = authored_error_targets()
    assert len(targets) >= 7, (
        f"only {len(targets)} data-error-target attributes found; the migration "
        "from hx-on::response-error covered seven forms"
    )


# ---------------------------------------------------------------------------
# post-success cleanup
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("path", "token"), authored_success_tokens(), ids=lambda v: str(v)
)
def test_every_success_token_is_implemented(path: Path, token: str) -> None:
    """An unrecognised token is a silent no-op — the #431 failure shape."""
    name = token.split(":", 1)[0]
    assert name in implemented_tokens(), (
        f"{path.name}: data-on-success token {name!r} is not implemented in "
        f"ui.js (implements: {sorted(implemented_tokens())})"
    )


def test_parameterised_tokens_carry_an_argument() -> None:
    for path, token in authored_success_tokens():
        name, _, arg = token.partition(":")
        if name in {"remove", "remove-closest", "navigate"}:
            assert arg, f"{path.name}: token {token!r} needs an argument"


def test_success_actions_only_run_on_success() -> None:
    """The old attributes all guarded on ``event.detail.successful``."""
    assert "if (!evt.detail.successful)" in UI_JS, (
        "runSuccessTokens must not fire on a failed request"
    )


# ---------------------------------------------------------------------------
# #433 — a dead backend is visible
# ---------------------------------------------------------------------------
def test_connection_lost_banner_exists() -> None:
    assert 'id="connection-lost"' in BASE_HTML
    assert 'role="alert"' in BASE_HTML, (
        "the banner needs role=alert so unhiding it is announced"
    )
    banner = re.search(r'<div id="connection-lost"[^>]*>', BASE_HTML)
    assert banner is not None
    assert "hidden" in banner.group(0), (
        "the banner must start hidden — otherwise it is on screen at all times"
    )


def test_the_banner_reuses_the_themed_error_surface() -> None:
    """It must not define a second themed box.

    ``.error`` already carries the ``--error-bg``/``--danger`` token pair that
    ``tokens.css`` redefines per theme, so borrowing it gets dark mode for free
    AND obeys ui-uplift-m8's rule ladder, which forbids the four-sided border
    and the border-radius a standalone banner would otherwise want.
    """
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    banner = re.search(r'<div id="connection-lost"[^>]*class="([^"]*)"', BASE_HTML)
    assert banner is not None and "error" in banner.group(1).split(), (
        "the banner must carry the .error class so it inherits the themed "
        "surface instead of defining its own"
    )
    assert ".connection-lost[hidden]" in css, (
        "[hidden] must be forced to display:none, or .error's display:block "
        "wins the cascade and the banner never hides"
    )
    block = css[css.index(".connection-lost {") :][:200]
    for forbidden in ("border:", "border-radius"):
        assert forbidden not in block, (
            f".connection-lost sets {forbidden!r}; ui-uplift-m8's rule ladder "
            "is horizontal-only and reserves radius for the control layer"
        )


def test_the_status_badge_is_marked_down_not_replaced() -> None:
    """Replacing the badge element would stop its own 10s poll forever.

    The badge re-emits its ``hx-get``/``hx-trigger`` on every swap, so the
    recovery path depends on the node surviving the outage. ui.js may set text
    and class on it; it must not swap it out.
    """
    assert "status-badge--down" in UI_JS, (
        "ui.js must put the badge into its down state on a connection failure"
    )
    assert "outerHTML" not in UI_JS_CODE, (
        "ui.js must not replace the badge element — that kills the every-10s "
        "poll that lets it recover on its own"
    )


def test_the_down_modifier_is_a_real_css_class() -> None:
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert ".status-badge--down" in css, (
        "ui.js sets status-badge--down; app.css must define it"
    )
