"""ui-uplift-m13 (UPL-13 v0) — live-region hygiene.

Twelve live regions rendered on one page, six of them empty error blocks at
first paint, and a 2s poll that re-announced the whole ingest status on every
tick for the duration of a run.

Three properties are pinned here, and each is asserted against the RENDERED
page rather than the template source where the distinction matters — a live
region is a property of the accessibility tree, and the tree is built from what
renders.

**The counting rule this module follows.** "How many live regions" is the
milestone's own headline number, so it is derived, never typed: explicit
``aria-live`` attributes plus the elements whose implicit ARIA role is a live
region (``<output>`` → ``role="status"``). A test that counted only the
attribute would have scored the ``<output>`` migration as a reduction to six
when the announcing surfaces did not change at all.
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
from server.routes.notebooks import _ingest_status_fragment
from server.routes.notebooks import router as notebooks_router
from server.routes.ui import router as ui_router
from tools import _notebook_common

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
FRONTEND: Path = REPO_ROOT / "server" / "frontend"
FRONTEND_STATIC: Path = FRONTEND / "static"
APP_CSS: str = (FRONTEND_STATIC / "app.css").read_text(encoding="utf-8")
APP_CSS_NO_COMMENTS: str = re.sub(r"/\*.*?\*/", "", APP_CSS, flags=re.S)
DETAIL_HTML: str = (FRONTEND / "templates" / "notebook_detail.html").read_text(
    encoding="utf-8"
)
DETAIL: str = re.sub(r"\{#.*?#\}", "", DETAIL_HTML, flags=re.S)

#: The never-swapped wrapper that carries the ingest live region.
LIVE_WRAPPER_ID = "ingest-live"
#: The element the 2s poll replaces, INSIDE that wrapper.
POLLED_ID = "ingest-status"

#: The six per-form error blocks migrated to <output> (AC#2). Derived from the
#: template below as well, so this list cannot silently fall behind.
ERROR_BLOCK_IDS = (
    "rename-error", "topic-error", "discover-error",
    "paste-error", "upload-error", "ingest-error",
    # ui-uplift-m11 (UPL-21): the empty papers state gained a first-paper
    # control, and its error surface got the <output> treatment on arrival
    # rather than being the one block that reintroduced an explicit
    # aria-live. Six was m13's count; this list is what the guards derive
    # from, and it moves when the page does.
    "papers-empty-error",
)

#: Elements whose implicit ARIA role IS a live region.
IMPLICIT_LIVE_TAGS = {"output"}

_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input",
                   "link", "meta", "source", "track", "wbr"})


class _Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict[str, str], parent=None) -> None:
        self.tag, self.attrs, self.parent = tag, attrs, parent
        self.children: list[_Node] = []

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def contains(self, other: _Node) -> bool:
        n = other.parent
        while n is not None:
            if n is self:
                return True
            n = n.parent
        return False


class _Dom(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#document", {})
        self._cur = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, {k: (v or "") for k, v in attrs}, self._cur)
        self._cur.children.append(node)
        if tag not in _VOID:
            self._cur = node

    def handle_startendtag(self, tag, attrs):
        self._cur.children.append(
            _Node(tag, {k: (v or "") for k, v in attrs}, self._cur)
        )

    def handle_endtag(self, tag):
        n = self._cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self._cur = n.parent


def _dom(html: str) -> _Node:
    d = _Dom()
    d.feed(html)
    return d.root


def _live_regions(root: _Node) -> list[_Node]:
    """Every announcing surface: explicit aria-live OR an implicit-role tag."""
    return [
        n for n in root.walk()
        if n.attrs.get("aria-live") or n.tag in IMPLICIT_LIVE_TAGS
    ]


@pytest.fixture()
def detail_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Path]]:
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
        app.mount("/ui/static", StaticFiles(directory=str(FRONTEND_STATIC)),
                  name="ui-static")
        with TestClient(app) as c:
            yield c, db_path
        loop.run_until_complete(store.close())
    finally:
        loop.close()


def _render(client: TestClient, db_path: Path, state: str) -> str:
    slug = f"m13-{state}"
    r = client.post("/ui/api/notebooks",
                    json={"slug": slug, "display_name": slug,
                          "notebook_kind": "arxiv"})
    assert r.status_code in (200, 201), r.text
    if state != "none":
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "INSERT INTO notebook_ingest_runs "
                "(slug, status, started_at, finished_at) VALUES (?, ?, ?, ?)",
                (slug, state, "2026-08-05T03:20:00Z", "2026-08-05T03:30:00Z"),
            )
            conn.commit()
        finally:
            conn.close()
    page = client.get(f"/ui/notebooks/{slug}")
    assert page.status_code == 200, page.text
    return page.text


# --- AC#1 — an unchanged poll makes no announcement
class TestThePolledRegionPersists:
    """The whole of AC#1 reduces to one structural fact: the element carrying
    the live region must survive the swap that the element carrying the CONTENT
    does not."""

    def test_the_live_region_is_not_the_swap_target(self, detail_client) -> None:
        client, db_path = detail_client
        root = _dom(_render(client, db_path, "running"))
        wrapper = next(
            (n for n in root.walk() if n.attrs.get("id") == LIVE_WRAPPER_ID), None
        )
        polled = next(
            (n for n in root.walk() if n.attrs.get("id") == POLLED_ID), None
        )
        assert wrapper is not None, f"#{LIVE_WRAPPER_ID} is not rendered"
        assert polled is not None, f"#{POLLED_ID} is not rendered"

        assert wrapper.attrs.get("aria-live") == "polite"
        assert wrapper.attrs.get("aria-atomic") == "true"
        assert "aria-live" not in polled.attrs, (
            "the polled element declares its own live region; it is replaced "
            "every 2s, and an inserted live region announces its whole content "
            "with no previous version to diff against — that is UPL-13's defect"
        )
        assert wrapper.contains(polled), (
            "the swap target must sit INSIDE the live region, or the region "
            "never sees the new text at all"
        )

    def test_the_wrapper_is_never_swapped(self, detail_client) -> None:
        """A live region that is itself a swap target is not a live region —
        it is a series of them."""
        client, db_path = detail_client
        root = _dom(_render(client, db_path, "running"))
        wrapper = next(n for n in root.walk()
                       if n.attrs.get("id") == LIVE_WRAPPER_ID)
        hx = {k: v for k, v in wrapper.attrs.items() if k.startswith("hx-")}
        assert not hx, f"#{LIVE_WRAPPER_ID} participates in htmx: {hx!r}"

        targets = {n.attrs["hx-target"] for n in root.walk()
                   if n.attrs.get("hx-target")}
        assert f"#{LIVE_WRAPPER_ID}" not in targets, (
            f"something swaps #{LIVE_WRAPPER_ID}; it must persist across every "
            f"poll or the announcement returns on every tick"
        )

    @pytest.mark.parametrize("status", ["none", "running", "success", "failed"])
    def test_no_fragment_branch_nests_a_second_live_region(
        self, status: str
    ) -> None:
        frag = _ingest_status_fragment(
            slug="demo", run_id=1, status=status,
            started_at="2026-08-05T00:00:00Z",
            finished_at="2026-08-05T00:01:00Z",
            exit_code=1 if status == "failed" else None,
            stderr_tail="boom" if status == "failed" else None,
        )
        assert "aria-live" not in frag and "aria-atomic" not in frag, (
            f"the {status!r} fragment declares a live region inside "
            f"#{LIVE_WRAPPER_ID}. Nesting one restores the per-tick "
            f"announcement on the inner node."
        )

    def test_the_polled_element_still_carries_the_poll(
        self, detail_client
    ) -> None:
        """Guard against 'fixing' the announcement by removing the update."""
        client, db_path = detail_client
        root = _dom(_render(client, db_path, "running"))
        polled = next(n for n in root.walk() if n.attrs.get("id") == POLLED_ID)
        assert polled.attrs.get("hx-swap") == "outerHTML"
        assert polled.attrs.get("hx-target") == f"#{POLLED_ID}"


# --- AC#2 — the six empty-at-first-paint error blocks
class TestErrorBlocksAreOutputs:
    def test_no_error_block_carries_an_explicit_aria_live(self) -> None:
        for block_id in ERROR_BLOCK_IDS:
            m = re.search(rf'<[^>]*id="{block_id}"[^>]*>', DETAIL)
            assert m is not None, f"#{block_id} is gone from the template"
            assert "aria-live" not in m.group(0), (
                f"#{block_id} still carries an explicit aria-live: {m.group(0)}"
            )

    def test_every_error_block_is_an_output(self) -> None:
        """``<output>`` has an implicit ``role=status``, so the announcement
        survives the attribute's removal. AC#2 is not 'make errors silent'."""
        for block_id in ERROR_BLOCK_IDS:
            m = re.search(rf'<(\w+)[^>]*id="{block_id}"', DETAIL)
            assert m is not None and m.group(1) == "output", (
                f"#{block_id} is a <{m.group(1) if m else '?'}>; it must be "
                f"<output> so its live region is implicit rather than absent"
            )

    def test_the_template_ships_exactly_the_enumerated_error_blocks(self) -> None:
        """Derived, so a seventh block cannot be added without a decision."""
        found = set(re.findall(r'<output[^>]*id="([a-z-]+)"', DETAIL))
        assert found == set(ERROR_BLOCK_IDS), (
            f"error blocks in the template are {sorted(found)}, enumerated "
            f"{sorted(ERROR_BLOCK_IDS)}"
        )

    def test_an_empty_error_block_stays_in_the_accessibility_tree(self) -> None:
        """The finding the brief did not carry, and the reason the migration
        would otherwise be cosmetic.

        `display: none` removes an element from the accessibility tree. All six
        blocks are empty at first paint, so with `:empty { display: none }` the
        live region did not exist when the AT needed to register it; the error
        path then set `.textContent`, which in one frame both filled the element
        and made `:empty` stop matching — inserting an already-populated region,
        which is the canonical way to announce nothing.
        """
        m = re.search(r"\.error:empty\s*\{([^}]*)\}", APP_CSS_NO_COMMENTS)
        assert m is not None, ".error:empty rule is gone"
        body = m.group(1)
        assert "display" not in body, (
            f".error:empty declares display ({body.strip()!r}). Any value that "
            f"removes the box from the a11y tree un-registers the live region "
            f"before its text arrives. Collapse the footprint instead."
        )

    def test_the_empty_state_has_no_visual_footprint(self) -> None:
        """The reason `display: none` was there in the first place — six tinted
        empty boxes is not an acceptable trade for the fix."""
        m = re.search(r"\.error:empty\s*\{([^}]*)\}", APP_CSS_NO_COMMENTS)
        assert m is not None
        body = m.group(1)
        for prop in ("padding", "margin", "min-height", "background"):
            assert prop in body, (
                f".error:empty does not neutralise {prop}; an empty error block "
                f"would show as a tinted box on first paint"
            )


