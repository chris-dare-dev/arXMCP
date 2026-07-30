---
name: claim-drift-verify-against-code
description: Recurring family — a doc/docstring/summary/synthesis statement is a CLAIM about control flow or a shipped surface; grep the cited code before accepting it. Verdicts by surface.
metadata:
  type: feedback
---

The single most recurring finding class across this project: **"X says Y, code does
Z."** A design doc, module docstring, `ToolMeta.description`, implementation-summary
deviation note, or research-synthesis "failure mode" is a CLAIM. Verify it against the
cited `file:line` control flow before marking the axis clean. Lead with a **Why:** the
implementer edits the surface the brief names and leaves the enforcing code (or a
sibling surface) stale. **How to apply:** grep the asserted function/validator/guard
for the early-return, import, or ordering it claims.

Instances (each is a concrete replay of the pattern):

- **stale-docstring-anti-pattern** (textbook-ingest-m2, HIGH): a milestone "ships X" but
  the module docstring still says "X not implemented; do Y workaround." Grep the docstring
  of any file the milestone "completes." `ingest/schema.py:13-15` lied about
  `_migrate_chunks_schema_if_needed`.
- **bp1-description-vs-handler-validator-drift** (textbook-ingest-m3, HIGH): edited
  `SEARCH_PAPERS.description` to "documents widened acceptance" but
  `server/handlers/search.py:175` still called `is_valid_arxiv_paper_id` (narrow). Grep
  the validator import line in the handler before declaring a description edit clean.
- **security-doc-drift-on-multi-byte-magic-sniff** (textbook-ingest-m4, HIGH):
  `.claude/docs/security-pdf-sandbox.md` kept "first 4 bytes %PDF + 4 tokens" while code
  shipped "5 bytes %PDF- + 7 tokens + </html>/</body>". Grep the design doc for byte
  counts / token lists / marker strings whenever the matching code path changes.
- **doc-finalize-leaves-sibling-snippet-stale** (textbook-ingest-m10, MEDIUM): fixed the
  ONE snippet the brief named (JS, security-pdf-sandbox.md:222-243) but left the
  page-count snippet below it (:262-266) referencing a non-existent `_pdf_page_count`
  (real: `_pdf_declared_page_count` /Count byte-regex, notebooks.py:636). On doc-accuracy
  milestones read the WHOLE edited block + the headline threat table, not just diff lines;
  grep every function name in the doc against the module; cross-check threat-table summary
  rows vs the doc's own detail (m10 said "2 tokens" while its bullet said 7).
- **synthesis-FM-claim-vs-actual-control-flow** (corpus-integrity-observability-m1, MEDIUM):
  a synthesis FM justified skipping a test with "write_chunks([]) returns early today" —
  false; `ingest/store.py:796-801` falls through to build an empty table + create indices +
  marker. Benign here (counts=0) so MEDIUM, but the reasoning was wrong.
- **synthesis-required-FM-test-vs-pure-helper-only** (corpus-integrity-observability-m2,
  HIGH): a pure helper (`compute_chunk_count_divergence`) was tested exhaustively while the
  synthesis-REQUIRED integration-boundary FMs (corpus_corruption clobber guard, count_rows
  raising) shipped untested — never booted `Resources.startup` with the degraded pre-state.
  Grep synthesis for "regression coverage"/"FM-N" lists, then grep tests for one driving the
  INTEGRATION entrypoint per item. HIGH when the untested guard protects a more-severe signal
  on a reachable path. Also: a new `@field_validator` mirroring an existing one is a
  copy-paste-typo magnet — absent test for the new field name = MEDIUM.
- **populate-after-append-dead-write** (corpus-integrity-observability-e3, HIGH): new
  dataclass field `WriteStats.total_rows_after_commit` (store.py:196) is serialized at :887
  but populated at :941 → always 0 in the jsonl; the impl-summary claimed "populated
  correctly." For any new serialized dataclass field, confirm the populate precedes the
  earliest consumer.
- **documented-deploy-flow-crashes-on-empty-corpus** (notebook-ops-hardening-m3, HIGH):
  documented `make bootstrap → up --wait → /readyz 200` is non-functional on a fresh box —
  `bootstrap` only makes empty dirs, `server/corpus.py:291` raises `CorpusNotIngestedError`
  → container EXITS at startup (NOT a graceful 503, as the synthesis claimed). The deploy doc
  IS the deliverable; flag HIGH when it omits the corpus prerequisite. Also diff copy-adapted
  compose tests' FUNCTION lists (m3 dropped `test_restart_policy_is_no`).

Related: [[bp1-description-vs-handler-validator-drift]],
[[middleware-cap-vs-handler-cap-read-ordering]], [[security-doc-drift-on-multi-byte-magic-sniff]],
[[uv-lock-transitive-major-version-downgrade]].
