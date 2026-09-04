from pathlib import Path

from app.agents import RetrievalAgent
from app.evaluation import (
    ExpectedCitation,
    RetrievalEvalCase,
    evaluate_retrieval,
)
from app.store import Store


def test_evaluation_calculates_recall_and_mrr(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.add_document(
        "d1",
        "Report.pdf",
        [
            (4, "Scope 1 and Scope 2 carbon emissions decreased 12% in 2024."),
            (8, "Worker safety training covered 500 employees."),
        ],
    )
    cases = [
        RetrievalEvalCase(
            id="emissions",
            question="carbon emissions",
            expected=[ExpectedCitation(document_id="d1", page=4)],
        )
    ]

    report = evaluate_retrieval(RetrievalAgent(store), cases, top_k=3)

    assert report.recall_at_k == 1
    assert report.mrr == 1
    assert report.details[0].retrieved >= 1


def test_empty_evaluation_is_safe(tmp_path: Path):
    report = evaluate_retrieval(RetrievalAgent(Store(tmp_path / "test.db")), [])
    assert report.cases == 0
    assert report.recall_at_k == 0
