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


def test_the_failure_page_names_the_log_and_its_volatility() -> None:
    """#464: the log is truncated on every launch, so telling the operator where it
    is without telling them it is about to be overwritten is a trap."""
    body = LIFECYCLE_RS[LIFECYCLE_RS.index("pub fn show_failure(") :][:2500]
    assert "desktop-child.log" in LIFECYCLE_RS, "the page must name the log path"
    assert "rewritten on every launch" in body, (
        "the page must warn that the log is truncated on the next launch "
        "(#464), or it sends the operator to a file that will be gone"
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
