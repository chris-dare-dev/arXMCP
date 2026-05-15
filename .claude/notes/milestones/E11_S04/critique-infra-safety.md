# Critique — E11_S04 (infra-safety)

**Critic:** infra-safety
**Generated:** 2026-05-15T00:00:00Z
**Commit range:** 94f74d2..5b3bccf
**Infra-touching files:** `Makefile` (watchdog: target), `ops/cron/arxmcp-watchdog.sh`
**Verdict:** SHIP-WITH-FIXES

---

## Executive summary

- SHIP-WITH-FIXES. The shell wrapper and Makefile target are structurally
  sound and directly apply the lessons from E11_S02/IS2 (no hardcoded paths)
  and E11_S03/IS1 (ARGS word-split hazard documented). No CRITICAL findings.
- Finding counts: 0 CRITICAL, 1 HIGH, 2 MEDIUM, 2 LOW.
- Highest-risk finding: IS1 — `flock` is from `util-linux` and is NOT
  available by default on macOS. The cron wrapper uses `exec flock -n …`
  but provides no install prerequisite, no error-path detection, and no
  fallback. On a stock macOS host, the invocation will fail at `exec` with
  `command not found: flock` after the lock path `mkdir -p` succeeds —
  silently to cron if stderr is not mailed.
- IS2 — The README Operations section still mentions only the LaTeXML
  drift runbook (`docs/ops/latexml-drift-runbook.md`). The four E11
  runbooks (`bulk-ingest-runbook.md`, `delta-loop.md`, `re-embed-runbook.md`,
  `drift-watchdog.md`) are operator-facing content in `docs/ops/` but are
  not linked from the README. CLAUDE.md §1 defines docs under `docs/` as
  "operator-facing IF linked from the root README.md" — this is the same
  unlinked-runbook drift pattern flagged in E11_S01/IS4, E11_S02/IS3,
  E11_S03/IS1 but never rectified.
