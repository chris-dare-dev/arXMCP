# Research Brief — E13_S07b

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-22T00:00:00Z

## In-codebase context

### Design notes that apply

`08-security-observability-ops.md` § Threat 7 (verbatim):
> We fetch from arxiv.org and ar5iv.labs.arxiv.org. If either is compromised,
> we ingest poisoned content.
> **Mitigations:** Verify TLS certs ... Content-length sanity checks (a single
> paper > 100 MB source is suspicious). Sandbox the parser (Threat 3
> mitigation covers downstream impact).

`07-multi-agent-caching.md` is not directly load-bearing for this milestone —
no MCP tool surface is modified, no `EXPECTED_TOOL_SCHEMA_SHA256` re-pinning
required.

### The canonical redirect-pin pattern (ar5iv_fetch.py lines 216–230)

```python
response_url = response.url
if not response_url.startswith(AR5IV_BASE_URL + "/"):
    logger.warning(
        "ar5iv: response redirected off %s for %s -> %s; treating as miss",
        AR5IV_BASE_URL, paper_id, response_url,
    )
    return Ar5ivResult(..., reason="unexpected_redirect")
```

`AR5IV_BASE_URL = "https://ar5iv.labs.arxiv.org/html"` — note the check adds
a trailing slash before the `startswith` call: `AR5IV_BASE_URL + "/"`. This
means only responses whose URL starts with `https://ar5iv.labs.arxiv.org/html/`
are accepted — same-host paths are allowed, cross-host URLs are rejected.

### The canonical redirect-pin pattern (oai_delta.py lines 368–374)

```python
response_url = response.url
if not response_url.startswith(endpoint):
    raise RuntimeError(
        f"OAI-PMH response redirected off {endpoint}: "
        f"got {response_url!r}; refusing as untrusted"
    )
```

`oai_delta` raises `RuntimeError` on redirect mismatch; `ar5iv_fetch` returns
a miss-result (no raise). The existing modules use DIFFERENT error behaviors.
The brief says "raise the same error type the existing modules raise" — but the
two existing modules disagree with each other. See Failure mode #1.

### `graph_ingest.py` HTTP layer

`OPENALEX_BASE = "https://api.openalex.org"` (line 117). Single HTTP fetch
function: `_fetch_openalex_work`. It calls `urllib.request.urlopen(request,
timeout=timeout)` inside a `with` block and reads `resp.read(...)`. There is
**no `response.url` check** after the read. The `response.url` attribute IS
available on urllib responses (it comes from `HTTPResponse.url` which is set by
`HTTPRedirectHandler` on the final response object — the same attribute both
`ar5iv_fetch.py` and `oai_delta.py` use). No cursor/next URL pattern exists in
`graph_ingest.py` — it fetches one JSON response per paper, not paginated.

### `inspire_ingest.py` HTTP layer

`INSPIRE_API_BASE = "https://inspirehep.net/api"` (line 142). Single HTTP fetch
function: `_fetch_inspire_record`. Same urllib/urlopen pattern, no `response.url`
check. Uses `?fields=` parameter to narrow response. No pagination / cursor
pattern in the single-record fetch. The `--include-back-refs` path (paginated
`?q=refersto:recid:<n>`) is NOT IMPLEMENTED and not part of this milestone
scope.

### Existing test file to mirror

