from pathlib import Path
from unittest.mock import Mock

from app.models import AnalysisState, RetrievalPlan, TemporalAnalysisResult
from app.store import Store
from app.workflow import ESGAnalysisPipeline


def test_pipeline_runs_end_to_end_with_trace(tmp_path: Path):
    store = Store(tmp_path / "workflow.db")
    store.add_document(
        "acme-2024",
        "Acme Sustainability Report 2024.pdf",
        [
            (
                5,
                (
                    "Acme reported Scope 1 emissions of 1200 tCO2e in 2024. "
                    "The company targets net zero by 2050 from a 2020 baseline year."
                ),
            ),
            (
                9,
                (
                    "Worker safety performance included a TRIR of 1.2 in 2024. "
                    "The board oversees climate and ethics compliance."
                ),
            ),
        ],
        company="Acme",
        sector="Industrials",
        year=2024,
    )

    result = ESGAnalysisPipeline(store, retrieval_mode="bm25").run(
        "Assess Acme ESG emissions, target, safety, governance and assurance",
        top_k=6,
        document_ids=["acme-2024"],
        mode="audit",
    )

    assert result.plan is not None
    assert result.citations
    assert result.extracted_facts is not None
    assert result.evidence_matrix
    assert result.evidence_completeness["status"] in {"complete", "incomplete"}
    assert result.trace_steps
    assert [step.agent for step in result.trace_steps][:5] == [
        "Workflow",
        "QueryPlanningAgent",
        "RetrievalAgent",
        "EvidenceVerificationAgent",
        "EvidenceExtractionAgent",
    ]
    assert any("not a legal" in limitation.lower() for limitation in result.limitations)


def test_unknown_document_scope_is_reported_not_silently_used(tmp_path: Path):
    store = Store(tmp_path / "workflow.db")
    store.add_document("known", "Known.pdf", [(1, "Scope 1 emissions were 100 tCO2e in 2024.")])

    result = ESGAnalysisPipeline(store, retrieval_mode="bm25").run(
        "What were Scope 1 emissions?",
        top_k=3,
        document_ids=["missing-id"],
        mode="qa",
    )

    assert any("unknown document ids" in item.lower() for item in result.limitations)


def test_supervisor_agent_graph_exposes_route_and_mode(tmp_path: Path):
    store = Store(tmp_path / "workflow.db")
    store.add_document(
        "acme-2024",
        "Acme Sustainability Report 2024.pdf",
        [(5, "Acme reported Scope 1 emissions of 1200 tCO2e in 2024.")],
        company="Acme",
        year=2024,
    )

    result = ESGAnalysisPipeline(store, retrieval_mode="bm25").run(
        "What were Acme Scope 1 emissions?",
        top_k=3,
        document_ids=["acme-2024"],
        agent_mode="deterministic",
    )

    assert result.requested_agent_mode == "deterministic"
    assert result.agent_mode == "deterministic_fallback"
    assert result.agent_stop_reason == "completed"
    assert result.agent_route[:5] == [
        "ScopeAgent",
        "QueryPlanningAgent",
        "RetrievalAgent",
        "EvidenceVerificationAgent",
        "EvidenceExtractionAgent",
    ]
    assert any("Supervisor: handoff" in item for item in result.trace)


def test_temporal_specialized_stage_uses_store_scope_once(tmp_path: Path):
    store = Store(tmp_path / "workflow.db")
    store.add_document(
        "acme-2023",
        "Acme 2023.pdf",
        [(1, "Acme Scope 1 emissions were 400 tCO2e in 2023.")],
        company="Acme",
        year=2023,
    )
    audit = Mock()
    audit.run_temporal_analysis.return_value = TemporalAnalysisResult(
        company="Acme",
        metric="scope_1_emissions",
    )
    pipeline = ESGAnalysisPipeline(store, audit_service=audit)
    state = AnalysisState(
        request_id="test-request",
        user_question="Show Scope 1 trend for Acme",
        document_ids=["acme-2023"],
        plan=RetrievalPlan(
            intent="temporal_trend",
            metrics=["scope_1_emissions"],
        ),
    )

    pipeline._run_specialized_analysis(state)

    audit.run_temporal_analysis.assert_called_once_with(
        "Acme",
        store,
        metric="scope_1_emissions",
        document_ids=["acme-2023"],
    )
