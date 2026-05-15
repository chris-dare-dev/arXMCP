# Critique — E11_S01

**Critic:** adversary
**Generated:** 2026-05-14T23:50:00Z
**Commit range:** e274edd..f0a19c6
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- Verdict SHIP-WITH-FIXES: the scaffolding is mostly defensible, but
  two real bugs corrupt the per-paper pipeline (silent stale-embed
  reuse on embedder failure, and a `parsed_dir` parameter that is
  honored by `try_cache` but ignored by `chunk_paper`'s hardcoded
  `PARSED_DIR`). One promised feature (`--resume`) is a documented
  no-op. AC4 is functionally deferred without honest justification.
- Counts: 0 CRITICAL, 3 HIGH, 4 MEDIUM, 3 LOW.
- Highest-risk file: `ingest/bulk_ingest.py:304-310` —
  `embed_paper(paper_id)` swallows failure (returns `EmbedStats`,
  never raises); the subsequent `load_embed_record` then returns
  stale prior embeddings instead of `None`, silently writing the
  wrong vectors into the staging LanceDB.
- Cross-axis pattern: the orchestrator trusts that nested ingest
  helpers (chunker, embedder) will either succeed or return `[]` /
  `None`. They don't in all paths; multiple silent-failure paths.
- AC4 ("`pytest --hybrid --ndcg-min=0.70` passes") is renamed
  "operator-gated" in the implementation summary, but the brief
  asserts the test passes — this is scope reduction past the bar
  with nothing in this milestone advancing the fixture toward
  runnable. F7.
- Per-paper Kùzu graph population (brief §4) is deferred to
  runbook step 6; the brief framed it as part of the per-paper
  pipeline ("Populate the citation graph"). Justifiable scoping
  but not a code-ship achievement of the AC; F6.
- `progress_interval` accepts 0 and crashes with ZeroDivisionError
  before any work happens — easy input-validation miss. F10.
- Doc-layout: runbook lands under `docs/ops/` which is established
  precedent (E10_S04), but CLAUDE.md §1 still describes `docs/` as
  only `install.md`; either CLAUDE.md is stale or `docs/ops/`
  violates the doc-placement rule. Not a critique-blocking issue.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer |

## Findings

### F1 — Silent stale-embed reuse on `embed_paper` failure

- **Severity:** HIGH
- **Source:** adversary
- **File:** ingest/bulk_ingest.py:304-310
- **What:** `ingest_one_paper` calls `embed_paper(paper_id)` and
  discards its return value, then immediately calls
  `load_embed_record(paper_id)`. Per `ingest/embedder.py:850-883`,
  `embed_paper` catches `PER_PAPER_FAILURE_EXCEPTIONS` and returns
  an `EmbedStats(status="fail", ...)` without raising — the
  per-paper NPZ on disk is whatever it was BEFORE the call (or
  absent). `load_embed_record` then reads the stale NPZ from a
  previous run of `embed_paper` (different chunker output,
  different model version) and `ingest_one_paper` writes those
  stale vectors into the staging LanceDB.
- **Why it matters:** Silent corpus corruption. The brief's AC1
  ("≥ 100K chunks in the staging LanceDB") would pass even when
  the chunks point at stale vectors — and there is no chunker /
  embedder version cross-check at the LanceDB-write boundary in
  this orchestrator. The whole "MVCC isolation" defense unravels
  if the staging dataset has wrong-version embeddings inside it.
- **Proposed fix:** Inspect `embed_paper`'s return value:
  ```python
  embed_stats = embed_paper(paper_id)
  if embed_stats.status != "ok":
      outcome.failure_reason = f"embedder_failed:{embed_stats.error_class or 'unknown'}"
      return outcome
  ```
  Also assert `embed_stats.chunks_processed > 0` for non-empty
  chunks; a "no-op skip" against a previously-embedded paper with
  STALE chunker_version is currently the up-to-date branch (see
  `ingest/embedder.py:914-936`) — that branch is correct only if
  the on-disk sidecar's chunker_version matches the version that
  just produced the chunks, which it does at the moment, but the
  orchestrator should not trust this implicitly.
- **Regression guard:** Add a test in `tests/test_bulk_ingest.py`
  that mocks `embed_paper` to return `EmbedStats(status="fail",
  error="x")` and asserts `ingest_one_paper` returns
  `failure_reason` starting with `"embedder_failed"` and does NOT
  call `write_chunks`.

### F2 — `parsed_dir` parameter is silently overridden by chunker's hardcoded `PARSED_DIR`