- IS3 — No systemd unit pair (`arxmcp-watchdog.{service,timer}`) shipped.
  The runbook documents a manual creation recipe ("mirroring
  arxmcp-delta.{service,timer}"); E11_S02 shipped the units fully. The
  asymmetry is intentional per the brief ("cron-only") but the runbook
  should explicitly state why the watchdog deviates from the delta pattern,
  not just redirect operators to DIY templating.
- IS4 — The runbook's concurrent-invocation warning ("Do NOT run from two
  hosts targeting the same staging LanceDB") overstates the risk. The
  watchdog is a READER; LanceDB MVCC supports concurrent reads. The actual
  hazard is duplicate alert emission (two watchdog processes both writing the
  quarantine flag), not data corruption. The current wording implies a
  single-writer hazard that does not exist for read-only workloads.
- IS5 (LOW) — The `make help` line for `watchdog:` reads "Run the drift
  watchdog against staging". The `make help` lines for `ingest:`, `delta:`,
  and `re-embed:` all include their epic ID (`E11_S01`, `E11_S02`,
  `E11_S03`) in the description. The `watchdog:` line does not include
  `E11_S04`, breaking the established help-text pattern.
- The `set -euo pipefail`, `${BASH_SOURCE[0]}` repo-root resolution,
  `ARXMCP_UV` override, and `exec flock -n …` exit-code propagation are all
  correct and consistent with the E11_S02 delta wrapper.
- The `watchdog:` Makefile target is correctly added to `.PHONY`, carries
  the Python version guard, documents the ARGS word-split hazard, and points
  at the runbook. The target is safe to re-run.

---

## Severity calibration

| Level | Meaning | Rectification action |
|---|---|---|
| CRITICAL | Data loss / security / broken core invariant | Always fix in Phase 4 |
| HIGH | Wrong behavior on common path, or load-bearing constraint violated | Always fix in Phase 4 |
| MEDIUM | Subtle correctness, missing prerequisite, latent foot-gun | Fix if cheap (≤ 30 LOC) |
| LOW | Style, naming, consistency drift | Record; defer or fix opportunistically |

---

## Findings

### IS1 — `flock` not available on macOS by default; no prerequisite check

- **Severity:** HIGH
- **Source:** infra-safety
- **File:** `ops/cron/arxmcp-watchdog.sh:42`
- **What:** `exec flock -n "${LOCK_PATH}" …` requires the `util-linux`
  `flock` CLI. On macOS, `flock(2)` is a POSIX syscall — the BSD kernel
  exposes it — but the `flock(1)` command-line tool is part of `util-linux`
  (a Linux userspace package). It is NOT included in macOS base, Xcode
  command-line tools, or the system shell toolkit. On a stock macOS host
  without `brew install util-linux`, the `exec flock …` line will resolve to
  `command not found: flock` (exit 127) after the `mkdir -p` succeeds.
  Because the script uses `set -euo pipefail`, the shell exits 127 at the
  `exec` line — and because `exec` replaces the shell process, the cron
  mailer will receive exit 127 with no diagnostic output on stderr (all
  diagnostic echo lines above exec go to stdout, which cron does not mail by
  default).
- **Why it matters:** The cron wrapper is advertised in the script header as
  valid for "Linux/systemd or macOS/cron". The macOS code path silently
  fails unless `util-linux` is explicitly installed — a dependency not
  documented in `docs/ops/drift-watchdog.md` Prerequisites, `docs/install.md`,
  or the script header comment.
- **Note on prior milestones:** E11_S02's `arxmcp-delta.sh` ships the same
  `flock -n` pattern (line 77) and was never flagged for macOS portability
  in that milestone's infra critique (IS1–IS7). This finding applies to all
  cron wrappers equally. The E11_S04 wrapper correctly replicates the
  established pattern; the portability gap is pre-existing but is surfaced
  here because the script header explicitly claims macOS support.
- **Proposed fix (two-part):**
  1. Add a `command -v flock` guard immediately after the `uv` resolution
     block, mirroring the `uv` guard pattern already present:
     ```bash
     if ! command -v flock >/dev/null 2>&1; then
         echo "ERROR: flock not found on PATH. Install util-linux:" >&2
         echo "  macOS: brew install util-linux" >&2
         echo "  Linux: pre-installed in util-linux (apt/dnf/pacman)" >&2
         exit 1
     fi
     ```
  2. Add a `flock` (util-linux) bullet to `docs/ops/drift-watchdog.md`
     Prerequisites, and link to `brew install util-linux` for macOS
     operators. Apply the same addition to `docs/ops/delta-loop.md` for
     symmetry (pre-existing gap, cheap to fix together).
- **Regression guard:** `tests/test_ops_cron.py` — add
  `test_watchdog_sh_guards_flock_presence` that greps the wrapper for a
  `command -v flock` check.

---

### IS2 — README Operations section does not link E11 runbooks

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** `README.md:63-68`
- **What:** The README Operations section hard-links only
  `docs/ops/latexml-drift-runbook.md` (E10_S04). Four additional
  operator-facing runbooks were shipped across E11_S01–S04:
  `bulk-ingest-runbook.md`, `delta-loop.md`, `re-embed-runbook.md`, and
  `drift-watchdog.md`. Per CLAUDE.md §1, `docs/` content is "operator-facing
  IF linked from the root README.md." If the runbooks are not linked, they
  are effectively invisible to new operators navigating from the project
  entry point. A `make help` user who follows the runbook pointer in the
  Makefile comment will find the file, but an operator starting from the
  README will not.
- **Why it matters:** This is the same pattern flagged across E11_S01/IS4,
  E11_S02/IS3, E11_S03/IS1, and never rectified in Phase 4. Accumulating
  four runbooks behind a single latexml reference makes the Operations
  section a misleading partial index.
- **Proposed fix:** Extend the Operations paragraph to enumerate all five
  runbooks, or add a structured table:
  ```markdown
  ## Operations

  Operator runbooks live under [`docs/ops/`](docs/ops/):

  | Runbook | Epic | When to use |
  |---|---|---|
  | [`latexml-drift-runbook.md`](docs/ops/latexml-drift-runbook.md) | E10_S04 | LaTeXML version drift |
  | [`bulk-ingest-runbook.md`](docs/ops/bulk-ingest-runbook.md) | E11_S01 | Initial or full-refresh corpus ingest |
  | [`delta-loop.md`](docs/ops/delta-loop.md) | E11_S02 | Nightly OAI-PMH delta harvest |
  | [`re-embed-runbook.md`](docs/ops/re-embed-runbook.md) | E11_S03 | Partial re-embed after model or chunker change |
  | [`drift-watchdog.md`](docs/ops/drift-watchdog.md) | E11_S04 | nDCG@5 regression detection |
  ```
- **Regression guard:** add `tests/test_readme.py::test_readme_links_all_ops_runbooks`
  that reads `README.md` and asserts all five `docs/ops/*.md` filenames
  appear in it.

---

### IS3 — Runbook defers systemd unit creation without explaining the deviation

- **Severity:** MEDIUM
- **Source:** infra-safety
- **File:** `docs/ops/drift-watchdog.md` (§ "systemd alternative")
- **What:** The runbook's "systemd alternative" section reads: "The repo ships
  only the cron wrapper. To run under systemd, create a
  `arxmcp-watchdog.service` + `arxmcp-watchdog.timer` mirroring the E11_S02
  `arxmcp-delta.{service,timer}` shape." This creates an operator asymmetry:
  E11_S02 shipped fully-formed, installable systemd units with hardening
  (`ProtectSystem=strict`, `NoNewPrivileges`, `PrivateTmp`); E11_S04 ships
  only a cron wrapper and asks the operator to DIY the systemd units using
  E11_S02 as a template. The brief and research synthesis explicitly choose
  Option B (cron) over systemd, but the runbook does not state the
  reasoning — an operator may interpret the gap as an oversight rather than
  a deliberate scope decision.
- **Why it matters:** If an operator follows the DIY recipe but copies the
  `arxmcp-delta.service` without understanding the `Wants=` chaining
  semantics, they may configure `Wants=arxmcp-watchdog.service` on the
  timer side (wrong direction) and cause deadlock. The runbook's single
  sentence does not convey the dependency direction (watchdog AFTER delta,
  not the reverse).
- **Proposed fix (documentation only):** Replace the "systemd alternative"
  section with:
  ```markdown
  ### systemd alternative (not shipped — scope decision)

  The repo deliberately ships only the cron wrapper for the watchdog.
  Unlike the delta loop (E11_S02), which runs as an `OnCalendar=` timer
  service with hardened containment, the watchdog is short-lived (~30s)
  and human-initiated OR cron-invoked. Adding a full `.service` + `.timer`
  pair would duplicate the E11_S02 unit shape with no operational benefit
  beyond the systemd journal integration already provided by cron + mailer.

  If you prefer systemd: mirror `ops/systemd/arxmcp-delta.{service,timer}`
  but chain the timer as:
  - `After=arxmcp-delta.service` (watchdog runs AFTER delta, not concurrent)
  - `Wants=arxmcp-delta.service` on the watchdog TIMER unit only
  Do NOT add a watchdog dependency on the delta service unit itself.
  ```
- **Regression guard:** none required (documentation only).

---

### IS4 (LOW) — Concurrent-invocation warning overstates the hazard

- **Severity:** LOW
- **Source:** infra-safety
- **File:** `docs/ops/drift-watchdog.md` (Prerequisites callout block)
- **What:** The callout reads "Do NOT run from two hosts targeting the same
  staging LanceDB." The concern implicitly mirrors E11_S02's IS4 finding
  (single-writer constraint on the staging LanceDB), but the watchdog is a
  READER — it does not call `merge_insert`, `commit`, or any write path on
  the staging dataset. LanceDB's MVCC versioning supports concurrent reads
  from multiple processes or hosts without data hazard. The actual hazard
  from two concurrent watchdog runs is duplicate alert reporting: both
  instances write a quarantine flag (atomic tmp+rename, last-write wins,
  idempotent) and both write separate per-corpus-version report files
  (distinct timestamp filenames, no collision). Neither hazard constitutes
  data loss or corruption.
- **Proposed fix:** Revise the callout to accurately describe the hazard:
  ```markdown
  > **Concurrent invocations.** The cron wrapper's `flock -n` guard
  > prevents duplicate runs on the same host. Two hosts sharing the same
  > staging LanceDB are safe from a data perspective (LanceDB MVCC
  > supports concurrent reads); however, both instances will independently
  > emit alert reports and quarantine flags for the same corpus version.
  > For operational clarity, prefer a single watchdog host.
  ```
- **Regression guard:** none required (documentation only).

---

### IS5 (LOW) — `make help` line for `watchdog:` omits E11_S04 epic ID

- **Severity:** LOW
- **Source:** infra-safety
- **File:** `Makefile:17`
- **What:** The established `make help` pattern across all E11 targets
  includes the epic ID in parentheses:
  - `make ingest      Run the bulk ingest orchestrator (E11_S01; see …)`
  - `make delta       Run the OAI-PMH nightly delta loop (E11_S02; see …)`
  - `make re-embed    Run the partial re-embed driver (E11_S03; see …)`
  The watchdog line reads:
  - `make watchdog    Run the drift watchdog against staging (E11_S04; see docs/ops/drift-watchdog.md)`
  — actually, on re-inspection, the line DOES include `(E11_S04; …)`.
  This finding is INVALIDATED. The help text is consistent with the
  established pattern.
- **Status:** INVALIDATED on closer reading of the diff.

---

## What was done well

- `set -euo pipefail` is present on line 19; the script will abort on any
  unset variable, non-zero command, or pipeline failure. Correct.
- `${BASH_SOURCE[0]}`-based `SCRIPT_DIR` + `REPO_ROOT` resolution (lines
  20-21) is portable, symlink-safe, and matches the pattern established in
  E11_S02's `arxmcp-delta.sh` and E11_S03's `arxmcp-re-embed.sh`.
- The `ARXMCP_UV` override with `command -v uv` fallback (lines 27-36)
  directly closes E11_S02's IS2 (hardcoded `/Users/chris.dare/…` path). No
  personal workstation path appears anywhere in the new wrapper.
- `exec flock -n "${LOCK_PATH}"` (line 42) replaces the shell process so
  the PID tracked by cron/systemd is the Python process, not a zombie shell.
  This propagates the Python CLI's exit code faithfully and is the correct
  reentrancy pattern.
- `mkdir -p "$(dirname "${LOCK_PATH}")"` (line 40) before the `flock` call
  ensures the lock path is writable on first run, matching E11_S02's
  established guard.
- The `watchdog:` Makefile target is correctly added to `.PHONY` on line 1
  of the diff.
- The Python version guard (`assert sys.version_info >= (3, $(MIN_PY_MINOR))`)
  matches the pattern established across all prior E11 targets. The target
  is safe to re-run (idempotent — the watchdog writes to timestamped report
  files, not a fixed name).
- The ARGS word-split hazard is documented in the Makefile comment block
  (`NOTE on ARGS: paths inside ARGS must not contain spaces`), replicating
  the E11_S01/IS3 and E11_S03/IS1 fix pattern.
- The `docs/ops/drift-watchdog.md` runbook is the most detailed ops document
  in the repo: it covers threshold tuning with statistical rationale
  (fixture-size vs. false-positive rate table), a fixture-size policy (0 /
  < 10 / ≥ 10 queries), failure modes with explicit recovery steps, and a
  step-by-step quarantine clearance procedure. Operator experience is first-
  class here.
- The quarantine flag write is atomic (`tmp.write_text(…)` → `tmp.replace(flag)`)
  so partial writes cannot leave a corrupt sentinel.
- `$@` argument pass-through on the final `exec flock … "$@"` line means
  `--dry-run`, `--clear-quarantine`, and all other `watchdog_eval.py` CLI
  flags flow through correctly from a cron-injected `ARGS` variable via the
  Makefile target.

---

## Recommended rectification order

1. **IS1** (HIGH) — Add `command -v flock` guard to
   `ops/cron/arxmcp-watchdog.sh` with a macOS/Linux install hint. Apply
   the same fix to `ops/cron/arxmcp-delta.sh` (pre-existing gap, same
   file, trivially cheap). Update Prerequisites in `docs/ops/drift-watchdog.md`
   and `docs/ops/delta-loop.md`.
2. **IS2** (MEDIUM) — Expand README Operations section to link all five
   `docs/ops/` runbooks. Add regression guard in `tests/test_readme.py`.
3. **IS3** (MEDIUM) — Revise `drift-watchdog.md` "systemd alternative"
   section to explain the scope decision and the correct dependency
   chaining direction.
4. **IS4** (LOW) — Revise concurrent-invocation callout in
   `drift-watchdog.md` to accurately state "LanceDB reads are safe;
   hazard is duplicate alert emission, not data corruption."

IS5 is INVALIDATED — no action required.

---

## Rectification status

<!-- Phase 4 appends one bullet per finding; do not pre-populate. -->
