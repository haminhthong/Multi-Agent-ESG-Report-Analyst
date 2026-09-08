from pathlib import Path

from app.facts.repository import FactRepository
from app.models import ESGFact
from app.store import Store


def test_ingestion_creates_candidate_before_explicit_review(tmp_path: Path):
    store = Store(tmp_path / "facts.db")
    store.add_document(
        "report-2024",
        "ACME 2024.pdf",
        [(10, "Scope 1 direct emissions were 100 tCO2e in 2024.")],
        company="ACME",
        year=2024,
    )
    repository = FactRepository(store)

    candidates = repository.query_candidates(document_id="report-2024")
    assert candidates
    assert repository.query_facts(document_id="report-2024") == []

    fact_id = candidates[0].fact_id
    assert repository.promote([fact_id], reviewed_by="analyst") == 1
    accepted = repository.query_facts(document_id="report-2024")
    assert [fact.fact_id for fact in accepted] == [fact_id]

    with store.connect() as db:
        decisions = db.execute(
            "SELECT decision FROM fact_review_decisions WHERE candidate_id=?",
            (fact_id,),
        ).fetchall()
    assert [row["decision"] for row in decisions] == ["ACCEPTED"]


def test_reindex_does_not_erase_accepted_fact_or_review_history(tmp_path: Path):
    store = Store(tmp_path / "reindex.db")
    store.add_document(
        "report",
        "ACME report.pdf",
        [(1, "Scope 1 direct emissions were 100 tCO2e in 2024.")],
        company="ACME",
        year=2024,
    )
    repository = FactRepository(store)
    fact_id = repository.query_candidates(document_id="report")[0].fact_id
    repository.promote([fact_id], reviewed_by="analyst")

    store.add_document(
        "report",
        "ACME report.pdf",
        [(1, "Scope 1 direct emissions were 100 tCO2e in 2024.")],
        company="ACME",
        year=2024,
    )

    assert repository.query_facts(document_id="report")[0].fact_id == fact_id
    with store.connect() as db:
        count = db.execute(
            "SELECT COUNT(*) AS count FROM fact_review_decisions WHERE candidate_id=?",
            (fact_id,),
        ).fetchone()["count"]
    assert count == 1


def test_reindex_removes_orphan_chunk_embeddings(tmp_path: Path):
    store = Store(tmp_path / "embeddings.db")
    store.add_document("report", "ACME report.pdf", [(1, "Scope 1 emissions were 100 tCO2e.")])

    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0] == 1

    store.add_document("report", "ACME report.pdf", [(1, "Scope 1 emissions were 120 tCO2e.")])

    with store.connect() as db:
        orphan_count = db.execute(
            "SELECT COUNT(*) FROM chunk_embeddings e "
            "LEFT JOIN chunks c ON c.id=e.chunk_id WHERE c.id IS NULL"
        ).fetchone()[0]
    assert orphan_count == 0


def test_fact_repository_save_facts_is_explicit_accepted_import(tmp_path: Path):
    store = Store(tmp_path / "accepted.db")
    store.add_document("report", "Report.pdf", [(1, "metadata")])
    repository = FactRepository(store)
    fact = ESGFact(
        metric="scope_1_emissions",
        value=10.0,
        unit="tCO2e",
        year=2024,
        company="ACME",
        document_id="report",
    )

    assert repository.save_facts([fact]) == 1
    assert repository.query_facts(company="ACME")[0].status == "ACCEPTED"
