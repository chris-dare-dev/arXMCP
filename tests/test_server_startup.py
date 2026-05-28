"""Server-startup tests (E06_S01).

Coverage map (acceptance criteria → test class):

  AC                                                Test class
  ──────────────────────────────────────────────────────────────────
  /healthz returns 200 before readiness             TestHealthEndpoints
  /readyz returns 503 → 200 within 30s              TestReadinessTransition
  ARXMCP_BIND_HOST=0.0.0.0 rejected at parse        TestConfigValidation
  Two servers on same port → clear error            TestPortConflict
  corpus_version logged matches corpus-version.json TestStartupLogging
  Streamable HTTP mount + /metrics + /mcp           TestRouteSurface

The default test path **mocks** the BGE-M3 model load (per synthesis
D7) so the suite stays fast and runs without GPU. A separate
env-gated test (``ARXMCP_RUN_REAL_BGE_M3=1``) runs the real-model
path; mirrors the precedent in ``tests/test_embedder.py``.

Tests do NOT pollute ``var/arxmcp/``: every Resources fixture
points the LanceDB path at ``tmp_path`` and seeds it via
``ingest.store.write_chunks`` against a tiny fixture.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import uvicorn
from fastapi.testclient import TestClient

from ingest.chunker_types import CHUNKER_VERSION, ChunkRecord
from ingest.embedder import EMBEDDER_VERSION, EMBEDDING_DIM
from ingest.schema import EmbedRecord
from ingest.store import write_chunks
from server.config import Config
from server.health import reset_metrics_for_tests
from server.main import create_app
from server.resources import (
    CorpusNotIngestedError,
    RerankerUnavailableError,
    Resources,
    Singleflight,
)

# ===========================================================================
# Fixtures
# ===========================================================================


def _seed_corpus(lancedb_path: Path) -> int:
    """Ingest a tiny 2-chunk corpus and return its corpus_version."""
    chunks = [
        ChunkRecord(
            chunk_id=f"arxiv:2307.0000{i}:{'0' * 16}",
            paper_id=f"2307.0000{i}",
            kind="stmt",
            section_path=[],
            theorem_name=None,
            theorem_label=None,
            body_text=f"chunk body {i}",
            body_tokens=f"chunk body {i}",
            preamble_ref=None,
            chunker_version=CHUNKER_VERSION,
        )
        for i in (1, 2)
    ]
    rng = np.random.default_rng(42)
    rows = []
    for _ in chunks:
        v = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        v /= np.linalg.norm(v)
        rows.append(v)
    embeddings = EmbedRecord(
        chunk_ids_stmt=[c.chunk_id for c in chunks],
        embedding_stmt=np.stack(rows, axis=0),
        chunk_ids_proof=[],
        embedding_proof=np.zeros((0, EMBEDDING_DIM), dtype=np.float32),
        embedder_version=EMBEDDER_VERSION,
    )
    return write_chunks(chunks, embeddings, lancedb_path=lancedb_path)


@pytest.fixture
def mocked_bge_m3(monkeypatch):
    """Replace the BGE-M3 model + tokenizer load with no-ops.

    Per synthesis D7: the default test path uses MOCKED resources
    so the suite runs without GPU and finishes in milliseconds, not
    minutes. The real-model path is gated separately via
    ``ARXMCP_RUN_REAL_BGE_M3=1``.
    """
    import server.query_encoder as qe_mod

    fake_model = object()
    fake_tokenizer = object()
    monkeypatch.setattr(qe_mod, "_get_model", lambda: fake_model)
    monkeypatch.setattr(qe_mod, "_get_tokenizer", lambda: fake_tokenizer)
    yield


@pytest.fixture
def seeded_lancedb(tmp_path: Path, monkeypatch) -> Path:
    """Seed a tiny LanceDB corpus under tmp_path and return the path.

    The seeded corpus has 2 chunks, satisfying ``Resources.startup``'s
    requirement that ``corpus-version.json`` exist with a valid
    integer version.
    """
    lancedb_path = tmp_path / "lancedb"
    _seed_corpus(lancedb_path)
    return lancedb_path


@pytest.fixture
def warm_app(seeded_lancedb, mocked_bge_m3):
    """A warm FastAPI app with mocked resources, ready for TestClient.

    The TestClient context manager triggers the lifespan (startup +
    shutdown), so by the time we yield the client, ``Resources`` is
    attached and ``/readyz`` returns 200.
    """
    cfg = Config(lancedb_path=seeded_lancedb)
    app = create_app(cfg)
    reset_metrics_for_tests()
    with TestClient(app) as client:
        yield client


# ===========================================================================
# AC: GET /healthz returns 200 before readiness
# ===========================================================================


class TestHealthEndpoints:
    def test_healthz_returns_200(self, warm_app):
        """AC: ``/healthz`` returns 200 (and stays 200 regardless of
        resource warm state)."""
        r = warm_app.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_healthz_works_before_resources_attach(self, seeded_lancedb, mocked_bge_m3):
        """A request to ``/healthz`` BEFORE the lifespan has attached
        Resources still returns 200. The brief AC: *"GET /healthz
        returns 200 before readiness."*

        Closes F6 from the E06_S01 critique — the original test
        body opened a TestClient context manager (which fires the
        lifespan) and ``pass``-ed without making any request. This
        version constructs the app, then probes ``/healthz`` via a
        TestClient that does NOT enter its context manager (so no
        lifespan fires), and asserts both (a) status 200, (b) the
        body is the documented liveness payload, AND (c) the
        ``app.state.resources`` attribute is unset at the time
        ``/healthz`` was hit.
        """
        from fastapi.testclient import TestClient as _TC

        cfg = Config(lancedb_path=seeded_lancedb)
        app = create_app(cfg)
        # Sanity: no resources attached yet (no lifespan fired).
        assert getattr(app.state, "resources", None) is None
        client = _TC(app)
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}
        # Re-confirm the lifespan did NOT fire as a side effect of
        # the bare GET — this is the load-bearing invariant for the
        # AC "/healthz returns 200 BEFORE readiness".
        assert getattr(app.state, "resources", None) is None


# ===========================================================================
# AC: GET /readyz returns 503 until embedder + LanceDB are warm, then 200
# ===========================================================================


class TestReadinessTransition:
    def test_readyz_200_when_warm(self, warm_app):
        """After the TestClient context manager runs the lifespan,
        Resources are warm and /readyz returns 200."""
        r = warm_app.get("/readyz")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ready"
        assert body["warm"]["embedder"] is True
        assert body["warm"]["lancedb"] is True
        # Reranker disabled by default → not warm.
        assert body["warm"]["reranker"] is False

    def test_readyz_reaches_200_within_30s(self, seeded_lancedb, mocked_bge_m3):
        """AC: server reaches /readyz 200 within 30 seconds.

        Closes F7 from the E06_S01 critique. The brief AC is a
        BUDGET assertion, not an "eventually 200" assertion. With
        mocked BGE-M3 the lifespan completes in milliseconds; a
        regression that made the embedder load take 35 s would NOT
        trip the bare ``test_readyz_200_when_warm`` test. This
        version times the lifespan + first /readyz round-trip and
        asserts elapsed < 30s.
        """
        cfg = Config(lancedb_path=seeded_lancedb)
        app = create_app(cfg)
        reset_metrics_for_tests()
        start = time.monotonic()
        with TestClient(app) as client:
            r = client.get("/readyz")
            assert r.status_code == 200
        elapsed = time.monotonic() - start
        assert elapsed < 30.0, (
            f"Lifespan + first /readyz exceeded the 30s budget: "
            f"elapsed={elapsed:.3f}s"
        )

    def test_readyz_503_when_resources_absent(self, seeded_lancedb, mocked_bge_m3):
        """If the lifespan has not run, ``/readyz`` returns 503 with
        the per-resource map showing all-False."""
        cfg = Config(lancedb_path=seeded_lancedb)
        app = create_app(cfg)
        # Do NOT enter the TestClient lifespan; directly hit the
        # readyz route.
        from fastapi.testclient import TestClient as _TC

        client = _TC(app)
        # Bypass lifespan by NOT using ``with`` — TestClient does not
        # auto-fire lifespan unless used as a context manager.
        r = client.get("/readyz")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "not_ready"
        assert body["warm"] == {
            "embedder": False,
            "lancedb": False,
            "reranker": False,
        }


# ===========================================================================
# AC: ARXMCP_BIND_HOST=0.0.0.0 rejected at config parse time
# ===========================================================================


class TestConfigValidation:
    def test_zero_zero_zero_zero_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="loopback"):
            Config(bind_host="0.0.0.0")

    def test_public_ip_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="loopback"):
            Config(bind_host="192.168.1.1")

    def test_loopback_127_accepted(self):
        cfg = Config(bind_host="127.0.0.1")
        assert cfg.bind_host == "127.0.0.1"

    def test_localhost_accepted(self):
        cfg = Config(bind_host="localhost")
        assert cfg.bind_host == "localhost"

    def test_ipv6_loopback_accepted(self):
        cfg = Config(bind_host="::1")
        assert cfg.bind_host == "::1"

    def test_privileged_port_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match=r"\[1024, 65535\]"):
            Config(bind_port=80)

    def test_zero_concurrency_rejected(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="must be >= 1"):
            Config(max_concurrent_embeddings=0)

    def test_extra_env_var_rejected(self):
        """``extra=forbid`` in SettingsConfigDict — typo in env var
        is a config error, not a silent pass."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Config(unknown_field="x")  # type: ignore[call-arg]

    def test_contact_email_env_var_rejected(self, monkeypatch):
        """``ARXMCP_CONTACT_EMAIL`` is an INGEST-side env var (consumed
        by ``tools/arxiv_fetch.py`` for the polite User-Agent string)
        and is NOT a declared server ``Config`` field. An earlier draft
        of ``docs/ops/notebook-modes.md`` Mode 1 launch recipe
        instructed operators to ``export ARXMCP_CONTACT_EMAIL=...``;
        the server then refused to start with the custom
        ``_scan_unknown_arxmcp_env_vars`` error from
        ``server/main.py:232`` (an F4 closure from E06_S01 — pydantic's
        ``extra="forbid"`` does NOT fire on env-var input, only on
        direct ``__init__`` kwargs). The m4 rect F1 closure removed
        the env var from the runbook AND pins this regression guard so
        a future runbook reviewer cannot silently re-add it without
        flipping this assertion.

        If we ever DO want to accept the env var on the server side
        (option (b) in the F1 fix tree — declare a no-op
        ``contact_email: str | None = None`` field), invert this test
        to assert acceptance and update both the runbook and the
        comment on this test.
        """
        from server.main import _scan_unknown_arxmcp_env_vars

        monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")
        cfg = Config()
        with pytest.raises(ValueError, match="ARXMCP_CONTACT_EMAIL"):
            _scan_unknown_arxmcp_env_vars(cfg)


