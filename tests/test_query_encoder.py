"""Unit tests for the singleflight query encoder (E03_S03).

Coverage map:
  Acceptance criterion -> test class
  ──────────────────────────────────────────────────────────────────────
  10 concurrent encode_query calls → exactly 1 forward pass
                                       -> TestSingleflight
  Each waiter receives the same (or byte-identical) array
                                       -> TestSingleflight
  100ms dedup window: a call at t > 100ms past completion is a fresh request
                                       -> TestEvictionWindow
  Module docstring includes the GIL release sentence
                                       -> TestModuleContract
  BGE_M3_COMMIT_SHA imported, not redefined
                                       -> TestSingleSourceOfTruth
  Integration test: cosine similarity ≥ 0.9999 (env-gated)
                                       -> TestRealModelIntegration

The actual BGE-M3 model is mocked everywhere except the env-gated
``TestRealModelIntegration``, mirroring the precedent set by
``tests/test_embedder.py:TestVectorContract``. The 10-concurrent test
asserts the mock's call count is exactly 1 — that's the brief's
primary AC.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

import server.query_encoder as qe_mod
from server.query_encoder import (
    BGE_M3_COMMIT_SHA,
    DEDUP_WINDOW_S,
    EMBEDDING_DIM,
    encode_query,
)

# ===========================================================================
# Test isolation fixture
# ===========================================================================


@pytest.fixture(autouse=True)
def _reset_singleflight_state():
    """Clear ``_inflight`` and ``SINGLEFLIGHT_DEDUP_COUNT`` per test.

    Without this, a prior test's ``call_later`` cleanup that fires
    after the test ended would race with the next test's setup, and
    the dedup counter would accumulate across tests masking off-by-one
    bugs.
    """
    qe_mod._reset_for_tests()
    yield
    qe_mod._reset_for_tests()


# ===========================================================================
# Helpers — fake tokenizer + fake model
# ===========================================================================


def _make_fake_loaders(distinct_per_call: bool = True):
    """Return (tokenizer, model, model_call_counter) for tests.

    The model is a callable that returns an object with
    ``last_hidden_state`` shaped (1, seq_len, EMBEDDING_DIM). The
    counter is a ``[int]`` list-as-mutable-int so tests can read it
    after the fact.
    """
    import torch

    counter = [0]

    class _FakeTokenizer:
        def __call__(self, texts, **kwargs):
            assert kwargs.get("padding") is True
            assert kwargs.get("truncation") is True
            assert kwargs.get("return_tensors") == "pt"
            batch = len(texts)
            return {
                "input_ids": torch.zeros(batch, 4, dtype=torch.long),
                "attention_mask": torch.ones(batch, 4, dtype=torch.long),
            }

    class _FakeOutput:
        def __init__(self, batch: int, seed: int):
            gen = torch.Generator().manual_seed(seed)
            # Shape: (batch, seq_len=4, hidden=EMBEDDING_DIM)
            self.last_hidden_state = torch.randn(
                batch, 4, EMBEDDING_DIM, generator=gen, dtype=torch.float32
            )

    class _FakeModel:
        def __call__(self, **kwargs):
            counter[0] += 1
            batch = kwargs["input_ids"].shape[0]
            # Distinct seed per call so successive forward passes
            # produce different vectors — useful for detecting
            # whether the singleflight actually deduped.
            seed = (1_000_000 * counter[0]) if distinct_per_call else 42
            return _FakeOutput(batch, seed)

    return _FakeTokenizer(), _FakeModel(), counter


# ===========================================================================
# TestModuleContract — the brief's literal docstring AC
# ===========================================================================


class TestModuleContract:
    def test_docstring_includes_gil_release_rationale(self):
        """AC: module docstring must carry the verbatim GIL sentence.

        Collapse all internal whitespace (including the docstring's
        line wrapping) so the sentence can be written across multiple
        source lines without breaking the substring match.
        """
        doc = qe_mod.__doc__ or ""
        doc_collapsed = " ".join(doc.split())
        # The brief gives the EXACT sentence required:
        required = (
            "BGE-M3 forward pass releases the GIL inside PyTorch's "
            "C++ backend; ThreadPoolExecutor is therefore safe for "
            "concurrent callers."
        )
        assert required in doc_collapsed, (
            "module docstring must contain the AC's GIL release sentence"
        )

    def test_dedup_window_is_100ms(self):
        # Brief: "Deduplication window is 100ms".
        assert DEDUP_WINDOW_S == 0.1

    def test_executor_is_single_worker(self):
        # Brief: "ThreadPoolExecutor with 1 worker".
        assert qe_mod._executor._max_workers == 1


# ===========================================================================
# TestSingleSourceOfTruth — closes the BGE_M3_COMMIT_SHA redefinition vector
# ===========================================================================


class TestSingleSourceOfTruth:
    def test_bge_m3_commit_sha_imported_from_embedder(self):
        # The constant exposed by server.query_encoder must be the SAME
        # object as the one defined in ingest.embedder. Object identity
        # (``is``) catches a future regression where someone redefines
        # the literal here.
        from ingest.embedder import BGE_M3_COMMIT_SHA as embedder_sha

        assert BGE_M3_COMMIT_SHA is embedder_sha

    def test_sha_literal_appears_exactly_once_across_ingest_and_server(self):
        """D14: scan ingest/ + server/ for the 40-char SHA literal.

        Mirrors ``tests/test_chunker_ids.py::TestSingleVersionDefinition``
        for ``BGE_M3_COMMIT_SHA``. Closes the redefinition door at
        lint time, not just at code-review time.
        """
        repo_root = Path(__file__).parent.parent
        # Match ANY 40-hex string assigned with quotes in source.
        sha_pattern = re.compile(r'"' + BGE_M3_COMMIT_SHA + r'"')
        hits: list[Path] = []
        for src_dir in ("ingest", "server"):
            for py_file in (repo_root / src_dir).rglob("*.py"):
                text = py_file.read_text(encoding="utf-8")
                if sha_pattern.search(text):
                    hits.append(py_file)
        assert len(hits) == 1, (
            f"BGE_M3_COMMIT_SHA literal must appear exactly once across "
            f"ingest/ + server/; found in: {hits}"
        )
        assert hits[0].name == "embedder.py"


# ===========================================================================
# TestSingleflight — the brief's central AC: 10 concurrent → 1 forward pass
# ===========================================================================


class TestSingleflight:
    def test_ten_concurrent_same_query_one_forward_pass(self):
        """AC: 10 concurrent encode_query("test query") → 1 forward pass."""
        tok, model, counter = _make_fake_loaders()

        async def _run() -> list[np.ndarray]:
            with (
                patch("server.query_encoder._get_tokenizer", return_value=tok),
                patch("server.query_encoder._get_model", return_value=model),
            ):
                # gather 10 concurrent calls.
                return await asyncio.gather(
                    *(encode_query("test query") for _ in range(10))
                )

        results = asyncio.run(_run())
        # Exactly ONE forward pass.
        assert counter[0] == 1, (
            f"expected exactly 1 BGE-M3 forward pass, got {counter[0]}"
        )
        # All 10 callers got the same vector value.
        first = results[0]
        for r in results[1:]:
            assert np.array_equal(r, first)
        # And the dedup counter saw 9 coalesced calls (10 callers, 1
        # spawned the encode, 9 awaited the same future).
        assert qe_mod.SINGLEFLIGHT_DEDUP_COUNT == 9

    def test_concurrent_callers_get_independent_array_objects(self):
        """D12: each waiter gets a .copy() so mutation by one does not
        leak to others."""
        tok, model, _ = _make_fake_loaders()

        async def _run():
            with (
                patch("server.query_encoder._get_tokenizer", return_value=tok),
                patch("server.query_encoder._get_model", return_value=model),
            ):
                a, b = await asyncio.gather(
                    encode_query("same"), encode_query("same")
                )
            return a, b

        a, b = asyncio.run(_run())
        # Same value...
        assert np.array_equal(a, b)
        # ...but distinct objects (otherwise mutation would leak).
        assert a is not b
        # Mutation isolation: scribble on one, the other stays clean.
        a[0] = 999.0
        assert b[0] != 999.0

    def test_returned_vector_shape_and_dtype(self):
        tok, model, _ = _make_fake_loaders()

        async def _run():
            with (
                patch("server.query_encoder._get_tokenizer", return_value=tok),
                patch("server.query_encoder._get_model", return_value=model),
            ):
                return await encode_query("foo")

        vec = asyncio.run(_run())
        assert vec.shape == (EMBEDDING_DIM,)
        assert vec.dtype == np.float32

    def test_returned_vector_is_l2_normalized(self):
        # Even though the fake model produces random hidden states, the
        # production code path applies F.normalize so the returned
        # vector should always have ||v||₂ ≈ 1.
        tok, model, _ = _make_fake_loaders()

        async def _run():
            with (
                patch("server.query_encoder._get_tokenizer", return_value=tok),
                patch("server.query_encoder._get_model", return_value=model),
            ):
                return await encode_query("normalized?")

        vec = asyncio.run(_run())
        norm = float(np.linalg.norm(vec))
        assert abs(norm - 1.0) < 1e-5

    def test_distinct_queries_get_distinct_forward_passes(self):
        # Singleflight only coalesces SAME query — different queries
        # must each trigger a forward pass.
        tok, model, counter = _make_fake_loaders()

        async def _run():
            with (
                patch("server.query_encoder._get_tokenizer", return_value=tok),
                patch("server.query_encoder._get_model", return_value=model),
            ):
                return await asyncio.gather(
                    encode_query("query A"),
                    encode_query("query B"),
                    encode_query("query C"),
                )

        asyncio.run(_run())
        assert counter[0] == 3
        assert qe_mod.SINGLEFLIGHT_DEDUP_COUNT == 0


# ===========================================================================
# TestCanonicalization — D4 normalization rules
# ===========================================================================


class TestCanonicalization:
    def test_strip_only_whitespace(self):
        # query.strip() handles leading/trailing whitespace; internal
        # whitespace is preserved (per the 07-note Tier-1 cache rule).
        assert qe_mod._canonicalize("  hello world  ") == "hello world"
        # Internal double-space NOT collapsed.
        assert qe_mod._canonicalize("hello  world") == "hello  world"

    def test_does_not_lowercase(self):
        # 07-note rule: "do NOT lowercase".
        assert qe_mod._canonicalize("Theorem") == "Theorem"
        assert qe_mod._canonicalize("Theorem") != "theorem"

    def test_does_not_strip_punctuation(self):
        assert qe_mod._canonicalize("\\'etale") == "\\'etale"

    def test_applies_nfc(self):
        # 'café' in NFD form (cafe + combining acute) -> NFC precomposed.
        nfd = "café"  # may already be NFC depending on source — see assertion
        nfc = "café"
        # Verify the helper produces NFC regardless of input form.
        assert qe_mod._canonicalize(nfd) == nfc

    def test_strip_then_nfc_singleflight_key_match(self):
        # Two callers sending the same query with different surrounding
        # whitespace must hit the same singleflight key.
        a = qe_mod._canonicalize("  hello  ")
        b = qe_mod._canonicalize("hello")
        assert a == b


# ===========================================================================
# TestEvictionWindow — D8 (completion-based 100ms eviction)
# ===========================================================================


class TestEvictionWindow:
    def test_in_flight_dedup_during_encode(self):
        """D9: any call arriving while encode is in flight shares the
        future, regardless of timing relative to first arrival."""
        # Use a slow encode (await sleep inside the executor stand-in)
        # so we can observe in-flight dedup. We monkey-patch
        # _encode_query_sync directly.
        counter = [0]

        def _slow_encode(text: str) -> np.ndarray:
            counter[0] += 1
            import time

            time.sleep(0.05)  # 50ms — well inside the in-flight window
            v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
            v[0] = 1.0
            return v

        async def _run():
            with patch(
                "server.query_encoder._encode_query_sync",
                side_effect=_slow_encode,
            ):
                # Two callers, second issued ~10ms after first.
                t1 = asyncio.create_task(encode_query("q"))
                await asyncio.sleep(0.01)
                t2 = asyncio.create_task(encode_query("q"))
                await asyncio.gather(t1, t2)

        asyncio.run(_run())
        assert counter[0] == 1
        assert qe_mod.SINGLEFLIGHT_DEDUP_COUNT == 1

    def test_call_after_eviction_window_is_fresh_request(self):
        """AC: a call arriving 101ms after the first (read as: 101ms
        after completion per D8) is treated as a new request."""
        counter = [0]

        def _fast_encode(text: str) -> np.ndarray:
            counter[0] += 1
            v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
            v[0] = float(counter[0])  # vary so we can tell calls apart
            return v

        async def _run():
            with patch(
                "server.query_encoder._encode_query_sync",
                side_effect=_fast_encode,
            ):
                v1 = await encode_query("q")
                # Sleep > DEDUP_WINDOW_S past completion to fall outside
                # the window. The cleanup callback fires at completion +
                # DEDUP_WINDOW_S; sleep ~0.15s to be comfortably past.
                await asyncio.sleep(DEDUP_WINDOW_S + 0.05)
                v2 = await encode_query("q")
            return v1, v2

        v1, v2 = asyncio.run(_run())
        # Two distinct forward passes → counter went 1 → 2.
        assert counter[0] == 2
        # And the fake encoded different markers per call.
        assert v1[0] == 1.0
        assert v2[0] == 2.0
        # Singleflight DID NOT coalesce — both calls were on the slow path.
        assert qe_mod.SINGLEFLIGHT_DEDUP_COUNT == 0

    def test_call_within_window_after_completion_dedups(self):
        """D8: a call arriving inside DEDUP_WINDOW_S after completion
        gets the cached result (no new forward pass)."""
        counter = [0]

        def _fast_encode(text: str) -> np.ndarray:
            counter[0] += 1
            return np.ones(EMBEDDING_DIM, dtype=np.float32) / np.sqrt(
                EMBEDDING_DIM
            )

        async def _run():
            with patch(
                "server.query_encoder._encode_query_sync",
                side_effect=_fast_encode,
            ):
                await encode_query("q")
                # Tiny gap — well inside the 100ms post-completion window.
                await asyncio.sleep(0.02)
                await encode_query("q")

        asyncio.run(_run())
        assert counter[0] == 1
        assert qe_mod.SINGLEFLIGHT_DEDUP_COUNT == 1


# ===========================================================================
# TestErrorPath — D10: errors evict immediately, no 100ms delay
# ===========================================================================


class TestErrorPath:
    def test_encode_raises_propagates_to_caller(self):
        def _raising_encode(text: str) -> np.ndarray:
            raise RuntimeError("simulated model failure")

        async def _run():
            with patch(
                "server.query_encoder._encode_query_sync",
                side_effect=_raising_encode,
            ), pytest.raises(RuntimeError, match="simulated"):
                await encode_query("q")

        asyncio.run(_run())

    def test_failed_call_evicted_immediately_so_retry_is_fresh(self):
        """D10: error path skips the 100ms post-completion delay so a
        retry does not inherit the stale exception future."""
        attempts = [0]

        def _flaky_encode(text: str) -> np.ndarray:
            attempts[0] += 1
            if attempts[0] == 1:
                raise RuntimeError("first attempt fails")
            v = np.zeros(EMBEDDING_DIM, dtype=np.float32)
            v[0] = 1.0
            return v

        async def _run():
            with patch(
                "server.query_encoder._encode_query_sync",
                side_effect=_flaky_encode,
            ):
                with pytest.raises(RuntimeError):
                    await encode_query("q")
                # Immediately retry — must NOT see the cached failure.
                v = await encode_query("q")
            return v

        v = asyncio.run(_run())
        assert v[0] == 1.0
        assert attempts[0] == 2

    def test_concurrent_waiters_see_same_exception(self):
        # Two concurrent callers should both see the same exception
        # raised on the in-flight future.
        attempts = [0]

        def _raising_encode(text: str) -> np.ndarray:
            attempts[0] += 1
            raise ValueError("boom")

        async def _run():
            with patch(
                "server.query_encoder._encode_query_sync",
                side_effect=_raising_encode,
            ):
                t1 = asyncio.create_task(encode_query("q"))
                t2 = asyncio.create_task(encode_query("q"))
                results = await asyncio.gather(
                    t1, t2, return_exceptions=True
                )
            return results

        results = asyncio.run(_run())
        # Both callers raise; the encode should have happened only once
        # (singleflight coalesced).
        assert attempts[0] == 1
        for r in results:
            assert isinstance(r, ValueError)
            assert "boom" in str(r)


# ===========================================================================
# TestThreat6 — verify the encoder module honors model pinning indirectly
# ===========================================================================


class TestThreat6:
    def test_encoder_uses_embedder_lazy_loaders(self):
        """The encoder must import _get_model / _get_tokenizer from
        ingest.embedder rather than redefining them, so Threat 6
        revision-pinning enforcement (regression-tested in
        test_embedder.py) automatically covers the query path too."""
        import ingest.embedder as embedder_mod

        assert qe_mod._get_model is embedder_mod._get_model
        assert qe_mod._get_tokenizer is embedder_mod._get_tokenizer


# ===========================================================================
# TestRealModelIntegration — env-gated, downloads the actual BGE-M3 weights
# ===========================================================================


@pytest.mark.skipif(
    os.environ.get("ARXMCP_RUN_REAL_BGE_M3") != "1",
    reason=(
        "skipped by default; set ARXMCP_RUN_REAL_BGE_M3=1 to run the "
        "real-model integration test (~2.3 GB download on first run)"
    ),
)
class TestRealModelIntegration:
    def test_two_calls_same_query_cosine_ge_9999(self):
        """AC: two calls with the same query string return vectors with
        cosine similarity ≥ 0.9999 (floating-point identical up to
        rounding under different batch sizes)."""

        async def _run():
            v1 = await encode_query("Theorem 1: every group has identity.")
            # Sleep past eviction window so the second call goes through
            # a fresh forward pass — that's what we want to compare.
            await asyncio.sleep(DEDUP_WINDOW_S + 0.05)
            v2 = await encode_query("Theorem 1: every group has identity.")
            return v1, v2

        v1, v2 = asyncio.run(_run())
        # cosine = dot / (||v1|| ||v2||); both are L2-normalized so dot
        # is the cosine directly.
        cosine = float(np.dot(v1, v2))
        assert cosine >= 0.9999, f"cosine = {cosine!r}; expected ≥ 0.9999"
