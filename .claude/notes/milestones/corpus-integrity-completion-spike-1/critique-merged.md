# Critique — corpus-integrity-completion-spike-1

**Critic:** adversary
**Generated:** 2026-05-31T23:09:40Z
**Commit range:** 297b690..2bc124b
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- The decision document's INSERT-SITE specification is materially wrong: placing the
  WAP gate "inside the existing `try:` block at lines 938-977" means the gate's
  `raise RuntimeError(...)` is SWALLOWED by the existing `except Exception` at
  `ingest/store.py:970`. The e1 implementer following the decision verbatim would
  ship a non-functional gate. (F1, CRITICAL.)
- The decision's Test plan Mutation A asserts the gate raises — but with the site
  spec from §3 the raise is swallowed, so the test would fail against the
  decision's own implementation. Internal contradiction. (F2, HIGH.)
- The decision's Test plan Mutation C ("write 'not valid json' via the marker
  monkeypatch; assert `read_corpus_version` returns None and the gate raises")
  is wrong: per `server/corpus.py:525-538`, malformed JSON raises `ValueError`,
  it does NOT return None. The gate as written would propagate the ValueError
  uncaught (well, swallowed by the surrounding except — see F1). (F3, HIGH.)
- The synthesis-time FM-10 reframing ("PARTIAL — catches fully-swallowed write")
  is correct only when no prior marker file exists at the path. On the common
  production case (subsequent `write_chunks` calls overwriting an existing
  marker), a swallowed write leaves the OLD marker; `read_corpus_version`
  returns the stale value; the gate raises with the COUNT-MISMATCH message,
  not the MISSING-marker message. The decision's §4 FM-10 row is misleading. (F4, MEDIUM.)
- 0 CRITICAL on shipped code (no code shipped); 1 CRITICAL + 2 HIGH + 3 MEDIUM + 2 LOW on the decision artifact.
- m1, m2, m3 prerequisites verified at HEAD: `docs/ops/corpus-drift-runbook.md`
  exists, `tests/_corpus_helpers.py::seed_corpus_multi_paper` exists,
  `ingest/store.py:938-953` matches the synthesis's verbatim quotes. The tier
  sequencing claim is honest.
- Claim 2 ("variant (b) false-fires on idempotent re-runs") verified against
  `ingest/bulk_ingest.py:303-325`: `chunks_written = len(chunks)` is set after
  every `write_chunks` call regardless of merge_insert upsert behavior. R2's
  analysis holds.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | decision is materially wrong; would lead e1 implementer to ship a broken gate | always fix in Phase 4 |
| HIGH | decision is incomplete or self-contradictory in a way that blocks e1 from proceeding | always fix in Phase 4 |
| MEDIUM | subtle correctness issue / latent foot-gun in the decision's claims | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, documentation polish | defer (record under `deferred_findings`) |

## Findings

### F1 — Gate placed inside try/except Exception swallows the gate's raise

- **Severity:** CRITICAL
- **Source:** adversary
- **File:** `.claude/notes/milestones/corpus-integrity-completion-spike-1/decision.md:50`
- **What:** The decision §3 "Site" specifies: *"`ingest/store.py::write_chunks`,
  immediately after `write_corpus_version_marker(...)` returns (inside the
  existing `try:` block at lines 938-977)."* But the existing try block ends
  with `except Exception as exc:` at `ingest/store.py:970` which catches ALL
  exceptions (verified by reading the file). A `raise RuntimeError(...)` placed
  inside that block — even AFTER `write_corpus_version_marker` returns — is
  caught by line 970, logged as a "could not write corpus-version.json marker"
  warning, and `write_chunks` returns the dataset_version normally.
- **Why it matters:** The entire purpose of the WAP gate is to RAISE on
  detected divergence so the caller (`ingest_one_paper` → `run_bulk_ingest`) can
  record the per-paper failure and operators see a fail-fast signal. With the
  decision's site placement, the gate never reaches the caller — it is logged
  as a best-effort marker-write warning and silently absorbed. The e1
  implementer following the decision verbatim ships a gate that catches nothing
  in production. The decision's §3 "Behavioral contract change" paragraph
  asserts "The gate raises only when divergence is detected" — false under the
  specified placement.
- **Proposed fix:** Change the §3 "Site" spec to: *"`ingest/store.py::write_chunks`,
  AFTER the existing `try/except Exception` block at lines 931-977 closes,
  before the `_append_store_stats(stats)` call at line 985."* The gate code is
  unchanged; only the placement boundary moves. Add a sentence to §3
  "Behavioral contract change" clarifying that the gate runs AFTER the
  best-effort swallow's scope has closed, so its raise propagates to the
  caller. Alternative: wrap only the `write_corpus_version_marker` call inside
  the existing try (preserving best-effort marker write), then run the gate
  unconditionally OUTSIDE the try — but the first proposal is the minimal
  edit.
