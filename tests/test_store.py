from pathlib import Path

from app.store import Store


def test_reindex_document_replaces_old_content(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.add_document("report", "Report.pdf", [(1, "old carbon disclosure")])
    store.add_document("report", "Report.pdf", [(2, "new safety disclosure")])

    assert not store.search("old carbon", document_ids=["report"])
    assert store.search("new safety", document_ids=["report"])[0]["page"] == 2


def test_corpus_stats(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.add_document("a", "A.pdf", [(1, "carbon emissions")], "A", "Energy", 2024)

    assert store.stats() == {"documents": 1, "chunks": 1, "companies": 1, "sectors": 1}
