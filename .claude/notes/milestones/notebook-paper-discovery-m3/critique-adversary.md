# Critique — notebook-paper-discovery-m3

**Critic:** adversary
**Generated:** 2026-05-31T19:33:10Z
**Commit range:** 05697597979f6f19a55d6a93d849d459285a76ea..cd7d2a095dca1348c25649ee909344dd816ea199
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: one MEDIUM dedup-correctness gap when notebook_papers holds versioned IDs
- 0 CRITICAL, 0 HIGH, 1 MEDIUM, 0 LOW
- Highest-risk line: `tools/discover_for_notebook.py:98` (dedup set built from raw stored IDs)
- The research synthesis at synthesis.md line 101 asserted "add_paper produces un-versioned
  IDs" — false; the URL-paste route stores whatever is extracted from the URL (e.g.
  `2604.26204v3`), as confirmed by `tests/test_notebook_api.py:264`
- All 8 axes walked; 7 are clean; only Axis 3(c)/Axis 8 carry the MEDIUM
- Banned-pattern checklist clean: no `assert`, no `BaseHTTPMiddleware`, no fork, no 0.0.0.0
- Tool-schema hash, prompts.py, and ALL_TOOLS are unchanged (Axis 1 verified clean)
- No new egress host, no new pip dependency, no MCP surface change

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Dedup silently misses versioned paper_ids in notebook_papers

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `tools/discover_for_notebook.py:98`
- **What:** `existing_ids = {p["paper_id"] for p in await store.list_papers(slug)}` builds the
  dedup set from whatever `notebook_papers.paper_id` stores. The URL-paste route
  (`server/routes/notebooks.py:160,697`) passes the raw candidate from
  `_arxiv_url_to_paper_id` — which calls `is_valid_arxiv_paper_id` and returns the candidate
  verbatim — to `store.add_paper`. `is_valid_arxiv_paper_id` accepts versioned IDs (pattern
  `^\d{4}\.\d{4,5}(v\d+)?\Z`), so a paper added via
  `https://arxiv.org/abs/2604.26204v3` is stored as `"2604.26204v3"`.
  `parse_atom_feed` strips the `vN` suffix (line 181 of `_arxiv_api.py`:
  `paper_id = paper_id.split("v", 1)[0]`), yielding `"2604.26204"`. The membership test
  `"2604.26204" not in {"2604.26204v3"}` is `True`, so the paper is re-proposed even
  though it is already in the notebook.
- **Why it matters:** Silent dedup failure — a paper the operator deliberately added
  (e.g., by URL-paste of a specific version) reappears in every discovery run until
  deduplication is correct. The research synthesis FM-d claimed both sides are
  un-versioned, but `tests/test_notebook_api.py:264` falsifies this:
  `assert r.json()["paper_id"] == "2604.26204v3"`.  The dedup tests all seed the store
  with unversioned IDs (`"2307.00001"` etc.) via direct `store.add_paper()` calls, so
  the gap is untested.
- **Proposed fix:** Normalize the dedup set to strip version suffixes:
  ```python
  # tools/discover_for_notebook.py:98
  def _strip_version(pid: str) -> str:
      return pid.split("v", 1)[0] if "v" in pid else pid

  existing_ids = {
      _strip_version(p["paper_id"])
      for p in await store.list_papers(slug)
  }
  ```
  Alternatively (more targeted): at the dedup line itself, the `c.paper_id` from
  `parse_atom_feed` is already stripped; only the `existing_ids` side needs normalization.
  The fix is ≤5 LOC.
- **Regression guard:** Add a test to `tests/test_discover_for_notebook.py`:
  ```python
  def test_dedup_handles_versioned_existing_paper(
      self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
  ) -> None:
      monkeypatch.setattr(
          _arxiv_api, "_fetch_url",
          lambda url, contact_email=None: _feed(_THREE),
      )

      async def _run() -> list[DiscoveryCandidate]:
          store = await _seed_store(tmp_path / "notebooks.db")
          # Simulate URL-paste adding a versioned ID
          await store.add_paper("bridgeland", "2307.00001v2", "2026-05-31T00:00:00+00:00")
          try:
              return await discover_for_notebook_async(
                  store, "bridgeland", sleep=_NOOP_SLEEP,
              )
          finally:
              await store.close()

      out = asyncio.run(_run())
      # 2307.00001v2 in store matches 2307.00001 from feed -> must be deduped
      assert "2307.00001" not in {c.paper_id for c in out}
      assert [c.paper_id for c in out] == ["2307.00002", "2307.00003"]
  ```

## What was done well

- All four acceptance criteria are covered by tests; the AC1 happy-path test
  (`test_returns_new_and_dedups_existing`) exercises a real `NotebooksStore` on a
  `tmp_path` SQLite and correctly seeds a pre-existing paper to verify dedup.
- The `_arxiv_api.Candidate` extension is purely additive: `title` and `submitted_date`
  carry defaults (`""`), the existing keyword-only constructions in
  `test_fetch_seed.py::TestFilterCandidates._candidate` and `test_arxiv_api.py::TestReExport`
  remain unbroken, and `as_tsv_row` still emits 5 columns.
- The empty-category guard fires BEFORE any HTTP call (verified by
  `test_empty_category_does_not_call_arxiv`), so a misconfigured notebook never touches
  the arXiv API.
- The injection-safety argument is sound: `description` passes through unmodified to
  `abs_keywords`; m2's `_keyword_clause` quotes the phrase and strips embedded double-quotes
  in one place, not two.
- `fetch_candidates` receives the injected `sleep` callable and the test wires
  `sleep=_NOOP_SLEEP` throughout, so the politeness contract is testable without real
  wall-clock delays.
- No banned patterns introduced: no `assert` for invariants, no `BaseHTTPMiddleware`,
  no `anthropic` SDK import, no `0.0.0.0` bind, no `git push` in code.
- The `DiscoveryCandidate` decoupling from `Candidate` is the right abstraction: it
  hides arXiv-internal fields (`n_authors`, `primary_category`, `submitted_year`) from
  the m4 console panel contract, making the boundary stable.
- `asyncio.run` use in the sync wrapper mirrors the established `notebook_init.py`
  pattern; the wrapper opens and closes the store in a `try/finally`, so store cleanup
  runs even if `discover_for_notebook_async` raises.
- The `test_blank_description_is_category_only` test confirms the `keywords or None`
  sentinel correctly produces a category-only query, closing the rect-F1 blank-after-strip
  interaction inherited from m2.

## Recommended rectification order

1. **F1** — strip version suffixes in the `existing_ids` set (≤5 LOC in
   `tools/discover_for_notebook.py:98`) + add the `test_dedup_handles_versioned_existing_paper`
   regression test (≤25 LOC in `tests/test_discover_for_notebook.py`).

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