- **Regression guard:** The e1 milestone's test plan must include a
  positive-control test that monkeypatches `write_corpus_version_marker` to
  raise (NOT to write a wrong value) and asserts that the OUTER WAP gate
  STILL fires (because the file either doesn't exist or has stale content),
  AND that the existing best-effort swallow's log message ALSO fired. Without
  this test, a future regression that moves the gate back inside the swallow
  goes undetected.

### F2 — Test plan Mutation A contradicts §3 site placement

- **Severity:** HIGH
- **Source:** adversary
- **File:** `.claude/notes/milestones/corpus-integrity-completion-spike-1/decision.md:95`
- **What:** Test plan Mutation A states: *"`monkeypatch.setattr(store_mod,
  "write_corpus_version_marker", lambda *a, **kw: real_marker(*a, **{**kw,
  "chunk_count": 1}))`. Assert the WAP gate raises `RuntimeError` with the
  divergence error message + diagnostic."* But with the §3 site placement
  (inside the try block), the RuntimeError from the gate is swallowed by line
  970 — `pytest.raises(RuntimeError)` on the test side would not see the
  exception, and the test would FAIL. The decision's Test plan is internally
  inconsistent with its Site specification.
- **Why it matters:** The e1 implementer will either (a) discover the
  contradiction at test-implementation time and need to escalate back to the
  spike, defeating the spike's "binding" claim; or (b) fix one of the two
  (move the gate or change the test assertion) on their own discretion,
  silently diverging from the spike's intent. The spike's value as a "binding
  implementation contract that the e1 milestone consumes" (decision §0) is
  undermined.
- **Proposed fix:** After applying F1's site move, re-verify each of the three
  mutation tests in §3 passes the new placement. Update the test plan to
  explicitly note the gate runs OUTSIDE the best-effort swallow's scope.
- **Regression guard:** N/A — the fix is documentary, but the e1 test file
  itself becomes the regression guard once it's authored.

### F3 — Test plan Mutation C asserts wrong read_corpus_version contract

- **Severity:** HIGH
- **Source:** adversary
- **File:** `.claude/notes/milestones/corpus-integrity-completion-spike-1/decision.md:97`
- **What:** Mutation C states: *"`monkeypatch.setattr(store_mod,
  "write_corpus_version_marker", lambda *a, **kw: target.write_text("not valid
  json"))`. Assert `read_corpus_version` returns None and the gate raises."*
  Per `server/corpus.py:525-538`, `read_corpus_version` does NOT return None
  for malformed JSON — it RAISES `ValueError` ("corpus-version.json at
  {marker_path} is not valid JSON: {exc}"). The only `None`-return path is
  `marker_path.is_file()` being false at line 523. The Mutation C assertion is
  wrong on the contract.
- **Why it matters:** With the gate code as written in §3 (no try around
  `read_corpus_version`), the ValueError raised by `read_corpus_version`
  propagates uncaught up the stack — it is then SWALLOWED by the outer
  `except Exception` at line 970 (F1's pathology) and logged as a marker-write
  warning. The test's `pytest.raises(RuntimeError)` fails. Even if F1 is
  fixed (gate moved outside), the ValueError still doesn't match the test's
  RuntimeError assertion. The decision needs to either wrap
  `read_corpus_version` in a try/except ValueError → re-raise as RuntimeError
  with the malformed-marker diagnostic, OR change Mutation C to write a JSON
  with a wrong chunk_count instead of malformed JSON.
- **Proposed fix:** Choose ONE of two paths and document it in §3:
  1. Add a third `if`-arm to the gate code: `except ValueError as exc:
     raise RuntimeError(f"WAP gate: corpus-version.json marker at
     {target_path} is malformed: {exc}. ...") from exc`. This catches FM-3
     atomic-rename-truncation (which produces malformed JSON) explicitly.
  2. Drop Mutation C from the test plan; Mutation A (wrong chunk_count) is
     already structurally equivalent to FM-3 from the gate's perspective
     because both cause the count comparison to mismatch IF the JSON parses.
- **Regression guard:** If path 1 is chosen, add a fourth mutation test:
  monkeypatch the marker writer to `lambda *a, **kw: target.write_text("not
  valid json")` and assert RuntimeError is raised with "malformed" in the
  message.

### F4 — FM-10 reframing only holds on the cold-start path

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `.claude/notes/milestones/corpus-integrity-completion-spike-1/decision.md:118` (synthesis §5 also)
- **What:** The decision §4 FM-10 row claims: *"Swallowed marker-write
  exception — `read_corpus_version` returns None, MISSING-marker error
  raises."* This holds only when no marker file existed at the path before
  the swallowed write. On the production-common path (second+ `write_chunks`
  call on a dataset that already has a marker from prior runs), a swallowed
  marker write leaves the PREVIOUS marker on disk. `read_corpus_version`
  returns the stale `CorpusVersionInfo`; the gate fires on the count-mismatch
  arm (stale `chunk_count` ≠ fresh `count_rows()`), not the MISSING-marker
  arm. The gate STILL fires — the synthesis's coverage claim is correct in
  net — but the synthesis's claim about WHICH error message fires and WHAT
  the operator sees is wrong for the common case.
- **Why it matters:** The decision's runbook-friendliness argument hinges on
  the operator reading the error message and immediately knowing it's a
  marker-write swallow. With the stale-marker case, they see "marker reports
  X but tbl.count_rows()=Y" and reach for the wrong remediation (marker
  arithmetic regression hunt) instead of the right one (transient I/O failure
  swallowed by best-effort contract). This is also an observability hole that
  blocks the e1 implementer from writing a fully-honest §4 failure-mode table.
- **Proposed fix:** Update §4 FM-10 row to: *"PARTIAL — on a fresh dataset
  the MISSING-marker error fires; on a dataset with a prior marker the
  COUNT-MISMATCH error fires (operator's diagnostic path requires a sweep
  through the best-effort swallow's logged warning to detect this case
  cleanly)."* Optionally extend the gate's error messages to include "(check
  the preceding log line for a 'could not write corpus-version.json marker'
  warning that may indicate this is a swallowed-write rather than an
  arithmetic regression)."
- **Regression guard:** Add a fifth mutation test: pre-seed the marker with
  a stale chunk_count (e.g. via `seed_corpus_multi_paper(n=2)` + manual
  marker rewrite), then run a third `write_chunks` whose
  `write_corpus_version_marker` is monkeypatched to raise; assert the gate
  fires with the count-mismatch message AND assert the swallow's warning was
  logged.

### F5 — read_corpus_version import direction unverified at decision time

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `.claude/notes/milestones/corpus-integrity-completion-spike-1/decision.md:132`
- **What:** §5 estimated effort: *"a brief import of `read_corpus_version`
  from `server.corpus` if not already imported in `ingest/store.py`; the e1
  implementer must verify the import direction is acceptable per the
  project's module-dependency graph."* The decision punts this verification
  to the e1 implementer. Verified at HEAD: `ingest/bm25_indexer.py:87`
  already does `from server.corpus import open_chunks_table`, so the
  `server → ingest` boundary is bidirectional in practice — the import IS
  acceptable. The decision could have pinned this finding and saved e1 the
  side-task.
- **Why it matters:** A spike's job is to remove unknowns. Leaving "verify
  the import direction" as a punt for e1 means e1 wastes time on a
  precondition the spike already had the codebase access to confirm.
  Low-friction but real.
- **Proposed fix:** Add a one-line note to §3 "Code" or §5: *"Import
  direction verified: `ingest/bm25_indexer.py:87` already imports from
  `server.corpus`, establishing the precedent. The new import in
  `ingest/store.py` is consistent."*
- **Regression guard:** N/A.

### F6 — Decision points operators to runbook section that doesn't exist

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `.claude/notes/milestones/corpus-integrity-completion-spike-1/decision.md:72` (and 82)
- **What:** Both gate error messages cite *"Runbook:
  docs/ops/corpus-drift-runbook.md."* Verified at HEAD: the runbook exists
  but covers only the two Prometheus-alert-triggered scenarios
  (`ArXMCPCorpusCountRowsFailed`, `ArXMCPCorpusUnindexedRows`). There is no
  section for "WAP gate raised `RuntimeError` during `write_chunks`." An
  operator following the error message's pointer arrives at a runbook that
  doesn't mention their actual failure path. They will reach for
  `make reconcile` (which IS correctly named in the message) and try to
  reverse-engineer the rest.
- **Why it matters:** The decision's "operator-actionability" claim in §3
  ("sufficient for a 2am-pager scenario") is overstated if the runbook
  pointer leads to a runbook that doesn't cover the case. This is fixable
  by either (a) the e1 milestone authoring a new "WAP gate raised" section
  in the runbook as part of its work, or (b) the spike acknowledging the
  runbook extension as part of the binding contract for e1.
- **Proposed fix:** Add a §3 sub-bullet under "Operator-actionability": *"e1
  also extends `docs/ops/corpus-drift-runbook.md` with a new section for the
  WAP-gate `RuntimeError` failure path: diagnosis = check the preceding
  swallow-warning log line; remediation = `make reconcile`; preserve the
  staging LanceDB so the operator can inspect the divergence."*
- **Regression guard:** The e1 milestone's PR should include both the gate
  code AND the runbook section in the same commit — no separate-tracker
  drift.

### F7 — "No (b) variant ever ships" is overstated

- **Severity:** LOW
- **Source:** adversary
- **File:** `.claude/notes/milestones/corpus-integrity-completion-spike-1/decision.md:138`
- **What:** §6 says: *"No (b) variant ever ships — the idempotent-re-run
  false-positive landmine is structural."* The very next sentence walks back
  the "ever" by acknowledging a `chunks_written_distinct` field on
  `WriteStats` would make it viable. "Ever" overstates the bind — what's
  actually true is "no (b) variant ships within the
  corpus-integrity-completion epic." Future-binding the language at "ever"
  invites a future agent to re-litigate the spike when the chunks_written_distinct
  shape is contemplated, instead of reading the spike's exact scope.
- **Why it matters:** Calibration matters for the spike's "binding" claim.
  Over-binding at "ever" cheapens the actually-binding claim of "not in this
  epic." Same calibration hygiene as severity inflation: once "ever" stops
  meaning ever, the synthesizer's other strong claims weaken too.
- **Proposed fix:** Replace *"No (b) variant ever ships"* with *"No (b)
  variant ships in the corpus-integrity-completion epic; future work that
  needs caller-arithmetic detection would route through a
  `chunks_written_distinct` field on `WriteStats` and is out-of-scope here."*
- **Regression guard:** N/A.

### F8 — Decision is silent on always-on vs config-flagged gate

- **Severity:** LOW
- **Source:** adversary
- **File:** `.claude/notes/milestones/corpus-integrity-completion-spike-1/decision.md` (no section)
- **What:** The decision specifies the code, the test plan, the operator
  message, the runbook pointer, the failure-mode coverage — but is silent on
  whether the gate runs unconditionally or behind a feature flag (e.g.
  `ARXMCP_WAP_GATE_ENABLED=1`). For a write-time correctness gate this is
  almost certainly fine to ship unconditionally — but the decision being
  silent leaves the e1 implementer to guess. Confirmed at HEAD: no other
  gate in `ingest/store.py` is feature-flagged, so the precedent argues
  for unconditional. But the spike should pin the question explicitly to be
  fully binding.
- **Why it matters:** "Binding" decisions remove guesswork. A silent
  question is one the e1 implementer has to ask back to the user or guess.
- **Proposed fix:** Add a §3 sub-bullet: *"The gate is unconditional (no
  feature flag). Precedent: no other gate in `ingest/store.py` uses a
  flag; the m1 marker-write itself is unconditional. A future need to
  disable the gate for a specific operator scenario (e.g. mid-migration
  spurious divergences) is out-of-scope for e1."*
- **Regression guard:** N/A.

## What was done well

- Both researchers independently caught DIFFERENT load-bearing problems with
  the roadmap's pre-recommendation of (c) — this is exactly the value
  proposition of running two parallel researchers and the synthesis honestly
  surfaces the convergence (decision §2 problems 1 and 2).
- The decision's refutation of the roadmap's pre-recommendation of (c) is
  intellectually honest: it doesn't paper over the disagreement; it walks
  the reasoning end-to-end with codebase line citations
  (`ingest/store.py:938-953` quoted verbatim).
- Claim 2 (the merge_insert idempotency / variant-(b) false-positive) is
  verifiable by tracing through `ingest/bulk_ingest.py:303-325` —
  `chunks_written = len(chunks)` is set after every write_chunks regardless
  of sidecar short-circuit. R2's analysis holds against the actual code.
- The tier-sequencing claim is honest: `docs/ops/corpus-drift-runbook.md`
  exists at HEAD (m2 deliverable), and
  `tests/_corpus_helpers.py::seed_corpus_multi_paper` exists at HEAD (m3
  deliverable). The decision's references to prior milestones are grounded.
- The synthesis surfaces the R1/R2 disagreement explicitly in §4 and walks
  through how R1's escape hatch collapses into (a) — this is the kind of
  honest reasoning that distinguishes a good synthesis from a soft "split
  the difference" punt.
- The R1's tautology refinement IS load-bearing and IS correct: the
  pre-spike literal "second `count_rows()`" recommendation from the roadmap
  was tautological under single-writer, and the spike caught it before
  e1 shipped wasted code.
- The decision document covers the operator-actionability surface
  (full lancedb path, claimed count, actual count, corpus_version, runbook
  URL, remediation command in the error message) — this is the right
  shape for a 2am-pager message, even though the runbook itself needs an
  e1-era extension (F6).
- The decision honestly enumerates the Won't list (FM-4, FM-5, FM-6,
  FM-8, FM-9, FM-11) with the reason each is out-of-scope, so the e1
  implementer doesn't waste time on coverage the spike already considered
  and rejected.
- The synthesis's R1-vs-R2 §4 walk-through is the highest-leverage piece
  of synthesis work in the artifact: it shows the surface-level
  disagreement (R1 said ship both, R2 said ship (a) only) and dissolves
  it by showing R1's (b) shape collapses to (a). This is exactly the work
  that justifies the synthesis step.

## Recommended rectification order

1. **F1 (CRITICAL)** — site placement is the load-bearing flaw; fixing it
   resolves F2 and F3's setup as a side-effect.
2. **F3 (HIGH)** — once F1 is fixed, decide which path (catch ValueError
   inside the gate, or drop Mutation C) and update §3 accordingly.
3. **F2 (HIGH)** — re-verify the three mutation tests against the new site;
   the verification is the recheck of F1+F3.
4. **F4 (MEDIUM)** — update §4 FM-10 row for the stale-marker case.
5. **F6 (MEDIUM)** — extend the binding contract to include the
   runbook section that e1 must add.
6. **F5 (MEDIUM)** — add the pre-verified import-direction note.
7. **F7 (LOW)** — narrow "ever" to "this epic."
8. **F8 (LOW)** — pin the always-on / no-flag decision.

## Rectification status

- **F1 | CRITICAL | fixed** in rect commit — decision §3 "Site" rewritten to place the gate AFTER the existing `try/except Exception` block closes (lines 931-977), before `_append_store_stats(stats)` at line 985. Behavioral-contract paragraph clarified. The gate's `raise RuntimeError(...)` now propagates to the caller instead of being silently absorbed by the swallow.
- **F2 | HIGH | fixed** in rect commit — Mutation A is now self-consistent with the F1-corrected placement. Documentary fix only.
- **F3 | HIGH | fixed** in rect commit — added `try: read_corpus_version(...) except ValueError → raise RuntimeError` arm to the gate code. Mutation C rewritten to assert the gate raises the malformed-marker error (was previously wrong about `read_corpus_version`'s contract per `server/corpus.py:525-538`).
- **F4 | MEDIUM | fixed** in rect commit — §4 FM-10 row honestly distinguishes cold-clone (MISSING-marker arm) from production-common stale-marker (count-mismatch arm). Gate error messages now cite the preceding swallow-warning log line so operators can disambiguate. Mutation D added to test plan.
- **F5 | MEDIUM | fixed** in rect commit — §5 now includes the pre-verified import-direction note: `ingest/bm25_indexer.py:87` precedent establishes `server → ingest` is acceptable.
- **F6 | MEDIUM | fixed** in rect commit — §3 Operator-actionability section binds e1 to extend `docs/ops/corpus-drift-runbook.md` with a "WAP-gate `RuntimeError` failure path" section in the same commit.
- **F7 | LOW | fixed** in rect commit — §6 narrowed "No (b) variant ever ships" → "No (b) variant ships in the corpus-integrity-completion epic."
- **F8 | LOW | fixed** in rect commit — §3 now explicitly says "The gate is unconditional (no feature flag)" with precedent rationale.

**Re-verify gate:** Both HIGHs + the CRITICAL re-verified pre-fix:
- F1: `ingest/store.py:925-990` confirmed; the `try:` at line 931 + `except Exception as exc: logger.error(...)` at 970-976 would have swallowed the gate's raise. Adversary claim accurate.
- F3: `server/corpus.py:525-538` confirmed; `read_corpus_version` raises `ValueError` on malformed JSON, returns None only for missing files. Adversary claim accurate.

Invalidation rate: 0/8. The CRITICAL finding being caught reflects HIGH-VALUE adversary work — without the catch, the e1 implementer following the pre-rect decision verbatim would have shipped a structurally non-functional gate (the gate's raise absorbed by the surrounding swallow, the test silently passing without exercising real divergence detection).
