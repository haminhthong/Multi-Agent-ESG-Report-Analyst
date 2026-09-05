from pathlib import Path

from app.agents import (
    ESGAuditAgent,
    EvidenceExtractionAgent,
    QueryPlanningAgent,
)
from app.models import Citation
from app.store import Store


def test_target_with_baseline():
    """Kiểm tra target có năm cơ sở rõ ràng không bị cảnh báo thiếu baseline."""
    cite = Citation(
        chunk_id=1,
        document_id="d1",
        document_name="Boeing_2023.pdf",
        page=15,
        excerpt="The company commits to reduce absolute Scope 1 emissions by 40% by 2030 compared to 2019 baseline year.",
    )
    agent = ESGAuditAgent()
    res = agent.screen_greenwashing_signals([cite], [])
    assert any("Baseline Year" in s for s in res.target_credibility_signals)
    assert not any("thiếu năm cơ sở" in s.lower() for s in res.target_credibility_signals)


def test_target_without_baseline():
    """Kiểm tra target tham vọng nhưng thiếu baseline bị cảnh báo Greenwashing."""
    cite = Citation(
        chunk_id=1,
        document_id="d1",
        document_name="Vague_ESG.pdf",
        page=3,
        excerpt="We proudly aspire to achieve net-zero carbon emissions by 2050 across our worldwide operations.",
    )
    agent = ESGAuditAgent()
    res = agent.screen_greenwashing_signals([cite], [])
    assert any("thiếu năm cơ sở" in s.lower() for s in res.target_credibility_signals)
    assert res.risk_level in ("MEDIUM", "HIGH")


def test_negated_assurance_as_negative_evidence():
    """Kiểm tra tuyên bố từ chối bảo đảm độc lập được nhận diện chuẩn xác như bằng chứng tiêu cực."""
    cite = Citation(
        chunk_id=1,
        document_id="d1",
        document_name="Unassured_Report.pdf",
        page=70,
        excerpt="This sustainability report has not been independently assured or audited by an external third party.",
    )
    agent = ESGAuditAgent()
    res = agent.screen_greenwashing_signals([cite], [])
    assert any("KHÔNG ĐƯỢC kiểm toán hoặc bảo đảm" in s for s in res.evidence_quality_signals)


def test_scope3_not_confused_with_scope2():
    """Kiểm tra Scope 2 và Scope 3 được trích xuất riêng biệt không bị nhầm lẫn giá trị."""
    cite = Citation(
        chunk_id=1,
        document_id="d1",
        document_name="Emissions.pdf",
        page=22,
        excerpt="In 2023, market-based Scope 2 emissions were 412,000 MT CO2e. Upstream and downstream Scope 3 supply chain emissions reached 35,600,000 MT CO2e.",
    )
    extractor = EvidenceExtractionAgent()
    facts = extractor.extract_facts([cite])
    metrics_found = {f.metric: f.value for f in facts}

    assert "scope_2_emissions" in metrics_found
    assert "scope_3_emissions" in metrics_found
    assert metrics_found["scope_2_emissions"] == 412000.0
    assert metrics_found["scope_3_emissions"] == 35600000.0
    assert metrics_found["scope_2_emissions"] != metrics_found["scope_3_emissions"]


def test_metric_wrong_unit():
    """Kiểm tra trích xuất số liệu chuẩn hóa đơn vị metric tons CO2e."""
    cite = Citation(
        chunk_id=1,
        document_id="d1",
        document_name="Units.pdf",
        page=10,
        excerpt="Scope 1 direct greenhouse gas emissions totaled 580,000 metric tons CO2e in 2023.",
    )
    facts = EvidenceExtractionAgent.extract_facts([cite])
    s1 = next((f for f in facts if f.metric == "scope_1_emissions"), None)
    assert s1 is not None
    assert s1.value == 580000.0
    assert "metric tons" in s1.unit.lower() or "tco2e" in s1.unit.lower()


def test_conflicting_evidence_detection():
    """Kiểm tra phát hiện mâu thuẫn số liệu giữa các trang hoặc các báo cáo."""
    cite1 = Citation(
        chunk_id=1,
        document_id="d1",
        document_name="Report_A.pdf",
        page=12,
        excerpt="In 2023, Scope 1 greenhouse gas emissions were 150,000 MT CO2e.",
    )
    cite2 = Citation(
        chunk_id=2,
        document_id="d1",
        document_name="Report_A.pdf",
        page=45,
        excerpt="In 2023, Scope 1 greenhouse gas emissions reached 280,000 MT CO2e.",
    )
    extractor = EvidenceExtractionAgent()
    facts = extractor.extract_facts([cite1, cite2])
    conflicts = extractor.detect_conflicts(facts)

    assert len(conflicts) > 0
    assert any(c.metric == "scope_1_emissions" for c in conflicts)
    assert any(c.severity == "high" for c in conflicts)


def test_temporal_analysis(tmp_path: Path):
    """Kiểm tra tính toán chuỗi thời gian nhiều năm và tính delta % change."""
    store = Store(tmp_path / "temporal.db")
    store.add_document(
        "doc_2021",
        "Company_2021.pdf",
        [(10, "In 2021, Scope 1 emissions were 500,000 MT CO2e.")],
    )
    store.add_document(
        "doc_2022",
        "Company_2022.pdf",
        [(10, "In 2022, Scope 1 emissions were 450,000 MT CO2e.")],
    )
    store.add_document(
        "doc_2023",
        "Company_2023.pdf",
        [(10, "In 2023, Scope 1 emissions were 400,000 MT CO2e.")],
    )

    agent = ESGAuditAgent()
    res = agent.run_temporal_analysis("Company", store, metric="scope_1_emissions")

    assert res.company == "Company"
    assert len(res.timeline) >= 2
    assert len(res.yoy_changes) >= 1
    # 500k -> 400k is a -20% reduction
    if res.baseline_to_current_change is not None:
        assert res.baseline_to_current_change < 0


def test_cross_company_comparison(tmp_path: Path):
    """Kiểm tra so sánh chéo 2 doanh nghiệp theo ma trận tiêu chí."""
    store = Store(tmp_path / "compare.db")
    store.add_document(
        "corp_a",
        "AlphaCorp_2023.pdf",
        [(5, "AlphaCorp Scope 1 direct greenhouse gas emissions reached 120,000 MT CO2e in 2023.")],
    )
    store.add_document(
        "corp_b",
        "BetaCorp_2023.pdf",
        [(8, "BetaCorp Scope 1 direct greenhouse gas emissions reached 350,000 MT CO2e in 2023.")],
    )

    agent = ESGAuditAgent()
    res = agent.run_comparison(["AlphaCorp", "BetaCorp"], store, criteria_ids=["E_GHG_SCOPE_1_2"])

    assert "AlphaCorp" in res.companies
    assert "BetaCorp" in res.companies
    assert len(res.criteria_matrix) > 0
    row = res.criteria_matrix[0]
    assert "AlphaCorp" in row.values_by_company
    assert "BetaCorp" in row.values_by_company


def test_query_planner_decomposition():
    """Kiểm tra Query Planning Agent phân rã câu hỏi phức tạp thành subqueries và required evidence."""
    planner = QueryPlanningAgent()
    plan = planner.plan(
        "Compare Scope 1 emissions and renewable energy of Boeing and Airbus between 2022 and 2023"
    )

    assert plan.intent == "cross_document_compare"
    assert len(plan.subqueries) >= 3
    assert len(plan.required_evidence) > 0
    assert any("scope" in q.lower() for q in plan.subqueries)
