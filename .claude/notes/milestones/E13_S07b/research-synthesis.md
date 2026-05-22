# Research Synthesis — E13_S07b

**Milestone:** E13_S07b — Add redirect-host validation to graph_ingest + inspire_ingest
**Mode:** standard (2× researcher, parallel)
**Synthesized:** 2026-05-22 (orchestrator, main session)
**Briefs merged:** research-brief-1.md, research-brief-2.md

## One-line scope

Add a post-fetch `response.url` redirect-host pin to the single HTTP call site
in each of `ingest/graph_ingest.py` (`_fetch_openalex_work`) and
`ingest/inspire_ingest.py` (`_fetch_inspire_record`), raising `RuntimeError`
on an off-host redirect — mirroring the existing `oai_delta.py` pattern.
Closes Threat 7 partial-coverage gap G2 (GitHub issue #2).

## Agreed facts (both briefs concur)

1. **Single fetch call site per module.** `graph_ingest.py` has exactly one
   HTTP fetch function, `_fetch_openalex_work` (lines ~176–229); `inspire_ingest.py`
   has exactly one, `_fetch_inspire_record` (lines ~227–301). Both use
   `with urllib.request.urlopen(request, timeout=timeout) as resp:` then
   `resp.read(...)` then `return json.loads(...)`. Neither has a `response.url`
   check today. There is **no missed second call site** — verified by both.

2. **No cursor / next-URL fetch surface.** `graph_ingest.py` parses
   `referenced_works` URLs from the response body but never fetches them
   directly. `inspire_ingest.py` extracts arXiv IDs (not URLs) from the body.
   The `--include-back-refs` paginated path is NOT IMPLEMENTED. **Conclusion:
   the redirect-host pin on the single initial fetch is the only guard needed.**
   This is not a separate hole.

3. **Use `.url`, not `.geturl()`.** `urllib.request.urlopen` follows 30x
   redirects automatically; the post-redirect URL is on `response.url`
   (populated by `HTTPRedirectHandler`). Both compliant modules
   (`ar5iv_fetch.py`, `oai_delta.py`) use `.url`. Capture
   `response_url = resp.url` INSIDE the `with` block.

4. **Raise `RuntimeError` for BOTH modules.** The brief says "raise the same
   error type the existing modules raise" — but the two compliant modules
   DISAGREE: `oai_delta.py` raises `RuntimeError`; `ar5iv_fetch.py` returns a
   miss-result (`Ar5ivResult(hit=False, reason="unexpected_redirect")`).
   **Resolution: `RuntimeError`** — `graph_ingest` and `inspire_ingest`
   propagate fetch errors via exceptions through their callers
   (`except urllib.error.URLError`), so a return-value sentinel would force
   caller refactoring. A redirect on a pipeline-critical fetch is unambiguously
   wrong and should abort the paper, not silently skip it. This also satisfies
   CLAUDE.md §4.7 (`assert` banned; use `if … raise`).

5. **Host pin constants already exist.** `OPENALEX_BASE = "https://api.openalex.org"`
   (graph_ingest.py line ~117); `INSPIRE_API_BASE = "https://inspirehep.net/api"`
   (inspire_ingest.py line ~142). Pin against these.

6. **Tests go in the EXISTING `tests/security/test_source_ingest.py`** as a new
   class (`TestRedirectHostPin` or similar) — do NOT create a new file. The file
   already exists from E13_S07 and is already cited in the coverage doc, so the
   `test_threat_model_coverage.py` staleness gate needs no citation update.
   Mirror `tests/test_oai_delta.py::TestFetchPageRedirectPin`: 4 tests —
   off-host-rejected ×2 modules + on-host-accepted ×2 modules.

7. **Upstream APIs do not legitimately redirect cross-host.** OpenAlex issues
   only SAME-HOST 301s (merged entities, `/works/W123`→`/works/W456`) — these
   pass a `startswith("https://api.openalex.org")` check. INSPIRE-HEP serves
   the apex `inspirehep.net` domain consistently, no `www.` redirect. The pin
   is safe for production ingest.

8. **No tool-schema re-pin.** Milestone touches only `ingest/` + `tests/` +
   `.claude/docs/`. `EXPECTED_TOOL_SCHEMA_SHA256` untouched. BP1 cache stable.

9. **E13_S07 is real** (not a fictional prerequisite) — it did the Threat 7
   audit; `security-threat-7-audit.md` exists with the compliance matrix
   showing both modules as `⚠️ not pinned (follow-up)`.

## Divergence resolved by orchestrator

**Trailing slash in the `startswith` prefix.**
- **Researcher-1:** pin `startswith(OPENALEX_BASE + "/")` and
  `startswith(INSPIRE_API_BASE + "/")` — mirrors `ar5iv_fetch.py`
  (`AR5IV_BASE_URL + "/"`). Closes the prefix-collision hole: a bare
  `startswith("https://api.openalex.org")` would ALSO accept
  `https://api.openalex.org.evil.com/…` (attacker registers a subdomain-shaped
  domain).
- **Researcher-2:** pin bare `startswith(OPENALEX_BASE)` /
  `startswith(INSPIRE_API_BASE)` — mirrors `oai_delta.py`.

**Orchestrator decision: use `+ "/"` (researcher-1).** The prefix-collision
attack is real — `https://api.openalex.org.evil.com/` passes a bare
`startswith` but is correctly rejected by `+ "/"` (after `api.openalex.org`
the legitimate URL always has `/`, the attacker domain has `.`). The
`oai_delta.py` bare form is a (minor, latent) weakness; the brief says "mirror
the pattern" and BOTH patterns exist in the codebase — we pick the strictly
stronger one. Concretely:
- `graph_ingest`: `if not response_url.startswith(OPENALEX_BASE + "/")`
- `inspire_ingest`: `if not response_url.startswith(INSPIRE_API_BASE + "/")`

Both legitimate URL shapes have a `/` after the pinned base:
`https://api.openalex.org/works/…?mailto=…` and
`https://inspirehep.net/api/arxiv/<id>?fields=…`. The same-host OpenAlex 301
target (`/works/W…`) also has the `/`. No false positives.

## Implementation plan (INLINE — orchestrator, main session)

Size: ~50 LOC production + ~80 LOC test + 2 doc edits. Well under the
delegated-path threshold; inline.

1. **`ingest/graph_ingest.py`** — inside `_fetch_openalex_work`'s
   `with urllib.request.urlopen(...) as resp:` block, after `resp.read(...)`,
   capture `response_url = resp.url` and after the read raise on mismatch:
   ```python
   response_url = resp.url
   ...
   if not response_url.startswith(OPENALEX_BASE + "/"):
       raise RuntimeError(
           f"OpenAlex response redirected off {OPENALEX_BASE}: "
           f"got {response_url!r}; refusing as untrusted (Threat 7)"
       )
   ```
   Do NOT add the check on the `HTTPError`/404 `return None` path — an
   `HTTPError` response does not pass through the redirect handler.

2. **`ingest/inspire_ingest.py`** — same pattern in `_fetch_inspire_record`,
   pinning `INSPIRE_API_BASE + "/"`, message
   `f"INSPIRE response redirected off {INSPIRE_API_BASE}: …"`.

3. **`tests/security/test_source_ingest.py`** — new class with 4 tests.
   Mock `urllib.request.urlopen` (patched on the module under test) to return a
   fake context-manager response. **Failure mode #4 guard:** the fake MUST set
   an explicit `.url` attribute — a bare `MagicMock` returns a truthy mock for
   `.url`, and `.startswith` on a mock raises `AttributeError` (test errors
   instead of failing cleanly). Define a small local `_FakeResponse` stub (or
   reuse the `test_source_ingest.py` existing mock helper if one is present) with
   `.url`, `.read()`, `.headers`, `.status`, and `__enter__/__exit__`.
   Tests: off-host URL → `pytest.raises(RuntimeError, match="redirected off")`;
   on-host URL → fetch returns the parsed JSON unchanged.

4. **`.claude/docs/security-threat-7-audit.md`** — flip both module rows in the
   compliance matrix from `⚠️ not pinned (follow-up)` to `✅` with an E13_S07b
   attribution; update the Known gaps section to mark the gap closed.

5. **`.claude/docs/security-threat-model-coverage.md`** — Threat 7 row Gaps
   cell: remove the `#2` issue link, replace with `(none — closed by E13_S07b)`;
   Gap-issue triage table row G2 marked closed (strikethrough, like G1/E13_S04b).

6. **Verify:** `pytest tests/security/test_source_ingest.py tests/test_graph_ingest.py
   tests/test_inspire_ingest.py tests/security/test_threat_model_coverage.py`
   all green; `ruff check .` clean; full `pytest` no new failures.

## Open questions

None. Both researchers independently concluded the implementation can proceed.
The only judgment call (trailing slash) is resolved above.

## External writes required (deduped union)

| Type | Target | Why | Blocking |
|---|---|---|---|
| `git push` | `main` @ `github.com/chris-dare-dev/arXMCP` | Land the feat+rect+chore commits | YES — per-event user authorization |
| `gh issue close` | `chris-dare-dev/arXMCP#2` | Close the gap-issue once the pin lands | YES — Phase 4 boundary |

## Orchestrator synthesis note

The two briefs agreed on every load-bearing fact (single call site, `.url`,
`RuntimeError`, no cursor hole, host constants, test-file placement). The sole
divergence was the trailing-slash in the `startswith` prefix; resolved in
favor of researcher-1's `+ "/"` form on security grounds (closes the
`api.openalex.org.evil.com` prefix-collision vector) — this is strictly
stronger than the `oai_delta.py` bare form and matches the `ar5iv_fetch.py`
precedent. Researcher-2's failure-mode #4 (MagicMock without `.url` →
`AttributeError`) is folded into the test plan as an explicit guard.
