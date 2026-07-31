"""The backup-status producer/consumer contract — chris-dare-dev/arXMCP#202 + #203.

#202: ``ops/cron/arxmcp-backup.sh`` emitted ``"success"`` and composites of
the form ``backup_<phase>_forget_<phase>``, while ``server/health.py``
declared the enum ``("ok", "failed", "running", "unknown")``. The two sets
were **disjoint** — no value the producer could emit was a member of the
consumer's enum — so a perfect backup classified as ``unknown`` and
``arxmcp_backup_status{state="ok"}`` was pinned at 0.0 forever.

#203: the reader set ``BACKUP_LAST_SUCCESS_GAUGE`` from ``finished_at``
*before* looking at the run's status, so a failed run advanced the freshness
clock and suppressed ``ArXMCPBackupStale``.

Why this file exists as its own module rather than more cases in
``tests/test_server_metrics.py``: every pre-existing backup test hand-authored
its sentinel JSON with ``{"status": "ok"}`` — a value the producer never
emitted. The tests encoded the consumer's assumption instead of the
producer's reality, which is exactly how a wholly-disjoint vocabulary
survived. The tests here take their inputs from the REAL shell source, never
from a hand-typed token.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from server.backup_status import (
    BACKUP_STATE_FAILED,
    BACKUP_STATE_OK,
    BACKUP_STATE_PARTIAL,
    BACKUP_STATE_RUNNING,
    BACKUP_STATE_UNKNOWN,
    BACKUP_STATES,
    EMITTABLE_STATES,
    advances_freshness,
    classify_backup_state,
)
from server.health import compute_health_status, refresh_sentinel_metrics
from server.metrics import (
    BACKUP_LAST_SUCCESS_GAUGE,
    BACKUP_STATUS_GAUGE,
    reset_sentinel_metrics_for_tests,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
WRAPPER = REPO_ROOT / "ops" / "cron" / "arxmcp-backup.sh"
STATUS_LIB = REPO_ROOT / "ops" / "cron" / "backup-status-lib.sh"

#: ``ARXMCP_BACKUP_STATE_OK="ok"`` — the shell half's declarations.
_SHELL_STATE_DECL = re.compile(
    r'^ARXMCP_BACKUP_STATE_[A-Z]+="([a-z_]+)"$', re.MULTILINE
)

#: Every ``"status": "..."`` value the wrapper writes into a sentinel heredoc.
_SENTINEL_STATUS_VALUE = re.compile(r'^\s*"status":\s*"([^"]*)"', re.MULTILINE)


@pytest.fixture
def reset_backup_metrics():
    reset_sentinel_metrics_for_tests()
    yield
    reset_sentinel_metrics_for_tests()


def _write_sentinel(ops_dir: Path, payload: dict) -> None:
    ops_dir.mkdir(parents=True, exist_ok=True)
    (ops_dir / "backup-status.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _active_states() -> set[str]:
    """The label cells currently at 1.0."""
    return {
        state
        for state in BACKUP_STATES
        if BACKUP_STATUS_GAUGE.labels(state=state)._value.get() == 1.0
    }


class TestSharedVocabulary:
    """The producer and the consumer must name the same states."""

    def test_shell_lib_exists(self):
        assert STATUS_LIB.is_file(), (
            "ops/cron/backup-status-lib.sh is the shell half of the shared "
            "vocabulary; without it the wrapper re-invents its own tokens, "
            "which is arXMCP#202"
        )

    def test_shell_states_equal_python_emittable_states(self):
        """THE #202 regression guard.

        Had this assertion existed, it would have failed on the original
        code: the shell could emit {success, backup_*_forget_*} and Python
        accepted {ok, failed, running, unknown} — intersection empty.
        """
        shell_states = set(
            _SHELL_STATE_DECL.findall(
                STATUS_LIB.read_text(encoding="utf-8")
            )
        )
        assert shell_states, "no ARXMCP_BACKUP_STATE_* declarations found"
        assert shell_states == set(EMITTABLE_STATES), (
            "producer/consumer vocabulary drift: shell declares "
            f"{sorted(shell_states)}, server.backup_status.EMITTABLE_STATES "
            f"is {sorted(EMITTABLE_STATES)}"
        )

    def test_unknown_is_consumer_only(self):
        """``unknown`` is the catch-all; the producer must never emit it,
        or a real drift becomes indistinguishable from a normal run."""
        assert BACKUP_STATE_UNKNOWN not in EMITTABLE_STATES
        assert BACKUP_STATE_UNKNOWN in BACKUP_STATES
        assert set(BACKUP_STATES) == EMITTABLE_STATES | {BACKUP_STATE_UNKNOWN}

    def test_wrapper_writes_no_bare_status_literal(self):
        """Every ``"status"`` the wrapper emits must come from a shell
        variable, never a hand-typed literal — a literal is what drifted."""
        values = _SENTINEL_STATUS_VALUE.findall(
            WRAPPER.read_text(encoding="utf-8")
        )
        assert values, "no sentinel status field found in the wrapper"
        bare = [v for v in values if not re.fullmatch(r"\$\{[A-Z_]+\}", v)]
        assert not bare, (
            f"wrapper writes bare status literal(s) {bare}; they must come "
            "from the shared vocabulary in ops/cron/backup-status-lib.sh"
        )

    def test_wrapper_status_variables_are_vocabulary_bound(self):
        """The referenced variables are either a shared-vocabulary constant
        or FINAL_STATUS (whose value is proven below by running the real
        shell decision function)."""
        text = WRAPPER.read_text(encoding="utf-8")
        names = {
            re.fullmatch(r"\$\{([A-Z_]+)\}", v).group(1)
            for v in _SENTINEL_STATUS_VALUE.findall(text)
        }
        allowed_prefix = "ARXMCP_BACKUP_STATE_"
        unbound = {
            n
            for n in names
            if not n.startswith(allowed_prefix) and n != "FINAL_STATUS"
        }
        assert not unbound, (
            f"wrapper sentinel status references unbound variable(s) {sorted(unbound)}"
        )

    def test_wrapper_sources_the_shared_lib(self):
        text = WRAPPER.read_text(encoding="utf-8")
        assert "backup-status-lib.sh" in text
        assert "arxmcp_backup_final_status" in text

    def test_wrapper_no_longer_builds_composite_tokens(self):
        """The #202 shape: ``backup_${X}_forget_${Y}``."""
        text = WRAPPER.read_text(encoding="utf-8")
        assert "backup_${BACKUP_STATUS}_forget_" not in text
        assert "backup_complete_forget_pending" not in text


