"""The remaining chaos-run mediums: marker validation and desktop diagnostics.

Marker (#447 embedder pin, #448 paper_count, #449 absent version) · supervisor
(#459 hardlink, #460 error conflation, #461 exec bit, #462 serde detail,
#464 log truncation, #466 probe overwrite) · frozen child (#458/#468 abort).

Two in the batch are NOT closed here and say so in their own tickets: #463 was
already fixed by the #443 watchdog, and #467 needs process-group ownership that
would not actually reach the real leak.
"""

from __future__ import annotations

from pathlib import Path

# #495: one lexer-aware extractor, shared. The local `_rust_fn` this
# replaces counted braces inside string literals and comments.
from tests._source_blocks import python_block, rust_fn

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
SUP: Path = REPO_ROOT / "apps" / "desktop" / "crates" / "supervisor" / "src"
MAIN_RS: str = (SUP / "main.rs").read_text(encoding="utf-8")
LIFECYCLE_RS: str = (SUP / "lifecycle.rs").read_text(encoding="utf-8")


RESOURCES_PY: str = (REPO_ROOT / "server" / "resources.py").read_text(encoding="utf-8")
CORPUS_PY: str = (REPO_ROOT / "server" / "corpus.py").read_text(encoding="utf-8")
HEALTH_PY: str = (REPO_ROOT / "server" / "health.py").read_text(encoding="utf-8")
CHILD_PY: str = (REPO_ROOT / "server" / "desktop_child.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# #447 / #448 / #449 — MOVED to tests/test_marker_reconciliation.py
# --------------------------------------------------------------------------
#
# Eight source-scanning tests lived here and were deleted rather than
# repaired, because every one of them passed against code an external review
# then showed to be wrong at runtime (#495). Recording what they asserted, so
# the failure mode is not re-derived from scratch later:
#
#   * "the embedder pin is checked" asserted that
#     `embedder_version != EMBEDDER_VERSION` appeared ANYWHERE in
#     resources.py. It did — inside `startup` only. `_bind_corpus`, which
#     `late_bind` and `refresh_corpus_if_stale` share, had no check at all,
#     so bootstrap promotion published a clean verdict for a corpus built by
#     a different embedder. A substring cannot distinguish one call site from
#     three.
#
#   * "the embedder mismatch outranks a wrong counter" compared the two
#     reasons' STRING OFFSETS in the file and asserted `"if degraded is
#     None:" in RESOURCES_PY`. Both held while the embedder branch assigned
#     unconditionally and silently overwrote `corpus_corruption` — a more
#     severe reason that appears EARLIER in the file, which the offset
#     comparison was structurally unable to see.
#
#   * "the tip lookup is failure-path only" asserted `return None` appeared
#     in `_dataset_tip_version`. It did. The function still opened the table
#     without reading a row, so a corpus that was BOTH corrupt and
#     marker-ahead was told "The data is NOT corrupt".
#
# The replacements build a real LanceDB table, run the code, and read the
# verdict — and each is mutation-checked against the specific defect it
# exists to catch. Structural assertions are kept only where the property
# genuinely IS structural (a constant's value, a call site's placement inside
# a `try`, a ban on a construct).


# --------------------------------------------------------------------------
# #459 / #460 / #461 — containment tells the truth
# --------------------------------------------------------------------------
def test_canonicalize_failures_are_distinguished() -> None:
    """EACCES, ENOENT and the rest are different repairs; one string sent an
    operator with a mode-000 directory looking for a missing file."""
    assert "fn canonicalize_reason(" in MAIN_RS
    fn = rust_fn(MAIN_RS, "fn canonicalize_reason(")
    assert "ErrorKind::NotFound" in fn
    assert "ErrorKind::PermissionDenied" in fn


def test_the_child_must_be_executable() -> None:
    """Containment proves the file is INSIDE the root, never that it runs.

    A ditto/zip round trip or a restrictive umask strips the exec bit, and
    `--print-child-plan` then attested an unrunnable payload as healthy.
    """
    assert "is not executable" in MAIN_RS
    assert "0o111" in MAIN_RS


def test_a_hardlinked_child_is_refused() -> None:
    """canonicalize resolves SYMLINKS; a hardlink has no link to resolve, so
    content from outside the root passes containment while presenting an
    in-root path. Measured on APFS, not the Linux-only class the residual-risk
    note describes."""
    assert "is hardlinked" in MAIN_RS
    assert "nlink()" in MAIN_RS


def test_the_containment_checks_run_after_the_prefix_test() -> None:
    fn = rust_fn(MAIN_RS, "fn resolve_inside(")
    assert fn.index("starts_with") < fn.index("check_child_file("), (
        "escape is the cheaper and more serious refusal; keep it first"
    )


# --------------------------------------------------------------------------
# #462 — serde already knew what was wrong
# --------------------------------------------------------------------------
def test_a_malformed_plan_keeps_its_diagnosis() -> None:
    """Field name, line, column and expected type were all discarded, so a
    typo, a schema mismatch and a zero-byte file looked identical."""
    assert 'format!("launch plan malformed: {err}")' in MAIN_RS


# --------------------------------------------------------------------------
# #464 — the log must survive the next launch
# --------------------------------------------------------------------------
def test_the_child_log_appends() -> None:
    """It is the ONLY place a cold-start failure's reason exists (#444), so
    truncating destroyed the evidence on the second double-click. The event
    log beside it was already append-only."""
    fn = rust_fn(LIFECYCLE_RS, "pub fn open_private_log(")
    assert ".append(true)" in fn
    assert ".truncate(true)" not in fn


# --------------------------------------------------------------------------
# #466 — the probe cannot clobber
# --------------------------------------------------------------------------
def test_the_plan_probe_cannot_overwrite_an_existing_file() -> None:
    """It ships enabled in the signed bundle and took its destination from
    argv unconstrained."""
    fn = rust_fn(MAIN_RS, "fn emit_child_plan_probe(")
    assert "create_new(true)" in fn
    assert "fs::write(" not in fn, "fs::write truncates; create_new does not"


# --------------------------------------------------------------------------
# #458 / #468 — the frozen child exits cleanly
# --------------------------------------------------------------------------
def test_the_child_exits_without_interpreter_finalization() -> None:
    """A daemon thread parked in a blocking stdin read makes CPython abort at
    finalization: the exit code becomes -1, indistinguishable from "the
    supervisor had to SIGKILL it", and the abort block bypasses logging."""
    assert "def _exit_without_finalizing(" in CHILD_PY
    assert "_exit_without_finalizing(main())" in CHILD_PY
    fn = python_block(CHILD_PY, "def _exit_without_finalizing(")
    assert "os._exit(code)" in fn


def test_the_child_flushes_before_exiting() -> None:
    """os._exit skips flushing too — losing the last log lines of a failed
    startup would trade one diagnostic problem for another."""
    fn = python_block(CHILD_PY, "def _exit_without_finalizing(")
    assert "logging.shutdown()" in fn
    assert fn.index("logging.shutdown()") < fn.index("os._exit(code)")
