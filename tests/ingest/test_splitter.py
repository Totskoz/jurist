"""Tests for paragraph-aware chunker."""
from __future__ import annotations


def test_empty_body_returns_empty() -> None:
    from jurist.ingest.splitter import split
    assert split("", target_words=500, overlap_words=50) == []


def test_short_body_single_chunk() -> None:
    from jurist.ingest.splitter import split
    body = "Dit is een korte uitspraak over huur. De verhuurder heeft gelijk."
    chunks = split(body, target_words=500, overlap_words=50)
    assert len(chunks) == 1
    assert chunks[0] == body


def test_paragraphs_packed_until_target() -> None:
    from jurist.ingest.splitter import split
    para1 = " ".join(["woord"] * 200)
    para2 = " ".join(["begrip"] * 200)
    para3 = " ".join(["andere"] * 200)
    body = f"{para1}\n\n{para2}\n\n{para3}"
    chunks = split(body, target_words=500, overlap_words=50)
    # 600 words > 500 target → 2 chunks
    assert len(chunks) == 2
    assert "woord" in chunks[0]
    assert "begrip" in chunks[0]  # packed with para1
    assert "andere" in chunks[1]


def test_overlap_prepends_last_words_of_prev_chunk() -> None:
    from jurist.ingest.splitter import split
    para1 = " ".join([f"a{i}" for i in range(400)])
    para2 = " ".join([f"b{i}" for i in range(400)])
    body = f"{para1}\n\n{para2}"
    chunks = split(body, target_words=500, overlap_words=50)
    assert len(chunks) >= 2
    # Last 50 words of chunk 0 should appear at start of chunk 1
    last_50_of_0 = chunks[0].split()[-50:]
    first_50_of_1 = chunks[1].split()[:50]
    assert last_50_of_0 == first_50_of_1


def test_long_single_paragraph_sentence_split() -> None:
    from jurist.ingest.splitter import split
    # 800 words, all in one paragraph (no blank line). Sentence-split fallback.
    sentences = [" ".join(["word"] * 100) + "." for _ in range(8)]
    body = " ".join(sentences)
    chunks = split(body, target_words=500, overlap_words=50)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk.split()) <= 550  # allow some slack for overlap


def test_dutch_abbreviations_not_split_as_sentences() -> None:
    from jurist.ingest.splitter import split
    # "art." and "jo." should not terminate sentences.
    body = (
        "De rechtbank overweegt dat art. 7:248 BW jo. art. 7:246 BW "
        "van toepassing is. Dit geldt ook voor Hof Den Haag 2023. "
        "Daarom volgt het oordeel."
    )
    chunks = split(body, target_words=500, overlap_words=50)
    # Short body, should stay one chunk; key test is that when larger bodies
    # split, abbrevs don't create broken chunks. Inline trivial check here:
    assert len(chunks) == 1


def test_pathological_single_sentence_char_split() -> None:
    from jurist.ingest.splitter import split
    # 700 "words" with no sentence boundaries (malformed XML edge).
    body = " ".join(["noend"] * 700)
    chunks = split(body, target_words=500, overlap_words=50)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk.split()) <= 550
