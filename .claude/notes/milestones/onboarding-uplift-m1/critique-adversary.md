# Critique — onboarding-uplift-m1

**Critic:** adversary
**Generated:** 2026-05-31T02:35:00Z
**Commit range:** be099b339859b3583e35ec1922a92a3b143d7aaf..e7c480adba88bf928efadbf0988a17badc813d2d
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Implementation is functionally correct and closes BLOCKER B1 cleanly:
  the 30-line declared-vars dump is gone, the carve-out branch renders
  legibly on stderr via both the `__main__` and uvicorn-import paths,
  and BP1/tool-schema hashes are byte-stable (104/104 m1-relevant
  tests pass, ruff clean).
- 0 CRITICAL, 0 HIGH, 4 MEDIUM, 2 LOW. The MEDIUMs cluster on a
  doc/code drift between the synthesis-locked 3-tool carve-out list
  and the 5 actual `os.environ.get("ARXMCP_CONTACT_EMAIL")` call sites
  — notably the very tool the README quick-start tells the user to run
  (`tools/fetch_seed.py`) is NOT in the carve-out hint, so a user who
  follows the README will be momentarily disoriented by the error.
- Highest-risk file:line: `server/main.py:281-286` (the carve-out hint
  string lists 3 of 5 actual consumers; misses
  `tools/fetch_seed.py`+`tools/fetch_one_paper.py`+`tools/curate_seed.py`
  via `tools/arxiv_fetch.py`, and `ingest/graph_ingest.py` directly).
- difflib `cutoff=0.7` calibrated correctly on 4/5 realistic typos
  (`ARXMCP_BIND_HOTS`→`BIND_HOST`, `LOG_LEVELE`→`LOG_LEVEL`,
  `NOTEBOK`→`NOTEBOOK`, `BIND_PROT`→`BIND_PORT`); fails the typo
  `ARXMCP_CONACT_EMAIL` (which falls to nearest-3 fallback). This is
  acceptable, but the gap is worth noting.
- `server/main.py:354` docstring lists `ARXMCP_OTEL_ENDPOINT` as a
  "documented-but-unimplemented var" used as an example of the
  silently-ignored class — but `ARXMCP_OTEL_ENDPOINT` is NOW declared
  on `Config` (`server/config.py:349`), so it would NOT be rejected.
  Stale example.
- `docs/install.md:322` troubleshooting row uses the OLD error-message
  prefix style (`variables: …`) but the new error reads
  `variables — each would silently bypass…`. A user grepping for the
  exact troubleshooting symptom text won't match.
- BP1/schema hash byte-stability verified independently via
  `pytest tests/test_server_tool_schema.py tests/test_prompts.py` →
  42 passed. No touch to `server/tools.py::ALL_TOOLS` or
  `server/prompts.py`.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — Carve-out hint misses 2/5 actual CONTACT_EMAIL consumers, including the README-quick-start tool

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/main.py:281-286
- **What:** `_KNOWN_INGEST_ENV_VARS["ARXMCP_CONTACT_EMAIL"]` names exactly three
  consuming modules: `tools/notebook_fetch.py`, `tools/recover_preambles.py`,
  `ingest/inspire_ingest.py`. A full repo grep for actual `os.environ` /
  `os.environ.get` reads of `ARXMCP_CONTACT_EMAIL` returns FIVE files:
  `tools/recover_preambles.py:236`, `tools/notebook_fetch.py:91`,
  `ingest/inspire_ingest.py:784`, `tools/arxiv_fetch.py:101` (library
  consumed transitively by `tools/fetch_seed.py`, `tools/fetch_one_paper.py`,
  `tools/curate_seed.py`), and `ingest/graph_ingest.py:775` (direct CLI).
  The carve-out omits `ingest/graph_ingest.py` and elides the
  `arxiv_fetch.py`-fronted CLI tools — `tools/fetch_seed.py` in particular
  is the tool the **README quick-start itself uses** at line 51
  (`python tools/fetch_seed.py`).
