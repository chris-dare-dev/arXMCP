# Critique — corpus-integrity-completion-m2

**Critic:** adversary
**Generated:** 2026-05-31T00:00:00Z
**Commit range:** `5a8c7f0..653986a`
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES — the 5 AC sections are present and operator-correct in
  the main flow, but the runbook prescribes a non-existent `make down`
  target on the primary remediation path and propagates a broken
  cross-reference anchor (`failure-modes.md#degraded-modes`) three times.
  At 2 a.m. an operator hitting this runbook will trip on the first
  command of Remediation.
- Counts: 0 CRITICAL, 2 HIGH, 4 MEDIUM, 3 LOW.
- Highest-risk citation: `docs/ops/corpus-drift-runbook.md:145` — the
  S1/S7 Remediation step 1 says `make down` but `Makefile` exposes no
  such target (only `up`, `up-wizard`, `status`, `ingest`, ...).
- AC-3 deviation (Common tasks → Operations table) is sound and
  CLAUDE.md-§1-grounded; not flagged.
- The `corpus-version.json` "safe to attach to a public issue" claim
  IS verified against `ingest/store.py::write_corpus_version_marker`
  (chunk_count + chunker_version + created_at ISO timestamp +
  embedder_version + paper_count + version — no operator PII). The
  more interesting risk is what the runbook does NOT say about the
  journalctl capture's sensitivity.
- The runbook structure (Symptom / Quick triage / Likely causes /
  Remediation / Escalation) diverges from the 4-part
  Symptoms/Detection/Steps/Verification skeleton that
  `docs/ops/README.md` declares mandatory — but m2 added a row to that
  index without flagging or reconciling the divergence.
- Cross-checked against `infra/prometheus/alerts.yml`: alert names,
  expressions, severities, and `for:` windows match byte-for-byte.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — `make down` is prescribed but not a real Makefile target

- **Severity:** HIGH
- **Source:** adversary
- **File:** `docs/ops/corpus-drift-runbook.md:145, 193`
- **What:** The S1/S7 remediation step 1 says `make down   # or pkill -f
  'python -m server.main' if no Make target` (line 145), and the S2
  remediation says `make down && make up` with no hedge (line 193). I
  searched the Makefile end-to-end (`grep -n "^down:\|^down " Makefile`
  → no output). The Makefile targets that ship are `up`, `up-wizard`,
  `status`, `ingest`, `delta`, ..., `reconcile` (and ~30 others) — no
  `down`. The hedge on line 145 admits this ("if no Make target") but
  line 193 doesn't, and presenting `make down` as the primary command
  is misleading at 2 a.m.
- **Why it matters:** An operator running the runbook top-to-bottom hits
  `make: *** No rule to make target 'down'. Stop.` on the very first
  remediation command. The runbook then says "Re-trigger the triage
  commands to confirm" (step 5) — but step 1 failed, so the operator is
  stuck reasoning about whether the failure was intentional. The fact
  that line 145 has a parenthetical "or pkill" hedge proves the author
  KNEW `make down` might not exist; the right fix is to make `pkill`
  the primary or to add a `make down` target. Line 193 has NO hedge at
  all.
- **Proposed fix:** Either (a) add a `down:` target to `Makefile`
  (probably out of scope for this milestone — it's a Make change, not a
  docs change, and would route through infra-safety), OR (b) rewrite
  lines 145 and 193 to lead with the `pkill -f 'python -m server.main'`
  form and drop the `make down` reference. Option (b) is the
  docs-only fix and is the right scope for this milestone. If (a) is
  pursued, also add a row to README §Operations and a regression test
  that the target exists.
- **Regression guard:** Add a one-line assertion in
  `tests/test_ops_runbooks.py` (or wherever runbook content is
  validated) — or a simple `make -n down` check in the project test
  collection — that confirms every Makefile target named in the
  Remediation code blocks resolves. Cheapest: a regex scan for
  ``\bmake (\w[\w-]*)`` in `docs/ops/corpus-drift-runbook.md` and an
  assertion that each captured target name is in `make -p` output.

### F2 — Three runbook links point at a non-existent anchor (`failure-modes.md#degraded-modes`)

