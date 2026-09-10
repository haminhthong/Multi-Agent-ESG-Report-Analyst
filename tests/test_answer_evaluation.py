from pathlib import Path

from app.answer_eval import AnswerEvalCase, evaluate_answer_quality
from app.pipeline import ESGPipeline
from app.store import Store


def test_answer_quality_evaluation(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.add_document(
        "boeing-demo",
        "Boeing 2025 Report.pdf",
        [
            (
                43,
                "As of the end of 2024, 724 suppliers were rated using social criteria, a 148% increase.",
            )
        ],
    )
    pipeline = ESGPipeline(store)

    cases = [
        AnswerEvalCase(
            id="test_suppliers",
            question="How many suppliers were evaluated using social criteria?",
            query_scope=["boeing-demo"],
            expected_topics=["suppliers", "social", "criteria"],
            expected_numbers=["724", "148%"],
            expected_evidence=[{"document_id": "boeing-demo", "page": 43}],
        )
    ]

    report = evaluate_answer_quality(pipeline, cases, top_k=2)
    assert report.cases == 1
    assert 0.0 <= report.faithfulness <= 1.0
    assert 0.0 <= report.citation_correctness <= 1.0
    assert 0.0 <= report.completeness <= 1.0
    assert 0.0 <= report.unsupported_claim_rate <= 1.0
    assert report.gold_citation_precision is not None
    assert 0.0 <= report.gold_citation_precision <= 1.0
    assert len(report.details) == 1
    assert report.details[0].id == "test_suppliers"
