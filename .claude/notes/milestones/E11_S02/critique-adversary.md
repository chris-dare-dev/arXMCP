# E11_S02 — Adversary critique

**Commit range.** `76f7373..478cd44`
**Scope.** OAI-PMH delta loop: `ingest/oai_delta.py`, runbook,
systemd units, shell wrapper, mocked-HTTP test suite.

---

## Executive summary

- **Verdict: REWORK.** Two CRITICAL findings (dead 503 branch + no
  retry/backoff; missing redirect pinning on a NEW egress channel),
  two HIGH findings (cross-set token confusion in state file;
  `noRecordsMatch` raises on quiet days), several MEDIUM coverage
  gaps. The brief explicitly cites "Closes MEDIUM: arXiv 429
  backoff" — the milestone does not actually close it.
- **F1 (CRITICAL):** `urllib.request.urlopen` raises `HTTPError`
  on 5xx BEFORE `_fetch_page`'s status check at lines 259-262 is
  reached. That branch is dead code. No `HTTPError` catch, no
  `Retry-After` handling, no exponential backoff — the very thing
  the brief says this milestone closes. Note 08:200 mandates "Pause
  delta loop with exponential backoff (max 1 hour)."
- **F2 (CRITICAL):** The OAI-PMH `_fetch_page` does NOT validate
  `response.url` stays under `oaipmh.arxiv.org`. The docstring at
  `oai_delta.py:9-13` claims F9 redirect pinning is "inherited" —
  it is not. The OAI-PMH host is a separate egress channel that
  needs its own F9 mitigation (compare `ar5iv_fetch.py:155-173`).
- **F3 (HIGH):** State-file recovery is set-naive. A crash mid-set
  saves the in-flight token globally; on next-day recovery the
  token from (say) set 2 is fed to set 1 — arXiv raises
  `badResumptionToken` and the run dies before any progress.
- **F4 (HIGH):** A quiet day with zero new papers in a target set
  returns `<error code="noRecordsMatch">`, which `_parse_listrecords`
  promotes to `RuntimeError` (line 296). This crashes the delta
  run on legitimate empty responses. Common path, not edge.
- **F5 (MEDIUM):** AC3 "500-paper run in 90 min" test only proves
  budget arithmetic — `ingest_one_paper` is mocked to no-op.
  Real ~10s/paper × 500 ≈ 83 min is right at the boundary; the
  test does not model this. Acceptance criterion is only
  technically satisfied.
- **F6 (MEDIUM):** No test for HTTP 503 / `Retry-After`. Without
  one the "Closes MEDIUM: arXiv 429 backoff" claim in the brief is
  hollow at code-ship.
- **F7-F11:** Doc + edge-case gaps documented below.

---

## Severity calibration

| Severity | Definition (this critique) |
|---|---|
| **CRITICAL** | Data loss, security boundary breach, or broken invariant on a documented path. Examples: silent corruption, F9-class redirect bypass, the explicit brief-closer not implemented. |
| **HIGH** | Wrong behavior on common path (not edge). The run dies on a normal arxiv response; recovery code does the wrong thing on the documented crash-recovery path. |
| **MEDIUM** | Subtle correctness gap, missing test for a load-bearing claim, or partial implementation that meets the AC only by mocking the load-bearing component. |
| **LOW** | Doc-layout drift, redundant work, minor UX rough edges. |

---

## CRITICAL

### F1 — Dead `if status != 200` branch + no 503/Retry-After handling (`ingest/oai_delta.py:259-263`)

**File:line:** `ingest/oai_delta.py:250-263`

```python
with urllib.request.urlopen(  # noqa: S310 — pinned arxiv host
    request, timeout=timeout_seconds
) as response:
    status = response.status
    body = response.read()
    if status != 200:
        raise RuntimeError(
            f"OAI-PMH unexpected HTTP {status} for {url}"
        )
```

