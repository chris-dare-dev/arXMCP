# Critique — onboarding-uplift-m3

**Critic:** adversary
**Generated:** 2026-05-31T00:00:00Z
**Commit range:** b66fa1e58fe2ee66f48ec4a73831624a9062bccf..72d5e183463dab323082bc08ad1438bda262ba18
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- One MEDIUM finding (absolute path leak in `reconcile-marker` 422
  responses) drifts from the project's `redact_paths` precedent
  (`server/ingest_tracker.py:81`, used by parse tracker per memory
  `parsed-path-leak-vs-m9-redact-precedent`); inconsistent with the
  sibling `notebook_health` 422 path that already redacts.
- One LOW dead-code finding (`_DEFAULT_DB_PATH` defined but never read
  in `tools/notebook_repair_registry.py:46`); one LOW double-aria-live
  finding (nested `<small>` aria-live inside parent `<span>` with
  aria-atomic="true"); one LOW docstring/test-count drift (summary
  claims 26 endpoint tests; actual count is 25).
- Highest-risk file:line: `server/routes/notebooks.py:936-942` (path
  leak in 422 details).
- Cache discipline holds: `tests/test_server_tool_schema.py` +
  `tests/test_prompts.py` pass; `EXPECTED_TOOL_SCHEMA_SHA256` +
  `EXPECTED_BP1_SHA256` UNCHANGED. The structural `TestNoMCPSurfaceTouch`
  guard at `tests/test_m3_endpoints.py:541` adds a defense-in-depth
  grep against the m3 modules touching `server.tools`.
- MVCC pinned-checkout claim verified: `server/corpus.py:299-313`
  performs `tbl.checkout(version)` and `tests/test_mvcc.py::TestVersionPinning::test_checkout_pre_and_post_second_write`
  is the live contract. The recount handlers correctly pass
  `version=old_info.version`, never `None`
  (`server/routes/notebooks.py:947`, `1041`).
- Atomic-rewrite contract matches canonical: tmp filename
  `f"{out_path.suffix}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"`,
  default separators, `ensure_ascii=False`, `sort_keys=True`, trailing
  `"\n"`, `os.replace`, `try/finally` cleanup — verbatim mirror of
  `ingest/store.py:755-766`. The "minified separators" deviation in
  the implementation-summary note was correctly self-corrected before
  landing.
- Cross-module helper duplication is intentional (REST handler at
  `server/routes/notebooks.py:684` + CLI at `tools/notebook_reconcile_marker.py:69`
  both implement `_write_marker_atomically`); both pass the same
  byte-identical idempotency assertion (`tests/test_m3_endpoints.py:324`
  + `tests/test_m3_cli.py:220`). No drift risk.
- Test isolation: fixture monkeypatches BOTH
  `_notebook_common.NOTEBOOKS_BASE` AND `notebooks_module.NOTEBOOKS_BASE`
  (`tests/test_m3_endpoints.py:50-51`); confirmed sufficient because
  `notebook_lancedb_path(slug)` (no `base=` kwarg) reads
  `_notebook_common.NOTEBOOKS_BASE`. No production-disk leak path
  detected.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — reconcile-marker 422 details leak absolute install path

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/routes/notebooks.py:936-937 (also :942-943)
- **What:** `reconcile_marker`'s 422 response bodies include
  `nb_lance` (an absolute resolved path) in the `detail` field:
  `f"no corpus-version.json at {nb_lance}; run `make ingest` first"`
  and `f"corpus-version.json at {nb_lance} is malformed; operator
  investigation required"`. For a developer on macOS the leaked path
  is `/Users/<username>/.../var/arxmcp/notebooks/<slug>/lancedb`,
  which surfaces the home directory and username in the JSON
  response.
- **Why it matters:** The project already established a redaction
  precedent for `var/arxmcp/`-prefixed paths in operator-facing JSON
  output: `server/ingest_tracker.py:81` defines `redact_paths`, used
  by `parse_tracker.py:284` for the `/parse-status` surface (m9 FM-4
  closure). The sibling `notebook_health` endpoint at lines 1026 +
  1038 ALREADY OMITS the path from its analogous "no corpus-version.json"
  / "malformed" details. The `reconcile_marker` handler is
  inconsistent with both — it leaks the install path while its sibling
  declines to. Loopback-only deployment caps the blast radius but does
  not zero the precedent drift. Memory note
  `parsed-path-leak-vs-m9-redact-precedent` (from m6 critique) flagged
  the same shape.
