---
name: tarfile-extractfile-follows-intra-archive-symlinks
description: Python tarfile.extractfile() silently follows SYMTYPE members whose linkname points at another member inside the archive — relevant whenever a tar-consuming CLI reads a manifest BEFORE running a safe-member pre-pass
metadata:
  type: feedback
---

When auditing a tar-bundle consumer that reads a `manifest.json` (or
any "control file") member BEFORE running a safe-member pre-pass over
`tar.getmembers()`, check whether the manifest is read via
`tar.extractfile(member)`. **`tar.extractfile` silently follows
SYMTYPE members whose `linkname` points at another member inside the
same archive** — confirmed live on Python 3.12 (Darwin 25.4.0):

```python
ti = tarfile.TarInfo(name='manifest.json')
ti.type = tarfile.SYMTYPE
ti.linkname = 'other.json'  # other.json is also in the tar
tar.addfile(ti)
# ... later ...
m = tar.getmember('manifest.json')   # finds the symlink
f = tar.extractfile(m)               # silently follows to other.json
f.read()                             # returns other.json's body, no warning
```

A hostile bundle can therefore use a SYMTYPE control file to make the
parsed manifest dict come from an arbitrary member name, bypassing any
"manifest.json must be canonical" intuition.

**Why:** Python `tarfile` resolves intra-archive SYMTYPEs via its
internal `_FileInFile` redirection. The behavior is documented in CPython
source (`Lib/tarfile.py` `extractfile()` follows `_proc_member` for
SYMTYPE chains within the archive's member table) but not prominently in
the stdlib docs. Extra-archive linknames (`/etc/passwd`) raise KeyError
because they aren't members.

**How to apply:** for any tar-consuming CLI critique:

1. Find the FIRST `tar.extractfile(...)` call in `restore_*` /
   `consume_*` / `import_*` style functions.
2. Trace whether a `_safe_member` / `_check_members` / `filter="data"`
   pre-pass has fired against EVERY member yet (including the very
   member being extractfile'd).
3. If the pre-pass runs LATER, this is at minimum a LOW ordering smell.
   The exploit-grade is bounded by what state-mutating side effects
   happen between the manifest-parse and the pre-pass.
4. The fix is cheap: add `if member.issym() or member.islnk(): raise
   ...` at the top of the read-helper. Two lines, defense in depth.

PEP 706's `filter="data"` only applies to `tar.extractall` and
`tar.extract`, NOT to `tar.extractfile` — extractfile is an in-memory
read with NO filter argument. So even projects that pass `filter="data"`
to `extractall` are still exposed to intra-archive symlink-follow on
control-file reads.

See [[escape-on-emit-untested-for-new-wrap-kind]] — same shape (a defense
that does NOT apply to a particular API call), different surface.
