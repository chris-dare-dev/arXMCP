"""The chunk: the one module that declares what a chunk is (chunk-module-m1).

Terms follow ``.claude/CONTEXT.md``; the reuse rules are
``.claude/docs/adr-chunk-identity-and-reuse.md`` (rules 2 and 3; rule 1 is
the next milestone). Everything a caller needs to know about a chunk lives
here and nowhere else:

- the record (:class:`ChunkRecord`) and :data:`CHUNKER_VERSION`;
- the row of the LanceDB ``chunks`` table (:data:`CHUNKS_SCHEMA_V1`,
  :func:`to_row`, :func:`to_arrow_table`, :func:`from_row`) and the
  write-time domains a row is checked against;
- chunk-id computation for arXiv (:func:`_compute_chunk_id`) and textbook
  (:func:`_compute_textbook_chunk_id`) chunks;
- the route of a kind (:func:`route`) and which vector column it fills;
- the embedding input (:func:`embedding_input`) and its policy
  (:data:`EMBED_INPUT_POLICY_VERSION`);
- the reuse identity (:func:`reuse_identity`, :func:`stored_reuse_identity`,
  :func:`reusable_vectors`).

It imports only the standard library and ``pyarrow`` and does no I/O, so any
other ingest module can depend on it without an import cycle. LanceDB, NPZ
and JSON files stay with the store, the embedder and the re-embed driver.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, fields

import pyarrow as pa

# ---------------------------------------------------------------------------
# Versions and dimensions
# ---------------------------------------------------------------------------

# Single source of truth for the chunker version string. Bump this
# constant in lockstep with any change to chunking strategy
# (theorem/proof detection, windowing, section extraction). The value
# flows into every ChunkRecord's ``chunker_version`` field via the
# dataclass default below, into the per-paper ``chunk_manifest.json``
# (written by ``ingest.chunker``), and is what E04_S02's MVCC writer
# uses to detect stale rows.
#
# **Schema-migration constraint (E11_S03).** The CANONICAL-BYTES
# function :func:`_compute_chunk_id` below —
# ``sha256(preamble_text + NFC(body_text))[:16]`` — must remain
# byte-stable across CHUNKER_VERSION bumps: an edit rotates every
# chunk_id even for byte-identical content. That is a SCHEMA migration,
# NOT a chunker_version bump, and the
# ``tests/test_re_embed.py::TestChunkerVersionFreeze`` regression guard
# must be updated in the same change. Vector reuse no longer depends on
# the chunk id (ADR rule 2: it is keyed on the reuse identity below), so
# a rotation costs a copy, not a re-embed.
CHUNKER_VERSION = "v1.2"

# BGE-M3's hidden size (XLM-RoBERTa-large backbone): the width of every
# vector column in the chunks table. ``ingest.embedder`` and
# ``ingest.schema`` re-export it.
EMBEDDING_DIM = 1024

# The named, versioned rule that turns a chunk into its embedding input
# (CONTEXT.md "Embedding input policy"). ``body-first-v1`` is
# ``NFC(body_text)``: it reads only ``body_text``, which every row stores,
# so a stored row's input can always be recomputed (ADR rule 3).
EMBED_INPUT_POLICY_VERSION = "body-first-v1"

# The policy every row embedded before the Bridgeland repair used: the
# preamble was prepended to the body. No row stores the preamble, so a row
# under this policy (or with a NULL policy, which means this one) can never
# have its input recomputed and is never reusable.
LEGACY_EMBED_INPUT_POLICY_VERSION = "preamble-first-v1"


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


@dataclass
class ChunkRecord:
    """One logical chunk emitted by a chunker.

    Attributes
    ----------
    chunk_id:
        Content-addressable identifier
        ``arxiv:<paper_id>:<sha256(preamble_text + NFC(body_text))[:16]>``
        for arXiv chunks (landed in E02_S04), or
        ``textbook:<slug>:<sha256(...)[:16]>`` for textbook chunks
        (textbook-ingest-m1 + m2). The 16-hex-char prefix is stable
        across re-runs of the same paper and changes deterministically
        when either the preamble or the body content changes.
    paper_id:
        Canonical arXiv ID without version suffix (``2307.01156``)
        or textbook paper_id (``textbook:shimura-varieties``).
    kind:
        Chunk type.  Matched theorem+proof pairs yield ``"stmt"`` and
        ``"proof"`` chunks.  Unmatched environments use the LaTeXML subclass
        name (``"lemma"``, ``"corollary"``, ``"definition"``, ``"remark"``,
        ``"example"``, etc.).  Stand-alone prose sections emit ``"section"``.
    section_path:
        Ordered list of section titles from outermost to innermost, e.g.
        ``["3. Main results", "3.2 The flat case"]``.  Empty list when the
        chunk is in the document preamble or top-level prose.
    theorem_name:
        Display name extracted from the theorem heading, e.g.
        ``"Riemann–Roch"`` from ``Theorem 3.1 (Riemann–Roch)``.  ``None``
        for non-theorem environments and when no parenthetical name is
        present.
    theorem_label:
        User-supplied ``\\label{}`` key embedded in the LaTeXML ``id``
        attribute, or ``None`` when LaTeXML auto-generated the id.
    body_text:
        Plain-text extraction of the environment body (no HTML tags).
        A chunk is lossless: an over-long environment becomes several
        parts (``part_index`` / ``part_count``), never a truncated body.
        NOTE: stored bytes are NOT NFC-normalised — the chunk_id hash
        (E02_S04) and the embedding input apply NFC, but the stored
        body_text preserves the parser's exact output. Downstream
        consumers that hash body_text for their own cache keys must
        apply ``unicodedata.normalize("NFC", ...)`` to match the
        chunk_id discipline (F3 closure).
    body_tokens:
        Whitespace-joined math-aware token stream produced by E02_S03's
        ``ingest.tokenizer.tokenize_body``. The string the BM25 index
        (E04_S04) splits at query time. ``None`` only when the chunker
        emitted before E02_S03 wired this field in (legacy artifacts).
    preamble_ref:
        First 16 hex chars of ``SHA-256(preamble_text)`` for the paper's
        per-paper preamble (E02_S02). ``None`` when preamble extraction
        failed for the paper (F3 fallback in E02_S02). The embedding
        input no longer reads the preamble (``body-first-v1``).
    chunker_version:
        Stable version string for the chunking strategy. Defaults to
        :data:`CHUNKER_VERSION`. Bump the constant when chunking changes.
    truncated:
        ``True`` when a body was shortened. The store refuses such a chunk
        (a chunk is lossless); kept so legacy artifacts are recognisable.

    Textbook-specific fields (textbook-ingest-m2). All optional; the
    arXiv chunking path leaves them at their defaults, and the schema
    enforces ``source_kind="arxiv"`` + ``license="arxiv-license"`` as
    the arXiv-corpus defaults.

    source_kind:
        ``"arxiv"`` (default) or ``"textbook"``. Discriminates the
        chunk's origin corpus. Mirrored on the LanceDB ``source_kind``
        column for downstream filtering.
    license:
        Free-text license token. Default ``"arxiv-license"`` for
        arXiv chunks; textbook chunks carry the textbook's license
        (e.g. ``"GFDL"`` for Stacks Project, ``"author-distributed"``
        for lecture notes, etc.). Documentary only; no license value gates serving (the
        ``truncated_for_license`` / e5 truncation gate was removed in
        license-serving-removal-m1).
    chapter:
        Textbook chapter name (``"Chapter 3: Schemes"``) or ``None``
        for arXiv.
    page_start, page_end:
        Inclusive page range for textbook chunks. ``None`` for arXiv.
    textbook_slug:
        Notebook slug (``"shimura-varieties"``) for textbook chunks;
        redundant with ``paper_id = "textbook:<slug>"`` but enables
        a scalar-index filter without string-splitting at query time.
        ``None`` for arXiv.
    parser_used:
        Per-chunk parser provenance, one of :data:`ALLOWED_PARSER_USED`
        or ``None`` for unknown / failure.
    printed_number:
        Rendered theorem number ("3.1", "A.2", "1.5.1"); ``None`` when
        genuinely unnumbered. Independent of ``theorem_label`` and of the
        chunk id, so populating it never rotates a chunk_id.
    part_index, part_count, source_start, source_end:
        Lossless windowing provenance: which part of how many, and the
        character span of ``body_text`` in its source when known.
    """

    chunk_id: str
    paper_id: str
    kind: str
    section_path: list[str]
    theorem_name: str | None
    theorem_label: str | None
    body_text: str
    # E02_S03 populates this with a whitespace-joined string produced by
    # `ingest.tokenizer.tokenize_body`. The annotation is `str | None`
    # (NOT `list[str] | None`) to match the LanceDB schema's `string`
    # column type — E04_S04's BM25 indexer does `body_tokens.split()`.
    body_tokens: str | None = field(default=None)
    preamble_ref: str | None = field(default=None)
    chunker_version: str = field(default=CHUNKER_VERSION)
    truncated: bool = field(default=False)
    # ---- textbook-ingest-m2 fields ----
    source_kind: str = field(default="arxiv")
    license: str = field(default="arxiv-license")
    chapter: str | None = field(default=None)
    page_start: int | None = field(default=None)
    page_end: int | None = field(default=None)
    textbook_slug: str | None = field(default=None)
    parser_used: str | None = field(default=None)
    # ---- source-truth-m2 field (chunks schema v2) ----
    printed_number: str | None = field(default=None)
    # ---- Bridgeland repair: lossless parts ----
    part_index: int = field(default=1)
    part_count: int = field(default=1)
    source_start: int | None = field(default=None)
    source_end: int | None = field(default=None)

    def to_dict(self) -> dict:
        """Serialise to a JSON-safe dict with keys in sorted order."""
        return {
            "body_text": self.body_text,
            "body_tokens": self.body_tokens,
            "chapter": self.chapter,
            "chunk_id": self.chunk_id,
            "chunker_version": self.chunker_version,
            "kind": self.kind,
            "license": self.license,
            "page_end": self.page_end,
            "page_start": self.page_start,
            "paper_id": self.paper_id,
            "parser_used": self.parser_used,
            "part_count": self.part_count,
            "part_index": self.part_index,
            "preamble_ref": self.preamble_ref,
            "printed_number": self.printed_number,
            "section_path": self.section_path,
            "source_end": self.source_end,
            "source_kind": self.source_kind,
            "source_start": self.source_start,
            "textbook_slug": self.textbook_slug,
            "theorem_label": self.theorem_label,
            "theorem_name": self.theorem_name,
            "truncated": self.truncated,
        }


# ---------------------------------------------------------------------------
# Chunk ids
# ---------------------------------------------------------------------------
#
# The "preamble" slot is a position value, passed through byte-for-byte:
# the arXiv HTML chunker passes the paper preamble (or ""), the TeX chunker
# ``tex-offset:<n>``, the textbook HTML chunker "", the textbook Markdown
# chunker the raw ``"\x00".join(section_path)`` and the textbook PDF
# chunker ``<paper_id>:page:<n>:offset:<m>``. Normalising or harmonising
# any of them rotates every affected id.
#
# ``_compute_chunk_id`` is source-pinned by
# ``tests/test_re_embed.py::TestChunkerVersionFreeze`` (through its
# ``ingest.chunker`` re-export): keep it byte-identical, docstring included.


def _compute_chunk_id(paper_id: str, preamble_text: str, body_text: str) -> str:
    """Return ``arxiv:<paper_id>:<sha256(preamble_text + NFC(body_text))[:16]>``.

    The hash input is ``preamble_text + NFC(body_text)`` UTF-8-encoded.
    ``preamble_text`` is already NFC (preamble.py applies F6's
    normalization at extraction time); ``body_text`` is NFC-normalised
    here for the hash but the stored ``chunk.body_text`` is left
    unchanged. This is the same discipline ``tokenize_body`` uses.

    The 16-hex-char prefix is 64 bits of entropy. At the project's 200K-
    paper end state (~20M chunks), the birthday-bound collision
    probability is ≈ 1.1×10⁻⁵ — negligible for a retrieval system, and
    we additionally fail loudly on any duplicate ``chunk_id`` per paper
    (see ``_chunk_paper_impl``).

    When the per-paper preamble is missing (extraction failed; F3
    fallback), ``preamble_text`` is ``""``. The hash then depends only
    on ``body_text``, which still keeps the chunk_id content-addressable
    and stable across re-runs of the same paper.
    """
    body_normalized = unicodedata.normalize("NFC", body_text)
    digest = hashlib.sha256(
        (preamble_text + body_normalized).encode("utf-8")
    ).hexdigest()[:16]
    return f"arxiv:{paper_id}:{digest}"


def _compute_textbook_chunk_id(
    slug: str, preamble_text: str, body_text: str
) -> str:
    """Return ``textbook:<slug>:<sha256(preamble_text + NFC(body_text))[:16]>``.

    Identical hash discipline to :func:`_compute_chunk_id` (NFC-normalize
    body, UTF-8 encode, 16-hex prefix) but emits the ``textbook:`` prefix
    so the id round-trips through ``ingest.identifiers.CHUNK_ID_PATTERN``.
    ``preamble_text`` is the caller's position value: identical text
    recurs at different places in one textbook (ADR rule 1).
    """
    body_normalized = unicodedata.normalize("NFC", body_text)
    digest = hashlib.sha256(
        (preamble_text + body_normalized).encode("utf-8")
    ).hexdigest()[:16]
    return f"textbook:{slug}:{digest}"


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

#: Names of the two dual-encoding vector columns, in canonical search
#: order (stmt first, proof second, as declared in
#: :data:`CHUNKS_SCHEMA_V1`). ``ingest.schema`` re-exports this, so
#: readers that enumerate the searchable vector columns import it
#: rather than literalize the names (E05_S02 F3).
EMBEDDING_COLUMN_NAMES = ("embedding_stmt", "embedding_proof")

# Which vector column each route fills. The other column is NULL.
_ROUTE_COLUMNS = dict(zip(("stmt", "proof"), EMBEDDING_COLUMN_NAMES, strict=True))


def route(kind: str | None) -> str:
    """Return the route of a chunk of ``kind``: ``"proof"`` or ``"stmt"``.

    Proof chunks are embedded in the proof space and stored in
    ``embedding_proof``; every other kind in the statement space and
    ``embedding_stmt``. A chunk id does not hash its kind, so one id can
    come back from a re-chunk on the other route: the route is part of
    the reuse identity for exactly that reason.
    """
    return "proof" if kind == "proof" else "stmt"


# ---------------------------------------------------------------------------
# Embedding input
# ---------------------------------------------------------------------------


def embedding_input(body_text: str) -> str:
    """Return the exact text the embedder sees for a chunk.

    Under :data:`EMBED_INPUT_POLICY_VERSION` (``body-first-v1``) this is
    ``NFC(body_text)``: the stored body is left raw (NFC is applied for
    the model only), and nothing else (no preamble, no heading) reaches
    the embedder. Because it reads only ``body_text``, a stored row's
    input can be recomputed from the row alone (ADR rule 3).
    """
    return unicodedata.normalize("NFC", body_text)


# ---------------------------------------------------------------------------
# Reuse identity (ADR rules 2 and 3)
# ---------------------------------------------------------------------------

#: First field of every reuse-identity digest. Changing the encoding below
#: means bumping this tag, so a new digest can never equal an old one.
REUSE_IDENTITY_SCHEME = "chunk-reuse-identity/v1"


def _digest(*parts: str) -> str:
    # Each part is length-prefixed (8-byte big-endian byte count), so no
    # two different part tuples share an encoding: a joined string with a
    # separator would let ("a|b", "c") collide with ("a", "b|c"). The
    # full 64-hex digest is kept: a collision here would silently serve
    # the wrong vector.
    h = hashlib.sha256()
    for part in parts:
        encoded = part.encode("utf-8")
        h.update(len(encoded).to_bytes(8, "big"))
        h.update(encoded)
    return h.hexdigest()


def reuse_identity(kind: str, body_text: str, *, embedder_version: str) -> str:
    """Return the reuse identity of a chunk embedded now.

    The identity hashes exactly what ADR rule 2 names: the embedding
    input, the embedder version, the embedding input policy (the current
    one: a freshly chunked chunk is always embedded under it) and the
    route. It never hashes the chunk id, the paper id or the chunker
    version, so a chunk id rotation keeps the identity and costs a copy.
    """
    if not embedder_version:
        raise ValueError("reuse identity needs a non-empty embedder_version")
    return _digest(
        REUSE_IDENTITY_SCHEME,
        embedder_version,
        EMBED_INPUT_POLICY_VERSION,
        route(kind),
        embedding_input(body_text),
    )


def stored_reuse_identity(row: Mapping[str, object]) -> str | None:
    """Return the reuse identity of a stored ``chunks`` row, or ``None``.

    Recomputed only from the row's own ``body_text``, ``kind``,
    ``embedder_version`` and ``embed_input_policy_version`` (ADR rule 3).
    ``None`` means the row's vector is not reusable: its policy is NULL
    (a pre-repair row, which means :data:`LEGACY_EMBED_INPUT_POLICY_VERSION`),
    legacy or unknown, so its input cannot be recomputed from what the
    row stores — never "assume the current policy".
    """
    if row.get("embed_input_policy_version") != EMBED_INPUT_POLICY_VERSION:
        return None
    kind = row.get("kind")
    body_text = row.get("body_text")
    embedder_version = row.get("embedder_version")
    if not (
        isinstance(kind, str)
        and isinstance(body_text, str)
        and isinstance(embedder_version, str)
        and embedder_version
    ):
        return None
    return reuse_identity(kind, body_text, embedder_version=embedder_version)


def stored_vector(row: Mapping[str, object]) -> Sequence[float] | None:
    """Return the vector a stored row carries on its kind's route, or ``None``.

    A row whose vector sits in the other route's column (the 7b160a0 bug
    class) has no vector on its own route and so reads as ``None``.
    """
    kind = row.get("kind")
    return row.get(_ROUTE_COLUMNS[route(kind if isinstance(kind, str) else None)])


def reusable_vectors(
    rows: Iterable[Mapping[str, object]],
) -> dict[str, Sequence[float]]:
    """Index stored rows by reuse identity: ``identity -> vector``.

    A row is left out when it is not reusable: no identity
    (:func:`stored_reuse_identity` is ``None``) or no vector on its route.
    When two rows share an identity (a body repeated at two places), the
    row with the lowest chunk id wins, so a run reproduces. Either vector
    is valid for that identity.
    """
    chosen: dict[str, tuple[str, Sequence[float]]] = {}
    for row in rows:
        identity = stored_reuse_identity(row)
        vector = stored_vector(row)
        if identity is None or vector is None:
            continue
        chunk_id = str(row.get("chunk_id") or "")
        held = chosen.get(identity)
        if held is None or chunk_id < held[0]:
            chosen[identity] = (chunk_id, vector)
    return {identity: vector for identity, (_cid, vector) in chosen.items()}


# ---------------------------------------------------------------------------
# The chunks-table row
# ---------------------------------------------------------------------------

# The risk note in the E04_S01 brief is explicit: "Nullable columns
# for ``embedding_eq`` must be declared in PyArrow as
# ``pa.field("embedding_eq", pa.list_(pa.float32(), 1024),
# nullable=True)`` — omitting nullability would cause Arrow errors on
# insertion." We declare every nullable field with ``nullable=True``
# and every required field with ``nullable=False``. Column order is a
# fixed source literal so the schema bytes are deterministic (BP1).
CHUNKS_SCHEMA_V1 = pa.schema(
    [
        # Identity columns (all required).
        pa.field("chunk_id", pa.utf8(), nullable=False),
        pa.field("paper_id", pa.utf8(), nullable=False),
        pa.field("kind", pa.utf8(), nullable=False),
        # Section breadcrumb (always present, may be empty list).
        pa.field("section_path", pa.list_(pa.utf8()), nullable=False),
        # Theorem metadata (nullable when not a theorem environment).
        pa.field("theorem_name", pa.utf8(), nullable=True),
        pa.field("theorem_label", pa.utf8(), nullable=True),
        # Content payload (always present).
        pa.field("body_text", pa.utf8(), nullable=False),
        # ``body_tokens`` is non-nullable here even though
        # ``ChunkRecord.body_tokens: str | None`` allows None for legacy
        # pre-E02_S03 chunks. :func:`to_row` raises ``ValueError`` on a
        # None at write time.
        pa.field("body_tokens", pa.utf8(), nullable=False),
        # Dual-column dense embeddings. Nullable per the dual-encoding
        # contract: ``kind="proof"`` chunks have ``embedding_proof``
        # populated and ``embedding_stmt`` NULL; everything else has
        # ``embedding_stmt`` populated and ``embedding_proof`` NULL. The
        # column a chunk's vector belongs in is its :func:`route`.
        pa.field(
            "embedding_stmt",
            pa.list_(pa.float32(), EMBEDDING_DIM),
            nullable=True,
        ),
        pa.field(
            "embedding_proof",
            pa.list_(pa.float32(), EMBEDDING_DIM),
            nullable=True,
        ),
        # ``embedding_eq`` is reserved for E10_S03 (equation embeddings).
        # The embedder NEVER populates this; every row :func:`to_row`
        # builds has ``embedding_eq=None``.
        pa.field(
            "embedding_eq",
            pa.list_(pa.float32(), EMBEDDING_DIM),
            nullable=True,
        ),
        # Versioning columns (required). ``chunker_version`` flows from
        # ``ChunkRecord.chunker_version``; ``embedder_version`` flows from
        # the embedder's ``EMBEDDER_VERSION`` constant via ``EmbedRecord``.
        pa.field("chunker_version", pa.utf8(), nullable=False),
        pa.field("embedder_version", pa.utf8(), nullable=False),
        # ``preamble_ref`` is the SHA-256[:16] of the per-paper preamble;
        # NULL when preamble extraction failed (F3 fallback in E02_S02).
        pa.field("preamble_ref", pa.utf8(), nullable=True),
        # ---- textbook-ingest-m2 columns ----
        # All declared nullable=True so a freshly-created table at
        # this schema version accepts arXiv-only writes (NULL for the
        # textbook-specific columns). The in-place schema-evolution
        # migration that backfills these on a pre-m2 LanceDB table is
        # the work of ``textbook-ingest-m2`` proper — NOT bundled with
        # ``embedder-truncation-m1`` even though that milestone
        # incorporated the schema additions. New writes always populate
        # ``source_kind`` and ``license`` (from ``ChunkRecord``
        # defaults); the four textbook-only columns stay NULL for
        # arXiv chunks.
        #
        # ``source_kind`` enum domain: {"arxiv", "textbook"}. Enforced
        # at write time in :func:`to_row` against :data:`ALLOWED_SOURCE_KINDS`.
        pa.field("source_kind", pa.utf8(), nullable=True),
        # ``license`` is free-text — domain is documentary, not
        # validated. Default ``"arxiv-license"`` for arXiv chunks;
        # textbook chunks carry the textbook's specific license token
        # (``"GFDL"`` for Stacks Project, ``"author-distributed"`` for
        # lecture notes, etc.). licensing gates no serving
        # decision — the ``truncated_for_license`` / e5 truncation gate was
        # removed in license-serving-removal-m1.
        pa.field("license", pa.utf8(), nullable=True),
        # Textbook chapter name (``"Chapter 3: Schemes"``). NULL for
        # arXiv chunks; populated by the textbook chunker (e3).
        pa.field("chapter", pa.utf8(), nullable=True),
        # Inclusive page range for textbook chunks. NULL for arXiv.
        pa.field("page_start", pa.int32(), nullable=True),
        pa.field("page_end", pa.int32(), nullable=True),
        # Notebook slug for textbook chunks (``"shimura-varieties"``).
        # Redundant with ``paper_id = "textbook:<slug>"`` but enables a
        # scalar-index filter without string-splitting at query time.
        # NULL for arXiv chunks.
        pa.field("textbook_slug", pa.utf8(), nullable=True),
        # Per-chunk parser provenance. Domain: :data:`ALLOWED_PARSER_USED`,
        # enforced at write time in :func:`to_row`. NULL = unknown /
        # failure. Promoted from ``PaperOutcome`` in m2 so chunk-grain
        # re-parse decisions are possible.
        pa.field("parser_used", pa.utf8(), nullable=True),
        # ---- source-truth-m2 columns (chunks schema v2) ----
        # All five declared nullable=True: a freshly-created table
        # accepts writes that leave the registry-derived columns NULL,
        # and the in-place migration of pre-v2 rows
        # (``_migrate_chunks_schema_if_needed``) rides the same SQL-dict
        # ``add_columns`` loop as the textbook columns above — one
        # ``cast(NULL as ...)`` default each, NO struct branch (spike-4).
        #
        # ``source_revision_id`` — the authoritative pointer to the
        # per-revision documents-registry row (source-truth-m1), stored
        # as ``f"{work_id}@{arxiv_version}"`` or the bare ``work_id`` when
        # unversioned (the ``notebook_documents_backfill._label`` form).
        # NULL when the chunk's paper is unregistered or the registry has
        # >1 row for the work (defensive abstention). Hydrated by the
        # backfill; a plain new write leaves it NULL (forward-wiring is a
        # tracked fast-follow — no new-ingest driver consults the
        # per-notebook registry yet).
        pa.field("source_revision_id", pa.utf8(), nullable=True),
        # ``source_span`` — a JSON *string* (NOT a struct, so it rides the
        # SQL-dict migration path unmodified), byte-stable via
        # ``json.dumps(sort_keys=True, separators=(",", ":"))``. Shape:
        # ``{"rev":<16-hex parse_artifact_sha256 prefix>,
        #    "txt":<64-hex sha256(NFC(ws-collapsed body_text))>,
        #    "id":<source element id or "">}``. ``txt`` is the
        # authoritative resolving key (spike-3); ``rev`` is a redundant
        # cross-check; ``id`` is a non-authoritative debug hint. NULL when
        # ``source_revision_id`` is unresolved OR the backfill's chunk-id
        # re-derivation did not reproduce this row (abstention, counted).
        pa.field("source_span", pa.utf8(), nullable=True),
        # ``truncated`` — persists ``ChunkRecord.truncated`` (previously
        # computed at ingest but dropped at ``_build_arrow_table``). The
        # ONLY v2 column with no legitimate NULL path once hydrated: the
        # backfill fills it for 100% of rows (exact on a chunk-id hit,
        # else a safe-direction token recount vs ``STMT_MAX_TOKENS`` /
        # unconditional False for ``kind="proof"``).
        pa.field("truncated", pa.bool_(), nullable=True),
        # ``printed_number`` — the rendered theorem number ("3.1", "A.2",
        # "1.5.1") extracted by ``ingest.chunker._extract_printed_number``
        # from the ``ltx_tag_theorem`` heading text. Chunker-native (every
        # new theorem-like/proof chunk gets it). NULL when genuinely
        # unnumbered (F1), for ``kind`` in {proof-orphan, section}, or when
        # the backfill's chunk-id match missed.
        pa.field("printed_number", pa.utf8(), nullable=True),
        # ``license_ref`` — the matched registry row's ``license_status``
        # value denormalized onto the chunk row (``eligible`` /
        # ``not-allowlisted-open`` / ``unknown``), NOT a second pointer.
        # ADVISORY: changes no serving behavior until the owner-gated m4
        # cutover. NULL exactly when ``source_revision_id`` is NULL.
        pa.field("license_ref", pa.utf8(), nullable=True),
        # Bridgeland corpus repair: the embedding input policy the row's
        # vector was computed under (NULL on pre-repair rows, read as
        # :data:`LEGACY_EMBED_INPUT_POLICY_VERSION`, never reusable) and
        # lossless window provenance. Added at the tail for schema evolution.
        pa.field("embed_input_policy_version", pa.utf8(), nullable=True),
        pa.field("part_index", pa.int32(), nullable=True),
        pa.field("part_count", pa.int32(), nullable=True),
        pa.field("source_start", pa.int32(), nullable=True),
        pa.field("source_end", pa.int32(), nullable=True),
    ]
)

#: The closed set of kinds a chunker emits. PyArrow has no enum, so
#: :func:`to_row` refuses a typo (``"theroem"``) that would otherwise
#: land and break routing. The serving side derives its proof-route
#: exclusion list from this set (``server/handlers/search.py`` via the
#: ``ingest.store.ALLOWED_KINDS`` re-export).
ALLOWED_KINDS: frozenset[str] = frozenset(
    {
        "stmt",
        "proof",
        "section",
        "definition",
        "lemma",
        "proposition",
        "corollary",
        "remark",
        "example",
        "claim",
        "conjecture",
        "fact",
        "hypothesis",
        "observation",
        "problem",
        "question",
        "exercise",
        "assumption",
        "convention",
        "notation",
        "theorem",
    }
)

#: Domain of ``source_kind``. The chunk-id prefix must equal
#: ``source_kind + ":"`` (see :func:`to_row`).
ALLOWED_SOURCE_KINDS: frozenset[str] = frozenset({"arxiv", "textbook"})

#: Domain of a non-NULL ``parser_used``.
ALLOWED_PARSER_USED: frozenset[str] = frozenset(
    {"ar5iv", "latexml", "mineru+latexml", "mineru+markdown", "pdftotext", "tex"}
)

# Record fields that admit no None: a row may not leave their column NULL
# when it is mapped back to a record (derived from the annotations so a new
# field cannot be forgotten here).
_RECORD_FIELDS = tuple(f.name for f in fields(ChunkRecord))
_REQUIRED_RECORD_FIELDS = frozenset(
    f.name
    for f in fields(ChunkRecord)
    if "None" not in str(f.type).replace(" ", "").split("|")
)
_NON_NULLABLE_COLUMNS = tuple(f.name for f in CHUNKS_SCHEMA_V1 if not f.nullable)


def _check_record(record: ChunkRecord) -> None:
    """Refuse a record the chunks table must not hold (messages are pinned)."""
    if record.truncated:
        raise ValueError(
            f"chunk {record.chunk_id} has truncated=true; "
            "re-chunk the source with no-loss windows before storage"
        )
    if record.body_tokens is None:
        # D8: body_tokens=None is a real bug (E02_S03 has shipped).
        raise ValueError(
            f"chunk {record.chunk_id} has body_tokens=None; "
            "E02_S03 is required and must have populated this field"
        )
    if record.kind not in ALLOWED_KINDS:
        raise ValueError(
            f"chunk {record.chunk_id} has kind={record.kind!r} which "
            f"is not in the allowed set {sorted(ALLOWED_KINDS)!r}"
        )
    if record.source_kind not in ALLOWED_SOURCE_KINDS:
        raise ValueError(
            f"chunk {record.chunk_id} has source_kind="
            f"{record.source_kind!r} which is not in the allowed "
            f"set {sorted(ALLOWED_SOURCE_KINDS)!r}"
        )
    # textbook-ingest-m9 / e4 rect F6: the dense path filters on the
    # source_kind COLUMN while the BM25 path infers it from the chunk_id
    # PREFIX (server/retrieval/bm25.py); they must agree.
    expected_prefix = f"{record.source_kind}:"
    if not record.chunk_id.startswith(expected_prefix):
        raise ValueError(
            f"chunk {record.chunk_id} has source_kind="
            f"{record.source_kind!r} but its chunk_id does not start "
            f"with the matching prefix {expected_prefix!r}; the "
            f"chunk_id prefix and source_kind column must agree so "
            f"the dense (column) and BM25 (prefix) retrieval paths "
            f"classify the chunk identically"
        )
    if record.parser_used is not None and record.parser_used not in ALLOWED_PARSER_USED:
        raise ValueError(
            f"chunk {record.chunk_id} has parser_used="
            f"{record.parser_used!r} which is not in the allowed "
            f"set {sorted(ALLOWED_PARSER_USED)!r} (or None for "
            f"failure/unknown)"
        )


def to_row(
    record: ChunkRecord,
    vector: Sequence[float],
    *,
    embedder_version: str,
    policy: str,
) -> dict[str, object]:
    """Map a record and its one vector to a ``chunks`` row.

    The vector is placed by the record's route, so a statement-route
    vector cannot land on a proof row: the caller hands over a vector, not
    a column. ``embedding_eq`` and the three registry-derived columns
    (``source_revision_id``, ``source_span``, ``license_ref``) are NULL on
    a new write; ``tools/notebook_chunks_backfill.py`` hydrates the latter.
    """
    _check_record(record)
    column = _ROUTE_COLUMNS[route(record.kind)]
    if len(vector) != EMBEDDING_DIM:
        raise ValueError(
            f"chunk {record.chunk_id}: {column} vector has {len(vector)} "
            f"values, expected {EMBEDDING_DIM}"
        )
    row: dict[str, object] = {name: getattr(record, name) for name in _RECORD_FIELDS}
    row["section_path"] = list(record.section_path)
    row.update(
        {
            "embedding_stmt": None,
            "embedding_proof": None,
            "embedding_eq": None,
            "embedder_version": embedder_version,
            "embed_input_policy_version": policy,
            "source_revision_id": None,
            "source_span": None,
            "license_ref": None,
        }
    )
    row[column] = vector
    return row


def _check_row(row: Mapping[str, object]) -> None:
    # pyarrow neither enforces nullable=False nor rejects unknown keys
    # (it drops them and NULLs the missing ones), and LanceDB's merge_insert
    # reports a NULL in a required column only as an opaque spill error.
    names = CHUNKS_SCHEMA_V1.names
    missing = [name for name in names if name not in row]
    extra = sorted(set(row) - set(names))
    if missing or extra:
        raise ValueError(
            f"chunks row {row.get('chunk_id')!r} does not match CHUNKS_SCHEMA_V1: "
            f"missing column(s) {missing}, unexpected column(s) {extra}"
        )
    for name in _NON_NULLABLE_COLUMNS:
        if row[name] is None:
            raise ValueError(
                f"chunks row {row.get('chunk_id')!r}: column {name!r} is "
                f"non-nullable but is NULL"
            )


def to_arrow_table(rows: Iterable[Mapping[str, object]]) -> pa.Table:
    """Build a :data:`CHUNKS_SCHEMA_V1` table from ``chunks`` rows.

    Every row must carry exactly the schema's columns and no NULL in a
    non-nullable one; the error names the column. ``rows`` is read once,
    so a generator yields the same table as a list.
    """
    materialized = [dict(row) for row in rows]
    for row in materialized:
        _check_row(row)
    return pa.Table.from_pylist(materialized, schema=CHUNKS_SCHEMA_V1)


def from_row(row: Mapping[str, object]) -> ChunkRecord:
    """Map a ``chunks`` row (as from ``to_pylist()``) back to a record.

    Reads only the record's own columns; the vectors, versions and
    registry-derived columns stay on the row. A NULL (or absent) column
    whose record field admits no None raises, naming the column — a
    migrated legacy row with NULL ``truncated`` or ``part_index`` is not
    silently given a default.
    """
    values: dict[str, object] = {}
    for name in _RECORD_FIELDS:
        value = row.get(name)
        if value is None and name in _REQUIRED_RECORD_FIELDS:
            raise ValueError(
                f"chunks row {row.get('chunk_id')!r}: column {name!r} is NULL "
                f"but ChunkRecord.{name} does not admit None"
            )
        values[name] = list(value) if name == "section_path" else value
    return ChunkRecord(**values)


__all__ = [
    "ALLOWED_KINDS",
    "ALLOWED_PARSER_USED",
    "ALLOWED_SOURCE_KINDS",
    "CHUNKER_VERSION",
    "CHUNKS_SCHEMA_V1",
    "EMBEDDING_COLUMN_NAMES",
    "EMBEDDING_DIM",
    "EMBED_INPUT_POLICY_VERSION",
    "LEGACY_EMBED_INPUT_POLICY_VERSION",
    "REUSE_IDENTITY_SCHEME",
    "ChunkRecord",
    "embedding_input",
    "from_row",
    "reusable_vectors",
    "reuse_identity",
    "route",
    "stored_reuse_identity",
    "stored_vector",
    "to_arrow_table",
    "to_row",
]
