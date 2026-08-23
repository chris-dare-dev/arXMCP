import json, shutil, subprocess, sys
from pathlib import Path
sys.path.insert(0, "/Users/chris.dare/Personal/SourceCode/arXMCP")
from server.corpus import read_corpus_version, open_chunks_table_with_fallback

S = Path("/private/tmp/claude-501/-Users-chris-dare-Personal-SourceCode/1295cdbb-487b-4884-af5b-60198b75dc76/scratchpad/data")
SRC = S / "ldb-a"


def clone(n):
    d = S / n
    if d.exists():
        shutil.rmtree(d)
    subprocess.run(["cp", "-Rc", str(SRC), str(d)], check=True)
    return d


cases = {
    "M1-absent": None,
    "M2-empty": "",
    "M3-invalid-json": "{not json",
    "M4-future-version": json.dumps({"chunk_count": 105, "chunker_version": "v1.0", "created_at": "2099-01-01T00:00:00Z", "embedder_version": "bge-m3@5617a9f6", "paper_count": 1, "version": 999999}),
    "M5-count-mismatch": json.dumps({"chunk_count": 1, "chunker_version": "v1.0", "created_at": "2026-05-21T19:53:41Z", "embedder_version": "bge-m3@5617a9f6", "paper_count": 9999, "version": 181}),
    "M6-wrong-embedder": json.dumps({"chunk_count": 105, "chunker_version": "v9.9", "created_at": "x", "embedder_version": "totally-different-model@ffff", "paper_count": 1, "version": 181}),
}

for i, (name, content) in enumerate(cases.items()):
    d = clone("m%d" % i)
    mp = d / "corpus-version.json"
    if content is None:
        mp.unlink()
    else:
        mp.write_text(content)
    print("\n===== %s =====" % name)
    try:
        print("read_corpus_version:", read_corpus_version(d))
    except Exception as e:
        print("EXC:", type(e).__name__, str(e)[:250])

print("\n===== FALLBACK on C7 corrupt tip manifest =====")
try:
    t, st = open_chunks_table_with_fallback(S / "c7-badmanifest", version=181)
    print("fallback ->", st, "rows:", t.count_rows())
except Exception as e:
    print("EXC:", type(e).__name__, str(e)[:300])

print("\n===== FALLBACK on C4 zeroed fragments =====")
try:
    t, st = open_chunks_table_with_fallback(S / "c4-zeroall", version=181)
    print("fallback ->", st, "rows:", t.count_rows())
    print("search:", [x["chunk_id"][:20] for x in t.search([0.01] * 1024, vector_column_name="embedding_stmt").limit(3).to_list()])
except Exception as e:
    print("EXC:", type(e).__name__, str(e)[:300])
