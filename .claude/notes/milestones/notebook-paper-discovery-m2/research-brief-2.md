# Research Brief — notebook-paper-discovery-m2

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-31T17:15:00Z

---

## In-codebase context

**Design constitution files that apply:**

- `01-mission-and-context.md` — "power tool, not autopilot"; discovery is deterministic,
  LLM-free. "No `anthropic` SDK at runtime" (CLAUDE.md §4.7). This is a pure library
  extraction — no new runtime surface, no MCP tool.
- `07-multi-agent-caching.md` — load-bearing for the "no new MCP tool" gate: "An
  agent-facing `discover_papers` MCP tool is a deferred v2 (it forces a BP1 cold-start
  cache bust that must be batched with other tool additions)". `EXPECTED_TOOL_SCHEMA_SHA256`
  MUST NOT change in m2.
- `08-security-observability-ops.md` — Threat 7: "fetches from arxiv.org… If either is
  compromised, we ingest poisoned content." Mitigations include TLS cert verification
  (already enabled), content-length sanity checks, and sandbox. For the Atom channel
  (metadata-only, no LaTeXML invocation), the applicable mitigations are TLS + content-
  length cap + XML parse safety.
- `.claude/notes/notebook-discovery-model.md` §1 — `discovery_category` is a fixed enum
  (`math.AG`, `math.NT`, `math-ph`, `hep-th`) that flows directly into `cat:` in the query.
  `description` is free text, `max_length=512`, control chars stripped before storage.
  These are the keyword sources for `abs:`/`ti:` clauses.

**Existing parse path (source of truth):**

`tools/curate_seed.py:35`: `import xml.etree.ElementTree as ET` — the current Atom feed
parser uses stdlib `xml.etree`, NOT `defusedxml`.

**`defusedxml` is already a project dependency** (`pyproject.toml:139-146`):
```
# defusedxml: XXE/billion-laughs-safe replacement for
#   ``xml.etree.ElementTree`` (E10_S03). Used by
#   ``server.retrieval.equations`` to parse MathML from caller input
#   to the find_equation handler.
"defusedxml>=0.7",
```

`server/retrieval/equations.py` uses `import defusedxml.ElementTree as DET` with
`DET.fromstring(mathml)`. The arXiv Atom parse in `curate_seed.py` is the ONLY remaining
stdlib `xml.etree` consumer that handles untrusted external data. **This is an inconsistency
the implementer should fix: migrate `parse_atom_feed` to `defusedxml.ElementTree` in
`tools/_arxiv_api.py`.**

**`POLITENESS_SLEEP_SECONDS = 3.0`** is defined in `tools/arxiv_fetch.py:35`. The injectable
`sleep=time.sleep` contract in the AC must default to a call that waits at least this long.
The canonical default should import and use this constant as the interval — not hard-code 3.

**`tools/_notebook_common.py` pattern** (per the milestone brief) — the implementation should
mirror this pattern for the new `tools/_arxiv_api.py`. The leading underscore signals an
internal helper, not a user-facing CLI.

**No `assert` for invariants** (CLAUDE.md §4.7). Query builder validation (bad category,
keyword too long) must use `if … raise ValueError(…)`, not `assert`.

**`tools/` is a registered package** (`pyproject.toml:16`: `packages = ["server", "ingest",
"tools", "shim"]`). `tools/_arxiv_api.py` is auto-discoverable with no setup change.

**Existing test coverage:** `tests/test_fetch_seed.py` imports `build_query_url`,
`parse_atom_feed`, `filter_candidates` directly from `tools.curate_seed`. After rewiring,
these imports must continue to resolve (either re-exported from `curate_seed.py` or the
test file updated). The AC says "its existing tests pass unchanged" — so the implementer
must re-export or keep the names importable from `curate_seed`.

---

## Prior decisions and lessons

**Recent git log (from status context):** last milestone landed was `ui-attractive-polish-m3`
(e69de9c). The notebook-paper-discovery-m1 state is `research-running` (just started).

**Discovery model decisions locked in `notebook-discovery-model.md` §2:**
- "Deterministic ingest job, not an LLM-in-the-loop crawl."
- "No new MCP tool in v1." — `EXPECTED_TOOL_SCHEMA_SHA256` must not change.
- "Propose → confirm, never auto-ingest (v1)."

**Security pattern from E10_S03:** when parsing untrusted external XML in this codebase,
use `defusedxml.ElementTree`, not `xml.etree.ElementTree`. The arXiv API response is
external-origin data. This is the established pattern to follow.

