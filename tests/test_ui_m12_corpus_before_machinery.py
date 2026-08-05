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
from html.parser import HTMLParser
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

#: The disclosure's own id (m12 M13's anchor target) and the id its
#: aria-labelledby resolves to (m12 M12).
MANAGE_ID: str = "manage"
MANAGE_SUMMARY_ID: str = "manage-summary"

_VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "source", "track", "wbr",
})


class _DomNode:
    """A minimal element node: tag, attrs, children, parent."""

    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict[str, str], parent=None) -> None:
        self.tag = tag
        self.attrs = attrs
        self.children: list[_DomNode] = []
        self.parent = parent

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def ancestors(self) -> list[str]:
        out, node = [], self.parent
        while node is not None:
            out.append(node.tag)
            node = node.parent
        return out

    def contains(self, other: _DomNode) -> bool:
        node = other.parent
        while node is not None:
            if node is self:
                return True
            node = node.parent
        return False

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        ident = self.attrs.get("id") or self.attrs.get("class") or ""
        return f"<{self.tag}{' ' + ident if ident else ''}>"


class _DomBuilder(HTMLParser):
    """Build a real element tree from RENDERED markup.

    Added 2026-08-05 closing m12 M5/M6/M7. Those findings all have the same
    shape: the milestone asserted a STRUCTURAL invariant ("no swap targets an
    ancestor of the disclosure", "the ladder reaches every region") and then
    checked it with a regex over CSS or source text, which cannot see
    structure at all. Both were mutation-proven false by the critics — a
    wrapper ``<div>`` inserted after the ``<summary>`` strips the rung,
    margin AND padding from all five relocated blocks with every guard still
    green. Structure needs a tree.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _DomNode("#document", {})
        self._cursor = self.root

    def handle_starttag(self, tag: str, attrs) -> None:
        node = _DomNode(tag, {k: (v or "") for k, v in attrs}, self._cursor)
        self._cursor.children.append(node)
        if tag not in _VOID_ELEMENTS:
            self._cursor = node

    def handle_startendtag(self, tag: str, attrs) -> None:
        self._cursor.children.append(
            _DomNode(tag, {k: (v or "") for k, v in attrs}, self._cursor)
        )

    def handle_endtag(self, tag: str) -> None:
        node = self._cursor
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self._cursor = node.parent


def _dom(html: str) -> _DomNode:
    builder = _DomBuilder()
    builder.feed(html)
    return builder.root


def _find(root: _DomNode, predicate) -> _DomNode | None:
    return next((n for n in root.walk() if predicate(n)), None)


def _disclosure(root: _DomNode) -> _DomNode:
    node = _find(
        root,
        lambda n: n.tag == "details"
        and "manage-disclosure" in n.attrs.get("class", ""),
    )
    assert node is not None, "the Manage disclosure is not in the rendered page"
    return node

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
        assert "CORPUS-MUTATION form above the table" in DETAIL_HTML, (
            "the template no longer records that AC#1 is read as 'no "
            "CORPUS-MUTATION form above the table'."
        )

    def test_the_narrowing_agrees_with_the_canonical_AC(self) -> None:
        """The narrowing must live in the ROADMAP too, not only here.

        External review, 2026-08-05. m12 declared AC#1 narrowed to "no
        mutation form above the table" in the template while
        ``plans/ui-uplift/roadmap.yaml`` still read "without scrolling past
        any input form" — and ``form.rename-form`` is an input form above the
        table. So the milestone read as passing an AC its canonical text says
        it fails, and nothing could see the disagreement because the two
        statements lived in different files with no guard between them.

        Resolved by owner decision: the AC text moved. That milestone's own
        ``summary`` already scoped it to "the FIVE mutation forms" — rename is
        the sixth — so the AC sentence was the outlier, not the shipped page.

        This pins the agreement rather than either side alone. A future edit
        that reverts the AC to "any input form" without moving rename fails
        here, which is the state that existed before this test.
        """
        roadmap = (REPO_ROOT / "plans" / "ui-uplift" / "roadmap.yaml").read_text(
            encoding="utf-8"
        )
        block = roadmap.split("id: ui-uplift-m12", 1)[1].split("id: ui-uplift-m13", 1)[0]
        ac1 = next(
            line for line in block.splitlines()
            if "the papers table is visible without scrolling" in line
        )
        assert "corpus-mutation form" in ac1, (
            f"roadmap AC#1 reads:\n  {ac1.strip()}\n"
            f"but this page keeps form.rename-form above the table. Either the "
            f"AC names corpus-mutation forms, or rename moves below the table. "
            f"A narrowing recorded only in the template is a contradiction the "
            f"roadmap does not know about."
        )
        assert "any input form" not in ac1, (
            "roadmap AC#1 has reverted to the unnarrowed wording while rename "
            "still sits above the table"
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

    def test_the_mutation_divs_stay_at_column_zero(self) -> None:
        """m12 M4/M8 — pin the premise another guard now rests on.

        ``tests/test_ui_m8_rule_ladder.py::TestSectioningElementDecision``
        finds the seven per-site element decisions with ``^<(section|div)>``.
        After m12 five of those blocks are children of ``<details>``, kept at
        column 0 deliberately: indenting them drops five of the seven records
        out of that extractor's view, and "a decision recorded as a total is
        not a recorded decision" is m8's own note.

        Indenting them is the natural thing any agent or formatter would do,
        and until this test the only thing preventing it was a prose paragraph
        — in a repo with no CI and no code review (CLAUDE.md §4.1). Worse, the
        m8 guard would fail with a message about "column-0 blocks" while the
        reader looked for a layout regression that had not happened.

        Fails HERE first, naming the real cause.
        """
        column_zero = re.findall(r"^<div>", DETAIL, flags=re.M)
        assert len(column_zero) == 5, (
            f"{len(column_zero)} <div>s are emitted at column 0; m12 ships "
            f"five (topic, discover, add-paper, upload, ingest). If they were "
            f"indented, tests/test_ui_m8_rule_ladder.py::"
            f"TestSectioningElementDecision loses five of its seven per-site "
            f"element records and fails with a misleading message. Keep them "
            f"at column 0, or update that guard's extractor in the same edit."
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
        # ui-uplift-m11 (UPL-21) made this SIX: the empty papers state gained
        # a first-paper Add-by-URL control, which posts the same JSON endpoint
        # and therefore carries the same extension. Counting is the point —
        # a form that gains the endpoint without the encoding fails here.
        assert DETAIL.count('hx-ext="json-enc"') == 6, (
            "the four JSON forms inside the disclosure, rename, and m11's "
            'empty-state control must all keep hx-ext="json-enc".'
        )


class TestStructuralInvariantsHoldInTheRenderedTree:
    """m12 M5 / M6 / M7 — the invariants that were declared and not enforced.

    All three share a shape: the milestone stated a STRUCTURAL property and
    checked it with a regex over CSS or template text. The critics proved each
    false by mutation while every guard stayed green.
    """

    def test_no_swap_targets_the_disclosure_or_an_ancestor(
        self, detail_client
    ) -> None:
        """M5 + M7. The template records "no swap may target the <details> or
        any ancestor of it" as the HARD CONSTRAINT that lets m12 escape
        onboarding-uplift-m3 §3 D2's rejection of <details> — and named
        ui-uplift-m13 as the near-miss. Nothing asserted it.

        m13 `depends_on: [ui-uplift-m12]` and its roadmap summary prescribes
        exactly the violating shape: "Move aria-live onto a stable
        never-swapped wrapper." Mutation-proven by the critic: wrapping the
        disclosure in a polled `<div hx-swap="outerHTML">` left all ten m12/m8
        template guards green while destroying and recreating the `<details>`
        every 2 seconds — the server-rendered `open` snaps back on every tick,
        which is the D2 failure this milestone claims to have escaped.

        Under §4.1's no-PR/no-CI posture a comment is not a constraint.
        """
        client, db_path = detail_client
        root = _dom(_render(client, db_path, "running"))
        details = _disclosure(root)

        by_id = {n.attrs["id"]: n for n in root.walk() if n.attrs.get("id")}
        targets = {
            n.attrs["hx-target"] for n in root.walk() if n.attrs.get("hx-target")
        }
        assert targets, "no hx-targets found — the scan is broken"

        for target in sorted(targets):
            if not target.startswith("#"):
                continue
            node = by_id.get(target[1:])
            if node is None:
                continue  # resolution is TestSwapTargetsStillResolve's job
            assert node is not details, (
                f"hx-target={target!r} IS the Manage disclosure. Swapping it "
                f"re-renders `open` from the server predicate on every tick, "
                f"so the operator's open/closed state snaps back — the exact "
                f"onboarding-uplift-m3 D2 failure m12's note claims to escape."
            )
            assert not node.contains(details), (
                f"hx-target={target!r} is an ANCESTOR of the Manage "
                f"disclosure ({node!r}). Any swap of it destroys and recreates "
                f"the <details>, resetting open state. See the HARD "
                f"CONSTRAINT note in notebook_detail.html before changing this."
            )

    def test_the_disclosure_itself_is_never_a_swap_participant(
        self, detail_client
    ) -> None:
        """The other half of M7: the <details> must carry no hx-* of its own."""
        client, db_path = detail_client
        details = _disclosure(_dom(_render(client, db_path, "running")))
        hx = {k: v for k, v in details.attrs.items() if k.startswith("hx-")}
        assert not hx, (
            f"the Manage disclosure carries {hx!r}; it must not participate "
            f"in any swap — see the HARD CONSTRAINT note in the template."
        )

    def test_the_rule_ladder_actually_reaches_the_rendered_markup(
        self, detail_client
    ) -> None:
        """M6. ``TestRuleLadderReachesEveryRegion`` asserts two selectors
        EXIST in app.css and carry the right token — it never evaluates either
        against the markup that has to match.

        The critic's mutation, reproduced as an assertion here: inserting a
        wrapper `<div>` after the `<summary>` makes
        ``.manage-disclosure > div + div`` match nothing (one div child has no
        adjacent div sibling), stripping the rung, the margin AND the padding
        from all five relocated blocks — with six guards still green. The same
        gap runs upward: ``main > :where(section, div) + div`` requires the
        `<details>` to be a DIRECT child of `<main>`, which nothing pinned.
        """
        client, db_path = detail_client
        root = _dom(_render(client, db_path, "running"))
        details = _disclosure(root)

        # (a) `main > …` requires a direct-child <details>.
        assert details.parent is not None and details.parent.tag == "main", (
            f"the disclosure's parent is <{details.parent.tag if details.parent else None}>, "
            f"not <main> — `main > :where(section, div) + div` and the section "
            f"rung both use the direct-child combinator and stop matching."
        )
        assert details.parent.attrs.get("id") == "main", (
            "the disclosure is not inside <main id='main'>"
        )

        # (b) `.manage-disclosure > div + div` needs ADJACENT div children.
        div_children = [c for c in details.children if c.tag == "div"]
        assert len(div_children) >= 2, (
            f"the disclosure has {len(div_children)} direct <div> children. "
            f"`.manage-disclosure > div + div` is an adjacent-sibling rule, so "
            f"fewer than two direct div children silently removes the rung, "
            f"the 1.25rem margin AND the padding from every relocated block. "
            f"A wrapper <div> around the group does exactly this."
        )

    @pytest.mark.parametrize(("marker", "name"), MUTATION_FORMS)
    def test_every_mutation_form_is_inside_a_direct_div_child(
        self, detail_client, marker: str, name: str
    ) -> None:
        """The other direction of (b): a form that drifts out of a direct div
        child loses the rung even though the div count still passes."""
        client, db_path = detail_client
        root = _dom(_render(client, db_path, "running"))
        details = _disclosure(root)
        attr, _, value = marker.partition("=")
        rendered_value = value.strip('"').replace(
            "{{ notebook.slug }}", "m12-running"
        )
        # ui-uplift-m11: the Add-by-URL endpoint now has TWO forms — the one
        # in the disclosure and the empty state's first-paper control. This
        # guard is about the DISCLOSURE's copy, so resolve inside it rather
        # than taking whichever comes first in document order.
        node = _find(
            details, lambda n: n.attrs.get(attr.strip()) == rendered_value
        )
        assert node is not None, (
            f"the {name} form is not inside the Manage disclosure"
        )
        block = next(
            (a for a in _iter_parents(node) if a.parent is details), None
        )
        assert block is not None and block.tag == "div", (
            f"the {name} form is not inside a direct <div> child of the "
            f"disclosure, so `.manage-disclosure > div + div` does not rung it."
        )


def _iter_parents(node: _DomNode):
    current = node.parent
    while current is not None:
        yield current
        current = current.parent


class TestRegionThreeIsNamedAndReachable:
    """m12 M12 + M13 — the region that was neither announceable nor findable."""

    def test_the_disclosure_carries_an_accessible_name(
        self, detail_client
    ) -> None:
        """M12. The summary is styled at --text-section, byte-identical to h2,
        but is a role=button — so region 3 contributed nothing to the heading
        list, and that list silently gained or lost five entries with the
        disclosure's open state. Nesting an <h2> inside <summary> is NOT the
        fix: role=button makes its children presentational. HTML-AAM maps
        <details> to role=group, so naming the group is the zero-structure
        answer."""
        client, db_path = detail_client
        root = _dom(_render(client, db_path, "running"))
        details = _disclosure(root)

        labelledby = details.attrs.get("aria-labelledby")
        assert labelledby, (
            "the Manage disclosure has no accessible name; region 3 is "
            "announced as a bare group on entry."
        )
        summary = next(
            (c for c in details.children if c.tag == "summary"), None
        )
        assert summary is not None, "the disclosure has no <summary>"
        assert summary.attrs.get("id") == labelledby, (
            f"aria-labelledby={labelledby!r} does not resolve to this "
            f"disclosure's own <summary> (id={summary.attrs.get('id')!r}); an "
            f"unresolvable reference names nothing."
        )

    def test_the_corpus_section_points_to_the_machinery(
        self, detail_client
    ) -> None:
        """M13. store.list_papers() is uncapped, so on a 50-paper notebook the
        disclosure sits ~2400px below the fold. The pointer to it existed only
        in the `{% if not papers %}` empty state — i.e. exactly when it is
        least needed. Asserted with papers PRESENT, which is the state that
        was broken."""
        client, db_path = detail_client
        html = _render(client, db_path, "success")
        root = _dom(html)
        details = _disclosure(root)
        assert details.attrs.get("id") == MANAGE_ID, (
            f"the disclosure's id is {details.attrs.get('id')!r}; the anchor "
            f"beside the papers heading targets #{MANAGE_ID}."
        )

        papers_h2 = _find(
            root,
            lambda n: n.tag == "h2"
            and any(
                c.tag == "a" and c.attrs.get("href") == f"#{MANAGE_ID}"
                for c in n.children
            ),
        )
        assert papers_h2 is not None, (
            f"no link to #{MANAGE_ID} sits with the papers <h2>. Over an "
            f"uncapped table the disclosure is the only affordance for adding, "
            f"discovering, uploading or ingesting, and nothing near the corpus "
            f"points at it."
        )

    def test_the_pointer_is_a_link_not_a_second_control(
        self, detail_client
    ) -> None:
        """BAN-9 forbids multiple primary CTAs per viewport, so M13's fix must
        stay a link — a duplicated Add/Ingest button up here would be the ban
        it was written to avoid."""
        client, db_path = detail_client
        root = _dom(_render(client, db_path, "success"))
        papers = _find(
            root,
            lambda n: n.tag == "section"
            and _find(n, lambda m: m.attrs.get("id") == "papers-tbody") is not None,
        )
        assert papers is not None, "the papers <section> is not in the page"
        rows = [n for n in papers.walk()
                if n.tag == "tr" and n.attrs.get("data-paper-id")]
        forms = [n for n in papers.walk() if n.tag == "form"]
        if rows:
            assert not forms, (
                f"the POPULATED papers section carries {len(forms)} form(s); "
                f"M13's pointer is deliberately a link, and m12 AC#1 keeps "
                f"corpus-mutation forms out of this region."
            )
        else:
            # ui-uplift-m11 (UPL-21) narrowed this, and the narrowing is the
            # M9 lesson applied to m12's own guard. The blanket "no form in
            # the papers section" was written against the POPULATED page,
            # where a second Add control beside the table is BAN-9's duplicate
            # CTA. In the EMPTY state there is no table to duplicate beside
            # and no other reachable control — m12 put every mutation form
            # behind the disclosure — so m11 AC#1's "one actual control, not a
            # pointer" lands exactly here. Forbidding it would have pinned m11
            # out of its own acceptance criterion, which is precisely what M9
            # had to be relaxed for.
            assert len(forms) <= 1, (
                f"the empty papers state carries {len(forms)} forms; m11 "
                f"AC#1 authorises ONE control, not a panel"
            )
        # Either way the M13 pointer itself must stay a link.
        assert _find(papers, lambda n: n.tag == "a"
                     and n.attrs.get("href") == f"#{MANAGE_ID}") is not None


class TestLadderDeclarationsCannotBeEmptiedSilently:
    """m12 L5 + L2 — mutation-proven misses in the CSS guards."""

    def test_the_summary_rule_keeps_its_size_parity_and_affordance(
        self,
    ) -> None:
        """L5: emptying `.manage-disclosure > summary` entirely left every m12
        and m8 guard green, while deleting the size parity this milestone
        argued for at length and the `cursor: pointer` affordance."""
        m = re.search(r"\.manage-disclosure\s*>\s*summary\s*\{([^}]*)\}", APP_CSS)
        assert m is not None, "the summary rule is gone"
        body = m.group(1)
        assert "font-size: var(--text-section)" in body, (
            "the summary lost --text-section. Region parity WITHOUT wrapping "
            "an <h2> inside a role=button is the whole argument for this rule."
        )
        assert "cursor: pointer" in body, "the summary lost its pointer cursor"

    def test_the_top_level_section_rung_keeps_its_rhythm(self) -> None:
        """L5's second half: stripping margin-block-start/padding-block-start
        from the top-level rung also passed everything."""
        m = re.search(
            r"main\s*>\s*:where\(section, div\)\s*\+\s*div\s*\{([^}]*)\}", APP_CSS
        )
        assert m is not None, "the top-level row rung is gone"
        body = m.group(1)
        for prop in ("margin-block-start", "padding-block-start"):
            assert prop in body, (
                f"the top-level rung lost {prop}; the rule becomes the sole "
                f"separator, which is what m8's exemption forbids."
            )

    def test_the_summary_needs_no_marker_clipping_workaround(self) -> None:
        """L2. `list-style-position: outside` was copied from
        `.discover-abstract > summary`, where it is REQUIRED because that rule
        sets `overflow: hidden` + `max-height` and an inside marker would be
        clipped. Here it is visual parity only. Pin that this rule declares
        neither, so nobody re-derives the m10 requirement for it."""
        m = re.search(r"\.manage-disclosure\s*>\s*summary\s*\{([^}]*)\}", APP_CSS)
        assert m is not None
        body = m.group(1)
        for prop in ("overflow", "max-height"):
            assert prop not in body, (
                f"`.manage-disclosure > summary` now declares {prop}. If it "
                f"clips, `list-style-position: outside` stops being cosmetic "
                f"parity and becomes load-bearing — re-open the note above it."
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
    """m12 fixed a FACT in the papers empty state; ui-uplift-m11 (UPL-21) then
    took ownership of the surface, as m12's own M9 relaxation anticipated.

    m12's interim copy was a ``<p class="empty">`` ABOVE the table reading
    'Add one from "Manage this notebook" below'. m11 replaced it with a row
    INSIDE the tbody carrying a cause line and a real control, so the guards
    that matched on that ``<p>`` no longer have a subject.

    What survives is the DURABLE half — the property m12 established and m11
    cannot legitimately reverse: the copy must not point UPWARD, which was
    false the moment the Add-by-URL form moved below the table. Asserted
    against whatever element carries the empty state rather than against the
    ``<p>`` m12 happened to ship.
    """

    @staticmethod
    def _empty_copy() -> str:
        m = re.search(
            r'<(?:p|td)[^>]*class="empty"[^>]*>(.*?)</(?:p|td)>', DETAIL, re.S
        )
        assert m is not None, "the papers empty state is gone entirely"
        return m.group(1)

    def test_the_empty_state_no_longer_points_upward(self) -> None:
        copy = self._empty_copy()
        assert "above" not in copy.lower(), (
            f"the empty state points upward again: {copy.strip()[:120]!r}. "
            f"The add path is BELOW the table since m12, and inside the empty "
            f"state itself since m11."
        )

    def test_the_empty_state_still_says_something(self) -> None:
        assert re.search(r"[A-Za-z]", self._empty_copy()), (
            "the empty state renders no copy at all"
        )


