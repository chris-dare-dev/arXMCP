---
name: parseerror-not-runtimeerror-in-except-tuple
description: xml.etree.ElementTree.ParseError is SyntaxError subclass, NOT RuntimeError/OSError; except-tuple that lists "parse failure" as covered is wrong
metadata:
  type: feedback
---

`xml.etree.ElementTree.ParseError` (and `defusedxml.ElementTree.ParseError`) is a subclass of `SyntaxError`, NOT `RuntimeError` or `OSError`. A route that catches `except (RuntimeError, OSError)` and documents "parse failure" in the comment has a gap: malformed XML (e.g. arXiv returning an HTML maintenance page instead of Atom XML) raises `ParseError`, which escapes the tuple and produces a 500.

**Why:** The project already handles this correctly in `server/retrieval/equations.py:133` (`except DET.ParseError as exc`) — that file is the pattern to follow. The route comment saying "parse failure → 502" is believable but wrong.

**How to apply:** On any route that catches `RuntimeError`/`OSError` to handle "network/parse failures" from an XML-parsing call chain, check whether `ET.ParseError` is also in the tuple (or wrapped at source). Verify with `print(ET.ParseError.__mro__)`.

Fix options:
1. Add `ET.ParseError` to the catch tuple in the route.
2. Better: wrap `DET.fromstring(bytes)` in `parse_atom_feed` with `try/except ET.ParseError as e: raise RuntimeError(...) from e` — matches the existing pattern and keeps route catch-tuples unchanged.

See [[escape-on-emit-untested-for-new-wrap-kind]] for the related "doc says covered, code doesn't" class.
