from pathlib import Path
from unittest.mock import MagicMock

from app.agents import SupervisorAgent
from app.llm import LLMClient, validate_answer_grounding
from app.store import Store


def test_llm_client_fallback_when_disabled():
    client = LLMClient(enabled=False)
    assert client.is_available() is False
    assert client.generate_plan("question") is None
    assert client.synthesize_answer("question", []) is None


def test_supervisor_deterministic_fallback(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.add_document(
        "d1",
        "TestReport.pdf",
        [(5, "Scope 1 direct emissions reached 100 metric tons in 2024.")],
    )
    llm = LLMClient(enabled=False)
    supervisor = SupervisorAgent(store, llm_client=llm)

    res = supervisor.run("What are the emissions?", top_k=3, mode="qa")
    assert res.agent_mode == "deterministic_fallback"
    assert len(res.citations) > 0
    assert res.citations[0].page == 5
    assert any("Deterministic Heuristic Engine" in t for t in res.trace)


def test_supervisor_with_mock_llm(tmp_path: Path):
    store = Store(tmp_path / "test.db")
    store.add_document(
        "d1",
        "TestReport.pdf",
        [(5, "Scope 1 direct emissions reached 100 metric tons in 2024.")],
    )

    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.is_available.return_value = True
    mock_llm.generate_plan.return_value = [
        {"tool": "search_document", "args": {"query": "emissions", "top_k": 3}},
        {"tool": "extract_metric", "args": {"text": "Scope 1 direct emissions reached 100 metric tons"}},
    ]
    mock_llm.synthesize_answer.return_value = (
        "Based on [TestReport.pdf, trang 5], Scope 1 emissions were 100 metric tons in 2024."
    )

    supervisor = SupervisorAgent(store, llm_client=mock_llm)
    res = supervisor.run("What are the emissions?", top_k=3, mode="qa")

    assert res.agent_mode == "agent_orchestrated"
    assert "Based on [TestReport.pdf, trang 5]" in res.answer
    assert any("LLM Structured Planning" in t for t in res.trace)
    assert any("Tool search_document" in t for t in res.trace)


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
