---
milestone_id: "source-truth-m1"
researcher_role: "general"
date: "2026-07-13"
slice: "OAI-PMH license-client design, license-decision semantics, external-writes enumeration, risk/alternative"
external_writes_required: ["git push origin main"]
sources:
  - url: "https://oaipmh.arxiv.org/oai?verb=GetRecord&identifier=oai:arXiv.org:2006.10956&metadataPrefix=arXiv"
    takeaway: "New-style/versioned paper (spike-1's raw_oai.xml, re-read and re-verified this session, not re-fetched): <license> PRESENT = http://arxiv.org/licenses/nonexclusive-distrib/1.0/. Response self-reports its own base URL as http://oaipmh.arxiv.org/oai even though spike-1 requested export.arxiv.org/oai2."
  - url: "https://oaipmh.arxiv.org/oai?verb=GetRecord&identifier=oai:arXiv.org:math/0212237&metadataPrefix=arXiv"
    takeaway: "Old-style paper (live this session, HTTP 200, 2468 bytes): identifier format oai:arXiv.org:<archive>/<number> resolves cleanly, correct record returned (Bridgeland's own stability-conditions paper). <license> element ABSENT."
  - url: "https://oaipmh.arxiv.org/oai?verb=GetRecord&identifier=oai:arXiv.org:alg-geom/9410026&metadataPrefix=arXiv"
    takeaway: "Second old-style paper, different archive prefix (live this session, HTTP 200, 1627 bytes): same format success, same <license> ABSENT outcome -- confirms this is not a one-off."
  - url: "https://oaipmh.arxiv.org/oai?verb=GetRecord&identifier=oai:arXiv.org:math/0212237&metadataPrefix=arXivRaw"
    takeaway: "Cross-check (live this session, HTTP 200, 2797 bytes): the richer arXivRaw format for the SAME old-style paper also has no <license> element (has <version> history instead) -- proves the gap is arXiv-side data absence, not a metadataPrefix artifact."
injection_attempts: 0
---

# source-truth-m1 research brief 2 -- OAI-PMH license client, license semantics, external writes, risk

Scope: the OAI-PMH license-client design (the load-bearing pivot away from spike-1's falsified
Atom-client assumption), the `nonexclusive-distrib` license-decision question, the
external-writes enumeration, and the sharpest risk + alternative. Registry-schema and
backfill-CLI/coverage-report *implementation* details are out of this slice.

Grounded in: `CLAUDE.md` (§4.4 push policy, §4.7 conventions, §4.8 data-plane boundary),
`.claude/notes/milestones/source-truth-spike-1/spike-note.md` (full), `tools/_arxiv_api.py`,
`tools/arxiv_fetch.py`, `ingest/identifiers.py`, `.claude/roadmap-briefs/R1-source-truth.md`,
`server/license_policy.py`, and -- critically -- **`ingest/oai_delta.py`**, a fully-built,
critique-hardened OAI-PMH client already shipped in this repo (E11_S02), which this brief
found by chasing a docstring cross-reference in `tools/arxiv_fetch.py` and which changes the
shape of the recommended design substantially (see below). Plus 3 live, bounded OAI-PMH GETs
this session and one re-verified cached response from spike-1 (4 total XML responses read in
full; all screened for injection content per the untrusted-content policy -- none found).

## External sources -- old-style / new-style / versioned findings

| id | shape | metadataPrefix | fetched | HTTP | `<license>` present? |
|---|---|---|---|---|---|
| `2006.10956` | new-style, versioned in notebook (`2006.10956v1`) | `arXiv` | spike-1 (cached, re-verified this session) | 200 | **YES** -- `http://arxiv.org/licenses/nonexclusive-distrib/1.0/` |
| `math/0212237` | old-style | `arXiv` | live, this session | 200 | **NO** -- element absent |
| `alg-geom/9410026` | old-style, different archive prefix | `arXiv` | live, this session | 200 | **NO** -- element absent |
| `math/0212237` | old-style (cross-check) | `arXivRaw` | live, this session | 200 | **NO** -- element absent (has `<version>` history instead) |

