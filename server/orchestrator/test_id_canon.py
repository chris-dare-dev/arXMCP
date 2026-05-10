"""Re-export stub for the brief's literal AC path (E08_S04).

The brief's AC #6 reads: ``pytest server/orchestrator/test_id_canon.py``
must pass. Project convention places test files under ``tests/``
(``pyproject.toml`` pins ``testpaths = ["tests"]``). The full test
suite for ``canonicalize_turn`` lives at
``tests/test_id_canon.py``.

This stub satisfies the literal AC: running
``pytest server/orchestrator/test_id_canon.py`` collects the same
test classes (re-exported below) and runs them. The deviation is
documented in ``docs/orchestrator-rules.md``.

F3 fix from the E08_S04 critique: pre-fix the literal AC was
unsatisfied because the file did not exist at this path. The
stub closes the AC without weakening project conventions
(``testpaths = ["tests"]`` stays unchanged; CI's plain ``pytest``
still picks up the canonical file at ``tests/test_id_canon.py``).
"""

from __future__ import annotations

from tests.test_id_canon import (  # noqa: F401
    TestCanonicalForm,
    TestDeepCopyDiscipline,
    TestFourAgentFanoutExample,
    TestIdempotency,
    TestPairingInvariant,
    TestRobustness,
)