# --- AC#3 — the ingest region is excluded from the <output> migration
class TestIngestStatusIsExcludedFromTheOutputMigration:
    def test_the_polled_region_is_not_an_output(self, detail_client) -> None:
        client, db_path = detail_client
        root = _dom(_render(client, db_path, "failed"))
        for node_id in (LIVE_WRAPPER_ID, POLLED_ID):
            node = next(n for n in root.walk() if n.attrs.get("id") == node_id)
            assert node.tag != "output", (
                f"#{node_id} is an <output>. <output> is PHRASING content and "
                f"the failed branch emits <pre class=\"error\">, which is FLOW "
                f"content — invalid, and AC#3 excludes it by name."
            )

    def test_the_failed_branch_still_emits_a_pre(self) -> None:
        """The concrete reason for the exclusion, pinned so a later milestone
        cannot 'finish' the migration without meeting it."""
        frag = _ingest_status_fragment(
            slug="demo", run_id=1, status="failed",
            started_at=None, finished_at=None, exit_code=1,
            stderr_tail="traceback",
        )
        assert '<pre class="error">' in frag


# --- The headline number, derived rather than asserted
class TestLiveRegionCensus:
    def test_the_detail_page_announces_from_one_polled_surface(
        self, detail_client
    ) -> None:
        """Regions may be added; what must not come back is a SECOND announcing
        surface inside the polled subtree."""
        client, db_path = detail_client
        root = _dom(_render(client, db_path, "running"))
        wrapper = next(n for n in root.walk()
                       if n.attrs.get("id") == LIVE_WRAPPER_ID)
        inside = [n for n in _live_regions(root) if wrapper.contains(n)]
        assert inside == [], (
            f"{len(inside)} live region(s) nested inside #{LIVE_WRAPPER_ID}: "
            f"{[n.tag for n in inside]}. The wrapper is the only announcing "
            f"surface for the poll."
        )

    def test_the_census_counts_implicit_roles_too(self, detail_client) -> None:
        """The counting rule itself, pinned.

        Counting only `aria-live` attributes would score the `<output>`
        migration as removing six live regions when it removed none — it
        changed six explicit regions into six implicit ones. A milestone whose
        headline is a count must not be able to improve that count by changing
        how it is spelled.
        """
        client, db_path = detail_client
        root = _dom(_render(client, db_path, "running"))
        explicit = [n for n in root.walk() if n.attrs.get("aria-live")]
        implicit = [n for n in root.walk() if n.tag in IMPLICIT_LIVE_TAGS]
        assert len(implicit) == len(ERROR_BLOCK_IDS), (
            f"expected {len(ERROR_BLOCK_IDS)} implicit live regions "
            f"(<output>), found {len(implicit)}"
        )
        assert _live_regions(root) and len(_live_regions(root)) == len(
            explicit
        ) + len(implicit), "the census helper is not counting both kinds"


