import pytest

from app.chunking import chunk_pages, normalize_text


def test_chunking_preserves_page_and_bounds_size():
    chunks = chunk_pages(
        [(12, " ".join(f"word{i}" for i in range(700)))], max_words=100, overlap_words=20
    )
    assert len(chunks) > 1
    assert all(chunk.page == 12 for chunk in chunks)
    assert all(len(chunk.text.split()) <= 100 for chunk in chunks)


def test_normalize_repairs_line_break_hyphenation():
    assert normalize_text("green-\nhouse   gas") == "greenhouse gas"


def test_chunking_rejects_invalid_overlap():
    with pytest.raises(ValueError, match="overlap_words"):
        chunk_pages([(1, "sample text")], max_words=10, overlap_words=10)
