
## paper-metadata (2026-07-05)
- RICE honestly ranked the small payoff epic (e2, e=0.75) above its blocking enabler (e1) — value density and execution order legitimately diverge; depends_on carries the ordering, do not fudge factors to force rank = sequence.
- Both epics defaulted c=0.5 (no usage evidence for a solo research corpus) — surfaced by name; recurring pattern for arXMCP internal-tooling roadmaps.
- Compact now/next split for a 2-epic roadmap: now = must epic fully spec'd (spike + m1 + 4 tasks), next = the should epic's single shaped milestone with acceptance but no task decomposition.

## data-plane-governance (2026-07-11)
- Days-scale docs+git-state governance track: all 3 milestones legitimately land in the now lane of one 2-week cycle — the "now = musts only" heuristic yields to capacity fit when the whole track is <1 week of work and a downstream gate needs multiple epics merged (R1-R7 tool-surface changes blocked on m1+m3).
- An owner-behavior must assumption ("owner dispositions six plans in one sitting") takes a decision-spike, not a technical prototype: the spike IS the time-boxed sitting over a prepared disposition matrix, with the deferral fallback in its acceptance — while the owner-gated outcome also stays inside the milestone's acceptance as observable git state.
- c above the 0.5 default is citable when a briefs README structurally gates downstream tracks on the epic's outputs (documented dependency = reach evidence); record the citation as a trailing comment on the rice line. The owner-gated epic stayed c=0.5 — its delivery hinges on the unvalidated assumption itself.
- The 60% cap on 3 epics allows exactly 1 must; a program gate that jointly blocks on two epics' milestones (m1+m3) does not make both epics must — depends_on plus all-now lanes carry joint criticality without breaking the cap.

## source-truth (2026-07-11)
- 4-epic diamond DAG (e1->{e2,e3}->e4): lanes fell out as now = root must epic fully spec'd, next = the dependent must (L) + top should shaped, later = the owner-gated join epic; a bottom-tie in RICE (e3/e4 both 3.0, shared rank 3) is fine — depends_on carries the execution order, don't fudge factors to break ties.
- Split the L-sized must epic into a data-layer milestone (m2) and a separate W1-riding tool-surface milestone (m5, depends_on m2) so an external schema-window slip can't drag the migration work; mirrored retrieval-unlocks' W1 acceptance wording including the standalone-re-pin fallback.
- Owner-gated cutovers belong in later with the gates written into summary (not acceptance) — promotion to now writes the GWT when the owner gate opens; the earlier-checkable gates (manifest re-verify, zero-re-embed backfill) landed as acceptance on the next-lane milestones that own them.
- c=0.8 justified once via a sibling roadmap's shipped spike data (paper-metadata-spike-1 measured Atom per-field coverage on the same ID shapes/client); everything else defaulted c=0.5 — the recurring no-usage-evidence pattern for arXMCP internal tooling.
- Front-loading the dependent epic's must-assumption spike (printed-number coverage) into the now lane alongside the root epic's work de-risks the next wave without violating lane-dependency rules (next may depend on now, never the reverse).
