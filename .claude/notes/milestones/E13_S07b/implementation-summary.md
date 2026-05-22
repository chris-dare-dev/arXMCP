# Implementation summary — E13_S07b

**Milestone:** E13_S07b — Add redirect-host validation to graph_ingest + inspire_ingest
**Implementation base SHA:** `c9df7f10377a2f3ab7a7f61fd1bf615932e6b6c7`
**Path:** inline (orchestrator implemented directly in main session)

## One-line summary

Closed Threat 7 partial-coverage gap G2 (GitHub issue #2) by adding the
post-fetch `response.url` redirect-host pin — already present in
`ingest/ar5iv_fetch.py` and `ingest/oai_delta.py` — to the single HTTP
fetch function in each of `ingest/graph_ingest.py` (`_fetch_openalex_work`)
and `ingest/inspire_ingest.py` (`_fetch_inspire_record`). On an off-host
redirect both raise `RuntimeError`. No production-code refactor; no schema
change; `ingest/`-only + tests + docs.

## Files changed

| File | Change | Why |
|---|---|---|
| `ingest/graph_ingest.py` | MODIFIED | `_fetch_openalex_work`: capture `resp.url` after the body read; raise `RuntimeError` if it does not start with `OPENALEX_BASE + "/"` |
| `ingest/inspire_ingest.py` | MODIFIED | `_fetch_inspire_record`: same guard pinning `INSPIRE_API_BASE + "/"` |
| `tests/security/test_source_ingest.py` | MODIFIED | New `TestRedirectHostPin` class — 6 tests: off-host rejection + on-host acceptance + prefix-collision rejection, per module |
| `.claude/docs/security-threat-7-audit.md` | MODIFIED | Compliance matrix: both module rows flipped `⚠️ not pinned (follow-up)` → `✅ E13_S07b`; Known-gaps section marks the gap closed; references list updated; test-class count 4 → 5 |
| `.claude/docs/security-threat-model-coverage.md` | MODIFIED | Threat 7 summary-table row + per-threat section + Gap-issue triage row G2 all updated to mark the gap closed by E13_S07b |

## Design decision (from research synthesis)

The two compliant modules use **different** redirect-pin forms:
- `ar5iv_fetch.py` pins `startswith(AR5IV_BASE_URL + "/")` (trailing slash)
  and returns a miss-result on mismatch.
- `oai_delta.py` pins `startswith(endpoint)` (no trailing slash) and raises
  `RuntimeError` on mismatch.

Synthesis decisions:
1. **Raise `RuntimeError`** (the `oai_delta.py` behavior) for both new
   guards — `graph_ingest` / `inspire_ingest` propagate fetch errors via
   exceptions through their callers; a return-value sentinel would force
   caller refactoring. A redirect on a pipeline-critical fetch is
   unambiguously wrong and should abort the paper, not silently skip it.
2. **Use the trailing `"/"`** (the `ar5iv_fetch.py` form) — strictly
   stronger than the bare `oai_delta.py` form. A bare
   `startswith("https://api.openalex.org")` would also accept
   `https://api.openalex.org.evil.com/…` (an attacker-registrable domain).
   The `+ "/"` rejects it: the legitimate URL always has `/` after the
   host, the attacker domain has `.`. Two dedicated prefix-collision tests
   pin this.

## Acceptance criteria status

| AC | Status | Evidence |
|---|---|---|
| `graph_ingest.py` validates `response.url` against the OpenAlex host after every fetch | ✅ | `_fetch_openalex_work` guard; sole HTTP call site |
| `inspire_ingest.py` validates `response.url` against the INSPIRE-HEP host after every fetch | ✅ | `_fetch_inspire_record` guard; sole HTTP call site |
| Both checks use semantics identical to the existing `ar5iv_fetch.py` / `oai_delta.py` guard | ✅ | `RuntimeError` (oai_delta) + trailing-slash pin (ar5iv) — synthesis-resolved hybrid; both forms exist in-repo |
| `test_source_ingest.py` includes redirect-host-rejection tests for both modules | ✅ | `TestRedirectHostPin` — 6 tests |
| `pytest tests/security/test_source_ingest.py` passes; existing graph/inspire tests still pass | ✅ | `test_source_ingest.py` 19 passed; `test_graph_ingest.py`/`test_inspire_ingest.py` failures are pre-existing Kùzu-DB file-lock issues on Windows (confirmed by traceback), unrelated to the redirect pin |
| `security-threat-7-audit.md` Known gaps section marks the gap closed | ✅ | Known-gaps bullet struck through + "CLOSED by E13_S07b" |
| `security-threat-model-coverage.md` Threat 7 row no longer cites #2; Gap-issue triage updated | ✅ | Summary-table row, per-threat Gaps section, and G2 triage row all updated |
| `tests/security/test_threat_model_coverage.py` (E13_S10 staleness gate) still passes | ✅ | 21 passed; `test_source_ingest.py` already cited (no citation change needed) |
| GitHub issue #2 closed with a commit reference | ⚠️ **Phase-4 gated** — `gh issue close 2` requires user authorization at the external-write boundary |

## Tests

- **Extended file:** `tests/security/test_source_ingest.py`
- **New class:** `TestRedirectHostPin` (6 tests, all passing)
  - `test_graph_ingest_rejects_off_host_redirect`
  - `test_graph_ingest_accepts_on_host_response`
  - `test_inspire_ingest_rejects_off_host_redirect`
  - `test_inspire_ingest_accepts_on_host_response`
  - `test_graph_ingest_rejects_prefix_collision_host`
  - `test_inspire_ingest_rejects_prefix_collision_path`
- Mock discipline (research-brief-2 failure mode #4): the fake response
  sets an explicit `.url` string. A bare `MagicMock` returns a truthy
  child for `.url` and `.startswith` on that child raises `AttributeError`.

## Project-check status

- `ruff check ingest/graph_ingest.py ingest/inspire_ingest.py tests/security/test_source_ingest.py` → clean
- `pytest tests/security/test_source_ingest.py` → 19 passed (was 13 → +6)
- `pytest tests/security/test_source_ingest.py tests/security/test_threat_model_coverage.py` → 40 passed
- Full `pytest` → 2457 passed, 49 failed. The 49 failures are ALL
  pre-existing Windows-platform issues (Kùzu DB file-locks on
  `test_graph_ingest.py`/`test_inspire_ingest.py`, POSIX-shell
  `test_quarterly_drill_reminder.py`, symlink `test_preamble.py`,
  subprocess `test_chunker_ids.py`/`test_latexml_sandbox.py`,
  `test_drift_check.py` latexmlc) OR in-flight work from other milestones
  not yet committed (`test_preview_route.py` ×14 from
  proof-verify-handler-wiring-m10, notebook tests). None touch
  `graph_ingest`/`inspire_ingest` redirect-pin code; `test_source_ingest.py`
  has zero failures.

## Repo-state note for the critic

The working tree at implementation time carried uncommitted modifications
from in-flight non-E13_S07b work (`server/lean_repl.py`,
`server/resources.py`, `tests/test_lean_repl.py`,
`tests/test_server_startup.py`, `.claude/docs/lean-sandbox-design.md`,
`verification-feedback-m2/state.json`, untracked `capability-scout`
agent files). These are NOT part of this milestone and were deliberately
EXCLUDED from the E13_S07b commit (specific-file `git add`, never
`git add -A`). The feat commit contains only the 5 files listed above
plus the `.claude/notes/milestones/E13_S07b/` pipeline artifacts.

## External writes required

| Type | Target | Why | Blocking |
|---|---|---|---|
| `git push` | `main @ github.com/chris-dare-dev/arXMCP` | Land the feat+rect+chore commits | YES — per-event user authorization |
| `gh issue close` | `chris-dare-dev/arXMCP#2` | Close gap-issue G2 with a commit reference | YES — Phase-4 gated |

## Deviations from the brief

1. **"raise the same error type the existing modules raise"** — the two
   compliant modules raise different things (`ar5iv` returns a miss,
   `oai_delta` raises `RuntimeError`). Resolved to `RuntimeError` for both
   — see Design decision above.
2. **"create the file if absent"** for `tests/security/test_source_ingest.py`
   — the file already exists (shipped by E13_S07); the new tests were
   added as a class to the existing file, which is also what keeps the
   `test_threat_model_coverage.py` citation gate green with no doc edit.
