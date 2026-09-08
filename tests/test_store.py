from pathlib import Path

from app.models import ESGFact
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


def test_search_with_non_positive_limit_is_empty(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.add_document("report", "Report.pdf", [(1, "carbon emissions")])

    assert store.search("carbon", limit=0) == []
    assert store.search("carbon", limit=-1) == []


def test_query_facts_defaults_to_accepted_only(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.add_document("report", "Report.pdf", [(1, "carbon emissions")])
    store.save_facts(
        [
            ESGFact(
                metric="scope_1_emissions",
                value=100.0,
                unit="tCO2e",
                company="ACME",
                document_id="report",
                status="CANDIDATE",
            )
        ]
    )

    assert store.query_facts(document_id="report") == []
    assert len(store.query_facts(document_id="report", include_candidates=True)) == 1