`tests/test_oai_delta.py::TestFetchPageRedirectPin` (lines 739–770) has two
tests: `test_off_host_response_url_rejected` and `test_on_host_response_url_accepted`.
Target: `tests/security/test_source_ingest.py` — ADD to existing file, don't
create a new file (the brief says "mirroring
`tests/test_oai_delta.py::TestFetchPageRedirectPin`").

### The compliance matrix from the E13_S07 audit doc (verbatim)

> | `ingest/graph_ingest.py` | ✅ | n/a (per-service cap is tighter) | ✅ existing | ⚠️ not pinned (follow-up) | 5 MB |
> | `ingest/inspire_ingest.py` | ✅ | n/a (per-service cap is tighter) | ✅ existing | ⚠️ not pinned (follow-up) | 8 MB |

This confirms: TLS is already safe-by-default, per-service byte caps exist (5 MB
and 8 MB respectively). E13_S07b adds ONLY the redirect-host pin.

### Mock target pattern

Both `graph_ingest.py` and `inspire_ingest.py` docstrings declare:
> "THIS FUNCTION IS THE INTEGRATION-TEST MOCK TARGET. Tests use
> `monkeypatch.setattr(graph_ingest, '_fetch_openalex_work', ...)` /
> `monkeypatch.setattr(inspire_ingest, '_fetch_inspire_record', _stub)`"

The guard must be placed INSIDE the respective `_fetch_*` function (inside the
`with urllib.request.urlopen(...) as resp:` block, after `resp.read()`), so the
unit test can mock `urllib.request.urlopen` to return a fake response with a
controlled `.url` attribute — the same mock pattern used in `test_ar5iv_fetch.py`
and `test_source_ingest.py`.

**CRITICAL NOTE on `response.url` vs `geturl()`:** Python's `urllib.request`
response object exposes the post-redirect URL via `response.url` (since Python
3.x, this attribute is populated by `HTTPRedirectHandler`). Both existing
modules use `.url` directly. `geturl()` is the older equivalent. Use `.url`
for consistency with the existing pattern.

### Constraint from agent-conventions.md

Tool-schema re-pinning (`EXPECTED_TOOL_SCHEMA_SHA256`) is NOT required — this
milestone adds no MCP tool, modifies no `ALL_TOOLS` entry.

### Doc placement

`security-threat-7-audit.md` is at `.claude/docs/security-threat-7-audit.md`
(established precedent per E13_S01–S10 audit-doc placement rule).
`security-threat-model-coverage.md` is at
`.claude/docs/security-threat-model-coverage.md`. Both are correct. Do NOT
write to `docs/security/`.

## Prior decisions and lessons

Recent git log (from the repo state at start of session):
```
c9df7f1 feat(server): Lean REPL subprocess harness (verification-feedback-m2)
d9af59d Merge branch 'main'
f22a73b chore(notes): finalize verification-feedback-m1 state -> complete
3e4dcd6 rect(server): close F1-F4 from verification-feedback-m1 critique
01b8788 chore(notes): finalize proof-verify-handler-wiring-m10 state -> complete
```

E13 milestones are complete (E13_S10 shipped). GitHub issue #2 was filed at the
E13_S10 Phase-4 boundary (confirmed in `security-threat-model-coverage.md`).
This milestone closes that issue.

**From memory (E13_S07):** `ingest/sources/` does not exist — all HTTP clients
are scattered in `ingest/` and `tools/`. All use `urllib.request`. No `httpx`.

**From E13_S07 audit doc Known gaps (verbatim):**
> `ingest/graph_ingest.py` and `ingest/inspire_ingest.py` do NOT validate
> redirect hosts after fetch. ar5iv and oai_delta both do. A graph/INSPIRE
> redirect to attacker-controlled hosts is mitigated only by TLS verification
> (any attacker-controlled host would need a valid cert for the new domain).
> A follow-up hardening pass should add the same `response.url.startswith(...)`
> guard used by ar5iv.

Severity in gap triage: MEDIUM (G2).

**Pattern from CLAUDE.md §4.7:** `assert` for invariants is BANNED. Use
`if ... raise RuntimeError(...)` instead. The redirect pin raises `RuntimeError`
in `oai_delta.py` — follow that pattern for both new implementations.

**macOS segfault guard** (`KMP_DUPLICATE_LIB_OK=TRUE` in `tests/conftest.py`)
is not touched by this milestone.

## External sources

### Python `urllib.request` redirect behavior

`urllib.request.urlopen` follows 30x redirects automatically via the built-in
`HTTPRedirectHandler`. On the final (post-redirect) response object, the URL
that was actually fetched is available as `response.url` — this is populated by
the handler and is exactly what both `ar5iv_fetch.py` and `oai_delta.py`
already use. `response.geturl()` is an older equivalent; prefer `.url` for
consistency with the existing pattern.

### OpenAlex API redirect behavior

Canonical base URL: `https://api.openalex.org`. Per OpenAlex documentation, the
API issues 301 redirects when merged/deprecated entity records are accessed.
These are SAME-HOST redirects (e.g., `/works/W123` → `/works/W456`), not
cross-host redirects. Normal production ingest (`/works/<arxiv-url-encoded>`)
does NOT redirect cross-host. A strict `response.url.startswith("https://api.openalex.org")`
check will survive same-host redirects (both the original URL and the redirect
target start with `https://api.openalex.org`). This pin is safe for production.

**Important:** `http://api.openalex.org` (without TLS) would NOT start with
`"https://api.openalex.org"`. Since we always construct HTTPS URLs, this is a
non-issue. If OpenAlex ever issues an http-to-https redirect (unlikely since we
construct the URL with `https://` from `OPENALEX_BASE`), the redirect URL would
start with `https://` and the check passes.

### INSPIRE-HEP API redirect behavior

Canonical base URL: `https://inspirehep.net/api/` (no `www.` prefix). The API
consistently uses the apex `inspirehep.net` domain. No evidence of `www.`
subdomain redirects or cross-host redirects in normal operation.

`INSPIRE_API_BASE = "https://inspirehep.net/api"` — the per-paper URL pattern
is `https://inspirehep.net/api/arxiv/<id>?fields=...`. A `response.url.startswith("https://inspirehep.net")`
check is the right scope — it covers the full domain including both the API
path and any same-host redirect that INSPIRE might issue. Using the full
`INSPIRE_API_BASE` prefix (`"https://inspirehep.net/api"`) is even more precise
and is the correct choice for defense-in-depth.

## Recommendation

**Implement the redirect-pin guard inside each `_fetch_*` function, immediately
after `resp.read(...)`, before the `with` block closes. Raise `RuntimeError`
in both implementations (matching `oai_delta.py`, the more conservative
existing behavior). Pin `graph_ingest` to `OPENALEX_BASE` and `inspire_ingest`
to `INSPIRE_API_BASE`.**

Concretely:

For `graph_ingest._fetch_openalex_work`, inside the `with urllib.request.urlopen(...) as resp:` block, after reading the body but before `return json.loads(...)`:
```python
response_url = resp.url
if not response_url.startswith(OPENALEX_BASE):
    raise RuntimeError(
        f"OpenAlex response redirected off {OPENALEX_BASE}: "
        f"got {response_url!r}; refusing as untrusted (Threat 7)"
    )
```

For `inspire_ingest._fetch_inspire_record`, the same pattern using `INSPIRE_API_BASE`.

The guard must appear INSIDE the `with` block (before `__exit__` is called),
mirroring the `oai_delta.py` pattern where `response_url = response.url` is
captured inside the `with` block and the check runs immediately after. Using
`RuntimeError` matches `oai_delta.py` (not the miss-return of `ar5iv_fetch.py`)
because these are pipeline-critical fetches where a redirect is unambiguously
wrong and should abort the paper, not silently skip it.

The brief says "raise the same error type the existing modules raise" — the two
existing modules disagree (one raises `RuntimeError`, one returns a miss). Pick
`RuntimeError` because it is more appropriate for a pipeline fetch where silent
skip would mask a potential attack.

For tests: add a `TestRedirectHostPinGraphInspire` class to
`tests/security/test_source_ingest.py` (NOT a new file). Four tests: off-host
rejection for each module + on-host acceptance for each module.

## Failure modes

**1. Brief says "same error type" but the two existing modules disagree.**
`ar5iv_fetch.py` returns a miss result (no raise); `oai_delta.py` raises
`RuntimeError`. The brief instruction "raise the same error type the existing
modules raise" is ambiguous. The implementer must pick one. Recommendation:
`RuntimeError` (see above). Tests in `tests/test_graph_ingest.py` that mock
`_fetch_openalex_work` may need to add a test for this error path.

**2. Guard placed outside the `with` block, causing `response.url` to be
accessed on a closed socket.** In `ar5iv_fetch.py`, the implementation reads
`response_url = response.url` inside the `with` block, then checks after the
`with` closes (lines 218–230). In `oai_delta.py`, the check is inside the
`with` block. **Both approaches work** because `.url` is populated during the
redirect handling, not by reading the socket. However, to be safe, capture
`resp.url` inside the `with` block before it closes — matching `oai_delta.py`.

**3. A fetch call site is missed.** `graph_ingest.py` has ONE fetch function:
`_fetch_openalex_work`. `inspire_ingest.py` has ONE fetch function:
`_fetch_inspire_record`. Both are clearly documented as the mock target.
However, the NOT-IMPLEMENTED `--include-back-refs` paginated path in
`inspire_ingest.py` has no HTTP call site today; if it is ever implemented,
it would need its own redirect pin. This is out of E13_S07b scope.

**4. The test mocks `response` without a `.url` attribute.** The existing
`_FakeUrlOpenResponse` helper in `test_oai_delta.py` accepts a `url=` kwarg.
The `MagicMock` pattern in `test_source_ingest.py` sets `mock_response.url`
directly. The new tests must set `mock_response.url` to an attacker URL for the
rejection test and to a valid API URL for the acceptance test. A `MagicMock`
without `.url` set will return another `MagicMock` (truthy), causing
`startswith(...)` to fail with `AttributeError` — the test would error rather
than fail cleanly.

**5. Paginated "next" URL from the response body (cursor poisoning).** The
brief notes this as a separate surface. In `graph_ingest.py`, the `referenced_works`
field contains `"https://openalex.org/W..."` URLs — these are parsed from the
response body but NEVER fetched directly; the only network call is
`_fetch_openalex_work` per paper. In `inspire_ingest.py`, references are
extracted from the body as arXiv IDs (not URLs), never fetched. The
`--include-back-refs` path (paginated `?q=refersto:...`) is NOT IMPLEMENTED.
**Conclusion: there is no cursor/next-URL fetch in either module at v1. The
redirect-host pin on the initial fetch is the only necessary guard.**
This is NOT a separate hole — the body-parsing paths use the response data
for graph construction, not for further HTTP calls.

## Open questions

**Q1: Where exactly inside `_fetch_openalex_work` to place the guard?**
The function has a retry loop. The `response.url` check should be inside the
`try: with urllib.request.urlopen(...) as resp:` block — specifically after
`resp.read(...)` and before `return json.loads(body)`. The 404 `return None`
path (HTTPError) should NOT get the redirect check because an HTTPError
response from urllib does not go through the redirect handler.

This is fully answerable from the code — no user input needed. Implementer
can proceed.

**No other open questions — implementation can proceed on the above recommendation.**

## External writes the implementation will require

| Type | Target | Why |
|---|---|---|
| `gh issue close` | `chris-dare-dev/arXMCP#2` | Closes the redirect-host validation gap filed at E13_S10 Phase-4 |
