# Critique — proof-verify-handler-wiring-m3 (merged)

**Critics fired:** adversary (1; infra-safety / oss-scout / frontend-UX
did not fire — no infra paths in diff, no OSS-scout opt-in, no frontend
exists by design).

**Verdict:** SHIP-WITH-FIXES (adversary).

## Findings summary

| ID | Sev | Source | Title | Phase-4 status |
|---|---|---|---|---|
| F1 | HIGH | adversary | `pkill -f "ARXMCP_LANCEDB_PATH=..."` recipe cannot find daemon (env vars not in argv) | CLOSED — switched both launch and restart recipes to a PID-file pattern; added a kill-verify post-step |
| F2 | MEDIUM | adversary | Bind-host validator cite points at `validate_port_range` (line 323) instead of `reject_non_loopback_bind` (line 294) | CLOSED — cite corrected to `server/config.py:294`; symbol name now linked inline |
| F3 | MEDIUM | adversary | `.where(paper_id IN ...)` cite range `449-454` points at unrelated Tier-2 cache code; real call is at line 468 inside `span_ann` block 463-468 | CLOSED — cite corrected to `server/handlers/search.py:463-468` with `span_ann` framing |
| F4 | LOW | adversary | `filters_applied` cite `218-232` points at docstring not injection body | CLOSED — folded into F3 edit; cite widened to full `_inject_filters_applied` function range `195-241` and linked to the symbol name |

## Rectification artifacts

- `docs/ops/notebook-modes.md` — three edits:
  - **F1 launch recipe** (Mode 1 §Launch): added `mkdir -p .../ops`,
    `echo $! > .../daemon.pid`, and a code comment naming the env-vars-
    not-in-argv reason. Both Notebook A (`export VAR=...`) and Notebook B
    (inline `VAR=val cmd`) examples updated.
  - **F1 kill recipe** (Mode 1 §Restart after ingest): replaced
    `pkill -f "ARXMCP_LANCEDB_PATH=.*..."` with
    `kill -TERM "$(cat $PID_FILE)"` + post-kill `ps -p` verification
    + a code comment naming F1 explicitly so a future doc edit doesn't
    silently revert.
  - **F2 cite** (Mode 1 §Launch trailing paragraph): bind-host validator
    cite moved from `server/config.py:323` to `server/config.py:294`;
    symbol name `reject_non_loopback_bind` now linked.
  - **F3+F4 cites** (Mode 2 §What): `.where(...)` cite range moved from
    `449-454` to `463-468` with `span_ann` framing; `filters_applied`
    cite widened from `218-232` (docstring-only) to `195-241` (whole
    function) with the `_inject_filters_applied` symbol now linked.

## Final test count

`make test`: **2259 passed, 9 skipped, 1 xfailed.** Unchanged from the
m3 feat baseline (pure-docs rect; no source-tree files touched). Ruff
clean.

## Deferred findings

None. All 4 findings (1 HIGH + 2 MEDIUM + 1 LOW) closed in one rect
commit. No findings deferred.

## Re-verify gate notes

All 4 findings re-verified before fixing. Source line numbers at write
time:
- F2: `reject_non_loopback_bind` confirmed at `server/config.py:294`;
  `validate_port_range` confirmed at `server/config.py:325` (the
  doc's old cite at `:323` is the `@field_validator` decorator one
  line above).
- F3: `.search(...).where(paper_id_predicate, prefilter=True)` chain
  confirmed at `server/handlers/search.py:468`, inside `with
  span_ann(k=k):` at line 463.
- F4: `_inject_filters_applied` confirmed at lines 195-241 (docstring
  + body); injection logic specifically at lines 234-241.
- F1: env-var-not-in-argv behavior confirmed empirically — `env FOO=bar
  sleep 0.1` shows `command = sleep 0.1` in `ps`, no `FOO=bar` prefix.

Zero findings invalidated. Adversary invalidation rate: 0 / 4 (0%) —
well under the 40% threshold; critic prompt is calibrated correctly.

## Cross-critic agreement

N/A — only one critic fired (adversary). Infra-safety did not fire
(no infra paths in diff). OSS-scout is opt-in only. Frontend-UX does
not apply to arXMCP by design.
