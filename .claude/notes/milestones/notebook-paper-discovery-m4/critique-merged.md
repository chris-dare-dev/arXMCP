# Critique — notebook-paper-discovery-m4

**Critic:** adversary
**Generated:** 2026-05-31T18:00:00Z
**Commit range:** 96b6338d4cd4fec18d3c13ac9896195ee5c7b5ce..a7d79711f8a7c96c6f3de5b86f817c111e265abe
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: one HIGH (ParseError escapes the except-tuple and produces a 500, directly
  contradicting the route's own docstring invariant "never a 500")
- 0 CRITICAL, 1 HIGH, 1 MEDIUM, 2 LOW
- Highest-risk line: `server/routes/notebooks.py:744` — `except (RuntimeError, OSError)` does
  not catch `xml.etree.ElementTree.ParseError` (a `SyntaxError` subclass), which `parse_atom_feed`
  can raise when arXiv returns a non-XML response (redirect landing page, maintenance HTML, etc.)
- XSS escaping verified complete: every interpolated value in `_discover_results_fragment` is
  `html.escape`'d; the `html.escape(c.title) or "—"` precedence is correct; `len(candidates)`
  is a safe int; the XSS test round-trip is sound (XML-encoded hostile title decodes to text,
  then re-escaped on emit)
- Axis 1 (cache byte-stability) clean: `server/tools.py`/`ALL_TOOLS` untouched; `EXPECTED_TOOL_SCHEMA_SHA256` unchanged
- The "Add" form-to-JSON conversion relies on the `htmx:configRequest` shim in `base.html`
  (already shipped); the discover fragment is injected into the live page so the shim covers it
  in the browser — no production bug, but the test fixture bypasses JavaScript so AC2 is
  untested end-to-end
- Axes 2, 4, 5, 7 clean (metadata-only, no MCP tool, no new egress host, no forked code)

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings

### F1 — ParseError escapes except-tuple -> 500 on malformed arXiv response

- **Severity:** HIGH
- **Source:** adversary
- **File:** `server/routes/notebooks.py:744`
- **What:** `discover_papers` catches `(RuntimeError, OSError)` for the "parse failure" path, but
  `defusedxml.ElementTree.fromstring` raises `xml.etree.ElementTree.ParseError` (a subclass of
  `SyntaxError`, not `RuntimeError` or `OSError`) when given non-XML bytes. A non-XML arXiv
  response (maintenance HTML page, redirect landing page, or a truncated response) causes an
  unhandled exception that FastAPI surfaces as HTTP 500.
- **Why it matters:** The route's own docstring at line 714 states "arXiv failures and
  unconfigured notebooks return 4xx/502 — never a 500." The `except (RuntimeError, OSError)`
  comment on line 744–745 explicitly lists "parse failure" as a case it covers, but it
  does not. `xml.etree.ElementTree.ParseError` is `SyntaxError.__subclass__`; confirmed via
  `print(ET.ParseError.__mro__)`. The project precedent for catching this is already set in
  `server/retrieval/equations.py:133` (`except DET.ParseError as exc`). The failure mode is
  reachable whenever arXiv returns HTML (maintenance window, Cloudflare captcha, CDN redirect)
  instead of Atom XML.
- **Proposed fix:** Add `ET.ParseError` (importable as `xml.etree.ElementTree.ParseError`, or
  equivalently since `parse_atom_feed` uses `defusedxml`, catch `Exception as e` with a narrow
  isinstance guard) to the existing except clause:
  ```python
  # server/routes/notebooks.py
  import xml.etree.ElementTree as ET
  # ...
  except (RuntimeError, OSError, ET.ParseError) as e:
      raise HTTPException(
          status_code=status.HTTP_502_BAD_GATEWAY,
          detail=f"discovery failed: {e}",
      ) from e
  ```
  Alternatively (and more robustly), catch it at the source in `tools/_arxiv_api.py::parse_atom_feed`
  by wrapping `DET.fromstring(xml_bytes)` in `try/except ET.ParseError as exc: raise RuntimeError(...) from exc`.
  That keeps the route's except-tuple unchanged and matches the pattern in `equations.py`.
- **Regression guard:** Add `TestDiscoverErrors::test_malformed_xml_502_not_500`:
  monkeypatch `_arxiv_api._fetch_url` to return `b"<html>maintenance</html>"`;
  assert `r.status_code == 502` and `"discovery failed" in r.json()["detail"]`.

---

### F2 — AC2 end-to-end Add path untested in discover test suite

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tests/test_discover_route.py:113`
- **What:** `test_renders_candidates` asserts the Add mini-form's `hx-post` attribute targets
  `/ui/api/notebooks/bridgeland/papers` and that the hidden `arxiv_url` `value` is correctly
  rendered. It does NOT actually call that route with the extracted URL to verify the junction
  row is recorded. AC2 ("Add -> ingested into LanceDB + recorded in notebook_papers") is
  therefore untested at the integration level.
- **Why it matters:** The `add_paper` route accepts only JSON (`PaperAdd: BaseModel`), not
  `application/x-www-form-urlencoded`. The form-to-JSON conversion in the browser relies on
  the `htmx:configRequest` shim in `base.html`. Test clients bypass JavaScript, so they would
  send form-encoded data and receive a 422. The route itself is separately tested and correct,
  but the discover→Add round-trip has no regression test. If someone later modifies the fragment
  URL pattern (`value="https://arxiv.org/abs/{pid}"`), no test would catch the break.
- **Proposed fix:** Add a focused integration test that (a) runs discover to get the fragment,
  (b) extracts the `arxiv_url` value from the fragment HTML, and (c) POSTs it as JSON to the
  add-paper route, asserting a 201 and that the paper appears in `list_papers`:
  ```python
  def test_add_from_discover_fragment_records_paper(
      self, client: TestClient, monkeypatch: pytest.MonkeyPatch,
  ) -> None:
      monkeypatch.setattr(_arxiv_api, "_fetch_url",
          lambda url, contact_email=None: _feed(_THREE))
      _make_notebook(client)
      r = client.post("/ui/api/notebooks/bridgeland/discover")
      # Extract first arxiv_url from fragment
      import re
      urls = re.findall(r'value="(https://arxiv\.org/abs/[^"]+)"', r.text)
      assert urls, "no arxiv_url found in fragment"
      add = client.post(
          "/ui/api/notebooks/bridgeland/papers",
          json={"arxiv_url": urls[0]},
      )
      assert add.status_code == 201, add.text
      papers = client.get("/ui/api/notebooks/bridgeland/papers").json()
      assert any(p["paper_id"] in urls[0] for p in papers)
  ```
- **Regression guard:** The test itself is the regression guard.

---

## What was done well

- XSS coverage is genuinely thorough: all five interpolated values in `_discover_results_fragment`
  (`safe_slug`, `pid`, `c.title`, `c.submitted_date`, `c.abstract_head`) are `html.escape`'d;
  `len(candidates)` is an int and never interpolated as user data; the `html.escape(c.title) or "—"`
  precedence is correct (escapes first, then checks for empty string, then falls back to em-dash).
- The XSS test fixture is sound: placing `&lt;script&gt;alert(1)&lt;/script&gt;` as the title in the
  feed XML means the XML parser decodes it to the text `<script>alert(1)</script>`, and
  `html.escape` re-encodes it to `&lt;script&gt;…`, which the test then asserts is present and the
  raw script tag is absent. The round-trip is faithful to the real arXiv threat model.
- `validate_slug` is called FIRST before any store access or external call — correct path-traversal
  defense order matching `08-security-observability-ops.md` Threat 1.
- Error-handling for the common cases is clean: slug validation (422) → unknown slug (404) →
  unconfigured notebook / no `discovery_category` (422 via `ValueError`) → arXiv unreachable
  (502 via `RuntimeError`/`OSError` from `urllib.error.URLError`, which IS an `OSError` subclass).
- No MCP tool surface was touched: `server/tools.py`, `ALL_TOOLS`, and `EXPECTED_TOOL_SCHEMA_SHA256`
  are byte-identical across the commit range — Axis 1 is unambiguously clean.
- The `_safe_contact_email()` bare-except pattern is correctly scoped and documented: it is
  explicitly a best-effort degradation, not a silent invariant violation.
- The `htmx:configRequest` shim (already in `base.html`) correctly handles the form-to-JSON
  conversion for the Add mini-forms, and the discover fragment is injected into the live page
  so the shim applies in the browser without any extra wiring.
- The `DiscoveryCandidate` `TYPE_CHECKING`-only import is safe because `from __future__ import
  annotations` is present at the top of `server/routes/notebooks.py` — annotations are not
  evaluated at runtime.
- The deviation from the brief ("Add records junction only; embedding via separate Ingest") is
  documented in both the implementation summary and `notebook-discovery-model.md §3a`, and is
  consistent with the existing URL-paste add-paper pattern.
- `aria-live="polite"` and `aria-atomic="true"` are re-emitted on the swapped `#discover-results`
  `<div>` in both the server-rendered fragment and the initial placeholder — the `outerHTML` swap
  correctly preserves the live region for screen readers (the `ui-attractive-polish-m1` lesson
  is applied here).

## Recommended rectification order

1. **F1** (`server/routes/notebooks.py:744` + `tools/_arxiv_api.py::parse_atom_feed`): Add
   `ET.ParseError` to the catch clause (or wrap at source). Add the `test_malformed_xml_502_not_500`
   regression test. This is the only fix required before shipping; it is ≤ 5 LOC.
2. **F2** (`tests/test_discover_route.py`): Add the discover→Add integration test. ~15 LOC; cheap
   and closes the AC2 gap. Fix only if cheap (MEDIUM).

## deferred_findings

- **F3 (LOW):** `_safe_contact_email()` (`server/routes/notebooks.py:628`) calls
  `get_contact_email()` with `DEFAULT_DB_PATH` (`var/arxmcp/cache/notebooks.db` relative to CWD),
  not the `NotebooksStore`'s actual db path. In the production default (single user, CWD = repo
  root), both paths resolve to the same file. In tests, the fixture uses a `tmp_path` db, so
  `_safe_contact_email` silently returns `None` via the bare except. This is a correctness
  quirk (tests never exercise the contact-email path through this shim) but not a production
  bug. Fix: accept an optional `db_path` parameter and thread it from the route's `store`.