**Politeness contract (E01):** `POLITENESS_SLEEP_SECONDS = 3.0` in `arxiv_fetch.py` is the
canonical constant. The injectable `sleep` argument is a testability pattern enabling mocks
— but the default must preserve the 3s interval, referenced by name not value.

---

## External sources

### arXiv API — query grammar (from info.arxiv.org/help/api/user-manual.html)

**Field prefixes:** `ti:` (title), `au:` (author), `abs:` (abstract), `cat:` (category),
`co:` (comment), `jr:` (journal ref), `all:` (all fields simultaneously).

**Boolean operators:** `AND`, `OR`, `ANDNOT`. Parentheses group: encoded as `%28`/`%29`.

**Multi-word phrases:** use double quotes encoded as `%22`, spaces as `+`. Example:
`abs:%22quantum+criticality%22`.

**Pagination:** `start` (0-indexed offset) + `max_results`. Per-request cap: **2,000**.
Total-query cap: **30,000**. Pagination loop must respect both.

**Sort:** `sortBy=submittedDate&sortOrder=descending` (mirrors existing `curate_seed.py`
default; keep this default in `_arxiv_api.py`).

**Rate limit:** "we encourage you to play nice and incorporate a **3 second delay** in your
code." This aligns with `POLITENESS_SLEEP_SECONDS = 3.0`.

**Atom feed structure:**
- Feed-level: `<opensearch:totalResults>`, `<opensearch:startIndex>`,
  `<opensearch:itemsPerPage>`
- Per-entry: `<title>`, `<id>`, `<summary>`, `<published>`, `<updated>`, `<author>`,
  `<category>`, `<arxiv:primary_category>`

**No-match behavior:** HTTP 200 with an empty entry list (not an error status). An API
error (malformed query, server fault) appears as a single-entry feed with an error
`<summary>` — NOT a 4xx/5xx response. The parser must detect this "error entry" pattern.

---

## Failure-mode analysis

### FM-1: XXE / billion-laughs attack via hostile Atom XML

**Trigger:** arXiv API is MITM'd or returns a crafted response with external entity
declarations or deeply nested entity expansions (`&a;&a;&a;…` exponentially expanding).

**Observable symptom:** `xml.etree.ElementTree.fromstring()` is NOT safe against XXE in
Python's stdlib — it expands external entities by default on some Python/platform combos,
and is vulnerable to billion-laughs exponential expansion.

**Mitigation:** Use `defusedxml.ElementTree.fromstring()` (already a project dep, used by
`server/retrieval/equations.py`). This blocks both XXE and entity expansion attacks. This
is the **strongest reason** to use `defusedxml` in the new `_arxiv_api.py`, not the stdlib
import from `curate_seed.py`. **The implementer MUST migrate to `defusedxml` here.**

### FM-2: Pagination infinite loop / runaway

**Trigger:** `opensearch:totalResults` is missing or returns a larger value than actual
entries; the API keeps returning results at the final page; implementation logic has an
off-by-one on the stop condition.

**Observable symptom:** `fetch_candidates` never terminates; the caller blocks indefinitely.