Python's default `urllib.request.urlopen` calls
`HTTPErrorProcessor` which raises `urllib.error.HTTPError` on any
response with status `>= 400`. Confirmed live: a 503 with
`Retry-After: 30` raises `HTTPError(code=503, headers=...)` from
inside `urlopen` itself, before the `status != 200` check is
reached. The branch is **dead code**.

There is no `except urllib.error.HTTPError`, no retry, no
`Retry-After` parsing, no exponential backoff. The first 503 from
arxiv's OAI-PMH endpoint propagates up `_fetch_page` →
`harvest_set` → `run_delta` and **crashes the entire nightly run
on the very first transient blip**. No state-file token is
salvageable because `_write_state` only runs AFTER `_parse_listrecords`
succeeds.

This is the precise failure mode the brief says this milestone
closes:

> **Risk notes.** Closes MEDIUM: arXiv 429 backoff (latency
> budget) — documenting the 90-minute latency budget and
> preserving the 3-second per-IP politeness delay closes the
> finding ...

The design constitution at
`.claude/notes/08-security-observability-ops.md:200` is
explicit:

> | OAI-PMH endpoint 503 | HTTP retry exhausted | Pause delta
> loop with exponential backoff (max 1 hour) |

Neither retry NOR exponential backoff exists. The runbook at
`docs/ops/delta-loop.md:160-166` waves at this: "sustained 503s
are unusual. If they appear: pause the timer (systemctl stop ...)
for an hour and resume." That is not a system implementation;
that is a manual operator workaround that contradicts the brief.

**Required fix:** Wrap `_fetch_page` in an explicit
`urllib.error.HTTPError` handler; treat 503 as the rate-limit
signal per OAI-PMH spec (read `Retry-After`, sleep, retry; cap
attempts and total elapsed at 1 hour per the design note).
Add a test that mocks a 503-then-200 sequence and asserts the
loop honors `Retry-After`. Without this F1 fix, the milestone's
own brief-closer is unfulfilled.

### F2 — OAI-PMH egress missing F9 redirect pinning (`ingest/oai_delta.py:247-263`)

**File:line:** `ingest/oai_delta.py:247-263`

E11_S01's F9 rectifier pinned ar5iv egress against silent off-host
redirects (`ar5iv_fetch.py:155-173`):

```python
response_url = response.url
if not response_url.startswith(AR5IV_BASE_URL + "/"):
    # ... treat as miss; F9 closes the silent redirect attack
```

The docstring at `oai_delta.py:9-13` advertises this fix as
"inherited" via `ingest_one_paper`. **This is misleading.** The
delta loop opens its OWN urllib connection to
`oaipmh.arxiv.org` in `_fetch_page`; that connection has no
inherited mitigation. A DNS-poisoned or attacker-controlled
intermediate redirect (3xx) silently follows to any host —
`urllib.request.urlopen` does this by default — and the
delta loop will trustingly parse the response as OAI-PMH XML.

The OAI-PMH endpoint is a NEW egress channel that needs its own
F9. The synthesis at §4 D4 fixed the endpoint to HTTPS, which
helps, but does not constrain redirects.

**Required fix:** After `urlopen`, assert
`response.url.startswith(OAI_PMH_ENDPOINT + "?")` (or the host
prefix); reject otherwise. Add a test where `_fetch_page`'s mock
returns a redirected URL and the run fails closed. Pair the
runbook entry pointing at this contract.

---

## HIGH

### F3 — State file is set-naive; cross-set crash recovery is broken (`ingest/oai_delta.py:411-417, 549-571`)

**File:line:** `ingest/oai_delta.py:411-417` (write), `549-571`
(consume).

The state file only persists `last_resumption_token` +
`last_harvest_date`. It does NOT persist which `set_spec` the
token belongs to. Concrete crash trace:

1. Set 1 (`math:math:AG`) completes. `harvest_set` writes
   `last_resumption_token=None` (lines 414).
