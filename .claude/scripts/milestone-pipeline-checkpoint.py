#!/usr/bin/env python3
"""Advance milestone state to the next phase, or read/write a state field.

Usage:
  milestone-pipeline-checkpoint.py <ID> <new-phase>             # advance state
  milestone-pipeline-checkpoint.py <ID> --get <field>           # read a top-level field
  milestone-pipeline-checkpoint.py <ID> --set <field>=<json>    # set a top-level field
  milestone-pipeline-checkpoint.py <ID> --append <field>=<json> # append to a list field
  milestone-pipeline-checkpoint.py --self-test                  # tempdir refusal fixtures

Phase advancement is validated against the state machine:
  init -> research-running -> research-complete
       -> implement-running -> implement-complete
       -> critique-running -> critique-complete
       -> rectify-running -> complete

Refuses backward transitions and skipped phases.  Writes atomically.

Some transitions additionally require state fields to be populated FIRST
(--set them before advancing).  This is the drift-guard for the class of runs
that reached 'complete' with research/implementation/critique evidence never
recorded:

  research-complete   requires research_briefs (non-empty list of brief paths),
                      research_mode (str; one of standard|deep|single -- enum-
                      checked at --set and at transition)
  implement-complete  requires implementation_base (str),
                      implementation_commit_range (str)
  critique-complete   requires critique_path (str), critics_run (non-empty list),
                      critique_files (non-empty list -- one path per critic that
                      fired), critique_finding_counts (dict with int critical/
                      high/medium/low -- null means "never recorded"; a real
                      zero-findings run sets all-zero counts), AND
                      findings_register (str -- the repo-relative path Phase 3's
                      `extract` wrote; the "new-format run" marker, round-4 F5:
                      it lets 'complete' distinguish a legacy run that never had
                      a register from a new run whose register was skipped/lost)
  complete            requires rectification_commit (str), AND the external-write
                      ledger to balance.  The ledger is an ARRAY model (downstream
                      keeps required/completed/authorized as lists, NOT a bool):
                      every entry of external_writes_required must appear in BOTH
                      external_writes_completed AND external_writes_authorized
                      (an empty required list = nothing to authorize).
                      ADDITIONALLY (round-4 F5, sharpened):
                      - findings_register SET (new-format run): the canonical
                        register (<state-dir>/findings.json) must exist (missing
                        = extract skipped or register lost -- refuse; the
                        findings gate itself no-ops on a missing register, so
                        this F5 distinction is enforced HERE), and
                        `milestone-pipeline-findings.py gate <id>` must pass
                        (no open CRITICAL/HIGH).
                      - findings_register NULL (legacy/ad-hoc run): the gate
                        runs only if <state-dir>/findings.json happens to exist
                        (defense in depth); else skipped -- same skip semantics
                        as the findings gate for unregistered ids.
                      The gate logic lives ONLY in the findings script (one
                      authority; it locates the register from <id> via the same
                      repo-root resolution); this is a subprocess invocation.

Type mismatches refuse the transition (a placeholder string smuggled into a
list/dict field via --set's plain-string fallback does NOT pass the guard).

Concurrency: milestone-pipeline-init-state.sh holds the whole-pipeline
.claude/notes/milestones/.lock (one milestone at a time), and each write here is
atomic (temp + os.replace in the same directory).  No fcntl lock -- POSIX flock
crashes on win32 and the .lock already serializes sessions.

Repo-root detection (in order):
  1. $REPO_ROOT env var if set
  2. `git rev-parse --show-toplevel` from CWD if currently inside a git repo
  3. Walk up from this script's dir to the nearest .git/
  4. parents[2] -- a synced copy lives at <root>/.claude/scripts/<file>, so the
     grandparent of the scripts dir is the repo root even in a bare checkout.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Force UTF-8 stdout/stderr so any non-ASCII content does not crash on Windows
# default cp1252 codepage.  All print() statements in this module use ASCII,
# but defensive output via --get on stored JSON strings could include any UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

try:
    from datetime import UTC, datetime
except ImportError:  # pragma: no cover -- Python <3.11 fallback
    from datetime import datetime, timezone  # noqa: UP017

    UTC = timezone.utc  # type: ignore[assignment]  # noqa: UP017

# Milestone-id containment (round-4 F10): the id becomes a path segment under
# .claude/notes/milestones/ -- separators or a leading dot would escape the
# state dir ('../evil').  This is the permissive-but-traversal-containing
# superset of init-state.sh's stricter id shapes (<slug>-mN | <slug>-spike-N |
# adhoc-YYYYMMDD-<sha7>); keep it in sync with milestone-pipeline-findings.py.
MILESTONE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

PHASE_ORDER = [
    "init",
    "research-running",
    "research-complete",
    "implement-running",
    "implement-complete",
    "critique-running",
    "critique-complete",
    "rectify-running",
    "complete",
]

# field -> expected python type; checked when the field is a transition
# requirement AND at --set time (a placeholder string smuggled into a list/dict
# field refuses).
FIELD_TYPES: dict[str, type] = {
    "research_briefs": list,
    "research_mode": str,
    "implementation_base": str,
    "implementation_commit_range": str,
    "implementation_commits": list,
    "critique_path": str,
    "critics_run": list,
    "critique_files": list,
    "critique_finding_counts": dict,
    "findings_register": str,
    "rectification_commit": str,
    "fixed_findings": list,
    "deferred_findings": list,
    "invalidated_findings": list,
    # Ledger fields (round-4 F3): a plain-string required-list iterates per
    # CHARACTER in the complete balance check and can false-pass when completed
    # carries the same string.  Typed at --set here AND at the transition below.
    # external_writes_authorized is a LIST downstream (approved items), not the
    # upstream bool.
    "external_writes_required": list,
    "external_writes_completed": list,
    "external_writes_authorized": list,
}

# Fields that must be populated (non-null, non-empty, correctly typed) BEFORE
# the transition is allowed.  'complete' has additional ledger + findings-gate
# semantics below.
REQUIRED_FIELDS_BY_PHASE: dict[str, list[str]] = {
    "research-complete": ["research_briefs", "research_mode"],
    "implement-complete": ["implementation_base", "implementation_commit_range"],
    "critique-complete": [
        "critique_path",
        "critics_run",
        "critique_files",
        "critique_finding_counts",
        "findings_register",
    ],
    "complete": ["rectification_commit"],
}

# The full state.json schema (kept in sync with init-state.sh's skeleton --
# the two files are coupled through FIELD_TYPES / REQUIRED_FIELDS).
# --set may CREATE a key that older state files predate IF it is listed here
# (schema evolution -- e.g. findings_register on a pre-round-4 state.json);
# truly unknown fields still refuse.  Without this, the documented escape for
# wedged in-flight runs ("--set the new field manually") could never work.
KNOWN_FIELDS = {
    "id", "created_at", "updated_at", "phase", "phase_history",
    "milestone_brief", "brief_source", "research_mode", "oss_scout_requested",
    "allow_large_diff", "research_briefs", "research_synthesis",
    "implementation_path", "implementation_plan", "implementation_base",
    "implementation_commit_range", "implementation_commits", "implementation_branch",
    "external_writes_required", "critique_path", "critics_run", "critique_files",
    "critique_finding_counts", "findings_register", "rectification_commit",
    "fixed_findings", "deferred_findings", "invalidated_findings",
    "regression_tests_added", "external_writes_authorized", "external_writes_completed",
}

COUNT_KEYS = ("critical", "high", "medium", "low")

# The findings-gate authority (subprocess target for the 'complete' transition).
# Module-level so the self-test can point it at a nonexistent path to prove the
# missing-script branch refuses (fail-loud, never skip a present register).
FINDINGS_SCRIPT = Path(__file__).resolve().parent / "milestone-pipeline-findings.py"

# Enum-valued fields: type-valid but out-of-vocabulary values are exactly the
# placeholder-class content the guards exist to catch ("standrad" is not
# evidence).  Checked at --set AND at transition time.
FIELD_ENUMS: dict[str, set[str]] = {
    "research_mode": {"standard", "deep", "single"},
    "implementation_path": {"inline", "delegated"},
}


def _find_repo_root() -> Path:
    env = os.environ.get("REPO_ROOT")
    if env:
        p = Path(env)
        if p.is_dir():
            return p
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if out:
            return Path(out)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    # Walk up from this script's own dir to the nearest .git/.
    here = Path(__file__).resolve().parent
    for candidate in [here, *here.parents]:
        if (candidate / ".git").exists():
            return candidate
    # Final fallback: a synced copy lives at <root>/.claude/scripts/<file>, so
    # parents[2] is the repo root even when there is no .git/ (bare checkout).
    return Path(__file__).resolve().parents[2]


def _state_path(mid: str) -> Path:
    if not MILESTONE_ID_RE.match(mid) or "/" in mid or "\\" in mid:
        sys.exit(
            f"invalid milestone id {mid!r} -- ids are [A-Za-z0-9][A-Za-z0-9._-]* "
            "(no path separators; the id is a directory segment under "
            ".claude/notes/milestones/)"
        )
    return _find_repo_root() / ".claude" / "notes" / "milestones" / mid / "state.json"


def _load(state_path: Path) -> dict:
    if not state_path.exists():
        sys.exit(
            f"state.json not found at {state_path} "
            "-- run milestone-pipeline-init-state.sh first"
        )
    return json.loads(state_path.read_text(encoding="utf-8"))


def _save_atomic(state_path: Path, state: dict) -> None:
    tmp = state_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, state_path)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_ledger(state: dict, problems: list[str]) -> None:
    """Balance the external-write ledger (array model) at the complete gate."""
    required = state.get("external_writes_required")
    completed = state.get("external_writes_completed")
    authorized = state.get("external_writes_authorized")
    # Type-check the ledger BEFORE the balance check (round-4 F3): a plain
    # string in required/completed/authorized iterates per CHARACTER below and
    # can false-pass when both carry the same string.  Mistyped = refuse.
    ledger_typed = True
    for fname, fval in (
        ("external_writes_required", required),
        ("external_writes_completed", completed),
        ("external_writes_authorized", authorized),
    ):
        if fval is not None and not isinstance(fval, list):
            problems.append(
                f"{fname} has type {type(fval).__name__}, expected list "
                "(a string ledger false-passes the balance check -- re-set it as "
                "a proper JSON array)"
            )
            ledger_typed = False
    if not ledger_typed:
        return
    required = required or []
    completed = completed or []
    authorized = authorized or []
    missing_completed = [w for w in required if w not in completed]
    if missing_completed:
        problems.append(
            "external writes required but not recorded as completed: "
            + "; ".join(missing_completed)
        )
    # Array model: authorization is recorded per-item, not a single bool. Every
    # required item must be explicitly approved (authorization recorded, not
    # merely performed).
    missing_authorized = [w for w in required if w not in authorized]
    if missing_authorized:
        problems.append(
            "external writes required but not authorized: "
            + "; ".join(missing_authorized)
        )


def _check_findings_gate(state: dict, state_path: Path, problems: list[str]) -> None:
    """Subprocess-invoke the findings gate (one authority) at the complete gate.

    The downstream findings script takes the milestone id and locates the
    register itself (<root>/.claude/notes/milestones/<id>/findings.json) via the
    same repo-root resolution; it no-ops (exit 0) on a missing register and
    exits 3 on any open CRITICAL/HIGH.

    marker SET (new-format run)  -> register must exist (F5 refusal HERE, since
                                    the gate itself would no-op) AND gate passes
    marker NULL (legacy/ad-hoc)  -> gate only if the canonical file exists
    """
    marker = state.get("findings_register")
    if marker is not None and not (isinstance(marker, str) and marker.strip()):
        problems.append(
            "findings_register is set but not a non-empty string (hand-mangled state?)"
        )
        marker = None
    # The register the findings gate will actually read (canonical location).
    canonical_reg = state_path.parent / "findings.json"
    if marker and not canonical_reg.is_file():
        # F5: a new-format run must not complete ungated. The gate no-ops on a
        # missing register, so this distinction is enforced here, not delegated.
        problems.append(
            f"findings_register is set ({marker}) but no register exists at "
            f"{canonical_reg} -- Phase 3's extract was skipped or the register "
            "was lost; re-run extract (round-4 F5)"
        )
        return
    have_register = marker is not None or canonical_reg.is_file()
    if not have_register:
        return  # legacy/ad-hoc run -- nothing to gate
    if not FINDINGS_SCRIPT.is_file():
        problems.append(
            f"findings register exists ({canonical_reg}) but the gate script is "
            f"missing ({FINDINGS_SCRIPT}) -- cannot verify open CRITICAL/HIGH "
            "findings; restore the script (fail-loud, never skip a present register)"
        )
        return
    proc = subprocess.run(
        [sys.executable, str(FINDINGS_SCRIPT), "gate", state["id"]],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        problems.append(
            "findings gate refused:\n    "
            + (proc.stderr or proc.stdout).rstrip().replace("\n", "\n    ")
        )
    elif "deferrable" in proc.stdout:
        # Open MEDIUM/LOW findings are deferrable -- the gate passes but prints a
        # note; surface it so the operator sees them at the terminal gate.
        print(proc.stdout.rstrip())


def _check_required_fields(state: dict, new_phase: str, state_path: Path) -> None:
    """Refuse a transition whose evidence fields were never recorded (or mistyped)."""
    problems: list[str] = []
    for field in REQUIRED_FIELDS_BY_PHASE.get(new_phase, []):
        val = state.get(field)
        if val is None or (isinstance(val, (list, str, dict)) and not val):
            problems.append(f"{field} not recorded")
            continue
        want = FIELD_TYPES.get(field)
        if want and not isinstance(val, want):
            problems.append(
                f"{field} has type {type(val).__name__}, expected {want.__name__} "
                "(a placeholder pasted through --set's plain-string fallback?)"
            )
            continue
        allowed = FIELD_ENUMS.get(field)
        if allowed and val not in allowed:
            problems.append(f"{field} value {val!r} is not one of {sorted(allowed)}")
            continue
        if field == "critique_finding_counts":
            bad = [
                k for k in COUNT_KEYS
                if not isinstance(val.get(k), int) or isinstance(val.get(k), bool)
            ]
            if bad:
                problems.append(
                    f"critique_finding_counts missing/non-int keys: {', '.join(bad)}"
                )

    if new_phase == "complete":
        _check_ledger(state, problems)
        _check_findings_gate(state, state_path, problems)

    if problems:
        sys.exit(
            f"refusing transition to {new_phase}:\n  - "
            + "\n  - ".join(problems)
            + "\n--set the fields first (see docstring) -- this is the drift-guard; "
            "do not bypass it by writing state.json directly."
        )


def advance(mid: str, new_phase: str) -> None:
    if new_phase not in PHASE_ORDER:
        sys.exit(f"unknown phase: {new_phase}. Valid: {', '.join(PHASE_ORDER)}")
    sp = _state_path(mid)
    state = _load(sp)
    cur = state["phase"]
    cur_idx = PHASE_ORDER.index(cur)
    new_idx = PHASE_ORDER.index(new_phase)
    if new_idx <= cur_idx:
        sys.exit(f"refusing backward/same transition: {cur} -> {new_phase}")
    if new_idx - cur_idx > 1:
        sys.exit(
            f"refusing skipped transition: {cur} -> {new_phase} "
            "(must advance one step at a time)"
        )
    _check_required_fields(state, new_phase, sp)
    now = _now()
    state["phase"] = new_phase
    state["updated_at"] = now
    state["phase_history"].append({"phase": new_phase, "at": now})
    _save_atomic(sp, state)
    print(f"{mid}: {cur} -> {new_phase} @ {now}")


def get_field(mid: str, field: str) -> None:
    """Print the value of <field> on stdout.

    Exit codes:
      0  field has a non-None value (printed on stdout, possibly empty string)
      2  field exists in schema but is None (i.e. never set) -- diagnostic on stderr

    The exit-code split lets bash callers distinguish "never set" from
    "explicitly empty string".  Use `if VAL=$(... --get foo); then ...` to
    branch on whether the field was populated.
    """
    state = _load(_state_path(mid))
    if field not in state:
        sys.exit(f"unknown field: {field}. Valid: {', '.join(state.keys())}")
    val = state[field]
    if val is None:
        print(f"field {field!r} is unset (None)", file=sys.stderr)
        sys.exit(2)
    if isinstance(val, (dict, list)):
        print(json.dumps(val, indent=2))
    else:
        print(val)


def set_field(mid: str, expr: str) -> None:
    if "=" not in expr:
        sys.exit("--set value must be field=<json>")
    field, raw = expr.split("=", 1)
    field = field.strip()
    try:
        val = json.loads(raw)
    except json.JSONDecodeError:
        val = raw  # treat as plain string
    want = FIELD_TYPES.get(field)
    if want and not isinstance(val, want):
        sys.exit(
            f"--set {field}: expected {want.__name__}, got {type(val).__name__} "
            f"({json.dumps(val)[:60]}). Pass valid JSON of the right type."
        )
    allowed = FIELD_ENUMS.get(field)
    if allowed and val is not None and val not in allowed:
        sys.exit(f"--set {field}: {val!r} is not one of {sorted(allowed)}")
    sp = _state_path(mid)
    state = _load(sp)
    if field not in state and field not in KNOWN_FIELDS:
        # Not present AND not a known-schema field -> refuse. A known field that
        # a pre-round-4 state.json predates is allowed through (schema evolution,
        # the documented wedge escape).
        sys.exit(f"unknown field: {field}. Add it to the schema first.")
    state[field] = val
    state["updated_at"] = _now()
    _save_atomic(sp, state)
    print(f"{mid}: set {field} = {json.dumps(val)[:80]}")


def append_field(mid: str, expr: str) -> None:
    if "=" not in expr:
        sys.exit("--append value must be field=<json>")
    field, raw = expr.split("=", 1)
    field = field.strip()
    try:
        val = json.loads(raw)
    except json.JSONDecodeError:
        val = raw
    sp = _state_path(mid)
    state = _load(sp)
    if field not in state:
        sys.exit(f"unknown field: {field}. Add it to the schema first.")
    if not isinstance(state[field], list):
        sys.exit(f"field {field!r} is not a list ({type(state[field]).__name__})")
    state[field].append(val)
    state["updated_at"] = _now()
    _save_atomic(sp, state)
    print(f"{mid}: appended to {field} (new length {len(state[field])})")


# ---------------------------------------------------------------- self-test


def self_test() -> int:
    """Tempdir fixtures for every transition-guard refusal path.

    Includes a real subprocess assertion against milestone-pipeline-findings.py
    so the cross-script gate CLI contract (gate --register <path>, non-zero on
    open C/H) is pinned, plus a missing-script simulation via FINDINGS_SCRIPT.
    The real-subprocess assertions are SKIPPED when the sibling script is not
    yet present (it is a separate deliverable) so this harness still exits 0.
    """
    import contextlib
    import io
    import tempfile

    global FINDINGS_SCRIPT
    failures = 0

    def expect(name: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"  {name}: {'ok' if ok else f'FAIL {detail}'}")
        if not ok:
            failures += 1

    def run_main(argv: list[str]) -> tuple[int, str]:
        """Run main() capturing exit code + combined output (SystemExit-safe)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                main(["checkpoint.py", *argv])
                rc = 0
            except SystemExit as exc:
                if isinstance(exc.code, int) or exc.code is None:
                    rc = exc.code or 0
                else:
                    out.write(str(exc.code) + "\n")
                    rc = 1
        return rc, out.getvalue()

    def write_state(sdir: Path, **overrides) -> None:
        # Mirrors init-state.sh's downstream skeleton: implementation_plan,
        # array external_writes_authorized, null findings_register +
        # critique_finding_counts.
        state = {
            "id": "t1", "created_at": "t", "updated_at": "t",
            "phase": "init", "phase_history": [{"phase": "init", "at": "t"}],
            "milestone_brief": "b", "brief_source": "inline",
            "research_mode": None, "oss_scout_requested": False,
            "allow_large_diff": False, "research_briefs": [],
            "research_synthesis": None, "implementation_path": None,
            "implementation_plan": None, "implementation_base": None,
            "implementation_commit_range": None, "implementation_commits": [],
            "implementation_branch": None, "external_writes_required": [],
            "critique_path": None, "critics_run": [], "critique_files": [],
            "critique_finding_counts": None, "findings_register": None,
            "rectification_commit": None,
            "fixed_findings": [], "deferred_findings": [], "invalidated_findings": [],
            "regression_tests_added": [],
            "external_writes_authorized": [], "external_writes_completed": [],
        }
        state.update(overrides)
        (sdir / "state.json").write_text(json.dumps(state))

    print("self-test: milestone-pipeline-checkpoint.py")
    real_script = FINDINGS_SCRIPT
    findings_available = real_script.is_file()
    prev_repo_root = os.environ.get("REPO_ROOT")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        os.environ["REPO_ROOT"] = str(root)
        sdir = root / ".claude" / "notes" / "milestones" / "t1"
        sdir.mkdir(parents=True)
        write_state(sdir)

        # phase-machine basics
        rc, out = run_main(["t1", "research-complete"])
        expect("skipped transition refused", rc != 0 and "skipped" in out, out.strip()[:80])
        rc, out = run_main(["t1", "research-running"])
        expect("forward transition ok", rc == 0, out.strip()[:80])
        rc, out = run_main(["t1", "init"])
        expect("backward transition refused", rc != 0, out.strip()[:80])

        # research-complete evidence gate
        rc, out = run_main(["t1", "research-complete"])
        expect("research-complete refused w/o evidence",
               rc != 0 and "research_briefs" in out, out.strip()[:80])
        rc, out = run_main(["t1", "--set", 'research_mode="standrad"'])
        expect("research_mode enum refused at --set",
               rc != 0 and "standrad" in out, out.strip()[:80])
        run_main(["t1", "--set", 'research_briefs=["research/a.md"]'])
        run_main(["t1", "--set", 'research_mode="single"'])
        rc, out = run_main(["t1", "research-complete"])
        expect("research-complete passes with evidence", rc == 0, out.strip()[:80])

        # typed --set
        rc, out = run_main(["t1", "--set", 'critics_run="milestone-adversary-critic"'])
        expect("mistyped --set refused", rc != 0 and "expected list" in out, out.strip()[:80])

        # implement-complete evidence gate
        run_main(["t1", "implement-running"])
        rc, out = run_main(["t1", "implement-complete"])
        expect("implement-complete refused w/o base+range", rc != 0, out.strip()[:80])
        run_main(["t1", "--set", 'implementation_base="aaa"'])
        run_main(["t1", "--set", 'implementation_commit_range="aaa..bbb"'])
        rc, out = run_main(["t1", "implement-complete"])
        expect("implement-complete passes", rc == 0, out.strip()[:80])

        # critique-complete evidence gate
        run_main(["t1", "critique-running"])
        rc, out = run_main(["t1", "critique-complete"])
        expect("critique-complete refused w/o evidence",
               rc != 0 and "critique_files" in out, out.strip()[:80])
        run_main(["t1", "--set", 'critique_path="critique/dedup.md"'])
        run_main(["t1", "--set", 'critics_run=["milestone-adversary-critic"]'])
        run_main(["t1", "--set", 'critique_files=["critique/adversary.md"]'])
        run_main(["t1", "--set",
                  'critique_finding_counts={"critical":0,"high":1,"medium":0,"low":0}'])
        rc, out = run_main(["t1", "critique-complete"])
        expect("critique-complete refused w/o findings_register (F5)",
               rc != 0 and "findings_register" in out, out.strip()[:80])
        # schema evolution: a pre-round-4 state.json lacks the key entirely --
        # --set must be able to CREATE known-schema fields (the documented wedge
        # escape), while unknown fields still refuse.
        sp0 = sdir / "state.json"
        st0 = json.loads(sp0.read_text())
        st0.pop("findings_register", None)
        sp0.write_text(json.dumps(st0))
        rc, out = run_main(
            ["t1", "--set", 'findings_register=".claude/notes/milestones/t1/findings.json"']
        )
        expect("--set creates known-but-missing field (schema evolution)",
               rc == 0, out.strip()[:80])
        rc, out = run_main(["t1", "--set", 'not_a_real_field="x"'])
        expect("--set still refuses unknown fields",
               rc != 0 and "unknown field" in out, out.strip()[:80])
        rc, out = run_main(["t1", "critique-complete"])
        expect("critique-complete passes", rc == 0, out.strip()[:80])
        run_main(["t1", "rectify-running"])
        run_main(["t1", "--set", 'rectification_commit="ccc"'])

        # external-write ledger (array model)
        run_main(["t1", "--set", 'external_writes_required=["git push origin main"]'])
        rc, out = run_main(["t1", "complete"])
        expect("complete refused on unbalanced ledger",
               rc != 0 and "not recorded as completed" in out, out.strip()[:80])
        run_main(["t1", "--set", 'external_writes_completed=["git push origin main"]'])
        rc, out = run_main(["t1", "complete"])
        expect("complete refused w/o authorization",
               rc != 0 and "not authorized" in out, out.strip()[:80])
        run_main(["t1", "--set", 'external_writes_authorized=["git push origin main"]'])

        # string-ledger false-pass (round-4 F3): typed --set refuses, and a
        # string smuggled directly into state.json refuses at the transition.
        rc, out = run_main(["t1", "--set", "external_writes_required=git push origin main"])
        expect("ledger --set refuses plain string (F3)",
               rc != 0 and "expected list" in out, out.strip()[:80])
        sp = sdir / "state.json"
        st = json.loads(sp.read_text())
        st["external_writes_required"] = "git push origin main"
        st["external_writes_completed"] = "git push origin main"
        sp.write_text(json.dumps(st))
        rc, out = run_main(["t1", "complete"])
        expect("complete refuses string ledger in state (F3)",
               rc != 0 and "false-passes" in out, out.strip()[:120])
        st["external_writes_required"] = ["git push origin main"]
        st["external_writes_completed"] = ["git push origin main"]
        st["external_writes_authorized"] = ["git push origin main"]
        sp.write_text(json.dumps(st))

        # milestone-id containment (round-4 F10)
        rc, out = run_main(["../evil", "--get", "phase"])
        expect("path-traversal id refused (F10)",
               rc != 0 and "invalid milestone id" in out, out.strip()[:80])

        # new-format run: marker set but register missing -> complete refuses
        # (F5). Does not need the sibling script -- refuses before the subprocess.
        rc, out = run_main(["t1", "complete"])
        expect("complete refused: marker set, register missing (F5)",
               rc != 0 and "no register exists" in out, out.strip()[:120])

        freg = sdir / "findings.json"
        base_finding = {
            "id": "C1", "severity": "CRITICAL", "status": "open",
            "file": "x", "line": 1, "title": "t",
            "source_critic": "milestone-adversary-critic", "source_file": "adversary.md",
        }

        def write_register(finding: dict) -> None:
            # The downstream register keys findings by id (a dict, not a list),
            # and every finding must carry a valid severity + status.
            freg.write_text(json.dumps({
                "schema_version": 1, "milestone_id": "t1",
                "findings": {finding["id"]: finding},
            }))

        if not findings_available:
            print("  (findings-gate subprocess assertions SKIPPED: "
                  "milestone-pipeline-findings.py not present yet)")

        if findings_available:
            # REAL subprocess against the sibling (pins gate --register <path>,
            # non-zero exit on open C/H).
            write_register(base_finding)
            rc, out = run_main(["t1", "complete"])
            expect("complete refused by findings gate (open C1)",
                   rc != 0 and "findings gate refused" in out, out.strip()[:120])
            freg.write_text("{not json")
            rc, out = run_main(["t1", "complete"])
            expect("complete refused on corrupt register",
                   rc != 0 and "findings gate refused" in out, out.strip()[:120])

        # missing gate script refuses (fail-loud, never skip a present register).
        # Independent of the real sibling -- only needs a present register file.
        write_register(base_finding)
        FINDINGS_SCRIPT = root / "nonexistent-findings.py"
        rc, out = run_main(["t1", "complete"])
        expect("complete refused when gate script missing",
               rc != 0 and "gate" in out and "missing" in out, out.strip()[:120])
        FINDINGS_SCRIPT = real_script

        if findings_available:
            # deferrable pass-through: open MEDIUM only -> complete passes, note
            # surfaced (the gate returns 0 with a "deferrable" line).
            base_finding.update({"id": "M1", "severity": "MEDIUM"})
            write_register(base_finding)
            rc, out = run_main(["t1", "complete"])
            expect("complete passes with deferrable note on open MEDIUM",
                   rc == 0 and "deferrable" in out, out.strip()[:120])

        # absent register skips the gate entirely (ad-hoc/legacy run)
        sdir2 = root / ".claude" / "notes" / "milestones" / "t2"
        sdir2.mkdir(parents=True)
        write_state(
            sdir2, id="t2", phase="rectify-running",
            phase_history=[{"phase": "rectify-running", "at": "t"}],
            rectification_commit="ccc",
        )
        rc, out = run_main(["t2", "complete"])
        expect("complete passes with no register (ad-hoc/legacy)", rc == 0, out.strip()[:120])

    if prev_repo_root is None:
        os.environ.pop("REPO_ROOT", None)
    else:
        os.environ["REPO_ROOT"] = prev_repo_root
    print(f"self-test: {'PASS' if failures == 0 else f'{failures} FAILURE(S)'}")
    return 0 if failures == 0 else 1


def main(argv: list[str]) -> None:
    if "--self-test" in argv:
        raise SystemExit(self_test())
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    if len(argv) < 3:
        sys.exit(__doc__)
    mid, second = argv[1], argv[2]
    if second == "--get":
        if len(argv) < 4:
            sys.exit("--get requires a field name")
        get_field(mid, argv[3])
    elif second == "--set":
        if len(argv) < 4:
            sys.exit("--set requires field=value")
        set_field(mid, argv[3])
    elif second == "--append":
        if len(argv) < 4:
            sys.exit("--append requires field=value")
        append_field(mid, argv[3])
    else:
        advance(mid, second)


if __name__ == "__main__":
    main(sys.argv)
