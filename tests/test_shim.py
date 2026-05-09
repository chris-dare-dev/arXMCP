"""Integration tests for the arxmcp-shim stdio↔HTTP proxy (E06_S02).

The shim is a subprocess from the test's perspective. Each test
spawns the shim binary (the installed ``arxmcp-shim`` console script)
against a tiny ``http.server`` mock that pretends to be the real
arxmcp-server. Avoids the ~10s BGE-M3 cold load.

Coverage map (acceptance criteria → test class):

  AC                                                Test class
  ──────────────────────────────────────────────────────────────────
  Forwards tools/list end-to-end                    TestShimEndToEnd
  Exits 1 + stderr on /readyz failure               TestProbeFailure
  ≤60 lines (excluding comments + blanks)           TestShimLineCount
  docs/install.md verbatim ~/.claude.json snippet   TestInstallDoc
  Byte-pass-through (no JSON re-serialization)      TestBytePassThrough
  Per-process session-id capture + echo             TestSessionIdHandling
"""

from __future__ import annotations

import ast
import http.server
import json
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIM_PATH = REPO_ROOT / "shim" / "arxmcp_shim.py"
INSTALL_DOC_PATH = REPO_ROOT / "docs" / "install.md"
DESIGN_NOTE_PATH = REPO_ROOT / ".claude" / "notes" / "06-mcp-server-design.md"


# ===========================================================================
# Mock HTTP server fixture
# ===========================================================================