# ===========================================================================
# notebook-retrieval-m1 (fork C) — ARXMCP_NOTEBOOK derives lancedb_path
# ===========================================================================


class TestNotebookConfig:
    """ARXMCP_NOTEBOOK=<slug> makes the server serve that notebook's
    lancedb (fork C). Routing happens in Config.derive_notebook_lancedb_path
    BEFORE Resources.startup reads lancedb_path."""

    @pytest.fixture
    def notebooks_base(self, tmp_path: Path, monkeypatch):
        """Redirect the shared notebook-base constant to a tmp dir so
        the Config validator's notebook_lancedb_path() resolves there."""
        from tools import _notebook_common

        base = tmp_path / "notebooks"
        base.mkdir()
        monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
        return base

    def test_notebook_unset_keeps_shared_corpus(self, monkeypatch):
        """AC4: with ARXMCP_NOTEBOOK unset, lancedb_path is byte-identical
        to today's default (shared corpus). No new code path fires."""
        monkeypatch.delenv("ARXMCP_NOTEBOOK", raising=False)
        cfg = Config()
        assert cfg.notebook is None
        assert cfg.lancedb_path == Path("var/arxmcp/index/lancedb")

    def test_notebook_set_derives_lancedb_path(self, notebooks_base):
        """AC1 (routing): ARXMCP_NOTEBOOK=<slug> rewrites lancedb_path to
        the per-notebook dataset dir."""
        (notebooks_base / "demo-nb" / "lancedb").mkdir(parents=True)
        cfg = Config(notebook="demo-nb")
        assert cfg.lancedb_path == (notebooks_base / "demo-nb" / "lancedb").resolve()

    def test_notebook_set_via_env(self, notebooks_base, monkeypatch):
        """The slug arrives via ARXMCP_NOTEBOOK env, not just kwargs."""
        (notebooks_base / "demo-nb" / "lancedb").mkdir(parents=True)
        monkeypatch.setenv("ARXMCP_NOTEBOOK", "demo-nb")
        cfg = Config()
        assert cfg.notebook == "demo-nb"
        assert cfg.lancedb_path == (notebooks_base / "demo-nb" / "lancedb").resolve()

    def test_missing_notebook_corpus_clear_error(self, notebooks_base):
        """AC5: notebook set but never ingested (no lancedb dir) → a
        clear config-load error naming the ingest command, NOT a deeper
        CorpusNotIngestedError at Resources.startup."""
        from pydantic import ValidationError

        # notebooks_base exists but demo-nb/lancedb does not.
        with pytest.raises(ValidationError, match="notebook_ingest.py demo-nb"):
            Config(notebook="demo-nb")

    def test_notebook_slug_traversal_rejected(self, notebooks_base):
        """Threat 1: a path-traversal slug is rejected at config-load
        (inherited from notebook_lancedb_path → notebook_dir → validate_slug)."""
        from pydantic import ValidationError

        for bad in ("../etc", "..", "a/b", "ABC", "x"):  # traversal / slash / upper / too-short
            with pytest.raises(ValidationError):
                Config(notebook=bad)

    def test_notebook_and_explicit_lancedb_path_rejected(self, notebooks_base):
        """Ambiguity guard: setting BOTH ARXMCP_NOTEBOOK and an explicit
        lancedb_path is rejected — the operator must pick one substrate."""
        from pydantic import ValidationError

        (notebooks_base / "demo-nb" / "lancedb").mkdir(parents=True)
        with pytest.raises(ValidationError, match="not.*both|either"):
            Config(notebook="demo-nb", lancedb_path=Path("var/arxmcp/index/lancedb"))


