## 2026-05-27 — textbook-ingest-m2 — lancedb-cast-nullability-inference
LanceDB `tbl.add_columns({col: "cast('literal' as string)"})` produces a
column with `nullable=False` because the SQL infers non-null from the
literal. A column declared `nullable=True` in `CHUNKS_SCHEMA_V1` but
migrated via this SQL ends up nullable=False on disk — divergent from a
freshly-created table. Always reproduce schema-migration claims by
building both the fresh and migrated paths and comparing
`tbl.schema.field(col).nullable` across them. Use `alter_columns` or
COALESCE-against-typed-NULL to force nullable=True.

## 2026-05-27 — textbook-ingest-m2 — stale-docstring-anti-pattern
When a milestone "ships X", check that the previous milestone's
docstring that said "X is not yet implemented; do Y workaround" got
retracted. The m1 critique F1 closed exactly this class of issue
(`ingest/schema.py:13-15` lying about `_migrate_chunks_schema_if_needed`
not existing); m2's feat commit reintroduced the same shape because the
docstring still says "Existing-row migration is NOT implemented in this
milestone." Grep the module docstring of any file the milestone is
"completing" — stale claims are a recurring HIGH finding.
