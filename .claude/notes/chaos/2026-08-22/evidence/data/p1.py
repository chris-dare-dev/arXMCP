import sys
sys.path.insert(0,"/Users/chris.dare/Personal/SourceCode/arXMCP")
from pathlib import Path
from server.corpus import open_chunks_table, read_corpus_version
S=Path("/private/tmp/claude-501/-Users-chris-dare-Personal-SourceCode/1295cdbb-487b-4884-af5b-60198b75dc76/scratchpad/data")
cv=read_corpus_version(S/"ldb-a"); print("marker:",cv)
t=open_chunks_table(S/"ldb-a", version=cv.version)
print("rows:",t.count_rows())
print("schema:",[ (f.name,str(f.type)[:40]) for f in t.schema])
