"""Paragraph-aware recursive text chunker. Stdlib only.

Algorithm:
1. Split body on blank-line boundaries → paragraphs.
2. Greedily pack paragraphs into chunks up to `target_words`.
3. Single paragraph > target → recurse on sentence boundaries, skipping
   Dutch legal abbreviations.
4. Single sentence > target → character-split at word boundary (last resort).

Overlap: last `overlap_words` of chunk N are prepended to chunk N+1.
"""
from __future__ import annotations

import re

# Dutch legal abbreviations that end with a period but are NOT sentence
# terminators. Case-sensitive — "Art." at start of sentence is intentional.
_ABBREVIATIONS = {
    "art.", "artt.", "lid", "jo.", "Hof", "Mr.", "Dr.", "mr.", "dr.",
    "nr.", "blz.", "o.a.", "i.c.", "m.b.t.", "vs.", "ibid.", "ca.",
}

_SENTENCE_END = re.compile(r"(?<=[.?!])\s+")


def split(body: str, *, target_words: int, overlap_words: int) -> list[str]:
    """Chunk `body` into ≤`target_words`-word slices with overlap.

    Returns [] for empty input.
    """
    if not body.strip():
        return []

    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]

    raw_chunks: list[str] = []
    buf: list[str] = []
    buf_wc = 0
    for para in paragraphs:
        wc = _word_count(para)
        if wc > target_words:
            # Flush current buffer, then recurse on this long paragraph.
            if buf:
                raw_chunks.append(" ".join(buf))
                buf, buf_wc = [], 0
            raw_chunks.extend(_split_long(para, target_words))
            continue
        if buf_wc + wc > target_words and buf:
            raw_chunks.append(" ".join(buf))
            buf, buf_wc = [], 0
        buf.append(para)
        buf_wc += wc
    if buf:
        raw_chunks.append(" ".join(buf))

    return _apply_overlap(raw_chunks, overlap_words)


def _word_count(s: str) -> int:
    return len(s.split())


def _split_long(para: str, target_words: int) -> list[str]:
    """Sentence-split; fall back to char-split on single long sentences."""
    sentences = _sentence_split(para)
    out: list[str] = []
    buf: list[str] = []
    buf_wc = 0
    for sent in sentences:
        wc = _word_count(sent)
        if wc > target_words:
            # Flush, then char-split this monster.
            if buf:
                out.append(" ".join(buf))
                buf, buf_wc = [], 0
            out.extend(_char_split(sent, target_words))
            continue
        if buf_wc + wc > target_words and buf:
            out.append(" ".join(buf))
            buf, buf_wc = [], 0
        buf.append(sent)
        buf_wc += wc
    if buf:
        out.append(" ".join(buf))
    return out


def _sentence_split(text: str) -> list[str]:
    """Split on sentence ends, skipping Dutch legal abbreviations."""
    parts: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        # Look at the word ending at `match.start()` — skip if it's an abbrev.
        preceding = text[:match.start()].rsplit(None, 1)
        prev_word = preceding[-1] if preceding else ""
        if prev_word in _ABBREVIATIONS:
            continue
        parts.append(text[start:match.start() + 1].strip())
        start = match.end()
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _char_split(sent: str, target_words: int) -> list[str]:
    """Last-resort word-boundary split for pathologically long sentences."""
    words = sent.split()
    return [
        " ".join(words[i : i + target_words])
        for i in range(0, len(words), target_words)
    ]


def _apply_overlap(chunks: list[str], overlap_words: int) -> list[str]:
    """Prepend last `overlap_words` of chunk N to chunk N+1."""
    if overlap_words <= 0 or len(chunks) <= 1:
        return chunks
    out = [chunks[0]]
    for i in range(1, len(chunks)):
        prev_tail = " ".join(chunks[i - 1].split()[-overlap_words:])
        out.append(f"{prev_tail} {chunks[i]}")
    return out