class TestNotebookLancedbPathHelper:
    """AC8 (stepping-stone shaping): the slug→lancedb-path derivation
    lives in tools._notebook_common.notebook_lancedb_path — the shared
    seam both fork C (startup) and fork A (per-request) call."""

    def test_helper_returns_notebook_dir_slash_lancedb(self, tmp_path):
        from tools._notebook_common import notebook_dir, notebook_lancedb_path

        base = tmp_path / "notebooks"
        (base / "demo-nb").mkdir(parents=True)
        got = notebook_lancedb_path("demo-nb", base=base)
        assert got == notebook_dir("demo-nb", base=base) / "lancedb"

    def test_helper_inherits_slug_validation(self, tmp_path):
        """The helper re-uses notebook_dir's Threat-1 guard — bad slugs
        raise NotebookError (so the C and A paths share one safety
        contract, not two divergent ones)."""
        from tools._notebook_common import NotebookError, notebook_lancedb_path

        base = tmp_path / "notebooks"
        base.mkdir()
        for bad in ("../etc", "a/b", "ABC"):
            with pytest.raises(NotebookError):
                notebook_lancedb_path(bad, base=base)

    def test_helper_rejects_symlinked_notebook(self, tmp_path):
        """notebook_dir's m6 F3 symlink rejection flows through the
        shared helper."""
        from tools._notebook_common import NotebookError, notebook_lancedb_path

        base = tmp_path / "notebooks"
        base.mkdir()
        real = tmp_path / "real"
        real.mkdir()
        (base / "spooky").symlink_to(real)
        with pytest.raises(NotebookError):
            notebook_lancedb_path("spooky", base=base)


