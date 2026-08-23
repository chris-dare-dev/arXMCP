import asyncio, os, sqlite3, sys
from pathlib import Path
sys.path.insert(0, "/Users/chris.dare/Personal/SourceCode/arXMCP")
from server.cache_sqlite import Tier1Store

S = Path("/private/tmp/claude-501/-Users-chris-dare-Personal-SourceCode/1295cdbb-487b-4884-af5b-60198b75dc76/scratchpad/data/cache")
S.mkdir(parents=True, exist_ok=True)


async def case(name, path, prep=None):
    print("\n===== %s =====" % name)
    if prep:
        prep(path)
    try:
        st = await Tier1Store.open(path)
        print("open OK ->", type(st).__name__)
        try:
            await st.close()
        except Exception:
            pass
    except Exception as e:
        print("open EXC:", type(e).__name__, str(e)[:300])


def mk_good(p):
    if p.exists():
        p.unlink()
    c = sqlite3.connect(p)
    c.execute("create table t(x)")
    c.commit()
    c.close()


async def main():
    # K1: garbage bytes in place of a sqlite db
    p = S / "k1.db"
    await case("K1 corrupt (garbage) cache db", p, lambda q: q.write_bytes(b"NOT A SQLITE DB" * 500))
    # K2: valid sqlite header then truncated
    p = S / "k2.db"

    def prep2(q):
        mk_good(q)
        os.truncate(q, 100)
    await case("K2 truncated sqlite db", p, prep2)
    # K3: read-only file
    p = S / "k3.db"

    def prep3(q):
        mk_good(q)
        os.chmod(q, 0o444)
    await case("K3 read-only cache db file", p, prep3)
    # K4: non-writable parent dir, db absent
    d = S / "ro-parent"
    d.mkdir(exist_ok=True)
    os.chmod(d, 0o555)
    await case("K4 non-writable parent dir", d / "k4.db")
    os.chmod(d, 0o755)
    # K5: parent dir does not exist
    await case("K5 missing parent dir", S / "nope" / "deep" / "k5.db")
    # K6: db path is a directory
    dd = S / "k6.db"
    dd.mkdir(exist_ok=True)
    await case("K6 db path is a directory", dd)
    # K7: exclusive lock held by another connection
    p = S / "k7.db"
    mk_good(p)
    holder = sqlite3.connect(p, isolation_level=None)
    holder.execute("PRAGMA locking_mode=EXCLUSIVE")
    holder.execute("BEGIN EXCLUSIVE")
    holder.execute("create table lockme(y)")
    await case("K7 exclusive lock held by another process/conn", p)
    holder.close()

asyncio.run(main())