- **Severity:** HIGH
- **Source:** adversary
- **File:** ingest/bulk_ingest.py:250-251, 282-285, 294;
  ingest/chunker.py:78, 815
- **What:** `ingest_one_paper` accepts `parsed_dir` and passes it
  to `try_cache` (which honors it — writes ar5iv HTML there) AND
  to `_has_local_parsed_html` (which checks there). But on the
  next line, `chunks = chunk_paper(paper_id)` calls into the
  chunker, which reads from a HARDCODED module-level
  `PARSED_DIR = REPO_ROOT / "var" / "arxmcp" / "corpus" / "parsed"`
  at `ingest/chunker.py:78,815`. If an operator overrides
  `--parsed-dir`, ar5iv writes HTML into the overridden directory,
  the orchestrator's existence-check reports a "hit", and then
  the chunker fails-to-find at the default path → returns `[]` →
  `failure_reason = "chunker_returned_empty"`.
- **Why it matters:** Hidden coupling. A user-facing CLI flag is
  honored partially and ignored partially; the error mode is a
  silent skip-and-log, not a hard error. Operator wastes hours
  debugging "why are all my papers failing the chunker."
- **Proposed fix:** Either (a) remove the `parsed_dir` parameter
  from `ingest_one_paper` and the CLI surface (use the chunker's
  fixed `PARSED_DIR` everywhere), or (b) make the chunker's
  `PARSED_DIR` reach `_chunk_paper_impl` via parameter
  (parameterize, defaulting to `PARSED_DIR`), so the CLI override
  threads end-to-end. Option (a) is safer — operator can always
  symlink. Either way the CLI `--parsed-dir` flag must not exist
  in its current form.
- **Regression guard:** Add a test that overrides `parsed_dir` to
  a tmp_path, stages ar5iv hit content there, and asserts the
  chunker is invoked against the same tmp_path (or that
  `--parsed-dir` is gone from the CLI).

### F3 — `--resume` flag is documented but a no-op

- **Severity:** HIGH
- **Source:** adversary
- **File:** ingest/bulk_ingest.py:338, 457-466, 489-497;
  docs/ops/bulk-ingest-runbook.md:162-172
- **What:** The CLI advertises a `--resume` flag with a
  three-sentence help text claiming it "skips papers whose
  embeddings sidecar exists". The flag's value is threaded into
  `run_bulk_ingest(...resume=resume...)`, but inside
  `run_bulk_ingest` the parameter is never read — it's dead.
  The runbook (docs/ops/bulk-ingest-runbook.md:162-172) prescribes
  `make ingest ARGS="--paper-ids-file=... --resume"` as the
  resume command and explicitly describes the behavior. The
  implementation summary at line 207-211 acknowledges this is a
  "no-op" CLI flag — i.e. the summary admits the bug but ships
  it anyway.
- **Why it matters:** An operator following the runbook for a
  multi-day ingest crash recovery will think they have skipped
  ahead and silently reprocess every paper (slow), or worse,
  re-trigger the destructive chunker sweep at
  `ingest/chunker.py:837-840` (`for stale in out_dir.glob("*.json"): stale.unlink()`)
  on every paper. While the embedder's up-to-date check makes
  this *correct*, it's an order-of-magnitude time waste with
  the operator believing they are resuming.
- **Proposed fix:** Either (a) implement `--resume` for real
  (short-circuit `ingest_one_paper` when
  `(EMBEDDINGS_DIR / paper_id / EMBEDDINGS_NPZ_NAME).exists()`),
  or (b) remove the flag from the CLI surface and remove the
  runbook lines that describe it. Pick (b) for a smaller diff
  — the embedder's sidecar idempotence already protects against
  duplicate work at the embed step; chunker re-runs are cheap.
- **Regression guard:** If implementing (a), add a test that
  stages an `embeddings.npz` sidecar and asserts
  `ingest_one_paper` is never called for that paper_id. If
  removing (b), grep that `--resume` is absent from `_cli`,
  `run_bulk_ingest`, and the runbook.

### F4 — `<math` body-content guard rejects math-light papers

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/ar5iv_fetch.py:66, 176-188
- **What:** The ar5iv-fetch hit detection requires `"<math"` to
  appear in the response body, on the theory that LaTeXML
  produces `<math>` MathML tags for any math content. But (a) a
  paper with NO math content whatsoever (rare in math.AG but
  possible in survey-style hep-th notes) would be rejected and
  fall through to LaTeXML — which would also produce no math
  and (with the chunker) generate a paper missing nothing. (b)
  An ar5iv "this paper could not be processed" page does
  not always strip ALL `<math` substrings (CSS classes like
  `<div class="math">` would also trigger). The substring match
  is loose.