- **Why it matters:** the documented quick-start path is: bootstrap →
  export EMAIL → `python tools/fetch_seed.py` → `unset` (per README:48-52) →
  `make up`. If the user forgets the `unset` step, they hit the new error,
  which directs them to three tool names — none of which match
  `tools/fetch_seed.py` (the tool they JUST ran). The implementer-authored
  m1 doc-quality goal ("operator can locate where the var is actually
  consumed", `tests/test_server_startup.py:1306-1308`) is undershot for
  the most common operator path.
- **Proposed fix:** in `server/main.py:281-286`, expand the hint string
  to either name the `tools/arxiv_fetch.py` library *and* note the
  CLI tools that consume it, OR replace the three-tool enumeration with
  a shorter directive pointing at one place to look:
  ```python
  "ARXMCP_CONTACT_EMAIL": (
      "is NOT a server config var; it is read by the arXiv-facing CLI "
      "tools (tools/arxiv_fetch.py library + tools/fetch_seed.py, "
      "tools/notebook_fetch.py, tools/recover_preambles.py; "
      "ingest/inspire_ingest.py and ingest/graph_ingest.py) for the "
      "arXiv polite-pool User-Agent. Unset it for the server."
  ),
  ```
  Cheaper alternative: just add `tools/fetch_seed.py` and
  `ingest/graph_ingest.py` to the existing 3-name list — keeps
  ≤2 lines on stderr.
- **Regression guard:** `tests/test_server_startup.py::TestEnvVarScan::test_contact_email_carve_out_names_ingest_tools`
  currently asserts `any(tool in msg for tool in ("tools/notebook_fetch.py",
  "tools/recover_preambles.py", "ingest/inspire_ingest.py"))` — extend the
  tuple to include `tools/fetch_seed.py` and either tighten to `all()` or
  add a second `any()` asserting the README-quick-start path tool is
  present.

### F2 — Docstring example for the silently-ignored class is stale (OTEL_ENDPOINT is now declared)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/main.py:354
- **What:** The docstring on `_scan_unknown_arxmcp_env_vars` reads:
  > "a typo like `ARXMCP_BIND_HOST_TYPO` or a documented-but-unimplemented
  > var like `ARXMCP_OTEL_ENDPOINT` is silently ignored."

  Live verification: `ARXMCP_OTEL_ENDPOINT` is declared on
  `server/config.py:349` (`otel_endpoint: str | None = None`), so it
  is in `Config.model_fields` and `declared` includes it. Setting
  `ARXMCP_OTEL_ENDPOINT=...` does NOT trigger the scan's rejection
  branch — the docstring example is wrong by ~6 months of E14 evolution.
- **Why it matters:** this is the same "doc says X, code does Y" shape
  that my memory file `bp1-description-vs-handler-validator-drift`
  flags. A future implementer reading the docstring to understand WHY
  this scan exists will be misled into thinking OTEL_ENDPOINT is the
  motivating example, then will be confused when they grep and find it
  IS declared. It's a maintenance-time foot-gun, not a runtime bug.
- **Proposed fix:** replace `ARXMCP_OTEL_ENDPOINT` with a still-valid
  example. Good candidate: a variable that was never declared, e.g.
  `ARXMCP_CACHE_TTL_SECONDS` (purely hypothetical; not used anywhere
  in the repo). Or drop the second example entirely and just keep the
  `ARXMCP_BIND_HOST_TYPO` typo case.
  ```python
  # Closes F4 from the E06_S01 critique. ``pydantic-settings``'s
  # ``extra="forbid"`` only fires for direct ``__init__`` kwargs —
  # NOT for env-var input. So a typo like ``ARXMCP_BIND_HOST_TYPO``
  # is silently ignored. This scan walks ``os.environ`` for every
  # ``ARXMCP_*`` key and asserts it maps to a declared field.
  ```
- **Regression guard:** none required (pure doc edit; existing
  `TestEnvVarScan` already covers the typo-rejection runtime contract).

### F3 — Cardinal "no 32-var dump" test threshold collides with multi-unknown realistic case

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_server_startup.py:1351-1357
- **What:** `test_error_message_does_not_dump_all_declared_vars` sets
  ONE unknown var (`ARXMCP_DOES_NOT_EXIST_AT_ALL`) and asserts the
  message contains `< 10` ARXMCP_ mentions, justified in the assertion
  message as "real ceiling ~4: offending var + up to 3 nearest". This
  is too tight for the realistic multi-unknown failure case. With ONE
  unknown taking the short-form fallback, the ARXMCP_ count is 6
  (`unknown ARXMCP_* environment variables` (1) +
  `ARXMCP_DOES_NOT_EXIST_AT_ALL` (1) +
  `is not a declared ARXMCP_* var; nearest:` (1) + 3 nearest (3) = 6).
  With THREE unknowns each taking different branches (carve-out + typo
  + short-form), the count rises to ~9 — right at the threshold. A
  future cleanup that adds a single ARXMCP_-prefixed phrase to the
  header would push a multi-unknown test fixture over the boundary,
  triggering a false regression alarm.
- **Why it matters:** the cardinal test is **explicitly described** as
  the "regression guard that catches re-introducing the 30-line dump
  even if other assertions pass" (tests/test_server_startup.py:1340-1342).
  Tightening it too much risks false positives on benign refactors;
  loosening it too much defeats the purpose. The current threshold of
  10 is reasonable for the single-unknown case (6 ≪ 10) but should
  ideally also assert it doesn't blow up for the multi-unknown case
  the implementer never tested.
- **Proposed fix:** either (a) raise the threshold to 20 (still well
  below 32+the header strings; comfortably tolerant of multi-unknown
  workloads), OR (b) keep the threshold at 10 and add a SECOND
  parameterized assertion with 3 unknowns set, threshold 15, to lock
  the multi-unknown realistic case. Option (a) is the cheaper fix:
  ```python
  assert arxmcp_mentions < 20, (
      f"error message mentions {arxmcp_mentions} ARXMCP_* names — "
      f"the 30-line declared-vars dump regressed. Expected <20 "
      f"(realistic max: ~10 for 3 unknowns across all 3 branches; "
      f"32 was the BLOCKER B1 signal). Message: {msg!r}"
  )
  ```
- **Regression guard:** this finding IS the regression-guard
  calibration; the fix tightens the test itself.

### F4 — Troubleshooting-table symptom column uses pre-rewrite error wording

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** docs/install.md:322
- **What:** The new troubleshooting row's Symptom column reads:
  > "Server FATALs at boot with `unknown ARXMCP_* environment
  > variables: …ARXMCP_CONTACT_EMAIL…`"

  The literal new error message reads (live-verified):
  > `unknown ARXMCP_* environment variables — each would silently
  > bypass the documented config; fix or remove:`

  The colon (`:`) in the doc symptom row does NOT appear in the new
  error — there's an em-dash (` — `) instead. A user searching the
  install doc with `grep "unknown ARXMCP_"` matches; a user searching
  for the literal `unknown ARXMCP_* environment variables:` (with the
  colon, as shown in the doc) does NOT match the runtime message.
- **Why it matters:** the troubleshooting table is one of the two
  AC6-mandated `/mcp/` note locations; its searchability is the entire
  reason it exists. A doc that mis-quotes the FATAL string defeats the
  "look up the error in install.md" affordance the implementer added.
  This is the same class as my memory file
  `security-doc-drift-on-multi-byte-magic-sniff`: operator-facing doc
  pre-dates the code edit and didn't move in lockstep.
- **Proposed fix:** update `docs/install.md:322` Symptom column to
  match the actual new error prefix, OR drop the literal `:` to be
  prefix-agnostic:
  ```markdown
  | Server FATALs at boot with `unknown ARXMCP_* environment variables` mentioning `ARXMCP_CONTACT_EMAIL` | … |
  ```
  Either form survives future minor wording refactors.
- **Regression guard:** none feasible (the doc table isn't covered
  by a structural test). Lock the symptom phrasing in the doc itself
  by quoting only the substring that the new test pins.

### F5 — `/mcp/` inline note misses GET (SSE-listen) clients that also hit the 307 redirect

- **Severity:** LOW
- **Source:** adversary
- **File:** docs/install.md:148-156
- **What:** The new inline note phrases the trailing-slash problem as
  a POST-body-drop issue:
  > "most HTTP clients drop POST bodies on the redirect"

  The MCP 2025-06-18 Streamable HTTP spec (verified via WebFetch,
  https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
  §"Listening for Messages from the Server") permits a client to
  also issue an HTTP **GET** to the MCP endpoint to open an SSE
  stream. A GET to `/mcp` (bare) likewise 307-redirects to `/mcp/`.
  GET requests carry no body, so the body-drop framing doesn't
  cover the GET-SSE case; the worse failure mode is a misconfigured
  proxy / client that doesn't follow 307 at all and just sees a
  status code instead of the SSE stream.
- **Why it matters:** very low. The shim only POSTs; the
  registration-block scenario doesn't involve custom GET-SSE
  clients. But for the section titled "MCP endpoint path" in the
  install doc, a reader writing a custom Streamable-HTTP client (not
  via the shim) gets the *partial* story.
- **Proposed fix:** broaden the inline note's coverage to mention
  the GET-SSE path, or just state the rule generally:
  ```markdown
  > **MCP endpoint path.** The shim POSTs to `/mcp/` (with the
  > trailing slash) — it appends the path internally to the
  > `--server` base URL, so the registration above is correct
  > as-is. Custom HTTP clients (POST or GET-for-SSE) must address
  > `/mcp/` directly: FastAPI/Starlette 307-redirects bare `/mcp`
  > to `/mcp/`, which most HTTP clients handle for GET but drop
  > the POST body for. This is a FastAPI mount idiosyncrasy, not
  > an MCP spec requirement (see MCP 2025-06-18 Streamable HTTP:
  > the example endpoint is unslashed).
  ```
- **Regression guard:** none feasible (operator-facing doc precision).

### F6 — README `unset ARXMCP_CONTACT_EMAIL` is in the quick-start but absent from `docs/install.md`

- **Severity:** LOW
- **Source:** adversary
- **File:** README.md:52, docs/install.md (no equivalent)
- **What:** The README's quick-start now brackets the
  `export ARXMCP_CONTACT_EMAIL=...` line with an explicit
  `unset ARXMCP_CONTACT_EMAIL` after `python tools/fetch_seed.py`.
  Good. But `docs/install.md` — the canonical operator-onboarding
  doc the README itself points at — does NOT describe the
  export/unset flow at all; only the registration block + the new
  troubleshooting row. A user starting from `docs/install.md` (the
  more thorough resource) is not told that the var is needed for
  initial corpus fetch, then must be unset for the server.
- **Why it matters:** the README and install.md should tell
  consistent operator stories. The README is the "go fast" door;
  install.md is the "operate this correctly" door. The install.md
  troubleshooting row reads as a corrective for a fault — but the
  doc never told the user to set the var in the first place. The
  fault state is reachable only via the README path; a pure install.md
  reader would never encounter the issue. So the install.md
  troubleshooting row addresses a problem the doc itself doesn't
  cause. Minor inconsistency.
- **Proposed fix:** add a short sub-section to `docs/install.md`
  (between §1 "Install" and §2 "Register with Claude Code") titled
  "Initial corpus fetch" that mirrors the README's bracketed
  export/unset pattern. Or just delete the troubleshooting row's
  ARXMCP_CONTACT_EMAIL entry if install.md is the "operating only"
  doc and the README's bracketed pattern is sufficient for first-run.
- **Regression guard:** none.

## What was done well

- BP1 cache discipline absolutely respected: zero touch to
  `server/tools.py::ALL_TOOLS`, `server/prompts.py`, or any frozen-bytes
  surface. `EXPECTED_TOOL_SCHEMA_SHA256` (tests/test_server_tool_schema.py:95)
  and `EXPECTED_BP1_SHA256` (tests/test_prompts.py:649) verified
  unchanged via live test run (42 passed).
- The synthesis-locked D2 decision (`difflib n=1, cutoff=0.7`) was
  adopted and verified live against the actual 32-var declared set:
  `ARXMCP_BIND_HOTS→BIND_HOST`, `LOG_LEVELE→LOG_LEVEL`,
  `NOTEBOK→NOTEBOOK`, `BIND_PROT→BIND_PORT` all produce sensible
  suggestions; the `ARXMCP_OTEL_ENDPOINT` case (which would have been
  a false rejection at cutoff=0.6) correctly suggests itself at 0.7
  by virtue of being declared.
- The carve-out semantics correctly chose D1 (still raise, with
  tailored message). The pre-existing
  `test_contact_email_env_var_rejected:357-383` regex
  `match="ARXMCP_CONTACT_EMAIL"` continues to pass unchanged — proves
  the implementer correctly read the synthesis on the contract
  inversion question.
- The three new tests under `TestEnvVarScan` use independent predicates
  per synthesis FM-4, NOT full-sentence equality. The variable-name +
  semantic-fragment pattern correctly resists brittle wording locks.
- `Config.model_fields` preserved as the dynamic source of `declared`
  (server/main.py:368-370) — adding a future Config field automatically
  widens the rejection set. Synthesis FM-5 mitigation honored.
- The `_KNOWN_INGEST_ENV_VARS: dict[str, str]` shape (instead of the
  synthesis's `frozenset`) is actually a MORE flexible substrate for
  future ingest vars — each entry carries its own hint string, so
  future contributors don't need to thread per-var message logic
  through `_format_unknown_arxmcp_env_var`. This is a justified
  deviation from synthesis intent and well-motivated by the
  carve-out-message-customization use case.
- Doc-sweep grep returns clean: every server-startup snippet
  (CLAUDE.md §9, README.md quick-start) is either retargeted to
  ingest context or explicitly states "the server rejects it".
  All `tools/*.py` ingest-context references correctly preserved
  per synthesis FM-6.
- The error message renders correctly on stderr in BOTH paths
  (`__main__` direct + `uvicorn server.main:app` import). Live test
  confirmed the multi-line `\n` survives `sys.stderr.write(f"FATAL:
  {exc}\n")` wrapping at server/main.py:825 and 856; the user sees
  the full per-var hint list.
- The Makefile bootstrap nag (line 63-67) correctly fires only when
  CONTACT_EMAIL is unset AND correctly directs users to ingest tools
  (not `make up`). The synthesis's concern about persona-A noise is
  arguably present but the nag wording explicitly says "NOTE: …
  before running the arXiv CLI fetch tools" — a notebook-only user
  who doesn't ingest can ignore it without confusion.

## Recommended rectification order

1. F1 (carve-out tool list completeness) — highest leverage; touches
   the user-facing operator story. ~5 LOC + 1 test assertion.
2. F4 (install.md troubleshooting row symptom precision) — single doc
   line edit; preserves the AC6 affordance.
3. F2 (server/main.py:354 stale docstring example) — pure doc edit
   inside server/main.py; ~2 LOC.
4. F3 (cardinal test threshold raise) — single test line edit;
   prevents future false alarms on multi-unknown realistic case.
5. F5, F6 (LOW) — defer.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->

verdict: RECTIFY-REQUIRED; 6 findings (0/0/4/2)
