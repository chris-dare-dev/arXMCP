# Research Brief — E13_S07b

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-22T21:15:00Z

## In-codebase context

### Canonical redirect-pin pattern in the compliant modules

**`ingest/ar5iv_fetch.py` (lines 216–230):** The canonical pattern reads `response.url` from inside the `with urllib.request.urlopen(...) as response:` block, then checks it AFTER the context manager exits:

```python
            response_url = response.url
        if not response_url.startswith(AR5IV_BASE_URL + "/"):
            logger.warning(
                "ar5iv: response redirected off %s for %s -> %s; "
                "treating as miss",
                AR5IV_BASE_URL, paper_id, response_url,
            )
            return Ar5ivResult(
                paper_id=paper_id,
                hit=False,
                cache_path=None,
                parsed_path=None,
                reason="unexpected_redirect",
            )
```

- Host constant pinned against: `AR5IV_BASE_URL = "https://ar5iv.labs.arxiv.org/html"` — note the trailing `/` is added in the check (`AR5IV_BASE_URL + "/"`)
- On mismatch: **returns a miss result** (does NOT raise). Error type: return value `Ar5ivResult(hit=False, reason="unexpected_redirect")`.

**`ingest/oai_delta.py` (lines 369–374):** Different structure — single HTTP call site in `_fetch_page`, inside the retry loop:

```python
            response_url = response.url
        # F2: pin egress to the configured OAI-PMH endpoint.
        if not response_url.startswith(endpoint):
            raise RuntimeError(
                f"OAI-PMH response redirected off {endpoint}: "
                f"got {response_url!r}; refusing as untrusted"
            )
```

- Host constant: `OAI_PMH_ENDPOINT = "https://oaipmh.arxiv.org/oai"` (passed as `endpoint` parameter)
- On mismatch: **raises `RuntimeError`** (NOT a miss-return). The upstream caller (`harvest_set`) catches `RuntimeError` and converts it to a graceful partial-result.

**Critical implementation choice:** The two existing compliant modules use DIFFERENT error types on mismatch — ar5iv returns a miss, oai_delta raises RuntimeError. The brief says "raise the same error type the existing modules raise." For graph_ingest and inspire_ingest, the fetch functions (`_fetch_openalex_work`, `_fetch_inspire_record`) use the `with urllib.request.urlopen(...) as resp:` pattern and return a dict or None. **Recommendation: raise `RuntimeError` for both**, mirroring oai_delta (not ar5iv), because both graph_ingest and inspire_ingest propagate errors via exception (see `except urllib.error.URLError` in their callers) rather than return-value sentinel. An ar5iv-style miss-return would require caller refactoring.

### `ingest/graph_ingest.py` fetch call sites

Single fetch function: `_fetch_openalex_work` (lines 176–229). It uses:
```python
with urllib.request.urlopen(  # noqa: S310
    request, timeout=timeout
) as resp:
    body = resp.read(OPENALEX_MAX_RESPONSE_BYTES + 1)
    ...
    return json.loads(body.decode("utf-8"))
```

- `resp.url` is available inside the `with` block (same as ar5iv/oai_delta)
- Host constant: `OPENALEX_BASE = "https://api.openalex.org"`
- The function is the SOLE HTTP call site. The guard belongs immediately after `resp.read(...)` and before `json.loads(...)`, or by capturing `response_url = resp.url` inside the block and checking after.
- On mismatch: raise `RuntimeError(f"OpenAlex response redirected off {OPENALEX_BASE}: got {response_url!r}; refusing as untrusted")`

### `ingest/inspire_ingest.py` fetch call sites

Single fetch function: `_fetch_inspire_record` (lines 227–301). It uses:
```python
with urllib.request.urlopen(  # noqa: S310
    request, timeout=timeout
) as resp:
    body = resp.read(INSPIRE_MAX_RESPONSE_BYTES + 1)
    ...
    return json.loads(body.decode("utf-8"))
```

- `resp.url` is available inside the `with` block
- Host constant: `INSPIRE_API_BASE = "https://inspirehep.net/api"` — the check should pin against `"https://inspirehep.net"` (the host-only prefix) OR `INSPIRE_API_BASE`. Since all calls go to `/api/arxiv/<id>`, pinning to `INSPIRE_API_BASE` is narrower and more precise.
- The function is the SOLE HTTP call site.
- On mismatch: raise `RuntimeError(f"INSPIRE response redirected off {INSPIRE_API_BASE}: got {response_url!r}; refusing as untrusted")`

### How `response.url` is exposed

