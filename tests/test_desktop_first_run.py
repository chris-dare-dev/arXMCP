"""The shipped application must start, say when it cannot, and trust nothing.

Two criticals from the 2026-08-22 chaos run, fixed together because neither
half stands alone.

**#426 — there was no first-run state that could succeed.** The self-authored
plan points ``data_root`` at ``~/Library/Application Support/arXMCP``, which on
a machine that has never run an ingest is empty. ``Resources.startup`` then
raised :class:`CorpusNotIngestedError` and the child exited before emitting
``bound``. The remedy that error names — ``make up-wizard`` — does not exist
inside a ``.app``, so the failure was not merely likely but total.

**#425 — the failure was invisible.** Every refusal path is ``eprintln!`` plus
an exit, and under LaunchServices a double-clicked application's stderr goes
nowhere an operator will look. Measured: no dialog, no message, ``open`` exits
0, process gone in five to seven seconds, and the only trace an NDJSON file the
next launch truncates (#464).

**#427 — the environment launch-plan arm applied no containment.** With
``ARXMCP_DESKTOP_LAUNCH_PLAN`` set, ``load_plan`` deserialized the JSON and
exec'd whatever ``child_argv[0]`` named — proven against the SIGNED release
bundle with ``/usr/bin/touch``. The containment the README documents
(``child_payload_root``, ``resolve_inside``, the symlink refusal, the identity
digest) is reachable only from ``self_authored_plan``, so the external plan was
trusted MORE than the self-authored one, and ``main.rs``'s own comment claimed
the reverse.

Fixing any one alone leaves the product broken: a bootstrap that works but
cannot report its next failure, a clear report of a failure that always
happens, or either of those in a binary that will exec whatever an environment
variable points at.

Everything here is static analysis: the runtime behaviour these fixes rely on
is already covered by ``tests/test_bootstrap_mode.py``, and this module asserts
that the desktop entrypoint and the supervisor actually reach for it. No model
is loaded and no process is spawned.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
DESKTOP_CHILD: Path = REPO_ROOT / "server" / "desktop_child.py"
SUPERVISOR_SRC: Path = REPO_ROOT / "apps" / "desktop" / "crates" / "supervisor" / "src"
LIFECYCLE_RS: str = (SUPERVISOR_SRC / "lifecycle.rs").read_text(encoding="utf-8")


def _strip_rust_comments(text: str) -> str:
    """Drop ``//``/``///`` and ``/* */`` comments.

    The source DOCUMENTS the wrong path it used to look at
    (``/usr/sbin/codesign``), so a raw negative scan flags the explanation as
    the offence — the same trap as ui.js documenting ``new Function()``.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


LIFECYCLE_CODE: str = _strip_rust_comments(LIFECYCLE_RS)
MAIN_RS: str = (SUPERVISOR_SRC / "main.rs").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# #426 — a cold machine can start
# ---------------------------------------------------------------------------
def _config_call_keywords() -> dict[str, ast.expr]:
    """Find the ``Config(...)`` call in ``desktop_child.main`` via AST.

    Derived rather than grepped: a substring check for ``bootstrap_mode=True``
    would also match a comment or a docstring, and the failure this guards
    against is precisely a claim that is present in prose and absent in code.
    """
    tree = ast.parse(DESKTOP_CHILD.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Config"
        ):
            return {kw.arg: kw.value for kw in node.keywords if kw.arg}
    raise AssertionError("no Config(...) call found in server/desktop_child.py")


def test_the_desktop_child_asks_for_bootstrap_mode() -> None:
    """#426. Without this the shipped .app cannot start on a fresh machine."""
    keywords = _config_call_keywords()
    assert "bootstrap_mode" in keywords, (
        "server/desktop_child.py must build its Config with "
        "bootstrap_mode=True; without it a fresh install raises "
        "CorpusNotIngestedError and never emits `bound` (#426)"
    )
    value = keywords["bootstrap_mode"]
    assert isinstance(value, ast.Constant) and value.value is True, (
        "bootstrap_mode must be the literal True, not a computed value — a "
        "cold start is the ONLY case it changes, and guessing at it is how "
        "#426 shipped"
    )