class TestRealShellOutputThroughHealthPy:
    """Pipe the REAL producer's output through the REAL consumer.

    ``arxmcp_backup_final_status`` is sourced from the shipped
    ``ops/cron/backup-status-lib.sh`` and driven over the full cross-product
    of phase outcomes; every token it yields is written to a real
    ``backup-status.json`` and passed to
    :func:`server.health.refresh_sentinel_metrics`. Nothing here is
    hand-typed, so the assertion "no emitted value classifies as unknown"
    is a claim about production code, not about a fixture.
    """

    @staticmethod
    def _bash() -> str:
        bash = shutil.which("bash")
        if bash is None:  # pragma: no cover - bash is present on dev boxes
            pytest.skip("bash not on PATH")
        return bash

    def _emitted_tokens(self) -> set[str]:
        """Run the real decision function over every phase combination.

        The phase inputs come from the SHELL's own ``ARXMCP_BACKUP_STATE_*``
        variables, not from the Python vocabulary — feeding it Python's
        tokens would make this test go green on a drifted producer by
        handing the function inputs it never actually sees.
        """
        shell_states = " ".join(
            f'"${{{name}}}"'
            for name in sorted(
                re.findall(
                    r"^(ARXMCP_BACKUP_STATE_[A-Z]+)=",
                    STATUS_LIB.read_text(encoding="utf-8"),
                    re.MULTILINE,
                )
            )
        )
        script = (
            f'source "{STATUS_LIB.as_posix()}"\n'
            f"for b in {shell_states}; do\n"
            f"  for f in {shell_states}; do\n"
            '    arxmcp_backup_final_status "$b" "$f"\n'
            "  done\n"
            "done\n"
        )
        result = subprocess.run(
            [self._bash(), "-euo", "pipefail", "-c", script],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"driving the real shell decision function failed:\n{result.stderr}"
        )
        tokens = {line.strip() for line in result.stdout.splitlines()}
        tokens.discard("")
        assert tokens, "the shell decision function emitted nothing"
        return tokens

    def test_no_shell_emitted_token_classifies_as_unknown(
        self, tmp_path: Path, reset_backup_metrics
    ):
        """THE headline assertion for #202."""
        ops_dir = tmp_path / "ops"
        for token in sorted(self._emitted_tokens()):
            _write_sentinel(
                ops_dir,
                {"status": token, "finished_at": "2026-07-31T03:51:12Z"},
            )
            refresh_sentinel_metrics(ops_dir)

            unknown = BACKUP_STATUS_GAUGE.labels(
                state=BACKUP_STATE_UNKNOWN
            )._value.get()
            assert unknown == 0.0, (
                f"the wrapper emits {token!r} and the server classifies it as "
                f"unknown — producer/consumer vocabulary drift (arXMCP#202)"
            )
            assert _active_states() == {token}, (
                f"{token!r} must light exactly its own cell; "
                f"active={sorted(_active_states())}"
            )

    def test_shell_decision_function_covers_the_expected_outcomes(self):
        """A clean run yields ok; anything else degrades. Guards against the
        function collapsing to a constant and passing the test above
        vacuously."""
        tokens = self._emitted_tokens()
        assert BACKUP_STATE_OK in tokens
        assert BACKUP_STATE_PARTIAL in tokens
        assert BACKUP_STATE_FAILED in tokens
        assert tokens <= EMITTABLE_STATES

    def test_clean_run_is_ok_and_failed_backup_stays_failed(self):
        """Pin the two decisions that matter most, by name."""
        script = (
            f'source "{STATUS_LIB.as_posix()}"\n'
            f'arxmcp_backup_final_status "{BACKUP_STATE_OK}" "{BACKUP_STATE_OK}"\n'
            f'arxmcp_backup_final_status "{BACKUP_STATE_FAILED}" "{BACKUP_STATE_OK}"\n'
            f'arxmcp_backup_final_status "{BACKUP_STATE_OK}" "{BACKUP_STATE_FAILED}"\n'
            f'arxmcp_backup_final_status "{BACKUP_STATE_PARTIAL}" "{BACKUP_STATE_OK}"\n'
        )
        result = subprocess.run(
            [self._bash(), "-euo", "pipefail", "-c", script],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.split() == [
            BACKUP_STATE_OK,
            BACKUP_STATE_FAILED,
            BACKUP_STATE_PARTIAL,
            BACKUP_STATE_PARTIAL,
        ]


class TestEveryEmittableStateIsConsumable:
    """The always-runs half of the #202 guard — no bash required.

    Byte-fixtures of the sentinel the wrapper writes, one per emittable
    state, driven through the real consumer.
    """

    def test_no_emittable_state_classifies_as_unknown(
        self, tmp_path: Path, reset_backup_metrics
    ):
        ops_dir = tmp_path / "ops"
        for state in sorted(EMITTABLE_STATES):
            assert classify_backup_state(state) == state
            _write_sentinel(
                ops_dir,
                {"status": state, "finished_at": "2026-07-31T03:51:12Z"},
            )
            refresh_sentinel_metrics(ops_dir)
            assert _active_states() == {state}
            assert (
                BACKUP_STATUS_GAUGE.labels(
                    state=BACKUP_STATE_UNKNOWN
                )._value.get()
                == 0.0
            )

    def test_the_old_producer_vocabulary_would_still_be_caught(
        self, tmp_path: Path, reset_backup_metrics, caplog
    ):
        """The pre-fix tokens must classify as unknown AND log — proving the
        F4 guard still works and that the fix is a vocabulary change, not a
        loosening of the guard."""
        ops_dir = tmp_path / "ops"
        for legacy in ("success", "backup_partial_forget_success"):
            with caplog.at_level("WARNING"):
                caplog.clear()
                _write_sentinel(
                    ops_dir,
                    {"status": legacy, "finished_at": "2026-07-31T03:51:12Z"},
                )
                refresh_sentinel_metrics(ops_dir)
            assert _active_states() == {BACKUP_STATE_UNKNOWN}
            assert any(
                "reports unknown state" in rec.message for rec in caplog.records
            )


class TestFailedRunDoesNotAdvanceFreshness:
    """chris-dare-dev/arXMCP#203 regression guards.

    ``finished_at`` is stamped by the wrapper on every run that reaches the
    end, success or not. The freshness gauge must move only on a state in
    ``FRESHNESS_ADVANCING_STATES``.
    """

    LAST_GOOD = "2026-07-30T03:51:12Z"
    LATER = "2026-07-31T03:51:12Z"

    def _epoch(self, iso: str) -> float:
        from datetime import datetime

        return datetime.fromisoformat(iso).timestamp()

    def _seed_good_backup(self, ops_dir: Path) -> float:
        _write_sentinel(
            ops_dir, {"status": BACKUP_STATE_OK, "finished_at": self.LAST_GOOD}
        )
        refresh_sentinel_metrics(ops_dir)
        good = self._epoch(self.LAST_GOOD)
        assert BACKUP_LAST_SUCCESS_GAUGE._value.get() == good
        return good

    @pytest.mark.parametrize(
        "state",
        [BACKUP_STATE_FAILED, BACKUP_STATE_PARTIAL, BACKUP_STATE_RUNNING],
    )
    def test_non_success_leaves_freshness_gauge_unchanged(
        self, tmp_path: Path, reset_backup_metrics, state
    ):
        """THE headline assertion for #203.

        Pre-fix, the reader set the gauge from ``finished_at`` before
        reading ``status`` at all, so this advanced to ``LATER`` and
        ArXMCPBackupStale could never fire on a run of failures.
        """
        ops_dir = tmp_path / "ops"
        good = self._seed_good_backup(ops_dir)

        _write_sentinel(
            ops_dir, {"status": state, "finished_at": self.LATER}
        )
        refresh_sentinel_metrics(ops_dir)

        assert BACKUP_LAST_SUCCESS_GAUGE._value.get() == good, (
            f"a {state!r} run advanced the last-success clock from the real "
            "last good backup; the staleness alert is suppressed (arXMCP#203)"
        )
        assert _active_states() == {state}

    def test_unknown_state_leaves_freshness_gauge_unchanged(
        self, tmp_path: Path, reset_backup_metrics
    ):
        """The #202 + #203 interaction: while the vocabularies were
        disjoint every run classified unknown, so this is the path the
        production system actually took."""
        ops_dir = tmp_path / "ops"
        good = self._seed_good_backup(ops_dir)

        _write_sentinel(ops_dir, {"status": "success", "finished_at": self.LATER})
        refresh_sentinel_metrics(ops_dir)

        assert BACKUP_LAST_SUCCESS_GAUGE._value.get() == good
        assert _active_states() == {BACKUP_STATE_UNKNOWN}

    def test_missing_status_key_does_not_advance_freshness(
        self, tmp_path: Path, reset_backup_metrics
    ):
        """A truncated / half-written sentinel must not read as a success."""
        ops_dir = tmp_path / "ops"
        good = self._seed_good_backup(ops_dir)

        _write_sentinel(ops_dir, {"finished_at": self.LATER})
        refresh_sentinel_metrics(ops_dir)

        assert BACKUP_LAST_SUCCESS_GAUGE._value.get() == good
        assert _active_states() == {BACKUP_STATE_UNKNOWN}

    def test_successful_run_does_advance(
        self, tmp_path: Path, reset_backup_metrics
    ):
        """The gate must not be so tight it never opens."""
        ops_dir = tmp_path / "ops"
        self._seed_good_backup(ops_dir)

        _write_sentinel(
            ops_dir, {"status": BACKUP_STATE_OK, "finished_at": self.LATER}
        )
        refresh_sentinel_metrics(ops_dir)

        assert BACKUP_LAST_SUCCESS_GAUGE._value.get() == self._epoch(self.LATER)

    def test_only_ok_advances_freshness(self):
        for state in BACKUP_STATES:
            assert advances_freshness(state) is (state == BACKUP_STATE_OK)


class TestWrapperEmitsFailedState:
    """``failed`` has to be reachable, or alerting on it is dead.

    The hard-failure path used to ``exit`` without writing a sentinel, so
    ``arxmcp_backup_status{state="failed"}`` could never become 1.0 and the
    operator saw the previous run's values.
    """

    def test_hard_failure_path_writes_a_failed_sentinel(self):
        text = WRAPPER.read_text(encoding="utf-8")
        fail_branch = text.index("ERROR: restic backup failed")
        exit_stmt = text.index('exit "${RESTIC_BACKUP_EXIT}"', fail_branch)
        between = text[fail_branch:exit_stmt]
        assert '"status": "${ARXMCP_BACKUP_STATE_FAILED}"' in between, (
            "the hard-failure path must write a failed sentinel BEFORE "
            "exiting, or the failed state is unreachable"
        )
        assert 'mv "${TMP_STATUS}" "${STATUS_FILE}"' in between

    def test_in_flight_sentinel_uses_running(self):
        text = WRAPPER.read_text(encoding="utf-8")
        assert '"status": "${ARXMCP_BACKUP_STATE_RUNNING}"' in text

    def test_in_flight_sentinel_has_no_finished_at(self):
        """A run still in flight must not stamp finished_at at all — that
        is the cheapest possible defense for the #203 half."""
        text = WRAPPER.read_text(encoding="utf-8")
        start = text.index('"status": "${ARXMCP_BACKUP_STATE_RUNNING}"')
        # Walk back to the opening brace of that heredoc body.
        block_start = text.rindex("cat > \"${TMP_STATUS}\"", 0, start)
        assert "finished_at" not in text[block_start:start]


# ---------------------------------------------------------------------------
# The #202 / #203 FOLLOW-UP — carrying last_success_at across runs
# ---------------------------------------------------------------------------
#
# #203 stopped a failed run from advancing the freshness clock, which left a
# residual hole: the sentinel records only the MOST RECENT run, and
# BACKUP_LAST_SUCCESS_GAUGE is process state rehydrated from that file at each
# /metrics scrape. Restart the server while the latest run is failed/partial
# and the gauge starts at 0.0 with nothing able to advance it — ArXMCPBackupStale
# fires immediately with an age computed from epoch 0. Fail-loud in the right
# direction, meaningless number. The /status backup:time check had the same
# hole. The wrapper now carries last_success_at onto EVERY sentinel it writes.


#: ``cat > "${TMP_STATUS}" <<EOF … EOF`` — one per sentinel the wrapper writes.
_SENTINEL_HEREDOC = re.compile(
    r'^[ \t]*cat > "\$\{TMP_STATUS\}" <<EOF\n(.*?)^EOF$',
    re.MULTILINE | re.DOTALL,
)

#: ``${NAME}`` references inside a heredoc body.
_SHELL_VAR_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

#: What the wrapper's own ``date -u +%Y-%m-%dT%H:%M:%SZ`` produces.
_PRIOR_SUCCESS = "2026-07-29T03:41:07Z"
_LATER = "2026-07-31T03:51:12Z"


def _bash_or_skip() -> str:
    bash = shutil.which("bash")
    if bash is None:  # pragma: no cover - bash is present on dev boxes
        pytest.skip("bash not on PATH")
    return bash


def _epoch(iso: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(iso).timestamp()


class TestWrapperCarriesLastSuccessForward:
    """Producer-side structure: the wrapper must read the prior sentinel
    before it clobbers it, and stamp the carried value on every write."""

    def test_wrapper_reads_prior_sentinel_before_the_first_overwrite(self):
        """Order is the whole trick. The read has to happen before ANY
        ``mv`` lands on STATUS_FILE, or the carried value is read back off
        the sentinel this run just wrote."""
        text = WRAPPER.read_text(encoding="utf-8")
        read_at = text.index("arxmcp_backup_prior_last_success")
        first_write = text.index('cat > "${TMP_STATUS}"')
        assert read_at < first_write, (
            "the prior sentinel must be read before the first sentinel write; "
            "afterwards its last_success_at is already gone"
        )

    def test_every_sentinel_the_wrapper_writes_carries_the_field(self):
        """Including the failed / partial / running ones — those are exactly
        the sentinels a restart can land on, which is the bug."""
        bodies = _SENTINEL_HEREDOC.findall(WRAPPER.read_text(encoding="utf-8"))
        assert len(bodies) == 3, (
            f"expected the failed + running + final sentinel writes, found "
            f"{len(bodies)}"
        )
        missing = [b for b in bodies if '"last_success_at":' not in b]
        assert not missing, (
            "a sentinel omits last_success_at; a restart landing on that one "
            "leaves the freshness gauge at 0.0 with nothing to advance it"
        )

    def test_sentinel_writes_stay_atomic(self):
        """Two-phase write discipline: every heredoc goes to TMP_STATUS and
        is published by ``mv``, never written to STATUS_FILE in place. A
        scrape landing mid-write must never see a truncated sentinel."""
        text = WRAPPER.read_text(encoding="utf-8")
        for match in _SENTINEL_HEREDOC.finditer(text):
            tail = text[match.end() :]
            next_write = tail.find('cat > "${TMP_STATUS}"')
            window = tail if next_write == -1 else tail[:next_write]
            assert 'mv "${TMP_STATUS}" "${STATUS_FILE}"' in window, (
                "a sentinel heredoc is not followed by the atomic mv"
            )
        assert 'cat > "${STATUS_FILE}"' not in text

    def test_only_a_clean_run_advances_the_carried_stamp(self):
        """``FINISHED_AT`` may become the new last_success_at only behind an
        ok check — the same gate as FRESHNESS_ADVANCING_STATES. Otherwise the
        carry-forward would quietly re-open #203 from the producer side."""
        text = WRAPPER.read_text(encoding="utf-8")
        advance = text.index('LAST_SUCCESS_JSON="\\"${FINISHED_AT}\\""')
        guard = text.rindex(
            'if [ "${FINAL_STATUS}" = "${ARXMCP_BACKUP_STATE_OK}" ]; then',
            0,
            advance,
        )
        assert "\n" not in text[guard:advance].strip().split("then", 1)[1].strip(), (
            "the advance must sit directly under the ok guard"
        )
        assert 'LAST_SUCCESS_JSON="${PRIOR_LAST_SUCCESS_JSON}"' in text, (
            "a non-ok run must re-emit the prior value unchanged"
        )


class TestPriorLastSuccessShellFunction:
    """Drive the REAL producer-side reader over real sentinel files.

    ``arxmcp_backup_prior_last_success`` lives in the shared lib precisely so
    this is possible: the resolution order under test is the shipped one, not
    a Python restatement of it.
    """

    def _call(self, tmp_path: Path, payload: object | None) -> str:
        status_file = tmp_path / "backup-status.json"
        if payload is not None:
            status_file.write_text(
                payload if isinstance(payload, str) else json.dumps(payload),
                encoding="utf-8",
            )
        script = (
            f'source "{STATUS_LIB.as_posix()}"\n'
            f'arxmcp_backup_prior_last_success "{status_file.as_posix()}" '
            f'"${{ARXMCP_BACKUP_STATE_OK}}"\n'
        )
        result = subprocess.run(
            [_bash_or_skip(), "-euo", "pipefail", "-c", script],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            "the reader must never fail the run — the wrapper calls it under "
            f"set -euo pipefail:\n{result.stderr}"
        )
        return result.stdout.strip()

    def test_carries_last_success_at_off_a_failed_sentinel(self, tmp_path):
        """THE headline for the follow-up: a failed run still names the last
        good backup."""
        assert self._call(
            tmp_path,
            {
                "status": BACKUP_STATE_FAILED,
                "finished_at": _LATER,
                "last_success_at": _PRIOR_SUCCESS,
            },
        ) == _PRIOR_SUCCESS

    @pytest.mark.parametrize(
        "state", [BACKUP_STATE_PARTIAL, BACKUP_STATE_RUNNING]
    )
    def test_carries_through_partial_and_running(self, tmp_path, state):
        assert self._call(
            tmp_path,
            {"status": state, "last_success_at": _PRIOR_SUCCESS},
        ) == _PRIOR_SUCCESS

    def test_falls_back_to_finished_at_on_an_ok_sentinel(self, tmp_path):
        """The upgrade path: a sentinel written before the field existed
        still seeds the carry chain, provided the run actually succeeded."""
        assert self._call(
            tmp_path, {"status": BACKUP_STATE_OK, "finished_at": _PRIOR_SUCCESS}
        ) == _PRIOR_SUCCESS

    def test_does_not_fall_back_to_finished_at_on_a_failed_sentinel(
        self, tmp_path
    ):
        """arXMCP#203 from the producer side. The wrapper stamps finished_at
        on every run that reaches the end; treating a legacy failed sentinel's
        finished_at as a success would manufacture a last-good time that never
        existed."""
        assert self._call(
            tmp_path,
            {"status": BACKUP_STATE_FAILED, "finished_at": _LATER},
        ) == ""

    @pytest.mark.parametrize(
        ("label", "payload"),
        [
            ("absent", None),
            ("truncated", '{"status": "ok", "finished'),
            ("not-json", "this is not json at all"),
            ("json-but-a-list", "[1, 2, 3]"),
            ("null-carry", {"status": "failed", "last_success_at": None}),
            ("non-string-carry", {"status": "failed", "last_success_at": 17}),
            (
                "wrong-shape",
                {"status": "failed", "last_success_at": "yesterday"},
            ),
        ],
    )
    def test_unusable_prior_yields_empty_never_an_error(
        self, tmp_path, label, payload
    ):
        """The wrapper runs under ``set -euo pipefail``; a backup must not
        abort over its own bookkeeping."""
        assert self._call(tmp_path, payload) == "", label

    def test_a_quote_bearing_value_cannot_escape_the_json_literal(
        self, tmp_path
    ):
        """The carried value is interpolated into a JSON string literal by
        the wrapper. A hand-edited sentinel must not be able to inject
        structure into the next one."""
        assert self._call(
            tmp_path,
            {
                "status": BACKUP_STATE_FAILED,
                "last_success_at": '2026-07-29T03:41:07Z", "status": "ok',
            },
        ) == ""


class TestRenderedSentinelsAreValidJson:
    """Render each sentinel heredoc through the real bash and parse it.

    Every other producer-side test in this repo greps the wrapper's TEXT.
    Adding a field to three hand-written JSON heredocs is exactly the edit a
    grep cannot vet — a dropped comma yields a file the server can only
    report as malformed, and ``restic`` is not installed here so the wrapper
    is never run end-to-end.
    """

    def _render(self, tmp_path: Path, body: str, carried: str) -> dict:
        # The wrapper body lives inside ``bash -c '<single-quoted>'``, so
        # ``'"${REPO_ROOT}"'`` is expanded by the OUTER shell before bash -c
        # ever sees it. Reproduce that, which also leaves the extracted body
        # apostrophe-free.
        body = body.replace("'\"${REPO_ROOT}\"'", "${REPO_ROOT}")
        assert "'" not in body

        out = tmp_path / "backup-status.json"
        assignments = [
            f'source "{STATUS_LIB.as_posix()}"',
            'REPO_ROOT="/srv/arxmcp"',
            f'TMP_STATUS="{out.as_posix()}"',
        ]
        for name in sorted(set(_SHELL_VAR_REF.findall(body))):
            if name.startswith("ARXMCP_BACKUP_STATE_") or name == "REPO_ROOT":
                continue  # from the shared lib / set above
            if name.endswith("_JSON"):
                # A bare JSON literal, quotes included — the wrapper builds
                # these the same way (``VAR="\"${STAMP}\""`` / ``VAR=null``)
                # so the field can be null rather than an empty string.
                assignments.append(f"{name}='{carried}'")
                continue
            if name.endswith("_EXIT"):
                value = "0"
            elif name.endswith("_AT"):
                value = _LATER
            else:
                value = f"{name.lower()}-placeholder"
            assignments.append(f'{name}="{value}"')

        script = tmp_path / "render.sh"
        script.write_text(
            "set -euo pipefail\n"
            + "\n".join(assignments)
            + '\ncat > "${TMP_STATUS}" <<EOF\n'
            + body
            + "EOF\n",
            encoding="utf-8",
            newline="\n",
        )
        result = subprocess.run(
            [_bash_or_skip(), str(script)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        return json.loads(out.read_text(encoding="utf-8"))

    @pytest.mark.parametrize("index", [0, 1, 2])
    def test_sentinel_parses_with_a_carried_stamp(self, tmp_path, index):
        bodies = _SENTINEL_HEREDOC.findall(WRAPPER.read_text(encoding="utf-8"))
        payload = self._render(
            tmp_path, bodies[index], f'"{_PRIOR_SUCCESS}"'
        )
        assert payload["last_success_at"] == _PRIOR_SUCCESS

    @pytest.mark.parametrize("index", [0, 1, 2])
    def test_sentinel_parses_when_nothing_has_ever_succeeded(
        self, tmp_path, index
    ):
        """``null``, not ``""`` — a consumer must be able to tell "no
        successful backup on record" from a malformed field."""
        bodies = _SENTINEL_HEREDOC.findall(WRAPPER.read_text(encoding="utf-8"))
        payload = self._render(tmp_path, bodies[index], "null")
        assert payload["last_success_at"] is None

    def test_a_never_succeeded_sentinel_reads_as_no_success(
        self, tmp_path, reset_backup_metrics
    ):
        """A rendered ``null`` sentinel must not classify as a success on the
        consumer side either — round-trip the real bytes, don't assume."""
        bodies = _SENTINEL_HEREDOC.findall(WRAPPER.read_text(encoding="utf-8"))
        ops_dir = tmp_path / "ops"
        ops_dir.mkdir()
        payload = self._render(tmp_path, bodies[0], "null")
        (ops_dir / "backup-status.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        refresh_sentinel_metrics(ops_dir)
        assert BACKUP_LAST_SUCCESS_GAUGE._value.get() == 0.0


class TestFreshnessSurvivesRestart:
    """Consumer side. Each test resets the gauges first — that IS the
    restart: a fresh process has no prior value, only the sentinel on disk.
    """

    @pytest.mark.parametrize(
        "state",
        [BACKUP_STATE_FAILED, BACKUP_STATE_PARTIAL, BACKUP_STATE_RUNNING],
    )
    def test_carried_stamp_seeds_the_gauge_on_a_non_ok_sentinel(
        self, tmp_path: Path, reset_backup_metrics, state
    ):
        """THE headline assertion for the follow-up.

        Pre-fix the gauge sat at 0.0 here and ArXMCPBackupStale fired with an
        age of ``time() - 0`` — around 56 years — which tells the operator
        nothing about when the last good backup actually was.
        """
        ops_dir = tmp_path / "ops"
        _write_sentinel(
            ops_dir,
            {
                "status": state,
                "finished_at": _LATER,
                "last_success_at": _PRIOR_SUCCESS,
            },
        )
        refresh_sentinel_metrics(ops_dir)

        assert BACKUP_LAST_SUCCESS_GAUGE._value.get() == _epoch(_PRIOR_SUCCESS)
        # …and the run's own outcome is still reported truthfully.
        assert _active_states() == {state}

    def test_carried_stamp_does_not_smuggle_in_the_current_run(
        self, tmp_path: Path, reset_backup_metrics
    ):
        """#203 must still hold: the gauge takes the CARRIED value, never the
        failed run's own ``finished_at``."""
        ops_dir = tmp_path / "ops"
        _write_sentinel(
            ops_dir,
            {
                "status": BACKUP_STATE_FAILED,
                "finished_at": _LATER,
                "last_success_at": _PRIOR_SUCCESS,
            },
        )
        refresh_sentinel_metrics(ops_dir)
        assert BACKUP_LAST_SUCCESS_GAUGE._value.get() != _epoch(_LATER)

    def test_legacy_sentinel_without_the_field_keeps_203_behavior(
        self, tmp_path: Path, reset_backup_metrics
    ):
        """A sentinel from a wrapper predating the field: ``finished_at`` on
        a failed run is still not evidence of a backup."""
        ops_dir = tmp_path / "ops"
        _write_sentinel(
            ops_dir, {"status": BACKUP_STATE_FAILED, "finished_at": _LATER}
        )
        refresh_sentinel_metrics(ops_dir)
        assert BACKUP_LAST_SUCCESS_GAUGE._value.get() == 0.0

    def test_ok_run_advances_past_a_stale_carried_value(
        self, tmp_path: Path, reset_backup_metrics
    ):
        """The wrapper writes ``last_success_at == finished_at`` on a clean
        run, so the gate must not be so tight it pins the gauge to an old
        carried value."""
        ops_dir = tmp_path / "ops"
        _write_sentinel(
            ops_dir,
            {
                "status": BACKUP_STATE_OK,
                "finished_at": _LATER,
                "last_success_at": _LATER,
            },
        )
        refresh_sentinel_metrics(ops_dir)
        assert BACKUP_LAST_SUCCESS_GAUGE._value.get() == _epoch(_LATER)

    def test_unparseable_carried_value_falls_back_and_warns(
        self, tmp_path: Path, reset_backup_metrics, caplog
    ):
        """One corrupt field must not cost the other, usable one."""
        ops_dir = tmp_path / "ops"
        with caplog.at_level("WARNING"):
            _write_sentinel(
                ops_dir,
                {
                    "status": BACKUP_STATE_OK,
                    "finished_at": _LATER,
                    "last_success_at": "not-a-timestamp",
                },
            )
            refresh_sentinel_metrics(ops_dir)
        assert BACKUP_LAST_SUCCESS_GAUGE._value.get() == _epoch(_LATER)
        assert any(
            "unparseable last_success_at" in rec.message
            for rec in caplog.records
        )

    def test_producer_to_consumer_round_trip(
        self, tmp_path: Path, reset_backup_metrics
    ):
        """End to end: the REAL shell reader resolves the carried value off
        yesterday's sentinel, it is stamped onto today's failed one, and the
        REAL consumer rehydrates the gauge from it in a fresh process."""
        prior = tmp_path / "prior.json"
        prior.write_text(
            json.dumps(
                {"status": BACKUP_STATE_OK, "finished_at": _PRIOR_SUCCESS}
            ),
            encoding="utf-8",
        )
        script = (
            f'source "{STATUS_LIB.as_posix()}"\n'
            f'arxmcp_backup_prior_last_success "{prior.as_posix()}" '
            f'"${{ARXMCP_BACKUP_STATE_OK}}"\n'
        )
        result = subprocess.run(
            [_bash_or_skip(), "-euo", "pipefail", "-c", script],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        carried = result.stdout.strip()

        ops_dir = tmp_path / "ops"
        _write_sentinel(
            ops_dir,
            {
                "status": BACKUP_STATE_FAILED,
                "finished_at": _LATER,
                "last_success_at": carried,
            },
        )
        refresh_sentinel_metrics(ops_dir)
        assert BACKUP_LAST_SUCCESS_GAUGE._value.get() == _epoch(_PRIOR_SUCCESS)


class TestStatusBackupCheckUsesTheCarriedStamp:
    """``/status``'s ``backup:time`` check has the same rehydration story as
    the gauge and must reach the same verdict — that both consumers read one
    resolver is the point."""

    def _report(self, tmp_path: Path, payload: dict, *, now: float) -> dict:
        from tests.test_status_endpoint import (
            _FakeResources,
            _FakeStore,
            _run,
        )

        ops = tmp_path / "ops"
        ops.mkdir(parents=True, exist_ok=True)
        (ops / "backup-status.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        res = _FakeResources(warm=True, data_dir=tmp_path, ops_dir=ops)
        report = _run(compute_health_status(res, _FakeStore(1), now=now))
        return report["checks"]["backup:time"][0]

    def test_failed_run_reports_the_real_last_good_time(self, tmp_path):
        """It still warns — the latest run failed — but the operator now gets
        the true last-good timestamp instead of "no backup recorded"."""
        check = self._report(
            tmp_path,
            {
                "status": BACKUP_STATE_FAILED,
                "finished_at": _LATER,
                "last_success_at": _PRIOR_SUCCESS,
            },
            now=_epoch(_LATER),
        )
        assert check["status"] == "warn"
        assert check["observedValue"] == _PRIOR_SUCCESS
        assert "did not succeed" in check["output"]
        assert "last success 48h ago" in check["output"]

    def test_failed_run_with_no_history_says_so(self, tmp_path):
        check = self._report(
            tmp_path,
            {
                "status": BACKUP_STATE_FAILED,
                "finished_at": _LATER,
                "last_success_at": None,
            },
            now=_epoch(_LATER),
        )
        assert check["status"] == "warn"
        assert "no successful backup on record" in check["output"]
        assert "observedValue" not in check

    def test_a_recent_carried_success_still_warns_on_a_failed_run(
        self, tmp_path
    ):
        """A carried timestamp inside the freshness window must not paper
        over the failure — #203 in the /status surface."""
        check = self._report(
            tmp_path,
            {
                "status": BACKUP_STATE_FAILED,
                "finished_at": _LATER,
                "last_success_at": _LATER,
            },
            now=_epoch(_LATER) + 60,
        )
        assert check["status"] == "warn"
        assert "did not succeed" in check["output"]

    def test_both_consumers_agree_on_the_last_good_time(
        self, tmp_path, reset_backup_metrics
    ):
        payload = {
            "status": BACKUP_STATE_PARTIAL,
            "finished_at": _LATER,
            "last_success_at": _PRIOR_SUCCESS,
        }
        check = self._report(tmp_path, payload, now=_epoch(_LATER))
        refresh_sentinel_metrics(tmp_path / "ops")
        assert (
            _epoch(str(check["observedValue"]))
            == BACKUP_LAST_SUCCESS_GAUGE._value.get()
        )