- **Proposed fix:** Replace `{nb_lance}` in both 422 details with a
  redacted form. Two clean options:
  (a) Drop the path entirely and reference the slug:
      `f"no corpus-version.json for {slug!r}; run `make ingest` first"`.
  (b) Apply `redact_paths(str(nb_lance).encode()).decode()` to scrub
      the prefix down to `var/arxmcp/`.
  Option (a) matches what `notebook_health` already does.
- **Regression guard:** Add a test
  `test_422_detail_omits_absolute_path` that POSTs against a slug with
  no marker and asserts the response detail does NOT contain `/Users/`
  or the operator's `$HOME` substring. Mirror the existing health
  endpoint's behavior pattern.

### F2 — `_DEFAULT_DB_PATH` defined but never used in CLI

- **Severity:** LOW
- **Source:** adversary
- **File:** tools/notebook_repair_registry.py:46
- **What:** `_DEFAULT_DB_PATH: Path = Path("var/arxmcp/cache/notebooks.db")`
  is declared at module level with a docstring claiming it "mirrors
  :data:`server.operator_settings.DEFAULT_DB_PATH`. Imported lazily in
  :func:`main`." Grep across the file confirms it is never read — the
  `main()` body at line 186-189 imports `DEFAULT_DB_PATH` lazily from
  `server.operator_settings` and `_DEFAULT_DB_PATH` is dead weight.
- **Why it matters:** Two sources of truth for the same constant.
  Future maintainer reading the module-level definition will assume
  it is the canonical default and may add references to it, drifting
  from `server.operator_settings.DEFAULT_DB_PATH`. Trivial to delete
  now; harder to chase the drift later.
- **Proposed fix:** Delete the `_DEFAULT_DB_PATH` line at line 46 and
  its docstring comment at lines 43-45.
- **Regression guard:** N/A (LOW; covered by ruff if it ever lands
  `F841` for module-level unused names, but the unused-name rule does
  not fire at module scope).

### F3 — Nested `aria-live` on inner `<small>` inside `aria-atomic` parent

- **Severity:** LOW
- **Source:** adversary
- **File:** server/routes/ui.py:317
- **What:** `_build_remediation_block` emits
  `'<small class="status-badge__remediation" aria-live="polite">...'`
  nested inside the outer `<span>` that already declares
  `aria-live="polite" aria-atomic="true"` at line 278. Per WAI-ARIA,
  the parent's `aria-atomic="true"` causes the entire `<span>`
  contents to be announced as one unit when ANY descendant changes;
  adding `aria-live` on the nested `<small>` creates a nested live
  region that screen readers handle inconsistently (some announce the
  inner once + the outer atomic block; some announce twice).