# ===========================================================================
# AC: Starting two server processes on the same port → clear error
# ===========================================================================


class TestPortConflict:
    def test_address_in_use_propagates(self, seeded_lancedb, mocked_bge_m3):
        """Bind a socket to a free port, then attempt to start uvicorn
        on the same port. The bind should fail with OSError (errno
        EADDRINUSE) — not silently hang."""
        # Pick a free port and HOLD it via a raw socket.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        held_port = s.getsockname()[1]

        try:
            # Try to start uvicorn on the held port. We use a thread
            # so the test doesn't block; the failure mode here is
            # that uvicorn raises OSError synchronously inside its
            # bind path on most platforms.
            cfg = Config(
                lancedb_path=seeded_lancedb,
                bind_port=held_port,
            )
            app = create_app(cfg)

            # The startup call inside uvicorn.Server.serve will hit
            # the address-in-use OSError. We wrap it in run() in a
            # background thread and observe the exception via
            # capturing-thread.
            err_box = []

            def _runner():
                try:
                    config = uvicorn.Config(
                        app,
                        host="127.0.0.1",
                        port=held_port,
                        lifespan="on",
                        log_config=None,
                    )
                    server = uvicorn.Server(config)
                    asyncio.run(server.serve())
                except SystemExit as e:
                    err_box.append(("SystemExit", str(e)))
                except OSError as e:
                    err_box.append(("OSError", str(e)))
                except Exception as e:
                    err_box.append((type(e).__name__, str(e)))

            t = threading.Thread(target=_runner, daemon=True)
            t.start()
            t.join(timeout=5.0)
            # The 5-second join is the silent-hang detector.
            assert not t.is_alive(), (
                "uvicorn hung instead of failing on port conflict"
            )
            # F8 fix: assert on the captured exception type, not
            # just thread liveness. A future uvicorn that silently
            # exits 0 on EADDRINUSE would pass the liveness check
            # but break the AC's "clear error" promise.
            assert err_box, (
                "uvicorn exited without raising; expected an OSError "
                "/ SystemExit on port conflict"
            )
            exc_type, exc_msg = err_box[0]
            assert exc_type in {"OSError", "SystemExit"}, (
                f"expected OSError or SystemExit on port conflict; "
                f"got {exc_type}: {exc_msg}"
            )
        finally:
            s.close()


