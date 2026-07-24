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
    #:
    #: **notebook-retrieval-m1 (fork C):** when :attr:`notebook` is set
    #: (``ARXMCP_NOTEBOOK=<slug>``), the :meth:`derive_notebook_lancedb_path`
    #: model-validator OVERRIDES this field with the per-notebook dataset
    #: path ``var/arxmcp/notebooks/<slug>/lancedb`` before
    #: ``Resources.startup`` reads it. Setting both ``ARXMCP_NOTEBOOK``
    #: and ``ARXMCP_LANCEDB_PATH`` explicitly is rejected as ambiguous.
    lancedb_path: Path = Path("var/arxmcp/index/lancedb")

    #: notebook-retrieval-m1 (fork C) — when set to a notebook slug
    #: (via ``ARXMCP_NOTEBOOK``), the server serves THAT notebook's
    #: corpus: :meth:`derive_notebook_lancedb_path` rewrites
    #: :attr:`lancedb_path` to ``var/arxmcp/notebooks/<slug>/lancedb``.
    #: This is the v1 single-notebook-per-process mode. Default
    #: ``None`` preserves the shared-corpus behavior byte-for-byte
    #: (the server attempts ``var/arxmcp/index/lancedb`` exactly as
    #: it does today — including its ``CorpusNotIngestedError`` when
    #: that corpus is empty). The eventual per-call multi-notebook
    #: mode (``filters.notebook=<slug>``, fork A) layers on top and
    #: reuses the same
    #: :func:`tools._notebook_common.notebook_lancedb_path` helper.
    notebook: str | None = None

    #: Repo-relative or absolute path to the Kùzu citation-graph DB
    #: directory. Default matches :data:`server.graph_queries.DEFAULT_KUZUDB_PATH`
    #: and the Makefile bootstrap target — ``kuzu/`` not ``kuzudb/``
    #: (the canonical path; see CLAUDE.md §8 gotcha #4). The
    #: ``cite_neighbors`` handler reads this via :func:`get_resources`
    #: rather than accepting an agent-supplied path — the E09_S03 F2
    #: path-validation contract requires the graph path to be
    #: config-derived, never sourced from agent JSON arguments.
    kuzu_path: Path = Path("var/arxmcp/index/kuzu")

    #: SQLite file path for the Tier-1 retrieval cache (E08_S03).
    #: Sibling-of-sibling to ``lancedb_path`` so a single ``var/``
    #: tree holds both the corpus index and the cache. Parent
    #: directory is created at ``Resources.startup()`` time.
    cache_db_path: Path = Path("var/arxmcp/cache/retrieval.db")

    #: Per-notebook BM25 index root (notebook-bm25-isolation-m1).
    #: Default ``None`` means "resolve :data:`ingest.bm25_indexer.BM25_INDEX_ROOT`
    #: at call time" — preserving the conftest autouse
    #: ``monkeypatch.setattr(bm25_mod, "BM25_INDEX_ROOT", ...)`` used by
    #: ~40 tests. When :attr:`notebook` is set, the
    #: :meth:`derive_notebook_lancedb_path` validator rewrites this to
    #: ``var/arxmcp/notebooks/<slug>/index/bm25`` (mirroring the
    #: ``cache_db_path`` isolation) unless ``ARXMCP_BM25_INDEX_ROOT``
    #: was set explicitly. The shared (non-notebook) path stays ``None``
    #: so the global root remains in effect (FM-4 — shared default MUST
    #: stay global).
    bm25_index_root: Path | None = None

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

    #: verification-feedback-m2 — gates the managed Lean 4 REPL
    #: subprocess harness (``server/lean_repl.py``). Default OFF, exactly
    #: mirroring :attr:`enable_rerank`: the server starts cleanly on a
    #: workstation with no Lean toolchain. When ``true``,
    #: ``Resources.startup`` spawns one ``LeanRepl`` and a startup
    #: failure (unresolvable toolchain) is FATAL — ``LeanUnavailableError``
    #: is raised, the server refuses to start (the ``enable_rerank`` /
    #: ``RerankerUnavailableError`` precedent: trust the operator).
    enable_lean: bool = False

    #: onboarding-uplift-m4 — opt-in "wizard mode" for fresh-clone
    #: operators who want to boot the server BEFORE any corpus exists.
    #: Default ``False`` preserves the historical behaviour: a cold-start
    #: (no ``corpus-version.json`` marker) is FATAL and the server
    #: refuses to start (synthesis D1).
    #:
    #: When ``True`` AND no corpus marker is present:
    #: ``Resources.startup`` skips :class:`CorpusNotIngestedError`, sets
    #: :attr:`Resources.bootstrap_mode_active` = ``True``, and returns a
    #: stub instance with ``corpus_info=None`` / ``chunks_table=None``.
    #: Every MCP tool call is short-circuited to a structured
    #: ``no_notebook_selected`` envelope (via
    #: :func:`server.tools._build_bootstrap_envelope`) until the first
    #: successful ingest fires :meth:`Resources.late_bind`.
    #:
    #: FM-7: if ``bootstrap_mode=True`` AND the corpus IS already
    #: ingested, the flag is silently ignored and the server boots
    #: normally.  A restart with ``ARXMCP_BOOTSTRAP_MODE=1`` after
    #: ingest succeeds is therefore benign.
    #:
    #: The ``make up-wizard`` convenience target sets this env var
    #: automatically.  Operators wanting the wizard flow set
    #: ``ARXMCP_BOOTSTRAP_MODE=1`` or run ``make up-wizard``.
    bootstrap_mode: bool = False

    #: verification-feedback-m2 — directory of the built
    #: ``leanprover-community/repl`` package; the subprocess ``cwd`` for
    #: ``lake exe repl`` (``lake`` sets ``LEAN_PATH`` for that package).
    #: ``None`` (the default) is valid only when ``enable_lean=False``;
    #: with ``enable_lean=True`` an unset value raises
    #: ``LeanUnavailableError`` at startup. Lean is a *system*
    #: dependency, not a pip dep — `pyproject.toml` cannot declare it,
    #: so the operator points this at a pre-built repl directory.
    lean_repl_dir: Path | None = None

    #: verification-feedback-m2 — absolute path to the ``lake`` /
    #: ``lake.exe`` binary used to launch the Lean REPL. An absolute
    #: path is mandatory: ``asyncio.create_subprocess_exec`` does NOT
    #: PATH-search a bare name on Windows (spike-2 finding #1). ``None``
    #: is valid only when ``enable_lean=False``.
    lake_path: Path | None = None

    #: verification-feedback-m3 — hard address-space cap (``RLIMIT_AS``,
    #: bytes) applied to the Lean REPL subprocess via a POSIX
    #: ``preexec_fn``. Closes the m2 critique F4 deferral: agent-supplied
    #: Lean source first reaches ``LeanRepl.query`` in m3, so this is
    #: where the memory cap lands. Default 4 GiB — generous enough that a
    #: trivial elaboration succeeds (Lean kernel + oleans easily mmap
    #: hundreds of MB) but bounded so a runaway ``def f := List.range
    #: 10_000_000`` cannot OOM-kill the parent process.
    #:
    #: **POSIX-only.** Windows has no ``RLIMIT_AS`` / ``resource`` module
    #: and ``asyncio.create_subprocess_exec`` raises ``ValueError`` if
    #: ``preexec_fn`` is set — ``LeanRepl.spawn`` therefore silently skips
    #: the cap on ``sys.platform == "win32"`` and logs a WARN at startup.
    #: A Job-Object-based equivalent for Windows is documented as
    #: deferred in ``.claude/docs/lean-sandbox-design.md``.
    lean_rlimit_as_bytes: int = 4 * 1024 * 1024 * 1024  # 4 GiB

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

    #: agent-platform-m1 (D4-R07) — lifetime cap on ``search_papers``
    #: calls per MCP session, enforced by ``SessionCapMiddleware`` via
    #: :data:`server.session.MAX_SEARCH_PAPERS_CALLS`.
    #:
    #: Declared as a Config field rather than read from the environment
    #: directly so the ``extra="forbid"`` contract stays intact — an
    #: undeclared ``ARXMCP_*`` var is a startup error via
    #: ``_scan_unknown_arxmcp_env_vars`` (which derives its allow-list
    #: from ``Config.model_fields``, so declaring here is sufficient).
    #:
    #: Default raised 3 -> 30 for interactive use. See
    #: :mod:`server.session` for why the legacy E08_S04 value was
    #: unusable and why these caps are cost control, not a security
    #: boundary.
    max_search_papers_calls: int = Field(default=30, ge=1)

    #: agent-platform-m1 (D4-R07) — lifetime cap on ``get_chunk`` calls
    #: per MCP session. Default raised 4 -> 100; see
    #: :attr:`max_search_papers_calls` for the declaration rationale.
    max_get_chunk_calls: int = Field(default=100, ge=1)

    # --- Retrieval tuning ------------------------------------------------

    #: Linear-combination weight α for the equation-similarity fusion
    #: in ``server.retrieval.equations.EquationIndex`` (E10_S03).
    #: ``final_score = α * (1 - normalized_ted) + (1 - α) * cosine``.
    #: α=0 collapses to pure cosine (dense-only); α=1 collapses to
    #: pure tree-edit distance. Default 0.5 (equal weights). Operators
    #: tuning recall vs. structural precision can shift via
    #: ``ARXMCP_EQ_TED_WEIGHT``.
    eq_ted_weight: float = 0.5

    #: retrieval-unlocks-m4 — route a LaTeX ``find_equation`` query onto
    #: the TED lane by converting it to Presentation MathML with
    #: latex2mathml, instead of falling back to dense-only over
    #: ``embedding_stmt``.
    #:
    #: **Default OFF, deliberately**, even though the parity gate passes
    #: (converted queries retrieve their own equation rank-1 on the
    #: sampled corpus — 50/50, the property that matters for serving;
    #: exact tree agreement is only ~18%, from macro divergence
    #: latex2mathml can't resolve, which is why rank-1 not distance is the
    #: gate). Three reasons to ship it off and flip the default later,
    #: in the same W1 change that corrects the tool description:
    #:   1. The regression guard (``tests/eval/test_equations_parity.py``)
    #:      SKIPS when the parsed corpus is absent — i.e. in CI — so a
    #:      default-ON route would have no automated protection against a
    #:      latex2mathml bump. The exact pin is the only always-on guard.
    #:   2. The parity evidence is a single small-pool draw; rank-1 on a
    #:      200-equation pool does not prove it at 50K-corpus scale.
    #:   3. No equations table exists on disk yet, so the route is latent
    #:      regardless — OFF costs nothing today and keeps the (unedited,
    #:      W1-staged) tool description TRUE until the flip.
    #: Set ``ARXMCP_EQ_LATEX_ROUTE=true`` to enable. W1 (#72) flips this
    #: default and the description together; see w1-schema-deltas.md.
    eq_latex_route: bool = False

    # --- Observability ---------------------------------------------------

    log_level: str = "INFO"

    #: Log output format (corpus-integrity-observability-e2). ``"json"`` emits
    #: one structured JSON line per record (12-factor; the default per
    #: ``08-security-observability-ops.md`` §Logging "Structured JSON logs to
    #: stdout"); ``"text"`` keeps the human-readable stdlib format for local
    #: dev. The ``RedactionFilter`` runs regardless of format. Set via
    #: ``ARXMCP_LOG_FORMAT``.
    log_format: str = "json"

    #: Tolerance for the startup corpus-count reconciliation invariant
    #: (corpus-integrity-observability-m2). At ``Resources.startup`` the
    #: server compares the live ``chunks_table.count_rows()`` against the
    #: marker's ``chunk_count``; a divergence beyond this fraction logs a
    #: WARN and flips ``/readyz`` to ``degraded`` (WARN-and-serve —
    #: retrieval is unaffected). Default 0.05 (5%). A 1-row absolute floor
    #: is applied on top so tiny corpora do not alarm on a single-row
    #: delta. Set via ``ARXMCP_CORPUS_CHUNK_COUNT_TOLERANCE``.
    corpus_chunk_count_tolerance: float = 0.05

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

    #: E13_S07 (Threat 7) — opt-in CA pinning flag for arxiv.org +
    #: ar5iv.labs.arxiv.org. Default ``False``: ``urllib.request``
    #: uses the system trust store (safe-by-default; TLS verification
    #: cannot be disabled by any ``ARXMCP_*`` env var).
    #:
    #: When ``True`` (E13_S07c wiring), the two arxiv-rooted fetch
    #: sites — ``ingest/ar5iv_fetch.py::try_cache`` and
    #: ``tools/arxiv_fetch.py::fetch_eprint`` — use an
    #: ``ssl.SSLContext`` built from a pinned CA bundle instead of
    #: the system trust store. The bundle defaults to the vendored
    #: ISRG Root X1 PEM at ``infra/ca/arxiv-ca-bundle.pem``
    #: (arxiv.org and ar5iv chain to Let's Encrypt; pinning the root
    #: survives the 60-90-day intermediate rotation cadence). An
    #: operator-supplied alternative path is accepted via
    #: :attr:`arxiv_ca_bundle_path`.
    #:
    #: **Fail-closed contract.** When this flag is ``True`` but the
    #: resolved bundle path does not exist, the
    #: :meth:`validate_arxiv_ca_bundle` model-validator raises
    #: ``ValueError`` at Config-load time — the server does NOT
    #: silently fall back to the system trust store, which would
    #: defeat the entire purpose of the pin.
    #:
    #: Scope: arxiv.org + ar5iv.labs.arxiv.org ONLY. The pin does
    #: NOT apply to OpenAlex / INSPIRE / OAI-PMH fetches — those
    #: have separate hosts and separate CA chains, outside Threat 7
    #: scope per the threat statement in
    #: ``.claude/notes/08-security-observability-ops.md``.
    #:
    #: See ``.claude/docs/security-threat-7-audit.md`` for the
    #: refresh procedure (``make refresh-arxiv-ca``) and the
    #: rotation-cadence rationale.
    pin_arxiv_ca: bool = False

    #: E13_S07c — operator override for the pinned CA bundle path.
    #: Default ``None`` means "use the vendored bundle at
    #: ``infra/ca/arxiv-ca-bundle.pem``". A non-None value is taken
    #: verbatim (no path traversal, no envvar expansion); the
    #: validator below checks the resolved file exists.
    #:
    #: Declared as a Config field (rather than read from the
    #: environment directly) so the ``extra="forbid"`` contract
    #: stays intact — undeclared ``ARXMCP_*`` env vars are caught at
    #: startup by ``_scan_unknown_arxmcp_env_vars`` in
    #: ``server/main.py``. Default-None semantics: only consulted
    #: when ``pin_arxiv_ca=True``; never affects the safe-by-default
    #: flag-off posture.
    arxiv_ca_bundle_path: Path | None = None

    # --- Validators ------------------------------------------------------

    @model_validator(mode="after")
    def derive_notebook_lancedb_path(self) -> Config:
        """notebook-retrieval-m1 (fork C) — when ``ARXMCP_NOTEBOOK=<slug>``
        is set, rewrite :attr:`lancedb_path` to the per-notebook dataset
        ``var/arxmcp/notebooks/<slug>/lancedb`` BEFORE ``Resources.startup``
        reads it (the substitution must precede ``read_corpus_version`` —
        see the notebook-retrieval-m1 synthesis).

        Safety + clarity:

        * The slug is validated (regex + symlink rejection + containment)
          by :func:`tools._notebook_common.notebook_lancedb_path`, which
          raises ``NotebookError`` (re-wrapped as ``ValueError`` →
          pydantic ``ValidationError``) for any path-traversal attempt
          (Threat 1).
        * Setting BOTH ``ARXMCP_NOTEBOOK`` and an explicit
          ``ARXMCP_LANCEDB_PATH`` *that differs from the field default*
          is rejected as ambiguous — the operator must pick one
          substrate. Setting ``ARXMCP_LANCEDB_PATH`` to its own default
          value is a no-op and does NOT conflict (F4 rectification).
        * If the notebook corpus has not been ingested (no
          ``corpus-version.json`` marker on disk — the SAME marker
          ``Resources.startup`` reads), fail fast at config-load with a
          remediation message naming the ingest command, rather than
          surfacing a deeper ``CorpusNotIngestedError`` from
          ``Resources.startup`` (AC5 — clean typed error, not a 500;
          F3 rectification).
        * The Tier-1 retrieval cache is redirected to a per-notebook
          sibling (``var/arxmcp/notebooks/<slug>/cache/retrieval.db``)
          unless ``ARXMCP_CACHE_DB_PATH`` is set explicitly, so two
          notebooks relaunched within the cache TTL cannot serve each
          other's chunks (F1 rectification).

        No-op when ``notebook`` is ``None`` (the default shared-corpus
        posture; AC4 — env-unset behavior is byte-identical to today).
        """
        if self.notebook is None:
            return self
        # Ambiguity guard (F4 rectification): reject notebook + explicit
        # lancedb_path ONLY when the explicit value DIFFERS from the field
        # default. Setting ARXMCP_LANCEDB_PATH to its own default value
        # alongside ARXMCP_NOTEBOOK is not a real conflict — a common
        # foot-gun for operators who carry a baseline ARXMCP_LANCEDB_PATH
        # in a shell profile. A value-equals-default override is a no-op,
        # so the notebook derivation proceeds unambiguously.
        default_lancedb = type(self).model_fields["lancedb_path"].default
        if (
            "lancedb_path" in self.model_fields_set
            and self.lancedb_path != default_lancedb
        ):
            raise ValueError(
                "set either ARXMCP_NOTEBOOK or ARXMCP_LANCEDB_PATH, not "
                f"both (got notebook={self.notebook!r} and an explicit "
                f"lancedb_path={self.lancedb_path!s}). ARXMCP_NOTEBOOK "
                "derives the lancedb path from the notebook slug."
            )
        # Defer the import: tools._notebook_common is the shared seam
        # (also called by the future fork-A per-request path). Keeping
        # it lazy avoids a server→tools import at module load for the
        # common (notebook-unset) case.
        from tools._notebook_common import (  # noqa: PLC0415
            NotebookError,
            notebook_lancedb_path,
        )
        try:
            derived = notebook_lancedb_path(self.notebook)
        except NotebookError as exc:
            raise ValueError(
                f"invalid ARXMCP_NOTEBOOK={self.notebook!r}: {exc}"
            ) from exc
        # F3 rectification: prove the corpus is actually INGESTED, not
        # merely that the lancedb directory exists. ``Resources.startup``
        # reads ``<lancedb_path>/corpus-version.json`` (server/resources.py
        # line 308); a dir-present / marker-absent partial ingest passes an
        # ``is_dir()`` check then dies later with ``CorpusNotIngestedError``
        # — the exact "deeper error, not a clean config error" that AC5 was
        # written to prevent. Check the SAME marker the startup path checks,
        # so the config gate and the startup gate share one contract.
        if not (derived / "corpus-version.json").is_file():
            raise ValueError(
                f"ARXMCP_NOTEBOOK={self.notebook!r}: no ingested corpus "
                f"at {derived!s}. Ingest it first: "
                f"`uv run python tools/notebook_ingest.py {self.notebook}`."
            )
        self.lancedb_path = derived
        # F1 rectification (HIGH): redirect the Tier-1 retrieval cache to a
        # per-notebook sibling unless ARXMCP_CACHE_DB_PATH was set
        # explicitly. Without this, two notebooks relaunched within the
        # cache TTL share the default ``cache_db_path``; the Tier-1 key is
        # (query, filters, k, corpus_version, level) — NO notebook slug —
        # and corpus_version is per-dataset MVCC (not globally unique), so a
        # relaunch from notebook A to notebook B can serve A's chunks for a
        # B query. Structural isolation here mirrors the lancedb isolation
        # and avoids the slug-in-key refactor deferred to m2.
        if "cache_db_path" not in self.model_fields_set:
            self.cache_db_path = derived.parent / "cache" / "retrieval.db"
        # notebook-bm25-isolation-m1: redirect the BM25 index root to a
        # per-notebook directory unless ARXMCP_BM25_INDEX_ROOT was set
        # explicitly. Mirrors the ``cache_db_path`` isolation above.
        # ``derived.parent`` = ``var/arxmcp/notebooks/<slug>/`` so the
        # BM25 root becomes ``var/arxmcp/notebooks/<slug>/index/bm25``.
        # The shared (non-notebook) path stays ``None`` via the
        # ``if self.notebook is None: return self`` guard above (FM-4).
        if "bm25_index_root" not in self.model_fields_set:
            self.bm25_index_root = derived.parent / "index" / "bm25"
        return self

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

    @model_validator(mode="after")
    def validate_arxiv_ca_bundle(self) -> Config:
        """E13_S07c — fail-closed when ``pin_arxiv_ca=True`` but the
        resolved CA bundle path does not exist.

        Resolution order:

        1. If :attr:`arxiv_ca_bundle_path` is set, take it verbatim.
        2. Otherwise, fall back to the vendored bundle at
           ``infra/ca/arxiv-ca-bundle.pem`` relative to the repo root.

        Raises ``ValueError`` if the resolved path does not point at
        a regular file. The exception fires at Config-load time
        (before uvicorn binds, before any fetch is attempted) so an
        operator sees the misconfiguration immediately and the
        server cannot silently fall back to the system trust store —
        which would defeat the entire point of the pin.

        No-op when :attr:`pin_arxiv_ca` is ``False`` (the
        safe-by-default flag-off posture).
        """
        if not self.pin_arxiv_ca:
            return self
        # Resolve the bundle path: operator override, else vendored.
        if self.arxiv_ca_bundle_path is not None:
            resolved = self.arxiv_ca_bundle_path
            source = "ARXMCP_ARXIV_CA_BUNDLE_PATH"
        else:
            # Vendored bundle lives at <repo_root>/infra/ca/.
            # ``server/config.py`` → parents[1] is the repo root.
            resolved = (
                Path(__file__).resolve().parents[1]
                / "infra"
                / "ca"
                / "arxiv-ca-bundle.pem"
            )
            source = "vendored bundle"
        if not resolved.is_file():
            raise ValueError(
                f"ARXMCP_PIN_ARXIV_CA=1 but CA bundle not found at "
                f"{resolved!s} ({source}). Refusing to fall back to "
                f"the system trust store — that would defeat the pin. "
                f"Run ``make refresh-arxiv-ca`` to (re)create the "
                f"vendored bundle, or set ARXMCP_ARXIV_CA_BUNDLE_PATH "
                f"to a valid PEM file, or unset ARXMCP_PIN_ARXIV_CA "
                f"to use the system trust store. See "
                f".claude/docs/security-threat-7-audit.md (Threat 7 / "
                f"E13_S07c)."
            )
        # E13_S07c F4 rectification — defense-in-depth: the path
        # exists, but is it a parseable PEM bundle? Without this
        # check, ``arxiv_ca_bundle_path=/etc/passwd`` would pass
        # config-load and fail only at first fetch with an
        # ``ssl.SSLError``. Run the same ``create_default_context``
        # call now (its only side effects are file-read + parse;
        # idempotent). Convert the exception into a ``ValueError``
        # so pydantic wraps it into a ``ValidationError`` at
        # config-load time per the surrounding contract.
        import ssl as _ssl
        try:
            _ssl.create_default_context(cafile=str(resolved))
        except (_ssl.SSLError, OSError) as exc:
            raise ValueError(
                f"ARXMCP_PIN_ARXIV_CA=1 but CA bundle at {resolved!s} "
                f"({source}) is not a parseable PEM file: "
                f"{exc.__class__.__name__}: {exc}. Refusing to fall "
                f"back to the system trust store. Run "
                f"``make refresh-arxiv-ca`` to regenerate the "
                f"vendored bundle, or supply a valid PEM via "
                f"ARXMCP_ARXIV_CA_BUNDLE_PATH."
            ) from exc
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

    @field_validator("log_format")
    @classmethod
    def validate_log_format(cls, v: str) -> str:
        """Log format must be ``"json"`` (default, 12-factor) or ``"text"``
        (human-readable dev output). Normalized to lower-case."""
        normalized = v.strip().lower()
        if normalized not in {"json", "text"}:
            raise ValueError(
                f"ARXMCP_LOG_FORMAT must be 'json' or 'text'; got {v!r}."
            )
        return normalized

    @field_validator("corpus_chunk_count_tolerance")
    @classmethod
    def validate_corpus_chunk_count_tolerance(cls, v: float) -> float:
        """The reconciliation tolerance is a fraction in [0, 1].
        0.0 = exact match required (any delta beyond the 1-row floor
        degrades /readyz); 1.0 = effectively disabled (only a >100%
        delta degrades). Default 0.05 = 5%."""
        if not 0.0 <= v <= 1.0:
            raise ValueError(
                f"ARXMCP_CORPUS_CHUNK_COUNT_TOLERANCE must be in "
                f"[0.0, 1.0]; got {v}."
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