def test_the_child_still_owns_its_data_root() -> None:
    """The launch frame stays the source of the data root."""
    keywords = _config_call_keywords()
    assert "data_dir" in keywords, "Config must still be given the frame's data_root"


def test_the_semantics_bootstrap_mode_relies_on_are_covered_elsewhere() -> None:
    """Pointer, not duplication.

    The two behaviours #426 leans on — bootstrap_mode skipping the cold-start
    refusal, and FM-7's "present marker means the hint is ignored" — are
    already asserted in ``tests/test_bootstrap_mode.py``. Re-testing them here
    would add a second place to update and no new coverage. What is NEW is that
    the DESKTOP entrypoint asks for the mode at all, which the AST guards above
    pin. This test fails if that upstream coverage is deleted or renamed, so
    the reference cannot rot silently.
    """
    upstream = (REPO_ROOT / "tests" / "test_bootstrap_mode.py").read_text(
        encoding="utf-8"
    )
    for required in (
        "test_resources_startup_raises_on_cold_start_default",
        "test_resources_startup_skips_raise_in_bootstrap_mode",
        "test_resources_startup_bootstrap_hint_ignored_when_corpus_exists",
    ):
        assert required in upstream, (
            f"tests/test_bootstrap_mode.py no longer defines {required!r}; "
            "#426's correctness argument rests on it — re-home the assertion "
            "before deleting it"
        )


# ---------------------------------------------------------------------------
# #425 — a failure reaches the operator
# ---------------------------------------------------------------------------
def test_the_failure_path_shows_a_window() -> None:
    """`lifecycle-failed` must be accompanied by something on screen."""
    assert "pub fn show_failure(" in LIFECYCLE_RS, (
        "lifecycle.rs must define show_failure (#425)"
    )
    failure_arm = LIFECYCLE_RS[LIFECYCLE_RS.index('recorder.record("lifecycle-failed"') :][
        :1200
    ]
    assert "show_failure(" in failure_arm, (
        "show_failure must be called on the lifecycle-failed arm, not merely "
        "defined — an unreferenced failure surface is #425 unfixed"
    )
    assert 'record("failure-shown"' in failure_arm, (
        "record failure-shown so a triage session can tell 'the operator was "
        "told' from 'the operator was not told'"
    )


def test_the_failure_page_is_not_shown_in_smoke_mode() -> None:
    """Smoke runs are headless gates that exit immediately after failing."""
    failure_arm = LIFECYCLE_RS[LIFECYCLE_RS.index('recorder.record("lifecycle-failed"') :][
        :1200
    ]
    assert "if !smoke" in failure_arm, (
        "the failure page belongs to the interactive path only"
    )


def test_a_non_smoke_failure_no_longer_takes_the_window_away() -> None:
    """The other half of #425, and the easiest to regress.

    Showing the reason and then exiting removes it from the screen again, which
    is indistinguishable from never having shown it. A smoke run MUST still
    self-exit — the m6 fault matrix asserts an exit code of 1 — so the guard is
    that the exit is reached under ``smoke`` and not under a bare ``code != 0``.
    """
    match = re.search(r"if smoke \{\s*handle\.exit\(code\);\s*\}", MAIN_RS)
    assert match is not None, (
        "main.rs must exit on smoke runs only; a non-smoke failure has to "
        "leave the failure page on screen (#425)"
    )
    assert "if smoke || code != 0" not in MAIN_RS, (
        "the old condition exits on a non-smoke failure, which takes the "
        "failure page off screen — that is #425"
    )


def test_the_failure_page_names_the_log_and_its_retention() -> None:
    """#464: tell the operator what will happen to the file they are being
    sent to.

    **This assertion had to be inverted, and that is the finding.** It
    originally required the page to say the log is *"rewritten on every
    launch"* — true when #444 wrote the sentence, and made FALSE by #464 in
    the same batch, which changed the open to append. Both shipped green,
    because a source-scan test cannot notice that the string it is pinning
    has stopped describing the code. It was actively holding the wrong text
    in place: correcting the page would have failed this test.

    Retention is now bounded and stated: append, one rotated generation, so
    the previous launch survives a second double-click and growth stops at
    2 x LOG_ROTATE_BYTES.
    """
    body = _rust_fn(LIFECYCLE_RS, "pub fn show_failure(")
    assert "desktop-child.log" in LIFECYCLE_RS, "the page must name the log path"
    assert "rewritten on every launch" not in body, (
        "the log has been APPEND since #464; this sentence is false and "
        "tells an operator to copy a file that is not going anywhere"
    )
    assert "last two launches" in body, (
        "the page must say what retention the operator actually gets"
    )


