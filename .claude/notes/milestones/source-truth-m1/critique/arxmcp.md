# Critique — source-truth-m1 — milestone-arxmcp-critic

**Critic:** milestone-arxmcp-critic
**Commit range:** f61cb8b..846724a
**Diff stats:** 8 files, 2986 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. The milestone is a clean, advisory-only, security-conscious
addition: the untrusted OAI-PMH surface is parsed with `defusedxml`, redirect-
pinned, byte-capped, and identifier-validated before URL interpolation; it adds
no MCP tool, leaves `server/tools.py` / `server/prompts.py` / `server/license_policy.py`
untouched (BP1 schema-hash test still green), and its 0-re-embed guarantee is
structural and tested. No CRITICAL or HIGH. The one MEDIUM is a coverage-report
gloss that mis-states a downstream consequence to the very owner it advises;
the two LOWs are a latent dead parameter and a one-branch test gap, both
deferrable.

## Executive summary

- [MEDIUM] The coverage report tells the owner a large `not-allowlisted-open` bucket is "the real 'most papers truncate at m4' headline" — but every arXiv chunk today carries `license="arxiv-license"` (`ingest/store.py:321`), which IS in `OA_ALLOWLIST`, so those papers are served full-body, not truncated (Axis 6).
- [LOW] `fetch_license` / `build_getrecord_url` expose a configurable `endpoint`, but the redirect-pin in `_fetch_record` hardcodes the module constant, so any non-default endpoint is silently unusable via the default fetch path (Axis 3 / no-fork mirror divergence).
- [LOW] The Threat-7 actual-read byte-cap branch (lying / absent `Content-Length`) has no test; only the declared-`Content-Length` path is covered (Axis 8).
- [CLEAN] Axis 3 (security): `defusedxml`, redirect-pin, dual byte-cap, and strict `\Z`-anchored id validation before interpolation — all present and tested; `<license>` URI is treated as data, never dereferenced.
- [CLEAN] Axis 4 / Axis 1: no MCP tool added, no `get_chunk` / `ALL_TOOLS` / prompts change; `test_server_tool_schema.py` (BP1 pin) verified passing.
- [CLEAN] Axis 7: OAI-PMH client reimplemented natively (deliberate ~60-line mirror of the repo's own `ingest/oai_delta.py`), no vendored code, no new pip dep (`defusedxml>=0.7` pre-existing).
- [CLEAN] Axis 5 / Axis 8: per-notebook SQLite under `var/arxmcp/notebooks/<slug>/`, no cloud/`/tmp`; 57 new tests pass, 0-re-embed asserted structurally + via corpus-artifact sentinel.
- [CLEAN] Advisory-only: `server/license_policy.py` untouched, `decide_license_status` is a pure predicate, both commits GPG-signed with the `Claude Opus 4.8` co-author trailer.

## Findings

**M1 — Coverage report over-claims "truncate at m4" for arxiv-default papers** (MEDIUM)

**Where:** `tools/documents_coverage_report.py:23`
**Anchor:** `value there is the real "most papers tru`
**What:** The report's docstring frames a large `not-allowlisted-open` count as "the real 'most papers truncate at m4' headline," but arXiv's default license (`nonexclusive-distrib`, which `decide_license_status` maps to `not-allowlisted-open`) corresponds to the chunk token `license="arxiv-license"` that `ingest/store.py:321` stamps on every arXiv row, and `arxiv-license` IS a member of `server/license_policy.py::OA_ALLOWLIST` — so `is_open_access` returns True and `get_chunk` serves those bodies in FULL, never truncated.
**Why it matters:** This is an owner-facing advisory report whose stated purpose is to inform the pre-cutover escalation decision; asserting that the (typically majority) `not-allowlisted-open` bucket "truncates at m4" as fact directly contradicts the shipped truncation policy and can push the owner to the wrong OA-coverage conclusion. The 3-way CLASSIFICATION itself is fine and intended (m1 checks only its CC marker set and defers the arxiv-license OA call) — only the downstream-consequence GLOSS overreaches, and it also treats an OA decision already shipped in textbook-ingest-m11 as still pending.
**Proposed fix:** Reword the docstring (and keep the runtime `OK:` / `ESCALATION:` messages, which are already careful — "the owner's allowlist call, not a data gap") so `not-allowlisted-open` is described as "a real, non-CC license whose m4 serving treatment is the owner's call" rather than asserting truncation. Do not assert any specific `get_chunk` truncation outcome the shipped `OA_ALLOWLIST` does not currently produce.
**Regression-guard:** Optional (doc-fidelity); if desired, a test asserting the report text does not contain a categorical "truncate at m4" claim.
**Source critic:** milestone-arxmcp-critic
**Source axis:** Axis 6 — tier sequencing

**L1 — Configurable `endpoint` is ignored by the redirect-pin (dead/misleading knob)** (LOW)

**Where:** `tools/oai_license.py:299`
**Anchor:** `if not response_url.startswith(OAI_PMH_E`
**What:** `build_getrecord_url` and `fetch_license` accept an `endpoint` parameter and build the request URL from it, but `_fetch_record` takes no endpoint and pins the resolved response URL against the module-level `OAI_PMH_ENDPOINT` constant; a caller passing any non-default `endpoint` through the default fetch path gets an immediate `redirected off` RuntimeError even with no redirect.
**Why it matters:** The mirrored source (`ingest/oai_delta.py::_fetch_page`) pins against its `endpoint` PARAMETER, so this is a silent divergence from the pattern the module claims to mirror; the knob invites a maintenance trap. It is currently harmless (production uses the default; tests bypass `_fetch_record` via the `fetch` seam) and is arguably security-positive (the pin is unconditionally the canonical arXiv host), so it is LOW.
**Proposed fix:** Either drop the `endpoint` parameter from `build_getrecord_url`/`fetch_license` (YAGNI), or thread `endpoint` into `_fetch_record` and pin against it (matching `oai_delta`). Document that the pin is intentionally the canonical host if kept hardcoded.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** Axis 7 — no-fork (mirror fidelity)

**L2 — Threat-7 actual-read byte-cap branch is untested** (LOW)

**Where:** `tools/oai_license.py:292`
**Anchor:** `if len(body) > OAI_PMH_MAX_RESPONSE_BYTES`
**What:** `test_oversized_content_length_refused` exercises only the declared-`Content-Length` pre-read reject (line 285); the actual-read cap at line 291-297 — the branch that catches a lying or absent `Content-Length` with an oversized body — has no covering test.
**Why it matters:** Axis 8 requires every new code path covered, and this is the harder-to-reach half of the Threat-7 mitigation (the one a hostile chunked response would actually trip). Low severity because the code mirrors the tested `oai_delta` structure and the header path is covered.
**Proposed fix:** Add a test whose `_FakeResponse` returns a body longer than `OAI_PMH_MAX_RESPONSE_BYTES` with no (or a small) `Content-Length` and assert `_fetch_record` raises `RuntimeError` matching "exceeded cap".
**Regression-guard:** `tests/test_oai_license.py::test_oversized_read_body_refused` (to add).
**Source critic:** milestone-arxmcp-critic
**Source axis:** Axis 8 — test surface

## What was done well

- Axis 3 primary: the untrusted OAI-PMH XML is parsed with `defusedxml.ElementTree` (XXE / billion-laughs safe), guarded by `test_parser_uses_defusedxml`, and the module deliberately does NOT copy `oai_delta.py`'s unsafe plain `xml.etree` — the exact inconsistency the research flagged.
- Redirect-pinning + a dual Threat-7 byte-cap (pre-read `Content-Length` reject AND `read(cap+1)` size check) are faithfully mirrored from `oai_delta._fetch_page`, hardcoded to the canonical arXiv host, with `test_redirect_off_host_is_refused` + `test_oversized_content_length_refused`.
- Strict identifier validation before URL interpolation: `build_getrecord_url` runs `is_valid_arxiv_paper_id` (the `\Z`-anchored `ARXIV_PAPER_ID_RE`, which rejects `..`, whitespace, and shell metacharacters) and the backfill pre-validates every `papers.txt` line — injection-safe by construction, and the `<license>` URI is only ever substring-matched, never dereferenced.
- The 0-re-embed guarantee is STRUCTURAL (the driver imports no embedder / `ingest.store` / LanceDB) and proven by BOTH an import-scan test and a corpus-artifact sentinel test — a stronger guarantee than the row-count check the brief asked for.
- Idempotency is real and tested end-to-end: `registered_keys` gates re-runs to zero network egress, and a transient fetch failure writes NO row so a re-run retries exactly the missed id (`test_transient_failure_is_per_id_miss_and_rerun_retries`).
- Advisory-only discipline is airtight: `server/license_policy.py` is untouched, `decide_license_status` is a pure predicate (no `assert`, no serving effect), the coverage report changes no serving path, and no MCP tool or schema hash is touched (BP1 pin verified green).
- The schema migration wraps the CREATE + `user_version` bump in an explicit `BEGIN/COMMIT` (autocommit connection) against the named `notebooks_store` v4→v5 crash-loop precedent, is additive-only (`test_migration_never_drops_tables`), and re-runnable without data loss (`test_migration_is_rerunnable_without_data_loss`).
- "Abstention, not silence" is enforced: a NULL `raw_source_sha256` always travels with an explicit `raw_source_status='unavailable'`, and the raw-tree hash is deterministic and cross-platform (sorted POSIX-relative paths + byte lengths + bytes).
- Faithful reuse of the shipped `paper_metadata_store` pattern (per-notebook SQLite sibling, `synchronous=NORMAL` regenerable tier, async-over-sync + `asyncio.Lock`) — no new architectural surface, correct local-first placement under `var/arxmcp/notebooks/<slug>/`.
- Membership is sourced from `papers.txt` with a guard test (`test_driver_never_reads_the_empty_junction_table`) that prevents the silent-zero-rows failure of keying off the empty `notebook_papers` junction, and the summary line reports `registered/total` so a zero-row run stays loud. Both commits are GPG-signed and carry the mandatory `Co-Authored-By: Claude Opus 4.8` trailer.

Severity counts: C0 H0 M1 L2

## Recommended rectification order

M1, L2, L1

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed:
- Deferred:
- Invalidated:
- Regression tests added:
