"""ui-uplift-m12 (UPL-1) — corpus before machinery, detail page, v0.

The notebook detail page emitted its seven blocks in *shipping-history* order,
so the only corpus content on it — the papers table — began at a measured
y=1823 of a 2343px document, after six consecutive input forms. m12 reorders it
into the three regions the discovery authored: ruled masthead -> papers ledger
-> one ``<details>`` "Manage this notebook" carrying the five mutation forms.

Guards are grouped by acceptance criterion, plus two the milestone inherits
rather than lists: ladder REACHABILITY (``main >`` is a direct-child
combinator, and the five moved blocks left ``main``'s child list) and the
class-scoping that stops a bare ``summary`` rule from stripping m10's marker.

The rationale for each decision lives at its site — in the template and in
``app.css``. This file pins the decisions; it does not restate them.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from server.notebooks_store import NotebooksStore
from server.routes import notebooks as notebooks_module
from server.routes.notebooks import (
    INGEST_STATE_CUE_ID,
    _ingest_status_fragment,
)
from server.routes.notebooks import router as notebooks_router
from server.routes.ui import router as ui_router
from tools import _notebook_common

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FRONTEND: Path = REPO_ROOT / "server" / "frontend"
FRONTEND_STATIC: Path = FRONTEND / "static"

DETAIL_HTML: str = (FRONTEND / "templates" / "notebook_detail.html").read_text(
    encoding="utf-8"
)
#: Jinja comments stripped. Source-level guards run against THIS, not the raw
#: file: m12's rationale names the very strings some of them forbid, and a
#: guard its own explanation can satisfy is not a guard (the m7 rectify learned
#: that on ``test_text_wrap_is_not_used``).
DETAIL: str = re.sub(r"\{#.*?#\}", "", DETAIL_HTML, flags=re.S)

APP_CSS: str = re.sub(
    r"/\*.*?\*/", "",
    (FRONTEND_STATIC / "app.css").read_text(encoding="utf-8"), flags=re.S,
)

#: The id joining the summary's state cue (template) to its OOB re-render
#: (Python). Spelled literally here rather than imported alone, so a rename on
#: either side has to be made deliberately on all three.
CUE_ID: str = "ingest-state-cue"

#: The authored label (art-direction-scout-brief.md:428-430), not invented
#: copy: BAN-10 scores 0 on this page and the discovery calls that an asset.
LABEL = "Manage this notebook"

#: The five mutation forms in the authored order, keyed by the htmx attribute
#: that identifies each uniquely.
MUTATION_FORMS = (
    ('hx-patch="/ui/api/notebooks/{{ notebook.slug }}/topic"', "Topic"),
    ('hx-post="/ui/api/notebooks/{{ notebook.slug }}/discover"', "Discover"),
    ('hx-post="/ui/api/notebooks/{{ notebook.slug }}/papers"', "Add-by-URL"),
    ('hx-post="/ui/api/notebooks/{{ notebook.slug }}/papers/upload"', "Upload"),
    ('hx-post="/ui/api/notebooks/{{ notebook.slug }}/ingest"', "Ingest"),
)

#: ``_ingest_status_fragment``'s four branches. ``none`` is synthesised by the
#: route for the no-row case; the rest are the store's closed vocabulary.
#: ``none`` and ``running`` keep polling every 2s and ``failed`` carries the
#: stderr tail, so only ``success`` is unambiguously closable.
OPEN_STATES = ("none", "running", "failed")
ALL_STATES = (*OPEN_STATES, "success")


@pytest.fixture
def detail_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Path]]:
    """Minimal app + a real store, yielding ``(client, db_path)``.

    Shape lifted from ``tests/test_notebook_detail_status.py``: seeding an
    ingest-run row over a separate WAL-mode sqlite3 connection keeps us off the
    store's asyncio.Lock on a foreign event loop.
    """
    base = tmp_path / "notebooks"
    base.mkdir()
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebooks_module, "NOTEBOOKS_BASE", base, raising=False)
    db_path = tmp_path / "notebooks.db"
    loop = asyncio.new_event_loop()
    try:
        store = loop.run_until_complete(NotebooksStore.open(db_path))
        app = FastAPI()
        app.state.notebooks_store = store
        app.include_router(notebooks_router, prefix="/ui/api")
        app.include_router(ui_router, prefix="/ui")
        app.mount(
            "/ui/static", StaticFiles(directory=str(FRONTEND_STATIC)), name="ui-static"
        )
        with TestClient(app) as c:
            yield c, db_path
        loop.run_until_complete(store.close())
    finally:
        loop.close()


def _render(client: TestClient, db_path: Path, state: str) -> str:
    """Render the detail page with the latest ingest run in ``state``.

    ``state == "none"`` seeds no row, which is what makes ``latest_run`` None.
    """
    slug = f"m12-{state}"
    r = client.post(
        "/ui/api/notebooks",
        json={"slug": slug, "display_name": slug, "notebook_kind": "arxiv"},
    )
    assert r.status_code in (200, 201), r.text
    if state != "none":
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "INSERT INTO notebook_ingest_runs "
                "(slug, status, started_at, finished_at) VALUES (?, ?, ?, ?)",
                (slug, state, "2026-08-04T03:20:00Z", "2026-08-04T03:30:00Z"),
            )
            conn.commit()
        finally:
            conn.close()
    page = client.get(f"/ui/notebooks/{slug}")
    assert page.status_code == 200, page.text
    return page.text


def _rendered_tag(html: str) -> str:
    m = re.search(r'<details\b[^>]*class="manage-disclosure"[^>]*>', html)
    assert m is not None, "the Manage disclosure is not in the rendered page"
    return m.group(0)


def _template_tag() -> str:
    m = re.search(r"<details\b[^>]*>", DETAIL)
    assert m is not None, "no <details> in notebook_detail.html"
    return m.group(0)


def _disclosure_body() -> str:
    start = DETAIL.index('<details class="manage-disclosure"')
    return DETAIL[start : DETAIL.index("</details>", start)]


# --- AC#1 — corpus before machinery, and the narrowing that makes it true
class TestCorpusPrecedesMachinery:
    @pytest.mark.parametrize(("marker", "name"), MUTATION_FORMS)
    def test_the_papers_table_precedes_every_mutation_form(
        self, marker: str, name: str
    ) -> None:
        assert DETAIL.index('<tbody id="papers-tbody"') < DETAIL.index(marker), (
            f"the {name} form is emitted BEFORE the papers table; the whole "
            f"milestone is that the corpus leads."
        )

    def test_the_rename_form_stays_above_the_table_and_this_is_recorded(
        self,
    ) -> None:
        """The AC#1 narrowing, pinned in both directions so it cannot become
        an accident. SIX forms exist here, not the five the roadmap counts;
        the sixth is ``form.rename-form`` and it STAYS in the identity
        ``<section>``, so AC#1 is implemented as "no MUTATION form above the
        table". An unrecorded narrowing of an AC is indistinguishable from
        failing it, which is why the second assertion exists.
        """
        assert DETAIL.index('class="rename-form"') < DETAIL.index(
            '<tbody id="papers-tbody"'
        ), "rename moved below the table — that is a re-decision of m12's D1."
        assert "MUTATION form above the table" in DETAIL_HTML, (
            "the template no longer records that AC#1 is read as 'no MUTATION "
            "form above the table'."
        )

    def test_the_page_lands_three_regions_not_seven_blocks(self) -> None:
        """BAN-2's authored payload — 7 cards -> 3 regions
        (art-direction-scout-brief.md:434) — which the roadmap dropped."""
        regions = re.findall(r"^<(section|details)\b", DETAIL, flags=re.M)
        assert regions == ["section", "section", "details"], (
            f"top-level regions are {regions}; the authored anatomy is "
            f"masthead <section> -> papers <section> -> one <details>."
        )


class TestManageDisclosureNesting:
    """``test_ui_m8_rule_ladder`` records the seven per-site element decisions
    in document order and finds them with ``^<(section|div)>``. Indenting the
    five moved DIVs would drop five of those records out of its view, so they
    stay at column 0 — and this is the guard that pins what the indentation
    would only have implied.
    """

    @pytest.mark.parametrize("marker", [m for m, _ in MUTATION_FORMS])
    def test_every_mutation_form_is_inside_the_disclosure(self, marker) -> None:
        assert marker in _disclosure_body(), (
            "a mutation form escaped the disclosure — machinery back above "
            "the corpus."
        )

    def test_the_papers_table_is_outside_the_disclosure(self) -> None:
        assert '<tbody id="papers-tbody"' not in _disclosure_body(), (
            "the papers table is inside the disclosure; both beforeend swaps "
            "target it, and a collapsed target is AC#4's invisible-success "
            "failure."
        )

    def test_the_disclosure_is_not_an_exclusive_accordion(self) -> None:
        """A ``name`` would group this with any disclosure sharing it, making
        them close each other — and ``.discover-abstract`` disclosures nest
        INSIDE this one after the reorder."""
        assert "name=" not in _template_tag()


# --- AC#2 — open unless success, emitted BARE
class TestDisclosureOpenState:
    @pytest.mark.parametrize("state", OPEN_STATES)
    def test_non_terminal_or_failed_renders_open(self, detail_client, state) -> None:
        client, db_path = detail_client
        tag = _rendered_tag(_render(client, db_path, state))
        assert re.search(r"\sopen(?=[\s>])", tag), (
            f"ingest state {state!r} left the disclosure CLOSED. Verified at "
            f"the vendored htmx 2.0.10 source: a poll inside a closed "
            f"<details> keeps firing (the only guard is bodyContains), so the "
            f"operator watches nothing for a whole run."
        )

    def test_success_renders_closed(self, detail_client) -> None:
        client, db_path = detail_client
        tag = _rendered_tag(_render(client, db_path, "success"))
        assert not re.search(r"\sopen(?=[\s>])", tag), (
            f"a settled ingest still forces the disclosure open: {tag!r}"
        )

    @pytest.mark.parametrize("state", ALL_STATES)
    def test_open_is_never_a_valued_attribute(self, detail_client, state) -> None:
        """The footgun this AC dies on: ``open="false"`` renders a
        ``<details>`` OPEN, because HTML boolean attributes are
        presence-based. Checking only the open case would not catch it."""
        client, db_path = detail_client
        tag = _rendered_tag(_render(client, db_path, state))
        assert "open=" not in tag, (
            f"the disclosure emits a VALUED open attribute: {tag!r}. Any "
            f'value, including "false", renders it open.'
        )

    def test_the_template_emits_the_attribute_conditionally(self) -> None:
        tag = _template_tag()
        assert re.search(r"\{%\s*if[^%]*%\}\s*open\s*\{%\s*endif\s*%\}", tag), (
            f"open is not conditional emission of the bare attribute: {tag!r}"
        )


# --- AC#3 — a state cue read from the same row the fragment reads
class TestSummaryStateCue:
    @staticmethod
    def _summary(html: str) -> str:
        m = re.search(r"<summary\b[^>]*>(.*?)</summary>", html, flags=re.S)
        assert m is not None, "the disclosure has no <summary>"
        return m.group(1)

    @pytest.mark.parametrize("state", ALL_STATES)
    def test_the_summary_carries_the_label_and_the_state(
        self, detail_client, state
    ) -> None:
        client, db_path = detail_client
        summary = self._summary(_render(client, db_path, state))
        assert LABEL in summary, (
            f"the authored label {LABEL!r} is missing; 'Quick Actions' / "
            f"'Controls' / 'Tools' are the BAN-10 shapes it replaces."
        )
        assert f'<code id="{CUE_ID}">{state}</code>' in summary, (
            f"no {state!r} cue. It must ride the summary's TEXT: browsers "
            f"that map <summary> to role=button treat its children as "
            f"presentational, so only a cue inside the accessible NAME is "
            f"announced by every AT pairing. The id is what the OOB refresh "
            f"in _ingest_status_fragment addresses."
        )

    def test_the_cue_reads_the_same_row_the_fragment_reads(self) -> None:
        """AC#3's actual content. ``ui.py`` passes ``latest_run`` from
        ``store.get_latest_ingest_run(slug)`` and the polling endpoint in
        ``notebooks.py`` calls the SAME method — one row, two readers, so the
        SOURCE row cannot drift from the fragment.

        This pins the PAGE-LOAD source only. That the RENDERED value keeps
        tracking the row afterwards is a separate property with its own guard
        below (``TestSummaryCueIsRefreshedOutOfBand``) — round 1 of the m12
        rectify conflated the two, corrected the comment that denied the
        drift, and left the drift itself in place."""
        assert "latest_run" in self._summary(DETAIL), (
            "the cue does not read `latest_run`; any other source is a second "
            "read of one fact, free to drift."
        )
        for name in ("ui.py", "notebooks.py"):
            src = (REPO_ROOT / "server" / "routes" / name).read_text(encoding="utf-8")
            assert "get_latest_ingest_run(" in src, (
                f"{name} no longer calls get_latest_ingest_run; the same-row "
                f"guarantee behind AC#3 is gone."
            )

    def test_the_cue_uses_the_same_voice_as_the_other_rendering(self) -> None:
        """m7's rectify exists because two rendering paths for one value
        disagreed on voice. ``latest_run.status`` renders in ``<code>`` at
        'Last indexed'; the cue matches."""
        assert DETAIL.count("ingest <code") >= 2


# --- H2/M2 — the cue must TRACK the row, not snapshot it at page load
class TestSummaryCueIsRefreshedOutOfBand:
    """ui-uplift-m12 rectify (H2/M2), round 2.

    The cue was a page-load snapshot with no refresh path, so it drifted in
    both directions and the critique reproduced both live:

    - page load renders `running`; the 2s poll lands `success` into a body
      inside this same open disclosure; the summary still reads `running`.
    - page load renders `success`/`none`; the operator starts a run in-page;
      the 202 renders a `running` body under a summary still reading
      `success`.

    Round 1 corrected the comment that denied this and kept the snapshot. A
    cue that lies is a defect whether or not the comment admits it, so this
    pins the behaviour instead: EVERY fragment branch re-renders the cue out
    of band with its own literal token.
    """

    #: (status kwarg, the token the branch renders) for all four branches.
    BRANCHES = [("none", "none"), ("running", "running"),
                ("success", "success"), ("failed", "failed")]

    @pytest.mark.parametrize("status,token", BRANCHES)
    def test_every_fragment_branch_carries_the_oob_cue(self, status, token) -> None:
        frag = _ingest_status_fragment(
            slug="demo", run_id=1, status=status,
            started_at="2026-08-05T00:00:00Z",
            finished_at="2026-08-05T00:01:00Z",
            exit_code=1 if status == "failed" else None,
            stderr_tail=None,
        )
        assert f'<code id="{CUE_ID}" hx-swap-oob="true">{token}</code>' in frag, (
            f"the {status!r} fragment does not re-render the summary cue. "
            f"Any branch that omits it reintroduces the drift: the body says "
            f"one thing and the disclosure's accessible name says another."
        )

    @pytest.mark.parametrize("status,token", BRANCHES)
    def test_the_oob_token_matches_the_body_token(self, status, token) -> None:
        """The cue is not a second read of the row — it is the branch's own
        token. One reader, so there is nothing left to disagree with."""
        frag = _ingest_status_fragment(
            slug="demo", run_id=1, status=status,
            started_at="2026-08-05T00:00:00Z",
            finished_at="2026-08-05T00:01:00Z",
            exit_code=1 if status == "failed" else None,
            stderr_tail=None,
        )
        body = frag.split(f'<code id="{CUE_ID}"')[0]
        if status == "none":
            assert "No ingest runs yet." in body
        else:
            assert f"Status: <code>{token}</code>" in body

    def test_the_oob_element_is_top_level_in_the_response(self) -> None:
        """htmx only processes ``hx-swap-oob`` on TOP-LEVEL elements of the
        response. Nested inside ``#ingest-status`` the attribute is inert and
        the cue silently stops updating — a failure that looks exactly like
        the bug this closes."""
        frag = _ingest_status_fragment(
            slug="demo", run_id=1, status="running",
            started_at="2026-08-05T00:00:00Z", finished_at=None,
            exit_code=None, stderr_tail=None,
        )
        assert frag.index("</div>") < frag.index('<code id="'), (
            "the OOB cue sits inside #ingest-status; htmx will not process it"
        )
        assert frag.endswith("</code>")

    @pytest.mark.parametrize("state", ALL_STATES)
    def test_the_poll_response_carries_the_cue_over_the_wire(
        self, detail_client, state
    ) -> None:
        """The builder is not the contract — the RESPONSE is. This drives the
        same endpoint the 2s poll drives and pins the cue on what actually
        reaches the browser, which is where the drift was observed.
        """
        client, db_path = detail_client
        page = _render(client, db_path, state)
        # The page-load cue and the polled cue must agree from the first cycle.
        assert f'<code id="{CUE_ID}">{state}</code>' in page

        r = client.get(f"/ui/api/notebooks/m12-{state}/ingest/latest")
        assert r.status_code in (200, 286), r.text
        assert f'<code id="{CUE_ID}" hx-swap-oob="true">{state}</code>' in r.text, (
            f"the {state!r} poll response does not re-render the cue; the "
            f"summary would keep its page-load snapshot. Response: {r.text!r}"
        )

    def test_the_summary_cue_carries_the_id_the_fragment_addresses(self) -> None:
        """The two halves are matched by a literal id string across a template
        and a Python module — the one seam that can rot silently."""
        assert f'id="{CUE_ID}"' in DETAIL, (
            f"the summary cue lost id={CUE_ID!r}; the OOB swap now addresses "
            f"nothing and fails silently."
        )
        assert INGEST_STATE_CUE_ID == CUE_ID


# --- AC#4 — every target resolves, and nothing lands out of view
class TestSwapTargetsStillResolve:
    def test_every_id_target_on_the_page_exists(self, detail_client) -> None:
        client, db_path = detail_client
        html = _render(client, db_path, "running")
        ids = set(re.findall(r'\bid="([^"]+)"', html))
        targets = set(re.findall(r'hx-target="#([^"]+)"', html))
        assert targets, "no id-based hx-targets found — the scan is broken"
        assert targets <= ids, (
            f"hx-targets resolving to nothing: {sorted(targets - ids)}. "
            f"querySelector ignores DOM position and <details> open-state, so "
            f"a miss here means the id is gone, not hidden."
        )

    @pytest.mark.parametrize("marker", [MUTATION_FORMS[2][0], MUTATION_FORMS[3][0]])
    def test_the_beforeend_swaps_scroll_their_append_point_into_view(
        self, marker: str
    ) -> None:
        """AC#4's second clause. Both ``beforeend`` swaps target
        ``#papers-tbody``, which the reorder moves from BELOW these forms to
        above the disclosure they now live in. Without ``show:`` the new row
        appends off-screen upward: the swap succeeds and looks like a failure.
        The tbody carries ``aria-live``, so this is a sighted-only defect —
        which is exactly why no existing test caught it.
        """
        m = re.search(rf"<form\b[^>]*{re.escape(marker)}[^>]*>", DETAIL)
        assert m is not None, f"form not found for {marker!r}"
        swap = re.search(r'hx-swap="([^"]*)"', m.group(0))
        assert swap is not None, f"form has no hx-swap: {m.group(0)!r}"
        assert swap.group(1).split()[0] == "beforeend", (
            f"the swap KIND changed from beforeend: {swap.group(1)!r}"
        )
        assert "show:#papers-tbody" in swap.group(1), (
            f"hx-swap={swap.group(1)!r} appends into a target that now sits "
            f"above this form, with nothing to bring it into view."
        )

    def test_the_encoding_of_each_moved_form_is_untouched(self) -> None:
        """Four moved forms ride ``hx-ext="json-enc"``; Upload deliberately
        uses ``hx-encoding="multipart/form-data"`` and must not be
        normalised onto the others."""
        upload = re.search(r'<form\b[^>]*papers/upload"[^>]*>', DETAIL)
        assert upload is not None
        assert 'hx-encoding="multipart/form-data"' in upload.group(0)
        assert 'hx-ext="json-enc"' not in upload.group(0)
        assert DETAIL.count('hx-ext="json-enc"') == 5, (
            "the four JSON forms inside the disclosure plus rename must keep "
            'hx-ext="json-enc" through the move.'
        )


# --- AC#5 — no expand animation, and not for the reason the roadmap gives
class TestNoExpandAnimation:
    #: ``interpolate-size`` / ``calc-size()`` really are Chromium-only.
    #: ``::details-content`` is NOT — Baseline NEWLY across all engines since
    #: 2025-09-16 (Chrome 131 / Firefox 143 / Safari 18.4, WPT 1.0). It is
    #: refused anyway on Newly-not-Widely (Widely 2028-03-16), the bar m6
    #: applied to light-dark(), m7 to text-wrap: balance and m10 to
    #: line-clamp. Repeating "both Chromium-only" would be a checkable
    #: falsehood, so it is not repeated anywhere in this milestone.
    REFUSED = ("interpolate-size", "calc-size(", "::details-content",
               "allow-discrete")

    @pytest.mark.parametrize("feature", REFUSED)
    def test_the_expand_animation_recipe_is_absent(self, feature: str) -> None:
        assert feature not in APP_CSS, (
            f"{feature} is used in app.css. Seven live lines in the discovery "
            f"still assign [MOT-15 accordion-expand] to UPL-1; challenge.md "
            f"and final-report.md killed it, and those two are the record."
        )

    def test_the_disclosure_declares_no_motion(self) -> None:
        for sel, body in re.findall(
            r"([^{}]*manage-disclosure[^{}]*)\{([^}]*)\}", APP_CSS
        ):
            assert not re.search(r"\b(transition|animation)\b", body), (
                f"`{sel.strip()}` declares motion: {body.strip()!r}"
            )

    def test_the_existing_clamp_is_not_mistaken_for_an_animation(self) -> None:
        """``.discover-abstract > summary``'s ``max-height: 4.5em`` is m10's
        three-line CLAMP, not motion, and must not be 'harmonised' into a
        transition by a later pass."""
        m = re.search(r"\.discover-abstract\s*>\s*summary\s*\{([^}]*)\}", APP_CSS)
        assert m is not None, "m10's abstract clamp rule is gone"
        assert "max-height" in m.group(1) and "transition" not in m.group(1)


class TestDisclosureRulesAreClassScoped:
    def test_no_bare_details_or_summary_selector_exists(self) -> None:
        """``.discover-abstract > summary`` is (0,1,1); a bare ``summary`` is
        (0,0,1), so m10 wins only for the four properties it declares. For
        every other property a bare rule wins by default with nothing to lose
        to — ``summary { list-style: none }`` would silently strip m10's
        disclosure triangle, the affordance m10's own rectify added.
        """
        offenders = []
        for sel in re.findall(r"([^{};]+)\{", APP_CSS):
            for leaf in sel.split(","):
                if re.fullmatch(r"(details|summary)", leaf.strip()):
                    offenders.append(sel.strip())
        assert not offenders, (
            f"bare disclosure selectors: {offenders}. Scope every rule to "
            f".manage-disclosure — a bare rule leaks onto .discover-abstract."
        )

    def test_the_marker_is_kept_on_every_summary(self) -> None:
        """Removing the default marker breaks state announcement across
        VoiceOver, JAWS and NVDA, and in Firefox + VoiceOver the triangle's
        direction is the ONLY channel that communicates open/closed."""
        for sel, body in re.findall(r"([^{}]*summary[^{}]*)\{([^}]*)\}", APP_CSS):
            for prop in ("list-style: none", "list-style-type: none", "display: block"):
                assert prop not in body, (
                    f"`{sel.strip()}` sets {prop!r}, removing the marker AT "
                    f"depends on for state."
                )


# --- Inherited: ladder REACHABILITY — the risk nothing in the suite covered
class TestRuleLadderReachesEveryRegion:
    """``main >`` is a DIRECT-CHILD combinator, so nesting the five mutation
    blocks inside ``<details>`` removes them from ``main``'s child list and
    they lose their rule, margin and padding — silently, because m8's guards
    check the ladder's tokens and its horizontality, never its coverage. That
    absence is the reason this class exists.
    """

    def test_the_disclosure_takes_the_section_rung(self) -> None:
        m = re.search(r"main\s*>[^{}]*\+\s*:where\(([^)]*)\)\s*\{([^}]*)\}", APP_CSS)
        assert m is not None, (
            "the top-level ladder no longer folds the disclosure into the "
            "section rung; `main > … + details` matching nothing leaves the "
            "third region butted against the second with no rule at all."
        )
        assert "details" in m.group(1), (
            f"the section rung selects {m.group(1)!r} — <details> is not in it"
        )
        assert "var(--rule-section)" in m.group(2), (
            "the disclosure is a PEER region of the two sections; it takes the "
            "section rung, not a tinted one."
        )

    def test_the_nested_blocks_keep_a_rung(self) -> None:
        m = re.search(
            r"\.manage-disclosure\s*>\s*div\s*\+\s*div\s*\{([^}]*)\}", APP_CSS
        )
        assert m is not None, (
            "no nested ladder for the disclosure's children — the five "
            "mutation blocks collapse into one undifferentiated run."
        )
        body = m.group(1)
        assert "var(--rule-row)" in body, (
            f"the nested rung is not --rule-row: {body.strip()!r}. These "
            f"blocks took the row rung as main's children; same rhythm, one "
            f"level down."
        )
        assert "border-block-start" in body and "border-inline" not in body, (
            "the ladder is horizontal only — a vertical edge re-introduces "
            "the box m8 deleted."
        )


class TestEmptyStateCopyIsNotWrong:
    def test_the_empty_state_no_longer_points_upward(self) -> None:
        """"No papers yet. Add one above." was true while the Add-by-URL form
        sat above the table. After the reorder a first-run notebook would
        render a page whose only instruction is wrong and whose only action is
        behind a disclosure. ``ui-uplift-m11`` (UPL-21) owns empty-state copy
        and ``depends_on`` m12, so it revisits the voice; shipping the interim
        page with a false instruction is not an option.
        """
        m = re.search(r'<p class="empty">([^<]*)</p>', DETAIL)
        assert m is not None, "the papers empty-state <p> is gone"
        copy = m.group(1)
        assert "above" not in copy, (
            f"the empty state still says {copy!r}; the add form is BELOW now."
        )
        assert LABEL in copy, (
            f"{copy!r} does not name the affordance the operator has to open. "
            f"Naming it is what keeps this disclosure on the legitimate side "
            f"of the progressive-disclosure line."
        )
