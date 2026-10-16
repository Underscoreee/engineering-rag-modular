"""Deterministic paragraph, sentence, then token fallback splitting."""

import re

from .models import TextPiece

_TOKEN = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9]+(?:[._/-][A-Za-z0-9]+)*|[^\s]")
_SENTENCE = re.compile(r".+?(?:[。！？；!?;]+|(?=\n)|$)", re.DOTALL)


def count_tokens(text: str) -> int:
    """Return the dependency-free V1 token estimate used for limits and metadata."""
    return len(_TOKEN.findall(text))


def split_text_piece(piece: TextPiece, max_tokens: int) -> list[TextPiece]:
    if count_tokens(piece.text) <= max_tokens:
        return [piece]
    sentences = [match.group(0).strip() for match in _SENTENCE.finditer(piece.text)]
    sentences = [sentence for sentence in sentences if sentence]
    if len(sentences) <= 1:
        return [
            TextPiece(text=value, source_block_ids=piece.source_block_ids)
            for value in _token_windows(piece.text, max_tokens)
        ]
    result: list[TextPiece] = []
    for sentence in sentences:
        if count_tokens(sentence) <= max_tokens:
            result.append(TextPiece(sentence, piece.source_block_ids))
        else:
            result.extend(
                TextPiece(value, piece.source_block_ids)
                for value in _token_windows(sentence, max_tokens)
            )
    return result


def pack_text_pieces(pieces: list[TextPiece], max_tokens: int) -> list[TextPiece]:
    """Pack complete semantic pieces without overlap; split only an oversized piece."""
    expanded = [part for piece in pieces for part in split_text_piece(piece, max_tokens)]
    packed: list[TextPiece] = []
    current_text = ""
    current_ids: list[str] = []
    for piece in expanded:
        candidate = f"{current_text}\n{piece.text}" if current_text else piece.text
        if current_text and count_tokens(candidate) > max_tokens:
            packed.append(TextPiece(current_text, tuple(current_ids)))
            current_text = piece.text
            current_ids = list(piece.source_block_ids)
            continue
        current_text = candidate
        for block_id in piece.source_block_ids:
            if block_id not in current_ids:
                current_ids.append(block_id)
    if current_text:
        packed.append(TextPiece(current_text, tuple(current_ids)))
    return packed


def _token_windows(text: str, max_tokens: int) -> list[str]:
    matches = list(_TOKEN.finditer(text))
    windows: list[str] = []
    for start in range(0, len(matches), max_tokens):
        selected = matches[start : start + max_tokens]
        value = text[selected[0].start() : selected[-1].end()].strip()
        if value:
            windows.append(value)
    return windows
