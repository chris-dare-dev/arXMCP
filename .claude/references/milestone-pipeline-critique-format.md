# Canonical critique format

Every critic writes a markdown file matching this exact shape. The findings
register (`milestone-pipeline-findings.py`) parses the finding header, the
`**Where:**` citation, and the per-finding body fields — deviate and `extract`
fails LOUD (it refuses the whole file and lists every malformed block; it never
silently drops a finding).

**Critique format version:** 1.0

## What changed in v1.0 (authored ids)

Critics now **author their own finding ids** (`C1`, `H2`, ...) in the header,
instead of the register synthesizing them by file order. Authored ids are
stable: inserting a finding no longer renumbers the ones after it, so a
disposition recorded in Phase 4 (`fixed` / `deferred` / `invalidated`) stays
attached to the finding it was about across a re-`extract`. The id-letter must
agree with the severity (`C`↔CRITICAL, `H`↔HIGH, `M`↔MEDIUM, `L`↔LOW); the
parser rejects a mismatch.

## File layout

```markdown
# Critique — <id> — <critic-name>

**Critic:** <milestone-adversary-critic | milestone-oss-scout | overlay name>
**Commit range:** <base-sha>..<head-sha>
**Diff stats:** <files-changed> files, <loc-changed> LOC
**Critique format version:** 1.0

## Verdict

One of: SHIP / SHIP-WITH-FIXES / DO-NOT-SHIP

(One paragraph, ≤ 4 sentences, justifying the verdict.)

## Executive summary

- ≤ 8 bullets summarizing the most important findings.
- Each bullet starts with severity in brackets, e.g. `[CRITICAL]`.
- Concrete; no hedging.

## Findings

(Zero or more findings in the per-finding template below, ordered
CRITICAL → HIGH → MEDIUM → LOW. Number within each severity from 1:
C1, C2, ..., H1, H2, ..., M1, ..., L1, ...)

## What was done well

(REQUIRED. 5–10 bullets. An empty section reads adversarial-for-its-own-sake
and triggers a re-dispatch.)

Severity counts: C<n> H<n> M<n> L<n>

## Recommended rectification order

(Ordered list of finding ids, e.g. `C1, H1, H3, M1`. Phase 4 follows this
order by default. The dedupe step inserts its "Cross-critic agreement"
section immediately BEFORE this heading — keep the heading verbatim.)

## Phase 4 status (filled by orchestrator at rectify time)

- Fixed: <finding ids>
- Deferred: <finding ids>
- Invalidated: <finding ids with reasons>
- Regression tests added: <file paths>
```

## Per-finding template (parser-load-bearing)

```markdown
**C1 — <short title under 70 chars>** (CRITICAL)

**Where:** `path/to/file.ext:123`
**Anchor:** `<first 40 chars of the cited line, verbatim>`
**What:** <One sentence describing what is wrong.>
**Why it matters:** <One sentence on the consequence.>
**Proposed fix:** <One short paragraph; pseudo-code or a one-line patch is fine.>
**Regression-guard:** <CRITICAL + HIGH: the test/assert that catches regression. MEDIUM + LOW: optional.>
**Source critic:** <agent name>
**Source axis:** <axis name, if applicable>
```

Parser contract (enforced by `milestone-pipeline-findings.py extract`):

- **Header**: `**<id> — <title>** (<SEVERITY>)` where the id is
  `<letter><serial>` (letter ∈ C | H | M | L), SEVERITY ∈ CRITICAL | HIGH |
  MEDIUM | LOW, and the letter matches the severity. Em-dash or hyphen
  separator both parse. The whole header is one bold span on its own line
  with the severity in a trailing paren.
- **`**Where:**`** at line start, with a backticked `` `file:line` `` citation.
  The line number is a SINGLE integer (for a range, cite the first line).
  Cross-cutting findings may say `**Where:** no specific file` — they are
  kept but excluded from dedup clustering.
- **Required body fields**: `**What:**`, `**Why it matters:**`,
  `**Proposed fix:**`, `**Regression-guard:**`, `**Source critic:**`. A
  finding missing any of these is a malformed block; `extract` refuses the
  whole file.
- **`**Anchor:**`** and **`**Source axis:**`** are parsed but optional — the
  Anchor is what the Phase-4 re-verification protocol re-locates the finding
  by, so include it for every CRITICAL + HIGH.

Example finding headers that appear inside ``` fenced blocks (like the ones in
this document) are NOT parsed — the parser blanks fenced code before scanning,
so documentation examples never leak into a register.

## Severity counts line

A `Severity counts: C<n> H<n> M<n> L<n>` line (place it just before the
`## Recommended rectification order` heading, or in the header block) records
the author's own tally. If present, it MUST equal the parsed count — a drifted
line means a finding was added or removed without updating it, and `extract`
flags it. The register never trusts this line for the gate; it is an
author-error tripwire, and `summary --counts-for` re-derives counts by parsing.

## Dedup semantics

The orchestrator concatenates all critic files into `critique/dedup.md`
(adversary first, then overlays, then oss) and runs
`milestone-pipeline-findings.py dedupe` on it. Findings within ±5 lines of the
same file are clustered into a "Cross-critic agreement" callout — the strongest
fix-first signal, labelled with the cluster's MOST-severe member. The dedupe
step runs through the same fail-loud parser: a malformed or uncited finding
BLOCKS (it never silently vanishes). Idempotent: re-running on a deduped file
is a no-op.

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
**H1 — Acceptance criterion 2 has no covering test** (HIGH)

**Where:** `src/index/store.py:88`
**Anchor:** `def reopen(self, path: Path) -> Index:`
**What:** The "no rebuild on reopen" criterion is implemented but nothing asserts it.
**Why it matters:** A future refactor can silently regress the criterion the milestone exists to deliver.
**Proposed fix:** Add a test that builds the index, reopens the store, and asserts zero rebuild work was scheduled.
**Regression-guard:** tests/test_store_reopen.py::test_reopen_is_norebuild
**Source critic:** milestone-adversary-critic
**Source axis:** Acceptance coverage
```