# --- critique H1 — the same defect at 10s, on every page
class TestNoPolledSwapTargetIsItsOwnLiveRegion:
    """The general rule m13 arrived at, applied to every polled target.

    Found by this milestone's own critique, not by its acceptance criteria:
    ``#status-badge`` in ``base.html`` had the identical shape at 10s — and
    unlike the ingest poll it never terminates and is on every page. The ACs
    were written from the ingest symptom; the milestone's census sentence is
    what actually scoped the work.

    Derived over the rendered page, so the NEXT polled region added anywhere
    fails here on arrival rather than shipping the same bug a third time.
    """

    @staticmethod
    def _polled_live_targets(root: _Node) -> list[str]:
        offenders = []
        by_id = {n.attrs["id"]: n for n in root.walk() if n.attrs.get("id")}
        for node in root.walk():
            trigger = node.attrs.get("hx-trigger", "")
            if "every" not in trigger:
                continue
            target = node.attrs.get("hx-target", "")
            swapped = by_id.get(target[1:]) if target.startswith("#") else node
            if swapped is None:
                continue
            if swapped.attrs.get("aria-live") or swapped.tag in IMPLICIT_LIVE_TAGS:
                offenders.append(
                    f"{trigger!r} replaces #{swapped.attrs.get('id')} which is "
                    f"itself a live region"
                )
        return offenders

    def test_no_polled_element_replaces_a_live_region(
        self, detail_client
    ) -> None:
        client, db_path = detail_client
        for state in ("none", "running", "failed"):
            root = _dom(_render(client, db_path, state))
            offenders = self._polled_live_targets(root)
            assert not offenders, (
                f"state {state!r}: " + "; ".join(offenders)
                + ". A polled swap target must not declare its own live "
                "region — put the region on a wrapper that survives the poll."
            )

    def test_the_status_badge_region_is_the_wrapper(self, detail_client) -> None:
        client, db_path = detail_client
        root = _dom(_render(client, db_path, "running"))
        wrapper = next(
            (n for n in root.walk() if n.attrs.get("id") == "status-live"), None
        )
        badge = next(
            (n for n in root.walk() if n.attrs.get("id") == "status-badge"), None
        )
        assert wrapper is not None, "#status-live is not rendered"
        assert badge is not None, "#status-badge is not rendered"
        assert wrapper.attrs.get("aria-live") == "polite"
        assert "aria-live" not in badge.attrs
        assert wrapper.contains(badge)
        # The wrapper lives inside <small> in the footer, so it must stay
        # phrasing content — a <div> there is invalid.
        assert wrapper.tag == "span", (
            f"#status-live is a <{wrapper.tag}>; it sits inside <small> and "
            f"must be phrasing content"
        )
