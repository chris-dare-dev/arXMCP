# Critique — source-truth-m1 — merged (adversary + arxmcp)

**Critic:** milestone-adversary-critic + milestone-arxmcp-critic (orchestrator-merged, id-remapped)
**Commit range:** f61cb8b..846724a
**Diff stats:** 8 files, 2986 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. The registry, OAI-PMH client, backfill, and coverage report are well-built and
security-conscious: the untrusted OAI-PMH surface is `defusedxml`-parsed, redirect-pinned,
byte-capped, and identifier-validated before URL interpolation; all three ACs are met AND
behavior-tested; the three owner decisions are implemented faithfully; `server/license_policy.py`
is untouched (advisory-only, BP1 schema-hash pin green); both commits GPG-signed + trailered. No
CRITICAL. One real defect (H2: a `Retry-After: 0` busy-loop that would violate the arXiv
politeness contract) should be fixed before running live; H1 is the mandated diff-size flag
(owner-approved `allow_large_diff`, strongly mitigated by 57 behavior-asserting tests); M1/M2 are
cheap consistency/fidelity fixes; three LOWs are deferrable.

## Executive summary

- [HIGH] `oai_license._fetch_record` honors `Retry-After: 0` literally (no politeness floor) → a persistent `503 + Retry-After: 0` becomes a no-delay busy-loop hammering arXiv until the 1h cap. The sibling `arxiv_fetch` clamps; this copied `oai_delta`'s unclamped pattern.
- [HIGH] Mandated diff-size flag: 2986 LOC (>400). `allow_large_diff` owner-approved; 57 behavior-asserting tests mitigate.
- [MEDIUM] A `papers.txt` member with a missing `parsed/<id>/index.html` (a real parse-failure mode) is registered "successfully" with `parse_artifact_sha256=NULL` and NO status marker — silence on one checksum axis, unlike the raw-source abstention. Untested.
- [MEDIUM] The coverage report's docstring frames a large `not-allowlisted-open` bucket as "the real 'most papers truncate at m4' headline" — but `arxiv-license` (the token every chunk carries, `ingest/store.py:321`) IS in `OA_ALLOWLIST`, so those bodies serve FULL today. Owner-facing over-claim.
- [CLEAN] Axis 3 security: defusedxml + redirect-pin + dual byte-cap + strict id-validation all present + tested. No MCP tool / schema-hash touch. Native no-fork mirror, no new dep. Advisory-only confirmed.

## Findings

**H1 — Diff is 2986 LOC (>400): review-quality-at-risk** (HIGH)

**Where:** no specific file
**What:** The two feat commits total 2986 insertions across 8 files, over the 400-LOC single-review threshold, so subtle defects are statistically more likely to slip a single critique pass.
**Why it matters:** Large diffs degrade per-line review attention; this is the mandated process flag whenever a diff exceeds 400 LOC.
**Proposed fix:** No code change. `allow_large_diff` was owner-approved (the 5 tasks form one coherent registry system). The risk is substantially reduced by strong, behavior-asserting coverage (4 test files, ~57 tests exercising each acceptance path and owner decision); the residual gaps are the specific untested edges in H2 and M1.
**Regression-guard:** N/A (process flag); the follow-up guards are H2's and M1's tests.
**Source critic:** milestone-adversary-critic
**Source axis:** Test discipline / diff size

**H2 — `Retry-After: 0` defeats the 503 backoff → no-delay busy-loop against arXiv** (HIGH)

**Where:** `tools/oai_license.py:311`
**Anchor:** `wait = retry_after if retry_after is not None else backoff`
**What:** `_parse_retry_after` returns `max(0.0, float(value))` (line 238), so `Retry-After: 0` yields `0.0`; because `0.0 is not None`, the 503 loop takes `wait = 0.0`, `min(0.0, remaining) = 0.0`, `sleep(0.0)`, and the exponential `backoff` is never consulted — a persistent `503 + Retry-After: 0` spins with zero inter-request delay until the 1-hour `retry_cap_seconds` wall clock.
**Why it matters:** This module's entire reason for the self-contained fetch is the arXiv politeness contract (≤1 request / 3s). The busy-loop can exceed that by orders of magnitude for up to an hour, risking throttling or a ban of the operator's polite-pool contact email — and `Retry-After: 0` is a live-observed arXiv behavior the sibling `tools/notebook_metadata_backfill.py` documents and clamps via `tools.arxiv_fetch.parse_retry_after`.
**Proposed fix:** Clamp the honored wait to the politeness floor on the 503 path: `wait = max(wait, POLITENESS_SLEEP_SECONDS)` before `min(wait, remaining)` (or reuse `tools.arxiv_fetch.parse_retry_after`, which already clamps). Preserves honoring a server-requested longer delay while never dropping below the 3s contract.
**Regression-guard:** `tests/test_oai_license.py::test_retry_after_zero_is_floored` — feed a `503` with `Retry-After: 0`, assert the recorded `sleep` value is `>= POLITENESS_SLEEP_SECONDS` and the loop does not issue an unbounded number of requests within the cap.
**Source critic:** milestone-adversary-critic
**Source axis:** OAI-PMH client correctness (503/Retry-After/politeness)

