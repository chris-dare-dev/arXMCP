# capability-scout-challenger — lessons

<!-- Append one generalizable lesson per line as scout runs surface them.
     Format: `YYYY-MM-DD [<scout-id>] <lesson>`. Append only; do not delete. -->

2026-05-28 [2026q2-notebook-ux-storage-ops] Synthesis routinely forwards [VERIFY] candidates without executing the verification inline; any [VERIFY] flag should be resolved by the challenger via direct file inspection before assigning severity — in this run, CAND-7 (Dockerfile HEALTHCHECK) was already shipped and should have been killed at synthesis, not deferred to the challenger.
