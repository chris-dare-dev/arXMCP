"""Sandboxed SymPy/CAS runner tests (stage2/arx-d3 — WS-D D-5;
AC-D.11).

The three mandated behaviors, pinned:

1. **Flag off ⇒ the runner refuses** — a structured ``disabled``
   envelope and provably NO subprocess spawn (default posture).
2. **Timeout kills the runner** — a spinning check is killed and
   reaped at the wall-clock budget; the envelope says so.
3. Counterexample searches return structured, replayable envelopes
   (code + params + timeout recorded on EVERY path).

These are real-subprocess tests (no mocks on the execution paths);
only the refusal/argv tests monkeypatch ``subprocess.Popen``.
"""

from __future__ import annotations

import importlib.util
import json
import textwrap

import pytest

from server.proving import sympy_runner
from server.proving.sympy_runner import (
    CAS_ENABLE_ENV_VAR,
    CasCheckSpec,
    cas_enabled,
    run_cas_check,
)

#: Pure-Python primality scan — no sympy import, so the check runs in
#: any interpreter. The classic FALSE-must-reject seed (kat-fm-02):
#: n² + n + 41 is composite first at n = 40.
_TRIAL_DIVISION_CODE = textwrap.dedent(
    """\
    def _is_prime(k):
        if k < 2:
            return False
        d = 2
        while d * d <= k:
            if k % d == 0:
                return False
            d += 1
        return True

    def find_counterexample(start, stop):
        for n in range(start, stop):
            value = n * n + n + 41
            if not _is_prime(value):
                return {"n": n, "value": value}
        return None
    """
)

_SPIN_CODE = "def find_counterexample():\n    while True:\n        pass\n"

_HAS_SYMPY = importlib.util.find_spec("sympy") is not None


@pytest.fixture(autouse=True)
def _flag_unset(monkeypatch):
    """Every test starts from the default posture: gate OFF."""
    monkeypatch.delenv(CAS_ENABLE_ENV_VAR, raising=False)


def _spec(**kw) -> CasCheckSpec:
    defaults = {
        "name": "n2n41-scan",
        "code": _TRIAL_DIVISION_CODE,
        "params": {"start": 0, "stop": 200},
        "timeout_s": 30.0,
    }
    defaults.update(kw)
    return CasCheckSpec(**defaults)