def test_the_log_retention_the_page_promises_is_the_one_implemented() -> None:
    """The pairing the previous test could not make on its own.

    A page can say anything. What makes "the last two launches" true is the
    rotation in `open_private_log`: append, plus one generation kept as
    `.log.1` when the live file passes `LOG_ROTATE_BYTES`.
    """
    assert "LOG_ROTATE_BYTES" in LIFECYCLE_RS
    body = _rust_fn(LIFECYCLE_RS, "pub fn open_private_log(")
    assert ".append(true)" in body, "append is what preserves the last launch"
    assert 'with_extension("log.1")' in body, (
        "one rotated generation is what bounds growth while keeping the "
        "previous launch — appending forever is what #464 shipped"
    )


def test_the_failure_tail_is_scoped_to_this_launch() -> None:
    """#444 round 2. Behavioral coverage is in `lifecycle.rs`'s own tests
    (`a_pre_spawn_failure_quotes_nothing_from_the_previous_launch` and three
    siblings, each verified to fail without the boundary); this pins the
    placement those tests cannot see from outside.
    """
    assert "LAUNCH_BANNER" in LIFECYCLE_RS
    opener = _rust_fn(LIFECYCLE_RS, "pub fn open_private_log(")
    assert "LAUNCH_BANNER" in opener, (
        "the boundary must be written when the log is OPENED — before the "
        "child can produce anything — or a pre-spawn failure still has no "
        "marker to tail from (#444)"
    )


# ---------------------------------------------------------------------------
# #427 — the environment arm does not exist in a shipped binary
# ---------------------------------------------------------------------------
def test_the_env_plan_arm_is_debug_only() -> None:
    """#427. Not a runtime check — the path is not compiled into a release.

    A runtime guard (`if cfg!(debug_assertions) { ... }`) would leave the
    deserialize-and-exec code in the artifact for someone to find a way back
    into. Two ``#[cfg]``-gated definitions mean the release binary genuinely
    has no environment arm.
    """
    assert "#[cfg(debug_assertions)]\nfn env_plan_path()" in MAIN_RS, (
        "the debug definition of env_plan_path must be #[cfg]-gated"
    )
    assert "#[cfg(not(debug_assertions))]\nfn env_plan_path()" in MAIN_RS, (
        "release builds need an env_plan_path that returns None, so the "
        "deserialize-and-exec path is absent rather than merely unreached"
    )
    assert "let Some(path) = env_plan_path() else {" in MAIN_RS, (
        "load_plan must read the plan through env_plan_path(), not by calling "
        "std::env::var_os(PLAN_ENV) directly (#427)"
    )


def test_load_plan_does_not_read_the_env_var_directly() -> None:
    """The gate is worthless if the old call survives beside it."""
    load_plan = MAIN_RS[MAIN_RS.index("fn load_plan()") :]
    load_plan = load_plan[: load_plan.index("\n}\n")]
    assert "var_os(PLAN_ENV)" not in load_plan, (
        "load_plan reads PLAN_ENV directly again, which reinstates the "
        "environment arm in release builds (#427)"
    )


def test_an_ignored_env_plan_is_recorded_not_silently_dropped() -> None:
    """A release build that disregards the variable must say so.

    Ignoring rather than refusing is deliberate — a stray exported variable
    must not stop an operator's application from starting — but an ignored
    injection attempt that leaves no trace is indistinguishable from one that
    never happened.
    """
    assert "fn env_plan_was_ignored()" in MAIN_RS
    assert "self-authored (env plan ignored: release build)" in MAIN_RS, (
        "the plan_source recorded on supervisor-started must name the ignored "
        "environment plan, so the event log shows the attempt"
    )


