# Critique — source-truth-m1 — milestone-adversary-critic

**Critic:** milestone-adversary-critic
**Commit range:** f61cb8b..846724a
**Diff stats:** 8 files, 2986 LOC
**Critique format version:** 1.0

## Verdict

SHIP-WITH-FIXES. The registry, OAI-PMH client, backfill and coverage report are well-built, and all three acceptance criteria are met AND exercised by behavior-asserting tests (not smoke); the three owner decisions are implemented faithfully with `server/license_policy.py` grep-confirmed untouched, both commits GPG-signed + co-authored, scope exactly the 8 intended files. One real defect (H2: a `Retry-After: 0` busy-loop that can violate the arXiv politeness contract by orders of magnitude) should be fixed before this runs against live arXiv; M1 (silent parse-artifact NULL) is a cheap consistency fix; H1 is the mandated diff-size flag, substantially mitigated by the coverage.

## Executive summary

- [HIGH] The 503 retry path in `oai_license._fetch_record` honors `Retry-After: 0` literally (no politeness floor), so a persistent `503 + Retry-After: 0` — a live-observed arXiv behavior the sibling metadata-backfill explicitly guards against — becomes a no-delay busy-loop hammering arXiv until the 1-hour cap.
- [HIGH] Mandated: the diff is 2986 LOC (>400), a review-quality-at-risk flag. `allow_large_diff` was owner-approved; the test coverage (57 tests, behavior-asserting) genuinely mitigates but the flag stands.
- [MEDIUM] A `papers.txt` member whose `parsed/<id>/index.html` is missing (a real parser-failure mode) is registered "successfully" with `parse_artifact_sha256=NULL` and NO status marker — silence on the parse axis, contradicting the milestone's own "abstention, not silence" principle that the raw-source axis honors with `raw_source_status`. Untested.
- [LOW] Redirect-pin is a `startswith(endpoint)` prefix match, so a same-host different-path redirect (`oaipmh.arxiv.org/oai...`) would pass; low real risk (same trusted host), mirrors `oai_delta`.
- Zero CRITICAL: no external write in the diff, no `plans/*/roadmap.yaml` status edit, production code carries test deltas, both commits signed + trailered, `license_policy.py` untouched, no `assert`-for-invariant in any production file, no CLAUDE.md contradiction.

## Findings

**H1 — Diff is 2986 LOC (>400): review-quality-at-risk** (HIGH)

**Where:** no specific file
**What:** The two feat commits total 2986 insertions across 8 files, over the 400-LOC single-review threshold, so subtle defects are statistically more likely to slip a single critique pass.
**Why it matters:** Large diffs degrade per-line review attention; this is the mandated process flag the pipeline requires whenever a diff exceeds 400 LOC.
**Proposed fix:** No code change. Record that `allow_large_diff` was owner-approved for this milestone (the 5 tasks form one coherent registry system). Honest mitigation assessment: the risk is substantially reduced by strong, behavior-asserting coverage — 4 test files, ~57 tests, each acceptance path and owner decision exercised (schema idempotency, abstention round-trip, revision PK, cold reopen, GetRecord parse variants incl. deleted/idDoesNotExist, defusedxml, 503 backoff, redirect-pin, oversized-body, 3-way decision incl. nonexclusive-distrib, 3s politeness, idempotent zero-egress re-run, structural 0-re-embed import-scan guard, membership-from-papers.txt guard, coverage counts, >20%-unknown escalation, Decision-C not-allowlisted-open-does-not-escalate invariant, missing-registry fail state). The residual gaps are the specific untested edges called out in H2 and M1.
**Regression-guard:** N/A (process flag). The follow-up guards are the tests proposed under H2 and M1.
**Source critic:** milestone-adversary-critic
**Source axis:** Test discipline / diff size

**H2 — `Retry-After: 0` defeats the 503 backoff -> no-delay busy-loop against arXiv** (HIGH)