**Identifier format for old-style ids -- RESOLVED.** `oai:arXiv.org:math/0212237` and
`oai:arXiv.org:alg-geom/9410026` (archive prefix retained, literal unescaped `/`, no percent-
encoding needed in the query string) both resolved on the first try: HTTP 200, correct
`<record>` with matching title/author (`math/0212237` -> Bridgeland, "Stability conditions on
triangulated categories"; `alg-geom/9410026` -> Zube, "Exceptional vector bundle on Enriques
surfaces"), no `idDoesNotExist` error. Spike-1's open caveat about the *format* is closed: the
archive prefix stays, joined to `oai:arXiv.org:` exactly like the new-style case, for both of
the two archive-prefix families sampled (`math/`, `alg-geom/`).

**License presence for old-style ids -- NOT resolved, and the news is worse than "format
differs."** Both old-style samples (original submissions 2002 and 1994; last metadata touch
2006 and 2009 respectively, per each record's own `<header><datestamp>`) have **no `<license>`
element at all**, under both the `arXiv` and (cross-checked once) `arXivRaw` metadata formats.
This is a genuine absence in arXiv's own stored metadata for these records -- not a client bug,
not a metadataPrefix choice, not an artifact of which OAI-PMH host was queried. Contrast: the
one new-style paper tested (2020 submission) has a real license URI. This is consistent with
arXiv having rolled out explicit per-paper license URIs well after these old-style papers'
original submission and never backfilling it for records nobody has since touched -- but that
mechanism is inferred, not verified; n=2 is enough to prove the failure mode is real and not a
fluke (2/2, two different archive families), not enough to state a rate. See Risk 1.

**Canonical endpoint -- also resolved, and it isn't the one this brief's Step 2 named.** The
brief's literal text pointed at `https://export.arxiv.org/oai2`. Spike-1 issued its GetRecord
request to exactly that URL and it worked -- but the response's own `<request
verb="GetRecord" ...>http://oaipmh.arxiv.org/oai</request>` element (present verbatim in
`raw_oai.xml`) shows arXiv itself reports the base URL that actually served the request as
`http://oaipmh.arxiv.org/oai`, not `export.arxiv.org/oai2`. This matches `ingest/oai_delta.py`'s
already-in-production `OAI_PMH_ENDPOINT = "https://oaipmh.arxiv.org/oai"` (its docstring: "arXiv
migrated from `http://export.arxiv.org/oai2` to `https://oaipmh.arxiv.org/oai` in March 2025.
The legacy URL still works but is HTTP-only"). All 3 of this session's live requests targeted
`https://oaipmh.arxiv.org/oai` directly and all succeeded. **Recommend the new client target
this same canonical host**, not the legacy alias -- one arXiv-OAI-PMH-down incident path,
consistent with the module that already talks to it in production.

## OAI-PMH license client design

**There is already a fully-built, critique-hardened OAI-PMH client in this repo:
`ingest/oai_delta.py` (E11_S02, the nightly delta harvester).** It does not fetch license (it
uses `ListRecords`/`metadataPrefix=arXivRaw` for incremental discovery, not per-paper lookup),
but it already solves -- and has already been adversary-critiqued on -- almost every mechanical
problem this design needs: the endpoint, the 503/politeness contract, and redirect-pinning. The
design below treats it as load-bearing prior art, not a green field.

**Request shape.**
```
GET https://oaipmh.arxiv.org/oai?verb=GetRecord&identifier=oai:arXiv.org:<bare_id>&metadataPrefix=arXiv
```
- `<bare_id>` must be the **unversioned** id (old-style keeps its archive-prefix slash). Strip
  any `vN` suffix first -- reuse `tools._arxiv_api.strip_id_version()` (already exists, already
  handles both id shapes) rather than writing a new stripper. Both this session's and spike-1's
  working requests only ever used bare ids; OAI-PMH identifiers conventionally name the *work*,
  not a version snapshot, so a versioned identifier is not expected to resolve (untested here,
  not recommended).
- Validate the id with `ingest.identifiers.ARXIV_PAPER_ID_RE` / `is_valid_arxiv_paper_id` before
  building the URL -- the same discipline `build_id_list_url` already applies for the Atom
  id_list endpoint (one malformed id there poisons a whole batch response; here it would just
  waste one request, but pre-validation is still cheap and consistent).
- `/` and `:` in the identifier value need no percent-encoding in the query string (verified
  live against real requests both here and via spike-1); mirror `_arxiv_api.py::
  build_id_list_url`'s `urlencode(params, safe=",/")` convention if building the URL via
  `urlencode`.

**Parsing.** New namespace pair, distinct from `oai_delta.py`'s `arXivRaw` namespace:
`{"oai": "http://www.openarchives.org/OAI/2.0/", "arxiv": "http://arxiv.org/OAI/arXiv/"}`.
Verified live structure: `OAI-PMH > GetRecord > record > header > {identifier, datestamp,
setSpec*}` and `... > metadata > arXiv > {id, created, updated?, authors, title, categories,
comments?, license?, abstract}`. `<license>`, when present, is one dereferenceable-URI text
node with no attributes.
- **Parse `<license>` as optional.** A missing element is an expected, first-class outcome
  (see External sources above) -- not a parse error and not "malformed response."
- **`<header status="deleted">` rides along for free.** This is the same OAI-PMH deletion
  signal `ingest/oai_delta.py` already parses for withdrawn-record handling, and it is present
  on `GetRecord` responses too (header schema is verb-independent). One `GetRecord` fetch can
  therefore hydrate *both* the documents registry's license URI *and* its active/withdrawn
  status field in a single round-trip -- surface both from the same parse rather than fetching
  twice or leaving withdrawal detection to a separate mechanism.
- **Handle `idDoesNotExist` as a per-paper, non-fatal outcome.** OAI-PMH signals an unknown
  identifier as `<error code="idDoesNotExist">` in place of `<GetRecord>` (not an HTTP error).
  Mirror `ingest/oai_delta.py::harvest_set`'s existing philosophy (a bad record should not
  abort a multi-paper run): record `license_status=unknown` for that one paper and continue the
  backfill loop.
