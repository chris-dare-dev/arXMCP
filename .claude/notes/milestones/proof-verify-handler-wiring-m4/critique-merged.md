# Critique — proof-verify-handler-wiring-m4 (merged)

**Critics fired:** adversary (1; infra-safety / oss-scout / frontend-UX
did not fire — no infra paths in diff, no OSS-scout opt-in, no frontend
exists by design).

**Verdict:** SHIP-WITH-FIXES (adversary).

## Findings summary

| ID | Sev | Source | Title | Phase-4 status |
|---|---|---|---|---|
| F1 | HIGH | adversary | m3 runbook recipe hard-fails on `ARXMCP_CONTACT_EMAIL` + stateless `tools/call`; "backlog" was a phrase, not an artifact | CLOSED — both runbook bugs fixed (env var removed + sanity-check recipe rewritten to use spec-compliant init handshake); regression test pins `_scan_unknown_arxmcp_env_vars` rejection |
| F2 | MEDIUM | adversary | Validator IOError paths emit raw tracebacks instead of `FAIL: ...` per docstring contract | CLOSED — wrapped `read_paper_ids_from_papers_txt` + `queries_path.open` in `try/except OSError`; +2 chmod-0o000 regression tests |
| F3 | MEDIUM | adversary | Real-notebook "hard-pin" tests have no cross-reference comment in the validator | CLOSED — added a docstring block above `REQUIRED_TOP_KEYS` naming the live fixtures + the lockstep tests |
| F4 | MEDIUM | adversary | BM25 sentinel files diverge byte-wise from script-written form (manual `echo` added trailing `\n`) | CLOSED — sentinels rewritten via `pathlib.Path.write_text(slug)` to match `tools/notebook_ingest.py:157` exactly; verified byte-equal via `od -c` |
| F5 | MEDIUM | adversary | Validator delegates to `is_valid_paper_id` boundary classes (trailing newline, CR, leading whitespace) with no own-surface coverage or cross-reference | CLOSED — added 5-case parametrized boundary test (`test_paper_id_boundary_classes_rejected`) + inline comment at the delegation site pointing at the m1-rect-F3 history and the new test |
| F6 | LOW | adversary | Synthesis says "shimura has ~8 queries"; reality is 10 | **DEFERRED** — pure synthesis-doc drift; LOW; the milestone artifact is closed and re-opening it for a number-only correction is anti-pattern (per CLAUDE.md state.json forward-only discipline). Tracked here for visibility. |
| F7 | LOW | adversary | `_validate_top_level` doesn't isinstance-check `schema_version`, `notebook_display_name`, `created_at` | **DEFERRED** — defensive typing improvement; LOW; would also benefit from ISO-8601 format validation on `created_at` which is more scope. Tracked for a future hardening pass. |

## Rectification artifacts

- `docs/ops/notebook-modes.md` — F1 dual fix:
  - Mode 1 §Launch: removed two `ARXMCP_CONTACT_EMAIL=...` references
    + added a 5-line comment explaining why (env var is ingest-side
    only; server rejects unknown `ARXMCP_*` at startup via the F4-from-
    E06_S01 scanner).
  - §Sanity check: replaced the stateless `tools/call` recipe (which
    fails empirically with `{"code":-32600,"message":"Bad Request:
    Missing session ID"}`) with the spec-compliant 3-step handshake
    (`initialize` → `notifications/initialized` → `tools/call`),
    capturing the `Mcp-Session-Id` from the server's response header
    via `awk`. The recipe is the same one m4's AC #5 smoke test
    actually used and verified working.
- `tests/test_server_startup.py::TestConfigValidation::test_contact_email_env_var_rejected` —
  F1 regression guard. Monkeypatches `ARXMCP_CONTACT_EMAIL` into the
  environment and asserts `_scan_unknown_arxmcp_env_vars(cfg)` raises
  `ValueError` naming the offending key. Note the comment names the
  inversion path: if a future milestone decides to declare the field
  as `contact_email: str | None = None` on `Config`, flip the test
  to assert acceptance.
- `tools/validate_notebook_fixtures.py` — F2 + F3 + F5 closures:
  - F2: wrapped both file-read sites in `try/except OSError` →
    `FixtureValidationError("... is unreadable: ...")`.
  - F3: added a 7-line cross-reference comment above
    `REQUIRED_TOP_KEYS` pointing at the live fixtures + lockstep
    tests so a future curator can't silently break the coupling.
  - F5: added an inline comment at the `is_valid_paper_id`
    delegation site naming the m1-rect-F3 hardening + the new
    boundary-class test as the proof.
- `tests/tools/test_validate_notebook_fixtures.py` — F2 + F5
  regression guards (+8 new tests across two new classes):
  - `TestPerQueryStructure::test_paper_id_boundary_classes_rejected`
    (5 parametrized cases: trailing `\n`, trailing `\r`, leading
    whitespace, trailing whitespace, embedded `\n`).
  - `TestIOErrorHandling::test_unreadable_{papers,queries}_*` (2
    cases each guarded with Windows + root skips).
- `var/arxmcp/index/bm25/v157/.notebook_slug` + `v49/.notebook_slug` —
  F4 closure: rewritten via `pathlib.Path.write_text(slug)` to match
  the script's canonical form (no trailing newline). Verified
  byte-exact via `od -c`.

## Final test count

`make test`: **2296 passed** (+8 rect, total +37 across m4 feat + rect),
9 skipped, 1 xfailed. Ruff clean.

## Deferred findings

- **F6 (LOW)** — synthesis-doc drift (shimura has 10 queries, not ~8 as
  noted in the synthesis open-questions section). Pure historical
  artifact; the milestone is closed; re-opening the synthesis is
  anti-pattern. Recorded here for any future maintainer who reads
  the synthesis verbatim.
- **F7 (LOW)** — defensive `isinstance` typing on `schema_version`,
  `notebook_display_name`, `created_at` plus ISO-8601 format
  validation on `created_at`. Cheap individually but the F7 + a few
  related hardening items (date format, schema_version semver shape,
  etc.) are a natural cluster for a future validator-hardening pass.

## Re-verify gate notes

All 5 closed findings re-verified before fixing:
- F1: `docs/ops/notebook-modes.md:64,73` confirmed to contain the
  `ARXMCP_CONTACT_EMAIL` references; `server/main.py:232-253`
  confirmed `_scan_unknown_arxmcp_env_vars` is the actual rejecter;
  empirical reproduction confirmed `Config()` alone DOES NOT raise
  (pydantic's `extra="forbid"` is `__init__`-kwarg-only) — the
  custom scanner is the gate.
- F2: validator at `tools/validate_notebook_fixtures.py:179-192`
  confirmed to lack the try/except wrap.
- F3: confirmed `REQUIRED_TOP_KEYS` has no comment naming the
  lockstep tests.
- F4: `od -c var/arxmcp/index/bm25/v157/.notebook_slug` confirmed a
  trailing `\n` (0x0a) byte; `tools/notebook_ingest.py:157` confirmed
  to write `slug` without trailing newline.
- F5: confirmed the validator's tests had only one `"NOT-A-PAPER-ID"`
  invalidation case at `tests/tools/test_validate_notebook_fixtures.py:298-308`,
  with no coverage of the m1-rect-F3 boundary classes.

Zero findings invalidated. Adversary invalidation rate: **0 / 5 (0%)** —
well under the 40% threshold; critic prompt calibrated correctly.

## Cross-critic agreement

N/A — only one critic fired (adversary). Infra-safety did not fire
(no infra paths in diff). OSS-scout is opt-in only. Frontend-UX does
not apply to arXMCP by design.
