# Chaos run 2026-08-22 — finding schema

Every lane appends one JSON object per line to `findings-<lane>.jsonl`.
NEVER truncate the list. Report every finding, including duplicates of
another lane's — dedup happens at synthesis, not at write time.

```json
{
  "id": "CHAOS-<LANE>-<NN>",
  "lane": "supervisor|packaging|api|frontend|data",
  "severity": "critical|high|medium|low|info",
  "area": "supervisor|server|frontend|packaging|data|ingest",
  "title": "one line, <= 80 chars",
  "repro": "exact shell commands or steps, copy-pasteable",
  "observed": "what actually happened, verbatim output where possible",
  "expected": "what should have happened and why (cite file:line or doc)",
  "evidence": "path to log/screenshot in evidence/, or inline excerpt",
  "code_ref": "file:line of the responsible code, or null",
  "reproducible": "always|intermittent|once",
  "status": "open",
  "first_seen": "2026-08-22"
}
```

Severity rubric:
- critical — data loss, corpus corruption, RCE, auth bypass, orphaned process
  that survives quit, app cannot start at all.
- high — crash, hang > 60s, wrong results returned to the user, token leak in
  logs, UI shows stale/wrong state with no error.
- medium — bad error message, missing error state in UI, resource leak that
  self-heals, degraded but correct.
- low — cosmetic, copy, a11y nit, log noise.
- info — behaviour worth recording, not a defect.
