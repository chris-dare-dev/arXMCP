"""``cap_result_list`` drops the lowest-ranked rows until the payload fits."""

from __future__ import annotations

import json
import random
from types import SimpleNamespace

import pytest

from server import tools
from server.tools import cap_result_list, reset_resources_for_tests, set_resources


def _wire_size(payload: dict) -> int:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return len(text.encode("utf-8")) * tools._WIRE_OVERHEAD_FACTOR


def _rows_that_fit(payload: dict, cap: int) -> int:
    """Reference answer: the most leading rows whose payload fits."""
    rows = payload["results"]
    for n in range(len(rows), -1, -1):
        if _wire_size({**payload, "results": rows[:n]}) <= cap:
            return n
    return 0


@pytest.fixture
def byte_cap():
    def install(cap: int) -> None:
        set_resources(SimpleNamespace(config=SimpleNamespace(result_byte_cap=cap)))

    yield install
    reset_resources_for_tests()


def _payload(seed: int, n_rows: int) -> dict:
    rng = random.Random(seed)
    alphabet = "abcxyz ∂∑ℤ→é\"\\"
    rows = [
        {
            "chunk_id": f"2401.{i:05d}#c{i}",
            "score": rng.random(),
            "snippet": "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 300))),
            "meta": {"kind": rng.choice(["theorem", "proof"]), "n": [i, None, True]},
        }
        for i in range(n_rows)
    ]
    return {"query": "zeta ∑", "results": rows, "retrieval_mode": "hybrid"}


@pytest.mark.parametrize("seed", range(5))
def test_keeps_exactly_the_rows_that_fit(byte_cap, seed):
    payload = _payload(seed, 40)
    full = _wire_size(payload)
    for cap in sorted({full // 7, full // 3, full // 2, full - 2, 50, 1}):
        byte_cap(cap)
        out, blocks = cap_result_list(payload, "results")

        assert len(out["results"]) == _rows_that_fit(payload, cap)
        assert out["results"] == payload["results"][: len(out["results"])]
        assert out["body_truncated"] is True
        assert blocks == []


def test_under_cap_payload_is_returned_untouched(byte_cap):
    payload = _payload(0, 5)
    byte_cap(_wire_size(payload))

    out, _ = cap_result_list(payload, "results")

    assert out is payload


def test_caller_payload_is_not_mutated(byte_cap):
    payload = _payload(1, 20)
    before = json.dumps(payload, sort_keys=True)
    byte_cap(_wire_size(payload) // 4)

    cap_result_list(payload, "results")

    assert json.dumps(payload, sort_keys=True) == before


def test_serialization_work_is_linear_in_payload_size(byte_cap, monkeypatch):
    """Trimming must not re-serialize the whole payload per dropped row,
    which costs bytes quadratic in the row count."""
    payload = _payload(2, 200)
    payload_chars = len(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    byte_cap(200)
    serialized_chars = 0
    real_dumps = json.dumps

    def counting_dumps(*args, **kwargs):
        nonlocal serialized_chars
        text = real_dumps(*args, **kwargs)
        serialized_chars += len(text)
        return text

    monkeypatch.setattr(tools.json, "dumps", counting_dumps)
    out, _ = cap_result_list(payload, "results")

    assert out["results"] == []
    assert serialized_chars <= 5 * payload_chars