- **F4 (LOW):** `discover_papers` (`server/routes/notebooks.py:698`) calls
  `discover_for_notebook_async` which calls `fetch_candidates` (sync `urllib`, 60s timeout) on
  the event loop thread without `asyncio.to_thread`. This blocks all other loopback routes
  (including `/ui/status-badge` polls and `/readyz`) for up to 60 seconds if arXiv is slow.
  The route docstring documents this as "accepted for the single-operator loopback console."
  Acceptable for v1; upgrade path is wrapping the call in `await asyncio.to_thread(fetch_candidates, ...)`.

## Rectification status (filled by Phase 4)

- F1 (HIGH) — fixed at SOURCE in `tools/_arxiv_api.py::parse_atom_feed`: `DET.fromstring`
  is wrapped in `try/except DET.ParseError -> raise RuntimeError(...)` (the
  `equations.py` precedent), so a non-XML/truncated arXiv response becomes a
  `RuntimeError` that the route's `except (RuntimeError, OSError)` maps to 502 — never a
  500. Fixing at source hardens every `parse_atom_feed` caller (m3 driver included), not
  just the route. Regression guards:
  `tests/test_arxiv_api.py::TestParseAtomFeed::test_non_xml_response_raises_runtimeerror`
  and `tests/test_discover_route.py::TestDiscoverErrors::test_malformed_xml_502_not_500`.
- F2 (MEDIUM) — fixed: added
  `tests/test_discover_route.py::TestDiscoverAddRoundTrip::test_add_from_discover_fragment_records_paper`,
  which extracts the `arxiv_url` from the discover fragment, POSTs it (as the browser's
  JSON shim would) to the add-paper route, and asserts the junction records the paper —
  closing the AC2 end-to-end gap.
- F3 (LOW) — deferred. `_safe_contact_email` reads `DEFAULT_DB_PATH`, which equals the
  store's db in the production single-user default; the bare-except degrades to `None` in
  tests. Production-correct; threading the store's db_path is a future nicety.
- F4 (LOW) — deferred. The synchronous arXiv fetch briefly blocks the event loop;
  documented + accepted for the single-operator loopback console (`MAX_RESPONSE_BYTES`
  caps the response). Upgrade path: `await asyncio.to_thread(fetch_candidates, ...)`.

Re-verify gate: F1 re-verified — `parse_atom_feed` did `DET.fromstring` with no
`ParseError` catch (`_arxiv_api.py:166`), and the route's `except (RuntimeError, OSError)`
(`notebooks.py:744`) excludes `ParseError` (a `SyntaxError` subclass; confirmed live).
No findings invalidated. Adversary invalidation rate: 0%.