**M1 — Missing parse-artifact is a silent NULL with no status marker (untested)** (MEDIUM)

**Where:** `tools/notebook_documents_backfill.py:204`
**Anchor:** `parse_artifact_sha256=_parse_artifact_sha256(`
**What:** `_parse_artifact_sha256` returns `None` when `parsed/<work_id>/index.html` is absent, and `_build_record` stores that `None` into a row still registered as a success (exit 0) with no companion status field — whereas the raw-source axis records the same gap as a first-class `raw_source_status='unavailable'` abstention marker.
**Why it matters:** A `papers.txt` member whose parse failed (a real, tracked failure mode) then carries a NULL parse checksum indistinguishable from a populated one, silently failing AC1's "every registered revision row carries ... parse-artifact sha256" and the milestone's "abstention, not silence" principle on one of its two checksum axes.
**Proposed fix:** Either (a) treat a missing `index.html` as a per-id miss (do not write the row, so a re-run retries), or (b) add a `parse_artifact_status` marker mirroring `raw_source_status` so the gap is explicit. (Orchestrator note: (b) is more consistent with AC1's "every revision has a row" + the established abstention pattern.)
**Regression-guard:** A backfill test with a member that has a raw tree + OAI license but NO `parsed/<id>/index.html`, asserting the chosen contract (explicit parse-abstention status, or row withheld) rather than a silent NULL.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage (AC1 provenance completeness)

**M2 — Coverage report over-claims "truncate at m4" for arxiv-default papers** (MEDIUM)

**Where:** `tools/documents_coverage_report.py:23`
**Anchor:** `value there is the real "most papers tru`
**What:** The report's docstring frames a large `not-allowlisted-open` count as "the real 'most papers truncate at m4' headline," but arXiv's default license (`nonexclusive-distrib`, mapped to `not-allowlisted-open`) corresponds to the chunk token `license="arxiv-license"` that `ingest/store.py:321` stamps on every arXiv row, and `arxiv-license` IS in `server/license_policy.py::OA_ALLOWLIST` — so `is_open_access` returns True and `get_chunk` serves those bodies in FULL, never truncated.
**Why it matters:** This is an owner-facing advisory report; asserting that the (typically majority) `not-allowlisted-open` bucket "truncates at m4" as fact contradicts the shipped truncation policy and can push the owner to the wrong OA-coverage conclusion. The 3-way classification itself is fine — only the downstream-consequence gloss overreaches.
**Proposed fix:** Reword the docstring so `not-allowlisted-open` is "a real, non-CC license whose m4 serving treatment is the owner's call" rather than asserting truncation. Keep the careful runtime `OK:`/`ESCALATION:` messages. Assert no specific `get_chunk` truncation outcome the shipped `OA_ALLOWLIST` does not currently produce.
**Regression-guard:** Optional (doc-fidelity); a test asserting the report text contains no categorical "truncate at m4" claim.
**Source critic:** milestone-arxmcp-critic
**Source axis:** Axis 6 — tier sequencing

**L1 — Redirect-pin is a prefix match, not exact-origin** (LOW)

**Where:** `tools/oai_license.py:299`
**Anchor:** `if not response_url.startswith(OAI_PMH_ENDPOINT):`
**What:** The pin accepts any resolved URL beginning with `https://oaipmh.arxiv.org/oai`, so a same-host redirect to a different path (`.../oai-anything`) would satisfy it; only off-host redirects are rejected.
**Why it matters:** Real risk is low — the check still binds egress to arXiv's own trusted OAI host — but the pin is looser than an exact-origin check; verbatim copy of `ingest/oai_delta.py`'s check.
**Proposed fix:** Optional; defer. If tightened, compare parsed origin + path prefix explicitly.
**Regression-guard:** Optional.
**Source critic:** milestone-adversary-critic
**Source axis:** OAI-PMH client security (redirect pinning)

**L2 — Configurable `endpoint` is ignored by the redirect-pin (dead/misleading knob)** (LOW)

**Where:** `tools/oai_license.py:299`
**Anchor:** `if not response_url.startswith(OAI_PMH_E`
**What:** `build_getrecord_url`/`fetch_license` accept an `endpoint` parameter and build the request URL from it, but `_fetch_record` pins the resolved URL against the module-level `OAI_PMH_ENDPOINT` constant; a caller passing a non-default `endpoint` gets an immediate `redirected off` RuntimeError even with no redirect.
**Why it matters:** Silent divergence from `oai_delta._fetch_page` (which pins against its `endpoint` PARAMETER); a maintenance trap. Currently harmless (production uses the default) and arguably security-positive.
**Proposed fix:** Drop the `endpoint` parameter (YAGNI), or thread it into `_fetch_record` and pin against it; document if intentionally hardcoded to the canonical host.
**Regression-guard:** Optional.
**Source critic:** milestone-arxmcp-critic
**Source axis:** Axis 7 — no-fork (mirror fidelity)

**L3 — Threat-7 actual-read byte-cap branch is untested** (LOW)

**Where:** `tools/oai_license.py:292`
**Anchor:** `if len(body) > OAI_PMH_MAX_RESPONSE_BYTES`
**What:** `test_oversized_content_length_refused` exercises only the declared-`Content-Length` pre-read reject; the actual-read cap (the branch catching a lying/absent `Content-Length` with an oversized body) has no covering test.
**Why it matters:** Axis 8 requires every new code path covered, and this is the harder-to-reach half of the Threat-7 mitigation. Low because the code mirrors the tested `oai_delta` structure.
**Proposed fix:** Add a test whose fake response returns a body longer than `OAI_PMH_MAX_RESPONSE_BYTES` with no/small `Content-Length` and assert `_fetch_record` raises "exceeded cap".
**Regression-guard:** `tests/test_oai_license.py::test_oversized_read_body_refused`.
**Source critic:** milestone-arxmcp-critic
**Source axis:** Axis 8 — test surface

## What was done well

- **defusedxml on untrusted OAI-PMH XML** (both critics): `parse_getrecord` uses `defusedxml.ElementTree` (XXE/entity-safe), asserted by `test_parser_uses_defusedxml` — a deliberate, tested divergence from `oai_delta.py`'s plain-ET choice the research flagged.
- **Id validated before URL construction** (both): `build_getrecord_url` strips `vN` then runs `is_valid_arxiv_paper_id` (the `\Z`-anchored regex) before interpolation, closing query-injection; old-style archive prefix + literal `/` preserved + tested.
- **Redirect-pin + dual Threat-7 byte-cap** (arxmcp): pre-read `Content-Length` reject AND `read(cap+1)` check, mirrored from `oai_delta._fetch_page`, hardcoded to the canonical arXiv host; `<license>` URI only substring-matched, never dereferenced.
- **Atomic, re-runnable schema migration** (both): v0→v1 CREATE + `PRAGMA user_version=1` in explicit BEGIN/COMMIT with ROLLBACK; `test_migration_is_rerunnable_without_data_loss` reproduces the user_version-lags-tables crash window; `test_migration_never_drops_tables`.
- **Structural (not incidental) 0-re-embed** (both): the backfill imports no embedder/`ingest.store`/lancedb; proven by an import-scan test AND a corpus-artifact sentinel — stronger than the row-count check the brief asked for.
- **Advisory 3-way license_status, no folding** (both): CC-family→`eligible`, `nonexclusive-distrib`→`not-allowlisted-open`, None→`unknown`; `server/license_policy.py` grep-confirmed untouched — the m4 cutover is not pre-empted.
- **Abstention-not-silence for raw source** (both): NULL `raw_source_sha256` always travels with `raw_source_status='unavailable'`, round-trips; the raw-tree hash is deterministic + cross-platform (sorted POSIX-relative paths + byte lengths + bytes).
- **Revision-grained PK** (adversary): `(work_id, arxiv_version)` retains the version the rest of the codebase strips; `test_distinct_versions_are_distinct_rows`.
- **Politeness owned by the caller + tested** (both): `fetch_license` never sleeps; the driver sleeps 3s before every request except the first; an idempotent re-run performs zero network egress.
- **idDoesNotExist vs transient-miss distinction** (both): `idDoesNotExist` → terminal per-paper `unknown` that writes a row (exit 0); a transient failure writes NO row (re-run retries) — both directions tested.
- **Owner Decision C escalation is precise** (adversary): the gate is on `unknown` alone; `test_not_allowlisted_open_does_not_trigger_escalation` proves a 70%-not-allowlisted / 10%-unknown notebook does NOT escalate while reporting `not-allowlisted-open` prominently. No `assert`-for-invariant; both commits signed + trailered; no new pip dep.

Severity counts: C0 H2 M2 L3


## Cross-critic agreement

The following findings cluster within 5 lines of each other in the same file. Multiple critics flagged the same area - these are the strongest signals to fix first.

- **L1, L2** at `tools/oai_license.py:299-299` (LOW): Redirect-pin is a prefix match, not exact-origin; Configurable `endpoint` is ignored by the redirect-pin (dead/misleading knob)

## Recommended rectification order

H2, M1, M2, L3, L2, H1, L1
