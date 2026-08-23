import json, os, shutil, subprocess, sys
from pathlib import Path
sys.path.insert(0,"/Users/chris.dare/Personal/SourceCode/arXMCP")
from server.corpus import open_chunks_table, read_corpus_version, open_chunks_table_with_fallback
S=Path("/private/tmp/claude-501/-Users-chris-dare-Personal-SourceCode/1295cdbb-487b-4884-af5b-60198b75dc76/scratchpad/data")
SRC=S/"ldb-a"
def clone(n):
    d=S/n
    if d.exists(): shutil.rmtree(d)
    subprocess.run(["cp","-Rc",str(SRC),str(d)],check=True); return d
def probe(d,label,ver=None):
    print(f"\n########## {label} ##########")
    try:
        cv=read_corpus_version(d); print("marker:",cv)
    except Exception as e:
        print("marker EXC:",type(e).__name__,str(e)[:250]); cv=None
    v = ver if ver is not None else (cv.version if cv else None)
    try:
        t=open_chunks_table(d,version=v); print("open OK v=",v)
    except Exception as e:
        print("open EXC:",type(e).__name__,str(e)[:250]); return
    for nm,fn in (("count_rows",lambda: t.count_rows()),
                  ("search5",lambda: [x["chunk_id"][:30] for x in t.search([0.01]*1024,vector_column_name="embedding_stmt").limit(5).to_list()]),
                  ("to_arrow_rows",lambda: t.to_arrow().num_rows)):
        try: print(f"{nm}:",fn())
        except Exception as e: print(f"{nm} EXC:",type(e).__name__,str(e)[:250])

# C4: zero ALL data fragments
d=clone("c4-zeroall")
n=0
for f in (d/"chunks.lance/data").iterdir():
    sz=f.stat().st_size; f.write_bytes(b"\x00"*sz); n+=1
print(f"[C4] zeroed {n} fragments")
probe(d,"C4 ALL data fragments zeroed")

# C5: truncate ALL data fragments to 40%
d=clone("c5-truncall")
for f in (d/"chunks.lance/data").iterdir():
    os.truncate(f, max(1,f.stat().st_size*4//10))
print("[C5] truncated all fragments to 40%")
probe(d,"C5 ALL data fragments truncated to 40%")

# C6: delete the tip manifest only
d=clone("c6-delmanifest")
mp=d/"chunks.lance/_versions/18446744073709551434.manifest"
print("[C6] deleting", mp.name, mp.exists()); mp.unlink()
probe(d,"C6 tip manifest for v181 deleted")

# C7: corrupt tip manifest (flip half the bytes to 0xff)
d=clone("c7-badmanifest")
mp=d/"chunks.lance/_versions/18446744073709551434.manifest"
b=bytearray(mp.read_bytes());
for i in range(0,len(b),3): b[i]=0xff
mp.write_bytes(bytes(b))
print("[C7] corrupted manifest bytes")
probe(d,"C7 tip manifest corrupted")
