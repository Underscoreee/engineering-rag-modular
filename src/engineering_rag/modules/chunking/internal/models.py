"""Small private values shared by Chunk V1 assembly steps."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextPiece:
    text: str
    source_block_ids: tuple[str, ...]