**Where:** `tools/oai_license.py:311`
**Anchor:** `wait = retry_after if retry_after is not None else backoff`
**What:** `_parse_retry_after` returns `max(0.0, float(value))` (line 238), so `Retry-After: 0` yields `0.0`; because `0.0 is not None`, the 503 loop takes `wait = 0.0`, `min(0.0, remaining) = 0.0`, `sleep(0.0)`, and the exponential `backoff` (which doubles each turn) is never consulted — a persistent `503 + Retry-After: 0` spins with zero inter-request delay until the 1-hour `retry_cap_seconds` wall clock is hit.
**Why it matters:** This module's entire reason for the self-contained fetch is the arXiv politeness contract (≤1 request / 3s). The busy-loop can exceed that by orders of magnitude for up to an hour, risking throttling or a ban of the operator's polite-pool contact email — and `Retry-After: 0` is a live-observed arXiv behavior: the sibling `tools/notebook_metadata_backfill.py` documents it verbatim ("arXiv has served Retry-After: 0, which would otherwise hammer") and defends against it by clamping via `tools.arxiv_fetch.parse_retry_after`. The bug is a faithful copy of the same unclamped pattern in `ingest/oai_delta.py:294` (so a pattern-level fix there is a reasonable separate follow-up), but this milestone chose the unclamped source when a clamped one already lived in the `tools.arxiv_fetch` module it imports.
**Proposed fix:** Clamp the honored wait to the politeness floor on the 503 path, e.g. `wait = max(wait, POLITENESS_SLEEP_SECONDS)` before `min(wait, remaining)` (or reuse `tools.arxiv_fetch.parse_retry_after(header, DEFAULT_...)` which already clamps to a default floor). This preserves honoring a server-requested longer delay while never dropping below the 3s contract.
**Regression-guard:** Add `tests/test_oai_license.py::test_retry_after_zero_is_floored` — feed a `503` with `Retry-After: 0`, assert the recorded `sleep` value is `>= POLITENESS_SLEEP_SECONDS` (and that the loop does not issue an unbounded number of requests within the cap).
**Source critic:** milestone-adversary-critic
**Source axis:** OAI-PMH client correctness (503/Retry-After/politeness)

**M1 — Missing parse-artifact is a silent NULL with no status marker (untested)** (MEDIUM)

**Where:** `tools/notebook_documents_backfill.py:204`
**Anchor:** `parse_artifact_sha256=_parse_artifact_sha256(`
**What:** `_parse_artifact_sha256` returns `None` when `parsed/<work_id>/index.html` is absent, and `_build_record` stores that `None` into a row that is still registered as a success (exit 0) with no companion status field — whereas the raw-source axis records the same gap as a first-class `raw_source_status='unavailable'` abstention marker.
**Why it matters:** The docstring asserts `index.html` is "present for ALL id shapes", but a `papers.txt` member whose parse failed (a real, tracked failure mode in this corpus) violates that assumption; the row then carries a NULL parse checksum indistinguishable from a populated one, silently failing AC1's "every registered revision row carries ... parse-artifact sha256" and the milestone's "abstention, not silence" principle on one of its two checksum axes.
**Proposed fix:** Either (a) treat a missing `index.html` as a per-id miss (do not write the row, so a re-run retries — same posture as a transient fetch failure), or (b) add a `parse_artifact_status` marker mirroring `raw_source_status` so the gap is explicit. Option (a) is the smaller change and keeps the "row == fully-provenanced" invariant.
**Regression-guard:** Add a backfill test with a member that has a raw tree + OAI license but NO `parsed/<id>/index.html`, asserting the chosen contract (row withheld as a miss, or row present with an explicit parse-abstention status) rather than a silent NULL.
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage (AC1 provenance completeness)

**L1 — Redirect-pin is a prefix match, not exact-origin** (LOW)

**Where:** `tools/oai_license.py:299`
**Anchor:** `if not response_url.startswith(OAI_PMH_ENDPOINT):`
**What:** The pin accepts any resolved URL that begins with `https://oaipmh.arxiv.org/oai`, so a same-host redirect to a different path (e.g. `https://oaipmh.arxiv.org/oai-anything`) would satisfy it; only off-host redirects are rejected.
**Why it matters:** Real risk is low — the check still binds egress to arXiv's own trusted OAI host, and a hostile same-host different-path redirect is not a realistic threat — but the pin is looser than an exact-origin/base-URL check would be, and it is a verbatim copy of `ingest/oai_delta.py`'s check.
**Proposed fix:** Optional; defer. If tightened, compare the parsed origin + path prefix explicitly (e.g. `urlsplit(response_url)` netloc equals `oaipmh.arxiv.org` and path starts with `/oai`), or match against the endpoint plus a `?`/`/` boundary.
**Regression-guard:** Optional.
**Source critic:** milestone-adversary-critic
**Source axis:** OAI-PMH client security (redirect pinning)