2. Set 2 (`math:math:NT`) page 1 returns. `harvest_set` writes
   `last_resumption_token="tok-NT-2"`.
3. Process crashes.
4. Tomorrow 02:00 the systemd timer fires.
   `_resolve_resume` reads `last_resumption_token="tok-NT-2"`,
   `last_harvest_date=today` (well, yesterday now). Cross-day path
   → discards the token, sets `from=last_harvest_date`. (Good.)
5. But if the crash was same-day (cron retry, manual rerun),
   `_resolve_resume` returns `("today", "tok-NT-2")`. Then
   `run_delta` at line 554 feeds that token to `sets[0]`
   (`math:math:AG`). arXiv's resumption tokens are typed to the
   originating set; arXiv responds `<error code="badResumptionToken">`,
   which `_parse_listrecords` raises (line 296), crashing the
   whole run.

The synthesis at D6 specifies set-aware recovery; the
implementation does not honor it. The doc comment at line 552-554
acknowledges the gap ("we don't try to match a token to a set
after a crash") but the "safer recovery is to re-harvest the
full window" alternative is not implemented either — the token
gets used wrong, not discarded.

**Required fix:** Persist `last_set_spec` alongside the token,
and reject (or scope) the token at resume time if the set
doesn't match `sets[0]`. Add a test exercising the same-day
crash-then-resume path for set 2 → set 1 token misuse.

### F4 — `noRecordsMatch` on quiet days crashes the run (`ingest/oai_delta.py:291-296`)

**File:line:** `ingest/oai_delta.py:291-296`

```python
error_el = root.find("oai:error", _NS)
if error_el is not None:
    code = error_el.get("code", "unknown")
    msg = (error_el.text or "").strip()
    raise RuntimeError(f"OAI-PMH error code={code}: {msg}")
```

The OAI-PMH spec defines `noRecordsMatch` as the response when a
windowed query (e.g., `set=math:math:AG&from=2026-05-14&until=2026-05-14`)
matches zero records. This is a **normal, expected** response on
quiet days or in newer/quieter sets. The implementation treats
ALL `<error>` codes as fatal `RuntimeError`.

Result: any nightly run where ANY of the four target sets had a
zero-paper day crashes the entire harvest (the other sets'
records are lost, since the exception bubbles out of
`harvest_set` and `run_delta` never reaches the per-paper feed
loop).

`noRecordsMatch` MUST be caught and treated as "empty page, no
token, advance to next set." Optionally `badArgument` /
`cannotDisseminateFormat` / `badResumptionToken` remain fatal.

**Required fix:** Whitelist `noRecordsMatch` (and probably
`noSetHierarchy`) as "empty success." Add a test that returns
`noRecordsMatch` for one set and the run continues with the
other three.

---

## MEDIUM

### F5 — AC3 "500-paper budget" test does not model real per-paper cost (`tests/test_oai_delta.py:427-452`)

The test sets `sleep_between_pages=lambda _t: None` AND mocks
`ingest_one_paper` to return `_ok_paper_outcome` in microseconds.
This proves only that 500 iterations of a no-op loop fit in 90
minutes — which they trivially do. It does NOT prove that real
embedder + LaTeXML cost fits.

Per the implementation summary (lines 137-141), real typical runs
take ~15-20 min for ~71-133 papers — roughly 10s/paper. At
500 papers × 10s = 5000s ≈ 83 min, which is **right at the
budget boundary**. A spike day with 200-250 papers + ar5iv
degradation could plausibly breach.

**Required fix:** Either (a) parametrize the test with a synthetic
per-paper delay matching the implementation summary's stated
10s/paper figure to PROVE the budget is met under realistic
conditions, or (b) downgrade the AC claim in the implementation
summary from "verified" to "satisfied by mocked timing; real-load
verification deferred to E11_S05." The current state where the
AC is claimed without a load-faithful test is misleading.

### F6 — No test exercises 503 / Retry-After handling (`tests/test_oai_delta.py`)

The brief states this milestone **closes** the MEDIUM:arXiv-429-backoff
finding. There is no test for HTTP 503, no test for `Retry-After`,
no test that proves the loop survives a transient
rate-limit blip. Without such a test, the close is on paper only.

Tightly coupled to F1: even after the fix, ship a regression test
that mocks a 503-with-Retry-After=2 followed by a 200, and asserts
the harvester sleeps and retries.

### F7 — XML billion-laughs attack against ElementTree (`ingest/oai_delta.py:290`)

`xml.etree.ElementTree` does NOT resolve external entities in
Python 3.7+ (defusedxml's XXE protection is largely redundant),
but it DOES expand internal entities. A hijacked `oaipmh.arxiv.org`
(or man-in-the-middle on the still-unpinned response in F2)
returning a billion-laughs payload would memory-bomb the
harvester.

Pinned-host assumption mitigates the LIKELIHOOD; F2's missing
redirect pinning makes that assumption weaker. The standard
fix is `defusedxml.ElementTree.fromstring` instead of the stdlib
parser. Note 08 does not currently mandate defusedxml repo-wide
(it's not in `pyproject.toml`), so this is a coverage gap to
flag rather than a fix-now mandate. Acceptable to defer to E13
(threat-model audit) IF F2 is fixed.

### F8 — `_resolve_resume` future-clock-drift edge unconsidered (`ingest/oai_delta.py:213-230`)

If `state["last_harvest_date"]` is in the future (e.g., operator
manually wrote it to debug, or system clock skewed forward then
backward), `_resolve_resume` returns
`(future_date, None)` for the no-token branch. The `from`
parameter to `ListRecords` will be a future date; arXiv responds
`<error code="badArgument">` (technically valid OAI-PMH but the
window is empty). Compounds with F4: the run crashes.

Low blast radius (operator-error scenario) but the recovery is
trivial — if `last_harvest_date > today`, log + reset to yesterday.

### F9 — `from > until` operator-error path uncovered (`ingest/oai_delta.py:540-543, 678`)

The CLI accepts arbitrary `--from` / `--until` strings; nothing
validates `from <= until`. Operator typo of `--from=2026-05-15
--until=2026-05-14` produces a `badArgument` error from arXiv,
which (per F4) crashes the run with a confusing
`OAI-PMH error code=badArgument` rather than a clear local error.

**Recommendation:** Validate at CLI parse + `run_delta` entry:
fail fast with a clear message if `from > until`.

---

## LOW

### F10 — Redundant `_feed_record_to_pipeline` call for deleted records (`ingest/oai_delta.py:580-590`)

`run_delta`'s loop splits deleted vs not, but BOTH paths call
`_feed_record_to_pipeline` (lines 583-589 for deleted, 591-597
otherwise). `_feed_record_to_pipeline` internally short-circuits
deleted records (lines 442-447) and returns `None`. So the
deleted branch is doing a function-call dance to log a message
that could be logged inline. Cosmetic; not a bug.

### F11 — Stale `delta-timeout.flag` not cleared on dry-run (`ingest/oai_delta.py:573-578`)

`run_delta`'s `if dry_run: ... return summary` short-circuits
BEFORE `_clear_budget_flag(timeout_flag_path)`. An operator's
post-incident smoke-test dry-run will silently leave a prior
breach's sentinel in place. Move the clear above the dry-run
branch, or document the asymmetry in the runbook.

### F12 — `docs/ops/delta-loop.md` not referenced from root `README.md`

Per CLAUDE.md §1: "ONLY user-facing documentation referenced by
the root `README.md`" belongs under `docs/`. The runbook lives
at `docs/ops/delta-loop.md` but is not linked from the root
README. The README at `README.md:63-68` links the `docs/ops/`
directory and `latexml-drift-runbook.md` specifically, but not
the new delta-loop runbook. Comparable precedent:
`bulk-ingest-runbook.md` is also unreferenced — but that's
established drift, not a defense. Either link the runbook from
the README's "Operations" section or add a one-line bullet
listing it alongside the drift runbook.

### F13 — `make help` lacks a `make delta:` target

The runbook calls `./ops/cron/arxmcp-delta.sh` directly. There
is no `make delta:` convenience target. Cron + systemd are the
canonical invocations per synthesis D10, so this is a UX nit,
but a smoke-test convenience target would help operators not
muscle-memory the shell wrapper path. Acceptable to defer.

### F14 — Implementation docstring overclaims inherited fixes (`ingest/oai_delta.py:9-13`)

"This delta loop reuses it unchanged rather than cloning the
per-paper logic — every E11_S01 fix flows through transparently"
is true for `ingest_one_paper`'s scope (parse + chunk + embed +
write). It is FALSE for HTTP-egress fixes (F9 redirect pinning),
because the OAI-PMH page fetch is the delta loop's own egress
channel. The docstring should scope the claim.

---

## What was done well

- **Reuse of `ingest_one_paper` is correctly framed.** The delta
  loop is a thin harvester + per-paper feed; the bulk-ingest
  pipeline is called unmodified. Every per-paper fix from E11_S01
  flows through where it actually applies (chunker, embedder,
  store write). Good engineering discipline.
- **Staging-path discipline is preserved.** Writes route to
  `DEFAULT_LANCEDB_STAGING_PATH`; the active `corpus-version.json`
  is not touched. The synthesis's correction of the brief's
  "fresh LanceDB directory" language landed cleanly.
- **HTTPS endpoint and `arXivRaw` metadata format are right.**
  Synthesis D4/D5 was followed (`oaipmh.arxiv.org/oai` over the
  legacy HTTP). Four per-set calls, not the `set=math` umbrella.
- **Atomic state-file writes.** `_write_state` writes to
  `.tmp` and `replace()`s. Robust against torn writes mid-crash.
  Tested.
- **`flock -n` reentrancy guard is the right pattern** and
  matches established repo precedent (`latexml-drift-check.sh`).
- **No tool-schema changes; no hash bumps.** Synthesis D15
  honored — no BP1 cache breakpoint drift.
- **Sentinel-flag pattern mirrors the E10_S04 drift detector.**
  Cross-tool observability stays uniform.
- **Cross-day token expiry is correct.** `_resolve_resume`
  discards the saved token when `last_harvest_date < today`.
  Test coverage (`test_cross_day_resume_discards_expired_token`)
  is faithful.
- **`<header status="deleted">` is correctly treated as skip
  (no chunk/embed) per the brief.**
- **29 new tests, all green; no `requires_model` / network
  gating; runs on default suite.** Test scaffolding (mock
  fetcher, XML fixture helpers) is clean.

---

## Recommended rectification order

1. **F1** — Add `HTTPError` handler + 503 / `Retry-After` /
   exponential backoff (cap 1 hour). Closes brief's named risk.
2. **F2** — Pin `_fetch_page` to `oaipmh.arxiv.org` via
   `response.url` check. Same pattern as `ar5iv_fetch.py:155-173`.
3. **F4** — Whitelist `noRecordsMatch` as empty-success.
4. **F3** — Persist `last_set_spec`; scope token to set on resume.
5. **F6** — Add regression test for 503-then-200.
6. **F5** — Either parametrize the 500-paper test with a synthetic
   per-paper delay OR rescope the AC claim in the implementation
   summary.
7. **F8, F9** — Add guard clauses for future-date / inverted-window.
8. **F11** — Clear timeout flag before dry-run early-return.
9. **F12** — Link delta runbook from root README (or roll up
   with bulk-ingest-runbook into a single "Operator runbooks"
   bullet).
10. **F7, F10, F13, F14** — Defer or address as cleanup; not
    blocking.

---

## Rectification status

(empty — populated by the rectify phase)

