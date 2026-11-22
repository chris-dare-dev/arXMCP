"""Re-export of ``tests/test_id_canon.py`` at this path.

The test suite for ``canonicalize_turn`` lives at
``tests/test_id_canon.py`` (``pyproject.toml`` pins
``testpaths = ["tests"]``). Running
``pytest src/arxmcp/server/orchestrator/test_id_canon.py`` collects the same
test classes, re-exported below.
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