- **Why it matters:** False-negatives on legitimate ar5iv pages
  inflate the ar5iv miss rate (AC5 has a ≥ 70% target) and
  unnecessarily push papers down the LaTeXML or skip ladder.
  False-positives let ar5iv error banners through. The current
  ar5iv error-banner format documented in research-brief-2.md
  is unstable.
- **Proposed fix:** Tighten to a tag boundary —
  `re.search(r"<math\b", body)` — and also accept the alternate
  signal `mathml` namespace declaration. For belt-and-braces,
  reject if `body.count("<math") == 0 AND
  "could not be processed" IN body` (the documented banner
  text). Keep the heuristic but make it less brittle.
- **Regression guard:** Add tests for: math-light paper (one
  inline `<math>` tag) → hit; error-banner with `class="math"`
  div but no `<math>` element → miss; happy path with
  `<math display="block">` → hit. Tests already exist for two
  of the three cases; the third (`class="math"` false positive
  guard) is new.

### F5 — Dry-run misreports `ar5iv_hit_rate` for un-queried papers

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/bulk_ingest.py:387-411
- **What:** `_run_dry` increments `summary.ar5iv_misses` for
  the catch-all "WOULD_FETCH_AR5IV_THEN_FALLBACK" branch — i.e.
  papers for which we never check ar5iv because we never made
  a network call. The dry-run's final `ar5iv_rate=...` line
  (the CLI summary printout) therefore reports a hit rate
  computed against papers that were never queried.
- **Why it matters:** Operator-facing reporting bug. The dry-run
  is intended to sanity-check the input list and the cache
  state before a multi-day commit. If 100% of the papers have no
  local cache, the dry-run reports ar5iv_rate=0.000 — which an
  operator might interpret as "ar5iv is broken" rather than
  "the cache is empty" (the correct interpretation, since the
  dry-run doesn't actually hit ar5iv).
- **Proposed fix:** In `_run_dry`, track a separate
  `local_cache_hits` field and a `would_fetch` field; don't
  conflate them into `ar5iv_hits` / `ar5iv_misses`. Or,
  cleaner, do NOT increment `ar5iv_misses` in dry-run at all —
  leave the field at 0 for dry-run summaries and update the
  CLI summary printout to omit `ar5iv_rate` when `dry_run=True`.
- **Regression guard:** Add a `TestDryRun::test_dry_run_does_not_report_misleading_ar5iv_rate`
  that runs a 3-paper dry-run with no local cache and asserts
  the summary's `ar5iv_misses` stays at 0 (or the printout
  omits the rate line).

### F6 — Per-paper Kùzu graph population is silently deferred from the brief

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** ingest/bulk_ingest.py:246-320 (absence);
  docs/ops/bulk-ingest-runbook.md:191-200
- **What:** The brief §4 specifies "Populate the citation graph
  in Kùzu from OpenAlex (math.AG, math.NT) and INSPIRE-HEP
  (hep-th, math-ph) citation data." The implementation lifts
  this OUT of the per-paper pipeline and into a runbook step
  ("Step 6 — Populate the citation graph") that runs separate
  `ingest.graph_ingest` / `ingest.inspire_ingest` modules. The
  implementation summary calls this a "scope reminder" but
  doesn't explain why the brief's ordering (Kùzu pop as part
  of the pipeline) should be ignored.
- **Why it matters:** Defensible decoupling (graph and chunks
  are on different cadences) BUT the brief's deliverables list
  does not separate them; an operator who runs `make ingest`
  and verifies AC1+AC2+AC5 will believe the milestone is
  complete and may skip step 6 entirely. The `cite_neighbors`
  tool would then return empty results against the bulk-
  ingested corpus.
- **Proposed fix:** Either (a) chain a final
  `ingest.graph_ingest` + `ingest.inspire_ingest` call at the
  END of `run_bulk_ingest` (after the per-paper loop, gated
  by a `--with-graph` flag defaulting to true), or (b)
  document this scope split in the implementation summary AND
  in the runbook's executive paragraph (currently buried at
  step 6). Option (b) is cheaper and matches the synthesis's
  scaffolding-only posture.
