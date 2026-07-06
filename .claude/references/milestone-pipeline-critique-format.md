# Canonical critique format

Every critic writes a markdown file matching this exact shape. The dedupe
script (`milestone-pipeline-dedupe-findings.py`) parses the finding heading
and the `**Where:**` line — deviate and your findings silently drop out of
dedup and the severity counts.

## File layout

```markdown
# Critique — <id> — <critic-name>

**Critic:** <milestone-adversary-critic | milestone-oss-scout | overlay name>
**Commit range:** <base-sha>..<head-sha>
**Diff stats:** <files-changed> files, <loc-changed> LOC

## Verdict

One of: SHIP / SHIP-WITH-FIXES / DO-NOT-SHIP

(One paragraph, ≤ 4 sentences, justifying the verdict.)

## Executive summary

- ≤ 8 bullets summarizing the most important findings.
- Each bullet starts with severity in brackets, e.g. `[CRITICAL]`.
- Concrete; no hedging.

## Findings

(Zero or more findings in the per-finding template below, ordered
CRITICAL → HIGH → MEDIUM → LOW.)

## What was done well

(REQUIRED. 5–10 bullets. An empty section reads adversarial-for-its-own-sake
and triggers a re-dispatch.)

## Recommended rectification order

(Ordered list of finding ids, e.g. `C1, H1, H3, M1`. Phase 4 follows this
order by default. The dedupe script inserts its "Cross-critic agreement"
section immediately BEFORE this heading — keep the heading verbatim.)

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>
```

## Per-finding template (parser-load-bearing)

```markdown
### <SEVERITY> — <short title under 70 chars>

**Where:** `path/to/file.ext:123`
**Anchor:** `<first 40 chars of the cited line, verbatim>`
**What:** <One sentence describing what is wrong.>
**Why it matters:** <One sentence on the consequence.>
**Proposed fix:** <One short paragraph; pseudo-code or a one-line patch is fine.>
**Regression-guard:** <CRITICAL + HIGH: the test/assert that catches regression. MEDIUM + LOW: optional.>
**Source critic:** <agent name>
**Source axis:** <axis name, if applicable>
```

Parser contract:

- Heading: `### <SEVERITY> — <title>` where SEVERITY ∈ CRITICAL | HIGH |
  MEDIUM | LOW, at heading level 3 exactly. Em-dash or hyphen separator both
  parse.
- `**Where:**` at line start, with a backticked `` `file:line` `` citation.
  The line number is a SINGLE integer (for a range, cite the first line).
  Cross-cutting findings may say `**Where:** no specific file` — they are
  kept but excluded from dedup clustering.

## Finding ids

Critics do NOT number their own findings. Ids are synthesized at parse time
as `<severity-initial><serial>` in file order (C1, C2, H1, M1, L1, ...) over
the merged `critique/dedup.md`. The rectification order and Phase 4 records
use these merged ids.

## Dedup semantics

The orchestrator concatenates all critic files into `critique/dedup.md`
(adversary first, then overlays, then oss) and runs
`milestone-pipeline-dedupe-findings.py` on it. Findings within ±5 lines of
the same file are clustered into a "Cross-critic agreement" callout — the
strongest fix-first signal. Idempotent: re-running on a deduped file is a
no-op. Severity counts are derived by grepping `^### CRITICAL` etc. on the
merged file — another reason the heading shape is load-bearing.

## Severity calibration anchors

- **CRITICAL** — production breaks or a contract violation (external write
  in the diff, one-writer rule violation, production change with zero test
  deltas, unsigned/untrailered commit, CLAUDE.md contradicted).
- **HIGH** — likely-to-cause-incident bug, unmet acceptance criterion,
  security exposure, dependency license/CVE problem, diff > 400 LOC.
- **MEDIUM** — subtle bug, perf regression, or doc drift; fix only if cheap
  (≤ 30 LOC).
- **LOW** — style, naming, micro-optimization; defer by default.

If a finding maps to no clear analog, demote one level. Never invent a
CRITICAL. Zero CRITICALs and two HIGHs is a credible critique — padding
severity erodes signal.

## Worked example

```markdown
### HIGH — Acceptance criterion 2 has no covering test

**Where:** `src/index/store.py:88`
**Anchor:** `def reopen(self, path: Path) -> Index:`
**What:** The "no rebuild on reopen" criterion is implemented but nothing asserts it.
**Why it matters:** A future refactor can silently regress the criterion the milestone exists to deliver.
**Proposed fix:** Add a test that builds the index, reopens the store, and asserts zero rebuild work was scheduled.
**Regression-guard:** tests/test_store_reopen.py::test_reopen_is_norebuild
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage
```