- **Use `defusedxml.ElementTree`**, matching `tools/_arxiv_api.py`'s existing pattern for
  untrusted-response parsing (XXE/entity-expansion safe) -- see Risk 5: don't copy
  `ingest/oai_delta.py`'s plain-`xml.etree.ElementTree` choice into the new client.

**Politeness / rate limits -- mirror `ingest/oai_delta.py::_fetch_page`, don't re-derive.**
This exact problem (arXiv OAI-PMH 503 + `Retry-After` behavior) was already solved and
adversary-critiqued in this repo (E11_S02 findings F1/F2). Reuse its shape and constants:
- `POLITENESS_SLEEP_SECONDS = 3.0` between requests (matches `tools.arxiv_fetch.
  POLITENESS_SLEEP_SECONDS`, the project-wide arXiv politeness contract).
- On HTTP 503: honor a `Retry-After` header (seconds form) if present; otherwise exponential
  backoff starting at 30s, doubling each retry, capped at 600s per wait; overall retry budget
  capped at 3600s (1 hour) before giving up with a clear error.
- Redirect-pinning: after a successful read, verify the response's resolved URL still starts
  with the configured endpoint -- guards against a poisoned redirect being trusted as OAI-PMH
  XML (same mitigation as `ingest/ar5iv_fetch.py` and `ingest/oai_delta.py::_fetch_page`).
- A Content-Length + read-cap sanity check against a generous byte ceiling (defense-in-depth;
  a single `GetRecord` response is a few KB, so this never legitimately fires here).
