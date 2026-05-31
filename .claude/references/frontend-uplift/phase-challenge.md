# Phase 3 — CHALLENGE (sub-agent)

**Purpose:** dispatch a single sub-agent (the Challenger) to argue AGAINST each modernization candidate so Phase 4 prioritization receives honest signal about feasibility, accessibility risk, bundle cost, and arXMCP-design-system fit.  Mirrors `/capability-scout` Phase 3 but specialized for frontend concerns.

## Inputs

- `.claude/notes/frontend-uplifts/{ID}/artifacts/synthesis.md`
- (Optional) the 4 discover briefs under `.claude/notes/frontend-uplifts/{ID}/discover/` for ground-checking the synthesis against its sources.

## Output

`.claude/notes/frontend-uplifts/{ID}/artifacts/challenge.md`

## Dispatch

Single `Agent` call with `subagent_type: frontend-uplift-challenger`, sonnet, `isolation: worktree`. The canonical Challenger system prompt is in the agent file at `.claude/agents/frontend-uplift-challenger.md`; the orchestrator passes a short user prompt that supplies the placeholders below.

Substitute:
- `{ID}` → uplift slug
- `{SYNTHESIS_PATH}` → `.claude/notes/frontend-uplifts/{ID}/artifacts/synthesis.md`
- `{CHALLENGE_PATH}` → `.claude/notes/frontend-uplifts/{ID}/artifacts/challenge.md`

## Severity rubric (Challenger-specific)

The challenger uses the 4-tier rubric mapped to the standard format for state-field consistency:

| Challenger tier | Maps to standard severity | Meaning |
|---|---|---|
| **BLOCKER** | CRITICAL | Must be dropped or fundamentally redesigned.  Examples: any npm-installable library (React / Tailwind / shadcn / Framer Motion / Recharts / Zustand / TanStack — automatic BLOCKER per CLAUDE.md §4.7), motion-vocabulary §8 anti-pattern (parallax on operator console, magnetic-cursor on destructive button, etc.), license-incompatible vendored asset, CSP-widening change without justification. |
| **MAJOR** | HIGH | Shippable but with significant cost the synthesis didn't surface.  Examples: vendored single-file >20 KB gz without justification (the htmx baseline is ~14 KB); a11y regression with no remediation plan; `prefers-reduced-motion` gate missing across a key path; CSP impact not declared; expansion of the un-audited UI surface (`chris-dare-dev/arXMCP#9`) without flagging. |
| **MINOR** | MEDIUM | Light scope adjustment.  Examples: token name drift, missing `aria-hidden` on a decorative icon, `prefers-reduced-motion` gate missing on a single class, `:focus-visible` styling missing on a single new interactive element. |
| **NONE** | LOW (clean) | Candidate survives.  Aim for 30–60% of candidates rating NONE — that's calibrated. |

## The 10-axis FRONTEND-CHALLENGER checklist

Every candidate gets evaluated against (calibrated to arXMCP's stack — see the agent file `.claude/agents/frontend-uplift-challenger.md` for the canonical list and binding):

1. **No-build-chain compliance (CLAUDE.md §4.7)** — npm / Node / bundler / React / Tailwind / shadcn / Framer / Recharts / Zustand / TanStack = automatic BLOCKER
2. **`prefers-reduced-motion` honored** — `@media (prefers-reduced-motion: no-preference)` gate required on every new animation; arXMCP's CSS has ZERO such blocks today
3. **Accessibility regression risk** — WCAG AA contrast vs the 8 CSS variables, keyboard nav, screen-reader semantics, ARIA roles, `aria-live` on htmx swap targets, `:focus-visible` story
4. **Vendored-asset weight** — new vendored JS >20 KB gz needs explicit justification (htmx baseline ~14 KB)
5. **CSP impact** — stays within `script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'`; flag any new external resource / inline-eval / Web Worker / WebSocket; UI security audit is OPEN
6. **Mobile responsiveness consideration** — single-operator loopback-only may de-prioritize mobile; refusing mobile entirely without acknowledgement is MAJOR
7. **Token discipline (arXMCP's 8 CSS variables)** — `--fg`, `--bg`, `--card-bg`, `--border`, `--accent`, `--danger`, `--error-bg`, `--mono`; new tokens must be added explicitly (not parallel-defined)
8. **Effort honesty** — t-shirt size matches arXMCP historical frontend milestone sizes (notebook-surface-expansion m1–m7 is the realistic effort grain)
9. **Motion-vocabulary anti-pattern** — explicitly check candidate against motion-vocabulary.md §8
10. **Sequencing dependencies** — DAG between candidates (e.g. `prefers-reduced-motion` block must land before any new animation candidate)

## After receiving the challenge

Parse the challenge to populate:

```bash
.claude/scripts/frontend-uplift/checkpoint.py <ID> --set challenge_path='".claude/notes/frontend-uplifts/<ID>/artifacts/challenge.md"'
.claude/scripts/frontend-uplift/checkpoint.py <ID> --set challenge_finding_counts='{"critical":N_BLOCKER,"high":N_MAJOR,"medium":N_MINOR,"low":N_CLEAN}'
.claude/scripts/frontend-uplift/checkpoint.py <ID> challenge-complete
```

## Anti-patterns

| Tempting belief | Reality |
|---|---|
| ">50% of candidates have MAJOR or BLOCKER objections — the synthesis was bad." | Possible.  More often, the synthesis under-considered the no-build-chain lock or proposed npm-installable libraries (which are automatic BLOCKERs). Re-read with §4.7 in mind before re-running. |
| "Every candidate must have AT LEAST a MINOR objection." | NO.  A clean NONE is a credible verdict.  Calibrated runs see 30–60% NONE. |
| "BLOCKER findings should kill candidates outright." | Not always.  A BLOCKER + a credible redesign sketch leaves Phase 4 deciding whether the redesigned candidate is worth pursuing. |
| "The challenger should propose its own candidates." | NO.  Phase 1's job.  Challenger evaluates the synthesis; it does not extend it. |