def test_the_inverted_containment_comment_is_gone() -> None:
    """#427's sharpest point was a comment asserting the opposite of the code.

    ``main.rs`` used to read *"The self-authored plan is NOT trusted more than
    an external one: it goes through the same validator, under the same rules"*.
    True about the validator, and backwards about everything else — the
    external arm skipped the containment the self-authored arm submits to.
    """
    assert (
        "The self-authored plan is NOT trusted more than an external one"
        not in MAIN_RS
    ), (
        "the inverted comment is back; the two arms do NOT share the "
        "containment story, only validate_plan (#427)"
    )
    load_plan = MAIN_RS[MAIN_RS.index("fn load_plan()") :]
    load_plan = load_plan[: load_plan.index("\n}\n")]
    assert "resolve_inside" in load_plan, (
        "load_plan's comment must name what the two arms do NOT share, so the "
        "next reader is not misled the way #427 was"
    )


# ---------------------------------------------------------------------------
# #436 / #435 — the seal is consulted, and the digest stops overclaiming
# ---------------------------------------------------------------------------
README: str = (
    REPO_ROOT / "apps" / "desktop" / "README.md"
).read_text(encoding="utf-8")


def test_the_signature_is_verified_before_exec() -> None:
    """#436. `codesign` catches a flipped byte; nothing used to run it."""
    assert "pub fn verify_signature(" in LIFECYCLE_RS
    cycle = LIFECYCLE_RS[LIFECYCLE_RS.index("fn cycle(") :]
    cycle = cycle[: cycle.index("\n}\n")]
    spawn_at = cycle.index("command.spawn()")
    verify_at = cycle.index("verify_signature(")
    assert verify_at < spawn_at, (
        "the signature must be verified BEFORE spawn — checking a binary "
        "after starting it is not a check (#436)"
    )
    assert 'record("child-signature-invalid"' in cycle, (
        "a refused launch must record why, or the operator sees only the "
        "generic failure page"
    )


def test_codesign_is_invoked_by_absolute_path() -> None:
    """A PATH lookup would let a planted `codesign` answer for itself."""
    assert '"/usr/bin/codesign"' in LIFECYCLE_RS, (
        "codesign must be absolute, and it is /usr/bin/codesign — NOT "
        "/usr/sbin/codesign, which does not exist on macOS 26.6"
    )
    assert "/usr/sbin/codesign" not in LIFECYCLE_CODE, (
        "the wrong path is back in the CODE (it is fine in a comment that "
        "explains the mistake)"
    )


def test_the_digest_no_longer_claims_to_detect_tampering() -> None:
    """#435. The defect was the claim, not only the code.

    `identity_file == child_argv[0]`, so the digest and the child's
    self-report read the same bytes and move together under tampering. The
    check has a real, smaller purpose; the code and the README must say which
    one, because a guarantee people believe in is worse than none.
    """
    assert "SELF-CONSISTENCY check" in LIFECYCLE_RS, (
        "lifecycle.rs must state what the identity digest actually is (#435)"
    )
    assert "self-consistency check, not a tamper\n   check" in README, (
        "apps/desktop/README.md must not imply the digest detects tampering"
    )


def test_the_resign_limitation_is_documented_not_buried() -> None:
    """The check is honest about what it cannot do.

    An ad-hoc signature has no identity to pin, so `codesign --force --sign -`
    restores validity to a tampered or swapped binary. Measured, and asserted
    in the Rust suite by
    `an_adhoc_resign_defeats_verification_and_that_is_the_known_limit`.
    """
    assert "ad-hoc" in README and "re-sign" in README.replace("re-signs", "re-sign"), (
        "the README must record the ad-hoc re-sign limit alongside the claim"
    )
    assert "an_adhoc_resign_defeats_verification" in LIFECYCLE_RS, (
        "the limitation must be pinned by a test that starts failing when the "
        "guarantee improves, not left as prose"
    )


