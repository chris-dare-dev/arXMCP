# Canonical critique format

Every critic (adversary, infra-safety, OSS-scout, future additions)
writes its output as a markdown file at the path the orchestrator
declares. The format below is enforced because `dedupe-findings.py`
parses it: deviating means cross-critic agreement won't be detected.

## File layout

```markdown
# Critique — <milestone-id>

**Critic:** adversary | infra-safety | oss-scout
**Generated:** <ISO-8601 UTC>
**Commit range:** <base..head>
**Verdict:** SHIP | SHIP-WITH-FIXES | DO-NOT-SHIP

## Executive summary

- Up to 8 bullets. First bullet states the verdict and the single most
  load-bearing reason for it.
- Mention finding counts (e.g. "3 CRITICAL, 1 HIGH, 4 MEDIUM, 2 LOW").
- Flag the highest-risk file, if any, with file:line.
- Note any cross-axis pattern worth pulling forward.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

A critic that flags everything CRITICAL is a broken critic. Inflate
severity once and the prompt stops pulling its weight.

## Findings

Group findings by severity, CRITICAL → HIGH → MEDIUM → LOW. Use
`### F<n> — <title>` headings exactly. The `F<n>` ID is what Phase 4
records in `fixed_findings` / `deferred_findings`.

### F1 — <one-line title, ≤ 70 chars>

- **Severity:** CRITICAL
- **Source:** adversary | infra-safety | oss-scout
- **File:** path/to/file.py:42
- **What:** the observed behavior. Two sentences max.
- **Why it matters:** the consequence. One sentence — name the
  invariant, the user-visible bug, or the constraint violated.
- **Proposed fix:** concrete change. File path + diff sketch is fine.
  Don't over-specify; the rectifier re-verifies before applying.
- **Regression guard:** what test / assertion / snapshot to add so
  this finding cannot reappear silently. Required for CRITICAL + HIGH.

(repeat for F2, F3, …)

## What was done well

5–10 bullets. Required section. Empty = adversarial-for-its-own-sake
critic, which the orchestrator should treat as a broken prompt and
either re-dispatch or down-weight.

## Recommended rectification order

Numbered list, highest-leverage-first. Account for blast radius and
fix interdependencies — don't propose F4 before F1 if F4 sits on the
same code path F1 will rewrite.

## Rectification status (filled by Phase 4)

<!-- Phase 4 appends one bullet per finding; do not pre-populate. -->

- F1 — fixed in <sha> (regression guard: tests/foo_test.py::test_bar)
- F2 — invalidated by re-verify (cited file:line no longer matches)
- F3 — deferred (reason: out of scope; tracked at <ref>)
```

## Findings ID convention

- `F<n>` for adversary findings
- `IS<n>` for infra-safety findings
- `OS<n>` for oss-scout findings
- `UX<n>` reserved for the frontend-UX critic (this project ships no
  frontend, so this prefix should not appear)

This is what `dedupe-findings.py` keys on for cross-critic agreement.
A region of code flagged by `F2` (adversary) AND `IS3` (infra-safety)
is almost always a real issue and deserves the highest rectification
priority.

## The 40% invalidation heuristic

If Phase 4's re-verify gate strips ≥ 40% of a single critic's CRITICAL
+ HIGH findings, the critic prompt is functionally noise on this run.
The orchestrator records the rate in `state.invalidated_findings` and
surfaces it in the rect commit body. **40% is a defensible heuristic,
not a published number** — tune from real runs. The point is to have a
metric that fires before you've spent another dollar on the same
broken prompt.

## Don'ts

- **Don't merge multiple findings into one heading.** One finding per
  `### F<n>`. Composite findings break dedup, hide severity, and lose
  fix-tracking.
- **Don't omit `**File:**`** even when the finding is project-wide.
  Pick the most representative file:line — `dedupe-findings.py` keys
  on it and a missing field excludes the finding from cross-critic
  agreement.
- **Don't write critique narrative outside the headings above.** The
  rectifier reads the file as structured data; prose between sections
  is just noise.
- **Don't pre-populate the rectification status section.** Phase 4
  fills it. A pre-filled section confuses replay.