- **Open implementation choice, not resolved here:** literally reuse `ingest.oai_delta.
  _fetch_page` (it is verb-agnostic -- takes an `endpoint` + a `params` dict, so
  `{"verb": "GetRecord", "identifier": ..., "metadataPrefix": "arXiv"}` fits its existing
  signature unchanged) vs. re-mirror the same logic into a new `tools/`-side module per this
  brief's literal instruction to follow `_arxiv_api.py`'s pattern. Both are legitimate:
  `tools/_arxiv_api.py` already imports across the tools/ -> ingest/ boundary
  (`ingest.identifiers.ARXIV_PAPER_ID_RE`), so reuse isn't a layering violation -- but
  `_fetch_page` is underscore-private by convention, so importing it is a minor smell the
  implementer should weigh against duplicating 60-odd lines of already-critiqued retry logic.

**Fetch shape: `GetRecord` vs `ListRecords` -- recommend `GetRecord`.**
- Both live notebooks together have **194 bare paper ids** (142 bridgeland-stability + 52
  fourier-duality; counted directly from `papers.txt` this session, matching spike-1's
  independently-counted 142 for bridgeland-stability exactly). 25 of 194 (12.9%) are old-style:
  15 of 142 (10.6%) on bridgeland-stability, 10 of 52 (19.2%) on fourier-duality. (This task's
  own "~142 + ~53 ~= ~200" estimate was close; 194 is the exact count.)
- **`GetRecord` cost:** 194 requests x ~3s enforced politeness gap ~= 9.7 minutes of sleep, plus
  real request latency (this session's 3 live `GetRecord` round-trips each completed in well
  under a second). **~10-13 minutes wall-clock for one full backfill of both notebooks.** This
  is a one-shot, personal-use CLI run, not a recurring job -- that cost is unremarkable, not a
  blocker.
- **`ListRecords` shape mismatch:** `ListRecords` is a *discovery* primitive ("give me
  everything new/changed in this set + date window") -- exactly why `ingest/oai_delta.py` (the
  incremental *delta* harvester) uses it. m1's actual need is the opposite shape: hydrate
  license data for an already-known, finite, ~200-id list spanning the full 1994-2026 range and
  several primary categories (math.AG, math.CT, math.GR, hep-th, math-ph all appear in the
  sample). A `ListRecords` approach would have to either harvest entire categories across 30+
  years (vastly more data than needed, then discard almost all of it) or already know each
  paper's submission date precisely enough to build minimal per-paper windows -- at which point
  per-paper `GetRecord` is simpler and no more expensive.
- **Recommendation: `GetRecord`, one request per version-stripped paper_id, looped with the
  `ingest/oai_delta.py`-mirrored politeness/backoff.** Revisit only if a future milestone needs
  a full-corpus (not two-notebook) backfill, where `ListRecords`' bulk-discovery shape would
  start to pay off.

## License-decision semantics -- the `nonexclusive-distrib` question

Every non-empty license value observed so far (n=1 live-verified, `2006.10956`) is exactly
`http://arxiv.org/licenses/nonexclusive-distrib/1.0/` -- arXiv's own default "perpetual,
non-exclusive license to distribute," granted automatically unless the author opts into a
Creative Commons alternative at submission. **This is not a Creative Commons license**, and it
does **not** match anything in `server/license_policy.py`'s current `OA_ALLOWLIST`
(`{arxiv-license, CC-BY, CC-BY-SA, CC0, public-domain, GFDL}`). Note that `arxiv-license`
there is a *synthetic blanket token* the corpus currently stamps on every arXiv chunk
regardless of its real per-paper license -- precisely the defect R1's roadmap brief names for
retirement ("the blanket `arxiv-license` token is eliminated from new writes and backfilled").

**Consequence: under a literal "match the real URI against the existing CC-only allowlist"
reading, `nonexclusive-distrib` matches nothing and would resolve to non-open-access.** Because
this is arXiv's historical default (predating the CC options, and still the fallback today for
any author who doesn't actively choose otherwise), it is very likely the single most common
per-paper license value across a corpus spanning 1994-2026 -- but I have not run a census
across either notebook, and the exact rate is precisely what m1's own coverage report should
measure, not something this research brief should assert a number for (per CLAUDE.md §4.9,
novelty/prevalence claims need a dated, scoped count, not an inference from n=1).