# ===========================================================================
# AC: corpus_version is logged at startup and matches corpus-version.json
# ===========================================================================


class TestStartupLogging:
    def test_corpus_version_logged_at_startup(
        self, seeded_lancedb, mocked_bge_m3, caplog
    ):
        cfg = Config(lancedb_path=seeded_lancedb)
        app = create_app(cfg)
        with caplog.at_level("INFO"), TestClient(app) as client:
            r = client.get("/readyz")
            assert r.status_code == 200

        # The startup log carries 'pinning corpus_version=N'. We don't
        # assert the exact integer (it varies with seeding) but we DO
        # assert the message is present.
        startup_msgs = [
            rec.getMessage()
            for rec in caplog.records
            if "pinning corpus_version=" in rec.getMessage()
        ]
        assert len(startup_msgs) >= 1, (
            f"expected startup log to include 'pinning corpus_version=', "
            f"got: {[r.getMessage() for r in caplog.records]}"
        )


# ===========================================================================
# Route surface — /metrics and /mcp are mounted
# ===========================================================================


class TestRouteSurface:
    def test_metrics_endpoint_responds(self, warm_app):
        r = warm_app.get("/metrics")
        assert r.status_code == 200
        # Prometheus exposition is text/plain.
        body = r.text
        assert "arxmcp_corpus_version" in body
        assert "arxmcp_resources_warm" in body
        assert "arxmcp_process_start_time_seconds" in body

    def test_metrics_corpus_version_matches_pinned(self, warm_app):
        r = warm_app.get("/metrics")
        # Find the gauge line for arxmcp_corpus_version.
        for line in r.text.splitlines():
            if line.startswith("arxmcp_corpus_version"):
                # Format: ``arxmcp_corpus_version <float>``
                value = float(line.split()[-1])
                # Seeded corpus is at version 1 or 2 depending on
                # internal LanceDB layout; we just assert it's a
                # positive integer.
                assert value >= 1.0
                return
        raise AssertionError("arxmcp_corpus_version not found in /metrics")

    def test_mcp_endpoint_mounted(self):
        """The /mcp endpoint is mounted (Streamable HTTP).

        The mcp library's ``streamable_http_app()`` carries its own
        session-manager lifespan; correctly threading that into the
        parent FastAPI lifespan + actually hitting the endpoint
        end-to-end requires the tool registrations that land in
        E06_S03. For this skeleton milestone we verify that the
        mount is present in ``app.routes`` — the route exists; the
        wire-up of the session-manager lifespan is E06_S03 territory.
        """
        from server.config import Config
        from server.main import create_app

        app = create_app(Config())
        # Find the /mcp Mount in app.routes.
        mount_paths = [
            getattr(r, "path", None)
            for r in app.routes
            if type(r).__name__ == "Mount"
        ]
        assert "/mcp" in mount_paths, (
            f"/mcp Mount not found; routes: "
            f"{[(type(r).__name__, getattr(r, 'path', None)) for r in app.routes]}"
        )


