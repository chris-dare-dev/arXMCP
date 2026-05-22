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

from pydantic import Field, SecretStr, field_validator, model_validator
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

    #: SQLite file path for the per-notebook metadata store
    #: (proof-verify-handler-wiring-m7). SEPARATE file from
    #: ``cache_db_path`` so a schema-version bump on either side
    #: does not trigger the OTHER's DROP-AND-RECREATE migration
    #: (m7 synthesis FM-6). Sibling to ``cache_db_path`` per the
    #: m7 brief; the per-notebook on-disk assets live elsewhere
    #: at ``var/arxmcp/notebooks/<slug>/`` and are NOT in this DB.
    notebooks_db_path: Path = Path("var/arxmcp/cache/notebooks.db")

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

    #: Root directory for runtime state — corpus, indices, caches,
    #: ops sentinels. The disk-full scrape hook (E14_S05 D4) calls
    #: ``shutil.disk_usage(data_dir)`` so the gauge reflects the
    #: filesystem actually serving the corpus and indices.
    #:
    #: Default ``var/arxmcp`` matches the project's existing
    #: directory convention (CLAUDE.md §5). Production deployments
    #: under ``/var/lib/arxmcp`` or ``/opt/arxmcp/var`` should set
    #: ``ARXMCP_DATA_DIR`` accordingly.
    data_dir: Path = Path("var/arxmcp")

    #: Query-embedder provider (E14_S05 D6). ``"local"`` uses the
    #: in-process BGE-M3 weights. ``"voyage"`` reserves the hosted
    #: path; the v1 implementation is a stub that raises and falls
    #: back to local — actual Voyage HTTP integration is a separate
    #: ticket. The fallback wrapper in
    #: :func:`server.query_encoder.encode_query` tags results with
    #: ``degraded=true`` on the fallback path.
    query_embed_provider: str = "local"

    #: API key for the optional hosted-embedder provider (Voyage).
    #: Wrapped in :class:`pydantic.SecretStr` so a stray
    #: ``logger.info("config=%s", config)`` cannot leak the key —
    #: ``SecretStr.__repr__`` returns ``SecretStr('**********')``.
    #: Callers that need the actual value must call
    #: ``.get_secret_value()`` explicitly. F5 rectification from
    #: the E14_S05 adversary critique.
    voyage_api_key: SecretStr | None = None

    #: OTLP/gRPC endpoint for OpenTelemetry trace export (E14_S02).
    #: When unset (``None``), tracing is COMPLETELY DISABLED at the
    #: OTel SDK layer: :func:`server.observability.tracing.setup_tracing`
    #: returns without calling ``trace.set_tracer_provider(...)``, so
    #: every ``tracer.start_as_current_span(...)`` invocation takes
    #: the ``ProxyTracer`` → ``NoOpTracer`` fast path with zero
    #: allocation. When set, the SDK exports via ``OTLPSpanExporter``
    #: (gRPC) with ``insecure=True``; the ``http://`` scheme is
    #: decorative — the gRPC client uses it only to decide
    #: ``insecure_channel`` vs ``secure_channel``. Default port 4317
    #: matches Phoenix's OTLP intake.
    #:
    #: **Security: loopback-only at config parse time.** Spans carry
    #: ``mcp.session_id`` (per ``08-security-observability-ops.md``
    #: §Tracing). Forwarding to an external SaaS collector would
    #: leak session IDs. The :meth:`validate_otel_endpoint_loopback`
    #: validator rejects non-loopback hostnames at instantiation
    #: time — same precedent as :meth:`reject_non_loopback_bind` for
    #: ``bind_host``. The escape hatch
    #: (:data:`otel_allow_remote`) is documented separately and
    #: requires an explicit operator opt-in. F1 from the E14_S02
    #: adversary critique.
    otel_endpoint: str | None = None

    #: Operator-only escape hatch — set to ``True`` to allow
    #: ``otel_endpoint`` to point at a non-loopback host. Requires
    #: that the operator has independently audited the export path
    #: for `mcp.session_id` leakage (e.g. via a custom span
    #: processor that redacts the attribute). Default ``False`` =
    #: loopback-only.
    otel_allow_remote: bool = False

    #: E13_S05 (Threat 5) — additional Origin values accepted beyond
    #: the hardcoded loopback floor (``LOOPBACK_ORIGIN_HOSTS`` in
    #: :mod:`server.middleware`). Empty list (default) preserves the
    #: existing E06_S05 behavior: only loopback Origin values pass.
    #: Non-empty list EXTENDS the floor — the listed origins are
    #: accepted in addition to the loopback set. The loopback floor
    #: is a security baseline that cannot be bypassed via this var.
    #:
    #: Parsed from ``ARXMCP_ALLOWED_ORIGINS`` as a JSON list (per
    #: pydantic-settings convention for ``list[str]`` fields), e.g.
    #: ``ARXMCP_ALLOWED_ORIGINS='["http://my-tool.localhost:8080"]'``.
    allowed_origins: list[str] = Field(default_factory=list)

    #: E13_S05 (Threat 5) — escape hatch for non-loopback bind.
    #: Default ``False`` = ``ARXMCP_BIND_HOST=0.0.0.0`` is rejected
    #: at config parse time (the historical behavior preserved).
    #: ``True`` = the bind-host validator permits non-loopback
    #: values AND a WARN log fires at startup. The escape hatch is
    #: documented for container deployments only — see
    #: ``.claude/docs/security-binding.md``.
    unsafe_network_bind: bool = False

    #: E13_S07 (Threat 7) — opt-in CA pinning flag for arxiv.org.
    #: Default ``False``: ``urllib.request`` uses the system trust
    #: store (safe-by-default; TLS verification cannot be disabled
    #: by any ``ARXMCP_*`` env var).
    #:
    #: **Forward-compatible placeholder. No current behavior.**
    #: Setting ``True`` is accepted by the config but does NOT yet
    #: change the SSL context — the field is plumbing for a future
    #: milestone that will validate the arxiv.org certificate chain
    #: against a pinned fingerprint. F1 rectification (E13_S07
    #: adversary): the prior docstring claimed an INFO log was
    #: emitted on opt-in; no such log exists yet. The actual log
    #: line and the SSL-context wiring land together in the closure
    #: milestone.
    #:
    #: The threat model in ``.claude/notes/08-security-observability-ops.md``
    #: § Threat 7 lists this as one mitigation; the actual
    #: certificate-chain inspection is deferred because the
    #: arxiv.org CA rotates periodically and hard-coding a pin
    #: without an operator refresh procedure creates more
    #: operational toil than security benefit at Tier-5. See
    #: ``.claude/docs/security-threat-7-audit.md`` for the full
    #: rationale and the planned closure path.
    pin_arxiv_ca: bool = False

    # --- Validators ------------------------------------------------------

    @model_validator(mode="after")
    def reject_non_loopback_bind(self) -> Config:
        """Closes the brief's "binding to ``0.0.0.0`` is rejected at
        config parse time" AC. Threat 4 from the security note +
        Threat 5 from E13_S05.

        E13_S05 D1 — converted from ``@field_validator("bind_host")``
        to ``@model_validator(mode="after")`` so both ``bind_host``
        and ``unsafe_network_bind`` are visible. The default-deny
        posture is preserved: ``bind_host`` must be in
        :data:`LOOPBACK_HOSTS` unless ``unsafe_network_bind=True``
        is explicitly set (typically only in container deployments
        where the host-side port mapping pins to 127.0.0.1).
        """
        if self.bind_host not in LOOPBACK_HOSTS and not self.unsafe_network_bind:
            raise ValueError(
                f"ARXMCP_BIND_HOST must be a loopback address "
                f"({sorted(LOOPBACK_HOSTS)}); got {self.bind_host!r}. "
                f"The MCP server binds only to localhost (Threat 4/5 — see "
                f".claude/notes/08-security-observability-ops.md). "
                f"Container deployments should expose the port via host "
                f"port-mapping (``ports: \"127.0.0.1:7733:7733\"``) rather "
                f"than binding to 0.0.0.0. If the container truly must "
                f"bind 0.0.0.0 INTERNALLY (with the host port-mapping "
                f"still pinning the host side to 127.0.0.1), set "
                f"``ARXMCP_UNSAFE_NETWORK_BIND=1`` to override; see "
                f".claude/docs/security-binding.md for the full warning."
            )
        return self

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

    @field_validator("query_embed_provider")
    @classmethod
    def validate_query_embed_provider(cls, v: str) -> str:
        """Reject unknown provider names at parse time. The E14_S05
        D6 contract: only ``local`` is implemented end-to-end;
        ``voyage`` is reserved (stub that falls back to local).
        Adding a new provider requires both this allow-list update
        and a registration in ``server.query_encoder``."""
        allowed = {"local", "voyage"}
        if v not in allowed:
            raise ValueError(
                f"ARXMCP_QUERY_EMBED_PROVIDER must be one of "
                f"{sorted(allowed)}; got {v!r}"
            )
        return v

    @model_validator(mode="after")
    def validate_otel_endpoint_loopback(self) -> Config:
        """Reject non-loopback ``otel_endpoint`` values at config parse
        time unless :data:`otel_allow_remote` is explicitly set.

        Closes F1 from the E14_S02 adversary critique and the brief's
        named Risk note (*"OTel spans containing mcp.session_id must
        not be forwarded to a remote endpoint by default"*). Mirrors
        the :meth:`reject_non_loopback_bind` precedent on ``bind_host`` —
        push the policy to the config layer so an environment-driven
        misconfiguration fails at startup, not silently in production.

        Accepted endpoints (when ``otel_allow_remote=False``):

        * ``None`` — tracing disabled (the default).
        * Hostnames in :data:`LOOPBACK_HOSTS` (``127.0.0.1``, ``::1``,
          ``localhost``).
        * Any ``http://`` or ``https://`` URL where the hostname is
          loopback.

        Rejected (raises ``ValueError`` → pydantic-settings
        ``ValidationError``): public IPs, private RFC-1918 ranges,
        link-local metadata-service IPs (``169.254.x.x``), DNS
        hostnames, userinfo (``user:pass@host``), missing host.

        The ``otel_allow_remote=True`` escape hatch is for operators
        who have independently audited their span pipeline for
        ``mcp.session_id`` leakage (e.g. by registering a span
        processor that redacts the attribute before export).
        """
        if self.otel_endpoint is None:
            return self
        if self.otel_allow_remote:
            return self

        # Defer urlparse import to avoid module-load cost when the
        # endpoint is None (the common case).
        from urllib.parse import urlparse  # noqa: PLC0415

        try:
            parsed = urlparse(self.otel_endpoint)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"ARXMCP_OTEL_ENDPOINT must be a valid URL; got "
                f"{self.otel_endpoint!r}: {exc}"
            ) from exc

        if parsed.scheme not in ("http", "https"):
            raise ValueError(
                f"ARXMCP_OTEL_ENDPOINT must use http:// or https:// "
                f"scheme; got {self.otel_endpoint!r}"
            )
        if parsed.username or parsed.password:
            raise ValueError(
                f"ARXMCP_OTEL_ENDPOINT must not include userinfo; got "
                f"{self.otel_endpoint!r}"
            )
        host = parsed.hostname
        if host is None or host == "":
            raise ValueError(
                f"ARXMCP_OTEL_ENDPOINT must include a hostname; got "
                f"{self.otel_endpoint!r}"
            )
        if host not in LOOPBACK_HOSTS:
            raise ValueError(
                f"ARXMCP_OTEL_ENDPOINT host must be a loopback "
                f"address ({sorted(LOOPBACK_HOSTS)}); got {host!r} "
                f"in {self.otel_endpoint!r}. Spans carry "
                f"mcp.session_id (see "
                f".claude/notes/08-security-observability-ops.md "
                f"§Tracing) — forwarding to an external collector "
                f"leaks session IDs. To override after auditing the "
                f"export path, set ARXMCP_OTEL_ALLOW_REMOTE=1."
            )
        return self


__all__ = [
    "DEFAULT_BIND_PORT",
    "DEFAULT_RESULT_BYTE_CAP",
    "LOOPBACK_HOSTS",
    "Config",
]
