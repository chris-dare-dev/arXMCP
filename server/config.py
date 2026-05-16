"""Server configuration via ``pydantic-settings`` (E06_S01).

The single source of truth for the long-running ``arxmcp-server``
process's runtime knobs. Every value is overridable via an
``ARXMCP_*`` environment variable; defaults are the v1 production
values per the design constitution
(:doc:`.claude/notes/06-mcp-server-design.md`).

**Loopback-only binding (load-bearing).** ``bind_host`` is validated
at config-parse time to reject any non-loopback value
(``0.0.0.0``, public interfaces, etc.). The brief AC: *"binding to
``0.0.0.0`` is rejected at config parse time."* The validator
raises ``ValueError`` so pydantic-settings turns it into a
``ValidationError`` at instantiation, before uvicorn binds the
socket. Closes Threat 4 from
:doc:`.claude/notes/08-security-observability-ops.md` at the
config layer.

**Note on docker-compose drift.** ``08-security-observability-ops.md``
line 261 shows a docker-compose example setting
``ARXMCP_BIND_HOST=0.0.0.0`` inside the container (with the host-side
port-publish at ``127.0.0.1:7733``). The E06_S01 brief AC overrides
this for v1: reject non-loopback at the config layer with no
exception. If a future docker-compose deployment needs
container-internal binding, E06_S05 (security hardening) will
revisit. This synthesis call is documented in the implementation
summary.

**Why pydantic-settings.** A field-level ``@field_validator`` raises
at instantiation, satisfying the "rejected at config parse time"
AC without ad-hoc startup checks scattered across modules.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: The v1 default bind port. Picked once and pinned (`06-mcp-server-design.md`
#: line 313). The shim (E06_S02) hard-codes the same default; both must
#: change together if the project ever moves off 7733.
DEFAULT_BIND_PORT = 7733

#: Loopback values accepted by ``bind_host``. Per Threat 4
#: (`08-security-observability-ops.md`), only these names may be bound;
#: ``0.0.0.0`` and any public interface are rejected at config parse.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

#: Default 256 KB inline result-payload cap, per the brief and
#: `06-mcp-server-design.md` line 38. Larger payloads must be returned
#: via ``resource_link`` (E06_S03 enforcement).
DEFAULT_RESULT_BYTE_CAP = 256 * 1024


# ---------------------------------------------------------------------------
# Config — the single Settings class
# ---------------------------------------------------------------------------


class Config(BaseSettings):
    """Process-wide config.

    Instantiated once at server startup (``Config()`` reads env vars).
    Pass the resulting object into the lifespan; do NOT re-instantiate
    inside request handlers (that would re-read env on every call,
    and field validators would re-fire).

    All field defaults are the v1 production values; tests override
    via constructor kwargs or ``monkeypatch.setenv("ARXMCP_…")``
    BEFORE calling ``Config()``.
    """

    model_config = SettingsConfigDict(
        env_prefix="ARXMCP_",
        env_file=None,  # ARXMCP_* env vars only — no .env-file fallback.
        extra="forbid",  # unknown ARXMCP_* vars are configuration errors.
    )

    # --- Network ---------------------------------------------------------

    bind_host: str = "127.0.0.1"
    bind_port: int = DEFAULT_BIND_PORT

    # --- Storage ---------------------------------------------------------

    #: Repo-relative or absolute path to the LanceDB dataset root.
    #: Defaults match :data:`ingest.store.DEFAULT_LANCEDB_PATH` (the
    #: writer-side default), so a single-machine dev setup needs zero
    #: config to point reader-side at the same dataset the ingest
    #: pipeline wrote.
    lancedb_path: Path = Path("var/arxmcp/index/lancedb")

    #: SQLite file path for the Tier-1 retrieval cache (E08_S03).
    #: Sibling-of-sibling to ``lancedb_path`` so a single ``var/``
    #: tree holds both the corpus index and the cache. Parent
    #: directory is created at ``Resources.startup()`` time.
    cache_db_path: Path = Path("var/arxmcp/cache/retrieval.db")

    #: SQLite file path for the theorem-names FTS5 index (E10_S02).
    #: Sibling to the LanceDB indices under ``var/arxmcp/index/``;
    #: parent directory is created on first indexer run. When the
    #: file is absent, ``find_lemma_by_name`` falls back to the
    #: legacy in-memory scan over the chunks table.
    theorem_names_db_path: Path = Path("var/arxmcp/index/sqlite/theorem_names.db")

    #: Directory that holds cron-emitted sentinel files
    #: (drift-detected.flag, eval-quarantine.flag,
    #: delta-timeout.flag, backup-status.json) plus the
    #: per-version eval-reports/ subdirectory. Read at scrape
    #: time by E14_S01's :func:`server.health.refresh_sentinel_metrics`
    #: to rehydrate cross-process gauges from disk. Letting this
    #: be configurable lets tests inject a ``tmp_path`` cleanly
    #: without monkey-patching paths in three modules.
    ops_dir: Path = Path("var/arxmcp/ops")

    # --- Models ----------------------------------------------------------

    #: Whether to load the BGE-reranker-v2-m3 at startup. When True
    #: and the model is unavailable, startup FAILS (per synthesis D6:
    #: "Trust the operator's choice; refuse to start"). When False
    #: the reranker is never loaded; ``/readyz`` flips to 200 once
    #: the embedder + LanceDB are warm.
    enable_rerank: bool = False

    #: Pinned commit SHA for the BGE-reranker-v2-m3 model (E07_S03).
    #: The actual loader at :func:`server.resources._load_reranker_or_raise`
    #: passes ``revision=server.retrieval.rerank.BGE_RERANKER_COMMIT_SHA``
    #: (the module constant, NOT this Config value) to
    #: ``transformers.AutoModelForSequenceClassification.from_pretrained``
    #: — the constant is the canonical pin so an env-var override
    #: cannot silently swap models. This Config field is for the
    #: startup drift check + the audit trail. Default mirrors the
    #: constant; an operator who deliberately wants to test a
    #: different ref can override via env var, and the SHA-drift
    #: warning will then fire.
    rerank_model_sha: str = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"

    # --- Concurrency -----------------------------------------------------

    #: Throughput cap on DISTINCT-query embedding calls per
    #: synthesis D2 ("two-tier concurrency"). The semaphore bounds
    #: distinct-query parallelism; the existing
    #: :func:`server.query_encoder.encode_query` singleflight
    #: collapses same-query duplication. Both layers apply.
    max_concurrent_embeddings: int = 8

    #: Throughput cap on concurrent reranker forward passes. The
    #: reranker singleflight (added by ``server/resources.py``)
    #: handles the same-query collapse for the rerank path.
    max_concurrent_reranks: int = 4

    # --- Limits ----------------------------------------------------------

    #: Hard cap on inline tool-result body bytes. Enforced as a FastAPI
    #: middleware in :mod:`server.main`; tools landing in E06_S03 must
    #: return a ``resource_link`` for any payload that would exceed
    #: this. ``/healthz``, ``/readyz``, and ``/metrics`` are exempt
    #: (Prometheus output can grow large; health endpoints are
    #: negligible).
    result_byte_cap: int = DEFAULT_RESULT_BYTE_CAP

    # --- Retrieval tuning ------------------------------------------------

    #: Linear-combination weight α for the equation-similarity fusion
    #: in ``server.retrieval.equations.EquationIndex`` (E10_S03).
    #: ``final_score = α * (1 - normalized_ted) + (1 - α) * cosine``.
    #: α=0 collapses to pure cosine (dense-only); α=1 collapses to
    #: pure tree-edit distance. Default 0.5 (equal weights). Operators
    #: tuning recall vs. structural precision can shift via
    #: ``ARXMCP_EQ_TED_WEIGHT``.
    eq_ted_weight: float = 0.5

    # --- Observability ---------------------------------------------------

    log_level: str = "INFO"

    # --- Validators ------------------------------------------------------

    @field_validator("bind_host")
    @classmethod
    def reject_non_loopback(cls, v: str) -> str:
        """Closes the brief's "binding to ``0.0.0.0`` is rejected at
        config parse time" AC. Threat 4 from the security note.

        Accepts only the values in :data:`LOOPBACK_HOSTS`. Any other
        value — including ``0.0.0.0``, ``::`` (the IPv6 wildcard), a
        public IP, a hostname — raises ``ValueError`` which
        pydantic-settings turns into a ``ValidationError`` at
        instantiation time.
        """
        if v not in LOOPBACK_HOSTS:
            raise ValueError(
                f"ARXMCP_BIND_HOST must be a loopback address "
                f"({sorted(LOOPBACK_HOSTS)}); got {v!r}. The MCP "
                f"server binds only to localhost (Threat 4 — see "
                f".claude/notes/08-security-observability-ops.md). "
                f"Container deployments expose the port via host "
                f"port-mapping, not by binding to 0.0.0.0."
            )
        return v

    @field_validator("bind_port")
    @classmethod
    def validate_port_range(cls, v: int) -> int:
        """Reject privileged (<1024) and out-of-range ports at config
        parse so a misconfigured ``ARXMCP_BIND_PORT`` fails fast
        rather than producing a confusing ``PermissionError`` from
        uvicorn at bind time."""
        if not 1024 <= v <= 65535:
            raise ValueError(
                f"ARXMCP_BIND_PORT must be in [1024, 65535]; got {v}. "
                f"Privileged ports require root and the server runs "
                f"as a non-privileged user."
            )
        return v

    @field_validator("max_concurrent_embeddings", "max_concurrent_reranks")
    @classmethod
    def validate_positive_concurrency(cls, v: int) -> int:
        """Concurrency knobs must be positive. ``0`` would deadlock
        every request waiting on the semaphore; negative values are
        nonsensical and a likely typo."""
        if v < 1:
            raise ValueError(
                f"concurrency knob must be >= 1; got {v}"
            )
        return v

    @field_validator("eq_ted_weight")
    @classmethod
    def validate_eq_ted_weight(cls, v: float) -> float:
        """Equation fusion α must live in [0, 1]. Values outside the
        unit interval would produce final scores that no longer track
        either cosine or TED meaningfully."""
        if not 0.0 <= v <= 1.0:
            raise ValueError(
                f"ARXMCP_EQ_TED_WEIGHT must be in [0.0, 1.0]; got {v}. "
                f"0.0 = pure cosine (no TED), 1.0 = pure TED (no "
                f"cosine), 0.5 = equal weights (default)."
            )
        return v

    @field_validator("result_byte_cap")
    @classmethod
    def validate_byte_cap(cls, v: int) -> int:
        """The result cap must be positive. A 0 cap would refuse every
        non-empty response; a negative cap is nonsensical."""
        if v < 1:
            raise ValueError(
                f"result_byte_cap must be >= 1; got {v}"
            )
        return v


__all__ = [
    "DEFAULT_BIND_PORT",
    "DEFAULT_RESULT_BYTE_CAP",
    "LOOPBACK_HOSTS",
    "Config",
]