# ---------------------------------------------------------------------------
# #442 / #443 — the supervisor keeps watching, and stops waiting on the dead
# ---------------------------------------------------------------------------
def test_the_bound_wait_reports_progress() -> None:
    """#442. The 240s timeout is not the bug; 241s of silence is.

    A cold BGE-M3 load is genuinely slow, so shortening the timeout would turn
    slow first runs into failures. What has to change is that a warm-up and a
    wedged child were indistinguishable — to the operator AND to a triage
    session reading the event log afterwards.
    """
    assert "BOUND_PROGRESS_INTERVAL" in LIFECYCLE_RS
    assert 'record(\n                    "waiting-for-bound"' in LIFECYCLE_RS or (
        '"waiting-for-bound"' in LIFECYCLE_RS
    ), "the bound wait must emit progress events"
    assert "BOUND_TIMEOUT: Duration = Duration::from_secs(240)" in LIFECYCLE_RS, (
        "the timeout itself should NOT have been shortened — that would fail "
        "slow-but-healthy first runs (#442)"
    )


def test_a_long_start_explains_itself_on_screen() -> None:
    assert "pub fn show_slow_start(" in LIFECYCLE_RS
    assert "FIRST_RUN_NOTICE" in LIFECYCLE_RS
    body = _rust_fn(LIFECYCLE_RS, "pub fn show_slow_start(")
    assert "retrieval model" in body, (
        "the notice must say WHY it is slow, not just that it is"
    )


def test_the_cooperative_grace_is_skipped_only_for_a_stopped_child() -> None:
    """#442's other half — and the discriminator matters.

    A first draft keyed this on "never bound" and the m6 fault matrix rejected
    it, correctly: its startup-timeout arm is a *parked but cooperating* child
    that never emits ``bound`` and still honours the shutdown frame with a
    clean exit 0, and its malformed-bound arm is alive enough to have spoken
    badly. Both deserve the grace. Only a SIGSTOP'd process provably cannot
    use it.
    """
    assert "fn is_stopped(" in LIFECYCLE_RS, (
        "the shortcut must key on the process being STOPPED, not on whether "
        "it bound (#442)"
    )
    shutdown = _rust_fn(LIFECYCLE_RS, "pub fn shutdown_child(")
    assert "is_stopped(control.child.id())" in shutdown
    assert "control.bound" not in LIFECYCLE_RS, (
        "the never-bound discriminator was wrong and must not come back"
    )
    for required in (
        "a_stopped_child_skips_straight_to_kill",
        "a_running_child_still_gets_its_full_grace",
        "is_stopped_is_false_for_an_unknown_pid",
    ):
        assert required in LIFECYCLE_RS, f"{required} must pin this behaviour"


def test_is_stopped_fails_safe() -> None:
    """An unreadable process state must keep the FULL ladder.

    Guessing "stopped" on a bad reading would force-kill a healthy server
    mid-flush of its LanceDB and Kuzu handles — strictly worse than the bug
    being fixed.
    """
    probe = _rust_fn(LIFECYCLE_RS, "fn is_stopped(pid: u32)")
    assert "return false;" in probe, "a failed probe must return false"
    assert '"/bin/ps"' in probe, (
        "absolute path — a planted ps earlier on PATH must not answer this"
    )


def test_a_watchdog_watches_the_child() -> None:
    """#443. Nothing observed the child after the cycle returned."""
    assert "fn spawn_child_watchdog(" in LIFECYCLE_RS
    run_cycle = LIFECYCLE_RS[LIFECYCLE_RS.index("pub fn run_cycle(") :]
    run_cycle = run_cycle[: run_cycle.index("\n}\n")]
    assert "spawn_child_watchdog(" in run_cycle, (
        "the watchdog must be started on the non-smoke path, where the cycle "
        "hands the child off and returns (#443)"
    )
    watchdog = _rust_fn(LIFECYCLE_RS, "fn spawn_child_watchdog(")
    assert 'record("child-exited"' in watchdog, (
        "a dead server must leave a line in the event log"
    )
    assert "show_failure(" in watchdog, (
        "and must reach the operator, not only the log"
    )
    assert "try_wait()" in watchdog, (
        "try_wait both detects the exit and reaps it — the measured bug left "
        "a zombie behind"
    )


def test_the_watchdog_does_not_silently_restart() -> None:
    """A hidden crash loop is harder to diagnose than a stop that explains."""
    # Whole-file: the rationale lives in the doc comment ABOVE the fn, which
    # a slice starting at the signature necessarily misses.
    assert "Deliberately does NOT restart" in LIFECYCLE_RS, (
        "record the decision; a future reader will otherwise assume restart "
        "was forgotten rather than chosen"
    )