**Mitigation:** Three independent guards:
1. Hard cap: never request `start >= 30000` (the API's documented total cap).
2. Page-count cap: if the number of pages fetched exceeds `ceil(max_total / max_results) + 1`,
   raise `RuntimeError`, not a silent loop exit.
3. Empty-page termination: if a response returns 0 entries, stop — even if `totalResults`
   says more should exist. This is the only reliable convergence guarantee.

### FM-3: Query-syntax injection via operator-supplied keywords

**Trigger:** `description` (from `notebooks` table, operator-supplied) is used directly as
`abs:`/`ti:` keyword text. A notebook description of `"stability AND abs:evil"` would
produce a malformed or logic-bypassing query.

**Observable symptom:** The assembled `search_query` has injected boolean operators or
field prefixes, potentially leaking hits from unintended categories or categories the
operator hasn't selected.

**Mitigation:**
- URL-encode all keyword values via `urllib.parse.quote_plus()` before interpolation.
- Multi-word phrases should be wrapped in double-quotes (`%22…%22`) to prevent
  accidental boolean parsing.
- Strip or reject keywords containing `:` characters (they'd introduce unintended field
  prefixes). Since `description` is already capped at 512 chars and has control chars
  stripped (`notebook-discovery-model.md §1`), the remaining risk is operator intentional
  injection — which is acceptable (single-user tool, operator is the threat model boundary).
  URL-encoding alone closes the accidental case.

### FM-4: Politeness violation — 503 / IP block on pagination

**Trigger:** Multi-page pagination that does NOT sleep between pages sends N requests
in rapid succession. arXiv rate-limits and may return 503.

**Observable symptom:** HTTP 503 response mid-pagination; subsequent requests blocked.

**Mitigation:** The injectable `sleep=time.sleep` with default `POLITENESS_SLEEP_SECONDS`
MUST be invoked BETWEEN pages, not only after the final page. The existing `curate_seed.py`
sleeps after a single fetch — the new `_arxiv_api.py` paginator must call `sleep(3.0)`
after every page including intermediate ones. A `Retry-After` header on 503 responses
should be honored using the existing `parse_retry_after()` helper in `arxiv_fetch.py`.

### FM-5: Oversized or zero-result response

**Trigger:** A valid category with no recent papers returns 0 results; a query matching
30,000+ papers returns a massive paginated response.

**Observable symptom for zero results:** The loop terminates with an empty list — correct,
but a caller that expects at least 1 result might fail silently.

**Observable symptom for oversized:** `max_total` pages are consumed but all 30,000 entries
are returned, hitting the API cap silently with no signal that results were truncated.

**Mitigation:**
- Zero results: correct behavior; callers handle empty lists.
- Oversized: when `totalResults > 30000`, log a WARNING but continue (don't crash); the
  30,000 cap is an API constraint, not a library error.
- Per-fetch content-length cap: add a byte cap on the raw Atom response (consistent with
  `MAX_RESPONSE_BYTES = 100 * 1024 * 1024` in `arxiv_fetch.py`) to defend against a
  single malformed response inflating the process.

### FM-6: arXiv API "error entry" masquerading as a valid result

**Trigger:** Malformed query URL (e.g., bad boolean syntax) causes the API to return HTTP
200 with a single entry whose `<summary>` contains an error description
("incorrect id format for ...").

**Observable symptom:** `parse_atom_feed` returns one entry that looks like a paper but has
an `<id>` matching `http://arxiv.org/api/errors#...` or a summary starting with "Error".

**Mitigation:** The parser should detect and raise on entries whose `<id>` contains
`/api/errors#`. This is a known arXiv API error pattern documented in the API manual.
Raising `RuntimeError` with the error summary text allows callers to surface the issue.

---

## Recommendation

**Implement `tools/_arxiv_api.py` using `defusedxml.ElementTree` (not stdlib `xml.etree`)
for `parse_atom_feed()`, with injectable `sleep=time.sleep` defaulting to
`POLITENESS_SLEEP_SECONDS`, and a three-guard pagination terminator (hard 30000 cap +
empty-page stop + page-count ceiling).**

Reasoning: `defusedxml` is already a project dependency with an established usage pattern
in `server/retrieval/equations.py`. Using it for the Atom parser is the **correct** choice
per Threat 7 in `08-security-observability-ops.md` (external-origin untrusted content) and
eliminates an inconsistency where the only remaining stdlib ET consumer handles external
data. URL-encode all keyword values via `urllib.parse.quote_plus()` to close FM-3. Keep
`build_query_url`, `parse_atom_feed`, and `filter_candidates` re-exported from
`curate_seed.py` to keep existing test imports passing without changes.

**Banned pattern check:**
- No `assert` anywhere in `_arxiv_api.py` — use `if … raise`.
- No `anthropic` SDK import.
- No new MCP tool registration — `EXPECTED_TOOL_SCHEMA_SHA256` unchanged.
- No new Markdown file outside `.claude/`.
- No `BaseHTTPMiddleware`.
- `KMP_DUPLICATE_LIB_OK=TRUE` in `tests/conftest.py` untouched (no model loading here).

---

## Open questions

1. **`parse_atom_feed` type hint generalization:** The current signature returns
   `list[Candidate]` where `Candidate` is defined in `curate_seed.py`. Moving parsing
   to `_arxiv_api.py` requires either (a) moving `Candidate` to `_arxiv_api.py` and
   importing it into `curate_seed.py`, or (b) returning a more generic `list[dict]` from
   `_arxiv_api.py` and constructing `Candidate` in `curate_seed.py`. **Recommendation:**
   move `Candidate` to `_arxiv_api.py` — it's a parse-output type, not a curate-seed
   concern. This requires updating the existing test import
   `from tools.curate_seed import Candidate` — which contradicts the AC "existing tests
   pass unchanged." **The implementer must decide: update the test import (cleanest), or
   re-export `Candidate` from `curate_seed.py` (preserves AC literally).** This is the
   only true open question; the implementer should re-export to preserve AC literally.

No other open questions — implementation can proceed on the above recommendation once the
re-export decision for `Candidate` is confirmed.

---

## External writes the implementation will require

None — this milestone is purely local. No git push, no PR, no ticket, no infra mutation.
The implementation lands via the standard three-commit pattern on `main`.