## What was done well

- **defusedxml on untrusted OAI-PMH XML.** `parse_getrecord` uses `defusedxml.ElementTree` (XXE / entity-expansion safe, Threat 7) and the test `test_parser_uses_defusedxml` asserts the stdlib `xml.etree.ElementTree` import is absent — a deliberate, tested divergence from `oai_delta.py`'s plain-ET choice.
- **Id validated before URL construction.** `build_getrecord_url` strips `vN` then runs `is_valid_arxiv_paper_id` before joining to `oai:arXiv.org:`, closing query-injection; old-style archive prefix + literal `/` are preserved unescaped and verified (`test_old_style_prefix_and_slash_preserved_unescaped`).
- **Atomic, re-runnable schema migration.** The v0->v1 create wraps `CREATE TABLE IF NOT EXISTS` + `PRAGMA user_version=1` in an explicit BEGIN/COMMIT with ROLLBACK-on-exception, and `test_migration_is_rerunnable_without_data_loss` reproduces the user_version-lags-tables crash window and proves it re-migrates without data loss.
- **Structural (not incidental) 0-re-embed.** The backfill imports no embedder / `ingest.store` / lancedb, and `test_driver_imports_no_embedder_store_or_lancedb` enforces it by scanning IMPORT LINES only (so the docstring naming `ingest.store` to say it is NOT imported can't false-positive) — plus a sentinel test that a run leaves a stand-in LanceDB marker byte-identical.
- **Advisory 3-way license_status with no folding.** `decide_license_status` maps CC-family -> `eligible`, `nonexclusive-distrib` -> `not-allowlisted-open`, None/empty -> `unknown`, with the CC markers deliberately narrow (by-nc / by-nd fall through), and `server/license_policy.py` is grep-confirmed untouched — the m4 cutover is not pre-empted.
- **Abstention-not-silence for raw source.** NULL `raw_source_sha256` always travels with `raw_source_status='unavailable'`, round-trips (`test_abstention_marker_round_trips`), and the old-style prefix-intact id is the only valid key (bare number rejected) — tested both in the store and end-to-end in the backfill.
- **Revision-grained PK.** `(work_id, arxiv_version)` retains the version the rest of the codebase strips; `test_distinct_versions_are_distinct_rows` proves v1 and v2 are two rows, and the version-slice `line.strip()[len(work_id):]` is exact because `strip_id_version` uses an end-anchored `v\d+\Z` regex.
- **Politeness owned by the caller and tested.** `fetch_license` never sleeps (`test_fetch_license_does_not_sleep`); the driver sleeps 3s before every request except the first (`test_three_second_spacing_between_requests` asserts exactly two sleeps for three papers), and an idempotent re-run performs zero network egress (`test_rerun_is_noop_with_zero_network_egress`).
- **idDoesNotExist vs transient-miss distinction.** `idDoesNotExist` is a terminal per-paper `unknown` that WRITES a row and exits 0, whereas a transient fetch failure writes NO row (so a re-run retries) and exits 1 — both directions are tested, including the re-run-retries-only-the-missed-id path.
- **Owner Decision C escalation is precise.** The coverage gate is on `unknown` alone; `test_not_allowlisted_open_does_not_trigger_escalation` proves a 70%-`not-allowlisted-open` notebook with 10% unknown does NOT escalate while still reporting `not-allowlisted-open=7` prominently, and a missing/empty registry is a loud non-zero fail state. No `assert`-for-invariant appears in any of the four production files; both commits are GPG-signed with the `Co-Authored-By: Claude Opus 4.8` trailer.

Severity counts: C0 H2 M1 L1

## Recommended rectification order

H2, M1, H1, L1