# ---------------------------------------------------------------------------
# #438 / #439 / #488 — the token cannot reach disk, and the logs are private
# ---------------------------------------------------------------------------
REDACT_RS: str = (SUPERVISOR_SRC / "redact.rs").read_text(encoding="utf-8")
EVENTS_RS: str = (SUPERVISOR_SRC / "events.rs").read_text(encoding="utf-8")


def _rust_fn(source: str, signature: str) -> str:
    """The whole body of a top-level Rust fn, brace-balanced.

    Replaces the `source[source.index(sig):][:900]` shape that this file used
    throughout. A fixed window is wrong in both directions and fails silently
    each way: it OVERRUNS into the next function when a block shrinks (so an
    assertion passes against a neighbour's code) and TRUNCATES when a block
    grows (so an assertion fails against code that is still correct). The
    latter happened four separate times in this session's work -- most
    recently when #464's rotation block pushed `.append(true)` past character
    900 of `open_private_log`.

    rustfmt puts a top-level fn's closing brace at column 0, but braces are
    counted rather than trusted so a nested item cannot end the slice early.
    """
    start = source.index(signature)
    depth = 0
    seen_open = False
    for pos in range(start, len(source)):
        char = source[pos]
        if char == "{":
            depth += 1
            seen_open = True
        elif char == "}":
            depth -= 1
            if seen_open and depth == 0:
                return source[start : pos + 1]
    raise AssertionError(f"unbalanced braces after {signature!r}")


def test_child_stderr_is_relayed_not_handed_over() -> None:
    """#438. A file descriptor handed to the child cannot be scrubbed.

    The bytes never entered this process, so no scrubber could exist in the
    path — which is why the defence had to change shape, not just get better.
    """
    assert "Stdio::from(log_file)" not in _strip_rust_comments(LIFECYCLE_RS), (
        "child stderr must NOT be wired straight to the log file (#438)"
    )
    assert "fn spawn_stderr_relay(" in LIFECYCLE_RS
    relay = _rust_fn(LIFECYCLE_RS, "fn spawn_stderr_relay(")
    assert "scrub_child_text" in relay, "the relay must scrub before writing"
    assert "read_until" in relay, (
        "read_line would abort the relay on non-UTF-8 child stderr; the bytes "
        "must be split first and decoded lossily after"
    )


def test_child_controlled_text_uses_the_strong_scrubber() -> None:
    """#439. Exact matching cannot see a copy the child chose the casing of."""
    assert "pub fn scrub_child_text(" in REDACT_RS
    assert "HEX_RUN_MIN" in REDACT_RS
    invalid = LIFECYCLE_RS[LIFECYCLE_RS.index('record("bound-frame-invalid"') - 900 :][:1400]
    assert "scrub_child_text" in invalid, (
        "the bound-frame-invalid diagnostic persists child-chosen bytes and "
        "must use the hex-aware scrubber, not bare scrub (#439)"
    )


def test_the_shared_scrub_primitive_is_left_alone() -> None:
    """The exact-match vectors stay pinned, on purpose.

    `scrub` is shared with a Python reference semantic and locked by
    `fixtures.sha256`. Its exact-match behaviour is still correct for scrubbing
    OUR OWN strings, where over-eager stripping would corrupt legitimate
    digests. The fix was to stop using it ALONE on text the child chose — the
    distinction is who picked the bytes.
    """
    assert 'input.replace(secret, "[REDACTED]")' in REDACT_RS, (
        "scrub's exact-match semantics are pinned across two languages; "
        "changing them requires re-approving the vectors and fixtures.sha256"
    )


def test_both_logs_are_created_private() -> None:
    """#488. 0600, and enforced on files an earlier version already made."""
    assert "fn open_private_log(" in LIFECYCLE_RS
    for source, name in ((LIFECYCLE_RS, "lifecycle.rs"), (EVENTS_RS, "events.rs")):
        assert "0o600" in source, f"{name} must create its log 0600"
        assert "set_permissions" in source, (
            f"{name} must also chmod an EXISTING log — mode() applies only at "
            "creation, so a 0644 file from an earlier version would keep it"
        )


