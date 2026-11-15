"""A deterministic stand-in for the BGE-M3 tokenizer the chunker uses.

The chunker needs a tokenizer to count tokens, window long proofs and
truncate statements. Its tests check chunk structure (pairing, kinds,
ids, window mechanics), not BGE-M3's subword splits, so they run against
this instead of a 2 GB model download. Real-tokenizer behaviour is pinned
separately by ``requires_model`` tests.

A token is a run of up to four non-space characters, which keeps counts
in the same range as BGE-M3's on English and LaTeX text. Ids are stable
within an instance, and character offsets are real, so windowing and
truncation slice the text exactly as they would with the real tokenizer.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"\S{1,4}")


class StandInTokenizer:
    """The three calls ``ingest.chunker`` makes on a Hugging Face tokenizer."""

    def __init__(self) -> None:
        self._ids: dict[str, int] = {}
        self._pieces: list[str] = []

    def _id(self, piece: str) -> int:
        if piece not in self._ids:
            self._ids[piece] = len(self._pieces)
            self._pieces.append(piece)
        return self._ids[piece]

    def __call__(
        self,
        text: str,
        add_special_tokens: bool = False,
        return_offsets_mapping: bool = False,
    ) -> dict[str, list]:
        matches = list(_TOKEN.finditer(text))
        out: dict[str, list] = {"input_ids": [self._id(m.group()) for m in matches]}
        if return_offsets_mapping:
            out["offset_mapping"] = [(m.start(), m.end()) for m in matches]
        return out

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        return self(text)["input_ids"]

    def decode(self, token_ids: list[int], skip_special_tokens: bool = True) -> str:
        return " ".join(self._pieces[i] for i in token_ids)
