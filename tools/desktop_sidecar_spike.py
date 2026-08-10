"""Disposable frozen-sidecar entry point for desktop-distribution-spike-1."""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import shutil
import stat
import sys
from pathlib import Path

ASSETS = ("app.css", "tokens.css", "htmx.min.js")
FORBIDDEN_ENV = ("KMP_DUPLICATE_LIB_OK", "PYTHONHOME", "PYTHONPATH")

#: Dynamic-loader override prefixes. Held byte-identical across the three
#: copies of this launch contract (here, ``tools/desktop_model_probe.py``,
#: ``apps/desktop/pyinstaller/probe_entry.py``) by
#: ``tests/test_desktop_package.py``: a narrower set on one side would let the
#: golden vectors be produced under an override the frozen probe would refuse.
FORBIDDEN_ENV_PREFIXES = ("DYLD_", "LD_")


def launch_environment(root: Path, port: int) -> dict[str, str]:
    """Create the probe's allowlisted, offline launch environment."""
    root = root.resolve()
    dirs = {name: root / name for name in ("data", "home", "cache", "tmp", "empty-bin")}
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return {
        "ARXMCP_BIND_HOST": "127.0.0.1",
        "ARXMCP_BIND_PORT": str(port),
        "ARXMCP_BOOTSTRAP_MODE": "1",
        "ARXMCP_DATA_DIR": str(dirs["data"]),
        "ARXMCP_LOG_FORMAT": "text",
        "ARXMCP_LOG_LEVEL": "WARNING",
        "HF_HOME": str(dirs["cache"] / "huggingface"),
        "HF_HUB_OFFLINE": "1",
        "HOME": str(dirs["home"]),
        "OMP_NUM_THREADS": "1",
        "PATH": str(dirs["empty-bin"]),
        "PYTHONNOUSERSITE": "1",
        "TMPDIR": str(dirs["tmp"]),
        "TOKENIZERS_PARALLELISM": "false",
        "TRANSFORMERS_OFFLINE": "1",
        "XDG_CACHE_HOME": str(dirs["cache"]),
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_DATA_HOME": str(root / "share"),
    }


def validate_launch_environment(env: dict[str, str]) -> None:
    """Reject ambient Python, dynamic-loader paths, or online model access."""
    bad = [
        key
        for key in env
        if key in FORBIDDEN_ENV or key.startswith(FORBIDDEN_ENV_PREFIXES)
    ]
    if bad:
        raise RuntimeError(f"forbidden environment keys: {sorted(bad)}")
    if env.get("HF_HUB_OFFLINE") != "1" or env.get("TRANSFORMERS_OFFLINE") != "1":
        raise RuntimeError("offline model flags are required")
    if shutil.which("python", path=env.get("PATH")) or shutil.which(
        "python3", path=env.get("PATH")
    ):
        raise RuntimeError("launch PATH supplies an ambient Python")


def tree_manifest(root: Path) -> str:
    """Hash root metadata, entry metadata, file bytes, and symlink targets."""
    digest = hashlib.sha256()
    for path in [root, *sorted(root.rglob("*"))]:
        metadata = path.lstat()
        relative = "." if path == root else path.relative_to(root).as_posix()
        row = f"{relative}\0{metadata.st_mode:o}\0{metadata.st_size}\n"
        digest.update(row.encode("utf-8"))
        if stat.S_ISLNK(metadata.st_mode):
            digest.update(os.fsencode(os.readlink(path)))
        elif stat.S_ISREG(metadata.st_mode):
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
    return digest.hexdigest()