class TestGate:
    def test_default_off(self):
        assert cas_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "On", " 1 "])
    def test_truthy_env_values(self, monkeypatch, value):
        monkeypatch.setenv(CAS_ENABLE_ENV_VAR, value)
        assert cas_enabled() is True

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "banana"])
    def test_falsy_env_values(self, monkeypatch, value):
        monkeypatch.setenv(CAS_ENABLE_ENV_VAR, value)
        assert cas_enabled() is False

    def test_explicit_overrides_env(self, monkeypatch):
        monkeypatch.setenv(CAS_ENABLE_ENV_VAR, "1")
        assert cas_enabled(False) is False
        monkeypatch.delenv(CAS_ENABLE_ENV_VAR)
        assert cas_enabled(True) is True

    def test_flag_off_refuses_and_spawns_nothing(self, monkeypatch):
        """The mandated refusal test: default posture ⇒ a structured
        `disabled` envelope and NO subprocess — Popen is booby-trapped."""

        def _boom(*args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("flag off must never spawn a subprocess")

        monkeypatch.setattr(sympy_runner.subprocess, "Popen", _boom)
        env = run_cas_check(_spec())
        assert env["status"] == "disabled"
        assert env["found"] is None
        assert env["witness"] is None
        assert CAS_ENABLE_ENV_VAR in env["detail"]
        # AC-D.11 replay floor present even on the refused path.
        assert env["code"] == _TRIAL_DIVISION_CODE
        assert env["params"] == {"start": 0, "stop": 200}
        assert env["timeout_s"] == 30.0

    def test_env_var_enables_without_explicit(self, monkeypatch):
        monkeypatch.setenv(CAS_ENABLE_ENV_VAR, "1")
        env = run_cas_check(_spec())
        assert env["status"] == "ok"


class TestExecution:
    def test_known_false_statement_finds_counterexample(self):
        """n² + n + 41 (FALSE-must-reject seed): the scan finds n = 40."""
        env = run_cas_check(_spec(), enabled=True)
        assert env["status"] == "ok"
        assert env["found"] is True
        assert env["witness"] == {"n": 40, "value": 1681}
        assert env["exit_code"] == 0
        assert env["wall_clock_s"] is not None and env["wall_clock_s"] >= 0
        assert env["child_python"]

    def test_no_counterexample_in_range(self):
        env = run_cas_check(
            _spec(params={"start": 0, "stop": 40}), enabled=True
        )
        assert env["status"] == "ok"
        assert env["found"] is False
        assert env["witness"] is None

    def test_replay_envelope_records_code_params_timeout(self):
        """AC-D.11: the artifact alone suffices to replay the check."""
        env = run_cas_check(_spec(), enabled=True)
        assert env["code"] == _TRIAL_DIVISION_CODE
        assert env["params"] == {"start": 0, "stop": 200}
        assert env["timeout_s"] == 30.0
        assert env["engine"] == "sympy-subprocess"
        assert env["python_executable"]

    def test_timeout_kills_the_runner(self):
        """The mandated timeout test: a spinning check is killed at the
        wall clock and REAPED (exit_code present = communicate returned
        after kill; no zombie/handle leak)."""
        env = run_cas_check(
            _spec(name="spin", code=_SPIN_CODE, params={}, timeout_s=1.0),
            enabled=True,
        )
        assert env["status"] == "timeout"
        assert env["exit_code"] is not None
        assert env["wall_clock_s"] >= 1.0
        assert env["wall_clock_s"] < 30.0
        assert "killed" in env["detail"]

    def test_check_exception_is_structured_error(self):
        env = run_cas_check(
            _spec(
                name="boom",
                code="def find_counterexample():\n    raise ValueError('nope')\n",
                params={},
            ),
            enabled=True,
        )
        assert env["status"] == "error"
        assert "ValueError" in env["detail"]

    def test_missing_function_is_structured_error(self):
        env = run_cas_check(
            _spec(name="nofn", code="x = 1\n", params={}), enabled=True
        )
        assert env["status"] == "error"
        assert "find_counterexample" in env["detail"]

    def test_unserializable_witness_is_structured_error(self):
        env = run_cas_check(
            _spec(
                name="badwitness",
                code="def find_counterexample():\n    return {1, 2, 3}\n",
                params={},
            ),
            enabled=True,
        )
        assert env["status"] == "error"
        assert "non-JSON-serializable" in env["detail"]

    def test_user_prints_do_not_corrupt_parsing(self):
        code = (
            "def find_counterexample():\n"
            "    print('scanning...')\n"
            "    print('still scanning')\n"
            "    return 7\n"
        )
        env = run_cas_check(_spec(name="chatty", code=code, params={}), enabled=True)
        assert env["status"] == "ok"
        assert env["witness"] == 7

    def test_marker_spoof_is_overridden_by_real_result(self):
        """Check code printing a fake result marker cannot forge a
        witness: the parent reads the LAST marker line, and the harness
        writes the authoritative one after the check returns."""
        fake = json.dumps({"found": True, "witness": 99})
        code = (
            "def find_counterexample():\n"
            f"    print('__ARXMCP_CAS_RESULT__ ' + {fake!r})\n"
            "    return None\n"
        )
        env = run_cas_check(_spec(name="spoof", code=code, params={}), enabled=True)
        assert env["status"] == "ok"
        assert env["found"] is False
        assert env["witness"] is None


class TestIsolation:
    def test_child_runs_in_isolated_mode(self, monkeypatch):
        """The child interpreter gets ``-I`` (no user site, PYTHON*
        env ignored, no cwd on sys.path) and the spec goes over stdin,
        never argv."""
        captured: dict = {}

        class _FakeProc:
            pid = 4242
            returncode = 0

            def communicate(self, payload=None, timeout=None):
                captured["stdin"] = payload
                return (
                    "\n__ARXMCP_CAS_RESULT__ "
                    + json.dumps({"found": False, "witness": None, "child_python": "x"})
                    + "\n",
                    "",
                )

        def _fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return _FakeProc()

        monkeypatch.setattr(sympy_runner.subprocess, "Popen", _fake_popen)
        env = run_cas_check(_spec(), enabled=True)
        assert env["status"] == "ok"
        assert captured["cmd"][1] == "-I"
        assert "-c" in captured["cmd"]
        loaded = json.loads(captured["stdin"])
        assert loaded["code"] == _TRIAL_DIVISION_CODE
        assert loaded["params"] == {"start": 0, "stop": 200}
        # Fresh scratch cwd, not the repo checkout.
        assert "arxmcp-cas-" in str(captured["kwargs"]["cwd"])

    def test_pythonpath_junk_does_not_reach_child(self, monkeypatch, tmp_path):
        """Functional -I check: a poisoned PYTHONPATH with a fake sympy
        module must be invisible to the isolated child."""
        evil = tmp_path / "sympy"
        evil.mkdir()
        (evil / "__init__.py").write_text(
            "raise RuntimeError('poisoned import')", encoding="utf-8"
        )
        monkeypatch.setenv("PYTHONPATH", str(tmp_path))
        code = (
            "def find_counterexample():\n"
            "    import sys\n"
            "    return [p for p in sys.path if 'poisoned' in p]\n"
        )
        env = run_cas_check(_spec(name="iso", code=code, params={}), enabled=True)
        assert env["status"] == "ok"
        assert env["witness"] == []


class TestSpecValidation:
    def test_empty_code_rejected(self):
        with pytest.raises(ValueError):
            CasCheckSpec(name="x", code="")

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError):
            CasCheckSpec(name="", code="pass")

    def test_unserializable_params_rejected(self):
        with pytest.raises(ValueError, match="JSON-serializable"):
            CasCheckSpec(name="x", code="pass", params={"bad": {1, 2}})

    @pytest.mark.parametrize("timeout", [0, -1, 1e9])
    def test_timeout_bounds(self, timeout):
        with pytest.raises(ValueError):
            CasCheckSpec(name="x", code="pass", timeout_s=timeout)

    def test_oversize_code_rejected(self):
        with pytest.raises(ValueError, match="exceeds"):
            CasCheckSpec(name="x", code="#" * (sympy_runner.MAX_CODE_LEN + 1))


@pytest.mark.skipif(not _HAS_SYMPY, reason="sympy not importable in this venv")
class TestRealSympy:
    def test_sympy_isprime_finds_the_witness(self):
        """The actual SymPy engine path (sympy ships transitively with
        torch in this venv; functional probe keeps the test honest)."""
        code = textwrap.dedent(
            """\
            def find_counterexample(start, stop):
                import sympy
                for n in range(start, stop):
                    if not sympy.isprime(n * n + n + 41):
                        return {"n": n}
                return None
            """
        )
        env = run_cas_check(
            CasCheckSpec(
                name="sympy-n2n41",
                code=code,
                params={"start": 0, "stop": 100},
                timeout_s=60.0,
            ),
            enabled=True,
        )
        assert env["status"] == "ok", env
        assert env["witness"] == {"n": 40}
