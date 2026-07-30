---
name: test-wiring-and-coverage-gaps
description: The selector/wiring/routing layer is routinely UNTESTED even when the new impl is unit-tested in isolation; and dual-column embed routing needs vector↔id integration pins. Where to grep.
metadata:
  type: feedback
---

**Rule:** the glue that activates a new impl (argparse choice, `X if flag else Y` ternary,
kwarg threading, `app.state.<tracker>` assignment) is the milestone's actual deliverable and
almost always ships uncovered while the new impl is unit-tested in isolation. **How to apply:**
grep the ROUTE/CLI test file for the wiring symbol; its absence = the common path is untested.

Instances:

- **route-tracker-test-fixture-gap** (textbook-ingest-m6, HIGH): the test client fixture set
  `app.state.notebooks_store` but NOT `app.state.parse_tracker`, so every upload test hit the
  `tracker is None` warn-branch and the schedule/start_parse transition had zero coverage.
  Grep the route test fixture for `app.state.<tracker_name>`.
- **second-chunker-shares-flag-divergent-error-envelope** (textbook-markdown-chunker-m1,
  MEDIUM): a second impl behind `--chunker {html,markdown}` had a DIFFERENT error envelope —
  HTML peer caught `PER_PAPER_FAILURE_EXCEPTIONS`→[], the new markdown one raised
  `FileNotFoundError` uncaught → raw traceback aborts the whole batch (main only catches
  `NotebookError`). Diff the two impls' error envelopes, not just happy paths. The selector
  ternary + kwarg threading was untested; a `dry_run=True` monkeypatch-callee test is the
  lancedb-free guard.
- **notebook-cli-validate-slug-main-guard-contract** (textbook-ingest-m12, MEDIUM): notebook
  CLIs (`tools/notebook_*.py`) have a contract from `notebook_ingest.py:70,204-208` — call
  `validate_slug(slug)` at run() TOP and wrap run() in main() with `except NotebookError →
  return 1`. New CLIs skip both and lean on a downstream callee that RAISES for a bad slug →
  uncaught traceback + nonzero SystemExit instead of the documented 0/1/2 exit code. Not a
  security hole (slug still rejected) → MEDIUM. Diff new CLI main()/run() vs
  `notebook_ingest.py:198-208`.
- **embedrecord-wrong-column-placement-blindspot** (textbook-ingest-m12): `EmbedRecord.
  __post_init__` (schema.py:309-414) validates only dup-within-list, stmt/proof overlap, and
  L2-norm — it does NOT catch a stmt chunk routed into the proof column, nor a vector↔id
  TRANSPOSE (both pass all 4 checks). For any build→batch→split-into-dual-columns flow
  (embedder.py:1017-1081), the backstop MUST be (a) an INTEGRATION test retrieving the
  stmt-routed chunk via the dense `embedding_stmt` path
  (`.search(vector_column_name="embedding_stmt", ..., prefilter=True)`, the server's real
  mechanism at search.py:628-650) AND (b) a unit test pinning vectors to ids (argmax-marker
  encoder). Asserting only `chunk_ids_stmt == [...]` catches a routing swap but NOT a transpose.
- **AC-names-missing-but-test-only-covers-malformed** (textbook-ingest-m10, MEDIUM): when an
  AC enumerates a LIST of edge cases and the test docstring claims to close all, count assert
  methods against the list. m10's docstring claimed "malformed/missing" C-L but only tested
  malformed+negative; "missing" was a benign pass-through (middleware.py:899 None C-L falls
  through to eager pre-read) → MEDIUM not HIGH. Trace the untested branch before picking
  severity: benign pass-through gap = MEDIUM; a rejection-guard gap = HIGH.

Related: [[spy-passthrough-vs-binding-forward]], [[threading-pinned-by-reading-not-assertion]],
[[kuzu-reopen-guard-nondeterministic-under-refcounting]].