`urllib.request.urlopen` returns an `http.client.HTTPResponse` object (wrapped through redirects). The final URL after all redirects is exposed as `response.url` (an attribute set by urllib's redirect handler). This is the same attribute both compliant modules use. **Do NOT use `.geturl()` — that is a `urllib.request.Request` method, not `HTTPResponse`.**

### Test mirror target: `tests/test_oai_delta.py::TestFetchPageRedirectPin`

```python
class TestFetchPageRedirectPin:
    """Closes F2: off-host redirects rejected."""

    def test_off_host_response_url_rejected(self):
        with patch(
            "ingest.oai_delta.urllib.request.urlopen",
            return_value=_FakeUrlOpenResponse(
                body=b"<ok\>", url="https://evil.example/x"
            ),
        ), pytest.raises(RuntimeError, match="redirected off"):
            _fetch_page(...)

    def test_on_host_response_url_accepted(self):
        with patch(
            "ingest.oai_delta.urllib.request.urlopen",
            return_value=_FakeUrlOpenResponse(
                body=b"<ok/>",
                url=f"{OAI_PMH_ENDPOINT}?verb=ListRecords",
            ),
        ):
            body = _fetch_page(...)
        assert body == b"<ok/>"
```

The `_FakeUrlOpenResponse` is a context-manager stub with `.url`, `.headers`, and `.read()`. It lives in `tests/test_oai_delta.py` (lines 936–974). The new tests in `tests/security/test_source_ingest.py` should define their own equivalent stub or import this helper — **prefer defining a local stub** in the security test file to avoid coupling to a non-security test module's internals.

### Existing test files (regression AC)

- `tests/test_graph_ingest.py` — exists; tests mock `_fetch_openalex_work` via monkeypatch
- `tests/test_inspire_ingest.py` — exists; tests mock `_fetch_inspire_record` via monkeypatch
- `tests/security/test_source_ingest.py` — EXISTS (E13_S07). The new redirect-pin tests go IN this existing file as a new class, not a new file.

### Security doc state

- `.claude/docs/security-threat-7-audit.md` — compliance matrix at line 35 shows both `ingest/graph_ingest.py` and `ingest/inspire_ingest.py` with `⚠️ not pinned (follow-up)` in the Redirect-host pin column. The Known gaps section (line 217–224) documents the gap explicitly. This file must be updated to mark the gap closed.
- `.claude/docs/security-threat-model-coverage.md` — Threat 7 row cites `[#2 — redirect-host validation on graph/inspire ingest](https://github.com/chris-dare-dev/arXMCP/issues/2)` in the Gaps column. Gap-issue triage table row G2 shows `MEDIUM | Real coverage gap`. Both must be updated.
- `tests/security/test_threat_model_coverage.py` — the staleness gate checks every cited `tests/security/test_*.py` file exists AND every existing security test file is cited in the coverage doc. Adding a new class to the existing `test_source_ingest.py` (already cited) requires NO coverage-doc update for the citation gate. HOWEVER, the Threat 7 row in the coverage doc DOES need its Gaps cell updated (removing the #2 link) — the gap-row well-formedness test (`TestGapRowsWellFormed`) checks that remaining gap cells are either `(none)`, em-dash, `(TODO file issue...)`, or a github.com/issues/N URL. After #2 is closed, the cell must use `(none)` or reference the closed issue with a note; leaving the bare URL to an open issue when it's closed is still well-formed but ideally should note the closure.

**No tool-schema re-pinning required** — this milestone touches only `ingest/` and `tests/`, not `server/tools.py`.

## Prior decisions and lessons

Recent git log shows post-E13 work on proof-verify-handler-wiring milestones (UI, Lean REPL, citation handler). E13 is fully complete per CLAUDE.md §3. The E13_S07 state.json confirms:
- Phase: `complete`
- E13_S07 EXISTS and DID perform the Threat 7 audit (verified by state.json and the audit doc)
- The fictional-prerequisite pattern (common in E13 briefs for E06_S07, E07_S09 etc.) does NOT apply here — E13_S07 is a real, complete milestone

Memory note: The E13_S07 memory entry documents that `urllib.request` (not httpx) is used everywhere and that `ingest/sources/` directory does not exist — both confirmed here.

**No conflicts detected between the brief and codebase.** The brief accurately describes the gap: graph_ingest and inspire_ingest have no `response.url` check. The host constants (`OPENALEX_BASE`, `INSPIRE_API_BASE`) are real and correct.

**One important discrepancy to flag:** The brief says "raise the same error type the existing modules raise" but the two compliant modules raise DIFFERENT types (ar5iv returns a miss; oai_delta raises RuntimeError). **The implementer must pick one — recommend RuntimeError for both** (see Recommendation section).

## External sources

### OpenAlex API redirect behavior

OpenAlex API (`https://api.openalex.org`) does NOT legitimately redirect to a different host. All API paths are served from `api.openalex.org`. There is no `http://api.openalex.org` → `https://api.openalex.org` redirect concern because the code already constructs HTTPS URLs via `OPENALEX_BASE = "https://api.openalex.org"` and `_build_works_url`. The canonical identifier URL (`/works/https%3A%2F%2Farxiv.org%2Fabs%2F<id>`) returns a JSON record from `api.openalex.org` — no cross-host redirect is expected or documented.

**Safe host pin:** `OPENALEX_BASE = "https://api.openalex.org"` — pinning `response.url.startswith(OPENALEX_BASE)` is correct and will not trigger false positives on legitimate responses. The `?mailto=...` query string is appended to the URL, so `response.url` will look like `https://api.openalex.org/works/...?mailto=...` which passes `startswith("https://api.openalex.org")`.

### INSPIRE-HEP API redirect behavior

INSPIRE-HEP (`https://inspirehep.net/api/arxiv/<id>`) does NOT legitimately redirect cross-host. The API endpoint is stable at `inspirehep.net`. The path prefix is `/api/` so pinning `INSPIRE_API_BASE = "https://inspirehep.net/api"` is safe — legitimate responses will have URLs starting with this prefix. The `?fields=...` query appended in `_build_record_url` becomes part of the URL; `response.url.startswith(INSPIRE_API_BASE)` still passes because `startswith` checks a prefix, not an exact match.

**Trailing slash nuance:** `INSPIRE_API_BASE = "https://inspirehep.net/api"` without a trailing slash means `https://inspirehep.net/apiFAKE` would technically pass `startswith("https://inspirehep.net/api")`. However, this is an extremely unlikely attack vector (would require `inspirehep.net` to redirect to `inspirehep.net/apiFAKE/...`). Mirroring oai_delta's simpler `startswith(endpoint)` pattern (no trailing slash added) is the correct approach for consistency. Both existing modules use the raw base URL without adding a trailing slash in the check (oai_delta checks `startswith(endpoint)` where endpoint is `https://oaipmh.arxiv.org/oai`; ar5iv checks `startswith(AR5IV_BASE_URL + "/")` WITH a trailing slash since the base URL has no trailing slash and path components follow). For INSPIRE, `https://inspirehep.net/api` is always followed by `/arxiv/...`, so `startswith(INSPIRE_API_BASE)` is fine.

**ar5iv pattern uses `/` suffix because:** `AR5IV_BASE_URL = "https://ar5iv.labs.arxiv.org/html"` — without the `/` suffix, `https://ar5iv.labs.arxiv.org/html-evil` would pass. For OpenAlex and INSPIRE, the same concern applies: pin with explicit path separator to prevent prefix collision attacks. Recommend: `startswith(OPENALEX_BASE + "/")` and `startswith(INSPIRE_API_BASE + "/")`.

## Recommendation

**Add `RuntimeError`-raising redirect-host checks to both `_fetch_openalex_work` and `_fetch_inspire_record` by capturing `response_url = resp.url` inside the `with urlopen(...) as resp:` block and raising after the block exits if the URL fails `startswith`.** Add a new class `TestRedirectHostPin` to the existing `tests/security/test_source_ingest.py` with two parametrized or separate tests per module (off-host rejected, on-host accepted). Update both audit docs to mark the gap closed.

Use RuntimeError (not ar5iv's miss-return) because graph_ingest and inspire_ingest propagate errors via exceptions through their callers; a return-value sentinel would require caller-side refactoring. Use `OPENALEX_BASE + "/"` and `INSPIRE_API_BASE + "/"` as the startswith prefix to mirror the ar5iv trailing-slash pattern and prevent prefix-collision attacks. The error message should mirror oai_delta: `f"OpenAlex response redirected off {OPENALEX_BASE}: got {response_url!r}; refusing as untrusted"`.

## Open questions

**Placement of `response_url = resp.url` capture:** It must be inside the `with` block (before `resp` is closed). The check itself can be either inside or immediately after the block. Both ar5iv (after) and oai_delta (after) do it after the block. Recommend: capture inside, check after — consistent with both existing implementations.

No other open questions — implementation can proceed on the above recommendation.

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| `git push` | `main` branch on `github.com/chris-dare-dev/arXMCP` | Deliver the implementation commit(s) to remote |
| `gh issue close` | `chris-dare-dev/arXMCP#2` | Close the gap issue filed by E13_S10 once the implementation lands; Phase 4 main-thread only |
