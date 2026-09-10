from pathlib import Path
from unittest.mock import MagicMock

from app.llm import LLMClient, validate_answer_grounding
from app.pipeline import ESGPipeline
from app.store import Store


def test_llm_client_fallback_when_disabled():
    client = LLMClient(enabled=False)
    assert client.is_available() is False
    assert client.synthesize_answer("question", []) is None


def test_pipeline_falls_back_when_llm_is_disabled(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.add_document(
        "d1",
        "TestReport.pdf",
        [(5, "Scope 1 direct emissions reached 100 metric tons in 2024.")],
    )
    llm = LLMClient(enabled=False)
    pipeline = ESGPipeline(store, llm_client=llm)

    res = pipeline.run("What are the emissions?", top_k=3, mode="qa")
    assert len(res.citations) > 0
    assert res.citations[0].page == 5
    assert res.answer


def test_audit_answer_cites_sources_not_computed_metrics(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.add_document(
        "d1",
        "TestReport.pdf",
        [(5, "Scope 1 direct emissions reached 100 metric tons in 2024.")],
    )

    result = ESGPipeline(store, retrieval_mode="bm25").run(
        "Audit the reported emissions", top_k=3, mode="audit"
    )
    coverage_line = next(
        line for line in result.answer.splitlines() if line.startswith("Disclosure coverage")
    )

    assert "computed from indexed evidence" in coverage_line
    assert "[C1]" not in coverage_line
    assert "Evidence reviewed: [C1]" in result.answer


def test_pipeline_with_optional_llm_synthesis(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.add_document(
        "d1",
        "TestReport.pdf",
        [(5, "Scope 1 direct emissions reached 100 metric tons in 2024.")],
    )

    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.is_available.return_value = True
    mock_llm.synthesize_answer.return_value = (
        "Based on [TestReport.pdf, trang 5], Scope 1 emissions were 100 metric tons in 2024."
    )

    pipeline = ESGPipeline(store, llm_client=mock_llm)
    res = pipeline.run("What are the emissions?", top_k=3, mode="qa")

    assert "Based on [TestReport.pdf, trang 5]" in res.answer
    mock_llm.synthesize_answer.assert_called_once()


def test_validate_answer_grounding_accepts_cid_and_rejects_bad_page():
    citations = [
        {
            "cid": "[C1]",
            "page": 5,
            "excerpt": "Scope 1 emissions were 100 metric tons in 2024.",
            "document_name": "TestReport.pdf",
        }
    ]
    ok, issues = validate_answer_grounding(
        "Scope 1 was 100 metric tons in 2024 [C1].",
        citations,
    )
    assert ok is True
    assert issues == []

    bad, bad_issues = validate_answer_grounding(
        "Scope 1 was 100 metric tons on trang 99 [C1].",
        citations,
    )
    assert bad is False
    assert any("hallucinated_pages" in i for i in bad_issues)


def test_validate_answer_grounding_rejects_unsupported_numbers():
    citations = [
        {
            "cid": "[C1]",
            "page": 5,
            "excerpt": "Scope 1 emissions were 100 metric tons in 2024.",
            "document_name": "TestReport.pdf",
        }
    ]
    ok, issues = validate_answer_grounding(
        "Emissions totaled 999999 tCO2e in 2024 [C1].",
        citations,
    )
    assert ok is False
    assert any("unsupported_numbers" in i for i in issues)


def test_validate_answer_grounding_rejects_uncited_sentence():
    citations = [
        {
            "cid": "[C1]",
            "page": 5,
            "excerpt": "Scope 1 emissions were 100 metric tons in 2024.",
            "document_name": "TestReport.pdf",
        }
    ]
    ok, issues = validate_answer_grounding(
        "Scope 1 emissions were 100 metric tons in 2024 [C1]. This is a broad conclusion.",
        citations,
    )
    assert ok is False
    assert "missing_evidence_ids" in issues