**This is explicitly named as unresolved by the roadmap brief itself** ("arXiv-perpetual vs CC
variants," `R1-source-truth.md` line 20) -- not settled by it. Per this task's own framing, the
mapping is an **owner / trustworthy-release-D8-R04 decision**, and m1 must not silently
pre-empt it in either direction:
- Defaulting `nonexclusive-distrib` -> `eligible` risks shipping a compliance decision nobody
  actually made.
- Defaulting it -> `unknown` conflates "we have no data" with "we have real data but haven't
  decided what it means," which corrupts the coverage report's own >20%-owner-escalation
  signal -- a report reading "73% unknown" could mean either "we couldn't fetch 73% of
  licenses" or "we fetched 73% fine, they're just not CC-allowlisted," and those demand
  completely different owner responses.

**Recommendation: a third `license_status` value**, distinct from `eligible` and `unknown`, for
"a real, recognized, dereferenceable license URI was recovered, but it is not currently
allowlisted as open" (exact string is the implementer's / D8-R04's call -- the three-way split
is the point, not the name). This keeps m1 fully advisory -- `server/license_policy.py::
is_open_access()` and its `arxiv-license` token stay untouched, serving is unchanged, per scope
-- while keeping the coverage report legible: `unknown` = genuine data gaps (Risk 1 below),
third-bucket = eligibility-pending-policy-decision, `eligible` = already-decided-permissive.
The >20% threshold reads most cleanly against `unknown` alone (the data-completeness question
spike-1's threshold was actually about); the third bucket's count should be reported alongside,
equally prominently -- if it is large, "most papers truncate at the m4 cutover" is the real
headline, not a footnote to the unknown-rate number.

One structural note for whichever slice owns the decision-fn/registry design: `is_open_access()`
takes a bare token (`"CC-BY"`), not a URI. The eventual mapping needs a URI -> status layer in
front of (or replacing) today's token-allowlist check; designing that mapping itself is out of
this slice and arguably out of m1's advisory scope, but the shape mismatch should be accounted
for wherever `license_ref`/the decision function is actually designed.

## External writes

m1's writes, per this slice's design, are all local: (1) new client / decision-fn / backfill-CLI
/ coverage-report code as repo files; (2) a per-notebook SQLite registry under
`var/arxmcp/notebooks/<slug>/...`, extending the `paper-metadata-m1` / `server/
paper_metadata_store.py` placement precedent; (3) a coverage report (file or stdout). All three
match CLAUDE.md §4.8 Rule 2 ("writes enter only via offline ingest CLIs or operator-gated `/ui/`
console actions"). The OAI-PMH `GetRecord` calls are read-only, politeness-contracted GETs
against `oaipmh.arxiv.org` -- hydration reads, not external writes; no arXiv submission or other
mutating API is touched anywhere in this design. No `/ui/` console action, no deploy, no
publish, no other network egress beyond arXiv OAI-PMH is in scope. The only external write in
m1's scope is the milestone's eventual `git push origin main`, which per §4.4 requires fresh,
per-event owner authorization at milestone exit -- nothing in this research phase implies or
grants that.

```
external_writes_required: ["git push origin main"]
```

## Risks and open questions (<=5)

1. **OAI-PMH does not reach near-100% license coverage even after fixing the endpoint.**
   Live-verified: 2 of 2 sampled old-style ids have no `<license>` element at all, under both
   `arXiv` and `arXivRaw` metadata formats. This is a genuine gap in arXiv's own metadata for
   these records, not a client bug. It is the corrected, resolved form of spike-1's caveat: the
   identifier *format* resolves cleanly for old-style ids, but license *presence* does not.
   bridgeland-stability's 15 old-style ids (10.6% of 142) and fourier-duality's 10 (19.2% of 52)
   are now confirmed at real, non-hypothetical risk of `license_status=unknown` -- the true rate
   is unmeasured beyond n=2 and is exactly what m1's backfill + coverage report must establish.
2. **The `nonexclusive-distrib` mapping is undecided and swings the coverage numbers hugely**
   (see License-decision semantics above) -- recommend the 3-way `license_status` split so m1
   stays advisory without hiding the scale of the pending decision from the coverage report.
3. **`GetRecord` returns the record's current/latest metadata state, not a per-version
   snapshot.** `arXivRaw`'s `<version>` sub-elements carry per-version `<date>`/`<size>`, but
   this brief did not verify (and found no evidence either way) whether license can legitimately
   differ by version for one work. If the documents registry keys license by `(work_id,
   arxiv_version)`, m1 may need "the current record's license applies to all versions of that
   work" as a documented simplifying assumption, unless a future check finds otherwise.
4. **Rate-limit risk is low but not exhaustively verified.** The 3s/request + `Retry-After`/
   backoff contract is well-established (mirrors `ingest/oai_delta.py`'s already-critiqued
   behavior), and a ~194-request, ~11-minute one-time run is unremarkable next to the existing
   nightly delta loop's traffic. This brief found no evidence of an additional per-day/per-IP
   cap beyond the documented 503 behavior, and did not test for one -- deliberately triggering a
   rate-limit ban was out of scope for a bounded, polite research probe.
5. **Minor existing-code inconsistency, not this slice's to fix:** `ingest/oai_delta.py` parses
   untrusted arXiv OAI-PMH XML with plain `xml.etree.ElementTree`, not `defusedxml`. The new
   license client should use `defusedxml` (per this brief's instruction and `tools/
   _arxiv_api.py`'s convention) and should treat `oai_delta.py` as the pattern to copy for
   retry/backoff/redirect-pinning only, not for its XML-parsing import choice.

## Acceptance criteria the implementer must meet (<=7)

1. **[roadmap AC1]** The OAI-PMH license client issues `GET
   https://oaipmh.arxiv.org/oai?verb=GetRecord&identifier=oai:arXiv.org:<bare_id>&
   metadataPrefix=arXiv` (canonical host, not the legacy `export.arxiv.org/oai2` alias), with
   `<bare_id>` produced by stripping any version suffix via `strip_id_version()` first, for both
   old-style (archive-prefixed) and new-style ids.
2. **[roadmap AC1]** The client parses `<license>` as OPTIONAL (a missing element is a valid,
   expected outcome, not a parse error) and separately surfaces `<header status="deleted">` so
   one fetch populates both the documents row's license URI and its active/withdrawn status.
3. **[roadmap AC1]** XML parsing uses `defusedxml.ElementTree`; the 503/`Retry-After`/backoff/
   redirect-pinning behavior mirrors (or directly reuses) `ingest/oai_delta.py::_fetch_page`'s
   existing, already-critiqued constants rather than re-deriving new ones.
4. **[roadmap AC1]** The backfill CLI drives the client via per-paper `GetRecord` (not
   `ListRecords`) over the full 194-id union of both notebooks' `papers.txt`, honoring the 3s
   politeness gap between requests, and handles `idDoesNotExist` as a per-paper non-fatal
   outcome that does not abort the run.
5. **[roadmap AC2]** The per-revision decision function maps a missing/absent license to
   `license_status=unknown`, and represents a real-but-non-CC-allowlisted URI (starting with
   `nonexclusive-distrib`) as a status distinct from both `unknown` and `eligible` -- not
   silently folded into either -- while leaving `server/license_policy.py`'s serving behavior
   untouched (advisory-only, per scope).
6. **[roadmap AC3]** The coverage report breaks out counts by the full `license_status` value
   set (not just a binary known/unknown), and separately by old-style vs. new-style id shape,
   since this research found the two shapes carry materially different missing-license risk.
7. **[roadmap AC3]** The coverage report documents explicitly which `license_status` bucket(s)
   count toward the >20%-bridgeland-stability-unknown owner-escalation check, given Risk 2's
   finding that lumping the pending-policy bucket into "unknown" (or vice versa) changes the
   headline number substantially.
