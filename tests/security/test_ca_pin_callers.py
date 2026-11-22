"""``ARXMCP_PIN_ARXIV_CA=1`` reaches the TLS layer on every fetch path.

Each production entry point that downloads arxiv content (bulk ingest,
the notebook fetcher, the seed fetcher, the one-paper fetcher, the
preamble back-fill and the notebook raw-tex helper) is driven with a
fake ``urllib.request.urlopen`` that records the ``context`` it was
handed and answers 404. No request leaves the process.

With the pin on, every recorded context trusts exactly the pinned
bundle. With the pin off, every recorded context is ``None`` (the
system trust store). With the pin on and the bundle missing, no request
is made at all.
"""

from __future__ import annotations

import contextlib
import io
import ssl
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

import pytest

from arxmcp.ingest import bulk_ingest
from arxmcp.ingest import notebooks as _notebook_common
from arxmcp.server.ssl_pin import VENDORED_ARXIV_CA_BUNDLE
from arxmcp.tools import (
    fetch_one_paper,
    fetch_seed,
    notebook_fetch,
    recover_preambles,
)

PAPER_ID = "2307.01156"


def _drive_bulk_ingest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bulk_ingest.ingest_one_paper(
        PAPER_ID,
        lancedb_staging_path=tmp_path / "staging",
        ar5iv_cache_dir=tmp_path / "ar5iv",
        parsed_dir=tmp_path / "parsed",
        build_indices=False,
    )


def _drive_notebook_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = tmp_path / "notebooks"
    (base / "demo").mkdir(parents=True)
    (base / "demo" / "papers.txt").write_text(f"{PAPER_ID}\n", encoding="utf-8")
    monkeypatch.setattr(_notebook_common, "NOTEBOOKS_BASE", base)
    monkeypatch.setattr(notebook_fetch, "DEFAULT_AR5IV_CACHE_DIR", tmp_path / "ar5iv")
    monkeypatch.setattr(notebook_fetch, "DEFAULT_PARSED_DIR", tmp_path / "parsed")
    monkeypatch.setattr(notebook_fetch, "CORPUS_RAW_DIR", tmp_path / "raw")
    notebook_fetch.run("demo", sleep_seconds=0.0)


def _drive_fetch_seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fetch_seed.fetch_with_backoff(PAPER_ID, tmp_path / "raw")


def _drive_fetch_one_paper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetch_one_paper, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(sys, "argv", ["fetch_one_paper", PAPER_ID])
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    fetch_one_paper.main()


def _drive_recover_preambles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parsed = tmp_path / "parsed"
    (parsed / PAPER_ID).mkdir(parents=True)
    (tmp_path / "preamble").mkdir()
    monkeypatch.setattr(recover_preambles, "CORPUS_PARSED_DIR", parsed)
    monkeypatch.setattr(recover_preambles, "PREAMBLE_OUTPUT_DIR", tmp_path / "preamble")
    monkeypatch.setattr(recover_preambles, "CORPUS_RAW_DIR", tmp_path / "raw")
    recover_preambles.run(sleep_seconds=0.0)


def _drive_notebook_raw_tex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _notebook_common.fetch_raw_tex_if_missing(PAPER_ID, tmp_path / "raw")


ENTRY_POINTS: dict[str, Callable[[Path, pytest.MonkeyPatch], None]] = {
    "bulk_ingest": _drive_bulk_ingest,
    "notebook_fetch": _drive_notebook_fetch,
    "fetch_seed": _drive_fetch_seed,
    "fetch_one_paper": _drive_fetch_one_paper,
    "recover_preambles": _drive_recover_preambles,
    "notebook_raw_tex": _drive_notebook_raw_tex,
}


@pytest.fixture
def recorded_contexts(monkeypatch: pytest.MonkeyPatch) -> list[ssl.SSLContext | None]:
    """Replace ``urlopen`` with a recorder that answers 404."""
    seen: list[ssl.SSLContext | None] = []

    def _urlopen(request, *args, context=None, **kwargs):
        seen.append(context)
        url = request.full_url if hasattr(request, "full_url") else str(request)
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    monkeypatch.setenv("ARXMCP_CONTACT_EMAIL", "test@example.com")
    monkeypatch.delenv("ARXMCP_ARXIV_CA_BUNDLE_PATH", raising=False)
    return seen


def _trusted_subjects(context: ssl.SSLContext) -> list[tuple]:
    return sorted(cert["subject"] for cert in context.get_ca_certs())


@pytest.mark.parametrize("entry", sorted(ENTRY_POINTS))
def test_pinned_context_reaches_every_request(
    entry, tmp_path, monkeypatch, recorded_contexts
):
    monkeypatch.setenv("ARXMCP_PIN_ARXIV_CA", "1")

    ENTRY_POINTS[entry](tmp_path, monkeypatch)

    expected = _trusted_subjects(
        ssl.create_default_context(cafile=str(VENDORED_ARXIV_CA_BUNDLE))
    )
    assert recorded_contexts, f"{entry} made no request"
    for context in recorded_contexts:
        assert isinstance(context, ssl.SSLContext)
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname
        assert _trusted_subjects(context) == expected


@pytest.mark.parametrize("entry", sorted(ENTRY_POINTS))
def test_operator_bundle_override_reaches_every_request(
    entry, tmp_path, monkeypatch, recorded_contexts
):
    bundle = tmp_path / "operator-ca.pem"
    bundle.write_bytes(VENDORED_ARXIV_CA_BUNDLE.read_bytes())
    monkeypatch.setenv("ARXMCP_PIN_ARXIV_CA", "1")
    monkeypatch.setenv("ARXMCP_ARXIV_CA_BUNDLE_PATH", str(bundle))
    cafiles_read: list[str] = []
    real_create = ssl.create_default_context

    def _create(*args, cafile=None, **kwargs):
        cafiles_read.append(str(cafile))
        return real_create(*args, cafile=cafile, **kwargs)

    monkeypatch.setattr(ssl, "create_default_context", _create)

    ENTRY_POINTS[entry](tmp_path, monkeypatch)

    assert recorded_contexts, f"{entry} made no request"
    assert all(isinstance(c, ssl.SSLContext) for c in recorded_contexts)
    assert set(cafiles_read) == {str(bundle)}


@pytest.mark.parametrize("entry", sorted(ENTRY_POINTS))
def test_unpinned_requests_use_system_trust_store(
    entry, tmp_path, monkeypatch, recorded_contexts
):
    monkeypatch.delenv("ARXMCP_PIN_ARXIV_CA", raising=False)

    ENTRY_POINTS[entry](tmp_path, monkeypatch)

    assert recorded_contexts, f"{entry} made no request"
    assert all(context is None for context in recorded_contexts)


@pytest.mark.parametrize("entry", sorted(ENTRY_POINTS))
def test_missing_bundle_blocks_the_request(
    entry, tmp_path, monkeypatch, recorded_contexts
):
    monkeypatch.setenv("ARXMCP_PIN_ARXIV_CA", "1")
    monkeypatch.setenv("ARXMCP_ARXIV_CA_BUNDLE_PATH", str(tmp_path / "absent.pem"))

    # Config refusing the missing bundle is a correct outcome too.
    with contextlib.suppress(ValueError):
        ENTRY_POINTS[entry](tmp_path, monkeypatch)

    assert recorded_contexts == []
