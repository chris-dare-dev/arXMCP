# ingest/

Ingestion service — separate process from `server/`, single-writer to the indices. Fetches papers, runs the LaTeXML parser, chunks, embeds, and writes new LanceDB versions atomically.

Empty until [E01_S04](../.claude/roadmap/epic-01-vertical-slice.md) (chunker) and [E01_S06](../.claude/roadmap/epic-01-vertical-slice.md) (storage). Production ingestion at scale lands in [E11](../.claude/roadmap/epic-11-ingestion-at-scale.md).

For one-off developer scripts (e.g. seed corpus fetch) see [`tools/`](../tools/) — those live outside `ingest/` because they are not part of the production pipeline.

Design rationale in [`.claude/notes/03-ingestion-pipeline.md`](../.claude/notes/03-ingestion-pipeline.md) and [`.claude/notes/04-parsing-and-chunking.md`](../.claude/notes/04-parsing-and-chunking.md).