# ---------------------------------------------------------------------------
# #444 / #465 — refusals reach the operator, before AND after the window exists
# ---------------------------------------------------------------------------
def test_pre_window_refusals_show_a_native_alert() -> None:
    """#465. `fail()` runs BEFORE the Tauri app exists.

    #425's failure page is unreachable this early — there is no window to
    render into — so a native alert is the only surface available. Every
    refusal in the self-authoring arm reaches `fail()`: missing payload,
    symlinked payload root, escaping child executable, uncreatable or
    unresolvable data root, no HOME.
    """
    assert "fn show_native_alert(" in MAIN_RS
    fail_fn = _rust_fn(MAIN_RS, "fn fail(reason: &str) -> ! {")
    assert "show_native_alert(reason)" in fail_fn, (
        "fail() must show the alert, not merely have one available (#465)"
    )
    assert "eprintln!" in fail_fn, (
        "stderr must stay — it is what a terminal-launched developer sees"
    )


def test_the_alert_cannot_block_the_exit() -> None:
    """`display alert` blocks until dismissed; fail() must still exit."""
    alert = _rust_fn(MAIN_RS, "fn show_native_alert(reason: &str)")
    assert ".spawn()" in alert and ".status()" not in alert and ".output()" not in alert, (
        "the alert must be spawned and never waited on, or a refusal hangs "
        "instead of exiting"
    )
    assert "giving up after" in alert, (
        "an undismissed alert must not linger forever"
    )
    assert '"/usr/bin/osascript"' in alert, "absolute path"


def test_the_alert_is_release_only() -> None:
    """The gates drive the debug binary through these refusals deliberately."""
    assert '#[cfg(all(target_os = "macos", not(debug_assertions)))]' in MAIN_RS, (
        "a dialog per refusal would be noise in the conformance gate, which "
        "exercises the refusal paths on purpose"
    )


def test_the_failure_page_carries_the_childs_own_error() -> None:
    """#444. The supervisor's reason names the symptom, not the cause.

    "child stdout closed before bound" is structural and says nothing about
    why. The child's message is specific and actionable — the measured case
    was a cold-start corpus refusal that named its own remedy — and it was
    sitting in a log the operator would never open.
    """
    assert "fn child_log_tail(" in LIFECYCLE_RS
    show = _rust_fn(LIFECYCLE_RS, "pub fn show_failure(")
    assert "child_log_tail(" in show, (
        "show_failure must pull the child's last lines into the page (#444)"
    )
    assert "The server reported:" in show


def test_the_tail_read_is_bounded_and_scrubbed() -> None:
    tail = _rust_fn(LIFECYCLE_RS, "fn child_log_tail(")
    assert "WINDOW" in tail and "seek" in tail.lower(), (
        "a child that spewed megabytes must not be read into memory to show "
        "its last line"
    )
    assert "scrub_child_text" in tail, (
        "defence in depth — this display path must not depend on the #438 "
        "relay having scrubbed correctly"
    )
    for required in (
        "child_log_tail_is_bounded_and_drops_a_cut_first_line",
        "child_log_tail_redacts_hex_even_though_the_relay_already_did",
        "child_log_tail_is_none_when_there_is_nothing_to_show",
    ):
        assert required in LIFECYCLE_RS, f"{required} must pin this"


# ---------------------------------------------------------------------------
# #437 / #441 — the machine-global single-instance socket
# ---------------------------------------------------------------------------
def test_single_instance_registration_is_conditional() -> None:
    """#441. A supervisor on its own data root must not be exited by another.

    The fs2 lock on ``<data_root>/supervisor.lock`` is already the primary
    single-instance defence and is correctly per-data-root. The plugin's
    socket is machine-global, so registering it unconditionally let an
    unrelated instance exit this one — 0, no event, no stderr. A developer's
    debug run could kill the operator's shipped app, and vice versa.
    """
    assert "fn single_instance_decision(" in MAIN_RS
    assert "enum SingleInstance" in MAIN_RS
    code = _strip_rust_comments(MAIN_RS)
    assert "if single_instance == SingleInstance::Register {" in code, (
        "the plugin must be registered conditionally (#441)"
    )
    assert 'record(\n            "single-instance-skipped"' in MAIN_RS or (
        '"single-instance-skipped"' in MAIN_RS
    ), "a skip must be recorded, or it is another silent behaviour change"