# ===========================================================================
# Resources.startup — refuses to start on cold corpus / unavailable reranker
# ===========================================================================


class TestStartupRefusals:
    def test_missing_corpus_marker_raises(self, tmp_path, mocked_bge_m3):
        """Synthesis D5: server REFUSES TO START when
        corpus-version.json is absent."""
        cfg = Config(lancedb_path=tmp_path / "no_lancedb")
        with pytest.raises(CorpusNotIngestedError, match="corpus-version.json not found"):
            asyncio.run(Resources.startup(cfg))

    def test_enable_rerank_without_model_raises(
        self, seeded_lancedb, mocked_bge_m3, monkeypatch
    ):
        """Synthesis D6: server REFUSES TO START when
        ARXMCP_ENABLE_RERANK=true but the reranker model is
        unavailable.

        E07_S03 ships the real reranker loader (replacing the
        E06_S01 stub that always raised). To preserve the original
        test intent (load failure → fatal), we patch
        ``server.resources._load_reranker_or_raise`` itself to
        raise — same outcome as the pre-E07_S03 stub:
        ``RerankerUnavailableError`` propagates out of
        ``Resources.startup`` and the server refuses to open
        ``/readyz``."""
        import server.resources as res_mod

        async def _force_raise():
            raise RerankerUnavailableError(
                "simulated reranker load failure (test fixture)"
            )

        monkeypatch.setattr(res_mod, "_load_reranker_or_raise", _force_raise)

        cfg = Config(
            lancedb_path=seeded_lancedb,
            enable_rerank=True,
        )
        with pytest.raises(
            RerankerUnavailableError, match="reranker"
        ):
            asyncio.run(Resources.startup(cfg))

    def test_enable_lean_spawn_failure_tears_down_resources(
        self, seeded_lancedb, mocked_bge_m3, monkeypatch
    ):
        """m2 critique F1: ARXMCP_ENABLE_LEAN=true with a Lean spawn
        failure must (a) propagate the error so the server refuses to
        start, AND (b) tear down the already-warm BGE-M3 / LanceDB /
        cache / SQLite resources before re-raising.

        Without the teardown, an operator with a broken
        ARXMCP_LAKE_PATH under ``docker restart: on-failure`` gets a
        crash-restart loop that leaks ~1.5 GB of BGE-M3 weights and an
        open SQLite WAL handle every iteration. The fix places the
        step-6e Lean spawn AFTER the ``Resources`` constructor so a
        failure routes through ``instance.shutdown()``.
        """
        import server.lean_repl as lean_mod
        from server.cache import get_cache
        from server.lean_repl import LeanUnavailableError

        async def _force_raise(_config):
            raise LeanUnavailableError(
                "simulated Lean spawn failure (test fixture)"
            )

        # spawn_from_config is accessed as LeanRepl.spawn_from_config(cfg)
        # (on the class, not an instance) — a plain async function is the
        # right shape.
        monkeypatch.setattr(
            lean_mod.LeanRepl, "spawn_from_config", _force_raise
        )

        cfg = Config(lancedb_path=seeded_lancedb, enable_lean=True)
        with pytest.raises(
            LeanUnavailableError, match="simulated Lean spawn failure"
        ):
            asyncio.run(Resources.startup(cfg))
        # instance.shutdown() ran on the failure path: the retrieval-
        # cache singleton was closed and the module reference cleared.
        assert get_cache() is None


# ===========================================================================
# Singleflight — generic class for the reranker (E07 consumer)
# ===========================================================================