def _free_port() -> int:
    """Allocate an OS-assigned free port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _MockHandler(http.server.BaseHTTPRequestHandler):
    """Per-process mock state lives in class-level dicts so the
    threaded handler shares it with the test fixtures."""

    canned_response_body: bytes = b'{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}'
    canned_session_id: str | None = "test-session-abc123"
    record_requests: list = []

    def log_message(self, *args, **kwargs):  # noqa: D401, ANN002, ANN003
        pass  # silence the default access-log spam

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/readyz":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        n = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(n)
        sid_in = self.headers.get("mcp-session-id")
        type(self).record_requests.append(
            {"path": self.path, "body": body, "session_id": sid_in}
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header(
            "Content-Length", str(len(self.canned_response_body))
        )
        if self.canned_session_id:
            self.send_header("mcp-session-id", self.canned_session_id)
        self.end_headers()
        self.wfile.write(self.canned_response_body)


@pytest.fixture
def mock_server():
    """A threaded mock arxmcp-server on a free port. The handler
    captures every POST so the test can assert byte-equality."""
    _MockHandler.record_requests = []
    _MockHandler.canned_response_body = (
        b'{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}'
    )
    _MockHandler.canned_session_id = "test-session-abc123"
    port = _free_port()
    httpd = http.server.HTTPServer(("127.0.0.1", port), _MockHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield port, httpd
    httpd.shutdown()
    httpd.server_close()


def _spawn_shim(server_url: str, *, stdin_input: bytes = b"", timeout: float = 10.0):
    """Spawn the shim subprocess. Returns CompletedProcess."""
    return subprocess.run(
        [sys.executable, str(SHIM_PATH), "--server", server_url],
        input=stdin_input,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


# ===========================================================================
# AC: forwards tools/list correctly end-to-end
# ===========================================================================


class TestShimEndToEnd:
    def test_tools_list_round_trip(self, mock_server):
        port, _ = mock_server
        url = f"http://127.0.0.1:{port}"
        request_frame = (
            b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
        )
        result = _spawn_shim(url, stdin_input=request_frame + b"\n")
        assert result.returncode == 0, (
            f"shim exited {result.returncode}; stderr={result.stderr!r}"
        )
        # Response is response_body + b"\n" (the shim's stdout framing).
        assert result.stdout == _MockHandler.canned_response_body + b"\n"
        # Mock server saw the request body verbatim (byte-pass-through).
        recorded = _MockHandler.record_requests
        assert len(recorded) == 1
        assert recorded[0]["body"] == request_frame
        assert recorded[0]["path"] == "/mcp/"


# ===========================================================================
# AC: exits 1 with stderr on /readyz probe failure
# ===========================================================================


class TestProbeFailure:
    def test_exit_1_when_server_unreachable(self):
        """No server is running on a random unused port."""
        port = _free_port()  # alloc + close → port is free + unused
        url = f"http://127.0.0.1:{port}"
        result = _spawn_shim(url, timeout=10.0)
        assert result.returncode == 1
        assert b"FATAL:" in result.stderr
        assert b"cannot reach arxmcp-server" in result.stderr or b"not ready" in result.stderr

    def test_exit_1_when_readyz_returns_503(self):
        """Mock that returns 503 from /readyz; shim treats it as
        not-ready and exits."""
        class _NotReadyHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args, **kwargs):
                pass

            def do_GET(self):
                if self.path == "/readyz":
                    self.send_response(503)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(404)
                self.end_headers()

        port = _free_port()
        httpd = http.server.HTTPServer(("127.0.0.1", port), _NotReadyHandler)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            result = _spawn_shim(f"http://127.0.0.1:{port}", timeout=10.0)
            assert result.returncode == 1
            assert b"FATAL:" in result.stderr
            assert b"503" in result.stderr
        finally:
            httpd.shutdown()
            httpd.server_close()


# ===========================================================================
# AC: shim binary ≤60 lines (excluding comments + blank lines)
# ===========================================================================


class TestShimLineCount:
    def test_loc_under_60(self):
        """Per the brief AC. Excludes comments, blank lines, AND
        docstrings — the LOC budget is for executable code logic.
        Module-level and function-level docstrings (the triple-
        quoted blocks) are detected via AST and stripped from the
        count."""
        src = SHIM_PATH.read_text(encoding="utf-8")
        tree = ast.parse(src)
        docstring_lines = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and isinstance(node.body, list)
                and node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                ds = node.body[0]
                for ln in range(ds.lineno, ds.end_lineno + 1):
                    docstring_lines.add(ln)
        loc = sum(
            1
            for i, line in enumerate(src.splitlines(), 1)
            if line.strip()
            and not line.strip().startswith("#")
            and i not in docstring_lines
        )
        assert loc <= 60, f"shim is {loc} effective LOC; cap is 60"


# ===========================================================================
# AC: docs/install.md contains the verbatim ~/.claude.json snippet
# ===========================================================================


class TestInstallDoc:
    def test_install_doc_exists(self):
        assert INSTALL_DOC_PATH.is_file(), (
            f"docs/install.md missing at {INSTALL_DOC_PATH}"
        )

    def test_claude_json_snippet_verbatim(self):
        """The snippet at 06-mcp-server-design.md:19-29 must appear
        verbatim in docs/install.md. The brief AC is a literal-
        string match so a future docs reflow doesn't drift the
        snippet.

        We extract the JSON object content (between the
        ``\\`\\`\\`json`` and ``\\`\\`\\``` fences in the design
        note) and assert byte-for-byte presence in the install doc.
        """
        design_text = DESIGN_NOTE_PATH.read_text(encoding="utf-8")
        # Find the unique fenced ```json ... ``` block in the design
        # note that mentions "arxmcp-shim" — that's the canonical
        # snippet. Extract its inner JSON object.
        in_block = False
        block_lines: list[str] = []
        for line in design_text.splitlines():
            stripped = line.strip()
            if stripped == "```json":
                in_block = True
                block_lines = []
                continue
            if in_block and stripped == "```":
                # End of a block; check if this is the right one.
                content = "\n".join(block_lines)
                if "arxmcp-shim" in content:
                    snippet = content
                    break
                in_block = False
                block_lines = []
                continue
            if in_block:
                block_lines.append(line)
        else:
            raise AssertionError(
                "no ```json fenced block mentioning 'arxmcp-shim' "
                "found in 06-mcp-server-design.md"
            )

        # The snippet is valid JSON.
        parsed = json.loads(snippet)
        assert "mcpServers" in parsed
        assert parsed["mcpServers"]["arxmcp"]["command"] == "arxmcp-shim"

        # The verbatim content (inside-the-fence JSON) must appear in
        # the install doc.
        install_text = INSTALL_DOC_PATH.read_text(encoding="utf-8")
        assert snippet in install_text, (
            "docs/install.md must contain the ~/.claude.json snippet "
            "from 06-mcp-server-design.md verbatim (byte-for-byte)"
        )


# ===========================================================================
# Byte-pass-through invariant (load-bearing risk-note close)
# ===========================================================================


class TestBytePassThrough:
    def test_request_body_byte_equal(self, mock_server):
        """The shim must NOT re-serialize the request body. Sending a
        non-canonical JSON string (extra whitespace, non-alphabetical
        keys) must arrive at the server byte-for-byte unchanged.
        Otherwise tool-schema byte-stability (BP1) breaks."""
        port, _ = mock_server
        url = f"http://127.0.0.1:{port}"
        # Deliberately non-canonical: spaces, non-alpha key order.
        non_canonical = (
            b'{ "jsonrpc": "2.0",  "id": 7, "method": "z_method", "params": {"b": 2, "a": 1} }'
        )
        result = _spawn_shim(url, stdin_input=non_canonical + b"\n")
        assert result.returncode == 0
        recorded = _MockHandler.record_requests
        assert len(recorded) == 1
        assert recorded[0]["body"] == non_canonical, (
            "shim must forward request body bytes verbatim; "
            "re-serialization would break BP1 byte-stability"
        )

    def test_response_body_byte_equal(self, mock_server):
        """Symmetric: the response body bytes from the server must
        appear in stdout exactly (plus trailing \\n)."""
        port, _ = mock_server
        url = f"http://127.0.0.1:{port}"
        # Set a non-canonical response body on the mock.
        non_canonical = b'{"id":1, "result":  {"x":2,"a":1}, "jsonrpc":  "2.0"}'
        _MockHandler.canned_response_body = non_canonical
        result = _spawn_shim(
            url,
            stdin_input=b'{"jsonrpc":"2.0","id":1,"method":"x"}\n',
        )
        assert result.returncode == 0
        assert result.stdout == non_canonical + b"\n"


# ===========================================================================
# Per-process session-id state
# ===========================================================================


class TestSessionIdHandling:
    def test_session_id_captured_and_echoed(self, mock_server):
        """The shim must capture ``mcp-session-id`` from the first
        response that carries it AND echo it on the next request."""
        port, _ = mock_server
        url = f"http://127.0.0.1:{port}"
        # Two requests in one shim process. The first captures the
        # session-id from the mock's response header; the second
        # should echo it.
        two_frames = (
            b'{"jsonrpc":"2.0","id":1,"method":"initialize"}\n'
            b'{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'
        )
        result = _spawn_shim(url, stdin_input=two_frames)
        assert result.returncode == 0
        recorded = _MockHandler.record_requests
        assert len(recorded) == 2
        # First request: no session-id (Claude Code hasn't received
        # one yet).
        assert recorded[0]["session_id"] is None
        # Second request: session-id from the first response.
        assert recorded[1]["session_id"] == "test-session-abc123"

    def test_no_session_id_when_server_omits_header(self, mock_server):
        """If the mock omits the session-id header, the shim does NOT
        invent one and subsequent requests are still session-less."""
        port, _ = mock_server
        url = f"http://127.0.0.1:{port}"
        _MockHandler.canned_session_id = None
        two_frames = (
            b'{"jsonrpc":"2.0","id":1,"method":"x"}\n'
            b'{"jsonrpc":"2.0","id":2,"method":"y"}\n'
        )
        result = _spawn_shim(url, stdin_input=two_frames)
        assert result.returncode == 0
        recorded = _MockHandler.record_requests
        assert len(recorded) == 2
        assert recorded[0]["session_id"] is None
        assert recorded[1]["session_id"] is None