def tree_statistics(root: Path) -> dict[str, int]:
    """Measure regular-file payloads without following in-tree symlinks."""
    result = {"regular_files": 0, "symlinks": 0, "logical_bytes": 0,
              "allocated_bytes": 0}
    for path in root.rglob("*"):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            result["symlinks"] += 1
        elif stat.S_ISREG(metadata.st_mode):
            result["regular_files"] += 1
            result["logical_bytes"] += metadata.st_size
            blocks = getattr(metadata, "st_blocks", (metadata.st_size + 511) // 512)
            result["allocated_bytes"] += blocks * 512
    return result


def validate_frozen_paths(bundle: Path) -> None:
    """Require the executable and import roots to remain inside the bundle."""
    bundle = bundle.resolve()
    candidates = [Path(sys.executable), *(Path(item) for item in sys.path if item)]
    outside = [str(path) for path in candidates if not path.resolve().is_relative_to(bundle)]
    if outside:
        raise RuntimeError(f"runtime path escaped bundle: {outside}")


def _native_model_probe() -> dict[str, object]:
    import faiss
    import httptools
    import kuzu
    import lancedb
    import numpy as np
    import pyarrow as pa
    import torch
    import uvloop
    from tokenizers import Tokenizer, models
    from transformers import AutoModel, XLMRobertaConfig

    from ingest.embedder import BGE_M3_COMMIT_SHA
    from server.model_loader import validate_model_revision
    from server.retrieval.rerank import BGE_RERANKER_COMMIT_SHA

    data = Path(os.environ["ARXMCP_DATA_DIR"]).resolve() / "spike-probe"
    data.mkdir(parents=True, exist_ok=True)
    validate_model_revision(BGE_M3_COMMIT_SHA, model_name="BAAI/bge-m3")
    validate_model_revision(BGE_RERANKER_COMMIT_SHA, model_name="BAAI/bge-reranker-v2-m3")

    arrow = pa.table({"value": [1, 2]})
    schema = pa.schema([pa.field("id", pa.int64()), pa.field("v", pa.list_(pa.float32(), 2))])
    table = lancedb.connect(data / "lance").create_table(
        "probe", [{"id": 1, "v": [1.0, 0.0]}], schema=schema, mode="overwrite"
    )
    index = faiss.IndexFlatL2(2)
    index.add(np.asarray([[1.0, 0.0]], dtype="float32"))
    _, nearest = index.search(np.asarray([[1.0, 0.0]], dtype="float32"), 1)

    database = kuzu.Database(str(data / "kuzu"))
    connection = kuzu.Connection(database)
    connection.execute("CREATE NODE TABLE Probe(id INT64, PRIMARY KEY(id))")
    connection.execute("CREATE (:Probe {id: 7})")
    kuzu_value = connection.execute("MATCH (p:Probe) RETURN p.id").get_next()[0]
    connection.close()
    database.close()

    tokenizer = Tokenizer(models.WordLevel({"[UNK]": 0, "math": 1}, unk_token="[UNK]"))
    token_ids = tokenizer.encode("math").ids
    loop = uvloop.new_event_loop()
    loop.close()

    class Protocol:
        def __getattr__(self, _name: str):
            return lambda *args: None

    httptools.HttpRequestParser(Protocol()).feed_data(b"GET / HTTP/1.1\r\nHost:x\r\n\r\n")

    model_dir = data / "tiny-model"
    config = XLMRobertaConfig(
        vocab_size=32, hidden_size=8, intermediate_size=16,
        num_hidden_layers=1, num_attention_heads=2, max_position_embeddings=32,
    )
    AutoModel.from_config(config).save_pretrained(model_dir, safe_serialization=True)
    model = AutoModel.from_pretrained(
        model_dir, local_files_only=True, use_safetensors=True, trust_remote_code=False
    ).eval()
    with torch.no_grad():
        shape = list(model(input_ids=torch.tensor([[0, 2, 3]])).last_hidden_state.shape)
    return {
        "arrow_rows": arrow.num_rows,
        "bge_m3_pin": BGE_M3_COMMIT_SHA,
        "bge_reranker_pin": BGE_RERANKER_COMMIT_SHA,
        "faiss_neighbor": int(nearest[0, 0]),
        "kuzu_value": int(kuzu_value),
        "lance_rows": table.count_rows(),
        "model_shape": shape,
        "model_weights": sorted(path.name for path in model_dir.iterdir()),
        "token_ids": token_ids,
    }


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("serve", "probe"))
    args = parser.parse_args(argv)
    if args.mode == "serve":
        from server.cli import main as serve

        return serve([])
    validate_launch_environment(dict(os.environ))
    if getattr(sys, "frozen", False):
        validate_frozen_paths(Path(sys.executable).parent)
    print(json.dumps(_native_model_probe(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
