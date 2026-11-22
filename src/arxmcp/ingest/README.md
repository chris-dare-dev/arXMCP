# ingest/

Ingestion service — separate process from `server/`, single-writer to the indices. Fetches papers, runs the LaTeXML parser, chunks, embeds, and writes new LanceDB versions atomically.

For one-off developer scripts (e.g. seed corpus fetch) see [`tools/`](../tools/) — those live outside `ingest/` because they are not part of the production pipeline.

Design rationale in [`.claude/notes/03-ingestion-pipeline.md`](https://github.com/chris-dare-dev/arXMCP/blob/433ba41ba8710be74d6f99c627dce7d3b5383fca/.claude/notes/03-ingestion-pipeline.md) and [`.claude/notes/04-parsing-and-chunking.md`](https://github.com/chris-dare-dev/arXMCP/blob/433ba41ba8710be74d6f99c627dce7d3b5383fca/.claude/notes/04-parsing-and-chunking.md).
