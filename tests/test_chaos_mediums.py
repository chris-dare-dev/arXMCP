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

REPO_ROOT: Path = Path(__file__).resolve().parents[1]
SUP: Path = REPO_ROOT / "apps" / "desktop" / "crates" / "supervisor" / "src"
MAIN_RS: str = (SUP / "main.rs").read_text(encoding="utf-8")
LIFECYCLE_RS: str = (SUP / "lifecycle.rs").read_text(encoding="utf-8")
RESOURCES_PY: str = (REPO_ROOT / "server" / "resources.py").read_text(encoding="utf-8")
CORPUS_PY: str = (REPO_ROOT / "server" / "corpus.py").read_text(encoding="utf-8")
HEALTH_PY: str = (REPO_ROOT / "server" / "health.py").read_text(encoding="utf-8")
CHILD_PY: str = (REPO_ROOT / "server" / "desktop_child.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# #448 — the embedder pin
# --------------------------------------------------------------------------
def test_the_embedder_pin_is_checked_against_the_marker() -> None:
    """The silently-wrong-results shape.

    Score is (1 + cos) / 2, so a mismatched vector space returns a FULL
    ranked list clustered near the 0.5 neutral midpoint rather than failing.
    Nothing looks broken. Config already carried this discipline for the
    reranker; the embedder never got it.
    """
    assert "from ingest.embedder import EMBEDDER_VERSION" in RESOURCES_PY
    assert "embedder_version != EMBEDDER_VERSION" in RESOURCES_PY
    assert "embedder_version_mismatch" in RESOURCES_PY


def test_the_embedder_mismatch_outranks_a_wrong_counter() -> None:
    """A DegradedState carries ONE reason, so the ordering is a real choice:
    the condition that changes ANSWERS must win over the one that changes a
    number."""
    embedder = RESOURCES_PY.index("embedder_version_mismatch")
    paper = RESOURCES_PY.index("paper_count_diverged")
    assert embedder < paper, (
        "the embedder check must run first, or a paper_count divergence can "
        "occupy the single degrade slot and hide it (#448)"
    )
    assert "if degraded is None:" in RESOURCES_PY, (
        "the lower-severity check must not overwrite an existing reason"
    )


# --------------------------------------------------------------------------
# #447 — paper_count, the symmetric check
# --------------------------------------------------------------------------
def test_paper_count_is_reconciled() -> None:
    assert "paper_count DIVERGED" in RESOURCES_PY
    assert "_PAPER_COUNT_SCAN_LIMIT" in RESOURCES_PY, (
        "an O(N) column scan at boot needs a size guard; an unchecked count "
        "beats a slow start, and `make reconcile` computes it on demand"
    )


def test_the_paper_count_scan_is_never_fatal() -> None:
    """Same FM-2 discipline count_rows() already has: a marker cross-check
    must never be the thing that stops a server from serving."""
    block = RESOURCES_PY[RESOURCES_PY.index("_PAPER_COUNT_SCAN_LIMIT") :][:2000]
    assert "except Exception" in block
    assert "startup_paper_count = -1" in block


# --------------------------------------------------------------------------
# #449 — a marker version the dataset never had
# --------------------------------------------------------------------------
def test_an_absent_marker_version_is_diagnosed_not_blamed_on_corruption() -> None:
    """The operator was being sent to restore from backup for a JSON typo."""
    assert "corpus_marker_version_absent" in CORPUS_PY
    assert "def _dataset_tip_version(" in CORPUS_PY
    block = CORPUS_PY[CORPUS_PY.index("corpus_marker_version_absent") :][:700]
    assert "NOT corrupt" in block, "say plainly that the data is fine"
    assert "make reconcile" in block


def test_the_tip_lookup_is_failure_path_only() -> None:
    """Its cost must never land on a healthy boot, and an unreadable dataset
    is a corruption question — guessing there would swap one wrong diagnosis
    for another."""
    fn = CORPUS_PY[CORPUS_PY.index("def _dataset_tip_version(") :][:900]
    assert "return None" in fn
    body = CORPUS_PY[CORPUS_PY.index("except corrupt_exc as primary_exc:") :][:900]
    assert "_dataset_tip_version(" in body, (
        "the lookup belongs on the failure path, not before the first open"
    )


def test_new_degrade_reasons_are_in_the_gauge_label_space() -> None:
    """A reason missing here never resets its gauge to 0 after it clears."""
    for reason in ("embedder_version_mismatch", "paper_count_diverged"):
        assert reason in HEALTH_PY, f"{reason} must be in the reset enum"


# --------------------------------------------------------------------------
# #459 / #460 / #461 — containment tells the truth
# --------------------------------------------------------------------------
def test_canonicalize_failures_are_distinguished() -> None:
    """EACCES, ENOENT and the rest are different repairs; one string sent an
    operator with a mode-000 directory looking for a missing file."""
    assert "fn canonicalize_reason(" in MAIN_RS
    fn = MAIN_RS[MAIN_RS.index("fn canonicalize_reason(") :][:700]
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
    fn = MAIN_RS[MAIN_RS.index("fn resolve_inside(") :][:1400]
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
    fn = LIFECYCLE_RS[LIFECYCLE_RS.index("pub fn open_private_log(") :][:900]
    assert ".append(true)" in fn
    assert ".truncate(true)" not in fn


# --------------------------------------------------------------------------
# #466 — the probe cannot clobber
# --------------------------------------------------------------------------
def test_the_plan_probe_cannot_overwrite_an_existing_file() -> None:
    """It ships enabled in the signed bundle and took its destination from
    argv unconstrained."""
    fn = MAIN_RS[MAIN_RS.index("fn emit_child_plan_probe(") :][:2000]
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
    fn = CHILD_PY[CHILD_PY.index("def _exit_without_finalizing(") :][:2200]
    assert "os._exit(code)" in fn


def test_the_child_flushes_before_exiting() -> None:
    """os._exit skips flushing too — losing the last log lines of a failed
    startup would trade one diagnostic problem for another."""
    fn = CHILD_PY[CHILD_PY.index("def _exit_without_finalizing(") :][:2200]
    assert "logging.shutdown()" in fn
    assert fn.index("logging.shutdown()") < fn.index("os._exit(code)")