- **Regression guard:** Update `docs/ops/bulk-ingest-runbook.md`
  preamble (line 1-15) to explicitly call out "Step 6 (graph
  population) is part of this milestone's contract." Add a
  comment in `ingest/bulk_ingest.py` module docstring pointing
  at the runbook for the graph step.

### F7 — AC4 (`pytest --hybrid --ndcg-min=0.70`) is functionally deferred

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** .claude/notes/milestones/E11_S01/implementation-summary.md:73-78;
  tests/eval/test_retrieval_quality.py
- **What:** The brief AC4 reads: "`pytest tests/eval/test_retrieval_quality.py
  --hybrid --ndcg-min=0.70` passes against the new version." The
  implementation summary marks this as "Operator-gated" because
  "the 20-query fixture is underpowered (4 queries today)" — and
  ships nothing that materially closes that gap. The synthesis
  punts the fixture-curation to E11_S04. This milestone does
  not add fixture entries, does not add the operator flag
  plumbing to run the eval against the staging path, and does
  not document a path to "this AC has teeth."
- **Why it matters:** The brief's AC is an explicit pass / fail
  bar; the implementation reframes it as "skipped by the cold-
  start matrix when fixture is missing." This is scope reduction
  past the brief's bar — distinct from F1/F5/F6's behavioral
  bugs but still a violation of the milestone's contract. The
  rectifier should decide whether to push back on the brief
  (which would unblock the implementation by formally noting AC4
  as a follow-up dependency on E11_S04) or to add the missing
  plumbing.
- **Proposed fix:** Either (a) add a CLI flag `--lancedb-path`
  to the eval harness that points the retrieval query at the
  staging path, so AC4 has a runnable form even at code-ship,
  OR (b) explicitly amend the roadmap E11_S01 brief to mark AC4
  as deferred to E11_S04 and update the implementation summary
  to call that out as the contractual change. Option (a) is the
  rigorous one; option (b) is the smaller-blast option.
- **Regression guard:** If (a), add a test that runs the eval
  against a synthetic 1-paper staging LanceDB and verifies the
  query path resolves to the staging path. If (b), update both
  `.claude/roadmap/E11-*.md` and the brief verbatim in
  `state.json.milestone_brief`.

### F8 — `progress_interval=0` triggers ZeroDivisionError

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/bulk_ingest.py:380
- **What:** The bulk loop computes `n % progress_interval == 0`.
  If the operator passes `--progress-interval=0` (the CLI does
  not currently expose this, but the public function signature
  defaults `progress_interval: int = DEFAULT_PROGRESS_INTERVAL`
  and accepts any int), the first paper triggers
  `ZeroDivisionError`. Negative values give surprising behavior
  too (modulo wraps).
- **Why it matters:** Public-API foot-gun on a parameter that
  shouldn't be 0. Currently unreachable from the CLI, but every
  public Python parameter that an external caller might set
  should validate.
- **Proposed fix:** Validate at the top of `run_bulk_ingest`:
  ```python
  if progress_interval <= 0:
      raise ValueError("progress_interval must be ≥ 1")
  ```
- **Regression guard:** Add a test
  `TestRunBulkIngest::test_zero_progress_interval_rejected`.

### F9 — `urllib` request does not bound redirects to ar5iv host

- **Severity:** LOW
- **Source:** adversary
- **File:** ingest/ar5iv_fetch.py:134-143
- **What:** `urllib.request.urlopen(...)` uses the default
  `OpenerDirector` which includes `HTTPRedirectHandler` — it
  silently follows 3xx redirects to any host. If
  `ar5iv.labs.arxiv.org` ever returns a 302/303 to an attacker-
  controlled location, the fetch follows blindly. The body
  validation (`<math` check) provides some defense (an attacker
  page would have to include the substring to pass) but not
  much.
- **Why it matters:** Defense-in-depth gap. ar5iv is a static
  CDN site that doesn't redirect — but the threat model in
  `08-security-observability-ops.md` calls for hostname pinning
  on the egress path, and this is an egress that doesn't pin.
- **Proposed fix:** Build a redirect-disabling
  `OpenerDirector` and use it; or after the `urlopen` call,
  verify `response.url.startswith(AR5IV_BASE_URL)`.
- **Regression guard:** Add a test that mocks a redirect
  response and verifies the fetch rejects it as a miss with
  reason `"unexpected_redirect"`.

### F10 — Test file docstring promises a `requires_model` smoke test that doesn't exist

- **Severity:** LOW
- **Source:** adversary
- **File:** tests/test_bulk_ingest.py:9-13
- **What:** The module docstring claims: "End-to-end 'smoke'
  test against a SINGLE paper — mocks the ar5iv hit, stages a
  minimal parsed HTML, runs the real chunker + embedder +
  LanceDB write at the staging path. Marked `requires_model`
  (BGE-M3 download)." No such test exists in the file.
  `grep "@pytest.mark.requires_model" tests/test_bulk_ingest.py`
  is empty. The smoke test is described but not written.
- **Why it matters:** A reader trusts the docstring. The
  test-coverage claim in the implementation summary line 158-167
  ("+7 tests") doesn't include any end-to-end test, which the
  summary itself doesn't promise — but the test-file's docstring
  promises it as part of the suite's contract.
- **Proposed fix:** Either (a) delete the misleading docstring
  lines, or (b) add the promised smoke test. (a) is the smaller
  diff.
- **Regression guard:** None for (a); for (b), the test itself
  is the regression guard.

## What was done well

- **Staging-path discipline is the right call.** The
  implementation summary correctly identifies the brief's
  `vN+1/` directory language as wrong (LanceDB MVCC is
  in-dataset version-int), and writes to
  `var/arxmcp/index/lancedb-staging/` instead. AC2 ("active
  `corpus-version.json` untouched") falls out of the design.
- **`is_valid_paper_id` is called at every input boundary.**
  `_read_paper_ids`, `ingest_one_paper`, and `try_cache` all
  validate before any path concat. Path-traversal defense via
  the regex.
- **Single-writer constraint is respected.** The bulk loop is
  sequential at the write boundary; the module docstring cites
  `ingest/store.py:44-55` and the constraint is honored. No
  `multiprocessing.Pool` over `write_chunks`.
- **`requires_full_corpus` marker is double-gated.** Marker AND
  `ARXMCP_RUN_FULL_CORPUS_TESTS=1` env var — prevents a stray
  `-m` flag in CI from accidentally opting in. Good belt-and-
  braces hygiene.
- **`Ar5ivResult` is a frozen, slotted dataclass.** Immutability
  at the boundary; no risk of caller mutation skewing the
  miss/hit reporting downstream.
- **Politeness contract is correctly NOT mixed with
  `arxiv.org`'s.** The ar5iv module's docstring explicitly
  documents that the 3-second sleep is for `export.arxiv.org`
  only — saves an order-of-magnitude on a 200K paper run.
- **Local-cache short-circuit is byte-checked.** `try_cache`
  requires BOTH the cache file AND the parsed file to exist
  before skipping the network call. If only one is present
  (partial prior write), the network call fires and rewrites
  both — no half-state ambiguity.
- **`tools/list` schema hash is correctly untouched.** No tool
  surface change in this milestone; `TOOL_SCHEMA_VERSION` stays
  at 6, `EXPECTED_TOOL_SCHEMA_SHA256` not re-pinned. BP1 cache
  discipline preserved.
- **The dry-run respects `assertion`-style mocks.** The dry-run
  test patches `ingest_one_paper` with an `AssertionError` side
  effect and verifies the function is never called — strong
  guarantee that dry-run is truly side-effect-free.

## Recommended rectification order

1. **F1** — silent stale-embed reuse. Most-load-bearing
   correctness issue; could be confused with "MVCC working
   correctly" because the corpus-version.json discipline is
   intact. Fix first, add the regression test.
2. **F3** — remove (or implement) the no-op `--resume` flag.
   Cheaper to remove; F3's fix also clarifies whether F1's fix
   should special-case the resume short-circuit.
3. **F2** — `parsed_dir` parameter coupling. Either remove the
   CLI flag (smaller blast) or thread parsed_dir end-to-end into
   the chunker. Both options interact with F3's CLI cleanup, so
   sequence after F3.
4. **F7** — AC4 deferral. Pick option (b) — formal brief
   amendment — unless the rectifier opts for option (a)'s eval-
   plumbing addition. Either way this is a contract-clarity fix.
5. **F6** — Kùzu graph population. Update the runbook preamble
   to call out step 6 as part of the milestone contract.
6. **F4** — `<math` body guard tightening. Add the
   `\b` word-boundary and the optional error-banner negative
   check. Cheap.
7. **F5** — dry-run hit-rate reporting. Cheap label fix.
8. **F8, F9, F10** — bundle the LOWs into a single cleanup
   commit if the rectifier has budget; otherwise defer F9 + F10
   to a follow-up issue.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate. -->