- **Severity:** HIGH
- **Source:** adversary
- **File:** `docs/ops/corpus-drift-runbook.md:20, 124, 265`
- **What:** The runbook references `failure-modes.md#degraded-modes` in
  three places: line 20 (the "does not cover" callout), line 124 (S3
  out-of-scope pointer), and line 265 (See also block). I read
  `docs/ops/failure-modes.md` end-to-end (`grep "^## "` → 13 H2s) — the
  closest matches are `## Hosted-embedder outage` (#hosted-embedder-outage)
  and `## LanceDB corruption` (#lancedb-corruption). There is NO
  `## Degraded modes` section, so no GitHub-auto-anchor `#degraded-modes`
  exists. Note: `infra/prometheus/alerts.yml:58` (the
  `ArXMCPDegradedMode` rule's `runbook_url`) uses the SAME broken
  anchor, so this is partly a pre-existing m1-era bug — but m2 added
  three NEW broken-anchor references rather than fixing the upstream
  issue.
- **Why it matters:** When an operator's `ArXMCPDegradedMode` alert
  fires with `reason="chunk_count_diverged"` and they click the link
  from this runbook, GitHub renders the page but the anchor doesn't
  jump — they land at the top of a 257-line file with no idea which
  section is relevant. The runbook explicitly directs S3-symptom
  operators to this anchor as the "Fix via `make reconcile`" route, so
  the broken link masks the actual remediation path. This is the named
  "broken operator cross-ref" failure mode the prompt flagged.
- **Proposed fix:** Either (a) update `failure-modes.md` to add a
  `## Degraded modes` section (or a `## ArXMCPDegradedMode` section,
  matching the alert name) — out of scope for m2 by AC-4 (which says
  no edits to the 4 other runbooks; but `failure-modes.md` IS one of
  the 4), OR (b) change the three references to point at a real
  anchor. The 13 existing H2s include `## LanceDB corruption` —
  acceptable substitute, since `chunk_count_diverged` is a corpus
  divergence not a mode. Recommend: rewrite the three links as
  `failure-modes.md#lancedb-corruption` OR drop the anchor entirely
  and let GitHub land the operator on the table-of-contents at the
  top of failure-modes.md.
- **Regression guard:** Add to `tests/test_ops_runbooks.py` (new file
  if needed) a single function that scans every `[text](file.md#anchor)`
  reference in `docs/ops/corpus-drift-runbook.md` and validates the
  anchor resolves to a heading in the target file (GitHub's
  slugification rule: lowercase, `-` for spaces, drop punctuation). 

### F3 — Escalation step's journalctl capture leaks operator state without a redaction warning

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `docs/ops/corpus-drift-runbook.md:244, 246-249, 254-257`
- **What:** Escalation step 1 captures three files (`/tmp/marker.json`,
  `/tmp/gauges.txt`, `/tmp/startup.log`) and step 3 directs the
  operator to "Open an issue at <github.com/.../issues>" attaching
  "the captured state". The runbook explicitly clears the marker file
  as "not sensitive" per the threat model — that claim verifies
  against `ingest/store.py:746-755` (marker schema is chunk_count,
  chunker_version, created_at, embedder_version, paper_count, version
  — no PII; created_at is just an ISO timestamp). BUT the runbook
  makes no equivalent statement about `/tmp/startup.log`. Per
  `.claude/notes/08-security-observability-ops.md:214`, "Sensitive
  fields (full query text, chunk bodies) are logged at DEBUG only,
  never at INFO or above" — meaning at INFO+ the log slice IS
  generally safe, but operators raise verbosity to DEBUG during
  troubleshooting (which is exactly the state they're in when reading
  the runbook). The 30-minute slice could include user-submitted MCP
  query strings under that DEBUG path.
- **Why it matters:** A public-issue attachment of a
  DEBUG-verbosity startup log can leak operator search queries,
  partial chunk bodies, and absolute filesystem paths (the
  `server/parse_tracker.py` / `server/ingest_tracker.py`
  path-redaction infrastructure exists for exactly this concern —
  see `server/parse_tracker.py:79 _redact_path_prefix`). The runbook
  presents the journalctl capture as a routine snapshot with no
  redaction reminder.
- **Proposed fix:** Add a sentence after the `journalctl ...` line:
  > **Before attaching `/tmp/startup.log` to a public issue, scan for
  > DEBUG-level entries containing full query strings or chunk bodies
  > (sensitive per `.claude/notes/08-security-observability-ops.md`
  > §Logging) and absolute home-directory paths. Redact or attach to
  > a private channel if found.**
  No code change required; add this to the Escalation section in
  the m2-shipped runbook.
- **Regression guard:** None (operator-doc finding). If a future
  milestone formalizes a `tools/redact_startup_log.py` helper, link
  it here.

### F4 — Runbook diverges from `docs/ops/README.md` "every runbook follows the same 4-part skeleton" claim

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `docs/ops/README.md:66-67` vs `docs/ops/corpus-drift-runbook.md:24,46,80,132,233`
- **What:** `docs/ops/README.md` lines 66-73 say: "Every runbook
  follows the same 4-part skeleton: **Symptoms → Detection → Steps
  → Verification**" and "If a runbook needs to deviate from this
  skeleton ... the index entry calls that out explicitly." The new
  corpus-drift-runbook.md uses the m1-AC-mandated 5-part skeleton
  (Symptom / Quick triage / Likely causes / Remediation /
  Escalation). The m2-shipped row 9 in the README table does NOT
  call out the deviation. This is a documented-elsewhere structural
  inconsistency the milestone propagates without flagging.
- **Why it matters:** The runbook index's convention statement now
  has a counter-example without an explanation. An operator
  reading the index expects 4 sections and finds 5; an author
  following the index's convention writes 4 sections for a future
  runbook and discovers the 5-section pattern only after seeing
  the corpus-drift runbook. Not a runtime bug; a documentation
  invariant the milestone silently invalidates.
- **Proposed fix:** Either (a) update `docs/ops/README.md:64-77` to
  acknowledge that some runbooks (latexml-drift-runbook.md and now
  corpus-drift-runbook.md) use a 5-section schema mapped to the
  4-part conceptual skeleton (Symptom → Symptoms; Quick triage +
  Likely causes → Detection; Remediation → Steps; Escalation
  doesn't map cleanly, but it's still a section), OR (b) add a
  one-line index-row callout: "Uses the 5-section operator-alert
  pattern (Symptom / Quick triage / Likely causes / Remediation /
  Escalation); see the runbook header."
- **Regression guard:** None at this severity. If the team formalizes
  a runbook-skeleton lint, this is the case it must allow.

### F5 — Line citations in Remediation steps point at metric declarations, not the cited behavior

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `docs/ops/corpus-drift-runbook.md:164-165, 191`
- **What:** Step 4 of "Fix S1/S7" says "Successful startup clears the
  cached -1 from the gauge (which is read once at startup; see
  server/health.py:111-120)." Step 2 of "Fix S2" says "the gauge is
  cached at startup (see server/health.py:122-134)." Real lines
  111-120 are the `CORPUS_CHUNK_COUNT_ACTUAL = Gauge(...)`
  declaration block; lines 122-134 are the `CORPUS_UNINDEXED_ROWS =
  Gauge(...)` declaration block. Neither line range contains the
  "read once at startup" caching/setting logic the runbook is
  citing — that's `Resources.startup` (elsewhere in `server/`).
- **Why it matters:** A reader who clicks through to verify the
  claim finds a Prometheus `Gauge()` constructor call, not the
  "read once at startup" code. The runbook's verifiability is
  reduced; an operator who needs to understand why a restart is
  required to re-read the gauge has to keep grepping. Not
  operator-blocking but it's a small-credibility hit on a runbook
  whose value comes from precision.
- **Proposed fix:** Either drop the line citations entirely (the
  prose claim "read once at startup" is sufficient and the gauge
  docstrings on lines 115-119, 128-133 already say so), or repoint
  them at the `Resources.startup_chunk_count` /
  `Resources.startup_unindexed_rows` setter sites (which is what's
  actually load-bearing). Cheapest: replace
  `(see server/health.py:111-120)` with `(see the
  CORPUS_CHUNK_COUNT_ACTUAL docstring in server/health.py)` —
  no line numbers, less fragile to drift.
- **Regression guard:** None.

### F6 — S2 Likely-causes claim about `_create_indices` is right but the cross-reference is wrong

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** `docs/ops/corpus-drift-runbook.md:104-107`
- **What:** The "Rebuild-window calibration" callout says: "see the
  `latexml-drift-runbook.md` §"Timing estimates" table for the
  per-corpus-size wall-clock numbers used to pick this." I read
  `docs/ops/latexml-drift-runbook.md` (grep `^## \|^### \|Timing`):
  line 103 contains `**Timing estimates:**` (a bold inline label, not
  an H3 heading). It's NOT a `§"Timing estimates"` section — it's a
  bold paragraph inside Step 3. GitHub will not produce a clean
  `#timing-estimates` anchor for it (bold inline isn't a heading),
  so a reader trying to follow the cross-reference has to scroll.
  More importantly: the m1-IS2 closure justification ("for: 1h
  window is sized to filter post-full-ingest rebuild windows at
  full scale") is built on this reference, and the linked content
  is in fact about LaTeXML re-rendering wall-clock, NOT HNSW
  rebuild wall-clock — two different operations with different
  per-paper costs.
- **Why it matters:** The IS2 closure depends on a citation that
  (a) doesn't point at an anchored section and (b) points at the
  WRONG timing table conceptually (LaTeXML re-render is N×
  per-paper LaTeXML; HNSW rebuild is one bulk index build). The
  numeric defense of `for: 1h` is unsupported by the cited source.
- **Proposed fix:** Either (a) add a real `### Timing estimates`
  H3 to the relevant section of `latexml-drift-runbook.md`
  (out-of-scope per AC-4), OR (b) rewrite the callout to cite the
  actual mechanism: "the 1h window is empirically the rough
  upper-bound for a bulk `_create_indices` rebuild on the 200K
  corpus (HNSW index, M=16, efConstruction=200 defaults); reduce
  to 10m on the 50-paper seed corpus if false-positive noise
  appears." Drop the latexml-drift cross-ref.
- **Regression guard:** None operator-facing; the implementation
  summary's m1-IS2 closure narrative should be updated to reflect
  the cross-ref correction.

### F7 — Runbook claims default LanceDB path that is wrong for `ARXMCP_NOTEBOOK`-mode deployments

- **Severity:** LOW
- **Source:** adversary
- **File:** `docs/ops/corpus-drift-runbook.md:63, 149-150, 158`
- **What:** Multiple commands hard-code `var/arxmcp/index/lancedb/`
  as the dataset path (e.g. `cat var/arxmcp/index/lancedb/corpus-
  version.json` on line 63, `ls -la
  var/arxmcp/index/lancedb/_versions/` on line 149). When the
  server is launched with `ARXMCP_NOTEBOOK=<slug>` (the
  notebook-retrieval-m1 fork-C deployment mode), `server/config.py`
  rewrites `lancedb_path` to `var/arxmcp/notebooks/<slug>/lancedb`
  (see `server/config.py:95-118`). The runbook acknowledges this
  partially: "the m2 alerts fire on the shared corpus gauges" (line
  217-218). But the alerts CAN fire on a notebook-mode deployment
  if that's the operator's setup — the `arxmcp_corpus_*` gauges
  read whatever `lancedb_path` the running process resolved to.
- **Why it matters:** A notebook-mode operator follows the runbook,
  runs `cat var/arxmcp/index/lancedb/corpus-version.json`, gets
  "No such file or directory", and thinks the marker is missing —
  but really it's at `var/arxmcp/notebooks/<slug>/lancedb/
  corpus-version.json`. Confuses the diagnosis.
- **Proposed fix:** Add a one-line note at the top of Quick triage:
  > **Path note:** All paths below use the shared-corpus default
  > (`var/arxmcp/index/lancedb/...`). If the server was launched
  > with `ARXMCP_NOTEBOOK=<slug>`, replace
  > `var/arxmcp/index/lancedb` with `var/arxmcp/notebooks/<slug>/
  > lancedb` everywhere.
- **Regression guard:** None.

### F8 — `make reconcile` expected stdout block uses fabricated numbers

- **Severity:** LOW
- **Source:** adversary
- **File:** `docs/ops/corpus-drift-runbook.md:223-226`
- **What:** The runbook shows:
  > ```
  > reconcile-marker [shared]: version=42 before=10298 chunks / 217 papers
  >   after=10298 chunks / 217 papers drift_resolved=0
  > ```
  I confirmed via `tools/notebook_reconcile_marker.py:140-143` that
  the format string IS correct (`version=`, `before=`, `after=`,
  `drift_resolved=` are real). The specific numbers (`version=42`,
  `chunks=10298`, `papers=217`) are illustrative and not from any
  fixture — fine. But the example shows `drift_resolved=0` which is
  the no-op case; the runbook is telling the operator "this is what
  success looks like" but the OPERATOR ran this BECAUSE there was
  drift. The first real run will show `drift_resolved=<non-zero
  int>` and an operator may pause and wonder if `0` was the only
  acceptable success indicator.
- **Why it matters:** Minor UX confusion. If the operator ran
  `make reconcile` precisely because they expected drift, seeing
  `drift_resolved=42` is the SUCCESS signal, not a failure. The
  example should show that case.
- **Proposed fix:** Change the example to show a non-zero
  `drift_resolved` (e.g. `drift_resolved=12`) since that's the
  more diagnostic case, OR add a one-liner: "On a real run
  resolving drift you'll see `drift_resolved=<n>` where n > 0;
  exit code 0 still means success."
- **Regression guard:** None.

### F9 — Quick-triage "third command" assumes the operator hasn't broken the marker

- **Severity:** LOW
- **Source:** adversary
- **File:** `docs/ops/corpus-drift-runbook.md:62-63`
- **What:** Quick triage step 3 runs `cat
  var/arxmcp/index/lancedb/corpus-version.json` with no error
  handling. The very symptom the runbook is for (S3 — operator
  manually deleted `corpus-version.json`, the explicitly out-of-
  scope case) produces `cat: ...: No such file or directory`.
  Less common but possible. The runbook then explicitly says
  this case (S3) should redirect to ArXMCPDegradedMode, but the
  Quick triage step itself doesn't disambiguate — a `cat` error
  is silently treated as data.
- **Why it matters:** This is genuinely a "scope-drift" symptom
  (the runbook routes S3 out of scope, but Quick triage doesn't
  detect S3 from this command alone). At 2 a.m. an operator
  who hits a cat error on step 3 has to reason about whether
  they're in S3 territory and switch runbooks. The runbook's S3
  out-of-scope text is in `## Likely causes`, AFTER `## Quick
  triage`. The reading order is wrong for routing-by-symptom.
- **Proposed fix:** Wrap the `cat` in `if-test`:
  ```bash
  if [ ! -f var/arxmcp/index/lancedb/corpus-version.json ]; then
    echo "marker missing — see failure-modes.md (ArXMCPDegradedMode)"
  else
    cat var/arxmcp/index/lancedb/corpus-version.json
  fi
  ```
  Or just add a one-liner: "If the marker file is missing,
  you're hitting `ArXMCPDegradedMode`, not these alerts — see
  the out-of-scope note at the bottom of Likely causes."
- **Regression guard:** None.

## What was done well

- **AC-3 deviation is well-grounded.** The AC-literal "Common tasks"
  section does not exist in README; adding an orphan H2 would have
  violated CLAUDE.md §1's README scope restriction. The implementation
  summary documents the reasoning with two cross-verified research
  briefs. Adding the row to the existing `## Operations` runbook
  table (which IS the natural home for runbook entries) is the
  minimum-coherent reading of the AC's intent.
- **Symmetric addition to `docs/ops/README.md`.** Every other runbook
  in the main README table also appears in `docs/ops/README.md`'s
  runbook index. Extending both surfaces avoids the asymmetry where
  the dedicated runbook index would be silently incomplete.
- **5-part skeleton implements the literal AC structure.** H2 sections
  `## Symptom`, `## Quick triage`, `## Likely causes`, `## Remediation`,
  `## Escalation` appear in the literal order specified by AC-1.
- **Per-alert H3 nesting preserves discoverability.** Inside Symptom,
  Quick triage, and Remediation, separate H3 subsections distinguish
  the two alerts — clean for an operator who knows which alert fired.
- **Out-of-scope S3/S4 callout closes the misattribution gap.** The
  explicit "S3 → ArXMCPDegradedMode, not these alerts; S4 → empty
  corpus, not -1" routing prevents operators from running the wrong
  remediation when their alert is a sibling failure mode.
- **`corpus-version.json` "not sensitive" claim is verified.** I
  checked `ingest/store.py:746-755` — the marker schema contains only
  chunk_count + chunker_version + created_at ISO timestamp +
  embedder_version + paper_count + version. No paths, hostnames, or
  user identifiers. The runbook's public-issue claim is accurate for
  the marker.
- **m1-IS2 closure is delivered.** The `## Likely causes` → S2 block
  cites both the 50-paper-seed and 200K-full timing bands and ties
  the `for: 1h` window to the rebuild-time upper bound. (The exact
  cross-reference target is wrong — see F6 — but the substantive
  IS2 closure is present.)
- **`tests/test_alerts_yaml.py:138-165` continues to validate the
  runbook_url prefix.** The runbook URL annotation on both alerts
  in `infra/prometheus/alerts.yml` still resolves to the (now
  canonical) `docs/ops/corpus-drift-runbook.md` and the prefix
  `https://github.com/chris-dare-dev/arXMCP/blob/main/docs/ops/`
  still matches. No re-pin required.
- **Asymmetry in `make reconcile` routing is documented.** The
  callout on lines 209-213 explains that `make reconcile` for the
  shared corpus falls back to the CLI even when the server is up
  (no per-shared-corpus REST endpoint) — closes a confusion path
  the m1 R1 brief explicitly identified.
- **No edits to the 4 other pre-existing runbooks (AC-4 met).** Diff
  confirms only corpus-drift-runbook.md was rewritten;
  failure-modes.md, backup-restore.md, drift-watchdog.md, and
  latexml-drift-runbook.md are untouched.

## Recommended rectification order

1. **F1 (HIGH, `make down`).** Cheapest fix: replace `make down` on
   lines 145 and 193 with `pkill -f 'python -m server.main'` as the
   primary form. Eliminates the "first command fails" path. ~6
   lines of diff.
2. **F2 (HIGH, broken `#degraded-modes` anchor).** Replace the three
   references with `failure-modes.md` (no anchor) or
   `failure-modes.md#lancedb-corruption`. 3 lines of diff.
3. **F3 (MEDIUM, journalctl redaction warning).** Add the redaction
   sentence in Escalation step 1. ~4 lines of diff.
4. **F6 (MEDIUM, S2 cross-reference).** Rewrite the m1-IS2 closure
   to cite the HNSW rebuild path rather than the LaTeXML re-render
   path. ~6 lines of diff.
5. **F4 (MEDIUM, 4-vs-5-part skeleton).** Add the one-line
   structure callout to `docs/ops/README.md` row 9 OR to the
   convention statement. ~3 lines of diff. (Bigger refactor would
   be out of scope.)
6. **F5 (MEDIUM, line-citation drift).** Drop the
   `server/health.py:111-120` / `:122-134` numbers; cite the
   docstring instead. ~4 lines of diff.
7. **F7, F8, F9 (LOW).** Defer to a future docs-polish sweep.

## Rectification status

- **F1 | HIGH | fixed** in rect commit — replaced both `make down` references with `pkill -f 'python -m server.main'`. Inline comments document the missing-target reason.
- **F2 | HIGH | fixed** in rect commit — all three `failure-modes.md#degraded-modes` references rewritten as bare `failure-modes.md` with a parenthetical noting the anchor was missing per rect F2.
- **F3 | MEDIUM | fixed** in rect commit — Escalation step 1 carries a redaction-warning callout naming DEBUG-patterns to grep for, citing `.claude/notes/08-security-observability-ops.md` §Logging. Added a `docker logs` alternative for non-systemd deployments.
- **F4 | MEDIUM | fixed** in rect commit — `docs/ops/README.md` row 9 carries an inline `**Note:**` callout explaining the 5-section schema vs the index's 4-part skeleton.
- **F5 | MEDIUM | fixed** in rect commit — line-number citations replaced with docstring references (`CORPUS_CHUNK_COUNT_ACTUAL` and `CORPUS_UNINDEXED_ROWS`); less fragile.
- **F6 | MEDIUM | fixed** in rect commit — IS2 closure rewritten to cite the HNSW rebuild path (`M=16`, `efConstruction=200` defaults) rather than the LaTeXML re-render path; latexml-drift cross-ref dropped.
- **F7 | LOW | deferred** — `ARXMCP_NOTEBOOK` path note; tracked in state.json `follow_ups`.
- **F8 | LOW | deferred** — `drift_resolved=0` example UX nit; tracked in `follow_ups`.
- **F9 | LOW | deferred** — Quick-triage `cat` error-handling; Likely-causes out-of-scope text already routes S3-symptom operators correctly. Tracked in `follow_ups`.

**Re-verify gate:** All findings re-verified pre-fix (`make down` absent from Makefile; `failure-modes.md` has no `## Degraded modes` H2; `latexml-drift-runbook.md` has `**Timing estimates:**` as a bold paragraph, not a heading). Invalidation rate: 0/9. The single critic (infra-safety did not fire — no infra path in diff) calibrated cleanly.
