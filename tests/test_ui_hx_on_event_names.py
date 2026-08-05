"""Every ``hx-on`` attribute must bind an event htmx actually dispatches.

**arXMCP#383.** All twelve ``hx-on`` attributes in the operator console were
authored as ``hx-on::htmx:after-request`` / ``hx-on::htmx:response-error``. In
htmx's attribute-name normaliser the ``::`` form ALREADY expands to ``htmx:``,
so the doubled prefix produced ``htmx:htmx:after-request`` — an event nothing
dispatches. No error surface in ``/ui/`` had ever displayed anything, and no
form had ever reset on success. The bug predated its discovery by many
milestones and was found only when two independent critics reached for the
vendored bundle.

**Why nothing caught it.** Every existing guard asserts the attribute STRING is
present — ``test_ui_m3``'s ``hx-disabled-elt`` checks, ``test_ui_htmx_json_
contract``, m12's ``hx-ext`` count. Presence is not binding. A test that reads
the attribute name and stops has no way to notice that the name resolves to an
event htmx never fires.

**So this module derives both halves from the shipped bundle**, never from a
hand-list:

1. the NORMALISER — htmx's own ``hx-on`` name-expansion rules, transcribed from
   ``htmx.min.js`` and pinned by :func:`test_the_normaliser_matches_the_bundle`
   so a vendored-htmx upgrade that changes them fails here rather than silently
   invalidating every assertion below;
2. the EVENT VOCABULARY — every ``htmx:*`` literal in the bundle, plus the
   kebab-case aliases htmx generates for them.

A hand-listed vocabulary would have to be updated on every htmx bump and would
rot exactly the way the bug it guards against did.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FRONTEND: Path = REPO_ROOT / "server" / "frontend"
HTMX_JS: str = (FRONTEND / "static" / "htmx.min.js").read_text(encoding="utf-8")
TEMPLATES: list[Path] = sorted((FRONTEND / "templates").glob("*.html"))

#: Matches any ``hx-on`` / ``data-hx-on`` attribute NAME in authored markup.
_HX_ON_ATTR = re.compile(r"\b((?:data-)?hx-on[:-][^\s=]*)\s*=")


def normalise(attr_name: str) -> str | None:
    """htmx's own ``hx-on`` attribute-name -> event-name expansion.

    Transcribed from the vendored bundle::

        const o = n.indexOf("-on") + 3;
        const i = n.slice(o, o + 1);
        if (i === "-" || i === ":") {
            let e = n.slice(o + 1);
            if (l(e, ":"))          { e = "htmx" + e }
            else if (l(e, "-"))     { e = "htmx:" + e.slice(1) }
            else if (l(e, "htmx-")) { e = "htmx:" + e.slice(5) }
            Dt(t, e, r)
        }

    where ``l(e, t)`` is ``e.substring(0, t.length) === t``. Returns ``None``
    when htmx would not treat the attribute as an ``hx-on`` binding at all.
    """
    idx = attr_name.find("-on")
    if idx == -1:
        return None
    o = idx + 3
    sep = attr_name[o : o + 1]
    if sep not in ("-", ":"):
        return None
    rest = attr_name[o + 1 :]
    if rest.startswith(":"):
        return "htmx" + rest
    if rest.startswith("-"):
        return "htmx:" + rest[1:]
    if rest.startswith("htmx-"):
        return "htmx:" + rest[5:]
    return rest


def _camel_to_kebab(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()


def htmx_event_vocabulary() -> set[str]:
    """Every ``htmx:*`` event the bundle names, in both spellings.

    htmx dispatches camelCase internally (``htmx:afterRequest``) and also
    honours the kebab alias (``htmx:after-request``), which is the spelling
    this product authors. Deriving both from the bundle means an htmx upgrade
    that renames an event surfaces here.
    """
    names = set(re.findall(r"htmx:([A-Za-z][A-Za-z0-9]*)", HTMX_JS))
    vocab: set[str] = set()
    for n in names:
        vocab.add(f"htmx:{n}")
        vocab.add(f"htmx:{_camel_to_kebab(n)}")
    return vocab


def authored_hx_on_attributes() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    for path in TEMPLATES:
        text = re.sub(r"\{#.*?#\}", "", path.read_text(encoding="utf-8"), flags=re.S)
        out.extend((path, m.group(1)) for m in _HX_ON_ATTR.finditer(text))
    return out


# ---------------------------------------------------------------------------
# The guards
# ---------------------------------------------------------------------------
def test_the_normaliser_matches_the_bundle() -> None:
    """Pin the transcription. Everything below is only as good as this.

    If a vendored-htmx upgrade changes the expansion rules, the assertions in
    this module would keep passing against a stale model of htmx's behaviour —
    which is precisely the failure mode #383 was.
    """
    assert 'l(e,":")' in HTMX_JS or 'l(e, ":")' in HTMX_JS, (
        "the vendored htmx no longer branches on a leading ':' in hx-on names; "
        "re-read its normaliser and update normalise() before trusting this file"
    )
    assert 'function l(e,t){return e.substring(0,t.length)===t}' in HTMX_JS, (
        "htmx's startsWith helper changed shape; re-verify normalise()"
    )
    # The behaviour that matters, stated as examples.
    assert normalise("hx-on::after-request") == "htmx:after-request"
    assert normalise("hx-on:htmx:after-request") == "htmx:after-request"
    assert normalise("hx-on::htmx:after-request") == "htmx:htmx:after-request"
    assert normalise("hx-on:click") == "click"


def test_the_vocabulary_is_derived_and_non_trivial() -> None:
    vocab = htmx_event_vocabulary()
    assert len(vocab) > 40, f"only {len(vocab)} htmx events found — regex broke"
    for expected in ("htmx:after-request", "htmx:response-error",
                     "htmx:afterRequest", "htmx:responseError"):
        assert expected in vocab, f"{expected!r} missing from the derived vocabulary"


def test_there_are_hx_on_attributes_to_check() -> None:
    """Vacuity guard: this whole module passes trivially on zero attributes."""
    assert authored_hx_on_attributes(), "no hx-on attributes found — regex broke"


@pytest.mark.parametrize(
    ("path", "attr"),
    authored_hx_on_attributes(),
    ids=lambda v: v.name if isinstance(v, Path) else v,
)
def test_every_hx_on_binds_a_real_htmx_event(path: Path, attr: str) -> None:
    """arXMCP#383's regression.

    An ``hx-on`` naming an htmx event must name one htmx dispatches. Plain DOM
    events (``hx-on:click``) are out of scope — they are not ``htmx:``-prefixed
    and the browser owns that vocabulary.
    """
    event = normalise(attr)
    assert event is not None, f"{path.name}: {attr!r} is not a valid hx-on form"
    if not event.startswith("htmx:"):
        return  # a plain DOM event; the browser's vocabulary, not htmx's
    vocab = htmx_event_vocabulary()
    assert event in vocab, (
        f"{path.name}: {attr!r} binds {event!r}, which the vendored htmx never "
        f"dispatches.\n"
        f"`::` ALREADY expands to `htmx:` — writing `hx-on::htmx:X` doubles the "
        f"prefix and yields `htmx:htmx:X`. Use `hx-on::X`.\n"
        f"This is arXMCP#383: twelve attributes shipped this way and every "
        f"error surface in /ui/ stayed silent for months."
    )


def test_no_attribute_uses_the_doubled_prefix() -> None:
    """The specific shape of #383, named so the failure message teaches it.

    The parametrized test above already covers this, but it fails with a
    vocabulary miss. This one fails with the CAUSE, which is what a reader
    copying an existing attribute needs to see.
    """
    offenders = [
        f"{path.name}: {attr}"
        for path, attr in authored_hx_on_attributes()
        if ":htmx:" in attr
    ]
    assert not offenders, (
        "attributes using the doubled `::htmx:` prefix:\n  "
        + "\n  ".join(offenders)
        + "\n\n`hx-on::X` means `htmx:X`. Drop the redundant `htmx:`."
    )