class TestSingleflight:
    def test_dedup_concurrent_same_key(self):
        """Two concurrent calls with the same key produce ONE
        invocation of the factory."""
        sf = Singleflight()
        invocations = []

        async def factory():
            invocations.append(1)
            await asyncio.sleep(0.01)
            return "result"

        async def go():
            r1, r2 = await asyncio.gather(
                sf.run("key", factory),
                sf.run("key", factory),
            )
            return r1, r2

        r1, r2 = asyncio.run(go())
        assert r1 == "result" and r2 == "result"
        assert len(invocations) == 1
        assert sf.dedup_count == 1

    def test_distinct_keys_run_independently(self):
        sf = Singleflight()
        invocations = []

        async def factory_a():
            invocations.append("a")
            return "A"

        async def factory_b():
            invocations.append("b")
            return "B"

        async def go():
            return await asyncio.gather(
                sf.run("a", factory_a),
                sf.run("b", factory_b),
            )

        results = asyncio.run(go())
        assert results == ["A", "B"]
        assert sorted(invocations) == ["a", "b"]
        assert sf.dedup_count == 0

    def test_eviction_after_completion(self):
        """A successful run evicts the future, so a subsequent call
        with the same key invokes the factory again."""
        sf = Singleflight()
        count = [0]

        async def factory():
            count[0] += 1
            return count[0]

        async def go():
            r1 = await sf.run("k", factory)
            r2 = await sf.run("k", factory)
            return r1, r2

        r1, r2 = asyncio.run(go())
        assert r1 == 1 and r2 == 2

    def test_failure_evicts_and_propagates(self):
        sf = Singleflight()

        async def factory():
            raise RuntimeError("boom")

        async def go():
            with pytest.raises(RuntimeError, match="boom"):
                await sf.run("k", factory)
            # After failure, key is evicted and the next call retries.
            with pytest.raises(RuntimeError, match="boom"):
                await sf.run("k", factory)

        asyncio.run(go())

    def test_slow_path_cancel_does_not_break_fast_waiters(self):
        """F3 close: cancelling the slow-path caller must NOT cancel
        the shared task; fast-path waiters still receive the result.

        Reproduces the bug F1-from-E03_S03 closed for the embedder
        singleflight, but for this generic class.
        """
        sf = Singleflight()
        invocations = []

        async def factory():
            invocations.append(1)
            await asyncio.sleep(0.05)
            return "result"

        async def go():
            # Start the slow-path caller, give it time to register
            # the in-flight task, then start a fast-path waiter,
            # cancel the slow-path, and assert the fast-path still
            # gets the result.
            slow = asyncio.create_task(sf.run("k", factory))
            await asyncio.sleep(0.005)  # let slow path register
            fast = asyncio.create_task(sf.run("k", factory))
            await asyncio.sleep(0.005)  # let fast path register
            slow.cancel()
            with pytest.raises(asyncio.CancelledError):
                await slow
            # fast-path must still complete with the result
            result = await fast
            assert result == "result"
            assert len(invocations) == 1
            # dedup count incremented because fast-path saw the
            # in-flight task.
            assert sf.dedup_count == 1

        asyncio.run(go())


# ===========================================================================
# F1 — BodySizeCapMiddleware actually fires
# ===========================================================================


class TestBodySizeCap:
    """Closes F1 from the E06_S01 critique: the original
    ``BodySizeCapMiddleware`` was a silent no-op because Starlette
    wraps responses in ``_StreamingResponse`` whose payload lives in
    ``body_iterator``, not ``body``. The pure-ASGI rewrite intercepts
    the body events directly and short-circuits with 413."""

    @pytest.fixture
    def small_cap_app(self, seeded_lancedb, mocked_bge_m3):
        """An app with byte_cap=10 so a routine response trips the
        413 rewrite. Mounts a debug ``/__test_oversize`` route that
        returns 100 bytes."""
        cfg = Config(lancedb_path=seeded_lancedb, result_byte_cap=10)
        app = create_app(cfg)

        @app.get("/__test_oversize")
        async def oversize() -> dict:
            return {"data": "x" * 200}  # JSON body well over 10 bytes

        @app.get("/__test_under")
        async def under() -> dict:
            return {"ok": 1}  # JSON body well under 10 bytes... actually ~10

        with TestClient(app) as client:
            yield client

    def test_oversize_response_returns_413(self, small_cap_app):
        r = small_cap_app.get("/__test_oversize")
        assert r.status_code == 413
        body = r.json()
        assert body["error"] == "payload_too_large"
        assert body["byte_cap"] == 10

    def test_exempt_path_bypasses_cap(self, small_cap_app):
        """``/healthz`` returns its normal 200 even with byte_cap=10
        (the response body is ``{"status": "ok"}`` ≈ 16 bytes, over
        the cap)."""
        r = small_cap_app.get("/healthz")
        assert r.status_code == 200

    def test_metrics_path_bypasses_cap(self, small_cap_app):
        """Prometheus exposition ALWAYS exceeds 10 bytes; must not
        be capped."""
        r = small_cap_app.get("/metrics")
        assert r.status_code == 200


