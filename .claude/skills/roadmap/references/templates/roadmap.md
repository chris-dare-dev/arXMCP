# {{TITLE}} — Roadmap

**Slug:** `{{SLUG}}`
**Created:** {{CREATED}}
**Status:** init

<!--
This roadmap is itself the state. Re-invoking the `roadmap` skill on
this file resumes from the first un-populated phase. Sections below
contain `{{TOKEN}}` placeholders until their phase runs.

Phases:
  1. REFINE     — How-Might-We, sharpening questions, assumptions, OKR, Won't list
  2. DECOMPOSE  — technique, epics, INVEST, specialist suggestions
  3. SEQUENCE   — MoSCoW, RICE, Now/Next/Later, spike lane, Now-lane milestones
  4. MATERIALIZE — validation results, optional GitHub bundle, next-step handoff
-->

---

## Phase 1 — Refine

<!-- status: pending -->
<!-- populated by REFINE phase; do not edit other phases until this one is complete -->

### How Might We

{{HMW}}

### Sharpening questions answered

{{SHARPENING}}

### Assumptions

- `[MUST]` {{MUST_ASSUMPTION_1}}
- `[SHOULD]` {{SHOULD_ASSUMPTION_1}}
- `[MIGHT]` {{MIGHT_ASSUMPTION_1}}

### Objective

{{OBJECTIVE}}

### Key Results

1. {{KR_1}}
2. {{KR_2}}
3. {{KR_3}}

### Won't (explicit out-of-scope)

- {{WONT_1}}

---

## Phase 2 — Decompose

<!-- status: pending -->
<!-- populated by DECOMPOSE phase -->

### Technique

{{TECHNIQUE}}

<!-- Default: vertical slicing + enabler stories. Deviate explicitly with reason. -->

### Epics

#### {{SLUG}}-e1 — {{EPIC_1_TITLE}}

- **Type:** value | enabler
- **Specialist suggestion:** {{SPECIALIST_1}}
- **Outcome:** {{EPIC_1_OUTCOME}}
- **Estimated size:** S | M | L
- **INVEST check:** I/N/V/E/S/T — {{NOTES}}

(repeat for each epic; cap 2–6 epics, each ≤ 6 weeks)

---

## Phase 3 — Sequence

<!-- status: pending -->
<!-- populated by SEQUENCE phase -->

### MoSCoW assignment

- **Must** (≤ 60% of total effort): {{MUST_LIST}}
- **Should**: {{SHOULD_LIST}}
- **Could**: {{COULD_LIST}}
- **Won't (this cycle)**: {{WONT_LIST}}

### RICE ranking — Musts

| ID | Reach | Impact | Confidence | Effort | Score |
|---|---|---|---|---|---|
{{RICE_TABLE}}

### Now / Next / Later

- **Now** (fully spec'd, in-flight or next-up): {{NOW_LIST}}
- **Next** (shaped, awaiting capacity): {{NEXT_LIST}}
- **Later** (outcome-only, low-confidence horizon): {{LATER_LIST}}

### Spike / discovery lane

- `{{SLUG}}-spike-1` — {{SPIKE_1_DESCRIPTION}} (≤ 3 days, validates `[MUST]` assumption: {{ASSUMPTION_REF}})

### Milestones — Now lane

<!--
Each Now-lane milestone is its own H3 below. Heading format is
`### <slug>-mN — Title` exactly — milestone-pipeline's init-state.sh
greps for this. Do not change it.
-->

### {{SLUG}}-m1 — {{MILESTONE_1_TITLE}}

**Description.** {{MILESTONE_1_DESC}}

**Acceptance criteria.**
- [ ] {{AC_1}}

**Dependencies.** {{DEPS}}

**Complexity.** S | M | L

**Specialist suggestion.** {{SPECIALIST}}

(repeat for each Now-lane milestone; each ≤ 3 days execution; ≤ 5 files touched preferred)

---

## Phase 4 — Materialize

<!-- status: pending -->
<!-- populated by MATERIALIZE phase -->

### Validation

- `validate-roadmap.py`: {{VALIDATE_RESULT}}
- Must-cap: {{MUST_PCT}}% (≤ 60%)
- All Now-lane milestones have AC: {{AC_RESULT}}
- Slug format valid: {{SLUG_VALID}}

### GitHub tickets

{{GITHUB_BUNDLE}}

<!-- If `--github` was passed, this section names the per-issue body files
under `plans/{{SLUG}}-tickets/` and the `create-tickets.sh` script the user
runs manually to invoke `gh issue create`. The skill never invokes `gh`. -->

### Next step

{{NEXT_STEP}}

<!-- Default suggestion: run `milestone-pipeline {{SLUG}}-m1` for the first
Now-lane milestone. Offered, not auto-invoked. -->

---

<!-- end:roadmap -->
