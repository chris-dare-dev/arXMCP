"""Corpus: what a paper, chunk, notebook and corpus version are, and where they live.

The box above settings. It owns

* identifiers: the paper-id and chunk-id formats, the validator every
  writer runs before building a path from a paper id, and the log-field
  sanitiser (:func:`validate_paper_id`, :func:`sanitize_log_field`);
* the chunk record and its row in the LanceDB ``chunks`` table
  (:class:`ChunkRecord`, :data:`CHUNKER_VERSION`, chunk-id computation,
  routing, the embedding input and the reuse identity);
* the table schemas and the embed record (:class:`EmbedRecord`), and
  the per-paper embeddings layout on disk (:data:`EMBEDDINGS_DIR`);
* the store: writing chunks into a dataset under its write lock, the
  ``corpus-version.json`` marker, deleting a paper
  (:func:`write_chunks`, :func:`dataset_write_lock`, :func:`delete_paper`);
* the reader: opening the ``chunks`` table pinned at a corpus version,
  and the degraded state when it cannot be opened
  (:func:`open_chunks_table`, :func:`read_corpus_version`);
* notebooks: the slug, the notebook directory and its dataset path
  (:func:`notebook_dir`, :func:`notebook_lancedb_path`);
* the formats and locations of the derived indexes it holds itself: the
  theorem-name store (:class:`TheoremNamesStore`) and the Kùzu citation
  graph schema (:func:`apply_schema`);
* the ingest-paused sentinel (:func:`write_pause`, :func:`is_paused`,
  :func:`clear_pause`).

Ingest builds the corpus and the server reads it, both through this
interface. Corpus imports no other ``arxmcp`` box except settings. Other
boxes import from this package root only.
"""

from arxmcp.corpus.chunk import (
    CHUNKER_VERSION,
    EMBED_INPUT_POLICY_VERSION,
    EMBEDDING_DIM,
    ChunkRecord,
    compute_chunk_id,
    compute_textbook_chunk_id,
    embedding_input,
    reusable_vectors,
    reuse_identity,
    route,
    stored_reuse_identity,
    stored_vector,
)
from arxmcp.corpus.embedding import (
    EMBEDDINGS_DIR,
    EMBEDDINGS_MANIFEST_NAME,
    EMBEDDINGS_NPZ_NAME,
    read_embeddings_manifest,
)
from arxmcp.corpus.identifiers import (
    ARXIV_PAPER_ID_RE,
    SOURCE_KIND_ARXIV,
    SOURCE_KIND_TEXTBOOK,
    InvalidPaperIDError,
    is_valid_arxiv_paper_id,
    is_valid_chunk_id,
    is_valid_paper_id,
    paper_id_from_chunk_id,
    paper_id_source_kind,
    sanitize_log_field,
    validate_paper_id,
)
from arxmcp.corpus.kuzudb_schema import apply_schema
from arxmcp.corpus.notebooks import (
    CORPUS_CHUNKS_DIR,
    CORPUS_EMBEDDINGS_DIR,
    CORPUS_PARSED_DIR,
    CORPUS_RAW_DIR,
    NOTEBOOKS_BASE,
    NotebookError,
    notebook_dir,
    notebook_lancedb_path,
    read_paper_ids_from_papers_txt,
    validate_slug,
)
from arxmcp.corpus.reader import (
    CorpusVersionInfo,
    DegradedState,
    open_chunks_table,
    open_chunks_table_with_fallback,
    project_column,
    project_columns,
    read_corpus_version,
)
from arxmcp.corpus.schema import (
    CHUNKS_TABLE_NAME,
    DEFINITIONS_SCHEMA_V1,
    DEFINITIONS_TABLE_NAME,
    EQUATIONS_SCHEMA_V1,
    EQUATIONS_TABLE_NAME,
    LANCE_STORAGE_OPTIONS,
    EmbedRecord,
    add_missing_columns,
)
from arxmcp.corpus.sentinel import clear_pause, is_paused, write_pause
from arxmcp.corpus.store import (
    ALLOWED_KINDS,
    CORPUS_VERSION_MARKER_NAME,
    DEFAULT_LANCEDB_PATH,
    STALE_CHUNKER_EXIT_CODE,
    STORE_STATS_PATH,
    StaleChunkerRowsError,
    WapGateError,
    delete_paper,
    load_embed_record,
    refresh_indices,
    refuse_stale_chunker_rows,
    write_chunks,
)
from arxmcp.corpus.theorem_names_store import (
    TheoremNamesSchemaStale,
    TheoremNamesStore,
    TheoremRow,
    dedup_key,
    normalize_name,
    serialize_section_path,
    theorem_names_db_path,
)
from arxmcp.corpus.write_lock import (
    dataset_write_lock,
    exits_when_write_locked,
    holds_dataset_write_lock,
)

__all__ = [
    "ALLOWED_KINDS",
    "ARXIV_PAPER_ID_RE",
    "CHUNKER_VERSION",
    "CHUNKS_TABLE_NAME",
    "CORPUS_CHUNKS_DIR",
    "CORPUS_EMBEDDINGS_DIR",
    "CORPUS_PARSED_DIR",
    "CORPUS_RAW_DIR",
    "CORPUS_VERSION_MARKER_NAME",
    "DEFAULT_LANCEDB_PATH",
    "DEFINITIONS_SCHEMA_V1",
    "DEFINITIONS_TABLE_NAME",
    "EMBEDDINGS_DIR",
    "EMBEDDINGS_MANIFEST_NAME",
    "EMBEDDINGS_NPZ_NAME",
    "EMBEDDING_DIM",
    "EMBED_INPUT_POLICY_VERSION",
    "EQUATIONS_SCHEMA_V1",
    "EQUATIONS_TABLE_NAME",
    "LANCE_STORAGE_OPTIONS",
    "NOTEBOOKS_BASE",
    "SOURCE_KIND_ARXIV",
    "SOURCE_KIND_TEXTBOOK",
    "STALE_CHUNKER_EXIT_CODE",
    "STORE_STATS_PATH",
    "ChunkRecord",
    "CorpusVersionInfo",
    "DegradedState",
    "EmbedRecord",
    "InvalidPaperIDError",
    "NotebookError",
    "StaleChunkerRowsError",
    "TheoremNamesSchemaStale",
    "TheoremNamesStore",
    "TheoremRow",
    "WapGateError",
    "add_missing_columns",
    "apply_schema",
    "clear_pause",
    "compute_chunk_id",
    "compute_textbook_chunk_id",
    "dataset_write_lock",
    "dedup_key",
    "delete_paper",
    "embedding_input",
    "exits_when_write_locked",
    "holds_dataset_write_lock",
    "is_paused",
    "is_valid_arxiv_paper_id",
    "is_valid_chunk_id",
    "is_valid_paper_id",
    "load_embed_record",
    "normalize_name",
    "notebook_dir",
    "notebook_lancedb_path",
    "open_chunks_table",
    "open_chunks_table_with_fallback",
    "paper_id_from_chunk_id",
    "paper_id_source_kind",
    "project_column",
    "project_columns",
    "read_corpus_version",
    "read_embeddings_manifest",
    "read_paper_ids_from_papers_txt",
    "refresh_indices",
    "refuse_stale_chunker_rows",
    "reusable_vectors",
    "reuse_identity",
    "route",
    "sanitize_log_field",
    "serialize_section_path",
    "stored_reuse_identity",
    "stored_vector",
    "theorem_names_db_path",
    "validate_paper_id",
    "validate_slug",
    "write_chunks",
    "write_pause",
]