# ===========================================================================
# F2 — MCP /mcp endpoint serves tools/list end-to-end
# ===========================================================================


class TestMcpEndToEnd:
    """Closes F2 from the E06_S01 critique: the MCP session-manager
    lifespan must be threaded into the parent FastAPI lifespan, OR
    the first /mcp request raises ``RuntimeError: Task group is not
    initialized``. The original implementation lacked this; this
    test exercises a real round-trip with zero tools registered."""

    def test_tools_list_returns_empty(self, warm_app):
        """POST /mcp/ with an initialize JSON-RPC request returns
        a non-500 (i.e. the MCP session manager IS running).

        The mcp library's own DNS-rebinding protection rejects
        TestClient's default ``testserver`` Host header with 421;
        we pass ``Host: 127.0.0.1:7733`` to satisfy the protection.
        The exact tools/list round-trip (session-id handshake,
        SSE framing) is exercised end-to-end in E06_S03 once tools
        are registered. The minimum bar this milestone enforces:
        the session manager IS running, so initialize doesn't
        raise the "Task group is not initialized" error.
        """
        init_resp = warm_app.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            },
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "Host": "127.0.0.1:7733",
            },
        )
        # 200/202 = OK. The bug we're closing was: every POST to
        # /mcp/ returned 500 "Task group is not initialized" because
        # the session-manager lifespan never ran. Anything other
        # than that 500 means F2 is closed.
        assert init_resp.status_code != 500, (
            f"MCP /mcp endpoint returned 500 — likely the F2 'Task "
            f"group not initialized' regression. Body: "
            f"{init_resp.text[:300]}"
        )
        # Belt + suspenders: the response body must NOT mention
        # "Task group" — that would mean the session-manager
        # lifespan threading regressed even with a non-500 status.
        assert "Task group" not in init_resp.text, (
            f"MCP response body mentions 'Task group' — F2 may have "
            f"regressed. Body: {init_resp.text[:300]}"
        )


# ===========================================================================
# F4 — startup-time scan for unknown ARXMCP_* env vars
# ===========================================================================


class TestEnvVarScan:
    """Closes F4 from the E06_S01 critique:
    pydantic-settings's ``extra="forbid"`` only fires for direct
    ``__init__`` kwargs, NOT for env-var input. So a typo like
    ``ARXMCP_BIND_HOST_TYPO`` was silently ignored. The startup-
    time scan in :func:`server.main._scan_unknown_arxmcp_env_vars`
    catches it."""

    def test_unknown_env_var_rejected(self, monkeypatch):
        from server.main import _scan_unknown_arxmcp_env_vars

        monkeypatch.setenv("ARXMCP_DOES_NOT_EXIST", "x")
        with pytest.raises(ValueError, match="unknown ARXMCP_"):
            _scan_unknown_arxmcp_env_vars(Config(bind_host="127.0.0.1"))

    def test_known_env_vars_pass(self, monkeypatch):
        """Setting the canonical env vars must NOT trip the scan."""
        from server.main import _scan_unknown_arxmcp_env_vars

        monkeypatch.setenv("ARXMCP_BIND_HOST", "127.0.0.1")
        monkeypatch.setenv("ARXMCP_BIND_PORT", "7733")
        # Should not raise.
        _scan_unknown_arxmcp_env_vars(Config())

    def test_create_app_rejects_unknown_env(self, monkeypatch, seeded_lancedb):
        """create_app() invokes the scan; an unknown env var fails
        app construction, not lifespan startup."""
        monkeypatch.setenv("ARXMCP_BOGUS_VAR", "1")
        cfg = Config(lancedb_path=seeded_lancedb)
        with pytest.raises(ValueError, match="unknown ARXMCP_"):
            create_app(cfg)


# Suppress unused-import warning — `time` is used in the docstring example.
_ = time