def test_the_loser_path_is_gated_the_same_way() -> None:
    """The mirror image: notifying a socket owned by an unrelated root.

    If we would not REGISTER for this data root, we must not NOTIFY on it
    either — the process on the other end is somebody else's instance.
    """
    code = _strip_rust_comments(MAIN_RS)
    loser = code[code.index("let Some(supervisor_lock) = supervisor_lock else {") :][:1600]
    assert "may_notify" in loser and "single_instance_decision(" in loser, (
        "the lock-loser path must consult the same decision, or the two "
        "halves disagree about who owns the socket (#437/#441)"
    )


def test_a_squatted_socket_does_not_stop_the_app() -> None:
    """#437. /tmp is world-writable, so anything can pre-create that path."""
    for required in (
        "a_squatted_socket_degrades_activation_instead_of_exiting",
        "a_non_default_data_root_never_touches_the_shared_socket",
        "the_default_data_root_still_registers",
        "an_underivable_default_is_not_assumed_to_be_the_shipped_shape",
    ):
        assert required in MAIN_RS, f"{required} must pin this behaviour"
    assert "fn single_instance_socket_owner(" in MAIN_RS, (
        "the socket's owner must be checked before registering (#437)"
    )


# ---------------------------------------------------------------------------
# #445 / #434 — the OS asks us to stop; the OS warns the user about us
# ---------------------------------------------------------------------------
def test_a_termination_signal_runs_the_bounded_shutdown() -> None:
    """#445. The grace/force/reap contract was reachable only via Tauri.

    Tauri installs no signal handler, so `killall`, Activity Monitor's Quit,
    launchd logout/restart/shutdown and any process manager bypassed the
    shutdown frame, the 35s cooperative grace, the escalation and the reap —
    and left no record for a post-mortem to read.
    """
    assert "fn install_termination_handler(" in MAIN_RS
    assert "libc::SIGTERM" in MAIN_RS and "libc::SIGINT" in MAIN_RS
    assert '"shutdown-on-signal"' in MAIN_RS, (
        "the signal path must leave evidence, or a post-mortem cannot tell it "
        "from a clean quit (#445)"
    )
    assert "shutdown_child(control)" in MAIN_RS


def test_the_signal_handler_itself_stays_async_signal_safe() -> None:
    """Doing the shutdown IN the handler would malloc, lock and waitpid from a
    signal context — the class of bug that turns a clean stop into a hang."""
    handler = MAIN_RS[MAIN_RS.index("extern \"C\" fn on_termination_signal") :][:600]
    assert "store(true" in handler, "the handler must only set a flag"
    for forbidden in ("shutdown_child", "record(", "lock()"):
        assert forbidden not in handler, (
            f"{forbidden!r} is not async-signal-safe and must live in the "
            "watcher thread, not the handler"
        )


def test_both_shutdown_paths_share_the_slot_discipline() -> None:
    """Take-from-the-slot, so RunEvent::Exit and the signal path can never
    both run the ladder against one child."""
    code = _strip_rust_comments(MAIN_RS)
    assert code.count("guard.take()") + code.count("slot.take()") >= 2, (
        "both exit paths must TAKE the control out of the shared slot"
    )


def test_the_quarantine_experience_is_documented() -> None:
    """#434. "exit 0 and no process" is true about the process table and

    says nothing about what the person sees: a modal malware warning whose
    most prominent button deletes the app. Any network distribution sets the
    quarantine bit, so this is the default first experience for every
    non-developer.
    """
    readme = (
        REPO_ROOT / "apps" / "desktop" / "README.md"
    ).read_text(encoding="utf-8")
    assert "Not Opened" in readme and "Move to Trash" in readme, (
        "the README must record the dialog the operator actually sees (#434)"
    )
    assert "no \"Open Anyway\" button" in readme, (
        "the absence of an escape hatch is the point — without it the user's "
        "only offered action is deletion"
    )
    assert "xattr -d com.apple.quarantine" in readme, (
        "document the deliberate workaround, or every recipient discovers it "
        "while staring at a malware warning"
    )