- **Why it matters:** Screen-reader accessibility was a load-bearing
  AC at ui-attractive-polish-m1 (UPL-3, referenced in this file's own
  comment block at lines 261-267 — "MOST-CRITICAL implementation risk
  for m1"). Double-announcement on each 10s poll is exactly the
  failure mode that surface area was hardened against. Not breakage —
  just a regression of the screen-reader contract by one nesting
  level.
- **Proposed fix:** Drop the `aria-live="polite"` attribute from the
  nested `<small>`. The parent's `aria-live` + `aria-atomic` already
  cover the contents.
- **Regression guard:** Add a test
  `test_remediation_small_does_not_redeclare_aria_live` that asserts
  the fragment contains exactly ONE `aria-live` attribute.

### F4 — Implementation summary claims 26 endpoint tests; actual count is 25

- **Severity:** LOW
- **Source:** adversary
- **File:** .claude/notes/milestones/onboarding-uplift-m3/implementation-summary.md:68-70 + tests/test_m3_endpoints.py
- **What:** Implementation summary states "26 tests" for
  `tests/test_m3_endpoints.py`; live count via `grep -c "def test_"`
  is 25. CLI count of 11 is accurate.
- **Why it matters:** Trivial bookkeeping drift, but the summary is
  read by future agents as ground truth for what landed. A one-off
  count error makes other claims slightly less trustworthy. Easy fix.
- **Proposed fix:** Update the summary to `25 tests` (or add a 26th
  test — see F3's regression guard suggestion for a candidate).
- **Regression guard:** N/A.

## What was done well

- **MVCC pinned-checkout invariant correctly applied.** Both the REST
  handler (`server/routes/notebooks.py:947`) and the CLI
  (`tools/notebook_reconcile_marker.py:124-125`) pass
  `version=old_info.version` — never `version=None`. The synthesis FM-1
  hazard is closed at both call sites.
- **Atomic-rewrite pattern is byte-identical to canonical.** Tmp
  filename pattern (`{ext}.{pid}.{uuid_hex_8}.tmp`), `os.replace`,
  `try/finally` cleanup with `contextlib.suppress(OSError)`,
  `ensure_ascii=False`, `sort_keys=True`, trailing `\n` — verbatim
  mirror of `ingest/store.py::write_corpus_version_marker`. The
  late-breaking deviation from the synthesis (minified vs default
  separators) was caught during smoke and corrected before landing;
  the deviation is documented in the implementation summary.
- **`CorpusVersionInfo.with_counts()` validates input domain.** Lines
  385-394 reject non-int / negative `chunk_count` and `paper_count`
  with a typed `ValueError` — fails loud on a bad recount rather than
  writing a corrupt marker (matches the project's loud-fail
  convention).
- **D4 byte-identical idempotency is asserted by test, not by hope.**
  Both `tests/test_m3_endpoints.py::test_byte_identical_idempotency_at_steady_state`
  (line 324) and `tests/test_m3_cli.py::test_byte_identical_at_canonical_steady_state`
  (line 220) read the file bytes after two reconcile runs and assert
  equality. This is the right shape for an idempotency contract.
- **BP1/BP2 cache hashes UNCHANGED.** `tests/test_server_tool_schema.py`
  + `tests/test_prompts.py` pass with the pinned
  `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256`. The
  structural `TestNoMCPSurfaceTouch` guard at
  `tests/test_m3_endpoints.py:541` adds belt-and-braces against future
  drift.
- **Test isolation properly redirects both module bindings.** The
  fixture at `tests/test_m3_endpoints.py:50-51` monkeypatches both
  `_notebook_common.NOTEBOOKS_BASE` and `notebooks_module.NOTEBOOKS_BASE`
  — sufficient because `notebook_lancedb_path(slug)` (no `base=`
  kwarg) reads from `_notebook_common.NOTEBOOKS_BASE`. No production-
  disk leak path detected during the walk.
- **Per-dir failure isolation in `repair_registry`.** The walk's
  `_read_marker_safely` returns `(None, "malformed")` rather than
  raising, so a single bad marker doesn't abort the entire walk (FM-7
  mitigation). The four-bucket response shape gives the operator
  per-slug visibility into the outcome.
- **TOCTOU race handled via the `sqlite3.IntegrityError` catch.** The
  `existing_slugs` snapshot at line 811 may go stale during the walk
  if a concurrent caller creates a notebook; line 872's catch
  correctly routes the racing slug to `already_registered`. Semantic
  correctness preserved without holding a lock.
- **`make reconcile` dual-mode shell flow propagates curl exit codes.**
  Recipe at lines 555-574 uses `|| { echo ERROR ...; exit 1; }` after
  the curl call, so a REST-side failure exits the whole multi-line
  shell with 1. Server-down branch ($PYTHON CLI invocations) are the
  last command in their respective branches, so their exit codes
  propagate as the recipe's exit code.
- **`make reconcile NOTEBOOK=` server-up correctly falls back to CLI
  --shared.** Lines 555-558 detect the "server-up + no NOTEBOOK="
  case and explicitly invoke the CLI with `--shared` because there is
  no REST endpoint for the shared-corpus reconcile. Clear, honest
  fallback rather than a silent skip.

## Recommended rectification order

1. **F1** — redact the absolute path in `reconcile_marker`'s 422
   details to match `notebook_health`'s already-redacted form
   (server/routes/notebooks.py:936-937, :942-943). Add regression
   guard. ~5 LOC + ~10 LOC test.
2. **F3** — remove the nested `aria-live` from the inner `<small>`
   (server/routes/ui.py:317). Add regression assertion that the
   fragment contains exactly one `aria-live` attribute. ~1 LOC +
   ~5 LOC test.
3. **F2** — delete the dead `_DEFAULT_DB_PATH` module-level constant
   in `tools/notebook_repair_registry.py:43-46`. ~4 LOC.
4. **F4** — fix the test count in implementation-summary.md
   (`26 tests` → `25 tests`, or alternatively add the F3 regression
   test to bring the count to 26). Bookkeeping.

verdict: SHIP-WITH-FIXES; 4 findings (0/0/1/3)

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
